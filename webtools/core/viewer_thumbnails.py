"""Source-bound automatic SDK costume thumbnails rendered by the app's WebGL view.

Only the short-lived browser render is cached. Model bytes, authoring settings,
recipient, template assets and quality settings all participate in its binding.
Blender and Photoshop are build-time reference tools, never runtime dependencies.
"""
from collections import OrderedDict
from contextlib import ExitStack
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
import time
import zipfile

_ASSETS = Path(__file__).resolve().parents[1] / "web" / "static" / "thumbnail-sdk"
_LOCK = threading.RLock()
_PLANS = OrderedDict()
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
TTL = 1800
MAX_ITEMS = 128
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_PLAN_BYTES = 32 * 1024 * 1024
QUALITY = {"renderer": "SifasMaterial", "highQuality": True, "animation": False, "supersample": 2,
           "rimlight": False, "subject": "head-and-upper-body-v1"}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _profile():
    raw = (_ASSETS / "profile.json").read_bytes()
    profile = json.loads(raw)
    files = sorted(path for path in _ASSETS.iterdir() if path.is_file() and path.suffix in (".png", ".json"))
    digest = _hash(_json([[path.name, _sha(path)] for path in files]))
    return profile, digest


def _owner(value):
    from .charinfo import NAMES
    _require(type(value) is int and value in NAMES, "Choose a valid target member before rendering a 3D thumbnail.")
    return value


def _file(value):
    from webtools import filebrowser
    _require(isinstance(value, str) and value and len(value) <= 4096, "Choose a costume file for its thumbnail.")
    supplied = Path(value).expanduser()
    _require(not supplied.is_symlink(), "A thumbnail source cannot be a symbolic link.")
    path = supplied.resolve()
    _require(filebrowser.is_within_allowed(str(path)), "The thumbnail source is outside the allowed model folders.")
    _require(path.is_file() and 0 < path.stat().st_size <= 256 * 1024 * 1024, "The thumbnail source is missing or too large.")
    return str(path)


def _prune():
    now = time.monotonic()
    for key, value in list(_PLANS.items()):
        if value["expires"] < now:
            if value.get("temporary"):
                shutil.rmtree(value["temporary"], ignore_errors=True)
            del _PLANS[key]


def _plan(token):
    _require(isinstance(token, str) and _TOKEN.fullmatch(token), "Prepare the automatic 3D thumbnail again.")
    _prune()
    value = _PLANS.get(token)
    _require(value is not None, "The 3D thumbnail expired. Create it again.")
    _PLANS.move_to_end(token)
    return value


def _tool_options(params):
    return {key: params.get(key, default) for key, default in (
        ("mode", "single"), ("in_path", ""), ("in_dir", ""), ("in_paths", ""), ("auto_chara_id", True),
        ("manual_chara_id", 0), ("thumbnail_size", 256), ("combine_pairs", True), ("thumbnail_fit_full", False))}


def _viewer_binding(token, state, character_id, counterpart_path, selected_variant, mesh_state=None, include_face_edits=None):
    from . import model_edits, viewer_mod_flow
    normalized = model_edits.validate_state(token, state, allow_empty=True)
    mesh = viewer_mod_flow.normalize_mesh_state(mesh_state)
    _require(include_face_edits is None or isinstance(include_face_edits, bool), "Choose whether to include this costume's verified face companion.")
    context = model_edits.mod_source_context(token)
    binding = {"token": token, "state": normalized, "sources": [
        {key: source[key] for key in ("name", "container", "member", "sha256")} for source in context["sources"]],
        "character_id": character_id, "counterpart_path": counterpart_path,
        "selected_variant": selected_variant}
    if mesh is not None:
        binding["mesh_state"] = mesh
    if include_face_edits is not None:
        binding["include_face_edits"] = include_face_edits
    return binding, context, normalized


def _viewer_owner(context, requested):
    if requested is not None:
        return _owner(requested)
    from . import viewer_mod_flow
    from .sukusta import default_sukusta_dir
    metadata = viewer_mod_flow.metadata(context, repo_root=Path.cwd(),
        cache_root=Path(default_sukusta_dir("extracted")) / "game-models")
    return _owner(metadata.get("characterId"))


def plan(params):
    """Create a bounded render plan; sources remain private and immutable."""
    _require(isinstance(params, dict), "Invalid automatic thumbnail request.")
    kind = params.get("kind")
    _require(kind in ("packer", "viewer", "updater"), "Choose a supported thumbnail source.")
    supplied = params if kind == "viewer" else params.get("params", {})
    fit_full = supplied.get("thumbnail_fit_full", False) if isinstance(supplied, dict) else False
    _require(type(fit_full) is bool, "Choose whether to fit the full character in its thumbnail.")
    quality = dict(QUALITY)
    if fit_full:
        quality["subject"] = "full-character-v1"
    profile, profile_digest = _profile()
    temporary = None
    try:
        if kind == "packer":
            _require(set(params) == {"kind", "params"} and isinstance(params["params"], dict), "Invalid costume thumbnail options.")
            options = _tool_options(params["params"])
            _require(options["mode"] in ("single", "multi", "batch"), "Choose single, selected files or batch costume packing.")
            size = int(options["thumbnail_size"])
            from webtools.core.repo import ensure_repo_on_path
            ensure_repo_on_path()
            import unity_costumemod_packer as packer
            groups = {}
            if options["mode"] == "single":
                paths = [_file(options["in_path"])]
                groups[paths[0]] = paths[:]
            elif options["mode"] == "multi":
                from webtools.tools.common import parse_multi_paths
                paths = list(dict.fromkeys(_file(path) for path in parse_multi_paths(params["params"])))
                _require(paths and len(paths) <= MAX_ITEMS, "Choose one to 128 costume files for automatic 3D thumbnails.")
                groups = {path: [path] for path in paths}
            else:
                from webtools import filebrowser
                from .sukusta import find_bundles
                directory = Path(options["in_dir"]).expanduser().resolve()
                _require(filebrowser.is_within_allowed(str(directory)) and directory.is_dir(), "Choose an allowed costume folder.")
                sources = [_file(str(path)) for path in find_bundles(str(directory))]
                _require(sources and len(sources) <= MAX_ITEMS * 4, "Choose a bounded costume batch for automatic 3D thumbnails.")
                jobs, rina_names, rina_paths, _ = packer.prepare_pack_jobs(sources, combine_pairs=bool(options["combine_pairs"]), log=lambda message: None)
                # An Android+iOS package uses its Android costume preview; all
                # paired/helper bytes still participate in the source binding.
                paths = []
                for job in jobs:
                    primary = job[2] if job[0] == "pair" else job[1]
                    bound = list(job[2:]) if job[0] == "pair" else [primary]
                    for path in bound[:]:
                        helper = rina_paths.get(path)
                        if helper is None and Path(path).stem.lower().startswith("209rinamasked"):
                            helper = rina_names.get(packer.normalize_rina_key(Path(path).stem.lower()))
                        if helper and helper not in bound:
                            bound.append(helper)
                    paths.append(primary)
                    groups[primary] = bound
                _require(paths and len(paths) <= MAX_ITEMS, "Choose a batch of one to 128 costumes for automatic 3D thumbnails.")
            items = []
            for path in paths:
                _require(not zipfile.is_zipfile(path), "Choose costume bundles here. Use Replace existing Mod thumbnail for installer ZIPs.")
                names = packer._bundle_texture_names(path)
                owners = {packer.extract_chara_id_from_texture_name(name) for name in names}
                owners.discard(None)
                if options["auto_chara_id"]:
                    _require(len(owners) <= 1, "This costume has ambiguous members. Choose the target member manually.")
                    owner = next(iter(owners), None) or packer.extract_chara_id_from_filename(Path(path).stem) or int(options["manual_chara_id"] or 0)
                else:
                    owner = int(options["manual_chara_id"] or 0)
                owner = _owner(owner)
                items.append({"paths": [path], "source_hashes": [[source, _sha(source)] for source in groups[path]], "characterId": owner})
            binding = options
        elif kind == "updater":
            _require(set(params) == {"kind", "params"} and isinstance(params["params"], dict), "Invalid thumbnail replacement options.")
            from . import mod_thumbnail_replace
            prepared = mod_thumbnail_replace.plan_inputs(params["params"])
            binding, items, size = prepared["binding"], prepared["items"], int(prepared["size"])
            _require(items and len(items) <= MAX_ITEMS, "Choose one to 128 costume ZIPs to update.")
            for item in items:
                _require(len(item["paths"]) == 1, "Render one installer costume ZIP at a time.")
                item["paths"] = [_file(item["paths"][0])]
                item["characterId"] = _owner(item["characterId"])
                _unchanged(item)
        else:
            fields = {"kind", "token", "state", "character_id", "counterpart_path", "selected_variant"}
            _require(fields <= set(params) <= fields | {"mesh_state", "include_face_edits", "thumbnail_fit_full"}, "Invalid viewer thumbnail options.")
            binding, context, normalized = _viewer_binding(params["token"], params["state"], params["character_id"], params["counterpart_path"], params["selected_variant"], params.get("mesh_state"), params.get("include_face_edits"))
            owner = _viewer_owner(context, params["character_id"])
            from . import viewer_mod_flow, viewer_scene_roles
            mesh = binding.get("mesh_state")
            _require(mesh is None or not (params["counterpart_path"] or viewer_scene_roles.session_metadata(params["token"])),
                     "Mesh edits cannot be propagated to paired or scene costumes. Save an individual edited Unity bundle instead.")
            from .sukusta import default_sukusta_dir
            root = Path(default_sukusta_dir("")) / ".viewer-cache" / "thumbnails"
            _require(not root.is_symlink(), "The thumbnail cache cannot be a symbolic link.")
            root.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.mkdtemp(prefix="render-", dir=root)
            result = viewer_mod_flow.export_current(params["token"], normalized, temporary, mesh_state=mesh, allow_empty=True,
                repo_root=Path.cwd(), cache_root=Path(default_sukusta_dir("extracted")) / "game-models")
            paths = list(result["preview_paths"])
            items = [{"paths": paths, "source_hashes": [[row["path"], row["sha256"]] for row in context["containers"]], "characterId": owner}]
            size = 256
        _require(64 <= size <= 1024, "Choose a thumbnail size between 64 and 1024 pixels.")
        color_table = profile["memberColors"]
        for item in items:
            _require(str(item["characterId"]) in color_table, "The SDK thumbnail template has no color for this member.")
            item["id"] = secrets.token_hex(16)
            item["png"] = None
            item["cacheKey"] = _hash(_json({"kind": kind, "binding": binding, "source": item["source_hashes"],
                "targetMember": item["characterId"], "profile": profile_digest, "size": size, "quality": quality}))
            item["plannedCacheKey"] = item["cacheKey"]
        token = secrets.token_hex(16)
        with _LOCK:
            _prune()
            while len(_PLANS) >= 16:
                _, old = _PLANS.popitem(last=False)
                if old.get("temporary"):
                    shutil.rmtree(old["temporary"], ignore_errors=True)
            _PLANS[token] = {"kind": kind, "binding": binding, "items": items, "size": size,
                "profile": profile_digest, "quality": quality, "fit_full": fit_full,
                "expires": time.monotonic() + TTL, "temporary": temporary}
        temporary = None
        return {"token": token, "size": size, "profileDigest": profile_digest,
                "profileUrl": "/static/thumbnail-sdk/profile.json", "quality": quality,
                "items": [{"id": item["id"], "name": Path(item["paths"][0]).name,
                    "characterId": item["characterId"], "color": color_table[str(item["characterId"])],
                    "cacheKey": item["cacheKey"], "sources": [{"name": Path(path).name, "sha256": digest} for path, digest in item["source_hashes"]]} for item in items]}
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


def _item(value, item_id):
    return next((item for item in value["items"] if item["id"] == item_id), None)


def _unchanged(item):
    for path, digest in item["source_hashes"] + item.get("face_source_hashes", []):
        _require(Path(path).is_file() and _sha(path) == digest, "The costume changed after preparing its thumbnail. Render it again.")



def _excluded_meshes(paths, render_sources=None):
    """Keep the character's head; hide only unrelated execution dependencies."""
    if render_sources is None:
        return []
    from . import model_viewer
    from .viewer_thumbnail_roles import excluded_renderers
    deadline = time.monotonic() + 60
    environment = model_viewer._environment(paths, deadline)
    scene = model_viewer._Scene(environment, deadline)
    heads = excluded_renderers(scene, paths)
    head_renderers = {tuple(row["rendererIdentity"][key] for key in ("source", "file", "id"))
                      for row in heads if row.get("rendererIdentity")}
    excluded = []
    allowed = {str(Path(path).resolve()) for path in render_sources}
    indices = {str(Path(path).resolve()): index for index, path in enumerate(paths)}
    files = {}
    for obj in environment.objects:
        source = model_viewer._source_path(obj)
        known = files.setdefault(source, {})
        known.setdefault(id(obj.assets_file), len(known))
    def identity(obj):
        source = model_viewer._source_path(obj)
        index, file = indices.get(source), files.get(source, {}).get(id(obj.assets_file))
        return {"source": index, "file": file, "id": str(obj.path_id)} if index is not None and file is not None else None
    for renderer, tree, game in scene.renderers:
        if model_viewer._source_path(renderer) in allowed:
            continue
        if renderer.type.name == "SkinnedMeshRenderer":
            mesh = model_viewer._ref(renderer, tree.get("m_Mesh"))
        elif renderer.type.name == "Mesh":
            mesh = renderer
        else:
            mesh = scene.filters.get(model_viewer._key(game))
        mesh_id, renderer_id = identity(mesh) if mesh is not None else None, identity(renderer)
        if mesh_id is None or renderer_id is None:
            continue
        if tuple(renderer_id[key] for key in ("source", "file", "id")) in head_renderers:
            continue
        excluded.append({"mesh": mesh_id, "renderer": str(renderer.path_id), "rendererIdentity": renderer_id,
                         "role": "dependency", "name": scene.name(mesh),
                         "proofs": [{"scope": "scene-graph-dependency", "renderer": renderer_id}]})
    return excluded


def model(params):
    _require(isinstance(params, dict) and set(params) == {"token", "item_id"}, "Invalid thumbnail model request.")
    with _LOCK:
        value = _plan(params["token"])
        item = _item(value, params["item_id"])
        _require(item is not None, "Choose a thumbnail in this render plan.")
        _unchanged(item)
        paths = item["paths"][:]
    from . import model_viewer, viewer_archive
    from webtools import filebrowser
    from .sukusta import default_sukusta_dir
    cache = Path(default_sukusta_dir("")) / ".viewer-cache"
    with ExitStack() as stack:
        if value["kind"] == "updater":
            from . import mod_thumbnail_replace
            source_sha = next(digest for source, digest in item["source_hashes"] if source == paths[0])
            expanded = stack.enter_context(mod_thumbnail_replace.render_inputs(paths[0], cache, source_sha,
                variant=item.get("variant", value["binding"].get("variant", "auto"))))
            render_sources = expanded.render_sources
        else:
            expanded = stack.enter_context(viewer_archive.expand_inputs(paths, cache))
            render_sources = None
        excluded = _excluded_meshes(expanded.paths, render_sources)
        prepared = model_viewer.prepare(expanded.paths, rigged=True, face_context={
            "enabled": True, "allow_download": True, "repo_root": str(Path.cwd()),
            "library_roots": list(dict.fromkeys(str(Path(root).resolve()) for root in filebrowser.allowed_roots().values())),
            "cache_dir": str(cache), "origins": getattr(expanded, "origins", {}),
            "manifest_paths": getattr(expanded, "manifest_paths", []),
        }, motion_paths=[])
        # The original face is resolved by the same trusted owner/CAB checks as
        # the main viewer. Bind its actual bytes too, so a cached thumbnail can
        # never silently survive a face replacement between render and save.
        companions = model_viewer.get_editing_companions(prepared["id"])
        face_hashes = []
        for row in companions:
            path, digest = row.get("path"), row.get("sha256")
            _require(isinstance(path, str) and Path(path).is_file() and _sha(path) == digest,
                     "The original face changed while rendering its thumbnail. Render it again.")
            if [path, digest] not in face_hashes:
                face_hashes.append([path, digest])
        with _LOCK:
            _require(_item(_plan(params["token"]), params["item_id"]) is item,
                     "Prepare the automatic 3D thumbnail again.")
            render_key = (_hash(_json({"plan": item["plannedCacheKey"], "faces": sorted([Path(path).name, digest] for path, digest in face_hashes)}))
                          if face_hashes else item["plannedCacheKey"])
            if render_key != item["cacheKey"]:
                item["png"] = None
                item.pop("render", None)
            item["cacheKey"] = render_key
            item["face_source_hashes"] = face_hashes
    _require(prepared.get("stats", {}).get("triangles", 0) > 0, "The costume contains no visible triangles.")
    return {"url": prepared["url"], "rig": prepared.get("rig", {}), "stats": prepared["stats"],
            "cacheKey": item["cacheKey"], "profileDigest": value["profile"], "excludedMeshes": excluded,
            "plannedCacheKey": item["plannedCacheKey"], "faces": prepared.get("faces", {}), "subject": value["quality"]["subject"],
            "faceSources": [{"name": Path(path).name, "sha256": digest} for path, digest in face_hashes]}


def store(params):
    _require(isinstance(params, dict) and set(params) == {"token", "item_id", "cache_key", "profile_digest", "png", "render"}, "Invalid rendered thumbnail request.")
    encoded = params["png"]
    _require(isinstance(encoded, str) and encoded.startswith("data:image/png;base64,") and len(encoded) <= MAX_IMAGE_BYTES * 4 // 3 + 64, "The rendered thumbnail must be a bounded PNG.")
    try:
        png = base64.b64decode(encoded.split(",", 1)[1], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("The rendered thumbnail is not valid base64 PNG data.") from error
    from PIL import Image
    _require(0 < len(png) <= MAX_IMAGE_BYTES and png.startswith(b"\x89PNG\r\n\x1a\n"), "The rendered thumbnail is too large or invalid.")
    with _LOCK:
        value = _plan(params["token"])
        item = _item(value, params["item_id"])
        _require(item is not None and params["cache_key"] == item["cacheKey"] and params["profile_digest"] == value["profile"], "The thumbnail source or template changed. Render it again.")
        _require(_profile()[1] == value["profile"], "The SDK thumbnail template changed. Render it again.")
        _unchanged(item)
        with Image.open(io.BytesIO(png)) as image:
            _require(image.format == "PNG" and image.size == (value["size"], value["size"]), "The thumbnail dimensions do not match its render plan.")
            image.verify()
        render = params["render"]
        _require(isinstance(render, dict) and isinstance(render.get("quality"), dict) and
                 render["quality"].get("enabled") is True and render["quality"].get("ready") is True and
                 type(render.get("subjectPixels")) is int and render["subjectPixels"] > 0 and
                 render.get("triangles", 0) > 0, "The high-quality 3D thumbnail did not render a visible costume.")
        total = sum(len(row["png"] or b"") for row in value["items"] if row is not item) + len(png)
        _require(total <= MAX_PLAN_BYTES, "This thumbnail batch is too large. Choose fewer costumes or a smaller size.")
        combined = sum(len(row["png"] or b"") for plan in _PLANS.values() for row in plan["items"] if row is not item) + len(png)
        _require(combined <= 64 * 1024 * 1024, "The thumbnail cache is full. Finish packing or try again shortly.")
        item["png"] = png
        item["render"] = copy.deepcopy(render)
        return {"token": params["token"], "itemId": item["id"], "sha256": _hash(png), "bytes": len(png),
            "size": value["size"], "characterId": item["characterId"], "cacheKey": item["cacheKey"],
            "profileDigest": value["profile"], "quality": value["quality"], "sources": [{"name": Path(path).name, "sha256": digest} for path, digest in item["source_hashes"]],
            "faceSources": [{"name": Path(path).name, "sha256": digest} for path, digest in item.get("face_source_hashes", [])]}


def packer_provider(params):
    if params.get("thumbnail_mode", "texture") != "3d":
        return None
    with _LOCK:
        value = _plan(params.get("thumbnail_plan"))
        expected, actual = copy.deepcopy(value["binding"]), _tool_options(params)
        if expected.get("mode") == "multi" and actual.get("mode") == "single":
            expected.update(mode="single", in_path=actual["in_path"])
        _require(value["kind"] == "packer" and expected == actual, "The costume packing settings changed. Render the thumbnails again.")
        _require(_profile()[1] == value["profile"], "The SDK thumbnail template changed. Render it again.")
        items = copy.copy(value["items"])
    def provide(path, size, character_id):
        selected = str(Path(path).resolve())
        item = next((row for row in items if selected in row["paths"]), None)
        _require(item is not None and item["png"] is not None and item["characterId"] == character_id and size == value["size"], "The automatic 3D thumbnail is missing or belongs to another costume/member.")
        _unchanged(item)
        return item["png"]
    return provide


def updater_provider(params):
    """Return only images bound to these exact existing costume ZIP bytes."""
    from . import mod_thumbnail_replace
    with _LOCK:
        value = _plan(params.get("thumbnail_plan"))
        actual, expected = mod_thumbnail_replace.render_options(params), copy.deepcopy(value["binding"])
        if expected.get("mode") == "multi" and actual.get("mode") == "single":
            expected.update(mode="single", in_path=actual["in_path"])
        _require(value["kind"] == "updater" and expected == actual,
                 "The costume ZIP selection or thumbnail settings changed. Render again.")
        _require(_profile()[1] == value["profile"], "The SDK thumbnail template changed. Render it again.")
        items = copy.copy(value["items"])
    def provide(path):
        selected = str(Path(path).resolve())
        item = next((row for row in items if row["paths"] == [selected]), None)
        _require(item is not None and item["png"] is not None, "This costume ZIP has no completed automatic thumbnail.")
        _unchanged(item)
        source_sha = next((digest for source, digest in item["source_hashes"] if source == selected), None)
        _require(source_sha is not None, "The rendered thumbnail is not bound to this costume ZIP.")
        return {"png": item["png"], "sha256": _hash(item["png"]), "character_id": item["characterId"],
                "profile_digest": value["profile"], "cache_key": item["cacheKey"], "quality": copy.deepcopy(value["quality"]),
                "source_path": selected, "source_sha256": source_sha, "size": value["size"], "variant": item["variant"]}
    return provide


def for_viewer_package(thumbnail_token, source_token, state, character_id, counterpart_path, selected_variant, *, mesh_state=None, include_face_edits=None):
    if not thumbnail_token:
        return None
    binding, context, _ = _viewer_binding(source_token, state, character_id, counterpart_path, selected_variant, mesh_state, include_face_edits)
    with _LOCK:
        value = _plan(thumbnail_token)
        _require(value["kind"] == "viewer" and value["binding"] == binding and value["profile"] == _profile()[1], "The model, target member, edits or template changed. Render the thumbnail again.")
        item = value["items"][0]
        _require(item["png"] is not None and item["characterId"] == _viewer_owner(context, character_id), "The automatic 3D thumbnail is missing or belongs to another target member.")
        _unchanged(item)
        return {"png": item["png"], "character_id": item["characterId"], "sha256": _hash(item["png"]),
                "profile_digest": value["profile"], "cache_key": item["cacheKey"], "quality": copy.deepcopy(value["quality"])}
