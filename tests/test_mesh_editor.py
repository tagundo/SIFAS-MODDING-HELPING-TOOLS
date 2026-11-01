"""Pose editor checks; optional core matrix checks use UnityPy and numpy."""
import sys
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webtools.tools.mesh import (
    BODY_PARTS, _body_part_percentages, _build_body_targets, _build_targets,
    inspect_body_parts, inspect_bones, run_mesh_baker,
)


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
        DEFAULT_HIDDEN={"Hair", "Face", "foot_shadow"},
    )


def model_mesh(name, bones, parents=None):
    return {"name": name, "bones": bones, "parents": parents or [-1] * len(bones)}


class BodyPartTests(unittest.TestCase):
    def test_percentages_normalize_numbers_and_default_to_100(self):
        percentages = _body_part_percentages({"head": "125", "thighs": 80.5})
        self.assertEqual(percentages["head"], 125)
        self.assertEqual(percentages["thighs"], 80.5)
        self.assertEqual(percentages["torso"], 100)
        self.assertEqual(set(percentages), set(BODY_PARTS))
        for value in (50, 150):
            self.assertEqual(_body_part_percentages({"head": value})["head"], value)

    def test_percentages_reject_invalid_values_and_unknown_parts(self):
        for value in (49.9, 150.1, "NaN", float("inf"), None, True, [], ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _body_part_percentages({"head": value})
        for value in (None, [], {"hair": 120}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _body_part_percentages(value)

    def test_parts_map_to_paired_bones_and_preserve_length_axis(self):
        bones = list(dict.fromkeys(bone for part in BODY_PARTS.values() for bone in part["bones"]))
        targets = _build_body_targets(fake_backend(), _body_part_percentages(
            {part: 120 for part in BODY_PARTS}), [model_mesh("body", bones + ["Spine2"])], include_hidden=True)
        by_bone = {target.bone: target for target in targets}
        self.assertEqual(set(by_bone), set(bones))
        for part, definition in BODY_PARTS.items():
            for bone in definition["bones"]:
                target = by_bone[bone]
                thickness = definition["kind"] == "thickness"
                self.assertEqual(target.scale, (1, 1.2, 1.2) if thickness else (1.2,) * 3)
                self.assertEqual(target.compensate, thickness)
                self.assertTrue(target.compensate_explicit)
        self.assertEqual(by_bone["Spine"].comp_bones, ["Spine2"])

    def test_missing_paired_side_is_unavailable_and_never_scales_one_side(self):
        meshes = [model_mesh("body", ["LeftArm"])]
        with patch.dict(sys.modules, {"sifas_mesh_baker": fake_backend()}), \
                patch("webtools.tools.mesh.ensure_repo_on_path"), \
                patch("webtools.tools.mesh._inspect_bundle", return_value=meshes):
            options = inspect_body_parts({"reference_path": "/costume.unity"})
        upper_arms = next(option for option in options if option["value"] == "upper_arms")
        self.assertFalse(upper_arms["available"])
        self.assertEqual(upper_arms["bones"], ["LeftArm"])
        with self.assertRaisesRegex(ValueError, "Upper arms thickness is unavailable"):
            _build_body_targets(fake_backend(), _body_part_percentages({"upper_arms": 110}), meshes)

    def test_no_reference_still_supplies_all_disabled_controls(self):
        options = inspect_body_parts({})
        self.assertEqual([option["value"] for option in options], list(BODY_PARTS))
        self.assertTrue(all(not option["available"] for option in options))

    def test_waist_requires_supported_upper_body_compensation(self):
        incomplete = [model_mesh("body", ["Spine"])]
        with patch.dict(sys.modules, {"sifas_mesh_baker": fake_backend()}), \
                patch("webtools.tools.mesh.ensure_repo_on_path"), \
                patch("webtools.tools.mesh._inspect_bundle", return_value=incomplete):
            options = inspect_body_parts({"reference_path": "/costume.unity"})
        waist = next(option for option in options if option["value"] == "torso")
        self.assertFalse(waist["available"])
        with self.assertRaisesRegex(ValueError, "Waist thickness is unavailable"):
            _build_body_targets(fake_backend(), _body_part_percentages({"torso": 110}), incomplete)
        complete = [model_mesh("body", ["Spine", "Spine1", "Spine2"], [-1, 0, 1])]
        targets = _build_body_targets(fake_backend(), _body_part_percentages({"torso": 110}), complete)
        self.assertEqual([target.bone for target in targets], ["Spine"])
        self.assertEqual(targets[0].comp_bones, ["Spine2"])

    def test_head_scales_body_and_separate_hair_and_rejects_overlapping_roots(self):
        percentages = _body_part_percentages({"head": 110})
        separate = [model_mesh("body", ["Head"]), model_mesh("Hair", ["Head_Hair"])]
        targets = _build_body_targets(fake_backend(), percentages, separate, include_hidden=True)
        self.assertEqual([target.bone for target in targets], ["Head", "Head_Hair"])
        self.assertTrue(all(not target.compensate for target in targets))
        with self.assertRaisesRegex(ValueError, "mesh selection"):
            _build_body_targets(fake_backend(), percentages, separate, mesh_filter={"body"}, include_hidden=True)
        overlap = [model_mesh("Hair", ["Head", "Head_Hair"], [-1, 0])]
        with self.assertRaisesRegex(ValueError, "avoid scaling it twice"):
            _build_body_targets(fake_backend(), percentages, overlap, include_hidden=True)


class BodyPartBakingTests(unittest.TestCase):
    def invoke(self, backend, params):
        job = Mock()
        job.should_stop.return_value = False
        with patch.dict(sys.modules, {"sifas_mesh_baker": backend}), \
                patch("webtools.tools.mesh.ensure_repo_on_path"):
            return run_mesh_baker(job, params)

    def test_unchanged_controls_require_a_real_change(self):
        for expert in ([], [{"bone": "Head", "scale": [1, 1, 1]}]):
            with self.subTest(expert=expert), \
                    self.assertRaisesRegex(ValueError, "move its slider away from 100%"), \
                    patch("webtools.tools.mesh._inspect_bundle") as inspect:
                self.invoke(fake_backend(), {"body_parts": {}, "targets": expert})
            inspect.assert_not_called()

    def test_all100_with_expert_change_keeps_expert_operation(self):
        backend = fake_backend()
        def save(_source, output, targets, **_kwargs):
            self.assertEqual([target.bone for target in targets], ["Head"])
            with open(output, "wb") as file:
                file.write(b"bundle")
            return [{"applied": ["Head"]}]
        backend.process_bundle = Mock(side_effect=save)
        with tempfile.TemporaryDirectory() as base, patch("webtools.tools.mesh._inspect_bundle") as inspect:
            self.invoke(backend, {"body_parts": {}, "targets": [{"bone": "Head", "scale": [1.1] * 3}],
                                  "in_path": os.path.join(base, "source.unity"), "out_dir": base})
            inspect.assert_not_called()

    def test_each_batch_input_resolves_its_own_head_and_includes_hair(self):
        backend = fake_backend()
        applied = []
        def save(source, output, targets, **kwargs):
            applied.append((source.name, [target.bone for target in targets]))
            self.assertTrue(kwargs["include_hidden"])
            self.assertTrue(kwargs["hierarchical"])
            with open(output, "wb") as file:
                file.write(b"output bundle")
            return [{"applied": [target.bone for target in targets]}]
        backend.process_bundle = Mock(side_effect=save)
        def inspect(_module, source):
            return [model_mesh("body", ["Head"])] if source.name == "a.unity" else \
                [model_mesh("Hair", ["Head_Hair"])]
        with tempfile.TemporaryDirectory() as base:
            inputs, outputs = os.path.join(base, "in"), os.path.join(base, "out")
            os.makedirs(inputs)
            os.makedirs(outputs)
            for name in ("a.unity", "b.unity"):
                with open(os.path.join(inputs, name), "wb") as file:
                    file.write(b"UnityFS")
            with patch("webtools.tools.mesh._inspect_bundle", side_effect=inspect) as inspect_call:
                summary = self.invoke(backend, {"mode": "batch", "in_dir": inputs, "out_dir": outputs,
                                                "body_parts": {"head": 110}, "hierarchical": False,
                                                "reference_path": "/old-model.unity"})
            self.assertEqual(inspect_call.call_count, 2)
        self.assertEqual(summary, "batch done: total=2 ok=2 fail=0")
        self.assertEqual(applied, [("a.unity", ["Head"]), ("b.unity", ["Head_Hair"])])

    def test_same_bone_simple_and_expert_controls_conflict_before_baking(self):
        backend = fake_backend()
        backend.process_bundle = Mock()
        with tempfile.TemporaryDirectory() as base, \
                patch("webtools.tools.mesh._inspect_bundle", return_value=[model_mesh("body", ["Head"])]), \
                self.assertRaisesRegex(ValueError, "either the body part control or the advanced editor"):
            self.invoke(backend, {"body_parts": {"head": 110}, "targets": [{"bone": "Head"}],
                                  "in_path": os.path.join(base, "source.unity"), "out_dir": base})
        backend.process_bundle.assert_not_called()


class BodyCompensationMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("UnityPy") is None:
            raise unittest.SkipTest("numpy and UnityPy are needed for the core matrix checks")
        import sifas_mesh_baker
        cls.backend = sifas_mesh_baker

    def matrices(self, parts, names, parents, targets=None):
        import numpy as np
        backend = self.backend
        if targets is None:
            targets = _build_body_targets(backend, _body_part_percentages(parts),
                                          [model_mesh("body", names, parents)])
        # Offset each joint along its local length (X) axis. These realistic
        # bind translations also verify that compensation keeps joint positions.
        rest = [backend.trs(translate=(index, 0, 0)) for index in range(len(names))]
        deltas, _applied, _compensated, _missing = backend.expand_targets(
            targets, parents, {name: index for index, name in enumerate(names)}, names, rest_world=rest)
        matrices = backend.hierarchical_skin_matrices([np.linalg.inv(matrix) for matrix in rest], parents, deltas)
        return matrices

    def test_adjacent_arm_sliders_are_independent_and_hands_stay_100(self):
        import numpy as np
        names = ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
        matrices = self.matrices({"upper_arms": 110, "forearms": 120}, names, [-1, 0, 1, -1, 3, 4])
        for side in (0, 3):
            np.testing.assert_allclose(matrices[side], np.diag([1, 1.1, 1.1, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 1], np.diag([1, 1.2, 1.2, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 2], np.eye(4), atol=1e-12)

    def test_adjacent_leg_sliders_are_independent_and_feet_stay_100(self):
        import numpy as np
        names = ["LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"]
        matrices = self.matrices({"thighs": 110, "calves": 120}, names, [-1, 0, 1, -1, 3, 4])
        for side in (0, 3):
            np.testing.assert_allclose(matrices[side], np.diag([1, 1.1, 1.1, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 1], np.diag([1, 1.2, 1.2, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 2], np.eye(4), atol=1e-12)

    def test_hand_size_follows_its_own_percent_after_arm_and_forearm_changes(self):
        import numpy as np
        names = ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
        matrices = self.matrices({"upper_arms": 110, "forearms": 120, "hands": 130}, names, [-1, 0, 1, -1, 3, 4])
        for index in (2, 5):
            np.testing.assert_allclose(matrices[index, :3, :3], np.diag([1.3] * 3), atol=1e-12)

    def test_expert_targets_keep_existing_compensation_semantics(self):
        import numpy as np
        names = ["LeftArm", "LeftForeArm", "LeftHand"]
        targets = [self.backend.Target("LeftArm", scale=(1, 1.1, 1.1), compensate=True),
                   self.backend.Target("LeftForeArm", scale=(1, 1.2, 1.2), compensate=True)]
        matrices = self.matrices({}, names, [-1, 0, 1], targets=targets)
        np.testing.assert_allclose(matrices[1], np.diag([1, 1.32, 1.32, 1]), atol=1e-12)
        np.testing.assert_allclose(matrices[2], np.diag([1, 1.1, 1.1, 1]), atol=1e-12)

    def test_waist_compensation_keeps_chest_and_head_at_100(self):
        import numpy as np
        names = ["Spine", "Spine1", "Spine2", "Head"]
        matrices = self.matrices({"torso": 115}, names, [-1, 0, 1, 2])
        np.testing.assert_allclose(matrices[0], np.diag([1, 1.15, 1.15, 1]), atol=1e-12)
        np.testing.assert_allclose(matrices[1], np.diag([1, 1.15, 1.15, 1]), atol=1e-12)
        np.testing.assert_allclose(matrices[2], np.eye(4), atol=1e-12)
        np.testing.assert_allclose(matrices[3], np.eye(4), atol=1e-12)

    def test_symmetric_thickness_compensation_commutes_with_length_axis_roll(self):
        import numpy as np
        backend = self.backend
        names = ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
        parents = [-1, 0, 1, -1, 3, 4]
        targets = _build_body_targets(backend, _body_part_percentages({"upper_arms": 110, "forearms": 120}),
                                      [model_mesh("body", names, parents)])
        rest = [backend.trs(translate=(index, 0, 0), rotate=(index * 17, 0, 0))
                for index in range(len(names))]
        deltas, _, _, _ = backend.expand_targets(targets, parents,
                                                {name: index for index, name in enumerate(names)}, names,
                                                rest_world=rest)
        matrices = backend.hierarchical_skin_matrices([np.linalg.inv(matrix) for matrix in rest], parents, deltas)
        for side in (0, 3):
            np.testing.assert_allclose(matrices[side], np.diag([1, 1.1, 1.1, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 1], np.diag([1, 1.2, 1.2, 1]), atol=1e-12)
            np.testing.assert_allclose(matrices[side + 2], np.eye(4), atol=1e-12)

    def test_bent_translated_legs_keep_feet_fixed_and_each_changed_part_at_its_own_pivot(self):
        import numpy as np
        backend = self.backend
        names = ["LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"]
        parents = [-1, 0, 1, -1, 3, 4]
        rest = []
        for index, parent in enumerate(parents):
            local = backend.trs(translate=(0.24 + index * 0.03, 0.07, -0.05),
                                rotate=(index * 11, 25 + index * 13, -index * 9))
            rest.append(local if parent < 0 else rest[parent] @ local)
        targets = _build_body_targets(backend, _body_part_percentages({"thighs": 110, "calves": 120}),
                                      [model_mesh("body", names, parents)])
        deltas, _, _, _ = backend.expand_targets(targets, parents,
                                                {name: index for index, name in enumerate(names)}, names,
                                                rest_world=rest)
        matrices = backend.hierarchical_skin_matrices([np.linalg.inv(matrix) for matrix in rest], parents, deltas)
        for index in range(len(names)):
            factor = (1.1, 1.2, 1)[index % 3]
            expected = rest[index] @ np.diag([1, factor, factor, 1]) @ np.linalg.inv(rest[index])
            np.testing.assert_allclose(matrices[index], expected, atol=1e-12)

    def test_full_descendant_rest_frame_preserves_bent_offset_upper_body(self):
        import numpy as np
        backend = self.backend
        names = ["Spine", "Spine1", "Spine2", "Head", "LeftArm", "RightArm"]
        parents = [-1, 0, 1, 2, 2, 2]
        rest = []
        for index, parent in enumerate(parents):
            local = backend.trs(translate=(0.1, 0.12 + index * 0.01, -0.03),
                                rotate=(index * 7, 20 + index * 11, -index * 13))
            rest.append(local if parent < 0 else rest[parent] @ local)
        targets = _build_body_targets(backend, _body_part_percentages({"torso": 115}),
                                      [model_mesh("body", names, parents)])
        deltas, _, _, _ = backend.expand_targets(targets, parents,
                                                {name: index for index, name in enumerate(names)}, names,
                                                rest_world=rest)
        matrices = backend.hierarchical_skin_matrices([np.linalg.inv(matrix) for matrix in rest], parents, deltas)
        for index in (2, 3, 4, 5):
            np.testing.assert_allclose(matrices[index], np.eye(4), atol=1e-12)

    def test_compensation_preserves_parent_movement_rotation_and_child_own_transform(self):
        import numpy as np
        backend = self.backend
        names = ["LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"]
        parents = [-1, 0, 1, -1, 3, 4]
        targets = _build_body_targets(backend, _body_part_percentages({"thighs": 110, "calves": 120}),
                                      [model_mesh("body", names, parents)])
        by_bone = {target.bone: target for target in targets}
        by_bone["LeftUpLeg"].translate = (0.05, -0.03, 0.01)
        by_bone["LeftUpLeg"].rotate = (12, -17, 23)
        by_bone["LeftLeg"].translate = (0.02, 0.01, -0.04)
        by_bone["LeftLeg"].rotate = (-7, 19, 5)
        rest = []
        for index, parent in enumerate(parents):
            local = backend.trs(translate=(0.2, 0.08, -0.03), rotate=(index * 7, 35, -index * 9))
            rest.append(local if parent < 0 else rest[parent] @ local)
        deltas, _, _, _ = backend.expand_targets(targets, parents,
                                                {name: index for index, name in enumerate(names)}, names,
                                                rest_world=rest)
        matrices = backend.hierarchical_skin_matrices([np.linalg.inv(matrix) for matrix in rest], parents, deltas)
        parent_target = by_bone["LeftUpLeg"]
        retained_parent = backend.trs(translate=parent_target.translate, rotate=parent_target.rotate)
        relative = np.linalg.inv(rest[0]) @ rest[1]
        expected = rest[0] @ retained_parent @ relative @ by_bone["LeftLeg"].delta() @ np.linalg.inv(rest[1])
        np.testing.assert_allclose(matrices[1], expected, atol=1e-12)

    def test_beginner_compensation_requires_rest_transforms(self):
        backend = self.backend
        names = ["LeftUpLeg", "LeftLeg", "RightUpLeg", "RightLeg"]
        parents = [-1, 0, -1, 2]
        targets = _build_body_targets(backend, _body_part_percentages({"thighs": 110}),
                                      [model_mesh("body", names, parents)])
        with self.assertRaisesRegex(ValueError, "rest-world transforms"):
            backend.expand_targets(targets, parents, {name: index for index, name in enumerate(names)}, names)


class ActualBodyCompensationTests(unittest.TestCase):
    """Opt in with SIFAS_MESH_TEST_BUNDLE=/path/to/an/extracted/model.unity."""
    @classmethod
    def setUpClass(cls):
        fixture = os.environ.get("SIFAS_MESH_TEST_BUNDLE")
        if not fixture or not os.path.isfile(fixture):
            raise unittest.SkipTest("Set SIFAS_MESH_TEST_BUNDLE for actual model invariants")
        import sifas_mesh_baker as backend
        cls.backend = backend
        env = backend.UnityPy.load(fixture)
        tos = backend.build_bone_name_map(env)
        ids = backend.build_id_map(env)
        smr = backend.smr_bone_pids(env, ids)
        cls.meshes = []
        for mesh in backend.list_meshes(env):
            if not mesh.skinned:
                continue
            names, parents = backend.resolve_bones(env, ids, tos, mesh.obj, mesh.tree, smr)
            cls.meshes.append((mesh, names, parents))

    def test_original_foot_and_upper_body_matrices_stay_fixed(self):
        import numpy as np
        backend = self.backend
        metadata = [model_mesh(mesh.name, names, parents) for mesh, names, parents in self.meshes]
        cases = [({"thighs": 110, "calves": 120}, ("LeftFoot", "RightFoot")),
                 ({"torso": 115}, ("Spine2", "Head", "LeftArm", "RightArm"))]
        for parts, protected in cases:
            targets = _build_body_targets(backend, _body_part_percentages(parts), metadata, include_hidden=True)
            checked = set()
            for mesh, names, parents in self.meshes:
                bps = [backend.mat_from(matrix) for matrix in mesh.tree["m_BindPose"]]
                rest = [np.linalg.inv(matrix) for matrix in bps]
                deltas, _, _, _ = backend.expand_targets(targets, parents,
                                                        {name: index for index, name in enumerate(names)}, names,
                                                        rest_world=rest)
                matrices = backend.hierarchical_skin_matrices(bps, parents, deltas)
                for name in protected:
                    if name not in names:
                        continue
                    checked.add(name)
                    with self.subTest(parts=parts, mesh=mesh.name, bone=name):
                        np.testing.assert_allclose(matrices[names.index(name)], np.eye(4), atol=1e-6)
            self.assertEqual(checked, set(protected))

    def test_bake_pipeline_passes_full_rest_frames_to_compensation(self):
        import copy
        backend = self.backend
        metadata = [model_mesh(mesh.name, names, parents) for mesh, names, parents in self.meshes]
        targets = _build_body_targets(backend, _body_part_percentages({"thighs": 110, "calves": 120}),
                                      metadata, include_hidden=True)
        mesh, names, parents = next(item for item in self.meshes if "LeftFoot" in item[1])
        with patch.object(backend, "expand_targets", wraps=backend.expand_targets) as expand:
            result = backend.bake_mesh(copy.deepcopy(mesh.tree), names, parents, targets)
        self.assertTrue(result["applied"])
        self.assertEqual(len(expand.call_args.kwargs["rest_world"]), len(names))


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
