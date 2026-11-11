"""Static texture editing must not authorize outline or rig mutations."""
import base64
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import io
import os
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import UnityPy
from PIL import Image

from sifas_mesh_baker import stream_layout
from webtools.core import model_edits, model_viewer, viewer_texture_tools, viewer_mesh_tools, viewer_mod_flow, viewer_transplants
from webtools.server import Handler


FIXTURES = Path(__file__).parent / "fixtures"


def static_outline_fixture():
    """Real typed MeshRenderer/Filter, stock shader and RGBA8; no skin/head."""
    env = UnityPy.load((FIXTURES / "viewer_textured_triangle.unity").read_bytes())
    colored = UnityPy.load((FIXTURES / "viewer_persistence.unity").read_bytes())
    source_mesh = next(obj for obj in colored.objects if obj.type.name == "Mesh")
    mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
    tree = source_mesh.read_typetree()
    tree["m_Name"] = "Old custom shell"
    count, channels, strides, starts, _ = stream_layout(tree)
    color = channels[3]
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    for vertex in range(count):
        start = starts[color["stream"]] + color["offset"] + vertex * strides[color["stream"]]
        data[start:start + 4] = bytes(([0, 51, 128, 191, 255, 37][vertex], 90, 150, 255))
    tree["m_VertexData"]["m_DataSize"] = bytes(data)
    mesh.save_typetree(tree)
    game = next(obj for obj in env.objects if obj.type.name == "GameObject")
    tree = game.read_typetree(); tree["m_Name"] = "Old imported object"
    game.save_typetree(tree)

    source_shader = next(obj for obj in colored.objects if obj.type.name == "Shader")
    shader = copy.copy(source_shader)
    shader.assets_file = mesh.assets_file
    shader.path_id = 8
    shader.type_id = len(mesh.assets_file.types)
    shader.serialized_type = copy.copy(source_shader.serialized_type)
    mesh.assets_file.types.append(shader.serialized_type)
    shader.set_raw_data(source_shader.get_raw_data())
    mesh.assets_file.objects[shader.path_id] = shader
    material = next(obj for obj in env.objects if obj.type.name == "Material")
    source_material = next(obj for obj in colored.objects if obj.type.name == "Material")
    tree = source_material.read_typetree()
    tree["m_Name"] = "Old custom cloth"
    tree["m_Shader"] = {"m_FileID": 0, "m_PathID": shader.path_id}
    for _, texture in tree["m_SavedProperties"]["m_TexEnvs"]:
        if texture["m_Texture"]["m_PathID"]:
            texture["m_Texture"] = {"m_FileID": 0, "m_PathID": 7}
    material.save_typetree(tree)
    return env.file.save()


class OutlineInventorySessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = static_outline_fixture()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(3)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.library = self.root / "library"
        self.source = self.library / "extracted/3d_model/old-custom.unity"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(self.raw)
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        environment.start(); self.addCleanup(environment.stop)
        with model_edits._LOCK:
            model_edits._SESSIONS.clear()

    def request(self, route, body):
        request = urllib.request.Request(self.url + route, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def assert_inventory(self, metadata, reason="This model has no editable rig."):
        self.assertTrue(metadata["available"])
        self.assertFalse(metadata["bodyEditingAvailable"])
        self.assertEqual(metadata["bodyEditingReason"], reason)
        self.assertEqual(metadata["supported"], ["texture_pixels"])
        self.assertEqual(metadata["nodes"], [])
        self.assertTrue(any(row["available"] for row in metadata["textures"]["textures"]))
        session = model_edits._session(metadata["token"])
        self.assertFalse(session["bodyEditingAvailable"])
        self.assertEqual(session["targets"], {})
        catalog = metadata["outlines"]
        self.assertTrue(catalog["available"])
        self.assertEqual(len(catalog["meshes"]), 1)
        record = catalog["meshes"][0]
        self.assertEqual(record["name"], "Old custom shell")
        self.assertEqual(record["vertexCount"], 6)
        self.assertEqual(record["originalWidth"], {
            "min": 0, "max": 255, "mean": sum([0, 51, 128, 191, 255, 37]) / 6})
        self.assertEqual(catalog["sources"], [{"sourceIndex": 0, "name": self.source.name,
                                             "sha256": hashlib.sha256(self.raw).hexdigest()}])
        self.assertNotIn(str(self.root), json.dumps(metadata))
        return record

    def assert_nontexture_writes_denied(self, token, record):
        forged = [
            {"edits": [{"node": 1, "method": "mesh", "scale": [1.2, 1, 1]}]},
            {"outlines": [{"id": record["id"], "factor": .5}]},
            {"physics": [{"id": "0:0:999", "properties": {}}]},
            {"compensationReference": [{"node": 1, "scale": [1, 1, 1], "position": [0, 0, 0], "rotation": [0, 0, 0, 1]}]},
            {"accessoryUnclip": {"strength": 1, "overlap": 0, "closeGaps": False}},
            {"accessoryUnclip": False},
            {"accessoryUnclip": {}},
        ]
        for changes in forged:
            state = {"version": 1, "edits": [], **changes}
            with self.subTest(channel=next(iter(changes))), self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
                model_edits.export(token, state, self.root / "forged-output", allow_empty=True)
        self.assertFalse((self.root / "forged-output").exists())

    def test_actual_static_renderer_inventory_retains_texture_only_session(self):
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        self.assertEqual(preview["stats"]["meshes"], 1)
        self.assertFalse(preview["rig"]["available"])
        self.assertTrue(model_viewer.get_model(preview["id"]).startswith(b"glTF"))
        metadata = model_edits.register_session(preview["id"], [str(self.source)], preview["rig"])
        record = self.assert_inventory(metadata)
        self.assertIn(preview["id"], model_edits._SESSIONS)
        self.assert_nontexture_writes_denied(preview["id"], record)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_unavailable_rig_cannot_authorize_supplied_bone_metadata(self):
        token = secrets.token_hex(16)
        rig = {"available": False, "bones": [{"node": 1, "sourceIndex": 0,
            "transformId": "3", "sourceHash": hashlib.sha256(self.raw).hexdigest()}]}
        record = self.assert_inventory(model_edits.register_session(token, [str(self.source)], rig))
        self.assertIn(token, model_edits._SESSIONS)
        self.assert_nontexture_writes_denied(token, record)

    def test_unavailable_preview_still_rejects_changed_source_bytes(self):
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        self.assertFalse(preview["rig"]["available"])
        self.assertTrue(preview["rig"]["bones"], "The static preview still binds its source transform identity")
        env = UnityPy.load(self.raw)
        mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
        tree = mesh.read_typetree(); tree["m_Name"] = "Changed after static preview"
        mesh.save_typetree(tree)
        changed = env.file.save()
        self.assertNotEqual(hashlib.sha256(changed).hexdigest(), hashlib.sha256(self.raw).hexdigest())
        self.source.write_bytes(changed)
        with self.assertRaisesRegex(model_edits.ModelEditError, "changed while its preview"):
            model_edits.register_session(preview["id"], [str(self.source)], preview["rig"])
        self.assertNotIn(preview["id"], model_edits._SESSIONS)

    def test_available_flag_without_writable_nodes_only_authorizes_texture_pixels(self):
        token = secrets.token_hex(16)
        record = self.assert_inventory(model_edits.register_session(token, [str(self.source)],
            {"available": True, "bones": []}), reason="No original writable body nodes were found.")
        self.assertIn(token, model_edits._SESSIONS)
        self.assert_nontexture_writes_denied(token, record)

    def test_http_static_rig_inventory_cannot_authorize_outline_exports(self):
        with patch.object(model_edits, "register_session", wraps=model_edits.register_session) as register:
            status, response = self.request("/api/viewer/prepare", {
                "paths": [str(self.source)], "rigged": True, "auto_face": False})
        self.assertEqual(status, 200, response)
        register.assert_called_once()
        self.assertFalse(response["rig"]["available"])
        record = self.assert_inventory(response["editing"])
        status, denied = self.request("/api/viewer/edit/export", {"token": response["id"],
            "state": {"version": 1, "edits": [], "outlines": [{"id": record["id"], "factor": .5}]}})
        self.assertEqual(status, 400, denied)
        self.assertIn("texture pixel edits only", denied["error"])
        self.assertIn(response["id"], model_edits._SESSIONS)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_static_mesh_reads_remain_available_but_geometry_pipelines_are_denied(self):
        token = secrets.token_hex(16)
        metadata = model_edits.register_session(token, [str(self.source)], {"available": False, "bones": []})
        self.assert_inventory(metadata)
        identity = viewer_mesh_tools.inspect(token)["meshes"][0]["mesh"]
        self.assertTrue(viewer_mesh_tools.data(token, identity)["positions"])
        mesh_state = {"version": 1, "meshes": [{"mesh": identity, "deleteFaces": [0]}]}
        body = {"version": 1, "edits": []}
        with self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
            viewer_mesh_tools.export(token, mesh_state, self.root / "forged-mesh", body_state=body)
        with self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
            viewer_mod_flow.export_current(token, body, self.root / "forged-flow", mesh_state=mesh_state,
                allow_empty=True, repo_root=self.root, cache_root=self.root / "forged-cache")
        normalized = model_edits.validate_state(token, body, allow_empty=True)
        body_recipe = model_edits._recipe(model_edits._session(token), normalized)
        recipe = {"version": 1, "tool": "mesh-tools", "sources": [hashlib.sha256(self.raw).hexdigest()],
                  "state": mesh_state, "bodyState": normalized, "bodyRecipe": body_recipe}
        with patch.object(viewer_mesh_tools, "_write_mesh", side_effect=AssertionError("Native mesh writer must not run")), \
                self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
            viewer_mod_flow.restore_current(token, recipe)
        status, denied = self.request("/api/viewer/mesh/export", {"token": token, "state": mesh_state, "bodyState": body})
        self.assertEqual(status, 400, denied)
        self.assertIn("texture pixel edits only", denied["error"])
        request = {"token": token, "state": body, "donor": str(self.source), "variant": "primary",
                   "operation": "costume", "partRoot": "", "cutLow": .3, "cutHigh": .92, "region": "lower_belly"}
        with patch.object(viewer_transplants, "_read_donor", side_effect=AssertionError("Donor must not be read")), \
                self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
            viewer_transplants.validate_request(request)
        with self.assertRaisesRegex(model_edits.ModelEditError, "texture pixel edits only"):
            viewer_transplants.run_transplant(None, {"token": token}, output_root=self.root / "forged-graft",
                cache_root=self.root / "forged-graft-cache")
        for name in ("forged-mesh", "forged-flow", "forged-cache", "forged-graft", "forged-graft-cache"):
            self.assertFalse((self.root / name).exists(), name)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_static_texture_pixels_export_restore_and_leave_outline_geometry_exact(self):
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        metadata = model_edits.register_session(preview["id"], [str(self.source)], preview["rig"])
        self.assert_inventory(metadata)
        row = next(row for row in metadata["textures"]["textures"] if row["available"])
        original = viewer_texture_tools.data(preview["id"], row["texture"])
        with Image.open(io.BytesIO(base64.b64decode(original["image"].split(",", 1)[1]))) as source:
            image = source.convert("RGBA")
        before_pixels = image.copy()
        image.putpixel((0, 0), (209, 17, 83, image.getpixel((0, 0))[3]))
        buffer = io.BytesIO(); image.save(buffer, "PNG")
        operation = {"texture": row["texture"], "sourceSha256": hashlib.sha256(self.raw).hexdigest(),
                     "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(), "kind": "paint"}
        state = {"version": 1, "edits": [], "outlines": [], "physics": [], "compensationReference": [], "textures": [operation]}
        for extra in ({"outlines": [{"id": metadata["outlines"]["meshes"][0]["id"], "factor": .5}]},
                      {"accessoryUnclip": False}, {"savedSettingsEnabled": False}, {"unsupported": ["preview"]}):
            with self.subTest(extra=extra), self.assertRaises(model_edits.ModelEditError):
                model_edits.export(preview["id"], {**state, **extra}, self.root / "forged-texture-mix")
        self.assertFalse((self.root / "forged-texture-mix").exists())
        saved = model_edits.export(preview["id"], state, self.root / "texture-output")
        original_objects = {(index, obj.path_id): obj for index, asset in enumerate(UnityPy.load(self.raw).assets)
                            for obj in asset.objects.values()}
        def assert_texture_only(raw):
            objects = {(index, obj.path_id): obj for index, asset in enumerate(UnityPy.load(raw).assets)
                       for obj in asset.objects.values()}
            self.assertEqual(set(objects), set(original_objects))
            identity = row["texture"]["file"], int(row["texture"]["id"])
            for key, obj in objects.items():
                if key != identity:
                    self.assertEqual(obj.get_raw_data(), original_objects[key].get_raw_data(), obj.type.name)
            actual = objects[identity].read().image.convert("RGBA")
            self.assertEqual(actual.tobytes(), image.tobytes())
            self.assertEqual(actual.getchannel("A").tobytes(), before_pixels.getchannel("A").tobytes())
        assert_texture_only(Path(saved["preview_paths"][0]).read_bytes())
        reopened = secrets.token_hex(16)
        model_edits.register_session(reopened, [str(self.source)], preview["rig"])
        restored = model_edits.restore(reopened, saved["recipe"])
        self.assertEqual(restored["textures"], [operation])
        repeated = model_edits.export(reopened, restored, self.root / "repeated-texture-output")
        assert_texture_only(Path(repeated["preview_paths"][0]).read_bytes())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_preview_only_and_nonrigged_prepare_do_not_register_inventory(self):
        for extra in ({"rigged": True, "preview_only": True}, {"rigged": False}, {}):
            with self.subTest(extra=extra), \
                    patch.object(model_edits, "register_session", wraps=model_edits.register_session) as register:
                status, response = self.request("/api/viewer/prepare", {
                    "paths": [str(self.source)], "auto_face": False, **extra})
                self.assertEqual(status, 200, response)
                register.assert_not_called()
                self.assertNotIn("editing", response)
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
