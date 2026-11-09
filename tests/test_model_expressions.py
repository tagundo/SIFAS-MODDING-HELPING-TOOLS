"""Source-named expressions are usable without inventing numeric semantics."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from webtools.core import model_expressions as expressions


FACE_HASH = "97e79b210e61c6d4b1f8cbee68d903e8c6e4fb6e070bb84a9d2b6fd37fad2bd4"


def rig():
    definitions = [("Head_Face", None, "Head_Face"),
                   ("LeftEye1", 0, "Head_Face/Face_Root/Eye_Root/LeftEye_Root/LeftEye1"),
                   ("LeftEye2", 1, "Head_Face/Face_Root/Eye_Root/LeftEye_Root/LeftEye1/LeftEye2"),
                   ("RightEye1", 0, "Head_Face/Face_Root/Eye_Root/RightEye_Root/RightEye1"),
                   ("RightEye2", 3, "Head_Face/Face_Root/Eye_Root/RightEye_Root/RightEye1/RightEye2")]
    bones = [{"node": node, "name": name, "parent": parent, "path": path}
             for node, (name, parent, path) in enumerate(definitions)]
    parts = ["Head_Face", "LeftEye1", "LeftEye2", "RightEye1", "RightEye2", "Eye_Around",
             "Mouth", "LeftEyeWhiteLine", "RightEyeWhiteLine", "Eye"]
    doc = {"nodes": [{"name": name, "extras": {"originalName": name}} for name in parts]}
    names = {
        5: ["EyeBlendShape.eye_facial_" + value for value in
            ("001", "002", "003_006_011", "004", "005", "012", "013", "014", "015", "016", "017", "018", "019", "099")],
        6: ["MouthBlendShape.mouth_facial_%03d" % index for index in list(range(1, 13)) + [99]],
        7: ["LeftEyeWhiteLineBlendShape.LeftEye_LineWhite_%03d" % index for index in range(1, 4)],
        8: ["RightEyeWhiteLineBlendShape.RightEye_LineWhite_%03d" % index for index in range(1, 4)],
    }
    morphs = [{"node": node, "names": values, "weights": [0.] * len(values)} for node, values in names.items()]
    sources = {node: {"part": parts[node], "sourceHash": FACE_HASH} for node in names}
    sources[9] = {"part": "Eye", "sourceHash": FACE_HASH}
    return morphs, bones, doc, sources


class ExpressionCatalogTests(unittest.TestCase):
    def setUp(self):
        self.morphs, self.bones, self.doc, self.sources = rig()

    def catalog(self, **extra):
        options = dict(owner=207, sources=self.sources)
        options.update(extra)
        return expressions.describe_expressions(self.morphs, self.bones, self.doc, **options)

    def test_canonical_labels_preserve_every_original_node_index_name_and_default(self):
        self.morphs[0]["weights"][0] = .35
        original = copy.deepcopy((self.morphs, self.bones, self.doc, self.sources))
        result = self.catalog()
        self.assertEqual(len(result["rawChannels"]), 33)
        self.assertEqual(len(result["controls"]), 24)
        self.assertEqual([(value["node"], value["index"], value["name"], value["defaultValue"])
                          for value in result["rawChannels"]],
                         [(record["node"], index, name, record["weights"][index])
                          for record in self.morphs for index, name in enumerate(record["names"])])
        self.assertEqual((self.morphs, self.bones, self.doc, self.sources), original)
        self.assertEqual(next(value for value in result["controls"] if value["id"] == "mouth-smile")["label"], "Smiling mouth")

    def test_gaze_uses_the_displayed_characters_verified_pose_bank(self):
        clips = [{"name": "own-up", "sourceName": "ch0207_LiveFacial_eye_008", "sourceHash": "own", "bindingComplete": True},
                 {"name": "shared-up", "sourceName": "ch0001_LiveFacial_eye_008", "sourceHash": "shared", "bindingComplete": True},
                 {"name": "unbound-left", "sourceName": "ch0207_LiveFacial_eye_007", "sourceHash": "own", "bindingComplete": False},
                 {"name": "blink", "sourceName": "ch0207_LiveFacial_eye_900", "bindingComplete": True}]
        result = self.catalog(clips=clips)
        self.assertTrue(result["gaze"]["available"])
        self.assertEqual(result["gaze"]["clips"], [{"name": "own-up", "index": 8, "kind": "eyes",
                                                   "sourceName": "ch0207_LiveFacial_eye_008", "sourceHash": "own"}])
        self.assertEqual((result["gaze"]["horizontalLimit"], result["gaze"]["verticalLimit"]), (45, 30))
        self.assertNotIn(0, result["gaze"]["nodes"])

    def test_gaze_does_not_require_morph_channels_and_never_invents_missing_eye_poses(self):
        clips = [{"name": "up", "sourceName": "ch0207_LiveFacial_eye_008", "sourceHash": "own", "bindingComplete": True}]
        result = expressions.describe_expressions([], self.bones, self.doc, owner=207, clips=clips)
        self.assertTrue(result["available"])
        self.assertTrue(result["gaze"]["available"])
        self.assertFalse(expressions.describe_expressions([], self.bones, self.doc)["gaze"]["available"])

    def test_shared_eyelid_shape_is_open_eyelids_not_a_fake_gaze_control(self):
        result = self.catalog()
        control = next(value for value in result["controls"] if value["id"] == "eyes-open")
        self.assertEqual(control["semanticId"], 3)
        self.assertEqual(control["label"], "Open eyelids")
        self.assertFalse(control["complete"])
        self.assertEqual(control["targets"][0]["name"], "EyeBlendShape.eye_facial_003_006_011")
        self.assertIn("gaze", control["note"])
        self.assertFalse(any("rightward" in value["id"] or "leftward" in value["id"] for value in result["controls"]))

    def test_099_auxiliary_and_arbitrary_numbers_remain_advanced_raw_channels(self):
        self.morphs[1]["names"].append("123")
        self.morphs[1]["weights"].append(.2)
        result = self.catalog()
        unknown = [value for value in result["rawChannels"] if value["name"].endswith("099") or value["name"] == "123"]
        self.assertEqual(len(unknown), 3)
        self.assertTrue(all(not value["known"] and value["advanced"] for value in unknown))
        self.assertFalse(any(value["name"].endswith("099") for control in result["controls"] for value in control["targets"]))
        self.assertEqual(sum(value["advanced"] for value in result["rawChannels"] if "LineWhite" in value["name"]), 6)

    def test_closed_eyelids_group_the_original_left_right_auxiliary_morphs(self):
        control = next(value for value in self.catalog()["controls"] if value["id"] == "eyes-closed")
        self.assertEqual({(value["node"], value["index"]) for value in control["targets"]}, {(5, 0), (7, 0), (8, 0)})
        self.assertEqual(len(control["resetTargets"]), 20)
        self.assertEqual((control["min"], control["max"], control["step"]), (0, 1, .01))

    def test_split_renderers_share_one_control_but_ambiguous_same_mesh_shapes_do_not(self):
        self.doc["nodes"].append({"name": "Mouth_part2"})
        self.morphs.append({"node": 10, "names": ["MouthBlendShape.mouth_facial_007"], "weights": [0]})
        result = self.catalog()
        control = next(value for value in result["controls"] if value["id"] == "mouth-smile")
        self.assertEqual({value["node"] for value in control["targets"]}, {6, 10})
        self.morphs[1]["names"].append("MouthBlendShape.mouth_facial_007")
        self.morphs[1]["weights"].append(0)
        self.assertFalse(any(value["id"] == "mouth-smile" for value in self.catalog()["controls"]))

    def test_complete_eye_pose_uses_exact_original_face_and_all_coupled_operations(self):
        result = self.catalog()
        preset = next(value for value in result["presets"] if value["id"] == "eyes-smile")
        self.assertTrue(preset["complete"])
        self.assertEqual(preset["source"], "verified_game_clip")
        self.assertEqual(preset["faceSourceHash"], FACE_HASH)
        self.assertEqual({value["node"] for value in preset["bones"]}, {1, 2, 3, 4})
        self.assertEqual(preset["resetBones"], [1, 2, 3, 4])
        self.assertEqual(preset["visibility"], [{"node": 7, "visible": True}, {"node": 8, "visible": True}])
        moved = next(value for value in preset["bones"] if value["node"] == 4 and value["kind"] == "position")
        self.assertAlmostEqual(moved["value"][2], -.00115, places=8)
        self.assertFalse(any(value["node"] == 0 for value in preset["bones"]))
        self.assertEqual(len(preset["targets"]), 20)
        self.assertEqual(sum(value["value"] == 1 for value in preset["targets"]), 3)

    def test_other_owner_or_face_hash_never_receives_207_bone_recipes(self):
        for owner in (1, 101, 209, None, True, 207.0):
            with self.subTest(owner=owner):
                self.assertFalse(any(value["source"] == "verified_game_clip" for value in self.catalog(owner=owner)["presets"]))
        self.sources[5]["sourceHash"] = "0" * 64
        self.assertFalse(any(value["source"] == "verified_game_clip" for value in self.catalog()["presets"]))
        self.assertEqual(len(self.catalog()["rawChannels"]), 33)

    def test_custom_non_morph_iris_never_receives_original_eye_bone_recipe(self):
        self.sources[9]["sourceHash"] = "0" * 64
        result = self.catalog()
        self.assertFalse(any(value["source"] == "verified_game_clip" for value in result["presets"]))
        self.assertEqual(len(result["controls"]), 24)
        self.assertEqual(len(result["rawChannels"]), 33)

    def test_ambiguous_or_unrelated_bones_fail_closed_without_losing_raw_morphs(self):
        for mode in ("duplicate_head", "wrong_parent", "wrong_path"):
            with self.subTest(mode=mode):
                morphs, bones, doc, sources = rig()
                if mode == "duplicate_head":
                    bones.append({"node": 9, "name": "Head_Face", "parent": None, "path": "Head_Face"})
                    doc["nodes"].append({"name": "Head_Face"})
                elif mode == "wrong_parent":
                    bones[1]["parent"] = 9
                else:
                    bones[1]["path"] = "Other/LeftEye1"
                result = expressions.describe_expressions(morphs, bones, doc, owner=207, sources=sources)
                self.assertFalse(any(value["source"] == "verified_game_clip" for value in result["presets"]))
                self.assertEqual(len(result["rawChannels"]), 33)

    def test_missing_optional_recipe_keeps_named_shapes_and_original_channels(self):
        with patch.object(expressions, "_recipes", return_value=()):
            result = self.catalog()
        self.assertEqual(len(result["controls"]), 24)
        self.assertEqual(len(result["rawChannels"]), 33)
        self.assertTrue(all(value["scope"] == "mouth_shape" for value in result["presets"]))

    def test_invalid_optional_eye_rotation_never_produces_a_bone_recipe(self):
        records = copy.deepcopy(expressions._recipes())
        first = next(value for value in records if value["id"] == "eyes-closed")
        rotation = next(value for value in first["bones"] if value["kind"] == "quaternion")
        rotation["value"] = [0, 0, 0, 0]
        with patch.object(expressions, "_recipes", return_value=records):
            result = self.catalog()
        self.assertFalse(any(value["id"] == "eyes-closed" for value in result["presets"]))
        self.assertEqual(len(result["controls"]), 24)
        self.assertEqual(len(result["rawChannels"]), 33)

    def test_viewer_face_combinations_are_explicit_not_claimed_original_whole_face_clips(self):
        preset = next(value for value in self.catalog()["presets"] if value["id"] == "smile")
        self.assertEqual(preset["source"], "viewer_combination")
        self.assertFalse(preset["complete"])
        self.assertEqual(preset["components"], ["eyes-smile", "mouth-smile"])
        self.assertEqual(len(preset["targets"]), 33)
        self.assertEqual(sum(value["value"] == 1 for value in preset["targets"]), 4)

    def test_loaded_original_eye_clips_get_names_without_promoting_partial_or_gaze_controls(self):
        clips = [{"name": "ch0207_LiveFacial_eye_012", "bindingComplete": True},
                 {"name": "ch0207_LiveFacial_eye_006", "bindingComplete": True},
                 {"name": "ch0207_LiveFacial_eye_900", "bindingComplete": False},
                 {"name": "ch0207_LiveFacial_eye_099", "bindingComplete": True},
                 {"name": "unrelated_001", "bindingComplete": True}]
        labels = self.catalog(clips=clips)["clips"]
        self.assertEqual([value["label"] for value in labels], ["Right wink", "Look right", "Blink"])
        self.assertFalse(labels[0]["advanced"])
        self.assertTrue(labels[1]["advanced"])
        self.assertFalse(labels[2]["complete"])

    def test_unknown_models_remain_raw_and_optional_catalog_is_bounded(self):
        self.morphs = [{"node": 5, "names": [str(index) for index in range(600)], "weights": [0] * 600}]
        result = self.catalog()
        self.assertEqual(len(result["rawChannels"]), expressions.MAX_CHANNELS)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["rawChannelCount"], 600)
        self.assertEqual(result["controls"], [])
        self.assertEqual(result["presets"], [])

    def test_truncated_original_face_never_emits_incomplete_eye_or_full_face_recipe(self):
        # The original eyelids are early in the catalog, but the coupled white
        # lines lie beyond its bound. An "Eyes open" recipe must not claim to
        # reset those still-active .4 weights when it cannot reference them.
        original_eyes, original_mouth, left_line, right_line = self.morphs
        left_line["weights"] = [.4, 0, 0]
        right_line["weights"] = [.4, 0, 0]
        extras = []
        for ordinal in range(8):
            node = len(self.doc["nodes"])
            self.doc["nodes"].append({"name": "Custom_%d" % ordinal})
            extras.append({"node": node, "names": ["custom_%d_%d" % (ordinal, index) for index in range(64)],
                           "weights": [0.] * 64})
        self.morphs = [original_eyes, original_mouth] + extras + [left_line, right_line]
        before = copy.deepcopy(self.morphs)
        result = self.catalog()
        self.assertEqual(result["rawChannelCount"], 545)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["rawChannels"]), expressions.MAX_CHANNELS)
        self.assertTrue(any(value["id"] == "eyes-open" for value in result["controls"]))
        self.assertTrue(any(value["scope"] == "mouth_shape" for value in result["presets"]))
        self.assertFalse(any(value["complete"] for value in result["presets"]))
        self.assertFalse(any(value["source"] in ("verified_game_clip", "viewer_combination")
                             for value in result["presets"]))
        self.assertEqual(self.morphs, before)


if __name__ == "__main__":
    unittest.main()
