"""Source-bound SwingBone and SwingCollider inspection and absolute editing.

The serialized values are the game's original fields. The browser's spring
preview is an approximation; exporting never bakes that approximation into the
mesh. Component identity includes source, serialized file and Unity PathID.
"""
import copy
import math

MAX_COMPONENTS = 512
SCALAR_FIELDS = {"bone": {"stiffnessForce": (0., 10.), "dragForce": (0., 1.)},
                 "collider": {"radius": (0., 10.)}}
VECTOR_FIELDS = {"bone": {"lowRotationLimit": 180., "highRotationLimit": 180.},
                 "collider": {"offset": 10.}}


def _field(tree, name):
    if name in tree:
        return tree[name]
    return tree.get("Base", {}).get(name)


def _set(tree, name, value):
    if name in tree:
        tree[name] = value
    elif name in tree.get("Base", {}):
        tree["Base"][name] = value
    else:
        raise ValueError("The original physics component no longer has this field.")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value):
    return [float(value[a]) for a in "xyz"] if isinstance(value, dict) and all(_finite(value.get(a)) for a in "xyz") else None


def _local(obj, pointer):
    if not isinstance(pointer, dict) or pointer.get("m_FileID", 0) != 0:
        return None
    return obj.assets_file.objects.get(pointer.get("m_PathID"))


def recommendations():
    """Exact presets from sifas_breast_tuner's Physics parameter buttons.

    The collider tool deliberately provides no universal radius recommendation;
    its default is to retain the source's independently authored capsule ends.
    """
    return [{"id": "softer", "label": "Softer", "stiffnessForce": .01, "dragForce": .2},
            {"id": "soft", "label": "Soft", "stiffnessForce": .02, "dragForce": .3},
            {"id": "firm", "label": "Firm", "stiffnessForce": .05, "dragForce": .5}]


def inspect_info(info, source_index, bones):
    nodes = {(int(b.get("serializedFile", 0)), str(b["transformId"])): b["node"]
             for b in bones if b.get("sourceIndex") == source_index and "transformId" in b}
    game_transforms = {}
    for key, tree in info["transforms"].items():
        ptr = tree.get("m_GameObject", {})
        if ptr.get("m_FileID", 0) == 0:
            game_transforms[(key[0], ptr.get("m_PathID"))] = key
    paths = {}
    def path(key, active=None):
        if key in paths:
            return paths[key]
        active = set() if active is None else active
        if key in active or len(active) > 256:
            raise ValueError("A physics bone has a circular hierarchy.")
        active.add(key)
        parent = info["parents"].get(key)
        value = (path(parent, active) + "/" if parent in info["transforms"] else "") + info["names"].get(key, "")
        active.remove(key)
        paths[key] = value
        return value
    records = []
    for key, obj in info["objects"].items():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
            script = _local(obj, _field(tree, "m_Script"))
            cls = script.read_typetree().get("m_ClassName", "") if script and script.type.name == "MonoScript" else ""
            if cls.rsplit(".", 1)[-1] == "SwingBone":
                kind = "bone"
            elif cls.rsplit(".", 1)[-1] == "SwingCollider":
                kind = "collider"
            else:
                continue
            values = {name: float(_field(tree, name)) for name in SCALAR_FIELDS[kind] if _finite(_field(tree, name))}
            values.update({name: _vector(_field(tree, name)) for name in VECTOR_FIELDS[kind] if _vector(_field(tree, name)) is not None})
            if set(values) != set(SCALAR_FIELDS[kind]) | set(VECTOR_FIELDS[kind]):
                continue
            game = _field(tree, "m_GameObject") or {}
            transform_key = game_transforms.get((key[0], game.get("m_PathID"))) if game.get("m_FileID", 0) == 0 else None
            if transform_key is None:
                continue
            name = info["names"].get(transform_key, "")
            record = {"id": f"{source_index}:{key[0]}:{key[1]}", "kind": kind,
                      "sourceIndex": source_index, "serializedFile": key[0], "componentId": str(key[1]),
                      "transformId": str(transform_key[1]), "node": nodes.get((transform_key[0], str(transform_key[1]))),
                      "name": name, "path": path(transform_key), "values": values,
                      "enabled": bool(_field(tree, "m_Enabled") if _field(tree, "m_Enabled") is not None else True),
                      "group": "breast" if "breast" in name.lower() else "thighs" if "upleg" in name.lower() or "thigh" in name.lower() else "other"}
            if kind == "collider":
                slot = _field(tree, "siblingIndex")
                if type(slot) is int and 0 <= slot <= MAX_COMPONENTS:
                    record["siblingIndex"] = slot
                sibling = _field(tree, "sibling") or {}
                if sibling.get("m_FileID", 0) == 0 and sibling.get("m_PathID"):
                    record["sibling"] = f"{source_index}:{key[0]}:{sibling['m_PathID']}"
            else:
                gravity = _vector(_field(tree, "gravity"))
                if gravity is not None:
                    record["gravity"] = gravity
            records.append(record)
            if len(records) > MAX_COMPONENTS:
                raise ValueError("The model has too many physics components for preview editing.")
        except (KeyError, TypeError, AttributeError):
            continue
    return records


def catalog_sources(sources, bones):
    from .model_edits import _inspect
    records = []
    for index, source in enumerate(sources):
        records.extend(inspect_info(_inspect(source["raw"]), index, bones))
        if len(records) > MAX_COMPONENTS:
            raise ValueError("The selected models have too many physics components.")
    return {"available": bool(records), "components": records, "presets": recommendations(),
            "recommendationSource": "sifas_breast_tuner.py / Upleg_SwingCollider_changer.py",
            "preview": "approximate_spring_sphere_capsule"}


def validate_edits(catalog, edits):
    if not isinstance(edits, list) or len(edits) > MAX_COMPONENTS:
        raise ValueError("Choose a bounded list of physics component edits.")
    components = {row["id"]: row for row in catalog.get("components", [])}
    normalized, seen = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"id", "values"} or not isinstance(edit["id"], str):
            raise ValueError("A physics edit must identify an original component and its values.")
        ident = edit["id"]
        if ident not in components or ident in seen:
            raise ValueError("A physics edit is duplicated or does not belong to this model.")
        seen.add(ident)
        component = components[ident]
        values, out = edit["values"], {}
        kind = component["kind"]
        if not isinstance(values, dict) or not values or set(values) - set(component["values"]):
            raise ValueError("The selected physics property is unsupported.")
        for name, value in values.items():
            if name in SCALAR_FIELDS[kind]:
                low, high = SCALAR_FIELDS[kind][name]
                if not _finite(value) or not low <= value <= high:
                    raise ValueError(f"Physics {name} must be between {low:g} and {high:g}.")
                out[name] = float(value)
            else:
                bound = VECTOR_FIELDS[kind][name]
                if not isinstance(value, list) or len(value) != 3 or any(not _finite(v) or abs(v) > bound for v in value):
                    raise ValueError(f"Physics {name} must contain finite XYZ values within ±{bound:g}.")
                out[name] = [float(v) for v in value]
        merged = {**component["values"], **out}
        if kind == "bone" and any(a > b for a, b in zip(merged["lowRotationLimit"], merged["highRotationLimit"])):
            raise ValueError("Each low rotation limit must be at most its high rotation limit.")
        normalized.append({"id": ident, "values": out})
    return sorted(normalized, key=lambda r: r["id"])


def apply_edits(raw, source_index, edits, catalog):
    from .model_edits import _inspect
    components = {row["id"]: row for row in catalog.get("components", [])}
    selected = [row for row in edits if components[row["id"]]["sourceIndex"] == source_index]
    if not selected:
        return raw
    info = _inspect(raw)
    for edit in selected:
        record = components[edit["id"]]
        key = record["serializedFile"], int(record["componentId"])
        obj = info["objects"].get(key)
        if obj is None or obj.type.name != "MonoBehaviour":
            raise ValueError("The source physics component is no longer available.")
        tree = obj.read_typetree()
        for name, value in edit["values"].items():
            if isinstance(value, list):
                target = copy.deepcopy(_field(tree, name))
                if not isinstance(target, dict):
                    raise ValueError("The source physics vector is no longer available.")
                target.update(dict(zip("xyz", value)))
                _set(tree, name, target)
            else:
                _set(tree, name, value)
        obj.save_typetree(tree)
    blob = info["env"].file.save(packer="original")
    reloaded = _inspect(blob)
    for edit in selected:
        record = components[edit["id"]]
        tree = reloaded["objects"][(record["serializedFile"], int(record["componentId"]))].read_typetree()
        for name, expected in edit["values"].items():
            actual = _vector(_field(tree, name)) if isinstance(expected, list) else _field(tree, name)
            pairs = zip(actual, expected) if isinstance(expected, list) else [(actual, expected)]
            if any(not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7) for a, b in pairs):
                raise ValueError("A saved physics value failed reload validation.")
    return blob
