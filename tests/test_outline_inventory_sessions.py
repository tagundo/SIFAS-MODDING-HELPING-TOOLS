"""Static original outline inventory must not authorize persistent editing."""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
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

from sifas_mesh_baker import stream_layout
from webtools.core import model_edits, model_viewer
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
        self.assertFalse(metadata["available"])
        self.assertNotIn("token", metadata)
        self.assertEqual(metadata["reason"], reason)
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

    def test_actual_static_renderer_inventory_without_edit_session(self):
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        self.assertEqual(preview["stats"]["meshes"], 1)
        self.assertFalse(preview["rig"]["available"])
        self.assertTrue(model_viewer.get_model(preview["id"]).startswith(b"glTF"))
        metadata = model_edits.register_session(preview["id"], [str(self.source)], preview["rig"])
        self.assert_inventory(metadata)
        self.assertNotIn(preview["id"], model_edits._SESSIONS)
        with self.assertRaises(model_edits.ModelEditError):
            model_edits.export(preview["id"], {"version": 1, "edits": []}, self.root / "output", allow_empty=True)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_unavailable_rig_cannot_authorize_supplied_bone_metadata(self):
        token = secrets.token_hex(16)
        rig = {"available": False, "bones": [{"node": 1, "sourceIndex": 0,
            "transformId": "3", "sourceHash": hashlib.sha256(self.raw).hexdigest()}]}
        self.assert_inventory(model_edits.register_session(token, [str(self.source)], rig))
        self.assertNotIn(token, model_edits._SESSIONS)

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

    def test_available_flag_without_writable_nodes_preserves_inventory_only(self):
        token = secrets.token_hex(16)
        self.assert_inventory(model_edits.register_session(token, [str(self.source)],
            {"available": True, "bones": []}), reason="No original writable body nodes were found.")
        self.assertNotIn(token, model_edits._SESSIONS)

    def test_http_static_rig_inventory_is_reported_but_export_stays_unavailable(self):
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
        self.assertNotIn(response["id"], model_edits._SESSIONS)
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
