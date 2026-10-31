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
def inspect_bones(params):
    """List the real bone names in a reference bundle for the pose editor."""
    reference = (params.get("reference_path") or "").strip()
    if not reference:
        return []
    ensure_repo_on_path()
    import sifas_mesh_baker as m

    env = m.UnityPy.load(reference)
    tos = m.build_bone_name_map(env)
    id2obj = m.build_id_map(env)
    smr_map = m.smr_bone_pids(env, id2obj)
    meshes_by_bone = {}
    for mi in m.list_meshes(env):
        if not mi.skinned:
            continue
        names, _ = m.resolve_bones(env, id2obj, tos, mi.obj, mi.tree, smr_map)
        for name in names:
            # These fallback labels identify unresolved hashes/indices, not a
            # bone which a user can meaningfully choose by name.
            if name and not name.startswith(("<bone:", "<hash:")):
                meshes_by_bone.setdefault(name, set()).add(mi.name)
    return [{"value": name, "label": f"{name} ({', '.join(sorted(meshes_by_bone[name]))})"}
            for name in sorted(meshes_by_bone, key=str.casefold)]


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


def _build_targets(m, params):
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
    if not targets:
        raise ValueError("Add a bone transform, an advanced target spec, or a thigh preset.")
    # match the desktop GUI/CLI: pick which child bone absorbs the inverse scale
    # for compensated Spine* targets (default spine2). No-op on non-Spine targets.
    m.apply_spine_comp(targets, params.get("spine_comp") or "spine2")
    return targets


def run_mesh_baker(job, params):
    ensure_repo_on_path()
    import sifas_mesh_baker as m

    targets = _build_targets(m, params)
    recompute = bool(params.get("recompute_normals", True))
    hierarchical = bool(params.get("hierarchical", True))
    include_hidden = bool(params.get("include_hidden", False))
    # optional per-mesh restriction (comma/newline separated); blank = all skinned,
    # non-hidden meshes, matching the desktop default of every mesh checked.
    names = [n.strip() for n in (params.get("mesh_names") or "").replace(",", "\n").splitlines() if n.strip()]
    mesh_filter = set(names) or None
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or "_baked"
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        results = m.process_bundle(Path(src), out_path, targets,
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
