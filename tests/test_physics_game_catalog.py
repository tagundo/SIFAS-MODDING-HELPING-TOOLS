"""Game solver inputs preserve the serialized manager graph and unknowns."""
import copy
from pathlib import Path
import tempfile
import unittest

from generate_viewer_physics_fixture import fixture_bytes
from webtools.core import model_edits, model_viewer, viewer_physics


class GamePhysicsCatalogueTests(unittest.TestCase):
    def prepare(self, *, native):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name).resolve() / "source.unity"
        path.write_bytes(fixture_bytes(native=native))
        preview = model_viewer.prepare([str(path)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        metadata = model_edits.register_session(preview["id"], [str(path)], preview["rig"])
        return path, preview, metadata["physics"]

    def test_original_flags_and_order_survive_the_real_preview_session(self):
        path, preview, catalog = self.prepare(native=True)
        self.assertTrue(catalog["native"]["available"], catalog["native"])
        manager = catalog["managers"][0]
        self.assertEqual(manager["bones"], ["0:0:221"])
        self.assertEqual(manager["colliders"], ["0:0:224", "0:0:223"])
        self.assertEqual(manager["lodBones"], [])
        self.assertEqual(manager["kneeTransforms"], [])
        self.assertIs(manager["enableJob"], False)
        self.assertIs(manager["enableLod"], False)
        self.assertIs(manager["enableAutoStart"], False)
        self.assertIsInstance(manager["node"], int)
        direct = viewer_physics.catalog_sources([{"raw": path.read_bytes()}], preview["rig"]["bones"])
        self.assertEqual(direct, catalog, "HTTP/session and direct catalogue use the same owner")
        self.assertEqual(path.read_bytes(), fixture_bytes(native=True))

    def test_legacy_source_missing_native_facts_is_explicitly_unavailable(self):
        _, _, catalog = self.prepare(native=False)
        self.assertTrue(catalog["available"], "Enhanced preview remains available")
        self.assertFalse(catalog["native"]["available"])
        self.assertIn("0:0:228:enableJob", catalog["native"]["missing"])
        self.assertIn("0:0:228:kneeTransforms", catalog["native"]["missing"])

    def test_unresolved_slots_are_not_compacted_or_rebound_to_another_source(self):
        _, preview, catalog = self.prepare(native=True)
        raw = fixture_bytes(native=True)
        info = model_edits._inspect(raw)
        manager = info["objects"][(0, 228)]
        tree = manager.read_typetree()
        tree["bones"].insert(0, {"m_FileID": 0, "m_PathID": 0})
        tree["colliders"][0]["m_FileID"] = 1
        manager.save_typetree(tree)
        info = model_edits._inspect(info["env"].file.save(packer="original"))
        managers = viewer_physics.native_managers(info, 0, preview["rig"]["bones"])
        self.assertEqual(managers[0]["bones"], [None, "0:0:221"])
        self.assertEqual(managers[0]["colliders"], [None, "0:0:223"])
        ready = viewer_physics.native_readiness(catalog["components"], managers)
        self.assertFalse(ready["available"])
        other = viewer_physics.native_managers(model_edits._inspect(raw), 1,
            [dict(row, sourceIndex=1) for row in preview["rig"]["bones"]])
        self.assertEqual(other[0]["bones"], ["1:0:221"])
        self.assertEqual(other[0]["colliders"], ["1:0:224", "1:0:223"])
        self.assertFalse(viewer_physics.native_readiness(copy.deepcopy(catalog["components"]), other)["available"])

    def test_knee_discovery_uses_source_activation_and_original_dfs_last_match(self):
        _, preview, _ = self.prepare(native=True)
        info = model_edits._inspect(fixture_bytes(native=True))
        for ident, name, enabled in [(8, "Source_LeftUpLeg", True), (208, "Later_LeftUpLeg", False), (210, "Source_RightUpLeg", True)]:
            obj = info["objects"][(0, ident)]
            tree = obj.read_typetree()
            tree.update(m_Name=name, m_IsActive=enabled)
            obj.save_typetree(tree)
        raw = info["env"].file.save(packer="original")
        info = model_edits._inspect(raw)
        node = {row["transformId"]: row["node"] for row in preview["rig"]["bones"]}
        managers = viewer_physics.native_managers(info, 0, preview["rig"]["bones"])
        self.assertEqual(managers[0]["kneeTransforms"], [])
        self.assertEqual(managers[0]["resolvedKneeTransforms"], [node["9"], node["211"]])
        obj = info["objects"][(0, 208)]
        tree = obj.read_typetree(); tree["m_IsActive"] = True; obj.save_typetree(tree)
        info = model_edits._inspect(info["env"].file.save(packer="original"))
        managers = viewer_physics.native_managers(info, 0, preview["rig"]["bones"])
        self.assertEqual(managers[0]["resolvedKneeTransforms"], [node["209"], node["211"]])


if __name__ == "__main__":
    unittest.main()
