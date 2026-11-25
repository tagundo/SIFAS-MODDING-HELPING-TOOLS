"""Read-only, bounded UnityFS to GLB conversion for the local 3D viewer.

Only explicitly supplied bundle bytes are loaded. Unity dependencies can resolve
to another supplied bundle or an embedded resource, never to an arbitrary file.
The GLB contains static rest geometry and original-size PNG textures; source
meshes, skin weights, texture pixels and bundle files are never written.
"""
from collections import OrderedDict
import io
import hashlib
import json
import math
import ntpath
import os
import re
import secrets
import struct
import threading
import time
import zlib

from . import decode


MAX_FILES = 8
MAX_MOTION_FILES = 256
# Public selections and trusted dependencies have separate bounded slots.
# The retained motion library has separate slots from model selections and
# trusted facial/preview dependencies; existing byte/geometry limits still apply.
MAX_INTERNAL_FILES = MAX_FILES + MAX_MOTION_FILES + 4 + 4
MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 192 * 1024 * 1024
MAX_UNPACKED_BYTES = 192 * 1024 * 1024
MAX_VERTICES = 250_000
MAX_TRIANGLES = 500_000
MAX_MESHES = 128
MAX_NATIVE_STAGE_EFFECT_MESHES = 192
MAX_TEXTURE_PIXELS = 32 * 1024 * 1024
MAX_GLB_BYTES = 64 * 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_CACHE_ENTRIES = 2
CACHE_SECONDS = 600
BUILD_SECONDS = 120
FINAL_BINDING_SECONDS = 20

_BUILD_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_SESSIONS = OrderedDict()
_CONVERSION_LOCK = threading.Lock()
_REQUEST_STATE = threading.local()
_TEXTURE_PNGS = OrderedDict()
_NORMALIZED_BUNDLES = OrderedDict()
MAX_TEXTURE_CACHE_BYTES = 24 * 1024 * 1024
MAX_TEXTURE_CACHE_ENTRIES = 64
MAX_BUNDLE_CACHE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_CACHE_ENTRIES = 4
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ModelViewerError(ValueError):
    """An input cannot be shown by the model viewer."""


class ViewerBusyError(ModelViewerError):
    """Another bounded conversion is already using the worker."""


def _remaining(deadline):
    if time.monotonic() >= deadline:
        raise ModelViewerError("Model preview took too long. Try opening fewer model files.")


def _conversion_get(cache, key, deadline):
    """Share only immutable conversion bytes, never rigs, trees or edit state."""
    _remaining(deadline)
    if getattr(_REQUEST_STATE, "reimport", False):
        return None
    with _CONVERSION_LOCK:
        now = time.monotonic()
        for previous, value in list(cache.items()):
            if value[0] <= now:
                del cache[previous]
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
    if value is not None:
        _remaining(deadline)
        return value[1]
    return None


def _conversion_put(cache, key, data, *, max_bytes, max_entries):
    if not isinstance(data, bytes) or len(data) > max_bytes:
        return
    with _CONVERSION_LOCK:
        cache[key] = (time.monotonic() + CACHE_SECONDS, data)
        cache.move_to_end(key)
        while len(cache) > max_entries or sum(len(value[1]) for value in cache.values()) > max_bytes:
            cache.popitem(last=False)


def _normalized_bundle(data, layout, deadline):
    # Preflight is always performed by _environment before consulting this
    # content-addressed cache. Raw/LZ4 inputs already avoid normalization.
    if layout is None or (layout["flags"] & 0x3f != 1
                          and not any(flags & 0x3f == 1 for _, _, flags in layout["blocks"])):
        return _bounded_bundle(data, layout, deadline)
    key = (hashlib.sha256(data).digest(), id(_bounded_bundle))
    value = _conversion_get(_NORMALIZED_BUNDLES, key, deadline)
    if value is None:
        value = _bounded_bundle(data, layout, deadline)
        _conversion_put(_NORMALIZED_BUNDLES, key, value,
                        max_bytes=MAX_BUNDLE_CACHE_BYTES, max_entries=MAX_BUNDLE_CACHE_ENTRIES)
    _remaining(deadline)
    return value


def _paths(paths, *, internal=False):
    limit = MAX_INTERNAL_FILES if internal else MAX_FILES
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= limit:
        raise ModelViewerError("The model has too many automatic dependencies." if internal else "Choose between one and eight extracted Unity model files.")
    result, total = [], 0
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ModelViewerError("Choose an extracted Unity model file.")
        path = os.path.realpath(os.path.expanduser(raw))
        if path in result:
            continue
        if not os.path.isfile(path):
            raise ModelViewerError("A selected model file no longer exists.")
        size = os.path.getsize(path)
        if not 0 < size <= MAX_SOURCE_BYTES:
            raise ModelViewerError("A model file is too large for the mobile viewer.")
        total += size
        if total > MAX_TOTAL_SOURCE_BYTES:
            raise ModelViewerError("The selected model files are too large. Open fewer files.")
        result.append(path)
    return result


def _cstring(data, position, limit=4096):
    end = data.find(b"\0", position, min(len(data), position + limit + 1))
    if end < 0:
        raise ModelViewerError("The selected Unity bundle has an invalid header.")
    return data[position:end], end + 1


def _block_info(data, expected, compression):
    if compression == 0:
        value = data
    elif compression in (2, 3):
        import lz4.block
        value = lz4.block.decompress(data, uncompressed_size=expected)
    elif compression == 1:
        import lzma
        if len(data) < 5:
            raise ModelViewerError("The selected Unity bundle is truncated.")
        properties, dictionary = struct.unpack_from("<BI", data)
        if properties >= 9 * 5 * 5 or dictionary > 64 * 1024 * 1024:
            raise ModelViewerError("The selected Unity bundle exceeds the preview memory limit.")
        remainder = properties // 9
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{
            "id": lzma.FILTER_LZMA1, "dict_size": max(dictionary, 4096),
            "lc": properties % 9, "lp": remainder % 5, "pb": remainder // 5,
        }])
        value = decoder.decompress(data[5:], max_length=expected + 1)
    else:
        raise ModelViewerError("This Unity bundle compression is unavailable in the viewer.")
    if len(value) != expected:
        raise ModelViewerError("The selected Unity bundle has invalid block information.")
    return value


def _preflight_bundle(data, _with_layout=False):
    """Bound allocations before UnityPy decompresses the mesh/texture payload."""
    if not data.startswith(b"UnityFS\0"):
        # Raw serialized .assets/.unity files are also useful for extracted mesh
        # assets. Their declared file/metadata sizes must fit the supplied bytes.
        try:
            metadata, size, version, offset = struct.unpack_from(">IIII", data)
            header_size = 20
            if not 14 <= version <= 22:
                raise ValueError("Unsupported serialized version")
            if version >= 22:
                metadata, size, offset = struct.unpack_from(">Iqq", data, 20)
                header_size = 48
            if len(data) < header_size or size != len(data) or not 0 < metadata <= 16 * 1024 * 1024 \
                    or not header_size <= offset <= size or data[16] not in (0, 1):
                raise ValueError("Invalid serialized header")
            return (len(data), None) if _with_layout else len(data)
        except (struct.error, ValueError, IndexError) as error:
            raise ModelViewerError("Choose an extracted Unity model bundle, not an APK or image.") from error
    try:
        version, = struct.unpack_from(">I", data, 8)
        if version not in (6, 7, 8):
            raise ModelViewerError("This Unity bundle version is unavailable in the viewer.")
        _, position = _cstring(data, 12, 256)  # player version (often "5.x.x")
        engine, position = _cstring(data, position, 256)
        fields_offset = position
        length, compressed, uncompressed, flags = struct.unpack_from(">QIII", data, position)
        position += 20
        if length > len(data) or not 20 <= uncompressed <= 4 * 1024 * 1024 \
                or not 0 < compressed <= 4 * 1024 * 1024:
            raise ModelViewerError("The selected Unity bundle is truncated or too large.")
        parsed = re.match(rb"(\d+)\.(\d+)\.(\d+)", engine)
        engine_version = tuple(map(int, parsed.groups())) if parsed else (0, 0, 0)
        if version >= 7 or (engine_version[:2] == (2019, 4) and engine_version[2] >= 15):
            position = (position + 15) & ~15
        start = len(data) - compressed if flags & 0x80 else position
        if start < 0 or start + compressed > len(data):
            raise ModelViewerError("The selected Unity bundle is truncated.")
        info = _block_info(data[start:start + compressed], uncompressed, flags & 0x3F)
        count, = struct.unpack_from(">i", info, 16)
        if not 1 <= count <= 8192:
            raise ModelViewerError("The selected Unity bundle has too many data blocks.")
        cursor, unpacked, packed, blocks = 20, 0, 0, []
        for _ in range(count):
            size, compressed_size, block_flags = struct.unpack_from(">IIH", info, cursor)
            cursor += 10
            # LZMA data is normalized with a capped decoder before UnityPy sees
            # it; its legacy native decompressor must never receive this input.
            if block_flags & 0x3F not in (0, 1, 2, 3):
                raise ModelViewerError("This Unity bundle compression is unavailable in the viewer.")
            if size > 64 * 1024 * 1024:
                raise ModelViewerError("The model exceeds the preview memory limit.")
            if block_flags & 0x3F == 0 and size != compressed_size:
                raise ModelViewerError("The selected Unity bundle has invalid data blocks.")
            unpacked += size
            packed += compressed_size
            blocks.append((size, compressed_size, block_flags))
        if unpacked > MAX_UNPACKED_BYTES or packed > len(data):
            raise ModelViewerError("The model exceeds the preview memory limit.")
        nodes, = struct.unpack_from(">i", info, cursor)
        cursor += 4
        if not 1 <= nodes <= 4096:
            raise ModelViewerError("The selected Unity bundle has too many embedded files.")
        for _ in range(nodes):
            offset, size, _flags = struct.unpack_from(">qqI", info, cursor)
            cursor += 20
            _, cursor = _cstring(info, cursor)
            if offset < 0 or size < 0 or offset + size > unpacked:
                raise ModelViewerError("The selected Unity bundle has invalid embedded files.")
        payload = position if flags & 0x80 else position + compressed
        modern_padding = engine_version >= (2020, 3, 34) if engine_version[0] == 2020 else (
            engine_version >= (2021, 3, 2) if engine_version[0] == 2021 else engine_version >= (2022, 1, 1))
        if modern_padding and flags & 0x200:
            payload = (payload + 15) & ~15
        payload_end = len(data) - compressed if flags & 0x80 else len(data)
        if payload + packed > payload_end:
            raise ModelViewerError("The selected Unity bundle is truncated.")
        if not _with_layout:
            return unpacked
        return unpacked, {"info": info, "blocks": blocks, "payload": payload,
                          "prefix": data[:fields_offset], "aligned": position != fields_offset + 20,
                          "flags": flags}
    except ModelViewerError:
        raise
    except Exception as error:
        raise ModelViewerError("The selected Unity bundle is damaged or unsupported.") from error


def _bounded_bundle(data, layout, deadline):
    """Replace only LZMA compression in memory, preserving every asset byte."""
    if layout is None or (layout["flags"] & 0x3F != 1
                          and not any(flags & 0x3F == 1 for _, _, flags in layout["blocks"])):
        return data
    info, payload = bytearray(layout["info"]), layout["payload"]
    payload_size = 0
    for index, (size, compressed, flags) in enumerate(layout["blocks"]):
        if flags & 0x3F == 1:
            struct.pack_into(">IIH", info, 20 + index * 10, size, size, flags & ~0x3F)
        payload_size += size if flags & 0x3F == 1 else compressed
    prefix = layout["prefix"]
    padding = bytes(-(len(prefix) + 20) % 16) if layout["aligned"] else b""
    length = len(prefix) + 20 + len(padding) + len(info) + payload_size
    # Block-info is also uncompressed, preventing UnityPy's unbounded LZMA
    # decoder from handling either metadata or data. File offsets stay intact.
    header = struct.pack(">QIII", length, len(info), len(info), 0x40)
    output = io.BytesIO()
    output.write(prefix)
    output.write(header)
    output.write(padding)
    output.write(info)
    # Keep only one bounded decoded block alive, rather than retaining every
    # block plus a joined payload plus a concatenated copy on mobile devices.
    for size, compressed, flags in layout["blocks"]:
        _remaining(deadline)
        chunk = data[payload:payload + compressed]
        payload += compressed
        output.write(_block_info(chunk, size, 1) if flags & 0x3F == 1 else chunk)
        _remaining(deadline)
    return output.getvalue()


def _environment(paths, deadline, base_env=None):
    import UnityPy
    from UnityPy.environment import simplify_name

    class PreviewEnvironment(UnityPy.Environment):
        def load_file(self, file, parent=None, name=None, is_dependency=False):
            if isinstance(file, (str, os.PathLike)):
                raise FileNotFoundError("Only explicitly selected model bundles can be loaded.")
            return super().load_file(file, parent=parent, name=name, is_dependency=is_dependency)

        def find_file(self, name, is_dependency=True):
            found = self.get_cab(name) or self.get_cab(ntpath.basename(name))
            if found is None:
                raise FileNotFoundError("A linked asset was not included in the selected files.")
            return found

    env = base_env if base_env is not None else PreviewEnvironment()
    unpacked_total = getattr(env, "preview_unpacked_total", 0)
    start_index = len(env.files)
    for index, path in enumerate(paths, start_index):
        _remaining(deadline)
        with open(path, "rb") as file:
            data = file.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ModelViewerError("The model file grew beyond the preview memory limit.")
        unpacked, layout = _preflight_bundle(data, _with_layout=True)
        unpacked_total += unpacked
        if unpacked_total > MAX_UNPACKED_BYTES:
            raise ModelViewerError("The selected models exceed the preview memory limit.")
        # The input has already been jailed by the server. Loading bytes rather
        # than a filename prevents UnityPy from walking neighbouring directories.
        loaded = env.load_file(_normalized_bundle(data, layout, deadline), name=f"preview-{index}-{os.path.basename(path)}")
        loaded.preview_source_name = os.path.basename(path)
        loaded.preview_source_path = path
        loaded.preview_source_hash = hashlib.sha256(data).hexdigest()
        # Raw serialized assets may be linked by their filename rather than an
        # embedded CAB id. Register only explicitly supplied, in-memory content.
        if hasattr(loaded, "objects"):
            env.register_cab(os.path.basename(path), loaded)
    env.preview_unpacked_total = unpacked_total
    class AssetScope:
        """Prefer this asset's own resources when original/baked CAB ids match."""
        def __init__(self, asset):
            self.asset = asset

        def __getattr__(self, name):
            return getattr(env, name)

        def get_cab(self, name):
            wanted = simplify_name(name)
            container = self.asset.parent
            if container is not None and container is not env:
                for key, value in container.files.items():
                    if simplify_name(key) == wanted:
                        return value
            return env.get_cab(name)

        def find_file(self, name, is_dependency=True):
            value = self.get_cab(name) or self.get_cab(ntpath.basename(name))
            if value is None:
                raise FileNotFoundError("A linked asset was not included in the selected files.")
            return value

    for asset in env.assets:
        asset.environment = AssetScope(asset)
    return env


def _ref(owner, pointer):
    if not pointer or not pointer.get("m_PathID"):
        return None
    from UnityPy.classes.PPtr import PPtr
    try:
        return PPtr(m_FileID=int(pointer.get("m_FileID", 0)),
                    m_PathID=int(pointer["m_PathID"]), assetsfile=owner.assets_file).deref()
    except (KeyError, ValueError, FileNotFoundError):
        return None


def _key(obj):
    return id(obj.assets_file), obj.path_id


def _source_name(obj):
    container = obj.assets_file
    for _ in range(64):
        name = getattr(container, "preview_source_name", None)
        if name:
            return name
        container = getattr(container, "parent", None)
        if container is None:
            break
    return ""


def _source_path(obj):
    container = obj.assets_file
    for _ in range(64):
        path = getattr(container, "preview_source_path", None)
        if path:
            return path
        container = getattr(container, "parent", None)
        if container is None:
            break
    return ""


def _source_hash(obj):
    container = obj.assets_file
    for _ in range(64):
        value = getattr(container, "preview_source_hash", None)
        if value:
            return value
        container = getattr(container, "parent", None)
        if container is None:
            break
    return ""


def _trs(tree):
    import numpy as np
    rotation = tree.get("m_LocalRotation", {})
    x, y, z, w = [float(rotation.get(axis, 1 if axis == "w" else 0)) for axis in "xyzw"]
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm < 1e-12:
        raise ModelViewerError("A model transform has an invalid rotation.")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    result = np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w), 0],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w), 0],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y), 0],
        [0, 0, 0, 1],
    ], dtype=float)
    scale = tree.get("m_LocalScale", {})
    result[:3, :3] @= np.diag([float(scale.get(a, 1)) for a in "xyz"])
    position = tree.get("m_LocalPosition", {})
    result[:3, 3] = [float(position.get(a, 0)) for a in "xyz"]
    if not np.isfinite(result).all():
        raise ModelViewerError("A model transform contains invalid numbers.")
    return result


class _Scene:
    def __init__(self, env, deadline, trees=None):
        self.env, self.deadline = env, deadline
        self.trees, self.transforms, self.world_cache = dict(trees or {}), {}, {}
        self.names = {}
        self.filters, self.renderers = {}, []
        self.warnings = []
        self.stats = {"meshes": 0, "vertices": 0, "triangles": 0, "materials": 0, "textures": 0}
        for obj in env.objects:
            typ = obj.type.name
            if typ not in ("Transform", "MeshFilter", "MeshRenderer", "SkinnedMeshRenderer"):
                continue
            _remaining(deadline)
            tree = self.tree(obj)
            game_object = _ref(obj, tree.get("m_GameObject"))
            if game_object is None:
                continue
            if typ == "Transform":
                self.transforms[_key(game_object)] = obj
            elif typ == "MeshFilter":
                self.filters[_key(game_object)] = _ref(obj, tree.get("m_Mesh"))
            else:
                self.renderers.append((obj, tree, game_object))
        if not self.renderers:
            # A standalone Mesh asset has no prefab hierarchy. Give its geometry
            # an identity placement; never resurrect hidden prefab meshes when
            # actual renderers exist in the supplied scene.
            self.renderers.extend((obj, {"m_Enabled": True, "m_Materials": []}, obj)
                                  for obj in env.objects if obj.type.name == "Mesh")
        from .model_board import board_positions
        self.runtime_positions = board_positions(self)

    def tree(self, obj):
        _remaining(self.deadline)
        key = _key(obj)
        if key not in self.trees:
            self.trees[key] = obj.read_typetree()
            _remaining(self.deadline)
        return self.trees[key]

    def name(self, obj):
        """Read only m_Name instead of expanding mesh/texture pixel payloads."""
        _remaining(self.deadline)
        key = _key(obj)
        if key not in self.names:
            if key in self.trees:
                value = self.trees[key].get("m_Name", "")
            else:
                value = obj.peek_name()
            self.names[key] = str(value or "")
            _remaining(self.deadline)
        return self.names[key]

    def local_tree(self, transform):
        """Runtime TRS view; tree() continues to expose immutable source values."""
        tree = self.tree(transform)
        position = self.runtime_positions.get(_key(transform))
        if position is None:
            return tree
        return dict(tree, m_LocalPosition=dict(zip("xyz", position)))

    def world(self, transform, visiting=None):
        import numpy as np
        if transform is None:
            return np.eye(4)
        key = _key(transform)
        if key in self.world_cache:
            return self.world_cache[key]
        visiting = set() if visiting is None else visiting
        if key in visiting or len(visiting) > 256:
            raise ModelViewerError("The model contains a circular transform hierarchy.")
        visiting.add(key)
        tree = self.local_tree(transform)
        parent = _ref(transform, tree.get("m_Father"))
        result = self.world(parent, visiting) @ _trs(tree)
        visiting.remove(key)
        self.world_cache[key] = result
        return result

    def active(self, game_object):
        seen = set()
        while game_object is not None:
            key = _key(game_object)
            if key in seen or len(seen) > 256:
                raise ModelViewerError("The model contains a circular transform hierarchy.")
            seen.add(key)
            if not self.tree(game_object).get("m_IsActive", True):
                return False
            transform = self.transforms.get(key)
            if transform is None:
                break
            parent = _ref(transform, self.tree(transform).get("m_Father"))
            game_object = _ref(parent, self.tree(parent).get("m_GameObject")) if parent else None
        return True

    def warn(self, code, name=""):
        messages = {
            "texture_unavailable": "Some textures could not be displayed. A neutral surface is shown instead.",
            "linked_texture_missing": "A linked texture is missing. Add its companion model file to the preview.",
            "linked_mesh_missing": "A linked mesh is missing. Add its companion model file to the preview.",
            "facial_assets_missing": "This costume needs its separate facial asset to show eyes and expressions.",
            "skin_bones_unavailable": "Some bone transforms are unavailable. Those parts use their saved renderer placement.",
            "skin_zero_weight_vertices": "Some vertices have no bone weights and use their saved renderer placement.",
            "rig_unavailable": "This model uses a static preview because its rig could not be loaded.",
            "stage_hidden_transform": "An animated stage mesh starts at zero scale and is hidden in this preview.",
            "member_shadow_prefabs_unavailable": "The stage's member shadow prefabs could not be exported, so the "
                                                 "performers draw no shadows in this preview.",
        }
        warning = {"code": code, "name": str(name)[:160], "message": messages.get(code, code)}
        if warning not in self.warnings:
            self.warnings.append(warning)


class _Glb:
    def __init__(self):
        self.data = bytearray()
        self.doc = {"asset": {"version": "2.0", "generator": "Elichika model viewer"},
                    "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                    "materials": [], "accessors": [], "bufferViews": [],
                    "images": [], "textures": [], "samplers": [], "buffers": [{}]}

    def view(self, data, target=None):
        self.data.extend(b"\0" * (-len(self.data) % 4))
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        if len(self.data) + len(data) > MAX_GLB_BYTES:
            raise ModelViewerError("This preview is too large. Open fewer model parts.")
        self.data.extend(data)
        index = len(self.doc["bufferViews"])
        self.doc["bufferViews"].append(view)
        return index

    def attribute(self, values, kind, component=5126, bounds=False, target="auto"):
        import numpy as np
        dtype = {5126: "<f4", 5123: "<u2", 5125: "<u4"}[component]
        array = np.ascontiguousarray(values, dtype=dtype)
        if component == 5126 and not np.isfinite(array).all():
            raise ModelViewerError("The model contains invalid geometry values.")
        view_target = (34963 if kind == "SCALAR" else 34962) if target == "auto" else target
        item = {"bufferView": self.view(array.tobytes(), view_target),
                "componentType": component, "count": len(array), "type": kind}
        if bounds:
            item["min"], item["max"] = array.min(axis=0).tolist(), array.max(axis=0).tolist()
        index = len(self.doc["accessors"])
        self.doc["accessors"].append(item)
        return index

    def finish(self):
        self.data.extend(b"\0" * (-len(self.data) % 4))
        self.doc["buffers"][0]["byteLength"] = len(self.data)
        doc = dict(self.doc)
        for optional in ("images", "textures", "samplers", "skins", "animations"):
            if not doc.get(optional):
                doc.pop(optional, None)
        encoded = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        encoded += b" " * (-len(encoded) % 4)
        length = 12 + 8 + len(encoded) + 8 + len(self.data)
        if length > MAX_GLB_BYTES:
            raise ModelViewerError("This preview is too large. Open fewer model parts.")
        return (struct.pack("<4sII", b"glTF", 2, length)
                + struct.pack("<I4s", len(encoded), b"JSON") + encoded
                + struct.pack("<I4s", len(self.data), b"BIN\0") + self.data)


def _properties(tree, name):
    return dict(tree.get("m_SavedProperties", {}).get(name, []))


_NATIVE_MEMBER_SHADER = ("cab-9382ea964987eceddd567506a3b21312", 8291131735116688333)


def _as_member_material(scene, obj, tree):
    """Identify the known SIFAS shader before ignoring its unused _Color."""
    if obj is None:
        return False
    pointer = tree.get("m_Shader") or {}
    shader = _ref(obj, pointer)
    if shader is not None:
        if shader.type.name != "Shader":
            return False
        shader_tree = scene.tree(shader)
        name = shader_tree.get("m_Name") or shader_tree.get("m_ParsedForm", {}).get("m_Name")
        return name in ("AS/Member", "Hidden/AS/Member/Main")
    # A source bundle may also depend on the transparent ground-shadow shader.
    # Require the AS/Member property fingerprint as well as its exact dependency;
    # a dependency alone must not change unrelated or generic materials.
    if not pointer.get("m_PathID") or int(pointer.get("m_FileID", 0)) <= 0:
        return False
    try:
        external = obj.assets_file.externals[int(pointer["m_FileID"]) - 1]
        identity = (ntpath.basename(external.name).lower(), int(pointer["m_PathID"]))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False
    # This reference is independently verified against the original AS/Member
    # shader and the actual iOS mod/Android assets. A dependency or stale saved
    # properties alone cannot establish which shader an external PPtr uses.
    if identity != _NATIVE_MEMBER_SHADER:
        return False
    if not {"_TintColor", "_AmbientColor", "_RimlightColor"} <= set(_properties(tree, "m_Colors")):
        return False
    source = _source_path(obj)
    for candidate in scene.env.objects:
        if candidate.type.name == "AssetBundle" and _source_path(candidate) == source:
            if "asmember.shader.unity3d" in scene.tree(candidate).get("m_Dependencies", []):
                return True
    return False


# Original SIFAS AS/* shaders that tint with _TintColor and declare no _Color
# (shader bundle serialized file, path ID). Each declares _TintColor with the
# ShaderLab default (1, 1, 1, 1) in m_ParsedForm.m_PropInfo.
_AS_TINT_SHADERS = {
    ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367): "AS/General/Opaque",
    ("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267): "AS/General/Transparent",
    ("cab-6cf8387efa4151b6220fceb9384d0e8e", 7983779172275908372): "AS/Rimlight/Opaque",
    ("cab-31fad648db7286e0012ae8cc07024bff", -1043432931367049882): "AS/Color/Opaque",
    ("cab-da18667fd7e5e991d56b5d877869e6c6", 7366096703533297961): "AS/Coloring/Transparent",
    ("cab-a44cd34f6481b592fc0475c6e5d23bfa", 9060382612279247893): "AS/FlashLight",
    ("cab-fc0511ca63f2d94bbfe211260d08ddd1", -6509019661097744245): "AS/Stage",
    ("cab-4004e36071ab5261ebac9281e0eccd75", 3926475870365283136): "AS/Penlight",
    ("cab-f8a6d724e5bbefa191ed2e1f27102738", -3111404110691668338): "AS/Blend/Opaque",
}
# Only these verified shaders tint, loaded or not: other AS/* shaders that
# declare _TintColor without _Color (AS/MatCap/*, AS/Member) are not checked.
_AS_TINT_NAMES = frozenset(_AS_TINT_SHADERS.values())
_WHITE = {"r": 1., "g": 1., "b": 1., "a": 1.}


def _as_blend_material(obj, tree):
    """Whether a material uses AS/Blend/Opaque (by ShaderLab name, or its verified shared identity)."""
    from .mv_studio_shader_identity import name

    try:
        return obj is not None and name(obj, tree) == "AS/Blend/Opaque"
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _as_tint_default(scene, obj, tree):
    """ShaderLab default _TintColor of a verified AS/* shader whose tint is _TintColor; None otherwise."""
    if obj is None:
        return None
    pointer = tree.get("m_Shader") or {}
    shader = _ref(obj, pointer)
    if shader is not None:
        if shader.type.name != "Shader":
            return None
        form = scene.tree(shader).get("m_ParsedForm") or {}
        props = {item.get("m_Name"): item for item in (form.get("m_PropInfo") or {}).get("m_Props", [])
                 if isinstance(item, dict)}
        tint, name = props.get("_TintColor"), form.get("m_Name")
        if not isinstance(name, str) or name not in _AS_TINT_NAMES or "_Color" in props or not tint or tint.get("m_Type") != 0:
            return None
        default = {axis: tint.get(f"m_DefValue[{index}]", 1.) for index, axis in enumerate("rgba")}
        return default if all(type(value) in (int, float) for value in default.values()) else None
    # The stage preview loads no shader bundles: match the verified external identity.
    try:
        file_id = int(pointer.get("m_FileID", 0))
        external = obj.assets_file.externals[file_id - 1] if file_id > 0 else None
        identity = (ntpath.basename(external.name).lower(), int(pointer["m_PathID"])) if external else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None
    return dict(_WHITE) if identity in _AS_TINT_SHADERS else None


def _member_depth_material(scene, material):
    """Admit the exact opaque wrapper that imports the member depth pass."""
    if material.type.name != "Material":
        return None
    tree = scene.tree(material)
    pointer = tree.get("m_Shader") or {}
    file_id = pointer.get("m_FileID")
    externals = material.assets_file.externals
    if type(file_id) is not int or not 0 <= file_id <= len(externals):
        return None
    file_name = externals[file_id - 1].name if file_id else material.assets_file.name
    if (ntpath.basename(file_name).casefold(), pointer.get("m_PathID")) != _NATIVE_MEMBER_SHADER:
        return None
    queue = tree.get("m_CustomRenderQueue", -1)
    if (type(queue) is not int or not -1 <= queue <= 2500 or tree.get("disabledShaderPasses")
            or tree.get("stringTagMap")):
        return None
    return {"kind": "member", "queue": 1900 if queue == -1 else queue}


def _member_depth_vertices(mesh, raw, quality):
    """Check that the GLB preserves the native member pass's posed inputs."""
    import numpy as np

    # Auto uses the player's two-weight setting. Fixed limits are serialized
    # on the renderer. The preview and live pose must use the same weights.
    limit = {0: 2, 1: 1, 2: 2, 4: 4}.get(quality)
    weights = np.asarray(raw["weights"])
    if (limit is None or weights.ndim != 2 or (np.count_nonzero(weights, axis=1) > limit).any()
            or getattr(mesh.m_Shapes, "channels", ())):
        return False
    return _member_depth_color(mesh, raw)


def _member_depth_color(mesh, raw):
    import numpy as np

    channels = getattr(mesh.m_VertexData, "m_Channels", ())
    if len(channels) < 4 or channels[3].dimension != 4:
        return False
    colors = np.asarray(raw["colors"])
    if colors.dtype.kind not in "iuf" or colors.ndim != 2 or colors.shape[1] != 4 or not colors.size:
        return False
    # RigBuilder converts emitted byte colors to normalized floats. A byte
    # stream containing only 0 and 1 cannot use its range-based conversion.
    if channels[3].format == 2:
        return colors.min() >= 0 and 1 < colors.max() <= 255
    return channels[3].format == 0 and colors.min() >= 0 and colors.max() <= 1


def _member_face_depth_vertices(raw, tree):
    """Verify source rigid geometry and complete position and normal morphs."""
    mesh = raw["mesh"]
    if (tree.get("m_Bones") or (tree.get("m_RootBone") or {}).get("m_PathID")
            or mesh.m_BindPose or raw["indices"] is not None or raw["weights"] is not None
            or not raw["authored_normals"] or any(tree.get("m_BlendShapeWeights", ()))
            or not _member_depth_color(mesh, raw)):
        return False
    shapes = mesh.m_Shapes
    channels = getattr(shapes, "channels", ())
    if not channels:
        return True
    if len(channels) != len(shapes.shapes) or len(channels) != len(shapes.fullWeights):
        return False
    for channel_index, channel in enumerate(channels):
        if (channel.frameCount != 1 or channel.frameIndex != channel_index
                or shapes.fullWeights[channel_index] != 100 or not shapes.shapes[channel_index].hasNormals):
            return False
    return True


def _member_face_depth_binding(raw, tree, role):
    import numpy as np

    if role == "merge":
        return _member_face_depth_vertices(raw, tree)
    colors = np.asarray(raw["colors"])
    if role == "line":
        return (_member_face_depth_vertices(raw, tree) and len(getattr(raw["mesh"].m_Shapes, "channels", ())) == 3
                and np.all(colors == [0, 255, 255, 255]))
    mesh = raw["mesh"]
    weights, indices = np.asarray(raw["weights"]), np.asarray(raw["indices"])
    if (not raw["authored_normals"] or not _member_depth_vertices(mesh, raw, tree.get("m_Quality"))
            or len(mesh.m_BindPose) != 9 or indices.shape != weights.shape
            or not np.all(colors == 255) or not np.all((weights == 0) | (weights == 1))
            or not np.all(weights.sum(axis=1) == 1)):
        return False
    return set(indices[weights == 1]) == {5, 8}


def _png_texture(image, deadline):
    """Encode unchanged RGBA pixels with fixed SUB filtering in 64-row strips."""
    _remaining(deadline)
    with io.BytesIO() as output:
        # Native ASTC output inherits these TGA controls through convert/flip;
        # Pillow's PNG writer ignores them. Preserve its behavior for every
        # other mode or metadata item, including color/transparency metadata.
        if image.mode != "RGBA" or set(image.info) - {"orientation", "compression", "id_section"}:
            image.save(output, format="PNG", compress_level=1)
            _remaining(deadline)
            return output.getvalue()

        import numpy as np

        def chunk(kind, data):
            output.write(struct.pack(">I", len(data)))
            output.write(kind)
            output.write(data)
            output.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff))

        width, height = image.size
        output.write(b"\x89PNG\r\n\x1a\n")
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        compressor = zlib.compressobj(level=1, strategy=zlib.Z_RLE)
        for top in range(0, height, 64):
            _remaining(deadline)
            rows = min(64, height - top)
            with image.crop((0, top, width, top + rows)) as strip:
                raw = strip.tobytes()
            source = np.frombuffer(raw, dtype=np.uint8).reshape(rows, width * 4)
            filtered = np.empty((rows, width * 4 + 1), dtype=np.uint8)
            filtered[:, 0] = 1  # SUB: bytes relative to the previous pixel.
            filtered[:, 1:5] = source[:, :4]
            np.subtract(source[:, 4:], source[:, :-4], out=filtered[:, 5:])
            data = compressor.compress(memoryview(filtered).cast("B"))
            if data:
                chunk(b"IDAT", data)
            del source, raw, filtered, data
        _remaining(deadline)
        data = compressor.flush()
        _remaining(deadline)
        if data:
            chunk(b"IDAT", data)
        chunk(b"IEND", b"")
        _remaining(deadline)
        return output.getvalue()


def _texture_png(texture, deadline, *, stage=False):
    """Decode original texture bytes once, including across ZIP temp paths.

    Source hashes belong to the actual encoded pixels, not file timestamps or
    mutable preview objects. Material/sampler metadata is rebuilt each time.
    Reimport bypasses reads and replaces successful entries with fresh results.
    """
    _remaining(deadline)
    width, height = texture.m_Width, texture.m_Height
    stream = getattr(texture, "m_StreamData", None)
    inline = getattr(texture, "image_data", b"") or b""
    reader = getattr(texture, "object_reader", None)
    platform = getattr(reader, "platform", None)
    blob = getattr(texture, "m_PlatformBlob", None)
    stage_format = False
    try:
        from UnityPy.enums import TextureFormat
        name = TextureFormat(texture.m_TextureFormat).name
        stage_format = stage and name in decode._STAGE_BLOCK_FORMATS
        supported = (name in decode._RAW_FORMATS or name == "ETC2_RGBA8Crunched"
                     or stage_format or bool(re.fullmatch(r"ASTC_(?:RGB|RGBA)_(4|5|6|8|10|12)x\1", name)))
    except (AttributeError, TypeError, ValueError):
        supported = False
    bounded = (callable(getattr(texture, "get_image_data", None))
               and isinstance(getattr(texture, "m_TextureFormat", None), int)
               and supported and getattr(texture, "m_ImageCount", 1) == 1
               and getattr(texture, "m_TextureDimension", 2) == 2
               and platform != 11 and not (platform == 38 and blob)
               and isinstance(width, int) and not isinstance(width, bool)
               and isinstance(height, int) and not isinstance(height, bool)
               and 0 < width <= decode._MAX_DIMENSION and 0 < height <= decode._MAX_DIMENSION
               and width * height <= decode._MAX_PIXELS
               and getattr(stream, "size", 0) <= decode._MAX_SOURCE_BYTES
               and len(inline) <= decode._MAX_SOURCE_BYTES)
    if not bounded:
        # The decoder supplies the existing detailed validation error without
        # reading an oversized external stream just to construct a cache key.
        image = decode._android_image(texture, deadline, **({"stage": True} if stage_format else {}))
        try:
            return _png_texture(image, deadline)
        finally:
            image.close()
    profile = decode._texture65_profile(texture) if name == "ETC2_RGBA8Crunched" else None
    data = texture.get_image_data()
    if len(data) > decode._MAX_SOURCE_BYTES:
        raise ValueError("Texture data exceeds the preview limit")
    binary = os.environ.get("ELICHIKA_TEXTURE65_BIN" if name == "ETC2_RGBA8Crunched" or stage_format else "ASTCENC_BIN", "")
    try:
        stat = os.stat(binary)
        decoder = (os.path.realpath(binary), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError:
        decoder = None
    key = (width, height, int(texture.m_TextureFormat), getattr(texture, "m_ImageCount", 1),
           getattr(texture, "m_TextureDimension", 2), platform,
           bool(blob), hashlib.sha256(data).digest(), decoder, id(decode._android_image), id(_png_texture))
    if profile is not None:
        key += (profile,)
    png = _conversion_get(_TEXTURE_PNGS, key, deadline)
    if png is not None:
        return png

    class TextureBytes:
        def __getattr__(self, name):
            return getattr(texture, name)

        def get_image_data(self):
            return data

    image = decode._android_image(TextureBytes(), deadline, **({"stage": True} if stage_format else {}))
    try:
        png = _png_texture(image, deadline)
    finally:
        image.close()
    _conversion_put(_TEXTURE_PNGS, key, png,
                    max_bytes=MAX_TEXTURE_CACHE_BYTES, max_entries=MAX_TEXTURE_CACHE_ENTRIES)
    return png


class _Materials:
    def __init__(self, scene, glb, rigged=False):
        self.scene, self.glb = scene, glb
        self.rigged = rigged
        self.materials, self.textures = {}, {}
        self.predecoded = {}
        self.pixels = 0
        self.source_indices, self.source_files = {}, {}
        self.stage_texture_samplers = {}

    def mip_textures(self, objects):
        """Decode at most two immutable mip slices concurrently; append in order.

        Unity ObjectReaders and GLB state stay on the conversion thread. These
        generated slice proxies already contain bounded, independent byte data.
        """
        if len(objects) <= 1:
            return [self.texture(obj) for obj in objects]
        if len(objects) > 12:
            raise ModelViewerError("The authored mip chain exceeds the preview limits.")
        from concurrent.futures import ThreadPoolExecutor
        remaining, pending = MAX_TEXTURE_PIXELS - self.pixels, []
        for obj in objects:
            key = _key(obj)
            if key in self.textures:
                continue
            texture = obj.read()
            pixels = int(texture.m_Width) * int(texture.m_Height)
            remaining -= pixels
            if pixels < 1 or remaining < 0:
                self.predecoded[key] = ModelViewerError("The model textures exceed the preview memory limit.")
            else:
                pending.append((key, texture))
        reimport = getattr(_REQUEST_STATE, "reimport", False)

        def convert(texture):
            previous = getattr(_REQUEST_STATE, "reimport", False)
            _REQUEST_STATE.reimport = reimport
            try:
                if getattr(self.scene, "preview_stage", False):
                    return _texture_png(texture, self.scene.deadline, stage=True)
                return _texture_png(texture, self.scene.deadline)
            finally:
                _REQUEST_STATE.reimport = previous

        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="viewer-mip") as pool:
                futures = [(key, pool.submit(convert, texture)) for key, texture in pending]
                for key, future in futures:
                    try:
                        self.predecoded[key] = future.result()
                    except Exception as error:
                        self.predecoded[key] = error
            return [self.texture(obj) for obj in objects]
        finally:
            for obj in objects:
                self.predecoded.pop(_key(obj), None)

    def texture(self, obj):
        key = _key(obj)
        if key in self.textures:
            if self.textures[key] is None:
                raise ValueError("This texture format could not be previewed.")
            return self.textures[key]
        self.textures[key] = None
        texture = obj.read()
        pixels = int(texture.m_Width) * int(texture.m_Height)
        if pixels < 1 or self.pixels + pixels > MAX_TEXTURE_PIXELS:
            raise ModelViewerError("The model textures exceed the preview memory limit.")
        self.pixels += pixels
        png = self.predecoded.pop(key, None)
        if isinstance(png, Exception):
            raise png
        if png is None:
            if getattr(self.scene, "preview_stage", False):
                png = _texture_png(texture, self.scene.deadline, stage=True)
            else:
                png = _texture_png(texture, self.scene.deadline)
        settings = getattr(texture, "m_TextureSettings", None)
        wrapping = {0: 10497, 1: 33071, 2: 33648, 3: 33071}
        index = self.embed_texture(png, str(texture.m_Name),
                                   wrapping.get(getattr(settings, "m_WrapU", 0), 10497),
                                   wrapping.get(getattr(settings, "m_WrapV", 0), 10497))
        source = _source_path(obj)
        source_index = self.source_indices.get(source)
        file_index = self.source_files.get(source, {}).get(id(obj.assets_file))
        if source_index is not None and file_index is not None:
            self.glb.doc["textures"][index]["extras"] = {"viewerTexture": {
                "source": source_index, "file": file_index, "id": str(obj.path_id)}}
        self.textures[key] = index
        return index

    def embed_texture(self, png, name, wrap_s=10497, wrap_t=10497):
        image_index = len(self.glb.doc["images"])
        self.glb.doc["images"].append({"bufferView": self.glb.view(png), "mimeType": "image/png", "name": name})
        sampler_index = len(self.glb.doc["samplers"])
        self.glb.doc["samplers"].append({"magFilter": 9729, "minFilter": 9729, "wrapS": wrap_s, "wrapT": wrap_t})
        index = len(self.glb.doc["textures"])
        self.glb.doc["textures"].append({"source": image_index, "sampler": sampler_index})
        self.scene.stats["textures"] += 1
        return index

    def material(self, obj):
        key = _key(obj) if obj is not None else None
        if key in self.materials:
            return self.materials[key]
        tree = self.scene.tree(obj) if obj is not None else {}
        if obj is not None and getattr(self.scene, "member_attach", None) is not None:
            obj, tree = self.scene.member_attach.material(self.scene, obj, tree)  # suit attach data
        colors = _properties(tree, "m_Colors")
        # AS/Member never consumes _Color; carrying stale Unity generic shader
        # values into glTF incorrectly darkens real outfit heads. Lighting/tint
        # shader parity remains outside this unlit texture preview.
        color = ({"r": 1, "g": 1, "b": 1, "a": 1} if _as_member_material(self.scene, obj, tree)
                 else colors.get("_Color"))
        if color is None:
            # AS/* stage shaders tint with _TintColor (ShaderLab default white), never a generic grey.
            tint = _as_tint_default(self.scene, obj, tree)
            color = colors.get("_TintColor", tint) if tint is not None else {"r": .72, "g": .74, "b": .78, "a": 1}
        factor = [float(color.get(a, 1)) for a in "rgba"]
        if not all(math.isfinite(v) for v in factor):
            raise ModelViewerError("A model material contains invalid colors.")
        factor = [min(1., max(0., value)) for value in factor]
        floats = _properties(tree, "m_Floats")
        material = {"name": str(tree.get("m_Name") or "Model surface"),
                    "pbrMetallicRoughness": {"baseColorFactor": factor, "metallicFactor": 0,
                                             "roughnessFactor": 1},
                    "doubleSided": floats.get("_CullMode", 2) == 0}
        mode, keywords = floats.get("_Mode", 0), str(tree.get("m_ShaderKeywords", ""))
        if mode == 1 or "_ALPHATEST_ON" in keywords:
            material.update(alphaMode="MASK", alphaCutoff=min(1., max(0., float(floats.get("_Cutoff", .5)))))
        elif mode in (2, 3) or "_ALPHABLEND_ON" in keywords or "_ALPHAPREMULTIPLY_ON" in keywords:
            material["alphaMode"] = "BLEND"
        envs = _properties(tree, "m_TexEnvs")
        main = envs.get("_MainTex") or envs.get("_BaseMap")
        if main is None and "_MainTexA" in envs and _as_blend_material(obj, tree):
            # AS/Blend/Opaque draws _MainTexA at its default _BlendRate 0; the
            # MV stage material evaluates both maps (mv_studio_stage_materials).
            main = envs["_MainTexA"]
        texture = _ref(obj, main.get("m_Texture")) if obj is not None and main else None
        if texture is not None and texture.type.name == "Texture2D":
            try:
                tex = {"index": self.texture(texture)}
                scale = [float(main.get("m_Scale", {}).get(a, 1)) for a in "xy"]
                offset = [float(main.get("m_Offset", {}).get(a, 0)) for a in "xy"]
                if not all(math.isfinite(v) for v in scale + offset):
                    raise ValueError("Invalid texture coordinates")
                if scale != [1., 1.] or offset != [0., 0.]:
                    tex["extensions"] = {"KHR_texture_transform": {
                        "scale": scale, "offset": [offset[0], 1 - scale[1] - offset[1]],
                    }}
                    self._extension("KHR_texture_transform")
                material["pbrMetallicRoughness"]["baseColorTexture"] = tex
                material["extensions"] = {"KHR_materials_unlit": {}}
                self._extension("KHR_materials_unlit")
            except Exception as error:
                if isinstance(error, ModelViewerError):
                    raise
                self.scene.warn("texture_unavailable", tree.get("m_Name", ""))
        elif main and main.get("m_Texture", {}).get("m_PathID"):
            self.scene.warn("linked_texture_missing", tree.get("m_Name", ""))
        if self.rigged and _as_member_material(self.scene, obj, tree):
            from .model_materials import attach_member_metadata
            attach_member_metadata(self.scene, obj, tree, material, self.texture, mip_resolver=self.mip_textures)
        index = len(self.glb.doc["materials"])
        self.glb.doc["materials"].append(material)
        self.materials[key] = index
        self.scene.stats["materials"] += 1
        return index

    def _extension(self, name):
        extensions = self.glb.doc.setdefault("extensionsUsed", [])
        if name not in extensions:
            extensions.append(name)


def _validate_mesh_allocations(mesh):
    """Check declared counts before MeshHandler expands packed data to lists."""
    vertex_data = getattr(mesh, "m_VertexData", None)
    count = int(getattr(vertex_data, "m_VertexCount", 0) or 0)
    compressed = getattr(mesh, "m_CompressedMesh", None)
    packed_vertices = int(getattr(getattr(compressed, "m_Vertices", None), "m_NumItems", 0) or 0)
    if count < 0 or packed_vertices < 0 or max(count, (packed_vertices + 2) // 3) > MAX_VERTICES:
        raise ModelViewerError("The model has too many vertices for the mobile viewer.")
    packed_indices = int(getattr(getattr(compressed, "m_Triangles", None), "m_NumItems", 0) or 0)
    if packed_indices < 0 or packed_indices > MAX_TRIANGLES * 3:
        raise ModelViewerError("The model has too many triangles for the mobile viewer.")
    vertices = max(count, (packed_vertices + 2) // 3)
    for name, components in (("m_UV", 32), ("m_Normals", 2), ("m_Tangents", 2),
                             ("m_Weights", 4), ("m_NormalSigns", 1), ("m_TangentSigns", 2),
                             ("m_FloatColors", 4), ("m_Colors", 4), ("m_BoneIndices", 4)):
        packed = getattr(compressed, name, None)
        number = int(getattr(packed, "m_NumItems", 0) or 0)
        if number < 0 or number > vertices * components:
            raise ModelViewerError("The model has oversized compressed vertex data.")
    index_format = getattr(mesh, "m_IndexFormat", 0)
    if index_format not in (None, 0, 1):
        raise ModelViewerError("The model has an unsupported index format.")
    use_16 = getattr(mesh, "m_Use16BitIndices", None)
    size = 2 if (use_16 if use_16 is not None else index_format != 1) else 4
    raw = getattr(mesh, "m_IndexBuffer", None) or b""
    if len(raw) % size or len(raw) > MAX_TRIANGLES * 3 * size:
        raise ModelViewerError("The model has too many or invalid triangle indices.")
    available = max(len(raw) // size, packed_indices)
    parts = getattr(mesh, "m_SubMeshes", None) or []
    if len(parts) > MAX_MESHES:
        raise ModelViewerError("The model has too many submeshes for the mobile viewer.")
    triangles = 0
    for part in parts:
        first, number = int(part.firstByte), int(part.indexCount)
        topology = int(part.topology)
        if first < 0 or first % size or number < 0 or number > MAX_TRIANGLES * 3 \
                or first // size + number > available:
            raise ModelViewerError("A model submesh declares invalid triangle indices.")
        if topology == 0:
            if number % 3:
                raise ModelViewerError("A model submesh declares incomplete triangles.")
            triangles += number // 3
        elif topology == 1:
            triangles += max(0, number - 2)
        elif topology == 2:
            if number % 4:
                raise ModelViewerError("A model submesh declares incomplete quads.")
            triangles += number // 2
        else:
            raise ModelViewerError("Only triangle or quad model surfaces can be previewed.")
        if triangles > MAX_TRIANGLES:
            raise ModelViewerError("The model has too many triangles for the mobile viewer.")


def _geometry(mesh_obj, world, bone_world_matrices=None, warnings=None, rig_data=None, morph_weights=None, deadline=None,
              penlight_data=None, stage_data=None):
    import numpy as np
    from .model_mesh import PreviewMeshHandler

    mesh = mesh_obj.read()
    _validate_mesh_allocations(mesh)
    handler = PreviewMeshHandler(mesh)
    handler.process()
    positions = np.asarray(handler.m_Vertices, dtype=float)
    if positions.ndim != 2 or positions.shape[1] < 3 or not 0 < len(positions) <= MAX_VERTICES:
        raise ModelViewerError("The model does not contain supported vertex positions.")
    positions = positions[:, :3]
    triangles = handler.get_triangles()
    result = []
    for part, raw in zip(mesh.m_SubMeshes, triangles):
        indices = np.asarray(raw, dtype=np.int64)
        if indices.size == 0:
            result.append(np.empty((0, 3), dtype=np.int64))
            continue
        if indices.ndim != 2 or indices.shape[1] != 3:
            raise ModelViewerError("A model submesh contains invalid triangles.")
        indices += int(getattr(part, "baseVertex", 0) or 0)
        if indices.min() < 0 or indices.max() >= len(positions):
            raise ModelViewerError("A model triangle points outside its vertex data.")
        result.append(indices)
    if sum(map(len, result)) > MAX_TRIANGLES:
        raise ModelViewerError("The model has too many triangles for the mobile viewer.")
    if not np.isfinite(positions).all():
        raise ModelViewerError("The model contains invalid vertex positions.")
    normals = None
    if handler.m_Normals is not None:
        candidate = np.asarray(handler.m_Normals, dtype=float)
        if candidate.ndim == 2 and candidate.shape[0] == len(positions) and candidate.shape[1] >= 3:
            normals = candidate[:, :3]
    has_source_normals = normals is not None and np.isfinite(normals).all()
    if stage_data is not None and stage_data.get("needsAuthoredNormals"):
        stage_data["authoredNormals"] = has_source_normals and (np.abs(normals).max(axis=1) >= 1e-12).all()
    if not has_source_normals:
        normals = np.zeros_like(positions)
        for indices in result:
            if not len(indices):
                continue
            points = positions[indices]
            face_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
            for corner in range(3):
                np.add.at(normals, indices[:, corner], face_normals)
    if rig_data is not None:
        rig_data.update(mesh=mesh, positions=positions, normals=normals,
                        indices=handler.m_BoneIndices, weights=handler.m_BoneWeights,
                        colors=handler.m_Colors, authored_normals=has_source_normals)
    if penlight_data is not None:
        # AS/Penlight stores each billboard's pivot in UV1 and four random
        # inputs in COLOR0. Neither channel is a conventional UV or color.
        pivots = np.asarray(handler.m_UV1, dtype=np.float32)
        colors = np.asarray(handler.m_Colors, dtype=np.float32)
        if (pivots.shape == positions.shape and colors.shape == (len(positions), 4)
                and np.isfinite(pivots).all() and np.isfinite(colors).all()):
            penlight_data.update(_PENLIGHT_CENTER=pivots, _PENLIGHT_COLOR=colors,
                                 _PENLIGHT_CORNER=positions - pivots)
    if stage_data is not None:
        from .mv_studio_stage_materials import read_vertex_inputs
        read_vertex_inputs(handler, stage_data, len(positions))
        soft = stage_data.get("softBillboard")
        if soft:
            channels = getattr(mesh.m_VertexData, "m_Channels", ())
            required = {0: 3, 4: 2, **({3: 4, 5: 3} if soft == "fog" else {1: 3})}
            if all(index < len(channels) and (channels[index].format, channels[index].dimension) == (0, dimensions)
                   for index, dimensions in required.items()):
                if soft == "fog":
                    centers = np.asarray(handler.m_UV1, dtype=np.float32)
                    if (centers.shape == positions.shape and np.isfinite(centers).all()
                            and "color" in stage_data):
                        # The main mesh and pivot both mirror X. The shader reconstructs
                        # the unreflected camera-facing delta from those coordinates.
                        centers = centers.copy()
                        centers[:, 0] *= -1
                        stage_data["softCenter"] = centers
                elif len(channels) <= 3 or not channels[3].dimension or "color" in stage_data:
                    stage_data["smokeNormals"] = has_source_normals and (np.abs(normals).max(axis=1) >= 1e-12).all()
    if morph_weights:
        from .model_rig import apply_default_morphs
        positions, normals = apply_default_morphs(mesh, positions, normals, morph_weights, deadline=deadline)
    orientation = -1 if np.linalg.det(world[:3, :3]) < 0 else 1
    if bone_world_matrices is not None:
        from .model_skinning import rest_skin_mesh, SkinningError
        try:
            rest = rest_skin_mesh(positions, normals, handler.m_BoneIndices, handler.m_BoneWeights,
                                  bone_world_matrices, mesh.m_BindPose, world, max_vertices=MAX_VERTICES)
        except SkinningError as error:
            raise ModelViewerError(str(error)) from error
        positions, normals = rest["positions"], rest["normals"]
        orientation = rest["orientation_sign"]
        if warnings is not None:
            warnings.extend(rest["warnings"])
        # Skinning already produces Unity world coordinates. Applying the
        # renderer transform here again would move the edited body twice.
        world = np.eye(4)
    transform = np.diag([-1., 1., 1., 1.]) @ world
    positions = positions @ transform[:3, :3].T + transform[:3, 3]
    try:
        normals = normals @ np.linalg.inv(transform[:3, :3])
    except np.linalg.LinAlgError as error:
        raise ModelViewerError("The model contains a zero-scale transform.") from error
    lengths = np.linalg.norm(normals, axis=1)
    zero = lengths < 1e-12
    normals[zero] = [0, 1, 0]
    lengths[zero] = 1
    normals /= lengths[:, None]
    if orientation > 0:
        result = [indices[:, [0, 2, 1]] for indices in result]
    uv = None
    if handler.m_UV0 is not None:
        candidate = np.asarray(handler.m_UV0, dtype=float)
        if candidate.ndim == 2 and candidate.shape[0] == len(positions) and candidate.shape[1] >= 2 \
                and np.isfinite(candidate).all():
            uv = candidate[:, :2].copy()
            uv[:, 1] = 1 - uv[:, 1]
    return str(mesh.m_Name), positions, normals, uv, result


def _stage_audience_point(scene, component, tree):
    pointer = tree.get("audiencesPoint")
    script_pointer = tree.get("m_Script")
    if not isinstance(pointer, dict) or pointer.get("m_FileID", 0) or not isinstance(script_pointer, dict):
        return None
    script = _ref(component, script_pointer)
    if script is None or script.type.name != "MonoScript":
        return None
    script_tree = scene.tree(script)
    if (script_tree.get("m_ClassName"), script_tree.get("m_Namespace"), script_tree.get("m_AssemblyName")) != (
            "LiveCoreStageModel", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll"):
        return None
    game = _ref(component, pointer)
    if game is None or game.type.name != "GameObject":
        return None
    transform = scene.transforms.get(_key(game))
    if transform is None:
        return None
    # Static preview geometry is flattened in world space and mirrors Unity X.
    x, y, z = scene.world(transform)[:3, 3]
    return (-float(x), float(y), float(z)) if all(map(math.isfinite, (x, y, z))) else None


def _penlight_binding(scene, component, tree):
    pointers = tree.get("materials")
    if not tree.get("m_Enabled", True) or not isinstance(pointers, list) or not 0 < len(pointers) <= MAX_MESHES:
        return None
    script = _ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    script_tree = scene.tree(script)
    if (script_tree.get("m_ClassName"), script_tree.get("m_Namespace"), script_tree.get("m_AssemblyName")) != (
            "LiveCoreStagePenlight", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll"):
        return None
    game = _ref(component, tree.get("m_GameObject"))
    transform = scene.transforms.get(_key(game)) if game is not None else None
    if transform is None:
        return None

    names = []
    current = transform
    seen = set()
    while current is not None and len(names) < 32 and _key(current) not in seen:
        seen.add(_key(current))
        node = scene.tree(current)
        owner = _ref(current, node.get("m_GameObject"))
        name = scene.name(owner) if owner is not None else ""
        if not name or "/" in name:
            return None
        names.append(name)
        current = _ref(current, node.get("m_Father"))
    if current is not None or len(names) < 2:
        return None
    # The effect prefab is inserted under Stages/*/Effect by the game.
    # The prefab root name itself does not appear in the timeline binding.
    suffix = "/".join(reversed(names[:-1]))

    materials = set()
    for pointer in pointers:
        if not isinstance(pointer, dict):
            continue
        material = _ref(component, pointer)
        if material is not None and material.type.name == "Material":
            materials.add(_key(material))
    return (_key(game), materials, suffix) if materials else None


def _penlight_material(tree):
    floats = _properties(tree, "m_Floats")
    if "_SWING_MODE" not in floats:
        return None
    selected = {name: value for name, value in floats.items()
                if (name in {"_FogIntensity", "_RandomBrightness", "_SWING_MODE", "_BeatLength", "_BeatOffset",
                            "_RandomSwingIntensity", "_CullMode"}
                    or name.startswith(("_BasicYZ_", "_GrowthYZ_", "_BasicX_", "_SimpleXZ_")))}
    colors = _properties(tree, "m_Colors")
    vectors = {}
    for name in ("_TintColor", "_RandomDelay", "_RandomUp"):
        color = colors.get(name)
        if isinstance(color, dict) and set(color) == set("rgba"):
            vectors[name] = [color[axis] for axis in "rgba"]
    values = [*selected.values(), *(value for vector in vectors.values() for value in vector)]
    if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
        return None
    mode = next((keyword for keyword in str(tree.get("m_ShaderKeywords", "")).split()
                 if keyword in {"_SWING_MODE_STOP", "_SWING_MODE_BASIC_YZ", "_SWING_MODE_GROWTH_YZ",
                                "_SWING_MODE_BASIC_X", "_SWING_MODE_SIMPLE_XZ"}), None)
    return {"floats": selected, "vectors": vectors, "keyword": mode}


def _append_scene(scene, glb, faces, deadline, *, auto_only=False, materials=None, rig=None):
    # SIFAS downloads its facial prefab separately from the outfit. The base
    # Face mesh alone does not contain iris/mouth geometry. Do not invent it or
    # quietly tell users that a body-only file is a complete game character.
    from .model_faces import _names as facial_names, renderer_role
    # Explicitly selected native facial prefabs still need their semantic role
    # when automatic face discovery is disabled/already complete. Keep this
    # local: discovering a declaration must not accept a rejected donor.
    facial_sources = set(faces.dynamic_sources) | facial_names(scene)[1]
    # Saved costume/face graphs isolate Unity's CAB and AssetBundle names.
    # Their native prefab container paths remain unchanged. Recognize that
    # declaration locally without changing FacePlan's accepted-source state.
    native_face_prefab = re.compile(r"(?:^|/)characters/models/ch([0-9]{4})/ch\1_[^/]*_facedynamic\.prefab$", re.I)
    for source_object in scene.env.objects:
        if source_object.type.name != "AssetBundle" or _source_path(source_object) in facial_sources:
            continue
        _remaining(deadline)
        containers = scene.tree(source_object).get("m_Container", [])
        if any(isinstance(row, (list, tuple)) and row and isinstance(row[0], str)
               and native_face_prefab.search(row[0].replace("\\", "/")) for row in containers[:64]):
            facial_sources.add(_source_path(source_object))
    faces.bind_selected_materials(scene, facial_sources)
    if rig is not None and auto_only:
        for path in faces.auto_paths:
            if path not in rig.source_indices:
                rig.source_indices[path] = len(rig.source_indices)
    penlights, audience_points, detached_templates, shaft_sources, area_sources = {}, set(), set(), [], []
    stage_materials = getattr(scene, "preview_stage", False) and not auto_only and rig is None
    member_depth = faces.context.get("_mv_performer") is True and rig is not None and not auto_only
    face_depth_bindings = {}
    if member_depth:
        face_depth_bindings, rig.face_mounts = faces.native_merge_bindings(scene, rig.selected, facial_sources)
    stage_nodes = None
    if stage_materials and getattr(scene, "stage_motion_bindings", ()):
        from .mv_studio_stage_nodes import StageNodes

        stage_nodes = StageNodes(scene, glb, scene.stage_motion_bindings)
    # Native stage effects retain dormant renderers driven by authored animation.
    animated_effect = stage_nodes is not None and stage_nodes.roots and getattr(scene, "native_stage_effect", False)
    mesh_limit = MAX_NATIVE_STAGE_EFFECT_MESHES if animated_effect else MAX_MESHES
    if stage_materials:
        from . import mv_studio_shaft, mv_studio_spotlight_area, mv_studio_stage_coloring, mv_studio_stage_display
        from . import mv_studio_stage_beam, mv_studio_stage_flash, mv_studio_stage_materials, mv_studio_stage_overlay
        from . import mv_studio_axis_billboard, mv_studio_soft_billboards, mv_studio_stage_props, unity_builtin_meshes
        from . import mv_studio_lossy_scale
        ambient_materials, lightmap_settings, stage_metadata, stage_cubes = {}, {}, {}, {}
        single_ambient, stage_emissive, stage_cubemap_owners = {}, set(), []
        stage_coloring, stage_palettes, stage_displays = {}, {}, {}
        stage_flashes = {}
        axis_billboards, stage_props, lossy_scales = set(), [], {}
    shadow_stages = shadow_prefabs = None
    if stage_materials and getattr(scene, "native_stage_effect", False):
        from . import mv_studio_member_shadow

        shadow_stages = []
    for obj in scene.env.objects:
        if auto_only and _source_path(obj) not in faces.auto_paths:
            continue
        if stage_materials and obj.type.name == "LightmapSettings":
            lightmap_settings[id(obj.assets_file)] = obj
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = scene.tree(obj)
        except Exception:
            continue
        if getattr(scene, "preview_stage", False) and not auto_only:
            try:
                point = _stage_audience_point(scene, obj, tree)
            except ValueError:
                point = None  # An invalid optional locator must not hide the stage.
            if point is not None:
                audience_points.add(point)
            binding = _penlight_binding(scene, obj, tree)
            if binding is not None:
                owner, linked_materials, suffix = binding
                penlights[owner] = linked_materials, suffix
        if shadow_stages is not None:
            defaults = mv_studio_member_shadow.stage_default(scene, obj, tree)
            if defaults is not None:
                shadow_stages.append(defaults)
                shadow_prefabs = mv_studio_member_shadow.stage_prefabs(scene, obj, tree)
                # The prefab assets are only instantiated under the members.
                detached_templates.update(_key(game) for game in shadow_prefabs or () if game is not None)
        if stage_materials:
            excluded, shaft_source = mv_studio_shaft.references(scene, obj, tree)
            detached_templates.update(excluded)
            if shaft_source is not None:
                shaft_sources.append(shaft_source)
            area = mv_studio_spotlight_area.reference(scene, obj, tree)
            if area is not None:
                detached_templates.add(_key(area[0]))
                area_sources.append(area)
            defaults, ambient_binding = mv_studio_stage_materials.ambient_materials(scene, obj, tree)
            ambient_materials.update(defaults)
            try:
                stage_emissive.update(mv_studio_stage_materials.emissive_materials(scene, obj, tree))
            except (TypeError, ValueError, KeyError, EOFError, struct.error):
                pass
            try:
                is_model, cubemap_owner = mv_studio_stage_materials.cubemap_model_ownership(scene, obj, tree)
                if is_model:
                    stage_cubemap_owners.append(cubemap_owner)
            except (TypeError, ValueError, KeyError, EOFError, struct.error):
                stage_cubemap_owners.append(None)
            if ambient_binding:
                for identity in defaults:
                    single_ambient[identity] = None if identity in single_ambient else ambient_binding
            coloring = mv_studio_stage_coloring.binding(scene, obj, tree)
            if coloring is not None:
                identity, entry = coloring
                stage_coloring.setdefault(identity, []).append(entry)
            display = mv_studio_stage_display.binding(scene, obj, tree)
            if display is not None:
                identity, entry = display
                stage_displays[identity] = None if identity in stage_displays else entry
            flash = mv_studio_stage_flash.binding(scene, obj, tree)
            if flash is not None:
                identity, entry = flash
                stage_flashes[identity] = None if identity in stage_flashes else entry
            axis_billboards.update(mv_studio_axis_billboard.owners(scene, obj, tree))
            for key, values in mv_studio_lossy_scale.offsets(scene, obj, tree).items():
                lossy_scales[key] = None if key in lossy_scales else values
            stage_props.extend(mv_studio_stage_props.props(scene, obj, tree))
        face = tree.get("face")
        if isinstance(face, dict) and face.get("m_PathID") and _ref(obj, face) is None:
            scene.warn("facial_assets_missing")
    if len(audience_points) == 1:
        glb.doc["scenes"][0].setdefault("extras", {})["mvAudiencePoint"] = next(iter(audience_points))
    if shadow_stages is not None and len(shadow_stages) == 1:
        glb.doc["scenes"][0].setdefault("extras", {})["mvMemberShadowDefaults"] = shadow_stages[0]
    cubemap_owner = stage_cubemap_owners[0] if stage_materials and len(stage_cubemap_owners) == 1 else None
    materials = materials or _Materials(scene, glb, rigged=rig is not None)
    materials.scene = scene
    if shadow_stages == [False] and shadow_prefabs:
        exported = mv_studio_member_shadow.export_prefabs(scene, glb, materials, shadow_prefabs, deadline)
        if exported is not None:
            glb.doc["scenes"][0].setdefault("extras", {})["mvMemberShadowPrefabs"] = exported
        else:
            # The game deletes the costume shadows for these prefabs, so nothing stands in for them.
            scene.warn("member_shadow_prefabs_unavailable")
    if animated_effect:
        from . import mv_studio_stage_laser_cores, mv_studio_stationary_bursts

        cores = mv_studio_stage_laser_cores.read(scene, stage_nodes, deadline)
        if cores is not None:
            fields, mips = cores
            pixels = sum((512 >> level) ** 2 for level in range(len(mips)))
            if materials.pixels + pixels <= MAX_TEXTURE_PIXELS:
                materials.pixels += pixels
                fields["texture"] = [materials.embed_texture(png, f"tex_par_gen_17 mip {level}")
                                     for level, png in enumerate(mips)]
                glb.doc["scenes"][0].setdefault("extras", {})["mvStageLaserCores"] = fields
        bound_cores = mv_studio_stage_laser_cores.read_bound(scene, stage_nodes, materials, deadline)
        if bound_cores:
            glb.doc["scenes"][0].setdefault("extras", {})["mvStageResidentCores"] = bound_cores
        bursts = mv_studio_stationary_bursts.read_bound(scene, stage_nodes, materials, deadline)
        if bursts:
            glb.doc["scenes"][0].setdefault("extras", {})["mvStageStationaryBursts"] = bursts
    if len(shaft_sources) == 1:
        retained = mv_studio_shaft.export(scene, glb, materials, shaft_sources[0], deadline)
        if retained:
            glb.doc["scenes"][0].setdefault("extras", {})["mvShaftTemplates"] = retained
    if len(area_sources) == 1:
        try:
            area = mv_studio_spotlight_area.export(scene, glb, materials, area_sources[0], deadline)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError):
            area = None
        if area is not None:
            glb.doc["scenes"][0].setdefault("extras", {})["mvSpotlightArea"] = area
    # Match the serialized-file ordinals used by the editor's _inspect(raw).
    # A CAB's ordinal belongs to its selected input, not the combined scene.
    source_files = {}
    for source_object in scene.env.objects:
        files = source_files.setdefault(_source_path(source_object), {})
        files.setdefault(id(source_object.assets_file), len(files))
    materials.source_indices = rig.source_indices if rig is not None else {}
    materials.source_files = source_files
    for renderer, tree, game_object in scene.renderers:
        if rig is not None and _source_path(renderer) in getattr(rig, "motion_sources", set()):
            continue
        if auto_only and _source_path(renderer) not in faces.auto_paths:
            continue
        _remaining(deadline)
        if _key(game_object) in detached_templates:
            continue
        stage_beam = stage_opaque = stage_transparent = stage_soft = None
        stage_motion = None
        overlay = False
        renderer_type = renderer.type.name
        material_refs = tree.get("m_Materials", ())
        if stage_nodes is not None and renderer_type in {"MeshRenderer", "SkinnedMeshRenderer"}:
            binding = stage_nodes.binding(game_object)
            overlay = binding is not None and mv_studio_stage_overlay.layer(scene, game_object)
            if renderer_type == "MeshRenderer":
                stage_motion = binding
            shared_material = material_refs and all(ref == material_refs[0] for ref in material_refs[1:])
            if animated_effect and binding and (len(material_refs) == 1 or
                    renderer_type == "SkinnedMeshRenderer" and not overlay and shared_material):
                candidate = _ref(renderer, material_refs[0])
                if renderer_type == "SkinnedMeshRenderer" and len(material_refs) == 1:
                    try:
                        stage_beam = mv_studio_stage_beam.export_material(
                            scene, renderer, game_object, candidate, materials, deadline)
                    except ValueError:
                        pass
                if stage_beam is None and (not overlay or renderer_type == "SkinnedMeshRenderer"):
                    if overlay or mv_studio_stage_overlay.world_layer(scene, game_object):
                        if not overlay and renderer_type == "MeshRenderer":
                            stage_soft = mv_studio_soft_billboards.read_material(scene, candidate)
                        if stage_soft is None:
                            stage_transparent = mv_studio_stage_overlay.read_material(scene, candidate, world=not overlay)
                    if (stage_transparent is None and candidate is not None and not overlay
                            and renderer_type == "SkinnedMeshRenderer" and len(material_refs) == 1):
                        identity = _key(candidate)
                        if identity not in stage_metadata:
                            stage_metadata[identity] = mv_studio_stage_materials.read_material(
                                scene, candidate, ambient_materials, single_ambient)
                        descriptor = stage_metadata[identity]
                        if descriptor and descriptor["shader"] == "general":
                            stage_opaque = descriptor
                if stage_beam is not None or stage_opaque is not None or stage_transparent is not None:
                    stage_motion = binding
        overlay = overlay and stage_motion is not None
        # AxisBillboard turns its own transform toward the camera, so a static
        # billboard keeps its authored hierarchy instead of baked world vertices.
        axis_node = (stage_materials and stage_motion is None and renderer_type == "MeshRenderer"
                     and _key(game_object) in axis_billboards)
        flash_binding = stage_flashes.get(_key(renderer)) if stage_materials else None
        renderer_enabled = tree.get("m_Enabled", True)
        if (not renderer_enabled and flash_binding is None) or (stage_motion is None and not scene.active(game_object)):
            continue
        game_name = scene.name(game_object)
        if renderer.type.name == "Mesh":
            mesh_obj = renderer
        elif renderer.type.name == "SkinnedMeshRenderer":
            mesh_obj = _ref(renderer, tree.get("m_Mesh"))
        else:
            mesh_obj = scene.filters.get(_key(game_object))
        # A MeshFilter may point at Unity's built-in Plane or Quad, which no
        # bundle contains. Unity draws it with the renderer's own material.
        builtin_mesh = (unity_builtin_meshes.mesh_id(scene, game_object)
                        if stage_materials and mesh_obj is None and renderer_type == "MeshRenderer" else None)
        if not builtin_mesh and (mesh_obj is None or mesh_obj.type.name != "Mesh"):
            scene.warn("linked_mesh_missing", game_name)
            continue
        if not builtin_mesh and not faces.include(scene, renderer, game_object, mesh_obj):
            continue
        mesh_source = renderer if builtin_mesh else mesh_obj
        mesh_name = unity_builtin_meshes.MESHES[builtin_mesh][0] if builtin_mesh else scene.name(mesh_obj)
        # These game-specific ground helpers can be ten metres wide and would
        # dwarf the character when fitting the camera. They are not body parts.
        if re.search(r"(?:foot.?shadow|dropshadow|shadowtoe)", mesh_name + " " + game_name, re.I):
            continue
        auto_face = _source_path(renderer) in faces.auto_paths
        skin_material = (stage_opaque or stage_transparent) if renderer_type == "SkinnedMeshRenderer" else None
        native_skin = stage_beam is not None or skin_material is not None
        needs_sort_bounds = (
            stage_motion is not None and not builtin_mesh and (
                stage_soft is not None or stage_transparent is not None
                and (stage_transparent.get("alphaBlend") or stage_transparent.get("depthWrite"))
            )
        )
        raw = {} if rig is not None or native_skin or needs_sort_bounds else None
        penlight = penlights.get(_key(game_object)) if renderer.type.name == "MeshRenderer" else None
        native_attributes = {} if penlight is not None else None
        display_binding = stage_displays.get(_key(renderer)) if stage_materials else None
        stage_inputs = {} if overlay or stage_transparent or stage_soft or flash_binding or display_binding else None
        if stage_soft:
            stage_inputs["softBillboard"] = stage_soft["kind"]
        if stage_transparent and stage_transparent.get("matcap"):
            stage_inputs["needsAuthoredNormals"] = True
        coloring_for_renderer = {}
        if stage_opaque and stage_opaque.get("vertexColor") and stage_inputs is None:
            stage_inputs = {}
        if stage_materials and renderer.type.name == "MeshRenderer":
            for pointer in tree.get("m_Materials", ()):
                candidate = _ref(renderer, pointer)
                if candidate is None:
                    continue
                identity = _key(candidate)
                if identity not in stage_metadata:
                    stage_metadata[identity] = mv_studio_stage_materials.read_material(
                        scene, candidate, ambient_materials, single_ambient)
                description = stage_metadata[identity]
                if description and description.get("vertexColor"):
                    if stage_inputs is None:
                        stage_inputs = {}
                    if description.get("usesEmissive"):
                        stage_inputs["needsEmissiveUV"] = True
                coloring = mv_studio_stage_coloring.renderer_binding(scene, game_object, stage_coloring.get(identity))
                if coloring is not None:
                    coloring_for_renderer[identity] = coloring
                    if stage_inputs is None:
                        stage_inputs = {}
        # LivePropBasic swaps its own material instances into the renderers below it.
        prop_light = mv_studio_stage_props.renderer_entry(scene, game_object, stage_props) if stage_materials else None
        if prop_light is not None and stage_inputs is None:
            stage_inputs = {}
        bones, skin_warnings, stage_skin = None, [], None
        transparent_skin_material = None
        try:
            # A previously visible renderer may still use its rest pose when
            # the original skin exceeds the live stage preview's support.
            for use_skin in ((True, False) if skin_material is not None else (native_skin,)):
                if renderer.type.name == "SkinnedMeshRenderer" and not use_skin:
                    refs = tree.get("m_Bones", [])
                    if len(refs) > 1024:
                        raise ModelViewerError("The model has too many bones for the mobile viewer.")
                    bones = []
                    for ref in refs:
                        transform = _ref(renderer, ref)
                        bones.append(faces.world(scene, renderer, scene.world(transform)) if transform is not None else None)
                if stage_motion is None and not axis_node:
                    world = faces.world(scene, renderer, scene.world(scene.transforms.get(_key(game_object))))
                else:
                    import numpy as np

                    # The native parent hierarchy supplies the transforms for these meshes.
                    world = np.eye(4)
                keywords = {"rig_data": raw} if raw is not None else {}
                if native_attributes is not None:
                    keywords["penlight_data"] = native_attributes
                if stage_inputs is not None:
                    keywords["stage_data"] = stage_inputs
                if any(tree.get("m_BlendShapeWeights", [])):
                    keywords["morph_weights"] = tree["m_BlendShapeWeights"]
                    keywords["deadline"] = deadline
                if builtin_mesh:
                    name, positions, normals, uv, submeshes = unity_builtin_meshes.geometry(builtin_mesh, world)
                    if stage_inputs is not None:
                        stage_inputs["colorAbsent"] = True  # Plane and Quad have no COLOR stream.
                else:
                    name, positions, normals, uv, submeshes = _geometry(mesh_obj, world, bones, skin_warnings, **keywords)
                overlay_inputs_ready = uv is not None
                if stage_transparent and stage_transparent.get("matcap"):
                    # MatCap projects authored normals into camera space and
                    # reads COLOR0. Mesh UV0 does not enter this shader.
                    overlay_inputs_ready = (stage_inputs["authoredNormals"] and "color" in stage_inputs
                                            and len(submeshes) == 1)
                if not use_skin or not any(map(len, submeshes)):
                    break
                merge_submeshes = (stage_transparent is not None and not overlay
                                   and not stage_transparent.get("alphaBlend")
                                   and len(submeshes) > 1 and len(material_refs) == len(submeshes))
                if (overlay_inputs_ready
                        and (stage_beam is None and stage_transparent is None or len(submeshes) == 1 or merge_submeshes)
                        and (not stage_opaque or not stage_opaque.get("vertexColor") or "color" in stage_inputs
                             or stage_inputs.get("colorAbsent"))):
                    if stage_transparent is not None:
                        try:
                            transparent_skin_material = mv_studio_stage_overlay.export_material(
                                materials, stage_transparent, renderer_tree=tree, skinned=True)
                        except ValueError:
                            pass
                    if stage_transparent is None or transparent_skin_material is not None:
                        stage_skin = stage_nodes.export_skinned(renderer, tree, game_object, raw, rigid=stage_beam is not None)
                if stage_skin is not None and merge_submeshes:
                    # These draw ranges share the same native material and
                    # belong to one animated renderer property block.
                    submeshes = [np.concatenate(submeshes)]
                if stage_skin is not None or stage_beam is not None or not scene.active(game_object):
                    break
                stage_motion = raw = stage_transparent = transparent_skin_material = None
                overlay = False
        except Exception as error:
            if auto_face:
                faces.failed()
                continue
            if getattr(scene, "preview_stage", False) and str(error) in {
                "A model skin contains a zero-scale transform.",
                "The model contains a zero-scale transform.",
            }:
                scene.warn("stage_hidden_transform", game_name)
                continue
            raise
        for warning in skin_warnings:
            scene.warn(warning, game_name)
        if not any(map(len, submeshes)):
            continue
        if native_skin and stage_skin is None and (stage_beam is not None or stage_motion is not None):
            continue
        flash = None
        if flash_binding is not None:
            if uv is not None and len(submeshes) == 1 and "lightUV" in stage_inputs:
                try:
                    flash = mv_studio_stage_flash.export(materials, flash_binding)
                except ValueError:
                    pass
            if flash is None and not renderer_enabled:
                continue
        if scene.stats["meshes"] + 1 > mesh_limit or scene.stats["vertices"] + len(positions) > MAX_VERTICES \
                or scene.stats["triangles"] + sum(map(len, submeshes)) > MAX_TRIANGLES:
            if auto_face:
                faces.failed()
                continue
            raise ModelViewerError("The selected models are too complex. Open fewer model parts.")
        scene.stats["meshes"] += 1
        scene.stats["vertices"] += len(positions)
        scene.stats["triangles"] += sum(map(len, submeshes))
        attributes = {"POSITION": glb.attribute(positions, "VEC3", bounds=True),
                      "NORMAL": glb.attribute(normals, "VEC3")}
        skin, targets, target_names, target_hashes, target_weights = None, [], [], [], []
        if stage_skin is not None:
            skin_attributes, skin = stage_skin
            attributes.update(skin_attributes)
        face_depth_bind = face_depth_bindings.get(_key(renderer))
        if face_depth_bind is not None and (
                len(submeshes) != 1 or not _member_face_depth_binding(raw, tree, face_depth_bind[2])):
            face_depth_bind = None
        if rig is not None:
            rig.record_bounds(positions)
            static_attributes = dict(attributes)
            checkpoint = (len(glb.data), {key: len(glb.doc.get(key, [])) for key in ("accessors", "bufferViews", "skins")})
            try:
                attributes, skin = rig.attributes(renderer, tree, game_object, raw, positions,
                                                  rigid_bind=face_depth_bind[0] if face_depth_bind is not None else None)
                targets, target_names, target_hashes, target_weights = rig.morph_targets(raw, renderer, game_object)
            except ValueError as error:
                rig.warnings.append(str(error))
                del glb.data[checkpoint[0]:]
                for key, length in checkpoint[1].items():
                    if key in glb.doc:
                        del glb.doc[key][length:]
                attributes = static_attributes
                skin = None
                targets, target_names, target_hashes, target_weights = [], [], [], []
        if uv is not None:
            attributes["TEXCOORD_0"] = glb.attribute(uv, "VEC2")
        member_depth_mesh = (
            member_depth and skin is not None and renderer_type == "SkinnedMeshRenderer"
            and game_name.casefold() in {"body", "hair"} and _source_path(renderer) in rig.selected
            and _source_path(renderer) not in facial_sources and scene.tree(game_object).get("m_Layer") == 16
            and tree.get("m_Enabled") is True and tree.get("m_CastShadows") in (0, 1, 2)
            and not tree.get("m_ForceRenderingOff")
            and tree.get("m_Bones") and raw["mesh"].m_BindPose and raw["authored_normals"]
            and "_SIFAS_COLOR" in attributes and _member_depth_vertices(raw["mesh"], raw, tree.get("m_Quality"))
        )
        soft_billboard = None
        if stage_soft and uv is not None and len(submeshes) == 1:
            center = stage_inputs.get("softCenter")
            if center is not None or stage_inputs.get("smokeNormals"):
                texture = stage_soft["texture"]
                try:
                    texture_index = materials.texture(texture)
                except ValueError:
                    pass
                else:
                    sort_bounds = mv_studio_stage_overlay._sort_bounds(tree, (raw or {}).get("mesh"))
                    soft_billboard = {**stage_soft, "texture": texture_index, **(sort_bounds or {})}
                    mv_studio_stage_materials.collect_texture_sampler(materials, texture, soft_billboard, "mainSampler")
                    if "color" in stage_inputs:
                        attributes["_STAGE_COLOR"] = glb.attribute(stage_inputs["color"], "VEC4")
                    if center is not None:
                        attributes["_SOFT_CENTER"] = glb.attribute(center, "VEC3")
        source = _source_path(mesh_source)
        source_index = rig.source_indices.get(source) if rig is not None else None
        writable = source_index is not None and not auto_face
        import numpy as np
        position_matrix = np.diag([-1., 1., 1., 1.])
        if skin is None:
            if bones:
                writable = False  # Rest-skin baking is not one invertible affine map.
            else:
                position_matrix = position_matrix @ world
        mesh_identity = {"source": source_index, "file": source_files.get(source, {}).get(id(mesh_source.assets_file), 0),
                         "id": str(builtin_mesh) if builtin_mesh else str(mesh_obj.path_id)}
        penlight_attributes, penlight_transform = None, None
        if native_attributes:
            penlight_transform = {"bindingSuffix": penlight[1],
                                  "localToPreview": position_matrix.T.reshape(-1).tolist()}
        stage_color = stage_lightmap = stage_lightmap_source = stage_uv = stage_emissive_uv = coloring_uv = None
        primitives, refs, first_face = [], tree.get("m_Materials", []), 0
        for index, triangles in enumerate(submeshes):
            if not len(triangles):
                continue
            ref = refs[min(index, len(refs) - 1)] if refs else None
            material_obj = None
            original_material = None
            try:
                original_material = _ref(renderer, ref)
                material_obj = faces.material(renderer, original_material)
                material = materials.material(material_obj)
            except Exception:
                if not auto_face:
                    raise
                material = materials.material(None)
                scene.warn("texture_unavailable", game_name)
            component = 5123 if len(positions) <= 65535 else 5125
            primitives.append({"attributes": attributes,
                               "indices": glb.attribute(triangles.reshape(-1), "SCALAR", component),
                               "material": material, "mode": 4,
                               "extras": {"viewerMesh": {"version": 1, "mesh": mesh_identity,
                                   "renderer": str(renderer.path_id), "submesh": index,
                                   "rendererIdentity": {"source": rig.source_indices.get(_source_path(renderer)) if rig is not None else None,
                                       "file": source_files.get(_source_path(renderer), {}).get(id(renderer.assets_file), 0),
                                       "id": str(renderer.path_id)},
                                   "firstFace": first_face, "faceCount": len(triangles),
                                   "vertexCount": len(positions), "vertexOrder": "identity",
                                   "positionMatrix": position_matrix.T.reshape(-1).tolist(),
                                   "boneOrder": "identity", "writable": writable}}})
            if penlight_transform and material_obj is not None and _key(material_obj) in penlight[0]:
                native_material = _penlight_material(scene.tree(material_obj))
                if native_material is not None:
                    if penlight_attributes is None:
                        penlight_attributes = dict(attributes)
                        penlight_attributes.update({
                            name: glb.attribute(values, "VEC4" if name == "_PENLIGHT_COLOR" else "VEC3")
                            for name, values in native_attributes.items()
                        })
                    primitives[-1]["attributes"] = penlight_attributes
                    primitives[-1]["extras"]["mvPenlight"] = {**penlight_transform, "material": native_material}
            if stage_beam is not None:
                primitives[-1]["extras"]["mvStageBeam"] = stage_beam
            if (member_depth_mesh and original_material is not None and original_material is material_obj
                    and _source_path(original_material) == _source_path(renderer)):
                depth = _member_depth_material(scene, original_material)
                if depth is not None:
                    primitives[-1]["extras"]["mvStageCameraDepth"] = depth
            if (face_depth_bind is not None and skin is not None and "_SIFAS_COLOR" in attributes
                    and len(targets) == len(getattr(raw["mesh"].m_Shapes, "channels", ()))
                    and material_obj is face_depth_bind[1]):
                depth = _member_depth_material(scene, material_obj)
                if depth is not None:
                    if face_depth_bind[2] != "eye":
                        depth["kind"] = "memberFace"
                    primitives[-1]["extras"]["mvStageCameraDepth"] = depth
            if soft_billboard is not None:
                primitives[-1]["extras"]["mvStageSoftBillboard"] = soft_billboard
            if flash is not None:
                primitives[-1]["attributes"] = {**attributes, "_STAGE_FLASH_UV": glb.attribute(stage_inputs["lightUV"], "VEC2")}
                primitives[-1]["extras"]["mvStageFlash"] = flash
            display = None
            if display_binding and uv is not None and len(submeshes) == 1:
                try:
                    display = mv_studio_stage_display.export(scene, materials, display_binding)
                except ValueError:
                    pass
                if display is not None:
                    if "color" in stage_inputs and (display["fallback"].get("vertexColor")
                            or any(variant["background"].get("vertexColor") for variant in display["variants"])):
                        stage_color = glb.attribute(stage_inputs["color"], "VEC4")
                        primitives[-1]["attributes"] = {**primitives[-1]["attributes"], "_STAGE_COLOR": stage_color}
                    primitives[-1]["extras"]["mvStageDisplay"] = display
            overlay_material = None
            if overlay_inputs_ready and (overlay or stage_transparent is not None):
                if transparent_skin_material is not None:
                    overlay_material = {**transparent_skin_material, "rendererClass": 137}
                else:
                    try:
                        overlay_material = (mv_studio_stage_overlay.material(scene, materials, material_obj)
                                            if overlay else mv_studio_stage_overlay.export_material(
                                                materials, stage_transparent, renderer_tree=tree,
                                                mesh=(raw or {}).get("mesh"), builtin_mesh=bool(builtin_mesh)))
                    except ValueError:
                        pass
                if overlay_material is not None:
                    if overlay_material["vertexColor"] and "color" in stage_inputs:
                        if stage_color is None:
                            stage_color = glb.attribute(stage_inputs["color"], "VEC4")
                        primitives[-1]["attributes"] = {**attributes, "_STAGE_COLOR": stage_color}
                    if not overlay:
                        overlay_material["world"] = True
                        mv_studio_stage_materials.collect_texture_sampler(
                            materials, stage_transparent["texture"], overlay_material, "mainSampler")
                    primitives[-1]["extras"]["mvStageOverlay"] = overlay_material
            descriptor = stage_metadata.get(_key(material_obj)) if stage_materials and material_obj is not None and display is None and overlay_material is None else None
            if descriptor and (not stage_opaque or stage_skin is not None):
                descriptor = dict(descriptor)
                if descriptor.get("vertexColor") and (stage_inputs is None or "color" not in stage_inputs):
                    # Unity feeds opaque white to COLOR when the mesh has no color stream.
                    if stage_inputs is not None and stage_inputs.get("colorAbsent"):
                        descriptor["vertexColorAbsent"] = True
                    else:
                        descriptor = None
                if descriptor and descriptor["shader"] == "stage":
                    if stage_uv is None and "lightUV" in stage_inputs:
                        info = mv_studio_stage_materials.lightmap_for(scene, renderer, tree, lightmap_settings)
                        if info:
                            texture, transform = info
                            try:
                                stage_lightmap = materials.texture(texture)
                            except ValueError:
                                stage_lightmap = None
                            if stage_lightmap is not None:
                                stage_lightmap_source = texture
                                coords = stage_inputs["lightUV"] * transform[:2] + transform[2:]
                                coords[:, 1] = 1 - coords[:, 1]
                                stage_uv = glb.attribute(coords, "VEC2")
                    if stage_uv is not None:
                        descriptor["lightmap"] = stage_lightmap
                        if descriptor.get("reflectionToggle"):
                            if cubemap_owner is not None:
                                descriptor["reflectionQualityControlled"] = _key(material_obj) in cubemap_owner
                            reflection = mv_studio_stage_materials.export_reflection(
                                scene, glb, materials, material_obj, stage_cubes,
                            )
                            if reflection is not None:
                                descriptor["reflection"] = reflection
                    else:
                        descriptor = None
                if descriptor and descriptor.pop("usesEmissive", False):
                    emissive = None
                    if "emissiveUV" in stage_inputs:
                        try:
                            emissive = mv_studio_stage_materials.export_emissive(
                                scene, materials, material_obj, controlled=_key(material_obj) in stage_emissive)
                        except ValueError:
                            pass
                    if emissive is None:
                        descriptor = None
                    else:
                        descriptor["emissive"] = emissive
                        if stage_emissive_uv is None:
                            coords = stage_inputs["emissiveUV"].copy()
                            coords[:, 1] = 1 - coords[:, 1]
                            stage_emissive_uv = glb.attribute(coords, "VEC2")
                if descriptor and descriptor["shader"] == "blend":
                    try:
                        if uv is None or not mv_studio_stage_materials.export_blend_maps(materials, material_obj, descriptor):
                            descriptor = None
                    except ValueError:
                        descriptor = None
                if descriptor:
                    custom = {}
                    if descriptor.get("vertexColor") and not descriptor.get("vertexColorAbsent"):
                        if stage_color is None:
                            stage_color = glb.attribute(stage_inputs["color"], "VEC4")
                        custom["_STAGE_COLOR"] = stage_color
                    if descriptor["shader"] == "stage":
                        custom["_STAGE_LIGHT_UV"] = stage_uv
                    if "emissive" in descriptor:
                        custom["_STAGE_EMISSIVE_UV"] = stage_emissive_uv
                    primitives[-1]["attributes"] = {**primitives[-1]["attributes"], **custom}
                    primitives[-1]["extras"]["mvStageMaterial"] = descriptor
                    if descriptor["shader"] in {"stage", "general"}:
                        mv_studio_stage_materials.collect_main_sampler(
                            scene, materials, material_obj, descriptor,
                            static_opaque=descriptor["shader"] == "general" and stage_opaque is None,
                        )
                    if descriptor["shader"] == "stage":
                        mv_studio_stage_materials.collect_texture_sampler(
                            materials, stage_lightmap_source, descriptor, "lightmapSampler",
                        )
            if (stage_materials and material_obj is not None and renderer_type == "MeshRenderer" and display is None
                    and mv_studio_stage_overlay.world_layer(scene, game_object)):
                shadow = mv_studio_stage_materials.camera_depth(
                    scene, material_obj, tree, supports_cutout=bool(descriptor and "alphaCutoff" in descriptor),
                )
                if shadow is not None:
                    primitives[-1]["extras"]["mvStageCameraDepth"] = shadow
            coloring = coloring_for_renderer.get(_key(material_obj)) if material_obj is not None else None
            if coloring and uv is not None and "lightUV" in stage_inputs:
                try:
                    descriptor = mv_studio_stage_coloring.export(glb, materials, coloring, stage_palettes)
                except ValueError:
                    descriptor = None
                if descriptor is not None:
                    # world is the matrix baked into these vertices (identity under a retained node).
                    descriptor = mv_studio_stage_coloring.with_sort_center(
                        descriptor, tree, None if builtin_mesh else (raw or {}).get("mesh") or mesh_obj.read(),
                        builtin_mesh=bool(builtin_mesh), world=world)
                    if coloring_uv is None:
                        coloring_uv = glb.attribute(stage_inputs["lightUV"], "VEC2")
                    primitives[-1]["attributes"] = {**primitives[-1]["attributes"], "_STAGE_COLOR_INDEX": coloring_uv}
                    primitives[-1]["extras"]["mvStageColoring"] = descriptor
            prop = (mv_studio_stage_props.light(prop_light, scene.name(material_obj))
                    if prop_light is not None and material_obj is not None else None)
            if prop is not None:
                primitives[-1]["extras"]["mvPropLight"] = prop
                rimlight = mv_studio_stage_props.rimlight_material(scene, material_obj) if uv is not None else None
                try:
                    rimlight = mv_studio_stage_props.export_rimlight(materials, rimlight) if rimlight else None
                except ValueError:
                    rimlight = None
                if rimlight is not None:
                    if "color" in stage_inputs:
                        if stage_color is None:
                            stage_color = glb.attribute(stage_inputs["color"], "VEC4")
                        primitives[-1]["attributes"] = {**primitives[-1]["attributes"], "_STAGE_COLOR": stage_color}
                    primitives[-1]["extras"]["mvStageRimlight"] = rimlight
            first_face += len(triangles)
            if targets:
                primitives[-1]["targets"] = targets
        mesh_index = len(glb.doc["meshes"])
        glb.doc["meshes"].append({"name": name or game_name, "primitives": primitives})
        if target_names:
            glb.doc["meshes"][-1].update(weights=target_weights, extras={"targetNames": target_names})
        node_index = len(glb.doc["nodes"])
        glb.doc["nodes"].append({"name": name or game_name, "mesh": mesh_index,
                                 "extras": {"sourceName": _source_name(mesh_source)}})
        if _source_path(renderer) in facial_sources and renderer_role(
                scene, renderer, game_object, mesh_obj, dynamic=True) == "mouth":
            glb.doc["nodes"][-1]["extras"]["viewerFacialRole"] = "mouth"
        if _source_path(renderer) in faces.auto_paths and re.search(r"closed|blink|(?:^|[_\s])close(?:$|[_\s])", name + " " + game_name, re.I):
            glb.doc["nodes"][-1]["extras"]["hidden_default"] = True
        if stage_motion is None and not axis_node:
            glb.doc["scenes"][0]["nodes"].append(node_index)
        else:
            if stage_skin is not None:
                glb.doc["nodes"][node_index]["skin"] = skin
                if skin_material is not None:
                    glb.doc["nodes"][node_index]["extras"]["mvStageSkin"] = True
            if stage_nodes is None:
                from .mv_studio_stage_nodes import StageNodes

                stage_nodes = StageNodes(scene, glb, ())
            stage_nodes.attach(game_object, node_index)
        if rig is not None and skin is not None:
            rig.place(node_index, renderer, game_object, skin, target_names, target_hashes, target_weights)
        if auto_face:
            faces.added += 1
            from .model_faces import renderer_role
            faces.rendered_roles.add(renderer_role(scene, renderer, game_object, mesh_obj,
                                                   _source_path(renderer) in faces.dynamic_sources))
    if stage_materials and axis_billboards:
        mv_studio_axis_billboard.tag(glb, stage_nodes, axis_billboards)
    if stage_materials and lossy_scales:
        from . import mv_studio_lossy_scale
        mv_studio_lossy_scale.tag(glb, stage_nodes, lossy_scales)
    return materials


def _to_glb(scene, glb, faces, deadline, rig=None, *, require_existing_clips=False):
    if not scene.stats["meshes"]:
        raise ModelViewerError("No visible model meshes were found. Choose an extracted 3D model file.")
    _remaining(deadline)
    faces.finish()
    if faces.enabled and faces.status in ("added", "already_present"):
        scene.warnings = [warning for warning in scene.warnings if warning["code"] != "facial_assets_missing"]
    elif faces.auto_paths and not faces.added:
        faces.status = "unavailable"
        faces.warn("face_source_unavailable", "The original face could not be opened. The costume is still shown.")
    if rig is not None:
        rig.finalize(animations=False)
    data = bytes(glb.finish())
    _remaining(deadline)
    result = (data, dict(scene.stats), list(scene.warnings) + faces.warnings, faces.metadata())
    if rig is None:
        return result
    base_rig = rig.metadata()
    if any(obj.type.name == "AnimationClip" for obj in scene.env.objects):
        checkpoint = (glb.doc, glb.data, rig.clips, rig.animation_warnings, rig.scaling)
        try:
            rig.finalize()
            # A later optional append must not erase a complete, playable clip
            # already committed with this same geometry. The immutable snapshot
            # also protects its valid accessors if re-export only partly fails.
            for previous in base_rig.get("clips", []) if require_existing_clips else []:
                if previous.get("bindingComplete") and not any(
                    all(current.get(key) == previous.get(key) for key in
                        ("sourceId", "sourceHash", "sourceName", "channels", "sourceTracks"))
                    and current.get("bindingComplete") for current in rig.clips
                ):
                    raise ModelViewerError("A completed animation could not be retained.")
            animated = bytes(glb.finish())
            _remaining(deadline)
            return (animated,) + result[1:] + (rig.metadata(),)
        except Exception:
            glb.doc, glb.data, rig.clips, rig.animation_warnings, rig.scaling = checkpoint
            if require_existing_clips:
                raise
            base_rig["animationWarnings"].append({"code": "animation_unavailable", "message": "Animation loading exceeded its remaining preview budget. The completed model is still shown."})
    return result + (base_rig,)


def _finish_stage_samplers(materials, deadline, base):
    from .mv_studio_stage_materials import (
        AUXILIARY_SAMPLERS, MAIN_SAMPLERS, STATIC_OPAQUE_SAMPLERS, attach_texture_samplers,
    )

    # Preserve the completed lightmap and effect chains if the extra static
    # surfaces run out of conversion time or texture space.
    for priority in (MAIN_SAMPLERS, AUXILIARY_SAMPLERS, STATIC_OPAQUE_SAMPLERS):
        if not attach_texture_samplers(materials, deadline, priority=priority):
            continue
        try:
            _remaining(deadline)
            data = bytes(materials.glb.finish())
            _remaining(deadline)
        except ModelViewerError:
            break
        base = (data, dict(materials.scene.stats), *base[2:])
    return base


def _build(paths, deadline, face_context=None, rigged=False, *, _optional_deadline=None, _geometry_deadline=None):
    """Keep geometry and mandatory finishing work within separate fixed caps.

    Selected geometry retains its original allowance. Facial geometry ends
    forty seconds after that deadline; playable rigs reserve a further twenty
    seconds for final binding/serialization. Lookup/network and static facial
    conversion keep their forty-second caps. Recovery reuses both original
    deadlines instead of renewing either allowance. Completed GLBs are immutable.
    """
    from .model_faces import FacePlan, FACE_SECONDS, SavedFacePlatformMismatch
    env = _environment(paths, deadline)
    scene, glb = _Scene(env, deadline), _Glb()
    scene.preview_stage = bool((face_context or {}).get("_mv_stage"))
    scene.stage_motion_bindings = (face_context or {}).get("_mv_stage_motion_bindings", ())
    scene.native_stage_effect = (face_context or {}).get("_mv_native_stage_effect") is True
    if (face_context or {}).get("_mv_attach_key"):
        from .mv_studio_suit_attach import MemberAttach
        scene.member_attach = MemberAttach.read(scene, face_context["_mv_attach_key"])
    disabled_faces = FacePlan(scene, paths, dict(face_context, enabled=False) if face_context else None, deadline)
    rig = None
    if rigged:
        from .model_rig import RigBuilder
        try:
            model_paths = (face_context or {}).get("_selected_model_paths", paths)
            rig = RigBuilder(scene, glb, disabled_faces, model_paths, deadline)
        except ValueError:
            glb = _Glb()
            scene.warn("rig_unavailable")
    materials = _append_scene(scene, glb, disabled_faces, deadline, rig=rig)
    if rig is not None and (face_context or {}).get("_mv_performer"):
        from . import mv_studio_member_shadow

        shadow = mv_studio_member_shadow.read(scene, glb, materials, rig, deadline)
        if shadow is not None:
            glb.doc["scenes"][0].setdefault("extras", {})["mvMemberShadow"] = shadow
    base = _to_glb(scene, glb, disabled_faces, deadline, rig=rig)
    if materials.stage_texture_samplers:
        base = _finish_stage_samplers(materials, deadline, base)
    face_enabled = bool(face_context and face_context.get("enabled", True))
    playable_rig = rig is not None and (rig.skinned > 0 or bool(rig.morphs))
    authored_motion = bool(face_context and face_context.get("_mv_authored_motion"))
    # An MV import supplies its timeline-selected clip bundles up front.
    # They are already exported in base. A generic suit animation or a
    # rediscovered donor would append unrelated or duplicate motion.
    if not face_context or (not face_enabled and (not playable_rig or authored_motion)):
        return base

    geometry_deadline = _geometry_deadline
    if geometry_deadline is None:
        geometry_deadline = deadline + FACE_SECONDS
    optional_deadline = _optional_deadline
    if optional_deadline is None:
        optional_deadline = geometry_deadline + (FINAL_BINDING_SECONDS if playable_rig else 0)
    # Commit the verified offline pose before optional faces can consume the
    # common allowance. No catalog/cache lookup or expression discovery runs
    # here, and automatic motion never becomes a selected NodeScaling source.
    early_motion, preload_failed = [], False
    stage = None if authored_motion else face_context.get("_motion_stage")
    if playable_rig and stage is not None:
        motion_deadline = min(geometry_deadline, time.monotonic() + FACE_SECONDS)
        try:
            _remaining(motion_deadline)
            early_motion = stage.bundled(rig, paths, motion_deadline)
            if early_motion:
                _paths(paths + early_motion, internal=True)
                env = _environment(early_motion, motion_deadline, base_env=env)
                expanded = _Scene(env, motion_deadline, trees=scene.trees)
                expanded.stats, expanded.warnings = dict(base[1]), list(scene.warnings)
                rig.update(expanded, disabled_faces, motion_deadline)
                candidate = _to_glb(expanded, glb, disabled_faces, motion_deadline, rig=rig)
                stage.promote(candidate[4])
                if not candidate[4].get("previewMotion", {}).get("verified"):
                    raise ModelViewerError("The bundled preview could not be exported.")
                base, scene = candidate, expanded
        except Exception:
            # A failed merge may have changed the live environment or GLB.
            # Its immutable body remains safe; do not append faces to that
            # partially imported state or spend another body allowance.
            preload_failed = bool(early_motion)
            early_motion = []
            metadata = dict(base[4])
            metadata["animationWarnings"] = list(metadata.get("animationWarnings", [])) + [{
                "code": "animation_unavailable", "message": "The bundled preview could not be imported. The completed model is still shown."}]
            base = base[:4] + (metadata,)
    face_deadline = min(geometry_deadline, time.monotonic() + FACE_SECONDS)
    faces, completed, extra = disabled_faces, base, []
    face_append_started = False
    if face_enabled:
        faces = None
        try:
            if preload_failed:
                raise ModelViewerError("The optional preview import failed.")
            _remaining(face_deadline)
            scene.deadline = face_deadline
            faces = FacePlan(scene, paths, face_context, face_deadline)
            _remaining(face_deadline)
            extra = faces.resolve()
            _remaining(face_deadline)
            if extra:
                # Facial geometry keeps the original cap. Only a fully
                # completed append may enter the reserved finishing phase.
                render_deadline = geometry_deadline if rig is not None else face_deadline
                _paths(paths + early_motion + extra, internal=True)
                face_append_started = True
                env = _environment(extra, render_deadline, base_env=env)
                expanded = _Scene(env, render_deadline, trees=scene.trees)
                expanded.stats, expanded.warnings = dict(base[1]), list(scene.warnings)
                if rig is not None:
                    rig.update(expanded, faces, render_deadline)
                _append_scene(expanded, glb, faces, render_deadline, auto_only=True, materials=materials, rig=rig)
                _remaining(render_deadline)
                finish_deadline = optional_deadline if playable_rig else render_deadline
                expanded.deadline = finish_deadline
                if rig is not None:
                    rig.update(expanded, faces, finish_deadline)
                completed = _to_glb(expanded, glb, faces, finish_deadline, rig=rig,
                                    require_existing_clips=bool(early_motion))
                scene = expanded
            else:
                warnings = list(base[2]) + faces.warnings
                if faces.status == "already_present":
                    warnings = [warning for warning in warnings if warning["code"] != "facial_assets_missing"]
                completed = (base[0], base[1], warnings, faces.metadata()) + base[4:]
        except SavedFacePlatformMismatch as error:
            # A saved source-bound edit cannot be replaced with stock geometry
            # under the optional-face fallback. Keep the original files intact
            # and report this precise conflict before any costume operation.
            raise ModelViewerError(str(error)) from None
        except Exception:
            if faces is None:
                faces = FacePlan(scene, paths, None, face_deadline)
                faces.enabled = True
            faces.added = 0
            faces.status = "unavailable"
            faces.warn("face_source_unavailable", "The original face could not be opened. The costume is still shown.")
            completed = (base[0], base[1], list(base[2]) + faces.warnings, faces.metadata()) + base[4:]
            if preload_failed or (face_append_started and early_motion):
                return completed
            if face_append_started:
                # Optional import/rendering may already have changed the shared
                # environment, GLB and rig. Rebuild only this failed rigged
                # attempt, with faces disabled, so its independent automatic
                # motion cannot inherit partially appended facial geometry.
                # This cleanup uses only the original geometry time left;
                # it cannot borrow the finishing reserve or renew either cap.
                if playable_rig and time.monotonic() < geometry_deadline:
                    try:
                        recovered = _build(paths, geometry_deadline, dict(face_context, enabled=False), rigged=True,
                                           _optional_deadline=optional_deadline, _geometry_deadline=geometry_deadline)
                        return recovered[:2] + (list(recovered[2]) + faces.warnings, faces.metadata()) + recovered[4:]
                    except Exception:
                        pass
                return completed
            extra = []

    # Motion is independent of automatic facial completion. Unsupported/static
    # rigs cannot use discovered tracks; errors must not rewrite face status.
    if authored_motion or preload_failed or rig is None or not (rig.skinned > 0 or rig.morphs):
        return completed
    motion_deadline = min(optional_deadline, time.monotonic() + FACE_SECONDS)
    try:
        _remaining(motion_deadline)
        scene.deadline = motion_deadline
        rig.update(scene, faces, motion_deadline)
        from .model_animation import discover_animation_paths
        stage = face_context.get("_motion_stage")
        animation_paths = stage.automatic(rig, paths + extra, motion_deadline) if stage is not None else []
        if not animation_paths and rig.clips and not early_motion and not face_context.get("animation_paths"):
            return completed
        loaded = paths + early_motion + extra

        def append_motion(additions):
            nonlocal env, scene
            _remaining(motion_deadline)
            _paths(loaded + additions, internal=True)
            env = _environment(additions, motion_deadline, base_env=env)
            expanded = _Scene(env, motion_deadline, trees=scene.trees)
            expanded.stats, expanded.warnings = dict(completed[1]), list(scene.warnings)
            rig.update(expanded, faces, motion_deadline)
            result = _to_glb(expanded, glb, faces, motion_deadline, rig=rig)
            scene = expanded
            return result

        if animation_paths:
            # Commit the bundled/known preview before optional local expression
            # discovery. A missing or broken companion cannot remove this pose.
            completed = append_motion(animation_paths)
            loaded += animation_paths
        if len(loaded) >= MAX_INTERNAL_FILES:
            return completed
        companions = discover_animation_paths(loaded, face_context, faces.owner or rig.owner, motion_deadline)
        if not companions:
            return completed
        return append_motion(companions[:min(2, MAX_INTERNAL_FILES - len(loaded))])
    except Exception:
        metadata = dict(completed[4])
        metadata["animationWarnings"] = list(metadata.get("animationWarnings", [])) + [{
            "code": "animation_unavailable", "message": "A local animation companion could not be imported. The completed model is still shown."}]
        return completed[:4] + (metadata,)


def _prune(now):
    for token, value in list(_SESSIONS.items()):
        if value[0] <= now:
            del _SESSIONS[token]
    while len(_SESSIONS) > MAX_CACHE_ENTRIES or sum(len(value[1]) for value in _SESSIONS.values()) > MAX_CACHE_BYTES:
        _SESSIONS.popitem(last=False)


def prepare(paths, *, face_context=None, rigged=False, motion_paths=None, reimport=False):
    """Convert selected, already-jailed bundle paths and create a short-lived GLB."""
    if not isinstance(rigged, bool):
        raise ModelViewerError("The rigged preview setting must be true or false.")
    if not isinstance(reimport, bool):
        raise ModelViewerError("Reimport must be on or off.")
    paths = _paths(paths)
    if motion_paths is not None and (not rigged or not isinstance(motion_paths, (list, tuple))):
        raise ModelViewerError("The retained motion library is too large or invalid.")
    if motion_paths is not None and len(motion_paths) > MAX_MOTION_FILES:
        raise ModelViewerError(f"The motion library allows at most {MAX_MOTION_FILES} source files. Selected: {len(motion_paths)}.")
    library_paths = _paths(motion_paths, internal=True) if motion_paths else []
    library_paths = [path for path in library_paths if path not in paths]
    combined_paths = _paths(paths + library_paths, internal=True)
    if not _BUILD_LOCK.acquire(timeout=1):
        raise ViewerBusyError("Another model is opening. Wait for it to finish and try again.")
    previous_reimport = getattr(_REQUEST_STATE, "reimport", False)
    _REQUEST_STATE.reimport = reimport
    try:
        deadline = time.monotonic() + BUILD_SECONDS
        try:
            # Keep the original internal call shape for callers/tests that do
            # not enable automatic discovery.
            if rigged:
                from .model_motion import prepare_motion_inputs
                with prepare_motion_inputs(combined_paths, face_context, deadline) as motion:
                    context = dict(face_context or {"enabled": False, "allow_download": False})
                    context["_motion_stage"] = motion
                    context["origins"] = {**context.get("origins", {}), **motion.origins}
                    context["_selected_model_paths"] = motion.paths[:len(paths)]
                    context["_selected_motion_paths"] = motion.paths[len(paths):]
                    built = _build(motion.paths, deadline, context, rigged=True)
                    if len(built) > 4:
                        motion.promote(built[4])
            else:
                built = _build(paths, deadline, face_context) if face_context is not None else _build(paths, deadline)
            data, stats, warnings = built[:3]
            faces = built[3] if len(built) > 3 else {"enabled": False, "status": "not_needed", "added": 0, "characters": []}
            rig = built[4] if len(built) > 4 else {"enabled": bool(rigged), "available": False}
            rig = dict(rig)
            companions = rig.pop("_editingCompanions", [])
            if rigged:
                from .game_motions import resolve_import
                # Only server-issued imports whose current bytes still match
                # their receipt may describe a playable composite timeline.
                rig = dict(rig, motionTimelines=resolve_import(paths + library_paths))
        except ModelViewerError:
            raise
        except Exception as error:
            raise ModelViewerError("This model could not be opened. Its format or linked assets may be unsupported.") from error
        token = secrets.token_hex(16)
        with _CACHE_LOCK:
            now = time.monotonic()
            _SESSIONS[token] = (now + CACHE_SECONDS, data, companions)
            _prune(now)
        return {"id": token, "url": f"/api/viewer/model/{token}.glb",
                "source_names": [os.path.basename(path) for path in paths],
                "stats": dict(stats), "warnings": warnings, "faces": faces, "rig": rig}
    finally:
        _REQUEST_STATE.reimport = previous_reimport
        _BUILD_LOCK.release()


def get_model(token):
    """Return the bounded GLB bytes, or None when an id is invalid or expired."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None
    with _CACHE_LOCK:
        now = time.monotonic()
        _prune(now)
        value = _SESSIONS.get(token)
        if value is None:
            return None
        _SESSIONS.move_to_end(token)
        return value[1]


def get_editing_companions(token):
    """Return source proofs from this completed preview, never client paths."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return []
    with _CACHE_LOCK:
        _prune(time.monotonic())
        value = _SESSIONS.get(token)
        return [dict(row) for row in value[2]] if value is not None and len(value) > 2 else []
