"""Read the four authored Monster Girls Expert sparks_roop emitters."""

from . import model_viewer as viewer
from . import mv_studio_sparks_b as sparks, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_display_lights import _enabled
from .mv_studio_stage_title_particles import _constant, _constant_range, _float32


_PREFAB = "fx_par_so2056_03"
_TRACK = "StageEffect/Expert/Control/sparks_roop"
_LAYER = 1
_ALIAS = "speedBackCenterStars"
_PROFILE = "late_kirakira"
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "SizeModule",
            "ColorModule", "UVModule", "VelocityModule"}
_NAMES = ("sparks_R1", "sparks_R2", "sparks_L1", "sparks_L2")


def _state(source, name, deadline):
    delay = _constant_range(source["startDelay"], 0, 1)
    if (_enabled(source) != _MODULES or not source["playOnAwake"] or not source["autoRandomSeed"]
            or source["randomSeed"] != 0 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or source["lengthInSec"] != 13 or delay != (0, 0) or source["moveWithCustomTransform"]["m_PathID"]
            or any(source[key] for key in ("looping", "prewarm", "moveWithTransform", "useUnscaledTime",
                                           "cullingMode", "ringBufferMode", "stopAction"))):
        return None
    emission, initial = source["EmissionModule"], source["InitialModule"]
    rate = _constant(emission["rateOverTime"])
    side = name.endswith("2")
    if (rate != (200 if side else 100) or _constant(emission["rateOverDistance"]) != 0
            or emission["m_BurstCount"] or emission["m_Bursts"]):
        return None
    lifetime = _constant_range(initial["startLifetime"], 0, 4)
    size = _constant_range(initial["startSize"], 0, 1)
    roll = _constant_range(initial["startRotation"], 0, 7)
    gravity, speed = _constant(initial["gravityModifier"]), _constant(initial["startSpeed"])
    if (lifetime != (3, 2) or size != (_float32(.2), _float32(.3)) or roll != (0, _float32(6.283185))
            or (gravity, speed, initial["maxNumParticles"]) != (_float32(.1), 0, 1000)
            or initial["size3D"] or initial["rotation3D"] or initial["randomizeRotationDirection"]):
        return None
    scale = [4, .5, 1] if side else [2, .5, .5]
    shape = sparks._sphere_shape(source["ShapeModule"], (1.5, 180, 0, scale, [90, 0, 0]))
    parts = (sparks._size(source["SizeModule"], _PROFILE, deadline),
             sparks._motion(source, _PROFILE, deadline), sparks._colors(source, 2, 3))
    uv = sparks._sheet(source["UVModule"], _PROFILE, deadline)
    if shape is None or uv is None or any(part is None for part in parts):
        return None
    sizing, motion, color = parts
    return {"name": name, "seed": None, "duration": source["lengthInSec"], "rate": rate,
            "delay": delay, "lifetime": lifetime, "size": size, "speed": [speed, speed], "roll": roll, "gravity": gravity,
            "shape": shape, "capacity": initial["maxNumParticles"], "bursts": [], "uv": uv, **sizing, **motion, **color}


def _leaf(objects, game, name, deadline):
    typed = title._components(objects, game, _COMPONENTS, layer=_LAYER)
    if typed is None or typed[0]["m_Name"] != name:
        return None
    parts = typed[1]
    _, transform = parts["Transform"]
    pose = _authored_trs(transform)
    rotation = pose["rotation"]
    if (transform["m_Children"] or pose["scale"] != title._IDENTITY["scale"]
            or rotation[0] or rotation[2] or any(abs(value) > 100 for value in pose["translation"])):
        return None
    state = _state(parts["ParticleSystem"][1], name, deadline)
    surface = sparks._surface(objects, *parts["ParticleSystemRenderer"], _PROFILE) if state is not None else None
    if surface is None:
        return None
    renderer, atlas = surface
    return {**state, **renderer, "position": pose["translation"], "rotation": rotation}, atlas


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
        result = _leaf(objects, child, name, deadline) if child is not None else None
        if result is None or (atlas is not None and viewer._key(result[1]) != viewer._key(atlas)):
            return None
        row, atlas = result
        rows.append(row)
    return rows, atlas


def read(objects, mono, tracks, deadline, *, atlas_refs=None):
    """Return the authentic auto-seeded cluster for the single native Control cue."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    accepted = None
    for track in tracks:
        control = controls.get(track["id"])
        if control is None or track["label"] != _TRACK or track.get("binding") or track.get("bindings"):
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
                effect = _prefab(objects, original[0], deadline) if original is not None else None
                if effect is not None:
                    if accepted is not None:
                        return None
                    accepted = {"trackId": track["id"], "eventId": event["id"]}, effect
        except title._UNSUPPORTED:
            continue
    if accepted is None:
        return None
    cue, (emitters, reader) = accepted
    if atlas_refs is not None and atlas_refs.get(viewer._key(reader)) == _ALIAS:
        atlas = _ALIAS
    else:
        try:
            atlas = particles._texture(reader, deadline)
        except title._UNSUPPORTED:
            return None
        if not atlas or len(atlas) != 10:
            return None
    return {"textures": [atlas], "emitters": emitters, "cues": [cue]}
