"""Package immutable viewer exports and install their server-bound receipts."""
from collections import OrderedDict
import ast
import copy
import hashlib
import io
from itertools import chain
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile

_PACKAGES = OrderedDict()
_LOCK = threading.RLock()
_PACKAGE_SLOT = threading.BoundedSemaphore(1)
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
PACKAGE_SECONDS = 3600


def discard_failed_export(result, output_root):
    """Remove only this exporter's newly generated directory after failure."""
    if not isinstance(result, dict) or not isinstance(result.get("recipe_path"), str):
        return
    directory = Path(result["recipe_path"]).parent
    if (directory.is_symlink() or not re.fullmatch(r"body-edit-\d{8}-\d{6}-[a-f0-9]{8}", directory.name)
            or directory.resolve().parent != Path(output_root).resolve()):
        return
    shutil.rmtree(directory, ignore_errors=True)


def _hash_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_PACKAGE_BYTES:
        raise ValueError("The saved Mod ZIP is missing or invalid. Create it again.")
    before = path.stat()
    digest, total = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(block)
            if total > MAX_PACKAGE_BYTES:
                raise ValueError("The Mod ZIP exceeds the size limit.")
            digest.update(block)
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or total != before.st_size):
        raise ValueError("The saved Mod ZIP changed while reading. Create it again.")
    return digest.hexdigest(), total


def _check(job):
    if job.should_stop():
        raise ValueError("Mod packaging was cancelled.")


def cached_receipts(context, cache_root):
    """Read only bounded receipts in the app's fixed game-import cache."""
    root = Path(cache_root).resolve()
    selected = {str(Path(row["path"]).resolve()): row["sha256"] for row in context["containers"]}
    result = []
    if not root.is_dir():
        return result
    preserved = [root / (".provenance-" + hashlib.sha256(path.encode()).hexdigest()[:32] + ".json") for path in selected]
    for index, manifest in enumerate(chain(preserved, root.glob(".selection-*.json"))):
        if index >= 256:
            break
        try:
            if manifest.is_symlink() or manifest.stat().st_size > 16 * 1024:
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if manifest.name.startswith(".provenance-"):
                model = Path(data["path"]).resolve()
                record = data.get("record")
            else:
                relative = PurePosixPath(data["model"])
                if relative.is_absolute() or ".." in relative.parts or any(":" in p for p in relative.parts):
                    continue
                model = (root / relative).resolve()
                if not model.is_relative_to(root):
                    continue
                record = data.get("selection_record")
            if selected.get(str(model)) != data.get("sha256"):
                continue
            if isinstance(record, dict):
                result.append({"path": str(model), "sha256": data["sha256"], "record": record})
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            continue
    return result


def remember_export_sources(context, result, *, repo_root, cache_root):
    """Carry verified game identity onto byte-identical preserved originals.

    A recipe opens these copies when re-editing. Their names and locations do
    not establish costume identity; only the original SHA/catalog binding does.
    """
    from webtools.core import viewer_mod_sources
    try:
        bindings = viewer_mod_sources.game_context(context, repo_root, receipts=cached_receipts(context, cache_root))
    except sqlite3.Error:
        return
    originals = result.get("original_paths", [])
    if not bindings or len(originals) != len(context["containers"]):
        return
    root = Path(cache_root)
    if root.is_symlink():
        raise ValueError("The game source receipt folder cannot be a symbolic link.")
    root.mkdir(parents=True, exist_ok=True)
    for binding in bindings:
        index = binding["container"]
        original = Path(originals[index]).resolve()
        digest, size = _hash_file(original)
        if digest != context["containers"][index]["sha256"]:
            raise ValueError("The preserved original no longer matches its game source.")
        # Bind the receipt to the bytes just verified against the session.
        # Re-reading and registering a new hash here could lend the old game
        # identity to a file replaced between those two reads.
        receipt = {"path": str(original), "sha256": digest, "record": copy.deepcopy(binding["record"])}
        key = hashlib.sha256(str(original).encode()).hexdigest()[:32]
        target = root / (".provenance-" + key + ".json")
        if target.is_symlink():
            raise ValueError("The game source receipt cannot be a symbolic link.")
        temporary = root / (".provenance-" + secrets.token_hex(16) + ".part")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(receipt, handle, allow_nan=False)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _manifest_metadata(context, language):
    values = {}
    if len(context["containers"]) != 1:
        return values
    raw = context["containers"][0]["raw"]
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return values
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [entry for entry in archive.infolist() if PurePosixPath(entry.filename).name == "modinstall.txt"]
            if len(entries) != 1 or entries[0].file_size > 64 * 1024:
                return values
            for node in ast.parse(archive.read(entries[0]).decode("utf-8-sig")).body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        values[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError):
        return {}
    name = values.get("costume_name_" + language) or values.get("costume_name_en")
    return {"name": name if isinstance(name, str) else None, "owner": values.get("chara_id"),
            "paired": bool(values.get("costume_file") and values.get("rina_unmask_costume_file"))}


def metadata(context, *, repo_root, cache_root, language="en"):
    """Small UI hints; all packaging identities are verified again on Save."""
    from webtools.core.charinfo import NAMES
    result = {"nameBase": Path(context["containers"][0]["name"]).stem,
              "characterId": None, "requiresCounterpart": False,
              "characters": [{"value": str(key), "label": value} for key, value in NAMES.items()]}
    manifest = _manifest_metadata(context, language)
    if manifest.get("name"):
        result["nameBase"] = manifest["name"][:120]
    if type(manifest.get("owner")) is int and manifest["owner"] in NAMES:
        result["characterId"] = manifest["owner"]
        result["requiresCounterpart"] = manifest["owner"] == 209 and not manifest.get("paired")
    try:
        from webtools.core import game_models, viewer_mod_sources
        bindings = viewer_mod_sources.game_context(context, repo_root, receipts=cached_receipts(context, cache_root))
        if len(bindings) == 1:
            record = bindings[0]["record"]
            result["characterId"] = record["owner"]
            result["requiresCounterpart"] = False
            database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
            try:
                row = database.execute("SELECT name FROM m_suit WHERE id=?", (record["suit_id"],)).fetchone()
            finally:
                database.close()
            dictionary = game_models._dictionary(repo_root, record["region"], language)
            try:
                label = game_models._extractor().real_costume_name(dictionary, row[0]) if dictionary and row else None
                if label:
                    result["nameBase"] = str(label)[:120]
            finally:
                if dictionary:
                    dictionary.close()
        elif result["characterId"] is None:
            # Rina's board texture has a distinct, observed character identity;
            # no costume/suit pairing is inferred from that texture hint.
            _, sources = viewer_mod_sources._snapshots(context)
            facts = [viewer_mod_sources._model_facts(source["raw"]) for source in sources]
            if facts and all(item["owner"] == 209 for item in facts):
                result["characterId"] = 209
                result["requiresCounterpart"] = True
    except (ImportError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # A naming hint must not disable ordinary model/recipe exports.
        pass
    return result


def validate_options(display_name, character_id, counterpart_path, selected_variant):
    if (not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 120 or
            any(ord(char) < 32 or ord(char) == 127 for char in display_name)):
        raise ValueError("Enter a Mod name between 1 and 120 characters without line breaks.")
    from webtools.core.charinfo import NAMES
    if character_id is not None and (type(character_id) is not int or character_id not in NAMES):
        raise ValueError("Choose a valid character for the Mod ZIP.")
    if counterpart_path is not None and (not isinstance(counterpart_path, str) or not counterpart_path):
        raise ValueError("Choose a valid Rina counterpart file.")
    if selected_variant not in (None, "primary", "unmasked"):
        raise ValueError("Choose which Rina variant is being edited.")
    if counterpart_path and selected_variant is None:
        raise ValueError("Choose whether the edited Rina model uses the board.")
    if selected_variant and not counterpart_path:
        raise ValueError("Choose the other Rina model file, or keep automatic variant selection.")
    return display_name.strip()


def create_package(token, state, *, output_root, repo_root, cache_root, display_name,
                   character_id=None, counterpart_path=None, selected_variant=None, thumbnail_token="", job):
    from webtools.core import model_edits, viewer_mod_package, viewer_mod_sources, viewer_mod_pair_edits, viewer_scene_roles
    name = validate_options(display_name, character_id, counterpart_path, selected_variant)
    if not _PACKAGE_SLOT.acquire(blocking=False):
        raise ValueError("Another Mod ZIP is being prepared. Try again shortly.")
    exported_result = None
    try:
        _check(job)
        context = model_edits.mod_source_context(token)
        normalized = model_edits.validate_state(token, state)
        from webtools.core import viewer_thumbnails
        thumbnail = viewer_thumbnails.for_viewer_package(thumbnail_token, token, normalized,
            character_id, counterpart_path, selected_variant)
        result = model_edits.export(token, normalized, output_root, log=job.log)
        exported_result = result
        remember_export_sources(context, result, repo_root=repo_root, cache_root=cache_root)
        _check(job)
        selection = {"counterpart_path": counterpart_path, "selected_variant": selected_variant} if counterpart_path else None
        pair = viewer_mod_sources.resolve_pair(context, result, repo_root=repo_root,
            output_root=cache_root, job=job, selection=selection, receipts=cached_receipts(context, cache_root))
        paired = (viewer_mod_pair_edits.apply_pair_edits(context, result, normalized, pair=pair, job=job)
                  if model_edits.has_changes(normalized) else {"result": result, "pair": pair, "summary": []})
        result, pair = paired["result"], paired["pair"]
        if paired.get("summary"):
            result["paired_edits"] = paired["summary"]
        _check(job)
        packed = viewer_mod_package.package_saved_export(result, Path(result["recipe_path"]).parent / "mod",
            display_name=name, chara_id=character_id, pair=pair,
            log=job.log, should_stop=job.should_stop,
            **({"thumbnail": thumbnail} if thumbnail is not None else {}))
        if viewer_scene_roles.should_package(context, normalized, packed, token):
            packed = viewer_scene_roles.package_scene(context, result, normalized, pair=pair, packed=packed,
                token=token, repo_root=repo_root, receipts=cached_receipts(context, cache_root), log=job.log)
        _check(job)
        path = str(Path(packed["package_path"]).resolve())
        digest, size = _hash_file(path)
        if packed.get("sha256") != digest or packed.get("bytes") != size:
            raise ValueError("The Mod ZIP failed its completed-output check.")
        package_token = secrets.token_hex(16)
        public = {"token": package_token, "package_path": path, "sha256": digest, "bytes": size,
                  "character_id": packed.get("chara_id", packed.get("owner")),
                  "platform": packed.get("platform"),
                  "variants": [{"id": key, "label": value} for key, value in packed.get("variant_labels", {}).items()],
                  "display_name": name, "installable": True}
        if packed.get("format"):
            public.update(format=packed["format"], version=packed["version"])
        if packed.get("thumbnail"):
            public["thumbnail"] = copy.deepcopy(packed["thumbnail"])
        if paired.get("summary"):
            result["paired_edits"] = paired["summary"]
        receipt = {"public": copy.deepcopy(public), "source_token": token, "state": normalized,
                   "created": time.monotonic(), "status": "ready"}
        with _LOCK:
            for old_token, old in list(_PACKAGES.items()):
                if time.monotonic() - old["created"] > PACKAGE_SECONDS and old["status"] != "installing":
                    del _PACKAGES[old_token]
            _PACKAGES[package_token] = receipt
            while len(_PACKAGES) > 64:
                removable = next((key for key, row in _PACKAGES.items() if row["status"] != "installing"), None)
                if removable is None:
                    break
                del _PACKAGES[removable]
        result["mod_package"] = public
        result["output_paths"] = list(dict.fromkeys(result["output_paths"] + [path]))
        return result
    except Exception:
        discard_failed_export(exported_result, output_root)
        raise
    finally:
        _PACKAGE_SLOT.release()


def _receipt(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ValueError("Create a Mod ZIP before adding it to the game.")
    receipt = _PACKAGES.get(token)
    if receipt is None or time.monotonic() - receipt["created"] > PACKAGE_SECONDS:
        raise ValueError("The Mod ZIP installation session expired. Create it again.")
    if receipt["status"] != "ready":
        raise ValueError("This Mod ZIP is already being added or has been installed. Create a new copy to add it again.")
    return receipt


def validate_install(token):
    with _LOCK:
        receipt = copy.deepcopy(_receipt(token))
    digest, size = _hash_file(receipt["public"]["package_path"])
    if digest != receipt["public"]["sha256"] or size != receipt["public"]["bytes"]:
        raise ValueError("The Mod ZIP changed after saving. Create it again before adding it.")
    return receipt


def install_package(token, *, repo_root, library_root, job):
    """Use the existing backed-up installer and native owned-server controller."""
    from database_maintenance import guard
    from adminui import serverctl
    from adminui.tools.installers import run_costume_file
    root = Path(repo_root).resolve()
    if not (root / "serverdata.db").is_file() or not (root / "assets/db/gl/masterdata.db").is_file():
        raise ValueError("Prepare the Elichika server data before adding a costume.")
    with _LOCK:
        receipt = _receipt(token)
        receipt["status"] = "installing"
        public = copy.deepcopy(receipt["public"])
    try:
        _check(job)
        digest, size = _hash_file(public["package_path"])
        if digest != public["sha256"] or size != public["bytes"]:
            raise ValueError("The Mod ZIP changed after saving. Create it again before adding it.")
        target_root = Path(library_root).resolve() / "suit"
        target_root.mkdir(parents=True, exist_ok=True)
        if target_root.is_symlink():
            raise ValueError("The costume installation folder cannot be a symbolic link.")
        source = Path(public["package_path"])
        stem = source.stem.encode("utf-8")[:180].decode("utf-8", errors="ignore")
        target = target_root / (stem + "-" + secrets.token_hex(4) + ".zip")
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if _hash_file(target) != (digest, size):
            target.unlink(missing_ok=True)
            raise ValueError("The install copy does not match the saved Mod ZIP.")
        _check(job)
        controller = serverctl._controller
        was_running = bool(controller and controller.is_running())
        # Native launchers already wrap this callback in whole_job_server and a
        # database guard. The guard is reentrant on this OS thread and also
        # protects an ordinary standalone webtools job manager.
        with guard(root):
            summary = run_costume_file(job, str(target), digest, restart_server=controller is not None)
        if job.should_stop():
            raise ValueError("Costume installation was cancelled. Check the server console before restarting.")
        with _LOCK:
            receipt["status"] = "installed"
        return {"installed": True, "mod_package": public, "installed_package_path": str(target),
                "was_running": was_running, "summary": str(summary)}
    except BaseException:
        with _LOCK:
            receipt["status"] = "failed"
        raise
