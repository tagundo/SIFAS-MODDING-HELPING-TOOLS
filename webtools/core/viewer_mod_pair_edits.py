"""Apply source-relative body edits to declared costume/platform variants.

Pairs use their own immutable sources and writable rigs. Numeric Unity IDs,
preview animation and filenames never establish correspondence between rigs.
"""
import ast
import copy
import io
import json
from pathlib import Path, PurePosixPath
import secrets
import shutil
import tempfile
import zipfile

from . import model_edits as edits
from . import model_viewer
from . import viewer_mod_sources as sources


def _check(job):
    if job.should_stop():
        raise InterruptedError("Paired body editing was cancelled.")


def _zip_declarations(raw):
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return []
    from .viewer_archive import _entry_path, MAX_ENTRIES, MAX_MANIFEST_BYTES
    from .charinfo import NAMES
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ValueError("The paired costume ZIP has too many members.")
        members, total = {}, 0
        for info in entries:
            relative = _entry_path(info)
            key = str(relative).casefold()
            total += info.file_size
            if key in members or total > sources.MAX_BYTES:
                raise ValueError("The paired costume ZIP has duplicate or oversized members.")
            members[key] = info
        output = []
        fields = {"chara_id", "costume_file", "rina_unmask_costume_file", "costume_file_ios", "rina_unmask_costume_file_ios"}
        for key, info in members.items():
            if PurePosixPath(key).name != "modinstall.txt":
                continue
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ValueError("The paired costume manifest is too large.")
            values = {}
            try:
                tree = ast.parse(archive.read(info).decode("utf-8-sig"))
            except (SyntaxError, UnicodeError):
                # Opaque legacy metadata is not a declared family. Ordinary
                # raw export preserves it; installer packaging validates it.
                continue
            try:
                # Raw save also passes through this mapper. A legacy/generic
                # manifest without an explicit owner declares no trusted family
                # here; preserve its existing raw-save behavior unchanged.
                if not any(isinstance(node, ast.Assign) and len(node.targets) == 1 and
                           isinstance(node.targets[0], ast.Name) and node.targets[0].id == "chara_id"
                           for node in tree.body):
                    continue
                literal = True
                for node in tree.body:
                    if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                            isinstance(node.targets[0], ast.Name) and node.targets[0].id in fields):
                        name = node.targets[0].id
                        try:
                            value = ast.literal_eval(node.value)
                        except (ValueError, TypeError, RecursionError):
                            literal = False
                            break
                        if name in values and values[name] != value:
                            raise ValueError("The paired costume manifest has conflicting values.")
                        values[name] = value
                if not literal:
                    continue
            except (TypeError, RecursionError) as error:
                raise ValueError("The paired costume manifest is not a safe literal declaration.") from error
            owner = values.get("chara_id")
            if owner is None:
                continue
            rina = owner == 209
            # One explicit installer manifest establishes the costume family.
            # A lone ordinary model has no counterpart to edit, and unrelated
            # files never become partners merely because their rigs match.
            if not rina and not (values.get("costume_file") and values.get("costume_file_ios")):
                continue
            if isinstance(owner, bool) or not isinstance(owner, int) or owner not in NAMES:
                raise ValueError("The paired costume manifest must declare a known character.")
            if not rina and any(values.get(field) for field in
                                ("rina_unmask_costume_file", "rina_unmask_costume_file_ios")):
                raise ValueError("Only Rina may declare board and unmasked costume variants.")
            selected = []
            digests = set()
            explicit_ios = bool(values.get("costume_file_ios") or values.get("rina_unmask_costume_file_ios"))
            for platform, main, other in (("android", "costume_file", "rina_unmask_costume_file"),
                                          ("ios", "costume_file_ios", "rina_unmask_costume_file_ios")):
                if not values.get(main) and not values.get(other):
                    continue
                # Legacy iOS-only installers put their iOS model in the main
                # fields. An explicit *_ios alternative makes the main fields
                # Android; without it, preserve a concrete same-platform pair.
                expected_platform = platform if explicit_ios else None
                role_platform = None
                for field in (main, other) if rina else (main,):
                    value = values.get(field)
                    if not isinstance(value, str) or not value:
                        raise ValueError("Each declared platform must include its complete costume variants.")
                    relative = PurePosixPath(value.replace("\\", "/"))
                    if relative.is_absolute() or ".." in relative.parts or any(":" in p for p in relative.parts):
                        raise ValueError("The paired costume has an unsafe model reference.")
                    member = members.get(str(PurePosixPath(key).parent / relative).casefold())
                    if member is None or member.is_dir():
                        raise ValueError("A declared costume variant is missing from its original ZIP.")
                    model_raw = archive.read(member)
                    facts, digest = sources._model_facts(model_raw), sources._sha(model_raw)
                    # A known literal manifest owner is the user's explicit
                    # family declaration. Costume transplants may retain donor
                    # texture names, so those cannot override that declaration.
                    # Platform identity still comes from each original Unity
                    # asset; no platform is copied or converted from another.
                    if (not facts["platform"] or
                            expected_platform is not None and facts["platform"] != expected_platform or
                            role_platform is not None and facts["platform"] != role_platform):
                        raise ValueError("The declared costume variants must match their Android/iOS platform.")
                    role_platform = facts["platform"]
                    if digest in digests:
                        raise ValueError("One model cannot stand in for distinct costume/platform variants.")
                    digests.add(digest)
                    selected.append(member.filename)
            if len(selected) not in (2, 4) or len(set(selected)) != len(selected):
                raise ValueError("A paired Mod ZIP must declare two or four distinct costume variants.")
            output.append(selected)
        return output


def apply_pair_edits(context, result, state, *, pair, job):
    """Return a completed export plus an edited counterpart, or an honest no-op."""
    _check(job)
    declarations = [_zip_declarations(item["raw"]) for item in context["containers"]]
    if pair is None and not any(declarations):
        return {"result": result, "pair": None, "summary": []}
    return _apply(context, result, state, pair=pair, declarations=declarations, job=job)


def _hierarchy(info, anchored):
    """Semantic paths retain every hierarchy segment; there is no leaf fallback."""
    paths, active = {}, set()
    def visit(key):
        if key in paths:
            return paths[key]
        if key in active or len(active) > 256:
            raise ValueError("A paired model has a circular transform hierarchy.")
        active.add(key)
        name = info["names"][key]
        if not isinstance(name, str) or not name:
            raise ValueError("A paired bone has no semantic hierarchy identity.")
        parent = info["parents"].get(key)
        if anchored and name == "Move":
            path = ("sifas-skeleton", "Move")
        elif parent in info["transforms"]:
            path = visit(parent) + (name,)
        else:
            path = ("complete-hierarchy", name)
        active.remove(key)
        paths[key] = path
        return path
    for key in info["transforms"]:
        visit(key)
    inverse = {}
    for key, path in paths.items():
        inverse.setdefault(path, []).append(key)
    return paths, inverse


def _key(node):
    try:
        return int(node["serializedFile"]), int(node["transformId"])
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("An edited bone has no source-bound Unity identity.") from error


def _relative(kind, desired, source_base, target_base):
    import numpy as np
    desired, source_base, target_base = (np.asarray(value, dtype=float) for value in (desired, source_base, target_base))
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in (desired, source_base, target_base)):
        raise ValueError("A paired body edit contains an invalid transform.")
    if kind == "scale":
        if (np.abs(source_base) < 1e-8).any():
            raise ValueError("A source scale cannot be used as a paired-edit baseline.")
        return (desired / source_base * target_base).tolist()
    if kind == "position":
        return (target_base + desired - source_base).tolist()
    if kind == "rotation":
        # Quaternion-equivalent composition in Unity's existing Ry @ Rx @ Rz
        # convention. Adding Euler components would fail for rotated baselines.
        matrix = edits._euler_matrix(desired) @ edits._euler_matrix(source_base).T @ edits._euler_matrix(target_base)
        return edits._matrix_euler(matrix)
    raise ValueError("This paired transform property is unsupported.")


def _map_state(context, state, source_index, source_info, target_context, target_info):
    source_nodes = {node["node"]: node for node in context["nodes"] if node["sourceIndex"] == source_index}
    target_nodes = {_key(node): node for node in target_context["nodes"]}
    move_counts = [sum(name == "Move" for name in info["names"].values()) for info in (source_info, target_info)]
    if any(count > 1 for count in move_counts):
        raise ValueError("A paired rig has ambiguous duplicate Move skeleton roots.")
    anchored = move_counts == [1, 1]
    source_paths, source_inverse = _hierarchy(source_info, anchored)
    _, target_inverse = _hierarchy(target_info, anchored)
    mapping = {}
    def mapped(ident):
        if ident in mapping:
            return mapping[ident]
        source = source_nodes.get(ident)
        if source is None:
            raise ValueError("A paired edit refers to a different source model.")
        key = _key(source)
        if key not in source_paths or source_info["names"][key] != source["name"]:
            raise ValueError("An edited bone no longer matches its immutable source.")
        path = source_paths[key]
        candidates = target_inverse.get(path, [])
        if len(source_inverse[path]) != 1 or len(candidates) != 1:
            raise ValueError("The counterpart is missing a unique matching bone hierarchy: " + source["name"])
        target = target_nodes.get(candidates[0])
        if target is None:
            raise ValueError("The counterpart bone is not writable: " + source["name"])
        source_base = edits._public_trs(source_info["effective"][key])
        target_base = edits._public_trs(target_info["effective"][candidates[0]])
        mapping[ident] = (source, target, source_base, target_base, path)
        return mapping[ident]
    converted, required_references = [], set()
    for row in state["edits"]:
        if row["node"] not in source_nodes:
            continue
        source, target, source_base, target_base, _ = mapped(row["node"])
        if row["method"] not in target["methods"]:
            raise ValueError("The counterpart cannot preserve the selected save method: " + source["name"])
        change = {"node": target["node"], "method": row["method"], "compensate": row.get("compensate", False)}
        for kind in ("scale", "position", "rotation"):
            if kind in row:
                change[kind] = _relative(kind, row[kind], source_base[kind], target_base[kind])
        if row.get("compensate"):
            change["compensationTargets"] = [mapped(ident)[1]["node"] for ident in row["compensationTargets"]]
            # ref_world only depends on these ancestor chains. Unrelated face
            # reference rows must not force an unjustified face-bone mapping.
            for ident in [row["node"], *row["compensationTargets"]]:
                key = _key(source_nodes[ident])
                seen = set()
                while key in source_info["transforms"]:
                    if key in seen:
                        raise ValueError("A compensation reference hierarchy is circular.")
                    seen.add(key)
                    required_references.add(key)
                    key = source_info["parents"].get(key)
        converted.append(change)
    if not converted and "accessoryUnclip" not in state:
        raise ValueError("There are no source-bound body edits to apply to the counterpart.")
    references = []
    for row in state.get("compensationReference", []):
        source = source_nodes.get(row["node"])
        if source is None or _key(source) not in required_references:
            continue
        baseline = edits._public_trs(source_info["effective"][_key(source)])
        import numpy as np
        if (np.allclose(row["scale"], baseline["scale"], rtol=1e-8, atol=1e-8) and
                np.allclose(row["position"], baseline["position"], rtol=1e-8, atol=1e-8) and
                np.allclose(edits._euler_matrix(row["rotation"]), edits._euler_matrix(baseline["rotation"]), rtol=1e-8, atol=1e-8)):
            # No relative reference change: the partner's own baseline is
            # already the correct ref_local default. This also avoids treating
            # different cosmetic wrappers as corresponding semantic bones.
            continue
        _, target, source_base, target_base, _ = mapped(row["node"])
        references.append({"node": target["node"], **{
            kind: _relative(kind, row[kind], source_base[kind], target_base[kind])
            for kind in ("scale", "position", "rotation")}})
    translated = {"version": edits.VERSION, "savedSettingsEnabled": True, "unsupported": [],
                  "edits": converted, "compensationReference": references}
    if "accessoryUnclip" in state:
        translated["accessoryUnclip"] = copy.deepcopy(state["accessoryUnclip"])
    proof = [{"sourceNode": ident, "targetNode": row[1]["node"], "hierarchy": list(row[4]),
              "sourceUnity": list(_key(row[0])), "targetUnity": list(_key(row[1]))}
             for ident, row in mapping.items()]
    return translated, proof


def _edit_partner(context, state, source_index, original_raw, folder, job):
    _check(job)
    source = context["sources"][source_index]
    container = context["containers"][source["container"]]
    source_raw = container["raw"]
    if source["member"] is not None:
        with zipfile.ZipFile(io.BytesIO(source_raw)) as archive:
            source_raw = archive.read(source["member"])
    if sources._sha(source_raw) != source["sha256"]:
        raise ValueError("The selected source changed before paired editing.")
    model_viewer._preflight_bundle(original_raw)
    folder.mkdir()
    original = folder / "counterpart.unity"
    original.write_bytes(original_raw)
    prepared = model_viewer.prepare([str(original)], rigged=True,
        face_context={"enabled": False, "allow_download": False})
    token = prepared["id"]
    try:
        metadata = edits.register_session(token, [str(original)], prepared["rig"])
        if metadata.get("available") is not True:
            raise ValueError("The counterpart has no writable body rig.")
        partner_context = edits.mod_source_context(token)
        translated, proof = _map_state(context, state, source_index, edits._inspect(source_raw),
                                       partner_context, edits._inspect(original_raw))
        normalized = edits.validate_state(token, translated)
        _check(job)
        exported = edits.export(token, normalized, folder / "export", log=job.log)
        _check(job)
        output = Path(exported["preview_paths"][0])
        output_raw = sources._read(output)
        # Export itself reloads endpoints and meshes. Keep the source receipt and
        # independently inspect completed bytes before making any ZIP visible.
        edits._inspect(output_raw)
        if original.read_bytes() != original_raw:
            raise ValueError("A counterpart original changed during paired editing.")
        return {"raw": output_raw, "sha256": sources._sha(output_raw),
                "original_sha256": sources._sha(original_raw), "export": exported,
                "mapping": proof}
    finally:
        # These are internal temporary rigs, not extra user editor sessions.
        with edits._LOCK:
            edits._SESSIONS.pop(token, None)
        with model_viewer._CACHE_LOCK:
            model_viewer._SESSIONS.pop(token, None)


def _replace_zip(saved_path, destination, replacements):
    saved_raw = sources._read(saved_path)
    with zipfile.ZipFile(io.BytesIO(saved_raw)) as incoming, zipfile.ZipFile(destination, "w") as outgoing:
        outgoing.comment = incoming.comment
        pending = dict(replacements)
        for entry in incoming.infolist():
            value = pending.pop(entry.filename) if entry.filename in pending else incoming.read(entry)
            outgoing.writestr(copy.copy(entry), value)
        if pending:
            raise ValueError("A saved costume ZIP is missing a declared variant.")
    with zipfile.ZipFile(io.BytesIO(saved_raw)) as incoming, zipfile.ZipFile(destination) as checked:
        if incoming.namelist() != checked.namelist() or incoming.comment != checked.comment:
            raise ValueError("The paired ZIP changed unrelated archive structure.")
        for entry in incoming.infolist():
            expected = replacements[entry.filename] if entry.filename in replacements else incoming.read(entry)
            if checked.read(entry.filename) != expected:
                raise ValueError("A paired ZIP failed its completed-member reload check.")
    return sources._sha(saved_raw)


def _apply(context, result, state, *, pair, declarations, job):
    containers, _ = sources._snapshots(context)
    if (not isinstance(result, dict) or not isinstance(result.get("preview_paths"), list) or
            len(result["preview_paths"]) != len(containers)):
        raise ValueError("The saved costume model lost its original container identity.")
    root = Path(result["recipe_path"]).resolve().parent
    temporary = Path(tempfile.mkdtemp(prefix=".paired-body-", dir=root))
    final = root / ("paired-body-" + secrets.token_hex(8))
    output = copy.deepcopy(result)
    new_pair = copy.deepcopy(pair)
    summaries, replaced_paths, partner_exports = [], {}, []
    initial = {str(Path(path).resolve()): sources._sha(sources._read(path)) for path in result["preview_paths"]}
    try:
        count = 0
        if pair is not None:
            roles = {}
            for role in ("primary", "unmasked"):
                item = pair[role]
                path = str(Path(item["path"]).resolve())
                raw = sources._read(path)
                if sources._sha(raw) != item["sha256"]:
                    raise ValueError("A Rina role changed before paired body editing.")
                roles[role] = (path, raw)
            selected = [(index, source, role) for index, source in enumerate(context["sources"])
                        if source["member"] is None for role, (path, _) in roles.items()
                        if str(Path(result["preview_paths"][source["container"]]).resolve()) == path]
            if len(selected) != 1:
                raise ValueError("The selected Rina body cannot be uniquely bound to its pair.")
            index, source, role = selected[0]
            other = "unmasked" if role == "primary" else "primary"
            path, raw = roles[other]
            edited = _edit_partner(context, state, index, raw, temporary / f"variant-{count}", job)
            count += 1
            target = edited["export"]["preview_paths"][0]
            new_pair[other] = {"path": target, "sha256": edited["sha256"]}
            initial[path] = sources._sha(raw)
            partner_exports.append(edited["export"])
            summaries.append({"variant": other, **{key: edited[key] for key in ("original_sha256", "sha256", "mapping")}})
        else:
            for ci, groups in enumerate(declarations):
                if not groups:
                    continue
                replacements, claimed = {}, set()
                for members in groups:
                    selected = [(index, source) for index, source in enumerate(context["sources"])
                                if source["container"] == ci and source["member"] in members and
                                ("accessoryUnclip" in state or
                                 any(row["node"] in {node["node"] for node in context["nodes"] if node["sourceIndex"] == index}
                                     for row in state["edits"]))]
                    if not selected:
                        continue
                    # With no authored node changes, every opened counterpart
                    # already received its own original-bound accessory pass.
                    # Only unopened family members need separate derivation.
                    already_selected = {row[1]["member"] for row in selected} if not state["edits"] else set()
                    if already_selected:
                        selected = selected[:1]
                    if len(selected) != 1:
                        raise ValueError("Multiple edited costume variants would conflict in one paired ZIP.")
                    index, source = selected[0]
                    with zipfile.ZipFile(io.BytesIO(containers[ci]["raw"])) as archive:
                        for member in members:
                            if member == source["member"] or member in already_selected:
                                continue
                            if member in claimed:
                                raise ValueError("Two paired declarations target the same costume member.")
                            claimed.add(member)
                            raw = archive.read(member)
                            edited = _edit_partner(context, state, index, raw, temporary / f"variant-{count}", job)
                            count += 1
                            replacements[member] = edited["raw"]
                            partner_exports.append(edited["export"])
                            summaries.append({"member": member, **{key: edited[key] for key in ("original_sha256", "sha256", "mapping")}})
                if replacements:
                    saved = str(Path(result["preview_paths"][ci]).resolve())
                    destination = temporary / f"paired-{ci}.zip"
                    if _replace_zip(saved, destination, replacements) != initial[saved]:
                        raise ValueError("The selected saved ZIP changed during paired editing.")
                    replaced_paths[saved] = str(destination)
        if not summaries:
            shutil.rmtree(temporary)
            return {"result": result, "pair": pair, "summary": []}
        _check(job)
        for path, digest in initial.items():
            if sources._sha(sources._read(path)) != digest:
                raise ValueError("A costume input changed while paired edits were being saved.")
        receipt = {"format": "elichika-paired-body-edit", "version": 1,
                   "sourceOriginals": [{"name": row["name"], "sha256": row["sha256"]} for row in containers],
                   "targets": summaries}
        (temporary / "paired-recipe.json").write_text(json.dumps(receipt, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        temporary.rename(final)
        def published(path):
            value = Path(path)
            return str(final / value.relative_to(temporary)) if value.is_relative_to(temporary) else str(value)
        for field in ("preview_paths", "output_paths"):
            output[field] = [published(replaced_paths.get(str(Path(path).resolve()), path)) for path in output[field]]
        recipes, originals = [], []
        for exported in partner_exports:
            recipes.append(published(exported["recipe_path"]))
            originals.extend(published(path) for path in exported["original_paths"])
        output["paired_recipe_paths"] = recipes + [str(final / "paired-recipe.json")]
        output["paired_original_paths"] = originals
        output["output_paths"] = list(dict.fromkeys(output["output_paths"] + output["paired_recipe_paths"]))
        if new_pair is not None:
            for role in ("primary", "unmasked"):
                new_pair[role]["path"] = published(new_pair[role]["path"])
        return {"result": output, "pair": new_pair, "summary": summaries}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
