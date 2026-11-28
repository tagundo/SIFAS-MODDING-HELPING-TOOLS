"""A minimal game catalog for the face-original proof tests (no game data).

One member's default costume (m_member_init -> m_suit) whose body depends on
face assets in packs. Elichika's ``llas_asset_extractor`` is replaced by a
stand-in whose section decryption is the identity, so a pack holds the face
bytes as they are; the face plan's own catalog listing and pack reading run
unchanged on these files.
"""
from pathlib import Path
import sqlite3
import sys
import types


def extractor_module(root):
    module = types.ModuleType("llas_asset_extractor")
    module.FIXED_KEY0 = 0
    module.DEFAULT_CDN_BASE = "https://assets.invalid/static/"
    module.COPIED_PACKS_DIR = str(Path(root) / "no-copied-packs")
    module.list_asset_dbs = lambda repo: sorted(str(path) for path in Path(repo).glob("assets/db/*/asset_*.db"))
    module.detect_game_candidates = lambda: []
    module.decrypt_section = lambda data, key0, key1, key2: None
    return module


def install_extractor(root):
    """Put the stand-in extractor in ``sys.modules``; returns the function that restores the entry."""
    missing = object()
    previous = sys.modules.get("llas_asset_extractor", missing)
    sys.modules["llas_asset_extractor"] = extractor_module(root)

    def restore():
        if previous is missing:
            sys.modules.pop("llas_asset_extractor", None)
        else:
            sys.modules["llas_asset_extractor"] = previous
    return restore


def write_catalog(root, owner, faces, *, suit=None, body="body-default", local=True, platform="a", region="gl"):
    """Write the catalog of ``owner``'s default costume.

    ``faces`` maps asset paths to ``(pack name, bytes)``; the default body
    depends on each of them. With ``local`` each pack is written to the
    repository's ``static`` folder, where local packs are read first.
    Returns the face plan descriptors of the faces, by asset path.
    """
    root = Path(root)
    suit = suit or owner * 1000 + 1
    directory = root / "assets" / "db" / region
    directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(directory / "masterdata.db") as db:
        db.executescript("CREATE TABLE IF NOT EXISTS m_suit(id INTEGER, member_m_id INTEGER, model_asset_path TEXT);"
                         "CREATE TABLE IF NOT EXISTS m_member_init(member_m_id INTEGER, suit_m_id INTEGER);")
        db.execute("DELETE FROM m_suit WHERE member_m_id=?", (owner,))
        db.execute("DELETE FROM m_member_init WHERE member_m_id=?", (owner,))
        db.execute("INSERT INTO m_suit VALUES(?,?,?)", (suit, owner, body))
        db.execute("INSERT INTO m_member_init VALUES(?,?)", (owner, suit))
    descriptors = {}
    with sqlite3.connect(directory / f"asset_{platform}_en.db") as db:
        db.executescript("CREATE TABLE IF NOT EXISTS member_model(asset_path TEXT, pack_name TEXT, head INTEGER, size INTEGER,"
                         " key1 INTEGER, key2 INTEGER);"
                         "CREATE TABLE IF NOT EXISTS member_model_dependency(asset_path TEXT, dependency TEXT);"
                         "CREATE TABLE IF NOT EXISTS m_asset_package_mapping(pack_name TEXT, file_size INTEGER);")
        db.execute("DELETE FROM member_model_dependency WHERE asset_path=?", (body,))
        for asset, (pack, raw) in faces.items():
            db.execute("DELETE FROM member_model WHERE asset_path=?", (asset,))
            db.execute("DELETE FROM m_asset_package_mapping WHERE pack_name=?", (pack,))
            db.execute("INSERT INTO member_model VALUES(?,?,?,?,?,?)", (asset, pack, 0, len(raw), 11, 22))
            db.execute("INSERT INTO member_model_dependency VALUES(?,?)", (body, asset))
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?)", (pack, len(raw)))
            descriptors[asset] = {"asset_path": asset, "pack_name": pack, "head": 0, "size": len(raw),
                                  "key1": 11, "key2": 22, "pack_size": len(raw)}
            if local:
                (root / "static").mkdir(exist_ok=True)
                (root / "static" / pack).write_bytes(raw)
    return descriptors
