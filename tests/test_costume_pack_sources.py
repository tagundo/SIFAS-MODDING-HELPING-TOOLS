"""Selected cache files derive identity from current receipts and actual bytes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import costume_pack_sources as bindings
from webtools.core import viewer_cache


class CostumePackSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.library = self.root / "library"
        self.environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.current = viewer_cache.game_models_dir(); self.current.mkdir(parents=True)
        self.old = self.library / "extracted/game-models"; self.old.mkdir(parents=True)
        self.record = {"region": "gl", "suit_id": 12, "variant": "primary", "download": False,
                       "owner": 209, "purpose": "transplant", "platform": "ios", "selection_language": "ko"}
        self.validate = patch.object(bindings.game, "validate_selection", side_effect=lambda repo, params, language: copy.deepcopy(self.record))
        self.validate_mock = self.validate.start(); self.addCleanup(self.validate.stop)
        self.platform = patch.object(bindings, "_platform_raw", return_value=9)
        self.platform_mock = self.platform.start(); self.addCleanup(self.platform.stop)

    def receipt(self, root=None, record=None, data=b"native model", name="body.unity", tag="one"):
        root = root or self.current
        root.mkdir(parents=True, exist_ok=True)
        path = root / name; path.write_bytes(data)
        row = {"model": name, "sha256": hashlib.sha256(data).hexdigest(), "source": [{"path": "local source", "size": 3}],
               "selection_record": copy.deepcopy(record or self.record)}
        manifest = root / (".selection-" + tag + ".json"); manifest.write_text(json.dumps(row))
        return path, manifest, row

    def read(self, *paths, **kwargs):
        return bindings.source_bindings(paths, self.root, **kwargs)

    def test_renamed_native_copy_uses_hash_current_selection_and_actual_platform(self):
        original, _, row = self.receipt()
        renamed = self.root / "totally-renamed.unity"; renamed.write_bytes(original.read_bytes())
        with patch.object(bindings, "_local_native_platform", side_effect=AssertionError("native case must not reread source packs")):
            found = self.read(renamed)[str(renamed)]
        self.assertEqual((found["owner"], found["suit_id"], found["variant"], found["platform"]), (209, 12, "primary", "ios"))
        self.assertTrue(found["native_platform_verified"])
        self.assertEqual(found["receipt"]["original_path"], str(original))
        repo, params, language = self.validate_mock.call_args.args
        self.assertEqual(repo, self.root); self.assertEqual(language, "ko")
        self.assertEqual(params, {"region": "gl", "suit": "suit:12", "variant": "primary", "download": False, "purpose": "transplant", "platform": "ios"})
        self.assertEqual(found["sha256"], row["sha256"])

    def test_legacy_and_native_transplant_subdirectory_receipts_are_read_only(self):
        for root in (self.current / "transplant-bodies", self.old, self.old / "transplant-bodies"):
            with self.subTest(root=root):
                path, _, _ = self.receipt(root, tag="legacy")
                before = {str(p): p.read_bytes() for p in self.library.rglob("*") if p.is_file()}
                self.assertEqual(self.read(path, cache_roots=[root])[str(path)]["suit_id"], 12)
                self.assertEqual(before, {str(p): p.read_bytes() for p in self.library.rglob("*") if p.is_file()})

    def test_explicit_ios_viewer_receipt_replays_its_catalog_and_platform(self):
        self.record["purpose"] = "viewer"
        path, _, _ = self.receipt()
        found = self.read(path)[str(path)]
        _, selection, language = self.validate_mock.call_args.args
        self.assertEqual((selection["purpose"], selection["platform"], language), ("viewer", "ios", "ko"))
        self.assertEqual((found["platform"], found["native_platform_verified"]), ("ios", True))

    def test_explicit_and_legacy_android_receipts_agree_on_identical_catalog_bytes(self):
        self.record.update(purpose="viewer", platform="android")
        self.platform_mock.return_value = 13
        path, _, _ = self.receipt(tag="new")
        legacy = {key: value for key, value in self.record.items()
                  if key not in ("purpose", "platform", "selection_language")}
        self.receipt(self.old, record=legacy, tag="old")
        self.validate_mock.side_effect = lambda repo, params, lang: self.record if "purpose" in params else legacy
        found = self.read(path)[str(path)]
        self.assertEqual(found["platform"], "android")
        self.assertEqual(found["receipt"]["record"]["purpose"], "viewer")

    def test_changed_selected_cache_and_stale_current_catalog_are_clear_errors(self):
        path, _, _ = self.receipt(); path.write_bytes(b"edited without source receipt")
        with self.assertRaisesRegex(ValueError, "changed after its source receipt"):
            self.read(path)
        path.write_bytes(b"native model")
        self.validate_mock.side_effect = lambda *args: {**self.record, "suit_id": 13}
        with self.assertRaisesRegex(ValueError, "stale|catalog"):
            self.read(path)

    def test_conflicting_matching_hash_receipts_are_not_paired(self):
        path, _, _ = self.receipt()
        other = {**self.record, "variant": "unmasked"}
        self.receipt(record=other, name="other.unity", tag="two")
        self.validate_mock.side_effect = lambda repo, params, language: {**self.record, "variant": params["variant"]}
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.read(path)

    def test_no_target_never_gets_a_default_native_platform(self):
        path, _, _ = self.receipt()
        self.platform_mock.return_value = -2
        with patch.object(bindings, "_local_native_platform", return_value=None) as local:
            found = self.read(path)[str(path)]
        self.assertEqual(found["platform"], "ios")
        self.assertFalse(found["native_platform_verified"])
        local.assert_called_once()
        with patch.object(bindings, "_local_native_platform", return_value="ios"):
            self.assertTrue(self.read(path)[str(path)]["native_platform_verified"])
        with patch.object(bindings, "_local_native_platform", return_value="android"):
            with self.assertRaisesRegex(ValueError, "source bytes disagree"):
                self.read(path)

    def test_changed_known_local_source_signature_is_rejected_without_payload_read(self):
        path, manifest, row = self.receipt()
        source = self.root / "pack"; source.write_bytes(b"old pack")
        stat = source.stat()
        row["source"] = [{"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "pack_offset": 0}]
        manifest.write_text(json.dumps(row))
        self.assertIn(str(path), self.read(path))
        source.write_bytes(b"changed pack")
        with self.assertRaisesRegex(ValueError, "source pack no longer matches"):
            self.read(path)

    def test_native_platform_must_match_exact_record(self):
        path, _, _ = self.receipt(); self.platform_mock.return_value = 13
        with self.assertRaisesRegex(ValueError, "native Unity platform disagrees"):
            self.read(path)

    def test_untrusted_roots_and_links_are_not_identity_authority(self):
        other = self.root / "user/game-models"; other.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "managed viewer"):
            self.read(cache_roots=[other])
        self.current.rmdir(); self.current.symlink_to(other, target_is_directory=True)
        self.assertEqual(self.read(cache_roots=[self.current]), {})

    def test_selection_and_receipt_scan_bounds(self):
        path, _, _ = self.receipt()
        self.assertEqual(len(self.read(*([path] * 512))), 1)
        with self.assertRaisesRegex(ValueError, "512"):
            self.read(*([path] * 513))
        # Unrelated entries are enumerated with a finite cap; only 256 JSON
        # receipts can be inspected across all four managed roots.
        calls = []
        original = bindings._origin
        def observed(*args):
            calls.append(args[2]); return original(*args)
        for index in range(300):
            (self.current / (".selection-extra-%03d.json" % index)).write_text("{}")
        with patch.object(bindings, "_origin", side_effect=observed):
            self.read(path)
        self.assertLessEqual(len(calls), bindings.MAX_RECEIPTS)

    def test_matching_preserved_receipt_must_bind_its_path_fingerprint(self):
        path = self.root / "saved-original.unity"; path.write_bytes(b"native model")
        row = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "record": self.record}
        (self.old / ".provenance-wrong.json").write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, "invalid source provenance"):
            self.read(path)

    def test_actual_tiny_unity_platform_is_read_from_serialized_bytes(self):
        self.platform.stop()
        import UnityPy
        raw = (Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes()
        for code in (9, 13, -2):
            env = UnityPy.load(raw)
            for asset in env.assets:
                asset.target_platform = code; asset._m_target_platform = code
            self.assertEqual(bindings._platform_raw(env.file.save(), "renamed.unity"), code)


if __name__ == "__main__":
    unittest.main()
