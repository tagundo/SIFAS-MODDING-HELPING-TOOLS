"""Read the authored Monster Girls background mesh particle for Studio."""

from . import model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _constant, _float32, _number


_PREFAB = "fx_dis_so2056_09"
_SIBLINGS = {"speed", "speed_R", "speed_L", "speed_back", "stars", "stars_center"}
_ZERO = dict.fromkeys("xyz", 0)
_SURFACE = {"_BlendDst": 10, "_BlendSrc": 5, "_CullMode": 0, "_SATURATE": 1,
            "_StencilComp": 3, "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0,
            "_VERTEX_COLOR": 1, "_ZTestMode": 4, "_ZWriteParam": 0}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 4 or fields["m_RenderAlignment"] != 2
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or not fields["m_ApplyActiveColorSpace"]
            or not fields["m_AllowRoll"] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_SortMode"] != 2 or fields["m_SortingFudge"] != 5 or fields["m_MaxParticleSize"] != 2
            or fields["m_NormalDirection"] != 1 or fields["m_LengthScale"] != 2
            or fields["m_RenderingLayerMask"] != 1 or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_EnableGPUInstancing", "m_UseCustomVertexStreams", "m_CameraVelocityScale",
                                           "m_VelocityScale", "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows",
                                           "m_ReceiveShadows", "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
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
    if (tree["m_CustomRenderQueue"] != 2900 or tree["m_ShaderKeywords"] != "_SATURATE_ON _VERTEX_COLOR_ON"
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


def _particle(source):
    enabled = {name for name, module in source.items() if name.endswith("Module") and module["enabled"]}
    if (enabled != {"InitialModule", "EmissionModule"} or not source["playOnAwake"]
            or source["simulationSpeed"] != 1 or source["scalingMode"] != 1 or _constant(source["startDelay"]) != 0
            or not _number(source["lengthInSec"], .01, 1) or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction", "autoRandomSeed"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    lifetime = _constant(initial["startLifetime"])
    if (lifetime != 60 or _constant(initial["startSize"]) != 1 or initial["size3D"] or initial["rotation3D"]
            or initial["randomizeRotationDirection"] or not 1 <= initial["maxNumParticles"] <= 10
            or any(_constant(initial[key]) != 0 for key in ("startSpeed", "startRotation", "gravityModifier"))
            or any(_constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))
            or emission["m_BurstCount"] != 1):
        return None
    burst, = emission["m_Bursts"]
    if (burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1
            or _constant(burst["countCurve"]) != 1):
        return None
    start = initial["startColor"]
    color = [start["maxColor"][axis] for axis in "rgba"]
    if start["minMaxState"] != 0 or not all(_number(value, 0, 1) for value in color):
        return None
    return lifetime, [int(_float32(_float32(value * 255) + .5)) for value in color]


def _geometry(reader, particle_color, deadline):
    import numpy as np

    tree = reader.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    if (tree["m_Name"] != "dis_speed" or vertices["m_VertexCount"] != 1701 or len(submeshes) != 1
            or (submeshes[0]["indexCount"], submeshes[0]["topology"]) != (9600, 0)
            or vertices["m_Channels"][3]["format"] != 2 or vertices["m_Channels"][3]["dimension"] != 4
            or tree["m_BindPose"] or tree["m_MeshCompression"] or tree["m_StreamData"]["size"]
            or any(tree["m_Shapes"].values())):
        return None
    raw = {}
    _, positions, _, uv, faces = viewer._geometry(reader, np.eye(4), rig_data=raw, deadline=deadline)
    colors = np.asarray(raw["colors"])
    if (uv is None or (np.abs(positions) > 10).any() or (uv < 0).any() or (uv > 1).any()
            or len(faces) != 1 or faces[0].size != 9600
            or colors.shape != (1701, 4) or colors.dtype.kind not in "iu" or not (colors[:, :3] == 128).all()
            or colors[:, 3].min() < 0 or colors[:, 3].max() > 255):
        return None
    # Unity's CPU particle mesh writer packs (meshByte + 1) * particleByte
    # down to Color32 before the shader reads the normalized vertex input.
    rgb = [(129 * value) >> 8 for value in particle_color[:3]]
    alpha = ((colors[:, 3].astype(np.uint32) + 1) * particle_color[3]) >> 8
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].reshape(-1).tolist(),
            "rgb": rgb, "alpha": alpha.tolist()}


def _prefab(objects, game, deadline):
    from . import mv_studio_speed_back_animation

    outer = title._components(objects, game, {"Transform"})
    if outer is None:
        return None
    transform, fields = outer[1]["Transform"]
    child, = fields["m_Children"]
    if _authored_trs(fields) != title._IDENTITY or fields["m_Father"]["m_PathID"]:
        return None
    pivot = title._transform_child(objects, transform, child)
    root = title._components(objects, pivot, {"Transform", "Animator"}) if pivot is not None else None
    if root is None or root[0]["m_Name"] != "root":
        return None
    transform, fields = root[1]["Transform"]
    if len(fields["m_Children"]) != len(_SIBLINGS) or _authored_trs(fields) != title._IDENTITY:
        return None
    leaves = {}
    for ref in fields["m_Children"]:
        game = title._transform_child(objects, transform, ref)
        name = game.peek_name() if game is not None else None
        if name not in _SIBLINGS or name in leaves:
            return None
        leaves[name] = game
    leaf = title._components(objects, leaves["speed_back"], {"Transform", "ParticleSystem", "ParticleSystemRenderer"})
    if leaf is None:
        return None
    _, parts = leaf
    _, fields = parts["Transform"]
    pose = _authored_trs(fields, allow_zero_scale=True)
    if (fields["m_Children"] or pose["scale"] != [2.5, 1.5, 0] or pose["rotation"] != title._IDENTITY["rotation"]
            or any(abs(value) > 100 for value in pose["translation"])):
        return None
    state = _particle(parts["ParticleSystem"][1])
    texture = _surface(objects, *parts["ParticleSystemRenderer"])
    animation = mv_studio_speed_back_animation.read(objects, *root[1]["Animator"], deadline)
    if state is None or texture is None or animation is None:
        return None
    renderer, fields = parts["ParticleSystemRenderer"]
    mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
    lifetime, color = state
    geometry = _geometry(mesh, color, deadline) if mesh is not None else None
    if geometry is None:
        return None
    x, y, z = pose["translation"]
    sx, sy, sz = pose["scale"]
    matrix = [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, x, y, z, 1]
    return {**geometry, **animation, "lifetime": lifetime, "matrix": matrix}, texture


def read(objects, mono, tracks, deadline):
    """Return the native background for a supported Stage Display cue."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    matches = []
    for track in tracks:
        source = controls.get(track["id"])
        if (source is None or track.get("binding") or track.get("bindings") or motion._quality(track["label"]) != "stage_display"
                or track["label"] != "StageEffect/Expert/Display/light"):
            continue
        owner, fields = source
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields)):
                continue
            for event in track["events"]:
                if event["label"] != _PREFAB:
                    continue
                viewer._remaining(deadline)
                values = event["values"]
                if values.get("clipIn") != 0 or values.get("offset") != _ZERO:
                    continue
                ctrl = particles._source(objects, owner, fields, event)
                if ctrl is None or ctrl[0].peek_name() != _PREFAB:
                    continue
                original = _prefab(objects, ctrl[0], deadline)
                if original is not None and event["duration"] <= original[0]["lifetime"]:
                    matches.append((event, track, *original))
        except title._UNSUPPORTED:
            continue
    if len(matches) != 1:
        return None
    event, track, background, source = matches[0]
    try:
        texture = particles._texture(source, deadline)
    except title._UNSUPPORTED:
        return None
    if not texture or len(texture) != 10:
        return None
    return {**background, "texture": texture, "trackId": track["id"], "eventId": event["id"]}
