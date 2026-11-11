"""Original Unity outline masks: real bytes, source identity and round trips."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

from webtools.core import model_edits as edits, model_outlines as outlines, model_viewer, viewer_mesh_tools
from sifas_mesh_baker import stream_layout


FIXTURE = Path(__file__).parent / "fixtures/viewer_persistence.unity"


def colored_fixture(*, mixed=False, format_override=None, separate_color_stream=False, float_colors=False):
    env = UnityPy.load(FIXTURE.read_bytes())
    mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
    tree = mesh.read_typetree()
    count, channels, strides, starts, _ = stream_layout(tree)
    channel = channels[3]
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    for index in range(count):
        offset = starts[channel["stream"]] + index * strides[channel["stream"]] + channel["offset"]
        data[offset:offset + 4] = bytes(([0, 51, 128, 191, 255, 37][index % 6], 70 + index, 130 + index, 220 + index))
    if separate_color_stream or float_colors:
        # Six valid vertices with a distinct, tightly packed final color
        # stream. Unity does not require the last stream's trailing alignment.
        assert strides == {0: 56} and channel["offset"] == 52
        body = b"".join(data[index * 56:index * 56 + 52] for index in range(count))
        rgba = b"".join(data[index * 56 + 52:index * 56 + 56] for index in range(count))
        if float_colors:
            rgba = (np.frombuffer(rgba, dtype=np.uint8).astype("<f4") / 255).astype("<f4").tobytes()
            channel["format"] = 0
        data = body + bytes((-len(body)) % 16) + rgba
        channel["stream"], channel["offset"] = 1, 0
    tree["m_VertexData"]["m_DataSize"] = bytes(data)
    if format_override is not None:
        tree["m_VertexData"]["m_Channels"][3]["format"] = format_override
    mesh.save_typetree(tree)
    if mixed:
        shader = next(obj for obj in env.objects if obj.type.name == "Shader")
        duplicate = copy.copy(shader)
        duplicate.path_id = 901
        shader_tree = copy.deepcopy(shader.read_typetree())
        shader_tree["m_Name"] = "Standard"
        if "m_ParsedForm" in shader_tree:
            shader_tree["m_ParsedForm"]["m_Name"] = "Standard"
        duplicate.save_typetree(shader_tree)
        shader.assets_file.objects[901] = duplicate
        material = next(obj for obj in env.objects if obj.type.name == "Material")
        other = copy.copy(material)
        other.path_id = 902
        material_tree = copy.deepcopy(material.read_typetree())
        material_tree["m_Shader"] = {"m_FileID": 0, "m_PathID": 901}
        other.save_typetree(material_tree)
        material.assets_file.objects[902] = other
        renderer = next(obj for obj in env.objects if obj.type.name == "SkinnedMeshRenderer")
        value = renderer.read_typetree()
        value["m_Materials"].append({"m_FileID": 0, "m_PathID": 902})
        renderer.save_typetree(value)
    return env.file.save()


def colors(obj):
    handler = MeshHandler(obj.read())
    handler.process()
    return np.asarray(handler.m_Colors, dtype=np.uint8)


class OutlineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        with edits._LOCK:
            edits._SESSIONS.clear()

    def register(self, raw):
        path = self.root / (secrets.token_hex(4) + ".unity")
        path.write_bytes(raw)
        preview = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
        metadata = edits.register_session(preview["id"], [str(path)], preview["rig"])
        self.assertTrue(metadata["available"])
        return path, preview["id"], metadata

    @staticmethod
    def state(identity, factor):
        return {"version": 1, "edits": [], "outlines": [{"id": identity, "factor": factor}]}

    def assert_only_red_changed(self, original, saved, factors):
        before, after = edits._inspect(original), edits._inspect(saved)
        self.assertEqual(set(before["objects"]), set(after["objects"]))
        changed = set()
        for key, obj in before["objects"].items():
            other = after["objects"][key]
            if key not in factors:
                self.assertEqual(obj.get_raw_data(), other.get_raw_data(), (key, obj.type.name))
                continue
            changed.add(key)
            source_tree, target_tree = obj.read_typetree(), other.read_typetree()
            source_data, target_data = source_tree["m_VertexData"]["m_DataSize"], target_tree["m_VertexData"]["m_DataSize"]
            count, channels, strides, starts, _ = stream_layout(source_tree)
            channel = channels[3]
            expected = bytearray(source_data)
            for index in range(count):
                offset = starts[channel["stream"]] + index * strides[channel["stream"]] + channel["offset"]
                expected[offset] = min(255, int(source_data[offset] * factors[key] + .5))
            self.assertEqual(bytes(expected), bytes(target_data))
            source_tree["m_VertexData"]["m_DataSize"] = target_data
            self.assertEqual(source_tree, target_tree)
            a, b = colors(obj), colors(other)
            self.assertTrue(np.array_equal(a[:, 1:], b[:, 1:]))
            self.assertTrue(np.all(b[a[:, 0] == 0, 0] == 0))
        self.assertEqual(changed, set(factors))

    def test_catalogue_rounding_clamp_masks_and_exact_unrelated_bytes(self):
        for separate_color_stream in (False, True):
            raw = colored_fixture(separate_color_stream=separate_color_stream)
            catalog = outlines.catalogue(edits._inspect(raw), 0)
            self.assertTrue(catalog["available"])
            self.assertEqual(catalog["meshes"][0]["format"], "UNorm8")
            record = catalog["meshes"][0]
            self.assertEqual(record["id"], f"0:{record['file']}:{record['meshId']}")
            key = record["file"], int(record["meshId"])
            for factor in (0, .5, 1.5, 2):
                with self.subTest(factor=factor, separate_color_stream=separate_color_stream):
                    saved = outlines.apply_edits(raw, 0, [{"id": record["id"], "factor": factor}], catalog)
                    self.assert_only_red_changed(raw, saved, {key: factor})
            self.assertEqual(outlines.apply_edits(raw, 0, [{"id": record["id"], "factor": 1}], catalog), raw)

    def test_diagnostic_sources_match_captured_bytes_and_change_with_new_model(self):
        original = colored_fixture()
        path, token, metadata = self.register(original)
        self.assertEqual(metadata["outlines"]["sources"], [{
            "sourceIndex": 0, "name": path.name, "sha256": hashlib.sha256(original).hexdigest()}])
        self.assertNotIn(str(self.root), json.dumps(metadata["outlines"]))
        first = metadata["outlines"]["meshes"][0]
        self.assertEqual(first["vertexCount"], 6)
        self.assertEqual(first["originalWidth"], {"min": 0, "max": 255, "mean": sum([0, 51, 128, 191, 255, 37]) / 6})
        self.assertEqual(first["sourceIndex"], metadata["outlines"]["sources"][0]["sourceIndex"])

        env = UnityPy.load(original)
        mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
        tree = mesh.read_typetree(); tree["m_Name"] = "Second outline model"
        mesh.save_typetree(tree)
        other = env.file.save()
        other_path, _, other_metadata = self.register(other)
        self.assertNotEqual(hashlib.sha256(original).hexdigest(), hashlib.sha256(other).hexdigest())
        self.assertEqual(other_metadata["outlines"]["sources"], [{
            "sourceIndex": 0, "name": other_path.name, "sha256": hashlib.sha256(other).hexdigest()}])
        self.assertEqual(other_metadata["outlines"]["meshes"][0]["name"], "Second outline model")
        self.assertEqual(edits.mod_source_context(token)["outlines"], metadata["outlines"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(other_path.read_bytes(), other)

    def test_rejects_forged_duplicate_nonfinite_bool_and_unknown_settings(self):
        _, token, metadata = self.register(colored_fixture())
        identity = metadata["outlines"]["meshes"][0]["id"]
        for factor in (True, "0.5", -.01, 2.01, math.nan, math.inf, 10**1000):
            with self.subTest(factor=factor), self.assertRaises(ValueError):
                edits.validate_state(token, self.state(identity, factor))
        for rows in ([{"id": "0:0:999999", "factor": .5}],
                     [{"id": identity, "factor": .5}, {"id": identity, "factor": .8}],
                     [{"id": identity, "factor": .5, "sourceIndex": 0}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                edits.validate_state(token, {"version": 1, "edits": [], "outlines": rows})
        neutral = edits.validate_state(token, self.state(identity, 1), allow_empty=True)
        self.assertNotIn("outlines", neutral)
        self.assertFalse(edits.has_changes(neutral))
        self.assertEqual(len(metadata["sourceFingerprint"]), 64)

    def test_mixed_or_unsupported_color_shader_is_not_writable(self):
        self.assertFalse(outlines.catalogue(edits._inspect(colored_fixture(mixed=True)), 0)["available"])
        self.assertFalse(outlines.catalogue(edits._inspect(colored_fixture(format_override=6)), 0)["available"])

    def test_arbitrary_mesh_gameobject_material_names_preserve_outline_eligibility(self):
        raw = colored_fixture()
        original = outlines.catalogue(edits._inspect(raw), 0)["meshes"][0]
        env = UnityPy.load(raw)
        for obj in env.objects:
            if obj.type.name in ("Mesh", "GameObject", "Material"):
                tree = obj.read_typetree()
                tree["m_Name"] = "사용자 의상." + obj.type.name + ".001"
                obj.save_typetree(tree)
        renamed = env.file.save()
        path, _, metadata = self.register(renamed)
        catalog = metadata["outlines"]
        self.assertEqual(len(catalog["meshes"]), 1)
        self.assertEqual(catalog["excludedMeshes"], [])
        record = catalog["meshes"][0]
        self.assertEqual(record["id"], original["id"])
        self.assertEqual(record["name"], "사용자 의상.Mesh.001")
        self.assertEqual(record["originalWidth"], original["originalWidth"])
        self.assertEqual(path.read_bytes(), renamed)

    def test_preview_visible_unsupported_meshes_have_reasons_and_are_not_writable(self):
        shader_env = UnityPy.load(colored_fixture())
        shader = next(obj for obj in shader_env.objects if obj.type.name == "Shader")
        tree = shader.read_typetree()
        tree["m_Name"] = "OriginalASMember_Renamed"
        if "m_ParsedForm" in tree:
            tree["m_ParsedForm"]["m_Name"] = tree["m_Name"]
        shader.save_typetree(tree)
        for raw, expected in ((colored_fixture(format_override=6), {"unsupported_color_layout"}),
                              (shader_env.file.save(), {"unsupported_material"}),
                              (colored_fixture(mixed=True), {"unsupported_material", "mixed_material_references"})):
            with self.subTest(reasons=expected):
                path, token, metadata = self.register(raw)
                catalog = metadata["outlines"]
                self.assertFalse(catalog["available"])
                self.assertEqual(catalog["meshes"], [])
                self.assertEqual(len(catalog["excludedMeshes"]), 1)
                record = catalog["excludedMeshes"][0]
                self.assertEqual({row["code"] for row in record["reasons"]}, expected)
                self.assertEqual(record["id"], f"0:{record['file']}:{record['meshId']}")
                self.assertEqual(catalog["sources"][0]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertNotIn(str(self.root), json.dumps(catalog))
                self.assertNotIn("OriginalASMember_Renamed", json.dumps(record))
                self.assertTrue(all(row["message"] for row in record["reasons"]))
                with self.assertRaises(ValueError):
                    edits.validate_state(token, self.state(record["id"], .5))
                self.assertEqual(path.read_bytes(), raw)

    def test_standalone_preview_mesh_and_invalid_renderer_binding_are_distinguished(self):
        env = UnityPy.load(colored_fixture())
        for obj in list(env.objects):
            if obj.type.name in ("SkinnedMeshRenderer", "MeshRenderer"):
                del obj.assets_file.objects[obj.path_id]
        raw = env.file.save()
        path = self.root / "standalone.unity"
        path.write_bytes(raw)
        preview = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
        self.assertEqual(preview["stats"]["meshes"], 1)
        catalog = outlines.catalogue(edits._inspect(raw), 0)
        self.assertEqual(catalog["meshes"], [])
        self.assertEqual([row["code"] for row in catalog["excludedMeshes"][0]["reasons"]], ["no_verified_renderer_binding"])

        env = UnityPy.load(colored_fixture())
        renderer = next(obj for obj in env.objects if obj.type.name == "SkinnedMeshRenderer")
        tree = renderer.read_typetree()
        tree["m_GameObject"] = {"m_FileID": 0, "m_PathID": 987654321}
        renderer.save_typetree(tree)
        catalog = outlines.catalogue(edits._inspect(env.file.save()), 0)
        self.assertEqual([row["code"] for row in catalog["excludedMeshes"][0]["reasons"]], ["invalid_renderer_binding"])

    def test_inventory_distinguishes_layout_name_and_limit_failures_without_omission(self):
        def mesh_variant(change):
            env = UnityPy.load(colored_fixture())
            mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
            tree = mesh.read_typetree()
            change(tree)
            mesh.save_typetree(tree)
            return env.file.save()
        variants = [
            (lambda t: t["m_VertexData"]["m_Channels"][3].update(dimension=0), "missing_color_channel"),
            (lambda t: t["m_VertexData"].update(m_DataSize=t["m_VertexData"]["m_DataSize"][:-1]), "malformed_vertex_data"),
            (lambda t: t.update(m_Name="x" * 1025), "invalid_mesh_name"),
            (lambda t: t["m_VertexData"].update(m_VertexCount=outlines.MAX_VERTICES + 1), "vertex_limit"),
        ]
        for change, expected in variants:
            with self.subTest(reason=expected):
                catalog = outlines.catalogue(edits._inspect(mesh_variant(change)), 7)
                self.assertEqual(catalog["meshes"], [])
                self.assertEqual(len(catalog["excludedMeshes"]), 1)
                record = catalog["excludedMeshes"][0]
                self.assertEqual(record["sourceIndex"], 7)
                self.assertEqual([row["code"] for row in record["reasons"]], [expected])
                self.assertLessEqual(len(record["name"].encode()), 1024)
        info = edits._inspect(colored_fixture())
        with mock.patch.object(outlines, "MAX_MESHES", 1):
            catalog = outlines.catalogue_sources([(info, 0), (info, 1)])
        self.assertEqual(catalog["meshes"], [])
        self.assertEqual({row["sourceIndex"] for row in catalog["excludedMeshes"]}, {0, 1})
        self.assertTrue(all([reason["code"] for reason in row["reasons"]] == ["mesh_limit"] for row in catalog["excludedMeshes"]))
        with mock.patch.object(outlines, "MAX_INVENTORY_MESHES", 1), self.assertRaisesRegex(ValueError, "outline inventory limit"):
            outlines.catalogue_sources([(info, 0), (info, 1)])
        self.assertEqual(outlines.catalogue_sources([]), {"version": 1, "available": False, "meshes": [], "excludedMeshes": []})

    def test_float32_outlines_preserve_precision_format_and_every_non_red_byte(self):
        env = UnityPy.load(colored_fixture(float_colors=True))
        mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
        tree = mesh.read_typetree()
        count, start, stride = outlines._layout(tree)
        source_data = bytearray(tree["m_VertexData"]["m_DataSize"])
        for vertex, red in enumerate((0, .123456789, .6, 1, .995, .231234567)):
            struct.pack_into("<4f", source_data, start + vertex * stride, red, .23456789, .45678912, .87654321)
        tree["m_VertexData"]["m_DataSize"] = bytes(source_data)
        mesh.save_typetree(tree)
        raw = env.file.save()
        path, token, metadata = self.register(raw)
        catalog = metadata["outlines"]
        record = catalog["meshes"][0]
        self.assertEqual(record["format"], "Float32")
        self.assertEqual(catalog["excludedMeshes"], [])
        red_values = [struct.unpack_from("<f", source_data, start + vertex * stride)[0] for vertex in range(count)]
        self.assertEqual(record["originalWidth"], {"min": min(red_values) * 255, "max": max(red_values) * 255,
                                                  "mean": sum(red * 255 for red in red_values) / count})
        self.assertNotEqual(red_values[1] * 255, round(red_values[1] * 255))
        before = edits._inspect(raw)
        key = record["file"], int(record["meshId"])
        for settings in ({"factor": 0}, {"factor": .5}, {"factor": 2}, {"factor": 1, "absolute": 128},
                         {"factor": 1.5, "absolute": 64, "vertices": [{"vertex": 0, "value": .333333333}, {"vertex": 2, "value": 0}]}):
            with self.subTest(settings=settings):
                row = {"id": record["id"], **settings}
                saved = outlines.apply_edits(raw, 0, [row], catalog)
                after = edits._inspect(saved)
                expected = bytearray(source_data)
                overrides = {entry["vertex"]: entry["value"] for entry in row.get("vertices", [])}
                for vertex in range(count):
                    value = overrides.get(vertex, settings.get("absolute", red_values[vertex] * 255) / 255)
                    struct.pack_into("<f", expected, start + vertex * stride, min(1, max(0, value * settings["factor"])))
                target_tree = after["objects"][key].read_typetree()
                self.assertEqual(target_tree["m_VertexData"]["m_DataSize"], bytes(expected))
                source_tree = before["objects"][key].read_typetree()
                source_tree["m_VertexData"]["m_DataSize"] = bytes(expected)
                self.assertEqual(source_tree, target_tree)
                self.assertEqual(set(before["objects"]), set(after["objects"]))
                for other in set(before["objects"]) - {key}:
                    self.assertEqual(before["objects"][other].get_raw_data(), after["objects"][other].get_raw_data())
                self.assertEqual(outlines.catalogue(after, 0)["meshes"][0]["vertexOrderSignature"], record["vertexOrderSignature"])
                self.assertEqual(outlines.apply_edits(saved, 0, [row], catalog, original_raw=raw), saved)
        state = edits.validate_state(token, {"version": 1, "edits": [], "outlines": [{"id": record["id"], "factor": .5}]})
        output = edits.export(token, state, self.root / "float-export")
        restored = edits.restore(token, json.loads(Path(output["recipe_path"]).read_text()))
        again = edits.export(token, restored, self.root / "float-again")
        self.assertEqual(Path(again["preview_paths"][0]).read_bytes(), Path(output["preview_paths"][0]).read_bytes())
        reset = edits.export(token, {"version": 1, "edits": []}, self.root / "float-reset", allow_empty=True)
        self.assertEqual(Path(reset["preview_paths"][0]).read_bytes(), raw)
        self.assertEqual(path.read_bytes(), raw)

    def test_float32_nonfinite_and_out_of_range_masks_remain_excluded(self):
        for component, value in ((0, math.nan), (0, math.inf), (0, -.001), (0, 1.001), (1, math.nan), (2, 1.001)):
            with self.subTest(component=component, value=value):
                env = UnityPy.load(colored_fixture(float_colors=True))
                mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
                tree = mesh.read_typetree()
                _, start, _ = outlines._layout(tree)
                data = bytearray(tree["m_VertexData"]["m_DataSize"])
                struct.pack_into("<f", data, start + component * 4, value)
                tree["m_VertexData"]["m_DataSize"] = bytes(data)
                mesh.save_typetree(tree)
                raw = env.file.save()
                catalog = outlines.catalogue(edits._inspect(raw), 0)
                self.assertEqual(catalog["meshes"], [])
                self.assertEqual([row["code"] for row in catalog["excludedMeshes"][0]["reasons"]], ["invalid_float_color_values"])
                with self.assertRaises(ValueError):
                    outlines.apply_edits(raw, 0, [{"id": catalog["excludedMeshes"][0]["id"], "factor": .5}], catalog)

    def test_outline_only_export_recipe_restore_and_repeat_do_not_accumulate(self):
        raw = colored_fixture()
        path, token, metadata = self.register(raw)
        record = metadata["outlines"]["meshes"][0]
        state = edits.validate_state(token, self.state(record["id"], .5))
        self.assertTrue(edits.has_changes(state))
        first = edits.export(token, state, self.root / "first")
        saved = Path(first["preview_paths"][0]).read_bytes()
        self.assert_only_red_changed(raw, saved, {(record["file"], int(record["meshId"])): .5})
        recipe = json.loads(Path(first["recipe_path"]).read_text())
        self.assertEqual(recipe["state"]["outlines"], state["outlines"])
        restored = edits.restore(token, recipe)
        again = edits.export(token, restored, self.root / "again")
        self.assertEqual(Path(again["preview_paths"][0]).read_bytes(), saved)
        self.assertEqual(path.read_bytes(), raw)
        reset = edits.export(token, {"version": 1, "edits": []}, self.root / "reset", allow_empty=True)
        self.assertEqual(Path(reset["preview_paths"][0]).read_bytes(), raw)

    def test_vertex_and_body_edit_combination_preserves_outline_mask_basis(self):
        raw = colored_fixture()
        path, token, metadata = self.register(raw)
        record = metadata["outlines"]["meshes"][0]
        mesh = {"source": 0, "file": record["file"], "id": record["meshId"]}
        initial = viewer_mesh_tools.data(token, mesh)
        source_position = initial["positions"][0]
        position = [source_position[0] + .03125, source_position[1], source_position[2]]
        body = self.state(record["id"], .5)
        node = next(row for row in metadata["nodes"] if row["name"] == "BreastSize")
        body["edits"] = [{"node": node["node"], "method": "node", "scale": [1.1, 1.1, 1.1]}]
        mesh_state = {"version": 1, "meshes": [{"mesh": mesh, "positions": [{"vertex": 0, "position": position}]}]}
        output = viewer_mesh_tools.export(token, mesh_state, self.root / "combined", body_state=body)
        saved = Path(output["preview_paths"][0]).read_bytes()
        original_info, saved_info = edits._inspect(raw), edits._inspect(saved)
        key = record["file"], int(record["meshId"])
        before, after = colors(original_info["objects"][key]), colors(saved_info["objects"][key])
        self.assertTrue(np.array_equal(after[:, 0], np.floor(before[:, 0].astype(float) * .5 + .5).astype(np.uint8)))
        self.assertTrue(np.array_equal(before[:, 1:], after[:, 1:]))
        self.assertEqual(path.read_bytes(), raw)

    def test_sparse_vertex_width_grows_zero_masks_and_preserves_all_other_bytes(self):
        raw = colored_fixture(separate_color_stream=True)
        catalog = outlines.catalogue(edits._inspect(raw), 0)
        record = catalog["meshes"][0]
        row = {"id": record["id"], "factor": .5,
               "vertices": [{"vertex": 2, "value": 0}, {"vertex": 0, "value": 1}]}
        normalized = outlines.validate(catalog, [row])
        self.assertEqual([value["vertex"] for value in normalized[0]["vertices"]], [0, 2])
        saved = outlines.apply_edits(raw, 0, normalized, catalog)
        a, b = edits._inspect(raw), edits._inspect(saved)
        key = record["file"], int(record["meshId"])
        before = a["objects"][key].read_typetree()
        after = b["objects"][key].read_typetree()
        expected = bytearray(before["m_VertexData"]["m_DataSize"])
        count, start, stride = outlines._layout(before)
        for vertex in range(count):
            red = 255 if vertex == 0 else 0 if vertex == 2 else expected[start + vertex * stride]
            expected[start + vertex * stride] = int(red * .5 + .5)
        self.assertEqual(after["m_VertexData"]["m_DataSize"], bytes(expected))
        self.assertEqual(colors(b["objects"][key])[0, 0], 128)
        self.assertEqual(colors(b["objects"][key])[2, 0], 0)
        before["m_VertexData"]["m_DataSize"] = after["m_VertexData"]["m_DataSize"]
        self.assertEqual(before, after)
        for other in set(a["objects"]) - {key}:
            self.assertEqual(a["objects"][other].get_raw_data(), b["objects"][other].get_raw_data())
        self.assertEqual(record["vertexOrderSignature"], outlines.catalogue(b, 0)["meshes"][0]["vertexOrderSignature"])

    def test_detail_state_is_bounded_and_survives_recipe_restore(self):
        raw = colored_fixture()
        original, token, metadata = self.register(raw)
        record = metadata["outlines"]["meshes"][0]
        base = {"id": record["id"], "factor": 1, "vertices": [{"vertex": 0, "value": .375}]}
        state = edits.validate_state(token, {"version": 1, "edits": [], "outlines": [base]})
        output = edits.export(token, state, self.root / "detail")
        restored = edits.restore(token, json.loads(Path(output["recipe_path"]).read_text()))
        self.assertEqual(restored["outlines"], state["outlines"])
        again = edits.export(token, restored, self.root / "again")
        self.assertEqual(Path(again["preview_paths"][0]).read_bytes(), Path(output["preview_paths"][0]).read_bytes())
        self.assertEqual(original.read_bytes(), raw)
        invalid = ([{"vertex": True, "value": .5}], [{"vertex": -1, "value": .5}],
                   [{"vertex": record["vertexCount"], "value": .5}], [{"vertex": .5, "value": .5}],
                   [{"vertex": 0, "value": True}], [{"vertex": 0, "value": math.nan}],
                   [{"vertex": 0, "value": 1.01}], [{"vertex": 0, "value": .5, "other": 1}],
                   [{"vertex": 0, "value": .5}, {"vertex": 0, "value": .7}], "0")
        for vertices in invalid:
            with self.subTest(vertices=vertices), self.assertRaises(ValueError):
                outlines.validate(metadata["outlines"], [{**base, "vertices": vertices}])

    def test_absolute_raw_width_sets_every_vertex_and_preserves_source_and_other_channels(self):
        raw = colored_fixture(separate_color_stream=True)
        original, token, metadata = self.register(raw)
        record = metadata["outlines"]["meshes"][0]
        key = record["file"], int(record["meshId"])
        self.assertEqual(record["originalWidth"], {"min": 0, "max": 255, "mean": sum((0, 51, 128, 191, 255, 37)) / 6})
        for absolute in (0, 1, 128, 255):
            with self.subTest(absolute=absolute):
                row = {"id": record["id"], "factor": 1, "absolute": absolute}
                state = edits.validate_state(token, {"version": 1, "edits": [], "outlines": [row]})
                self.assertEqual(state["outlines"], [row])
                output = edits.export(token, state, self.root / ("absolute-" + str(absolute)))
                saved = Path(output["preview_paths"][0]).read_bytes()
                before, after = edits._inspect(raw), edits._inspect(saved)
                source_tree, target_tree = before["objects"][key].read_typetree(), after["objects"][key].read_typetree()
                expected = bytearray(source_tree["m_VertexData"]["m_DataSize"])
                count, start, stride = outlines._layout(source_tree)
                for vertex in range(count):
                    expected[start + vertex * stride] = absolute
                self.assertEqual(bytes(expected), target_tree["m_VertexData"]["m_DataSize"])
                source_tree["m_VertexData"]["m_DataSize"] = target_tree["m_VertexData"]["m_DataSize"]
                self.assertEqual(source_tree, target_tree)
                for other in set(before["objects"]) - {key}:
                    self.assertEqual(before["objects"][other].get_raw_data(), after["objects"][other].get_raw_data())
                recipe = json.loads(Path(output["recipe_path"]).read_text())
                self.assertEqual(edits.restore(token, recipe)["outlines"], [row])
        self.assertEqual(original.read_bytes(), raw)
        for invalid in (-1, 256, 1.5, True, None, "128"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                outlines.validate(metadata["outlines"], [{"id": record["id"], "factor": 1, "absolute": invalid}])

    def test_sparse_vertex_override_after_absolute_width_keeps_native_rounding(self):
        raw = colored_fixture()
        catalog = outlines.catalogue(edits._inspect(raw), 0)
        record = catalog["meshes"][0]
        row = {"id": record["id"], "factor": .5, "absolute": 200,
               "vertices": [{"vertex": 0, "value": 1}, {"vertex": 1, "value": 0}]}
        saved = outlines.apply_edits(raw, 0, [row], catalog)
        data = colors(edits._inspect(saved)["objects"][record["file"], int(record["meshId"])])
        self.assertEqual(data[:, 0].tolist(), [128, 0, 100, 100, 100, 100])

    def test_runtime_member_face_requires_exact_original_body_binding(self):
        body = edits._inspect(colored_fixture())
        face_env = UnityPy.load(colored_fixture())
        shader = next(obj for obj in face_env.objects if obj.type.name == "Shader")
        tree = shader.read_typetree()
        tree["m_Name"] = "Standard"
        if "m_ParsedForm" in tree:
            tree["m_ParsedForm"]["m_Name"] = "Standard"
        shader.save_typetree(tree)
        face = edits._inspect(face_env.file.save())
        asset = next(iter(body["objects"].values())).assets_file
        face_asset = next(iter(face["objects"].values())).assets_file
        # Neutral meshes are real Unity fixtures; only the two component
        # references are declared test boundaries, with no game assets bundled.
        def add(info, file, identity, kind, tree):
            obj = SimpleNamespace(path_id=identity, assets_file=file, type=SimpleNamespace(name=kind), read_typetree=lambda: tree)
            file.objects[identity] = obj
            info["objects"][(0, identity)] = obj
        for info, file, identity, name in ((body, asset, 901, "BodyPartManager"), (face, face_asset, 902, "MemberFace")):
            add(info, file, identity, "MonoScript", {"m_ClassName": name, "m_Namespace": "LLAS.Components.Members", "m_AssemblyName": "Assembly-CSharp.dll"})
        add(face, face_asset, 904, "MonoBehaviour", {"m_Script": {"m_FileID": 0, "m_PathID": 902}, "m_GameObject": {"m_FileID": 0, "m_PathID": 2}})
        self.assertFalse(outlines.catalogue(face, 1)["available"])
        asset.externals.append(SimpleNamespace(path=face_asset.name))
        pointer = {"m_FileID": len(asset.externals), "m_PathID": 904}
        add(body, asset, 903, "MonoBehaviour", {"m_Script": {"m_FileID": 0, "m_PathID": 901}, "face": pointer,
                                             "headMaterial": {"m_FileID": 0, "m_PathID": 13}})
        catalog = outlines.catalogue_sources([(body, 0), (face, 1)])
        self.assertTrue(any(row["sourceIndex"] == 1 and row["runtimeBindings"] for row in catalog["meshes"]))
        pointer["m_PathID"] = 999999
        self.assertFalse(any(row["sourceIndex"] == 1 for row in outlines.catalogue_sources([(body, 0), (face, 1)])["meshes"]))

    @unittest.skipUnless(os.environ.get("SIFAS_OUTLINE_BODY") and os.environ.get("SIFAS_OUTLINE_FACE"), "Set original body and face for companion jaw export")
    def test_original_automatic_face_jaw_detail_saves_only_selected_red(self):
        body, face = self.root / "ch0201_co0002.unity", self.root / "ch0201_face.unity"
        body_raw, face_raw = Path(os.environ["SIFAS_OUTLINE_BODY"]).read_bytes(), Path(os.environ["SIFAS_OUTLINE_FACE"]).read_bytes()
        body.write_bytes(body_raw)
        face.write_bytes(face_raw)
        result = model_viewer.prepare([str(body)], rigged=True, face_context={"enabled": True, "allow_download": False})
        metadata = edits.register_session(result["id"], [str(body)], result["rig"], companions=model_viewer.get_editing_companions(result["id"]))
        jaw = next(row for row in metadata["outlines"]["meshes"] if row["sourceIndex"] == 1 and row["name"] == "Mouth")
        info = edits._inspect(face_raw)
        obj = info["objects"][(jaw["file"], int(jaw["meshId"]))]
        handler = MeshHandler(obj.read()); handler.process()
        vertex = int(np.argmin(np.asarray(handler.m_Vertices)[:, 1]))
        state = {"version": 1, "edits": [], "outlines": [{"id": jaw["id"], "factor": 1, "vertices": [{"vertex": vertex, "value": .25}]}]}
        exported = edits.export(result["id"], state, self.root / "jaw-copy")
        saved = [Path(path).read_bytes() for path in exported["preview_paths"]]
        self.assertIn(body_raw, saved)
        after_raw = next(raw for raw in saved if raw != body_raw)
        before_tree, after_tree = obj.read_typetree(), edits._inspect(after_raw)["objects"][(jaw["file"], int(jaw["meshId"]))].read_typetree()
        expected = bytearray(before_tree["m_VertexData"]["m_DataSize"])
        _, start, stride = outlines._layout(before_tree)
        expected[start + vertex * stride] = 64
        self.assertEqual(bytes(expected), bytes(after_tree["m_VertexData"]["m_DataSize"]))
        before_tree["m_VertexData"]["m_DataSize"] = after_tree["m_VertexData"]["m_DataSize"]
        self.assertEqual(before_tree, after_tree)
        before, after = edits._inspect(face_raw), edits._inspect(after_raw)
        for key in set(before["objects"]) - {(jaw["file"], int(jaw["meshId"]))}:
            self.assertEqual(before["objects"][key].get_raw_data(), after["objects"][key].get_raw_data())
        self.assertEqual(body.read_bytes(), body_raw)
        self.assertEqual(face.read_bytes(), face_raw)

    @unittest.skipUnless(os.environ.get("SIFAS_OUTLINE_ORIGINALS"), "Set SIFAS_OUTLINE_ORIGINALS for original game preservation checks")
    def test_actual_original_costumes_change_only_red_and_keep_textures_exact(self):
        for name in os.environ["SIFAS_OUTLINE_ORIGINALS"].split(os.pathsep):
            with self.subTest(source=Path(name).name):
                raw = Path(name).read_bytes()
                catalog = outlines.catalogue(edits._inspect(raw), 0)
                self.assertTrue(catalog["available"])
                rows = [{"id": row["id"], "factor": .5} for row in catalog["meshes"]]
                saved = outlines.apply_edits(raw, 0, rows, catalog)
                self.assert_only_red_changed(raw, saved, {(row["file"], int(row["meshId"])): .5 for row in catalog["meshes"]})
                self.assertEqual(Path(name).read_bytes(), raw)
