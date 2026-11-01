"""Read-only scaling metadata for a rigged preview's authored rest shape.

SIFAS node records store absolute local endpoints, not multipliers. This module
never applies them on load: doing so would hide authored edits or apply shape
changes again to baked meshes. Relative preview controls always start from the
exported glTF node's saved TRS. The game's separate heightScale initialization
formula is not inferred from metadata. Native call-target evidence identifies
rotation records as Vector3.Lerp endpoints for localEulerAngles; converting and
applying those saved Euler records is not implemented in this exporter.
"""
import math


MAX_COMPONENTS = 32
MAX_ENTRIES = 1024
MAX_CONTROL_NODES = 32
MAX_ABSOLUTE_VALUE = 1_000_000
EPSILON = 1e-3

_CONTROLS = (
    ("height", "Height", "Move", 50, 150),
    ("breast", "Breast size", "BreastSize", 25, 200),
)


def _number(value):
    if isinstance(value, bool):
        raise ValueError("A scaling value must be a finite number.")
    value = float(value)
    if not math.isfinite(value) or abs(value) > MAX_ABSOLUTE_VALUE:
        raise ValueError("A scaling value exceeds the preview bounds.")
    return value


def _vector(value, width=3):
    if isinstance(value, dict):
        value = [value[key] for key in "xyzw"[:width]]
    if not isinstance(value, (list, tuple)) or len(value) != width:
        raise ValueError("A scaling vector has an invalid shape.")
    return [_number(part) for part in value]


def _quaternion(value):
    result = _vector(value, 4)
    length = math.sqrt(sum(part * part for part in result))
    if length < 1e-12:
        raise ValueError("A scaling rotation has zero length.")
    return [part / length for part in result]


def _close(left, right, quaternion=False):
    direct = max(abs(a - b) for a, b in zip(left, right))
    if quaternion:
        direct = min(direct, max(abs(a + b) for a, b in zip(left, right)))
    return direct <= EPSILON


def _state(authored, origin, scaled, quaternion=False):
    if _close(authored, scaled, quaternion):
        return "unchanged" if _close(origin, scaled, quaternion) else "already_applied"
    return "pending" if _close(authored, origin, quaternion) else "mismatch"


def evaluate_saved_entry(entry, weight=1.0):
    """Return an absolute glTF local endpoint without changing any input.

    Intermediate values are an explicit viewer interpolation, not a claim to
    reproduce all native controller behavior. Applying the returned property
    repeatedly is idempotent. Saved Vector3 Euler records remain inspection-only
    because their conversion is not implemented, despite the encoding proof.
    """
    if not entry.get("supported"):
        raise ValueError("This saved scaling entry cannot be applied safely.")
    weight = _number(weight)
    if not 0 <= weight <= 1:
        raise ValueError("Saved scaling interpolation must be between zero and one.")
    kind = entry.get("kind")
    if kind not in ("scale", "position"):
        raise ValueError("Saved rotation interpolation is not verified.")
    origin, scaled = _vector(entry["origin"]), _vector(entry["scaled"])
    result = [a + (b - a) * weight for a, b in zip(origin, scaled)]
    if kind == "scale" and any(abs(value) < 1e-8 for value in result):
        raise ValueError("A preview scale cannot collapse a bone to zero.")
    return {"scale" if kind == "scale" else "translation": result}


def describe_scaling(scene, glb, node_by_transform, *, sources=None):
    """Describe selected source records and controls; never modify TRS/meshes.

    node_by_transform uses model_viewer._key(Transform) -> glTF node index.
    Positions are reflected in X to match the rig exporter. Control limits are
    conservative viewer UI bounds, not asserted game/runtime scale limits.
    """
    from .model_viewer import _key, _ref, _source_name, _source_path

    selected = None if sources is None else set(sources)
    nodes = glb.doc["nodes"]
    result = {"version": 1, "baseline": "authored", "savedOverridesApplied": False,
              "gameHeightFormulaVerified": False, "components": [], "controls": [], "warnings": []}

    def warn(code):
        if code not in result["warnings"]:
            result["warnings"].append(code)

    def rest(transform):
        index = node_by_transform.get(_key(transform))
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(nodes):
            raise ValueError("The scaling target is outside the exported rig.")
        node = nodes[index]
        if "matrix" in node:
            raise ValueError("Matrix-only rig nodes cannot use local TRS controls.")
        return {"node": index, "basePosition": _vector(node.get("translation", [0, 0, 0])),
                "baseQuaternion": _quaternion(node.get("rotation", [0, 0, 0, 1])),
                "baseScale": _vector(node.get("scale", [1, 1, 1]))}

    catalogue = {name: {} for _, _, name, _, _ in _CONTROLS}
    seen = set()
    for transform in scene.transforms.values():
        key = _key(transform)
        if key in seen or (selected is not None and _source_path(transform) not in selected):
            continue
        seen.add(key)
        try:
            tree = scene.tree(transform)
            game_object = _ref(transform, tree.get("m_GameObject"))
            name = scene.name(game_object) if game_object is not None else ""
            if name not in catalogue:
                continue
            target = rest(transform)
            if any(abs(value) < 1e-8 for value in target["baseScale"]):
                continue
            target.update(name=name, axes=[1, 1, 1])
            catalogue[name][target["node"]] = target
        except (ValueError, KeyError, TypeError, OverflowError):
            warn("scaling_target_unavailable")

    total_entries = 0
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour" or (selected is not None and _source_path(obj) not in selected):
            continue
        try:
            tree = scene.tree(obj)
        except Exception:
            continue
        if not all(key in tree for key in ("targetName", "scaleValues", "positionValues")):
            continue
        if len(result["components"]) >= MAX_COMPONENTS:
            warn("scaling_metadata_limit")
            break
        component = {"sourceName": _source_name(obj), "targetName": str(tree["targetName"])[:160],
                     "heightScale": None, "entries": []}
        try:
            component["heightScale"] = _number(tree.get("heightScale", 1))
        except (ValueError, TypeError, OverflowError):
            warn("scaling_invalid_height")
        for kind, field in (("scale", "scaleValues"), ("position", "positionValues"), ("rotation", "rotationValues")):
            records = tree.get(field, [])
            if not isinstance(records, list):
                warn("scaling_invalid_entry")
                continue
            for record in records:
                total_entries += 1
                if total_entries > MAX_ENTRIES:
                    warn("scaling_metadata_limit")
                    break
                try:
                    record = record.get("data", record)
                    transform = _ref(obj, record.get("target"))
                    if transform is None or transform.type.name != "Transform" or _source_path(transform) != _source_path(obj):
                        raise ValueError("The saved scaling target is missing or belongs to another source.")
                    target = rest(transform)
                    game_object = _ref(transform, scene.tree(transform).get("m_GameObject"))
                    name = scene.name(game_object) if game_object is not None else ""
                    origin, scaled = _vector(record["originValue"]), _vector(record["scaledValue"])
                    authored = target["baseScale"] if kind == "scale" else target["basePosition"]
                    if kind == "position":
                        origin[0], scaled[0] = -origin[0], -scaled[0]
                    entry = {"node": target["node"], "name": name, "kind": kind,
                             "origin": origin, "scaled": scaled, "authored": list(authored),
                             "supported": kind != "rotation", "application": "absolute_local_" + kind,
                             "space": "gltf_local", "state": "unverified"}
                    if kind == "rotation":
                        entry.update(authored=target["baseQuaternion"], space="unity_unverified_vector3",
                                     application=None, reason="rotation_encoding_unverified")
                    else:
                        entry["state"] = _state(authored, origin, scaled)
                        if kind == "scale" and any(abs(value) < 1e-8 for value in scaled):
                            entry.update(supported=False, reason="zero_scale")
                    component["entries"].append(entry)
                except (ValueError, KeyError, AttributeError, TypeError, OverflowError):
                    warn("scaling_invalid_entry")
        result["components"].append(component)
        if total_entries > MAX_ENTRIES:
            break

    for identity, label, name, minimum, maximum in _CONTROLS:
        targets = list(catalogue[name].values())
        if len(targets) > MAX_CONTROL_NODES:
            targets = []
            warn("scaling_metadata_limit")
        result["controls"].append({"id": identity, "label": label, "available": bool(targets),
                                   "default": 100, "min": minimum, "max": maximum,
                                   "unit": "percent", "mode": "multiply_authored_local_scale",
                                   "limitsSource": "viewer_preview_bounds", "nodes": targets})
    return result


# Integration name retained for the exporter; this function is metadata-only.
apply_to_rig = describe_scaling
