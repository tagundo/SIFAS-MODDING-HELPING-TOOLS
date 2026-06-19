"""Adapter for sifas-assetbundle-renamer-by-texture.py.

The filename has hyphens (not a valid module name) AND it imports tkinter at top
level, so we install the headless tk stub and load it by path via importlib.
Its two pure functions (extract_texture_name / generate_new_filename) are reused;
the rename loop is done here, writing renamed *copies* into out_dir (safe -
never touches the originals in place).
"""
import importlib.util
import os
import shutil
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path, repo_root
from webtools.core.sukusta import find_bundles
from webtools.core.tkstub import ensure_tk_stub
from webtools.tools.common import as_float_or_none

_MODULE = None


def _module():
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    ensure_tk_stub()
    ensure_repo_on_path()
    path = repo_root() / "sifas-assetbundle-renamer-by-texture.py"
    spec = importlib.util.spec_from_file_location("sifas_renamer_by_texture", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MODULE = mod
    return mod


def run_renamer(job, params):
    m = _module()
    in_dir = params.get("in_dir")
    out_dir = params.get("out_dir")
    include_costume_id = bool(params.get("include_costume_id", False))
    remove_special = bool(params.get("remove_special_chars", False))
    length_limit = as_float_or_none(params.get("filename_length_limit"))
    length_limit = int(length_limit) if length_limit else None

    os.makedirs(out_dir, exist_ok=True)
    bundles = find_bundles(in_dir)
    total = len(bundles)
    ok = renamed = skipped = 0
    for i, src in enumerate(bundles, 1):
        if job.should_stop():
            job.log("[stopped]")
            break
        try:
            tex = m.extract_texture_name(str(src))
            new_name = m.generate_new_filename(
                src.name, tex, include_costume_id=include_costume_id,
                remove_special_chars=remove_special, filename_length_limit=length_limit)
            dst = Path(out_dir) / new_name
            shutil.copy2(str(src), str(dst))
            ok += 1
            if new_name != src.name:
                renamed += 1
                job.log(f"OK   {src.name} -> {new_name}")
            else:
                skipped += 1
                job.log(f"--   {src.name} (no texture name found; copied unchanged)")
        except Exception as exc:  # noqa: BLE001
            job.log(f"FAIL {src.name}: {exc}")
        job.progress(i, total)
    job.log(f"Done. total={total}  copied={ok}  renamed={renamed}  unchanged={skipped}")
    return f"copied={ok} renamed={renamed} -> {out_dir}"
