"""Read the two original stretched rain emitters in Aion Expert."""

import math

from . import model_viewer as viewer, mv_studio_butterfly_glow as glow, mv_studio_butterfly_shine as shine
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


TRACK = "StageEffect/Expert/Control/par_01-02_rain"
_PROFILES = {
    "fx_par_so2028_01": ("01", 15, 600, 120, (3, 5), 1.2, 16, 1.5, ((0, 0), (-.2, -.15), (0, 0))),
    "fx_par_so2028_02": ("02", _float32(8.53), 300, 30, (1, 2), .2, 25, 0, ((-.15, .1), (-.1, .1), (3, 10))),
}
_SETTINGS = {**glow._SETTINGS, "cullingMode": 3, "randomSeed": 1950736341, "autoRandomSeed": False}
_RENDERER = {**{name: value for name, value in glow._RENDERER.items() if name != "m_Mesh"},
             "m_EnableGPUInstancing": False, "m_ApplyActiveColorSpace": False, "m_RenderMode": 1,
             "m_RenderingLayerMask": 0xFFFFFFFF, "m_MaxParticleSize": .5, "m_Flip": glow._ZERO, "m_LengthScale": 1}
_PARENT_Y = _float32(.01)
_ROTATION = [math.sqrt(.5), 0, 0, math.sqrt(.5)]


def _size_curve(source):
    size = source["curve"]
    if source["separateAxes"] or (size["minMaxState"], size["minScalar"], size["scalar"]) != (2, 1, 1):
        return None
    result = []
    for name in ("minCurve", "maxCurve"):
        curve = size[name]
        keys = curve["m_Curve"]
        if (len(keys) != 3 or (curve["m_PreInfinity"], curve["m_PostInfinity"]) != (2, 2)
                or not (keys[0]["time"] == 0 < keys[1]["time"] < keys[2]["time"] == 1)):
            return None
        rows = []
        for key in keys:
            if (key["weightedMode"] or not 0 <= key["value"] <= 1
                    or not all(-8 <= key[side] <= 8 for side in ("inSlope", "outSlope"))):
                return None
            rows.append([key[name] for name in ("time", "value", "inSlope", "outSlope")])
        result.append(rows)
    return result


def _color_curves(source):
    start = source["InitialModule"]["startColor"]
    life = source["ColorModule"]["gradient"]
    if start["minMaxState"] != 4 or life["minMaxState"] != 1:
        return None
    initial, lifetime = start["maxGradient"], life["maxGradient"]
    start_rgb = shine._gradient(initial, "ctime", 3, "rgb")
    start_alpha = shine._gradient(initial, "atime", 2, "a")
    rgb = shine._gradient(lifetime, "ctime", 2, "rgb")
    alpha = shine._gradient(lifetime, "atime", 4, "a")
    if not start_rgb or start_alpha != [[0, 1], [65535, 1]] or not rgb or not alpha:
        return None
    # Preserve authored sixteen-bit key phases so the preview can reproduce
    # Unity's packed lifetime-color cache before interpolating the bytes.
    if any(rows[0][0] != 0 or rows[-1][0] != 65535 for rows in (start_rgb, rgb, alpha)):
        return None
    return {"startRGB": start_rgb, "colorKeys": {"rgb": rgb, "alpha": alpha}}


def _shape(source, length):
    if (not glow._matches(source, {"type": 5, "radiusThickness": 1, "placementMode": 0, "alignToDirection": False,
                                  "m_Position": glow._ZERO, "m_Rotation": glow._ZERO, "boxThickness": glow._ZERO,
                                  "m_Scale": {"x": 25, "y": length, "z": 0}})
            or any(source[name] for name in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(source[name] != glow._NULL for name in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                            "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return False
    return all(glow._matches(source[name], {"mode": 0, "spread": 0, "value": value})
               and _constant(source[name]["speed"]) == 1 for name, value in (("radius", .5), ("arc", 360)))


def _emission(source, opening, rate):
    if _constant(source["rateOverTime"]) != rate or _constant(source["rateOverDistance"]) != 0:
        return False
    bursts = source["m_Bursts"]
    if opening:
        return source["m_BurstCount"] == 0 and not bursts
    if source["m_BurstCount"] != 1 or len(bursts) != 1:
        return False
    burst = bursts[0]
    return (glow._matches(burst, {"time": 0, "cycleCount": 1, "probability": 1})
            and _constant(burst["countCurve"]) == 0)


def _system(source, profile):
    key, _, capacity, rate, speed, initial_y, box_y, gravity, drift = profile
    opening = key == "01"
    settings = {**_SETTINGS, "lengthInSec": .5 if opening else 2.5, "looping": opening, "prewarm": opening}
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != shine._MODULES or not glow._matches(source, settings) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    life_matches = (_constant(initial["startLifetime"]) == _float32(1.4) if opening
                    else shine._range(initial["startLifetime"], 1.5, 2))
    if (not life_matches or not glow._matches(initial, {"size3D": True, "rotation3D": False, "maxNumParticles": capacity,
                                                        "randomizeRotationDirection": 0})
            or any(not shine._range(initial[name], *bounds) for name, bounds in (
                ("startSpeed", speed), ("startSize", (.2, .3)), ("startSizeY", (initial_y, 1.5)),
                ("startSizeZ", (.2, .3)), ("startRotation", (0, 0))))
            or _constant(initial["gravityModifier"]) != gravity or not _shape(source["ShapeModule"], box_y)
            or not _emission(source["EmissionModule"], opening, rate)):
        return None
    velocity = source["VelocityModule"]
    if (velocity["inWorldSpace"] or _constant(velocity["speedModifier"]) != 1
            or any(not shine._range(velocity[axis], *bounds) for axis, bounds in zip("xyz", drift))
            or any(_constant(velocity[name]) != 0 for name in ("radial", "orbitalX", "orbitalY", "orbitalZ",
                                                              "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ"))):
        return None
    sheet = source["UVModule"]
    if (not glow._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 20, "tilesX": 4, "tilesY": 4,
                                  "flipU": 0, "flipV": 0, "randomRow": False})
            or not sheet["uvChannelMask"] & 1 or _constant(sheet["frameOverTime"]) != 0
            or _constant(sheet["startFrame"]) != .125):
        return None
    size, color = _size_curve(source["SizeModule"]), _color_curves(source)
    return {**color, "sizeKeys": size} if size is not None and color is not None else None


def _renderer(objects, renderer, fields):
    if not glow._matches(fields, _RENDERER):
        return None
    # The unused mode-1 Mesh pointer is Unity's built-in primitive.
    pointer = fields["m_Mesh"]
    file_id, references = pointer["m_FileID"], renderer.assets_file.externals
    if (pointer["m_PathID"] != 10202 or not 0 < file_id <= len(references)
            or references[file_id - 1].path.replace("\\", "/").lower() != "library/unity default resources"):
        return None
    return glow._material_texture(objects, renderer, fields)


def _prefab(objects, game, deadline):
    name = game.peek_name()
    profile = _PROFILES.get(name)
    if profile is None:
        return None
    viewer._remaining(deadline)
    for index, node in enumerate((name, "root", "all")):
        parts = title._components(objects, game, {"Transform"}, layer=1) if game is not None else None
        if parts is None or parts[0]["m_Name"] != node:
            return None
        transform, fields = parts[1]["Transform"]
        expected = {**title._IDENTITY, "translation": [0, _PARENT_Y, 0]} if node == "all" else title._IDENTITY
        if _authored_trs(fields) != expected or index == 0 and fields["m_Father"] != glow._NULL:
            return None
        if node == "all":
            game = glow._child(objects, transform, fields, "rain")
        else:
            child, = fields["m_Children"]
            game = title._transform_child(objects, transform, child)
    if game is None:
        return None
    parts = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=1)
    if parts is None:
        return None
    leaf = parts[1]
    _, transform = leaf["Transform"]
    pose = _authored_trs(transform)
    position = [-_float32(.19), profile[1], -_float32(3.88)]
    if (transform["m_Children"] or pose["translation"] != position or pose["scale"] != [1, 1, 1]
            or any(abs(a - b) > 1e-8 for a, b in zip(pose["rotation"], _ROTATION))):
        return None
    source = _system(leaf["ParticleSystem"][1], profile)
    texture = _renderer(objects, *leaf["ParticleSystemRenderer"])
    if source is None or texture is None:
        return None
    position[1] = _float32(position[1] + _PARENT_Y)
    return {"profile": profile[0], "position": position, "rotation": pose["rotation"]}, source, texture


def read(objects, mono, tracks, deadline):
    """Return the supported rain cues and their original shared texture."""
    matches = [track for track in tracks if track.get("label") == TRACK and not track.get("binding")
               and not track.get("bindings")]
    if len(matches) != 1:
        return None
    track, = matches
    declaration = next(((owner, fields) for key, (owner, fields, kind) in mono.items()
                        if kind == "CustomControlTrack" and timeline._id(key) == track["id"]), None)
    if declaration is None:
        return None
    owner, fields = declaration
    try:
        if (not fields["m_Enabled"] or fields["m_Name"] != "par_01-02_rain" or not 1 <= len(fields["m_Clips"]) <= 2
                or not 1 <= len(track["events"]) <= 2
                or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                or not title._group(objects, owner, fields, "control")):
            return None
    except title._UNSUPPORTED:
        return None
    cues, shared, atlas = [], None, None
    for cue in track["events"]:
        try:
            control = particles._source(objects, owner, fields, cue)
            effect = _prefab(objects, control[0], deadline) if control is not None else None
        except title._UNSUPPORTED:
            continue
        if effect is None:
            continue
        info, source, texture = effect
        if (shared is not None and shared != source or atlas is not None and viewer._key(atlas) != viewer._key(texture)):
            continue
        cues.append({**info, "trackId": track["id"], "eventId": cue["id"]})
        shared, atlas = source, texture
    if not cues:
        return None
    try:
        levels = particles._texture(atlas, deadline)
    except title._UNSUPPORTED:
        return None
    if not levels:
        return None
    return {"schema": 1, **shared, "cues": cues, "texture": levels, "uv": [.25, .25, .5, 0], "maxViewportWidth": .5,
            "material": {"tint": [1, 1, 1, 1], "queue": 3010, "cull": 0, "blend": "add", "premultiply": False}}
