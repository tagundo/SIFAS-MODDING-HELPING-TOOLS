"""Read the authored Monster Girls Expert stage break transition."""

import math

from . import model_animation as animation, model_viewer as viewer
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_center_stars import _material as _add_material
from .mv_studio_display_lights import _enabled
from .mv_studio_falling_display import _light_material as _alpha_material
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_title_particles import _constant, _constant_range, _float32, _scalar


_PREFAB = "fx_dis_so2056_08"
_TRACK = "StageEffect/Expert/Display/break"
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_NAMES = ("Break", "Fall", "light_big", "flash")
_ZERO = dict.fromkeys("xyz", 0)
_BASE = {"InitialModule", "EmissionModule", "ColorModule", "UVModule"}
_ROTATION = {"RotationModule"}
_SHAPE = {"ShapeModule"}
_MODULES = {
    "Break": _BASE,
    "Fall": _BASE | _ROTATION | _SHAPE | {"ClampVelocityModule"},
    "light_big": _BASE | _ROTATION | _SHAPE | {"VelocityModule"},
    "flash": _BASE | _ROTATION,
}
_BURSTS = {"Break": (1, 1, _float32(.5)), "Fall": (60, 100, _float32(.1)),
           "light_big": (8, 1000, 50), "flash": (1, 100, _float32(.1))}
_SEED = 10354082
_SPIN = (_float32(-12.56637), _float32(12.56637))
_ATLASES = {
    "Break": (0, "tex_dis_par_so2056_09", 2, 4, None, True),
    "Fall": (2, "tex_par_so2056_01", 4, 4, None, True),
    "light_big": (1, "tex_dis_par_so2056_07", 1, 4, None, False),
    "flash": (2, "tex_par_so2056_01", 4, 4, 0, False),
}
_ALIASES = (None, "displayLights", "speedBackCenterStars")
_RENDERERS = {
    # Render mode, alignment, intra-system sort, renderer sort bias, viewport limit.
    "Break": (4, 2, 0, 0, .5),
    "Fall": (0, 0, 1, -1, 2),
    "light_big": (0, 2, 1, 0, 2),
    "flash": (0, 2, 0, 2, 4),
}


def _curve(source, deadline, *, expected=None):
    keys = source["m_Curve"]
    if ((source["m_PreInfinity"], source["m_PostInfinity"]) != (2, 2)
            or not 1 <= len(keys) <= 16 or any(not 0 <= key["time"] <= 1 for key in keys)
            or any(left["time"] >= right["time"] for left, right in zip(keys, keys[1:]))
            or (expected is not None and tuple((key["time"], key["value"], key["inSlope"], key["outSlope"])
                                              for key in keys) != expected)):
        return None
    return animation._editor_scalar(keys, deadline=deadline)


def _atlas(module, name, deadline):
    _, _, columns, rows, row, random_row = _ATLASES[name]
    if ((module["tilesX"], module["tilesY"], module["animationType"], module["rowIndex"], module["randomRow"])
            != (columns, rows, int(row is not None), row or 0, random_row)
            or any(module[key] for key in ("mode", "timeMode", "flipU", "flipV"))
            or module["cycles"] != 1 or module["uvChannelMask"] != -1):
        return None
    # Whole Sheet uses the shared tile phase before a row can be sampled.
    start = module["startFrame"]
    endpoints = _constant_range(start, 0, 1) if name == "Fall" else (_constant(start),) * 2
    if endpoints != ((_float32(.75), _float32(.9999)) if name == "Fall" else (0, 0)):
        return None
    value = module["frameOverTime"]
    expected_mode = 0 if name in {"Fall", "flash"} else 1
    if value["minMaxState"] != expected_mode or value["scalar"] != (0 if name == "Fall" else _float32(.9999)):
        return None
    if expected_mode:
        raw = value["maxCurve"]
        if (raw["m_PreInfinity"], raw["m_PostInfinity"]) != (2, 2):
            return None
        keys = []
        for key in raw["m_Curve"]:
            if key["weightedMode"]:
                if (name != "light_big" or key["weightedMode"] != 3 or key["inSlope"] != math.inf
                        or key["outSlope"] != math.inf or key["time"] != _float32(.1556786745786667)
                        or (key["inWeight"], key["outWeight"]) != (_float32(1 / 3),) * 2):
                    return None
                # Both adjacent segments are steps, so the authored weights have no effect.
                key = {**key, "weightedMode": 0}
            keys.append(key)
        value = {**value, "maxCurve": {**raw, "m_Curve": keys}}
    pack = _scalar(value, deadline, through=1)
    if pack is None:
        return None
    return {"tiles": [columns, rows], "row": row, "frame": pack, "start": endpoints, "period": 0}


def _source_state(source, name):
    count, capacity, duration = _BURSTS[name]
    delay = .25 if name in {"Fall", "flash"} else 0
    seed = _SEED if delay else 0
    if (_enabled(source) != _MODULES[name] or not source["playOnAwake"]
            or source["autoRandomSeed"] != (name == "Break") or source["randomSeed"] != seed
            or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or source["lengthInSec"] != duration or _constant(source["startDelay"]) != delay
            or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction"))):
        return None
    initial, emission = source["InitialModule"], source["EmissionModule"]
    lifetime = {"Break": _float32(.6), "flash": .75}.get(name, 1)
    gravity = 2 if name == "Fall" else 0
    if (_constant(initial["startLifetime"]) != lifetime or _constant(initial["gravityModifier"]) != gravity
            or initial["maxNumParticles"] != capacity or initial["size3D"] != (name in {"Break", "light_big"})
            or initial["rotation3D"] or initial["randomizeRotationDirection"]
            or any(_constant(emission[key]) != 0 for key in ("rateOverTime", "rateOverDistance"))
            or emission["m_BurstCount"] != 1 or len(emission["m_Bursts"]) != 1):
        return None
    burst, = emission["m_Bursts"]
    if (burst["time"] != 0 or burst["cycleCount"] != 1 or burst["probability"] != 1
            or _constant(burst["countCurve"]) != count):
        return None
    color = _rgba8(initial, source["ColorModule"])
    if color is None:
        return None
    roll = initial["startRotation"]
    if name == "Fall":
        size = _constant_range(initial["startSize"], 0, 10)
        speed = _constant_range(initial["startSpeed"], 0, 32)
        roll_range = _constant_range(roll, -7, 7)
        angle = _float32(1.04719758)
        if size != (.5, 1) or speed != (30, 10) or roll_range != (-angle, angle):
            return None
    else:
        size = [_constant(initial[key]) for key in ("startSize", "startSizeY", "startSizeZ")]
        expected = {"Break": [11, 6, 1], "light_big": [3, .75, _float32(.1)], "flash": [150, 1, 1]}
        if size != expected[name] or _constant(initial["startSpeed"]) != 0:
            return None
        if not initial["size3D"]:
            size = [size[0]] * 3
        speed = None
        turn = _float32(6.283185)
        roll_range = _constant_range(roll, -7, 7) if name == "light_big" else (_constant(roll),) * 2
        if roll_range != ((turn, -turn) if name == "light_big" else (0, 0)):
            return None
    result = {"seed": seed, "count": count, "lifetime": lifetime, "delay": delay, "size": size,
              "rollRange": roll_range, "color": color["rgba8"]}
    if speed is not None:
        result.update(speedRange=speed, gravity=gravity)
    return result


def _shape(fields, name):
    cone = name == "Fall"
    radius, arc = fields["radius"], fields["arc"]
    scale = [fields["m_Scale"][axis] for axis in "xyz"]
    angle = 45 if cone else 25
    if (fields["type"] != (4 if cone else 5) or fields["angle"] != angle or fields["length"] != 5
            or scale != ([1, 1, 1] if cone else [8, 5, 1]) or fields["radiusThickness"] != 1
            or fields["m_Position"] != _ZERO or fields["m_Rotation"] != _ZERO or fields["boxThickness"] != _ZERO
            or fields["placementMode"] or radius["value"] != (_float32(.1) if cone else 1)
            or arc["value"] != 360 or radius["mode"] or arc["mode"] != (3 if cone else 0)
            or any(item["spread"] or _constant(item["speed"]) != 1 for item in (radius, arc))
            or any(fields[key] for key in ("alignToDirection", "randomDirectionAmount", "sphericalDirectionAmount",
                                           "randomPositionAmount"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return {"type": fields["type"], "scale": scale, "radius": radius["value"], "angle": angle,
            "arc": arc["value"], "arcMode": arc["mode"]}


def _motion(source, name, deadline):
    rotation = source["RotationModule"]
    spin = rotation["curve"]
    if rotation["separateAxes"]:
        return None
    result = {}
    if name in {"Fall", "light_big"}:
        shape = _shape(source["ShapeModule"], name)
        if shape is None:
            return None
        result["shape"] = shape
    if name != "light_big":
        rates = _constant_range(spin, -13, 13)
        if rates != _SPIN:
            return None
        result["spinRange"] = rates
        if name == "Fall":
            clamp = source["ClampVelocityModule"]
            limit = _constant(clamp["magnitude"])
            if (clamp["separateAxis"] or clamp["inWorldSpace"] or _constant(clamp["drag"]) != 0
                    or limit != 1 or clamp["dampen"] != _float32(.1)):
                return None
            result["clamp"] = {"limit": limit, "dampen": clamp["dampen"]}
        return result
    if spin["minMaxState"] != 2 or spin["scalar"] != _float32(13.962634):
        return None
    spin_curves = [_curve(spin[key], deadline, expected=((0, 0, math.inf, math.inf), (.25, sign, 0, 0)))
                   for key, sign in (("minCurve", -1), ("maxCurve", 1))]
    velocity = source["VelocityModule"]
    if (any(curve is None for curve in spin_curves) or velocity["inWorldSpace"]
            or _constant(velocity["speedModifier"]) != 1
            or any(_constant(velocity[key]) != 0 for key in ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX",
                                                            "orbitalOffsetY", "orbitalOffsetZ", "radial"))):
        return None
    y_slope = _float32(-.8)
    velocity_specs = (
        (1, ((0, 0, 0, 0), (1, 0, 0, 0))),
        (1.5, ((0, _float32(-.2), y_slope, y_slope), (1, -1, y_slope, y_slope))),
        (25, ((.25, 0, math.inf, math.inf), (_float32(.3), 1, 0, 0))),
    )
    velocity_curves = []
    for axis, (multiplier, expected) in zip("xyz", velocity_specs):
        curve = velocity[axis]
        if curve["minMaxState"] != 1 or curve["scalar"] != multiplier:
            return None
        packed = _curve(curve["maxCurve"], deadline, expected=expected)
        if packed is None:
            return None
        mode, keys = packed
        velocity_curves.append((mode, [(stamp, [value * multiplier for value in coefficients])
                                       for stamp, coefficients in keys]))
    return {**result, "velocityCurves": velocity_curves, "spinCurves": spin_curves, "spinMultiplier": spin["scalar"]}


def _surface(objects, renderer, fields, name):
    render_mode, alignment, sort, bias, width = _RENDERERS[name]
    if (not fields["m_Enabled"] or not fields["m_AllowRoll"] or not fields["m_ApplyActiveColorSpace"]
            or (fields["m_RenderMode"], fields["m_RenderAlignment"], fields["m_SortMode"], fields["m_SortingFudge"],
                fields["m_MaxParticleSize"]) != (render_mode, alignment, sort, bias, width)
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_LengthScale"] != 2 or fields["m_NormalDirection"] != 1 or fields["m_RenderingLayerMask"] != 1
            or fields["m_StaticBatchInfo"]["subMeshCount"] or (name == "Break" and fields["m_EnableGPUInstancing"])
            or any(fields[key] for key in ("m_UseCustomVertexStreams", "m_CameraVelocityScale", "m_VelocityScale",
                                           "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows",
                                           "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))
            or bool(fields["m_Mesh"]["m_PathID"]) != (name == "Break")):
        return None
    material = _add_material if name == "flash" else _alpha_material
    texture = material(objects, renderer, fields["m_Materials"])
    if texture is None or texture.peek_name() != _ATLASES[name][1]:
        return None
    return texture


def _mesh(reader, deadline):
    import numpy as np

    tree = reader.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    if (tree["m_Name"] != "pPlane1" or vertices["m_VertexCount"] != 49 or len(submeshes) != 1
            or (submeshes[0]["indexCount"], submeshes[0]["topology"]) != (216, 0)
            or vertices["m_Channels"][3]["dimension"] or tree["m_BindPose"] or tree["m_MeshCompression"]
            or tree["m_StreamData"]["size"] or any(tree["m_Shapes"].values())):
        return None
    data = {}
    _, positions, _, uv, faces = viewer._geometry(reader, np.eye(4), rig_data=data, deadline=deadline)
    if (positions.shape != (49, 3) or not np.isfinite(positions).all() or (np.abs(positions) > 1).any()
            or not (positions[:, 2] == 0).all() or uv is None or uv.shape != (49, 2) or not np.isfinite(uv).all()
            or (uv < -1e-6).any() or (uv > 1 + 1e-6).any() or len(faces) != 1 or faces[0].size != 216
            or (faces[0] < 0).any() or (faces[0] >= 49).any() or data["colors"] is not None):
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].reshape(-1).tolist(),
            "vertexColors": None}


def _leaf(objects, game, name, deadline):
    typed = title._components(objects, game, _COMPONENTS)
    if typed is None:
        return None
    parts = typed[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    if (transform["m_Children"] or pose["rotation"] != title._IDENTITY["rotation"]
            or pose["scale"] != title._IDENTITY["scale"] or any(abs(value) > 100 for value in pose["translation"])):
        return None
    source = parts["ParticleSystem"][1]
    state = _source_state(source, name)
    texture = _surface(objects, *parts["ParticleSystemRenderer"], name)
    atlas = _atlas(source["UVModule"], name, deadline)
    if state is None or texture is None or atlas is None:
        return None
    position = pose["translation"]
    _, _, _, sort_bias, viewport = _RENDERERS[name]
    if name == "Break":
        renderer, fields = parts["ParticleSystemRenderer"]
        mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
        geometry = _mesh(mesh, deadline) if mesh is not None else None
        if geometry is None:
            return None
        return {**geometry, "position": position, "scale": state["size"], "lifetime": state["lifetime"],
                "delay": state["delay"], "color": state["color"], "atlasCurve": atlas["frame"],
                "maxViewportWidth": viewport, "sortBias": sort_bias}, texture
    motion = _motion(source, name, deadline)
    if motion is None:
        return None
    return {**state, **motion, "name": name, "position": position, "atlas": atlas, "maxViewportWidth": viewport,
            "sortBias": sort_bias, "texture": _ATLASES[name][0]}, texture


def _prefab(objects, game, deadline):
    typed = title._components(objects, game, {"Transform"})
    if typed is None:
        return None
    transform, fields = typed[1]["Transform"]
    if (len(fields["m_Children"]) != 1 or fields["m_Father"]["m_PathID"]
            or _authored_trs(fields) != title._IDENTITY):
        return None
    pivot = title._transform_child(objects, transform, fields["m_Children"][0])
    root = title._components(objects, pivot, _COMPONENTS) if pivot is not None else None
    if root is None or root[0]["m_Name"] != "root":
        return None
    _, parts = root
    transform, fields = parts["Transform"]
    if (len(fields["m_Children"]) != len(_NAMES) or _authored_trs(fields) != title._IDENTITY
            or _enabled(parts["ParticleSystem"][1]) != {"InitialModule"} or parts["ParticleSystemRenderer"][1]["m_Enabled"]):
        return None
    leaves, textures = {}, [None] * len(_ALIASES)
    for name, ref in zip(_NAMES, fields["m_Children"]):
        viewer._remaining(deadline)
        game = title._transform_child(objects, transform, ref)
        if game is None or game.peek_name() != name:
            return None
        decoded = _leaf(objects, game, name, deadline)
        if decoded is None:
            return None
        leaf, texture = decoded
        index = _ATLASES[name][0]
        if textures[index] is not None and viewer._key(textures[index]) != viewer._key(texture):
            return None
        textures[index] = texture
        leaves[name] = leaf
    return leaves.pop("Break"), list(leaves.values()), textures


def read(objects, mono, tracks, deadline, *, atlas_refs=None):
    """Return the supported native stage break and its verified texture references."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    accepted = None
    for track in tracks:
        source = controls.get(track["id"])
        if source is None or track["label"] != _TRACK or track.get("binding") or track.get("bindings"):
            continue
        owner, fields = source
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields,
                    (*title._NAMESPACE, "CustomControlTrack")) or not title._group(objects, owner, fields)):
                continue
            for event in track["events"]:
                values = event["values"]
                if event["label"] != _PREFAB or values.get("clipIn") != 0 or values.get("offset") != _ZERO:
                    continue
                viewer._remaining(deadline)
                control = particles._source(objects, owner, fields, event)
                if control is not None and control[0].peek_name() == _PREFAB:
                    effect = _prefab(objects, control[0], deadline)
                    if effect is not None:
                        if accepted is not None:
                            return None
                        accepted = track["id"], event["id"], effect
        except title._UNSUPPORTED:
            continue
    if accepted is None:
        return None
    track_id, event_id, (mesh, emitters, readers) = accepted
    textures = []
    try:
        for reader, alias in zip(readers, _ALIASES):
            if alias is not None and atlas_refs is not None and atlas_refs.get(viewer._key(reader)) == alias:
                textures.append(alias)
            else:
                mips = particles._texture(reader, deadline)
                if not mips or len(mips) != 10:
                    return None
                textures.append(mips)
    except title._UNSUPPORTED:
        return None
    return {"trackId": track_id, "eventId": event_id, "textures": textures, "mesh": mesh, "emitters": emitters}
