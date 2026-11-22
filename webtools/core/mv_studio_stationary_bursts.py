"""Read resident, activation-driven stationary particles drawn in the display pass."""

from . import model_viewer as viewer
from . import mv_studio_butterfly_glow as source
from . import mv_studio_stage_burst as burst
from . import mv_studio_stage_dust as dust
from . import mv_studio_stage_overlay as surface
from . import mv_studio_stage_title as title
from .mv_studio_butterfly_shine import _gradient
from .mv_studio_stage_materials import collect_texture_sampler
from .mv_studio_stage_title_particles import _constant


_LAYER = 26
_MAX_EMITTERS = 24
_UNIT = dict.fromkeys("xyz", 1)
_IDENTITY = {**source._ZERO, "w": 1}
_PARTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_BASE_MODULES = {"InitialModule", "EmissionModule"}
_SETTINGS = {key: value for key, value in source._SETTINGS.items() if key != "lengthInSec"}
_RENDERER = {**source._RENDERER, "m_Flip": source._ZERO}


def _parts(scene, game):
    fields = scene.tree(game)
    refs = fields["m_Component"]
    if fields["m_Layer"] != _LAYER or len(refs) != len(_PARTS):
        return None
    parts = {}
    for value in refs:
        ref = value["component"]
        obj = viewer._ref(game, ref) if ref["m_FileID"] == 0 else None
        if obj is None or obj.type.name not in _PARTS or obj.type.name in parts:
            return None
        tree = scene.tree(obj)
        if tree["m_GameObject"] != {"m_FileID": 0, "m_PathID": game.path_id}:
            return None
        parts[obj.type.name] = obj, tree
    return parts


def _size_keys(fields):
    curve = fields["curve"]
    maximum = curve["maxCurve"]
    keys = maximum["m_Curve"]
    if (fields["separateAxes"] or curve["minMaxState"] != 1 or not dust._number(curve["scalar"], 0, 16)
            or curve["minCurve"]["m_Curve"] or (maximum["m_PreInfinity"], maximum["m_PostInfinity"]) != (2, 2)
            or not 4 <= len(keys) <= 16 or keys[0]["time"] != 0
            or len(keys) == 16 and keys[-1]["time"] != 1):
        return None
    rows = []
    for key in keys:
        stamp, size, enter, exit = (key[name] for name in ("time", "value", "inSlope", "outSlope"))
        if (key["weightedMode"] or not dust._number(stamp, 0, 1) or not dust._number(size, 0, 16)
                or rows and stamp <= rows[-1][0]
                or any(not dust._number(slope, -4096, 4096) for slope in (enter, exit))):
            return None
        rows.append([stamp, size, enter, exit])
    # Unity's clamp post-wrap uses the final authored key. It may precede normalized age one.
    return rows, curve["scalar"]


def _atlas(fields):
    if (not source._matches(fields, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1,
                                    "randomRow": True, "rowIndex": 0, "flipU": 0, "flipV": 0})
            or not fields["uvChannelMask"] & 1 or any(row["sprite"] != source._NULL for row in fields["sprites"])
            or _constant(fields["frameOverTime"]) != 0):
        return None
    columns, rows = fields["tilesX"], fields["tilesY"]
    phase = _constant(fields["startFrame"])
    if (type(columns) is not int or type(rows) is not int or not 1 <= columns <= 16 or not 1 <= rows <= 16
            or not dust._number(phase, 0, 1)):
        return None
    index = int(phase * columns * rows) % (columns * rows)
    return [1 / columns, 1 / rows, (index % columns) / columns, (index // columns) / rows]


def _color_over_life(fields):
    if fields["minMaxState"] != 1:
        return None
    gradient = fields["maxGradient"]
    result = {}
    for field, prefix, channels in (("m_NumColorKeys", "ctime", "rgb"), ("m_NumAlphaKeys", "atime", "a")):
        count = gradient[field]
        rows = _gradient(gradient, prefix, count, channels) if type(count) is int and 2 <= count <= 8 else None
        if rows is None or rows[0][0] != 0:
            return None
        # Unity holds the last authored value across the remainder of the gradient.
        if rows[-1][0] != 65535:
            if len(rows) == 8:
                return None
            rows.append([65535, *rows[-1][1:]])
        result["alpha" if channels == "a" else "rgb"] = rows
    return result


def _profile(system, mode):
    active = {name for name, fields in system.items() if name.endswith("Module") and fields.get("enabled")}
    required = _BASE_MODULES | ({"ColorModule"} if mode == "mesh" else {"SizeModule", "UVModule"})
    duration, delay = system["lengthInSec"], _constant(system["startDelay"])
    if (not required <= active <= required | {"ColorModule"} or not source._matches(system, _SETTINGS)
            or system["ringBufferLoopRange"] != {"x": 0, "y": 1}
            or not dust._number(duration, .01, 120) or not dust._number(delay, 0, duration)):
        return None
    initial = system["InitialModule"]
    lifetime = _constant(initial["startLifetime"])
    sized = mode == "billboard"
    dimensions = ("startSize", "startSizeY", "startSizeZ") if sized else ("startSize",) * 3
    size = [_constant(initial[name]) for name in dimensions]
    start = initial["startColor"]
    color = [start["maxColor"][axis] for axis in "rgba"]
    if (not source._matches(initial, {"size3D": sized, "rotation3D": False, "randomizeRotationDirection": 0})
            or not dust._number(lifetime, .01, 10) or any(not dust._number(value, .001, 20) for value in size)
            or start["minMaxState"] != 0 or any(not dust._number(value, 0, 1) for value in color)
            or type(initial["maxNumParticles"]) is not int or initial["maxNumParticles"] < 1
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "gravityModifier", "startRotation"))):
        return None
    schedule = burst._burst(system["EmissionModule"], duration)
    if schedule is None or schedule["cycles"] != 1:
        return None
    result = {"mode": mode, "duration": duration, "delay": delay, "lifetime": lifetime, "size": size,
              "startColor": color}
    if "ColorModule" in active:
        color_over_life = _color_over_life(system["ColorModule"]["gradient"])
        if color_over_life is None:
            return None
        result["colorOverLife"] = color_over_life
    if sized:
        sizes, uv = _size_keys(system["SizeModule"]), _atlas(system["UVModule"])
        if sizes is None or uv is None:
            return None
        result.update(sizeKeys=sizes[0], sizeMultiplier=sizes[1], uv=uv)
    return result


def _geometry(obj, deadline):
    import numpy as np

    tree = obj.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    channels = vertices["m_Channels"]
    if (not 0 < vertices["m_VertexCount"] <= 512 or len(submeshes) != 1 or submeshes[0]["topology"] != 0
            or not 0 < submeshes[0]["indexCount"] <= 3072 or channels[3]["dimension"]
            or channels[0]["dimension"] != 3 or channels[4]["dimension"] != 2
            or tree["m_BindPose"] or tree["m_MeshCompression"] or tree["m_StreamData"]["size"]
            or any(tree["m_Shapes"].values())):
        return None
    _, positions, _, uv, faces = viewer._geometry(obj, np.eye(4), deadline=deadline)
    if (uv is None or uv.shape != (len(positions), 2) or not np.isfinite(uv).all()
            or len(faces) != 1 or not faces[0].size):
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].reshape(-1).tolist()}


def _paint(scene, renderer, fields, mode):
    references = fields["m_Materials"]
    if not references or len(references) > 2 or any(item != references[0] and item != source._NULL for item in references):
        return None
    material = viewer._ref(renderer, references[0])
    details = surface.read_material(scene, material, world=True)
    if (details is None or details["texture"] is None
            or not source._matches(details, {"alphaBlend": True, "depthTest": True, "stencilRef": 2,
                                             "queue": 2900, "vertexColor": True})
            or details["cull"] not in (0, 2)
            or scene.tree(material)["disabledShaderPasses"] or scene.tree(material)["stringTagMap"]):
        return None
    texture, uv = details.pop("texture"), details.pop("uv")
    if mode == "billboard" and uv != [1, 1, 0, 0]:
        return None
    native = texture.read()
    sampler = native.m_TextureSettings
    if (native.m_ColorSpace != 1 or native.m_TextureDimension != 2 or native.m_ImageCount != 1
            or not 0 < native.m_Width <= 2048 or not 0 < native.m_Height <= 2048
            or (sampler.m_FilterMode, sampler.m_MipBias, sampler.m_WrapU, sampler.m_WrapV) != (1, 0, 0, 0)):
        return None
    mapped = [uv[0], uv[1], uv[2], 1 - uv[1] - uv[3]]
    return (texture, details, mapped) if all(-64 <= value <= 64 for value in mapped) else None


def _emitter(scene, parts, deadline):
    renderer, fields = parts["ParticleSystemRenderer"]
    pointer = fields["m_Mesh"]
    maximum = fields["m_MaxParticleSize"]
    if (fields["m_RenderMode"], fields["m_RenderAlignment"], fields["m_SortMode"]) == (4, 1, 1):
        mode = "mesh"
        flip_x = False
        expected = {"m_Mesh": pointer, "m_RenderMode": 4, "m_RenderAlignment": 1, "m_SortMode": 1,
                    "m_MaxParticleSize": maximum, "m_EnableGPUInstancing": False}
    elif (fields["m_RenderMode"], fields["m_RenderAlignment"], fields["m_SortMode"]) == (0, 2, 0):
        mode = "billboard"
        flip = fields["m_Flip"]
        if flip["x"] not in (0, 1) or flip["y"] or flip["z"]:
            return None
        flip_x = flip["x"] == 1
        expected = {"m_RenderAlignment": 2, "m_MaxParticleSize": maximum, "m_Flip": flip}
    else:
        return None
    if not dust._number(maximum, .001, 5) or not source._matches(fields, {**_RENDERER, **expected}):
        return None
    row = _profile(parts["ParticleSystem"][1], mode)
    paint = _paint(scene, renderer, fields, mode) if row is not None else None
    if paint is None:
        return None
    texture, material, uv = paint
    if flip_x:
        if material["cull"] != 0:
            return None
        row["flipX"] = True
    if mode == "mesh":
        mesh = viewer._ref(renderer, pointer) if pointer["m_FileID"] == 0 else None
        geometry = _geometry(mesh, deadline) if mesh is not None and mesh.type.name == "Mesh" else None
        if geometry is None:
            return None
        row.update(geometry=geometry, uv=uv)
    return {**row, "maxViewportWidth": maximum, "material": material}, texture


def _activation_path(scene, stage_nodes, game, transform, binding, *, world_mesh):
    inactive = None
    for _ in range(64):
        pose = scene.tree(transform)
        if pose["m_LocalScale"] != _UNIT or world_mesh and pose["m_LocalRotation"] != _IDENTITY:
            return None
        if not scene.tree(game)["m_IsActive"]:
            owner = stage_nodes.binding(game)
            if inactive is not None or owner is None or owner[0] != binding:
                return None
            inactive = owner[1]
        father = pose["m_Father"]
        if father == source._NULL:
            return inactive
        transform = viewer._ref(transform, father)
        if transform is None:
            return None
        game = viewer._ref(transform, scene.tree(transform)["m_GameObject"])
        if game is None:
            return None
    return None


def read_bound(scene, stage_nodes, materials, deadline):
    """Retain exact supported emitters and the inactive ancestor's animation path."""
    result = []
    for key in stage_nodes.paths:
        viewer._remaining(deadline)
        transform = scene.transforms[key]
        game = viewer._ref(transform, scene.tree(transform)["m_GameObject"])
        if game is None:
            continue
        binding = stage_nodes.binding(game)
        if binding is None or not binding[1]:
            continue
        try:
            parts = _parts(scene, game)
            if parts is None:
                continue
            world_mesh = parts["ParticleSystemRenderer"][1]["m_RenderMode"] == 4
            activation = _activation_path(scene, stage_nodes, game, transform, binding[0], world_mesh=world_mesh)
            if activation is None:
                continue
            value = _emitter(scene, parts, deadline)
            if value is None:
                continue
            row, texture = value
            index = materials.texture(texture)
            if index is not None and stage_nodes.retain(game):
                row.update(binding=binding[0], path=binding[1], activationPath=activation, texture=index)
                collect_texture_sampler(materials, texture, row, "mainSampler")
                result.append(row)
                if len(result) >= _MAX_EMITTERS:
                    break
        except title._UNSUPPORTED:
            continue
    return result
