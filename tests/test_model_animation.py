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


class AnimationTests(unittest.TestCase):
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
        self.assertEqual(values(glb, exported["samplers"][1]["output"]), [(1., 2., 3.)] * 3)
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

    def test_duplicate_clip_names_stay_independently_selectable(self):
        first = clip([binding(1, 1)], constant=[0, 0, 0], name="Authored pose")
        second = clip([binding(1, 1)], constant=[1, 0, 0], name="Authored pose")
        glb = builder()
        result = animation.append_animations(scene([first, second]), glb, {1: 1})
        self.assertEqual([item["name"] for item in result["clips"]], ["Authored pose", "Authored pose__2"])
        self.assertEqual([item["name"] for item in glb.doc["animations"]], [item["name"] for item in result["clips"]])
        self.assertEqual(values(glb, glb.doc["animations"][1]["samplers"][0]["output"])[0], (-1., 0., 0.))

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
        with patch.object(animation, "MAX_VALUES", 10):
            result = animation.append_animations(scene([tree]), glb, {1: 1})
        self.assertEqual(result["clips"], [])
        self.assertEqual(len(glb.data), 0)
        self.assertEqual(glb.doc["accessors"], [])
        self.assertEqual(glb.doc["bufferViews"], [])

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
        rows = values(glb, glb.doc["animations"][0]["samplers"][0]["output"])
        self.assertAlmostEqual(rows[1][0], -.15625)
        self.assertAlmostEqual(rows[-1][0], -1.)

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
