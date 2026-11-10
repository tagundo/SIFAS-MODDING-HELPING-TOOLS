"""Cut-plane coverage and final compression/vertex preservation regressions."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import UnityPy

import costume_part_transplant as part
import lower_body_swap as lower
from test_viewer_transplants import costume_fixture
from transplant_bundle_io import original_packer, write_working_bundle, finish_working_bundle
from generate_viewer_lower_seam_fixture import write_pair
from webtools.core import model_edits
from unittest.mock import patch


def covered(point, positions, faces):
    """Independent 2-D barycentric coverage oracle for the seam patch."""
    for face in faces:
        a, b, c = positions[face, :2]
        matrix = np.column_stack((b - a, c - a))
        u, v = np.linalg.solve(matrix, point - a)
        if u >= -1e-9 and v >= -1e-9 and u + v <= 1 + 1e-9:
            return True
    return False


class CutBoundaryTests(unittest.TestCase):
    def test_real_unity_opposite_diagonal_graft_fills_the_reported_lower_cut_hole(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair = write_pair(root)
            target, donor = Path(pair['target']['path']), Path(pair['donor']['path'])
            before = (target.read_bytes(), donor.read_bytes())
            info = model_edits._inspect(before[0])
            body = lower.BodyMesh(UnityPy.load(before[0]), str(target))
            bone = body.bones.index('LeftUpLeg')
            worlds = model_edits._worlds({key: model_edits._matrix(value) for key, value in info['effective'].items()}, info['parents'])
            matrix = worlds[(0, body.smr['m_Bones'][bone]['m_PathID'])] @ part.mat_from(body.tt['m_BindPose'][bone])
            def coverage(path):
                saved = lower.BodyMesh(UnityPy.load(str(path)), str(path))
                world = (np.column_stack([saved.pos, np.ones(saved.n)]) @ matrix.T)[:, :3]
                faces = saved.tris()
                faces = faces[np.isclose(world[faces, 2], pair['planeZ'], atol=1e-5).all(axis=1)]
                return covered(np.asarray(pair['holeProbe']), world, faces)
            old = root / 'old.unity'
            def old_centres(positions, triangles, low, high, boundary):
                centre = positions[triangles, 1].mean(axis=1)
                return (centre >= low) & (centre <= high)
            with patch.object(lower, '_band_faces', old_centres):
                lower.graft_one(str(target), str(donor), str(old), cut_low=.5, cut_high=.92,
                    region='lower_belly', log=lambda *args: None)
            self.assertFalse(coverage(old), 'The actual previous Unity export reproduces the empty seam patch')
            output = root / 'new.unity'
            lower.graft_one(str(target), str(donor), str(output), cut_low=.5, cut_high=.92,
                region='lower_belly', log=lambda *args: None)
            self.assertTrue(coverage(output), 'Actual exported target/donor boundary faces cover the same patch')
            self.assertEqual((target.read_bytes(), donor.read_bytes()), before)

    def test_opposite_diagonals_leave_no_missing_surface_at_either_plane(self):
        positions = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]])
        target = np.array([[0, 1, 2], [0, 2, 3]])
        donor = np.array([[0, 1, 3], [1, 2, 3]])
        for low, high in ((.5, .92), (.1, .5)):
            with self.subTest(low=low, high=high):
                # The former centre-only masks leave a real hole despite both
                # complete source surfaces covering the same square.
                old_drop = (positions[target, 1].mean(1) >= low) & (positions[target, 1].mean(1) <= high)
                old_take = (positions[donor, 1].mean(1) >= low) & (positions[donor, 1].mean(1) <= high)
                old_faces = np.concatenate([target[~old_drop], donor[old_take]])
                drop = lower._band_faces(positions, target, low, high, 'inside')
                take = lower._band_faces(positions, donor, low, high, 'intersect')
                faces = np.concatenate([target[~drop], donor[take]])
                points = [np.array([x, y]) for x in np.linspace(.05, .95, 19) for y in np.linspace(.05, .95, 19)]
                self.assertGreater(sum(not covered(p, positions, old_faces) for p in points), 0)
                self.assertTrue(all(covered(p, positions, faces) for p in points))

    def test_only_wholly_interior_wearer_faces_are_removed(self):
        positions = np.array([[0., y, 0.] for y in (.1, .4, .6, .7, .8, 1.0)])
        triangles = np.array([[0, 1, 2], [2, 3, 4], [3, 4, 5]])
        np.testing.assert_array_equal(lower._band_faces(positions, triangles, .5, .92, 'inside'), [False, True, False])
        np.testing.assert_array_equal(lower._band_faces(positions, triangles, .5, .92, 'intersect'), [True, True, True])
        self.assertEqual(lower.CUT_PRESETS['hip_fix'], (.5, .92))

    def test_real_boundary_graft_keeps_original_surface_uv_and_skin(self):
        raw = costume_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, donor, output = (root / n for n in ('target.unity', 'donor.unity', 'out.unity'))
            target.write_bytes(raw); donor.write_bytes(raw)
            body = lower.BodyMesh(UnityPy.load(raw), str(target))
            _, world = lower.band_selection(body, -10, 10, selection_scope='mesh')
            first = body.tris()[0]
            low = float(world[first, 1].min() + np.ptp(world[first, 1]) * .25)
            high = float(world[first, 1].max() + 1)
            lower.graft_one(str(target), str(donor), str(output), cut_low=low, cut_high=high,
                            selection_scope='mesh', log=lambda *a: None)
            saved = lower.BodyMesh(UnityPy.load(str(output)), str(output))
            np.testing.assert_array_equal(part.submesh_triangles(saved.tt)[0][0], first)
            for channel in (0, 4, 12, 13):
                before_count, before_channels, before_stride, before_start, _ = part.stream_layout(body.tt)
                count, channels, stride, start, _ = part.stream_layout(saved.tt)
                before = part.read_attr(np.frombuffer(bytes(body.tt['m_VertexData']['m_DataSize']), np.uint8), channel,
                                        before_channels, before_stride, before_start, before_count)
                after = part.read_attr(np.frombuffer(bytes(saved.tt['m_VertexData']['m_DataSize']), np.uint8), channel,
                                       channels, stride, start, count)
                np.testing.assert_array_equal(after[:before_count], before)
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(donor.read_bytes(), raw)


class WorkingBundleTests(unittest.TestCase):
    def test_working_file_is_uncompressed_and_final_matches_original_bundle_bytes(self):
        raw = costume_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'work.unity'
            env = UnityPy.load(raw)
            original = env.file.save(packer='lzma')
            env = UnityPy.load(original)
            flags = write_working_bundle(env.file, path)
            self.assertEqual(original_packer(UnityPy.load(str(path)).file), (64, 64))
            finish_working_bundle(path, flags)
            self.assertEqual(original_packer(UnityPy.load(str(path)).file), flags)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
