"""Replace an existing costume Mod ZIP thumbnail without repacking its models.

Only literal legacy manifests and the validated scene envelope are supported.
No installer is imported or executed, and originals are never written.
"""
from contextlib import contextmanager
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import tempfile
from types import SimpleNamespace
import zipfile

from . import viewer_archive, viewer_scene_format as scene_format

MAX_ITEMS = 128
MAX_PNG = 3 * 1024 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MODELS = ("costume_file", "rina_unmask_costume_file", "costume_file_ios", "rina_unmask_costume_file_ios",
           "costume_facedynamic_file", "costume_facedynamic_file_ios")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source(value):
    from webtools import filebrowser
    _require(isinstance(value, (str, os.PathLike)) and bool(str(value)), "Choose an existing costume Mod ZIP.")
    supplied = Path(value).expanduser()
    _require(not supplied.is_symlink(), "A costume Mod ZIP cannot be a symbolic link.")
    path = supplied.resolve()
    _require(filebrowser.is_within_allowed(str(path)), "The costume ZIP is outside the allowed folders.")
    _require(path.is_file() and 0 < path.stat().st_size <= viewer_archive.MAX_ARCHIVE_BYTES,
             "Choose a costume ZIP within the supported size limit.")
    return path


def _owner(value):
    from .charinfo import NAMES
    _require(type(value) is int and value in NAMES, "The costume Mod ZIP must declare a known recipient member.")
    return value


def _literal(raw):
    _require(len(raw) <= viewer_archive.MAX_MANIFEST_BYTES, "The costume manifest is too large.")
    try:
        text = raw.decode("utf-8-sig")
        parsed = ast.parse(text)
        values, nodes = {}, {}
        for node in parsed.body:
            _require(isinstance(node, ast.Assign) and len(node.targets) == 1 and
                     isinstance(node.targets[0], ast.Name),
                     "Only costume manifests with literal assignments can have their thumbnail replaced.")
            key = node.targets[0].id
            _require(key not in values, "The costume manifest has ambiguous duplicate assignments.")
            values[key], nodes[key] = ast.literal_eval(node.value), node.value
        return values, nodes, text
    except (SyntaxError, UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise ValueError("The costume manifest contains unsupported dynamic or invalid settings; it was not executed.") from error


def _reference(value, manifest, available, label):
    _require(isinstance(value, str) and value, "The costume manifest is missing " + label + ".")
    relative = PurePosixPath(value.replace("\\", "/"))
    _require(not relative.is_absolute() and ".." not in relative.parts and "\0" not in value and
             not any(":" in part for part in relative.parts), "The costume manifest has an unsafe asset reference.")
    member = str(PurePosixPath(manifest.replace("\\", "/")).parent / relative)
    _require(member in available, "The costume manifest references a missing " + label + ".")
    return available[member]


def inspect(value, *, variant="auto", expected_sha=None):
    """Private bounded source snapshot; the returned raw bytes stay server-side."""
    path = _source(value)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
             "The costume ZIP changed while it was being read.")
    digest = _sha(raw)
    _require(expected_sha is None or digest == expected_sha, "The costume ZIP changed after its thumbnail was rendered.")
    _require(variant in ("auto", "primary", "unmasked"), "Choose a valid costume thumbnail variant.")
    if scene_format.is_scene_package(raw):
        decoded = scene_format.read_package(raw)
        manifest = decoded["manifest"]
        selected = manifest.get("default_variant", "primary") if variant == "auto" else variant
        owner = _owner(manifest.get("target_member_id", manifest["character_id"]))
        return {"path": str(path), "sha256": digest, "raw": raw, "format": "scene", "characterId": owner,
                "variant": selected, "decoded": decoded}
    scene_format._directory(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            available, folded, files, total = {}, set(), {}, 0
            for info in infos:
                name = str(viewer_archive._entry_path(info))
                _require(name.casefold() not in folded, "The costume ZIP contains duplicate asset paths.")
                folded.add(name.casefold())
                available[name] = info.filename
                total += info.file_size
                _require(total <= viewer_archive.MAX_UNPACKED_BYTES, "The costume ZIP expands beyond the size limit.")
                files[info.filename] = archive.read(info)
            manifests = [info.filename for info in infos if not info.is_dir() and
                         PurePosixPath(info.filename.replace("\\", "/")).name.casefold() == "modinstall.txt"]
            _require(len(manifests) == 1, "Choose a costume Mod ZIP with exactly one literal modinstall.txt manifest.")
            manifest = manifests[0]
            values, _, _ = _literal(files[manifest])
            owner = _owner(values.get("chara_id"))
            models = {}
            for key in _MODELS:
                entry = values.get(key)
                if not entry:
                    continue
                models[key] = _reference(entry, manifest, available, key)
                _require(viewer_archive._model_header(files[models[key]][:48], len(files[models[key]])),
                         "The costume manifest does not reference a Unity model.")
            _require("costume_file" in models, "The costume Mod ZIP has no primary model.")
            selected = "primary" if variant == "auto" else variant
            if selected == "unmasked":
                _require(owner == 209 and ("rina_unmask_costume_file" in models or "rina_unmask_costume_file_ios" in models),
                         "This costume has no declared Rina unmasked variant.")
            return {"path": str(path), "sha256": digest, "raw": raw, "format": "legacy", "characterId": owner,
                    "variant": selected, "manifest": manifest, "values": values, "files": files,
                    "infos": infos, "comment": archive.comment, "models": models}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError("The costume Mod ZIP could not be read.") from error


def render_options(params):
    """Normalize the relevant form options; extra job/plan fields are ignored."""
    from webtools import filebrowser
    from webtools.tools.common import parse_multi_paths
    _require(isinstance(params, dict), "Invalid costume thumbnail replacement options.")
    mode = params.get("mode", "single")
    _require(mode in ("single", "multi"), "Choose Single or Selected files for existing Mod ZIPs.")
    variant = params.get("variant", "auto")
    _require(variant in ("auto", "primary", "unmasked"), "Choose a valid costume thumbnail variant.")
    value = params.get("thumbnail_size", 256)
    _require(type(value) is not bool, "Choose a thumbnail size between 64 and 1024.")
    try:
        size = int(str(value))
    except (ValueError, TypeError) as error:
        raise ValueError("Choose a whole thumbnail size between 64 and 1024.") from error
    _require(64 <= size <= 1024, "Choose a thumbnail size between 64 and 1024.")
    fit_full = params.get("thumbnail_fit_full", False)
    _require(type(fit_full) is bool, "Choose whether to fit the full character in its thumbnail.")
    supplied = params.get("out_dir")
    _require(isinstance(supplied, str) and supplied, "Choose an output folder for the new costume ZIP copies.")
    root = Path(supplied).expanduser()
    _require(not root.is_symlink(), "The output folder cannot be a symbolic link.")
    root = root.resolve()
    _require(filebrowser.is_within_allowed(str(root)), "The output folder is outside the allowed folders.")
    _require(not root.exists() or root.is_dir(), "Choose an output directory.")
    multi = [str(_source(path)) for path in parse_multi_paths(params)]
    single = str(_source(params.get("in_path"))) if mode == "single" else ""
    selected = multi if mode == "multi" else [single]
    _require(1 <= len(selected) <= MAX_ITEMS and len(set(selected)) == len(selected),
             "Choose one to 128 different costume Mod ZIPs.")
    return {"mode": mode, "in_path": single, "in_paths": multi, "out_dir": str(root),
            "thumbnail_size": size, "variant": variant, "thumbnail_fit_full": fit_full}


def plan_inputs(params):
    binding = render_options(params)
    paths = binding["in_paths"] if binding["mode"] == "multi" else [binding["in_path"]]
    items = []
    for path in paths:
        source = inspect(path, variant=binding["variant"])
        items.append({"paths": [path], "source_hashes": [[path, source["sha256"]]],
                      "characterId": source["characterId"], "variant": source["variant"], "format": source["format"]})
    return {"binding": binding, "items": items, "size": binding["thumbnail_size"]}


@contextmanager
def render_inputs(path, cache_root, expected_sha=None, *, variant="auto"):
    """Open current executable scene models, never unedited authoring originals."""
    source = inspect(path, variant=variant, expected_sha=expected_sha)
    if source["format"] == "legacy":
        # An ordinary costume has one primary model but offers no selectable
        # variant family. The archive default already chooses primary; an
        # explicit choice is only needed for Rina's unmasked alternative.
        choices = {source["path"]: "unmasked"} if source["variant"] == "unmasked" else None
        with viewer_archive.expand_inputs([source["path"]], cache_root,
                variant_choices=choices) as expanded:
            expanded.render_sources = list(expanded.paths)
            yield expanded
        return
    manifest, files = source["decoded"]["manifest"], source["decoded"]["files"]
    platform = "android" if "android" in manifest["platforms"] else "ios"
    role = "mv_unmasked" if source["variant"] == "unmasked" else "mv_board"
    root_member = manifest["platforms"][platform][role]["member"]
    members = [root_member]
    graph = manifest.get("execution_model_graph", {}).get(platform)
    if graph:
        visited = set()
        def visit(key):
            if key in visited:
                return
            visited.add(key)
            node = graph["nodes"][key]
            member = node["resource"]["member"]
            if member not in members:
                members.append(member)
            for dependency in node["model_dependencies"]:
                visit(dependency)
        visit(graph["role_bindings"][role])
    cache = Path(cache_root)
    _require(not cache.is_symlink(), "The thumbnail render cache cannot be a symbolic link.")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thumbnail-scene-", dir=cache) as directory:
        paths = []
        for index, member in enumerate(members):
            target = Path(directory) / (str(index) + ".unity")
            target.write_bytes(files[member])
            paths.append(str(target))
        yield SimpleNamespace(paths=paths, origins={item: source["path"] for item in paths},
                              render_sources=[paths[0]], variant=source["variant"])


def _legacy_bytes(source, png):
    values, nodes, text = _literal(source["files"][source["manifest"]])
    relative = "renderedthumbnail" + secrets.token_hex(8) + ".png"
    member = str(PurePosixPath(source["manifest"].replace("\\", "/")).parent / relative)
    _require(member.casefold() not in {name.casefold() for name in source["files"]}, "The new thumbnail asset name collides with an existing asset.")
    raw = text.encode("utf-8")
    node = nodes.get("thumbnail_file")
    if node is None:
        raw += ("\nthumbnail_file = " + repr(relative) + "\n").encode("utf-8")
    else:
        offsets = [0]
        for line in raw.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        start = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        raw = raw[:start] + repr(relative).encode() + raw[end:]
    if source["files"][source["manifest"]].startswith(b"\xef\xbb\xbf"):
        raw = b"\xef\xbb\xbf" + raw
    _require(len(raw) <= viewer_archive.MAX_MANIFEST_BYTES, "The updated costume manifest is too large.")
    _require(len(source["infos"]) + 1 <= viewer_archive.MAX_ENTRIES and
             sum(map(len, source["files"].values())) - len(source["files"][source["manifest"]]) + len(raw) + len(png)
             <= viewer_archive.MAX_UNPACKED_BYTES, "The new thumbnail exceeds the costume ZIP entry or unpacked-size limit.")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.comment = source["comment"]
        for info in source["infos"]:
            archive.writestr(copy.copy(info), raw if info.filename == source["manifest"] else source["files"][info.filename])
        archive.writestr(member, png, compress_type=zipfile.ZIP_DEFLATED)
    output = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        changed, _, _ = _literal(archive.read(source["manifest"]))
        original = dict(values); original["thumbnail_file"] = relative
        _require(changed == original and archive.comment == source["comment"], "The costume manifest changed beyond its thumbnail reference.")
        for name, payload in source["files"].items():
            if name != source["manifest"]:
                _require(archive.read(name) == payload, "A preserved costume ZIP asset changed.")
        _require(archive.read(member) == png, "The new thumbnail changed while writing.")
    return output, member, source["manifest"]


def _scene_bytes(source, png):
    manifest = copy.deepcopy(source["decoded"]["manifest"])
    files = dict(source["decoded"]["files"])
    previous = manifest["thumbnail"]
    member = previous["member"] if previous is not None else "thumbnail-" + secrets.token_hex(8) + ".png"
    if previous is None:
        _require(member not in files, "The new scene thumbnail name collides with an existing resource.")
    files[member] = png
    manifest["thumbnail"] = scene_format.reference(member, png)
    raw = scene_format.encode_package(manifest, files)
    with zipfile.ZipFile(io.BytesIO(source["raw"])) as original:
        comment = original.comment
    if comment:
        preserved = io.BytesIO(raw)
        with zipfile.ZipFile(preserved, "a") as archive:
            archive.comment = comment
        raw = preserved.getvalue()
    verified = scene_format.read_package(raw)
    original = copy.deepcopy(source["decoded"]["manifest"])
    original["thumbnail"] = manifest["thumbnail"]
    _require(verified["manifest"] == original, "The scene settings changed beyond the thumbnail reference.")
    for name, payload in source["decoded"]["files"].items():
        if previous is None or name != previous["member"]:
            _require(verified["files"][name] == payload, "A preserved scene model or setting resource changed.")
    return raw, member, scene_format.MANIFEST


def replace(path, output_dir, thumbnail, *, size=256, variant="auto", should_stop=lambda: False):
    """Atomically publish a new source/member-bound thumbnail ZIP copy."""
    _require(type(size) is int and 64 <= size <= 1024, "Choose a whole thumbnail size between 64 and 1024.")
    source = inspect(path, variant=variant)
    _require(isinstance(thumbnail, dict), "Prepare an automatic 3D thumbnail before updating the ZIP.")
    _require(thumbnail.get("source_path") == source["path"] and thumbnail.get("source_sha256") == source["sha256"],
             "The rendered thumbnail belongs to a different or changed costume ZIP.")
    _require(type(thumbnail.get("character_id")) is int and thumbnail["character_id"] == source["characterId"],
             "The rendered thumbnail belongs to another recipient member.")
    _require(thumbnail.get("variant") == source["variant"], "The rendered thumbnail belongs to another costume variant.")
    _require(thumbnail.get("size") == size, "The rendered thumbnail size changed. Render it again.")
    png = thumbnail.get("png")
    _require(type(png) is bytes and 0 < len(png) <= MAX_PNG and png.startswith(b"\x89PNG\r\n\x1a\n") and
             thumbnail.get("sha256") == _sha(png), "The rendered thumbnail bytes changed or are not a bounded PNG.")
    _require(all(isinstance(thumbnail.get(key), str) and _SHA.fullmatch(thumbnail[key]) for key in ("profile_digest", "cache_key")),
             "The rendered thumbnail has no source/template binding.")
    quality = thumbnail.get("quality")
    _require(isinstance(quality, dict) and quality.get("renderer") == "SifasMaterial" and quality.get("highQuality") is True,
             "The thumbnail was not prepared with the high-quality 3D renderer.")
    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        _require(image.format == "PNG" and image.size == (size, size), "The PNG dimensions do not match the selected thumbnail size.")
        image.verify()
    _require(not should_stop(), "Thumbnail replacement was cancelled.")
    data, member, manifest = (_scene_bytes(source, png) if source["format"] == "scene" else _legacy_bytes(source, png))
    _require(len(data) <= viewer_archive.MAX_ARCHIVE_BYTES, "The updated costume ZIP exceeds the size limit.")
    from webtools import filebrowser
    root = Path(output_dir).expanduser()
    _require(not root.is_symlink(), "The output folder cannot be a symbolic link.")
    root = root.resolve()
    _require(filebrowser.is_within_allowed(str(root)), "The output folder is outside the allowed folders.")
    root.mkdir(parents=True, exist_ok=True)
    stem = Path(source["path"]).stem.encode("utf-8")[:120].decode("utf-8", errors="ignore")
    target = root / (stem + "-thumbnail-" + secrets.token_hex(8) + ".zip")
    temporary = None
    reserved = False
    try:
        with tempfile.NamedTemporaryFile(prefix=".thumbnail-", suffix=".zip", dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        current = _source(source["path"])
        _require(current.stat().st_size == len(source["raw"]) and _file_sha(current) == source["sha256"],
                 "The original costume ZIP changed during thumbnail replacement.")
        _require(not should_stop(), "Thumbnail replacement was cancelled.")
        # Exclusive reservation prevents an existing user output being replaced.
        # Replacing our own empty reservation is atomic even on FUSE volumes
        # where hard links are unavailable.
        with target.open("xb"):
            reserved = True
        os.replace(temporary, target)
        temporary = None
        reserved = False
        return {"source_path": source["path"], "source_sha256": source["sha256"],
                "output_path": str(target), "sha256": _sha(data), "bytes": len(data),
                "character_id": source["characterId"], "thumbnail_member": member, "thumbnail_sha256": _sha(png),
                "manifest_member": manifest, "format": source["format"], "variant": source["variant"], "size": size,
                "profile_digest": thumbnail["profile_digest"], "cache_key": thumbnail["cache_key"],
                "quality": copy.deepcopy(quality), "originals_preserved": True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if reserved:
            target.unlink(missing_ok=True)
