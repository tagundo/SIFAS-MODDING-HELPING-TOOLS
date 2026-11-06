"""HTTP boundaries for original-bound viewer exports and portable recipes."""
import json
import hashlib
import http.client
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request
from urllib.parse import quote

import webtools.core
from webtools.jobs import MANAGER
from webtools.server import Handler


class ViewerEditRouteTests(unittest.TestCase):
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
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.library = self.root / "sukusta"
        self.models = self.library / "extracted/3d_model"
        self.models.mkdir(parents=True)
        self.source = self.models / "original.unity"
        self.source.write_bytes(b"UnityFS source must never change")
        self.token = "a" * 32
        self.state = {"version": 1, "savedSettingsEnabled": True,
                      "edits": [{"node": 3, "scale": [1, 1.2, 1.3], "method": "auto"}]}
        self.recipe = {"version": 1, "sources": [{"sha256": "b" * 64}], "state": self.state}
        self.output = self.library / "modded/viewer/new-copy/original.unity"
        self.recipe_path = self.output.with_name("editing-recipe.json")

        def export(token, state, output_dir, *, log):
            self.assertEqual(token, self.token)
            self.assertEqual(state, self.state)
            self.assertEqual(output_dir, str(self.library / "modded/viewer"))
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_bytes(b"UnityFS edited copy")
            self.recipe_path.write_text(json.dumps(self.recipe))
            return {"output_paths": [str(self.output)], "preview_paths": [str(self.output)],
                    "recipe_path": str(self.recipe_path)}

        self.backend = SimpleNamespace(
            register_session=Mock(return_value={"available": True, "token": self.token, "nodes": []}),
            mod_source_context=Mock(return_value={"model_id": self.token,
                "containers": [{"path": str(self.source), "name": self.source.name,
                    "raw": self.source.read_bytes(),
                    "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}],
                "sources": [], "variants": {}, "nodes": []}),
            validate_state=Mock(return_value=self.state), export=Mock(side_effect=export),
            restore=Mock(return_value=self.state))
        self.viewer = SimpleNamespace(prepare=Mock(return_value={
            "id": self.token, "rig": {"available": True, "bones": []}}))
        for name, value in (("model_edits", self.backend), ("model_viewer", self.viewer)):
            context = patch.dict(sys.modules, {"webtools.core." + name: value})
            context.start()
            self.addCleanup(context.stop)
            context = patch.object(webtools.core, name, value, create=True)
            context.start()
            self.addCleanup(context.stop)
        context = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        context.start()
        self.addCleanup(context.stop)

    def request(self, path, payload=None, *, raw=None, headers=None):
        body = json.dumps(payload).encode() if payload is not None else raw
        request = urllib.request.Request(self.url + path, data=body,
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def export_request(self, **extra):
        return self.request("/api/viewer/edit/export", {"token": self.token, "state": self.state, **extra})

    def finish(self, job_id):
        job = MANAGER.get(job_id)
        limit = time.monotonic() + 3
        while not job.is_done and time.monotonic() < limit:
            time.sleep(.01)
        self.assertTrue(job.is_done)
        return job

    def test_prepare_registers_only_selected_editable_sources(self):
        status, result = self.request("/api/viewer/prepare", {
            "paths": [str(self.source)], "rigged": True, "auto_face": False})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["editing"]["available"])
        args, kwargs = self.backend.register_session.call_args
        self.assertEqual(args[:2], (self.token, [str(self.source)]))
        self.assertEqual(kwargs["originals"], [str(self.source)])
        self.assertIn("archive_members", kwargs)
        self.assertEqual(self.source.read_bytes(), b"UnityFS source must never change")

    def test_cache_failure_keeps_read_only_viewer_available(self):
        self.backend.register_session.side_effect = OSError("Editing cache is full.")
        status, result = self.request("/api/viewer/prepare", {
            "paths": [str(self.source)], "rigged": True, "auto_face": False})
        self.assertEqual(status, 200)
        self.assertEqual(result["id"], self.token)
        self.assertFalse(result["editing"]["available"])

    def test_export_publishes_copy_recipe_and_reopen_paths_after_job(self):
        status, response = self.export_request()
        self.assertEqual(status, 200, response)
        job = self.finish(response["job_id"])
        self.assertEqual(job.status, "done")
        status, result = self.request("/api/viewer/edit/result/" + job.id)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["preview_paths"], [str(self.output)])
        self.assertEqual(job.output_paths(), [str(self.output), str(self.recipe_path)])
        self.assertEqual(self.source.read_bytes(), b"UnityFS source must never change")

    def test_no_caller_paths_or_extra_flags_reach_export_backend(self):
        for extra in ({"output_dir": str(self.root)}, {"path": str(self.source)},
                      {"name": "../../outside"}, {"overwrite": True}):
            with self.subTest(extra=extra):
                self.assertEqual(self.export_request(**extra)[0], 400)
        self.backend.export.assert_not_called()

    def test_malformed_large_or_unbound_requests_are_rejected(self):
        for payload in ({}, [], {"token": "../x", "state": self.state},
                        {"token": self.token, "state": []},
                        {"token": self.token, "state": self.state, "ignored": True}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("/api/viewer/edit/export", payload)[0], 400)
        self.assertEqual(self.request("/api/viewer/edit/export", raw=b"not-json")[0], 400)
        # An oversized declaration is rejected before reading its body. Send
        # only the headers so an intentional early close is not a client-side
        # BrokenPipe while urllib is still streaming half a megabyte.
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.putrequest("POST", "/api/viewer/edit/export")
            connection.putheader("Content-Length", str(512 * 1024 + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
        self.backend.export.assert_not_called()

    def test_invalid_or_expired_state_fails_before_creating_export_job(self):
        self.backend.validate_state.side_effect = ValueError("Editing session expired.")
        status, response = self.export_request()
        self.assertEqual(status, 400)
        self.assertIn("expired", response["error"])
        self.backend.export.assert_not_called()

    def test_cross_origin_writes_rejected_same_origin_allowed(self):
        payload = {"token": self.token, "recipe": self.recipe}
        for origin in ("https://untrusted.invalid", "null", self.url + "/other", self.url + "?x=1"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("/api/viewer/edit/restore", payload,
                                             headers={"Origin": origin})[0], 403)
        self.backend.restore.assert_not_called()
        self.assertEqual(self.request("/api/viewer/edit/restore", payload,
                                     headers={"Origin": self.url})[0], 200)

    def test_restore_is_source_bound_and_rejects_overrides(self):
        status, response = self.request("/api/viewer/edit/restore", {
            "token": self.token, "recipe": self.recipe})
        self.assertEqual(status, 200, response)
        self.assertEqual(response["state"], self.state)
        self.backend.restore.assert_called_once_with(self.token, self.recipe)
        self.backend.restore.reset_mock()
        self.assertEqual(self.request("/api/viewer/edit/restore", {
            "token": self.token, "recipe": self.recipe, "source": str(self.source)})[0], 400)
        self.backend.restore.assert_not_called()

    def test_failed_background_job_has_no_success_result(self):
        self.backend.export.side_effect = ValueError("Unsupported source geometry.")
        status, response = self.export_request()
        self.assertEqual(status, 200)
        job = self.finish(response["job_id"])
        self.assertEqual(job.status, "error")
        self.assertEqual(self.request("/api/viewer/edit/result/" + job.id)[0], 400)
        self.assertFalse(self.output.exists())

    def test_pending_or_unrelated_job_does_not_expose_result(self):
        pending = MANAGER.create("viewer_body_edit")
        self.assertEqual(self.request("/api/viewer/edit/result/" + pending.id)[0], 202)
        other = MANAGER.create("unrelated")
        self.assertEqual(self.request("/api/viewer/edit/result/" + other.id)[0], 404)
        for token in ("../outside", "f" * 12, "invalid"):
            self.assertEqual(self.request("/api/viewer/edit/result/" + token)[0], 404)

    def test_unicode_model_download_preserves_name_in_valid_http_header(self):
        source = self.models / "의상_衣装.unity"
        source.write_bytes(b"UnityFS original Unicode filename")
        request = urllib.request.Request(self.url + "/api/download?path=" + quote(str(source), safe=""))
        with self.opener.open(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), source.read_bytes())
            disposition = response.headers["Content-Disposition"]
            self.assertTrue(disposition.isascii())
            self.assertIn("filename*=UTF-8''" + quote(source.name, safe=""), disposition)
            self.assertNotIn("\r", disposition)
            self.assertNotIn("\n", disposition)


if __name__ == "__main__":
    unittest.main()
