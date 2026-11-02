"""Read-only scaling metadata for a rigged preview's authored rest shape.

SIFAS node records store absolute local endpoints, not multipliers. Metadata
does not modify the exported authored TRS. Native ApplyScale uses clamped
Vector3.Lerp for localScale/localPosition/localEulerAngles. Rotation endpoints
therefore retain their source Euler values: interpolate them before Unity ZXY
conversion, rather than interpolating quaternions. The separate heightScale
initialization formula is not inferred from these records.
"""
import math
import re


MAX_COMPONENTS = 32
MAX_ENTRIES = 1024
MAX_CONTROL_NODES = 32
MAX_CATALOGUE_NODES = 1024
MAX_ABSOLUTE_VALUE = 1_000_000
EPSILON = 1e-3

_SKIRT_ROOTS = ("SkirtA1_Dyna", "SkirtE1_Dyna", "LeftSkirtB1_Dyna", "RightSkirtB1_Dyna",
                "LeftSkirtC1_Dyna", "RightSkirtC1_Dyna", "LeftSkirtD1_Dyna", "RightSkirtD1_Dyna")

# Keep these exact profiles in sync with sifas_breast_tuner.py. That editor is
# also distributed as a standalone script, so the viewer must not import its
# desktop/UI implementation during a bounded model conversion.
_BREAST_REDUCE_PRESETS = (
    ("Yoshiko/Shioriko", (.95, .99, .98)), ("Honoka/Maki", (.90, .98, .96)),
    ("Umi/Ruby/Kasumi", (.80, .96, .92)), ("Rin", (.72, .95, .90)),
    ("Nico", (.64, .94, .88)), ("Rina", (.61, .91, .85)),
)
_BREAST_ENLARGE_PRESETS = (
    ("Chika/You/Ayumu", (1.04, 1.02, 1.04)), ("Hanayo/Setsuna", (1.08, 1.04, 1.08)),
    ("Hanamaru/Ai", (1.12, 1.06, 1.12)), ("Lanzhu", (1.14, 1.07, 1.14)),
    ("Eli/Kanan/Kanata", (1.16, 1.08, 1.16)), ("Mari", (1.20, 1.10, 1.20)),
    ("Karin", (1.22, 1.11, 1.22)), ("Nozomi", (1.30, 1.15, 1.30)),
    ("Emma", (1.30, 1.18, 1.30)),
)
_CONTROLS = (
    ("height", "Height", ("Move",), 50, 150, "height_vertical_preserve_head", [0, 1, 0]),
    ("breast", "Breast size", ("BreastSize",), 25, 200, "breast_tool_curve", [1, 1, 1]),
    ("skirt", "Skirt length and volume", _SKIRT_ROOTS, 50, 150, "multiply_authored_local_scale", [1, 1, 1]),
)
_RECOMMENDED = {
    "Head": ("Head", "head"), "Head_Hair": ("Hair", "hair"),
    "Neck_Hair": ("Back hair", "hair"), "Move": ("Height", "height"),
    "BreastSize": ("Breast size", "breast"), "Breast_Offset": ("Breast placement", "breast"),
    "HipsSize": ("Hip size", "hips"),
    "Spine": ("Lower torso", "waist"), "Spine1": ("Middle torso", "waist"),
    "Spine2": ("Upper torso", "waist"),
    "LeftShoulder": ("Left shoulder", "shoulders"), "RightShoulder": ("Right shoulder", "shoulders"),
    "LeftArm": ("Left upper arm", "arms"), "RightArm": ("Right upper arm", "arms"),
    "LeftForeArm": ("Left forearm", "arms"), "RightForeArm": ("Right forearm", "arms"),
    "LeftHand": ("Left hand", "hands"), "RightHand": ("Right hand", "hands"),
    "LeftUpLeg": ("Left thigh", "legs"), "RightUpLeg": ("Right thigh", "legs"),
    "LeftLeg": ("Left calf", "legs"), "RightLeg": ("Right calf", "legs"),
    "LeftFoot": ("Left foot", "feet"), "RightFoot": ("Right foot", "feet"),
    **{name: ("Skirt", "skirt") for name in _SKIRT_ROOTS},
}


def _breast_profile():
    """Describe the existing editor's exact XYZ profiles and enlargement line.

    The relative control uses F(x * p/100) / F(x), component by component,
    where F linearly interpolates the stored reduction triples and follows
    x=z=1+2Y, y=1+Y above stock. This preserves custom file XYZ at p=100.
    Emma remains an explicit preset because its Y is an intentional exception.
    """
    curve = sorted([list(value) for _, value in _BREAST_REDUCE_PRESETS] + [[1., 1., 1.]])
    curve.append([3., 2., 3.])  # open upper endpoint: editor supports 0 < Y < 1
    presets = [{"id": "stock", "label": "Stock", "scale": [1., 1., 1.], "group": "stock"}]
    for group, entries in (("smaller", _BREAST_REDUCE_PRESETS), ("larger", _BREAST_ENLARGE_PRESETS)):
        for label, value in entries:
            presets.append({"id": re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"),
                            "label": label, "scale": list(value), "group": group})
    return {"curve": curve, "curveDomain": {"minX": .61, "maxX": 3., "maxExclusive": True},
            "curveParameter": "local_scale_x", "relativeFormula": "F(x*p/100)/F(x)",
            "presets": presets, "presetApplication": "absolute_local_scale",
            "source": "sifas_breast_tuner.py:breast_enlarge_xyz/BREAST_REDUCE_PRESETS/BREAST_ENLARGE_PRESETS"}


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


def unity_euler_to_gltf(value):
    """Unity localEulerAngles (degrees, Z then X then Y), reflected in X.

    Column-vector rotation is Ry @ Rx @ Rz, or Hamilton qY*qX*qZ. Reflection
    conjugates the matrix by diag(-1,1,1), giving [qx,-qy,-qz,qw].
    """
    x, y, z = [math.radians(part) * .5 for part in _vector(value)]
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return _quaternion([cy * sx * cz + sy * cx * sz,
                        -(sy * cx * cz - cy * sx * sz),
                        -(cy * cx * sz - sy * sx * cz),
                        cy * cx * cz + sy * sx * sz])


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

    Match the verified ApplyScale operation: clamp finite t to [0,1], linearly
    interpolate stored vectors, then assign the absolute local property. Euler
    angles are not wrapped or interpolated on the shortest quaternion arc.
    """
    if not entry.get("supported"):
        raise ValueError("This saved scaling entry cannot be applied safely.")
    weight = min(1., max(0., _number(weight)))
    kind = entry.get("kind")
    if kind == "rotation":
        if entry.get("interpolation") != "unity_euler_lerp" or entry.get("rotationOrder") != "ZXY":
            raise ValueError("The saved rotation interpolation is unsupported.")
        origin, scaled = _vector(entry["unityEulerOrigin"]), _vector(entry["unityEulerScaled"])
        return {"rotation": unity_euler_to_gltf([a + (b - a) * weight for a, b in zip(origin, scaled)])}
    if kind not in ("scale", "position"):
        raise ValueError("The saved node property is unsupported.")
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
    result = {"version": 2, "baseline": "authored", "savedOverridesApplied": False,
              "savedInterpolation": "unity_vector3_lerp_clamp01", "rotationOrder": "ZXY",
              "gameHeightFormulaVerified": False, "components": [], "controls": [], "targets": [],
              "nodes": [], "recommendedTargets": [], "warnings": []}

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

    catalogue = {name: {} for _, _, names, *_ in _CONTROLS for name in names}
    authored_nodes, source_by_node = {}, {}
    parents = {}
    for parent, node in enumerate(nodes):
        for child in node.get("children", []):
            if isinstance(child, int) and not isinstance(child, bool) and 0 <= child < len(nodes):
                parents.setdefault(child, []).append(parent)
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
            target = rest(transform)
            if len(authored_nodes) >= MAX_CATALOGUE_NODES and target["node"] not in authored_nodes:
                warn("scaling_metadata_limit")
                continue
            parent = parents.get(target["node"], [])
            label, category = _RECOMMENDED.get(name, (name, "other"))
            target.update(name=name, label=label, category=category,
                          parent=parent[0] if len(parent) == 1 else None,
                          sourceName=_source_name(transform))
            authored_nodes[target["node"]] = target
            source_by_node[target["node"]] = _source_path(transform)
            if name in catalogue and all(abs(value) >= 1e-8 for value in target["baseScale"]):
                catalogue[name][target["node"]] = dict(target)
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
        if "targetName" not in tree or not any(key in tree for key in ("scaleValues", "positionValues", "rotationValues")):
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
                             "supported": True, "application": "absolute_local_" + kind,
                             "space": "gltf_local", "state": "unverified",
                             "interpolation": "unity_vector3_lerp"}
                    if kind == "rotation":
                        original_euler, scaled_euler = origin, scaled
                        origin, scaled = unity_euler_to_gltf(origin), unity_euler_to_gltf(scaled)
                        authored = target["baseQuaternion"]
                        entry.update(authored=authored, origin=origin, scaled=scaled,
                                     originQuaternion=list(origin), scaledQuaternion=list(scaled),
                                     unityEulerOrigin=original_euler, unityEulerScaled=scaled_euler,
                                     rotationOrder="ZXY", interpolation="unity_euler_lerp",
                                     quaternionConvention="unity_zxy_mirror_x",
                                     application="absolute_local_quaternion")
                        entry["state"] = _state(authored, origin, scaled, quaternion=True)
                    else:
                        entry["state"] = _state(authored, origin, scaled)
                        if kind == "scale" and any(abs(value) < 1e-8 for value in origin + scaled):
                            entry.update(supported=False, reason="zero_scale")
                    entry["id"] = str(len(result["components"])) + ":" + str(len(component["entries"]))
                    component["entries"].append(entry)
                except (ValueError, KeyError, AttributeError, TypeError, OverflowError):
                    warn("scaling_invalid_entry")
        result["components"].append(component)
        if total_entries > MAX_ENTRIES:
            break

    # Every exported saved target participates, including skirt/accessory nodes.
    # Ambiguous absolute operations must not depend on component/file order.
    operations, groups = {}, {}
    for component_index, component in enumerate(result["components"]):
        for entry_index, entry in enumerate(component["entries"]):
            operations.setdefault((entry["node"], entry["kind"]), []).append(entry)
            if entry["node"] not in groups:
                node = nodes[entry["node"]]
                name = entry["name"]
                label = {"Move": "Whole model", "BreastSize": "Breast size"}.get(name)
                if label is None:
                    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", re.sub(r"_Dyna$", "", name)).replace("_", " ")
                groups[entry["node"]] = {"node": entry["node"], "name": name, "label": label,
                    "category": "skirt" if "skirt" in name.lower() else "other", "kinds": [], "entries": [],
                    "basePosition": _vector(node.get("translation", [0, 0, 0])),
                    "baseQuaternion": _quaternion(node.get("rotation", [0, 0, 0, 1])),
                    "baseScale": _vector(node.get("scale", [1, 1, 1]))}
            group = groups[entry["node"]]
            if entry["kind"] not in group["kinds"]:
                group["kinds"].append(entry["kind"])
            group["entries"].append({"component": component_index, "entry": entry_index, "id": entry["id"]})
    for entries in operations.values():
        first = entries[0]
        # Source Euler endpoints matter even when 360-degree offsets yield the
        # same final quaternion: native intermediate angles can still differ.
        fields = ("unityEulerOrigin", "unityEulerScaled") if first["kind"] == "rotation" else ("origin", "scaled")
        if any(any(max(abs(a - b) for a, b in zip(entry[field], first[field])) > 1e-6 for field in fields) for entry in entries[1:]):
            for entry in entries:
                entry.update(supported=False, reason="conflicting_saved_entries")
            warn("scaling_conflicting_entries")
    result["targets"] = list(groups.values())

    for node, target in authored_nodes.items():
        group = groups.get(node)
        target["hasSavedSettings"] = group is not None
        target["savedKinds"] = list(group["kinds"]) if group else []
        target["savedEntries"] = [entry["id"] for entry in group["entries"]] if group else []
        result["nodes"].append(target)
        if target["name"] in _RECOMMENDED:
            result["recommendedTargets"].append({key: target[key] for key in
                ("node", "name", "label", "category", "hasSavedSettings")})

    def descends(child, ancestor):
        """Require one exported parent chain entirely inside the same source."""
        source = source_by_node.get(ancestor)
        seen = set()
        while child not in seen and child in authored_nodes and source_by_node.get(child) == source:
            if child == ancestor:
                return True
            seen.add(child)
            chain = parents.get(child, [])
            if len(chain) != 1:
                return False
            child = chain[0]
        return False

    def outermost(targets):
        return [target for target in targets if not any(
            target["node"] != other["node"] and descends(target["node"], other["node"])
            for other in targets)]

    for identity, label, names, minimum, maximum, mode, axes in _CONTROLS:
        targets = [dict(target) for name in names for target in catalogue[name].values()]
        reason = None
        if identity == "height":
            verified = []
            for target in targets:
                roots = []
                for name in ("Head", "Neck_Hair"):
                    matches = [node for node in authored_nodes.values()
                               if node["name"] == name and descends(node["node"], target["node"])]
                    if len(matches) > 1 or (name == "Head" and not matches):
                        reason = "ambiguous_height_head" if matches else "missing_height_head"
                        roots = None
                        break
                    roots.extend(matches)
                if roots is None:
                    continue
                target["compensationRoots"] = [dict(root) for root in outermost(roots)]
                verified.append(target)
            targets = outermost(verified)
        elif identity == "skirt":
            targets = outermost(targets)
        for target in targets:
            target["axes"] = list(axes)
        if len(targets) > MAX_CONTROL_NODES:
            targets = []
            warn("scaling_metadata_limit")
        control = {"id": identity, "label": label, "available": bool(targets),
                   "default": 100, "min": minimum, "max": maximum,
                   "unit": "percent", "mode": mode, "baseline": "active_pose_and_saved_settings",
                   "limitsSource": "viewer_preview_bounds", "nodes": targets}
        if not targets and reason:
            control["unavailableReason"] = reason
        if identity == "height":
            control.update(source="viewer_vertical_height_policy", axesMeaning="vertical_only",
                           compensation="preserve_world_linear_basis_at_shifted_anchor",
                           gameHeightFormulaVerified=False)
        elif identity == "breast":
            control.update(_breast_profile())
        else:
            control.update(source="skirt_length_changer.py:DEFAULT_SKIRT_PATTERNS",
                           exactRootNames=list(_SKIRT_ROOTS), axesMeaning="length_and_volume")
        result["controls"].append(control)
    return result


# Integration name retained for the exporter; this function is metadata-only.
apply_to_rig = describe_scaling
