"""Import coverage: what MV Studio does with every original timeline track of a game import.

Every native track class is classified explicitly, so a track the preview
does not reproduce is reported instead of being dropped silently. The status
of a track is one of:

- ``rendered``: a preview module plays its clips;
- ``partial``: only part of the original behaviour is reproduced (the note says which);
- ``not rendered``: the original behaviour is missing from the preview;
- ``no effect``: the original client gives it no runtime effect;
- ``metadata``: kept and editable, played from another source;
- ``structure``: a group without clips;
- ``muted``: muted in the timeline, so the original does not play it either;
- ``unclassified``: a class this table does not know yet.

The table follows the preview consumers in web/static (by nativeClass or by
the clip's playableClass) and the Python readers that feed them. Clip-level
coverage is given where the preview decides per clip: every CustomControl
clip has a row in the import's ``controlCoverage`` ledger
(mv_studio_control_prefabs: drawn by a per-effect stage reader, drawn in full
or in part by the particle and prefab rules, drawing nothing in the original,
or not previewed with the reasons; an import without the ledger counts a cue
as drawn when a stage preview descriptor names its (trackId, eventId)), and
stage-node clips when the stage-motion reader accepted them (AnimationTrack
events in stageMotion.mix, ActivationTrack events in stageMotion.activations).

Performer prop tracks (mv_studio_props.bindings) play only through an
attached prop: a ``props`` asset with a preview and an ``attachment``, the
same test the scene uses before it creates MVStudioProps. load_game attaches
one only when the catalog lists a stage props bundle, the timeline has
exactly one prop binding and the prop preview succeeds; in every other case
the prop tracks are reported as not rendered with load_game's reason.

The report reflects the stage readers that actually ran, and some of them
depend on the external texture decoders. 12007 (iOS and Android) draws two
CustomControl cues, StageEffect/Expert/Control/Star_par :0 and :1, through
stageLensFlare only when ELICHIKA_TEXTURE65_BIN is set (ASTCENC_BIN alone
gives none); without it the same import reports all 18 of its cues as not
drawn. Compare importCoverage only between imports made with the same
decoders (ASTCENC_BIN, ELICHIKA_TEXTURE65_BIN) as the baselines.
"""
import re

RENDERED, PARTIAL, NOT_RENDERED, NO_EFFECT = "rendered", "partial", "not rendered", "no effect"
METADATA, STRUCTURE, MUTED, UNCLASSIFIED = "metadata", "structure", "muted", "unclassified"
_REPORTED = (NOT_RENDERED, PARTIAL, UNCLASSIFIED)
_MAX_ITEMS = 24

_SLOT = re.compile(r"/EntryPoint/Live/Members/Member(\d+)(?:/|$)")
_PROP_SLOT = re.compile(r"/EntryPoint/Live/Members/ske_[A-Za-z0-9_]+/Member(\d+)/")
_LABEL_SLOT = re.compile(r"Member(\d+)")
_MAIN_CAMERA = re.compile(r"/EntryPoint/Live/Cameras/MainCamera")
_SPLIT_CAMERA = re.compile(r"/EntryPoint/Live/Cameras/SplitScreenEffect/Cameras/SubCamera[1-4]")

# nativeClass -> (status, what the preview does). None: decided per track or clip below.
CLASSES = {
    "GroupTrack": (STRUCTURE, "Groups tracks."),
    "AnimationTrack": (None, "Dance, camera, stage-node and prop animation by binding."),
    "ActivationTrack": (None, "Stage-node and prop visibility by binding."),
    "CustomControlTrack": (None, "Effect prefab cues drawn by the stage effect readers."),
    "MemberLipSyncTrack": (RENDERED, "Mouth shapes on the performer's face."),
    "MemberEyeTrack": (RENDERED, "Eye shapes on the performer's face."),
    "MemberGazeTrack": (RENDERED, "Performer gaze toward the camera."),
    "MemberCheekTrack": (RENDERED, "Cheek blush on the performer's head."),
    "LiveBloomTrack": (RENDERED, "Bloom post-processing."),
    "LiveDepthOfFieldTrack": (RENDERED, "Depth-of-field focus."),
    "LiveDisplayTrack": (RENDERED, "Stage display screens."),
    "LiveColoringTrack": (RENDERED, "Stage colouring."),
    "LiveSplitScreenTrack": (RENDERED, "Split-screen layouts."),
    "LiveCameraOffsetTrack": (RENDERED, "Camera height offset."),
    "LivePenlightTrack": (RENDERED, "Audience penlights."),
    "LiveBaseLightTrack": (RENDERED, "Base ambient and rim light."),
    "LiveMemberAmbientTrack": (RENDERED, "Performer ambient light."),
    "LiveRimlightTrack": (RENDERED, "Performer rim light."),
    "LiveStageAmbientTrack": (RENDERED, "Stage ambient light."),
    "LiveStageSingleAmbientTrack": (RENDERED, "Stage single ambient light."),
    "LiveStageEmissiveTrack": (RENDERED, "Stage emissive light."),
    "LiveMemberSpotLightAreaTrack": (RENDERED, "Performer spot light area."),
    "LiveMemberSpotLightShaftTrack": (RENDERED, "Performer spot light shaft."),
    "LiveFlareTrack": (RENDERED, "Lens flare."),
    "LiveFlashLightTrack": (RENDERED, "Stage flash lights."),
    "LivePropAmbientTrack": (RENDERED, "Prop ambient light."),
    "LivePropRimlightTrack": (RENDERED, "Prop rim light."),
    "LiveMemberCullerTrack": (RENDERED, "Performer culling."),
    "LiveMemberScalingTrack": (RENDERED, "Performer height scaling."),
    "LiveMemberShadowTrack": (RENDERED, "Member foot shadow scales and the stage's shadow prefab index."),
    "LiveMemberIKTrack": (NOT_RENDERED, "Arm IK (TimelineAssetBindingInfo.ikInfo) is not implemented."),
    "LiveDisplayCameraTrack": (NOT_RENDERED, "The display camera that draws onto the stage screens is not implemented."),
    "LivePropColoringTrack": (NOT_RENDERED, "Prop colouring is not implemented."),
    "LiveCameraCutMarkerTrack": (NO_EFFECT, "Cut markers have no runtime caller in the original client."),
    "ControlTrack": (NOT_RENDERED, "Unity ControlTrack prefab activation is not implemented."),
    "AudioTrack": (METADATA, "The soundtrack plays from the catalog cue."),
    "NaviVoiceTrack": (METADATA, "Navigator voice lines are not part of the MV preview."),
}


def _slot(track):
    found = _SLOT.match(track.get("binding") or "")
    if found:
        return int(found[1])
    for part in str(track.get("label") or "").split("/"):
        found = _LABEL_SLOT.fullmatch(part)
        if found:
            return int(found[1])
    return None


def _reported_slot(track):
    # A performer prop binding names its member slot below the skeleton root.
    found = _PROP_SLOT.match(track.get("binding") or "")
    return int(found[1]) if found else _slot(track)


def claimed_cues(project):
    """(trackId, eventId) pairs that a stage preview descriptor draws."""
    found, stack = set(), [value for key, value in project.items() if key.startswith("stage")]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if isinstance(value.get("trackId"), str) and isinstance(value.get("eventId"), str):
                found.add((value["trackId"], value["eventId"]))
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return found


# Why load_game attached no performer prop (mv_studio.load_game picks one).
PROP_NO_BUNDLE = "The catalog lists no stage props bundle for this stage."
PROP_SEVERAL = "More than one performer prop binding; the preview attaches a single prop only."
PROP_UNAVAILABLE = "The stage props bundle is unavailable."
PROP_PREVIEW_FAILED = "The performer prop preview could not be built from the props bundle."
# load_game's reason when the stage effect has member-shadow prefabs that could not be exported:
# the costume shadows are removed for them (ShadowComponent.Initialize), so no shadow is drawn.
SHADOW_PREFABS_UNAVAILABLE = ("The stage's member shadow prefabs could not be exported, so no performer "
                              "shadow is drawn for the shadow index and scales.")
PROP_NOT_ATTACHED = "No performer prop is attached to this import."
_PROP_NO_CURVE = "Prop clips without a playable native opening curve."


def _attached_props(project):
    """Prop specs the scene animates: a props asset with a preview and an attachment."""
    return [asset["attachment"] for asset in project.get("assets") or ()
            if isinstance(asset, dict) and asset.get("kind") == "props" and asset.get("previewUrl")
            and isinstance(asset.get("attachment"), dict)]


def _prop_tracks(project, tracks, gap):
    """Track id -> the attached prop spec that plays it, or why no prop plays it."""
    from . import mv_studio_props
    try:
        rows = mv_studio_props.bindings(tracks)
    except (KeyError, TypeError, ValueError):
        rows = []
    found = {identity: gap or PROP_NOT_ATTACHED for row in rows for identity in (row["track"], *row["activation"])}
    for spec in _attached_props(project):
        for identity in (spec.get("track"), *(spec.get("activation") or ())):
            if isinstance(identity, str):
                found[identity] = spec
    return found


_NO_PERFORMER = "No performer is loaded at its member slot."
_REJECTED = "Clips the stage-motion reader rejects."
# MVStudioStageMotion drives a stage binding only through exactly one track of each class.
_SHARED = {"AnimationTrack": "More than one AnimationTrack on this stage binding; none is animated.",
           "ActivationTrack": "More than one accepted ActivationTrack on this stage binding; none is switched."}


_LEDGER_STATUSES = {RENDERED, PARTIAL, NOT_RENDERED, NO_EFFECT, MUTED}


def _control_ledger(project):
    """(trackId, eventId) -> (status, note) of every CustomControl clip, from the import's ledger."""
    rows = project.get("controlCoverage")
    found = {}
    for row in rows if isinstance(rows, list) else ():
        if (isinstance(row, dict) and row.get("status") in _LEDGER_STATUSES and isinstance(row.get("note"), str)
                and isinstance(row.get("trackId"), str) and isinstance(row.get("eventId"), str)):
            found[row["trackId"], row["eventId"]] = row["status"], row["note"]
    return found


def _split(total, rendered, rendered_note, missing_note):
    rows = [(RENDERED, rendered, rendered_note)] if rendered or not total else []
    if rendered < total:
        rows.append((NOT_RENDERED, total - rendered, missing_note))
    return rows


def _prop_rows(native, events, prop, context):
    if isinstance(prop, str):
        return [(NOT_RENDERED, len(events), prop)]
    if prop.get("member") not in context["performers"]:
        return [(NOT_RENDERED, len(events), _NO_PERFORMER)]
    if native == "ActivationTrack":
        return [(RENDERED, len(events), "Performer prop visibility.")]
    # MVStudioProps plays a clip only through its opening curve; others keep the default angle.
    curves = prop.get("curves") if isinstance(prop.get("curves"), dict) else {}
    played = sum(event.get("id") in curves for event in events)
    return _split(len(events), played, "Performer prop animation.", _PROP_NO_CURVE)


def _classify(track, project, context):
    """Return [(status, clips, note), ...] for one track."""
    native = track.get("nativeClass") or "UnknownTrack"
    events = [event for event in track.get("events") or () if isinstance(event, dict)]
    status, note = CLASSES.get(native, (UNCLASSIFIED, "MV Studio does not know this track class."))
    if track.get("muted"):
        return [(MUTED, len(events), "Muted in the original timeline.")]
    slot = _slot(track)
    binding = track.get("binding") or ""
    prop = context["props"].get(track.get("id")) if native in ("AnimationTrack", "ActivationTrack") else None
    if prop is not None:
        return _prop_rows(native, events, prop, context)
    if native == "AnimationTrack":
        if track.get("kind") == "dance" or (slot is not None and binding.endswith("/Model")):
            status, note = RENDERED, "Performer dance from the timeline's choreography pack."
        elif _MAIN_CAMERA.fullmatch(binding):
            status, note = RENDERED, "Main camera."
        elif _SPLIT_CAMERA.fullmatch(binding):
            status, note = (RENDERED, "Split-screen sub camera.") if project.get("splitScreen") else (
                NOT_RENDERED, "Split-screen sub camera without a split-screen layout.")
        elif binding in context["motion"]:
            if context["animated"].get(binding, 0) > 1:
                return [(NOT_RENDERED, len(events), _SHARED[native])]
            mixed = sum(event.get("id") in context["mix"] for event in events)
            return _split(len(events), mixed, "Stage-node animation.", _REJECTED)
        else:
            status, note = NOT_RENDERED, "No preview module animates this binding."
    elif native == "ActivationTrack":
        accepted = context["activations"].get(track.get("id"))
        if accepted is None:
            status, note = NOT_RENDERED, "No preview module switches this binding."
        elif context["switched"].get(binding, 0) > 1:
            return [(NOT_RENDERED, len(events), _SHARED[native])]
        else:
            accepted = set(accepted) if isinstance(accepted, (list, tuple, set)) else set()
            return _split(len(events), sum(event.get("id") in accepted for event in events),
                          "Stage-node visibility.", _REJECTED)
    elif native == "CustomControlTrack":
        ledger = context["control"]
        if ledger:
            # One row per clip from mv_studio_control_prefabs: what the stage readers,
            # the particle rule and the prefab rule draw of the clip's clone, or why nothing.
            grouped = {}
            for event in events:
                status, reason = ledger.get((track.get("id"), event.get("id")),
                                            (NOT_RENDERED, "Effect cues no stage effect reader draws."))
                grouped[status, reason] = grouped.get((status, reason), 0) + 1
            return [(status, count, reason) for (status, reason), count in grouped.items()] or [(RENDERED, 0, note)]
        drawn = sum((track.get("id"), event.get("id")) in context["cues"] for event in events)
        rows = []
        if drawn:
            rows.append((RENDERED, drawn, "Effect cues drawn by a stage effect reader."))
        if drawn < len(events):
            rows.append((NOT_RENDERED, len(events) - drawn, "Effect cues no stage effect reader draws."))
        return rows or [(RENDERED, 0, note)]
    if native == "LiveMemberShadowTrack" and context.get("shadow"):
        status, note = NOT_RENDERED, context["shadow"]
    if status == RENDERED and slot is not None and slot not in context["performers"]:
        status, note = NOT_RENDERED, _NO_PERFORMER
    return [(status, len(events), note)]


def report(project, prop_gap=None, shadow_gap=None):
    """Return per (native class, status) counts of tracks and clips, and the reported gaps.

    ``prop_gap`` is load_game's reason for attaching no performer prop, ``shadow_gap``
    its reason when the stage's member-shadow prefabs are not drawn.
    """
    tracks = [track for track in project.get("tracks") or () if isinstance(track, dict)]
    motion = project.get("stageMotion") or {}
    activations = motion.get("activations") if isinstance(motion.get("activations"), dict) else {}
    animated, switched = {}, {}
    for track in tracks:
        # The stage-motion consumer counts every track on the binding, muted or not.
        if track.get("nativeClass") == "AnimationTrack":
            animated[track.get("binding")] = animated.get(track.get("binding"), 0) + 1
        elif track.get("nativeClass") == "ActivationTrack" and track.get("id") in activations:
            switched[track.get("binding")] = switched.get(track.get("binding"), 0) + 1
    context = {
        "motion": set(motion.get("bindings") or ()),
        "mix": motion.get("mix") if isinstance(motion.get("mix"), dict) else {},
        "activations": activations,
        "animated": animated,
        "switched": switched,
        "props": _prop_tracks(project, tracks, prop_gap),
        "cues": claimed_cues(project),
        "control": _control_ledger(project),
        "performers": {row.get("position") for row in project.get("performers") or ()
                       if isinstance(row, dict) and (row.get("motion") or row.get("glb"))},
        "shadow": shadow_gap,
    }
    rows = {}
    for track in tracks:
        for status, clips, note in _classify(track, project, context):
            key = track.get("nativeClass") or "UnknownTrack", status, note
            row = rows.setdefault(key, {"nativeClass": key[0], "status": status, "tracks": 0, "clips": 0, "note": note})
            row["tracks"] += 1
            row["clips"] += clips
            if note == _NO_PERFORMER:
                row["slots"] = sorted({*row.get("slots", ()), _reported_slot(track)} - {None})
    ordered = sorted(rows.values(), key=lambda row: (row["nativeClass"], row["status"], row["note"]))
    return {"tracks": ordered, "gaps": [row for row in ordered if row["status"] in _REPORTED and row["clips"]]}


def _item(row):
    clips = f"{row['clips']} clip{'' if row['clips'] == 1 else 's'}"
    slots = row.get("slots")
    where = f" ({', '.join(f'Member{slot}' for slot in slots)})" if slots else ""
    return f"{row['nativeClass']} x{row['tracks']} ({clips}: {row['note'].rstrip('.')}{where})"


def warnings(coverage):
    """One project warning per gap status, naming each native class with clips."""
    notes = []
    for status, lead in ((NOT_RENDERED, "Original timeline tracks MV Studio does not reproduce"),
                         (PARTIAL, "Original timeline tracks MV Studio reproduces only in part"),
                         (UNCLASSIFIED, "Original timeline track classes MV Studio does not know")):
        items = [_item(row) for row in coverage["gaps"] if row["status"] == status]
        if items:
            more = f"; {len(items) - _MAX_ITEMS} more" if len(items) > _MAX_ITEMS else ""
            notes.append(f"{lead}: {'; '.join(items[:_MAX_ITEMS])}{more}.")
    return notes


def apply(project, prop_gap=None, shadow_gap=None):
    """Attach the coverage report to a game import and add its gap warnings.

    Run it once ``project["assets"]`` is final, so an attached performer prop is seen.
    """
    coverage = report(project, prop_gap, shadow_gap)
    project["importCoverage"] = coverage
    project["warnings"].extend(warnings(coverage))
    return coverage
