"""Serialized single-slot atlas geometry, with independently checked skin/morphs."""
from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
import UnityPy

import costume_part_transplant as part
from graft_atlas_geometry import flatten_material_groups


class Affine:
    def __init__(self, scale, offset):
        self.scale = np.asarray(scale)
        self.offset = np.asarray(offset)

    def remap_uv(self, uv):
        return uv * self.scale + self.offset


def mesh_fixture(*, half=False, legacy_skin=False):
    """Independent two-stream layout with a non-UV third coordinate and padding."""
    channels = [dict(stream=0, offset=0, format=0, dimension=0) for _ in range(14)]
    channels[0] = dict(stream=0, offset=0, format=0, dimension=3)
    channels[1] = dict(stream=0, offset=12, format=0, dimension=3)
    channels[3] = dict(stream=0, offset=24, format=2, dimension=4)
    channels[4] = dict(stream=1, offset=0, format=int(half), dimension=3)
    channels[5] = dict(stream=1, offset=8 if half else 12, format=0, dimension=2)
    if not legacy_skin:
        channels[12] = dict(stream=0, offset=28, format=0, dimension=4)
        channels[13] = dict(stream=0, offset=44, format=6, dimension=4)
    mesh = dict(m_VertexData=dict(m_VertexCount=4, m_Channels=channels),
        m_IndexFormat=0, m_IndexBuffer=np.asarray([0, 1, 2, 0, 2, 3], '<u2').tobytes(),
        m_SubMeshes=[dict(firstByte=0, indexCount=3, topology=0, baseVertex=0,
                          firstVertex=0, vertexCount=3),
                     dict(firstByte=6, indexCount=3, topology=0, baseVertex=0,
                          firstVertex=0, vertexCount=4)],
        m_BindPose=[dict(name='bindpose remains byte equivalent')], m_BoneNameHashes=[12, 17],
        m_Shapes=dict(vertices=[dict(index=0, vertex=dict(x=.1, y=.2, z=.3),
                                    normal=dict(x=1., y=0., z=0.), tangent=dict(x=0., y=1., z=0.)),
                               dict(index=2, vertex=dict(x=.4, y=.5, z=.6),
                                    normal=dict(x=0., y=1., z=0.), tangent=dict(x=1., y=0., z=0.)),
                               dict(index=0, vertex=dict(x=.7, y=.8, z=.9))],
                      shapes=[dict(firstVertex=0, vertexCount=2, hasNormals=True, hasTangents=True),
                              dict(firstVertex=2, vertexCount=1, hasNormals=False, hasTangents=False)],
                      channels=[dict(name='smile', frameIndex=0, frameCount=2)], fullWeights=[50., 100.]))
    vc, _, strides, starts, total = part.stream_layout(mesh)
    raw = np.arange(total, dtype=np.uint8)
    for stream, stride in strides.items():
        block = raw[starts[stream]:starts[stream] + vc * stride].reshape(vc, stride)
        if stream == 0:
            positions = np.asarray([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], '<f4')
            block[:, :12] = positions.view(np.uint8).reshape(4, 12)
        else:
            values = np.asarray([[0., 0., 4.], [1., 0., 5.], [1., 1., 6.], [0., 1., 7.]], '<f2' if half else '<f4')
            block[:, :values.shape[1] * values.dtype.itemsize] = values.view(np.uint8).reshape(4, -1)
    mesh['m_VertexData']['m_DataSize'] = raw.tobytes()
    if legacy_skin:
        mesh['m_Skin'] = [dict(**{f'weight[{k}]': (1. if k == 0 else 0.) for k in range(4)},
                               **{f'boneIndex[{k}]': i if k == 0 else 0 for k in range(4)}) for i in range(vc)]
    return mesh


class AtlasGeometryTests(unittest.TestCase):
    transforms = [Affine((.4, .8), (.05, .1)), Affine((.4, .8), (.55, .1))]

    def test_shared_vertices_split_and_all_non_uv_bytes_skin_and_morphs_survive(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                mesh = mesh_fixture(legacy_skin=legacy)
                before = deepcopy(mesh)
                stats = flatten_material_groups(mesh, self.transforms)
                self.assertEqual(stats, dict(source_submeshes=2, submeshes=1, vertices=6,
                                            split_vertices=2, triangles=2, index_format=0))
                np.testing.assert_array_equal(part.read_indices(mesh), [0, 1, 2, 4, 5, 3])
                self.assertEqual(mesh['m_SubMeshes'], [dict(firstByte=0, indexCount=6, topology=0,
                    baseVertex=0, firstVertex=0, vertexCount=6)])
                old_vc, channels, strides, starts, _ = part.stream_layout(before)
                vc, _, new_strides, new_starts, _ = part.stream_layout(mesh)
                old = np.frombuffer(before['m_VertexData']['m_DataSize'], np.uint8)
                new = np.frombuffer(mesh['m_VertexData']['m_DataSize'], np.uint8)
                source_ids = [0, 1, 2, 3, 0, 2]
                for stream, stride in strides.items():
                    original = old[starts[stream]:starts[stream] + old_vc * stride].reshape(old_vc, stride)
                    saved = new[new_starts[stream]:new_starts[stream] + vc * stride].reshape(vc, stride)
                    if stream == 0:
                        np.testing.assert_array_equal(saved, original[source_ids])
                    else:
                        # UV0.z, UV1 and the padding bytes must not change.
                        np.testing.assert_array_equal(saved[:, 8:], original[source_ids, 8:])
                        actual = saved[:, :8].copy().view('<f4').reshape(vc, 2)
                        np.testing.assert_allclose(actual, [[.05, .1], [.45, .1], [.45, .9],
                                                           [.55, .9], [.55, .1], [.95, .9]])
                for field in ('m_BindPose', 'm_BoneNameHashes'):
                    self.assertEqual(mesh[field], before[field])
                if legacy:
                    self.assertEqual(mesh['m_Skin'], [before['m_Skin'][i] for i in source_ids])
                shapes = mesh['m_Shapes']
                self.assertEqual([(frame['firstVertex'], frame['vertexCount']) for frame in shapes['shapes']], [(0, 4), (4, 2)])
                self.assertEqual([entry['index'] for entry in shapes['vertices']], [0, 2, 4, 5, 0, 4])
                self.assertEqual(shapes['channels'], before['m_Shapes']['channels'])
                self.assertEqual(shapes['fullWeights'], [50., 100.])
                for duplicate, original in ((2, 0), (3, 1), (5, 4)):
                    entry = dict(shapes['vertices'][duplicate]); entry['index'] = shapes['vertices'][original]['index']
                    self.assertEqual(entry, shapes['vertices'][original])

    def test_float16_uv_and_base_vertex_are_supported(self):
        mesh = mesh_fixture(half=True)
        mesh['m_SubMeshes'][1]['baseVertex'] = 1
        mesh['m_IndexBuffer'] = np.asarray([0, 1, 2, 0, 1, 2], '<u2').tobytes()
        flatten_material_groups(mesh, self.transforms)
        np.testing.assert_array_equal(part.read_indices(mesh), [0, 1, 2, 4, 5, 3])
        vc, _, strides, starts, _ = part.stream_layout(mesh)
        block = np.frombuffer(mesh['m_VertexData']['m_DataSize'], np.uint8)[starts[1]:starts[1] + vc * strides[1]].reshape(vc, strides[1])
        uv = block[:, :4].copy().view('<f2').reshape(vc, 2)
        np.testing.assert_allclose(uv, [[.05,.1],[.45,.1],[.45,.9],[.55,.9],[.95,.1],[.95,.9]], atol=.001)
        source = mesh_fixture(half=True)
        _, _, old_strides, old_starts, _ = part.stream_layout(source)
        original = np.frombuffer(source['m_VertexData']['m_DataSize'], np.uint8)[old_starts[1]:old_starts[1] + 4 * old_strides[1]].reshape(4, old_strides[1])
        np.testing.assert_array_equal(block[:, 4:], original[[0,1,2,3,1,2], 4:])

    def test_identity_has_no_uv_inset_padding_or_unreferenced_vertex_removal(self):
        mesh = mesh_fixture()
        mesh['m_SubMeshes'] = mesh['m_SubMeshes'][:1]
        before = deepcopy(mesh)
        stats = flatten_material_groups(mesh, [Affine((1, 1), (0, 0))])
        self.assertEqual(stats['split_vertices'], 0)
        self.assertEqual(stats['vertices'], 4)  # Vertex 3 remains, though unreferenced.
        self.assertEqual(mesh['m_VertexData']['m_DataSize'], before['m_VertexData']['m_DataSize'])
        self.assertEqual(mesh['m_Shapes'], before['m_Shapes'])

    def test_identical_affine_tiles_reuse_shared_original_and_split_rows(self):
        mesh = mesh_fixture()
        # A third material uses the second material's exact atlas rectangle.
        third = deepcopy(mesh['m_SubMeshes'][1])
        third['firstByte'] = len(mesh['m_IndexBuffer'])
        mesh['m_SubMeshes'].append(third)
        mesh['m_IndexBuffer'] += np.asarray([0,2,3], '<u2').tobytes()
        stats = flatten_material_groups(mesh, [self.transforms[0], self.transforms[1],
            Affine((.4,.8), (.55,.1))])
        self.assertEqual(stats['split_vertices'], 2)
        np.testing.assert_array_equal(part.read_indices(mesh), [0,1,2,4,5,3,4,5,3])
        same = mesh_fixture()
        stats = flatten_material_groups(same, [Affine((.5,1), (0,0)), Affine((.5,1), (0,0))])
        self.assertEqual(stats['split_vertices'], 0)
        np.testing.assert_array_equal(part.read_indices(same), [0,1,2,0,2,3])

    def test_every_failure_keeps_caller_mesh_unchanged(self):
        def overflow(mesh): return dict(max_vertices=5)
        def bad_index(mesh): mesh['m_IndexBuffer'] = np.asarray([0,1,9,0,2,3], '<u2').tobytes(); return {}
        def bad_frame(mesh): mesh['m_Shapes']['shapes'][1]['firstVertex'] = 0; return {}
        def variable_skin(mesh): mesh['m_VariableBoneCountWeights'] = dict(m_Data=[1]); return {}
        def compressed(mesh): mesh['m_CompressedMesh'] = dict(m_UV=dict(m_NumItems=8)); return {}
        def streamed(mesh): mesh['m_StreamData'] = dict(size=100, path='mesh.resS'); return {}
        def bad_uv(mesh): mesh['m_VertexData']['m_Channels'][4]['format'] = 2; return {}
        def misaligned(mesh): mesh['m_SubMeshes'][1]['firstByte'] = 5; return {}
        for alter in (overflow, bad_index, bad_frame, variable_skin, compressed, streamed, bad_uv, misaligned):
            with self.subTest(case=alter.__name__):
                mesh = mesh_fixture(); kwargs = alter(mesh); before = deepcopy(mesh)
                with self.assertRaises(ValueError): flatten_material_groups(mesh, self.transforms, **kwargs)
                self.assertEqual(mesh, before)

    def test_uint32_indices_retained_and_unreferenced_original_rows_preserved(self):
        mesh = mesh_fixture()
        mesh['m_IndexFormat'] = 1
        mesh['m_IndexBuffer'] = np.asarray([0,1,2,0,2,3], '<u4').tobytes()
        mesh['m_SubMeshes'][1]['firstByte'] = 12
        flatten_material_groups(mesh, self.transforms)
        self.assertEqual(mesh['m_IndexFormat'], 1)
        self.assertEqual(len(mesh['m_IndexBuffer']), 24)

    def test_native_mesh_typetree_reopens_as_one_submesh_with_valid_morph_indices(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from generate_viewer_persistence_fixture import fixture_bytes
        env = UnityPy.load(fixture_bytes(morphs=True, mixed_skin=True))
        obj = next(obj for obj in env.objects if obj.type.name == 'Mesh')
        tree = obj.read_typetree()
        first = deepcopy(tree['m_SubMeshes'][0])
        first.update(firstByte=len(tree['m_IndexBuffer']), baseVertex=0)
        tree['m_SubMeshes'].append(first)
        tree['m_IndexBuffer'] = bytes(tree['m_IndexBuffer']) * 2
        before_vertices = tree['m_VertexData']['m_VertexCount']
        before_bones = deepcopy(tree['m_BindPose'])
        flatten_material_groups(tree, self.transforms)
        obj.save_typetree(tree)
        reopened = next(o for o in UnityPy.load(env.file.save()).objects if o.type.name == 'Mesh').read_typetree()
        self.assertEqual(len(reopened['m_SubMeshes']), 1)
        self.assertEqual(reopened['m_SubMeshes'][0]['indexCount'], first['indexCount'] * 2)
        self.assertEqual(reopened['m_VertexData']['m_VertexCount'], before_vertices * 2)
        self.assertEqual(reopened['m_BindPose'], before_bones)
        self.assertEqual([entry['index'] for entry in reopened['m_Shapes']['vertices']], [4, 4 + before_vertices])


if __name__ == '__main__':
    unittest.main()
