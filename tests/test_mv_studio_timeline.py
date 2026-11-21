"""Native MV descriptors and copy-only edits; original samples are optional."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json
import os
import unittest

from webtools.core import mv_studio_timeline as studio

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))


class TimelineContractTests(unittest.TestCase):
    def test_non_timeline_input_has_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "UnityFS live timeline"):
            studio.parse_timeline(b"not a bundle", "invalid.unity")

    def test_unmodified_native_output_is_the_same_blob(self):
        raw = b"preserve source file bytes"
        original = {"duration": 0, "tracks": [], "warnings": []}
        self.assertIs(studio.edit_timeline(raw, original, deepcopy(original)), raw)

    def test_fov_uses_the_camera_monoscript_property_binding(self):
        rows = [
            {"path": 0, "typeID": 4, "attribute": 4},
            {"path": 0, "typeID": 114, "attribute": 2282594708},
            {"path": 0, "typeID": 4, "attribute": 1},
        ]
        clip = {"m_ClipBindingConstant": {"genericBindings": rows}}
        self.assertEqual(studio._camera_sample_order(clip), ["euler", "fov", "position"])
        for wrong in ({"path": 1}, {"typeID": 20}, {"attribute": 17}, {"isPPtrCurve": True}):
            with self.subTest(wrong=wrong):
                amended = deepcopy(clip)
                amended["m_ClipBindingConstant"]["genericBindings"][1].update(wrong)
                with self.assertRaisesRegex(ValueError, "camera bindings"):
                    studio._camera_sample_order(amended)


@unittest.skipUnless((SAMPLES / "a-1205603-live_timeline.unity").is_file() and
                     (SAMPLES / "i-1205603-live_timeline.unity").is_file(), "Original game samples are optional")
class ActualTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = {platform: (SAMPLES / f"{platform}-1205603-live_timeline.unity").read_bytes()
                   for platform in ("a", "i")}
        cls.original = {platform: studio.parse_timeline(raw, platform) for platform, raw in cls.raw.items()}

    def camera(self, data):
        return next(track for track in data["tracks"] if track["label"] == "CameraMotion/Camera1")

    def test_native_special_stage_tracks_and_camera_samples_agree_on_android_and_ios(self):
        before = self.original["a"]
        self.assertEqual(before, self.original["i"])
        self.assertEqual(len(before["tracks"]), 105)
        self.assertEqual(sum(len(track["events"]) for track in before["tracks"]), 2064)
        self.assertAlmostEqual(before["duration"], 118.6166667)
        self.assertTrue({"camera", "dance", "lighting", "bloom", "dof", "effects", "crowd",
                         "display", "split", "mouth", "eyes", "gaze", "cheek"} <=
                        {track["kind"] for track in before["tracks"]})
        camera = self.camera(before)
        self.assertEqual(camera["binding"], "/EntryPoint/Live/Cameras/MainCamera")
        self.assertEqual(len(camera["events"]), 78)
        first = camera["events"][0]
        self.assertAlmostEqual(first["duration"], 241 / 60)
        points = first["values"]["keyframes"]
        self.assertEqual(len(points), 242)
        self.assertAlmostEqual(points[0]["fov"], 41.112091, places=5)
        self.assertAlmostEqual(points[-1]["time"], first["duration"])
        self.assertTrue(all(a["time"] < b["time"] for a, b in zip(points, points[1:])))
        self.assertIn("exact companion asset packs", " ".join(before["warnings"]))
        json.dumps(before, allow_nan=False)

    def test_native_existing_point_and_bloom_edit_reopen_with_original_platform(self):
        import UnityPy

        for platform, target in (("a", 13), ("i", 9)):
            with self.subTest(platform=platform):
                old = self.original[platform]
                revision = deepcopy(old)
                event = self.camera(revision)["events"][0]
                event["label"] = "Edited cut"
                point = event["values"]["keyframes"][12]
                point["fov"] += 1.5
                point["position"][0] += .25
                bloom = next(track for track in revision["tracks"] if track["kind"] == "bloom")["events"][0]
                bloom["start"] += .01
                bloom["values"]["intensity"] = .45
                changed = studio.edit_timeline(self.raw[platform], old, revision)
                with patch.object(studio, "parse_timeline", wraps=studio.parse_timeline) as parse:
                    self.assertEqual(studio.export_timeline(self.raw[platform], platform, revision["tracks"]), changed)
                    self.assertEqual(parse.call_count, 1)
                self.assertIs(studio.export_timeline(self.raw[platform], platform, old["tracks"]), self.raw[platform])
                current = studio.parse_timeline(changed, platform)
                self.assertEqual({int(asset.target_platform) for asset in UnityPy.load(changed).assets}, {target})
                actual = self.camera(current)["events"][0]
                self.assertEqual(actual["label"], "Edited cut")
                self.assertAlmostEqual(actual["values"]["keyframes"][12]["fov"], point["fov"], places=4)
                self.assertAlmostEqual(actual["values"]["keyframes"][12]["position"][0], point["position"][0], places=4)
                actual_bloom = next(track for track in current["tracks"] if track["kind"] == "bloom")["events"][0]
                self.assertAlmostEqual(actual_bloom["values"]["intensity"], .45, places=6)
                self.assertAlmostEqual(actual_bloom["start"], bloom["start"])
                self.assertEqual(self.camera(current)["events"][1:], self.camera(old)["events"][1:])

    def test_native_copy_refuses_replacement_refs_and_stale_baseline(self):
        original = self.original["a"]
        revision = deepcopy(original)
        self.camera(revision)["events"][0]["values"]["animation"] = "cab:1"
        with self.assertRaisesRegex(ValueError, "read-only"):
            studio.edit_timeline(self.raw["a"], original, revision)
        baseline = deepcopy(original)
        self.camera(baseline)["events"][0]["label"] = "Stale source"
        with self.assertRaisesRegex(ValueError, "changed after opening"):
            studio.edit_timeline(self.raw["a"], baseline, revision)

    def test_shared_playable_allows_timing_only_and_keeps_other_clip(self):
        import UnityPy

        def bloom(data):
            return next(track for track in data["tracks"] if track["kind"] == "bloom")

        track_id = int(bloom(self.original["a"])["id"].rsplit(":", 1)[1])
        environment = UnityPy.load(self.raw["a"])
        component = next(obj for obj in environment.objects if obj.path_id == track_id)
        tree = component.read_typetree()
        tree["m_Clips"][1]["m_Asset"] = tree["m_Clips"][0]["m_Asset"]
        component.save_typetree(tree)
        shared = environment.file.save(packer="lz4")
        original = studio.parse_timeline(shared, "shared")
        revision = deepcopy(original)
        first = bloom(revision)["events"][0]
        first["values"]["intensity"] = .51
        with self.assertRaisesRegex(ValueError, "shared or external"):
            studio.edit_timeline(shared, original, revision)
        first["values"]["intensity"] = bloom(original)["events"][0]["values"]["intensity"]
        first["start"] += .01
        changed = studio.edit_timeline(shared, original, revision)
        current = studio.parse_timeline(changed, "changed")
        self.assertAlmostEqual(bloom(current)["events"][0]["start"], first["start"])
        self.assertEqual(bloom(current)["events"][1], bloom(original)["events"][1])
