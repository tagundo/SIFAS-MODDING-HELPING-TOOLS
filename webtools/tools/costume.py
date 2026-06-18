"""Adapters for unity_costumemod_packer, costume_transplant,
assetbundle_IosApk_batch_import_plus.

packer and transplant are import-safe (lazy Tk). The IosApk importer `import`s
tkinter at top, so the headless stub is installed first.
"""
import os
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.core.sukusta import find_bundles
from webtools.core.tkstub import ensure_tk_stub
from webtools.tools.common import as_float, parse_patterns, single_out_path


# ---------------------------------------------------------- costume packer
def run_costume_packer(job, params):
    ensure_repo_on_path()
    import unity_costumemod_packer as m

    out_dir = params.get("out_dir")
    auto_chara_id = bool(params.get("auto_chara_id", True))
    manual_chara_id = int(as_float(params.get("manual_chara_id"), 0))
    thumbnail_size = int(as_float(params.get("thumbnail_size"), 256))

    if params.get("mode") == "batch":
        combine_pairs = bool(params.get("combine_pairs", True))
        files = [str(p) for p in find_bundles(params.get("in_dir"))]
        job.log(f"packing {len(files)} bundle(s)...")
        success, fail = m.run_pack_jobs(
            files, out_dir, auto_chara_id=auto_chara_id, manual_chara_id=manual_chara_id,
            thumbnail_size=thumbnail_size, combine_pairs=combine_pairs,
            ask_chara_id=None, log=job.log)
        job.progress(1, 1)
        return f"packed: success={success} fail={fail}"

    in_file = params.get("in_path")
    job.progress(0, 1)
    zip_path = m.pack_single_bundle(
        in_file, out_dir, auto_chara_id=auto_chara_id, manual_chara_id=manual_chara_id,
        thumbnail_size=thumbnail_size, ask_chara_id=None, log=job.log)
    job.progress(1, 1)
    if not zip_path:
        raise RuntimeError("packing failed (see log above)")
    return f"created {os.path.basename(zip_path)}"


# -------------------------------------------------------- costume transplant
def run_costume_transplant(job, params):
    ensure_repo_on_path()
    import costume_transplant as m

    donor = params.get("donor")
    target = params.get("target")
    out_dir = params.get("out_dir")
    suffix = params.get("suffix") or "_transplant"
    out_path = single_out_path(out_dir, target, "", suffix)

    job.log(f"transplanting {Path(donor).name} (costume) onto {Path(target).name} (wearer)...")
    job.progress(0, 1)
    m.transplant(
        str(donor), str(target), str(out_path), verbose=False,
        preserve_physics=bool(params.get("preserve_physics", False)),
        realign=bool(params.get("realign", True)),
        restore_collision=bool(params.get("restore_collision", True)),
        worldspace=bool(params.get("worldspace", True)),
        fix_nodescaling=bool(params.get("fix_nodescaling", True)),
    )
    ok = m.validate(str(out_path), verbose=False)
    job.log(f"OK -> {out_path.name}  (validation: {'passed' if ok else 'FAILED'})")
    job.progress(1, 1)
    return f"transplanted -> {out_path}  (validate: {'ok' if ok else 'fail'})"


# ---------------------------------------------- iOS/APK selective pair import
def run_iosapk_import(job, params):
    ensure_tk_stub()
    ensure_repo_on_path()
    import assetbundle_IosApk_batch_import_plus as m

    import_new = bool(params.get("import_new_objects", True))
    name_inc = parse_patterns(params.get("name_include"), [])
    name_exc = parse_patterns(params.get("name_exclude"), [])
    empty = set()
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        prefix = params.get("prefix") or ""
        suffix = params.get("suffix") or ""
        job.log("pairing donor/target bundles by pathID intersection...")
        job.progress(0, 1)
        m.batch_by_pid(
            Path(params.get("donor_dir")), Path(params.get("target_dir")), Path(out_dir),
            empty, empty, empty, empty, name_inc, name_exc, [],
            out_prefix=prefix, out_suffix=suffix, import_new_objects=import_new)
        job.progress(1, 1)
        return "batch import complete (see log)"

    donor = params.get("donor")
    target = params.get("target")
    suffix = params.get("suffix") or "_import"
    export = single_out_path(out_dir, target, "", suffix)
    job.progress(0, 1)
    candidates, applied, skipped, injected, failed = m.copy_selective_from_pair(
        Path(donor), Path(target), export,
        empty, empty, empty, empty, name_inc, name_exc, [], import_new_objects=import_new)
    job.log(f"OK -> {export.name}  (candidates={candidates}, applied={applied}, "
            f"injected={injected}, skipped={skipped}, failed={len(failed)})")
    job.progress(1, 1)
    return f"applied={applied} injected={injected} -> {export}"
