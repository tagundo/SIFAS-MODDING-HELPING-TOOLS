"""Read the separate floor leaf emitters of Aion Expert's .07 prefab."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard, mv_studio_butterfly_shine as shine
from . import mv_studio_leaves as leaves, mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_stage_title_particles import _constant, _float32


_POSITION = [0, _float32(.06), 0]
_RENDERER = {**leaves._RENDERER, "m_RenderAlignment": 1}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "RotationModule", "ShapeModule", "UVModule"}
_ROLES = (
    ("alpha", "autumnLeaves_floor_alb", leaves._SEED, 7, 5, 1, 1, 10),
    ("add", "autumnLeaves_floor_add", 363848346, 3, 4, .8, .8, 0),
)


def _shape(source):
    if (not billboard._matches(source, {"type": 10, "placementMode": 0, "radiusThickness": 1, "alignToDirection": False,
                                        "m_Position": billboard._ZERO, "m_Rotation": {"x": 90, "y": 0, "z": 0},
                                        "m_Scale": {"x": _float32(8.77), "y": _float32(4.9), "z": 0},
                                        "boxThickness": billboard._ZERO})
            or any(source[name] for name in ("randomDirectionAmount", "sphericalDirectionAmount", "randomPositionAmount"))
            or any(source[name] != billboard._NULL for name in ("m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                                 "m_Sprite", "m_SpriteRenderer", "m_Texture"))):
        return False
    return all(billboard._matches(source[name], {"value": value, "mode": 0, "spread": 0})
               and _constant(source[name]["speed"]) == 1 for name, value in (("radius", 1), ("arc", 360)))


def _emission(source, rate, burst_count):
    if _constant(source["rateOverTime"]) != rate or _constant(source["rateOverDistance"]) != 0:
        return False
    bursts = source["m_Bursts"]
    if not burst_count:
        return source["m_BurstCount"] == 0 and not bursts
    if source["m_BurstCount"] != 1 or len(bursts) != 1:
        return False
    burst = bursts[0]
    return (billboard._matches(burst, {"time": 0, "cycleCount": 1, "probability": 1})
            and _constant(burst["countCurve"]) == burst_count)


def _system(source, seed, rate, max_life, x_size, y_size, burst):
    settings = {**leaves._SETTINGS, "prewarm": True, "randomSeed": seed}
    enabled = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    if enabled != _MODULES or not billboard._matches(source, settings) or _constant(source["startDelay"]) != 0:
        return None
    initial = source["InitialModule"]
    if (not billboard._matches(initial, {"size3D": True, "rotation3D": True, "maxNumParticles": 200,
                                        "randomizeRotationDirection": 0})
            or any(not shine._range(initial[name], first, last) for name, first, last in (
                ("startLifetime", 4, max_life), ("startSize", x_size, .5), ("startSizeY", y_size, y_size),
                ("startSizeZ", .5, .3)))
            or any(_constant(initial[name]) != 0 for name in ("startRotation", "startRotationY", "startSpeed", "gravityModifier"))
            or _constant(initial["startRotationX"]) != leaves._PI_OVER_TWO
            or not _shape(source["ShapeModule"]) or not _emission(source["EmissionModule"], rate, burst)):
        return None
    rotation = source["RotationModule"]
    if (not rotation["separateAxes"] or not shine._range(rotation["curve"], leaves._ROLL, -leaves._ROLL)
            or any(not shine._range(rotation[name], 0, 0) for name in ("x", "y"))):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 2, "tilesX": 4,
                                       "tilesY": 4, "flipU": 0, "flipV": 0}) or not sheet["uvChannelMask"] & 1
            or _constant(sheet["frameOverTime"]) != 0 or _constant(sheet["startFrame"]) != .3125):
        return None
    return leaves._colors(source, "07")


def read(objects, root, fields):
    """Return two linked render profiles and their shared original resources."""
    if len(fields["m_Children"]) != len(_ROLES):
        return None
    common, atlas, mesh, emitters = None, None, None, []
    for ref, (role, name, seed, rate, max_life, x_size, y_size, burst) in zip(fields["m_Children"], _ROLES):
        game = title._transform_child(objects, root, ref)
        row = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"},
                                layer=1) if game is not None else None
        if row is None or row[0]["m_Name"] != name:
            return None
        parts = row[1]
        _, transform = parts["Transform"]
        renderer, render = parts["ParticleSystemRenderer"]
        pose = _authored_trs(transform)
        if (pose != {**title._IDENTITY, "translation": _POSITION} or transform["m_Children"]
                or not billboard._matches(render, _RENDERER)):
            return None
        source = _system(parts["ParticleSystem"][1], seed, rate, max_life, x_size, y_size, burst)
        texture = billboard._material_texture(objects, renderer, render, alpha=role == "alpha")
        geometry = title._local(objects, renderer, render["m_Mesh"], "Mesh")
        if source is None or texture is None or geometry is None:
            return None
        if (common is not None and common != source or atlas is not None and viewer._key(atlas) != viewer._key(texture)
                or mesh is not None and viewer._key(mesh) != viewer._key(geometry)):
            return None
        common, atlas, mesh = source, texture, geometry
        emitters.append({"role": role, "seed": seed & 0xFFFFFFFF, "rate": rate,
                         "material": {**leaves._MATERIAL, "blend": role}})
    start, alpha = common
    return {"profile": "07", "position": _POSITION, "rotation": title._IDENTITY["rotation"],
            "uv": [.25, .25, .25, .25], "startColor": start, "emitters": emitters}, alpha, atlas, mesh
