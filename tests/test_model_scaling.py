"""Scaling contracts preserve authored rigs and use absolute saved endpoints."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_scaling as scaling
from webtools.core import model_viewer as viewer


class ScalingTests(unittest.TestCase):
    def setUp(self):
        self.asset = object()
        self.objects = {}

        def make(index, typ, tree, source="costume.unity"):
            obj = SimpleNamespace(path_id=index, assets_file=self.asset, type=SimpleNamespace(name=typ),
                                  tree=tree, source=source)
            self.objects[index] = obj
            return obj

        self.move_go = make(1, "GameObject", {"m_Name": "Move"})
        self.move = make(2, "Transform", {"m_GameObject": {"m_PathID": 1}})
        self.breast_go = make(3, "GameObject", {"m_Name": "BreastSize"})
        self.breast = make(4, "Transform", {"m_GameObject": {"m_PathID": 3}})
        self.tree = {"targetName": "ch0207_body", "heightScale": .960872829,
                     "scaleValues": [self.record(2, [1, 1, 1], [.963] * 3),
                                     self.record(4, [1, 1, 1], [1.08, 1.04, 1.08])],
                     "positionValues": [], "rotationValues": []}
        self.component = make(5, "MonoBehaviour", self.tree)
        self.glb = SimpleNamespace(doc={"nodes": [
            {"name": "Move__0", "translation": [-1, 2, 3], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
            {"name": "BreastSize__1", "translation": [0, .3, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}]})
        self.scene = SimpleNamespace(env=SimpleNamespace(objects=list(self.objects.values())),
                                     transforms={1: self.move, 3: self.breast},
                                     tree=lambda obj: obj.tree, name=lambda obj: obj.tree.get("m_Name", ""))
        self.mapping = {(id(self.asset), 2): 0, (id(self.asset), 4): 1}

    @staticmethod
    def record(target, origin, scaled):
        def vector(value):
            return dict(zip("xyz", value))
        return {"target": {"m_PathID": target}, "originValue": vector(origin), "scaledValue": vector(scaled)}

    def describe(self, **kwargs):
        with patch.object(viewer, "_ref", side_effect=lambda owner, pointer: self.objects.get((pointer or {}).get("m_PathID"))), \
                patch.object(viewer, "_source_path", side_effect=lambda obj: obj.source), \
                patch.object(viewer, "_source_name", side_effect=lambda obj: obj.source):
            return scaling.describe_scaling(self.scene, self.glb, self.mapping, **kwargs)

    def test_authored_default_never_applies_saved_metadata_or_header_height(self):
        before = copy.deepcopy((self.glb.doc, self.tree))
        result = self.describe()
        self.assertEqual((self.glb.doc, self.tree), before)
        self.assertFalse(result["savedOverridesApplied"])
        self.assertEqual(result["baseline"], "authored")
        self.assertFalse(result["gameHeightFormulaVerified"])
        self.assertEqual(result["components"][0]["heightScale"], .960872829)
        self.assertEqual([entry["state"] for entry in result["components"][0]["entries"]], ["pending", "pending"])
        height, breast = result["controls"]
        self.assertEqual(height["nodes"][0]["baseScale"], [1, 1, 1])
        self.assertEqual(breast["nodes"][0]["baseScale"], [1, 1, 1])
        self.assertEqual(height["mode"], "multiply_authored_local_scale")
        self.assertEqual(height["limitsSource"], "viewer_preview_bounds")

    def test_already_scaled_transform_is_preserved_and_not_squared(self):
        self.glb.doc["nodes"][1]["scale"] = [1.08, 1.04, 1.08]
        result = self.describe()
        entry = result["components"][0]["entries"][1]
        self.assertEqual(entry["state"], "already_applied")
        self.assertEqual(scaling.evaluate_saved_entry(entry), {"scale": [1.08, 1.04, 1.08]})
        self.assertEqual(result["controls"][1]["nodes"][0]["baseScale"], [1.08, 1.04, 1.08])

    def test_nonunit_authored_and_mismatched_origins_remain_authored(self):
        self.glb.doc["nodes"][1]["scale"] = [2, 3, 4]
        result = self.describe()
        self.assertEqual(result["controls"][1]["nodes"][0]["baseScale"], [2, 3, 4])
        self.assertEqual(result["components"][0]["entries"][1]["state"], "mismatch")
        self.assertEqual(self.glb.doc["nodes"][1]["scale"], [2, 3, 4])

    def test_positions_are_absolute_and_mirrored_once(self):
        self.tree["positionValues"] = [self.record(2, [1, 2, 3], [2, 3, 4])]
        entry = self.describe()["components"][0]["entries"][-1]
        self.assertEqual(entry["state"], "pending")
        self.assertEqual(entry["origin"], [-1, 2, 3])
        self.assertEqual(scaling.evaluate_saved_entry(entry), {"translation": [-2, 3, 4]})
        self.assertEqual(scaling.evaluate_saved_entry(entry, .5), {"translation": [-1.5, 2.5, 3.5]})

    def test_unknown_rotation_encoding_stays_inspection_only(self):
        self.tree["rotationValues"] = [self.record(4, [0, 0, 0], [0, 45, 0])]
        entry = self.describe()["components"][0]["entries"][-1]
        self.assertFalse(entry["supported"])
        self.assertEqual(entry["reason"], "rotation_encoding_unverified")
        with self.assertRaises(ValueError):
            scaling.evaluate_saved_entry(entry)

    def test_wrapped_records_and_entry_cap(self):
        self.tree["scaleValues"] = [{"data": self.record(4, [1] * 3, [2] * 3)}] * 10
        with patch.object(scaling, "MAX_ENTRIES", 2):
            result = self.describe()
        self.assertEqual(len(result["components"][0]["entries"]), 2)
        self.assertIn("scaling_metadata_limit", result["warnings"])

    def test_cross_source_and_missing_rig_targets_are_not_adjusted(self):
        self.breast.source = "other.unity"
        result = self.describe(sources=["costume.unity"])
        self.assertFalse(result["controls"][1]["available"])
        self.assertEqual(len(result["components"][0]["entries"]), 1)
        self.assertIn("scaling_invalid_entry", result["warnings"])
        self.mapping.clear()
        self.assertFalse(any(control["available"] for control in self.describe()["controls"]))

    def test_invalid_vectors_and_matrix_nodes_fail_closed(self):
        self.tree["scaleValues"][0]["scaledValue"]["x"] = float("nan")
        self.glb.doc["nodes"][1] = {"matrix": [1] * 16}
        result = self.describe()
        self.assertEqual(result["components"][0]["entries"], [])
        self.assertFalse(result["controls"][1]["available"])
        with self.assertRaises(ValueError):
            scaling.evaluate_saved_entry({"supported": True, "kind": "scale", "origin": [1] * 3, "scaled": [0] * 3})
        for weight in (-1, 2, float("inf"), True):
            with self.assertRaises(ValueError):
                scaling.evaluate_saved_entry({"supported": True, "kind": "scale", "origin": [1] * 3, "scaled": [2] * 3}, weight)


if __name__ == "__main__":
    unittest.main()
