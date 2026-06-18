"""Thumbnail generation by reusing unity_costumemod_packer.py's SIGILL-isolated
texture decode worker as a subprocess.

The native texture codecs (texture2ddecoder / astc-encoder / etcpak) can crash
with SIGILL on some Termux/ARM builds. The packer already ships a throwaway-child
decode worker exactly for this reason; we shell out to it so a codec crash kills
only the child and we fall back to "no thumbnail" instead of taking down the
server.
"""
import os
import subprocess
import sys
import tempfile

from .repo import repo_root

# (path, mtime) -> PNG bytes; b"" marks a known-failed decode so we don't retry.
_CACHE: dict = {}


def _packer_path():
    p = repo_root() / "unity_costumemod_packer.py"
    return str(p) if p.exists() else None


def thumbnail(bundle_path, timeout: int = 180):
    """Return PNG bytes for the body texture in `bundle_path`, or None on any
    failure (missing file, no packer, codec crash, timeout)."""
    try:
        bundle_path = os.path.realpath(os.path.expanduser(str(bundle_path)))
    except Exception:
        return None
    if not os.path.isfile(bundle_path):
        return None
    try:
        mtime = os.path.getmtime(bundle_path)
    except OSError:
        return None

    key = (bundle_path, mtime)
    if key in _CACHE:
        return _CACHE[key] or None

    packer = _packer_path()
    if not packer:
        _CACHE[key] = b""
        return None

    fd, out_png = tempfile.mkstemp(prefix="webtools_thumb_", suffix=".png")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, packer, "--decode-worker", bundle_path, out_png],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        if proc.returncode == 0 and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
            with open(out_png, "rb") as f:
                data = f.read()
            _CACHE[key] = data
            return data
        _CACHE[key] = b""
        return None
    except Exception:
        _CACHE[key] = b""
        return None
    finally:
        try:
            os.remove(out_png)
        except OSError:
            pass
