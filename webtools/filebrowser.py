"""A read-only, jailed file browser that replaces the tools' tkinter file
dialogs. All access is confined to a small set of allowed roots (the sukusta
library + the user's home), and every path is realpath-normalised and checked so
the browser can never read or write outside those roots.
"""
import os

from webtools.core.sukusta import default_sukusta_dir, is_unity_bundle


def allowed_roots() -> dict:
    """Named starting points the UI may browse from."""
    roots = {}
    roots["extracted"] = default_sukusta_dir("extracted")
    roots["modded"] = default_sukusta_dir("modded")
    # The costume installer's drop folder — the packer writes finished .zip packs
    # here so Install Costume picks them up without a manual move.
    roots["suit"] = default_sukusta_dir("suit")
    base = os.environ.get("SUKUSTA_DIR")
    if base:
        roots["sukusta"] = os.path.expanduser(base)
    roots["home"] = os.path.expanduser("~")
    return roots


def _real(path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def is_within_allowed(path) -> bool:
    rp = _real(path)
    for root in allowed_roots().values():
        rr = _real(root)
        if rp == rr or rp.startswith(rr + os.sep):
            return True
    return False


def roots_listing() -> dict:
    """The roots, annotated with whether they currently exist on disk."""
    out = []
    for name, path in allowed_roots().items():
        rp = _real(path)
        out.append({"name": name, "path": rp, "exists": os.path.isdir(rp)})
    return {"roots": out}


def list_dir(path) -> dict:
    """List one directory (jailed). `path` blank/None falls back to home."""
    if not path:
        path = os.path.expanduser("~")
    rp = _real(path)
    if not is_within_allowed(rp):
        raise PermissionError("path is outside the allowed roots")
    if not os.path.isdir(rp):
        raise NotADirectoryError(rp)

    entries = []
    try:
        names = sorted(os.listdir(rp), key=lambda s: s.lower())
    except OSError as exc:
        raise PermissionError(str(exc))

    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(rp, name)
        try:
            is_dir = os.path.isdir(full)
        except OSError:
            continue
        item = {"name": name, "path": full, "is_dir": is_dir}
        if not is_dir:
            try:
                item["size"] = os.path.getsize(full)
            except OSError:
                item["size"] = 0
            item["is_bundle"] = is_unity_bundle(full)
        entries.append(item)

    parent = os.path.dirname(rp)
    return {
        "path": rp,
        "parent": parent if (parent != rp and is_within_allowed(parent)) else None,
        "entries": entries,
    }
