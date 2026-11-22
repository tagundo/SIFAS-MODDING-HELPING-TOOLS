"""Resolve supported native stage-control particle prefabs for MV preview."""

import base64
from collections import Counter
import math

from . import decode, model_viewer as viewer, mv_studio_stage_title as title
from . import mv_studio_stage_motion as motion, mv_studio_timeline as timeline
from .model_materials import _original_mips


SCHEMA = 4
_MAX_EMITTERS = 12


def _coverage(descriptor):
    try:
        textures = [tuple(level["png"] for level in chain) for chain in descriptor["textures"]]
        templates = [Counter((textures[emitter["texture"]], emitter["birth"]) for emitter in template)
                     for template in descriptor["templates"]]
        return {(cue["trackId"], cue["eventId"]): templates[cue["template"]] for cue in descriptor["cues"]}
    except (KeyError, IndexError, TypeError):
        return {}


def preserves(saved, restored):
    # A local decoder can rebuild only part of an effect. Compare by authored
    # cue and embedded mip data because a successful rebuild can reindex both.
    required = _coverage(saved)
    if not required:
        return True
    rebuilt = _coverage(restored)
    return all(cue in rebuilt and emitters <= rebuilt[cue] for cue, emitters in required.items())


def _source(objects, owner, tree, event, *, overwrite_seed=False):
    values = event["values"]
    if (values.get("playableClass") != "CustomControlClip" or values.get("timeScale") != 1
            or not 0 < event["duration"] <= 60
            or any(values.get(field) for field in ("preExtrapolationMode", "postExtrapolationMode"))
            or any(values.get(field, 0) > 0 for field in ("easeIn", "easeOut", "blendIn", "blendOut"))):
        return None
    clip = tree["m_Clips"][int(event["id"].rsplit(":", 1)[1])]
    asset = title._local(objects, owner, clip.get("m_Asset"), "MonoBehaviour")
    if asset is None or (clip.get("m_AnimationCurves") or {}).get("m_PathID"):
        return None
    fields = asset.read_typetree()
    offset = fields.get("offset")
    seed = fields.get("particleRandomSeed")
    if (not title._declared(objects, asset, fields, (*title._NAMESPACE, "CustomControlClip"))
            or not fields.get("m_Enabled") or fields.get("weight") != 1
            or fields.get("overwriteRandomSeed") != int(overwrite_seed)
            or type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF
            or not isinstance(offset, dict)
            or any(type(offset.get(axis)) not in (int, float) or not math.isfinite(offset[axis])
                   or abs(offset[axis]) > 1000 for axis in "xyz")):
        return None
    # PrefabControl activates the clone and lets its ParticleSystems start on
    # awake. The graph's clipIn is not an input to their simulation clock.
    prefab = title._local(objects, asset, fields.get("prefabGameObject"), "GameObject")
    return (prefab, seed) if prefab is not None else None


def _texture(reader, deadline, *, sizes=(256, 512)):
    base = title._texture(reader, deadline, sizes=sizes)
    if base is None:
        return None
    levels = [base]
    for proxy in _original_mips(reader, reader.read()):
        native = proxy.read()
        with decode._android_image(native, deadline, stage=True) as image:
            png = viewer._png_texture(image, deadline)
        if len(png) > title._MAX_IMAGE_BYTES:
            return None
        levels.append({"png": base64.b64encode(png).decode("ascii"),
                       "width": native.m_Width, "height": native.m_Height})
    return levels if len(levels) == base["width"].bit_length() else None


def read(objects, mono, tracks, deadline):
    from . import mv_studio_finale_flashes, mv_studio_foot_particles, mv_studio_umbrella_particles

    readers = (mv_studio_finale_flashes.read, mv_studio_umbrella_particles.read, mv_studio_foot_particles.read)
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    textures, templates, cues = [], [], []
    texture_ids, prefab_ids = {}, {}
    for track in tracks:
        track_source = controls.get(track["id"])
        if (track_source is None or track.get("binding") or track.get("bindings")
                or motion._quality(track["label"]) != "stage_control"):
            continue
        owner, fields = track_source
        try:
            if (not fields.get("m_Enabled") or not title._declared(
                    objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields, "control")):
                continue
        except title._UNSUPPORTED:
            continue
        for event in track["events"]:
            viewer._remaining(deadline)
            try:
                source = _source(objects, owner, fields, event)
                if source is None:
                    continue
                prefab, seed = source
                key = (viewer._key(prefab), seed)
                if key not in prefab_ids:
                    if len(templates) >= 8:
                        continue
                    prefab_ids[key] = None
                    authored = None
                    for reader in readers:
                        try:
                            authored = reader(objects, prefab, deadline, clip_seed=seed)
                        except title._UNSUPPORTED:
                            continue
                        if authored:
                            break
                    if not authored or len(authored) > _MAX_EMITTERS:
                        continue
                    emitters = []
                    for emitter, reader in authored:
                        texture = viewer._key(reader)
                        if texture not in texture_ids:
                            texture_ids[texture] = None
                            if len(textures) < 4:
                                try:
                                    levels = _texture(reader, deadline)
                                except title._UNSUPPORTED:
                                    levels = None
                                if levels is not None:
                                    texture_ids[texture] = len(textures)
                                    textures.append(levels)
                        index = texture_ids[texture]
                        if index is not None:
                            emitters.append({**emitter, "texture": index})
                    if emitters:
                        prefab_ids[key] = len(templates)
                        templates.append(emitters)
                template = prefab_ids[key]
                if template is not None:
                    if len(cues) >= 32:
                        return None
                    cues.append({"trackId": track["id"], "eventId": event["id"], "template": template})
            except title._UNSUPPORTED:
                continue
    return {"schema": SCHEMA, "textures": textures, "templates": templates, "cues": cues} if cues else None
