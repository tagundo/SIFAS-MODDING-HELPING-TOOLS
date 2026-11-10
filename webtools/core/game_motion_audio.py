"""Original, local-only motion audio resolved from Unity timelines and catalogs.

Navigation voice playback uses the actual NaviVoiceTrack clip's cue, start,
clip-in, duration and time scale. Music uses the selected live's catalog BGM.
ACB/AWB source packs stay local; browsers receive bounded PCM WAV derivatives.
"""
from collections import OrderedDict
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import wave

from . import game_models as game

MAX_EVENTS = 32
MAX_PACK_BYTES = 32 * 1024 * 1024
MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 1200
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
_AUDIO = {}
_LOCK = threading.Lock()
_SLOT = threading.BoundedSemaphore(1)
_ENVELOPES = OrderedDict()
_ENVELOPE_LOCK = threading.Lock()


def _number(value, low=0., high=MAX_SECONDS):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("The game's audio timeline contains an invalid time value.")
    return float(value)


def _class(obj, tree):
    ptr = tree.get("m_Script", {})
    script = obj.assets_file.objects.get(ptr.get("m_PathID")) if ptr.get("m_FileID", 0) == 0 else None
    return script.read_typetree().get("m_ClassName", "") if script is not None and script.type.name == "MonoScript" else ""


def timeline_events(paths):
    """Read verified navigation voice tracks, retaining their Unity timings."""
    import UnityPy
    events, seen = [], set()
    for path in paths:
        path = Path(path)
        if not 0 < path.stat().st_size <= game.MAX_MODEL_BYTES:
            raise ValueError("The motion timeline exceeds the audio inspection limit.")
        env = UnityPy.load(str(path))
        objects = list(env.objects)
        if len(objects) > 20000:
            raise ValueError("The motion has too many objects for audio inspection.")
        for obj in objects:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = obj.read_typetree()
            if _class(obj, tree) != "NaviVoiceTrack" or tree.get("m_Muted") or not tree.get("m_Enabled", True):
                continue
            clips = tree.get("m_Clips", [])
            if not isinstance(clips, list) or len(clips) > MAX_EVENTS:
                raise ValueError("The motion has too many scheduled voice clips.")
            for clip in clips:
                ptr = clip.get("m_Asset", {})
                if ptr.get("m_FileID", 0) != 0:
                    raise ValueError("The navigation voice clip points outside its timeline.")
                asset = obj.assets_file.objects.get(ptr.get("m_PathID"))
                if asset is None or asset.type.name != "MonoBehaviour":
                    continue
                data = asset.read_typetree()
                if _class(asset, data) != "NaviVoiceClip":
                    continue
                cue = data.get("cueName")
                if not isinstance(cue, str) or not 1 <= len(cue) <= 240 or "\x00" in cue:
                    raise ValueError("The navigation voice clip has an invalid cue name.")
                event = {"cue": cue, "kind": "voice", "startTime": _number(clip.get("m_Start", 0)),
                         "offset": _number(clip.get("m_ClipIn", 0)),
                         "playDuration": _number(clip.get("m_Duration", 0)),
                         "playbackRate": _number(clip.get("m_TimeScale", 1), .05, 8.)}
                if not event["playDuration"]:
                    continue
                identity = json.dumps(event, sort_keys=True)
                if identity not in seen:
                    seen.add(identity); events.append(event)
                if len(events) > MAX_EVENTS:
                    raise ValueError("The selected motion has too many scheduled audio events.")
    return sorted(events, key=lambda row: (row["startTime"], row["cue"]))


def _pack(db, name):
    if not isinstance(name, str) or not game._PACK.fullmatch(name):
        raise ValueError("The sound pack has an invalid catalog identity.")
    rows = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (name,)).fetchall()
    if not rows:
        raise ValueError("The sound pack is missing its package mapping.")
    size, meta, offset = rows[0]
    if type(size) is not int or not 0 < size <= MAX_PACK_BYTES:
        raise ValueError("The sound pack exceeds the audio import limit.")
    record = {"pack_name": name, "head": 0, "size": size, "pack_size": size, "metapack": None}
    if meta:
        if not isinstance(meta, str) or not game._PACK.fullmatch(meta) or type(offset) is not int or offset < 0:
            raise ValueError("The sound metapack mapping is invalid.")
        record["metapack"] = {"name": meta, "offset": offset, "size": size}
    return record


def _sound_candidates(repo_root, record, event):
    directory = Path(repo_root) / "assets/db" / record["region"]
    preferred = record.get("asset_database") or record.get("catalog_path")
    paths = sorted(directory.glob("asset_a_*.db"), key=lambda p: (str(p) != str(preferred), p.name != "asset_a_en.db", p.name))
    cue = event["cue"]
    result, seen = [], set()
    for path in paths:
        with closing(game._readonly(path)) as db:
            try:
                # Prefix candidates are verified against the ACB's exact cue
                # table before playback; a filename prefix never picks a wave.
                rows = db.execute("SELECT sheet_name,acb_pack_name,awb_pack_name FROM m_asset_sound WHERE sheet_name=? OR substr(?,1,length(sheet_name)+1)=sheet_name || '_' ORDER BY LENGTH(sheet_name) DESC LIMIT 16", (cue, cue)).fetchall()
            except Exception as error:
                import sqlite3
                if isinstance(error, sqlite3.OperationalError) and "no such table" in str(error):
                    continue
                raise
            for sheet, acb, awb in rows:
                identity = sheet, acb, awb
                if identity in seen:
                    continue
                seen.add(identity)
                result.append({"sheet": sheet, "acb": _pack(db, acb), "awb": _pack(db, awb) if awb and awb != "0" else None})
        if result:
            # One selected language's complete mapping wins. Mixing voices
            # between language catalogs could pair another line to this cue.
            break
    return result


def _read_pack(repo_root, descriptor, *, download, extractor, job, deadline):
    source, signature = game._source(repo_root, descriptor, extractor, job, deadline)
    game._check(job, deadline)
    if source:
        with source.open("rb") as handle:
            handle.seek(signature["pack_offset"])
            raw = handle.read(descriptor["size"])
        stat = source.stat()
        if stat.st_size != signature["size"] or stat.st_mtime_ns != signature["mtime_ns"]:
            raise ValueError("The original sound pack changed while reading.")
    else:
        if not download:
            raise ValueError("The linked sound pack is missing. Enable downloading missing assets.")
        raw = game._remote_pack(descriptor, extractor, job, deadline)
    if len(raw) != descriptor["size"]:
        raise ValueError("The linked sound pack is incomplete.")
    return bytes(raw)


def _wav_metadata(path):
    if path.is_symlink() or not path.is_file() or not 44 <= path.stat().st_size <= MAX_MEDIA_BYTES:
        raise ValueError("The decoded audio file is missing or exceeds the playback limit.")
    try:
        with wave.open(str(path), "rb") as audio:
            channels, rate, frames = audio.getnchannels(), audio.getframerate(), audio.getnframes()
            if not 1 <= channels <= 2 or not 8000 <= rate <= 192000 or audio.getsampwidth() != 2 or not 0 < frames / rate <= MAX_SECONDS:
                raise ValueError("The decoded audio format is unsupported.")
    except (wave.Error, EOFError) as error:
        raise ValueError("The decoded audio file has invalid WAV data.") from error
    return {"duration": frames / rate, "sampleRate": rate, "channels": channels, "frames": frames}


def _decoded_cache(root, key, signatures):
    manifest = root / (".audio-selection-" + key + ".json")
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 8192:
            return None
        row = json.loads(manifest.read_text(encoding="utf-8"))
        stored = row.get("sources")
        if (not isinstance(stored, list) or len(stored) != len(signatures) or
                any(current is not None and current != old for current, old in zip(signatures, stored)) or
                not re.fullmatch(r"[a-f0-9]{64}\.wav", row.get("name", ""))):
            return None
        path = root / row["name"]
        _wav_metadata(path)
        if game._sha(path) != row["sha256"]:
            return None
        return path
    except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError):
        return None


def _remember_decode(root, key, signatures, path):
    handle, name = tempfile.mkstemp(prefix=".audio-selection-", suffix=".part", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"sources": signatures, "name": path.name, "sha256": game._sha(path)}, stream)
        os.replace(temporary, root / (".audio-selection-" + key + ".json"))
    finally:
        temporary.unlink(missing_ok=True)


def _register(path):
    token = secrets.token_hex(16)
    with _LOCK:
        _AUDIO[token] = {"path": str(path), "expires": time.monotonic() + 3600}
        for old, row in list(_AUDIO.items()):
            if row["expires"] < time.monotonic():
                _AUDIO.pop(old, None)
        while len(_AUDIO) > 256:
            _AUDIO.pop(next(iter(_AUDIO)))
    return token


def mouth_envelope(path, *, point_limit=6000):
    """A bounded RMS openness guide; this does not identify spoken phonemes."""
    path = Path(path)
    original = path.stat()
    def unchanged():
        current = path.stat()
        return (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) == (
            original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns)
    meta = _wav_metadata(path)
    frames_per_point = max(round(meta["sampleRate"] * .04), math.ceil(meta["frames"] / max(1, min(6000, point_limit))))
    # Verify current bytes even on a warm import. A stat-only cache would miss
    # user replacements that preserve size/mtime, and must not change lip sync.
    identity = game._sha(path), frames_per_point
    if not unchanged():
        raise ValueError("The decoded audio changed while preparing its mouth motion. Load the motion again.")
    with _ENVELOPE_LOCK:
        cached = _ENVELOPES.get(identity)
        if cached is not None:
            _ENVELOPES.move_to_end(identity)
            return {"kind": "rms_mouth_openness", "step": cached[0], "values": list(cached[1])}
    try:
        import numpy as np
    except ImportError:
        np = None
        import array
        import sys
    values = []
    with wave.open(str(path), "rb") as stream:
        while True:
            remaining, energy, samples = frames_per_point, 0, 0
            while remaining:
                # Limit temporary arrays even for long cues or a small point
                # limit. NumPy reduces integer PCM exactly before normalization.
                wanted = min(remaining, 16384)
                block = stream.readframes(wanted)
                if not block:
                    break
                if np is not None:
                    pcm = np.frombuffer(block, dtype="<i2").astype(np.int32)
                    energy += int(np.square(pcm, dtype=np.int64).sum(dtype=np.int64))
                else:
                    pcm = array.array("h"); pcm.frombytes(block)
                    if sys.byteorder != "little":
                        pcm.byteswap()
                    energy += sum(sample * sample for sample in pcm)
                samples += len(pcm)
                remaining -= len(pcm) // meta["channels"]
            if not samples:
                break
            values.append(math.sqrt(energy / samples) / 32768.)
    if not values:
        raise ValueError("The decoded audio contains no PCM samples for its mouth motion.")
    if not unchanged():
        raise ValueError("The decoded audio changed while preparing its mouth motion. Load the motion again.")
    ordered = sorted(values)
    normalizer = max(.02, ordered[min(len(ordered) - 1, int(len(ordered) * .9))])
    step = frames_per_point / meta["sampleRate"]
    result = tuple(round(min(1., max(0., value - .002) / normalizer), 4) for value in values)
    with _ENVELOPE_LOCK:
        _ENVELOPES[identity] = step, result
        _ENVELOPES.move_to_end(identity)
        while len(_ENVELOPES) > 16:
            _ENVELOPES.popitem(last=False)
    return {"kind": "rms_mouth_openness", "step": step, "values": list(result)}


def get_audio(token):
    """Resolve only server-created local WAV tokens; never accept a path."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ValueError("The linked audio identity is invalid.")
    with _LOCK:
        row = _AUDIO.get(token)
        if row is None or row["expires"] < time.monotonic():
            raise ValueError("The linked audio expired. Load the game motion again.")
        row["expires"] = time.monotonic() + 3600
        path = Path(row["path"])
    _wav_metadata(path)
    return path, "audio/wav"


def prepare_audio(job, *, repo_root, output_root, record, timeline_paths):
    """Decode exact scheduled cues and the selected live's music into local WAVs."""
    from . import cri_audio_decode
    if not _SLOT.acquire(blocking=False):
        raise ValueError("Another linked motion soundtrack is being prepared.")
    try:
        events = timeline_events(timeline_paths)
        music = record.get("music_key", record.get("music"))
        if record.get("category") == "mv" and isinstance(music, str) and music:
            events.insert(0, {"cue": music, "kind": "music", "startTime": _number(record.get("music_start", 0)),
                              "offset": _number(record.get("music_offset", 0)), "playDuration": MAX_SECONDS, "playbackRate": 1.})
        root = game._safe_directory(Path(output_root))
        extractor = game._extractor()
        tracks, warnings, sources, source_bytes = [], [], {}, 0
        deadline = time.monotonic() + max(90, len(events) * 20)
        for event in events:
            game._check(job, deadline)
            candidates = _sound_candidates(repo_root, record, event)
            if not candidates:
                warnings.append("No game sound mapping was found for " + event["cue"] + ".")
                continue
            failure = None
            for source in candidates:
                temporary = None
                try:
                    pair = source["sheet"], source["acb"]["pack_name"], source["awb"]["pack_name"] if source["awb"] else None
                    signatures = [game._source(repo_root, descriptor, extractor, job, deadline)[1]
                                  if descriptor else None for descriptor in (source["acb"], source["awb"])]
                    selection_key = hashlib.sha256(json.dumps({"source": source, "cue": event["cue"]}, sort_keys=True).encode()).hexdigest()[:32]
                    path = _decoded_cache(root, selection_key, signatures)
                    if path is None and pair not in sources:
                        job.log("Preparing linked sound: " + source["sheet"])
                        acb = _read_pack(repo_root, source["acb"], download=record.get("download", True), extractor=extractor, job=job, deadline=deadline)
                        awb = _read_pack(repo_root, source["awb"], download=record.get("download", True), extractor=extractor, job=job, deadline=deadline) if source["awb"] else None
                        source_bytes += len(acb) + len(awb or b"")
                        if source_bytes > MAX_TOTAL_SOURCE_BYTES:
                            raise ValueError("The selected motion exceeds the linked audio memory limit.")
                        sources[pair] = acb, awb
                    if path is None:
                        acb, awb = sources[pair]
                        identity = hashlib.sha256(acb + (awb or b"") + event["cue"].encode()).hexdigest()
                        path = root / (identity + ".wav")
                        handle, temporary_name = tempfile.mkstemp(prefix=".audio-", suffix=".wav", dir=root); os.close(handle)
                        temporary = Path(temporary_name)
                        cri_audio_decode.decode_cue(acb, awb, event["cue"], temporary)
                        _wav_metadata(temporary)
                        os.replace(temporary, path); temporary = None
                        _remember_decode(root, selection_key, signatures, path)
                    meta = _wav_metadata(path)
                    token = _register(path)
                    duration = min(event["playDuration"], max(0., (meta["duration"] - event["offset"]) / event["playbackRate"]))
                    if duration <= 0:
                        raise ValueError("The scheduled audio starts beyond its decoded cue.")
                    tracks.append({**event, **meta, "playDuration": duration, "sheet": source["sheet"], "token": token,
                                   "url": "/api/viewer/game/motions/audio/" + token + ".wav", "mime": "audio/wav",
                                   "envelope": mouth_envelope(path, point_limit=max(1, 12000 // max(1, len(events))))})
                    failure = None
                    break
                except (ValueError, OSError) as error:
                    failure = str(error)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            if failure:
                warnings.append(event["cue"] + ": " + failure)
        for warning in warnings:
            job.log("Linked audio: " + warning)
        return {"version": 1, "tracks": tracks, "warnings": warnings, "source": "game_timeline_and_sound_catalog"}
    finally:
        _SLOT.release()
