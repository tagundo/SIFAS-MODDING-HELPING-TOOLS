# CLAUDE.md — working notes for Claude Code in this repo

SIFAS costume / mesh / texture modding helper scripts (Python + Pillow + UnityPy).
**Read this before touching any texture, atlas, or UV code.**

## Texture & atlas handling — NEVER distort the source

These scripts move / copy / combine game textures. The output must preserve the
source pixels **exactly** wherever the resolution allows.

> **Do NOT resample, squish, shift, pad, dilate, or blur a texture to prevent
> "bleeding" / "seam bleed" / mipmap cross-talk unless the user explicitly asks
> for it.**

That anti-bleed instinct has repeatedly made things WORSE in this repo: it
distorts every pixel to avoid a marginal, usually-imaginary seam artifact. The
maintainer has rejected it multiple times. When combining two images, the job is
literally *place them side by side* — nothing more.

### Concrete rules

- **Side-by-side atlas** (e.g. `lower_body_swap.py` `combine()`): each image goes
  in an EXACT half — target owns UV `[0, 0.5]`, donor owns `[0.5, 1]`. No gutter,
  no `(0.5 - g)` horizontal squish, no centre-band edge-column dilation. The UV
  remap is `uL(u) = u*0.5`, `uR(u) = 0.5 + u*0.5`. The `*0.5` is only the
  normalized-UV ↔ double-width conversion (`uR(u)*2048 == 1024 + u*1024`); it is
  **not** a gutter — do not "fix" it.
- **UV-region patch** (e.g. `costume_part_transplant.py` `_patch_uv_region`): crop
  the donor at the EXACT UV region (no ±px bleed margin) and paste at the same
  region on the target. Resize ONLY when donor/target atlas resolutions genuinely
  differ.
- **Resize a source ONLY** to match a genuinely different target size, and skip it
  when the size already matches:
  `img if img.size == (w, h) else img.resize((w, h))`.
- Every SIFAS texture is power-of-two; keep atlas dims pow2, but never use that as
  an excuse to downscale a source that already fits.

If you believe an anti-bleed / gutter / padding step is genuinely required, STOP
and ask the maintainer first — do not add it silently.
