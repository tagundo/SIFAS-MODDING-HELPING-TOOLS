"""Durable MV actor source identity, replay, and cache repair."""
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_actor_cache as actor_cache


class ActorCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.private = self.root / "private"
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": str(self.private)}).start()
        self.cache = self.reopen()
        self.assertIsNotNone(self.cache)
        self.model, self.face, self.shader = [self.asset(name) for name in ("model.unity", "face.unity", "shader.unity")]
        self.key = self.identity(self.cache)
        self.glb = b"glTF actor test bytes"
        digest = sha256(self.glb).hexdigest()
        self.name = digest[:32] + ".glb"
        self.media(self.name)[0].write_bytes(self.glb)
        self.motion = {"bodySegments": [{"sourceHash": "native-hash", "sourceName": "dance"}]}
        self.rig = {
            "available": True,
            "clips": [{"sourceHash": "native-hash", "sourceName": "dance", "bindingComplete": True}],
        }

    def asset(self, name):
        path = self.root / name
        path.write_bytes(name.encode())
        return path

    def media(self, name):
        return self.root / name, "model/gltf-binary"

    def reopen(self):
        return actor_cache.open_cache(("gl", "android"), self.media)

    def identity(self, cache, *, companions=None, native=b"timeline"):
        return cache.key(cache.inputs(native, [self.shader]), 1, 210, self.model,
                         [self.face, self.shader] if companions is None else companions, [])

    def put(self, key=None, rig=None):
        self.cache.put(key or self.key, self.name, rig or self.rig, self.motion)

    def test_restart_and_source_or_converter_changes(self):
        self.put()
        replay = self.reopen()
        self.assertEqual(replay.get(self.identity(replay)), (self.name, self.rig, self.motion))
        self.assertNotEqual(self.identity(replay, companions=[self.shader, self.face]), self.key)
        self.assertNotEqual(self.identity(replay, native=b"new timeline"), self.key)
        self.assertIsNone(self.identity(replay, companions=[]))

        self.face.write_bytes(b"changed native face")
        self.assertIsNone(replay.get(self.identity(replay)))
        self.face.write_bytes(self.face.name.encode())
        with patch.object(actor_cache, "_PREVIEW_VERSION", actor_cache._PREVIEW_VERSION + 1):
            updated = self.reopen()
        self.assertNotEqual(self.identity(updated), self.key)
        self.assertIsNone(updated.get(self.key))
        self.assertIsNotNone(replay.get(self.key))

    def test_unreadable_code_keeps_the_version_keyed_cache(self):
        # An importer that cannot hand back module bytes (the APK's packed assets) must not
        # turn the actor cache off: it falls back to the version and library releases.
        from webtools.core import mv_studio_import_cache
        self.put()
        with patch.object(mv_studio_import_cache, "_source_recipe", return_value=None):
            fallback = self.reopen()
            self.assertIsNotNone(fallback)
            self.assertNotEqual(fallback.recipe, self.cache.recipe)
            fallback.put(self.identity(fallback), self.name, self.rig, self.motion)
            again = self.reopen()
            self.assertEqual(again.get(self.identity(again)), (self.name, self.rig, self.motion))
            with patch.object(actor_cache, "_PREVIEW_VERSION", actor_cache._PREVIEW_VERSION + 1):
                self.assertIsNone(self.reopen().get(self.identity(again)))

    def test_rebuilds_after_media_or_receipt_corruption(self):
        self.put()
        media, _ = self.media(self.name)
        media.write_bytes(self.glb[:-1] + bytes([self.glb[-1] ^ 1]))
        self.assertIsNone(self.reopen().get(self.key))
        media.write_bytes(self.glb)
        with sqlite3.connect(self.cache.path) as db:
            db.execute("UPDATE actor_receipts SET receipt = ? WHERE id = ?", (b'{"broken": true}', self.key))
        self.assertIsNone(self.reopen().get(self.key))
        self.put()
        self.assertEqual(self.reopen().get(self.key), (self.name, self.rig, self.motion))

    def test_uses_lru_without_deleting_content_addressed_media(self):
        keys = [self.identity(self.cache, native=name.encode()) for name in ("one", "two", "three")]
        with patch.object(actor_cache, "_MAX_RECEIPTS", 2):
            self.put(keys[0])
            self.put(keys[1])
            self.assertIsNotNone(self.reopen().get(keys[0]))
            self.put(keys[2])
        self.assertIsNotNone(self.cache.get(keys[0]))
        self.assertIsNone(self.cache.get(keys[1]))
        self.assertIsNotNone(self.cache.get(keys[2]))
        self.assertEqual(self.media(self.name)[0].read_bytes(), self.glb)

    def test_retries_incomplete_ambiguous_or_failed_animation(self):
        clip = self.rig["clips"][0]
        for rig in (
            {"available": True, "clips": [dict(clip, bindingComplete=False)]},
            {"available": True, "clips": [clip, clip]},
            dict(self.rig, animationWarnings=[{"code": "animation_unavailable"}]),
        ):
            with self.subTest(rig=rig):
                self.put(rig=rig)
                self.assertIsNone(self.cache.get(self.key))

    def test_unavailable_private_path_disables_cache(self):
        with patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": ""}):
            self.assertIsNone(self.reopen())
        with patch.object(actor_cache.os, "geteuid", None, create=True):
            self.assertIsNone(self.reopen())
        link = self.root / "linked"
        link.symlink_to(self.private, target_is_directory=True)
        with patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": str(link)}):
            self.assertIsNone(self.reopen())
        self.cache.directory.chmod(0o755)
        self.assertIsNone(self.reopen())

    def test_unreadable_database_only_disables_cache(self):
        self.put()
        self.cache.path.write_bytes(b"previous receipts lost")
        self.assertIsNone(self.reopen())
        self.assertIsNone(self.cache.get(self.key))
        self.put()
        self.assertEqual(self.media(self.name)[0].read_bytes(), self.glb)
