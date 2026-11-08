"""Cache budget checks must not weaken integrity checks of selected face assets."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import model_faces as faces


class FaceCachePruneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "cache"
        (self.root / "packs").mkdir(parents=True)
        (self.root / "models").mkdir()

    def save(self, name, data, *, models=False, age=1):
        path = self.root / ("models" if models else "packs") / name
        faces._save(path, data)
        os.utime(path, (age, age))
        return path

    def test_under_budget_skips_all_payload_hashes_without_changing_cache_files(self):
        self.save("pack_a", b"a" * 2048)
        self.save("ch0207_" + "a" * 24 + ".unity", b"b" * 1024, models=True)
        invalid = self.save("invalid", b"corrupt")
        Path(str(invalid) + ".json").unlink()
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(faces, "_cached", side_effect=AssertionError("Below-budget pruning needs no payload read")):
            faces._prune_cache(self.root, deadline=time.monotonic() + 5)
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_equal_budget_also_needs_no_hashes(self):
        self.save("pack", b"1234")
        with patch.object(faces, "MAX_CACHE_BYTES", 4), \
                patch.object(faces, "_cached", side_effect=AssertionError("Exactly full cache needs no eviction")):
            faces._prune_cache(self.root)

    def test_selected_file_still_rejects_same_size_tampering_after_fast_prune(self):
        target = self.save("pack", b"1234")
        target.write_bytes(b"4321")
        with patch.object(faces, "_cached", wraps=faces._cached) as cached:
            faces._prune_cache(self.root)
            cached.assert_not_called()
            self.assertIsNone(faces._cached(target, 4))
            self.assertEqual(cached.call_count, 1)
        self.assertTrue(target.is_file())

    def test_over_budget_keeps_full_validation_lru_and_protection(self):
        protected = self.save("old", b"1234", age=1)
        removed = self.save("new", b"5678", age=2)
        invalid = self.save("unverified", b"x" * 128, age=3)
        Path(str(invalid) + ".json").unlink()
        with patch.object(faces, "MAX_CACHE_BYTES", 4), \
                patch.object(faces, "_cached", wraps=faces._cached) as cached:
            faces._prune_cache(self.root, protected=(str(protected),))
        self.assertEqual({Path(call.args[0]).name for call in cached.call_args_list}, {"old", "new", "unverified"})
        self.assertTrue(protected.is_file())
        self.assertFalse(removed.exists())
        self.assertFalse(Path(str(removed) + ".json").exists())
        # Invalid/unowned bytes were never eligible for deletion in this module.
        self.assertTrue(invalid.is_file())

    def test_over_budget_upper_bound_does_not_delete_a_valid_under_budget_subset(self):
        valid = self.save("valid", b"1234")
        invalid = self.save("invalid", b"x" * 128)
        invalid.write_bytes(b"z" * 128)
        with patch.object(faces, "MAX_CACHE_BYTES", 4), \
                patch.object(faces, "_cached", wraps=faces._cached) as cached:
            faces._prune_cache(self.root)
        self.assertEqual(cached.call_count, 2)
        self.assertTrue(valid.exists())
        self.assertTrue(invalid.exists())

    def test_symlinks_and_unowned_library_files_are_not_counted_or_removed(self):
        outside = self.root.parent / "outside"
        outside.write_bytes(b"user-owned")
        (self.root / "packs" / "linked").symlink_to(outside)
        unowned = self.root / "models" / "original_costume.unity"
        unowned.write_bytes(b"library data")
        with patch.object(faces, "MAX_CACHE_BYTES", 0), \
                patch.object(faces, "_cached", side_effect=AssertionError("No managed regular files")):
            faces._prune_cache(self.root)
        self.assertEqual(outside.read_bytes(), b"user-owned")
        self.assertEqual(unowned.read_bytes(), b"library data")

    def test_expired_deadline_is_not_bypassed_by_the_fast_path(self):
        self.save("pack", b"1234")
        with self.assertRaises(faces.FaceUnavailable):
            faces._prune_cache(self.root, deadline=time.monotonic() - 1)


if __name__ == "__main__":
    unittest.main()
