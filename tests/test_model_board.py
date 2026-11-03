"""Native board initialization preserves source TRS and coherent rigid skinning."""
import copy
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import model_board as board
from webtools.core import model_viewer as viewer
import test_model_faces as face_fixture
from test_model_rig import unpack, evaluate, node_worlds


class BoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
            import numpy
        except ImportError as error:
            raise unittest.SkipTest("UnityPy and numpy are required") from error
        cls.UnityPy, cls.np = UnityPy, numpy

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "board.unity"
        self.addCleanup(viewer._SESSIONS.clear)

    def source(self, owner=209, *, head="Head_Face", dots="mesh_facedots", active=True,
               enabled=True, unknown=False, overlay=False):
        data = face_fixture.FaceTests.board_part(self, owner=owner, head=head, active=active, overlay=overlay)
        env = self.UnityPy.load(data)
        for obj in list(env.objects):
            if obj.type.name == "AnimationClip":
                del obj.assets_file.objects[obj.path_id]
                continue
            if obj.type.name not in ("Transform", "GameObject", "Mesh", "SkinnedMeshRenderer"):
                continue
            tree = obj.read_typetree()
            if obj.type.name == "GameObject":
                if obj.path_id == 2 and unknown:
                    tree["m_Name"] = "UnknownCharacter"
                if obj.path_id == 6 and not overlay:
                    tree["m_Name"] = dots
            elif obj.type.name == "Transform" and obj.path_id == 7:
                # The native operation replaces this value; it must not add.
                tree["m_LocalPosition"] = dict(zip("xyz", [.2, -.3, .4]))
            elif obj.type.name == "Mesh":
                tree["m_BindPose"] = []
            elif obj.type.name == "SkinnedMeshRenderer":
                tree["m_Bones"] = []
                tree["m_Enabled"] = enabled
            obj.save_typetree(tree)
        self.path.write_bytes(next(iter(env.files.values())).save())
        return self.path

    def scene(self, trees=None):
        deadline = time.monotonic() + 30
        return viewer._Scene(viewer._environment([str(self.path)], deadline), deadline, trees=trees)

    def named(self, scene, name):
        return next(t for t in scene.transforms.values()
                    if scene.name(viewer._ref(t, scene.tree(t)["m_GameObject"])) == name)

    def test_source_values_remain_raw_while_world_and_local_view_use_absolute_native_position(self):
        self.source()
        scene = self.scene()
        transform = self.named(scene, "mesh_facedots")
        source = copy.deepcopy(scene.tree(transform))
        runtime = scene.local_tree(transform)
        self.assertEqual(runtime["m_LocalPosition"], dict(zip("xyz", board.BOARD_POSITION)))
        self.assertEqual(scene.tree(transform), source)
        self.np.testing.assert_allclose(list(source["m_LocalPosition"].values()), [.2, -.3, .4], atol=2e-8)
        parent = viewer._ref(transform, source["m_Father"])
        expected = scene.world(parent) @ viewer._trs(runtime)
        self.np.testing.assert_allclose(scene.world(transform), expected, atol=1e-12)
        runtime["m_LocalPosition"]["z"] = 99
        self.assertEqual(scene.local_tree(transform)["m_LocalPosition"]["z"], board.BOARD_POSITION[2])
        self.assertEqual(scene.tree(transform), source)

    def test_expanded_scene_reuses_raw_trees_without_accumulating_or_modifying_input_cache(self):
        self.source()
        scene = self.scene()
        transform = self.named(scene, "mesh_facedots")
        first = scene.world(transform).copy()
        cache = copy.deepcopy(scene.trees)
        for _ in range(3):
            scene = viewer._Scene(scene.env, time.monotonic() + 30, trees=scene.trees)
            transform = self.named(scene, "mesh_facedots")
            self.np.testing.assert_array_equal(scene.world(transform), first)
            self.assertEqual(scene.trees, cache)

    def test_real_source_identity_and_exact_active_native_hierarchy_are_required(self):
        for values, expected in [({"owner": 209}, True), ({"owner": 9999}, True),
                                 ({"owner": 207}, False), ({"unknown": True}, False),
                                 ({"head": "Head_face"}, False), ({"dots": "mesh_faceDots"}, False),
                                 ({"active": False}, False), ({"enabled": False}, False),
                                 ({"overlay": True}, False)]:
            with self.subTest(values=values):
                self.source(**values)
                self.assertEqual(bool(self.scene().runtime_positions), expected)

    def test_both_exact_targets_use_same_head_but_cross_source_overlay_is_rejected(self):
        self.source()
        scene = self.scene()
        dots = self.named(scene, "mesh_facedots")
        leaf = self.named(scene, "UnknownDisplayLeaf")
        # Reuse two ordinary unused bones as a native overlay hierarchy.
        mask = self.named(scene, "unusedBone")
        for transform, name, parent in ((mask, "mesh_mask", viewer._ref(dots, scene.tree(dots)["m_Father"])),
                                        (leaf, "Mask_DisplayOverlayparts", mask)):
            game = viewer._ref(transform, scene.tree(transform)["m_GameObject"])
            scene.tree(game)["m_Name"] = name
            scene.names.pop(viewer._key(game), None)
            scene.tree(transform)["m_Father"] = {"m_FileID": 0, "m_PathID": parent.path_id}
        # The original board renderer now points at overlay; add another real
        # active renderer record below dots to retain native board evidence.
        renderer, tree, _ = scene.renderers[0]
        dots_go = viewer._ref(dots, scene.tree(dots)["m_GameObject"])
        scene.renderers.append((renderer, tree, dots_go))
        actual = board.board_positions(scene)
        self.assertEqual(set(actual), {viewer._key(dots), viewer._key(leaf)})
        source_path = viewer._source_path
        with patch.object(viewer, "_source_path", side_effect=lambda obj: "other.unity" if obj is leaf else source_path(obj)):
            self.assertEqual(set(board.board_positions(scene)), {viewer._key(dots)})

    def test_foreign_transform_or_mesh_cannot_borrow_same_named_rina_hierarchy(self):
        self.source()
        scene = self.scene()
        dots = self.named(scene, "mesh_facedots")
        renderer, tree, game = scene.renderers[0]
        mesh = viewer._ref(renderer, tree["m_Mesh"])
        source_path = viewer._source_path
        for foreign in (dots, game, mesh):
            with self.subTest(type=foreign.type.name), patch.object(
                    viewer, "_source_path", side_effect=lambda obj: "other.unity" if obj is foreign else source_path(obj)):
                self.assertEqual(board.board_positions(scene), {})

    def test_static_and_rigged_rest_and_rotated_head_share_native_placement_without_source_edits(self):
        self.source()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        static = evaluate(*unpack(viewer.prepare([str(self.path)])))
        result = viewer.prepare([str(self.path)], rigged=True)
        document, binary = unpack(result)
        rigged = evaluate(document, binary)
        self.assertTrue(result["rig"]["available"])
        for name in static:
            self.np.testing.assert_allclose(rigged[name], static[name], atol=2e-6)
        dots_node = next(b["node"] for b in result["rig"]["bones"] if b["name"] == "mesh_facedots")
        self.assertEqual(document["nodes"][dots_node]["translation"], list(board.BOARD_POSITION))
        self.np.testing.assert_allclose(result["rig"]["sourcePositions"][dots_node], [-.2, -.3, .4], atol=2e-8)
        head = next(b["node"] for b in result["rig"]["bones"] if b["name"] == "Head_Face")
        rotation = [0, .3826834323650898, 0, .9238795325112867]
        changed = evaluate(document, binary, {head: {"rotation": rotation}})
        rest_world = node_worlds(document)[head]
        changed_world = node_worlds(document, {head: {"rotation": rotation}})[head]
        delta = changed_world @ self.np.linalg.inv(rest_world)
        for name, points in rigged.items():
            expected = points @ delta[:3, :3].T + delta[:3, 3]
            self.np.testing.assert_allclose(changed[name], expected, atol=2e-6)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_unrelated_model_serialization_and_scaling_metadata_are_unchanged(self):
        from test_model_rig import FIXTURE
        original = viewer.prepare([str(FIXTURE)], rigged=True)
        original_doc, original_binary = unpack(original)
        with patch.object(board, "board_positions", return_value={}):
            baseline = viewer.prepare([str(FIXTURE)], rigged=True)
            baseline_doc, baseline_binary = unpack(baseline)
        self.assertEqual((original_doc, original_binary), (baseline_doc, baseline_binary))
        self.assertEqual(original["rig"], baseline["rig"])


if __name__ == "__main__":
    unittest.main()
