"""Original Unity outline masks: real bytes, source identity and round trips."""
import copy
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import unittest

import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

from webtools.core import model_edits as edits, model_outlines as outlines, model_viewer, viewer_mesh_tools
from sifas_mesh_baker import stream_layout


FIXTURE = Path(__file__).parent / "fixtures/viewer_persistence.unity"


def colored_fixture(*, mixed=False, format_override=None, separate_color_stream=False):
    env = UnityPy.load(FIXTURE.read_bytes())
    mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
    tree = mesh.read_typetree()
    count, channels, strides, starts, _ = stream_layout(tree)
    channel = channels[3]
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    for index in range(count):
        offset = starts[channel["stream"]] + index * strides[channel["stream"]] + channel["offset"]
        data[offset:offset + 4] = bytes(([0, 51, 128, 191, 255, 37][index % 6], 70 + index, 130 + index, 220 + index))
    if separate_color_stream:
        # Six valid vertices with a distinct, tightly packed final color
        # stream. Unity does not require the last stream's trailing alignment.
        assert strides == {0: 56} and channel["offset"] == 52
        body = b"".join(data[index * 56:index * 56 + 52] for index in range(count))
        rgba = b"".join(data[index * 56 + 52:index * 56 + 56] for index in range(count))
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
