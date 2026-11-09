"""Source-bound costume operations for the shared 3D editing workspace.

The existing transplant tools do the actual Unity work. This adapter gives them
an immutable donor and a copy of the current body edits, and replaces only the
displayed model member when the wearer came from an archive.
"""
import copy
import hashlib
import io
import math
from pathlib import Path
import secrets
import shutil
import tempfile
import zipfile

from webtools import filebrowser
from webtools.core import model_edits, viewer_archive

MAX_DONOR_BYTES = 96 * 1024 * 1024
OPERATIONS = {"costume", "part", "lower"}


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


def inspect_donor(path, variant="primary", *, cache_root):
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
            parts = part_root_options({"donor": model})
            return {"name": donor.name, "parts": parts, "platform": _platform(model),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "cutPresets": [
                        {"value": "hip_fix", "label": "Knee to waist", "low": .5, "high": .96},
                        {"value": "calf", "label": "Calf to waist", "low": .3, "high": .96},
                        {"value": "ankle", "label": "Ankle to waist", "low": .11, "high": .96},
                        {"value": "custom", "label": "Custom range"}]}


def validate_request(params):
    if not isinstance(params, dict) or set(params) != {
            "token", "state", "donor", "variant", "operation", "partRoot", "cutLow", "cutHigh", "region"}:
        raise ValueError("Unsupported costume transplant request.")
    operation = params.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("Choose a costume transplant operation.")
    if params.get("variant") not in ("primary", "unmasked"):
        raise ValueError("Choose a valid donor costume variant.")
    part = params.get("partRoot")
    if not isinstance(part, str) or len(part) > 256 or operation == "part" and not part:
        raise ValueError("Choose the donor part root bone.")
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
    return {**copy.deepcopy(params), "state": state, "donorName": donor.name,
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
                      "match_skin": True, "match_thigh": False}
            if operation == "costume":
                costume.run_costume_transplant(job, params)
            elif operation == "part":
                available = {item["value"] for item in costume.part_root_options({"donor": donor_model})}
                if request["partRoot"] not in available:
                    raise ValueError("The selected part no longer exists in the donor costume.")
                costume.run_costume_part_transplant(job, {**params,
                    "part_root": request["partRoot"], "new_submesh": True})
            else:
                costume.run_lower_body_swap(job, {**params, "cut": "custom", "region": request["region"],
                    "cut_low": request["cutLow"], "cut_high": request["cutHigh"], "exclude_accessories": True})
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
