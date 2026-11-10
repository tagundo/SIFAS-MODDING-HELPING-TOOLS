"""Strict reimport routes and fresh source-bound viewer/game sessions."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import webtools.core
from webtools.core import model_viewer as real_viewer
from webtools.core import game_models as game
from webtools.jobs import Job
import test_viewer_routes as routes
import test_game_models as game_fixture


class ReimportRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy  # preload before the legacy route mock snapshots sys.modules
            import numpy
            cls.native_available = True
        except ImportError:
            cls.native_available = False
        routes.ViewerRouteTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        routes.ViewerRouteTests.tearDownClass.__func__(cls)

    def setUp(self):
        routes.ViewerRouteTests.setUp(self)

    request = routes.ViewerRouteTests.request

    def test_prepare_reimport_is_strict_and_forwarded_only_when_enabled(self):
        for invalid in (None, 0, 1, "true", [], {}):
            with self.subTest(reimport=invalid):
                status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)], "reimport": invalid})
                self.assertEqual(status, 400, body)
        self.backend.prepare.assert_not_called()
        for enabled in (False, True):
            self.backend.prepare.reset_mock()
            status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)], "reimport": enabled})
            self.assertEqual(status, 200, body)
            self.backend.prepare.assert_called_once()
            kwargs = self.backend.prepare.call_args.kwargs
            self.assertEqual(kwargs.get("reimport", False), enabled)
            self.assertEqual(self.model.read_bytes(), b"UnityFS input")

    def test_actual_http_reimport_rereads_pixels_and_creates_fresh_editing_tokens(self):
        if not self.native_available:
            self.skipTest("UnityPy and NumPy are required for the actual HTTP model roundtrip")
        self.model.write_bytes((Path(__file__).parent / "fixtures/viewer_rig.unity").read_bytes())
        original = hashlib.sha256(self.model.read_bytes()).hexdigest()
        real_viewer._TEXTURE_PNGS.clear()
        real_viewer._NORMALIZED_BUNDLES.clear()
        observed, rendered = [], []
        with patch.dict(sys.modules, {"webtools.core.model_viewer": real_viewer}), \
                patch.object(webtools.core, "model_viewer", real_viewer), \
                patch.object(real_viewer.decode, "_android_image", wraps=real_viewer.decode._android_image) as decode:
            counts = []
            for enabled in (False, False, True):
                status, _, body = self.request("/api/viewer/prepare", {"paths": [str(self.model)], "rigged": True,
                                                                      "auto_face": False, "reimport": enabled})
                self.assertEqual(status, 200, body)
                value = json.loads(body)
                observed.append(value)
                self.assertTrue(value["editing"]["available"])
                self.assertEqual(value["editing"]["token"], value["id"])
                status, _, data = self.request(value["url"])
                self.assertEqual(status, 200)
                self.assertTrue(data.startswith(b"glTF"))
                rendered.append(data)
                counts.append(decode.call_count)
            self.assertGreater(counts[0], 0)
            self.assertEqual(counts[0], counts[1])
            self.assertGreater(counts[2], counts[1])
        self.assertEqual(len({row["id"] for row in observed}), 3)
        self.assertEqual(rendered, [rendered[0]] * 3)
        self.assertEqual(hashlib.sha256(self.model.read_bytes()).hexdigest(), original)

    def test_game_import_rejects_non_boolean_reimport_before_catalog_or_job(self):
        for invalid in (None, 0, 1, "true", [], {}):
            with self.subTest(reimport=invalid), patch.object(game, "validate_selection") as selection:
                status, _, body = self.request("/api/viewer/game/import", {"region": "gl", "suit": "suit:1",
                    "variant": "primary", "download": False, "reimport": invalid})
                self.assertEqual(status, 400, body)
                selection.assert_not_called()


@unittest.skipUnless(game_fixture.extractor, "Elichika extractor is required")
class GameReimportTests(unittest.TestCase):
    setUp = game_fixture.GameModelTests.setUp
    select = game_fixture.GameModelTests.select

    def test_cached_and_forced_imports_keep_originals_and_create_new_verified_copy(self):
        record = self.select()
        original_packs = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in self.original}
        outputs = []
        with patch.object(game, "_plain_section", wraps=game._plain_section) as decrypt:
            for reimport in (False, False, True):
                job = Job("reimport", "viewer_game_assets")
                game.run_import(job, repo_root=self.root, output_root=self.output, record=record, reimport=reimport)
                paths = job.output_paths()
                self.assertEqual(len(paths), 1)
                outputs.append(Path(paths[0]))
                self.assertEqual(outputs[-1].read_bytes(), self.payload)
                self.assertEqual(decrypt.call_count, 2 if reimport else 1)
        self.assertEqual(outputs[0], outputs[1])
        self.assertNotEqual(outputs[0], outputs[2])
        self.assertTrue(outputs[0].is_file())
        self.assertEqual(outputs[0].read_bytes(), outputs[2].read_bytes())
        for path, digest in original_packs.items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)
        for invalid in (None, 1, "true"):
            with self.subTest(reimport=invalid), self.assertRaisesRegex(ValueError, "Reimport"):
                game.run_import(Job("bad", "viewer_game_assets"), repo_root=self.root,
                                output_root=self.output, record=record, reimport=invalid)


if __name__ == "__main__":
    unittest.main()
