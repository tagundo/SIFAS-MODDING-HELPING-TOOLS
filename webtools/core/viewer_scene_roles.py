"""Derive shared Rina board execution after canonical body editing completes.

Canonical originals, recipes and MV goldens remain unchanged. The shared
board copy synchronizes only its supported authored scale defaults, followed
by identity isolation; it never reapplies NodeScaling or bakes another mesh.
"""
from collections import OrderedDict
from contextlib import closing
import ast
import copy
import io
import json
import math
import struct
from pathlib import Path
import secrets
import sqlite3
import threading
import zipfile

from . import model_edits as edits
from . import viewer_scene_format as fmt

_SCENES = OrderedDict()
_LOCK = threading.RLock()
_FIELDS = {"costume_file": "primary", "rina_unmask_costume_file": "unmasked",
           "costume_file_ios": "primary", "rina_unmask_costume_file_ios": "unmasked"}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _json(raw):
    return json.loads(raw.decode("utf-8"))


def session_metadata(token):
    with _LOCK:
        return copy.deepcopy(_SCENES.get(token))


def _literal_models(raw):
    """Read a previously validated legacy family; never execute a manifest."""
    from . import viewer_mod_pair_edits
    if not viewer_mod_pair_edits._zip_declarations(raw):
        return {}
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifests = [info for info in archive.infolist() if Path(info.filename).name.lower() == "modinstall.txt"]
        _require(len(manifests) == 1, "A scene costume needs one unambiguous original family.")
        values = {}
        for node in ast.parse(archive.read(manifests[0]).decode("utf-8-sig")).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in _FIELDS):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        directory = Path(manifests[0].filename).parent
        for field, variant in _FIELDS.items():
            if not values.get(field):
                continue
            name = (directory / values[field]).as_posix()
            data = archive.read(name)
            platform = next((key for key, value in fmt.PLATFORMS.items() if value == fmt._native_platform(data)), None)
            _require(platform is not None and (platform, variant) not in result, "The scene original family is ambiguous.")
            result[platform, variant] = data
    return result


def _literal_faces(raw):
    """Read declared canonical face companions without executing metadata."""
    from . import viewer_mod_pair_edits
    _require(viewer_mod_pair_edits._zip_declarations(raw), "The preserved source has no verified costume family.")
    fields = {"costume_facedynamic_file", "costume_facedynamic_file_ios"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifests = [info for info in archive.infolist() if Path(info.filename).name.lower() == "modinstall.txt"]
        _require(len(manifests) == 1, "The preserved source face declarations are ambiguous.")
        values = {}
        for node in ast.parse(archive.read(manifests[0]).decode("utf-8-sig")).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in fields):
                key, value = node.targets[0].id, ast.literal_eval(node.value)
                _require(key not in values or values[key] == value, "The preserved source face declarations conflict.")
                values[key] = value
        faces = {}
        for field, value in values.items():
            if value in (None, ""):
                continue
            _require(isinstance(value, str), "The preserved source face reference is invalid.")
            relative = fmt._path(value.replace("\\", "/"))
            member = (Path(manifests[0].filename).parent / relative).as_posix()
            _require(member in archive.namelist(), "The preserved source face companion is missing.")
            data = archive.read(member)
            platform = next((key for key, target in fmt.PLATFORMS.items() if target == fmt._native_platform(data)), None)
            _require(platform is not None and platform not in faces and
                     (not field.endswith("_ios") or platform == "ios") and
                     (field.endswith("_ios") or not values.get("costume_facedynamic_file_ios") or platform == "android"),
                     "The preserved source face platform is invalid or ambiguous.")
            faces[platform] = data
        return faces


def _normalize_recipe(recipe, original, name):
    candidates = [index for index, source in enumerate(recipe["sources"]) if source["sha256"] == fmt.sha(original)]
    _require(len(candidates) == 1, "A scene recipe cannot be bound to one original model.")
    index = candidates[0]
    identities = [copy.deepcopy(row) for row in recipe["nodeIdentities"] if row["sourceIndex"] == index]
    nodes = {row["node"] for row in identities}
    state = copy.deepcopy(recipe["state"])
    state["edits"] = [row for row in state["edits"] if row["node"] in nodes]
    state["compensationReference"] = [row for row in state.get("compensationReference", []) if row["node"] in nodes]
    for row in identities:
        row["sourceIndex"] = 0
    return {"format": "elichika-viewer-body-edit", "version": 1,
            "sources": [{"name": name, "sha256": fmt.sha(original), "container": 0, "member": None}],
            "originals": [{"name": name, "sha256": fmt.sha(original)}],
            "state": state, "nodeIdentities": identities}


def _empty_recipe(original, name):
    return {"format": "elichika-viewer-body-edit", "version": 1,
            "sources": [{"name": name, "sha256": fmt.sha(original), "container": 0, "member": None}],
            "originals": [{"name": name, "sha256": fmt.sha(original)}],
            "state": {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [], "compensationReference": []},
            "nodeIdentities": []}


def _originals_and_recipes(context, result, pair, goldens, state):
    originals = {}
    for container in context["containers"]:
        if zipfile.is_zipfile(io.BytesIO(container["raw"])):
            originals.update(_literal_models(container["raw"]))
    if not originals:
        _require(pair is not None and len(context["sources"]) == 1, "The raw Rina scene has no verified complete pair.")
        selected = str(Path(result["preview_paths"][0]).resolve())
        roles = [variant for variant in fmt.VARIANTS if str(Path(pair[variant]["path"]).resolve()) == selected]
        _require(len(roles) == 1, "The selected Rina source lost its pair identity.")
        source = context["sources"][0]
        _require(source["member"] is None, "The raw Rina source must be its complete original file.")
        original = context["containers"][source["container"]]["raw"]
        platform = next(key for key, value in fmt.PLATFORMS.items() if value == fmt._native_platform(original))
        originals[platform, roles[0]] = original
        summaries = result.get("paired_edits", [])
        for summary in summaries:
            if summary.get("variant") not in fmt.VARIANTS:
                continue
            candidates = [Path(path).read_bytes() for path in result.get("paired_original_paths", [])
                          if fmt.sha(Path(path).read_bytes()) == summary["original_sha256"]]
            _require(len(candidates) == 1, "A paired canonical original is missing.")
            originals[platform, summary["variant"]] = candidates[0]
        if not edits.has_changes(state):
            for variant in fmt.VARIANTS:
                originals.setdefault((platform, variant), Path(pair[variant]["path"]).read_bytes())
    _require(set(originals) == set(goldens), "The scene costume has no complete native original family.")
    recipes = [result["recipe"]]
    for path in result.get("paired_recipe_paths", []):
        value = _json(Path(path).read_bytes())
        if value.get("format") == "elichika-viewer-body-edit":
            recipes.append(value)
    normalized = {}
    for key, original in originals.items():
        candidates = [recipe for recipe in recipes if any(source["sha256"] == fmt.sha(original) for source in recipe["sources"])]
        if not edits.has_changes(state):
            normalized[key] = _empty_recipe(original, "_".join(key) + ".unity")
        else:
            _require(len(candidates) == 1, "The scene costume has no unique original-bound variant recipe.")
            normalized[key] = _normalize_recipe(candidates[0], original, "_".join(key) + ".unity")
    return originals, normalized


def _sync_navi(golden, recipe):
    info = edits._inspect(golden)
    _require(not info["conflicts"], "Conflicting saved Node settings cannot form a shared Rina board.")
    by_identity = {(row["serializedFile"], int(row["transformId"])): row["node"] for row in recipe["nodeIdentities"]}
    allowed = {row["node"] for row in recipe["state"]["edits"] if row["method"] == "node" and "scale" in row}
    named = {node: info["names"].get(key) for key, node in by_identity.items()}
    for row in recipe["state"]["edits"]:
        if row["method"] == "node":
            _require(named.get(row["node"]) in fmt.SUPPORTED_SCALES and "scale" in row and
                     not any(kind in row for kind in ("position", "rotation")),
                     "Shared Rina board export supports only BreastSize/HipsSize scale-only Node edits; reset other Node changes or use mesh baking.")
    # HOME skips the board scaler. Only the two scale-only targets whose
    # Common/MV behavior was validated can share an authored execution model.
    # In particular, explicit inverse-child Node edits must not silently remain
    # MV-only. Mesh compensation is already baked into the canonical golden.
    for key, kind in info["records"]:
        if not edits._close(info["effective"][key][kind], info["authored"][key][kind]):
            _require(kind == "scale" and info["names"].get(key) in fmt.SUPPORTED_SCALES,
                     "Shared Rina board export supports only BreastSize/HipsSize Node scales; reset other saved Node changes or use mesh baking.")
    sync, changed = {}, set()
    before = {key: obj.get_raw_data() for key, obj in info["objects"].items()}
    streams = {name: bytes(value.bytes) for name, value in info["env"].file.files.items() if not hasattr(value, "objects")}
    for key, name in info["names"].items():
        if name not in fmt.SUPPORTED_SCALES or (by_identity.get(key) not in allowed and
                edits._close(info["effective"][key]["scale"], info["authored"][key]["scale"])):
            continue
        _require(name not in sync and sum(other == name for other in info["names"].values()) == 1 and
                 (key, "scale") in info["records"], "The Navi scale target is ambiguous or has no Node setting.")
        value = list(info["effective"][key]["scale"])
        tree = info["transforms"][key]
        tree["m_LocalScale"] = edits._d3(value)
        obj = info["objects"][key]
        obj.save_typetree(tree)
        changed.add(key)
        sync[name] = value
    result = info["env"].file.save(packer="original")
    # Check the persisted float32 defaults, including every directly bound
    # skin bone, against the original client's IllegalSkinMesh limits.
    checked = edits._inspect(result)
    _require(set(checked["objects"]) == set(before) and
             all(obj.get_raw_data() == before[key] for key, obj in checked["objects"].items() if key not in changed),
             "Deriving the shared Rina board changed an unrelated object.")
    _require(streams == {name: bytes(value.bytes) for name, value in checked["env"].file.files.items()
                        if not hasattr(value, "objects")}, "Deriving the shared Rina board changed streamed resources.")
    low = struct.unpack("<f", struct.pack("<f", .2))[0]
    skin_bones = set()
    for obj in checked["env"].objects:
        if obj.type.name != "SkinnedMeshRenderer":
            continue
        file_index = checked["file_indices"][id(obj.assets_file)]
        for pointer in obj.read_typetree().get("m_Bones", []):
            key = (file_index, pointer.get("m_PathID")) if pointer.get("m_FileID") == 0 else None
            skin_bones.add(key)
            _require(key in checked["authored"] and all(math.isfinite(v) and low <= v <= 2.5
                     for v in checked["authored"][key]["scale"]),
                     "A shared Rina board skin bone scale is outside the game's 0.2–2.5 limits.")
    for key, name in checked["names"].items():
        if name in sync:
            _require(key in skin_bones, "The shared Rina scale target is not a directly bound skin bone.")
            _require(checked["authored"][key]["scale"] == checked["effective"][key]["scale"],
                     "The shared Rina board endpoint changed while serializing.")
    return result, sync


def _provenance(context, token, repo_root, receipts):
    previous = session_metadata(token)
    if previous:
        return previous["source_suit_id"], previous["source_provenance"]
    from . import viewer_mod_sources
    bindings = viewer_mod_sources.game_context(context, repo_root, receipts=receipts)
    if not bindings:
        return None, None
    from . import game_models
    ids = set()
    for binding in bindings:
        record = binding["record"]
        with closing(game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")) as database:
            row = database.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (record["suit_id"],)).fetchone()
            _require(row is not None and row[0] == 209, "The canonical Rina source changed.")
            source_id, _ = game_models._attachment(database, record["suit_id"], 209, row[1])
            ids.add(source_id)
    _require(len(ids) == 1, "The scene costume has conflicting game source identities.")
    return next(iter(ids)), None  # Filled from validated native catalogs below.


def _fill_source_provenance(manifest, repo_root):
    if manifest["source_suit_id"] is None or manifest["source_provenance"] is not None:
        return
    from . import game_models
    proof = {}
    for region in ("gl", "jp"):
        folder = Path(repo_root) / "assets/db" / region
        with closing(game_models._readonly(folder / "masterdata.db")) as database:
            row = database.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?",
                                   (manifest["source_suit_id"],)).fetchone()
            _require(row is not None and row[0] == 209, "The original Rina costume is not available in both game regions.")
            views = dict(database.execute("SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=?",
                                          (manifest["source_suit_id"],)))
            models = {"primary": views.get(1) or row[1], "unmasked": views.get(2)}
            _require(all(models.values()), "The original Rina scene variants are incomplete.")
        proof[region] = {}
        for platform in manifest["platforms"]:
            catalogs = sorted(folder.glob("asset_" + ("a" if platform == "android" else "i") + "_*.db"))
            _require(catalogs, "The original native Rina catalog is unavailable.")
            records = None
            for catalog in catalogs:
                with closing(game_models._readonly(catalog)) as database:
                    current = {}
                    for variant, model in models.items():
                        descriptor = game_models._descriptor(database, model, manifest["source_suit_id"])
                        _require(descriptor is not None, "An original native scene descriptor is missing.")
                        current[variant] = {"asset_path": model, **{key: descriptor[key] for key in ("pack_name", "head", "size", "key1", "key2")}}
                    _require(records is None or records == current, "The original scene catalog fingerprints conflict.")
                    records = current
            proof[region][platform] = records
    manifest["source_provenance"] = proof


def expand_scene(path, directory, variant=None):
    """Recover only canonical originals into a deterministic legacy input ZIP."""
    decoded = fmt.read_package(path)
    manifest, files = decoded["manifest"], decoded["files"]
    if variant is None:
        variant = manifest.get("default_variant", "primary")
    _require(variant in fmt.VARIANTS, "Choose a valid Rina costume variant.")
    platform = "android" if "android" in manifest["platforms"] else "ios"
    members, values = {}, {"chara_id": 209}
    for native, family in manifest["authoring"].items():
        for role in fmt.VARIANTS:
            name = native + "_" + role + ".unity"
            members[name] = files[family[role]["original"]["member"]]
            field = "costume_file" if role == "primary" else "rina_unmask_costume_file"
            if native == "ios" and "android" in manifest["platforms"]:
                field += "_ios"
            values[field] = name
    for language in ("en", "ko", "ja", "zh"):
        values["costume_name_" + language] = manifest["display_name"]
    values["costume_description"] = manifest["display_name"]
    if manifest["thumbnail"]:
        members["thumbnail.png"] = files[manifest["thumbnail"]["member"]]
        values["thumbnail_file"] = "thumbnail.png"
    for native, dependencies in manifest["dependencies"].items():
        if dependencies["facedynamic"]:
            name = native + "_face.unity"
            members[name] = files[dependencies["facedynamic"]["member"]]
            field = "costume_facedynamic_file" + ("_ios" if native == "ios" and "android" in manifest["platforms"] else "")
            values[field] = name
    members["modinstall.txt"] = ("\n".join(key + " = " + repr(value) for key, value in sorted(values.items())) + "\n").encode()
    original_zip = Path(directory) / "canonical-originals.zip"
    # Prefer an exact preserved input ZIP only after its native role bytes
    # agree with every canonical original. Companion metadata is never run.
    originals = {(native, role): files[family[role]["original"]["member"]]
                 for native, family in manifest["authoring"].items() for role in fmt.VARIANTS}
    preserved = None
    for source in manifest.get("source_archives", []):
        raw = files[source["file"]["member"]]
        if _literal_models(raw) == originals:
            canonical_faces = {native: files[dependencies["facedynamic"]["member"]]
                               for native, dependencies in manifest["dependencies"].items() if dependencies["facedynamic"]}
            _require(_literal_faces(raw) == canonical_faces,
                     "The preserved source ZIP's declared face companion does not match the canonical original face. Open the original complete costume ZIP.")
            preserved = raw
            break
    if preserved is not None:
        original_zip.write_bytes(preserved)
    else:
        with zipfile.ZipFile(original_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(members.items()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw)
    recipe = _json(files[manifest["authoring"][platform][variant]["recipe"]["member"]])
    return {"path": str(original_zip), "variant": variant, "recipe": recipe,
            "metadata": {**{key: copy.deepcopy(manifest[key]) for key in ("display_name", "source_suit_id", "source_provenance")},
                         "target_member_id": manifest.get("target_member_id", 209),
                         "default_variant": manifest.get("default_variant", "primary")}}


def register_reopened(token, scene):
    """Restore a recipe only after the exact selected raw source is recovered."""
    session = edits._session(token)
    recipe = copy.deepcopy(scene["recipe"])
    matches = [index for index, source in enumerate(session["sources"])
               if source["sha256"] == recipe["sources"][0]["sha256"]]
    _require(len(matches) == 1, "The scene recipe lost its canonical original identity.")
    index = matches[0]
    recipe["sources"] = edits._source_signature(session)
    recipe["originals"] = [{"name": item["name"], "sha256": item["sha256"]} for item in session["containers"]]
    for identity in recipe["nodeIdentities"]:
        identity["sourceIndex"] = index
    session["allowEmptySceneReset"] = True
    state = edits.restore(token, recipe)
    with _LOCK:
        _SCENES[token] = copy.deepcopy(scene["metadata"])
        while len(_SCENES) > edits.MAX_SESSIONS:
            _SCENES.popitem(last=False)
    return state


def should_package(context, state, packed, token):
    if session_metadata(token):
        return True
    if packed.get("chara_id") != 209:
        return False
    if pending_supported_nodes(context):
        return True
    names = {node["node"]: node["name"] for node in context["nodes"]}
    return any(row["method"] == "node" and "scale" in row and names.get(row["node"]) in fmt.SUPPORTED_SCALES
               for row in state["edits"])


def pending_supported_nodes(context):
    return any(node["name"] in fmt.SUPPORTED_SCALES and "node" in node["methods"] and
               not edits._close(node["baseline"]["scale"], node["authored"]["scale"])
               for node in context["nodes"])


def package_scene(context, result, state, *, pair, packed, token, repo_root, receipts=(), log=lambda value: None):
    """Preserve MV goldens and sync/isolate one board copy shared by HOME/MV."""
    from . import bundle_identity
    legacy = Path(packed["package_path"])
    files, goldens, extras = {}, {}, {}
    with zipfile.ZipFile(legacy) as archive:
        for field, variant in _FIELDS.items():
            member = packed["model_members"].get(field)
            if not member:
                continue
            raw = archive.read(member)
            platform = next(key for key, value in fmt.PLATFORMS.items() if value == fmt._native_platform(raw))
            _require((platform, variant) not in goldens, "The saved scene family is ambiguous.")
            goldens[platform, variant] = raw
        for key, member in packed.get("asset_members", {}).items():
            if key not in _FIELDS:
                extras[key] = archive.read(member)
    platforms = {key[0] for key in goldens}
    _require(set(goldens) == {(platform, variant) for platform in platforms for variant in fmt.VARIANTS},
             "A Rina scene costume needs a complete native board/bare family.")
    originals, recipes = _originals_and_recipes(context, result, pair, goldens, state)
    source_id, provenance = _provenance(context, token, repo_root, receipts)
    previous = session_metadata(token) or {}
    manifest = {"format": fmt.FORMAT, "version": fmt.SHARED_VERSION, "requires": [fmt.SHARED_CAPABILITY],
                "character_id": 209, "target_member_id": previous.get("target_member_id", 209),
                "default_variant": previous.get("default_variant", "primary"),
                "display_name": packed["display_name"], "platforms": {}, "canonical_goldens": {},
                "authoring": {}, "thumbnail": None, "dependencies": {}, "navi_sync": {},
                "source_suit_id": source_id, "source_provenance": provenance}
    def store(member, raw, platform=None):
        files[member] = raw
        return fmt.reference(member, raw, platform)
    namespace = secrets.token_hex(16)
    proofs = {}
    for platform in sorted(platforms):
        manifest["platforms"][platform], manifest["canonical_goldens"][platform], manifest["authoring"][platform] = {}, {}, {}
        for variant in fmt.VARIANTS:
            role = "mv_board" if variant == "primary" else "mv_unmasked"
            golden = goldens[platform, variant]
            manifest["canonical_goldens"][platform][role] = store(f"goldens/{platform}_{role}.unity", golden, platform)
            if variant == "unmasked":
                execution, proof = bundle_identity.isolate_verified_bundle(golden, namespace + ":" + platform + ":" + role)
                manifest["platforms"][platform][role] = store(f"models/{platform}_{role}.unity", execution, platform)
                proofs[platform + ":" + role] = proof
            manifest["authoring"][platform][variant] = {
                "original": store(f"originals/{platform}_{variant}.unity", originals[platform, variant], platform),
                "recipe": store(f"recipes/{platform}_{variant}.json", json.dumps(recipes[platform, variant], allow_nan=False).encode())}
        navi, sync = _sync_navi(goldens[platform, "primary"], recipes[platform, "primary"])
        navi, proof = bundle_identity.isolate_verified_bundle(navi, namespace + ":" + platform + ":navi_board")
        shared_board = store(f"models/{platform}_shared_board.unity", navi, platform)
        manifest["platforms"][platform]["navi_board"] = shared_board
        manifest["platforms"][platform]["mv_board"] = copy.deepcopy(shared_board)
        proofs[platform + ":navi_board"] = proof
        proofs[platform + ":mv_board"] = copy.deepcopy(proof)
        manifest["navi_sync"][platform] = sync
        face = extras.get("costume_facedynamic_file_ios" if platform == "ios" and "android" in platforms else "costume_facedynamic_file")
        manifest["dependencies"][platform] = {"facedynamic": store(f"dependencies/{platform}_face.unity", face, platform) if face else None}
    if extras.get("thumbnail_file"):
        manifest["thumbnail"] = store("thumbnail.png", extras["thumbnail_file"])
    manifest["source_archives"] = []
    for index, container in enumerate(context["containers"]):
        raw = container["raw"]
        if zipfile.is_zipfile(io.BytesIO(raw)):
            # A .data member stays inert even in old installers. The exact
            # source ZIP retains comments/companions without becoming an
            # executable nested mod or replacing canonical recipe authority.
            name = Path(container["name"]).name[:120] or "source.zip"
            manifest["source_archives"].append({"name": name,
                "file": store(f"metadata/source-{index}.data", raw)})
    _fill_source_provenance(manifest, repo_root)
    data = fmt.encode_package(manifest, files)
    destination = legacy.with_name(legacy.stem + "-scene.zip")
    _require(not destination.exists(), "The scene package output already exists.")
    temporary = destination.with_suffix(".part")
    try:
        with temporary.open("xb") as output:
            output.write(data)
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
    log("Prepared Rina Navi/MV scene-role Mod ZIP: " + destination.name)
    return {**packed, "package_path": str(destination), "sha256": fmt.sha(data), "bytes": len(data),
            "format": fmt.FORMAT, "version": fmt.SHARED_VERSION, "scene_roles": manifest["platforms"],
            "target_member_id": manifest["target_member_id"], "default_variant": manifest["default_variant"],
            "identity_proofs": proofs, "canonical_goldens": manifest["canonical_goldens"]}
