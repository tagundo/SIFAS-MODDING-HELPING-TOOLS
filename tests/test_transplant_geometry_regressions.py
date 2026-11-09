"""Geometry/material regressions plus opt-in tests on actual downloaded GL costumes.

ELICHIKA_REAL_COSTUME_ROOT points at the existing read-only extraction directory;
no game data is committed or fetched by the test suite.
"""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy
import costume_part_transplant as part
import costume_transplant as full
import lower_body_swap as lower


class SubmeshTests(unittest.TestCase):
    def test_indices_honour_submesh_offsets_and_base_vertices(self):
        mesh = {"m_IndexBuffer": np.array([99, 99, 0, 1, 2, 0, 2, 3], '<u2').tobytes(),
                "m_IndexFormat": 0, "m_SubMeshes": [
                    {"firstByte": 4, "indexCount": 3, "baseVertex": 10},
                    {"firstByte": 10, "indexCount": 3, "baseVertex": 20}]}
        self.assertEqual([g.tolist() for g in part.submesh_triangles(mesh)], [[[10, 11, 12]], [[20, 22, 23]]])

    def test_growing_mesh_to_32bit_updates_existing_submesh_byte_offsets(self):
        target = part._build_synth_mesh(65534, 1, [[0, 1, 2]], np.tile([1., 0, 0, 0], (65534, 1)), np.zeros((65534, 4), int))
        donor = part._build_synth_mesh(3, 1, [[0, 1, 2]], np.tile([1., 0, 0, 0], (3, 1)), np.zeros((3, 4), int))
        target['m_SubMeshes'].append(copy.deepcopy(target['m_SubMeshes'][0]))
        target['m_IndexBuffer'] *= 2
        target['m_SubMeshes'][1]['firstByte'] = 6
        part.splice_mesh(target, donor, np.array([[0, 1, 2]]), np.array([0, 1, 2]),
                         np.zeros((3, 4), int), np.tile([1., 0, 0, 0], (3, 1)), [], new_submesh=True)
        self.assertEqual(target['m_IndexFormat'], 1)
        self.assertEqual(target['m_SubMeshes'][1]['firstByte'], 12)
        self.assertEqual(part.submesh_triangles(target)[1].tolist(), [[0, 1, 2]])


@unittest.skipUnless(os.environ.get('ELICHIKA_REAL_COSTUME_ROOT'), 'Set ELICHIKA_REAL_COSTUME_ROOT for read-only GL game costume regressions')
class ActualGameCostumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ['ELICHIKA_REAL_COSTUME_ROOT'])
        cls.target = str(next(root.glob('gl-101011001-*/ch*.unity')))
        cls.splash = str(next(root.glob('gl-310109-*/ch*.unity')))
        cls.wolf = str(next(root.glob('gl-401013001-*/ch*.unity')))
        cls.source_hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (cls.target, cls.splash, cls.wolf)}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.out = str(Path(self.directory.name) / 'graft.unity')

    def textures(self, path):
        return {hashlib.sha256(o.read().get_image_data()).hexdigest() for o in UnityPy.load(path).objects if o.type.name == 'Texture2D'}

    def check_model(self, path):
        self.assertTrue(full.validate(path, verbose=False))
        env = UnityPy.load(path); objs, index = part._index(env)
        renderer = part._body_smr(objs).read_typetree()
        mesh = index[renderer['m_Mesh']['m_PathID']].read_typetree()
        self.assertEqual(len(renderer['m_Materials']), len(mesh['m_SubMeshes']))
        count, channels, stride, start, _ = part.stream_layout(mesh)
        W, BI = part.get_skin(np.frombuffer(bytes(mesh['m_VertexData']['m_DataSize']), np.uint8), mesh, channels, stride, start, count)
        self.assertTrue(np.all(BI[W > 0] < len(renderer['m_Bones'])))
        self.assertTrue(np.all(BI[W > 0] >= 0))
        self.assertTrue(np.allclose(W.sum(axis=1)[W.sum(axis=1) > 0], 1., atol=1e-3))
        self.assertEqual(len(mesh['m_BindPose']), len(renderer['m_Bones']))
        for group in part.submesh_triangles(mesh):
            self.assertTrue(np.all(group >= 0)); self.assertTrue(np.all(group < count))
        for source, digest in self.source_hashes.items():
            self.assertEqual(hashlib.sha256(Path(source).read_bytes()).hexdigest(), digest)
        return renderer, mesh

    def test_actual_full_keeps_original_donor_texture_bytes(self):
        full.transplant(self.splash, self.target, self.out, verbose=False)
        self.check_model(self.out)
        def body_textures(path):
            return {hashlib.sha256(o.read().get_image_data()).hexdigest() for o in UnityPy.load(path).objects
                    if o.type.name == 'Texture2D' and '_body' in o.read().m_Name}
        self.assertTrue(body_textures(self.splash) <= self.textures(self.out))

    def test_actual_tail_injects_bones_and_keeps_all_target_and_donor_textures(self):
        part.transplant_part(self.wolf, self.target, self.out, part_root='TailA_Root_Dyna', new_submesh=True, verbose=False)
        renderer, mesh = self.check_model(self.out)
        env = UnityPy.load(self.out); _, index = part._index(env)
        self.assertIn('TailA1_Dyna', part._smr_bone_names(index, renderer))
        self.assertIn('TailA_Root_Dyna', part._name2transform(index))
        names = part._smr_bone_names(index, renderer)
        self.assertEqual(mesh['m_BoneNameHashes'][names.index('TailA1_Dyna')],
                         part._bone_name_hash(part._path_of_bone(index, 'TailA1_Dyna')))
        self.assertTrue(self.textures(self.target) <= self.textures(self.out))
        # Only textures of the chosen body material are copied, not donor hair.
        self.assertTrue(self.textures(self.wolf) & self.textures(self.out))

    def test_actual_reported_lower_band_has_matching_selection_and_preserved_materials(self):
        target = lower.BodyMesh(UnityPy.load(self.target), self.target)
        donor = lower.BodyMesh(UnityPy.load(self.splash), self.splash)
        drop, _ = lower.band_selection(target, .38, .96, 'lower_belly', True)
        take, _ = lower.band_selection(donor, .38, .96, 'lower_belly', True)
        self.assertGreater(take.sum(), 0)
        lower.graft_one(self.target, self.splash, self.out, cut_low=.38, cut_high=.96, region='lower_belly', log=lambda *a: None)
        _, mesh = self.check_model(self.out)
        groups = part.submesh_triangles(mesh)
        self.assertEqual(len(groups[-1]), take.sum())
        self.assertEqual(sum(map(len, groups[:-1])), len(target.tris()) - drop.sum())
        self.assertTrue(self.textures(self.target) <= self.textures(self.out))
        self.assertTrue(self.textures(self.splash) & self.textures(self.out))

    def test_whole_mesh_scope_includes_garment_faces_and_retains_original_materials(self):
        donor = lower.BodyMesh(UnityPy.load(self.wolf), self.wolf)
        skin, _ = lower.band_selection(donor, .38, .96, 'lower_belly', False, 'skin')
        whole, _ = lower.band_selection(donor, .38, .96, 'lower_belly', False, 'mesh')
        self.assertGreater(whole.sum(), skin.sum())
        lower.graft_one(self.target, self.wolf, self.out, cut_low=.38, cut_high=.96, region='lower_belly', selection_scope='mesh', log=lambda *a: None)
        self.check_model(self.out)
        self.assertTrue(self.textures(self.target) <= self.textures(self.out))

    def test_explicit_skin_only_matching_preserves_non_skin_outfit_pixels_exactly(self):
        from webtools.core import bodymatch
        import skin_tone_changer as colour
        source = UnityPy.load(self.wolf)
        body = next(o for o in source.objects if o.type.name == 'Texture2D' and o.read().m_Name.endswith('_body'))
        original = np.asarray(body.read().image.convert('RGBA'))
        protected = ~colour._skin_mask(original[..., :3].astype(float), original[..., 3].astype(float))
        self.assertTrue(bodymatch.apply_skin_match(self.wolf, self.out, 'bright', 'medium_tone', skin_only=True, colour_guard=True, log=lambda *a: None))
        result = next(o for o in UnityPy.load(self.out).objects if o.path_id == body.path_id)
        actual = np.asarray(result.read().image.convert('RGBA'))
        self.assertTrue(np.array_equal(actual[protected], original[protected]))
        self.assertGreater(np.count_nonzero(actual != original), 0)


if __name__ == '__main__': unittest.main()
