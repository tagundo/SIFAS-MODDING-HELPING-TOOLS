"""Restart-safe receipts for MV import steps that are pure functions of their inputs.

The live timeline parse, its external dance clip names, the stage, stage
effect and prop GLB conversions and the decoded soundtrack depend only on the
bytes of their game sections, this code and the native decoders. Each receipt
is keyed by sha256 over all of those:

- the exact input bytes (sha256 of every section) and the call's options;
- a recipe: the bytes of every source and resource file of this tool
  (webtools/core, webtools/*.py, live_timeline, the top-level modules), the
  Elichika modules the import reads with, the interpreter and library
  versions, the machine, and the identity (path, inode, size, mtime, ctime)
  of every decoder executable or library a step may run.

Any change to any of them is a different key, so a receipt can never be
served for other inputs or other code. A receipt is a file holding its own
key, recipe and payload checksum; a hit is re-verified (checksum, key, recipe,
and the sha256 of every media file it names) and anything that does not match
is a miss. Payloads are stored as JSON with tuples tagged, and admitted only
when decoding gives back an equal value of the same types (only str/int/
float/bool/None, lists, tuples and string-keyed dicts; no non-finite floats),
so a hit returns exactly what the step returned. The store is bounded and
evicts the least recently used receipts.
"""
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import sys
import tempfile
import zlib

_MAX_ENTRIES = 96
_MAX_BYTES = 96 * 1024 * 1024
# Decoded textures (PNG) live in their own folder: a costume's are reused by
# every MV it appears in, while its whole GLB is specific to one MV's dance.
_MAX_TEXTURES = 1024
_MAX_TEXTURE_BYTES = 192 * 1024 * 1024
_MAX_RECEIPT_BYTES = 32 * 1024 * 1024
_KEY = re.compile(r"[a-f0-9]{64}\Z")
_KINDS = {"timeline", "clips", "preview", "audio", "texture"}
_MEDIA_URL = "/api/mv-studio/media/"
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}\.(?:glb|wav|ogg|mp3|m4a|flac)\Z")
_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError, zlib.error,
           UnicodeDecodeError, RecursionError)
# Library modules whose code shapes the imported bytes.
_LIBRARIES = ("UnityPy", "numpy", "PIL", "lz4", "brotli", "astc_encoder", "texture2ddecoder", "etcpak")
# Elichika modules the import reads game sections and catalogs with.
_HOST_MODULES = ("llas_asset_extractor", "mv_studio_live")


def _file_identity(value):
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


def decoders():
    """Every native decoder an import may run, as file identities (checked on each import)."""
    hca = [os.environ.get("ELICHIKA_HCA_LIBRARY")]
    native = os.environ.get("ELICHIKA_NATIVE_DIR")
    names = ("libelichika_hca.dylib", "libelichika_hca.so", "elichika_hca.dll")
    if native:
        hca.extend(str(Path(native) / name) for name in names)
    hca.extend(str(Path(__file__).parent / "resources" / "cri_hca" / name) for name in names)
    return {
        "astcenc": _file_identity(os.environ.get("ASTCENC_BIN")),
        "texture65": _file_identity(os.environ.get("ELICHIKA_TEXTURE65_BIN")),
        "hca": [os.environ.get("ELICHIKA_HCA_LIBRARY"), native, [_file_identity(item) for item in hca]],
        "ffmpeg": _file_identity(shutil.which("ffmpeg")),
    }


def _tree_digest(digest, root, folder, suffixes=None):
    base = root / folder
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file() or (suffixes and path.suffix not in suffixes):
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256(path.read_bytes()).digest())


@lru_cache(maxsize=1)
def _source_recipe():
    """sha256 of the code that shapes an import, read once per process.

    Hashing the files on disk (not just a version number) means an edited
    checkout or an app update can never reuse receipts of other code.
    """
    root = Path(__file__).resolve().parents[2]
    digest = sha256()
    _tree_digest(digest, root, "webtools/core")
    for path in sorted((root / "webtools").glob("*.py")) + sorted(root.glob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256(path.read_bytes()).digest())
    _tree_digest(digest, root, "live_timeline", {".py", ".json"})
    for name in _HOST_MODULES:
        try:
            spec = importlib.util.find_spec(name)
            origin = spec.origin if spec else None
            digest.update(name.encode() + b"\0" + (sha256(Path(origin).read_bytes()).digest() if origin and os.path.isfile(origin) else b"-"))
        except (ImportError, ValueError, OSError):
            digest.update(name.encode() + b"\0?")
    versions = []
    for name in _LIBRARIES:
        # The installed package's file identity, whether or not it is imported yet.
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        versions.append([name, None if spec is None else _file_identity(spec.origin)])
    digest.update(json.dumps({"python": sys.version, "implementation": sys.implementation.cache_tag,
                              "machine": platform.machine(), "system": platform.system(), "libraries": versions},
                             sort_keys=True).encode())
    return digest.hexdigest()


def recipe():
    return sha256(json.dumps([_source_recipe(), decoders()], sort_keys=True).encode()).hexdigest()


_TUPLE = "\u0000tuple"


def _strict(value):
    """True when value is data that _dumps/_loads reproduce exactly, types included."""
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is float:
        return value == value and value not in (float("inf"), float("-inf"))
    if type(value) in (list, tuple):
        return all(_strict(item) for item in value)
    if type(value) is dict:
        return _TUPLE not in value and all(type(key) is str and _strict(item) for key, item in value.items())
    return False


def _tagged(value):
    if type(value) is tuple:
        return {_TUPLE: [_tagged(item) for item in value]}
    if type(value) is list:
        return [_tagged(item) for item in value]
    if type(value) is dict:
        return {key: _tagged(item) for key, item in value.items()}
    return value


def _untag(item):
    return tuple(item[_TUPLE]) if len(item) == 1 and _TUPLE in item else item


def _dumps(value):
    # Key order is kept: it is part of the project JSON the page receives.
    return json.dumps(_tagged(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _loads(text):
    return json.loads(text, object_hook=_untag)


def _same(a, b):
    """Equal and of the same types all the way down (== alone equates 1, 1.0 and True)."""
    if type(a) is not type(b):
        return False
    if type(a) in (list, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if type(a) is dict:
        return list(a) == list(b) and all(_same(a[key], b[key]) for key in a)
    if type(a) is float:
        return struct.pack("<d", a) == struct.pack("<d", b)
    return a == b


def _media_names(value, found=None):
    found = set() if found is None else found
    if isinstance(value, dict):
        for item in value.values():
            _media_names(item, found)
    elif isinstance(value, list):
        for item in value:
            _media_names(item, found)
    elif isinstance(value, str) and value.startswith(_MEDIA_URL) and _MEDIA_NAME.fullmatch(value[len(_MEDIA_URL):]):
        found.add(value[len(_MEDIA_URL):])
    return found


def digest(data):
    return sha256(data).hexdigest()


class ImportCache:
    def __init__(self, directory, media, max_entries=None, max_bytes=None):
        self.directory = directory
        self.media = media
        self.max_entries = _MAX_ENTRIES if max_entries is None else max_entries
        self.max_bytes = _MAX_BYTES if max_bytes is None else max_bytes
        self.recipe = recipe()

    def key(self, kind, *parts):
        if kind not in _KINDS:
            raise ValueError("Unknown MV import receipt kind.")
        return sha256(json.dumps([self.recipe, kind, parts], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _path(self, key):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("Invalid MV import receipt key.")
        return self.directory / (key + ".receipt")

    def _media_current(self, names):
        from .mv_studio_actor_cache import _media_fingerprint
        for name in names:
            path, _ = self.media(name)
            if _media_fingerprint(path)[0][:32] != name.split(".", 1)[0]:
                return False
        return True

    def _read(self, key):
        path = self._path(key)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_RECEIPT_BYTES:
            return None, None
        raw = path.read_bytes()
        head, _, body = raw.partition(b"\n")
        header = json.loads(head)
        if (header.get("key") != key or header.get("recipe") != self.recipe
                or header.get("sha256") != sha256(body).hexdigest()):
            return None, None
        return path, body

    def _write(self, key, body):
        data = json.dumps({"key": key, "recipe": self.recipe, "sha256": sha256(body).hexdigest()}).encode() + b"\n" + body
        if len(data) > _MAX_RECEIPT_BYTES:
            return False
        path = self._path(key)
        descriptor, name = tempfile.mkstemp(dir=self.directory, prefix=".receipt-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        self._evict()
        return True

    def get_bytes(self, key):
        """Bytes stored with put_bytes (checksummed like every receipt), or None."""
        try:
            path, body = self._read(key)
            if body is None:
                return None
            try:
                os.utime(path)
            except OSError:
                pass
            return body
        except _ERRORS:
            return None

    def put_bytes(self, key, data):
        try:
            return isinstance(data, bytes) and bool(data) and self._write(key, data)
        except _ERRORS:
            return False

    def get(self, key):
        """The payload stored under key, or None. Media it names must still hold their exact bytes."""
        try:
            path, body = self._read(key)
            if body is None:
                return None
            payload = _loads(zlib.decompress(body))
            if not self._media_current(_media_names(payload)):
                return None
            try:
                os.utime(path)  # most recently used
            except OSError:
                pass
            return payload
        except _ERRORS:
            return None

    def put(self, key, payload):
        """Store payload when it is exact JSON data whose media are in place. Never raises."""
        try:
            if not _strict(payload):
                return False
            text = _dumps(payload)
            if not _same(_loads(text), payload) or not self._media_current(_media_names(payload)):
                return False
            return self._write(key, zlib.compress(text.encode(), 6))
        except _ERRORS:
            return False

    def _evict(self):
        entries = []
        for path in self.directory.glob("*.receipt"):
            try:
                info = path.stat()
                entries.append((info.st_mtime_ns, info.st_size, path))
            except OSError:
                pass
        entries.sort(reverse=True)
        total = 0
        for index, (_, size, path) in enumerate(entries):
            total += size
            if index >= self.max_entries or total > self.max_bytes:
                path.unlink(missing_ok=True)


def open_cache(media, folder="imports", **limits):
    """A private receipt store, or None when ELICHIKA_MV_PRIVATE_CACHE is not a private folder."""
    value = os.environ.get("ELICHIKA_MV_PRIVATE_CACHE")
    effective_uid = getattr(os, "geteuid", None)
    if not value or effective_uid is None or folder not in ("imports", "textures"):
        return None
    try:
        configured = Path(value)
        if not configured.is_absolute() or configured.resolve() != configured:
            return None
        directory = configured / folder
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if (directory.resolve() != directory or not stat.S_ISDIR(info.st_mode) or info.st_uid != effective_uid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            return None
        return ImportCache(directory, media, **limits)
    except _ERRORS:
        return None


def open_texture_cache(media):
    return open_cache(media, "textures", max_entries=_MAX_TEXTURES, max_bytes=_MAX_TEXTURE_BYTES)
