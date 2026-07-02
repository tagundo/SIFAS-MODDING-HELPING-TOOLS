"""Adapters for sifas_mesh_baker and fix_sifas_bundle_export (both import-safe).

mesh_baker bakes bone scale/rotate/translate into mesh vertices, driven by a
"target spec" string (same grammar as its CLI --target). fix_export normalizes
skinned meshes to world space.
"""
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.tools.common import run_batch, single_out_path


# --------------------------------------------------------------- mesh baker
def _build_targets(m, params):
    targets = []
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
        raise ValueError("Provide at least one target spec line (e.g. 'Spine2;s=1.1') or a thigh preset.")
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
        m.process_bundle(Path(src), out_path, targets,
                         recompute_normals=recompute, hierarchical=hierarchical,
                         mesh_filter=mesh_filter, include_hidden=include_hidden, log=job.log)
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
