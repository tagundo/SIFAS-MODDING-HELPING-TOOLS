"""Apply an MV Studio project to the game ("게임에 적용"): plan, apply all, apply only the edits, restore.

Targets (from the project's game source):

- a stock 3D MV imported from the game: Elichika's ``mv_studio_stock`` replaces that MV's
  timeline (a new key in every catalog of the region, both platforms; restorable);
- an MV-only song registered by MV Studio: the registration store's ``update_mv_song`` with only
  the timelines changed (title, credit, audio and jacket are kept). A first registration stays in
  the registration panel ("MV 전용 곡으로 등록"), which this panel opens for any other project.

Modes:

- ``all`` (전체 적용): the project's whole timeline replaces what the game plays. Every platform is
  baked from its own TRUE stock by the registration bake (``mv_studio_register._bake``: unchanged
  fingerprints and timelines the game already plays are kept, a platform left out with consent
  keeps what it plays).
- ``edits`` (수정 사항만 적용): only the changes between the project and the timeline it was loaded
  from (its source snapshot, ``mv_studio._native``) go onto the timeline the game plays now, field
  by field (``mv_studio_timeline.merge_changes``), with the native rewrite that keeps every other
  object's bytes. A field the game changed differently since loading is a conflict: nothing is
  written, and the plan and the job list every conflict.
- restore (원래대로 되돌리기, stock MVs): the original timeline again.

``plan()`` writes nothing. The jobs check the game's timeline key against the plan's, validate
every payload with the store's validator before the game server stops, stop a managed game server
only around the store write and report its state; the store takes a restorable backup first.
"""
from contextlib import closing, ExitStack
import hashlib
from pathlib import Path
import re

from . import game_models as game
from . import mv_studio, mv_studio_game, mv_studio_register as register, mv_studio_timeline


PLATFORMS = register.PLATFORMS
REGIONS = register.REGIONS
MODES = ("all", "edits")
_TITLES_SHOWN = 8

# Job stages, in order (English i18n keys).
STAGES = {
    "check": "Checking the game's timeline",
    "android": register.STAGES["android"],
    "ios": register.STAGES["ios"],
    "merge-android": "Applying the edits to the Android timeline",
    "merge-ios": "Applying the edits to the iOS timeline",
    "validate": "Checking the timelines against the original MV",
    "stop": register.STAGES["stop"],
    "write": register.STAGES["write"],
    "restore": "Restoring the original MV",
    "restart": register.STAGES["restart"],
}

# Fixed user-facing messages (English i18n keys, translated by exact match in webtools/i18n.py).
NO_TARGET = "Load the MV from the game to apply it."
NO_STOCK_STORE = "This Elichika version cannot change stock MVs. Update the Elichika server app."
NO_SOURCE = "The timeline this project was loaded from is unavailable. Load the MV from the game again."
SONG_REMOVED = "The MV-only song this project was loaded from was removed. Register the project as a new song."
LAYOUT = mv_studio_timeline.MERGE_LAYOUT
CONFLICTS = ("Some edits were also changed differently in the game since this project was loaded. Use Apply all, "
             "or load the MV from the game again.")
STALE = "The game's timeline changed after the check. Check it again, then apply."
PROJECT_STALE = "The project changed after the last check. Check it again, then apply."
MODE = "Choose Apply all or Apply only the edits."
REQUEST = "The apply request is invalid."
NO_EDITS = "There are no edits since this project was loaded."
NO_RESTORE = "The MV already plays its original timeline."
SERVED_MISSING_ANDROID = ("The Android timeline the game plays now is not available. Allow the download, or apply to "
                          "iOS only.")
SERVED_MISSING_IOS = "The iOS timeline the game plays now is not available. Allow the download, or apply to Android only."
PLATFORMS_UNEQUAL = "The Android and iOS timelines the game plays now differ. Each platform keeps its own changes."
APPLIED = "Applied to the game: {title}."
RESTORED = "Restored the original MV: {title}."
CANCELLED = "Applying to the game was cancelled."
MESSAGES = (NO_TARGET, NO_STOCK_STORE, NO_SOURCE, SONG_REMOVED, LAYOUT, CONFLICTS, STALE, PROJECT_STALE, MODE, REQUEST,
            NO_EDITS, NO_RESTORE, SERVED_MISSING_ANDROID, SERVED_MISSING_IOS, PLATFORMS_UNEQUAL, APPLIED, RESTORED,
            CANCELLED, *STAGES.values())


class ConflictError(ValueError):
    """Edits-only refused: ``conflicts`` lists every field changed differently in the game."""

    def __init__(self, conflicts):
        super().__init__(CONFLICTS)
        self.conflicts = conflicts


class _Progress(register._Progress):
    def stage(self, key):
        if key not in self.stages:
            self.stages.append(key)
        index = self.stages.index(key)
        self.job.emit({"type": "mv-stage", "stage": key, "label": STAGES[key], "index": index, "total": len(self.stages)})
        self.job.progress(index, len(self.stages))
        self.job.log(STAGES[key])


def _sha(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


# ---------------------------------------------------------------- target

def _target(repo_root, project, live, language):
    """What the project applies to: {kind: stock|song, region, liveId, assetId, base, facts, game, song?},
    None (not a game import with a native timeline) or {"kind": "song", "removed": True}.

    ``game`` describes what the game plays now in the shape both stores give: {timelineKey, region,
    platforms {p: custom|stock}, revision, updatedAt, fingerprints}."""
    source = project.get("source") if isinstance(project.get("source"), dict) else {}
    if (project.get("nativeTimeline") is not True or source.get("kind") != "game" or source.get("region") not in REGIONS
            or source.get("platform") not in PLATFORMS or not register._identity(source.get("liveId"))
            or not register._identity(source.get("assetId"))):
        return None
    region = source["region"]
    if source.get("registered") is True:
        song = register._registered_source(repo_root, live, region, source["liveId"], source.get("registeredSong"))
        if song is None:
            return {"kind": "song", "region": region, "removed": True}
        if song.get("templateAssetId") is None:
            return {"kind": "song", "region": region, "unknown": True, "song": song}
        base = {"region": region, "liveId": song["templateLiveId"], "assetId": song["templateAssetId"], "fixed": True,
                "registered": True, "song": song}
        facts = register._facts(repo_root, region, song["templateLiveId"], song["templateAssetId"], language)
        return {"kind": "song", "region": region, "liveId": song["liveId"], "assetId": song["assetId"], "title": song["title"],
                "stage": facts["stage"], "base": base, "facts": facts, "game": song, "song": song, "lives": []}
    if not hasattr(live, "describe_mv_timeline"):
        raise ValueError(NO_STOCK_STORE)
    timeline = live.describe_mv_timeline(repo_root, region=region, asset_id=source["assetId"])
    if timeline.get("song"):
        return None
    facts = register._facts(repo_root, region, source["liveId"], source["assetId"], language)
    base = {"region": region, "liveId": source["liveId"], "assetId": source["assetId"], "fixed": True,
            "registered": False}
    return {"kind": "stock", "region": region, "liveId": source["liveId"], "assetId": source["assetId"],
            "title": facts["title"], "stage": facts["stage"], "base": base, "facts": facts, "game": timeline,
            "lives": _live_titles(repo_root, region, timeline.get("lives") or [], language)}


def _live_titles(repo_root, region, ids, language):
    """[{liveId, title}] of the first lives that play this MV (display only)."""
    root = Path(repo_root).resolve()
    shown = [{"liveId": live_id, "title": str(live_id)} for live_id in ids[:_TITLES_SHOWN]]
    try:
        extractor = game._extractor()
        dictionary = game._dictionary(root, region, language)
        try:
            with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as master:
                for item in shown:
                    row = master.execute("SELECT name FROM m_live WHERE live_id=?", (item["liveId"],)).fetchone()
                    if row is not None:
                        item["title"] = mv_studio_game._display(extractor, dictionary, row[0], item["liveId"])
        finally:
            if dictionary is not None:
                dictionary.close()
    except Exception:  # noqa: BLE001 - titles are optional display data
        pass
    return {"count": len(ids), "shown": shown}


def _target_summary(target):
    return {key: target.get(key) for key in ("kind", "region", "liveId", "assetId", "title", "stage")} | {
        "lives": target.get("lives") or {"count": 0, "shown": []}}


def _game_summary(target):
    game_state = target["game"]
    custom = any(state == "custom" for state in (game_state.get("platforms") or {}).values())
    override = game_state.get("override", custom) if target["kind"] == "stock" else custom
    return {"state": "custom" if override else "original", "revision": game_state.get("revision") or 0,
            "updatedAt": game_state.get("updatedAt"), "key": game_state.get("timelineKey"),
            "platforms": dict(game_state.get("platforms") or {})}


def _source_summary(project, target):
    source = project.get("source") or {}
    override = source.get("timelineOverride") if isinstance(source.get("timelineOverride"), dict) else None
    if target["kind"] == "song":
        opened = source.get("registeredSong") if isinstance(source.get("registeredSong"), dict) else {}
        return {"state": "song", "revision": opened.get("revision")}
    if override is not None:
        return {"state": "custom", "revision": override.get("revision")}
    key = source.get("timelineKey")
    if isinstance(key, str) and key != target["facts"]["timelineKey"]:
        return {"state": "custom", "revision": None}
    return {"state": "original", "revision": None}


# ---------------------------------------------------------------- timelines per platform

def _catalogued(target):
    return [platform for platform in PLATFORMS if target["facts"]["timelines"].get(platform)]


def _stock(repo_root, target, platform, blob, *, download):
    """(true stock bytes or None, status: project | local | download | missing)."""
    return register._original(repo_root, target["facts"], platform, blob, download=download)


def _served(repo_root, target, platform, blob, *, download):
    """(bytes the game serves for ``platform`` now or None, status: local | download | missing)."""
    if (target["game"].get("platforms") or {}).get(platform) == "custom":
        raw = register._registered_timelines(repo_root, target["game"], [platform]).get(platform)
        return raw, ("local" if raw is not None else "missing")
    raw, status = _stock(repo_root, target, platform, blob, download=download)
    return raw, ("local" if status == "project" else status)


def _snapshot(project):
    raw = mv_studio._native(project)
    if raw is None:
        raise ValueError(NO_SOURCE)
    return raw


def _ours(project, snapshot):
    """(base parse of the snapshot, the project's tracks normalized against it, the normalize report)."""
    base = register._parse(snapshot, "source")
    prepared = mv_studio_timeline.prepare_tracks(snapshot, project["name"], project["tracks"], base["tracks"])
    ours, report = register.normalize(base["tracks"], prepared)
    return base, ours, report


_DIGEST = re.compile(r"[0-9a-f]{16}\Z")
_MAX_SYNCED = 50000


def _synced(project, snapshot):
    """The fields this project and the game agreed on at its last successful apply (``source.applied``,
    which the page stores from the job's result), or None. It belongs to the snapshot it was made
    against: a project loaded again starts from its new snapshot."""
    applied = (project.get("source") or {}).get("applied")
    if (not isinstance(applied, dict) or applied.get("source") != _sha(snapshot)[:16]
            or not isinstance(applied.get("fields"), dict)):
        return None
    fields, count = {}, 0
    for event, values in applied["fields"].items():
        if not isinstance(event, str) or len(event) > 200 or not isinstance(values, dict):
            return None
        for field, digest in values.items():
            count += 1
            if not isinstance(field, str) or len(field) > 120 or not isinstance(digest, str) \
                    or not _DIGEST.fullmatch(digest) or count > _MAX_SYNCED:
                return None
        fields[event] = dict(values)
    return fields


def _applied(snapshot, base, ours):
    """``source.applied`` after a successful apply: what the project and the game now agree on."""
    return {"source": _sha(snapshot)[:16], "fields": mv_studio_timeline.synced_fields(base["tracks"], ours)}


def _merge(base, ours, served_raw, synced=None):
    """(merged tracks or None when nothing is taken, conflicts, taken, theirs_only, theirs parse)."""
    theirs = register._parse(served_raw, "served")
    merged, conflicts, taken, theirs_only = mv_studio_timeline.merge_changes(base["tracks"], ours, theirs["tracks"],
                                                                             synced)
    return (merged if taken else None), conflicts, taken, theirs_only, theirs


def _pending(base, ours, synced):
    """Edit counts (as register.count_edits) of what differs from the last agreed values: the edits
    since loading, or since this project's last successful apply."""
    if synced is None:
        return register.count_edits(base["tracks"], ours)
    agreed = mv_studio_timeline.synced_fields(base["tracks"], ours)
    counts = {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0}
    for track in base["tracks"]:
        for event in track["events"]:
            now, before = agreed.get(event["id"], {}), synced.get(event["id"], {})
            fields = {field for field in now.keys() | before.keys() if now.get(field) != before.get(field)}
            if not fields:
                continue
            counts["clips"] += 1
            if fields & ({"start", "duration", "label"} | register._TIMING):
                counts["timing"] += 1
            if "keyframes" in fields:
                counts["cameraShots"] += 1
            counts["values"] += len(fields - {"start", "duration", "label", "keyframes"} - register._TIMING)
    return counts


def _status(raw, status, descriptor):
    entry = {"status": status}
    if status == "download":
        size = (descriptor or {}).get("pack_size") or (descriptor or {}).get("size")
        if size:
            entry["bytes"] = size
    return entry


# ---------------------------------------------------------------- plan

def plan(repo_root, project, *, unbaked=(), language="en"):
    """What each mode would do for ``project``. Writes nothing and writes no timeline."""
    live = register.store()
    mv_studio._document(project)
    result = {"target": None, "game": None, "source": None, "platforms": {}, "edits": None, "all": None,
              "restore": {"available": False}, "notInGame": [], "warnings": [], "blocked": [],
              "managedRestart": register.managed(), "expected": None}
    target = _target(repo_root, project, live, language)
    if target is None:
        result["blocked"].append({"message": NO_TARGET})
        return result
    if target.get("removed"):
        result["blocked"].append({"message": SONG_REMOVED})
        return result
    if target.get("unknown"):
        result["blocked"].append({"message": register.BASE_UNKNOWN})
        return result
    result.update(target=_target_summary(target), game=_game_summary(target), source=_source_summary(project, target))
    result["restore"]["available"] = target["kind"] == "stock" and result["game"]["state"] == "custom"
    result["expected"] = {"key": target["game"].get("timelineKey"), "sha": {}}
    try:
        snapshot = _snapshot(project)
        base, ours, report = _ours(project, snapshot)
        synced = _synced(project, snapshot)
    except register.StructureError as error:
        result["blocked"].append({"message": register.STRUCTURE, "labels": error.labels})
        return result
    except ValueError as error:
        result["blocked"].append({"message": str(error)})
        return result
    result["notInGame"] = register._not_in_game(project, report, unbaked)
    if unbaked:
        result["blocked"].append({"message": register.UNBAKED})
    blob = register._project_blob(project, target["base"], target["facts"])
    # Edits since loading, or since this project's last successful apply.
    edits = {"counts": _pending(base, ours, synced), "conflicts": [], "apply": [], "keep": [], "download": [],
             "missing": [], "theirsOnly": 0, "blocked": [], "since": "apply" if synced is not None else "load"}
    edits["unchanged"] = not edits["counts"]["clips"]
    every = {"counts": None, "unchanged": True, "download": [], "missing": [], "blocked": []}
    parsed, served_tracks = {}, {}
    for platform in _catalogued(target):
        descriptor = target["facts"]["timelines"][platform]
        stock_raw, stock_status = _stock(repo_root, target, platform, blob, download=False)
        served_raw, served_status = _served(repo_root, target, platform, blob, download=False)
        result["platforms"][platform] = {"stock": _status(stock_raw, stock_status, descriptor),
                                         "served": _status(served_raw, served_status, descriptor)}
        if served_raw is not None:
            result["expected"]["sha"][platform] = _sha(served_raw)
        # Apply all bakes from the true stock: it needs the stock, and differs when the game plays other content.
        if stock_raw is None:
            every["download" if stock_status == "download" else "missing"].append(platform)
        else:
            parsed.setdefault("stock", register._parse(stock_raw, "stock"))
        if served_raw is not None:
            try:
                served = served_tracks[platform] = register._parse(served_raw, "served")["tracks"]
                current, _ = register.normalize(served, ours)
                if register.count_edits(served, current)["clips"]:
                    every["unchanged"] = False
            except (register.StructureError, ValueError, KeyError, TypeError):
                every["unchanged"] = False
        else:
            every["unchanged"] = False
        # Edits only: the served timeline, and the stock to validate a changed platform against.
        if served_raw is None:
            edits["download" if served_status == "download" else "missing"].append(platform)
            continue
        try:
            merged, conflicts, taken, theirs_only, _ = _merge(base, ours, served_raw, synced)
        except ValueError as error:
            edits["blocked"].append({"message": str(error), "platform": platform})
            continue
        edits["theirsOnly"] = max(edits["theirsOnly"], theirs_only)
        edits["conflicts"].extend({"platform": platform, **item} for item in conflicts)
        if merged is None:
            edits["keep"].append(platform)
            continue
        edits["apply"].append(platform)
        if stock_raw is None and platform not in edits["download"]:
            edits["download" if stock_status == "download" else "missing"].append(platform)
    if "stock" in parsed:
        try:
            normalized, _ = register.normalize(parsed["stock"]["tracks"], ours)
            every["counts"] = register.count_edits(parsed["stock"]["tracks"], normalized)
        except (register.StructureError, ValueError):
            every["counts"] = None
    if edits["conflicts"]:
        edits["blocked"].append({"message": CONFLICTS})
    if edits["unchanged"]:
        edits["blocked"].append({"message": NO_EDITS})
    if len(served_tracks) == 2 and served_tracks["android"] != served_tracks["ios"]:
        result["warnings"].append({"message": PLATFORMS_UNEQUAL})
    result["source"]["changedSince"] = bool(edits["theirsOnly"] or edits["conflicts"])
    result["edits"], result["all"] = edits, every
    return result


# ---------------------------------------------------------------- job requests

def validate_apply(repo_root, data):
    if not isinstance(data, dict):
        raise ValueError(REQUEST)
    allowed = {"mode", "project", "platforms", "download", "expected", "unbaked"}
    if set(data) - allowed or not {"mode", "project", "platforms", "expected"} <= set(data):
        raise ValueError(REQUEST)
    if data["mode"] not in MODES:
        raise ValueError(MODE)
    mv_studio._document(data["project"])
    expected = data["expected"]
    if (not isinstance(expected, dict) or set(expected) - {"key", "sha"} or not isinstance(expected.get("key"), str)
            or not 1 <= len(expected["key"]) <= 64):
        raise ValueError(STALE)
    if type(data.get("download", False)) is not bool:
        raise ValueError(REQUEST)
    unbaked = data.get("unbaked", [])
    if not isinstance(unbaked, list):
        raise ValueError(REQUEST)
    if unbaked:
        raise ValueError(register.UNBAKED)
    return {"mode": data["mode"], "project": data["project"], "platforms": register._platforms(data["platforms"]),
            "download": data.get("download", False), "expected": expected["key"]}


def validate_restore(data):
    if (not isinstance(data, dict) or set(data) != {"region", "assetId", "expected"} or data["region"] not in REGIONS
            or not register._identity(data["assetId"]) or not isinstance(data["expected"], dict)
            or not isinstance(data["expected"].get("key"), str) or not 1 <= len(data["expected"]["key"]) <= 64):
        raise ValueError(REQUEST)
    return {"region": data["region"], "assetId": data["assetId"], "expected": data["expected"]["key"]}


# ---------------------------------------------------------------- jobs

def _run(job, body, cancelled):
    if not register.reserve():
        raise ValueError(register.BUSY)
    try:
        with ExitStack() as stack:
            lifecycle = register._lifecycle(stack, job)
            summary = register._finish(job, lifecycle, body)
        register._clear_late_cancel(job)
        return summary
    except register._Cancelled:
        return cancelled
    finally:
        register.release()


def run_apply(job, repo_root, request, *, language="en"):
    """Job body of POST /api/mv-studio/apply-job. Returns the summary line."""
    return _run(job, lambda: _apply(job, repo_root, request, language), CANCELLED)


def run_restore(job, repo_root, request, *, language="en"):
    """Job body of POST /api/mv-studio/restore-job: the stock MV plays its original timeline again."""
    return _run(job, lambda: _restore(job, repo_root, request, language), CANCELLED)


def _bake_all(job, progress, repo_root, project, target, request):
    """Apply all: (timelines, originals, fingerprints) from the registration bake on the true stock."""
    bake_request = {"platforms": request["platforms"], "download": request["download"], "title": project["name"]}
    timelines, originals, fingerprints = register._bake(job, progress, repo_root, project, target["base"],
                                                        target["facts"], bake_request, target["game"],
                                                        left_out_keep=True)
    from mv_studio_live import KEEP
    timelines = dict(timelines or {})
    served = register._registered_timelines(repo_root, target["game"], [platform for platform, value in timelines.items()
                                                                        if isinstance(value, bytes)])
    for platform, raw in served.items():
        # The game already plays this content (an earlier apply wrote other bytes for it): keep it.
        if register._parse(raw, "served")["tracks"] == register._parse(timelines[platform], "verify")["tracks"]:
            timelines[platform] = KEEP
            originals.pop(platform, None)
            fingerprints.pop(platform, None)
    return timelines, originals, fingerprints


def _merge_edits(job, progress, repo_root, project, target, request):
    """Edits only: (timelines, originals) with the project's edits rewritten onto what the game plays.

    Every platform is merged before anything is rewritten, so one conflict anywhere refuses the
    whole apply (ConflictError, after an mv-conflicts event with the list). A platform whose
    served timeline or stock needs a download that was not allowed keeps what it plays, when the
    page left it out with the user's consent."""
    from mv_studio_live import KEEP
    snapshot = _snapshot(project)
    base, ours, _ = _ours(project, snapshot)
    synced = _synced(project, snapshot)
    timelines = {platform: KEEP for platform in _catalogued(target)}
    if not _pending(base, ours, synced)["clips"]:
        return timelines, {}
    blob = register._project_blob(project, target["base"], target["facts"])

    def consented(platform, status):
        return platform not in request["platforms"] and status == "download" and not request["download"]

    pending, conflicts = {}, []
    for platform in _catalogued(target):
        progress.check()
        served_raw, status = _served(repo_root, target, platform, blob, download=request["download"])
        if served_raw is None:
            if consented(platform, status):
                continue
            raise ValueError(SERVED_MISSING_IOS if platform == "ios" else SERVED_MISSING_ANDROID)
        merged, found, _, _, theirs = _merge(base, ours, served_raw, synced)
        conflicts.extend({"platform": platform, **item} for item in found)
        if merged is not None:
            pending[platform] = (served_raw, theirs, merged)
    if conflicts:
        job.emit({"type": "mv-conflicts", "conflicts": conflicts})
        raise ConflictError(conflicts)
    originals = {}
    for platform, (served_raw, theirs, merged) in pending.items():
        stock_raw, status = _stock(repo_root, target, platform, blob, download=request["download"])
        if stock_raw is None:
            if consented(platform, status):
                continue
            raise ValueError(register.ORIGINAL_MISSING_IOS if platform == "ios" else register.ORIGINAL_MISSING_ANDROID)
        if platform not in request["platforms"]:
            # The page left out a platform that needs no download: its check is out of date.
            raise ValueError(PROJECT_STALE)
        progress.check()
        progress.stage("merge-" + platform)
        output = mv_studio_timeline._rewrite_timeline(served_raw, theirs, {**theirs, "tracks": merged})
        if output == served_raw:
            continue
        timelines[platform] = output
        if status in ("project", "download"):
            originals[platform] = stock_raw
    return timelines, originals


def _changed(target, timelines):
    """Platforms the store call would change: new bytes, or back to stock from a custom timeline."""
    current = target["game"].get("platforms") or {}
    return [platform for platform in _catalogued(target) if isinstance(timelines.get(platform), bytes)
            or timelines.get(platform) is None and current.get(platform) == "custom"]


def _apply(job, repo_root, request, language):
    live = register.store()
    is_managed = register.managed()
    progress = _Progress(job, ["check"])
    progress.stage("check")
    project = request["project"]
    target = _target(repo_root, project, live, language)
    if target is None:
        raise ValueError(NO_TARGET)
    if target.get("removed"):
        raise ValueError(SONG_REMOVED)
    if target.get("unknown"):
        raise ValueError(register.BASE_UNKNOWN)
    if target["game"].get("timelineKey") != request["expected"]:
        raise ValueError(STALE)
    snapshot = _snapshot(project)
    base, ours, _ = _ours(project, snapshot)
    applied = _applied(snapshot, base, ours)
    fingerprints = {}
    if request["mode"] == "all":
        timelines, originals, fingerprints = _bake_all(job, progress, repo_root, project, target, request)
    else:
        timelines, originals = _merge_edits(job, progress, repo_root, project, target, request)
    payloads = {platform: value for platform, value in timelines.items() if isinstance(value, bytes)}
    if not _changed(target, timelines):
        job.emit({"type": "mv-timeline", "mode": request["mode"], "target": _target_summary(target), "changed": False,
                  "parts": [], "restart": "none", "backup": None, "warnings": [], "managed": is_managed,
                  "game": _game_summary(target), "applied": applied})
        job.progress(len(progress.stages), len(progress.stages))
        return register.NO_CHANGES
    progress.check()
    if payloads:
        # The store's own validator, before the game server stops: a refused payload costs no restart.
        progress.stage("validate")
        validated_asset = target["assetId"] if target["kind"] == "stock" else target["base"]["assetId"]
        live.validate_mv_timelines(repo_root, region=target["region"], asset_id=validated_asset, timelines=payloads,
                                   originals=originals or None)
    progress.check()
    region, key = target["region"], target["game"]["timelineKey"]
    stored = {platform: fingerprints[platform] for platform in payloads if platform in fingerprints}
    if target["kind"] == "stock":
        call = lambda: live.apply_mv_timeline(repo_root, region=region, asset_id=target["assetId"], timelines=timelines,
                                              expected_key=key, originals=originals or None,
                                              fingerprints=stored or None, log=job.log)
    else:
        call = lambda: live.update_mv_song(repo_root, region=region, live_id=target["liveId"], timelines=timelines,
                                           originals=originals or None, fingerprints=stored or None,
                                           expected_timeline=key, log=job.log)
    result, session = register._store_step(job, progress, repo_root, stage="write", stop=is_managed, restart=True,
                                           is_managed=is_managed, call=call)
    return _report(job, progress, repo_root, live, target, request["mode"], result, session, is_managed, applied)


def _report(job, progress, repo_root, live, target, mode, result, session, is_managed, applied=None):
    changed = bool(result.get("changed", True))
    restart = register._restart_state(session, is_managed, changed)
    if restart in ("done", "pending"):
        progress.stage("restart")
    if target["kind"] == "stock":
        game_state = result.get("timeline") or live.describe_mv_timeline(repo_root, region=target["region"],
                                                                         asset_id=target["assetId"])
    else:
        game_state = result.get("song") or target["game"]
    summary = _game_summary({**target, "game": game_state})
    job.emit({"type": "mv-timeline", "mode": mode, "target": _target_summary(target), "changed": changed,
              "parts": result.get("parts", []), "restart": restart, "backup": result.get("backup"),
              "warnings": result.get("warnings", []), "managed": is_managed, "game": summary, "applied": applied})
    job.progress(len(progress.stages), len(progress.stages))
    if not changed:
        return register.NO_CHANGES
    return (RESTORED if mode == "restore" else APPLIED).replace("{title}", str(target.get("title") or target["liveId"]))


def _restore(job, repo_root, request, language):
    live = register.store()
    is_managed = register.managed()
    progress = _Progress(job, ["check", "stop", "restore"])
    progress.stage("check")
    if not hasattr(live, "restore_mv_timeline"):
        raise ValueError(NO_STOCK_STORE)
    region, asset_id = request["region"], request["assetId"]
    timeline = live.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)
    if timeline["timelineKey"] != request["expected"]:
        raise ValueError(STALE)
    if not timeline["override"]:
        raise ValueError(NO_RESTORE)
    target = {"kind": "stock", "region": region, "liveId": None, "assetId": asset_id, "title": None, "stage": None,
              "game": timeline, "lives": None}
    title = _title(repo_root, region, timeline, language)
    target.update(title=title, liveId=(timeline.get("lives") or [None])[0])
    progress.check()
    result, session = register._store_step(
        job, progress, repo_root, stage="restore", stop=is_managed, restart=True, is_managed=is_managed,
        call=lambda: live.restore_mv_timeline(repo_root, region=region, asset_id=asset_id,
                                              expected_key=timeline["timelineKey"], log=job.log))
    return _report(job, progress, repo_root, live, target, "restore", result, session, is_managed)


def _title(repo_root, region, timeline, language):
    lives = timeline.get("lives") or []
    if not lives:
        return str(timeline["assetId"])
    shown = _live_titles(repo_root, region, lives[:1], language)["shown"]
    return shown[0]["title"] if shown else str(lives[0])


def list_timelines(repo_root, *, region):
    """Every stock MV of the region whose timeline MV Studio applied (GET /api/mv-studio/timelines)."""
    live = register.store()
    if region not in REGIONS:
        raise ValueError("Select the GL or JP catalog.")
    if not hasattr(live, "list_mv_timelines"):
        raise ValueError(NO_STOCK_STORE)
    return {"region": region, "timelines": live.list_mv_timelines(repo_root, region=region),
            "managedRestart": register.managed()}


__all__ = ("plan", "run_apply", "run_restore", "validate_apply", "validate_restore", "list_timelines", "MESSAGES",
           "STAGES")
