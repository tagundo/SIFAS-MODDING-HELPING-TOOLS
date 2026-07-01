"""Adapter for skin_tone_changer.py.

Recolours a SIFAS body/hand texture from one official skin-tone class to another
by a per-channel linear map. It works on IMAGE files (PNG/JPG/…), not bundles, so
export the texture first (or use any texture PNG you have). tkinter is lazy and no
UnityPy is involved, so this is import-safe on-device.
"""
from webtools.core.repo import ensure_repo_on_path
from webtools.tools.common import as_float, single_out_path

TONES = ["bright", "default", "slight", "medium_tone"]
SRC_TONES = ["auto"] + TONES


def _module():
    ensure_repo_on_path()
    import skin_tone_changer as m
    return m


def run_skintone(job, params):
    m = _module()
    src = params.get("src") or "auto"
    dst = params.get("dst") or "default"
    skin_only = bool(params.get("skin_only"))
    strength = as_float(params.get("strength"), 1.0)
    suffix = params.get("suffix") or "_tone"
    out_dir = params.get("out_dir")

    if params.get("mode") == "batch":
        ok, fail, total = m.run_batch(
            params.get("in_dir"), out_dir, src, dst, suffix,
            skin_only=skin_only, strength=strength, recursive=True,
            log=job.log, should_stop=job.should_stop)
        return f"batch done: total={total} ok={ok} fail={fail}"

    in_file = params.get("in_path")
    out_path = single_out_path(out_dir, in_file, "", suffix)
    job.progress(0, 1)
    used = m.convert_file(in_file, str(out_path), src, dst,
                          skin_only=skin_only, strength=strength, log=job.log)
    job.progress(1, 1)
    return f"{used} -> {dst} : {out_path}"
