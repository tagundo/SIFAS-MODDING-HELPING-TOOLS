"""Sukusta library path + bundle helpers.

These mirror the identical helpers in the tool scripts (e.g.
sifas_breast_tuner.default_sukusta_dir / is_unity_bundle) so the web layer has a
single canonical copy and never has to import a tool module just to resolve a
path. Behaviour is intentionally kept byte-for-byte compatible with the tools.
"""
import os


def is_termux() -> bool:
    """Best-effort guess at whether we're running inside Termux."""
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def default_sukusta_dir(name: str) -> str:
    """Default path for sukusta/<name> ('extracted' or 'modded').
    Override the base with the SUKUSTA_DIR env var. Termux uses shared Downloads."""
    base = os.environ.get("SUKUSTA_DIR")
    if base:
        return os.path.join(os.path.expanduser(base), name)
    if is_termux():
        return os.path.expanduser(f"~/storage/downloads/sukusta/{name}")
    return os.path.expanduser(f"~/sukusta/{name}")


def is_unity_bundle(path) -> bool:
    """True if the file starts with the UnityFS magic (i.e. an asset bundle)."""
    try:
        with open(path, "rb") as f:
            return f.read(7) == b"UnityFS"
    except Exception:
        return False


def find_bundles(root):
    """Recursively list UnityFS asset bundles under root (sorted Paths)."""
    from pathlib import Path
    root = Path(os.path.expanduser(str(root)))
    if not root.exists():
        return []
    return [p for p in sorted(root.rglob("*")) if p.is_file() and is_unity_bundle(p)]
