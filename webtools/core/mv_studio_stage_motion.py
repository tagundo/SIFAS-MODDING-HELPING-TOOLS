"""Typed transform and GameObject activation data for a native stage preview."""

import math
import struct

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


def _read_clip(reader, deadline, *, overlay=False):
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
        channels.append(channel)
    return {"start": data["start"], "duration": data["duration"], "loop": data["loop"], "channels": channels}, cost


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


def _quality(label):
    # The native collector indexes direct category children of a StageEffect
    # difficulty group, normalizing case and removing spaces from the name.
    parts = label.split("/")
    if len(parts) >= 4 and parts[0] == "StageEffect":
        return _STAGE_QUALITY.get(parts[2].replace(" ", "").lower())
    return None


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
        setting = "stage_overlay_effect" if overlay else _quality(track["label"])
        for event in track["events"]:
            _remaining(deadline)
            values = event["values"]
            identity = values.get("animation")
            playable = by_id.get(values.get("asset"))
            if not identity or identity in rejected or playable is None or values.get("playableClass") != "AnimationPlayableAsset":
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
            else:
                try:
                    clip = _read_clip(reader, deadline, overlay=overlay)
                except (KeyError, TypeError, ValueError, IndexError, OverflowError, struct.error):
                    clip = None
                if clip is None or clip[1] > remaining:
                    rejected.add(identity)
                    continue
                declaration, cost = clip
            if cost + timing_cost > remaining:
                continue
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
