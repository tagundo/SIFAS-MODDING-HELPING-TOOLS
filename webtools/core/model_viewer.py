"""Read-only, bounded UnityFS to GLB conversion for the local 3D viewer.

Only explicitly supplied bundle bytes are loaded. Unity dependencies can resolve
to another supplied bundle or an embedded resource, never to an arbitrary file.
The GLB contains static rest geometry and original-size PNG textures; source
meshes, skin weights, texture pixels and bundle files are never written.
"""
from collections import OrderedDict
import io
import json
import math
import ntpath
import os
import re
import secrets
import struct
import threading
import time

from . import decode


MAX_FILES = 8
MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 192 * 1024 * 1024
MAX_UNPACKED_BYTES = 192 * 1024 * 1024
MAX_VERTICES = 250_000
MAX_TRIANGLES = 500_000
MAX_MESHES = 128
MAX_TEXTURE_PIXELS = 32 * 1024 * 1024
MAX_GLB_BYTES = 64 * 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_CACHE_ENTRIES = 2
CACHE_SECONDS = 600
BUILD_SECONDS = 120

_BUILD_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_SESSIONS = OrderedDict()
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class ModelViewerError(ValueError):
    """An input cannot be shown by the model viewer."""


class ViewerBusyError(ModelViewerError):
    """Another bounded conversion is already using the worker."""


def _remaining(deadline):
    if time.monotonic() >= deadline:
        raise ModelViewerError("Model preview took too long. Try opening fewer model files.")


def _paths(paths):
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ModelViewerError("Choose between one and eight extracted Unity model files.")
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
        loaded = env.load_file(_bounded_bundle(data, layout, deadline), name=f"preview-{index}-{os.path.basename(path)}")
        loaded.preview_source_name = os.path.basename(path)
        loaded.preview_source_path = path
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
        tree = self.tree(transform)
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
    if identity != ("cab-9382ea964987eceddd567506a3b21312", 8291131735116688333):
        return False
    if not {"_TintColor", "_AmbientColor", "_RimlightColor"} <= set(_properties(tree, "m_Colors")):
        return False
    source = _source_path(obj)
    for candidate in scene.env.objects:
        if candidate.type.name == "AssetBundle" and _source_path(candidate) == source:
            if "asmember.shader.unity3d" in scene.tree(candidate).get("m_Dependencies", []):
                return True
    return False


class _Materials:
    def __init__(self, scene, glb, rigged=False):
        self.scene, self.glb = scene, glb
        self.rigged = rigged
        self.materials, self.textures = {}, {}
        self.pixels = 0

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
        image = decode._android_image(texture, self.scene.deadline)
        try:
            output = io.BytesIO()
            image.save(output, format="PNG")
            png = output.getvalue()
        finally:
            image.close()
        image_index = len(self.glb.doc["images"])
        self.glb.doc["images"].append({"bufferView": self.glb.view(png), "mimeType": "image/png",
                                       "name": str(texture.m_Name)})
        settings = getattr(texture, "m_TextureSettings", None)
        wrapping = {0: 10497, 1: 33071, 2: 33648, 3: 33071}
        sampler = {"magFilter": 9729, "minFilter": 9729,
                   "wrapS": wrapping.get(getattr(settings, "m_WrapU", 0), 10497),
                   "wrapT": wrapping.get(getattr(settings, "m_WrapV", 0), 10497)}
        sampler_index = len(self.glb.doc["samplers"])
        self.glb.doc["samplers"].append(sampler)
        index = len(self.glb.doc["textures"])
        self.glb.doc["textures"].append({"source": image_index, "sampler": sampler_index})
        self.textures[key] = index
        self.scene.stats["textures"] += 1
        return index

    def material(self, obj):
        key = _key(obj) if obj is not None else None
        if key in self.materials:
            return self.materials[key]
        tree = self.scene.tree(obj) if obj is not None else {}
        colors = _properties(tree, "m_Colors")
        # AS/Member never consumes _Color; carrying stale Unity generic shader
        # values into glTF incorrectly darkens real outfit heads. Lighting/tint
        # shader parity remains outside this unlit texture preview.
        color = ({"r": 1, "g": 1, "b": 1, "a": 1} if _as_member_material(self.scene, obj, tree)
                 else colors.get("_Color", {"r": .72, "g": .74, "b": .78, "a": 1}))
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
            attach_member_metadata(self.scene, obj, tree, material, self.texture)
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


def _geometry(mesh_obj, world, bone_world_matrices=None, warnings=None, rig_data=None, morph_weights=None, deadline=None):
    import numpy as np
    from UnityPy.helpers.MeshHelper import MeshHandler

    mesh = mesh_obj.read()
    _validate_mesh_allocations(mesh)
    handler = MeshHandler(mesh)
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
    if normals is None or not np.isfinite(normals).all():
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
                        colors=handler.m_Colors)
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


def _append_scene(scene, glb, faces, deadline, *, auto_only=False, materials=None, rig=None):
    # SIFAS downloads its facial prefab separately from the outfit. The base
    # Face mesh alone does not contain iris/mouth geometry. Do not invent it or
    # quietly tell users that a body-only file is a complete game character.
    for obj in scene.env.objects:
        if auto_only and _source_path(obj) not in faces.auto_paths:
            continue
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = scene.tree(obj)
        except Exception:
            continue
        face = tree.get("face")
        if isinstance(face, dict) and face.get("m_PathID") and _ref(obj, face) is None:
            scene.warn("facial_assets_missing")
    materials = materials or _Materials(scene, glb, rigged=rig is not None)
    materials.scene = scene
    for renderer, tree, game_object in scene.renderers:
        if auto_only and _source_path(renderer) not in faces.auto_paths:
            continue
        _remaining(deadline)
        if not tree.get("m_Enabled", True) or not scene.active(game_object):
            continue
        game_name = scene.name(game_object)
        if renderer.type.name == "Mesh":
            mesh_obj = renderer
        elif renderer.type.name == "SkinnedMeshRenderer":
            mesh_obj = _ref(renderer, tree.get("m_Mesh"))
        else:
            mesh_obj = scene.filters.get(_key(game_object))
        if mesh_obj is None or mesh_obj.type.name != "Mesh":
            scene.warn("linked_mesh_missing", game_name)
            continue
        if not faces.include(scene, renderer, game_object, mesh_obj):
            continue
        mesh_name = scene.name(mesh_obj)
        # These game-specific ground helpers can be ten metres wide and would
        # dwarf the character when fitting the camera. They are not body parts.
        if re.search(r"(?:foot.?shadow|dropshadow|shadowtoe)", mesh_name + " " + game_name, re.I):
            continue
        auto_face = _source_path(renderer) in faces.auto_paths
        raw = {} if rig is not None else None
        bones, skin_warnings = None, []
        try:
            if renderer.type.name == "SkinnedMeshRenderer":
                refs = tree.get("m_Bones", [])
                if len(refs) > 1024:
                    raise ModelViewerError("The model has too many bones for the mobile viewer.")
                bones = []
                for ref in refs:
                    transform = _ref(renderer, ref)
                    bones.append(faces.world(scene, renderer, scene.world(transform)) if transform is not None else None)
            arguments = (mesh_obj, faces.world(scene, renderer, scene.world(scene.transforms.get(_key(game_object)))), bones, skin_warnings)
            keywords = {"rig_data": raw} if raw is not None else {}
            if any(tree.get("m_BlendShapeWeights", [])):
                keywords["morph_weights"] = tree["m_BlendShapeWeights"]
                keywords["deadline"] = deadline
            name, positions, normals, uv, submeshes = _geometry(*arguments, **keywords)
        except Exception:
            if auto_face:
                faces.failed()
                continue
            raise
        for warning in skin_warnings:
            scene.warn(warning, game_name)
        if not any(map(len, submeshes)):
            continue
        if scene.stats["meshes"] + 1 > MAX_MESHES or scene.stats["vertices"] + len(positions) > MAX_VERTICES \
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
        if rig is not None:
            rig.record_bounds(positions)
            static_attributes = dict(attributes)
            checkpoint = (len(glb.data), {key: len(glb.doc.get(key, [])) for key in ("accessors", "bufferViews", "skins")})
            try:
                attributes, skin = rig.attributes(renderer, tree, game_object, raw, positions)
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
        primitives, refs = [], tree.get("m_Materials", [])
        for index, triangles in enumerate(submeshes):
            if not len(triangles):
                continue
            ref = refs[min(index, len(refs) - 1)] if refs else None
            try:
                material = materials.material(faces.material(renderer, _ref(renderer, ref)))
            except Exception:
                if not auto_face:
                    raise
                material = materials.material(None)
                scene.warn("texture_unavailable", game_name)
            component = 5123 if len(positions) <= 65535 else 5125
            primitives.append({"attributes": attributes,
                               "indices": glb.attribute(triangles.reshape(-1), "SCALAR", component),
                               "material": material, "mode": 4})
            if targets:
                primitives[-1]["targets"] = targets
        mesh_index = len(glb.doc["meshes"])
        glb.doc["meshes"].append({"name": name or game_name, "primitives": primitives})
        if target_names:
            glb.doc["meshes"][-1].update(weights=target_weights, extras={"targetNames": target_names})
        node_index = len(glb.doc["nodes"])
        glb.doc["nodes"].append({"name": name or game_name, "mesh": mesh_index,
                                 "extras": {"sourceName": _source_name(mesh_obj)}})
        if _source_path(renderer) in faces.auto_paths and re.search(r"closed|blink|(?:^|[_\s])close(?:$|[_\s])", name + " " + game_name, re.I):
            glb.doc["nodes"][-1]["extras"]["hidden_default"] = True
        glb.doc["scenes"][0]["nodes"].append(node_index)
        if rig is not None and skin is not None:
            rig.place(node_index, renderer, game_object, skin, target_names, target_hashes, target_weights)
        if auto_face:
            faces.added += 1
            from .model_faces import facial_role
            faces.rendered_roles.add(facial_role(game_name, mesh_name, _source_path(renderer) in faces.dynamic_sources))
    return materials


def _to_glb(scene, glb, faces, deadline, rig=None):
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
        try:
            rig.finalize()
            animated = bytes(glb.finish())
            _remaining(deadline)
            return (animated,) + result[1:] + (rig.metadata(),)
        except Exception:
            base_rig["animationWarnings"].append({"code": "animation_unavailable", "message": "Animation loading exceeded its remaining preview budget. The completed model is still shown."})
    return result + (base_rig,)


def _build(paths, deadline, face_context=None, rigged=False):
    """Finish the selected model before spending any time on optional faces.

    The original conversion gets its entire allowance. Face lookup/network is
    capped separately; valid rigged facial geometry uses the global time left.
    Motion gets a fresh bounded wait only after the face result is complete.
    The original total deadline and legacy static-face budget are unchanged.
    Completed GLBs are immutable and survive optional phase failures.
    """
    from .model_faces import FacePlan, FACE_SECONDS
    env = _environment(paths, deadline)
    scene, glb = _Scene(env, deadline), _Glb()
    disabled_faces = FacePlan(scene, paths, None, deadline)
    rig = None
    if rigged:
        from .model_rig import RigBuilder
        try:
            rig = RigBuilder(scene, glb, disabled_faces, paths, deadline)
        except ValueError:
            glb = _Glb()
            scene.warn("rig_unavailable")
    materials = _append_scene(scene, glb, disabled_faces, deadline, rig=rig)
    base = _to_glb(scene, glb, disabled_faces, deadline, rig=rig)
    face_enabled = bool(face_context and face_context.get("enabled", True))
    playable_rig = rig is not None and (rig.skinned > 0 or bool(rig.morphs))
    if not face_context or (not face_enabled and not playable_rig):
        return base

    face_deadline = min(deadline, time.monotonic() + FACE_SECONDS)
    faces, completed, extra = disabled_faces, base, []
    if face_enabled:
        faces = None
        try:
            _remaining(face_deadline)
            scene.deadline = face_deadline
            faces = FacePlan(scene, paths, face_context, face_deadline)
            _remaining(face_deadline)
            extra = faces.resolve()
            _remaining(face_deadline)
            if extra:
                # Lookup/network stays capped at forty seconds. Once a valid
                # face is local, rigged geometry may use the original global
                # conversion time left; motion must wait for its completion.
                render_deadline = deadline if rig is not None else face_deadline
                _paths(paths + extra)
                env = _environment(extra, render_deadline, base_env=env)
                expanded = _Scene(env, render_deadline, trees=scene.trees)
                expanded.stats, expanded.warnings = dict(base[1]), list(scene.warnings)
                if rig is not None:
                    rig.update(expanded, faces, render_deadline)
                _append_scene(expanded, glb, faces, render_deadline, auto_only=True, materials=materials, rig=rig)
                completed = _to_glb(expanded, glb, faces, render_deadline, rig=rig)
                scene = expanded
            else:
                warnings = list(base[2]) + faces.warnings
                if faces.status == "already_present":
                    warnings = [warning for warning in warnings if warning["code"] != "facial_assets_missing"]
                completed = (base[0], base[1], warnings, faces.metadata()) + base[4:]
        except Exception:
            if faces is None:
                faces = FacePlan(scene, paths, None, face_deadline)
                faces.enabled = True
            faces.added = 0
            faces.status = "unavailable"
            faces.warn("face_source_unavailable", "The original face could not be opened. The costume is still shown.")
            return (base[0], base[1], list(base[2]) + faces.warnings, faces.metadata()) + base[4:]

    # Motion is independent of automatic facial completion. Unsupported/static
    # rigs cannot use discovered tracks; errors must not rewrite face status.
    if rig is None or not (rig.skinned > 0 or rig.morphs):
        return completed
    if rig.clips:
        return completed
    motion_deadline = min(deadline, time.monotonic() + FACE_SECONDS)
    try:
        _remaining(motion_deadline)
        from .model_animation import discover_animation_paths
        animation_paths = discover_animation_paths(paths + extra, face_context, faces.owner or rig.owner, motion_deadline)
        _remaining(motion_deadline)
        if not animation_paths:
            return completed
        _paths(paths + extra + animation_paths)
        env = _environment(animation_paths, motion_deadline, base_env=env)
        expanded = _Scene(env, motion_deadline, trees=scene.trees)
        expanded.stats, expanded.warnings = dict(completed[1]), list(scene.warnings)
        rig.update(expanded, faces, motion_deadline)
        return _to_glb(expanded, glb, faces, motion_deadline, rig=rig)
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


def prepare(paths, *, face_context=None, rigged=False):
    """Convert selected, already-jailed bundle paths and create a short-lived GLB."""
    if not isinstance(rigged, bool):
        raise ModelViewerError("The rigged preview setting must be true or false.")
    paths = _paths(paths)
    if not _BUILD_LOCK.acquire(timeout=1):
        raise ViewerBusyError("Another model is opening. Wait for it to finish and try again.")
    try:
        deadline = time.monotonic() + BUILD_SECONDS
        try:
            # Keep the original internal call shape for callers/tests that do
            # not enable automatic discovery.
            built = (_build(paths, deadline, face_context, rigged=True) if rigged
                     else _build(paths, deadline, face_context) if face_context is not None else _build(paths, deadline))
            data, stats, warnings = built[:3]
            faces = built[3] if len(built) > 3 else {"enabled": False, "status": "not_needed", "added": 0, "characters": []}
            rig = built[4] if len(built) > 4 else {"enabled": bool(rigged), "available": False}
        except ModelViewerError:
            raise
        except Exception as error:
            raise ModelViewerError("This model could not be opened. Its format or linked assets may be unsupported.") from error
        token = secrets.token_hex(16)
        with _CACHE_LOCK:
            now = time.monotonic()
            _SESSIONS[token] = (now + CACHE_SECONDS, data)
            _prune(now)
        return {"id": token, "url": f"/api/viewer/model/{token}.glb",
                "source_names": [os.path.basename(path) for path in paths],
                "stats": dict(stats), "warnings": warnings, "faces": faces, "rig": rig}
    finally:
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
