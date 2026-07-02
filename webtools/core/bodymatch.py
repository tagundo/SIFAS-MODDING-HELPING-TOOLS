"""Match a transplanted costume to the target character.

Two optional post-processing steps for the costume transplant:
  * thigh  — scale the thighs from the donor's body type to the target's, using
             the mesh baker (sifas_mesh_baker.thigh_targets / process_bundle).
  * skin   — recolour the body skin texture from the donor's official skin-tone
             class to the target's, using skin_tone_changer.convert_array.

Character ids are read from the bundles' chNNNN_coNNNN texture names; the thigh
class and skin tone per character come from webtools.core.charinfo.
"""
import os
import re
import sys

from webtools.core.repo import ensure_repo_on_path

# the body skin texture (ch####_co####_body), excluding auxiliary maps
_BODY_RE = re.compile(r"ch\d{4}_co\d{4}_body", re.IGNORECASE)
_AUX_RE = re.compile(
    r"(rim|nrm|normal|mask|msk|emi|emiss|metal|mtl|smooth|gloss|spec|_ao\b|"
    r"occl|sss|thick|alpha|_uv|toon|ramp|shadow|highlight)", re.IGNORECASE)


def is_android():
    """True on the phone app (Chaquopy/Android), False on desktop. Used to pick
    the platform-appropriate default for 'Recolour skin only'."""
    return bool(os.environ.get("ASTCENC_BIN")) or hasattr(sys, "getandroidapilevel")


def detect_char_from_bundle(path):
    """Character id read from a bundle's chNNNN_coNNNN texture names, or None."""
    ensure_repo_on_path()
    try:
        import UnityPy
        import unity_costumemod_packer as pk
    except Exception:
        return None
    try:
        env = UnityPy.load(str(path))
    except Exception:
        return None
    for obj in env.objects:
        if getattr(obj.type, "name", "") != "Texture2D":
            continue
        try:
            name = getattr(obj.read(), "m_Name", "") or ""
        except Exception:
            continue
        cid = pk.extract_chara_id_from_texture_name(name)
        if cid:
            return int(cid)
    return None


def apply_thigh_match(in_path, out_path, src_class, dst_class, log=print):
    """Scale thighs from src_class -> dst_class on the bundle (mesh baker). Returns
    True when it wrote out_path, False when it was a no-op (classes equal)."""
    if not src_class or not dst_class or src_class == dst_class:
        log(f"[thigh] already {src_class or '?'}; skipped")
        return False
    ensure_repo_on_path()
    import sifas_mesh_baker as mb
    targets = mb.thigh_targets(src_class, dst_class, compensate=True)
    mb.process_bundle(str(in_path), str(out_path), targets,
                      recompute_normals=True, hierarchical=True, packer="lz4", log=log)
    log(f"[thigh] matched {src_class} -> {dst_class}")
    return True


# Bones that carry COSTUME geometry (flowy / dynamic parts) rather than the body.
# A mesh triangle weighted to one of these is clothing, not skin — even when it is
# skin-coloured (a cream skirt). Breast* is the bust (skin), so it is excluded here.
_COSTUME_BONE_RE = re.compile(
    r"Skirt|Ribbon|Sleeve|Sailor|Button|Cape|Tail|Wing|Frill|Muffler|Scarf|"
    r"Necktie|Tie|Sode|Acce|Collar|Apron|Hood|Bow|Belt|Pocket|Lace", re.IGNORECASE)


def build_skin_uv_mask(env, width, height, log=print):
    """Rasterise a skin-region mask (H×W bool) from the body mesh: texels covered by
    triangles weighted to BODY bones, minus those weighted to dynamic COSTUME bones
    (skirt / sleeve / ribbon / accessory). This separates skin from skin-coloured
    clothing far better than pixel colour, and — unlike a colour mask — never drops
    real skin. Returns None when the mesh can't be decoded (caller falls back to the
    colour mask). Torso-tight clothing on body bones (a bodice) can't be told from
    chest skin by any signal, so it is not excluded here."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
        from UnityPy.export.MeshExporter import MeshHandler
    except Exception as exc:
        log(f"[skin] UV mask deps missing ({exc}); using colour mask")
        return None
    try:
        obj = {o.path_id: o for o in env.objects}
        goname = {p: o.read_typetree().get("m_Name")
                  for p, o in obj.items() if o.type.name == "GameObject"}
        # body SMR = the skinned renderer with the most bones
        smr, best = None, -1
        for o in env.objects:
            if o.type.name != "SkinnedMeshRenderer":
                continue
            tt = o.read_typetree()
            if len(tt.get("m_Bones", [])) > best:
                smr, best = tt, len(tt.get("m_Bones", []))
        if not smr or best <= 0:
            return None

        def bone_name(bp):
            bo = obj.get(bp)
            return goname.get(bo.read_typetree().get("m_GameObject", {}).get("m_PathID")) if bo else None

        bnames = [bone_name(b["m_PathID"]) for b in smr["m_Bones"]]
        cost_idx = {i for i, nm in enumerate(bnames)
                    if nm and "Breast" not in nm and _COSTUME_BONE_RE.search(nm)}
        if not cost_idx:
            return None   # nothing costume-boned to exclude; colour mask is no worse
        mo = obj.get(smr["m_Mesh"]["m_PathID"])
        if not mo:
            return None
        h = MeshHandler(mo.read())
        h.process()
        uv = np.asarray(h.m_UV0).reshape(-1, 2)
        bi = np.asarray(h.m_BoneIndices).reshape(-1, 4)
        bw = np.asarray(h.m_BoneWeights).reshape(-1, 4)
        tris = np.asarray(h.get_triangles()).reshape(-1, 3)
        dom = bi[np.arange(len(bi)), bw.argmax(1)]
        vcost = np.isin(dom, list(cost_idx))

        skin_im = Image.new("L", (width, height), 0)
        cost_im = Image.new("L", (width, height), 0)
        ds, dc = ImageDraw.Draw(skin_im), ImageDraw.Draw(cost_im)

        def px(i):
            u, v = uv[i]
            return (u * width, (1.0 - v) * height)   # V is flipped in texture space

        for a, b, c in tris:
            poly = [px(a), px(b), px(c)]
            (dc if (vcost[a] or vcost[b] or vcost[c]) else ds).polygon(poly, fill=255)
        skin_m = (np.asarray(skin_im) > 0) & ~(np.asarray(cost_im) > 0)
        # grow a few px so the UV-seam border between skin and cloth still recolours
        grown = Image.fromarray((skin_m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(5))
        mask = np.asarray(grown) > 0
        log(f"[skin] UV/bone skin mask built ({100 * mask.mean():.0f}% of atlas; "
            f"{len(cost_idx)} costume bones excluded)")
        return mask
    except Exception as exc:
        log(f"[skin] UV mask unavailable ({exc}); using colour mask")
        return None


def apply_skin_match(in_path, out_path, src_tone, dst_tone, skin_only=True,
                     strength=1.0, src_override=None, colour_guard=False, log=print):
    """Recolour the body skin texture to dst_tone (skin tone changer).

    Source-tone precedence: src_override (the user's explicit choice) >
    src_tone (the donor character's official roster tone) > pixel detection.
    The official classes differ by only a few /255 — inside costume-to-costume
    variation — so close pairs (bright vs default) cannot be told apart
    reliably from pixels alone; detection is a fallback for when the donor
    character is unknown, never an override. Returns True when it wrote
    out_path, False on a no-op (already dst_tone / no body texture /
    unavailable)."""
    if not dst_tone:
        log("[skin] target tone unknown; skipped")
        return False
    ensure_repo_on_path()
    try:
        import UnityPy
        import numpy as np
        from PIL import Image
        import skin_tone_changer as stc
    except Exception as exc:
        log(f"[skin] unavailable ({exc}); skipped")
        return False
    # ASTC decode goes through the bundled CLI on the phone so SIFAS's compressed
    # textures can be read. Re-ENCODING through that same CLI has proven unreliable
    # on-device (it silently fails to persist the pixels — the bundle keeps the
    # original ASTC bytes), so when the native ASTC encoder is absent we write the
    # recoloured skin as uncompressed RGBA32: no codec, guaranteed to land, and the
    # game loads it fine. On desktop (native encoder present) the original
    # compressed format is kept, so output stays small there.
    try:
        from webtools.tools.texture import ensure_astc_cli
        ensure_astc_cli()
    except Exception:
        pass
    from UnityPy.export import Texture2DConverter as _T
    native_astc = getattr(_T, "astc_encoder", None) is not None
    force_rgba32 = None
    if not native_astc:
        try:
            from UnityPy.enums import TextureFormat
            force_rgba32 = TextureFormat.RGBA32
        except Exception:
            force_rgba32 = None

    env = UnityPy.load(str(in_path))
    # Prefer a UV/bone-derived skin region (excludes skirt/sleeve/ribbon/accessory
    # geometry even when it is skin-coloured) over the pixel-colour detector. Built
    # lazily per texture size and cached (body textures share the mesh UV). None ->
    # fall back to the colour mask. Only built when restricting to skin (skin_only).
    _uv_cache = {}

    def _uv_mask_for(w, h):
        if not skin_only:
            return None
        if (w, h) not in _uv_cache:
            _uv_cache[(w, h)] = build_skin_uv_mask(env, w, h, log)
        return _uv_cache[(w, h)]

    changed = 0
    originals = {}   # pathID -> (rgb, alpha, intended_shift) for post-save verify
    for obj in env.objects:
        if getattr(obj.type, "name", "") != "Texture2D":
            continue
        data = obj.read()
        name = getattr(data, "m_Name", "") or ""
        if not _BODY_RE.search(name) or _AUX_RE.search(name):
            continue
        try:
            pil = data.image
            if pil is None:
                continue
            arr = np.asarray(pil.convert("RGBA")).astype(np.float64)
            rgb, alpha = arr[..., :3], arr[..., 3]
            detected = stc.detect_tone(rgb, alpha)
            tone = src_override or src_tone or detected
            if not tone:
                log(f"[skin] {name}: source tone unknown; skipped")
                continue
            if detected and detected != tone:
                log(f"[skin] {name}: note - pixels look closer to {detected}, "
                    f"using {tone}; set 'Donor skin tone' if the donor was "
                    "already recoloured")
            if tone == dst_tone:
                log(f"[skin] {name}: already {dst_tone}; nothing to recolour "
                    "(official tone classes only differ subtly)")
                continue
            uv = _uv_mask_for(rgb.shape[1], rgb.shape[0])
            if uv is not None:
                region = uv.astype(np.float64)
                if colour_guard:
                    # also require skin colour: removes non-skin-coloured body-bone
                    # clothing (a blue bodice) but may drop deeply shadowed skin.
                    region = region * stc._skin_mask(rgb, alpha).astype(np.float64)
                out = stc.convert_array(rgb, tone, dst_tone, mask=region, strength=strength)
            else:
                out = stc.convert_array(rgb, tone, dst_tone,
                                        skin_only=skin_only, strength=strength)
            u8 = np.clip(out, 0, 255).astype(np.uint8)
            newpil = Image.fromarray(np.dstack([u8, alpha.astype(np.uint8)]), "RGBA")
            if force_rgba32 is not None:
                # uncompressed write, no astcenc CLI in the path
                data.set_image(newpil, target_format=force_rgba32)
            else:
                data.image = newpil
            data.save()
            changed += 1
            m = stc._skin_mask(rgb, alpha)
            intended = float(np.abs(out - rgb)[m].mean()) if m.any() else 0.0
            originals[obj.path_id] = (rgb, alpha, intended, tone)
            log(f"[skin] recolouring {name}: {tone} -> {dst_tone} "
                f"(target shift {intended:.1f}/255"
                f"{', as RGBA32' if force_rgba32 is not None else ''})")
        except Exception as exc:
            log(f"[skin] recolour failed on {name}: {exc}")
    if not changed:
        log("[skin] no body texture recoloured; output left as-is")
        return False
    with open(str(out_path), "wb") as f:
        f.write(env.file.save(packer="lz4"))
    # Verify the change actually persisted so the log can never again claim a
    # recolour that did not land: reload and measure the REAL skin shift against
    # the pre-edit pixels. If it did not stick, say so and fail (the caller then
    # keeps the un-recoloured transplant rather than a silently-unchanged file).
    landed = 0
    try:
        v = UnityPy.load(str(out_path))
        for obj in v.objects:
            if getattr(obj.type, "name", "") != "Texture2D":
                continue
            if obj.path_id not in originals:
                continue
            rgb0, alpha0, intended, tone = originals[obj.path_id]
            a = np.asarray(obj.read().image.convert("RGBA")).astype(np.float64)[..., :3]
            m = stc._skin_mask(rgb0, alpha0)
            actual = float(np.abs(a - rgb0)[m].mean()) if m.any() else 0.0
            nm = getattr(obj.read(), "m_Name", "") or "body"
            if intended >= 1.0 and actual < 0.5:
                log(f"[skin] WARNING {nm}: recolour did NOT persist "
                    f"(actual shift {actual:.1f}/255 vs target {intended:.1f}); "
                    "the texture was left unchanged on disk")
            else:
                landed += 1
                log(f"[skin] verified {nm}: actual skin shift {actual:.1f}/255")
    except Exception as exc:
        log(f"[skin] could not verify output ({exc}); assuming written")
        return True
    return landed > 0
