"""Read the independent native leaf emitters during Aion Expert's transition."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine
from . import mv_studio_leaves as leaves, mv_studio_stage_title as title, mv_studio_transition_red_burst as red_burst
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


_ROLES = {
    "burst_autumnLeaves_green": ("green-burst", -1015692234, 0, 50, 0, 0),
    "burst_autumnLeaves_yellow": ("yellow-burst", -930065881, 0, 50, .5, 0),
    "burst_autumnLeaves_red": ("red-burst", red_burst.SEED, 0, None, .25, 0),
    "autumnLeaves_red_in": ("red-in", 1722352272, 26, 30, .25, _float32(.6)),
}
_SETTINGS = {**leaves._SETTINGS, "looping": False, "playOnAwake": False}
_BURST_POSITION = [0, _float32(.57), 0]
_BURST_ROTATION = [-leaves._ROTATION[0], 0, 0, leaves._ROTATION[3]]
_IN_POSITION = [_float32(.65), 4, -_float32(.46)]
_BURST_ALPHA = [[0, 1], [58982, 1], [65535, 0]]
_BURST_VELOCITY = (("x", (-10, 1), (-1, 1), (1, -1)), ("y", (-5, 1), (-1, 1), (1, -1)),
                   ("z", (0, 1), (-1, 1), (1, -1)))
_IN_VELOCITY = (("x", (-10, 2), (-1, 1), (1, -1)), *leaves._VELOCITY_CURVES[1:])
_GRAVITY = {
    "minCurve": ((0, .09195709228515625, 0, 0), (.06452926248311996, -.9195404052734375, 0, 0)),
    "maxCurve": ((0, .17645278573036194, -7.342578887939453, -7.342578887939453), (.037464167922735214, -1, 0, 0)),
}


def _gravity(source):
    if (source["minMaxState"], source["minScalar"], source["scalar"]) != (2, 0, 1):
        return False
    for side, expected in _GRAVITY.items():
        curve = source[side]
        keys = curve["m_Curve"]
        if ((curve["m_PreInfinity"], curve["m_PostInfinity"]) != (2, 2) or len(keys) != 2
                or any(key["weightedMode"] or tuple(key[name] for name in ("time", "value", "inSlope", "outSlope")) != row
                       for key, row in zip(keys, expected))):
            return False
    return True


def _emission(source, rate, count):
    if (source["m_BurstCount"] != 1 or _constant(source["rateOverTime"]) != rate
            or _constant(source["rateOverDistance"]) != 0):
        return False
    burst, = source["m_Bursts"]
    return (billboard._matches(burst, {"time": 0, "cycleCount": 1, "probability": 1})
            and _constant(burst["countCurve"]) == count)


def _system(source, role, seed, rate, count, atlas_x, delay):
    incoming = role == "red-in"
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if (enabled != leaves._MODULES or not billboard._matches(source, {**_SETTINGS, "randomSeed": seed})
            or _constant(source["startDelay"]) != delay):
        return None
    initial = source["InitialModule"]
    lifetime = (6, 7) if incoming else (1.2, 1.5)
    if (not billboard._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 200,
                                        "randomizeRotationDirection": 0})
            or any(not shine._range(initial[name], *bounds) for name, bounds in (
                ("startLifetime", lifetime), ("startSize", (.5, .8)), ("startRotation", (-leaves._ROLL, leaves._ROLL)),
                ("startRotationX", (0, 3.1415927410125732)), ("startRotationY", (0, 3.1415927410125732))))
            or not _emission(source["EmissionModule"], rate, count)):
        return None
    shape = source["ShapeModule"]
    if incoming:
        if (_constant(initial["gravityModifier"]) != _float32(.01)
                or not leaves._minmax(initial["startSpeed"], (5, 1), (1, 0), (.00040886178612709045, 1))
                or not leaves._shape(shape, scale=(13, 10, 3)) or not leaves._motion(source, _IN_VELOCITY)):
            return None
    elif (not _gravity(initial["gravityModifier"]) or _constant(initial["startSpeed"]) != 0
          or shape["angle"] != 0 or shape["length"] != 5
          or not leaves._shape(shape, shape_type=8, scale=(_float32(3.7), 4.5, .5))
          or not leaves._motion(source, _BURST_VELOCITY)):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 2, "tilesX": 4,
                                       "tilesY": 4, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .25 + atlas_x / 4):
        return None
    return leaves._colors(source, role, alpha_keys=leaves._ALPHA_KEYS if incoming else _BURST_ALPHA)


def _emitter(objects, game, source):
    role, seed, rate, count, atlas_x, delay = source
    row = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=1)
    if row is None:
        return None
    parts = row[1]
    _, transform = parts["Transform"]
    renderer, fields = parts["ParticleSystemRenderer"]
    pose = _authored_trs(transform)
    incoming = role == "red-in"
    separate = role == "red-burst"
    position, rotation = (red_burst.POSITION, red_burst.ROTATION) if separate else (
        (_IN_POSITION, leaves._ROTATION) if incoming else (_BURST_POSITION, _BURST_ROTATION)
    )
    render = {**leaves._RENDERER, "m_RenderAlignment": 4} if separate else leaves._RENDERER
    if (pose != {**title._IDENTITY, "translation": position, "rotation": rotation} or transform["m_Children"]
            or not billboard._matches(fields, render)):
        return None
    system = parts["ParticleSystem"][1]
    data = red_burst.read(system) if separate else _system(system, *source)
    atlas = billboard._material_texture(objects, renderer, fields, alpha=True)
    mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
    if data is None or atlas is None or mesh is None:
        return None
    start, alpha = data
    emitter = {"role": role, "position": pose["translation"], "rotation": pose["rotation"], "uv": [.25, .25, atlas_x, .25],
               "seed": seed & 0xFFFFFFFF, "rate": rate, "startColor": start, "alphaKeys": alpha, "material": leaves._MATERIAL}
    return emitter, atlas, mesh


def read(objects, root, fields):
    """Keep every supported original role with a matching mesh and atlas."""
    refs = fields["m_Children"]
    if not 1 <= len(refs) <= len(_ROLES):
        return None
    found, emitters, atlas, mesh = set(), [], None, None
    for ref in refs:
        game = title._transform_child(objects, root, ref)
        name = game.peek_name() if game is not None else None
        if name not in _ROLES or name in found:
            return None
        found.add(name)
        source = _ROLES.get(name)
        try:
            result = _emitter(objects, game, source)
        except title._UNSUPPORTED:
            continue
        if result is None:
            continue
        emitter, image, geometry = result
        if (atlas is not None and viewer._key(atlas) != viewer._key(image)
                or mesh is not None and viewer._key(mesh) != viewer._key(geometry)):
            continue
        emitters.append(emitter)
        atlas, mesh = image, geometry
    if not emitters:
        return None
    return {"profile": "05", "emitters": emitters}, leaves._ALPHA_KEYS, atlas, mesh
