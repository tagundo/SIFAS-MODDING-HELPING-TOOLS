"""Read the native smoke emitter in the Monster Girls Expert front sparks prefab."""

from . import mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_display_lights import _enabled
from .mv_studio_foot_particles import _rgba8
from .mv_studio_sparks_b import _curve_pair, _spark_atlas
from .mv_studio_stage_break import _curve
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _number


_NAME = "smoke"
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule",
            "ClampVelocityModule", "RotationModule", "VelocityModule"}
_ZERO = dict.fromkeys("xyz", 0)
_UNIT = dict.fromkeys("xyz", 1)
_WHITE_START = {"startColor": {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}}
_ROTATION = {"x": _float32(-.7071068286895752), "y": 0, "z": 0, "w": _float32(.7071068286895752)}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or not fields["m_AllowRoll"] or not fields["m_ApplyActiveColorSpace"]
            or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 0 or fields["m_SortMode"] != 3
            or fields["m_LengthScale"] != 1 or fields["m_VelocityScale"] != _float32(.1)
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO or fields["m_MaxParticleSize"] != 2
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_NormalDirection"] != 1
            or fields["m_RenderingLayerMask"] != 1 or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortingFudge", "m_UseCustomVertexStreams", "m_CameraVelocityScale",
                                           "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows",
                                           "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    return _spark_atlas(objects, renderer, fields["m_Materials"])


def _shape(fields):
    radius, arc = fields["radius"], fields["arc"]
    radius_speed = _constant(radius["speed"])
    if (fields["type"] != 8 or fields["angle"] != 8 or fields["length"] != 6 or fields["radiusThickness"] != 1
            or (radius["value"], radius["mode"], radius_speed) != (.25, 1, 10)
            or (arc["value"], arc["mode"], _constant(arc["speed"])) != (360, 0, 1)
            or radius["spread"] or arc["spread"] or fields["m_Scale"] != _UNIT
            or any(fields[key] != _ZERO for key in ("m_Position", "m_Rotation", "boxThickness"))
            or any(fields[key] for key in ("placementMode", "alignToDirection", "randomDirectionAmount",
                                           "sphericalDirectionAmount", "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return {"type": fields["type"], "radius": radius["value"], "radiusMode": radius["mode"], "radiusSpeed": radius_speed,
            "radiusThickness": fields["radiusThickness"], "angle": fields["angle"], "length": fields["length"],
            "arc": arc["value"], "arcMode": arc["mode"], "scale": [fields["m_Scale"][axis] for axis in "xyz"],
            "rotation": [fields["m_Rotation"][axis] for axis in "xyz"]}


def _emission(source, deadline):
    emission = source["EmissionModule"]
    rate = emission["rateOverTime"]
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or rate["minMaxState"] != 1 or rate["scalar"] != 30):
        return None
    curve = _curve(rate["maxCurve"], deadline, expected=((0, 1, 0, 0), (1, .5, 0, 0)))
    return {"rateCurve": curve, "rateMultiplier": rate["scalar"]} if curve is not None else None


def _initial(source, deadline):
    roll = _constant_range(source["startRotation"], -7, 7)
    turn = _float32(6.283185)
    if (roll != (-turn, turn) or source["maxNumParticles"] != 1000 or _constant(source["gravityModifier"]) != 0
            or source["size3D"] or source["rotation3D"] or source["randomizeRotationDirection"]):
        return None
    result = {"roll": roll, "capacity": source["maxNumParticles"]}
    for key, name, multipliers in (("startLifetime", "initialLifetime", (3, 1.5)), ("startSize", "initialSize", (1, 2)),
                                   ("startSpeed", "initialSpeed", (5, 15))):
        field = source[key]
        if (field["minScalar"], field["scalar"]) != multipliers:
            return None
        curves = _curve_pair(field, 2, deadline)
        if curves is None:
            return None
        result[name] = {"curves": curves, "minMultiplier": field["minScalar"], "maxMultiplier": field["scalar"]}
    return result


def _motion(source, deadline):
    rotation = source["RotationModule"]
    spin = _constant_range(rotation["curve"], -2, 2)
    quarter = _float32(1.57079625)
    velocity = source["VelocityModule"]
    y = _constant_range(velocity["y"], 0, 1)
    if (rotation["separateAxes"] or spin != (quarter, -quarter)
            or velocity["inWorldSpace"] or y != (_float32(.2), _float32(.02))
            or any(_constant_range(velocity[axis], 0, 1) != (0, 0) for axis in "xz")
            or _constant(velocity["speedModifier"]) != 1
            or any(_constant(velocity[key]) != 0 for key in ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX",
                                                              "orbitalOffsetY", "orbitalOffsetZ", "radial"))):
        return None
    clamp = source["ClampVelocityModule"]
    limit = clamp["magnitude"]
    if (clamp["separateAxis"] or clamp["inWorldSpace"] or _constant(clamp["drag"]) != 0
            or clamp["dampen"] != _float32(.15) or limit["minMaxState"] != 1 or limit["scalar"] != 1):
        return None
    limit_curve = _curve(limit["maxCurve"], deadline)
    if limit_curve is None:
        return None
    return {"rollSpeed": spin, "velocityY": y, "clamp": {"curve": limit_curve, "dampen": clamp["dampen"]}}


def _start_gradient(gradient):
    if gradient["m_Mode"] != 0 or (gradient["m_NumColorKeys"], gradient["m_NumAlphaKeys"]) != (2, 2):
        return None
    result = {}
    for label, prefix, axes in (("rgb", "ctime", "rgb"), ("alpha", "atime", "a")):
        keys = []
        for index, expected_time in enumerate((0, 65535)):
            time = gradient[f"{prefix}{index}"]
            values = [gradient[f"key{index}"][axis] for axis in axes]
            if time != expected_time or any(not _number(value, 0, 1) for value in values):
                return None
            keys.append([time, *values])
        result[label] = keys
    return result


def _colors(source):
    initial = source["InitialModule"]["startColor"]
    lifetime = source["ColorModule"]
    if initial["minMaxState"] != 3 or lifetime["gradient"]["minMaxState"] != 3:
        return None
    start, life = [], []
    for name in ("minGradient", "maxGradient"):
        original = _start_gradient(initial[name])
        fields = {"enabled": True, "gradient": {"minMaxState": 1, "maxGradient": lifetime["gradient"][name]}}
        packed = _rgba8(_WHITE_START, fields)
        if original is None or packed is None:
            return None
        start.append(original)
        life.append(packed["rgba8"]["keys"])
    return {"startGradients": start, "lifeColors": life}


def _state(source, deadline):
    delay, duration = _constant(source["startDelay"]), source["lengthInSec"]
    if (_enabled(source) != _MODULES or not source["playOnAwake"] or not source["autoRandomSeed"]
            or source["randomSeed"] != 0 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or delay != 0 or duration != _float32(.3) or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction"))):
        return None
    atlas = _atlas(source["UVModule"], deadline, through=1)
    if atlas != {"tiles": [4, 4], "row": 2, "frame": ("constant", 0)}:
        return None
    sizing = source["SizeModule"]
    curve = sizing["curve"]
    if sizing["separateAxes"] or curve["scalar"] != 2:
        return None
    size_curves = _curve_pair(curve, 2, deadline)
    shape = _shape(source["ShapeModule"])
    initial = _initial(source["InitialModule"], deadline)
    emission, motion, color = _emission(source, deadline), _motion(source, deadline), _colors(source)
    if any(item is None for item in (size_curves, shape, initial, emission, motion, color)):
        return None
    return {"name": _NAME, "delay": delay, "duration": duration, "shape": shape, **initial, **emission, **motion, **color,
            "sizeCurves": size_curves, "sizeMultiplier": curve["scalar"], "uv": [.25, .25, 0, .5]}


def read(objects, game, deadline):
    """Return the smoke descriptor and the original shared atlas object."""
    typed = title._components(objects, game, _COMPONENTS, layer=1)
    if typed is None or typed[0]["m_Name"] != _NAME:
        return None
    parts = typed[1]
    _, transform = parts["Transform"]
    if (transform["m_Children"] or transform["m_LocalPosition"] != _ZERO
            or transform["m_LocalScale"] != _UNIT or transform["m_LocalRotation"] != _ROTATION):
        return None
    source = parts["ParticleSystem"][1]
    state = _state(source, deadline)
    renderer, fields = parts["ParticleSystemRenderer"]
    atlas = _surface(objects, renderer, fields) if state is not None else None
    if atlas is None:
        return None
    return {**state, "rotation": _authored_trs(transform)["rotation"], "maxViewportWidth": fields["m_MaxParticleSize"],
            "sortMode": fields["m_SortMode"]}, atlas
