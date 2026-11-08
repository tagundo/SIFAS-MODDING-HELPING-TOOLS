"""Bounded Mesh Baker output against the independent pre-chunk algorithm.

All meshes are generated from the repository's neutral fixture. The reference
below retains the original dense whole-mesh operations, including its global
singular-normal fallback. No game assets or user databases are used.
"""
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy
import sifas_mesh_baker as baker

def _legacy_bake_mesh(tree, bone_names, parent, targets, recompute_normals=True, hierarchical=True):
    """제자리에서 tree 의 m_VertexData/m_LocalAABB 수정. stats 반환.
    bone_names/parent 는 resolve_bones() 결과(길이 = m_BindPose 수)."""
    bps_raw = tree.get('m_BindPose', [])
    if not bps_raw or not bone_names:
        return {'skinned': False, 'applied': [], 'compensated': [], 'influenced': 0, 'max_disp': 0.0}
    idx2leaf = bone_names
    name2idx = {}
    for i, n in enumerate(idx2leaf):
        name2idx.setdefault(n, i)
    bps = [baker.mat_from(b) for b in bps_raw]
    rest_world = [np.linalg.inv(b) for b in bps] if any((getattr(target, 'compensate_explicit', False) and target.compensate for target in targets)) else None
    deltas, applied, comp, missing = baker.expand_targets(targets, parent, name2idx, idx2leaf, rest_world=rest_world)
    if not deltas:
        return {'skinned': True, 'applied': [], 'compensated': [], 'influenced': 0, 'max_disp': 0.0, 'missing': missing}
    vc, chans, stride, start, _ = baker.stream_layout(tree)
    buf = bytearray(tree['m_VertexData']['m_DataSize'])
    u8 = np.frombuffer(buf, dtype=np.uint8)
    nb = len(bps)
    M = baker.hierarchical_skin_matrices(bps, parent, deltas) if hierarchical else baker.independent_skin_matrices(bps, deltas)
    pos = baker.read_attr(u8, baker.ATTR_POS, chans, stride, start, vc)
    w, bidx = baker.get_skin(u8, tree, chans, stride, start, vc)
    if pos is None or w is None:
        return {'skinned': True, 'applied': [], 'compensated': [], 'influenced': 0, 'max_disp': 0.0, 'error': 'could not read vertex/skin data'}
    bidx = np.clip(bidx, 0, nb - 1)
    Mb = M[bidx]
    Bv = (Mb * w[..., None, None]).sum(axis=1)
    ph = np.concatenate([pos, np.ones((vc, 1))], axis=1)
    newpos = np.einsum('vij,vj->vi', Bv, ph)[:, :3]
    baker.write_attr(u8, newpos, baker.ATTR_POS, chans, stride, start, vc)
    moved_idx = set(deltas.keys())
    infl_mask = np.zeros(vc, bool)
    for k in range(4):
        infl_mask |= np.isin(bidx[:, k], list(moved_idx)) & (w[:, k] > 0)
    disp = np.linalg.norm(newpos - pos, axis=1)
    if recompute_normals:
        R3 = Bv[:, :3, :3]
        n = baker.read_attr(u8, baker.ATTR_NORMAL, chans, stride, start, vc)
        if n is not None:
            try:
                NIT = np.linalg.inv(R3).transpose(0, 2, 1)
            except np.linalg.LinAlgError:
                NIT = R3.copy()
                dets = np.linalg.det(R3)
                ok = np.abs(dets) > 1e-12
                NIT[ok] = np.linalg.inv(R3[ok]).transpose(0, 2, 1)
            newn = np.einsum('vij,vj->vi', NIT, n)
            ln = np.linalg.norm(newn, axis=1, keepdims=True)
            ln[ln == 0] = 1
            baker.write_attr(u8, newn / ln, baker.ATTR_NORMAL, chans, stride, start, vc)
        t = baker.read_attr(u8, baker.ATTR_TANGENT, chans, stride, start, vc)
        if t is not None:
            txyz = np.einsum('vij,vj->vi', R3, t[:, :3])
            lt = np.linalg.norm(txyz, axis=1, keepdims=True)
            lt[lt == 0] = 1
            t[:, :3] = txyz / lt
            baker.write_attr(u8, t, baker.ATTR_TANGENT, chans, stride, start, vc)
    mn, mx = (newpos.min(0), newpos.max(0))
    c, e = ((mn + mx) / 2, (mx - mn) / 2)
    old = tree['m_LocalAABB']
    tree['m_LocalAABB'] = {'m_Center': {'x': float(c[0]), 'y': float(c[1]), 'z': float(c[2])}, 'm_Extent': {'x': float(e[0]), 'y': float(e[1]), 'z': float(e[2])}}
    tree['m_VertexData']['m_DataSize'] = bytes(buf)
    return {'skinned': True, 'applied': applied, 'compensated': comp, 'missing': missing, 'influenced': int(infl_mask.sum()), 'max_disp': float(disp[infl_mask].max()) if infl_mask.any() else 0.0, 'max_disp_other': float(disp[~infl_mask].max()) if (~infl_mask).any() else 0.0, 'old_extent': (old['m_Extent']['x'], old['m_Extent']['y'], old['m_Extent']['z']), 'new_extent': (float(e[0]), float(e[1]), float(e[2]))}


class ExplicitTarget(baker.Target):
    compensate_explicit = True


def unity_bundle(raw):
    version = b"2019.4.0f1"
    name = ("CAB-" + hashlib.sha256(raw).hexdigest()[:32]).encode()
    info = bytes(16) + struct.pack(">iIIHi", 1, len(raw), len(raw), 0, 1)
    info += struct.pack(">qqI", 0, len(raw), 0) + name + b"\0"
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + version + b"\0"
    return prefix + struct.pack(">QIII", len(prefix)+20+len(info)+len(raw),
                                len(info), len(info), 64) + info + raw


class MeshBakerChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()

    def source(self, repeats=1, platform=13, tangents=True, overlap=False, rotated_bindposes=False):
        env = UnityPy.load(self.original)
        env.file.target_platform = platform
        env.file._m_target_platform = platform
        obj = next(obj for obj in env.objects if obj.type.name == "Mesh")
        tree = obj.read_typetree()
        if rotated_bindposes:
            rest = [np.eye(4), baker.trs(translate=(.2, .7, -.1), rotate=(19, -13, 7))]
            rest.append(rest[1] @ baker.trs(translate=(.1, .3, .2), rotate=(-11, 23, 41)))
            inverse = [np.linalg.inv(matrix) for matrix in rest]
            tree["m_BindPose"] = [{f"e{r}{c}": float(matrix[r, c])
                                  for r in range(4) for c in range(4)} for matrix in inverse]
        vertex = tree["m_VertexData"]
        vertex["m_VertexCount"] *= repeats
        vertex["m_DataSize"] *= repeats
        count, channels, stride, start, _ = baker.stream_layout(tree)
        buf = bytearray(vertex["m_DataSize"])
        # Real Float32 weights for three bones, including blended and rigid
        # vertices. Repeated and unique weights exercise the same chunk path.
        rng = np.random.default_rng(20261108)
        weights = rng.random((count, 4)); weights[:, 3] = 0
        weights /= weights.sum(1)[:, None]
        data = np.frombuffer(buf, np.uint8)
        baker.write_attr(data, weights, baker.ATTR_BLENDWEIGHT, channels, stride, start, count)
        block = data.reshape(count, stride[0])
        block[:, 48:52] = np.asarray([0, 1, 2, 0], np.uint8)
        vertex["m_DataSize"] = bytes(buf)
        if tangents:
            if overlap:
                channels[baker.ATTR_TANGENT] = dict(stream=0, offset=12, format=0, dimension=4)
            else:
                channels[baker.ATTR_TANGENT] = dict(stream=1, offset=0, format=0, dimension=4)
                padded = (len(buf) + 15) // 16 * 16
                tangent = np.zeros((count, 4), dtype="<f4")
                tangent[:, :3] = [.6, .8, 0]
                tangent[:, 3] = np.where(np.arange(count) % 2, -1, 1)
                vertex["m_DataSize"] = bytes(buf) + bytes(padded-len(buf)) + tangent.tobytes()
        obj.save_typetree(tree)
        return unity_bundle(env.file.save())

    def compare(self, raw, targets, **kwargs):
        outputs, results = [], []
        for function in (_legacy_bake_mesh, baker.bake_mesh):
            env = UnityPy.load(raw)
            ids = baker.build_id_map(env)
            names = baker.build_bone_name_map(env)
            renderers = baker.smr_bone_pids(env, ids)
            meshes = baker.list_meshes(env)
            self.assertEqual(len(meshes), 1)
            mesh = meshes[0]
            bones, parents = baker.resolve_bones(env, ids, names, mesh.obj, mesh.tree, renderers)
            result = function(mesh.tree, bones, parents, targets, **kwargs)
            mesh.obj.save_typetree(mesh.tree)
            results.append(result)
            outputs.append(env.file.save(packer="original"))
        self.assertEqual(results[0], results[1])
        self.assertEqual(outputs[0], outputs[1], "Whole serialized native bundle changed")
        return outputs[1], results[1]

    def test_position_normal_tangent_and_compensation_match_complete_native_bundles(self):
        for platform in (13, 9):
            for hierarchical in (True, False):
                with self.subTest(platform=platform, hierarchical=hierarchical):
                    raw = self.source(repeats=2731, platform=platform)
                    targets = [baker.Target("LeftUpLeg", scale=(1, .8, 1.2),
                               rotate=(17, -9, 23), translate=(.02, -.01, .03), compensate=True),
                               baker.Target("BreastSize", scale=(1.1, .95, 1.03))]
                    self.compare(raw, targets, hierarchical=hierarchical)

    def test_rotated_rest_child_compensation_and_preset_keep_original_results(self):
        raw = self.source(repeats=1366, rotated_bindposes=True)
        self.compare(raw, [ExplicitTarget("LeftUpLeg", scale=(1, .83, 1.17),
                     rotate=(11, 2, -13), compensate=True, comp_bones=["BreastSize"])])
        self.compare(raw, baker.thigh_targets("slim", "thick"))

    def test_normal_singular_fallback_is_global_across_chunk_boundaries(self):
        raw = self.source(repeats=2731)
        matrices = np.repeat(np.eye(4)[None], 3, axis=0)
        matrices[0, 0, 0] = 1e-14
        matrices[1, 0, 0] = 0
        matrices[2, :3, :3] = np.diag([1.1, .9, 1.2])
        env = UnityPy.load(raw); mesh = baker.list_meshes(env)[0]
        tree = mesh.tree; count, channels, stride, start, _ = baker.stream_layout(tree)
        buf = bytearray(tree["m_VertexData"]["m_DataSize"]); data = np.frombuffer(buf, np.uint8)
        weights = np.zeros((count, 4)); weights[:, 0] = 1
        baker.write_attr(data, weights, baker.ATTR_BLENDWEIGHT, channels, stride, start, count)
        # stream0 sits before the independent tangent stream.
        data[:count*stride[0]].reshape(count, stride[0])[:, 48:52] = [0, 0, 0, 0]
        data[:count*stride[0]].reshape(count, stride[0])[baker._BAKE_CHUNK_VERTICES:, 48] = 2
        data[:count*stride[0]].reshape(count, stride[0])[baker._BAKE_CHUNK_VERTICES, 48] = 1
        normals = np.repeat(np.asarray([[1., 1., 0.]])/np.sqrt(2), count, axis=0)
        baker.write_attr(data, normals, baker.ATTR_NORMAL, channels, stride, start, count)
        tree["m_VertexData"]["m_DataSize"] = bytes(buf); mesh.obj.save_typetree(tree)
        mixed = env.file.save(packer="original")
        with patch.object(baker, "hierarchical_skin_matrices", return_value=matrices):
            result, _ = self.compare(mixed, [baker.Target("LeftUpLeg", scale=(1, .9, 1.1))])
        mesh = baker.list_meshes(UnityPy.load(result))[0]
        count, channels, stride, start, _ = baker.stream_layout(mesh.tree)
        normal = baker.read_attr(np.frombuffer(mesh.tree["m_VertexData"]["m_DataSize"], np.uint8),
                                 baker.ATTR_NORMAL, channels, stride, start, count)
        self.assertLess(abs(normal[0, 0]), 1e-12)
        self.assertGreater(normal[0, 1], .99)

    def test_overlapping_attributes_keep_original_write_then_read_order(self):
        self.compare(self.source(repeats=1366, overlap=True),
                     [baker.Target("LeftUpLeg", scale=(1.2, .8, 1.1), rotate=(11, 23, -17))])

    def test_normal_disabled_and_noop_keep_original_behavior(self):
        self.compare(self.source(repeats=1366),
                     [baker.Target("LeftUpLeg", scale=(1.1, .9, 1.2))], recompute_normals=False)
        self.compare(self.source(), [baker.Target("LeftUpLeg")])

    def test_optional_attributes_and_reflections_keep_original_results(self):
        target = [baker.Target("LeftUpLeg", scale=(-1.2, .8, 1.1))]
        for normals, tangents in ((False, False), (False, True), (True, False)):
            with self.subTest(normals=normals, tangents=tangents):
                env = UnityPy.load(self.source(repeats=1366, tangents=tangents))
                mesh = baker.list_meshes(env)[0]
                if not normals:
                    mesh.tree["m_VertexData"]["m_Channels"][baker.ATTR_NORMAL]["dimension"] = 0
                mesh.obj.save_typetree(mesh.tree)
                self.compare(env.file.save(packer="original"), target)

    def test_unrelated_blend_shape_data_and_other_serialized_fields_are_preserved(self):
        from generate_viewer_persistence_fixture import fixture_bytes
        with patch.object(self, "original", fixture_bytes(morphs=True, mixed_skin=True)):
            raw = self.source(repeats=1366)
        before = baker.list_meshes(UnityPy.load(raw))[0].tree["m_Shapes"]
        output, _ = self.compare(raw, [baker.Target("LeftUpLeg", scale=(1, .9, 1.1), compensate=True)])
        self.assertEqual(baker.list_meshes(UnityPy.load(output))[0].tree["m_Shapes"], before)

    def test_large_mesh_bounds_every_dense_matrix_batch(self):
        original_einsum = np.einsum
        batches = []
        def bounded(expression, *args, **kwargs):
            if expression == "vij,vj->vi":
                batches.append(len(args[0]))
                self.assertLessEqual(len(args[0]), baker._BAKE_CHUNK_VERTICES)
            return original_einsum(expression, *args, **kwargs)
        with patch.object(np, "einsum", side_effect=bounded):
            env = UnityPy.load(self.source(repeats=4000)); mesh = baker.list_meshes(env)[0]
            ids = baker.build_id_map(env); names = baker.build_bone_name_map(env)
            bones, parents = baker.resolve_bones(env, ids, names, mesh.obj, mesh.tree, baker.smr_bone_pids(env, ids))
            result = baker.bake_mesh(mesh.tree, bones, parents, [baker.Target("LeftUpLeg", scale=(1.1, .9, 1.2))])
        self.assertGreater(len(batches), 3)
        self.assertTrue(result["applied"])


if __name__ == "__main__":
    unittest.main()
