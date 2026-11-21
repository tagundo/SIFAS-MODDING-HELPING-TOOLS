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
from . import game_models, model_viewer, viewer_archive
from .member_identity import member_from_native
from .sukusta import default_sukusta_dir
from .viewer_cache import game_models_dir, viewer_cache_root


PROJECT_BYTES = 16 * 1024 * 1024
PACKAGE_BYTES = 384 * 1024 * 1024
MEDIA_BYTES = 96 * 1024 * 1024
MAX_MEDIA = 48
_MEDIA = {"glb": "model/gltf-binary", "wav": "audio/wav", "ogg": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4"}
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}\.(?:glb|wav|ogg|mp3|m4a)\Z")
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
_NATIVE_DIGEST = re.compile(rb"[a-f0-9]{64}\Z")
_MEDIA_URL = "/api/mv-studio/media/"
_UNITY_SUFFIXES = {".unity", ".unity3d", ".assets", ".bundle", ".bytes"}
_PREVIEW_KIND = {"stage", "effect", "props", "background", "performer", "outfit"}
_ROLES = _PREVIEW_KIND | {"audio", "timeline", "camera", "lighting", "display", "dance", "mouth", "eyes", "gaze", "cheek", "shader", "crowd", "split", "other"}
_IMPORT = threading.BoundedSemaphore(1)
_ACTOR_PREVIEWS = OrderedDict()
_STAGE_PREVIEWS = OrderedDict()
_ACTOR_PREVIEW_ENTRIES = 24
_ACTOR_PREVIEW_METADATA_BYTES = 4 * 1024 * 1024


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
             "m4a": lambda: data[4:8] == b"ftyp"}
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
             native_stage_effect=False):
    models = [path, *companions]
    key = None
    cache = _ACTOR_PREVIEWS if performer else _STAGE_PREVIEWS
    if reuse and ((performer and motions and companions) or (not performer and not motions and not companions)):
        # Game stage previews depend on one exact input. Performer previews
        # also need explicit companions to rule out local face discovery.
        key = (_root(), tuple((item.name, game_models._sha(item)) for item in models),
               tuple((item.name, game_models._sha(item)) for item in motions), tuple(stage_bindings),
               native_stage_effect)
        cached = model_viewer._conversion_get(cache, key, time.monotonic() + model_viewer.BUILD_SECONDS)
        if cached is not None:
            name, rig = json.loads(cached)
            try:
                previous, _ = media(name)
                if game_models._sha(previous)[:32] == previous.stem:
                    return _MEDIA_URL + name, rig
            except OSError:
                pass
    prepared = model_viewer.prepare(list(map(str, models)), rigged=performer,
        face_context={"enabled": performer and not companions, "allow_download": False,
                      "_mv_stage": not performer, "_mv_authored_motion": performer and bool(motions),
                      "_mv_stage_motion_bindings": stage_bindings, "_mv_performer": performer,
                      "_mv_native_stage_effect": native_stage_effect},
        motion_paths=list(map(str, motions)) or None)
    payload = model_viewer.get_model(prepared["id"])
    if payload is None:
        raise ValueError("The 3D preview expired. Reopen the asset.")
    url, rig = _media(payload, "glb"), prepared.get("rig", {}) if performer else {}
    if rig.get("bones"):
        from . import viewer_physics

        try:
            physics = viewer_physics.catalogue_preview(models, rig["bones"])
            if physics.get("available"):
                rig = {**rig, "physics": physics}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Optional source physics is independent of the usable body model.
            pass
    if key is not None:
        if performer and rig.get("available") and any(clip.get("bindingComplete") for clip in rig.get("clips", [])):
            model_viewer._conversion_put(
                cache, key, json.dumps([url.removeprefix(_MEDIA_URL), rig]).encode(),
                max_bytes=_ACTOR_PREVIEW_METADATA_BYTES, max_entries=_ACTOR_PREVIEW_ENTRIES,
            )
        elif not performer and not prepared.get("warnings"):
            model_viewer._conversion_put(cache, key, json.dumps([url.removeprefix(_MEDIA_URL), rig]).encode(),
                                         max_bytes=16 * 1024, max_entries=32)
    return url, rig


def _preview_file(path, kind, *, stage_bindings=()):
    if path.suffix.lower() == ".glb":
        return _media(path.read_bytes(), "glb"), {}
    return _preview(path, performer=kind in {"performer", "outfit"}, stage_bindings=stage_bindings)


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


def _timeline(path):
    from . import mv_studio_timeline
    raw = path.read_bytes()
    parsed = mv_studio_timeline.parse_timeline(raw, path.name, preview_split=True, preview_stage_motion=True,
                                               preview_member_shafts=True, preview_stage_title=True,
                                               preview_stage_particles=True, preview_stage_ribbons=True)
    if not parsed.get("tracks"):
        raise ValueError("This file does not contain an original live timeline.")
    return raw, parsed


def _motion(timeline, dependencies, facial, directory, position, owner, tracks, deadline):
    from . import game_motion_selection, game_motion_timeline
    selected = game_motion_selection.select(timeline, dependencies, performer=position, deadline=deadline)
    facial_selection, facial_entries = game_motion_selection.facial_banks(facial, deadline=deadline)
    selected["selected"].update(facial_selection["selected"])
    directory.mkdir()
    files, segments, sources, identities = game_motion_selection.write_selected(selected, directory)
    facial_clips = []
    for item in facial_entries:
        key = item["key"]
        facial_clips.append({name: value for name, value in item.items() if name != "key"} | identities[key])
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
    native_face = game_motion_timeline.parse_timeline(str(timeline), position, segments=segments)
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
    descriptor = {"version": 2, "category": "mv", "performerPosition": position, "targetCharacter": owner,
                  "clipSources": sources, "bodySegments": segments, "facialClips": facial_clips, "facial": native_face}
    return [item["path"] for item in files], descriptor


def _cast_in_timeline_order(performers, tracks):
    members = {}
    for track in tracks:
        if track["kind"] != "dance" or not (slot := re.fullmatch(r"/EntryPoint/Live/Members/Member(\d+)/Model", track.get("binding", ""))):
            continue
        for event in track["events"]:
            identity = re.match(r"ch(\d{4})(?:_|$)", event["values"].get("animationName") or event["label"])
            if identity:
                members.setdefault(int(slot[1]), set()).add(member_from_native(int(identity[1])))
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
        motion = track.get("nativeClass") == "AnimationTrack" and track.get("binding") in stage_motion.get("bindings", ())
        activation_ids = stage_motion.get("activations", {}).get(track.get("id"))
        if track.get("muted") or (track["kind"] not in {"lighting", "crowd"} and not screen and not motion and activation_ids is None):
            continue
        events = []
        for event in track["events"]:
            start, end = event["start"], event["start"] + event["duration"]
            timing = stage_motion["mix"].get(event["id"]) if motion else None
            if start <= 0 <= end or (timing is not None and start > 0
                    and event["values"].get("preExtrapolationMode") in (1, 2, 3, 4)
                    and (timing.get("preInfinite") or (event["values"].get("preExtrapolationTime") or 0) >= start)):
                events.append(event)
        if events or screen or motion or activation_ids is not None:
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


def load_game(repo_root, *, region, platform, live_id, asset_id, language, download=False, on_stage=None):
    """Import the complete project, optionally publishing its renderable stage first."""
    from . import mv_studio_actor_cache, mv_studio_game, mv_studio_quality

    if type(download) is not bool:
        raise ValueError("Choose whether to download missing game assets.")
    if on_stage is not None and not callable(on_stage):
        raise TypeError("The stage preview callback must be callable.")
    if not _IMPORT.acquire(blocking=False):
        raise ValueError("An MV is already being prepared. Try again when it finishes.")
    try:
        selected = mv_studio_game.resolve(repo_root, region=region, platform=platform,
                                          live_id=live_id, asset_id=asset_id, language=language)
        source = {"kind": "game", "region": selected["region"], "platform": selected["platform"],
                  "liveId": selected["liveId"], "assetId": selected["assetId"], "mvOnly": selected.get("mvOnly", False),
                  "registered": selected.get("registered", False)}
        project = _blank(selected["name"], source)
        project["quality"] = mv_studio_quality.read_quality(repo_root, region=source["region"], language=language,
                                                             quality_set=selected.get("qualitySet"))
        deadline = time.monotonic() + 210
        warnings = project["warnings"]
        with tempfile.TemporaryDirectory(prefix="import-", dir=_root()) as name:
            directory = Path(name)
            local, rows = {}, {}

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
                        raw = mv_studio_game.load_asset(repo_root, descriptor, download=download, deadline=deadline)
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

            timeline_row, timeline = load(selected.get("timeline"), "timeline", "Live timeline")
            if timeline is None:
                raise ValueError("The original MV timeline pack is missing. Download its missing assets or choose a local mod file.")
            native, parsed = _timeline(timeline)
            project.update({field: parsed[field] for field in
                            ("duration", "tracks", "splitScreen", "stageMotion", "stageTitle", "stageParticles", "stageRibbons")
                            if field in parsed})
            warnings.extend(parsed.get("warnings", []))
            original_cast = selected.get("performers", [])[:9]
            performers = _cast_in_timeline_order(original_cast, project["tracks"])
            stage = selected.get("stage") or {}
            stage_row, stage_file = load(selected.get("stageModel") or stage.get("model"), "stage", stage.get("name") or "Stage model")
            effect_row, effect_file = load(selected.get("stageEffect") or stage.get("effect"), "effect", "Stage effects")
            for row, preview_path in ((stage_row, stage_file), (effect_row, effect_file)):
                if preview_path is None:
                    continue
                try:
                    bindings = project.get("stageMotion", {}).get("bindings", ()) if row is effect_row else ()
                    row["previewUrl"], _ = _preview(preview_path, reuse=True, stage_bindings=bindings,
                                                    native_stage_effect=row is effect_row)
                except (ValueError, OSError) as error:
                    warnings.append(f"{row['label']}: {error}")
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
            if performer_prop is None:
                prop_row, prop_file = load(stage.get("props"), "props", "Stage props")
                if prop_file is not None:
                    try:
                        prop_row["previewUrl"], _ = _preview(prop_file, reuse=True)
                    except (ValueError, OSError) as error:
                        warnings.append(f"{prop_row['label']}: {error}")
            if on_stage is not None and project["stage"] is not None:
                on_stage(_stage_snapshot(project, rows.values(), performers))
            if performer_prop is not None:
                prop_row, prop_file = load(stage.get("props"), "props", "Performer prop")
                if prop_file is not None:
                    try:
                        glb, attachment = mv_studio_props.preview(
                            prop_file, native, timeline.name, performer_prop, deadline,
                        )
                        prop_row.update(previewUrl=_media(glb, "glb"), attachment=attachment)
                    except (ValueError, OSError) as error:
                        prop_row["status"] = "unavailable"
                        warnings.append(f"{prop_row['label']}: {error}")
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
            for entry in performers:
                number = entry["position"]
                label = entry.get("memberName") or f"Member {number}"
                _, model = load(entry.get("model"), "outfit", entry.get("costumeName") or label)
                # Position is a workbench starting pose until native rig
                # translations replace it. Never treat it as a stage bind.
                result = {"id": f"member-{number}", "position": number, "label": label,
                          "memberId": entry.get("memberId"), "costumeId": entry.get("costumeId"),
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
                    key = actor_cache.key(motion_inputs, number, result["memberId"], model, companions, facial_files) if actor_cache else None
                    saved = actor_cache.get(key) if key is not None else None
                    if saved is not None:
                        name, rig, motion = saved
                        result.update(glb=_MEDIA_URL + name, rig=rig, motion=motion)
                    else:
                        clips, motion = [], None
                        try:
                            clips, motion = _motion(timeline, motion_files, facial_files, directory / f"actor-{number}", number,
                                                    result["memberId"], project["tracks"], deadline)
                        except (ValueError, OSError) as error:
                            warnings.append(f"{label} choreography: {error}")
                        try:
                            url, rig = _preview(model, performer=True, motions=clips, companions=companions, reuse=True)
                            result.update(glb=url, rig=rig, motion=motion)
                            if key is not None:
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
            audio = selected.get("audio") or {}
            for role in ("acb", "awb"):
                describe((audio.get("chorus") or {}).get(role), "audio", f"Chorus {role.upper()}")
            if audio.get("cue") and audio.get("acb"):
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
                        decoded = directory / "soundtrack.wav"
                        cri_audio_decode.decode_cue(cue_bank, awb.read_bytes() if awb else None, audio["cue"], decoded)
                        project["soundtrack"] = _song_audio(decoded)
                        project["duration"] = max(project["duration"], project["soundtrack"]["duration"])
                except (ValueError, OSError) as error:
                    warnings.append(f"Soundtrack: {error}")
            if audio.get("cue") and project["soundtrack"] is None:
                warnings.append("The original soundtrack is unavailable for preview.")
            warnings.extend(f"{item['role']}: {item['reason']}" if isinstance(item, dict) else str(item)
                            for item in selected.get("missing", []))
            project["assets"] = list(rows.values())
        return _register(project, native)
    finally:
        _IMPORT.release()


def _document(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("This file is not a supported 3D MV project.")
    if not isinstance(value.get("name"), str) or len(value["name"]) > 160:
        raise ValueError("Enter a valid MV project name.")
    duration = value.get("duration")
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 3600:
        raise ValueError("The MV project has an invalid duration.")
    counts = {"tracks": 512, "assets": 256, "performers": 9, "warnings": 1024}
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


def _open_saved(archive, entries):
    from . import mv_studio_stage_particles

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
    if source is not None and (restore_split or restore_title or restore_particles or restore_ribbons):
        from . import mv_studio_timeline

        try:
            options = {}
            if restore_particles:
                options["preview_stage_particles"] = True
            if restore_ribbons:
                options["preview_stage_ribbons"] = True
            original = mv_studio_timeline.parse_timeline(source, project["name"], preview_split=restore_split,
                                                         preview_stage_title=restore_title, **options)
        except (EOFError, KeyError, TypeError, ValueError, OSError, struct.error):
            pass
        else:
            for field in ("splitScreen", "stageTitle"):
                if field in original:
                    project[field] = original[field]
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
                                ("duration", "tracks", "splitScreen", "stageMotion", "stageTitle", "stageParticles", "stageRibbons")
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
        if "performer" in result and len(project["performers"]) < 9:
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
