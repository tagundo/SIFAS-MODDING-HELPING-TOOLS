"""Read the stationary and orbiting billboards of a native umbrella effect."""

import math

from . import model_viewer as viewer
from . import mv_studio_stage_title as title
from . import mv_studio_stage_title_particles as particles
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS


_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_REQUIRED_MODULES = {"InitialModule", "EmissionModule", "RotationModule"}
_OPTIONAL_MODULES = {"SizeModule", "ColorModule"}
_RING_MODULES = {"ShapeModule", "VelocityModule"}
_CENTER = "kasa_loop"
_RINGS = ("kasa_out_loop_01", "kasa_out_loop_02")
# The stock horizontal scalar billboard treats size as its diagonal. Mirror
# X, reverse winding and flip V to preserve the native corner/UV pairs.
_HALF_SIDE = .3535533845424652
_GEOMETRY = {
    "positions": [[_HALF_SIDE, 0, _HALF_SIDE], [-_HALF_SIDE, 0, _HALF_SIDE],
                  [-_HALF_SIDE, 0, -_HALF_SIDE], [_HALF_SIDE, 0, -_HALF_SIDE]],
    "uv": [[0, 0], [1, 0], [1, 1], [0, 1]],
    "indices": [0, 2, 1, 0, 3, 2],
}
_PIVOT = dict(x=0, y=0, z=0)
_MATERIAL_FLOATS = {"_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 2, "_SATURATE": 0, "_StencilComp": 8,
                    "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
                    "_ZTestMode": 4, "_ZWriteParam": 0}


def _leaves(objects, game):
    root = title._components(objects, game, {"Transform"}, layer=15)
    if root is None:
        return None
    transform, fields = root[1]["Transform"]
    children = fields["m_Children"]
    if (len(children) != 1 or _authored_trs(fields) != title._IDENTITY
            or fields["m_Father"]["m_PathID"]):
        return None
    pivot = title._transform_child(objects, transform, children[0])
    root = title._components(objects, pivot, _COMPONENTS, layer=15) if pivot is not None else None
    if root is None or root[0]["m_Name"] != "root":
        return None
    transform, fields = root[1]["Transform"]
    children = fields["m_Children"]
    if len(children) != 3 or _authored_trs(fields) != title._IDENTITY:
        return None
    leaves = {}
    for ref in children:
        child = title._transform_child(objects, transform, ref)
        if child is None:
            return None
        name = child.peek_name()
        if name in leaves:
            return None
        leaves[name] = child
    if leaves.keys() != {_CENTER, *_RINGS}:
        return None
    return leaves


def _surface(objects, renderer, fields, outer):
    streams = [0, 1, 3, 4] if outer else [0, 1, 3, 4, 32]
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 2 or fields["m_RenderAlignment"] != 2
            or fields["m_UseCustomVertexStreams"] or fields["m_ApplyActiveColorSpace"] == outer
            or not fields["m_AllowRoll"] or fields["m_VertexStreams"] != streams
            or fields["m_Pivot"] != _PIVOT or fields["m_Flip"] != _PIVOT
            or fields["m_MinParticleSize"] != 0 or fields["m_MaxParticleSize"] != 20
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
    if (tree["m_CustomRenderQueue"] != 3000 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or viewer._properties(tree, "m_Floats") != _MATERIAL_FLOATS
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower() != cab):
        return None
    saved_color = viewer._properties(tree, "m_Colors")["_TintColor"]
    saved_texture = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    tint = [saved_color[axis] for axis in "rgba"]
    uv = [saved_texture[key][axis] for key in ("m_Scale", "m_Offset") for axis in "xy"]
    texture = title._local(objects, material, saved_texture["m_Texture"], "Texture2D")
    if texture is None or tint != [1, 1, 1, 1] or uv != [1, 1, 0, 0]:
        return None
    return {"tint": tint, "uv": uv, "queue": 3000, "cull": 2, "blend": "add"}, texture


def _motion(source, deadline, outer):
    constant = particles._constant
    if (not source["playOnAwake"] or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or constant(source["startDelay"]) != 0 or source["moveWithCustomTransform"]["m_PathID"]
            or not particles._number(source["lengthInSec"], .01, 1)
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction", "autoRandomSeed", "randomSeed"))):
        return None
    enabled = {name for name, module in source.items() if name.endswith("Module") and module["enabled"]}
    required = _REQUIRED_MODULES | _RING_MODULES if outer else _REQUIRED_MODULES
    if not required <= enabled <= required | _OPTIONAL_MODULES:
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    if (initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(constant(initial[key]) != 0 for key in ("startSpeed", "gravityModifier"))
            or any(constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))
            or emission["m_BurstCount"] != 1 or len(emission["m_Bursts"]) != 1):
        return None
    burst, = emission["m_Bursts"]
    count = constant(burst["countCurve"])
    if (burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1
            or count not in ((3, 4) if outer else (1,)) or initial["maxNumParticles"] < count):
        return None
    lifetime, size, rotation = (constant(initial[key]) for key in ("startLifetime", "startSize", "startRotation"))
    angular = source["RotationModule"]
    speed = constant(angular["curve"])
    if (angular["separateAxes"] or not particles._number(lifetime, .01, 120)
            or not particles._number(size, .01, 20) or not particles._number(rotation, -math.tau, math.tau)
            or not particles._number(speed, -math.tau, math.tau)):
        return None
    size_module = source["SizeModule"]
    if size_module["enabled"] and size_module["separateAxes"]:
        return None
    curve = particles._scalar(size_module["curve"], deadline) if size_module["enabled"] else ("constant", 1)
    start_color = initial["startColor"]
    rgba = [start_color["maxColor"][channel] for channel in "rgba"]
    if curve is None or not all(particles._number(value, 0, 1) for value in rgba):
        return None
    # Unity stores the start color in the particle's byte RGBA before evaluating over-lifetime color.
    quantized = {channel: int(particles._float32(particles._float32(value * 255) + .5)) / 255
                 for channel, value in zip("rgba", rgba)}
    color = particles._color({"startColor": {**start_color, "maxColor": quantized}}, source["ColorModule"])
    # The ring renderer uses raw vertex color. Both color spaces agree for white RGB.
    if color is None or (outer and any(row[1:] != [1, 1, 1] for row in color["rgb"])):
        return None
    return {"birth": 0, "lifetime": lifetime, "size": size, "sizeCurve": curve,
            "yaw": -rotation, "yawSpeed": -speed, "color": color}, int(count)


def _ring(source, billboard, texture, count):
    constant = particles._constant
    shape, velocity = source["ShapeModule"], source["VelocityModule"]
    arc, radius = shape["arc"], shape["radius"]
    rotation, scale = shape["m_Rotation"], shape["m_Scale"]
    if (shape["type"] != 10 or not shape["alignToDirection"] or shape["radiusThickness"] != 0
            or shape["m_Position"] != _PIVOT or rotation["x"] != 90 or rotation["z"] != 0
            or not particles._number(rotation["y"], -360, 360) or scale["x"] != scale["y"] or scale["z"] != 0
            or arc["mode"] != 3 or arc["spread"] != 0 or (arc["value"], count) not in ((360, 4), (180, 3))
            or radius["mode"] != 0 or radius["spread"] != 0 or radius["value"] != 1
            or not particles._number(scale["x"], .01, 20)
            or any(shape[key] for key in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(shape[key]["m_PathID"] for key in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                     "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return None
    orbit = constant(velocity["orbitalY"])
    if (velocity["inWorldSpace"] or constant(velocity["speedModifier"]) != 1
            or not particles._number(orbit, -math.tau, math.tau)
            or any(particles._constant_range(velocity[key], 0, 0) is None for key in "xyz")
            or any(constant(velocity[key]) != 0 for key in ("orbitalX", "orbitalZ", "radial", "orbitalOffsetX",
                                                            "orbitalOffsetY", "orbitalOffsetZ"))):
        return None
    # Native Circle/Burst Spread starts at +X. Full rings omit the duplicated endpoint.
    # Radial alignment changes the initial X/Y Euler channels; planar billboards read Z.
    _, height, _ = billboard["position"]
    step = math.radians(arc["value"]) / (count if arc["value"] == 360 else count - 1)
    angle = math.radians(rotation["y"])
    positions = [[-scale["x"] * math.cos(index * step - angle), height,
                  scale["y"] * math.sin(index * step - angle)] for index in range(count)]
    return [({**billboard, "position": position, "orbitY": -orbit}, texture) for position in positions]


def _billboard(objects, game, deadline, *, outer=False):
    try:
        leaf = title._components(objects, game, _COMPONENTS, layer=15)
        if leaf is None:
            return None
        parts = leaf[1]
        transform = parts["Transform"][1]
        trs = _authored_trs(transform)
        if (trs["rotation"] != title._IDENTITY["rotation"] or trs["scale"] != title._IDENTITY["scale"]
                or trs["translation"] != [0, particles._float32(.01), 0] or transform["m_Children"]):
            return None
        source = parts["ParticleSystem"][1]
        motion = _motion(source, deadline, outer)
        surface = _surface(objects, *parts["ParticleSystemRenderer"], outer)
        if motion is None or surface is None:
            return None
        material, texture = surface
        values, count = motion
        billboard = {**values, "position": trs["translation"], "rotation": trs["rotation"], "scale": trs["scale"],
                     "material": material, "geometry": _GEOMETRY}
        if outer:
            return _ring(source, billboard, texture, count)
        return [(billboard, texture)]
    except title._UNSUPPORTED:
        return None


def read(objects, game, deadline, *, clip_seed=None):
    # Circle/Burst Spread, constant lifetime and zero positional spread are seed-independent.
    try:
        leaves = _leaves(objects, game)
    except title._UNSUPPORTED:
        return None
    if leaves is None:
        return None
    center = _billboard(objects, leaves[_CENTER], deadline)
    if center is None:
        return None
    first, second = (_billboard(objects, leaves[name], deadline, outer=True) for name in _RINGS)
    return center + first + second if first is not None and second is not None else center
