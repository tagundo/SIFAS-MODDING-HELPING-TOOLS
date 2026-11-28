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
import os
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
    if "physics" in state:
        state["physics"] = [{**row, "id": "0:" + row["id"].split(":", 1)[1]}
                            for row in state["physics"] if row["id"].split(":", 1)[0] == str(index)]
    if "outlines" in state:
        state["outlines"] = [{**row, "id": "0:" + row["id"].split(":", 1)[1]}
                             for row in state["outlines"] if row["id"].split(":", 1)[0] == str(index)]
    if "textures" in state:
        state["textures"] = [{**row, "texture": {**row["texture"], "source": 0}}
                             for row in state["textures"] if row["texture"]["source"] == index]
        _require(all(row["sourceSha256"] == fmt.sha(original) for row in state["textures"]),
                 "A scene texture recipe is not bound to its canonical original model.")
        if not state["textures"]:
            state.pop("textures")
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


def _source_bytes(context, index):
    source = context["sources"][index]
    raw = context["containers"][source["container"]]["raw"]
    if source["member"] is not None:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            raw = archive.read(source["member"])
    _require(fmt.sha(raw) == source["sha256"], "The canonical face source no longer matches its captured original.")
    return raw


def _face_sources(context):
    """Session sources that are a face: automatic companions, or the face
    companion a selected costume ZIP declares (bound by its exact bytes)."""
    faces = set(context.get("outline_only_sources", []))
    declared = set()
    for container in context["containers"]:
        if zipfile.is_zipfile(io.BytesIO(container["raw"])):
            declared.update(fmt.sha(raw) for raw in _literal_faces(container["raw"]).values())
    faces.update(index for index, source in enumerate(context["sources"]) if source["sha256"] in declared)
    return faces


def _face_originals_and_recipes(context, result, platforms, runtime_faces):
    """Keep face authoring authority separate from private execution bytes."""
    originals, declared = {}, set()
    def remember(platform, raw):
        _require(platform not in originals or originals[platform] == raw,
                 "The scene costume has conflicting original face companions.")
        originals[platform] = raw
    for container in context["containers"]:
        if zipfile.is_zipfile(io.BytesIO(container["raw"])):
            for platform, raw in _literal_faces(container["raw"]).items():
                remember(platform, raw)
                declared.add(platform)
    for index in context.get("outline_only_sources", []):
        raw = _source_bytes(context, index)
        platform = next((key for key, value in fmt.PLATFORMS.items() if value == fmt._native_platform(raw)), None)
        _require(platform is not None, "The original face has an unsupported native platform.")
        remember(platform, raw)
    records = {}
    for platform, original in originals.items():
        if platform not in platforms:
            continue
        matches = [index for index, source in enumerate(result["recipe"]["sources"])
                   if source["sha256"] == fmt.sha(original)]
        _require(len(matches) <= 1, "The original scene face has an ambiguous source binding.")
        recipe = (_normalize_recipe(result["recipe"], original, platform + "_face.unity") if matches else
                  _empty_recipe(original, platform + "_face.unity"))
        _require(not recipe["state"].get("edits") and not recipe["state"].get("physics"),
                 "Scene face authoring supports texture and outline edits; reset facial Node or physics changes before exporting.")
        recipe["nodeIdentities"] = []
        recipe["state"] = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [],
                           "compensationReference": [], **{key: recipe["state"][key] for key in ("textures", "outlines")
                                                          if recipe["state"].get(key)}}
        runtime = runtime_faces.get(platform)
        if (edits.has_changes(recipe["state"]) or runtime is not None and runtime != original or
                platform in declared and runtime is None):
            records[platform] = (original, recipe)
    return records


def _originals_and_recipes(context, result, pair, goldens, state):
    # A texture edit changes one explicitly selected image layout. It does not
    # authorize copying pixels into a board/bare or Android/iOS counterpart.
    partner_state = {key: value for key, value in state.items() if key != "textures"}
    # A face's own outline edits belong to the face authoring recipe, which
    # both variants share. They do not change either body, so an unchanged
    # counterpart stays its original, as pairing already treats them.
    faces = _face_sources(context)
    if faces and partner_state.get("outlines"):
        partner_state["outlines"] = [row for row in partner_state["outlines"]
                                     if int(row["id"].split(":", 1)[0]) not in faces]
    partner_body_changed = edits.has_changes(partner_state) or bool(context.get("held_counterpart"))
    # A counterpart that has none of the edited parts (Rina's board-only Mask,
    # eye and mouth meshes) keeps its original bytes and has no variant recipe.
    unchanged = {summary["original_sha256"] for summary in result.get("paired_edits", []) if summary.get("unchanged")}
    originals = {}
    for container in context["containers"]:
        if zipfile.is_zipfile(io.BytesIO(container["raw"])):
            originals.update(_literal_models(container["raw"]))
    if not originals:
        body_sources = [row for index, row in enumerate(context["sources"])
                        if index not in set(context.get("outline_only_sources", []))]
        _require(pair is not None and len(body_sources) == 1, "The raw Rina scene has no verified complete pair.")
        source = body_sources[0]
        selected = str(Path(result["preview_paths"][source["container"]]).resolve())
        roles = [variant for variant in fmt.VARIANTS if str(Path(pair[variant]["path"]).resolve()) == selected]
        _require(len(roles) == 1, "The selected Rina source lost its pair identity.")
        _require(source["member"] is None, "The raw Rina source must be its complete original file.")
        original = context["containers"][source["container"]]["raw"]
        platform = next(key for key, value in fmt.PLATFORMS.items() if value == fmt._native_platform(original))
        originals[platform, roles[0]] = original
        summaries = result.get("paired_edits", [])
        for summary in summaries:
            if summary.get("variant") not in fmt.VARIANTS:
                continue
            if summary.get("unchanged"):
                raw = Path(pair[summary["variant"]]["path"]).read_bytes()
                _require(fmt.sha(raw) == summary["original_sha256"], "A paired canonical original is missing.")
                originals[platform, summary["variant"]] = raw
                continue
            candidates = [Path(path).read_bytes() for path in result.get("paired_original_paths", [])
                          if fmt.sha(Path(path).read_bytes()) == summary["original_sha256"]]
            _require(len(candidates) == 1, "A paired canonical original is missing.")
            originals[platform, summary["variant"]] = candidates[0]
        if not partner_body_changed:
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
        if (not (edits.has_changes(state) or context.get("held_counterpart")) or
                not candidates and (not partner_body_changed or fmt.sha(original) in unchanged)):
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


def expand_scene(path, directory, variant=None, *, platform=None):
    """Recover only canonical originals into a deterministic legacy input ZIP."""
    decoded = fmt.read_package(path)
    manifest, files = decoded["manifest"], decoded["files"]
    if variant is None:
        variant = manifest.get("default_variant", "primary")
    _require(variant in fmt.VARIANTS, "Choose a valid Rina costume variant.")
    # The selected body and edit recipe must come from the same native family.
    if platform is None:
        platform = "android" if "android" in manifest["platforms"] else "ios"
    _require(platform in manifest["platforms"], "The scene costume has no body for the selected platform.")
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
    canonical_faces = {}
    for native, dependencies in manifest["dependencies"].items():
        authoring = manifest.get("face_authoring", {}).get(native)
        reference = authoring["original"] if authoring else dependencies["facedynamic"]
        if reference:
            name = native + "_face.unity"
            members[name] = canonical_faces[native] = files[reference["member"]]
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
    face = manifest.get("face_authoring", {}).get(platform)
    face_recipes = [_json(files[face["recipe"]["member"]])] if face else []
    # The other variant's recipes: rows for parts this view's body lacks are
    # carried into its pair edit (hold_counterpart), never shown or dropped.
    other_recipes = [_json(files[family[role]["recipe"]["member"]]) for family in manifest["authoring"].values()
                     for role in fmt.VARIANTS if role != variant]
    return {"path": str(original_zip), "variant": variant, "platform": platform,
            "recipe": recipe, "face_recipes": face_recipes, "other_recipes": other_recipes,
            "metadata": {**{key: copy.deepcopy(manifest[key]) for key in ("display_name", "source_suit_id", "source_provenance")},
                         "target_member_id": manifest.get("target_member_id", 209),
                         "default_variant": manifest.get("default_variant", "primary"),
                         # The originals ZIP above always declares the face kept
                         # for authoring; only these dependencies say whether
                         # the scene's Mod ZIP ships a face to the game.
                         "face_included": any(row["facedynamic"] is not None for row in manifest["dependencies"].values())}}


def counterpart_face_proof(session, index):
    """Outline records of one declared Rina face, proven by its unmasked body.

    The board body of a masked view does not bind this face's AS/Member
    headMaterial, so its face meshes are listed but not editable there. The
    costume's unmasked body, declared in the same family archive, names this
    exact face: the unchanged outline proof runs on that pair. Returns the
    face's records, or None without such a counterpart.
    """
    from . import model_outlines
    try:
        source = session["sources"][index]
        raw = session["containers"][source["container"]]["raw"]
        if source["member"] is None or not zipfile.is_zipfile(io.BytesIO(raw)):
            return None
        faces, models = _literal_faces(raw), _literal_models(raw)
    except (ValueError, KeyError, IndexError, TypeError, OSError, SyntaxError, zipfile.BadZipFile):
        return None
    platform = next((key for key, value in faces.items() if fmt.sha(value) == source["sha256"]), None)
    body = models.get((platform, "unmasked"))
    if platform is None or body is None or fmt.sha(source["raw"]) != source["sha256"]:
        return None
    # The counterpart is not a session source; it only supplies the proof.
    catalog = model_outlines.catalogue_sources([(edits._inspect(source["raw"]), index),
                                                (edits._inspect(body), len(session["sources"]))])
    return [row for row in catalog["meshes"] if row["sourceIndex"] == index and row.get("runtimeBindings")]


def split_held_face_outlines(session, rows):
    """Separate face outline rows this view lists but cannot edit.

    A masked Rina view lists its face meshes as not editable. A saved row for
    one of them is held when the costume's own unmasked body proves that face
    (counterpart_face_proof): it is carried unchanged into every save. Any
    other row stays in ``rows`` and keeps its strict validation.
    """
    catalog = session.get("outlines", {})
    editable = {row["id"] for row in catalog.get("meshes", [])}
    excluded = {row["id"] for row in catalog.get("excludedMeshes", [])}
    candidates = [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)
                  and row["id"] not in editable and row["id"] in excluded]
    proofs = {}
    for row in candidates:
        index = row["id"].split(":", 1)[0]
        if index.isdigit() and int(index) < len(session["sources"]) and index not in proofs:
            proofs[index] = counterpart_face_proof(session, int(index)) or []
    proof = [record for records in proofs.values() for record in records]
    proven = {record["id"] for record in proof}
    held = [row for row in candidates if row["id"] in proven]
    if not held:
        return rows, [], None
    from . import model_outlines
    return ([row for row in rows if row not in held], model_outlines.validate({"meshes": proof}, held),
            {"meshes": proof})


def register_reopened(token, scene):
    """Restore a recipe only after the exact selected raw source is recovered."""
    session = edits._session(token)
    recipe = copy.deepcopy(scene["recipe"])
    def bind(value):
        matches = [index for index, source in enumerate(session["sources"])
                   if source["sha256"] == value["sources"][0]["sha256"]]
        _require(len(matches) == 1, "The scene recipe lost its canonical original identity.")
        index = matches[0]
        for identity in value["nodeIdentities"]:
            identity["sourceIndex"] = index
        for field in ("physics", "outlines"):
            if value["state"].get(field):
                value["state"][field] = [{**row, "id": str(index) + ":" + row["id"].split(":", 1)[1]}
                                        for row in value["state"][field]]
        if value["state"].get("textures"):
            value["state"]["textures"] = [{**row, "texture": {**row["texture"], "source": index}}
                                          for row in value["state"]["textures"]]
        return value
    bind(recipe)
    for face in copy.deepcopy(scene.get("face_recipes", [])):
        bind(face)
        _require(not face["nodeIdentities"] and not face["state"].get("edits") and not face["state"].get("physics"),
                 "The face authoring recipe contains unsupported model changes.")
        # The masked view draws Rina's board over this face, so its face
        # meshes are not editable here; restore holds those rows and every
        # save carries them unchanged (split_held_face_outlines).
        for field in ("textures", "outlines"):
            if face["state"].get(field):
                recipe["state"].setdefault(field, []).extend(face["state"][field])
    recipe["sources"] = edits._source_signature(session)
    recipe["originals"] = [{"name": item["name"], "sha256": item["sha256"]} for item in session["containers"]]
    session["allowEmptySceneReset"] = True
    state = edits.restore(token, recipe)
    hold_counterpart(session, scene.get("other_recipes", []))
    with _LOCK:
        _SCENES[token] = copy.deepcopy(scene["metadata"])
        while len(_SCENES) > edits.MAX_SESSIONS:
            _SCENES.popitem(last=False)
    return state


def hold_counterpart(session, recipes):
    """Keep the other variant's own outline, physics and texture rows for pair editing.

    A reopened scene shows one variant. Rows that only the other variant's
    parts have (the board's Mask meshes in the Normal face view, the Normal
    face's hair dyna bones in the board view) and that variant's own texture
    edits (textures are never mirrored) cannot appear here, but every Mod ZIP
    of this view rewrites that variant: pair editing writes them back
    (viewer_mod_pair_edits). Each entry names the original it binds.
    """
    held = []
    for recipe in recipes:
        state = recipe.get("state", {})
        rows = {field: copy.deepcopy(state[field]) for field in ("outlines", "physics", "textures") if state.get(field)}
        if rows and len(recipe.get("sources", [])) == 1:
            held.append({"sha256": recipe["sources"][0]["sha256"], **rows})
    session["heldCounterpart"] = held


BINDING_FORMAT = "elichika-viewer-scene-binding"
# Held rows may carry the other variant's texture PNGs (both platforms).
MAX_BINDING_BYTES = 64 * 1024 * 1024


def remember_saved_originals(token, context, paths):
    """Keep a reopened scene beside the originals copy its save wrote.

    Saving a reopened scene copies its canonical originals ZIP unchanged to the
    export's originals/ folder, which Re-edit from original opens. The scene
    (its metadata, the view's variant and the other variant's held rows) is
    written next to it as ``edits.SCENE_BINDING``, bound to that file's name
    and bytes, so a re-edit in any later session reopens the scene. The
    person's own copy of the same original, without that file beside it, or a
    save of an ordinary costume, stays what it is (register_preserved).
    """
    if len(context["containers"]) != 1 or len(paths) != 1:
        return
    metadata = session_metadata(token)
    if metadata is None:
        return
    original = Path(paths[0])
    binding = {"format": BINDING_FORMAT, "version": 1,
               "original": {"file": original.name, "sha256": context["containers"][0]["sha256"]},
               "variant": context["variants"].get("0", "primary"), "metadata": metadata,
               "held": copy.deepcopy(edits._session(token).get("heldCounterpart", []))}
    encoded = json.dumps(binding, ensure_ascii=False, allow_nan=False).encode("utf-8")
    _require(len(encoded) <= MAX_BINDING_BYTES, "The reopened scene is too large to keep beside its saved originals.")
    target = original.with_name(edits.SCENE_BINDING)
    temporary = original.with_name(".viewer-scene-" + secrets.token_hex(8) + ".part")
    try:
        with temporary.open("xb") as output:
            output.write(encoded)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _binding_metadata(metadata, platforms):
    """The scene metadata a binding may carry, checked as a scene manifest's.

    ``face_included`` (whether the scene's Mod ZIP shipped a runtime face) is
    absent from bindings written before it existed; those count as no face.
    """
    keys = {"display_name", "source_suit_id", "source_provenance", "target_member_id", "default_variant"}
    if type(metadata) is not dict or set(metadata) not in (keys, keys | {"face_included"}):
        return None
    if "face_included" in metadata and type(metadata["face_included"]) is not bool:
        return None
    name, source, provenance = metadata["display_name"], metadata["source_suit_id"], metadata["source_provenance"]
    target, default = metadata["target_member_id"], metadata["default_variant"]
    if (not isinstance(name, str) or name != name.strip() or not 0 < len(name) <= 120 or any(ord(char) < 32 for char in name)
            or not (source is None or type(source) is int and 0 < source < 10 ** 12) or (source is None) != (provenance is None)
            or type(target) is not int or not 0 < target < 2 ** 31 or default not in fmt.VARIANTS
            or target == 209 and default != "primary"):
        return None
    if provenance is not None:
        if type(provenance) is not dict or not provenance or not set(provenance) <= {"gl", "jp"}:
            return None
        for region in provenance.values():
            if type(region) is not dict or set(region) != platforms:
                return None
            for family in region.values():
                if type(family) is not dict or set(family) != set(fmt.VARIANTS):
                    return None
                for descriptor in family.values():
                    if (type(descriptor) is not dict or set(descriptor) != {"asset_path", "pack_name", "head", "size", "key1", "key2"}
                            or not all(isinstance(descriptor[key], str) and 0 < len(descriptor[key]) <= 512 for key in ("asset_path", "pack_name"))
                            or not all(type(descriptor[key]) is int for key in ("head", "size", "key1", "key2"))):
                        return None
    return metadata


def _held_rows(held):
    """Held counterpart rows as hold_counterpart writes them; pair editing
    validates every row again against the counterpart itself."""
    fields = {"outlines", "physics", "textures"}
    if type(held) is not list or len(held) > 8:
        return None
    for entry in held:
        if (type(entry) is not dict or not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64
                or not set(entry) - {"sha256"} <= fields
                or any(type(entry[field]) is not list or any(type(row) is not dict for row in entry[field])
                       for field in set(entry) - {"sha256"})):
            return None
    return held


def _read_binding(container):
    """The scene kept beside an opened originals copy, or None."""
    import unicodedata
    path = Path(container["path"])
    sidecar = path.with_name(edits.SCENE_BINDING)
    try:
        if sidecar.is_symlink() or not sidecar.is_file() or sidecar.stat().st_size > MAX_BINDING_BYTES:
            return None
        binding = json.loads(sidecar.read_bytes().decode("utf-8"))
        models = _literal_models(container["raw"])
    except (OSError, ValueError, SyntaxError, KeyError, zipfile.BadZipFile, RecursionError):
        return None
    platforms = {platform for platform, _ in models}
    if (type(binding) is not dict or set(binding) != {"format", "version", "original", "variant", "metadata", "held"}
            or binding["format"] != BINDING_FORMAT or type(binding["version"]) is not int or binding["version"] != 1
            or type(binding["original"]) is not dict or set(binding["original"]) != {"file", "sha256"}
            or not isinstance(binding["original"]["file"], str)
            or unicodedata.normalize("NFC", binding["original"]["file"]) != unicodedata.normalize("NFC", path.name)
            or binding["original"]["sha256"] != container["sha256"] or binding["variant"] not in fmt.VARIANTS
            # Only a complete Rina board/bare family is a scene's originals.
            or not platforms or set(models) != {(platform, variant) for platform in platforms for variant in fmt.VARIANTS}
            or _binding_metadata(binding["metadata"], platforms) is None or _held_rows(binding["held"]) is None):
        return None
    return binding


def register_preserved(token, context):
    """Bind a re-edit of a saved scene's originals copy to that scene.

    Opening an originals copy with the scene kept beside it
    (remember_saved_originals), with unchanged bytes, packages a scene Mod ZIP
    with the scene's name, source and face authoring, as reopening the scene
    ZIP does, and keeps the other variant's own rows when it opens in the
    saved view's variant. ``context`` is the session's mod_source_context.
    Returns the scene metadata, or None for any other input.
    """
    if len(context["containers"]) != 1:
        return None
    entry = _read_binding(context["containers"][0])
    if entry is None:
        return None
    with _LOCK:
        _SCENES[token] = copy.deepcopy(entry["metadata"])
        while len(_SCENES) > edits.MAX_SESSIONS:
            _SCENES.popitem(last=False)
    session = edits._session(token)
    session["allowEmptySceneReset"] = True
    if context["variants"].get("0", "primary") == entry["variant"]:
        session["heldCounterpart"] = entry["held"]
    return copy.deepcopy(entry["metadata"])


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
    runtime_faces = {platform: extras.get("costume_facedynamic_file_ios" if platform == "ios" and "android" in platforms else "costume_facedynamic_file")
                     for platform in platforms}
    face_authoring = _face_originals_and_recipes(context, result, platforms, runtime_faces)
    manifest = {"format": fmt.FORMAT, "version": fmt.SHARED_VERSION, "requires": [fmt.SHARED_CAPABILITY],
                "character_id": 209, "target_member_id": previous.get("target_member_id", 209),
                "default_variant": previous.get("default_variant", "primary"),
                "display_name": packed["display_name"], "platforms": {}, "canonical_goldens": {},
                "authoring": {}, "thumbnail": None, "dependencies": {}, "navi_sync": {},
                "source_suit_id": source_id, "source_provenance": provenance}
    if face_authoring:
        manifest["requires"].append(fmt.FACE_AUTHORING_CAPABILITY)
        manifest["face_authoring"] = {}
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
        if platform in face_authoring:
            original, recipe = face_authoring[platform]
            manifest["face_authoring"][platform] = {
                "original": store(f"originals/{platform}_face.unity", original, platform),
                "recipe": store(f"recipes/{platform}_face.json", json.dumps(recipe, allow_nan=False).encode())}
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
            "thumbnail": ({**packed["thumbnail"], "member": "thumbnail.png"} if packed.get("thumbnail") else None),
            "format": fmt.FORMAT, "version": fmt.SHARED_VERSION, "scene_roles": manifest["platforms"],
            "target_member_id": manifest["target_member_id"], "default_variant": manifest["default_variant"],
            "identity_proofs": proofs, "canonical_goldens": manifest["canonical_goldens"]}
