"""Adapter for texture_batch_importer.py.

That tool imports tkinter and PIL at module top level, so it is NOT import-safe
on a headless/Termux server. Its texture-import core is tiny and self-contained,
so we reproduce it verbatim here (with lazy UnityPy/PIL imports). This is the one
tool whose logic is copied rather than imported - the byte-match verification
covers it.
"""
import os

SUPPORTED_IMG_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".tga"]
SUPPORTED_BUNDLE_EXTS = [".bundle", ".unity3d", ".ab", ".assets", ""]

# Common Texture2D formats offered in the UI ("Keep Original" leaves it untouched).
TEXTURE_FORMATS = [
    "Keep Original", "RGBA32", "RGB24", "ARGB32", "RGB565",
    "DXT1", "DXT5", "BC4", "BC5", "BC7",
    "ETC_RGB4", "ETC2_RGBA8", "ASTC_4x4", "ASTC_6x6", "ASTC_8x8",
]


def find_image_by_name(img_root, name):
    for ext in SUPPORTED_IMG_EXTS:
        p = os.path.join(img_root, name + ext)
        if os.path.exists(p):
            return p
    return None


def _safe_make_dir(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)


def process_single_bundle(bundle_path, img_folder, out_path, selected_format_name, status_cb=None):
    """Verbatim port of texture_batch_importer.process_single_bundle."""
    import UnityPy
    from UnityPy.enums import TextureFormat
    from PIL import Image

    env = UnityPy.load(bundle_path)
    imported_count = 0

    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            tex_name = data.m_Name
            img_path = find_image_by_name(img_folder, tex_name)
            if img_path:
                pil = Image.open(img_path)
                if selected_format_name and selected_format_name != "Keep Original":
                    fmt = getattr(TextureFormat, selected_format_name, None)
                    if fmt is not None:
                        data.m_TextureFormat = fmt
                data.image = pil
                data.save()
                imported_count += 1
                if status_cb:
                    status_cb(f"Importing {os.path.basename(bundle_path)} :: {tex_name}")

    _safe_make_dir(out_path)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))
    return imported_count


def iter_bundle_files(input_root, recursive):
    """Verbatim port of texture_batch_importer.iter_bundle_files."""
    if os.path.isfile(input_root):
        yield input_root
        return
    if recursive:
        for root, _, files in os.walk(input_root):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS or ext == "":
                    yield os.path.join(root, fn)
    else:
        for fn in os.listdir(input_root):
            fp = os.path.join(input_root, fn)
            if os.path.isfile(fp):
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS or ext == "":
                    yield fp


def run_texture(job, params):
    from pathlib import Path
    from webtools.tools.common import batch_out_path, single_out_path

    img_folder = params.get("img_folder")
    fmt = params.get("format") or "Keep Original"
    prefix = params.get("prefix") or ""
    suffix = params.get("suffix") or ""
    out_dir = params.get("out_dir")

    if not img_folder:
        raise ValueError("Image folder is required for texture import")

    if params.get("mode") == "batch":
        in_dir = params.get("in_dir")
        recursive = bool(params.get("recursive", True))
        files = list(iter_bundle_files(in_dir, recursive))
        total = len(files)
        ok = fail = 0
        imported_total = 0
        for i, src in enumerate(files, 1):
            if job.should_stop():
                job.log("[stopped]")
                break
            out_path = str(batch_out_path(in_dir, src, out_dir, prefix, suffix))
            try:
                cnt = process_single_bundle(src, img_folder, out_path, fmt, job.log)
                imported_total += cnt
                ok += 1
                job.log(f"OK   {os.path.basename(src)} -> {os.path.basename(out_path)} (imported {cnt})")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                job.log(f"FAIL {os.path.basename(src)}: {exc}")
            job.progress(i, total)
        job.log(f"Done. bundles={total}  ok={ok}  fail={fail}  textures={imported_total}")
        return f"batch done: bundles={total} ok={ok} fail={fail} textures={imported_total}"

    in_file = params.get("in_path")
    out_path = str(single_out_path(out_dir, in_file, prefix, suffix))
    job.progress(0, 1)
    cnt = process_single_bundle(in_file, img_folder, out_path, fmt, job.log)
    job.log(f"OK {os.path.basename(in_file)} -> {os.path.basename(out_path)} (imported {cnt})")
    job.progress(1, 1)
    return f"imported {cnt} textures -> {out_path}"
