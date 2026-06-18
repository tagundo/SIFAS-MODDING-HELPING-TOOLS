"""Adapter for skirt_length_changer.py.

modify_skirt_scaling() already calls ensure_unitypy() itself, so we just import
the module (it is import-safe: tkinter is lazy). The tool has no callback batch
runner, so batch mode iterates here using its find_asset_bundles() helper while
emitting the same on_log / on_progress / should_stop events as the other tools.
"""
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.tools.common import (
    batch_out_path, parse_patterns, single_out_path, triple_add, triple_set,
)

DEFAULT_SKIRT_PATTERNS = [
    "SkirtA1_Dyna", "SkirtE1_Dyna",
    "LeftSkirtB1_Dyna", "RightSkirtB1_Dyna",
    "LeftSkirtC1_Dyna", "RightSkirtC1_Dyna",
    "LeftSkirtD1_Dyna", "RightSkirtD1_Dyna",
]


def _module():
    ensure_repo_on_path()
    import skirt_length_changer as m
    return m


def run_skirt(job, params):
    m = _module()
    patterns = parse_patterns(params.get("patterns"), DEFAULT_SKIRT_PATTERNS)
    set_xyz = triple_set(params, ("set_x", "set_y", "set_z"))
    add_dxyz = triple_add(params, ("add_x", "add_y", "add_z"))
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        in_dir = params.get("in_dir")
        bundles = m.find_asset_bundles(in_dir)
        total = len(bundles)
        ok = fail = 0
        for i, src in enumerate(bundles, 1):
            if job.should_stop():
                job.log("[stopped]")
                break
            out_path = batch_out_path(in_dir, src, out_dir, prefix, suffix)
            try:
                scanned, changed, _ = m.modify_skirt_scaling(
                    Path(src), out_path, patterns, set_xyz, add_dxyz, write_log_file=False,
                )
                ok += 1
                job.log(f"OK   {Path(src).name} -> {out_path.name} (scanned={scanned}, changed={changed})")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                job.log(f"FAIL {Path(src).name}: {exc}")
            job.progress(i, total)
        job.log(f"Done. total={total}  ok={ok}  fail={fail}")
        return f"batch done: total={total} ok={ok} fail={fail}"

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    scanned, changed, _lines = m.modify_skirt_scaling(
        Path(in_file), out_path, patterns, set_xyz, add_dxyz,
    )
    job.log(f"OK {Path(in_file).name} -> {out_path.name} (scanned={scanned}, changed={changed})")
    job.progress(1, 1)
    return f"changed={changed} -> {out_path}"
