"""Persistent body export checks against original neutral serialized Unity data."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_edits as edits

try:
    import numpy as np
    import UnityPy
    from webtools.core import model_viewer, viewer_archive
    from sifas_mesh_baker import stream_layout, read_attr, ATTR_POS, ATTR_NORMAL
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "UnityPy and numpy are needed for serialized body editing checks")
class ModelEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Path(__file__).parent / "fixtures" / "viewer_persistence.unity"
        cls.raw = cls.fixture.read_bytes()
        cls.rig = model_viewer.prepare([str(cls.fixture.resolve())], rigged=True,
            face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "costume.unity"
        self.source.write_bytes(self.raw)
        with edits._LOCK:
            edits._SESSIONS.clear()
        self.token = secrets.token_hex(16)
        self.metadata = edits.register_session(self.token, [str(self.source)], self.rig)
        self.nodes = {row["name"]: row for row in self.metadata["nodes"]}

    def state(self, *changes, **extra):
        return {"version": 1, "savedSettingsEnabled": True,
                "edits": list(changes), **extra}

    def change(self, name="LeftUpLeg", method="auto", **properties):
        return {"node": self.nodes[name]["node"], "method": method, **properties}

    def save(self, state, directory=None):
        return edits.export(self.token, state, directory or self.base / "out")

    def inspect(self, path):
        return edits._inspect(Path(path).read_bytes())

    def transform(self, info, name):
        return next(key for key, value in info["names"].items() if value == name)

    def mesh(self, info):
        obj = next(obj for obj in info["env"].objects if obj.type.name == "Mesh")
        tree = obj.read_typetree()
        count, channels, stride, start, _ = stream_layout(tree)
        raw = np.frombuffer(tree["m_VertexData"]["m_DataSize"], np.uint8)
        return tree, read_attr(raw, ATTR_POS, channels, stride, start, count)

    def test_metadata_is_content_bound_and_recommends_only_audited_scale_scope(self):
        self.assertTrue(self.metadata["available"])
        self.assertEqual(self.nodes["LeftUpLeg"]["recommendedMethod"], "mesh")
        self.assertEqual(self.nodes["BreastSize"]["recommendedMethod"], "node")
        self.assertEqual(self.nodes["LeftUpLeg"]["baseline"]["scale"][0],
                         edits._inspect(self.raw)["effective"][(0, 7)]["scale"][0])
        self.assertNotIn(str(self.base), json.dumps(self.metadata))
        before = self.raw
        self.source.write_bytes(before + b"changed-after-preview")
        with self.assertRaisesRegex(edits.ModelEditError, "changed while"):
            edits.register_session(secrets.token_hex(16), [str(self.source)], self.rig)

    def test_node_export_changes_only_requested_endpoint_not_vertices_or_other_fields(self):
        baseline = edits._inspect(self.raw)
        result = self.save(self.state(self.change("BreastSize", "node", scale=[1.2, 1.1, .9])))
        output = self.inspect(result["preview_paths"][0])
        key = self.transform(output, "BreastSize")
        self.assertTrue(np.allclose(output["effective"][key]["scale"], [1.2, 1.1, .9]))
        self.assertEqual(output["effective"][key]["position"], baseline["effective"][key]["position"])
        self.assertEqual(output["effective"][key]["rotation"], baseline["effective"][key]["rotation"])
        self.assertTrue(np.array_equal(self.mesh(baseline)[1], self.mesh(output)[1]))
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(result["original_paths"][0]).read_bytes(), self.raw)

    def test_mesh_conversion_migrates_existing_nonunit_endpoint_without_slider_change(self):
        node = self.nodes["LeftUpLeg"]
        result = self.save(self.state(self.change(method="mesh", scale=node["baseline"]["scale"])))
        output = self.inspect(result["preview_paths"][0]); old = edits._inspect(self.raw)
        key = self.transform(output, "LeftUpLeg")
        self.assertEqual(output["effective"][key]["scale"], [1., 1., 1.])
        self.assertFalse(np.allclose(self.mesh(old)[1], self.mesh(output)[1]))
        breast = self.transform(output, "BreastSize")
        self.assertEqual(output["effective"][breast], old["effective"][breast])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_hybrid_writes_each_kind_once_and_repeated_exports_do_not_accumulate(self):
        state = self.state(self.change(scale=[1.6, 1.2, 1.1]),
                           self.change("BreastSize", "node", scale=[1.25, .9, 1.]))
        first, second = self.save(state), self.save(state)
        self.assertNotEqual(first["preview_paths"], second["preview_paths"])
        self.assertEqual(Path(first["preview_paths"][0]).read_bytes(), Path(second["preview_paths"][0]).read_bytes())
        self.assertEqual(first["recipe"], second["recipe"])
        info = self.inspect(first["preview_paths"][0])
        self.assertEqual(info["effective"][self.transform(info, "LeftUpLeg")]["scale"], [1., 1., 1.])
        self.assertTrue(np.allclose(info["effective"][self.transform(info, "BreastSize")]["scale"], [1.25, .9, 1.]))
        restored = edits.restore(self.token, first["recipe"])
        self.assertEqual(restored, edits.validate_state(self.token, state))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_node_position_reflects_x_and_rotation_uses_unity_euler(self):
        result = self.save(self.state(self.change("BreastSize", "node",
            position=[.12, .6, -.03], rotation=[15., 25., 35.])))
        info = self.inspect(result["preview_paths"][0]); key = self.transform(info, "BreastSize")
        self.assertTrue(np.allclose(info["effective"][key]["position"], [-.12, .6, -.03]))
        self.assertTrue(np.allclose(info["effective"][key]["rotation"], [15., 25., 35.]))

    def test_auto_position_rotation_require_explicit_method(self):
        for kind in ("position", "rotation"):
            with self.subTest(kind=kind), self.assertRaisesRegex(edits.ModelEditError, "explicitly"):
                edits.validate_state(self.token, self.state(self.change("BreastSize", **{kind: [1, 2, 3]})))

    def test_invalid_states_do_not_create_outputs(self):
        states = [None, {"version": 1, "edits": []},
                  self.state(self.change(scale=[1, 1, 1]), savedSettingsEnabled=False),
                  self.state(self.change(scale=[1, 1, 1]), unsupported=["expression"]),
                  self.state(self.change(scale=[1, True, 1])),
                  self.state(self.change(scale=[1, float("nan"), 1])),
                  self.state(self.change(scale=[1, 0, 1])),
                  self.state(self.change(scale=[1, 1])),
                  self.state(self.change(scale=[1, 1, 1]), unexpected="ignored"),
                  self.state(self.change(scale=[1, 1, 1]), self.change(scale=[2, 2, 2])),
                  self.state({"node": 99999, "scale": [1, 1, 1]}),
                  self.state(self.change("BreastSize", "node", scale=[2, 2, 2], compensate=True,
                                         compensationTargets=[self.nodes["LeftUpLeg"]["node"]])),
                  self.state(self.change(scale=[2, 2, 2], compensate=True, compensationTargets=[[1]]))]
        for value in states:
            with self.subTest(value=value), self.assertRaises(edits.ModelEditError):
                self.save(value)
        self.assertFalse((self.base / "out").exists())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_non_descendant_compensation_is_rejected_before_publication(self):
        state = self.state(self.change(scale=[1.5, 1.1, 1.], compensate=True,
                                      compensationTargets=[self.nodes["Move"]["node"]]))
        with self.assertRaisesRegex(edits.ModelEditError, "descendant"):
            self.save(state)
        self.assertFalse((self.base / "out").exists())

    def test_real_child_compensation_survives_rotation_and_reload(self):
        state = self.state(self.change(scale=[1.8, 1.1, .85], compensate=True,
                                      compensationTargets=[self.nodes["BreastSize"]["node"]]))
        result = self.save(state)
        tree, positions = self.mesh(self.inspect(result["preview_paths"][0]))
        self.assertTrue(np.isfinite(positions).all())
        self.assertGreater(len(result["summary"][0]["meshes"]), 0)
        self.assertEqual(tree["m_BindPose"], self.mesh(edits._inspect(self.raw))[0]["m_BindPose"])

    def test_changed_original_rejects_export_and_preserves_existing_output(self):
        output = self.base / "out"; output.mkdir(); sentinel = output / "keep.txt"; sentinel.write_text("existing")
        self.source.write_bytes(self.raw + b"changed")
        with self.assertRaisesRegex(edits.ModelEditError, "changed after"):
            self.save(self.state(self.change(scale=[1.5, 1, 1])), output)
        self.assertEqual(sentinel.read_text(), "existing")
        self.assertEqual(list(output.iterdir()), [sentinel])

    def test_recipe_rejects_other_bytes_but_is_portable_across_renamed_originals(self):
        result = self.save(self.state(self.change(scale=[1.5, 1.1, 1.])))
        renamed = self.base / "renamed-copy.unity"; renamed.write_bytes(self.raw)
        token = secrets.token_hex(16)
        edits.register_session(token, [str(renamed)], self.rig)
        self.assertEqual(edits.restore(token, result["recipe"]), result["recipe"]["state"])
        broken = copy.deepcopy(result["recipe"]); broken["sources"][0]["sha256"] = "0"*64
        with self.assertRaisesRegex(edits.ModelEditError, "different original"):
            edits.restore(token, broken)

    def test_zip_exports_only_selected_member_and_preserves_manifest_and_variant(self):
        archive = self.base / "rina.zip"
        with zipfile.ZipFile(archive, "w") as out:
            out.writestr("primary.unity", self.raw)
            out.writestr("unmasked.unity", self.raw)
            out.writestr("modinstall.txt", "costume_file='primary.unity'\nrina_unmask_costume_file='unmasked.unity'\n")
            out.writestr("untouched.bin", b"keep these bytes")
            out.comment = b"preserved comment"
        before = archive.read_bytes(); token = secrets.token_hex(16)
        with viewer_archive.expand_inputs([str(archive)], self.base / "cache",
                variant_choices={str(archive): "unmasked"}) as expanded:
            result = model_viewer.prepare(expanded.paths, rigged=True,
                face_context={"enabled": False, "allow_download": False})
            metadata = edits.register_session(token, expanded.paths, result["rig"],
                originals=[str(archive)], origins=expanded.origins,
                archive_members=expanded.archive_members, variants={str(archive): "unmasked"})
        node = next(n for n in metadata["nodes"] if n["name"] == "LeftUpLeg")
        saved = edits.export(token, self.state({"node": node["node"], "method": "mesh", "scale": [1.6, 1.2, 1.]}), self.base / "zip-output")
        with zipfile.ZipFile(archive) as old, zipfile.ZipFile(saved["preview_paths"][0]) as new:
            self.assertEqual(old.namelist(), new.namelist())
            self.assertEqual(old.comment, new.comment)
            for name in old.namelist():
                if name != "unmasked.unity":
                    self.assertEqual(old.read(name), new.read(name))
                else:
                    self.assertNotEqual(old.read(name), new.read(name))
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(saved["preview_variants"], {"0": "unmasked"})
        self.assertEqual(saved["original_variants"], {"0": "unmasked"})

    def test_multi_input_filename_collisions_and_recipe_restore_preserve_every_original(self):
        paths = []
        for i, name in enumerate(("4-model.unity", "model.unity", "model.unity", "model.unity")):
            folder = self.base / str(i); folder.mkdir(); path = folder / name; path.write_bytes(self.raw); paths.append(str(path))
        result = model_viewer.prepare(paths, rigged=True, face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16); metadata = edits.register_session(token, paths, result["rig"])
        left = next(n for n in metadata["nodes"] if n["name"] == "LeftUpLeg" and n["sourceIndex"] == 0)
        saved = edits.export(token, self.state({"node": left["node"], "method": "mesh", "scale": [1.6, 1., 1.]}), self.base / "multi-output")
        self.assertEqual(len(set(saved["preview_paths"])), 4)
        self.assertEqual(len(set(saved["original_paths"])), 4)
        self.assertTrue(all(Path(p).read_bytes() == self.raw for p in saved["original_paths"]))
        other = model_viewer.prepare(saved["original_paths"], rigged=True, face_context={"enabled": False, "allow_download": False})
        new_token = secrets.token_hex(16); edits.register_session(new_token, saved["original_paths"], other["rig"])
        self.assertEqual(edits.restore(new_token, saved["recipe"]), saved["recipe"]["state"])
        for p in paths:
            self.assertEqual(Path(p).read_bytes(), self.raw)

    def test_active_export_snapshot_survives_pruning_and_concurrent_save_is_bounded(self):
        session = edits._session(self.token)
        session["busy"].acquire()
        self.addCleanup(lambda: session["busy"].release() if session["busy"].locked() else None)
        session["expires"] = 0
        with edits._LOCK:
            edits._prune(10**12)
        self.assertIs(edits._session(self.token), session)
        with self.assertRaisesRegex(edits.ModelEditError, "already being saved"):
            self.save(self.state(self.change(scale=[1.6, 1., 1.])))

    def test_disabled_or_inactive_saved_settings_fail_closed(self):
        for mode in ("disabled", "inactive_ancestor"):
            with self.subTest(mode=mode):
                env = UnityPy.load(self.raw)
                for obj in env.objects:
                    tree = obj.read_typetree()
                    if mode == "disabled" and obj.type.name == "MonoBehaviour":
                        tree["m_Enabled"] = 0; obj.save_typetree(tree)
                    if mode == "inactive_ancestor" and obj.type.name == "GameObject" and tree["m_Name"] == "SyntheticRig":
                        tree["m_IsActive"] = False; obj.save_typetree(tree)
                with self.assertRaisesRegex(edits.ModelEditError, "Disabled|Inactive"):
                    edits._inspect(env.file.save())

    def test_atomic_failure_never_publishes_partial_folder(self):
        directory = self.base / "failed"
        with patch.object(edits, "_edit_source", side_effect=RuntimeError("injected save failure")), \
                self.assertRaisesRegex(RuntimeError, "injected"):
            self.save(self.state(self.change(scale=[1.5, 1., 1.])), directory)
        self.assertFalse(directory.exists())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_large_vertex_export_bounds_dense_matrix_work_to_chunks(self):
        env = UnityPy.load(self.raw)
        for obj in env.objects:
            if obj.type.name != "Mesh":
                continue
            tree = obj.read_typetree()
            original = tree["m_VertexData"]["m_DataSize"]
            tree["m_VertexData"]["m_VertexCount"] = 24_000
            tree["m_VertexData"]["m_DataSize"] = original * 4000
            obj.save_typetree(tree)
        path = self.base / "large.unity"; path.write_bytes(env.file.save())
        prepared = model_viewer.prepare([str(path)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        metadata = edits.register_session(prepared["id"], [str(path)], prepared["rig"])
        node = next(n for n in metadata["nodes"] if n["name"] == "LeftUpLeg")
        original_solve = np.linalg.solve
        sizes = []
        def bounded_solve(left, right):
            if left.ndim == 3:
                sizes.append(left.shape[0])
                self.assertLessEqual(left.shape[0], 16_384)
            return original_solve(left, right)
        with patch.object(np.linalg, "solve", side_effect=bounded_solve):
            result = edits.export(prepared["id"], self.state({"node": node["node"],
                "method": "mesh", "scale": [1.5, 1.1, 1.]}), self.base / "chunked")
        self.assertGreaterEqual(len(sizes), 2)
        self.assertEqual(sum(sizes), 24_000)
        self.assertEqual(result["summary"][0]["meshes"][0]["vertices"], 24_000)

    def test_combined_morph_geometry_is_transformed_and_conservatively_bounded(self):
        spec = importlib.util.spec_from_file_location("neutral_persistence_fixture",
            Path(__file__).parent / "generate_viewer_persistence_fixture.py")
        generator = importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
        env = UnityPy.load(generator.fixture_bytes(morphs=True))
        for obj in env.objects:
            tree = obj.read_typetree()
            if obj.type.name == "Mesh":
                shapes = tree["m_Shapes"]
                entry = shapes["vertices"][0]
                entry["vertex"] = {"x": 1., "y": .2, "z": .1}
                entry["normal"] = {"x": .1, "y": .02, "z": .03}
                entry["tangent"] = {"x": .03, "y": .01, "z": .04}
                shapes["vertices"].append(copy.deepcopy(entry))
                shapes["shapes"][0].update(hasNormals=True, hasTangents=True)
                second = copy.deepcopy(shapes["shapes"][0]); second["firstVertex"] = 1
                shapes["shapes"].append(second)
                shapes["channels"].append({"name": "SecondBend", "nameHash": 12345,
                                           "frameIndex": 1, "frameCount": 1})
                shapes["fullWeights"].append(100.)
                obj.save_typetree(tree)
            elif obj.type.name == "SkinnedMeshRenderer":
                tree["m_BlendShapeWeights"] = [300., -200.]; obj.save_typetree(tree)
        raw = env.file.save(); path = self.base / "morph.unity"; path.write_bytes(raw)
        prepared = model_viewer.prepare([str(path)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        metadata = edits.register_session(prepared["id"], [str(path)], prepared["rig"])
        node = next(n for n in metadata["nodes"] if n["name"] == "LeftUpLeg")
        result = edits.export(prepared["id"], self.state({"node": node["node"],
            "method": "mesh", "scale": [1.6, .83, 1.1]}), self.base / "morphed")
        tree, positions = self.mesh(self.inspect(result["preview_paths"][0]))
        envelope = np.zeros_like(positions)
        for entry in tree["m_Shapes"]["vertices"]:
            envelope[entry["index"]] += 3 * np.abs([entry["vertex"][a] for a in "xyz"])
        box = tree["m_LocalAABB"]
        center = np.array([box["m_Center"][a] for a in "xyz"])
        extent = np.array([box["m_Extent"][a] for a in "xyz"])
        self.assertTrue(np.all(positions-envelope >= center-extent-1e-5))
        self.assertTrue(np.all(positions+envelope <= center+extent+1e-5))
        self.assertEqual(len(tree["m_Shapes"]["channels"]), 2)
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
