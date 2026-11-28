"""Readable costume names for people; identities stay codes.

Cache files keep names such as ``ch0004_suit100041001_primary.unity`` because
receipts, member inference and transplant cache reuse depend on them. People
see the game's own names instead: the member's three-digit number (Umi 004,
Chika 101), the member and the costume from the game's dictionaries, in each
interface language, e.g. ``004 소노다 우미 · 오토노키자카 고교 교복(동복)``. An
added costume shows the name its Mod was installed with, without a second
number or member when that name already starts with them.

A label never establishes identity. It is read from the same server-written
receipts (``.selection``/``.provenance``, derived edit/transplant receipts)
that already bind a file's exact bytes, or from a Mod ZIP's own manifest
names. A file nothing describes keeps its file name.
"""
from collections import OrderedDict
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading
import zipfile

LANGUAGES = ("en", "ko", "ja")
MAX_PATHS = 16
MAX_FILE_BYTES = 96 * 1024 * 1024
_KEY = re.compile(r"k\.[A-Za-z0-9_.-]{1,120}\Z")
# The installer stores "suit:<id>" when a Mod ZIP had no English name.
_PLACEHOLDER = re.compile(r"suit:[0-9]{1,12}\Z")
_REGION_LANGUAGE = {"gl": "en", "jp": "ja"}
_DIGESTS = OrderedDict()
_DIGEST_LOCK = threading.Lock()


def _tr(text, language):
    from webtools import i18n
    return i18n.tr(text, language)


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _clean(message, key=None):
    """A readable dictionary message, never a raw key or installer placeholder."""
    if not isinstance(message, str):
        return None
    message = " ".join(message.split())
    if (not message or len(message) > 240 or message == key or _KEY.fullmatch(message)
            or _PLACEHOLDER.fullmatch(message)):
        return None
    return message


class _Names:
    """Bounded read-only lookups across the GL/JP masterdata and dictionaries."""

    def __init__(self, root):
        self.root = Path(root)
        self.connections = {}

    def close(self):
        for connection in self.connections.values():
            if connection is not None:
                connection.close()
        self.connections.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _database(self, region, name):
        key = (region, name)
        if key not in self.connections:
            path = self.root / "assets/db" / region / name
            try:
                self.connections[key] = _readonly(path) if path.is_file() else None
            except sqlite3.Error:
                self.connections[key] = None
        return self.connections[key]

    def key(self, region, table, row_id):
        database = self._database(region, "masterdata.db")
        if database is None:
            return None
        try:
            row = database.execute(f"SELECT name FROM {table} WHERE id=?", (row_id,)).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row and isinstance(row[0], str) and row[0] else None

    def message(self, region, language, key):
        database = self._database(region, f"dictionary_{language}_k.db")
        if database is None or not isinstance(key, str):
            return None
        clean = key[2:] if key.startswith("k.") else key
        try:
            row = database.execute("SELECT message FROM m_dictionary WHERE id=?", (clean,)).fetchone()
        except sqlite3.Error:
            return None
        return _clean(row[0] if row else None, key)

    def localized(self, region, table, row_id, language):
        """The UI language first, also from the other region's dictionary when
        that region stores the same name key for the same row, then the
        region's own language and any other language. None when none exist."""
        regions = [region] + [other for other in ("gl", "jp") if other != region]
        keys = {candidate: self.key(candidate, table, row_id) for candidate in regions}
        source = keys.get(region)
        if source is None:
            return None
        shared = [candidate for candidate in regions if keys.get(candidate) == source]
        order = [(candidate, language) for candidate in shared]
        order.append((region, _REGION_LANGUAGE.get(region, "en")))
        order += [(candidate, code) for candidate in shared for code in ("en", "ko", "ja", "zh")]
        for candidate, code in dict.fromkeys(order):
            found = self.message(candidate, code, source)
            if found:
                return found
        return None


def _fallback_member(owner):
    from .charinfo import NAMES
    return NAMES.get(owner) or (f"#{owner}" if type(owner) is int else None)


def member_number(owner):
    """The member's number as three ASCII digits (Umi 004, Chika 101, Rina
    209), so names sort by member; None for an unknown member."""
    return f"{owner:03d}" if type(owner) is int and 0 < owner < 1000 else None


def _starts_with_name(text, name):
    if not name or not text.startswith(name):
        return False
    rest = text[len(name):]
    return not rest or not (rest[0].isalnum() or rest[0] in "'\u2019")


def titled(owner, member, text, aliases=()):
    """``004 소노다 우미 · <text>``: the member's number, name and ``text``.

    A name that already starts with the member's number (a name this feature
    made) is kept as it is; one that starts with the member's name only gets
    the number. Without a known member the text stays as it is.
    """
    number = member_number(owner)
    if number is None or not member:
        return text
    if not text:
        return f"{number} {member}"
    if re.match(re.escape(number) + r"(?![0-9])", text):
        return text
    if any(_starts_with_name(text, alias) for alias in (member, *aliases)):
        return f"{number} {text}"
    return f"{number} {member} · {text}"


def _aliases(owner, member):
    from .charinfo import NAMES
    return tuple(dict.fromkeys([*(member or {}).values(), NAMES.get(owner) or ""]))


def member_names(root, owner, *, region="gl", names=None):
    """The member's own name from m_member and the dictionaries, per language."""
    if type(owner) is not int or not 0 < owner < 100000:
        return None
    own = names is None
    names = names or _Names(root)
    try:
        result = {}
        for language in LANGUAGES:
            found = None
            for candidate in dict.fromkeys([region, "gl", "jp"]):
                found = names.localized(candidate, "m_member", owner, language)
                if found:
                    break
            result[language] = found or _fallback_member(owner)
        return result if all(result.values()) else None
    finally:
        if own:
            names.close()


def costume_names(root, region, suit_id, *, names=None):
    """The costume's dictionary name per language, or None for every
    language when the game has no readable name for it."""
    if region not in ("gl", "jp") or type(suit_id) is not int:
        return None
    own = names is None
    names = names or _Names(root)
    try:
        result = {language: names.localized(region, "m_suit", suit_id, language) for language in LANGUAGES}
        return result if all(result.values()) else None
    finally:
        if own:
            names.close()


def _join(*parts):
    return " · ".join(part for part in parts if part)


def record_label(root, record, *, names=None):
    """Display parts for a verified game selection record, per language."""
    if not isinstance(record, dict):
        return None
    region, suit_id, variant = record.get("region"), record.get("suit_id"), record.get("variant")
    owner = record.get("owner")
    if region not in ("gl", "jp") or type(suit_id) is not int or variant not in ("primary", "unmasked"):
        return None
    own = names is None
    names = names or _Names(root)
    try:
        if type(owner) is not int:
            database = names._database(region, "masterdata.db")
            try:
                row = database.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit_id,)).fetchone() if database else None
            except sqlite3.Error:
                row = None
            owner = row[0] if row and type(row[0]) is int else None
        member = member_names(root, owner, region=region, names=names) if owner is not None else None
        costume = costume_names(root, region, suit_id, names=names)
    finally:
        if own:
            names.close()
    named = costume is not None
    costume = costume or {language: _tr("Costume #{id}", language).replace("{id}", str(suit_id))
                          for language in LANGUAGES}
    # The default model is the costume itself. Only the other view is named.
    view = {language: _tr("Without mask", language) for language in LANGUAGES} if variant == "unmasked" else None
    base = _titled_names(owner, member, costume)
    label = {language: _join(base[language], view and view[language]) for language in LANGUAGES}
    return {"label": label, "member": member, "costume": costume, "view": view, "named": named,
            # A Mod ZIP of a Rina costume always carries both views, so the
            # automatic Mod name never names one of them.
            "nameBase": base, "region": region, "suitId": suit_id,
            "variant": variant, "owner": owner if member else None}


def _titled_names(owner, member, text):
    aliases = _aliases(owner, member)
    return {language: titled(owner, member and member[language], text[language], aliases) for language in LANGUAGES}


def titled_names(root, owner, text, *, names=None):
    """``text`` (one name or one per language) after the member's number and
    name in each language; ``text`` as it is for an unknown member."""
    if isinstance(text, str):
        text = {language: text for language in LANGUAGES}
    member = member_names(root, owner, names=names) if type(owner) is int else None
    return _titled_names(owner, member, text)


def member_choices(root, owners, *, region="gl", names=None):
    """Numbered member names per language, e.g. ``004 소노다 우미``."""
    own = names is None
    names = names or _Names(root)
    try:
        rows = []
        for owner in owners:
            member = member_names(root, owner, region=region, names=names)
            labels = ({language: titled(owner, member[language], "") for language in LANGUAGES} if member
                      else {language: str(owner) for language in LANGUAGES})
            rows.append({"value": str(owner), "labels": labels})
        return rows
    finally:
        if own:
            names.close()


def text_label(root, text, owner=None, *, names=None):
    """Display parts for a name a Mod ZIP or scene package declares."""
    if isinstance(text, str):
        text = {language: text for language in LANGUAGES}
    if not isinstance(text, dict):
        return None
    values = {language: _clean(text.get(language)) or _clean(text.get("en")) for language in LANGUAGES}
    if not all(values.values()):
        return None
    member = member_names(root, owner, names=names) if type(owner) is int else None
    base = _titled_names(owner, member, values)
    return {"label": base, "member": member, "costume": values, "view": None, "named": True,
            "nameBase": dict(base), "owner": owner if member else None}


_FACE_FILE = re.compile(r"ch([0-9]{4})_[0-9a-f]{24}\.unity\Z")


def face_label(root=None, file_name="", *, names=None):
    """``004 소노다 우미 · 얼굴(자동)`` for the server's automatic face file
    (``ch0004_<24 hex>.unity``); ``얼굴(자동)`` when its member is unknown."""
    face = {language: _tr("Face (automatic)", language) for language in LANGUAGES}
    match = _FACE_FILE.fullmatch(file_name or "")
    if root is None or match is None:
        return face
    from .member_identity import member_from_native
    return titled_names(root, member_from_native(int(match.group(1))), face, names=names)


# ---------------------------------------------------------------- receipts
def _digest(path):
    """SHA-256 of a bounded regular file, remembered per exact file state."""
    stat = path.stat()
    if not 0 < stat.st_size <= MAX_FILE_BYTES:
        raise ValueError("The model file is empty or too large to label.")
    key = (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    with _DIGEST_LOCK:
        if key in _DIGESTS:
            _DIGESTS.move_to_end(key)
            return _DIGESTS[key]
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    after = path.stat()
    if (after.st_size, after.st_mtime_ns, after.st_ino) != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
        raise ValueError("The model file changed while it was labelled.")
    with _DIGEST_LOCK:
        _DIGESTS[key] = digest
        while len(_DIGESTS) > 256:
            _DIGESTS.popitem(last=False)
    return digest


def _identity(record):
    return (record.get("region"), record.get("suit_id"), record.get("variant"))


def _bound_record(path, digest, cache_root):
    """The one game record whose receipt binds these exact bytes, else None."""
    from . import viewer_mod_flow, viewer_mod_sources
    context = {"containers": [{"path": str(path), "sha256": digest}]}
    records = [row["record"] for row in viewer_mod_flow.cached_receipts(context, cache_root)]
    with viewer_mod_sources._LOCK:
        registered = viewer_mod_sources._REGISTRY.get(str(path))
        if registered and registered.get("sha256") == digest:
            records.append(registered.get("record"))
    records = [record for record in records if isinstance(record, dict)]
    identities = {_identity(record) for record in records}
    return records[0] if len(identities) == 1 else None


def source_record(path, digest, cache_root):
    """Follow verified receipts to the original game record of these bytes.

    An edited preview copy, a mesh save and a transplant result each carry a
    derived receipt naming the bytes they came from; the first parent is the
    wearer (a donor is never followed). Returns ``(record, derived)``.
    """
    from . import viewer_physics_runtime
    proof = {"path": str(path), "containerSha256": digest, "member": None, "sha256": digest}
    for depth in range(viewer_physics_runtime._MAX_DERIVED_DEPTH):
        record = _bound_record(proof["path"], proof["sha256"], cache_root)
        if record is not None:
            return record, depth > 0
        try:
            row = viewer_physics_runtime._read_receipt(cache_root, proof)
        except (OSError, ValueError, TypeError, KeyError):
            return None, False
        parents = row.get("parents") if row else None
        if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
            break
        parent = parents[0]
        if (not isinstance(parent, dict) or parent.get("member") is not None
                or not isinstance(parent.get("path"), str) or not isinstance(parent.get("sha256"), str)
                or parent.get("containerSha256") != parent.get("sha256")):
            break
        proof = {"path": str(Path(parent["path"]).resolve()), "containerSha256": parent["sha256"],
                 "member": None, "sha256": parent["sha256"]}
    return None, False


def _zip_text(archive, info, limit):
    if info.file_size > limit:
        return None
    with archive.open(info) as stream:
        raw = stream.read(limit + 1)
    return raw if len(raw) <= limit else None


def archive_names(path):
    """Declared names of a Mod ZIP or canonical scene package, or None."""
    from . import viewer_scene_format
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= 4096:
                return None
            by_name = {}
            for info in infos:
                if not info.is_dir():
                    by_name.setdefault(PurePosixPath(info.filename.replace("\\", "/")).name.casefold(), []).append(info)
            scene = by_name.get(viewer_scene_format.MANIFEST.casefold(), [])
            if len(scene) == 1:
                raw = _zip_text(archive, scene[0], 256 * 1024)
                manifest = json.loads(raw.decode("utf-8")) if raw else None
                if not isinstance(manifest, dict):
                    return None
                owner = manifest.get("target_member_id", manifest.get("character_id"))
                return {"names": manifest.get("display_name"), "owner": owner if type(owner) is int else None,
                        "scene": True}
            manifests = by_name.get("modinstall.txt", [])
            if len(manifests) != 1:
                return None
            raw = _zip_text(archive, manifests[0], 64 * 1024)
            if raw is None:
                return None
            values = {}
            for node in ast.parse(raw.decode("utf-8-sig")).body:
                if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id.startswith(("costume_name_", "chara_id"))):
                    try:
                        values[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError, RecursionError):
                        pass
    except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError, zipfile.BadZipFile,
            zipfile.LargeZipFile, NotImplementedError, RuntimeError):
        return None
    from .member_identity import member_from_native
    owner = values.get("chara_id_append") if values.get("chara_id_append") is not None else member_from_native(values.get("chara_id"))
    names = {language: values.get("costume_name_" + language) for language in LANGUAGES}
    return {"names": names, "owner": owner if type(owner) is int else None, "scene": False}


def describe(path, *, repo_root, cache_root, names=None):
    """Label parts for one model file the caller already authorized."""
    path = Path(path)
    result = {"file": path.name}
    try:
        if path.is_symlink() or not path.is_file():
            return result
        path = path.resolve()
        digest = _digest(path)
    except (OSError, ValueError):
        return result
    own = names is None
    names = names or _Names(repo_root)
    try:
        record, derived = source_record(path, digest, cache_root)
        if record is not None:
            parts = record_label(repo_root, record, names=names)
            if parts:
                return {**result, **parts, "source": "derived" if derived else "game"}
        if zipfile.is_zipfile(path):
            declared = archive_names(path)
            if declared:
                parts = text_label(repo_root, declared["names"], declared["owner"], names=names)
                if parts:
                    return {**result, **parts, "source": "scene" if declared["scene"] else "manifest"}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        pass
    finally:
        if own:
            names.close()
    return result


def describe_paths(paths, *, repo_root, cache_root):
    with _Names(repo_root) as names:
        return [describe(path, repo_root=repo_root, cache_root=cache_root, names=names) for path in paths]


def safe_parts(parts):
    """The JSON-safe subset sent to the page."""
    if not isinstance(parts, dict):
        return None
    return {key: parts[key] for key in ("label", "member", "costume", "view", "named", "nameBase",
                                        "region", "suitId", "variant", "owner", "source", "file")
            if key in parts}
