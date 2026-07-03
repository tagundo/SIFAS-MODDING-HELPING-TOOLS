"""Adapters for unity_costumemod_packer, costume_transplant,
assetbundle_IosApk_batch_import_plus.

packer and transplant are import-safe (lazy Tk). The IosApk importer `import`s
tkinter at top, so the headless stub is installed first.
"""
import os
import re
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.core.sukusta import find_bundles
from webtools.core.tkstub import ensure_tk_stub
from webtools.tools.common import as_float, single_out_path


# ---- dynamic dropdown provider: donor -> candidate part-root bones ----------
def part_root_options(params):
    """Options for the Costume Part Transplant 'part root bone' dropdown: the
    donor bundle's candidate part roots, mirroring the desktop GUI's parts
    combobox (costume_part_transplant.inspect). Returns [{value, label}]; the
    value is the bone name transplant_part expects, the label adds vert/tri/bone
    counts. Empty list when no donor is chosen yet."""
    donor = (params.get("donor") or "").strip()
    if not donor:
        return []
    ensure_repo_on_path()
    import costume_part_transplant as cpt
    out = []
    for p in cpt.inspect(donor, verbose=False):
        root = p.get("root")
        if not root:
            continue
        out.append({
            "value": root,
            "label": "%s  (%d v, %d t, %d bones)" % (
                root, p.get("verts", 0), p.get("tris", 0), len(p.get("bones", []) or [])),
        })
    return out


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
        colour_guard = bool(params.get("skin_colour_guard", False))
        donor_tone = params.get("donor_tone")
        src_override = donor_tone if donor_tone in (
            "bright", "default", "slight", "medium_tone") else None
        tmp = str(out_path) + ".skin.tmp"
        try:
            if bodymatch.apply_skin_match(out_path, tmp,
                                          charinfo.SKIN_TONE.get(dchar), charinfo.SKIN_TONE.get(tchar),
                                          skin_only=skin_only, src_override=src_override,
                                          colour_guard=colour_guard, log=job.log):
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

    # GUI maps the unchecked "own sub-mesh" box to new_submesh="auto"; checked -> True
    new_submesh = True if params.get("new_submesh") else "auto"
    job.progress(0, 1)
    job.log(f"transplanting part from {Path(donor).name} onto {Path(target).name} …")
    m.transplant_part(
        str(donor), str(target), str(out_path),
        part_root=part_root, auto=(part_root is None),
        preserve_physics=bool(params.get("preserve_physics", True)),
        restore_collision=bool(params.get("restore_collision", True)),
        new_submesh=new_submesh,
        patch_texture=bool(params.get("patch_texture", False)),
        worldspace=bool(params.get("worldspace", True)),
        fix_nodescaling=bool(params.get("fix_nodescaling", True)), verbose=False,
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
    # Default the output folder like run_batch does, so every path (single, batch,
    # and the match-batch loop below) behaves the same even without an out_dir.
    out_dir = params.get("out_dir") or os.path.join(m.sukusta_dir(), "modded")
    suffix = params.get("suffix") or "_lower"
    exclude_acc = bool(params.get("exclude_accessories", True))
    kw = dict(exclude_accessories=exclude_acc, log=job.log)

    # Band: a named preset (like the desktop tool), unless 'custom', in which case
    # the raw Cut low/high Y + Region fields are used. Presets always graft the
    # 'lower' region (matches the desktop GUI, which hardcodes region for presets).
    cut = (params.get("cut") or "hip_fix").strip()
    if cut and cut != "custom":
        kw["region"] = "lower"
        lo, hi = m.CUT_PRESETS.get(cut, (-m.INF, m.INF))
        kw["cut_low"], kw["cut_high"] = lo, hi
    else:
        kw["region"] = params.get("region") or "lower"
        for k in ("cut_low", "cut_high"):
            raw = params.get(k)
            if raw in (None, ""):
                continue
            try:
                kw[k] = float(str(raw).strip())
            except (TypeError, ValueError):
                raise ValueError(f"{k.replace('_', ' ')} must be a number (e.g. 0.50).")

    # Open skirt cap: overall lift (0 = flat cap = default) + optional rim edge lift
    # (all sides) with per-side overrides. Applies to single and batch.
    cap = as_float(params.get("open_cap"), 0.0)
    if cap:
        kw["open_cap_lift"] = cap
    edge = as_float(params.get("open_cap_edge"), 0.0)
    if edge:
        kw["open_cap_edge"] = edge
    for pk, ak in (("cap_edge_front", "open_cap_edge_front"),
                   ("cap_edge_back", "open_cap_edge_back"),
                   ("cap_edge_left", "open_cap_edge_left"),
                   ("cap_edge_right", "open_cap_edge_right")):
        if params.get(pk) not in (None, ""):
            v = as_float(params.get(pk), None)
            if v is not None:
                kw[ak] = v

    # Texture / output toggles (desktop parity).
    kw["merge_rim"] = bool(params.get("merge_rim", True))
    kw["mipmaps"] = bool(params.get("mipmaps", True))
    if params.get("dry_run"):
        kw["dry_run"] = True

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
                if not params.get("dry_run"):   # dry run writes nothing to match against
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
    if params.get("dry_run"):
        job.progress(1, 1)
        return "dry run — nothing written (see the log for what would be grafted)"
    _match_to_target(job, params, donor, target, out_path)
    job.progress(1, 1)
    return f"lower body swapped -> {out_path}"


# ---------------------------------------------- costume recolour (irochi)
_CN_SUFFIX = re.compile(r"_c\d+$", re.IGNORECASE)          # ..._body_c1 -> ..._body
_CHCO_RE = re.compile(r"ch\d+_co\d+", re.IGNORECASE)       # the costume-pair key


def _classify_bundle(path):
    """Classify a decrypted bundle purely by its CONTENTS — no DB needed:
      ('complete', code)  = has a mesh (the full model with base textures)
      ('variant',  code)  = texture-only bundle carrying _cN recolour textures
      ('other',    code)  = neither
    `code` is the chXXXX_coYYYY pair key (or None), `color` is the _cN tag
    (e.g. 'c1') for a variant. Returns (kind, code, color)."""
    import UnityPy
    env = UnityPy.load(str(path))
    has_mesh = False
    texnames = []
    for obj in env.objects:
        tn = obj.type.name
        if tn in ("Mesh", "SkinnedMeshRenderer"):
            has_mesh = True
        elif tn == "Texture2D":
            texnames.append(getattr(obj.read(), "m_Name", "") or "")
    code = None
    for n in texnames:
        m = _CHCO_RE.search(n)
        if m:
            code = m.group(0).lower()
            break
    color = ""
    for n in texnames:
        m = _CN_SUFFIX.search(n)
        if m:
            color = m.group(0).lstrip("_")     # '_c1' -> 'c1'
            break
    if has_mesh:
        return "complete", code, color
    if color:
        return "variant", code, color
    return "other", code, color


def _recolour_one(job, base_bundle, variant_bundle, out_path):
    """Composite the variant bundle's _cN textures onto the base model, keeping
    each base texture's own format, and write out_path. Returns
    (imported, skipped, errors). Deletes out_path when nothing imported."""
    import tempfile
    import shutil
    import UnityPy
    import texture_importer as ti
    env = UnityPy.load(str(variant_bundle))
    tmp = tempfile.mkdtemp(prefix="irochi_")
    mapping = {}
    try:
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            data = obj.read()
            nm = getattr(data, "m_Name", "") or ""
            base_nm = _CN_SUFFIX.sub("", nm)     # ..._body_c1 -> ..._body
            png = os.path.join(tmp, base_nm + ".png")
            try:
                data.image.save(png)
                mapping[base_nm] = png
            except Exception as exc:             # noqa: BLE001
                job.log(f"  ! could not read variant texture {nm}: {exc}")
        if not mapping:
            return 0, 0, []
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        imported, skipped, errors = ti.process_bundle(
            str(base_bundle), str(out_path), lambda name: mapping.get(name),
            "Keep Original", job.log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if imported == 0:
        try:
            os.remove(out_path)      # process_bundle wrote a plain copy — don't keep it
        except OSError:
            pass
    return imported, skipped, errors


def run_costume_recolour(job, params):
    """Apply a colour-variant (irochi) texture bundle onto its base costume model.

    In SIFAS an alt-colour costume is NOT a separate model: it's a texture-only
    bundle whose textures carry a `_cN` suffix (e.g. chXXXX_coYYYY_body_c1), meant
    to override the shared base model's textures. Extracting the model gives the
    base colour; extracting the variant gives textures with no mesh. This
    composites them into a self-contained recoloured model.

    Single mode: pick the base model + the variant texture bundle.
    Batch mode: point at a FOLDER of decrypted bundles — each texture-only variant
    is auto-paired with its complete model by the chXXXX_coYYYY code INSIDE the
    bundles (no DB / no costume list needed) and composited."""
    from webtools.tools.texture import ensure_astc_cli
    ensure_astc_cli()                        # ASTC decode/encode on-device
    ensure_repo_on_path()
    ensure_tk_stub()                         # texture_importer imports tkinter at top

    out_dir = params.get("out_dir")
    if params.get("mode") == "batch":
        return _recolour_batch(job, params, out_dir)

    base = (params.get("base") or "").strip()
    variant = (params.get("variant") or "").strip()
    if not base or not variant:
        raise ValueError("Pick both the base model bundle and the colour-variant "
                         "(irochi) texture bundle.")
    suffix = params.get("suffix") or "_recolour"
    out_path = single_out_path(out_dir, base, "", suffix)
    job.progress(0, 1)
    job.log(f"recolouring {Path(base).name} with {Path(variant).name} …")
    imported, skipped, errors = _recolour_one(job, base, variant, out_path)
    job.progress(1, 1)
    if imported == 0:
        if errors:
            raise ValueError(
                f"Textures matched but all {len(errors)} import(s) failed "
                f"(first: {errors[0][2]}). Check the texture formats / astcenc.")
        raise ValueError(
            "No textures matched — the variant names didn't line up with the base "
            "model's textures. Are these the same costume (chXXXX_coYYYY)? Base and "
            "variant must be the same suit.")
    return (f"recoloured -> {out_path}  (imported {imported}, "
            f"skipped {skipped}, errors {len(errors)})")


def _recolour_batch(job, params, out_dir):
    """Scan a folder of decrypted bundles, auto-pair each colour-variant
    (texture-only _cN) bundle with its complete model by the chXXXX_coYYYY code
    inside, and composite them all — no DB, no costume list."""
    folder = params.get("in_dir")
    if not folder:
        raise ValueError("Pick a folder of decrypted bundles.")
    bundles = [str(b) for b in find_bundles(folder)]
    if not bundles:
        raise ValueError("No .unity bundles found in that folder.")
    job.log(f"scanning {len(bundles)} bundles …")
    complete = {}      # code -> path of a full model
    variants = []      # (code, color, path)
    for b in bundles:
        try:
            kind, code, color = _classify_bundle(b)
        except Exception as exc:             # noqa: BLE001
            job.log(f"  ! skip {os.path.basename(b)}: {exc}")
            continue
        if kind == "complete" and code:
            complete.setdefault(code, b)
        elif kind == "variant" and code:
            variants.append((code, color, b))
    job.log(f"  found {len(complete)} complete models, {len(variants)} colour variants")
    if not variants:
        return ("no colour-variant (texture-only _cN) bundles found in the folder — "
                "nothing to recolour")
    ok = 0
    for i, (code, color, vpath) in enumerate(variants):
        job.progress(i, len(variants))
        base = complete.get(code)
        if not base:
            job.log(f"  ! {code} {color}: no complete model in the folder — skipped")
            continue
        out_path = single_out_path(out_dir, base, "", "_" + (color or "recolour"))
        imported, _skipped, errors = _recolour_one(job, base, vpath, out_path)
        if imported > 0:
            ok += 1
            job.log(f"  ✓ {code} {color} -> {os.path.basename(out_path)}  (imported {imported})")
        else:
            why = f"{len(errors)} import error(s)" if errors else "no matching textures"
            job.log(f"  ! {code} {color}: {why}")
    job.progress(len(variants), len(variants))
    return f"batch recolour: {ok}/{len(variants)} colour variants composited to {out_dir}"


# ---------------------------------------------- iOS/APK selective pair import
def run_iosapk_import(job, params):
    ensure_tk_stub()
    ensure_repo_on_path()
    import assetbundle_IosApk_batch_import_plus as m

    import_new = bool(params.get("import_new_objects", True))
    # The matcher consumers expect (matcher_fn, pattern) tuples from
    # compile_name_patterns, NOT raw strings — passing strings crashes (unpack
    # error) or silently no-ops. Compile with the tool's own function so the web
    # filters behave exactly like the desktop GUI. digit_agnostic defaults on
    # (GUI default) so ch0001_* patterns match any character id.
    name_mode = params.get("name_mode") or "glob"
    digit_agnostic = bool(params.get("digit_agnostic", True))

    def _compile(raw):
        return m.compile_name_patterns(raw or "", mode=name_mode, digit_agnostic=digit_agnostic)

    name_inc = _compile(params.get("name_include"))
    name_exc = _compile(params.get("name_exclude"))
    # protect the wearer's own script components (swing physics) from being
    # clobbered by a same-path_id donor MonoBehaviour, matching the GUI default.
    script_exc = _compile(params.get("script_exclude") if params.get("script_exclude") is not None
                          else "SwingBone, SwingCollider")
    empty = set()
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        prefix = params.get("prefix") or ""
        suffix = params.get("suffix") or ""
        job.log("pairing donor/target bundles by pathID intersection...")
        job.progress(0, 1)
        m.batch_by_pid(
            Path(params.get("donor_dir")), Path(params.get("target_dir")), Path(out_dir),
            empty, empty, empty, empty, name_inc, name_exc, script_exc,
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
        empty, empty, empty, empty, name_inc, name_exc, script_exc, import_new_objects=import_new)
    job.log(f"OK -> {export.name}  (candidates={candidates}, applied={applied}, "
            f"injected={injected}, skipped={skipped}, failed={len(failed)})")
    job.progress(1, 1)
    return f"applied={applied} injected={injected} -> {export}"
