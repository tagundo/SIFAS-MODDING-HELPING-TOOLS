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
_PERFORMER_MODEL = re.compile(r"/EntryPoint/Live/Members/Member([1-9][0-9]*)/Model")
_MEMBER_SHAFT = re.compile(r"/EntryPoint/Live/Members/Member([1-9])")
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
    if len(curves) != offset or "position" not in channels or not {"rotation", "euler"} & channels.keys():
        raise ValueError("The camera clip has unsupported native channel bindings.")
    return channels


def _camera_binding(binding):
    if binding.get("path") or binding.get("isPPtrCurve"):
        return None
    typ, attr = binding.get("typeID", binding.get("classID")), binding.get("attribute")
    if typ == 4:
        return {1: "position", 2: "rotation", 4: "euler"}.get(attr)
    if typ == 114 and attr == _FOV:
        return "fov"
    return None


def _camera_frames(obj, clip, duration, deadline, remaining_frames):
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
                                         euler="rotation" not in channels)
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
                warnings.add("Some original animation clips need their exact companion asset packs.")
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
                   preview_stage_speed_back=False,
                   preview_stage_display_lights=False, preview_stage_falling_effects=False,
                   preview_stage_break=False, preview_stage_finale_floor=False,
                   preview_stage_sparks_a=False, preview_stage_sparks_b=False, preview_stage_sparks_roop=False) -> dict:
    """Return scene tracks, timing and preview samples without changing the bundle."""
    from .model_viewer import _remaining

    deadline = time.monotonic() + 45
    _, objects, source = _read(raw, name, deadline)
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
        from . import mv_studio_split

        split = mv_studio_split.read(objects, mono, tracks, deadline)
        if split:
            result["splitScreen"] = split
    if preview_stage_motion:
        from . import mv_studio_stage_motion

        stage_motion = mv_studio_stage_motion.read(objects, mono, tracks, deadline)
        if stage_motion:
            result["stageMotion"] = stage_motion
    if preview_stage_title:
        from . import mv_studio_stage_title

        stage_title = mv_studio_stage_title.read(objects, mono, tracks, deadline)
        if stage_title:
            result["stageTitle"] = stage_title
    if preview_stage_particles:
        from . import mv_studio_stage_particles

        stage_particles = mv_studio_stage_particles.read(objects, mono, tracks, deadline)
        if stage_particles:
            result["stageParticles"] = stage_particles
    if preview_stage_ribbons:
        from . import mv_studio_stage_ribbons

        stage_ribbons = mv_studio_stage_ribbons.read(objects, mono, tracks, deadline)
        if stage_ribbons:
            result["stageRibbons"] = stage_ribbons
    if preview_stage_spotlight:
        from . import mv_studio_stage_spotlight

        stage_spotlight = mv_studio_stage_spotlight.read(objects, mono, tracks, deadline)
        if stage_spotlight:
            result["stageSpotlight"] = stage_spotlight
    if preview_stage_butterfly:
        from . import mv_studio_butterfly

        butterfly = mv_studio_butterfly.read(objects, mono, tracks, deadline)
        if butterfly:
            result["stageButterfly"] = butterfly
    atlas_refs = {} if (preview_stage_falling_effects or preview_stage_break or preview_stage_finale_floor
                        or preview_stage_sparks_a or preview_stage_sparks_b or preview_stage_sparks_roop) else None
    if preview_stage_speed_back:
        from . import mv_studio_speed_back

        speed_back = mv_studio_speed_back.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if speed_back:
            result["stageSpeedBack"] = speed_back
    if preview_stage_display_lights:
        from . import mv_studio_display_lights

        display_lights = mv_studio_display_lights.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if display_lights:
            result["stageDisplayLights"] = display_lights
    if preview_stage_falling_effects:
        from . import mv_studio_falling_display

        falling = mv_studio_falling_display.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if falling:
            result["stageFallingEffects"] = falling
    if preview_stage_break:
        from . import mv_studio_stage_break

        stage_break = mv_studio_stage_break.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if stage_break:
            result["stageBreak"] = stage_break
    if preview_stage_finale_floor:
        from . import mv_studio_finale_floor

        finale_floor = mv_studio_finale_floor.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if finale_floor:
            result["stageFinaleFloor"] = finale_floor
    if preview_stage_sparks_a:
        from . import mv_studio_sparks_a

        sparks_a = mv_studio_sparks_a.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_a:
            result["stageSparksA"] = sparks_a
    if preview_stage_sparks_b:
        from . import mv_studio_sparks_b

        sparks_b = mv_studio_sparks_b.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_b:
            result["stageSparksB"] = sparks_b
    if preview_stage_sparks_roop:
        from . import mv_studio_sparks_roop

        sparks_roop = mv_studio_sparks_roop.read(objects, mono, tracks, deadline, atlas_refs=atlas_refs)
        if sparks_roop:
            result["stageSparksRoop"] = sparks_roop
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
    "LiveDepthOfFieldClip": {"focusDistance", "aperture", "focalLength", "useCameraFov", "antiAura"},
    "LiveBaseLightClip": {"ambientColor", "ambientTintColor", "rimlightColor", "rimlightIntensity",
                         "rimlightSharpness", "rimlightDirection"},
    "LiveMemberAmbientClip": {"color", "tintColor"},
    "LiveStageAmbientClip": {"color", "tintColor", "blendColor"},
    "LiveStageSingleAmbientClip": {"color", "tintColor", "blendColor"},
    "LiveMemberSpotLightAreaClip": {"color"},
    "LiveMemberSpotLightShaftClip": {"color", "scale", "offsetHeight", "smoothTime"},
    "LiveRimlightClip": {"color", "intensity", "sharpness", "direction"},
    "LiveFlareClip": {"color", "center", "intensity", "smoothness", "roundness", "rounded"},
    "LiveFlashLightClip": {"tintColor", "speed"},
    "LiveDisplayClip": {"scrollSpeed", "ambientColor"},
    "LiveColoringClip": {"shift", "tintColor", "speed"},
    "LiveCameraOffsetClip": {"intensity"},
    "LivePenlightClip": {"tintColor", "fogIntensity", "randomBrightness", "beatLength", "beatOffset",
                         "randomDelay", "randomUp", "randomSwingIntensity"},
    "CustomControlClip": {"weight", "offset"},
}
_LIMITED_VALUES = {
    ("MemberLipSyncClip", "index"): (0, 4096),
    ("MemberEyeClip", "index"): (0, 4096),
    ("MemberGazeClip", "target"): (0, 256),
    ("MemberCheekClip", "cheekType"): (0, 1),
}
_TIMING_NATIVE = {label: field for field, label in _CLIP_TIMING.items()}


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
        if {k: v for k, v in before.items() if k != "events"} != {k: v for k, v in after.items() if k != "events"}:
            raise ValueError("Track identity, binding, and original metadata are read-only in native exports.")
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


def _set_playable_value(tree, native, field, value):
    bounds = _LIMITED_VALUES.get((native, field))
    if bounds and (type(value) is not int or not bounds[0] <= value <= bounds[1]):
        raise ValueError(f"'{field}' is outside the supported native range.")
    if field in ("weight", "weightForDirection") or native == "MemberCheekClip" and field == "intensity":
        value = _time(value, field, minimum=0, maximum=1)
    tree[field] = _replace_value(tree[field], value, field)


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
    from live_timeline.sifas_timeline_inject import quat_to_unity_euler

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
            euler = quat_to_unity_euler(rotation)
            if previous_euler is not None:
                euler = [axis + 360 * round((previous - axis) / 360) for axis, previous in zip(euler, previous_euler)]
            values["euler"] = previous_euler = euler
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


def export_timeline(raw: bytes, name: str, tracks: list) -> bytes:
    """Derive the base from these source bytes and export the submitted tracks."""
    original = parse_timeline(raw, name)
    if isinstance(tracks, list):
        # Shaft targets are derived preview metadata, independent of any clip's
        # member color selector. The original track identity remains read-only.
        tracks = [
            {key: value for key, value in track.items() if key != "shaftSlot"}
            if (isinstance(track, dict) and type(track.get("shaftSlot")) is int
                and _shaft_slot(track) == track["shaftSlot"]) else track
            for track in tracks
        ]
    if original["tracks"] == tracks:
        return raw
    return _rewrite_timeline(raw, original, {**original, "tracks": tracks})


def _rewrite_timeline(raw, original, revised):
    changes = _changes(original, revised)
    if not changes:
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

    import hashlib
    untouched = {key: hashlib.sha256(obj.get_raw_data()).digest() for key, obj in objects.items() if key not in dirty}
    edited_payloads = {key: objects[key].save_typetree(tree) for key, tree in dirty.items()}
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
