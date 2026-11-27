"""MV timeline packs in MV Studio ("MV 타임라인 팩", ``.sifasmv``): export, open, and the legacy zip.

The pack format (a zip: manifest.json, one plain UnityFS timeline per platform and, with an
Android file and a complete stage, the legacy ``livetimeline.txt`` layout) is read and written
ONCE, by Elichika's ``mv_timeline_pack`` (``write_pack(*, name, song, source, target_asset_id,
timelines, stage, note, target_stage, source_timeline_key)``, ``read_pack`` / ``read_any`` /
``read_legacy_livetimeline_zip`` returning {manifest, timelines, legacy}): the reader there is the
safe one (size and entry limits, no path traversal, JSON only, sha256 and UnityFS checks, never
exec). This module only adapts it to MV Studio:

- ``export_pack``: the project's whole timeline for each platform (the same payloads "게임에
  적용" writes for another slot: ``mv_studio_apply._cross_payloads``), the target slot and the
  optional stage, as a .sifasmv file in the library's ``modded/mv-studio`` folder.
- ``open_pack``: a pack (or a legacy livetimeline zip) staged for the game import, which then
  loads the pack's source MV (stage, members, song) with the pack's timeline instead of the
  catalogued one (``staged``). The project records the pack (``source.pack``): the apply panel
  preselects its target slot and stage.
"""
import hashlib
import json
import lzma
from pathlib import Path
import re
import time
import zipfile
import zlib

from . import game_models, mv_studio, mv_studio_register as register

EXTENSION = ".sifasmv"
PACK_BYTES = 64 * 1024 * 1024  # the size limit when Elichika's reader does not name its own (MAX_PACK_BYTES)
MAX_NAME = 80
MAX_NOTE = 500

NO_PACKS = "This Elichika version cannot read or write MV timeline packs. Update the Elichika server app."
NOT_PACK = "This file is not an MV timeline pack."
TOO_LARGE = "The MV timeline pack is too large or has too many files."  # Elichika's own wording
PACK_NAME = "Enter a pack name between 1 and 80 characters."
PACK_NOTE = "Enter a note of at most 500 characters."
PACK_PLATFORM = "The pack has no timeline this MV Studio can open."
PACK_STALE = "The opened pack is no longer available. Open it again."
PACK_SONG = "The game has no song that plays this pack's 3D MV."
EXPORT_REQUEST = "The MV timeline pack request is invalid."
MESSAGES = (NO_PACKS, NOT_PACK, TOO_LARGE, PACK_NAME, PACK_NOTE, PACK_PLATFORM, PACK_STALE, PACK_SONG, EXPORT_REQUEST)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def module():
    """Elichika's mv_timeline_pack (ValueError NO_PACKS without it)."""
    try:
        import mv_timeline_pack
    except ImportError as error:
        raise ValueError(NO_PACKS) from error
    return mv_timeline_pack


# ---------------------------------------------------------------- reading

def _files(value):
    """{platform: bytes} from a reader result's platform files."""
    files = {}
    for platform, entry in (value or {}).items():
        if platform not in register.PLATFORMS:
            continue
        if isinstance(entry, dict):
            entry = entry.get("data", entry.get("bytes"))
        if isinstance(entry, (bytes, bytearray)):
            files[platform] = bytes(entry)
    return files


def _normalized(result, legacy):
    """{"manifest", "platforms": {platform: bytes}, "legacy", "editor"} from a reader result: a
    {"manifest", "platforms"|"timelines"|"files"} dict or a (manifest, files) pair. ``editor`` is the
    exporting MV Studio's record a newer reader returns (mvstudio.json), else None."""
    if isinstance(result, tuple) and len(result) == 2:
        manifest, files = result
    elif isinstance(result, dict) and isinstance(result.get("manifest"), dict):
        manifest = result["manifest"]
        files = next((result[key] for key in ("platforms", "timelines", "files") if isinstance(result.get(key), dict)), {})
    else:
        raise ValueError(NOT_PACK)
    if not isinstance(manifest, dict):
        raise ValueError(NOT_PACK)
    files = _files(files)
    for platform, raw in files.items():
        if not raw.startswith(b"UnityFS\0"):
            raise ValueError(NOT_PACK)
    if not files:
        raise ValueError(PACK_PLATFORM)
    editor = result.get("editor") if isinstance(result, dict) else None
    return {"manifest": manifest, "platforms": files, "legacy": legacy,
            "editor": editor if isinstance(editor, dict) else None}


# What a damaged compressed entry raises from a reader that does not turn it into its own ValueError
# (an Elichika reader before that fix): the pack-open route then answers "not a pack", not a server error.
_DAMAGED = (zlib.error, lzma.LZMAError, EOFError, zipfile.BadZipFile, NotImplementedError, OSError)


def _call(function, path, data):
    try:
        try:
            return function(data)
        except TypeError:
            return function(path)
    except _DAMAGED as error:
        raise ValueError(NOT_PACK) from error


def _limit(pack):
    """The largest pack Elichika's reader opens (its MAX_PACK_BYTES), so every pack its writer makes opens here."""
    limit = getattr(pack, "MAX_PACK_BYTES", None)
    return limit if type(limit) is int and limit > 0 else PACK_BYTES


def read(path):
    """A .sifasmv pack or a legacy livetimeline zip as {"manifest", "platforms", "legacy"}."""
    pack = module()
    path = Path(path)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(NOT_PACK)
    if path.stat().st_size > _limit(pack):
        raise ValueError(TOO_LARGE)
    data = path.read_bytes()
    reader = getattr(pack, "read_any", None)
    if reader is not None:
        result = _call(reader, path, data)
        return _normalized(result, bool(isinstance(result, dict) and result.get("legacy")))
    try:
        return _normalized(_call(pack.read_pack, path, data), False)
    except ValueError as error:
        reader = getattr(pack, "read_legacy_livetimeline_zip", None)
        if reader is None or str(error) == PACK_PLATFORM:
            raise
        try:
            return _normalized(_call(reader, path, data), True)
        except ValueError:
            raise error from None


# ---------------------------------------------------------------- the exporting MV Studio

def editor_keywords(pack, previous=None):
    """write_pack's ``editor`` keyword, when Elichika's writer takes it (its EDITOR entry): this MV
    Studio's timeline export format (mv_timeline_platform.EXPORT_FORMAT) and version, so a server
    whose MV Studio tools are older can say the pack is newer. A pack rewritten from one ``previous``
    says a newer MV Studio made keeps that newer format. An older writer gets nothing."""
    if not getattr(pack, "EDITOR", None):
        return {}
    import webtools
    from . import mv_timeline_platform
    timeline_format = mv_timeline_platform.EXPORT_FORMAT
    earlier = previous.get("timelineFormat") if isinstance(previous, dict) else None
    if type(earlier) is int and earlier > timeline_format:
        timeline_format = earlier
    return {"editor": {"timelineFormat": timeline_format, "modtools": str(webtools.__version__)[:64]}}


# ---------------------------------------------------------------- staging for the game import

def _stage_dir():
    return game_models._safe_directory(mv_studio._root() / "native" / "packs")


def _blob(raw):
    directory = game_models._safe_directory(mv_studio._root() / "native" / "blobs")
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / (digest + ".unity")
    if not (path.is_file() and path.stat().st_size == len(raw)):
        mv_studio._write(path, raw)
    return digest


def _identity(value):
    return register._identity(value)


def _summary(manifest, files, legacy):
    """The pack facts MV Studio keeps with the project (source.pack) and shows in the panel."""
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    song = manifest.get("song") if isinstance(manifest.get("song"), dict) else {}
    stage = manifest.get("stage") if isinstance(manifest.get("stage"), dict) else None
    text = lambda value, limit: value[:limit] if isinstance(value, str) else ""  # noqa: E731
    return {"name": text(manifest.get("name"), MAX_NAME), "note": text(manifest.get("note"), MAX_NOTE),
            "legacy": legacy, "region": source.get("region") if source.get("region") in register.REGIONS else None,
            "sourceAssetId": _identity(source.get("assetId")), "targetAssetId": _identity(target.get("assetId")),
            "liveId": _identity(song.get("liveId")), "title": text(song.get("title"), 200),
            "stage": stage is not None, "platforms": sorted(files)}


def _legacy_source(repo_root, region, key, target):
    """The 3D MV a legacy zip's timeline was made from: the asset whose (stock) timeline key the
    legacy txt names (its dependency rows came from there), else None."""
    if not isinstance(key, str) or not key:
        return None
    from contextlib import closing
    import sqlite3
    path = Path(repo_root).resolve() / "assets/db" / region / "masterdata.db"
    with closing(game_models._readonly(path)) as master:
        rows = [row[0] for row in master.execute("SELECT id FROM m_live_3d_asset WHERE timeline=? ORDER BY id", (key,))]
        try:
            rows += [row[0] for row in master.execute(
                "SELECT asset_id FROM _elichika_mv_studio_timeline WHERE stock_key=? ORDER BY asset_id", (key,))]
        except sqlite3.Error:
            pass
    return (target if target in rows else rows[0]) if rows else None


def _first_live(repo_root, region, asset_id):
    path = Path(repo_root).resolve() / "assets/db" / region / "masterdata.db"
    from contextlib import closing
    with closing(game_models._readonly(path)) as master:
        row = master.execute("SELECT live_id FROM m_live_mv WHERE live_3d_asset_master_id=? UNION "
                             "SELECT live_id FROM m_live_difficulty WHERE live_3d_asset_master_id=? ORDER BY 1 LIMIT 1",
                             (asset_id, asset_id)).fetchone()
    return row[0] if row else None


def open_pack(repo_root, path, *, region=None, platform=None):
    """Stage a pack for the game import. Returns the import choice for the page:
    {"pack": token, "region", "platform", "liveId", "assetId", "info": summary}.

    The source MV is the pack's source asset (a legacy zip names only its target: that asset is
    used); the platform is the one asked for when the pack has it, else the pack's own."""
    selected = mv_studio._path(path)
    pack = read(selected)
    info = _summary(pack["manifest"], pack["platforms"], pack["legacy"])
    region = info["region"] or (region if region in register.REGIONS else "gl")
    info["region"] = region
    asset = (info["sourceAssetId"] or _legacy_source(repo_root, region, pack["manifest"].get("legacyTimelineKey"),
                                                     info["targetAssetId"]) or info["targetAssetId"])
    if asset is None:
        raise ValueError(NOT_PACK)
    info["sourceAssetId"] = asset
    live_id = info["liveId"] or _first_live(repo_root, region, asset)
    if live_id is None:
        raise ValueError(PACK_SONG)
    chosen = platform if platform in pack["platforms"] else sorted(pack["platforms"])[0]
    digests = {name: _blob(raw) for name, raw in pack["platforms"].items()}
    record = {"info": info, "platforms": digests, "stage": pack["manifest"].get("stage"), "created": int(time.time())}
    token = digests[chosen]
    mv_studio._write(_stage_dir() / (token + ".json"), json.dumps(record, sort_keys=True).encode())
    return {"pack": token, "region": region, "platform": chosen, "liveId": live_id, "assetId": asset, "info": info}


def staged(token, platform):
    """(timeline bytes, source.pack record) of a pack opened with ``open_pack``."""
    if not isinstance(token, str) or not _DIGEST.fullmatch(token):
        raise ValueError(PACK_STALE)
    try:
        record = json.loads((_stage_dir() / (token + ".json")).read_bytes())
        raw = (mv_studio._root() / "native" / "blobs" / (token + ".unity")).read_bytes()
    except (OSError, ValueError) as error:
        raise ValueError(PACK_STALE) from error
    if hashlib.sha256(raw).hexdigest() != token or record.get("platforms", {}).get(platform) != token:
        raise ValueError(PACK_STALE)
    info = record.get("info") or {}
    return raw, {**info, "token": token, "platform": platform}


# ---------------------------------------------------------------- export

def validate_export(data):
    if not isinstance(data, dict) or set(data) - {"project", "name", "note", "target", "platforms", "download"}:
        raise ValueError(EXPORT_REQUEST)
    name = data.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= MAX_NAME or any(ord(c) < 32 for c in name):
        raise ValueError(PACK_NAME)
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE or any(ord(c) < 32 and c not in "\n\t" for c in note):
        raise ValueError(PACK_NOTE)
    if type(data.get("download", False)) is not bool:
        raise ValueError(EXPORT_REQUEST)
    mv_studio._document(data["project"])
    target = data.get("target")
    if target is not None and (not isinstance(target, dict) or set(target) - {"assetId", "stage"}
                               or not _identity(target.get("assetId")) or type(target.get("stage", True)) is not bool):
        raise ValueError(EXPORT_REQUEST)
    return {"project": data["project"], "name": name.strip(), "note": note.strip(), "target": target,
            "platforms": register._platforms(data.get("platforms", list(register.PLATFORMS))),
            "download": data.get("download", False)}


def export_pack(repo_root, request, *, language="en"):
    """Write the project's timeline pack. Returns {"path", "download", "platforms", "skipped"}.

    A platform whose timeline cannot be made (its original is not in the game, or needs a
    download that was not allowed) is left out and listed in ``skipped``."""
    from . import mv_studio_apply as apply
    pack = module()
    project = request["project"]
    live = register.store()
    loaded = apply._target(repo_root, project, live, language)
    if loaded is None or loaded.get("removed") or loaded.get("unknown"):
        raise ValueError(apply.NO_TARGET)
    if loaded["kind"] != "stock":
        raise ValueError(apply.CROSS_SONG)
    # A slot that plays another slot's timeline: the pack would name this asset as its source while
    # its timeline is the other asset's (the same refusal as plan and apply).
    if apply._foreign_source(loaded) is not None:
        raise ValueError(apply.SLOT_FROM_OTHER_JOB)
    apply._ours(project, apply._snapshot(project))  # structure check
    wanted, skipped = [], []
    blob = register._project_blob(project, loaded["base"], loaded["facts"])
    own = blob.get("platform") or project["source"]["platform"]
    for platform in request["platforms"]:
        if platform == own:
            wanted.append(platform)
            continue
        stock, _ = apply._stock(repo_root, loaded, platform, blob, download=request["download"])
        (wanted if stock is not None else skipped).append(platform)
    payloads, _ = apply._cross_payloads(repo_root, project, loaded, wanted, download=request["download"])
    target = request["target"] or {"assetId": loaded["assetId"], "stage": False}
    stage = None
    if target.get("stage", True) and target["assetId"] != loaded["assetId"]:
        # The source's STOCK stage (what "Change the stage too" carries in apply), not its current row.
        stage = apply._source_stage(live, repo_root, loaded["region"], loaded["assetId"])
    # The legacy layout (for the old "Replace Live Camera Timeline" tool) needs a complete stage: the
    # target slot's original one when this pack does not carry the source's (what an install without a
    # stage puts back), and the source's stock key.
    target_stage = apply._source_stage(live, repo_root, loaded["region"], target["assetId"])
    data = pack.write_pack(name=request["name"], note=request["note"],
                           song={"liveId": loaded["liveId"], "title": str(loaded["title"])[:160]},
                           source={"region": loaded["region"], "assetId": loaded["assetId"]},
                           target_asset_id=target["assetId"], timelines=payloads, stage=stage,
                           target_stage=target_stage, source_timeline_key=loaded["facts"].get("timelineKey"),
                           **editor_keywords(pack))
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError(NO_PACKS)
    destination = mv_studio._destination(request["name"], EXTENSION)
    mv_studio._write(destination, bytes(data))
    return {**mv_studio._receipt(destination), "platforms": sorted(payloads), "skipped": skipped}


# ---------------------------------------------------------------- rewriting a read pack

def _stock_timeline_key(repo_root, region, asset_id):
    """The TRUE stock timeline key of a 3D asset (whose dependency rows the legacy tool copies), or None."""
    from contextlib import closing
    import sqlite3
    path = Path(repo_root).resolve() / "assets/db" / region / "masterdata.db"
    try:
        with closing(game_models._readonly(path)) as master:
            row = master.execute("SELECT timeline FROM m_live_3d_asset WHERE id=?", (asset_id,)).fetchone()
            return register._stock_key(master, asset_id, row[0]) if row is not None and row[0] else None
    except (sqlite3.Error, OSError, ValueError):
        return None


def rewrite_stage(repo_root, manifest, *, partial=False):
    """write_pack's stage keywords for a new pack made from a read ``manifest`` (the platform
    conversion adds a platform): ({"stage", "target_stage", "source_timeline_key"}, filled).

    A pack may name only some stage fields; installing it fills the others from the TARGET slot's
    original stage (Elichika's apply_mv_timeline). A writer that takes a partial stage
    (``partial``: mv_timeline_pack.PARTIAL_STAGE) gets it as it is, so the new pack installs the
    same stage. An older writer needs all five: the left-out fields then come from the manifest
    target's stock (original) stage, the values the install would give them there, and are listed
    in ``filled``. ``target_stage`` (that same stock stage) and ``source_timeline_key`` keep the
    legacy layout in the new pack."""
    from . import mv_studio_apply as apply
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    region, asset = source.get("region"), source.get("assetId")
    target = (manifest.get("target") or {}).get("assetId") if isinstance(manifest.get("target"), dict) else None
    try:
        live = register.store()
    except ImportError:
        live = None  # _source_stage then reads the region's masterdata
    target_stage = apply._source_stage(live, repo_root, region, target) if target else None
    stage, filled = manifest.get("stage"), []
    if isinstance(stage, dict) and set(stage) != set(apply.STAGE_FIELDS) and not partial:
        if target_stage is None:
            from . import mv_timeline_platform
            raise ValueError(mv_timeline_platform.NO_ASSET)
        filled = [field for field in apply.STAGE_FIELDS if field not in stage]
        stage = {**target_stage, **stage}
    return {"stage": stage, "target_stage": target_stage,
            "source_timeline_key": _stock_timeline_key(repo_root, region, asset)}, filled


__all__ = ("open_pack", "staged", "read", "export_pack", "validate_export", "rewrite_stage", "editor_keywords",
           "MESSAGES", "EXTENSION")
