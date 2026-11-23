"""AxisBillboard light-beam cones listed by LiveCoreStageEffect.axisBillboards.

Set SIFAS_TEST_MV_TIMELINE and SIFAS_TEST_MV_EFFECT to an original live_timeline
and stage_effect bundle pair (for example 12035) for the real export check;
SIFAS_TEST_MV_AXIS_BILLBOARDS optionally names the expected tagged-node count.
"""
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_axis_billboard as billboard


def _object(kind, path_id, tree):
    return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=path_id, assets_file=SimpleNamespace(), tree=tree)


class AxisBillboardOwnerTests(unittest.TestCase):
    def setUp(self):
        effect_script = _object("MonoScript", 1, {"m_AssemblyName": "Assembly-CSharp.dll",
                                                  "m_Namespace": "LLAS.Scene.Live.Components",
                                                  "m_ClassName": "LiveCoreStageEffect"})
        axis_script = _object("MonoScript", 2, {"m_AssemblyName": "Assembly-CSharp.dll",
                                                "m_Namespace": "LLAS.Components.AxisBillboard",
                                                "m_ClassName": "AxisBillboard"})
        other_script = _object("MonoScript", 3, {"m_AssemblyName": "Assembly-CSharp.dll",
                                                 "m_Namespace": "LLAS.Components.AxisBillboard",
                                                 "m_ClassName": "Billboard"})
        self.file = SimpleNamespace()
        self.games = {pid: _object("GameObject", pid, {}) for pid in (20, 21, 22, 30)}
        # Initialize enables a listed component even when it is serialized disabled.
        self.objects = {1: effect_script, 2: axis_script, 3: other_script, **self.games,
                        10: _object("MonoBehaviour", 10, {"m_Script": {"m_PathID": 2}, "m_Enabled": 0,
                                                         "m_GameObject": {"m_PathID": 20}}),
                        11: _object("MonoBehaviour", 11, {"m_Script": {"m_PathID": 2}, "m_Enabled": 1,
                                                         "m_GameObject": {"m_PathID": 21}}),
                        12: _object("MonoBehaviour", 12, {"m_Script": {"m_PathID": 3}, "m_Enabled": 1,
                                                         "m_GameObject": {"m_PathID": 22}})}
        for obj in self.objects.values():
            obj.assets_file = self.file
        self.scene = SimpleNamespace(tree=lambda obj: obj.tree)
        self.ref = patch.object(viewer, "_ref", lambda owner, pointer: self.objects.get((pointer or {}).get("m_PathID")))
        self.ref.start()
        self.addCleanup(self.ref.stop)

    def owners(self, tree):
        component = _object("MonoBehaviour", 99, tree)
        component.assets_file = self.file
        self.scene.env = SimpleNamespace(objects=[component, *self.objects.values()])
        paths = {30: ("fx_root",), 20: ("fx_root", "lit_01", "litB_01_bilcone"),
                 21: ("other_root", "litB_02_bilcone"), 22: ("fx_root", "lit_01", "litC_01_bilcone")}
        with patch.object(billboard, "_path", lambda scene, game: paths.get(game.path_id, ())):
            return billboard.owners(self.scene, component, tree)

    def test_every_axis_billboard_below_the_stage_effect_is_an_owner(self):
        # GetComponentsInChildren<AxisBillboard>(true): disabled components count, and
        # Initialize enables them; the serialized axisBillboards array is replaced.
        tree = {"m_Script": {"m_PathID": 1}, "m_GameObject": {"m_PathID": 30}, "axisBillboards": []}
        self.assertEqual(self.owners(tree), {viewer._key(self.games[20])})
        # Another component is not LiveCoreStageEffect.
        self.assertEqual(self.owners({**tree, "m_Script": {"m_PathID": 3}}), set())

    def test_tag_marks_only_retained_nodes_and_keeps_their_trs(self):
        nodes = [{"name": "litB_01_bilcone", "rotation": [0, .5, 0, .8660254], "extras": {"mvStageNode": {"active": True}}},
                 {"name": "other"}]
        glb = SimpleNamespace(doc={"nodes": [dict(node) for node in nodes]})
        stage_nodes = SimpleNamespace(nodes={("file", 20): 0})
        self.assertEqual(billboard.tag(glb, stage_nodes, {("file", 20), ("file", 21)}), 1)
        self.assertEqual(glb.doc["nodes"][0]["extras"], {"mvStageNode": {"active": True}, "mvAxisBillboard": 1})
        self.assertEqual(glb.doc["nodes"][0]["rotation"], nodes[0]["rotation"])
        self.assertNotIn("extras", glb.doc["nodes"][1])
        self.assertEqual(billboard.tag(glb, None, {("file", 20)}), 0)


@unittest.skipUnless(os.environ.get("SIFAS_TEST_MV_TIMELINE") and os.environ.get("SIFAS_TEST_MV_EFFECT"),
                     "Set private local live_timeline and stage_effect bundle paths for the real export check")
class AxisBillboardBundleTests(unittest.TestCase):
    def test_each_listed_billboard_with_a_mesh_is_a_tagged_live_node(self):
        from webtools.core import mv_studio_timeline

        timeline = Path(os.environ["SIFAS_TEST_MV_TIMELINE"])
        parsed = mv_studio_timeline.parse_timeline(timeline.read_bytes(), timeline.name, preview_stage_motion=True)
        bindings = tuple(parsed["stageMotion"]["bindings"])
        prepared = viewer.prepare([os.environ["SIFAS_TEST_MV_EFFECT"]], face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_stage_motion_bindings": bindings,
            "_mv_native_stage_effect": True})
        payload = viewer.get_model(prepared["id"])
        size = struct.unpack_from("<I", payload, 12)[0]
        doc = json.loads(payload[20:20 + size])
        tagged = [node for node in doc["nodes"] if node.get("extras", {}).get("mvAxisBillboard") == 1]
        self.assertTrue(tagged)
        roots = set(doc["scenes"][0]["nodes"])
        for node in tagged:
            self.assertIn("mvStageNode", node["extras"])
            self.assertNotIn(doc["nodes"].index(node), roots)
            self.assertTrue(any("mesh" in doc["nodes"][child] for child in node.get("children", [])))
        expected = os.environ.get("SIFAS_TEST_MV_AXIS_BILLBOARDS")
        if expected:
            self.assertEqual(len(tagged), int(expected))


if __name__ == "__main__":
    unittest.main()
