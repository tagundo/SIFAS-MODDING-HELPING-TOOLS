"""Read verified stationary one-particle View billboards in stage and overlay prefabs."""

import math

from . import mv_studio_butterfly_glow as billboard, mv_studio_stage_dust as dust
from .mv_studio_stage_title_particles import _constant


_STATE = {**billboard._SETTINGS, "cullingMode": 1, "ringBufferLoopRange": {"x": 0, "y": 1}}
_MODULES = {"EmissionModule", "InitialModule", "SizeModule"}
_RENDERER = {**billboard._RENDERER, "m_RenderingLayerMask": 0xFFFFFFFF, "m_Flip": billboard._ZERO}


def _burst(emission, duration):
    rows = emission["m_Bursts"]
    if (emission["m_BurstCount"] != 1 or len(rows) != 1
            or any(_constant(emission[field]) != 0 for field in ("rateOverTime", "rateOverDistance"))):
        return None
    schedule, = rows
    cycles, period = schedule["cycleCount"], schedule["repeatInterval"]
    if (type(cycles) is not int or cycles not in (0, 1) or not dust._number(period, .001, 60)
            or schedule["time"] != 0 or schedule["probability"] != 1 or _constant(schedule["countCurve"]) != 1
            or cycles == 0 and math.ceil(duration / period) > 64):
        return None
    return {"count": 1, "time": 0, "cycles": cycles, "period": period}


def _atlas(source):
    if (not billboard._matches(source, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1,
                                       "tilesX": 4, "tilesY": 4, "randomRow": True, "rowIndex": 0,
                                       "flipU": 0, "flipV": 0})
            or not source["uvChannelMask"] & 1):
        return None
    start, frame = (_constant(source[key]) for key in ("startFrame", "frameOverTime"))
    if not all(dust._number(value, 0, 1) for value in (start, frame)):
        return None
    return {"start": [start, start], "frame": [frame, frame]}


def read(source, renderer, layer):
    if layer == 1:
        visual_module, blend, maximum, enabled = "ColorModule", "add", 3, True
    elif layer == 20:
        visual_module, blend, maximum, enabled = "UVModule", "alpha", .5, False
    else:
        return None
    active = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if (active != _MODULES | {visual_module}
            or not billboard._matches(renderer, {**_RENDERER, "m_MaxParticleSize": maximum,
                                                "m_EnableGPUInstancing": enabled, "m_ApplyActiveColorSpace": enabled})):
        return None
    duration, delay = source["lengthInSec"], _constant(source["startDelay"])
    seed, auto = source["randomSeed"], source["autoRandomSeed"]
    if (not billboard._matches(source, {**_STATE, "lengthInSec": duration})
            or not dust._number(duration, .01, 240) or not dust._number(delay, 0, 60)
            or type(auto) is not bool or type(seed) is not int or not -0x80000000 <= seed <= 0xFFFFFFFF):
        return None
    initial = source["InitialModule"]
    lifetime, size = (_constant(initial[key]) for key in ("startLifetime", "startSize"))
    cap, start = initial["maxNumParticles"], initial["startColor"]
    rgba = [start["maxColor"][channel] for channel in "rgba"]
    if (not billboard._matches(initial, {"rotation3D": True, "size3D": False, "randomizeRotationDirection": 0})
            or not dust._number(lifetime, .01, 5) or not dust._number(size, 0, 20)
            or type(cap) is not int or not 1 <= cap <= 16
            or start["minMaxState"] != 0 or any(not dust._number(value, 0, 1) for value in rgba)
            or any(_constant(initial[key]) != 0 for key in ("gravityModifier", "startSpeed", "startRotation",
                                                             "startRotationX", "startRotationY"))):
        return None
    burst, sizes = _burst(source["EmissionModule"], duration), dust._sizes(source["SizeModule"])
    if burst is None or sizes is None:
        return None
    row = {"kind": "stationaryBurst", "layer": layer, "blend": blend, "maxViewportWidth": maximum,
           "duration": duration, "delay": delay, "burst": burst, "maxParticles": cap,
           "lifetime": [lifetime, lifetime], "size": [size, size], "startColor": rgba,
           "sizeKeys": sizes[0], "sizeMultiplier": sizes[1], "autoSeed": auto, "seed": seed & 0xFFFFFFFF}
    if layer == 1:
        color = dust.color_over_life(source["ColorModule"]["gradient"])
        return {**row, "tiles": [1, 1], "colorOverLife": color} if color is not None else None
    atlas = _atlas(source["UVModule"])
    return {**row, "tiles": [4, 4], "atlas": atlas} if atlas is not None else None
