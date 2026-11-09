"""Optional original-game regression checks without bundling proprietary assets.

REAL_GAME_MOTION_DIR points at privately downloaded/decrypted original samples.
Normal CI still exercises the independent synthetic catalog/import fixtures.
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from webtools.core import game_motion_selection as selection


SAMPLES = Path(os.environ.get("REAL_GAME_MOTION_DIR", "/nonexistent-private-game-samples"))


@unittest.skipUnless((SAMPLES / "solo-main.unity").is_file(), "Private original-game samples are optional")
class OriginalGameMotionSelectionTests(unittest.TestCase):
    def deadline(self):
        return time.monotonic() + 45

    def test_original_solo_resolves_dancer_pointer_and_exports_only_that_clip(self):
        selected = selection.select(SAMPLES / "solo-main.unity", [SAMPLES / "solo-dance.unity"],
                                    performer=1, category="mv", deadline=self.deadline())
        self.assertEqual([entry["object"].peek_name() for entry in selected["selected"].values()], ["ch0201_so2002"])
        self.assertEqual(selected["segments"][0]["track"], "/MemberMotion/Member1")
        with tempfile.TemporaryDirectory() as directory:
            files, segments, clips, identities = selection.write_selected(selected, directory)
            self.assertEqual(len(files), 1)
            import UnityPy
            objects = list(UnityPy.load(str(files[0]["path"])).objects)
            self.assertEqual([(obj.type.name, obj.peek_name()) for obj in objects], [("AnimationClip", "ch0201_so2002")])
            self.assertEqual(segments[0]["sourceHash"], files[0]["sha256"])

    def test_original_group_resolves_selected_member_instead_of_camera_or_other_dancer(self):
        selected = selection.select(SAMPLES / "group-main.unity", sorted(SAMPLES.glob("group-dep-*.unity")),
                                    performer=1, category="mv", deadline=self.deadline())
        self.assertEqual([entry["object"].peek_name() for entry in selected["selected"].values()], ["ch0001_so0001"])
        self.assertTrue(all(segment["track"] == "/MemberMotion/Member1" for segment in selected["segments"]))
        with self.assertRaisesRegex(ValueError, "no Animator dance binding"):
            selection.select(SAMPLES / "group-main.unity", sorted(SAMPLES.glob("group-dep-*.unity")),
                             performer=10, category="mv", deadline=self.deadline())

    def test_original_voice_preserves_all_overlapping_body_segments_and_speeds(self):
        candidates = list(SAMPLES.glob("voice-dep-*.unity"))
        for manifest in (SAMPLES / "extracted/game-motions").glob(".motion-*.json"):
            receipt = json.loads(manifest.read_text())
            if receipt.get("motion", {}).get("motion") == "voice:1001014":
                directory = manifest.parent / Path(receipt["timelines"][0]["name"]).parent
                candidates = list(directory.glob("source-*.unity"))
                break
        if not candidates:
            self.skipTest("Private voice dependencies are required")
        selected = selection.select(SAMPLES / "voice-main.unity", candidates, category="voice", deadline=self.deadline())
        segments = selected["segments"]
        self.assertEqual(len(segments), 4)
        expected = [(0, 4.15, 0, 1), (4.6166666667, 2.5, 0, 1.2),
                    (6.3666666667, 2.4833333333, .0666666667, 1), (8.2166666667, 2.75, 0, .8)]
        for segment, values in zip(segments, expected):
            for key, value in zip(("start", "duration", "clipIn", "timeScale"), values):
                self.assertAlmostEqual(segment[key], value, places=5)
        self.assertGreater(segments[1]["start"] + segments[1]["duration"], segments[2]["start"])

    def test_original_facial_table_preserves_aliases_instead_of_guessing_names(self):
        selected, entries = selection.facial_banks([SAMPLES / "ayumu-animations1.unity", SAMPLES / "ayumu-animations2.unity"],
                                                   deadline=self.deadline())
        resolved = {(entry["kind"], entry["index"]): selected["selected"][entry["key"]]["object"].peek_name() for entry in entries}
        self.assertTrue(resolved["eyes", 101].endswith("LiveFacial_eye_005"))
        self.assertTrue(resolved["eyes", 102].endswith("LiveFacial_eye_004"))
        self.assertTrue(resolved["mouth", 13].endswith("LiveFacial_mouth_004"))
        self.assertTrue(resolved["mouth", 999].endswith("LiveFacial_mouth_007"))
        self.assertEqual(len(selected["selected"]), 32)

    def test_original_camera_and_facial_roles_follow_exact_timeline_and_table_pointers(self):
        from collections import Counter
        from webtools.core import model_viewer as viewer
        paths = [SAMPLES / "group-main.unity", SAMPLES / "ayumu-animations1.unity", SAMPLES / "ayumu-animations2.unity"]
        deadline = self.deadline()
        scene = viewer._Scene(viewer._environment([str(path) for path in paths], deadline), deadline)
        roles = selection.describe_clip_roles(scene, deadline)
        self.assertEqual(Counter(roles.values()), {"camera": 62, "body": 9, "facial": 32})
        for obj in scene.env.objects:
            if obj.type.name == "AnimationClip" and "camera" in obj.peek_name():
                self.assertEqual(roles[selection._object_key(obj)], "camera")


if __name__ == "__main__":
    unittest.main()
