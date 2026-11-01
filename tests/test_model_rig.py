"""Standard skin rest/pose/morph invariants on original synthetic Unity assets."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from webtools.core import model_viewer as viewer

FIXTURE = Path(__file__).parent / "fixtures" / "viewer_rig.unity"


def unpack(metadata):
    value = viewer.get_model(metadata["id"])
    length, = struct.unpack_from("<I", value, 12)
    return json.loads(value[20:20 + length]), value[28 + length:]


def attribute(document, binary, index):
    import numpy as np
    item = document["accessors"][index]
    view = document["bufferViews"][item["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[item["type"]]
    return np.frombuffer(binary, dtype={5126: "<f4", 5123: "<u2", 5125: "<u4"}[item["componentType"]],
                         count=item["count"] * width, offset=view.get("byteOffset", 0)).reshape(item["count"], width)


def node_worlds(document, overrides=None):
    import numpy as np
    worlds = {}

    def visit(index, parent):
        node = dict(document["nodes"][index])
        node.update((overrides or {}).get(index, {}))
        local = viewer._trs({"m_LocalPosition": dict(zip("xyz", node.get("translation", [0, 0, 0]))),
                             "m_LocalRotation": dict(zip("xyzw", node.get("rotation", [0, 0, 0, 1]))),
                             "m_LocalScale": dict(zip("xyz", node.get("scale", [1, 1, 1])))})
        worlds[index] = parent @ local
        for child in node.get("children", []):
            visit(child, worlds[index])

    for root in document["scenes"][0]["nodes"]:
        visit(root, np.eye(4))
    return worlds


def evaluate(document, binary, overrides=None):
    import numpy as np
    worlds, result = node_worlds(document, overrides), {}
    for node_index, node in enumerate(document["nodes"]):
        if "mesh" not in node:
            continue
        mesh = document["meshes"][node["mesh"]]
        primitive = mesh["primitives"][0]
        points = attribute(document, binary, primitive["attributes"]["POSITION"]).astype(float)
        for target, weight in zip(primitive.get("targets", []), mesh.get("weights", [])):
            points += weight * attribute(document, binary, target["POSITION"])
        if "skin" in node:
            skin = document["skins"][node["skin"]]
            inverse = attribute(document, binary, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
            matrices = np.asarray([worlds[joint] for joint in skin["joints"]]) @ inverse
            indices = attribute(document, binary, primitive["attributes"]["JOINTS_0"])
            weights = attribute(document, binary, primitive["attributes"]["WEIGHTS_0"])
            final = np.zeros_like(points)
            for slot in range(4):
                selected = matrices[indices[:, slot]]
                final += (np.einsum("nij,nj->ni", selected[:, :3, :3], points) + selected[:, :3, 3]) * weights[:, slot, None]
        else:
            final = points @ worlds[node_index][:3, :3].T + worlds[node_index][:3, 3]
        result[mesh["name"]] = final
    return result


class RigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
            import numpy as np
        except ImportError as error:
            raise unittest.SkipTest("UnityPy and numpy are required") from error
        cls.UnityPy, cls.np = UnityPy, np

    def tearDown(self):
        viewer._SESSIONS.clear()

    def test_genuine_skin_preserves_rest_positions_and_standard_binding_graph(self):
        before = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        static = evaluate(*unpack(viewer.prepare([str(FIXTURE)])))
        metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        document, binary = unpack(metadata)
        actual = evaluate(document, binary)
        self.assertTrue(metadata["rig"]["available"])
        self.assertEqual(len(document["skins"]), 1)
        self.assertEqual(len(document["skins"][0]["joints"]), 3)
        for name in static:
            self.np.testing.assert_allclose(actual[name], static[name], atol=1e-6)
        primitive = document["meshes"][0]["primitives"][0]
        self.assertIn("_SIFAS_COLOR", primitive["attributes"])
        self.assertNotIn("COLOR_0", primitive["attributes"])
        self.assertEqual(document["meshes"][0]["extras"]["targetNames"], ["NeutralBend"])
        self.assertEqual([clip["name"] for clip in document["animations"]], ["Neutral swing"])
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), before)

    def test_bone_scale_and_clip_rotation_change_actual_skinned_vertices(self):
        metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        document, binary = unpack(metadata)
        rest = evaluate(document, binary)
        control = next(item for item in metadata["rig"]["scaling"]["controls"] if item["id"] == "breast")
        node = control["nodes"][0]["node"]
        changed = evaluate(document, binary, {node: {"scale": [1.2, .9, 1.]}})
        self.assertGreater(max(abs(changed[name] - rest[name]).max() for name in rest), .01)
        animation = document["animations"][0]
        track = next(item for item in animation["channels"] if item["target"]["path"] == "rotation")
        rotations = attribute(document, binary, animation["samplers"][track["sampler"]]["output"])
        self.assertGreater(abs(rotations[0] - rotations[len(rotations) // 2]).max(), .1)

    def test_authored_nonzero_morph_defaults_match_static_baseline(self):
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        renderer = next(obj for obj in environment.objects if obj.type.name == "SkinnedMeshRenderer")
        tree = renderer.read_typetree()
        tree["m_BlendShapeWeights"] = [35.]
        renderer.save_typetree(tree)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authored.unity"
            path.write_bytes(next(iter(environment.files.values())).save())
            static = evaluate(*unpack(viewer.prepare([str(path)])))
            metadata = viewer.prepare([str(path)], rigged=True)
            document, binary = unpack(metadata)
        self.assertEqual(document["meshes"][0]["weights"], [.35])
        self.assertEqual(metadata["rig"]["morphs"][0]["weights"], [.35])
        for name, points in evaluate(document, binary).items():
            self.np.testing.assert_allclose(points, static[name], atol=1e-6)

    def test_unrigged_mesh_remains_static_and_has_no_invented_skin(self):
        path = FIXTURE.with_name("viewer_triangle.unity")
        metadata = viewer.prepare([str(path)], rigged=True)
        document, _ = unpack(metadata)
        self.assertFalse(metadata["rig"]["available"])
        self.assertFalse(document.get("skins"))

    def test_negative_authored_axis_preserves_absolute_scale_animation_basis(self):
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        transform = next(obj for obj in environment.objects if obj.type.name == "Transform" and obj.read_typetree()["m_GameObject"]["m_PathID"] ==
                         next(go.path_id for go in environment.objects if go.type.name == "GameObject" and go.peek_name() == "Move"))
        tree = transform.read_typetree()
        tree["m_LocalScale"] = dict(x=1., y=-1., z=1.)
        transform.save_typetree(tree)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "negative-axis.unity"
            path.write_bytes(next(iter(environment.files.values())).save())
            metadata = viewer.prepare([str(path)], rigged=True)
            document, _ = unpack(metadata)
        node = next(row["node"] for row in metadata["rig"]["bones"] if row["name"] == "Move")
        self.assertEqual(document["nodes"][node]["scale"], [1, -1, 1])
        self.np.testing.assert_allclose(document["nodes"][node]["rotation"], [0, 0, 0, 1])
        # An absolute localScale key/saved endpoint must still mean Unity XYZ,
        # rather than a sign moved to X and compensated by a new Z rotation.
        changed = node_worlds(document, {node: {"scale": [1, -.8, 1]}})
        self.np.testing.assert_allclose(changed[node], self.np.diag([1, -.8, 1, 1]), atol=1e-7)

    def test_large_authored_morph_checks_deadline_inside_vertex_loop(self):
        from webtools.core.model_rig import apply_default_morphs
        vector = SimpleNamespace(x=0., y=.01, z=0.)
        value = SimpleNamespace(index=0, vertex=vector, normal=vector)
        shape = SimpleNamespace(firstVertex=0, vertexCount=8192, hasNormals=True)
        channel = SimpleNamespace(frameCount=1, frameIndex=0)
        mesh = SimpleNamespace(m_Shapes=SimpleNamespace(channels=[channel], shapes=[shape], fullWeights=[100.], vertices=[value] * 8192))
        with patch.object(viewer.time, "monotonic", side_effect=[0., 0., 2.]):
            with self.assertRaisesRegex(viewer.ModelViewerError, "too long"):
                apply_default_morphs(mesh, self.np.zeros((1, 3)), self.np.zeros((1, 3)), [10.], deadline=1.)

    def test_hierarchy_path_bytes_are_capped_before_joining(self):
        from webtools.core.model_rig import RigBuilder, RigError, MAX_NAME_BYTES
        asset = object()
        transform = SimpleNamespace(assets_file=asset, path_id=1)
        game = SimpleNamespace(assets_file=asset, path_id=2)
        builder = RigBuilder.__new__(RigBuilder)
        builder.scene = SimpleNamespace(tree=lambda obj: {"m_GameObject": game, "m_Father": None},
                                        name=lambda obj: "x" * (MAX_NAME_BYTES + 1))
        with patch.object(viewer, "_ref", side_effect=lambda obj, pointer: pointer):
            with self.assertRaisesRegex(RigError, "byte limit"):
                builder._path(transform)

    def test_animation_failure_preserves_completed_rig_skin_and_morph_model(self):
        from webtools.core import model_animation
        static = evaluate(*unpack(viewer.prepare([str(FIXTURE)])))
        with patch.object(model_animation, "append_animations", side_effect=viewer.ModelViewerError("optional clip took too long")):
            metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        document, binary = unpack(metadata)
        self.assertTrue(metadata["rig"]["available"])
        self.assertEqual(len(document["skins"]), 1)
        self.assertEqual(document["meshes"][0]["extras"]["targetNames"], ["NeutralBend"])
        self.assertTrue(metadata["rig"]["animationWarnings"])
        for name, points in evaluate(document, binary).items():
            self.np.testing.assert_allclose(points, static[name], atol=1e-6)


class ActualRigTests(unittest.TestCase):
    def test_actual_clothed_face_and_head_pose_stay_joined(self):
        costume, facial = os.environ.get("SIFAS_FACE_TEST_COSTUME"), os.environ.get("SIFAS_FACE_TEST_BUNDLE")
        if not costume or not facial:
            self.skipTest("Set actual clothed costume/facial source environment variables")
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            roots = [str(Path(facial).parent)]
            if os.environ.get("SIFAS_FACE_TEST_EYE_TABLE"):
                roots.append(str(Path(os.environ["SIFAS_FACE_TEST_EYE_TABLE"]).parent))
            context = {"enabled": True, "allow_download": False, "cache_dir": directory, "library_roots": roots}
            static = evaluate(*unpack(viewer.prepare([costume], face_context=context)))
            metadata = viewer.prepare([costume], face_context=context, rigged=True)
            document, binary = unpack(metadata)
        rest = evaluate(document, binary)
        for name in static:
            np.testing.assert_allclose(rest[name], static[name], atol=4e-6, rtol=0)
        head = next(row["node"] for row in metadata["rig"]["bones"] if row["name"] == "Head")
        changed = evaluate(document, binary, {head: {"rotation": [.1, .15, .05, .98]}})
        worlds, posed = node_worlds(document), node_worlds(document, {head: {"rotation": [.1, .15, .05, .98]}})
        delta = posed[head] @ np.linalg.inv(worlds[head])
        for name in ("Face", "Eye", "Eye_Around", "Mouth", "LeftEyeWhiteLine", "RightEyeWhiteLine"):
            expected = rest[name] @ delta[:3, :3].T + delta[:3, 3]
            np.testing.assert_allclose(changed[name], expected, atol=4e-6, rtol=0)
        self.assertEqual(len(document["skins"]), 8)
        self.assertEqual(sum(len(row["names"]) for row in metadata["rig"]["morphs"]), 33)
        if os.environ.get("SIFAS_FACE_TEST_EYE_TABLE"):
            expected = {"001": {"LeftEyeWhiteLine", "RightEyeWhiteLine"}, "005": {"LeftEyeWhiteLine", "RightEyeWhiteLine"},
                        "012": {"RightEyeWhiteLine"}, "013": {"LeftEyeWhiteLine"},
                        "018": {"LeftEyeWhiteLine", "RightEyeWhiteLine"}, "019": {"LeftEyeWhiteLine", "RightEyeWhiteLine"}}
            clips = metadata["rig"]["clips"]
            self.assertEqual(len(clips), 20)
            for suffix, mesh_names in expected.items():
                clip = next(row for row in clips if row["sourceName"].endswith("_" + suffix))
                self.assertEqual({document["meshes"][document["nodes"][track["node"]]["mesh"]]["name"] for track in clip["visibility"]}, mesh_names)
                for track in clip["visibility"]:
                    self.assertEqual(track["values"], [False, True])
                    self.assertEqual(track["times"], [0., 1.])
            self.assertFalse(any(row["code"] == "animation_partial" for row in metadata["rig"]["animationWarnings"]))
        controls = {row["id"]: row for row in metadata["rig"]["scaling"]["controls"]}
        move = controls["height"]["nodes"][0]["node"]
        scale = [value * 1.1 for value in document["nodes"][move]["scale"]]
        taller_worlds = node_worlds(document, {move: {"scale": scale}})
        delta = taller_worlds[move] @ np.linalg.inv(worlds[move])
        taller = evaluate(document, binary, {move: {"scale": scale}})
        for name, points in rest.items():
            np.testing.assert_allclose(taller[name], points @ delta[:3, :3].T + delta[:3, 3], atol=4e-6, rtol=0)
        breast = controls["breast"]["nodes"][0]["node"]
        enlarged = evaluate(document, binary, {breast: {"scale": [value * 1.2 for value in document["nodes"][breast]["scale"]]}})
        body = next(name for name in rest if "deleteMesh" in name)
        self.assertGreater(abs(enlarged[body] - rest[body]).max(), .001)
        for name in ("Face", "Eye", "Eye_Around", "Mouth", "Hair"):
            np.testing.assert_allclose(enlarged[name], rest[name], atol=4e-6, rtol=0)
