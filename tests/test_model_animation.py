"""Animation curve sampling and glTF binding checks; fixtures are original data."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_animation as animation
from webtools.core import model_viewer as viewer


def words(frames):
    data = bytearray()
    for stamp, keys in frames:
        data.extend(struct.pack("<fI", stamp, len(keys)))
        for index, coefficients in keys:
            data.extend(struct.pack("<Iffff", index, *coefficients))
    return list(struct.unpack("<" + "I" * (len(data) // 4), data))


def binding(path, attribute, kind=4, custom=0):
    return dict(path=path, attribute=attribute, typeID=kind, customType=custom, isPPtrCurve=0)


def clip(bindings, *, stream=None, dense=None, constant=None, duration=1., rate=60., name="Original clip"):
    return {"m_Name": name, "m_SampleRate": rate, "m_ClipBindingConstant": {"genericBindings": bindings},
            "m_MuscleClip": {"m_StartTime": 0., "m_StopTime": duration, "m_LoopTime": False, "m_Clip": {"data": {
                "m_StreamedClip": stream or {"curveCount": 0, "data": []},
                "m_DenseClip": dense or {"m_CurveCount": 0, "m_FrameCount": 0, "m_SampleArray": []},
                "m_ConstantClip": {"data": constant or []}}}}}


def scene(trees):
    objects = [SimpleNamespace(type=SimpleNamespace(name="AnimationClip"), data=tree) for tree in trees]
    return SimpleNamespace(env=SimpleNamespace(objects=objects), name=lambda obj: obj.data["m_Name"], tree=lambda obj: obj.data)


def builder(count=4):
    glb = viewer._Glb()
    glb.doc["nodes"] = [{"name": "Original node " + str(index)} for index in range(count)]
    return glb


def values(glb, index):
    accessor = glb.doc["accessors"][index]
    view = glb.doc["bufferViews"][accessor["bufferView"]]
    size = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    start = view.get("byteOffset", 0)
    return list(struct.iter_unpack("<" + "f" * size, glb.data[start:start + accessor["count"] * size * 4]))


def hermite(stamps, rows, time):
    """glTF CUBICSPLINE evaluation (spec appendix C) of [in, value, out] rows."""
    if time <= stamps[0]:
        return rows[1]
    if time >= stamps[-1]:
        return rows[3 * len(stamps) - 2]
    index = max(index for index, stamp in enumerate(stamps) if stamp <= time)
    span = stamps[index + 1] - stamps[index]
    s = (time - stamps[index]) / span
    p0, m0, m1, p1 = rows[3 * index + 1], rows[3 * index + 2], rows[3 * index + 3], rows[3 * index + 4]
    return [(2*s**3 - 3*s**2 + 1) * a + (s**3 - 2*s**2 + s) * span * b + (-2*s**3 + 3*s**2) * d + (s**3 - s**2) * span * c
            for a, b, c, d in zip(p0, m0, m1, p1)]


def unity_streamed(frames, curve, time):
    """Independent model of libunity's streamed clip: the curve's last key at or before `time`, then
    t*(t*(t*c0 + c1) + c2) + c3 with t = time - key time (SampleClip 0x591078 / seek 0x591304)."""
    owner = None
    for stamp, keys in frames:
        if stamp <= time:
            owner = next(((stamp, c) for index, c in keys if index == curve), owner)
    stamp, (c0, c1, c2, c3) = owner
    t = 0. if stamp < -1e20 else time - stamp
    return t * (t * (t * c0 + c1) + c2) + c3


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


class AnimationTests(unittest.TestCase):
    def test_animation_rebuild_remaps_detached_shadow_geometry(self):
        glb = builder()
        glb.attribute([.25, .5], "SCALAR")  # Old animation data, no live reference.
        positions = glb.attribute([[0, 0, 0], [1, 0, 0], [0, 0, 1]], "VEC3")
        uv = glb.attribute([[0, 0], [1, 0], [0, 1]], "VEC2")
        indices = glb.attribute([0, 1, 2], "SCALAR", 5123)
        source = {"POSITION": positions, "TEXCOORD_0": uv, "indices": indices}
        glb.doc["scenes"][0]["extras"] = {"mvMemberShadow": {"schema": 1, "geometry": source}}

        rebuilt = animation.animation_candidate(glb)
        restored = rebuilt.doc["scenes"][0]["extras"]["mvMemberShadow"]["geometry"]
        self.assertEqual(list(restored.values()), [0, 1, 2])
        self.assertEqual(list(source.values()), [1, 2, 3])
        self.assertEqual(values(rebuilt, restored["POSITION"]), values(glb, positions))
        self.assertEqual(len(rebuilt.doc["bufferViews"]), 3)

    def test_full_song_float32_keys_do_not_duplicate_the_nominal_60hz_grid(self):
        duration = 125.5
        stamps = [struct.unpack("<f", struct.pack("<f", frame / 60))[0] for frame in range(7531)]
        stream = words([(stamp, [(0, (0., 0., 0., math.sin(stamp)))]) for stamp in stamps] + [(math.inf, [])])
        original = clip([binding(7, 123, 137, 20)], stream={"curveCount": 1, "data": stream}, duration=duration)
        decoded = animation.decode_clip(original)
        self.assertEqual(decoded["times"], stamps)
        self.assertEqual(decoded["times"][-1], duration)
        self.assertTrue(all(a < b for a, b in zip(decoded["times"], decoded["times"][1:])))

    def test_near_grid_authored_morph_boundaries_and_terminal_value_are_retained(self):
        name = "OriginalMouthShape"
        times = [struct.unpack("<f", struct.pack("<f", stamp))[0] for stamp in (.123456, .500004, .500008)]
        frames = [(0., [(0, (0., 0., 0., 0.))]),
                  (times[0], [(0, (0., 0., 0., 25.))]),
                  (times[1], [(0, (0., 0., 0., 100.))]),
                  (times[2], [(0, (0., 0., 0., 50.))]),
                  (1., [(0, (0., 0., 0., 0.))]), (math.inf, [])]
        tree = clip([binding(99, animation.path_hash(name), 137, 20)], stream={"curveCount": 1, "data": words(frames)})
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {}, {99: {"node": 1, "names": [name], "weights": [0.]}})
        self.assertEqual(result["warnings"], [])
        sampler = glb.doc["animations"][0]["samplers"][0]
        stamps = [row[0] for row in values(glb, sampler["input"])]
        weights = [row[0] for row in values(glb, sampler["output"])]
        for stamp, weight in zip(times, (.25, 1., .5)):
            self.assertIn(stamp, stamps)
            self.assertAlmostEqual(weights[stamps.index(stamp)], weight)
        self.assertNotIn(.5, stamps)
        self.assertEqual(stamps[-1], 1.)
        self.assertEqual(weights[-1], 0.)

    def test_unsupported_animator_parameters_are_counted_separately_from_bound_body(self):
        tree = clip([binding(1, 1), binding(1, 3431781216, 95), binding(1, 1893911870, 95)],
                    constant=[1., 2., 3., .4, .5], duration=.1)
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {1: 1})
        metadata = result["clips"][0]
        self.assertEqual(metadata["channels"], 1)
        self.assertEqual(metadata["unsupportedTracks"], 2)
        self.assertEqual(metadata["unboundTracks"], 0)
        self.assertEqual({row["attribute"] for row in metadata["unsupportedKinds"]}, {3431781216, 1893911870})
        self.assertIn("2 Animator parameter curves", result["warnings"][0]["message"])

    def test_discovery_deduplicates_real_paths_across_overlapping_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            selected, wrong = nested / "model.unity", nested / "unrelated.unity"
            selected.write_bytes(b"selected")
            wrong.write_bytes(b"candidate")
            calls = []
            def inspect(path, deadline):
                calls.append(path)
                return {101}, 0
            with patch.object(animation, "_animation_source", side_effect=inspect):
                result = animation.discover_animation_paths([str(selected)], {"library_roots": [str(root), str(nested), str(root)]}, 207, time.monotonic() + 10)
        self.assertEqual(result, [])
        self.assertEqual(calls, [str(wrong)])

    def test_discovery_prioritizes_owner_motion_and_stops_after_usable_companion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected, correct, wrong = root / "model.unity", root / "Setsuna_eye_animation.unity", root / "aaa_Chika.unity"
            for path in (selected, correct, wrong):
                path.write_bytes(b"candidate")
            with patch.object(animation, "_animation_source", return_value=({207}, 20)) as inspect:
                result = animation.discover_animation_paths([str(selected)], {"library_roots": [str(root)]}, 207, time.monotonic() + 10)
        self.assertEqual(result, [str(correct)])
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(inspect.call_args.args[0], str(correct))

    def test_renderer_visibility_has_real_step_metadata_without_skeleton_scale(self):
        data = words([(-3.4e38, [(0, (0, 0, 0, 0))]), (0, [(0, (0, 0, 0, 0))]),
                      (1, [(0, (0, 0, 0, 1))]), (math.inf, [])])
        tree = clip([binding(123, 3305885265, 25)], stream={"curveCount": 1, "data": data}, rate=4)
        glb = builder()
        glb.doc["nodes"][1]["mesh"] = 0
        result = animation.append_animations(scene([tree]), glb, {123: 2}, visibility_bindings={"renderer": {123: [1]}})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["clips"][0]["index"], None)
        self.assertEqual(result["clips"][0]["channels"], 0)
        self.assertEqual(result["clips"][0]["visibility"], [{"node": 1, "times": [0., 1.], "values": [False, True],
                                                         "interpolation": "STEP", "sourceProperty": "Renderer.m_Enabled"}])
        self.assertFalse(glb.doc.get("animations"))
        self.assertNotIn("scale", glb.doc["nodes"][2])

    def test_parent_active_and_renderer_enabled_merge_once_per_mesh_with_and(self):
        tree = clip([binding(10, 2086281974, 1), binding(20, 3305885265, 25)], constant=[0, 1], duration=.1)
        glb = builder()
        glb.doc["nodes"][1]["mesh"] = 0
        result = animation.append_animations(scene([tree]), glb, {}, visibility_bindings={"gameObject": {10: [1]}, "renderer": {20: [1]}})
        tracks = result["clips"][0]["visibility"]
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["values"], [False])
        self.assertEqual(tracks[0]["sourceProperty"], "combined_visibility")

    def test_visibility_binding_to_skeleton_bone_is_rejected(self):
        tree = clip([binding(10, 3305885265, 25)], constant=[0], duration=.1)
        result = animation.append_animations(scene([tree]), builder(), {}, visibility_bindings={"renderer": {10: [2]}})
        self.assertEqual(result["clips"], [])
        self.assertIn("never a skeleton bone", result["warnings"][0]["message"])

    def test_dense_position_and_constant_scale_bind_to_real_node(self):
        tree = clip([binding(123, 1), binding(123, 3)],
                    dense={"m_CurveCount": 3, "m_FrameCount": 3, "m_SampleRate": 2., "m_BeginTime": 0.,
                           "m_SampleArray": [0, 0, 0, 1, 2, 3, 2, 4, 6]}, constant=[1, 2, 3], rate=2)
        before = copy.deepcopy(tree)
        glb = builder()
        metadata = animation.append_animations(scene([tree]), glb, {123: 2})
        self.assertEqual(tree, before)
        self.assertEqual(metadata["clips"][0]["channels"], 2)
        self.assertEqual(metadata["warnings"], [])
        exported = glb.doc["animations"][0]
        self.assertEqual(exported["channels"][0]["target"], {"node": 2, "path": "translation"})
        self.assertEqual(values(glb, exported["samplers"][0]["output"]), [(0., 0., 0.), (-1., 2., 3.), (-2., 4., 6.)])
        # A constant channel keeps only its two end samples.
        self.assertEqual(values(glb, exported["samplers"][1]["output"]), [(1., 2., 3.)] * 2)
        self.assertEqual(values(glb, exported["samplers"][1]["input"]), [(0.,), (1.,)])
        self.assertEqual([sampler["interpolation"] for sampler in exported["samplers"]], ["LINEAR", "LINEAR"])
        accessor = glb.doc["accessors"][exported["samplers"][0]["input"]]
        self.assertEqual(accessor["min"], [0.])
        self.assertEqual(accessor["max"], [1.])
        self.assertTrue(all("target" not in glb.doc["bufferViews"][item["bufferView"]] for item in glb.doc["accessors"]))

    def test_streamed_polynomial_preserves_morph_peak_and_rest_targets(self):
        name = "EyeBlendShape.eye_facial_001"
        data = words([(-3.4e38, [(0, (0, 0, 0, 0))]), (0, [(0, (-200, 300, 0, 0))]), (1, [(0, (0, 0, 0, 100))]), (math.inf, [])])
        tree = clip([binding(99, animation.path_hash(name), 137, 20)], stream={"curveCount": 1, "data": data}, rate=4)
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {}, {99: {"node": 1, "names": [name, "Other"], "weights": [0, .2]}})
        self.assertEqual(result["warnings"], [])
        sampler = glb.doc["animations"][0]["samplers"][0]
        rows = [row[0] for row in values(glb, sampler["output"])]
        for value in rows[1::2]:
            self.assertAlmostEqual(value, .2)
        self.assertAlmostEqual(rows[2], .15625)
        self.assertAlmostEqual(rows[4], .5)
        self.assertAlmostEqual(rows[-2], 1)

    def test_clip_metadata_lists_the_morph_targets_the_source_clip_binds(self):
        # A glTF weights channel carries every target; the gaze layer needs the
        # source binding (LiveMemberEyeContact clips bind one eyelid shape).
        name = "EyeBlendShape.eye_facial_003_006_011"
        data = words([(-3.4e38, [(0, (0, 0, 0, 0))]), (0, [(0, (0, 0, 0, 100))]), (math.inf, [])])
        tree = clip([binding(99, animation.path_hash(name), 137, 20)], stream={"curveCount": 1, "data": data}, rate=4)
        glb = builder()
        names = ["EyeBlendShape.eye_facial_002", name, "EyeBlendShape.eye_facial_004"]
        result = animation.append_animations(scene([tree]), glb, {}, {99: {"node": 1, "names": names, "weights": [0, 0, 0]}})
        self.assertEqual(result["clips"][0]["morphTargets"], [{"node": 1, "indices": [1]}])
        rows = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])
        self.assertEqual([round(row[0], 6) for row in rows[-3:]], [0, 1, 0], "unbound targets keep their rest weight")
        bones = animation.append_animations(scene([clip([])]), builder(), {}, {})
        self.assertTrue(all("morphTargets" not in item for item in bones["clips"]))

    def test_unique_morph_name_can_rebind_legacy_path_but_ambiguous_name_cannot(self):
        name = "FullOriginalShapeName"
        tree = clip([binding(999, animation.path_hash(name), 137, 20)], constant=[100], duration=.1)
        first = {123: {"node": 1, "names": [name], "weights": [0]}}
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {}, first)
        self.assertEqual(result["clips"][0]["channels"], 1)
        self.assertEqual(result["warnings"][0]["code"], "animation_morph_path_rebound")
        duplicate = dict(first, other={"node": 2, "names": [name], "weights": [0]})
        result = animation.append_animations(scene([tree]), builder(), {}, duplicate)
        self.assertEqual(result["clips"], [])

    def test_euler_zxy_and_quaternion_handedness_are_normalized(self):
        q = animation._quaternion([0, 0, 90], euler=True)
        self.assertAlmostEqual(q[2], -math.sqrt(.5))
        self.assertAlmostEqual(q[3], math.sqrt(.5))
        tree = clip([binding(1, 2)], constant=[0, 0, 2, 2], duration=.1)
        glb = builder()
        animation.append_animations(scene([tree]), glb, {1: 1})
        rotations = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])
        for row in rotations:
            self.assertAlmostEqual(sum(value * value for value in row), 1., places=6)
            self.assertLess(row[2], 0)

    def test_mixed_euler_rotation_uses_unity_zxy_order_before_mirroring(self):
        import numpy as np
        x, y, z = (math.radians(value) for value in (30, 60, 90))
        rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
        ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
        rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
        quaternion = dict(zip("xyzw", animation._quaternion([30, 60, 90], euler=True)))
        actual = viewer._trs({"m_LocalRotation": quaternion})[:3, :3]
        mirror = np.diag([-1, 1, 1])
        np.testing.assert_allclose(actual, mirror @ (ry @ rx @ rz) @ mirror, atol=1e-12)

    def test_euler_binding_honours_unity_rotation_order_from_custom_type(self):
        import numpy as np
        x, y, z = (math.radians(value) for value in (30, 60, 90))
        rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
        ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
        rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
        mirror = np.diag([-1, 1, 1])
        # Unity RotationOrder names the axes in the order they apply: OrderXYZ = Rz Ry Rx.
        expected = {0: rz @ ry @ rx, 1: ry @ rz @ rx, 2: rx @ rz @ ry, 3: rz @ rx @ ry, 4: ry @ rx @ rz, 5: rx @ ry @ rz}
        for order, matrix in expected.items():
            with self.subTest(order=order):
                quaternion = dict(zip("xyzw", animation._quaternion([30, 60, 90], euler=True, order=order)))
                np.testing.assert_allclose(viewer._trs({"m_LocalRotation": quaternion})[:3, :3], mirror @ matrix @ mirror,
                                           atol=1e-12)
                tree = clip([binding(1, 4, custom=order)], constant=[30, 60, 90], duration=.1)
                self.assertEqual(animation.decode_clip(tree)["tracks"][0]["rotationOrder"], order)
                glb = builder()
                animation.append_animations(scene([tree]), glb, {1: 1})
                row = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])[0]
                np.testing.assert_allclose(viewer._trs({"m_LocalRotation": dict(zip("xyzw", row))})[:3, :3],
                                           mirror @ matrix @ mirror, atol=1e-6)
        self.assertEqual(animation._quaternion([30, 60, 90], euler=True), animation._quaternion([30, 60, 90], True, 4))
        missing = clip([dict(path=1, attribute=4, typeID=4, isPPtrCurve=0)], constant=[30, 60, 90], duration=.1)
        self.assertEqual(animation.decode_clip(missing)["tracks"][0]["rotationOrder"], 4, "Unity's default is ZXY")
        for invalid in (6, -1, 1.5, True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(animation.AnimationError, "rotation order"):
                animation.decode_clip(clip([binding(1, 4, custom=invalid)], constant=[30, 60, 90], duration=.1))

    def test_editor_euler_curves_keep_their_animation_curve_rotation_order(self):
        keys = [{"time": 0, "value": {"x": 30, "y": 60, "z": 90}}, {"time": 1, "value": {"x": 30, "y": 60, "z": 90}}]
        for order in (0, 4, None):
            curve = {"m_Curve": keys} if order is None else {"m_Curve": keys, "m_RotationOrder": order}
            tree = {"m_Name": "Editor Euler", "m_SampleRate": 4, "m_EulerCurves": [{"path": "Root/Bone", "curve": curve}]}
            with self.subTest(order=order):
                track, = animation.decode_clip(tree)["tracks"]
                self.assertEqual(track["rotationOrder"], 4 if order is None else order)
                glb = builder()
                animation.append_animations(scene([tree]), glb, {"Root/Bone": 1})
                row = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])[0]
                expected = animation._quaternion([30, 60, 90], True, track["rotationOrder"])
                for actual, wanted in zip(row, expected):
                    self.assertAlmostEqual(actual, wanted, places=6)

    def test_duplicate_clip_names_stay_independently_selectable(self):
        first = clip([binding(1, 1)], constant=[0, 0, 0], name="Authored pose")
        second = clip([binding(1, 1)], constant=[1, 0, 0], name="Authored pose")
        glb = builder()
        result = animation.append_animations(scene([first, second]), glb, {1: 1})
        self.assertEqual([item["name"] for item in result["clips"]], ["Authored pose", "Authored pose__2"])
        self.assertEqual([item["name"] for item in glb.doc["animations"]], [item["name"] for item in result["clips"]])
        self.assertEqual(values(glb, glb.doc["animations"][1]["samplers"][0]["output"])[0], (-1., 0., 0.))

    def test_identical_samples_share_storage_without_sharing_rig_channels(self):
        first = clip([binding(1, 1), binding(2, 1)], constant=[1, 2, 3, 1, 2, 3], name="First")
        second = clip([binding(1, 1)], constant=[1, 2, 4], name="Second")
        glb = builder()
        result = animation.append_animations(scene([first, second]), glb, {1: 1, 2: 2})
        self.assertEqual(result["warnings"], [])
        a, b = glb.doc["animations"]
        self.assertEqual([channel["target"]["node"] for channel in a["channels"]], [1, 2])
        self.assertEqual(a["samplers"][0], a["samplers"][1])
        shared = a["samplers"][0]
        different = b["samplers"][0]
        self.assertEqual(shared["input"], different["input"])
        self.assertNotEqual(shared["output"], different["output"])
        self.assertEqual(values(glb, shared["output"])[0], (-1., 2., 3.))
        self.assertEqual(values(glb, different["output"])[0], (-1., 2., 4.))

    def test_unsupported_visibility_consumes_its_scalar_before_transform(self):
        tree = clip([binding(2, 3305885265, 25), binding(1, 1)], constant=[1, 2, 3, 4], duration=.1)
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {1: 1})
        self.assertEqual(result["clips"][0]["channels"], 1)
        self.assertEqual(result["warnings"][0]["code"], "animation_partial")
        self.assertEqual(values(glb, glb.doc["animations"][0]["samplers"][0]["output"])[0], (-2., 3., 4.))

    def test_budget_failure_does_not_append_partial_buffer_data(self):
        tree = clip([binding(1, 1)], constant=[0, 0, 0])
        glb = builder()
        with patch.object(animation, "MAX_VALUES", 5):
            result = animation.append_animations(scene([tree]), glb, {1: 1})
        self.assertEqual(result["clips"], [])
        self.assertEqual(len(glb.data), 0)
        self.assertEqual(glb.doc["accessors"], [])
        self.assertEqual(glb.doc["bufferViews"], [])

    def test_hundreds_of_small_poses_use_shared_sample_and_channel_budgets(self):
        trees = [clip([binding(1, 1)], constant=[index / 1000, 0, 0],
                      duration=0, name=f"Original pose {index}") for index in range(400)]
        originals = copy.deepcopy(trees)
        glb = builder()
        result = animation.append_animations(scene(trees), glb, {1: 1})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["clips"]), 400)
        self.assertEqual(len(glb.doc["animations"]), 400)
        for index in (0, 96, 399):
            output = glb.doc["animations"][index]["samplers"][0]["output"]
            self.assertAlmostEqual(values(glb, output)[0][0], -index / 1000, places=6)
        self.assertEqual(trees, originals, "sampling a large bank never rewrites source curves")

    def test_shared_channel_budget_keeps_complete_prior_clips_and_reports_omissions(self):
        trees = [clip([binding(1, 1)], constant=[index, 0, 0], duration=0,
                      name=f"Original pose {index}") for index in range(3)]
        expected = builder()
        animation.append_animations(scene(trees[:1]), expected, {1: [1, 2]})
        glb = builder()
        with patch.object(animation, "MAX_CHANNELS", 3):
            result = animation.append_animations(scene(trees), glb, {1: [1, 2]})
        self.assertEqual([item["name"] for item in result["clips"]], ["Original pose 0"])
        self.assertEqual(glb.doc, expected.doc)
        self.assertEqual(glb.data, expected.data)
        self.assertEqual([item["name"] for item in result["warnings"]], ["Original pose 1", "Original pose 2"])
        self.assertTrue(all("channel limit" in item["message"] for item in result["warnings"]))

    def test_clip_metadata_limit_reports_the_exact_number_omitted(self):
        trees = [clip([binding(1, 1)], constant=[index, 0, 0], duration=0,
                      name=f"Original pose {index}") for index in range(4)]
        with patch.object(animation, "MAX_CLIPS", 2):
            result = animation.append_animations(scene(trees), builder(), {1: 1})
        self.assertEqual(len(result["clips"]), 2)
        self.assertEqual(result["warnings"][0]["code"], "animation_limit")
        self.assertIn("first 2", result["warnings"][0]["message"])
        self.assertIn("2 clips were omitted", result["warnings"][0]["message"])

    def test_malformed_counts_and_nonfinite_stream_values_are_rejected(self):
        for stream in ({"curveCount": 1, "data": words([(0, [(2, (0, 0, 0, 1))])])},
                       {"curveCount": 1, "data": words([(0, [(0, (0, 0, math.nan, 1))])])},
                       {"curveCount": animation.MAX_CURVES + 1, "data": []}):
            with self.subTest(stream=stream), self.assertRaises(animation.AnimationError):
                animation.decode_clip(clip([binding(1, 1)], stream=stream))

    def test_editor_hermite_curves_are_sampled_without_mutating_source(self):
        keys = [{"time": 0, "value": {"x": 0, "y": 0, "z": 0}, "outSlope": {"x": 0, "y": 0, "z": 0}},
                {"time": 1, "value": {"x": 1, "y": 0, "z": 0}, "inSlope": {"x": 0, "y": 0, "z": 0}}]
        tree = {"m_Name": "Original editor curve", "m_SampleRate": 4,
                "m_PositionCurves": [{"path": "Root/Bone", "curve": {"m_Curve": keys}}]}
        before = copy.deepcopy(tree)
        glb = builder()
        animation.append_animations(scene([tree]), glb, {"Root/Bone": 1})
        self.assertEqual(tree, before)
        sampler = glb.doc["animations"][0]["samplers"][0]
        self.assertEqual(sampler["interpolation"], "CUBICSPLINE")
        stamps = [row[0] for row in values(glb, sampler["input"])]
        rows = values(glb, sampler["output"])
        self.assertEqual(stamps, [0., 1.])
        self.assertAlmostEqual(hermite(stamps, rows, .25)[0], -.15625)
        self.assertAlmostEqual(hermite(stamps, rows, 1.)[0], -1.)

    @staticmethod
    def hermite_frames(curves, sentinel=True):
        """Unity-style streamed frames from Hermite keys {curve: [(time, value, inSlope, outSlope)]}."""
        stamps = {}
        for index, keys in curves.items():
            for position, (stamp, value, _, outgoing) in enumerate(keys):
                coefficients = (0., 0., 0., value)
                if position + 1 < len(keys):
                    other, next_value, incoming, _ = keys[position + 1]
                    span = other - stamp
                    coefficients = ((2*value - 2*next_value + span*(outgoing + incoming)) / span**3,
                                    (-3*value + 3*next_value - span*(2*outgoing + incoming)) / span**2, outgoing, value)
                stamps.setdefault(f32(stamp), []).append((index, tuple(f32(c) for c in coefficients)))
        frames = [(-3.4028234663852886e+38, [(index, (0., 0., 0., f32(keys[0][1]))) for index, keys in curves.items()])] if sentinel else []
        frames += sorted(stamps.items())
        return frames + [(math.inf, [])]

    def test_streamed_trs_is_exported_as_exact_cubic_hermite(self):
        # Each component keeps its own key stamps, as in a Unity streamed clip.
        curves = {0: [(0, .10, 0, .3), (.3, .19, .2, -.1), (.7, .12, .4, .4), (1, .3, 0, 0)],
                  1: [(0, -.2, 0, .5), (.45, .05, .1, .1), (1, .1, 0, 0)],
                  2: [(0, .05, 0, 0), (.2, .02, -.3, -.3), (.55, -.1, 0, .6), (.8, .04, .2, .2), (1, 0, 0, 0)],
                  3: [(0, .97, 0, -.1), (1, .94, .05, 0)],
                  4: [(0, 0, 0, 1), (.25, .3, 1.5, 1.5), (1, .9, 0, 0)],
                  5: [(0, 1.2, 0, 0), (.6, 1.0, -.8, -.8), (1, 1.1, 0, 0)],
                  6: [(0, -.4, 0, 0), (1, .4, 0, 0)]}
        frames = self.hermite_frames(curves)
        tree = clip([binding(1, 2), binding(1, 1)], stream={"curveCount": 7, "data": words(frames)}, duration=1.)
        glb = builder()
        result = animation.append_animations(scene([tree]), glb, {1: 1})
        self.assertEqual(result["warnings"], [])
        exported = glb.doc["animations"][0]
        rotation, translation = (exported["samplers"][channel["sampler"]] for channel in exported["channels"])
        self.assertEqual([channel["target"]["path"] for channel in exported["channels"]], ["rotation", "translation"])
        for sampler, indices, mirror in ((rotation, range(4), (1, -1, -1, 1)), (translation, range(4, 7), (-1, 1, 1))):
            self.assertEqual(sampler["interpolation"], "CUBICSPLINE")
            stamps = [row[0] for row in values(glb, sampler["input"])]
            expected = sorted({f32(key[0]) for index in indices for key in curves[index]})
            self.assertEqual(stamps, expected, "the per-channel union of the components' key stamps")
            rows = values(glb, sampler["output"])
            self.assertEqual(len(rows), 3 * len(stamps))
            for step in range(1, 400):
                time = step / 400 + 1 / 7919  # off the key stamps and off the 60 Hz grid
                if time >= 1:
                    continue
                unity = [sign * unity_streamed(frames, index, time) for index, sign in zip(indices, mirror)]
                for actual, wanted in zip(hermite(stamps, rows, time), unity):
                    self.assertAlmostEqual(actual, wanted, delta=2e-6, msg=f"t={time}")
        # Raw components: the client evaluates each one separately, so the
        # exported key values are neither normalized nor sign-flipped.
        rows = values(glb, rotation["output"])
        self.assertAlmostEqual(rows[1][3], .97, places=6)
        self.assertGreater(abs(math.sqrt(sum(value * value for value in rows[1])) - 1), 1e-3)

    def test_cubic_tangents_split_a_component_without_its_own_key(self):
        frames = self.hermite_frames({0: [(0, 0, 0, 2), (1, 1, 0, 0)], 1: [(0, 0, 0, 0), (.5, 1, 0, 0), (1, 0, 0, 0)],
                                      2: [(0, 3, 0, 0), (1, 3, 0, 0)]})
        tree = clip([binding(1, 1)], stream={"curveCount": 3, "data": words(frames)}, duration=1.)
        glb = builder()
        animation.append_animations(scene([tree]), glb, {1: 1})
        sampler = glb.doc["animations"][0]["samplers"][0]
        self.assertEqual([row[0] for row in values(glb, sampler["input"])], [0., .5, 1.])
        incoming, value, outgoing = values(glb, sampler["output"])[3:6]
        # x has no key at .5: its cubic is split with one derivative on both sides.
        self.assertAlmostEqual(value[0], -unity_streamed(frames, 0, .5), places=6)
        self.assertAlmostEqual(incoming[0], outgoing[0], places=6)
        self.assertAlmostEqual(incoming[0], -(3 * frames[1][1][0][1][0] * .25 + 2 * frames[1][1][0][1][1] * .5 + 2), places=5)

    def test_stepped_keys_infinite_tangents_and_float32_collisions_keep_the_linear_grid(self):
        stepped = words([(-3.4e38, [(0, (0, 0, 0, 0)), (1, (0, 0, 0, 0)), (2, (0, 0, 0, 0))]),
                         (0, [(0, (0, 0, 0, 0)), (1, (0, 0, 0, 0)), (2, (0, 0, 0, 0))]),
                         (f32(.5), [(0, (0, 0, 0, 1))]), (math.inf, [])])
        infinite = [{"time": 0, "value": {"x": 0, "y": 0, "z": 0}, "outSlope": {"x": math.inf, "y": 0, "z": 0}},
                    {"time": .5, "value": {"x": 1, "y": 0, "z": 0}}, {"time": 1, "value": {"x": 1, "y": 0, "z": 0}}]
        collision = [{"time": 0, "value": {"x": 0, "y": 0, "z": 0}}, {"time": .5, "value": {"x": 1, "y": 0, "z": 0}},
                     {"time": .5 + 1e-9, "value": {"x": 1, "y": 0, "z": 0}}, {"time": 1, "value": {"x": 0, "y": 0, "z": 0}}]
        trees = [clip([binding(1, 1)], stream={"curveCount": 3, "data": stepped}, duration=1., name="Stepped"),
                 {"m_Name": "Infinite tangent", "m_SampleRate": 60, "m_PositionCurves": [{"path": "Root/Bone", "curve": {"m_Curve": infinite}}]},
                 {"m_Name": "Collision", "m_SampleRate": 60, "m_PositionCurves": [{"path": "Root/Bone", "curve": {"m_Curve": collision}}]}]
        for tree in trees:
            with self.subTest(clip=tree["m_Name"]):
                glb = builder()
                result = animation.append_animations(scene([tree]), glb, {1: 1, "Root/Bone": 1})
                self.assertEqual(result["warnings"], [])
                sampler = glb.doc["animations"][0]["samplers"][0]
                self.assertEqual(sampler["interpolation"], "LINEAR")
                stamps = [row[0] for row in values(glb, sampler["input"])]
                self.assertGreater(len(stamps), 60, "the LINEAR fallback keeps the 60 Hz grid")
                rows = values(glb, sampler["output"])
                self.assertEqual(len(rows), len(stamps))
                if tree["m_Name"] != "Collision":
                    self.assertEqual(rows[stamps.index(f32(.5)) - 1][0], 0., "held until the stepped key")
                    self.assertEqual(rows[stamps.index(f32(.5))][0], -1.)

    def test_single_stamp_pose_clip_exports_one_cubic_key(self):
        frames = self.hermite_frames({0: [(0, .1, 0, 0)], 1: [(0, .2, 0, 0)], 2: [(0, .3, 0, 0)], 3: [(0, .9, 0, 0)]})
        tree = clip([binding(1, 2)], stream={"curveCount": 4, "data": words(frames)}, duration=0., name="Pose")
        glb = builder()
        animation.append_animations(scene([tree]), glb, {1: 1})
        sampler = glb.doc["animations"][0]["samplers"][0]
        self.assertEqual(sampler["interpolation"], "CUBICSPLINE")
        self.assertEqual(values(glb, sampler["input"]), [(0.,)])
        self.assertEqual([round(value, 6) for value in values(glb, sampler["output"])[1]], [.1, -.2, -.3, .9])

    def test_local_companion_discovery_uses_internal_owner_and_jail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected, matching, false_name = root / "body.unity", root / "eye_data.unity", root / "ch0207_wrong.unity"
            for path in (selected, matching, false_name):
                path.write_bytes(b"UnityFS\0synthetic inspector fixture")
            with patch.object(animation, "_animation_source", side_effect=lambda path, _: ({207} if path == str(matching) else {101}, 1)):
                found = animation.discover_animation_paths([str(selected)], {"library_roots": [str(root)]}, 207, time.monotonic() + 10)
            self.assertEqual(found, [str(matching)])


class ActualAnimationTests(unittest.TestCase):
    def test_actual_eye_table_exports_against_actual_face_transform_and_morph_paths(self):
        table = os.environ.get("SIFAS_ANIMATION_TEST_EYE_TABLE")
        facial = os.environ.get("SIFAS_ANIMATION_TEST_FACE_BUNDLE")
        if not table or not facial:
            self.skipTest("Set SIFAS_ANIMATION_TEST_EYE_TABLE and SIFAS_ANIMATION_TEST_FACE_BUNDLE for actual clip binding checks")
        sources = [Path(table), Path(facial)]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
        deadline = time.monotonic() + 60
        actual = viewer._Scene(viewer._environment([facial, table], deadline), deadline)
        glb = builder(0)
        nodes, morphs, paths = {}, {}, {}
        for obj in actual.env.objects:
            if obj.type.name != "Transform":
                continue
            names, current = [], obj
            while current is not None:
                tree = actual.tree(current)
                game_object = viewer._ref(current, tree.get("m_GameObject"))
                names.append(actual.name(game_object))
                current = viewer._ref(current, tree.get("m_Father"))
            path = "/".join(reversed(names[:-1]))
            index = len(glb.doc["nodes"])
            glb.doc["nodes"].append({"name": path})
            nodes[animation.path_hash(path)] = index
            paths[viewer._key(obj)] = path
        for renderer, tree, game_object in actual.renderers:
            mesh = viewer._ref(renderer, tree.get("m_Mesh"))
            if mesh is None:
                continue
            channels = mesh.read().m_Shapes.channels
            if not channels:
                continue
            path = paths[viewer._key(actual.transforms[viewer._key(game_object)])]
            morphs[animation.path_hash(path)] = {"node": nodes[animation.path_hash(path)],
                                                  "names": [channel.name for channel in channels],
                                                  "weights": [0] * len(channels)}
        result = animation.append_animations(actual, glb, nodes, morphs, deadline=deadline)
        self.assertEqual(len(result["clips"]), 20)
        selected = next(item for item in result["clips"] if item["name"].endswith("_900"))
        exported = glb.doc["animations"][selected["index"]]
        self.assertEqual(len(exported["channels"]), 1)
        self.assertEqual(exported["channels"][0]["target"]["path"], "weights")
        weights = values(glb, exported["samplers"][0]["output"])
        self.assertAlmostEqual(max(row[0] for row in weights), 1, places=3)
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in sources], before)

    def test_actual_eye_clips_decode_and_keep_eye_900_authored_motion(self):
        path = os.environ.get("SIFAS_ANIMATION_TEST_EYE_TABLE")
        if not path:
            self.skipTest("Set SIFAS_ANIMATION_TEST_EYE_TABLE for actual facial AnimationClip checks")
        source = Path(path)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        deadline = time.monotonic() + 60
        actual = viewer._Scene(viewer._environment([str(source)], deadline), deadline)
        clips = [animation.decode_clip(actual.tree(obj), deadline) for obj in actual.env.objects if obj.type.name == "AnimationClip"]
        self.assertEqual(len(clips), 20)
        selected = next(item for item in clips if item["name"].endswith("_900"))
        self.assertAlmostEqual(selected["duration"], .1, places=6)
        self.assertEqual(len(selected["tracks"]), 1)
        curve = selected["tracks"][0]["curves"][0]
        self.assertAlmostEqual(animation._evaluate(curve, 0), 0)
        self.assertAlmostEqual(animation._evaluate(curve, 1 / 30), 100, places=3)
        self.assertAlmostEqual(animation._evaluate(curve, selected["duration"]), 0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        found = animation.discover_animation_paths([], {"library_roots": [str(source.parent)]}, 207, time.monotonic() + 60)
        self.assertIn(str(source), found)

    def test_actual_varying_transform_clip_uses_streamed_scale_data(self):
        path = os.environ.get("SIFAS_ANIMATION_TEST_TRANSFORM_CLIP")
        if not path:
            self.skipTest("Set SIFAS_ANIMATION_TEST_TRANSFORM_CLIP for actual streamed Transform checks")
        deadline = time.monotonic() + 60
        actual = viewer._Scene(viewer._environment([path], deadline), deadline)
        glb = builder()
        result = animation.append_animations(actual, glb, {0: 1}, deadline=deadline)
        self.assertEqual(len(result["clips"]), 1)
        self.assertEqual(glb.doc["animations"][0]["channels"][0]["target"]["path"], "scale")
        rows = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])
        self.assertGreater(max(row[0] for row in rows) - min(row[0] for row in rows), .01)


if __name__ == "__main__":
    unittest.main()


class EulerWriteHelpersTest(unittest.TestCase):
    """The Euler write helpers used by camera point edits live in webtools (model_animation),
    so an older top-level live_timeline package earlier on sys.path cannot shadow them."""

    def test_helpers_match_the_live_timeline_copy_for_every_order(self):
        import importlib.util
        import random
        from webtools.core import model_animation as animation
        # Load this checkout's copy by path: another top-level live_timeline on
        # sys.path (for example an older Elichika modtools submodule) would
        # otherwise be compared instead.
        source = Path(__file__).resolve().parents[1] / 'live_timeline' / 'sifas_timeline_inject.py'
        spec = importlib.util.spec_from_file_location('_checkout_sifas_timeline_inject', source)
        inject = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inject)
        rng = random.Random(7)
        for order in range(6):
            previous = None
            for _ in range(200):
                q = [rng.uniform(-1, 1) for _ in range(4)]
                ours, theirs = animation.quat_to_unity_euler(q, order), inject.quat_to_unity_euler(q, order)
                self.assertTrue(all(abs(a - b) < 1e-9 for a, b in zip(ours, theirs)), (order, q))
                self.assertEqual(animation.unity_euler_branches(list(ours), order), inject.unity_euler_branches(list(ours), order))
                near_ours = animation.unity_euler_near(q, order, previous)
                near_theirs = inject.unity_euler_near(q, order, previous)
                self.assertTrue(all(abs(a - b) < 1e-9 for a, b in zip(near_ours, near_theirs)), (order, q, previous))
                previous = near_ours

    def test_camera_writer_does_not_import_live_timeline(self):
        source = (Path(__file__).resolve().parents[1] / 'webtools' / 'core' / 'mv_studio_timeline.py').read_text(encoding='utf-8')
        self.assertNotIn('from live_timeline', source)
        self.assertNotIn('import live_timeline', source)
