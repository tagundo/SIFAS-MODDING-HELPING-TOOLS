"""Read the selected performer's original, bounded facial Timeline tracks.

Only server-verified local imports call this module. Unity object pointers and
parent groups determine ownership; camera and other performers are excluded.
"""
import math
import re
import time

MAX_EVENTS = 12000
_VOWELS = {"a": 1, "i": 2, "u": 3, "e": 4, "o": 5, "n": 6, "m": 6}


def _finite(value, default=0., low=0., high=600.):
    if type(value) not in (int, float) or not math.isfinite(value):
        return default
    return min(high, max(low, float(value)))


def _curve(value):
    result = []
    for key in (value or {}).get("m_Curve", [])[:128]:
        if not isinstance(key, dict):
            continue
        result.append({name: _finite(key.get(name), low=-10000, high=10000)
                       for name in ("time", "value", "inSlope", "outSlope")})
    return result


def timing(clip):
    return {"easeIn": _finite(clip.get("m_EaseInDuration")),
            "easeOut": _finite(clip.get("m_EaseOutDuration")),
            "blendIn": _finite(clip.get("m_BlendInDuration"), -1, low=-1),
            "blendOut": _finite(clip.get("m_BlendOutDuration"), -1, low=-1),
            "mixIn": _curve(clip.get("m_MixInCurve")),
            "mixOut": _curve(clip.get("m_MixOutCurve")),
            "preMode": int(_finite(clip.get("m_PreExtrapolationMode"), high=4)),
            "postMode": int(_finite(clip.get("m_PostExtrapolationMode"), high=4)),
            "preTime": _finite(clip.get("m_PreExtrapolationTime")),
            "postTime": _finite(clip.get("m_PostExtrapolationTime"))}


def parse_timeline(path, performer=1, *, segments=None):
    from .game_motion_selection import _read, _class
    source = _read(path, time.monotonic() + 30)
    mono, classes = {}, {}
    for obj in source["objects"]:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        mono[obj.path_id] = tree
        classes[obj.path_id] = _class(source, obj, tree)

    def belongs(tree):
        seen = set()
        while tree:
            name = tree.get("m_Name", "")
            member = re.fullmatch(r"Member([1-9][0-9]*)", name)
            if member:
                return int(member[1]) == int(performer)
            parent = tree.get("m_Parent", {})
            identity = parent.get("m_PathID")
            if parent.get("m_FileID", 0) or identity in seen:
                break
            seen.add(identity)
            tree = mono.get(identity)
        # Navi tracks have no numbered member parent.
        return not any(re.fullmatch(r"Member[1-9][0-9]*", value.get("m_Name", ""))
                       for value in mono.values())

    events, warnings = [], []
    types = {"MemberLipSyncTrack": "mouth", "MemberEyeTrack": "eyes",
             "MemberGazeTrack": "gaze", "MemberCheekTrack": "cheek"}
    for identity, tree in mono.items():
        kind = types.get(classes[identity])
        if not kind or tree.get("m_Muted") or not belongs(tree):
            continue
        for clip in tree.get("m_Clips", []):
            pointer = clip.get("m_Asset", {})
            if pointer.get("m_FileID", 0):
                warnings.append("An external facial event could not be resolved.")
                continue
            asset = mono.get(pointer.get("m_PathID"))
            if not asset:
                continue
            duration = _finite(clip.get("m_Duration"))
            if not duration:
                continue
            index = int(_finite(asset.get("index"), high=10000))
            if kind == "mouth" and index == 0:
                index = _VOWELS.get(str(asset.get("paramName", "")).lower(), 0)
            event = {"kind": kind, "index": index,
                     "start": _finite(clip.get("m_Start")), "duration": duration,
                     "clipIn": _finite(clip.get("m_ClipIn")),
                     "timeScale": _finite(clip.get("m_TimeScale"), 1, low=.001, high=100),
                     "weight": _finite(asset.get("weight", asset.get("weightForDirection")), 1, high=1),
                     "label": str(clip.get("m_DisplayName", ""))[:128], "timing": timing(clip)}
            if kind == "gaze":
                event["target"] = int(_finite(asset.get("target"), high=1000))
            events.append(event)
            if len(events) > MAX_EVENTS:
                raise ValueError("The selected facial timeline contains too many events.")
    events.sort(key=lambda event: (event["start"], event["kind"]))
    duration = max([event["start"] + event["duration"] for event in events] +
                   [float(segment["start"]) + float(segment["duration"]) for segment in segments or []] + [0.])
    return {"version": 1, "performer": int(performer), "duration": duration,
            "events": events, "warnings": sorted(set(warnings))}
