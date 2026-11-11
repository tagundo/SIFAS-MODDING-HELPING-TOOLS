"""HTTP access checks for read-only model preparation and generated GLB sessions."""
import copy
import hashlib
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
            MAX_MOTION_FILES=32,
            prepare=Mock(return_value={"id": self.identifier,
                                       "url": "/api/viewer/model/" + self.identifier + ".glb"}),
            get_model=Mock(return_value=self.glb),
            get_editing_companions=Mock(return_value=[]),
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

    def dual_variant_zip(self, name="rina.zip", companion=False):
        """Generate neutral alternatives from two genuine serialized fixtures."""
        source = self.models / name
        fixtures = Path(__file__).parent / "fixtures"
        board = (fixtures / "viewer_triangle.unity").read_bytes()
        normal = (fixtures / "viewer_textured_triangle.unity").read_bytes()
        manifest = (b"chara_id=209\ncostume_file='board.unity'\n"
                    b"rina_unmask_costume_file='normal.unity'\n")
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("board.unity", board)
            archive.writestr("normal.unity", normal)
            if companion:
                archive.writestr("accessory.unity", board)
            archive.writestr("modinstall.txt", manifest)
            archive.writestr("preview.png", b"not model bytes")
        return source, board, normal, manifest

    def assert_variant_response(self, response, source, selected, index=0):
        self.assertEqual(response["variants"], [{
            "source_index": index, "source_name": source.name, "selected": selected,
            "choices": ["primary", "unmasked"]}])
        # Read-only outline diagnostics expose the selected member's basename
        # and captured hash. Permit that exact source-bound field, while still
        # forbidding member names in arbitrary response fields or private paths.
        checked = copy.deepcopy(response)
        member = "board.unity" if selected == "primary" else "normal.unity"
        with zipfile.ZipFile(source) as archive:
            selected_sha = hashlib.sha256(archive.read(member)).hexdigest()
        records = checked.get("editing", {}).get("outlines", {}).get("sources", [])
        for record in records:
            if record.get("name") == member:
                self.assertIs(type(record["sourceIndex"]), int)
                self.assertGreaterEqual(record["sourceIndex"], 0)
                self.assertEqual(record, {"sourceIndex": record["sourceIndex"],
                                          "name": member, "sha256": selected_sha})
                record["name"] = "<selected source basename>"
        encoded = json.dumps(checked)
        for private in ("source_path", "viewer-zip-", "board.unity", "normal.unity", str(self.base)):
            self.assertNotIn(private, encoded)

    def test_variant_diagnostics_allow_only_the_hash_bound_selected_source_name(self):
        source, board, _, _ = self.dual_variant_zip()
        response = {"variants": [{"source_index": 0, "source_name": source.name,
                                  "selected": "primary", "choices": ["primary", "unmasked"]}],
                    "editing": {"outlines": {"sources": [{"sourceIndex": 0, "name": "board.unity",
                        "sha256": hashlib.sha256(board).hexdigest()}]}}}
        self.assert_variant_response(response, source, "primary")
        self.assertEqual(response["editing"]["outlines"]["sources"][0]["name"], "board.unity")
        for field, value in (("debug", "board.unity"), ("debug", "normal.unity"),
                             ("source_path", "hidden"), ("debug", "viewer-zip-secret"),
                             ("debug", str(self.base))):
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                self.assert_variant_response({**response, field: value}, source, "primary")
        for replacement in ({"sha256": "0" * 64}, {"name": "normal.unity"},
                            {"sourceIndex": True}, {"source_path": "hidden"}):
            changed = copy.deepcopy(response)
            changed["editing"]["outlines"]["sources"][0].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                self.assert_variant_response(changed, source, "primary")

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
        self.backend.get_editing_companions.assert_called_once_with(self.identifier)

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

    def test_variant_zip_defaults_to_only_primary_before_the_model_backend(self):
        source, board, _, manifest = self.dual_variant_zip()
        original, seen = source.read_bytes(), {}

        def prepare(paths, *, face_context, rigged):
            self.assertTrue(rigged)
            self.assertFalse(face_context["enabled"])
            self.assertEqual(len(paths), 1)
            selected = seen["selected"] = Path(paths[0])
            seen["manifest"] = Path(face_context["manifest_paths"][0])
            self.assertEqual(selected.name, "board.unity")
            self.assertEqual(selected.read_bytes(), board)
            self.assertEqual(seen["manifest"].read_bytes(), manifest)
            self.assertEqual(set(face_context["origins"]), {str(selected), str(seen["manifest"])})
            self.assertTrue(all(origin == str(source.resolve()) for origin in face_context["origins"].values()))
            self.assertEqual(sorted(path.name for path in selected.parent.iterdir()),
                             ["board.unity", "modinstall.txt"])
            return {"id": self.identifier}

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(source)], "auto_face": False, "rigged": True})
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertEqual(response["source_names"], [source.name])
        self.assert_variant_response(response, source, "primary")
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(all(not path.exists() for path in seen.values()))
        self.backend.prepare.assert_called_once()

    def test_explicit_normal_variant_excludes_primary_before_face_loading(self):
        source, _, normal, _ = self.dual_variant_zip()
        original, seen = source.read_bytes(), {}

        def prepare(paths, *, face_context):
            self.assertTrue(face_context["enabled"])
            self.assertEqual(len(paths), 1)
            selected = seen["selected"] = Path(paths[0])
            self.assertEqual(selected.name, "normal.unity")
            self.assertEqual(selected.read_bytes(), normal)
            self.assertEqual(sorted(path.name for path in selected.parent.iterdir()),
                             ["modinstall.txt", "normal.unity"])
            self.assertEqual(face_context["origins"][str(selected)], str(source.resolve()))
            return {"id": self.identifier}

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(source)], "archive_variants": {"0": "unmasked"}})
        self.assertEqual(status, 200, body)
        self.assert_variant_response(json.loads(body), source, "unmasked")
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(seen["selected"].exists())
        self.assertNotIn("archive_variants", self.backend.prepare.call_args.kwargs)

    def test_variant_index_uses_original_inputs_after_alias_dedup_and_keeps_companions(self):
        source, board, normal, _ = self.dual_variant_zip(companion=True)
        self.model.write_bytes(board)
        plain_alias = str(self.model.parent) + "/./" + self.model.name
        original, seen = source.read_bytes(), {}

        def prepare(paths, *, face_context):
            self.assertEqual(len(paths), 3)
            self.assertEqual(paths[0], str(self.model.resolve()))
            selected = seen["temporary"] = [Path(path) for path in paths[1:]]
            self.assertEqual([path.name for path in selected], ["normal.unity", "accessory.unity"])
            self.assertEqual([path.read_bytes() for path in selected], [normal, board])
            self.assertEqual(face_context["origins"][paths[0]], str(self.model.resolve()))
            self.assertTrue(all(face_context["origins"][str(path)] == str(source.resolve()) for path in selected))
            self.assertFalse((selected[0].parent / "board.unity").exists())
            return {"id": self.identifier}

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(self.model), plain_alias, str(source)],
            "archive_variants": {"2": "unmasked"}})
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertEqual(response["source_names"], [self.model.name, source.name])
        self.assert_variant_response(response, source, "unmasked", index=2)
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(all(not path.exists() for path in seen["temporary"]))

    def test_two_archives_have_independent_variant_indices(self):
        first, board, normal, _ = self.dual_variant_zip("first.zip")
        second, _, _, _ = self.dual_variant_zip("second.zip")

        def prepare(paths, *, face_context):
            self.assertEqual([Path(path).name for path in paths], ["board.unity", "normal.unity"])
            self.assertEqual([Path(path).read_bytes() for path in paths], [board, normal])
            self.assertEqual([face_context["origins"][path] for path in paths],
                             [str(first.resolve()), str(second.resolve())])
            return {"id": self.identifier}

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(first), str(second)], "archive_variants": {"1": "unmasked"}})
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertEqual([(item["source_index"], item["source_name"], item["selected"])
                          for item in response["variants"]],
                         [(0, "first.zip", "primary"), (1, "second.zip", "unmasked")])
        self.assertNotIn("source_path", body.decode())

    def test_variant_wire_objects_keys_modes_and_indices_are_strict_before_backend(self):
        source, _, _, _ = self.dual_variant_zip()
        invalid = [None, [], True, "unmasked", {"1": "unmasked"}, {"-1": "primary"},
                   {"01": "primary"}, {"+0": "primary"}, {" 0": "primary"},
                   {str(source): "primary"}, {"0": True}, {"0": 1}, {"0": None},
                   {"0": []}, {"0": {"selected": "primary"}}, {"0": "both"},
                   {"0": "masked"}, {"0": "PRIMARY"}, {"0": "board.unity"},
                   {"0": "../../normal.unity"}, {"0": "primary", "1": "unmasked"}]
        for choices in invalid:
            with self.subTest(choices=choices):
                status, _, body = self.request("/api/viewer/prepare", {
                    "paths": [str(source)], "archive_variants": choices})
                self.assertEqual(status, 400, body)
        self.backend.prepare.assert_not_called()

    def test_variant_choice_on_plain_or_generic_zip_does_not_invent_a_variant(self):
        generic = self.models / "generic.zip"
        with zipfile.ZipFile(generic, "w") as archive:
            archive.writestr("body.unity", (Path(__file__).parent / "fixtures/viewer_triangle.unity").read_bytes())
        for source in (self.model, generic):
            with self.subTest(source=source):
                status, _, body = self.request("/api/viewer/prepare", {
                    "paths": [str(source)], "archive_variants": {"0": "unmasked"}})
                self.assertEqual(status, 400, body)
        self.backend.prepare.assert_not_called()

    def test_duplicate_alias_choices_conflict_before_backend_and_equal_choices_deduplicate(self):
        source, _, normal, _ = self.dual_variant_zip()
        alias = self.models / "same-zip-alias.zip"
        alias.symlink_to(source)
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(source), str(alias)],
            "archive_variants": {"0": "primary", "1": "unmasked"}})
        self.assertEqual(status, 400, body)
        self.assertIn("Conflicting", json.loads(body)["error"])
        self.backend.prepare.assert_not_called()

        def prepare(paths, *, face_context):
            self.assertEqual(len(paths), 1)
            self.assertEqual(Path(paths[0]).read_bytes(), normal)
            return {"id": self.identifier}

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(source), str(alias)],
            "archive_variants": {"0": "unmasked", "1": "unmasked"}})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["source_names"], [source.name])
        self.assert_variant_response(json.loads(body), source, "unmasked", index=0)
        self.backend.prepare.assert_called_once()

    def test_selected_variant_cleanup_survives_backend_rejection(self):
        source, _, _, _ = self.dual_variant_zip()
        original, seen = source.read_bytes(), []

        def prepare(paths, *, face_context):
            seen.extend(Path(path) for path in paths + face_context["manifest_paths"])
            self.assertTrue(all(path.exists() for path in seen))
            raise ValueError("The selected variant has no visible model meshes.")

        self.backend.prepare.side_effect = prepare
        status, _, body = self.request("/api/viewer/prepare", {
            "paths": [str(source)], "archive_variants": {"0": "unmasked"}})
        self.assertEqual(status, 400, body)
        self.assertIn("selected variant", json.loads(body)["error"])
        self.assertTrue(seen)
        self.assertTrue(all(not path.exists() for path in seen))
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
