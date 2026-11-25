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
  written, and the plan and the job list every conflict. After an apply, each platform's edits
  count from what the project and that platform last agreed on (``source.applied``, per platform):
  a platform left out with consent still gets the edits on a later apply.
- restore (원래대로 되돌리기, stock MVs): the original timeline again.

``plan()`` writes nothing. The jobs check the game's timeline key against the plan's, validate
every payload with the store's validator before the game server stops, stop a managed game server
only around the store write and report its state; the store takes a restorable backup first.

Another MV slot (``target``: another 3D asset of the same song, or any 3D asset id, like
Elichika's legacy "라이브 카메라 타임라인 교체"): the project's WHOLE timeline goes into that slot
("Apply all" semantics; "only the edits" is meaningless against another slot's timeline). The
project's own platform is exported onto what it was loaded from, and the other platform is
converted from it onto the source asset's own stock for that platform
(``mv_timeline_platform.convert_parsed``, verified to parse identically). By default the source
asset's stage goes with it (live_stage_master_id, stage_effect_asset_path,
live_prop_skeleton_asset_path, quality_setitng_set_id, shader_variant_asset_path); without it the
plan counts the timeline's stage-bound tracks and warns. The write goes through Elichika's
``apply_mv_timeline(..., source_asset_id=, stage=)`` per chosen region (dependencies and packages
from the SOURCE timeline, exact restore of timeline and stage), and restore works per target slot.
Each region checks the payloads against that region's own original of the source asset (GL and JP
keep it in different packs): the plan lists the downloads that needs (``cross.verify``) so the
panel asks first. A slot that already plays another slot's timeline is edited through that source
MV, not directly (its own stock no longer matches what it plays); restore stays available.
"""
from contextlib import closing, ExitStack
import hashlib
import inspect
from pathlib import Path
import re
import sqlite3

from . import game_models as game
from . import mv_studio, mv_studio_game, mv_studio_register as register, mv_studio_timeline
from . import mv_timeline_platform as platform_conversion


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
# Another MV slot.
NO_CROSS_STORE = ("This Elichika version cannot put an MV into another slot. Update the Elichika server app to apply "
                  "it to another 3D MV.")
TARGET_REQUEST = "Choose the MV slot to apply to."
TARGET_MISSING = "3D MV {asset} is not in the {region} game."
TARGET_SONG = "3D MV {asset} belongs to an MV-only song. Choose a stock 3D MV."
SOURCE_MISSING = "3D MV {asset} this project was loaded from is not in the {region} game."
CROSS_SONG = "A project opened from an MV-only song can only update that song. Load a stock MV to apply it to another slot."
CROSS_EDITS = "Only Apply all can put a timeline into another MV slot."
CROSS_MISSING_ANDROID = "No Android timeline can be made for the chosen slot. Apply to iOS only, or cancel."
CROSS_MISSING_IOS = "No iOS timeline can be made for the chosen slot. Apply to Android only, or cancel."
PARTIAL_GL = "Only the GL game was changed. The JP game could not be changed; see the job log."
PARTIAL_JP = "Only the JP game was changed. The GL game could not be changed; see the job log."
CROSS_VERIFY_DOWNLOAD = ("Checking the timeline for the other region needs the source MV's original timeline from that "
                         "region's game. Allow the download, or apply to this region only.")
# A slot that plays a timeline put there from another slot: it is edited through that source MV.
SLOT_FROM_OTHER = ("This slot plays the timeline of 3D {source}, put here from another slot. Load 3D {source} and apply "
                   "it to this slot, or restore this slot first.")
SLOT_FROM_OTHER_JOB = ("This slot plays a timeline put here from another 3D MV. Load that MV and apply it to this slot, "
                       "or restore this slot first.")
MESSAGES = (NO_TARGET, NO_STOCK_STORE, NO_SOURCE, SONG_REMOVED, LAYOUT, CONFLICTS, STALE, PROJECT_STALE, MODE, REQUEST,
            NO_EDITS, NO_RESTORE, SERVED_MISSING_ANDROID, SERVED_MISSING_IOS, PLATFORMS_UNEQUAL, APPLIED, RESTORED,
            CANCELLED, NO_CROSS_STORE, TARGET_REQUEST, TARGET_MISSING, TARGET_SONG, SOURCE_MISSING, CROSS_SONG,
            CROSS_EDITS, CROSS_MISSING_ANDROID, CROSS_MISSING_IOS, PARTIAL_GL, PARTIAL_JP, CROSS_VERIFY_DOWNLOAD,
            SLOT_FROM_OTHER, SLOT_FROM_OTHER_JOB, *STAGES.values())

# The m_live_3d_asset fields "Change the stage too" copies from the source asset (the legacy tool's
# set, plus the prop skeleton the legacy tool leaves behind).
STAGE_FIELDS = ("live_stage_master_id", "stage_effect_asset_path", "live_prop_skeleton_asset_path",
                "quality_setitng_set_id", "shader_variant_asset_path")


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
    """{platform: fields} the project and each platform's game timeline agreed on at that
    platform's last successful apply (``source.applied``, which the page stores from the job's
    result; ``fields`` as ``mv_studio_timeline.synced_fields``). A platform without a record (never
    applied, or left out with consent) merges against the loaded snapshot. The record belongs to
    the snapshot it was made against: a project loaded again starts from its new snapshot, and a
    malformed record counts as none."""
    applied = (project.get("source") or {}).get("applied")
    if (not isinstance(applied, dict) or applied.get("source") != _sha(snapshot)[:16]
            or not isinstance(applied.get("platforms"), dict) or set(applied["platforms"]) - set(PLATFORMS)):
        return {}
    result, count = {}, 0
    for platform, entries in applied["platforms"].items():
        if not isinstance(entries, dict):
            return {}
        fields = {}
        for event, values in entries.items():
            if not isinstance(event, str) or len(event) > 200 or not isinstance(values, dict):
                return {}
            for field, entry in values.items():
                count += 1
                digest, label = mv_studio_timeline.synced_digest(entry)
                if (not isinstance(field, str) or len(field) > 120 or digest is None or not _DIGEST.fullmatch(digest)
                        or label is not None and len(label) > 64 or count > _MAX_SYNCED):
                    return {}
            fields[event] = dict(values)
        result[platform] = fields
    return result


def _applied(snapshot, base, ours, synced, advanced):
    """``source.applied`` after a successful job: the platforms in ``advanced`` (written, or found
    to play the project already) now agree with the project; every other platform keeps its record
    (or has none). None when no platform has one."""
    agreed = mv_studio_timeline.synced_fields(base["tracks"], ours)
    platforms = {platform: (agreed if platform in advanced else synced[platform]) for platform in PLATFORMS
                 if platform in advanced or platform in synced}
    return {"source": _sha(snapshot)[:16], "platforms": platforms} if platforms else None


def _merge(base, ours, served_raw, synced=None):
    """(merged tracks or None when nothing is taken, conflicts, taken, theirs_only, theirs parse)."""
    theirs = register._parse(served_raw, "served")
    merged, conflicts, taken, theirs_only = mv_studio_timeline.merge_changes(base["tracks"], ours, theirs["tracks"],
                                                                             synced)
    return (merged if taken else None), conflicts, taken, theirs_only, theirs


def _pending(base, ours, synced):
    """Edit counts (as register.count_edits) of what differs from one platform's last agreed values:
    the edits since loading (``synced`` None), or since this project's last apply to it."""
    if synced is None:
        return register.count_edits(base["tracks"], ours)
    agreed = mv_studio_timeline.synced_fields(base["tracks"], ours)
    counts = {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0}
    digest = lambda entries, field: mv_studio_timeline.synced_digest(entries.get(field))[0]  # noqa: E731
    for track in base["tracks"]:
        for event in track["events"]:
            now, before = agreed.get(event["id"], {}), synced.get(event["id"], {})
            fields = {field for field in now.keys() | before.keys() if digest(now, field) != digest(before, field)}
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

def plan(repo_root, project, *, unbaked=(), language="en", target=None):
    """What each mode would do for ``project``. Writes nothing and writes no timeline.

    ``target`` ({"assetId", "stage", "regions"}) chooses another MV slot; None (or the loaded
    asset) is the slot the project was loaded from."""
    live = register.store()
    mv_studio._document(project)
    cross = _cross_request(project, target)
    result = {"target": None, "game": None, "source": None, "platforms": {}, "edits": None, "all": None,
              "restore": {"available": False}, "notInGame": [], "warnings": [], "blocked": [],
              "managedRestart": register.managed(), "expected": None, "slots": [], "loaded": None, "cross": None}
    loaded = _target(repo_root, project, live, language)
    if loaded is None:
        result["blocked"].append({"message": NO_TARGET})
        return result
    if loaded.get("removed"):
        result["blocked"].append({"message": SONG_REMOVED})
        return result
    if loaded.get("unknown"):
        result["blocked"].append({"message": register.BASE_UNKNOWN})
        return result
    if loaded["kind"] == "stock":
        result["slots"] = _slots(repo_root, loaded, (project.get("source") or {}).get("platform"), language)
        result["loaded"] = {"assetId": loaded["assetId"], "liveId": loaded["liveId"], "region": loaded["region"],
                            "title": loaded["title"], "stage": loaded["stage"]}
    if cross is not None:
        return _cross_plan(repo_root, project, live, loaded, cross, result, unbaked, language)
    target = loaded
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
    # Edits since loading, or since this project's last successful apply, per platform: a platform
    # left out of an earlier apply still needs the edits the other one already has.
    pending = {platform: _pending(base, ours, synced.get(platform)) for platform in _catalogued(target)}
    shown = max(pending, key=lambda platform: pending[platform]["clips"], default=None)
    edits = {"counts": pending[shown] if shown else register.count_edits(base["tracks"], ours), "conflicts": [],
             "apply": [], "keep": [], "download": [], "missing": [], "theirsOnly": 0, "blocked": [],
             "since": "apply" if shown in synced else "load",
             "pending": {platform: counts["clips"] for platform, counts in pending.items()}}
    edits["unchanged"] = not edits["counts"]["clips"]
    every = {"counts": None, "unchanged": True, "download": [], "missing": [], "blocked": []}
    # An unedited game import bakes nothing: every platform plays the stock rows, no original is read.
    stock_unchanged = register._unchanged_stock(blob, project["tracks"])
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
            if not stock_unchanged:
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
            merged, conflicts, taken, theirs_only, _ = _merge(base, ours, served_raw, synced.get(platform))
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
    if stock_unchanged:
        every["counts"] = {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0}
    elif "stock" in parsed:
        try:
            normalized, _ = register.normalize(parsed["stock"]["tracks"], ours)
            every["counts"] = register.count_edits(parsed["stock"]["tracks"], normalized)
        except (register.StructureError, ValueError):
            every["counts"] = None
    if edits["conflicts"]:
        edits["blocked"].append({"message": CONFLICTS})
    if edits["unchanged"]:
        edits["blocked"].append({"message": NO_EDITS})
    foreign = _foreign_source(target)
    if foreign is not None:
        # The slot plays another asset's timeline: edits and Apply all would be checked against this
        # slot's own stock and refused. Restore stays available.
        for part in (edits, every):
            part["blocked"].insert(0, {"message": SLOT_FROM_OTHER, "values": {"source": foreign}})
    if len(served_tracks) == 2 and served_tracks["android"] != served_tracks["ios"]:
        result["warnings"].append({"message": PLATFORMS_UNEQUAL})
    result["source"]["changedSince"] = bool(edits["theirsOnly"] or edits["conflicts"])
    result["edits"], result["all"] = edits, every
    return result


# ---------------------------------------------------------------- job requests

def validate_apply(repo_root, data):
    if not isinstance(data, dict):
        raise ValueError(REQUEST)
    allowed = {"mode", "project", "platforms", "download", "expected", "unbaked", "target"}
    if set(data) - allowed or not {"mode", "project", "platforms", "expected"} <= set(data):
        raise ValueError(REQUEST)
    if data["mode"] not in MODES:
        raise ValueError(MODE)
    mv_studio._document(data["project"])
    cross = _cross_request(data["project"], data.get("target"))
    expected = data["expected"]
    if (not isinstance(expected, dict) or set(expected) - {"key", "sha", "keys"} or not isinstance(expected.get("key"), str)
            or not 1 <= len(expected["key"]) <= 64):
        raise ValueError(STALE)
    if cross is not None:
        keys = expected.get("keys")
        if data["mode"] != "all":
            raise ValueError(CROSS_EDITS)
        if (not isinstance(keys, dict) or set(keys) != set(cross["regions"])
                or any(not isinstance(key, str) or not 1 <= len(key) <= 64 for key in keys.values())):
            raise ValueError(STALE)
        cross = {**cross, "keys": dict(keys)}
    if type(data.get("download", False)) is not bool:
        raise ValueError(REQUEST)
    unbaked = data.get("unbaked", [])
    if not isinstance(unbaked, list):
        raise ValueError(REQUEST)
    if unbaked:
        raise ValueError(register.UNBAKED)
    return {"mode": data["mode"], "project": data["project"], "platforms": register._platforms(data["platforms"]),
            "download": data.get("download", False), "expected": expected["key"], "target": cross}


def validate_restore(data):
    """{"region", "assetId", "expected": {"key"}} (one region) or {"assetId", "regions": {region: {"key"}}}
    (a slot applied in several regions). Returns {"assetId", "regions": {region: key}}."""
    if isinstance(data, dict) and set(data) == {"assetId", "regions"}:
        regions = data["regions"]
        if (not register._identity(data["assetId"]) or not isinstance(regions, dict) or not regions
                or set(regions) - set(REGIONS) or any(not isinstance(value, dict) or set(value) != {"key"}
                                                      or not isinstance(value["key"], str) or not 1 <= len(value["key"]) <= 64
                                                      for value in regions.values())):
            raise ValueError(REQUEST)
        return {"assetId": data["assetId"], "regions": {region: regions[region]["key"] for region in REGIONS
                                                        if region in regions}}
    if (not isinstance(data, dict) or set(data) != {"region", "assetId", "expected"} or data["region"] not in REGIONS
            or not register._identity(data["assetId"]) or not isinstance(data["expected"], dict)
            or not isinstance(data["expected"].get("key"), str) or not 1 <= len(data["expected"]["key"]) <= 64):
        raise ValueError(REQUEST)
    return {"assetId": data["assetId"], "regions": {data["region"]: data["expected"]["key"]}}


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
    """Edits only: (timelines, originals, agreed) with the project's edits rewritten onto what the
    game plays; ``agreed`` lists the platforms that play the project's values once the job is done.

    Every platform is merged before anything is rewritten, so one conflict anywhere refuses the
    whole apply (ConflictError, after an mv-conflicts event with the list). A platform whose
    served timeline or stock needs a download that was not allowed keeps what it plays, when the
    page left it out with the user's consent (and keeps its own record of the last apply)."""
    from mv_studio_live import KEEP
    snapshot = _snapshot(project)
    base, ours, _ = _ours(project, snapshot)
    synced = _synced(project, snapshot)
    timelines = {platform: KEEP for platform in _catalogued(target)}
    # Each platform against its own last agreed values: one left out of an earlier apply still
    # takes the edits the other platform already has.
    waiting = [platform for platform in _catalogued(target) if _pending(base, ours, synced.get(platform))["clips"]]
    agreed = [platform for platform in _catalogued(target) if platform not in waiting]
    if not waiting:
        return timelines, {}, agreed
    blob = register._project_blob(project, target["base"], target["facts"])

    def consented(platform, status):
        return platform not in request["platforms"] and status == "download" and not request["download"]

    pending, conflicts = {}, []
    for platform in waiting:
        progress.check()
        served_raw, status = _served(repo_root, target, platform, blob, download=request["download"])
        if served_raw is None:
            if consented(platform, status):
                continue
            raise ValueError(SERVED_MISSING_IOS if platform == "ios" else SERVED_MISSING_ANDROID)
        merged, found, _, _, theirs = _merge(base, ours, served_raw, synced.get(platform))
        conflicts.extend({"platform": platform, **item} for item in found)
        if merged is not None:
            pending[platform] = (served_raw, theirs, merged)
        elif not found:
            agreed.append(platform)  # The game already plays every edit.
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
        agreed.append(platform)
        if output == served_raw:
            continue  # The rewrite changes no byte: nothing to write for this platform.
        timelines[platform] = output
        if status in ("project", "download"):
            originals[platform] = stock_raw
    return timelines, originals, agreed


def _foreign_source(target):
    """The 3D asset id whose timeline a stock slot plays when it was put there from another slot, else None."""
    if target.get("kind") != "stock":
        return None
    source = (target.get("game") or {}).get("source")
    asset = source.get("assetId") if isinstance(source, dict) else None
    return asset if register._identity(asset) and asset != target.get("assetId") else None


def _changed(target, timelines):
    """Platforms the store call would change: new bytes, or back to stock from a custom timeline."""
    current = target["game"].get("platforms") or {}
    return [platform for platform in _catalogued(target) if isinstance(timelines.get(platform), bytes)
            or timelines.get(platform) is None and current.get(platform) == "custom"]


def _apply(job, repo_root, request, language):
    if request.get("target") is not None:
        return _apply_cross(job, repo_root, request, language)
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
    if _foreign_source(target) is not None:
        raise ValueError(SLOT_FROM_OTHER_JOB)
    snapshot = _snapshot(project)
    base, ours, _ = _ours(project, snapshot)
    fingerprints = {}
    if request["mode"] == "all":
        timelines, originals, fingerprints = _bake_all(job, progress, repo_root, project, target, request)
        # Every platform asked for plays the whole project; one left out with consent keeps what it plays.
        agreed = [platform for platform in _catalogued(target) if platform in request["platforms"]]
    else:
        timelines, originals, agreed = _merge_edits(job, progress, repo_root, project, target, request)
    # What the project and each platform agree on after this job (the page keeps it as source.applied).
    applied = _applied(snapshot, base, ours, _synced(project, snapshot), agreed)
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
    asset_id = request["assetId"]
    timelines = {}
    for region, key in request["regions"].items():
        timeline = live.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)
        if timeline["timelineKey"] != key:
            raise ValueError(STALE)
        if timeline["override"]:
            timelines[region] = timeline
    if not timelines:
        raise ValueError(NO_RESTORE)
    # The store restores the timeline and, for a slot that took another MV's stage, that stage too.
    region, timeline = next(iter(timelines.items()))
    target = {"kind": "stock", "region": region, "liveId": None, "assetId": asset_id, "title": None, "stage": None,
              "game": timeline, "lives": None}
    title = _title(repo_root, region, timeline, language)
    target.update(title=title, liveId=(timeline.get("lives") or [None])[0])
    progress.check()

    def call():
        return _each_region(job, list(timelines), lambda name: live.restore_mv_timeline(
            repo_root, region=name, asset_id=asset_id, expected_key=timelines[name]["timelineKey"], log=job.log))

    result, session = register._store_step(job, progress, repo_root, stage="restore", stop=is_managed, restart=True,
                                           is_managed=is_managed, call=call)
    return _report(job, progress, repo_root, live, target, "restore", result, session, is_managed)


def _each_region(job, regions, write):
    """Run one store write per region (one stop of the game server). A failure after an earlier
    region was written names the region that changed (PARTIAL_*); the job log has the reason."""
    results = {}
    for region in regions:
        try:
            results[region] = write(region)
        except Exception as error:
            if not results:
                raise
            job.log(f"{region.upper()}: {error}")
            raise ValueError(PARTIAL_GL if "gl" in results else PARTIAL_JP) from error
    first = results[regions[0]]
    if len(results) == 1:
        return first
    return {**first, "changed": any(result.get("changed", True) for result in results.values()),
            "parts": sorted({part for result in results.values() for part in result.get("parts", [])}),
            "backup": "; ".join(str(result["backup"]) for result in results.values() if result.get("backup")) or None,
            "warnings": [warning for result in results.values() for warning in result.get("warnings", [])],
            "regions": {region: {"changed": result.get("changed", True), "backup": result.get("backup")}
                        for region, result in results.items()}}


# ---------------------------------------------------------------- another MV slot

def _cross_request(project, value):
    """{"assetId", "stage", "regions"} for another MV slot, or None for the slot the project was loaded from.

    ``regions`` starts with the project's own region; "both" adds the other region's slot with the
    same 3D asset id (the legacy tool's GL + JP choice)."""
    if value is None:
        return None
    source = project.get("source") if isinstance(project.get("source"), dict) else {}
    if (not isinstance(value, dict) or set(value) - {"assetId", "stage", "regions"}
            or not register._identity(value.get("assetId")) or type(value.get("stage", True)) is not bool):
        raise ValueError(TARGET_REQUEST)
    if value["assetId"] == source.get("assetId"):
        return None
    own = source.get("region")
    regions = value.get("regions", [own])
    if (not isinstance(regions, list) or not regions or len(set(regions)) != len(regions) or set(regions) - set(REGIONS)
            or own not in regions):
        raise ValueError(TARGET_REQUEST)
    return {"assetId": value["assetId"], "stage": value.get("stage", True),
            "regions": [own] + [region for region in REGIONS if region in regions and region != own]}


def _cross_supported(live):
    """Whether the store can put a timeline into another slot (Elichika's apply_mv_timeline with
    ``source_asset_id`` and ``stage``)."""
    try:
        parameters = inspect.signature(live.apply_mv_timeline).parameters
    except (AttributeError, TypeError, ValueError):
        return False
    return "stage" in parameters and "source_asset_id" in parameters


def _store_cross(live, repo_root, *, region, asset_id, source_asset_id, timelines, expected_key, originals, stage, log):
    """One region's write. ``stage``: the source's STAGE_FIELDS (written exactly), or None: the slot
    plays its own original stage. A platform without a timeline (None) plays the source's original
    timeline; the store's restore puts the slot's timeline and stage back exactly."""
    return live.apply_mv_timeline(repo_root, region=region, asset_id=asset_id, timelines=timelines,
                                  expected_key=expected_key, originals=originals or None, stage=stage, log=log,
                                  source_asset_id=source_asset_id)


def _source_stage(live, repo_root, region, asset_id):
    """The STAGE_FIELDS "Change the stage too" carries: the source asset's STOCK stage (the store's
    describe ``stage.stock``), or its current masterdata values with an older store; None when the
    asset is not in the region."""
    try:
        described = live.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)
    except (ValueError, AttributeError):
        described = None
    stock = ((described or {}).get("stage") or {}).get("stock")
    if isinstance(stock, dict) and set(stock) == set(STAGE_FIELDS):
        return dict(stock)
    return stage_fields(repo_root, region, asset_id)


def stage_fields(repo_root, region, asset_id):
    """The STAGE_FIELDS of a 3D asset as the region's masterdata has them now, or None."""
    path = Path(repo_root).resolve() / "assets/db" / region / "masterdata.db"
    try:
        with closing(game._readonly(path)) as master:
            columns = {row[1] for row in master.execute("PRAGMA table_info(m_live_3d_asset)")}
            present = [field for field in STAGE_FIELDS if field in columns]
            row = master.execute(f"SELECT {','.join(present)} FROM m_live_3d_asset WHERE id=?", (asset_id,)).fetchone()
    except (sqlite3.Error, OSError, ValueError):
        return None
    if row is None:
        return None
    values = dict(zip(present, row))
    return {field: values.get(field) for field in STAGE_FIELDS}


def _stage_name(repo_root, region, stage_id, language):
    """(stage name, scene) of an m_live_stage row for display; (None, None) when unknown."""
    root = Path(repo_root).resolve()
    try:
        with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as master:
            master.row_factory = sqlite3.Row
            stage = master.execute("SELECT * FROM m_live_stage WHERE id=?", (stage_id,)).fetchone()
        if stage is None:
            return None, None
        scene = stage["scene_name"] if "scene_name" in stage.keys() else None
        name = None
        extractor, dictionary = game._extractor(), game._dictionary(root, region, language)
        try:
            if "stage_name" in stage.keys():
                name = mv_studio_game._display(extractor, dictionary, stage["stage_name"], scene)
        finally:
            if dictionary is not None:
                dictionary.close()
        return name, (re.sub(r"_s\d+$", "", scene) if isinstance(scene, str) else None)
    except Exception:  # noqa: BLE001 - display data only
        return None, None


def _slots(repo_root, loaded, platform, language):
    """The MV slots of the loaded song as MV Studio's game picker lists them (display and choice)."""
    try:
        listing = mv_studio_game.catalog(repo_root, region=loaded["region"], platform=platform or "android",
                                         language=language, search=str(loaded["liveId"]))
    except Exception:  # noqa: BLE001 - the picker is optional; "another 3D asset id" still works
        return []
    song = next((item for item in listing.get("songs", []) if item.get("id") == loaded["liveId"]), None)
    if song is None:
        return []
    return [{key: variant.get(key) for key in ("id", "label", "position", "scene", "source")}
            for variant in song.get("variants", [])]


def _cross_plan(repo_root, project, live, loaded, cross, result, unbaked, language):
    """The plan for another MV slot: the whole timeline, the stage choice, the lives that change,
    stage-bound tracks, and per platform whether its timeline can be made (``all.download``:
    converted from the project's platform once the source's original is downloaded;
    ``all.missing``: cannot be made)."""
    asset_id, own_region, source_asset = cross["assetId"], loaded["region"], loaded["assetId"]
    result["edits"] = None
    every = {"counts": None, "unchanged": False, "download": [], "missing": [], "blocked": [], "cross": True}
    result["all"] = every
    if loaded["kind"] != "stock":
        result["blocked"].append({"message": CROSS_SONG})
        return result
    foreign = _foreign_source(loaded)
    if foreign is not None:
        result["blocked"].append({"message": SLOT_FROM_OTHER, "values": {"source": foreign}})
    supported = _cross_supported(live)
    if not supported:
        result["blocked"].append({"message": NO_CROSS_STORE})
    regions, keys = {}, {}
    for region in cross["regions"]:
        entry = regions[region] = {"available": False}
        try:
            described = live.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)
        except ValueError:
            result["blocked"].append({"message": TARGET_MISSING, "values": {"asset": asset_id, "region": region.upper()}})
            continue
        if described.get("song"):
            result["blocked"].append({"message": TARGET_SONG, "values": {"asset": asset_id}})
            continue
        source_stage = _source_stage(live, repo_root, region, source_asset)
        if source_stage is None:
            result["blocked"].append({"message": SOURCE_MISSING, "values": {"asset": source_asset,
                                                                            "region": region.upper()}})
            continue
        now = stage_fields(repo_root, region, asset_id) or {}
        stage_name, scene = _stage_name(repo_root, region, now.get("live_stage_master_id"), language)
        keys[region] = described["timelineKey"]
        entry.update(available=True, key=described["timelineKey"],
                     game=_game_summary({"kind": "stock", "game": described}),
                     lives=_live_titles(repo_root, region, described.get("lives") or [], language),
                     stage=stage_name, scene=scene, stageNow=now, stageAfter=source_stage if cross["stage"] else None,
                     restore=bool(described.get("override")))
    own = regions.get(own_region) or {}
    lives = own.get("lives") or {"count": 0, "shown": []}
    result["target"] = {"kind": "stock", "region": own_region, "liveId": (lives["shown"][0]["liveId"] if lives["shown"]
                                                                          else None),
                        "assetId": asset_id, "title": lives["shown"][0]["title"] if lives["shown"] else str(asset_id),
                        "stage": own.get("stage"), "lives": lives}
    result["game"] = own.get("game")
    result["source"] = _source_summary(project, loaded)
    result["restore"] = {"available": any(entry.get("restore") for entry in regions.values()),
                         "regions": [region for region, entry in regions.items() if entry.get("restore")]}
    result["expected"] = {"key": keys.get(own_region) or "-", "keys": keys}
    try:
        snapshot = _snapshot(project)
        base, ours, report = _ours(project, snapshot)
    except register.StructureError as error:
        result["blocked"].append({"message": register.STRUCTURE, "labels": error.labels})
        return result
    except ValueError as error:
        result["blocked"].append({"message": str(error)})
        return result
    result["notInGame"] = register._not_in_game(project, report, unbaked)
    if unbaked:
        result["blocked"].append({"message": register.UNBAKED})
    bound = platform_conversion.stage_bound_tracks(ours)
    blob = register._project_blob(project, loaded["base"], loaded["facts"])
    own_platform = blob.get("platform") or (project.get("source") or {}).get("platform")
    for platform in _catalogued(loaded):
        descriptor = loaded["facts"]["timelines"][platform]
        if platform == own_platform:
            result["platforms"][platform] = {"payload": {"status": "project"}}
            continue
        stock_raw, status = _stock(repo_root, loaded, platform, blob, download=False)
        status = "local" if stock_raw is not None else status
        result["platforms"][platform] = {"payload": _status(stock_raw, status, descriptor)}
        if status in ("download", "missing"):
            every[status].append(platform)
    for platform in PLATFORMS:
        if platform not in result["platforms"] and platform != own_platform:
            result["platforms"][platform] = {"payload": {"status": "missing"}}
            every["missing"].append(platform)
    verify = _cross_originals(repo_root, loaded, regions, own_region, own_platform, blob, result["platforms"])
    result["cross"] = {"assetId": asset_id, "stage": cross["stage"], "regions": regions, "supported": supported,
                       "verify": verify,
                       "platform": own_platform, "stageBound": {"count": len(bound), "labels": bound[:12]},
                       "source": {"assetId": source_asset, "region": own_region, "title": loaded["title"],
                                  "stage": loaded["stage"], "stageFields": stage_fields(repo_root, own_region,
                                                                                        source_asset)}}
    return result


def _cross_originals(repo_root, loaded, regions, own_region, own_platform, blob, payloads):
    """Per chosen region, whether the source asset's original timeline of each platform is at hand for
    the store's check (``regions[region]["originals"]``: {platform: {status: project|local|download|missing,
    bytes?}}). GL and JP keep the same stock timeline in different packs, so each region has its own.

    Returns the downloads the check needs beyond the conversion's own (the own region's other
    platform is already ``all.download``): [{region, platform, bytes?}]."""
    verify = []
    source_asset = loaded["assetId"]
    for region, entry in regions.items():
        if not entry.get("available"):
            continue
        statuses = {}
        for platform in _catalogued(loaded):
            if region == own_region and platform != own_platform:
                statuses[platform] = dict(payloads[platform]["payload"])  # the conversion's template
                continue
            if region == own_region:
                raw, status = _stock(repo_root, loaded, platform, blob, download=False)
                status = "local" if raw is not None and status != "project" else status
                statuses[platform] = _status(raw, status, loaded["facts"]["timelines"][platform])
            else:
                try:
                    statuses[platform] = platform_conversion.template_status(repo_root, region, source_asset, platform)
                except ValueError:
                    statuses[platform] = {"status": "missing"}
            if statuses[platform]["status"] == "download":
                verify.append({"region": region, "platform": platform,
                               **({"bytes": statuses[platform]["bytes"]} if statuses[platform].get("bytes") else {})})
        entry["originals"] = statuses
    return verify


def _region_originals(repo_root, region, source_asset, payloads, *, download):
    """{platform: original} of the source asset in another region for the store's check and write
    (downloaded when allowed); a platform without a catalogued original is left to the store's refusal."""
    originals = {}
    for platform in sorted(payloads):
        try:
            originals[platform] = platform_conversion.template(repo_root, region, source_asset, platform,
                                                               download=download)
        except ValueError as error:
            if str(error) == platform_conversion.TEMPLATE_DOWNLOAD:
                raise ValueError(CROSS_VERIFY_DOWNLOAD) from error
            if str(error) not in (platform_conversion.NO_TEMPLATE, platform_conversion.NO_ASSET):
                raise
    return originals


def _cross_payloads(repo_root, project, loaded, wanted, *, download, progress=None):
    """({platform: bytes}, originals) of the project's WHOLE timeline for ``wanted`` platforms.

    The project's own platform is exported onto what it was loaded from (the source asset's stock,
    or the timeline the game played); every other platform is converted from that result onto the
    source asset's own stock for that platform and verified to parse identically
    (``mv_timeline_platform.convert_parsed``). ``originals`` holds downloaded stocks for the store's
    validator."""
    blob = register._project_blob(project, loaded["base"], loaded["facts"])
    if blob["kind"] not in ("stock", "mod") or blob["raw"] is None:
        raise ValueError(CROSS_SONG)
    own = blob["platform"] or project["source"]["platform"]
    reference = register._parse(blob["raw"], "source")
    normalized, _ = register.normalize(reference["tracks"], project["tracks"])
    if progress is not None:
        progress.check()
        progress.stage(own)
    own_payload = register._export(blob["raw"], project["name"], normalized)
    payloads, originals = {}, {}
    for platform in PLATFORMS:
        if platform not in wanted:
            continue
        if platform == own:
            payloads[platform] = own_payload
            stock_raw, status = _stock(repo_root, loaded, platform, blob, download=download)
        else:
            if progress is not None:
                progress.check()
                progress.stage(platform)
            stock_raw, status = _stock(repo_root, loaded, platform, blob, download=download)
            if stock_raw is None:
                raise ValueError(CROSS_MISSING_IOS if platform == "ios" else CROSS_MISSING_ANDROID)
            payloads[platform] = platform_conversion.convert_parsed(own_payload, stock_raw, name=project["name"])
        if stock_raw is not None and status in ("project", "download"):
            originals[platform] = stock_raw
    return payloads, originals


def _apply_cross(job, repo_root, request, language):
    live = register.store()
    is_managed = register.managed()
    progress = _Progress(job, ["check"])
    progress.stage("check")
    project, cross = request["project"], request["target"]
    loaded = _target(repo_root, project, live, language)
    if loaded is None:
        raise ValueError(NO_TARGET)
    if loaded.get("removed"):
        raise ValueError(SONG_REMOVED)
    if loaded["kind"] != "stock":
        raise ValueError(CROSS_SONG)
    if _foreign_source(loaded) is not None:
        raise ValueError(SLOT_FROM_OTHER_JOB)
    if not _cross_supported(live):
        raise ValueError(NO_CROSS_STORE)
    asset_id, own_region, source_asset = cross["assetId"], loaded["region"], loaded["assetId"]
    described, stages = {}, {}
    for region in cross["regions"]:
        try:
            described[region] = live.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)
        except ValueError as error:
            raise ValueError(STALE) from error
        if described[region]["timelineKey"] != cross["keys"].get(region) or described[region].get("song"):
            raise ValueError(STALE)
        stages[region] = _source_stage(live, repo_root, region, source_asset) if cross["stage"] else None
        if cross["stage"] and stages[region] is None:
            raise ValueError(STALE)
    _ours(project, _snapshot(project))  # structure check before anything is baked
    try:
        payloads, originals = _cross_payloads(repo_root, project, loaded, request["platforms"],
                                              download=request["download"], progress=progress)
    except platform_conversion.ConversionError as error:
        job.log(str(error) + " " + ", ".join(error.labels))
        raise
    if not payloads:
        raise ValueError(register.PLATFORMS_CHOICE)
    progress.check()
    progress.stage("validate")
    # The payloads are the SOURCE asset's timeline: checked against its true stock in each region,
    # whose originals are that region's own (GL and JP keep them in different packs).
    checked = {region: (dict(originals) if region == own_region else
                        _region_originals(repo_root, region, source_asset, payloads, download=request["download"]))
               for region in cross["regions"]}
    for region in cross["regions"]:
        progress.check()
        live.validate_mv_timelines(repo_root, region=region, asset_id=source_asset, timelines=payloads,
                                   originals=checked[region] or None)
    # A platform left out with consent plays the source MV's original timeline (the store refuses
    # KEEP while the slot's source changes, and the slot's old timeline would not match the new stage).
    timelines = {platform: payloads.get(platform) for platform in PLATFORMS}
    progress.check()

    def write(region):
        return _store_cross(live, repo_root, region=region, asset_id=asset_id,
                            source_asset_id=source_asset, timelines=timelines,
                            expected_key=described[region]["timelineKey"],
                            originals=checked[region], stage=stages[region], log=job.log)

    result, session = register._store_step(job, progress, repo_root, stage="write", stop=is_managed, restart=True,
                                           is_managed=is_managed,
                                           call=lambda: _each_region(job, cross["regions"], write))
    changed = bool(result.get("changed", True))
    restart = register._restart_state(session, is_managed, changed)
    if restart in ("done", "pending"):
        progress.stage("restart")
    game_state = result.get("timeline") or live.describe_mv_timeline(repo_root, region=own_region, asset_id=asset_id)
    lives = _live_titles(repo_root, own_region, game_state.get("lives") or [], language)
    title = lives["shown"][0]["title"] if lives["shown"] else str(asset_id)
    target = {"kind": "stock", "region": own_region, "liveId": None, "assetId": asset_id, "title": title, "stage": None,
              "lives": lives}
    # No "applied" record: the project's agreement with its own slot is unchanged.
    job.emit({"type": "mv-timeline", "mode": "all", "target": target, "changed": changed,
              "parts": result.get("parts", []), "restart": restart, "backup": result.get("backup"),
              "warnings": result.get("warnings", []), "managed": is_managed,
              "game": _game_summary({"kind": "stock", "game": game_state}),
              "cross": {"assetId": asset_id, "regions": list(cross["regions"]), "stage": cross["stage"],
                        "results": result.get("regions")}})
    job.progress(len(progress.stages), len(progress.stages))
    if not changed:
        return register.NO_CHANGES
    return APPLIED.replace("{title}", f"{title} · 3D {asset_id}")


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
