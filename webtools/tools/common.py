"""Small shared helpers for turning loosely-typed form params into the exact
argument types the tool core functions expect."""
import os
from pathlib import Path


def parse_multi_paths(params):
    """The selected files from a `paths` field (newline-joined 'in_paths')."""
    raw = params.get("in_paths") or ""
    return [p.strip() for p in str(raw).replace("\r", "").split("\n") if p.strip()]


class _MultiJobProxy:
    """Wraps a Job for a single sub-run inside a multi run: log/cancel pass
    through, but the sub-run's own progress(0..1) is swallowed — the outer
    dispatcher drives the overall N-file progress bar."""
    def __init__(self, job):
        self._job = job

    def log(self, line):
        self._job.log(line)

    def should_stop(self):
        return self._job.should_stop()

    def progress(self, done, total):
        pass

    def __getattr__(self, name):
        return getattr(self._job, name)


def run_multi(tool_run, job, params):
    """Run each explicitly-selected file (multi-select mode) through the tool's
    own single-file path — so every tool that supports Single supports multi with
    no tool-specific code. Mirrors run_batch's log/progress/cancel/summary."""
    paths = parse_multi_paths(params)
    if not paths:
        raise ValueError("No files selected.")
    proxy = _MultiJobProxy(job)
    total = len(paths)
    ok = fail = 0
    job.progress(0, total)
    for i, p in enumerate(paths):
        if job.should_stop():
            job.log("[stopped]")
            break
        job.log(f"[{i + 1}/{total}] {os.path.basename(p)}")
        sub = dict(params)
        sub["mode"] = "single"
        sub["in_path"] = p
        try:
            tool_run(proxy, sub)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            job.log(f"FAIL {os.path.basename(p)}: {exc}")
        job.progress(i + 1, total)
    job.log(f"Done. total={total}  ok={ok}  fail={fail}")
    return f"multi done: total={total} ok={ok} fail={fail}"


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


def run_batch(job, in_dir, out_dir, prefix, suffix, per_file):
    """Apply per_file(src_path, out_path)->status_str over every bundle under
    in_dir, mirroring sub-paths and emitting log/progress/cancel events."""
    from webtools.core.sukusta import find_bundles
    bundles = find_bundles(in_dir)
    total = len(bundles)
    ok = fail = 0
    for i, src in enumerate(bundles, 1):
        if job.should_stop():
            job.log("[stopped]")
            break
        out_path = batch_out_path(in_dir, src, out_dir, prefix, suffix)
        try:
            status = per_file(src, out_path)
            ok += 1
            job.log(f"OK   {src.name} -> {out_path.name}" + (f" ({status})" if status else ""))
        except Exception as exc:  # noqa: BLE001
            fail += 1
            job.log(f"FAIL {src.name}: {exc}")
        job.progress(i, total)
    job.log(f"Done. total={total}  ok={ok}  fail={fail}")
    return f"batch done: total={total} ok={ok} fail={fail}"
