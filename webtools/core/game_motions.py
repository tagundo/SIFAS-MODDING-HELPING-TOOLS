"""Catalog-backed, bounded motion imports for the model viewer.

The picker uses the game's navigation relationships, rather than guessing
filenames. Timeline dependencies supply all body/eye motion clips belonging to
one action. MV animation clips live in the live timeline bundle itself.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time

from . import game_models as game

MAX_OPTIONS = 200
MAX_BUNDLES = 6
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BYTES = 32 * 1024 * 1024
_SLOT = threading.BoundedSemaphore(1)
_CHOICE = re.compile(r"(idle|auto|autocard|tap|tapcard|voice|login|mv):([1-9][0-9]{0,11})(?::([1-9][0-9]{0,11}))?\Z")
CATEGORIES = [
    {"value": "home", "label": "Home and idle motions"},
    {"value": "tap", "label": "Click motions"},
    {"value": "voice", "label": "Member voice motions"},
    {"value": "mv", "label": "MV motions"},
    {"value": "special", "label": "Login and special-day motions"},
]


def _rows(db, sql, values=()):
    try:
        return db.execute(sql, values).fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" in str(error) or "no such column" in str(error):
            return []
        raise


def _limited(start, end):
    # Retain the actual dates in the picker. Short availability windows identify
    # dated home events; no birthday or holiday is inferred from an asset name.
    return isinstance(start, int) and isinstance(end, int) and 0 < end - start <= 366 * 86400


def _choices(db, owner, category, resolve):
    values = []
    if category == "home":
        for key, in _rows(db, "SELECT idle_animation_clip_path FROM m_navi_model WHERE member_m_id=?", (owner,)):
            values.append({"value": f"idle:{owner}", "label": "Home idle", "asset": key, "table": "navi_motion"})
    if category in ("home", "tap", "special"):
        tables = [("auto", "m_navi_action_auto"), ("autocard", "m_navi_action_auto_card")] if category in ("home", "special") else [("tap", "m_navi_action_tap"), ("tapcard", "m_navi_action_tap_card")]
        for kind, table in tables:
            dated = kind in ("auto", "tap")
            dates = "x.start_at,x.end_at" if dated else "NULL,NULL"
            rows = _rows(db, f"SELECT x.id,t.timeline_asset_path,{dates},x.suit_m_id,a.navi_action_comment_id FROM {table} x JOIN m_navi_action a ON a.id=x.navi_action_id JOIN m_navi_timeline t ON t.id=a.navi_action_timeline_id WHERE x.member_m_id=? AND x.navi_action_scene=1 ORDER BY x.id LIMIT 5000", (owner,))
            for identity, asset, start, end, suit, comment in rows:
                special = _limited(start, end)
                if category == "special" and not special or category == "home" and special:
                    continue
                comments = _rows(db, "SELECT comment FROM m_navi_action_comment WHERE navi_action_comment_id=? ORDER BY order_no LIMIT 1", (comment,))
                label = resolve(comments[0][0]) if comments else ""
                values.append({"value": f"{kind}:{identity}", "label": str(label or f"Action {identity}")[:300], "asset": asset, "table": "navi_timeline", "start_at": start, "end_at": end, "suit_id": suit})
    if category == "voice":
        for identity, name, asset in _rows(db, "SELECT v.id,v.name,t.timeline_asset_path FROM m_navi_voice v JOIN m_navi_timeline t ON t.id=v.id WHERE v.member_m_id=? ORDER BY v.display_order DESC,v.id LIMIT 5000", (owner,)):
            values.append({"value": f"voice:{identity}", "label": str(resolve(name) or identity)[:300], "asset": asset, "table": "navi_timeline"})
    if category == "special":
        for identity, bonus, day, asset in _rows(db, "SELECT x.id,x.login_bonus_type,x.login_bonus_day,t.timeline_asset_path FROM m_navi_action_login x JOIN m_navi_action a ON a.id=x.navi_action_id JOIN m_navi_timeline t ON t.id=a.navi_action_timeline_id WHERE x.member_m_id=? ORDER BY x.login_bonus_type,x.id LIMIT 5000", (owner,)):
            values.append({"value": f"login:{identity}", "label": f"Login · {identity} · bonus {bonus}" + (f" · day {day}" if day else ""), "asset": asset, "table": "navi_timeline", "login_bonus_type": bonus})
    if category == "mv":
        # All dancers' clips are in the selected timeline. Character choice
        # stays available for navigation; it does not fabricate per-member MV
        # files or infer a performer binding from the selected character.
        for live, identity, name, asset, music in _rows(db, "SELECT DISTINCT l.live_id,a.id,l.name,a.timeline,l.bgm_path FROM m_live l JOIN m_live_difficulty d ON d.live_id=l.live_id JOIN m_live_3d_asset a ON a.id=d.live_3d_asset_master_id WHERE l.is_2d_live=0 ORDER BY l.live_id,a.id LIMIT 5000"):
            values.append({"value": f"mv:{live}:{identity}", "label": str(resolve(name) or live)[:300] + f" · {identity}", "asset": asset, "table": "live_timeline", "music": music})
    return values


def _owner(value, *, optional=False):
    if optional and value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,7}", value):
        raise ValueError("Choose a valid character.")
    return int(value)


def catalog(root, *, language="en", region="", character="", category="home", search=""):
    if not isinstance(category, str) or category not in {entry["value"] for entry in CATEGORIES} or not isinstance(search, str) or len(search) > 120:
        raise ValueError("Choose a valid motion category and search.")
    owner = _owner(character, optional=True)
    region, regions = game._region(root, region, language)
    extractor = game._extractor()
    names = game._names(extractor)
    with closing(game._readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        members = sorted({row[0] for row in _rows(db, "SELECT member_m_id FROM m_navi_model") if isinstance(row[0], int) and 0 < row[0] < 10000})
        dictionary = game._dictionary(root, region, language)
        try:
            choices = _choices(db, owner, category, lambda key: extractor.real_costume_name(dictionary, key)) if owner or category == "mv" else []
            query = search.strip().casefold()
            choices = [entry for entry in choices if not query or query in entry["label"].casefold() or query in entry["value"].casefold()]
            more = len(choices) > MAX_OPTIONS
            public = [{key: value for key, value in entry.items() if key not in ("asset", "table")} for entry in choices[:MAX_OPTIONS]]
        finally:
            if dictionary:
                dictionary.close()
    return {"region": region, "regions": [{"value": value, "label": "Global (GL)" if value == "gl" else "Japan (JP)"} for value in regions], "characters": [{"value": str(value), "label": names.get(value, str(value))} for value in members], "categories": CATEGORIES, "motions": public, "limit": MAX_OPTIONS, "more": more}


def _descriptor(db, table, asset):
    # The identifier is exclusively selected from these fixed source tables.
    if table not in ("navi_motion", "navi_timeline", "live_timeline"):
        raise ValueError("Unsupported motion asset type.")
    rows = _rows(db, f"SELECT pack_name,head,size,key1,key2 FROM {table} WHERE asset_path=? LIMIT 1", (asset,))
    if not rows:
        return None
    record = dict(zip(("pack_name", "head", "size", "key1", "key2"), rows[0]))
    if not isinstance(record["pack_name"], str) or not game._PACK.fullmatch(record["pack_name"]) or any(type(record[key]) is not int for key in ("head", "size", "key1", "key2")) or record["head"] < 0 or not 0 < record["size"] <= MAX_BYTES:
        raise ValueError("The selected motion has invalid package metadata.")
    record.update(asset=asset, table=table, pack_size=None, metapack=None)
    rows = _rows(db, "SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (record["pack_name"],))
    if rows:
        size, meta, offset = rows[0]
        if type(size) is not int or size < record["head"] + record["size"]:
            raise ValueError("The motion package size is invalid.")
        record["pack_size"] = size
        if meta:
            if not isinstance(meta, str) or not game._PACK.fullmatch(meta) or type(offset) is not int or offset < 0:
                raise ValueError("The motion metapack mapping is invalid.")
            record["metapack"] = {"name": meta, "offset": offset, "size": size}
    return record


def validate_selection(root, params, language="en"):
    if not isinstance(params, dict) or set(params) != {"region", "character", "category", "motion", "download"} or type(params["download"]) is not bool or any(not isinstance(params[key], str) for key in ("region", "character", "category", "motion")) or not _CHOICE.fullmatch(params["motion"]):
        raise ValueError("Unsupported game motion request.")
    owner = _owner(params["character"], optional=params["category"] == "mv")
    if params["category"] not in {entry["value"] for entry in CATEGORIES}:
        raise ValueError("Choose a valid motion category.")
    region, _ = game._region(root, params["region"], language)
    with closing(game._readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        choice = next((entry for entry in _choices(db, owner, params["category"], lambda value: value) if entry["value"] == params["motion"]), None)
    if not choice:
        raise ValueError("The selected motion is no longer available. Refresh the list.")
    catalogs = sorted((Path(root) / "assets/db" / region).glob("asset_a_*.db"), key=lambda path: (path.name != f"asset_a_{language}.db", path.name != "asset_a_en.db", path.name))
    for path in catalogs:
        with closing(game._readonly(path)) as db:
            if choice["table"] == "navi_timeline":
                rows = _rows(db, "SELECT d.dependency FROM navi_timeline_dependency d JOIN navi_motion n ON n.asset_path=d.dependency WHERE d.asset_path=? ORDER BY d.dependency LIMIT 7", (choice["asset"],))
                if not rows:
                    continue
                resources = [_descriptor(db, "navi_motion", row[0]) for row in rows]
            else:
                resource = _descriptor(db, choice["table"], choice["asset"])
                resources = [resource] if resource else []
            if not resources or any(item is None for item in resources):
                continue
            if len(resources) > MAX_BUNDLES or sum(item["size"] for item in resources) > MAX_TOTAL_BYTES:
                raise ValueError("This motion exceeds the viewer import limit.")
            return {"region": region, "character": owner, "category": params["category"], "motion": params["motion"], "download": params["download"], "resources": resources}
    raise ValueError("This motion is missing from the Android asset catalog.")


def _cached(root, identity, signatures):
    try:
        manifest = root / (".motion-" + identity + ".json")
        if manifest.is_symlink() or manifest.stat().st_size > 8192:
            return None
        value = json.loads(manifest.read_text())
        if value["sources"] != signatures or not 1 <= len(value["files"]) <= MAX_BUNDLES:
            return None
        paths = []
        for item in value["files"]:
            name = item["name"]
            if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
                return None
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root) or not 0 < path.stat().st_size <= MAX_BYTES or game._sha(path) != item["sha256"]:
                return None
            paths.append(path)
        return paths
    except (OSError, ValueError, KeyError, TypeError):
        return None


def run_import(job, *, repo_root, output_root, record):
    if not _SLOT.acquire(blocking=False):
        raise ValueError("Another game motion is being prepared. Try again shortly.")
    temporary, manifest_temp = None, None
    try:
        deadline = time.monotonic() + game.IMPORT_SECONDS
        game._check(job, deadline)
        root = game._safe_directory(Path(output_root))
        extractor = game._extractor()
        resources = record["resources"]
        found = [game._source(repo_root, resource, extractor, job, deadline) for resource in resources]
        signatures = [signature for _, signature in found]
        identity = hashlib.sha256(json.dumps({key: value for key, value in record.items() if key != "download"}, sort_keys=True).encode()).hexdigest()[:32]
        cached = _cached(root, identity, signatures)
        if cached:
            for path in cached:
                job.add_output(path)
            job.progress(len(cached), len(cached))
            return "Game motion ready."
        temporary = Path(tempfile.mkdtemp(prefix="motion-" + identity[:8] + "-", dir=root))
        outputs = []
        for index, (resource, (source, signature)) in enumerate(zip(resources, found)):
            game._check(job, deadline)
            if not source and not record["download"]:
                raise ValueError("The motion pack is missing. Enable downloading missing assets.")
            raw = game._plain_section(job, resource, source, signature, extractor, deadline)
            path = temporary / f"clip-{index + 1}.unity"
            path.write_bytes(raw)
            outputs.append({"name": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest()})
            job.progress(index + 1, len(resources))
        game._check(job, deadline)
        descriptor, name = tempfile.mkstemp(prefix=".motion-", suffix=".part", dir=root)
        manifest_temp = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"sources": signatures, "files": outputs}, handle)
        manifest = root / (".motion-" + identity + ".json")
        if manifest.is_symlink():
            raise ValueError("The game motion cache contains a linked file.")
        game._check(job, deadline)
        os.replace(manifest_temp, manifest)
        manifest_temp = None
        for item in outputs:
            job.add_output(root / item["name"])
        temporary = None
        job.log("Game motion ready.")
        return "Game motion ready."
    except game.ImportCancelled:
        job.log("Cancelled")
        return "Cancelled"
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)
        _SLOT.release()
