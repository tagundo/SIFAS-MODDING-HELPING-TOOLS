"""Numerical rest-skinning regressions; no character pictures are generated."""
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from webtools.core.model_skinning import SkinningError, rest_skin_mesh


def translation(x=0, y=0, z=0):
    result = np.eye(4)
    result[:3, 3] = [x, y, z]
    return result


class RestSkinningTests(unittest.TestCase):
    def setUp(self):
        self.points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        self.normals = np.tile([0., 0., 1.], (3, 1))
        self.indices = np.zeros((3, 4), dtype=int)
        self.weights = np.tile([1., 0., 0., 0.], (3, 1))

    def skin(self, **changes):
        args = dict(positions=self.points, normals=self.normals,
                    bone_indices=self.indices, bone_weights=self.weights,
                    bone_world_matrices=[np.eye(4)], bind_poses=[np.eye(4)])
        args.update(changes)
        return rest_skin_mesh(**args)

    def test_zero_bindpose_face_uses_renderer_world_once(self):
        world = translation(2, 3, 4)
        result = self.skin(bind_poses=[], renderer_world=world)
        np.testing.assert_allclose(result["positions"], self.points + [2, 3, 4])
        np.testing.assert_array_equal(result["normals"], self.normals)
        self.assertFalse(result["applied"])
        self.assertTrue(result["world_space"])

    def test_ordinary_rest_bind_cancels_bone_frames_and_preserves_renderer(self):
        world = translation(2, 3, 4)
        world[:3, :3] = [[0, -2, 0], [2, 0, 0], [0, 0, 2]]
        bones = [translation(0, 1, 0), translation(3, 2, 1)]
        poses = [np.linalg.inv(bone) @ world for bone in bones]
        result = self.skin(bone_world_matrices=bones, bind_poses=poses,
                           bone_indices=np.tile([0, 1, 0, 0], (3, 1)),
                           bone_weights=np.tile([.25, .75, 0, 0], (3, 1)),
                           renderer_world=world, chunk_size=1)
        expected = self.points @ world[:3, :3].T + world[:3, 3]
        np.testing.assert_allclose(result["positions"], expected)
        np.testing.assert_array_equal(result["normals"], self.normals)
        self.assertTrue(result["applied"])

    def test_recentered_uploaded_body_rest_offset_is_restored_by_bindposes(self):
        # Exact metadata from the uploaded ch0207_co0031 mod, not an AABB fix.
        points = np.array([[0, -.7118396759033203, 0],
                           [0, .7118392586708069, 0], [0, 0, 0]])
        skin = translation(0, .7117905, -.00503146)
        bones = [translation(0, 1.3914487, -.0028155), translation(0, .9, 0)]
        poses = [np.linalg.inv(bone) @ skin for bone in bones]
        result = self.skin(positions=points, bone_world_matrices=bones, bind_poses=poses,
                           bone_indices=np.tile([0, 1, 0, 0], (3, 1)),
                           bone_weights=np.tile([.4, .6, 0, 0], (3, 1)))
        np.testing.assert_allclose(result["positions"][:, 1],
                                   [-.0000491759033203, 1.423629758670807, .7117905],
                                   atol=1e-14)
        np.testing.assert_allclose(result["positions"][:, 2], -.00503146)
        self.assertTrue(result["applied"])

    def test_blended_rotations_transform_positions_and_normals(self):
        quarter_turn = np.array([[0., -1, 0, 0], [1, 0, 0, 0],
                                 [0, 0, 1, 0], [0, 0, 0, 1]])
        result = self.skin(normals=np.tile([1., 0, 0], (3, 1)),
                           bone_world_matrices=[np.eye(4), quarter_turn],
                           bind_poses=[np.eye(4), np.eye(4)],
                           bone_indices=np.tile([0, 1, 0, 0], (3, 1)),
                           bone_weights=np.tile([.75, .25, 0, 0], (3, 1)))
        np.testing.assert_allclose(result["positions"],
                                   [[0, 0, 0], [.75, .25, 0], [-.25, .75, 0]])
        np.testing.assert_allclose(result["normals"],
                                   np.tile([3 / np.sqrt(10), 1 / np.sqrt(10), 0], (3, 1)))

    def test_scaled_normal_uses_inverse_transpose_then_normalizes(self):
        scale = np.diag([2., 1, .5, 1])
        result = self.skin(normals=np.tile([1., 1, 0], (3, 1)),
                           bone_world_matrices=[scale])
        np.testing.assert_allclose(result["normals"],
                                   np.tile([1 / np.sqrt(5), 2 / np.sqrt(5), 0], (3, 1)))

    def test_zero_weights_fall_back_per_vertex_and_unused_indices_are_ignored(self):
        weights = self.weights.copy()
        weights[1] = 0
        indices = self.indices.copy()
        indices[:, 1:] = -999
        result = self.skin(bone_weights=weights, bone_indices=indices,
                           bone_world_matrices=[translation(0, 5, 0)],
                           renderer_world=translation(2, 0, 0))
        np.testing.assert_allclose(result["positions"], [[0, 5, 0], [3, 0, 0], [0, 6, 0]])
        self.assertEqual(result["warnings"], ["skin_zero_weight_vertices"])

    def test_bind_pose_supports_unity_row_major_objects_and_dicts(self):
        matrix = translation(1, 2, 3)
        fields = {f"e{row}{column}": matrix[row, column]
                  for row in range(4) for column in range(4)}
        for pose in (fields, SimpleNamespace(**fields)):
            with self.subTest(kind=type(pose).__name__):
                np.testing.assert_allclose(self.skin(bind_poses=[pose])["positions"],
                                           self.points + [1, 2, 3])

    def test_reflection_reports_winding_and_inputs_remain_unchanged(self):
        before = [array.copy() for array in (self.points, self.normals, self.indices, self.weights)]
        result = self.skin(bone_world_matrices=[np.diag([-1., 1, 1, 1])])
        self.assertEqual(result["orientation_sign"], -1)
        for original, snapshot in zip((self.points, self.normals, self.indices, self.weights), before):
            np.testing.assert_array_equal(original, snapshot)
        self.assertFalse(np.shares_memory(result["positions"], self.points))
        self.assertFalse(np.shares_memory(result["normals"], self.normals))

    def test_chunk_boundaries_and_absent_normals(self):
        points = np.arange(123, dtype=float).reshape(-1, 3)
        args = dict(positions=points, normals=None,
                    bone_indices=np.zeros((41, 4), int),
                    bone_weights=np.tile([1., 0, 0, 0], (41, 1)),
                    bone_world_matrices=[translation(1, 2, 3)])
        first = self.skin(**args, chunk_size=1)
        second = self.skin(**args, chunk_size=16)
        np.testing.assert_array_equal(first["positions"], second["positions"])
        self.assertIsNone(first["normals"])

    def test_invalid_active_skin_is_an_error(self):
        invalid = [dict(bone_world_matrices=[None]),
                   dict(bone_indices=np.ones((3, 4), int)),
                   dict(bone_indices=np.full((3, 4), .5)),
                   dict(bone_weights=np.tile([-.1, 1.1, 0, 0], (3, 1))),
                   dict(bone_weights=np.tile([float("nan"), 0, 0, 0], (3, 1))),
                   dict(bone_weights=np.tile([.5, 0, 0, 0], (3, 1))),
                   dict(bone_weights=None), dict(bone_indices=None),
                   dict(bone_indices=np.zeros((3, 5)), bone_weights=np.ones((3, 5)) / 5),
                   dict(bone_world_matrices=[np.diag([0., 1, 1, 1])]),
                   dict(renderer_world=np.diag([1., 0, 1, 1])),
                   dict(max_vertices=2), dict(chunk_size=16385),
                   dict(positions=[[0, 0, 0, 0]] * 3),
                   dict(bone_indices=np.full((3, 4), 1j)),
                   dict(bind_poses=[{}]), dict(bind_poses=[np.zeros((4, 5))])]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(SkinningError):
                self.skin(**changes)

    def test_oversized_rows_are_rejected_before_numeric_copy(self):
        class OversizedRow:
            def __len__(self):
                return 1_000_000_000

            def __array__(self, *args, **kwargs):
                raise AssertionError("An oversized row must not be converted")

        with self.assertRaises(SkinningError):
            self.skin(bone_weights=[OversizedRow()] * 3)

    def test_float_quantization_is_normalized_without_mutating_source_weights(self):
        weights = self.weights.copy()
        weights[:, 0] = 1.00001
        before = weights.copy()
        result = self.skin(bone_weights=weights, bone_world_matrices=[translation(1, 2, 3)])
        np.testing.assert_allclose(result["positions"], self.points + [1, 2, 3])
        np.testing.assert_array_equal(weights, before)


class ActualSkinningRegressionTests(unittest.TestCase):
    def inspect(self, variable, edited):
        path = os.environ.get(variable)
        if not path:
            self.skipTest(f"Set {variable} for metadata-only actual bundle regression")
        import time
        from UnityPy.helpers.MeshHelper import MeshHandler
        from webtools.core import model_viewer as viewer
        source = Path(path)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        scene = viewer._Scene(viewer._environment([str(source)], time.monotonic() + 60),
                              time.monotonic() + 60)
        checked = 0
        for renderer, tree, game_object in scene.renderers:
            if renderer.type.name != "SkinnedMeshRenderer":
                continue
            name = scene.tree(game_object).get("m_Name", "")
            if name != "Body":
                continue
            mesh = viewer._ref(renderer, tree.get("m_Mesh")).read()
            handler = MeshHandler(mesh)
            handler.process()
            points = np.asarray(handler.m_Vertices, float)[:, :3]
            normals = np.asarray(handler.m_Normals, float)[:, :3]
            world = scene.world(scene.transforms.get(viewer._key(game_object)))
            bones = [scene.world(viewer._ref(renderer, ref)) for ref in tree["m_Bones"]]
            result = rest_skin_mesh(points, normals, handler.m_BoneIndices,
                                    handler.m_BoneWeights, bones, mesh.m_BindPose, world)
            self.assertTrue(result["applied"])
            self.assertTrue(np.isfinite(result["positions"]).all())
            np.testing.assert_allclose(np.linalg.norm(result["normals"], axis=1), 1, atol=1e-12)
            if edited:
                self.assertAlmostEqual(points[:, 1].min(), -.7118396759033203)
                self.assertAlmostEqual(result["positions"][:, 1].min(), -.0000493719, places=6)
                self.assertAlmostEqual(result["positions"][:, 1].max(), 1.4236300249, places=6)
            else:
                previous = points @ world[:3, :3].T + world[:3, 3]
                np.testing.assert_allclose(result["positions"], previous, atol=3e-5, rtol=0)
            checked += 1
        self.assertGreater(checked, 0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_uploaded_edited_body_rest_alignment(self):
        self.inspect("SIFAS_SKINNING_TEST_EDITED_BUNDLE", True)

    def test_ordinary_original_body_matches_previous_world_geometry(self):
        self.inspect("SIFAS_SKINNING_TEST_ORIGINAL_BUNDLE", False)


if __name__ == "__main__":
    unittest.main()
