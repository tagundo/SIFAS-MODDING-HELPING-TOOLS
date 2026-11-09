"""Resolve dancer clips using original Timeline bindings and exact Unity PPtrs.

This module never identifies a dancer by a camera/clip filename or by the order
of database dependencies. Only the timeline's Animator binding, serialized CAB
identity and AnimationPlayableAsset object pointer select an animation.
"""
import hashlib
import math
from pathlib import Path
import re

MAX_OBJECTS = 50000
MAX_SEGMENTS = 1024
_MEMBER_MODEL = re.compile(r"^/EntryPoint/Live/Members/Member([1-9][0-9]*)/Model$")


def _cab(value):
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _read(path, deadline):
    from .model_viewer import _environment, _remaining
    _remaining(deadline)
    env = _environment([str(path)], deadline)
    objects = list(env.objects)
    if len(objects) > MAX_OBJECTS:
        raise ValueError("The motion timeline contains too many objects.")
    scripts = {}
    for obj in objects:
        if obj.type.name == "MonoScript":
            tree = obj.read_typetree()
            scripts[(_cab(obj.assets_file.name), obj.path_id)] = tree.get("m_ClassName", "")
    return {"path": Path(path), "env": env, "objects": objects, "scripts": scripts}


def _object_key(obj):
    return _cab(obj.assets_file.name), obj.path_id


def _pointer_key(obj, pointer):
    file_id, path_id = pointer.get("m_FileID"), pointer.get("m_PathID")
    if type(file_id) is not int or type(path_id) is not int or path_id == 0:
        raise ValueError("The selected motion contains an invalid clip reference.")
    if file_id == 0:
        return _cab(obj.assets_file.name), path_id
    if not 1 <= file_id <= len(obj.assets_file.externals):
        raise ValueError("The selected motion references an unavailable serialized file.")
    return _cab(obj.assets_file.externals[file_id - 1].path), path_id


def _class(source, obj, tree):
    try:
        return source["scripts"].get(_pointer_key(obj, tree.get("m_Script", {})), "")
    except ValueError:
        return ""


def _number(value, label, *, minimum=0, maximum=600):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("The motion timeline has an invalid " + label + ".")
    return float(value)


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def describe_clip_roles(scene, deadline=None):
    """Identify original camera/body/facial clips through serialized references.

    Camera AnimationClips often animate path zero, which can also bind a
    character root. Their actual Timeline binding is authoritative; neither
    curve target names nor clip filenames can distinguish that case safely.
    """
    from .model_viewer import _remaining
    objects = list(scene.env.objects)
    if len(objects) > MAX_OBJECTS:
        raise ValueError("The animation sources contain too many objects.")
    scripts, mono = {}, {}
    for obj in objects:
        if deadline is not None:
            _remaining(deadline)
        if not hasattr(obj, "assets_file"):
            continue
        if obj.type.name == "MonoScript":
            try:
                scripts[_object_key(obj)] = scene.tree(obj).get("m_ClassName", "")
            except (ValueError, TypeError):
                continue
    source = {"scripts": scripts}
    for obj in objects:
        if deadline is not None:
            _remaining(deadline)
        if obj.type.name == "MonoBehaviour" and hasattr(obj, "assets_file"):
            try:
                tree = scene.tree(obj)
            except (ValueError, TypeError):
                continue
            mono[_object_key(obj)] = (obj, tree, _class(source, obj, tree))

    def track_path(key):
        parts, seen = [], set()
        while key in mono and key not in seen and len(seen) < 256:
            seen.add(key)
            obj, tree, kind = mono[key]
            if kind == "TimelineAsset":
                return "/" + "/".join(reversed(parts))
            parts.append(str(tree.get("m_Name", "")))
            try:
                key = _pointer_key(obj, tree.get("m_Parent", {}))
            except ValueError:
                break
        return "/" + "/".join(reversed(parts))

    bindings, roles = {}, {}

    def mark(key, role):
        roles.setdefault(key, set()).add(role)

    for key, (obj, tree, kind) in mono.items():
        if kind == "TimelineAssetBindingInfo":
            for binding in tree.get("bindingInfos", [])[:MAX_SEGMENTS]:
                if binding.get("playableAssetTypeName", "").split(",", 1)[0] != "UnityEngine.Timeline.AnimationTrack":
                    continue
                target = binding.get("bindObjectPath", "")
                role = "body" if _MEMBER_MODEL.fullmatch(target) else "camera" if re.fullmatch(r"/EntryPoint/Live/Cameras/[^/]+", target) else None
                if role:
                    bindings.setdefault((key[0], binding.get("playableAssetPath")), set()).add(role)
        elif kind == "MemberFacialAnimationDataTable":
            for entry in tree.get("datas", [])[:256]:
                try:
                    mark(_pointer_key(obj, entry.get("clip", {})), "facial")
                except ValueError:
                    continue
    for key, (obj, tree, kind) in mono.items():
        if kind != "AnimationTrack":
            continue
        bound_roles = bindings.get((key[0], track_path(key)), ())
        if not bound_roles:
            continue
        for clip in tree.get("m_Clips", [])[:MAX_SEGMENTS]:
            try:
                playable = mono.get(_pointer_key(obj, clip.get("m_Asset", {})))
                if not playable or playable[2] != "AnimationPlayableAsset":
                    continue
                animation = _pointer_key(playable[0], playable[1].get("m_Clip", {}))
                for role in bound_roles:
                    mark(animation, role)
            except ValueError:
                continue
    return {key: next(iter(value)) if len(value) == 1 else "mixed" for key, value in roles.items()}


def select(timeline_path, candidate_paths, *, performer=1, category="mv", deadline):
    """Return exact selected source clips and authored timeline segments.

    ``candidate_paths`` are already bounded imports of DB-listed dependencies.
    They cannot introduce dependencies that the selected timeline never names.
    """
    timeline = _read(timeline_path, deadline)
    sources = [_read(path, deadline) for path in candidate_paths]
    object_map, source_map = {}, {}
    for source in [timeline] + sources:
        for obj in source["objects"]:
            key = _object_key(obj)
            if key in object_map and object_map[key].get_raw_data() != obj.get_raw_data():
                raise ValueError("Two motion dependencies have conflicting serialized identities.")
            object_map[key] = obj
            source_map[key] = source
    mono, classes = {}, {}
    for obj in timeline["objects"]:
        if obj.type.name == "MonoBehaviour":
            tree = obj.read_typetree()
            mono[obj.path_id] = (obj, tree)
            classes[obj.path_id] = _class(timeline, obj, tree)

    def track_path(path_id):
        parts, seen = [], set()
        while path_id in mono and path_id not in seen:
            seen.add(path_id)
            _, tree = mono[path_id]
            if classes[path_id] == "TimelineAsset":
                break
            parts.append(str(tree.get("m_Name", "")))
            parent = tree.get("m_Parent", {})
            if parent.get("m_FileID", 0) != 0:
                break
            path_id = parent.get("m_PathID")
        return "/" + "/".join(reversed(parts))

    selected_tracks = set()
    if category == "mv":
        bound_paths = set()
        for path_id, (_, tree) in mono.items():
            if classes[path_id] != "TimelineAssetBindingInfo":
                continue
            for binding in tree.get("bindingInfos", []):
                match = _MEMBER_MODEL.fullmatch(binding.get("bindObjectPath", ""))
                if (match and int(match.group(1)) == performer and
                        binding.get("bindObjectTypeName", "").split(",", 1)[0] in ("UnityEngine.Animator", "UnityEngine.GameObject") and
                        binding.get("playableAssetTypeName", "").split(",", 1)[0] == "UnityEngine.Timeline.AnimationTrack"):
                    bound_paths.add(binding.get("playableAssetPath"))
        selected_tracks = {path_id for path_id in mono if classes[path_id] == "AnimationTrack" and track_path(path_id) in bound_paths}
        if not selected_tracks:
            raise ValueError(f"The original timeline has no Animator dance binding for performer {performer}. Camera tracks cannot animate a character.")
    else:
        # The original Navi player binds its AnimationTracks to its one model.
        # Semantic facial, voice, rotation and camera tracks have other scripts.
        selected_tracks = {path_id for path_id in mono if classes[path_id] == "AnimationTrack"}
        if not selected_tracks:
            raise ValueError("This original navigation timeline has no model AnimationTrack.")

    segments, selected = [], {}
    for path_id in sorted(selected_tracks):
        track_obj, track = mono[path_id]
        if track.get("m_Muted"):
            continue
        clips = track.get("m_Clips", [])
        if len(segments) + len(clips) > MAX_SEGMENTS:
            raise ValueError("This motion timeline has too many animation segments.")
        for clip in clips:
            playable_key = _pointer_key(track_obj, clip.get("m_Asset", {}))
            playable = object_map.get(playable_key)
            if playable is None or playable.type.name != "MonoBehaviour":
                raise ValueError("An original motion playable could not be resolved from its dependencies.")
            playable_tree = playable.read_typetree()
            if _class(source_map[playable_key], playable, playable_tree) != "AnimationPlayableAsset":
                raise ValueError("An Animator track references an unsupported playable type.")
            animation_key = _pointer_key(playable, playable_tree.get("m_Clip", {}))
            animation = object_map.get(animation_key)
            if animation is None or animation.type.name != "AnimationClip":
                raise ValueError("The dancer AnimationClip is missing from its exact CAB/object dependency. Open the original game packs again.")
            source = source_map[animation_key]
            start = _number(clip.get("m_Start", 0), "start time")
            duration = _number(clip.get("m_Duration", 0), "duration")
            speed = _number(clip.get("m_TimeScale", 1), "playback speed", minimum=1e-6, maximum=100)
            offset = _number(clip.get("m_ClipIn", 0), "clip offset")
            if start + duration > 600:
                raise ValueError("This motion exceeds the supported timeline duration.")
            selected[animation_key] = {"object": animation, "source": source}
            from .game_motion_timeline import timing
            segments.append({"key": animation_key, "sourceName": animation.peek_name(), "start": start, "duration": duration,
                             "clipIn": offset, "timeScale": speed, "track": track_path(path_id),
                             "timing": timing(clip)})
    if not selected:
        raise ValueError("The selected original model track contains no AnimationClip. Camera-only timelines cannot be used as dances.")
    return {"timeline": timeline, "selected": selected, "segments": sorted(segments, key=lambda item: (item["start"], item["sourceName"]))}


def animation_only(path, *, deadline):
    source = _read(path, deadline)
    selected = {_object_key(obj): {"object": obj, "source": source} for obj in source["objects"] if obj.type.name == "AnimationClip"}
    if not selected:
        raise ValueError("The selected motion asset contains no AnimationClip.")
    segments = []
    if len(selected) == 1:
        from .model_animation import decode_clip
        key, entry = next(iter(selected.items()))
        clip = decode_clip(entry["object"].read_typetree(), deadline)
        segments.append({"key": key, "sourceName": clip["name"], "start": 0., "duration": clip["duration"],
                         "clipIn": 0., "timeScale": 1., "track": "/DirectAnimation", "timing": {}, "loop": clip["loop"]})
    return {"timeline": None, "selected": selected, "segments": segments}


def facial_banks(paths, *, deadline):
    """Read the game's exact index/custom-index -> AnimationClip table.

    Semantic ids are the client's FacialAnimationId values: eyes below 10000,
    mouth in the 10000 range. This preserves aliases such as eye101 -> eye005
    without guessing a clip filename from an event's index.
    """
    sources = [_read(path, deadline) for path in paths]
    objects = {_object_key(obj): (obj, source) for source in sources for obj in source["objects"]}
    selected, entries = {}, []
    for source in sources:
        for obj in source["objects"]:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = obj.read_typetree()
            if _class(source, obj, tree) != "MemberFacialAnimationDataTable":
                continue
            datas = tree.get("datas", [])
            if not isinstance(datas, list) or len(datas) > 256:
                raise ValueError("The original facial animation table exceeds its limit.")
            for data in datas:
                index, summary = data.get("index"), data.get("summary")
                if type(index) is not int or type(summary) is not int or not 0 < index < 10000:
                    continue
                kind = "eyes" if 0 < summary < 10000 else "mouth" if 10000 <= summary < 20000 else None
                pointer = data.get("clip", {})
                if kind is None or pointer.get("m_PathID", 0) == 0:
                    continue
                key = _pointer_key(obj, pointer)
                resolved = objects.get(key)
                if not resolved or resolved[0].type.name != "AnimationClip":
                    raise ValueError("The facial table references a missing original AnimationClip.")
                animation, owner = resolved
                selected[key] = {"object": animation, "source": owner}
                entries.append({"key": key, "kind": kind, "index": index, "customIndex": data.get("customIndex", 0), "summary": summary})
    return {"timeline": None, "selected": selected, "segments": []}, entries


def write_selected(selection, directory):
    """Write clips only, so donor skeletons and camera clips cannot enter a model."""
    groups = {}
    for key, entry in selection["selected"].items():
        source = entry["source"]
        groups.setdefault(str(source["path"]), {"source": source, "keys": set()})["keys"].add(key)
    files, identities = [], {}
    for index, group in enumerate(groups.values()):
        source, keep = group["source"], group["keys"]
        for obj in source["objects"]:
            if _object_key(obj) not in keep:
                del obj.assets_file.objects[obj.path_id]
        containers = list(source["env"].files.values())
        if len(containers) != 1:
            raise ValueError("An imported motion has an ambiguous source container.")
        raw = containers[0].save(packer="lz4")
        path = Path(directory) / f"animation-{index + 1}.unity"
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        files.append({"path": path, "sha256": digest})
        for key in keep:
            obj = selection["selected"][key]["object"]
            identities[key] = {"sourceHash": digest, "sourceName": obj.peek_name()}
    segments = []
    for segment in selection["segments"]:
        segment = dict(segment)
        key = segment.pop("key")
        segment.update(identities[key])
        segments.append(segment)
    return files, segments, list(identities.values()), identities
