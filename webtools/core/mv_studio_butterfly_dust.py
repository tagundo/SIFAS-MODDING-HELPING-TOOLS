"""Read Aion Expert's two world-space butterfly finale dust emitters."""

import math

from . import model_viewer as viewer, mv_studio_butterfly_glow as glow, mv_studio_stage_title as title
from . import mv_studio_butterfly_shine as shine
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


_SETTINGS = {**shine._SETTINGS, "lengthInSec": _float32(1.3), "randomSeed": -1379653984}
_VIEWPORT_WIDTH = _float32(.12)
_RENDERER = {**shine._RENDERER, "m_EnableGPUInstancing": False, "m_ApplyActiveColorSpace": False,
             "m_MaxParticleSize": _VIEWPORT_WIDTH}
_ROLES = {"out_par_dust_add": "add", "out_par_dust": "alpha"}
_WHITE_CURVE = [[0, 1, 1, 1], [65535, 1, 1, 1]]


def _curve(source, count, *, size=False):
    keys = source["m_Curve"]
    if len(keys) != count or (source["m_PreInfinity"], source["m_PostInfinity"]) != (2, 2):
        return None
    rows, previous = [], -1
    for key in keys:
        stamp, value, incoming, outgoing = (key[name] for name in ("time", "value", "inSlope", "outSlope"))
        if (key["weightedMode"] or not 0 <= stamp <= 1 or stamp <= previous
                or not (-1 if not size else 0) <= value <= 1 or not -32 <= incoming <= 32
                or not (-32 <= outgoing <= 32 or size and outgoing == math.inf)):
            return None
        # Positive infinity is the native held tangent. Use JSON null to
        # distinguish a held segment from a finite cubic tangent.
        rows.append([stamp, value, incoming, None if outgoing == math.inf else outgoing])
        previous = stamp
    return rows


def _size_keys(module):
    curve = module["curve"]
    if module["separateAxes"] or (curve["minMaxState"], curve["minScalar"], curve["scalar"]) != (2, 1, 1):
        return None
    minimum = _curve(curve["minCurve"], 10, size=True)
    maximum = _curve(curve["maxCurve"], 12, size=True)
    if not minimum or not maximum or minimum[0][0] != 0 or maximum[0][0] != 0:
        return None
    return [minimum, maximum]


def _velocity(module):
    if (module["inWorldSpace"] or not shine._range(module["speedModifier"], .2, .5)
            or any(_constant(module[name]) != 0 for name in ("radial", "orbitalX", "orbitalY", "orbitalZ",
                                                            "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return None
    curves = []
    for axis, count, first, last in (("x", 4, -.2, .5), ("y", 2, .1, .6), ("z", 2, -.5, .5)):
        row = module[axis]
        scale = [row["minScalar"], row["scalar"]]
        if row["minMaxState"] != 2 or scale != [_float32(first), _float32(last)]:
            return None
        minimum, maximum = _curve(row["minCurve"], count), _curve(row["maxCurve"], count)
        if not minimum or not maximum or minimum[-1][0] != 1 or maximum[-1][0] != 1:
            return None
        curves.append({"min": minimum, "max": maximum, "scale": scale})
    return curves


def _start_color(source, role):
    if role == "alpha":
        color = [source["maxColor"][axis] for axis in "rgba"]
        return color if source["minMaxState"] == 0 and all(0 <= value <= 1 for value in color) else None
    if source["minMaxState"] != 3:
        return None
    minimum, maximum = source["minGradient"], source["maxGradient"]
    rgb = [shine._gradient(minimum, "ctime", 4, "rgb"), shine._gradient(maximum, "ctime", 5, "rgb")]
    alpha = [shine._gradient(minimum, "atime", 3, "a"), shine._gradient(maximum, "atime", 2, "a")]
    if not all(rgb) or not all(alpha):
        return None
    return {"rgb": rgb, "alpha": alpha}


def _profile(source, role):
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != shine._MODULES or not glow._matches(source, _SETTINGS) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    if (not glow._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 300,
                                   "randomizeRotationDirection": 0})
            or not shine._range(initial["startLifetime"], 1.2, 1.8) or not shine._range(initial["startSize"], .03, .05)
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "startRotation", "gravityModifier"))
            or not shine._sphere(source["ShapeModule"], .05)):
        return None
    emission = source["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (emission["m_BurstCount"] != 2 or len(bursts) != 2
            or any(_constant(emission[name]) != 0 for name in ("rateOverTime", "rateOverDistance"))
            or any(not glow._matches(row, {"time": stamp, "cycleCount": 1, "probability": 1})
                   or _constant(row["countCurve"]) != count for row, (stamp, count) in zip(bursts, ((0, 40), (_float32(.3), 20))))):
        return None
    sheet = source["UVModule"]
    if (not glow._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 4, "tilesY": 4,
                                 "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or not shine._range(sheet["startFrame"], 0, .09375)):
        return None
    gradient = source["ColorModule"]["gradient"]
    maximum = gradient["maxGradient"]
    rgba_keys = shine._gradient(maximum, "atime", 3, "a")
    if gradient["minMaxState"] != 1 or shine._gradient(maximum, "ctime", 2, "rgb") != _WHITE_CURVE or not rgba_keys:
        return None
    alpha = [[stamp, int(_float32(_float32(value * 255) + .5))] for stamp, value in rgba_keys]
    size, velocity = _size_keys(source["SizeModule"]), _velocity(source["VelocityModule"])
    color = _start_color(initial["startColor"], role)
    if size is None or velocity is None or color is None or alpha[0][0] != 0 or alpha[-1][0] != 65535:
        return None
    return {"sizeKeys": size, "velocity": velocity, "alphaKeys": alpha}, color


def read(objects, ctrl, fields, deadline, *, activations):
    """Return the coupled dust descriptor and its single original atlas reader."""
    try:
        viewer._remaining(deadline)
        activation = activations.get("out_par_dust_add")
        if activation is None or activation != activations.get("out_par_dust"):
            return None
        shared, texture, emitters = None, None, []
        for name, role in _ROLES.items():
            game = glow._child(objects, ctrl, fields, name)
            parts = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"},
                                      layer=1) if game is not None else None
            if parts is None:
                return None
            components = parts[1]
            _, transform = components["Transform"]
            renderer, type_tree = components["ParticleSystemRenderer"]
            if (transform["m_Children"] or _authored_trs(transform) != title._IDENTITY
                    or not glow._matches(type_tree, _RENDERER)):
                return None
            profile = _profile(components["ParticleSystem"][1], role)
            atlas = glow._material_texture(objects, renderer, type_tree, alpha=role == "alpha")
            if profile is None or atlas is None:
                return None
            common, color = profile
            if (shared is not None and shared != common
                    or texture is not None and viewer._key(texture) != viewer._key(atlas)):
                return None
            shared, texture = common, atlas
            emitters.append({"role": role, "startColor": color,
                             "material": {"tint": [1, 1, 1, 1], "queue": 3010, "cull": 0,
                                          "blend": role, "premultiply": False}})
        return {**shared, "profile": "finale", "activation": activation, "position": [0, 0, 0],
                "maxViewportWidth": _VIEWPORT_WIDTH, "uv": [.25, .25, 0, 0], "emitters": emitters}, texture
    except title._UNSUPPORTED:
        return None
