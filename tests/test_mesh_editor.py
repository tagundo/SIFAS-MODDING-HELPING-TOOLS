"""Pose editor adapter checks; no UnityPy/numpy installation is required."""
import sys
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webtools.tools.mesh import _build_targets, inspect_bones, run_mesh_baker


class FakeTarget:
    def __init__(self, bone, **values):
        self.bone = bone
        self.__dict__.update(values)


def fake_backend():
    return SimpleNamespace(
        Target=FakeTarget,
        default_compensate=lambda name: name.startswith("Spine"),
        apply_spine_comp=Mock(),
        parse_target_spec=Mock(return_value=FakeTarget("Head")),
        thigh_targets=Mock(return_value=[FakeTarget("LeftUpLeg"), FakeTarget("RightUpLeg")]),
    )


class PoseTargetsTests(unittest.TestCase):
    def test_structured_transform_preserves_all_axes_and_compensation(self):
        backend = fake_backend()
        targets = _build_targets(backend, {"targets": [{
            "bone": " Spine1 ", "scale": [1, "1.2", 1.3],
            "rotate": [-5, 0, 12], "translate": [0.01, -0.2, 0],
        }], "spine_comp": "both"})
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.bone, "Spine1")
        self.assertEqual(target.scale, (1.0, 1.2, 1.3))
        self.assertEqual(target.rotate, (-5.0, 0.0, 12.0))
        self.assertEqual(target.translate, (0.01, -0.2, 0.0))
        self.assertTrue(target.compensate)
        backend.apply_spine_comp.assert_called_once_with(targets, "both")

    def test_defaults_and_explicit_compensation(self):
        targets = _build_targets(fake_backend(), {"targets": [{
            "bone": "Spine2", "compensate": False,
        }]})
        self.assertEqual(targets[0].scale, (1.0, 1.0, 1.0))
        self.assertEqual(targets[0].rotate, (0.0, 0.0, 0.0))
        self.assertEqual(targets[0].translate, (0.0, 0.0, 0.0))
        self.assertFalse(targets[0].compensate)

    def test_rejects_invalid_transforms_before_baking(self):
        invalid_rows = [
            {"bone": ""}, {"bone": None}, None,
            {"bone": "Head", "scale": [1, 2]},
            {"bone": "Head", "scale": [0, 1, 1]},
            {"bone": "Head", "scale": [-1, 1, 1]},
            {"bone": "Head", "rotate": ["NaN", 0, 0]},
            {"bone": "Head", "translate": [0, float("inf"), 0]},
            {"bone": "Head", "translate": [0, True, 0]},
            {"bone": "Head", "compensate": "false"},
        ]
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                _build_targets(fake_backend(), {"targets": [row]})
        with self.assertRaises(ValueError):
            _build_targets(fake_backend(), {"targets": "[]"})

    def test_rejects_duplicate_bones(self):
        with self.assertRaisesRegex(ValueError, "more than one"):
            _build_targets(fake_backend(), {"targets": [{"bone": "Head"}, {"bone": " Head "}]})

    def test_manual_specs_and_thigh_presets_remain_supported(self):
        backend = fake_backend()
        targets = _build_targets(backend, {
            "targets": [{"bone": "Spine"}],
            "target_spec": "Head;r=10,0,0", "thigh": "slim:thick",
        })
        self.assertEqual([target.bone for target in targets], ["Spine", "Head", "LeftUpLeg", "RightUpLeg"])
        backend.parse_target_spec.assert_called_once_with("Head;r=10,0,0")
        backend.thigh_targets.assert_called_once_with("slim", "thick")

    def test_empty_pose_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "Add a bone transform"):
            _build_targets(fake_backend(), {"targets": []})


class BoneOptionsTests(unittest.TestCase):
    def test_missing_reference_returns_empty_without_loading_unity(self):
        self.assertEqual(inspect_bones({}), [])

    def test_options_use_real_skinned_bones_deduplicated_across_meshes(self):
        env = object()
        body = SimpleNamespace(name="body", skinned=True, obj="body-object", tree="body-tree")
        ribbon = SimpleNamespace(name="ribbon", skinned=True, obj="ribbon-object", tree="ribbon-tree")
        shadow = SimpleNamespace(name="shadow", skinned=False)
        backend = SimpleNamespace(
            UnityPy=SimpleNamespace(load=Mock(return_value=env)),
            build_bone_name_map=Mock(return_value="tos"),
            build_id_map=Mock(return_value="ids"),
            smr_bone_pids=Mock(return_value="smr"),
            list_meshes=Mock(return_value=[body, ribbon, shadow]),
            resolve_bones=Mock(side_effect=[
                (["Spine", "Head", "Head", "<hash:123>", "<bone:0>"], []),
                (["Spine", "Ribbon"], []),
            ]),
        )
        with patch.dict(sys.modules, {"sifas_mesh_baker": backend}), \
                patch("webtools.tools.mesh.ensure_repo_on_path"):
            options = inspect_bones({"reference_path": "/bundles/costume.unity"})
        self.assertEqual(options, [
            {"value": "Head", "label": "Head (body)"},
            {"value": "Ribbon", "label": "Ribbon (ribbon)"},
            {"value": "Spine", "label": "Spine (body, ribbon)"},
        ])
        backend.UnityPy.load.assert_called_once_with("/bundles/costume.unity")
        self.assertEqual(backend.resolve_bones.call_count, 2)

    def test_options_endpoint_rejects_reference_outside_library(self):
        from webtools.server import Handler
        handler = Handler.__new__(Handler)
        handler._query = lambda: {"reference_path": ["/etc/passwd"]}
        handler._send_json = Mock()
        with patch("webtools.tools.mesh.inspect_bones") as inspect:
            handler._api_options("mesh_baker/targets")
        self.assertEqual(handler._send_json.call_args.kwargs["status"], 403)
        inspect.assert_not_called()


class ModelFolderTests(unittest.TestCase):
    def test_picker_uses_models_and_falls_back_for_older_libraries(self):
        from webtools.filebrowser import allowed_roots
        from webtools.tools.registry import get_tool
        with tempfile.TemporaryDirectory() as base, patch.dict(os.environ, {"SUKUSTA_DIR": base}):
            extracted = os.path.join(base, "extracted")
            self.assertEqual(allowed_roots()["models"], extracted)
            models = os.path.join(extracted, "3d_model")
            os.makedirs(models)
            self.assertEqual(allowed_roots()["models"], models)
        fields = get_tool("mesh_baker")["fields"]
        for name in ("in_path", "in_paths", "in_dir", "reference_path"):
            self.assertEqual(next(f["root"] for f in fields if f.get("name") == name), "models")


class BakingOutputTests(unittest.TestCase):
    def run_with_backend(self, backend, params):
        job = Mock()
        job.should_stop.return_value = False
        with patch.dict(sys.modules, {"sifas_mesh_baker": backend}), \
                patch("webtools.tools.mesh.ensure_repo_on_path"):
            return run_mesh_baker(job, params)

    def params(self, base, bone="HairA1_Dyna"):
        return {"mode": "single", "in_path": os.path.join(base, "costume.unity"),
                "out_dir": base, "targets": [{"bone": bone, "scale": [1, 1.1, 1.1]}]}

    def test_hidden_only_bone_reports_no_output_and_how_to_enable_it(self):
        backend = fake_backend()
        backend.process_bundle = Mock(return_value=[
            {"mesh": "body", "applied": [], "missing": ["HairA1_Dyna"]},
        ])
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaisesRegex(ValueError, "Include hidden meshes"):
                self.run_with_backend(backend, self.params(base))
            self.assertFalse(os.path.exists(os.path.join(base, "costume_baked.unity")))
        self.assertFalse(backend.process_bundle.call_args.kwargs["include_hidden"])

    def test_unmatched_bone_cannot_succeed_even_with_stale_output(self):
        backend = fake_backend()
        backend.process_bundle = Mock(return_value=[
            {"mesh": "body", "applied": [], "missing": ["UnknownBone"]},
        ])
        with tempfile.TemporaryDirectory() as base:
            stale = os.path.join(base, "costume_baked.unity")
            with open(stale, "wb") as file:
                file.write(b"old bundle")
            with patch("webtools.tools.mesh.single_out_path", return_value=stale), \
                    self.assertRaisesRegex(ValueError, "No transform was applied; no output was saved"):
                self.run_with_backend(backend, self.params(base, "UnknownBone"))

    def test_applied_stats_require_a_real_nonempty_output(self):
        backend = fake_backend()
        backend.process_bundle = Mock(return_value=[{"applied": ["Spine"]}])
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaisesRegex(RuntimeError, "did not create an output"):
                self.run_with_backend(backend, self.params(base, "Spine"))
            with open(os.path.join(base, "costume_baked.unity"), "wb"):
                pass
            with patch("webtools.tools.mesh.single_out_path", return_value=os.path.join(base, "costume_baked.unity")), \
                    self.assertRaisesRegex(RuntimeError, "did not create an output"):
                self.run_with_backend(backend, self.params(base, "Spine"))

    def test_hidden_bone_with_inclusion_and_saved_output_succeeds(self):
        backend = fake_backend()
        def save(_source, output, _targets, **kwargs):
            self.assertTrue(kwargs["include_hidden"])
            with open(output, "wb") as file:
                file.write(b"new bundle")
            return [{"mesh": "Hair", "applied": ["HairA1_Dyna"]}]
        backend.process_bundle = Mock(side_effect=save)
        with tempfile.TemporaryDirectory() as base:
            params = {**self.params(base), "include_hidden": True}
            result = self.run_with_backend(backend, params)
            self.assertEqual(result, f"baked -> {base}/costume_baked.unity")

    def test_batch_counts_unmatched_bone_as_failed_file(self):
        backend = fake_backend()
        backend.process_bundle = Mock(return_value=[{"applied": [], "missing": ["UnknownBone"]}])
        with tempfile.TemporaryDirectory() as base:
            source = os.path.join(base, "costume.unity")
            with open(source, "wb") as file:
                file.write(b"UnityFS")
            params = {**self.params(base, "UnknownBone"), "mode": "batch", "in_dir": base}
            result = self.run_with_backend(backend, params)
            self.assertEqual(result, "batch done: total=1 ok=0 fail=1")


if __name__ == "__main__":
    unittest.main()
