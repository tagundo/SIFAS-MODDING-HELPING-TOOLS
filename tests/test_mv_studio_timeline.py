"""Native MV descriptors and copy-only edits; original samples are optional."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import os
import time
import unittest
import zipfile

from webtools.core import mv_studio_timeline as studio

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))


def legacy_zxy_quaternion(values, euler=False, order=None):
    """model_animation._quaternion as 998b326 had it: every Euler rotation composed in ZXY, whatever its order."""
    import math
    from webtools.core import model_animation as animation

    if euler:
        x, y, z = (math.radians(value) * .5 for value in values)
        values = animation._multiply(animation._multiply((0, math.sin(y), 0, math.cos(y)), (math.sin(x), 0, 0, math.cos(x))),
                                     (0, 0, math.sin(z), math.cos(z)))
    length = math.sqrt(sum(value * value for value in values))
    x, y, z, w = (value / length for value in values)
    return [x, -y, -z, w]


def rotation_degrees(a, b):
    import math
    return math.degrees(2 * math.acos(min(1., abs(sum(x * y for x, y in zip(a, b))))))


class TimelineContractTests(unittest.TestCase):
    def test_non_timeline_input_has_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "UnityFS live timeline"):
            studio.parse_timeline(b"not a bundle", "invalid.unity")

    def test_unmodified_native_output_is_the_same_blob(self):
        raw = b"preserve source file bytes"
        original = {"duration": 0, "tracks": [], "warnings": []}
        self.assertIs(studio.edit_timeline(raw, original, deepcopy(original)), raw)

    def test_legacy_emissive_track_preserves_clip_edits_and_restores_mix_metadata(self):
        original_event = {
            "id": "stage:0", "start": 0, "duration": 6, "label": "Emissive",
            "values": {"asset": "bundle:2", "playableClass": "LiveStageEmissiveClip",
                       "color": {"r": 1, "g": 1, "b": 1, "a": 1}, "intensity": 1.,
                       "mixIn": [{"time": 0., "value": 0.}, {"time": 1., "value": 1.}]},
            "editableValues": ["color", "intensity"],
        }
        track = {"id": "stage", "nativeClass": "LiveStageEmissiveTrack", "kind": "lighting",
                 "binding": "/EntryPoint/Live/Stages/MainStage/Model", "events": [original_event]}
        old = deepcopy(track)
        old["kind"] = "effects"
        old_event = old["events"][0]
        old_event["start"] = 1.25
        old_event["values"].pop("mixIn")
        old_event["editableValues"] = []

        restored, = studio.restore_emissive_track_metadata([old], [track])
        self.assertEqual(restored, {**track, "events": [{**original_event, "start": 1.25}]})
        self.assertEqual(old["kind"], "effects")
        self.assertEqual(old_event["editableValues"], [])
        self.assertNotIn("mixIn", old_event["values"])

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

    @staticmethod
    def euler_camera(order, eulers, rate=60.):
        """A full native shot: dense position, Euler (customType = RotationOrder) and FOV samples."""
        rows = [{"path": 0, "typeID": 4, "attribute": 1, "customType": 0, "isPPtrCurve": 0},
                {"path": 0, "typeID": 4, "attribute": 4, "customType": order, "isPPtrCurve": 0},
                {"path": 0, "typeID": 114, "attribute": studio._FOV, "customType": 0, "isPPtrCurve": 0}]
        samples = [value for index, euler in enumerate(eulers) for value in (index * .1, 1.5, -4., *euler, 30. + index)]
        span = (len(eulers) - 1) / rate
        return {"m_SampleRate": rate, "m_ClipBindingConstant": {"genericBindings": rows}, "m_MuscleClip": {
            "m_StartTime": 0., "m_StopTime": span, "m_Clip": {"data": {
                "m_StreamedClip": {"curveCount": 0, "data": []}, "m_ConstantClip": {"data": []},
                "m_DenseClip": {"m_CurveCount": 7, "m_FrameCount": len(eulers), "m_SampleRate": rate,
                                "m_BeginTime": 0., "m_SampleArray": samples}}}}}

    @staticmethod
    def camera_points(tree):
        span = tree["m_MuscleClip"]["m_StopTime"]
        return studio._camera_frames(SimpleNamespace(read_typetree=lambda: tree), {}, span, None, 10_000)

    def test_camera_euler_binding_uses_its_unity_rotation_order(self):
        import math
        from webtools.core import model_animation as animation

        def unity(order, euler):  # Unity-handed quaternion of the Euler angles in that order.
            return list(animation.unity_euler_quaternion(euler, order))

        eulers = [[10., 70., -40.], [12., 68., -35.]]
        for order in (0, 4):
            with self.subTest(order=order):
                tree = self.euler_camera(order, eulers)
                self.assertEqual(studio._camera_channels(tree, None)["eulerOrder"], order)
                for point, euler in zip(self.camera_points(tree), eulers):
                    expected = unity(order, euler)
                    self.assertGreater(abs(sum(a * b for a, b in zip(point["rotation"], expected))), 1 - 1e-12)
        # SIFAS cameras bind customType 0: XYZ is q = qZ*qY*qX, which differs from the ZXY default here.
        xyz, zxy = unity(0, eulers[0]), unity(4, eulers[0])
        self.assertLess(abs(sum(a * b for a, b in zip(xyz, zxy))), math.cos(math.radians(1)))
        for invalid in (6, 2.5):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Euler rotation order"):
                studio._camera_channels(self.euler_camera(invalid, eulers), None)

    def test_camera_point_edits_write_euler_samples_in_the_binding_order(self):
        import math
        import random
        rng = random.Random(7)
        # A sweep through the XYZ gimbal region and across +-180 degrees.
        eulers = [[170. + 4 * index, 60. + 2.5 * index, -175. - 3 * index] for index in range(16)]
        eulers += [[rng.uniform(-170, 170), rng.uniform(-80, 80), rng.uniform(-170, 170)] for _ in range(8)]
        for order in (0, 4):
            with self.subTest(order=order):
                tree = self.euler_camera(order, eulers)
                span = tree["m_MuscleClip"]["m_StopTime"]
                before = self.camera_points(tree)
                after = deepcopy(before)
                for point in after:
                    point["fov"] += 1
                studio._write_camera(tree, {}, {"duration": span, "values": {"keyframes": before}},
                                     {"duration": span, "values": {"keyframes": after}})
                written = self.camera_points(tree)
                for old, new in zip(after, written):
                    self.assertGreater(abs(sum(a * b for a, b in zip(old["rotation"], new["rotation"]))), 1 - 1e-12)
                    self.assertAlmostEqual(new["fov"], old["fov"], places=9)
                samples = tree["m_MuscleClip"]["m_Clip"]["data"]["m_DenseClip"]["m_SampleArray"]
                angles = [samples[index * 7 + 3:index * 7 + 6] for index in range(len(eulers))]
                # Linear interpolation between dense samples never takes the long way round.
                self.assertLess(max(abs(b - a) for first, second in zip(angles, angles[1:])
                                    for a, b in zip(first, second)), 181)
                # Authored steps are 2.5-4 degrees. Exactly at the XYZ gimbal (y = 90) only x - z is defined:
                # the writer keeps x and the next sample catches up with one doubled step.
                self.assertLess(max(abs(b - a) for first, second in zip(angles[:16], angles[1:16])
                                    for a, b in zip(first, second)), 8.5)

    def legacy_camera_fixture(self):
        """Two native XYZ camera shots: their parsed track, the same track as 998b326 saved it, and the bundle objects."""
        import random
        from webtools.core import model_animation as animation

        rng = random.Random(11)
        trees, clips, events, objects = [], [], [], {}
        for index in range(2):
            eulers = [[rng.uniform(-60, 60), rng.uniform(-80, 80), rng.uniform(-40, 40)] for _ in range(9)]
            tree = self.euler_camera(0, eulers)
            span = tree["m_MuscleClip"]["m_StopTime"]
            trees.append(tree)
            clips.append({"m_Start": index * 2., "m_Duration": span})
            objects[("cab-x", 20 + index)] = SimpleNamespace(type=SimpleNamespace(name="AnimationClip"),
                                                             read_typetree=lambda tree=tree: deepcopy(tree))
            events.append({"id": f"cab-x:5:{index}", "start": index * 2., "duration": span, "label": f"Shot {index}",
                           "values": {"asset": f"cab-x:{10 + index}", "playableClass": "AnimationPlayableAsset",
                                      "animation": f"cab-x:{20 + index}", "animationName": f"cam{index}",
                                      "keyframes": self.camera_points(tree)},
                           "editableValues": ["keyframes"]})
        objects[("cab-x", 5)] = SimpleNamespace(type=SimpleNamespace(name="MonoBehaviour"),
                                                read_typetree=lambda: {"m_Clips": deepcopy(clips)})
        native = {"id": "cab-x:5", "kind": "camera", "label": "CameraMotion/Camera1", "events": events,
                  "nativeClass": "AnimationTrack", "muted": False, "binding": "/EntryPoint/Live/Cameras/MainCamera"}
        legacy = deepcopy(native)
        with patch.object(animation, "_quaternion", legacy_zxy_quaternion):
            for event, tree in zip(legacy["events"], trees):
                event["values"]["keyframes"] = self.camera_points(tree)
        # Python and browser JSON both round-trip these doubles exactly.
        return trees, native, json.loads(json.dumps(legacy)), objects

    def test_legacy_unedited_camera_points_export_the_original_bytes(self):
        trees, native, legacy, objects = self.legacy_camera_fixture()
        self.assertGreater(max(rotation_degrees(a["rotation"], b["rotation"]) for event, old in zip(native["events"], legacy["events"])
                               for a, b in zip(event["values"]["keyframes"], old["values"]["keyframes"])), 1)
        bloom = {"id": "cab-x:7", "kind": "bloom", "label": "Bloom", "events": [], "nativeClass": "BloomTrack", "muted": False}
        saved = [legacy, bloom]
        snapshot = deepcopy(saved)
        with patch.object(studio, "_read", return_value=(None, objects, {})):
            self.assertEqual(studio.restore_legacy_camera_keyframes(b"raw", "x", saved, [native, bloom]), [native, bloom])
        self.assertEqual(saved, snapshot)
        with patch.object(studio, "_read") as read:
            current = [deepcopy(native), bloom]
            self.assertIs(studio.restore_legacy_camera_keyframes(b"raw", "x", current, [native, bloom]), current)
        read.assert_not_called()

        raw = b"native timeline bytes"
        original = {"duration": 4., "tracks": [native, bloom], "warnings": []}
        with patch.object(studio, "parse_timeline", return_value=original), \
                patch.object(studio, "_read", return_value=(None, objects, {})):
            self.assertIs(studio.export_timeline(raw, "x", deepcopy([native, bloom])), raw)
            self.assertIs(studio.export_timeline(raw, "x", deepcopy(saved)), raw)

    def test_legacy_camera_edit_is_kept_and_written_in_the_binding_order(self):
        trees, native, legacy, objects = self.legacy_camera_fixture()
        edited = deepcopy(legacy)
        points = edited["events"][1]["values"]["keyframes"]
        points[3]["fov"] += 2.
        points[5]["rotation"] = [0., .6, 0., .8]
        with patch.object(studio, "_read", return_value=(None, objects, {})):
            restored, = studio.restore_legacy_camera_keyframes(b"raw", "x", [edited], [native])
        self.assertEqual(restored["events"][0], native["events"][0])
        expected = deepcopy(native["events"][1])
        expected["values"]["keyframes"][3]["fov"] += 2.
        expected["values"]["keyframes"][5]["rotation"] = [0., .6, 0., .8]
        self.assertEqual(restored["events"][1], expected)

        written = deepcopy(trees[1])
        studio._write_camera(written, {}, native["events"][1], restored["events"][1])
        for point, want in zip(self.camera_points(written), expected["values"]["keyframes"]):
            self.assertLess(rotation_degrees(point["rotation"], want["rotation"]), 1e-5)
            self.assertAlmostEqual(point["fov"], want["fov"], places=9)
        # Without the migration the edited shot's untouched points would bake the old ZXY error into the clip.
        baked = deepcopy(trees[1])
        studio._write_camera(baked, {}, native["events"][1], edited["events"][1])
        self.assertGreater(max(rotation_degrees(point["rotation"], want["rotation"]) for point, want in
                               zip(self.camera_points(baked), expected["values"]["keyframes"])), 1)

    def test_stage_motion_euler_channels_carry_the_binding_rotation_order(self):
        from webtools.core import mv_studio_stage_motion as stage
        bindings = {"genericBindings": []}
        tree = {"m_ClipBindingConstant": bindings, "m_MuscleClip": {
            "m_StartTime": 0, "m_StopTime": 2, "m_Clip": {"m_ConstantClip": {"data": [30., 60., 90.]}}}}
        reader = SimpleNamespace(read_typetree=lambda: tree)
        for order in (0, 4):
            with self.subTest(order=order):
                bindings["genericBindings"] = [{"path": 77, "typeID": 4, "attribute": 4, "customType": order,
                                                "isPPtrCurve": 0, "script": {"m_FileID": 0, "m_PathID": 0}}]
                declaration, _ = stage._read_clip(reader, None)
                self.assertEqual(declaration["channels"], [{"path": 77, "kind": "euler", "rotationOrder": order,
                                                            "curves": [("constant", 30.), ("constant", 60.), ("constant", 90.)]}])

    def test_overlay_material_distinguishes_native_color_and_vector_lanes(self):
        from webtools.core.mv_studio_stage_overlay import material_channels
        from zlib import crc32

        def binding(path, property_name, channel, renderer_class=23):
            return {"path": path, "typeID": renderer_class, "customType": 22, "isPPtrCurve": 0,
                    "script": {"m_FileID": 0, "m_PathID": 0},
                    "attribute": (crc32(property_name) & 0x0FFFFFFF) | (channel << 28)}

        # Aion's second flare uses color lanes 4–7 plus four ordinary UV lanes.
        lanes = [binding(3121091544, b"_TintColor", i) for i in range(4, 8)]
        uv = [binding(3121091544, b"_MainTex_ST", i) for i in range(4)]
        curves = [("constant", value) for value in range(8)]
        decoded, count = material_channels(lanes + uv, curves, lambda _: 1)
        self.assertEqual(count, 8)
        self.assertEqual(decoded, [
            {"path": 3121091544, "kind": "overlayTint", "curves": curves[:4]},
            {"path": 3121091544, "kind": "overlayUV", "curves": curves[4:]},
        ])
        vectors = [binding(3121091544, b"_TintColor", i) for i in range(4)]
        for unsupported in (lanes[:-1] + vectors[-1:], lanes + vectors,
                            [binding(3121091544, b"_MainTex_ST", i) for i in range(4, 8)]):
            self.assertEqual(material_channels(unsupported, curves, lambda _: 1), ([], 0))
        skin_tint = [binding(279126303, b"_TintColor", i, 137) for i in range(4)]
        decoded, count = material_channels(lanes + skin_tint, curves, lambda _: 1)
        self.assertEqual(count, 8)
        self.assertEqual(decoded[1], {
            "path": 279126303, "kind": "overlayTint", "curves": curves[4:], "rendererClass": 137,
        })
        for unsupported in (
                skin_tint[:3] + [binding(279126303, b"_TintColor", 3)],
                skin_tint + [binding(279126303, b"_MainTex_ST", i) for i in range(4)],
                skin_tint[:3] + [{**skin_tint[-1], "script": {"m_FileID": 0, "m_PathID": 99}}],
        ):
            self.assertEqual(material_channels(unsupported, curves, lambda _: 1), ([], 0))

    def test_soft_billboard_material_requires_complete_world_color_and_typed_scalar_lanes(self):
        from webtools.core import mv_studio_stage_motion as stage
        from zlib import crc32

        def binding(path, name, lane, renderer_class=23):
            return {"path": path, "typeID": renderer_class, "customType": 22, "isPPtrCurve": 0,
                    "script": {"m_FileID": 0, "m_PathID": 0},
                    "attribute": (crc32(name.encode()) & 0x0fffffff) | (lane << 28)}

        fog, floor = 108786859, 3192247854
        color = [binding(fog, "_Color", lane) for lane in (3, 1, 0, 2)]
        props = ("_Density", "_MoveIntensity", "_AlphaAnimPower", "_AlphaAnimScale",
                 "_SizeStartX", "_SizeStartY", "_SizeEndX", "_SizeEndY", "_SizeRandom")
        scalars = [binding(fog, name, 8) for name in props]
        tint = [binding(floor, "_TintColor", lane) for lane in range(4)]
        bindings = {"genericBindings": []}
        constants = {"data": []}
        tree = {"m_ClipBindingConstant": bindings, "m_MuscleClip": {
            "m_StartTime": 0, "m_StopTime": 2, "m_Clip": {"m_ConstantClip": constants},
        }}
        reader = SimpleNamespace(read_typetree=lambda: tree)

        def read(rows, **scope):
            bindings["genericBindings"] = rows
            constants["data"] = list(range(len(rows)))
            return stage._read_clip(reader, None, **scope)

        declaration, _ = read(color + scalars + tint, world=True)
        self.assertEqual(declaration["channels"], [
            {"path": fog, "kind": "overlayColor", "curves": [("constant", lane) for lane in (2, 1, 3, 0)]},
            *[{"path": fog, "kind": "overlayScalar", "property": name, "curves": [("constant", lane)]}
              for lane, name in enumerate(props, 4)],
            {"path": floor, "kind": "overlayTint", "curves": [("constant", lane) for lane in range(13, 17)]},
        ])
        # The layer-20 overlay pass holds no soft billboard: those curves are dropped and reported.
        declaration, _ = read(color + scalars + tint, overlay=True)
        self.assertEqual([channel["kind"] for channel in declaration["channels"]], ["overlayTint"])
        self.assertEqual(len(declaration["droppedChannels"]), 1 + len(props))
        for invalid in (color + scalars + scalars[:1], color + [binding(fog, "_Density", 8, 137)],
                        color + [{**scalars[0], "script": {"m_FileID": 0, "m_PathID": 77}}]):
            self.assertIsNone(read(invalid + tint, world=True))
        # An incomplete color, a scalar in another lane or an unknown float is dropped, not the clip.
        for partial, kept in ((color[1:] + scalars, len(props)), (color + [binding(fog, "_Density", 9)], 1),
                              (color + [binding(fog, "_UnknownFloat", 8)], 1)):
            declaration, _ = read(partial + tint, world=True)
            self.assertEqual(len(declaration["channels"]), kept + 1)
            self.assertEqual(len(declaration["droppedChannels"]), 1)

    def test_stage_motion_rejects_partial_native_clip_playback(self):
        from webtools.core import mv_studio_stage_motion as stage

        reader = SimpleNamespace(read_typetree=lambda: {})
        data = {"start": 0, "duration": 0, "loop": False, "unsupported": 0, "tracks": [
            {"path": 17, "kind": "visibility", "visibilityType": "gameObject", "curves": [("constant", 1)]},
        ]}
        with patch.object(stage.animation, "decode_clip", return_value=data):
            self.assertEqual(stage._read_clip(reader, None)[0]["channels"], data["tracks"])
            for unsupported in (
                {"path": 17, "kind": "visibility", "visibilityType": "renderer", "curves": [("constant", 1)]},
                {"path": 0, "kind": "translation", "curves": [("constant", 1)] * 3},
            ):
                with self.subTest(unsupported=unsupported):
                    data["tracks"].append(unsupported)
                    self.assertIsNone(stage._read_clip(reader, None))
                    data["tracks"].pop()
            data["unsupported"] = 1
            self.assertIsNone(stage._read_clip(reader, None))

    def test_stage_animation_quality_uses_direct_native_children(self):
        from webtools.core import mv_studio_stage_motion as stage

        owner = object()
        mono = {("cab", 0): (owner, {}, "TimelineAsset")}
        for identity, name in enumerate(("StageEffect", "Expert", "Animation", "Curtain"), 1):
            mono[("cab", identity)] = owner, {"m_Name": name, "m_Parent": {"m_PathID": identity - 1}}, "GroupTrack"
        with patch.object(studio, "_pointer", side_effect=lambda _, ptr: ("cab", ptr["m_PathID"]) if ptr else None):
            self.assertEqual(stage._quality("StageEffect/Expert/Animation/Lights", parent=("cab", 3), mono=mono), "stage_animation")
            self.assertIsNone(stage._quality("StageEffect/Expert/Animation/Curtain/Track", parent=("cab", 4), mono=mono))

    def test_typed_native_overlay_uses_category_and_world_renderer_curves_need_their_own_material(self):
        from webtools.core import mv_studio_stage_motion as stage
        from zlib import crc32

        texture_tint = crc32(b"_TintColor") & 0x0FFFFFFF
        bindings = [{"path": 17, "typeID": 23, "customType": 22, "isPPtrCurve": 0,
                     "attribute": texture_tint | (lane << 28)} for lane in range(4)]
        clip = {"m_ClipBindingConstant": {"genericBindings": bindings}, "m_MuscleClip": {
            "m_StartTime": 0, "m_StopTime": 2, "m_Clip": {"m_ConstantClip": {"data": [1, .5, .25, 0]}},
        }}
        reader = SimpleNamespace(type=SimpleNamespace(name="AnimationClip"), read_typetree=lambda: clip)
        native = object()
        mono = {("cab", track_id): (native, {"m_Clips": [{}]}, "AnimationTrack") for track_id in (1, 2)}
        mono[("cab", 3)] = native, {"m_Clip": {"m_PathID": 4}}, "AnimationPlayableAsset"
        objects = {("cab", 4): reader}

        def track(track_id, category, path):
            return {"id": f"cab:{track_id}", "label": f"StageEffect/Expert/{category}/Track",
                    "binding": f"/EntryPoint/Live/Stages/MainStage/Effect/{path}", "nativeClass": "AnimationTrack",
                    "events": [{"id": f"cab:{track_id}:0", "values": {
                        "animation": "cab:4", "asset": "cab:3", "playableClass": "AnimationPlayableAsset",
                    }}]}

        overlay = track(1, "OverlayEffect", "ArbitraryPrefab/AuthoredRoot")
        world = track(2, "Animation", "WorldPrefab/Root")
        legacy = track(1, "OverlayEffect", "fx_ove_known/Effect_root")
        with patch.object(stage, "_declared", return_value=True), \
                patch.object(studio, "_pointer", side_effect=lambda _, ptr: ("cab", ptr["m_PathID"]) if ptr else None):
            for tracks in ([world, overlay], [overlay, world]):
                parsed = stage.read(objects, mono, tracks, time.monotonic() + 3)
                # MVStudioStageMaterial has no world holder for a MeshRenderer
                # _TintColor, so the world alias stays unbound.
                self.assertEqual(parsed["bindings"], [overlay["binding"]])
                self.assertEqual(parsed["quality"], {"cab:1": "stage_overlay_effect"})
                self.assertEqual(parsed["mix"], {"cab:1:0": {}})
                declared = parsed["clips"]["cab:4"]
                self.assertTrue(declared["requiresOverlayMaterial"])
                self.assertTrue(declared["sampleTimeF32"])
                self.assertEqual(declared["channels"], [{
                    "path": 17, "kind": "overlayTint",
                    "curves": [("constant", value) for value in (1, .5, .25, 0)],
                }])
            existing = stage.read(objects, mono, [legacy], time.monotonic() + 3)["clips"]["cab:4"]
            self.assertNotIn("requiresOverlayMaterial", existing)
            # Every overlay clip samples at the native normalized float time,
            # a MeshRenderer-only legacy fx_ove_*/Effect_root clip included.
            self.assertTrue(existing["sampleTimeF32"])
            for row in bindings:
                row.update(typeID=137, script={"m_FileID": 0, "m_PathID": 0})
            skinned = stage.read(objects, mono, [legacy], time.monotonic() + 3)["clips"]["cab:4"]
            self.assertTrue(skinned["requiresOverlayMaterial"])
            self.assertTrue(skinned["sampleTimeF32"])
            self.assertEqual(skinned["channels"][0]["rendererClass"], 137)
            for tracks in ([world, legacy], [legacy, world]):
                shared = stage.read(objects, mono, tracks, time.monotonic() + 3)
                self.assertEqual(set(shared["bindings"]), {world["binding"], legacy["binding"]})
                self.assertEqual(shared["mix"]["cab:2:0"], {"materialScope": "world"})
                self.assertEqual(shared["mix"]["cab:1:0"], {})
                self.assertEqual(shared["clips"]["cab:4"], skinned)
            bindings[3]["attribute"] = texture_tint | (2 << 28)
            self.assertIsNone(stage.read(objects, mono, [overlay], time.monotonic() + 3))
            soft_color = crc32(b"_Color") & 0x0fffffff
            for lane, row in enumerate(bindings):
                row.update(typeID=23, attribute=soft_color | (lane << 28))
            for tracks in ([world, legacy], [legacy, world]):
                shared = stage.read(objects, mono, tracks, time.monotonic() + 3)
                self.assertEqual(shared["bindings"], [world["binding"]])
                self.assertEqual(shared["mix"], {"cab:2:0": {"materialScope": "world"}})
                self.assertTrue(shared["clips"]["cab:4"]["requiresOverlayMaterial"])
                self.assertTrue(shared["clips"]["cab:4"]["sampleTimeF32"])

            # A world MeshRenderer _MainTex_ST curve binds to that renderer's own
            # stage material, so the world clip is selected.
            def renderer(path, name):
                return [{"path": path, "typeID": 23, "customType": 22, "isPPtrCurve": 0,
                         "attribute": (crc32(name) & 0x0FFFFFFF) | (lane << 28)} for lane in range(4)]

            clip["m_ClipBindingConstant"]["genericBindings"] = renderer(17, b"_MainTex_ST")
            for tracks in ([world, overlay], [overlay, world]):
                parsed = stage.read(objects, mono, tracks, time.monotonic() + 3)
                self.assertEqual(parsed["bindings"], [row["binding"] for row in tracks])
                self.assertEqual(parsed["quality"], {"cab:1": "stage_overlay_effect", "cab:2": "stage_animation"})
                self.assertEqual(parsed["mix"], {"cab:1:0": {}, "cab:2:0": {"materialScope": "world"}})
                declared = parsed["clips"]["cab:4"]
                self.assertTrue(declared["requiresOverlayMaterial"])
                self.assertEqual(declared["channels"], [{
                    "path": 17, "kind": "overlayUV",
                    "curves": [("constant", value) for value in (1, .5, .25, 0)],
                }])
            # With a _TintColor on a second MeshRenderer the tint has no world
            # holder, so the whole world clip stays unbound.
            clip["m_ClipBindingConstant"]["genericBindings"] = renderer(17, b"_MainTex_ST") + renderer(18, b"_TintColor")
            clip["m_MuscleClip"]["m_Clip"]["m_ConstantClip"]["data"] = [1, .5, .25, 0, 1, 1, 1, 1]
            for tracks in ([world, overlay], [overlay, world]):
                parsed = stage.read(objects, mono, tracks, time.monotonic() + 3)
                self.assertEqual(parsed["bindings"], [overlay["binding"]])
                self.assertEqual(parsed["mix"], {"cab:1:0": {}})
                self.assertEqual({row["kind"] for row in parsed["clips"]["cab:4"]["channels"]}, {"overlayUV", "overlayTint"})

    def test_resident_particle_color_requires_exact_world_skin_and_complete_lanes(self):
        from webtools.core import mv_studio_stage_motion as stage
        from zlib import crc32

        def lane(path, attr, class_id, custom):
            return {"path": path, "attribute": attr, "typeID": class_id, "customType": custom, "isPPtrCurve": 0,
                    "script": {"m_FileID": 0, "m_PathID": 0}}

        surface = [lane(27, (crc32(b"_TintColor") & 0x0fffffff) | (i << 28), 137, 22) for i in range(4)]
        colors = [lane(57, crc32(f"InitialModule.startColor.maxColor.{axis}".encode()), 198, 27) for axis in "rgba"]
        payload = {"genericBindings": []}
        constants = {"data": []}
        raw = {"m_ClipBindingConstant": payload, "m_MuscleClip": {
            "m_StartTime": 0, "m_StopTime": 2, "m_Clip": {"m_ConstantClip": constants},
        }}
        reader = SimpleNamespace(read_typetree=lambda: raw)
        for mode, values in (([0, 1, 2], [.5, .75, 1.25]), ([2, 0, 3, 1], [1.25, .5, .6, .75])):
            payload["genericBindings"] = surface + [colors[i] for i in mode]
            constants["data"] = [1, .5, .75, 0] + values
            self.assertIsNone(stage._read_clip(reader, None, overlay=True))
            declaration, cost = stage._read_clip(reader, None, world=True)
            expected = [.5, .75, 1.25] + ([.6] if len(mode) == 4 else [])
            self.assertEqual(declaration["particleStartColors"],
                             [{"path": 57, "curves": [("constant", value) for value in expected]}])
            self.assertEqual(cost, 8 + len(mode))
            with patch.object(stage, "_MAX_SCALARS", cost - 1):
                self.assertIsNone(stage._read_clip(reader, None, world=True))

        constants["data"] = [1] * 7
        for unsupported in (colors[:2] + colors[3:], colors[:2] + colors[:1],
                            colors[:2] + [{**colors[2], "script": {"m_FileID": 1, "m_PathID": 4}}]):
            payload["genericBindings"] = surface + unsupported
            self.assertIsNone(stage._read_clip(reader, None, world=True))
        payload["genericBindings"] = [{**item, "typeID": 23} for item in surface] + colors[:3]
        self.assertIsNone(stage._read_clip(reader, None, world=True))


@unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file(), "Original game samples are optional")
class LegacyCameraProjectTests(unittest.TestCase):
    """1203503 binds its camera Euler curves in XYZ; projects saved by 998b326 carry them composed in ZXY."""

    @classmethod
    def setUpClass(cls):
        from webtools.core import model_animation as animation

        cls.raw = (SAMPLES / "a-1203503-live_timeline.unity").read_bytes()
        cls.fresh = studio.parse_timeline(cls.raw, "a")
        with patch.object(animation, "_quaternion", legacy_zxy_quaternion):
            legacy = studio.parse_timeline(cls.raw, "a")
        cls.legacy = json.loads(json.dumps(legacy))  # As a saved project carries it.

    @staticmethod
    def camera(data):
        return next(track for track in data["tracks"] if track["kind"] == "camera")

    def affected(self):
        return [index for index, (fresh, legacy) in enumerate(zip(self.camera(self.fresh)["events"],
                                                                  self.camera(self.legacy)["events"])) if fresh != legacy]

    def test_unedited_legacy_project_exports_the_original_bytes(self):
        self.assertEqual(len(self.raw), 300856)
        self.assertEqual(len(self.affected()), 15)
        tracks = deepcopy(self.legacy["tracks"])
        restored = studio.restore_legacy_camera_keyframes(self.raw, "a", tracks, self.fresh["tracks"])
        self.assertEqual(restored, self.fresh["tracks"])
        self.assertEqual(studio._changes(self.fresh, {**self.fresh, "tracks": restored}), [])
        self.assertIs(studio.export_timeline(self.raw, "a", deepcopy(self.fresh["tracks"])), self.raw)
        self.assertIs(studio.export_timeline(self.raw, "a", tracks), self.raw)
        self.assertEqual(tracks, self.legacy["tracks"])

    def test_legacy_project_keeps_its_camera_edit_and_matches_a_fresh_edit(self):
        index = self.affected()[0]

        def edit(data):
            tracks = deepcopy(data["tracks"])
            point = self.camera({"tracks": tracks})["events"][index]["values"]["keyframes"][12]
            point["fov"] += 1.5
            point["position"][0] += .25
            return tracks

        fresh, legacy = edit(self.fresh), edit(self.legacy)
        restored = studio.restore_legacy_camera_keyframes(self.raw, "a", legacy, self.fresh["tracks"])
        self.assertEqual(restored, fresh)
        self.assertEqual(len(studio._changes(self.fresh, {**self.fresh, "tracks": restored})), 1)
        changed = studio.export_timeline(self.raw, "a", fresh)
        self.assertEqual(studio.export_timeline(self.raw, "a", legacy), changed)
        current = self.camera(studio.parse_timeline(changed, "a"))["events"]
        original = self.camera(self.fresh)["events"]
        self.assertEqual(current[:index] + current[index + 1:], original[:index] + original[index + 1:])
        written = current[index]["values"]["keyframes"]
        wanted = self.camera({"tracks": fresh})["events"][index]["values"]["keyframes"]
        self.assertAlmostEqual(written[12]["fov"], wanted[12]["fov"], places=4)
        self.assertAlmostEqual(written[12]["position"][0], wanted[12]["position"][0], places=4)
        self.assertLess(max(rotation_degrees(a["rotation"], b["rotation"]) for a, b in zip(written, wanted)), .01)


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

    def test_native_member_shaft_preview_binding_preserves_timeline_export(self):
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                preview = studio.parse_timeline(raw, platform, preview_member_shafts=True)
                shafts = [track for track in preview["tracks"]
                          if track["nativeClass"] == "LiveMemberSpotLightShaftTrack"]
                self.assertEqual([track["shaftSlot"] for track in shafts], [1, 2, 3])
                self.assertEqual([len(track["events"]) for track in shafts], [5, 6, 3])
                self.assertEqual([track["binding"].rsplit("/", 1)[-1] for track in shafts],
                                 ["Member1", "Member2", "Member3"])
                self.assertIs(studio.export_timeline(raw, platform, preview["tracks"]), raw)
                for shaft in shafts:
                    del shaft["shaftSlot"]
                self.assertEqual(preview, self.original[platform])

    def test_original_split_masks_and_clip_pointers_match_both_platforms(self):
        split = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_split=True)
            composition = parsed.pop("splitScreen")
            self.assertEqual(parsed, self.original[platform], "preview-only data leaves the native revision schema intact")
            self.assertEqual(len(composition["masks"]), 9)
            self.assertEqual(len(composition["events"]), 8)
            track = next(track for track in parsed["tracks"] if track["nativeClass"] == "LiveSplitScreenTrack")
            first = track["events"][0]
            self.assertAlmostEqual(first["start"], 242 / 60)
            self.assertEqual([first["values"][key] for key in ("mainCamera", "subCamera1", "subCamera2", "subCamera3")], [0, 1, 0, 0])
            mask, _, _, fourth = composition["events"][first["id"]]
            self.assertIsNone(fourth)
            self.assertEqual(mask["pointer"], first["values"]["mask1"])
            geometry = composition["masks"][mask["key"]]
            self.assertEqual(len(geometry["positions"]), 12)
            self.assertEqual(geometry["indices"], [0, 1, 2, 0, 2, 3])
            self.assertAlmostEqual(geometry["bounds"][0], 3.5, places=5)
            self.assertAlmostEqual(geometry["bounds"][1], 2.0, places=5)
            self.assertIs(studio.export_timeline(raw, platform, parsed["tracks"]), raw)
            split.append(composition)
        self.assertEqual(*split)

    def test_original_stage_animator_curves_and_infinite_holds_match_both_platforms(self):
        motion = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_stage_motion=True)
            stage = parsed.pop("stageMotion")
            self.assertEqual(parsed, self.original[platform], "stage playback must not change the native revision")
            roots = [f"/EntryPoint/Live/Stages/MainStage/Effect/lit_01/lit{group}_All" for group in "ABCD"]
            overlay = "/EntryPoint/Live/Stages/MainStage/Effect/fx_ove_so2056_01/Effect_root"
            beam = "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root"
            self.assertEqual(stage["bindings"], [*roots, beam, overlay])
            self.assertEqual(len(stage["clips"]), 16)
            self.assertEqual(len(stage["mix"]), 26)
            tracks = [track for track in parsed["tracks"] if stage["quality"].get(track["id"]) == "stage_animation"]
            self.assertEqual([track["binding"] for track in tracks], roots)
            overlay_tracks = [track for track in parsed["tracks"]
                              if stage["quality"].get(track["id"]) == "stage_overlay_effect"]
            self.assertEqual([track["binding"] for track in overlay_tracks], [overlay])
            self.assertEqual(len(overlay_tracks[0]["events"]), 1)
            beam_track, = [track for track in parsed["tracks"] if track.get("binding") == beam]
            self.assertEqual(stage["quality"][beam_track["id"]], "stage_control")
            cue, = beam_track["events"]
            beam_clip = stage["clips"][cue["values"]["animation"]]
            self.assertTrue(beam_clip["sampleTimeF32"])
            self.assertEqual(len(beam_clip["channels"]), 36)
            tint, = [channel for channel in beam_clip["channels"] if channel["kind"] == "overlayTint"]
            self.assertEqual(tint["path"], 587684620)
            self.assertEqual(len(tint["curves"]), 4)
            for track in [*tracks, *overlay_tracks, beam_track]:
                event = track["events"][-1]
                self.assertIsNone(event["values"]["postExtrapolationTime"])
                self.assertTrue(stage["mix"][event["id"]]["postInfinite"])
            self.assertEqual({channel["kind"] for clip in stage["clips"].values()
                              for channel in clip["channels"]},
                             {"euler", "overlayTint", "overlayUV", "scale", "translation", "visibility"})
            self.assertTrue(any(clip["duration"] == 0 for clip in stage["clips"].values()))
            json.dumps(stage, allow_nan=False)
            motion.append(stage)
        self.assertEqual(*motion)

    def test_saved_project_without_split_metadata_recovers_original_mask_bindings(self):
        from webtools.core import mv_studio

        project = mv_studio._blank("Older project")
        project.update(duration=self.original["a"]["duration"], tracks=deepcopy(self.original["a"]["tracks"]))
        split_track = next(track for track in project["tracks"] if track["nativeClass"] == "LiveSplitScreenTrack")
        split_track["events"][0]["start"] = 4.1
        with io.BytesIO() as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                archive.writestr("project.json", json.dumps(project))
                archive.writestr("source-timeline.unity", self.raw["a"])
            with zipfile.ZipFile(handle, "r") as archive, patch.object(mv_studio, "_register", side_effect=lambda value, source: value):
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(len(reopened["splitScreen"]["masks"]), 9)

    def test_native_world_display_title_uses_same_assets_on_both_platforms(self):
        descriptors = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_stage_title=True)
            title = parsed.pop("stageTitle")
            self.assertEqual(parsed, self.original[platform])
            cue, main = title["cues"]
            self.assertEqual({mesh["name"] for mesh in cue["meshes"]}, {"title_L", "title_R"})
            self.assertEqual({mesh["name"] for mesh in main["meshes"]}, {"title_up", "title_doun"})
            self.assertEqual({row["kind"] for row in main["animation"]["channels"]},
                             {"overlayUV", "overlayTint", "translation"})
            self.assertEqual(main["texture"], cue["texture"])
            self.assertEqual(title["particleSchema"], 2)
            self.assertEqual(len(title["textures"]), 4)
            self.assertTrue(all((texture["width"], texture["height"]) == (512, 512)
                                for texture in title["textures"]))
            track = next(track for track in parsed["tracks"] if track["id"] == cue["trackId"])
            event = next(event for event in track["events"] if event["id"] == cue["eventId"])
            self.assertAlmostEqual(event["start"], 350 / 60)
            self.assertAlmostEqual(event["start"] + event["duration"], 670 / 60)
            first, middle, last = title["particles"]
            self.assertEqual((main["trackId"], main["eventId"]), (first["trackId"], first["eventId"]))
            self.assertEqual([emitter["name"] for emitter in first["emitters"]], ["title_main"])
            red, white = middle["emitters"]
            self.assertEqual(red["lifetime"], 2.9159176349639893)
            self.assertEqual(white["lifetime"], 3.2112085819244385)
            self.assertEqual(red["size"], [18.36803436279297] * 2)
            self.assertEqual(white["size"], [18.04229736328125] * 2)
            self.assertEqual(red["color"]["rgb"], [[0, 228 / 255, 10 / 255, 56 / 255]])
            self.assertEqual(white["color"]["rgb"], [[0, 1, 1, 1]])
            self.assertEqual(red["texture"], white["texture"])
            self.assertEqual(red["atlas"], white["atlas"])
            self.assertEqual(red["atlas"]["tiles"], [2, 4])
            self.assertEqual(red["atlas"]["period"], .5)
            self.assertIsNone(red["atlas"]["row"])
            self.assertEqual({emitter["name"] for emitter in last["emitters"]},
                             {"title_main", "title_sub", "title_main_vanish", "square", "block"})
            for group, start in ((first, 350 / 60), (middle, 466 / 60), (last, 580 / 60)):
                track = next(track for track in parsed["tracks"] if track["id"] == group["trackId"])
                event = next(event for event in track["events"] if event["id"] == group["eventId"])
                self.assertAlmostEqual(event["start"], start)
            self.assertIs(studio.export_timeline(raw, platform, parsed["tracks"]), raw)
            descriptors.append(title)
        self.assertEqual(*descriptors)

    def test_native_speed_background_preserves_paired_mesh_color_and_animation(self):
        from webtools.core.model_animation import _evaluate

        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True)
                effect = parsed.pop("stageSpeedBack")
                self.assertEqual(parsed, self.original[platform])
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/light")
                self.assertEqual(event["label"], "fx_dis_so2056_09")
                self.assertAlmostEqual(event["start"], 77.05)
                self.assertAlmostEqual(event["start"] + event["duration"], 118.6166667)
                self.assertEqual((effect["duration"], effect["lifetime"]), (50, 60))
                self.assertEqual(len(effect["positions"]), 1701)
                self.assertEqual(len(effect["uv"]), 1701)
                self.assertEqual(len(effect["indices"]), 9600)
                self.assertEqual(effect["rgb"], [109, 117, 128])
                self.assertEqual(set(effect["alpha"]), {0, 7, 15, 22, 30, 38})
                self.assertEqual(effect["matrix"][::5], [2.5, 1.5, 0, 1])
                self.assertEqual([row["width"] for row in effect["texture"]],
                                 [512 >> index for index in range(10)])
                for curve, expected in zip(effect["uvCurves"], (1.535, 1, .465, 69.75)):
                    self.assertAlmostEqual(_evaluate(curve, 23.25), expected, places=6)
                stars = effect["centerStars"]
                self.assertEqual(stars["seed"], 3710075818)
                self.assertEqual((stars["size"], stars["lifetime"], stars["rate"], stars["cycle"]), (2, 1, 2, 5))
                self.assertEqual(stars["uv"], [.25, .25, 0, .25])
                self.assertAlmostEqual(stars["sizePeriod"], .2)
                self.assertEqual([row["width"] for row in stars["texture"]],
                                 [512 >> index for index in range(10)])
                moving = effect["movingCompanions"]
                self.assertEqual([row["name"] for row in moving], ["speed", "speed_R", "speed_L", "stars"])
                self.assertEqual([row["rate"] for row in moving], [250, 100, 100, 100])
                self.assertEqual([row["seed"] for row in moving], [0, 1626203053, 2207999926, 3710075818])
                self.assertEqual([row["shape"]["type"] for row in moving], [4, 10, 10, 4])
                self.assertEqual([row["uv"] for row in moving], [[.25, .25, .75, 0]] * 3 + [[.25, .25, .75, .25]])
                self.assertTrue(all("texture" not in row for row in moving))
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_display_lights_match_across_android_and_ios(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_display_lights=True)
                effect = parsed.pop("stageDisplayLights")
                self.assertEqual(parsed, self.original[platform])
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/light")
                self.assertEqual(event["label"], "fx_dis_so2056_06")
                self.assertAlmostEqual(event["start"], 2897 / 60)
                self.assertAlmostEqual(event["start"] + event["duration"], 62.95)
                self.assertEqual([row["width"] for row in effect["texture"]], [512 >> index for index in range(10)])
                emitters = {row["name"]: row for row in effect["emitters"]}
                self.assertEqual(set(emitters), {"light_up", "light_down", "light_right", "light_left", "light_L", "light_R"})
                for name, row in emitters.items():
                    side = name in {"light_L", "light_R"}
                    self.assertEqual(row["bursts"], [[0, 2], [1, 2]] if side else [[0, 1]])
                    self.assertEqual((row["speed"], row["lifetime"], row["sortBias"]), (-1 if side else 1, 4, 0))
                    self.assertNotIn("texture", row)
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_falling_effects_reuse_the_existing_paired_atlases(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_display_lights=True,
                                               preview_stage_speed_back=True, preview_stage_falling_effects=True)
                effect = parsed.pop("stageFallingEffects")
                self.assertEqual(effect["textures"], ["displayLights", "speedBackCenterStars"])
                self.assertEqual(len(parsed.pop("stageDisplayLights")["texture"]), 10)
                self.assertEqual(len(parsed.pop("stageSpeedBack")["centerStars"]["texture"]), 10)
                self.assertEqual(parsed, self.original[platform])
                emitters = {row["name"]: row for row in effect["emitters"]}
                self.assertEqual(set(emitters), {"light_big", "light_smole", "light_smole_L", "light_smole_R", "stars"})
                self.assertEqual(emitters["stars"]["rate"], 10)
                self.assertTrue(all(emitters[name]["burstPeriod"] == 1 for name in emitters if name != "stars"))
                starts = {"fx_dis_so2056_05": 670 / 60, "fx_dis_so2056_07": 62.95}
                palettes = {"fx_dis_so2056_05": [32768, 128, 170, 255], "fx_dis_so2056_07": [32768, 255, 128, 128]}
                for cue in effect["cues"]:
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertAlmostEqual(event["start"], starts[event["label"]])
                    self.assertEqual(cue["starPalette"]["rgb"][0], palettes[event["label"]])
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_stage_break_reuses_paired_atlases_and_retains_the_fracture_mesh(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_display_lights=True, preview_stage_break=True)
                effect = parsed.pop("stageBreak")
                self.assertEqual(effect["textures"][1:], ["displayLights", "speedBackCenterStars"])
                self.assertEqual([level["width"] for level in effect["textures"][0]], [512 >> i for i in range(10)])
                self.assertEqual(effect["mesh"]["color"]["start"], [95, 71, 75, 255])
                self.assertEqual(effect["mesh"]["scale"], [11, 6, 1])
                self.assertIsNone(effect["mesh"]["vertexColors"])
                self.assertEqual((len(effect["mesh"]["positions"]), len(effect["mesh"]["indices"])), (49, 216))
                roles = {row["name"]: (row["count"], row["delay"], row["texture"]) for row in effect["emitters"]}
                self.assertEqual(roles, {"flash": (1, .25, 2), "Fall": (60, .25, 2), "light_big": (8, 0, 1)})
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/break")
                self.assertAlmostEqual(event["start"], 77.05)
                self.assertAlmostEqual(event["start"] + event["duration"], 79.55)
                del parsed["stageDisplayLights"], parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_finale_floor_matches_the_paired_source_and_shares_the_star_atlas(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_finale_floor=True)
                floor = parsed.pop("stageFinaleFloor")
                stars = parsed.pop("stageSpeedBack")["centerStars"]
                self.assertEqual(floor["textures"], ["speedBackCenterStars"])
                self.assertEqual(len(stars["texture"]), 10)
                self.assertEqual(parsed, self.original[platform])
                self.assertEqual((floor["seed"], floor["rate"], floor["cycle"], floor["lifetime"]), (0, 150, 5, .5))
                self.assertEqual(floor["box"], [20, 0, 1])
                self.assertEqual(tuple(floor["speedRange"]), (15, 25))
                self.assertEqual(floor["uv"], [.25, .25, .75, 0])
                track, = [row for row in parsed["tracks"] if row["id"] == floor["trackId"]]
                event, = [row for row in track["events"] if row["id"] == floor["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Control/flo")
                self.assertAlmostEqual(event["start"], 114.5)
                self.assertAlmostEqual(event["start"] + event["duration"], 118.6166666667)
                descriptors.append(floor)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_front_spark_cues_preserve_the_distinct_seed_overrides(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_sparks_a=True)
                sparks = parsed.pop("stageSparksA")
                self.assertEqual(sparks["textures"], ["speedBackCenterStars"])
                del parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                emitter, secondary, smoke = sparks["emitters"]
                self.assertEqual(emitter["name"], "hibana_01")
                self.assertEqual(secondary["name"], "hibana_02")
                self.assertAlmostEqual(secondary["delay"], .12)
                self.assertEqual(secondary["shape"]["length"], 7)
                self.assertEqual(secondary["bursts"][0][:3], [0, 60, 3])
                self.assertAlmostEqual(secondary["bursts"][0][3], .15)
                self.assertEqual(len(secondary["size3D"]), 3)
                self.assertEqual(secondary["atlas"], {"tiles": [4, 4], "start": (0, .125)})
                self.assertAlmostEqual(secondary["minViewportWidth"], .02)
                self.assertEqual(secondary["maxViewportWidth"], 2)
                self.assertEqual(smoke["name"], "smoke")
                self.assertAlmostEqual(smoke["duration"], .3)
                self.assertEqual(smoke["rateMultiplier"], 30)
                self.assertEqual(len(smoke["startGradients"]), 2)
                self.assertEqual(smoke["sortMode"], 3)
                self.assertEqual(smoke["uv"], [.25, .25, 0, .5])
                self.assertEqual(emitter["shape"]["type"], 8)
                self.assertEqual(emitter["bursts"], [[0, 1000]])
                self.assertEqual(emitter["maxViewportWidth"], 1)
                self.assertAlmostEqual(emitter["stretch"]["velocityScale"], .025)
                self.assertEqual(emitter["uv"], [.25, .25, .75, 0])
                self.assertEqual(len(sparks["cues"]), 2)
                for index, (cue, x, y) in enumerate(zip(sparks["cues"], (7, -4), (-1, -2)), 1):
                    self.assertEqual(cue["seed"], 100 * index)
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertTrue(track["label"].endswith(f"/Control/sparks_A_{index:02}"))
                    self.assertAlmostEqual(event["start"], 77.7333333333)
                    self.assertAlmostEqual(event["start"] + event["duration"], 83.1333333333)
                    self.assertEqual(event["values"]["offset"], {"x": x, "y": y, "z": 8})
                descriptors.append(sparks)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_spark_pair_matches_the_source_and_shares_the_star_atlas(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_sparks_b=True)
                sparks = parsed.pop("stageSparksB")
                self.assertEqual(sparks["textures"], ["speedBackCenterStars"])
                del parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                self.assertEqual([row["name"] for row in sparks["emitters"]], ["grow", "hibana", "late_kirakira"])
                self.assertEqual([row["seed"] for row in sparks["emitters"]], [None, 0, None])
                glow, streak, glimmer = sparks["emitters"]
                self.assertEqual(glow["uv"], [.25, .25, 0, .5])
                self.assertEqual([burst[1] for burst in streak["bursts"]], [100, 75, 50])
                self.assertEqual(streak["stretch"]["lengthScale"], 2.5)
                self.assertEqual(glimmer["rate"], 75)
                self.assertEqual(len(sparks["cues"]), 2)
                for index, (cue, x) in enumerate(zip(sparks["cues"], (4, -4)), 1):
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertTrue(track["label"].endswith(f"/Control/sparks_B_{index:02}"))
                    self.assertAlmostEqual(event["start"], 77.4166666667)
                    self.assertAlmostEqual(event["start"] + event["duration"], 83.1333333333)
                    self.assertEqual(event["values"]["offset"], {"x": x, "y": 5.5, "z": -5})
                descriptors.append(sparks)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_roop_shares_the_paired_sphere_profile_and_borrows_the_star_atlas(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_sparks_roop=True)
                sparks = parsed.pop("stageSparksRoop")
                self.assertEqual(sparks["textures"], ["speedBackCenterStars"])
                del parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                names = [row["name"] for row in sparks["emitters"]]
                self.assertEqual(names, ["sparks_R1", "sparks_R2", "sparks_L1", "sparks_L2"])
                for row, (x, z, rate) in zip(sparks["emitters"], ((7, -4.8, 100), (9.5, -.95, 200),
                                                                (-7, -4.8, 100), (-9.5, -.95, 200))):
                    self.assertEqual(row["shape"]["type"], 0)
                    self.assertIsNone(row["seed"])
                    self.assertEqual(row["duration"], 13)
                    self.assertEqual(row["rate"], rate)
                    self.assertEqual(tuple(row["lifetime"]), (3, 2))
                    self.assertEqual(row["uv"], [.25, .25, .75, .25])
                    self.assertAlmostEqual(row["position"][0], x)
                    self.assertAlmostEqual(row["position"][1], 9.2, places=6)
                    self.assertAlmostEqual(row["position"][2], z, places=6)
                cue, = sparks["cues"]
                track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Control/sparks_roop")
                self.assertAlmostEqual(event["start"], 77.05)
                self.assertAlmostEqual(event["start"] + event["duration"], 92.8333333333)
                descriptors.append(sparks)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_title_pair_with_forced_seed_keeps_other_title_cues(self):
        from UnityPy.files.ObjectReader import ObjectReader

        track = next(track for track in self.original["a"]["tracks"] if track["label"].endswith("/Title_mainDis"))
        event = track["events"][1]
        source = int(event["values"]["asset"].rsplit(":", 1)[-1])
        read = ObjectReader.read_typetree

        def force_seed(reader, *args, **kwargs):
            tree = read(reader, *args, **kwargs)
            return {**tree, "overwriteRandomSeed": 1} if reader.path_id == source else tree

        with patch.object(ObjectReader, "read_typetree", force_seed):
            title = studio.parse_timeline(self.raw["a"], "android", preview_stage_title=True)["stageTitle"]
        self.assertEqual(len(title["cues"]), 2)
        self.assertEqual(len(title["textures"]), 3)
        self.assertEqual([group["eventId"] for group in title["particles"]],
                         [track["events"][0]["id"], track["events"][2]["id"]])

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
