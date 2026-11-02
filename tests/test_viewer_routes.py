"""HTTP access checks for read-only model preparation and generated GLB sessions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

import webtools.core
from webtools.server import Handler


class ViewerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.library = self.base / "sukusta"
        self.models = self.library / "extracted" / "3d_model"
        self.models.mkdir(parents=True)
        self.model = self.models / "costume.unity"
        self.model.write_bytes(b"UnityFS input")
        self.identifier = "a" * 32
        self.glb = b"glTF\x02\x00\x00\x00test-only-response"
        self.backend = SimpleNamespace(
            prepare=Mock(return_value={"id": self.identifier,
                                       "url": "/api/viewer/model/" + self.identifier + ".glb"}),
            get_model=Mock(return_value=self.glb),
        )
        env = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        env.start()
        self.addCleanup(env.stop)
        modules = patch.dict(sys.modules, {"webtools.core.model_viewer": self.backend})
        modules.start()
        self.addCleanup(modules.stop)
        attribute = patch.object(webtools.core, "model_viewer", self.backend, create=True)
        attribute.start()
        self.addCleanup(attribute.stop)

    def request(self, path, data=None, raw=None):
        body = json.dumps(data).encode() if data is not None else raw
        request = urllib.request.Request(self.url + path, data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_prepare_resolves_and_deduplicates_only_authorized_paths(self):
        status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)] * 2})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["id"], self.identifier)
        self.backend.prepare.assert_called_once()
        args, kwargs = self.backend.prepare.call_args
        self.assertEqual(args, ([str(self.model.resolve())],))
        context = kwargs["face_context"]
        self.assertTrue(context["enabled"])
        self.assertTrue(context["allow_download"])
        self.assertEqual(context["repo_root"], str(Path.cwd()))
        self.assertIn(str(self.models.resolve()), context["library_roots"])
        self.assertNotIn("chara_id", context)
        self.assertEqual(self.model.read_bytes(), b"UnityFS input")

    def test_face_context_cannot_be_injected_and_disable_flag_is_strict(self):
        for extra in ({"face_context": {"repo_root": "/private", "cdn_base": "https://untrusted/"}},
                      {"chara_id": 101}, {"auto_face": 1}, {"auto_face": "true"}):
            with self.subTest(extra=extra):
                status, _, _ = self.request("/api/viewer/prepare", {"paths": [str(self.model)], **extra})
                self.assertEqual(status, 400)
        self.backend.prepare.assert_not_called()
        status, _, body = self.request("/api/viewer/prepare",
                                       {"paths": [str(self.model)], "auto_face": False})
        self.assertEqual(status, 200, body)
        context = self.backend.prepare.call_args.kwargs["face_context"]
        self.assertFalse(context["enabled"])
        self.assertFalse(context["allow_download"])

    def test_interactive_rig_flag_is_strict_and_does_not_accept_runtime_transforms(self):
        for extra in ({"rigged": 1}, {"rigged": "true"}, {"rigged": None},
                      {"bone_scales": {"BreastSize": [2, 2, 2]}},
                      {"previewMotion": {"kind": "sifas_suit_preview", "verified": True,
                                         "name": "untrusted_clip"}},
                      {"verified_resources": ["/private/motion.unity"]}):
            with self.subTest(extra=extra):
                status, _, _ = self.request("/api/viewer/prepare", {"paths": [str(self.model)], **extra})
                self.assertEqual(status, 400)
        self.backend.prepare.assert_not_called()
        status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)], "rigged": True})
        self.assertEqual(status, 200, body)
        self.backend.prepare.assert_called_once()
        self.assertIs(self.backend.prepare.call_args.kwargs["rigged"], True)
        self.assertNotIn("bone_scales", self.backend.prepare.call_args.kwargs)

    def test_legacy_prepare_remains_static_unless_interactive_loading_is_requested(self):
        for extra in ({}, {"rigged": False}):
            with self.subTest(extra=extra):
                self.backend.prepare.reset_mock()
                status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)], **extra})
                self.assertEqual(status, 200, body)
                self.assertNotIn("rigged", self.backend.prepare.call_args.kwargs)

    def test_costume_zip_passes_only_temporary_model_and_manifest_data(self):
        source = self.models / "costume.zip"
        fixture = (Path(__file__).parent / "fixtures/viewer_triangle.unity").read_bytes()
        manifest = b"chara_id=207\ncostume_file='207setsuna'\n"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("207setsuna", fixture)
            archive.writestr("modinstall.txt", manifest)
            archive.writestr("preview.png", b"image bytes not sent to Unity")
        original = source.read_bytes()
        seen = {}
        def prepare(paths, *, face_context):
            self.assertEqual(len(paths), 1)
            seen["path"] = Path(paths[0])
            self.assertEqual(seen["path"].read_bytes(), fixture)
            self.assertEqual(Path(face_context["manifest_paths"][0]).read_bytes(), manifest)
            self.assertEqual(face_context["origins"][paths[0]], str(source.resolve()))
            return {"id": self.identifier}
        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {"paths": [str(source)]})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["source_names"], ["costume.zip"])
        self.assertFalse(seen["path"].exists())
        self.assertEqual(source.read_bytes(), original)

    def test_unsafe_zip_is_rejected_before_unity_or_face_loading(self):
        source = self.models / "unsafe.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("../private", b"UnityFS\0" + b"\0" * 64)
        status, _, body = self.request("/api/viewer/prepare", {"paths": [str(source)]})
        self.assertEqual(status, 400, body)
        self.backend.prepare.assert_not_called()

    def test_outside_path_and_symlink_escape_are_rejected_before_model_loading(self):
        outside = self.base / "outside.unity"
        outside.write_bytes(b"private")
        linked = self.models / "escape.unity"
        linked.symlink_to(outside)
        for path in (outside, linked):
            with self.subTest(path=path):
                status, _, _ = self.request("/api/viewer/prepare", {"paths": [str(path)]})
                self.assertEqual(status, 403)
        self.backend.prepare.assert_not_called()

    def test_missing_model_and_invalid_requests_have_actionable_errors(self):
        status, _, _ = self.request("/api/viewer/prepare", {"paths": [str(self.models / "missing.unity")]})
        self.assertEqual(status, 404)
        for params in ({}, {"paths": []}, {"paths": "not a list"}, {"paths": [False]},
                       {"paths": [str(self.model)] * 9}, [str(self.model)]):
            with self.subTest(params=params):
                status, _, _ = self.request("/api/viewer/prepare", params)
                self.assertEqual(status, 400)
        status, _, _ = self.request("/api/viewer/prepare", raw=b"{" + b" " * 17000)
        self.assertEqual(status, 400)
        self.backend.prepare.assert_not_called()

    def test_invalid_unity_file_is_a_client_error(self):
        self.backend.prepare.side_effect = ValueError("This file has no visible model meshes.")
        status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)]})
        self.assertEqual(status, 400)
        self.assertIn("visible model", json.loads(body)["error"])

    def test_glb_session_response_has_binary_mime_and_no_browser_cache(self):
        status, headers, body = self.request("/api/viewer/model/" + self.identifier + ".glb")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "model/gltf-binary")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body, self.glb)
        self.backend.get_model.assert_called_once_with(self.identifier)

    def test_unknown_and_malformed_sessions_do_not_open_files(self):
        self.backend.get_model.return_value = None
        status, _, body = self.request("/api/viewer/model/" + self.identifier + ".glb")
        self.assertEqual(status, 404)
        self.assertIn("expired", json.loads(body)["error"])
        self.backend.get_model.reset_mock()
        for name in ("private.unity", "../private.glb", "a" * 31 + ".glb", "G" * 32 + ".glb"):
            status, _, _ = self.request("/api/viewer/model/" + name)
            self.assertEqual(status, 404)
        self.backend.get_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
