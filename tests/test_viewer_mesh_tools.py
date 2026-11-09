"""Real serialized Unity/ZIP round trips for UV deletion and skin/vertex writes."""
import copy
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest
import zipfile

from webtools.core import model_edits, model_viewer, viewer_mesh_tools as mesh


class InfluenceTests(unittest.TestCase):
    def test_duplicates_top_four_and_zero_sum(self):
        normalized = mesh.normalize_influences([[0, .1], [0, .1], [1, .2], [2, .3], [3, .4], [4, .01]], 5)
        self.assertEqual([i for i, _ in normalized], [3, 2, 0, 1])
        self.assertAlmostEqual(sum(w for _, w in normalized), 1.)
        for bad in ([[0, 0]], [[True, 1]], [[5, 1]], [[0, -1]], [[0, float('nan')]]):
            with self.subTest(bad=bad), self.assertRaises(mesh.MeshToolError):
                mesh.normalize_influences(bad, 5)


class MeshRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Path(__file__).parent / 'fixtures' / 'viewer_persistence.unity'
        cls.raw = cls.fixture.read_bytes()
        cls.rig = model_viewer.prepare([str(cls.fixture.resolve())], rigged=True,
            face_context={'enabled': False, 'allow_download': False})['rig']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.source = self.base / 'costume.unity'
        self.source.write_bytes(self.raw)
        with model_edits._LOCK:
            model_edits._SESSIONS.clear()
        self.token = secrets.token_hex(16)
        self.editing = model_edits.register_session(self.token, [str(self.source)], self.rig)
        self.ident = mesh.inspect(self.token)['meshes'][0]['mesh']

    def state(self, **values):
        return {'version': 1, 'meshes': [{'mesh': self.ident, **values}]}

    def save(self, state, **options):
        return mesh.export(self.token, state, self.base / 'out', **options)

    def output(self, result):
        raw = Path(result['preview_paths'][0]).read_bytes()
        _, records = mesh._mesh_records(raw, 0)
        return records[0]

    def test_data_has_original_uv_texture_bones_and_not_generated_coordinates(self):
        data = mesh.data(self.token, self.ident)
        self.assertEqual(len(data['positions']), 6)
        self.assertEqual(len(data['triangles']), 4)
        self.assertEqual(data['uv'][0], [0, 0])
        self.assertEqual(data['bones'], ['Move', 'LeftUpLeg', 'BreastSize'])
        self.assertTrue(data['texture'].startswith('data:image/png;base64,'))
        self.assertTrue(data['skinWritable']); self.assertTrue(data['positionWritable'])

    def test_verified_outline_companion_cannot_be_used_as_a_mesh_edit_source(self):
        companion = self.base / 'verified-face-source.unity'
        companion.write_bytes(self.raw)
        proof = {'path': str(companion), 'sha256': hashlib.sha256(self.raw).hexdigest(), 'sourceIndex': 1}
        model_edits.register_session(self.token, [str(self.source)], self.rig, companions=[proof])
        self.assertTrue(mesh.inspect(self.token)['meshes'])
        self.assertTrue(all(row['mesh']['source'] == 0 for row in mesh.inspect(self.token)['meshes']))
        self.assertEqual(len(mesh.data(self.token, self.ident)['positions']), 6)
        foreign = {**self.ident, 'source': 1}
        with self.assertRaisesRegex(mesh.MeshToolError, 'face file explicitly'):
            mesh.data(self.token, foreign)
        with self.assertRaisesRegex(mesh.MeshToolError, 'face file explicitly'):
            self.save({'version': 1, 'meshes': [{'mesh': foreign, 'deleteFaces': [0]}]})
        self.assertEqual(companion.read_bytes(), self.raw)
        companion.write_bytes(self.raw + b'changed')
        with self.assertRaisesRegex(model_edits.ModelEditError, 'facial companion changed'):
            model_edits.register_session(secrets.token_hex(16), [str(self.source)], self.rig, companions=[proof])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_delete_only_painted_faces_preserves_vertex_and_morph_identity(self):
        result = self.save(self.state(deleteFaces=[1, 3]))
        record = self.output(result); tree = record[2]
        faces, _, _ = mesh._triangles(tree, 6)
        self.assertEqual(faces, [[0, 1, 2], [2, 3, 4]])
        _, old = mesh._mesh_records(self.raw, 0)
        self.assertEqual(tree['m_Shapes'], old[0][2]['m_Shapes'])
        self.assertEqual(tree['m_VertexData'], old[0][2]['m_VertexData'])
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(result['original_paths'][0]).read_bytes(), self.raw)

    def test_positions_and_weights_roundtrip_and_normalize(self):
        result = self.save(self.state(positions=[{'vertex': 2, 'position': [.2, .8, -.1]}],
            weights=[{'vertex': 2, 'influences': [[1, .25], [2, .25], [1, .25]]}]))
        record = self.output(result)
        positions, _, weights, indices = mesh._arrays(record[1], record[2])
        for actual, expected in zip(positions[2], [.2, .8, -.1]):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertEqual(list(indices[2]), [1, 2, 0, 0])
        self.assertAlmostEqual(weights[2][0], 2 / 3, places=6)
        self.assertAlmostEqual(weights[2][1], 1 / 3, places=6)
        self.assertAlmostEqual(sum(weights[2]), 1., places=6)
        self.assertEqual(list(weights[0]), [1, 0, 0, 0])

    def test_body_edits_are_preserved_in_same_mesh_export(self):
        breast = next(r for r in self.editing['nodes'] if r['name'] == 'BreastSize')
        body = {'version': 1, 'edits': [{'node': breast['node'], 'method': 'node', 'scale': [1.2, 1.3, 1.4]}], 'savedSettingsEnabled': True}
        result = self.save(self.state(deleteFaces=[0]), body_state=body)
        info = model_edits._inspect(Path(result['preview_paths'][0]).read_bytes())
        key = next(k for k, n in info['names'].items() if n == 'BreastSize')
        for actual, expected in zip(info['effective'][key]['scale'], [1.2, 1.3, 1.4]):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_invalid_selection_weights_and_positions_publish_nothing(self):
        states = [self.state(deleteFaces=[999]), self.state(deleteFaces=[True]), self.state(deleteFaces=[1, 1]),
            self.state(positions=[{'vertex': 1, 'position': [float('nan'), 0, 0]}]),
            self.state(weights=[{'vertex': 1, 'influences': [[99, 1]]}]),
            self.state(weights=[{'vertex': 1, 'influences': [[0, 0]]}]),
            self.state(positions=[{'vertex': -1, 'position': [0, 0, 0]}])]
        for state in states:
            with self.subTest(state=state), self.assertRaises(mesh.MeshToolError):
                self.save(state)
        if (self.base / 'out').exists():
            self.assertEqual(list((self.base / 'out').iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_multi_material_ranges_and_deletion_preserve_other_material_faces(self):
        from generate_viewer_mesh_fixture import fixture_bytes
        raw = fixture_bytes(); self.source.write_bytes(raw)
        rig = model_viewer.prepare([str(self.source)], rigged=True, face_context={'enabled': False, 'allow_download': False})['rig']
        token = secrets.token_hex(16); model_edits.register_session(token, [str(self.source)], rig)
        identity = mesh.inspect(token)['meshes'][0]['mesh']; original = mesh.data(token, identity)
        self.assertEqual([(s['firstFace'], s['faceCount']) for s in original['submeshes']], [(0, 4), (4, 4)])
        self.assertNotEqual(original['textures'][0], original['textures'][1])
        state = {'version': 1, 'meshes': [{'mesh': identity, 'deleteFaces': [0, 1]}]}
        result = mesh.export(token, state, self.base / 'out')
        _, output = mesh._mesh_records(Path(result['preview_paths'][0]).read_bytes(), 0)
        faces, spans, _ = mesh._triangles(output[0][2], 6)
        self.assertEqual([last - first for first, last, _ in spans], [2, 4])
        self.assertEqual(faces[2:], original['triangles'][4:])
        self.assertEqual(self.source.read_bytes(), raw)

    def test_archive_alternative_models_cannot_be_silently_left_unedited(self):
        archive = self.base / 'paired.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('android.unity', self.raw)
            zipped.writestr('ios.unity', self.raw)
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(self.source)], self.rig,
            originals=[str(archive)], origins={str(self.source): str(archive)},
            archive_members={str(self.source): 'android.unity'})
        with self.assertRaisesRegex(mesh.MeshToolError, 'alternative model copies'):
            mesh.export(token, self.state(deleteFaces=[0]), self.base / 'out')
        self.assertFalse((self.base / 'out').exists())

    def test_undo_can_save_a_restored_original_copy(self):
        edited = self.save(self.state(deleteFaces=[0]))
        restored = self.save({'version': 1, 'meshes': []})
        self.assertEqual(Path(restored['preview_paths'][0]).read_bytes(), self.raw)
        self.assertNotEqual(Path(edited['preview_paths'][0]).read_bytes(), self.raw)
        self.assertEqual(Path(edited['preview_paths'][0]).read_bytes(), Path(edited['output_paths'][0]).read_bytes())

    def test_vertex_and_new_weights_are_inputs_to_body_mesh_bake(self):
        import numpy as np
        from sifas_mesh_baker import mat_from
        vertex = [.2, .8, -.1]
        body_node = next(row for row in self.editing['nodes'] if row['name'] == 'LeftUpLeg')
        body = {'version': 1, 'savedSettingsEnabled': True, 'edits': [
            {'node': body_node['node'], 'method': 'mesh', 'scale': [1.6, 1.2, .8]}]}
        state = self.state(positions=[{'vertex': 2, 'position': vertex}],
            weights=[{'vertex': 2, 'influences': [[1, .6], [2, .4]]}])
        result = self.save(state, body_state=body)
        original = model_edits._inspect(self.raw)
        desired = copy.deepcopy(original['effective'])
        target = next(key for key, name in original['names'].items() if name == 'LeftUpLeg')
        desired[target]['scale'] = [1.6, 1.2, .8]
        wanted_world = model_edits._worlds({key: model_edits._matrix(value) for key, value in desired.items()}, original['parents'])
        saved_raw = Path(result['preview_paths'][0]).read_bytes(); saved = model_edits._inspect(saved_raw)
        actual_world = model_edits._worlds({key: model_edits._matrix(value) for key, value in saved['effective'].items()}, saved['parents'])
        record = self.output(result); positions, _, weights, indices = mesh._arrays(record[1], record[2])
        renderer = record[4][0].read_typetree()
        bones = [(0, pointer['m_PathID']) for pointer in renderer['m_Bones']]
        poses = [mat_from(value) for value in record[2]['m_BindPose']]
        wanted = sum(w * (wanted_world[bones[i]] @ poses[i] @ np.asarray([*vertex, 1.])) for i, w in ((1, .6), (2, .4)))
        actual = sum(w * (actual_world[bones[int(i)]] @ poses[int(i)] @ np.asarray([*positions[2], 1.]))
                     for i, w in zip(indices[2], weights[2]) if w > 0)
        self.assertTrue(np.allclose(actual, wanted, atol=1e-5), (actual, wanted))

    def test_malformed_body_state_is_rejected_even_without_body_edits(self):
        for body in ('invalid', True, [], {}, {'version': 1, 'edits': [], 'unsupported': ['unsaved']}):
            with self.subTest(body=body), self.assertRaises((mesh.MeshToolError, model_edits.ModelEditError)):
                self.save(self.state(deleteFaces=[0]), body_state=body)
        self.assertFalse((self.base / 'out').exists())

    def test_repeated_exports_always_start_from_original(self):
        state = self.state(deleteFaces=[0])
        first, second = self.save(state), self.save(state)
        self.assertEqual(Path(first['preview_paths'][0]).read_bytes(), Path(second['preview_paths'][0]).read_bytes())
        self.source.write_bytes(self.raw + b'changed')
        with self.assertRaisesRegex(mesh.MeshToolError, 'changed after opening'):
            self.save(state)

    def test_zip_members_and_original_comments_remain_intact(self):
        archive = self.base / 'costume.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.comment = b'keep-me'
            zipped.writestr('models/android.unity', self.raw)
            zipped.writestr('installer.json', b'{"title":"costume"}')
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(self.source)], self.rig,
            originals=[str(archive)], origins={str(self.source): str(archive)},
            archive_members={str(self.source): 'models/android.unity'})
        original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        result = mesh.export(token, self.state(deleteFaces=[0]), self.base / 'out')
        with zipfile.ZipFile(result['preview_paths'][0]) as saved:
            self.assertEqual(saved.comment, b'keep-me')
            self.assertEqual(saved.read('installer.json'), b'{"title":"costume"}')
            self.assertNotEqual(saved.read('models/android.unity'), self.raw)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), original_hash)


if __name__ == '__main__':
    unittest.main()
