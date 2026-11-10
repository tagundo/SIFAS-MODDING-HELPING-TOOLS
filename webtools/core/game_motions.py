"""Catalog-backed, bounded motion imports for the model viewer.

The picker uses the game's navigation relationships, rather than guessing
filenames. Timeline dependencies supply all body/eye motion clips belonging to
one action. MV camera timelines reference separate dancer bundles through
exact serialized-file and object pointers; camera clips are never imported.
"""
from collections import OrderedDict
from contextlib import closing
import copy
import hashlib
import html
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
# Match the viewer's separately bounded motion library. A single original
# action can contain five body clips plus three facial banks; retaining every
# authored segment must not trip the former six-file combined-model limit.
MAX_BUNDLES = 32
MAX_RESOURCES = 32
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BYTES = 32 * 1024 * 1024
_SLOT = threading.BoundedSemaphore(1)
_IMPORTS = {}
_IMPORT_LOCK = threading.RLock()
_CATALOG_CACHE = OrderedDict()
_CATALOG_LOCK = threading.Lock()
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


def _columns(db, table):
    return {row[1] for row in _rows(db, "PRAGMA table_info(" + table + ")")}


def _performers(db, mapping, names=None):
    names = names or {}
    rows = _rows(db, "SELECT position,member_master_id,is_center FROM m_live_member_mapping WHERE mapping_id=? ORDER BY position", (mapping,))
    if not rows:
        rows = _rows(db, "SELECT position,member_master_id,is_center FROM m_live_override_member_mapping WHERE mapping_id=? ORDER BY position", (mapping,))
    return [{"value": str(position), "position": position, "member_id": member,
             "is_center": bool(center), "label": str(position) + " · " + str(names.get(member, member or "Member"))}
            for position, member, center in rows if type(position) is int and 1 <= position <= 64]


def _mv_choices(db, resolve, names=None, selected=None):
    live_columns, asset_columns = _columns(db, "m_live"), _columns(db, "m_live_3d_asset")
    mapping = "l.live_member_mapping_id" if "live_member_mapping_id" in live_columns else "NULL"
    stage = "a.live_stage_master_id" if "live_stage_master_id" in asset_columns else "NULL"
    rows = []
    for table in ("m_live_mv", "m_live_difficulty"):
        condition = " AND l.live_id=? AND a.id=?" if selected is not None else ""
        rows += _rows(db, f"SELECT DISTINCT l.live_id,a.id,l.name,a.timeline,l.bgm_path,{mapping},{stage} FROM m_live l JOIN {table} v ON v.live_id=l.live_id JOIN m_live_3d_asset a ON a.id=v.live_3d_asset_master_id WHERE l.is_2d_live=0{condition} ORDER BY l.live_id,a.id LIMIT 5000", selected or ())
    seen, output, formations = set(), [], {}
    for live, identity, name, asset, music, mapping, stage in sorted(rows, key=lambda row: (row[0], row[1])):
        if (live, identity) in seen:
            continue
        seen.add((live, identity))
        if mapping not in formations:
            formations[mapping] = _performers(db, mapping, names)
        performers = formations[mapping]
        output.append({"value": f"mv:{live}:{identity}", "label": html.unescape(str(resolve(name) or live))[:260] + f" · {identity}",
                       "asset": asset, "table": "live_timeline", "music": music, "live_id": live, "asset_3d_id": identity,
                       "mapping_id": mapping, "stage_id": stage, "performers": performers,
                       "song_type": "solo" if len(performers) == 1 else "group" if performers else "unknown"})
    return output


def _choices(db, owner, category, resolve, names=None, selection=None):
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
        selected = tuple(map(int, selection.split(":")[1:])) if selection else None
        values.extend(_mv_choices(db, resolve, names, selected))
    return values


def _catalog_signature(root, region, language):
    directory = Path(root) / "assets/db" / region
    paths = [directory / "masterdata.db"]
    for code in dict.fromkeys([language, "ja" if region == "jp" else "en", "ko", "en", "ja", "zh"]):
        path = directory / f"dictionary_{code}_k.db"
        if path.is_file():
            paths.append(path)
            break
    result = []
    for path in paths:
        for value in (path, Path(str(path) + "-wal")):
            try:
                stat = value.stat()
                result.append((str(value.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
            except FileNotFoundError:
                result.append((str(value.resolve()), None))
    return tuple(result)


def _catalog_choices(root, region, language, owner, category, extractor, names):
    signature = _catalog_signature(root, region, language)
    key = str(Path(root).resolve()), region, language, owner, category, signature
    with _CATALOG_LOCK:
        cached = _CATALOG_CACHE.get(key)
        if cached is not None:
            _CATALOG_CACHE.move_to_end(key)
            return cached
    with closing(game._readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        members = sorted({row[0] for row in _rows(db, "SELECT member_m_id FROM m_navi_model") if isinstance(row[0], int) and 0 < row[0] < 10000})
        dictionary = game._dictionary(root, region, language)
        try:
            choices = _choices(db, owner, category, lambda name: html.unescape(str(extractor.real_costume_name(dictionary, name))), names) if owner or category == "mv" else []
        finally:
            if dictionary:
                dictionary.close()
    # Include SQLite WAL and inode/ctime so committed database updates, atomic
    # replacements and restored mtimes cannot leave the picker on stale data.
    if signature == _catalog_signature(root, region, language):
        with _CATALOG_LOCK:
            _CATALOG_CACHE[key] = members, choices
            _CATALOG_CACHE.move_to_end(key)
            while len(_CATALOG_CACHE) > 4:
                _CATALOG_CACHE.popitem(last=False)
    return members, choices


def _owner(value, *, optional=False):
    if optional and value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,7}", value):
        raise ValueError("Choose a valid character.")
    return int(value)


def catalog(root, *, language="en", region="", character="", category="home", search="", offset=0, song_type="all"):
    if not isinstance(category, str) or category not in {entry["value"] for entry in CATEGORIES} or not isinstance(search, str) or len(search) > 120:
        raise ValueError("Choose a valid motion category and search.")
    if isinstance(offset, str) and re.fullmatch(r"[0-9]{1,6}", offset):
        offset = int(offset)
    if type(offset) is not int or not 0 <= offset <= 100000 or song_type not in ("all", "solo", "group"):
        raise ValueError("Choose a valid motion page and song type.")
    owner = _owner(character, optional=True)
    if not region:
        available = game._regions(root)
        preferred = "jp" if language in ("ja", "jp") else "gl"
        region = preferred if preferred in available else ""
    region, regions = game._region(root, region, language)
    extractor = game._extractor()
    names = game._names(extractor)
    members, choices = _catalog_choices(root, region, language, owner, category, extractor, names)
    query = search.strip().casefold()
    choices = [entry for entry in choices if not query or query in entry["label"].casefold() or query in entry["value"].casefold()]
    if category == "mv" and song_type != "all":
        choices = [entry for entry in choices if entry.get("song_type") == song_type]
    total, more = len(choices), len(choices) > offset + MAX_OPTIONS
    public = [copy.deepcopy({key: value for key, value in entry.items() if key not in ("asset", "table")}) for entry in choices[offset:offset + MAX_OPTIONS]]
    return {"region": region, "regions": [{"value": value, "label": "Global (GL)" if value == "gl" else "Japan (JP)"} for value in regions], "characters": [{"value": str(value), "label": names.get(value, str(value))} for value in members], "categories": CATEGORIES, "motions": public, "limit": MAX_OPTIONS, "more": more, "offset": offset, "total": total, "song_type": song_type}


def _descriptor(db, table, asset):
    # The identifier is exclusively selected from these fixed source tables.
    if table not in ("navi_motion", "navi_timeline", "live_timeline", "member_facial_animation", "member_model"):
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


def _facial_resources(root, region, asset_db, owner):
    if owner is None:
        return []
    with closing(game._readonly(Path(root) / "assets/db" / region / "masterdata.db")) as master:
        rows = _rows(master, "SELECT s.model_asset_path FROM m_member_init i JOIN m_suit s ON s.id=i.suit_m_id WHERE i.member_m_id=? AND s.member_m_id=?", (owner, owner))
        models = [row[0] for row in rows if row[0]]
        overrides = [row[0] for row in _rows(master, "SELECT animation_asset_path FROM m_member_override_facial_animation WHERE member_id=? ORDER BY view_status,animation_type", (owner,)) if row[0]]
    keys = list(overrides)
    for model in models[:1]:
        keys.extend(row[0] for row in _rows(asset_db, "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency LIMIT 64", (model,)))
    output = []
    for key in dict.fromkeys(keys):
        for table in ("member_model", "member_facial_animation"):
            resource = _descriptor(asset_db, table, key)
            if resource:
                output.append(dict(resource, role="facial_candidate"))
                break
    if len(output) > 8:
        raise ValueError("The target character has too many facial animation sources.")
    return output


def validate_selection(root, params, language="en"):
    required = {"region", "character", "category", "motion", "download"}
    if not isinstance(params, dict) or not required <= set(params) or set(params) - required - {"performer", "audio", "target_character"} or type(params["download"]) is not bool or any(not isinstance(params[key], str) for key in ("region", "character", "category", "motion")) or not _CHOICE.fullmatch(params["motion"]):
        raise ValueError("Unsupported game motion request.")
    if type(params.get("audio", True)) is not bool or not isinstance(params.get("performer", ""), str):
        raise ValueError("Choose a valid performer and audio option.")
    owner = _owner(params["character"], optional=params["category"] == "mv")
    target = _owner(params.get("target_character", ""), optional=True) if "target_character" in params else owner
    if params["category"] not in {entry["value"] for entry in CATEGORIES}:
        raise ValueError("Choose a valid motion category.")
    region, _ = game._region(root, params["region"], language)
    with closing(game._readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        choice = next((entry for entry in _choices(db, owner, params["category"], lambda value: value, selection=params["motion"]) if entry["value"] == params["motion"]), None)
    if not choice:
        raise ValueError("The selected motion is no longer available. Refresh the list.")
    performer = params.get("performer", "")
    performers = choice.get("performers", [])
    if performer and (not re.fullmatch(r"[1-9][0-9]?", performer) or performers and performer not in {entry["value"] for entry in performers}):
        raise ValueError("Choose a performer from the original song formation.")
    if params["category"] == "mv" and not performer:
        preferred = next((entry for entry in performers if entry["member_id"] == owner), None)
        preferred = preferred or next((entry for entry in performers if entry["is_center"]), None)
        performer = preferred["value"] if preferred else performers[0]["value"] if performers else "1"
    performer_position = int(performer or "1")
    catalogs = sorted((Path(root) / "assets/db" / region).glob("asset_a_*.db"), key=lambda path: (path.name != f"asset_a_{language}.db", path.name != "asset_a_en.db", path.name))
    for path in catalogs:
        with closing(game._readonly(path)) as db:
            if choice["table"] in ("navi_timeline", "live_timeline"):
                main = _descriptor(db, choice["table"], choice["asset"])
                resources = [dict(main, role="timeline")] if main else []
                dependency_table = choice["table"] + "_dependency"
                rows = _rows(db, f"SELECT dependency FROM {dependency_table} WHERE asset_path=? ORDER BY dependency LIMIT {MAX_RESOURCES + 1}", (choice["asset"],))
                for dependency, in rows:
                    for table in ("live_timeline", "navi_motion", "member_facial_animation"):
                        resource = _descriptor(db, table, dependency)
                        if resource:
                            resources.append(dict(resource, role="dependency"))
                            break
                if not main and choice["table"] == "live_timeline":
                    continue
            else:
                resource = _descriptor(db, choice["table"], choice["asset"])
                resources = [dict(resource, role="animation")] if resource else []
            if not resources or any(item is None for item in resources):
                continue
            facial = _facial_resources(root, region, db, target)
            seen = {(item["table"], item["asset"]) for item in resources}
            resources.extend(item for item in facial if (item["table"], item["asset"]) not in seen)
            if len(resources) > MAX_RESOURCES or sum(item["size"] for item in resources) > MAX_TOTAL_BYTES:
                raise ValueError("This motion exceeds the viewer import limit.")
            return {"version": 2, "region": region, "character": owner, "category": params["category"], "motion": params["motion"],
                    "download": params["download"], "resources": resources, "audio": params.get("audio", True),
                    "timeline_asset": choice["asset"], "performer_position": performer_position,
                    "performer": next((entry for entry in performers if entry["position"] == performer_position), None),
                    "music_key": choice.get("music"), "live_id": choice.get("live_id"), "asset_3d_id": choice.get("asset_3d_id"),
                    "asset_database": str(path.resolve()), "label": choice["label"], "target_character": target}
    raise ValueError("This motion is missing from the Android asset catalog.")


def _cached(root, identity, signatures):
    try:
        manifest = root / (".motion-" + identity + ".json")
        if manifest.is_symlink() or manifest.stat().st_size > 8 * 1024 * 1024:
            return None
        value = json.loads(manifest.read_text())
        if value.get("version") != 2 or value["sources"] != signatures or not 1 <= len(value["files"]) <= MAX_BUNDLES:
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
        timelines = []
        for item in value.get("timelines", []):
            name = item["name"]
            if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
                return None
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root) or game._sha(path) != item["sha256"]:
                return None
            timelines.append(path)
        return {"paths": paths, "motion": value["motion"], "timelines": timelines}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_source_signatures(found):
    signatures = []
    for path, signature in found:
        if path is None:
            signatures.append(None)
            continue
        stat = path.stat()
        if stat.st_size != signature["size"] or stat.st_mtime_ns != signature["mtime_ns"]:
            raise ValueError("The game motion pack changed while checking its cache. Load it again.")
        signatures.append({**signature, "ctime_ns": stat.st_ctime_ns, "inode": stat.st_ino, "device": stat.st_dev})
    return signatures


def _register(paths, descriptor):
    # The frontend cannot supply facial timelines or arbitrary local paths. A
    # later model preparation resolves only this source-bound server receipt.
    receipt = {"paths": [str(Path(path).resolve()) for path in paths],
               "hashes": [game._sha(path) for path in paths],
               "motion": json.loads(json.dumps(descriptor, allow_nan=False))}
    with _IMPORT_LOCK:
        for path in receipt["paths"]:
            _IMPORTS[path] = receipt
        while len(_IMPORTS) > 256:
            _IMPORTS.pop(next(iter(_IMPORTS)))


def resolve_import(paths):
    """Return verified timeline descriptors for explicitly loaded motion files."""
    result, seen = [], set()
    selected = {str(Path(path).resolve()) for path in paths}
    with _IMPORT_LOCK:
        receipts = [_IMPORTS.get(path) for path in selected]
    for receipt in receipts:
        if not receipt or id(receipt) in seen or not set(receipt["paths"]) <= selected:
            continue
        seen.add(id(receipt))
        try:
            if all(game._sha(path) == digest for path, digest in zip(receipt["paths"], receipt["hashes"])):
                result.append(json.loads(json.dumps(receipt["motion"], allow_nan=False)))
        except OSError:
            continue
    return result


def _audio(job, repo_root, output_root, record, timelines):
    if not record.get("audio", True):
        return {"version": 1, "tracks": [], "warnings": []}
    from .game_motion_audio import prepare_audio
    try:
        return prepare_audio(job, repo_root=repo_root, output_root=Path(output_root) / "audio", record=record, timeline_paths=timelines)
    except (ValueError, OSError) as error:
        job.log("Linked audio: " + str(error))
        return {"version": 1, "tracks": [], "warnings": [str(error)]}


def _publish(job, *, paths, descriptor, timelines, repo_root, output_root, record):
    descriptor = json.loads(json.dumps(descriptor, allow_nan=False))
    from .viewer_physics_runtime import motion_settings
    descriptor["physics"] = motion_settings(repo_root=repo_root, record=record)
    descriptor["audio"] = _audio(job, repo_root, output_root, record, timelines)
    _register(paths, descriptor)
    job.emit({"type": "motion", "motion": descriptor})
    for path in paths:
        job.add_output(path)
    return descriptor


def run_import(job, *, repo_root, output_root, record):
    if not _SLOT.acquire(blocking=False):
        raise ValueError("Another game motion is being prepared. Try again shortly.")
    temporary, manifest_temp = None, None
    stage, pack = "Finding motion packs", ""
    try:
        deadline = time.monotonic() + 180
        game._check(job, deadline)
        root = game._safe_directory(Path(output_root))
        extractor = game._extractor()
        resources = record["resources"]
        found = [game._source(repo_root, resource, extractor, job, deadline) for resource in resources]
        signatures = _cache_source_signatures(found)
        identity = hashlib.sha256(json.dumps({key: value for key, value in record.items() if key != "download"}, sort_keys=True).encode()).hexdigest()[:32]
        stage = "Checking the motion cache"
        cached = _cached(root, identity, signatures)
        if cached:
            stage = "Preparing linked voice or music"
            _publish(job, paths=cached["paths"], descriptor=cached["motion"], timelines=cached["timelines"],
                     repo_root=repo_root, output_root=root, record=record)
            job.progress(len(resources), len(resources))
            return "Game motion ready."
        temporary = Path(tempfile.mkdtemp(prefix="motion-" + identity[:8] + "-", dir=root))
        raw_paths, timelines, downloaded = [], [], {}
        for index, (resource, (source, signature)) in enumerate(zip(resources, found)):
            stage, pack = "Preparing motion pack", resource["pack_name"]
            game._check(job, deadline)
            if not source and not record["download"]:
                raise ValueError("The motion pack is missing. Enable downloading missing assets.")
            if source:
                raw = game._plain_section(job, resource, source, signature, extractor, deadline)
            else:
                # A dance's nine dependencies commonly share two packs. Fetch
                # each pack once, while retaining the same aggregate byte bound.
                name = resource["pack_name"]
                if name not in downloaded:
                    stage = "Downloading motion pack"
                    packed = game._remote_pack(resource, extractor, job, deadline)
                    if sum(len(value) for value in downloaded.values()) + len(packed) > MAX_TOTAL_BYTES:
                        raise ValueError("The selected motion packs exceed the aggregate download limit.")
                    downloaded[name] = packed
                raw = bytearray(downloaded[name][resource["head"]:resource["head"] + resource["size"]])
                if len(raw) != resource["size"]:
                    raise ValueError("The original motion section is incomplete.")
                stage = "Decrypting motion pack"
                extractor.decrypt_section(raw, extractor.FIXED_KEY0, resource["key1"], resource["key2"])
                from .model_viewer import _preflight_bundle
                _preflight_bundle(raw)
            path = temporary / f"source-{index + 1}.unity"
            path.write_bytes(raw)
            raw_paths.append(path)
            if resource.get("role") == "timeline":
                timelines.append(path)
            job.progress(index + 1, len(resources))
        downloaded.clear()
        stage, pack = "Resolving original motion clips", ""
        from . import game_motion_selection
        if timelines:
            candidates = [path for path, resource in zip(raw_paths, resources) if resource.get("role") == "dependency"]
            selected = game_motion_selection.select(timelines[0], candidates,
                performer=record.get("performer_position", 1), category=record["category"], deadline=deadline)
        elif len([item for item in resources if item.get("role") == "animation"]) == 1:
            selected = game_motion_selection.animation_only(next(path for path, resource in zip(raw_paths, resources) if resource.get("role") == "animation"), deadline=deadline)
        else:
            raise ValueError("The original action timeline is missing, so its body and facial clips cannot be synchronized safely.")
        facial_paths = [path for path, resource in zip(raw_paths, resources) if resource.get("role") == "facial_candidate"]
        stage = "Resolving original facial clips"
        facial_selection, facial_entries = game_motion_selection.facial_banks(facial_paths, deadline=deadline)
        selected["selected"].update(facial_selection["selected"])
        stage = "Writing selected motion clips"
        files, segments, clip_sources, identities = game_motion_selection.write_selected(selected, temporary)
        facial_clips = []
        for entry in facial_entries:
            entry = dict(entry)
            entry.update(identities[entry.pop("key")])
            facial_clips.append(entry)
        if len(files) > MAX_BUNDLES:
            raise ValueError("The selected performer needs too many motion bundles for the viewer.")
        descriptor = {"version": 2, "category": record["category"], "motion": record["motion"], "label": record.get("label", record["motion"]),
                      "performer": record.get("performer"), "performerPosition": record.get("performer_position", 1),
                      "clipSources": clip_sources, "bodySegments": segments, "facialClips": facial_clips, "targetCharacter": record.get("target_character"),
                      "duration": max((row["start"] + row["duration"] for row in segments), default=0), "warnings": []}
        if timelines:
            stage = "Reading original facial timeline"
            from .game_motion_timeline import parse_timeline
            descriptor["facial"] = parse_timeline(str(timelines[0]), record.get("performer_position", 1), segments=segments)
        outputs = [{"name": str(item["path"].relative_to(root)), "sha256": item["sha256"]} for item in files]
        timeline_records = [{"name": str(path.relative_to(root)), "sha256": game._sha(path)} for path in timelines]
        game._check(job, deadline)
        stage = "Saving the motion cache"
        manifest_fd, name = tempfile.mkstemp(prefix=".motion-", suffix=".part", dir=root)
        manifest_temp = Path(name)
        with os.fdopen(manifest_fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "sources": signatures, "files": outputs, "timelines": timeline_records, "motion": descriptor}, handle, allow_nan=False)
        manifest = root / (".motion-" + identity + ".json")
        if manifest.is_symlink():
            raise ValueError("The game motion cache contains a linked file.")
        game._check(job, deadline)
        os.replace(manifest_temp, manifest)
        manifest_temp = None
        stage = "Preparing linked voice or music"
        _publish(job, paths=[item["path"] for item in files], descriptor=descriptor, timelines=timelines,
                 repo_root=repo_root, output_root=root, record=record)
        temporary = None
        job.log("Game motion ready.")
        return "Game motion ready."
    except game.ImportCancelled:
        job.log("Cancelled")
        return "Cancelled"
    except Exception as error:
        from urllib.error import HTTPError, URLError
        reason = str(error).strip() or type(error).__name__
        detail = {"type": "motion_error", "stage": stage, "reason": reason, "pack": pack}
        if isinstance(error, HTTPError):
            detail["httpStatus"] = error.code
        elif isinstance(error, URLError):
            detail["reason"] = str(error.reason).strip() or reason
        job.emit(detail)
        # JobManager retains the chained traceback; even older clients receive
        # the actual failing stage/reason in their ordinary done summary.
        raise ValueError(stage + (" (" + pack + ")" if pack else "") + ": " + detail["reason"]) from error
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)
        _SLOT.release()
