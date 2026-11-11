"""Portable layered texture projects retain exact straight-alpha PNG sources."""
import base64
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, PngImagePlugin

from webtools.core import texture_project_io as projects


PNG_PREFIX = "data:image/png;base64,"
EXTENSION = ".elichika-texture.json"


def png_uri(raw):
    return PNG_PREFIX + base64.b64encode(raw).decode("ascii")


def png_bytes(image, **options):
    stream = io.BytesIO()
    image.save(stream, "PNG", **options)
    return stream.getvalue()


def chunk(kind, value):
    encoded = kind + value
    return struct.pack(">I", len(value)) + encoded + struct.pack(">I", zlib.crc32(encoded) & 0xffffffff)


def replace_dimensions(raw, width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return raw[:8] + chunk(b"IHDR", ihdr) + raw[33:]


def fixture():
    layers, originals = [], []
    for index, (identifier, name, visible, opacity) in enumerate((
            ("bottom", "원본 의상", True, 1),
            ("paint", "색상 · 입술", True, .375),
            ("hidden", "숨겨 둔 레이어", False, 0))):
        image = Image.new("RGBA", (5, 3), (37 + index, 89, 174, 129))
        image.putpixel((0, 0), (11 + index, 23 + index, 45 + index, 0))
        image.putpixel((1, 0), (223, 111 + index, 17, 1))
        image.putpixel((2, 1), (83, 129, 227 + index, 127))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Author", "Keep PNG metadata byte-for-byte: " + identifier)
        raw = png_bytes(image, pnginfo=metadata)
        layers.append({"id": identifier, "name": name, "visible": visible,
                       "opacity": opacity, "png": png_uri(raw)})
        originals.append((raw, image.tobytes()))
    return {"format": "elichika-texture-project", "version": 1, "width": 5, "height": 3,
            "activeLayer": "paint", "layers": layers}, originals


class TextureProjectFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project, self.originals = fixture()

    def test_three_layer_save_open_retains_order_metadata_and_every_png_byte(self):
        original = copy.deepcopy(self.project)
        for value in (self.project, json.dumps(self.project, ensure_ascii=False),
                      json.dumps(self.project, ensure_ascii=False).encode("utf-8")):
            canonical = projects.validate_project(value)
            self.assertEqual(canonical, original)
        saved = projects.save_project(self.project, "의상 색상" + EXTENSION.upper(), self.root / "out")
        path = Path(saved["path"])
        self.assertEqual(path.name, saved["name"])
        self.assertTrue(path.name.endswith(EXTENSION))
        restored = projects.open_project(path)
        self.assertEqual(restored, original)
        self.assertEqual(json.loads(path.read_text("utf-8")), original)
        for layer, (raw, pixels) in zip(restored["layers"], self.originals):
            restored_png = base64.b64decode(layer["png"][len(PNG_PREFIX):], validate=True)
            self.assertEqual(restored_png, raw)
            with Image.open(io.BytesIO(restored_png)) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.tobytes(), pixels)
        self.assertEqual(self.project, original)

    def test_schema_rejects_invalid_types_fields_ids_names_and_nonfinite_opacity(self):
        invalid = []
        for key, value in (("format", "other"), ("version", True), ("version", 2),
                           ("width", True), ("width", 5.0), ("width", 0), ("height", -1),
                           ("activeLayer", "absent"), ("activeLayer", False),
                           ("layers", []), ("layers", [self.project["layers"][0]] * 9)):
            candidate = copy.deepcopy(self.project)
            candidate[key] = value
            invalid.append(candidate)
        candidate = copy.deepcopy(self.project); candidate["extra"] = "not permitted"; invalid.append(candidate)
        candidate = copy.deepcopy(self.project); del candidate["activeLayer"]; invalid.append(candidate)
        candidate = copy.deepcopy(self.project); candidate["layers"][1]["id"] = "bottom"; invalid.append(candidate)
        for key, value in (("id", "a" * 65), ("id", "../layer"), ("id", "레이어"),
                           ("id", ""), ("name", "a" * 129), ("name", "line\nfeed"),
                           ("name", "null\0byte"), ("visible", 1), ("opacity", True),
                           ("opacity", -.01), ("opacity", 1.01), ("opacity", float("nan")),
                           ("opacity", float("inf")), ("opacity", "0.5"), ("extra", 1)):
            candidate = copy.deepcopy(self.project)
            candidate["layers"][0][key] = value
            invalid.append(candidate)
        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                snapshot = copy.deepcopy(value)
                with self.assertRaises(ValueError):
                    projects.validate_project(value)
                # NaN is unequal to itself, so compare the stable serialized
                # source rather than mistaking that property for mutation.
                self.assertEqual(json.dumps(value, sort_keys=True), json.dumps(snapshot, sort_keys=True))

    def test_json_duplicate_keys_malformed_utf8_and_nonfinite_tokens_are_rejected(self):
        encoded = json.dumps(self.project, ensure_ascii=False)
        invalid = [None, [], b"\xff", "{", "null", encoded + " trailing",
                   encoded.replace('"version": 1', '"version": 1, "version": 1', 1),
                   encoded.replace('"id": "bottom"', '"id": "bottom", "id": "bottom"', 1),
                   encoded.replace('"opacity": 0.375', '"opacity": NaN'),
                   encoded.replace('"opacity": 0.375', '"opacity": Infinity')]
        for value in invalid:
            with self.subTest(value=str(value)[:60]):
                with self.assertRaises(ValueError):
                    projects.validate_project(value)

    def test_png_type_animation_crc_truncation_trailing_bytes_and_text_bomb_refused(self):
        raw = self.originals[0][0]
        alternate = Image.new("RGBA", (5, 3), (1, 2, 3, 4))
        animated = png_bytes(alternate, save_all=True, append_images=[Image.new("RGBA", (5, 3), (4, 3, 2, 1))])
        jpeg = io.BytesIO(); alternate.convert("RGB").save(jpeg, "JPEG")
        bad_crc = bytearray(raw); bad_crc[29] ^= 1
        text_bomb = raw[:33] + chunk(b"zTXt", b"Comment\0\0" + zlib.compress(b"A" * (1024 * 1024 + 1))) + raw[33:]
        invalid = ["data:image/png;base64,@@@", png_uri(b"not png"), png_uri(jpeg.getvalue()),
                   png_uri(raw[:-1]), png_uri(raw + b"trailing"), png_uri(bytes(bad_crc)),
                   png_uri(animated), png_uri(text_bomb),
                   png_uri(png_bytes(Image.new("RGB", (5, 3)))),
                   png_uri(png_bytes(Image.new("P", (5, 3)))),
                   png_uri(png_bytes(Image.new("I;16", (5, 3)))),
                   png_uri(png_bytes(Image.new("RGBA", (6, 3))))]
        palette = chunk(b"PLTE", bytes((11, 23, 45)))
        invalid.extend(png_uri(raw[:33] + chunk(b"PLTE", bytes(length)) + raw[33:])
                       for length in (0, 2, 767, 771))
        invalid.extend((png_uri(raw[:33] + palette + palette + raw[33:]),
                        png_uri(raw[:-12] + palette + raw[-12:])))
        for value in invalid:
            with self.subTest(png_length=len(value)):
                candidate = copy.deepcopy(self.project)
                candidate["layers"][0]["png"] = value
                with self.assertRaises(ValueError):
                    projects.validate_project(candidate)
        suggested_palette = copy.deepcopy(self.project)
        suggested_palette["layers"][0]["png"] = png_uri(raw[:33] + palette + raw[33:])
        self.assertEqual(projects.validate_project(suggested_palette), suggested_palette)

    def test_dimension_and_aggregate_budgets_fail_before_any_pixel_allocation(self):
        raw = self.originals[0][0]
        for width, height in ((8193, 1), (4097, 4097)):
            with self.subTest(dimensions=(width, height)):
                candidate = copy.deepcopy(self.project)
                candidate.update(width=width, height=height)
                candidate["layers"] = [dict(candidate["layers"][0], png=png_uri(replace_dimensions(raw, width, height)))]
                candidate["activeLayer"] = "bottom"
                with patch.object(PngImagePlugin.PngImageFile, "load", side_effect=AssertionError("allocated oversized pixels")), \
                        patch.object(projects.zlib, "decompressobj", side_effect=AssertionError("inflated before dimension preflight")):
                    with self.assertRaises(ValueError):
                        projects.validate_project(candidate)
        for constant, maximum in (("MAX_TOTAL_PIXELS", 44), ("MAX_DECODED_BYTES", 179),
                                  ("MAX_LAYER_PNG_BYTES", len(raw) - 1), ("MAX_BYTES", 1)):
            with self.subTest(constant=constant), patch.object(projects, constant, maximum):
                with patch.object(PngImagePlugin.PngImageFile, "load", side_effect=AssertionError("allocated pixels before budget preflight")), \
                        patch.object(projects.zlib, "decompressobj", side_effect=AssertionError("inflated before aggregate preflight")):
                    with self.assertRaises(ValueError):
                        projects.validate_project(self.project)
        candidate = copy.deepcopy(self.project)
        candidate["layers"][-1]["png"] = png_uri(raw + b"trailing")
        with patch.object(projects.zlib, "decompressobj", side_effect=AssertionError("inflated before last layer preflight")):
            with self.assertRaises(ValueError):
                projects.validate_project(candidate)

    def test_crc_valid_deflate_bombs_filters_and_interlaced_pixel_streams(self):
        signature = b"\x89PNG\r\n\x1a\n"
        def encoded(width, height, compressed, interlace=0):
            header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, interlace)
            # Splitting even the zlib header/checksum exercises legal IDAT
            # boundaries without decoding or rewriting source PNG bytes.
            parts = [compressed[at:at + 3] for at in range(0, len(compressed), 3)]
            return signature + chunk(b"IHDR", header) + b"".join(chunk(b"IDAT", part) for part in parts) + chunk(b"IEND", b"")
        def document(raw, width=5, height=3):
            value = copy.deepcopy(self.project)
            value.update(width=width, height=height, activeLayer="bottom")
            value["layers"] = [dict(value["layers"][0], png=png_uri(raw))]
            return value
        scanlines = b"".join(bytes([filter_kind]) + bytes((10, 20, 30, 127)) * 5 for filter_kind in (0, 1, 4))
        valid = document(encoded(5, 3, zlib.compress(scanlines)))
        self.assertEqual(projects.validate_project(valid), valid)
        compressed = zlib.compress(scanlines)
        streams = [b"not zlib", compressed[:-2], zlib.compress(scanlines[:-1]),
                   zlib.compress(scanlines + b"\0"), zlib.compress(b"\5" + scanlines[1:]),
                   compressed + zlib.compress(b""), zlib.compress(bytes(1024 * 1024))]
        for stream in streams:
            with self.subTest(compressed_bytes=len(stream)):
                with self.assertRaises(ValueError):
                    projects.validate_project(document(encoded(5, 3, stream)))
        # This explicit 2x2 Adam7 stream has populated passes1,6,7. Hidden RGB
        # and partial alpha survive both the standard PNG decoder and project.
        p00, p10, p01, p11 = bytes((19, 31, 47, 0)), bytes((211, 97, 53, 1)), bytes((71, 89, 107, 127)), bytes((131, 149, 167, 255))
        interlaced = encoded(2, 2, zlib.compress(b"\0" + p00 + b"\0" + p10 + b"\0" + p01 + p11), 1)
        with Image.open(io.BytesIO(interlaced)) as image:
            self.assertEqual(image.tobytes(), p00 + p10 + p01 + p11)
        project = document(interlaced, 2, 2)
        saved = projects.save_project(project, "interlaced", self.root / "interlaced")
        self.assertEqual(projects.open_project(saved["path"]), project)

    def test_safe_names_collision_and_existing_file_symlink_never_overwrite_or_escape(self):
        directory = self.root / "exports"
        first = projects.save_project(self.project, "../의상:색상?", directory)
        second = projects.save_project(self.project, "../의상:색상?", directory)
        long = projects.save_project(self.project, "한" * 300, directory)
        self.assertNotEqual(first["path"], second["path"])
        for result in (first, second, long):
            path = Path(result["path"])
            self.assertEqual(path.parent, directory)
            self.assertLessEqual(len(path.name.encode("utf-8")), 255)
            self.assertTrue(path.name.endswith(EXTENSION))
            self.assertEqual(projects.open_project(path), self.project)
        victim = self.root / "outside-original.txt"; victim.write_bytes(b"do not replace")
        collision = directory / ("layer" + EXTENSION); collision.symlink_to(victim)
        saved = projects.save_project(self.project, "layer", directory)
        self.assertNotEqual(Path(saved["path"]), collision)
        self.assertTrue(collision.is_symlink())
        self.assertEqual(victim.read_bytes(), b"do not replace")

    def test_invalid_project_and_unsafe_input_or_output_paths_publish_nothing(self):
        directory = self.root / "new-output"
        invalid = copy.deepcopy(self.project); invalid["layers"][0]["png"] = "not a PNG"
        for value, name in ((invalid, "bad"), (self.project, ""), (self.project, False)):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    projects.save_project(value, name, directory)
                self.assertFalse(directory.exists())
        real = self.root / ("valid" + EXTENSION)
        real.write_text(json.dumps(self.project), "utf-8")
        symlink = self.root / ("symlink" + EXTENSION); symlink.symlink_to(real)
        wrong_suffix = self.root / "wrong.json"; wrong_suffix.write_bytes(real.read_bytes())
        damaged = self.root / ("damaged" + EXTENSION); damaged.write_bytes(b"{invalid")
        huge = self.root / ("huge" + EXTENSION)
        with huge.open("wb") as stream: stream.truncate(32 * 1024 * 1024 + 1)
        for path in (symlink, wrong_suffix, damaged, huge, self.root):
            with self.subTest(path=path.name):
                with self.assertRaises(ValueError):
                    projects.open_project(path)
        actual = self.root / "actual-output"; actual.mkdir()
        linked = self.root / "linked-output"; linked.symlink_to(actual, target_is_directory=True)
        for output in (linked, linked / "nested"):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    projects.save_project(self.project, "unsafe", output)
        self.assertEqual(list(actual.iterdir()), [])
        self.assertEqual(projects.open_project(real), self.project)


if __name__ == "__main__":
    unittest.main()
