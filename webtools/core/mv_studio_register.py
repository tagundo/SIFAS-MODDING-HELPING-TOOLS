"""MV-only song registration ("MV 전용 곡으로 등록"): plan, bake, audio, jacket and the store jobs.

A registered song is a stock base MV (stage, choreography, props, members) plus the
project's edits that fit inside the base timeline's existing slots, a title, an optional
credit, jacket and audio. The Elichika store (``mv_studio_live``) writes the catalogs;
this module decides what to send it.

- ``plan()`` writes nothing and bakes nothing. It resolves the base MV, reports which
  original timeline each platform would use, counts the edits that reach the game, lists
  the edits that do not and reports the audio and jacket options.
- ``run_register()`` and ``run_remove()`` are job bodies. The slow work (baking both
  platforms from the posted project, encoding audio, preparing the jacket) runs while the
  game server keeps running; only the store call runs with the server stopped (when the
  app manages it) and under ``database_maintenance.guard``.

Texture rule (CLAUDE.md): a 400x400 PNG or JPEG jacket is stored byte for byte; any other
square is resized once to 400x400; a non-square image needs a square crop box, cut at exact
pixels and resized only when the box is not 400 px. Nothing is squished or padded.
"""
from collections import OrderedDict
from contextlib import ExitStack, closing
import base64
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time

from . import game_models as game
from . import mv_studio, mv_studio_game, mv_studio_timeline


PLATFORMS = ("android", "ios")
REGIONS = ("gl", "jp")
SAMPLE_RATE = 44100
MAX_TITLE = 160
MAX_CREDIT = 200
JACKET_SIZE = 400
JACKET_BYTES = 2 * 1024 * 1024
JACKET_SOURCE_BYTES = 32 * 1024 * 1024
JACKET_SOURCE_PIXELS = 64 * 1024 * 1024
PCM_BYTES = 96 * 1024 * 1024
PREVIEW_IMAGE = 512
# Part of every fingerprint: a new bake or encode rule makes the next update rebuild that part.
FINGERPRINT_VERSION = "mv-studio-register-1"
# Track fields the editor may change that the native timeline stores (editor-features adds "muted"
# to mv_studio_timeline.EXPORTABLE_TRACK_FIELDS when it makes mute exportable).
_DERIVED_TRACK_FIELDS = frozenset({"shaftSlot"})
_UNITY_PLATFORMS = {13: "android", 9: "ios"}
_TIMING = frozenset(mv_studio_timeline._CLIP_TIMING.values())
_PCM_NAME = re.compile(r"[a-f0-9]{32}\.wav\Z")
_PARSED = OrderedDict()
_PARSED_LOCK = threading.Lock()
_PARSED_ENTRIES = 3
# One registration or removal at a time in this process (the database guard covers other tools).
_ACTIVE = threading.Lock()

# Job stages, in order (English i18n keys; the page shows them in Korean).
STAGES = {
    "check": "Checking the base MV originals",
    "android": "Building the Android timeline",
    "ios": "Building the iOS timeline",
    "audio": "Converting the audio",
    "preview": "Building the preview audio",
    "jacket": "Preparing the jacket",
    "stop": "Stopping the game server",
    "write": "Writing to the game catalog",
    "restart": "Restarting the game server",
    "remove": "Removing the song from the game",
}

# Fixed user-facing messages (English i18n keys, translated by exact match in webtools/i18n.py).
NO_ELICHIKA = "MV registration requires the Elichika server app."
BUSY = "Another MV registration or removal is running. Try again when it finishes."
CHOOSE_BASE = "Choose the base MV."
BASE_UNKNOWN = "The base MV of this song is unknown. Only removal is available."
BASE_MISMATCH = "This song was made from another base MV. Register the project as a new song."
STRUCTURE = "The track structure changed, so the timeline cannot go into the game:"
TIMELINE_UNAVAILABLE = "The original MV timeline is unavailable. Reopen the original timeline before saving."
MOD_MISMATCH = "The project's timeline does not belong to this base MV."
ORIGINAL_MISSING_IOS = ("The base MV's original iOS timeline is not available. Allow the download, or register for "
                        "Android only.")
ORIGINAL_MISSING_ANDROID = ("The base MV's original Android timeline is not available. Allow the download, or register "
                            "for iOS only.")
OTHER_PLATFORM_FAILED_IOS = ("The edits could not be baked into the iOS original MV. Register for Android only to "
                             "play the original MV on iOS.")
OTHER_PLATFORM_FAILED_ANDROID = ("The edits could not be baked into the Android original MV. Register for iOS only to "
                                 "play the original MV on Android.")
PLATFORMS_DIFFER = "The Android and iOS timelines came out different, so nothing was registered."
UNBAKED = "Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again."
TITLE = "Enter a song title between 1 and 160 characters."
CREDIT = "Enter a credit of at most 200 characters on one line."
PLATFORMS_CHOICE = "Choose Android, iOS or both."
REQUEST = "The MV registration request is invalid."
MODE = "Choose a new song, or a registered song to update."
KEEP_NEW = "A new song has no registered part to keep."
AUDIO_KIND = "Choose the song audio."
ENCODER = "This version can register only the original audio or prepared ACB/AWB files."
BPM_REQUIRED = "Enter the BPM and the first beat of the project audio."
BEAT = "Enter a BPM between 1 and 999 and a first beat of 0 seconds or more."
PREVIEW_START = "Enter a preview start of 0 seconds or more."
PCM_MISSING = "The converted project audio is no longer available. Register again."
PCM_SIZE = "The converted audio is empty or larger than 96 MiB."
AUDIO_TEMPLATE = "The base song's audio is not available locally. Allow the download, or keep the original audio."
JACKET_KIND = "Choose the jacket."
JACKET_CROP = "Choose the square area for the jacket."
JACKET_BOX = "The jacket area must be a square inside the image."
JACKET_IMAGE = "The jacket must be a PNG, JPEG or another image this app can open."
JACKET_SOURCE = "The jacket image is larger than this app can open."
CANCELLED = "MV registration was cancelled."
REMOVE_CANCELLED = "Removing the MV-only song was cancelled."
REGISTERED = "Registered '{title}' ({id})."
UPDATED = "Updated '{title}' ({id})."
NO_CHANGES = "No changes to apply."
REMOVED = "Removed '{title}' ({id})."
RESTARTED = "The game server was restarted."
RESTART_PENDING = "The game server restarts when this job finishes."
RESTART_MANUAL = "Restart the game server to apply it."
STOPPED_MANUAL = "The game server was stopped. Start it again."
# Plan notes: what does not reach the game.
NOT_TRACK_SETTINGS = "Track settings do not reach the game:"
NOT_VALUES = "These edited values are preview-only:"
NOT_STAGE = "Imported stage, effect or prop models"
NOT_PERFORMERS = "Imported performer models"
NOT_POSITIONS = "Member positions"
NOT_COSTUMES = "Pinned costumes (choose outfits in the game's MV deck)"
NOT_QUALITY = "MV quality preview settings"
NOT_UNBAKED = "Editor changes that could not be baked:"
FOLLOW_NOTE = "The follow camera is baked for the preview members' heights."
AUDIO_LONGER = "The audio is {seconds} s longer than the MV. The last scene holds until the music ends."
AUDIO_SHORTER = "The audio is {seconds} s shorter than the MV. The MV ends with the music."
OFFSET_BASE = "The soundtrack offset applies only to the project audio. The original audio starts with the MV."
EDITS_PENDING = "The edits are counted once the original MV is available. Allow the download to bake them."
MESSAGES = (
    NO_ELICHIKA, BUSY, CHOOSE_BASE, BASE_UNKNOWN, BASE_MISMATCH, STRUCTURE, TIMELINE_UNAVAILABLE, MOD_MISMATCH,
    ORIGINAL_MISSING_IOS, ORIGINAL_MISSING_ANDROID, OTHER_PLATFORM_FAILED_IOS, OTHER_PLATFORM_FAILED_ANDROID,
    PLATFORMS_DIFFER, UNBAKED, TITLE, CREDIT, PLATFORMS_CHOICE, REQUEST, MODE, KEEP_NEW, AUDIO_KIND, ENCODER,
    BPM_REQUIRED, BEAT, PREVIEW_START, PCM_MISSING, PCM_SIZE, AUDIO_TEMPLATE, JACKET_KIND, JACKET_CROP, JACKET_BOX,
    JACKET_IMAGE, JACKET_SOURCE, CANCELLED, REMOVE_CANCELLED, REGISTERED, UPDATED, NO_CHANGES, REMOVED, RESTARTED,
    RESTART_PENDING, RESTART_MANUAL, STOPPED_MANUAL, NOT_TRACK_SETTINGS, NOT_VALUES, NOT_STAGE, NOT_PERFORMERS,
    NOT_POSITIONS, NOT_COSTUMES, NOT_QUALITY, NOT_UNBAKED, FOLLOW_NOTE, AUDIO_LONGER, AUDIO_SHORTER, OFFSET_BASE,
    EDITS_PENDING,
    *STAGES.values(),
)


class _Cancelled(Exception):
    """The user cancelled the job before its database step."""


class StructureError(ValueError):
    """Added, removed or reordered tracks or clips; ``labels`` names the tracks."""

    def __init__(self, labels):
        super().__init__(STRUCTURE)
        self.labels = labels


# ---------------------------------------------------------------- environment

def store():
    """Elichika's MV Studio store; ImportError without the Elichika server app."""
    import mv_studio_live
    return mv_studio_live


def managed():
    """True when the app controls the game server (Android, macOS): the job stops and restarts it."""
    try:
        from adminui import serverctl
    except ImportError:
        return False
    return serverctl._controller is not None


def encoder_available():
    try:
        from . import cri_acb_write
        return bool(cri_acb_write.encoder_available())
    except Exception:  # noqa: BLE001 - feature detection: no numpy or no clHCA library
        return False


def capabilities():
    return {"encoder": encoder_available(), "managedRestart": managed()}


def songs(repo_root, *, region):
    """Every MV-only song of the region with the server capabilities (GET /api/mv-studio/songs)."""
    live = store()
    if region not in REGIONS:
        raise ValueError("Select the GL or JP catalog.")
    return {"region": region, "songs": live.list_mv_songs(repo_root, region=region), **capabilities()}


# ---------------------------------------------------------------- small helpers

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(*parts):
    digest = hashlib.sha256()
    for part in parts:
        data = part if isinstance(part, bytes) else str(part).encode("utf-8")
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _identity(value):
    return value if type(value) is int and 0 < value < 1 << 31 else None


def _text(value, limit, message, *, required):
    if value is None and not required:
        return None
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(message)
    value = value.strip()
    if required and not 1 <= len(value) <= limit or len(value) > limit:
        raise ValueError(message)
    return value or None


def _parse(raw, name="base"):
    """parse_timeline with a small in-process cache keyed by the bytes' sha256."""
    key = hashlib.sha256(raw).hexdigest()
    with _PARSED_LOCK:
        if key in _PARSED:
            _PARSED.move_to_end(key)
            return copy.deepcopy(_PARSED[key])
    parsed = mv_studio_timeline.parse_timeline(raw, name)
    with _PARSED_LOCK:
        _PARSED[key] = parsed
        while len(_PARSED) > _PARSED_ENTRIES:
            _PARSED.popitem(last=False)
    return copy.deepcopy(parsed)


def _export(raw, name, tracks):
    return mv_studio_timeline.export_timeline(raw, name, tracks)


def _blob_platform(raw):
    """The Unity build target of a native timeline blob: android, ios or None."""
    try:
        env, _, _ = mv_studio_timeline._read(raw, "project", time.monotonic() + 45)
        assets = list(env.assets)
        return _UNITY_PLATFORMS.get(int(assets[0].target_platform)) if len(assets) == 1 else None
    except (ValueError, OSError, TypeError, AttributeError, IndexError):
        return None


def _load(repo_root, descriptor, *, download, deadline=None):
    return mv_studio_game.load_asset(repo_root, descriptor, download=download,
                                     deadline=deadline if deadline is not None else
                                     time.monotonic() + (180 if download else 20))


# ---------------------------------------------------------------- base MV

def _base(repo_root, project, template, live):
    """The base MV: {region, liveId, assetId, fixed, registered, song?}, None (choose one) or BASE_UNKNOWN."""
    source = project.get("source") if isinstance(project.get("source"), dict) else {}
    if (source.get("kind") == "game" and source.get("region") in REGIONS and _identity(source.get("liveId"))
            and _identity(source.get("assetId"))):
        region = source["region"]
        if source.get("registered") is True:
            song = live.describe_mv_song(repo_root, region=region, live_id=source["liveId"])
            if song.get("templateAssetId") is None:
                return {"region": region, "liveId": None, "assetId": None, "fixed": True, "registered": True,
                        "song": song, "unknown": True}
            return {"region": region, "liveId": song["templateLiveId"], "assetId": song["templateAssetId"],
                    "fixed": True, "registered": True, "song": song}
        return {"region": region, "liveId": source["liveId"], "assetId": source["assetId"], "fixed": True,
                "registered": False}
    if template is None:
        return None
    if (not isinstance(template, dict) or set(template) != {"region", "liveId", "assetId"}
            or template["region"] not in REGIONS or not _identity(template["liveId"])
            or not _identity(template["assetId"])):
        raise ValueError(CHOOSE_BASE)
    return {"region": template["region"], "liveId": template["liveId"], "assetId": template["assetId"],
            "fixed": False, "registered": False}


def _first_catalog_row(root, region, platform, language, table, key):
    for path in mv_studio_game._asset_catalogs(root, region, platform, language):
        with closing(game._readonly(path)) as db:
            descriptor = mv_studio_game._resource(db, table, key, table)
            if descriptor is not None:
                mv_studio_game._link_bundle_packs(db, [descriptor])
                return descriptor, path
    return None, None


def _facts(repo_root, region, live_id, asset_id, language="en"):
    """Catalog facts of a stock base MV: title, stage, timeline descriptors per platform, audio descriptors."""
    root = Path(repo_root).resolve()
    with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as master:
        master.row_factory = sqlite3.Row
        live = master.execute("SELECT * FROM m_live WHERE live_id=?", (live_id,)).fetchone()
        asset = master.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (asset_id,)).fetchone()
        stage = None
        if asset is not None:
            try:
                stage = master.execute("SELECT * FROM m_live_stage WHERE id=?",
                                       (asset["live_stage_master_id"],)).fetchone()
            except Exception:  # noqa: BLE001 - optional display data
                stage = None
    if live is None or asset is None or not asset["timeline"] or live["is_2d_live"]:
        raise ValueError("The base MV must be a stock 3D song with a song cue and formation.")
    title, stage_name = str(live_id), None
    try:
        extractor = game._extractor()
        dictionary = game._dictionary(root, region, language)
        try:
            title = mv_studio_game._display(extractor, dictionary, live["name"], live_id)
            if stage is not None and "stage_name" in stage.keys():
                stage_name = mv_studio_game._display(extractor, dictionary, stage["stage_name"],
                                                     stage["scene_name"] if "scene_name" in stage.keys() else None)
        finally:
            if dictionary is not None:
                dictionary.close()
    except Exception:  # noqa: BLE001 - display names are optional
        pass
    timelines, audio = {}, {"music": None, "preview": None}
    for platform in PLATFORMS:
        descriptor, path = _first_catalog_row(root, region, platform, language, "live_timeline", asset["timeline"])
        if descriptor is not None:
            timelines[platform] = descriptor
            if audio["music"] is None:
                with closing(game._readonly(path)) as db:
                    audio["music"] = mv_studio_game._sound(db, live["bgm_path"], [], "audio")
                    audio["preview"] = mv_studio_game._sound(db, live["chorus_bgm_path"], [], "chorus")
    return {"liveId": live_id, "assetId": asset_id, "title": title, "stage": stage_name,
            "timelineKey": asset["timeline"], "timelines": timelines, "audio": audio,
            "bgmPath": live["bgm_path"], "chorusPath": live["chorus_bgm_path"]}


def _stock_identity(descriptor):
    return ":".join(str(descriptor.get(field)) for field in ("pack_name", "head", "size", "key1", "key2"))


# ---------------------------------------------------------------- originals per platform

def _project_blob(project, base):
    """The project's own native timeline: {"kind", "raw", "platform"}.

    kind is None (no native timeline: audio or GLB only), "stock" (a game import of the base MV,
    whose blob is the stock pack of ``platform``), "registered" (an import of a registered song:
    its blob is the song's edited timeline, never a base) or "mod" (a mod timeline, the base of
    its own platform).
    """
    if project.get("nativeTimeline") is not True:
        return {"kind": None, "raw": None, "platform": None}
    source = project.get("source") if isinstance(project.get("source"), dict) else {}
    game_source = source.get("kind") == "game" and source.get("platform") in PLATFORMS
    if game_source and base.get("registered"):
        return {"kind": "registered", "raw": None, "platform": source["platform"]}
    raw = mv_studio._native(project)
    if raw is None:
        raise ValueError(TIMELINE_UNAVAILABLE)
    if game_source:
        if source.get("liveId") == base["liveId"] and source.get("assetId") == base["assetId"]:
            return {"kind": "stock", "raw": raw, "platform": source["platform"]}
    return {"kind": "mod", "raw": raw, "platform": _blob_platform(raw)}


def _original(repo_root, facts, platform, blob, *, download, deadline=None):
    """(stock bytes or None, status): project, local, download (fetched or needed) or missing."""
    descriptor = facts["timelines"].get(platform)
    if descriptor is None:
        return None, "missing"
    if (blob["kind"] == "stock" and blob["platform"] == platform and blob["raw"] is not None
            and len(blob["raw"]) == descriptor["size"]):
        return blob["raw"], "project"
    local = _load(repo_root, descriptor, download=False, deadline=deadline)
    if local is not None:
        return local, "local"
    if download:
        fetched = _load(repo_root, descriptor, download=True, deadline=deadline)
        if fetched is not None:
            return fetched, "download"
    return None, "download"


def _original_status(repo_root, facts, platform, blob):
    """Plan-only status without reading a pack twice: (status, bytes of a usable original or None)."""
    raw, status = _original(repo_root, facts, platform, blob, download=False)
    descriptor = facts["timelines"].get(platform) or {}
    size = descriptor.get("pack_size") or descriptor.get("size")
    return {"status": status, **({"bytes": size} if status == "download" and size else {})}, raw


# ---------------------------------------------------------------- normalization and edits

def _label(track):
    return str(track.get("label") or track.get("id") or "")


def normalize(original_tracks, tracks):
    """Return (tracks ready for export_timeline, report) or raise StructureError.

    Every non-``events`` track field goes back to the base parse except those in
    ``mv_studio_timeline.EXPORTABLE_TRACK_FIELDS``. Event values outside the clip's
    ``editableValues`` go back to the base, and extra keys are dropped. Added, removed or
    reordered tracks or clips are refused with their track labels.
    """
    if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
        raise ValueError(REQUEST)
    base = {track["id"]: track for track in original_tracks}
    order = [track.get("id") for track in tracks]
    labels = []
    if order != list(base):
        names = {track.get("id"): _label(track) for track in tracks}
        changed = [names[identity] for identity in order if identity not in base]
        changed += [_label(base[identity]) for identity in base if identity not in order]
        if not changed:
            changed = [_label(base[identity]) for identity, expected in zip(order, base) if identity != expected]
        raise StructureError(sorted(dict.fromkeys(changed)))
    exportable = frozenset(getattr(mv_studio_timeline, "EXPORTABLE_TRACK_FIELDS", ()))
    normalized, settings, preview = [], [], []
    for track in tracks:
        before = base[track["id"]]
        events = track.get("events")
        if (not isinstance(events, list) or any(not isinstance(event, dict) for event in events)
                or [event.get("id") for event in events] != [event["id"] for event in before["events"]]):
            labels.append(_label(before))
            continue
        result, restored = {}, False
        for key in set(before) | set(track):
            if key == "events":
                continue
            if key in exportable and key in track:
                result[key] = track[key]
            elif key in before:
                result[key] = before[key]
            if key not in _DERIVED_TRACK_FIELDS and key not in exportable and track.get(key) != before.get(key):
                restored = True
        if restored:
            settings.append(_label(before))
        output, edited_preview = [], False
        for event, original in zip(events, before["events"]):
            editable = set(original.get("editableValues") or ())
            values = event.get("values") if isinstance(event.get("values"), dict) else {}
            merged = {}
            for key, value in original["values"].items():
                if key in editable and key in values:
                    merged[key] = values[key]
                else:
                    merged[key] = value
                    if key in values and values[key] != value:
                        edited_preview = True
            output.append({**original, "start": event.get("start", original["start"]),
                           "duration": event.get("duration", original["duration"]),
                           "label": event.get("label", original["label"]), "values": merged})
        if edited_preview:
            preview.append(_label(before))
        result["events"] = output
        normalized.append(result)
    if labels:
        raise StructureError(sorted(dict.fromkeys(labels)))
    return normalized, {"trackSettings": sorted(dict.fromkeys(settings)),
                        "previewValues": sorted(dict.fromkeys(preview))}


def count_edits(original_tracks, tracks):
    """Edits by kind between the base parse and normalized tracks."""
    counts = {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0}
    for before, after in zip(original_tracks, tracks):
        for old, new in zip(before["events"], after["events"]):
            if old == new:
                continue
            counts["clips"] += 1
            changed = {key for key in old["values"] if new["values"].get(key) != old["values"][key]}
            if any(new[key] != old[key] for key in ("start", "duration", "label")) or changed & _TIMING:
                counts["timing"] += 1
            if "keyframes" in changed:
                counts["cameraShots"] += 1
            counts["values"] += len(changed - _TIMING - {"keyframes"})
    return counts


def _exportable_view(tracks):
    """What reaches the game from the project's tracks: clip timing, names and editable values."""
    view = []
    for track in tracks if isinstance(tracks, list) else ():
        if not isinstance(track, dict):
            continue
        events = []
        for event in track.get("events") or ():
            if not isinstance(event, dict):
                continue
            values = event.get("values") if isinstance(event.get("values"), dict) else {}
            editable = event.get("editableValues") if isinstance(event.get("editableValues"), list) else ()
            events.append([event.get("id"), event.get("start"), event.get("duration"), event.get("label"),
                           {key: values[key] for key in editable if isinstance(key, str) and key in values}])
        view.append([track.get("id"), events])
    return view


def timeline_fingerprint(platform, base_identity, tracks):
    """sha256 over the format version, the base original's identity and the exportable part of the tracks."""
    return _sha(FINGERPRINT_VERSION, "timeline", platform, base_identity, _canonical(_exportable_view(tracks)))


# ---------------------------------------------------------------- preview-only content

def _not_in_game(project, report, unbaked):
    notes = []
    if report.get("trackSettings"):
        notes.append({"message": NOT_TRACK_SETTINGS, "labels": report["trackSettings"]})
    if report.get("previewValues"):
        notes.append({"message": NOT_VALUES, "labels": report["previewValues"]})
    imported = [row for row in project.get("assets") or () if isinstance(row, dict)
                and re.fullmatch(r"[0-9a-f]{16}", str(row.get("id", "")))]
    if any(row.get("kind") in {"stage", "effect", "props", "background"} for row in imported):
        notes.append({"message": NOT_STAGE})
    game_source = (project.get("source") or {}).get("kind") == "game"
    performers = [row for row in project.get("performers") or () if isinstance(row, dict)]
    if any(row.get("kind") in {"performer", "outfit"} for row in imported) or (performers and not game_source):
        notes.append({"message": NOT_PERFORMERS})
    moved = False
    for row in performers:
        position = (row.get("transform") or {}).get("position") if isinstance(row.get("transform"), dict) else None
        if row.get("motion") and isinstance(position, list) and any(value != 0 for value in position):
            moved = True
    if moved:
        notes.append({"message": NOT_POSITIONS})
    if any(row.get("suitSource") == "pinned" for row in performers):
        notes.append({"message": NOT_COSTUMES})
    quality = project.get("quality") if isinstance(project.get("quality"), dict) else {}
    preset = next((mode for mode in quality.get("modes") or () if isinstance(mode, dict)
                   and mode.get("id") == quality.get("mode")), None)
    if preset is not None and isinstance(quality.get("values"), dict) and quality["values"] != preset.get("values"):
        notes.append({"message": NOT_QUALITY})
    if unbaked:
        notes.append({"message": NOT_UNBAKED, "labels": sorted({str(item.get("eventId") or item.get("kind") or "")
                                                                 for item in unbaked if isinstance(item, dict)})})
    return notes


def _follow(project):
    editor = project.get("editor") if isinstance(project.get("editor"), dict) else {}
    camera = editor.get("camera") if isinstance(editor.get("camera"), dict) else {}
    return bool(camera.get("rigs"))


# ---------------------------------------------------------------- audio

def _beat_default(facts, project, repo_root, offset):
    """The base cue's beat table shifted by the soundtrack offset: {bpm, firstBeat, segments?} or None."""
    beat = None
    stage = project.get("stage") if isinstance(project.get("stage"), dict) else {}
    if isinstance(stage.get("beatSync"), dict):
        beat = stage["beatSync"]
    else:
        music = facts["audio"].get("music") or {}
        if music.get("acb"):
            try:
                from . import cri_audio_decode
                acb = _load(repo_root, music["acb"], download=False)
                if acb is not None:
                    beat = cri_audio_decode.inspect_beat_sync(acb, music["cue"])
            except Exception:  # noqa: BLE001 - the beat table only prefills two inputs
                beat = None
    return shift_beat(beat, offset) if beat else None


def shift_beat(beat, offset, rate=SAMPLE_RATE):
    """Move a CRI beat table by the soundtrack offset (audio time = director time + offset)."""
    try:
        segments = beat.get("segments") or [beat]
        shift = round(float(offset) * rate)
        kept = []
        for segment in segments:
            bpm, start, end = float(segment["bpm"]), int(segment["startSample"]) - shift, int(segment["endSample"]) - shift
            if end < 0 or not 0 < bpm <= 1000:
                continue
            if start < 0:
                period = 60 * rate / bpm
                start = int(round(start + math.ceil(-start / period) * period))
            kept.append({"bpm": round(bpm, 6), "startSample": max(0, start)})
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not kept:
        return None
    result = {"bpm": kept[0]["bpm"], "firstBeat": round(kept[0]["startSample"] / rate, 6)}
    if len(kept) > 1:
        result["segments"] = kept
    return result


def _soundtrack(project):
    track = project.get("soundtrack") if isinstance(project.get("soundtrack"), dict) else None
    if not track or not isinstance(track.get("url"), str):
        return None
    offset = track.get("offset", 0)
    offset = float(offset) if type(offset) in (int, float) and math.isfinite(offset) else 0.0
    duration = track.get("duration")
    duration = float(duration) if type(duration) in (int, float) and math.isfinite(duration) else None
    return {"origin": track.get("origin") if track.get("origin") == "game" else "project", "offset": offset,
            "duration": duration, "url": track["url"]}


def _preview_start(duration):
    if not duration:
        return 0.0
    return float(min(60.0, max(0.0, round(duration - 20, 1))))


def store_pcm(data):
    """Keep page-decoded PCM (RIFF/WAVE, 16-bit, 44.1 kHz, stereo) in the media cache: {name, duration}."""
    from . import cri_hca_encode
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= PCM_BYTES:
        raise ValueError(PCM_SIZE)
    pcm = cri_hca_encode.read_wav(bytes(data), max_bytes=PCM_BYTES)
    url = mv_studio._media(bytes(data), "wav")
    return {"name": url.rsplit("/", 1)[1], "duration": round(len(pcm) / SAMPLE_RATE, 6), "samples": int(len(pcm))}


def _read_pcm(name):
    from . import cri_hca_encode
    if not isinstance(name, str) or not _PCM_NAME.fullmatch(name):
        raise ValueError(PCM_MISSING)
    try:
        path, _ = mv_studio.media(name)
    except FileNotFoundError:
        raise ValueError(PCM_MISSING) from None
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest()[:32] != name[:32]:
        raise ValueError(PCM_MISSING)
    return cri_hca_encode.read_wav(data, max_bytes=PCM_BYTES), name[:32]


def _beat_argument(audio):
    bpm, first = audio.get("bpm"), audio.get("firstBeat")
    if bpm is None or first is None:
        raise ValueError(BPM_REQUIRED)
    if (type(bpm) not in (int, float) or type(first) not in (int, float) or not math.isfinite(bpm)
            or not math.isfinite(first) or not 0 < bpm < 1000 or first < 0):
        raise ValueError(BEAT)
    segments = audio.get("segments")
    if segments is not None:
        if (not isinstance(segments, list) or not 1 < len(segments) <= 64
                or any(not isinstance(item, dict) or set(item) != {"bpm", "startSample"}
                       or type(item["bpm"]) not in (int, float) or type(item["startSample"]) is not int
                       for item in segments)):
            raise ValueError(BEAT)
        return {"segments": [{"bpm": float(item["bpm"]), "startSample": item["startSample"]} for item in segments]}
    return {"bpm": float(bpm), "firstBeat": float(first)}


# ---------------------------------------------------------------- jacket

def _image_module():
    from PIL import Image, ImageOps
    return Image, ImageOps


def _open_image(path):
    Image, ImageOps = _image_module()
    data = Path(path).read_bytes()
    if not 0 < len(data) <= JACKET_SOURCE_BYTES:
        raise ValueError(JACKET_SOURCE)
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > JACKET_SOURCE_PIXELS:
            raise ValueError(JACKET_SOURCE)
        image.load()
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001 - Pillow raises many types for bad files
        raise ValueError(JACKET_IMAGE) from error
    orientation = 1
    try:
        orientation = int(image.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001
        orientation = 1
    oriented = ImageOps.exif_transpose(image) if orientation != 1 else image
    return data, image.format, orientation, oriented


def jacket_preview(path):
    """{width, height, format, square, exact, previewUrl} of a chosen jacket image (after EXIF orientation)."""
    source = mv_studio._path(path)
    Image, _ = _image_module()
    data, kind, orientation, image = _open_image(source)
    width, height = image.size
    exact = (width, height) == (JACKET_SIZE, JACKET_SIZE) and kind in ("PNG", "JPEG") and orientation == 1
    thumbnail = image.copy()
    if thumbnail.mode not in ("RGB", "RGBA", "L", "LA"):
        thumbnail = thumbnail.convert("RGBA")
    # Display only: the crop box is drawn over this picture; the jacket itself is cut from the source.
    thumbnail.thumbnail((PREVIEW_IMAGE, PREVIEW_IMAGE), Image.LANCZOS)
    buffer = io.BytesIO()
    thumbnail.save(buffer, "PNG")
    return {"width": width, "height": height, "format": (kind or "").lower(), "square": width == height,
            "exact": exact, "name": source.name,
            "previewUrl": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}


def prepare_jacket(path, crop=None):
    """Jacket bytes for the store: verbatim 400x400 PNG/JPEG, else an exact crop, resized only when not 400 px."""
    Image, _ = _image_module()
    data, kind, orientation, image = _open_image(path)
    width, height = image.size
    if crop is None:
        if width != height:
            raise ValueError(JACKET_CROP)
        box = (0, 0, width, height)
    else:
        if (not isinstance(crop, dict) or set(crop) != {"x", "y", "size"}
                or any(type(crop[key]) is not int for key in crop)):
            raise ValueError(JACKET_BOX)
        x, y, size = crop["x"], crop["y"], crop["size"]
        if size < 1 or x < 0 or y < 0 or x + size > width or y + size > height:
            raise ValueError(JACKET_BOX)
        box = (x, y, x + size, y + size)
    whole = box == (0, 0, width, height)
    if (whole and (width, height) == (JACKET_SIZE, JACKET_SIZE) and kind in ("PNG", "JPEG") and orientation == 1
            and len(data) <= JACKET_BYTES):
        return data
    region = image if whole else image.crop(box)
    if region.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        region = region.convert("RGBA" if "A" in region.getbands() else "RGB")
    if region.size != (JACKET_SIZE, JACKET_SIZE):
        # A genuinely different size: the one resample this path allows.
        if region.mode == "P":
            region = region.convert("RGBA")
        region = region.resize((JACKET_SIZE, JACKET_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    region.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------- plan

def _targets(listed, base):
    return [song for song in listed if base and song.get("templateLiveId") == base["liveId"]
            and song.get("templateAssetId") == base["assetId"]]


def plan(repo_root, project, *, template=None, target=None, unbaked=(), language="en"):
    """What a registration of ``project`` would do. Writes nothing and bakes nothing."""
    live = store()
    mv_studio._document(project)
    result = {"region": None, "base": None, "song": None, "targets": [], "target": "new",
              "title": project["name"].strip()[:MAX_TITLE], "credit": "", "platforms": {}, "projectPlatform": None,
              "timeline": {"native": project.get("nativeTimeline") is True, "unchanged": True, "fingerprints": {}},
              "edits": {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0, "follow": _follow(project)},
              "notInGame": [], "blocked": [], "warnings": [], "audio": {}, "jacket": {"default": "base"},
              **capabilities()}
    base = _base(repo_root, project, template, live)
    if base is None:
        result["blocked"].append({"message": CHOOSE_BASE})
        result["region"] = (template or {}).get("region") if isinstance(template, dict) else None
        _audio_plan(result, project, None, repo_root, None)
        return result
    result["region"] = base["region"]
    if base.get("unknown"):
        result["song"] = base["song"]
        result["blocked"].append({"message": BASE_UNKNOWN})
        return result
    facts = _facts(repo_root, base["region"], base["liveId"], base["assetId"], language)
    result["base"] = {"liveId": base["liveId"], "assetId": base["assetId"], "title": facts["title"],
                      "stage": facts["stage"], "fixed": base["fixed"], "registered": base["registered"]}
    listed = live.list_mv_songs(repo_root, region=base["region"])
    result["targets"] = _targets(listed, base)
    known = {song["liveId"]: song for song in result["targets"]}
    link = project.get("registration") if isinstance(project.get("registration"), dict) else {}
    chosen = None
    if target not in (None, "new"):
        if not _identity(target) or target not in known:
            raise ValueError(MODE)
        chosen = known[target]
    elif target is None:
        if base.get("registered") and base["song"]["liveId"] in known:
            chosen = known[base["song"]["liveId"]]
        elif link.get("region") == base["region"] and link.get("liveId") in known:
            chosen = known[link["liveId"]]
    if chosen is not None:
        result["target"], result["song"] = chosen["liveId"], chosen
        result["title"], result["credit"] = chosen["title"], chosen.get("credit") or ""
        result["jacket"]["default"] = "keep"
    # Originals per platform and the base parse.
    try:
        blob = _project_blob(project, base)
    except ValueError as error:
        result["blocked"].append({"message": str(error)})
        _audio_plan(result, project, facts, repo_root, chosen)
        return result
    result["projectPlatform"] = blob["platform"]
    result["timeline"]["kind"] = blob["kind"]
    stock_raw = None
    for platform in PLATFORMS:
        status, raw = _original_status(repo_root, facts, platform, blob)
        result["platforms"][platform] = status
        if raw is not None and stock_raw is None:
            stock_raw = raw
    if blob["kind"] == "stock" and stock_raw is None:
        stock_raw = blob["raw"]
    tracks = project["tracks"]
    keep = []
    if blob["kind"] is not None:
        mod_raw = blob["raw"] if blob["kind"] == "mod" else None
        for platform in PLATFORMS:
            descriptor = facts["timelines"].get(platform)
            if descriptor is None:
                continue
            identity = _stock_identity(descriptor)
            if mod_raw is not None and platform == blob["platform"]:
                identity += ":" + hashlib.sha256(mod_raw).hexdigest()
            fingerprint = timeline_fingerprint(platform, identity, tracks)
            result["timeline"]["fingerprints"][platform] = fingerprint
            if (chosen is not None and chosen.get("platforms", {}).get(platform) == "custom"
                    and chosen.get("fingerprints", {}).get(platform) == fingerprint):
                keep.append(platform)
        try:
            if stock_raw is None and mod_raw is None:
                result["timeline"]["pending"] = True
                result["timeline"]["unchanged"] = False
                result["warnings"].append({"message": EDITS_PENDING})
                result["notInGame"] = _not_in_game(project, {}, unbaked)
            else:
                original = _parse(stock_raw if stock_raw is not None else mod_raw)
                reference = _parse(mod_raw) if mod_raw is not None else original
                if mod_raw is not None and stock_raw is not None and (
                        [track["id"] for track in original["tracks"]] != [track["id"] for track in reference["tracks"]]):
                    raise ValueError(MOD_MISMATCH)
                normalized, report = normalize(reference["tracks"], tracks)
                result["notInGame"] = _not_in_game(project, report, unbaked)
                counts = count_edits(original["tracks"], normalized)
                result["edits"].update(counts)
                result["timeline"]["unchanged"] = not counts["clips"] and mod_raw is None
                result["timeline"]["duration"] = original["duration"]
        except StructureError as error:
            result["blocked"].append({"message": STRUCTURE, "labels": error.labels})
        except (ValueError, OSError, KeyError, TypeError) as error:
            result["blocked"].append({"message": str(error)})
    else:
        result["notInGame"] = _not_in_game(project, {}, unbaked)
    timeline = result["timeline"]
    timeline["keep"] = keep
    # Platforms whose original the bake needs: every catalogued one with edits, minus kept ones.
    bake = [] if blob["kind"] is None or timeline["unchanged"] else [
        platform for platform in PLATFORMS if platform in facts["timelines"] and platform not in keep]
    timeline["bake"] = bake
    timeline["download"] = [platform for platform in bake if result["platforms"][platform]["status"] == "download"]
    timeline["missing"] = [platform for platform in PLATFORMS if result["platforms"][platform]["status"] == "missing"]
    if unbaked:
        result["blocked"].append({"message": UNBAKED})
    if result["edits"]["follow"]:
        result["warnings"].append({"message": FOLLOW_NOTE})
    _audio_plan(result, project, facts, repo_root, chosen)
    return result


def _audio_plan(result, project, facts, repo_root, song):
    soundtrack = _soundtrack(project)
    encoder = result.get("encoder", False)
    if song is not None:
        default = "keep"
    elif soundtrack is None or soundtrack["origin"] == "game" and abs(soundtrack["offset"]) < 1e-9:
        default = "base"
    else:
        default = "project" if encoder else "base"
    audio = {"default": default, "encoder": encoder, "soundtrack": soundtrack, "beat": None,
             "previewStart": _preview_start(soundtrack["duration"] - soundtrack["offset"]
                                            if soundtrack and soundtrack["duration"] else None),
             "template": "missing", "music": None}
    if facts is not None:
        music = facts["audio"].get("music") or {}
        if music.get("acb"):
            local = _load(repo_root, music["acb"], download=False) is not None
            audio["template"] = "local" if local else "download"
        if soundtrack is not None and soundtrack["origin"] == "game":
            audio["beat"] = _beat_default(facts, project, repo_root, soundtrack["offset"])
        duration = result["timeline"].get("duration")
        if soundtrack and soundtrack["duration"] and duration:
            difference = round(soundtrack["duration"] - soundtrack["offset"] - duration, 1)
            if difference >= 0.5:
                result["warnings"].append({"message": AUDIO_LONGER, "values": {"seconds": difference}})
            elif difference <= -0.5:
                result["warnings"].append({"message": AUDIO_SHORTER, "values": {"seconds": -difference}})
        if soundtrack and abs(soundtrack["offset"]) >= 1e-9 and default == "base":
            result["warnings"].append({"message": OFFSET_BASE})
    result["audio"] = audio


# ---------------------------------------------------------------- job request

def _platforms(value):
    """The platforms to bake; one left out (consented) or both left out keep playing the original MV."""
    if not isinstance(value, list) or len(value) > 2 or any(item not in PLATFORMS for item in value) \
            or len(set(value)) != len(value):
        raise ValueError(PLATFORMS_CHOICE)
    return tuple(platform for platform in PLATFORMS if platform in value)


def _jacket_request(value, update):
    if not isinstance(value, dict) or value.get("kind") not in ("keep", "base", "file"):
        raise ValueError(JACKET_KIND)
    if value["kind"] == "keep" and not update:
        raise ValueError(KEEP_NEW)
    if value["kind"] != "file":
        if set(value) != {"kind"}:
            raise ValueError(JACKET_KIND)
        return {"kind": value["kind"]}
    if set(value) - {"kind", "path", "crop"} or "path" not in value:
        raise ValueError(JACKET_KIND)
    return {"kind": "file", "path": mv_studio._path(value["path"]), "crop": value.get("crop")}


def _audio_request(value, update):
    if not isinstance(value, dict) or value.get("kind") not in ("base", "keep", "project", "files"):
        raise ValueError(AUDIO_KIND)
    kind = value["kind"]
    allowed = {"base": {"kind"}, "keep": {"kind"},
               "project": {"kind", "pcm", "bpm", "firstBeat", "segments", "previewStart"},
               "files": {"kind", "acbPath", "awbPath"}}[kind]
    if set(value) - allowed:
        raise ValueError(AUDIO_KIND)
    if kind == "keep" and not update:
        raise ValueError(KEEP_NEW)
    if kind == "project":
        if not encoder_available():
            raise ValueError(ENCODER)
        if not isinstance(value.get("pcm"), str) or not _PCM_NAME.fullmatch(value["pcm"]):
            raise ValueError(PCM_MISSING)
        beat = _beat_argument(value)
        start = value.get("previewStart", 0)
        if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
            raise ValueError(PREVIEW_START)
        return {"kind": kind, "pcm": value["pcm"], "beat": beat, "previewStart": float(start)}
    if kind == "files":
        if "acbPath" not in value:
            raise ValueError("Choose the ACB cue sheet for this AWB bank.")
        return {"kind": kind, "acb": mv_studio._path(value["acbPath"]),
                "awb": mv_studio._path(value["awbPath"]) if value.get("awbPath") else None}
    return {"kind": kind}


def validate_register(repo_root, data):
    """Check a register-job request before any job starts; returns the normalized request."""
    if not isinstance(data, dict):
        raise ValueError(REQUEST)
    mode = data.get("mode")
    if mode not in ("new", "update"):
        raise ValueError(MODE)
    if mode == "update" and data.get("addPlaceholder") is True and "project" not in data:
        # "Fix" from the songs list: only the placeholder chart, every other part kept.
        if set(data) - {"mode", "region", "liveId", "addPlaceholder"} or data.get("region") not in REGIONS \
                or not _identity(data.get("liveId")):
            raise ValueError(REQUEST)
        return {"mode": "fix", "region": data["region"], "liveId": data["liveId"]}
    allowed = {"project", "mode", "liveId", "template", "title", "credit", "jacket", "audio", "platforms", "download",
               "unbaked", "addPlaceholder"}
    if set(data) - allowed or not {"project", "title", "jacket", "audio", "platforms"} <= set(data):
        raise ValueError(REQUEST)
    project = data["project"]
    mv_studio._document(project)
    update = mode == "update"
    if update and not _identity(data.get("liveId")) or not update and "liveId" in data:
        raise ValueError(MODE)
    if type(data.get("download", False)) is not bool or type(data.get("addPlaceholder", False)) is not bool:
        raise ValueError(REQUEST)
    unbaked = data.get("unbaked", [])
    if not isinstance(unbaked, list):
        raise ValueError(REQUEST)
    if unbaked:
        raise ValueError(UNBAKED)
    return {"mode": mode, "project": project, "liveId": data.get("liveId"), "template": data.get("template"),
            "title": _text(data["title"], MAX_TITLE, TITLE, required=True),
            "credit": _text(data.get("credit"), MAX_CREDIT, CREDIT, required=False),
            "jacket": _jacket_request(data["jacket"], update), "audio": _audio_request(data["audio"], update),
            "platforms": _platforms(data["platforms"]), "download": data.get("download", False),
            "addPlaceholder": data.get("addPlaceholder", False)}


def validate_remove(data):
    if (not isinstance(data, dict) or set(data) != {"region", "liveId", "reviewToken"}
            or data["region"] not in REGIONS or not _identity(data["liveId"])
            or not isinstance(data["reviewToken"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["reviewToken"])):
        raise ValueError("The removal review is out of date. Review the song again before removing it.")
    return data


def remove_plan(repo_root, *, region, live_id):
    live = store()
    if region not in REGIONS or not _identity(live_id):
        raise ValueError("Select a song registered by MV Studio.")
    plan_result = live.plan_remove_mv_song(repo_root, region=region, live_id=live_id)
    return {"reviewToken": plan_result["review_token"], "summary": plan_result["summary"],
            "blocked": plan_result["blocked"]}


# ---------------------------------------------------------------- jobs

class _Progress:
    def __init__(self, job, stages):
        self.job, self.stages = job, list(stages)

    def stage(self, key):
        if key not in self.stages:
            self.stages.append(key)
        index = self.stages.index(key)
        self.job.emit({"type": "mv-stage", "stage": key, "label": STAGES[key], "index": index,
                       "total": len(self.stages)})
        self.job.progress(index, len(self.stages))
        self.job.log(STAGES[key])

    def check(self):
        if self.job.should_stop():
            raise _Cancelled()


def _server_session(job, *, stop, restart):
    from adminui.serverctl import installation_server
    return installation_server(job.log, stop=stop, restart=restart)


def _guard(root):
    from database_maintenance import guard
    return guard(root)


def _restart_state(session, is_managed, changed):
    """none (nothing changed), done, pending (after the job), or manual (start the server yourself)."""
    if not changed:
        return "none"
    if is_managed and getattr(session, "restart_pending", False):
        return "pending"
    if is_managed and getattr(session, "restarted", False):
        return "done"
    return "manual"


def _bake(job, progress, repo_root, project, base, facts, request, song):
    """Timelines, originals and fingerprints for the store. Runs before the game server stops.

    Every baked platform starts from its own stock original (embedded Shader objects differ
    between platforms), except a mod project's own platform, whose base is the mod timeline.
    Both platforms receive the same normalized tracks. A platform whose result equals its
    stock gets no override; an update keeps a platform whose fingerprint is unchanged.
    """
    from mv_studio_live import KEEP
    blob = _project_blob(project, base)
    if blob["kind"] is None:
        # Audio or GLB only: the base timeline plays unchanged (an update keeps what is there).
        return ({} if song is None else None), {}, {}
    mod_raw = blob["raw"] if blob["kind"] == "mod" else None
    tracks = project["tracks"]
    wanted = request["platforms"]
    timelines, originals, fingerprints, outputs = {}, {}, {}, {}
    normalized = None

    def reference_from(raw):
        reference = _parse(raw)
        result, _ = normalize(reference["tracks"], tracks)
        # Without edits both platforms keep the stock rows: nothing to bake or download.
        unchanged = mod_raw is None and not count_edits(reference["tracks"], result)["clips"]
        return result, unchanged

    if mod_raw is not None or blob["kind"] == "stock":
        normalized, unchanged = reference_from(mod_raw if mod_raw is not None else blob["raw"])
        if unchanged:
            return {}, {}, {}
    for platform in PLATFORMS:
        descriptor = facts["timelines"].get(platform)
        if platform not in wanted or descriptor is None:
            continue
        identity = _stock_identity(descriptor)
        own = mod_raw is not None and platform == blob["platform"]
        if own:
            identity += ":" + hashlib.sha256(mod_raw).hexdigest()
        fingerprint = timeline_fingerprint(platform, identity, tracks)
        if (song is not None and song["platforms"].get(platform) == "custom"
                and song.get("fingerprints", {}).get(platform) == fingerprint):
            timelines[platform] = KEEP
            fingerprints[platform] = fingerprint
            continue
        progress.check()
        progress.stage(platform)
        stock, status = _original(repo_root, facts, platform, blob, download=request["download"])
        if stock is None:
            raise ValueError(ORIGINAL_MISSING_IOS if platform == "ios" else ORIGINAL_MISSING_ANDROID)
        if status in ("project", "download"):
            originals[platform] = stock
        if normalized is None:
            normalized, unchanged = reference_from(stock)
            if unchanged:
                return {}, {}, {}
        try:
            output = _export(mod_raw if own else stock, request["title"], normalized)
        except ValueError:
            if mod_raw is not None and not own:
                raise ValueError(OTHER_PLATFORM_FAILED_IOS if platform == "ios" else OTHER_PLATFORM_FAILED_ANDROID)
            raise
        if output == stock:
            continue  # Unchanged: this platform keeps the stock row and gets no pack.
        timelines[platform] = output
        fingerprints[platform] = fingerprint
        outputs[platform] = output
    if len(outputs) == 2:
        parsed = [_parse(outputs[platform], "verify")["tracks"] for platform in PLATFORMS]
        if parsed[0] != parsed[1]:
            raise ValueError(PLATFORMS_DIFFER)
    return timelines, originals, fingerprints


def _music_sheet(live_id, song):
    if song is not None and song.get("audio") == "custom" and isinstance(song.get("musicSheet"), str):
        return song["musicSheet"]
    return f"music_{live_id}"


def _audio(job, progress, repo_root, facts, request, song, live_id):
    """(audio argument for the store, fingerprint or None)."""
    from mv_studio_live import KEEP
    audio = request["audio"]
    if audio["kind"] == "keep":
        return KEEP, None
    if audio["kind"] == "base":
        return None, None
    if audio["kind"] == "files":
        acb = audio["acb"].read_bytes()
        awb = audio["awb"].read_bytes() if audio["awb"] else None
        return {"music": (acb, awb)}, _sha(FINGERPRINT_VERSION, "files", acb, awb or b"")
    from . import cri_acb_write
    pcm, digest = _read_pcm(audio["pcm"])
    sheet = _music_sheet(live_id, song)
    music, chorus = facts["audio"].get("music") or {}, facts["audio"].get("preview") or {}
    fingerprint = _sha(FINGERPRINT_VERSION, "audio", digest, _canonical(audio["beat"]), audio["previewStart"], sheet,
                       _canonical([music.get("acb"), music.get("awb"), chorus.get("acb"), chorus.get("awb")]))
    if song is not None and song.get("audio") == "custom" and song.get("fingerprints", {}).get("audio") == fingerprint:
        return KEEP, fingerprint
    progress.check()
    progress.stage("audio")

    def load(descriptor):
        if not descriptor:
            return None
        return _load(repo_root, descriptor, download=request["download"])

    template_acb = load(music.get("acb"))
    template_awb = load(music.get("awb")) if music.get("awb") else None
    if template_acb is None or music.get("awb") and template_awb is None:
        raise ValueError(AUDIO_TEMPLATE)

    def tick(done, total):
        if job.should_stop():
            raise _Cancelled()
        job.emit({"type": "mv-encode", "done": int(done), "total": int(total)})

    with tempfile.TemporaryDirectory(prefix="mv-register-", dir=mv_studio._root()) as scratch:
        cue = cri_acb_write.make_cue(pcm, template_acb, template_awb, sheet=sheet, beat=audio["beat"], progress=tick,
                                     scratch_dir=scratch)
        progress.check()
        progress.stage("preview")
        sabi_acb = load(chorus.get("acb")) if chorus.get("acb") else None
        sabi_awb = load(chorus.get("awb")) if chorus.get("awb") else None
        if sabi_acb is not None and (not chorus.get("awb") or sabi_awb is not None):
            length = cri_acb_write.template_info(sabi_acb, sabi_awb)["sampleCount"]
        else:
            sabi_acb, sabi_awb, length = template_acb, template_awb, None
        preview = cri_acb_write.make_preview(pcm, sabi_acb, sabi_awb, sheet=sheet + "_SABI",
                                             start_seconds=audio["previewStart"], beat=audio["beat"],
                                             length_samples=length, scratch_dir=scratch)
    return {"music": (cue["acb"], cue["awb"]), "preview": (preview["acb"], preview["awb"])}, fingerprint


def _jacket(progress, request, song):
    from mv_studio_live import KEEP
    jacket = request["jacket"]
    if jacket["kind"] == "keep":
        return KEEP, None
    if jacket["kind"] == "base":
        return None, None
    progress.check()
    progress.stage("jacket")
    data = prepare_jacket(jacket["path"], jacket.get("crop"))
    fingerprint = _sha(FINGERPRINT_VERSION, "jacket", data)
    if song is not None and song.get("jacket") == "custom" and song.get("fingerprints", {}).get("jacket") == fingerprint:
        return KEEP, fingerprint
    return data, fingerprint


def _unchanged(song, request, timelines, audio, jacket):
    from mv_studio_live import KEEP
    if request["title"] != song["title"] or (request["credit"] or None) != (song.get("credit") or None):
        return False
    if request.get("addPlaceholder") and not song.get("visible"):
        return False
    for platform in PLATFORMS:
        value = timelines.get(platform) if isinstance(timelines, dict) else None
        current = song["platforms"].get(platform) == "custom"
        if timelines is None:
            continue
        if value is KEEP:
            continue
        if value is None and not current:
            continue
        return False
    return (audio is KEEP or audio is None and song.get("audio") == "base") and \
        (jacket is KEEP or jacket is None and song.get("jacket") == "base")


def _clear_late_cancel(job):
    # A cancel after the database step began did not stop it; the job finished.
    if job.should_stop():
        job.cancel_event.clear()
        job.log("Cancel arrived after the game catalog was being written; the change was kept.")


def _guarded_manager():
    """True when the app's guarded job manager (adminui.jobs) runs this job: it already holds
    whole_job_server and the database guard for the whole job."""
    try:
        from adminui.jobs import JobManager as GuardedJobManager
    except ImportError:
        return False
    import sys
    manager = getattr(sys.modules.get("webtools.server"), "MANAGER", None)
    if manager is None:
        from webtools.jobs import MANAGER as manager
    return isinstance(manager, GuardedJobManager)


def _lifecycle(stack, job):
    """whole_job_server for the plain webtools job manager (the guarded manager already holds it)."""
    if _guarded_manager():
        return None
    from adminui.serverctl import whole_job_server
    return stack.enter_context(whole_job_server(job.log))


def run_register(job, repo_root, request, *, language="en"):
    """Job body of POST /api/mv-studio/register-job. Returns the summary line."""
    try:
        with ExitStack() as stack:
            lifecycle = _lifecycle(stack, job)
            summary = _register(job, repo_root, request, language)
            if lifecycle is not None:
                lifecycle.successful = not job.should_stop()
            return summary
    except _Cancelled:
        return CANCELLED
    finally:
        _release()


def _register(job, repo_root, request, language):
    live = store()
    is_managed = managed()
    progress = _Progress(job, ["check"])
    progress.stage("check")
    if request["mode"] == "fix":
        song = live.describe_mv_song(repo_root, region=request["region"], live_id=request["liveId"])
        return _write(job, progress, repo_root, live, is_managed, request["region"], "update",
                      {"live_id": request["liveId"], "add_placeholder": True})
    project = request["project"]
    base = _base(repo_root, project, request.get("template"), live)
    if base is None:
        raise ValueError(CHOOSE_BASE)
    if base.get("unknown"):
        raise ValueError(BASE_UNKNOWN)
    region = base["region"]
    song = None
    if request["mode"] == "update":
        song = live.describe_mv_song(repo_root, region=region, live_id=request["liveId"])
        if song.get("templateAssetId") is None:
            raise ValueError(BASE_UNKNOWN)
        if (song["templateLiveId"], song["templateAssetId"]) != (base["liveId"], base["assetId"]):
            raise ValueError(BASE_MISMATCH)
    facts = _facts(repo_root, region, base["liveId"], base["assetId"], language)
    timelines, originals, fingerprints = _bake(job, progress, repo_root, project, base, facts, request, song)
    live_id = request["liveId"] if song is not None else None
    if request["audio"]["kind"] == "project" and live_id is None:
        # The cue sheet is named after the song id, so pick it before encoding.
        live_id = live.next_mv_song_id(repo_root, region=region)
    audio, audio_fingerprint = _audio(job, progress, repo_root, facts, request, song, live_id)
    jacket, jacket_fingerprint = _jacket(progress, request, song)
    for part, value in (("audio", audio_fingerprint), ("jacket", jacket_fingerprint)):
        if value:
            fingerprints[part] = value
    progress.check()
    if song is None:
        arguments = {"live_id": live_id, "template_live_id": base["liveId"], "template_asset_id": base["assetId"],
                     "title": request["title"], "credit": request["credit"], "timelines": timelines or None,
                     "originals": originals or None, "audio": audio, "jacket": jacket,
                     "fingerprints": fingerprints or None}
        return _write(job, progress, repo_root, live, is_managed, region, "new", arguments)
    arguments = {"live_id": song["liveId"], "title": request["title"], "credit": request["credit"],
                 "originals": originals or None, "audio": audio, "jacket": jacket,
                 "add_placeholder": request.get("addPlaceholder", False), "fingerprints": fingerprints or None}
    if timelines is not None:
        arguments["timelines"] = timelines
    noop = _unchanged(song, request, timelines, audio, jacket)
    return _write(job, progress, repo_root, live, is_managed, region, "update", arguments, noop=noop)


def _write(job, progress, repo_root, live, is_managed, region, mode, arguments, *, noop=False):
    root = Path(repo_root)
    stop = is_managed and not noop
    session = None
    with ExitStack() as stack:
        if stop:
            progress.stage("stop")
            session = stack.enter_context(_server_session(job, stop=True, restart=True))
        progress.stage("write")
        with _guard(root):
            if mode == "new":
                result = live.register_mv_song(repo_root, region=region, log=job.log, **arguments)
            else:
                result = live.update_mv_song(repo_root, region=region, log=job.log, **arguments)
        _clear_late_cancel(job)
    changed = bool(result.get("changed", True))
    restart = _restart_state(session, is_managed, changed)
    if restart in ("done", "pending"):
        progress.stage("restart")
    described = result["song"]
    job.emit({"type": "mv-song", "mode": mode, "song": described, "changed": changed, "parts": result.get("parts", []),
              "restart": restart, "warnings": result.get("warnings", []), "managed": is_managed})
    job.progress(len(progress.stages), len(progress.stages))
    if not changed:
        return NO_CHANGES
    message = REGISTERED if mode == "new" else UPDATED
    return message.replace("{title}", described["title"]).replace("{id}", str(described["liveId"]))


def run_remove(job, repo_root, request):
    """Job body of POST /api/mv-studio/songs/remove-job: always stops the game server first."""
    try:
        with ExitStack() as stack:
            lifecycle = _lifecycle(stack, job)
            live = store()
            is_managed = managed()
            progress = _Progress(job, ["check", "stop", "remove"])
            progress.stage("check")
            song = live.describe_mv_song(repo_root, region=request["region"], live_id=request["liveId"])
            progress.check()
            progress.stage("stop")
            with _server_session(job, stop=True, restart=is_managed) as session:
                progress.stage("remove")
                with _guard(Path(repo_root)):
                    result = live.remove_mv_song(repo_root, region=request["region"], live_id=request["liveId"],
                                                 review_token=request["reviewToken"], log=job.log)
                _clear_late_cancel(job)
            restart = "stopped" if not is_managed else _restart_state(session, True, True)
            if restart in ("done", "pending"):
                progress.stage("restart")
            job.emit({"type": "mv-song-removed", "liveId": request["liveId"], "region": request["region"],
                      "title": song["title"], "restart": restart, "warnings": result.get("warnings", []),
                      "backup": result.get("backup"), "managed": is_managed})
            job.progress(len(progress.stages), len(progress.stages))
            if lifecycle is not None:
                lifecycle.successful = not job.should_stop()
            return REMOVED.replace("{title}", song["title"]).replace("{id}", str(request["liveId"]))
    except _Cancelled:
        return REMOVE_CANCELLED
    finally:
        _release()


def reserve():
    """Take the one-job-at-a-time slot; False when a registration or removal is already running."""
    return _ACTIVE.acquire(blocking=False)


def _release():
    try:
        _ACTIVE.release()
    except RuntimeError:
        pass


def release():
    """Give the slot back when a reserved job could not start."""
    _release()
