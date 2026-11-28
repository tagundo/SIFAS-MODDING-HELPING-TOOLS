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


def untitled(owner, member, text, aliases=()):
    """``text`` without the ``004 소노다 우미 · `` that :func:`titled` puts first.

    The inverse of :func:`titled` for its own forms: ``004 <member> · X`` is
    ``X``, ``004 <member>`` is empty and ``004 <member>…`` (a name that
    started with the member) loses only the number. Anything else, also a
    name that starts with the number but not with a space and the member,
    is returned as it is.
    """
    number = member_number(owner)
    if number is None or not isinstance(text, str) or not text.startswith(number + " "):
        return text
    rest = text[len(number) + 1:]
    known = sorted({name for name in (member, *aliases) if name}, key=len, reverse=True)
    for name in known:
        if rest == name:
            return ""
        if rest.startswith(name + " · "):
            return rest[len(name) + 3:]
    if any(_starts_with_name(rest, name) for name in known):
        return rest
    return text


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


# Transplant receipts name what was done; a costume transplant puts the
# donor's costume on the wearer (costume_transplant.py), the others keep the
# wearer's costume with a donor part.
TRANSPLANTS = {"costume": "Costume transplant", "part": "Costume part transplant", "lower": "Lower body replacement"}


def _compose(owner, member, costume, view=None, operations=()):
    """Label, automatic Mod name base and the base without its member.

    ``costume`` is the text per language (None names the member only).
    """
    aliases = _aliases(owner, member)
    done = {language: [_tr(TRANSPLANTS[operation], language) for operation in operations] for language in LANGUAGES}
    base, text = {}, {}
    for language in LANGUAGES:
        name = member and member[language]
        first = titled(owner, name, costume[language] if costume else "", aliases)
        base[language] = _join(first, *done[language])
        text[language] = untitled(owner, name, base[language], aliases)
    label = {language: _join(titled(owner, member and member[language], costume[language] if costume else "", aliases),
                             view and view[language], *done[language]) for language in LANGUAGES}
    # A Mod ZIP of a Rina costume always carries both views, so the
    # automatic Mod name never names one of them.
    return {"label": label, "nameBase": base, "nameText": text}


def _record_owner(names, region, suit_id, owner):
    if type(owner) is int:
        return owner
    database = names._database(region, "masterdata.db")
    try:
        row = database.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit_id,)).fetchone() if database else None
    except sqlite3.Error:
        row = None
    return row[0] if row and type(row[0]) is int else None


def record_label(root, record, *, names=None, operations=(), costume=None):
    """Display parts for a verified game selection record, per language.

    ``operations`` are transplants done to these bytes (from their derived
    receipts); ``costume`` replaces the record's costume for a costume
    transplant: {"text": per language or None, "region", "suitId"}.
    ``counterpart`` always stays the record itself: the bytes' container.
    """
    if not isinstance(record, dict):
        return None
    region, suit_id, variant = record.get("region"), record.get("suit_id"), record.get("variant")
    if region not in ("gl", "jp") or type(suit_id) is not int or variant not in ("primary", "unmasked"):
        return None
    own = names is None
    names = names or _Names(root)
    try:
        owner = _record_owner(names, region, suit_id, record.get("owner"))
        member = member_names(root, owner, region=region, names=names) if owner is not None else None
        named_costume = costume_names(root, region, suit_id, names=names)
    finally:
        if own:
            names.close()
    named = named_costume is not None
    shown = named_costume or {language: _tr("Costume #{id}", language).replace("{id}", str(suit_id))
                              for language in LANGUAGES}
    shown_region, shown_suit = region, suit_id
    if costume is not None:
        # The donor's costume, or none when the donor cannot be named; never
        # the costume the transplant replaced.
        shown, named = costume.get("text"), costume.get("text") is not None
        shown_region, shown_suit = costume.get("region"), costume.get("suitId")
        if member is None and shown is None:
            return None
    # The default model is the costume itself. Only the other view is named.
    view = {language: _tr("Without mask", language) for language in LANGUAGES} if variant == "unmasked" else None
    parts = {**_compose(owner, member, shown, view, operations), "member": member, "costume": shown, "view": view,
             "named": named, "variant": variant, "owner": owner if member else None,
             "counterpart": {"region": region, "suitId": suit_id, "variant": variant, "owner": owner}}
    if shown_region in ("gl", "jp") and type(shown_suit) is int:
        parts.update(region=shown_region, suitId=shown_suit)
    if operations:
        parts["operations"] = list(operations)
    return parts


def _titled_names(owner, member, text):
    aliases = _aliases(owner, member)
    return {language: titled(owner, member and member[language], text[language], aliases) for language in LANGUAGES}


def _untitled_names(owner, member, text):
    aliases = _aliases(owner, member)
    return {language: untitled(owner, member and member[language], text[language], aliases) for language in LANGUAGES}


def titled_names(root, owner, text, *, names=None):
    """``text`` (one name or one per language) after the member's number and
    name in each language; ``text`` as it is for an unknown member."""
    if isinstance(text, str):
        text = {language: text for language in LANGUAGES}
    member = member_names(root, owner, names=names) if type(owner) is int else None
    return _titled_names(owner, member, text)


def for_member(root, owner, text, *, names=None):
    """The automatic Mod name base for another chosen member.

    ``101 타카미 치카 · <text>``: the member's choice label (see
    :func:`member_choices`), then ``text`` (a base without its own member).
    The page builds the same from the choice labels it was sent, so a base
    never keeps the number of a member the costume is no longer for.
    """
    member = member_names(root, owner, names=names) if type(owner) is int else None
    if member is None or member_number(owner) is None or not isinstance(text, dict):
        return None
    return {language: _join(titled(owner, member[language], ""), text.get(language) or "") for language in LANGUAGES}


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
            "nameBase": dict(base), "nameText": _untitled_names(owner, member, base), "owner": owner if member else None}


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


def pair_operation(row):
    """The transplant that made a two-parent derived receipt row, or None.

    A transplant row names it; an edit of a transplant result reuses that
    result's parents, and newer edit rows keep the operation in
    ``pairOperation``. Older edit rows: the last transplant they list.
    """
    parents = row.get("parents") if isinstance(row, dict) else None
    if not isinstance(parents, list) or len(parents) != 2:
        return None
    operation = row.get("operation")
    if operation in TRANSPLANTS:
        return operation
    if operation != "edit":
        return None
    if row.get("pairOperation") in TRANSPLANTS:
        return row["pairOperation"]
    listed = row.get("operations")
    done = [value for value in listed if value in TRANSPLANTS] if isinstance(listed, list) else []
    return done[-1] if done else None


def _row_operations(row):
    listed = row.get("operations", [row.get("operation")])
    return [value for value in listed if value in TRANSPLANTS] if isinstance(listed, list) else []


def trace(path, digest, cache_root):
    """Follow verified receipts from these bytes to the game record they are.

    An edited preview copy, a mesh save and a transplant result each carry a
    derived receipt naming the bytes they came from. The first parent is the
    wearer and is followed to the original game record: the bytes'
    container, which platform conversion matches too. A donor is never
    followed for that record; the newest costume transplant on the way only
    notes its donor (``donor``), whose costume the result wears.

    Returns ``{"record", "derived", "operations", "donor"}`` or None;
    ``operations`` are the transplants, oldest first; ``donor`` is None or
    ``{"proof": <donor proof or None>}``.
    """
    from . import viewer_physics_runtime
    proof = {"path": str(path), "containerSha256": digest, "member": None, "sha256": digest}
    done, donor = [], None
    for depth in range(viewer_physics_runtime._MAX_DERIVED_DEPTH):
        record = _bound_record(proof["path"], proof["sha256"], cache_root)
        if record is not None:
            operations = list(dict.fromkeys(value for chunk in reversed(done) for value in chunk))
            return {"record": record, "derived": depth > 0, "operations": operations, "donor": donor}
        try:
            row = viewer_physics_runtime._read_receipt(cache_root, proof)
        except (OSError, ValueError, TypeError, KeyError):
            return None
        parents = row.get("parents") if row else None
        if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
            return None
        parent = parents[0]
        # A wearer inside a ZIP is not one file this server imported.
        if (not isinstance(parent, dict) or parent.get("member") is not None
                or not isinstance(parent.get("path"), str) or not isinstance(parent.get("sha256"), str)
                or parent.get("containerSha256") != parent.get("sha256")):
            return None
        done.append(_row_operations(row))
        if donor is None and pair_operation(row) == "costume":
            donor = {"proof": parents[1] if isinstance(parents[1], dict) else None}
        proof = {"path": str(Path(parent["path"]).resolve()), "containerSha256": parent["sha256"],
                 "member": None, "sha256": parent["sha256"]}
    return None


def _donor_costume(root, proof, cache_root, names, hops):
    """What a costume transplant's donor wears, without the donor's member.

    The donor file must still be the exact bytes the receipt names. A game
    import (or its edited copy) gives its game costume, a Mod ZIP the names
    it declares. None when nothing names it.
    """
    if hops <= 0 or not isinstance(proof, dict) or not isinstance(proof.get("path"), str):
        return None
    path = Path(proof["path"])
    if path.is_symlink() or not path.is_file():
        return None
    path = path.resolve()
    digest = _digest(path)
    if digest != proof.get("containerSha256"):
        return None
    if proof.get("member") is None:
        if proof.get("sha256") != digest:
            return None
        parts = _traced_parts(root, path, digest, cache_root, names, hops - 1)
        if not parts:
            return None
        text = _compose(parts["owner"], parts["member"], parts["costume"])["nameText"] if parts["costume"] else None
        return {"text": text, "region": parts.get("region"), "suitId": parts.get("suitId")}
    declared = archive_names(path) if zipfile.is_zipfile(path) else None
    parts = text_label(root, declared["names"], declared["owner"], names=names) if declared else None
    return {"text": parts["nameText"] if parts and all(parts["nameText"].values()) else None}


def _traced_parts(root, path, digest, cache_root, names, hops=4):
    traced = trace(path, digest, cache_root)
    if traced is None:
        return None
    costume = None
    if traced["donor"] is not None:
        costume = _donor_costume(root, traced["donor"]["proof"], cache_root, names, hops) or {"text": None}
    parts = record_label(root, traced["record"], names=names, operations=traced["operations"], costume=costume)
    if parts:
        parts["source"] = "derived" if traced["derived"] else "game"
    return parts


def bytes_label(path, digest, *, repo_root, cache_root, names=None):
    """Label parts for exact bytes the server's receipts describe, or None."""
    own = names is None
    names = names or _Names(repo_root)
    try:
        return _traced_parts(repo_root, Path(path), digest, cache_root, names)
    finally:
        if own:
            names.close()


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
        parts = _traced_parts(repo_root, path, digest, cache_root, names)
        if parts:
            return {**result, **parts}
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
    return {key: parts[key] for key in ("label", "member", "costume", "view", "named", "nameBase", "nameText",
                                        "region", "suitId", "variant", "owner", "operations", "counterpart",
                                        "source", "file")
            if key in parts}
