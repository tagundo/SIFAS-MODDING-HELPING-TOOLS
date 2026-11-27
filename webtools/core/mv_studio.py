"""Shared MV workbench project, preview assets, and native timeline copies."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import struct
import tempfile
import threading
import time
from urllib.parse import quote
import zipfile

from webtools import filebrowser
from . import game_models, model_viewer, transient_failures, viewer_archive
from .member_identity import member_from_native
from .sukusta import default_sukusta_dir
from .viewer_cache import game_models_dir, viewer_cache_root


PROJECT_BYTES = 16 * 1024 * 1024
PACKAGE_BYTES = 384 * 1024 * 1024
MEDIA_BYTES = 96 * 1024 * 1024
MAX_MEDIA = 48
_MEDIA = {"glb": "model/gltf-binary", "wav": "audio/wav", "ogg": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
          "flac": "audio/flac"}
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}\.(?:glb|wav|ogg|mp3|m4a|flac)\Z")
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
_NATIVE_DIGEST = re.compile(rb"[a-f0-9]{64}\Z")
_MEDIA_URL = "/api/mv-studio/media/"
_UNITY_SUFFIXES = {".unity", ".unity3d", ".assets", ".bundle", ".bytes"}
_PREVIEW_KIND = {"stage", "effect", "props", "background", "performer", "outfit"}
# LiveCoreMemberManager.MemberMax and LiveConstants.MaxMember: an MV has up to 12 performers.
_MEMBER_MAX = 12
_ROLES = _PREVIEW_KIND | {"audio", "timeline", "camera", "lighting", "display", "dance", "mouth", "eyes", "gaze", "cheek", "shader", "crowd", "split", "other"}
_IMPORT = threading.BoundedSemaphore(1)
_IMPORT_WAIT_SECONDS = 5
_ACTOR_PREVIEWS = OrderedDict()
_STAGE_PREVIEWS = OrderedDict()
_ACTOR_PREVIEW_ENTRIES = 24
_ACTOR_PREVIEW_METADATA_BYTES = 4 * 1024 * 1024
# Conversion warnings that follow from the bundle's own content (never from a
# decoder timeout or a busy worker), so a restart-safe receipt may repeat them.
_STRUCTURAL_WARNINGS = {"linked_mesh_missing", "linked_texture_missing", "stage_hidden_transform"}


def _root():
    return game_models._safe_directory(viewer_cache_root() / "mv-studio")


def _write(path, data):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".mv-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


def _media_name(data, extension):
    return hashlib.sha256(data).hexdigest()[:32] + "." + extension


def _media(data, extension):
    if extension not in _MEDIA or not 0 < len(data) <= MEDIA_BYTES:
        raise ValueError("The stage preview or soundtrack exceeds the supported size.")
    valid = {"glb": lambda: data[:4] == b"glTF", "wav": lambda: data[:4] == b"RIFF" and data[8:12] == b"WAVE",
             "ogg": lambda: data[:4] == b"OggS", "mp3": lambda: data[:3] == b"ID3" or data[:1] == b"\xff",
             "m4a": lambda: data[4:8] == b"ftyp", "flac": lambda: data[:4] == b"fLaC"}
    if not valid[extension]():
        raise ValueError("The preview asset does not have the expected file format.")
    if extension == "glb":
        _verify_glb(data)
    name = _media_name(data, extension)
    directory = game_models._safe_directory(_root() / "media")
    _write(directory / name, data)
    return _MEDIA_URL + name


def _verify_glb(data):
    # A local project may reference embedded buffers and images only. A model
    # must never turn the loader into a request to arbitrary local/remote URLs.
    if len(data) < 20:
        raise ValueError("The stage GLB is truncated.")
    _, version, length, size, kind = struct.unpack_from("<4sIII4s", data)
    if version != 2 or length != len(data) or kind != b"JSON" or not 0 < size <= min(len(data) - 20, PROJECT_BYTES):
        raise ValueError("The stage has an invalid GLB header.")
    document = json.loads(data[20:20 + size])
    if not isinstance(document, dict):
        raise ValueError("The stage GLB does not contain a model.")
    for field in ("images", "buffers"):
        items = document.get(field, [])
        if not isinstance(items, list):
            raise ValueError("The stage GLB has invalid images or buffers.")
        for item in items:
            uri = item.get("uri", "") if isinstance(item, dict) else None
            if not isinstance(uri, str) or uri and not re.match(r"data:(?:image/(?:png|jpeg|webp)|application/(?:octet-stream|gltf-buffer));base64,", uri):
                raise ValueError("The stage GLB needs all images and buffers embedded.")


def media(name):
    if not _MEDIA_NAME.fullmatch(name):
        raise FileNotFoundError("The MV preview asset is unavailable.")
    directory = _root() / "media"
    path = directory / name
    if path.resolve() != path or not path.is_file() or not 0 < path.stat().st_size <= MEDIA_BYTES:
        raise FileNotFoundError("The MV preview asset is unavailable.")
    return path, _MEDIA[path.suffix[1:]]


def _blank(name, source=None):
    return {"version": 1, "name": name, "duration": 0, "source": source or {"kind": "mod"},
            "stage": None, "performers": [], "soundtrack": None, "assets": [], "tracks": [],
            "quality": {"modes": [], "options": [], "mode": None, "values": {}}, "warnings": []}


def _read_native_file(path, maximum):
    try:
        if path.resolve() != path or not path.is_file() or not 0 < path.stat().st_size <= maximum:
            return None
        with path.open("rb") as source:
            raw = source.read(maximum + 1)
    except (OSError, RuntimeError):
        return None
    return raw if 0 < len(raw) <= maximum else None


def _register(project, native=None):
    token = secrets.token_hex(16)
    if native is not None:
        if not 0 < len(native) <= MEDIA_BYTES:
            raise ValueError("The original MV timeline exceeds the supported size.")
        directory = game_models._safe_directory(_root() / "native")
        blobs = game_models._safe_directory(directory / "blobs")
        digest = hashlib.sha256(native).hexdigest()
        blob = blobs / (digest + ".unity")
        try:
            current = (blob.resolve() == blob and blob.is_file() and blob.stat().st_size == len(native)
                       and game_models._sha(blob) == digest)
        except (OSError, RuntimeError):
            current = False
        if not current:
            _write(blob, native)
        # Each open still receives a separate token, while the original bytes
        # are only written once. Publish the token after the source is ready.
        _write(directory / (token + ".sha256"), digest.encode("ascii"))
    project["token"] = token
    project["nativeTimeline"] = native is not None
    return project


def _native(project):
    token = project.get("token")
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None
    directory = _root() / "native"
    legacy = _read_native_file(directory / (token + ".unity"), MEDIA_BYTES)
    if legacy is not None:
        return legacy
    digest = _read_native_file(directory / (token + ".sha256"), 64)
    if digest is None or not _NATIVE_DIGEST.fullmatch(digest):
        return None
    source = _read_native_file(directory / "blobs" / (digest.decode("ascii") + ".unity"), MEDIA_BYTES)
    return source if source is not None and hashlib.sha256(source).hexdigest().encode("ascii") == digest else None


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("Choose an MV project or an asset file.")
    selected = Path(value).expanduser()
    path = selected.resolve()
    if selected.is_symlink() or not filebrowser.is_within_allowed(path):
        raise PermissionError("The selected MV file is outside the allowed folders.")
    if not path.is_file() or not 0 < path.stat().st_size <= PACKAGE_BYTES:
        raise ValueError("The selected MV file is empty or exceeds the import limit.")
    return path


def _preview(path, *, performer=False, motions=(), companions=(), reuse=False, stage_bindings=(),
             native_stage_effect=False, attach="", prop_skeleton=(), warnings=None, reused=None, store=None):
    """Return (media URL, rig) of a model preview; ``warnings`` receives its conversion warnings.

    ``attach`` is the performer's m_suit_attach key and ``prop_skeleton`` the
    member's merged prop skeleton (mv_studio_props.skeleton). A stage preview
    is reused from the in-memory cache only when it converted without
    warnings, and from ``store`` (mv_studio_import_cache) only when its
    warnings are structural; the receipt then repeats them. ``reused`` (a
    list) receives True when the result came from a cache. Neither cache keeps
    a conversion during which a failure that may not repeat was noted
    (transient_failures).
    """
    models = [path, *companions]
    key = None
    cache = _ACTOR_PREVIEWS if performer else _STAGE_PREVIEWS
    if reuse and ((performer and motions and companions) or (not performer and not motions and not companions)):
        # Game stage previews depend on one exact input. Performer previews
        # also need explicit companions to rule out local face discovery.
        key = (_root(), tuple((item.name, game_models._sha(item)) for item in models),
               tuple((item.name, game_models._sha(item)) for item in motions), tuple(stage_bindings),
               native_stage_effect) + ((attach,) if attach else ()) + (
            (json.dumps(list(prop_skeleton), sort_keys=True),) if prop_skeleton else ())
        cached = model_viewer._conversion_get(cache, key, time.monotonic() + model_viewer.BUILD_SECONDS)
        if cached is not None:
            name, rig = json.loads(cached)
            try:
                previous, _ = media(name)
                if game_models._sha(previous)[:32] == previous.stem:
                    if reused is not None:
                        reused.append(True)
                    return _MEDIA_URL + name, rig
            except OSError:
                pass
    receipt = None
    if key is not None and store is not None and not performer:
        try:
            receipt = store.key("preview", str(key[0]), [list(item) for item in key[1]], [list(item) for item in key[2]],
                                list(key[3]), key[4])
        except (TypeError, ValueError):
            receipt = None
        saved = store.get(receipt) if receipt is not None else None
        if saved is not None:
            if warnings is not None:
                warnings.extend(saved["warnings"])
            if reused is not None:
                reused.append(True)
            return _MEDIA_URL + saved["name"], saved["rig"]
    watch = transient_failures.Watch()
    prepared = model_viewer.prepare(list(map(str, models)), rigged=performer,
        face_context={"enabled": performer and not companions, "allow_download": False,
                      "_mv_stage": not performer, "_mv_authored_motion": performer and bool(motions),
                      "_mv_stage_motion_bindings": stage_bindings, "_mv_performer": performer,
                      "_mv_native_stage_effect": native_stage_effect,
                      **({"_mv_attach_key": attach} if performer and attach else {}),
                      **({"_mv_prop_skeleton": list(prop_skeleton)} if performer and prop_skeleton else {})},
        motion_paths=list(map(str, motions)) or None)
    payload = model_viewer.get_model(prepared["id"])
    if payload is None:
        raise ValueError("The 3D preview expired. Reopen the asset.")
    if warnings is not None:
        warnings.extend(item for item in prepared.get("warnings") or () if isinstance(item, dict))
    url, rig = _media(payload, "glb"), prepared.get("rig", {}) if performer else {}
    if rig.get("bones"):
        from . import viewer_physics

        try:
            physics = viewer_physics.catalogue_preview(models, rig["bones"])
            if physics.get("available"):
                rig = {**rig, "physics": physics}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Optional source physics is independent of the usable body model.
            transient_failures.note_if_environmental(error)
        from . import model_constraints

        try:
            constraints = model_constraints.catalogue_preview(models, rig["bones"])
            if constraints.get("available"):
                rig = {**rig, "constraints": constraints}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Unity constraints are optional rig data, like source physics.
            transient_failures.note_if_environmental(error)
    if key is not None and watch.clean:
        if performer and rig.get("available") and any(clip.get("bindingComplete") for clip in rig.get("clips", [])):
            model_viewer._conversion_put(
                cache, key, json.dumps([url.removeprefix(_MEDIA_URL), rig]).encode(),
                max_bytes=_ACTOR_PREVIEW_METADATA_BYTES, max_entries=_ACTOR_PREVIEW_ENTRIES,
            )
        elif not performer and not prepared.get("warnings"):
            model_viewer._conversion_put(cache, key, json.dumps([url.removeprefix(_MEDIA_URL), rig]).encode(),
                                         max_bytes=16 * 1024, max_entries=32)
    if receipt is not None and watch.clean:
        converted = list(prepared.get("warnings") or ())
        if all(isinstance(item, dict) and item.get("code") in _STRUCTURAL_WARNINGS for item in converted):
            store.put(receipt, {"name": url.removeprefix(_MEDIA_URL), "rig": rig, "warnings": converted})
    return url, rig


def _preview_file(path, kind, *, stage_bindings=()):
    if path.suffix.lower() == ".glb":
        return _media(path.read_bytes(), "glb"), {}
    return _preview(path, performer=kind in {"performer", "outfit"}, stage_bindings=stage_bindings,
                    native_stage_effect=kind == "effect" and bool(stage_bindings))


def _song_audio(path, offset=0):
    extension = path.suffix.lower().lstrip(".")
    info = {"offset": offset}
    if extension == "wav":
        import wave
        try:
            with wave.open(str(path), "rb") as audio:
                info["duration"] = audio.getnframes() / audio.getframerate()
        except (EOFError, wave.Error) as error:
            raise ValueError("The selected WAV file is invalid.") from error
    info["url"] = _media(path.read_bytes(), extension)
    return info


def _asset(path, kind, *, stage_bindings=()):
    if path.stat().st_size > MEDIA_BYTES:
        raise ValueError("The file exceeds the individual MV asset size limit.")
    label = path.name
    row = {"id": secrets.token_hex(8), "kind": kind, "label": label, "path": label, "status": "loaded"}
    result = {"asset": row}
    if kind == "audio":
        result["soundtrack"] = _song_audio(path)
        row["previewUrl"] = result["soundtrack"]["url"]
    elif kind in _PREVIEW_KIND:
        url, rig = _preview_file(path, kind, stage_bindings=stage_bindings)
        row["previewUrl"] = url
        if kind == "stage":
            result["stage"] = {"glb": url, "label": label}
        elif kind in {"performer", "outfit"}:
            result["performer"] = {"id": row["id"], "label": label, "glb": url, "rig": rig,
                                   "transform": {"position": [0, 0, 0]}}
    else:
        raise ValueError("Open a timeline with Open mod. Choose a model or an audio file for an asset override.")
    return result


def import_asset(path, kind):
    if kind == "effects":
        kind = "effect"
    if not isinstance(kind, str) or kind not in _ROLES:
        raise ValueError("Choose the kind of MV asset to replace.")
    return _asset(_path(path), kind)


def _timeline(path, store=None, reused=None):
    """(raw bytes, parsed timeline); ``store`` keeps restart-safe receipts of the parse."""
    from . import mv_studio_import_cache, mv_studio_timeline
    raw = path.read_bytes()
    receipt = store.key("timeline", mv_studio_import_cache.digest(raw), path.name) if store is not None else None
    parsed = store.get(receipt) if receipt is not None else None
    hit = parsed is not None and bool(parsed.get("tracks"))
    if reused is not None:
        reused.append(hit)
    if hit:
        return raw, parsed
    watch = transient_failures.Watch()
    parsed = mv_studio_timeline.parse_timeline(raw, path.name, preview_split=True, preview_stage_motion=True,
                                               preview_member_shafts=True, preview_stage_title=True,
                                               preview_stage_particles=True, preview_stage_ribbons=True,
                                               preview_stage_spotlight=True, preview_stage_butterfly=True,
                                               preview_stage_rain=True, preview_stage_leaves=True, preview_stage_momiji=True,
                                               preview_stage_confetti=True, preview_stage_glow=True, preview_stage_lens=True,
                                               preview_stage_speed_back=True,
                                               preview_stage_display_lights=True, preview_stage_falling_effects=True,
                                               preview_stage_break=True, preview_stage_finale_floor=True,
                                               preview_stage_sparks_a=True, preview_stage_sparks_b=True,
                                               preview_stage_sparks_roop=True, preview_particle_systems=True,
                                               preview_control_prefabs=True)
    if not parsed.get("tracks"):
        raise ValueError("This file does not contain an original live timeline.")
    # A texture or template given up for want of time, memory or a working decoder
    # is not a property of these bytes: such a parse is used but never kept.
    if receipt is not None and watch.clean:
        store.put(receipt, parsed)
    return raw, parsed


def _motion(timeline, dependencies, facial, directory, position, owner, tracks, deadline):
    from . import game_motion_selection
    selected = game_motion_selection.select(timeline, dependencies, performer=position, deadline=deadline)
    facial_selection, facial_entries = game_motion_selection.facial_banks(facial, deadline=deadline)
    selected["selected"].update(facial_selection["selected"])
    directory.mkdir()
    files, segments, sources, identities = game_motion_selection.write_selected(selected, directory)
    facial_clips = []
    for item in facial_entries:
        key = item["key"]
        facial_clips.append({name: value for name, value in item.items() if name != "key"} | (identities[key] if key is not None else {}))
    native_events = {}
    for track in tracks:
        if track["kind"] == "dance":
            for event in track["events"]:
                key = ("/" + track["label"], event["start"], event["duration"])
                native_events.setdefault(key, []).append((track["id"], event["id"]))
    for segment in segments:
        matches = native_events.get((segment["track"], segment["start"], segment["duration"]), ())
        if len(matches) == 1:
            segment["nativeTrackId"], segment["nativeEventId"] = matches[0]
    descriptor = {"version": 2, "category": "mv", "performerPosition": position, "targetCharacter": owner,
                  "clipSources": sources, "bodySegments": segments, "facialClips": facial_clips}
    return [item["path"] for item in files], descriptor


def _facial(timeline, descriptor, position, tracks, head):
    """Add the facial events once the loaded head is known (see member_head)."""
    from . import game_motion_timeline
    native_face = game_motion_timeline.parse_timeline(str(timeline), position, segments=descriptor["bodySegments"],
                                                      face_dots=(head or {}).get("faceDots"))
    facial_events = {}
    for track in tracks:
        if track["kind"] not in {"mouth", "eyes", "gaze", "cheek"} or f"Member{position}" not in track["label"].split("/"):
            continue
        for event in track["events"]:
            key = (track["kind"], event["start"], event["duration"], event["label"][:128])
            facial_events.setdefault(key, []).append(event["id"])
    for event in native_face["events"]:
        matches = facial_events.get((event["kind"], event["start"], event["duration"], event["label"]), ())
        if len(matches) == 1:
            event["nativeEventId"] = matches[0]
    return {**descriptor, "facial": native_face}


def _cast_in_timeline_order(performers, tracks, clip_names=None):
    # The AnimationClip a slot plays identifies its member. m_DisplayName is
    # only a fallback: in 12035/12036 it carries the other Mia/Lanzhu code.
    # A name without a chNNNN code identifies nobody, so the next one is tried.
    clip_names = clip_names or {}
    members = {}
    for track in tracks:
        if track["kind"] != "dance" or not (slot := re.fullmatch(r"/EntryPoint/Live/Members/Member(\d+)/Model", track.get("binding", ""))):
            continue
        for event in track["events"]:
            for name in (clip_names.get(event.get("id")), event["values"].get("animationName"), event.get("label")):
                identity = re.match(r"ch(\d{4})(?:_|$)", name) if isinstance(name, str) else None
                if identity:
                    members.setdefault(int(slot[1]), set()).add(member_from_native(int(identity[1])))
                    break
    latest = {performer["memberId"]: performer for performer in performers}
    positions = {performer["position"] for performer in performers}
    if set(members) != positions or any(len(ids) != 1 for ids in members.values()):
        return performers
    assigned = {slot: next(iter(ids)) for slot, ids in members.items()}
    if len(set(assigned.values())) != len(performers) or set(assigned.values()) != set(latest):
        return performers
    return [{**latest[assigned[slot]], "position": slot} for slot in sorted(assigned)]


def _stage_snapshot(project, assets, performers):
    # The overview uses its own camera and shows stage effects at time zero.
    # Keep active events in order so overlaps resolve as in the full renderer.
    effects_at_start = []
    stage_motion = project.get("stageMotion") or {}
    motion_at_start = {"clips": {}, "mix": {}, "activations": {}, "quality": {}}
    for track in project["tracks"]:
        screen = track.get("nativeClass") in {"LiveColoringTrack", "LiveDisplayTrack"}
        emissive = track.get("nativeClass") == "LiveStageEmissiveTrack"
        motion = track.get("nativeClass") == "AnimationTrack" and track.get("binding") in stage_motion.get("bindings", ())
        activation_ids = stage_motion.get("activations", {}).get(track.get("id"))
        if track.get("muted") or (track["kind"] not in {"lighting", "crowd"} and not screen and not motion and activation_ids is None):
            continue
        events = []
        for event in track["events"]:
            start, end = event["start"], event["start"] + event["duration"]
            timing = stage_motion["mix"].get(event["id"]) if motion else None
            if start <= 0 <= end or ((timing is not None or emissive) and start > 0
                    and event["values"].get("preExtrapolationMode") in (1, 2, 3, 4)
                    and ((timing or {}).get("preInfinite") or (event["values"].get("preExtrapolationTime") or 0) >= start)):
                events.append(event)
        # An enabled emissive mixer writes zero even while no clips are active.
        if events or emissive or screen or motion or activation_ids is not None:
            effects_at_start.append(dict(track, events=events))
        if activation_ids is not None:
            motion_at_start["activations"][track["id"]] = [event["id"] for event in events if event["id"] in activation_ids]
        if motion:
            gate = stage_motion.get("quality", {}).get(track["id"])
            if gate is not None:
                motion_at_start["quality"][track["id"]] = gate
            for event in events:
                asset = event["values"].get("animation")
                if asset in stage_motion["clips"] and event["id"] in stage_motion["mix"]:
                    motion_at_start["clips"][asset] = stage_motion["clips"][asset]
                    motion_at_start["mix"][event["id"]] = stage_motion["mix"][event["id"]]
    # The preview consumer can retain this copy without sharing edit state.
    stage = dict(project["stage"])
    colors = {str(entry["position"]): entry["themeColor"] for entry in performers if "themeColor" in entry}
    if colors:
        stage["memberThemeColors"] = colors
    return deepcopy({
        "stage": stage,
        "source": {"kind": project["source"]["kind"]},
        "duration": project["duration"],
        "quality": project["quality"],
        "assets": [asset for asset in assets if asset["kind"] in {"effect", "props", "background"} and asset.get("previewUrl")],
        "tracks": effects_at_start,
        **({"stageMotion": motion_at_start} if any(motion_at_start.values()) else {}),
    })


def _descriptor_bytes(*descriptors):
    return sum(item["size"] for item in descriptors
               if isinstance(item, dict) and type(item.get("size")) is int and item.get("available") is not False)


def _progress_plan(selected):
    """The steps of this import, in order, for the progress plan."""
    stage = selected.get("stage") or {}
    audio = selected.get("audio") or {}
    performers = selected.get("performers", [])[:_MEMBER_MAX]
    steps = [{"id": "resolve"},
             {"id": "timeline", "bytes": _descriptor_bytes(selected.get("timeline"), *selected.get("choreography", []))},
             {"id": "stage", "bytes": _descriptor_bytes(selected.get("stageModel") or stage.get("model"))},
             {"id": "effect", "bytes": _descriptor_bytes(selected.get("stageEffect") or stage.get("effect"))}]
    if stage.get("props"):
        steps.append({"id": "props", "bytes": _descriptor_bytes(stage["props"])})
    for index, entry in enumerate(performers, 1):
        steps.append({"id": "member", "index": index, "of": len(performers),
                      "bytes": _descriptor_bytes(entry.get("model"), *entry.get("companions", []), *entry.get("facial", []))})
    if audio.get("cue") and audio.get("acb"):
        steps.append({"id": "audio", "bytes": _descriptor_bytes(audio["acb"], audio.get("awb"))})
    steps.append({"id": "finish"})
    return steps, len(performers), sum(step.get("bytes", 0) for step in steps)


def load_game(repo_root, *, region, platform, live_id, asset_id, language, download=False, on_stage=None, costumes=None,
              deck=None, on_progress=None, later=None, pack=None):
    """Import the complete project, optionally publishing its renderable stage first.

    Performers follow the client's MV deck chain (mv_studio_suits); `deck` gives the
    player state (deck type, local Elichika player). `costumes` ({position: suit id or
    {"suit", "viewStatus"}}) dresses members in explicit suits instead, e.g. the suits a
    recorded game performance wore. `on_progress` receives the events that
    mv_studio_progress describes and may raise its ImportCancelled.

    The restart-safe receipts of the timeline, clips, stage and soundtrack are
    written after the project is complete: given a list `later`, as a callable
    appended to it for the caller to run once the project has been delivered,
    otherwise before this returns. An import that fails or is cancelled
    writes none of them.

    `pack` (a token from mv_studio_pack.open_pack) loads the MV with an opened MV timeline
    pack's timeline instead of the catalogued one; the project records it in source.pack."""
    from . import (mv_studio_actor_cache, mv_studio_game, mv_studio_import_cache, mv_studio_progress, mv_studio_quality,
                   mv_studio_suits)

    if type(download) is not bool:
        raise ValueError("Choose whether to download missing game assets.")
    if on_stage is not None and not callable(on_stage):
        raise TypeError("The stage preview callback must be callable.")
    if on_progress is not None and not callable(on_progress):
        raise TypeError("The progress callback must be callable.")
    if later is not None and type(later) is not list:
        raise TypeError("Deferred receipt writes need a list.")
    pack_raw = pack_info = None
    if pack is not None:
        from . import mv_studio_pack
        pack_raw, pack_info = mv_studio_pack.staged(pack, platform)
    progress = mv_studio_progress.Progress(on_progress) if on_progress is not None else mv_studio_progress.SILENT
    # An import whose client left stops at its next cancellation point (normally within a
    # fraction of a second). A new import, usually the same person choosing again, waits
    # for that instead of being refused.
    if not _IMPORT.acquire(timeout=_IMPORT_WAIT_SECONDS):
        raise ValueError("An MV is already being prepared. Try again when it finishes.")
    previous_progress = mv_studio_progress.activate(progress)
    previous_textures = model_viewer.set_texture_store(None)
    try:
        # Decoded textures are reused across MVs: a costume's are the same in every song.
        model_viewer.set_texture_store(mv_studio_import_cache.open_texture_cache(media))
        selected = mv_studio_game.resolve(repo_root, region=region, platform=platform,
                                          live_id=live_id, asset_id=asset_id, language=language, costumes=costumes,
                                          deck=deck)
        steps, members, total_bytes = _progress_plan(selected)
        progress.plan(steps, members, total_bytes)
        progress.state("resolve", "done")
        source = {"kind": "game", "region": selected["region"], "platform": selected["platform"],
                  "liveId": selected["liveId"], "assetId": selected["assetId"], "mvOnly": selected.get("mvOnly", False),
                  "registered": selected.get("registered", False),
                  # Which registered song this is (its revision and base): the store reuses removed songs' IDs.
                  **({"registeredSong": selected["registeredSong"]} if selected.get("registeredSong") else {}),
                  # The timeline key this import read, and the MV Studio version it was when MV Studio had
                  # applied a timeline to this MV: "Apply only the edits" merges relative to that version.
                  **({"timelineKey": selected["timelineKey"]} if isinstance(selected.get("timelineKey"), str) else {}),
                  **({"timelineOverride": selected["timelineOverride"]} if selected.get("timelineOverride") else {}),
                  # An opened MV timeline pack: its timeline replaces the catalogued one (a "mod" of this MV).
                  **({"timelineKey": "pack:" + pack, "pack": pack_info} if pack_info is not None else {}),
                  # The deck tab / local player and every position's suit source, so a saved
                  # project or a frame capture says which player state dressed the members.
                  **mv_studio_suits.provenance(selected.get("deck"), selected.get("performers"))}
        project = _blank(selected["name"], source)
        project["quality"] = mv_studio_quality.read_quality(repo_root, region=source["region"], language=language,
                                                             quality_set=selected.get("qualitySet"))
        deadline = time.monotonic() + 210
        warnings = project["warnings"]
        # Receipts are only written once the whole import has succeeded (flush below).
        receipts = mv_studio_import_cache.open_cache(media, pending=[])
        from .game_motion_selection import shared_reads
        # Every member's dance selection reads the same timeline and choreography bundles.
        with tempfile.TemporaryDirectory(prefix="import-", dir=_root()) as name, shared_reads():
            directory = Path(name)
            local, rows = {}, {}
            from . import mv_studio_external_clips
            read_asset = mv_studio_external_clips.SharedReads(
                lambda descriptor: mv_studio_game.load_asset(repo_root, descriptor, download=download, deadline=deadline))

            def describe(descriptor, kind, label=None):
                if not descriptor:
                    return None
                asset = str(descriptor.get("asset", descriptor.get("pack_name", "")))
                identity = (kind, descriptor.get("table"), asset)
                if identity not in rows:
                    rows[identity] = {"id": str(len(rows) + 1), "kind": kind, "label": label or descriptor.get("role") or asset,
                                      "path": asset, "status": "available" if descriptor.get("available") else "missing"}
                return rows[identity]

            def load(descriptor, kind, label=None):
                row = describe(descriptor, kind, label)
                if row is None:
                    return None, None
                if row["id"] not in local:
                    try:
                        raw = read_asset(descriptor)
                        progress.read(len(raw or b""))
                        if not raw:
                            row["status"] = "missing"
                            return row, None
                        asset_path = directory / ("game-" + row["id"] + ".unity")
                        asset_path.write_bytes(raw)
                        local[row["id"]] = asset_path
                        row["status"] = "loaded"
                    except (ValueError, OSError) as error:
                        row["status"] = "unavailable"
                        warnings.append(f"{row['label']}: {error}")
                        return row, None
                return row, local[row["id"]]

            progress.state("timeline", "start")
            if pack_raw is not None:
                timeline = directory / "pack-timeline.unity"
                timeline.write_bytes(pack_raw)
            else:
                timeline_row, timeline = load(selected.get("timeline"), "timeline", "Live timeline")
            if timeline is None:
                raise ValueError("The original MV timeline pack is missing. Download its missing assets or choose a local mod file.")
            timeline_reused = []
            native, parsed = (_timeline(timeline) if receipts is None else
                              _timeline(timeline, store=receipts, reused=timeline_reused))
            project.update({field: parsed[field] for field in
                            ("duration", "tracks", "splitScreen", "stageMotion", "stageTitle", "stageParticles",
                             "stageRibbons", "stageSpotlight", "stageButterfly", "stageRain", "stageLeaves", "stageMomiji",
                             "stageConfetti", "stageGlow", "stageLensFlare", "stageSpeedBack",
                             "stageDisplayLights", "stageFallingEffects", "stageBreak", "stageFinaleFloor",
                             "stageSparksA", "stageSparksB", "stageSparksRoop", "stageParticleSystems",
                             "stageControlPrefabs", "controlCoverage")
                            if field in parsed})
            warnings.extend(parsed.get("warnings", []))
            original_cast = selected.get("performers", [])[:_MEMBER_MAX]
            # Dance clips live in the timeline's choreography packs (exact CAB/PathID).
            clip_names = mv_studio_external_clips.apply(project, native, selected.get("choreography", []), read_asset, deadline,
                                                        cache=receipts, reused=timeline_reused)
            performers = _cast_in_timeline_order(original_cast, project["tracks"], clip_names)
            progress.state("timeline", "cached" if timeline_reused and all(timeline_reused) else "done")
            stage = selected.get("stage") or {}
            stage_row, stage_file = load(selected.get("stageModel") or stage.get("model"), "stage", stage.get("name") or "Stage model")
            effect_row, effect_file = load(selected.get("stageEffect") or stage.get("effect"), "effect", "Stage effects")
            from . import mv_studio_import_coverage
            shadow_gap = None
            for step, (row, preview_path) in zip(("stage", "effect"), ((stage_row, stage_file), (effect_row, effect_file))):
                if preview_path is None:
                    progress.state(step, "skipped")
                    continue
                progress.state(step, "start")
                try:
                    bindings = project.get("stageMotion", {}).get("bindings", ()) if row is effect_row else ()
                    converted, reused = [], []
                    row["previewUrl"], _ = _preview(preview_path, reuse=True, stage_bindings=bindings,
                                                    native_stage_effect=row is effect_row, warnings=converted,
                                                    reused=reused, store=receipts)
                    for item in converted:
                        if item.get("code") == "member_shadow_prefabs_unavailable":
                            warnings.append(f"{row['label']}: {item.get('message')}")
                            shadow_gap = mv_studio_import_coverage.SHADOW_PREFABS_UNAVAILABLE
                    progress.state(step, "cached" if reused else "done")
                except (ValueError, OSError) as error:
                    warnings.append(f"{row['label']}: {error}")
                    progress.state(step, "failed")
            if stage_row and stage_row.get("previewUrl"):
                project["stage"] = {"glb": stage_row["previewUrl"], "label": stage_row["label"], "sceneName": stage.get("sceneName")}
                colors = {str(entry["position"]): entry["themeColor"] for entry in original_cast if "themeColor" in entry}
                if colors:
                    project["stage"]["originalMemberThemeColors"] = colors
            else:
                warnings.append("The original stage model is unavailable for preview.")
            describe(stage.get("background"), "background", "2D stage background")
            describe(stage.get("thumbnail"), "other", "Stage thumbnail")
            from . import mv_studio_props
            prop_bindings = mv_studio_props.bindings(project["tracks"]) if stage.get("props") else []
            performer_prop = prop_bindings[0] if len(prop_bindings) == 1 else None
            # Why the timeline's performer prop tracks do not play, for the coverage report.
            prop_gap = (mv_studio_import_coverage.PROP_NO_BUNDLE if not stage.get("props") else
                        mv_studio_import_coverage.PROP_SEVERAL if len(prop_bindings) > 1 else None)
            if performer_prop is None and stage.get("props"):
                progress.state("props", "start")
                prop_row, prop_file = load(stage.get("props"), "props", "Stage props")
                prop_state = "skipped"
                if prop_file is not None:
                    try:
                        reused = []
                        prop_row["previewUrl"], _ = _preview(prop_file, reuse=True, reused=reused, store=receipts)
                        prop_state = "cached" if reused else "done"
                    except (ValueError, OSError) as error:
                        warnings.append(f"{prop_row['label']}: {error}")
                        prop_state = "failed"
                progress.state("props", prop_state)
            if on_stage is not None and project["stage"] is not None:
                on_stage(_stage_snapshot(project, rows.values(), performers))
            # Every member merges its own ske_ prop skeleton (whatever prop the
            # preview can draw), so its dance clips animate the prop nodes.
            prop_skeletons = {}
            if stage.get("props"):
                _, skeleton_file = load(stage.get("props"), "props", "Performer prop" if performer_prop else "Stage props")
                if skeleton_file is not None:
                    try:
                        prop_skeletons = mv_studio_props.skeleton(skeleton_file, deadline)
                    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
                        # An unreadable skeleton leaves the members without merged prop nodes.
                        warnings.append(f"Member prop skeleton: {error}")
            if performer_prop is not None:
                progress.state("props", "start")
                prop_row, prop_file = load(stage.get("props"), "props", "Performer prop")
                prop_gap = mv_studio_import_coverage.PROP_UNAVAILABLE
                if prop_file is None:
                    progress.state("props", "skipped")
                else:
                    try:
                        glb, attachment = mv_studio_props.preview(
                            prop_file, native, timeline.name, performer_prop, deadline,
                        )
                        prop_row.update(previewUrl=_media(glb, "glb"), attachment=attachment)
                        prop_gap = None
                        progress.state("props", "done")
                    except (ValueError, OSError) as error:
                        prop_row["status"] = "unavailable"
                        warnings.append(f"{prop_row['label']}: {error}")
                        prop_gap = mv_studio_import_coverage.PROP_PREVIEW_FAILED
                        progress.state("props", "failed")
            describe(selected.get("songBackground"), "background", "Song background")
            movie = selected.get("movie") or {}
            describe(movie.get("source"), "display", "MV screen video")
            describe(movie.get("background"), "background", "Video background")
            for item in selected.get("shaderDependencies", []):
                describe(item, "shader")
            for item in selected.get("dependencies", []):
                role = item.get("role", "other")
                describe(item, "dance" if role == "choreography" else role if role in _ROLES else "other")
            motion_files = []
            for item in selected.get("choreography", []):
                _, path = load(item, "dance")
                if path is not None and path != timeline:
                    motion_files.append(path)
            from . import viewer_physics_runtime

            actor_cache = mv_studio_actor_cache.open_cache((source["region"], source["platform"]), media)
            motion_inputs = actor_cache.inputs(native, motion_files) if actor_cache else None
            motion_physics = viewer_physics_runtime.motion_settings(repo_root=repo_root,
                record={"category": "mv", "region": source["region"], "live_id": source["liveId"]})
            project["motionPhysics"] = motion_physics
            for member_index, entry in enumerate(performers, 1):
                number = entry["position"]
                label = entry.get("memberName") or f"Member {number}"
                member_ids = {"index": member_index, "of": len(performers)}
                progress.state("member", "start", **member_ids, name=label)
                member_state = "skipped"
                _, model = load(entry.get("model"), "outfit", entry.get("costumeName") or label)
                # Position is a workbench starting pose until native rig
                # translations replace it. Never treat it as a stage bind.
                attach = entry.get("attachKey") or ""
                result = {"id": f"member-{number}", "position": number, "label": label,
                          "memberId": entry.get("memberId"), "costumeId": entry.get("costumeId"),
                          **{field: entry[field] for field in ("viewStatus", "suitSource", "costumes")
                             if field in entry}, **({"attachKey": attach} if attach else {}),
                          "transform": {"position": [0 if entry.get("isCenter") else ((-1 if number % 2 == 0 else 1) * ((number + 1) // 2)), 0, 0]}}
                if "themeColor" in entry:
                    result["themeColor"] = entry["themeColor"]
                if model is not None:
                    facial_files, companions = [], []
                    for descriptor in entry.get("companions", []):
                        _, companion = load(descriptor, "outfit", f"{label} face and model dependencies")
                        if companion is not None and companion != model:
                            companions.append(companion)
                    for descriptor in entry.get("facial", []):
                        _, facial_file = load(descriptor, "eyes", f"{label} facial clips")
                        if facial_file is not None:
                            facial_files.append(facial_file)
                    skeleton = prop_skeletons.get(number, ())
                    key = actor_cache.key(motion_inputs, number, result["memberId"], model, companions, facial_files,
                                          attach=attach, props=skeleton) if actor_cache else None
                    saved = actor_cache.get(key) if key is not None else None
                    if saved is not None:
                        name, rig, motion = saved
                        result.update(glb=_MEDIA_URL + name, rig=rig, motion=motion)
                        member_state = "cached"
                    else:
                        clips, motion = [], None
                        member_state = "failed"
                        watch = transient_failures.Watch()
                        try:
                            progress.phase("motion")
                            clips, motion = _motion(timeline, motion_files, facial_files, directory / f"actor-{number}", number,
                                                    result["memberId"], project["tracks"], deadline)
                        except (ValueError, OSError) as error:
                            transient_failures.note_if_environmental(error)
                            warnings.append(f"{label} choreography: {error}")
                        try:
                            url, rig = _preview(model, performer=True, motions=clips, companions=companions, reuse=True,
                                                attach=attach, prop_skeleton=skeleton)
                            if motion is not None:
                                try:
                                    motion = _facial(timeline, motion, number, project["tracks"], rig.get("memberHead"))
                                except (ValueError, OSError) as error:
                                    transient_failures.note_if_environmental(error)
                                    warnings.append(f"{label} facial timeline: {error}")
                            result.update(glb=url, rig=rig, motion=motion)
                            member_state = "done"
                            if key is not None and watch.clean:
                                actor_cache.put(key, url.removeprefix(_MEDIA_URL), rig, motion)
                        except (ValueError, OSError) as error:
                            warnings.append(f"{label}: {error}")
                    if result.get("motion") and result["rig"].get("clips"):
                        result["transform"]["position"] = [0, 0, 0]
                    catalog = result.get("rig", {}).get("physics")
                    if catalog:
                        if result.get("motion") is not None:
                            result["motion"] = {**result["motion"], "physics": motion_physics}
                        if catalog.get("native", {}).get("available") and type(result["costumeId"]) is int:
                            try:
                                flags = viewer_physics_runtime._source_settings(
                                    {"region": source["region"], "suit_id": result["costumeId"]}, repo_root)
                            except (OSError, ValueError, TypeError, sqlite3.Error):
                                flags = None
                            if flags:
                                sources = sorted({manager["sourceIndex"] for manager in catalog["managers"]})
                                runtime = {"profile": "sifas-3.12.0", "sources": [
                                    {"sourceIndex": index, "known": True, "skirtsafeDisable": flags["default"],
                                     "suitId": result["costumeId"], "region": source["region"]} for index in sources]}
                                result["rig"] = {**result["rig"], "physics": {**catalog, "native": {
                                    **catalog["native"], "runtime": runtime}}}
                project["performers"].append(result)
                progress.state("member", member_state, **member_ids)
            audio = selected.get("audio") or {}
            for role in ("acb", "awb"):
                describe((audio.get("chorus") or {}).get(role), "audio", f"Chorus {role.upper()}")
            if audio.get("cue") and audio.get("acb"):
                progress.state("audio", "start")
                audio_saved = None
                try:
                    from . import cri_audio_decode
                    _, acb = load(audio["acb"], "audio", "Soundtrack cue bank")
                    _, awb = load(audio.get("awb"), "audio", "Soundtrack wave bank")
                    cue_bank = acb.read_bytes() if acb else None
                    if cue_bank is not None and project["stage"] is not None and any(
                            track.get("nativeClass") == "LivePenlightTrack" for track in project["tracks"]):
                        try:
                            beat = cri_audio_decode.inspect_beat_sync(cue_bank, audio["cue"])
                            if beat is not None:
                                project["stage"]["beatSync"] = beat
                        except cri_audio_decode.AudioDecodeError:
                            # An unreadable optional timing table does not
                            # prevent decoding the same cue's waveform.
                            pass
                    if acb and (awb or not audio.get("awb")):
                        wave_bank = awb.read_bytes() if awb else None
                        receipt = receipts.key("audio", mv_studio_import_cache.digest(cue_bank),
                                               wave_bank and mv_studio_import_cache.digest(wave_bank),
                                               audio["cue"]) if receipts is not None else None
                        audio_saved = receipts.get(receipt) if receipt is not None else None
                        if audio_saved is not None:
                            project["soundtrack"] = audio_saved
                        else:
                            decoded = directory / "soundtrack.wav"
                            watch = transient_failures.Watch()
                            cri_audio_decode.decode_cue(cue_bank, wave_bank, audio["cue"], decoded)
                            # The base song's own cue: registration keeps it unless the offset moves it.
                            project["soundtrack"] = {**_song_audio(decoded), "origin": "game"}
                            if receipt is not None and watch.clean:
                                receipts.put(receipt, project["soundtrack"])
                        project["duration"] = max(project["duration"], project["soundtrack"]["duration"])
                except (ValueError, OSError) as error:
                    warnings.append(f"Soundtrack: {error}")
                progress.state("audio", "failed" if project["soundtrack"] is None else "cached" if audio_saved is not None else "done")
            if audio.get("cue") and project["soundtrack"] is None:
                warnings.append("The original soundtrack is unavailable for preview.")
            warnings.extend(f"{item['role']}: {item['reason']}" if isinstance(item, dict) else str(item)
                            for item in selected.get("missing", []))
            project["assets"] = list(rows.values())
            # After the assets: only an attached performer prop plays its tracks.
            mv_studio_import_coverage.apply(project, prop_gap, shadow_gap)
        with progress.step("finish"):
            result = _register(project, native)
        if receipts is not None:
            if later is None:
                receipts.flush()
            else:
                later.append(receipts.flush)
        return result
    finally:
        model_viewer.set_texture_store(previous_textures)
        mv_studio_progress.restore(previous_progress)
        _IMPORT.release()


def _document(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("This file is not a supported 3D MV project.")
    if not isinstance(value.get("name"), str) or len(value["name"]) > 160:
        raise ValueError("Enter a valid MV project name.")
    duration = value.get("duration")
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 3600:
        raise ValueError("The MV project has an invalid duration.")
    counts = {"tracks": 512, "assets": 256, "performers": _MEMBER_MAX, "warnings": 1024}
    for field, maximum in counts.items():
        items = value.get(field)
        if not isinstance(items, list) or len(items) > maximum:
            raise ValueError("The MV project has too many or invalid " + field + ".")
        if field in {"tracks", "assets", "performers"} and any(not isinstance(row, dict) for row in items):
            raise ValueError("The MV project contains invalid " + field + ".")
    track_ids, events = set(), 0
    for track in value["tracks"]:
        if (not isinstance(track.get("id"), str) or track["id"] in track_ids
                or not isinstance(track.get("events"), list) or not isinstance(track.get("kind"), str)):
            raise ValueError("The MV project has an invalid or duplicate track.")
        track_ids.add(track["id"])
        event_ids = set()
        events += len(track["events"])
        for event in track["events"]:
            if (not isinstance(event, dict) or not isinstance(event.get("id"), str) or event["id"] in event_ids
                    or any(type(event.get(key)) not in (int, float) or not math.isfinite(event[key]) or not 0 <= event[key] <= 3600
                           for key in ("start", "duration")) or not isinstance(event.get("values"), dict)):
                raise ValueError("The MV project has an invalid or duplicate timeline event.")
            event_ids.add(event["id"])
    if events > 12000:
        raise ValueError("The MV project contains too many timeline events.")
    if (any(not isinstance(value.get(field), dict) for field in ("quality", "source")) or
            any(value.get(field) is not None and not isinstance(value[field], dict) for field in ("stage", "soundtrack"))):
        raise ValueError("The MV project has invalid scene settings.")
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(data) > PROJECT_BYTES:
        raise ValueError("The edited MV project exceeds the storage limit.")
    return data


def _references(project):
    names = set()
    for objects, fields in (([project.get("stage") or {}], ("glb", "effectsGlb")),
                            (project["performers"], ("glb",)),
                            (project["assets"], ("previewUrl",)),
                            ([project.get("soundtrack") or {}], ("url",))):
        for item in objects:
            for field in fields:
                if value := item.get(field):
                    if not isinstance(value, str) or not value.startswith(_MEDIA_URL) or not _MEDIA_NAME.fullmatch(value[len(_MEDIA_URL):]):
                        raise ValueError("An MV preview references an invalid media address.")
                    names.add(value[len(_MEDIA_URL):])
    if len(names) > MAX_MEDIA:
        raise ValueError("The MV project references too many preview assets.")
    return sorted(names)


def _destination(name, suffix):
    if not isinstance(name, str):
        raise ValueError("Enter a name for the MV file.")
    label = re.sub(r"[^\w .()-]+", "-", name)[:60].strip(" .-") or "MV"
    root = game_models._safe_directory(Path(default_sukusta_dir("modded/mv-studio")).resolve())
    return root / (label + "-" + secrets.token_hex(4) + suffix)


def _receipt(path):
    return {"path": str(path), "download": "/api/download?path=" + quote(str(path), safe="")}


def save(project, name=None):
    data = _document(project)
    files = [("media/" + token, media(token)[0]) for token in _references(project)]
    source = _native(project)
    if source is None and project.get("nativeTimeline") is True:
        raise ValueError("The original MV timeline is unavailable. Reopen the original timeline before saving.")
    if len(data) + sum(path.stat().st_size for _, path in files) + len(source or b"") > PACKAGE_BYTES:
        raise ValueError("The MV project and its preview assets exceed the ZIP size limit.")
    target = _destination(name or project["name"], ".mv-project.zip")
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".mv-project-")
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            archive.writestr("project.json", data)
            if source is not None:
                archive.writestr("source-timeline.unity", source)
            for relative, path in files:
                archive.write(path, relative, compress_type=zipfile.ZIP_STORED)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return _receipt(target)


def export_timeline(project):
    from . import mv_studio_timeline
    _document(project)
    source = _native(project)
    if source is None:
        raise ValueError("Open an original live timeline to export a native timeline copy.")
    output = mv_studio_timeline.export_timeline(source, project["name"], project["tracks"])
    return _receipt(_write(_destination(project["name"], ".unity"), output))


def _archive_entries(archive):
    found, seen, total = {}, set(), 0
    for info in archive.infolist():
        path = viewer_archive._entry_path(info)
        if info.is_dir():
            continue
        key = path.as_posix().casefold()
        total += info.file_size
        if key in seen or len(found) >= 256 or total > PACKAGE_BYTES:
            raise ValueError("The selected ZIP has ambiguous or oversized MV assets.")
        seen.add(key)
        found[path.as_posix()] = info
    return found


def _display_particle_atlases(project):
    display, speed = project.get("stageDisplayLights"), project.get("stageSpeedBack")
    center = speed.get("centerStars") if isinstance(speed, dict) else None
    return {"displayLights": display.get("texture") if isinstance(display, dict) else None,
            "speedBackCenterStars": center.get("texture") if isinstance(center, dict) else None}


def _restore_display_atlases(project, original, field, aliases):
    descriptor = original.get(field)
    if not descriptor:
        return
    saved_atlases = _display_particle_atlases(project)
    original_atlases = _display_particle_atlases(original)
    restored = []
    for texture, alias in zip(descriptor["textures"], aliases):
        if alias is None:
            restored.append(texture)
            continue
        # A saved project may have a custom atlas. Keep the authentic native
        # one embedded when the previously saved owner's atlas differs.
        authentic = original_atlases.get(alias) if texture == alias else texture
        restored.append(alias if authentic == saved_atlases.get(alias) else authentic)
    project[field] = {**descriptor, "textures": restored}



def _restore_front_sparks(project, original, saved):
    field = "stageSparksA"
    alias = "speedBackCenterStars"
    if saved is None:
        _restore_display_atlases(project, original, field, (alias,))
        return
    rebuilt = original.get(field)
    saved_textures = saved.get("textures")
    if (not rebuilt or rebuilt["cues"] != saved.get("cues")
            or not isinstance(saved_textures, list) or len(saved_textures) != 1):
        return
    present = {row["name"] for row in saved["emitters"]}
    additions = [row for row in rebuilt["emitters"] if row["name"] not in present]
    if not additions:
        return
    previous, = saved_textures
    authentic, = rebuilt["textures"]
    if previous == alias:
        previous = _display_particle_atlases(project)[alias]
    if authentic == alias:
        authentic = _display_particle_atlases(original)[alias]
    # Keep a saved custom atlas and its existing emitters intact when the
    # recovered native emitters cannot share that atlas.
    if authentic is not None and previous == authentic:
        project[field] = {**saved, "emitters": [*saved["emitters"], *additions]}


def _restore_butterfly_companion(saved, rebuilt, field, tracks, authentic_atlas):
    recovered = {**{key: value for key, value in rebuilt.items() if key != field}, **saved}
    # Native companions reuse a single atlas and follow the original cue after
    # edits. Preserve all previously saved rows, including custom effects.
    track_id, event_id = rebuilt.get("trackId"), rebuilt.get("eventId")
    if (field not in saved and field in rebuilt and authentic_atlas and track_id is not None and event_id is not None
            and recovered.get("trackId") == track_id and recovered.get("eventId") == event_id
            and any(track["id"] == track_id and any(event["id"] == event_id for event in track["events"])
                    for track in tracks)):
        recovered[field] = rebuilt[field]
    return recovered


def _saved_particle_cues(saved, maximum):
    if isinstance(saved, dict) and type(saved.get("schema")) is int and saved["schema"] == 1:
        cues = saved.get("cues")
        if isinstance(cues, list) and 1 <= len(cues) <= maximum and all(
                isinstance(row, dict) and all(isinstance(row.get(key), str) for key in ("trackId", "eventId", "profile"))
                for row in cues):
            return cues
    return ()


def _restore_rain_impacts(project, rebuilt, existing):
    cues = [cue for cue in rebuilt["cues"] if (cue["trackId"], cue["eventId"]) in existing]
    if not cues:
        return
    if "stageRain" not in project:
        project["stageRain"] = {**rebuilt, "cues": cues}
        return
    saved = project["stageRain"]
    atlas = rebuilt.get("impactTextures")
    if not atlas or saved.get("impactTextures", atlas) != atlas:
        return
    impacts = {(cue["trackId"], cue["eventId"], cue["profile"]): cue["impact"] for cue in cues if "impact" in cue}
    restored = []
    for cue in _saved_particle_cues(saved, 2):
        identity = cue["trackId"], cue["eventId"], cue["profile"]
        impact = impacts.get(identity)
        if "impact" in cue and "impactTextures" not in saved and cue["impact"] != impact:
            return
        restored.append({**cue, "impact": impact} if impact is not None and "impact" not in cue else cue)
    if restored and restored != saved["cues"]:
        project["stageRain"] = {**saved, "cues": restored, "impactTextures": atlas}


def _restore_leaves(project, rebuilt, available, missing_cues):
    cues = [cue for cue in rebuilt["cues"] if (cue["trackId"], cue["eventId"]) in available]
    if not cues:
        return
    if "stageLeaves" not in project:
        project["stageLeaves"] = {**rebuilt, "cues": cues}
        return
    saved = project["stageLeaves"]
    if any(key not in saved or saved[key] != rebuilt.get(key) for key in ("geometry", "texture", "alphaKeys", "material")):
        return
    additions = {(cue["trackId"], cue["eventId"]): cue for cue in cues
                 if missing_cues.get((cue["trackId"], cue["eventId"])) == cue["profile"]}
    restored = []
    for existing in saved["cues"]:
        cue = additions.pop((existing["trackId"], existing["eventId"]), None)
        roles = _transition_roles(existing)
        if cue is None or roles is None:
            restored.append(existing)
        else:
            emitters = [emitter for emitter in cue["emitters"] if emitter["role"] not in roles]
            merged = [*existing["emitters"], *emitters]
            restored.append({**existing, "emitters": merged} if len(merged) <= 4 else existing)
    restored.extend(additions.values())
    if restored != saved["cues"]:
        project["stageLeaves"] = {**saved, "cues": restored}


def _transition_roles(cue):
    emitters = cue.get("emitters")
    if cue["profile"] != "05" or not isinstance(emitters, list) or not 1 <= len(emitters) <= 4:
        return None
    if any(not isinstance(row, dict) or not isinstance(row.get("role"), str) for row in emitters):
        return None
    roles = {row["role"] for row in emitters}
    return roles if len(roles) == len(emitters) else None


def _momiji_roles(saved):
    if (not isinstance(saved, dict) or type(saved.get("schema")) is not int or saved["schema"] != 1
            or not isinstance(saved.get("textures"), dict)
            or any(not isinstance(saved.get(key), str) for key in ("trackId", "eventId"))):
        return None
    rows = saved.get("emitters")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
        return None
    if any(not isinstance(row, dict) or not isinstance(row.get("role"), str) for row in rows):
        return None
    roles = {row["role"] for row in rows}
    return roles if len(roles) == len(rows) else None


def _restore_momiji(project, rebuilt, active):
    if (rebuilt["trackId"], rebuilt["eventId"]) not in active:
        return
    if "stageMomiji" not in project:
        project["stageMomiji"] = rebuilt
        return
    saved = project["stageMomiji"]
    roles = _momiji_roles(saved)
    if roles is None or any(saved.get(key) != rebuilt[key] for key in ("trackId", "eventId", "anchor")):
        return
    restored = {**saved, "textures": dict(saved["textures"]), "emitters": list(saved["emitters"])}
    for row in rebuilt["emitters"]:
        if row["role"] in roles or len(restored["emitters"]) >= 4:
            continue
        kind = row["texture"]
        texture = rebuilt["textures"][kind]
        if kind in saved["textures"] and saved["textures"][kind] != texture:
            continue
        if kind == "leaf":
            geometry = rebuilt["geometry"]
            if "geometry" in saved and saved["geometry"] != geometry:
                continue
            restored["geometry"] = geometry
        restored["textures"][kind] = texture
        restored["emitters"].append(row)
    if restored != saved:
        project["stageMomiji"] = restored


def _open_saved(archive, entries):
    from . import mv_studio_confetti, mv_studio_leaves, mv_studio_momiji, mv_studio_rain
    from . import mv_studio_stage_glow, mv_studio_stage_lens, mv_studio_stage_particles
    from . import mv_studio_timeline

    entry = entries["project.json"]
    if entry.file_size > PROJECT_BYTES:
        raise ValueError("The saved MV project file is too large.")
    project = json.loads(archive.read(entry))
    _document(project)
    for name in _references(project):
        info = entries.get("media/" + name)
        if info is None or not 0 < info.file_size <= MEDIA_BYTES:
            raise ValueError("The saved project is missing a preview asset.")
        raw = archive.read(info)
        extension = name.rsplit(".", 1)[1]
        if _media_name(raw, extension) != name:
            raise ValueError("A preview asset has changed since the project was saved.")
        _media(raw, extension)
    timeline = entries.get("source-timeline.unity")
    if timeline is not None and not 0 < timeline.file_size <= MEDIA_BYTES:
        raise ValueError("The saved project contains an invalid original timeline.")
    source = archive.read(timeline) if timeline is not None else None
    restore_split = "splitScreen" not in project and any(
        track.get("nativeClass") == "LiveSplitScreenTrack" for track in project["tracks"])
    title = project.get("stageTitle")
    schema = title.get("particleSchema") if isinstance(title, dict) else None
    restore_title = (type(schema) is not int or schema < 2) and any(
        track.get("nativeClass") == "CustomControlTrack" and "/Display/" in str(track.get("label", ""))
        for track in project["tracks"])
    particles = project.get("stageParticles")
    schema = particles.get("schema") if isinstance(particles, dict) else None
    restore_particles = (type(schema) is not int or schema < mv_studio_stage_particles.SCHEMA) and any(
        track.get("nativeClass") == "CustomControlTrack" and "/Control/" in str(track.get("label", ""))
        for track in project["tracks"])
    ribbons = project.get("stageRibbons")
    restore_ribbons = (not isinstance(ribbons, dict) or "shine" not in ribbons) and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Display/dis_par_01-02_obi")
        for track in project["tracks"])
    restore_spotlight = "stageSpotlight" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Control/par_12_spot")
        for track in project["tracks"])
    butterfly = project.get("stageButterfly")
    butterfly = butterfly if isinstance(butterfly, dict) else {}
    saved_finale = butterfly.get("finale")
    missing_butterflies = tuple(suffix for row, suffix, required in (
        (butterfly, "/Control/par_13_butterfly", {"trackId", "eventId", "glow", "shine"}),
        (saved_finale, "/Control/par_14_butterfly", {"trackId", "eventId", "glow", "dust"}),
    ) if not isinstance(row, dict) or not required <= row.keys() or "glowTexture" not in butterfly)
    restore_butterfly = bool(missing_butterflies) and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith(missing_butterflies)
        for track in project["tracks"])
    rain_cues = {(track["id"], event["id"]) for track in project["tracks"]
                 if track.get("nativeClass") == "CustomControlTrack" and track.get("label") == mv_studio_rain.TRACK
                 for event in track["events"]}
    restore_rain = bool(rain_cues) and ("stageRain" not in project or any(
        (cue["trackId"], cue["eventId"]) in rain_cues and "impact" not in cue
        for cue in _saved_particle_cues(project["stageRain"], 2)))
    leaf_cues = {(track["id"], event["id"]) for track in project["tracks"]
                 if track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")) in mv_studio_leaves.PROFILES
                 for event in track["events"]}
    saved_leaves = _saved_particle_cues(project.get("stageLeaves"), 10)
    saved_leaf_cues = {(cue["trackId"], cue["eventId"]): cue for cue in saved_leaves}
    transition_roles = set(mv_studio_leaves.TRANSITION_ROLES)
    partial_transitions = {key for key, cue in saved_leaf_cues.items()
                           if (roles := _transition_roles(cue)) is not None and not transition_roles <= roles}
    missing_leaves = {(track["id"], event["id"]): mv_studio_leaves.PROFILES[track["label"]][0]
                      for track in project["tracks"] if track.get("nativeClass") == "CustomControlTrack"
                      and track.get("label") in (mv_studio_leaves.RED_TRACK, mv_studio_leaves.FLOOR_TRACK,
                                                 mv_studio_leaves.TRANSITION_TRACK)
                      for event in track["events"] if (track["id"], event["id"]) not in saved_leaf_cues
                      or (track["id"], event["id"]) in partial_transitions}
    restore_leaves = bool(leaf_cues) and ("stageLeaves" not in project or bool(saved_leaves and missing_leaves))
    momiji_cues = {(track["id"], event["id"]) for track in project["tracks"]
                   if track.get("nativeClass") == "CustomControlTrack" and track.get("label") == mv_studio_momiji.TRACK
                   for event in track["events"]}
    saved_momiji = project.get("stageMomiji")
    momiji_roles = _momiji_roles(saved_momiji)
    restore_momiji = bool(momiji_cues) and ("stageMomiji" not in project or (
        momiji_roles is not None and not mv_studio_momiji.ROLES.keys() <= momiji_roles
        and (saved_momiji.get("trackId"), saved_momiji.get("eventId")) in momiji_cues))
    confetti_cues = {(track["id"], event["id"]) for track in project["tracks"]
                     if track.get("nativeClass") == "CustomControlTrack" and track.get("label") == mv_studio_confetti.TRACK
                     for event in track["events"]}
    saved_confetti = project.get("stageConfetti")
    confetti_roles = mv_studio_confetti.saved_roles(saved_confetti)
    restore_confetti = bool(confetti_cues) and ("stageConfetti" not in project or (
        confetti_roles is not None and confetti_roles != set(mv_studio_confetti.ROLES.values())))
    glow_cues = {(track["id"], event["id"]) for track in project["tracks"]
                 if track.get("nativeClass") == "CustomControlTrack" and track.get("label") == mv_studio_stage_glow.TRACK
                 for event in track["events"]}
    restore_glow = bool(glow_cues) and "stageGlow" not in project
    lens_cues = mv_studio_stage_lens.candidate_cues(project["tracks"])
    saved_lens = project.get("stageLensFlare")
    saved_lens_cues = mv_studio_stage_lens.saved_cues(saved_lens)
    lens_missing = lens_cues - {(cue["trackId"], cue["eventId"]) for cue in saved_lens_cues}
    known_lens = mv_studio_stage_lens.known_schema(saved_lens)
    lens_scanned = known_lens and saved_lens["schema"] == mv_studio_stage_lens.SCHEMA and saved_lens.get("scanComplete") is True
    empty_lens = known_lens and all(saved_lens.get(key) == [] for key in ("textures", "emitters", "cues"))
    restore_lens = bool(lens_missing) and not lens_scanned and (
        "stageLensFlare" not in project or bool(saved_lens_cues) or empty_lens)
    speed_back = project.get("stageSpeedBack")
    restore_speed_back = (not isinstance(speed_back, dict) or
                          not {"centerStars", "movingCompanions"} <= speed_back.keys()) and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Display/light")
        and any(event.get("label") == "fx_dis_so2056_09" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "9155575924868579619",
        } for event in track["events"]) for track in project["tracks"])
    restore_display_lights = "stageDisplayLights" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Display/light")
        and any(event.get("label") == "fx_dis_so2056_06" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "-3728220010162171534",
        } for event in track["events"]) for track in project["tracks"])
    restore_falling = "stageFallingEffects" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Display/light")
        and any(event.get("label") in ("fx_dis_so2056_05", "fx_dis_so2056_07")
                or event["values"].get("prefabGameObject") in (
                    {"m_FileID": 0, "m_PathID": "-1918126523244823858"},
                    {"m_FileID": 0, "m_PathID": "-4628465527854343341"})
                for event in track["events"]) for track in project["tracks"])
    restore_break = "stageBreak" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Display/break")
        and any(event.get("label") == "fx_dis_so2056_08" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "-277186095147178148",
        } for event in track["events"]) for track in project["tracks"])
    restore_finale_floor = "stageFinaleFloor" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Control/flo")
        and any(event.get("label") == "fx_flo_so2056_01" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "-1916851570489530364",
        } for event in track["events"]) for track in project["tracks"])
    sparks_a = project.get("stageSparksA")
    front_emitters = sparks_a.get("emitters") if isinstance(sparks_a, dict) else None
    front_names = (
        tuple(row.get("name") if isinstance(row, dict) else None for row in front_emitters)
        if isinstance(front_emitters, list) else ()
    )
    missing_front_emitters = front_names in (("hibana_01",), ("hibana_01", "hibana_02"), ("hibana_01", "smoke"))
    restore_sparks_a = (sparks_a is None or missing_front_emitters) and any(
        track.get("nativeClass") == "CustomControlTrack"
        and str(track.get("label", "")).endswith(("/Control/sparks_A_01", "/Control/sparks_A_02"))
        and any(event.get("label") == "fx_par_so2056_01" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "6581900986414377151",
        } for event in track["events"]) for track in project["tracks"])
    restore_sparks_b = "stageSparksB" not in project and any(
        track.get("nativeClass") == "CustomControlTrack"
        and str(track.get("label", "")).endswith(("/Control/sparks_B_01", "/Control/sparks_B_02"))
        and any(event.get("label") == "fx_par_so2056_02" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "-8184682665616244301",
        } for event in track["events"]) for track in project["tracks"])
    restore_sparks_roop = "stageSparksRoop" not in project and any(
        track.get("nativeClass") == "CustomControlTrack" and str(track.get("label", "")).endswith("/Control/sparks_roop")
        and any(event.get("label") == "fx_par_so2056_03" or event["values"].get("prefabGameObject") == {
            "m_FileID": 0, "m_PathID": "1069439206166195116",
        } for event in track["events"]) for track in project["tracks"])
    restore_emissive_tracks = any(mv_studio_timeline.needs_emissive_track_metadata(track) for track in project["tracks"])
    restore_camera_points = any(mv_studio_timeline.needs_camera_keyframe_check(track) for track in project["tracks"])
    shared_playables = mv_studio_timeline.shared_playables(project["tracks"])
    restore_editable_values = any(mv_studio_timeline.needs_editable_values_sync(track, shared_playables)
                                  for track in project["tracks"])
    if source is not None and (restore_split or restore_title or restore_particles or restore_ribbons
                               or restore_spotlight or restore_butterfly or restore_rain or restore_leaves or restore_momiji
                               or restore_confetti or restore_glow or restore_lens or restore_speed_back
                               or restore_display_lights or restore_falling
                               or restore_break or restore_finale_floor or restore_sparks_a or restore_sparks_b
                               or restore_sparks_roop or restore_emissive_tracks or restore_camera_points
                               or restore_editable_values):
        try:
            options = {}
            if restore_particles:
                options["preview_stage_particles"] = True
            if restore_ribbons:
                options["preview_stage_ribbons"] = True
            if restore_spotlight:
                options["preview_stage_spotlight"] = True
            if restore_butterfly:
                options["preview_stage_butterfly"] = True
            if restore_rain:
                options["preview_stage_rain"] = True
            if restore_leaves:
                options["preview_stage_leaves"] = True
            if restore_momiji:
                options["preview_stage_momiji"] = True
            if restore_confetti:
                options["preview_stage_confetti"] = True
            if restore_glow:
                options["preview_stage_glow"] = True
            if restore_lens:
                options["preview_stage_lens"] = True
            if restore_speed_back:
                options["preview_stage_speed_back"] = True
            if restore_display_lights:
                options["preview_stage_display_lights"] = True
            if restore_falling:
                options["preview_stage_falling_effects"] = True
            if restore_break:
                options["preview_stage_break"] = True
            if restore_finale_floor:
                options["preview_stage_finale_floor"] = True
            if restore_sparks_a:
                options["preview_stage_sparks_a"] = True
            if restore_sparks_b:
                options["preview_stage_sparks_b"] = True
            if restore_sparks_roop:
                options["preview_stage_sparks_roop"] = True
            original = mv_studio_timeline.parse_timeline(source, project["name"], preview_split=restore_split,
                                                         preview_stage_title=restore_title, **options)
        except (EOFError, KeyError, TypeError, ValueError, OSError, struct.error):
            pass
        else:
            if restore_emissive_tracks:
                project["tracks"] = mv_studio_timeline.restore_emissive_track_metadata(project["tracks"], original["tracks"])
            if isinstance(original.get("tracks"), list):
                # Fields made editable after the project was saved (additions to the whitelist only).
                project["tracks"] = mv_studio_timeline.sync_editable_values(project["tracks"], original["tracks"])
            if restore_camera_points and isinstance(original.get("tracks"), list):
                # Unedited camera points saved before camera Euler rotation orders preview as the game does.
                try:
                    project["tracks"] = mv_studio_timeline.restore_legacy_camera_keyframes(
                        source, project["name"], project["tracks"], original["tracks"])
                except (EOFError, KeyError, TypeError, ValueError, OSError, struct.error):
                    pass
            for field in ("splitScreen", "stageTitle", "stageSpotlight", "stageDisplayLights"):
                if field in original:
                    project[field] = original[field]
            if "stageButterfly" in original:
                rebuilt = original["stageButterfly"]
                atlas = rebuilt.get("glowTexture")
                use_atlas = bool(atlas) and butterfly.get("glowTexture", atlas) == atlas
                recovered = _restore_butterfly_companion(butterfly, rebuilt, "shine", project["tracks"], use_atlas)
                if "finale" in rebuilt and isinstance(butterfly.get("finale", {}), dict):
                    recovered["finale"] = _restore_butterfly_companion(
                        saved_finale or {}, rebuilt["finale"], "dust", project["tracks"], use_atlas,
                    )
                project["stageButterfly"] = recovered
            if restore_rain and "stageRain" in original:
                _restore_rain_impacts(project, original["stageRain"], rain_cues)
            if restore_leaves and "stageLeaves" in original:
                _restore_leaves(project, original["stageLeaves"], leaf_cues, missing_leaves)
            if restore_momiji and "stageMomiji" in original:
                _restore_momiji(project, original["stageMomiji"], momiji_cues)
            if restore_confetti and "stageConfetti" in original:
                restored = mv_studio_confetti.restore_saved(saved_confetti, original["stageConfetti"], confetti_cues)
                if restored is not None:
                    project["stageConfetti"] = restored
            if restore_glow and "stageGlow" in original:
                rebuilt = original["stageGlow"]
                cues = [cue for cue in rebuilt["cues"] if (cue["trackId"], cue["eventId"]) in glow_cues]
                if cues:
                    project["stageGlow"] = {**rebuilt, "cues": cues}
            if restore_lens and "stageLensFlare" in original:
                restored = mv_studio_stage_lens.restore_saved(saved_lens, original["stageLensFlare"], lens_cues, saved_lens_cues)
                if restored is not None:
                    project["stageLensFlare"] = restored
            rebuilt_background = original.get("stageSpeedBack")
            if rebuilt_background and not isinstance(speed_back, dict):
                project["stageSpeedBack"] = rebuilt_background
            elif rebuilt_background and "centerStars" in rebuilt_background and all(
                    speed_back.get(key) == rebuilt_background.get(key) for key in ("trackId", "eventId")):
                original_stars = rebuilt_background["centerStars"]
                saved_stars = speed_back.get("centerStars", original_stars)
                restored = {**speed_back, "centerStars": saved_stars}
                # Moving emitters share the original center atlas. Preserve
                # any saved atlas and only attach these emitters if it matches.
                original_atlas = original_stars.get("texture")
                if ("movingCompanions" in rebuilt_background and original_atlas and isinstance(saved_stars, dict)
                        and saved_stars.get("texture") == original_atlas):
                    restored.setdefault("movingCompanions", rebuilt_background["movingCompanions"])
                project["stageSpeedBack"] = restored
            _restore_display_atlases(project, original, "stageFallingEffects", ("displayLights", "speedBackCenterStars"))
            _restore_display_atlases(project, original, "stageBreak", (None, "displayLights", "speedBackCenterStars"))
            _restore_display_atlases(project, original, "stageFinaleFloor", ("speedBackCenterStars",))
            if restore_sparks_a:
                _restore_front_sparks(project, original, sparks_a)
            _restore_display_atlases(project, original, "stageSparksB", ("speedBackCenterStars",))
            _restore_display_atlases(project, original, "stageSparksRoop", ("speedBackCenterStars",))
            rebuilt_ribbons = original.get("stageRibbons")
            if rebuilt_ribbons and not isinstance(ribbons, dict):
                project["stageRibbons"] = rebuilt_ribbons
            elif rebuilt_ribbons and "shine" in rebuilt_ribbons:
                project["stageRibbons"] = {**ribbons, "shine": rebuilt_ribbons["shine"]}
            rebuilt = original.get("stageParticles")
            if rebuilt is not None and mv_studio_stage_particles.preserves(particles, rebuilt):
                project["stageParticles"] = rebuilt
    return _register(project, source)


def _mod_files(project, files):
    native = None
    media_files = []
    for path, label, kind in files:
        if kind in {"timeline", "other"} and path.suffix.lower() in _UNITY_SUFFIXES:
            try:
                raw, parsed = _timeline(path)
            except (ValueError, OSError):
                if kind == "timeline":
                    project["warnings"].append(f"{label}: a live timeline could not be opened.")
            else:
                if native is not None:
                    project["warnings"].append(f"{label}: open this timeline separately to edit this variant.")
                    continue
                native = raw
                project.update({field: parsed[field] for field in
                                ("duration", "tracks", "splitScreen", "stageMotion", "stageTitle", "stageParticles",
                                 "stageRibbons", "stageSpotlight", "stageButterfly", "stageRain", "stageLeaves", "stageMomiji",
                                 "stageConfetti", "stageGlow", "stageLensFlare", "stageSpeedBack",
                                 "stageDisplayLights", "stageFallingEffects", "stageBreak", "stageFinaleFloor",
                                 "stageSparksA", "stageSparksB", "stageSparksRoop", "stageParticleSystems",
                                 "stageControlPrefabs", "controlCoverage")
                                if field in parsed})
                project["warnings"].extend(parsed.get("warnings", []))
                project["assets"].append({"id": secrets.token_hex(8), "kind": "timeline", "label": label,
                                          "path": label, "status": "loaded"})
                continue
        media_files.append((path, label, kind))
    stage_bindings = project.get("stageMotion", {}).get("bindings", ())
    for path, label, kind in media_files:
        if kind == "other" and len(files) == 1:
            kind = "stage"
        if kind not in _PREVIEW_KIND | {"audio"}:
            project["assets"].append({"id": secrets.token_hex(8), "kind": kind, "label": label,
                                      "path": label, "status": "reference"})
            continue
        try:
            result = _asset(path, kind, stage_bindings=stage_bindings if kind in {"effect", "stage"} else ())
        except (ValueError, OSError) as error:
            project["warnings"].append(f"{label}: {error}")
            continue
        result["asset"].update(path=label, label=label)
        project["assets"].append(result["asset"])
        if "stage" in result:
            project["stage"] = result["stage"]
        if "soundtrack" in result:
            project["soundtrack"] = result["soundtrack"]
            project["duration"] = max(project["duration"], project["soundtrack"].get("duration", 0))
        if "performer" in result and len(project["performers"]) < _MEMBER_MAX:
            project["performers"].append(result["performer"])
    if native is None and not project["stage"] and not project["performers"] and not project["soundtrack"]:
        raise ValueError("No supported live timeline, stage model, character or soundtrack was found in this mod.")
    return _register(project, native)


def _mod_kind(name):
    path = Path(name)
    if path.suffix.lower().lstrip(".") in _MEDIA and path.suffix.lower() != ".glb":
        return "audio"
    stem = path.stem.casefold()
    for kind, words in (("timeline", ("timeline",)), ("effect", ("effect", "vfx")),
                        ("props", ("props", "prop_skeleton")), ("background", ("background", "backdrop")),
                        ("performer", ("costume", "wearer", "member_model")), ("stage", ("stage", "scenery"))):
        if any(word in stem for word in words):
            return kind
    return "other"


def open_project(path):
    selected = _path(path)
    if selected.suffix.lower() == ".json":
        if selected.stat().st_size > PROJECT_BYTES:
            raise ValueError("The saved MV project file is too large.")
        value = json.loads(selected.read_bytes())
        _document(value)
        for name in _references(value):
            media(name)
        return _register(value, _native(value))
    project = _blank(selected.stem)
    if not zipfile.is_zipfile(selected):
        return _mod_files(project, [(selected, selected.name, _mod_kind(selected.name))])
    with zipfile.ZipFile(selected) as archive:
        entries = _archive_entries(archive)
        if "project.json" in entries:
            return _open_saved(archive, entries)
        with tempfile.TemporaryDirectory(prefix="mod-", dir=_root()) as path:
            files = []
            for index, (name, info) in enumerate(entries.items()):
                suffix = Path(name).suffix.lower()
                if suffix in _UNITY_SUFFIXES or suffix.lstrip(".") in _MEDIA:
                    if not 0 < info.file_size <= MEDIA_BYTES or len(files) >= 48:
                        raise ValueError("The mod has too many or oversized preview asset files.")
                    local = Path(path) / (str(index) + suffix)
                    with archive.open(info) as source, local.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    files.append((local, name, _mod_kind(name)))
            return _mod_files(project, files)
