"""Read a selected 3D MV from the game's regional master and asset indexes."""

from collections import deque
from contextlib import closing, contextmanager
import html
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from urllib.error import HTTPError

from . import game_models as game
from . import mv_studio_suits
from .game_motions import _columns, _rows


PLATFORMS = {"android": "Android", "ios": "iOS"}
REGIONS = {"gl": "Global (GL)", "jp": "Japan (JP)"}
ASSET_TABLES = (
    "live_timeline", "stage", "stage_effect", "live_prop_skeleton", "shader",
    "member_model", "member_facial_animation", "member_facial", "texture", "background",
)
DEPENDENCY_TABLES = frozenset(ASSET_TABLES) - {"texture", "background"}
MAX_ROWS = 5000
MAX_ASSETS = 192
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_PACK_BYTES = 2 * 1024 * 1024 * 1024
_ID = re.compile(r"[1-9][0-9]{0,11}\Z")
_PACK = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
# Downloaded packs an import keeps for its other sections (shared_downloads).
_SHARED_PACK_BYTES = 192 * 1024 * 1024
_SHARED = threading.local()


def _identity(value):
    if type(value) not in (str, int) or not _ID.fullmatch(str(value)):
        raise ValueError("Choose a valid game MV and stage.")
    return int(value)


def _selection(root, region, platform, language):
    if not isinstance(region, str) or region not in (*REGIONS, "") or not isinstance(platform, str) or platform not in PLATFORMS:
        raise ValueError("Choose a supported game region and asset platform.")
    if not isinstance(language, str) or len(language) > 24:
        raise ValueError("Choose a supported display language.")
    language = language.lower().split("-", 1)[0].split("_", 1)[0]
    language = language if language in ("en", "ko", "zh", "ja") else "en"
    root = Path(root).resolve()
    region, regions = game._region(root, region, language)
    return root, region, regions, language


def _asset_catalogs(root, region, platform, language):
    prefix = "asset_i_" if platform == "ios" else "asset_a_"
    global_locales = ("en", "ko", "zh")
    preferred = language if language in global_locales else "en"
    locales = ("ja",) if region == "jp" else dict.fromkeys((preferred, *global_locales))
    directory = root / "assets/db" / region
    return [path for locale in locales if (path := directory / f"{prefix}{locale}.db").is_file()]


def _variant_rows(db, selected=None):
    # The client's MV stage picker lists m_live_mv rows by their live_stage_master_id
    # (SelectableStageVO), but Live3DDM.GetMvLive3DAssetVO loads the stage scene and
    # model from m_live_3d_asset.live_stage_master_id of the row's 3D asset. The
    # m_live_mv stage id is only the picker key and never chooses the stage.
    condition = " AND live.live_id=? AND asset.id=?" if selected else ""
    common = "FROM m_live AS live JOIN {table} AS mv ON mv.live_id=live.live_id " \
             "JOIN m_live_3d_asset AS asset ON asset.id=mv.live_3d_asset_master_id " \
             "LEFT JOIN m_live_stage AS stage ON stage.id=asset.live_stage_master_id " \
             "WHERE asset.timeline IS NOT NULL AND asset.timeline<>''{condition} "
    rows = []
    for table, priority in (("m_live_mv", 0), ("m_live_difficulty", 1)):
        position = "mv.position" if not priority else "0"
        picker = "mv.live_stage_master_id" if not priority else "NULL"
        columns = (
            "live.live_id,asset.id,live.name,stage.stage_name,stage.scene_name,"
            f"asset.live_stage_master_id, {position} AS position,"
            "NOT EXISTS(SELECT 1 FROM m_live_difficulty d WHERE d.live_id=live.live_id) AS mv_only,"
            f"{priority} AS priority, {picker} AS picker_stage"
        )
        query = "SELECT DISTINCT " + columns + " " + common.format(table=table, condition=condition)
        # No silent partial catalogs. These tables normally return hundreds of rows.
        found = _rows(db, query + "LIMIT ?", (*selected, MAX_ROWS+1) if selected else (MAX_ROWS+1,))
        if len(found) > MAX_ROWS:
            raise ValueError("The game contains too many 3D MV catalog rows.")
        rows.extend(found)
    return sorted(rows, key=lambda row: (row[0], row[8], row[6] or 0, row[1]))


def _display(extractor, dictionary, raw, fallback):
    value = extractor.real_costume_name(dictionary, raw) if isinstance(raw, str) else None
    return html.unescape(str(value or fallback))[:260]


def catalog(repo_root, *, region="", platform="android", language="en", search=""):
    if not isinstance(search, str) or len(search) > 120:
        raise ValueError("Choose a valid MV search.")
    root, region, regions, language = _selection(repo_root, region, platform, language)
    extractor = game._extractor()
    with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as db:
        rows = _variant_rows(db)
    by_song, variants = {}, set()
    dictionary = game._dictionary(root, region, language)
    try:
        for live, asset, title, stage, scene, stage_id, position, mv_only, priority, picker_stage in rows:
            if (live, asset) in variants:
                continue
            variants.add((live, asset))
            if live not in by_song:
                by_song[live] = {"id": live, "title": _display(extractor, dictionary, title, str(live)),
                                 "variants": [], "mvOnly": bool(mv_only)}
            label = _display(extractor, dictionary, stage, scene or str(asset))
            by_song[live]["variants"].append({"id": asset, "label": label, "stageId": stage_id,
                                               "pickerStageId": picker_stage,
                                               "sceneName": scene, "position": position,
                                               # bg0018_02_s1 -> bg0018_02: tells same-named stages apart.
                                               "scene": re.sub(r"_s\d+$", "", scene) if isinstance(scene, str) else None,
                                               "source": "difficulty" if priority else "mv"})
            # Only m_live_mv rows appear in the client's MV screen; the others are live (rhythm game) 3D.
            by_song[live]["inMvList"] = by_song[live].get("inMvList", False) or not priority
    finally:
        if dictionary is not None:
            dictionary.close()
    query = search.strip().casefold()
    songs = sorted(by_song.values(), key=lambda row: (row["title"].casefold(), row["id"]))
    if query:
        songs = [song for song in songs if query in song["title"].casefold() or query in str(song["id"]) or
                 any(query in variant["label"].casefold() or query in str(variant["id"]) for variant in song["variants"])]
    available = {value: bool(_asset_catalogs(root, region, value, language)) for value in PLATFORMS}
    return {"region": region, "platform": platform, "songs": songs, "players": mv_studio_suits.users(root),
            "regions": [{"value": value, "label": REGIONS[value]} for value in regions],
            "platforms": [{"value": value, "label": label, "available": available[value]}
                          for value, label in PLATFORMS.items()]}


def _pack_rows(db, names):
    if any(not isinstance(name, str) or not _PACK.fullmatch(name) for name in names):
        raise ValueError("The game asset has an invalid pack identity.")
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = _rows(db, "SELECT pack_name,file_size,metapack_name,metapack_offset FROM m_asset_package_mapping "
                 f"WHERE pack_name IN ({placeholders}) ORDER BY pack_name,metapack_name IS NULL,package_key", names)
    result = {}
    for name, size, meta, offset in rows:
        result.setdefault(name, (size, meta, offset))
    return result


def _mapping_info(info, end):
    size, meta, offset = info
    if type(size) is not int or not max(1, end) <= size <= MAX_PACK_BYTES:
        raise ValueError("The game asset's catalogued pack size is invalid.")
    if meta and (not isinstance(meta, str) or not _PACK.fullmatch(meta) or
                 type(offset) is not int or not 0 <= offset <= (1 << 42)-size):
        raise ValueError("The game asset's metapack offset is invalid.")
    return {"pack_size": size, "metapack": {"name": meta, "offset": offset, "size": size} if meta else None}


def _link_bundle_packs(db, descriptors):
    # Pack mappings are indexed by package key, so look up all the selected
    # sections in a single read instead of rescanning the table for each asset.
    descriptors = [item for item in descriptors if item and item["available"]]
    known = _pack_rows(db, tuple(sorted({item["pack_name"] for item in descriptors})))
    for item in descriptors:
        info = known.get(item["pack_name"])
        if info is not None:
            item.update(_mapping_info(info, item["head"] + item["size"]))


def _resource(db, table, asset, role):
    if table not in ASSET_TABLES or not isinstance(asset, str) or not 0 < len(asset) <= 255 or "\0" in asset:
        return None
    rows = _rows(db, f"SELECT pack_name,head,size,key1,key2 FROM {table} WHERE asset_path=? LIMIT 2", (asset,))
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("The game asset catalog has an ambiguous asset identity.")
    name, head, size, key1, key2 = rows[0]
    if (not isinstance(name, str) or not _PACK.fullmatch(name) or
            any(type(value) is not int for value in (head, size, key1, key2)) or
            not 0 <= head <= MAX_PACK_BYTES or not 0 < size <= MAX_ASSET_BYTES or head+size > MAX_PACK_BYTES or
            not all(-(1 << 31) <= key < 1 << 32 for key in (key1, key2))):
        raise ValueError("The game asset has invalid section metadata.")
    return {"table": table, "asset": asset, "role": role, "format": "unity", "available": True,
            "pack_name": name, "head": head, "size": size, "key1": key1, "key2": key2,
            "pack_size": None, "metapack": None}


def _raw_resource(db, table, name, role, format_name):
    if not name or name == "0":
        return None
    info = _pack_rows(db, (name,)).get(name)
    if info is None:
        return None
    mapping = _mapping_info(info, 0)
    if mapping["pack_size"] > MAX_ASSET_BYTES:
        return None
    return {"table": table, "asset": name, "role": role, "format": format_name, "available": True,
            "pack_name": name, "head": 0, "size": mapping["pack_size"], **mapping}


def _required(db, tables, asset, role, missing):
    if not asset:
        return None
    for table in tables:
        descriptor = _resource(db, table, asset, role)
        if descriptor is not None:
            return descriptor
    missing.append({"role": role, "asset": asset, "reason": "Not present in the selected asset catalog."})
    return {"table": tables[0], "asset": asset, "role": role, "format": "unity", "available": False}


def _dependencies(db, roots, missing):
    found, visited = [], set()
    pending = deque(item for item in roots if item and item["available"])
    rooted = {(item["table"], item["asset"]) for item in pending}
    requested = set()
    while pending:
        parent = pending.popleft()
        key = parent["table"], parent["asset"]
        if key in visited or parent["table"] not in DEPENDENCY_TABLES:
            continue
        visited.add(key)
        children = _rows(db, f"SELECT dependency FROM {parent['table']}_dependency WHERE asset_path=? ORDER BY dependency LIMIT ?",
                         (parent["asset"], MAX_ASSETS+1))
        if len(children) > MAX_ASSETS:
            raise ValueError("This MV has too many linked game assets.")
        for asset, in children:
            tables = (parent["table"], *(table for table in ASSET_TABLES if table != parent["table"]))
            role = "choreography" if parent["table"] == "live_timeline" else "dependency"
            if (parent["table"], asset) in requested:
                continue
            requested.add((parent["table"], asset))
            if len(requested) > MAX_ASSETS:
                raise ValueError("This MV has too many linked game assets.")
            child = _required(db, tables, asset, role, missing)
            if not child or not child["available"]:
                continue
            child_key = child["table"], child["asset"]
            if child_key in rooted:
                continue
            rooted.add(child_key)
            if len(rooted) > MAX_ASSETS:
                raise ValueError("This MV has too many linked game assets.")
            role = "shader" if child["table"] == "shader" else role
            if role == "choreography" and child["table"] != "live_timeline":
                role = "dependency"
            child = dict(child, role=role, parent={"table": key[0], "asset": key[1]})
            found.append(child)
            pending.append(child)
    return found


def _sound(db, cue, missing, role):
    if not cue:
        return None
    candidates = _rows(db, "SELECT sheet_name,acb_pack_name,awb_pack_name FROM m_asset_sound "
                       "WHERE sheet_name=? OR substr(?,1,length(sheet_name)+1)=sheet_name || '_' "
                       "ORDER BY length(sheet_name) DESC LIMIT 16", (cue, cue))
    sheets = []
    for sheet, acb_name, awb_name in candidates:
        acb = _raw_resource(db, "m_asset_sound", acb_name, "acb", "acb")
        awb = _raw_resource(db, "m_asset_sound", awb_name, "awb", "awb")
        if not acb or (awb_name and awb_name != "0" and not awb):
            continue
        sheets.append({"sheet": sheet, "acb": acb, "awb": awb})
    if not sheets:
        missing.append({"role": role, "asset": cue, "reason": "No matching CRI sound bank is catalogued."})
        return {"cue": cue, "sheet": None, "acb": None, "awb": None, "candidates": []}
    return {"cue": cue, **sheets[0], "candidates": sheets}


def _pinned_costumes(costumes):
    """{position: (suit id, view status or None)} from an explicit request; None when nothing is pinned.

    A pin is a suit id, or {"suit": id, "viewStatus": n} for an m_suit_view model."""
    if costumes is None:
        return None
    if not isinstance(costumes, dict) or len(costumes) > 64:
        raise ValueError("Choose valid costumes for the MV members.")
    pinned = {}
    for position, value in costumes.items():
        position = int(position) if isinstance(position, str) and position.isdigit() else position
        suit, view = (value.get("suit"), value.get("viewStatus")) if isinstance(value, dict) else (value, None)
        if (type(position) is not int or not 1 <= position <= 64 or type(suit) is not int or not 0 < suit < 1 << 31 or
                isinstance(value, dict) and set(value) - {"suit", "viewStatus"} or
                view is not None and (type(view) is not int or not 0 < view < 64)):
            raise ValueError("Choose valid costumes for the MV members.")
        pinned[position] = (suit, view)
    return pinned


_CHOICE_LIMIT = 96


def _choices(master, dictionary, extractor, member, non_playable, first):
    """Costume override choices: the resolved/mapping/initial suits first, then the member's other
    suits; every suit followed by its m_suit_view models."""
    if non_playable:
        rows = _rows(master, "SELECT id,name,model_asset_path FROM m_suit_non_playable WHERE member_m_id=? ORDER BY rowid",
                     (member,))
    else:
        order = "display_order DESC,id" if "display_order" in _columns(master, "m_suit") else "id"
        rows = _rows(master, f"SELECT id,name,model_asset_path FROM m_suit WHERE member_m_id=? ORDER BY {order}", (member,))
    known = {row[0]: row for row in rows}
    order = [suit for suit in dict.fromkeys([*first, *known]) if suit in known][:_CHOICE_LIMIT]
    choices = []
    for suit in order:
        _, name, _ = known[suit]
        label = _display(extractor, dictionary, name, suit)
        choices.append({"id": suit, "name": label, "asset": mv_studio_suits.costume(master, suit)[0]})
        for status in mv_studio_suits.views(master, suit):
            model, _ = mv_studio_suits.costume(master, suit, status)
            choices.append({"id": suit, "name": label, "asset": model, "viewStatus": status})
    return choices


def _performers(master, db, mapping, dictionary, extractor, missing, costumes=None, deck=None):
    deck_type = (deck or {}).get("deckType", mv_studio_suits.DEFAULT_DECK)
    by_position = mv_studio_suits.members_by_position(mv_studio_suits.mapping(master, mapping), deck_type, deck)
    cache = mv_studio_suits._Master(master)
    names = game._names(extractor)

    def themes_for(table, ids):
        keys = tuple(sorted({value for value in ids if type(value) is int and value > 0}))
        if not keys:
            return {}
        slots = ",".join("?" for _ in keys)
        return dict(_rows(master, f"SELECT id,theme_color FROM {table} WHERE id IN ({slots})", keys))

    rows = [row for _, row in sorted(by_position.items())]
    themes = themes_for("m_member", (row["member"] for row in rows if not row["nonPlayable"]))
    non_playable_themes = themes_for("m_member_non_playable", (row["member"] for row in rows if row["nonPlayable"]))
    performers = []
    for row in rows:
        position, member = row["position"], row["member"]
        resolved, source = mv_studio_suits.suit_for(master, row, deck_type, deck, cache)
        suit, view = resolved, mv_studio_suits.view_status(deck, member)
        if costumes and position in costumes:
            # An explicit costume (e.g. the suit a recorded game performance wore) must
            # belong to this member; it is never silently replaced by the resolved suit.
            suit, pinned_view = costumes[position]
            table = "m_suit_non_playable" if row["nonPlayable"] else "m_suit"
            if not _rows(master, f"SELECT 1 FROM {table} WHERE id=? AND member_m_id=?", (suit, member)):
                raise ValueError(f"Costume {suit} is not a costume of the member at position {position}.")
            if pinned_view is not None:
                if pinned_view != mv_studio_suits.VIEW_DEFAULT and pinned_view not in mv_studio_suits.views(master, suit):
                    raise ValueError(f"Costume {suit} has no view status {pinned_view} model.")
                view = pinned_view
            source = "pinned"
        asset, effective_view = mv_studio_suits.costume(master, suit, view) if suit else (None, mv_studio_suits.VIEW_DEFAULT)
        choices = _choices(master, dictionary, extractor, member, row["nonPlayable"],
                           [suit, resolved, row.get("suit"), cache.member_init(member)])
        chosen = next((choice for choice in choices if choice["id"] == suit), None)
        model = _required(db, ("member_model",), asset, "costume", missing) if asset else None
        performers.append({"position": position, "memberId": member, "memberName": names.get(member, str(member or "")),
                           "isCenter": bool(row["isCenter"]), "costumeId": suit,
                           "costumeName": chosen["name"] if chosen else None, "costumes": choices, "model": model,
                           "viewStatus": effective_view, "suitSource": source, "nonPlayable": row["nonPlayable"],
                           "attachKey": mv_studio_suits.attach_key(master, suit) if suit else ""})
        color = (non_playable_themes if row["nonPlayable"] else themes).get(member)
        if type(color) is int and -(1 << 31) <= color < 1 << 32:
            # ColorVO stores signed SQLite integers as packed RGBA bytes.
            performers[-1]["themeColor"] = [((color >> shift) & 255) / 255 for shift in (24, 16, 8, 0)]
    if costumes and set(costumes) - {row["position"] for row in performers}:
        raise ValueError("A requested costume has no member at its position in this MV.")
    return performers


def _resolve_assets(db, master, variant, song, asset, dictionary, extractor, costumes=None, deck=None):
    live_id, asset_id, title, stage_title, scene, stage_id, _, mv_only, _, _ = variant
    name = _display(extractor, dictionary, title, live_id)
    music_id, cue, chorus, member_mapping, song_background = song
    timeline_key, effect_key, prop_key, quality, shader_key = asset
    stage_row = _rows(master, "SELECT stage_model_asset_path,stage_thumbnail_asset_path,stage_background_asset_path "
                      "FROM m_live_stage WHERE id=?", (stage_id,))
    stage_model_key, thumb_key, bg_key = stage_row[0] if stage_row else (None, None, None)
    if not stage_model_key:
        raise ValueError("The selected MV stage has no game stage model reference.")
    missing = []
    timeline = _required(db, ("live_timeline",), timeline_key, "timeline", missing)
    model = _required(db, ("stage",), stage_model_key, "stage", missing)
    effect = _required(db, ("stage_effect",), effect_key, "stageEffect", missing)
    props = _required(db, ("live_prop_skeleton",), prop_key, "props", missing)
    background = _required(db, ("background", "texture"), bg_key, "stageBackground", missing)
    thumbnail = _required(db, ("texture", "background"), thumb_key, "stageThumbnail", missing)
    song_background = _required(db, ("background", "texture"), song_background, "songBackground", missing)
    shader = _required(db, ("shader",), shader_key, "shader", missing)
    performers = _performers(master, db, member_mapping, dictionary, extractor, missing, costumes, deck)
    for performer in performers:
        member = performer["memberId"]
        if member is None:
            continue
        # MemberOverrideFacialAnimationMaster.Get(member, view status, type 1 / 2): the
        # effective view status of the loaded model (GetMvLiveMember3DAssetVOs b__1).
        overrides = _rows(master, "SELECT animation_asset_path FROM m_member_override_facial_animation "
                                 "WHERE member_id=? AND view_status=? AND animation_type IN (1,2) ORDER BY animation_type",
                          (member, performer.get("viewStatus", mv_studio_suits.VIEW_DEFAULT)))
        performer["facial"] = [descriptor for key in dict.fromkeys(row[0] for row in overrides if row[0])
                               if (descriptor := _resource(db, "member_facial_animation", key, "face")) is not None]
        if performer_model := performer["model"]:
            keys = _rows(db, "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency LIMIT 8",
                         (performer_model["asset"],))
            performer["companions"] = [descriptor for key, in keys if (descriptor :=
                _resource(db, "member_model", key, "face") or _resource(db, "member_facial", key, "face")) is not None]
    dependencies = _dependencies(db, [timeline, model, effect, props, shader, *(row["model"] for row in performers)], missing)
    audio = _sound(db, cue, missing, "audio") or {"cue": cue, "sheet": None, "acb": None, "awb": None, "candidates": []}
    audio.update(musicId=music_id, chorus=_sound(db, chorus, missing, "chorus"))
    movie = None
    movie_rows = _rows(master, "SELECT codec,movie_asset_path,stage_background_asset_path FROM m_live_movie WHERE live_id=? LIMIT 2", (live_id,))
    if len(movie_rows) == 1:
        codec, movie_asset, movie_bg = movie_rows[0]
        packs = _rows(db, "SELECT pack_name FROM m_movie WHERE pavement=? LIMIT 2", (movie_asset,))
        source = _raw_resource(db, "m_movie", packs[0][0], "movie", "movie") if len(packs) == 1 else None
        movie = {"codec": codec, "asset": movie_asset, "source": source,
                 "background": _required(db, ("background", "texture"), movie_bg, "movieBackground", missing)}
        if not source and movie_asset:
            missing.append({"role": "movie", "asset": movie_asset, "reason": "The movie pack is not catalogued."})
    stage = {"id": stage_id, "name": _display(extractor, dictionary, stage_title, scene or stage_id),
             "sceneName": scene, "model": model, "effect": effect, "background": background,
             "thumbnail": thumbnail, "props": props}
    _link_bundle_packs(db, [timeline, model, effect, props, background, thumbnail, song_background, shader,
                            *(row["model"] for row in performers), *dependencies,
                            *(item for row in performers for field in ("facial", "companions")
                              for item in row.get(field, [])), movie and movie["background"]])
    return {"name": name, "title": name, "liveId": live_id, "assetId": asset_id, "mvOnly": bool(mv_only),
            "qualitySet": quality, "stage": stage, "stageModel": model, "stageEffect": effect,
            "timeline": timeline, "timelineKey": timeline_key, "cameras": {"timeline": timeline_key},
            "lighting": {"timeline": timeline_key, "stageEffect": effect_key},
            "screens": {"timeline": timeline_key, "stageEffect": effect_key, "movie": movie},
            "songBackground": song_background, "performers": performers, "audio": audio, "movie": movie,
            "choreography": [item for item in dependencies if item["role"] == "choreography"],
            "shaderDependencies": ([shader] if shader and shader["available"] else []) +
                                  [item for item in dependencies if item["role"] == "shader"],
            "dependencies": dependencies, "missing": missing}


def _deck(root, deck, live_id):
    """The player MV state: a new player's when absent, the local Elichika player's for {"userId": id}."""
    deck = mv_studio_suits.normalize_deck(deck)
    if deck is not None and "userId" in deck:
        deck = mv_studio_suits.read_user(root, deck["userId"], live_id, deck["deckType"])
    return deck


def resolve(repo_root, *, region, platform, live_id, asset_id, language="en", costumes=None, deck=None):
    """Performers follow the client's MV deck chain (mv_studio_suits).

    `deck` optionally gives the player state: {"deckType": 1 (Original) | 2 (Customize, the
    client's first tab), "userId": local Elichika player} or the same state read elsewhere
    ({"original"/"custom": {"members", "suits"}, "ownedSuits", "members": {id: {"viewStatus"}}}).
    `costumes` optionally pins {position: suit id or {"suit", "viewStatus"}} over the chain."""
    costumes = _pinned_costumes(costumes)
    root, region, _, language = _selection(repo_root, region, platform, language)
    ids = _identity(live_id), _identity(asset_id)
    deck = _deck(root, deck, ids[0])
    catalogs = _asset_catalogs(root, region, platform, language)
    if not catalogs:
        raise ValueError("The selected region has no " + PLATFORMS[platform] + " asset catalog.")
    extractor = game._extractor()
    with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as master:
        master.execute("BEGIN")
        variants = _variant_rows(master, ids)
        if not variants:
            raise ValueError("The selected game MV and stage are no longer available. Refresh the list.")
        song = master.execute("SELECT music_id,bgm_path,chorus_bgm_path,live_member_mapping_id,background_asset_path "
                              "FROM m_live WHERE live_id=?", ids[:1]).fetchone()
        registered_song = _registered_song(master, ids[0])
        registered = registered_song is not None
        override = _timeline_override(master, ids[1])
        asset = master.execute("SELECT timeline,stage_effect_asset_path,live_prop_skeleton_asset_path,"
                               "quality_setitng_set_id,shader_variant_asset_path FROM m_live_3d_asset WHERE id=?", ids[1:]).fetchone()
        chosen = catalogs[0]
        for path in catalogs:
            with closing(game._readonly(path)) as db:
                if _rows(db, "SELECT 1 FROM live_timeline WHERE asset_path=? LIMIT 1", (asset[0],)):
                    chosen = path
                    break
        dictionary = game._dictionary(root, region, language)
        try:
            with closing(game._readonly(chosen)) as db:
                db.execute("BEGIN")
                result = _resolve_assets(db, master, variants[0], song, asset, dictionary, extractor, costumes, deck)
        finally:
            if dictionary is not None:
                dictionary.close()
    deck_state = {"deckType": (deck or {}).get("deckType", mv_studio_suits.DEFAULT_DECK),
                  "userId": (deck or {}).get("userId"),
                  "saved": any(name in (deck or {}) for name in ("original", "custom"))}
    return dict(result, region=region, platform=platform, assetCatalog=chosen.name, registered=registered,
                **({"registeredSong": registered_song} if registered else {}),
                **({"timelineOverride": override} if override else {}), deck=deck_state)


def _registered_song(master, live_id):
    """The MV Studio song registered under ``live_id`` (Elichika's _elichika_mv_studio_song row), or None.

    Its revision, last update and base song, as the store describes them: the store reuses the IDs
    of removed songs, so a project opened from this song keeps them to tell it from a later song
    registered under the same ID. Rows from before the store's revisions have revision 0."""
    columns = _columns(master, "_elichika_mv_studio_song")
    if not {"live_id", "source_live_id"} <= columns:
        return None
    fields = ["source_live_id"] + [name for name in ("revision", "updated_at") if name in columns]
    rows = _rows(master, f"SELECT {','.join(fields)} FROM _elichika_mv_studio_song WHERE live_id=?", (live_id,))
    if not rows:
        return None
    row = dict(zip(fields, rows[0]))
    return {"revision": row.get("revision") or 0, "updatedAt": row.get("updated_at"),
            "templateLiveId": row["source_live_id"]}


def _timeline_override(master, asset_id):
    """{revision, updatedAt} of the timeline MV Studio applied to this stock 3D MV (Elichika's
    _elichika_mv_studio_timeline row), or None while it plays its original timeline."""
    columns = _columns(master, "_elichika_mv_studio_timeline")
    if not {"asset_id", "revision"} <= columns:
        return None
    fields = ["revision"] + (["updated_at"] if "updated_at" in columns else [])
    rows = _rows(master, f"SELECT {','.join(fields)} FROM _elichika_mv_studio_timeline WHERE asset_id=?", (asset_id,))
    if not rows:
        return None
    row = dict(zip(fields, rows[0]))
    return {"revision": row.get("revision") or 0, "updatedAt": row.get("updated_at")}


def _cached_pack(extractor, root, name):
    for directory in (root, root / "files", root / "files/files", root / "static", root / "static/files"):
        for parent in (directory, directory / ("pkg" + name[0])):
            candidate = extractor._pack_path(str(root), str(parent / name), name)
            if candidate:
                return Path(candidate).resolve()
    key = str(root)
    cache = extractor._pack_index_cache
    if key not in cache:
        index = extractor._load_disk_index(key)
        if index is not None:
            cache[key] = index
    candidate = extractor._pack_path(key, cache.get(key, {}).get(name), name)
    return Path(candidate).resolve() if candidate else None


def _local_section(extractor, root, descriptor, deadline):
    game_roots = [path for path, status in extractor.detect_game_candidates() if status == "found"]
    sources = [(descriptor["pack_name"], 0, descriptor.get("pack_size"))]
    meta = descriptor.get("metapack")
    if meta:
        sources.append((meta["name"], meta["offset"], None))
    for directory in extractor.build_pack_roots(str(root), None, game_roots):
        _check_deadline(deadline)
        for name, offset, expected in sources:
            path = _cached_pack(extractor, Path(directory).resolve(), name)
            if path is None:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            except (FileNotFoundError, PermissionError):
                continue
            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                if (not stat.S_ISREG(before.st_mode) or expected is not None and before.st_size != expected or
                        before.st_size < offset + descriptor["head"] + descriptor["size"]):
                    continue
                handle.seek(offset + descriptor["head"])
                payload = handle.read(descriptor["size"])
                after = os.fstat(handle.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("The selected game pack changed during import. Try again.")
                return payload
    return None


class _ReadJob:
    def should_stop(self):
        return False

    def log(self, message):
        pass


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        from .transient_failures import note
        note()
        raise ValueError("Reading the selected MV assets took too long. Try again.")


@contextmanager
def shared_downloads():
    """Within this block, on this thread, a missing pack is downloaded once.

    Several sections of one import often live in the same pack (a group MV
    downloaded 50 packs, 32 of them distinct: 107 MB instead of 44 MB). The
    whole pack is kept for the block's other sections, up to _SHARED_PACK_BYTES.
    """
    previous = getattr(_SHARED, "packs", None)
    if previous is None:
        _SHARED.packs = {}
    try:
        yield
    finally:
        if previous is None:
            _SHARED.packs = None


def _remote_pack(descriptor, extractor, deadline):
    held = getattr(_SHARED, "packs", None)
    meta = descriptor.get("metapack")
    key = (descriptor["pack_name"], descriptor.get("pack_size"), meta and (meta["name"], meta["offset"], meta.get("size")))
    if held is not None and key in held:
        return held[key]
    pack = game._remote_pack(descriptor, extractor, _ReadJob(), deadline)
    if held is not None and isinstance(pack, bytes) and sum(map(len, held.values())) + len(pack) <= _SHARED_PACK_BYTES:
        held[key] = pack
    return pack


def load_asset(repo_root, descriptor, *, download=False, deadline=None):
    """Read one bounded section by catalog identity. Missing local assets return None."""
    if descriptor is None or isinstance(descriptor, dict) and descriptor.get("available") is False:
        return None
    if not isinstance(descriptor, dict) or type(download) is not bool:
        raise ValueError("Choose a valid game asset descriptor.")
    name, head, size = (descriptor.get(field) for field in ("pack_name", "head", "size"))
    format_name, pack_size, meta = (descriptor.get(field) for field in ("format", "pack_size", "metapack"))
    if (not isinstance(name, str) or not _PACK.fullmatch(name) or type(head) is not int or type(size) is not int or
            not 0 <= head <= MAX_PACK_BYTES or not 0 < size <= MAX_ASSET_BYTES or head+size > MAX_PACK_BYTES or
            format_name not in ("unity", "acb", "awb", "movie") or
            pack_size is not None and (type(pack_size) is not int or not head+size <= pack_size <= MAX_PACK_BYTES) or
            meta is not None and (not isinstance(meta, dict) or not isinstance(meta.get("name"), str) or
                                  not _PACK.fullmatch(meta["name"]) or type(meta.get("offset")) is not int or
                                  pack_size is None or not 0 <= meta["offset"] <= (1 << 42)-pack_size or
                                  meta.get("size") != pack_size)):
        raise ValueError("Choose a valid game asset descriptor.")
    deadline = time.monotonic()+20 if deadline is None else deadline
    extractor = game._extractor()
    payload = _local_section(extractor, Path(repo_root).resolve(), descriptor, deadline)
    if payload is None and download:
        try:
            pack = _remote_pack(descriptor, extractor, deadline)
        except HTTPError as error:
            if error.code in (404, 410):
                return None
            raise
        payload = pack[head:head+size]
    _check_deadline(deadline)
    if payload is None:
        return None
    if len(payload) != size:
        raise ValueError("The selected game pack section is incomplete.")
    if format_name == "unity":
        if any(type(descriptor.get(key)) is not int or not -(1 << 31) <= descriptor[key] < 1 << 32 for key in ("key1", "key2")):
            raise ValueError("The selected Unity asset has invalid catalog keys.")
        plain = bytearray(payload)
        extractor.decrypt_section(plain, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
        from .model_viewer import _preflight_bundle
        _preflight_bundle(plain)
        payload = bytes(plain)
    elif format_name in ("acb", "awb") and payload[:4] != {"acb": b"@UTF", "awb": b"AFS2"}[format_name]:
        raise ValueError("The selected sound pack has an invalid CRI header.")
    return payload
