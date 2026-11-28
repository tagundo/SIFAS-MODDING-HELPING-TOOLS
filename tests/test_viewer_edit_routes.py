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
# Import these with the real model_edits before setUp swaps it in sys.modules:
# a first import inside a test would bind them to the mock for every later test.
from webtools.core import viewer_mod_pair_edits, viewer_scene_roles  # noqa: F401
from webtools.jobs import MANAGER
from webtools.server import Handler


# A reopened scene's readable names (viewer_mod_flow.scene_name_bases).
SCENE_NAMES = {"en": "209 Rina Tennoji · Scene name", "ko": "209 텐노지 리나 · Scene name", "ja": "209 天王寺 璃奈 · Scene name"}


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

        def export(token, state, output_dir, *, log, allow_empty=False):
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
                "sources": [{"source": 0, "container": 0, "member": None,
                    "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}], "variants": {}, "nodes": []}),
            validate_state=Mock(return_value=self.state), export=Mock(side_effect=export),
            accessory_preview=Mock(return_value={"corrections": [], "summary": {"status": "nothing", "changed": 0}}),
            restore=Mock(return_value=self.state))
        self.viewer = SimpleNamespace(MAX_MOTION_FILES=32, get_editing_companions=Mock(return_value=[]), prepare=Mock(return_value={
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
        self.assertEqual(kwargs["companions"], [])
        self.viewer.get_editing_companions.assert_called_once_with(self.token)
        self.assertEqual(self.source.read_bytes(), b"UnityFS source must never change")

    def test_accessory_preview_is_read_only_and_source_bound(self):
        state = {"version": 1, "savedSettingsEnabled": True, "edits": [],
                 "accessoryUnclip": {"strength": 1, "overlap": .15, "closeGaps": False}}
        status, result = self.request("/api/viewer/edit/accessories", {"token": self.token, "state": state})
        self.assertEqual(status, 200, result)
        self.assertEqual(result, {"corrections": [], "summary": {"status": "nothing", "changed": 0}})
        self.backend.accessory_preview.assert_called_once_with(self.token, state)
        self.backend.export.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), b"UnityFS source must never change")

    def test_accessory_preview_rejects_foreign_origins_and_caller_paths(self):
        payload = {"token": self.token, "state": self.state}
        status, _ = self.request("/api/viewer/edit/accessories", payload, headers={"Origin": "https://foreign.example"})
        self.assertEqual(status, 403)
        for invalid in ({**payload, "output_dir": str(self.root)},
                        {**payload, "token": "outside"}, {**payload, "state": []}):
            status, _ = self.request("/api/viewer/edit/accessories", invalid)
            self.assertEqual(status, 400)
        self.backend.accessory_preview.assert_not_called()
        self.backend.export.assert_not_called()

    def test_accessory_preview_reports_unsupported_skin_without_exporting(self):
        self.backend.accessory_preview.side_effect = ValueError("The accessory skin is unsupported.")
        status, result = self.request("/api/viewer/edit/accessories", {"token": self.token, "state": self.state})
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "The accessory skin is unsupported.")
        self.backend.export.assert_not_called()
        self.assertFalse(self.output.exists())

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
        self.assertEqual(job.status, "done", job._events[-3:])
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
        # BrokenPipe while urllib is still streaming the combined edit body.
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.putrequest("POST", "/api/viewer/edit/export")
            connection.putheader("Content-Length", str(32 * 1024 * 1024 + 1))
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

    def test_restore_reports_held_face_rows_and_a_release_notice(self):
        before = [{"id": "0:0:7", "factor": 1.0, "absolute": 40}]
        report = {"heldFaceOutlines": {"count": 0, "meshes": [], "rows": []},
                  "notice": {"text": "This recipe sets the face outlines itself; 1 face outline edit made in the Normal face view was released.", "values": {}}}
        order = []
        self.backend.held_snapshot = Mock(side_effect=lambda token: order.append("snapshot") or before)
        self.backend.restore.side_effect = lambda token, recipe: order.append("restore") or self.state
        self.backend.held_response = Mock(side_effect=lambda token, value: order.append("response") or report)
        status, response = self.request("/api/viewer/edit/restore", {"token": self.token, "recipe": self.recipe})
        self.assertEqual(status, 200, response)
        self.assertEqual(response, {"state": self.state, **report})
        # Taken before the restore, reported after it.
        self.assertEqual(order, ["snapshot", "restore", "response"])
        self.backend.held_response.assert_called_once_with(self.token, before)

    def prepare_with(self, scene_context=None):
        from contextlib import contextmanager
        from webtools.core import viewer_archive
        expanded = SimpleNamespace(paths=[str(self.source)], manifest_paths=[], origins={}, source_names=[self.source.name],
                                   variants=[], archive_members={}, editing_originals=None, editing_variants=None,
                                   scene_context=scene_context)
        @contextmanager
        def expand(*args, **kwargs):
            yield expanded
        with patch.object(viewer_archive, "expand_inputs", expand):
            return self.request("/api/viewer/prepare", {"paths": [str(self.source)], "rigged": True, "auto_face": False})

    def test_prepare_of_a_reopened_scene_reports_its_held_face_rows(self):
        summary = {"count": 1, "meshes": ["Mouth"], "rows": [{"id": "1:0:7", "factor": 0.5}]}
        session = {}
        self.backend._session = Mock(return_value=session)
        self.backend.held_summary = Mock(return_value=summary)
        scene = {"metadata": {"display_name": "Scene name"}}
        from webtools.core import viewer_mod_flow
        with patch.object(viewer_scene_roles, "register_reopened", Mock(return_value=self.state)) as reopened, \
                patch.object(viewer_mod_flow, "scene_name_bases", Mock(return_value=SCENE_NAMES)) as named:
            status, result = self.prepare_with(scene)
        self.assertEqual(status, 200, result)
        reopened.assert_called_once_with(self.token, scene)
        self.backend.held_summary.assert_called_once_with(session)
        self.assertEqual(result["editing"]["heldFaceOutlines"], summary)
        self.assertEqual(result["editing"]["initialState"], self.state)
        # Named after its target member (readable names), in the page language.
        self.assertEqual(named.call_args[0][1], scene["metadata"])
        packaging = result["editing"]["modPackaging"]
        self.assertEqual((packaging["nameBase"], packaging["nameBases"], packaging["nameTexts"], packaging["nameOwner"]),
                         (SCENE_NAMES["en"], SCENE_NAMES, None, None))

    def test_prepare_of_a_saved_scene_original_packages_as_that_scene(self):
        self.backend.register_session = Mock(side_effect=lambda *args, **kwargs: {"available": True, "token": self.token, "nodes": []})
        from webtools.core import viewer_mod_flow
        with patch.object(viewer_scene_roles, "register_preserved", Mock(return_value={"display_name": "Scene name"})) as preserved, \
                patch.object(viewer_mod_flow, "scene_name_bases", Mock(return_value=SCENE_NAMES)) as named:
            status, result = self.prepare_with()
        self.assertEqual(status, 200, result)
        token, context = preserved.call_args[0]
        self.assertEqual((token, context["containers"][0]["path"]), (self.token, str(self.source)))
        # The same readable scene name as reopening the scene ZIP.
        self.assertEqual(named.call_args[0][1], {"display_name": "Scene name"})
        packaging = result["editing"]["modPackaging"]
        self.assertEqual((packaging["nameBase"], packaging["characterId"], packaging["requiresCounterpart"], packaging["sceneRoles"]),
                         (SCENE_NAMES["en"], 209, False, True))
        self.assertEqual((packaging["nameBases"], packaging["nameTexts"], packaging["nameOwner"]), (SCENE_NAMES, None, None))
        self.assertTrue(result["editing"]["allowEmptySceneReset"])
        # Any other model keeps its own packaging.
        status, result = self.prepare_with()
        self.assertEqual(status, 200, result)
        self.assertNotIn("sceneRoles", result["editing"]["modPackaging"])
        self.assertNotIn("allowEmptySceneReset", result["editing"])

    def test_a_reopened_scene_includes_its_face_by_default_only_when_its_mod_zip_shipped_it(self):
        import copy, io, zipfile
        # A scene's originals ZIP always declares the face it keeps for authoring.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("modinstall.txt", "chara_id = 209\ncostume_file = 'android_primary.unity'\n"
                             "rina_unmask_costume_file = 'android_unmasked.unity'\ncostume_facedynamic_file = 'android_face.unity'\n")
        self.source.write_bytes(buffer.getvalue())
        context = self.backend.mod_source_context.return_value
        context["containers"][0].update(raw=buffer.getvalue(), sha256=hashlib.sha256(buffer.getvalue()).hexdigest())
        self.backend._session = Mock(return_value={})
        self.backend.held_summary = Mock(return_value={"count": 0, "meshes": [], "rows": []})
        self.addCleanup(lambda: viewer_scene_roles._SCENES.pop(self.token, None))

        # As the real registrations do: the session's scene is bound, then reported.
        def reopened(token, scene):
            viewer_scene_roles._SCENES[token] = copy.deepcopy(scene["metadata"])
            return self.state

        def preserved(metadata):
            def register(token, context):
                viewer_scene_roles._SCENES[token] = copy.deepcopy(metadata)
                return copy.deepcopy(metadata)
            return register
        for shipped in (False, True):
            metadata = {"display_name": "Scene name", "face_included": shipped}
            viewer_scene_roles._SCENES.pop(self.token, None)
            with self.subTest(reopened=shipped), patch.object(viewer_scene_roles, "register_reopened", side_effect=reopened):
                status, result = self.prepare_with({"metadata": metadata})
                self.assertEqual(status, 200, result)
                packaging = result["editing"]["modPackaging"]
                self.assertEqual((packaging["sceneRoles"], packaging["hasFaceCompanions"], packaging["faceIncluded"]), (True, True, shipped))
            # Re-edit from original: the scene kept beside the saved originals copy.
            viewer_scene_roles._SCENES.pop(self.token, None)
            with self.subTest(preserved=shipped), patch.object(viewer_scene_roles, "register_preserved", side_effect=preserved(metadata)):
                status, result = self.prepare_with()
                self.assertEqual(status, 200, result)
                packaging = result["editing"]["modPackaging"]
                self.assertEqual((packaging["sceneRoles"], packaging["faceIncluded"]), (True, shipped))
        # The same ZIP opened as an ordinary costume ships the face it declares.
        viewer_scene_roles._SCENES.pop(self.token, None)
        with patch.object(viewer_scene_roles, "register_preserved", Mock(return_value=None)):
            status, result = self.prepare_with()
        self.assertEqual(status, 200, result)
        self.assertNotIn("sceneRoles", result["editing"]["modPackaging"])
        self.assertIs(result["editing"]["modPackaging"]["faceIncluded"], True)

    def test_save_mod_zip_proves_game_faces_against_the_face_cache_prepare_uses(self):
        from webtools.core import viewer_mod_flow
        calls = []

        def create(token, state, **options):
            calls.append(options)
            return {"output_paths": [], "mod_package": {}}
        with patch.object(viewer_mod_flow, "create_package", side_effect=create):
            for include in (False, True):
                status, response = self.request("/api/viewer/edit/package", {
                    "token": self.token, "state": self.state, "display_name": "Scene", "character_id": None,
                    "counterpart_path": None, "selected_variant": None, "include_face_edits": include})
                self.assertEqual(status, 200, response)
                self.assertEqual(self.finish(response["job_id"]).status, "done")
        self.assertEqual([call["include_face_edits"] for call in calls], [False, True])
        cache = os.path.join(os.path.realpath(str(self.library)), ".viewer-cache")
        self.assertEqual({call["face_cache_root"] for call in calls}, {cache})

    def test_prepare_reports_the_face_option_as_the_costume_opens(self):
        from contextlib import contextmanager
        from webtools.core import viewer_archive, viewer_mod_flow
        expanded = SimpleNamespace(paths=[str(self.source)], manifest_paths=[], origins={}, source_names=[self.source.name],
                                   variants=[], archive_members={}, editing_originals=None, editing_variants=None,
                                   scene_context=None)

        @contextmanager
        def expand(*args, **kwargs):
            yield expanded
        cache = os.path.join(os.path.realpath(str(self.library)), ".viewer-cache")
        for auto_face in (True, False):
            option = Mock(return_value={"faceIncluded": True, "faceCheck": "unchecked"})
            with self.subTest(auto_face=auto_face), patch.object(viewer_archive, "expand_inputs", expand), \
                    patch.object(viewer_mod_flow, "face_option", option):
                status, result = self.request("/api/viewer/prepare", {"paths": [str(self.source)], "rigged": True,
                                                                      "auto_face": auto_face})
                self.assertEqual(status, 200, result)
                packaging = result["editing"]["modPackaging"]
                self.assertEqual((packaging["faceIncluded"], packaging["faceCheck"]), (True, "unchecked"))
                (context,), options = option.call_args
                self.assertEqual(context, self.backend.mod_source_context.return_value)
                # The game's original is read as the open reads automatic faces:
                # the same face cache, and the asset server only when it may.
                self.assertEqual(options["face_cache_root"], cache)
                self.assertEqual((options["download"], options["face_context"]["allow_download"]), (auto_face, auto_face))
                self.assertEqual(options["face_context"]["cache_dir"], cache)
                self.assertEqual(options["repo_root"], Path.cwd())

    def test_save_mod_zip_checks_game_faces_from_local_copies_only(self):
        from webtools.core import viewer_mod_flow
        calls = []

        def create(token, state, **options):
            calls.append(options)
            return {"output_paths": [], "mod_package": {}}
        with patch.object(viewer_mod_flow, "create_package", side_effect=create):
            status, response = self.request("/api/viewer/edit/package", {
                "token": self.token, "state": self.state, "display_name": "Scene", "character_id": None,
                "counterpart_path": None, "selected_variant": None, "include_face_edits": False})
            self.assertEqual(status, 200, response)
            self.assertEqual(self.finish(response["job_id"]).status, "done")
        context = calls[0]["face_context"]
        self.assertEqual((context["cache_dir"], context["allow_download"]), (calls[0]["face_cache_root"], False))
        self.assertEqual(context["repo_root"], str(calls[0]["repo_root"]))
        self.assertIn(os.path.realpath(str(self.library)), context["library_roots"])

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
