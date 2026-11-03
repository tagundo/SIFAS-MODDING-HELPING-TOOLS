"""Standard skin rest/pose/morph invariants on original synthetic Unity assets."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core.model_rig import RigBuilder, RigError, MAX_NODES

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

    def owner_rig_without_clips(self, unbound_clip=False):
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        body_object = next(obj.read_typetree()["m_GameObject"]["m_PathID"] for obj in environment.objects if obj.type.name == "SkinnedMeshRenderer")
        for obj in list(environment.objects):
            if obj.type.name == "AnimationClip":
                if unbound_clip:
                    tree = obj.read_typetree()
                    for field in ("m_RotationCurves", "m_PositionCurves", "m_ScaleCurves", "m_EulerCurves"):
                        for curve in tree.get(field, []):
                            curve["path"] = "Absent/UnboundBone"
                    obj.save_typetree(tree)
                else:
                    del obj.assets_file.objects[obj.path_id]
            elif obj.type.name == "Material":
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0207_neutral_rig"
                obj.save_typetree(tree)
            elif obj.type.name == "GameObject" and obj.path_id == body_object:
                tree = obj.read_typetree()
                tree["m_Name"] = "Body"
                obj.save_typetree(tree)
        return next(iter(environment.files.values())).save()

    def _face_budget_inputs(self, directory):
        from test_model_faces import FaceTests, bundle
        root = Path(directory)
        path, donor = root / "rig.unity", root / "Setsuna_original.unity"
        path.write_bytes(self.owner_rig_without_clips())
        donor.write_bytes(bundle([(name + ".assets", FaceTests.scene(self, name)) for name in ("Face", "Eyes")]))
        return path, {"enabled": True, "allow_download": False,
                      "library_roots": [str(root)], "cache_dir": str(root / "cache")}

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
        builder.deadline = float("inf")
        builder._path_cache = {}
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

    def test_disabled_auto_face_static_costume_skips_global_motion_discovery(self):
        from webtools.core import viewer_archive, model_animation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "costume.zip"
            shutil.copyfile(FIXTURE.with_name("viewer_auto_face_costume.zip"), archive)
            shutil.copyfile(FIXTURE.with_name("viewer_auto_face_donor.unity"), root / "donor.unity")
            # Stage the actual companion when supplied; the no-playable-rig
            # guard must run before scanning or attempting any of its 20 clips.
            actual = os.environ.get("SIFAS_FACE_TEST_EYE_TABLE")
            if actual:
                shutil.copyfile(actual, root / "Setsuna_eye_animation.unity")
            with viewer_archive.expand_inputs([str(archive)], root / "cache") as expanded:
                context = {"enabled": False, "allow_download": False, "library_roots": [str(root)],
                           "cache_dir": str(root / "cache"), "origins": expanded.origins,
                           "manifest_paths": expanded.manifest_paths}
                with patch.object(model_animation, "discover_animation_paths", side_effect=AssertionError("Static models must not discover clips")) as discovery:
                    metadata = viewer.prepare(expanded.paths, face_context=context, rigged=True)
            discovery.assert_not_called()
        self.assertEqual(metadata["faces"], {"enabled": False, "status": "not_needed", "added": 0, "characters": []})
        self.assertFalse(metadata["rig"]["available"])
        self.assertEqual(metadata["stats"]["meshes"], 2)
        self.assertNotIn("face_source_unavailable", [row["code"] for row in metadata["warnings"]])

    def test_disabled_faces_survive_playable_motion_discovery_failure(self):
        from webtools.core import model_animation
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips())
            baseline = viewer.prepare([str(path)], rigged=True)
            original = viewer.get_model(baseline["id"])
            with patch.object(model_animation, "discover_animation_paths", side_effect=OSError("motion lookup failed")):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": False})
            self.assertEqual(viewer.get_model(metadata["id"]), original)
        self.assertEqual(metadata["faces"], baseline["faces"])
        self.assertEqual(metadata["warnings"], baseline["warnings"])
        self.assertEqual(metadata["rig"]["animationWarnings"][-1]["code"], "animation_unavailable")

    def test_automatic_motion_survives_face_lookup_failure(self):
        from webtools.core import model_faces, model_motion
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips())
            with patch.object(model_faces.FacePlan, "resolve", side_effect=OSError("face CDN unavailable")), \
                    patch.object(model_motion.MotionInputs, "automatic", return_value=[str(FIXTURE)]) as automatic:
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True})
            automatic.assert_called_once()
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
        self.assertTrue(metadata["rig"]["available"])
        self.assertEqual(metadata["stats"]["meshes"], 1)

    def _offline_preview(self, directory):
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        for obj in list(environment.objects):
            if obj.type.name != "AnimationClip":
                del obj.assets_file.objects[obj.path_id]
        plain = next(iter(environment.files.values())).save()
        path = Path(directory) / "preview.unity"
        path.write_bytes(plain)
        return path, {hashlib.sha256(plain).hexdigest(): {
            "size": len(plain), "assetName": None, "clipName": "Neutral swing", "channels": 1}}

    def test_verified_preview_is_committed_before_face_lookup_exhausts_allowance(self):
        from webtools.core import model_faces, model_motion
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            preview, recipes = self._offline_preview(directory)
            clock, finish, calls = [0.], viewer._to_glb, []

            def finish_body(*args, **kwargs):
                result = finish(*args, **kwargs)
                if not calls:
                    clock[0] = 120.
                calls.append(result)
                return result

            def expire_lookup(faces):
                self.assertEqual(faces.deadline, 160.)
                self.assertEqual([clip["name"] for clip in calls[-1][4]["clips"]], ["Neutral swing"])
                clock[0] = 160.
                return []

            with patch.object(model_motion, "KNOWN_PREVIEWS", recipes), \
                    patch.object(model_motion, "BUNDLED_PREVIEW", preview), \
                    patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(viewer, "_to_glb", side_effect=finish_body), \
                    patch.object(model_faces.FacePlan, "resolve", expire_lookup):
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
                document, _ = unpack(metadata)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["stats"]["meshes"], 1)
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
        self.assertTrue(metadata["rig"]["previewMotion"]["verified"])
        self.assertEqual(len(document["animations"]), 1)

    def test_failed_face_rebinding_returns_pre_face_preview_not_stale_face_bytes(self):
        from webtools.core import model_motion, model_rig
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            preview, recipes = self._offline_preview(directory)
            finalize, failures = model_rig.RigBuilder.finalize, []

            def fail_rebinding(rig, animations=True):
                if animations and rig.faces.enabled and rig.faces.added:
                    # The live animation list has already been replaced when
                    # re-export fails. Its pre-face snapshot must remain valid.
                    rig.glb.doc.pop("animations", None)
                    failures.append(True)
                    raise viewer.ModelViewerError("late facial rebind expired")
                return finalize(rig, animations=animations)

            with patch.object(model_motion, "KNOWN_PREVIEWS", recipes), \
                    patch.object(model_motion, "BUNDLED_PREVIEW", preview), \
                    patch.object(model_rig.RigBuilder, "finalize", fail_rebinding):
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
            document, _ = unpack(metadata)
        self.assertEqual(failures, [True])
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["faces"]["added"], 0)
        self.assertEqual(metadata["stats"]["meshes"], 1)
        self.assertEqual(len(document["meshes"]), 1)
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
        self.assertTrue(metadata["rig"]["previewMotion"]["verified"])
        for animation in document["animations"]:
            for channel in animation["channels"]:
                self.assertLess(channel["target"]["node"], len(document["nodes"]))

    def test_incomplete_face_rebind_cannot_reuse_old_complete_preview_metadata(self):
        from webtools.core import model_motion, model_rig
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            preview, recipes = self._offline_preview(directory)
            finalize = model_rig.RigBuilder.finalize

            def incomplete_rebinding(rig, animations=True):
                result = finalize(rig, animations=animations)
                if animations and rig.faces.enabled and rig.faces.added:
                    for clip in rig.clips:
                        clip["bindingComplete"] = False
                return result

            with patch.object(model_motion, "KNOWN_PREVIEWS", recipes), \
                    patch.object(model_motion, "BUNDLED_PREVIEW", preview), \
                    patch.object(model_rig.RigBuilder, "finalize", incomplete_rebinding):
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
            document, _ = unpack(metadata)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["faces"]["added"], 0)
        self.assertEqual(metadata["stats"]["meshes"], 1)
        self.assertEqual(len(document["meshes"]), 1)
        self.assertTrue(metadata["rig"]["clips"][0]["bindingComplete"])
        self.assertTrue(metadata["rig"]["previewMotion"]["verified"])

    def test_rina_board_placeholder_uses_validated_costume_metadata_for_motion_owner(self):
        from webtools.core import model_motion
        environment = self.UnityPy.load(self.owner_rig_without_clips())
        for obj in environment.objects:
            if obj.type.name == "Material":
                tree = obj.read_typetree()
                tree["m_Name"] = "ch9999_co0035_body"
                obj.save_typetree(tree)
        owners = []
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = Path(directory) / "costume.unity", Path(directory) / "modinstall.txt"
            path.write_bytes(next(iter(environment.files.values())).save())
            manifest.write_text("chara_id = 209\ncostume_file = 'costume.unity'\n")
            def capture_owner(stage, rig, loaded, deadline):
                owners.append(rig.owner)
                return []
            with patch.object(model_motion.MotionInputs, "automatic", capture_owner):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": False,
                    "manifest_paths": [str(manifest)], "allow_download": False})
        self.assertTrue(metadata["rig"]["available"])
        self.assertEqual(owners, [209])

    def test_completed_automatic_pose_survives_optional_expression_lookup_failure(self):
        from webtools.core import model_animation, model_motion
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips())
            with patch.object(model_motion.MotionInputs, "automatic", return_value=[str(FIXTURE)]), \
                    patch.object(model_animation, "discover_animation_paths", side_effect=OSError("optional expression lookup")):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": False})
            document, _ = unpack(metadata)
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
        self.assertEqual(len(document["animations"]), 1)
        self.assertEqual(metadata["rig"]["animationWarnings"][-1]["code"], "animation_unavailable")

    def test_automatic_motion_survives_partially_appended_face_failure(self):
        from webtools.core import model_motion
        from test_model_faces import FaceTests, bundle
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, donor = root / "rig.unity", root / "original.unity"
            path.write_bytes(self.owner_rig_without_clips())
            donor.write_bytes(bundle([(name + ".assets", FaceTests.scene(self, name)) for name in ("Face", "Eyes")]))
            append = viewer._append_scene

            def fail_after_append(*args, **kwargs):
                result = append(*args, **kwargs)
                if kwargs.get("auto_only"):
                    raise OSError("optional facial geometry failed after appending")
                return result

            with patch.object(viewer, "_append_scene", side_effect=fail_after_append), \
                    patch.object(model_motion.MotionInputs, "automatic", return_value=[str(FIXTURE)]) as automatic:
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True,
                    "allow_download": False, "library_roots": [str(root)], "cache_dir": str(root / "cache")})
            automatic.assert_called_once()
            document, _ = unpack(metadata)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["faces"]["added"], 0)
        self.assertEqual(metadata["stats"]["meshes"], 1)
        self.assertEqual(len(document["meshes"]), 1)
        self.assertEqual(len(document["skins"]), 1)
        self.assertTrue(all(joint < len(document["nodes"]) for skin in document["skins"] for joint in skin["joints"]))
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])

    def test_automatic_motion_recovers_from_partially_loaded_face_environment(self):
        from webtools.core import model_faces, model_motion
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips())
            environment = viewer._environment
            attempts = [0]

            def fail_optional_load(paths, deadline, base_env=None):
                if paths == ["broken-face.unity"]:
                    # Simulate an optional import corrupting its shared state
                    # before it can return. Recovery must load a fresh body.
                    base_env.files["half-loaded-face"] = object()
                    attempts[0] += 1
                    raise OSError("partial optional asset import")
                return environment(paths, deadline, base_env=base_env)

            with patch.object(model_faces.FacePlan, "resolve", return_value=["broken-face.unity"]), \
                    patch.object(viewer, "_paths", side_effect=lambda paths: paths), \
                    patch.object(viewer, "_environment", side_effect=fail_optional_load), \
                    patch.object(model_motion.MotionInputs, "automatic", return_value=[str(FIXTURE)]):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True})
        self.assertEqual(attempts[0], 1)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["stats"]["meshes"], 1)
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])

    def test_unbound_selected_clip_does_not_suppress_local_companion_search(self):
        from webtools.core import model_animation
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips(unbound_clip=True))
            with patch.object(model_animation, "discover_animation_paths", return_value=[]) as discovery:
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": False})
            self.assertTrue(metadata["rig"]["available"])
            self.assertEqual(metadata["rig"]["clips"], [])
            discovery.assert_called_once()
            self.assertEqual(metadata["faces"]["status"], "not_needed")

    def test_disabled_faces_get_clamped_optional_deadline_after_base_completion(self):
        from webtools.core import model_animation, model_motion
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rig.unity"
            path.write_bytes(self.owner_rig_without_clips())
            baseline = viewer.prepare([str(path)], rigged=True)
            original, clock, finish, motion_deadlines = viewer.get_model(baseline["id"]), [0.], viewer._to_glb, []

            def finish_then_expire(*args, **kwargs):
                result = finish(*args, **kwargs)
                clock[0] = 120.
                return result

            def optional_motion(stage, rig, loaded, deadline):
                motion_deadlines.append(deadline)
                self.assertEqual(deadline, 160.)
                return []

            with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(viewer, "_to_glb", side_effect=finish_then_expire), \
                    patch.object(model_motion.MotionInputs, "automatic", optional_motion), \
                    patch.object(model_animation, "discover_animation_paths", return_value=[]):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": False})
                self.assertEqual(viewer.get_model(metadata["id"]), original)
        self.assertEqual(motion_deadlines, [160.])
        self.assertEqual(metadata["faces"], baseline["faces"])
        self.assertEqual(metadata["warnings"], baseline["warnings"])

    def test_late_body_faces_and_motion_share_deadline_through_real_readers(self):
        from webtools.core import model_motion, model_rig
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            clock, geometry_calls = [0.], [0]
            observed = {key: [] for key in ("scene", "rig", "materials", "decode", "motion")}
            geometry, scene_init = viewer._geometry, viewer._Scene.__init__
            rig_update, texture, decode_image = model_rig.RigBuilder.update, viewer._Materials.texture, viewer.decode._android_image

            def timed_geometry(*args, **kwargs):
                geometry_calls[0] += 1
                clock[0] = 119. if geometry_calls[0] == 1 else 150.
                return geometry(*args, **kwargs)

            def inspect_scene(scene, env, deadline, trees=None):
                observed["scene"].append(deadline)
                return scene_init(scene, env, deadline, trees=trees)

            def inspect_rig(rig, scene, faces, deadline):
                self.assertEqual(scene.deadline, deadline)
                observed["rig"].append(deadline)
                return rig_update(rig, scene, faces, deadline)

            def inspect_texture(materials, obj):
                observed["materials"].append(materials.scene.deadline)
                return texture(materials, obj)

            def inspect_decode(texture, deadline):
                observed["decode"].append(deadline)
                return decode_image(texture, deadline)

            def optional_motion(stage, rig, loaded, deadline):
                observed["motion"].append(deadline)
                self.assertEqual(deadline, 160.)
                self.assertEqual(rig.deadline, deadline)
                self.assertEqual(rig.scene.deadline, deadline)
                clock[0] = 158.
                return [str(FIXTURE)]

            with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(viewer, "_geometry", timed_geometry), \
                    patch.object(viewer._Scene, "__init__", inspect_scene), \
                    patch.object(model_rig.RigBuilder, "update", inspect_rig), \
                    patch.object(viewer._Materials, "texture", inspect_texture), \
                    patch.object(viewer.decode, "_android_image", inspect_decode), \
                    patch.object(model_motion.MotionInputs, "automatic", optional_motion):
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
                document, _ = unpack(metadata)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 2)
        self.assertEqual(metadata["stats"]["meshes"], 3)
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
        self.assertEqual(len(document["meshes"]), 3)
        for phase in ("scene", "rig", "materials", "decode"):
            self.assertIn(160., observed[phase], phase)
            self.assertTrue(all(deadline <= 160. for deadline in observed[phase]), (phase, observed[phase]))
        self.assertEqual(observed["scene"][0], 120.)
        self.assertEqual(observed["decode"][0], 120.)
        self.assertEqual(observed["motion"], [160.])

    def test_early_body_preserves_fixed_rigged_face_and_later_motion_allowance(self):
        from webtools.core import model_motion
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            clock, geometry_calls, motion_deadlines = [0.], [0], []
            geometry = viewer._geometry

            def timed_geometry(*args, **kwargs):
                geometry_calls[0] += 1
                clock[0] = 50. if geometry_calls[0] == 1 else 125.
                return geometry(*args, **kwargs)

            def optional_motion(stage, rig, loaded, deadline):
                motion_deadlines.append(deadline)
                self.assertEqual(deadline, 160.)
                self.assertEqual(rig.deadline, deadline)
                self.assertEqual(rig.scene.deadline, deadline)
                clock[0] = 150.
                return [str(FIXTURE)]

            with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(viewer, "_geometry", timed_geometry), \
                    patch.object(model_motion.MotionInputs, "automatic", optional_motion):
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
                document, _ = unpack(metadata)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 2)
        self.assertEqual(metadata["stats"]["meshes"], 3)
        self.assertEqual(len(document["meshes"]), 3)
        self.assertEqual(motion_deadlines, [160.])
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])

    def test_late_body_motion_uses_remaining_shared_allowance_with_faces_on_or_off(self):
        from webtools.core import model_faces, model_motion
        for enabled in (False, True):
            with self.subTest(faces_enabled=enabled), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "rig.unity"
                path.write_bytes(self.owner_rig_without_clips())
                clock, calls = [0.], []
                geometry = viewer._geometry

                def late_body(*args, **kwargs):
                    clock[0] = 119.
                    return geometry(*args, **kwargs)

                def face_lookup(plan):
                    self.assertEqual(plan.deadline, 159.)
                    clock[0] = 150.
                    return []

                def optional_motion(stage, rig, loaded, deadline):
                    calls.append(deadline)
                    self.assertEqual(deadline, 160. if enabled else 159.)
                    self.assertEqual(rig.deadline, deadline)
                    self.assertEqual(rig.scene.deadline, deadline)
                    clock[0] = 158.
                    return [str(FIXTURE)]

                with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(viewer, "_geometry", late_body), \
                        patch.object(model_faces.FacePlan, "resolve", face_lookup), \
                        patch.object(model_motion.MotionInputs, "automatic", optional_motion):
                    metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": enabled})
                self.assertEqual(calls, [160. if enabled else 159.])
                self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])
                self.assertEqual(metadata["faces"]["enabled"], enabled)

    def test_failed_face_recovery_keeps_original_optional_deadline_and_clean_geometry(self):
        from webtools.core import model_motion
        cases = ((50., 70., 145., 150., 160.), (119., 130., 145., 150., 160.))
        for body_at, failure_at, recovery_at, motion_at, optional_end in cases:
            with self.subTest(body_finished_at=body_at), tempfile.TemporaryDirectory() as directory:
                path, context = self._face_budget_inputs(directory)
                clock, body_attempts, motion_deadlines = [0.], [0], []
                append = viewer._append_scene

                def partial_face(scene, glb, faces, deadline, **kwargs):
                    if kwargs.get("auto_only"):
                        self.assertEqual(deadline, optional_end)
                        clock[0] = failure_at
                        append(scene, glb, faces, deadline, **kwargs)
                        raise OSError("face failed after mutating the shared GLB")
                    body_attempts[0] += 1
                    clock[0] = body_at if body_attempts[0] == 1 else recovery_at
                    return append(scene, glb, faces, deadline, **kwargs)

                def optional_motion(stage, rig, loaded, deadline):
                    motion_deadlines.append(deadline)
                    self.assertEqual(deadline, optional_end)
                    self.assertEqual(rig.scene.deadline, deadline)
                    self.assertEqual(rig.deadline, deadline)
                    clock[0] = motion_at
                    return [str(FIXTURE)]

                with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(viewer, "_append_scene", partial_face), \
                        patch.object(model_motion.MotionInputs, "automatic", optional_motion):
                    metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
                    document, _ = unpack(metadata)
                self.assertEqual(body_attempts[0], 2)
                self.assertEqual(motion_deadlines, [optional_end])
                self.assertEqual(metadata["faces"]["status"], "unavailable")
                self.assertEqual(metadata["faces"]["added"], 0)
                self.assertEqual(metadata["stats"]["meshes"], 1)
                self.assertEqual(len(document["meshes"]), 1)
                self.assertEqual(len(document["skins"]), 1)
                self.assertTrue(all(joint < len(document["nodes"]) for skin in document["skins"] for joint in skin["joints"]))
                self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing"])

    def test_expired_optional_face_append_preserves_base_without_recovery_or_motion(self):
        from webtools.core import model_motion
        with tempfile.TemporaryDirectory() as directory:
            path, context = self._face_budget_inputs(directory)
            baseline = viewer.prepare([str(path)], rigged=True)
            original = viewer.get_model(baseline["id"])
            clock, body_attempts = [0.], [0]
            append = viewer._append_scene

            def expire_after_partial_face(scene, glb, faces, deadline, **kwargs):
                if kwargs.get("auto_only"):
                    self.assertEqual(deadline, 160.)
                    clock[0] = 150.
                    append(scene, glb, faces, deadline, **kwargs)
                    clock[0] = 160.
                    raise viewer.ModelViewerError("optional facial append expired")
                body_attempts[0] += 1
                clock[0] = 119.
                return append(scene, glb, faces, deadline, **kwargs)

            with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(viewer, "_append_scene", expire_after_partial_face), \
                    patch.object(model_motion.MotionInputs, "automatic") as automatic:
                metadata = viewer.prepare([str(path)], rigged=True, face_context=context)
                self.assertEqual(viewer.get_model(metadata["id"]), original)
            automatic.assert_not_called()
        self.assertEqual(body_attempts[0], 1)
        self.assertEqual(metadata["stats"], baseline["stats"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["faces"]["added"], 0)

    def test_already_present_faces_survive_unrelated_motion_load_failure(self):
        from webtools.core import model_animation
        from test_model_faces import FaceTests, bundle
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "complete.unity"
            path.write_bytes(bundle([("rig.assets", self.owner_rig_without_clips()), ("face.assets", FaceTests.scene(self, "Face")), ("eyes.assets", FaceTests.scene(self, "Eyes"))]))
            baseline = viewer.prepare([str(path)], rigged=True)
            environment = viewer._environment

            def fail_motion(paths, deadline, base_env=None):
                if base_env is not None:
                    raise viewer.ModelViewerError("motion import took too long")
                return environment(paths, deadline)

            with patch.object(model_animation, "discover_animation_paths", return_value=[str(path)]), patch.object(viewer, "_environment", side_effect=fail_motion):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True})
            self.assertEqual(viewer.get_model(metadata["id"]), viewer.get_model(baseline["id"]))
        self.assertEqual(metadata["faces"]["status"], "already_present")
        self.assertEqual(metadata["faces"]["added"], 0)
        self.assertFalse(any(row["code"] == "face_source_unavailable" for row in metadata["warnings"]))

    def test_valid_rigged_face_render_uses_global_time_after_bounded_lookup(self):
        from test_model_faces import FaceTests, bundle
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, donor = root / "rig.unity", root / "Setsuna_original.unity"
            path.write_bytes(self.owner_rig_without_clips())
            donor.write_bytes(bundle([(name + ".assets", FaceTests.scene(self, name)) for name in ("Face", "Eyes")]))
            geometry, clock = viewer._geometry, [0.]

            # Explicit counter avoids depending on a display mesh's name.
            calls = [0]
            def times(mesh, *args, **kwargs):
                calls[0] += 1
                clock[0] = 50. if calls[0] == 1 else 95.
                return geometry(mesh, *args, **kwargs)
            with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), patch.object(viewer, "_geometry", side_effect=times):
                metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True, "allow_download": False,
                    "library_roots": [str(root)], "cache_dir": str(root / "cache")})
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 2)
        self.assertEqual(metadata["stats"]["meshes"], 3)

    def test_rigged_face_global_timeout_retains_original_completed_body(self):
        from test_model_faces import FaceTests, bundle
        for expired_at in (160., 161.):
            with self.subTest(facial_geometry_finished_at=expired_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, donor = root / "rig.unity", root / "Setsuna_original.unity"
                path.write_bytes(self.owner_rig_without_clips())
                donor.write_bytes(bundle([(name + ".assets", FaceTests.scene(self, name)) for name in ("Face", "Eyes")]))
                baseline = viewer.prepare([str(path)], rigged=True)
                original, geometry, clock, calls = viewer.get_model(baseline["id"]), viewer._geometry, [0.], [0]
                def times(mesh, *args, **kwargs):
                    calls[0] += 1
                    clock[0] = 50. if calls[0] == 1 else expired_at
                    return geometry(mesh, *args, **kwargs)
                with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), patch.object(viewer, "_geometry", side_effect=times):
                    metadata = viewer.prepare([str(path)], rigged=True, face_context={"enabled": True, "allow_download": False,
                        "library_roots": [str(root)], "cache_dir": str(root / "cache")})
                    self.assertEqual(viewer.get_model(metadata["id"]), original)
                self.assertEqual(metadata["stats"], baseline["stats"])
                self.assertEqual(metadata["faces"]["status"], "unavailable")


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
            self.assertEqual(len(clips), 21)
            preview = metadata["rig"]["previewMotion"]
            self.assertTrue(preview["verified"])
            self.assertEqual(preview["origin"], "bundled")
            self.assertEqual(len([clip for clip in clips if clip["name"] == preview["name"]]), 1)
            self.assertEqual(len([clip for clip in clips if clip["sourceName"].startswith("ch0207_")]), 20)
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


class RigPathScene:
    def __init__(self):
        self.records = {}
        self.tree_reads = self.name_reads = 0

    def add(self, name, parent=None, *, asset=None, index=None):
        asset = asset if asset is not None else object()
        index = index if index is not None else len(self.records) + 1
        game = SimpleNamespace(assets_file=asset, path_id=index * 2, name=name)
        transform = SimpleNamespace(assets_file=asset, path_id=index * 2 + 1)
        self.records[viewer._key(transform)] = {"m_GameObject": game, "m_Father": parent}
        return transform

    def tree(self, transform):
        self.tree_reads += 1
        return self.records[viewer._key(transform)]

    def name(self, game):
        self.name_reads += 1
        return game.name


class RigPathCacheTests(unittest.TestCase):
    def setUp(self):
        self.resolve = patch.object(viewer, "_ref", side_effect=lambda owner, pointer: pointer)
        self.resolve.start()
        self.addCleanup(self.resolve.stop)

    def builder(self, scene):
        value = RigBuilder.__new__(RigBuilder)
        value.scene, value.deadline, value._path_cache = scene, float("inf"), {}
        return value

    def chain(self, scene, names, *, asset=None):
        result, parent = [], None
        for index, name in enumerate(names, 1):
            parent = scene.add(name, parent, asset=asset, index=index)
            result.append(parent)
        return result

    def test_paths_keep_omitted_root_unicode_and_empty_segments(self):
        for names, expected in (
            (["Reference"], ""),
            (["Reference", "Head", "Face"], "Head/Face"),
            (["", "머리", "얼굴"], "머리/얼굴"),
            (["Reference", "", "Face"], "/Face"),
            (["Reference", "Head", ""], "Head/"),
            (["Reference", "", ""], "/"),
        ):
            with self.subTest(names=names):
                scene = RigPathScene()
                nodes = self.chain(scene, names)
                builder = self.builder(scene)
                # Warm a parent prefix separately before extending it.
                if len(nodes) > 1:
                    builder._path(nodes[-2])
                self.assertEqual(builder._path(nodes[-1]), expected)
                self.assertEqual(builder._path(nodes[-1]), expected)

    def test_equal_path_ids_in_different_asset_files_do_not_alias(self):
        scene = RigPathScene()
        first = self.chain(scene, ["Reference", "Head"], asset=object())
        second = self.chain(scene, ["Reference", "Hair"], asset=object())
        builder = self.builder(scene)
        self.assertEqual(builder._path(first[-1]), "Head")
        self.assertEqual(builder._path(second[-1]), "Hair")

    def test_cached_ancestor_retains_full_depth_limit(self):
        scene = RigPathScene()
        nodes = self.chain(scene, ["x"] * 257)
        builder = self.builder(scene)
        self.assertEqual(builder._path(nodes[254]).count("/"), 253)
        self.assertEqual(builder._path(nodes[255]).count("/"), 254)
        with self.assertRaisesRegex(RigError, "circular"):
            builder._path(nodes[256])

    def test_cold_depth_limit_matches_cached_limit(self):
        scene = RigPathScene()
        nodes = self.chain(scene, ["x"] * 257)
        with self.assertRaisesRegex(RigError, "circular"):
            self.builder(scene)._path(nodes[-1])

    def test_root_bytes_still_count_when_cached_output_omits_root(self):
        scene = RigPathScene()
        nodes = self.chain(scene, ["x" * 1023] * 4 + [""])
        builder = self.builder(scene)
        self.assertEqual(len(builder._path(nodes[3])), 3071)
        # Four names plus their separators already cost the full4096bytes.
        # An empty fifth component still costs one byte, despite the root
        # being absent from the returned relative path.
        with self.assertRaisesRegex(RigError, "byte limit"):
            builder._path(nodes[4])

    def test_utf8_name_limit_counts_bytes_even_for_omitted_root(self):
        scene = RigPathScene()
        valid = scene.add("가" * 341)
        invalid = scene.add("가" * 342)
        builder = self.builder(scene)
        self.assertEqual(builder._path(valid), "")
        with self.assertRaisesRegex(RigError, "byte limit"):
            builder._path(invalid)

    def test_cycle_rejected_without_populating_cache(self):
        scene = RigPathScene()
        root, child = self.chain(scene, ["Reference", "Head"])
        scene.records[viewer._key(root)]["m_Father"] = child
        builder = self.builder(scene)
        with self.assertRaisesRegex(RigError, "circular"):
            builder._path(child)
        self.assertEqual(builder._path_cache, {})

    def test_update_invalidates_paths_for_replaced_scene(self):
        asset = object()
        first, second = RigPathScene(), RigPathScene()
        old = self.chain(first, ["Reference", "Head"], asset=asset)
        new = self.chain(second, ["Reference", "Hair"], asset=asset)
        builder = self.builder(first)
        self.assertEqual(builder._path(old[-1]), "Head")
        builder.update(second, None, float("inf"))
        self.assertEqual(builder._path_cache, {})
        self.assertEqual(builder._path(new[-1]), "Hair")

    def test_update_cannot_hide_new_cycle_behind_cached_prefix(self):
        scene = RigPathScene()
        root, child = self.chain(scene, ["Reference", "Head"])
        builder = self.builder(scene)
        self.assertEqual(builder._path(child), "Head")
        scene.records[viewer._key(root)]["m_Father"] = child
        builder.update(scene, None, float("inf"))
        with self.assertRaisesRegex(RigError, "circular"):
            builder._path(child)

    def test_deadline_is_checked_for_cache_hit(self):
        scene = RigPathScene()
        node = scene.add("Reference")
        builder = self.builder(scene)
        builder._path(node)
        before = scene.tree_reads
        builder.deadline = 1.
        with patch.object(viewer.time, "monotonic", return_value=1.):
            with self.assertRaisesRegex(viewer.ModelViewerError, "too long"):
                builder._path(node)
        self.assertEqual(scene.tree_reads, before)

    def test_shared_ancestors_are_read_once_per_scene(self):
        scene = RigPathScene()
        chain = self.chain(scene, ["Reference"] + ["Bone"] * 63)
        leaves = [scene.add("Leaf" + str(index), chain[-1]) for index in range(128)]
        builder = self.builder(scene)
        for node in leaves:
            builder._path(node)
        self.assertEqual(scene.name_reads, 64 + 128)
        self.assertEqual(scene.tree_reads, 2 * (64 + 128))
        before = scene.tree_reads
        for node in leaves:
            builder._path(node)
        self.assertEqual(scene.tree_reads, before)

    def test_cache_is_bounded_without_changing_uncached_paths(self):
        scene = RigPathScene()
        root = scene.add("Reference")
        builder = self.builder(scene)
        for index in range(MAX_NODES + 20):
            node = scene.add("Leaf" + str(index), root)
            self.assertEqual(builder._path(node), "Leaf" + str(index))
        self.assertEqual(len(builder._path_cache), MAX_NODES)


if __name__ == "__main__":
    unittest.main()
