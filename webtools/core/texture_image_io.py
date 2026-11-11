"""Bounded PNG file I/O for the shared editor and native app file pickers."""
import base64
import os
from pathlib import Path
import re
import secrets

from . import viewer_texture_tools


def open_png(path):
    source = Path(path)
    if source.suffix.lower() != ".png" or not source.is_file():
        raise ValueError("Choose a PNG image file.")
    with source.open("rb") as stream:
        raw = stream.read(viewer_texture_tools.MAX_PNG_BYTES + 1)
    if not 0 < len(raw) <= viewer_texture_tools.MAX_PNG_BYTES:
        raise ValueError("Choose a PNG image within the 8 MiB texture limit.")
    return viewer_texture_tools.decode_image("data:image/png;base64," + base64.b64encode(raw).decode("ascii"))


def save_png(png, name, output_root):
    # Validate full decoding and dimensions before creating any output. Retain
    # the exact PNG bytes, including RGB hidden by zero/partial alpha.
    viewer_texture_tools.decode_image(png)
    if not isinstance(name, str) or not 0 < len(name) <= 1024:
        raise ValueError("Choose a PNG file name.")
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(". ")
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    stem = stem.encode("utf-8")[:180].decode("utf-8", errors="ignore").strip(". ") or "texture"
    directory = Path(output_root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (stem + "-" + secrets.token_hex(8) + ".png")
    raw = base64.b64decode(png.split(",", 1)[1], validate=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"path": str(target), "name": target.name}
