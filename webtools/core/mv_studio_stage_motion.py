"""Typed transform and GameObject activation data for a native stage preview."""

import math
import struct
from collections import Counter

from . import model_animation as animation
from . import mv_studio_timeline as timeline
from .model_viewer import _remaining


_BINDING_ROOT = "/EntryPoint/Live/Stages/MainStage/Effect/"
_ASSEMBLY = "UnityEngine.Timeline.dll"
_NAMESPACE = "UnityEngine.Timeline"
_MAX_SCALARS = 300_000
_MAX_MIX_KEYS = 128
_WIDTH = {"translation": 3, "rotation": 4, "euler": 3, "scale": 3, "visibility": 1, "overlayTint": 4, "overlayUV": 4}
_STAGE_QUALITY = {"post": "posteffect", "ambient": "stage_ambient", "animation": "stage_animation",
                  "coloring": "stage_coloring", "control": "stage_control", "flashlight": "stage_flash_light",
                  "display": "stage_display", "audience": "stage_audience", "emissive": "stage_emissive",
                  "overlayeffect": "stage_overlay_effect"}
_AION_OVERLAY = _BINDING_ROOT + "fx_ove_so2028_01/Effect_root"
_AION_OVERLAY_CLIP = 3160271792038109442
_LASER_BINDING = _BINDING_ROOT + "fx_par_so2056_05/root"
_LASER_TRACK = "StageEffect/Expert/Control/fx_par_so2056_05_root"
_LASER_CLIP = -7002476404608242900
_LASER_DURATION = 118.81666564941406
_LASER_BEAM = animation.path_hash("joint_all/LaserBeam")
_LASER_TINT = animation.path_hash("_TintColor") & 0x0FFFFFFF
_LASER_CORE_PATHS = {animation.path_hash(f"joint_all/Joint_root_{root:02}/{side}/core")
                     for root in (1, 2) for side in ("L", "R")}
_LASER_CORE_CONSTANTS = {0xF31EAC3F: 0.6000000238418579, 0x9EC348D4: 0.800000011920929,
                         0xEEA9BC5B: 1.0, 0x77A0EDE1: 0.6000000238418579}


def _declared(objects, owner, tree, name, scripts):
    key = timeline._pointer(owner, tree.get("m_Script"))
    if key not in scripts:
        script = objects.get(key)
        try:
            values = script.read_typetree() if script is not None and script.type.name == "MonoScript" else {}
        except (KeyError, TypeError, ValueError, struct.error):
            values = {}
        scripts[key] = tuple(values.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName"))
    return scripts[key] == (_ASSEMBLY, _NAMESPACE, name)


def _neutral_offsets(tree):
    for field, expected in (("m_Position", (0, 0, 0)), ("m_EulerAngles", (0, 0, 0)), ("m_Rotation", (0, 0, 0, 1))):
        value = tree.get(field)
        if value is not None and (not isinstance(value, dict) or tuple(value.get(axis) for axis in "xyzw"[:len(expected)]) != expected):
            return False
    return True


def _track_supported(obj, tree, mono):
    if (tree.get("m_TrackOffset", 0) != 0 or tree.get("m_ApplyOffsets") or not _neutral_offsets(tree)
            or tree.get("m_Children")):
        return False
    parent = mono.get(timeline._pointer(obj, tree.get("m_Parent")))
    return (not parent or parent[2] != "AnimationTrack") and not any(
        (tree.get(field) or {}).get("m_PathID") for field in ("m_AvatarMask", "m_AnimClip", "m_InfiniteClip"))


def _laser_tint(tree, bindings, deadline):
    # The beam tint belongs to the SkinnedMeshRenderer. The four core emitters
    # use their own validated constant birth colors in the resident particle reader.
    if tree.get("m_Name") != "clip_par_so2056_05" or len(bindings) != 55:
        return None
    transform_profile = Counter({(4, 4, 4): 28, (4, 3, 0): 4, (1, 2086281974, 0): 3})
    core = {(path, attribute): value for path in _LASER_CORE_PATHS
            for attribute, value in _LASER_CORE_CONSTANTS.items()}
    packed = animation._packed_curves(tree, deadline)
    components, index = {}, 0
    for binding in bindings:
        if binding.get("isPPtrCurve") != 0 or binding.get("script") != {"m_FileID": 0, "m_PathID": 0}:
            return None
        path = binding["path"]
        kind = binding["typeID"]
        attribute = binding["attribute"]
        custom = binding["customType"]
        profile = kind, attribute, custom
        if transform_profile[profile]:
            transform_profile[profile] -= 1
        elif kind == 198 and custom == 27:
            value = core.pop((path, attribute), None)
            if value is None or packed[index] != ("constant", value):
                return None
        elif kind == 137 and custom == 22 and path == _LASER_BEAM:
            lane = attribute >> 28
            if (attribute & 0x0FFFFFFF) != _LASER_TINT or not 0 <= lane < 4 or lane in components:
                return None
            components[lane] = packed[index]
        else:
            return None
        index += animation._width(binding)
    if core or any(transform_profile.values()) or len(components) != 4:
        return None
    return {"path": _LASER_BEAM, "kind": "overlayTint", "curves": [components[lane] for lane in range(4)]}


def _read_clip(reader, deadline, *, overlay=False, resident_laser=False):
    tree = reader.read_typetree()
    if any(tree.get(field) for field in ("m_Legacy", "m_Compressed", "m_HasGenericRootTransform", "m_HasMotionFloatCurves",
                                          "m_Events", "m_PPtrCurves", "m_CompressedRotationCurves")):
        return None
    muscle = tree.get("m_MuscleClip") or {}
    if muscle.get("m_CycleOffset") or muscle.get("m_Mirror"):
        return None
    bindings = (tree.get("m_ClipBindingConstant") or {}).get("genericBindings", [])
    if not bindings and any(item.get("classID") != 1 or item.get("attribute") != "m_IsActive"
                            for item in tree.get("m_FloatCurves", [])):
        return None
    data = animation.decode_clip(tree, deadline)
    if overlay and data["unsupported"]:
        from .mv_studio_stage_overlay import material_channels
        channels, described = material_channels(bindings, animation._packed_curves(tree, deadline), animation._width)
        if described == data["unsupported"]:
            data["tracks"].extend(channels)
            data["unsupported"] = 0
    tint = None
    if (resident_laser and data["unsupported"] == 20 and
            (data["start"], data["duration"], data["loop"]) == (0.0, _LASER_DURATION, False)):
        tint = _laser_tint(tree, bindings, deadline)
    if tint is not None:
        data["tracks"].append(tint)
        data["unsupported"] = 0
    if data["unsupported"] or not data["tracks"]:
        return None

    channels, claimed, cost = [], set(), 2
    for track in data["tracks"]:
        kind, path, curves = track["kind"], track["path"], track["curves"]
        if isinstance(path, str):
            path = animation.path_hash(path)
        if not 0 <= path <= 0xffffffff or len(curves) != _WIDTH.get(kind):
            return None
        if kind == "visibility" and track.get("visibilityType") != "gameObject":
            return None
        if not path and kind in {"translation", "rotation", "euler"}:
            return None  # Root motion also depends on the Animator and offsets.
        key = (path, "rotation" if kind == "euler" else kind)
        if key in claimed:
            return None
        claimed.add(key)
        cost += 1  # Native relative path hash.
        for mode, values in curves:
            if mode == "constant":
                cost += 1
            elif mode in {"linear", "cubic"} and values:
                cost += len(values) * (5 if mode == "cubic" else 2)
            else:
                return None
        if cost > _MAX_SCALARS:
            return None
        channel = {"path": path, "kind": kind, "curves": curves}
        if kind == "visibility":
            channel["visibilityType"] = "gameObject"
        if track.get("rendererClass") == 137:
            channel["rendererClass"] = 137
        channels.append(channel)
    clip = {"start": data["start"], "duration": data["duration"], "loop": data["loop"], "channels": channels}
    if tint is not None:
        clip["sampleTimeF32"] = True
    return clip, cost


def _mix(clip):
    timing, cost = {}, 0
    for side in ("In", "Out"):
        raw = (clip.get(f"m_Mix{side}Curve") or {}).get("m_Curve", [])
        if len(raw) > _MAX_MIX_KEYS:
            return None
        rows = []
        for row in raw:
            values = {key: row.get(key) for key in ("time", "value", "inSlope", "outSlope")}
            if row.get("weightedMode", 0) or not all(type(value) in (float, int) and math.isfinite(value) for value in values.values()):
                return None
            if rows and values["time"] <= rows[-1]["time"]:
                return None
            rows.append(values)
        if rows:
            timing[f"mix{side}"] = rows
            cost += len(rows) * 4
    for side in ("Pre", "Post"):
        if clip.get(f"m_{side}ExtrapolationTime") == math.inf:
            timing[f"{side.lower()}Infinite"] = True
    return timing, cost


def _activation_events(events, by_id, objects, scripts):
    ids = []
    for event in events:
        values = event["values"]
        playable = by_id.get(values.get("asset"))
        if values.get("playableClass") != "ActivationPlayableAsset" or playable is None:
            return []
        owner, tree, _ = playable
        if not _declared(objects, owner, tree, "ActivationPlayableAsset", scripts):
            return []
        if event["duration"] > 0:
            ids.append(event["id"])
    return ids


def _quality(label, *, parent=None, mono=None):
    # The native collector indexes direct category children of a StageEffect
    # difficulty group, normalizing case and removing spaces from the name.
    parts = label.split("/")
    if len(parts) < 4 or parts[0] != "StageEffect":
        return None
    category = parts[2].replace(" ", "").lower()
    if category == "animation" and mono is not None and parent in mono:
        # The game's Timeline mutes a nested GroupTrack itself. Its output
        # AnimationTracks are compiled independently and continue to play.
        _, parent_path = timeline._lineage(parent, mono, set())
        if parent_path != "/" + "/".join(parts[:3]):
            return None
    return _STAGE_QUALITY.get(category)


def read(objects, mono, tracks, deadline):
    """Match supported tracks and events to original stage paths and local clips."""
    by_id = {timeline._id(key): row for key, row in mono.items()
             if row[2] in {"AnimationTrack", "AnimationPlayableAsset", "ActivationTrack", "ActivationPlayableAsset"}}
    scripts, clips, mix, activations, bindings, quality, rejected = {}, {}, {}, {}, {}, {}, set()
    remaining = _MAX_SCALARS
    for track in tracks:
        binding = track.get("binding", "")
        native = by_id.get(track["id"])
        kind = track.get("nativeClass")
        if (kind not in {"AnimationTrack", "ActivationTrack"} or native is None or not binding.startswith(_BINDING_ROOT)
                or any(part in {"", ".", ".."} for part in binding.removeprefix(_BINDING_ROOT).split("/"))):
            continue
        obj, tree, _ = native
        if not _declared(objects, obj, tree, kind, scripts):
            continue
        if kind == "ActivationTrack":
            _remaining(deadline)
            ids = _activation_events(track["events"], by_id, objects, scripts)
            if ids:
                bindings[binding] = None
                activations[track["id"]] = ids
                # ActivationPlayableAsset ClipCaps is None. The mixer only
                # tests whether any input's evaluated weight is positive.
                mix.update((identity, {}) for identity in ids)
            continue
        if not _track_supported(obj, tree, mono):
            continue
        branch = binding.removeprefix(_BINDING_ROOT).split("/")
        overlay = len(branch) == 2 and branch[0].startswith("fx_ove_") and branch[1] == "Effect_root"
        laser_track = binding == _LASER_BINDING and track["label"] == _LASER_TRACK
        parent = timeline._pointer(obj, tree.get("m_Parent"))
        setting = "stage_overlay_effect" if overlay else _quality(track["label"], parent=parent, mono=mono)
        allow_overlay_material = setting == "stage_overlay_effect"
        for event in track["events"]:
            _remaining(deadline)
            values = event["values"]
            identity = values.get("animation")
            profile = (identity, allow_overlay_material)
            playable = by_id.get(values.get("asset"))
            if not identity or profile in rejected or playable is None or values.get("playableClass") != "AnimationPlayableAsset":
                continue
            owner, payload, _ = playable
            if (payload.get("m_Loop", 0) != 0 or not _neutral_offsets(payload)
                    or not _declared(objects, owner, payload, "AnimationPlayableAsset", scripts)):
                continue
            key = timeline._pointer(owner, payload.get("m_Clip"))
            reader = objects.get(key)
            if reader is None or reader.type.name != "AnimationClip" or timeline._id(key) != identity:
                continue
            source = tree["m_Clips"][int(event["id"].rsplit(":", 1)[1])]
            if (source.get("m_AnimationCurves") or {}).get("m_PathID"):
                continue
            data = _mix(source)
            if data is None:
                continue
            timing, timing_cost = data
            if identity in clips:
                declaration, cost = clips[identity], 0
                if declaration.get("requiresOverlayMaterial") and not allow_overlay_material:
                    continue
            else:
                resident_laser = laser_track and key[1] == _LASER_CLIP and not any(
                    other is not event and other["values"].get("animation") == identity
                    for row in tracks for other in row["events"])
                try:
                    clip = _read_clip(reader, deadline, overlay=allow_overlay_material, resident_laser=resident_laser)
                except (KeyError, TypeError, ValueError, IndexError, OverflowError, struct.error):
                    clip = None
                if clip is None or clip[1] > remaining:
                    rejected.add(profile)
                    continue
                declaration, cost = clip
                if binding == _AION_OVERLAY and key[1] == _AION_OVERLAY_CLIP:
                    declaration["sampleTimeF32"] = True
            if cost + timing_cost > remaining:
                continue
            if allow_overlay_material and any(
                    channel["kind"] in {"overlayTint", "overlayUV"} and
                    (not overlay or channel.get("rendererClass") == 137) for channel in declaration["channels"]):
                declaration["requiresOverlayMaterial"] = True
                declaration["sampleTimeF32"] = True
            remaining -= cost + timing_cost
            clips[identity] = declaration
            mix[event["id"]] = timing
            bindings[binding] = None
            if setting:
                quality[track["id"]] = setting
    if not mix:
        return None
    result = {"clips": clips, "mix": mix, "bindings": list(bindings)}
    if activations:
        result["activations"] = activations
    if quality:
        result["quality"] = quality
    return result
