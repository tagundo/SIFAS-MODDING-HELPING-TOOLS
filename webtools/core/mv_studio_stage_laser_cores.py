"""Read the resident Monster Girls laser core emitters and their original atlas."""

from . import decode, model_animation, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_title as title
from .mv_studio_display_lights import _enabled
from .mv_studio_finale_floor import _SURFACE
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_materials import _cube_levels
from .mv_studio_stage_title_particles import _constant, _constant_range, _float32


_STAGE_ROOT = ("bg0021_01_fx_so2056_ex", "fx_par_so2056_05", "root")
_TRACK_ID = "-3114162657147975647"
_TEXTURE_ID = -6744472684846749850
_MATERIAL_ID = -4628503787897855423
_SEED = -1462782512
_ZERO = dict.fromkeys("xyz", 0)
_ONE = dict.fromkeys("xyz", 1)
_ROTATION = {**_ZERO, "w": 1}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "UVModule", "VelocityModule"}
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_BASE_COLOR = [.458823561668396, .7765381932258606, 1., .597691535949707]
_ANIMATED_COLOR = tuple(motion._LASER_CORE_CONSTANTS[model_animation.path_hash(
    f"InitialModule.startColor.maxColor.{component}")] for component in "rgba")


def _components(scene, game):
    tree = scene.tree(game)
    refs = tree["m_Component"]
    if not scene.active(game) or tree["m_Layer"] != 1 or len(refs) != len(_COMPONENTS):
        return None
    parts = {}
    for reference in refs:
        pointer = reference["component"]
        item = viewer._ref(game, pointer)
        if pointer["m_FileID"] != 0 or item is None or item.type.name not in _COMPONENTS:
            return None
        fields = scene.tree(item)
        owner = fields["m_GameObject"]
        if owner["m_FileID"] != 0 or owner["m_PathID"] != game.path_id or item.type.name in parts:
            return None
        parts[item.type.name] = item, fields
    return parts


def _material(scene, renderer, fields):
    if (not fields["m_Enabled"] or not fields["m_AllowRoll"] or fields["m_RenderMode"] != 0
            or fields["m_RenderAlignment"] != 2 or fields["m_MaxParticleSize"] != .5
            or fields["m_LengthScale"] != 2 or fields["m_NormalDirection"] != 1
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_RenderingLayerMask"] != 0xFFFFFFFF or fields["m_VertexStreams"] != [0, 1, 3, 4]
            or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[name] for name in (
                "m_SortMode", "m_SortingFudge", "m_SortingLayerID", "m_SortingLayer", "m_SortingOrder",
                "m_MinParticleSize", "m_CameraVelocityScale", "m_VelocityScale", "m_RendererPriority",
                "m_UseCustomVertexStreams", "m_EnableGPUInstancing", "m_ApplyActiveColorSpace",
                "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows", "m_LightProbeUsage",
                "m_ReflectionProbeUsage"))
            or any(fields[name]["m_PathID"] for name in (
                "m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    # Unity reserves the second slot for trails. TrailModule is disabled here.
    refs = fields["m_Materials"]
    if refs != [{"m_FileID": 0, "m_PathID": _MATERIAL_ID}] * 2:
        return None
    material = viewer._ref(renderer, refs[0])
    return material if material is not None and material.type.name == "Material" else None


def _atlas(scene, material):
    tree = scene.tree(material)
    values = viewer._properties(tree, "m_Floats")
    colors = viewer._properties(tree, "m_Colors")
    textures = viewer._properties(tree, "m_TexEnvs")
    if (tree["m_Name"] != "mat_par_gen_add_26" or tree["m_CustomRenderQueue"] != 3010
            or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON" or tree["stringTagMap"] or tree["disabledShaderPasses"]
            or any(values.get(key) != value for key, value in _SURFACE.items())
            or colors.get("_TintColor") != dict.fromkeys("rgba", 1) or set(textures) != {"_MainTex"}
            or not _shader_matches(material, tree, "AS/General/Transparent")):
        return None
    tex = textures["_MainTex"]
    if (tex["m_Scale"] != dict.fromkeys("xy", 1) or tex["m_Offset"] != dict.fromkeys("xy", 0)
            or tex["m_Texture"] != {"m_FileID": 0, "m_PathID": _TEXTURE_ID}):
        return None
    reader = viewer._ref(material, tex["m_Texture"])
    return reader if reader is not None and reader.type.name == "Texture2D" else None


def _mips(reader, deadline):
    from PIL import Image

    native = reader.read()
    sampler = native.m_TextureSettings
    name = {34: "etc1", 32: "pvrtc4"}.get(native.m_TextureFormat)
    if (not name or native.m_Name != "tex_par_gen_17" or native.m_Width != 512 or native.m_Height != 512
            or native.m_MipCount != 10 or native.m_ImageCount != 1 or native.m_TextureDimension != 2
            or native.m_ColorSpace != 1 or native.m_StreamingMipmaps
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias,
                sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    levels = list(_cube_levels(native.m_Width, name))
    length = sum(level[2] for level in levels)
    if native.m_CompleteImageSize != length or getattr(native.m_StreamData, "size", 0) not in (0, length):
        return None
    blocks = native.get_image_data()
    if len(blocks) != length:
        return None
    offset, result = 0, []
    for side, extent, size in levels:
        with decode._stage_block_image(name, blocks[offset:offset + size], extent, extent, deadline) as image:
            # The last PVRTC levels store a padded 8 × 8 footprint. Crop
            # the native rows before converting their bottom-origin UVs.
            with image.crop((0, 0, side, side)) as level:
                with level.transpose(Image.Transpose.FLIP_TOP_BOTTOM) as upright:
                    result.append(viewer._png_texture(upright, deadline))
        offset += size
    return result


def _velocity_is_zero(velocity):
    if (velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1
            or any(_constant(velocity[key]) != 0 for key in (
                "orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ", "radial"))):
        return False
    # The authored curve pairs are enabled, with zero multipliers for both lanes.
    return all((velocity[axis]["minMaxState"], velocity[axis]["minScalar"], velocity[axis]["scalar"]) == (2, 0, 0)
               for axis in "xyz")


def _profile(system, group, side):
    if (_enabled(system) != _MODULES or not system["playOnAwake"] or not system["looping"]
            or not system["useRigidbodyForVelocity"] or system["randomSeed"] != _SEED
            or system["lengthInSec"] != 200 or system["simulationSpeed"] != 1 or system["scalingMode"] != 1
            or system["cullingMode"] != 3 or _constant(system["startDelay"]) != 0
            or system["moveWithCustomTransform"]["m_PathID"]
            or any(system[name] for name in (
                "autoRandomSeed", "prewarm", "moveWithTransform", "useUnscaledTime", "ringBufferMode", "stopAction"))
            or not _velocity_is_zero(system["VelocityModule"])):
        return None
    initial = system["InitialModule"]
    lifetime = _constant(initial["startLifetime"])
    size = _constant(initial["startSize"])
    roll = _constant_range(initial["startRotation"], 0, 7)
    color = initial["startColor"]
    rgba = [color["maxColor"][axis] for axis in "rgba"]
    expected_color = [.4729999899864197, *_BASE_COLOR[1:]] if (group, side) == (2, "L") else _BASE_COLOR
    if (color["minMaxState"] != 0 or rgba != expected_color
            or (lifetime, size, roll, initial["maxNumParticles"]) != (
                .25, _float32(.8 if group == 1 else .6), (0, _float32(6.283185)), 20)
            or any(initial[name] for name in ("size3D", "rotation3D", "randomizeRotationDirection"))
            or any(_constant(initial[name]) != 0 for name in ("gravityModifier", "startSpeed"))):
        return None
    emission = system["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (len(bursts) != 1 or emission["m_BurstCount"] != 1
            or _constant(emission["rateOverTime"]) != 0 or _constant(emission["rateOverDistance"]) != 0):
        return None
    burst = bursts[0]
    if ((burst["time"], burst["cycleCount"], burst["probability"], burst["repeatInterval"]) != (0, 0, 1, _float32(.08))
            or _constant(burst["countCurve"]) != 1):
        return None
    sheet = system["UVModule"]
    if ((sheet["tilesX"], sheet["tilesY"], sheet["animationType"], sheet["rowIndex"], sheet["cycles"]) != (8, 8, 1, 1, 1)
            or any(sheet[name] for name in ("mode", "timeMode", "randomRow", "flipU", "flipV"))
            or not (sheet["uvChannelMask"] & 1)
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .75):
        return None
    gradient = _rgba8(initial, system["ColorModule"])
    keys = gradient["rgba8"]["keys"] if gradient is not None else None
    alpha_keys = [[_float32(stamp / 65535), alpha] for stamp, alpha in ((0, 0), (655, 255), (64880, 255), (65535, 0))]
    if keys != [[time, 255, 255, 255, alpha] for time, alpha in alpha_keys]:
        return None
    # Single Row, row 1. Native frame .75 selects column 6 of 8.
    return rgba, size, {
        "seed": system["randomSeed"] & 0xFFFFFFFF, "burstPeriod": burst["repeatInterval"],
        "lifetime": lifetime, "rollRange": list(roll), "alphaKeys": alpha_keys,
        "uv": [.125, .125, .75, .125], "maxViewportWidth": .5, "capacity": initial["maxNumParticles"],
    }


def read(scene, stage_nodes, deadline):
    """Return the resident core metadata and the ten source-level PNG images."""
    if stage_nodes.roots.get(_STAGE_ROOT) != motion._LASER_BINDING:
        return None
    candidates = {}
    for key, path in stage_nodes.paths.items():
        relative = path[len(_STAGE_ROOT):]
        if (path[:len(_STAGE_ROOT)] == _STAGE_ROOT and relative and relative[0] == "joint_all"
                and (len(relative) == 2 or len(relative) == 4 and relative[-1] == "core")):
            candidates.setdefault(path, []).append(key)
    emitters, games = [], []
    common, material = None, None
    # Roots 3–6 are inactive in the source and absent from the activation clip.
    try:
        for group in range(3, 7):
            matches = candidates.get((*_STAGE_ROOT, "joint_all", f"Joint_root_{group:02}"), ())
            if len(matches) != 1:
                return None
            transform = scene.transforms[matches[0]]
            game = viewer._ref(transform, scene.tree(transform)["m_GameObject"])
            if scene.tree(game)["m_IsActive"]:
                return None
        for group in (1, 2):
            activation = f"joint_all/Joint_root_{group:02}"
            for side in ("L", "R"):
                path = f"{activation}/{side}/core"
                matches = candidates.get((*_STAGE_ROOT, *path.split("/")), ())
                if len(matches) != 1:
                    return None
                transform = scene.transforms[matches[0]]
                game = viewer._ref(transform, scene.tree(transform)["m_GameObject"])
                parts = _components(scene, game)
                if parts is None:
                    return None
                _, pose = parts["Transform"]
                if (pose["m_Children"] or pose["m_LocalPosition"] != _ZERO
                        or pose["m_LocalRotation"] != _ROTATION or pose["m_LocalScale"] != _ONE):
                    return None
                row = _profile(parts["ParticleSystem"][1], group, side)
                surface = _material(scene, *parts["ParticleSystemRenderer"])
                if row is None or surface is None:
                    return None
                color, size, profile = row
                if (common is not None and common != profile
                        or material is not None and viewer._key(surface) != viewer._key(material)):
                    return None
                common, material = profile, surface
                games.append(game)
                emitters.append({"path": model_animation.path_hash(path),
                                 "activationPath": model_animation.path_hash(activation),
                                 "size": size, "color": color, "animatedColor": list(_ANIMATED_COLOR)})
        reader = _atlas(scene, material)
        mips = _mips(reader, deadline) if reader is not None else None
        if mips is None or not all(stage_nodes.retain(game) for game in games):
            return None
    except title._UNSUPPORTED:
        return None
    return {"binding": motion._LASER_BINDING, "trackId": _TRACK_ID, "eventId": _TRACK_ID + ":0",
            "emitters": emitters, **common}, mips
