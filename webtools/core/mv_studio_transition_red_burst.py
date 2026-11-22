"""Validate the separately authored red burst in Aion's leaf transition."""

from . import mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from .mv_studio_stage_title_particles import _constant, _float32


SEED = 1586243424
POSITION = [_float32(.512), _float32(.021), _float32(4.133)]
ROTATION = [0, .983316296761958, 0, -.18190398709854855]
_MODULES = (leaves._MODULES - {"RotationBySpeedModule"}) | {"SizeModule"}
_SETTINGS = {**leaves._SETTINGS, "looping": False, "playOnAwake": False, "lengthInSec": 12, "randomSeed": SEED}
_PI = 3.1415927410125732
_TAU = 6.283185005187988
_WHITE_RGB = [[0, 1, 1, 1], [65535, 1, 1, 1]]
_WHITE_ALPHA = [[0, 1], [65535, 1]]
_ALPHA = [[0, 0], [1311, 1], [58982, 1], [65535, 0]]
_SPEED_MIN = ((0, 1, -2.207141160964966, -2.207141160964966), (.9980774521827698, .27537664771080017, 0, 0))
_SPEED_MAX = ((0, .6278756856918335, -1.1490671634674072, -1.1490671634674072),
              (.9980774521827698, .3180050849914551, -.12376324832439423, -.12376324832439423))
_MODIFIER_MIN = ((0, 1, -12.329466819763184, -12.329466819763184),
                 (.15709102153778076, .1557157337665558, -.6902754306793213, -.6902754306793213),
                 (1, .025065496563911438, 0, 0))
_MODIFIER_MAX = ((0, 1, -6.630202770233154, -6.630202770233154),
                 (.2608562409877777, .3196832239627838, -.9326057434082031, -.9326057434082031),
                 (1, .094718337059021, -.19471216201782227, -.19471216201782227))
_SIZE = ((.8644065856933594, _float32(.9), 0, 0), (1, 0, -17.877954483032227, -17.877954483032227))


def _curves(source, scalars, minimum, maximum):
    return ((source["minMaxState"], source["minScalar"], source["scalar"]) == scalars
            and leaves._keyframes_match(source["minCurve"], minimum)
            and leaves._keyframes_match(source["maxCurve"], maximum))


def _motion(source):
    initial = source["InitialModule"]
    roll = initial["startRotation"]
    if (not billboard._matches(initial, {"size3D": False, "rotation3D": False, "maxNumParticles": 1000,
                                        "randomizeRotationDirection": 0})
            or not shine._range(initial["startLifetime"], 5, 12) or not shine._range(initial["startSize"], .4, .2)
            or _constant(initial["gravityModifier"]) != _float32(.1)
            or not _curves(initial["startSpeed"], (2, 5, 3), _SPEED_MIN, _SPEED_MAX)
            or not _curves(roll, (2, 0, _TAU), ((0, 0, 0, 0), (.5, 1, 0, 0), (1, 0, 0, 0)),
                           ((0, 0, 0, 0), (.5, -1, 0, 0), (1, 0, 0, 0)))
            or any(not leaves._minmax(initial[name], (0, _PI), (0, 0), (0, 0)) for name in ("startRotationX", "startRotationY"))):
        return False
    velocity = source["VelocityModule"]
    if (velocity["inWorldSpace"] or not _curves(velocity["speedModifier"], (2, 1, 1), _MODIFIER_MIN, _MODIFIER_MAX)
            or any(not shine._range(velocity[name], first, last) for name, first, last in (
                ("x", -.1, 3), ("y", 1.2, 2.5), ("z", -.1, 1)))
            or _constant(velocity["orbitalOffsetX"]) != -_float32(.2) or _constant(velocity["orbitalZ"]) != _float32(.1)
            or _constant(velocity["radial"]) != -_float32(.2)
            or any(_constant(velocity[name]) != 0 for name in ("orbitalX", "orbitalY", "orbitalOffsetY", "orbitalOffsetZ"))):
        return False
    rotation = source["RotationModule"]
    size = source["SizeModule"]
    curve = size["curve"]
    return (not rotation["separateAxes"] and shine._range(rotation["curve"], 10.471975326538086, 5.235987663269043)
            and not size["separateAxes"] and (curve["minMaxState"], curve["minScalar"], curve["scalar"]) == (1, 1, 1)
            and not curve["minCurve"]["m_Curve"] and leaves._keyframes_match(curve["maxCurve"], _SIZE))


def _colors(source):
    life = source["ColorModule"]["gradient"]
    start = source["InitialModule"]["startColor"]
    if life["minMaxState"] != 1 or start["minMaxState"] != 3:
        return None
    maximum = life["maxGradient"]
    alpha = shine._gradient(maximum, "atime", 4, "a")
    if alpha != _ALPHA or shine._gradient(maximum, "ctime", 2, "rgb") != _WHITE_RGB:
        return None
    rgb, start_alpha = [], []
    for lane in ("minGradient", "maxGradient"):
        gradient = start[lane]
        rows = shine._gradient(gradient, "ctime", 2, "rgb")
        opacity = shine._gradient(gradient, "atime", 2, "a")
        if not rows or opacity != _WHITE_ALPHA:
            return None
        rgb.append(rows)
        start_alpha.append(opacity)
    return {"rgb": rgb, "alpha": start_alpha}, alpha


def read(source):
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != _MODULES or not billboard._matches(source, _SETTINGS) or _constant(source["startDelay"]) != 0:
        return None
    shape = source["ShapeModule"]
    if (shape["angle"] != _float32(19.18) or shape["length"] != _float32(1.43)
            or not leaves._shape(shape, shape_type=8, scale=(_float32(2.1), 1, .5),
                                 rotation=(_float32(-64.34), 0, 0), radius=_float32(.9))
            or not _motion(source)):
        return None
    emission = source["EmissionModule"]
    bursts = emission["m_Bursts"]
    expected = ((.1, 30), (.2, 100), (.4, 100), (.6, 60))
    if (emission["m_BurstCount"] != 4 or len(bursts) != 4
            or any(_constant(emission[name]) != 0 for name in ("rateOverTime", "rateOverDistance"))
            or any(not billboard._matches(burst, {"time": _float32(stamp), "cycleCount": 1, "probability": 1})
                   or _constant(burst["countCurve"]) != count for burst, (stamp, count) in zip(bursts, expected))):
        return None
    sheet = source["UVModule"]
    # A constant frame-over-time value selects the fifth cell even though
    # the serialized start frame is zero.
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 4,
                                       "tilesY": 4, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != .3125 or _constant(sheet["startFrame"]) != 0):
        return None
    return _colors(source)
