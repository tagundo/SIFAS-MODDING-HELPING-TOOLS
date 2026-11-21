"""A costume platform preview selects one authorized native counterpart."""
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import UnityPy

from webtools.core import costume_platform_source as platform
from webtools.core import game_models as game, viewer_physics_runtime
from webtools.jobs import Job
from webtools.server import Handler

import test_game_models as fixtures
import test_game_models_transplant as native_fixtures


@unittest.skipUnless(fixtures.extractor, "The application asset extractor is required")
class CostumePlatformSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_fixtures.TransplantGameModelTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.ios_catalog()
        self.root = self.fixture.root.resolve()
        self.cache = self.fixture.helper.output.resolve()
        self.target_cache = self.cache / "transplant-bodies"
        self.packs = self.fixture.helper.packs.resolve()
        self.library = self.fixture.helper.library.resolve()
        self.file = self.library / "edited" / "renamed.unity"
        self.file.parent.mkdir(parents=True)
        self.no_download = patch.object(game, "_remote_pack", side_effect=AssertionError("unexpected download")).start()
        self.no_scan = patch.object(fixtures.extractor, "indexed_pack_file", side_effect=AssertionError("unexpected scan")).start()
        self.addCleanup(patch.stopall)

    def edited_bundle_from_receipt(self):
        job = Job("original", "viewer_game_assets")
        original = game.validate_selection(self.root, {
            "region": "gl", "suit": "suit:1", "variant": "primary", "download": False,
            "purpose": "transplant", "platform": "android",
        }, "ko")
        # First create a fresh native selection and its genuine cache receipt.
        game.run_import(job, repo_root=self.root, output_root=self.target_cache, record=original,
                        source_lookup=platform._LocalPacks())
        (original_path,) = map(Path, job.output_paths())
        raw = original_path.read_bytes()
        environment = UnityPy.load(raw)
        obj = next(parent for parent in environment.objects if parent.type.name == "Mesh")
        value = obj.read_typetree()
        value["m_Name"] += "Edited"
        obj.save_typetree(value)
        changed = environment.file.save()
        self.assertNotEqual(raw, changed)
        self.file.write_bytes(changed)
        sha = hashlib.sha256(raw).hexdigest()
        viewer_physics_runtime._write_receipts(self.cache, self.file, [{
            "member": None, "sha256": hashlib.sha256(changed).hexdigest(), "operation": "part",
            "parents": [platform._proof(original_path, sha)], "components": [],
        }])
        return original_path

    def requests(self, **kwargs):
        return {"path": str(self.file), "direction": "android_to_ios", "region": "gl", **kwargs}

    def preview(self, **kwargs):
        return platform.match(self.root, self.requests(**kwargs), language="ko", cache_root=self.cache)

    def test_renamed_edited_wearer_receipt_matches_and_extracts_native_counterpart(self):
        original = self.edited_bundle_from_receipt()
        expected = (self.packs / "basepack_ios").read_bytes()
        self.assertNotEqual(original.read_bytes(), expected)
        result = self.preview()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["selection"], {"region": "gl", "suit": "suit:1", "variant": "primary",
                                               "purpose": "transplant", "platform": "ios", "download": False})
        self.assertFalse(result["missing"])
        self.assertEqual(result["missing_bytes"], 0)
        self.assertIn("첫 의상", result["label"])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn("key1", json.dumps(result))
        self.assertEqual(self.preview(region="jp")["message"], platform.WRONG_REGION)
        resolved = platform.resolve(self.root, self.requests(), language="ko", cache_root=self.cache)
        job = Job("prepare", "costume_platform")
        output = platform.prepare_target(job, repo_root=self.root, resolved=resolved, output_root=self.target_cache)
        self.assertEqual({int(asset.target_platform) for asset in UnityPy.load(str(output)).assets}, {9})
        self.assertEqual(job.output_paths(), [])
        self.assertEqual(original, platform.prepare_source_original(
            job, repo_root=self.root, resolved=resolved, output_root=self.target_cache))
        self.assertEqual((self.packs / "basepack_ios").read_bytes(), expected)

    def test_missing_pack_requires_consent_and_sharded_alternate_supplies_it(self):
        self.edited_bundle_from_receipt()
        raw = (self.packs / "basepack_ios").read_bytes()
        (self.packs / "basepack_ios").unlink()
        result = self.preview()
        self.assertEqual((result["status"], result["missing"], result["missing_bytes"]), ("matched", True, len(raw)))
        resolved = platform.resolve(self.root, self.requests(), language="ko", cache_root=self.cache)
        job = Job("missing", "costume_platform")
        with self.assertRaisesRegex(ValueError, "pack is missing"):
            platform.prepare_target(job, repo_root=self.root, resolved=resolved, output_root=self.target_cache)
        alternate = self.library / "selected-packs"
        bucket = alternate / "files" / "pak24"
        bucket.mkdir(parents=True)
        (bucket / "basepack_ios").write_bytes(raw)
        result = self.preview(packs_dir=str(alternate))
        self.assertEqual((result["status"], result["missing"]), ("matched", False))
        resolved = platform.resolve(self.root, self.requests(packs_dir=str(alternate)), language="ko", cache_root=self.cache)
        self.assertTrue(platform.prepare_target(
            job, repo_root=self.root, resolved=resolved, output_root=self.target_cache).is_file())
        self.no_download.assert_not_called()
        self.no_scan.assert_not_called()

    def test_explicit_download_fetches_the_one_selected_pack(self):
        self.edited_bundle_from_receipt()
        path = self.packs / "basepack_ios"
        raw = path.read_bytes()
        path.unlink()
        resolved = platform.resolve(self.root, self.requests(), language="ko", cache_root=self.cache)
        self.assertTrue(resolved["missing"])
        self.no_download.side_effect = None
        self.no_download.return_value = raw
        job = Job("download", "costume_platform")
        output = platform.prepare_target(job, repo_root=self.root, resolved=resolved, output_root=self.target_cache,
                                         download=True)
        self.assertTrue(output.is_file())
        self.no_download.assert_called_once()
        self.assertEqual(self.no_download.call_args.args[0]["pack_name"], "basepack_ios")
        self.assertFalse(path.exists())
        self.assertFalse(self.preview()["missing"])

    def test_filename_hint_without_verified_identity_fails_and_duplicate_color_is_ambiguous(self):
        self.file = self.file.with_name("ch0101_suit1_primary.unity")
        self.file.write_bytes(self.fixture.helper.payload)
        self.assertEqual(self.preview()["status"], "unknown")
        identity = (101, "assets/llas/resources/characters/models/ch0101/ch0101_co0002_member.prefab", 1, "cab-" + "a" * 32)
        with patch.object(platform, "_body_identity", side_effect=(identity, None, None)):
            self.assertEqual(self.preview()["status"], "unknown")
        with patch.object(platform, "_body_identity", return_value=identity):
            self.assertEqual(self.preview()["status"], "ambiguous")
        with sqlite3.connect(self.root / "assets/db/gl/masterdata.db") as db:
            db.execute("DELETE FROM m_suit WHERE id=3")
        with patch.object(platform, "_body_identity", return_value=identity):
            self.assertEqual(self.preview()["status"], "matched")


    def write_costume_zip(self, bodies, manifest=None):
        self.file = self.file.with_name("opaque.zip")
        with zipfile.ZipFile(self.file, "w", zipfile.ZIP_DEFLATED) as package:
            for name, raw in bodies.items():
                package.writestr(name, raw)
            if manifest is not None:
                package.writestr("modinstall.txt", manifest)

    def test_zip_label_requires_same_platform_canonical_identity(self):
        self.write_costume_zip({"opaque-body.unity": self.fixture.helper.payload},
                               'costume_file = "opaque-body.unity"\n'
                               'costume_name_ko = "ch0101_suit1_primary · Edited"\n')
        identity = (101, "assets/llas/resources/characters/models/ch0101/ch0101_co0002_member.prefab",
                    1, "cab-" + "a" * 32)
        with sqlite3.connect(self.root / "assets/db/gl/masterdata.db") as db:
            db.execute("DELETE FROM m_suit WHERE id=3")
        with patch.object(platform, "_body_identity", side_effect=(identity, None)):
            self.assertEqual(self.preview()["status"], "unknown")
        with patch.object(platform, "_body_identity", return_value=identity):
            self.assertEqual(self.preview()["selection"]["suit"], "suit:1")
            (self.packs / "basepack").unlink()
            self.assertEqual(self.preview()["status"], "unknown")
        self.no_download.assert_not_called()
        with self.assertRaisesRegex(ValueError, "no iOS body"):
            self.preview(direction="ios_to_android")

    def test_zip_chooses_verified_native_body_and_pins_conversion_snapshot(self):
        android = self.fixture.helper.payload
        extractor = fixtures.extractor
        ios = bytearray((self.packs / "basepack_ios").read_bytes())
        extractor.decrypt_section(ios, extractor.FIXED_KEY0, 7, 11)
        self.write_costume_zip({"bodyA.unity": android, "bodyI.unity": bytes(ios)},
                               'costume_file = "bodyA.unity"\ncostume_file_ios = "bodyI.unity"\n')
        archive = self.file.read_bytes()
        for name, target, raw in (("android", 13, android), ("ios", 9, bytes(ios))):
            with self.subTest(platform=name):
                with platform.converter_input(self.file, name) as (body, sha):
                    self.assertEqual(body.read_bytes(), raw)
                    self.assertEqual(sha, hashlib.sha256(raw).hexdigest())
                    self.assertEqual({int(asset.target_platform) for asset in UnityPy.load(str(body)).assets}, {target})
                self.assertFalse(body.exists())
        with self.assertRaisesRegex(ValueError, "ZIP changed"):
            with platform.converter_input(self.file, "android", expected_sha256="0" * 64):
                self.fail("An unexpected body must not reach the converter.")
        self.assertEqual(self.file.read_bytes(), archive)

    def test_ambiguous_and_unsafe_archives_are_refused(self):
        android = self.fixture.helper.payload
        self.write_costume_zip({"one.unity": android, "two.unity": android},
                               'costume_file = "one.unity"\ncostume_file_ios = "two.unity"\n')
        with self.assertRaisesRegex(ValueError, "multiple bodies"):
            self.preview()
        self.write_costume_zip({"one.unity": android}, 'costume_file = "missing.unity"\n')
        with self.assertRaisesRegex(ValueError, "missing or conflicting"):
            self.preview()
        self.write_costume_zip({"one.unity": android, "../escape": b"ignored"},
                               'costume_file = "one.unity"\n')
        with self.assertRaisesRegex(ValueError, "unsafe file path"):
            self.preview()
        escaped = self.root / "executed"
        self.write_costume_zip({"one.unity": android},
                               f'open({str(escaped)!r}, "w")\ncostume_file = "one.unity"\n')
        with self.assertRaisesRegex(ValueError, "literal assignments"):
            self.preview()
        self.assertFalse(escaped.exists())

    def test_alternate_link_escapes_are_rejected_or_ignored(self):
        self.edited_bundle_from_receipt()
        outside = self.library / "outside"
        outside.mkdir()
        (self.packs / "basepack_ios").rename(outside / "basepack_ios")
        alternate = self.library / "selected-packs"
        alternate.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            self.preview(packs_dir=str(alternate))
        alternate.unlink()
        alternate.mkdir()
        (alternate / "basepack_ios").symlink_to(outside / "basepack_ios")
        self.assertTrue(self.preview(packs_dir=str(alternate))["missing"])

    def test_same_origin_http_returns_only_public_match_fields(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with patch.object(platform, "game_models_dir", return_value=self.cache):
            self.edited_bundle_from_receipt()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            origin = "http://127.0.0.1:" + str(server.server_port)
            url = origin + "/api/costume-platform/match?lang=ko"
            body = self.requests()
            def request(payload, source=origin):
                return Request(url, data=json.dumps(payload).encode(),
                               headers={"Origin": source, "Content-Type": "application/json"})
            with urlopen(request(body)) as response:
                result = json.load(response)
            self.assertEqual(result, self.preview())
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request(body, "https://another.example"))
            self.assertEqual(rejected.exception.code, 403)
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request({**body, "path": "/etc/passwd"}))
            self.assertEqual(rejected.exception.code, 403)
            self.assertNotIn("/etc/passwd", rejected.exception.read().decode())
