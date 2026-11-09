"""Exact GLB primitive identity against real serialized Unity objects/indices."""
import copy
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest

import numpy as np
from webtools.core import model_edits, model_viewer as viewer, viewer_mesh_tools as mesh
from generate_viewer_mesh_fixture import fixture_bytes as multi_material_bytes
from generate_viewer_persistence_fixture import fixture_bytes as persistence_bytes
from test_model_faces import bundle
from test_model_rig import attribute


class MeshMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def prepare(self, raws):
        paths = []
        for index, raw in enumerate(raws):
            path = self.root / ('source-' + str(index) + '.unity'); path.write_bytes(raw); paths.append(str(path))
        metadata = viewer.prepare(paths, rigged=True, face_context={'enabled': False, 'allow_download': False})
        glb = viewer.get_model(metadata['id']); size = struct.unpack_from('<I', glb, 12)[0]
        return metadata, json.loads(glb[20:20 + size]), glb[28 + size:], paths

    def verify(self, raws, document, binary):
        sources = []
        for index, raw in enumerate(raws):
            _, records = mesh._mesh_records(raw, index)
            sources.append({(r[0]['file'], r[0]['id']): r for r in records})
        mappings = []
        for exported in document['meshes']:
            for primitive in exported['primitives']:
                mapping = primitive['extras']['viewerMesh']; mappings.append(mapping)
                identity = mapping['mesh']; record = sources[identity['source']][(identity['file'], identity['id'])]
                positions, _, weights, indices = mesh._arrays(record[1], record[2])
                triangles, spans, _ = mesh._triangles(record[2], len(positions))
                start, stop, _ = spans[mapping['submesh']]
                self.assertEqual(mapping['firstFace'], start); self.assertEqual(mapping['faceCount'], stop - start)
                self.assertEqual(mapping['vertexCount'], len(positions)); self.assertEqual(mapping['vertexOrder'], 'identity')
                self.assertTrue(mapping['writable'])
                transform = np.asarray(mapping['positionMatrix']).reshape(4, 4).T
                expected = np.c_[positions, np.ones(len(positions))] @ transform.T
                actual = attribute(document, binary, primitive['attributes']['POSITION'])
                self.assertTrue(np.allclose(actual, expected[:, :3], atol=1e-6))
                actual_faces = attribute(document, binary, primitive['indices']).reshape(-1, 3)
                self.assertEqual(len(actual_faces), stop - start)
                for actual_face, source_face in zip(actual_faces, triangles[start:stop]):
                    self.assertEqual(sorted(map(int, actual_face)), sorted(source_face), 'Face order/vertex identity must survive winding reflection')
                if indices is not None:
                    actual_indices = attribute(document, binary, primitive['attributes']['JOINTS_0'])
                    actual_weights = attribute(document, binary, primitive['attributes']['WEIGHTS_0'])
                    active = np.asarray(weights) > 0
                    self.assertTrue(np.array_equal(actual_indices[active], np.asarray(indices)[active]))
                    self.assertTrue(np.allclose(actual_weights, np.asarray(weights) / np.asarray(weights).sum(axis=1)[:, None]))
        return mappings

    def test_submeshes_repeated_positions_and_same_uvs_have_distinct_face_ranges(self):
        raw = multi_material_bytes(); _, document, binary, _ = self.prepare([raw]); mappings = self.verify([raw], document, binary)
        self.assertEqual([(m['submesh'], m['firstFace'], m['faceCount']) for m in mappings], [(0, 0, 4), (1, 4, 4)])

    def test_identical_path_ids_in_two_sources_never_share_identity(self):
        raw = persistence_bytes(morphs=True)
        _, document, binary, _ = self.prepare([raw, raw]); mappings = self.verify([raw, raw], document, binary)
        self.assertEqual({m['mesh']['source'] for m in mappings}, {0, 1})
        self.assertEqual({m['mesh']['file'] for m in mappings}, {0})
        for exported in document['meshes']:
            for primitive in exported['primitives']:
                for target in primitive.get('targets', []):
                    delta = attribute(document, binary, target['POSITION'])
                    self.assertEqual(len(delta), 6, 'Morph accessors keep the same original vertex domain')

    def test_serialized_file_ordinal_is_local_to_its_source(self):
        raw = persistence_bytes()
        multi_file = bundle([('first.assets', raw), ('second.assets', raw)])
        _, document, binary, _ = self.prepare([raw, multi_file]); mappings = self.verify([raw, multi_file], document, binary)
        self.assertEqual({(m['mesh']['source'], m['mesh']['file']) for m in mappings}, {(0, 0), (1, 0), (1, 1)})

    def test_saved_deletion_preserves_vertex_domain_and_remaps_new_face_offsets(self):
        raw = multi_material_bytes(); metadata, _, _, paths = self.prepare([raw])
        token = secrets.token_hex(16); model_edits.register_session(token, paths, metadata['rig'])
        identity = mesh.inspect(token)['meshes'][0]['mesh']
        result = mesh.export(token, {'version': 1, 'meshes': [{'mesh': identity, 'deleteFaces': [0, 5]}]}, self.root / 'saved')
        saved = Path(result['preview_paths'][0]).read_bytes()
        _, document, binary, _ = self.prepare([saved]); mappings = self.verify([saved], document, binary)
        self.assertEqual([(m['firstFace'], m['faceCount'], m['vertexCount']) for m in mappings], [(0, 3, 6), (3, 3, 6)])


if __name__ == '__main__':
    unittest.main()
