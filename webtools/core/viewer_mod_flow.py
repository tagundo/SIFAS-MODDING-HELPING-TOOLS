"""Package immutable viewer exports and install their server-bound receipts."""
from collections import OrderedDict
import ast
import copy
import hashlib
import io
from itertools import chain, islice
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
    if (directory.is_symlink() or not re.fullmatch(r"(?:body|mesh)-edit-\d{8}-\d{6}-[a-f0-9]{8}", directory.name)
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


MAX_RECEIPT_ENTRIES = 16384


def _receipt_roots(cache_root):
    from .viewer_cache import legacy_cache_roots
    root = Path(cache_root).resolve()
    bases = (root, *legacy_cache_roots(root, "models"))
    return [candidate for base in bases for candidate in (base, base / "transplant-bodies")
            if candidate.is_dir() and not candidate.is_symlink() and candidate.resolve() == candidate]


def _provenance(receipt_root, path):
    return receipt_root / (".provenance-" + hashlib.sha256(path.encode()).hexdigest()[:32] + ".json")


def _receipt_row(receipt_root, manifest, selected):
    """One bounded receipt that binds a selected path to its exact SHA."""
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 16 * 1024:
            return None
        with manifest.open("rb") as handle:
            encoded = handle.read(16 * 1024 + 1)
        if len(encoded) > 16 * 1024:
            return None
        data = json.loads(encoded.decode("utf-8"))
        if manifest.name.startswith(".provenance-"):
            model = Path(data["path"]).resolve()
            record = data.get("record")
        else:
            relative = PurePosixPath(data["model"])
            if relative.is_absolute() or ".." in relative.parts or any(":" in p for p in relative.parts):
                return None
            model = (receipt_root / relative).resolve()
            if not model.is_relative_to(receipt_root):
                return None
            record = data.get("selection_record")
        if selected.get(str(model)) != data.get("sha256"):
            return None
        if isinstance(record, dict):
            return {"path": str(model), "sha256": data["sha256"], "record": record}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        pass
    return None


def cached_receipts(context, cache_root):
    """Read bounded, selected-SHA receipts in fixed current/legacy caches."""
    selected = {str(Path(row["path"]).resolve()): row["sha256"] for row in context["containers"]}
    result = []
    roots = _receipt_roots(cache_root)
    if not roots:
        return result
    # A specifically selected old cache file should not be starved behind a
    # full new cache. The total bound still covers all roots together.
    roots.sort(key=lambda candidate: not any(Path(path).is_relative_to(candidate) for path in selected))
    preserved = ((candidate, _provenance(candidate, path)) for candidate in roots for path in selected)
    def selections():
        for candidate in roots:
            try:
                for manifest in islice(candidate.iterdir(), 2048):
                    if manifest.name.startswith(".selection-") and manifest.name.endswith(".json"):
                        yield candidate, manifest
            except OSError:
                continue
    for index, (receipt_root, manifest) in enumerate(chain(preserved, selections())):
        if index >= 256:
            break
        row = _receipt_row(receipt_root, manifest, selected)
        if row is not None:
            result.append(row)
    return result


def stored_receipt(path, sha256, cache_root):
    """The receipt that binds one model's exact bytes, however full the cache.

    A preserved original's receipt is named after its path. A Game-assets
    model's selection receipt is in the cache folder that holds the model, so
    only such folders are listed, and only their receipts are read.
    """
    model = str(Path(path).resolve())
    selected = {model: sha256}
    roots = _receipt_roots(cache_root)
    for receipt_root in roots:
        row = _receipt_row(receipt_root, _provenance(receipt_root, model), selected)
        if row is not None:
            return row
    for receipt_root in roots:
        if not Path(model).is_relative_to(receipt_root):
            continue
        try:
            for manifest in islice(receipt_root.iterdir(), MAX_RECEIPT_ENTRIES):
                if manifest.name.startswith(".selection-") and manifest.name.endswith(".json"):
                    row = _receipt_row(receipt_root, manifest, selected)
                    if row is not None:
                        return row
        except OSError:
            continue
    return None


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
    from .member_identity import member_from_native
    owner = (values.get("chara_id_append") if values.get("chara_id_append") is not None
             else member_from_native(values.get("chara_id")))
    name = values.get("costume_name_" + language) or values.get("costume_name_en")
    return {"name": name if isinstance(name, str) else None, "owner": owner,
            "paired": bool(values.get("costume_file") and values.get("rina_unmask_costume_file")),
            "has_face": any(isinstance(values.get(key), str) and bool(values[key])
                            for key in ("costume_facedynamic_file", "costume_facedynamic_file_ios"))}


def metadata(context, *, repo_root, cache_root, language="en"):
    """Small UI hints; all packaging identities are verified again on Save."""
    from webtools.core.charinfo import NAMES
    result = {"nameBase": Path(context["containers"][0]["name"]).stem,
              "characterId": None, "requiresCounterpart": False,
              "hasFaceCompanions": bool(context.get("outline_only_sources")),
              "faceSourceIndices": list(context.get("outline_only_sources", [])),
              "characters": [{"value": str(key), "label": value} for key, value in NAMES.items()]}
    manifest = _manifest_metadata(context, language)
    result["hasFaceCompanions"] = result["hasFaceCompanions"] or bool(manifest.get("has_face"))
    # The opened costume ZIP declares its own face (a reopened Mod ZIP or
    # scene): Save mod ZIP keeps it unless the person leaves it out.
    result["faceIncluded"] = bool(manifest.get("has_face"))
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
            facts = [viewer_mod_sources._model_facts(source["raw"]) for source in sources
                     if source["source"] not in set(context.get("outline_only_sources", []))]
            from .member_identity import member_from_native
            owners = {member_from_native(item["owner"]) for item in facts}
            if facts and len(owners) == 1 and next(iter(owners)) in NAMES:
                result["characterId"] = next(iter(owners))
                result["requiresCounterpart"] = result["characterId"] == 209
    except (ImportError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # A naming hint must not disable ordinary model/recipe exports.
        pass
    try:
        from . import viewer_physics_runtime
        derived = viewer_physics_runtime.owner_for_context(context, repo_root=repo_root, cache_root=cache_root)
        if derived and derived.get("derived"):
            # A verified wearer hint is not an original game receipt and must
            # never lend the edited bytes native counterpart auto-pairing.
            result["derivedOwner"] = copy.deepcopy(derived)
            result["characterId"] = derived["character_id"]
            result["requiresCounterpart"] = derived["character_id"] == 209 and not manifest.get("paired")
    except (ImportError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        pass
    return result


def normalize_mesh_state(mesh_state):
    """Canonical optional mesh channel; the mesh exporter validates operations."""
    if mesh_state is None:
        return None
    from . import viewer_mesh_tools
    if (not isinstance(mesh_state, dict) or set(mesh_state) != {"version", "meshes"}
            or type(mesh_state.get("version")) is not int or mesh_state["version"] != 1
            or not isinstance(mesh_state["meshes"], list) or len(mesh_state["meshes"]) > 128):
        raise ValueError("Invalid mesh edit state.")
    try:
        encoded = json.dumps(mesh_state, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("The mesh edit state contains invalid values.") from error
    if len(encoded) > viewer_mesh_tools.MAX_REQUEST_BYTES:
        raise ValueError("The mesh edit request exceeds the supported limit.")
    return copy.deepcopy(mesh_state) if mesh_state["meshes"] else None


def export_current(token, state, output_root, *, mesh_state=None, allow_empty=False,
                   repo_root, cache_root, log=lambda message: None):
    """Save one immutable preview containing every active edit channel."""
    from . import model_edits, viewer_mesh_tools, viewer_physics_runtime
    context = model_edits.mod_source_context(token)
    mesh = normalize_mesh_state(mesh_state)
    normalized = model_edits.validate_state(token, state, allow_empty=allow_empty or mesh is not None)
    result = None
    try:
        if mesh is not None:
            result = viewer_mesh_tools.export(token, mesh, output_root, body_state=normalized)
            with model_edits._LOCK:
                session = model_edits._session(token)
                body_recipe = model_edits._recipe(session, model_edits.with_held(session, normalized))
            result["recipe"]["bodyRecipe"] = body_recipe
            # Held face outline rows were written too; both copies name them.
            result["recipe"]["bodyState"] = copy.deepcopy(body_recipe["state"])
            path = Path(result["recipe_path"])
            temporary = path.with_name(".mesh-recipe-" + secrets.token_hex(8) + ".part")
            try:
                temporary.write_text(json.dumps(result["recipe"], ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            result = model_edits.export(token, normalized, output_root, allow_empty=allow_empty, log=log)
        if normalized.get("textures"):
            with model_edits._LOCK:
                texture_session = model_edits._session(token)
                selected_sources = {row["texture"]["source"] for row in normalized["textures"]}
                result["texture_edits"] = [copy.deepcopy(row) for index in sorted(selected_sources)
                    for row in texture_session.get("textureWriteSummary", {}).get(index, [])]
            if any(row.get("encodingChanged") for row in result["texture_edits"]):
                log("Precise texture edits use lossless RGBA32 to preserve unselected pixels and alpha.")
        remember_export_sources(context, result, repo_root=repo_root, cache_root=cache_root)
        from . import viewer_scene_roles
        viewer_scene_roles.remember_saved_originals(token, context, result.get("original_paths", []))
        result["derived_runtime"] = viewer_physics_runtime.inherit_export(context, result["preview_paths"],
            repo_root=repo_root, cache_root=cache_root)
        result["metadata"] = metadata(context, repo_root=repo_root, cache_root=cache_root)
        return result
    except Exception:
        discard_failed_export(result, output_root)
        raise


def restore_current(token, recipe):
    """Restore a combined recipe only against its exact immutable sources."""
    from . import model_edits, viewer_mesh_tools
    fields = {"version", "tool", "sources", "state", "bodyState", "bodyRecipe"}
    if (not isinstance(recipe, dict) or set(recipe) != fields or recipe.get("tool") != "mesh-tools"
            or type(recipe.get("version")) is not int or recipe["version"] != 1):
        raise ValueError("Choose a source-bound combined mesh recipe.")
    context = model_edits.mod_source_context(token)
    hashes = [row["sha256"] for row in context["containers"]]
    if recipe["sources"] != hashes:
        raise ValueError("This mesh recipe belongs to different original model bytes.")
    for source in context["containers"]:
        if hashlib.sha256(model_edits._read(source["path"])).hexdigest() != source["sha256"]:
            raise ValueError("An original model changed after opening. Reopen it before restoring.")
    body_recipe = recipe["bodyRecipe"]
    def identities(rows):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return None
        return [{key: row.get(key) for key in ("sha256", "container", "member")} for row in rows]
    if (not isinstance(body_recipe, dict)
            or identities(body_recipe.get("sources")) != identities(context["sources"])
            or not isinstance(body_recipe.get("originals"), list)
            or [row.get("sha256") for row in body_recipe["originals"] if isinstance(row, dict)] != hashes
            or len(body_recipe["originals"]) != len(hashes)
            or recipe["bodyState"] != body_recipe.get("state")):
        raise ValueError("The combined recipe does not match every original source and body state.")
    body = model_edits.restore(token, body_recipe, allow_empty=True)
    normalized = normalize_mesh_state(recipe["state"])
    mesh = normalized if normalized is not None else {"version": 1, "meshes": []}
    with model_edits._LOCK:
        session = model_edits._session(token)
    viewer_mesh_tools._check_archive_scope(session)
    seen = set()
    for operation in mesh["meshes"]:
        if not isinstance(operation, dict) or set(operation) - {"mesh", "deleteFaces", "positions", "weights"}:
            raise ValueError("Unsupported mesh edit property.")
        identity = operation.get("mesh")
        source = viewer_mesh_tools._identity(identity, session)
        key = (source, identity["file"], identity["id"])
        if key in seen or not any(operation.get(name) for name in ("deleteFaces", "positions", "weights")):
            raise ValueError("The combined mesh recipe contains empty or duplicate operations.")
        seen.add(key)
        _, record = viewer_mesh_tools._record(session, identity)
        # The same native writer performs a dry validation in a fresh in-memory
        # Unity environment. No original bytes or files are modified here.
        viewer_mesh_tools._write_mesh(record[1], copy.deepcopy(record[2]), record[3], operation)
    return {"state": body, "mesh_state": mesh}


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


def _package_inputs(context, result):
    """Separate only server-verified automatic faces from body pack inputs."""
    automatic = set(context.get("outline_only_sources", []))
    if not automatic:
        return result, []
    sources = context["sources"]
    if any(type(index) is not int or not 0 <= index < len(sources) for index in automatic):
        raise ValueError("The automatic face source binding is invalid.")
    body = [row for index, row in enumerate(sources) if index not in automatic]
    if not body:
        raise ValueError("Choose a body costume before packaging its face companion.")
    by_container = {index: {i for i, row in enumerate(sources) if row["container"] == index}
                    for index in range(len(context["containers"]))}
    face_only = {index for index, rows in by_container.items() if rows and rows <= automatic}
    selected = dict(result)
    selected["preview_paths"] = [path for index, path in enumerate(result["preview_paths"]) if index not in face_only]
    companions = []
    from . import viewer_mod_sources
    target_hint = result.get("metadata", {}).get("characterId")
    directory = Path(result["recipe_path"]).parent / "face-companions"
    for index in sorted(automatic):
        source = sources[index]; container = source["container"]; member = source["member"]
        original = context["containers"][container]
        original_raw = original["raw"]
        if member is not None:
            with zipfile.ZipFile(io.BytesIO(original_raw)) as archive:
                original_raw = archive.read(member)
        if hashlib.sha256(original_raw).hexdigest() != source["sha256"]:
            raise ValueError("The automatic face no longer matches its original source.")
        current = Path(result["preview_paths"][container])
        raw = current.read_bytes()
        if member is not None:
            if container not in face_only:
                # An existing installer already preserves its declared face in
                # this same archive. Generic multi-model ZIPs remain rejected.
                with zipfile.ZipFile(current) as archive:
                    raw = archive.read(member)
                    declared = _manifest_metadata({"containers": [{"raw": current.read_bytes()}]}, "en")
                if declared.get("owner") is not None:
                    continue
                raise ValueError("Open the body and verified face as individual Unity bundles before packaging this multi-model archive.")
            with zipfile.ZipFile(current) as archive:
                raw = archive.read(member)
            directory.mkdir(exist_ok=True)
            current = directory / ("face-" + str(index) + ".unity")
            current.write_bytes(raw)
        facts = viewer_mod_sources._model_facts(original_raw)
        from .member_identity import member_from_native
        owner = member_from_native(facts["owner"]) if facts["owner"] is not None else None
        if owner is None:
            # Some native faces carry only meshes and link shared textures.
            # Their prefab/renderers can still prove the face's member.
            from . import face_platforms, model_faces, model_viewer
            deadline = time.monotonic() + model_faces.FACE_SECONDS
            scene = model_viewer._Scene(model_viewer._environment([str(current)], deadline), deadline)
            owner = face_platforms.face_owner(scene) or target_hint
        companions.append({"path": str(current), "sha256": hashlib.sha256(raw).hexdigest(),
            "original_path": result["original_paths"][container], "original_sha256": original["sha256"],
            "source_sha256": source["sha256"], "source_index": index, "container": container,
            "member": member, "owner": owner, "platform": facts["platform"],
            "body_source_sha256": body[0]["sha256"]})
    return selected, companions


def create_package(token, state, *, output_root, repo_root, cache_root, display_name,
                   character_id=None, counterpart_path=None, selected_variant=None, thumbnail_token="", mesh_state=None,
                   include_face_edits=None, job):
    from webtools.core import model_edits, viewer_mod_package, viewer_mod_sources, viewer_mod_pair_edits, viewer_scene_roles
    name = validate_options(display_name, character_id, counterpart_path, selected_variant)
    if include_face_edits is not None and not isinstance(include_face_edits, bool):
        raise ValueError("Choose whether to include this costume's verified face companion.")
    if not _PACKAGE_SLOT.acquire(blocking=False):
        raise ValueError("Another Mod ZIP is being prepared. Try again shortly.")
    exported_result = None
    try:
        _check(job)
        context = model_edits.mod_source_context(token)
        normalized = model_edits.validate_state(token, state, allow_empty=True)
        mesh = normalize_mesh_state(mesh_state)
        if mesh is not None and (counterpart_path or viewer_scene_roles.session_metadata(token)):
            raise ValueError("Mesh edits cannot be propagated to paired or scene costumes. Save an individual edited Unity bundle instead.")
        from webtools.core import viewer_thumbnails
        thumbnail = viewer_thumbnails.for_viewer_package(thumbnail_token, token, normalized,
            character_id, counterpart_path, selected_variant, mesh_state=mesh, include_face_edits=include_face_edits)
        result = export_current(token, normalized, output_root, mesh_state=mesh, allow_empty=True,
            repo_root=repo_root, cache_root=cache_root, log=job.log)
        exported_result = result
        _check(job)
        selection = {"counterpart_path": counterpart_path, "selected_variant": selected_variant} if counterpart_path else None
        derived = result.get("metadata", {}).get("derivedOwner")
        automatic_faces = set(context.get("outline_only_sources", []))
        body_containers = {source["container"] for index, source in enumerate(context["sources"])
                           if index not in automatic_faces}
        independent_derived = (derived and derived["character_id"] != 209 and not selection
            and len(body_containers) == 1
            and not zipfile.is_zipfile(io.BytesIO(context["containers"][next(iter(body_containers))]["raw"])))
        pair = (None if independent_derived else viewer_mod_sources.resolve_pair(context, result, repo_root=repo_root,
            output_root=cache_root, job=job, selection=selection, receipts=cached_receipts(context, cache_root)))
        if mesh is not None and pair is not None:
            raise ValueError("Mesh edits cannot be propagated to paired costumes. Save an individual edited Unity bundle instead.")
        pair_state = copy.deepcopy(normalized)
        if automatic_faces and pair_state.get("outlines"):
            pair_state["outlines"] = [row for row in pair_state["outlines"] if int(row["id"].split(":", 1)[0]) not in automatic_faces]
        if automatic_faces and pair_state.get("textures"):
            pair_state["textures"] = [row for row in pair_state["textures"] if row["texture"]["source"] not in automatic_faces]
        try:
            paired = (viewer_mod_pair_edits.apply_pair_edits(context, result, pair_state, pair=pair, job=job)
                      if model_edits.has_changes(pair_state) or context.get("held_counterpart")
                      else {"result": result, "pair": pair, "summary": []})
        except viewer_mod_pair_edits.PairEditError as error:
            # The page shows this sentence translated with the part's name
            # (viewer-persistence.js awaitJob).
            emit = getattr(job, "emit", None)
            if callable(emit):
                emit({"type": "message", **error.note})
            raise
        result, pair = paired["result"], paired["pair"]
        kept = list(dict.fromkeys(name for row in paired.get("summary", []) for name in (row.get("kept") or {}).get("names", [])))
        if kept:
            # Parts only this costume variant has keep their edits here (save status note).
            result["notes"] = [{"text": viewer_mod_pair_edits.SELECTED_ONLY, "values": {"names": kept}}]
        # Counterpart mapping may rewrite the complete archive. Bind derived
        # runtime proof to those final bytes, never to the pre-pair ZIP hash.
        from . import viewer_physics_runtime
        result["derived_runtime"] = viewer_physics_runtime.inherit_export(context, result["preview_paths"],
            repo_root=repo_root, cache_root=cache_root)
        if paired.get("summary"):
            result["paired_edits"] = paired["summary"]
        _check(job)
        package_result, faces = _package_inputs(context, result)
        owner = character_id if character_id is not None else result.get("metadata", {}).get("characterId")
        packed = viewer_mod_package.package_saved_export(package_result, Path(result["recipe_path"]).parent / "mod",
            display_name=name, chara_id=owner, pair=pair,
            log=job.log, should_stop=job.should_stop,
            **({"face_companions": faces} if include_face_edits and faces else {}),
            **({"include_face_edits": include_face_edits} if include_face_edits is not None else {}),
            **({"thumbnail": thumbnail} if thumbnail is not None else {}))
        result["face_identity"] = packed.get("face_identity", [])
        if viewer_scene_roles.should_package(context, normalized, packed, token):
            if mesh is not None:
                raise ValueError("Mesh edits cannot be propagated to scene costumes. Save an individual edited Unity bundle instead.")
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
        receipt = {"public": copy.deepcopy(public), "source_token": token, "state": normalized, "mesh_state": mesh,
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
