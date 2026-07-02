"""Adapters for hips_size_changer, Upleg_SwingCollider_changer, sifas_node_scaling.

hips and upleg `import tkinter` at module top, so we install the headless tk
stub before importing them; their core functions never touch tkinter.
node_scaling is import-safe.
"""
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.core.tkstub import ensure_tk_stub
from webtools.tools.common import (
    as_float, as_float_or_none, parse_patterns, run_batch, single_out_path,
    triple_add, triple_set,
)

DEFAULT_HIPS_NAME = "HipsSize"
DEFAULT_UPLEG_PATTERNS = ["LeftUpLeg", "RightUpLeg"]
NODE_SCALING_MODES = ["rebase", "neutralize", "none"]


# ----------------------------------------------------------------- hips size
def run_hips(job, params):
    ensure_tk_stub()
    ensure_repo_on_path()
    import hips_size_changer as m

    name = params.get("target_go_name") or DEFAULT_HIPS_NAME
    set_xyz = triple_set(params, ("set_x", "set_y", "set_z"))
    add_dxyz = triple_add(params, ("add_x", "add_y", "add_z"))
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        scanned, changed, _ = m.modify_livecore_scaling(Path(src), out_path, name, set_xyz, add_dxyz)
        return f"scanned={scanned}, changed={changed}"

    if params.get("mode") == "batch":
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    status = edit(in_file, out_path)
    job.log(f"OK {Path(in_file).name} -> {out_path.name} ({status})")
    job.progress(1, 1)
    return f"{status} -> {out_path}"


# ------------------------------------------------------- upleg swing collider
def run_upleg(job, params):
    ensure_tk_stub()
    ensure_repo_on_path()
    import Upleg_SwingCollider_changer as m

    patterns = parse_patterns(params.get("patterns"), DEFAULT_UPLEG_PATTERNS)
    set_radius = as_float_or_none(params.get("set_radius"))
    add_radius = as_float(params.get("add_radius"), 0.0)
    set_offset = triple_set(params, ("set_off_x", "set_off_y", "set_off_z"))
    add_offset = triple_add(params, ("add_off_x", "add_off_y", "add_off_z"))
    # optional clamps (blank = None = no bound), matching the desktop GUI. A tuple
    # is passed only when at least one axis is set; per-axis None leaves that axis free.
    radius_min = as_float_or_none(params.get("radius_min"))
    radius_max = as_float_or_none(params.get("radius_max"))
    offset_min = triple_set(params, ("off_min_x", "off_min_y", "off_min_z"))
    offset_max = triple_set(params, ("off_max_x", "off_max_y", "off_max_z"))
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        scanned, changed, _ = m.modify_swingcolliders(
            Path(src), out_path, patterns, set_radius, add_radius, set_offset, add_offset,
            radius_min=radius_min, radius_max=radius_max,
            offset_min=offset_min, offset_max=offset_max)
        return f"scanned={scanned}, changed={changed}"

    if params.get("mode") == "batch":
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    status = edit(in_file, out_path)
    job.log(f"OK {Path(in_file).name} -> {out_path.name} ({status})")
    job.progress(1, 1)
    return f"{status} -> {out_path}"


# --------------------------------------------------- accessory un-clip
def run_accessory_unclip(job, params):
    # lazy tkinter (no stub needed); mesh/transform surgery, no texture codec.
    ensure_repo_on_path()
    import sifas_accessory_unclip as m

    strength = as_float(params.get("strength"), 1.0)
    overlap = as_float(params.get("overlap"), 0.15)
    close_gaps = bool(params.get("close_gaps"))
    anchors = (params.get("anchors") or "").strip() or None
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or "_unclip"
    out_dir = params.get("out_dir")

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    job.log(f"un-clipping {Path(in_file).name} …")
    res = m.process(in_file, out=str(out_path), report=False, strength=strength,
                    overlap=overlap, anchors=anchors, close_gaps=close_gaps, verbose=False)
    job.progress(1, 1)
    lifted = (res or {}).get("lifted") or []
    job.log(f"OK {Path(in_file).name} -> {out_path.name} (lifted {len(lifted)} part(s))")
    return f"lifted {len(lifted)} accessory anchor(s) -> {out_path}"


# ------------------------------------------------------------- node scaling
def _node_lines(raw):
    """Split a textarea of node-scaling specs into non-empty, non-comment lines."""
    out = []
    for line in (raw or "").replace(";;", "\n").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def run_node_scaling(job, params):
    ensure_repo_on_path()
    import sifas_node_scaling as m

    mode = params.get("mode_select") or "rebase"
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    # optional manual add/edit specs, same grammar as the desktop CLI (--add/--set),
    # parsed with the tool's own parsers so the web can't drift from it. Like the
    # desktop, these apply to single-file runs only (auto-repair still runs in batch).
    add_specs = _node_lines(params.get("add_entries"))
    set_specs = _node_lines(params.get("set_entries"))
    adds = [m._parse_add(s) for s in add_specs] or None

    def edit(src, out_path):
        # expand wildcard --set keys to real (target,kind,bone) tuples per bundle,
        # mirroring sifas_node_scaling.run_cli's expand() step.
        edits = None
        if set_specs:
            import UnityPy
            wild = {}
            for s in set_specs:
                (kind, bone), vals = m._parse_set(s)
                wild[("*", kind, bone)] = vals
            _, entries = m.scan_components(UnityPy.load(str(src)))
            edits = {}
            for e in entries:
                k = ("*", e.kind, e.bone)
                if k in wild:
                    edits[(e.target_name, e.kind, e.bone)] = wild[k]
        n = m.process_bundle(Path(src), out_path, mode=mode,
                             adds=adds, edits=edits or None, log=job.log)
        return f"changed={n}"

    if params.get("mode") == "batch":
        if adds or set_specs:
            job.log("[note] add/edit entries apply to single-file runs only; "
                    "batch performs auto-repair (rebase/neutralize/none) only.")
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    status = edit(in_file, out_path)
    job.progress(1, 1)
    return f"{status} -> {out_path}"
