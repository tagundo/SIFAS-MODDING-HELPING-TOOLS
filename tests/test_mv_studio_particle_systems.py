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
    def __init__(self, tree, kind="MonoBehaviour"):
        self.tree = tree
        self.type = type("Type", (), {"name": kind})

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
        initial = particle_system()["InitialModule"]
        self.assertEqual(systems._main(particle_system(InitialModule={**initial, "maxNumParticles": 10000}))
                         ["maxParticles"], 10000)
        with mock.patch.object(systems, "_material", return_value=(dict(SURFACE), None)):
            def pool(**fields):
                source = particle_system(InitialModule={**initial, "maxNumParticles": 10000, **fields})
                return systems.system({}, None, Reader(source), Reader(RENDERER), systems._Textures(0))["main"]

            # 60/s for 2 s never fills the preview's 4096 pool, so it stands in exactly.
            self.assertEqual(pool()["maxParticles"], 4096)
            # A pool that could fill past 4096, or a lifetime curve that hides it, is reported.
            for fields in ({"startLifetime": constant(100.0)},
                           {"startLifetime": {**constant(2.0), "minMaxState": 1,
                                              "maxCurve": {"m_Curve": [key(0, 1), key(1, 1)]}}}):
                with self.assertRaisesRegex(systems._Unsupported, "maxParticles above the preview limit of 4096"):
                    pool(**fields)
        rate = {"mode": 0, "scalar": 10.0, "min": 10.0}
        bursts = [{"time": 0, "count": {"mode": 3, "scalar": 50.0, "min": 20.0}, "cycles": 2, "interval": .5,
                   "probability": 1}]
        row = {"main": {"lifetime": {"mode": 3, "scalar": 3.0, "min": 1.0}, "duration": 1.0, "looping": True},
               "emission": {"rate": rate, "bursts": bursts}}
        # 10/s * 3 s + 1, plus 2 firings of 50 in each of the 4 loops a 3 s window can touch.
        self.assertEqual(systems._alive_bound(row), 31 + 4 * 2 * 50)
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
        # The module's own switch rides along: the prewarm's rate carry emits only from an enabled module.
        self.assertIs(emission["enabled"], True)
        self.assertEqual(systems._emission({"enabled": False, "rateOverTime": constant(5.0)}),
                         {"enabled": False, "rate": {"mode": 0, "scalar": 0.0, "min": 0.0}, "bursts": []})

    def test_shapes_and_modules(self):
        source = particle_system()
        self.assertEqual(systems._shape(source["ShapeModule"])["scale"], [12, 12, 10])
        # Mesh shapes, BoxShell and BoxEdge (no boxThickness sampling) are reported.
        for kind in (6, 13, 14, 15, 16, 19):
            with self.assertRaises(systems._Unsupported):
                systems._shape({**source["ShapeModule"], "type": kind})
        # Partial radius thickness: spheres only at full volume, circles/cones full or edge.
        for kind, thickness in ((0, 0.0), (2, 0.5), (4, 0.6), (10, 0.9), (8, 0.5)):
            with self.assertRaisesRegex(systems._Unsupported, "radiusThickness"):
                systems._shape({**source["ShapeModule"], "type": kind, "radiusThickness": thickness})
        for kind, thickness in ((0, 1.0), (4, 0.0), (10, 1.0), (5, 0.0), (1, 0.0), (12, 0.3)):
            self.assertEqual(systems._shape({**source["ShapeModule"], "type": kind,
                                             "radiusThickness": thickness})["radiusThickness"], thickness)
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

    def test_three_dimensional_rotation_is_drawn_on_billboards(self):
        self.assertTrue(systems._zero(constant(0.0)))
        self.assertFalse(systems._zero(constant(0.5)))
        self.assertTrue(systems._zero({**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(0, 0), key(1, 0)]}}))
        self.assertFalse(systems._zero({**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(0, 0, 0, 1)]}}))
        self.assertFalse(systems._zero({**constant(0.0), "minMaxState": 3, "minScalar": -1.0}))
        initial = particle_system()["InitialModule"]
        flat = systems._main(particle_system(InitialModule={**initial, "rotation3D": True}))
        self.assertTrue(flat["rotation3D"])
        with mock.patch.object(systems, "_material", return_value=(dict(SURFACE), None)):
            local = Reader({**RENDERER, "m_RenderAlignment": 2})
            for axis in ("startRotationX", "startRotationY"):
                # AlwaysSimulate: culling never pauses it.
                tumbling = particle_system(cullingMode=3,
                                           InitialModule={**initial, "rotation3D": True, axis: constant(math.pi)})
                self.assertEqual(systems._main(tumbling)["rotationX" if axis.endswith("X") else "rotationY"]["scalar"],
                                 math.pi)
                # Billboards turn on their alignment's axes (libunity.so 0xd242c): the emitter's for
                # Local (the native display-light strokes' rule), the world's for World, and camera
                # right, up and back for View.
                for alignment in (0, 1, 2):
                    row = systems.system({}, None, Reader(tumbling), Reader({**RENDERER, "m_RenderAlignment": alignment}),
                                         systems._Textures(0))
                    self.assertTrue(row["main"]["rotation3D"])
                # Stretched, horizontal and vertical quads are reported.
                for mode in (1, 2, 3):
                    with self.assertRaisesRegex(systems._Unsupported, r"^3D start rotation \(X/Y axes\)$"):
                        systems.system({}, None, Reader(tumbling), Reader({**RENDERER, "m_RenderMode": mode}),
                                       systems._Textures(0))
            # Culling that pauses the system off screen (looping procedural Automatic, Pause) is
            # replayed by the runtime from the culling box; without the box the system stays
            # reported, since its clock depends on the cameras' visibility history.
            heavy = {**initial, "rotation3D": True, "startRotationY": constant(.1), "gravityModifier": constant(.5)}
            for culling, looping, extra, reason in (
                    (0, True, {}, None), (2, False, {}, None), (0, False, {}, None), (1, True, {}, None),
                    (3, True, {}, None),
                    (0, True, {"InitialModule": heavy},
                     "Automatic culling pauses it off screen, and its culling bounds with gravity are not reproduced"),
                    (2, False, {"stopAction": 1}, "Pause culling pauses it off screen, and Pause culling of a "
                                                  "non-procedural system")):
                fields = {"InitialModule": {**initial, "rotation3D": True, "startRotationY": constant(.1)}, **extra}
                tumbling = particle_system(cullingMode=culling, looping=looping, **fields)
                if reason:
                    with self.assertRaisesRegex(systems._Unsupported, "^" + reason.replace("(", "\\(").replace(")", "\\)")):
                        systems.system({}, None, Reader(tumbling), local, systems._Textures(0))
                else:
                    row = systems.system({}, None, Reader(tumbling), local, systems._Textures(0))
                    self.assertEqual(row["culling"]["pauses"], culling == 2 or (culling == 0 and looping))
            # A Z-only 3D rotation is no new case: culling does not keep it reported.
            self.assertTrue(systems.system({}, None, Reader(particle_system(InitialModule={**initial, "rotation3D": True})),
                                           local, systems._Textures(0)))
        # Unity keeps serialized X/Y values while 3D rotation is off; only Z is used then.
        self.assertFalse(systems._main(particle_system(InitialModule={**initial, "startRotationX": constant(1.0)}))
                         ["rotation3D"])
        spin = {"enabled": True, "separateAxes": True, "x": constant(0.0), "y": constant(0.0), "curve": constant(2.0)}
        self.assertEqual(systems._rotation(spin)["z"]["scalar"], 2.0)
        with self.assertRaisesRegex(systems._Unsupported, "RotationModule X/Y"):
            systems._rotation({**spin, "x": constant(1.0)})
        self.assertEqual(systems._rotation({**spin, "separateAxes": False, "x": constant(1.0)})["curve"]["scalar"], 2.0)

    def test_procedural_flag_follows_the_client(self):
        # libunity.so 0x1d1910 (the flag Play stores at state +0x21), mapped to serialized fields.
        self.assertTrue(systems.procedural(particle_system()))
        initial, shape = particle_system()["InitialModule"], particle_system()["ShapeModule"]
        rotation = particle_system()["RotationModule"]
        many = {**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(index / 9, 0) for index in range(10)],
                                                                 "m_PreInfinity": 2, "m_PostInfinity": 2}}
        looped = {**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(.2, 0), key(1, 1)],
                                                                   "m_PreInfinity": 1, "m_PostInfinity": 2}}
        clamped = {**looped, "maxCurve": {**looped["maxCurve"], "m_PreInfinity": 2}}
        velocity = {"enabled": True, "x": constant(1.0), "y": constant(0.0), "z": constant(0.0), "orbitalX": constant(0.0),
                    "orbitalY": constant(0.0), "orbitalZ": constant(0.0), "radial": constant(0.0)}
        cases = [
            ({"moveWithTransform": 1}, False), ({"stopAction": 1}, False),
            ({"EmissionModule": {**particle_system()["EmissionModule"], "rateOverDistance": constant(2.0)}}, False),
            *[({name: {"enabled": True}}, False) for name in systems._PROCEDURAL_OFF],
            ({"InitialModule": {**initial, "gravityModifier": {**constant(0.0), "minMaxState": 3}}}, False),
            ({"InitialModule": {**initial, "startLifetime": constant(math.inf)}}, False),
            # Arc modes other than Random rule out cones, circles and donuts; a box has none.
            ({"ShapeModule": {**shape, "type": 10, "arc": {"value": 360.0, "mode": 3}}}, False),
            ({"ShapeModule": {**shape, "type": 5, "arc": {"value": 360.0, "mode": 3}}}, True),
            ({"ShapeModule": {**shape, "type": 12, "radius": {"value": 1.0, "mode": 1}}}, False),
            # Curves must fit the 8-segment polynomial curve without Loop/PingPong wraps (0x1da114).
            ({"RotationModule": {**rotation, "enabled": True, "curve": many}}, False),
            ({"RotationModule": {**rotation, "enabled": True, "curve": looped}}, False),
            ({"RotationModule": {**rotation, "enabled": True, "curve": clamped}}, True),
            ({"RotationModule": {**rotation, "enabled": False, "curve": many}}, True),
            ({"VelocityModule": velocity}, True), ({"VelocityModule": {**velocity, "radial": constant(1.0)}}, False),
            ({"VelocityModule": {**velocity, "x": many}}, False),
            ({"ForceModule": {"enabled": True, "x": constant(1.0), "y": constant(0.0), "z": constant(0.0),
                              "randomizePerFrame": True}}, False),
        ]
        for fields, expected in cases:
            self.assertEqual(systems.procedural(particle_system(**fields)), expected, fields)
        # Automatic culling pauses only a looping procedural system; Pause culling any system.
        for culling, fields, pauses, bounded in ((0, {}, True, True), (0, {"looping": False}, False, False),
                                                 (0, {"stopAction": 1}, False, False), (1, {}, False, False),
                                                 (3, {}, False, False), (2, {}, True, True),
                                                 (2, {"stopAction": 1}, True, False)):
            row = systems.culling(particle_system(cullingMode=culling, **fields), RENDERER)
            self.assertEqual((row["pauses"], row["bounds"] is not None), (pauses, bounded), (culling, fields))
            # The flag itself rides along for the runtime's procedural prewarm cap, whatever the culling mode.
            self.assertEqual(row["procedural"], systems.procedural(particle_system(cullingMode=culling, **fields)))
        self.assertIs(systems.culling(particle_system(stopAction=1), RENDERER)["procedural"], False)

    def test_procedural_culling_bounds(self):
        # 0x1db800: the value range of a curve includes its overshoot between keys.
        bump = {"m_Curve": [key(0, 0, 0, 4), key(1, 0, -4, 0)]}
        self.assertEqual([round(value, 6) for value in systems._curve_range(bump)], [0, 1])
        self.assertEqual(systems.value_range(constant(2.0)), (0.0, 2.0))
        self.assertEqual(systems.value_range(constant(-2.0)), (-2.0, 0.0))
        self.assertEqual(systems.value_range({**constant(3.0), "minMaxState": 3, "minScalar": 1.0}), (1.0, 3.0))
        self.assertEqual(systems.value_range({**constant(2.0), "minMaxState": 1, "maxCurve": bump})[1], 2.0)
        # 0x1dbaec: the integral range over [0, 1]: 1 - 2t integrates to t - t^2, at most 1/4.
        falling = {**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(0, 1, -2, -2), key(1, -1, -2, -2)]}}
        self.assertEqual([round(value, 6) for value in systems.integral_range(falling)], [0, .25])
        # Constant past the last key: 1 until 0.5, then 0.
        early = {**constant(1.0), "minMaxState": 1, "maxCurve": {"m_Curve": [key(0, 1), key(.5, 1)]}}
        self.assertEqual([round(value, 6) for value in systems.integral_range(early)], [0, 1])
        # The fixture: a 12x12x10 Box emitting at rest, sizes up to 1 (start 1 times the size curve's 1).
        self.assertEqual([round(value, 4) for value in systems.procedural_bounds(particle_system(), RENDERER)],
                         [-6.71, -6.71, -5.71, 6.71, 6.71, 5.71])
        # Speed 2 for 2 s carries the box 4 units along the shape's +Z (Box directions are (0, 0, 0)..(0, 0, 1)).
        initial = particle_system()["InitialModule"]
        moving = particle_system(InitialModule={**initial, "startSpeed": constant(2.0)})
        self.assertEqual([round(value, 4) for value in systems.procedural_bounds(moving, RENDERER)],
                         [-6.71, -6.71, -5.71, 6.71, 6.71, 9.71])
        # Without a shape the displacement runs along +Z from the origin; a pivot of 0.5 widens by
        # half the size first.
        bare = particle_system(InitialModule={**initial, "startSpeed": constant(2.0)},
                               ShapeModule={**particle_system()["ShapeModule"], "enabled": False})
        pivoted = {**RENDERER, "m_Pivot": {"x": 0, "y": .5, "z": 0}}
        self.assertEqual([round(value, 4) for value in systems.procedural_bounds(bare, pivoted)],
                         [-1.21, -1.21, -1.21, 1.21, 1.21, 5.21])
        # Stretch adds the peak speed times m_VelocityScale plus m_LengthScale times the peak start size.
        stretched = {**RENDERER, "m_RenderMode": 1, "m_VelocityScale": .5, "m_LengthScale": 3.0}
        self.assertEqual([round(value, 4) for value in systems.procedural_bounds(bare, stretched)],
                         [-4.71, -4.71, -4.71, 4.71, 4.71, 8.71])
        # Pieces whose rule is not mapped are reported, not guessed.
        for fields, reason in (({"InitialModule": {**initial, "gravityModifier": constant(.5)}}, "gravity"),
                               ({"ShapeModule": {**particle_system()["ShapeModule"], "type": 8}}, "shape type 8"),
                               ({"scalingMode": 2}, "Shape scaling mode")):
            with self.assertRaisesRegex(systems._Unsupported, reason):
                systems.procedural_bounds(particle_system(**fields), RENDERER)

    def test_align_to_direction_only_where_it_cannot_change_a_horizontal_billboard(self):
        shape = particle_system()["ShapeModule"]
        planar = {**shape, "type": 10, "alignToDirection": True, "m_Rotation": {"x": 90, "y": 30, "z": 0}}
        horizontal = Reader({**RENDERER, "m_RenderMode": 2, "m_RenderAlignment": 2})
        with mock.patch.object(systems, "_material", return_value=(dict(SURFACE), None)):
            row = systems.system({}, None, Reader(particle_system(ShapeModule=planar)), horizontal, systems._Textures(0))
            self.assertTrue(row["shape"]["alignToDirection"])
            rejected = [(Reader(particle_system(ShapeModule=planar)), Reader(RENDERER), True),
                        (Reader(particle_system(ShapeModule={**planar, "type": 5})), horizontal, True),
                        (Reader(particle_system(ShapeModule={**planar, "m_Rotation": {"x": 0, "y": 0, "z": 0}})),
                         horizontal, True),
                        (Reader(particle_system(ShapeModule={**planar, "randomDirectionAmount": .5})), horizontal, True),
                        (Reader(particle_system(ShapeModule=planar)), horizontal, False)]
            rows = []
            for particle, renderer, upright in rejected:
                with self.assertRaisesRegex(systems._Unsupported, "alignToDirection"):
                    systems.system({}, None, particle, renderer, systems._Textures(0), upright=upright)
                rows.append({"reason": "ShapeModule.alignToDirection"})
        self.assertEqual(systems.warning({"unsupported": rows}),
                         "5 original particle systems are not previewed: ShapeModule.alignToDirection x5.")

    def test_transform_scale_is_reported_for_the_scaling_mode(self):
        def walked(scaling, parent_scale, own_scale, culling=3):
            emitter = walked_node("fx/root/emitter", 1)
            emitter["components"].update(ParticleSystem=Reader(particle_system(scalingMode=scaling, cullingMode=culling)),
                                         ParticleSystemRenderer=Reader(RENDERER))
            emitter["scale"] = list(own_scale)
            rows = [walked_node("fx", None), walked_node("fx/root", 0), emitter]
            rows[1]["scale"] = list(parent_scale)
            for node in rows:
                node["authored"] = True
            return rows

        local = "non-unit transform scale (Local scaling mode)"
        cases = {(0, (2, 2, 2), (1, 1, 1)): "non-unit transform scale (Hierarchy scaling mode)",
                 (2, (1, 1, 1), (1, 1, 0)): "non-unit transform scale (Shape scaling mode)",
                 # Local mode sizes a billboard by its own scale (the display clouds' 5x3 nodes).
                 (1, (1, 1, 1), (5, 3, 1)): None, (1, (1, 1, 1), (-5, 3, 1)): local,
                 (1, (2, 2, 2), (1, 1, 1)): None, (0, (1, 1, 1), (1, 1, 1)): None}
        with mock.patch.object(systems, "_material", return_value=(dict(SURFACE), None)):
            for (scaling, parent, own), reason in cases.items():
                with mock.patch.object(systems, "_walk", return_value=walked(scaling, parent, own)):
                    row, unsupported, _ = systems.template({}, None, systems._Textures(0), 0)
                self.assertEqual([item["reason"] for item in unsupported], [reason] if reason else [])
                self.assertEqual(len(row["systems"]), 0 if reason else 1)
            # The same scaled billboard under culling that pauses it off screen is drawn: the
            # runtime replays its culling box (the fixture's Box shape is reproduced).
            for culling, own, reasons in ((0, (5, 3, 1), []), (2, (5, 3, 1), []), (1, (5, 3, 1), []), (0, (1, 1, 1), [])):
                with mock.patch.object(systems, "_walk", return_value=walked(1, (1, 1, 1), own, culling)):
                    row, unsupported, _ = systems.template({}, None, systems._Textures(0), 0)
                self.assertEqual([item["reason"] for item in unsupported], reasons)
                self.assertEqual(len(row["systems"]), 0 if reasons else 1)
            # Only billboards in local simulation space without world-space forces.
            velocity = {"enabled": True, "inWorldSpace": True, "speedModifier": constant(1.0),
                        **{name: constant(0.0) for name in ("x", "y", "z", "orbitalX", "orbitalY", "orbitalZ",
                                                            "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ", "radial")}}
            for change in ({"moveWithTransform": 1},
                           {"InitialModule": {**particle_system()["InitialModule"], "gravityModifier": constant(0.5)}},
                           {"VelocityModule": velocity}, {"renderer": {**RENDERER, "m_RenderMode": 2}}):
                rows = walked(1, (1, 1, 1), (5, 3, 1))
                renderer = change.pop("renderer", RENDERER)
                rows[2]["components"].update(ParticleSystem=Reader(particle_system(scalingMode=1, cullingMode=3, **change)),
                                             ParticleSystemRenderer=Reader(renderer))
                with mock.patch.object(systems, "_walk", return_value=rows):
                    row, unsupported, _ = systems.template({}, None, systems._Textures(0), 0)
                self.assertEqual([item["reason"] for item in unsupported], [local])

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


def walked_node(path, parent, *, active=True, kinds=(), position=(0, 0, 0)):
    components = {kind: Reader({"m_Enabled": 1}, kind) for kind in ("Transform", *kinds)}
    parts = tuple(path.split("/"))
    return {"parent": parent, "game": None, "tree": {"m_Name": parts[-1], "m_Layer": 0}, "components": components,
            "parts": parts, "path": path, "self": active, "position": list(position), "rotation": [0, 0, 0, 1],
            "scale": [1, 1, 1]}


def binding(path, type_id, attribute):
    import zlib
    return {"path": zlib.crc32(path.encode()), "typeID": type_id, "attribute": attribute, "isPPtrCurve": 0}


def controller(states=1, transitions=0, culling=0):
    state = {"data": {"m_TransitionConstantArray": [{}] * transitions,
                      "m_BlendTreeConstantArray": [{"data": {"m_NodeArray": [{"data": {"m_ClipID": 0,
                                                                                        "m_ChildIndices": []}}]}}]}}
    return {"m_Controller": {"m_LayerArray": [{"data": {"m_StateMachineIndex": 0}}],
                             "m_StateMachineArray": [{"data": {"m_DefaultState": 0, "m_AnyStateTransitionConstantArray": [],
                                                               "m_StateConstantArray": [state] * states}}]},
            "m_AnimationClips": [{"m_PathID": 2}]}, culling


class AnimatorTests(unittest.TestCase):
    """In-prefab Animators: constant curves are applied, anything time-varying is reported."""

    def test_flat_curves(self):
        self.assertEqual(systems._flat(("constant", 0.0)), 0.0)
        sentinel = -3.4e38
        self.assertEqual(systems._flat(("cubic", [(sentinel, (0, 0, 0, 1.0)), (0.0, (0, 0, 0, 1.0))])), 1.0)
        self.assertIsNone(systems._flat(("cubic", [(sentinel, (0, 0, 0, 0.0)), (2.2, (0, 0, 0, 1.0))])))
        self.assertIsNone(systems._flat(("cubic", [(0.0, (0, 0, .5, 1.0))])))
        self.assertEqual(systems._flat(("linear", [(0.0, 2.0), (1.0, 2.0)])), 2.0)
        self.assertIsNone(systems._flat(("linear", [(0.0, 2.0), (1.0, 3.0)])))
        self.assertIsNone(systems._flat(("cubic", [])))

    def test_single_state_controller_only(self):
        tree, culling = controller()
        clip = Reader({"m_Name": "clip"}, "AnimationClip")

        def local(objects, owner, ref, kind=None):
            return {1: Reader(tree, "AnimatorController"), 2: clip}.get((ref or {}).get("m_PathID"))

        with mock.patch.object(systems.title, "_local", side_effect=local):
            fields = {"m_Controller": {"m_PathID": 1}, "m_CullingMode": culling}
            self.assertEqual(systems._default_clip({}, None, fields), {"m_Name": "clip"})
            self.assertIsNone(systems._default_clip({}, None, {"m_Controller": {"m_PathID": 0}}))
            with self.assertRaisesRegex(systems._Unsupported, "culling"):
                systems._default_clip({}, None, {**fields, "m_CullingMode": 1})
            for variant, message in ((controller(states=2)[0], "several states"),
                                     (controller(transitions=1)[0], "transitions")):
                tree.clear()
                tree.update(variant)
                with self.assertRaisesRegex(systems._Unsupported, message):
                    systems._default_clip({}, None, fields)

    def template(self, walked, rows=None, clip_error=None):
        def drawn(objects, game, particle, renderer, textures, blocked=None, **_):
            if blocked:
                raise systems._Unsupported(blocked)
            return {"main": {}}

        clip = mock.Mock(side_effect=clip_error) if clip_error else mock.Mock(return_value={"m_Name": "clip"})
        with mock.patch.object(systems, "_walk", return_value=walked), \
                mock.patch.object(systems, "_default_clip", clip), \
                mock.patch.object(systems, "_bindings", return_value=rows or []), \
                mock.patch.object(systems, "system", side_effect=drawn):
            return systems.template({}, None, None, 0)

    def test_constant_curves_apply_and_time_varying_curves_are_reported(self):
        ps = ("ParticleSystem", "ParticleSystemRenderer")
        walked = [walked_node("fx", None), walked_node("fx/root", 0, kinds=("Animator",)),
                  walked_node("fx/root/hidden", 1), walked_node("fx/root/hidden/core", 2, kinds=ps),
                  walked_node("fx/root/shown", 1), walked_node("fx/root/shown/core", 4, kinds=ps),
                  walked_node("fx/root/moved", 1, kinds=ps), walked_node("fx/root/swing", 1),
                  walked_node("fx/root/swing/core", 7, kinds=ps), walked_node("fx/root/blink", 1, kinds=ps),
                  walked_node("fx/root/tint", 1, kinds=ps), walked_node("fx/root/off", 1, active=False),
                  walked_node("fx/root/off/core", 11, kinds=ps), walked_node("fx/root/sibling", 1, kinds=ps)]
        for node in walked:
            node["authored"] = node["self"] and (node["parent"] is None or walked[node["parent"]]["authored"])
        active, position, euler = systems._ACTIVE, systems._POSITION, systems._EULER
        rows = [(binding("hidden", 1, active), [0.0]), (binding("shown/core", 1, active), [1.0]),
                (binding("moved", 4, position), [1.0, 2.0, 3.0]), (binding("moved", 4, euler), [0.0, 90.0, 0.0]),
                (binding("swing", 4, euler), [0.0, None, 0.0]), (binding("blink", 1, active), [None]),
                (binding("tint", 199, 822146758), [0.5]), (binding("off", 1, active), [1.0]),
                (binding("missing", 1, active), [0.0]), (binding("sibling", 23, 1), [None])]
        row, unsupported, notes = self.template(walked, rows)
        reasons = {item["path"]: item["reason"] for item in unsupported}
        self.assertEqual([system["path"] for system in row["systems"]],
                         ["fx/root/shown/core", "fx/root/moved", "fx/root/sibling"])
        self.assertEqual(reasons, {
            "fx/root/hidden/core": "kept inactive by the prefab Animator (the game never draws it)",
            "fx/root/swing/core": "animated by the prefab Animator (Transform)",
            "fx/root/blink": "animated by the prefab Animator (activation)",
            "fx/root/tint": "animated by the prefab Animator (ParticleSystemRenderer properties)",
            "fx/root/off/core": "activated by the prefab Animator"})
        moved = next(node for node in row["nodes"] if node["path"] == "fx/root/moved")
        self.assertEqual(moved["position"], [1.0, 2.0, 3.0])
        self.assertEqual([round(value, 6) for value in moved["rotation"]], [0, round(math.sqrt(.5), 6), 0,
                                                                          round(math.sqrt(.5), 6)])
        # The hidden node and its subtree are left out of the clone the runtime rebuilds.
        self.assertNotIn("fx/root/hidden", [node["path"] for node in row["nodes"]])
        self.assertEqual(notes, ["Animator"])

    def test_renderer_lane_families_are_reported_like_mesh_renderers(self):
        # mv_studio_prefab_animator.channels reports a mesh renderer whose _TintColor
        # binds both .xyzw and .rgba (or part of a vector); the particle renderer
        # gets the same reason instead of keeping whichever binding comes last.
        import zlib

        ps = ("ParticleSystem", "ParticleSystemRenderer")
        walked = [walked_node("fx", None), walked_node("fx/root", 0, kinds=("Animator",)),
                  walked_node("fx/root/both", 1, kinds=ps), walked_node("fx/root/part", 1, kinds=ps),
                  walked_node("fx/root/whole", 1, kinds=ps)]
        for node in walked:
            node["authored"] = True

        def lane(path, name, index):
            item = binding(path, 199, (zlib.crc32(name.encode()) & 0x0FFFFFFF) | (index << 28))
            return {**item, "customType": 22}

        moving = ("linear", [(0.0, 0.0), (1.0, 1.0)])
        rows = [*[(lane("both", "_TintColor", index), [None], [moving]) for index in range(4)],
                *[(lane("both", "_TintColor", 4 + index), [None], [moving]) for index in range(4)],
                *[(lane("part", "_MainTex_ST", index), [None], [moving]) for index in range(2)],
                *[(lane("whole", "_TintColor", 4 + index), [None], [moving]) for index in range(4)]]
        clip = {"m_Name": "clip", "m_MuscleClip": {"m_StartTime": 0.0, "m_StopTime": 1.0, "m_LoopTime": 1}}

        def drawn(objects, game, particle, renderer, textures, blocked=None, **_):
            if blocked:
                raise systems._Unsupported(blocked)
            return {"main": {}}

        with mock.patch.object(systems, "_walk", return_value=walked), \
                mock.patch.object(systems, "_default_clip", return_value=clip), \
                mock.patch.object(systems, "_bindings", return_value=rows), \
                mock.patch.object(systems, "system", side_effect=drawn):
            row, unsupported, _ = systems.template({}, None, None, 0)
        self.assertEqual({item["path"]: item["reason"] for item in unsupported}, {
            "fx/root/both": "Animator animates _TintColor through both its vector and color lanes",
            "fx/root/part": "Animator animates part of _MainTex_ST"})
        self.assertEqual([system["path"] for system in row["systems"]], ["fx/root/whole"])
        channel, = row["animation"]["channels"]
        self.assertEqual((channel["kind"], channel["system"]), ("tint", 0))

    def test_inactive_prefab_root_is_activated_by_the_clip(self):
        ps = ("ParticleSystem", "ParticleSystemRenderer")
        walked = [walked_node("fx", None, active=False, kinds=ps), walked_node("fx/root", 0, kinds=ps),
                  walked_node("fx/root/off", 1, active=False, kinds=ps)]
        with mock.patch.object(systems, "_components", side_effect=lambda objects, game: (game["tree"], game["components"])), \
                mock.patch.object(systems.title, "_local", return_value=None), \
                mock.patch.object(systems.viewer, "_remaining"):
            # _walk over a one-node stand-in: the root keeps m_IsActive=0 but counts as active.
            node = {"tree": {"m_Name": "fx", "m_IsActive": 0},
                    "components": {"Transform": Reader({"m_LocalPosition": {"x": 0, "y": 0, "z": 0},
                                                        "m_LocalRotation": {"x": 0, "y": 0, "z": 0, "w": 1},
                                                        "m_LocalScale": {"x": 1, "y": 1, "z": 1},
                                                        "m_Children": []}, "Transform")}}
            root, = systems._walk({}, node, 0)
            self.assertEqual((root["self"], root["authored"]), (False, True))
        for node in walked:
            node["authored"] = node["parent"] is None or (node["self"] and walked[node["parent"]]["authored"])
        row, unsupported, _ = self.template(walked)
        # OnBehaviourPlay activates the clone root; inactive children stay off.
        self.assertEqual([system["path"] for system in row["systems"]], ["fx", "fx/root"])
        self.assertEqual(unsupported, [])

    def test_unread_controller_reports_every_system_below_it(self):
        ps = ("ParticleSystem", "ParticleSystemRenderer")
        walked = [walked_node("fx", None, kinds=ps), walked_node("fx/root", 0, kinds=("Animator",)),
                  walked_node("fx/root/core", 1, kinds=ps)]
        for node in walked:
            node["authored"] = True
        row, unsupported, notes = self.template(
            walked, clip_error=systems._Unsupported("Animator controller with several states"))
        self.assertEqual([system["path"] for system in row["systems"]], ["fx"])
        self.assertEqual(unsupported, [{"path": "fx/root/core", "reason": "under prefab animation that is not "
                                        "previewed (Animator controller with several states)"}])
        self.assertEqual(notes, ["Animator"])
        legacy = [walked_node("fx", None), walked_node("fx/root", 0, kinds=("Animation",)),
                  walked_node("fx/root/core", 1, kinds=ps)]
        for node in legacy:
            node["authored"] = True
        row, unsupported, notes = self.template(legacy)
        self.assertEqual(row["systems"], [])
        self.assertEqual(unsupported, [{"path": "fx/root/core", "reason": "under prefab animation that is not "
                                        "previewed (legacy Animation component)"}])
        self.assertEqual(notes, ["Animation"])


_CENSUS = Path(os.environ.get(
    "ELICHIKA_MV_CENSUS_BUNDLES",
    "/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/coverage/bundle-census/bundles"))
_TIMELINE_12035 = _CENSUS / "android" / "live_timeline-bcc02fa813.unity3d"
_TIMELINE_12036 = _CENSUS / "android" / "live_timeline-9b87bf5145.unity3d"


@unittest.skipUnless(_TIMELINE_12035.is_file() and os.environ.get("ELICHIKA_TEXTURE65_BIN"),
                     "Set ELICHIKA_MV_CENSUS_BUNDLES and ELICHIKA_TEXTURE65_BIN for the original 12035 timeline")
class OriginalTimelineTests(unittest.TestCase):
    def test_12035_android_cues_templates_and_textures(self):
        from PIL import Image
        from webtools.core import mv_studio_timeline

        parsed = mv_studio_timeline.parse_timeline(_TIMELINE_12035.read_bytes(), "12035", preview_particle_systems=True)
        source = parsed["stageParticleSystems"]
        # Every system is drawn. The light beams (Local billboards tilted on Y, one on a
        # 1.1x1.1 node) and the display clouds (View billboards on 5x3..7x3 nodes, the side
        # ones tilted on Y) are looping procedural Automatic systems: the runtime replays
        # their culling from the main camera with their culling box.
        self.assertEqual(source["unsupported"], [])
        self.assertEqual(len(source["cues"]), 14)
        names = {template["name"]: template for template in source["templates"]}
        self.assertEqual(len(names), 10)
        rows = {row["path"].split("/root/", 1)[1]: row for name in ("fx_dis_par_so2035_02", "fx_par_so2035_04")
                for row in names[name]["systems"]}
        self.assertEqual(sorted(rows), ["light_01", "light_02", "main_dis/cloud_L", "main_dis/cloud_R",
                                        "sub_dis_L/cloud_L", "sub_dis_L/cloud_R", "sub_dis_R/cloud_L", "sub_dis_R/cloud_R"])
        for path, row in rows.items():
            self.assertTrue(row["culling"]["pauses"], path)
            self.assertTrue(row["culling"]["procedural"], path)
            self.assertEqual(row["culling"]["uniform"], path.startswith(("main_dis", "sub_dis")), path)
        # Size 17 billboards, no motion: 17 * 0.71 on every side.
        self.assertEqual([round(value, 4) for value in rows["light_01"]["culling"]["bounds"]], [-12.07] * 3 + [12.07] * 3)
        # A 1-unit cloud drifting along +X by the integral of its velocity curve (0.0239 to 0 over 10 s).
        self.assertEqual([round(value, 4) for value in rows["main_dis/cloud_L"]["culling"]["bounds"]],
                         [-.71, -.71, -.71, .8296, .71, .71])
        # 67 of the 93 systems are looping procedural Automatic systems; all have a culling box.
        culled = [row for template in names.values() for row in template["systems"] if row["culling"]["pauses"]]
        self.assertEqual((len(culled), sum(1 for row in culled if row["culling"]["bounds"])), (67, 67))
        # fx_flo_so2035_03 holds 35 systems, but 20 sit under inactive GameObjects that no clip
        # or Animator activates, so the clone never plays them.
        self.assertEqual({name: len(row["systems"]) for name, row in names.items() if name.startswith("fx_flo")},
                         {"fx_flo_so2035_01": 24, "fx_flo_so2035_02": 26, "fx_flo_so2035_03": 15})
        sparks = [cue for cue in source["cues"] if source["templates"][cue["template"]]["name"] == "fx_par_so2035_03"]
        self.assertEqual([cue["offset"] for cue in sparks], [[0.0, -1.8200000524520874, 8.0]] * 2)
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

    @unittest.skipUnless(_TIMELINE_12036.is_file(), "the original 12036 timeline is not available")
    def test_12036_android_animator_cores(self):
        from webtools.core import mv_studio_timeline

        parsed = mv_studio_timeline.parse_timeline(_TIMELINE_12036.read_bytes(), "12036", preview_particle_systems=True)
        source = parsed["stageParticleSystems"]
        drawn = {template["name"]: [row["path"].split("/root/", 1)[1] for row in template["systems"]]
                 for template in source["templates"]}
        # Each laser prefab's Animator holds constant m_IsActive curves on its cores:
        # only one joint pair stays on (the others are inactive in the prefab or kept off).
        self.assertEqual(drawn["fx_par_so2036_06"], ["joint_all/Joint_root_03/L/core", "joint_all/Joint_root_03/R/core"])
        self.assertEqual(drawn["fx_par_so2036_07"], ["joint_all/Joint_root_02/L/core", "joint_all/Joint_root_02/R/core"])
        self.assertEqual(drawn["fx_par_so2036_08"], ["joint_all/Joint_root_01/L/core", "joint_all/Joint_root_01/R/core"])
        reasons = {}
        for row in source["unsupported"]:
            reasons.setdefault(row["reason"], []).append(row["path"])
        hidden = reasons["kept inactive by the prefab Animator (the game never draws it)"]
        self.assertEqual(sorted(hidden), sorted(
            f"fx_par_so2036_0{prefab}/root/joint_all/Joint_root_0{joint}/{side}/core"
            for prefab, joints in ((6, (1, 2)), (7, (1, 3))) for joint in joints for side in "LR"))
        # Clouds the Animator blinks are reported, not drawn statically.
        self.assertNotIn("fx_dis_par_so2036_06", drawn)
        self.assertEqual(len(reasons["animated by the prefab Animator (activation)"]), 4)
        self.assertNotIn("animated by the prefab Animator (Transform)", reasons)
        # The dragon's Animator moves its local-space emitter: it is drawn with that curve.
        # The clouds beside it are Local billboards on scaled nodes under looping Automatic
        # culling; the runtime replays it from their culling box, so they are drawn too.
        self.assertEqual(sorted(drawn["fx_dis_par_so2036_05"]), ["kumo_01", "kumo_02", "kumo_03", "kumo_04", "ryuu_01"])
        self.assertFalse(any("culling" in reason for reason in reasons))
        dragon = next(template for template in source["templates"] if template["name"] == "fx_dis_par_so2036_05")
        self.assertEqual(dragon["animation"]["clips"],
                         [{"name": "clip_dis_so2036_02", "start": 0.0, "duration": 4.0, "loop": True}])
        # The same clip moves the dragon and the four clouds (their culling boxes follow per frame).
        channels = dragon["animation"]["channels"]
        self.assertEqual([(dragon["nodes"][row["node"]]["path"].rsplit("/", 1)[1], row["kind"], row["clip"]) for row in channels],
                         [(name, "translation", 0) for name in ("kumo_01", "kumo_02", "kumo_03", "kumo_04", "ryuu_01")])
        self.assertTrue(all([curve[0] for curve in row["curves"]] == ["cubic"] * 3 for row in channels))


if __name__ == "__main__":
    unittest.main()
