"""Read the native floor ripple and glow particles from a stage control prefab."""

import math

from . import model_viewer as viewer
from . import mv_studio_stage_title as native
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import (
    _color, _constant, _constant_range, _float32, _native_draws, _native_lerp, _native_unit, _scalar,
)


_LAYER = 1
_SHADER = (469499217473811506, "cab-7e68b9f01486ca88e5670d5f6b90807c")
_MODULES = {"InitialModule", "EmissionModule", "SizeModule", "RotationModule", "ColorModule", "CustomDataModule"}
_FLOATS = {"_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_ZTestMode": 4, "_ZWriteParam": 0,
           "_StencilComp": 8, "_StencilRef": 2, "_StencilPassOp": 0, "_StencilZFailOp": 0}
_GLOW_SHADER = (7151384334892346267, "cab-adf9ba7b61bd035c754bf74ae44927cb")
_GLOW_MODULES = {"InitialModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule"}
_GLOW_KEYWORDS = {"_ALPHAPREMULTIPLY_ON", "_VERTEXCOLOR_ON", "_VERTEX_COLOR_ON"}
_GLOW_FLOATS = {**_FLOATS, "_SATURATE": 0, "_VERTEX_COLOR": 1}
_WORD_MASK = 0xffffffff


def _material(objects, renderer, fields, *, glow=False):
    refs = fields["m_Materials"]
    if len(refs) != 2 or refs[0] != refs[1]:
        return None
    material = native._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    shader = tree["m_Shader"]
    file_id = shader["m_FileID"]
    externals = material.assets_file.externals
    path, cab = _GLOW_SHADER if glow else _SHADER
    floats = viewer._properties(tree, "m_Floats")
    if (shader["m_PathID"] != path or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab or tree["m_CustomRenderQueue"] != 3010):
        return None
    keywords = set(tree["m_ShaderKeywords"].split())
    if glow:
        if keywords != _GLOW_KEYWORDS or any(floats.get(name) != value for name, value in _GLOW_FLOATS.items()):
            return None
    elif keywords or floats != _FLOATS:
        return None
    color = viewer._properties(tree, "m_Colors")["_TintColor"]
    main = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    tint = [color[axis] for axis in "rgba"]
    uv = [main["m_Scale"][axis] for axis in "xy"] + [main["m_Offset"][axis] for axis in "xy"]
    texture = native._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None or tint != [1, 1, 1, 1] or uv != [1, 1, 0, 0]:
        return None
    # AS/General/Transparent's vertex-color pass multiplies tint and color
    # once, without the additional texture-alpha factor used by the wave.
    return {"tint": tint, "uv": uv, "queue": 3010, "cull": 0, "blend": "add",
            "premultiply": not glow}, texture


def _geometry(objects, renderer, fields, deadline):
    import numpy as np

    mesh = native._local(objects, renderer, fields["m_Mesh"], "Mesh")
    if mesh is None or mesh.peek_name() != "Circle_tex":
        return None
    source = mesh.read()
    if source.m_VertexData.m_VertexCount != 16 or [part.indexCount for part in source.m_SubMeshes] != [24]:
        return None
    viewer._remaining(deadline)
    _, positions, _, uv, partitions = viewer._geometry(mesh, np.eye(4))
    if len(positions) != 16 or uv is None or len(partitions) != 1 or len(partitions[0]) != 8:
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": partitions[0].reshape(-1).tolist()}


def _yaw_rate(seed, authored_range):
    # Unity's RotationModule uses a separately salted copy of the particle seed.
    first = (seed + 0x6aed452e) & _WORD_MASK
    last = (seed * 0x6ab51b9d + 0x00a01275) & _WORD_MASK
    shifted = (first ^ (first << 11)) & _WORD_MASK
    return _native_lerp(*authored_range, _native_unit(last ^ (last >> 19) ^ shifted ^ (shifted >> 8)))


def _records(source, deadline):
    if (source["simulationSpeed"] != 1 or source["autoRandomSeed"] or not source["playOnAwake"]
            or source["moveWithCustomTransform"]["m_PathID"] or _constant(source["startDelay"]) != 0
            or any(source[key] for key in ("moveWithTransform", "scalingMode", "prewarm", "looping",
                                            "stopAction", "ringBufferMode", "cullingMode", "useUnscaledTime"))):
        return None
    modules = {key for key, value in source.items() if key.endswith("Module") and value.get("enabled")}
    if modules != _MODULES:
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    size, rotation, data = source["SizeModule"], source["RotationModule"], source["CustomDataModule"]
    if (initial["size3D"] or not initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(initial[key]) != 0 for key in ("startSpeed", "gravityModifier"))
            or size["separateAxes"] or not rotation["separateAxes"]
            or (data["mode0"], data["vectorComponentCount0"], data["mode1"]) != (1, 2, 0)
            or any(_constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))):
        return None
    if (any(_constant_range(initial[key], 0, 0) is None for key in ("startRotationX", "startRotation"))
            or any(_constant_range(rotation[key], 0, 0) is None for key in ("x", "curve"))):
        return None
    dimension = _constant_range(initial["startSize"], .01, 4)
    yaw = _constant_range(initial["startRotationY"], -8, 8)
    speed = _constant_range(rotation["y"], -2, 2)
    life = _constant(initial["startLifetime"])
    if None in (dimension, yaw, speed) or life is None or not 0 < life <= 3:
        return None
    bursts = emission["m_Bursts"]
    if (not 1 <= len(bursts) <= 4 or emission["m_BurstCount"] != len(bursts)
            or any(not 0 <= burst["time"] < source["lengthInSec"] or burst["probability"] != 1
                   or burst["cycleCount"] != 1 or _constant(burst["countCurve"]) != 1 for burst in bursts)
            or any(a["time"] >= b["time"] for a, b in zip(bursts, bursts[1:]))):
        return None
    scaling = _scalar(size["curve"], deadline)
    color = _color(initial, source["ColorModule"])
    offsets = [_scalar(data[key], deadline) for key in ("vector0_0", "vector0_1")]
    if (scaling is None or color is None or any(curve is None or curve[0] != "cubic" or
            any(any(values[:3]) for _, values in curve[1]) for curve in offsets)):
        return None
    draws = iter(_native_draws(source["randomSeed"], len(bursts) * 7))
    records = []
    for burst in bursts:
        # The native SIMD initializer advances lane zero by seven draws for every single birth.
        seed, _, width, _, _, angle, _ = (next(draws) for _ in range(7))
        records.append({"birth": burst["time"], "lifetime": life, "size": _native_lerp(*dimension, _native_unit(width)),
                        "sizeCurve": scaling, "yaw": -_native_lerp(*yaw, _native_unit(angle)),
                        "yawSpeed": -_yaw_rate(seed, speed), "color": color, "uvOffset": offsets})
    return records


def _wave(objects, game, deadline):
    row = native._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=_LAYER)
    if row is None:
        return None
    parts = row[1]
    _, source = parts["ParticleSystem"]
    renderer, shape = parts["ParticleSystemRenderer"]
    _, transform = parts["Transform"]
    if (transform["m_Children"] or not shape["m_Enabled"] or shape["m_RenderMode"] != 4
            or shape["m_RenderAlignment"] != 1 or not shape["m_UseCustomVertexStreams"]
            or tuple(shape["m_VertexStreams"]) != (0, 1, 3, 4, 32)
            or not shape["m_ApplyActiveColorSpace"] or shape["m_EnableGPUInstancing"]
            or shape["m_Pivot"] != dict(x=0, y=0, z=0)
            or any(shape[key] for key in ("m_SortMode", "m_SortingLayerID", "m_SortingOrder"))
            or any(shape[key]["m_PathID"] for key in ("m_Mesh1", "m_Mesh2", "m_Mesh3"))):
        return None
    records = _records(source, deadline)
    surface = _material(objects, renderer, shape)
    if records is None or surface is None:
        return None
    geometry = _geometry(objects, renderer, shape, deadline)
    if geometry is None:
        return None
    material, texture = surface
    trs = _authored_trs(transform)
    shared = {"geometry": geometry, "position": trs["translation"], "rotation": trs["rotation"],
              "scale": trs["scale"], "material": material}
    return [({**shared, **particle}, texture) for particle in records]


def _sample_gradient(keys, stamp):
    start = keys[0]
    for end in keys[1:]:
        if stamp <= end[0]:
            weight = _float32((max(stamp, start[0]) - start[0]) / (end[0] - start[0]))
            return [_native_lerp(first, last, weight) for first, last in zip(start[1:], end[1:])]
        start = end
    return start[1:]


def _rgba8(initial, module):
    unmultiplied = {"startColor": {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}}
    gradient = _color(unmultiplied, module)
    start = initial["startColor"]
    if gradient is None or _color(initial, module) is None:
        return None
    rgb, alpha = gradient["rgb"], gradient["alpha"]
    stamps = sorted({row[0] for row in (*rgb, *alpha)})

    def byte(value):
        return int(_float32(_float32(value * 255) + .5))

    # Unity combines RGB and alpha times before converting all gradient
    # channels to bytes for its SIMD color-over-lifetime evaluator.
    return {"rgba8": {
        "start": [byte(start["maxColor"][axis]) for axis in "rgba"],
        "keys": [[_float32(stamp), *map(byte, _sample_gradient(rgb, stamp) + _sample_gradient(alpha, stamp))]
                 for stamp in stamps],
    }}


def _glow_geometry(sheet):
    if (sheet["mode"] or sheet["timeMode"] or sheet["animationType"] or sheet["cycles"] != 1
            or sheet["flipU"] or sheet["flipV"] or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0):
        return None
    columns, rows = sheet["tilesX"], sheet["tilesY"]
    offset = _constant(sheet["startFrame"])
    if not (1 <= columns <= 8 and 1 <= rows <= 8 and offset is not None and 0 <= offset < 1):
        return None
    frame = int(_float32(offset * columns * rows))
    column, row = frame % columns, frame // columns
    positions = [[.5, .5, 0], [-.5, .5, 0], [-.5, -.5, 0], [.5, -.5, 0]]
    uv = [[(column + x) / columns, (row + y) / rows] for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
    return {"positions": positions, "uv": uv, "indices": [0, 2, 1, 0, 3, 2]}


def _glow(objects, game, deadline):
    row = native._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=_LAYER)
    if row is None:
        return None
    parts = row[1]
    _, source = parts["ParticleSystem"]
    renderer, shape = parts["ParticleSystemRenderer"]
    _, transform = parts["Transform"]
    trs = _authored_trs(transform)
    if (transform["m_Children"] or trs["rotation"] != native._IDENTITY["rotation"]
            or trs["scale"] != native._IDENTITY["scale"] or not shape["m_Enabled"]
            or shape["m_RenderMode"] != 0 or shape["m_RenderAlignment"] != 1
            or shape["m_UseCustomVertexStreams"] or tuple(shape["m_VertexStreams"]) != (0, 1, 3, 4)
            or not shape["m_ApplyActiveColorSpace"] or not shape["m_AllowRoll"]
            or shape["m_MaxParticleSize"] != 2
            or any(shape[key] for key in ("m_MinParticleSize", "m_SortMode", "m_SortingLayerID", "m_SortingOrder",
                                          "m_MaskInteraction", "m_CameraVelocityScale", "m_VelocityScale"))
            or any(shape[key][axis] for key in ("m_Pivot", "m_Flip") for axis in "xyz")
            or any(shape[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3"))):
        return None
    modules = {key for key, value in source.items() if key.endswith("Module") and value.get("enabled")}
    if (modules != _GLOW_MODULES or source["simulationSpeed"] != 1 or not source["autoRandomSeed"]
            or not source["playOnAwake"] or source["moveWithCustomTransform"]["m_PathID"]
            or _constant(source["startDelay"]) != 0 or any(source[key] for key in (
                "moveWithTransform", "scalingMode", "prewarm", "looping", "stopAction", "ringBufferMode",
                "cullingMode", "useUnscaledTime"))):
        return None
    initial, emission, size = source["InitialModule"], source["EmissionModule"], source["SizeModule"]
    bursts = emission["m_Bursts"]
    if (initial["size3D"] or not initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(initial[key]) != 0 for key in ("startSpeed", "gravityModifier"))
            or size["separateAxes"] or any(_constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))
            or len(bursts) != 1 or emission["m_BurstCount"] != 1):
        return None
    (burst,) = bursts
    if (burst["time"] != 0 or burst["probability"] != 1 or burst["cycleCount"] != 1
            or _constant(burst["countCurve"]) != 1):
        return None
    dimension, life = _constant(initial["startSize"]), _constant(initial["startLifetime"])
    tilt = _constant_range(initial["startRotationX"], -math.pi, math.pi)
    roll = _constant_range(initial["startRotation"], -math.pi, math.pi)
    if (dimension is None or not 0 < dimension <= 4 or life is None or not 0 < life <= 3
            or tilt is None or tilt[0] != tilt[1] or roll is None or roll[0] > roll[1]
            or _constant_range(initial["startRotationY"], 0, 0) is None):
        return None
    geometry = _glow_geometry(source["UVModule"])
    size_curve = _scalar(size["curve"], deadline)
    color = _rgba8(initial, source["ColorModule"])
    surface = _material(objects, renderer, shape, glow=True)
    if None in (geometry, size_curve, color, surface):
        return None
    material, texture = surface
    # World billboard uses Rx(-tilt) * Rz(-roll) before reflecting X. The
    # reflected roll is drawn at activation; the clip's seed override is off.
    rotation = [-math.sin(tilt[0] / 2), 0, 0, math.cos(tilt[0] / 2)]
    emitter = {"geometry": geometry, "position": trs["translation"], "rotation": rotation, "rollRange": roll,
               "scale": trs["scale"], "material": material, "birth": 0, "lifetime": life, "size": dimension,
               "sizeCurve": size_curve, "yaw": 0, "yawSpeed": 0, "color": color}
    return emitter, texture


def read(objects, game, deadline, *, clip_seed=None):
    """Read supported emitters in a local floor-wave control prefab."""
    for depth in range(2):
        row = native._components(objects, game, {"Transform"}, layer=_LAYER)
        if row is None:
            return None
        transform, fields = row[1]["Transform"]
        if _authored_trs(fields) != native._IDENTITY or (depth == 0 and fields["m_Father"]["m_PathID"]):
            return None
        refs = fields["m_Children"]
        if len(refs) != 1:
            break
        game = native._transform_child(objects, transform, refs[0])
        if game is None:
            return None
    if len(refs) != 2:
        return None
    candidates = [native._transform_child(objects, transform, ref) for ref in refs]
    waves = [child for child in candidates if child is not None and child.peek_name() == "wave"]
    records = _wave(objects, waves[0], deadline) if len(waves) == 1 else None
    glows = [child for child in candidates if child is not None and child.peek_name() == "glow"]
    if records and len(glows) == 1:
        try:
            glow = _glow(objects, glows[0], deadline)
        except native._UNSUPPORTED:
            glow = None
        if glow is not None:
            records.append(glow)
    return records
