"""Read the four moving Monster Girls display emitters and their shared atlas."""

from . import model_viewer as viewer
from . import mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_center_stars import _material, _palette
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _number


_NAMES = ("speed", "speed_R", "speed_L", "stars")
_ZERO = dict.fromkeys("xyz", 0)
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule"}


def _renderer(fields, stretched):
    stretch = (1, 0, 20, _float32(.1)) if stretched else (0, 2, 1, 0)
    if (not fields["m_Enabled"] or not fields["m_ApplyActiveColorSpace"] or not fields["m_AllowRoll"]
            or (fields["m_RenderMode"], fields["m_RenderAlignment"], fields["m_LengthScale"],
                fields["m_VelocityScale"]) != stretch
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_MaxParticleSize"] != .5 or fields["m_NormalDirection"] != 1
            or fields["m_RenderingLayerMask"] != 1 or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortMode", "m_SortingFudge", "m_UseCustomVertexStreams",
                                           "m_CameraVelocityScale", "m_MinParticleSize", "m_MaskInteraction",
                                           "m_CastShadows", "m_ReceiveShadows", "m_SortingLayerID", "m_SortingOrder",
                                           "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    return {"maxViewportWidth": fields["m_MaxParticleSize"],
            "stretch": {"lengthScale": fields["m_LengthScale"], "velocityScale": fields["m_VelocityScale"]}
            if stretched else None}


def _shape(fields, circle):
    radius, arc = fields["radius"], fields["arc"]
    scale = [fields["m_Scale"][axis] for axis in "xyz"]
    expected_scale = [1, 1, _float32(.1)] if circle else [_float32(.6), _float32(.3), _float32(.1)]
    if (fields["m_Position"] != _ZERO or fields["m_Rotation"] != _ZERO or scale != expected_scale
            or fields["type"] != (10 if circle else 4) or fields["angle"] != 75 or fields["length"] != 5
            or fields["radiusThickness"] != 1 or radius["value"] != (1 if circle else _float32(.0001))
            or arc["value"] != (90 if circle else 360)
            or any(e["mode"] or e["spread"] or _constant(e["speed"]) != 1 for e in (radius, arc))
            or any(fields[key] for key in ("alignToDirection", "randomDirectionAmount", "sphericalDirectionAmount",
                                           "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return {"type": fields["type"], "scale": scale, "radius": radius["value"], "arc": arc["value"], "angle": fields["angle"]}


def _linear_size(fields):
    curve = fields["curve"]
    authored = curve["maxCurve"]
    first, last = authored["m_Curve"]
    # The size-over-life curve is exactly the normalized age for these four emitters.
    return (not fields["separateAxes"] and curve["minMaxState"] == 1 and curve["scalar"] == 1
            and (authored["m_PreInfinity"], authored["m_PostInfinity"]) == (2, 2)
            and (first["time"], first["value"], first["outSlope"], first["weightedMode"]) == (0, 0, 1, 0)
            and (last["time"], last["value"], last["inSlope"], last["weightedMode"]) == (1, 1, 1, 0))


def _state(source, name, deadline):
    modules = {key for key, item in source.items() if key.endswith("Module") and item["enabled"]}
    seed = source["randomSeed"]
    if (modules != _MODULES or not source["playOnAwake"] or not source["looping"] or source["lengthInSec"] != 5
            or source["simulationSpeed"] != 1 or source["scalingMode"] != 1 or _constant(source["startDelay"]) != 0
            or type(seed) is not int or not -(1 << 31) <= seed <= (1 << 32) - 1
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction", "autoRandomSeed"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    rate, capacity = _constant(emission["rateOverTime"]), initial["maxNumParticles"]
    lifetime = _constant(initial["startLifetime"])
    size = _constant_range(initial["startSize"], .01, 2)
    speed = _constant_range(initial["startSpeed"], .01, 25)
    is_star = name == "stars"
    if (lifetime != 2 or (rate, capacity) != ((250, 500) if name == "speed" else (100, 1000))
            or size != ((.5, 2) if is_star else (.5, 1)) or speed != ((5, 10) if is_star else (15, 25))
            or initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(initial[key]) != 0 for key in ("startRotation", "gravityModifier"))
            or _constant(emission["rateOverDistance"]) != 0 or emission["m_BurstCount"] or emission["m_Bursts"]
            or not _linear_size(source["SizeModule"])):
        return None
    shape = _shape(source["ShapeModule"], name in ("speed_R", "speed_L"))
    palette = _palette(initial["startColor"])
    white = {"startColor": {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}}
    color = _rgba8(white, source["ColorModule"])
    atlas = _atlas(source["UVModule"], deadline, through=1)
    row = 1 if is_star else 0
    if (shape is None or palette is None or color is None
            or atlas != {"tiles": [4, 4], "row": row, "frame": ("constant", _float32(.9999))}):
        return None
    return {"name": name, "seed": seed & 0xFFFFFFFF, "rate": rate, "lifetime": lifetime, "capacity": capacity,
            "cycle": source["lengthInSec"], "prewarm": source["prewarm"], "size": size, "speed": speed,
            "rollRange": [0, 0], "shape": shape, "palette": palette, "colorKeys": color["rgba8"]["keys"],
            "uv": [.25, .25, .75, row * .25]}


def _leaf(objects, game, name, deadline):
    row = title._components(objects, game, _COMPONENTS) if game is not None else None
    if row is None or row[0]["m_Name"] != name:
        return None
    parts = row[1]
    _, fields = parts["Transform"]
    pose = _authored_trs(fields)
    if (fields["m_Children"] or pose["scale"] != title._IDENTITY["scale"]
            or (name == "stars" and pose["rotation"] != title._IDENTITY["rotation"])
            or any(abs(value) > 100 for value in pose["translation"])):
        return None
    renderer, render_fields = parts["ParticleSystemRenderer"]
    profile = _renderer(render_fields, name != "stars")
    state = _state(parts["ParticleSystem"][1], name, deadline) if profile is not None else None
    texture = _material(objects, renderer, render_fields["m_Materials"]) if state is not None else None
    if texture is None:
        return None
    return {**state, **profile, "position": pose["translation"], "rotation": pose["rotation"]}, texture


def read(objects, leaves, deadline):
    """Read one complete moving-emitter cluster when all four profiles match."""
    rows, atlas = [], None
    try:
        for name in _NAMES:
            viewer._remaining(deadline)
            source = _leaf(objects, leaves.get(name), name, deadline)
            if source is None:
                return None
            row, texture = source
            if atlas is not None and viewer._key(texture) != viewer._key(atlas):
                return None
            rows.append(row)
            atlas = texture
    except title._UNSUPPORTED:
        return None
    return rows, atlas
