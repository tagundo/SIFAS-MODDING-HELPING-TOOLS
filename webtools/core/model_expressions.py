"""Bounded expression descriptions; original morph names and values stay intact.

Human labels follow the game's FacialAnimationId enum and its canonical morph
names. Complete eye recipes additionally require the exact original face bytes
and owner for which the original animation endpoints were verified.
"""
from collections import Counter, defaultdict
from functools import lru_cache
from importlib import resources
import json
import math
import re

MAX_CHANNELS = 512
MAX_RECIPES = 32
_FACE_207 = "97e79b210e61c6d4b1f8cbee68d903e8c6e4fb6e070bb84a9d2b6fd37fad2bd4"
_EYE = {
    "001": ("eyes-closed", "Closed eyelids", 1),
    "002": ("eyes-narrow", "Narrowed eyelids", 2),
    "003": ("eyes-open", "Open eyelids", 3),
    "003_006_011": ("eyes-open", "Open eyelids", 3),
    "004": ("eyes-wide", "Wide eyes", 4),
    "005": ("eyes-smile", "Smiling closed eyelids", 5),
    "012": ("eyes-wink-right", "Right wink shape", 12),
    "013": ("eyes-wink-left", "Left wink shape", 13),
    "014": ("eyes-troubled", "Troubled eyes", 14),
    "015": ("eyes-sad", "Sad eyes", 15),
    "016": ("eyes-angry", "Angry eyes", 16),
    "017": ("eyes-shy", "Shy eyes", 17),
    "019": ("eyes-tight", "Tightly closed eyelids", 19),
}
_MOUTH = {
    "001": ("mouth-a", "A mouth", 10001), "002": ("mouth-i", "I mouth", 10002),
    "003": ("mouth-u", "U mouth", 10003), "004": ("mouth-e", "E mouth", 10004),
    "005": ("mouth-o", "O mouth", 10005), "006": ("mouth-closed", "Closed mouth", 10006),
    "007": ("mouth-smile", "Smiling mouth", 10007), "008": ("mouth-laugh", "Laughing mouth", 10008),
    "009": ("mouth-troubled", "Troubled mouth", 10009), "010": ("mouth-sad", "Sad mouth", 10010),
    "011": ("mouth-angry", "Angry mouth", 10011), "012": ("mouth-shy", "Shy mouth", 10012),
}
_AUXILIARY = {
    "eyes-closed": ("LeftEye_LineWhite_001", "RightEye_LineWhite_001"),
    "eyes-smile": ("LeftEye_LineWhite_002", "RightEye_LineWhite_002"),
    "eyes-wink-right": ("RightEye_LineWhite_002",),
    "eyes-wink-left": ("LeftEye_LineWhite_002",),
    "eyes-tight": ("LeftEye_LineWhite_003", "RightEye_LineWhite_003"),
}
_EYE_CLIPS = {value[2]: value[1] for value in _EYE.values()}
_EYE_CLIPS.update({1: "Eyes closed", 2: "Narrow eyes", 3: "Eyes open", 4: "Eyes wide open",
                   5: "Smiling eyes", 6: "Look right", 7: "Look left", 8: "Look up", 9: "Look down",
                   10: "Look up and right", 11: "Look up and left", 12: "Right wink", 13: "Left wink",
                   19: "Eyes tightly closed", 900: "Blink"})
_CHANNEL = re.compile(r"^(EyeBlendShape\.eye_facial_|MouthBlendShape\.mouth_facial_)([0-9]{3}(?:_[0-9]{3})*)$")
_LINE = re.compile(r"^(Left|Right)EyeWhiteLineBlendShape\.\1Eye_LineWhite_([0-9]{3})$")
_CLIP = re.compile(r"(?:^|_)LiveFacial_(eye|mouth)_([0-9]{3,5})(?:__[0-9]+)?$")


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _reference(channel, value=None):
    result = {key: channel[key] for key in ("node", "index", "name")}
    if value is not None:
        result["value"] = float(value)
    return result


def _description(name, part):
    match = _CHANNEL.fullmatch(name)
    if match:
        group = "eyes" if match[1].startswith("Eye") else "mouth"
        definition = (_EYE if group == "eyes" else _MOUTH).get(match[2])
        if definition:
            return group, definition[1], definition
        return group, "Unidentified eye shape" if group == "eyes" else "Unidentified mouth shape", None
    match = _LINE.fullmatch(name)
    if match:
        return "eyes", "Left eye detail" if match[1] == "Left" else "Right eye detail", None
    return "other", "Shape channel", None


@lru_cache(maxsize=1)
def _recipes():
    try:
        raw = resources.files("webtools.core.resources").joinpath("sifas_expression_recipes.json").read_bytes()
        if len(raw) > 65536:
            return ()
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get("version") != 1 or data.get("owner") != 207
                or data.get("faceSourceHash") != _FACE_207 or data.get("space") != "gltf_local"
                or not isinstance(data.get("recipes"), list) or len(data["recipes"]) > MAX_RECIPES):
            return ()
        return tuple(data["recipes"])
    except (OSError, ImportError, UnicodeError, ValueError, TypeError, RecursionError):
        # Friendly optional labels must never prevent a valid raw model preview.
        return ()


def _complete_eyes(channels, bones, doc, sources, owner):
    if not _integer(owner) or owner != 207:
        return []
    original = [channel for channel in channels if sources.get(channel["node"], {}).get("sourceHash") == _FACE_207]
    if not original:
        return []
    by_name, by_part, by_bone = defaultdict(list), defaultdict(set), defaultdict(list)
    for channel in original:
        by_name[channel["name"]].append(channel)
        by_part[channel["part"]].add(channel["node"])
    for node, source in sources.items():
        if source.get("sourceHash") == _FACE_207 and _integer(node):
            by_part[source.get("part", "")].add(node)
    if any(len(by_part[part]) != 1 for part in ("Eye", "Eye_Around", "LeftEyeWhiteLine", "RightEyeWhiteLine")):
        return []
    for bone in bones:
        if _integer(bone.get("node")):
            by_bone[bone.get("name", "")].append(bone)
    required = ("Head_Face", "LeftEye1", "LeftEye2", "RightEye1", "RightEye2")
    if any(len(by_bone[name]) != 1 for name in required):
        return []
    head = by_bone["Head_Face"][0]["node"]
    bone_nodes = {bone["node"]: bone for bone in bones if _integer(bone.get("node"))}
    eye_nodes = [by_bone[name][0]["node"] for name in required[1:]]
    for side in ("Left", "Right"):
        prefix = "Head_Face/Face_Root/Eye_Root/%sEye_Root/%sEye1" % (side, side)
        for name, path in ((side + "Eye1", prefix), (side + "Eye2", prefix + '/' + side + "Eye2")):
            if not by_bone[name][0].get("path", "").endswith(path):
                return []
    for node in eye_nodes:
        parent, seen = node, set()
        while parent != head:
            if parent in seen or len(seen) >= 128 or parent not in bone_nodes:
                return []
            seen.add(parent)
            parent = bone_nodes[parent].get("parent")
    line_parts = ("LeftEyeWhiteLine", "RightEyeWhiteLine")
    if any(len(by_part[part]) != 1 for part in line_parts):
        return []
    nodes = doc.get("nodes", [])
    line_nodes = {part: next(iter(by_part[part])) for part in line_parts}
    if any(node >= len(nodes) for node in eye_nodes + list(line_nodes.values())):
        return []
    reset = [_reference(channel, 0) for channel in original if channel["group"] == "eyes"]
    result = []
    for recipe in _recipes():
        try:
            if not isinstance(recipe, dict) or recipe.get("id") not in {value[0] for value in _EYE.values()}:
                continue
            if (not isinstance(recipe.get("weights"), list) or len(recipe["weights"]) > 64
                    or not isinstance(recipe.get("bones"), list) or len(recipe["bones"]) > 16
                    or not isinstance(recipe.get("visibility"), list) or len(recipe["visibility"]) > 2
                    or not isinstance(recipe.get("label"), str) or len(recipe["label"]) > 128
                    or not _integer(recipe.get("semanticId"))):
                continue
            targets = {(value["node"], value["index"]): dict(value) for value in reset}
            for weight in recipe["weights"]:
                matches = by_name[weight["name"]]
                if len(matches) != 1 or not _finite(weight["value"]) or not 0 <= weight["value"] <= 1:
                    raise ValueError("Ambiguous expression target")
                target = _reference(matches[0], weight["value"])
                targets[target["node"], target["index"]] = target
            operations = []
            for operation in recipe["bones"]:
                name, kind, values = operation["name"], operation["kind"], operation["value"]
                if name not in required[1:] or kind not in ("position", "quaternion", "scale"):
                    raise ValueError("Unsupported expression bone")
                bone = by_bone[name][0]
                if not bone.get("path", "").endswith(operation["path"]):
                    raise ValueError("Unexpected expression bone hierarchy")
                if (not isinstance(values, list) or len(values) != (4 if kind == "quaternion" else 3)
                        or not all(_finite(value) and abs(value) <= 10 for value in values)):
                    raise ValueError("Unbounded expression transform")
                if kind == "quaternion" and abs(sum(value * value for value in values) - 1) > 1e-5:
                    raise ValueError("Invalid expression rotation")
                if kind == "scale" and any(value <= 0 for value in values):
                    raise ValueError("Invalid expression scale")
                operations.append({"node": bone["node"], "kind": kind, "value": list(values)})
            visibility = {node: not nodes[node].get("extras", {}).get("hidden_default", False)
                          for node in line_nodes.values()}
            for item in recipe["visibility"]:
                if item["part"] not in line_nodes or not isinstance(item["visible"], bool):
                    raise ValueError("Unsupported expression visibility")
                visibility[line_nodes[item["part"]]] = item["visible"]
            result.append({"id": recipe["id"], "group": "eyes", "label": recipe["label"],
                           "semanticId": recipe["semanticId"], "scope": "original_eye_pose",
                           "source": "verified_game_clip", "complete": True,
                           "sourceClip": recipe["clipName"], "faceSourceHash": _FACE_207, "owner": 207,
                           "targets": list(targets.values()), "bones": operations,
                           "visibility": [{"node": node, "visible": visible} for node, visible in visibility.items()],
                           "resetBones": eye_nodes, "resetVisibility": list(line_nodes.values()),
                           "note": "Original game eye pose for this verified face."})
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return result


def describe_expressions(morphs, bones, doc, *, owner=None, sources=None, clips=None):
    """Return UI-only metadata using already exported, bounded rig references."""
    sources = sources or {}
    channels, definitions = [], {}
    total_channels = sum(len(record.get("names", [])) for record in morphs if isinstance(record.get("names"), list))
    for record in morphs:
        node, names = record.get("node"), record.get("names", [])
        if not _integer(node) or node >= len(doc.get("nodes", [])) or not isinstance(names, list):
            continue
        part = sources.get(node, {}).get("part") or doc["nodes"][node].get("extras", {}).get("originalName") or doc["nodes"][node].get("name", "Part")
        weights = record.get("weights", [])
        for index, name in enumerate(names):
            if len(channels) >= MAX_CHANNELS:
                break
            if not isinstance(name, str) or len(name) > 1024:
                continue
            group, label, definition = _description(name, part)
            default = weights[index] if index < len(weights) and _finite(weights[index]) else 0
            channel = {"node": node, "index": index, "name": name, "part": part, "group": group,
                       "label": label, "known": definition is not None, "advanced": definition is None,
                       "defaultValue": default}
            if definition:
                channel["controlId"] = definition[0]
                definitions[definition[0]] = (group, definition[1], definition[2])
            channels.append(channel)
    controls = []
    for identity, (group, label, semantic) in definitions.items():
        main = [channel for channel in channels if channel.get("controlId") == identity]
        # Split renderers can share a semantic shape; two candidates on one mesh
        # are ambiguous and must remain individually available in advanced UI.
        if any(count > 1 for count in Counter(channel["node"] for channel in main).values()):
            continue
        targets = list(main)
        for suffix in _AUXILIARY.get(identity, ()):
            targets.extend(channel for channel in channels if _LINE.fullmatch(channel["name"])
                           and channel["name"].endswith('.' + suffix))
        defaults = [channel["defaultValue"] for channel in targets]
        mixed = any(abs(value - defaults[0]) > 1e-8 for value in defaults)
        controls.append({"id": identity, "group": group, "label": label, "semanticId": semantic,
                         "scope": "shape", "complete": False, "min": 0, "max": 1, "step": .01,
                         "defaultValue": None if mixed else defaults[0], "mixed": mixed,
                         "targets": [_reference(channel) for channel in targets],
                         "resetTargets": [_reference(channel) for channel in channels if channel["group"] == group],
                         "note": "Shared eyelid shape; gaze is controlled separately." if identity == "eyes-open" else "Shape control only."})
    # A complete eye recipe resets every coupled lid/white-line channel. Once
    # the optional catalog is truncated, some of those resets may be absent.
    # Keep shape/raw controls, but never advertise a partial recipe as complete.
    catalog_complete = len(channels) == total_channels
    presets = _complete_eyes(channels, bones, doc, sources, owner) if catalog_complete else []
    for control in controls:
        if control["group"] != "mouth":
            continue
        active = {(value["node"], value["index"]) for value in control["targets"]}
        presets.append({"id": control["id"], "group": "mouth", "label": control["label"],
                        "semanticId": control["semanticId"], "scope": "mouth_shape",
                        "source": "verified_morph_shape", "complete": False,
                        "targets": [_reference(channel, 1 if (channel["node"], channel["index"]) in active else 0)
                                    for channel in channels if channel["group"] == "mouth"],
                        "bones": [], "visibility": [], "resetBones": [], "resetVisibility": [],
                        "note": "Shape control only."})
    by_id = {preset["id"]: preset for preset in presets}
    for identity, label, eyes, mouth in (("smile", "Smile", "eyes-smile", "mouth-smile"),
                                       ("laugh", "Laugh", "eyes-smile", "mouth-laugh"),
                                       ("sad", "Sad", "eyes-sad", "mouth-sad"),
                                       ("angry", "Angry", "eyes-angry", "mouth-angry"),
                                       ("shy", "Shy", "eyes-shy", "mouth-shy")):
        if eyes not in by_id or mouth not in by_id:
            continue
        eye, lip = by_id[eyes], by_id[mouth]
        presets.append({"id": identity, "group": "all", "label": label, "scope": "viewer_expression",
                        "source": "viewer_combination", "complete": False, "components": [eyes, mouth],
                        "targets": eye["targets"] + lip["targets"], "bones": eye["bones"],
                        "visibility": eye["visibility"], "resetBones": eye["resetBones"],
                        "resetVisibility": eye["resetVisibility"],
                        "note": "A viewer combination of verified eye and mouth shapes."})
    for control in controls:
        if control["id"] in by_id:
            control["presetId"] = control["id"]
    clip_labels = []
    gaze_clips = []
    for clip in clips or []:
        name = clip.get("sourceName") or clip.get("name", "")
        match = _CLIP.search(name) if isinstance(name, str) else None
        if not match:
            continue
        group, index = match[1], int(match[2])
        labels = _EYE_CLIPS if group == "eye" else {value[2] - 10000: value[1] for value in _MOUTH.values()}
        if index not in labels:
            continue
        clip_labels.append({"name": clip.get("name", name), "label": labels[index],
                            "group": "eyes" if group == "eye" else "mouth",
                            "semanticId": index if group == "eye" else 10000 + index,
                            "complete": bool(clip.get("bindingComplete")),
                            "advanced": group == "eye" and (6 <= index <= 11 or index == 900)})
        if group == "eye" and 6 <= index <= 11 and clip.get("bindingComplete"):
            gaze_clips.append({"name": clip.get("name", name), "index": index,
                               "kind": "eyes", "sourceName": clip.get("sourceName", name),
                               "sourceHash": clip.get("sourceHash")})
    # Prefer the displayed character's own verified pose bank. Shared ch0001
    # is the original game's fallback; an ambiguous collection remains visible
    # to the evaluator as ambiguous rather than borrowing arbitrary endpoints.
    if _integer(owner):
        own_prefix = "ch%04d_" % owner
        own_gaze = [clip for clip in gaze_clips if clip["sourceName"].startswith(own_prefix)]
        shared_gaze = [clip for clip in gaze_clips if clip["sourceName"].startswith("ch0001_")]
        gaze_clips = own_gaze or shared_gaze or gaze_clips
    gaze_bones = [bone["node"] for bone in bones if _integer(bone.get("node")) and
                  re.fullmatch(r"(?:Left|Right)Eye(?:[12]|_Root)", bone.get("name", ""))]
    gaze = {"available": bool(gaze_clips and gaze_bones), "clips": gaze_clips,
            "nodes": gaze_bones, "horizontalLimit": 45, "verticalLimit": 30,
            "owner": owner if _integer(owner) else None}
    return {"version": 1, "available": bool(channels) or gaze["available"], "truncated": not catalog_complete,
            "rawChannelCount": total_channels, "catalogChannelLimit": MAX_CHANNELS,
            "groups": [{"id": "eyes", "label": "Eyes and brows"}, {"id": "mouth", "label": "Mouth"},
                       {"id": "other", "label": "Other expression channels"}],
            "controls": controls, "presets": presets, "rawChannels": channels, "clips": clip_labels,
            "gaze": gaze}
