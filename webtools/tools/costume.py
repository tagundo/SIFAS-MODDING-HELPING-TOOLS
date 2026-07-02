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

    # On the app the native texture decoders are absent, so thumbnail decode would
    # fall back to a name-only placeholder. Wire ASTC decode through the bundled
    # astcenc CLI so SIFAS's (ASTC) textures give real image thumbnails. No-op on
    # desktop / if unavailable; the packer already tolerates decode failures.
    try:
        from webtools.tools.texture import ensure_astc_cli
        ensure_astc_cli()
    except Exception as exc:  # never let thumbnail wiring break packing
        job.log(f"(astc thumbnail bridge unavailable: {exc})")

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
    # full desktop-GUI option surface; checkbox -> mode mappings mirror run_gui's
    # go(): mask on->"auto"/off->"off", donor-physics on->"donor"/off->"target".
    m.transplant(
        str(donor), str(target), str(out_path), verbose=False,
        preserve_physics=bool(params.get("preserve_physics", True)),
        realign=bool(params.get("realign", True)),
        restore_collision=bool(params.get("restore_collision", True)),
        worldspace=bool(params.get("worldspace", True)),
        fix_nodescaling=bool(params.get("fix_nodescaling", True)),
        mask_handling="auto" if bool(params.get("mask_handling", True)) else "off",
        costume_physics="donor" if bool(params.get("donor_costume_physics", True)) else "target",
        sync_textures=not bool(params.get("no_textures", False)),
        scale_swing_physics=bool(params.get("scale_swing_physics", True)),
    )

    # Optionally match the transplanted costume to the target character: thigh size
    # (donor body type -> target's) and/or skin tone (donor tone -> target's).
    _match_to_target(job, params, donor, target, out_path)

    ok = m.validate(str(out_path), verbose=False)
    job.log(f"OK -> {out_path.name}  (validation: {'passed' if ok else 'FAILED'})")
    job.progress(1, 1)
    return f"transplanted -> {out_path}  (validate: {'ok' if ok else 'fail'})"


def _match_to_target(job, params, donor, target, out_path):
    from webtools.core import bodymatch
    match_thigh = bool(params.get("match_thigh", False))
    match_skin = bool(params.get("match_skin", False))
    if not (match_thigh or match_skin):
        return
    from webtools.core import charinfo
    dchar = bodymatch.detect_char_from_bundle(donor)
    tchar = bodymatch.detect_char_from_bundle(target)
    job.log(f"[match] donor {dchar or '?'} ({charinfo.NAMES.get(dchar, '?')}) "
            f"-> target {tchar or '?'} ({charinfo.NAMES.get(tchar, '?')})")
    if match_thigh:
        if not dchar or not tchar:
            job.log("[thigh] could not detect both characters; skipped")
        else:
            tmp = str(out_path) + ".thigh.tmp"
            try:
                if bodymatch.apply_thigh_match(out_path, tmp,
                                               charinfo.THIGH.get(dchar), charinfo.THIGH.get(tchar),
                                               log=job.log):
                    os.replace(tmp, str(out_path))
            except Exception as exc:
                job.log(f"[thigh] failed: {exc}")
                if os.path.exists(tmp):
                    os.remove(tmp)
    if match_skin:
        # only the TARGET character (the destination tone) is required: the
        # source tone is auto-detected from the texture pixels, with the
        # donor's table tone as fallback (bodymatch.apply_skin_match).
        if not tchar:
            job.log("[skin] could not detect the target character; skipped")
            return
        skin_only = bool(params.get("skin_only", bodymatch.is_android()))
        tmp = str(out_path) + ".skin.tmp"
        try:
            if bodymatch.apply_skin_match(out_path, tmp,
                                          charinfo.SKIN_TONE.get(dchar), charinfo.SKIN_TONE.get(tchar),
                                          skin_only=skin_only, log=job.log):
                os.replace(tmp, str(out_path))
        except Exception as exc:
            job.log(f"[skin] failed: {exc}")
            if os.path.exists(tmp):
                os.remove(tmp)


# ------------------------------------------------- costume part transplant
def run_costume_part_transplant(job, params):
    # decodes + re-encodes textures, so wire the ASTC CLI bridge first
    from webtools.tools.texture import ensure_astc_cli
    ensure_astc_cli()
    ensure_repo_on_path()
    import costume_part_transplant as m

    donor = params.get("donor")
    target = params.get("target")
    out_dir = params.get("out_dir")
    suffix = params.get("suffix") or "_part"
    out_path = single_out_path(out_dir, target, "", suffix)
    part_root = (params.get("part_root") or "").strip() or None

    job.progress(0, 1)
    job.log(f"transplanting part from {Path(donor).name} onto {Path(target).name} …")
    m.transplant_part(
        str(donor), str(target), str(out_path),
        part_root=part_root, auto=(part_root is None),
        preserve_physics=bool(params.get("preserve_physics", True)),
        restore_collision=bool(params.get("restore_collision", True)),
        patch_texture=bool(params.get("patch_texture", False)),
        worldspace=True, fix_nodescaling=True, verbose=False,
    )
    job.progress(1, 1)
    job.log(f"OK -> {out_path.name}")
    return f"part transplanted -> {out_path}"


# --------------------------------------------------------- lower body swap
def run_lower_body_swap(job, params):
    from webtools.tools.texture import ensure_astc_cli
    ensure_astc_cli()
    ensure_repo_on_path()
    import lower_body_swap as m

    donor = params.get("donor")
    out_dir = params.get("out_dir")
    suffix = params.get("suffix") or "_lower"
    region = params.get("region") or "lower"
    exclude_acc = bool(params.get("exclude_accessories", True))
    kw = dict(region=region, exclude_accessories=exclude_acc, log=job.log)
    for k in ("cut_low", "cut_high"):
        v = as_float(params.get(k), None) if params.get(k) not in (None, "") else None
        if v is not None:
            kw[k] = v

    match = bool(params.get("match_thigh", False)) or bool(params.get("match_skin", False))

    if params.get("mode") == "batch":
        if not match:
            m.run_batch(str(donor), params.get("in_dir"), out_root=out_dir, **kw)
            return "batch lower-body swap done (see log)"
        # matching requested: loop so each output can be matched to its own target
        # (mirrors run_batch's donor-skip + relative-path layout).
        from webtools.core.sukusta import find_bundles
        folder = params.get("in_dir")
        targets = [str(t) for t in find_bundles(folder)
                   if os.path.abspath(str(t)) != os.path.abspath(str(donor))]
        ok = 0
        for i, tgt in enumerate(targets):
            out = os.path.join(out_dir, os.path.relpath(tgt, folder))
            try:
                os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
                job.log(f"• {os.path.relpath(tgt, folder)}")
                m.graft_one(tgt, str(donor), out, **kw)
                _match_to_target(job, params, donor, tgt, out)
                ok += 1
            except Exception as exc:
                job.log(f"  skip ({exc})")
            job.progress(i + 1, len(targets))
        return f"batch lower-body swap + match: {ok}/{len(targets)}"

    target = params.get("target")
    out_path = single_out_path(out_dir, target, "", suffix)
    job.progress(0, 1)
    job.log(f"grafting lower body from {Path(donor).name} onto {Path(target).name} …")
    m.graft_one(str(target), str(donor), str(out_path), **kw)
    _match_to_target(job, params, donor, target, out_path)
    job.progress(1, 1)
    return f"lower body swapped -> {out_path}"


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
