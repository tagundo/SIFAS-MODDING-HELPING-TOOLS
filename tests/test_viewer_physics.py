"""Serialized physics editing, recipes and counterpart correspondence."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_edits as edits, model_viewer, viewer_physics
from generate_viewer_physics_fixture import fixture_bytes


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fixture_bytes()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "original.unity"
        self.source.write_bytes(self.raw)
        prepared = model_viewer.prepare([str(self.source)], rigged=True, face_context={"enabled": False, "allow_download": False})
        self.token = prepared["id"]
        self.metadata = edits.register_session(self.token, [str(self.source)], prepared["rig"])
        self.catalog = self.metadata["physics"]
        self.bone = next(c for c in self.catalog["components"] if c["kind"] == "bone")
        self.colliders = [c for c in self.catalog["components"] if c["kind"] == "collider"]

    def state(self, *changes):
        return {"version": 1, "edits": [], "savedSettingsEnabled": True, "unsupported": [], "physics": list(changes)}

    def test_catalog_verifies_classes_source_ids_and_capsule_ends(self):
        self.assertEqual(len(self.catalog["components"]), 3)
        self.assertEqual(self.bone["group"], "breast")
        self.assertIsInstance(self.bone["node"], int)
        self.assertEqual({c["group"] for c in self.colliders}, {"thighs"})
        self.assertEqual(self.colliders[0]["sibling"], self.colliders[1]["id"])
        self.assertNotIn(str(self.base), json.dumps(self.metadata))
        self.assertEqual(viewer_physics.recommendations()[1]["stiffnessForce"], .02)
        simulation = self.bone["simulation"]
        self.assertAlmostEqual(simulation["radius"], .02)
        self.assertEqual(simulation["boneAxis"], [-1., 0., 0.])
        self.assertAlmostEqual(simulation["childOffset"][0], -.08)
        self.assertEqual(simulation["colliders"], ["0:0:224"])
        self.assertNotEqual(simulation["childNode"], self.bone["node"])
        self.assertEqual(simulation["manager"], "0:0:228")
        self.assertEqual(simulation["order"], 0)

    def test_manager_bits_resolve_when_variant_omits_pointer_membership(self):
        records = viewer_physics.inspect_info(edits._inspect(fixture_bytes(manager_membership=True)), 0, [])
        bone = next(r for r in records if r["kind"] == "bone")
        self.assertEqual(bone["simulation"]["colliders"], ["0:0:224"])

    def test_legacy_schema_uses_only_verified_native_constructor_defaults(self):
        import struct
        reference = json.loads((Path(__file__).parent / "fixtures/game_physics_native_constructor.json").read_text())
        self.assertEqual(reference["status"], "RETURNED")
        self.assertEqual(reference["instructions"], 114)
        self.assertTrue(reference["serializedFieldAttributes"]["noFormerlySerializedAs"])
        info = edits._inspect(fixture_bytes(native=True))
        bone_obj = info["objects"][(0, 221)]
        self.assertNotIn("kneeSpaceOffsetForce", bone_obj.read_typetree())
        records = viewer_physics.inspect_info(info, 0, [])
        simulation = next(r for r in records if r["kind"] == "bone")["simulation"]
        self.assertEqual(set(simulation["constructorDefaults"]), set(reference["appliedToLegacyPreviewOnly"]))
        for name in reference["appliedToLegacyPreviewOnly"]:
            self.assertEqual(struct.pack("<f", simulation[name]).hex(), reference["fields"][name]["float32le"])
        # These remain preview/runtime metadata: the old serialized schema and
        # source bytes are not rewritten to manufacture fields absent from it.
        self.assertNotIn("kneeSpaceOffsetForce", bone_obj.read_typetree())
        self.assertNotIn("enableLod", self.bone["simulation"])
        from UnityPy.helpers.TypeTreeNode import TypeTreeNode
        tree = bone_obj.read_typetree()
        tree.update(kneeSpaceOffsetForce=float("nan"))
        node = bone_obj.serialized_type.node
        field = TypeTreeNode(**next(child for child in node.m_Children if child.m_Name == "radius").to_dict())
        field.m_Name = "kneeSpaceOffsetForce"
        bone_obj.serialized_type.node = TypeTreeNode(**{**node.to_dict(), "m_Children": list(node.m_Children) + [field]})
        bone_obj.save_typetree(tree)
        invalid_info = edits._inspect(info["env"].file.save(packer="original"))
        invalid = next(r for r in viewer_physics.inspect_info(invalid_info, 0, []) if r["kind"] == "bone")["simulation"]
        self.assertNotIn("kneeSpaceOffsetForce", invalid)
        self.assertNotIn("kneeSpaceOffsetForce", invalid["constructorDefaults"])

    def test_breast_size_tiers_match_the_existing_tool_and_texture_identity(self):
        import sifas_breast_tuner as tuner
        reference = [{"scale": list(scale), "tier": tier} for _, scale, tier in tuner.BREAST_PRESETS_ALL]
        recommendations = self.catalog["breastSizeRecommendations"]
        self.assertEqual(recommendations["presets"], reference)
        self.assertEqual(recommendations["stockTolerance"], .03)
        info = edits._inspect(self.raw)
        texture = next(obj for obj in info["objects"].values() if obj.type.name == "Texture2D")
        original = texture.read_typetree()
        original["m_Name"] = "ch0209_co0001_body"
        texture.save_typetree(original)
        changed = edits._inspect(info["env"].file.save(packer="original"))
        records = viewer_physics.inspect_info(changed, 0, [])
        breast = next(r for r in records if r["kind"] == "bone")
        self.assertEqual(breast["stockJiggleTier"], 0)
        self.assertNotIn("stockJiggleTier", self.bone, "A path or model filename cannot invent stock character identity")

    @unittest.skipUnless(shutil.which("node"), "Node is required for the enhanced Three.js solver regression")
    def test_enhanced_solver_constrained_surfaces_and_live_mesh_edits(self):
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("viewer_physics_solver_node.js"))],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ENHANCED_PHYSICS_COUPLED_AND_EDIT_INVALIDATION_PASS", result.stdout)
        timing = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("viewer_physics_timing_node.js"))],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(timing.returncode, 0, timing.stdout)
        self.assertIn("ENHANCED_PHYSICS_TIMING_PASS", timing.stdout)

    def test_physics_only_export_roundtrips_fields_and_preserves_geometry_originals(self):
        state = self.state({"id": self.bone["id"], "values": {"stiffnessForce": .05, "dragForce": .5}},
                           {"id": self.colliders[0]["id"], "values": {"radius": .12, "offset": [.02, -.03, .04]}})
        output = edits.export(self.token, state, self.base / "out")
        raw = Path(output["preview_paths"][0]).read_bytes()
        info = edits._inspect(raw)
        physics = viewer_physics.inspect_info(info, 0, [])
        by_id = {c["id"]: c for c in physics}
        self.assertAlmostEqual(by_id[self.bone["id"]]["values"]["dragForce"], .5)
        self.assertAlmostEqual(by_id[self.colliders[0]["id"]]["values"]["radius"], .12)
        self.assertEqual(by_id[self.colliders[1]["id"]]["values"], self.colliders[1]["values"])
        self.assertEqual({k: v for k, v in by_id[self.bone["id"]]["simulation"].items() if k != "childNode"},
                         {k: v for k, v in self.bone["simulation"].items() if k != "childNode"})
        original = edits._inspect(self.raw)
        for key, obj in original["objects"].items():
            if obj.type.name in ("Mesh", "Transform", "Texture2D", "SkinnedMeshRenderer"):
                self.assertEqual(info["objects"][key].get_raw_data(), obj.get_raw_data())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(output["original_paths"][0]).read_bytes(), self.raw)
        self.assertEqual(edits.restore(self.token, output["recipe"])["physics"], edits.validate_state(self.token, state)["physics"])

    def test_absolute_edits_do_not_compound_and_restore_from_preserved_original(self):
        state = self.state({"id": self.bone["id"], "values": {"lowRotationLimit": [-10., -20., -25.], "highRotationLimit": [10., 20., 25.]}})
        a = edits.export(self.token, state, self.base / "a")
        b = edits.export(self.token, state, self.base / "b")
        self.assertEqual(Path(a["preview_paths"][0]).read_bytes(), Path(b["preview_paths"][0]).read_bytes())
        original = a["original_paths"][0]
        prepared = model_viewer.prepare([original], rigged=True, face_context={"enabled": False, "allow_download": False})
        edits.register_session(prepared["id"], [original], prepared["rig"])
        restored = edits.restore(prepared["id"], a["recipe"])
        c = edits.export(prepared["id"], restored, self.base / "c")
        self.assertEqual(Path(a["preview_paths"][0]).read_bytes(), Path(c["preview_paths"][0]).read_bytes())

    def test_rejects_unknown_ids_duplicate_edits_nonfinite_and_reversed_limits(self):
        invalid = [
            [{"id": "7:0:221", "values": {"dragForce": .5}}],
            [{"id": self.bone["id"], "values": {"dragForce": .5}}] * 2,
            [{"id": self.bone["id"], "values": {"dragForce": float("nan")}}],
            [{"id": self.bone["id"], "values": {"dragForce": 1.1}}],
            [{"id": self.bone["id"], "values": {"lowRotationLimit": [40., 0., 0.]}}],
            [{"id": self.colliders[0]["id"], "values": {"radius": -1.}}],
            [{"id": self.bone["id"], "values": {"m_Script": 17}}],
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                edits.validate_state(self.token, self.state(*rows))

    def test_empty_snapshot_requires_explicit_allow_empty(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            edits.validate_state(self.token, self.state())
        result = edits.export(self.token, self.state(), self.base / "snapshot", allow_empty=True)
        self.assertEqual(Path(result["preview_paths"][0]).read_bytes(), self.raw)

    def test_native_counterpart_maps_physics_by_unique_full_bone_hierarchy(self):
        from webtools.core.viewer_mod_pair_edits import _map_state
        context = edits.mod_source_context(self.token)
        state = edits.validate_state(self.token, self.state({"id": self.bone["id"], "values": {"dragForce": .6}}))
        mapped, proof = _map_state(context, state, 0, edits._inspect(self.raw), context, edits._inspect(self.raw))
        self.assertEqual(mapped["physics"], state["physics"])
        self.assertEqual(proof[0]["sourcePhysics"], self.bone["id"])
        ambiguous = copy.deepcopy(context)
        ambiguous["physics"]["components"].append(copy.deepcopy(self.bone))
        with self.assertRaisesRegex(ValueError, "unique matching"):
            _map_state(context, state, 0, edits._inspect(self.raw), ambiguous, edits._inspect(self.raw))

    def test_mesh_delete_retains_simultaneous_physics_edits(self):
        from webtools.core import viewer_mesh_tools as mesh
        ident = mesh.inspect(self.token)["meshes"][0]["mesh"]
        body = self.state({"id": self.bone["id"], "values": {"dragForce": .7}})
        result = mesh.export(self.token, {"version": 1, "meshes": [{"mesh": ident, "deleteFaces": [0]}]}, self.base / "mesh", body_state=body)
        raw = Path(result["preview_paths"][0]).read_bytes()
        rows = viewer_physics.inspect_info(edits._inspect(raw), 0, [])
        self.assertAlmostEqual(next(c for c in rows if c["kind"] == "bone")["values"]["dragForce"], .7, places=6)
        _, records = mesh._mesh_records(raw, 0)
        self.assertEqual(len(mesh._triangles(records[0][2], 6)[0]), 3)

    def test_physics_only_mod_package_dispatches_real_native_counterpart_mapping(self):
        import UnityPy
        import unity_costumemod_packer as packer
        from webtools.core import viewer_archive, viewer_mod_flow as flow, viewer_mod_pair_edits as paired
        from webtools.jobs import Job
        env = UnityPy.load(self.raw)
        for obj in env.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree(); tree["m_Name"] = "ch0006_co0123_body"; obj.save_typetree(tree)
        env.file._m_target_platform = 13
        android = env.file.save(packer="original")
        env.file._m_target_platform = 9
        ios = env.file.save(packer="original")
        import ast
        manifest = {node.targets[0].id: ast.literal_eval(node.value)
                    for node in ast.parse(packer.generate_modinstall_txt("Physics", "android.unity", "thumbnail.png", 6)).body}
        manifest["costume_file_ios"] = "ios.unity"
        source = self.base / "dual-platform.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("android.unity", android)
            archive.writestr("ios.unity", ios)
            archive.writestr("thumbnail.png", packer.make_name_thumbnail_png("Physics", 32, 6))
            archive.writestr("modinstall.txt", "\n".join(key + " = " + repr(value) for key, value in manifest.items()) + "\n")
        with viewer_archive.expand_inputs([str(source)], self.base / "extract") as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": False, "allow_download": False})
            metadata = edits.register_session(prepared["id"], expanded.paths, prepared["rig"], originals=[str(source)],
                origins=expanded.origins, archive_members=expanded.archive_members)
        bone = next(c for c in metadata["physics"]["components"] if c["kind"] == "bone")
        state = self.state({"id": bone["id"], "values": {"dragForce": .65}})
        runtime = self.base / "runtime"; runtime.mkdir()
        with patch.object(paired, "apply_pair_edits", wraps=paired.apply_pair_edits) as dispatch:
            result = flow.create_package(prepared["id"], state, output_root=self.base / "mod-out", repo_root=runtime,
                cache_root=self.base / "cache", display_name="Physics native versions", character_id=6, job=Job("physics-package", "viewer_mod_package"))
        dispatch.assert_called_once()
        self.assertTrue(result["paired_edits"])
        with zipfile.ZipFile(result["mod_package"]["package_path"]) as archive:
            import ast
            manifest = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            for field in ("costume_file", "costume_file_ios"):
                rows = viewer_physics.inspect_info(edits._inspect(archive.read(manifest[field])), 0, [])
                self.assertAlmostEqual(next(c for c in rows if c["kind"] == "bone")["values"]["dragForce"], .65, places=6)


if __name__ == "__main__":
    unittest.main()
