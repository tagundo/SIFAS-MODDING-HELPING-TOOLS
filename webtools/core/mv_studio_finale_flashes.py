"""Read the paired static local billboards of the native finale flash."""

from . import model_viewer as viewer
from . import mv_studio_stage_title as title
from . import mv_studio_stage_title_particles as particles
from .model_rig import _authored_trs
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_display import _SHADERS


_LAYER = 1
_PREFAB = "fx_par_so2056_04"
_LEAVES = {"flash_01", "flash_02"}
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "EmissionModule", "ColorModule"}
_ZERO = dict.fromkeys("xyz", 0)
_SURFACE = {
    "_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_SATURATE": 0, "_StencilComp": 8,
    "_StencilRef": 0, "_StencilPassOp": 0, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
    "_ZTestMode": 4, "_ZWriteParam": 0,
}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 2
            or fields["m_UseCustomVertexStreams"] or not fields["m_ApplyActiveColorSpace"]
            or not fields["m_AllowRoll"] or fields["m_VertexStreams"] != [0, 1, 3, 4]
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_MinParticleSize"] != 0 or not particles._number(fields["m_MaxParticleSize"], .01, 4)
            or fields["m_NormalDirection"] != 1 or fields["m_LengthScale"] != 2
            or any(fields[key] for key in ("m_CameraVelocityScale", "m_VelocityScale", "m_SortMode",
                                           "m_SortingFudge", "m_SortingOrder", "m_SortingLayerID",
                                           "m_MaskInteraction", "m_CastShadows"))
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
    if (tree["m_CustomRenderQueue"] != 3010 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or viewer._properties(tree, "m_Floats") != _SURFACE
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab):
        return None
    color = viewer._properties(tree, "m_Colors")["_TintColor"]
    main = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    tint = [color[axis] for axis in "rgba"]
    uv = [main[key][axis] for key in ("m_Scale", "m_Offset") for axis in "xy"]
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None or texture.read().m_ColorSpace != 1 or tint != [2, 2, 2, 1] or uv != [1, 1, 0, 0]:
        return None
    return {"tint": tint, "uv": uv, "queue": 3010, "cull": 0, "blend": "add"}, texture


def _particle(source):
    constant = particles._constant
    enabled = {name for name, module in source.items() if name.endswith("Module") and module["enabled"]}
    if (enabled != _MODULES or not source["playOnAwake"] or source["simulationSpeed"] != 1
            or source["scalingMode"] != 1 or constant(source["startDelay"]) != 0
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction", "autoRandomSeed"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(constant(initial[key]) != 0 for key in ("startSpeed", "startRotation", "gravityModifier"))
            or any(constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))
            or emission["m_BurstCount"] != 1 or len(bursts) != 1 or initial["maxNumParticles"] != 1):
        return None
    burst, = bursts
    if (burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1
            or constant(burst["countCurve"]) != 1):
        return None
    size, lifetime = (constant(initial[key]) for key in ("startSize", "startLifetime"))
    color = _rgba8(initial, source["ColorModule"])
    if color is None or not particles._number(size, .01, 64) or not particles._number(lifetime, .01, 120):
        return None
    return {"birth": 0, "size": size, "lifetime": lifetime, "color": color,
            "sizeCurve": ("constant", 1), "yaw": 0, "yawSpeed": 0}


def _billboard(objects, game):
    leaf = title._components(objects, game, _COMPONENTS, layer=_LAYER)
    if leaf is None:
        return None
    parts = leaf[1]
    _, transform = parts["Transform"]
    trs = _authored_trs(transform)
    if transform["m_Children"] or trs["scale"] != title._IDENTITY["scale"]:
        return None
    renderer, shape = parts["ParticleSystemRenderer"]
    surface = _surface(objects, renderer, shape)
    state = _particle(parts["ParticleSystem"][1])
    if surface is None or state is None:
        return None
    material, texture = surface
    return ({"geometry": title._QUAD, "position": trs["translation"], "rotation": trs["rotation"],
             "scale": trs["scale"], "material": material, "maxViewportWidth": shape["m_MaxParticleSize"],
             **state}, texture)


def read(objects, game, deadline, *, clip_seed=None):
    """Return both deterministic billboards from this authored control prefab."""
    if game.peek_name() != _PREFAB:
        return None
    outer = title._components(objects, game, {"Transform"}, layer=_LAYER)
    if outer is None:
        return None
    transform, fields = outer[1]["Transform"]
    children = fields["m_Children"]
    if (len(children) != 1 or _authored_trs(fields) != title._IDENTITY
            or fields["m_Father"]["m_PathID"]):
        return None
    pivot = title._transform_child(objects, transform, children[0])
    inner = title._components(objects, pivot, {"Transform"}, layer=_LAYER) if pivot is not None else None
    if inner is None or inner[0]["m_Name"] != "root":
        return None
    transform, fields = inner[1]["Transform"]
    if len(fields["m_Children"]) != len(_LEAVES) or _authored_trs(fields) != title._IDENTITY:
        return None
    emitters = {}
    for ref in fields["m_Children"]:
        viewer._remaining(deadline)
        child = title._transform_child(objects, transform, ref)
        name = child.peek_name() if child is not None else None
        if name not in _LEAVES or name in emitters:
            return None
        emitter = _billboard(objects, child)
        if emitter is None:
            return None
        emitters[name] = emitter
    return list(emitters.values())
