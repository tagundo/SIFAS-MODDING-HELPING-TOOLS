"""Bounded, temporary model inputs from costume ZIPs; never execute manifests."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import ast
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import tempfile
import threading
import zipfile

MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
MAX_UNPACKED_BYTES = 96 * 1024 * 1024
MAX_ENTRIES = 128
MAX_MODELS = 8
MAX_MANIFEST_BYTES = 64 * 1024
MAX_DIRECTORY_BYTES = 256 * 1024
_SLOTS = threading.BoundedSemaphore(2)


@dataclass
class ExpandedInputs:
    paths: list
    manifest_paths: list
    source_names: list
    origins: dict
    variants: list = field(default_factory=list)
    archive_members: dict = field(default_factory=dict)


def _entry_path(info):
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    mode = info.external_attr >> 16
    if (not name or (not path.parts and not info.is_dir())
            or len(name) > 512 or "\0" in name or path.is_absolute()
            or ".." in path.parts or any(":" in part for part in path.parts)
            or stat.S_ISLNK(mode)):
        raise ValueError("The costume ZIP contains an unsafe file path.")
    if info.flag_bits & 1:
        raise ValueError("Encrypted costume ZIPs cannot be previewed.")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ValueError("Use a stored or deflated costume ZIP for the mobile viewer.")
    return path


def _model_header(header, size):
    if header.startswith(b"UnityFS\0"):
        return True
    if len(header) < 20:
        return False
    metadata, length, version, offset = struct.unpack_from(">IIII", header)
    if version == 22 and len(header) >= 48:
        metadata, length, offset = struct.unpack_from(">Iqq", header, 20)
    return (14 <= version <= 22 and length == size and 0 < metadata <= size
            and 20 <= offset <= size and header[16] in (0, 1))


def _copy_member(archive, info, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    remaining = info.file_size
    with archive.open(info) as source, destination.open("xb") as target:
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                raise ValueError("The costume ZIP contains a truncated file.")
            target.write(chunk)
            remaining -= len(chunk)
        if source.read(1):
            raise ValueError("The costume ZIP exceeds its declared file size.")


_PLATFORM_PAIRS = (("costume_file", "costume_file_ios"),
                   ("rina_unmask_costume_file", "rina_unmask_costume_file_ios"))


def _manifest_models(models, manifests):
    """Resolve only bounded literal model references in this archive."""
    keys = {key for pair in _PLATFORM_PAIRS for key in pair}
    available = {str(relative).casefold() for _, relative in models}
    records = []
    for path, relative in manifests:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            values, assignments = {}, {}
            for item in tree.body:
                if (isinstance(item, ast.Assign) and len(item.targets) == 1
                        and isinstance(item.targets[0], ast.Name)
                        and item.targets[0].id in keys):
                    key = item.targets[0].id
                    value = ast.literal_eval(item.value)
                    values[key] = value
                    assignments.setdefault(key, []).append(value)
        except (OSError, UnicodeError, SyntaxError, ValueError, TypeError, RecursionError):
            continue

        def member(value):
            if not isinstance(value, str) or not value or len(value) > 512:
                return None
            target = PurePosixPath(value.replace("\\", "/"))
            if (target.is_absolute() or ".." in target.parts or "\0" in value
                    or any(":" in part for part in target.parts)):
                return None
            target = str(relative.parent / target).casefold()
            return target if target in available else None

        resolved = {key: member(values.get(key)) for key in keys}
        conflicts = {key for key, assigned in assignments.items()
                     if any(member(value) != resolved[key] for value in assigned)}
        records.append((resolved, conflicts))
    return records


def _platform_models(models, manifests, records=None):
    """Prefer declared Android variants, preserving unrelated model parts.

    A dual-platform installer names two alternative copies of each costume.
    Loading both duplicates the skeleton and prevents automatic facial bones
    from joining it. Only exclude an iOS member when its declared Android
    counterpart is also a real model in this ZIP. Names alone are not evidence
    of a platform, and iOS-only packages remain usable by the viewer.
    """
    preferred, alternatives = set(), set()
    for values, _ in records if records is not None else _manifest_models(models, manifests):
        for android, ios in _PLATFORM_PAIRS:
            primary, alternate = values.get(android), values.get(ios)
            if primary is not None:
                preferred.add(primary)
                if alternate is not None and alternate != primary:
                    alternatives.add(alternate)
    # A model explicitly selected as primary by another installer must survive.
    excluded = alternatives - preferred
    return [(info, relative) for info, relative in models
            if str(relative).casefold() not in excluded]


def _variant_models(models, manifests, choice):
    """Choose one declared costume family before any Unity model is loaded.

    The manifest's primary and Rina-unmasked files are alternatives, while
    Android/iOS names within either family are platform copies. Unrelated
    explicitly supplied model parts remain independent of this choice.
    """
    records = _manifest_models(models, manifests)
    declarations = {}
    all_primary, all_unmasked = set(), set()
    conflicting = False
    for values, conflicts in records:
        primary = frozenset(filter(None, (values.get(key) for key in _PLATFORM_PAIRS[0])))
        unmasked = frozenset(filter(None, (values.get(key) for key in _PLATFORM_PAIRS[1])))
        all_primary.update(primary)
        all_unmasked.update(unmasked)
        if not primary or not unmasked:
            continue
        if primary == unmasked and (
                values.get(_PLATFORM_PAIRS[0][0]) or values.get(_PLATFORM_PAIRS[0][1])) == (
                values.get(_PLATFORM_PAIRS[1][0]) or values.get(_PLATFORM_PAIRS[1][1])):
            continue
        if primary & unmasked or conflicts:
            conflicting = True
        pair = (primary, unmasked)
        previous = declarations.get(pair)
        if previous is not None and any(
                (previous.get(android) or previous.get(ios)) !=
                (values.get(android) or values.get(ios))
                for android, ios in _PLATFORM_PAIRS):
            conflicting = True
        declarations[pair] = values
    if declarations:
        if len(declarations) != 1:
            conflicting = True
        primary, unmasked = next(iter(declarations))
        if primary & all_unmasked or unmasked & all_primary:
            conflicting = True
        if conflicting:
            raise ValueError("The costume ZIP declares conflicting costume variants.")
        selected = choice or "primary"
        values = next(iter(declarations.values()))
        family = _PLATFORM_PAIRS[0 if selected == "primary" else 1]
        selected_member = values.get(family[0]) or values.get(family[1])
        excluded = (primary | unmasked) - {selected_member}
        filtered = {str(relative).casefold()
                    for _, relative in _platform_models(models, manifests, records)}
        return ([(info, relative) for info, relative in models
                 if str(relative).casefold() not in excluded and
                 (str(relative).casefold() in filtered or
                  str(relative).casefold() == selected_member)], selected)
    if choice is not None:
        raise ValueError("This costume ZIP does not offer that variant.")
    return _platform_models(models, manifests, records), None


def _preflight_zip(path):
    # ZipFile builds every ZipInfo eagerly. Bound its central directory before
    # construction; a tiny compressed payload can otherwise contain a million
    # empty entries and exhaust Android memory before our entry-count check.
    size = os.path.getsize(path)
    if not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ValueError("The costume ZIP is too large for the mobile viewer.")
    # Include the optional 20-byte locator even with a maximum-size comment.
    with open(path, "rb") as source:
        source.seek(max(0, size - 65577))
        tail = source.read(65577)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or at + 22 > len(tail):
        raise ValueError("The costume ZIP could not be read. Check the archive and try again.")
    _, disk, directory_disk, on_disk, count, directory_size, offset, comment = \
        struct.unpack_from("<4s4H2IH", tail, at)
    absolute = size - len(tail) + at
    # Python consults a ZIP64 locator even when the ordinary EOCD fields do
    # not contain sentinels. Reject both forms so it cannot replace our bounds.
    zip64 = at >= 20 and tail[at - 20:at - 16] == b"PK\x06\x07"
    if (zip64 or count == 0xFFFF or directory_size == 0xFFFFFFFF
            or offset == 0xFFFFFFFF):
        raise ValueError("ZIP64 costume archives are not supported by the mobile viewer.")
    if disk or directory_disk or on_disk != count:
        raise ValueError("Split costume ZIPs are not supported by the mobile viewer.")
    if (at + 22 + comment != len(tail) or not 1 <= count <= MAX_ENTRIES
            or not 0 < directory_size <= MAX_DIRECTORY_BYTES
            or offset + directory_size > absolute):
        raise ValueError("The costume ZIP directory exceeds the mobile preview limit.")


@contextmanager
def expand_inputs(paths, cache_root, variant_choices=None):
    """Yield selected files plus isolated ZIP members for one conversion.

    Only Unity model bytes and bounded modinstall.txt data are extracted. All
    filenames are validated before extraction, including ignored ZIP entries.
    Temporary files live through GLB conversion and disappear on every exit.
    """
    choices = {} if variant_choices is None else variant_choices
    if (not isinstance(choices, dict) or len(choices) > MAX_MODELS
            or any(not isinstance(value, str) or value not in ("primary", "unmasked")
                   for value in choices.values())):
        raise ValueError("Choose a valid costume variant.")
    if any(not isinstance(path, str) or path not in paths for path in choices):
        raise ValueError("Costume variant choices must refer to selected costume ZIPs.")
    names = [Path(path).name for path in paths]
    archives = [path for path in paths
                if Path(path).suffix.lower() == ".zip" or zipfile.is_zipfile(path)]
    if any(path not in archives for path in choices):
        raise ValueError("Costume variant choices must refer to selected costume ZIPs.")
    if not archives:
        yield ExpandedInputs(list(paths), [], names, {path: path for path in paths})
        return
    if not _SLOTS.acquire(blocking=False):
        raise TimeoutError("Another costume ZIP is being prepared. Try again shortly.")
    conversion_started = False
    try:
        cache_root = Path(cache_root)
        if cache_root.is_symlink():
            raise ValueError("The model preview cache must not be a symbolic link.")
        cache_root.mkdir(parents=True, exist_ok=True)
        if cache_root.resolve() != cache_root.absolute():
            raise ValueError("The model preview cache must use its real folder path.")
        with tempfile.TemporaryDirectory(prefix="viewer-zip-", dir=cache_root) as temporary:
            result, manifests, origins, variants, members = [], [], {}, [], {}
            total = 0
            for index, path in enumerate(paths):
                if path not in archives:
                    result.append(path)
                    origins[path] = path
                    continue
                _preflight_zip(path)
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    if not 1 <= len(entries) <= MAX_ENTRIES:
                        raise ValueError("The costume ZIP contains too many files.")
                    targets = set()
                    checked = []
                    for info in entries:
                        relative = _entry_path(info)
                        normalized = str(relative).casefold()
                        if normalized in targets:
                            raise ValueError("The costume ZIP contains duplicate file paths.")
                        targets.add(normalized)
                        if info.file_size < 0:
                            raise ValueError("The costume ZIP contains an invalid file size.")
                        total += info.file_size
                        if total > MAX_UNPACKED_BYTES:
                            raise ValueError("The costume ZIP expands beyond the mobile preview limit.")
                        checked.append((info, relative))
                    models, archive_manifests = [], []
                    for info, relative in checked:
                        if info.is_dir():
                            continue
                        destination = Path(temporary) / str(index) / Path(*relative.parts)
                        if relative.name.lower() == "modinstall.txt":
                            if info.file_size > MAX_MANIFEST_BYTES:
                                raise ValueError("The costume manifest is too large.")
                            _copy_member(archive, info, destination)
                            manifests.append(str(destination))
                            origins[str(destination)] = path
                            archive_manifests.append((destination, relative))
                            continue
                        with archive.open(info) as member:
                            header = member.read(48)
                        if not _model_header(header, info.file_size):
                            continue
                        models.append((info, relative))
                    selected_models, selected_variant = _variant_models(
                        models, archive_manifests, choices.get(path))
                    if selected_variant is not None:
                        variants.append({"source_path": path, "source_name": Path(path).name,
                                         "selected": selected_variant,
                                         "choices": ["primary", "unmasked"]})
                    for info, relative in selected_models:
                        destination = Path(temporary) / str(index) / Path(*relative.parts)
                        _copy_member(archive, info, destination)
                        result.append(str(destination))
                        origins[str(destination)] = path
                        members[str(destination)] = info.filename
                        if len(result) > MAX_MODELS:
                            raise ValueError("Choose a costume ZIP containing at most eight model files.")
            if not 1 <= len(result) <= MAX_MODELS:
                raise ValueError("The costume ZIP contains no extracted Unity model files.")
            expanded = ExpandedInputs(result, manifests, names, origins, variants, members)
            # Keep conversion errors distinct from ZIP parsing errors.
            conversion_started = True
            yield expanded
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as error:
        if conversion_started:
            raise
        raise ValueError("The costume ZIP could not be read. Check the archive and try again.") from error
    finally:
        _SLOTS.release()
