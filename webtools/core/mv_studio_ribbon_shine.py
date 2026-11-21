"""Read the source settings for the native ribbon's continuous shine emitter."""

import math

from . import model_viewer as viewer
from . import mv_studio_stage_title as title, mv_studio_stage_title_particles as particles
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS


_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "EmissionModule", "ShapeModule", "SizeModule"}
_ZERO = dict.fromkeys("xyz", 0)
_WHITE = dict.fromkeys("rgba", 1)
_SURFACE = {
    "_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_SATURATE": 0, "_StencilComp": 3,
    "_StencilRef": 2, "_StencilPassOp": 0, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
    "_ZTestMode": 4, "_ZWriteParam": 0,
}


def _texture(objects, renderer, fields):
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 0
            or fields["m_UseCustomVertexStreams"] or not fields["m_ApplyActiveColorSpace"]
            or not fields["m_AllowRoll"] or fields["m_VertexStreams"] != [0, 1, 3, 4]
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO or fields["m_NormalDirection"] != 1
            or fields["m_MinParticleSize"] != 0 or fields["m_MaxParticleSize"] != .5 or fields["m_LengthScale"] != 2
            or any(fields[key] for key in ("m_CameraVelocityScale", "m_VelocityScale", "m_SortMode",
                                           "m_SortingFudge", "m_SortingOrder", "m_SortingLayerID",
                                           "m_RendererPriority", "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3"))):
        return None
    refs = fields["m_Materials"]
    if len(refs) != 2 or refs[0] != refs[1]:
        return None
    material = title._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    shader = tree["m_Shader"]
    path_id, cab = _SHADERS["AS/General/Transparent"]
    file_id, externals = shader["m_FileID"], material.assets_file.externals
    floats = viewer._properties(tree, "m_Floats")
    if (tree["m_CustomRenderQueue"] != 2900 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or any(floats.get(key) != value for key, value in _SURFACE.items())
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab):
        return None
    color = viewer._properties(tree, "m_Colors")["_TintColor"]
    main = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    if color != _WHITE or main["m_Scale"] != {"x": 1, "y": 1} or main["m_Offset"] != {"x": 0, "y": 0}:
        return None
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None:
        return None
    image = texture.read()
    if (image.m_Width, image.m_Height, image.m_MipCount, image.m_TextureFormat, image.m_ColorSpace) != (256, 256, 9, 65, 1):
        return None
    sampler = image.m_TextureSettings
    if (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias,
            sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (1, 1, 0, 0, 0, 0):
        return None
    return texture


def _shape(shape):
    radius, arc = shape["radius"], shape["arc"]
    rotation, scale = shape["m_Rotation"], shape["m_Scale"]
    box = [scale[axis] for axis in "xyz"]
    if (shape["type"] != 5 or shape["m_Position"] != _ZERO or shape["boxThickness"] != _ZERO
            or shape["radiusThickness"] != 1 or shape["alignToDirection"]
            or radius["mode"] != 0 or radius["spread"] != 0 or radius["value"] != 1
            or arc["mode"] != 0 or arc["spread"] != 0 or arc["value"] != 360
            or rotation["x"] or rotation["z"] or not particles._number(rotation["y"], -360, 360)
            or not all(particles._number(axis, .01, 10) for axis in box)
            or any(shape[key] for key in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(shape[key]["m_PathID"] for key in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                     "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return None
    return {"box": box, "shapeYaw": math.radians(rotation["y"])}


def _particle(source, deadline):
    constant = particles._constant
    enabled = {name for name, module in source.items() if name.endswith("Module") and module["enabled"]}
    if (enabled != _MODULES or source["lengthInSec"] != 5 or source["simulationSpeed"] != 1
            or source["scalingMode"] != 1 or constant(source["startDelay"]) != 0
            or not all(source[key] for key in ("looping", "prewarm", "playOnAwake", "autoRandomSeed"))
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction", "randomSeed"))):
        return None
    initial, emission, size = (source[name] for name in ("InitialModule", "EmissionModule", "SizeModule"))
    color = initial["startColor"]
    if (initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or initial["maxNumParticles"] != 1000 or color["minMaxState"] != 0 or color["maxColor"] != _WHITE
            or any(constant(initial[key]) != 0 for key in ("startRotation", "gravityModifier"))
            or constant(emission["rateOverTime"]) != 10 or constant(emission["rateOverDistance"]) != 0
            or emission["m_BurstCount"] or emission["m_Bursts"] or size["separateAxes"]):
        return None
    ranges = {}
    for label, name, upper in (("size", "startSize", 1), ("lifetime", "startLifetime", 20), ("speed", "startSpeed", 4)):
        bounds = particles._constant_range(initial[name], .01, upper)
        if bounds is None or bounds[0] > bounds[1]:
            return None
        ranges[label] = list(bounds)
    curve = size["curve"]
    if curve["minMaxState"] != 2:
        return None
    # One native multiplier applies to each side before the per-particle
    # interpolation. Both source curves clamp at their last authored key.
    shapes = [particles._scalar({"minMaxState": 1, "scalar": curve["scalar"], "maxCurve": curve[which]}, deadline)
              for which in ("minCurve", "maxCurve")]
    if any(shape is None for shape in shapes):
        return None
    box = _shape(source["ShapeModule"])
    if box is None:
        return None
    return {**ranges, **box, "sizeCurves": shapes, "rate": 10, "cycle": 5}


def read(objects, shine, deadline):
    """Describe a supported local emitter without assigning a runtime seed."""
    viewer._remaining(deadline)
    try:
        leaf = title._components(objects, shine, _COMPONENTS)
        if leaf is None or leaf[0]["m_Name"] != "shine":
            return None
        parts = leaf[1]
        transform = parts["Transform"][1]
        trs = _authored_trs(transform)
        if (transform["m_Children"] or trs["rotation"] != title._IDENTITY["rotation"]
                or trs["scale"] != title._IDENTITY["scale"]):
            return None
        state = _particle(parts["ParticleSystem"][1], deadline)
        texture = _texture(objects, *parts["ParticleSystemRenderer"])
        if state is None or texture is None:
            return None
        return {**state, "position": trs["translation"], "maxViewportWidth": .5}, texture
    except title._UNSUPPORTED:
        return None
