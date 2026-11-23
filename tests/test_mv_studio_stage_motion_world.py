"""World-scope stage AnimationClips with MeshRenderer material curves."""
import os
from pathlib import Path
import unittest

from webtools.core import model_animation as animation
from webtools.core import mv_studio_timeline as timeline


class ActualRendererMaterialCurveTests(unittest.TestCase):
    """Set SIFAS_TEST_TIMELINE_12025 to the original Android 12025 live_timeline bundle."""

    def test_12025_anim_root_keeps_speaker_uv_and_cap_activation(self):
        raw = os.environ.get("SIFAS_TEST_TIMELINE_12025")
        if not raw or not Path(raw).is_file():
            self.skipTest("Set SIFAS_TEST_TIMELINE_12025 to the original 12025 live_timeline bundle")
        parsed = timeline.parse_timeline(Path(raw).read_bytes(), "12025", preview_stage_motion=True)
        motion = parsed["stageMotion"]
        binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so2025_01/root"
        track = next(row for row in parsed["tracks"] if row["label"] == "StageEffect/Expert/Animation/Anim_root")
        self.assertEqual(track["binding"], binding)
        self.assertIn(binding, motion["bindings"])
        event = track["events"][0]
        self.assertEqual(motion["mix"][event["id"]]["materialScope"], "world")
        self.assertEqual(motion["quality"][track["id"]], "stage_animation")
        clip = motion["clips"][event["values"]["animation"]]
        self.assertTrue(clip["requiresOverlayMaterial"])
        self.assertEqual({(row["kind"], row["path"]) for row in clip["channels"]}, {
            ("visibility", animation.path_hash("cap")), ("overlayUV", animation.path_hash("speaker"))})
        self.assertNotIn("rendererClass", next(row for row in clip["channels"] if row["kind"] == "overlayUV"))


if __name__ == "__main__":
    unittest.main()
