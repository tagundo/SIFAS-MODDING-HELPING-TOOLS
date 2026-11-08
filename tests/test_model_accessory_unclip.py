"""Serialized neutral accessory geometry and independent legacy-CLI oracles.

The fixture uses only this repository's generated typed Unity templates. Nine
cloth vertices belong to BreastSize; six ornament vertices belong to a separate
PartsA_Offset subtree parented to Spine2. No game/user model is included.
"""
import copy
import importlib.util
from pathlib import Path
import secrets
import struct
import tempfile
import unittest

import numpy as np
import UnityPy
from webtools.core import model_edits as edits, model_viewer
import sifas_accessory_unclip as legacy


def make_fixture(*, authored_scale=(1., 1., 1.), source_scale=(1.5, 1.5, 1.5),
                 rotated_parent=False, ambiguous_renderers=False,
                 external_weighted_bone=False):
    """Return original, serialized, skinned Unity bytes with real overlap."""
    path = Path(__file__).with_name("generate_viewer_body_fixture.py")
    spec = importlib.util.spec_from_file_location("accessory_neutral_fixture_writer", path)
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    move_rotation = (11., 17., -8.) if rotated_parent else (0., 0., 0.)
    move_scale = (1.2, .9, 1.1) if rotated_parent else (1., 1., 1.)
    parent_rotation = (-7., 13., 9.) if rotated_parent else (0., 0., 0.)
    parent_scale = (.95, 1.08, 1.04) if rotated_parent else (1., 1., 1.)
    writer.BONES = (
        ("Move", None, (0., 0., 0.), move_rotation, move_scale),
        ("Spine2", "Move", (.1, .35, .1), parent_rotation, parent_scale),
        ("BreastSize", "Spine2", (0., 0., 0.), (0., 0., 0.), tuple(authored_scale)),
        ("LeftBreast", "BreastSize", (0., .1, .01), (0., 0., 0.), (1., 1., 1.)),
        ("RightBreast", "BreastSize", (0., -.1, -.01), (0., 0., 0.), (1., 1., 1.)),
        ("PartsA_Offset", "Spine2", (.01, .02, .02), (0., 0., 0.), (1., 1., 1.)),
        ("PartsA_Tip", "PartsA_Offset", (.01, 0., .01), (0., 0., 0.), (1., 1., 1.)),
    )
    original = UnityPy.load(writer.SOURCE.read_bytes())
    record = copy.deepcopy(next(obj for obj in original.objects
                                if obj.type.name == "MonoBehaviour").read_typetree()["scaleValues"][0])
    env = UnityPy.load(writer.fixture_bytes())
    objects = {obj.path_id: obj for obj in env.objects}
    names = {obj.path_id: obj.read_typetree()["m_Name"]
             for obj in env.objects if obj.type.name == "GameObject"}
    transforms = {names[obj.read_typetree()["m_GameObject"]["m_PathID"]]: obj.path_id
                  for obj in env.objects if obj.type.name == "Transform"}
    record.update(target={"m_FileID": 0, "m_PathID": transforms["BreastSize"]},
                  originValue=dict(zip("xyz", authored_scale)),
                  scaledValue=dict(zip("xyz", source_scale)))
    component = objects[16].read_typetree()
    component.update(scaleValues=[record], positionValues=[], rotationValues=[])
    objects[16].save_typetree(component)
    mesh = objects[1].read_typetree()
    vertex_data = mesh["m_VertexData"]
    buffer = bytearray(vertex_data["m_DataSize"])
    stride = len(buffer) // vertex_data["m_VertexCount"]
    assert stride == 56
    for index in range(vertex_data["m_VertexCount"]):
        struct.pack_into("<2f", buffer, index * stride + 24,
                         .13 + index * .07, .21 + (index % 4) * .09)
        struct.pack_into("<4B", buffer, index * stride + 52,
                         70 + index, 120 + index, 170 + index, 255)
    # The legacy CLI's source format stores four uint32 skin indices. Preserve
    # that layout here so it remains an independent unchanged-tool oracle.
    expanded = bytearray()
    for index in range(vertex_data["m_VertexCount"]):
        record_bytes = buffer[index * stride:(index + 1) * stride]
        expanded += record_bytes[:48] + struct.pack("<4I", *record_bytes[48:52]) + record_bytes[52:]
    vertex_data["m_Channels"][13]["format"] = 10
    for channel in vertex_data["m_Channels"]:
        if channel.get("dimension", 0) and channel["stream"] == 0 and channel["offset"] >= 52:
            channel["offset"] += 12
    vertex_data["m_DataSize"] = bytes(expanded)
    objects[1].save_typetree(mesh)
    renderer = objects[12].read_typetree()
    if external_weighted_bone:
        # LeftBreast has three positive-weight vertices, not merely an unused
        # zero-weight slot with a stale external pointer.
        renderer["m_Bones"][3]["m_FileID"] = 1
        objects[12].save_typetree(renderer)
    if ambiguous_renderers:
        duplicate = copy.copy(objects[12]); duplicate.path_id = 900
        duplicate.save_typetree(copy.deepcopy(renderer))
        objects[12].assets_file.objects[900] = duplicate
        owner = objects[renderer["m_GameObject"]["m_PathID"]]
        owner_tree = owner.read_typetree()
        owner_tree["m_Component"].append({"component": {"m_FileID": 0, "m_PathID": 900}})
        owner.save_typetree(owner_tree)
    return env.file.save()


fixture_bytes = make_fixture


IDEAL_CENTROID_PARENT = np.array((.25166666666666665, .013333333333333334, .025))
IDEAL_LIFT = .5 * IDEAL_CENTROID_PARENT
TOLERANCE = 2e-6


def transform_key(info, name):
    return next(key for key, value in info["names"].items() if value == name)


def anchor_position(raw):
    info = edits._inspect(raw)
    return np.array(info["authored"][transform_key(info, "PartsA_Offset")]["position"])


def preserved_payloads(raw, *, include_all_stream=False):
    """Compare uninterpreted object/channel bytes, not exported screenshots."""
    from sifas_mesh_baker import stream_layout
    env = UnityPy.load(raw)
    result = {}
    for obj in env.objects:
        if obj.type.name in ("Texture2D", "Material", "Shader"):
            result[(obj.type.name, obj.path_id)] = bytes(obj.get_raw_data())
        if obj.type.name != "Mesh":
            continue
        tree = obj.read_typetree()
        count, channels, stride, start, _ = stream_layout(tree)
        data = bytes(tree["m_VertexData"]["m_DataSize"])
        result[("mesh-bindposes", obj.path_id)] = tree["m_BindPose"]
        result[("mesh-channels", obj.path_id)] = channels
        result[("mesh-indices", obj.path_id)] = bytes(tree["m_IndexBuffer"])
        for channel in (3, 4, 12, 13):  # Colour, nonzero UV, weights and uint32 joints.
            declaration = channels[channel]
            if not declaration.get("dimension", 0):
                continue
            assert declaration["stream"] == 0
            width = declaration["dimension"] * {0: 4, 2: 1, 6: 1, 10: 4}[declaration["format"]]
            offset = start[declaration["stream"]] + declaration["offset"]
            step = stride[declaration["stream"]]
            result[("channel", obj.path_id, channel)] = b"".join(
                data[offset + i * step:offset + i * step + width] for i in range(count))
        if include_all_stream:
            result[("all-mesh-stream", obj.path_id)] = data
    return result


def effective_world_vertices(path):
    """Independent legacy reader + actual saved skin, including runtime scales."""
    model = legacy.Model(str(path))
    for name, scale in model.node_scalings().items():
        model.tf[model.tfpid_of(name)]["m_LocalScale"] = dict(zip("xyz", scale))
    worlds = model.world()
    renderer = model.costume_smr().read_typetree()
    bones = [row["m_PathID"] for row in renderer["m_Bones"]]
    mesh = model.mesh[renderer["m_Mesh"]["m_PathID"]].read_typetree()
    count, channels, stride, start = legacy._stream_layout(mesh)
    data = np.frombuffer(mesh["m_VertexData"]["m_DataSize"], np.uint8)
    points = legacy._read_chan(data, channels, 0, stride, start, count, "<f4")
    weights = legacy._read_chan(data, channels, 12, stride, start, count, "<f4")
    joints = legacy._read_chan(data, channels, 13, stride, start, count, "<u4")
    matrices = np.array([worlds[bone] @ legacy._bp_mat(pose)
                         for bone, pose in zip(bones, mesh["m_BindPose"])])
    homogeneous = np.column_stack((points, np.ones(count)))
    world = np.zeros((count, 3))
    for column in range(4):
        world += weights[:, column:column + 1] * np.einsum(
            "vij,vj->vi", matrices[joints[:, column]], homogeneous)[:, :3]
    return world


class AccessoryGeometryOracleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="accessory-oracle-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.sequence = 0

    def session(self, raw=None):
        raw = make_fixture() if raw is None else raw
        self.sequence += 1
        source = self.base / ("source-" + str(self.sequence) + ".unity")
        source.write_bytes(raw)
        rig = model_viewer.prepare([str(source)], rigged=True,
                                  face_context={"enabled": False, "allow_download": False})["rig"]
        token = secrets.token_hex(16)
        metadata = edits.register_session(token, [str(source)], rig)
        self.addCleanup(edits._SESSIONS.pop, token, None)
        nodes = {row["name"]: row["node"] for row in metadata["nodes"]}
        return token, source, raw, nodes

    def state(self, *changes, **settings):
        return {"version": 1, "savedSettingsEnabled": True, "edits": list(changes),
                "accessoryUnclip": {"strength": 1., "overlap": .15, "closeGaps": False, **settings}}

    def export(self, token, state):
        self.sequence += 1
        result = edits.export(token, state, self.base / ("output-" + str(self.sequence)))
        path = Path(result["preview_paths"][0])
        return path, path.read_bytes(), result

    def preview_delta(self, token, nodes, state):
        result = edits.accessory_preview(token, state)
        self.assertEqual(result["summary"]["status"], "applied")
        self.assertEqual(result["summary"]["changed"], 1)
        self.assertEqual(result["corrections"][0]["node"], nodes["PartsA_Offset"])
        return np.array(result["corrections"][0]["delta"])

    def test_fixture_has_real_cloth_overlap_and_matches_unchanged_cli(self):
        token, source, raw, nodes = self.session()
        self.assertEqual(raw, make_fixture())
        analysis = legacy.analyze(legacy.Model(str(source)))
        self.assertEqual(len(analysis["nodes"]), 1)
        anchor = analysis["anchors"][0]
        self.assertEqual((anchor["name"], anchor["n_verts"]), ("PartsA_Offset", 6))
        self.assertAlmostEqual(anchor["overlaps"]["BreastSize"], 2 / 3)
        old_position = anchor_position(raw)
        cli_path = self.base / "legacy.unity"
        result = legacy.process(str(source), str(cli_path), verbose=False)
        self.assertEqual(result["status"], "written")
        np.testing.assert_allclose(anchor_position(cli_path.read_bytes()) - old_position,
                                   IDEAL_LIFT, atol=TOLERANCE, rtol=0)
        state = self.state()
        np.testing.assert_allclose(self.preview_delta(token, nodes, state),
                                   IDEAL_LIFT * [-1, 1, 1], atol=TOLERANCE, rtol=0)
        _, saved, _ = self.export(token, state)
        np.testing.assert_allclose(anchor_position(saved), anchor_position(cli_path.read_bytes()),
                                   atol=TOLERANCE, rtol=0)
        self.assertEqual(preserved_payloads(raw, include_all_stream=True),
                         preserved_payloads(saved, include_all_stream=True))
        self.assertEqual(source.read_bytes(), raw)

    def test_mesh_only_same_endpoint_has_nonzero_lift_and_same_rendered_world(self):
        token, source, raw, nodes = self.session()
        node_state = self.state()
        mesh_state = self.state({"node": nodes["BreastSize"], "method": "mesh", "scale": [1.5] * 3})
        node_delta = self.preview_delta(token, nodes, node_state)
        np.testing.assert_allclose(self.preview_delta(token, nodes, mesh_state), node_delta, atol=TOLERANCE, rtol=0)
        node_path, node_raw, _ = self.export(token, node_state)
        mesh_path, mesh_raw, _ = self.export(token, mesh_state)
        self.assertGreater(np.linalg.norm(anchor_position(mesh_raw) - anchor_position(raw)), .1)
        np.testing.assert_allclose(effective_world_vertices(node_path), effective_world_vertices(mesh_path),
                                   atol=TOLERANCE, rtol=0)
        np.testing.assert_allclose(anchor_position(mesh_raw), anchor_position(node_raw), atol=TOLERANCE, rtol=0)
        self.assertEqual(preserved_payloads(raw), preserved_payloads(mesh_raw))
        self.assertEqual(source.read_bytes(), raw)

    def test_authored_nonunit_rotated_parent_uses_absolute_scale_once(self):
        token, source, raw, nodes = self.session(make_fixture(authored_scale=(1.25,) * 3, rotated_parent=True))
        state = self.state()
        expected = .2 * IDEAL_CENTROID_PARENT
        np.testing.assert_allclose(self.preview_delta(token, nodes, state), expected * [-1, 1, 1],
                                   atol=TOLERANCE, rtol=0)
        _, saved, _ = self.export(token, state)
        np.testing.assert_allclose(anchor_position(saved) - anchor_position(raw), expected,
                                   atol=TOLERANCE, rtol=0)
        self.assertEqual(preserved_payloads(raw, include_all_stream=True),
                         preserved_payloads(saved, include_all_stream=True))
        self.assertEqual(source.read_bytes(), raw)

    def test_mixed_mesh_parent_and_node_child_do_not_apply_parent_twice(self):
        token, source, raw, nodes = self.session()
        outputs = []
        for method, local_factor in (("node", 1.), ("mesh", 1.4)):
            state = self.state({"node": nodes["Move"], "method": method, "scale": [1.4] * 3},
                               {"node": nodes["BreastSize"], "method": "node", "scale": [1.5] * 3})
            np.testing.assert_allclose(self.preview_delta(token, nodes, state), IDEAL_LIFT * [-1, 1, 1],
                                       atol=TOLERANCE, rtol=0)
            path, saved, _ = self.export(token, state)
            np.testing.assert_allclose(anchor_position(saved) - anchor_position(raw), local_factor * IDEAL_LIFT,
                                       atol=TOLERANCE, rtol=0)
            self.assertEqual(preserved_payloads(raw), preserved_payloads(saved))
            outputs.append(effective_world_vertices(path))
        np.testing.assert_allclose(outputs[0], outputs[1], atol=TOLERANCE, rtol=0)
        self.assertEqual(source.read_bytes(), raw)

    def test_compensated_mesh_parent_uses_distinct_preview_and_export_frames(self):
        token, source, raw, nodes = self.session()
        state = self.state({"node": nodes["Spine2"], "method": "mesh", "scale": [2.] * 3,
                            "compensate": True,
                            "compensationTargets": [nodes["BreastSize"], nodes["PartsA_Offset"]]},
                           {"node": nodes["BreastSize"], "method": "node", "scale": [1.5] * 3})
        # The desired parent frame is doubled while its serialized runtime
        # frame stays authored. Applying compensation to this delta again
        # would halve the visible lift and fail the world-geometry comparison.
        np.testing.assert_allclose(self.preview_delta(token, nodes, state), .5 * IDEAL_LIFT * [-1, 1, 1],
                                   atol=TOLERANCE, rtol=0)
        path, saved, _ = self.export(token, state)
        np.testing.assert_allclose(anchor_position(saved) - anchor_position(raw), IDEAL_LIFT,
                                   atol=TOLERANCE, rtol=0)
        baseline_path, _, _ = self.export(token, self.state())
        # Only Move/Spine2 own triangles are outside the compensated children.
        np.testing.assert_allclose(effective_world_vertices(path)[6:], effective_world_vertices(baseline_path)[6:],
                                   atol=TOLERANCE, rtol=0)
        self.assertEqual(preserved_payloads(raw), preserved_payloads(saved))
        self.assertEqual(source.read_bytes(), raw)

    def test_preview_repeat_export_restore_and_zero_strength_keep_original_immutable(self):
        token, source, raw, nodes = self.session()
        state = self.state()
        expected = self.preview_delta(token, nodes, state)
        for _ in range(3):
            np.testing.assert_array_equal(self.preview_delta(token, nodes, state), expected)
        _, first, result = self.export(token, state)
        _, second, second_result = self.export(token, state)
        self.assertEqual(first, second)
        self.assertEqual(result["recipe"], second_result["recipe"])
        restored = edits.restore(token, result["recipe"])
        self.assertEqual(restored, edits.validate_state(token, state))
        np.testing.assert_array_equal(self.preview_delta(token, nodes, restored), expected)
        disabled = {"version": 1, "savedSettingsEnabled": True, "edits": []}
        self.assertEqual(edits.accessory_preview(token, disabled)["corrections"], [])
        _, zero, _ = self.export(token, self.state(strength=0))
        self.assertEqual(zero, raw)
        self.assertEqual(source.read_bytes(), raw)

    def test_external_positive_weight_bone_is_rejected_before_import_and_by_writer(self):
        raw = make_fixture(external_weighted_bone=True)
        source = self.base / "external-weighted.unity"
        source.write_bytes(raw)
        with self.assertRaisesRegex(model_viewer.ModelViewerError, "unresolved bone"):
            model_viewer.prepare([str(source)], rigged=True,
                                 face_context={"enabled": False, "allow_download": False})
        # The public importer already stops this source. Independently exercise
        # the writer's source-bound check without inventing an imported session.
        info = edits._inspect(raw)
        targets = {index: {"key": key} for index, key in enumerate(info["transforms"])}
        with self.assertRaisesRegex(edits.ModelEditError, "external"):
            edits._edit_source(raw, [], targets, [], accessory_unclip=self.state()["accessoryUnclip"])
        self.assertEqual(source.read_bytes(), raw)

    def test_equal_dominant_renderers_reject_preview_and_export(self):
        token, source, raw, _ = self.session(make_fixture(ambiguous_renderers=True))
        with self.assertRaisesRegex(edits.ModelEditError, "ambiguous"):
            edits.accessory_preview(token, self.state())
        with self.assertRaisesRegex(edits.ModelEditError, "ambiguous"):
            self.export(token, self.state())
        self.assertEqual(source.read_bytes(), raw)
