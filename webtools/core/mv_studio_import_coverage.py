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
coverage is given where the preview decides per clip: CustomControl cues are
counted as drawn when a stage preview descriptor names their (trackId,
eventId).
"""
import re

RENDERED, PARTIAL, NOT_RENDERED, NO_EFFECT = "rendered", "partial", "not rendered", "no effect"
METADATA, STRUCTURE, MUTED, UNCLASSIFIED = "metadata", "structure", "muted", "unclassified"
_REPORTED = (NOT_RENDERED, PARTIAL, UNCLASSIFIED)
_MAX_ITEMS = 24

_SLOT = re.compile(r"/EntryPoint/Live/Members/Member(\d+)(?:/|$)")
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
    "LiveMemberShadowTrack": (PARTIAL, "Only turns the stage's default member shadows off; "
                                       "shadowIndex and scale clips are not applied."),
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


def _prop_tracks(tracks):
    from . import mv_studio_props
    try:
        rows = mv_studio_props.bindings(tracks)
    except (KeyError, TypeError, ValueError):
        return set()
    return {row["track"] for row in rows} | {identity for row in rows for identity in row["activation"]}


_NO_PERFORMER = "No performer is loaded at its member slot."


def _classify(track, project, context):
    """Return [(status, clips, note), ...] for one track."""
    native = track.get("nativeClass") or "UnknownTrack"
    events = [event for event in track.get("events") or () if isinstance(event, dict)]
    status, note = CLASSES.get(native, (UNCLASSIFIED, "MV Studio does not know this track class."))
    if track.get("muted"):
        return [(MUTED, len(events), "Muted in the original timeline.")]
    slot = _slot(track)
    binding = track.get("binding") or ""
    if native == "AnimationTrack":
        if track.get("kind") == "dance" or (slot is not None and binding.endswith("/Model")):
            status, note = RENDERED, "Performer dance from the timeline's choreography pack."
        elif _MAIN_CAMERA.fullmatch(binding):
            status, note = RENDERED, "Main camera."
        elif _SPLIT_CAMERA.fullmatch(binding):
            status, note = (RENDERED, "Split-screen sub camera.") if project.get("splitScreen") else (
                NOT_RENDERED, "Split-screen sub camera without a split-screen layout.")
        elif binding in context["motion"] or track.get("id") in context["props"]:
            status, note = RENDERED, "Stage-node or prop animation."
        else:
            status, note = NOT_RENDERED, "No preview module animates this binding."
    elif native == "ActivationTrack":
        if track.get("id") in context["activations"] or track.get("id") in context["props"]:
            status, note = RENDERED, "Stage-node or prop visibility."
        else:
            status, note = NOT_RENDERED, "No preview module switches this binding."
    elif native == "CustomControlTrack":
        drawn = sum((track.get("id"), event.get("id")) in context["cues"] for event in events)
        rows = []
        if drawn:
            rows.append((RENDERED, drawn, "Effect cues drawn by a stage effect reader."))
        if drawn < len(events):
            rows.append((NOT_RENDERED, len(events) - drawn, "Effect cues no stage effect reader draws."))
        return rows or [(RENDERED, 0, note)]
    if status == RENDERED and slot is not None and slot not in context["performers"]:
        status, note = NOT_RENDERED, _NO_PERFORMER
    return [(status, len(events), note)]


def report(project):
    """Return per (native class, status) counts of tracks and clips, and the reported gaps."""
    tracks = [track for track in project.get("tracks") or () if isinstance(track, dict)]
    motion = project.get("stageMotion") or {}
    context = {
        "motion": set(motion.get("bindings") or ()),
        "activations": set(motion.get("activations") or ()),
        "props": _prop_tracks(tracks),
        "cues": claimed_cues(project),
        "performers": {row.get("position") for row in project.get("performers") or ()
                       if isinstance(row, dict) and (row.get("motion") or row.get("glb"))},
    }
    rows = {}
    for track in tracks:
        for status, clips, note in _classify(track, project, context):
            key = track.get("nativeClass") or "UnknownTrack", status, note
            row = rows.setdefault(key, {"nativeClass": key[0], "status": status, "tracks": 0, "clips": 0, "note": note})
            row["tracks"] += 1
            row["clips"] += clips
            if note == _NO_PERFORMER:
                row["slots"] = sorted({*row.get("slots", ()), _slot(track)})
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


def apply(project):
    """Attach the coverage report to a game import and add its gap warnings."""
    coverage = report(project)
    project["importCoverage"] = coverage
    project["warnings"].extend(warnings(coverage))
    return coverage
