"""LiveCoreLossyScale on a real stage effect (12009's fx_ove_so2009_01 overlay, nine objects).
Set MV_LOSSY_SCALE_EFFECT and MV_LOSSY_SCALE_TIMELINE to the decrypted 12009 (asset 1200903)
stage_effect and live_timeline bundles to run it."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_EFFECT = os.environ.get("MV_LOSSY_SCALE_EFFECT", "")
_TIMELINE = os.environ.get("MV_LOSSY_SCALE_TIMELINE", "")


@unittest.skipUnless(_EFFECT and _TIMELINE and Path(_EFFECT).is_file() and Path(_TIMELINE).is_file(),
                     "MV_LOSSY_SCALE_EFFECT / MV_LOSSY_SCALE_TIMELINE are not set")
class LossyScaleTest(unittest.TestCase):
    def test_retained_nodes_carry_offset_scale(self):
        from webtools.core import model_viewer, mv_studio_timeline
        parsed = mv_studio_timeline.parse_timeline(Path(_TIMELINE).read_bytes(), Path(_TIMELINE).name,
                                                   preview_stage_motion=True)
        bindings = tuple(parsed.get("stageMotion", {}).get("bindings", ()))
        prepared = model_viewer.prepare([_EFFECT], rigged=False, face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
            "_mv_stage_motion_bindings": bindings, "_mv_performer": False, "_mv_native_stage_effect": True})
        payload = model_viewer.get_model(prepared["id"])
        doc = json.loads(payload[20:20 + int.from_bytes(payload[12:16], "little")])
        tagged = {node["name"]: node["extras"]["mvLossyScaleOffset"] for node in doc["nodes"]
                  if "mvLossyScaleOffset" in node.get("extras", {})}
        self.assertEqual(len(tagged), 9)
        self.assertEqual(tagged["Hoop_01"], [2.0, 2.0, 2.0])
        self.assertEqual(tagged["Shimmer"], [0.5, 0.5, 0.5])
        self.assertAlmostEqual(tagged["MultiIris_01"][0], 0.3, places=6)


if __name__ == "__main__":
    unittest.main()
