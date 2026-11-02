"""Bounded Unity AnimationClip curves exported as standard glTF animations.

Sources are read only. Streamed polynomials, dense samples and constants are
evaluated at the source sample rate (at most 60 Hz) into LINEAR glTF samplers.
Unsupported visibility/material/humanoid channels are reported, never guessed.
No clip, including SIFAS's eye_900, is implicitly selected as a neutral pose.
"""
import bisect
import math
import os
from pathlib import Path
import re
import struct
import time
import zlib


MAX_CLIPS = 32
MAX_CURVES = 2048
MAX_STREAM_WORDS = 1_000_000
MAX_STREAM_KEYS = 32768
MAX_KEYFRAMES = 32768
MAX_VALUES = 1_000_000
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
        if 0 < count <= MAX_CLIPS and (explicit or (owner is not None and owners == {int(owner)})):
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
            for directory, dirs, files in os.walk(root, followlinks=False):
                _check(deadline)
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
                tracks.append({"path": item.get("path", ""), "kind": kind, "curves": components})
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


def decode_clip(tree, deadline=None):
    """Decode curve declarations, retaining Unity path/attribute hashes."""
    _check(deadline)
    muscle = tree.get("m_MuscleClip") or {}
    start = _finite(muscle.get("m_StartTime", 0))
    stop = _finite(muscle.get("m_StopTime", start))
    tracks, unsupported = [], 0
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
                tracks.append({"path": int(binding.get("path", 0)), "kind": kind, "attribute": attribute,
                               "visibilityType": "gameObject" if typ == 1 else "renderer", "curves": selected})
            else:
                unsupported += 1
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
    count = max(1, int(math.ceil(duration * rate)) + 1)
    if count > MAX_KEYFRAMES:
        raise AnimationError("The animation has too many sampled frames.")
    stamps = [start + min(duration, index / rate) for index in range(count)]
    stamps[-1] = stop
    # Keep original finite key boundaries too, especially terminal visibility-
    # adjacent facial shape changes that need their exact authored endpoint.
    for track in tracks:
        for mode, keys in track["curves"]:
            if mode != "constant":
                stamps.extend(stamp for stamp, _ in keys if start <= stamp <= stop)
    ordered = []
    for stamp in sorted(set(stamps)):
        if not ordered or stamp - ordered[-1] > 1e-7:
            ordered.append(stamp)
    if len(ordered) > MAX_KEYFRAMES:
        raise AnimationError("The animation has too many sampled frames.")
    return {"name": str(tree.get("m_Name") or "Animation")[:160], "start": start, "duration": duration,
            "times": ordered, "tracks": tracks, "loop": bool(muscle.get("m_LoopTime", False)),
            "unsupported": unsupported, "sampling": "source_curves_at_most_60_hz"}


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


def _multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return (w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X, w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z)


def _quaternion(values, euler=False):
    if euler:
        x, y, z = (math.radians(value) * .5 for value in values)
        values = _multiply(_multiply((0, math.sin(y), 0, math.cos(y)), (math.sin(x), 0, 0, math.cos(x))),
                           (0, 0, math.sin(z), math.cos(z)))  # Unity intrinsic Z-X-Y
    length = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(length) or length < 1e-12:
        raise AnimationError("An animated rotation is invalid.")
    x, y, z, w = (value / length for value in values)
    return [x, -y, -z, w]


def _attribute(glb, values, kind, bounds=False):
    import numpy as np
    array = np.asarray(values, dtype=float)
    if array.size > MAX_VALUES or not np.isfinite(array).all() or (np.abs(array) > 3.4e38).any():
        raise AnimationError("The animation exceeds the preview value limit.")
    if kind == "SCALAR":
        array = array.reshape(-1, 1)
    index = glb.attribute(array, kind, bounds=bounds)
    view = glb.doc["accessors"][index]["bufferView"]
    glb.doc["bufferViews"][view].pop("target", None)
    return index


def append_animations(scene, glb, node_bindings, morph_bindings=None, *, deadline=None, visibility_bindings=None):
    """Append supplied clips; bindings refer only to already exported rig nodes."""
    warnings, metadata, used_frames, used_values = [], [], 0, 0
    morph_bindings = morph_bindings or {}
    visibility_bindings = visibility_bindings or {}
    used_names = {item.get("name", "") for item in glb.doc.get("animations", [])}

    def warn(code, name, message):
        item = {"code": code, "name": name, "message": message}
        if item not in warnings:
            warnings.append(item)

    clips = [obj for obj in scene.env.objects if obj.type.name == "AnimationClip"]
    if len(clips) > MAX_CLIPS:
        warn("animation_limit", "", "Only the first 32 supplied animation clips are available in this preview.")
    for obj in clips[:MAX_CLIPS]:
        _check(deadline)
        name = scene.name(obj)
        checkpoint = (len(glb.data), len(glb.doc["accessors"]), len(glb.doc["bufferViews"]))
        try:
            clip = decode_clip(scene.tree(obj), deadline)
            times, outputs, morph_outputs, rebound, unbound, ambiguous = clip["times"], [], {}, False, 0, False
            visibility_tracks = []
            planned_frames, planned_values = 0, 0
            for track in clip["tracks"]:
                _check(deadline)
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
                    for sample_index, stamp in enumerate(times):
                        if sample_index % 128 == 0:
                            _check(deadline)
                        state = _evaluate(track["curves"][0], stamp) >= .5
                        if not states or state != states[-1]:
                            stamps.append(stamp - clip["start"])
                            states.append(state)
                    for node in targets:
                        if not 0 <= int(node) < len(glb.doc["nodes"]) or "mesh" not in glb.doc["nodes"][int(node)]:
                            raise AnimationError("Visibility animation must target an exported mesh, never a skeleton bone.")
                        visibility_tracks.append({"node": int(node), "times": stamps, "values": states,
                                                  "interpolation": "STEP", "sourceProperty": "GameObject.m_IsActive" if mode == "gameObject" else "Renderer.m_Enabled"})
                    continue
                if track["kind"] == "weights":
                    matches, moved = _morphs(morph_bindings, track["path"], track["attribute"])
                    rebound |= moved
                    if not matches:
                        unbound += 1
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
                        for sample_index, (row, stamp) in enumerate(zip(morph_outputs[node], times)):
                            if sample_index % 128 == 0:
                                _check(deadline)
                            row[index] = _evaluate(track["curves"][0], stamp) / 100.
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
                values = []
                for sample_index, stamp in enumerate(times):
                    if sample_index % 128 == 0:
                        _check(deadline)
                    values.append([_evaluate(curve, stamp) for curve in track["curves"]])
                kind = track["kind"]
                if kind in ("rotation", "euler"):
                    values = [_quaternion(row, kind == "euler") for row in values]
                    for previous, current in zip(values, values[1:]):
                        if sum(a*b for a, b in zip(previous, current)) < 0:
                            current[:] = [-value for value in current]
                    kind = "rotation"
                elif kind == "translation":
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
            frames = len(times) * len(outputs) + sum(len(row["times"]) for row in visibility_tracks)
            values = sum(len(row) for _, _, rows in outputs for row in rows) + sum(len(row["values"]) for row in visibility_tracks)
            if used_frames + frames > MAX_KEYFRAMES or used_values + values > MAX_VALUES:
                raise AnimationError("The supplied animations exceed the mobile preview keyframe limit.")
            if any(not 0 <= node < len(glb.doc["nodes"]) for node, _, _ in outputs):
                raise AnimationError("An animation points to an unavailable rig node.")
            if not outputs and not visibility_tracks:
                warn("animation_unbound", name, "This clip has no supported channels bound to the displayed rig.")
                continue
            relative_times = [stamp - clip["start"] for stamp in times]
            input_accessor = _attribute(glb, relative_times, "SCALAR", bounds=True) if outputs else None
            exported_name, suffix = clip["name"], 2
            while exported_name in used_names:
                exported_name = clip["name"] + "__" + str(suffix)
                suffix += 1
            animation = {"name": exported_name, "samplers": [], "channels": [],
                         "extras": {"loop": clip["loop"], "sourceSampling": clip["sampling"]}}
            for node, kind, rows in outputs:
                accessor = _attribute(glb, [value for row in rows for value in row] if kind == "weights" else rows,
                                      "SCALAR" if kind == "weights" else ("VEC4" if kind == "rotation" else "VEC3"))
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
                             "bindingComplete": not (clip["unsupported"] or unbound or ambiguous)})
            used_frames += frames
            used_values += values
            if clip["unsupported"] or unbound:
                warn("animation_partial", name, "Some visibility, material, humanoid or unmatched animation channels are unavailable.")
            if rebound:
                warn("animation_morph_path_rebound", name, "A facial curve used its unique original morph name because its legacy transform path differs.")
        except Exception as error:
            del glb.data[checkpoint[0]:]
            del glb.doc["accessors"][checkpoint[1]:]
            del glb.doc["bufferViews"][checkpoint[2]:]
            warn("animation_unavailable", name, str(error) if isinstance(error, AnimationError) else "This animation format could not be imported.")
    return {"clips": metadata, "warnings": warnings}
