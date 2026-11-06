"""Resolve source-bound Rina partners without guessing costume or file names.

This module only locates immutable sources. It never maps edits between rigs,
changes a counterpart, executes an installer manifest, or installs a package.
Filesystem authorization belongs to the HTTP caller.
"""
from collections import OrderedDict
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import zipfile

MAX_BYTES = 96 * 1024 * 1024
MAX_RECEIPTS = 256
MAX_RECORD_BYTES = 16 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_CHARACTER = re.compile(r"(?:^|[^a-z0-9])ch(\d{4})(?:_|$)", re.I)
_REGISTRY = OrderedDict()
_LOCK = threading.RLock()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("Choose a real counterpart file, not a symbolic link.")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
        raise ValueError("The counterpart must be a bounded Unity model file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise ValueError("A model changed while preparing its counterpart.")
        raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    current = path.lstat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if (len(raw) != before.st_size or len(raw) > MAX_BYTES or
            signature(before) != signature(after) or signature(before) != signature(current)):
        raise ValueError("A model changed while preparing its counterpart.")
    return raw


def _record(record):
    try:
        encoded = json.dumps(record, sort_keys=True, allow_nan=False)
        if not isinstance(record, dict) or len(encoded.encode()) > MAX_RECORD_BYTES:
            raise ValueError()
        result = json.loads(encoded)
        if (result["region"] not in ("gl", "jp") or
                isinstance(result["suit_id"], bool) or not isinstance(result["suit_id"], int) or
                not 0 < result["suit_id"] < 10 ** 12 or
                result["variant"] not in ("primary", "unmasked") or
                not isinstance(result["download"], bool)):
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("The game model source receipt is invalid.") from error


def _selection(record):
    return {"region": record["region"], "suit": f"suit:{record['suit_id']}",
            "variant": record["variant"], "download": record["download"]}


def _descriptor(record):
    return {key: value for key, value in record.items() if key != "download"}


def register_game_import(path, record, *, expected_sha256=None):
    """Register only a successfully imported/cache-verified game model.

    The returned JSON-safe receipt can be persisted in the known import cache.
    On restart the caller may supply such receipts to ``game_context``; the
    model SHA and current game catalog are checked again before any pairing.
    """
    record = _record(record)
    raw = _read(path)
    digest = _sha(raw)
    if expected_sha256 is not None and (
            not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256) or
            digest != expected_sha256):
        raise ValueError("The imported game model changed before its source receipt was registered.")
    path = str(Path(path).resolve())
    receipt = {"path": path, "sha256": digest, "record": record}
    with _LOCK:
        _REGISTRY[path] = receipt
        _REGISTRY.move_to_end(path)
        while len(_REGISTRY) > MAX_RECEIPTS:
            _REGISTRY.popitem(last=False)
    return copy.deepcopy(receipt)


def _snapshots(context):
    if not isinstance(context, dict):
        raise ValueError("Open the original model again before creating a Mod ZIP.")
    containers, sources = context.get("containers"), context.get("sources")
    if (not isinstance(containers, (list, tuple)) or not 1 <= len(containers) <= 8 or
            not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= 8):
        raise ValueError("The model source identity is incomplete. Open it again.")
    total, output = 0, []
    for container in containers:
        if not isinstance(container, dict):
            raise ValueError("The model source identity is invalid.")
        raw, digest, path = container.get("raw"), container.get("sha256"), container.get("path")
        if (not isinstance(raw, bytes) or not isinstance(path, str) or
                not isinstance(digest, str) or not _SHA.fullmatch(digest) or
                not 0 < len(raw) <= MAX_BYTES or _sha(raw) != digest):
            raise ValueError("An original model no longer matches its source identity.")
        total += len(raw)
        if total > MAX_BYTES:
            raise ValueError("The model originals exceed the Mod ZIP source limit.")
    for index, source in enumerate(sources):
        ci = source.get("container") if isinstance(source, dict) else None
        if isinstance(ci, bool) or not isinstance(ci, int) or not 0 <= ci < len(containers):
            raise ValueError("An editable model has no original container identity.")
        container, member = containers[ci], source.get("member")
        raw = container["raw"]
        if member is not None:
            if not isinstance(member, str):
                raise ValueError("An archive model has an invalid member identity.")
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    info = archive.getinfo(member)
                    if not 0 < info.file_size <= MAX_BYTES:
                        raise ValueError("An archive model exceeds the source limit.")
                    raw = archive.read(info)
            except (KeyError, zipfile.BadZipFile) as error:
                raise ValueError("An archive model is missing from its original ZIP.") from error
        if source.get("sha256") != _sha(raw):
            raise ValueError("An editable model changed after its preview was opened.")
        output.append({"container": ci, "source": index, "path": str(Path(container["path"]).resolve()),
                       "member": member, "sha256": _sha(raw), "raw": raw})
    return containers, output


def game_context(context, repo_root, *, receipts=()):
    """Return catalog bindings for selected immutable raw game-model sources.

    ``receipts`` must come from the caller's fixed, bounded import-cache scan,
    never from request-provided paths or a filename-derived suit identity.
    """
    _, sources = _snapshots(context)
    if not isinstance(receipts, (list, tuple)) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("Too many game model source receipts.")
    with _LOCK:
        candidates = list(copy.deepcopy(_REGISTRY).values()) + list(receipts)
    matches = {}
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("The game model source receipt is invalid.")
        path = str(Path(item["path"]).resolve())
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError("The game model source receipt has no valid hash.")
        record = _record(item.get("record"))
        key = (path, digest)
        if key in matches and _descriptor(matches[key]) != _descriptor(record):
            raise ValueError("Conflicting game model source receipts were found.")
        matches[key] = record
    from webtools.core import game_models
    result = []
    for source in sources:
        record = matches.get((source["path"], source["sha256"])) if source["member"] is None else None
        if record is None:
            continue
        current = game_models.validate_selection(repo_root, _selection(record))
        if _descriptor(current) != _descriptor(record):
            raise ValueError("The costume catalog changed. Import that costume again before pairing.")
        result.append({key: source[key] for key in ("container", "source", "path", "sha256")} | {"record": record})
    return result


def _model_facts(raw):
    from webtools.core.model_viewer import _preflight_bundle
    _preflight_bundle(raw)
    import UnityPy
    environment = UnityPy.load(raw)
    platforms, characters = set(), set()
    for asset in getattr(environment, "assets", ()):
        platform = getattr(asset, "target_platform", None)
        if platform is not None:
            platforms.add(int(platform))
    for obj in environment.objects:
        if obj.type.name == "Texture2D":
            name = obj.read_typetree().get("m_Name", "")
            characters.update(int(match.group(1)) for match in _CHARACTER.finditer(name))
    known = {13: "android", 9: "ios"}
    platform = known.get(next(iter(platforms))) if len(platforms) == 1 else None
    rina = bool(characters & {209, 9999})
    owner = 209 if characters and characters <= {209, 9999} else (
        next(iter(characters)) if len(characters) == 1 else None)
    return {"platform": platform, "rina": rina, "owner": owner}


def _complete_rina_zip(raw, selected_member):
    """A complete literal installer pair is already preserved by normal export."""
    from webtools.core.viewer_archive import _entry_path, _model_header, MAX_ENTRIES, MAX_MANIFEST_BYTES
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return False
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError("The costume ZIP contains too many files.")
        members, total = {}, 0
        for info in entries:
            relative = _entry_path(info)
            total += info.file_size
            key = str(relative).casefold()
            if total > MAX_BYTES or key in members:
                raise ValueError("The costume ZIP has duplicate or oversized sources.")
            members[key] = info
        pairs = []
        fields = {"chara_id", "costume_file", "rina_unmask_costume_file", "costume_file_ios", "rina_unmask_costume_file_ios"}
        for name, info in members.items():
            if PurePosixPath(name).name != "modinstall.txt":
                continue
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ValueError("The costume manifest is too large.")
            try:
                tree = ast.parse(archive.read(info).decode("utf-8-sig"))
                values = {}
                for node in tree.body:
                    if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                            isinstance(node.targets[0], ast.Name) and node.targets[0].id in fields):
                        key, value = node.targets[0].id, ast.literal_eval(node.value)
                        if key in values and values[key] != value:
                            raise ValueError("Conflicting costume manifest declarations.")
                        values[key] = value
            except (UnicodeError, SyntaxError, TypeError, RecursionError) as error:
                raise ValueError("The costume manifest cannot identify a safe paired source.") from error
            if values.get("chara_id") != 209:
                continue
            for main, other in (("costume_file", "rina_unmask_costume_file"),
                                ("costume_file_ios", "rina_unmask_costume_file_ios")):
                if not values.get(main):
                    if values.get(other):
                        raise ValueError("The Rina ZIP is missing its matching primary model.")
                    continue
                resolved = []
                for field in (main, other):
                    value = values.get(field)
                    if not isinstance(value, str) or not value:
                        raise ValueError("The Rina ZIP must include both board and unmasked models.")
                    relative = PurePosixPath(value.replace("\\", "/"))
                    if relative.is_absolute() or ".." in relative.parts or any(":" in p for p in relative.parts):
                        raise ValueError("The Rina ZIP contains an unsafe counterpart reference.")
                    key = str(PurePosixPath(name).parent / relative).casefold()
                    member = members.get(key)
                    if member is None or member.is_dir():
                        raise ValueError("The Rina ZIP is missing its declared counterpart model.")
                    data = archive.read(member)
                    if not _model_header(data[:48], len(data)):
                        raise ValueError("A declared Rina counterpart is not a Unity model.")
                    resolved.append((member.filename, _model_facts(data), _sha(data)))
                if resolved[0][0] == resolved[1][0] or resolved[0][2] == resolved[1][2]:
                    raise ValueError("The Rina ZIP reuses one file as both costume variants.")
                facts = [item[1] for item in resolved]
                if (not facts[0]["platform"] or facts[0]["platform"] != facts[1]["platform"] or
                        any(item["owner"] != 209 for item in facts)):
                    raise ValueError("The Rina counterparts must use the same character and platform.")
                if selected_member in (item[0] for item in resolved):
                    pairs.append(tuple(item[0] for item in resolved))
        if len(set(pairs)) > 1:
            raise ValueError("The costume ZIP declares ambiguous Rina counterparts.")
        return bool(pairs)


class _ImportJob:
    def __init__(self, parent):
        self.parent, self.outputs = parent, []

    def log(self, value):
        self.parent.log(value)

    def progress(self, done, total):
        self.parent.progress(done, total)

    def should_stop(self):
        return self.parent.should_stop()

    def add_output(self, path):
        self.outputs.append(str(Path(path).resolve()))


def resolve_pair(context, export_result, *, repo_root, output_root, job, selection=None, receipts=()):
    """Resolve an unchanged partner for one selected, edited Rina source.

    Explicit counterpart paths must already be jailed/authorized by the caller.
    Their role is user-declared; neither role nor costume is inferred from names.
    """
    containers, sources = _snapshots(context)
    bindings = {item["source"]: item for item in game_context(context, repo_root, receipts=receipts)}
    rina = []
    declared_families = {}
    for source in sources:
        container = containers[source["container"]]
        if source["member"] is not None:
            # A validated dual-platform manifest also establishes the family
            # for transplants retaining another character's texture names.
            from .viewer_mod_pair_edits import _zip_declarations
            index = source["container"]
            if index not in declared_families:
                declared_families[index] = _zip_declarations(container["raw"])
            if any(source["member"] in group for group in declared_families[index]):
                continue
            if _complete_rina_zip(container["raw"], source["member"]):
                continue
        facts = _model_facts(source["raw"])
        binding = bindings.get(source["source"])
        if facts["rina"] or (binding is not None and binding["record"].get("owner") == 209):
            rina.append((source, facts, binding))
    if not rina:
        if selection is not None:
            raise ValueError("An explicit Rina counterpart requires a selected Rina costume.")
        return None
    if len(rina) != 1:
        raise ValueError("Choose one Rina costume before creating its paired Mod ZIP.")
    source, facts, binding = rina[0]
    if source["member"] is not None:
        raise ValueError("Use a complete paired Rina ZIP, or open the original extracted game costume.")
    previews = export_result.get("preview_paths") if isinstance(export_result, dict) else None
    if not isinstance(previews, (list, tuple)) or len(previews) != len(containers):
        raise ValueError("The saved model is not bound to its original container.")
    selected_path = str(Path(previews[source["container"]]).resolve())
    selected_raw = _read(selected_path)
    selected_facts = _model_facts(selected_raw)
    if (not facts["platform"] or selected_facts["platform"] != facts["platform"] or
            facts["owner"] not in (209, None) or
            selected_facts["owner"] not in (209, None)):
        raise ValueError("The saved costume changed platform or has no verified platform.")
    if selection is not None:
        if (not isinstance(selection, dict) or set(selection) != {"counterpart_path", "selected_variant"} or
                not isinstance(selection["counterpart_path"], str) or
                selection["selected_variant"] not in ("primary", "unmasked")):
            raise ValueError("Choose a counterpart file and declare which variant is being edited.")
        counterpart_path = str(Path(selection["counterpart_path"]).resolve())
        counterpart_raw = _read(selection["counterpart_path"])
        counterpart_facts = _model_facts(counterpart_raw)
        if (facts["owner"] != 209 or counterpart_facts["owner"] != 209 or
                counterpart_facts["platform"] != facts["platform"] or
                counterpart_path in (source["path"], selected_path)):
            raise ValueError("Choose a distinct Rina counterpart for the same platform.")
        variant, explicit = selection["selected_variant"], True
    else:
        if binding is None:
            raise ValueError("Rina needs both variants. Import this costume from Game assets, open a complete paired Mod ZIP, or explicitly choose its counterpart and variant.")
        record = binding["record"]
        if facts["platform"] != "android":
            raise ValueError("This game import receipt does not identify the model's platform.")
        from webtools.core import game_models
        request = _selection(record)
        request["variant"] = "unmasked" if record["variant"] == "primary" else "primary"
        counterpart = game_models.validate_selection(repo_root, request)
        if (counterpart.get("owner") != 209 or any(counterpart.get(key) != record.get(key)
                for key in ("region", "suit_id", "attach_key"))):
            raise ValueError("The game catalog does not provide a matching Rina counterpart.")
        importing = _ImportJob(job)
        game_models.run_import(importing, repo_root=repo_root, output_root=output_root, record=counterpart)
        if job.should_stop() or len(importing.outputs) != 1:
            raise ValueError("The Rina counterpart was not completely imported.")
        counterpart_path = importing.outputs[0]
        counterpart_raw = _read(counterpart_path)
        counterpart_facts = _model_facts(counterpart_raw)
        if counterpart_facts["platform"] != facts["platform"] or counterpart_facts["owner"] not in (209, None):
            raise ValueError("The game counterpart has a different or unverified platform.")
        variant, explicit = record["variant"], False
    if _sha(counterpart_raw) == source["sha256"]:
        raise ValueError("A copy of the selected costume cannot replace its missing Rina counterpart.")
    # Keep the bytes bound across any potentially slow import/validation work.
    if (_sha(_read(selected_path)) != _sha(selected_raw) or
            _sha(_read(counterpart_path)) != _sha(counterpart_raw)):
        raise ValueError("A paired model changed while preparing the Mod ZIP.")
    selected = {"path": selected_path, "sha256": _sha(selected_raw)}
    other = {"path": counterpart_path, "sha256": _sha(counterpart_raw)}
    return {"primary": selected if variant == "primary" else other,
            "unmasked": other if variant == "primary" else selected,
            "platform": facts["platform"], "owner": 209, "explicit_source": explicit}
