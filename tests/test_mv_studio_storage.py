"""Original MV timelines remain exportable when project sessions share their bytes."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from webtools.core import mv_studio


class MVStudioStorageTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name).resolve()
        native_root = patch.object(mv_studio, "_root", return_value=self.root)
        self.addCleanup(native_root.stop)
        native_root.start()
        output = patch.object(mv_studio, "_destination", side_effect=lambda name, suffix: self.root / (name + suffix))
        self.addCleanup(output.stop)
        output.start()
        self.original = b"original timeline bytes"

    def test_each_session_keeps_its_own_token_and_saved_zip_contains_the_original(self):
        first = mv_studio._register(mv_studio._blank("First"), self.original)
        with patch.object(mv_studio, "_write", wraps=mv_studio._write) as write:
            second = mv_studio._register(mv_studio._blank("Second"), self.original)
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[0].suffix, ".sha256")
        self.assertNotEqual(first["token"], second["token"])
        self.assertEqual(mv_studio._native(first), self.original)
        self.assertEqual(mv_studio._native(second), self.original)
        with ZipFile(mv_studio.save(second)["path"]) as archive:
            self.assertEqual(archive.read("source-timeline.unity"), self.original)
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        self.assertNotEqual(reopened["token"], second["token"])
        self.assertEqual(mv_studio._native(reopened), self.original)
        self.assertEqual(len(list((self.root / "native" / "blobs").glob("*.unity"))), 1)

    def test_corrupt_blob_fails_save_until_source_is_reopened(self):
        first = mv_studio._register(mv_studio._blank("Recorded"), self.original)
        blob, = (self.root / "native" / "blobs").glob("*.unity")
        blob.write_bytes(b"x" * len(self.original))
        self.assertIsNone(mv_studio._native(first))
        with self.assertRaisesRegex(ValueError, "original MV timeline is unavailable"):
            mv_studio.save(first)
        mv_studio._register(mv_studio._blank("Reopened"), self.original)
        self.assertEqual(mv_studio._native(first), self.original)

    def test_legacy_originals_stay_readable(self):
        token = "a" * 32
        legacy = self.root / "native" / (token + ".unity")
        legacy.parent.mkdir()
        legacy.write_bytes(self.original)
        self.assertEqual(mv_studio._native({"token": token}), self.original)
        self.assertIsNone(mv_studio._native({"token": "../" + token}))
        self.assertIsNone(mv_studio._native({"token": "b" * 32}))
