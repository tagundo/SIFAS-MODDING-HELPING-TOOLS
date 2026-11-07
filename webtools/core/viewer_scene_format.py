"""Bounded, non-executable Rina scene-role envelope shared with the installer.

This is a new format. It must never fall through to the legacy text-executing
installer or be interpreted as a generic archive of independent Unity models.
"""
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile

FORMAT = "elichika-scene-costume"
VERSION = 1
CAPABILITY = "rina-scene-routing-v1"
MANIFEST = "elichika-scene-mod.json"
PAYLOAD = "resources.payload"
MAGIC = b"ELICHIKA-SCENE-RESOURCES\x00\x01\n"
LEGACY_GUARD = (b"costume_file = None\nrina_unmask_costume_file = None\n"
                b"costume_file_ios = None\nrina_unmask_costume_file_ios = None\n")
PLATFORMS = {"android": 13, "ios": 9}
ROLES = ("navi_board", "mv_board", "mv_unmasked")
VARIANTS = ("primary", "unmasked")
SUPPORTED_SCALES = frozenset(("BreastSize", "HipsSize"))
MAX_BYTES = 96 * 1024 * 1024
MAX_ENTRIES = 128
MAX_JSON = 512 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _raw(value):
    if type(value) is bytes:
        _require(0 < len(value) <= MAX_BYTES, "The scene package exceeds its size limit.")
        return value
    path = Path(value)
    before = path.stat()
    _require(path.is_file() and not path.is_symlink() and 0 < before.st_size <= MAX_BYTES,
             "Choose a bounded regular scene package file.")
    raw = path.read_bytes()
    after = path.stat()
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
             "The scene package changed while reading.")
    return raw


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "The scene manifest contains duplicate keys.")
        result[key] = value
    return result


def _json(raw):
    _require(0 < len(raw) <= MAX_JSON, "The scene metadata exceeds its size limit.")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite scene metadata.")))
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("The scene metadata is invalid.") from error


def _path(name):
    _require(isinstance(name, str) and 0 < len(name) <= 512 and "\\" not in name and "\0" not in name,
             "The scene archive contains an invalid path.")
    path = PurePosixPath(name)
    _require(not path.is_absolute() and path.parts and str(path) == name and
             ".." not in path.parts and all(":" not in part for part in path.parts),
             "The scene archive contains an unsafe path.")
    return path


def _directory(raw):
    """Bound central-directory allocation without validating member contents."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "The scene archive is too large or empty.")
    tail = raw[-65577:]
    at = tail.rfind(b"PK\x05\x06")
    _require(at >= 0 and at + 22 <= len(tail), "The scene archive has no valid ZIP directory.")
    _, disk, directory_disk, on_disk, count, size, offset, comment = struct.unpack_from("<4s4H2IH", tail, at)
    absolute = len(raw) - len(tail) + at
    _require(not disk and not directory_disk and on_disk == count and 1 <= count <= MAX_ENTRIES and
             0 < size <= 256 * 1024 and offset + size <= absolute and at + 22 + comment == len(tail) and
             not (at >= 20 and tail[at - 20:at - 16] == b"PK\x06\x07") and
             count != 0xffff and size != 0xffffffff and offset != 0xffffffff,
             "The scene archive directory exceeds its bounds.")
    return count


def _archive(raw):
    """Check the central directory before ZipFile eagerly allocates entries."""
    count = _directory(raw)
    result, total, seen = {}, 0, set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            _require(len(archive.infolist()) == count, "The scene archive directory is inconsistent.")
            for entry in archive.infolist():
                _path(entry.filename)
                folded = entry.filename.casefold()
                _require(folded not in seen and not entry.is_dir() and
                         not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1 and
                         entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and entry.file_size > 0,
                         "The scene archive has duplicate, linked, encrypted or unsupported members.")
                seen.add(folded)
                total += entry.file_size
                _require(total <= MAX_BYTES, "The scene archive expands beyond its size limit.")
                result[entry.filename] = archive.read(entry)
                _require(len(result[entry.filename]) == entry.file_size, "The scene archive member is truncated.")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError("The scene archive could not be read.") from error
    return result


def reference(member, raw, platform=None):
    _path(member)
    result = {"member": member, "sha256": sha(raw), "bytes": len(raw)}
    if platform is not None:
        _require(platform in PLATFORMS, "The scene platform is unsupported.")
        result["target_platform"] = PLATFORMS[platform]
    return result


def _native_platform(raw):
    import UnityPy
    env = UnityPy.load(raw)
    platforms = {int(asset.target_platform) for asset in env.assets}
    _require(len(platforms) == 1, "A scene model has ambiguous native platforms.")
    return next(iter(platforms))


def _ref(value, files, claimed, *, platform=None, extension=None, native_validator=None):
    keys = {"member", "sha256", "bytes"} | ({"target_platform"} if platform is not None else set())
    _require(type(value) is dict and set(value) == keys, "The scene resource reference is invalid.")
    member = value["member"]
    path = _path(member)
    _require(extension is None or path.suffix.lower() == extension, "The scene resource has an unexpected type.")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_BYTES and
             isinstance(value["sha256"], str) and _SHA.fullmatch(value["sha256"]) and member in files,
             "The scene resource is missing or has invalid metadata.")
    raw = files[member]
    _require(len(raw) == value["bytes"] and sha(raw) == value["sha256"], "The scene resource checksum does not match.")
    if member in claimed:
        _require(claimed[member] == value, "The scene resource has conflicting references.")
    else:
        if platform is not None:
            _require(type(value["target_platform"]) is int and value["target_platform"] == PLATFORMS[platform] and
                     (native_validator or _native_platform)(raw) == PLATFORMS[platform],
                     "The scene resource does not match its native Android/iOS platform.")
        claimed[member] = value
    return raw


def validate(manifest, files, *, native_validator=None):
    required = {"format", "version", "requires", "character_id", "display_name", "platforms", "canonical_goldens", "authoring",
                "thumbnail", "dependencies", "navi_sync", "source_suit_id", "source_provenance"}
    _require(type(manifest) is dict and required <= set(manifest) <= required | {"source_archives"} and manifest["format"] == FORMAT and
             type(manifest["version"]) is int and manifest["version"] == VERSION and
             manifest["requires"] == [CAPABILITY] and type(manifest["character_id"]) is int and
             manifest["character_id"] == 209, "This scene costume format or capability is unsupported.")
    name = manifest["display_name"]
    _require(isinstance(name, str) and name == name.strip() and 0 < len(name) <= 120 and
             not any(ord(char) < 32 for char in name), "The scene costume name is invalid.")
    source = manifest["source_suit_id"]
    _require(source is None or type(source) is int and 0 < source < 10 ** 12, "The source costume identity is invalid.")
    platforms = manifest["platforms"]
    _require(type(platforms) is dict and platforms and set(platforms) <= set(PLATFORMS),
             "The scene costume has no supported native platform.")
    _require(all(type(manifest[key]) is dict and set(manifest[key]) == set(platforms)
                 for key in ("canonical_goldens", "authoring", "dependencies", "navi_sync")), "The scene role families are incomplete.")
    provenance = manifest["source_provenance"]
    _require((source is None) == (provenance is None), "The source costume proof is incomplete.")
    if provenance is not None:
        _require(type(provenance) is dict and provenance and set(provenance) <= {"gl", "jp"},
                 "The source costume region is invalid.")
        for region in provenance.values():
            _require(type(region) is dict and set(region) == set(platforms), "The source platform proof is incomplete.")
            for family in region.values():
                _require(type(family) is dict and set(family) == set(VARIANTS), "The source model proof is incomplete.")
                for descriptor in family.values():
                    _require(type(descriptor) is dict and set(descriptor) == {"asset_path", "pack_name", "head", "size", "key1", "key2"}
                             and all(isinstance(descriptor[key], str) and 0 < len(descriptor[key]) <= 512
                                     for key in ("asset_path", "pack_name"))
                             and all(type(descriptor[key]) is int for key in ("head", "size", "key1", "key2"))
                             and 0 <= descriptor["head"] < 2 ** 63 and 0 < descriptor["size"] <= MAX_BYTES
                             and all(-2 ** 63 <= descriptor[key] < 2 ** 64 for key in ("key1", "key2")),
                             "The source catalog fingerprint is invalid.")
    claimed = {}
    for platform, roles in platforms.items():
        _require(type(roles) is dict and set(roles) == set(ROLES), "Each native platform needs all three scene roles.")
        for value in roles.values():
            _ref(value, files, claimed, platform=platform, extension=".unity", native_validator=native_validator)
        _require(len({row["member"] for row in roles.values()}) == 3, "Scene roles must refer to distinct model members.")
        goldens = manifest["canonical_goldens"][platform]
        _require(type(goldens) is dict and set(goldens) == {"mv_board", "mv_unmasked"},
                 "The canonical MV golden family is incomplete.")
        for value in goldens.values():
            _ref(value, files, claimed, platform=platform, extension=".unity", native_validator=native_validator)
        authoring = manifest["authoring"][platform]
        _require(type(authoring) is dict and set(authoring) == set(VARIANTS), "The scene authoring family is incomplete.")
        for records in authoring.values():
            _require(type(records) is dict and set(records) == {"original", "recipe"}, "The scene authoring reference is invalid.")
            original = _ref(records["original"], files, claimed, platform=platform, extension=".unity", native_validator=native_validator)
            recipe = _json(_ref(records["recipe"], files, claimed, extension=".json"))
            _require(type(recipe) is dict and set(recipe) == {"format", "version", "sources", "originals", "state", "nodeIdentities"}
                     and recipe["format"] == "elichika-viewer-body-edit" and type(recipe["version"]) is int and recipe["version"] == 1,
                     "The scene costume has no supported canonical edit recipe.")
            source_hash = sha(original)
            _require(type(recipe["sources"]) is list and len(recipe["sources"]) == 1 and
                     type(recipe["sources"][0]) is dict and recipe["sources"][0].get("sha256") == source_hash and
                     type(recipe["sources"][0].get("container")) is int and recipe["sources"][0]["container"] == 0 and
                     recipe["sources"][0].get("member") is None and type(recipe["originals"]) is list and
                     len(recipe["originals"]) == 1 and type(recipe["originals"][0]) is dict and
                     recipe["originals"][0].get("sha256") == source_hash and type(recipe["state"]) is dict and
                     type(recipe["nodeIdentities"]) is list and len(recipe["nodeIdentities"]) <= 1024,
                     "The scene recipe is not bound to its canonical original model.")
        dependencies = manifest["dependencies"][platform]
        _require(type(dependencies) is dict and set(dependencies) == {"facedynamic"}, "The scene dependency declaration is invalid.")
        if dependencies["facedynamic"] is not None:
            _ref(dependencies["facedynamic"], files, claimed, platform=platform, extension=".unity", native_validator=native_validator)
        sync = manifest["navi_sync"][platform]
        _require(type(sync) is dict and set(sync) <= SUPPORTED_SCALES, "The scene costume requests an unsupported Navi change.")
        for value in sync.values():
            _require(type(value) is list and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) and
                     1e-8 <= abs(v) <= 1000000 for v in value), "The Navi scale endpoint is invalid.")
    if manifest["thumbnail"] is not None:
        raw = _ref(manifest["thumbnail"], files, claimed, extension=".png")
        _require(raw.startswith(b"\x89PNG\r\n\x1a\n"), "The scene thumbnail is not a PNG.")
    archives = manifest.get("source_archives", [])
    _require(type(archives) is list and len(archives) <= 8, "The inert source archive list is invalid.")
    for archive in archives:
        _require(type(archive) is dict and set(archive) == {"name", "file"} and
                 isinstance(archive["name"], str) and len(archive["name"]) <= 120 and
                 len(_path(archive["name"]).parts) == 1, "The inert source archive identity is invalid.")
        _ref(archive["file"], files, claimed, extension=".data")
    _require(set(files) == set(claimed), "The scene payload has undeclared or missing resources.")
    return {"manifest": manifest, "files": files}


def is_scene_package(value):
    """Only a dispatch hint; malformed recognized packages still fail read()."""
    try:
        raw = _raw(value)
    except OSError:
        return False
    if not raw.startswith(b"PK"):
        return False
    # Do not use the strict member reader here. A marker remains a scene
    # claim when other entries are duplicate, unsafe, or oversized; it must
    # reach read_package and be refused, never fall through to legacy exec.
    _directory(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if any(PurePosixPath(name.replace("\\", "/")).name.casefold() == MANIFEST for name in names):
                return True
            for info in archive.infolist():
                if PurePosixPath(info.filename.replace("\\", "/")).name.casefold() == PAYLOAD:
                    with archive.open(info) as stream:
                        if stream.read(len(MAGIC)) == MAGIC:
                            return True
            return False
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError("The costume archive could not be classified safely.") from error


def read_package(value, *, native_validator=None):
    raw = _raw(value)
    outer = _archive(raw)
    _require(set(outer) == {MANIFEST, PAYLOAD, "modinstall.txt"} and outer["modinstall.txt"] == LEGACY_GUARD,
             "The scene costume envelope or old-version guard is invalid.")
    payload = outer[PAYLOAD]
    _require(payload.startswith(MAGIC), "The scene resource envelope has an unsupported version.")
    return validate(_json(outer[MANIFEST]), _archive(payload[len(MAGIC):]), native_validator=native_validator)


def encode_package(manifest, files, *, native_validator=None):
    validate(manifest, files, native_validator=native_validator)
    def encode(entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(entries.items()):
                archive.writestr(name, raw)
        return output.getvalue()
    return encode({MANIFEST: json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(),
                   PAYLOAD: MAGIC + encode(files), "modinstall.txt": LEGACY_GUARD})
