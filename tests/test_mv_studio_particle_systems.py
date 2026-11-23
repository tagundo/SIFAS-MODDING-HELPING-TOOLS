import base64
import io
import math
import os
import unittest
from pathlib import Path
from unittest import mock

from webtools.core import mv_studio_particle_systems as systems


def constant(value):
    return {"minMaxState": 0, "scalar": value, "minScalar": value,
            "maxCurve": {"m_Curve": []}, "minCurve": {"m_Curve": []}}


def key(time, value, in_slope=0.0, out_slope=0.0):
    return {"time": time, "value": value, "inSlope": in_slope, "outSlope": out_slope, "weightedMode": 0}


def white_gradient(alpha_keys=((0, 1.0), (65535, 1.0))):
    row = {"m_Mode": 0, "m_NumColorKeys": 2, "m_NumAlphaKeys": len(alpha_keys), "ctime0": 0, "ctime1": 65535}
    for index in range(8):
        row[f"key{index}"] = {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
    for index, (stamp, alpha) in enumerate(alpha_keys):
        row[f"atime{index}"] = stamp
        row[f"key{index}"] = {**row[f"key{index}"], "a": alpha}
    return row


def disabled(**fields):
    return {"enabled": False, **fields}


def particle_system(**overrides):
    curve = {"minMaxState": 1, "scalar": 1.0, "minScalar": 1.0,
             "maxCurve": {"m_Curve": [key(0, 0), key(1, 1)]}, "minCurve": {"m_Curve": []}}
    source = {
        "lengthInSec": 5.0, "simulationSpeed": 1.0, "stopAction": 0, "cullingMode": 0, "ringBufferMode": 0,
        "looping": True, "prewarm": True, "playOnAwake": True, "useUnscaledTime": False, "autoRandomSeed": False,
        "startDelay": constant(0.0), "moveWithTransform": 0, "scalingMode": 1, "randomSeed": -1,
        "InitialModule": {"enabled": True, "startLifetime": constant(2.0), "startSpeed": constant(0.0),
                          "startColor": {"minMaxState": 0, "maxColor": {"r": 1, "g": 1, "b": 1, "a": 1},
                                         "minColor": {"r": 1, "g": 1, "b": 1, "a": 1}},
                          "startSize": constant(1.0), "startSizeY": constant(1.0), "startSizeZ": constant(1.0),
                          "startRotationX": constant(0.0), "startRotationY": constant(0.0),
                          "startRotation": constant(0.0), "randomizeRotationDirection": 0.0, "maxNumParticles": 60,
                          "size3D": False, "rotation3D": False, "gravityModifier": constant(0.0)},
        "ShapeModule": {"enabled": True, "type": 5, "angle": 25.0, "length": 5.0,
                        "boxThickness": {"x": 0, "y": 0, "z": 0}, "radiusThickness": 1.0, "donutRadius": 0.2,
                        "m_Position": {"x": 0, "y": 0, "z": 0}, "m_Rotation": {"x": 0, "y": 0, "z": 0},
                        "m_Scale": {"x": 12, "y": 12, "z": 10}, "placementMode": 0, "alignToDirection": False,
                        "randomDirectionAmount": 0.0, "sphericalDirectionAmount": 0.0, "randomPositionAmount": 0.0,
                        "radius": {"value": 1.0, "mode": 0}, "arc": {"value": 360.0, "mode": 0}},
        "EmissionModule": {"enabled": True, "rateOverTime": constant(60.0), "rateOverDistance": constant(0.0),
                           "m_BurstCount": 0, "m_Bursts": []},
        "SizeModule": {"enabled": True, "curve": curve, "y": curve, "z": curve, "separateAxes": False},
        "RotationModule": disabled(curve=constant(0.0), x=constant(0.0), y=constant(0.0), separateAxes=False),
        "ColorModule": {"enabled": True, "gradient": {"minMaxState": 1, "maxGradient": white_gradient(
            ((0, 0.0), (32768, 1.0), (65535, 0.0)))}},
        "UVModule": disabled(),
        "VelocityModule": disabled(),
        "ClampVelocityModule": disabled(),
        "RotationBySpeedModule": disabled(),
    }
    for name in systems._UNSUPPORTED_MODULES:
        source[name] = disabled()
    source.update(overrides)
    return source


class Reader:
    def __init__(self, tree):
        self.tree = tree

    def read_typetree(self):
        return self.tree


RENDERER = {"m_Enabled": 1, "m_RenderMode": 0, "m_RenderAlignment": 0, "m_SortMode": 0, "m_SortingFudge": 0.0,
            "m_MinParticleSize": 0.0, "m_MaxParticleSize": 0.5, "m_LengthScale": 2.0, "m_VelocityScale": 0.0,
            "m_CameraVelocityScale": 0.0, "m_Pivot": {"x": 0, "y": 0, "z": 0}, "m_Flip": {"x": 0, "y": 0, "z": 0},
            "m_AllowRoll": 1, "m_SortingOrder": 0, "m_Materials": [{"m_FileID": 0, "m_PathID": 5}]}
SURFACE = {"name": "mat", "queue": 3000, "tint": [1, 1, 1, 1], "st": [1, 1, 0, 0], "vertexColor": True,
           "saturate": False, "blend": [5, 1], "cull": 0, "zTest": 4, "zWrite": 0, "stencil": [8, 2, 0, 0]}


class NormalizationTests(unittest.TestCase):
    def test_min_max_curve_states(self):
        self.assertEqual(systems.curve(constant(2.5)), {"mode": 0, "scalar": 2.5, "min": 2.5})
        self.assertEqual(systems.curve({**constant(3.0), "minMaxState": 3, "minScalar": 1.0}),
                         {"mode": 3, "scalar": 3.0, "min": 1.0})
        stepped = {"minMaxState": 1, "scalar": 2.0, "minScalar": 0.0,
                   "maxCurve": {"m_Curve": [key(0, 1, 0, math.inf), key(1, 0, math.inf, 0)]}}
        self.assertEqual(systems.curve(stepped)["maxKeys"], [[0, 1, 0, None], [1, 0, None, 0]])
        both = {**stepped, "minMaxState": 2, "minCurve": {"m_Curve": [key(0, 0), key(0.5, 1)]}}
        self.assertEqual(systems.curve(both)["minKeys"], [[0, 0, 0, 0], [0.5, 1, 0, 0]])
        with self.assertRaises(systems._Unsupported):
            systems.curve({**stepped, "maxCurve": {"m_Curve": [key(i / 100, 0) for i in range(65)]}})
        with self.assertRaises(systems._Unsupported):
            systems.curve({**stepped, "maxCurve": {"m_Curve": []}})
        with self.assertRaises(systems._Unsupported):
            systems.curve({**constant(1.0), "minMaxState": 7})

    def test_gradients_keep_sixteen_bit_stamps(self):
        gradient = white_gradient(((0, 0.0), (32768, 1.0), (65535, 0.0)))
        self.assertEqual(systems.gradient(gradient), {
            "mode": 0, "rgb": [[0, 1.0, 1.0, 1.0], [65535, 1.0, 1.0, 1.0]],
            "alpha": [[0, 0.0], [32768, 1.0], [65535, 0.0]]})
        self.assertEqual(systems.color({"minMaxState": 4, "maxGradient": {**gradient, "m_Mode": 1}})["maxGradient"]["mode"], 1)
        two = systems.color({"minMaxState": 2, "minColor": {"r": 0, "g": 0, "b": 0, "a": 0},
                             "maxColor": {"r": 1, "g": .5, "b": .25, "a": 1}})
        self.assertEqual(two, {"mode": 2, "max": [1, .5, .25, 1], "min": [0, 0, 0, 0]})
        both = systems.color({"minMaxState": 3, "minGradient": gradient, "maxGradient": gradient})
        self.assertEqual(set(both), {"mode", "maxGradient", "minGradient"})
        with self.assertRaises(systems._Unsupported):
            systems.gradient({**gradient, "m_NumAlphaKeys": 9})

    def test_main_module_and_bursts(self):
        main = systems._main(particle_system(randomSeed=-1, simulationSpeed=0.5))
        self.assertEqual(main["randomSeed"], 0xFFFFFFFF)
        self.assertEqual(main["simulationSpeed"], 0.5)
        self.assertEqual(main["maxParticles"], 60)
        emission = systems._emission({"enabled": True, "rateOverTime": constant(0.0), "rateOverDistance": constant(0.0),
                                      "m_BurstCount": 1, "m_Bursts": [
                                          {"time": 0.0, "countCurve": constant(1.0), "cycleCount": 3,
                                           "repeatInterval": 0.25, "probability": 1.0},
                                          {"time": 9.0, "countCurve": constant(5.0), "cycleCount": 1,
                                           "repeatInterval": 0.0, "probability": 1.0}]})
        # Only the declared burst count is live; Unity keeps stale entries past it.
        self.assertEqual(emission["bursts"], [{"time": 0.0, "count": {"mode": 0, "scalar": 1.0, "min": 1.0},
                                               "cycles": 3, "interval": 0.25, "probability": 1.0}])
        with self.assertRaises(systems._Unsupported):
            systems._emission({"enabled": True, "rateOverTime": constant(1.0), "rateOverDistance": constant(2.0)})

    def test_shapes_and_modules(self):
        source = particle_system()
        self.assertEqual(systems._shape(source["ShapeModule"])["scale"], [12, 12, 10])
        for kind in (6, 13, 14, 19):
            with self.assertRaises(systems._Unsupported):
                systems._shape({**source["ShapeModule"], "type": kind})
        with self.assertRaises(systems._Unsupported):
            systems._shape({**source["ShapeModule"], "arc": {"value": 360, "mode": 1}})
        self.assertEqual(systems._shape({**source["ShapeModule"], "arc": {"value": 180, "mode": 3}})["arcMode"], 3)
        with self.assertRaises(systems._Unsupported):
            systems._shape({**source["ShapeModule"], "radius": {"value": 1, "mode": 3}})
        velocity = {"enabled": True, "x": constant(0.0), "y": constant(1.0), "z": constant(0.0),
                    "orbitalX": constant(0.0), "orbitalY": constant(0.0), "orbitalZ": constant(0.0),
                    "radial": constant(0.0), "speedModifier": constant(1.0), "inWorldSpace": True}
        velocity.update({name: constant(0.0) for name in ("orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ")})
        self.assertTrue(systems._velocity(velocity)["worldSpace"])
        self.assertNotIn("orbital", systems._velocity(velocity))
        orbit = systems._velocity({**velocity, "orbitalY": constant(1.0), "speedModifier": constant(2.0)})
        self.assertEqual(orbit["orbital"]["orbitalY"], {"mode": 0, "scalar": 1.0, "min": 1.0})
        self.assertEqual(orbit["speedModifier"]["scalar"], 2.0)
        limit = {"enabled": True, "separateAxis": False, "inWorldSpace": False, "dampen": .5,
                 "magnitude": constant(2.0), "drag": constant(1.0),
                 "multiplyDragByParticleSize": True, "multiplyDragByParticleVelocity": True}
        self.assertEqual(systems._clamp(limit)["drag"]["scalar"], 1.0)
        self.assertNotIn("drag", systems._clamp({**limit, "drag": constant(0.0), "multiplyDragByParticleSize": False}))
        with self.assertRaises(systems._Unsupported):
            systems._clamp({**limit, "multiplyDragByParticleVelocity": False})
        uv = {"enabled": True, "mode": 0, "timeMode": 0, "tilesX": 2, "tilesY": 2, "animationType": 1,
              "rowIndex": 1, "randomRow": False, "frameOverTime": constant(0.0), "startFrame": constant(0.5),
              "cycles": 1.0, "flipU": 0.0, "flipV": 0.0}
        self.assertEqual(systems._uv(uv)["tiles"], [2, 2])
        with self.assertRaises(systems._Unsupported):
            systems._uv({**uv, "mode": 1})

    def test_unsupported_modules_and_render_modes_are_reported_not_approximated(self):
        renderer, particle = Reader(RENDERER), Reader(particle_system())
        with mock.patch.object(systems, "_material", return_value=(dict(SURFACE), None)):
            row = systems.system({}, None, particle, renderer, systems._Textures(0))
            self.assertEqual(row["material"]["texture"], None)
            self.assertEqual(row["renderer"]["mode"], 0)
            noisy = Reader(particle_system(NoiseModule={"enabled": True}))
            with self.assertRaisesRegex(systems._Unsupported, "NoiseModule"):
                systems.system({}, None, noisy, renderer, systems._Textures(0))
            trails = Reader(particle_system(TrailModule={"enabled": True}))
            with self.assertRaisesRegex(systems._Unsupported, "TrailModule"):
                systems.system({}, None, trails, renderer, systems._Textures(0))
            idle = Reader(particle_system(playOnAwake=False))
            with self.assertRaisesRegex(systems._Unsupported, "playOnAwake"):
                systems.system({}, None, idle, renderer, systems._Textures(0))
            with self.assertRaisesRegex(systems._Unsupported, "mesh render mode"):
                systems.system({}, None, particle, Reader({**RENDERER, "m_RenderMode": 4}), systems._Textures(0))
            self.assertIsNone(systems.system({}, None, particle, Reader({**RENDERER, "m_Enabled": 0}),
                                             systems._Textures(0)))

    def test_claimed_cues_and_warning(self):
        result = {"tracks": [{"trackId": "ignored", "eventId": "ignored"}],
                  "stageRain": {"cues": [{"trackId": "a", "eventId": "a:0", "profile": "01"}]},
                  "stageButterfly": {"trackId": "b", "eventId": "b:1", "finale": {"trackId": "b", "eventId": "b:2"}}}
        self.assertEqual(systems.claimed_cues(result), {("a", "a:0"), ("b", "b:1"), ("b", "b:2")})
        self.assertIsNone(systems.warning({"unsupported": []}))
        note = systems.warning({"unsupported": [{"reason": "SubModule"}, {"reason": "SubModule"},
                                                {"reason": "mesh render mode"}]})
        self.assertEqual(note, "3 original particle systems are not previewed: SubModule x2, mesh render mode x1.")
        self.assertEqual(systems.warning({"unsupported": [], "otherComponents": {"fx": ["Animator", "MeshRenderer"]}}),
                         "1 particle prefabs also hold Animator, MeshRenderer content that is not previewed.")


_CENSUS = Path(os.environ.get(
    "ELICHIKA_MV_CENSUS_BUNDLES",
    "/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/coverage/bundle-census/bundles"))
_TIMELINE_12035 = _CENSUS / "android" / "live_timeline-bcc02fa813.unity3d"


@unittest.skipUnless(_TIMELINE_12035.is_file() and os.environ.get("ELICHIKA_TEXTURE65_BIN"),
                     "Set ELICHIKA_MV_CENSUS_BUNDLES and ELICHIKA_TEXTURE65_BIN for the original 12035 timeline")
class OriginalTimelineTests(unittest.TestCase):
    def test_12035_android_cues_templates_and_textures(self):
        from PIL import Image
        from webtools.core import mv_studio_timeline

        parsed = mv_studio_timeline.parse_timeline(_TIMELINE_12035.read_bytes(), "12035", preview_particle_systems=True)
        source = parsed["stageParticleSystems"]
        self.assertEqual(len(source["cues"]), 14)
        self.assertEqual(source["unsupported"], [])
        names = {template["name"]: template for template in source["templates"]}
        self.assertEqual(len(names), 10)
        # fx_flo_so2035_03 holds 35 systems, but 20 sit under inactive GameObjects that no clip
        # or Animator activates, so the clone never plays them.
        self.assertEqual({name: len(row["systems"]) for name, row in names.items() if name.startswith("fx_flo")},
                         {"fx_flo_so2035_01": 24, "fx_flo_so2035_02": 26, "fx_flo_so2035_03": 15})
        light = [cue for cue in source["cues"] if source["templates"][cue["template"]]["name"] == "fx_par_so2035_04"]
        self.assertEqual([cue["offset"] for cue in light], [[0.0, 13.0, 59.0]])
        self.assertEqual({cue["quality"] for cue in source["cues"]}, {"stage_control", "stage_display"})
        dust = names["fx_par_so2035_01"]["systems"][0]
        self.assertEqual((dust["main"]["randomSeed"], dust["main"]["autoRandomSeed"], dust["layer"]),
                         (dust["main"]["randomSeed"], False, 1))
        self.assertEqual(dust["shape"]["scale"], [12.0, 12.0, 10.0])
        for texture in source["textures"]:
            levels = texture["levels"]
            # Authored pixels and mip levels only: each level halves, nothing is resampled.
            for index, level in enumerate(levels):
                image = Image.open(io.BytesIO(base64.b64decode(level["png"])))
                self.assertEqual(image.size, (level["width"], level["height"]))
                self.assertEqual(level["width"], max(1, levels[0]["width"] >> index))
            self.assertEqual(len(levels), max(levels[0]["width"], levels[0]["height"]).bit_length())


if __name__ == "__main__":
    unittest.main()
