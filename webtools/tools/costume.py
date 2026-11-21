"""Adapters for unity_costumemod_packer, costume_transplant,
assetbundle_IosApk_batch_import_plus.

packer and transplant are import-safe (lazy Tk). The IosApk importer `import`s
tkinter at top, so the headless stub is installed first.
"""
import os
import re
from pathlib import Path

from webtools.core.repo import ensure_repo_on_path
from webtools.core.sukusta import find_bundles, default_sukusta_dir
from webtools.core.tkstub import ensure_tk_stub
from webtools.tools.common import as_float, batch_out_path, parse_multi_paths, single_out_path


# ---- dynamic dropdown provider: donor -> candidate part-root bones ----------
def part_root_options(params):
    """All donor skin bones, retaining their actual subtree relationships."""
    donor = (params.get("donor") or "").strip()
    if not donor:
        return []
    ensure_repo_on_path()
    import costume_part_transplant as cpt
    return cpt.part_hierarchy(donor, renderer=params.get("donor_renderer") or None)


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
    from webtools.core import viewer_thumbnails
    thumbnail_provider = viewer_thumbnails.packer_provider(params)

    mode = params.get("mode", "single")
    if mode == "batch":
        files = [str(p) for p in find_bundles(params.get("in_dir"))]
    elif mode == "multi":
        files = parse_multi_paths(params)
        if len(files) > 128:
            raise ValueError("Choose at most 128 costume files in one selection.")
    elif mode == "single":
        files = [params.get("in_path")]
    else:
        raise ValueError("Choose single, selected files or batch costume packing.")
    files = list(dict.fromkeys(os.path.realpath(os.path.expanduser(str(path)))
                               for path in files if path))
    if not files or any(not os.path.isfile(path) for path in files):
        raise ValueError("Choose existing costume bundle files.")
    if len(files) > 512:
        raise ValueError("Choose at most 512 costume files in one batch.")
    from webtools.core.costume_pack_sources import source_bindings
    bindings = source_bindings(files, repo_root=Path.cwd())
    job.log(f"packing {len(files)} selected bundle(s), keeping costume companions together...")
    job.progress(0, 1)
    success, fail = m.run_pack_jobs(
        files, out_dir, auto_chara_id=auto_chara_id, manual_chara_id=manual_chara_id,
        thumbnail_size=thumbnail_size, combine_pairs=bool(params.get("combine_pairs", True)),
        ask_chara_id=None, log=job.log, thumbnail_provider=thumbnail_provider,
        source_bindings=bindings)
    job.progress(1, 1)
    if fail:
        raise RuntimeError(f"Costume packing failed for {fail} costume(s); see the log above.")
    return f"packed: success={success} fail={fail}"


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
        physics_provenance=params.get("_physics_provenance"),
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
    uv_placement = params.get("uv_placement")
    if "uv_placement" in params and (not isinstance(uv_placement, str) or
                                     uv_placement not in ("same_position", "move_to_empty", "atlas")):
        raise ValueError("Choose same_position, move_to_empty or atlas for UV placement.")
    reuse_empty_uv = params.get("reuse_empty_uv", True)
    relocate_empty_uv = params.get("relocate_empty_uv", False)
    upscale_textures_for_uv_reuse = params.get("upscale_textures_for_uv_reuse", True)
    if any(type(value) is not bool for value in
           (reuse_empty_uv, relocate_empty_uv, upscale_textures_for_uv_reuse)):
        raise ValueError("Empty UV options must be true or false.")
    if uv_placement is None and relocate_empty_uv and not reuse_empty_uv:
        raise ValueError("Enable empty UV reuse before moving to another empty UV area.")
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
    part_bones = params.get("part_bones")
    triangle_indices = params.get("triangle_indices")

    # Game body combination consumes only the original shared material/submesh.
    # Standalone CLI modes remain available outside game-facing app workflows.
    new_submesh = "atlas"
    job.progress(0, 1)
    job.log(f"transplanting part from {Path(donor).name} onto {Path(target).name} …")
    m.transplant_part(
        str(donor), str(target), str(out_path),
        part_root=part_root, part_bones=part_bones,
        auto=part_root is None and part_bones is None and triangle_indices is None,
        triangle_indices=triangle_indices,
        donor_renderer=params.get("donor_renderer") or None,
        target_renderer=params.get("target_renderer") or None,
        preserve_physics=bool(params.get("preserve_physics", True)),
        restore_collision=bool(params.get("restore_collision", True)),
        new_submesh=new_submesh,
        reuse_empty_uv=reuse_empty_uv,
        relocate_empty_uv=relocate_empty_uv,
        upscale_textures_for_uv_reuse=upscale_textures_for_uv_reuse,
        uv_placement=uv_placement,
        patch_texture=bool(params.get("patch_texture", False)),
        worldspace=bool(params.get("worldspace", True)),
        fix_nodescaling=bool(params.get("fix_nodescaling", True)), verbose=False,
        physics_provenance=params.get("_physics_provenance"),
        log_callback=job.log,
    )
    _match_to_target(job, params, donor, target, out_path)
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
    kw = dict(exclude_accessories=exclude_acc, log=job.log,
              selection_scope=params.get("selection_scope", "skin"),
              donor_renderer=params.get("donor_renderer"), target_renderer=params.get("target_renderer"),
              physics_provenance=params.get("_physics_provenance"), uv_placement=params.get("uv_placement"))

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

    out_dir = params.get("out_dir") or default_sukusta_dir("modded")
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
        try:
            imported, _skipped, errors = _recolour_one(job, base, vpath, out_path)
        except Exception as exc:  # noqa: BLE001 - one bad bundle must not kill the batch
            job.log(f"  ! {code} {color}: failed ({exc}) — skipped")
            continue
        if imported > 0:
            ok += 1
            job.log(f"  ✓ {code} {color} -> {os.path.basename(out_path)}  (imported {imported})")
        else:
            why = f"{len(errors)} import error(s)" if errors else "no matching textures"
            job.log(f"  ! {code} {color}: {why}")
    job.progress(len(variants), len(variants))
    return f"batch recolour: {ok}/{len(variants)} colour variants composited to {out_dir}"


# ---------------------------------------------- iOS / Android costume conversion
def run_iosapk_import(job, params):
    ensure_tk_stub()
    ensure_repo_on_path()
    import assetbundle_IosApk_batch_import_plus as converter
    from webtools.core import costume_platform_source

    direction = params.get("direction")
    if not isinstance(direction, str) or direction not in costume_platform_source.DIRECTIONS:
        raise ValueError("Choose the costume conversion direction.")
    source_platform, platform = costume_platform_source.DIRECTIONS[direction]
    physics_source = params.get("physics_source", "target")
    if physics_source not in ("target", "donor"):
        raise ValueError("Choose which costume's existing swing physics to use.")
    physics = "source" if physics_source == "donor" else "target"
    base_mode = params.get("base_mode", "library")
    if base_mode not in ("library", "manual"):
        raise ValueError("Choose where to find the original costume for the output platform.")
    download = params.get("download_missing", False)
    if not isinstance(download, bool):
        raise ValueError("Choose whether to download the missing costume pack.")
    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir:
        raise ValueError("Choose the converted costume output folder.")
    out_dir = Path(out_dir).expanduser()
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ("_iOS" if platform == "ios" else "_APK")
    if any(not isinstance(part, str) or any(char in part for char in ("/", "\\", "\x00")) for part in (prefix, suffix)):
        raise ValueError("Use a filename prefix and suffix without directory separators.")

    def library_target(source):
        from webtools.core.game_models import ImportCancelled
        from webtools.core.viewer_cache import game_models_dir
        root = Path.cwd()
        models = game_models_dir()
        selection = {"path": str(source), "direction": direction, "region": params.get("region") or "gl"}
        if params.get("packs_dir"):
            selection["packs_dir"] = params["packs_dir"]
        language = params.get("language")
        if language not in ("en", "ko", "ja"):
            language = "ja" if selection["region"] == "jp" else "en"
        resolved = costume_platform_source.resolve(root, selection, language=language, cache_root=models)
        if resolved["status"] != "matched":
            raise ValueError(resolved["message"])
        if download and mode == "single":
            expected = {key: resolved["selection"][key] for key in ("region", "suit", "variant", "platform")}
            if params.get("match_selection") != expected:
                raise ValueError("Check the original costume again before downloading its missing packs.")
        cache = models / "transplant-bodies"
        try:
            target = costume_platform_source.prepare_target(job, repo_root=root, resolved=resolved,
                output_root=cache, download=download)
            original = costume_platform_source.prepare_source_original(job, repo_root=root, resolved=resolved,
                output_root=cache)
        except ImportCancelled:
            return None, None, None
        return target, original, resolved.get("donor_sha256")

    def convert(source, target, original, source_sha256, output):
        if job.should_stop():
            return False
        with costume_platform_source.converter_input(source, source_platform, expected_sha256=source_sha256) as (body, digest):
            result = converter.convert_costume_bundle(body, target, output, platform=platform, physics=physics,
                source_original_bundle=original, source_expected_sha256=digest)
        job.add_output(str(output))
        job.log(f"{source.name} → {output.name}: {result['copied']} updated objects, "
                f"{result['added']} new objects, {result['textures_retained']} native textures retained, "
                f"{result['textures_rgba32']} textures converted to RGBA32.")
        return True

    mode = params.get("mode", "single")
    if mode == "single":
        if not params.get("donor"):
            raise ValueError("Choose a modified costume bundle.")
        source = Path(params["donor"]).expanduser()
        if base_mode == "manual" and not params.get("target"):
            raise ValueError("Choose the same original costume for the output platform.")
        job.progress(0, 1)
        target, original, digest = library_target(source) if base_mode == "library" else (Path(params["target"]).expanduser(), None, None)
        output_source = source.with_suffix(".unity") if source.suffix.lower() == ".zip" else source
        output = single_out_path(out_dir, output_source, "", suffix)
        if not convert(source, target, original, digest, output):
            return "Costume conversion cancelled."
        job.progress(1, 1)
        return f"Converted costume → {output.name}"

    if mode != "batch" or not params.get("donor_dir"):
        raise ValueError("Choose a folder of modified costume bundles.")
    from webtools.core.viewer_cache import iter_source_files
    from webtools.core.sukusta import is_unity_bundle

    def chosen_bundles(folder):
        candidates = []
        for path in iter_source_files(folder):
            if job.should_stop():
                return []
            if path.is_symlink() or not is_unity_bundle(path):
                continue
            candidates.append(path)
            if len(candidates) > 512:
                raise ValueError("Choose a folder containing at most 512 costume bundles.")
        return sorted(candidates)

    sources = chosen_bundles(params["donor_dir"])
    if not sources:
        raise ValueError("No costume bundles were found in the selected folder.")

    def manual_targets():
        if not params.get("target_dir"):
            raise ValueError("Choose the folder containing original costumes for the output platform.")
        target_dir = Path(params["target_dir"]).expanduser()
        import UnityPy
        target_platform = 9 if platform == "ios" else 13
        index = {}
        for path in chosen_bundles(target_dir):
            try:
                env = UnityPy.load(str(path))
                if {int(asset.target_platform) for asset in env.assets} == {target_platform}:
                    index[str(path.relative_to(target_dir))] = {"ids": {obj.path_id for obj in env.objects}}
            except (OSError, ValueError, RuntimeError):
                continue
        if not index:
            raise ValueError("The selected folder has no original costume bundles for the output platform.")

        def locate(source):
            match, details = converter.pair_by_pid_intersection(source, target_dir, index)
            if match is None:
                message = "More than one original costume matches." if details.get("error") == "AMBIGUOUS" else "No matching original costume was found."
                raise ValueError(message + " Convert this costume separately to choose its original.")
            return match, None, None

        return locate

    locate = library_target if base_mode == "library" else manual_targets()
    converted = failed = 0
    job.progress(0, len(sources))
    for position, source in enumerate(sources, 1):
        if job.should_stop():
            break
        try:
            output = batch_out_path(params["donor_dir"], source, out_dir, prefix, suffix)
            target, original, digest = locate(source)
            converted += convert(source, target, original, digest, output)
        except (OSError, RuntimeError, ValueError) as error:
            failed += 1
            job.log(f"{source.name}: {error}")
        job.progress(position, len(sources))
    if failed:
        raise ValueError(f"{failed} costume(s) could not be converted. Check the details for each costume.")
    return f"Converted {converted} costume(s)."
