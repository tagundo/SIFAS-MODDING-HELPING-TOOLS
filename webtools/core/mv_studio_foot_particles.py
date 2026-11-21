"""Read the native timed floor-wave mesh particles from a stage control prefab."""

from . import model_viewer as viewer
from . import mv_studio_stage_title as native
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import (
    _color, _constant, _constant_range, _native_draws, _native_lerp, _native_unit, _scalar,
)


_LAYER = 1
_SHADER = (469499217473811506, "cab-7e68b9f01486ca88e5670d5f6b90807c")
_MODULES = {"InitialModule", "EmissionModule", "SizeModule", "RotationModule", "ColorModule", "CustomDataModule"}
_FLOATS = {"_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_ZTestMode": 4, "_ZWriteParam": 0,
           "_StencilComp": 8, "_StencilRef": 2, "_StencilPassOp": 0, "_StencilZFailOp": 0}
_WORD_MASK = 0xffffffff


def _material(objects, renderer, fields):
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
    if (shader["m_PathID"] != _SHADER[0] or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != _SHADER[1]
            or tree["m_ShaderKeywords"] or tree["m_CustomRenderQueue"] != 3010
            or viewer._properties(tree, "m_Floats") != _FLOATS):
        return None
    color = viewer._properties(tree, "m_Colors")["_TintColor"]
    main = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    tint = [color[axis] for axis in "rgba"]
    uv = [main["m_Scale"][axis] for axis in "xy"] + [main["m_Offset"][axis] for axis in "xy"]
    texture = native._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None or tint != [1, 1, 1, 1] or uv != [1, 1, 0, 0]:
        return None
    return {"tint": tint, "uv": uv, "queue": 3010, "cull": 0, "blend": "add", "premultiply": True}, texture


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


def read(objects, game, deadline):
    """Read the original Circle_tex emitter in a local stage control prefab."""
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
    return _wave(objects, waves[0], deadline) if len(waves) == 1 else None
