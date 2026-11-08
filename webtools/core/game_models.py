"""Open a selected game costume without changing its catalogs or source packs.

Catalog identities come from this server's GL/JP databases. Selected bundles
are decrypted with the same extractor as Server content, into a separate,
verified extraction cache. Requests never supply filesystem paths or URLs.
"""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_OPTIONS = 200
IMPORT_SECONDS = 90
_PACK = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_SUIT = re.compile(r"suit:([1-9][0-9]{0,11})\Z")
_IMPORT_SLOT = threading.BoundedSemaphore(1)


class ImportCancelled(Exception):
    pass


def _extractor():
    try:
        import llas_asset_extractor
        return llas_asset_extractor
    except ImportError as exc:
        raise ValueError("Game assets are unavailable. Start or prepare the server data first.") from exc


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _installed_scene(root, suit_id):
    """The application owns this resolver; requests never provide its path."""
    root = Path(root).resolve()
    if (root / "costume_scene_installer.py").is_file() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from costume_scene_installer import installed_scene_source
    except ImportError:
        return None
    return installed_scene_source(suit_id, root=root)


def _regions(root):
    return [region for region in ("gl", "jp")
            if (Path(root) / "assets/db" / region / "masterdata.db").is_file()]


def _region(root, requested, language):
    regions = _regions(root)
    if requested and requested not in ("gl", "jp"):
        raise ValueError("Choose a valid game region.")
    if not regions:
        raise ValueError("Game assets are unavailable. Start or prepare the server data first.")
    if requested:
        if requested not in regions:
            raise ValueError("The selected game region is unavailable.")
        return requested, regions
    # Match the running server's game-data locale before the independent UI locale.
    locale = language
    config = Path(root) / "config.json"
    try:
        if config.stat().st_size <= 1024 * 1024:
            value = json.loads(config.read_text(encoding="utf-8"))
            configured = value.get("locales") if isinstance(value, dict) else None
            if isinstance(configured, str) and configured.strip():
                locale = configured.strip().split(",")[0].strip()
            elif isinstance(configured, list) and configured and isinstance(configured[0], str):
                locale = configured[0]
    except (OSError, ValueError):
        pass
    preferred = "jp" if locale in ("ja", "jp") else "gl"
    return preferred if preferred in regions else regions[0], regions


def _names(extractor):
    try:
        import character_names
        return character_names.CHARACTERS
    except ImportError:
        return extractor.CHARACTERS


def _dictionary(root, region, language):
    directory = Path(root) / "assets/db" / region
    for code in dict.fromkeys([language, "ja" if region == "jp" else "en", "ko", "en", "ja", "zh"]):
        path = directory / f"dictionary_{code}_k.db"
        if path.is_file():
            return _readonly(path)
    return None


def _views(db, suit_id, owner, canonical_candidates=()):
    result = [{"value": "primary", "label": "Default costume"}]
    if owner == 209:
        try:
            model = db.execute("SELECT model_asset_path FROM m_suit WHERE id=?", (suit_id,)).fetchone()
            original_id, _ = _attachment(db, suit_id, owner, model[0])
            row = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id IN (?,?) AND view_status=2 LIMIT 1", (suit_id, original_id)).fetchone()
            if row and row[0]:
                result.append({"value": "unmasked", "label": "Without mask"})
        except sqlite3.Error:
            pass
    elif suit_id in canonical_candidates:
        try:
            row = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=2", (suit_id,)).fetchone()
            if row and row[0]:
                result.append({"value": "unmasked", "label": "Without mask"})
        except sqlite3.Error:
            pass  # Selection still verifies and reports invalid provenance.
    return result


def catalog(root, *, language="en", region="", character="", search=""):
    """Bounded character/costume picker, using source-region dictionaries."""
    if not isinstance(search, str) or len(search) > 120 or not isinstance(character, str) or len(character) > 8:
        raise ValueError("The costume search is too long.")
    if character and (not character.isascii() or not character.isdigit()):
        raise ValueError("Choose a valid character.")
    region, regions = _region(root, region, language)
    extractor = _extractor()
    names = _names(extractor)
    source_root = Path(root).resolve()
    if (source_root / "costume_scene_clones.py").is_file() and str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        from costume_scene_clones import canonical_clone_candidates
    except ImportError:
        canonical_candidates = set()
    else:
        canonical_candidates = canonical_clone_candidates(root=source_root)
    with closing(_readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        members = [int(row[0]) for row in db.execute("SELECT DISTINCT member_m_id FROM m_suit WHERE model_asset_path IS NOT NULL AND model_asset_path<>'' ORDER BY member_m_id") if isinstance(row[0], int) and 0 < row[0] < 10000]
        try:
            oldest = db.execute("SELECT display_order FROM m_suit WHERE id=100011001").fetchone()
            median = db.execute("SELECT display_order FROM m_suit ORDER BY display_order LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM m_suit)").fetchone()
            order = "ASC" if oldest and median and oldest[0] > median[0] else "DESC"
        except sqlite3.Error:
            order = "DESC"
        rows = []
        if search.strip() or character:
            condition, values = ("", ()) if search.strip() else ("AND member_m_id=?", (int(character),))
            rows = db.execute("SELECT id,member_m_id,name FROM m_suit WHERE model_asset_path IS NOT NULL AND model_asset_path<>'' " + condition + f" ORDER BY (name LIKE '%_cloned') DESC,display_order {order},id DESC LIMIT 20000", values).fetchall()
        options = []
        dictionary = _dictionary(root, region, language)
        try:
            query = search.strip().casefold()
            for suit, owner, key in rows:
                name = extractor.real_costume_name(dictionary, key) or str(suit)
                member = names.get(owner, str(owner))
                if query and query not in name.casefold() and query not in member.casefold():
                    continue
                options.append({"value": f"suit:{suit}", "label": f"{member} — {name}" if query else name,
                                "variants": _views(db, suit, owner, canonical_candidates)})
                if len(options) >= MAX_OPTIONS:
                    break
        finally:
            if dictionary:
                dictionary.close()
    return {"region": region, "regions": [{"value": r, "label": "Global (GL)" if r == "gl" else "Japan (JP)"} for r in regions],
            "characters": [{"value": str(owner), "label": names.get(owner, str(owner))} for owner in members],
            "costumes": options, "limit": MAX_OPTIONS}


def _attachment(db, suit_id, owner, model):
    """Resolve the game's exact colour attachment, never infer it from suit IDs."""
    original, key, seen = suit_id, None, set()
    for _ in range(8):
        if original in seen:
            raise ValueError("The costume colour mapping contains a loop.")
        seen.add(original)
        try:
            row = db.execute("SELECT original_suit_master_id,attach_key FROM m_suit_attach WHERE suit_master_id=?", (original,)).fetchone()
        except sqlite3.Error:
            row = None
        if row is None:
            return original, key
        source_id, next_key = row
        if not isinstance(source_id, int) or not isinstance(next_key, str) or not re.fullmatch(r"c[1-9][0-9]{0,2}", next_key):
            raise ValueError("The costume colour mapping is invalid.")
        source = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (source_id,)).fetchone()
        if source is None or source != (owner, model) or key is not None and key != next_key:
            raise ValueError("The costume colour mapping does not match its original model.")
        original, key = source_id, next_key
    raise ValueError("The costume colour mapping is too deep.")


def _descriptor(db, model, suit_id):
    found = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=? LIMIT 1", (model,)).fetchone()
    if not found:
        return None
    record = dict(zip(("pack_name", "head", "size", "key1", "key2"), found))
    if not isinstance(record["pack_name"], str) or not _PACK.fullmatch(record["pack_name"]) or any(not isinstance(record[key], int) for key in ("head", "size", "key1", "key2")) or record["head"] < 0 or not 0 < record["size"] <= MAX_MODEL_BYTES:
        raise ValueError("The selected game asset has invalid package metadata.")
    record.update(model=model, pack_size=None, metapack=None)
    try:
        mapping = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE package_key=? AND pack_name=? LIMIT 1", (f"suit:{suit_id}", record["pack_name"])).fetchone()
    except sqlite3.Error:
        mapping = None
    if mapping is None:
        try:
            mapping = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (record["pack_name"],)).fetchone()
        except sqlite3.Error:
            try:
                size = db.execute("SELECT file_size FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (record["pack_name"],)).fetchone()
                mapping = (size[0], None, 0) if size else None
            except sqlite3.Error:
                mapping = None
    if mapping:
        size, name, offset = mapping
        if not isinstance(size, int) or size < record["head"] + record["size"]:
            raise ValueError("The selected game asset has an invalid package size.")
        record["pack_size"] = size
        if name:
            if not isinstance(name, str) or not _PACK.fullmatch(name) or not isinstance(offset, int) or offset < 0:
                raise ValueError("The game metapack mapping is invalid.")
            record["metapack"] = {"name": name, "offset": offset, "size": size}
    return record


def validate_selection(root, params, language="en"):
    if not isinstance(params, dict) or set(params) != {"region", "suit", "variant", "download"}:
        raise ValueError("Unsupported game asset request.")
    if not isinstance(params["download"], bool) or not isinstance(params["region"], str) or not isinstance(params["suit"], str):
        raise ValueError("Choose a valid costume and download option.")
    match = _SUIT.fullmatch(params["suit"])
    if not match or params["variant"] not in ("primary", "unmasked"):
        raise ValueError("Choose a valid costume variant.")
    region, _ = _region(root, params["region"], language)
    suit_id = int(match.group(1))
    with closing(_readonly(Path(root) / "assets/db" / region / "masterdata.db")) as db:
        row = db.execute("SELECT member_m_id,name,model_asset_path FROM m_suit WHERE id=?", (suit_id,)).fetchone()
        if not row or not row[2] or not isinstance(row[0], int):
            raise ValueError("The selected costume is no longer available. Refresh the list.")
        owner, name, model = row
        scene = _installed_scene(root, suit_id)
        if scene is not None:
            if scene.get("target_member_id", 209) != owner:
                raise ValueError("The canonical costume owner does not match its installed archive.")
            return {"region": region, "suit_id": suit_id, "owner": owner, "variant": params["variant"],
                    "download": params["download"], "scene_source": scene, "model": model,
                    "attach_key": None, "recolours": []}
        if owner == 209:
            try:
                board = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=1", (suit_id,)).fetchone()
            except sqlite3.Error:
                board = None
            if board and board[0] != model:
                raise ValueError("This costume has separate Navi/MV models but no verified canonical archive. Open its original scene Mod ZIP to edit it.")
        original_id, attach_key = _attachment(db, suit_id, owner, model)
        base_model = model
        if params["variant"] == "unmasked":
            if owner != 209:
                raise ValueError("This costume has no unmasked model.")
            try:
                unmasked = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id IN (?,?) AND view_status=2 ORDER BY CASE WHEN suit_master_id=? THEN 0 ELSE 1 END LIMIT 1", (suit_id, original_id, suit_id)).fetchone()
            except sqlite3.Error:
                unmasked = None
            if not unmasked or not unmasked[0]:
                raise ValueError("This costume has no unmasked model.")
            model = unmasked[0]
    directory = Path(root) / "assets/db" / region
    catalogs = sorted(directory.glob("asset_a_*.db"), key=lambda p: (p.name != f"asset_a_{language}.db", p.name != "asset_a_en.db", p.name))
    for path in catalogs:
        with closing(_readonly(path)) as db:
            record = _descriptor(db, model, suit_id)
            if record is None:
                continue
            record.update(region=region, suit_id=suit_id, owner=owner, variant=params["variant"], download=params["download"], attach_key=attach_key, recolours=[])
            if attach_key:
                from adminui.tools.assets_extract import _recolour_dep_paths
                # Unmasked bodies can share the primary body's colour bundle.
                dependencies = list(dict.fromkeys(_recolour_dep_paths(db, model) + (_recolour_dep_paths(db, base_model) if model != base_model else [])))
                if not dependencies or len(dependencies) > 4:
                    raise ValueError("The selected costume colour assets are unavailable.")
                record["recolours"] = [_descriptor(db, dependency, suit_id) for dependency in dependencies]
                if any(item is None for item in record["recolours"]) or sum(item["size"] for item in record["recolours"]) + record["size"] > 128 * 1024 * 1024:
                    raise ValueError("The selected costume colour exceeds the model import limit.")
            return record
    raise ValueError("This costume is missing from the Android asset catalog.")


def _check(job, deadline):
    if job.should_stop():
        raise ImportCancelled()
    if time.monotonic() >= deadline:
        raise ValueError("Loading the game asset took too long. Try again.")


def _safe_directory(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("The game model cache must use its real folder path.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _source(root, record, extractor, job, deadline):
    game = [path for path, status in extractor.detect_game_candidates() if status == "found"]
    for directory in extractor.build_pack_roots(str(root), None, game):
        _check(job, deadline)
        real_root = Path(directory).resolve()
        candidates = [(record["pack_name"], 0, record.get("pack_size"), False)]
        meta = record.get("metapack")
        if meta:
            candidates.append((meta["name"], meta["offset"], None, True))
        for name, offset, exact_size, is_meta in candidates:
            find = getattr(extractor, "indexed_pack_file", None)
            if find is not None:
                candidate = find(str(real_root), name)
            else:
                # Standalone webtools can also meet an older extractor. Keep
                # its index fallback while still preferring fresh flat packs.
                flat = real_root / name
                candidate = flat if flat.is_file() else extractor.build_pack_index(str(real_root)).get(name)
            if not candidate:
                continue
            candidate = Path(candidate).resolve()
            if not candidate.is_relative_to(real_root) or not candidate.is_file():
                continue
            stat = candidate.stat()
            required = offset + (meta["size"] if is_meta else record["head"] + record["size"])
            if stat.st_size < required or exact_size is not None and stat.st_size != exact_size:
                continue
            return candidate, {"path": str(candidate), "size": stat.st_size,
                               "mtime_ns": stat.st_mtime_ns, "pack_offset": offset}
    return None, None


def _cache_hit(root, identity, signature):
    manifest = root / (".selection-" + identity + ".json")
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 8192:
            return None
        value = json.loads(manifest.read_text())
        relative = value["model"]
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            return None
        model = root / relative
        if model.is_symlink() or not model.resolve().is_relative_to(root) or not model.is_file() or not 0 < model.stat().st_size <= MAX_MODEL_BYTES:
            return None
        if signature is not None and value.get("source") != signature:
            return None
        if _sha(model) != value.get("sha256"):
            return None
        return model
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _metapack_download(url, offset, size, deadline):
    """Fetch only the selected pack's bounded HTTP byte range when possible."""
    from urllib.request import Request, urlopen
    from webtools.core.model_faces import FaceUnavailable, _DOWNLOAD_SLOT
    # Share the existing global socket slot: timed-out DNS can never grow an
    # unbounded queue of late workers or publish files after cancellation.
    if not _DOWNLOAD_SLOT.acquire(blocking=False):
        raise ValueError("Another asset download is still finishing. Try again shortly.")
    result, done = {}, threading.Event()
    def worker():
        try:
            request = Request(url, headers={"User-Agent": "Elichika model viewer", "Range": f"bytes={offset}-{offset + size - 1}", "Accept-Encoding": "identity"})
            with urlopen(request, timeout=min(8, max(1, deadline - time.monotonic()))) as response:
                final = urlsplit(response.geturl())
                if final.scheme != "https" or not final.netloc or final.username or final.password:
                    raise ValueError("The game asset server redirected to an invalid address.")
                partial = response.status == 206
                if partial:
                    header = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", header)
                    if not match or int(match[1]) != offset or int(match[2]) != offset + size - 1 or int(match[3]) < offset + size:
                        raise ValueError("The game asset server returned an invalid package range.")
                bound = size if partial else MAX_DOWNLOAD_BYTES
                length = response.headers.get("Content-Length")
                if length is not None and (int(length) > bound or partial and int(length) != size):
                    raise ValueError("The game metapack exceeds the model download limit.")
                chunks, total = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("Loading the game asset took too long. Try again.")
                    block = response.read(min(65536, bound - total + 1))
                    if not block:
                        break
                    total += len(block)
                    if total > bound:
                        raise ValueError("The game metapack exceeds the model download limit.")
                    chunks.append(block)
                packed = b"".join(chunks)
                value = packed if partial else packed[offset:offset + size]
                if len(value) != size:
                    raise ValueError("The game metapack section is incomplete.")
                result["value"] = value
        except Exception as exc:
            result["error"] = exc
        finally:
            _DOWNLOAD_SLOT.release(); done.set()
    threading.Thread(target=worker, name="game-metapack-download", daemon=True).start()
    if not done.wait(max(0, deadline - time.monotonic())):
        raise ValueError("Loading the game asset took too long. Try again.")
    if "error" in result:
        raise result["error"]
    return result["value"]


def _remote_pack(record, extractor, job, deadline):
    from urllib.error import HTTPError
    from webtools.core.model_faces import _download_with_deadline
    base = extractor.DEFAULT_CDN_BASE
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The original game asset server must use HTTPS.")
    expected = record.get("pack_size")
    if expected is not None and expected > MAX_DOWNLOAD_BYTES:
        raise ValueError("The game pack exceeds the model download limit.")
    try:
        return _download_with_deadline(base.rstrip("/") + "/" + record["pack_name"], expected, deadline, MAX_DOWNLOAD_BYTES)
    except HTTPError as exc:
        if exc.code != 404 or not record.get("metapack"):
            raise
    _check(job, deadline)
    mapping = record["metapack"]
    job.log("Reading the selected pack from its metapack…")
    return _metapack_download(base.rstrip("/") + "/" + mapping["name"], mapping["offset"], mapping["size"], deadline)


def _plain_section(job, record, source, signature, extractor, deadline):
    if source:
        job.log("Reading the downloaded game pack…")
        with open(source, "rb") as handle:
            handle.seek(signature["pack_offset"] + record["head"])
            section = handle.read(record["size"])
        stat = source.stat()
        if {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                "pack_offset": signature["pack_offset"]} != signature:
            raise ValueError("The game pack changed while reading. Try again.")
    else:
        job.log("Downloading the missing game pack…")
        packed = _remote_pack(record, extractor, job, deadline)
        section = packed[record["head"]:record["head"] + record["size"]]
    _check(job, deadline)
    if len(section) != record["size"]:
        raise ValueError("The game model section is incomplete.")
    data = bytearray(section)
    extractor.decrypt_section(data, extractor.FIXED_KEY0, record["key1"], record["key2"])
    from webtools.core.model_viewer import _preflight_bundle
    _preflight_bundle(data)
    return data


def run_import(job, *, repo_root, output_root, record):
    """One exact selected costume, with colour and unmasked variants preserved."""
    if not _IMPORT_SLOT.acquire(blocking=False):
        raise ValueError("Another game model is being prepared. Try again shortly.")
    temporary, temporary_manifest = None, None
    try:
        deadline = time.monotonic() + IMPORT_SECONDS
        root = _safe_directory(Path(output_root))
        _check(job, deadline)
        if record.get("scene_source") is not None:
            scene = _installed_scene(repo_root, record["suit_id"])
            if scene is None or scene != record["scene_source"]:
                raise ValueError("The installed scene costume changed. Refresh the game asset list.")
            source = Path(scene["archive_path"])
            destination = root / ("scene-" + scene["sha256"] + "-" + record["variant"] + ".zip")
            if destination.is_symlink():
                raise ValueError("The canonical scene cache cannot be a symbolic link.")
            if destination.exists():
                if _sha(destination) != scene["sha256"]:
                    raise ValueError("The cached canonical scene package changed.")
            else:
                with source.open("rb") as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            if _sha(destination) != scene["sha256"]:
                destination.unlink(missing_ok=True)
                raise ValueError("The canonical scene package changed while copying.")
            _check(job, deadline)
            job.add_output(str(destination))
            job.progress(1, 1)
            return "Canonical Rina scene costume prepared for re-editing."
        extractor = _extractor()
        resources = [record] + record["recolours"]
        found = [_source(repo_root, item, extractor, job, deadline) for item in resources]
        signatures = [signature for _, signature in found]
        identity = hashlib.sha256(json.dumps({key: value for key, value in record.items() if key != "download"}, sort_keys=True).encode()).hexdigest()[:32]
        cached = _cache_hit(root, identity, signatures)
        if cached:
            _check(job, deadline)
            from webtools.core.viewer_mod_sources import register_game_import
            # Upgrade an existing cache receipt without changing the model.
            receipt_path = root / (".selection-" + identity + ".json")
            receipt = json.loads(receipt_path.read_text())
            register_game_import(cached, record, expected_sha256=receipt["sha256"])
            receipt["selection_record"] = record
            fd, receipt_name = tempfile.mkstemp(prefix=".selection-", suffix=".part", dir=root)
            temporary_manifest = Path(receipt_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(receipt, handle, allow_nan=False)
            _check(job, deadline)
            os.replace(temporary_manifest, receipt_path)
            temporary_manifest = None
            job.log("Using the previously extracted game model.")
            job.add_output(cached)
            return "Game model ready."
        if not record["download"] and any(source is None for source, _ in found):
            raise ValueError("The game pack is missing. Enable Download missing assets or download the game data first.")
        total = len(resources) + 2
        job.progress(0, total)
        temporary = Path(tempfile.mkdtemp(prefix=f"{record['region']}-{record['suit_id']}-", dir=root))
        source, signature = found[0]
        data = _plain_section(job, record, source, signature, extractor, deadline)
        name = f"ch{record['owner']:04}_suit{record['suit_id']}_{record['variant']}.unity"
        output = temporary / name
        if record["attach_key"]:
            from adminui.tools.assets_extract import _composite_recolour
            base = temporary / ".base.unity"
            base.write_bytes(data)
            variants = []
            for index, dependency in enumerate(record["recolours"], 1):
                _check(job, deadline)
                job.progress(index, total)
                source, signature = found[index]
                variant_data = _plain_section(job, dependency, source, signature, extractor, deadline)
                variant_file = temporary / f".colour-{index}.unity"
                variant_file.write_bytes(variant_data)
                variants.append(variant_file)
            def log(line):
                _check(job, deadline)
                job.log(line)
            if _composite_recolour(base, variants, output, attach_key=record["attach_key"], log=log) <= 0:
                raise ValueError("The selected costume colour could not be applied. The base colour was not substituted.")
            for path in temporary.iterdir():
                if path != output:
                    path.unlink()
        else:
            with open(output, "xb") as handle:
                handle.write(data)
        _check(job, deadline)
        from webtools.core.model_viewer import _preflight_bundle
        _preflight_bundle(output.read_bytes())
        manifest = {"model": str(output.relative_to(root)), "sha256": _sha(output),
                    "source": signatures, "selection_record": record}
        descriptor, temporary_name = tempfile.mkstemp(prefix=".selection-", suffix=".part", dir=root)
        temporary_manifest = Path(temporary_name)
        destination_manifest = root / (".selection-" + identity + ".json")
        if destination_manifest.is_symlink():
            os.close(descriptor)
            raise ValueError("The game model cache contains a linked file.")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        _check(job, deadline)
        os.replace(temporary_manifest, destination_manifest)
        temporary_manifest = None
        from webtools.core.viewer_mod_sources import register_game_import
        register_game_import(output, record, expected_sha256=manifest["sha256"])
        job.progress(total, total)
        job.add_output(output)
        temporary = None
        job.log("Game model ready.")
        return "Game model ready."
    except ImportCancelled:
        job.log("Cancelled")
        return "Cancelled"
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
        _IMPORT_SLOT.release()
