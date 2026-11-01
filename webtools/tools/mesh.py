"""Adapters for sifas_mesh_baker and fix_sifas_bundle_export (both import-safe).

mesh_baker bakes bone scale/rotate/translate into mesh vertices, driven by a
"target spec" string (same grammar as its CLI --target). fix_export normalizes
skinned meshes to world space.
"""
import math
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.tools.common import run_batch, single_out_path


# --------------------------------------------------------------- mesh baker
BODY_PARTS = {
    "head": {"label": "Head size", "kind": "size", "bones": ("Head", "Head_Hair")},
    "torso": {"label": "Waist thickness", "kind": "thickness", "bones": ("Spine",)},
    "upper_arms": {"label": "Upper arms thickness", "kind": "thickness",
                   "bones": ("LeftArm", "RightArm")},
    "forearms": {"label": "Forearms thickness", "kind": "thickness",
                 "bones": ("LeftForeArm", "RightForeArm")},
    "hands": {"label": "Hand size", "kind": "size", "bones": ("LeftHand", "RightHand")},
    "thighs": {"label": "Thigh thickness", "kind": "thickness", "bones": ("LeftUpLeg", "RightUpLeg")},
    "calves": {"label": "Calf thickness", "kind": "thickness", "bones": ("LeftLeg", "RightLeg")},
    "feet": {"label": "Foot size", "kind": "size", "bones": ("LeftFoot", "RightFoot")},
}


def _inspect_bundle(m, path):
    """Keep each mesh's hierarchy: global names alone cannot detect double scaling."""
    env = m.UnityPy.load(str(path))
    tos = m.build_bone_name_map(env)
    id2obj = m.build_id_map(env)
    smr_map = m.smr_bone_pids(env, id2obj)
    meshes = []
    for mi in m.list_meshes(env):
        if not mi.skinned:
            continue
        names, parent = m.resolve_bones(env, id2obj, tos, mi.obj, mi.tree, smr_map)
        meshes.append({"name": mi.name, "bones": names, "parents": parent})
    return meshes


def inspect_bones(params):
    """List the real bone names in a reference bundle for the pose editor."""
    reference = (params.get("reference_path") or "").strip()
    if not reference:
        return []
    ensure_repo_on_path()
    import sifas_mesh_baker as m

    meshes_by_bone = {}
    for mesh in _inspect_bundle(m, reference):
        for name in mesh["bones"]:
            # These fallback labels identify unresolved hashes/indices, not a
            # bone which a user can meaningfully choose by name.
            if name and not name.startswith(("<bone:", "<hash:")):
                meshes_by_bone.setdefault(name, set()).add(mesh["name"])
    return [{"value": name, "label": f"{name} ({', '.join(sorted(meshes_by_bone[name]))})"}
            for name in sorted(meshes_by_bone, key=str.casefold)]


def _head_roots_overlap(meshes):
    """Head and Head_Hair can be separate roots, but may not scale each other."""
    for mesh in meshes:
        names, parents = mesh["bones"], mesh["parents"]
        for index, name in enumerate(names):
            if name not in BODY_PARTS["head"]["bones"]:
                continue
            seen = {index}
            ancestor = parents[index] if index < len(parents) else -1
            while 0 <= ancestor < len(names) and ancestor not in seen:
                if names[ancestor] in BODY_PARTS["head"]["bones"]:
                    return True
                seen.add(ancestor)
                ancestor = parents[ancestor] if ancestor < len(parents) else -1
    return False


def _body_part_options(meshes):
    names = {name for mesh in meshes for name in mesh["bones"]}
    options = []
    for part, definition in BODY_PARTS.items():
        bones = [name for name in definition["bones"] if name in names]
        missing = [name for name in definition["bones"] if name not in names]
        reason = ""
        if part == "head":
            if not bones:
                reason = "No supported head bones were found."
            elif _head_roots_overlap(meshes):
                reason = "This head layout needs the advanced bone editor to avoid scaling it twice."
        elif missing or (part == "torso" and "Spine2" not in names):
            reason = "This model does not have a supported waist." if part == "torso" else \
                "This model does not have both supported sides of this body part."
        options.append({"value": part, "label": definition["label"],
                        "available": not reason, "bones": bones,
                        "kind": definition["kind"], "percent": 100, "reason": reason})
    return options


def inspect_body_parts(params):
    """Availability for the simple editor; names are resolved again for every input."""
    reference = (params.get("reference_path") or "").strip()
    if not reference:
        return _body_part_options([])
    ensure_repo_on_path()
    import sifas_mesh_baker as m

    return _body_part_options(_inspect_bundle(m, reference))


def _body_part_percentages(raw):
    if not isinstance(raw, dict):
        raise ValueError("Body part sizes must be an object of percentages.")
    unknown = set(raw) - BODY_PARTS.keys()
    if unknown:
        raise ValueError("Unknown body part: " + ", ".join(sorted(map(str, unknown))))
    percentages = {}
    for part, definition in BODY_PARTS.items():
        value = raw.get(part, 100)
        try:
            if isinstance(value, bool):
                raise ValueError
            percent = float(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"{definition['label']} must be a number between 50 and 150%.") from None
        if not math.isfinite(percent) or not 50 <= percent <= 150:
            raise ValueError(f"{definition['label']} must be between 50 and 150%.")
        percentages[part] = percent
    return percentages


def _build_body_targets(m, percentages, meshes, mesh_filter=None, include_hidden=False):
    class BodyPartTarget(m.Target):
        # Simple controls describe each part's final percentage independently.
        # The core cancels a parent's scale even when its child is also edited.
        __slots__ = ()
        compensate_explicit = True

    options = {option["value"]: option for option in _body_part_options(meshes)}
    selected = [mesh for mesh in meshes if (
        mesh["name"] in mesh_filter if mesh_filter is not None
        else include_hidden or mesh["name"] not in m.DEFAULT_HIDDEN)]
    selected_names = {name for mesh in selected for name in mesh["bones"]}
    targets = []
    for part, percent in percentages.items():
        if percent == 100:
            continue
        option = options[part]
        if not option["available"]:
            raise ValueError(f"{option['label']} is unavailable in this model. {option['reason']}")
        missing = set(option["bones"]) - selected_names
        if part == "torso" and "Spine2" not in selected_names:
            missing.add("Spine2")
        if missing:
            raise ValueError(f"{option['label']} is excluded by the mesh selection. Clear 'Only these meshes' "
                             "or enable 'Include hidden meshes'.")
        factor = percent / 100
        thickness = option["kind"] == "thickness"
        scale = (1.0, factor, factor) if thickness else (factor,) * 3
        for bone in option["bones"]:
            target = BodyPartTarget(bone, scale=scale, compensate=thickness)
            if part == "torso":
                # This keeps the requested width through Spine1 and prevents
                # that scale from also changing shoulders, head and arms.
                target.comp_bones = ["Spine2"]
            targets.append(target)
    return targets


def _triple(value, default, label, positive=False):
    if value is None:
        value = default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain X, Y and Z values.")
    try:
        if any(isinstance(v, bool) for v in value):
            raise ValueError
        numbers = tuple(float(v) for v in value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{label} must contain three finite numbers.") from None
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError(f"{label} must contain three finite numbers.")
    if positive and any(v <= 0 for v in numbers):
        raise ValueError(f"{label} values must be greater than zero.")
    return numbers


def _has_transform(target):
    return (tuple(getattr(target, "scale", (1, 1, 1))) != (1, 1, 1)
            or tuple(getattr(target, "rotate", (0, 0, 0))) != (0, 0, 0)
            or tuple(getattr(target, "translate", (0, 0, 0))) != (0, 0, 0))


def _build_targets(m, params, allow_empty=False):
    targets = []
    rows = params.get("targets")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("Bone transforms must be a list.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each bone transform must be an object.")
        bone = row.get("bone")
        if not isinstance(bone, str) or not bone.strip():
            raise ValueError("Choose a bone for each transform.")
        bone = bone.strip()
        if bone in seen:
            raise ValueError(f"{bone} has more than one transform. Edit its existing row.")
        seen.add(bone)
        comp = row.get("compensate", m.default_compensate(bone))
        if not isinstance(comp, bool):
            raise ValueError(f"{bone}: child compensation must be true or false.")
        targets.append(m.Target(
            bone,
            scale=_triple(row.get("scale"), (1, 1, 1), f"{bone} scale", positive=True),
            rotate=_triple(row.get("rotate"), (0, 0, 0), f"{bone} rotation"),
            translate=_triple(row.get("translate"), (0, 0, 0), f"{bone} translation"),
            compensate=comp,
        ))
    spec = (params.get("target_spec") or "").strip()
    for line in spec.replace(";;", "\n").splitlines():
        line = line.strip()
        if line:
            targets.append(m.parse_target_spec(line))
    thigh = (params.get("thigh") or "").strip()
    if thigh:
        src, dst = thigh.lower().split(":")
        targets += m.thigh_targets(src, dst)
    if not targets and not allow_empty:
        raise ValueError("Add a bone transform, an advanced target spec, or a thigh preset.")
    # match the desktop GUI/CLI: pick which child bone absorbs the inverse scale
    # for compensated Spine* targets (default spine2). No-op on non-Spine targets.
    m.apply_spine_comp(targets, params.get("spine_comp") or "spine2")
    return targets


def run_mesh_baker(job, params):
    ensure_repo_on_path()
    import sifas_mesh_baker as m

    body_percentages = _body_part_percentages(params["body_parts"]) if "body_parts" in params else None
    targets = _build_targets(m, params, allow_empty=body_percentages is not None)
    body_changed = body_percentages is not None and any(percent != 100 for percent in body_percentages.values())
    if body_percentages is not None and all(percent == 100 for percent in body_percentages.values()) \
            and not any(_has_transform(target) for target in targets):
        raise ValueError("Choose a body part and move its slider away from 100%.")
    recompute = bool(params.get("recompute_normals", True))
    hierarchical = bool(params.get("hierarchical", True))
    if body_changed:
        hierarchical = True
    include_hidden = bool(params.get("include_hidden", False))
    if body_percentages is not None and body_percentages["head"] != 100:
        include_hidden = True
    # optional per-mesh restriction (comma/newline separated); blank = all skinned,
    # non-hidden meshes, matching the desktop default of every mesh checked.
    names = [n.strip() for n in (params.get("mesh_names") or "").replace(",", "\n").splitlines() if n.strip()]
    mesh_filter = set(names) or None
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or "_baked"
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        file_targets = targets
        if body_changed:
            simple_targets = _build_body_targets(
                m, body_percentages, _inspect_bundle(m, src),
                mesh_filter=mesh_filter, include_hidden=include_hidden)
            conflicts = {target.bone for target in targets} & {target.bone for target in simple_targets}
            if conflicts:
                raise ValueError("Use either the body part control or the advanced editor for: "
                                 + ", ".join(sorted(conflicts)))
            file_targets = simple_targets + targets
        results = m.process_bundle(Path(src), out_path, file_targets,
                                   recompute_normals=recompute, hierarchical=hierarchical,
                                   mesh_filter=mesh_filter, include_hidden=include_hidden, log=job.log)
        # The core deliberately skips saving when no transform applies (e.g. a
        # bone only exists on hidden Hair). Never turn that into a successful
        # download path, even if an older output happens to exist there.
        if not any(result.get("applied") for result in results):
            raise ValueError(
                "No transform was applied; no output was saved. Check bone/mesh names "
                "and change at least one scale, rotation or movement value. For bones "
                "on Hair, Face or foot_shadow, enable 'Include hidden meshes' or "
                "select the mesh explicitly in 'Only these meshes'.")
        if not Path(out_path).is_file() or Path(out_path).stat().st_size == 0:
            raise RuntimeError(f"Baking did not create an output bundle: {out_path}")
        publish = getattr(job, "add_output", None)
        if callable(publish):
            publish(out_path)
        return ""

    if params.get("mode") == "batch":
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    job.log(f"baking {Path(in_file).name} … "
            "(mesh processing + save can take a while on mobile)")
    edit(in_file, out_path)
    job.progress(1, 1)
    return f"baked -> {out_path}"


# ----------------------------------------------------- fix bundle export
def run_fix_export(job, params):
    ensure_repo_on_path()
    import fix_sifas_bundle_export as m

    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or "_fixed"
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        n = m.normalize(str(src), str(out_path), verbose=False)
        ok = m.validate(str(src), str(out_path), verbose=False)
        return f"meshes fixed={n}, validate={'ok' if ok else 'FAIL'}"

    if params.get("mode") == "batch":
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    status = edit(in_file, out_path)
    job.log(f"OK {Path(in_file).name} -> {out_path.name} ({status})")
    job.progress(1, 1)
    return f"{status} -> {out_path}"
