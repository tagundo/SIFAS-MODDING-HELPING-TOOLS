"""Unity RotationConstraint / PositionConstraint components of a member rig.

The GL 3.12 player (Unity 2018.4.23f1) registers only these two constraint
classes; Aim, Parent, Scale and LookAt are stripped ``[UNREGISTERED]`` types
in its libunity.so, so a bundle that carried them would not evaluate them.
The client never changes these components at runtime: no Assembly-CSharp code
reads ``BodyPartManager.timelineConstraints`` and
``LiveCoreMemberManager.SetAllSkirtConstraint`` (0x2f6ac70) never reaches
``BodyPartManager.SetSkirtConstraint`` (0x27c04a8). The serialized values are
therefore the whole input of the native ConstraintManager.
"""
import hashlib
import math

MAX_CONSTRAINTS = 256
_KINDS = {"RotationConstraint": ("rotation", "m_RotationAtRest", "m_RotationOffset", "m_AffectRotation"),
          "PositionConstraint": ("position", "m_TranslationAtRest", "m_TranslationOffset", "m_AffectTranslation")}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value):
    return [float(value[a]) for a in "xyz"] if isinstance(value, dict) and all(_finite(value.get(a)) for a in "xyz") else None


def _local(pointer):
    if not isinstance(pointer, dict) or pointer.get("m_FileID", 0) != 0 or not pointer.get("m_PathID"):
        return None
    return pointer["m_PathID"]


def inspect_info(info, source_index, bones):
    """Serialized constraints bound to preview nodes of one selected source."""
    nodes = {(int(b.get("serializedFile", 0)), str(b["transformId"])): b["node"]
             for b in bones if b.get("sourceIndex") == source_index and "transformId" in b}
    by_game_object, game_objects = {}, {}
    for key, tree in info["transforms"].items():
        pointer = tree.get("m_GameObject") or {}
        if pointer.get("m_FileID", 0) == 0:
            by_game_object[(key[0], pointer.get("m_PathID"))] = key

    def active(key, seen=()):
        # GameObject.activeInHierarchy: a constraint registers with the
        # ConstraintManager only while its Behaviour is enabled and active.
        if key in seen or len(seen) > 256:
            raise ValueError("A constraint transform has a circular hierarchy.")
        tree = info["transforms"][key]
        pointer = tree.get("m_GameObject") or {}
        game_key = (key[0], pointer.get("m_PathID"))
        if game_key not in game_objects:
            game = info["objects"].get(game_key) if pointer.get("m_FileID", 0) == 0 else None
            game_objects[game_key] = bool(game.read_typetree().get("m_IsActive", True)) if game is not None else False
        parent = info["parents"].get(key)
        return game_objects[game_key] and (active(parent, (*seen, key)) if parent in info["transforms"] else True)

    def node(file_index, path_id):
        key = by_game_object.get((file_index, path_id))
        return key, nodes.get((key[0], str(key[1]))) if key else None

    timeline = set()
    for key, obj in info["objects"].items():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        listed = tree.get("timelineConstraints")
        if isinstance(listed, list):
            timeline.update((key[0], path_id) for pointer in listed if (path_id := _local(pointer)))

    records = []
    for key, obj in info["objects"].items():
        layout = _KINDS.get(obj.type.name)
        if layout is None:
            continue
        kind, rest_field, offset_field, axis_prefix = layout
        try:
            tree = obj.read_typetree()
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        rest, offset, weight = _vector(tree.get(rest_field)), _vector(tree.get(offset_field)), tree.get("m_Weight")
        axes = [tree.get(axis_prefix + axis) for axis in "XYZ"]
        sources = tree.get("m_Sources")
        target_object = _local(tree.get("m_GameObject"))
        if (rest is None or offset is None or not _finite(weight) or not isinstance(sources, list) or
                any(type(value) not in (bool, int) for value in axes) or target_object is None):
            continue
        target_key, target = node(key[0], target_object)
        if target_key is None or target is None:
            continue
        rows = []
        for source in sources[:MAX_CONSTRAINTS]:
            if not isinstance(source, dict) or not _finite(source.get("weight")):
                continue
            transform = _local(source.get("sourceTransform"))
            transform_key = (key[0], transform) if transform else None
            rows.append({"node": nodes.get((key[0], str(transform))) if transform_key in info["transforms"] else None,
                         "weight": float(source["weight"])})
        records.append({
            "id": f"{source_index}:{key[0]}:{key[1]}", "kind": kind, "sourceIndex": source_index,
            "node": target, "name": info["names"].get(target_key, ""),
            "enabled": bool(tree.get("m_Enabled", 1)), "activeInHierarchy": active(target_key),
            "constraintActive": bool(tree.get("m_IsContraintActive", False)),
            "weight": float(weight), "atRest": rest, "offset": offset, "axes": [bool(value) for value in axes],
            "sources": rows, "timeline": (key[0], key[1]) in timeline,
        })
        if len(records) > MAX_CONSTRAINTS:
            raise ValueError("The model has too many constraint components.")
    return records


def catalogue_preview(paths, bones):
    """Bind an existing rig to the constraint components of the same bytes."""
    from .model_edits import _inspect

    records = []
    for index, path in enumerate(paths):
        selected = [bone for bone in bones if bone.get("sourceIndex") == index and "transformId" in bone]
        if not selected:
            continue
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if any(bone.get("sourceHash") != checksum for bone in selected):
            raise ValueError("The performer changed while its constraint data was being read.")
        info = _inspect(raw, saved_scaling=False)
        serialized = {}
        for file_index, path_id in info["transforms"]:
            serialized.setdefault(str(path_id), []).append(file_index)
        bound = [{**bone, "serializedFile": matches[0]}
                 for bone in selected if len(matches := serialized.get(str(bone["transformId"]), ())) == 1]
        records.extend(inspect_info(info, index, bound))
        if len(records) > MAX_CONSTRAINTS:
            raise ValueError("The selected models have too many constraint components.")
    return {"available": bool(records), "constraints": records, "runtime": "unity-2018.4.23f1"}
