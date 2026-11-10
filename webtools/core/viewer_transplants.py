"""Source-bound costume operations for the shared 3D editing workspace.

The existing transplant tools do the actual Unity work. This adapter gives them
an immutable donor and a copy of the current body edits, and replaces only the
displayed model member when the wearer came from an archive.
"""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import zipfile

from webtools import filebrowser
from webtools.core import model_edits, viewer_archive

MAX_DONOR_BYTES = 96 * 1024 * 1024
OPERATIONS = {"costume", "part", "lower"}
MAX_PART_BONES = 512
MAX_PART_TRIANGLES = 200000
PART_SELECTION_FIELDS = {"partSelectionMode", "partRoots", "includeDescendants", "triangleIndices", "donorSha256", "donorMesh", "donorSelectionFingerprint"}
OPTIONAL_FIELDS = {"matchSkin", "skinOnly", "excludeAccessories", "selectionScope", "donorRenderer", "targetRenderer"} | PART_SELECTION_FIELDS


def _geometry(model, renderer=None):
    import UnityPy
    import numpy as np
    import lower_body_swap as lower
    body = lower.BodyMesh(UnityPy.load(model), model, renderer)
    if body.n > 100000 or len(body.tris()) > 200000:
        raise ValueError("The donor mesh exceeds the transplant preview limits.")
    _, positions = lower.band_selection(body, -10, 10, "central", False, "mesh")
    triangles = body.tris()
    names = body.dom_names()
    if not np.isfinite(body.bw).all() or np.any(body.bw < 0):
        raise ValueError("The donor has invalid skin weights.")
    if np.any((body.bw > 0) & ((body.bi < 0) | (body.bi >= len(body.bones)))):
        raise ValueError("The donor skin refers to a missing bone.")
    return {"renderer": str(body.smr_obj.path_id), "mesh": str(body.mesh_obj.path_id),
            "positions": positions.tolist(), "triangles": triangles.tolist(),
            "boneNames": body.bones,
            "skin": [[[int(i), float(w)] for i, w in zip(ids, weights)]
                     for ids, weights in zip(body.bi, body.bw)],
            "anatomy": np.isin(names, list(lower.ANATOMY)).tolist(),
            "regions": {key: np.isin(names, list(value)).tolist() for key, value in lower.REGIONS.items()},
            "components": lower._components(body.pos, triangles, body.n).tolist()}


def _read_donor(path):
    if not isinstance(path, str) or len(path) > 4096:
        raise ValueError("Choose a donor costume file.")
    value = Path(path).resolve()
    if not filebrowser.is_within_allowed(value):
        raise PermissionError("The donor costume is outside the allowed folders.")
    if not value.is_file() or not 0 < value.stat().st_size <= MAX_DONOR_BYTES:
        raise ValueError("Choose a donor costume smaller than 96 MiB.")
    with value.open("rb") as source:
        raw = source.read(MAX_DONOR_BYTES + 1)
    if not 0 < len(raw) <= MAX_DONOR_BYTES:
        raise ValueError("Choose a donor costume smaller than 96 MiB.")
    return value, raw


def _platform(path):
    import UnityPy
    environment = UnityPy.load(str(path))
    values = {int(asset.target_platform) for asset in environment.assets}
    if len(values) != 1:
        raise ValueError("The selected costume has an ambiguous Unity platform.")
    return next(iter(values))


def _donor_model(expanded):
    import UnityPy
    candidates = []
    for path in expanded.paths:
        environment = UnityPy.load(path)
        if any(obj.type.name == "SkinnedMeshRenderer" for obj in environment.objects):
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError("Choose a donor containing one costume model, or select its Unity bundle directly.")
    return candidates[0]


def _selection_fingerprint(model, donor_sha256, variant, geometry):
    values = [donor_sha256, variant, hashlib.sha256(Path(model).read_bytes()).hexdigest(),
              geometry["renderer"], geometry["mesh"]]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def inspect_donor(path, variant="primary", *, cache_root, renderer=None):
    """Return verified part-root choices; inspection never writes to a model."""
    if variant not in ("primary", "unmasked"):
        raise ValueError("Choose a valid donor costume variant.")
    donor, raw = _read_donor(path)
    root = model_edits._safe_root(cache_root)
    with tempfile.TemporaryDirectory(prefix="transplant-inspect-", dir=root) as directory:
        original = Path(directory) / donor.name
        original.write_bytes(raw)
        choices = {str(original): variant} if zipfile.is_zipfile(original) and variant == "unmasked" else None
        with viewer_archive.expand_inputs([str(original)], root, choices) as expanded:
            model = _donor_model(expanded)
            from webtools.tools.costume import part_root_options
            import UnityPy
            env = UnityPy.load(model)
            renderers = []
            for obj in env.objects:
                if obj.type.name != "SkinnedMeshRenderer": continue
                tree = obj.read_typetree()
                if not tree.get("m_Bones", []): continue
                mesh = obj.assets_file.objects.get(tree.get("m_Mesh", {}).get("m_PathID"))
                if mesh is not None:
                    renderers.append({"value": str(obj.path_id), "label": mesh.read_typetree().get("m_Name", "Mesh")})
            if renderer is not None and renderer not in {row["value"] for row in renderers}:
                raise ValueError("Choose a valid skinned donor mesh.")
            geometry = _geometry(model, renderer)
            parts = part_root_options({"donor": model, "donor_renderer": geometry["renderer"]})
            digest = hashlib.sha256(raw).hexdigest()
            return {"name": donor.name, "parts": parts, "platform": _platform(model), "geometry": geometry,
                    "renderers": renderers,
                    "sha256": digest,
                    "selectionFingerprint": _selection_fingerprint(model, digest, variant, geometry),
                    "cutPresets": [
                        {"value": "hip_fix", "label": "Knee to waist", "low": .5, "high": .96},
                        {"value": "calf", "label": "Calf to waist", "low": .3, "high": .96},
                        {"value": "ankle", "label": "Ankle to waist", "low": .11, "high": .96},
                        {"value": "whole", "label": "Whole lower body", "low": -.05, "high": 1.06},
                        {"value": "custom", "label": "Custom range"}]}


def _part_selection(model, params):
    """Resolve a checked UI selection against the immutable donor model."""
    from webtools.tools.costume import part_root_options
    geometry = _geometry(model, params["donorRenderer"] or None)
    if params["donorMesh"] and geometry["mesh"] != params["donorMesh"]:
        raise ValueError("The selected donor mesh changed. Load the donor again.")
    fingerprint = _selection_fingerprint(model, params["donorSha256"], params["variant"], geometry)
    if params["donorSelectionFingerprint"] and params["donorSelectionFingerprint"] != fingerprint:
        raise ValueError("The selected donor variant or mesh changed. Load it again.")
    selected = {"donorRenderer": geometry["renderer"], "donorMesh": geometry["mesh"], "donorSelectionFingerprint": fingerprint}
    if params["partSelectionMode"] == "triangles":
        if any(index >= len(geometry["triangles"]) for index in params["triangleIndices"]):
            raise ValueError("A selected triangle is outside the original donor mesh.")
        return {**selected, "partBones": [], "triangleIndices": params["triangleIndices"]}
    choices = part_root_options({"donor": model, "donor_renderer": geometry["renderer"]})
    available = {item["value"]: item for item in choices}
    roots = params["partRoots"] or [params["partRoot"]]
    if any(root not in available for root in roots):
        raise ValueError("The selected part no longer exists in the donor costume.")
    names = set()
    for root in roots:
        names.update(available[root]["bones"] if params["includeDescendants"] else [root])
    return {**selected, "partBones": [name for name in geometry["boneNames"] if name in names], "triangleIndices": []}


def _resolve_snapshot_selection(raw, name, params):
    with tempfile.TemporaryDirectory(prefix="transplant-selection-") as directory:
        root = Path(directory)
        donor = root / name
        donor.write_bytes(raw)
        choices = {str(donor): params["variant"]} if zipfile.is_zipfile(donor) and params["variant"] == "unmasked" else None
        with viewer_archive.expand_inputs([str(donor)], root / "cache", choices) as expanded:
            return _part_selection(_donor_model(expanded), {**params, "donorSha256": hashlib.sha256(raw).hexdigest()})


def validate_request(params):
    required = {
            "token", "state", "donor", "variant", "operation", "partRoot", "cutLow", "cutHigh", "region"}
    if not isinstance(params, dict) or not required <= set(params) or set(params) - required - OPTIONAL_FIELDS:
        raise ValueError("Unsupported costume transplant request.")
    source_bound = bool(set(params) & PART_SELECTION_FIELDS)
    params = {"matchSkin": False, "skinOnly": True, "excludeAccessories": True,
              "selectionScope": "skin", "donorRenderer": "", "targetRenderer": "",
              "partSelectionMode": "bones", "partRoots": [], "includeDescendants": True,
              "triangleIndices": [], "donorSha256": "", "donorMesh": "", "donorSelectionFingerprint": "", **params}
    for key in ("matchSkin", "skinOnly", "excludeAccessories"):
        if not isinstance(params[key], bool): raise ValueError("Transplant options must be true or false.")
    if params["selectionScope"] not in ("skin", "mesh"):
        raise ValueError("Choose body skin or the selected whole mesh.")
    for key in ("donorRenderer", "targetRenderer", "donorMesh"):
        value = params[key]
        if not isinstance(value, str) or value and (len(value) > 21 or not value.lstrip("-").isdigit()):
            raise ValueError("Choose a valid donor or wearer mesh.")
    operation = params.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("Choose a costume transplant operation.")
    if params.get("variant") not in ("primary", "unmasked"):
        raise ValueError("Choose a valid donor costume variant.")
    part = params.get("partRoot")
    if not isinstance(part, str) or len(part) > 256:
        raise ValueError("Choose the donor part root bone.")
    if params["partSelectionMode"] not in ("bones", "triangles"):
        raise ValueError("Choose bone or donor surface selection.")
    if type(params["includeDescendants"]) is not bool:
        raise ValueError("Choose whether to include child bones.")
    roots = params["partRoots"]
    if (not isinstance(roots, list) or len(roots) > MAX_PART_BONES or
            any(not isinstance(root, str) or not root or len(root) > 256 for root in roots) or len(set(roots)) != len(roots)):
        raise ValueError("Choose valid donor part bones.")
    triangles = params["triangleIndices"]
    if (not isinstance(triangles, list) or len(triangles) > MAX_PART_TRIANGLES or
            any(type(index) is not int or not 0 <= index < MAX_PART_TRIANGLES for index in triangles) or len(set(triangles)) != len(triangles)):
        raise ValueError("Choose valid original donor triangles.")
    for key in ("donorSha256", "donorSelectionFingerprint"):
        if not isinstance(params[key], str) or params[key] and not re.fullmatch(r"[a-f0-9]{64}", params[key]):
            raise ValueError("The donor selection has no valid source identity.")
    if operation == "part":
        if params["partSelectionMode"] == "bones" and not (roots or part):
            raise ValueError("Choose one or more donor part bones.")
        if params["partSelectionMode"] == "triangles" and not triangles:
            raise ValueError("Select donor faces on the model or texture first.")
        if source_bound and not all(params[key] for key in ("donorSha256", "donorRenderer", "donorMesh", "donorSelectionFingerprint")):
            raise ValueError("Load the donor before selecting parts or faces.")
    if params.get("region") not in ("lower", "lower_belly", "central"):
        raise ValueError("Choose a valid lower-body region.")
    for key in ("cutLow", "cutHigh"):
        value = params.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 10:
            raise ValueError("Cut heights must be finite numbers between -10 and 10.")
    if params["cutLow"] >= params["cutHigh"]:
        raise ValueError("The lower cut must be below the upper cut.")
    state = model_edits.validate_state(params["token"], params["state"], allow_empty=True)
    context = model_edits.mod_source_context(params["token"])
    # Separate face/motion inputs have no body joints and are retained by export.
    candidates = {node["sourceIndex"] for node in context["nodes"]
                  if node["name"] in ("Hips", "HipsSize", "Spine", "BreastSize")}
    if len(candidates) != 1:
        raise ValueError("Open one wearer costume model before transplanting.")
    source_index = next(iter(candidates))
    if source_index >= len(context["sources"]):
        raise ValueError("The wearer model editing identity is invalid.")
    container = context["containers"][context["sources"][source_index]["container"]]
    if zipfile.is_zipfile(io.BytesIO(container["raw"])):
        # Different platforms and Rina variants need independently matched
        # donors. Never emit a ZIP whose other installer models remain stale.
        with zipfile.ZipFile(io.BytesIO(container["raw"])) as archive:
            model_count = 0
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                with archive.open(entry) as member:
                    if viewer_archive._model_header(member.read(48), entry.file_size):
                        model_count += 1
            if model_count != 1:
                raise ValueError("For transplanting, open a single Unity costume bundle or a ZIP with one model. Paired platform and Rina ZIPs need separate donor models.")
    donor, raw = _read_donor(params["donor"])
    digest = hashlib.sha256(raw).hexdigest()
    if params["donorSha256"] and params["donorSha256"] != digest:
        raise ValueError("The donor changed after selection. Load it again.")
    selection = _resolve_snapshot_selection(raw, donor.name, params) if operation == "part" else {}
    return {**copy.deepcopy(params), **selection, "state": state, "donorSha256": digest, "donorName": donor.name,
            "donorRaw": raw, "sourceIndex": source_index, "context": context}


def run_transplant(job, request, *, output_root, cache_root, export_fn=None):
    """Save the present edits, graft on a copy, and publish completed outputs.

    ``export_fn`` may include additional physics/mesh edits in the app's combined
    exporter. Its return shape matches model_edits.export.
    """
    root = model_edits._safe_root(output_root)
    cache = model_edits._safe_root(cache_root)
    context = request["context"]
    operation = request["operation"]
    source = context["sources"][request["sourceIndex"]]
    if job.should_stop():
        return "Cancelled"
    job.progress(0, 3)
    job.log("Saving current model edits before transplanting…")
    saved = (export_fn or model_edits.export)(request["token"], request["state"], str(root), log=job.log, allow_empty=True)
    saved_path = Path(saved["preview_paths"][source["container"]])
    pending = Path(tempfile.mkdtemp(prefix=".viewer-transplant-", dir=root))
    try:
        inputs = pending / "inputs"
        models = pending / "models"
        inputs.mkdir(); models.mkdir()
        donor = inputs / request["donorName"]
        donor.write_bytes(request["donorRaw"])
        choices = {str(donor): request["variant"]} if zipfile.is_zipfile(donor) and request["variant"] == "unmasked" else None
        with viewer_archive.expand_inputs([str(donor)], cache, choices) as expanded:
            donor_model = _donor_model(expanded)
            wearer = inputs / "wearer.unity"
            if source["member"] is None:
                shutil.copyfile(saved_path, wearer)
            else:
                with zipfile.ZipFile(saved_path) as archive:
                    wearer.write_bytes(archive.read(source["member"]))
            if _platform(wearer) != _platform(donor_model):
                raise ValueError("The donor and wearer need matching Unity platforms (Android or iOS).")
            if job.should_stop():
                return "Cancelled"
            job.progress(1, 3)
            from webtools.tools import costume
            params = {"mode": "single", "donor": donor_model, "target": str(wearer),
                      "out_dir": str(models), "suffix": "_transplant", "preserve_physics": True,
                      "restore_collision": True, "worldspace": True, "fix_nodescaling": True,
                      "match_skin": request["matchSkin"], "skin_only": request["skinOnly"],
                      "skin_colour_guard": request["skinOnly"], "match_thigh": False}
            if operation == "costume":
                costume.run_costume_transplant(job, params)
            elif operation == "part":
                costume.run_costume_part_transplant(job, {**params,
                    "part_bones": request["partBones"] or None,
                    "triangle_indices": request["triangleIndices"] if request["partSelectionMode"] == "triangles" else None,
                    "donor_renderer": request["donorRenderer"],
                    "target_renderer": request["targetRenderer"] or None, "new_submesh": True})
            else:
                costume.run_lower_body_swap(job, {**params, "cut": "custom", "region": request["region"],
                    "cut_low": request["cutLow"], "cut_high": request["cutHigh"],
                    "exclude_accessories": request["excludeAccessories"], "selection_scope": request["selectionScope"],
                    "donor_renderer": request["donorRenderer"] or None, "target_renderer": request["targetRenderer"] or None})
        changed = models / "wearer_transplant.unity"
        if not changed.is_file() or not changed.stat().st_size:
            raise ValueError("The costume operation did not create a model.")
        # Actual Unity deserialization verifies the resulting bundle before it
        # becomes a selectable viewer output.
        _platform(changed)
        from costume_transplant import validate as validate_model
        if not validate_model(str(changed), verbose=False):
            raise ValueError("The transplanted model has unresolved mesh or bone references. No result was published.")
        result = models / saved_path.name
        if source["member"] is None:
            if result != changed:
                changed.rename(result)
        else:
            with zipfile.ZipFile(saved_path) as incoming, zipfile.ZipFile(result, "w") as outgoing:
                outgoing.comment = incoming.comment
                for entry in incoming.infolist():
                    outgoing.writestr(copy.copy(entry), changed.read_bytes() if entry.filename == source["member"] else incoming.read(entry))
            changed.unlink()
        shutil.rmtree(inputs)
        if job.should_stop():
            return "Cancelled"
        final = root / ("transplant-" + secrets.token_hex(8))
        pending.rename(final); pending = None
        output = str(final / "models" / result.name)
        job.add_output(output)
        job.progress(3, 3)
        job.emit({"type": "transplant", "path": output,
                  "variant": context.get("variants", {}).get(str(source["container"]), "primary"),
                  "archived": source["member"] is not None,
                  "body_recipe": saved.get("recipe_path")})
        return "Costume transplanted onto the displayed model."
    finally:
        if pending is not None:
            shutil.rmtree(pending, ignore_errors=True)
