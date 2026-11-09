"""Source-bound SwingBone and SwingCollider inspection and absolute editing.

The serialized values are the game's original fields. Source game calculation
and additional mesh correction are separate preview modes; neither preview is
baked into exported geometry. Component identity includes source, serialized
file and Unity PathID.
"""
import copy
import math
import struct

MAX_COMPONENTS = 512
SCALAR_FIELDS = {"bone": {"stiffnessForce": (0., 10.), "dragForce": (0., 1.)},
                 "collider": {"radius": (0., 10.)}}
VECTOR_FIELDS = {"bone": {"lowRotationLimit": 180., "highRotationLimit": 180.},
                 "collider": {"offset": 10.}}

# Older bundles omit fields added to the runtime class. Unity runs the managed
# constructor before deserialization, so those fields retain the constructor's
# values. Captured by executing GL 3.12 SwingBone..ctor at RVA 0x2c99b90;
# tests/fixtures/game_physics_native_constructor.json records the boundaries.
# Do not use these for serialized-but-invalid values or unrelated missing facts.
_CONSTRUCTOR_DEFAULTS = {name: struct.unpack("<f", bytes.fromhex(bits))[0] for name, bits in (
    ("kneeSpaceOffsetFront", "0ad7a33c"),
    ("kneeSpaceOffsetOther", "0ad7233d"),
    ("kneeSpaceOffsetForce", "cdcc4c3e"),
)}

# Exact size/tier entries from sifas_breast_tuner.BREAST_PRESETS_ALL. Keep this
# small conversion metadata independent of the desktop tuner's UI imports.
_BREAST_SIZE_TIERS = (
    ((.61, .91, .85), 0), ((.64, .94, .88), 0), ((.72, .95, .90), 1),
    ((.80, .96, .92), 2), ((.90, .98, .96), 3), ((.95, .99, .98), 3),
    ((1.04, 1.02, 1.04), 5), ((1.08, 1.04, 1.08), 5), ((1.12, 1.06, 1.12), 6),
    ((1.14, 1.07, 1.14), 4), ((1.16, 1.08, 1.16), 6), ((1.20, 1.10, 1.20), 6),
    ((1.22, 1.11, 1.22), 7), ((1.30, 1.15, 1.30), 7), ((1.30, 1.18, 1.30), 7),
)


def _stock_jiggle_tier(info):
    """Identify stock shape only from unambiguous original body textures."""
    from .charinfo import JIGGLE
    characters = set()
    for obj in info["objects"].values():
        if obj.type.name != "Texture2D":
            continue
        name = obj.read_typetree().get("m_Name", "")
        if not isinstance(name, str) or not name.startswith("ch") or "_body" not in name:
            continue
        character = name[2:name.find("_")]
        if len(character) == 4 and character.isascii() and character.isdigit():
            characters.add(int(character))
    return JIGGLE.get(next(iter(characters))) if len(characters) == 1 else None


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
    stock_jiggle_tier = _stock_jiggle_tier(info)
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
    records, managers = [], []
    def reference(key, pointer):
        if isinstance(pointer, dict) and pointer.get("m_FileID", 0) == 0 and pointer.get("m_PathID"):
            return f"{source_index}:{key[0]}:{pointer['m_PathID']}"
        return None
    for key, obj in info["objects"].items():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
            script = _local(obj, _field(tree, "m_Script"))
            cls = script.read_typetree().get("m_ClassName", "") if script and script.type.name == "MonoScript" else ""
            cls = cls.rsplit(".", 1)[-1]
            if cls == "SwingBoneManager":
                managers.append((key, tree))
                continue
            if cls == "SwingBone":
                kind = "bone"
            elif cls == "SwingCollider":
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
                # These fields determine the actual contact geometry and graph.
                # In particular, a skirt's endpoint is the explicit Transform
                # PPtr, not the first child in arbitrary glTF node order.
                simulation = {}
                for field in ("radius", "skirtLimitDotMin", "skirtLimitDotMax", "skirtRotDegMax",
                              "kneeSpaceOffsetFront", "kneeSpaceOffsetOther", "kneeSpaceOffsetForce"):
                    value = _field(tree, field)
                    if _finite(value):
                        simulation[field] = float(value)
                defaults = []
                for field, value in _CONSTRUCTOR_DEFAULTS.items():
                    if field not in tree and field not in tree.get("Base", {}):
                        simulation[field] = value
                        defaults.append(field)
                if defaults:
                    simulation["constructorDefaults"] = defaults
                for field in ("boneAxis", "externalForce", "gravity"):
                    value = _vector(_field(tree, field))
                    if value is not None:
                        simulation[field] = value
                for field in ("parentIndex", "childIndex", "siblingIndex", "colliderBits", "skirtData"):
                    value = _field(tree, field)
                    if type(value) is int:
                        simulation[field] = value
                simulation["skirtSafeEnable"] = bool(_field(tree, "skirtSafeEnable"))
                lod = _field(tree, "enableLod")
                if type(lod) in (bool, int) and lod in (0, 1):
                    simulation["enableLod"] = bool(lod)
                child = _field(tree, "child") or {}
                if child.get("m_FileID", 0) == 0 and child.get("m_PathID"):
                    child_key = key[0], child["m_PathID"]
                    simulation["childNode"] = nodes.get((key[0], str(child["m_PathID"])))
                    child_tree = info["transforms"].get(child_key)
                    if child_tree is not None and info["parents"].get(child_key) == transform_key:
                        simulation["childOffset"] = _vector(child_tree.get("m_LocalPosition"))
                sibling = reference(key, _field(tree, "sibling"))
                if sibling:
                    simulation["sibling"] = sibling
                colliders = _field(tree, "colliders")
                if isinstance(colliders, list):
                    simulation["colliders"] = [value for p in colliders[:MAX_COMPONENTS]
                                               if (value := reference(key, p)) is not None]
                ids = _field(tree, "colliderIds")
                if isinstance(ids, list) and len(ids) <= MAX_COMPONENTS and all(type(v) is int for v in ids):
                    simulation["colliderIds"] = ids
                record["simulation"] = simulation
                if record["group"] == "breast" and stock_jiggle_tier is not None:
                    record["stockJiggleTier"] = stock_jiggle_tier
            records.append(record)
            if len(records) > MAX_COMPONENTS:
                raise ValueError("The model has too many physics components for preview editing.")
        except (KeyError, TypeError, AttributeError):
            continue
    by_id = {record["id"]: record for record in records}
    for key, tree in managers:
        bone_ids = [reference(key, pointer) for pointer in (_field(tree, "bones") or [])[:MAX_COMPONENTS]]
        collider_ids = [reference(key, pointer) for pointer in (_field(tree, "colliders") or [])[:MAX_COMPONENTS]]
        for ident in collider_ids:
            record = by_id.get(ident)
            if record is not None and record["kind"] == "collider" and "sibling" not in record:
                slot = record.get("siblingIndex", -1)
                if 0 <= slot < len(collider_ids) and collider_ids[slot] != ident:
                    record["sibling"] = collider_ids[slot]
        for index, ident in enumerate(bone_ids):
            record = by_id.get(ident)
            if record is None or record["kind"] != "bone":
                continue
            simulation = record["simulation"]
            simulation.update(manager=f"{source_index}:{key[0]}:{key[1]}", order=index)
            for field, target in (("parentIndex", "parent"), ("childIndex", "child")):
                slot = simulation.get(field, -1)
                if 0 <= slot < len(bone_ids) and bone_ids[slot] in by_id:
                    simulation[target] = bone_ids[slot]
            # References are authoritative. Packed manager indices are a
            # fallback for serialized variants which omit the PPtr array.
            if "colliders" not in simulation:
                selected = simulation.get("colliderIds", [])
                if not selected and simulation.get("colliderBits", 0) > 0:
                    selected = [slot + 1 for slot in range(len(collider_ids)) if simulation["colliderBits"] & (1 << slot)]
                simulation["colliders"] = [collider_ids[v - 1] for v in selected
                                           if 0 < v <= len(collider_ids) and collider_ids[v - 1] in by_id]
    return records


def native_managers(info, source_index, bones):
    """Retain the original ordered manager graph, including its empty slots.

    These are source settings, not inferred runtime quality choices. In the
    game Initialize receives job/LOD/skirtsafe flags from its caller; the
    browser adapter must keep that distinction explicit.
    """
    nodes = {(int(b.get("serializedFile", 0)), str(b["transformId"])): b["node"]
             for b in bones if b.get("sourceIndex") == source_index and "transformId" in b}
    transforms = {}
    for key, tree in info["transforms"].items():
        pointer = tree.get("m_GameObject") or {}
        if pointer.get("m_FileID", 0) == 0:
            transforms[(key[0], pointer.get("m_PathID"))] = key

    active_cache = {}

    def active(key):
        if key in active_cache:
            return active_cache[key]
        tree = info["transforms"][key]
        pointer = tree.get("m_GameObject") or {}
        game = info["objects"].get((key[0], pointer.get("m_PathID"))) if pointer.get("m_FileID", 0) == 0 else None
        own = bool(game.read_typetree().get("m_IsActive", True)) if game is not None else False
        parent = info["parents"].get(key)
        value = own and (active(parent) if parent in info["transforms"] else True)
        active_cache[key] = value
        return value

    def knees(root):
        found, visited = [None, None], set()

        def walk(key, is_root=False):
            if key in visited or key not in info["transforms"]:
                return
            visited.add(key)
            # Unity searches the receiver itself even when inactive. Other
            # transforms must be active in the original hierarchy; user mesh
            # visibility is not a GameObject activation flag.
            if not is_root and not active(key):
                return
            name = info["names"].get(key, "")
            for ordinal, token in enumerate(("LeftUpLeg", "RightUpLeg")):
                if token in name:
                    found[ordinal] = nodes.get((key[0], str(key[1])))
            for pointer in info["transforms"][key].get("m_Children", []):
                if isinstance(pointer, dict) and pointer.get("m_FileID", 0) == 0:
                    walk((key[0], pointer.get("m_PathID")))

        if root is not None:
            walk(root, True)
        return found

    def reference(key, pointer):
        if isinstance(pointer, dict) and pointer.get("m_FileID", 0) == 0 and pointer.get("m_PathID"):
            return f"{source_index}:{key[0]}:{pointer['m_PathID']}"
        return None

    result = []
    for key, obj in info["objects"].items():
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        script = _local(obj, _field(tree, "m_Script"))
        if script is None or script.type.name != "MonoScript":
            continue
        if script.read_typetree().get("m_ClassName", "").rsplit(".", 1)[-1] != "SwingBoneManager":
            continue
        pointer = _field(tree, "m_GameObject") or {}
        transform = transforms.get((key[0], pointer.get("m_PathID"))) if pointer.get("m_FileID", 0) == 0 else None
        manager = {"id": f"{source_index}:{key[0]}:{key[1]}", "sourceIndex": source_index,
                   "node": nodes.get((transform[0], str(transform[1]))) if transform else None,
                   "enabled": bool(_field(tree, "m_Enabled") if _field(tree, "m_Enabled") is not None else True)}
        for name in ("bones", "lodBones", "colliders", "kneeTransforms"):
            values = _field(tree, name)
            if values is None:
                manager[name] = None
                continue
            if not isinstance(values, list) or len(values) > MAX_COMPONENTS:
                raise ValueError("The original physics manager graph is invalid or too large.")
            if name == "kneeTransforms":
                manager[name] = [nodes.get((key[0], str(p.get("m_PathID"))))
                                 if isinstance(p, dict) and p.get("m_FileID", 0) == 0 else None for p in values]
            else:
                manager[name] = [reference(key, p) for p in values]
        for name in ("enableJob", "enableLod", "enableAutoStart"):
            value = _field(tree, name)
            manager[name] = bool(value) if type(value) in (bool, int) and value in (0, 1) else None
        if manager["kneeTransforms"] == []:
            manager["resolvedKneeTransforms"] = knees(transform)
        result.append(manager)
        if len(result) > MAX_COMPONENTS:
            raise ValueError("The model has too many original physics managers.")
    return result


def native_readiness(records, managers):
    """Report missing source facts rather than substituting enhanced physics."""
    missing, known = [], {row["id"]: row for row in records}
    active = [row for row in managers if row["enabled"]]
    if not active:
        missing.append("manager")
    for manager in active:
        if manager["node"] is None:
            missing.append(manager["id"] + ":node")
        for name in ("bones", "lodBones", "colliders", "kneeTransforms", "enableJob", "enableLod", "enableAutoStart"):
            if manager.get(name) is None:
                missing.append(manager["id"] + ":" + name)
        for name in ("bones", "lodBones", "colliders"):
            for ident in manager.get(name) or []:
                if ident not in known:
                    missing.append(manager["id"] + ":" + name + ":reference")
    managed = {ident for manager in active for ident in (manager.get("bones") or []) + (manager.get("lodBones") or [])}
    for ident in managed:
        row = known.get(ident)
        if row is None:
            continue
        sim = row.get("simulation", {})
        for name in ("radius", "boneAxis", "externalForce", "enableLod"):
            if name not in sim:
                missing.append(ident + ":" + name)
        if sim.get("childNode") is None and sim.get("childOffset") is None:
            missing.append(ident + ":child")
        if sim.get("skirtSafeEnable"):
            for name in ("skirtLimitDotMin", "skirtLimitDotMax", "skirtRotDegMax", "kneeSpaceOffsetFront", "kneeSpaceOffsetOther", "kneeSpaceOffsetForce"):
                if name not in sim:
                    missing.append(ident + ":" + name)
    for row in records:
        if row["node"] is None:
            missing.append(row["id"] + ":node")
        sibling = row.get("sibling") if row["kind"] == "collider" else row.get("simulation", {}).get("sibling")
        if sibling is not None and sibling not in known:
            missing.append(row["id"] + ":sibling")
    return {"profile": "sifas-3.12.0", "available": not missing,
            "missing": sorted(set(missing)), "runtimeFlagsFromCaller": True}


def catalog_sources(sources, bones):
    from .model_edits import _inspect
    records, managers = [], []
    for index, source in enumerate(sources):
        info = _inspect(source["raw"])
        records.extend(inspect_info(info, index, bones))
        managers.extend(native_managers(info, index, bones))
        if len(records) > MAX_COMPONENTS:
            raise ValueError("The selected models have too many physics components.")
    return make_catalog(records, managers)


def make_catalog(records, managers):
    if len(records) > MAX_COMPONENTS or len(managers) > MAX_COMPONENTS:
        raise ValueError("The selected models have too many physics components or managers.")
    return {"available": bool(records), "components": records, "managers": managers,
            "native": native_readiness(records, managers), "presets": recommendations(),
            "breastSizeRecommendations": {"presets": [{"scale": list(scale), "tier": tier}
                                                        for scale, tier in _BREAST_SIZE_TIERS],
                                          "stockTolerance": .03, "source": "sifas_breast_tuner.py"},
            "recommendationSource": "sifas_breast_tuner.py / Upleg_SwingCollider_changer.py",
            "preview": "source_game_or_enhanced"}


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
