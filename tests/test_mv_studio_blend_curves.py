"""World MeshRenderer material curves of AS/Blend/Opaque renderers (10120's sky_01 _BlendRate)."""
import os
from pathlib import Path
import unittest
from zlib import crc32

from webtools.core import model_animation as animation
from webtools.core import model_viewer
from webtools.core import mv_studio_stage_overlay as overlay

from test_mv_studio_blend_sky import _glb, _primitives

_SKY = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so0120_01/root"


class BlendCurveTests(unittest.TestCase):
    @staticmethod
    def _binding(name, lane, path=animation.path_hash("sky_01")):
        return {"path": path, "attribute": (lane << 28) | crc32(name.encode()) & 0x0FFFFFFF, "typeID": 23,
                "customType": 22, "isPPtrCurve": 0, "script": {"m_FileID": 0, "m_PathID": 0}}

    def test_world_mesh_renderer_blend_rate_and_ambient_channels(self):
        rows = [self._binding("_TintColor", lane) for lane in range(4)]
        rows += [self._binding("_BlendRate", 8)]
        rows += [self._binding("_AmbientColor", lane) for lane in range(4, 8)]
        curves = [("constant", float(index)) for index in range(len(rows))]
        channels, count = overlay.material_channels(rows, curves, lambda _: 1, world=True)
        self.assertEqual(count, 9)
        kinds = {(row["kind"], row.get("property")): row["curves"] for row in channels}
        self.assertEqual(kinds[("overlayTint", None)], curves[:4])
        self.assertEqual(kinds[("overlayScalar", "_BlendRate")], [curves[4]])
        self.assertEqual(kinds[("overlayAmbient", None)], curves[5:])
        self.assertEqual(overlay.material_channels(rows, curves, lambda _: 1, world=False), ([], 0),
                         "the layer-20 overlay pass has no AS/Blend/Opaque holder")
        self.assertEqual(overlay.material_channels(rows[:4] + rows[5:8], curves[:4] + curves[5:8], lambda _: 1, world=True),
                         ([], 0), "a partial color is not a channel")


class ActualSkyCurveTests(unittest.TestCase):
    """Set SIFAS_TEST_TIMELINE_10120 and SIFAS_TEST_STAGE_EFFECT_10120 to the original Android 10120
    (asset 1012003) live_timeline and stage_effect bundles."""

    @staticmethod
    def bundle(variable):
        raw = os.environ.get(variable)
        if not raw or not Path(raw).is_file():
            raise unittest.SkipTest(f"Set {variable} to the original 10120 bundle")
        return Path(raw)

    @classmethod
    def motion(cls):
        from webtools.core import mv_studio_timeline as timeline
        raw = cls.bundle("SIFAS_TEST_TIMELINE_10120").read_bytes()
        return timeline.parse_timeline(raw, "10120", preview_stage_motion=True)

    def test_sky_clip_drives_the_dome_renderer(self):
        parsed = self.motion()
        motion = parsed["stageMotion"]
        self.assertIn(_SKY, motion["bindings"])
        track = next(row for row in parsed["tracks"] if row.get("binding") == _SKY and row.get("nativeClass") == "AnimationTrack")
        self.assertEqual(motion["quality"][track["id"]], "stage_control")
        event = track["events"][0]
        self.assertEqual(motion["mix"][event["id"]]["materialScope"], "world")
        clip = motion["clips"][event["values"]["animation"]]
        self.assertTrue(clip["requiresOverlayMaterial"] and clip["sampleTimeF32"])
        sky = animation.path_hash("sky_01")
        rows = {(row["kind"], row.get("property"), row["path"]): row["curves"] for row in clip["channels"]}
        self.assertEqual(set(rows), {("overlayTint", None, sky), ("overlayScalar", "_BlendRate", sky)})

        def value(curve, time):
            mode, keys = curve
            start, (a, b, c, d) = [key for key in keys if key[0] <= time][-1]
            delta = time - start
            return ((a * delta + b) * delta + c) * delta + d

        rate = rows[("overlayScalar", "_BlendRate", sky)][0]
        self.assertEqual([value(rate, time) for time in (0., 44.5, 92.)], [0., 0., 0.], "the day map")
        self.assertEqual([value(rate, time) for time in (92.0167, 102.5, 121.9)], [1., 1., 1.],
                         "the night map from 92.0167 s")
        self.assertEqual({value(curve, 60.) for curve in rows[("overlayTint", None, sky)]}, {1.})

    def test_dome_keeps_the_prefab_node_its_curves_bind(self):
        bindings = self.motion()["stageMotion"]["bindings"]
        prepared = model_viewer.prepare([str(self.bundle("SIFAS_TEST_STAGE_EFFECT_10120"))], rigged=False, face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
            "_mv_stage_motion_bindings": bindings, "_mv_performer": False, "_mv_native_stage_effect": True})
        doc, _ = _glb(model_viewer.get_model(prepared["id"]))
        primitive, = _primitives(doc, "mat_stg_so0120_opa_01")
        node = next(index for index, row in enumerate(doc["nodes"]) if row.get("mesh") is not None
                    and doc["meshes"][row["mesh"]]["primitives"][0] is primitive)
        parent = next(row for row in doc["nodes"] if node in row.get("children", ()))
        self.assertEqual(parent["extras"]["mvStageNode"], {"active": True, "binding": _SKY, "path": animation.path_hash("sky_01")})
        self.assertNotIn("translation", doc["nodes"][node], "the dome vertices stay in the renderer's frame")


if __name__ == "__main__":
    unittest.main()
