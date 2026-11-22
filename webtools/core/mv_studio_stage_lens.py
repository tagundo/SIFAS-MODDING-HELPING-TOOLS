"""Read supported prewarmed View-facing particles from stage control prefabs."""

import math
import time

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard
from . import mv_studio_butterfly_shine as shine, mv_studio_leaves as leaves
from . import mv_studio_stage_burst as burst, mv_studio_stage_dust as dust
from . import mv_studio_stage_glow as glow, mv_studio_stage_particles as particles, mv_studio_stage_title as title
from . import mv_studio_timeline as timeline
from .model_rig import _authored_trs, _trs
from .mv_studio_stage_title_particles import _constant, _float32


SCHEMA = 4
_LEGACY_SCHEMAS = (1, 2, 3, SCHEMA)
_SECTIONS = {"control": "stage_control", "display": "stage_display"}
_STATE = {**billboard._SETTINGS, "looping": True, "prewarm": True, "ringBufferLoopRange": {"x": 0, "y": 1}}
_RENDERER = {**billboard._RENDERER, "m_MaxParticleSize": .5, "m_Flip": billboard._ZERO}
_MODULES = {"ColorModule", "EmissionModule", "InitialModule", "ShapeModule", "UVModule"}
_SHARED = ("material", "tiles", "maxViewportWidth", "sortMode")
_MAX_CUES = 16
_MAX_EMITTERS = 16
_MAX_GROUP = 8
_MAX_INSTANCES = 64
_MAX_NODES = 64
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
    layer = game.read_typetree()["m_Layer"]
    if layer not in (1, 20):
        return None
    stack = [(game, ())]
    layouts, visited = [], set()
    while stack:
        viewer._remaining(deadline)
        game, ancestors = stack.pop()
        key = viewer._key(game)
        if key in visited:
            return None
        if len(ancestors) >= 6 or len(visited) >= _MAX_NODES:
            raise ValueError("The stage billboard prefab tree limit was reached.")
        visited.add(key)
        component_count = len(game.read_typetree()["m_Component"])
        kinds = {"Transform"} if component_count == 1 else {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
        body = title._components(objects, game, kinds, layer=layer)
        if body is None:
            return None
        parts = body[1]
        node, transform = parts["Transform"]
        pose = _authored_trs(transform)
        if (pose["scale"] != title._IDENTITY["scale"]
                or any(abs(axis) > 1000 for axis in pose["translation"])
                or not ancestors and transform["m_Father"] != billboard._NULL):
            return None
        transforms = (*ancestors, transform)
        children = transform["m_Children"]
        if "ParticleSystem" in parts:
            if children:
                return None
            if len(layouts) >= _MAX_GROUP:
                raise ValueError("The stage billboard emitter count limit was reached.")
            layout = _emitter(objects, parts, transforms, layer)
            if layout is None:
                return None
            layouts.append((parts["ParticleSystem"][0].path_id, layout))
        else:
            if not children:
                return None
            if len(children) > _MAX_GROUP:
                raise ValueError("The stage billboard prefab child count limit was reached.")
            for ref in reversed(children):
                child = title._transform_child(objects, node, ref)
                if child is None:
                    return None
                stack.append((child, transforms))
    return layouts or None


def _emitter(objects, parts, transforms, layer):
    renderer, fields = parts["ParticleSystemRenderer"]
    source = parts["ParticleSystem"][1]
    if layer == 1 and billboard._matches(fields, _RENDERER):
        system = _system(source)
    elif layer == 1 and billboard._matches(fields, dust.RENDERER):
        system = dust.read(source, max_viewport_width=fields["m_MaxParticleSize"])
    else:
        system = burst.read(source, fields, layer)
    if system is None:
        return None
    atlas = glow.read_particle_atlas(objects, renderer, fields, blend=system.get("blend", "add"),
                                    max_dimension=512 if layer == 20 else 256)
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
    elif system.get("kind") == "stationaryBurst":
        row["sortCenter"] = pose["translation"]
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
    complete, instances = True, 0
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
                group = layouts[identity]
                if group is None:
                    rejected.add(identity)
                    continue
                if event["duration"] > 60 and any(layout[0].get("kind") != "boxDust" for _, layout in group):
                    continue
                if instances + len(group) > _MAX_INSTANCES:
                    complete = False
                    continue
                ids = [identity] if len(group) == 1 else [f"{identity}@{slot}" for slot, _ in group]
                additional = [(member, layout) for member, (_, layout) in zip(ids, group) if member not in emitters]
                if len(emitters) + len(additional) > _MAX_EMITTERS:
                    complete = False
                    continue
                if additional:
                    # A cue is admitted only if every member and its atlas can be loaded.
                    trial_textures, trial_indices = list(textures), dict(atlas_indices)
                    imported = {member: _load_emitter(layout, deadline, trial_indices, trial_textures)
                                for member, layout in additional}
                    if any(row is None for row in imported.values()):
                        rejected.add(identity)
                        complete = False
                        continue
                    textures, atlas_indices = trial_textures, trial_indices
                    emitters.update({member: {"id": member, **row} for member, row in imported.items()})
            except title._UNSUPPORTED:
                complete = False
                if identity is not None:
                    rejected.add(identity)
                continue
            members = {"emitterId": ids[0]} if len(ids) == 1 else {"emitterIds": ids}
            cues.append({"trackId": track["id"], "eventId": event["id"], **members, "quality": _SECTIONS[section]})
            instances += len(ids)
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


def _emitter_ids(cue):
    def usable(value):
        return isinstance(value, str) and 0 < len(value) <= 128

    if "emitterIds" in cue:
        ids = cue["emitterIds"]
        if ("emitterId" in cue or not isinstance(ids, list) or not 2 <= len(ids) <= _MAX_GROUP
                or not all(map(usable, ids)) or len(set(ids)) != len(ids)):
            return ()
        return tuple(ids)
    identity = cue.get("emitterId")
    return (identity,) if usable(identity) else ()


def saved_cues(descriptor):
    if not known_schema(descriptor):
        return ()
    cues = descriptor.get("cues")
    if not isinstance(cues, list) or not 1 <= len(cues) <= _MAX_CUES:
        return ()
    if any(not isinstance(cue, dict) or not all(isinstance(cue.get(key), str) for key in ("trackId", "eventId"))
           or cue.get("quality") not in _SECTIONS.values()
           or (descriptor["schema"] < 4 and "emitterIds" in cue) or not _emitter_ids(cue) for cue in cues):
        return ()
    return cues if sum(len(_emitter_ids(cue)) for cue in cues) <= _MAX_INSTANCES else ()


def restore_saved(saved, original, active, current):
    """Restore complete source-backed cue groups without discarding saved edits."""
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
    if (len(present) != len(current) or len(textures) > _MAX_ATLASES or len(emitters) > _MAX_EMITTERS
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or type(row.get("texture")) is not int
                   or not 0 <= row["texture"] < len(textures) for row in emitters)):
        return None
    saved_emitters = {row["id"]: row for row in emitters}
    if len(saved_emitters) != len(emitters) or any(member not in saved_emitters
                                                  for cue in current for member in _emitter_ids(cue)):
        return None
    source = {row["id"]: row for row in original["emitters"]}
    cues = list(current)
    instances = sum(len(_emitter_ids(cue)) for cue in current)
    for cue in candidates:
        if len(cues) >= _MAX_CUES:
            break
        members = _emitter_ids(cue)
        if instances + len(members) > _MAX_INSTANCES:
            continue
        trial_textures, added_emitters = list(textures), {}
        for identity in members:
            emitter = source[identity]
            atlas = original["textures"][emitter["texture"]]
            if identity in saved_emitters:
                row = saved_emitters[identity]
                if {**emitter, "texture": row["texture"]} != row or textures[row["texture"]] != atlas:
                    break
            else:
                if len(saved_emitters) + len(added_emitters) >= _MAX_EMITTERS:
                    break
                if atlas not in trial_textures:
                    if len(trial_textures) >= _MAX_ATLASES:
                        break
                    trial_textures.append(atlas)
                added_emitters[identity] = {**emitter, "texture": trial_textures.index(atlas)}
        else:
            textures = trial_textures
            saved_emitters.update(added_emitters)
            cues.append(cue)
            instances += len(members)
    added = len(cues) - len(current)
    if added or complete:
        return {**base, "schema": SCHEMA, "scanComplete": complete and added == len(candidates),
                "textures": textures, "emitters": list(saved_emitters.values()), "cues": cues}
    return None
