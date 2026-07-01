"""Adapter for sifas_breast_tuner.py (Physics/Dyna + Size).

Imports the real module and calls its existing pure-core functions
(modify_swingbones_in_bundle / modify_livecore_scaling) and batch runners
(run_dyna_batch / run_size_batch) so the WebUI runs byte-identical code to the
CLI. The module is import-safe (tkinter/UnityPy are lazy)."""
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.tools.common import (
    as_float, as_float_or_none, parse_patterns, single_out_path, triple_add, triple_set,
)

DEFAULT_DYNA_PATTERNS = ["LeftBreast_Dyna", "RightBreast_Dyna"]
DEFAULT_BREAST_NAME = "BreastSize"


def _module():
    ensure_repo_on_path()
    import sifas_breast_tuner as m
    m.ensure_unitypy()  # breast cores call UnityPy.load directly, so load it first
    return m


def run_dyna(job, params):
    m = _module()
    patterns = parse_patterns(params.get("patterns"), DEFAULT_DYNA_PATTERNS)
    stiff = as_float_or_none(params.get("stiff"))
    drag = as_float_or_none(params.get("drag"))
    ldy = as_float(params.get("low_dy"))
    ldz = as_float(params.get("low_dz"))
    hdy = as_float(params.get("high_dy"))
    hdz = as_float(params.get("high_dz"))
    # jiggle_auto: "off" | "size" (follow current bundle size) | "character"
    # (character's stock tier). Fall back to the old use_character_specific bool.
    jiggle_auto = (params.get("jiggle_auto") or "").strip().lower()
    if not jiggle_auto:
        jiggle_auto = "size" if bool(params.get("use_character_specific")) else "off"
    use_auto = jiggle_auto in ("size", "character")
    jiggle_by = "character" if jiggle_auto == "character" else "size"
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        total, ok, fail = m.run_dyna_batch(
            params.get("in_dir"), out_dir, prefix, suffix, patterns,
            stiff, drag, ldy, ldz, hdy, hdz, use_auto,
            job.log, job.progress, job.should_stop, jiggle_by=jiggle_by,
        )
        return f"batch done: total={total} ok={ok} fail={fail}"

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    job.log(f"reading + editing + saving {Path(in_file).name} … "
            "(parse/save is the slow part on mobile)")
    scanned, changed, _lines, n = m.modify_swingbones_in_bundle(
        Path(in_file), out_path, patterns, stiff, drag, ldy, ldz, hdy, hdz,
        use_character_specific=use_auto, jiggle_by=jiggle_by,
    )
    job.log(f"OK {Path(in_file).name} -> {out_path.name} (scanned={scanned}, changed={changed})")
    job.progress(1, 1)
    return f"changed={changed} -> {out_path}"


def run_size(job, params):
    m = _module()
    breast_name = params.get("breast_name") or DEFAULT_BREAST_NAME
    set_xyz = triple_set(params, ("set_x", "set_y", "set_z"))
    add_dxyz = triple_add(params, ("add_x", "add_y", "add_z"))
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        total, ok, fail = m.run_size_batch(
            params.get("in_dir"), out_dir, prefix, suffix, breast_name, set_xyz, add_dxyz,
            job.log, job.progress, job.should_stop,
        )
        return f"batch done: total={total} ok={ok} fail={fail}"

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, prefix, suffix)
    job.progress(0, 1)
    job.log(f"reading + editing + saving {Path(in_file).name} … "
            "(parse/save is the slow part on mobile)")
    scanned, changed, _lines = m.modify_livecore_scaling(
        Path(in_file), out_path, breast_name, set_xyz, add_dxyz,
    )
    job.log(f"OK {Path(in_file).name} -> {out_path.name} (scanned={scanned}, changed={changed})")
    job.progress(1, 1)
    return f"changed={changed} -> {out_path}"
