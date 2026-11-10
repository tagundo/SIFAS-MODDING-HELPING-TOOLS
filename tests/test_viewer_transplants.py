"""Real UnityFS costume grafts and source-bound workspace validation."""
import os
import hashlib
import copy
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy

from webtools.core import model_edits, model_viewer, viewer_transplants
from webtools.jobs import Job
from viewer_scene_fixture import bundle_fixture


def costume_fixture():
    """Give original neutral geometry the game's three-stream skin layout.

    One visible triangle at Y=.60–.70 is leg-weighted. Other independently
    weighted triangles exercise the real tool's anatomical region filtering.
    """
    env = UnityPy.load(bundle_fixture())
    mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
    tree = mesh.read_typetree(); vertex = tree["m_VertexData"]
    channels = vertex["m_Channels"]; count = vertex["m_VertexCount"]
    raw = vertex["m_DataSize"]; stride = len(raw) // count
    streams = [bytearray(), bytearray(), bytearray()]
    for index in range(count):
        row = raw[index * stride:(index + 1) * stride]
        position = struct.pack("<3f", *[(-.2, .6, 0), (.2, .7, 0), (0, .65, .1)][index]) if index < 3 else row[:12]
        streams[0] += position + row[12:24] + row[52:56]
        streams[1] += row[24:32]
        bones = (8, 0, 0, 0) if index < 3 else struct.unpack("<4B", row[48:52])
        streams[2] += row[32:48] + struct.pack("<4i", *bones)
    for stream in streams:
        stream += bytes(-len(stream) % 16)
    channels[3]["offset"] = 24
    channels[4].update(stream=1, offset=0)
    channels[12].update(stream=2, offset=0)
    channels[13].update(stream=2, offset=16, format=10)
    vertex["m_DataSize"] = b"".join(streams)
    mesh.save_typetree(tree)
    return env.file.save()


class ViewerTransplantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = costume_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "costume.unity"
            path.write_bytes(cls.raw)
            cls.rig = model_viewer.prepare([str(path)], rigged=True,
                face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.source = self.root / "extracted/wearer.unity"
        self.source.parent.mkdir(); self.source.write_bytes(self.raw)
        self.donor = self.source.with_name("donor.unity"); self.donor.write_bytes(self.raw)
        self.token = secrets.token_hex(16)
        self.metadata = model_edits.register_session(self.token, [str(self.source)], self.rig)
        self.node = next(row["node"] for row in self.metadata["nodes"] if row["name"] == "BreastSize")

    def request(self, **changes):
        value = {"token": self.token, "state": {"version": 1, "savedSettingsEnabled": True, "edits": []},
                 "donor": str(self.donor), "variant": "primary", "operation": "costume", "partRoot": "",
                 "cutLow": .5, "cutHigh": .96, "region": "lower"}
        value.update(changes); return value

    def run_graft(self, request):
        validated = viewer_transplants.validate_request(request)
        job = Job(secrets.token_hex(6), "viewer_transplant")
        viewer_transplants.run_transplant(job, validated,
            output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(len(job.output_paths()), 1)
        output = Path(job.output_paths()[0]); self.assertTrue(output.is_file())
        self.assertNotEqual(output, self.source)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)
        self.assertTrue(any(obj.type.name == "SkinnedMeshRenderer" for obj in UnityPy.load(str(output)).objects))
        self.last_job = job
        return output

    def test_real_full_transplant_preserves_current_breast_body_edit(self):
        state = {"version": 1, "savedSettingsEnabled": True,
                 "edits": [{"node": self.node, "method": "node", "scale": [1.25, 1.1, .9]}]}
        output = self.run_graft(self.request(state=state))
        inspected = model_edits._inspect(output.read_bytes())
        key = next(key for key, name in inspected["names"].items() if name == "BreastSize")
        for actual, expected in zip(inspected["effective"][key]["scale"], [1.25, 1.1, .9]):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_real_part_transplant_supports_an_unedited_wearer(self):
        output = self.run_graft(self.request(operation="part", partRoot="BreastSize"))
        self.assertGreater(output.stat().st_size, 0)

    def test_real_lower_body_swap_replaces_only_the_selected_vertical_band(self):
        output = self.run_graft(self.request(operation="lower", cutLow=.5, cutHigh=.96))
        logs = "\n".join(event.get("line", "") for event in self.last_job._events)
        self.assertIn("donor UVs, materials and texture bytes preserved", logs)
        self.assertGreater(output.stat().st_size, 0)

    def test_mesh_edits_are_baked_before_each_graft_and_retained_outside_replaced_geometry(self):
        from webtools.core import viewer_mesh_tools as mesh, viewer_mod_flow as flow
        import numpy as np
        identity = mesh.inspect(self.token)['meshes'][0]['mesh']
        state = {'version': 1, 'meshes': [{'mesh': identity, 'deleteFaces': [6],
            'positions': [{'vertex': 21, 'position': [.7, 1.7, .2]}],
            'weights': [{'vertex': 21, 'influences': [[6, .25], [7, .75]]}]}]}
        original_export = flow.export_current
        for operation in ('costume', 'part', 'lower'):
            exported = []
            def capture(*args, **kwargs):
                result = original_export(*args, **kwargs)
                exported.append(result)
                return result
            with self.subTest(operation=operation), patch.object(flow, 'export_current', side_effect=capture):
                output = self.run_graft(self.request(operation=operation, partRoot='BreastSize',
                    cutHigh=.92, mesh_state=state))
                self.assertEqual(len(exported), 1)
                _, records = mesh._mesh_records(Path(exported[0]['preview_paths'][0]).read_bytes(), 0)
                record = records[0]
                positions, _, weights, indices = mesh._arrays(record[1], record[2])
                self.assertEqual(len(mesh._triangles(record[2], len(positions))[0]), 19)
                np.testing.assert_allclose(positions[21], [.7, 1.7, .2], atol=1e-6)
                influences = {int(i): float(w) for i, w in zip(indices[21], weights[21]) if w > 0}
                self.assertEqual(influences, {6: .25, 7: .75})
                self.assertEqual(exported[0]['recipe']['state'], state)
                if operation != 'costume':
                    _, final_records = mesh._mesh_records(output.read_bytes(), 0)
                    record = final_records[0]
                    positions, _, weights, indices = mesh._arrays(record[1], record[2])
                    np.testing.assert_allclose(positions[21], [.7, 1.7, .2], atol=1e-6)
                    self.assertFalse(any(set(face) == {18, 19, 20}
                        for face in mesh._triangles(record[2], len(positions))[0]))
                    influences = {int(i): float(w) for i, w in zip(indices[21], weights[21]) if w > 0}
                    self.assertEqual(influences, {6: .25, 7: .75})

    def test_invalid_mesh_channel_is_rejected_before_donor_or_output_writes(self):
        for state in ({'version': 2, 'meshes': []}, {'version': True, 'meshes': []},
                      {'version': 1, 'meshes': [], 'path': '/outside'},
                      {'version': 1, 'meshes': [{'position': float('nan')}]}):
            with self.subTest(state=state), self.assertRaises(ValueError):
                viewer_transplants.validate_request(self.request(mesh_state=state))
        self.assertFalse((self.root / 'modded').exists())

    def test_verified_auto_face_outline_companion_survives_body_and_mesh_preexport(self):
        from test_model_outlines import colored_fixture, colors
        from webtools.core import viewer_mesh_tools as mesh
        face = self.source.with_name('custom-edited-face.unity')
        original_face = colored_fixture(); face.write_bytes(original_face)
        self.metadata = model_edits.register_session(self.token, [str(self.source)], self.rig,
            companions=[{'path': str(face), 'sha256': hashlib.sha256(original_face).hexdigest(), 'sourceIndex': 1}])
        outline = next(row for row in self.metadata['outlines']['meshes'] if row['sourceIndex'] == 1)
        state = {'version': 1, 'savedSettingsEnabled': True, 'edits': [],
            'outlines': [{'id': outline['id'], 'factor': 1, 'absolute': 19}]}
        identity = mesh.inspect(self.token)['meshes'][0]['mesh']
        for mesh_state in (None, {'version': 1, 'meshes': [{'mesh': identity, 'deleteFaces': [6]}]}):
            with self.subTest(mesh=mesh_state is not None):
                output = self.run_graft(self.request(operation='part', partRoot='BreastSize',
                    state=state, mesh_state=mesh_state))
                hint = json.loads((output.parent / viewer_transplants.COMPANION_HINT).read_text())
                self.assertEqual(hint['body'], {'file': output.name,
                    'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
                self.assertEqual(len(hint['companions']), 1)
                copied = output.parent / hint['companions'][0]['file']
                self.assertEqual(copied.name, face.name)
                self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), hint['companions'][0]['sha256'])
                saved_mesh = next(obj for obj in UnityPy.load(str(copied)).objects if obj.type.name == 'Mesh')
                self.assertTrue((colors(saved_mesh)[:, 0] == 19).all())
                self.assertEqual(face.read_bytes(), original_face)
                self.assertFalse((output.parent.parent / 'inputs').exists())

    def test_runtime_receipt_binds_the_published_output_and_original_sources(self):
        validated = viewer_transplants.validate_request(self.request())
        job = Job(secrets.token_hex(6), 'viewer_transplant')
        physics_cache = self.root / 'extracted/game-models'
        observed = {}
        def record(output, **values):
            self.assertTrue(Path(output).is_file())
            self.assertFalse(any(p.name == 'inputs' for p in Path(output).parents))
            self.assertEqual(Path(values['donor_path']), self.donor)
            self.assertEqual(values['donor_sha256'], hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(values['cache_root'], physics_cache)
            self.assertIsNone(values['donor_member'])
            observed.update(values)
        with patch('webtools.core.viewer_physics_runtime.record_transplant', side_effect=record):
            viewer_transplants.run_transplant(job, validated, output_root=self.root / 'modded/viewer',
                cache_root=self.root / '.viewer-cache', repo_root=self.root, physics_cache_root=physics_cache)
        self.assertEqual(len(job.output_paths()), 1)
        self.assertEqual(observed['operation'], 'costume')
        self.assertEqual(observed['wearer_source'], validated['sourceIndex'])
        self.assertIsInstance(observed['component_origins'], list)

    def test_failed_runtime_receipt_does_not_publish_a_partial_graft(self):
        validated = viewer_transplants.validate_request(self.request())
        job = Job(secrets.token_hex(6), 'viewer_transplant')
        output_root = self.root / 'modded/viewer'
        with patch('webtools.core.viewer_physics_runtime.record_transplant', side_effect=ValueError('The donor changed')):
            with self.assertRaisesRegex(ValueError, 'donor changed'):
                viewer_transplants.run_transplant(job, validated, output_root=output_root,
                    cache_root=self.root / '.viewer-cache', repo_root=self.root)
        self.assertEqual(job.output_paths(), [])
        self.assertEqual(list(output_root.glob('transplant-*')), [])
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_inspection_returns_real_donor_part_roots(self):
        result = viewer_transplants.inspect_donor(str(self.donor), cache_root=self.root / ".viewer-cache")
        self.assertIn("BreastSize", [part["value"] for part in result["parts"]])
        self.assertEqual(result["platform"], 13)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def selected_request(self, **changes):
        inspected = viewer_transplants.inspect_donor(str(self.donor), cache_root=self.root / ".viewer-cache")
        return self.request(operation="part", partSelectionMode="bones", partRoots=["LeftArm", "RightLeg"],
            includeDescendants=True, triangleIndices=[], donorSha256=inspected["sha256"],
            donorSelectionFingerprint=inspected["selectionFingerprint"],
            donorRenderer=inspected["geometry"]["renderer"], donorMesh=inspected["geometry"]["mesh"], **changes)

    def output_mesh(self, path):
        import costume_part_transplant as part
        env = UnityPy.load(str(path)); objects, index = part._index(env)
        renderer = part._body_smr(objects).read_typetree()
        return index[renderer["m_Mesh"]["m_PathID"]].read_typetree()

    def test_complete_bone_hierarchy_and_original_skin_are_available(self):
        result = viewer_transplants.inspect_donor(str(self.donor), cache_root=self.root / ".viewer-cache")
        rows = {row["value"]: row for row in result["parts"]}
        self.assertEqual(set(rows), set(result["geometry"]["boneNames"]))
        self.assertEqual(rows["LeftForeArm"]["parent"], "LeftArm")
        self.assertEqual(rows["LeftHandIndex1"]["parent"], "LeftHand")
        self.assertEqual(rows["LeftHandIndex1"]["depth"], rows["LeftArm"]["depth"] + 3)
        self.assertEqual(rows["LeftArm"]["bones"], ["LeftArm", "LeftForeArm", "LeftHand", "LeftHandIndex1"])
        self.assertEqual(rows["Move"]["ownVertices"], 0)
        self.assertEqual(rows["Move"]["vertices"], 60)
        self.assertEqual(len(result["geometry"]["skin"]), 60)
        self.assertEqual(result["geometry"]["skin"][0], [[8, 1.], [0, 0.], [0, 0.], [0, 0.]])
        self.assertEqual(result["sha256"], hashlib.sha256(self.raw).hexdigest())

    def test_explicit_renderer_identity_is_kept_when_two_renderers_share_one_mesh(self):
        env = UnityPy.load(self.raw)
        original = next(obj for obj in env.objects if obj.type.name == 'SkinnedMeshRenderer')
        sibling = copy.copy(original); sibling.path_id = 1000; original.assets_file.objects[1000] = sibling
        tree = copy.deepcopy(original.read_typetree()); tree['m_Bones'].reverse(); sibling.save_typetree(tree)
        self.donor.write_bytes(env.file.save())
        result = viewer_transplants.inspect_donor(str(self.donor), renderer='1000', cache_root=self.root / '.viewer-cache')
        self.assertEqual(result['geometry']['renderer'], '1000')
        self.assertEqual(result['geometry']['mesh'], '1')
        self.assertEqual(result['geometry']['boneNames'][0], 'BreastSize')
        self.assertEqual(result['geometry']['boneNames'][-1], 'Move')
        indices = {row['value']: row['index'] for row in result['parts']}
        self.assertEqual(indices['BreastSize'], 0)
        self.assertEqual(indices['Move'], 19)

    def test_multiple_roots_copy_the_union_with_real_children_once(self):
        import costume_part_transplant as part
        request = self.selected_request()
        request["partRoots"] += ["LeftHand"]  # overlapping roots do not duplicate geometry
        validated = viewer_transplants.validate_request(request)
        self.assertEqual(validated["partBones"], ["RightLeg", "RightFoot", "LeftArm", "LeftForeArm", "LeftHand", "LeftHandIndex1"])
        output = self.run_graft(request)
        self.assertEqual(sum(len(group) for group in part.submesh_triangles(self.output_mesh(output))), 26)

    def test_turning_off_child_selection_copies_only_the_selected_bones(self):
        import costume_part_transplant as part
        request = self.selected_request(); request["includeDescendants"] = False
        validated = viewer_transplants.validate_request(request)
        self.assertEqual(validated["partBones"], ["RightLeg", "LeftArm"])
        output = self.run_graft(request)
        self.assertEqual(sum(len(group) for group in part.submesh_triangles(self.output_mesh(output))), 22)

    def test_separate_surface_patches_preserve_exact_source_uvs(self):
        import costume_part_transplant as part
        request = self.selected_request(); request.update(partSelectionMode="triangles", triangleIndices=[0, 5, 19])
        output = self.run_graft(request)
        result = self.output_mesh(output)
        self.assertEqual(sum(len(group) for group in part.submesh_triangles(result)), 23)
        source = self.output_mesh(self.donor)
        def uv(tree):
            import numpy as np
            count, channels, strides, starts, _ = part.stream_layout(tree)
            raw = np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), np.uint8)
            return part.read_attr(raw, 4, channels, strides, starts, count)
        import numpy as np
        np.testing.assert_array_equal(uv(result)[60:], uv(source)[[0, 1, 2, 15, 16, 17, 57, 58, 59]])

    def test_surface_patches_keep_each_source_material_and_its_texture(self):
        import costume_part_transplant as part
        env = UnityPy.load(self.raw); objects, index = part._index(env)
        asset = index[13].assets_file
        for old_id, new_id in ((13, 1000), (14, 1001)):
            obj = copy.copy(index[old_id]); obj.path_id = new_id; asset.objects[new_id] = obj
            tree = copy.deepcopy(index[old_id].read_typetree())
            tree['m_Name'] = 'Second Donor Material' if old_id == 13 else 'Second Donor Texture'
            if old_id == 13:
                tree['m_SavedProperties']['m_TexEnvs'][0][1]['m_Texture']['m_PathID'] = 1001
                tree['m_SavedProperties']['m_Colors'][0][1]['g'] = .3
            obj.save_typetree(tree)
        mesh = index[1].read_typetree(); first = copy.deepcopy(mesh['m_SubMeshes'][0]); second = copy.deepcopy(first)
        first['indexCount'] = 30; second.update(firstByte=60, indexCount=30)
        mesh['m_SubMeshes'] = [first, second]; index[1].save_typetree(mesh)
        renderer = index[12].read_typetree(); renderer['m_Materials'].append({'m_FileID': 0, 'm_PathID': 1000})
        index[12].save_typetree(renderer)
        self.donor.write_bytes(env.file.save())
        donor_raw = self.donor.read_bytes()
        request = self.selected_request(); request.update(partSelectionMode='triangles', triangleIndices=[0, 19])
        job = Job(secrets.token_hex(6), 'viewer_transplant')
        viewer_transplants.run_transplant(job, viewer_transplants.validate_request(request),
            output_root=self.root / 'modded/viewer', cache_root=self.root / '.viewer-cache')
        output = Path(job.output_paths()[0]); saved = UnityPy.load(str(output)); saved_objects, saved_index = part._index(saved)
        result_renderer = part._body_smr(saved_objects).read_typetree()
        result_mesh = saved_index[result_renderer['m_Mesh']['m_PathID']].read_typetree()
        self.assertEqual([len(group) for group in part.submesh_triangles(result_mesh)], [20, 1, 1])
        materials = [saved_index[p['m_PathID']].read_typetree() for p in result_renderer['m_Materials']]
        self.assertEqual([m['m_Name'] for m in materials[-2:]], ['Neutral AS Member test material', 'Second Donor Material'])
        for material, original_id in zip(materials[-2:], [14, 1001]):
            tex_id = material['m_SavedProperties']['m_TexEnvs'][0][1]['m_Texture']['m_PathID']
            self.assertEqual(saved_index[tex_id].read().get_image_data(), asset.objects[original_id].read().get_image_data())
        self.assertEqual(self.donor.read_bytes(), donor_raw)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_surface_and_bone_selections_are_bound_to_the_original_donor(self):
        valid = self.selected_request()
        for changes in ({"donorSha256": "0" * 64}, {"donorSelectionFingerprint": "0" * 64}, {"donorSelectionFingerprint": ""},
                        {"variant": "unmasked"}, {"donorMesh": "123456"}, {"donorRenderer": "1"},
                        {"partRoots": ["NoSuchBone"]}, {"partRoots": ["LeftArm", "LeftArm"]},
                        {"includeDescendants": 1}, {"donorSha256": ""}, {"donorMesh": ""},
                        {"partSelectionMode": "triangles", "triangleIndices": []},
                        {"partSelectionMode": "triangles", "triangleIndices": [20]},
                        {"partSelectionMode": "triangles", "triangleIndices": [0, 0]},
                        {"partSelectionMode": "triangles", "triangleIndices": [True]},
                        {"partSelectionMode": "triangles", "triangleIndices": [0.0]},
                        {"partSelectionMode": "triangles", "triangleIndices": [-1]},
                        {"partSelectionMode": "triangles", "triangleIndices": list(range(200001))}):
            with self.subTest(changes=changes.keys()), self.assertRaises(ValueError):
                viewer_transplants.validate_request({**valid, **changes})
        self.assertFalse((self.root / "modded").exists())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_zip_surface_selection_uses_the_zip_identity_and_one_selected_model(self):
        archive = self.donor.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("costume.unity", self.raw)
        self.donor = archive
        request = self.selected_request(); request.update(partSelectionMode="triangles", triangleIndices=[0, 19])
        self.assertEqual(request["donorSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        validated = viewer_transplants.validate_request(request)
        self.assertEqual(validated["triangleIndices"], [0, 19])
        self.assertEqual(validated["donorRaw"], archive.read_bytes())

    def test_invalid_cut_values_and_extra_paths_are_rejected_before_writes(self):
        for changes in ({"cutLow": 1., "cutHigh": .5}, {"cutLow": float("nan")},
                        {"cutHigh": True}, {"out_dir": "/tmp/attacker"}, {"operation": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                viewer_transplants.validate_request(self.request(**changes))
        self.assertFalse((self.root / "modded").exists())

    def test_colour_matching_is_opt_in_and_options_are_strict(self):
        defaults = viewer_transplants.validate_request(self.request())
        self.assertFalse(defaults["matchSkin"])
        self.assertTrue(defaults["skinOnly"])
        for changes in ({"matchSkin": "false"}, {"skinOnly": 1}, {"selectionScope": "all"},
                        {"donorRenderer": "not-a-renderer"}, {"excludeAccessories": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                viewer_transplants.validate_request(self.request(**changes))

    def test_donor_bytes_are_snapshotted_before_the_background_job(self):
        validated = viewer_transplants.validate_request(self.request())
        self.donor.write_bytes(b"changed after donor selection")
        self.assertEqual(validated["donorRaw"], self.raw)
        job = Job(secrets.token_hex(6), "viewer_transplant")
        viewer_transplants.run_transplant(job, validated,
            output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(len(job.output_paths()), 1)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_paired_target_archive_is_refused_instead_of_leaving_stale_models(self):
        archive = self.root / "extracted/paired.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("android.unity", self.raw)
            output.writestr("ios.unity", self.raw)
        context = model_edits.mod_source_context(self.token)
        context["containers"][0]["raw"] = archive.read_bytes()
        context["sources"][0]["member"] = "android.unity"
        with patch.object(model_edits, "mod_source_context", return_value=context), self.assertRaisesRegex(ValueError, "Paired platform"):
            viewer_transplants.validate_request(self.request())

    def test_mismatched_platform_donor_does_not_publish_a_result(self):
        self.donor.write_bytes(bundle_fixture(platform=9))
        request = viewer_transplants.validate_request(self.request())
        job = Job(secrets.token_hex(6), "viewer_transplant")
        with self.assertRaisesRegex(ValueError, "matching Unity platforms"):
            viewer_transplants.run_transplant(job, request,
                output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(job.output_paths(), [])
        self.assertFalse(any((self.root / "modded/viewer").glob(".viewer-transplant-*")))
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
