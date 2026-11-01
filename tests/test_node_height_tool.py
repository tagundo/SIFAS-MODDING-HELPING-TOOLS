"""The web adapter must pass explicit height edits to the existing core safely."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from webtools.tools import bodymod


class HeightAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / "input.unity"
        self.source.write_bytes(b"original selected file")
        self.output = self.base / "result.unity"
        self.job = SimpleNamespace(log=Mock(), progress=Mock())
        self.core = SimpleNamespace(
            scan_components=Mock(return_value=([
                (None, {}, "member_a", 0.96), (None, {}, "member_b", 1.0)], [])),
            process_bundle=Mock(return_value=2),
            _parse_add=Mock(side_effect=AssertionError("Unexpected manual add")),
            _parse_set=Mock(side_effect=AssertionError("Unexpected manual edit")),
        )
        for context in (
            patch.dict(sys.modules, {"sifas_node_scaling": self.core,
                                     "UnityPy": SimpleNamespace(load=Mock(return_value=object()))}),
            patch.object(bodymod, "ensure_repo_on_path"),
            patch.object(bodymod, "single_out_path", return_value=self.output),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.params = {"mode": "single", "in_path": str(self.source),
                       "out_dir": str(self.base), "mode_select": "none"}

    def test_height_changes_only_explicit_saved_endpoints_for_selected_components(self):
        bodymod.run_node_scaling(self.job, {**self.params, "height_scale": "1.025"})
        self.core.process_bundle.assert_called_once()
        args, kwargs = self.core.process_bundle.call_args
        self.assertEqual(args, (self.source, self.output))
        self.assertEqual(kwargs["height_edits"], {"member_a": 1.025, "member_b": 1.025})
        self.assertEqual(kwargs["mode"], "none")
        self.assertIsNone(kwargs["adds"])
        self.assertIsNone(kwargs["edits"])
        self.assertEqual(self.source.read_bytes(), b"original selected file")

    def test_blank_height_keeps_existing_value_and_does_not_scan(self):
        bodymod.run_node_scaling(self.job, {**self.params, "height_scale": ""})
        self.core.scan_components.assert_not_called()
        self.assertIsNone(self.core.process_bundle.call_args.kwargs["height_edits"])

    def test_invalid_height_never_reaches_the_writer(self):
        for value in ("nan", "inf", "-inf", "0", "3.01", "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bodymod.run_node_scaling(self.job, {**self.params, "height_scale": value})
        self.core.process_bundle.assert_not_called()
        self.assertEqual(self.source.read_bytes(), b"original selected file")

    def test_missing_component_does_not_write_a_misleading_height_result(self):
        self.core.scan_components.return_value = ([], [])
        with self.assertRaisesRegex(ValueError, "No saved height component"):
            bodymod.run_node_scaling(self.job, {**self.params, "height_scale": "1.02"})
        self.core.process_bundle.assert_not_called()

    def test_batch_repairs_do_not_apply_single_file_height_or_manual_entries(self):
        def batch(job, in_dir, out_dir, prefix, suffix, edit):
            return edit(self.source, self.output)
        with patch.object(bodymod, "run_batch", side_effect=batch):
            for stale_height in ("1.1", "nan", "not a number"):
                with self.subTest(stale_height=stale_height):
                    bodymod.run_node_scaling(self.job, {**self.params, "mode": "batch",
                        "height_scale": stale_height, "add_entries": "single-file add",
                        "set_entries": "single-file edit"})
                    kwargs = self.core.process_bundle.call_args.kwargs
                    self.assertIsNone(kwargs["height_edits"])
                    self.assertIsNone(kwargs["adds"])
                    self.assertIsNone(kwargs["edits"])
        self.core._parse_add.assert_not_called()
        self.core._parse_set.assert_not_called()


class ActualHeightSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = os.environ.get("SIFAS_NODE_HEIGHT_TEST_BUNDLE")
        if not cls.source:
            raise unittest.SkipTest("Set SIFAS_NODE_HEIGHT_TEST_BUNDLE for an actual saved-height check")

    def test_saved_height_roundtrip_changes_only_requested_runtime_values(self):
        import UnityPy
        import sifas_node_scaling as core
        source = Path(self.source)
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        before = UnityPy.load(str(source))
        components, _ = core.scan_components(before)
        self.assertTrue(components)

        def source_data(env):
            data = {}
            for obj in env.objects:
                if obj.type.name == "Mesh":
                    tree = obj.read_typetree()
                    data[(obj.path_id, "vertices")] = tree.get("m_VertexData")
                    data[(obj.path_id, "bindposes")] = tree.get("m_BindPose")
                elif obj.type.name == "Texture2D":
                    data[(obj.path_id, "pixels")] = obj.read().image_data
            return data

        original_data = source_data(before)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "changed.unity"
            edits = {target: 1.025 for _, _, target, _ in components}
            changes = core.process_bundle(source, output, mode="none", height_edits=edits, log=lambda _: None)
            self.assertGreaterEqual(changes, len(edits))
            saved = UnityPy.load(str(output))
            saved_components, _ = core.scan_components(saved)
            self.assertEqual(len(saved_components), len(components))
            for _, _, target, height in saved_components:
                self.assertAlmostEqual(height, edits[target], places=5)
            self.assertEqual(source_data(saved), original_data)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)


if __name__ == "__main__":
    unittest.main()
