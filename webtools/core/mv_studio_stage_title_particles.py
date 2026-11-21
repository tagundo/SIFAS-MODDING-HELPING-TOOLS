"""Describe deterministic, stationary particle billboards in native display titles."""

from bisect import bisect_left
import math
import struct

from . import model_animation as animation
from . import mv_studio_stage_title as title
from .model_rig import _authored_trs


_MODES = {"InitialModule", "EmissionModule", "UVModule", "ColorModule", "SizeModule"}
_PARTICLE = {"ParticleSystem", "ParticleSystemRenderer"}
_ONE = ("constant", 1)
_WORD_MASK = (1 << 32) - 1


def _number(value, minimum, maximum):
    return type(value) in (int, float) and minimum <= value <= maximum


def _constant(value):
    if value.get("minMaxState") == 0 and math.isfinite(value["scalar"]):
        return value["scalar"]
    return None


def _scalar(value, deadline, *, through=1):
    mode, multiplier = value.get("minMaxState"), value["scalar"]
    if not _number(multiplier, 0, 16):
        return None
    if mode == 0:
        return "constant", multiplier
    if mode != 1:
        return None
    source = value["maxCurve"]
    keys = source["m_Curve"]
    if (not 0 < len(keys) <= 32 or source["m_PreInfinity"] != 2
            or any(not _number(key["time"], 0, 1) or not _number(key["value"], 0, 16) for key in keys)
            or any(before["time"] >= after["time"] for before, after in zip(keys, keys[1:]))):
        return None
    # A GameObject that deactivates before the last key never evaluates the authored post wrap.
    if source["m_PostInfinity"] != 2 and through > keys[-1]["time"]:
        return None
    mode, rows = animation._editor_scalar(keys, deadline=deadline)
    return mode, [(stamp, [value * multiplier for value in coefficients]) for stamp, coefficients in rows]


def _color(initial, module):
    start = initial["startColor"]
    multiplier = [start["maxColor"][axis] for axis in "rgba"]
    if start.get("minMaxState") != 0 or not all(_number(value, 0, 1) for value in multiplier):
        return None
    if not module.get("enabled"):
        return {"rgb": [[0, *multiplier[:3]]], "alpha": [[0, multiplier[3]]]}
    source = module["gradient"]
    grad = source["maxGradient"]
    # Unity serializes RGB and alpha gradient positions separately as unsigned 16-bit values.
    if source["minMaxState"] != 1 or grad["m_Mode"] != 0:
        return None
    groups = {}
    for name, fields, prefix, count, first in (("rgb", "rgb", "ctime", "m_NumColorKeys", 0),
                                                ("alpha", "a", "atime", "m_NumAlphaKeys", 3)):
        if not 0 < grad[count] <= 8:
            return None
        rows, previous = [], -1
        for index in range(grad[count]):
            stamp = grad[f"{prefix}{index}"]
            values = [grad[f"key{index}"][axis] for axis in fields]
            if not _number(stamp, 0, 65535) or stamp <= previous or not all(_number(value, 0, 1) for value in values):
                return None
            rows.append([stamp / 65535, *[value * multiplier[first + idx] for idx, value in enumerate(values)]])
            previous = stamp
        groups[name] = rows
    return groups


def _atlas(uv, deadline, through):
    if (not uv["enabled"] or uv["mode"] != 0 or uv["timeMode"] != 0 or uv["animationType"] not in (0, 1)
            or uv["cycles"] != 1 or uv["randomRow"] or uv["flipU"] or uv["flipV"] or not (uv["uvChannelMask"] & 1)
            or _constant(uv["startFrame"]) != 0 or not all(1 <= uv[key] <= 8 for key in ("tilesX", "tilesY"))):
        return None
    tiles = [uv["tilesX"], uv["tilesY"]]
    row = uv["rowIndex"] if uv["animationType"] == 1 else None
    frame = _scalar(uv["frameOverTime"], deadline, through=through)
    if frame is None or (row is not None and not 0 <= row < tiles[1]):
        return None
    return {"tiles": tiles, "row": row, "frame": frame}


def _float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _native_draws(seed, count):
    # Unity's InitialModule uses independent SIMD lanes of this xorshift state.
    state = [seed & _WORD_MASK]
    for _ in range(3):
        state.append((state[-1] * 0x6c078965 + 1) & _WORD_MASK)
    for _ in range(count):
        first = (state[0] ^ (state[0] << 11)) & _WORD_MASK
        last = state[-1]
        value = first ^ (first >> 8) ^ last ^ (last >> 19)
        yield value
        state = [*state[1:], value]


def _native_unit(word):
    return _float32((word & 0x7fffff) * _float32(1 / 0x7fffff))


def _native_lerp(first, last, weight):
    return _float32(first + _float32(_float32(last - first) * weight))


def _constant_range(source, low, high):
    values = source["minScalar"], source["scalar"]
    return values if source["minMaxState"] == 3 and all(_number(value, low, high) for value in values) else None


def _stepped_curve(source, deadline, *, wrap=2):
    post = source["m_PostInfinity"]
    keys = source["m_Curve"]
    loop_at_lifetime = wrap == 2 and post == 1 and keys and keys[-1]["time"] == 1
    if post != wrap and not loop_at_lifetime:
        return None
    curve = _scalar({"minMaxState": 1, "scalar": 1, "maxCurve": source}, deadline, through=0)
    # Long stepped curves use the original evaluator instead of Unity's two-segment approximation.
    if curve is None or len(curve[1]) < 4 or any(any(coefficients[:3]) for _, coefficients in curve[1]):
        return None
    return curve


def _fixed_random_color(start, unit):
    gradient = start["maxGradient"]
    if start["minMaxState"] != 4 or gradient["m_Mode"] != 1:
        return None
    stamp = _float32(unit * 65535)
    color = []
    for fields, prefix, count in (("rgb", "ctime", "m_NumColorKeys"), ("a", "atime", "m_NumAlphaKeys")):
        if not 2 <= gradient[count] <= 8:
            return None
        times = [gradient[f"{prefix}{index}"] for index in range(gradient[count])]
        if (not all(_number(time, 0, 65535) for time in times)
                or any(first >= last for first, last in zip(times, times[1:]))):
            return None
        key = gradient[f"key{min(bisect_left(times, stamp), len(times)-1)}"]
        values = [key[field] for field in fields]
        if not all(_number(value, 0, 1) for value in values):
            return None
        color.extend(int(_float32(_float32(value * 255) + .5)) / 255 for value in values)
    return {"rgb": [[0, *color[:3]]], "alpha": [[0, color[3]]]}


def _fixed_seed_pair(source, deadline):
    initial, size, uv = source["InitialModule"], source["SizeModule"], source["UVModule"]
    if (source["autoRandomSeed"] or source["randomSeed"] != 0 or initial["size3D"]
            or source["cullingMode"] != 0 or initial["maxNumParticles"] < 2
            or source["ColorModule"]["enabled"] or not size["enabled"] or size["separateAxes"]):
        return None
    life = _constant_range(initial["startLifetime"], .01, 10)
    dimensions = _constant_range(initial["startSize"], .01, 32)
    motion, frame = size["curve"], uv["frameOverTime"]
    if (life is None or dimensions is None or motion["minMaxState"] != 2 or not _number(motion["scalar"], 0, 16)
            or frame["minMaxState"] != 1 or not 0 < frame["scalar"] < 1
            or (uv["tilesX"], uv["tilesY"], uv["animationType"]) != (2, 4, 0)):
        return None
    minimum = _stepped_curve(motion["minCurve"], deadline)
    maximum = _stepped_curve(motion["maxCurve"], deadline)
    animation_frame = _stepped_curve(frame["maxCurve"], deadline, wrap=1)
    if minimum is None or maximum is None or animation_frame is None:
        return None
    keys = animation_frame[1]
    atlas = _atlas(uv, deadline, 0)
    if atlas is None or keys[0][0] != 0 or keys[-1][0] != .5 or any(row[3] > 1 for _, row in keys):
        return None
    atlas["period"] = .5
    atlas["frame"] = ("cubic", [(stamp, [0, 0, 0, _float32(row[3] * frame["scalar"])]) for stamp, row in keys])
    stamps = sorted({stamp for curve in (minimum, maximum) for stamp, _ in curve[1]})
    loop_min = motion["minCurve"]["m_PostInfinity"] == 1
    loop_max = motion["maxCurve"]["m_PostInfinity"] == 1
    records = []
    for lane in range(2):
        # Native births advance two different lanes, including the unused draw before color.
        seed, lifetime, width, _, color = _native_draws(367 * lane, 5)
        color = _fixed_random_color(initial["startColor"], _native_unit(color))
        if color is None:
            return None
        # Size over lifetime resamples a salted copy of each particle's own seed.
        weight = _native_unit(next(_native_draws(seed + 0x8d2c8431, 1)))
        values = []
        for stamp in stamps:
            first = _float32(animation._evaluate(minimum, 0 if loop_min and stamp == 1 else stamp) * motion["scalar"])
            last = _float32(animation._evaluate(maximum, 0 if loop_max and stamp == 1 else stamp) * motion["scalar"])
            values.append((stamp, [0, 0, 0, max(0, _native_lerp(first, last, weight))]))
        curve = ("cubic", values)
        size_start = _native_lerp(*dimensions, _native_unit(width))
        records.append({"size": [size_start, size_start], "sizeCurves": [curve, curve],
                        "lifetime": _native_lerp(*life, _native_unit(lifetime)), "atlas": atlas, "color": color})
    return records


def _emitter(objects, particle, renderer, window, deadline, *, allow_pair):
    _, source = particle
    obj, render = renderer
    if (not render["m_Enabled"] or render["m_RenderMode"] != 0 or render["m_RenderAlignment"] != 2
            or render["m_UseCustomVertexStreams"] or not render["m_ApplyActiveColorSpace"]
            or render["m_MinParticleSize"] != 0 or render["m_MaxParticleSize"] != 5
            or render["m_Pivot"] != dict(x=0, y=0, z=0)
            or any(render[key] for key in ("m_SortMode", "m_SortingOrder", "m_SortingLayerID"))
            or any(render[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3"))):
        return None
    refs = render["m_Materials"]
    if len(refs) != 2 or refs[0] != refs[1]:
        return None
    material = title._local(objects, obj, refs[0], "Material")
    surface = title._material(objects, material) if material is not None else None
    if surface is None:
        return None
    if (not source["playOnAwake"] or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or _constant(source["startDelay"]) != 0 or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                            "ringBufferMode", "stopAction"))):
        return None
    enabled = {name for name, data in source.items() if name.endswith("Module") and data.get("enabled")}
    if not {"InitialModule", "EmissionModule", "UVModule"} <= enabled <= _MODES:
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    if (initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(initial[key]) != 0 for key in ("startSpeed", "startRotation", "gravityModifier"))
            or _constant(emission["rateOverTime"]) != 0 or _constant(emission["rateOverDistance"]) != 0
            or emission["m_BurstCount"] != 1 or len(emission["m_Bursts"]) != 1):
        return None
    burst, = emission["m_Bursts"]
    if burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1:
        return None
    fields, texture = surface
    count = _constant(burst["countCurve"])
    if count == 2 and allow_pair and window == [0, None]:
        records = _fixed_seed_pair(source, deadline)
        return ([{**record, "material": fields} for record in records], texture) if records else None
    if count != 1:
        return None
    lifetime, width = (_constant(initial[key]) for key in ("startLifetime", "startSize"))
    height = _constant(initial["startSizeY"]) if initial["size3D"] else width
    if not _number(lifetime, .01, 10) or not all(_number(size, .01, 32) for size in (width, height)):
        return None
    size = source["SizeModule"]
    sx = _scalar(size["curve"], deadline) if size["enabled"] else _ONE
    sy = _scalar(size["y"], deadline) if size["enabled"] and size["separateAxes"] else sx
    first, last = window
    through = min(1, (last - first) / lifetime) if last is not None else 1
    atlas, color = _atlas(source["UVModule"], deadline, through), _color(initial, source["ColorModule"])
    if sx is None or sy is None or atlas is None or color is None:
        return None
    return [{"material": fields, "size": [width, height], "sizeCurves": [sx, sy], "lifetime": lifetime,
             "atlas": atlas, "color": color}], texture


def _window(active, curve):
    if curve is None:
        return [0, None] if active else None
    mode, rows = curve
    if mode != "cubic" or not rows:
        return None
    states = []
    for time, values in rows:
        value = values[3]
        if value not in (0, 1) or any(values[:3]):
            return None
        if time <= 0:
            states = [(0, bool(value))]
        elif not states or states[-1][1] != bool(value):
            states.append((time, bool(value)))
    if not states or states[0] != (0, active):
        return None
    if not active:
        states.pop(0)
    if not states or len(states) > 2 or not states[0][1] or (len(states) == 2 and states[1][1]):
        return None
    return [states[0][0], states[1][0] if len(states) == 2 else None]


def _pivot(objects, game):
    root = title._components(objects, game, {"Transform"})
    if root is None:
        return None
    transform, fields = root[1]["Transform"]
    if _authored_trs(fields) != title._IDENTITY or (fields.get("m_Father") or {}).get("m_PathID"):
        return None
    child, = fields["m_Children"]
    return title._transform_child(objects, transform, child)


def read(objects, game, deadline, *, preserve_seed=False):
    pivot = _pivot(objects, game)
    if pivot is None:
        return None
    for scope in ({"Transform", "Animator"}, {"Transform", "Animator", *_PARTICLE}, {"Transform"}):
        result = title._components(objects, pivot, scope)
        if result is not None:
            break
    if result is None:
        return None
    _, components = result
    if "ParticleSystem" in components:
        settings = components["ParticleSystem"][1]
        invisible = components["ParticleSystemRenderer"][1]
        if (invisible["m_Enabled"] or any(ref["m_PathID"] for ref in invisible["m_Materials"])
                or any(value.get("enabled") for key, value in settings.items()
                       if key.endswith("Module") and key != "InitialModule")):
            return None
    transform, fields = components["Transform"]
    if _authored_trs(fields) != title._IDENTITY or not 0 < len(fields["m_Children"]) <= 6:
        return None
    emitters, meshes, paths = {}, set(), set()
    for ref in fields["m_Children"]:
        child = title._transform_child(objects, transform, ref)
        if child is None:
            return None
        row = title._components(objects, child, {"Transform", *_PARTICLE}, require_active=False)
        if row is None:
            mesh = title._mesh(objects, child)
            if mesh is None or mesh[0]["path"] in paths:
                return None
            paths.add(mesh[0]["path"])
            meshes.add(mesh[0]["path"])
            continue
        child_fields, parts = row
        name, tr = child_fields["m_Name"], parts["Transform"][1]
        path = animation.path_hash(name)
        if tr["m_Children"] or path in paths or not 0 < len(name) <= 96 or not name.isprintable() or "/" in name:
            return None
        paths.add(path)
        emitters[path] = name, tr, parts, child_fields["m_IsActive"]
    if not emitters:
        return None
    visibility = {}
    if "Animator" in components:
        motion = title._animator(objects, *components["Animator"], deadline)
        if motion is None:
            return None
        clip, cost = motion
        if clip["start"] != 0 or not 0 < clip["duration"] <= 15 or clip["loop"] or cost > 4096:
            return None
        for channel in clip["channels"]:
            path, kind = channel["path"], channel["kind"]
            if path in emitters and kind == "visibility" and channel["visibilityType"] == "gameObject":
                visibility[path] = channel["curves"][0]
            elif path not in meshes or kind not in {"translation", "overlayTint", "overlayUV"}:
                return None
    result = []
    allow_pair = preserve_seed and "Animator" not in components and len(emitters) == 1 and not meshes
    for path, (name, tr, parts, active) in emitters.items():
        window = _window(active, visibility.get(path))
        if window is None:
            return None
        emitter = _emitter(objects, parts["ParticleSystem"], parts["ParticleSystemRenderer"], window, deadline,
                           allow_pair=allow_pair)
        if emitter is None:
            return None
        descriptors, texture = emitter
        trs = _authored_trs(tr)
        for descriptor in descriptors:
            descriptor.update(name=name, active=window, position=trs["translation"], rotation=trs["rotation"],
                              scale=trs["scale"])
            result.append((descriptor, texture))
    return result
