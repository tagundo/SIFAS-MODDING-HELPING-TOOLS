"""Bounded, read-only source discovery for optional SIFAS facial geometry.

The caller supplies trusted library/cache/repository roots. Character identity
comes from the selected Unity assets, never from the app's character picker.
Only the viewer decides which Face/Eyes renderers from a donor can be exported.
"""
import ast
from contextlib import closing, contextmanager
import hashlib
import json
from itertools import islice
import math
import ntpath
import os
from pathlib import Path
import re
import sqlite3
import struct
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
# Downloads that may still find the face a body references stop this long
# before the face deadline, so another prefab of the member can still be used.
FALLBACK_SECONDS = 10
# While a catalog original may still be downloaded, the broad library search
# and the other same-member files it keeps share this bound.
LOCAL_SECONDS = 8
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


class _NoAnswer(FaceUnavailable):
    """Nothing was learned about the face: its time ran out or the worker was busy."""


class _StillDownloading(_NoAnswer):
    """A download outlived one step's share of the face budget and keeps going."""



def _check(deadline):
    if time.monotonic() >= deadline:
        from .transient_failures import note
        note()
        raise _NoAnswer("Finding the original face took too long.")


def _serialized_names(path):
    """Casefolded serialized-file names a candidate bundle declares.

    Only the bounded UnityFS directory is read; no object is parsed. Unity
    resolves a PPtr's m_FileID through these names, so this tells whether a
    candidate is the exact face a body's BodyPartManager points to.
    """
    from .model_viewer import _preflight_bundle
    with open(path, "rb") as handle:
        data = handle.read(MAX_PACK_BYTES + 1)
    if len(data) > MAX_PACK_BYTES:
        return set()
    if not data.startswith(b"UnityFS\0"):
        return {ntpath.basename(path).casefold()}
    _, layout = _preflight_bundle(data, _with_layout=True)
    info = layout["info"]
    blocks, = struct.unpack_from(">i", info, 16)
    cursor = 20 + blocks * 10
    nodes, = struct.unpack_from(">i", info, cursor)
    cursor += 4
    names = set()
    for _ in range(nodes):
        cursor += 20
        end = info.index(b"\0", cursor)
        names.add(ntpath.basename(info[cursor:end].decode("utf-8", "replace")).casefold())
        cursor = end + 1
    return names


def _asset(descriptor):
    """A catalog asset across regions: one asset path and section size.

    The JP and GL catalogs list the same asset in their own packs with their
    own keys; its serialized file names are the same in each.
    """
    return descriptor.get("asset_path"), descriptor.get("size")


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


def _find(scene, transform, names):
    """Unity Transform.Find for a relative path: depth first over children."""
    from .model_viewer import _ref
    if transform is None:
        return None
    if not names:
        return transform
    children = scene.tree(transform).get("m_Children", ())
    for pointer in children[:256]:
        child = _ref(transform, pointer)
        if child is None or child.type.name != "Transform":
            continue
        game = _ref(child, scene.tree(child).get("m_GameObject"))
        if game is not None and scene.name(game) == names[0]:
            found = _find(scene, child, names[1:])
            if found is not None:
                return found
    return None


def member_head(scene, sources):
    """Runtime facts of the one performer head among the selected sources.

    CommonCoreMemberHead.GetFaceDots is headAll.transform.Find("Head_Face/
    mesh_facedots"). ExistsMask sets HasMask from it, and NeedsMergeFace is its
    negation; LiveDirectorBase.ShouldUseRinaFacialTracks requires it. The flag
    is read from the BodyPartManager.headAll actually loaded, never a suit id.
    """
    from .model_viewer import _key, _ref, _source_path
    heads = []
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour" or _source_path(obj) not in sources:
            continue
        _check(scene.deadline)
        try:
            tree = scene.tree(obj)
            if not all(field in tree for field in ("head", "headAll", "face")):
                continue
            script = _ref(obj, tree.get("m_Script"))
            if script is None or script.type.name != "MonoScript":
                continue
            definition = scene.tree(script)
            if (definition.get("m_ClassName"), definition.get("m_Namespace"), definition.get("m_AssemblyName")) != (
                    "BodyPartManager", "LLAS.Components.Members", "Assembly-CSharp.dll"):
                continue
            head_all = _ref(obj, tree.get("headAll"))
            if head_all is None or head_all.type.name != "GameObject":
                continue
            dots = _find(scene, scene.transforms.get(_key(head_all)), ("Head_Face", "mesh_facedots"))
            head = {"faceDots": dots is not None}
            face_component, face = _member_face(scene, obj, tree)
            # A face table that cannot be read only leaves facialTables out;
            # the head's dots, cheek and lip-sync weight do not depend on it.
            try:
                tables = _facial_tables(scene, face_component, face)
            except (AttributeError, KeyError, TypeError, ValueError):
                tables = {}
            if tables:
                head["facialTables"] = tables
            material = _ref(obj, tree.get("headMaterial"))
            # Only InitializeDefault (no mask) adds the cheek, bound to the
            # sharedMaterial of the merged mesh_face/CombineFace; the editor's
            # native merge gives those surfaces BodyPartManager.headMaterial.
            if (dots is None and face is not None and _flag(face.get("needsMergingFace"))
                    and material is not None and material.type.name == "Material"):
                head["cheekMaterial"] = str(scene.tree(material).get("m_Name", ""))
            # InitializeDefault passes MemberFaceData.LipSync.Weight to
            # LiveMemberLipSync.Initialize; the masked heads' mouth controls
            # create every clip at rate 1.
            lip_sync = (face or {}).get("lipSync")
            weight = lip_sync.get("weight") if isinstance(lip_sync, dict) else None
            if dots is None and type(weight) in (int, float) and math.isfinite(weight) and 0 <= weight <= 1:
                head["lipSyncWeight"] = float(weight)
            heads.append(head)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return heads[0] if len(heads) == 1 else {}


def _flag(value):
    return type(value) in (bool, int) and value == 1


def _member_face(scene, manager, tree):
    """BodyPartManager.face and its inline MemberFaceData, verified by its MonoScript."""
    from .model_viewer import _ref
    face = _ref(manager, tree.get("face"))
    if face is None or face.type.name != "MonoBehaviour":
        return None, None
    face_tree = scene.tree(face)
    if not _declares(scene, face, face_tree, "MemberFace", "LLAS.Components.Members"):
        return None, None
    data = face_tree.get("memberFaceData")
    return (face, data) if isinstance(data, dict) else (None, None)


def _declares(scene, component, tree, name, namespace):
    from .model_viewer import _ref
    script = _ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return False
    definition = scene.tree(script)
    return (definition.get("m_ClassName"), definition.get("m_Namespace"),
            definition.get("m_AssemblyName")) == (name, namespace, "Assembly-CSharp.dll")


_FACIAL_TABLES = (("eyes", "animationTableEye"), ("mouth", "animationTableMouth"))
_MAX_FACIAL_ROWS = 256


def _facial_tables(scene, face, data):
    """The face's own eye and mouth MemberFacialAnimationDataTable rows, in serialized order.

    LiveCoreMemberHead.InitializeDefault hands MemberFaceData.AnimationTableMouth to
    LiveMemberLipSync.Initialize and AnimationTableEye to LiveMemberEyeAnimation (and
    LiveMemberEyeContact). Initialize walks its clip enum and
    MemberFacialAnimationBase.CreateAnimationClip plays the first row whose index equals
    the id (Enumerable.FirstOrDefault): that row's clip, whatever its customIndex, e.g.
    mouth 13 (E2) -> LiveFacial_mouth_004. A missing row or a null clip creates no
    playable, so ProcessFrame finds no entry and the index adds nothing. Null rows are
    kept for that reason. A table whose clip is not loaded is left out entirely.
    """
    from .model_viewer import _ref, _source_hash
    result = {}
    if face is None or not isinstance(data, dict):
        return result
    for kind, field in _FACIAL_TABLES:
        table = _ref(face, data.get(field))
        if table is None or table.type.name != "MonoBehaviour":
            continue
        tree = scene.tree(table)
        datas = tree.get("datas")
        if (not _declares(scene, table, tree, "MemberFacialAnimationDataTable", "LLAS.Scene.Live.Components")
                or not isinstance(datas, list) or len(datas) > _MAX_FACIAL_ROWS):
            continue
        rows = []
        for entry in datas:
            values = [entry.get(name) for name in ("index", "customIndex", "summary")] if isinstance(entry, dict) else ()
            if len(values) != 3 or any(type(value) is not int for value in values):
                break
            row = dict(zip(("index", "customIndex", "summary"), values))
            pointer = entry.get("clip")
            if isinstance(pointer, dict) and pointer.get("m_PathID"):
                clip = _ref(table, pointer)
                if clip is None or clip.type.name != "AnimationClip" or not _source_hash(clip):
                    break
                row.update(sourceHash=_source_hash(clip), sourceName=str(scene.name(clip) or "Animation")[:160])
            rows.append(row)
        else:
            result[kind] = rows
    return result


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


def _save(path, data, owner=None, downloaded=False, compared=False):
    _atomic(path, data)
    meta = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "owner": owner}
    if downloaded:
        # The viewer fetched these bytes from the asset server. Later opens
        # give them the place a fresh download would get (see _accept).
        meta["downloaded"] = True
    if compared:
        # Fetched only to compare them with the face a body names, and not
        # used yet: every body gives them a download's place (see _waits).
        meta["compared"] = True
    _atomic(str(path) + ".json", json.dumps(meta).encode())


def _meta(path):
    """The cache metadata saved beside ``path``, or None."""
    try:
        if Path(str(path) + ".json").is_symlink():
            return None
        with open(str(path) + ".json", "rb") as handle:
            raw = handle.read(4097)
        meta = json.loads(raw) if len(raw) <= 4096 else None
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError):
        return None


def _downloaded(path):
    """Whether cached face bytes came from the viewer's own asset download."""
    return (_meta(path) or {}).get("downloaded") is True


def _compared(path):
    """Whether cached face bytes were downloaded only to compare them."""
    return (_meta(path) or {}).get("compared") is True


def _set_compared(path, compared):
    """Mark cached face bytes as fetched only to compare them, or clear that mark."""
    meta = _meta(path)
    if meta is None or (meta.get("compared") is True) == compared:
        return
    if compared:
        meta["compared"] = True
    else:
        meta.pop("compared", None)
    try:
        _atomic(str(path) + ".json", json.dumps(meta).encode())
    except OSError:
        pass


class _SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urlsplit(request.full_url), urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise FaceUnavailable("The original asset server redirected to another host.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _alive(deadline):
    """The download worker's own check: its deadline, or an abandoned transfer."""
    stop = getattr(threading.current_thread(), "face_stop", None)
    if stop is not None and stop.is_set():
        raise FaceUnavailable("The original face download is no longer needed.")
    _check(deadline)


def _download(url, expected, deadline, byte_limit=MAX_PACK_BYTES):
    """Existing CDN's /static/<pack> route, bounded even for missing length headers."""
    _alive(deadline)
    request = Request(url, headers={"User-Agent": "Elichika model viewer"})
    with build_opener(_SameOriginRedirect()).open(request, timeout=min(8, max(1, deadline - time.monotonic()))) as response:
        _alive(deadline)
        length = response.headers.get("Content-Length")
        if length is not None and (int(length) > byte_limit or (expected is not None and int(length) != expected)):
            raise FaceUnavailable("The original asset server returned an unexpected file size.")
        chunks, size = [], 0
        while True:
            _alive(deadline)
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


class _Transfer:
    """One original-asset download on the single network worker.

    At most one daemon may be inside the original downloader; nothing queues.
    The worker receives no FacePlan or cache path and only returns bytes, and
    it stops at ``deadline``. An abandoned result is discarded, so late
    DNS/HTTP completion cannot decrypt assets or publish cache files after the
    caller has returned its base model.
    """

    def __init__(self, url, expected, deadline, byte_limit):
        _check(deadline)
        slot = _DOWNLOAD_SLOT
        if not slot.acquire(blocking=False):
            raise _NoAnswer("An original face download is still finishing. Local facial assets can still be used.")
        self.deadline = deadline
        self.completed, self.lock, self.stop = threading.Event(), threading.Lock(), threading.Event()
        self.state = {"abandoned": False}
        downloader = _download

        def run():
            try:
                try:
                    data = downloader(url, expected, deadline, byte_limit)
                    error = None
                except Exception as exception:
                    data, error = None, exception
                with self.lock:
                    if not self.state["abandoned"]:
                        self.state.update(data=data, error=error)
            finally:
                slot.release()
                self.completed.set()

        try:
            worker = threading.Thread(target=run, name="viewer-face-download", daemon=True)
            worker.face_stop = self.stop
            worker.start()
        except Exception as error:
            slot.release()
            raise FaceUnavailable("The original face download could not be started.") from error

    def result(self, until):
        """The bytes, if the worker finishes by ``until``.

        A wait that ends before the worker's own deadline leaves it running
        (_StillDownloading); calling again keeps waiting for the same bytes.
        """
        finished = self.completed.wait(max(0., until - time.monotonic()))
        with self.lock:
            if not finished or time.monotonic() >= until:
                from .transient_failures import note
                note()
                if until < self.deadline:
                    raise _StillDownloading("The original face download continues in the background.")
                self._abandon()
                raise _NoAnswer("Finding the original face took too long.")
            error, data = self.state.pop("error", None), self.state.pop("data", None)
        if error is not None:
            raise error
        if data is None:
            raise FaceUnavailable("The original face download did not finish.")
        return data

    def abandon(self):
        with self.lock:
            self._abandon()

    def _abandon(self):
        self.state.clear()
        self.state["abandoned"] = True
        self.stop.set()


def _download_with_deadline(url, expected, deadline, byte_limit=MAX_PACK_BYTES, *, wait=None, kept=None):
    """Bound the caller's wait even when OS DNS ignores the socket timeout.

    With ``kept`` (the caller's unfinished downloads by URL), the caller waits
    only until ``wait``. A download still running then stays in ``kept`` with
    its own ``deadline``; asking for the same URL again waits for it instead of
    starting over.
    """
    until = deadline if wait is None else min(wait, deadline)
    transfer = kept.pop(url, None) if kept is not None else None
    if transfer is None:
        transfer = _Transfer(url, expected, deadline, byte_limit)
    try:
        return transfer.result(until)
    except _StillDownloading:
        if kept is None:
            transfer.abandon()
            raise _NoAnswer("Finding the original face took too long.") from None
        kept[url] = transfer
        raise


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
        # The body's own BodyPartManager.face CAB names, its verified game
        # selections, and same-owner candidates kept until no exact face exists.
        self.face_references, self._game_records, self._deferred = set(), [], []
        # Catalog identities of the member's default suit body itself.
        self._suit_models = set()
        # Downloads still running past one step's share of the budget, the
        # face deadline outside any _until, and viewer downloads that are not
        # the referenced face (kept for the late pass, like a fresh download).
        self._kept, self._outer, self._late = {}, None, []
        # (catalog candidate, fetched only to compare it) pairs whose download
        # is still running in ``_kept``.
        self._running = []
        # Cached faces whose bytes this plan downloaded, with their pack.
        self._fetched = {}
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
        if self.needed:
            self.face_references = self._face_references(scene, body_sources)
            self._game_records = self._selected_records(scene, body_sources)

    def _face_references(self, scene, sources):
        """CAB names that the bodies' BodyPartManager.face pointers resolve through.

        The game instantiates exactly that MemberFace prefab. A same-owner face
        with another CAB (the stock face of a costume whose installed face was
        isolated, or another costume's edited face) is a different prefab.
        """
        from .model_viewer import _source_path
        names = set()
        for obj in scene.env.objects:
            if obj.type.name != "MonoBehaviour" or _source_path(obj) not in sources:
                continue
            try:
                tree = scene.tree(obj)
                pointer = tree.get("face")
                if not isinstance(pointer, dict) or "headMaterial" not in tree:
                    continue
                file_id, path_id = pointer.get("m_FileID"), pointer.get("m_PathID")
                externals = obj.assets_file.externals
                if type(file_id) is not int or type(path_id) is not int or not path_id or not 0 < file_id <= len(externals):
                    continue
                if not _declares(scene, obj, tree, "BodyPartManager", "LLAS.Components.Members"):
                    continue
                names.add(ntpath.basename(externals[file_id - 1].path).casefold())
            except Exception:
                continue
        return names

    def _selected_records(self, scene, sources):
        """Game-assets selections registered for these exact body bytes."""
        from .model_viewer import _source_hash, _source_path
        from .viewer_mod_sources import imported_record
        hashes = {}
        for obj in scene.env.objects:
            source = _source_path(obj)
            if source in sources and source not in hashes:
                hashes[source] = _source_hash(obj)
        origins = self.context.get("origins", {})
        # Archive members and motion copies have another origin; only the
        # imported model file itself carries the server's receipt.
        eligible = [source for source in sorted(hashes) if origins.get(source, source) == source]
        records = []
        for source in eligible:
            record = imported_record(source, hashes[source])
            if record is None:
                # A restart empties the in-memory registry. The import cache
                # keeps its own receipt binding these exact bytes to the suit.
                record = self._stored_record(source, hashes[source])
            if record is not None and record not in records:
                records.append(record)
        return records

    def _stored_record(self, source, digest):
        """The selection the Game-assets import cache persisted for these bytes.

        Only the application's own game-model cache is read, and only a
        receipt bound to this file's path and SHA counts.
        """
        root = self.context.get("game_models_dir")
        if not isinstance(root, str) or not root:
            return None
        from .viewer_mod_flow import stored_receipt
        from .viewer_mod_sources import _record
        try:
            row = stored_receipt(source, digest, root)
            return None if row is None else _record(row["record"])
        except Exception:
            return None

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

        # Selected files' parents are already jailed by the server. Walk them
        # by their resolved path, as every file found is compared resolved.
        roots = [os.path.realpath(os.path.dirname(p)) for p in self.paths]
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

    def _selected_iter(self):
        """The selected game costume's own dependencies, as the client loads them.

        A Game-assets selection names its suit and model. The client loads
        that model's member_model_dependency rows with the body, so this is
        the face its BodyPartManager was built against, including the private
        face an installed edited costume depends on instead of the stock one.
        """
        root = self.context.get("repo_root")
        if not root:
            return
        seen = set()
        for record in self._game_records:
            region, model, suit = record.get("region"), record.get("model"), record.get("suit_id")
            platform = record.get("platform", "android")
            if (record.get("scene_source") is not None or region not in ("gl", "jp") or platform not in ("android", "ios")
                    or not isinstance(model, str) or not model or type(suit) is not int):
                continue
            prefix = "asset_i_" if platform == "ios" else "asset_a_"
            language = record.get("selection_language", "en")
            directory = Path(root) / "assets" / "db" / region
            catalogs = sorted(directory.glob(prefix + "*.db"),
                              key=lambda path: (path.name != f"{prefix}{language}.db", path.name != prefix + "en.db", path.name))
            for catalog in catalogs[:16]:
                _check(self.deadline)
                try:
                    with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                        dependencies = [row[0] for row in db.execute(
                            "SELECT dependency FROM member_model_dependency WHERE asset_path=? LIMIT 64", (model,))]
                        keys = [key for key in dict.fromkeys(dependencies) if key != model]
                        records = {}
                        if keys:
                            parameters = ",".join("?" for _ in keys)
                            for row in db.execute(f"SELECT asset_path,pack_name,head,size,key1,key2 FROM member_model WHERE asset_path IN ({parameters})", keys):
                                records.setdefault(row[0], row)
                        sizes = _pack_sizes(db, list(dict.fromkeys(row[1] for row in records.values())), suit)
                except (OSError, sqlite3.Error, TypeError, ValueError):
                    continue
                resources = [dict(zip(("asset_path", "pack_name", "head", "size", "key1", "key2"), row), pack_size=sizes.get(row[1]))
                             for row in records.values()]
                if not resources:
                    continue
                # One catalog is this selection's authority; other language
                # catalogs of the same region repeat the same packs.
                resources.sort(key=lambda resource: -resource["size"] if isinstance(resource["size"], int) else 0)
                for resource in resources[:MAX_AUTO_FILES]:
                    identity = tuple(resource[key] for key in ("pack_name", "head", "size", "key1", "key2", "pack_size"))
                    if identity not in seen:
                        seen.add(identity)
                        yield resource
                break

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
                            if body and resource is body[0]:
                                self._suit_models.add(identity)
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

        plain, packed, managed_pack, downloaded, compared, fetched = None, None, None, False, False, False
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
            downloaded = packed is not None and _downloaded(cached_pack)
            compared = packed is not None and _compared(cached_pack)
            if packed is None:
                if not download or not self.context.get("allow_download", True):
                    raise FaceUnavailable("Original face downloads are disabled.")
                base = self.context.get("cdn_base") or extractor.DEFAULT_CDN_BASE
                parsed = urlsplit(base)
                if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise FaceUnavailable("Configure a valid HTTPS original-asset CDN.")
                url = base.rstrip("/") + "/" + pack_name
                limit = MAX_PACK_BYTES
                if url not in self._kept:
                    remaining = MAX_TRANSFER_BYTES - self.transferred
                    reservation = pack_size if pack_size is not None else MAX_PACK_BYTES
                    if reservation > remaining:
                        raise FaceUnavailable("The original face exceeds the download budget.")
                    # Reserve before opening a socket, including failed attempts.
                    self.transferred += reservation
                    limit = min(MAX_PACK_BYTES, remaining)
                # The worker may use the whole face budget even while this step
                # waits only for its share; an unfinished download is kept.
                outer = self._outer if self._outer is not None else self.deadline
                packed = _download_with_deadline(url, pack_size, outer, limit, wait=self.deadline, kept=self._kept)
                if not 0 < len(packed) <= MAX_PACK_BYTES or (pack_size is not None and len(packed) != pack_size):
                    raise FaceUnavailable("The original asset download was incomplete.")
                downloaded = fetched = True
            try:
                plain = decrypt(packed[head:head + size])
            except FaceUnavailable:
                # Do not publish wrong-platform/HTML responses as cache hits.
                managed_pack.unlink(missing_ok=True)
                Path(str(managed_pack) + ".json").unlink(missing_ok=True)
                raise
        if managed_pack is not None:
            _save(managed_pack, packed, downloaded=downloaded, compared=compared)
        _save(output, plain, self.owner, downloaded=downloaded, compared=compared)
        if fetched:
            self._fetched[str(output)] = str(managed_pack)
        self.database_paths.add(str(output))
        return str(output)

    def resolve(self):
        if not self.enabled or self.owner is None:
            return []
        try:
            pending, selected_pending = [], []
            try:
                for path in self._verified_companions():
                    self._accept(path)
            except SavedFacePlatformMismatch:
                raise
            except Exception:
                pass
            # A Game-assets body names its own suit. The client loads that
            # suit's dependencies with it, so they come before owner-wide
            # caches and the member's default suit: an installed edited
            # costume depends on its private face, not on the stock one.
            try:
                if self.needed:
                    for descriptor in self._selected_iter():
                        _check(self.deadline)
                        try:
                            if self._accept(self._resource(descriptor, download=False), exact=True, own=True):
                                break
                        except Exception:
                            selected_pending.append(descriptor)
            except Exception:
                pass
            # A downloaded same-owner original must not wait behind catalog
            # scans. Names only select candidates; _accept validates contents.
            # A referenced face found by its native name outside the body's
            # folder and the extractor's own library folders may be an edited
            # copy, so it waits like ``later`` below.
            later = []
            try:
                if self.needed:
                    for path in self._known_local():
                        if (self.face_references and not self._in_cache(path) and not self._beside(path)
                                and not self._extracted(path) and self._referenced(path)):
                            if path not in later:
                                later.append(path)
                            continue
                        if self._accept(path, exact=True):
                            break
            except Exception:
                pass
            # Exact original/cache identities come before the broad Unity-file
            # search. A populated library must not consume the entire facial
            # budget before we can reuse its already-downloaded original pack.
            # ``checked`` holds the catalog assets already decrypted here.
            checked = set()
            try:
                if self.needed:
                    for descriptor in self._descriptor_iter():
                        _check(self.deadline)
                        if self.face_references and self._suit_model(descriptor):
                            # The default suit's own body is not the face a
                            # BodyPartManager references. It stays a late,
                            # non-exact candidate, never decrypted or fetched
                            # only to be compared.
                            pending.append(descriptor)
                            continue
                        try:
                            path = self._resource(descriptor, download=False)
                            checked.add(_asset(descriptor))
                            if self._accept(path, exact=True):
                                break
                            if path in self._late:
                                # An earlier open downloaded it: it keeps the
                                # place that download had, in the late pass.
                                pending.append(descriptor)
                        except Exception:
                            pending.append(descriptor)
            except Exception:
                # Standalone/local-only viewers do not need an asset catalog.
                pass
            # Downloads that may still find the referenced face leave the last
            # FALLBACK_SECONDS of the face budget to another prefab. One still
            # running then is kept and finished by the late pass if no other
            # prefab is used; only real answers mark a candidate as failed.
            allow = self.context.get("allow_download", True)
            reserve = max(time.monotonic(), self.deadline - FALLBACK_SECONDS)
            # The client downloads its own suit's missing face pack; do the
            # same before settling for another prefab of this member.
            answered, selected_failed = True, set()
            try:
                if self.needed and allow and selected_pending:
                    with self._until(reserve):
                        answered = self._fetch_exact(selected_pending, set(), selected_failed)
            except Exception:
                pass
            # The referenced face may sit next to the body: the viewer saves an
            # edited face beside it, and that face is used at once. One found
            # elsewhere in the library may be an edited copy of a catalog face
            # with the same serialized names, so it waits until the catalog's
            # own copy has been tried. Every other same-member file is kept,
            # in the old order, for the fallback.
            local_span, local_time = None, None
            if self.needed and self.face_references:
                start = len(self._deferred)
                local_time = self._search_local(pending, exact=True, later=later)
                local_span = (start, len(self._deferred))
            # A stock body's referenced face may only be on the CDN while
            # another prefab of this member is cached. Fetch the catalog
            # candidates that may still be it. One that is not keeps its old,
            # late place below; a failed one is not tried twice.
            failed = set()
            try:
                if self.needed and allow and answered and self.face_references and pending:
                    with self._until(reserve):
                        self._fetch_exact(pending, checked, failed, compare=True)
            except Exception:
                pass
            # A referenced face kept for ``later`` is used now: the catalog's
            # own copy was not found (it failed, did not answer, is still
            # downloading, or downloads are off). It has the face deadline,
            # whatever time the broad search left.
            try:
                for path in later:
                    if not self.needed or self._accept(path):
                        break
            except Exception:
                pass
            # The broad search keeps one bound for its walk and the other
            # candidates it kept, as before.
            limit = []

            def accept_local(path):
                if local_time is None:
                    return self._accept(path)
                if not limit:
                    limit.append(time.monotonic() + local_time)
                with self._until(limit[0]):
                    return self._accept(path)

            # None of those is the face the body references, e.g. a mod
            # renamed its face but left it out. Keep the earlier choice: the
            # first same-owner candidate, in the same order as before.
            try:
                for position, path in enumerate(list(self._deferred)):
                    if not self.needed:
                        break
                    if local_span and local_span[0] <= position < local_span[1]:
                        if accept_local(path):
                            break
                    elif self._accept(path):
                        break
            except Exception:
                pass
            if self.needed and local_span is None:
                self._search_local(pending)
            # The late pass: downloads in their old order, with the whole
            # budget. A download kept running above is waited for, not
            # restarted, unless a fallback before it in that order needs the
            # network. Faces the viewer downloaded earlier come last.
            if self.needed:
                late = [descriptor for index, descriptor in enumerate(selected_pending) if index not in selected_failed]
                late += [descriptor for index, descriptor in enumerate(pending) if index not in failed]
                # Where the download still running stands in the old order.
                running = next((index for index, item in enumerate(late)
                                if any(item is descriptor for descriptor, _ in self._running)), 0)
                for position, item in enumerate(late + list(self._late)):
                    if not self.needed:
                        break
                    _check(self.deadline)
                    try:
                        path = item if isinstance(item, str) else None
                        if path is None and self._running:
                            try:
                                path = self._resource(item, download=False)
                            except Exception:
                                # A new download needs the one network worker.
                                # The running download may be the face the
                                # body names, so it finishes first. An item
                                # before it in the old order (the fallback the
                                # old order used) waits for it at most half of
                                # the time left; then it is stopped.
                                until = (None if position >= running else
                                         time.monotonic() + max(0., self.deadline - time.monotonic()) / 2)
                                if self._finish_running(until):
                                    break
                                self._drop_running()
                        if path is None:
                            path = self._resource(item)
                        if self._accept(path):
                            break
                    except Exception:
                        # One missing optional pack cannot hide a costume.
                        continue
        except SavedFacePlatformMismatch:
            raise
        except Exception:
            pass
        finally:
            # A download no longer waited for stops; its bytes are discarded.
            for transfer in self._kept.values():
                transfer.abandon()
            self._kept.clear()
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

    def _suit_model(self, descriptor):
        return tuple(descriptor.get(key) for key in ("pack_name", "head", "size", "key1", "key2", "pack_size")) in self._suit_models

    @contextmanager
    def _until(self, deadline):
        """Bound one step by ``deadline``, never past the face deadline."""
        original, outer = self.deadline, self._outer
        if outer is None:
            self._outer = original
        self.deadline = min(original, deadline)
        try:
            yield
        finally:
            self.deadline, self._outer = original, outer

    def _beside_dirs(self):
        """The folders the selected files are in, as chosen and as resolved."""
        folders = set()
        for path in self.paths:
            folders.add(os.path.realpath(os.path.dirname(path)))
            folders.add(os.path.dirname(os.path.realpath(path)))
        return folders

    def _beside(self, path):
        return os.path.dirname(os.path.realpath(path)) in self._beside_dirs()

    def _extracted(self, path):
        """Whether ``path`` is in a folder where the asset extractor writes member models.

        These are the library roots and their 3d_model and extracted/3d_model
        folders, the places ``_known_local`` probes for the extractor's own
        chNNNN_facedynamic/chNNNN_face names. A face there is used at once, as
        before; an edited copy saved there under that name is trusted too.
        """
        folders = set()
        for root in self.context.get("library_roots", []):
            for relative in ("", "3d_model", os.path.join("extracted", "3d_model")):
                folders.add(os.path.realpath(os.path.join(os.path.realpath(root), relative)))
        return os.path.dirname(os.path.realpath(path)) in folders

    def _in_cache(self, path):
        """Whether ``path`` is one of the face cache's own model files."""
        cache = self.context.get("cache_dir")
        if not cache:
            return False
        try:
            directory = os.path.realpath(_cache_root(cache) / "models")
        except (OSError, FaceUnavailable):
            return False
        return os.path.dirname(os.path.realpath(path)) == directory

    def _search_local(self, pending, *, exact=False, later=None):
        """The broad same-member file search, with its old bound.

        With a catalog original still to download, the walk and the
        candidates it accepts share LOCAL_SECONDS. Returns what remains of them
        for candidates kept for later, or None when unbounded. With ``later``,
        only a referenced face beside a selected body is accepted here; one
        elsewhere is added to ``later`` and any other file is deferred. A face
        the viewer downloaded only to compare it keeps a download's place.
        """
        bounded = bool(pending) and self.context.get("allow_download", True)
        beside = self._beside_dirs()
        started = time.monotonic()
        try:
            # Leave time to obtain a known original when a large local
            # collection contains no usable same-character donor.
            with self._until(started + LOCAL_SECONDS if bounded else self.deadline):
                for path in self._local():
                    if later is not None and os.path.dirname(os.path.realpath(path)) not in beside:
                        if self._referenced(path):
                            if path not in later:
                                later.append(path)
                        elif self._late_download(path):
                            if path not in self._late:
                                self._late.append(path)
                        elif path not in self._deferred:
                            self._deferred.append(path)
                        continue
                    if not self.face_references and self._waits(path):
                        continue
                    if self._accept(path, exact=exact):
                        break
        except Exception:
            pass
        return max(0., LOCAL_SECONDS - (time.monotonic() - started)) if bounded else None

    def _referenced(self, path):
        try:
            return bool(_serialized_names(path) & self.face_references)
        except Exception:
            return False

    def _fetch_exact(self, descriptors, checked, failed, *, compare=False):
        """Download catalog candidates that may be the referenced face.

        A ``compare`` candidate that is not that face is not deferred: its
        old place is the late download pass. Other regions' copies of an
        asset already decrypted here (same path and size, so the same
        serialized names) and further assets of a pack that just failed are
        not fetched. Returns False once the CDN does not answer at all, so
        nothing else waits for it.

        Only an answer marks a candidate as ``failed``: an HTTP error, wrong
        or incomplete bytes, a network that does not answer. Running out of
        this step's share of the time, or a busy network worker, ends the step
        and leaves the candidate to the late pass, which has the whole budget
        and finishes a download still running from here.
        """
        from urllib.error import HTTPError
        broken = set()
        for index, descriptor in enumerate(descriptors):
            if not self.needed:
                break
            if descriptor.get("pack_name") in broken or compare and (
                    self._suit_model(descriptor) or _asset(descriptor) in checked):
                continue
            _check(self.deadline)
            try:
                path = self._resource(descriptor)
            except _NoAnswer as error:
                if isinstance(error, _StillDownloading):
                    self._running.append((descriptor, compare))
                return True
            except Exception as error:
                failed.add(index)
                broken.add(descriptor.get("pack_name"))
                if isinstance(error, OSError) and not isinstance(error, HTTPError):
                    return False
                continue
            if compare:
                self._compared_now(path)
            checked.add(_asset(descriptor))
            if self._accept(path, exact=True, defer=not compare, own=not compare):
                break
        return True

    def _late_download(self, path):
        """A face cached only because the viewer downloaded it.

        Without the cache it would be downloaded again, in the late pass, so
        it keeps that place in every later open: whether an earlier open
        fetched it cannot change the choice.
        """
        return self._in_cache(path) and _downloaded(path)

    def _compared_now(self, path):
        """Mark a face this plan downloaded only to compare it, with its pack."""
        if path in self._fetched:
            _set_compared(path, True)
            if self._fetched[path]:
                _set_compared(self._fetched[path], True)

    def _finish_running(self, until=None):
        """Wait for the downloads kept running, until ``until`` at most.

        True once the named face is in. A download still running then stays
        in ``_kept`` for ``_drop_running``.
        """
        running, self._running = self._running, []
        for descriptor, compare in running:
            try:
                with self._until(self.deadline if until is None else until):
                    path = self._resource(descriptor)
                if compare:
                    self._compared_now(path)
                if self._accept(path, exact=True, defer=False, own=not compare):
                    return True
            except Exception:
                continue
        return False

    def _drop_running(self):
        """Stop the downloads still kept running and wait for the network worker.

        The worker stops at its next chunk; its bytes are discarded.
        """
        self._running = []
        transfers = list(self._kept.values())
        self._kept.clear()
        for transfer in transfers:
            transfer.abandon()
        for transfer in transfers:
            transfer.completed.wait(max(0., self.deadline - time.monotonic()))

    def _waits(self, path, defer=True, own=False):
        """Whether a candidate keeps a later place instead of being used now.

        With a body reference, another face prefab of the same member is only
        a fallback while the face it references may still be found. For every
        body, a face the viewer downloaded only to compare it keeps the place
        a fresh download has, so that download cannot change later choices;
        the selected game costume's ``own`` faces are not held back by it.
        """
        if self.face_references:
            if self._referenced(path):
                return False
            if self._late_download(path):
                if path not in self._late:
                    self._late.append(path)
            elif defer and path not in self._deferred:
                self._deferred.append(path)
            return True
        if not own and self._in_cache(path) and _compared(path):
            if path not in self._late:
                self._late.append(path)
            return True
        return False

    def _accept(self, path, exact=False, defer=True, own=False):
        if path in self.paths or path in self.auto_paths or len(self.auto_paths) >= MAX_AUTO_FILES:
            return False
        if exact and self._waits(path, defer, own):
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
            if self._in_cache(path) and _compared(path):
                # Used now: from here on it is a face the viewer downloaded.
                _set_compared(path, False)
                if self._fetched.get(path):
                    _set_compared(self._fetched[path], False)
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
            # MergeAndCombineFaceMesh.MergeFace (GL 3.12.0 0x2c94ff4) also gives
            # headMaterial to every Renderer below headAll (set_sharedMaterial
            # loop at 0x2c95478) when the face needs merging. A costume's own
            # Hair keeps its serialized material only on masked heads.
            try:
                head_all = _ref(obj, tree.get("headAll"))
                face_data = scene.tree(face).get("memberFaceData")
            except Exception:
                continue
            merge = face_data.get("needsMergingFace") if isinstance(face_data, dict) else None
            if (head_all is None or head_all.type.name != "GameObject" or type(merge) not in (bool, int) or merge != 1
                    or material.assets_file is not obj.assets_file
                    or _find(scene, scene.transforms.get(_key(head_all)), ("Head_Face", "mesh_facedots")) is not None):
                continue
            for renderer, _, game_object in scene.renderers:
                if _source_path(renderer) != _source_path(obj) or not beneath(game_object, head_all):
                    continue
                key = _key(renderer)
                if key not in bindings:
                    bindings[key] = material
                elif bindings[key] is not None and _key(bindings[key]) != _key(material):
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
