"""Decode the two native Aion Expert confetti emitters and their shared mesh."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard
from . import mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title
from . import mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


TRACK = "StageEffect/Expert/Control/par_08_confetti"
ROLES = {"confetti_01": "air", "confetti_floor": "floor"}
_PREFAB = 7810072528735722267
_MESH = -6147347411476304519
_RENDERER = {**leaves._RENDERER, "m_Mesh": {"m_FileID": 0, "m_PathID": _MESH}}
_SETTINGS = {**billboard._SETTINGS, "looping": True, "prewarm": True, "playOnAwake": False,
             "autoRandomSeed": False, "ringBufferLoopRange": {"x": 0, "y": 1}}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "RotationModule", "ShapeModule", "UVModule"}
_MATERIAL = {"queue": 3010, "cull": 0, "blend": "add", "saturate": False, "premultiply": False, "tint": [1, 1, 1, 1],
             "stencil": "always", "stencilRef": 2}
_UV = [.5, .5, 0, .5]
_ORIGINS = {"air": [0, 15, 0], "floor": [0, _float32(.06), 0]}
_SEEDS = {"air": 1425677110, "floor": -1015692234}
_START_COLORS = [[1, .7585158348083496, .34433960914611816, 1], [1, .8903166651725769, .43867921829223633, 1]]
_TURN = 6.283185005187988
_SIZE_CURVE = ((0, 1, 0, 0), (_float32(.95), 1, 0, 0), (1, 0, -19.999996185302734, -19.999996185302734))


def _velocity_curve(source, times, values, post):
    keys = source["m_Curve"]
    return ((source["m_PreInfinity"], source["m_PostInfinity"]) == (2, post) and len(keys) == len(times)
            and all(not key["weightedMode"] and (key["time"], key["value"], key["inSlope"], key["outSlope"])
                    == (time, value, 0, 0) for key, time, value in zip(keys, times, values)))


def _air_motion(source):
    size, velocity = source["SizeModule"], source["VelocityModule"]
    curve = size["curve"]
    if (size["separateAxes"] or (curve["minMaxState"], curve["minScalar"], curve["scalar"]) != (1, 1, 1)
            or curve["minCurve"]["m_Curve"] or not leaves._keyframes_match(curve["maxCurve"], _SIZE_CURVE)
            or velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1
            or _constant(velocity["radial"]) != .5
            or any(_constant(velocity[name]) != 0 for name in ("orbitalX", "orbitalY", "orbitalZ",
                                                               "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return False
    periodic = (0, .25, .5)
    for axis, scales, times, minimum, maximum, post in (
            ("x", (-1, 2), periodic, (-1, 1, -1), (1, -1, 1), 0),
            ("y", (0, 1.5), (0, 1), (-.5, -.5), (-1, -1), 2),
            ("z", (0, 1), periodic, (-1, 1, -1), (1, -1, 1), 0)):
        item = velocity[axis]
        if ((item["minMaxState"], item["minScalar"], item["scalar"]) != (2, *scales)
                or not _velocity_curve(item["minCurve"], times, minimum, post)
                or not _velocity_curve(item["maxCurve"], times, maximum, post)):
            return False
    return True


def _system(source, role):
    air = role == "air"
    modules = _MODULES | {"SizeModule", "VelocityModule"} if air else _MODULES
    settings = {**_SETTINGS, "lengthInSec": 90 if air else 10, "cullingMode": 0 if air else 3,
                "randomSeed": _SEEDS[role]}
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != modules or not billboard._matches(source, settings) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    start = initial["startColor"]
    colors = [[start[name][channel] for channel in "rgba"] for name in ("minColor", "maxColor")]
    if (not billboard._matches(initial, {"rotation3D": True, "size3D": False, "randomizeRotationDirection": 0,
                                        "maxNumParticles": 1000 if air else 200})
            or start["minMaxState"] != 2 or colors != _START_COLORS
            or not shine._range(initial["startSize"], 1.2, .9)
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "gravityModifier"))):
        return None
    rotation, shape = source["RotationModule"], source["ShapeModule"]
    euler = ("startRotation", "startRotationX", "startRotationY")
    if air:
        if (_constant(initial["startLifetime"]) != _float32(8.2)
                or any(not shine._range(initial[name], -_TURN, _TURN) for name in euler)
                or rotation["separateAxes"] or not shine._range(rotation["curve"], 10.471975326538086, 5.235987663269043)
                or not leaves._shape(shape, shape_type=5, scale=(30, 5, 10)) or not _air_motion(source)):
            return None
    elif (not shine._range(initial["startLifetime"], 5, 8)
          or [_constant(initial[name]) for name in euler] != [0, leaves._PI_OVER_TWO, 0]
          or not rotation["separateAxes"] or not shine._range(rotation["curve"], leaves._ROLL, -leaves._ROLL)
          or any(not shine._range(rotation[name], 0, 0) for name in ("x", "y"))
          or not leaves._shape(shape, shape_type=10, scale=(6, 4, 0), rotation=(90, 0, 0))):
        return None
    emission = source["EmissionModule"]
    rate = 70 if air else 3
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or _constant(emission["rateOverTime"]) != rate):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 2,
                                       "tilesY": 2, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .5):
        return None
    life = source["ColorModule"]["gradient"]
    maximum = life["maxGradient"]
    alpha = shine._gradient(maximum, "atime", 4, "a")
    if (life["minMaxState"] != 1 or shine._gradient(maximum, "ctime", 2, "rgb") != [[0, 1, 1, 1], [65535, 1, 1, 1]]
            or alpha != [[0, 0], [6554, 1], [62258 if air else 58982, 1], [65535, 0]]):
        return None
    return {"seed": _SEEDS[role] & 0xFFFFFFFF, "rate": rate, "startColors": colors, "alphaKeys": alpha}


def _geometry(mesh, deadline):
    import numpy as np

    if mesh.peek_name() != "confetti" or not 0 < mesh.byte_size <= 4096:
        return None
    tree = mesh.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    channels = vertices["m_Channels"]
    if (vertices["m_VertexCount"] != 16 or len(submeshes) != 1
            or (submeshes[0]["indexCount"], submeshes[0]["topology"]) != (42, 0)
            or channels[0]["format"] != 0 or channels[0]["dimension"] != 3 or channels[3]["dimension"] != 0
            or channels[4]["format"] != 0 or channels[4]["dimension"] != 2
            or tree["m_BindPose"] or tree["m_MeshCompression"] or tree["m_StreamData"]["size"]
            or any(tree["m_Shapes"].values())):
        return None
    _, positions, _, uv, faces = viewer._geometry(mesh, np.eye(4), deadline=deadline)
    if (positions.shape != (16, 3) or not np.isfinite(positions).all() or np.abs(positions).max() > .076
            or uv is None or uv.shape != (16, 2) or not np.isfinite(uv).all() or uv.min() < 0 or uv.max() > 1
            or len(faces) != 1 or faces[0].shape != (14, 3) or faces[0].min() < 0 or faces[0].max() >= len(positions)):
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].ravel().tolist()}


def _emitter(objects, game, role):
    body = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=1)
    if body is None:
        return None
    parts = body[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    if transform["m_Children"] or pose != {**title._IDENTITY, "translation": _ORIGINS[role]}:
        return None
    renderer, fields = parts["ParticleSystemRenderer"]
    if not billboard._matches(fields, {**_RENDERER, "m_RenderAlignment": 2 if role == "air" else 1}):
        return None
    data = _system(parts["ParticleSystem"][1], role)
    if data is None:
        return None
    mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
    atlas = billboard._material_texture(objects, renderer, fields)
    if mesh is None or atlas is None:
        return None
    row = {"role": role, "position": pose["translation"], "rotation": pose["rotation"], "scale": pose["scale"],
           "sortMode": fields["m_SortMode"], "maxViewportWidth": fields["m_MaxParticleSize"], **data}
    return row, mesh, atlas


def _prefab(objects, game, deadline):
    body = title._components(objects, game, {"Transform"}, layer=1)
    if body is None or body[0]["m_Name"] != "fx_par_so2028_08":
        return None
    root, fields = body[1]["Transform"]
    if fields["m_Father"] != billboard._NULL or _authored_trs(fields) != title._IDENTITY:
        return None
    child, = fields["m_Children"]
    child = title._transform_child(objects, root, child)
    body = title._components(objects, child, {"Transform"}, layer=1) if child is not None else None
    if body is None or body[0]["m_Name"] != "root":
        return None
    root, fields = body[1]["Transform"]
    if _authored_trs(fields) != title._IDENTITY or not 1 <= len(fields["m_Children"]) <= len(ROLES):
        return None
    rows, mesh, atlas = [], None, None
    seen = set()
    for ref in fields["m_Children"]:
        viewer._remaining(deadline)
        child = title._transform_child(objects, root, ref)
        role = ROLES.get(child.peek_name()) if child is not None else None
        if role is None or role in seen:
            return None
        seen.add(role)
        try:
            emitter = _emitter(objects, child, role)
        except title._UNSUPPORTED:
            continue
        if emitter is not None:
            row, source_mesh, source_atlas = emitter
            if ((mesh is not None and viewer._key(mesh) != viewer._key(source_mesh))
                    or (atlas is not None and viewer._key(atlas) != viewer._key(source_atlas))):
                continue
            rows.append(row)
            mesh, atlas = source_mesh, source_atlas
    return rows, mesh, atlas


def read(objects, mono, tracks, deadline):
    matches = [track for track in tracks if track["label"] == TRACK and not track.get("binding") and not track.get("bindings")]
    if len(matches) != 1:
        return None
    track, = matches
    source = next(((owner, fields) for key, (owner, fields, kind) in mono.items()
                   if kind == "CustomControlTrack" and timeline._id(key) == track["id"]), None)
    if source is None:
        return None
    owner, fields = source
    try:
        if (not billboard._matches(fields, {"m_Name": "par_08_confetti", "m_Enabled": True, "m_Muted": False})
                or not 1 <= len(fields["m_Clips"]) <= 3 or not 1 <= len(track["events"]) <= 3
                or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                or not title._group(objects, owner, fields, section="control")):
            return None
        cues, prefab = [], None
        for event in track["events"]:
            control = particles._source(objects, owner, fields, event)
            if control is None or control[0].path_id != _PREFAB:
                continue
            cues.append({"trackId": track["id"], "eventId": event["id"]})
            prefab = control[0]
        if not cues:
            return None
        native = _prefab(objects, prefab, deadline)
        if native is None:
            return None
        emitters, mesh, atlas = native
        if not emitters:
            return None
        geometry = _geometry(mesh, deadline)
        levels = particles._texture(atlas, deadline, sizes=(256,)) if geometry is not None else None
    except title._UNSUPPORTED:
        return None
    if not levels:
        return None
    return {"schema": 1, "geometry": geometry, "texture": levels, "material": _MATERIAL, "uv": _UV,
            "emitters": emitters, "cues": cues}


def saved_roles(descriptor):
    if not isinstance(descriptor, dict) or type(descriptor.get("schema")) is not int or descriptor["schema"] != 1:
        return None
    rows = descriptor.get("emitters")
    if not isinstance(rows, list) or not 1 <= len(rows) <= len(ROLES):
        return None
    if any(not isinstance(row, dict) or not isinstance(row.get("role"), str) for row in rows):
        return None
    roles = {row["role"] for row in rows}
    return roles if len(roles) == len(rows) and roles <= set(ROLES.values()) else None


def restore_saved(saved, original, active):
    """Restore source roles only for still-present cues and matching saved assets."""
    cues = [cue for cue in original["cues"] if (cue["trackId"], cue["eventId"]) in active]
    if not cues:
        return None
    if saved is None:
        return {**original, "cues": cues}
    if saved_roles(saved) is None or any(saved.get(key) != original[key] for key in ("geometry", "texture", "material", "uv")):
        return None
    saved_cues = saved.get("cues")
    if (not isinstance(saved_cues, list) or not 1 <= len(saved_cues) <= 3
            or not all(cue in original["cues"] for cue in saved_cues) or not any(cue in cues for cue in saved_cues)):
        return None
    existing = {row["role"]: row for row in saved["emitters"]}
    emitters = [existing.pop(row["role"], row) for row in original["emitters"]]
    emitters.extend(existing.values())
    return {**saved, "emitters": emitters} if emitters != saved["emitters"] else None
