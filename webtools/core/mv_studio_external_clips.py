"""Resolve timeline AnimationClip references that live in the timeline's dependency packs.

An original MV timeline does not carry its dancers' AnimationClips. Each
member's AnimationPlayableAsset points with ``m_Clip = {m_FileID > 0, m_PathID}``
at a clip in a choreography bundle. Unity resolves that PPtr through the
referencing SerializedFile's ``externals[m_FileID - 1]`` (a CAB name) and the
PathID inside the loaded bundle with that CAB. The catalog lists the same
bundles as the timeline's ``live_timeline_dependency`` rows (they match the
timeline AssetBundle's ``m_Dependencies``). Example, 12035: track
MemberMotion/Member1 -> playable 8043450867467947168 -> m_Clip {2,
6826311605069373343} -> externals[1] = CAB-a1600f34dce5a67c3abab6068c0996fe,
the only AnimationClip of the choreography pack ``ch0212_so2035.fbx.unity3d``.

This module applies that rule to the parsed track list after the catalog
dependencies are read. Only the timeline's catalog choreography packs whose
CAB is in the timeline's serialized dependency closure can supply a clip, and
only by exact (CAB, PathID). Neither clip display names nor file names
identify a clip. The resolved names are kept in a top-level preview map keyed
by event id; event values stay byte-for-byte what native export expects.
"""
import json
import struct

from . import game_motion_selection as selection
from .mv_studio_timeline import EXTERNAL_CLIP_WARNING

_MAX_NOTES = 32
# A corrupt serialized file can fail inside UnityPy with any of these.
_ERRORS = (ValueError, OSError, KeyError, TypeError, EOFError, IndexError, OverflowError, struct.error)


class SharedReads:
    """Read each catalog section once, also when a resolver needs it before its asset row exists."""

    def __init__(self, read):
        self._read = read
        self._held = {}

    @staticmethod
    def _identity(descriptor):
        return json.dumps(descriptor, sort_keys=True, default=str)

    def prefetch(self, descriptors):
        for descriptor in descriptors:
            if not descriptor:
                continue
            identity = self._identity(descriptor)
            if identity in self._held:
                continue
            try:
                self._held[identity] = (self._read(descriptor), None)
            except (ValueError, OSError) as error:
                self._held[identity] = (None, error)

    def peek(self, descriptor):
        raw, _ = self._held.get(self._identity(descriptor), (None, None))
        return raw

    def __call__(self, descriptor):
        held = self._held.pop(self._identity(descriptor), None)
        if held is None:
            return self._read(descriptor)
        raw, error = held
        if error is not None:
            raise error
        return raw


def _key(identity):
    if not isinstance(identity, str) or ":" not in identity:
        return None
    cab, path_id = identity.rsplit(":", 1)
    try:
        return cab, int(path_id)
    except ValueError:
        return None


def references(tracks):
    """Return (track, event, key) for clips whose AnimationClip is not inside the timeline bundle.

    These are exactly the events for which the track parser could not name
    the clip: an AnimationPlayableAsset with a resolvable m_Clip pointer and
    no local AnimationClip behind it.
    """
    rows = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        for event in track.get("events") or ():
            values = event.get("values") if isinstance(event, dict) else None
            if (not isinstance(values, dict) or values.get("playableClass") != "AnimationPlayableAsset"
                    or "animationName" in values):
                continue
            key = _key(values.get("animation"))
            if key is not None:
                rows.append((track, event, key))
    return rows


def _source(raw, label, deadline):
    import UnityPy
    from .model_viewer import MAX_SOURCE_BYTES, _bounded_bundle, _preflight_bundle

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES or not raw.startswith(b"UnityFS\0"):
        raise ValueError(f"'{label}' is not a UnityFS bundle.")
    _, layout = _preflight_bundle(raw, _with_layout=True)
    env = UnityPy.load(_bounded_bundle(raw, layout, deadline))
    objects = list(env.objects)
    if len(objects) > selection.MAX_OBJECTS:
        raise ValueError(f"'{label}' contains too many objects.")
    return {"label": label, "env": env, "objects": objects, "scripts": {}}


def resolve(tracks, timeline_raw, dependencies, deadline):
    """Resolve external clip references against the timeline's catalog dependency packs.

    ``dependencies`` is ``[(label, raw bytes or None), ...]`` for the
    timeline's catalog choreography packs; None marks a pack that could not
    be read. Returns None when no clip needs a dependency, else
    ``{"clips": {event id: {...}}, "warnings": [...]}``.
    """
    refs = references(tracks)
    if not refs:
        return None
    from .model_viewer import _remaining

    timeline = _source(timeline_raw, "timeline", deadline)
    loaded, unavailable = [], []
    for label, raw in dependencies:
        _remaining(deadline)
        if raw is None:
            unavailable.append(label)
            continue
        try:
            loaded.append(_source(raw, label, deadline))
        except _ERRORS:
            unavailable.append(label)
    conflict = None
    try:
        objects, owners = selection.dependency_objects(timeline, loaded)
    except ValueError as error:
        objects, owners, conflict = {}, {}, str(error)
    reachable = selection.dependency_closure(timeline, loaded)
    unreferenced = [source["label"] for source in loaded
                    if not {selection._cab(item.name) for item in selection._serialized_files(source)} & reachable]
    present = {key[0] for key in objects}
    clips, notes = {}, []
    for track, event, key in refs:
        identity = f"{key[0]}:{key[1]}"
        where = f"Track '{track.get('label', '')}' clip '{event.get('label', '')}' plays AnimationClip {identity}"
        obj = objects.get(key)
        if obj is not None and obj.type.name == "AnimationClip":
            clips[event["id"]] = {"track": track.get("id"), "animation": identity,
                                  "animationName": str(obj.peek_name() or "")[:240],
                                  "dependency": owners[key]["label"]}
        elif conflict is not None:
            notes.append(f"{where}, but its dependency packs are inconsistent: {conflict}")
        elif obj is not None:
            notes.append(f"{where}, but that object is a {obj.type.name}, not an AnimationClip.")
        elif key[0] in present:
            notes.append(f"{where}, but the loaded dependency {key[0]} has no object {key[1]}.")
        else:
            missing = f" Unavailable dependency packs: {', '.join(unavailable)}." if unavailable else ""
            if unreferenced:
                missing += f" Loaded packs this timeline does not reference: {', '.join(unreferenced)}."
            notes.append(f"{where}, but no loaded dependency of this timeline provides {key[0]}.{missing}")
    if len(notes) > _MAX_NOTES:
        notes = notes[:_MAX_NOTES] + [f"{len(notes) - _MAX_NOTES} more unresolved animation clip references."]
    return {"clips": clips, "warnings": notes}


def _label(descriptor):
    return str(descriptor.get("asset", descriptor.get("pack_name", "")) or "dependency")


def apply(project, timeline_raw, descriptors, reads, deadline, cache=None, reused=None):
    """Name external dance clips of a game import and replace the generic warning.

    Returns ``{event id: AnimationClip name}`` for the resolved clips. The
    project gains ``companionClips`` (event id -> identity) when any resolve.
    A pack that is genuinely missing keeps a warning naming the track, the
    clip and its exact CAB:PathID. ``cache`` (mv_studio_import_cache) keeps a
    receipt of the resolution keyed by the timeline and every pack's bytes;
    ``reused`` (a list) receives whether it was used.
    """
    if not references(project.get("tracks") or ()):
        return {}
    descriptors = [item for item in descriptors or () if isinstance(item, dict)]
    reads.prefetch(descriptors)
    dependencies = [(_label(item), reads.peek(item)) for item in descriptors]
    receipt = result = None
    if cache is not None:
        from .mv_studio_import_cache import digest
        receipt = cache.key("clips", digest(timeline_raw),
                            [[label, None if raw is None else digest(raw)] for label, raw in dependencies])
        result = cache.get(receipt)
    if reused is not None:
        reused.append(result is not None)
    if result is None:
        try:
            result = resolve(project["tracks"], timeline_raw, dependencies, deadline)
        except Exception:
            # Clip names are advisory. An import that does not otherwise parse
            # these packs (an actor-cache hit) must not fail on them: keep the
            # generic warning and cast as before.
            return {}
        if result is None:
            return {}
        if receipt is not None:
            cache.put(receipt, result)
    warnings = project["warnings"]
    if EXTERNAL_CLIP_WARNING in warnings:
        index = warnings.index(EXTERNAL_CLIP_WARNING)
        warnings[index:index + 1] = result["warnings"]
    else:
        warnings.extend(result["warnings"])
    if result["clips"]:
        project["companionClips"] = result["clips"]
    return {event: row["animationName"] for event, row in result["clips"].items()}
