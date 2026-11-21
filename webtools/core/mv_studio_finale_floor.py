"""Read the native floor particles in the Monster Girls Expert finale."""

from . import model_viewer as viewer
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_center_stars import _palette
from .mv_studio_display_lights import _enabled
from .mv_studio_foot_particles import _rgba8
from .mv_studio_moving_companions import _linear_size
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32


_PREFAB = "fx_flo_so2056_01"
_TRACK = "StageEffect/Expert/Control/flo"
_LAYER = 15
_ALIAS = "speedBackCenterStars"
_ZERO = dict.fromkeys("xyz", 0)
_WHITE = dict.fromkeys("rgba", 1)
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule"}
_SURFACE = {"_BlendDst": 1, "_BlendSrc": 5, "_CullMode": 0, "_SATURATE": 0,
            "_StencilComp": 8, "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0,
            "_VERTEX_COLOR": 1, "_ZTestMode": 4, "_ZWriteParam": 0}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or not fields["m_ApplyActiveColorSpace"] or not fields["m_AllowRoll"]
            or fields["m_RenderMode"] != 2 or fields["m_RenderAlignment"] != 0
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_MaxParticleSize"] != 2 or fields["m_NormalDirection"] != 1
            or fields["m_LengthScale"] != 20 or fields["m_VelocityScale"] != _float32(.1)
            or fields["m_RenderingLayerMask"] != 1 or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortMode", "m_SortingFudge", "m_UseCustomVertexStreams",
                                           "m_CameraVelocityScale", "m_MinParticleSize", "m_MaskInteraction",
                                           "m_CastShadows", "m_ReceiveShadows", "m_SortingLayerID", "m_SortingOrder",
                                           "m_RendererPriority"))
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
    if (tree["m_CustomRenderQueue"] != 3000 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or tree["stringTagMap"] or tree["disabledShaderPasses"] or viewer._properties(tree, "m_Floats") != _SURFACE
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab
            or viewer._properties(tree, "m_Colors") != {"_TintColor": _WHITE}):
        return None
    textures = viewer._properties(tree, "m_TexEnvs")
    if set(textures) != {"_MainTex"}:
        return None
    main = textures["_MainTex"]
    if main["m_Scale"] != dict.fromkeys("xy", 1) or main["m_Offset"] != dict.fromkeys("xy", 0):
        return None
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None or texture.peek_name() != "tex_par_so2056_01":
        return None
    native = texture.read()
    sampler = native.m_TextureSettings
    if ((native.m_Width, native.m_Height, native.m_TextureFormat, native.m_MipCount, native.m_ColorSpace)
            != (512, 512, 65, 10, 1) or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias,
                                          sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return texture


def _box(fields):
    scale = [fields["m_Scale"][axis] for axis in "xyz"]
    radius, arc = fields["radius"], fields["arc"]
    if (fields["type"] != 5 or scale != [20, 0, 1] or fields["m_Position"] != _ZERO or fields["m_Rotation"] != _ZERO
            or fields["boxThickness"] != _ZERO or fields["radiusThickness"] != 1
            or radius["value"] != 1 or arc["value"] != 360
            or any(item["mode"] or item["spread"] or _constant(item["speed"]) != 1 for item in (radius, arc))
            or any(fields[key] for key in ("placementMode", "alignToDirection", "randomDirectionAmount",
                                           "sphericalDirectionAmount", "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return scale


def _state(source, deadline):
    seed, cycle = source["randomSeed"], source["lengthInSec"]
    if (_enabled(source) != _MODULES or not source["playOnAwake"] or not source["looping"]
            or seed != 0 or cycle != 5 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or _constant(source["startDelay"]) != 0 or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction", "autoRandomSeed"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    lifetime, rate, capacity = _constant(initial["startLifetime"]), _constant(emission["rateOverTime"]), initial["maxNumParticles"]
    size = [_constant(initial[key]) for key in ("startSize", "startSizeY", "startSizeZ")]
    speed = _constant_range(initial["startSpeed"], 0, 30)
    if ((lifetime, rate, capacity) != (.5, 150, 1000) or size != [_float32(.3), 20, 1] or speed != (15, 25)
            or not initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(initial[key]) != 0 for key in ("gravityModifier", "startRotation", "startRotationX", "startRotationY"))
            or _constant(emission["rateOverDistance"]) != 0 or emission["m_BurstCount"] or emission["m_Bursts"]
            or not _linear_size(source["SizeModule"])):
        return None
    box = _box(source["ShapeModule"])
    palette = _palette(initial["startColor"])
    color = _rgba8({"startColor": {"minMaxState": 0, "maxColor": _WHITE}}, source["ColorModule"])
    atlas = _atlas(source["UVModule"], deadline, through=1)
    if (box is None or palette is None or palette["alpha"] != [[0, 255], [65535, 255]] or color is None
            or atlas != {"tiles": [4, 4], "row": 0, "frame": ("constant", _float32(.9999))}):
        return None
    keys = color["rgba8"]["keys"]
    if any(key[1:4] != [255, 255, 255] for key in keys):
        return None
    return {"seed": seed, "rate": rate, "cycle": cycle, "lifetime": lifetime, "size": size, "speedRange": speed,
            "box": box, "palette": palette, "colorKeys": keys, "uv": [.25, .25, .75, 0], "capacity": capacity}


def _only_child(objects, game, name):
    typed = title._components(objects, game, {"Transform"}, layer=_LAYER)
    if typed is None or typed[0]["m_Name"] != name:
        return None
    transform, fields = typed[1]["Transform"]
    children = fields["m_Children"]
    if (len(children) != 1 or _authored_trs(fields) != title._IDENTITY
            or (name == _PREFAB and fields["m_Father"]["m_PathID"])):
        return None
    return title._transform_child(objects, transform, children[0])


def _prefab(objects, game, deadline):
    pivot = _only_child(objects, game, _PREFAB)
    leaf = _only_child(objects, pivot, "root") if pivot is not None else None
    if leaf is None or leaf.peek_name() != "flo_01":
        return None
    typed = title._components(objects, leaf, _COMPONENTS, layer=_LAYER)
    if typed is None:
        return None
    parts = typed[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    if (transform["m_Children"] or pose["scale"] != title._IDENTITY["scale"]
            or pose["rotation"] != title._IDENTITY["rotation"] or any(abs(value) > 100 for value in pose["translation"])):
        return None
    state = _state(parts["ParticleSystem"][1], deadline)
    renderer, fields = parts["ParticleSystemRenderer"]
    texture = _surface(objects, renderer, fields) if state is not None else None
    if texture is None:
        return None
    return {**state, "position": pose["translation"], "maxViewportWidth": fields["m_MaxParticleSize"]}, texture


def read(objects, mono, tracks, deadline, *, atlas_refs=None):
    """Resolve the neutral Expert floor cue and preserve its original atlas."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    accepted = None
    for track in tracks:
        source = controls.get(track["id"])
        if source is None or track["label"] != _TRACK or track.get("binding") or track.get("bindings"):
            continue
        owner, fields = source
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields, "control")):
                continue
            for event in track["events"]:
                if event["label"] != _PREFAB or event["values"].get("clipIn") != 0:
                    continue
                viewer._remaining(deadline)
                control = particles._source(objects, owner, fields, event)
                resolved = _prefab(objects, control[0], deadline) if control is not None else None
                if resolved is not None:
                    if accepted is not None:
                        return None
                    accepted = track["id"], event["id"], resolved
        except title._UNSUPPORTED:
            continue
    if accepted is None:
        return None
    track_id, event_id, (effect, reader) = accepted
    if atlas_refs is not None and atlas_refs.get(viewer._key(reader)) == _ALIAS:
        atlas = _ALIAS
    else:
        try:
            atlas = particles._texture(reader, deadline)
        except title._UNSUPPORTED:
            return None
        if not atlas or len(atlas) != 10:
            return None
    return {**effect, "trackId": track_id, "eventId": event_id, "textures": [atlas]}
