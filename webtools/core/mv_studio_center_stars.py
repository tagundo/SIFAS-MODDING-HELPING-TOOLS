"""Read the source emitter for the central Monster Girls star sprites."""

from . import model_viewer as viewer
from . import mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _number, _scalar


_ZERO = dict.fromkeys("xyz", 0)
_SURFACE = {"_BlendDst": 1, "_BlendSrc": 5, "_CullMode": 0, "_SATURATE": 0,
            "_StencilComp": 3, "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0,
            "_VERTEX_COLOR": 1, "_ZTestMode": 4, "_ZWriteParam": 0}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 2
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or not fields["m_ApplyActiveColorSpace"]
            or not fields["m_AllowRoll"] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_SortingFudge"] != 1 or fields["m_MaxParticleSize"] != .5
            or fields["m_NormalDirection"] != 1 or fields["m_LengthScale"] != 1
            or fields["m_RenderingLayerMask"] != 1 or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortMode", "m_UseCustomVertexStreams", "m_CameraVelocityScale",
                                           "m_VelocityScale", "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows",
                                           "m_ReceiveShadows", "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
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
    if (tree["m_CustomRenderQueue"] != 2900 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or tree["stringTagMap"] or tree["disabledShaderPasses"] or viewer._properties(tree, "m_Floats") != _SURFACE
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab
            or viewer._properties(tree, "m_Colors") != {"_TintColor": dict.fromkeys("rgba", 1)}):
        return None
    textures = viewer._properties(tree, "m_TexEnvs")
    if set(textures) != {"_MainTex"}:
        return None
    main = textures["_MainTex"]
    if main["m_Scale"] != dict.fromkeys("xy", 1) or main["m_Offset"] != dict.fromkeys("xy", 0):
        return None
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None:
        return None
    native = texture.read()
    sampler = native.m_TextureSettings
    if ((native.m_Width, native.m_Height, native.m_TextureFormat, native.m_MipCount, native.m_ColorSpace) != (512, 512, 65, 10, 1)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias,
                sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return texture


def _palette(source):
    if source["minMaxState"] != 4:
        return None
    gradient = source["maxGradient"]
    if gradient["m_Mode"] != 1:
        return None
    rows = {}
    for name, stamp, axes, count in (("rgb", "ctime", "rgb", "m_NumColorKeys"),
                                    ("alpha", "atime", "a", "m_NumAlphaKeys")):
        if not 0 < gradient[count] <= 8:
            return None
        keys = []
        for index in range(gradient[count]):
            time = gradient[f"{stamp}{index}"]
            components = [gradient[f"key{index}"][axis] for axis in axes]
            if (type(time) is not int or not 0 <= time <= 65535 or (keys and time <= keys[-1][0])
                    or not all(_number(value, 0, 1) for value in components)):
                return None
            keys.append([time, *(int(_float32(_float32(value * 255) + .5)) for value in components)])
        rows[name] = keys
    return rows


def _size_curve(module, deadline):
    value = module["curve"]
    authored = value["maxCurve"]
    keys = authored["m_Curve"]
    if (module["separateAxes"] or value["minMaxState"] != 1 or value["scalar"] != 1
            or authored["m_PostInfinity"] != 1 or len(keys) != 3 or keys[0]["time"] != 0
            or not _number(keys[-1]["time"], .1, .5)):
        return None
    period = keys[-1]["time"]
    # This curve uses Unity's cyclic post mode. The preview wraps the
    # normalized particle age before sampling the authored cubic segments.
    curve = _scalar(value, deadline, through=period)
    return (curve, period) if curve is not None else None


def _state(source, deadline):
    modules = {key for key, item in source.items() if key.endswith("Module") and item["enabled"]}
    seed = source["randomSeed"]
    if (modules != {"InitialModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule"}
            or not source["playOnAwake"] or not source["looping"] or source["lengthInSec"] != 5
            or source["simulationSpeed"] != 1 or source["scalingMode"] != 1 or _constant(source["startDelay"]) != 0
            or type(seed) is not int or not -(1 << 31) <= seed <= (1 << 32) - 1
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction", "autoRandomSeed"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    life, size, rate = (_constant(initial["startLifetime"]), _constant(initial["startSize"]),
                        _constant(emission["rateOverTime"]))
    roll = _constant_range(initial["startRotation"], -7, 7)
    if ((life, size, rate) != (1, 2, 2) or roll is None or roll[0] >= roll[1]
            or initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or not 3 <= initial["maxNumParticles"] <= 1000
            or any(_constant(initial[key]) != 0 for key in ("startSpeed", "gravityModifier"))
            or _constant(emission["rateOverDistance"]) != 0 or emission["m_BurstCount"] != 1):
        return None
    burst, = emission["m_Bursts"]
    if (burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1
            or _constant(burst["countCurve"]) != 1):
        return None
    palette = _palette(initial["startColor"])
    white = {"startColor": {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}}
    color = _rgba8(white, source["ColorModule"])
    curve = _size_curve(source["SizeModule"], deadline)
    uv = _atlas(source["UVModule"], deadline, through=1)
    if palette is None or color is None or curve is None or uv != {"tiles": [4, 4], "row": 1, "frame": ("constant", 0)}:
        return None
    size_curve, period = curve
    return {"seed": seed & 0xFFFFFFFF, "lifetime": life, "size": size, "rate": rate, "cycle": source["lengthInSec"],
            "rollRange": roll, "uv": [.25, .25, 0, .25], "palette": palette, "colorKeys": color["rgba8"]["keys"],
            "sizeCurve": size_curve, "sizePeriod": period}


def read(objects, leaf, deadline):
    """Return the bounded local billboard and original atlas for this emitter."""
    try:
        row = title._components(objects, leaf, {"Transform", "ParticleSystem", "ParticleSystemRenderer"})
        if row is None or row[0]["m_Name"] != "stars_center":
            return None
        parts = row[1]
        _, fields = parts["Transform"]
        pose = _authored_trs(fields)
        if (fields["m_Children"] or pose["rotation"] != title._IDENTITY["rotation"]
                or pose["scale"] != title._IDENTITY["scale"] or any(abs(value) > 100 for value in pose["translation"])):
            return None
        renderer, fields = parts["ParticleSystemRenderer"]
        descriptor = _state(parts["ParticleSystem"][1], deadline)
        texture = _surface(objects, renderer, fields) if descriptor is not None else None
        if texture is None:
            return None
        return {**descriptor, "position": pose["translation"], "maxViewportWidth": fields["m_MaxParticleSize"]}, texture
    except title._UNSUPPORTED:
        return None
