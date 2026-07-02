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
    # On the phone, wire ASTC decode/encode through the bundled CLI so SIFAS's
    # compressed textures round-trip. No-op on desktop / when unavailable.
    try:
        from webtools.tools.texture import ensure_astc_cli
        ensure_astc_cli()
    except Exception:
        pass

    env = UnityPy.load(str(in_path))
    changed = 0
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
            data.image = Image.fromarray(
                np.dstack([u8, alpha.astype(np.uint8)]), "RGBA")
            data.save()
            changed += 1
            # quantify the applied change so "nothing happened" is answerable
            # from the log: SIFAS's official tone classes only differ by a few
            # /255 on the skin, so a correct match is often nearly invisible.
            m = stc._skin_mask(rgb, alpha)
            shift = float(np.abs(out - rgb)[m].mean()) if m.any() else 0.0
            note = (" - official tones differ subtly, a small shift is correct"
                    if shift < 8 else "")
            log(f"[skin] recoloured {name}: {tone} -> {dst_tone} "
                f"(mean skin shift {shift:.1f}/255{note})")
        except Exception as exc:
            log(f"[skin] recolour failed on {name}: {exc}")
    if not changed:
        log("[skin] no body texture recoloured; output left as-is")
        return False
    with open(str(out_path), "wb") as f:
        f.write(env.file.save(packer="lz4"))
    return True
