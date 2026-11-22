"""Validate the authored particle roles in Aion's layered momiji display."""

import math

from . import mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from . import mv_studio_transition_red_burst as red_burst
from .mv_studio_stage_title_particles import _constant, _float32


_STATE = {**billboard._SETTINGS, "playOnAwake": False}
_WHITE_RGB = [[0, 1, 1, 1], [65535, 1, 1, 1]]
_WHITE_ALPHA = [[0, 1], [65535, 1]]
_FLASH_ALPHA = [[0, 0], [14649, 1], [42887, 1], [65535, 0]]
_LEAF_ALPHA = [[0, 0], [2602, 1], [50501, 1], [65535, 0]]
_SEED = 1586243424
_FAN_SEED = 1498035885


def _modules(source, expected, **state):
    enabled = {name for name, module in source.items() if name.endswith("Module") and module.get("enabled")}
    return enabled == expected and billboard._matches(source, {**_STATE, **state})


def _emission(module, expected):
    bursts = module["m_Bursts"]
    if (not len(bursts) == module["m_BurstCount"] == len(expected)
            or any(_constant(module[name]) != 0 for name in ("rateOverTime", "rateOverDistance"))):
        return False
    return all(billboard._matches(burst, {"time": _float32(stamp), "cycleCount": cycles, "probability": 1,
                                         "repeatInterval": _float32(interval)})
               and _constant(burst["countCurve"]) == count
               for burst, (stamp, cycles, interval, count) in zip(bursts, expected))


def _alpha(source, expected):
    value = source["ColorModule"]["gradient"]
    maximum = value["maxGradient"]
    return (value["minMaxState"] == 1 and shine._gradient(maximum, "ctime", 2, "rgb") == _WHITE_RGB
            and shine._gradient(maximum, "atime", len(expected), "a") == expected)


def _initial(source, *, size_3d=False, rotation_3d=False):
    return billboard._matches(source, {"size3D": size_3d, "rotation3D": rotation_3d, "maxNumParticles": 1000,
                                       "randomizeRotationDirection": 0})


def flash(source):
    if (not _modules(source, {"InitialModule", "EmissionModule", "ColorModule"}, lengthInSec=1,
                     autoRandomSeed=True, randomSeed=0)
            or _constant(source["startDelay"]) != 0 or not _emission(source["EmissionModule"], ((0, 1, .01, 1),))
            or not _alpha(source, _FLASH_ALPHA)):
        return None
    initial = source["InitialModule"]
    color = initial["startColor"]
    rgba = [color["maxColor"][axis] for axis in "rgba"]
    if (not _initial(initial) or color["minMaxState"] != 0 or rgba != [1, _float32(.35982987), 0, 1]
            or _constant(initial["startSize"]) != 15 or _constant(initial["startLifetime"]) != 1
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "gravityModifier", "startRotation",
                                                              "startRotationX", "startRotationY"))):
        return None
    return {"startColor": rgba, "alphaKeys": _FLASH_ALPHA, "size": 15, "lifetime": 1, "uv": [1, 1, 0, 0]}


def leaf(source, *, green):
    state = {"ColorModule", "EmissionModule", "InitialModule", "RotationModule", "ShapeModule", "SizeModule", "UVModule"}
    delay = _float32(.05 if green else .1)
    if (not _modules(source, state, lengthInSec=4, cullingMode=3, autoRandomSeed=False, randomSeed=_SEED)
            or _constant(source["startDelay"]) != delay or not _alpha(source, _LEAF_ALPHA)):
        return None
    initial = source["InitialModule"]
    life = (.3, .7) if green else (.5, 1)
    if (not _initial(initial, rotation_3d=True) or _constant(initial["gravityModifier"]) != _float32(.1)
            or any(not shine._range(initial[name], *bounds) for name, bounds in (
                ("startLifetime", life), ("startSize", (5, 7)), ("startSpeed", (6, 10)), ("startRotation", (0, 0)),
                ("startRotationX", (0, 0)), ("startRotationY", (0, leaves._PI_OVER_TWO))))):
        return None
    rotation, size, shape = source["RotationModule"], source["SizeModule"], source["ShapeModule"]
    curve = size["curve"]
    if (not rotation["separateAxes"] or not shine._range(rotation["curve"], 5.235987663269043, -5.235987663269043)
            or any(not shine._range(rotation[name], 0, 0) for name in ("x", "y"))
            or size["separateAxes"] or (curve["minMaxState"], curve["minScalar"], curve["scalar"]) != (1, 1, 1)
            or curve["minCurve"]["m_Curve"] or not leaves._keyframes_match(curve["maxCurve"], red_burst._SIZE)
            or shape["angle"] != _float32(1.27) or shape["length"] != _float32(1.43)
            or not leaves._shape(shape, shape_type=8, scale=(_float32(4.36), _float32(.24), 2 if green else 1),
                                 rotation=(-90, 0, 0), radius=_float32(.9), arc_mode=3)):
        return None
    bursts = ((0, 1, .01, 25), (.1, 3, .12, 15), (.4, 1, .12, 5)) if green else ((.1, 3, .15, 10),)
    atlas = [.25, .25, .75 if green else .25, .25]
    initial_color = initial["startColor"]
    sheet = source["UVModule"]
    if (not _emission(source["EmissionModule"], bursts) or not _sheet(sheet, 4, 4)
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != (.4375 if green else .3125)):
        return None
    if green:
        rgb = shine._gradient(initial_color["maxGradient"], "ctime", 4, "rgb")
        alpha = shine._gradient(initial_color["maxGradient"], "atime", 2, "a")
        if initial_color["minMaxState"] != 1 or not rgb or alpha != _WHITE_ALPHA:
            return None
        color = {"rgb": rgb, "alpha": alpha}
    else:
        if not billboard._matches(initial_color, {"minMaxState": 0, "maxColor": billboard._WHITE}):
            return None
        color = [1, 1, 1, 1]
    return {"seed": _SEED, "startColor": color, "alphaKeys": _LEAF_ALPHA, "uv": atlas}


def _sheet(source, columns, rows):
    return (billboard._matches(source, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": columns,
                                       "tilesY": rows, "flipU": 0, "flipV": 0})
            and source["uvChannelMask"] & 1)


def _fan_burst(module):
    if (module["m_BurstCount"] != 1 or any(_constant(module[name]) != 0 for name in ("rateOverTime", "rateOverDistance"))):
        return False
    burst, = module["m_Bursts"]
    count = burst["countCurve"]
    curve = count["maxCurve"]
    keys = curve["m_Curve"]
    expected = ((0, 1, math.inf, math.inf), (.10654573142528534, .7241373658180237, math.inf, math.inf))
    return (billboard._matches(burst, {"time": 0, "cycleCount": 2, "probability": 1, "repeatInterval": .25})
            and (count["minMaxState"], count["minScalar"], count["scalar"]) == (1, 30, 5)
            and not count["minCurve"]["m_Curve"] and leaves._keyframes_match(curve, expected)
            and all(key["inWeight"] == key["outWeight"] == 0 for key in keys))


def fan(source):
    modules = {"ClampVelocityModule", "EmissionModule", "InitialModule", "RotationModule", "ShapeModule", "UVModule"}
    if (not _modules(source, modules, lengthInSec=5, autoRandomSeed=False, randomSeed=_FAN_SEED)
            or _constant(source["startDelay"]) != 0 or not _fan_burst(source["EmissionModule"])):
        return None
    initial = source["InitialModule"]
    if (not _initial(initial, size_3d=True)
            or not billboard._matches(initial["startColor"], {"minMaxState": 0, "maxColor": billboard._WHITE})
            or any(_constant(initial[name]) != value for name, value in (
                ("startLifetime", _float32(1.3)), ("startSize", 4), ("startSizeY", 2), ("startSizeZ", 1),
                ("gravityModifier", 0)))
            or any(not shine._range(initial[name], *bounds) for name, bounds in (
                ("startSpeed", (12, 15)), ("startRotation", (-_float32(.52359879), _float32(.52359879))),
                ("startRotationX", (0, 0)), ("startRotationY", (0, 0))))):
        return None
    rotation, shape, clamp = source["RotationModule"], source["ShapeModule"], source["ClampVelocityModule"]
    magnitude = clamp["magnitude"]
    turn = 3.141592502593994
    if (rotation["separateAxes"] or not shine._range(rotation["curve"], -turn, turn)
            or shape["angle"] != 0 or shape["length"] != 5
            or not leaves._shape(shape, shape_type=4, scale=(_float32(3.93), 0, _float32(.11)), rotation=(-90, 0, 0))
            or not billboard._matches(clamp, {"dampen": _float32(.03), "separateAxis": False, "inWorldSpace": False,
                                              "multiplyDragByParticleSize": True, "multiplyDragByParticleVelocity": True})
            or _constant(clamp["drag"]) != 0
            or (magnitude["minMaxState"], magnitude["minScalar"], magnitude["scalar"]) != (1, 1, 1)
            or magnitude["minCurve"]["m_Curve"] or not leaves._keyframes_match(
                magnitude["maxCurve"], ((0, 1, -2, -2), (1, .16091954708099365, 0, 0)))):
        return None
    sheet = source["UVModule"]
    if (not _sheet(sheet, 1, 2) or _constant(sheet["frameOverTime"]) != _float32(.9999)
            or not shine._range(sheet["startFrame"], 0, .75)):
        return None
    return {"seed": _FAN_SEED, "tiles": [1, 2], "pivot": [0, .5, 0]}
