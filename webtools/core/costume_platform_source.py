"""Resolve the original counterpart of one edited costume body."""
from contextlib import closing, contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import zipfile

from webtools import filebrowser

from . import costume_pack_sources, game_models as game, viewer_mod_flow
from . import viewer_archive, viewer_mod_package, viewer_mod_sources, viewer_physics_runtime
from .viewer_cache import game_models_dir

DIRECTIONS = {"android_to_ios": ("android", "ios"), "ios_to_android": ("ios", "android")}
UNKNOWN = "Choose the original costume and variant manually. The edited bundle could not be matched to the game catalog."
AMBIGUOUS = "More than one original costume matches this bundle. Choose the costume and variant manually."
WRONG_REGION = "The edited bundle's source belongs to a different game region. Select that region or choose the original manually."
_PREFAB = re.compile(r"assets/llas/resources/characters/models/ch(\d{4})/ch\1_[a-z0-9_]{1,96}_member\.prefab")
_FILENAME_HINT = re.compile(r"ch(\d{4})_suit([1-9][0-9]{0,11})_(primary|unmasked)(?:_[a-z0-9_-]{1,60})?\.unity(?:3d)?", re.I)
_DISPLAY_HINT = re.compile(r"ch(\d{4})_suit([1-9][0-9]{0,11})_(primary|unmasked)(?=$|[^a-z0-9])", re.I)
_NATIVE_PLATFORMS = {"android": 13, "ios": 9}
_CAB = re.compile(r"cab-[0-9a-f]{32}")
_PACK_WRAPPERS = ("", "files", "files/files", "static")
_PACK_BUCKETS = tuple(prefix + str(bucket) for prefix in ("pak", "pkg") for bucket in range(10))
_MAX_BUCKET_ENTRIES = 1024


def _checked_path(value, *, directory=False):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise ValueError("Choose a valid costume bundle or packs folder.")
    path = Path(value).expanduser().absolute()
    if not filebrowser.is_within_allowed(path):
        raise PermissionError("Choose a file or folder inside the allowed library.")
    if path.resolve() != path or path.is_symlink():
        raise ValueError("Choose the real file or folder, without symbolic links.")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError("The selected costume bundle or packs folder is unavailable.")
    return path



def _archive_models(archive):
    members, manifests, models = {}, [], set()
    unpacked = 0
    entries = archive.infolist()
    if not 1 <= len(entries) <= viewer_archive.MAX_ENTRIES:
        raise ValueError("The costume ZIP contains too many files.")
    for info in entries:
        relative = viewer_archive._entry_path(info)
        key = str(relative).casefold()
        unpacked += info.file_size
        if key in members:
            raise ValueError("The costume ZIP contains duplicate file paths.")
        if not 0 <= unpacked <= viewer_archive.MAX_UNPACKED_BYTES:
            raise ValueError("The costume ZIP expands beyond the model import limit.")
        members[key] = info
        if info.is_dir():
            continue
        if relative.name.lower() == "modinstall.txt":
            if info.file_size > viewer_archive.MAX_MANIFEST_BYTES:
                raise ValueError("The costume manifest is too large.")
            manifests.append((info, relative))
            continue
        with archive.open(info) as source:
            header = source.read(48)
        if viewer_archive._model_header(header, info.file_size):
            models.add(key)
    if not manifests:
        if len(models) != 1:
            raise ValueError("Choose a costume ZIP containing one Unity body or one installer manifest.")
        return [members[key] for key in models], ()
    if len(manifests) != 1:
        raise ValueError("The costume ZIP contains multiple installer manifests.")
    info, relative = manifests[0]
    raw = archive.read(info)
    values, _ = viewer_mod_package._manifest(raw, "")
    references, conflicts = viewer_archive._manifest_model_references(
        raw, relative, {key for key, member in members.items() if not member.is_dir()},
    )
    if conflicts or any(values.get(key) and references.get(key) is None
                        for key in viewer_archive._MODEL_FIELDS):
        raise ValueError("The costume ZIP has missing or conflicting model references.")
    declared_bodies = [references[key] for key in viewer_archive._BODY_FIELDS if references[key]]
    bodies = set(declared_bodies)
    companions = {references[key] for key in viewer_archive._COMPANION_FIELDS if references[key]}
    if len(bodies) != len(declared_bodies):
        raise ValueError("The costume ZIP reuses one body for multiple installer roles.")
    if not bodies or bodies & companions or models - companions != bodies:
        raise ValueError("The costume ZIP does not declare each Unity model as a body or companion.")
    names = tuple(values[key] for key in viewer_mod_package._NAMES if isinstance(values.get(key), str))
    return [members[key] for key in sorted(bodies)], names


def _read_archive_body(path, source_platform):
    import UnityPy

    from .model_viewer import _preflight_bundle

    # Preflight and parse the same bounded snapshot, including when a mod is
    # being copied into the library while the chooser is open.
    snapshot = viewer_mod_sources._read(path)
    with tempfile.TemporaryDirectory(prefix="costume-conversion-zip-") as temporary:
        private = Path(temporary) / "source.zip"
        private.write_bytes(snapshot)
        del snapshot
        viewer_archive._preflight_zip(private)
        try:
            with zipfile.ZipFile(private) as archive:
                models, names = _archive_models(archive)
                selected = None
                for info in models:
                    if not 0 < info.file_size <= game.MAX_MODEL_BYTES:
                        raise ValueError("A costume ZIP body exceeds the model import limit.")
                    raw = archive.read(info)
                    if not raw.startswith(b"UnityFS\0"):
                        raise ValueError("The costume ZIP needs original UnityFS body bundles.")
                    _preflight_bundle(raw)
                    try:
                        environment = UnityPy.load(raw)
                        platforms = {int(asset.target_platform) for asset in environment.assets}
                    except Exception as exc:
                        raise ValueError("A costume ZIP body could not be read as a native Unity bundle.") from exc
                    if len(platforms) != 1 or not platforms <= set(_NATIVE_PLATFORMS.values()):
                        raise ValueError("The costume ZIP contains a body without one native platform.")
                    if platforms != {_NATIVE_PLATFORMS[source_platform]}:
                        continue
                    if selected is not None:
                        raise ValueError("The costume ZIP contains multiple bodies for this conversion platform.")
                    selected = raw, info.filename
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as exc:
            raise ValueError("The costume ZIP could not be read. Check the archive and try again.") from exc
    if selected is None:
        label = "Android" if source_platform == "android" else "iOS"
        raise ValueError(f"The costume ZIP contains no {label} body for this conversion direction.")
    raw, member = selected
    return raw, member, names


@contextmanager
def converter_input(path, source_platform, *, expected_sha256=None):
    """Supply the existing converter with a pinned native body file."""
    if path.suffix.lower() != ".zip":
        yield path, expected_sha256
        return
    raw, _, _ = _read_archive_body(_checked_path(str(path)), source_platform)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("The costume body in the ZIP changed. Match the original again.")
    with tempfile.TemporaryDirectory(prefix="costume-conversion-body-") as temporary:
        body = Path(temporary) / "body.unity"
        body.write_bytes(raw)
        yield body, digest


def _proof(path, digest):
    return {"path": str(path), "containerSha256": digest, "member": None, "sha256": digest}


def _receipt_selection(path, digest, repo_root, cache_root):
    """Follow only the verified wearer of an edit or graft, never its donor."""
    proof = _proof(path, digest)
    for _ in range(viewer_physics_runtime._MAX_DERIVED_DEPTH):
        context = {"containers": [{"path": str(path), "sha256": digest}]}
        receipts = viewer_mod_flow.cached_receipts(context, cache_root)
        if receipts:
            records = [costume_pack_sources._current_record(repo_root, item["record"]) for item in receipts]
            identities = {(record["region"], record["suit_id"], record["variant"]) for record in records}
            if len(identities) > 1:
                return "ambiguous", None
            return "matched", records[0]
        row = viewer_physics_runtime._read_receipt(cache_root, proof)
        parents = row.get("parents") if row else None
        if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
            break
        proof = parents[0]
        if not isinstance(proof, dict) or proof.get("member") is not None:
            break
        path = _checked_path(proof.get("path"))
        viewer_physics_runtime._entry_context(proof)
        digest = proof["sha256"]
    return "unknown", None


def _body_identity(env):
    """Use the canonical root prefab and serialized identity, not texture names."""
    candidates = []
    for name, pointer in env.container.items():
        if not isinstance(name, str):
            continue
        key = name.lower()
        found = _PREFAB.fullmatch(key)
        if found and pointer.file_id == 0 and pointer.path_id:
            candidates.append((int(found.group(1)), key, pointer.path_id))
    if len(candidates) != 1:
        return None
    cabs = {asset.name.lower() for asset in env.assets}
    if len(cabs) != 1 or not all(_CAB.fullmatch(name) for name in cabs):
        return None
    owner, prefab, path_id = candidates[0]
    return owner, prefab, path_id, next(iter(cabs))


def _selection(region, suit_id, variant, platform):
    return {"region": region, "suit": f"suit:{suit_id}", "variant": variant,
            "download": False, "purpose": "transplant", "platform": platform}


def _named_catalog_matches(db, owner, prefab):
    name = prefab.rsplit("/", 1)[-1]
    # Developer/extracted catalogues can have literal paths. Production GL/JP
    # usually stores opaque model keys, so these rows are often empty.
    keys = (prefab, name, name + ".unity3d")
    rows = db.execute(
        "SELECT id, 'primary' FROM m_suit WHERE member_m_id=? AND model_asset_path IN (?,?,?)",
        (owner, *keys)).fetchall()
    try:
        rows += db.execute(
            "SELECT s.id, 'unmasked' FROM m_suit_view v JOIN m_suit s ON s.id=v.suit_master_id "
            "WHERE s.member_m_id=? AND v.view_status=2 AND v.model_asset_path IN (?,?,?)",
            (owner, *keys)).fetchall()
    except sqlite3.OperationalError:
        pass
    return set(rows)


def _model_aliases(db, owner, model):
    primary = db.execute(
        "SELECT id, 'primary' FROM m_suit WHERE member_m_id=? AND model_asset_path=? LIMIT 2",
        (owner, model)).fetchall()
    try:
        variants = db.execute(
            "SELECT s.id, 'unmasked' FROM m_suit_view v JOIN m_suit s ON s.id=v.suit_master_id "
            "WHERE s.member_m_id=? AND v.view_status=2 AND v.model_asset_path=? LIMIT 2",
            (owner, model)).fetchall()
    except sqlite3.OperationalError:
        variants = []
    return set(primary + variants)


class _PreviewJob:
    def should_stop(self):
        return False

    def log(self, message):
        pass


class _LocalPacks:
    """Probe the exact requested name in supported layouts without indexing."""
    def __init__(self, extra=None):
        self.extra = extra

    def _roots(self, repo_root, extractor):
        from .sukusta import default_sukusta_dir

        if self.extra is not None and self.extra.resolve() != self.extra:
            raise ValueError("The selected packs folder changed. Choose it again.")
        clients = [path for path, status in extractor.detect_game_candidates() if status == "found"]
        roots = extractor.build_pack_roots(str(repo_root), [], clients)
        preferred = [self.extra, default_sukusta_dir("packs"), *roots]
        return list(dict.fromkeys(Path(root).expanduser().resolve() for root in preferred if root))

    @staticmethod
    def _probes(root, name, cached):
        wrappers = [root / wrapper for wrapper in _PACK_WRAPPERS]
        yield from (folder / name for folder in wrappers)
        hint = cached.get(name)
        if hint and Path(hint).name == name:
            yield Path(hint)
        yield from (folder / bucket / name for folder in wrappers for bucket in _PACK_BUCKETS)

        # Older client copies can use other bucket names. List only wrapper
        # entries and stat the requested basename under each matching bucket.
        for folder in wrappers:
            try:
                if folder.resolve() != folder:
                    continue
                with os.scandir(folder) as entries:
                    for i, entry in enumerate(entries):
                        if i >= _MAX_BUCKET_ENTRIES:
                            break
                        if (entry.name.lower().startswith(("pak", "pkg"))
                                and entry.name not in _PACK_BUCKETS
                                and entry.is_dir(follow_symlinks=False)):
                            yield folder / entry.name / name
            except OSError:
                continue

    def __call__(self, repo_root, record, extractor, job, deadline):
        meta = record.get("metapack")
        entries = [(record["pack_name"], 0, record.get("pack_size"), record["head"] + record["size"])]
        if meta:
            entries.append((meta["name"], meta["offset"], None, meta["size"]))
        for root in self._roots(repo_root, extractor):
            game._check(job, deadline)
            if not root.is_dir():
                continue
            cached = getattr(extractor, "_pack_index_cache", {}).get(str(root), {})
            for name, offset, exact_size, length in entries:
                if not game._PACK.fullmatch(name):
                    continue
                for path in self._probes(root, name, cached):
                    game._check(job, deadline)
                    if not path.is_relative_to(root):
                        continue
                    try:
                        if not path.is_file() or path.resolve() != path:
                            continue
                        stat = path.stat()
                    except OSError:
                        continue
                    if stat.st_size < offset + length or exact_size is not None and stat.st_size != exact_size:
                        continue
                    return path, {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                  "pack_offset": offset}
        return None, None


def _availability(repo_root, record, output_root, packs):
    if record.get("scene_source") is not None:
        return []
    resources = [record, *record["recolours"]]
    extractor = game._extractor()
    job, deadline = _PreviewJob(), time.monotonic() + 8
    found = [packs(repo_root, item, extractor, job, deadline) for item in resources]
    missing = [item for (source, _), item in zip(found, resources) if source is None]
    if missing:
        signatures = [signature for _, signature in found]
        cached, _ = game._cached_model(output_root, game._selection_identity(record), signatures, record)
        if cached and cached.name == game._tool_name(record):
            return []
    return missing


def _matches_local_identity(repo_root, record, packs, identity):
    if record.get("scene_source") is not None:
        return False
    extractor = game._extractor()
    job, deadline = _PreviewJob(), time.monotonic() + 8
    source, signature = packs(repo_root, record, extractor, job, deadline)
    if source is None:
        return False
    raw = game._plain_section(job, record, source, signature, extractor, deadline)
    return _body_identity(game._tool_body(raw, record["platform"])) == identity


def _unity_selection(path, env, *, repo_root, region, language, platforms, packs):
    identity = _body_identity(env)
    if identity is None:
        return "unknown", None
    owner, prefab, _, _ = identity
    database = Path(repo_root) / "assets/db" / region / "masterdata.db"
    with closing(game._readonly(database)) as db:
        matches = _named_catalog_matches(db, owner, prefab)
        if len(matches) > 1:
            return "ambiguous", None
        if matches:
            return "matched", next(iter(matches))
        hint = _FILENAME_HINT.fullmatch(path.name)
        if not hint or int(hint.group(1)) != owner:
            return "unknown", None
        suit_id, variant = int(hint.group(2)), hint.group(3).lower()
        for platform in platforms:
            try:
                record = game.validate_selection(repo_root, _selection(region, suit_id, variant, platform), language)
                if record["owner"] != owner or not _matches_local_identity(repo_root, record, packs, identity):
                    continue
            except (OSError, ValueError):
                continue
            if record.get("attach_key") or _model_aliases(db, owner, record["model"]) != {(suit_id, variant)}:
                return "ambiguous", None
            return "matched", (suit_id, variant)
    return "unknown", None



def _archive_selection(member, names, env, *, repo_root, region, language, platform, packs):
    identity = _body_identity(env)
    if identity is None:
        return "unknown", None
    owner, prefab, _, _ = identity
    with closing(game._readonly(Path(repo_root) / "assets/db" / region / "masterdata.db")) as db:
        candidates = _named_catalog_matches(db, owner, prefab)
        hints = [_FILENAME_HINT.fullmatch(Path(member).name)]
        hints.extend(_DISPLAY_HINT.match(name) for name in names)
        candidates.update((int(hint.group(2)), hint.group(3).lower()) for hint in hints
                          if hint and int(hint.group(1)) == owner)
        matched = set()
        for suit_id, variant in sorted(candidates):
            try:
                record = game.validate_selection(repo_root, _selection(region, suit_id, variant, platform), language)
                if record["owner"] != owner or not _matches_local_identity(repo_root, record, packs, identity):
                    continue
            except (OSError, ValueError):
                continue
            if record.get("attach_key") or _model_aliases(db, owner, record["model"]) != {(suit_id, variant)}:
                return "ambiguous", None
            matched.add((suit_id, variant))
        if len(matched) > 1:
            return "ambiguous", None
        if matched:
            return "matched", matched.pop()
    return "unknown", None


def _label(repo_root, region, suit_id, owner, language):
    extractor = game._extractor()
    with closing(game._readonly(Path(repo_root) / "assets/db" / region / "masterdata.db")) as db:
        key = db.execute("SELECT name FROM m_suit WHERE id=?", (suit_id,)).fetchone()[0]
    dictionary = game._dictionary(repo_root, region, language)
    try:
        costume = extractor.real_costume_name(dictionary, key) or str(suit_id)
    finally:
        if dictionary:
            dictionary.close()
    member = game._names(extractor).get(owner, str(owner))
    return f"{member} — {costume}"[:240]


def resolve(repo_root, payload, *, language="en", cache_root=None):
    """Return a preview and its private, freshly verified import descriptor."""
    if (not isinstance(payload, dict) or not {"path", "direction", "region"} <= set(payload)
            or set(payload) - {"path", "direction", "region", "packs_dir"}
            or not isinstance(payload["direction"], str) or payload["direction"] not in DIRECTIONS
            or not isinstance(payload["region"], str)):
        raise ValueError("Choose a valid costume bundle, direction, and game region.")
    donor = _checked_path(payload["path"])
    extra = _checked_path(payload["packs_dir"], directory=True) if "packs_dir" in payload else None
    region, _ = game._region(repo_root, payload["region"], language)
    source, target = DIRECTIONS[payload["direction"]]
    cache_root = game_models_dir() if cache_root is None else Path(cache_root)
    packs = _LocalPacks(extra)
    member, names = None, ()
    if donor.suffix.lower() == ".zip":
        raw, member, names = _read_archive_body(donor, source)
    else:
        raw = viewer_mod_sources._read(donor)
    if len(raw) > game.MAX_MODEL_BYTES:
        raise ValueError("The edited costume bundle exceeds the model import limit.")
    try:
        env = game._tool_body(raw, source)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The selected bundle could not be read as a native costume body.") from exc
    result = {"status": "unknown", "message": UNKNOWN, "region": region,
              "source_platform": source, "target_platform": target, "donor_path": donor,
              "donor_sha256": hashlib.sha256(raw).hexdigest(), "packs_dir": extra}
    try:
        status, receipt = (_receipt_selection(donor, result["donor_sha256"], repo_root, cache_root)
                           if member is None else ("unknown", None))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # A stale or malformed provenance chain never becomes a filename match.
        return result
    if receipt:
        if receipt["region"] != region:
            return {**result, "message": WRONG_REGION}
        if receipt.get("platform", source) != source:
            return result
        identity = receipt["suit_id"], receipt["variant"]
    elif status == "ambiguous":
        return {**result, "status": "ambiguous", "message": AMBIGUOUS}
    else:
        if member is None:
            status, identity = _unity_selection(donor, env, repo_root=repo_root, region=region,
                                                language=language, platforms=(source, target), packs=packs)
        else:
            status, identity = _archive_selection(member, names, env, repo_root=repo_root, region=region,
                                                  language=language, platform=source, packs=packs)
        if status != "matched":
            return {**result, "status": status, "message": AMBIGUOUS if status == "ambiguous" else UNKNOWN}
    suit_id, variant = identity
    selection = _selection(region, suit_id, variant, target)
    try:
        record = game.validate_selection(repo_root, selection, language)
    except ValueError:
        return result
    missing = _availability(repo_root, record, cache_root / "transplant-bodies", packs)
    sizes = {item["pack_name"]: item.get("pack_size") for item in missing}
    result.update(status="matched", label=_label(repo_root, region, suit_id, record["owner"], language),
                  selection=selection, record=record, missing=bool(missing),
                  missing_bytes=sum(sizes.values()) if all(size is not None for size in sizes.values()) else None)
    result.pop("message")
    return result


def match(repo_root, payload, *, language="en", cache_root=None):
    result = resolve(repo_root, payload, language=language, cache_root=cache_root)
    return {key: result[key] for key in (
        "status", "message", "region", "source_platform", "target_platform",
        "label", "selection", "missing", "missing_bytes") if key in result}


class _ImportJob:
    def __init__(self, job):
        self.job = job
        self.outputs = []

    def should_stop(self):
        return self.job.should_stop()

    def log(self, line):
        self.job.log(line)

    def progress(self, done, total):
        self.job.progress(done, total)

    def add_output(self, path):
        self.outputs.append(Path(path))


def _import(job, *, repo_root, record, output_root, packs):
    child = _ImportJob(job)
    game.run_import(child, repo_root=repo_root, output_root=output_root, record=record, source_lookup=packs)
    if not child.outputs and job.should_stop():
        raise game.ImportCancelled()
    if len(child.outputs) != 1:
        raise ValueError("The original costume could not be prepared.")
    return child.outputs[0]


def prepare_target(job, *, repo_root, resolved, output_root, download=False):
    """Prepare the chosen native counterpart without publishing an export."""
    if type(download) is not bool or resolved.get("status") != "matched":
        raise ValueError("Choose the original costume and confirm the download setting.")
    record = {**resolved["record"], "download": download}
    return _import(job, repo_root=repo_root, record=record, output_root=output_root,
                   packs=_LocalPacks(resolved["packs_dir"]))


def prepare_source_original(job, *, repo_root, resolved, output_root):
    """Try the original input-platform counterpart, using local sources only."""
    if resolved.get("status") != "matched":
        return None
    record = resolved["record"]
    packs = _LocalPacks(resolved["packs_dir"])
    values = _selection(record["region"], record["suit_id"], record["variant"], resolved["source_platform"])
    try:
        original = game.validate_selection(repo_root, values, record["selection_language"])
        if _availability(repo_root, original, Path(output_root), packs):
            return None
        return _import(job, repo_root=repo_root, record=original, output_root=output_root, packs=packs)
    except (ValueError, OSError, sqlite3.Error):
        return None
