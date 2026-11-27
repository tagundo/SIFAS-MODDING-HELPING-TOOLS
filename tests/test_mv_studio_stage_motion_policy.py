"""Stage-node clip material curves: an unplayable material curve is dropped and reported, not the clip."""
import os
from pathlib import Path
import unittest
from zlib import crc32

from webtools.core import model_animation as animation
from webtools.core import mv_studio_import_coverage as coverage
from webtools.core import mv_studio_stage_overlay as overlay

_NULL = {"m_FileID": 0, "m_PathID": 0}
_SMOKE = animation.path_hash("smoke_01")


def _binding(name, lane, *, path=_SMOKE, renderer=23, script=_NULL):
    return {"path": path, "attribute": (lane << 28) | crc32(name.encode()) & 0x0FFFFFFF, "typeID": renderer,
            "customType": 22, "isPPtrCurve": 0, "script": script}


def _decode(rows, **options):
    curves = [("constant", float(index)) for index in range(len(rows))]
    return overlay.material_channels(rows, curves, lambda _: 1, **options), curves


class MaterialCurvePolicyTests(unittest.TestCase):
    def test_every_smoke_and_fog_float_is_a_world_channel(self):
        # 11030 clip_stg_so1030_05 animates these AS/Smoke floats.
        names = ("_CurvePower", "_FadeOutPower", "_FadeOutScale", "_TextureRate", "_MoveSpeed", "_SizeAspect")
        (channels, count), curves = _decode([_binding(name, 8) for name in names], world=True)
        self.assertEqual(count, len(names))
        self.assertEqual({row["property"]: row["curves"] for row in channels},
                         {name: [curves[index]] for index, name in enumerate(names)})

    def test_unknown_property_is_dropped_and_reported(self):
        rows = [_binding("_TintColor", lane) for lane in range(4, 8)] + [_binding("_ScrollU", 8)]
        self.assertEqual(_decode(rows, world=True)[0], ([], 0), "without a report list the clip is refused")
        dropped = []
        (channels, count), curves = _decode(rows, world=True, dropped=dropped)
        self.assertEqual(count, 5, "the dropped lane still counts as described")
        self.assertEqual([(row["kind"], row["curves"]) for row in channels], [("overlayTint", curves[:4])])
        self.assertEqual(dropped, [{"path": _SMOKE, "rendererClass": 23,
                                    "propertyHash": crc32(b"_ScrollU") & 0x0FFFFFFF}])

    def test_overlay_scope_drops_world_only_properties(self):
        dropped = []
        (channels, count), _ = _decode([_binding("_Density", 8), _binding("_MainTex_ST", 0)] +
                                       [_binding("_MainTex_ST", lane) for lane in (1, 2, 3)], dropped=dropped)
        self.assertEqual(([row["kind"] for row in channels], count), (["overlayUV"], 5))
        self.assertEqual([row["propertyHash"] for row in dropped], [crc32(b"_Density") & 0x0FFFFFFF])

    def test_particle_renderer_material_curves_are_dropped(self):
        dropped = []
        particles = animation.path_hash("smoke_01/particles")
        rows = [_binding("_Color", lane, path=particles, renderer=199) for lane in range(4, 8)] + [_binding("_CurvePower", 8)]
        (channels, count), _ = _decode(rows, world=True, dropped=dropped)
        self.assertEqual(([row["property"] for row in channels], count), (["_CurvePower"], 5))
        self.assertEqual([(row["rendererClass"], row["propertyHash"]) for row in dropped],
                         [(199, crc32(b"_Color") & 0x0FFFFFFF)])
        # Without a report list they stay undescribed, so the clip reader refuses the clip.
        self.assertEqual(_decode(rows, world=True)[0][1], 1)

    def test_incomplete_lanes_are_dropped(self):
        dropped = []
        rows = [_binding("_TintColor", lane) for lane in (4, 5, 6)] + [_binding("_Density", 8)]
        (channels, count), _ = _decode(rows, world=True, dropped=dropped)
        self.assertEqual(([row["property"] for row in channels], count), (["_Density"], 4))
        self.assertEqual(dropped, [{"path": _SMOKE, "rendererClass": 23, "incomplete": ["overlayTint"]}])

    def test_malformed_bindings_still_refuse_the_clip(self):
        script = {"m_FileID": 1, "m_PathID": 9}
        for rows in ([_binding("_Density", 8), _binding("_Density", 8)],
                     [_binding("_Density", 8, script=script)],
                     [_binding("_Density", 8), _binding("_TintColor", 4, renderer=137)],
                     [{**_binding("_Density", 8), "path": 0}]):
            self.assertEqual(_decode(rows, world=True, dropped=[])[0], ([], 0), rows)


class DroppedCurveCoverageTests(unittest.TestCase):
    def test_clips_with_dropped_material_curves_are_partial(self):
        stage = "/EntryPoint/Live/Stages/MainStage/Effect/fx/root"
        events = [{"id": f"motion:{index}", "start": 0., "duration": 1.,
                   "values": {"animation": f"clip{index}"}} for index in range(3)]
        track = {"id": "motion", "nativeClass": "AnimationTrack", "kind": "effects", "label": "motion",
                 "binding": stage, "events": events}
        project = {"tracks": [track], "warnings": [], "performers": [], "stageMotion": {
            "bindings": [stage], "mix": {"motion:0": {}, "motion:1": {}},
            "clips": {"clip0": {"channels": []}, "clip1": {"channels": [], "droppedChannels": [{"path": 1}]}}}}
        rows = {(row["status"], row["note"]): row["clips"] for row in coverage.report(project)["tracks"]
                if row["nativeClass"] == "AnimationTrack"}
        self.assertEqual(rows, {(coverage.RENDERED, "Stage-node animation."): 1,
                                (coverage.PARTIAL, coverage._DROPPED_CURVES): 1,
                                (coverage.NOT_RENDERED, "Clips the stage-motion reader rejects."): 1})
        project["stageMotion"]["mix"] = {"motion:1": {}}
        rows = {(row["status"], row["note"]): row["clips"] for row in coverage.report(project)["tracks"]
                if row["nativeClass"] == "AnimationTrack"}
        self.assertEqual(rows, {(coverage.PARTIAL, coverage._DROPPED_CURVES): 1,
                                (coverage.NOT_RENDERED, "Clips the stage-motion reader rejects."): 2})


if __name__ == "__main__":
    unittest.main()
