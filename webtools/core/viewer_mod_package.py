"""Installer ZIPs from completed, server-authorized viewer exports.

This module does not resolve arbitrary request paths or install anything. The
HTTP integration supplies the completed source-bound export and, for a raw
Rina costume, both prepared variants after the same body edits are propagated.
The resolver supplies their explicit primary/unmasked roles and hashes.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import tempfile
import time
import unicodedata
import zipfile

from . import viewer_archive

_NAMES = ("costume_name_en", "costume_name_ko", "costume_name_zh",
          "costume_name_ja", "costume_description")
_MODELS = ("costume_file", "rina_unmask_costume_file", "costume_file_ios",
           "rina_unmask_costume_file_ios")
_ASSET_REFS = _MODELS + ("thumbnail_file", "costume_facedynamic_file", "costume_facedynamic_file_ios")
_SUPPORTED_CONFIG = _NAMES + ("chara_id",) + _ASSET_REFS + ("chara_id_append", "id_costume", "id_trade_product")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class ModPackageError(ValueError):
    pass


def _require(value, message):
    if not value:
        raise ModPackageError(message)


def _stop(should_stop):
    if should_stop():
        raise InterruptedError("Mod packaging was cancelled.")


def _sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _file(value):
    _require(isinstance(value, (str, os.PathLike)), "The saved model path is invalid.")
    path = Path(value)
    _require(not path.is_symlink(), "Saved models must not be symbolic links.")
    path = path.resolve(strict=True)
    _require(path.is_file() and 0 < path.stat().st_size <= viewer_archive.MAX_ARCHIVE_BYTES,
             "The saved model is missing or exceeds the packaging limit.")
    return path


def _owner(value):
    from .charinfo import NAMES
    _require(isinstance(value, int) and not isinstance(value, bool) and value in NAMES,
             "Choose a known costume character before creating its Mod ZIP.")
    return value


def _display(value):
    _require(isinstance(value, str) and value.strip() and len(value) <= 200 and "\0" not in value,
             "Enter a costume name of between one and 200 characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ModPackageError("The costume name must contain valid Unicode text.") from error
    return value


def _packer():
    from .repo import ensure_repo_on_path
    ensure_repo_on_path()
    import unity_costumemod_packer
    return unity_costumemod_packer


def _raw_identity(path, packer, requested=None):
    names = packer._bundle_texture_names(str(path))
    owners = {packer.extract_chara_id_from_texture_name(name) for name in names}
    owners.discard(None)
    if requested is not None:
        # A validated transplant/installer owner can differ from the donor's
        # retained texture names. Source hints only decide automatic identity.
        owner = _owner(requested)
    else:
        _require(len(owners) <= 1, "This model has ambiguous costume characters. Package one costume at a time.")
        observed = next(iter(owners), None)
        owner = _owner(observed if observed is not None else packer.extract_chara_id_from_filename(path.stem))
    platform = packer.detect_bundle_platform(str(path))
    _require(platform in ("android", "ios"), "The model platform is unknown. Choose an original Android or iOS costume bundle.")
    return owner, platform


def _arcname(path, packer):
    proposed = Path(packer.safe_arc_name(path.name))
    stem = packer.pack_safe_stem(proposed.stem)[:80]
    if not re.search("[a-z]", stem):
        stem = "costume" + stem
    extension = proposed.suffix if re.fullmatch(r"\.[A-Za-z]{1,10}", proposed.suffix) else ".unity"
    name = stem + extension
    return "costume" + name if name.casefold() in ("thumbnail.png", "modinstall.txt") else name


def _manifest(raw, display_name):
    _require(len(raw) <= viewer_archive.MAX_MANIFEST_BYTES, "The costume manifest exceeds the packaging limit.")
    try:
        text = raw.decode("utf-8-sig")
        tree = ast.parse(text)
        values, nodes = {}, {}
        for node in tree.body:
            _require(isinstance(node, ast.Assign) and len(node.targets) == 1 and
                     isinstance(node.targets[0], ast.Name),
                     "Use an installer manifest containing literal assignments only.")
            key = node.targets[0].id
            _require(key not in values, "The costume manifest contains ambiguous duplicate assignments.")
            values[key] = ast.literal_eval(node.value)
            nodes[key] = node.value
        encoded = text.encode("utf-8")
        offsets = [0]
        for line in encoded.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        replacement = repr(display_name).encode("utf-8")
        ranges = [(offsets[nodes[key].lineno - 1] + nodes[key].col_offset,
                   offsets[nodes[key].end_lineno - 1] + nodes[key].end_col_offset)
                  for key in _NAMES if key in nodes]
        for start, end in sorted(ranges, reverse=True):
            encoded = encoded[:start] + replacement + encoded[end:]
        for key in _NAMES:
            if key not in nodes:
                encoded += ("\n" + key + " = " + repr(display_name) + "\n").encode("utf-8")
        return values, encoded
    except (SyntaxError, UnicodeError, ValueError, TypeError, RecursionError) as error:
        if isinstance(error, ModPackageError):
            raise
        raise ModPackageError("The costume manifest must contain bounded literal assignments.") from error


def _reference(value, available, label):
    _require(isinstance(value, str) and value, "The costume manifest is missing " + label + ".")
    relative = PurePosixPath(value.replace("\\", "/"))
    _require(not relative.is_absolute() and ".." not in relative.parts and
             not any(":" in part for part in relative.parts) and "\0" not in value,
             "The costume manifest contains an unsafe file reference.")
    _require(str(relative) in available, "The costume manifest references a missing " + label + ".")
    return str(relative)


def _generic_archive(incoming, infos, target, temporary, display_name, requested, packer, should_stop, log):
    """Convert one clear model; retain unrelated files under extras/ unchanged."""
    models, extras = [], []
    for info in infos:
        if info.is_dir():
            continue
        _stop(should_stop)
        with incoming.open(info) as stream:
            header = stream.read(48)
        (models if viewer_archive._model_header(header, info.file_size) else extras).append(info)
    _require(len(models) == 1, "Choose a generic costume ZIP containing exactly one Unity model; unrelated models cannot be combined.")
    selected = models[0]
    name = PurePosixPath(selected.filename.replace("\\", "/")).name
    extracted = temporary / "generic" / name
    viewer_archive._copy_member(incoming, selected, extracted)
    owner, platform, _, references, _ = _raw([extracted], target, temporary, display_name,
        requested, None, packer, should_stop, log)
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as outgoing:
        outgoing.comment = incoming.comment
        for info in extras:
            _stop(should_stop)
            copied = copy.copy(info)
            copied.filename = copied.orig_filename = "extras/" + str(viewer_archive._entry_path(info))
            with incoming.open(info) as data, outgoing.open(copied, "w") as output:
                shutil.copyfileobj(data, output, 65536)
    with zipfile.ZipFile(target) as reloaded:
        for info in extras:
            _stop(should_stop)
            name = "extras/" + str(viewer_archive._entry_path(info))
            _require(_member_sha(reloaded, name) == _member_sha(incoming, info),
                     "An unrelated costume ZIP file changed while packaging.")
    return owner, platform, "packed_single_model_archive", references


def _existing(source, target, temporary, display_name, requested, packer, should_stop, log):
    viewer_archive._preflight_zip(source)
    with zipfile.ZipFile(source) as incoming:
        infos = incoming.infolist()
        _require(1 <= len(infos) <= viewer_archive.MAX_ENTRIES, "The costume ZIP contains too many files.")
        available, manifests, total = {}, [], 0
        for info in infos:
            relative = str(viewer_archive._entry_path(info))
            _require(relative.casefold() not in available, "The costume ZIP contains duplicate file paths.")
            available[relative.casefold()] = info
            total += info.file_size
            if PurePosixPath(relative).name.lower() == "modinstall.txt" and not info.is_dir():
                manifests.append(info)
        _require(total <= viewer_archive.MAX_UNPACKED_BYTES, "The costume ZIP expands beyond the packaging limit.")
        if not manifests:
            return (*_generic_archive(incoming, infos, target, temporary, display_name,
                                     requested, packer, should_stop, log), None)
        _require(len(manifests) == 1, "Choose one installer costume ZIP with exactly one modinstall.txt manifest.")
        manifest = manifests[0]
        source_manifest = incoming.read(manifest)
        values, renamed = _manifest(source_manifest, display_name)
        owner = _owner(values.get("chara_id"))
        _require(requested is None or _owner(requested) == owner, "The selected character differs from the costume manifest.")
        exact = {str(viewer_archive._entry_path(info)): info for info in infos if not info.is_dir()}
        references, platforms = {}, {}
        for key in _MODELS:
            value = values.get(key, "")
            _require(isinstance(value, str), "The costume manifest has an invalid model reference.")
            if not value:
                continue
            name = _reference(value, exact, key)
            _require(name not in references.values(), "The costume manifest reuses one model for conflicting roles.")
            references[key] = name
            destination = temporary / (key + ".unity")
            with incoming.open(exact[name]) as stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output, 65536)
            _, platforms[key] = _raw_identity(destination, packer, owner)
            _stop(should_stop)
        _require("costume_file" in references, "The installer costume ZIP is missing its primary costume file.")
        if "costume_file_ios" in references:
            _require(platforms["costume_file"] == "android" and platforms["costume_file_ios"] == "ios",
                     "The costume ZIP has mismatched Android and iOS roles.")
        for primary, other in (("costume_file", "rina_unmask_costume_file"),
                               ("costume_file_ios", "rina_unmask_costume_file_ios")):
            if primary not in references:
                _require(other not in references, "The costume ZIP has an unpaired Rina variant.")
                continue
            if owner == 209:
                _require(other in references, "Rina's Mod ZIP must include both the board and no-mask costume variants.")
                _require(platforms[other] == platforms[primary], "Rina's paired costumes must use the same platform.")
        thumbnail = values.get("thumbnail_file", "")
        _require(isinstance(thumbnail, str), "The costume thumbnail reference is invalid.")
        if thumbnail:
            _reference(thumbnail, exact, "thumbnail_file")
        with zipfile.ZipFile(target, "w") as outgoing:
            outgoing.comment = incoming.comment
            for info in infos:
                _stop(should_stop)
                copied = copy.copy(info)
                if info is manifest:
                    outgoing.writestr(copied, renamed)
                else:
                    with incoming.open(info) as data, outgoing.open(copied, "w") as output:
                        shutil.copyfileobj(data, output, 65536)
        with zipfile.ZipFile(target) as reloaded:
            _require(reloaded.namelist() == incoming.namelist() and reloaded.comment == incoming.comment,
                     "The renamed installer ZIP failed reload validation.")
            for info in infos:
                _stop(should_stop)
                expected = hashlib.sha256(renamed).hexdigest() if info is manifest else _member_sha(incoming, info)
                _require(_member_sha(reloaded, info.filename) == expected, "A preserved costume ZIP member changed unexpectedly.")
    platform = "android+ios" if "costume_file_ios" in references else platforms["costume_file"]
    return owner, platform, "preserved_installer_zip", references, source_manifest


def _member_sha(archive, info):
    with archive.open(info) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _namespace_assets(target, temporary, display_name, should_stop, source_manifest=None):
    """Emit one canonical executable config; preserve other text/ZIPs inertly."""
    normalized = temporary / "namespaced.zip"
    with zipfile.ZipFile(target) as incoming:
        infos = incoming.infolist()
        _require(len(infos) <= viewer_archive.MAX_ENTRIES and
                 sum(info.file_size for info in infos) <= viewer_archive.MAX_UNPACKED_BYTES,
                 "The completed installer ZIP exceeds the packaging limit.")
        exact = {str(viewer_archive._entry_path(info)): info for info in infos if not info.is_dir()}
        manifests = [info for info in infos if not info.is_dir() and
                     PurePosixPath(info.filename.replace("\\", "/")).name.lower() == "modinstall.txt"]
        _require(len(manifests) == 1, "The completed installer ZIP needs one manifest.")
        manifest = manifests[0]
        raw = incoming.read(manifest)
        values, _ = _manifest(raw, display_name)
        _require(all(values.get(key) == display_name for key in _NAMES), "The Mod ZIP lost its costume name.")
        prefix = "v" + secrets.token_hex(8)
        references, renamed = {}, {}
        for key in _ASSET_REFS:
            value = values.get(key, "")
            _require(isinstance(value, str), "The costume manifest has an invalid asset reference.")
            if not value:
                continue
            source = _reference(value, exact, key)
            _require(exact[source] is not manifest, "An installer asset cannot reference its manifest.")
            extension = ".png" if key == "thumbnail_file" else ".unity"
            name = prefix + "role" + str(len(references) + 1) + extension
            _require(name.casefold() not in {entry.casefold() for entry in exact},
                     "A generated asset namespace collides with an existing ZIP entry. Create another copy.")
            references[key] = name
            renamed.setdefault(source, []).append(name)
        append = values.get("chara_id_append")
        canonical = {key: values[key] for key in _NAMES}
        canonical["chara_id"] = _owner(values.get("chara_id"))
        canonical.update({key: references.get(key, "") for key in _ASSET_REFS})
        canonical.update(chara_id_append=None if append is None else _owner(append),
                         id_costume=None, id_trade_product=None)
        encoded = ("\n".join(key + " = " + repr(canonical[key]) for key in _SUPPORTED_CONFIG) + "\n").encode("utf-8")
        _require(len(encoded) <= viewer_archive.MAX_MANIFEST_BYTES, "The canonical costume manifest exceeds the packaging limit.")
        # Legacy installers execute every .txt and recursively inspect every
        # .zip. Keep original metadata and companion payloads byte-identical,
        # but outside those active extensions. Reserve unchanged names first.
        occupied = {"modinstall.txt"} | {name.casefold() for name in references.values()}
        file_names = set()
        for info in infos:
            original = str(viewer_archive._entry_path(info))
            if info is not manifest and original not in renamed and (info.is_dir() or
                    not info.filename.lower().endswith((".txt", ".zip"))):
                occupied.add(original.casefold())
                if not info.is_dir():
                    file_names.add(original.casefold())
        def available(candidate):
            base, ordinal = candidate, 2
            while candidate.casefold() in occupied:
                candidate = base + "." + str(ordinal) + ".data"
                ordinal += 1
            occupied.add(candidate.casefold())
            return candidate
        metadata_member = None
        if source_manifest is not None:
            folder, ordinal = "metadata", 2
            while folder.casefold() in file_names:
                folder = "metadata" + str(ordinal)
                ordinal += 1
            metadata_member = available(folder + "/source-modinstall.txt.data")
        moves = {}
        for info in infos:
            original = str(viewer_archive._entry_path(info))
            if info is manifest:
                moves[original] = ["modinstall.txt"]
            elif original in renamed:
                moves[original] = renamed[original]
            elif not info.is_dir() and info.filename.lower().endswith((".txt", ".zip")):
                moves[original] = [available(original + ".data")]
            else:
                moves[original] = [info.filename]
        with zipfile.ZipFile(normalized, "w") as outgoing:
            outgoing.comment = incoming.comment
            for info in infos:
                _stop(should_stop)
                original = str(viewer_archive._entry_path(info))
                for name in moves[original]:
                    copied = copy.copy(info)
                    copied.filename = copied.orig_filename = name
                    if info is manifest:
                        outgoing.writestr(copied, encoded)
                    else:
                        with incoming.open(info) as data, outgoing.open(copied, "w") as output:
                            shutil.copyfileobj(data, output, 65536)
            if metadata_member is not None:
                outgoing.writestr(metadata_member, source_manifest)
        with zipfile.ZipFile(normalized) as reloaded:
            _require(len(reloaded.infolist()) <= viewer_archive.MAX_ENTRIES and
                     sum(info.file_size for info in reloaded.infolist()) <= viewer_archive.MAX_UNPACKED_BYTES,
                     "The namespaced installer ZIP exceeds the packaging limit.")
            _require(len(reloaded.namelist()) == len({str(viewer_archive._entry_path(info)).casefold() for info in reloaded.infolist()}) and
                     reloaded.comment == incoming.comment, "The namespaced ZIP failed reload validation.")
            active = [name for name in reloaded.namelist() if name.lower().endswith((".txt", ".zip"))]
            final_config, _ = _manifest(reloaded.read("modinstall.txt"), display_name)
            _require(active == ["modinstall.txt"] and final_config == canonical and
                     set(final_config) == set(_SUPPORTED_CONFIG), "The installer ZIP contains active companion code or unsupported settings.")
            if metadata_member is not None:
                _require(reloaded.read(metadata_member) == source_manifest, "The preserved source manifest changed.")
            for info in infos:
                _stop(should_stop)
                original = str(viewer_archive._entry_path(info))
                expected = hashlib.sha256(encoded).hexdigest() if info is manifest else _member_sha(incoming, info)
                for name in moves[original]:
                    _require(_member_sha(reloaded, name) == expected,
                             "A namespaced installer asset changed its bytes.")
    normalized.replace(target)
    return references, prefix, metadata_member


def _raw(paths, target, temporary, display_name, requested, pair, packer, should_stop, log):
    if pair is not None:
        _require(isinstance(pair, dict) and pair.get("owner") == 209 and not isinstance(pair.get("owner"), bool),
                 "The Rina counterpart resolver did not provide a valid pair.")
        _require(requested is None or _owner(requested) == 209, "The selected character differs from the Rina pair.")
        roles = {}
        for role in ("primary", "unmasked"):
            record = pair.get(role)
            _require(isinstance(record, dict) and isinstance(record.get("sha256"), str) and _SHA.fullmatch(record["sha256"]),
                     "Rina's Mod ZIP requires verified board and no-mask counterparts.")
            path = _file(record.get("path"))
            _require(_sha(path) == record["sha256"], "A Rina counterpart changed after selection. Reopen the costume.")
            roles[role] = path
        _require(roles["primary"] != roles["unmasked"] and set(paths) <= set(roles.values()),
                 "The selected edited costume is not bound to the supplied Rina roles.")
        _require(pair.get("platform") in ("android", "ios"), "The Rina pair has no confirmed platform.")
        for path in roles.values():
            _, platform = _raw_identity(path, packer, 209)
            _require(platform == pair["platform"], "Rina's counterparts do not match the selected platform.")
        main, alternate, owner, platform = roles["primary"], roles["unmasked"], 209, pair["platform"]
    else:
        _require(len(paths) == 1, "Choose one costume to package; unrelated model files cannot share one Mod ZIP.")
        main, alternate = paths[0], None
        owner, platform = _raw_identity(main, packer, requested)
        _require(owner != 209, "Rina's Mod ZIP needs both the board and no-mask variants. Select the matching counterpart first.")
        roles = {"primary": main}
    _require(sum(path.stat().st_size for path in roles.values()) <= viewer_archive.MAX_UNPACKED_BYTES,
             "The prepared costume variants exceed the packaging limit.")
    _stop(should_stop)
    # The existing packer accepts a safe decoder; never enter native texture
    # codecs from an embedded Android request just to create a thumbnail.
    from . import decode
    deadline = time.monotonic() + 30
    _, png = packer._extract_body_texture_core(str(main), log=log,
        image_decoder=lambda texture: decode._android_image(texture, deadline))
    thumbnail = (packer.make_thumbnail_png(png, 256) if png else
                 packer.make_name_thumbnail_png(display_name, 256, owner))
    _require(thumbnail, "The costume thumbnail could not be created.")
    arcs = {"costume_file": _arcname(main, packer)}
    if alternate is not None:
        arcs["rina_unmask_costume_file"] = _arcname(alternate, packer)
        if arcs["rina_unmask_costume_file"].casefold() == arcs["costume_file"].casefold():
            arcs["rina_unmask_costume_file"] = "unmasked" + arcs["rina_unmask_costume_file"]
    # Escape the argument inserted by the existing literal-format generator.
    escaped = json.dumps(display_name, ensure_ascii=False)[1:-1]
    manifest = packer.generate_modinstall_txt(escaped, arcs["costume_file"], "thumbnail.png", owner,
                                             arcs.get("rina_unmask_costume_file"))
    _manifest(manifest.encode("utf-8"), display_name)  # Verify generated literals too.
    _stop(should_stop)
    packer.create_zip_package(str(target), str(main), thumbnail, "thumbnail.png", manifest,
        str(alternate) if alternate else None, masked_arcname=arcs["costume_file"],
        unmasked_arcname=arcs.get("rina_unmask_costume_file"))
    with zipfile.ZipFile(target) as archive:
        for role, path in roles.items():
            key = "costume_file" if role == "primary" else "rina_unmask_costume_file"
            _require(_member_sha(archive, arcs[key]) == _sha(path), "The packaged costume did not preserve its source bytes.")
    return owner, platform, "packed_unity", arcs, roles


def package_saved_export(export_result, output_dir, *, display_name, chara_id=None,
                         pair=None, log=lambda message: None, should_stop=lambda: False):
    """Return an atomic installer ZIP receipt; authorization belongs to the caller.

    Generic ZIPs require exactly one Unity model. Their other non-model files
    remain byte-identical under extras/; empty directories are not copied.
    All referenced installer assets receive fresh per-package names. Companion
    .txt/.zip files gain .data; original settings are inert metadata. All other
    unreferenced entries retain their original names and bytes.
    """
    display_name = _display(display_name)
    _require(isinstance(export_result, dict) and export_result.get("originals_preserved") is True,
             "Finish saving the source-bound costume before creating its Mod ZIP.")
    selected = export_result.get("preview_paths")
    _require(isinstance(selected, (list, tuple)) and 1 <= len(selected) <= viewer_archive.MAX_MODELS,
             "The completed viewer export has no valid costume outputs.")
    paths = [_file(path) for path in selected]
    _require(len(set(paths)) == len(paths), "The saved costume outputs contain duplicate paths.")
    snapshots = {path: _sha(path) for path in paths}
    _require(sum(path.stat().st_size for path in paths) <= viewer_archive.MAX_UNPACKED_BYTES,
             "The saved costumes exceed the packaging limit.")
    _stop(should_stop)
    packer = _packer()
    root = Path(os.path.abspath(output_dir))
    _require(not any(path.is_symlink() for path in (root, *root.parents)), "The Mod ZIP output folder must not use symbolic links.")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".viewer-package-", dir=root))
    try:
        target = temporary / "package.zip"
        source_manifest = None
        if any(zipfile.is_zipfile(path) for path in paths):
            _require(len(paths) == 1 and pair is None, "Choose one installer costume ZIP instead of combining independent archives or models.")
            owner, platform, mode, references, source_manifest = _existing(paths[0], target, temporary, display_name, chara_id, packer, should_stop, log)
        else:
            owner, platform, mode, references, roles = _raw(paths, target, temporary, display_name, chara_id, pair, packer, should_stop, log)
            for role, path in roles.items():
                snapshots[path] = pair[role]["sha256"] if pair is not None else snapshots[path]
        asset_references, asset_namespace, metadata_member = _namespace_assets(target, temporary, display_name, should_stop, source_manifest)
        references = {key: value for key, value in asset_references.items() if key != "thumbnail_file"}
        _stop(should_stop)
        _require(target.stat().st_size <= viewer_archive.MAX_ARCHIVE_BYTES, "The completed Mod ZIP exceeds the packaging limit.")
        for path, expected in snapshots.items():
            _require(_sha(path) == expected, "A saved costume changed during packaging. No Mod ZIP was published.")
        with zipfile.ZipFile(target) as archive:
            members = [{"name": info.filename, "bytes": info.file_size, "sha256": _member_sha(archive, info)}
                       for info in archive.infolist() if not info.is_dir()]
        digest, size = _sha(target), target.stat().st_size
        stem = re.sub(r"[^\w.-]+", "_", unicodedata.normalize("NFC", display_name)).strip("._-")
        stem = stem.encode("utf-8")[:160].decode("utf-8", errors="ignore").strip("._-") or "costume"
        suffix = {"android": "apk", "ios": "ios", "android+ios": "apk-ios"}[platform]
        final = root / (stem + "-" + suffix + "-" + secrets.token_hex(6) + ".zip")
        log("Prepared installer Mod ZIP: " + final.name)
        _stop(should_stop)
        _require(not final.exists(), "The output package already exists. Create a new copy.")
        target.rename(final)
        return {"package_path": str(final), "sha256": digest, "bytes": size,
                "display_name": display_name, "chara_id": owner, "platform": platform,
                "mode": mode, "model_members": references, "members": members,
                "asset_members": asset_references, "asset_namespace": asset_namespace,
                "source_manifest_member": metadata_member,
                "preserved_extras": [member["name"] for member in members
                                     if mode == "packed_single_model_archive" and member["name"].startswith("extras/")],
                "variant_labels": ({"primary": "Rina board", "unmasked": "Rina no-mask"}
                                   if owner == 209 else {"primary": "Costume"})}
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
