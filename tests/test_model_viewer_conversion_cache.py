"""Immutable preview conversions: fresh source pixels and fresh editing state."""
import hashlib
import io
from pathlib import Path
import time
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from webtools.core import model_viewer as viewer
from test_model_viewer import lzma_bundle


FIXTURES = Path(__file__).parent / "fixtures"


def raw_texture(red=20):
    data = bytes([red, 40, 60, 255] * 4)
    texture = SimpleNamespace(m_Width=2, m_Height=2, m_TextureFormat=4,
                              m_ImageCount=1, m_TextureDimension=2,
                              image_data=data, m_StreamData=None, object_reader=None)
    texture.get_image_data = lambda: texture.image_data
    return texture


class ConversionCacheTests(unittest.TestCase):
    def setUp(self):
        viewer._TEXTURE_PNGS.clear()
        viewer._NORMALIZED_BUNDLES.clear()
        viewer._SESSIONS.clear()
        viewer._REQUEST_STATE.reimport = False

    def tearDown(self):
        self.setUp()

    def test_pixels_are_immutable_content_addressed_and_source_changes_are_immediate(self):
        source = raw_texture()
        original = source.image_data
        with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            first = viewer._texture_png(source, time.monotonic() + 10)
            # A new ObjectReader/ZIP extraction with the same pixel bytes reuses
            # only encoded PNG bytes, not any material, image or sampler object.
            again = viewer._texture_png(raw_texture(), time.monotonic() + 10)
            self.assertIsInstance(first, bytes)
            self.assertEqual(first, again)
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(source.image_data, original)
            source.image_data = bytes([120, 40, 60, 255] * 4)
            changed = viewer._texture_png(source, time.monotonic() + 10)
            self.assertEqual(decode.call_count, 2)
            self.assertNotEqual(first, changed)
            with Image.open(io.BytesIO(changed)) as image:
                self.assertEqual(image.getpixel((0, 0)), (120, 40, 60, 255))

    def test_reimport_bypasses_cache_then_retains_fresh_successful_bytes(self):
        source = raw_texture()
        with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            first = viewer._texture_png(source, time.monotonic() + 10)
            viewer._REQUEST_STATE.reimport = True
            refreshed = viewer._texture_png(source, time.monotonic() + 10)
            self.assertEqual(decode.call_count, 2)
            viewer._REQUEST_STATE.reimport = False
            self.assertEqual(viewer._texture_png(source, time.monotonic() + 10), refreshed)
            self.assertEqual(decode.call_count, 2)
            self.assertEqual(first, refreshed)

    def test_source_shape_format_and_decoder_identity_are_part_of_texture_key(self):
        source = raw_texture()
        with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            square = viewer._texture_png(source, time.monotonic() + 10)
            source.m_Width, source.m_Height = 4, 1
            line = viewer._texture_png(source, time.monotonic() + 10)
            self.assertNotEqual(square, line)
            self.assertEqual(decode.call_count, 2)
            source.m_TextureFormat = 5  # ARGB32: same encoded bytes, other pixels.
            argb = viewer._texture_png(source, time.monotonic() + 10)
            self.assertNotEqual(line, argb)
            self.assertEqual(decode.call_count, 3)
        with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as replaced:
            self.assertEqual(viewer._texture_png(source, time.monotonic() + 10), argb)
            self.assertEqual(replaced.call_count, 1)

    def test_expired_and_evicted_textures_redecode_without_unbounded_memory(self):
        with patch.object(viewer, "CACHE_SECONDS", 0), \
                patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            viewer._texture_png(raw_texture(), time.monotonic() + 10)
            viewer._texture_png(raw_texture(), time.monotonic() + 10)
            self.assertEqual(decode.call_count, 2)
        viewer._TEXTURE_PNGS.clear()
        with patch.object(viewer, "MAX_TEXTURE_CACHE_BYTES", 120), \
                patch.object(viewer, "MAX_TEXTURE_CACHE_ENTRIES", 2), \
                patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            for color in (20, 30, 40, 50, 20):
                viewer._texture_png(raw_texture(color), time.monotonic() + 10)
            self.assertEqual(decode.call_count, 5)
            self.assertLessEqual(len(viewer._TEXTURE_PNGS), 2)
            self.assertLessEqual(sum(len(value[1]) for value in viewer._TEXTURE_PNGS.values()), 120)

    def test_invalid_or_failed_decodes_do_not_become_successful_cached_images(self):
        source = raw_texture()
        with patch.object(viewer.decode, "_android_image", side_effect=ValueError("decoder unavailable")) as decode:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "decoder unavailable"):
                    viewer._texture_png(source, time.monotonic() + 10)
            self.assertEqual(decode.call_count, 2)
            self.assertFalse(viewer._TEXTURE_PNGS)
        viewer._texture_png(source, time.monotonic() + 10)
        source.m_Width = 100000
        with self.assertRaisesRegex(ValueError, "dimensions"):
            viewer._texture_png(source, time.monotonic() + 10)

    def test_unsupported_texture_layouts_do_not_read_pixels_to_construct_cache_keys(self):
        from UnityPy.enums import TextureFormat
        for changes in ({"m_TextureFormat": int(TextureFormat.ETC2_RGBA8)}, {"m_ImageCount": 2},
                        {"m_TextureDimension": 3}, {"object_reader": SimpleNamespace(platform=11)},
                        {"object_reader": SimpleNamespace(platform=38), "m_PlatformBlob": [1]}):
            texture = raw_texture()
            texture.__dict__.update(changes)
            with self.subTest(changes=changes), patch.object(texture, "get_image_data", side_effect=AssertionError("Must not read unsupported pixels")) as read:
                with self.assertRaises(ValueError):
                    viewer._texture_png(texture, time.monotonic() + 10)
                read.assert_not_called()

    def test_normalization_is_immutable_source_bound_and_reimportable(self):
        source = lzma_bundle(b"original source bytes")
        _, layout = viewer._preflight_bundle(source, _with_layout=True)
        with patch.object(viewer, "_bounded_bundle", wraps=viewer._bounded_bundle) as normalize:
            first = viewer._normalized_bundle(source, layout, time.monotonic() + 10)
            self.assertEqual(viewer._normalized_bundle(bytes(source), layout, time.monotonic() + 10), first)
            self.assertEqual(normalize.call_count, 1)
            changed = lzma_bundle(b"modified source bytes")
            _, changed_layout = viewer._preflight_bundle(changed, _with_layout=True)
            self.assertNotEqual(viewer._normalized_bundle(changed, changed_layout, time.monotonic() + 10), first)
            self.assertEqual(normalize.call_count, 2)
            viewer._REQUEST_STATE.reimport = True
            self.assertEqual(viewer._normalized_bundle(source, layout, time.monotonic() + 10), first)
            self.assertEqual(normalize.call_count, 3)
            self.assertTrue(source.startswith(b"UnityFS\0"))

    def test_repeat_prepare_rebuilds_fresh_rig_metadata_and_tokens(self):
        source = FIXTURES / "viewer_rig.unity"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        context = {"enabled": False, "allow_download": False}
        with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            first = viewer.prepare([str(source)], face_context=context, rigged=True)
            count = decode.call_count
            self.assertGreater(count, 0)
            first_name = first["rig"]["bones"][0]["name"]
            first["rig"]["bones"][0]["name"] = "UNSAVED PREVIEW CHANGE"
            second = viewer.prepare([str(source)], face_context=context, rigged=True)
            self.assertEqual(decode.call_count, count)
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(second["rig"]["bones"][0]["name"], first_name)
            self.assertEqual(first["stats"], second["stats"])
            self.assertEqual(viewer.get_model(first["id"]), viewer.get_model(second["id"]))
            third = viewer.prepare([str(source)], face_context=context, rigged=True, reimport=True)
            self.assertGreater(decode.call_count, count)
            self.assertNotEqual(second["id"], third["id"])
            self.assertEqual(second["rig"], third["rig"])
            self.assertEqual(viewer.get_model(second["id"]), viewer.get_model(third["id"]))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        for invalid in (1, "true", None):
            with self.subTest(reimport=invalid), self.assertRaisesRegex(viewer.ModelViewerError, "Reimport"):
                viewer.prepare([str(source)], reimport=invalid)
        self.assertFalse(viewer._REQUEST_STATE.reimport)

    def test_zip_temporary_paths_share_pixels_but_keep_current_clip_source_identity(self):
        from webtools.core.viewer_archive import expand_inputs
        from webtools.core.model_motion import source_id
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "costume.zip"
            with zipfile.ZipFile(archive, "w") as target:
                target.writestr("body.unity", (FIXTURES / "viewer_rig.unity").read_bytes())
            results, temporary_paths = [], []
            with patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
                for _ in range(2):
                    with expand_inputs([str(archive)], root / "cache") as expanded:
                        path = expanded.paths[0]
                        temporary_paths.append(path)
                        result = viewer.prepare(expanded.paths, face_context={"enabled": False, "allow_download": False,
                                                "origins": expanded.origins}, rigged=True)
                        selected = [clip for clip in result["rig"]["clips"] if clip.get("userSelected")]
                        self.assertTrue(selected)
                        self.assertTrue(all(clip["sourceId"] == source_id(path) for clip in selected))
                        results.append(result)
                self.assertEqual(decode.call_count, 1)
            self.assertNotEqual(temporary_paths[0], temporary_paths[1])
            self.assertFalse(Path(temporary_paths[0]).exists())
            self.assertFalse(Path(temporary_paths[1]).exists())
            self.assertNotEqual(results[0]["id"], results[1]["id"])
            self.assertEqual(results[0]["stats"], results[1]["stats"])

    def test_mip_workers_overlap_at_most_two_and_register_exact_pixels_in_order(self):
        asset = object()
        textures, objects = [], []
        for index, size in enumerate((4, 2, 1)):
            texture = raw_texture(20 + index * 50)
            texture.m_Width = texture.m_Height = size
            texture.image_data = bytes([20 + index * 50, 40, 60, 255] * size * size)
            texture.m_Name = "slice-" + str(index)
            textures.append(texture)
            objects.append(SimpleNamespace(assets_file=asset, path_id=index, read=lambda value=texture: value))
        before = [texture.image_data for texture in textures]
        scene = SimpleNamespace(deadline=time.monotonic() + 10, stats={"textures": 0})
        glb = viewer._Glb()
        material = viewer._Materials(scene, glb)
        real_decode = viewer.decode._android_image
        lock, barrier = threading.Lock(), threading.Barrier(2)
        active = maximum = calls = 0

        def decode(*args):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                calls += 1
                ordinal = calls
                maximum = max(maximum, active)
            try:
                if ordinal <= 2:
                    barrier.wait(timeout=3)
                return real_decode(*args)
            finally:
                with lock:
                    active -= 1

        with patch.object(viewer.decode, "_android_image", side_effect=decode):
            self.assertEqual(material.mip_textures(objects), [0, 1, 2])
            self.assertEqual((calls, maximum), (3, 2))
            viewer._REQUEST_STATE.reimport = True
            again = viewer._Materials(scene, viewer._Glb())
            self.assertEqual(again.mip_textures(objects), [0, 1, 2])
            self.assertEqual(calls, 6)
        for index, image in enumerate(glb.doc["images"]):
            self.assertEqual(image["name"], "slice-" + str(index))
            view = glb.doc["bufferViews"][image["bufferView"]]
            data = bytes(glb.data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]])
            with Image.open(io.BytesIO(data)) as decoded:
                self.assertEqual(decoded.getpixel((0, 0)), (20 + index * 50, 40, 60, 255))
        self.assertEqual([texture.image_data for texture in textures], before)

    def test_mip_prefetch_does_not_decode_past_combined_pixel_budget(self):
        asset = object()
        objects = []
        for index in range(3):
            texture = raw_texture(20 + index * 30)
            texture.m_Name = "slice-" + str(index)
            objects.append(SimpleNamespace(assets_file=asset, path_id=index, read=lambda value=texture: value))
        scene = SimpleNamespace(deadline=time.monotonic() + 10, stats={"textures": 0})
        material = viewer._Materials(scene, viewer._Glb())
        with patch.object(viewer, "MAX_TEXTURE_PIXELS", 8), \
                patch.object(viewer.decode, "_android_image", wraps=viewer.decode._android_image) as decode:
            with self.assertRaisesRegex(viewer.ModelViewerError, "memory limit"):
                material.mip_textures(objects)
            self.assertEqual(decode.call_count, 2)
            self.assertEqual(scene.stats["textures"], 2)
            self.assertFalse(material.predecoded)


if __name__ == "__main__":
    unittest.main()
