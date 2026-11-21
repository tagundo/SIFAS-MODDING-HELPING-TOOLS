"""Read the native Monster Girls display strokes and their authored atlas."""

from . import model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _atlas, _constant, _number, _scalar


_PREFAB = "fx_dis_so2056_06"
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_LEAVES = {"light_up", "light_down", "light_left", "light_right", "light_R", "light_L"}
_ZERO = dict.fromkeys("xyz", 0)
_BASE_MODULES = {"InitialModule", "EmissionModule", "UVModule", "SizeModule"}
_SURFACE = {"_BlendDst": 10, "_BlendSrc": 5, "_CullMode": 0, "_SATURATE": 0,
            "_StencilComp": 3, "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0,
            "_VERTEX_COLOR": 1, "_ZTestMode": 4, "_ZWriteParam": 0}
_VELOCITY = ("x", "y", "z", "orbitalX", "orbitalY", "orbitalZ", "radial", "orbitalOffsetX",
             "orbitalOffsetY", "orbitalOffsetZ")


def _enabled(source):
    return {key for key, fields in source.items() if key.endswith("Module") and fields["enabled"]}


def _surface(objects, renderer, fields):
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 2
            or not fields["m_AllowRoll"] or not fields["m_ApplyActiveColorSpace"]
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_MaxParticleSize"] != 2 or fields["m_NormalDirection"] != 1 or fields["m_LengthScale"] != 2
            or fields["m_SortMode"] != 2 or fields["m_RenderingLayerMask"] != 1
            or fields["m_StaticBatchInfo"]["subMeshCount"] or not _number(fields["m_SortingFudge"], -10, 10)
            or any(fields[key] for key in ("m_UseCustomVertexStreams", "m_CameraVelocityScale", "m_VelocityScale",
                                           "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows",
                                           "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
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


def _bursts(emission, *, side):
    count = 2 if side else 1
    bursts = emission["m_Bursts"]
    if (emission["m_BurstCount"] != count or len(bursts) != count
            or any(_constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))):
        return None
    result = []
    for index, burst in enumerate(bursts):
        # Zero cycle count means the burst repeats until the emitter ends.
        if (burst["time"] != index or burst["cycleCount"] != 0 or burst["probability"] != 1
                or _constant(burst["countCurve"]) != 1 or burst["repeatInterval"] != count):
            return None
        result.append([burst["time"], burst["repeatInterval"]])
    return result


def _size(fields, deadline):
    scalar = fields["curve"]
    keys = scalar["maxCurve"]["m_Curve"]
    if (fields["separateAxes"] or scalar["minMaxState"] != 1 or len(keys) != 2
            or scalar["maxCurve"]["m_PostInfinity"] != 2 or not _number(scalar["scalar"], 0, 4)
            or (keys[0]["time"], keys[1]["time"]) != (0, 1)):
        return None
    return _scalar(scalar, deadline, through=1)


def _sheet(module, deadline):
    value = module["frameOverTime"]
    source = value["maxCurve"]
    keys = source["m_Curve"]
    if (value["minMaxState"] != 1 or not _number(value["scalar"], .99, 1)
            or source["m_PostInfinity"] != 1 or not 4 <= len(keys) <= 8
            or keys[0]["time"] != 0 or not _number(keys[-1]["time"], .1, .5)):
        return None
    period = keys[-1]["time"]
    atlas = _atlas(module, deadline, through=period)
    if atlas is None or atlas["tiles"] != [1, 4] or atlas["row"] is not None:
        return None
    frame = atlas["frame"]
    if len(frame[1]) < 4 or any(any(coefficients[:3]) for _, coefficients in frame[1]):
        return None
    return frame, period


def _state(source, name, deadline):
    side = name in ("light_L", "light_R")
    modes = _BASE_MODULES if side else _BASE_MODULES | {"ColorModule", "VelocityModule"}
    if (_enabled(source) != modes or not source["playOnAwake"] or source["lengthInSec"] != 50
            or source["simulationSpeed"] != 1 or source["scalingMode"] != 1 or _constant(source["startDelay"]) != 0
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction"))):
        return None
    if not side:
        velocity = source["VelocityModule"]
        if velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1 or any(
                _constant(velocity[key]) != 0 for key in _VELOCITY):
            return None
    initial = source["InitialModule"]
    speed, lifetime = _constant(initial["startSpeed"]), _constant(initial["startLifetime"])
    x, y, z = (_constant(initial[key]) for key in ("startSize", "startSizeY", "startSizeZ"))
    euler = [_constant(initial[key]) for key in ("startRotationX", "startRotationY", "startRotation")]
    if ((speed, lifetime) != ((-1, 4) if side else (1, 4)) or not _number(x, 2, 5) or y != 1 or z != 1
            or not initial["size3D"] or not initial["rotation3D"] or initial["randomizeRotationDirection"]
            or not all(_number(angle, -2, 2) for angle in euler) or initial["maxNumParticles"] < 4
            or _constant(initial["gravityModifier"]) != 0):
        return None
    # All visible inputs use constant initialization, independent of whether
    # the particle system itself is automatically seeded.
    color = _rgba8(initial, source["ColorModule"])
    size = _size(source["SizeModule"], deadline)
    atlas = _sheet(source["UVModule"], deadline)
    bursts = _bursts(source["EmissionModule"], side=side)
    if color is None or atlas is None or size is None or bursts is None:
        return None
    atlas_curve, period = atlas
    return {"name": name, "particleRotation": euler, "speed": speed, "lifetime": lifetime,
            "duration": source["lengthInSec"], "size": [x, y], "sizeCurve": size, "atlasCurve": atlas_curve,
            "atlasPeriod": period, "color": color["rgba8"], "bursts": bursts}


def _leaf(objects, game, name, deadline):
    row = title._components(objects, game, _COMPONENTS)
    if row is None:
        return None
    _, parts = row
    _, fields = parts["Transform"]
    pose = _authored_trs(fields)
    if (fields["m_Children"] or pose["scale"] != title._IDENTITY["scale"]
            or any(abs(value) > 100 for value in pose["translation"])):
        return None
    renderer, fields = parts["ParticleSystemRenderer"]
    state = _state(parts["ParticleSystem"][1], name, deadline)
    texture = _surface(objects, renderer, fields) if state is not None else None
    if texture is None:
        return None
    return {**state, "position": pose["translation"], "rotation": pose["rotation"],
            "maxViewportWidth": fields["m_MaxParticleSize"], "sortBias": fields["m_SortingFudge"]}, texture


def _prefab(objects, game, deadline):
    outer = title._components(objects, game, {"Transform"})
    if outer is None:
        return None
    transform, fields = outer[1]["Transform"]
    child, = fields["m_Children"]
    if _authored_trs(fields) != title._IDENTITY or fields["m_Father"]["m_PathID"]:
        return None
    root = title._transform_child(objects, transform, child)
    row = title._components(objects, root, _COMPONENTS) if root is not None else None
    if row is None or row[0]["m_Name"] != "root":
        return None
    _, parts = row
    transform, fields = parts["Transform"]
    if (len(fields["m_Children"]) != len(_LEAVES) or _authored_trs(fields) != title._IDENTITY
            or _enabled(parts["ParticleSystem"][1]) != {"InitialModule"} or parts["ParticleSystemRenderer"][1]["m_Enabled"]):
        return None
    found, atlas = {}, None
    for ref in fields["m_Children"]:
        viewer._remaining(deadline)
        child = title._transform_child(objects, transform, ref)
        name = child.peek_name() if child is not None else None
        if name not in _LEAVES or name in found:
            return None
        source = _leaf(objects, child, name, deadline)
        if source is None or (atlas is not None and viewer._key(source[1]) != viewer._key(atlas)):
            return None
        found[name], atlas = source
    return list(found.values()), atlas


def read(objects, mono, tracks, deadline):
    """Return the six typed source strokes for the supported Stage Display cue."""
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
                if original is not None and event["duration"] <= original[0][0]["duration"]:
                    if matches:
                        return None
                    matches.append((track["id"], event["id"], *original))
        except title._UNSUPPORTED:
            continue
    if not matches:
        return None
    track_id, event_id, emitters, atlas = matches[0]
    try:
        texture = particles._texture(atlas, deadline)
    except title._UNSUPPORTED:
        return None
    if not texture or len(texture) != 10:
        return None
    return {"trackId": track_id, "eventId": event_id, "texture": texture, "emitters": emitters}
