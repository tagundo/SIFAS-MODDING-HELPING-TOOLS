"""Restart-safe receipts for exact, server-staged MV actor inputs."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from .game_models import _sha


_PREVIEW_VERSION = 2  # Bump when actor motion selection or GLB conversion changes.
_MAX_RECEIPTS = 24
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_DATABASE_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_BYTES = 96 * 1024 * 1024
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_CACHE_ERRORS = (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError)


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sources(paths):
    # Include binding order and logical file names, excluding randomly generated
    # staging directory names. The caller supplies private snapshots of inputs.
    return [(path.name, _sha(path)) for path in paths]


def _decoder(name):
    value = os.environ.get(name)
    if not value:
        return None
    try:
        path = Path(value).resolve(strict=True)
        info = path.stat()
        if stat.S_ISREG(info.st_mode):
            return str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def _media_fingerprint(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_MEDIA_BYTES:
            raise ValueError("The cached actor media exceeds the preview limit.")
        digest = sha256()
        remaining = before.st_size
        while remaining:
            block = stream.read(min(remaining, 256 * 1024))
            if not block:
                raise ValueError("The cached actor media is incomplete.")
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("The cached actor media changed during import.")
    return digest.hexdigest(), before.st_size


def _playable(rig, motion):
    if not isinstance(rig, dict) or rig.get("available") is not True or not isinstance(motion, dict):
        return False
    clips, segments = rig.get("clips"), motion.get("bodySegments")
    if not isinstance(clips, list) or not isinstance(segments, list) or not segments:
        return False
    # A failed conversion can leave a usable rest pose or partial rig. Retry
    # such non-complete exports on the next open instead of persisting fallback.
    if any(warning.get("code") == "animation_unavailable" for warning in rig.get("animationWarnings", [])):
        return False
    complete = set()
    counts = Counter()
    for clip in clips:
        if isinstance(clip, dict):
            identity = clip.get("sourceHash"), clip.get("sourceName")
            counts[identity] += 1
            if clip.get("bindingComplete") is True:
                complete.add(identity)
    for segment in segments:
        identity = segment["sourceHash"], segment["sourceName"]
        if identity not in complete or counts[identity] != 1:
            return False
    return True


class ActorCache:
    def __init__(self, directory, context, media):
        self.directory = directory
        self.path = directory / "receipts.sqlite3"
        self.context = context
        self.media = media
        recipe = {
            "version": _PREVIEW_VERSION,
            "runtime": sys.implementation.cache_tag,
            "dependencies": [getattr(sys.modules.get(name), "__version__", None) for name in ("UnityPy", "numpy", "PIL")],
            "decoders": [_decoder(name) for name in ("ASTCENC_BIN", "ELICHIKA_TEXTURE65_BIN")],
        }
        self.recipe = sha256(_encode(recipe)).hexdigest()
        with closing(self._database()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS actor_receipts (
                id TEXT PRIMARY KEY, receipt BLOB NOT NULL, checksum TEXT NOT NULL, used INTEGER NOT NULL
            )""")

    def _database(self):
        if self.path.is_symlink() or self.path.resolve() != self.path:
            raise ValueError("The actor cache must use its private folder.")
        if self.path.exists() and (not self.path.is_file() or self.path.stat().st_size > _MAX_DATABASE_BYTES):
            raise ValueError("The actor cache database exceeds its size limit.")
        db = sqlite3.connect(self.path, timeout=.1)
        try:
            size, = db.execute("PRAGMA page_size").fetchone()
            db.execute(f"PRAGMA max_page_count={_MAX_DATABASE_BYTES // size}")
        except BaseException:
            db.close()
            raise
        return db

    def inputs(self, native, dependencies):
        try:
            return sha256(native).hexdigest(), _sources(dependencies)
        except _CACHE_ERRORS:
            return None

    def key(self, shared, position, member, model, companions, facial):
        if shared is None or not companions:
            return None
        try:
            recipe = (self.recipe, self.context, shared, position, member, _sources([model, *companions]), _sources(facial))
            return sha256(_encode(recipe)).hexdigest()
        except _CACHE_ERRORS:
            return None

    def get(self, key):
        if key is None:
            return None
        try:
            with closing(self._database()) as db:
                row = db.execute("SELECT receipt, checksum FROM actor_receipts WHERE id = ? AND length(receipt) <= ?",
                                 (key, _MAX_RECEIPT_BYTES)).fetchone()
            if row is None:
                return None
            data, checksum = row
            if sha256(data).hexdigest() != checksum:
                return None
            receipt = json.loads(data)
            digest = receipt["sha256"]
            if (receipt["key"] != key or receipt["recipe"] != self.recipe
                    or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
                    or not _playable(receipt["rig"], receipt["motion"])):
                return None
            name = digest[:32] + ".glb"
            path, _ = self.media(name)
            if _media_fingerprint(path) != (digest, receipt["size"]):
                return None
            try:
                with closing(self._database()) as db, db:
                    db.execute("""UPDATE actor_receipts
                        SET used = (SELECT COALESCE(MAX(used), 0) + 1 FROM actor_receipts)
                        WHERE id = ? AND checksum = ?""", (key, checksum))
            except _CACHE_ERRORS:
                pass
            return name, receipt["rig"], receipt["motion"]
        except _CACHE_ERRORS:
            return None

    def put(self, key, name, rig, motion):
        if key is None:
            return
        try:
            if not _playable(rig, motion):
                return
            path, _ = self.media(name)
            digest, size = _media_fingerprint(path)
            if name != digest[:32] + ".glb":
                return
            data = _encode({"key": key, "recipe": self.recipe, "sha256": digest, "size": size, "rig": rig, "motion": motion})
            if len(data) > _MAX_RECEIPT_BYTES:
                return
            with closing(self._database()) as db, db:
                db.execute("""INSERT INTO actor_receipts (id, receipt, checksum, used)
                    VALUES (?, ?, ?, (SELECT COALESCE(MAX(used), 0) + 1 FROM actor_receipts))
                    ON CONFLICT(id) DO UPDATE SET receipt = excluded.receipt,
                        checksum = excluded.checksum, used = excluded.used""", (key, data, sha256(data).hexdigest()))
                total = 0
                discard = []
                for index, (identity, length) in enumerate(db.execute(
                        "SELECT id, length(receipt) FROM actor_receipts ORDER BY used DESC")):
                    total += length
                    if index >= _MAX_RECEIPTS or total > _MAX_RECEIPT_BYTES:
                        discard.append((identity,))
                db.executemany("DELETE FROM actor_receipts WHERE id = ?", discard)
        except _CACHE_ERRORS:
            pass


def open_cache(context, media):
    value = os.environ.get("ELICHIKA_MV_PRIVATE_CACHE")
    effective_uid = getattr(os, "geteuid", None)
    if not value or effective_uid is None:
        return None
    try:
        configured = Path(value)
        if not configured.is_absolute() or configured.resolve() != configured:
            return None
        directory = configured / "actors"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if (directory.resolve() != directory or not stat.S_ISDIR(info.st_mode) or info.st_uid != effective_uid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            return None
        return ActorCache(directory, context, media)
    except _CACHE_ERRORS:
        return None
