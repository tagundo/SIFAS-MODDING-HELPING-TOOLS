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

from sifas_body_profiles import thigh_profile_metadata


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
    ("breast", "Breast size", ("BreastSize",), "breast_tool_presets"),
    ("skirt", "Skirt length and volume", _SKIRT_ROOTS, "absolute_skirt_root_scale"),
)
_BODY_CARD_CONTROLS = (
    ("hips", "Hip size", ("HipsSize",), "node"),
    ("thighs", "Thigh thickness", ("LeftUpLeg", "RightUpLeg"), "mesh"),
    ("waist", "Waist thickness", ("Spine",), "mesh"),
)
_RECOMMENDED = {
    "Head": ("Head", "head"), "Head_Hair": ("Hair", "hair"),
    "Neck_Hair": ("Back hair", "hair"), "Move": ("Whole model", "model"),
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
    """Expose the tool's discrete reference shapes as absolute XYZ profiles.

    Its below-stock triples are irregular character data, not samples of a
    continuous size curve. Do not interpolate them, infer a percentage from X,
    or multiply a custom file's XYZ by a profile-derived relative ratio.
    The loaded shape is a separate runtime baseline; Stock is an explicit
    [1, 1, 1] selection and must never stand in for that loaded baseline.
    """
    presets = [{"id": "stock", "label": "Stock", "scale": [1., 1., 1.], "group": "stock"}]
    for group, entries in (("smaller", _BREAST_REDUCE_PRESETS), ("larger", _BREAST_ENLARGE_PRESETS)):
        for label, value in entries:
            presets.append({"id": re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"),
                            "label": label, "scale": list(value), "group": group})
    return {"presets": presets, "presetApplication": "absolute_local_scale",
            "interpolation": "none", "continuousAdjustmentSupported": False,
            "profileMeaning": "reference_shape_not_body_measurement",
            "source": "sifas_breast_tuner.py:BREAST_REDUCE_PRESETS/BREAST_ENLARGE_PRESETS"}


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


def _body_card_controls(authored_nodes, parents, source_by_node):
    """Describe exact, source-bound size/thickness targets without editing them.

    SIFAS' simple thickness tools keep the local X length axis and change Y/Z.
    The parent inverse is applied at immediate child bones for thighs, or at
    Spine2 for the waist so Spine1 remains part of the waist adjustment. These
    are Mesh Baker operations: NodeScaling's HipsSize intentionally propagates
    to its children and must not inherit the mesh compensation switch.
    """
    def lineage(node):
        chain, seen = [], set()
        while node is not None:
            if node in seen or len(parents.get(node, [])) > 1:
                return None
            seen.add(node)
            chain.append(node)
            values = parents.get(node, [])
            node = values[0] if values else None
        return chain

    def valid_scale(target):
        return all(math.isfinite(value) and abs(value) >= 1e-8
                   for value in target["baseScale"])

    def source_root(node, path):
        # The exported Character node joins independent source armatures. It
        # cannot establish that a left/right pair belongs to the same rig.
        source = source_by_node[node]
        return next((ancestor for ancestor in reversed(path)
                     if source_by_node.get(ancestor) == source), None)

    def valid_compensation_path(parent, child):
        path = lineage(child)
        if path is None or parent not in path[1:]:
            return False
        for node in path[:path.index(parent)]:
            entry = authored_nodes.get(node)
            if entry is None or not valid_scale(entry) or source_by_node[node] != source_by_node[parent]:
                return False
        return True

    controls = []
    for identity, label, names, method in _BODY_CARD_CONTROLS:
        named = {name: [entry for entry in authored_nodes.values()
                        if entry["name"] == name] for name in names}
        targets = [dict(entry) for name in names for entry in named[name]]
        reason, compensation_targets = "", {}
        if any(not named[name] for name in names):
            reason = "missing_body_control_nodes"
        elif any(len(named[name]) != 1 for name in names):
            reason = "ambiguous_body_control_nodes"
        elif any(not valid_scale(target) for target in targets):
            reason = "invalid_body_control_scale"
        else:
            sources = {source_by_node[target["node"]] for target in targets}
            paths = [lineage(target["node"]) for target in targets]
            if len(sources) != 1:
                reason = "body_control_source_mismatch"
            elif any(path is None for path in paths) or len({
                    source_root(target["node"], path)
                    for target, path in zip(targets, paths)}) != 1:
                reason = "ambiguous_body_control_hierarchy"
            elif method == "mesh":
                for target in targets:
                    node = target["node"]
                    if identity == "waist":
                        descendants = [entry for entry in authored_nodes.values()
                                       if entry["name"] == "Spine2" and
                                       source_by_node[entry["node"]] == source_by_node[node] and
                                       (lineage(entry["node"]) or [])[1:].count(node) == 1]
                        if len(descendants) != 1:
                            reason = ("missing_waist_compensation_target" if not descendants
                                      else "ambiguous_waist_compensation_target")
                            break
                    else:
                        # Authored rig nodes already include the Transform
                        # hierarchy used by the viewer's immediate-bone rule.
                        descendants = [entry for entry in authored_nodes.values()
                                       if parents.get(entry["node"]) == [node] and
                                       source_by_node[entry["node"]] == source_by_node[node]]
                        if not descendants:
                            reason = "missing_body_control_children"
                            break
                    if any(not valid_compensation_path(node, child["node"])
                           for child in descendants):
                        reason = "invalid_body_control_scale"
                        break
                    compensation_targets[node] = [child["node"] for child in descendants]
        for target in targets:
            target["compensationTargets"] = compensation_targets.get(target["node"], [])
        control = {"id": identity, "label": label, "available": bool(targets) and not reason,
                   "mode": "relative_body_scale" if method == "node" else "compensated_thickness",
                   "method": method, "nodes": targets,
                   "unit": "percent", "default": 100, "baseline": "loaded_static_shape",
                   "application": "relative_to_original_static_scale",
                   "editedAxes": [0, 1, 2] if method == "node" else [1, 2],
                   "lengthAxis": None if method == "node" else 0,
                   "compensate": method == "mesh",
                   "compensationMode": "none" if method == "node" else "spine2" if identity == "waist" else "auto",
                   "editBounds": {"min": 20., "max": 250., "source": "viewer_ui_bounds",
                                  "appliesTo": "explicit_percentage_edits_only"},
                   "exactRootNames": list(names), "targetSelection": "unique_exact_named_nodes",
                   "axesMeaning": "uniform_size" if method == "node" else "thickness_without_length",
                   "source": "hips_size_changer.py:HipsSize" if method == "node" else "webtools/tools/mesh.py:_build_body_targets"}
        if identity == "thighs":
            control.update(thigh_profile_metadata())
        if reason:
            control["unavailableReason"] = reason
        controls.append(control)
    return controls


def describe_scaling(scene, glb, node_by_transform, *, sources=None):
    """Describe selected source records and controls; never modify TRS/meshes.

    node_by_transform uses model_viewer._key(Transform) -> glTF node index.
    Positions are reflected in X to match the rig exporter. Control limits are
    conservative viewer UI bounds, not asserted game/runtime scale limits.
    """
    from .model_viewer import _key, _ref, _source_name, _source_path

    selected = None if sources is None else set(sources)
    nodes = glb.doc["nodes"]
    result = {"version": 4, "baseline": "authored", "savedOverridesApplied": False,
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

    catalogue = {name: {} for _, _, names, _ in _CONTROLS for name in names}
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

    # The native heightScale initialization is distinct from the verified saved
    # TRS endpoints above. A Move-only Y stretch is not a height editor. Keep
    # those authored records visible without inventing a stature/cm mapping.
    result["controls"].append({
        "id": "height", "label": "Height", "available": False,
        "mode": "saved_height_metadata_only", "nodes": [],
        "source": "LiveCoreMemberNodeScaling.heightScale",
        "unavailableReason": "unverified_height_formula",
        "gameHeightFormulaVerified": False,
    })
    for identity, label, names, mode in _CONTROLS:
        targets = [dict(target) for name in names for target in catalogue[name].values()]
        ambiguous = False
        if identity == "skirt":
            # The absolute tool assigns every named root exactly once, even if
            # one named root is nested under another. Do not silently drop one
            # as the former relative-multiplier control did. Duplicate names
            # in one source remain visible, but need per-node advanced edits.
            seen_names = set()
            for target in targets:
                key = (source_by_node[target["node"]], target["name"])
                if key in seen_names:
                    ambiguous = True
                seen_names.add(key)
        if len(targets) > MAX_CONTROL_NODES:
            targets = []
            warn("scaling_metadata_limit")
        control = {"id": identity, "label": label, "available": bool(targets) and not ambiguous,
                   "mode": mode, "nodes": targets}
        if identity == "breast":
            control.update(default="loaded", unit="profile", baseline="loaded_saved_settings")
            control.update(_breast_profile())
        else:
            control.update(unit="local_scale_factor", supportsAbsoluteUniform=control["available"],
                           application="absolute_local_scale", uniformTolerance=1e-7,
                           editBounds={"min": .01, "max": 10., "source": "viewer_preview_bounds",
                                       "appliesTo": "explicit_uniform_edits_only"},
                           source="skirt_length_changer.py:DEFAULT_SKIRT_PATTERNS",
                           exactRootNames=list(_SKIRT_ROOTS), axesMeaning="length_and_volume",
                           targetSelection="exact_named_roots")
            if ambiguous:
                control["unavailableReason"] = "ambiguous_skirt_roots"
        result["controls"].append(control)
    result["controls"].extend(_body_card_controls(authored_nodes, parents, source_by_node))
    return result


# Integration name retained for the exporter; this function is metadata-only.
apply_to_rig = describe_scaling
