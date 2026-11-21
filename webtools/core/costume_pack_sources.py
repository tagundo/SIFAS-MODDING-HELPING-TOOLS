"""Read-only, bounded game-cache provenance for selected packer files.

Names never establish costume identity. A selected file must match a managed
receipt's SHA256 and its exact current game selection. Native platform proof
comes from actual Unity bytes, never the host OS or an Android default.
"""
import copy
import hashlib
import json
from itertools import islice
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time

from . import game_models as game
from . import viewer_mod_sources as sources
from .viewer_cache import game_models_dir

MAX_SELECTED = 512
# Bodies are read one at a time and each is bounded by sources.MAX_BYTES.
MAX_SELECTED_BYTES = MAX_SELECTED * sources.MAX_BYTES
MAX_RECEIPTS = 256
MAX_ROOT_ENTRIES = 2048
MAX_RECEIPT_BYTES = 16 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _descriptor(record):
    return {key: value for key, value in record.items() if key != "download"}


def _selection_source(record):
    # Purpose and locale can produce separate receipts for identical native
    # packs. Keep the platform and every resource descriptor in the identity.
    source = {key: value for key, value in record.items()
              if key not in ("download", "purpose", "selection_language")}
    source.setdefault("platform", "android")
    return source


def _roots(requested):
    current = game_models_dir()
    legacy = current.parents[2] / "extracted" / "game-models"
    fixed = (current, current / "transplant-bodies", legacy, legacy / "transplant-bodies")
    allowed = {path.absolute() for path in fixed}
    candidates = fixed if requested is None else tuple(Path(path).expanduser().absolute() for path in requested)
    if len(candidates) > 4 or any(path not in allowed for path in candidates):
        raise ValueError("Costume identity may only use the managed viewer model caches.")
    return [path for path in dict.fromkeys(candidates)
            if not path.is_symlink() and path.resolve() == path and path.is_dir()]


def _origin(data, root, manifest):
    if manifest.name.startswith(".provenance-"):
        origin = Path(data["path"])
        if not origin.is_absolute() or ".." in origin.parts:
            raise ValueError("The preserved costume receipt has an invalid source path.")
        origin = origin.resolve()
        expected = hashlib.sha256(str(origin).encode()).hexdigest()[:32]
        if manifest.name != ".provenance-" + expected + ".json":
            raise ValueError("The preserved costume receipt no longer matches its source path.")
        return origin, data.get("record"), None
    relative = PurePosixPath(data["model"])
    if relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
        raise ValueError("The game costume receipt has an invalid source path.")
    origin = (root / relative).resolve()
    if not origin.is_relative_to(root):
        raise ValueError("The game costume receipt escapes its managed cache.")
    return origin, data.get("selection_record"), data.get("source")


def _current_record(repo_root, record):
    record = sources._record(record)
    if type(record.get("owner")) is not int or not 0 < record["owner"] < 10000:
        raise ValueError("The game costume receipt has no valid character identity.")
    params = sources._selection(record)
    if "purpose" in record:
        languages = (record["selection_language"],)
    else:
        # Viewer records predate a language field. Check the actual finite DB
        # selections, retaining only an exact descriptor match; do not replace
        # the recorded resource with a default Android/language selection.
        languages = ("en", "ko", "zh", "ja")
    for language in languages:
        try:
            current = game.validate_selection(repo_root, params, language)
        except (ValueError, sqlite3.Error, OSError):
            continue
        if _descriptor(current) == _descriptor(record):
            return current
    raise ValueError("A matching costume cache receipt is stale or its exact game catalog is unavailable. Reimport that costume before pairing.")


def _platform_raw(raw, name):
    from .model_viewer import _preflight_bundle
    _preflight_bundle(raw)
    import UnityPy
    environment = UnityPy.load(raw)
    values = {int(asset.target_platform) for asset in environment.assets}
    if len(values) != 1 or not values <= {-2, 9, 13}:
        raise ValueError("The selected costume has an ambiguous or unsupported Unity platform: " + Path(name).name)
    return next(iter(values))


class _ReadJob:
    def should_stop(self):
        return False

    def log(self, message):
        pass


def _local_native_platform(repo_root, record, stored_sources):
    """Optional NoTarget diagnostic proof; this path never downloads bytes."""
    if record.get("scene_source") is not None:
        from . import viewer_scene_format as fmt
        scene = record["scene_source"]
        try:
            path = Path(scene["archive_path"])
            raw = fmt._raw(path)
            if hashlib.sha256(raw).hexdigest() != scene["sha256"]:
                raise ValueError("The recorded local canonical costume source changed. Reimport it.")
            decoded = fmt.read_package(raw)
            platform = record.get("platform")
            family = decoded["manifest"]["canonical_goldens"].get(platform)
            if family is None:
                return None
            role = "mv_board" if record["variant"] == "primary" else "mv_unmasked"
            body = decoded["files"][family[role]["member"]]
            code = _platform_raw(body, path.name)
            return {9: "ios", 13: "android"}.get(code)
        except (OSError, KeyError):
            return None
    try:
        extractor = game._extractor()
    except (ImportError, ValueError):
        return None
    deadline, job = time.monotonic() + 8, _ReadJob()
    resources = [record, *record.get("recolours", [])]
    found = [game._source(repo_root, resource, extractor, job, deadline) for resource in resources]
    if not found or any(path is None for path, _ in found):
        return None
    current = [signature for _, signature in found]
    if not isinstance(stored_sources, list) or len(stored_sources) != len(current):
        return None
    if any(stored is not None and stored != signature for stored, signature in zip(stored_sources, current)):
        raise ValueError("The local source pack no longer matches the costume cache receipt. Reimport the costume.")
    if any(stored is None for stored in stored_sources):
        return None
    body = game._plain_section(job, record, found[0][0], found[0][1], extractor, deadline)
    return {9: "ios", 13: "android"}.get(_platform_raw(bytes(body), found[0][0].name))


def _check_local_signatures(signatures):
    # A missing pack does not erase an already imported original's receipt.
    # When the recorded local file still exists, stale size/mtime provenance
    # must not authorize pairing. This performs no download or payload read.
    if not isinstance(signatures, list):
        return
    if len(signatures) > 64:
        raise ValueError("The costume receipt has too many local source signatures.")
    for signature in signatures:
        if not isinstance(signature, dict) or "path" not in signature:
            continue
        if not isinstance(signature["path"], str) or len(signature["path"]) > 4096:
            raise ValueError("The costume cache has an invalid local source signature.")
        path = Path(signature["path"])
        if not path.is_absolute():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("The recorded local costume source cannot be checked. Reimport the costume.") from error
        if (path.is_symlink() or path.resolve() != path or
                stat.st_size != signature.get("size") or stat.st_mtime_ns != signature.get("mtime_ns")):
            raise ValueError("The local source pack no longer matches the costume cache receipt. Reimport the costume.")


def source_bindings(paths, repo_root=None, cache_roots=None):
    """Return source-bound family/variant metadata keyed by selected real path.

    An unrecognized file simply has no binding. A receipt which claims the
    selected path/hash but is stale or conflicts with another match is an error.
    The caller still validates role/content, actual platform, and unchanged bytes
    before packaging. NoTarget is never converted or made installer-ready here.
    """
    if isinstance(paths, (str, bytes)):
        raise ValueError("Choose costume files as a bounded selection list.")
    paths = list(paths)
    if len(paths) > MAX_SELECTED:
        raise ValueError("Choose at most 512 files for source-bound costume pairing.")
    roots = _roots(cache_roots)
    if not roots or not paths:
        return {}
    if repo_root is None:
        from .repo import repo_root as default_repo_root
        repo_root = default_repo_root()
    repo_root = Path(repo_root).resolve()
    selected, total = {}, 0
    for value in paths:
        path = Path(value).expanduser().absolute()
        raw = sources._read(path)
        total += len(raw)
        if total > MAX_SELECTED_BYTES:
            raise ValueError("The selected costume sources exceed the provenance-read size limit.")
        selected[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        del raw
    matches, validated = {path: [] for path in selected}, {}
    inspected = 0
    roots.sort(key=lambda root: not any(Path(path).is_relative_to(root) for path in selected))
    for root in roots:
        try:
            entries = sorted(islice(root.iterdir(), MAX_ROOT_ENTRIES))
        except OSError:
            continue
        manifests = (path for path in entries if path.name.startswith((".selection-", ".provenance-")) and path.name.endswith(".json"))
        for manifest in manifests:
            if inspected >= MAX_RECEIPTS:
                break
            inspected += 1
            try:
                if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > MAX_RECEIPT_BYTES:
                    continue
                with manifest.open("rb") as handle:
                    encoded = handle.read(MAX_RECEIPT_BYTES + 1)
                if len(encoded) > MAX_RECEIPT_BYTES:
                    continue
                data = json.loads(encoded.decode("utf-8"))
                if not isinstance(data, dict):
                    continue
                digest = data.get("sha256")
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                continue
            try:
                origin, record, signatures = _origin(data, root, manifest)
            except (ValueError, KeyError, TypeError) as error:
                if digest in selected.values():
                    raise ValueError("A matching costume cache receipt has invalid source provenance. Reimport that costume.") from error
                continue
            targets = [path for path, current_sha in selected.items() if current_sha == digest]
            if str(origin) in selected and selected[str(origin)] != digest:
                raise ValueError("A selected cached costume changed after its source receipt was written. Export or reimport a verified source before pairing.")
            if not targets:
                continue
            if not isinstance(digest, str) or not _SHA.fullmatch(digest):
                raise ValueError("A matching costume receipt has no valid source SHA256.")
            fingerprint = json.dumps(_descriptor(sources._record(record)), sort_keys=True, allow_nan=False)
            if fingerprint not in validated:
                validated[fingerprint] = _current_record(repo_root, record)
            current = validated[fingerprint]
            for path in targets:
                matches[path].append({"record": current, "manifest": str(manifest), "origin": str(origin), "sources": signatures})
    result = {}
    for path, candidates in matches.items():
        if not candidates:
            continue
        identities = {json.dumps(_selection_source(item["record"]), sort_keys=True, allow_nan=False) for item in candidates}
        if len(identities) != 1:
            raise ValueError("The selected bytes match conflicting game costume receipts; choose a freshly imported exact costume/variant.")
        receipt = max(candidates, key=lambda item: "platform" in item["record"])
        record = receipt["record"]
        for candidate in candidates:
            _check_local_signatures(candidate["sources"])
        raw = sources._read(path)
        if hashlib.sha256(raw).hexdigest() != selected[path]:
            raise ValueError("A selected costume changed while its source identity was being checked.")
        code = _platform_raw(raw, path)
        actual = {9: "ios", 13: "android"}.get(code)
        intended = record.get("platform")
        if actual is not None and intended is not None and actual != intended:
            raise ValueError("The selected costume's native Unity platform disagrees with its source receipt. Reimport the matching platform.")
        if actual is None:
            actual_source = _local_native_platform(repo_root, record, receipt["sources"])
            if actual_source is not None and intended is not None and actual_source != intended:
                raise ValueError("The local source bytes disagree with the recorded costume platform. Reimport the matching platform.")
            native_verified = actual_source is not None
            platform = actual_source or intended
        else:
            platform, native_verified = actual, True
        result[path] = {"sha256": selected[path], "owner": record["owner"], "suit_id": record["suit_id"],
                        "region": record["region"], "variant": record["variant"], "platform": platform,
                        "native_platform_verified": native_verified,
                        "receipt": {"path": path, "sha256": selected[path], "record": copy.deepcopy(record),
                                    "manifest": receipt["manifest"], "original_path": receipt["origin"]}}
    return result
