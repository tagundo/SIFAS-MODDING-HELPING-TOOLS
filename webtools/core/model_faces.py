"""Bounded, read-only source discovery for optional SIFAS facial geometry.

The caller supplies trusted library/cache/repository roots. Character identity
comes from the selected Unity assets, never from the app's character picker.
Only the viewer decides which Face/Eyes renderers from a donor can be exported.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_TRANSFER_BYTES = 32 * 1024 * 1024
MAX_CACHE_BYTES = 96 * 1024 * 1024
MAX_CANDIDATES = 32
MAX_LOCAL_FILES = 512
MAX_AUTO_FILES = 4
FACE_SECONDS = 40
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
}


class FaceUnavailable(ValueError):
    pass


def _check(deadline):
    if time.monotonic() >= deadline:
        raise FaceUnavailable("Finding the original face took too long.")


def _inside(path, roots):
    path = os.path.realpath(path)
    return any(path == root or path.startswith(root + os.sep) for root in roots)


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
            target.update(int(match) for match in _OWNER.findall(value))
    return strong or weak, dynamic


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
            owners[candidate].add(owner)
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
    for role in ("brows", "eyelids"):
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
            role = facial_role(scene.name(game_object), scene.name(mesh), source in dynamic)
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
                if owned and entry.is_file() and not entry.is_symlink() and _cached(entry) is not None:
                    stat = entry.stat()
                    files.append((stat.st_mtime, stat.st_size, entry))
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
        self.owner, self.added, self.transferred = None, 0, 0
        self.status, self.needed, self.dynamic_sources = "not_needed", set(), set()
        self.required_roles, self.rendered_roles = set(), set()
        self.target_anchor, self.head_material = None, None
        self.source_adjustments = {}
        self.database_paths = set()
        self.initial_roles = roles(scene) if self.enabled else set()
        if not self.enabled:
            return
        # A deliberately selected hair/face accessory remains an accessory.
        # Only an outfit's body requests automatic full-face completion.
        if not has_body(scene):
            return
        manifest_owners = _manifest_owners(paths, self.context.get("manifest_paths"), self.context.get("origins"))
        source_owners = []
        for source in _body_sources(scene):
            internal, _ = _names(scene, source)
            metadata = manifest_owners.get(source, set())
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
        self.needed = {"face", "eyes"} - self.initial_roles
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
        from .model_viewer import _environment, _Scene
        _check(self.deadline)
        cache = self.context.get("cache_dir")
        if cache and _inside(path, [os.path.join(os.path.realpath(cache), "models")]) and _cached(path) is None:
            return None
        scene = _Scene(_environment([path], self.deadline), self.deadline)
        owners, dynamic = _names(scene)
        if owners and owners != {self.owner}:
            return None
        # Unknown-owner local donors are unsafe. DB/cache donors have an
        # authoritative same-character dependency chain instead.
        trusted = path in self.database_paths
        if not owners and not trusted:
            return None
        found = roles(scene) & self.needed
        if not found:
            return None
        return scene, dynamic, found

    def _local(self):
        try:
            import llas_asset_extractor as extractor
            character_name = extractor.CHARACTERS.get(self.owner, "").lower()
        except ImportError:
            from .charinfo import NAMES
            character_name = NAMES.get(self.owner, "").split(" ", 1)[0].lower()

        def rank_name(name):
            lower = name.lower()
            return 0 if (f"ch{self.owner:04}" in lower or f"{self.owner}_" in lower
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
            if not os.path.isdir(root):
                continue
            for directory, dirs, files in os.walk(root, followlinks=False):
                _check(self.deadline)
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
        root = self.context.get("repo_root")
        if not root:
            return []
        import llas_asset_extractor as extractor
        dbs = extractor.list_asset_dbs(root)
        dbs.sort(key=lambda path: ("asset_a" not in os.path.basename(path), "/gl/" not in path.replace("\\", "/"), "_en" not in path))
        master = extractor.find_masterdata(root)
        if not master or not dbs:
            return []
        with sqlite3.connect(Path(master).resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT s.model_asset_path FROM m_member_init i JOIN m_suit s ON s.id=i.suit_m_id WHERE i.member_m_id=? AND s.member_m_id=?", (self.owner, self.owner)).fetchone()
            if row is None:
                row = db.execute("SELECT model_asset_path FROM m_suit WHERE member_m_id=? ORDER BY id LIMIT 1", (self.owner,)).fetchone()
        if row is None:
            return []
        with sqlite3.connect(Path(dbs[0]).resolve().as_uri() + "?mode=ro", uri=True) as db:
            dependencies = [r[0] for r in db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (row[0],))]
            keys = dependencies + ([row[0]] if "face" in self.needed else [])
            result = []
            for key in keys:
                record = db.execute("SELECT asset_path,pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (key,)).fetchone()
                if not record:
                    continue
                pack = db.execute("SELECT file_size FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (record[1],)).fetchone()
                result.append(dict(zip(("asset_path", "pack_name", "head", "size", "key1", "key2"), record), pack_size=pack[0] if pack else None))
        # The largest shared member dependency normally contains facial mesh
        # geometry; tiny expression/animation companions need no initial fetch.
        result.sort(key=lambda resource: (resource["asset_path"] == row[0], -resource["size"]))
        return result[:MAX_AUTO_FILES]

    def _resource(self, descriptor):
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
        output = _managed_dir(root, "models") / f"ch{self.owner:04}_{identity}.unity"
        plain = _cached(output, size)
        if plain is not None:
            _preflight_bundle(plain)
            self.database_paths.add(str(output))
            return str(output)
        import llas_asset_extractor as extractor
        roots = list(self.context.get("pack_roots", []))
        roots.append(extractor.COPIED_PACKS_DIR)
        sukusta = os.environ.get("SUKUSTA_DIR")
        if sukusta:
            roots.append(os.path.join(sukusta, "packs"))
        repo = self.context.get("repo_root")
        if repo:
            roots.extend((os.path.join(repo, "static"), repo))
        # Same game-client pack layout used by the existing extractor.
        roots.extend(p for p, status in extractor.detect_game_candidates() if status == "found")
        pack_path, packed, managed_pack = None, None, None
        for directory in roots:
            for relative in (pack_name, "pkg" + pack_name[0] + "/" + pack_name, "pak" + pack_name[0] + "/" + pack_name, "files/pkg" + pack_name[0] + "/" + pack_name):
                candidate = os.path.realpath(os.path.join(directory, relative))
                if _inside(candidate, [os.path.realpath(directory)]) and os.path.isfile(candidate):
                    pack_path = candidate
                    break
            if pack_path:
                break
        if pack_path is not None:
            length = os.path.getsize(pack_path)
            if not 0 < length <= MAX_PACK_BYTES or (pack_size is not None and length != pack_size):
                raise FaceUnavailable("The cached original pack is truncated or has the wrong platform.")
            with open(pack_path, "rb") as handle:
                handle.seek(head)
                plain = bytearray(handle.read(size))
        else:
            cached_pack = _managed_dir(root, "packs") / pack_name
            managed_pack = cached_pack
            packed = _cached(cached_pack, pack_size)
            if packed is None:
                if not self.context.get("allow_download", True):
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
                packed = _download(base.rstrip("/") + "/" + pack_name, pack_size, self.deadline, min(MAX_PACK_BYTES, remaining))
                if not 0 < len(packed) <= MAX_PACK_BYTES or (pack_size is not None and len(packed) != pack_size):
                    raise FaceUnavailable("The original asset download was incomplete.")
            plain = bytearray(packed[head:head + size])
        if len(plain) != size:
            raise FaceUnavailable("The original face section is incomplete.")
        extractor.decrypt_section(plain, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
        try:
            _preflight_bundle(plain)
        except Exception:
            # Do not retain a complete-looking HTML/wrong-platform response as
            # an immutable successful cache entry. User-owned packs stay intact.
            if managed_pack is not None:
                managed_pack.unlink(missing_ok=True)
                Path(str(managed_pack) + ".json").unlink(missing_ok=True)
            raise FaceUnavailable("The original face could not be decrypted for this platform.")
        if managed_pack is not None:
            _save(managed_pack, packed)
        _save(output, plain, self.owner)
        self.database_paths.add(str(output))
        return str(output)

    def resolve(self):
        if not self.enabled or self.owner is None or not self.needed:
            return []
        candidates = []
        try:
            candidates.extend(self._local())
            for path in candidates:
                if self._accept(path):
                    break
            if self.needed:
                for descriptor in self._descriptors():
                    _check(self.deadline)
                    try:
                        path = self._resource(descriptor)
                        if self._accept(path):
                            break
                    except Exception:
                        # One missing optional pack cannot hide a valid costume.
                        continue
        except Exception:
            pass
        if self.needed:
            self.status = "partial" if self.auto_paths else "unavailable"
            self.warn("face_source_unavailable", "The original face could not be obtained. The costume is still shown; keep a same-character original model locally or check the asset CDN connection.")
        else:
            self.status = "added"
        try:
            if self.context.get("cache_dir"):
                _prune_cache(self.context["cache_dir"], self.auto_paths, self.deadline)
        except (OSError, FaceUnavailable):
            pass
        return list(self.auto_paths)

    def _accept(self, path):
        from .model_viewer import MAX_FILES
        if path in self.paths or path in self.auto_paths or len(self.paths) + len(self.auto_paths) >= MAX_FILES:
            return False
        try:
            inspected = self._inspect(path)
            if inspected is None:
                return False
            scene, dynamic, found = inspected
            self.auto_paths.append(path)
            self.dynamic_sources.update(dynamic)
            self.source_adjustments[path] = None
            if not hasattr(self, "source_roles"):
                self.source_roles = {}
            accepted_roles = set().union(*self.source_roles.values())
            self.source_roles[path] = set(found) | ((roles(scene) & set(_AUXILIARY)) - self.initial_roles - accepted_roles)
            self.needed.difference_update(found)
            return not self.needed
        except Exception:
            return False

    def include(self, scene, renderer, game_object, mesh):
        from .model_viewer import _source_path
        source = _source_path(renderer)
        if source not in self.auto_paths:
            return True
        role = facial_role(scene.name(game_object), scene.name(mesh), source in self.dynamic_sources)
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

    def material(self, renderer, material):
        from .model_viewer import _source_path
        # The game assigns BodyPartManager.headMaterial to its separate facial
        # prefab. Reuse that original texture, without resampling or UV edits.
        if _source_path(renderer) in self.dynamic_sources and self.head_material is not None:
            return self.head_material
        return material

    def metadata(self):
        return {"enabled": self.enabled, "status": self.status, "added": self.added,
                "characters": [self.owner] if self.owner is not None else []}

    def failed(self):
        self.status = "partial" if self.added else "unavailable"
        self.warn("face_source_unavailable", "The original face could not be opened. The costume is still shown.")

    def finish(self):
        if self.required_roles - self.rendered_roles:
            self.status = "partial" if self.added else "unavailable"
        elif self.required_roles:
            self.status = "added"
