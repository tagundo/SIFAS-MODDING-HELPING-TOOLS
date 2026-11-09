"""Costume exceptions are obtained from verified identities, not filenames."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from webtools.core import viewer_physics_runtime


class GamePhysicsRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        folder = self.root / "assets/db/gl"
        folder.mkdir(parents=True)
        with sqlite3.connect(folder / "masterdata.db") as database:
            database.execute("CREATE TABLE m_suit_custom3d (suit_master_id INTEGER, skirtsafe_disable INTEGER)")
            database.executemany("INSERT INTO m_suit_custom3d VALUES (?,?)", [(402022003, 1), (123, None), (999, 2)])
            database.execute("CREATE TABLE m_live_visible_definition (live_m_id INTEGER, safe_swing_bone INTEGER)")
            database.executemany("INSERT INTO m_live_visible_definition VALUES (?,?)", [(12007, 1), (12034, 0), (12001, None)])
        self.physics = {"managers": [{"sourceIndex": 0}, {"sourceIndex": 1}]}

    def describe(self, bindings, *, context=None):
        with mock.patch("webtools.core.viewer_mod_flow.cached_receipts", return_value=()), \
                mock.patch("webtools.core.viewer_mod_sources.game_context", return_value=bindings):
            return viewer_physics_runtime.describe(context or {}, self.physics,
                repo_root=self.root, cache_root=self.root / "cache")

    def binding(self, source, suit):
        return {"source": source, "record": {"region": "gl", "suit_id": suit}}

    def test_verified_exception_is_scoped_to_its_own_model(self):
        value = self.describe([self.binding(0, 402022003), self.binding(1, 456)])
        self.assertEqual([row["skirtsafeDisable"] for row in value["sources"]], [True, False])
        self.assertTrue(all(row["known"] for row in value["sources"]))

    def test_absent_and_nullable_rows_have_the_original_false_default(self):
        value = self.describe([self.binding(0, 456), self.binding(1, 123)])
        self.assertEqual([row["skirtsafeDisable"] for row in value["sources"]], [False, False])
        self.assertTrue(all(row["known"] for row in value["sources"]))

    def test_unverified_filename_and_invalid_database_value_stay_unknown(self):
        value = self.describe([], context={"containers": [{"name": "402022003.unity"}]})
        self.assertTrue(all(not row["known"] and row["skirtsafeDisable"] is None for row in value["sources"]))
        value = self.describe([self.binding(0, 999)])
        self.assertFalse(value["sources"][0]["known"])
        self.assertIsNone(value["sources"][0]["skirtsafeDisable"])

    def test_changed_or_conflicting_import_receipt_never_becomes_a_guess(self):
        with mock.patch("webtools.core.viewer_mod_flow.cached_receipts", return_value=()), \
                mock.patch("webtools.core.viewer_mod_sources.game_context", side_effect=ValueError("Changed source")):
            value = viewer_physics_runtime.describe({}, self.physics,
                repo_root=self.root, cache_root=self.root / "cache")
        self.assertTrue(all(not row["known"] for row in value["sources"]))

    def test_song_switch_and_costume_exception_are_distinct_native_inputs(self):
        for live, flag in [(12007, True), (12034, False), (12001, False), (99999, False)]:
            with self.subTest(live=live):
                value = viewer_physics_runtime.motion_settings(repo_root=self.root,
                    record={"category": "mv", "region": "gl", "live_id": live})
                self.assertTrue(value["safeSwingBoneKnown"])
                self.assertIs(value["safeSwingBone"], flag)
        value = viewer_physics_runtime.motion_settings(repo_root=self.root,
            record={"category": "mv", "region": "gl", "live_id": None})
        self.assertFalse(value["safeSwingBoneKnown"])
        self.assertIsNone(value["safeSwingBone"])
        self.assertEqual(viewer_physics_runtime.motion_settings(repo_root=self.root,
            record={"category": "voice"}), {"profile": "navi", "safeSwingBoneKnown": True, "safeSwingBone": False})


if __name__ == "__main__":
    unittest.main()
