"""Read Aion Expert's prewarmed glow billboard source and its two control cues."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard
from . import mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title
from . import mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_finale_floor import _SURFACE
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_title_particles import _constant, _float32


TRACK = "StageEffect/Expert/Control/par_09_glow"
_PREFAB = 5696484781506471570
_MATERIAL_ID = 141724214817085144
_TEXTURE_ID = -1608014405097343276
_DIMENSIONS = (256, 128)
_SEED = -1735008856
_STATE = {**billboard._SETTINGS, "lengthInSec": _float32(.1), "cullingMode": 3, "looping": True,
          "prewarm": True, "autoRandomSeed": False, "randomSeed": _SEED, "ringBufferLoopRange": {"x": 0, "y": 1}}
_RENDERER = {**billboard._RENDERER, "m_RenderingLayerMask": 0xFFFFFFFF, "m_SortMode": 3, "m_MaxParticleSize": 8,
             "m_Flip": billboard._ZERO, "m_EnableGPUInstancing": False, "m_ApplyActiveColorSpace": False}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "ShapeModule", "SizeModule", "UVModule", "VelocityModule"}
_MATERIAL = {"queue": 3010, "cull": 0, "blend": "add", "saturate": False, "premultiply": False,
             "tint": [1, 1, 1, 1], "stencil": "always", "stencilRef": 2}
_LOW, _SLOPE = _float32(.8), .7999999523162842
_SIZE_MIN = ((0, _LOW, _SLOPE, _SLOPE), (.25, 1, 0, 0), (.5, _LOW, 0, 0), (.75, 1, 0, 0),
             (1, _LOW, -_SLOPE, -_SLOPE))
_SIZE_MAX = ((0, 1, -_SLOPE, -_SLOPE), (.25, _LOW, 0, 0), (.5, 1, 0, 0), (.75, _LOW, 0, 0),
             (1, 1, _SLOPE, _SLOPE))


def _color(source, initial):
    start = initial["startColor"]
    life = source["ColorModule"]["gradient"]
    if start["minMaxState"] != 4 or life["minMaxState"] != 3:
        return None
    rgb = shine._gradient(start["maxGradient"], "ctime", 4, "rgb", mode=1)
    alpha = shine._gradient(start["maxGradient"], "atime", 5, "a", mode=1)
    fades = [life[key] for key in ("minGradient", "maxGradient")]
    keys = [shine._gradient(row, "atime", count, "a") for row, count in zip(fades, (8, 7))]
    if (rgb is None or alpha is None or any(row is None for row in keys)
            or any(shine._gradient(row, "ctime", 2, "rgb") != [[0, 1, 1, 1], [65535, 1, 1, 1]] for row in fades)):
        return None
    return {"startColor": {"rgb": rgb, "alpha": alpha}, "alphaKeys": keys}


def _system(source):
    active = {name for name, module in source.items() if name.endswith("Module") and module.get("enabled")}
    if active != _MODULES or not billboard._matches(source, _STATE) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    if (not billboard._matches(initial, {"rotation3D": False, "size3D": True, "randomizeRotationDirection": 0,
                                        "maxNumParticles": 100})
            or _constant(initial["startSpeed"]) != 0
            or any(not shine._range(initial[name], *values) for name, values in (
                ("startLifetime", (6, 8)), ("startSize", (3, 1.5)), ("startSizeY", (3, 1.5)), ("startSizeZ", (0, 0)),
                ("startRotation", (6.283185005187988, 0)), ("gravityModifier", (0, 0))))):
        return None
    emission = source["EmissionModule"]
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or _constant(emission["rateOverTime"]) != 5):
        return None
    shape = source["ShapeModule"]
    if not leaves._shape(shape, scale=tuple(map(_float32, (2.98, 2.6, 11.69))), rotation=(0, 90, 0), random_direction=1):
        return None
    velocity = source["VelocityModule"]
    if (velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1
            or any(_constant(velocity[name]) != 0 for name in ("radial", "orbitalX", "orbitalY", "orbitalZ",
                                                               "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))
            or any(not shine._range(velocity[name], -.3, .3) for name in ("x", "y"))
            or not shine._range(velocity["z"], 0, 0)):
        return None
    size = source["SizeModule"]
    curve = size["curve"]
    if (size["separateAxes"] or (curve["minMaxState"], curve["minScalar"], curve["scalar"]) != (2, 1, 1)
            or not leaves._keyframes_match(curve["minCurve"], _SIZE_MIN)
            or not leaves._keyframes_match(curve["maxCurve"], _SIZE_MAX)):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 4,
                                       "tilesY": 1, "flipU": 0, "flipV": 0, "randomRow": True})
            or not sheet["uvChannelMask"] & 1 or _constant(sheet["frameOverTime"]) != 0
            or _constant(sheet["startFrame"]) != .5):
        return None
    return _color(source, initial)


def _texture(objects, renderer, fields):
    material = title._local(objects, renderer, {"m_FileID": 0, "m_PathID": _MATERIAL_ID}, "Material")
    if material is None or fields["m_Materials"] != [{"m_FileID": 0, "m_PathID": _MATERIAL_ID}] * 2:
        return None
    tree = material.read_typetree()
    if (not billboard._matches(tree, {"m_Name": "mat_par_gen_add_24", "m_CustomRenderQueue": 3010,
                                      "m_ShaderKeywords": "_VERTEX_COLOR_ON", "stringTagMap": [], "disabledShaderPasses": []})
            or not _shader_matches(material, tree, "AS/General/Transparent")
            or not billboard._matches(viewer._properties(tree, "m_Floats"), _SURFACE)
            or viewer._properties(tree, "m_Colors").get("_TintColor") != billboard._WHITE):
        return None
    textures = viewer._properties(tree, "m_TexEnvs")
    main = textures["_MainTex"]
    if (not billboard._matches(main, {"m_Texture": {"m_FileID": 0, "m_PathID": _TEXTURE_ID},
                                       "m_Scale": dict.fromkeys("xy", 1), "m_Offset": dict.fromkeys("xy", 0)})
            or any(name != "_MainTex" and env["m_Texture"]["m_PathID"] for name, env in textures.items())):
        return None
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None:
        return None
    native = texture.read()
    settings = native.m_TextureSettings
    if ((native.m_Name, native.m_Width, native.m_Height, native.m_TextureFormat, native.m_MipCount, native.m_ColorSpace,
         native.m_ImageCount, native.m_TextureDimension, native.m_StreamingMipmaps) != ("tex_par_gen_15", *_DIMENSIONS, 65, 9, 1, 1, 2, False)
            or (settings.m_FilterMode, settings.m_Aniso, settings.m_MipBias, settings.m_WrapU,
                settings.m_WrapV, settings.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return texture


def _prefab(objects, game, deadline):
    position = [0, 0, 0]
    for name, translation in (("fx_par_so2028_09", [0, 0, 0]), ("root", [0, 0, -5.5])):
        body = title._components(objects, game, {"Transform"}, layer=1) if game is not None else None
        if body is None or body[0]["m_Name"] != name:
            return None
        node, fields = body[1]["Transform"]
        if (_authored_trs(fields) != {**title._IDENTITY, "translation": translation}
                or name == "fx_par_so2028_09" and fields["m_Father"] != billboard._NULL):
            return None
        position = [a + b for a, b in zip(position, translation)]
        child, = fields["m_Children"]
        game = title._transform_child(objects, node, child)
    body = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=1) if game is not None else None
    if body is None or body[0]["m_Name"] != "glow_F":
        return None
    parts = body[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    if (transform["m_Children"] or pose["translation"] != [-_float32(2.77), _float32(2.48), 6]
            or pose["scale"] != title._IDENTITY["scale"]
            or transform["m_LocalRotation"] != dict(zip("xyzw", (0, .9848077893257141, 0, .17364825308322906)))):
        return None
    renderer, fields = parts["ParticleSystemRenderer"]
    if not billboard._matches(fields, _RENDERER):
        return None
    system = _system(parts["ParticleSystem"][1])
    if system is None:
        return None
    source = _texture(objects, renderer, fields)
    levels = particles._texture(source, deadline, dimensions=_DIMENSIONS) if source is not None else None
    if not levels:
        return None
    return {**system, "texture": levels, "material": _MATERIAL, "uv": [.25, 1, .5, 0], "rate": 5,
            "seed": _SEED & 0xFFFFFFFF, "sortMode": fields["m_SortMode"], "maxViewportWidth": fields["m_MaxParticleSize"],
            "position": [a + b for a, b in zip(position, pose["translation"])],
            "rotation": pose["rotation"], "scale": pose["scale"]}


def read(objects, mono, tracks, deadline):
    matches = [track for track in tracks if track["label"] == TRACK and not track.get("binding") and not track.get("bindings")]
    if len(matches) != 1:
        return None
    track, = matches
    source = next(((owner, fields) for key, (owner, fields, kind) in mono.items()
                   if kind == "CustomControlTrack" and timeline._id(key) == track["id"]), None)
    if source is None:
        return None
    owner, fields = source
    try:
        if (not billboard._matches(fields, {"m_Name": "par_09_glow", "m_Enabled": True, "m_Muted": False})
                or not 1 <= len(fields["m_Clips"]) <= 2 or not 1 <= len(track["events"]) <= 2
                or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                or not title._group(objects, owner, fields, section="control")):
            return None
        cues, prefab = [], None
        for event in track["events"]:
            overwrite = event["values"].get("overwriteRandomSeed")
            if type(overwrite) is not int or overwrite not in (0, 1):
                continue
            control = particles._source(objects, owner, fields, event, overwrite_seed=bool(overwrite))
            if control is None or control[0].path_id != _PREFAB:
                continue
            prefab, seed = control
            cues.append({"trackId": track["id"], "eventId": event["id"], "overwriteRandomSeed": bool(overwrite),
                         "seed": seed if overwrite else _SEED & 0xFFFFFFFF})
        stage = _prefab(objects, prefab, deadline) if cues else None
    except title._UNSUPPORTED:
        return None
    return {"schema": 1, **stage, "cues": cues} if stage is not None else None
