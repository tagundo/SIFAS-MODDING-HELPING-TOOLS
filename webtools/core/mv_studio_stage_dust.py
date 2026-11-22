"""Validate the native local Box5 dust simulation used by stage billboards."""

import math

from . import mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from .mv_studio_stage_title_particles import _constant


RENDERER = {**billboard._RENDERER, "m_RenderingLayerMask": 0xFFFFFFFF, "m_EnableGPUInstancing": False,
            "m_ApplyActiveColorSpace": False, "m_Flip": billboard._ZERO}
_STATE = {**billboard._SETTINGS, "looping": True, "cullingMode": 1, "ringBufferLoopRange": {"x": 0, "y": 1}}
_MODULES = {"EmissionModule", "InitialModule", "ShapeModule", "SizeModule", "VelocityModule"}
_SHEET_MODULES = _MODULES | {"ColorModule", "UVModule"}
_SHEET_STATE = {**_STATE, "lengthInSec": 3, "cullingMode": 3}


def _number(value, low, high):
    return type(value) in (int, float) and low <= value <= high


def _range(source, low, high):
    values = [source["minScalar"], source["scalar"]]
    return values if source["minMaxState"] == 3 and all(_number(value, low, high) for value in values) else None


def _axis_keys(curve):
    keys = curve["m_Curve"]
    if ((curve["m_PreInfinity"], curve["m_PostInfinity"]) != (2, 2) or len(keys) != 2
            or any(key["time"] != i or key["weightedMode"] or key["inSlope"] or key["outSlope"]
                   or not _number(key["value"], -16, 16) for i, key in enumerate(keys))):
        return None
    return [key["value"] for key in keys]


def _velocity(source):
    if (source["inWorldSpace"] or _constant(source["speedModifier"]) != 1
            or any(_constant(source[name]) != 0 for name in ("radial", "orbitalX", "orbitalY", "orbitalZ",
                                                               "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return None
    axes = []
    for axis in "xyz":
        curve = source[axis]
        minimum, maximum = (_axis_keys(curve[key]) for key in ("minCurve", "maxCurve"))
        if curve["minMaxState"] != 2 or not _number(curve["scalar"], 0, 4) or minimum is None or maximum is None:
            return None
        axes.append([*minimum, *maximum, curve["scalar"]])
    return axes


def _sizes(source):
    curve = source["curve"]
    maximum = curve["maxCurve"]
    keys = maximum["m_Curve"]
    if (source["separateAxes"] or curve["minMaxState"] != 1 or not _number(curve["scalar"], 0, 16)
            or curve["minCurve"]["m_Curve"] or (maximum["m_PreInfinity"], maximum["m_PostInfinity"]) != (2, 2)
            or not 2 <= len(keys) <= 16 or keys[0]["time"] != 0 or keys[-1]["time"] != 1
            or len(keys) <= 3 and curve["scalar"] != 1):
        return None
    rows = []
    for key in keys:
        stamp, size, enter, exit = (key[name] for name in ("time", "value", "inSlope", "outSlope"))
        if (key["weightedMode"] or not _number(stamp, 0, 1) or not _number(size, 0, 16)
                or rows and stamp <= rows[-1][0]
                or any(not (_number(slope, -4096, 4096) or slope == math.inf) for slope in (enter, exit))):
            return None
        rows.append([stamp, size, None if enter == math.inf else enter, None if exit == math.inf else exit])
    return rows, curve["scalar"]


def _color_keys(source, prefix, channels):
    count = source["m_NumColorKeys" if prefix == "ctime" else "m_NumAlphaKeys"]
    rows = shine._gradient(source, prefix, count, channels) if type(count) is int and 2 <= count <= 8 else None
    return rows if rows and rows[0][0] == 0 and rows[-1][0] == 65535 else None


def _sprite_fields(source):
    color = source["ColorModule"]["gradient"]
    if color["minMaxState"] != 1:
        return None
    gradient = color["maxGradient"]
    rgb, alpha = _color_keys(gradient, "ctime", "rgb"), _color_keys(gradient, "atime", "a")
    if rgb is None or alpha is None:
        return None
    uv = source["UVModule"]
    if (not billboard._matches(uv, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 2, "tilesY": 2,
                                   "flipU": 0, "flipV": 0, "randomRow": True, "rowIndex": 0})
            or not uv["uvChannelMask"] & 1):
        return None
    frames = _range(uv["frameOverTime"], 0, 1)
    fixed = _constant(uv["startFrame"])
    start = [fixed, fixed] if _number(fixed, 0, 1) else _range(uv["startFrame"], 0, 1)
    if frames is None or start is None:
        return None
    return {"tiles": [2, 2], "colorOverLife": {"rgb": rgb, "alpha": alpha},
            "atlas": {"start": start, "frame": frames}}


def read(source, *, max_viewport_width=1):
    active = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if active == _MODULES and max_viewport_width == 1:
        state, visual = _STATE, {"tiles": [1, 1]}
        gravity = _constant(source["InitialModule"]["gravityModifier"])
        if not _number(gravity, 0, 1):
            return None
        gravity_fields = {"gravity": gravity}
    elif active == _SHEET_MODULES and max_viewport_width in (1, 2):
        state, visual = _SHEET_STATE, _sprite_fields(source)
        gravity_range = _range(source["InitialModule"]["gravityModifier"], 0, 1)
        if visual is None or gravity_range is None:
            return None
        gravity_fields = {"gravityRange": gravity_range}
    else:
        return None
    seed, auto = source["randomSeed"], source["autoRandomSeed"]
    if (not billboard._matches(source, state) or type(auto) is not bool
            or type(seed) is not int or not -0x80000000 <= seed <= 0xFFFFFFFF or _constant(source["startDelay"]) != 0):
        return None
    initial = source["InitialModule"]
    lifetime, size = _range(initial["startLifetime"], .1, 5), _range(initial["startSize"], 0, 20)
    cap, color = initial["maxNumParticles"], initial["startColor"]
    rgba = [color["maxColor"][channel] for channel in "rgba"]
    if (not billboard._matches(initial, {"rotation3D": False, "size3D": False, "randomizeRotationDirection": 0})
            or lifetime is None or size is None or type(cap) is not int or not 1 <= cap <= 512
            or color["minMaxState"] != 0 or any(not _number(value, 0, 1) for value in rgba)
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "startRotation"))):
        return None
    emission = source["EmissionModule"]
    rate = _constant(emission["rateOverTime"])
    max_rate = 180 if active == _SHEET_MODULES else 120
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or not _number(rate, 0, max_rate) or rate == 0):
        return None
    shape = source["ShapeModule"]
    dims = [shape["m_Scale"][axis] for axis in "xyz"]
    if (any(not _number(value, 0, 100) for value in dims)
            or not leaves._shape(shape, scale=dims, radius=.5, arc_value=1)):
        return None
    velocity, sizes = _velocity(source["VelocityModule"]), _sizes(source["SizeModule"])
    if velocity is None or sizes is None:
        return None
    return {"kind": "boxDust", **visual, **gravity_fields, "maxViewportWidth": max_viewport_width,
            "maxParticles": cap, "rate": rate, "duration": source["lengthInSec"], "lifetime": lifetime,
            "size": size, "shapeScale": dims, "velocity": velocity, "sizeKeys": sizes[0], "sizeMultiplier": sizes[1],
            "startColor": rgba, "autoSeed": auto, "seed": seed & 0xFFFFFFFF}
