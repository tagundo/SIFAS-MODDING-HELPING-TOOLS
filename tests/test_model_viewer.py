"""GLB interoperability, source preservation and bounded viewer regressions.

The tiny Unity fixtures are original generated triangle scenes, not game data.
Set SIFAS_VIEWER_TEST_BUNDLE for additional actual-character invariants.
"""
import copy
import hashlib
import io
import json
import lzma
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from webtools.core import model_viewer as viewer


FIXTURES = Path(__file__).parent / "fixtures"


def unpack_glb(data):
    magic, version, length = struct.unpack_from("<4sII", data)
    assert (magic, version, length) == (b"glTF", 2, len(data))
    count, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON" and count % 4 == 0
    doc = json.loads(data[20:20 + count])
    size, kind = struct.unpack_from("<I4s", data, 20 + count)
    assert kind == b"BIN\0" and size % 4 == 0
    binary = data[28 + count:]
    assert len(binary) == size == doc["buffers"][0]["byteLength"]
    for item in doc["bufferViews"]:
        assert item.get("byteOffset", 0) % 4 == 0
        assert 0 <= item.get("byteOffset", 0) <= len(binary)
        assert item.get("byteOffset", 0) + item["byteLength"] <= len(binary)
    assert "uri" not in doc["buffers"][0]
    assert all("uri" not in item for item in doc.get("images", []))
    return doc, binary


def attribute(doc, binary, index):
    item = doc["accessors"][index]
    view = doc["bufferViews"][item["bufferView"]]
    dimension = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[item["type"]]
    char = {5126: "f", 5123: "H", 5125: "I"}[item["componentType"]]
    offset = view.get("byteOffset", 0) + item.get("byteOffset", 0)
    return list(struct.iter_unpack("<" + char * dimension,
                                 binary[offset:offset + item["count"] * dimension * struct.calcsize(char)]))


def bundle_header(unpacked, packed=0, offset=0, flags=2):
    info = (bytes(16) + struct.pack(">iIIHiqqI", 1, unpacked, packed, flags, 1, offset, 0, 0) + b"model\0")
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"2018.4.0f1\0rev\0"
    header = struct.pack(">QIII", len(prefix) + 20 + len(info) + packed, len(info), len(info), 64)
    return prefix + header + info + bytes(packed)


def unity_bundle(entries):
    payload = b"".join(value for _, value in entries)
    info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
    offset = 0
    for name, value in entries:
        info += struct.pack(">qqI", offset, len(value), 0) + name.encode() + b"\0"
        offset += len(value)
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + b"2019.4.0f1\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 64) + info + payload


def lzma_bundle(payload, *, declared_size=None, version=6, info_at_end=False, info_lzma=False, mixed=False):
    """Original test container, including Unity's raw LZMA properties prefix."""
    def compress(value):
        return struct.pack("<BI", 0x5D, 1 << 20) + lzma.compress(value, format=lzma.FORMAT_RAW, filters=[{
            "id": lzma.FILTER_LZMA1, "dict_size": 1 << 20, "lc": 3, "lp": 0, "pb": 2}])
    size = len(payload) if declared_size is None else declared_size
    if mixed:
        split = len(payload) // 2
        blocks = [(split, compress(payload[:split]), 65), (size - split, payload[split:], 64)]
    else:
        blocks = [(size, compress(payload), 65)]
    info = bytes(16) + struct.pack(">i", len(blocks))
    info += b"".join(struct.pack(">IIH", count, len(value), flags) for count, value, flags in blocks)
    info += struct.pack(">iqqI", 1, 0, size, 0) + b"fixture.assets\0"
    packed_info = compress(info) if info_lzma else info
    prefix = b"UnityFS\0" + struct.pack(">I", version) + b"5.x.x\0" + b"2018.4.23f1\0"
    padding = bytes(-(len(prefix) + 20) % 16) if version >= 7 else b""
    packed_data = b"".join(value for _, value, _ in blocks)
    flags = 64 | (128 if info_at_end else 0) | (1 if info_lzma else 0)
    length = len(prefix) + 20 + len(padding) + len(packed_info) + len(packed_data)
    body = packed_data + packed_info if info_at_end else packed_info + packed_data
    return prefix + struct.pack(">QIII", length, len(packed_info), len(info), flags) + padding + body


class SessionTests(unittest.TestCase):
    def setUp(self):
        viewer._SESSIONS.clear()

    def tearDown(self):
        viewer._SESSIONS.clear()

    def test_opaque_ids_and_cache_entry_byte_limits(self):
        path = str(FIXTURES / "viewer_triangle.unity")
        with patch.object(viewer, "_build", return_value=(b"1234", {}, [])), \
                patch.object(viewer, "MAX_CACHE_ENTRIES", 2), patch.object(viewer, "MAX_CACHE_BYTES", 8):
            first = viewer.prepare([path])
            second = viewer.prepare([path])
            self.assertRegex(first["id"], "^[0-9a-f]{32}$")
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(viewer.get_model(first["id"]), b"1234")
            third = viewer.prepare([path])
            self.assertIsNone(viewer.get_model(second["id"]))
            self.assertEqual(viewer.get_model(first["id"]), b"1234")
            self.assertEqual(viewer.get_model(third["id"]), b"1234")
            self.assertEqual(first["source_names"], ["viewer_triangle.unity"])

    def test_session_expiry_and_malformed_ids(self):
        token = "a" * 32
        viewer._SESSIONS[token] = (time.monotonic() - 1, b"expired")
        self.assertIsNone(viewer.get_model(token))
        for invalid in ("../passwd", "A" * 32, "0" * 31, None, 12):
            self.assertIsNone(viewer.get_model(invalid))

    def test_busy_builder_rejects_without_entering_exporter(self):
        with patch.object(viewer, "_BUILD_LOCK") as lock, patch.object(viewer, "_build") as build:
            lock.acquire.return_value = False
            with self.assertRaises(viewer.ViewerBusyError):
                viewer.prepare([str(FIXTURES / "viewer_triangle.unity")])
            build.assert_not_called()
            lock.release.assert_not_called()

    def test_failed_builder_releases_lock_and_does_not_create_session(self):
        with patch.object(viewer, "_build", side_effect=viewer.ModelViewerError("bad mesh")):
            with self.assertRaisesRegex(viewer.ModelViewerError, "bad mesh"):
                viewer.prepare([str(FIXTURES / "viewer_triangle.unity")])
        self.assertFalse(viewer._BUILD_LOCK.locked())
        self.assertFalse(viewer._SESSIONS)


class InputTests(unittest.TestCase):
    def test_rejects_empty_non_paths_missing_and_directories(self):
        for value in (None, "model.unity", [], [None], [""], ["/no/such/model.unity"], [str(FIXTURES)]):
            with self.subTest(value=value), self.assertRaises(viewer.ModelViewerError):
                viewer.prepare(value)

    def test_source_size_limit_precedes_loader(self):
        with patch.object(viewer, "MAX_SOURCE_BYTES", 10), patch.object(viewer, "_build") as build:
            with self.assertRaisesRegex(viewer.ModelViewerError, "too large"):
                viewer.prepare([str(FIXTURES / "viewer_triangle.unity")])
            build.assert_not_called()

    def test_headers_reject_apk_truncation_and_decompression_bombs(self):
        for data in (b"PK\x03\x04not a model", b"UnityFS\0", bytes(100)):
            with self.subTest(data=data[:12]), self.assertRaises(viewer.ModelViewerError):
                viewer._preflight_bundle(data)
        with self.assertRaisesRegex(viewer.ModelViewerError, "memory limit"):
            viewer._preflight_bundle(bundle_header(viewer.MAX_UNPACKED_BYTES + 1))
        with self.assertRaisesRegex(viewer.ModelViewerError, "invalid embedded"):
            viewer._preflight_bundle(bundle_header(32, offset=-1))

    def test_declared_raw_asset_size_must_match_supplied_bytes(self):
        data = bytearray((FIXTURES / "viewer_triangle.unity").read_bytes())
        struct.pack_into(">I", data, 4, len(data) + 1)
        with self.assertRaisesRegex(viewer.ModelViewerError, "extracted Unity"):
            viewer._preflight_bundle(data)

    def test_lzma_rejects_oversized_dictionary_before_decoder_allocation(self):
        data = bytearray(lzma_bundle(b"payload"))
        _, layout = viewer._preflight_bundle(data, _with_layout=True)
        struct.pack_into("<I", data, layout["payload"] + 1, 64 * 1024 * 1024 + 1)
        with patch.object(lzma, "LZMADecompressor") as decoder:
            with self.assertRaisesRegex(viewer.ModelViewerError, "memory limit"):
                viewer._bounded_bundle(data, layout, time.monotonic() + 10)
        decoder.assert_not_called()


    def test_lzma_output_cannot_expand_beyond_declared_block_size(self):
        data = lzma_bundle(b"x" * 4096, declared_size=64)
        _, layout = viewer._preflight_bundle(data, _with_layout=True)
        decoder = lzma.LZMADecompressor
        limits = []

        class CappedDecoder:
            def __init__(self, *args, **kwargs):
                self.decoder = decoder(*args, **kwargs)

            def decompress(self, data, max_length):
                limits.append(max_length)
                return self.decoder.decompress(data, max_length=max_length)

        with patch.object(lzma, "LZMADecompressor", CappedDecoder):
            with self.assertRaisesRegex(viewer.ModelViewerError, "invalid block information"):
                viewer._bounded_bundle(data, layout, time.monotonic() + 10)
        self.assertEqual(limits, [65])

    def test_truncated_lzma_payload_is_rejected_before_data_decode(self):
        data = lzma_bundle(b"payload")[:-1]
        with patch.object(lzma, "LZMADecompressor") as decoder:
            with self.assertRaisesRegex(viewer.ModelViewerError, "truncated"):
                viewer._preflight_bundle(data)
        decoder.assert_not_called()


class ShaderMaterialTests(unittest.TestCase):
    def material(self, *, dependency=None, resolved=None, fingerprint=True, external_cab="cab-9382ea964987eceddd567506a3b21312", shader_path_id=8291131735116688333):
        asset = SimpleNamespace(externals=[SimpleNamespace(name=external_cab)])
        material = SimpleNamespace(assets_file=asset, path_id=1)
        shader = SimpleNamespace(assets_file=asset, path_id=2, type=SimpleNamespace(name="Shader")) if resolved is not None else None
        bundle = SimpleNamespace(assets_file=asset, path_id=3, type=SimpleNamespace(name="AssetBundle"))
        color = {"r": .5, "g": .4, "b": .3, "a": .8}
        colors = [("_Color", color)]
        if fingerprint:
            colors.extend((name, dict(r=1, g=1, b=1, a=1)) for name in ("_TintColor", "_AmbientColor", "_RimlightColor"))
        tree = {"m_Name": "Synthetic material", "m_Shader": {"m_FileID": 1, "m_PathID": shader_path_id}, "m_SavedProperties": {"m_Colors": colors}}

        def read(obj):
            if obj is material:
                return tree
            if obj is bundle:
                return {"m_Dependencies": [dependency] if dependency else []}
            if obj is shader:
                return {"m_ParsedForm": {"m_Name": resolved}}
            raise AssertionError("Unknown source")

        scene = SimpleNamespace(tree=read, env=SimpleNamespace(objects=[bundle]), stats={"materials": 0})
        glb = viewer._Glb()
        with patch.object(viewer, "_ref", return_value=shader), patch.object(viewer, "_source_path", return_value="selected.unity"):
            viewer._Materials(scene, glb).material(material)
        return glb.doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]

    def test_known_as_member_ignores_unused_generic_color(self):
        self.assertEqual(self.material(resolved="AS/Member"), [1, 1, 1, 1])
        self.assertEqual(self.material(resolved="Hidden/AS/Member/Main"), [1, 1, 1, 1])
        self.assertEqual(self.material(dependency="asmember.shader.unity3d"), [1, 1, 1, 1])

    def test_unknown_generic_and_other_resolved_shaders_preserve_color(self):
        expected = [.5, .4, .3, .8]
        self.assertEqual(self.material(), expected)
        self.assertEqual(self.material(resolved="Standard", dependency="asmember.shader.unity3d"), expected)
        self.assertEqual(self.material(dependency="asmember.shader.unity3d", fingerprint=False), expected)
        self.assertEqual(self.material(dependency="other-asmember.shader.unity3d"), expected)
        self.assertEqual(self.material(dependency="asmember.shader.unity3d", external_cab="unknown-standard-shader"), expected)
        self.assertEqual(self.material(dependency="asmember.shader.unity3d", shader_path_id=123), expected)


class RealUnityFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
            import numpy
            from PIL import Image
        except ImportError as error:
            raise unittest.SkipTest("UnityPy, numpy and Pillow are needed for real export checks") from error
        cls.UnityPy, cls.np, cls.Image = UnityPy, numpy, Image

    def export(self, path):
        result = viewer.prepare([str(path)])
        data = viewer.get_model(result["id"])
        self.assertIsNotNone(data)
        return result, *unpack_glb(data)

    def changed_fixture(self, callback, source="viewer_triangle.unity"):
        env = self.UnityPy.load((FIXTURES / source).read_bytes())
        callback(env)
        return next(iter(env.files.values())).save()

    def test_genuine_renderer_triangle_is_self_contained_and_source_unchanged(self):
        file = FIXTURES / "viewer_triangle.unity"
        original = hashlib.sha256(file.read_bytes()).hexdigest()
        meta, doc, binary = self.export(file)
        self.assertEqual(meta["stats"], {"meshes": 1, "vertices": 3, "triangles": 1,
                                         "materials": 1, "textures": 0})
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), original)
        primitive = doc["meshes"][0]["primitives"][0]
        points = self.np.array(attribute(doc, binary, primitive["attributes"]["POSITION"]))
        normals = self.np.array(attribute(doc, binary, primitive["attributes"]["NORMAL"]))
        self.np.testing.assert_allclose(points, [[.6, 0, 0], [-.6, 0, 0], [0, 1.2, 0]], atol=1e-7)
        self.np.testing.assert_allclose(normals, [[0, 0, 1]] * 3)
        self.assertEqual(attribute(doc, binary, primitive["indices"]), [(0,), (2,), (1,)])
        self.assertEqual(attribute(doc, binary, primitive["attributes"]["TEXCOORD_0"]), [(0., 1.), (1., 1.), (.5, 0.)])
        triangle = points[[0, 2, 1]]
        self.assertGreater(self.np.dot(self.np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]), normals[0]), 0)
        self.assertNotIn("COLOR_0", primitive["attributes"])

    def test_lzma_original_bytes_are_preserved_and_unbounded_unity_decoder_is_unused(self):
        from UnityPy.helpers import CompressionHelper
        original = (FIXTURES / "viewer_textured_triangle.unity").read_bytes()
        for settings in ({}, {"version": 7, "info_at_end": True, "info_lzma": True}, {"mixed": True}):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "face.unity"
                data = lzma_bundle(original, **settings)
                source.write_bytes(data)
                unpacked, layout = viewer._preflight_bundle(data, _with_layout=True)
                normalized = viewer._bounded_bundle(data, layout, time.monotonic() + 10)
                _, decoded = viewer._preflight_bundle(normalized, _with_layout=True)
                self.assertEqual(unpacked, len(original))
                self.assertEqual(normalized[decoded["payload"]:], original)
                with patch.object(CompressionHelper, "decompress_lzma", side_effect=AssertionError("Unbounded UnityPy LZMA is forbidden")):
                    metadata, doc, binary = self.export(source)
                self.assertEqual(metadata["stats"]["meshes"], 1)
                self.assertEqual(metadata["stats"]["textures"], 1)
                self.assertEqual(source.read_bytes(), data)

    def test_parent_rotation_scale_and_translation_are_applied_once(self):
        def change(env):
            transform = next(obj for obj in env.objects if obj.type.name == "Transform")
            tree = transform.read_typetree()
            tree["m_LocalPosition"] = dict(x=2., y=3., z=4.)
            tree["m_LocalRotation"] = dict(x=0., y=0., z=math.sqrt(.5), w=math.sqrt(.5))
            tree["m_LocalScale"] = dict(x=2., y=1., z=1.)
            transform.save_typetree(tree)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transformed.unity"
            path.write_bytes(self.changed_fixture(change))
            _, doc, binary = self.export(path)
        primitive = doc["meshes"][0]["primitives"][0]
        points = attribute(doc, binary, primitive["attributes"]["POSITION"])
        self.np.testing.assert_allclose(points, [[-2, 1.8, 4], [-2, 4.2, 4], [-.8, 3, 4]], atol=1e-6)

    def test_hidden_renderer_does_not_reappear_as_orphan_mesh(self):
        def change(env):
            obj = next(obj for obj in env.objects if obj.type.name == "MeshRenderer")
            tree = obj.read_typetree()
            tree["m_Enabled"] = False
            obj.save_typetree(tree)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hidden.unity"
            path.write_bytes(self.changed_fixture(change))
            with self.assertRaisesRegex(viewer.ModelViewerError, "No visible"):
                viewer.prepare([str(path)])

    def test_texture_png_preserves_original_pixels_dimensions_and_uv_orientation(self):
        meta, doc, binary = self.export(FIXTURES / "viewer_textured_triangle.unity")
        self.assertEqual(meta["stats"]["textures"], 1)
        image = doc["images"][0]
        view = doc["bufferViews"][image["bufferView"]]
        png = binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
        with self.Image.open(io.BytesIO(png)) as picture:
            picture.load()
            self.assertEqual(picture.size, (2, 2))
            self.assertEqual([picture.getpixel((x, y)) for y in range(2) for x in range(2)],
                             [(0, 0, 255, 255), (255, 255, 255, 255),
                              (255, 0, 0, 255), (0, 255, 0, 255)])
        material = doc["materials"][0]
        self.assertIn("KHR_materials_unlit", material["extensions"])
        self.assertNotIn("alphaMode", material)  # _Cutoff alone is not alpha testing

    def test_material_uv_scale_offset_are_converted_without_resampling(self):
        def change(env):
            obj = next(obj for obj in env.objects if obj.type.name == "Material")
            tree = obj.read_typetree()
            main = dict(tree["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]
            main["m_Scale"] = dict(x=2., y=.5)
            main["m_Offset"] = dict(x=.25, y=.1)
            obj.save_typetree(tree)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiled.unity"
            path.write_bytes(self.changed_fixture(change, "viewer_textured_triangle.unity"))
            _, doc, binary = self.export(path)
        tex = doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
        transform = tex["extensions"]["KHR_texture_transform"]
        self.assertEqual(transform["scale"], [2., .5])
        self.np.testing.assert_allclose(transform["offset"], [.25, .4], atol=1e-7)
        self.assertIn("KHR_texture_transform", doc["extensionsUsed"])

    def test_internal_only_loader_cannot_open_unselected_dependencies(self):
        env = viewer._environment([str(FIXTURES / "viewer_triangle.unity")], time.monotonic() + 10)
        with patch.object(env.fs, "open", side_effect=AssertionError("No filesystem dependency load")):
            with self.assertRaises(FileNotFoundError):
                env.find_file("/etc/passwd")
            with self.assertRaises(FileNotFoundError):
                env.load_file("/etc/passwd")
            with self.assertRaises(FileNotFoundError):
                env.assets[0].environment.find_file("/etc/passwd")

    def test_same_cab_ids_keep_each_selected_bundles_own_streamed_texture(self):
        def stream_texture(env):
            texture = next(obj for obj in env.objects if obj.type.name == "Texture2D")
            tree = texture.read_typetree()
            tree["image data"] = b""
            tree["m_StreamData"] = {"offset": 0, "size": 16, "path": "archive:/CAB-preview/CAB-preview.resS"}
            texture.save_typetree(tree)
        serialized = self.changed_fixture(stream_texture, "viewer_textured_triangle.unity")
        first_pixels = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
        second_pixels = bytes([0, 255, 255, 255]) * 4
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / "original.unity", Path(directory) / "baked.unity"]
            for path, pixels in zip(paths, [first_pixels, second_pixels]):
                path.write_bytes(unity_bundle([("CAB-preview", serialized), ("CAB-preview.resS", pixels)]))
            meta = viewer.prepare([str(path) for path in paths])
            doc, binary = unpack_glb(viewer.get_model(meta["id"]))
        self.assertEqual(meta["stats"]["meshes"], 2)
        self.assertEqual(meta["stats"]["textures"], 2)
        self.assertEqual([item["extras"]["sourceName"] for item in doc["nodes"]], ["original.unity", "baked.unity"])
        pixels = []
        for image in doc["images"]:
            view = doc["bufferViews"][image["bufferView"]]
            data = binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
            with self.Image.open(io.BytesIO(data)) as picture:
                pixels.append(picture.getpixel((0, 0)))
        self.assertEqual(pixels, [(0, 0, 255, 255), (0, 255, 255, 255)])

    def test_malformed_mesh_counts_are_rejected_before_meshhandler(self):
        from UnityPy.helpers import MeshHelper
        def mesh(**changes):
            value = SimpleNamespace(m_VertexData=SimpleNamespace(m_VertexCount=3),
                                    m_CompressedMesh=None, m_IndexFormat=0, m_Use16BitIndices=None,
                                    m_IndexBuffer=struct.pack("<3H", 0, 1, 2),
                                    m_SubMeshes=[SimpleNamespace(firstByte=0, indexCount=3, topology=0)])
            value.__dict__.update(changes)
            return value
        malformed = [
            mesh(m_VertexData=SimpleNamespace(m_VertexCount=viewer.MAX_VERTICES + 1)),
            mesh(m_SubMeshes=[SimpleNamespace(firstByte=0, indexCount=2**31 - 1, topology=0)]),
            mesh(m_SubMeshes=[SimpleNamespace(firstByte=2**31, indexCount=3, topology=0)]),
            mesh(m_SubMeshes=[SimpleNamespace(firstByte=0, indexCount=4, topology=0)]),
            mesh(m_IndexFormat=7),
            mesh(m_CompressedMesh=SimpleNamespace(m_Vertices=SimpleNamespace(m_NumItems=0),
                m_Triangles=SimpleNamespace(m_NumItems=viewer.MAX_TRIANGLES * 3 + 1))),
            mesh(m_CompressedMesh=SimpleNamespace(m_Vertices=SimpleNamespace(m_NumItems=0),
                m_UV=SimpleNamespace(m_NumItems=2**31))),
        ]
        for value in malformed:
            with self.subTest(value=value), patch.object(MeshHelper, "MeshHandler") as handler:
                with self.assertRaises(viewer.ModelViewerError):
                    viewer._geometry(SimpleNamespace(read=lambda: value), self.np.eye(4))
                handler.assert_not_called()


class ActualCharacterTests(unittest.TestCase):
    export = RealUnityFixtureTests.export

    @classmethod
    def setUpClass(cls):
        RealUnityFixtureTests.setUpClass.__func__(cls)
        raw = os.environ.get("SIFAS_VIEWER_TEST_BUNDLE")
        if not raw or not Path(raw).is_file():
            raise unittest.SkipTest("Set SIFAS_VIEWER_TEST_BUNDLE for actual-character checks")
        cls.path = Path(raw)

    def test_actual_character_geometry_texture_and_missing_face_warning(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        meta, doc, binary = self.export(self.path)
        self.assertEqual(meta["stats"]["meshes"], 3)
        self.assertEqual(meta["stats"]["vertices"], 5893)
        self.assertEqual(meta["stats"]["triangles"], 8933)
        self.assertEqual(meta["stats"]["textures"], 2 if os.environ.get("ASTCENC_BIN") else 1)
        self.assertIn("facial_assets_missing", [item["code"] for item in meta["warnings"]])
        self.assertFalse(any("shadow" in item["name"].lower() for item in doc["nodes"]))
        self.assertEqual({item["name"] for item in doc["nodes"]}, {"Face", "Hair", "body_chika"})
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                self.assertNotIn("COLOR_0", primitive["attributes"])
                normals = self.np.asarray(attribute(doc, binary, primitive["attributes"]["NORMAL"]))
                self.np.testing.assert_allclose(self.np.linalg.norm(normals, axis=1), 1, atol=1e-6)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_baked_geometry_remains_independent_when_original_and_result_are_opened_together(self):
        raw = os.environ.get("SIFAS_VIEWER_TEST_BAKED")
        if not raw or not Path(raw).is_file():
            self.skipTest("Set SIFAS_VIEWER_TEST_BAKED for actual saved-model comparisons")
        from UnityPy.helpers.MeshHelper import MeshHandler
        baked = Path(raw)
        meta = viewer.prepare([str(self.path), str(baked)])
        doc, binary = unpack_glb(viewer.get_model(meta["id"]))
        self.assertEqual(meta["stats"]["meshes"], 6)
        bodies = [node for node in doc["nodes"] if node["name"] == "body_chika"]
        self.assertEqual(len(bodies), 2)
        exported = []
        for path, node in zip([self.path, baked], bodies):
            obj = next(obj for obj in self.UnityPy.load(str(path)).objects
                       if obj.type.name == "Mesh" and obj.read_typetree()["m_Name"] == "body_chika")
            handler = MeshHandler(obj.read())
            handler.process()
            expected = self.np.asarray(handler.m_Vertices) * [-1, 1, 1]
            primitive = doc["meshes"][node["mesh"]]["primitives"][0]
            positions = self.np.asarray(attribute(doc, binary, primitive["attributes"]["POSITION"]))
            self.np.testing.assert_allclose(positions, expected, rtol=0, atol=1e-7)
            self.assertEqual(node["extras"]["sourceName"], path.name)
            exported.append(positions)
        self.assertGreater(self.np.max(self.np.abs(exported[0] - exported[1])), .001)


if __name__ == "__main__":
    unittest.main()
