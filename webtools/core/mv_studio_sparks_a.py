"""Read the source front spark bursts in Monster Girls Expert."""

from . import model_viewer as viewer
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_display_lights import _enabled
from .mv_studio_sparks_b import _colors, _curve_pair, _spark_atlas
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _scalar


_PREFAB = "fx_par_so2056_01"
_TRACKS = {f"StageEffect/Expert/Control/sparks_A_{index:02}": 100 * index for index in (1, 2)}
_NAME = "hibana_01"
_SECONDARY = "hibana_02"
_LAYER = 1
_ALIAS = "speedBackCenterStars"
_ZERO = dict.fromkeys("xyz", 0)
_UNIT = dict.fromkeys("xyz", 1)
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule",
            "ColorModule", "UVModule", "ClampVelocityModule"}
_UV_PHASE = _float32(.9999)
_SECONDARY_MODULES = (_MODULES - {"ClampVelocityModule"}) | {"VelocityModule"}


def _surface(objects, renderer, fields, *, secondary=False):
    length, velocity = fields["m_LengthScale"], fields["m_VelocityScale"]
    viewport = (fields["m_MinParticleSize"], fields["m_MaxParticleSize"])
    expected = (0, _float32(.08), (_float32(.02), 2)) if secondary else (1, _float32(.025), (0, 1))
    if (not fields["m_Enabled"] or not fields["m_AllowRoll"] or fields["m_ApplyActiveColorSpace"]
            or fields["m_RenderAlignment"] != 0 or length != 0
            or (fields["m_RenderMode"], velocity, viewport) != expected
            or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_NormalDirection"] != 1
            or fields["m_RenderingLayerMask"] != 0xFFFFFFFF or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortMode", "m_SortingFudge", "m_UseCustomVertexStreams",
                                           "m_EnableGPUInstancing", "m_CameraVelocityScale",
                                           "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows",
                                           "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    texture = _spark_atlas(objects, renderer, fields["m_Materials"])
    if texture is None:
        return None
    if secondary:
        return {"minViewportWidth": viewport[0], "maxViewportWidth": viewport[1]}, texture
    return {"maxViewportWidth": viewport[1], "stretch": {"lengthScale": length, "velocityScale": velocity}}, texture


def _shape(fields, *, secondary=False):
    radius = fields["radius"]
    arc = fields["arc"]
    rotation = [fields["m_Rotation"][axis] for axis in "xyz"]
    expected = (18, 7, .25) if secondary else (15, 2, _float32(.3))
    if (fields["type"] != 8 or (fields["angle"], fields["length"], radius["value"]) != expected
            or fields["radiusThickness"] != 1 or arc["value"] != 360 or fields["m_Position"] != _ZERO
            or rotation != [-90, 0, 0] or fields["m_Scale"] != _UNIT or fields["boxThickness"] != _ZERO
            or any(item["mode"] or item["spread"] or _constant(item["speed"]) != 1 for item in (radius, arc))
            or any(fields[key] for key in ("placementMode", "alignToDirection", "randomDirectionAmount",
                                           "sphericalDirectionAmount", "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return {"type": fields["type"], "radius": radius["value"], "radiusThickness": fields["radiusThickness"],
            "angle": fields["angle"], "length": fields["length"], "arc": arc["value"], "arcMode": arc["mode"],
            "scale": [fields["m_Scale"][axis] for axis in "xyz"], "rotation": rotation}


def _emission(source):
    emission = source["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (source["lengthInSec"] != _float32(.1) or _constant(emission["rateOverTime"]) != 0
            or _constant(emission["rateOverDistance"]) != 0 or emission["m_BurstCount"] != 1 or len(bursts) != 1):
        return None
    burst, = bursts
    if (burst["time"] != 0 or _constant(burst["countCurve"]) != 1000
            or burst["cycleCount"] != 1 or burst["probability"] != 1):
        return None
    return {"duration": source["lengthInSec"], "rate": 0, "bursts": [[burst["time"], 1000]]}


def _state(source, deadline):
    if (_enabled(source) != _MODULES or not source["playOnAwake"] or not source["autoRandomSeed"]
            or source["randomSeed"] != 0 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or _constant(source["startDelay"]) != 0 or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction"))):
        return None
    initial = source["InitialModule"]
    lifetime = _constant_range(initial["startLifetime"], 1, 3)
    size = _constant_range(initial["startSize"], .01, 1)
    speed = _constant_range(initial["startSpeed"], 0, 40)
    gravity = _constant_range(initial["gravityModifier"], 0, 2)
    roll = _constant(initial["startRotation"])
    capacity = initial["maxNumParticles"]
    if (lifetime != (_float32(1.2), _float32(2.4)) or size != (_float32(.02), _float32(.04))
            or speed != (3, 30) or gravity != (.5, _float32(1.2)) or roll != 0 or capacity != 1000
            or initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]):
        return None
    sizing = source["SizeModule"]
    authored_size = sizing["curve"]
    if sizing["separateAxes"] or authored_size["scalar"] != 1:
        return None
    curves = _curve_pair(authored_size, 2, deadline)
    clamp = source["ClampVelocityModule"]
    limit = _constant(clamp["magnitude"])
    if (limit != 1 or clamp["dampen"] != _float32(.1) or clamp["separateAxis"] or clamp["inWorldSpace"]
            or _constant(clamp["drag"]) != 0):
        return None
    atlas = source["UVModule"]
    start = atlas["startFrame"]
    if _constant(start) != _UV_PHASE:
        return None
    sheet = _atlas({**atlas, "startFrame": {**start, "scalar": 0}}, deadline, through=1)
    if sheet != {"tiles": [4, 4], "row": 0, "frame": ("constant", _UV_PHASE)}:
        return None
    shape = _shape(source["ShapeModule"])
    emission = _emission(source)
    color = _colors(source, 0, 3)
    if (shape is None or emission is None or curves is None or color is None
            or color["startColors"] != [[1, 1, 1, 1]] * 2):
        return None
    return {"name": _NAME, "delay": [0, 0], "lifetime": lifetime, "size": size, "speed": speed, "roll": [roll, roll],
            "gravity": gravity, "shape": shape, **emission, "sizeCurves": curves,
            "sizeMultiplier": authored_size["scalar"], "clamp": {"limit": limit, "dampen": clamp["dampen"]},
            **color, "uv": [.25, .25, .75, 0], "capacity": capacity}


def _secondary_state(source, deadline):
    delay = _constant(source["startDelay"])
    if (_enabled(source) != _SECONDARY_MODULES or not source["playOnAwake"] or not source["autoRandomSeed"]
            or source["randomSeed"] != 0 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or delay != _float32(.12) or source["lengthInSec"] != .5 or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction"))):
        return None
    initial = source["InitialModule"]
    lifetime = _constant_range(initial["startLifetime"], 0, 1)
    size = [_constant_range(initial[key], 0, 1) for key in ("startSize", "startSizeY", "startSizeZ")]
    roll = _constant_range(initial["startRotation"], 0, 7)
    gravity = _constant(initial["gravityModifier"])
    capacity = initial["maxNumParticles"]
    if (lifetime != (_float32(.16), _float32(.2)) or size != [(_float32(.4), _float32(.1))] * 3
            or _constant(initial["startSpeed"]) != 0 or roll != (0, _float32(6.283185))
            or gravity != _float32(.1) or capacity != 1000
            or not initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]):
        return None
    emission = source["EmissionModule"]
    bursts = emission["m_Bursts"]
    if (_constant(emission["rateOverTime"]) != 0 or _constant(emission["rateOverDistance"]) != 0
            or emission["m_BurstCount"] != 1 or len(bursts) != 1):
        return None
    burst, = bursts
    repeat = burst["repeatInterval"]
    if (burst["time"] != 0 or _constant(burst["countCurve"]) != 60
            or burst["cycleCount"] != 3 or burst["probability"] != 1 or repeat != _float32(.15)):
        return None
    velocity = source["VelocityModule"]
    velocity_y = _constant_range(velocity["y"], 0, 10)
    if (velocity["inWorldSpace"] or velocity_y != (6, 2)
            or any(_constant_range(velocity[axis], 0, 1) != (0, 0) for axis in "xz")
            or _constant(velocity["speedModifier"]) != 1
            or any(_constant(velocity[key]) != 0 for key in ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX",
                                                              "orbitalOffsetY", "orbitalOffsetZ", "radial"))):
        return None
    sizing = source["SizeModule"]
    authored_size = sizing["curve"]
    if sizing["separateAxes"] or authored_size["minMaxState"] != 1 or authored_size["scalar"] != 1:
        return None
    size_curve = _scalar(authored_size, deadline)
    atlas = source["UVModule"]
    start = atlas["startFrame"]
    endpoints = _constant_range(start, 0, 1)
    if endpoints != (0, .125):
        return None
    sheet = _atlas({**atlas, "startFrame": {**start, "minMaxState": 0, "scalar": 0}}, deadline, through=1)
    if sheet != {"tiles": [4, 4], "row": None, "frame": ("constant", 0)}:
        return None
    shape = _shape(source["ShapeModule"], secondary=True)
    color = _colors(source, 0, 1)
    if (shape is None or size_curve is None or color is None
            or color["startColors"] != [[1, 1, 1, 1]] * 2):
        return None
    return {"name": _SECONDARY, "delay": delay, "lifetime": lifetime, "size3D": size, "roll": roll,
            "gravity": gravity, "shape": shape, "duration": source["lengthInSec"],
            "bursts": [[burst["time"], 60, burst["cycleCount"], repeat]], "sizeCurve": size_curve,
            "sizeMultiplier": authored_size["scalar"], "velocityY": velocity_y,
            "lifeColors": [color["lifeColors"][0]], "atlas": {"tiles": sheet["tiles"], "start": endpoints},
            "capacity": capacity}


def _leaf(objects, game, deadline, *, secondary=False):
    leaf = title._components(objects, game, _COMPONENTS, layer=_LAYER)
    if leaf is None:
        return None
    _, fields = leaf[1]["Transform"]
    if fields["m_Children"] or _authored_trs(fields) != title._IDENTITY:
        return None
    read_state = _secondary_state if secondary else _state
    state = read_state(leaf[1]["ParticleSystem"][1], deadline)
    surface = _surface(objects, *leaf[1]["ParticleSystemRenderer"], secondary=secondary) if state is not None else None
    if surface is None:
        return None
    profile, texture = surface
    return {**state, **profile}, texture


def _prefab(objects, game, deadline):
    outer = title._components(objects, game, {"Transform"}, layer=_LAYER)
    if outer is None or outer[0]["m_Name"] != _PREFAB:
        return None
    transform, fields = outer[1]["Transform"]
    if (len(fields["m_Children"]) != 1 or fields["m_Father"]["m_PathID"]
            or _authored_trs(fields) != title._IDENTITY):
        return None
    pivot = title._transform_child(objects, transform, fields["m_Children"][0])
    root = title._components(objects, pivot, _COMPONENTS, layer=_LAYER) if pivot is not None else None
    if root is None or root[0]["m_Name"] != "root":
        return None
    parts = root[1]
    transform, fields = parts["Transform"]
    disabled = parts["ParticleSystem"][1]
    if (len(fields["m_Children"]) != 3 or _authored_trs(fields) != title._IDENTITY
            or _enabled(disabled) != {"InitialModule"} or not disabled["autoRandomSeed"]
            or parts["ParticleSystemRenderer"][1]["m_Enabled"]):
        return None
    children = [title._transform_child(objects, transform, ref) for ref in fields["m_Children"]]
    if any(child is None for child in children):
        return None
    if [child.peek_name() for child in children] != [_NAME, "hibana_02", "smoke"]:
        return None
    primary = _leaf(objects, children[0], deadline)
    if primary is None:
        return None
    emitter, texture = primary
    emitters = [emitter]
    try:
        secondary = _leaf(objects, children[1], deadline, secondary=True)
    except title._UNSUPPORTED:
        secondary = None
    if secondary is not None and viewer._key(secondary[1]) == viewer._key(texture):
        emitters.append(secondary[0])
    return emitters, texture


def read(objects, mono, tracks, deadline, *, atlas_refs=None):
    """Bind the supported native spark emitters to the two authored seed overrides."""
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
                original = particles._source(objects, owner, fields, event, overwrite_seed=True)
                if original is None or original[1] != _TRACKS[label]:
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
                cues[label] = {"trackId": track["id"], "eventId": event["id"], "seed": original[1]}
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
