"""Bounded Unity AnimationClip curves exported as standard glTF animations.

Sources are read only. Streamed polynomials, dense samples and constants are
evaluated at the source sample rate (at most 60 Hz) into LINEAR glTF samplers.
Unsupported visibility/material/humanoid channels are reported, never guessed.
No clip, including SIFAS's eye_900, is implicitly selected as a neutral pose.
"""
import bisect
from hashlib import blake2b
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
import zlib


# Clip count bounds metadata/action choices, while the shared channel, sample
# and GLB byte limits bound actual animation memory. A bank of tiny facial or
# body poses should not consume the same budget as full-length dances.
MAX_CLIPS = 2048
MAX_CHANNELS = 32_768
# Automatic costume/face companion discovery keeps its original small-bank
# bound; a larger library is only read when it was explicitly supplied.
MAX_COMPANION_CLIPS = 96
MAX_CURVES = 2048
MAX_STREAM_WORDS = 8_000_000
MAX_STREAM_KEYS = 1_500_000
# Full-length game dances plus the original eye/mouth pose bank need more
# samples than short preview clips. Keep a fixed combined numeric budget.
MAX_KEYFRAMES = 2_000_000
MAX_VALUES = 8_000_000
MAX_SECONDS = 600
MAX_MORPHS = 128
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_UNPACKED = 32 * 1024 * 1024
MAX_DISCOVERY_FILES = 256
_OWNER = re.compile(r"(?:^|[^a-z0-9])ch(\d{4})(?=[^0-9]|$)", re.I)


class AnimationError(ValueError):
    pass


def _check(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        from .transient_failures import note
        note()
        raise AnimationError("Animation export exceeded its time budget.")


def path_hash(path):
    return zlib.crc32(str(path).replace("\\", "/").encode("utf-8")) & 0xFFFFFFFF


def _animation_source(path, deadline):
    from .model_viewer import _environment, _preflight_bundle
    if not 0 < os.path.getsize(path) <= MAX_SOURCE_BYTES:
        return set(), 0
    with open(path, "rb") as source:
        data = source.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES or _preflight_bundle(data) > MAX_SOURCE_UNPACKED:
        return set(), 0
    env = _environment([path], deadline)
    owners, count = set(), 0
    for obj in env.objects:
        _check(deadline)
        if obj.type.name in ("AssetBundle", "AnimationClip"):
            name = obj.peek_name() or ""
            owners.update(int(value) for value in _OWNER.findall(name))
            if obj.type.name == "AnimationClip":
                count += 1
    return owners, count


def discover_animation_paths(paths, context, owner, deadline):
    """Find at most two local clip companions; no downloads or filename identity.

    Explicit ``context.animation_paths`` are server-jailed motion selections and
    may be shared across characters. Automatically discovered clips require an
    exact internal character identity. Filenames only prioritize cheap scans.
    """
    context = context or {}
    selected = {os.path.realpath(path) for path in paths}
    roots = [os.path.dirname(path) for path in selected]
    roots.extend(os.path.dirname(os.path.realpath(origin)) for path, origin in context.get("origins", {}).items() if os.path.realpath(path) in selected)
    roots.extend(os.path.realpath(path) for path in context.get("library_roots", []))
    roots = list(dict.fromkeys(roots))
    found, inspected, attempted = [], 0, set(selected)
    from .charinfo import NAMES
    owner_name = NAMES.get(int(owner), "").split(" ", 1)[0].lower() if owner is not None else ""
    families = {Path(path).name.split("_", 1)[0].lower() for path in paths
                if re.fullmatch(r"[a-z0-9]{6}_\d+\.unity", Path(path).name.lower())}

    def rank(name):
        lower = name.lower()
        animation_hint = any(token in lower for token in ("anim", "motion", "clip", "eye_table", "eyetable"))
        owner_hint = (owner is not None and f"ch{int(owner):04}" in lower) or (owner_name and owner_name in lower)
        family_hint = lower.split("_", 1)[0] in families
        return (not (owner_hint and animation_hint), not family_hint, not animation_hint, not owner_hint, name)

    def inside(path):
        return any(path == root or path.startswith(root + os.sep) for root in roots)

    def inspect(path, explicit=False):
        nonlocal inspected
        _check(deadline)
        path = os.path.realpath(path)
        if path in attempted or not inside(path) or not os.path.isfile(path):
            return
        attempted.add(path)
        inspected += 1
        owners, count = _animation_source(path, deadline)
        if 0 < count <= MAX_COMPANION_CLIPS and (explicit or (owner is not None and owners == {int(owner)})):
            found.append(path)

    try:
        for path in list(context.get("animation_paths", []))[:2]:
            try:
                inspect(path, explicit=True)
            except (OSError, ValueError):
                pass
        if found or owner is None:
            return found[:2]
        seen = 0
        for root in roots:
            if not os.path.isdir(root):
                continue
            from .viewer_cache import is_legacy_viewer_cache_path, prune_legacy_viewer_cache_dirs
            if is_legacy_viewer_cache_path(root):
                continue
            for directory, dirs, files in os.walk(root, followlinks=False):
                _check(deadline)
                prune_legacy_viewer_cache_dirs(directory, dirs)
                depth = os.path.relpath(directory, root).count(os.sep)
                dirs[:] = sorted(name for name in dirs if not name.startswith(".") and depth < 2)[:32]
                for name in sorted(files, key=rank):
                    seen += 1
                    if seen > MAX_DISCOVERY_FILES or inspected >= 32:
                        return found[:2]
                    if name.lower().endswith((".json", ".txt", ".png", ".jpg", ".zip", ".glb", ".csv")):
                        continue
                    try:
                        inspect(os.path.join(directory, name))
                    except (OSError, ValueError):
                        continue
                    if found:
                        return found[:2]
    except AnimationError:
        pass
    return found[:2]


def _finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise AnimationError("An animation contains a non-finite value.")
    return value


def _width(binding):
    if int(binding.get("typeID", binding.get("classID", 0))) == 4:
        attribute = int(binding.get("attribute", 0))
        return 4 if attribute == 2 else (3 if attribute in (1, 3, 4) else 1)
    return 1


def _streamed(tree, deadline):
    import numpy as np
    count = int(tree.get("curveCount", 0))
    words = tree.get("data", [])
    if not 0 <= count <= MAX_CURVES or len(words) > MAX_STREAM_WORDS:
        raise AnimationError("The streamed animation exceeds the preview limit.")
    if not words:
        return [("cubic", []) for _ in range(count)]
    array = np.asarray(words)
    if not np.issubdtype(array.dtype, np.integer) or (array < 0).any() or (array > 0xFFFFFFFF).any():
        raise AnimationError("An animation stream contains invalid data words.")
    raw = np.ascontiguousarray(array, dtype="<u4").tobytes()
    curves, cursor, keys, previous = [[] for _ in range(count)], 0, 0, -math.inf
    while cursor < len(raw):
        _check(deadline)
        if cursor + 8 > len(raw):
            raise AnimationError("An animation stream is truncated.")
        stamp, number = struct.unpack_from("<fI", raw, cursor)
        cursor += 8
        keys += number
        if number > count or keys > MAX_STREAM_KEYS or cursor + number * 20 > len(raw) or math.isnan(stamp):
            raise AnimationError("An animation stream declares invalid keyframes.")
        if stamp < previous or (not math.isfinite(stamp) and (stamp < 0 or number)):
            raise AnimationError("An animation stream has invalid keyframe times.")
        previous = stamp
        for _ in range(number):
            index, a, b, c, value = struct.unpack_from("<Iffff", raw, cursor)
            cursor += 20
            if index >= count or not all(math.isfinite(x) for x in (a, b, c, value)):
                raise AnimationError("An animation stream contains an invalid curve.")
            curves[index].append((stamp, (a, b, c, value)))
    return [("cubic", curve) for curve in curves]


def _packed_curves(tree, deadline):
    muscle = tree.get("m_MuscleClip") or {}
    clip = muscle.get("m_Clip") or {}
    clip = clip.get("data", clip)
    if not isinstance(clip, dict):
        raise AnimationError("This animation uses unsupported packed curve data.")
    curves = _streamed(clip.get("m_StreamedClip") or {}, deadline)
    dense = clip.get("m_DenseClip") or {}
    count, frames = int(dense.get("m_CurveCount", 0)), int(dense.get("m_FrameCount", 0))
    samples = dense.get("m_SampleArray", [])
    if not 0 <= count <= MAX_CURVES or frames < 0 or (count and frames > MAX_KEYFRAMES) or count * frames > MAX_VALUES or len(samples) != count * frames:
        raise AnimationError("The dense animation exceeds the preview limit or is truncated.")
    if count:
        rate, begin = _finite(dense.get("m_SampleRate", 0)), _finite(dense.get("m_BeginTime", 0))
        if rate <= 0 or frames == 0:
            raise AnimationError("A dense animation has an invalid sample rate.")
        times = [begin + index / rate for index in range(frames)]
        curves.extend(("linear", [(stamp, _finite(samples[index * count + channel])) for index, stamp in enumerate(times)]) for channel in range(count))
    constant = (clip.get("m_ConstantClip") or {}).get("data", [])
    if len(constant) > MAX_CURVES or len(curves) + len(constant) > MAX_CURVES:
        raise AnimationError("The animation has too many scalar curves.")
    curves.extend(("constant", _finite(value)) for value in constant)
    return curves


def _evaluate(curve, stamp):
    mode, keys = curve
    if mode == "constant":
        return keys
    if not keys:
        raise AnimationError("An animation binding has no scalar curve values.")
    index = max(0, bisect.bisect_right(keys, stamp, key=lambda item: item[0]) - 1)
    start, value = keys[index]
    if mode == "cubic":
        if abs(start) > 1e20:
            return value[3]  # Unity's negative sentinel seeds the first value.
        delta = max(0., stamp - start)
        return ((value[0] * delta + value[1]) * delta + value[2]) * delta + value[3]
    if index + 1 < len(keys):
        stop, other = keys[index + 1]
        if stop > start:
            fraction = min(1., max(0., (stamp - start) / (stop - start)))
            return value + (other - value) * fraction
    return value


def _ascending(times):
    return all(a <= b for a, b in zip(times, times[1:]))


def _sample(curve, times, deadline=None):
    """``[_evaluate(curve, stamp) for stamp in times]`` for ascending ``times``.

    One forward walk over the keys replaces a bisection per stamp. The key
    found is the same (the last key at or before the stamp, else the first),
    and every value uses _evaluate's arithmetic in the same order, so the
    floats are bit-identical.
    """
    mode, keys = curve
    if mode == "constant":
        return [keys] * len(times)
    if not times:
        return []
    if not keys:
        raise AnimationError("An animation binding has no scalar curve values.")
    output, index, last = [], 0, len(keys) - 1
    append = output.append
    start, value = keys[0]
    following = keys[1][0] if last else None
    cubic = mode == "cubic"
    for sample_index, stamp in enumerate(times):
        if sample_index % 1024 == 0:
            _check(deadline)
        if index < last and following <= stamp:
            index += 1
            while index < last and keys[index + 1][0] <= stamp:
                index += 1
            start, value = keys[index]
            following = keys[index + 1][0] if index < last else None
        if cubic:
            if abs(start) > 1e20:
                append(value[3])  # Unity's negative sentinel seeds the first value.
            else:
                delta = max(0., stamp - start)
                append(((value[0] * delta + value[1]) * delta + value[2]) * delta + value[3])
        elif index < last and following > start:
            other = keys[index + 1][1]
            fraction = min(1., max(0., (stamp - start) / (following - start)))
            append(value + (other - value) * fraction)
        else:
            append(value)
    return output


def _sample_array(curve, grid):
    """_sample with float64 element-wise numpy: the same IEEE operations in the same order.

    ``grid`` is the ascending stamp array. searchsorted(side="right") - 1,
    clamped at 0, is bisect_right - 1 clamped at 0. Separate ufunc calls
    round every intermediate like Python floats do (nothing fuses into an
    FMA), and ``where(x > 0., x, 0.)`` / ``where(x < 1., x, 1.)`` are exactly
    ``max(0., x)`` / ``min(1., x)``, including for signed zeros. Returns None
    when a key table is not ascending; the caller then walks the keys.
    """
    import numpy as np
    mode, keys = curve
    stamps = np.fromiter((key[0] for key in keys), dtype=np.float64, count=len(keys))
    if len(stamps) > 1 and not (stamps[1:] >= stamps[:-1]).all():
        return None
    index = np.searchsorted(stamps, grid, side="right") - 1
    np.maximum(index, 0, out=index)
    start = stamps[index]
    with np.errstate(all="ignore"):
        if mode == "cubic":
            table = np.array([key[1] for key in keys], dtype=np.float64).reshape(len(keys), 4)[index]
            delta = grid - start
            delta = np.where(delta > 0., delta, 0.)
            value = ((table[:, 0] * delta + table[:, 1]) * delta + table[:, 2]) * delta + table[:, 3]
            # Unity's negative sentinel seeds the first value.
            value = np.where(np.abs(start) > 1e20, table[:, 3], value)
        else:
            values = np.fromiter((key[1] for key in keys), dtype=np.float64, count=len(keys))
            following = np.minimum(index + 1, len(keys) - 1)
            stop, current, other = stamps[following], values[index], values[following]
            fraction = (grid - start) / (stop - start)
            fraction = np.where(fraction > 0., fraction, 0.)
            fraction = np.where(fraction < 1., fraction, 1.)
            value = np.where((index + 1 < len(keys)) & (stop > start), current + (other - current) * fraction, current)
    return value.tolist()


# Below this many samples the Python walk is cheaper than building arrays.
_ARRAY_SAMPLES = 64


def _columns(curves, times, deadline=None, ascending=None):
    """Sample each curve at ``times``; an unordered grid keeps the per-stamp search."""
    if ascending is None:
        ascending = _ascending(times)
    if ascending:
        grid, columns = None, []
        for curve in curves:
            column = None
            if curve[0] != "constant" and curve[1] and len(times) >= _ARRAY_SAMPLES:
                _check(deadline)
                if grid is None:
                    import numpy as np
                    grid = np.array(times, dtype=np.float64)
                column = _sample_array(curve, grid)
            columns.append(_sample(curve, times, deadline) if column is None else column)
        return columns
    columns = []
    for curve in curves:
        column = []
        for sample_index, stamp in enumerate(times):
            if sample_index % 128 == 0:
                _check(deadline)
            column.append(_evaluate(curve, stamp))
        columns.append(column)
    return columns


def _editor_scalar(keys, axis=None, deadline=None):
    rows = []
    for index, key in enumerate(keys):
        if index % 128 == 0:
            _check(deadline)
        if int(key.get("weightedMode", key.get("m_WeightedMode", 0)) or 0):
            raise AnimationError("Weighted editor animation tangents are not supported by this preview.")
        def component(field, default=0.):
            value = key.get(field, default)
            return float(value.get(axis, default) if axis is not None and isinstance(value, dict) else value)
        stamp, value = _finite(key["time"]), _finite(component("value"))
        incoming, outgoing = component("inSlope"), component("outSlope")
        if math.isnan(incoming) or math.isnan(outgoing):
            raise AnimationError("An editor animation has invalid tangents.")
        rows.append((stamp, value, incoming, outgoing))
    rows.sort()
    result = []
    for index, (stamp, value, _, outgoing) in enumerate(rows):
        coefficients = (0., 0., 0., value)
        if index + 1 < len(rows):
            stop, other, incoming, _ = rows[index + 1]
            span = stop - stamp
            if span <= 0:
                raise AnimationError("An editor animation repeats a keyframe time.")
            if math.isfinite(outgoing) and math.isfinite(incoming):
                coefficients = ((2*value - 2*other + span*(outgoing + incoming)) / span**3,
                                (-3*value + 3*other - span*(2*outgoing + incoming)) / span**2, outgoing, value)
        result.append((stamp, coefficients))
    return "cubic", result


def _editor_curves(tree, deadline=None):
    tracks, values = [], 0
    for field, kind, axes in (("m_PositionCurves", "translation", "xyz"), ("m_RotationCurves", "rotation", "xyzw"),
                              ("m_ScaleCurves", "scale", "xyz"), ("m_EulerCurves", "euler", "xyz")):
        for item in tree.get(field, []):
            _check(deadline)
            keys = item.get("curve", {}).get("m_Curve", [])
            values += len(keys) * len(axes)
            if len(keys) > MAX_KEYFRAMES or values > MAX_VALUES or len(tracks) >= MAX_CURVES:
                raise AnimationError("An editor animation has too many keys.")
            components = [_editor_scalar(keys, axis, deadline) for axis in axes]
            if keys:
                track = {"path": item.get("path", ""), "kind": kind, "curves": components}
                if kind == "euler":
                    track["rotationOrder"] = euler_order(item.get("curve", {}).get("m_RotationOrder", DEFAULT_EULER_ORDER))
                tracks.append(track)
    for item in tree.get("m_FloatCurves", []):
        attribute = str(item.get("attribute", ""))
        visibility = ("renderer" if attribute == "m_Enabled" and int(item.get("classID", 0)) in (23, 25, 137)
                      else "gameObject" if attribute == "m_IsActive" and int(item.get("classID", 0)) == 1 else None)
        if attribute.startswith("blendShape.") or visibility:
            keys = item.get("curve", {}).get("m_Curve", [])
            values += len(keys)
            if len(keys) > MAX_KEYFRAMES or values > MAX_VALUES or len(tracks) >= MAX_CURVES:
                raise AnimationError("A morph animation has too many keys.")
            if keys:
                tracks.append({"path": item.get("path", ""), "kind": "visibility" if visibility else "weights",
                               "visibilityType": visibility, "attribute": attribute if visibility else attribute[11:],
                               "curves": [_editor_scalar(keys, deadline=deadline)]})
    return tracks


def _sample_times(start, stop, rate, tracks, deadline):
    """Keep authored boundaries while removing Float32 echoes of the grid.

    Unity stream stamps are Float32 while a nominal 60 Hz grid uses Python
    doubles. Prefer an authored stamp near a grid point; never merge distinct
    authored keys merely because they are close to one another.
    """
    count = max(1, int(math.ceil((stop - start) * rate)) + 1)
    if count > MAX_KEYFRAMES:
        raise AnimationError("The animation has too many sampled frames.")
    original = {start, stop}
    for track in tracks:
        for mode, keys in track["curves"]:
            if mode != "constant":
                for index, (stamp, _) in enumerate(keys):
                    if index % 1024 == 0:
                        _check(deadline)
                    if start <= stamp <= stop:
                        original.add(stamp)
                if len(original) > MAX_KEYFRAMES:
                    raise AnimationError("The animation has too many sampled frames.")
    boundaries = sorted(original)
    stamps = set(original)
    for index in range(count):
        if index % 1024 == 0:
            _check(deadline)
        stamp = min(stop, start + index / rate)
        neighbor = bisect.bisect_left(boundaries, stamp)
        if ((neighbor < len(boundaries) and abs(boundaries[neighbor] - stamp) <= 1e-5) or
                (neighbor and abs(boundaries[neighbor - 1] - stamp) <= 1e-5)):
            continue
        stamps.add(stamp)
    ordered, encoded = [], None
    for stamp in sorted(stamps):
        relative = struct.unpack("<f", struct.pack("<f", stamp - start))[0]
        if encoded is not None and relative == encoded:
            # glTF inputs cannot distinguish these Float32 times. Preserve the
            # authored/right-hand endpoint instead of duplicate sampler inputs.
            if stamp in original:
                ordered[-1] = stamp
            continue
        ordered.append(stamp); encoded = relative
    if len(ordered) > MAX_KEYFRAMES:
        raise AnimationError("The animation has too many sampled frames.")
    return ordered


def decode_clip(tree, deadline=None):
    """Decode curve declarations, retaining Unity path/attribute hashes."""
    _check(deadline)
    muscle = tree.get("m_MuscleClip") or {}
    start = _finite(muscle.get("m_StartTime", 0))
    stop = _finite(muscle.get("m_StopTime", start))
    tracks, unsupported, unsupported_kinds = [], 0, {}
    bindings = (tree.get("m_ClipBindingConstant") or {}).get("genericBindings", [])
    if len(bindings) > MAX_CURVES:
        raise AnimationError("The animation has too many bindings.")
    if bindings:
        curves, offset = _packed_curves(tree, deadline), 0
        for binding in bindings:
            _check(deadline)
            width = _width(binding)
            selected = curves[offset:offset + width]
            offset += width
            if len(selected) != width:
                raise AnimationError("Animation bindings do not match their packed curves.")
            kind, attribute = None, int(binding.get("attribute", 0))
            typ = int(binding.get("typeID", binding.get("classID", 0)))
            if not binding.get("isPPtrCurve") and typ == 4:
                kind = {1: "translation", 2: "rotation", 3: "scale", 4: "euler"}.get(attribute)
            elif not binding.get("isPPtrCurve") and typ == 137 and int(binding.get("customType", 0)) == 20:
                kind = "weights"
            elif not binding.get("isPPtrCurve") and ((typ in (23, 25, 137) and attribute == 3305885265)
                                                     or (typ == 1 and attribute == 2086281974)):
                kind = "visibility"
            if kind:
                track = {"path": int(binding.get("path", 0)), "kind": kind, "attribute": attribute,
                         "visibilityType": "gameObject" if typ == 1 else "renderer", "curves": selected}
                if kind == "euler":
                    # A Transform Euler binding keeps its Unity RotationOrder in customType.
                    track["rotationOrder"] = euler_order(binding.get("customType", DEFAULT_EULER_ORDER))
                tracks.append(track)
            else:
                unsupported += 1
                key = typ, attribute, int(binding.get("customType", 0))
                unsupported_kinds[key] = unsupported_kinds.get(key, 0) + 1
        if offset != len(curves):
            raise AnimationError("Packed animation curves are not fully described by their bindings.")
    else:
        tracks = _editor_curves(tree, deadline)
        if tracks:
            stop = max(stop, max(key[0] for track in tracks for _, keys in track["curves"] for key in keys))
    duration = stop - start
    if not 0 <= duration <= MAX_SECONDS:
        raise AnimationError("The animation duration exceeds the preview limit.")
    rate = min(60., max(1., _finite(tree.get("m_SampleRate", 60))))
    ordered = _sample_times(start, stop, rate, tracks, deadline)
    return {"name": str(tree.get("m_Name") or "Animation")[:160], "start": start, "duration": duration,
            "times": ordered, "tracks": tracks, "loop": bool(muscle.get("m_LoopTime", False)),
            "unsupported": unsupported,
            "unsupportedKinds": [{"typeID": key[0], "attribute": key[1], "customType": key[2], "count": count}
                                 for key, count in sorted(unsupported_kinds.items())],
            "sampling": "source_curves_at_most_60_hz"}


def _nodes(bindings, path):
    keys = (path, path_hash(path)) if isinstance(path, str) else (path,)
    for key in keys:
        value = bindings.get(key)
        if value is not None:
            return list(value) if isinstance(value, (list, tuple)) else [value]
    return []


def _morphs(bindings, path, attribute):
    entries = _nodes(bindings, path)
    matches = []
    for entry in entries:
        for index, name in enumerate(entry.get("names", [])):
            if attribute == name or attribute == path_hash(name) or attribute == (entry.get("hashes") or {}).get(name):
                matches.append((entry, index))
    if matches:
        return matches, False
    # Old exported facial prefabs sometimes retain a legacy path hash while
    # preserving the exact full blendshape name/hash. Rebind only when unique.
    unique = {}
    for value in bindings.values():
        for entry in value if isinstance(value, (list, tuple)) else [value]:
            for index, name in enumerate(entry.get("names", [])):
                if attribute == name or attribute == path_hash(name) or attribute == (entry.get("hashes") or {}).get(name):
                    unique[(entry["node"], index)] = (entry, index)
    return (list(unique.values()), True) if len(unique) == 1 else ([], False)


def _merge_visibility(tracks, deadline):
    """Renderer.enabled and ancestor GameObject.active combine with logical AND."""
    from bisect import bisect_right
    grouped = {}
    for track in tracks:
        grouped.setdefault(track["node"], []).append(track)
    output = []
    for node, group in grouped.items():
        _check(deadline)
        if len(group) == 1:
            output.append(group[0])
            continue
        stamps = sorted({stamp for track in group for stamp in track["times"]})
        if len(stamps) * len(group) > MAX_VALUES:
            raise AnimationError("Combined visibility exceeds the preview evaluation limit.")
        times, states = [], []
        for index, stamp in enumerate(stamps):
            if index % 128 == 0:
                _check(deadline)
            state = all(track["values"][max(0, bisect_right(track["times"], stamp) - 1)] for track in group)
            if not states or states[-1] != state:
                times.append(stamp)
                states.append(state)
        output.append({"node": node, "times": times, "values": states, "interpolation": "STEP",
                       "sourceProperty": "combined_visibility", "sourceProperties": [track["sourceProperty"] for track in group]})
    return output


def _white_line_scalar_keys(track, clip):
    """Keep the source Float32 cubic for the native facial visibility mixer."""
    mode, keys = track["curves"][0]
    if mode != "cubic" or not 1 <= len(keys) <= 16:
        return None
    start, stop = clip["start"], clip["start"] + clip["duration"]
    rows = [[stamp - start, *coefficients] for stamp, coefficients in keys if start <= stamp <= stop]
    if not rows or rows[0][0] > 0:
        prior = [key for key in keys if key[0] < start]
        if not prior:
            return None
        stamp, coefficients = prior[-1]
        # The native negative sentinel initializes a constant before t=0.
        if stamp > -1e20 and any(coefficients[:3]):
            return None
        rows.insert(0, [0, 0, 0, 0, coefficients[3]])
    if any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
        return None
    return rows


def _multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return (w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X, w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z)


# Unity math::RotationOrder, as an animated Euler rotation stores it: the
# customType of a Transform Euler GenericBinding (attribute 4) and the
# m_RotationOrder of an editor m_EulerCurves AnimationCurve. Each name lists the
# axes in the order they are applied, so OrderXYZ is q = qZ * qY * qX. ZXY
# (q = qY * qX * qZ, the Transform.eulerAngles convention) is Unity's default.
EULER_ORDERS = {0: "xyz", 1: "xzy", 2: "yzx", 3: "yxz", 4: "zxy", 5: "zyx"}
DEFAULT_EULER_ORDER = 4


def euler_order(value):
    """Validate a Unity RotationOrder value; reject what the preview cannot reproduce."""
    if type(value) is bool or type(value) not in (int, float) or value != int(value) or int(value) not in EULER_ORDERS:
        raise AnimationError("An animated Euler rotation has an unknown rotation order.")
    return int(value)


def _axis_quaternion(axis, half):
    values = [0., 0., 0., math.cos(half)]
    values["xyz".index(axis)] = math.sin(half)
    return tuple(values)


def unity_euler_quaternion(values, order=DEFAULT_EULER_ORDER):
    """Unity Euler degrees -> unnormalized Unity-handed quaternion (x, y, z, w) in `order`."""
    half = dict(zip("xyz", (math.radians(value) * .5 for value in values)))
    result = (0., 0., 0., 1.)
    for axis in EULER_ORDERS[euler_order(order)]:
        result = _multiply(_axis_quaternion(axis, half[axis]), result)  # A later axis applies on the left.
    return result


# The inverse direction, for writing Euler samples (camera point edits). These live here, not
# only in live_timeline.sifas_timeline_inject, so the webtools import cannot be shadowed by an
# older top-level live_timeline package (for example an elichika checkout's pinned modtools).
def quat_to_unity_euler(q, order=4):
    """Unity quaternion -> Unity Euler degrees in rotation `order` (default ZXY).

    Applying axes a, b, c in this order gives R = Rc * Rb * Ra; the middle axis b is
    the asin one. Even permutations (xyz, yzx, zxy) and odd ones differ only in sign.
    """
    if order not in EULER_ORDERS:
        raise ValueError(f"unknown Unity rotation order {order!r}")
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    m = ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
         (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
         (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))
    a, b, c = ("xyz".index(axis) for axis in EULER_ORDERS[order])
    s = 1.0 if EULER_ORDERS[order] in ("xyz", "yzx", "zxy") else -1.0
    cb = math.hypot(m[c][b], m[c][c])  # |cos b|: atan2 instead of asin stays exact near +-90 deg.
    angles = [0.0, 0.0, 0.0]
    angles[b] = math.atan2(-s * m[c][a], cb)
    if cb > 1e-9:
        angles[a] = math.atan2(s * m[c][b], m[c][c])
        angles[c] = math.atan2(s * m[b][a], m[a][a])
    else:  # Gimbal lock: keep the first axis at 0 and put the rest on the last axis.
        angles[c] = math.atan2(-s * m[a][b], m[b][b])
    return tuple(math.degrees(value) for value in angles)


def unity_euler_branches(euler, order=4):
    """The two Euler solutions of the same rotation: as is, and (a+180, 180-b, c+180)."""
    a, b, c = ("xyz".index(axis) for axis in EULER_ORDERS[order])
    other = list(euler)
    other[a] += 180.0
    other[b] = 180.0 - other[b]
    other[c] += 180.0
    return [list(euler), other]


def _euler_qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def unity_euler_near(q, order=4, reference=None):
    """The Euler angles (degrees) of the same rotation nearest to `reference`.

    A DenseClip interpolates Euler values linearly between samples, so pick the
    solution nearest the previous sample, unwrapped by whole turns. At the middle-axis
    +-90 deg gimbal (yaw +-90 for XYZ cameras), pin the first axis to the previous
    value and solve the last one.
    """
    euler = quat_to_unity_euler(q, order)
    if reference is None:
        return list(euler)
    a, b, c = ("xyz".index(axis) for axis in EULER_ORDERS[order])
    candidates = unity_euler_branches(euler, order)
    if abs(math.cos(math.radians(euler[b]))) < 1e-6:
        # q = qc * qb * qa: with the first axis a pinned, qc = q * (qb * qa)^-1.
        half_a, half_b = math.radians(reference[a]) / 2, math.radians(euler[b]) / 2
        qa, qb = [0.0, 0.0, 0.0, math.cos(half_a)], [0.0, 0.0, 0.0, math.cos(half_b)]
        qa[a], qb[b] = math.sin(half_a), math.sin(half_b)
        x, y, z, w = _euler_qmul(qb, qa)
        qc = _euler_qmul(q, (-x, -y, -z, w))
        pinned = list(euler)
        pinned[a], pinned[c] = reference[a], math.degrees(2 * math.atan2(qc[c], qc[3]))
        candidates.append(pinned)
    candidates = [[value + 360.0 * round((previous - value) / 360.0) for value, previous in zip(branch, reference)]
                  for branch in candidates]
    return min(candidates, key=lambda branch: sum((value - previous) ** 2 for value, previous in zip(branch, reference)))


def _quaternion(values, euler=False, order=DEFAULT_EULER_ORDER):
    if euler:
        values = unity_euler_quaternion(values, order)
    if len(values) == 4:
        # sum() of the same four products in the same order (no generator).
        x, y, z, w = values
        length = math.sqrt(sum((x * x, y * y, z * z, w * w)))
    else:
        length = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(length) or length < 1e-12:
        raise AnimationError("An animated rotation is invalid.")
    x, y, z, w = (value / length for value in values)
    return [x, -y, -z, w]


def _sum4(a, b, c, d):
    """Element-wise ``sum((a, b, c, d))`` of float64 arrays, as this interpreter's sum() computes it.

    Python 3.12+ adds floats with Neumaier compensation (start 0 + a, then a
    running compensation added once at the end when it is finite and
    nonzero); older interpreters add left to right. Every step is one IEEE
    operation, and _array_sum_matches proves the replica against sum().
    """
    import numpy as np
    total = 0. + a
    if not _NEUMAIER:
        return ((total + b) + c) + d
    compensation = np.zeros_like(total)
    for item in (b, c, d):
        step = total + item
        compensation = compensation + np.where(np.abs(total) >= np.abs(item), (total - step) + item, (item - step) + total)
        total = step
    return np.where((compensation != 0.) & np.isfinite(compensation), total + compensation, total)


_NEUMAIER = sys.version_info >= (3, 12)
_SUM_CHECK = None


def _array_sum_matches():
    """True when _sum4 reproduces sum() bit for bit on cases where compensation matters."""
    global _SUM_CHECK
    if _SUM_CHECK is None:
        try:
            import numpy as np
            rows = [(1., 1e100, 1., -1e100), (.1, .2, .3, .4), (1e16, 1., -1e16, 1.), (0., -0., 0., -0.),
                    (-0., -0., -0., -0.), (1e308, 1e308, -1e308, 1.), (3., 1e-16, 1e-16, 1e-16), (-1., 1e-17, 1., 1e-17),
                    (.7, -.3, 1e-9, -.4), (2. ** -1074, -(2. ** -1074), 1., -1.)]
            columns = [np.array(column, dtype=np.float64) for column in zip(*rows)]
            with np.errstate(all="ignore"):
                found = _sum4(*columns).tolist()
            _SUM_CHECK = all(struct.pack("<d", value) == struct.pack("<d", sum(row)) for value, row in zip(found, rows))
        except Exception:
            _SUM_CHECK = False
    return _SUM_CHECK


def _rotation_rows(columns, euler, order, deadline=None):
    """``[_quaternion(row, euler, order) for row in rows]`` plus the sign continuity pass.

    The norm and the dot products use _sum4, so they are sum() bit for bit.
    Negating a row negates each dot product with it exactly (rounding is
    symmetric), so whether row i flips depends only on its original dot with
    row i - 1 and whether row i - 1 flipped.
    """
    rows = zip(*columns)
    if euler:
        rows = [unity_euler_quaternion(row, order) for row in rows]
    else:
        rows = list(rows)
    if len(rows) < _ARRAY_SAMPLES or any(len(row) != 4 for row in rows[:1]) or not _array_sum_matches():
        values = [_quaternion(row) for row in rows]
        for previous, current in zip(values, values[1:]):
            if sum((previous[0]*current[0], previous[1]*current[1],
                    previous[2]*current[2], previous[3]*current[3])) < 0:
                current[:] = [-current[0], -current[1], -current[2], -current[3]]
        return values
    import numpy as np
    _check(deadline)
    x, y, z, w = np.array(rows, dtype=np.float64).reshape(len(rows), 4).T
    with np.errstate(all="ignore"):
        length = np.sqrt(_sum4(x * x, y * y, z * z, w * w))
        if not (np.isfinite(length) & (length >= 1e-12)).all():
            raise AnimationError("An animated rotation is invalid.")
        x, y, z, w = x / length, -(y / length), -(z / length), w / length
        dots = _sum4(x[:-1] * x[1:], y[:-1] * y[1:], z[:-1] * z[1:], w[:-1] * w[1:]).tolist()
    _check(deadline)
    signs, flipped, any_flipped = [1.], False, False
    for dot in dots:
        flipped = (dot > 0. and flipped) or (dot < 0. and not flipped)
        signs.append(-1. if flipped else 1.)
        any_flipped = any_flipped or flipped
    if any_flipped:
        factor = np.array(signs, dtype=np.float64)
        x, y, z, w = x * factor, y * factor, z * factor, w * factor
    return np.stack((x, y, z, w), axis=1).tolist()


def _attribute(glb, values, kind, cache, bounds=False):
    import numpy as np
    array = np.asarray(values, dtype=float)
    if array.size > MAX_VALUES or not np.isfinite(array).all() or (np.abs(array) > 3.4e38).any():
        raise AnimationError("The animation exceeds the preview value limit.")
    if kind == "SCALAR":
        array = array.reshape(-1, 1)
    array = np.ascontiguousarray(array, dtype="<f4")
    raw = memoryview(array).cast("B")
    key = (kind, bounds, array.shape, blake2b(raw, digest_size=16).digest())
    index = cache.get(key)
    if index is not None:
        view = glb.doc["bufferViews"][glb.doc["accessors"][index]["bufferView"]]
        start = view["byteOffset"]
        if raw == memoryview(glb.data)[start:start + view["byteLength"]]:
            return index
    index = glb.attribute(array, kind, bounds=bounds, target=None)
    cache[key] = index
    return index


def animation_candidate(glb, deadline=None):
    """Copy live geometry/images to a new builder, discarding old animations.

    Geometry may have been appended after an earlier animation pass. Follow
    typed references so detached geometry and its buffers are retained.
    The original document/data remain available for transactional recovery.
    """
    import copy
    candidate = glb.__class__()
    candidate.doc = copy.deepcopy(glb.doc)
    candidate.doc.pop("animations", None)
    accessors = glb.doc.get("accessors", [])
    views = glb.doc.get("bufferViews", [])
    live_accessors, live_views = set(), set()
    def accessor(value):
        if type(value) is not int or not 0 <= value < len(accessors):
            raise AnimationError("A geometry attribute references an unavailable accessor.")
        live_accessors.add(value)
    def view(value):
        if type(value) is not int or not 0 <= value < len(views):
            raise AnimationError("A model buffer view is unavailable.")
        live_views.add(value)
    for mesh in candidate.doc.get("meshes", []):
        _check(deadline)
        for primitive in mesh.get("primitives", []):
            for value in primitive.get("attributes", {}).values():
                accessor(value)
            if "indices" in primitive:
                accessor(primitive["indices"])
            for target in primitive.get("targets", []):
                for value in target.values():
                    accessor(value)
    for skin in candidate.doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            accessor(skin["inverseBindMatrices"])
    shadows = [scene["extras"]["mvMemberShadow"] for scene in candidate.doc.get("scenes", [])
               if "mvMemberShadow" in scene.get("extras", {})]
    for shadow in shadows:
        for value in shadow["geometry"].values():
            accessor(value)
    for index in live_accessors:
        item = accessors[index]
        if "bufferView" in item:
            view(item["bufferView"])
        sparse = item.get("sparse", {})
        for key in ("indices", "values"):
            if key in sparse:
                view(sparse[key]["bufferView"])
    for image in candidate.doc.get("images", []):
        if "bufferView" in image:
            view(image["bufferView"])
    view_map = {}
    candidate.doc["bufferViews"] = []
    for index in sorted(live_views):
        _check(deadline)
        item = views[index]
        offset, length = item.get("byteOffset", 0), item["byteLength"]
        if item.get("buffer", 0) != 0 or type(offset) is not int or type(length) is not int or offset < 0 or length < 0 or offset + length > len(glb.data):
            raise AnimationError("A model buffer view has invalid binary bounds.")
        mapped = candidate.view(glb.data[offset:offset + length], item.get("target"))
        position = candidate.doc["bufferViews"][mapped]["byteOffset"]
        candidate.doc["bufferViews"][mapped] = {**copy.deepcopy(item), "buffer": 0, "byteOffset": position}
        view_map[index] = mapped
    accessor_map = {old: new for new, old in enumerate(sorted(live_accessors))}
    candidate.doc["accessors"] = [copy.deepcopy(accessors[index]) for index in sorted(live_accessors)]
    for item in candidate.doc["accessors"]:
        if "bufferView" in item:
            item["bufferView"] = view_map[item["bufferView"]]
        for entry in item.get("sparse", {}).values():
            if isinstance(entry, dict) and "bufferView" in entry:
                entry["bufferView"] = view_map[entry["bufferView"]]
    for mesh in candidate.doc.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            # Submeshes can share these containers. Replace them so a shared
            # accessor dictionary is never remapped twice through its alias.
            primitive["attributes"] = {key: accessor_map[value] for key, value in primitive.get("attributes", {}).items()}
            if "indices" in primitive:
                primitive["indices"] = accessor_map[primitive["indices"]]
            if "targets" in primitive:
                primitive["targets"] = [{key: accessor_map[value] for key, value in target.items()} for target in primitive["targets"]]
    for skin in candidate.doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            skin["inverseBindMatrices"] = accessor_map[skin["inverseBindMatrices"]]
    for shadow in shadows:
        shadow["geometry"] = {key: accessor_map[value] for key, value in shadow["geometry"].items()}
    for image in candidate.doc.get("images", []):
        if "bufferView" in image:
            image["bufferView"] = view_map[image["bufferView"]]
    if candidate.doc.get("buffers"):
        candidate.doc["buffers"][0]["byteLength"] = len(candidate.data)
    return candidate


def append_animations(scene, glb, node_bindings, morph_bindings=None, *, deadline=None, visibility_bindings=None):
    """Append supplied clips; bindings refer only to already exported rig nodes."""
    warnings, metadata, used_frames, used_values, used_channels = [], [], 0, 0, 0
    morph_bindings = morph_bindings or {}
    visibility_bindings = visibility_bindings or {}
    used_names = {item.get("name", "") for item in glb.doc.get("animations", [])}
    accessors = {}
    from .game_motion_selection import describe_clip_roles, _object_key
    source_roles = describe_clip_roles(scene, deadline)

    def warn(code, name, message):
        item = {"code": code, "name": name, "message": message}
        if item not in warnings:
            warnings.append(item)

    clips = [obj for obj in scene.env.objects if obj.type.name == "AnimationClip"]
    if len(clips) > MAX_CLIPS:
        warn("animation_limit", "", f"Only the first {MAX_CLIPS} supplied animation clips are available in this preview; {len(clips) - MAX_CLIPS} clips were omitted.")
    # Progress in source bytes: a full dance outweighs a facial pose.
    sizes = [max(1, int(getattr(obj, "byte_size", 1) or 1)) for obj in clips[:MAX_CLIPS]]
    total_size, done_size = sum(sizes), 0
    from .mv_studio_progress import tick
    for obj, size in zip(clips[:MAX_CLIPS], sizes):
        _check(deadline)
        tick("animation", round(100 * done_size / total_size), 100)
        done_size += size
        name = scene.name(obj)
        checkpoint = (len(glb.data), len(glb.doc["accessors"]), len(glb.doc["bufferViews"]))
        try:
            clip = decode_clip(scene.tree(obj), deadline)
            source_role = source_roles.get(_object_key(obj), "unknown") if hasattr(obj, "assets_file") else "unknown"
            times, outputs, morph_outputs, rebound, unbound, ambiguous = clip["times"], [], {}, False, 0, False
            ascending = _ascending(times)
            # A glTF weights channel carries every target of its mesh; the
            # source clip binds only these indices (the rest stay at rest).
            morph_indices = {}
            visibility_tracks = []
            planned_frames, planned_values = 0, 0
            for track_index, track in enumerate(clip["tracks"]):
                _check(deadline)
                tick("animation", round(100 * (done_size - size + size * track_index / len(clip["tracks"])) / total_size), 100)
                if track["kind"] == "visibility":
                    mode = track.get("visibilityType", "renderer")
                    targets = _nodes(visibility_bindings.get(mode, {}), track["path"])
                    if not targets:
                        unbound += 1
                    planned_frames += len(times) * len(targets)
                    planned_values += len(times) * len(targets)
                    if used_frames + planned_frames > MAX_KEYFRAMES or used_values + planned_values > MAX_VALUES:
                        raise AnimationError("Visibility animation exceeds the mobile preview keyframe limit.")
                    stamps, states = [], []
                    column = _columns([track["curves"][0]], times, deadline, ascending)[0] if times else []
                    for stamp, sampled in zip(times, column):
                        state = sampled >= .5
                        if not states or state != states[-1]:
                            stamps.append(stamp - clip["start"])
                            states.append(state)
                    for node in targets:
                        if not 0 <= int(node) < len(glb.doc["nodes"]) or "mesh" not in glb.doc["nodes"][int(node)]:
                            raise AnimationError("Visibility animation must target an exported mesh, never a skeleton bone.")
                        row = {"node": int(node), "times": stamps, "values": states,
                               "interpolation": "STEP", "sourceProperty": "GameObject.m_IsActive" if mode == "gameObject" else "Renderer.m_Enabled"}
                        target = glb.doc["nodes"][int(node)]
                        if (source_role == "facial" and mode == "renderer" and track["attribute"] == 3305885265
                                and target["name"] in ("LeftEyeWhiteLine", "RightEyeWhiteLine")):
                            primitives = glb.doc["meshes"][target["mesh"]]["primitives"]
                            if (len(primitives) == 1 and
                                    primitives[0].get("extras", {}).get("mvStageCameraDepth", {}).get("kind") == "memberFace"):
                                keys = _white_line_scalar_keys(track, clip)
                                if keys is not None:
                                    row["sourceScalarKeys"] = keys
                        visibility_tracks.append(row)
                    continue
                if track["kind"] == "weights":
                    matches, moved = _morphs(morph_bindings, track["path"], track["attribute"])
                    rebound |= moved
                    if not matches:
                        unbound += 1
                    column = None
                    for entry, index in matches:
                        count = len(entry["names"])
                        if not 0 < count <= MAX_MORPHS:
                            raise AnimationError("An animated mesh has too many morph targets.")
                        node = int(entry["node"])
                        if node not in morph_outputs:
                            planned_frames += len(times)
                            planned_values += len(times) * count
                            if used_frames + planned_frames > MAX_KEYFRAMES or used_values + planned_values > MAX_VALUES:
                                raise AnimationError("The supplied animations exceed the mobile preview keyframe limit.")
                            rest = list(entry.get("weights") or [0.] * count)
                            if len(rest) != count:
                                raise AnimationError("An animated mesh has invalid rest morph weights.")
                            morph_outputs[node] = [rest.copy() for _ in times]
                        morph_indices.setdefault(node, set()).add(index)
                        if times and column is None:
                            # Sampled where the first evaluation used to happen, so
                            # errors keep their order.
                            column = _columns([track["curves"][0]], times, deadline, ascending)[0]
                        for row, sampled in zip(morph_outputs[node], column or ()):
                            row[index] = sampled / 100.
                    continue
                targets = _nodes(node_bindings, track["path"])
                ambiguous |= len(set(targets)) > 1
                if not targets:
                    unbound += 1
                    continue
                planned_frames += len(times) * len(targets)
                planned_values += len(times) * len(track["curves"]) * len(targets)
                if used_frames + planned_frames > MAX_KEYFRAMES or used_values + planned_values > MAX_VALUES:
                    raise AnimationError("The supplied animations exceed the mobile preview keyframe limit.")
                columns = _columns(track["curves"], times, deadline, ascending)
                kind = track["kind"]
                if kind in ("rotation", "euler") and columns:
                    order = track.get("rotationOrder", DEFAULT_EULER_ORDER)
                    values = _rotation_rows(columns, kind == "euler", order, deadline)
                    kind = "rotation"
                elif kind in ("rotation", "euler"):
                    order = track.get("rotationOrder", DEFAULT_EULER_ORDER)
                    values = [_quaternion([], kind == "euler", order) for _ in times]
                    kind = "rotation"
                else:
                    values = [list(row) for row in zip(*columns)] if columns else [[] for _ in times]
                if kind == "translation":
                    values = [[-row[0], row[1], row[2]] for row in values]
                for node in targets:
                    outputs.append((int(node), kind, values))
            # Unity may retain editor Euler and quaternion curves for the same
            # target. glTF permits one channel per node/property; prefer the
            # first authored quaternion track (editor order places it first).
            unique = {}
            for node, kind, rows in outputs:
                unique.setdefault((node, kind), rows)
            outputs = [(node, kind, rows) for (node, kind), rows in unique.items()]
            outputs.extend((node, "weights", rows) for node, rows in morph_outputs.items())
            visibility_tracks = _merge_visibility(visibility_tracks, deadline)
            channels = len(outputs) + len(visibility_tracks)
            if used_channels + channels > MAX_CHANNELS:
                raise AnimationError("The supplied animations exceed the preview channel limit.")
            frames = len(times) * len(outputs) + sum(len(row["times"]) for row in visibility_tracks)
            values = sum(len(row) for _, _, rows in outputs for row in rows) + sum(
                len(row["values"]) + 5 * len(row.get("sourceScalarKeys", ())) for row in visibility_tracks)
            if used_frames + frames > MAX_KEYFRAMES or used_values + values > MAX_VALUES:
                raise AnimationError("The supplied animations exceed the mobile preview keyframe limit.")
            if any(not 0 <= node < len(glb.doc["nodes"]) for node, _, _ in outputs):
                raise AnimationError("An animation points to an unavailable rig node.")
            if not outputs and not visibility_tracks:
                warn("animation_unbound", name, "This clip has no supported channels bound to the displayed rig.")
                continue
            relative_times = [stamp - clip["start"] for stamp in times]
            input_accessor = _attribute(glb, relative_times, "SCALAR", accessors, bounds=True) if outputs else None
            exported_name, suffix = clip["name"], 2
            while exported_name in used_names:
                exported_name = clip["name"] + "__" + str(suffix)
                suffix += 1
            animation = {"name": exported_name, "samplers": [], "channels": [],
                         "extras": {"loop": clip["loop"], "sourceSampling": clip["sampling"]}}
            for node, kind, rows in outputs:
                accessor = _attribute(glb, [value for row in rows for value in row] if kind == "weights" else rows,
                                      "SCALAR" if kind == "weights" else ("VEC4" if kind == "rotation" else "VEC3"), accessors)
                sampler = len(animation["samplers"])
                animation["samplers"].append({"input": input_accessor, "output": accessor, "interpolation": "LINEAR"})
                animation["channels"].append({"sampler": sampler, "target": {"node": node, "path": kind}})
            index = len(glb.doc.setdefault("animations", [])) if outputs else None
            if outputs:
                glb.doc["animations"].append(animation)
            used_names.add(exported_name)
            source_identifier, source_hash = "", ""
            if hasattr(obj, "assets_file"):
                from .model_viewer import _source_path, _source_hash
                from .model_motion import source_id
                source_identifier, source_hash = source_id(_source_path(obj)), _source_hash(obj)
            metadata.append({"index": index, "name": exported_name, "sourceName": clip["name"], "duration": clip["duration"],
                             "channels": len(outputs), "loop": clip["loop"], "visibility": visibility_tracks,
                             "sourceId": source_identifier, "sourceHash": source_hash, "sourceTracks": len(clip["tracks"]),
                             "sourceRole": source_role,
                             "unsupportedTracks": clip["unsupported"], "unboundTracks": unbound,
                             "unsupportedKinds": clip["unsupportedKinds"],
                             "bindingComplete": not (clip["unsupported"] or unbound or ambiguous)})
            if morph_indices:
                metadata[-1]["morphTargets"] = [{"node": node, "indices": sorted(indices)}
                                                for node, indices in sorted(morph_indices.items())]
            used_frames += frames
            used_values += values
            used_channels += channels
            if clip["unsupported"] or unbound:
                animator = sum(row["count"] for row in clip["unsupportedKinds"] if row["typeID"] == 95)
                details = []
                if animator:
                    details.append(f"{animator} Animator parameter curves are not rendered.")
                if clip["unsupported"] > animator:
                    details.append(f"{clip['unsupported'] - animator} other animation channels are unsupported.")
                if unbound:
                    details.append(f"{unbound} animation channels could not bind to this model.")
                warn("animation_partial", name, " ".join(details))
            if rebound:
                warn("animation_morph_path_rebound", name, "A facial curve used its unique original morph name because its legacy transform path differs.")
        except Exception as error:
            del glb.data[checkpoint[0]:]
            del glb.doc["accessors"][checkpoint[1]:]
            del glb.doc["bufferViews"][checkpoint[2]:]
            accessors.clear()
            warn("animation_unavailable", name, str(error) if isinstance(error, AnimationError) else "This animation format could not be imported.")
    return {"clips": metadata, "warnings": warnings}
