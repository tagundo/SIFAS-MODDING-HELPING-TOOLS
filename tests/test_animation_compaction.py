"""Animation replacement preserves interleaved geometry and completed fallbacks."""
import copy
import io
import math
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from webtools.core import model_animation as animation, model_rig, model_viewer as viewer


def original_scene(frames=9, rate=4.):
    tree = {"m_Name": "Original compaction motion", "m_SampleRate": rate,
        "m_ClipBindingConstant": {"genericBindings": [dict(path=123, attribute=1, typeID=4, customType=0, isPPtrCurve=0)]},
        "m_MuscleClip": {"m_StartTime": 0., "m_StopTime": (frames - 1) / rate, "m_LoopTime": False,
            "m_Clip": {"data": {"m_StreamedClip": {"curveCount": 0, "data": []},
                "m_DenseClip": {"m_CurveCount": 3, "m_FrameCount": frames, "m_SampleRate": rate, "m_BeginTime": 0.,
                    "m_SampleArray": [value for index in range(frames) for value in (index * .01, math.sin(index * .1), index % 11 * .02)]},
                "m_ConstantClip": {"data": []}}}}}
    obj = SimpleNamespace(type=SimpleNamespace(name="AnimationClip"), data=tree)
    return SimpleNamespace(env=SimpleNamespace(objects=[obj]), name=lambda value: value.data["m_Name"],
        tree=lambda value: value.data, stats={"meshes": 1}, warnings=[])


def png_bytes():
    output = io.BytesIO()
    Image.new("RGBA", (3, 2), (17, 89, 144, 210)).save(output, format="PNG")
    return output.getvalue()


def geometry(glb, name, *, sparse=False):
    position = glb.attribute([[.1, .2, 0.], [.8, .2, 0.], [.1, .9, .1]], "VEC3", bounds=True)
    normal = glb.attribute([[0., 0., 1.]] * 3, "VEC3")
    uv = glb.attribute([[0., 0.], [1., 0.], [0., 1.]], "VEC2")
    indices = glb.attribute([0, 1, 2], "SCALAR", 5123)
    joints = glb.attribute([[0, 0, 0, 0]] * 3, "VEC4", 5123)
    weights = glb.attribute([[1., 0., 0., 0.]] * 3, "VEC4")
    inverse = glb.attribute([np.eye(4).reshape(-1)], "MAT4", target=None)
    morph = glb.attribute([[0., .05, 0.], [0., .1, 0.], [0., 0., 0.]], "VEC3")
    if sparse:
        sparse_indices = glb.view(b"\x01")
        sparse_values = glb.view(struct.pack("<fff", .25, .5, .75))
        position = len(glb.doc["accessors"])
        glb.doc["accessors"].append({"componentType": 5126, "count": 3, "type": "VEC3", "sparse": {
            "count": 1, "indices": {"bufferView": sparse_indices, "componentType": 5121},
            "values": {"bufferView": sparse_values}}})
    attributes = {"POSITION": position, "NORMAL": normal, "TEXCOORD_0": uv, "JOINTS_0": joints, "WEIGHTS_0": weights}
    targets = [{"POSITION": morph}]
    primitives = [{"attributes": attributes, "indices": indices, "targets": targets,
                   "extras": {"originalIntegers": [position, morph, inverse], "part": name}} for _ in range(2)]
    mesh = len(glb.doc["meshes"])
    glb.doc["meshes"].append({"name": name, "primitives": primitives, "weights": [.3], "extras": {"targetNames": [name + " morph"]}})
    skin = len(glb.doc.setdefault("skins", []))
    glb.doc["skins"].append({"joints": [0], "inverseBindMatrices": inverse, "skeleton": 0})
    node = len(glb.doc["nodes"])
    glb.doc["nodes"].append({"name": name, "mesh": mesh, "skin": skin})
    glb.doc["scenes"][0]["nodes"].append(node)
    glb.doc["images"].append({"name": name, "bufferView": glb.view(png_bytes()), "mimeType": "image/png"})
    return position


def accessor_values(glb, index):
    item = glb.doc["accessors"][index]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[item["type"]]
    dtype = np.dtype({5121: "<u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[item["componentType"]])
    if "bufferView" in item:
        view = glb.doc["bufferViews"][item["bufferView"]]
        offset = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        result = np.ndarray((item["count"], width), dtype=dtype, buffer=glb.data, offset=offset,
            strides=(view.get("byteStride", width * dtype.itemsize), dtype.itemsize)).copy()
    else:
        result = np.zeros((item["count"], width), dtype=dtype)
    if "sparse" in item:
        sparse = item["sparse"]
        indices = sparse["indices"]; view = glb.doc["bufferViews"][indices["bufferView"]]
        ids = np.frombuffer(glb.data, dtype={5121: "<u1", 5123: "<u2", 5125: "<u4"}[indices["componentType"]],
            count=sparse["count"], offset=view.get("byteOffset", 0) + indices.get("byteOffset", 0))
        values = sparse["values"]; view = glb.doc["bufferViews"][values["bufferView"]]
        replacement = np.frombuffer(glb.data, dtype=dtype, count=sparse["count"] * width,
            offset=view.get("byteOffset", 0) + values.get("byteOffset", 0)).reshape(sparse["count"], width)
        result[ids] = replacement
    return result.tolist()


def geometry_values(glb):
    result = {"nodes": copy.deepcopy(glb.doc["nodes"]), "meshes": [], "skins": [], "images": []}
    for mesh in glb.doc["meshes"]:
        result["meshes"].append([{"attributes": {key: accessor_values(glb, value) for key, value in primitive["attributes"].items()},
            "indices": accessor_values(glb, primitive["indices"]), "extras": copy.deepcopy(primitive["extras"]),
            "targets": [{key: accessor_values(glb, value) for key, value in target.items()} for target in primitive["targets"]]}
            for primitive in mesh["primitives"]])
    for skin in glb.doc.get("skins", []):
        result["skins"].append({"joints": list(skin["joints"]), "inverse": accessor_values(glb, skin["inverseBindMatrices"])})
    for image in glb.doc["images"]:
        view = glb.doc["bufferViews"][image["bufferView"]]
        result["images"].append(bytes(glb.data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]))
    return result


def animation_values(glb):
    return [{"name": clip["name"], "channels": copy.deepcopy(clip["channels"]),
             "samplers": [{"times": accessor_values(glb, sampler["input"]), "values": accessor_values(glb, sampler["output"])}
                          for sampler in clip["samplers"]]} for clip in glb.doc.get("animations", [])]


def rig_fixture(*, frames=9, rate=4.):
    glb = viewer._Glb()
    glb.doc["nodes"] = [{"name": "Original animated bone"}]
    glb.doc["scenes"][0]["nodes"] = [0]
    glb.attribute([[9., 9., 9.]], "VEC3")  # Unreferenced prefix makes remapping non-identity.
    geometry(glb, "Initial garment")
    rig = model_rig.RigBuilder.__new__(model_rig.RigBuilder)
    rig.glb, rig.scene, rig.deadline = glb, original_scene(frames, rate), float("inf")
    rig.nodes, rig.selected, rig.node_bindings, rig.morph_bindings, rig.visibility_bindings = {}, set(), {123: 0}, {}, {}
    rig.clips, rig.animation_warnings, rig.scaling = [], [], {"loaded": True}
    rig.metadata = lambda: {"enabled": True, "available": True, "clips": copy.deepcopy(rig.clips),
                            "animationWarnings": copy.deepcopy(rig.animation_warnings)}
    return rig


class AnimationCompactionTests(unittest.TestCase):
    def setUp(self):
        self.scaling = patch("webtools.core.model_scaling.describe_scaling", side_effect=lambda scene, glb, nodes, **kwargs: {"fromOriginalFile": True})
        self.scaling.start(); self.addCleanup(self.scaling.stop)

    def test_shared_submesh_attributes_and_morph_targets_remap_once(self):
        rig = rig_fixture(); glb = rig.glb
        before = geometry_values(glb)
        first, second = glb.doc["meshes"][0]["primitives"]
        self.assertIs(first["attributes"], second["attributes"])
        self.assertIs(first["targets"], second["targets"])
        candidate = animation.animation_candidate(glb)
        self.assertEqual(geometry_values(candidate), before)
        self.assertNotEqual(candidate.doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"], first["attributes"]["POSITION"])

    def test_interleaved_late_geometry_sparse_skin_and_png_keep_actual_values(self):
        rig = rig_fixture(); rig.finalize()
        geometry(rig.glb, "Late facial attachment", sparse=True)
        before = geometry_values(rig.glb)
        doc, data = rig.glb.doc, rig.glb.data
        document_copy, binary_copy = copy.deepcopy(doc), bytes(data)
        candidate = animation.animation_candidate(rig.glb)
        self.assertIs(rig.glb.doc, doc); self.assertIs(rig.glb.data, data)
        self.assertEqual(rig.glb.doc, document_copy); self.assertEqual(bytes(rig.glb.data), binary_copy)
        self.assertNotIn("animations", candidate.doc)
        self.assertEqual(geometry_values(candidate), before)
        late = candidate.doc["meshes"][1]["primitives"][0]["attributes"]["POSITION"]
        self.assertEqual(accessor_values(candidate, late), [[0., 0., 0.], [.25, .5, .75], [0., 0., 0.]])
        rig.finalize()
        self.assertEqual(geometry_values(rig.glb), before)
        for view in rig.glb.doc["bufferViews"]:
            self.assertEqual(view["byteOffset"] % 4, 0)
            self.assertLessEqual(view["byteOffset"] + view["byteLength"], len(rig.glb.data))

    def test_repeated_finalize_has_stable_allocation_and_decoded_tracks(self):
        rig = rig_fixture(); rig.finalize()
        initial = bytes(rig.glb.finish())
        allocation = (len(rig.glb.data), len(rig.glb.doc["accessors"]), len(rig.glb.doc["bufferViews"]))
        tracks = animation_values(rig.glb)
        for _ in range(3):
            rig.finalize()
            self.assertEqual((len(rig.glb.data), len(rig.glb.doc["accessors"]), len(rig.glb.doc["bufferViews"])), allocation)
            self.assertEqual(animation_values(rig.glb), tracks)
            self.assertEqual(bytes(rig.glb.finish()), initial)

    def test_latest_animation_fits_budget_without_obsolete_animation_bytes(self):
        rig = rig_fixture(frames=601, rate=60.); rig.finalize()
        initial = bytes(rig.glb.finish())
        live = animation.animation_candidate(rig.glb)
        animation_bytes = len(rig.glb.data) - len(live.data)
        limit = len(initial) + 512
        self.assertGreater(len(rig.glb.data) + animation_bytes, limit)
        with patch.object(viewer, "MAX_GLB_BYTES", limit):
            rig.finalize(); rig.finalize()
            self.assertEqual(len(rig.clips), 1)
            self.assertLessEqual(len(rig.glb.finish()), limit)
        self.assertEqual(bytes(rig.glb.finish()), initial)

    def assert_original_state(self, rig, checkpoint):
        doc, data, clips, warnings, scaling, contents, binary = checkpoint
        self.assertIs(rig.glb.doc, doc); self.assertIs(rig.glb.data, data)
        self.assertIs(rig.clips, clips); self.assertIs(rig.animation_warnings, warnings); self.assertIs(rig.scaling, scaling)
        self.assertEqual(rig.glb.doc, contents); self.assertEqual(bytes(rig.glb.data), binary)

    def checkpoint(self, rig):
        return rig.glb.doc, rig.glb.data, rig.clips, rig.animation_warnings, rig.scaling, copy.deepcopy(rig.glb.doc), bytes(rig.glb.data)

    def test_partial_append_failure_does_not_replace_previous_buffers_or_metadata(self):
        rig = rig_fixture(); rig.finalize(); before = self.checkpoint(rig)
        def fail(scene, candidate, *args, **kwargs):
            candidate.attribute([[1., 2., 3.]], "VEC3")
            raise animation.AnimationError("Original test append failure")
        with patch.object(animation, "append_animations", side_effect=fail), self.assertRaisesRegex(animation.AnimationError, "append failure"):
            rig.finalize()
        self.assert_original_state(rig, before)
        geometry(rig.glb, "Append after failed replacement"); rig.finalize()
        self.assertEqual(len(rig.glb.doc["meshes"]), 2)
        self.assertEqual(len(rig.clips), 1)

    def test_candidate_finish_and_late_deadline_failures_are_transactional(self):
        for failure in ("serialize", "deadline"):
            with self.subTest(failure=failure):
                rig = rig_fixture(); rig.finalize(); before = self.checkpoint(rig)
                finish = viewer._Glb.finish
                def fail(candidate):
                    result = finish(candidate)
                    if failure == "serialize":
                        raise viewer.ModelViewerError("Original test serialization failure")
                    rig.deadline = -1.
                    return result
                with patch.object(viewer._Glb, "finish", fail), self.assertRaises(ValueError):
                    rig.finalize()
                self.assert_original_state(rig, before)
                rig.deadline = float("inf"); rig.finalize()
                self.assertEqual(len(rig.clips), 1)

    def test_compaction_timeout_and_invalid_binary_bounds_leave_source_untouched(self):
        rig = rig_fixture(); rig.finalize(); before = self.checkpoint(rig)
        original, calls = animation._check, [0]
        def expire(deadline):
            calls[0] += 1
            if calls[0] == 3:
                raise animation.AnimationError("Original test compaction deadline")
            return original(deadline)
        with patch.object(animation, "_check", expire), self.assertRaisesRegex(animation.AnimationError, "compaction deadline"):
            animation.animation_candidate(rig.glb)
        self.assert_original_state(rig, before)
        view_id = rig.glb.doc["accessors"][rig.glb.doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]["bufferView"]
        rig.glb.doc["bufferViews"][view_id]["byteLength"] = len(rig.glb.data) + 1
        before = self.checkpoint(rig)
        with self.assertRaisesRegex(animation.AnimationError, "binary bounds"):
            animation.animation_candidate(rig.glb)
        self.assert_original_state(rig, before)

    def test_post_commit_validation_and_serialization_restore_completed_model(self):
        for failure in ("validation", "serialization", "deadline"):
            with self.subTest(failure=failure):
                rig = rig_fixture(); rig.finalize(); before = self.checkpoint(rig)
                faces = SimpleNamespace(enabled=False, status="not_needed", auto_paths=set(), added=0, warnings=[], finish=lambda: None, metadata=lambda: {})
                finalize, finish, remaining = rig.finalize, viewer._Glb.finish, viewer._remaining
                calls = [0]
                def incomplete(animations=True):
                    result = finalize(animations)
                    if animations:
                        rig.clips = [{**row, "bindingComplete": False} for row in rig.clips]
                    return result
                def fail_serialization(candidate):
                    calls[0] += 1
                    if calls[0] == 3:
                        raise viewer.ModelViewerError("Original post-commit serialization failure")
                    return finish(candidate)
                def fail_deadline(deadline):
                    calls[0] += 1
                    if calls[0] == 3:
                        raise viewer.ModelViewerError("Original post-commit deadline")
                    return remaining(deadline)
                # Baseline-only finalize is allowed to recompute scaling, but
                # use the same original metadata here to check rollback identity.
                with patch("webtools.core.model_scaling.describe_scaling", return_value=rig.scaling):
                    if failure == "validation":
                        with patch.object(rig, "finalize", side_effect=incomplete), self.assertRaisesRegex(ValueError, "could not be retained"):
                            viewer._to_glb(rig.scene, rig.glb, faces, float("inf"), rig, require_existing_clips=True)
                    elif failure == "serialization":
                        with patch.object(viewer._Glb, "finish", fail_serialization):
                            result = viewer._to_glb(rig.scene, rig.glb, faces, float("inf"), rig)
                        self.assertEqual(result[0], bytes(rig.glb.finish()))
                    else:
                        with patch.object(viewer, "_remaining", fail_deadline):
                            result = viewer._to_glb(rig.scene, rig.glb, faces, float("inf"), rig)
                        self.assertEqual(result[0], bytes(rig.glb.finish()))
                self.assert_original_state(rig, before)
