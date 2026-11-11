"""Native-friendly PNG file I/O must preserve pixels and never overwrite files."""
import base64
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image, PngImagePlugin
from webtools.core import texture_image_io


def fixture():
    image = Image.new("RGBA", (5, 3), (42, 93, 188, 128))
    image.putpixel((0, 0), (9, 8, 7, 0))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Author", "unmodified PNG metadata")
    stream = io.BytesIO()
    image.save(stream, "PNG", pnginfo=metadata)
    raw = stream.getvalue()
    return raw, "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


class TextureImageFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_open_and_save_preserve_every_png_byte_and_hidden_rgb(self):
        raw, png = fixture()
        source = self.root / "source.PNG"
        source.write_bytes(raw)
        decoded = texture_image_io.open_png(source)
        self.assertEqual((decoded["width"], decoded["height"]), (5, 3))
        saved = texture_image_io.save_png(png, "edited.png", self.root / "out")
        self.assertEqual(Path(saved["path"]).read_bytes(), raw)
        self.assertEqual(texture_image_io.open_png(saved["path"])["rgbaZlib"], decoded["rgbaZlib"])

    def test_export_name_cannot_escape_overwrite_or_exceed_native_name_limits(self):
        raw, png = fixture()
        directory = self.root / "out"
        first = texture_image_io.save_png(png, "../의상:색상.png", directory)
        second = texture_image_io.save_png(png, "../의상:색상.png", directory)
        long = texture_image_io.save_png(png, "한" * 300 + ".png", directory)
        self.assertNotEqual(first["path"], second["path"])
        for result in (first, second, long):
            path = Path(result["path"])
            self.assertEqual(path.parent, directory)
            self.assertLessEqual(len(path.name.encode("utf-8")), 255)
            self.assertEqual(path.read_bytes(), raw)

    def test_invalid_png_or_name_publishes_no_file(self):
        _, png = fixture()
        directory = self.root / "out"
        for value, name in (("data:image/png;base64,bm90LXBuZw==", "test.png"),
                            (png, ""), (png, "x" * 1025), (png, False)):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    texture_image_io.save_png(value, name, directory)
                self.assertFalse(directory.exists())

    def test_open_rejects_wrong_type_corrupt_or_oversized_inputs(self):
        raw, _ = fixture()
        wrong = self.root / "wrong.jpg"
        wrong.write_bytes(raw)
        corrupt = self.root / "corrupt.png"
        corrupt.write_bytes(b"not PNG")
        large = self.root / "large.png"
        with large.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        for source in (wrong, corrupt, large, self.root):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    texture_image_io.open_png(source)


if __name__ == "__main__":
    unittest.main()
