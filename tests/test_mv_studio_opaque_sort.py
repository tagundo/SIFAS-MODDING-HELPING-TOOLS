"""Unity's opaque front-to-back order: renderer bounds centres and queues of stage renderers."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from webtools.core import model_viewer
from webtools.core import mv_studio_stage_materials as stage

from test_mv_studio_blend_sky import _accessor, _blend_material, _glb, _primitives


class OpaqueSortCenterTests(unittest.TestCase):
    def test_bounds_centre_follows_the_vertex_frame(self):
        mesh = SimpleNamespace(m_LocalAABB=SimpleNamespace(m_Center=SimpleNamespace(x=1., y=2., z=3.)))
        world = np.eye(4)
        world[:3, 3] = [10., 0., -5.]
        matrix = np.diag([-1., 1., 1., 1.]) @ world
        self.assertEqual(stage.opaque_sort_center({}, mesh, matrix), [-11., 2., -2.])
        self.assertEqual(stage.opaque_sort_center({}, None, matrix, builtin_mesh=True), [-10., 0., -5.])
        self.assertIsNone(stage.opaque_sort_center({"m_SortingOrder": 1}, mesh, matrix),
                          "a sorting layer or order decides before the distance")
        self.assertIsNone(stage.opaque_sort_center({}, SimpleNamespace(m_LocalAABB=None), matrix))

    def test_material_queue_is_the_custom_or_the_geometry_queue(self):
        for queue, expected in ((-1, 2000), (2450, 2450), (3000, 3000)):
            material, scene, _ = _blend_material(queue=queue)
            self.assertEqual(stage.read_material(scene, material, {}, {})["queue"], expected)
        material, scene, tree = _blend_material()
        tree["m_CustomRenderQueue"] = 2.5
        self.assertNotIn("queue", stage.read_material(scene, material, {}, {}))


class ActualSkySortTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_10120 and SIFAS_TEST_STAGE_10120 to the original Android 10120
    (asset 1012003) stage_effect and stage bundles."""

    @staticmethod
    def export(variable):
        raw = os.environ.get(variable)
        if not raw or not Path(raw).is_file():
            raise unittest.SkipTest(f"Set {variable} to the original 10120 bundle")
        prepared = model_viewer.prepare([raw], rigged=False, face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
            "_mv_stage_motion_bindings": (), "_mv_performer": False, "_mv_native_stage_effect": False})
        return _glb(model_viewer.get_model(prepared["id"]))

    def test_dome_shares_the_stage_sky_vertices_and_sorts_after_it(self):
        effect, effect_binary = self.export("SIFAS_TEST_STAGE_EFFECT_10120")
        stage_doc, stage_binary = self.export("SIFAS_TEST_STAGE_10120")
        dome, = _primitives(effect, "mat_stg_so0120_opa_01")
        sky, = _primitives(stage_doc, "bg0018_01_sky_opa_mt")
        self.assertEqual(sky["extras"]["mvStageMaterial"]["shader"], "general")
        dome_positions = _accessor(effect, effect_binary, dome["attributes"]["POSITION"])
        stage_positions = _accessor(stage_doc, stage_binary, sky["attributes"]["POSITION"])
        used = stage_positions[np.unique(_accessor(stage_doc, stage_binary, sky["indices"]))]
        self.assertEqual({row.tobytes() for row in dome_positions}, {row.tobytes() for row in used},
                         "bit-identical preview vertices, so the two depths tie")
        self.assertEqual(dome["extras"]["mvStageMaterial"]["opaqueSort"]["queue"], 2000)
        dome_center = np.array(dome["extras"]["mvStageMaterial"]["opaqueSort"]["center"])
        stage_center = np.array(sky["extras"]["mvStageMaterial"]["opaqueSort"]["center"])
        self.assertEqual(sky["extras"]["mvStageMaterial"]["opaqueSort"]["queue"], 2000)
        self.assertGreater(dome_center[1], stage_center[1])
        # The AlphaTest queue (2450) is opaque too: the ground's balloon cut-outs sort in it, at the
        # ground renderer's bounds centre, after every Geometry queue renderer.
        cutouts = {doc_material: _primitives(stage_doc, doc_material)
                   for doc_material in ("bg0018_02_balloon_cut_mt", "bg0018_02_balloontree_cut_mt")}
        for name, primitives in cutouts.items():
            self.assertEqual(len(primitives), 1, name)
            self.assertEqual(primitives[0]["extras"]["mvStageMaterial"]["opaqueSort"],
                             {"queue": 2450, "center": stage_center.tolist()}, name)
        # The 10120 runtime dump's 201 main-camera samples lie in Unity x -8.35..10.60, y 0.003..1.97,
        # z -3.24..25.67 (preview x mirrored). From every corner of that box the stage bounds are
        # nearer: the stage draws first and the dome wins the depth tie, as the screencaps show.
        for x in (8.35, -10.60):
            for y in (0.003, 1.97):
                for z in (-3.24, 25.67):
                    eye = np.array([x, y, z])
                    self.assertLess(np.sum((stage_center - eye) ** 2), np.sum((dome_center - eye) ** 2))


if __name__ == "__main__":
    unittest.main()
