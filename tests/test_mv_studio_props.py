from pathlib import Path
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import model_animation, mv_studio, mv_studio_props, mv_studio_timeline


_FIXTURE = os.environ.get("ELICHIKA_AION_PROP_FIXTURE")
_HAND = "Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/RightShoulder/RightArm/RightForeArm/RightHand"
_TARGET = "/EntryPoint/Live/Members/ske_so2028/Member1/Model/" + _HAND + "/chp0001"


class MVStudioPropBindingsTests(unittest.TestCase):
    def test_matches_exact_animation_and_activation_target(self):
        tracks = [
            {"id": "motion", "nativeClass": "AnimationTrack", "binding": _TARGET,
             "events": [{"id": "clip", "values": {"animation": "cab:123"}}]},
            {"id": "different", "nativeClass": "ActivationTrack", "binding": _TARGET + "2"},
        ]
        self.assertEqual(mv_studio_props.bindings(tracks), [])
        tracks.append({"id": "visibility", "nativeClass": "ActivationTrack", "binding": _TARGET})
        binding, = mv_studio_props.bindings(tracks)
        self.assertEqual((binding["member"], binding["bone"]), (1, _HAND))
        self.assertEqual(binding["activation"], ["visibility"])
        self.assertEqual(binding["clips"], {"clip": "cab:123"})

    @unittest.skipUnless(_FIXTURE, "Set ELICHIKA_AION_PROP_FIXTURE to the native Aion catalog fixture.")
    def test_complete_original_assets_in_both_platforms(self):
        fixture = Path(_FIXTURE)
        with tempfile.TemporaryDirectory() as media, patch.object(mv_studio, "_root", return_value=Path(media)):
            for platform, key in (("android", "a"), ("ios", "i")):
                with self.subTest(platform=platform):
                    stages = []
                    project = mv_studio.load_game(
                        fixture / "runtime", region="gl", platform=platform, live_id=12028,
                        asset_id=1202803, language="en", on_stage=stages.append,
                    )
                    self.assertEqual(len(stages), 1)
                    self.assertTrue(stages[0]["stage"]["glb"])
                    self.assertFalse(any(row.get("attachment") for row in stages[0]["assets"]))
                    prop, = [item for item in project["assets"] if item.get("attachment")]
                    actor, = project["performers"]
                    self.assertEqual((actor["memberId"], actor["position"]), (208, 1))
                    self.assertTrue(actor["motion"])
                    spec = prop["attachment"]
                    self.assertEqual((spec["member"], spec["bone"], spec["limit"]), (1, _HAND, 135))
                    nodes = [bone["node"] for bone in actor["rig"]["bones"]
                             if bone["path"] == _HAND or bone["path"].endswith("/" + _HAND)]
                    self.assertEqual(len(nodes), 1)
                    raw, _ = mv_studio.media(prop["previewUrl"].rsplit("/", 1)[-1])
                    self._check_glb(raw.read_bytes())
                    curve, = spec["curves"].values()
                    self._check_angle(curve)
                    visibility, = [track for track in project["tracks"] if track["id"] in spec["activation"]]
                    interval, = visibility["events"]
                    self.assertEqual(interval["start"], 0)
                    self.assertAlmostEqual(interval["duration"], 97.8666666667)
                    for variant in (1202801, 1202802):
                        source = fixture / f"{key}-timeline-{variant}.unity"
                        native = source.read_bytes()
                        bindings, = mv_studio_props.bindings(mv_studio_timeline.parse_timeline(native, source.name)["tracks"])
                        glb, variant_spec = mv_studio_props.preview(
                            fixture / f"{key}-prop.unity", native, source.name, bindings, time.monotonic()+20,
                        )
                        self._check_glb(glb)
                        variant_curve, = variant_spec["curves"].values()
                        self._check_angle(variant_curve)

    def _check_glb(self, raw):
        length = int.from_bytes(raw[12:16], "little")
        document = json.loads(raw[20:20+length])
        attributes = document["meshes"][0]["primitives"][0]["attributes"]
        self.assertEqual(document["accessors"][attributes["_MV_FAN_UV"]]["count"], 288)
        self.assertEqual([image["name"] for image in document["images"]], ["chp0001"])
        self.assertEqual(document["nodes"][0]["matrix"], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])

    def _check_angle(self, source):
        self.assertEqual(source["mode"], "cubic")
        self.assertEqual(len(source["keys"]), 128)
        curve = source["mode"], source["keys"]
        self.assertEqual(model_animation._evaluate(curve, 1), 0)
        self.assertAlmostEqual(model_animation._evaluate(curve, 30), 135)


if __name__ == "__main__":
    unittest.main()
