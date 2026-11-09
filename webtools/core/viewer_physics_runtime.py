"""Bind costume-dependent original game physics settings to verified sources.

The manager's serialized booleans are not the game's Initialize arguments.
Home/member and Live profiles are recovered from the original 3.12 code; the
Live costume exception is obtained only from a validated game import receipt.
An arbitrary filename or display name never establishes a costume identity.
"""
from pathlib import Path
import sqlite3


def motion_settings(*, repo_root, record):
    """The original song-specific LateUpdate switch, independent of costume."""
    if record.get("category") != "mv":
        return {"profile": "navi", "safeSwingBoneKnown": True, "safeSwingBone": False}
    result = {"profile": "live", "liveId": record.get("live_id"),
              "safeSwingBoneKnown": False, "safeSwingBone": None}
    if (record.get("region") not in ("gl", "jp") or type(record.get("live_id")) is not int or
            not 0 < record["live_id"] < 10 ** 12):
        return result
    from . import game_models
    try:
        database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
        try:
            row = database.execute("SELECT safe_swing_bone FROM m_live_visible_definition WHERE live_m_id=?",
                                   (record["live_id"],)).fetchone()
        finally:
            database.close()
        value = row[0] if row is not None and row[0] is not None else 0
        if type(value) is int and value in (0, 1):
            result.update(safeSwingBoneKnown=True, safeSwingBone=bool(value))
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    return result


def describe(context, physics, *, repo_root, cache_root):
    indices = sorted({row["sourceIndex"] for row in physics.get("managers", [])})
    result = {"profile": "sifas-3.12.0", "sources": [
        {"sourceIndex": index, "known": False, "suitId": None, "skirtsafeDisable": None}
        for index in indices]}
    if not indices:
        return result
    from . import game_models, viewer_mod_flow, viewer_mod_sources
    try:
        bindings = viewer_mod_sources.game_context(context, repo_root,
            receipts=viewer_mod_flow.cached_receipts(context, cache_root))
    except (ImportError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return result
    indexed = {row["sourceIndex"]: row for row in result["sources"]}
    seen = set()
    for binding in bindings:
        index, record = binding["source"], binding["record"]
        if index not in indexed or index in seen:
            continue
        seen.add(index)
        try:
            database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
            try:
                row = database.execute("SELECT skirtsafe_disable FROM m_suit_custom3d WHERE suit_master_id=?",
                                       (record["suit_id"],)).fetchone()
            finally:
                database.close()
            # The original nullable lookup defaults an absent/NULL value to
            # false. Invalid data remains unknown, not a guessed false value.
            value = row[0] if row is not None and row[0] is not None else 0
            if type(value) is not int or value not in (0, 1):
                continue
            indexed[index].update(known=True, suitId=record["suit_id"], region=record["region"],
                                  skirtsafeDisable=bool(value))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            continue
    return result
