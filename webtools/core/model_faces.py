"""Bounded, read-only source discovery for optional SIFAS facial geometry.

The caller supplies trusted library/cache/repository roots. Character identity
comes from the selected Unity assets, never from the app's character picker.
Only the viewer decides which Face/Eyes renderers from a donor can be exported.
"""
import ast
import hashlib
import json
from itertools import islice
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .member_identity import member_from_native, native_from_member


MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_TRANSFER_BYTES = 32 * 1024 * 1024
MAX_CACHE_BYTES = 96 * 1024 * 1024
MAX_CANDIDATES = 32
MAX_DESCRIPTOR_CANDIDATES = 64
MAX_LOCAL_FILES = 512
MAX_AUTO_FILES = 4
COMPANION_HINT = "viewer-companions.json"
MAX_HINT_BYTES = 64 * 1024
FACE_SECONDS = 40
_DOWNLOAD_SLOT = threading.BoundedSemaphore(1)
_OWNER = re.compile(r"(?:^|[^a-z0-9])ch(\d{4})(?=[^0-9]|$)", re.I)
_PACK = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
_FACE = re.compile(r"(?:^|[^a-z])face(?:[^a-z]|$)", re.I)
_EYES = re.compile(r"(?:^|[^a-z])(?:eyes?|eyeballs?|iris|irises|pupils?)(?:[^a-z]|$)", re.I)
_AUXILIARY = {
    "brows": re.compile(r"(?:^|[^a-z])(?:eyebrows?|brows?)(?:[^a-z]|$)", re.I),
    "eyelids": re.compile(r"(?:^|[^a-z])(?:eyelids?|lids?|eyelash(?:es)?|lash(?:es)?|blink|closed)(?:[^a-z]|$)|(?:eye|face)[_ ]*close(?:[^a-z]|$)", re.I),
    "mouth": re.compile(r"(?:^|[^a-z])mouth(?:[^a-z]|$)", re.I),
    "teeth": re.compile(r"(?:^|[^a-z])(?:teeth|tooth)(?:[^a-z]|$)", re.I),
    "tongue": re.compile(r"(?:^|[^a-z])tongue(?:[^a-z]|$)", re.I),
    "eye_details": re.compile(r"(?:^|[^a-z])eye[_ ]+around(?:[^a-z]|$)|(?:^|[^a-z])(?:left|right)[_ ]+eye[_ ]+white[_ ]+line(?:[^a-z]|$)|(?:^|[^a-z])rin[_ ]*nya[_ ]*eye[_ ]+overlay(?:[^a-z]|$)", re.I),
}


class FaceUnavailable(ValueError):
    pass


class SavedFacePlatformMismatch(FaceUnavailable):
    """An authoritative edited face must not be silently replaced by stock."""



def _check(deadline):
    if time.monotonic() >= deadline:
        raise FaceUnavailable("Finding the original face took too long.")


def _inside(path, roots):
    path = os.path.realpath(path)
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _pack_sizes(db, names, suit_id):
    """Prefer the current suit's indexed mapping; scan only missing packs."""
    sizes = {}
    if not names:
        return sizes
    parameters = ",".join("?" for _ in names)
    try:
        # A pack is one physical CDN file. Its selected-suit record is the
        # relevant size if a custom catalog contains contradictory mappings.
        for name, size in db.execute(
                f"SELECT pack_name,file_size FROM m_asset_package_mapping WHERE package_key=? AND pack_name IN ({parameters})",
                [f"suit:{suit_id}", *names]):
            sizes.setdefault(name, size)
    except sqlite3.Error:
        pass  # older catalogs may not expose package_key
    missing = [name for name in names if name not in sizes]
    if missing:
        parameters = ",".join("?" for _ in missing)
        for name, size in db.execute(
                f"SELECT pack_name,file_size FROM m_asset_package_mapping WHERE pack_name IN ({parameters})", missing):
            sizes.setdefault(name, size)
    return sizes


def _names(scene, source=None):
    from .model_viewer import _source_path
    strong, weak, dynamic = set(), set(), set()
    for obj in scene.env.objects:
        if source is not None and _source_path(obj) != source:
            continue
        if obj.type.name not in ("AssetBundle", "GameObject", "Material", "Texture2D"):
            continue
        _check(scene.deadline)
        try:
            name = scene.name(obj)
        except Exception:
            continue
        values = [name]
        if obj.type.name == "AssetBundle":
            tree = scene.tree(obj)
            values.extend(str(row[0]) for row in tree.get("m_Container", [])[:64])
            if "facedynamic" in name.lower():
                dynamic.add(_source_path(obj))
        target = strong if obj.type.name in ("AssetBundle", "GameObject") else weak
        for value in values:
            # Unity names use native chXXXX IDs; catalogs and UI use members.
            target.update(member_from_native(int(match)) for match in _OWNER.findall(value))
    owners = strong or weak
    # The game's masked Rina models use ch9999 as a pseudo-character. Only
    # normalize it when that same source has real native board geometry, and
    # no other character identity occurs anywhere in its names.
    if 9999 in owners and (strong | weak) <= {209, 9999}:
        for renderer, tree, game_object in scene.renderers:
            if source is not None and _source_path(renderer) != source:
                continue
            if not tree.get("m_Enabled", True) or not scene.active(game_object):
                continue
            mesh = _mesh(scene, renderer, tree, game_object)
            if mesh is not None and renderer_role(scene, renderer, game_object, mesh) == "board":
                # The board must belong to a source which actually supplied
                # the pseudo identity, rather than another selected file.
                owner_source = _source_path(renderer)
                if source is not None or _raw_source_has_pseudo(scene, owner_source):
                    owners = (owners - {9999}) | {209}
                    break
    return owners, dynamic


def _raw_source_has_pseudo(scene, source):
    from .model_viewer import _source_path
    strong, weak = set(), set()
    for obj in scene.env.objects:
        if _source_path(obj) != source or obj.type.name not in ("AssetBundle", "GameObject", "Material", "Texture2D"):
            continue
        names = [scene.name(obj)]
        if obj.type.name == "AssetBundle":
            names.extend(str(row[0]) for row in scene.tree(obj).get("m_Container", [])[:64])
        target = strong if obj.type.name in ("AssetBundle", "GameObject") else weak
        target.update(int(match) for name in names for match in _OWNER.findall(name))
    return 9999 in (strong or weak)


def source_owner(scene, source, metadata=None):
    """Return runtime member IDs, given already validated runtime metadata.

    Internal identity wins. A manifest declaring Rina can identify a stripped
    ch9999 board mod whose actual board geometry was removed by the modder.
    No app selection or arbitrary filename participates in this decision.
    """
    internal, _ = _names(scene, source)
    metadata = set(metadata or ())
    if internal == {9999} and metadata == {209}:
        return {209}
    return internal or metadata


def _manifest_owners(paths, manifests, origins=None):
    """Read literal metadata assignments, without importing or executing them."""
    selected = {os.path.realpath(path) for path in paths}
    origins = {os.path.realpath(path): os.path.realpath(origin) for path, origin in (origins or {}).items()}
    owners = {path: set() for path in selected}
    for path in list(manifests or [])[:8]:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(65537)
            if len(raw) > 65536:
                continue
            tree = ast.parse(raw.decode("utf-8-sig"))
            values = {}
            for item in tree.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    key = item.targets[0].id
                    if key in ("chara_id", "costume_file"):
                        values[key] = ast.literal_eval(item.value)
            costume = values.get("costume_file")
            owner = values.get("chara_id")
            if not isinstance(costume, str) or not isinstance(owner, int) or isinstance(owner, bool) or not 1 <= owner <= 9999:
                continue
            relative = costume.replace("\\", "/")
            if not relative or relative.startswith("/") or ":" in relative or ".." in relative.split("/"):
                continue
            manifest = os.path.realpath(path)
            candidate = os.path.realpath(os.path.join(os.path.dirname(manifest), relative))
            if candidate not in selected or not _inside(candidate, [os.path.dirname(manifest)]):
                continue
            if manifest in origins or candidate in origins:
                if manifest not in origins or candidate not in origins or origins[manifest] != origins[candidate]:
                    continue
            # Legacy installer literals are native IDs (the installer swaps
            # Mia/Lanzhu before looking up runtime member rows).
            owners[candidate].add(member_from_native(owner))
        except (OSError, SyntaxError, ValueError, TypeError, UnicodeError):
            continue
    return owners


def _manifest_owner(paths, manifests, origins=None):
    return set().union(*_manifest_owners(paths, manifests, origins).values())


def facial_role(game_name, mesh_name, dynamic=False):
    names = str(game_name) + " " + str(mesh_name)
    # Split common Unity exporter CamelCase without letting EyeBrow/EyeLash
    # look like a real eye. Auxiliary geometry never completes the iris role.
    names = re.sub(r"([a-z])([A-Z])", r"\1 \2", names)
    names = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", names)
    for role in ("brows", "eyelids", "eye_details"):
        if _AUXILIARY[role].search(names):
            return role
    if _EYES.search(names):
        return "eyes"
    for role in ("mouth", "teeth", "tongue"):
        if _AUXILIARY[role].search(names):
            return role
    if _FACE.search(names):
        # SIFAS's separate MemberFace prefab can expose one combined Face
        # renderer. Explicit Mouth/Brow/etc names above retain their own roles.
        return "eyes" if dynamic else "face"
    return None



def completion_roles(found):
    """A native mask display supplies facial expression without iris meshes."""
    found = set(found)
    return found | ({"eyes"} if "board" in found else set())


def renderer_role(scene, renderer, game_object, mesh, dynamic=False):
    """Recognize native facial paths without accepting arbitrary costume masks.

    The game's CommonCoreMemberHead looks up Head_Face/mesh_facedots and
    Head_Face/mesh_mask/Mask_DisplayOverlayparts. A real active renderer may
    live below those transforms; its leaf mesh name is not a reliable marker.
    """
    from .model_viewer import _key, _ref, _source_path
    source, names, seen = _source_path(renderer), [], set()
    current = game_object
    while current is not None:
        _check(scene.deadline)
        key = _key(current)
        if key in seen or len(seen) >= 256:
            raise FaceUnavailable("The face contains a circular transform hierarchy.")
        if _source_path(current) != source:
            break
        seen.add(key)
        names.append(scene.name(current).lower())
        transform = scene.transforms.get(key)
        parent = _ref(transform, scene.tree(transform).get("m_Father")) if transform else None
        current = _ref(parent, scene.tree(parent).get("m_GameObject")) if parent else None
    path = tuple(reversed(names))
    for index in range(len(path)):
        if path[index:index + 2] == ("head_face", "mesh_facedots"):
            return "board"
        if path[index:index + 3] == ("head_face", "mesh_mask", "mask_displayoverlayparts"):
            return "face_overlay"
        if path[index:index + 2] == ("head_face", "mesh_mask"):
            return "board_shell"
    return facial_role(scene.name(game_object), scene.name(mesh), dynamic)

def _mesh(scene, renderer, tree, game_object):
    from .model_viewer import _key, _ref
    if renderer.type.name == "Mesh":
        return renderer
    if renderer.type.name == "SkinnedMeshRenderer":
        return _ref(renderer, tree.get("m_Mesh"))
    return scene.filters.get(_key(game_object))


def roles(scene, sources=None):
    from .model_viewer import _source_path
    _, dynamic = _names(scene)
    found = set()
    for renderer, tree, game_object in scene.renderers:
        source = _source_path(renderer)
        if sources is not None and source not in sources:
            continue
        if not tree.get("m_Enabled", True) or not scene.active(game_object):
            continue
        mesh = _mesh(scene, renderer, tree, game_object)
        if mesh is not None:
            role = renderer_role(scene, renderer, game_object, mesh, source in dynamic)
            if role:
                found.add(role)
    return found


def missing_dynamic(scene):
    from .model_viewer import _ref
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            face = scene.tree(obj).get("face")
            if isinstance(face, dict) and face.get("m_PathID") and _ref(obj, face) is None:
                return True
        except Exception:
            continue
    return False


def _body_sources(scene):
    from .model_viewer import _source_path
    sources = set()
    for renderer, tree, game_object in scene.renderers:
        if not tree.get("m_Enabled", True) or not scene.active(game_object):
            continue
        mesh = _mesh(scene, renderer, tree, game_object)
        if mesh is None:
            continue
        names = scene.name(game_object) + " " + scene.name(mesh)
        if re.search(r"(?:^|[^a-z])(?:mesh[_ ]?)?body(?:[^a-z]|$)", names, re.I):
            sources.add(_source_path(renderer))
    return sources


def has_body(scene):
    return bool(_body_sources(scene))


def declares_dynamic(scene):
    for obj in scene.env.objects:
        if obj.type.name == "AssetBundle":
            try:
                if any("facedynamic" in str(name).lower() for name in scene.tree(obj).get("m_Dependencies", [])):
                    return True
            except Exception:
                pass
    return False


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".face-", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _cache_root(root):
    root = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    if root.is_symlink() or root.resolve() != root:
        raise FaceUnavailable("The face cache must use its real private folder path.")
    return root


def _managed_dir(root, name):
    root = _cache_root(root)
    root.mkdir(parents=True, exist_ok=True)
    directory = root / name
    if directory.is_symlink():
        raise FaceUnavailable("The face cache contains an unsafe linked directory.")
    directory.mkdir(exist_ok=True)
    if directory.resolve() != directory:
        raise FaceUnavailable("The face cache is outside its private directory.")
    return directory


def _cached(path, expected=None):
    """Detect changed/truncated cached bytes; the asset DB supplies no signed hash."""
    try:
        if Path(path).is_symlink() or Path(str(path) + ".json").is_symlink():
            return None
        with open(str(path) + ".json", "rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            return None
        meta = json.loads(raw)
        size = os.path.getsize(path)
        if not 0 < size <= MAX_PACK_BYTES or meta["size"] != size or (expected is not None and size != expected):
            return None
        with open(path, "rb") as handle:
            data = handle.read(MAX_PACK_BYTES + 1)
        if len(data) != size:
            return None
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save(path, data, owner=None):
    _atomic(path, data)
    _atomic(str(path) + ".json", json.dumps({"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "owner": owner}).encode())


class _SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urlsplit(request.full_url), urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise FaceUnavailable("The original asset server redirected to another host.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download(url, expected, deadline, byte_limit=MAX_PACK_BYTES):
    """Existing CDN's /static/<pack> route, bounded even for missing length headers."""
    _check(deadline)
    request = Request(url, headers={"User-Agent": "Elichika model viewer"})
    with build_opener(_SameOriginRedirect()).open(request, timeout=min(8, max(1, deadline - time.monotonic()))) as response:
        _check(deadline)
        length = response.headers.get("Content-Length")
        if length is not None and (int(length) > byte_limit or (expected is not None and int(length) != expected)):
            raise FaceUnavailable("The original asset server returned an unexpected file size.")
        chunks, size = [], 0
        while True:
            _check(deadline)
            chunk = response.read(min(65536, byte_limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > byte_limit or (expected is not None and size > expected):
                raise FaceUnavailable("The original asset exceeds the face download limit.")
            chunks.append(chunk)
    if size == 0 or (expected is not None and size != expected):
        raise FaceUnavailable("The original asset download was incomplete.")
    return b"".join(chunks)


def _download_with_deadline(url, expected, deadline, byte_limit=MAX_PACK_BYTES):
    """Bound the caller's wait even when OS DNS ignores the socket timeout.

    At most one daemon may be inside the original downloader; nothing queues.
    The worker receives no FacePlan or cache path and only returns bytes. An
    abandoned result is discarded, so late DNS/HTTP completion cannot decrypt
    assets or publish cache files after the caller has returned its base model.
    """
    _check(deadline)
    slot = _DOWNLOAD_SLOT
    if not slot.acquire(blocking=False):
        raise FaceUnavailable("An original face download is still finishing. Local facial assets can still be used.")
    completed, lock = threading.Event(), threading.Lock()
    state = {"abandoned": False}
    downloader = _download

    def run():
        try:
            try:
                data = downloader(url, expected, deadline, byte_limit)
                error = None
            except Exception as exception:
                data, error = None, exception
            with lock:
                if not state["abandoned"]:
                    state.update(data=data, error=error)
        finally:
            slot.release()
            completed.set()

    try:
        threading.Thread(target=run, name="viewer-face-download", daemon=True).start()
    except Exception as error:
        slot.release()
        raise FaceUnavailable("The original face download could not be started.") from error
    finished = completed.wait(max(0., deadline - time.monotonic()))
    with lock:
        if not finished or time.monotonic() >= deadline:
            state.clear()
            state["abandoned"] = True
            raise FaceUnavailable("Finding the original face took too long.")
        error, data = state.pop("error", None), state.pop("data", None)
    if error is not None:
        raise error
    if data is None:
        raise FaceUnavailable("The original face download did not finish.")
    return data


def _prune_cache(root, protected=(), deadline=None):
    # Only this module's private files are eligible; never remove library files.
    files = []
    root = _cache_root(root)
    for name in ("packs", "models"):
        if deadline is not None:
            _check(deadline)
        directory = root / name
        if directory.is_symlink() or directory.resolve() != directory:
            continue
        if directory.is_dir():
            for entry in directory.iterdir():
                if deadline is not None:
                    _check(deadline)
                owned = bool(_PACK.fullmatch(entry.name)) if name == "packs" else bool(re.fullmatch(r"ch\d{4}_[0-9a-f]{24}\.unity", entry.name))
                if owned and entry.is_file() and not entry.is_symlink():
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    files.append((stat.st_mtime, stat.st_size, entry))
    # These sizes are an upper bound for the valid owned subset. Below budget
    # nothing can be evicted, so do not read/hash every cached bundle merely to
    # prove that. Loading a selected pack/model still always calls _cached.
    if sum(row[1] for row in files) <= MAX_CACHE_BYTES:
        return
    valid = []
    for row in files:
        if deadline is not None:
            _check(deadline)
        if _cached(row[2]) is not None:
            valid.append(row)
    files = valid
    total = sum(row[1] for row in files)
    for _, size, path in sorted(files):
        if total <= MAX_CACHE_BYTES:
            break
        if str(path) in protected:
            continue
        path.unlink(missing_ok=True)
        Path(str(path) + ".json").unlink(missing_ok=True)
        total -= size


class FacePlan:
    def __init__(self, scene, paths, context, deadline):
        self.context = context or {}
        self.enabled = bool(context and self.context.get("enabled", True))
        self.deadline = min(deadline, time.monotonic() + FACE_SECONDS)
        self.paths, self.auto_paths, self.warnings = list(paths), [], []
        self.saved_paths = set()
        self.source_roles = {}
        self.owner, self.added, self.transferred = None, 0, 0
        self.face_mode = "normal"
        self.status, self.needed, self.dynamic_sources = "not_needed", set(), set()
        self.required_roles, self.rendered_roles = set(), set()
        self.target_anchor, self.head_material = None, None
        self.material_bindings = {}
        self.source_adjustments = {}
        self.database_paths = set()
        self._hint_sources = {}
        self._body_platforms = set()
        self.initial_roles = roles(scene) if self.enabled else set()
        if not self.enabled:
            return
        # A deliberately selected hair/face accessory remains an accessory.
        # Only an outfit's body requests automatic full-face completion.
        if not has_body(scene):
            return
        manifest_owners = _manifest_owners(paths, self.context.get("manifest_paths"), self.context.get("origins"))
        source_owners = []
        body_sources = _body_sources(scene)
        from .model_viewer import _source_path
        for obj in scene.env.objects:
            if _source_path(obj) in body_sources:
                platform = getattr(obj.assets_file, "target_platform", None)
                try:
                    self._body_platforms.add(int(platform))
                except (ValueError, TypeError):
                    pass
        for source in body_sources:
            internal, _ = _names(scene, source)
            metadata = manifest_owners.get(source, set())
            if internal == {9999} and metadata == {209}:
                internal = source_owner(scene, source, metadata)
                self.face_mode = "board"
            if internal and metadata and internal != metadata:
                self.warn("face_owner_conflict", "The mod's character metadata disagrees with its Unity model. The Unity model's owner is used.")
            candidates = internal or metadata
            source_owners.append(next(iter(candidates)) if len(candidates) == 1 else None)
        owners = set(source_owners)
        if len(owners) == 1 and None not in owners:
            self.owner = next(iter(owners))
        if self.owner is None:
            self.status = "unavailable"
            self.warn("face_owner_unknown", "The model's character could not be identified safely, so an original face was not added.")
            return
        # SIFAS's base Face is only its surface shell. Stripped costume mods
        # may omit both the manager and dependency metadata but still need eyes.
        if "board" in self.initial_roles:
            self.face_mode = "board"
        self.needed = {"face", "eyes"} - completion_roles(self.initial_roles)
        self.required_roles = set(self.needed)
        self.status = "already_present" if not self.needed else "unavailable"
        self.target_anchor, self.head_material = self._anchor(scene)

    def warn(self, code, message):
        warning = {"code": code, "message": message}
        if warning not in self.warnings:
            self.warnings.append(warning)

    def _anchor(self, scene, source=None):
        from .model_viewer import _key, _ref, _source_path
        # BodyPartManager.head is the runtime head GameObject. Prefer the
        # dedicated face anchor when available, preserving the mod's head pose.
        best, material, priority = None, None, 0
        for obj in scene.env.objects:
            if source is not None and _source_path(obj) != source:
                continue
            if obj.type.name == "MonoBehaviour":
                try:
                    tree = scene.tree(obj)
                    if "face" in tree and "head" in tree:
                        material = _ref(obj, tree.get("headMaterial"))
                except Exception:
                    pass
            if obj.type.name == "GameObject":
                name = scene.name(obj).lower()
                if name in ("head_face", "head"):
                    transform = scene.transforms.get(_key(obj))
                    rank = 2 if name == "head_face" else 1
                    if transform is not None and rank > priority:
                        best = scene.world(transform)
                        priority = rank
        return best, material

    def _inspect(self, path):
        from .model_viewer import _environment, _Scene, _source_hash
        from . import model_platforms
        _check(self.deadline)
        cache = self.context.get("cache_dir")
        if cache and _inside(path, [os.path.join(os.path.realpath(cache), "models")]) and _cached(path) is None:
            return None
        scene = _Scene(_environment([path], self.deadline), self.deadline)
        hint = self._hint_sources.get(os.path.realpath(path))
        if hint is not None:
            hashes = {_source_hash(obj) for obj in scene.env.objects}
            if hashes != {hint}:
                return None
        owners, dynamic = _names(scene)
        if owners and owners != {self.owner}:
            return None
        # Unknown-owner local donors are unsafe. DB/cache donors have an
        # authoritative same-character dependency chain instead.
        trusted = path in self.database_paths
        if not owners and not trusted:
            return None
        # Automatically discovered game assets must match the native body.
        # Explicit saved companions can be previewed after identity checks.
        # An unassigned wearer keeps its original platform classification.
        try:
            body_platform = model_platforms.single_platform(self._body_platforms, self.paths[0])
            face_platform = model_platforms.from_environment(scene.env, path)
        except ValueError as error:
            if hint is not None:
                raise SavedFacePlatformMismatch(str(error)) from None
            return None
        if not model_platforms.compatible(body_platform, face_platform):
            if hint is None:
                return None
            # Saved, digest-bound faces are an explicit user choice. A valid
            # same-owner face can be previewed as-is; the transplant verifies
            # the target payload before generating a compatible copy.
            from . import face_platforms
            if not face_platforms.is_face(scene, self.owner):
                try:
                    model_platforms.require_compatible(body_platform, face_platform,
                        wearer_name=self.paths[0], other_name=path, role="saved facial companion")
                except ValueError as error:
                    raise SavedFacePlatformMismatch(str(error)) from None
        available = roles(scene)
        if self.face_mode == "normal" and "board" in available:
            return None
        found = available & self.needed
        if self.face_mode == "board":
            found.discard("eyes")
        if "eyes" in self.needed and "board" in available:
            found.add("board")
        if not found:
            # A complete body can keep its native preview (for example Rina's
            # board) while an explicitly saved face remains an editing source.
            from . import face_platforms
            if hint is None or not face_platforms.is_face(scene, self.owner):
                return None
        return scene, dynamic, found

    def _verified_companions(self):
        """Prefer a saved, body-bound facial copy without trusting its filename."""
        import unicodedata
        if len(self._body_platforms) != 1:
            return
        def name(value):
            return (isinstance(value, str) and value not in ("", ".", "..")
                    and len(value) <= 256 and not any(char in value for char in ("/", "\\", "\0")))
        def digest(path, limit):
            if os.path.islink(path) or not os.path.isfile(path) or not 0 < os.path.getsize(path) <= limit:
                return None
            result, total = hashlib.sha256(), 0
            with open(path, "rb") as stream:
                while True:
                    _check(self.deadline)
                    block = stream.read(min(1024 * 1024, limit + 1 - total))
                    if not block:
                        break
                    total += len(block)
                    if total > limit:
                        return None
                    result.update(block)
            return result.hexdigest()
        origins = self.context.get("origins", {})
        seen, candidates = set(), 0
        for selected in self.paths:
            body = os.path.realpath(origins.get(selected, selected))
            if body in seen:
                continue
            seen.add(body)
            parent = os.path.dirname(body)
            hint_path = os.path.join(parent, COMPANION_HINT)
            try:
                _check(self.deadline)
                if os.path.islink(hint_path) or not os.path.isfile(hint_path) or os.path.getsize(hint_path) > MAX_HINT_BYTES:
                    continue
                with open(hint_path, "rb") as stream:
                    raw = stream.read(MAX_HINT_BYTES + 1)
                if len(raw) > MAX_HINT_BYTES:
                    continue
                hint = json.loads(raw)
                if (not isinstance(hint, dict) or set(hint) != {"version", "body", "companions"}
                        or type(hint.get("version")) is not int or hint["version"] != 1):
                    continue
                identity, companions = hint["body"], hint["companions"]
                if (not isinstance(identity, dict) or set(identity) != {"file", "sha256"}
                        or not name(identity["file"])
                        or unicodedata.normalize("NFC", identity["file"]) != unicodedata.normalize("NFC", os.path.basename(body))
                        or not isinstance(identity["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", identity["sha256"])
                        or digest(body, MAX_CACHE_BYTES) != identity["sha256"]
                        or not isinstance(companions, list) or not 1 <= len(companions) <= MAX_AUTO_FILES):
                    continue
                for row in companions:
                    if (not isinstance(row, dict) or set(row) != {"file", "sha256"}
                            or not name(row["file"]) or not isinstance(row["sha256"], str)
                            or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
                        continue
                    candidate = os.path.join(parent, row["file"])
                    real = os.path.realpath(candidate)
                    if (real in seen or not _inside(real, [parent]) or os.path.dirname(real) != parent
                            or digest(candidate, MAX_PACK_BYTES) != row["sha256"]):
                        continue
                    seen.add(real)
                    self._hint_sources[real] = row["sha256"]
                    yield real
                    candidates += 1
                    if candidates >= MAX_AUTO_FILES:
                        return
            except (OSError, ValueError, TypeError, KeyError, FaceUnavailable):
                continue

    def _known_local(self):
        """Probe native-ID filenames for the runtime member before catalogs."""
        roots = [os.path.dirname(path) for path in self.paths]
        roots.extend(os.path.dirname(os.path.realpath(origin)) for path, origin in self.context.get("origins", {}).items()
                     if path in self.paths)
        roots.extend(os.path.realpath(root) for root in self.context.get("library_roots", []))
        seen, probes, candidates = set(self.paths), 0, 0
        native_owner = native_from_member(self.owner)
        names = [f"ch{native_owner:04}_facedynamic.unity", f"ch{native_owner:04}_face.unity"]
        for root in dict.fromkeys(os.path.realpath(path) for path in roots):
            for relative in ("", "3d_model", os.path.join("extracted", "3d_model")):
                for name in names:
                    if probes >= MAX_LOCAL_FILES:
                        return
                    _check(self.deadline)
                    probes += 1
                    path = os.path.join(root, relative, name)
                    real = os.path.realpath(path)
                    if real in seen or not _inside(real, [root]) or os.path.islink(path):
                        continue
                    try:
                        if not os.path.isfile(path) or not 0 < os.path.getsize(path) <= MAX_PACK_BYTES:
                            continue
                    except OSError:
                        continue
                    seen.add(real)
                    yield path
                    candidates += 1
                    if candidates >= MAX_CANDIDATES:
                        return
        cache = self.context.get("cache_dir")
        if not cache:
            return
        try:
            directory = _cache_root(cache) / "models"
            if directory.is_symlink() or directory.resolve() != directory:
                return
            # Accept previous app cache prefixes too; _inspect always verifies
            # the source's actual runtime owner before adding any geometry.
            prefixes = "|".join(str(value).zfill(4) for value in dict.fromkeys((native_owner, self.owner)))
            pattern = re.compile(rf"ch(?:{prefixes})_[0-9a-f]{{24}}\.unity", re.I)
            found = []
            with os.scandir(directory) as entries:
                for entry in islice(entries, MAX_LOCAL_FILES - probes):
                    _check(self.deadline)
                    probes += 1
                    if not pattern.fullmatch(entry.name):
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False) or not 0 < entry.stat(follow_symlinks=False).st_size <= MAX_PACK_BYTES:
                            continue
                    except OSError:
                        continue
                    real = os.path.realpath(entry.path)
                    if real in seen or not _inside(real, [str(directory)]):
                        continue
                    seen.add(real)
                    found.append(entry.path)
                    if len(found) + candidates >= MAX_CANDIDATES:
                        break
            for path in sorted(found):
                _check(self.deadline)
                yield path
        except (OSError, FaceUnavailable):
            return

    def _local(self):
        from .viewer_cache import is_legacy_viewer_cache_path, prune_legacy_viewer_cache_dirs
        try:
            import llas_asset_extractor as extractor
            character_name = extractor.CHARACTERS.get(self.owner, "").lower()
        except ImportError:
            from .charinfo import NAMES
            character_name = NAMES.get(self.owner, "").split(" ", 1)[0].lower()

        def rank_name(name):
            lower = name.lower()
            return 0 if (f"ch{native_from_member(self.owner):04}" in lower or f"{self.owner}_" in lower
                         or (character_name and re.match(re.escape(character_name) + r"(?:[^a-z]|$)", lower))) else 1

        # Selected files' parents are already jailed by the server.
        roots = [os.path.dirname(p) for p in self.paths]
        roots.extend(os.path.dirname(os.path.realpath(origin)) for path, origin in self.context.get("origins", {}).items() if path in self.paths)
        roots.extend(os.path.realpath(p) for p in self.context.get("library_roots", []) if os.path.isdir(p))
        cache = self.context.get("cache_dir")
        if cache:
            roots.insert(0, str(_cache_root(cache) / "models"))
        seen, found, count = set(self.paths), [], 0
        for root in dict.fromkeys(roots):
            if not os.path.isdir(root) or is_legacy_viewer_cache_path(root):
                continue
            for directory, dirs, files in os.walk(root, followlinks=False):
                _check(self.deadline)
                prune_legacy_viewer_cache_dirs(directory, dirs)
                depth = os.path.relpath(directory, root).count(os.sep)
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and depth < 2)[:32]
                for name in sorted(files, key=lambda name: (rank_name(name), name)):
                    count += 1
                    if count > MAX_LOCAL_FILES:
                        return [path for _, path in sorted(found)[:MAX_CANDIDATES]]
                    path = os.path.realpath(os.path.join(directory, name))
                    if path in seen or not _inside(path, [root]) or name.endswith((".json", ".png", ".jpg", ".txt", ".zip", ".csv")):
                        continue
                    seen.add(path)
                    try:
                        if not 0 < os.path.getsize(path) <= MAX_PACK_BYTES:
                            continue
                        with open(path, "rb") as handle:
                            header = handle.read(8)
                        if not header.startswith(b"UnityFS\0") and not name.lower().endswith((".unity", ".assets")):
                            continue
                    except OSError:
                        continue
                    found.append((rank_name(name), path))
        return [path for _, path in sorted(found)[:MAX_CANDIDATES]]

    def _descriptors(self):
        """Keep original view/region/platform alternatives before trying HTTP."""
        return list(self._descriptor_iter())

    def _descriptor_iter(self):
        """Yield a usable recipe before reading later region/platform catalogs."""
        root = self.context.get("repo_root")
        if not root:
            return
        import llas_asset_extractor as extractor
        dbs = extractor.list_asset_dbs(root)
        # A cached/edited NoTarget model has no trustworthy native preference.
        # Concrete bodies must not fetch Android faces merely because that DB
        # happened to be listed before the matching iOS catalog.
        from . import model_platforms
        desired = next(iter(self._body_platforms)) if len(self._body_platforms) == 1 else None
        desired = desired if desired in (model_platforms.ANDROID, model_platforms.IOS) else None
        def catalog_platform(path):
            name = os.path.basename(path)
            return (model_platforms.ANDROID if name.startswith("asset_a_") else
                    model_platforms.IOS if name.startswith("asset_i_") else None)
        dbs.sort(key=lambda path: (desired is not None and catalog_platform(path) != desired,
            "asset_a" not in os.path.basename(path), "/gl/" not in path.replace("\\", "/"), "_en" not in path))
        seen = set()
        for catalog in dbs[:16]:
            if desired is not None and catalog_platform(catalog) not in (None, desired):
                continue
            _check(self.deadline)
            master = Path(catalog).parent / "masterdata.db"
            if not master.is_file():
                continue
            try:
                with sqlite3.connect(master.resolve().as_uri() + "?mode=ro", uri=True) as db:
                    row = db.execute("SELECT s.id,s.model_asset_path FROM m_member_init i JOIN m_suit s ON s.id=i.suit_m_id WHERE i.member_m_id=? AND s.member_m_id=?", (self.owner, self.owner)).fetchone()
                    if row is None:
                        row = db.execute("SELECT id,model_asset_path FROM m_suit WHERE member_m_id=? ORDER BY id LIMIT 1", (self.owner,)).fetchone()
                    if row is None:
                        continue
                    # Alternate suit views include unmasked Rina. A normal
                    # target must not receive the default board's face instead.
                    try:
                        variants = [r[0] for r in db.execute("SELECT v.model_asset_path FROM m_suit_view v JOIN m_suit s ON s.id=v.suit_master_id WHERE v.suit_master_id=? AND s.member_m_id=? ORDER BY v.view_status DESC LIMIT 4", (row[0], self.owner))]
                    except sqlite3.Error:
                        variants = []
                    models = ([row[1]] + variants) if self.face_mode == "board" else (variants + [row[1]])
                for model in dict.fromkeys(models):
                    _check(self.deadline)
                    with sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True) as db:
                        dependencies = [r[0] for r in db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=? LIMIT 64", (model,))]
                        keys = list(dict.fromkeys(dependencies + [model]))
                        parameters = ",".join("?" for _ in keys)
                        records = {}
                        for record in db.execute(f"SELECT asset_path,pack_name,head,size,key1,key2 FROM member_model WHERE asset_path IN ({parameters})", keys):
                            records.setdefault(record[0], record)
                        names = list(dict.fromkeys(record[1] for record in records.values()))
                        sizes = _pack_sizes(db, names, row[0])
                        resources = []
                        for key in keys:
                            record = records.get(key)
                            if not record:
                                continue
                            resources.append(dict(zip(("asset_path", "pack_name", "head", "size", "key1", "key2"), record), pack_size=sizes.get(record[1])))
                    # Close SQLite before yielding: cache conversion must not
                    # retain an open catalog while it parses a facial bundle.
                    resources.sort(key=lambda resource: -resource["size"])
                    body = [resource for resource in resources if resource["asset_path"] == model][:1]
                    shared = [resource for resource in resources if resource["asset_path"] != model]
                    for resource in shared[:MAX_AUTO_FILES - len(body)] + body:
                        identity = tuple(resource[key] for key in ("pack_name", "head", "size", "key1", "key2", "pack_size"))
                        if identity not in seen:
                            seen.add(identity)
                            yield resource
                            if len(seen) >= MAX_DESCRIPTOR_CANDIDATES:
                                return
            except (OSError, sqlite3.Error, TypeError, ValueError):
                continue

    def _resource(self, descriptor, *, download=True):
        _check(self.deadline)
        from .model_viewer import _preflight_bundle
        cache = self.context.get("cache_dir")
        if not cache:
            raise FaceUnavailable("A writable face cache is unavailable.")
        root = _cache_root(cache)
        pack_name = descriptor["pack_name"]
        if not _PACK.fullmatch(pack_name):
            raise FaceUnavailable("The original asset database has an invalid pack name.")
        head, size, pack_size = descriptor["head"], descriptor["size"], descriptor["pack_size"]
        if not isinstance(head, int) or not isinstance(size, int) or head < 0 or not 0 < size <= MAX_PACK_BYTES \
                or (pack_size is not None and not head + size <= pack_size <= MAX_PACK_BYTES):
            raise FaceUnavailable("The original face exceeds the mobile download limit.")
        identity = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()[:24]
        output = _managed_dir(root, "models") / f"ch{native_from_member(self.owner):04}_{identity}.unity"
        plain = _cached(output, size)
        if plain is not None:
            _preflight_bundle(plain)
            self.database_paths.add(str(output))
            return str(output)
        import llas_asset_extractor as extractor
        roots = list(self.context.get("pack_roots", []))
        roots.extend(self.context.get("library_roots", []))
        roots.extend(os.path.dirname(path) for path in self.paths)
        roots.extend(os.path.dirname(os.path.realpath(origin)) for path, origin in self.context.get("origins", {}).items() if path in self.paths)
        roots.append(extractor.COPIED_PACKS_DIR)
        sukusta = os.environ.get("SUKUSTA_DIR")
        if sukusta:
            roots.append(os.path.join(sukusta, "packs"))
        repo = self.context.get("repo_root")
        if repo:
            roots.extend((os.path.join(repo, "static"), repo))
        # Same game-client pack layout used by the existing extractor.
        roots.extend(p for p, status in extractor.detect_game_candidates() if status == "found")
        def decrypt(section):
            if len(section) != size:
                raise FaceUnavailable("The original face section is incomplete.")
            data = bytearray(section)
            extractor.decrypt_section(data, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
            try:
                _preflight_bundle(data)
            except Exception as error:
                raise FaceUnavailable("The original face could not be decrypted for this platform.") from error
            return data

        plain, packed, managed_pack = None, None, None
        for directory in dict.fromkeys(roots):
            _check(self.deadline)
            for relative in (pack_name, "pkg" + pack_name[0] + "/" + pack_name, "pak" + pack_name[0] + "/" + pack_name, "files/pkg" + pack_name[0] + "/" + pack_name):
                candidate = os.path.realpath(os.path.join(directory, relative))
                if not _inside(candidate, [os.path.realpath(directory)]) or not os.path.isfile(candidate):
                    continue
                try:
                    length = os.path.getsize(candidate)
                    if not head + size <= length <= MAX_PACK_BYTES or (pack_size is not None and length != pack_size):
                        continue
                    with open(candidate, "rb") as handle:
                        handle.seek(head)
                        plain = decrypt(handle.read(size))
                    break
                except (OSError, FaceUnavailable):
                    # A stale or wrong-platform local pack must not prevent
                    # another local copy or the original CDN from working.
                    continue
            if plain is not None:
                break
        if plain is None:
            cached_pack = _managed_dir(root, "packs") / pack_name
            managed_pack = cached_pack
            packed = _cached(cached_pack, pack_size)
            if packed is None:
                if not download or not self.context.get("allow_download", True):
                    raise FaceUnavailable("Original face downloads are disabled.")
                base = self.context.get("cdn_base") or extractor.DEFAULT_CDN_BASE
                parsed = urlsplit(base)
                if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise FaceUnavailable("Configure a valid HTTPS original-asset CDN.")
                remaining = MAX_TRANSFER_BYTES - self.transferred
                reservation = pack_size if pack_size is not None else MAX_PACK_BYTES
                if reservation > remaining:
                    raise FaceUnavailable("The original face exceeds the download budget.")
                # Reserve before opening a socket, including failed attempts.
                self.transferred += reservation
                packed = _download_with_deadline(base.rstrip("/") + "/" + pack_name, pack_size, self.deadline, min(MAX_PACK_BYTES, remaining))
                if not 0 < len(packed) <= MAX_PACK_BYTES or (pack_size is not None and len(packed) != pack_size):
                    raise FaceUnavailable("The original asset download was incomplete.")
            try:
                plain = decrypt(packed[head:head + size])
            except FaceUnavailable:
                # Do not publish wrong-platform/HTML responses as cache hits.
                managed_pack.unlink(missing_ok=True)
                Path(str(managed_pack) + ".json").unlink(missing_ok=True)
                raise
        if managed_pack is not None:
            _save(managed_pack, packed)
        _save(output, plain, self.owner)
        self.database_paths.add(str(output))
        return str(output)

    def resolve(self):
        if not self.enabled or self.owner is None:
            return []
        try:
            pending = []
            try:
                for path in self._verified_companions():
                    self._accept(path)
            except SavedFacePlatformMismatch:
                raise
            except Exception:
                pass
            # A downloaded same-owner original must not wait behind catalog
            # scans. Names only select candidates; _accept validates contents.
            try:
                if self.needed:
                    for path in self._known_local():
                        if self._accept(path):
                            break
            except Exception:
                pass
            # Exact original/cache identities come before the broad Unity-file
            # search. A populated library must not consume the entire facial
            # budget before we can reuse its already-downloaded original pack.
            try:
                if self.needed:
                    for descriptor in self._descriptor_iter():
                        _check(self.deadline)
                        try:
                            if self._accept(self._resource(descriptor, download=False)):
                                break
                        except Exception:
                            pending.append(descriptor)
            except Exception:
                # Standalone/local-only viewers do not need an asset catalog.
                pass
            if self.needed:
                original_deadline = self.deadline
                if pending and self.context.get("allow_download", True):
                    # Leave time to obtain a known original when a large local
                    # collection contains no usable same-character donor.
                    self.deadline = min(self.deadline, time.monotonic() + 8)
                try:
                    for path in self._local():
                        if self._accept(path):
                            break
                except Exception:
                    pass
                finally:
                    self.deadline = original_deadline
            if self.needed:
                for descriptor in pending:
                    _check(self.deadline)
                    try:
                        if self._accept(self._resource(descriptor)):
                            break
                    except Exception:
                        # One missing optional pack cannot hide a costume.
                        continue
        except SavedFacePlatformMismatch:
            raise
        except Exception:
            pass
        if self.needed:
            self.status = "partial" if self.auto_paths else "unavailable"
            self.warn("face_source_unavailable", "The original face is unavailable. The costume is still shown; check the asset connection and try again.")
        else:
            self.status = "added" if any(self.source_roles.values()) else "already_present"
        try:
            if self.context.get("cache_dir"):
                _prune_cache(self.context["cache_dir"], self.auto_paths, self.deadline)
        except (OSError, FaceUnavailable):
            pass
        return list(self.auto_paths)

    def _accept(self, path):
        if path in self.paths or path in self.auto_paths or len(self.auto_paths) >= MAX_AUTO_FILES:
            return False
        try:
            inspected = self._inspect(path)
            if inspected is None:
                return False
            scene, dynamic, found = inspected
            accepted_roles = set().union(*self.source_roles.values())
            available = roles(scene)
            auxiliaries = (available & (set(_AUXILIARY) | {"face_overlay", "board_shell"})) - self.initial_roles - accepted_roles
            if not found or self.face_mode == "board" and "board" not in available:
                auxiliaries.clear()
            if self.face_mode != "board" or "board" not in available:
                auxiliaries.difference_update({"face_overlay", "board_shell"})
            self.auto_paths.append(path)
            if os.path.realpath(path) in self._hint_sources:
                self.saved_paths.add(path)
            self.dynamic_sources.update(dynamic)
            self.source_adjustments[path] = None
            self.source_roles[path] = set(found) | auxiliaries
            self.needed.difference_update(completion_roles(found))
            return not self.needed
        except SavedFacePlatformMismatch:
            raise
        except Exception:
            return False

    def include(self, scene, renderer, game_object, mesh):
        from .model_viewer import _source_path
        source = _source_path(renderer)
        if source not in self.auto_paths:
            return True
        role = renderer_role(scene, renderer, game_object, mesh, source in self.dynamic_sources)
        return role in self.source_roles.get(source, set())

    def world(self, scene, renderer, world):
        """Rigidly align known donor head frames; never guess a local face frame."""
        from .model_viewer import _source_path
        import numpy as np
        source = _source_path(renderer)
        if source not in self.auto_paths or self.target_anchor is None:
            return world
        if self.source_adjustments.get(source) is None:
            anchor, _ = self._anchor(scene, source)
            self.source_adjustments[source] = self.target_anchor @ np.linalg.inv(anchor) if anchor is not None else np.eye(4)
        return self.source_adjustments[source] @ world

    def bind_selected_materials(self, scene, facial_sources):
        """Apply the serialized BodyPartManager face/head-material binding.

        Automatic discovery is optional; this runtime binding is not. Saved
        previews already select their facial prefab, and private installer
        graphs rename CAB/AssetBundle identities while retaining the prefab
        declaration. Resolve the actual face pointer and its descendants so
        another selected costume cannot lend its atlas to an unrelated face.
        """
        from .model_viewer import _key, _ref, _source_path
        bindings = {}
        if not facial_sources:
            self.material_bindings = bindings
            return

        def beneath(game_object, root):
            root_key, source, seen = _key(root), _source_path(root), set()
            while game_object is not None and _source_path(game_object) == source:
                key = _key(game_object)
                if key == root_key:
                    return True
                if key in seen or len(seen) >= 256:
                    return False
                seen.add(key)
                transform = scene.transforms.get(key)
                parent = _ref(transform, scene.tree(transform).get("m_Father")) if transform else None
                game_object = _ref(parent, scene.tree(parent).get("m_GameObject")) if parent else None
            return False

        for obj in scene.env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            _check(scene.deadline)
            try:
                tree = scene.tree(obj)
            except Exception:
                continue
            if not all(key in tree for key in ("face", "head", "headMaterial")):
                continue
            face, head, material = (_ref(obj, tree.get(key)) for key in ("face", "head", "headMaterial"))
            if (face is None or head is None or material is None or material.type.name != "Material"
                    or _source_path(face) not in facial_sources):
                continue
            try:
                root = face if face.type.name == "GameObject" else _ref(face, scene.tree(face).get("m_GameObject"))
            except Exception:
                continue
            if root is None or root.type.name != "GameObject":
                continue
            for renderer, _, game_object in scene.renderers:
                if _source_path(renderer) != _source_path(face) or not beneath(game_object, root):
                    continue
                key = _key(renderer)
                if key not in bindings:
                    bindings[key] = material
                elif bindings[key] is not None and _key(bindings[key]) != _key(material):
                    # An explicitly shared prefab with distinct atlases has no
                    # single material assignment. Preserve its own material.
                    bindings[key] = None
        self.material_bindings = bindings

    def material(self, renderer, material):
        from .model_viewer import _key, _source_path
        if _key(renderer) in self.material_bindings:
            return self.material_bindings[_key(renderer)] or material
        # The game assigns BodyPartManager.headMaterial to its separate facial
        # prefab. Reuse that original texture, without resampling or UV edits.
        if _source_path(renderer) in self.dynamic_sources and self.head_material is not None:
            return self.head_material
        return material

    def native_merge_bindings(self, scene, selected, facial_sources):
        """Read the native face material, geometry bindings, and relocated transforms."""
        import numpy as np
        from .model_viewer import _key, _member_depth_material, _ref, _remaining, _source_path, _trs

        if not facial_sources:
            return {}, {}

        def typed(owner, pointer, kind, *, local=True):
            target = _ref(owner, pointer)
            if target is None or target.type.name != kind or (local and owner.assets_file is not target.assets_file):
                return None
            return target

        def declares(component, tree, name):
            script = typed(component, tree.get("m_Script"), "MonoScript", local=False)
            if script is None:
                return False
            definition = scene.tree(script)
            return (definition.get("m_ClassName"), definition.get("m_Namespace"), definition.get("m_AssemblyName")) == (
                name, "LLAS.Components.Members", "Assembly-CSharp.dll")

        def children(transform):
            if transform is None:
                return {}
            refs = scene.tree(transform).get("m_Children", ())
            if len(refs) > 256:
                return {}
            result = {}
            for pointer in refs:
                descendant = typed(transform, pointer, "Transform")
                child = game(descendant)
                if child is None:
                    continue
                name = scene.name(child)
                result[name] = descendant if name not in result else None
            return result

        def game(transform):
            return typed(transform, scene.tree(transform).get("m_GameObject"), "GameObject") if transform is not None else None

        renderers = {}
        for renderer, tree, owner in scene.renderers:
            renderers.setdefault(_key(owner), []).append((renderer, tree))

        def surface(transform):
            owner = game(transform)
            if owner is None or not scene.active(owner) or scene.tree(owner).get("m_Layer") != 16:
                return None
            rows = renderers.get(_key(owner), ())
            if len(rows) != 1:
                return None
            renderer, tree = rows[0]
            refs = tree.get("m_Materials", ())
            if (renderer.type.name != "SkinnedMeshRenderer" or renderer.assets_file is not owner.assets_file
                    or tree.get("m_Enabled") is not True or tree.get("m_CastShadows") not in (0, 1, 2)
                    or tree.get("m_ForceRenderingOff") or len(refs) != 1):
                return None
            material = typed(renderer, refs[0], "Material")
            return (renderer, material) if material is not None else None

        def merged_surfaces(root):
            pending, visited, result = [root], set(), []
            while pending:
                transform = pending.pop()
                if transform is None or _key(transform) in visited or len(visited) >= 64:
                    return None
                visited.add(_key(transform))
                owner = game(transform)
                if owner is None:
                    return None
                if scene.name(owner) != "Eye" and any(
                    renderer.type.name == "SkinnedMeshRenderer" for renderer, _ in renderers.get(_key(owner), ())
                ):
                    row = surface(transform)
                    if row is None:
                        return None
                    result.append((transform, *row))
                pending.extend(children(transform).values())
            return result

        def stock_placeholder(material):
            reference = scene.tree(material).get("m_Shader") or {}
            return (reference.get("m_FileID") == 0 and reference.get("m_PathID") == 952725256833404699
                    and typed(material, reference, "Shader") is not None)

        def donor_surface(transform, material):
            row = surface(transform)
            if row is None:
                return None
            renderer, placeholder = row
            if not stock_placeholder(placeholder) or self.material_bindings.get(_key(renderer)) is not material:
                return None
            return renderer

        def eye_mounts(renderer, donor_head, costume_head):
            face_root = children(donor_head).get("Face_Root")
            eye_root = children(face_root).get("Eye_Root")
            bones = [donor_head, face_root, eye_root]
            for side in ("Left", "Right"):
                side_root = children(eye_root).get(f"{side}Eye_Root")
                first = children(side_root).get(f"{side}Eye1")
                second = children(first).get(f"{side}Eye2")
                bones.extend((side_root, first, second))
            if any(transform is None for transform in bones):
                return None
            tree = scene.tree(renderer)
            if typed(renderer, tree.get("m_RootBone"), "Transform") is not donor_head:
                return None
            authored = [typed(renderer, pointer, "Transform") for pointer in tree.get("m_Bones", ())]
            if authored != bones:
                return None
            result = {_key(donor_head): (costume_head, True), _key(face_root): (costume_head, False)}
            for transform in bones[2:]:
                parent = typed(transform, scene.tree(transform).get("m_Father"), "Transform")
                if parent is None or _key(parent) not in result:
                    return None
                result[_key(transform)] = (parent, False)
            return result

        bindings, mounts = {}, {}
        for component in scene.env.objects:
            if component.type.name != "MonoBehaviour" or _source_path(component) not in selected:
                continue
            _remaining(scene.deadline)
            try:
                tree = scene.tree(component)
                if not all(field in tree for field in ("head", "headAll", "face", "headMaterial")):
                    continue
                if not declares(component, tree, "BodyPartManager"):
                    continue
                owner = typed(component, tree.get("m_GameObject"), "GameObject")
                head = typed(component, tree.get("head"), "GameObject")
                head_all = typed(component, tree.get("headAll"), "GameObject")
                face = typed(component, tree.get("face"), "MonoBehaviour", local=False)
                material = typed(component, tree.get("headMaterial"), "Material")
                if (any(value is None for value in (owner, head, head_all, face, material))
                        or _source_path(face) not in facial_sources
                        or face.assets_file.target_platform != component.assets_file.target_platform
                        or not scene.active(owner) or not _member_depth_material(scene, material)):
                    continue
                face_tree = scene.tree(face)
                if not declares(face, face_tree, "MemberFace"):
                    continue
                # MemberFaceData is an inline field of this typed component.
                face_data = face_tree.get("memberFaceData")
                merge = face_data.get("needsMergingFace") if isinstance(face_data, dict) else None
                if type(merge) not in (bool, int) or merge != 1:
                    continue
                prefab = typed(face, face_tree.get("m_GameObject"), "GameObject")
                if prefab is None:
                    continue
                head_children = children(scene.transforms.get(_key(head)))
                head_all_tr = scene.transforms.get(_key(head_all))
                if head_all_tr is None or head_children.get("Head_All") is not head_all_tr:
                    continue
                costume_nodes = children(head_all_tr)
                carrier = costume_nodes.get("mesh_face")
                if (carrier is None or costume_nodes.get("Head_Face") is None
                        or "mesh_facedots" in children(costume_nodes["Head_Face"])):
                    continue
                donor_root = children(scene.transforms.get(_key(prefab)))
                donor = donor_root.get("mesh_face")
                costume_parts = merged_surfaces(carrier)
                donor_parts = merged_surfaces(donor)
                if (not costume_parts or not donor_parts
                        or any(_key(source) != _key(material) for _, _, source in costume_parts)
                        or any(not stock_placeholder(source) or self.material_bindings.get(_key(renderer)) is not material
                               for _, renderer, source in donor_parts)):
                    continue
                carrier_world = scene.world(carrier)
                mounting = carrier_world @ np.linalg.inv(scene.world(donor))
                worlds = [scene.world(transform) for transform, _, _ in costume_parts]
                worlds.extend(mounting @ scene.world(transform) for transform, _, _ in donor_parts)
                # CombineFace bakes original vertex transforms but copies morph deltas
                # verbatim. Support the stock-compatible identity linear rest basis.
                if any(not np.isfinite(world).all() or not np.allclose(world[:3, :3], np.eye(3), atol=1e-6, rtol=0)
                       for world in worlds):
                    continue
                for (_, renderer, _), world in zip([*costume_parts, *donor_parts], worlds, strict=True):
                    key = _key(renderer)
                    bindings[key] = None if key in bindings else ((carrier, world), material, "merge")

                # RepairRootBone keeps Eye separate and replaces its donor Head_Face
                # joint with the selected costume's joint. Face_Root retains its local TRS.
                eye = donor_surface(children(donor).get("Eye"), material)
                if eye is not None:
                    eye_nodes = eye_mounts(eye, donor_root.get("Head_Face"), costume_nodes["Head_Face"])
                    if eye_nodes is not None and not mounts.keys() & eye_nodes.keys():
                        mounts.update(eye_nodes)
                        key = _key(eye)
                        bindings[key] = None if key in bindings else (None, material, "eye")

                # The source moves display_OnOff with worldPositionStays=false.
                display = donor_root.get("display_OnOff")
                if display is not None and _key(display) not in mounts:
                    display_world = scene.world(head_all_tr) @ _trs(scene.tree(display))
                    for name in ("LeftEyeWhiteLine", "RightEyeWhiteLine"):
                        transform = children(display).get(name)
                        line = donor_surface(transform, material)
                        if line is None:
                            continue
                        world = display_world @ _trs(scene.tree(transform))
                        if not np.isfinite(world).all():
                            continue
                        key = _key(line)
                        bindings[key] = None if key in bindings else ((display, world), material, "line")
                        mounts[_key(display)] = (head_all_tr, False)
            except (AttributeError, KeyError, TypeError, ValueError, np.linalg.LinAlgError, OSError):
                continue
        return bindings, mounts

    def metadata(self):
        return {"enabled": self.enabled, "status": self.status, "added": self.added,
                "characters": [self.owner] if self.owner is not None else []}

    def failed(self):
        self.status = "partial" if self.added else "unavailable"
        self.warn("face_source_unavailable", "The original face could not be opened. The costume is still shown.")

    def finish(self):
        if self.required_roles - completion_roles(self.rendered_roles):
            self.status = "partial" if self.added else "unavailable"
        elif self.required_roles:
            self.status = "added"
