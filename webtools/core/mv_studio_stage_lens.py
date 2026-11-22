"""Read supported prewarmed View-facing particles from stage control prefabs."""

import math
import time

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard
from . import mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from . import mv_studio_stage_dust as dust
from . import mv_studio_stage_glow as glow, mv_studio_stage_particles as particles, mv_studio_stage_title as title
from . import mv_studio_timeline as timeline
from .model_rig import _authored_trs, _trs
from .mv_studio_stage_title_particles import _constant, _float32


SCHEMA = 3
_LEGACY_SCHEMAS = (1, 2, SCHEMA)
_SECTIONS = {"control": "stage_control", "display": "stage_display"}
_STATE = {**billboard._SETTINGS, "looping": True, "prewarm": True, "ringBufferLoopRange": {"x": 0, "y": 1}}
_RENDERER = {**billboard._RENDERER, "m_MaxParticleSize": .5, "m_Flip": billboard._ZERO}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "ShapeModule", "UVModule"}
_SHARED = ("material", "tiles", "maxViewportWidth", "sortMode")
_MAX_CUES = 16
_MAX_ATLASES = 8


def _gradient(source, prefix, channels):
    count = source["m_NumColorKeys" if prefix == "ctime" else "m_NumAlphaKeys"]
    rows = shine._gradient(source, prefix, count, channels) if type(count) is int and 2 <= count <= 8 else None
    return rows if rows and rows[0][0] == 0 and rows[-1][0] == 65535 else None


def _colors(source):
    start = source["InitialModule"]["startColor"]
    life = source["ColorModule"]["gradient"]
    if start["minMaxState"] != 4 or life["minMaxState"] != 3:
        return None
    rgb = _gradient(start["maxGradient"], "ctime", "rgb")
    alpha = _gradient(start["maxGradient"], "atime", "a")
    gradients = [life[key] for key in ("minGradient", "maxGradient")]
    fades = [_gradient(gradient, "atime", "a") for gradient in gradients]
    if (rgb is None or alpha is None or any(row is None for row in fades)
            or any(_gradient(gradient, "ctime", "rgb") != [[0, 1, 1, 1], [65535, 1, 1, 1]] for gradient in gradients)):
        return None
    return {"startColor": {"rgb": rgb, "alpha": alpha}, "alphaKeys": fades}


def _number(value, low, high):
    return type(value) in (int, float) and low <= value <= high


def _system(source):
    active = {name for name, fields in source.items() if name.endswith("Module") and fields.get("enabled")}
    seed, auto = source["randomSeed"], source["autoRandomSeed"]
    if (active != _MODULES or not billboard._matches(source, _STATE) or type(auto) is not bool
            or type(seed) is not int or not -0x80000000 <= seed <= 0xFFFFFFFF or _constant(source["startDelay"]) != 0):
        return None
    cycle = source["lengthInSec"]
    initial = source["InitialModule"]
    lifetime = _constant(initial["startLifetime"])
    size = initial["startSize"]
    sizes = [size["minScalar"], size["scalar"]]
    if (not billboard._matches(initial, {"rotation3D": False, "size3D": False, "randomizeRotationDirection": 0})
            or lifetime != 5 or size["minMaxState"] != 3 or any(not _number(value, 0, 20) or value == 0 for value in sizes)
            or any(_constant(initial[name]) != 0 for name in ("startSpeed", "startRotation", "gravityModifier"))):
        return None
    emission = source["EmissionModule"]
    rate = _constant(emission["rateOverTime"])
    if (emission["m_BurstCount"] or emission["m_Bursts"] or _constant(emission["rateOverDistance"]) != 0
            or not _number(rate, 0, 30) or rate == 0 or initial["maxNumParticles"] < math.ceil(rate * lifetime) + 1):
        return None
    shape = source["ShapeModule"]
    dims = [shape["m_Scale"][axis] for axis in "xyz"]
    arc = shape["arc"]["value"]
    if (not _number(arc, 0, 360) or arc == 0 or any(not _number(value, 0, 100) for value in dims)
            or not leaves._shape(shape, shape_type=2, scale=dims, rotation=(-90, 0, 0), arc_value=arc)):
        return None
    sheet = source["UVModule"]
    if (not billboard._matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 2,
                                       "tilesY": 1, "flipU": 0, "flipV": 0, "randomRow": True})
            or not sheet["uvChannelMask"] & 1 or _constant(sheet["startFrame"]) != 0
            or not shine._range(sheet["frameOverTime"], 0, .75)):
        return None
    colors = _colors(source)
    if colors is None:
        return None
    return {**colors, "rate": rate, "size": sizes, "shapeScale": dims, "arcDegrees": arc, "cycle": cycle,
            "lifetime": lifetime, "autoSeed": auto, "seed": seed & 0xFFFFFFFF}


def _prefab(objects, game, deadline):
    transform_stack = []
    for level in range(6):
        viewer._remaining(deadline)
        fields = game.read_typetree()
        refs = fields["m_Component"]
        kinds = {"Transform"} if len(refs) == 1 else {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
        body = title._components(objects, game, kinds, layer=1)
        if body is None:
            return None
        parts = body[1]
        node, transform = parts["Transform"]
        pose = _authored_trs(transform)
        if (pose["scale"] != title._IDENTITY["scale"]
                or any(abs(axis) > 1000 for axis in pose["translation"])
                or level == 0 and transform["m_Father"] != billboard._NULL):
            return None
        transform_stack.append(transform)
        children = transform["m_Children"]
        if "ParticleSystem" in parts and not children:
            return _emitter(objects, parts, transform_stack)
        if "ParticleSystem" in parts or len(children) != 1:
            return None
        game = title._transform_child(objects, node, children[0])
        if game is None:
            return None
    return None


def _emitter(objects, parts, transforms):
    renderer, fields = parts["ParticleSystemRenderer"]
    source = parts["ParticleSystem"][1]
    if billboard._matches(fields, _RENDERER):
        system = _system(source)
    elif billboard._matches(fields, dust.RENDERER):
        system = dust.read(source, max_viewport_width=fields["m_MaxParticleSize"])
    else:
        return None
    if system is None:
        return None
    atlas = glow.read_additive_atlas(objects, renderer, fields)
    if atlas is None:
        return None
    world = viewer._trs(transforms[0])
    for transform in transforms[1:]:
        world = world @ viewer._trs(transform)
    pose = _trs(world)
    rotation = pose["rotation"]
    row = {**system, "position": pose["translation"], "rotation": rotation, "scale": [1, 1, 1]}
    if system.get("kind") == "boxDust":
        # The native Float32 gravity basis depends on the serialized quaternion.
        diagonal = _float32(.7071068286895752)
        if (any(_authored_trs(node)["rotation"] != title._IDENTITY["rotation"] for node in transforms[:-1])
                or transforms[-1]["m_LocalRotation"] != dict(zip("xyzw", (diagonal, 0, 0, diagonal)))):
            return None
    else:
        # Unity builds local bounds before applying the unit-scale emitter pose.
        center = world @ [0, system["shapeScale"][2] / 2, 0, 1]
        row["sortCenter"] = [_float32(-center[0]), _float32(center[1]), _float32(center[2])]
    return row, atlas


def _section(track):
    if track.get("nativeClass") != "CustomControlTrack" or track.get("binding") or track.get("bindings"):
        return None
    label = track.get("label")
    if not isinstance(label, str):
        return None
    parts = label.split("/", 3)
    if len(parts) != 4 or parts[0].replace(" ", "").lower() != "stageeffect":
        return None
    section = parts[2].replace(" ", "").lower()
    return section if section in _SECTIONS else None


def _source(objects, owner, fields, event):
    overwrite = event["values"].get("overwriteRandomSeed")
    if type(overwrite) is not int or overwrite not in (0, 1):
        return None
    control = particles._source(objects, owner, fields, event, overwrite_seed=bool(overwrite), max_duration=120)
    return control[0] if control is not None else None


def read(objects, mono, tracks, deadline):
    candidates = candidate_cues(tracks)
    if not candidates:
        return None
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    cues, emitters, layouts, rejected, textures, atlas_indices = [], {}, {}, set(), [], {}
    complete = True
    for track in tracks:
        source = controls.get(track["id"])
        section = _section(track)
        if source is None or section is None:
            continue
        owner, fields = source
        try:
            if not (billboard._matches(fields, {"m_Enabled": True, "m_Muted": False})
                    and title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    and title._group(objects, owner, fields, section=section)):
                continue
        except title._UNSUPPORTED:
            complete = False
            continue
        for event in track["events"]:
            if (track["id"], event["id"]) not in candidates:
                continue
            if len(cues) >= _MAX_CUES or time.monotonic() >= deadline:
                complete = False
                break
            identity = None
            try:
                prefab = _source(objects, owner, fields, event)
                if prefab is None:
                    continue
                key = timeline._pointer(prefab, {"m_FileID": 0, "m_PathID": prefab.path_id})
                if key is None:
                    continue
                identity = timeline._id(key)
                if identity in rejected:
                    continue
                if identity not in layouts:
                    layouts[identity] = _prefab(objects, prefab, deadline)
                layout = layouts[identity]
                if layout is None:
                    rejected.add(identity)
                    continue
                if event["duration"] > 60 and layout[0].get("kind") != "boxDust":
                    continue
                if identity not in emitters:
                    emitter = _load_emitter(layout, deadline, atlas_indices, textures)
                    if emitter is None:
                        rejected.add(identity)
                        continue
                    emitters[identity] = {"id": identity, **emitter}
            except title._UNSUPPORTED:
                complete = False
                if identity is not None:
                    rejected.add(identity)
                continue
            cues.append({"trackId": track["id"], "eventId": event["id"], "emitterId": identity,
                         "quality": _SECTIONS[section]})
    if not cues and not complete:
        return None
    return {"schema": SCHEMA, "scanComplete": complete, "textures": textures, "material": glow._MATERIAL,
            "tiles": [2, 1], "maxViewportWidth": .5, "sortMode": 0, "emitters": list(emitters.values()),
            "cues": cues}


def _load_emitter(layout, deadline, indices, textures):
    emitter, (atlas, dimensions) = layout
    key = viewer._key(atlas)
    index = indices.get(key)
    if index is None:
        if len(textures) >= _MAX_ATLASES:
            raise ValueError("The stage lens atlas limit was reached.")
        levels = particles._texture(atlas, deadline, dimensions=dimensions)
        if not levels:
            return None
        textures.append(levels)
        index = indices[key] = len(textures) - 1
    return {**emitter, "texture": index}


def candidate_cues(tracks):
    return {(track["id"], event["id"]) for track in tracks if _section(track) is not None
            for event in track["events"] if event["values"].get("playableClass") == "CustomControlClip"
            and (ptr := event["values"].get("prefabGameObject")) and isinstance(ptr, dict)
            and ptr.get("m_FileID") == 0 and ptr.get("m_PathID") not in (None, 0, "0")}


def known_schema(descriptor):
    return (isinstance(descriptor, dict) and type(descriptor.get("schema")) is int
            and descriptor["schema"] in _LEGACY_SCHEMAS)


def saved_cues(descriptor):
    if not known_schema(descriptor):
        return ()
    cues = descriptor.get("cues")
    if not isinstance(cues, list) or not 1 <= len(cues) <= _MAX_CUES:
        return ()
    if any(not isinstance(cue, dict) or not all(isinstance(cue.get(key), str) for key in ("trackId", "eventId", "emitterId"))
           or cue.get("quality") not in _SECTIONS.values() for cue in cues):
        return ()
    return cues


def restore_saved(saved, original, active, current):
    """Restore supported cues backed by the original data without discarding saved edits."""
    present = {(cue["trackId"], cue["eventId"]) for cue in current}
    candidates = [cue for cue in original["cues"] if (key := (cue["trackId"], cue["eventId"])) in active and key not in present]
    complete = original.get("scanComplete") is True
    if not candidates and saved is None:
        return {**original, "textures": [], "emitters": [], "cues": []} if complete else None
    if saved is not None and any(saved.get(key) != original[key] for key in _SHARED):
        return None
    base = original if saved is None else saved
    textures, emitters = [], []
    if saved is not None:
        if any(not isinstance(saved.get(key), list) for key in ("textures", "emitters")):
            return None
        textures, emitters = list(saved["textures"]), list(saved["emitters"])
    if (len(present) != len(current) or len(textures) > _MAX_ATLASES or len(emitters) > _MAX_CUES
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or type(row.get("texture")) is not int
                   or not 0 <= row["texture"] < len(textures) for row in emitters)):
        return None
    saved_emitters = {row["id"]: row for row in emitters}
    if len(saved_emitters) != len(emitters) or any(cue["emitterId"] not in saved_emitters for cue in current):
        return None
    source = {row["id"]: row for row in original["emitters"]}
    cues = list(current)
    for cue in candidates:
        if len(cues) >= _MAX_CUES:
            break
        identity = cue["emitterId"]
        emitter = source[identity]
        atlas = original["textures"][emitter["texture"]]
        if identity in saved_emitters:
            row = saved_emitters[identity]
            if {**emitter, "texture": row["texture"]} != row or textures[row["texture"]] != atlas:
                continue
        else:
            if len(emitters) >= _MAX_CUES or atlas not in textures and len(textures) >= _MAX_ATLASES:
                continue
            if atlas not in textures:
                textures.append(atlas)
            row = {**emitter, "texture": textures.index(atlas)}
            emitters.append(row)
            saved_emitters[identity] = row
        cues.append(cue)
    added = len(cues) - len(current)
    if added or complete:
        return {**base, "schema": SCHEMA, "scanComplete": complete and added == len(candidates),
                "textures": textures, "emitters": emitters, "cues": cues}
    return None
