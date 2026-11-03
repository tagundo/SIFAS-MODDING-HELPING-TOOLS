"""Gallery runtime routing, safe pixel decoding and isolated CLI regressions.

Raw/ASTC pixel assertions use Pillow when installed. Routing, selection and
bounds checks remain runnable on a standard-library-only host.
"""
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webtools.core import decode

try:
    from PIL import Image
except ImportError:
    Image = None


PNG = b"\x89PNG\r\n\x1a\nfixture"


class Texture:
    def __init__(self, data=b"", **values):
        self.m_Width = self.m_Height = 2
        self.m_TextureFormat = "RGBA32"
        self.m_ImageCount = 1
        self.m_TextureDimension = 2
        self.m_StreamData = None
        self.image_data = data
        self.payload = data
        self.reads = 0
        self.__dict__.update(values)

    @property
    def image(self):
        raise AssertionError("Android must never enter UnityPy's optional native image decoders")

    def get_image_data(self):
        self.reads += 1
        return self.payload


class RuntimeRoutingTests(unittest.TestCase):
    def setUp(self):
        decode._CACHE.clear()
        decode._ANDROID_CACHE.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name) / "body.unity"
        self.bundle.write_bytes(b"UnityFS fixture")

    def test_chaquopy_uses_safe_embedded_path_without_python_cli_or_script_file(self):
        with patch.dict(sys.modules, {"java.android": SimpleNamespace()}), \
                patch.object(decode, "_android_thumbnail", return_value=PNG) as safe, \
                patch.object(decode, "_packer_path") as script, \
                patch.object(decode.subprocess, "run") as run:
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
        safe.assert_called_once()
        script.assert_not_called()
        run.assert_not_called()

    def test_android_failure_falls_back_and_releases_decoder_lock(self):
        other = self.bundle.with_name("other.unity")
        other.write_bytes(b"UnityFS second fixture")
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_android_thumbnail", side_effect=[RuntimeError("unsupported"), PNG]):
            self.assertIsNone(decode.thumbnail(self.bundle))
            self.assertEqual(decode.thumbnail(other), PNG)

    def test_busy_android_queue_is_not_cached_as_unsupported_texture(self):
        lock = Mock()
        lock.acquire.return_value = False
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_ANDROID_LOCK", lock), \
                patch.object(decode, "_android_thumbnail") as safe:
            self.assertIsNone(decode.thumbnail(self.bundle, timeout=0))
        self.assertEqual(decode._CACHE, {})
        self.assertEqual(decode._ANDROID_CACHE, {})
        safe.assert_not_called()
        lock.release.assert_not_called()

    def test_android_cache_evicts_least_recent_including_negative_entries(self):
        other = self.bundle.with_name("other.unity")
        third = self.bundle.with_name("third.unity")
        other.write_bytes(b"UnityFS second fixture")
        third.write_bytes(b"UnityFS third fixture")
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_ANDROID_CACHE_ENTRIES", 2), \
                patch.object(decode, "_android_thumbnail", side_effect=[PNG, None, PNG, None]) as safe:
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
            self.assertIsNone(decode.thumbnail(other))
            self.assertEqual(decode.thumbnail(self.bundle), PNG)  # refresh the first entry
            self.assertEqual(decode.thumbnail(third), PNG)
            self.assertEqual([key[0] for key in decode._ANDROID_CACHE], [str(self.bundle), str(third)])
            self.assertIsNone(decode.thumbnail(other))  # the negative entry was evicted
            self.assertIsNone(decode.thumbnail(other))  # then cached again
        self.assertEqual(safe.call_count, 4)
        self.assertEqual(len(decode._ANDROID_CACHE), 2)
        self.assertEqual(decode._CACHE, {})

    def test_android_cache_evicts_for_total_png_bytes(self):
        other = self.bundle.with_name("other.unity")
        other.write_bytes(b"UnityFS second fixture")
        budget = len(PNG) + 1
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_ANDROID_CACHE_BYTES", budget), \
                patch.object(decode, "_android_thumbnail", return_value=PNG) as safe:
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
            self.assertEqual(decode.thumbnail(other), PNG)
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
        self.assertEqual(safe.call_count, 3)
        self.assertLessEqual(sum(map(len, decode._ANDROID_CACHE.values())), budget)

    def test_android_oversized_png_is_returned_without_caching(self):
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_ANDROID_CACHE_BYTES", len(PNG) - 1), \
                patch.object(decode, "_android_thumbnail", return_value=PNG) as safe:
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
        self.assertEqual(safe.call_count, 2)
        self.assertEqual(decode._ANDROID_CACHE, {})

    def test_android_uses_bounded_cache_independently_of_desktop_cache(self):
        key = (str(self.bundle), self.bundle.stat().st_mtime)
        decode._CACHE[key] = b"desktop preview"
        with patch.object(decode, "_embedded_android", return_value=True), \
                patch.object(decode, "_android_thumbnail", return_value=PNG) as safe:
            self.assertEqual(decode.thumbnail(self.bundle), PNG)
        safe.assert_called_once()
        self.assertEqual(decode._CACHE[key], b"desktop preview")
        self.assertEqual(decode._ANDROID_CACHE[key], PNG)

    def test_desktop_keeps_isolated_python_worker_and_timeout(self):
        def worker(command, **options):
            self.assertEqual(command[:4], [sys.executable, "/tools/packer.py", "--decode-worker", str(self.bundle)])
            self.assertEqual(options["timeout"], 7)
            Path(command[4]).write_bytes(PNG)
            return SimpleNamespace(returncode=0)
        with patch.object(decode, "_embedded_android", return_value=False), \
                patch.object(decode, "_packer_path", return_value="/tools/packer.py"), \
                patch.object(decode.subprocess, "run", side_effect=worker) as run:
            self.assertEqual(decode.thumbnail(self.bundle, timeout=7), PNG)
        run.assert_called_once()
        self.assertFalse(Path(run.call_args.args[0][4]).exists())

    def test_desktop_native_worker_crash_becomes_cached_no_preview(self):
        with patch.object(decode, "_embedded_android", return_value=False), \
                patch.object(decode, "_packer_path", return_value="/tools/packer.py"), \
                patch.object(decode.subprocess, "run", return_value=SimpleNamespace(returncode=-4)) as run:
            self.assertIsNone(decode.thumbnail(self.bundle))
            self.assertIsNone(decode.thumbnail(self.bundle))
        run.assert_called_once()


class SafeDecoderTests(unittest.TestCase):
    def setUp(self):
        # No actual UnityPy import is needed to validate supported-format routing.
        enums = SimpleNamespace(TextureFormat=lambda value: SimpleNamespace(name=value))
        self.enum_patch = patch.dict(sys.modules, {"UnityPy.enums": enums})
        self.enum_patch.start()
        self.addCleanup(self.enum_patch.stop)

    def image(self, texture):
        return decode._android_image(texture, time.monotonic() + 10)

    def test_invalid_dimensions_are_rejected_before_reading_stream_bytes(self):
        for width, height in ((0, 2), (-1, 2), (True, 2), (2, False), (8193, 1), (4097, 4096)):
            texture = Texture(m_Width=width, m_Height=height)
            with self.subTest(size=(width, height)), self.assertRaisesRegex(ValueError, "dimensions"):
                self.image(texture)
            self.assertEqual(texture.reads, 0)

    def test_large_stream_and_inline_data_are_rejected_before_accessor(self):
        texture = Texture(m_StreamData=SimpleNamespace(size=decode._MAX_SOURCE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "Streamed texture"):
            self.image(texture)
        self.assertEqual(texture.reads, 0)
        texture = Texture(b"x" * 16)
        with patch.object(decode, "_MAX_SOURCE_BYTES", 8), self.assertRaisesRegex(ValueError, "Texture data"):
            self.image(texture)
        self.assertEqual(texture.reads, 0)

    def test_unsupported_codecs_hdr_and_swizzled_data_never_enter_image_decoder(self):
        textures = [Texture(m_TextureFormat="ETC2_RGBA8Crunched"),
                    Texture(m_TextureFormat="ASTC_HDR_6x6"),
                    Texture(object_reader=SimpleNamespace(platform=38), m_PlatformBlob=[1]),
                    Texture(object_reader=SimpleNamespace(platform=11)),
                    Texture(m_ImageCount=2), Texture(m_TextureDimension=3)]
        with patch.object(decode.subprocess, "run") as run:
            for texture in textures:
                with self.subTest(texture=texture.__dict__), self.assertRaises(ValueError):
                    self.image(texture)
                self.assertEqual(texture.reads, 0)
        run.assert_not_called()

    def test_expired_decode_budget_does_not_read_texture(self):
        texture = Texture()
        with self.assertRaises(TimeoutError):
            decode._android_image(texture, time.monotonic() - 1)
        self.assertEqual(texture.reads, 0)

    @unittest.skipUnless(Image, "Pillow is required for pixel assertions")
    def test_raw_channels_flip_once_and_ignore_lower_mipmap_bytes(self):
        pixels = [(240, 10, 20, 11), (30, 220, 40, 22), (50, 60, 200, 33), (70, 80, 90, 44)]
        channels = {"RGBA32": lambda p: p, "ARGB32": lambda p: (p[3], *p[:3]),
                    "BGRA32": lambda p: (p[2], p[1], p[0], p[3]), "RGB24": lambda p: p[:3]}
        for name, convert in channels.items():
            payload = bytes(value for pixel in pixels for value in convert(pixel)) + b"lower mip data"
            texture = Texture(payload, m_TextureFormat=name)
            actual = list(self.image(texture).convert("RGBA").tobytes())
            expected = pixels[2:] + pixels[:2]
            if name == "RGB24":
                expected = [(*pixel[:3], 255) for pixel in expected]
            with self.subTest(format=name):
                self.assertEqual(actual, [channel for pixel in expected for channel in pixel])
                self.assertEqual(texture.reads, 1)

    @unittest.skipUnless(Image, "Pillow is required for pixel assertions")
    def test_stream_accessor_is_used_instead_of_empty_inline_data(self):
        texture = Texture(image_data=b"", m_StreamData=SimpleNamespace(size=16), payload=b"\xff\x00\x00\xff" * 4)
        self.assertEqual(self.image(texture).getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(texture.reads, 1)

    @unittest.skipUnless(Image, "Pillow is required for pixel assertions")
    def test_truncated_raw_and_astc_payloads_fail_cleanly(self):
        for name in ("RGBA32", "ASTC_RGBA_6x6"):
            with self.subTest(format=name), self.assertRaisesRegex(ValueError, "Truncated"):
                self.image(Texture(b"x" * 15, m_TextureFormat=name))

    @unittest.skipUnless(Image, "Pillow is required for isolated ASTC output assertions")
    def test_astc_runs_only_cli_with_base_mip_header_timeout_and_matching_orientation(self):
        texture = Texture(b"a" * 16 + b"lower mips", m_TextureFormat="ASTC_RGBA_6x6")
        image = Image.new("RGBA", (2, 2))
        image.putdata([(255, 0, 0, 255)] * 2 + [(0, 0, 255, 255)] * 2)
        def worker(command, **options):
            self.assertEqual(command[1], "-dl")
            self.assertEqual(Path(command[3]).suffix, ".tga")
            encoded = Path(command[2]).read_bytes()
            self.assertEqual(encoded[:16], b"\x13\xab\xa1\x5c\x06\x06\x01\x02\x00\x00\x02\x00\x00\x01\x00\x00")
            self.assertEqual(encoded[16:], b"a" * 16)
            self.assertTrue(options["check"])
            self.assertGreater(options["timeout"], 0)
            self.assertLessEqual(options["timeout"], 10)
            image.save(command[3])
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "libastcenc.so"
            binary.touch()
            with patch.dict(os.environ, {"ASTCENC_BIN": str(binary)}), \
                    patch.object(decode.subprocess, "run", side_effect=worker) as run:
                actual = self.image(texture)
            self.assertEqual(actual.getpixel((0, 0)), (0, 0, 255, 255))
            self.assertFalse(Path(run.call_args.args[0][2]).exists())

    @unittest.skipUnless(Image and os.environ.get("ASTCENC_HOST_TEST_BIN"),
                         "Set ASTCENC_HOST_TEST_BIN for exact native transport assertions")
    def test_actual_cli_tga_preserves_png_rgba_alpha_and_unity_orientation(self):
        binary = Path(os.environ["ASTCENC_HOST_TEST_BIN"])
        self.assertTrue(binary.is_file())

        def block(rgba):
            # Original generated ASTC LDR constant blocks, as defined by the
            # format: a void-extent prefix followed by four UNORM16 channels.
            return bytes.fromhex("fcfdffffffffffff") + struct.pack("<4H", *(v * 257 for v in rgba))

        cases = [
            (4, 4, [(12, 57, 190, 255)]),
            (4, 4, [(240, 60, 20, 37)]),
            (8, 8, [(255, 0, 0, 255), (0, 255, 0, 127), (0, 0, 255, 0), (255, 0, 255, 255)]),
            (7, 5, [(0, 255, 128, 0), (20, 80, 240, 64), (180, 30, 250, 128), (255, 255, 255, 255)]),
        ]
        for width, height, colors in cases:
            data = b"".join(map(block, colors))
            texture = Texture(data, m_Width=width, m_Height=height, m_TextureFormat="ASTC_RGBA_4x4")
            with self.subTest(size=(width, height), colors=colors), tempfile.TemporaryDirectory() as directory:
                source, png = Path(directory) / "source.astc", Path(directory) / "reference.png"
                source.write_bytes(bytes.fromhex("13aba15c040401") + width.to_bytes(3, "little")
                                   + height.to_bytes(3, "little") + b"\x01\x00\x00" + data)
                subprocess.run([str(binary), "-dl", str(source), str(png)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
                with Image.open(png) as reference:
                    expected = reference.convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    with patch.dict(os.environ, {"ASTCENC_BIN": str(binary)}):
                        actual = self.image(texture)
                    try:
                        self.assertEqual(actual.size, expected.size)
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                        self.assertEqual(actual.getchannel("A").getextrema(), expected.getchannel("A").getextrema())
                    finally:
                        actual.close()
                        expected.close()

    @unittest.skipUnless(Image, "Pillow is required for isolated ASTC output assertions")
    def test_astc_cli_timeout_crash_and_wrong_image_dimensions_are_not_accepted(self):
        texture = Texture(b"a" * 16, m_TextureFormat="ASTC_RGB_4x4")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "libastcenc.so"
            binary.touch()
            with patch.dict(os.environ, {"ASTCENC_BIN": str(binary)}):
                for error in (subprocess.TimeoutExpired("astc", 1), subprocess.CalledProcessError(-4, "astc")):
                    with patch.object(decode.subprocess, "run", side_effect=error), self.assertRaises(type(error)):
                        self.image(texture)
                def wrong_size(command, **options):
                    Image.new("RGBA", (3, 2)).save(command[3])
                    return SimpleNamespace(returncode=0)
                with patch.object(decode.subprocess, "run", side_effect=wrong_size), \
                        self.assertRaisesRegex(ValueError, "incorrect dimensions"):
                    self.image(texture)

    @unittest.skipUnless(Image, "Pillow is required for explicit TGA assertions")
    def test_astc_output_rejects_other_formats_and_truncated_tga_with_cleanup(self):
        encoded = io.BytesIO()
        Image.new("RGBA", (2, 2), (10, 20, 30, 40)).save(encoded, format="PNG")
        header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 2, 2, 32, 0x28)
        for payload in (encoded.getvalue(), header + b"\0" * 4):
            called = []
            def worker(command, **options):
                called.append((Path(command[2]), Path(command[3])))
                Path(command[3]).write_bytes(payload)
                return SimpleNamespace(returncode=0)
            with self.subTest(payload=payload[:18]), tempfile.TemporaryDirectory() as directory:
                binary = Path(directory) / "libastcenc.so"
                binary.touch()
                with patch.dict(os.environ, {"ASTCENC_BIN": str(binary)}), \
                        patch.object(decode.subprocess, "run", side_effect=worker), \
                        self.assertRaises((SyntaxError, OSError)):
                    self.image(Texture(b"a" * 16, m_TextureFormat="ASTC_RGBA_4x4"))
                self.assertEqual(len(called), 1)
                self.assertFalse(called[0][0].exists())
                self.assertFalse(called[0][1].exists())

    @unittest.skipUnless(Image and os.environ.get("ASTCENC_HOST_TEST_BIN"),
                         "Set ASTCENC_HOST_TEST_BIN for clean-process transport assertions")
    def test_clean_cli_decode_and_final_png_do_not_discover_all_image_plugins(self):
        # A fresh process is essential: earlier image tests may already have
        # registered TGA, hiding Image.open's expensive fallback to Image.init.
        script = textwrap.dedent(r'''
            import io, json, os, struct, sys, time
            from types import SimpleNamespace
            from PIL import Image
            from webtools.core import decode
            before = [name for name in sys.modules if name.startswith("PIL.") and name.endswith("ImagePlugin")]
            assert not before, before
            def forbidden():
                raise AssertionError("Bulk Pillow plugin discovery must not run")
            Image.init = forbidden
            sys.modules["UnityPy.enums"] = SimpleNamespace(TextureFormat=lambda value: SimpleNamespace(name=value))
            colors = [(255,0,0,255), (0,255,0,127), (0,0,255,0), (255,0,255,255)]
            data = b"".join(bytes.fromhex("fcfdffffffffffff") + struct.pack("<4H", *(v*257 for v in color)) for color in colors)
            texture = SimpleNamespace(m_Width=8, m_Height=8, m_ImageCount=1, m_TextureDimension=2,
                m_StreamData=None, image_data=data, m_TextureFormat="ASTC_RGBA_4x4", get_image_data=lambda: data)
            image = decode._android_image(texture, time.monotonic()+10)
            expected = bytes(channel for y in range(8) for x in range(8)
                for channel in colors[((7-y)//4)*2 + x//4])
            assert image.size == (8,8) and image.tobytes() == expected
            encoded = io.BytesIO()
            image.save(encoded, format="PNG")
            image.close()
            from PIL.PngImagePlugin import PngImageFile
            with PngImageFile(io.BytesIO(encoded.getvalue())) as actual:
                assert actual.mode == "RGBA" and actual.size == (8,8)
                assert actual.tobytes() == expected
                assert actual.getchannel("A").getextrema() == (0,255)
            print(json.dumps({"pluginModulesBefore":before,"pluginModulesAfter":[name for name in sys.modules
                if name.startswith("PIL.") and name.endswith("ImagePlugin")],"pixelsAndFinalPng":True}))
        ''')
        env = dict(os.environ, ASTCENC_BIN=os.environ["ASTCENC_HOST_TEST_BIN"])
        result = subprocess.run([sys.executable, "-c", script], env=env, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["pluginModulesBefore"], [])
        self.assertTrue(observed["pixelsAndFinalPng"])
        self.assertIn("PIL.TgaImagePlugin", observed["pluginModulesAfter"])
        self.assertIn("PIL.PngImagePlugin", observed["pluginModulesAfter"])


class PackerSelectionTests(unittest.TestCase):
    def test_optional_decoder_keeps_body_priority_without_native_image_or_global_platform_patch(self):
        import unity_costumemod_packer as packer
        body = Texture(m_Name="ch0101_co0012_body")
        rim = Texture(m_Name="ch0101_co0012_body_rim", m_Width=64, m_Height=64)
        objects = [SimpleNamespace(type=SimpleNamespace(name="Texture2D"), read=lambda t=t: t) for t in (rim, body)]
        env = SimpleNamespace(objects=objects)
        class Preview:
            def save(self, output, format):
                assert format == "PNG"
                output.write(PNG)
        safe = Mock(return_value=Preview())
        with patch.object(packer, "UnityPy", SimpleNamespace(load=lambda path: env)), \
                patch.object(packer, "_patch_platform_for_decode") as platform_patch:
            name, png = packer._extract_body_texture_core("bundle", image_decoder=safe)
        self.assertEqual((name, png), (body.m_Name, PNG))
        safe.assert_called_once_with(body)
        platform_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
