"""Real costume ZIP extraction stays read-only, bounded and temporary."""
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import viewer_archive


class ViewerArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.fixture = (Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes()
        self.archive = self.root / "costume.zip"

    def write_zip(self, files):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files:
                archive.writestr(name, data)

    def test_extensionless_bundle_and_manifest_are_preserved_without_running_code(self):
        # The name has no extension, as in real modinstall costume archives.
        bundle = b"UnityFS\0" + b"\0" * 64
        marker = self.root / "should-not-exist"
        manifest = ("chara_id=207\ncostume_file='207setsuna'\n"
                    "open(%r,'w').write('executed')\n" % str(marker)).encode()
        self.write_zip([("nested/207setsuna", bundle), ("nested/modinstall.txt", manifest),
                        ("nested/thumbnail.png", b"not a model")])
        original = self.archive.read_bytes()
        with viewer_archive.expand_inputs([str(self.archive)], self.cache) as expanded:
            self.assertEqual(len(expanded.paths), 1)
            self.assertEqual(Path(expanded.paths[0]).read_bytes(), bundle)
            self.assertEqual(Path(expanded.manifest_paths[0]).read_bytes(), manifest)
            self.assertEqual(expanded.source_names, ["costume.zip"])
            self.assertEqual(expanded.origins[expanded.paths[0]], str(self.archive))
            self.assertEqual(expanded.origins[expanded.manifest_paths[0]], str(self.archive))
            extracted = Path(expanded.paths[0])
            self.assertFalse(marker.exists())
        self.assertFalse(extracted.exists())
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_real_serialized_model_and_plain_selected_file_can_be_combined(self):
        plain = self.root / "plain.unity"
        plain.write_bytes(self.fixture)
        self.write_zip([("body.unity", self.fixture)])
        with viewer_archive.expand_inputs([str(self.archive), str(plain)], self.cache) as expanded:
            self.assertEqual(len(expanded.paths), 2)
            self.assertEqual(Path(expanded.paths[0]).read_bytes(), self.fixture)
            self.assertEqual(expanded.paths[1], str(plain))

    def test_plain_input_needs_no_cache_or_file_copy(self):
        plain = self.root / "body.unity"
        plain.write_bytes(self.fixture)
        with viewer_archive.expand_inputs([str(plain)], self.cache) as expanded:
            self.assertEqual(expanded.paths, [str(plain)])
            self.assertEqual(expanded.manifest_paths, [])
        self.assertFalse(self.cache.exists())

    def test_unsafe_paths_and_symlinks_are_rejected_before_extraction(self):
        for name in ("../escape", "/escape", "C:\\escape", "a/../../escape"):
            with self.subTest(name=name):
                self.write_zip([(name, self.fixture)])
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                        self.fail("Unsafe ZIP must not reach conversion")
        link = zipfile.ZipInfo("linked")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_zip([(link, b"outside"), ("body", self.fixture)])
        with self.assertRaisesRegex(ValueError, "unsafe"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                self.fail("Symlink ZIP must not reach conversion")

    def test_duplicate_names_and_zip_bomb_declarations_are_rejected(self):
        self.write_zip([("Body", self.fixture), ("body", self.fixture)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                self.fail("Ambiguous ZIP must not reach conversion")
        self.write_zip([("large-image.png", b"x" * 32), ("body", self.fixture)])
        with patch.object(viewer_archive, "MAX_UNPACKED_BYTES", 16), \
                patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("No member should be read")):
            with self.assertRaisesRegex(ValueError, "expands"):
                with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                    self.fail("Oversized ZIP must not reach conversion")

    def test_empty_non_model_and_invalid_zip_errors_are_actionable(self):
        self.write_zip([("readme.txt", b"Choose me as data, not instructions")])
        with self.assertRaisesRegex(ValueError, "no extracted Unity"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                self.fail("A text-only ZIP cannot be rendered")
        self.archive.write_bytes(b"not a ZIP")
        with self.assertRaisesRegex(ValueError, "could not be read"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                self.fail("Invalid ZIP cannot be rendered")

    def test_conversion_failure_cleans_up_and_preserves_the_original_error(self):
        self.write_zip([("body", self.fixture)])
        with self.assertRaisesRegex(RuntimeError, "^renderer failed$"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache) as expanded:
                extracted = Path(expanded.paths[0])
                raise RuntimeError("renderer failed")
        self.assertFalse(extracted.exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_symlinked_cache_is_not_used_or_written(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.cache.symlink_to(outside, target_is_directory=True)
        self.write_zip([("body", self.fixture)])
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                self.fail("Symlink cache must not be used")
        self.assertEqual(list(outside.iterdir()), [])

    def test_large_central_directory_is_rejected_before_zipfile_allocation(self):
        self.write_zip([("empty-" + str(index), b"") for index in range(1000)])
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("No ZipInfo allocation allowed")):
            with self.assertRaisesRegex(ValueError, "directory"):
                with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                    self.fail("Large directory must not reach conversion")

    def test_zip64_locator_cannot_override_small_eocd_counts(self):
        self.write_zip([("body", self.fixture)])
        data = self.archive.read_bytes()
        at = data.rfind(b"PK\x05\x06")
        locator = b"PK\x06\x07" + b"\0" * 16
        self.archive.write_bytes(data[:at] + locator + data[at:])
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("ZIP64 must be rejected first")):
            with self.assertRaisesRegex(ValueError, "ZIP64"):
                with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                    self.fail("ZIP64 directory must not reach conversion")

    def test_maximum_zip_comment_cannot_hide_a_zip64_locator(self):
        self.write_zip([("body", self.fixture)])
        data = bytearray(self.archive.read_bytes())
        at = data.rfind(b"PK\x05\x06")
        struct.pack_into("<H", data, at + 20, 65535)
        locator = b"PK\x06\x07" + b"\0" * 16
        self.archive.write_bytes(data[:at] + locator + data[at:] + b"x" * 65535)
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("Hidden ZIP64 must be rejected first")):
            with self.assertRaisesRegex(ValueError, "ZIP64"):
                with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                    self.fail("Hidden ZIP64 directory must not reach conversion")

    def test_forged_directory_byte_size_is_rejected_before_zipfile_allocation(self):
        self.write_zip([("body", self.fixture)])
        data = bytearray(self.archive.read_bytes())
        at = data.rfind(b"PK\x05\x06")
        struct.pack_into("<I", data, at + 12, viewer_archive.MAX_DIRECTORY_BYTES + 1)
        self.archive.write_bytes(data)
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("No directory parsing allowed")):
            with self.assertRaisesRegex(ValueError, "directory"):
                with viewer_archive.expand_inputs([str(self.archive)], self.cache):
                    self.fail("Oversized directory must not reach conversion")


if __name__ == "__main__":
    unittest.main()
