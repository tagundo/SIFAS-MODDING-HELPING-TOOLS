"""Read the native paired overhead spark cues in Monster Girls Expert."""

import math

from . import model_viewer as viewer
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_display_lights import _enabled
from .mv_studio_finale_flashes import _SURFACE
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_break import _curve
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _number


_PREFAB = "fx_par_so2056_02"
_TRACKS = {f"StageEffect/Expert/Control/sparks_B_{index:02}" for index in (1, 2)}
_NAMES = ("grow", "hibana", "late_kirakira")
_LAYER = 1
_ALIAS = "speedBackCenterStars"
_ZERO = dict.fromkeys("xyz", 0)
_WHITE_START = {"startColor": {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}}
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule", "ColorModule", "UVModule"}

_TIMING = {
    # Native emission duration, continuous rate, one-shot bursts.
    "grow": (_float32(.4), 0, ((0, 1),)),
    "hibana": (_float32(1.8), 0, ((0, 100), (_float32(.03), 75), (_float32(.06), 50))),
    "late_kirakira": (1, 75, ((0, 150),)),
}
_INITIAL = {
    # Delay, lifetime, size, speed, Z roll, gravity, capacity.
    "grow": ((0, 0), (_float32(.3),) * 2, (8, 8), (0, 0), (0, _float32(math.pi)), 0, 200),
    "hibana": ((0, 0), (1, 2), (_float32(.06), _float32(.14)), (2, 20), (0, 0), _float32(.8), 1000),
    "late_kirakira": ((_float32(.1), _float32(.2)), (2, 1.5), (_float32(.2), _float32(.3)),
                      (0, 0), (0, _float32(6.283185)), _float32(.2), 1000),
}
_SHAPES = {
    # Radius, total arc, arc mode, shape-local scale, Unity Euler rotation.
    "grow": (_float32(.1), 360, 0, [1, 1, 1], [0, 0, 0]),
    "hibana": (.5, 180, 3, [1.5, .25, 1], [90, 0, 0]),
    "late_kirakira": (1.5, 180, 0, [4, .5, 1], [90, 0, 0]),
}
_UV_PHASE = _float32(.9999)


def _surface(objects, renderer, fields, name):
    stretched = name == "hibana"
    length, speed = (2.5, _float32(.02)) if stretched else (0, _float32(.3))
    if (not fields["m_Enabled"] or not fields["m_AllowRoll"] or fields["m_ApplyActiveColorSpace"]
            or fields["m_RenderMode"] != int(stretched) or fields["m_RenderAlignment"] != 0
            or (fields["m_LengthScale"], fields["m_VelocityScale"]) != (length, speed)
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO or fields["m_MaxParticleSize"] != .5
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_NormalDirection"] != 1
            or fields["m_RenderingLayerMask"] != 0xFFFFFFFF or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortMode", "m_SortingFudge", "m_UseCustomVertexStreams",
                                           "m_CameraVelocityScale", "m_MinParticleSize", "m_MaskInteraction",
                                           "m_CastShadows", "m_ReceiveShadows", "m_SortingLayerID", "m_SortingOrder",
                                           "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    texture = _spark_atlas(objects, renderer, fields["m_Materials"])
    if texture is None:
        return None
    stretch = {"lengthScale": length, "velocityScale": speed} if stretched else None
    return {"maxViewportWidth": fields["m_MaxParticleSize"], "stretch": stretch}, texture


def _spark_atlas(objects, renderer, refs):
    if len(refs) != 2 or refs[0] != refs[1]:
        return None
    material = title._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    shader = tree["m_Shader"]
    path_id, cab = _SHADERS["AS/General/Transparent"]
    file_id, externals = shader["m_FileID"], material.assets_file.externals
    if (tree["m_CustomRenderQueue"] != 3010 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or tree["stringTagMap"] or tree["disabledShaderPasses"] or viewer._properties(tree, "m_Floats") != _SURFACE
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab
            or viewer._properties(tree, "m_Colors") != {"_TintColor": {"r": 2, "g": 2, "b": 2, "a": 1}}):
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


def _range(source, mode, lower, upper):
    if mode == 3:
        return _constant_range(source, lower, upper)
    value = _constant(source)
    return (value, value) if _number(value, lower, upper) else None


def _emission(source, name):
    duration, rate, expected = _TIMING[name]
    if source["lengthInSec"] != duration:
        return None
    emission = source["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (emission["m_BurstCount"] != len(expected) or len(bursts) != len(expected)
            or _constant(emission["rateOverTime"]) != rate or _constant(emission["rateOverDistance"]) != 0):
        return None
    result = []
    for burst, pair in zip(bursts, expected):
        time, count = burst["time"], _constant(burst["countCurve"])
        if (time, count) != pair or burst["cycleCount"] != 1 or burst["probability"] != 1:
            return None
        result.append([time, int(count)])
    return {"duration": duration, "rate": rate, "bursts": result}


def _initial(source, name):
    grow, hibana = name == "grow", name == "hibana"
    initial = source["InitialModule"]
    delay = _range(source["startDelay"], 0 if grow else 3, 0, 1)
    lifetime = _range(initial["startLifetime"], 0 if grow else 3, .01, 2)
    size = _range(initial["startSize"], 0 if grow else 3, .01, 8)
    speed = _range(initial["startSpeed"], 3 if hibana else 0, 0, 20)
    roll = _range(initial["startRotation"], 0 if hibana else 3, 0, 7)
    gravity = _constant(initial["gravityModifier"])
    capacity = initial["maxNumParticles"]
    if ((delay, lifetime, size, speed, roll, gravity, capacity) != _INITIAL[name]
            or initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]):
        return None
    # No clip overwrites the seed. For auto-seeded previews, a fresh seed must
    # be drawn once per emitter and cue so seeking replays the same realization.
    seed = 0 if hibana else None
    return {"seed": seed, "delay": delay, "lifetime": lifetime, "size": size, "speed": speed,
            "roll": roll, "gravity": gravity, "capacity": capacity}


def _shape(fields, name):
    return _sphere_shape(fields, _SHAPES[name])


def _sphere_shape(fields, expected):
    radius, arc, arc_mode, scale, rotation = expected
    radius_settings, arc_settings = fields["radius"], fields["arc"]
    if (fields["type"] != 0 or fields["m_Position"] != _ZERO or fields["boxThickness"] != _ZERO
            or [fields["m_Scale"][axis] for axis in "xyz"] != scale
            or [fields["m_Rotation"][axis] for axis in "xyz"] != rotation
            or fields["radiusThickness"] != 1 or radius_settings["value"] != radius or radius_settings["mode"]
            or (arc_settings["value"], arc_settings["mode"]) != (arc, arc_mode)
            or any(item["spread"] or _constant(item["speed"]) != 1 for item in (radius_settings, arc_settings))
            or any(fields[key] for key in ("placementMode", "alignToDirection", "randomDirectionAmount",
                                           "sphericalDirectionAmount", "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return {"type": fields["type"], "radius": radius, "radiusThickness": fields["radiusThickness"], "arc": arc,
            "arcMode": arc_mode, "scale": scale, "rotation": rotation}


def _curve_pair(field, mode, deadline):
    if field["minMaxState"] != mode:
        return None
    maximum = _curve(field["maxCurve"], deadline)
    minimum = _curve(field["minCurve"], deadline) if mode == 2 else maximum
    return [minimum, maximum] if minimum is not None and maximum is not None else None


def _size(fields, name, deadline):
    grow = name == "grow"
    curve = fields["curve"]
    if fields["separateAxes"] or curve["scalar"] != (2 if name == "hibana" else 1):
        return None
    pair = _curve_pair(curve, 1 if grow else 2, deadline)
    return {"sizeCurves": pair, "sizeMultiplier": curve["scalar"]} if pair is not None else None


def _motion(source, name, deadline):
    if name == "grow":
        return {"velocityCurves": None, "velocityMultipliers": None, "clamp": None}
    fields = source["VelocityModule"]
    if (fields["inWorldSpace"] or _constant(fields["speedModifier"]) != 1
            or any(_constant(fields[key]) != 0 for key in ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX",
                                                            "orbitalOffsetY", "orbitalOffsetZ", "radial"))):
        return None
    multipliers = [fields[axis]["scalar"] for axis in "xyz"]
    if multipliers != ([1, 1, 1] if name == "hibana" else [1, 4, 1]):
        return None
    curves = [_curve_pair(fields[axis], 2, deadline) for axis in "xyz"]
    if any(pair is None for pair in curves):
        return None
    clamp = None
    if name == "hibana":
        module = source["ClampVelocityModule"]
        if (module["separateAxis"] or module["inWorldSpace"] or _constant(module["drag"]) != 0
                or _constant(module["magnitude"]) != 1 or module["dampen"] != _float32(.15)):
            return None
        clamp = {"limit": 1, "dampen": module["dampen"]}
    return {"velocityCurves": curves, "velocityMultipliers": multipliers, "clamp": clamp}


def _colors(source, start_mode, life_mode):
    start = source["InitialModule"]["startColor"]
    fade = source["ColorModule"]
    if start["minMaxState"] != start_mode or fade["gradient"]["minMaxState"] != life_mode:
        return None
    endpoints = ("maxColor", "maxColor") if start_mode == 0 else ("minColor", "maxColor")
    start_colors = [[start[key][axis] for axis in "rgba"] for key in endpoints]
    if any(not _number(channel, 0, 1) for rgba in start_colors for channel in rgba):
        return None
    gradients = fade["gradient"]
    modes = ("maxGradient", "maxGradient") if life_mode == 1 else ("minGradient", "maxGradient")
    life_colors = []
    for key in modes:
        module = {**fade, "gradient": {**gradients, "minMaxState": 1, "maxGradient": gradients[key]}}
        color = _rgba8(_WHITE_START, module)
        if color is None:
            return None
        life_colors.append(color["rgba8"]["keys"])
    return {"startColors": start_colors, "lifeColors": life_colors}


def _sheet(module, name, deadline):
    grow = name == "grow"
    phase, row = (0, 2) if grow else (_UV_PHASE, 1)
    start = module["startFrame"]
    if _constant(start) != phase:
        return None
    atlas = _atlas({**module, "startFrame": {**start, "scalar": 0}}, deadline, through=1)
    if atlas != {"tiles": [4, 4], "row": row, "frame": ("constant", phase)}:
        return None
    # The Single Row grid wraps after adding Frame over Time and Start Frame.
    combined = _float32(phase + phase)
    tile = int(_float32(_float32(combined - math.floor(combined)) * 4))
    return [.25, .25, tile * .25, row * .25]


def _leaf(objects, game, name, deadline):
    typed = title._components(objects, game, _COMPONENTS, layer=_LAYER)
    if typed is None:
        return None
    parts = typed[1]
    _, transform = parts["Transform"]
    if transform["m_Children"] or _authored_trs(transform) != title._IDENTITY:
        return None
    source = parts["ParticleSystem"][1]
    modules = _MODULES | ({"VelocityModule"} if name != "grow" else set())
    if name == "hibana":
        modules = modules | {"ClampVelocityModule"}
    if (_enabled(source) != modules or not source["playOnAwake"] or source["randomSeed"] != 0
            or source["autoRandomSeed"] != (name != "hibana") or source["simulationSpeed"] != 1
            or source["scalingMode"] != 1 or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction"))):
        return None
    shape = _shape(source["ShapeModule"], name)
    uv = _sheet(source["UVModule"], name, deadline)
    surface = _surface(objects, *parts["ParticleSystemRenderer"], name)
    if shape is None or uv is None or surface is None:
        return None
    renderer, texture = surface
    grow = name == "grow"
    state = (_emission(source, name), _initial(source, name), _size(source["SizeModule"], name, deadline),
             _motion(source, name, deadline), _colors(source, 0 if grow else 2, 1 if grow else 3))
    if any(section is None for section in state):
        return None
    row = {"name": name, "shape": shape, "uv": uv, **renderer}
    for section in state:
        row.update(section)
    return row, texture


def _prefab(objects, game, deadline):
    outer = title._components(objects, game, {"Transform"}, layer=_LAYER)
    if outer is None or outer[0]["m_Name"] != _PREFAB:
        return None
    transform, fields = outer[1]["Transform"]
    if (len(fields["m_Children"]) != 1 or fields["m_Father"]["m_PathID"]
            or _authored_trs(fields) != title._IDENTITY):
        return None
    pivot = title._transform_child(objects, transform, fields["m_Children"][0])
    root = title._components(objects, pivot, {"Transform"}, layer=_LAYER) if pivot is not None else None
    if root is None or root[0]["m_Name"] != "root":
        return None
    transform, fields = root[1]["Transform"]
    if len(fields["m_Children"]) != len(_NAMES) or _authored_trs(fields) != title._IDENTITY:
        return None
    rows, atlas = [], None
    for ref, name in zip(fields["m_Children"], _NAMES):
        viewer._remaining(deadline)
        child = title._transform_child(objects, transform, ref)
        if child is None or child.peek_name() != name:
            return None
        result = _leaf(objects, child, name, deadline)
        if result is None or (atlas is not None and viewer._key(result[1]) != viewer._key(atlas)):
            return None
        row, atlas = result
        rows.append(row)
    return rows, atlas


def read(objects, mono, tracks, deadline, *, atlas_refs=None):
    """Return verified spark emitters once and bind each supported authored cue."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    cues, source = {}, None
    for track in tracks:
        control = controls.get(track["id"])
        label = track["label"]
        if control is None or label not in _TRACKS or track.get("binding") or track.get("bindings"):
            continue
        owner, fields = control
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields, "control")):
                continue
            for event in track["events"]:
                if event["label"] != _PREFAB or event["values"].get("clipIn") != 0:
                    continue
                viewer._remaining(deadline)
                original = particles._source(objects, owner, fields, event)
                if original is None:
                    continue
                prefab_key = viewer._key(original[0])
                if source is not None and source[0] != prefab_key:
                    return None
                if source is None:
                    effect = _prefab(objects, original[0], deadline)
                    if effect is None:
                        continue
                    source = prefab_key, effect
                if label in cues:
                    return None
                cues[label] = {"trackId": track["id"], "eventId": event["id"]}
        except title._UNSUPPORTED:
            continue
    if not cues or source is None:
        return None
    _, (emitters, reader) = source
    if atlas_refs is not None and atlas_refs.get(viewer._key(reader)) == _ALIAS:
        atlas = _ALIAS
    else:
        try:
            atlas = particles._texture(reader, deadline)
        except title._UNSUPPORTED:
            return None
        if not atlas or len(atlas) != 10:
            return None
    return {"textures": [atlas], "emitters": emitters, "cues": [cues[label] for label in sorted(cues)]}
