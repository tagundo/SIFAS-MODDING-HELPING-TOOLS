"""Scaling contracts preserve authored rigs and use absolute saved endpoints."""
import copy
import math
import os
from pathlib import Path
import tempfile
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

        self.make = make

        self.move_go = make(1, "GameObject", {"m_Name": "Move"})
        self.move = make(2, "Transform", {"m_GameObject": {"m_PathID": 1}})
        self.breast_go = make(3, "GameObject", {"m_Name": "BreastSize"})
        self.breast = make(4, "Transform", {"m_GameObject": {"m_PathID": 3}})
        self.head_go = make(6, "GameObject", {"m_Name": "Head"})
        self.head = make(7, "Transform", {"m_GameObject": {"m_PathID": 6}})
        self.hair_go = make(8, "GameObject", {"m_Name": "Neck_Hair"})
        self.hair = make(9, "Transform", {"m_GameObject": {"m_PathID": 8}})
        self.neck_go = make(10, "GameObject", {"m_Name": "Neck"})
        self.neck = make(11, "Transform", {"m_GameObject": {"m_PathID": 10}})
        self.tree = {"targetName": "ch0207_body", "heightScale": .960872829,
                     "scaleValues": [self.record(2, [1, 1, 1], [.963] * 3),
                                     self.record(4, [1, 1, 1], [1.08, 1.04, 1.08])],
                     "positionValues": [], "rotationValues": []}
        self.component = make(5, "MonoBehaviour", self.tree)
        self.glb = SimpleNamespace(doc={"nodes": [
            {"name": "Move__0", "translation": [-1, 2, 3], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1], "children": [1, 4]},
            {"name": "BreastSize__1", "translation": [0, .3, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
            {"name": "Head__2", "translation": [0, .2, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
            {"name": "Neck_Hair__3", "translation": [0, .1, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
            {"name": "Neck__4", "translation": [0, .6, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1], "children": [2, 3]}]})
        self.scene = SimpleNamespace(env=SimpleNamespace(objects=list(self.objects.values())),
                                     transforms={1: self.move, 3: self.breast, 6: self.head, 8: self.hair, 10: self.neck},
                                     tree=lambda obj: obj.tree, name=lambda obj: obj.tree.get("m_Name", ""))
        self.mapping = {(id(self.asset), 2): 0, (id(self.asset), 4): 1,
                        (id(self.asset), 7): 2, (id(self.asset), 9): 3, (id(self.asset), 11): 4}

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
        height, breast = result["controls"][:2]
        self.assertEqual(result["version"], 4)
        self.assertFalse(height["available"])
        self.assertEqual(height["nodes"], [])
        self.assertEqual(breast["nodes"][0]["baseScale"], [1, 1, 1])
        self.assertEqual(height["mode"], "saved_height_metadata_only")
        self.assertEqual(height["unavailableReason"], "unverified_height_formula")

    def test_already_scaled_transform_is_preserved_and_not_squared(self):
        self.glb.doc["nodes"][1]["scale"] = [1.08, 1.04, 1.08]
        result = self.describe()
        entry = result["components"][0]["entries"][1]
        self.assertEqual(entry["state"], "already_applied")
        self.assertEqual(scaling.evaluate_saved_entry(entry), {"scale": [1.08, 1.04, 1.08]})
        self.assertEqual(result["controls"][1]["nodes"][0]["baseScale"], [1.08, 1.04, 1.08])

    def test_height_is_read_only_without_an_invented_axis_or_measurement_mapping(self):
        before = copy.deepcopy((self.glb.doc, self.tree))
        result = self.describe(sources=["costume.unity"])
        control = result["controls"][0]
        self.assertFalse(control["available"])
        self.assertEqual(control["mode"], "saved_height_metadata_only")
        self.assertEqual(control["unavailableReason"], "unverified_height_formula")
        self.assertEqual(control["nodes"], [])
        self.assertFalse(control["gameHeightFormulaVerified"])
        for field in ("axes", "min", "max", "default", "unit", "compensation", "axesMeaning"):
            self.assertNotIn(field, control)
        # Existing saved endpoints and the distinct native header survive.
        component = result["components"][0]
        self.assertEqual(component["heightScale"], .960872829)
        self.assertEqual(component["entries"][0]["scaled"], [.963] * 3)
        self.assertEqual((self.glb.doc, self.tree), before)

    def test_height_does_not_become_editable_from_a_convenient_head_hierarchy(self):
        self.glb.doc["nodes"][4]["children"] = [3]
        self.glb.doc["nodes"][3]["children"] = [2]
        self.neck.source = "another_model.unity"
        control = self.describe()["controls"][0]
        self.assertFalse(control["available"])
        self.assertEqual(control["nodes"], [])
        self.assertEqual(control["unavailableReason"], "unverified_height_formula")

    def test_move_is_a_whole_model_bone_not_a_height_measurement(self):
        result = self.describe()
        move = next(node for node in result["recommendedTargets"] if node["name"] == "Move")
        self.assertEqual((move["label"], move["category"]), ("Whole model", "model"))
        target = next(node for node in result["targets"] if node["name"] == "Move")
        self.assertEqual(target["label"], "Whole model")
        self.assertEqual(target["baseScale"], [1, 1, 1])

    def test_breast_profiles_are_exact_discrete_tool_references_including_emma(self):
        import sifas_breast_tuner as tool
        control = self.describe()["controls"][1]
        self.assertEqual(control["mode"], "breast_tool_presets")
        actual = {preset["label"]: tuple(preset["scale"]) for preset in control["presets"]}
        expected = {name: tuple(xyz) for name, xyz, _ in tool.BREAST_REDUCE_PRESETS + tool.BREAST_ENLARGE_PRESETS}
        expected["Stock"] = (1., 1., 1.)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["Emma"], (1.30, 1.18, 1.30))
        self.assertEqual(actual["Nozomi"], (1.30, 1.15, 1.30))
        self.assertEqual(control["presetApplication"], "absolute_local_scale")
        self.assertEqual(control["profileMeaning"], "reference_shape_not_body_measurement")
        self.assertEqual(control["unit"], "profile")
        self.assertEqual(len(control["presets"]), 16)
        self.assertEqual({preset["label"] for preset in control["presets"] if preset["group"] == "smaller"},
                         {name for name, _, _ in tool.BREAST_REDUCE_PRESETS})

    def test_irregular_reduction_profiles_never_offer_an_invented_continuous_curve(self):
        control = self.describe()["controls"][1]
        self.assertFalse(control["continuousAdjustmentSupported"])
        self.assertEqual(control["interpolation"], "none")
        for field in ("curve", "curveDomain", "curveParameter", "relativeFormula", "min", "max", "axes"):
            self.assertNotIn(field, control)
        self.assertTrue(all("axes" not in node for node in control["nodes"]))

    def test_loaded_custom_breast_shape_is_distinct_from_explicit_stock_profile(self):
        custom = [.77, 1.2345678, .91]
        self.tree["scaleValues"][1] = self.record(4, [1, 1, 1], custom)
        self.glb.doc["nodes"][1]["scale"] = [2., 3., 4.]
        before = copy.deepcopy((self.glb.doc, self.tree))
        result = self.describe()
        control = result["controls"][1]
        self.assertEqual(control["default"], "loaded")
        self.assertEqual(control["baseline"], "loaded_saved_settings")
        self.assertEqual(control["nodes"][0]["baseScale"], [2., 3., 4.])
        self.assertEqual(result["components"][0]["entries"][1]["scaled"], custom)
        stock = next(preset for preset in control["presets"] if preset["id"] == "stock")
        self.assertEqual(stock["scale"], [1., 1., 1.])
        self.assertNotEqual(stock["scale"], custom)
        self.assertEqual((self.glb.doc, self.tree), before)

    def test_absolute_skirt_edit_keeps_named_nested_roots_but_excludes_other_descendants(self):
        self.breast_go.tree["m_Name"] = "LeftSkirtB1_Dyna"
        self.head_go.tree["m_Name"] = "LeftSkirtB2_Dyna"
        self.hair_go.tree["m_Name"] = "RightSkirtB1_Dyna"
        # Absolute local assignment must retain BOTH named roots. The former
        # relative control silently dropped the nested one.
        self.glb.doc["nodes"][4]["children"] = [2]
        self.glb.doc["nodes"][1]["children"] = [3]
        control = self.describe()["controls"][2]
        self.assertTrue(control["available"])
        self.assertEqual([node["name"] for node in control["nodes"]], ["LeftSkirtB1_Dyna", "RightSkirtB1_Dyna"])
        self.assertEqual(len({node["node"] for node in control["nodes"]}), 2)
        self.assertNotIn("LeftSkirtB2_Dyna", [node["name"] for node in control["nodes"]])
        self.assertEqual(control["mode"], "absolute_skirt_root_scale")
        self.assertEqual(control["unit"], "local_scale_factor")
        self.assertEqual(control["application"], "absolute_local_scale")
        self.assertTrue(control["supportsAbsoluteUniform"])
        self.assertEqual(control["uniformTolerance"], 1e-7)
        self.assertEqual(control["editBounds"], {"min": .01, "max": 10., "source": "viewer_preview_bounds",
                                                "appliesTo": "explicit_uniform_edits_only"})
        for key in ("default", "min", "max", "limitsSource", "baseline"):
            self.assertNotIn(key, control)
        self.assertTrue(all("axes" not in target for target in control["nodes"]))
        self.assertEqual(control["axesMeaning"], "length_and_volume")
        from webtools.tools.skirt import DEFAULT_SKIRT_PATTERNS
        self.assertEqual(control["exactRootNames"], DEFAULT_SKIRT_PATTERNS)

    def add_skirt_branch(self, name, serial, saved_scale):
        root_parent = len(self.glb.doc["nodes"])
        names = [name.replace("1_Dyna", "_Root_Dyna"), name, name.replace("1_Dyna", "2_Dyna")]
        transforms = []
        for offset, bone_name in enumerate(names):
            go_id = 100 + serial * 10 + offset * 2
            go = self.make(go_id, "GameObject", {"m_Name": bone_name})
            transform = self.make(go_id + 1, "Transform", {"m_GameObject": {"m_PathID": go_id}})
            node_index = len(self.glb.doc["nodes"])
            node = {"name": bone_name, "scale": [1., 1., 1.]}
            if offset < 2:
                node["children"] = [node_index + 1]
            self.glb.doc["nodes"].append(node)
            self.scene.transforms[go.path_id] = transform
            self.mapping[(id(self.asset), transform.path_id)] = node_index
            transforms.append(transform)
        self.glb.doc["nodes"][0]["children"].append(root_parent)
        self.tree["scaleValues"].append(self.record(transforms[1].path_id, [1., 1., 1.], saved_scale))
        self.scene.env.objects = list(self.objects.values())

    def test_eight_skirt085_records_and_sixteen_other_nodes_survive_without_a_hidden_multiplier(self):
        # Matches the actual uploaded skirt085 source's eight local endpoints.
        # IEEE float32 decoding is deliberately retained as source precision.
        import struct
        value = struct.unpack("<f", struct.pack("<f", .85))[0]
        for serial, name in enumerate(scaling._SKIRT_ROOTS):
            self.add_skirt_branch(name, serial, [value] * 3)
        before = copy.deepcopy((self.glb.doc, self.tree))
        result = self.describe()
        control = result["controls"][2]
        self.assertTrue(control["available"])
        self.assertEqual({node["name"] for node in control["nodes"]}, set(scaling._SKIRT_ROOTS))
        self.assertEqual(len(control["nodes"]), 8)
        self.assertTrue(all(node["sourceName"] == "costume.unity" for node in control["nodes"]))
        entries = [entry for component in result["components"] for entry in component["entries"] if "Skirt" in entry["name"]]
        self.assertEqual(len(entries), 8)
        self.assertTrue(all(entry["scaled"] == [value] * 3 for entry in entries))
        roots = {node["node"] for node in control["nodes"]}
        other_nodes = [node for node in result["nodes"] if "Skirt" in node["name"] and node["node"] not in roots]
        self.assertEqual(len(other_nodes), 16)
        self.assertTrue(all(node["baseScale"] == [1.] * 3 and not node["hasSavedSettings"] for node in other_nodes))
        self.assertEqual((self.glb.doc, self.tree), before)

    def test_asymmetric_skirt_endpoints_and_values_outside_new_edit_bounds_are_preserved(self):
        values = ([.85, .9, .87], [.85, .850001, .85], [.001] * 3, [12.] * 3)
        for serial, (name, scale) in enumerate(zip(scaling._SKIRT_ROOTS, values)):
            self.add_skirt_branch(name, serial, scale)
        before = copy.deepcopy((self.glb.doc, self.tree))
        result = self.describe()
        entries = [entry for component in result["components"] for entry in component["entries"] if "Skirt" in entry["name"]]
        self.assertEqual([entry["scaled"] for entry in entries], [list(value) for value in values])
        self.assertTrue(all(entry["supported"] for entry in entries))
        self.assertNotIn("default", result["controls"][2])
        self.assertEqual((self.glb.doc, self.tree), before)

    def test_ambiguous_same_source_skirt_names_disable_simple_edit_without_losing_raw_nodes(self):
        for serial in range(2):
            self.add_skirt_branch("SkirtA1_Dyna", serial, [.8 + .1 * serial] * 3)
        result = self.describe()
        control = result["controls"][2]
        self.assertFalse(control["available"])
        self.assertFalse(control["supportsAbsoluteUniform"])
        self.assertEqual(control["unavailableReason"], "ambiguous_skirt_roots")
        self.assertEqual(len(control["nodes"]), 2)
        self.assertEqual(len({node["node"] for node in control["nodes"]}), 2)
        raw = [node for node in result["nodes"] if node["name"] == "SkirtA1_Dyna"]
        self.assertEqual(len(raw), 2)
        self.assertTrue(all(node["hasSavedSettings"] for node in raw))

    def test_authored_node_catalogue_and_frequent_targets_are_source_bound(self):
        self.hair.source = "another_model.unity"
        result = self.describe(sources=["costume.unity"])
        by_node = {node["node"]: node for node in result["nodes"]}
        self.assertEqual(set(by_node), {0, 1, 2, 4})
        self.assertEqual(by_node[2]["parent"], 4)
        self.assertEqual(by_node[2]["basePosition"], [0, .2, 0])
        self.assertFalse(by_node[2]["hasSavedSettings"])
        self.assertTrue(by_node[1]["hasSavedSettings"])
        self.assertEqual(by_node[1]["savedKinds"], ["scale"])
        self.assertEqual(by_node[1]["savedEntries"], ["0:1"])
        self.assertNotIn("Neck_Hair", {node["name"] for node in result["recommendedTargets"]})

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

    def test_verified_rotation_is_absolute_and_preserves_source_euler(self):
        self.tree["rotationValues"] = [self.record(4, [0, 0, 0], [0, 45, 0])]
        before = copy.deepcopy((self.tree, self.glb.doc))
        entry = self.describe()["components"][0]["entries"][-1]
        self.assertTrue(entry["supported"])
        self.assertEqual(entry["application"], "absolute_local_quaternion")
        self.assertEqual(entry["state"], "pending")
        self.assertEqual(entry["unityEulerOrigin"], [0, 0, 0])
        self.assertEqual(entry["unityEulerScaled"], [0, 45, 0])
        self.assertEqual(scaling.evaluate_saved_entry(entry), {"rotation": entry["scaledQuaternion"]})
        self.assertEqual((self.tree, self.glb.doc), before)
        self.glb.doc["nodes"][1]["rotation"] = [-x for x in entry["scaledQuaternion"]]
        self.assertEqual(self.describe()["components"][0]["entries"][-1]["state"], "already_applied")

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
        for weight in (float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                scaling.evaluate_saved_entry({"supported": True, "kind": "scale", "origin": [1] * 3, "scaled": [2] * 3}, weight)

    def test_native_lerp_clamps_weight_and_rejects_zero_crossing(self):
        entry = {"supported": True, "kind": "scale", "origin": [1] * 3, "scaled": [2] * 3}
        self.assertEqual(scaling.evaluate_saved_entry(entry, -5), {"scale": [1.] * 3})
        self.assertEqual(scaling.evaluate_saved_entry(entry, 5), {"scale": [2.] * 3})
        entry["scaled"] = [-1, 2, 2]
        with self.assertRaisesRegex(ValueError, "collapse"):
            scaling.evaluate_saved_entry(entry, .5)
        self.tree["scaleValues"][0]["originValue"]["x"] = 0
        entry = self.describe()["components"][0]["entries"][0]
        self.assertFalse(entry["supported"])
        self.assertEqual(entry["reason"], "zero_scale")

    def test_all_saved_targets_are_catalogued_without_height_breast_whitelist(self):
        self.breast_go.tree["m_Name"] = "LeftSkirtB1_Dyna"
        self.tree["positionValues"] = [self.record(4, [0, .3, 0], [0, .2, .1])]
        self.tree["rotationValues"] = [self.record(4, [0, 0, 0], [30, 45, 60])]
        result = self.describe()
        skirt = next(target for target in result["targets"] if target["node"] == 1)
        self.assertEqual(skirt["kinds"], ["scale", "position", "rotation"])
        self.assertEqual(skirt["name"], "LeftSkirtB1_Dyna")
        self.assertEqual(skirt["label"], "Left Skirt B1")
        self.assertEqual(skirt["category"], "skirt")
        self.assertEqual(len(skirt["entries"]), 3)
        self.assertTrue(all(entry["supported"] for entry in result["components"][0]["entries"]))
        self.assertFalse(result["controls"][1]["available"])

    def test_conflicting_duplicate_absolute_targets_are_disabled_together(self):
        self.tree["scaleValues"].append(self.record(4, [1] * 3, [1.0801, 1.04, 1.08]))
        result = self.describe()
        breast = [entry for entry in result["components"][0]["entries"] if entry["node"] == 1]
        self.assertFalse(any(entry["supported"] for entry in breast))
        self.assertTrue(all(entry["reason"] == "conflicting_saved_entries" for entry in breast))
        self.assertIn("scaling_conflicting_entries", result["warnings"])
        self.tree["scaleValues"][-1] = copy.deepcopy(self.tree["scaleValues"][1])
        self.assertTrue(all(entry["supported"] for entry in self.describe()["components"][0]["entries"]))

    def test_euler_wrapped_duplicate_paths_are_conflicts_despite_equal_end_quats(self):
        self.tree["rotationValues"] = [self.record(4, [0, 0, 0], [0, 0, 10]),
                                        self.record(4, [0, 0, 360], [0, 0, 10])]
        entries = self.describe()["components"][0]["entries"][-2:]
        self.assertFalse(any(entry["supported"] for entry in entries))

    def test_rotation_only_component_is_recognized_and_invalid_euler_fails_closed(self):
        del self.tree["scaleValues"], self.tree["positionValues"]
        self.tree["rotationValues"] = [self.record(4, [0] * 3, [30, 45, 60])]
        self.assertTrue(self.describe()["components"][0]["entries"][0]["supported"])
        self.tree["rotationValues"][0]["scaledValue"]["x"] = float("nan")
        result = self.describe()
        self.assertEqual(result["components"][0]["entries"], [])
        self.assertIn("scaling_invalid_entry", result["warnings"])

    def test_parent_and_skirt_saved_trs_stay_absolute_across_repeated_updates(self):
        import numpy as np
        self.breast_go.tree["m_Name"] = "LeftSkirtB1_Dyna"
        self.tree["scaleValues"][1] = self.record(4, [1,1,1], [.7,.7,.7])
        self.tree["positionValues"] = [self.record(4, [0,.3,0], [0,.6,0])]
        self.tree["rotationValues"] = [self.record(4, [0,0,0], [30,45,60])]
        entries = self.describe()["components"][0]["entries"]
        nodes = copy.deepcopy(self.glb.doc["nodes"])

        def apply():
            for entry in entries:
                nodes[entry["node"]].update(scaling.evaluate_saved_entry(entry))

        def matrix(node):
            return viewer._trs({"m_LocalPosition": dict(zip("xyz",node["translation"])),
                                "m_LocalRotation": dict(zip("xyzw",node["rotation"])),
                                "m_LocalScale": dict(zip("xyz",node["scale"]))})

        apply()
        # Child local settings compose under parent scaling exactly once, then
        # propagate to any unchanged grandchild's local offset.
        grandchild = np.array([0.,.5,0.,1.])
        expected = matrix(nodes[0]) @ matrix(nodes[1]) @ grandchild
        self.assertAlmostEqual(nodes[1]["scale"][1], .7)
        self.assertAlmostEqual(nodes[1]["translation"][1], .6)
        for _ in range(10):
            apply()
            np.testing.assert_array_equal(matrix(nodes[0]) @ matrix(nodes[1]) @ grandchild, expected)
        # Native ApplyScale(0) restores serialized origin endpoints, rather
        # than dividing the current parent/child values by their saved ratios.
        for entry in entries:
            nodes[entry["node"]].update(scaling.evaluate_saved_entry(entry, 0))
        self.assertEqual(nodes[0]["scale"], [1,1,1])
        self.assertEqual(nodes[1]["scale"], [1,1,1])
        self.assertEqual(nodes[1]["translation"], [0,.3,0])


class EulerMathTests(unittest.TestCase):
    @staticmethod
    def matrix(quaternion):
        import numpy as np
        x, y, z, w = quaternion
        return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

    def test_compound_euler_matches_independent_unity_matrix_and_mirror(self):
        import numpy as np
        for values in ([30, 45, 60], [-120, 89, 205], [90, 0, 90], [350, -720, 10]):
            x, y, z = [math.radians(value) for value in values]
            rx = np.array([[1,0,0],[0,math.cos(x),-math.sin(x)],[0,math.sin(x),math.cos(x)]])
            ry = np.array([[math.cos(y),0,math.sin(y)],[0,1,0],[-math.sin(y),0,math.cos(y)]])
            rz = np.array([[math.cos(z),-math.sin(z),0],[math.sin(z),math.cos(z),0],[0,0,1]])
            mirror = np.diag([-1, 1, 1])
            expected = mirror @ ry @ rx @ rz @ mirror
            actual = scaling.unity_euler_to_gltf(values)
            np.testing.assert_allclose(self.matrix(actual), expected, atol=1e-12)
            unity = [actual[0], -actual[1], -actual[2], actual[3]]
            np.testing.assert_allclose(self.matrix(unity), ry @ rx @ rz, atol=1e-12)
        np.testing.assert_allclose(scaling.unity_euler_to_gltf([30,45,60]),
            [.3919038373291199,-.20056212114657512,-.3604234056503559,.8223631719059994], atol=1e-12)

    def test_halfway_lerps_source_euler_instead_of_quaternion_slerp(self):
        import numpy as np
        entry = {"kind": "rotation", "supported": True, "interpolation": "unity_euler_lerp", "rotationOrder": "ZXY",
                 "unityEulerOrigin": [0,0,0], "unityEulerScaled": [60,90,120]}
        result = scaling.evaluate_saved_entry(entry, .5)["rotation"]
        np.testing.assert_allclose(result, scaling.unity_euler_to_gltf([30,45,60]), atol=1e-12)
        end = np.array(scaling.unity_euler_to_gltf([60,90,120]))
        if end[3] < 0:
            end *= -1
        halfway_slerp = end + [0,0,0,1]
        halfway_slerp /= np.linalg.norm(halfway_slerp)
        self.assertGreater(np.max(abs(self.matrix(result) - self.matrix(halfway_slerp))), .25)
        entry.update(unityEulerOrigin=[0,0,350], unityEulerScaled=[0,0,10])
        np.testing.assert_allclose(self.matrix(scaling.evaluate_saved_entry(entry,.5)["rotation"]),
                                   np.diag([-1,-1,1]), atol=1e-12)


class ActualSavedNodeTests(unittest.TestCase):
    def test_clothed_skirt_saved_values_propagate_without_compounding(self):
        path = os.environ.get("SIFAS_FACE_TEST_COSTUME")
        if not path:
            self.skipTest("Set actual clothed costume for saved skirt propagation")
        import hashlib
        import numpy as np
        from tests.test_model_rig import unpack, evaluate, node_worlds
        original = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as cache:
            metadata = viewer.prepare([path], rigged=True, face_context={"enabled": False, "cache_dir": cache})
        document, binary = unpack(metadata)
        entries = [entry for component in metadata["rig"]["scaling"]["components"] for entry in component["entries"]]
        self.assertEqual(len(entries), 11)
        skirt = [entry for entry in entries if "Skirt" in entry["name"]]
        self.assertEqual(len(skirt), 8)
        self.assertTrue(all(entry["supported"] for entry in entries))
        overrides = {entry["node"]: scaling.evaluate_saved_entry(entry) for entry in skirt}
        before, after = evaluate(document,binary), evaluate(document,binary,overrides)
        body_name = max(before, key=lambda name: len(before[name]))
        self.assertGreater(np.max(abs(before[body_name] - after[body_name])), .001)
        worlds, changed = node_worlds(document), node_worlds(document,overrides)
        source = skirt[0]["node"]
        descendant = document["nodes"][source]["children"][0]
        self.assertGreater(np.max(abs(worlds[descendant] - changed[descendant])), .001)
        for _ in range(5):
            for entry in skirt:
                overrides[entry["node"]].update(scaling.evaluate_saved_entry(entry))
        repeated = evaluate(document,binary,overrides)
        for name in after:
            np.testing.assert_allclose(repeated[name], after[name], atol=0)
        self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), original)


if __name__ == "__main__":
    unittest.main()
