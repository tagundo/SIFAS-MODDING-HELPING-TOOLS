"""Read the world-space par_shine emitter under Aion's first Expert butterfly."""

import math

from . import model_viewer as viewer, mv_studio_butterfly_glow as glow, mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


_MODULES = glow._MODULES | {"ShapeModule", "ColorModule", "VelocityModule"}
_SETTINGS = {**glow._SETTINGS, "lengthInSec": 15, "moveWithTransform": 1, "cullingMode": 3,
             "autoRandomSeed": False, "randomSeed": 727550837}
_RENDERER = {**glow._RENDERER, "m_RenderingLayerMask": 0xFFFFFFFF, "m_MaxParticleSize": .5, "m_Flip": glow._ZERO}
_POSITION = [-_float32(.02), -_float32(.0369), 0]


def _range(source, first, last):
    return (source["minMaxState"], source["minScalar"], source["scalar"]) == (3, _float32(first), _float32(last))


def _sphere(source):
    if (not glow._matches(source, {"type": 0, "radiusThickness": 1, "placementMode": 0, "alignToDirection": False,
                                  "m_Position": glow._ZERO, "m_Rotation": glow._ZERO, "m_Scale": dict.fromkeys("xyz", 1)})
            or any(source[name] for name in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(source[name] != glow._NULL for name in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                            "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return False
    return all(glow._matches(source[name], {"mode": 0, "spread": 0, "value": value})
               and _constant(source[name]["speed"]) == 1 for name, value in (("radius", _float32(.03)), ("arc", 360)))


def _stepped(source, count):
    keys = source["m_Curve"]
    if (len(keys) != count or keys[0]["time"] != 0 or keys[-1]["time"] != 1
            or (source["m_PreInfinity"], source["m_PostInfinity"]) != (2, 2)):
        return None
    rows = []
    for key in keys:
        time, value = key["time"], key["value"]
        if (key["weightedMode"] or (key["inSlope"], key["outSlope"]) != (math.inf, math.inf)
                or not 0 <= value <= 1 or (rows and not rows[-1][0] < time <= 1)):
            return None
        rows.append([time, value])
    return rows


def _gradient(source, prefix, count, channels):
    key_count = "m_NumColorKeys" if prefix == "ctime" else "m_NumAlphaKeys"
    if source["m_Mode"] != 0 or source[key_count] != count:
        return None
    rows = []
    for index in range(count):
        stamp = source[f"{prefix}{index}"]
        values = [source[f"key{index}"][axis] for axis in channels]
        if (type(stamp) is not int or not 0 <= stamp <= 65535 or (rows and rows[-1][0] >= stamp)
                or any(not 0 <= value <= 1 for value in values)):
            return None
        rows.append([stamp, *values])
    return rows


def _curves(source, color):
    size = source["SizeModule"]
    curve = size["curve"]
    if (size["separateAxes"] or (curve["minMaxState"], curve["minScalar"], curve["scalar"]) != (2, 1, 1)
            or color["minMaxState"] != 4):
        return None
    minimum, maximum = _stepped(curve["minCurve"], 15), _stepped(curve["maxCurve"], 20)
    start = color["maxGradient"]
    start_rgb = _gradient(start, "ctime", 6, "rgb")
    start_alpha = _gradient(start, "atime", 2, "a")
    if not (minimum and maximum and start_rgb and start_alpha and all(row[1] == 1 for row in start_alpha)):
        return None
    color = source["ColorModule"]["gradient"]
    if color["minMaxState"] != 3:
        return None
    alpha = []
    for lane in ("minGradient", "maxGradient"):
        gradient = color[lane]
        rgb = _gradient(gradient, "ctime", 2, "rgb")
        rows = _gradient(gradient, "atime", 8, "a")
        if rgb != [[0, 1, 1, 1], [65535, 1, 1, 1]] or not rows or rows[0][0] != 0 or rows[-1][0] != 65535:
            return None
        # Unity converts the authored alpha keys to Color32 before its
        # lifetime gradient interpolation. Keep the original ushort phases.
        alpha.append([[stamp, int(_float32(_float32(value * 255) + .5))] for stamp, value in rows])
    return {"sizeKeys": [minimum, maximum], "startRGB": start_rgb, "alphaKeys": alpha}


def _profile(source):
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != _MODULES or not glow._matches(source, _SETTINGS) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    if (not glow._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 1000,
                                   "randomizeRotationDirection": 0})
            or any(not _range(initial[name], low, high) for name, low, high in (
                ("startLifetime", 1, 1.5), ("startSize", .02, .04), ("startSpeed", 0, 0), ("gravityModifier", .005, .012)))
            or any(_constant(initial[name]) != 0 for name in ("startRotation", "startRotationX", "startRotationY"))
            or not _sphere(source["ShapeModule"])):
        return None
    velocity = source["VelocityModule"]
    if (velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1 or any(
            not _range(velocity[axis], low, high) for axis, low, high in (("x", .03, .09), ("y", 0, -.05), ("z", 0, 0)))
            or any(_constant(velocity[name]) != 0 for name in ("radial", "orbitalX", "orbitalY", "orbitalZ",
                                                              "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return None
    emission = source["EmissionModule"]
    if (emission["m_BurstCount"] != 1 or _constant(emission["rateOverTime"]) != 10
            or _constant(emission["rateOverDistance"]) != 0):
        return None
    burst, = emission["m_Bursts"]
    if not glow._matches(burst, {"time": 0, "cycleCount": 1, "probability": 1}) or _constant(burst["countCurve"]) != 10:
        return None
    sheet = source["UVModule"]
    if (not glow._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 4, "tilesY": 4,
                                 "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .1875):
        return None
    return _curves(source, initial["startColor"])


def read(objects, butterfly, fields, deadline):
    """Return the authored .13 shine and a reader for its shared original atlas."""
    try:
        viewer._remaining(deadline)
        game = glow._child(objects, butterfly, fields, "par_shine")
        components = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"},
                                       layer=1) if game is not None else None
        if components is None:
            return None
        parts = components[1]
        _, transform = parts["Transform"]
        if transform["m_Children"] or _authored_trs(transform) != {**title._IDENTITY, "translation": _POSITION}:
            return None
        renderer, fields = parts["ParticleSystemRenderer"]
        if not glow._matches(fields, _RENDERER):
            return None
        profile = _profile(parts["ParticleSystem"][1])
        texture = glow._material_texture(objects, renderer, fields)
        if profile is None or texture is None:
            return None
        return {**profile, "profile": "opening", "position": _POSITION, "maxViewportWidth": .5, "uv": [.25, .25, .75, 0],
                "material": {"tint": [1, 1, 1, 1], "queue": 3010, "cull": 0, "blend": "add", "premultiply": False}}, texture
    except title._UNSUPPORTED:
        return None
