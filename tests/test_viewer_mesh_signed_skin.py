"""Native signed Int32 Unity skin indices: real bytes and rejected writes."""
import copy
from pathlib import Path
import secrets
import struct
import tempfile
import unittest

import UnityPy

from sifas_mesh_baker import stream_layout
from test_viewer_transplants import costume_fixture
from webtools.core import model_edits, model_viewer, viewer_mesh_tools as mesh


def signed_fixture():
    env = UnityPy.load(costume_fixture())
    for obj in env.objects:
        if obj.type.name != 'Mesh':
            continue
        tree = obj.read_typetree()
        tree['m_VertexData']['m_Channels'][13]['format'] = 11
        obj.save_typetree(tree)
    return env.file.save()


class SignedSkinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = signed_fixture()
        self.source = self.root / 'signed-skin.unity'
        self.source.write_bytes(self.raw)
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={'enabled': False, 'allow_download': False})
        self.token = secrets.token_hex(16)
        model_edits.register_session(self.token, [str(self.source)], preview['rig'])
        self.identity = mesh.inspect(self.token)['meshes'][0]['mesh']

    def state(self, influences):
        return {'version': 1, 'meshes': [{'mesh': self.identity,
            'weights': [{'vertex': 2, 'influences': influences}]}]}

    def test_native_signed_channel_exports_and_preserves_every_other_payload(self):
        original = mesh.data(self.token, self.identity)
        self.assertTrue(original['skinWritable'])
        output = mesh.export(self.token, self.state([[0, .25], [1, .75]]), self.root / 'out')
        saved = Path(output['preview_paths'][0]).read_bytes()
        before_env, before_rows = mesh._mesh_records(self.raw, 0)
        after_env, after_rows = mesh._mesh_records(saved, 0)
        before, after = before_rows[0][2], after_rows[0][2]
        self.assertEqual(before['m_VertexData']['m_Channels'][13]['format'], 11)
        self.assertEqual(after['m_VertexData']['m_Channels'], before['m_VertexData']['m_Channels'])
        _, channels, strides, starts, _ = stream_layout(before)
        weights = channels[12]
        indices = channels[13]
        start_w = starts[weights['stream']] + 2 * strides[weights['stream']] + weights['offset']
        start_i = starts[indices['stream']] + 2 * strides[indices['stream']] + indices['offset']
        initial, changed = before['m_VertexData']['m_DataSize'], after['m_VertexData']['m_DataSize']
        allowed = set(range(start_w, start_w + 16)) | set(range(start_i, start_i + 16))
        self.assertEqual(len(initial), len(changed))
        self.assertTrue(all(a == b for offset, (a, b) in enumerate(zip(initial, changed)) if offset not in allowed))
        self.assertEqual(struct.unpack_from('<4i', changed, start_i), (1, 0, 0, 0))
        self.assertEqual(struct.unpack_from('<4f', changed, start_w), (.75, .25, 0., 0.))
        clean_before, clean_after = copy.deepcopy(before), copy.deepcopy(after)
        clean_before['m_VertexData']['m_DataSize'] = clean_after['m_VertexData']['m_DataSize'] = b''
        self.assertEqual(clean_before, clean_after)
        def objects(env):
            return {(row.assets_file.name, row.path_id): row.get_raw_data() for row in env.objects if row.type.name != 'Mesh'}
        self.assertEqual(objects(before_env), objects(after_env))
        def streams(env):
            return {name: row.bytes for name, row in env.file.files.items() if not hasattr(row, 'objects')}
        self.assertTrue(streams(before_env))
        self.assertEqual(streams(before_env), streams(after_env))
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(output['original_paths'][0]).read_bytes(), self.raw)
        preview = model_viewer.prepare(output['preview_paths'], rigged=True,
            face_context={'enabled': False, 'allow_download': False})
        token = secrets.token_hex(16)
        model_edits.register_session(token, output['preview_paths'], preview['rig'])
        identity = mesh.inspect(token)['meshes'][0]['mesh']
        reloaded = mesh.data(token, identity)
        self.assertEqual(reloaded['skin'][2], [[1, .75], [0, .25]])
        self.assertEqual(reloaded['triangles'], original['triangles'])
        self.assertEqual(reloaded['positions'], original['positions'])

    def test_negative_out_of_range_overflow_and_boolean_indices_publish_nothing(self):
        for index in (-1, len(mesh.data(self.token, self.identity)['bones']), 2 ** 31, 2 ** 32, True):
            with self.subTest(index=index), self.assertRaises(mesh.MeshToolError):
                mesh.export(self.token, self.state([[index, 1.]]), self.root / 'out')
            self.assertEqual(self.source.read_bytes(), self.raw)
            self.assertFalse(list((self.root / 'out').glob('*')))

    def test_signed32_pack_overflow_rejects_before_saving_object(self):
        _, records = mesh._mesh_records(self.raw, 0)
        record = records[0]
        original_object = record[1].get_raw_data()
        with self.assertRaisesRegex(mesh.MeshToolError, 'cannot store'):
            # range provides a nonallocating bone-index domain so this reaches
            # the signed storage bound rather than stopping at rig bounds.
            mesh._write_mesh(record[1], copy.deepcopy(record[2]), range(2 ** 31 + 1),
                {'weights': [{'vertex': 2, 'influences': [[2 ** 31, 1.]]}]})
        self.assertEqual(record[1].get_raw_data(), original_object)
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
