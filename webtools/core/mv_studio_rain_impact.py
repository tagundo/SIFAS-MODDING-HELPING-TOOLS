"""Read the horizontal ripple and its birth-triggered glow in Aion Expert."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine
from . import mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_finale_floor import _SURFACE
from .mv_studio_foot_particles import _GLOW_FLOATS, _GLOW_KEYWORDS
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_title_particles import _constant, _float32


_Y = _float32(.01)
_ROLL = 1.570796251296997
_FRAME_SCALE = _float32(.9999)
_RENDERER = {**billboard._RENDERER, "m_RenderMode": 2, "m_MaxParticleSize": 2, "m_Flip": billboard._ZERO}
_MODULES = billboard._MODULES | {"ColorModule"}
_PARTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_WAVE_MATERIAL = (3937121538133114394, "mat_par_so2028_add_02", -6015316119998467099, "tex_par_so2028_02")
_GLOW_MATERIAL = (526642120773255349, "mat_par_gen_add_16", -1972939777780254603, "tex_grs_par_gen_09")


def _curve(source, multiplier, *, tangent_limit):
    if (source["minMaxState"] != 1 or source["scalar"] != multiplier or source["minCurve"]["m_Curve"]):
        return None
    maximum = source["maxCurve"]
    keys = maximum["m_Curve"]
    if (len(keys) != 2 or (keys[0]["time"], keys[1]["time"]) != (0, 1)
            or (maximum["m_PreInfinity"], maximum["m_PostInfinity"]) != (2, 2)
            or any(key["weightedMode"] or not 0 <= key["value"] <= 1
                   or not all(-tangent_limit <= key[name] <= tangent_limit for name in ("inSlope", "outSlope"))
                   for key in keys)):
        return None
    return [[key[name] for name in ("time", "value", "inSlope", "outSlope")] for key in keys]


def _gradient(gradient, rgb_count, alpha_count):
    rgb = shine._gradient(gradient, "ctime", rgb_count, "rgb")
    alpha = shine._gradient(gradient, "atime", alpha_count, "a")
    if not rgb or not alpha or any(rows[0][0] != 0 or rows[-1][0] != 65535 for rows in (rgb, alpha)):
        return None
    return {"rgb": rgb, "alpha": alpha}


def _colors(source, opening, wave):
    life = source["ColorModule"]["gradient"]
    start = source["InitialModule"]["startColor"]
    if life["minMaxState"] != 1:
        return None
    lifetime = _gradient(life["maxGradient"], 2 if wave and opening else 4, 4 if wave else 3)
    if wave:
        mode = 1 if opening else 4
        color = _gradient(start["maxGradient"], 3, 2)
        if color is None or start["minMaxState"] != mode:
            return None
        initial = {"mode": mode, **color}
    else:
        alpha = _float32(38 / 255 if opening else .4)
        initial = [start["maxColor"][channel] for channel in "rgba"]
        if start["minMaxState"] or initial != [1, 1, 1, alpha]:
            return None
    return {"colorKeys": lifetime, "startColor": initial} if lifetime is not None else None


def _shape(source):
    if (not billboard._matches(source, {"type": 5, "placementMode": 0, "radiusThickness": 1, "alignToDirection": False,
                                       "m_Position": {"x": 0, "y": _Y, "z": 1}, "m_Rotation": billboard._ZERO,
                                       "boxThickness": billboard._ZERO, "m_Scale": {"x": 16, "y": 0, "z": 10}})
            or any(source[name] for name in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(source[name] != billboard._NULL for name in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                                 "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return False
    return all(billboard._matches(source[name], {"mode": 0, "spread": 0, "value": value})
               and _constant(source[name]["speed"]) == 1 for name, value in (("radius", 1), ("arc", 360)))


def _settings(source, opening, wave):
    expected = {**billboard._SETTINGS, "lengthInSec": 5 if opening else 2.5, "looping": opening, "prewarm": opening,
                "randomSeed": 1950736341 if opening else 1, "autoRandomSeed": False}
    modules = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    enabled = _MODULES | {"ShapeModule", "SubModule"} if wave else _MODULES
    if modules != enabled or not billboard._matches(source, expected) or _constant(source["startDelay"]) != 0:
        return False
    initial = source["InitialModule"]
    if (not billboard._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 3000,
                                        "randomizeRotationDirection": 0})
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "gravityModifier"))
            or not shine._range(initial["startRotation"], -_ROLL, _ROLL)):
        return False
    life = initial["startLifetime"]
    life_matches = (_constant(life) == _float32(.6) if wave and opening
                    else shine._range(life, .4 if wave else .2, .6 if wave else .4))
    width = (.2, .3) if wave and not opening else (.3, .4)
    if not life_matches or not shine._range(initial["startSize"], *width):
        return False
    emission = source["EmissionModule"]
    rate = (100 if opening else 30) if wave else 0
    if _constant(emission["rateOverTime"]) != rate or _constant(emission["rateOverDistance"]) != 0:
        return False
    bursts = emission["m_Bursts"]
    if wave:
        return emission["m_BurstCount"] == 0 and not bursts and _shape(source["ShapeModule"])
    if emission["m_BurstCount"] != 1 or len(bursts) != 1:
        return False
    burst = bursts[0]
    return (billboard._matches(burst, {"time": 0, "cycleCount": 1, "probability": 1})
            and _constant(burst["countCurve"]) == 1)


def _profile(source, opening, wave):
    if not _settings(source, opening, wave):
        return None
    colors = _colors(source, opening, wave)
    size = source["SizeModule"]
    size_keys = _curve(size["curve"], 1, tangent_limit=8)
    if colors is None or size_keys is None or size["separateAxes"]:
        return None
    tiles = 4 if wave else 2
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": tiles,
                                       "tilesY": tiles, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["startFrame"]) != (0 if wave else .75)):
        return None
    result = {**colors, "sizeKeys": size_keys, "maxViewportWidth": 2}
    if wave:
        frames = _curve(sheet["frameOverTime"], _FRAME_SCALE, tangent_limit=4)
        if frames is None or [row[1] for row in frames] != [0, 1]:
            return None
        result.update({"frameKeys": frames, "tiles": [4, 4]})
    elif _constant(sheet["frameOverTime"]) == 0:
        result["uv"] = [.5, .5, .5, .5]
    else:
        return None
    return result


def _material(objects, renderer, fields, opening, wave):
    alignment = 0 if wave and not opening else 1
    extra_stream = wave and opening
    shape = {**_RENDERER, "m_EnableGPUInstancing": not extra_stream, "m_RenderAlignment": alignment,
             "m_VertexStreams": [0, 1, 3, 4, 32] if extra_stream else [0, 1, 3, 4]}
    if not billboard._matches(fields, shape):
        return None
    material_id, name, texture_id, texture_name = _WAVE_MATERIAL if wave else _GLOW_MATERIAL
    refs = fields["m_Materials"]
    if refs != [{"m_FileID": 0, "m_PathID": material_id}] * 2:
        return None
    material = title._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    if (not billboard._matches(tree, {"m_Name": name, "m_CustomRenderQueue": 3010, "stringTagMap": [], "disabledShaderPasses": []})
            or not _shader_matches(material, tree, "AS/General/Transparent")
            or viewer._properties(tree, "m_Colors").get("_TintColor") != billboard._WHITE):
        return None
    values = viewer._properties(tree, "m_Floats")
    keywords = set(tree["m_ShaderKeywords"].split())
    if wave:
        if values != {**_SURFACE, "_CullMode": 2, "_SATURATE": 1} or keywords != {"_SATURATE_ON", "_VERTEX_COLOR_ON"}:
            return None
    elif not billboard._matches(values, _GLOW_FLOATS) or keywords != _GLOW_KEYWORDS:
        return None
    textures = viewer._properties(tree, "m_TexEnvs")
    main = textures["_MainTex"]
    if (any(name != "_MainTex" and ref["m_Texture"]["m_PathID"] for name, ref in textures.items())
            or not billboard._matches(main, {"m_Texture": {"m_FileID": 0, "m_PathID": texture_id},
                                            "m_Scale": dict.fromkeys("xy", 1), "m_Offset": dict.fromkeys("xy", 0)})):
        return None
    reader = title._local(objects, material, main["m_Texture"], "Texture2D")
    if reader is None:
        return None
    texture = reader.read()
    sampler = texture.m_TextureSettings
    if ((texture.m_Name, texture.m_Width, texture.m_Height, texture.m_TextureFormat, texture.m_MipCount,
         texture.m_ColorSpace, texture.m_ImageCount, texture.m_TextureDimension, texture.m_StreamingMipmaps)
            != (texture_name, 256, 256, 65, 9, 1, 1, 2, False)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias, sampler.m_WrapU, sampler.m_WrapV,
                sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return {"queue": 3010, "tint": [1, 1, 1, 1], "blend": "add", "premultiply": False,
            "cull": 2 if wave else 0, "saturate": wave}, reader


def read(objects, parent, fields, profile, deadline):
    """Return the linked floor effects and two original undecoded atlases."""
    try:
        viewer._remaining(deadline)
        opening = profile == "01"
        game = billboard._child(objects, parent, fields, "wave")
        wave = title._components(objects, game, _PARTS, layer=1) if game is not None else None
        if wave is None:
            return None
        wave = wave[1]
        transform, pose = wave["Transform"]
        leaf_z = -1 if opening else 0
        if (_authored_trs(pose) != {**title._IDENTITY, "translation": [0, 0, leaf_z]} or len(pose["m_Children"]) != 1):
            return None
        game = billboard._child(objects, transform, pose, "glow")
        glow = title._components(objects, game, _PARTS, layer=1) if game is not None else None
        if glow is None:
            return None
        glow = glow[1]
        _, pose = glow["Transform"]
        if _authored_trs(pose) != title._IDENTITY or pose["m_Children"]:
            return None
        wave_system, wave_source = wave["ParticleSystem"]
        child_system, glow_source = glow["ParticleSystem"]
        sub, = wave_source["SubModule"]["subEmitters"]
        if (not billboard._matches(sub, {"type": 0, "properties": 0, "emitProbability": 1})
                or title._local(objects, wave_system, sub["emitter"], "ParticleSystem") is not child_system):
            return None
        effects, atlases = {}, {}
        for name, parts, source in (("wave", wave, wave_source), ("glow", glow, glow_source)):
            primary = name == "wave"
            data = _profile(source, opening, primary)
            surface = _material(objects, *parts["ParticleSystemRenderer"], opening, primary)
            if data is None or surface is None:
                return None
            material, atlas = surface
            effects[name], atlases[name] = {**data, "material": material}, atlas
        effects["wave"]["position"] = [0, _float32(_Y * 2), leaf_z + 1]
        return effects, atlases
    except title._UNSUPPORTED:
        return None
