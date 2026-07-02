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


def apply_skin_match(in_path, out_path, src_tone, dst_tone, skin_only=True,
                     strength=1.0, src_override=None, log=print):
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
