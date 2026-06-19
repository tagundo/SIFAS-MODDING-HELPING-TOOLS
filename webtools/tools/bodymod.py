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
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        scanned, changed, _ = m.modify_swingcolliders(
            Path(src), out_path, patterns, set_radius, add_radius, set_offset, add_offset)
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


# ------------------------------------------------------------- node scaling
def run_node_scaling(job, params):
    ensure_repo_on_path()
    import sifas_node_scaling as m

    mode = params.get("mode_select") or "rebase"
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    def edit(src, out_path):
        n = m.process_bundle(Path(src), out_path, mode=mode, log=job.log)
        return f"changed={n}"

    if params.get("mode") == "batch":
        return run_batch(job, params.get("in_dir"), out_dir, prefix, suffix, edit)

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    status = edit(in_file, out_path)
    job.progress(1, 1)
    return f"{status} -> {out_path}"
