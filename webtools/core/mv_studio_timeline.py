"""Read native Unity MV tracks and their existing scene events."""
import math
import re
import time
from collections import Counter, defaultdict

from . import game_motion_selection as selection
from . import model_animation as animation

_MAX_SECONDS = 3600
_MAX_TRACKS = 4096
_MAX_EVENTS = 30_000
_MAX_CAMERA_FRAMES = 72_000
_MAX_WARNINGS = 96
_MAX_VALUE_ITEMS = 256
_FOV = 2282594708
# Kept for parses without the timeline's dependency packs (mods, reopen, export).
# A game import resolves these clips in mv_studio_external_clips instead.
EXTERNAL_CLIP_WARNING = "Some original animation clips need their exact companion asset packs."
_PERFORMER_MODEL = re.compile(r"/EntryPoint/Live/Members/Member([1-9][0-9]*)/Model")
_MEMBER_SHAFT = re.compile(r"/EntryPoint/Live/Members/Member([1-9][0-9]*)")
_COMMON = {"m_GameObject", "m_Enabled", "m_Script", "m_Name", "m_PrefabInstance", "m_PrefabAsset"}
_CLIP_TIMING = {
    "m_ClipIn": "clipIn", "m_TimeScale": "timeScale", "m_EaseInDuration": "easeIn",
    "m_EaseOutDuration": "easeOut", "m_BlendInDuration": "blendIn", "m_BlendOutDuration": "blendOut",
    "m_PreExtrapolationMode": "preExtrapolationMode", "m_PostExtrapolationMode": "postExtrapolationMode",
    "m_PreExtrapolationTime": "preExtrapolationTime", "m_PostExtrapolationTime": "postExtrapolationTime",
}
_KINDS = {
    "GroupTrack": "group",
    "MemberLipSyncTrack": "mouth",
    "MemberEyeTrack": "eyes",
    "MemberGazeTrack": "gaze",
    "MemberCheekTrack": "cheek",
    "LiveBloomTrack": "bloom",
    "LiveDepthOfFieldTrack": "dof",
    "LiveDisplayTrack": "display",
    "LiveColoringTrack": "display",
    "LiveSplitScreenTrack": "split",
    "LiveCameraOffsetTrack": "camera",
    "LivePenlightTrack": "crowd",
    "LiveBaseLightTrack": "lighting",
    "LiveMemberAmbientTrack": "lighting",
    "LiveStageAmbientTrack": "lighting",
    "LiveStageSingleAmbientTrack": "lighting",
    "LiveStageEmissiveTrack": "lighting",
    "LiveMemberSpotLightAreaTrack": "lighting",
    "LiveMemberSpotLightShaftTrack": "lighting",
    "LiveRimlightTrack": "lighting",
    "LiveFlareTrack": "lighting",
    "LiveFlashLightTrack": "lighting",
    "CustomControlTrack": "effects",
    "ControlTrack": "effects",
    "ActivationTrack": "stage",
    "LiveMemberCullerTrack": "dance",
    "LiveMemberScalingTrack": "dance",
    "NaviVoiceTrack": "sound",
    "AudioTrack": "sound",
}


class _Warnings:
    def __init__(self):
        self.rows = set()
        self.omitted = 0

    def add(self, text):
        if text in self.rows:
            return
        if len(self.rows) < _MAX_WARNINGS:
            self.rows.add(text)
        else:
            self.omitted += 1

    def result(self):
        notes = sorted(self.rows)
        return notes + ([f"{self.omitted} more timeline warnings."] if self.omitted else [])


def _time(value, field, *, minimum=-_MAX_SECONDS, maximum=_MAX_SECONDS):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"The timeline has an invalid {field}.")
    return float(value)


def _label(value, fallback=""):
    return value[:240] if isinstance(value, str) and value else fallback


def _id(key):
    return f"{key[0]}:{key[1]}"


def _pointer(obj, value):
    if not isinstance(value, dict):
        return None
    try:
        return selection._pointer_key(obj, value)
    except ValueError:
        return None


def _public(value, warnings, depth=0):
    if value is None or isinstance(value, (bool, str)):
        return value[:4096] if isinstance(value, str) else value
    if type(value) is int:
        return value if -(1 << 53) < value < (1 << 53) else str(value)
    if type(value) is float:
        return value if math.isfinite(value) else None
    if depth < 4 and isinstance(value, dict):
        if set(value) == {"m_FileID", "m_PathID"}:
            path_id = value["m_PathID"]
            return {"m_FileID": value["m_FileID"], "m_PathID": str(path_id)}
        if len(value) <= _MAX_VALUE_ITEMS:
            return {key: _public(item, warnings, depth + 1) for key, item in value.items() if isinstance(key, str)}
    if depth < 4 and isinstance(value, (list, tuple)) and len(value) <= _MAX_VALUE_ITEMS:
        return [_public(item, warnings, depth + 1) for item in value]
    warnings.add("Some compound properties are too large or complex to display. Their native data is preserved.")
    return None


def _read(raw, name, deadline):
    import UnityPy
    from .model_viewer import MAX_SOURCE_BYTES, _bounded_bundle, _preflight_bundle, _remaining

    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES
            or not raw.startswith(b"UnityFS\0")):
        raise ValueError("Choose an extracted UnityFS live timeline bundle.")
    _, layout = _preflight_bundle(raw, _with_layout=True)
    try:
        env = UnityPy.load(_bounded_bundle(raw, layout, deadline))
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("The Unity live timeline could not be opened.") from exc
    objects = {}
    scripts = {}
    for obj in env.objects:
        _remaining(deadline)
        key = selection._object_key(obj)
        if key in objects:
            raise ValueError("The timeline has duplicate serialized object identities.")
        objects[key] = obj
        if obj.type.name == "MonoScript":
            scripts[key] = obj.read_typetree().get("m_ClassName", "")
        if len(objects) > selection.MAX_OBJECTS:
            raise ValueError("The live timeline contains too many objects.")
    return env, objects, {"scripts": scripts, "name": name}


def _lineage(key, mono, warnings):
    parts, seen = [], set()
    while key in mono and key not in seen and len(seen) < 256:
        obj, tree, kind = mono[key]
        if kind == "TimelineAsset":
            return key, "/" + "/".join(reversed(parts))
        seen.add(key)
        parts.append(_label(tree.get("m_Name"), kind or "Track"))
        key = _pointer(obj, tree.get("m_Parent"))
    if key in seen:
        warnings.add("A track has a circular native parent reference.")
    return None, "/" + "/".join(reversed(parts))


def _bindings(mono, roots, warnings):
    result = defaultdict(set)
    for key, (obj, tree, kind) in mono.items():
        if kind != "TimelineAssetBindingInfo":
            continue
        timeline = _pointer(obj, tree.get("timelineAsset"))
        if timeline not in roots:
            local = [candidate for candidate in roots if candidate[0] == key[0]]
            if len(local) != 1:
                warnings.add("A timeline binding target could not be resolved.")
                continue
            timeline = local[0]
        for row in tree.get("bindingInfos", []):
            if not isinstance(row, dict):
                continue
            path, target = row.get("playableAssetPath"), row.get("bindObjectPath")
            if isinstance(path, str) and isinstance(target, str) and target:
                result[timeline, path].add(target)
    return result


def _kind(native, path, binding):
    if native in _KINDS:
        return _KINDS[native]
    location = (binding or "").lower()
    text = f"{native} {path}".lower()
    if native == "AnimationTrack":
        if "/cameras/" in location:
            return "camera"
        if _PERFORMER_MODEL.fullmatch(binding or ""):
            return "dance"
        if "/stages/" in location:
            return "effects" if "/effect/" in location else "stage"
    for tokens, kind in (
        (("lip", "mouth"), "mouth"),
        (("audio", "voice", "sound", "music", "cue"), "sound"),
        (("split",), "split"),
        (("crowd", "audience", "penlight"), "crowd"),
        (("display", "screen", "coloring", "colouring"), "display"),
        (("light", "ambient", "flare"), "lighting"),
        (("camera",), "camera"),
        (("prop", "accessory", "accessories"), "props"),
        (("effect", "particle", "fog"), "effects"),
        (("stage",), "stage"),
    ):
        if any(token in text for token in tokens):
            return kind
    return "other"


def _camera_channels(tree, deadline):
    bindings = (tree.get("m_ClipBindingConstant") or {}).get("genericBindings", [])
    curves = animation._packed_curves(tree, deadline)
    channels, offset = {}, 0
    for bind in bindings:
        width = animation._width(bind)
        group, offset = curves[offset:offset + width], offset + width
        channel = _camera_binding(bind)
        if channel and len(group) == width:
            if channel in channels:
                raise ValueError("The camera clip has conflicting channel bindings.")
            channels[channel] = group
            if channel == "euler":
                # GenericBinding.customType is the Unity RotationOrder (SIFAS cameras use 0, XYZ).
                channels["eulerOrder"] = _camera_euler_order(bind)
    if len(curves) != offset or "position" not in channels or not {"rotation", "euler"} & channels.keys():
        raise ValueError("The camera clip has unsupported native channel bindings.")
    return channels


def _camera_euler_order(binding):
    try:
        return animation.euler_order(binding.get("customType", animation.DEFAULT_EULER_ORDER))
    except animation.AnimationError as error:
        raise ValueError("The camera clip has an unsupported Euler rotation order.") from error


def _camera_binding(binding):
    if binding.get("path") or binding.get("isPPtrCurve"):
        return None
    typ, attr = binding.get("typeID", binding.get("classID")), binding.get("attribute")
    if typ == 4:
        return {1: "position", 2: "rotation", 4: "euler"}.get(attr)
    if typ == 114 and attr == _FOV:
        return "fov"
    return None


def _camera_frames(obj, clip, duration, deadline, remaining_frames, euler_order=None):
    """Sample a camera shot. `euler_order` overrides an Euler binding's own order (legacy project checks only)."""
    if duration <= 0:
        return []
    tree = obj.read_typetree()
    rate = _time(tree.get("m_SampleRate", 60), "camera sample rate", minimum=1, maximum=1000)
    speed = _time(clip.get("m_TimeScale", 1), "camera clip speed", minimum=.000001, maximum=100)
    rate = min(60, max(1, rate * speed))
    count = math.ceil(duration * rate - 1e-9) + 1
    if count > remaining_frames:
        raise ValueError("The project camera sample limit was reached.")
    channels = _camera_channels(tree, deadline)
    if euler_order is None:
        euler_order = channels.get("eulerOrder", animation.DEFAULT_EULER_ORDER)
    muscle = tree.get("m_MuscleClip") or {}
    first = _time(muscle.get("m_StartTime", 0), "camera source start")
    last = _time(muscle.get("m_StopTime", first), "camera source end", minimum=first)
    source_offset = _time(clip.get("m_ClipIn", 0), "camera source offset")
    evaluate = animation._evaluate
    result = []
    for index in range(count):
        if not index % 128:
            animation._check(deadline)
        local = min(duration, index / rate)
        stamp = max(first, min(last, first + source_offset + local * speed))
        position = [animation._finite(evaluate(value, stamp)) for value in channels["position"]]
        orientation = channels.get("rotation") or channels["euler"]
        rotation = animation._quaternion([evaluate(value, stamp) for value in orientation],
                                         euler="rotation" not in channels, order=euler_order)
        # The viewer helper returns glTF handedness. This descriptor exposes
        # Unity coordinates, keeping handedness conversion with the renderer.
        rotation[1] = -rotation[1]
        rotation[2] = -rotation[2]
        fov = animation._finite(evaluate(channels["fov"][0], stamp)) if "fov" in channels else None
        result.append({"time": local, "position": position, "rotation": rotation, "fov": fov})
    return result


def _event(track_obj, clip, key, index, kind, objects, mono, references, animations, deadline, warnings, remaining_frames):
    if not isinstance(clip, dict):
        raise ValueError("A native timeline event is not a clip record.")
    start = _time(clip.get("m_Start", 0), "clip start")
    duration = _time(clip.get("m_Duration", 0), "clip duration", minimum=0)
    values = {label: _public(clip[field], warnings) for field, label in _CLIP_TIMING.items() if field in clip}
    editable = list(values)
    if kind in {"crowd", "lighting", "dof"} or mono[key][2] in {"LiveColoringTrack", "LiveDisplayTrack", "LiveMemberScalingTrack"}:
        for field, label in (("m_MixInCurve", "mixIn"), ("m_MixOutCurve", "mixOut")):
            curve = clip.get(field)
            if isinstance(curve, dict) and curve.get("m_Curve"):
                values[label] = _public(curve["m_Curve"], warnings)
    asset = _pointer(track_obj, clip.get("m_Asset"))
    label = _label(clip.get("m_DisplayName"), "Clip " + str(index + 1))
    if asset is not None:
        values["asset"] = _id(asset)
    elif isinstance(clip.get("m_Asset"), dict) and clip["m_Asset"].get("m_PathID"):
        warnings.add("Some clips have unresolved native asset references. Their timing is preserved.")
    playable = mono.get(asset)
    if playable is not None:
        playable_obj, tree, playable_class = playable
        values["playableClass"] = playable_class or "MonoBehaviour"
        for field, value in tree.items():
            if field not in _COMMON:
                values[field] = _public(value, warnings)
        if playable_class == "AnimationPlayableAsset":
            animation_key = _pointer(playable_obj, tree.get("m_Clip"))
            animation_obj = objects.get(animation_key)
            if animation_key is not None:
                values["animation"] = _id(animation_key)
            if animation_obj is not None and animation_obj.type.name == "AnimationClip":
                values["animationName"] = _label(animation_obj.peek_name())
                if kind == "camera":
                    try:
                        values["keyframes"] = _camera_frames(animation_obj, clip, duration, deadline, remaining_frames)
                        if (values["keyframes"] and references[asset] == 1 and animations[animation_key] == 1
                                and values.get("clipIn", 0) == 0 and values.get("timeScale", 1) == 1):
                            editable.append("keyframes")
                    except (ValueError, KeyError, TypeError) as error:
                        warnings.add(f"Camera clip '{label}' could not be sampled: {error}")
            elif animation_key is not None:
                warnings.add(EXTERNAL_CLIP_WARNING)
        elif references[asset] == 1:
            editable.extend(sorted(_EDITABLE_VALUES.get(playable_class, set()) & values.keys()))
    elif asset is not None:
        asset_obj = objects.get(asset)
        if asset_obj is None:
            warnings.add("Some clips reference an asset outside this bundle. Their timing is preserved.")
        else:
            values["playableClass"] = asset_obj.type.name
    return {"id": f"{_id(key)}:{index}", "start": start, "duration": duration, "label": label,
            "values": values, "editableValues": editable}


def _shaft_slot(track):
    binding = track.get("binding")
    if track.get("nativeClass") == "LiveMemberSpotLightShaftTrack" and isinstance(binding, str):
        target = _MEMBER_SHAFT.fullmatch(binding)
        if target:
            return int(target[1])
    return None


def parse_timeline(raw: bytes, name: str, *, preview_split=False, preview_stage_motion=False,
                   preview_member_shafts=False, preview_stage_title=False, preview_stage_particles=False,
                   preview_stage_ribbons=False, preview_stage_spotlight=False, preview_stage_butterfly=False,
                   preview_stage_rain=False, preview_stage_leaves=False, preview_stage_momiji=False, preview_stage_confetti=False,
                   preview_stage_glow=False, preview_stage_lens=False, preview_stage_speed_back=False,
                   preview_stage_display_lights=False, preview_stage_falling_effects=False,
                   preview_stage_break=False, preview_stage_finale_floor=False,
                   preview_stage_sparks_a=False, preview_stage_sparks_b=False, preview_stage_sparks_roop=False,
                   preview_particle_systems=False, preview_control_prefabs=False) -> dict:
    """Return scene tracks, timing and preview samples without changing the bundle."""
    from . import mv_studio_progress
    from .model_viewer import _remaining

    effects = [flag for flag in (preview_split, preview_stage_motion, preview_stage_title, preview_stage_particles,
                                 preview_stage_ribbons, preview_stage_spotlight, preview_stage_butterfly, preview_stage_rain,
                                 preview_stage_leaves, preview_stage_momiji, preview_stage_confetti, preview_stage_glow,
                                 preview_stage_lens, preview_stage_speed_back, preview_stage_display_lights,
                                 preview_stage_falling_effects, preview_stage_break, preview_stage_finale_floor,
                                 preview_stage_sparks_a, preview_stage_sparks_b, preview_stage_sparks_roop,
                                 preview_particle_systems, preview_control_prefabs) if flag]
    started = 0

    def part():
        # Progress of an MV import (a no-op otherwise): stage effect readers begun so far.
        nonlocal started
        mv_studio_progress.tick("effects", started, len(effects), force=not started)
        started += 1

    mv_studio_progress.tick("bundle", force=True)
    deadline = time.monotonic() + 45
    _, objects, source = _read(raw, name, deadline)
    mv_studio_progress.tick("tracks", force=True)
    warnings = _Warnings()
    mono, roots = {}, {}
    for key, obj in objects.items():
        if obj.type.name != "MonoBehaviour":
            continue
        _remaining(deadline)
        try:
            tree = obj.read_typetree()
        except (ValueError, TypeError, KeyError):
            warnings.add("An original component has no readable type tree and is preserved as-is.")
            continue
        native = selection._class(source, obj, tree)
        mono[key] = obj, tree, native
        if native == "TimelineAsset":
            roots[key] = tree
    if not roots:
        raise ValueError("The selected bundle has no native TimelineAsset.")
    if len(roots) > 1:
        warnings.add("The bundle contains more than one timeline. Their tracks retain separate native identities.")
    bindings = _bindings(mono, roots, warnings)
    references, animations = Counter(), Counter()
    for obj, tree, native in mono.values():
        for clip in tree.get("m_Clips", []):
            if isinstance(clip, dict):
                references[_pointer(obj, clip.get("m_Asset"))] += 1
        if native == "AnimationPlayableAsset":
            animations[_pointer(obj, tree.get("m_Clip"))] += 1
    tracks, events_count, camera_frames = [], 0, 0
    duration = max((_time(tree.get("m_FixedDuration", 0), "fixed duration", minimum=0)
                    for tree in roots.values()), default=0)

    def append(key):
        nonlocal duration, events_count, camera_frames
        _remaining(deadline)
        obj, tree, native = mono[key]
        clips = tree.get("m_Clips")
        if clips is None and native != "GroupTrack":
            return
        if clips is None:
            clips = []
        if not isinstance(clips, list):
            raise ValueError("A native timeline track has an invalid clip list.")
        events_count += len(clips)
        if len(tracks) >= _MAX_TRACKS or events_count > _MAX_EVENTS:
            raise ValueError("The native timeline has too many tracks or clips.")
        timeline, path = _lineage(key, mono, warnings)
        if _pointer(obj, tree.get("m_InfiniteClip")) is not None:
            warnings.add(f"Track '{path}' has an unbounded animation source that needs native preview.")
        markers = tree.get("m_Markers")
        if isinstance(markers, dict) and markers.get("m_Objects"):
            warnings.add(f"Track '{path}' contains native markers that are preserved in the bundle.")
        if timeline is None:
            warnings.add("Some native tracks refer to a missing timeline parent.")
        targets = sorted(bindings.get((timeline, path), ()))
        if len(targets) > 1:
            warnings.add(f"Track '{path}' has multiple native binding targets.")
        binding = targets[0] if len(targets) == 1 else None
        kind = _kind(native, path, binding)
        events = []
        for index, clip in enumerate(clips):
            _remaining(deadline)
            try:
                event = _event(obj, clip, key, index, kind, objects, mono, references, animations, deadline, warnings,
                               _MAX_CAMERA_FRAMES - camera_frames)
            except (TypeError, ValueError, KeyError) as error:
                if time.monotonic() >= deadline:
                    raise
                warnings.add(f"Track '{path}', clip {index + 1}: {error}")
                continue
            camera_frames += len(event["values"].get("keyframes", []))
            events.append(event)
            duration = max(duration, event["start"] + event["duration"])
        result = {"id": _id(key), "kind": kind, "label": path.lstrip("/"), "events": events,
                  "nativeClass": native or "UnknownTrack", "muted": bool(tree.get("m_Muted"))}
        if binding is not None:
            result["binding"] = binding
        elif targets:
            result["bindings"] = targets
        if preview_member_shafts:
            slot = _shaft_slot(result)
            if slot is not None:
                result["shaftSlot"] = slot
        tracks.append(result)

    ordered, seen = [], set()
    stack = []
    for root in reversed(list(roots)):
        obj, tree, _ = mono[root]
        stack.extend(_pointer(obj, pointer) for pointer in reversed(tree.get("m_Tracks", [])))
    while stack:
        key = stack.pop()
        if key in seen or key not in mono:
            continue
        seen.add(key)
        ordered.append(key)
        obj, tree, _ = mono[key]
        stack.extend(_pointer(obj, pointer) for pointer in reversed(tree.get("m_Children", [])))
    for key in ordered:
        append(key)
    for key in mono:
        if key not in seen:
            append(key)
    if not tracks:
        raise ValueError("The native TimelineAsset has no readable tracks.")
    result = {"duration": duration, "tracks": tracks, "warnings": warnings.result()}
    if preview_split:
        part()
        from . import mv_studio_split

        split = mv_studio_split.read(objects, mono, tracks, deadline)
        if split:
            result["splitScreen"] = split
    if preview_stage_motion:
        part()
        from . import mv_studio_stage_motion

        stage_motion = mv_studio_stage_motion.read(objects, mono, tracks, deadline)
        if stage_motion:
            result["stageMotion"] = stage_motion
    if preview_stage_title:
        part()
        from . import mv_studio_stage_title

        stage_title = mv_studio_stage_title.read(objects, mono, tracks, deadline)
        if stage_title:
            result["stageTitle"] = stage_title
    if preview_stage_particles:
        part()
        from . import mv_studio_stage_particles

        stage_particles = mv_studio_stage_particles.read(objects, mono, tracks, deadline)
        if stage_particles:
            result["stageParticles"] = stage_particles
    if preview_stage_ribbons:
        part()
        from . import mv_studio_stage_ribbons

        stage_ribbons = mv_studio_stage_ribbons.read(objects, mono, tracks, deadline)
        if stage_ribbons:
            result["stageRibbons"] = stage_ribbons
    if preview_stage_spotlight:
        part()
        from . import mv_studio_stage_spotlight

        stage_spotlight = mv_studio_stage_spotlight.read(objects, mono, tracks, deadline)
        if stage_spotlight:
            result["stageSpotlight"] = stage_spotlight
    if preview_stage_butterfly:
        part()
        from . import mv_studio_butterfly

        butterfly = mv_studio_butterfly.read(objects, mono, tracks, deadline)
        if butterfly:
            result["stageButterfly"] = butterfly
    if preview_stage_rain:
        part()
        from . import mv_studio_rain

        rain = mv_studio_rain.read(objects, mono, tracks, deadline)
        if rain:
            result["stageRain"] = rain
    if preview_stage_leaves:
        part()
        from . import mv_studio_leaves

        leaves = mv_studio_leaves.read(objects, mono, tracks, deadline)
        if leaves:
            result["stageLeaves"] = leaves
    if preview_stage_momiji:
        part()
        from . import mv_studio_momiji

        momiji = mv_studio_momiji.read(objects, mono, tracks, deadline)
        if momiji:
            result["stageMomiji"] = momiji
    if preview_stage_confetti:
        part()
        from . import mv_studio_confetti

        confetti = mv_studio_confetti.read(objects, mono, tracks, deadline)
        if confetti:
            result["stageConfetti"] = confetti
    if preview_stage_glow:
        part()
        from . import mv_studio_stage_glow

        glow = mv_studio_stage_glow.read(objects, mono, tracks, deadline)
        if glow:
            result["stageGlow"] = glow
    if preview_stage_lens:
        part()
        from . import mv_studio_stage_lens

        lens = mv_studio_stage_lens.read(objects, mono, tracks, deadline)
        if lens:
            result["stageLensFlare"] = lens
    atlas_refs = {} if (preview_stage_falling_effects or preview_stage_break or preview_stage_finale_floor
                        or preview_stage_sparks_a or preview_stage_sparks_b or preview_stage_sparks_roop) else None
    if preview_stage_speed_back:
        part()
        from . import mv_studio_speed_back

        speed_back = mv_studio_speed_back.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if speed_back:
            result["stageSpeedBack"] = speed_back
    if preview_stage_display_lights:
        part()
        from . import mv_studio_display_lights

        display_lights = mv_studio_display_lights.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if display_lights:
            result["stageDisplayLights"] = display_lights
    if preview_stage_falling_effects:
        part()
        from . import mv_studio_falling_display

        falling = mv_studio_falling_display.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if falling:
            result["stageFallingEffects"] = falling
    if preview_stage_break:
        part()
        from . import mv_studio_stage_break

        stage_break = mv_studio_stage_break.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if stage_break:
            result["stageBreak"] = stage_break
    if preview_stage_finale_floor:
        part()
        from . import mv_studio_finale_floor

        finale_floor = mv_studio_finale_floor.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if finale_floor:
            result["stageFinaleFloor"] = finale_floor
    if preview_stage_sparks_a:
        part()
        from . import mv_studio_sparks_a

        sparks_a = mv_studio_sparks_a.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_a:
            result["stageSparksA"] = sparks_a
    if preview_stage_sparks_b:
        part()
        from . import mv_studio_sparks_b

        sparks_b = mv_studio_sparks_b.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_b:
            result["stageSparksB"] = sparks_b
    if preview_stage_sparks_roop:
        part()
        from . import mv_studio_sparks_roop

        sparks_roop = mv_studio_sparks_roop.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_roop:
            result["stageSparksRoop"] = sparks_roop
    outcomes = {} if preview_particle_systems else None
    textures, shared = None, 0
    if preview_control_prefabs:
        from . import mv_studio_control_prefabs as control_prefabs

        legacy = control_prefabs.claims(result)
    if preview_particle_systems:
        part()
        from . import mv_studio_particle_systems as particle_systems

        # One texture table for the particle systems and the prefab meshes of the same clones.
        textures = particle_systems._Textures(deadline)
        # After the per-prefab readers, so a cue one of them draws is not drawn twice.
        systems = particle_systems.read(objects, mono, tracks, deadline, claimed=particle_systems.claimed_cues(result),
                                        outcomes=outcomes, textures=textures)
        note = particle_systems.warning(systems, meshes_elsewhere=preview_control_prefabs)
        if note:
            result["warnings"].append(note)
        if systems and systems["cues"]:
            result["stageParticleSystems"] = systems
            shared = len(systems["textures"])
    if preview_control_prefabs:
        part()
        # The meshes of the same clones, and one coverage row for every CustomControlClip.
        prefabs, ledger = control_prefabs.read(objects, mono, tracks, deadline, claimed=legacy, outcomes=outcomes,
                                               textures=textures, shared=shared)
        note = control_prefabs.warning(ledger)
        if note:
            result["warnings"].append(note)
        if prefabs:
            result["stageControlPrefabs"] = prefabs
        if ledger:
            result["controlCoverage"] = ledger
    return result


# Only values verified in the native track and playable schemas are writable.
# Names, asset indices and pointers into game-specific materials/prefabs remain
# read-only unless the actual linked resource is available and validated.
_EDITABLE_VALUES = {
    "MemberLipSyncClip": {"paramName", "index", "weight"},
    "MemberEyeClip": {"index", "weight"},
    "MemberGazeClip": {"target", "weightForDirection"},
    "MemberCheekClip": {"cheekType", "intensity"},
    "LiveBloomClip": {"intensity", "threshold", "softKnee", "radius", "antiFlicker"},
    "LiveDepthOfFieldClip": {"focusDistance", "aperture", "focalLength", "useCameraFov", "antiAura",
                             "kernelSize", "useMemberDistance", "bodyPart", "memberPosition", "cameraAutoDistanceMode",
                             "focusTransitionTime"},
    "LiveBaseLightClip": {"ambientColor", "ambientTintColor", "rimlightColor", "rimlightIntensity",
                         "rimlightSharpness", "rimlightDirection", "ambientColorType", "rimlightColorType",
                         "ambientMemberPosition", "rimlightMemberPosition"},
    "LiveMemberAmbientClip": {"color", "tintColor", "colorSpecifiedType", "memberPosition"},
    "LiveStageAmbientClip": {"color", "tintColor", "blendColor", "colorSpecifiedType", "memberPosition"},
    "LiveStageSingleAmbientClip": {"color", "tintColor", "blendColor", "colorSpecifiedType", "memberPosition"},
    "LiveStageEmissiveClip": {"color", "intensity", "colorSpecifiedType", "memberPosition"},
    "LiveMemberSpotLightAreaClip": {"color", "colorSpecifiedType", "memberPosition"},
    "LiveMemberSpotLightShaftClip": {"color", "scale", "offsetHeight", "smoothTime", "colorSpecifiedType",
                                     "drawObjectIndex", "memberPosition"},
    "LiveRimlightClip": {"color", "intensity", "sharpness", "direction", "colorSpecifiedType", "memberPosition"},
    "LiveFlareClip": {"color", "center", "intensity", "smoothness", "roundness", "rounded", "colorSpecifiedType",
                      "memberPosition"},
    "LiveFlashLightClip": {"tintColor", "speed", "colorSpecifiedType", "status", "memberPosition"},
    "LiveDisplayClip": {"scrollSpeed", "ambientColor", "materialIndex"},
    "LiveColoringClip": {"shift", "tintColor", "speed", "textureIndex"},
    "LiveCameraOffsetClip": {"intensity", "memberPosition"},
    "LivePenlightClip": {"tintColor", "fogIntensity", "randomBrightness", "beatLength", "beatOffset",
                         "randomDelay", "randomUp", "randomSwingIntensity", "swingMode", "position", "memberColors",
                         "basicYZMoveY", "basicYZMoveZ", "basicYZRotateZ", "basicYZSwingBackZ", "basicYZSwingPowerZ",
                         "growthYZMoveY", "growthYZMoveZ", "growthYZRotateZ", "growthYZSwingBackZ", "growthYZSwingPowerZ",
                         "growthYZSwingBottomZ", "basicXRotateX", "basicXMoveX", "basicXMoveY", "simpleXZRotateX",
                         "simpleXZRotateZ"},
    "CustomControlClip": {"weight", "offset"},
    "LiveMemberScalingClip": {"intensity"},
    "LivePropAmbientClip": {"color", "tintColor", "colorSpecifiedType", "memberPosition"},
    "LivePropRimlightClip": {"color", "intensity", "sharpness", "direction", "colorSpecifiedType", "memberPosition"},
}
# Every class above whose clips pick their colour source with colorSpecifiedType
# (0 custom, 1 member, 2 original member) is resolved by the preview's
# MVStudioLighting.memberColor, so the choice previews as it exports.
_COLOR_SOURCE_CLASSES = frozenset(native for native, fields in _EDITABLE_VALUES.items() if "colorSpecifiedType" in fields)
_LIMITED_VALUES = {
    ("MemberLipSyncClip", "index"): (0, 4096),
    ("MemberEyeClip", "index"): (0, 4096),
    ("MemberGazeClip", "target"): (0, 256),
    ("MemberCheekClip", "cheekType"): (0, 1),
    **{(native, "colorSpecifiedType"): (0, 2) for native in _COLOR_SOURCE_CLASSES},
    ("LiveDepthOfFieldClip", "kernelSize"): (0, 3),
    ("LiveDepthOfFieldClip", "useMemberDistance"): (0, 1),
    # LiveDepthOfFieldMixer.CalcFocusDistance (0x29237fc): 1 the nearest member, 2 the member nearest
    # the view axis, anything else memberPosition (mv-studio-dof-focus.js memberFocus).
    ("LiveDepthOfFieldClip", "cameraAutoDistanceMode"): (0, 2),
    ("LiveBaseLightClip", "ambientColorType"): (0, 2),
    ("LiveBaseLightClip", "rimlightColorType"): (0, 2),
    ("LiveFlashLightClip", "status"): (0, 2),
    # AS/Penlight ships one variant per swing keyword (_SWING_MODE_STOP, _BASIC_YZ, _GROWTH_YZ,
    # _BASIC_X, _SIMPLE_XZ); stock clips use 0 to 3 (mv-studio-penlight.js uMode).
    ("LivePenlightClip", "swingMode"): (0, 4),
}
# Values that name a member slot: a changed one must be a slot this timeline binds a performer
# model to (_PERFORMER_MODEL). The client reads Members[slot - 1] behind a bounds check and throws
# for a missing member (LiveDepthOfFieldMixer.CalcFocusDistance 0x2924148), and the member colour
# and camera height lookups read the same members.
_MEMBER_POSITIONS = frozenset(
    {(native, "memberPosition") for native in _COLOR_SOURCE_CLASSES | {"LiveDepthOfFieldClip", "LiveCameraOffsetClip"}}
    | {("LiveBaseLightClip", "ambientMemberPosition"), ("LiveBaseLightClip", "rimlightMemberPosition")})
MEMBER_SLOT = "Choose a member this MV has."
# Float fields with a native range (other floats take any value within +-1e6).
_FLOAT_RANGES = {
    ("LiveDepthOfFieldClip", "focusTransitionTime"): (0, 60),
    # AS/Penlight swing shapes (mv-studio-penlight.js): moves in metres, tilts in radians, the
    # rest offsets, and two exponents of a 0..1 wave (negative would divide by zero at 0).
    # growthYZSwingBottomZ splits the growth cycle (cycle / z and (cycle - z) / (1 - z)), so it stays
    # inside 0..1. growthYZSwingPowerY stays read-only: the preview reads LivePenlightMixer as passing
    # it on multiplied by its reset output (mv-studio-penlight.js uGrowthShape.x = 0), so an edit would
    # change nothing in the game (not re-read for this change).
    **{("LivePenlightClip", field): (-10, 10) for field in (
        "basicYZMoveY", "basicYZMoveZ", "basicYZRotateZ", "basicYZSwingBackZ", "growthYZMoveY", "growthYZMoveZ",
        "growthYZRotateZ", "growthYZSwingBackZ", "basicXRotateX", "basicXMoveX", "basicXMoveY", "simpleXZRotateX",
        "simpleXZRotateZ")},
    ("LivePenlightClip", "basicYZSwingPowerZ"): (0, 100),
    ("LivePenlightClip", "growthYZSwingPowerZ"): (0, 100),
    ("LivePenlightClip", "growthYZSwingBottomZ"): (.01, .99),
}
# LivePenlightClip.memberColors: one entry per palette slot; the length stays (the client sizes the
# palette from it), each entry keeps its fields.
_MEMBER_COLOR_KEYS = frozenset({"color", "colorSpecifiedType", "memberPosition"})
# Indices into game-side lists the bundle does not describe (coloring textures,
# display materials, shaft draw objects, BodyPartManager parts): a revision may
# only pick a value the original MV already uses for that field, on the same
# track or anywhere in the timeline.
_OBSERVED_VALUES = {
    ("LiveColoringClip", "textureIndex"): "track",
    ("LiveDisplayClip", "materialIndex"): "track",
    ("LiveMemberSpotLightShaftClip", "drawObjectIndex"): "track",
    ("LiveDepthOfFieldClip", "bodyPart"): "timeline",
}
# Changed values that only work for a clip whose member position (as revised) is a member slot:
# (values, message, the field holding that position).
_COLOUR_MEMBER = "This colour source needs the clip's member position to be 1 to 12."
_MEMBER_SLOT_VALUES = {
    **{(native, "colorSpecifiedType"): ({1, 2}, _COLOUR_MEMBER, "memberPosition") for native in _COLOR_SOURCE_CLASSES},
    ("LiveBaseLightClip", "ambientColorType"): ({1, 2}, _COLOUR_MEMBER, "ambientMemberPosition"),
    ("LiveBaseLightClip", "rimlightColorType"): ({1, 2}, _COLOUR_MEMBER, "rimlightMemberPosition"),
    ("LiveDepthOfFieldClip", "useMemberDistance"): ({1}, "Member focus needs the clip's member position to be 1 to 12.",
                                                    "memberPosition"),
}
_TIMING_NATIVE = {label: field for field, label in _CLIP_TIMING.items()}
# Track fields an export writes into the track's own MonoBehaviour, for a track whose
# exportable_track_fields lists them (mv_studio_register.normalize sends every other
# track field back to the original).
EXPORTABLE_TRACK_FIELDS = ("muted",)
# The client compiles each output track by its own m_Muted (TrackAsset.compilable 0x35b8c00 reads
# +0x19; a GroupTrack is never compiled), so a GroupTrack's mute changes nothing in the game.
GROUP_MUTE = "A group track's mute does not reach the game. Mute the tracks inside it."
# LiveQualityOperator decides the mute of every direct child track of these category groups (GL
# 3.12.0 libil2cpp): director setup (0x2924cdc) calls 0x20f3a00, which runs ApplyLiveQualityTo*
# (0x20f2788, 0x20f2a98, 0x20f2b70 StageEffect, 0x20f3164 MemberEffect, 0x20f331c PropEffect). Each
# fills {category: !option} and 0x20f28a0 calls ApplyMuteToChildTracks (0x20f348c) on every category
# group it finds; that calls ApplyMuteToTrack (0x20f30e8) on each direct child, and with muted false
# it calls TrackAsset.set_muted(false) (0x35d10e8). So an option that is on unmutes these tracks and one
# that is off mutes them: their own m_Muted never reaches the game. Tracks one group deeper keep theirs.
# StageEffect lists its ten categories by name (mv_studio_stage_motion._STAGE_QUALITY). The names in
# the other four tables were not read (1, 1, 4 and 3 keys; every category these MVs have there fits one
# of them), so every category under those roots counts.
_QUALITY_CATEGORIES = {
    "StageEffect": frozenset({"post", "ambient", "animation", "coloring", "control", "flashlight", "display",
                              "audience", "emissive", "overlayeffect"}),
    "MemberEffect": None, "PropEffect": None, "GlobalEffect": None, "MotionMisc": None,
}
QUALITY_MUTE = "The game's quality settings turn this track on and off, so its mute does not reach the game."


def quality_category(label):
    """The normalized name of the quality category group a track sits directly in, or None.

    ``label`` is the parsed track path <root>/<difficulty>/<category>/<track>; the client matches the
    category name without spaces and lower-cased (NormalizeTrackName). No stock group or track name
    contains "/"."""
    parts = label.split("/") if isinstance(label, str) else []
    if len(parts) != 4 or parts[0] not in _QUALITY_CATEGORIES:
        return None
    category = parts[2].replace(" ", "").lower()
    names = _QUALITY_CATEGORIES[parts[0]]
    return category if names is None or category in names else None


def track_mute_refusal(track):
    """Why a mute of this parsed track does not reach the game, or None when it does."""
    if not isinstance(track, dict) or track.get("nativeClass") == "GroupTrack":
        return GROUP_MUTE
    if quality_category(track.get("label")) is not None:
        return QUALITY_MUTE
    return None


def exportable_track_fields(track):
    """The EXPORTABLE_TRACK_FIELDS an export writes for this parsed (original) track."""
    return () if track_mute_refusal(track) else EXPORTABLE_TRACK_FIELDS


def _index_rows(items, name):
    if not isinstance(items, list) or len(items) > _MAX_EVENTS:
        raise ValueError(f"The revised project has an invalid {name} list.")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in result:
            raise ValueError(f"The revised project has duplicate or invalid {name} identities.")
        result[item["id"]] = item
    return result


def _changes(original, revised):
    if not isinstance(revised, dict) or set(revised) != set(original):
        raise ValueError("The revision no longer matches the original timeline.")
    if revised["warnings"] != original["warnings"]:
        raise ValueError("Timeline diagnostics are read-only in native exports.")
    _time(revised["duration"], "timeline duration", minimum=0, maximum=2 * _MAX_SECONDS)
    old_tracks = _index_rows(original["tracks"], "track")
    new_tracks = _index_rows(revised["tracks"], "track")
    if list(old_tracks) != list(new_tracks):
        raise ValueError("Native export can edit existing tracks in their original order only.")
    changes = []
    last_event_end = 0.
    for identity, before in old_tracks.items():
        after = new_tracks[identity]
        fixed = lambda track: {k: v for k, v in track.items() if k != "events" and k not in EXPORTABLE_TRACK_FIELDS}  # noqa: E731
        if before.keys() != after.keys() or fixed(before) != fixed(after):
            raise ValueError("Track identity, binding, and original metadata are read-only in native exports.")
        _track_fields(before, after)
        old_events = _index_rows(before["events"], "event")
        new_events = _index_rows(after["events"], "event")
        if list(old_events) != list(new_events):
            raise ValueError("Native export can edit existing clip slots in their original order only.")
        for event_id, old in old_events.items():
            new = new_events[event_id]
            last_event_end = max(last_event_end,
                _time(new.get("start"), "clip start") + _time(new.get("duration"), "clip duration", minimum=0))
            if new == old:
                continue
            if set(new) != set(old) or not isinstance(new["values"], dict) or new["values"].keys() != old["values"].keys():
                raise ValueError("The revision cannot replace a native clip's original identities or fields.")
            if new["editableValues"] != old["editableValues"]:
                raise ValueError("The revision cannot change which native clip fields are editable.")
            index = int(event_id.rsplit(":", 1)[1])
            changes.append((identity, before["kind"], index, old, new))
    if revised["duration"] != original["duration"] and (not changes or revised["duration"] != last_event_end):
        raise ValueError("Change the original clip timings to set the native timeline duration.")
    return changes


def _track_fields(before, after):
    """[(field, value)] of the EXPORTABLE_TRACK_FIELDS ``after`` changes on one track, or ValueError
    when the change cannot reach the game (a GroupTrack, a quality category's track) or is not a bool."""
    result = []
    for field in EXPORTABLE_TRACK_FIELDS:
        if field not in before or after.get(field) == before[field]:
            continue
        if type(after.get(field)) is not bool:
            raise ValueError("A track mute must be on or off.")
        refusal = track_mute_refusal(before)
        if refusal:
            raise ValueError(refusal)
        result.append((field, after[field]))
    return result


def _track_changes(original, revised):
    """[(track id, field, value)] for a revision _changes accepted."""
    revised_tracks = _index_rows(revised["tracks"], "track")
    return [(track["id"], field, value) for track in original["tracks"]
            for field, value in _track_fields(track, revised_tracks[track["id"]])]


def _replace_value(native, value, field):
    if type(native) is bool:
        if type(value) is bool:
            return value
    elif type(native) is int:
        if type(value) is int and -(1 << 31) <= value < (1 << 31):
            return value
    elif type(native) is float:
        return _time(value, field, minimum=-1_000_000, maximum=1_000_000)
    elif isinstance(native, str):
        if isinstance(value, str) and len(value) <= 120 and "\0" not in value:
            return value
    elif isinstance(native, dict) and set(native) in ({"x", "y"}, {"x", "y", "z"}, {"x", "y", "z", "w"}, {"r", "g", "b", "a"}):
        if isinstance(value, dict) and value.keys() == native.keys():
            return {key: _replace_value(native[key], value[key], field) for key in native}
    raise ValueError(f"'{field}' is not a supported native value for this clip.")


def _set_timing(clip, field, value):
    if field in ("preExtrapolationMode", "postExtrapolationMode"):
        if type(value) is not int or not 0 <= value <= 4:
            raise ValueError("Choose a supported native extrapolation mode.")
    elif field == "timeScale":
        value = _time(value, field, minimum=.000001, maximum=100)
    else:
        value = _time(value, field, minimum=-1 if field in ("blendIn", "blendOut") else 0)
    clip[_TIMING_NATIVE[field]] = value


def _member_colors(native, value):
    """A revised LivePenlightClip.memberColors: the same length and fields; an entry takes a colour, a
    changed colour source 0..2 and a changed member slot 1..12 (_check_values checks the slot against
    the MV). An unchanged source or slot stays as stock has it (custom-colour entries may hold 0)."""
    if (not isinstance(native, list) or not isinstance(value, list) or len(value) != len(native)
            or any(not isinstance(entry, dict) or entry.keys() != _MEMBER_COLOR_KEYS for entry in (*native, *value))):
        raise ValueError("Keep the penlight colour list's length and fields.")
    result = []
    for old, new in zip(native, value):
        if new == old:
            result.append(old)
            continue
        kind, slot = new["colorSpecifiedType"], new["memberPosition"]
        if type(kind) is not int or kind != old["colorSpecifiedType"] and not 0 <= kind <= 2:
            raise ValueError("'colorSpecifiedType' is outside the supported native range.")
        if type(slot) is not int or slot != old["memberPosition"] and not 1 <= slot <= 12:
            raise ValueError(MEMBER_SLOT)
        result.append({key: _replace_value(old[key], new[key], "memberColors") for key in old})
    return result


def _set_playable_value(tree, native, field, value):
    if native == "LivePenlightClip" and field == "memberColors":
        tree[field] = _member_colors(tree[field], value)
        return
    bounds = _LIMITED_VALUES.get((native, field))
    if bounds and (type(value) is not int or not bounds[0] <= value <= bounds[1]):
        raise ValueError(f"'{field}' is outside the supported native range.")
    if (native, field) in _MEMBER_POSITIONS and (type(value) is not int or not 1 <= value <= 12):
        raise ValueError(MEMBER_SLOT)
    if (field in ("weight", "weightForDirection")
            or native in ("MemberCheekClip", "LiveMemberScalingClip") and field == "intensity"):
        value = _time(value, field, minimum=0, maximum=1)
    floats = _FLOAT_RANGES.get((native, field))
    if floats:
        value = _time(value, field, minimum=floats[0], maximum=floats[1])
    tree[field] = _replace_value(tree[field], value, field)


def _value_key(value):
    import json

    return json.dumps(value, sort_keys=True)


def performer_slots(tracks):
    """The member slots a parsed timeline binds a performer model to (Members/Member<n>/Model)."""
    slots = set()
    for track in tracks:
        bindings = [track.get("binding"), *(track.get("bindings") or ())] if isinstance(track, dict) else ()
        for binding in bindings:
            match = _PERFORMER_MODEL.fullmatch(binding) if isinstance(binding, str) else None
            if match:
                slots.add(int(match[1]))
    return frozenset(slots)


def _check_member_colors(before, after, slots):
    """A changed penlight palette entry names a performer slot, and a member colour source needs a
    member slot; malformed lists are left to _member_colors."""
    if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(after):
        return
    for old, new in zip(before, after):
        if not isinstance(old, dict) or not isinstance(new, dict) or new == old:
            continue
        slot = new.get("memberPosition")
        if slot != old.get("memberPosition") and not (type(slot) is int and slot in slots):
            raise ValueError(MEMBER_SLOT)
        kind = new.get("colorSpecifiedType")
        if (kind != old.get("colorSpecifiedType") and type(kind) is int and kind in (1, 2)
                and not (type(slot) is int and 1 <= slot <= 12)):
            raise ValueError(_COLOUR_MEMBER)


def _check_values(original, revised):
    """Rules on changed values that one field alone cannot check.

    A field of _OBSERVED_VALUES must take a value the original timeline already
    uses for it (on the same track, or anywhere); a changed member position must
    be one of the timeline's performer slots; and a member colour or member focus
    needs the clip's member position (as revised) to be a member slot.
    Malformed revisions are left to _changes."""
    if not isinstance(revised, dict) or not isinstance(revised.get("tracks"), list):
        return
    revised_events = {}
    for track in revised["tracks"]:
        for event in track.get("events", []) if isinstance(track, dict) and isinstance(track.get("events"), list) else []:
            if isinstance(event, dict) and isinstance(event.get("id"), str) and isinstance(event.get("values"), dict):
                revised_events.setdefault(event["id"], event["values"])
    observed = {}
    for track in original["tracks"]:
        for event in track["events"]:
            values = event["values"]
            for (native, field), scope in _OBSERVED_VALUES.items():
                if values.get("playableClass") == native and field in values:
                    key = (native, field, track["id"] if scope == "track" else None)
                    observed.setdefault(key, set()).add(_value_key(values[field]))
    slots = performer_slots(original["tracks"])
    for track in original["tracks"]:
        for event in track["events"]:
            before, after = event["values"], revised_events.get(event["id"])
            native = before.get("playableClass")
            if after is None:
                continue
            for field in before.keys() & after.keys():
                value = after[field]
                if value == before[field] and type(value) is type(before[field]):
                    continue
                scope = _OBSERVED_VALUES.get((native, field))
                if scope and _value_key(value) not in observed.get(
                        (native, field, track["id"] if scope == "track" else None), ()):
                    raise ValueError(f"Choose a value this MV already uses for '{field}'.")
                if (native, field) in _MEMBER_POSITIONS and not (type(value) is int and value in slots):
                    raise ValueError(MEMBER_SLOT)
                if native == "LivePenlightClip" and field == "memberColors":
                    _check_member_colors(before[field], value, slots)
                rule = _MEMBER_SLOT_VALUES.get((native, field))
                slot = after.get(rule[2], before.get(rule[2])) if rule else None
                if rule and type(value) is int and value in rule[0] and not (type(slot) is int and 1 <= slot <= 12):
                    raise ValueError(rule[1])


def _camera_sample_order(tree):
    order = [_camera_binding(row) for row in tree["m_ClipBindingConstant"]["genericBindings"]]
    if len(order) != 3 or set(order) not in ({"position", "rotation", "fov"}, {"position", "euler", "fov"}):
        raise ValueError("These camera bindings need their original native key data.")
    return order


def _camera_vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"The camera {label} is incomplete.")
    return [_time(item, label, minimum=-1_000_000, maximum=1_000_000) for item in value]


def _write_camera(tree, clip, old_event, new_event):
    unity_euler_near = animation.unity_euler_near

    before, after = old_event["values"]["keyframes"], new_event["values"]["keyframes"]
    span = old_event["duration"]
    rate = float(tree["m_SampleRate"])
    muscle = tree["m_MuscleClip"]
    first, last = float(muscle["m_StartTime"]), float(muscle["m_StopTime"])
    if (not isinstance(after, list) or len(after) != len(before) or not 2 <= len(after) <= _MAX_CAMERA_FRAMES
            or new_event["duration"] != span or old_event["values"].get("clipIn", 0) != 0
            or old_event["values"].get("timeScale", 1) != 1 or clip.get("m_ClipIn", 0) != 0
            or clip.get("m_TimeScale", 1) != 1 or abs(first) > 1e-6 or abs(last - span) > 1e-3
            or not 1 <= rate <= 60 or abs(span * rate - (len(after) - 1)) > 1e-3):
        raise ValueError("Camera point edits require an untrimmed, full native shot with unchanged sample times.")
    order = _camera_sample_order(tree)
    sample_array, previous_euler = [], None
    if "euler" in order:
        channels = _camera_channels(tree, None)
        euler_order = channels["eulerOrder"]
        # Start from the original first sample's angles; later samples follow their predecessor.
        previous_euler = [animation._evaluate(curve, first) for curve in channels["euler"]]
    for index, (old_point, point) in enumerate(zip(before, after)):
        if (not isinstance(point, dict) or set(point) != {"time", "position", "rotation", "fov"}
                or point["time"] != old_point["time"] or abs(point["time"] - index / rate) > 1e-5):
            raise ValueError("Keep the original camera point count and times.")
        position = _camera_vector(point["position"], 3, "position")
        rotation = _camera_vector(point["rotation"], 4, "rotation")
        length = math.sqrt(sum(axis * axis for axis in rotation))
        if length < 1e-10:
            raise ValueError("The camera rotation quaternion must be nonzero.")
        rotation = [axis / length for axis in rotation]
        fov = [_time(point["fov"], "field of view", minimum=.01, maximum=179.99)]
        values = {"position": position, "rotation": rotation, "fov": fov}
        if "euler" in order:
            # Write the binding's own rotation order. The dense clip lerps Euler
            # samples, so keep the equivalent angles nearest the previous sample.
            values["euler"] = previous_euler = unity_euler_near(rotation, euler_order, previous_euler)
        for channel in order:
            sample_array.extend(values[channel])
    packed = muscle["m_Clip"]["data"]
    packed["m_StreamedClip"].update(data=[], curveCount=0)
    packed["m_ConstantClip"]["data"] = []
    packed["m_DenseClip"].update(m_FrameCount=len(after), m_CurveCount=len(sample_array) // len(after),
                                 m_SampleRate=rate, m_BeginTime=0., m_SampleArray=sample_array)


def _bundle_facts(env):
    import hashlib
    from UnityPy.files import BundleFile, SerializedFile
    from UnityPy.streams import EndianBinaryReader

    bundle = env.file
    if len(env.files) != 1 or not isinstance(bundle, BundleFile) or bundle.decryptor is not None:
        raise ValueError("A native edit needs one unencrypted UnityFS timeline bundle.")
    rows = {}
    for name, item in bundle.files.items():
        if isinstance(item, SerializedFile):
            dependencies = tuple((value.path, value.type, value.guid) for value in item.externals)
            rows[name] = ("serialized", item.flags, int(item.target_platform), item.header.version,
                          str(item.unity_version), dependencies)
        elif isinstance(item, EndianBinaryReader):
            rows[name] = ("stream", item.flags, hashlib.sha256(item.bytes).digest())
        else:
            raise ValueError("The timeline contains an unsupported embedded file.")
    return bundle, rows


def edit_timeline(raw: bytes, original: dict, revised: dict) -> bytes:
    """Repack a native copy after verified edits to existing track/clip slots."""
    if not isinstance(raw, bytes) or not isinstance(original, dict) or not isinstance(revised, dict):
        raise ValueError("Choose a valid original bundle and timeline revision.")
    if original == revised:
        return raw
    if parse_timeline(raw, "original") != original:
        raise ValueError("The native timeline changed after opening. Open it again before exporting.")
    return _rewrite_timeline(raw, original, revised)


def needs_emissive_track_metadata(track):
    return (isinstance(track, dict) and track.get("kind") == "effects"
            and track.get("nativeClass") == "LiveStageEmissiveTrack")


def restore_emissive_track_metadata(tracks, originals):
    """Add native lighting metadata to older projects without changing edits."""
    if not any(needs_emissive_track_metadata(track) for track in tracks):
        return tracks
    native_tracks = {track["id"]: track for track in originals
                     if track.get("nativeClass") == "LiveStageEmissiveTrack"}
    restored = []
    for track in tracks:
        identity = track.get("id") if needs_emissive_track_metadata(track) else None
        native = native_tracks.get(identity) if isinstance(identity, str) else None
        if native is None or not isinstance(track.get("events"), list):
            restored.append(track)
            continue
        native_events = _index_rows(native["events"], "event")
        events = []
        for event in track["events"]:
            event_id = event.get("id") if isinstance(event, dict) else None
            source = native_events.get(event_id) if isinstance(event_id, str) else None
            values = event.get("values") if source is not None else None
            if (not isinstance(values, dict) or values.get("asset") != source["values"].get("asset")
                    or values.get("playableClass") != source["values"].get("playableClass")):
                events.append(event)
                continue
            mixes = {key: source["values"][key] for key in ("mixIn", "mixOut") if key in source["values"]}
            editable = source["editableValues"]
            old_editable = [field for field in editable if field not in _EDITABLE_VALUES["LiveStageEmissiveClip"]]
            if event.get("editableValues") == old_editable:
                event = {**event, "editableValues": editable}
            events.append({**event, "values": {**mixes, **values}})
        restored.append({**track, "kind": native["kind"], "events": events})
    return restored


def shared_playables(tracks):
    """Asset ids that more than one saved clip references.

    The parser lists value fields as editable only for a playable that one clip
    references, so a clip of a shared playable never needs an editableValues sync."""
    counts = Counter()
    for track in tracks if isinstance(tracks, list) else ():
        events = track.get("events") if isinstance(track, dict) else None
        for event in events if isinstance(events, list) else ():
            values = event.get("values") if isinstance(event, dict) else None
            asset = values.get("asset") if isinstance(values, dict) else None
            if isinstance(asset, str):
                counts[asset] += 1
    return frozenset(asset for asset, count in counts.items() if count > 1)


def needs_editable_values_sync(track, shared=None):
    """A saved track with an event whose whitelisted fields are not all in its editableValues.

    `shared` is shared_playables() of the whole project; by default the clips of this
    track alone tell which playables are shared."""
    if not isinstance(track, dict) or not isinstance(track.get("events"), list):
        return False
    if shared is None:
        shared = shared_playables([track])
    for event in track["events"]:
        values = event.get("values") if isinstance(event, dict) else None
        saved = event.get("editableValues") if isinstance(event, dict) else None
        native = values.get("playableClass") if isinstance(values, dict) else None
        asset = values.get("asset") if isinstance(values, dict) else None
        if (isinstance(native, str) and isinstance(saved, list) and not (isinstance(asset, str) and asset in shared)
                and (_EDITABLE_VALUES.get(native, set()) & values.keys()) - set(saved)):
            return True
    return False


def sync_editable_values(tracks, originals):
    """Give events saved with an older field whitelist the current editableValues.

    An event takes the fresh parse's list only when its asset and playable class
    are the original's and its saved list is a subset of the fresh one, so a
    project saved before the whitelist grew exports again (_changes compares the
    lists) and nothing else changes."""
    native = {}
    for track in originals:
        for event in track["events"]:
            native[event["id"]] = event
    result = []
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get("events"), list):
            result.append(track)
            continue
        events, touched = [], False
        for event in track["events"]:
            source = native.get(event.get("id")) if isinstance(event, dict) and isinstance(event.get("id"), str) else None
            values = event.get("values") if source is not None else None
            saved = event.get("editableValues") if source is not None else None
            fresh = source["editableValues"] if source is not None else None
            if (isinstance(values, dict) and isinstance(saved, list) and saved != fresh
                    and all(isinstance(field, str) for field in saved) and set(saved) <= set(fresh)
                    and values.get("asset") == source["values"].get("asset")
                    and values.get("playableClass") == source["values"].get("playableClass")):
                event = {**event, "editableValues": list(fresh)}
                touched = True
            events.append(event)
        result.append({**track, "events": events} if touched else track)
    return result


# Before camera Euler bindings honoured their Unity RotationOrder, every camera
# sample was composed in the default ZXY order. Projects saved then carry those
# rotations; a point that still equals that legacy evaluation was never edited.
_LEGACY_CAMERA_ORDER = animation.DEFAULT_EULER_ORDER
_LEGACY_CAMERA_TOLERANCE = 1e-6  # Per unit-quaternion component.


def needs_camera_keyframe_check(track):
    """A saved camera track with sampled points, which may predate camera Euler rotation orders."""
    return (isinstance(track, dict) and track.get("kind") == "camera" and isinstance(track.get("events"), list)
            and any(isinstance(event, dict) and isinstance(event.get("values"), dict)
                    and isinstance(event["values"].get("keyframes"), list) for event in track["events"]))


def _same_rotation(saved, expected):
    if (not isinstance(saved, list) or len(saved) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in saved)):
        return False
    return min(max(abs(a - b) for a, b in zip(saved, expected)),
               max(abs(a + b) for a, b in zip(saved, expected))) <= _LEGACY_CAMERA_TOLERANCE


def _legacy_camera_frames(raw, name, events):
    """{event id: its points composed in the legacy ZXY order} for native camera events with another order."""
    deadline = time.monotonic() + 45
    _, objects, _ = _read(raw, name, deadline)
    by_id = {_id(key): key for key in objects}
    clips, result = {}, {}
    for event in events:
        track_id, index = event["id"].rsplit(":", 1)
        try:
            if track_id not in clips:
                clips[track_id] = objects[by_id[track_id]].read_typetree()["m_Clips"]
            clip = clips[track_id][int(index)]
            motion = objects[by_id[event["values"]["animation"]]]
            if motion.type.name != "AnimationClip":
                continue
            channels = _camera_channels(motion.read_typetree(), deadline)
            if "rotation" in channels or channels["eulerOrder"] == _LEGACY_CAMERA_ORDER:
                continue  # The legacy composition gave these same rotations.
            result[event["id"]] = _camera_frames(motion, clip, event["duration"], deadline, _MAX_CAMERA_FRAMES,
                                                 euler_order=_LEGACY_CAMERA_ORDER)
        except (KeyError, IndexError, TypeError, ValueError):
            if time.monotonic() >= deadline:
                raise
    return result


def restore_legacy_camera_keyframes(raw, name, tracks, originals):
    """Give camera points saved with the legacy ZXY composition their current rotation, keeping edits.

    Only a point whose saved rotation equals the legacy evaluation of its native
    sample takes the current one; its saved time, position and field of view stay.
    Edited rotations stay as saved and are written in the binding's own order."""
    native_tracks = {track["id"]: track for track in originals if track.get("kind") == "camera"}

    def pairs():
        for position, track in enumerate(tracks):
            identity = track.get("id") if needs_camera_keyframe_check(track) else None
            native = native_tracks.get(identity) if isinstance(identity, str) else None
            if native is None:
                continue
            native_events = _index_rows(native["events"], "event")
            for index, event in enumerate(track["events"]):
                event_id = event.get("id") if isinstance(event, dict) else None
                source = native_events.get(event_id) if isinstance(event_id, str) else None
                values = event.get("values") if source is not None else None
                saved = values.get("keyframes") if isinstance(values, dict) else None
                current = source["values"].get("keyframes") if source is not None else None
                if (isinstance(saved, list) and isinstance(current, list) and saved != current
                        and len(saved) == len(current) and values.get("animation") == source["values"].get("animation")):
                    yield position, index, source

    candidates = list(pairs())
    if not candidates:
        return tracks
    legacy = _legacy_camera_frames(raw, name, [source for _, _, source in candidates])
    restored = list(tracks)
    for position, index, source in candidates:
        before = legacy.get(source["id"])
        current = source["values"]["keyframes"]
        if before is None or len(before) != len(current):
            continue
        track = restored[position]
        event = track["events"][index]
        points = [{**point, "rotation": list(new["rotation"])}
                  if (isinstance(point, dict) and point.get("time") == old["time"]
                      and _same_rotation(point.get("rotation"), old["rotation"])) else point
                  for point, old, new in zip(event["values"]["keyframes"], before, current)]
        events = list(track["events"])
        events[index] = {**event, "values": {**event["values"], "keyframes": points}}
        restored[position] = {**track, "events": events}
    return restored


def prepare_tracks(raw: bytes, name: str, tracks, original_tracks):
    """Bring saved tracks up to the current parse rules of their source bytes, keeping every edit.

    The steps every native export runs first: emissive track metadata, the current editableValues
    lists, legacy (ZXY) camera rotations of unedited points, and the derived shaftSlot. Without
    them a project saved by an older version would differ from its own source where nothing was
    edited."""
    if not isinstance(tracks, list):
        return tracks
    tracks = restore_emissive_track_metadata(tracks, original_tracks)
    tracks = sync_editable_values(tracks, original_tracks)
    tracks = restore_legacy_camera_keyframes(raw, name, tracks, original_tracks)
    # Shaft targets are derived preview metadata, independent of any clip's
    # member color selector. The original track identity remains read-only.
    return [
        {key: value for key, value in track.items() if key != "shaftSlot"}
        if (isinstance(track, dict) and type(track.get("shaftSlot")) is int
            and _shaft_slot(track) == track["shaftSlot"]) else track
        for track in tracks
    ]


def export_timeline(raw: bytes, name: str, tracks: list) -> bytes:
    """Derive the base from these source bytes and export the submitted tracks."""
    original = parse_timeline(raw, name)
    tracks = prepare_tracks(raw, name, tracks, original["tracks"])
    if original["tracks"] == tracks:
        return raw
    return _rewrite_timeline(raw, original, {**original, "tracks": tracks})


MERGE_LAYOUT = "The MV in the game has a different track layout. Use Apply all."
_CLIP_FIELDS = ("start", "duration", "label")


def _float32(value):
    """``value`` with every float rounded to float32, the precision a native timeline stores, and every
    integer as the same float: a project posted by the page has lost the difference (JSON numbers), and
    Python compares 1 == 1.0 too. Booleans stay booleans."""
    import struct

    if type(value) is int:
        try:
            return float(value)
        except OverflowError:
            return value
    if type(value) is float:
        try:
            return struct.unpack("<f", struct.pack("<f", value))[0]
        except (OverflowError, struct.error):
            return value
    if isinstance(value, dict):
        return {key: _float32(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_float32(item) for item in value]
    return value


def field_digest(value):
    """A short digest of a merged field's value once stored (floats as float32): equal digests are the
    same value in the game, so an edit typed again (0.7) equals what the game holds (0.699999988)."""
    import hashlib

    return hashlib.sha256(_value_key(_float32(value)).encode()).hexdigest()[:16]


def _merge_value(event, field):
    return event[field] if field in _CLIP_FIELDS else event["values"][field]


def _merge_label(value):
    """A short display form of a merged field's value for the conflict list."""
    import json

    if isinstance(value, list) and value and all(isinstance(item, dict) and "time" in item for item in value):
        return f"{len(value)} keys"
    if type(value) is float:
        return f"{value:.6g}"
    if isinstance(value, dict) and all(type(item) in (int, float) for item in value.values()):
        return "(" + ", ".join(f"{item:.4g}" for item in value.values()) + ")"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= 48 else text[:47] + "…"


def _merge_fields(before, mine):
    for field in (*_CLIP_FIELDS, *before["values"]):
        if field in _CLIP_FIELDS or field in mine["values"]:
            yield field


def _shown(value):
    """The display form a synced entry keeps of an applied value (at most 64 characters)."""
    label = _merge_label(value)
    return label if len(label) <= 64 else label[:63] + "…"


def synced_digest(entry):
    """(digest, label) of one ``synced`` entry: ``[digest, label]`` as ``synced_fields`` makes it, or a
    bare digest; (None, None) for anything else."""
    if isinstance(entry, str):
        return entry, None
    if (isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[0], str)
            and (entry[1] is None or isinstance(entry[1], str))):
        return entry[0], entry[1]
    return None, None


def merge_changes(base, ours, theirs, synced=None):
    """Three-way merge of clip fields: put the edits ``ours`` made onto ``theirs``.

    ``base`` is the parse of the timeline a project was loaded from, ``ours`` the project's
    tracks normalized against it (mv_studio_register.normalize: same tracks, clips and value
    keys), ``theirs`` the parse of the timeline the game plays now. ``synced`` ({event id:
    {field: [field_digest, label]}}, from ``synced_fields`` after an earlier apply of this
    project to this platform) holds the values the project and the game last agreed on where
    they are not the base's. Every clip's start, duration, label and each of its values (camera
    keyframes as one field) is merged on its own, against its last agreed value:

    - unchanged in ours: theirs stays (also a change the game made since);
    - changed in ours, and theirs still has the agreed value or already ours: ours is taken;
    - changed differently in both: a conflict, and nothing is taken silently.

    Values compare as stored (``field_digest``). A conflict names its ``basis``: "load" (the
    agreed value is the loaded one, shown as ``loaded``) or "applied" (the value this project
    last applied, shown as ``loaded`` from the synced label). Track fields of
    EXPORTABLE_TRACK_FIELDS merge the same way, keyed by the track id in ``synced``; their
    conflicts have ``scope`` "track" (the track id as ``eventId``, no clip). Returns ``(merged
    tracks, conflicts, taken, theirs_only)``: merged is theirs with the taken fields;
    ``theirs_only`` counts the fields the game changed that the project does not hold. Raises
    ValueError(MERGE_LAYOUT) when theirs has other tracks, clips or value keys."""
    import copy

    if (not isinstance(theirs, list) or len(theirs) != len(base) or len(ours) != len(base)
            or any(track["id"] != other["id"] or [event["id"] for event in track["events"]]
                   != [event["id"] for event in other["events"]] for track, other in zip(base, theirs))):
        raise ValueError(MERGE_LAYOUT)
    synced = synced if isinstance(synced, dict) else {}
    merged = copy.deepcopy(theirs)
    conflicts, counts = [], {"taken": 0, "theirs_only": 0}

    def merge(identity, field, old, new, now, put, where):
        """Merge one field: put(new) when ours is taken, a conflict row (``where`` + values) otherwise."""
        agreed = synced.get(identity) if isinstance(synced.get(identity), dict) else {}
        old_digest, applied_label = synced_digest(agreed.get(field))
        basis = "applied" if old_digest is not None else "load"
        if old_digest is None:
            old_digest = field_digest(old)
        new_digest, now_digest = field_digest(new), field_digest(now)
        if new_digest == old_digest:
            if now_digest != old_digest:
                counts["theirs_only"] += 1
            return
        if now_digest == new_digest:
            return
        if now_digest == old_digest:
            put(new)
            counts["taken"] += 1
            return
        conflicts.append({**where, "field": field, "basis": basis,
                          "loaded": _merge_label(old) if basis == "load" else (applied_label or "?"),
                          "project": _merge_label(new), "game": _merge_label(now)})

    for base_track, our_track, merged_track in zip(base, ours, merged):
        track_label = str(base_track.get("label") or base_track["id"])
        for field in EXPORTABLE_TRACK_FIELDS:
            if field in base_track and field in our_track:
                if field not in merged_track:
                    raise ValueError(MERGE_LAYOUT)
                merge(base_track["id"], field, base_track[field], our_track[field], merged_track[field],
                      lambda value, track=merged_track, key=field: track.__setitem__(key, value),
                      {"track": track_label, "trackId": base_track["id"], "clip": "", "eventId": base_track["id"],
                       "start": 0.0, "scope": "track"})
        for before, mine, game in zip(base_track["events"], our_track["events"], merged_track["events"]):
            if not isinstance(game.get("values"), dict) or before["values"].keys() - game["values"].keys():
                raise ValueError(MERGE_LAYOUT)
            for field in _merge_fields(before, mine):
                target = game if field in _CLIP_FIELDS else game["values"]
                merge(before["id"], field, _merge_value(before, field), _merge_value(mine, field),
                      _merge_value(game, field), lambda value, target=target, key=field: target.__setitem__(key, value),
                      {"track": track_label, "trackId": base_track["id"], "clip": str(before.get("label") or before["id"]),
                       "eventId": before["id"], "start": before["start"]})
    return merged, conflicts, counts["taken"], counts["theirs_only"]


def synced_fields(base, ours):
    """What a project and the game agree on after a successful apply: {event id: {field: [digest,
    label]}} of every field where ours is not the base (the base holds for every other field); a
    changed EXPORTABLE_TRACK_FIELDS field is listed under its track id."""
    result = {}
    for base_track, our_track in zip(base, ours):
        for field in EXPORTABLE_TRACK_FIELDS:
            if field in base_track and field in our_track:
                digest = field_digest(our_track[field])
                if digest != field_digest(base_track[field]):
                    result.setdefault(base_track["id"], {})[field] = [digest, _shown(our_track[field])]
        for before, mine in zip(base_track["events"], our_track["events"]):
            for field in _merge_fields(before, mine):
                value = _merge_value(mine, field)
                digest = field_digest(value)
                if digest != field_digest(_merge_value(before, field)):
                    result.setdefault(before["id"], {})[field] = [digest, _shown(value)]
    return result


def _rewrite_timeline(raw, original, revised):
    _check_values(original, revised)
    changes = _changes(original, revised)
    track_changes = _track_changes(original, revised)
    if not changes and not track_changes:
        return raw
    deadline = time.monotonic() + 45
    env, objects, source = _read(raw, "original", deadline)
    bundle, facts = _bundle_facts(env)
    mono, references, animations = {}, Counter(), Counter()
    for key, obj in objects.items():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except (ValueError, KeyError, TypeError):
            continue
        native = selection._class(source, obj, tree)
        mono[key] = tree, native
        for clip in tree.get("m_Clips", []):
            references[_pointer(obj, clip.get("m_Asset"))] += 1
        if native == "AnimationPlayableAsset":
            animations[_pointer(obj, tree.get("m_Clip"))] += 1
    by_id = {_id(key): key for key in objects}
    dirty = {}
    for identity, kind, index, old, new in changes:
        animation._check(deadline)
        track = by_id[identity]
        tree, _ = mono[track]
        clip = tree["m_Clips"][index]
        if new["start"] != old["start"]:
            clip["m_Start"] = _time(new["start"], "clip start")
            dirty[track] = tree
        if new["duration"] != old["duration"]:
            clip["m_Duration"] = _time(new["duration"], "clip duration", minimum=0)
            dirty[track] = tree
        if new["label"] != old["label"]:
            if not isinstance(new["label"], str) or not 0 < len(new["label"]) <= 240 or "\0" in new["label"]:
                raise ValueError("The native clip needs a valid display label.")
            clip["m_DisplayName"] = new["label"]
            dirty[track] = tree
        fields = {key for key in new["values"] if new["values"][key] != old["values"][key]}
        for field in fields & _TIMING_NATIVE.keys():
            _set_timing(clip, field, new["values"][field])
            dirty[track] = tree
        payload_fields = fields - _TIMING_NATIVE.keys()
        if not payload_fields:
            continue
        asset = _pointer(objects[track], clip.get("m_Asset"))
        if asset not in mono or references[asset] != 1:
            raise ValueError("An edited clip uses a shared or external playable asset. Edit its timing only.")
        asset_tree, asset_type = mono[asset]
        if payload_fields == {"keyframes"} and kind == "camera" and asset_type == "AnimationPlayableAsset":
            camera = _pointer(objects[asset], asset_tree.get("m_Clip"))
            if camera not in objects or objects[camera].type.name != "AnimationClip" or animations[camera] != 1:
                raise ValueError("This camera animation is shared or external. Edit its timing only.")
            camera_tree = objects[camera].read_typetree()
            _write_camera(camera_tree, clip, old, new)
            dirty[camera] = camera_tree
        else:
            if not payload_fields <= _EDITABLE_VALUES.get(asset_type, set()) or not payload_fields <= asset_tree.keys():
                raise ValueError(f"Some requested properties are read-only for {asset_type or 'this original playable'}.")
            for field in payload_fields:
                _set_playable_value(asset_tree, asset_type, field, new["values"][field])
            dirty[asset] = asset_tree
    for identity, field, value in track_changes:
        # The track MonoBehaviour's own TrackAsset.m_Muted (the only EXPORTABLE_TRACK_FIELDS entry).
        track = by_id[identity]
        tree, native = mono[track]
        if native == "GroupTrack":
            raise ValueError(GROUP_MUTE)
        if field != "muted" or type(tree.get("m_Muted")) not in (bool, int):
            raise ValueError("This native track has no mute to change.")
        tree["m_Muted"] = value if type(tree["m_Muted"]) is bool else int(value)
        dirty[track] = tree

    import hashlib
    untouched = {key: hashlib.sha256(obj.get_raw_data()).digest() for key, obj in objects.items() if key not in dirty}
    # m_MuscleClipSize of a camera clip _write_camera rewrote (the only AnimationClips in dirty).
    # Every inspected stock camera clip records it as its serialized size + 188 bytes, and a dense
    # rewrite can grow a clip past it (a constant shot baked dense: so2036_2840f_2931f_camera,
    # 2432 -> 4972 bytes against 2620). Unity allocates the muscle-clip blob with this size, so a
    # clip that grew gets old value + growth + 64, rounded up to 16 (over-allocating is the safe
    # direction; unverified on device); it is never shrunk. A uint32, so the length is kept.
    camera_sizes = {key: len(objects[key].get_raw_data()) for key in dirty if objects[key].type.name == "AnimationClip"}

    def save(key, tree):
        payload = objects[key].save_typetree(tree)
        growth = len(payload) - camera_sizes[key] if key in camera_sizes and "m_MuscleClipSize" in tree else 0
        if growth > 0:
            tree["m_MuscleClipSize"] = (int(tree["m_MuscleClipSize"]) + growth + 64 + 15) // 16 * 16
            payload = objects[key].save_typetree(tree)
        return payload

    edited_payloads = {key: save(key, tree) for key, tree in dirty.items()}
    # The existing native timeline tools use Unity's LZ4 bundle container.
    # UnityPy's "original" only retains the first block's compression mode,
    # which can make mixed-compression stock timelines several times larger.
    output = bundle.save(packer="lz4")
    verified_env, verified_objects, _ = _read(output, "edited timeline", deadline)
    _, verified_facts = _bundle_facts(verified_env)
    if (verified_objects.keys() != objects.keys() or verified_facts != facts
            or any(hashlib.sha256(verified_objects[key].get_raw_data()).digest() != digest
                   for key, digest in untouched.items())):
        raise ValueError("The native copy changed unrelated Unity objects or resources.")
    for key, expected in edited_payloads.items():
        if verified_objects[key].get_raw_data() != expected:
            raise ValueError("A native timeline edit did not survive serialization.")
    return output
