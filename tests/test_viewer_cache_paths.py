"""Derived caches stay outside source extraction and remain read-only legacy inputs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from webtools.core import game_models, game_motions, game_motion_audio, model_animation
from webtools.core import sukusta, viewer_cache, viewer_mod_flow
from webtools.tools.texture import iter_bundle_files


class ViewerCachePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.extracted = self.library / "extracted"
        self.extracted.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        self.environment.start(); self.addCleanup(self.environment.stop)

    def bundle(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"UnityFS\0synthetic cache/source fixture")
        return path

    def snapshot(self):
        return {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_new_locations_and_exact_legacy_boundaries(self):
        self.assertEqual(viewer_cache.game_models_dir(), self.library / "cache/viewer/game-models")
        self.assertEqual(viewer_cache.game_motions_dir(), self.library / "cache/viewer/game-motions")
        self.assertFalse(viewer_cache.viewer_cache_root().exists())
        for kind in ("game-models", "game-motions"):
            self.assertTrue(viewer_cache.is_legacy_viewer_cache_path(self.extracted / kind / "body.unity"))
            self.assertFalse(viewer_cache.is_legacy_viewer_cache_path(self.extracted / "user" / kind / "body.unity"))
            self.assertFalse(viewer_cache.is_legacy_viewer_cache_path(self.root / kind / "body.unity"))

    def test_broad_bundle_scan_ignores_only_generated_descendants_and_explicit_selection_works(self):
        real = self.bundle("library/extracted/3d_model/source.bundle")
        user_same_name = self.bundle("library/extracted/user/game-models/owned.bundle")
        old_model = self.bundle("library/extracted/game-models/cache.bundle")
        old_motion = self.bundle("library/extracted/game-motions/cache.bundle")
        other = self.bundle("other/game-models/user.bundle")
        before = self.snapshot()
        self.assertEqual(set(sukusta.find_bundles(self.extracted)), {real, user_same_name})
        self.assertEqual(sukusta.find_bundles(old_model), [old_model])
        self.assertEqual(sukusta.find_bundles(old_model.parent), [old_model])
        self.assertEqual(sukusta.find_bundles(old_motion.parent), [old_motion])
        self.assertEqual(sukusta.find_bundles(other.parent), [other])
        self.assertEqual(self.snapshot(), before)

    def test_texture_recursive_scan_obeys_same_exact_boundary(self):
        real = self.bundle("library/extracted/user/source.bundle")
        named = self.bundle("library/extracted/user/game-motions/owned.bundle")
        old = self.bundle("library/extracted/game-models/cache.bundle")
        self.assertEqual(set(iter_bundle_files(str(self.extracted), True)), {str(real), str(named)})
        self.assertEqual(list(iter_bundle_files(str(old), True)), [str(old)])
        self.assertEqual(list(iter_bundle_files(str(old.parent), True)), [str(old)])

    def test_automatic_animation_scan_ignores_legacy_but_explicit_motion_is_valid(self):
        model = self.bundle("library/extracted/body/model.bundle")
        old = self.bundle("library/extracted/game-motions/ch0101_animation.bundle")
        selected_user = self.bundle("library/extracted/user/game-models/ch0101_animation.bundle")
        inspect = lambda path, deadline: ({101}, 1)
        context = {"library_roots": [str(self.extracted)]}
        with patch.object(model_animation, "_animation_source", side_effect=inspect):
            self.assertEqual(model_animation.discover_animation_paths([str(model)], context, 101, time.monotonic() + 3), [str(selected_user)])
            context["animation_paths"] = [str(old)]
            self.assertEqual(model_animation.discover_animation_paths([str(model)], context, 101, time.monotonic() + 3), [str(old)])

    def model_receipt(self):
        old = self.bundle("library/extracted/game-models/one/primary.unity")
        root = old.parent.parent
        record = {"owner": 209, "suit_id": 2090001, "platform": "android", "region": "gl", "variant": "primary", "download": False}
        signatures = [{"path": str(self.root / "packs/source"), "size": 123, "mtime_ns": 10, "pack_offset": 0}]
        digest = hashlib.sha256(old.read_bytes()).hexdigest()
        receipt = {"model": str(old.relative_to(root)), "sha256": digest, "source": signatures, "selection_record": record}
        (root / ".selection-test.json").write_text(json.dumps(receipt))
        return old, record, signatures, receipt

    def test_valid_legacy_model_receipt_is_read_only_and_invalid_bytes_or_selection_are_not_reused(self):
        old, record, signatures, receipt = self.model_receipt()
        before = self.snapshot()
        cached, root = game_models._cached_model(viewer_cache.game_models_dir(), "test", signatures, record)
        self.assertEqual(cached, old)
        self.assertEqual(root, self.extracted / "game-models")
        self.assertEqual(self.snapshot(), before)
        wrong = {**record, "suit_id": record["suit_id"] + 1}
        self.assertEqual(game_models._cached_model(viewer_cache.game_models_dir(), "test", signatures, wrong), (None, None))
        old.write_bytes(old.read_bytes() + b"changed")
        self.assertEqual(game_models._cached_model(viewer_cache.game_models_dir(), "test", signatures, record), (None, None))

    def test_legacy_native_transplant_subdirectory_is_a_verified_read_only_fallback(self):
        old, record, signatures, receipt = self.model_receipt()
        root = self.extracted / "game-models/transplant-bodies"; root.mkdir()
        moved = root / "native.unity"; moved.write_bytes(old.read_bytes())
        receipt["model"] = moved.name
        (root / ".selection-test.json").write_text(json.dumps(receipt))
        new = viewer_cache.game_models_dir() / "transplant-bodies"
        before = self.snapshot()
        self.assertEqual(viewer_cache.legacy_cache_roots(new, "models"), (root,))
        self.assertEqual(game_models._cached_model(new, "test", signatures, record), (moved, root))
        context = {"containers": [{"path": str(moved), "sha256": receipt["sha256"]}]}
        self.assertEqual(viewer_mod_flow.cached_receipts(context, viewer_cache.game_models_dir()),
                         [{"path": str(moved), "sha256": receipt["sha256"], "record": record}])
        self.assertEqual(before, self.snapshot())

    def test_legacy_receipts_match_selected_hash_and_share_bounded_new_old_scan(self):
        old, record, signatures, receipt = self.model_receipt()
        new = viewer_cache.game_models_dir(); new.mkdir(parents=True)
        for index in range(260):
            (new / f".selection-unused-{index}.json").write_text("{}")
        context = {"containers": [{"path": str(old), "sha256": receipt["sha256"]}]}
        before = self.snapshot()
        self.assertEqual(viewer_mod_flow.cached_receipts(context, new), [{"path": str(old), "sha256": receipt["sha256"], "record": record}])
        context["containers"][0]["sha256"] = "0" * 64
        self.assertEqual(viewer_mod_flow.cached_receipts(context, new), [])
        self.assertEqual(self.snapshot(), before)

    def test_legacy_motion_requires_selection_and_all_output_hashes(self):
        root = self.extracted / "game-motions"; root.mkdir()
        path = root / "motion/clip.unity"; path.parent.mkdir(); path.write_bytes(b"clip")
        signatures = [{"path": "source", "size": 4}]
        record = {"category": "home", "motion": "idle:1", "target_character": 101}
        descriptor = {"category": "home", "motion": "idle:1", "targetCharacter": 101, "performer": None, "performerPosition": 1}
        row = {"version": 2, "sources": signatures, "files": [{"name": str(path.relative_to(root)), "sha256": game_models._sha(path)}], "motion": descriptor, "timelines": []}
        (root / ".motion-test.json").write_text(json.dumps(row))
        before = self.snapshot()
        roots = viewer_cache.legacy_cache_roots(viewer_cache.game_motions_dir(), "motions")
        self.assertEqual(roots, (root,))
        self.assertEqual(game_motions._cached(root, "test", signatures, record)["paths"], [path])
        self.assertIsNone(game_motions._cached(root, "test", signatures, {**record, "motion": "other"}))
        self.assertEqual(self.snapshot(), before)
        path.write_bytes(b"bad")
        self.assertIsNone(game_motions._cached(root, "test", signatures, record))

    def test_legacy_audio_requires_wav_sha_and_source_signatures(self):
        root = self.extracted / "game-motions/audio"; root.mkdir(parents=True)
        path = root / ("a" * 64 + ".wav")
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(bytes(32))
        signatures = [{"path": "acb", "size": 5}]
        (root / ".audio-selection-test.json").write_text(json.dumps({"sources": signatures, "name": path.name, "sha256": game_models._sha(path)}))
        before = self.snapshot()
        self.assertEqual(viewer_cache.legacy_cache_roots(viewer_cache.game_motions_dir() / "audio", "audio"), (root,))
        self.assertEqual(game_motion_audio._decoded_cache(root, "test", signatures), path)
        self.assertIsNone(game_motion_audio._decoded_cache(root, "test", [{"path": "changed"}]))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
