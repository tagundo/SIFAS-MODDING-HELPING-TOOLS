"""Small shared helpers for turning loosely-typed form params into the exact
argument types the tool core functions expect."""
from pathlib import Path


def as_float_or_none(value):
    """'' / None -> None ; otherwise float(value)."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    return float(s)


def as_float(value, default=0.0):
    v = as_float_or_none(value)
    return default if v is None else v


def parse_patterns(value, default):
    """Accept a list or a comma/space separated string; fall back to `default`."""
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple)):
        out = [str(p).strip() for p in value if str(p).strip()]
    else:
        out = [p.strip() for p in str(value).replace(",", " ").split() if p.strip()]
    return out or list(default)


def triple_set(params, keys):
    """Return (x,y,z) absolute scale with None for blank axes, or None if all blank."""
    vals = tuple(as_float_or_none(params.get(k)) for k in keys)
    if all(v is None for v in vals):
        return None
    return vals


def triple_add(params, keys):
    """Return (dx,dy,dz) additive delta, blanks treated as 0.0."""
    return tuple(as_float(params.get(k), 0.0) for k in keys)


def batch_out_path(in_dir, src_file, out_dir, prefix, suffix):
    """out_dir/<sub-path of src under in_dir>/<prefix><stem><suffix><ext>,
    mirroring the layout the tools' own batch runners produce."""
    src = Path(src_file)
    try:
        rel = src.resolve().relative_to(Path(in_dir).resolve())
    except Exception:
        rel = Path(src.name)
    out_name = f"{prefix}{rel.stem}{suffix}{rel.suffix}"
    return Path(out_dir) / rel.parent / out_name


def single_out_path(out_dir, src_file, prefix, suffix):
    src = Path(src_file)
    return Path(out_dir) / f"{prefix}{src.stem}{suffix}{src.suffix}"
