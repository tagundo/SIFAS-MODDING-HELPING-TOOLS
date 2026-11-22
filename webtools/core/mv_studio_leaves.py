"""Read the native falling and floor autumn leaves in Aion Expert."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


RED_TRACK = "StageEffect/Expert/Control/par_06_momij_red"
FLOOR_TRACK = "StageEffect/Expert/Control/par_07_momiji_floor"
PROFILES = {
    "StageEffect/Expert/Control/par_03_momij_green": ("03", "green", 12, 0),
    "StageEffect/Expert/Control/par_04_momij_yellow": ("04", "yellow", 10, .5),
    RED_TRACK: ("06", "red", 20, .25),
    FLOOR_TRACK: ("07", "floor", None, .25),
}
_POSITION = [_float32(.65), 5, -_float32(.46)]
_ROTATION = [.7071067811865475, 0, 0, .7071067811865475]
_SEED = -1015692234
_RED_SEED = 670425550
_MESH = 7538295215578040852
_ROLL = .7853981256484985
_PI_OVER_TWO = 1.570796251296997
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "RotationBySpeedModule", "RotationModule",
            "ShapeModule", "UVModule", "VelocityModule"}
_SETTINGS = {**billboard._SETTINGS, "lengthInSec": 10, "looping": True, "cullingMode": 3, "autoRandomSeed": False,
             "randomSeed": _SEED}
_RENDERER = {**billboard._RENDERER, "m_RenderMode": 4, "m_RenderingLayerMask": 0xFFFFFFFF, "m_MaxParticleSize": .5,
             "m_Flip": billboard._ZERO, "m_EnableGPUInstancing": False, "m_ApplyActiveColorSpace": False,
             "m_Mesh": {"m_FileID": 0, "m_PathID": _MESH}}
_MATERIAL = {"queue": 3010, "cull": 0, "blend": "alpha", "premultiply": False, "tint": [1, 1, 1, 1]}


def _curve_matches(source, values):
    keys = source["m_Curve"]
    return ((source["m_PreInfinity"], source["m_PostInfinity"]) == (2, 2) and len(keys) == 2
            and all((key["time"], key["value"], key["inSlope"], key["outSlope"], key["weightedMode"])
                    == (index, value, 0, 0, 0) for index, (key, value) in enumerate(zip(keys, values))))


def _minmax(source, scale, minimum, maximum):
    return ((source["minMaxState"], source["minScalar"], source["scalar"]) == (2, *scale)
            and _curve_matches(source["minCurve"], minimum) and _curve_matches(source["maxCurve"], maximum))


def _shape(source):
    if (not billboard._matches(source, {"type": 5, "placementMode": 0, "radiusThickness": 1, "alignToDirection": False,
                                       "m_Position": billboard._ZERO, "m_Rotation": billboard._ZERO,
                                       "m_Scale": {"x": 13, "y": 10, "z": 2}, "boxThickness": billboard._ZERO})
            or any(source[name] for name in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(source[name] != billboard._NULL for name in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                                 "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return False
    return all(billboard._matches(source[name], {"value": value, "mode": 0, "spread": 0})
               and _constant(source[name]["speed"]) == 1 for name, value in (("radius", 1), ("arc", 360)))


def _motion(source):
    rotation = source["RotationModule"]
    by_speed = source["RotationBySpeedModule"]
    pi = 3.141592502593994
    if (not rotation["separateAxes"] or not by_speed["separateAxes"] or by_speed["range"] != {"x": 0, "y": 1}
            or any(not shine._range(rotation[key], first, last) for key, first, last in (
                ("x", -.8726646304130554, 1), ("y", -.5235987901687622, 1), ("curve", _PI_OVER_TWO, -_PI_OVER_TWO)))
            or any(not shine._range(by_speed[key], first, last) for key, first, last in (
                ("x", -_ROLL, _ROLL), ("y", -pi, pi), ("curve", -_PI_OVER_TWO, pi)))):
        return False
    velocity = source["VelocityModule"]
    if (velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1
            or _constant(velocity["orbitalZ"]) != _float32(.2)
            or any(_constant(velocity[name]) != 0 for name in ("radial", "orbitalX", "orbitalY",
                                                              "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return False
    return all(_minmax(velocity[axis], scale, minimum, maximum) for axis, scale, minimum, maximum in (
        ("x", (-10, 1), (-1, 1), (1, -1)), ("y", (-5, 1), (1, -1), (-1, 1)), ("z", (0, 0), (1, -1), (-1, 1))))


def _colors(source, profile):
    start = source["InitialModule"]["startColor"]
    life = source["ColorModule"]["gradient"]
    if life["minMaxState"] != 1:
        return None
    maximum = life["maxGradient"]
    rgb = shine._gradient(maximum, "ctime", 2, "rgb")
    alpha = shine._gradient(maximum, "atime", 4, "a")
    if rgb != [[0, 1, 1, 1], [65535, 1, 1, 1]] or alpha != [[0, 0], [6554, 1], [58982, 1], [65535, 0]]:
        return None
    if profile != "04":
        initial = start["maxGradient"]
        rgb = shine._gradient(initial, "ctime", 3, "rgb")
        initial_alpha = shine._gradient(initial, "atime", 2, "a")
        if (start["minMaxState"] != (1 if profile == "03" else 4) or not rgb or rgb[0][0] != 0 or rgb[-1][0] != 65535
                or initial_alpha != [[0, 1], [65535, 1]]):
            return None
        color = {"rgb": rgb, "alpha": initial_alpha}
    else:
        if not billboard._matches(start, {"minMaxState": 0, "maxColor": billboard._WHITE}):
            return None
        color = [1, 1, 1, 1]
    return color, alpha


def _system(source, profile, rate, atlas_x):
    red = profile == "06"
    settings = {**_SETTINGS, "playOnAwake": False, "prewarm": True, "randomSeed": _RED_SEED} if red else _SETTINGS
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != _MODULES or not billboard._matches(source, settings) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    if (not billboard._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 200,
                                        "randomizeRotationDirection": 0})
            or any(not shine._range(initial[name], first, last) for name, first, last in (
                ("startLifetime", 5.5 if red else 6, 7), ("startSize", .5, .8), ("startRotation", -_ROLL, _ROLL),
                ("startRotationX", 0, 3.1415927410125732), ("startRotationY", 0, 3.1415927410125732)))
            or _constant(initial["gravityModifier"]) != _float32(.01)
            or not _minmax(initial["startSpeed"], (5, 1), (1, 0), (.00040886178612709045, 1))
            or not _shape(source["ShapeModule"]) or not _motion(source)):
        return None
    emission = source["EmissionModule"]
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or _constant(emission["rateOverTime"]) != rate):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 2, "tilesX": 4,
                                       "tilesY": 4, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .25 + atlas_x / 4):
        return None
    return _colors(source, profile)


def _geometry(mesh, deadline):
    import numpy as np

    if mesh is None or mesh.peek_name() != "flower" or not 0 < mesh.byte_size <= 4096:
        return None
    tree = mesh.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    channels = vertices["m_Channels"]
    if (vertices["m_VertexCount"] != 22 or len(submeshes) != 1
            or (submeshes[0]["indexCount"], submeshes[0]["topology"]) != (60, 0)
            or channels[0]["format"] != 0 or channels[0]["dimension"] != 3 or channels[3]["dimension"] != 0
            or channels[4]["format"] != 0 or channels[4]["dimension"] != 2
            or tree["m_BindPose"] or tree["m_MeshCompression"] or tree["m_StreamData"]["size"]
            or any(tree["m_Shapes"].values())):
        return None
    _, positions, _, uv, faces = viewer._geometry(mesh, np.eye(4), deadline=deadline)
    if (positions.shape != (22, 3) or np.abs(positions).max() > .11
            or uv is None or uv.shape != (22, 2) or uv.min() < 0 or uv.max() > 1
            or len(faces) != 1 or faces[0].shape != (20, 3)):
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].ravel().tolist()}


def _prefab(objects, game, profile, deadline):
    number, label, rate, atlas_x = profile
    viewer._remaining(deadline)
    for name in (f"fx_par_so2028_{number}", "root"):
        outer = title._components(objects, game, {"Transform"}, layer=1) if game is not None else None
        if outer is None or outer[0]["m_Name"] != name:
            return None
        transform, fields = outer[1]["Transform"]
        if _authored_trs(fields) != title._IDENTITY or name != "root" and fields["m_Father"] != billboard._NULL:
            return None
        if name != "root":
            child, = fields["m_Children"]
            game = title._transform_child(objects, transform, child)
    if number == "07":
        from . import mv_studio_floor_leaves

        return mv_studio_floor_leaves.read(objects, transform, fields)
    child, = fields["m_Children"]
    game = title._transform_child(objects, transform, child)
    leaf = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"},
                             layer=1) if game is not None else None
    if leaf is None or leaf[0]["m_Name"] != f"autumnLeaves_{label}":
        return None
    parts = leaf[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    if (pose["translation"] != _POSITION or pose["scale"] != [1, 1, 1] or transform["m_Children"]
            or any(abs(left - right) > 1e-8 for left, right in zip(pose["rotation"], _ROTATION))):
        return None
    renderer, fields = parts["ParticleSystemRenderer"]
    if not billboard._matches(fields, _RENDERER):
        return None
    state = _system(parts["ParticleSystem"][1], number, rate, atlas_x)
    atlas = billboard._material_texture(objects, renderer, fields, alpha=True)
    mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
    if state is None or atlas is None or mesh is None:
        return None
    start, alpha = state
    cue = {"profile": number, "position": pose["translation"], "rotation": pose["rotation"], "rate": rate,
           "uv": [.25, .25, atlas_x, .25], "startColor": start}
    return cue, alpha, atlas, mesh


def _track_cues(objects, owner, fields, track, profile, deadline):
    red = profile[0] == "06"
    limit = {"06": 4, "07": 3}.get(profile[0], 1)
    if (fields["m_Name"] != track["label"].rsplit("/", 1)[1] or not fields["m_Enabled"]
            or not 1 <= len(fields["m_Clips"]) <= limit or not 1 <= len(track["events"]) <= limit
            or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
            or not title._group(objects, owner, fields, "control")):
        return []
    result, prefabs = [], {}
    for event in track["events"]:
        try:
            control = particles._source(objects, owner, fields, event)
            overwrite = red and control is None
            if overwrite:
                control = particles._source(objects, owner, fields, event, overwrite_seed=True)
            if control is None:
                continue
            game, seed = control
            key = viewer._key(game)
            if key not in prefabs:
                prefabs[key] = _prefab(objects, game, profile, deadline)
            effect = prefabs[key]
            if effect is None:
                continue
            cue, alpha, texture, mesh = effect
            info = {**cue, "trackId": track["id"], "eventId": event["id"]}
            if red:
                info.update({"seed": seed if overwrite else _RED_SEED, "overwriteRandomSeed": overwrite})
            result.append((event["start"], info, alpha, texture, mesh))
        except title._UNSUPPORTED:
            continue
    return result


def read(objects, mono, tracks, deadline):
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    accepted = {}
    for track in tracks:
        profile = PROFILES.get(track["label"])
        source = controls.get(track["id"])
        if profile is None or source is None or track.get("binding") or track.get("bindings"):
            continue
        owner, fields = source
        try:
            effects = _track_cues(objects, owner, fields, track, profile, deadline)
        except title._UNSUPPORTED:
            continue
        if effects:
            label = track["label"]
            accepted[label] = [] if label in accepted else effects
    cues, alpha, atlas, mesh = [], None, None, None
    effects = sorted((effect for group in accepted.values() for effect in group), key=lambda effect: effect[0])
    for _, cue, fade, texture, source_mesh in effects:
        if (alpha is not None and alpha != fade or atlas is not None and viewer._key(atlas) != viewer._key(texture)
                or mesh is not None and viewer._key(mesh) != viewer._key(source_mesh)):
            continue
        cues.append(cue)
        alpha, atlas, mesh = fade, texture, source_mesh
    if not cues:
        return None
    try:
        geometry = _geometry(mesh, deadline)
        levels = particles._texture(atlas, deadline) if geometry is not None else None
    except title._UNSUPPORTED:
        return None
    if not levels:
        return None
    return {"schema": 1, "geometry": geometry, "texture": levels, "alphaKeys": alpha, "cues": cues, "material": _MATERIAL}
