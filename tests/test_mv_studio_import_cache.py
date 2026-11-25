"""Restart-safe import receipts: exact payloads, keys that cover code, decoders and inputs, and verification."""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import model_viewer, mv_studio, mv_studio_actor_cache, mv_studio_external_clips, mv_studio_import_cache as cache


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "receipts").mkdir(mode=0o700)
        (self.root / "media").mkdir()
        self.store = cache.ImportCache(self.root / "receipts", self.media)

    def media(self, name):
        path = self.root / "media" / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path, "model/gltf-binary"

    def publish(self, data, extension="glb"):
        name = sha256(data).hexdigest()[:32] + "." + extension
        (self.root / "media" / name).write_bytes(data)
        return "/api/mv-studio/media/" + name

    def test_payload_comes_back_with_the_same_types_and_key_order(self):
        payload = {"z": 1, "a": [1.0, -0.0, 5e-324, True, None, "텍스트"], "curves": [("cubic", [(0.0, (1.5, 2, 3, 4))])],
                   "nested": {"b": ("x",), "a": []}}
        key = self.store.key("timeline", "abc", "game-1.unity")
        self.assertTrue(self.store.put(key, payload))
        found = self.store.get(key)
        self.assertTrue(cache._same(found, payload))
        self.assertEqual(list(found), ["z", "a", "curves", "nested"])
        self.assertIs(type(found["curves"][0]), tuple)
        self.assertIs(type(found["a"][0]), float)
        self.assertEqual(json.dumps(found), json.dumps(payload))

    def test_values_that_cannot_round_trip_exactly_are_not_stored(self):
        key = self.store.key("timeline", "abc", "x")
        for payload in ({"x": float("nan")}, {"x": float("inf")}, {1: "int key"}, {"x": {1, 2}},
                        {"x": {cache._TUPLE: [1]}}, {"x": b"bytes"}):
            with self.subTest(payload=repr(payload)):
                self.assertFalse(self.store.put(key, payload))
                self.assertIsNone(self.store.get(key))

    def test_inputs_options_code_and_decoders_are_all_part_of_the_key(self):
        base = self.store.key("preview", "root", [["game-2.unity", "a" * 64]], [], [], False)
        self.assertNotEqual(base, self.store.key("preview", "root", [["game-2.unity", "b" * 64]], [], [], False))
        self.assertNotEqual(base, self.store.key("preview", "root", [["game-2.unity", "a" * 64]], [], [], True))
        self.assertNotEqual(base, self.store.key("preview", "root", [["game-2.unity", "a" * 64]], [], ["/stage/a"], False))
        self.assertNotEqual(base, self.store.key("audio", "root", [["game-2.unity", "a" * 64]], [], [], False))
        self.assertTrue(self.store.put(base, {"name": "x"}))
        # Other code (an edited file or an app update) never reads this receipt.
        with patch.object(cache, "_source_recipe", return_value="other code"):
            other = cache.ImportCache(self.store.directory, self.media)
        self.assertNotEqual(other.recipe, self.store.recipe)
        self.assertIsNone(other.get(other.key("preview", "root", [["game-2.unity", "a" * 64]], [], [], False)))
        self.assertIsNone(other.get(base), "the stored recipe must match too")
        # Nor does another decoder build.
        decoder = self.root / "astcenc"
        decoder.write_bytes(b"decoder v1")
        with patch.dict(os.environ, {"ASTCENC_BIN": str(decoder)}):
            first = cache.recipe()
            decoder.write_bytes(b"decoder v2 with a different size")
            self.assertNotEqual(cache.recipe(), first)
        self.assertEqual(self.store.get(base), {"name": "x"})

    def test_tampered_receipts_and_changed_media_are_misses(self):
        url = self.publish(b"glTF" + b"\0" * 16)
        key = self.store.key("preview", "media")
        self.assertTrue(self.store.put(key, {"url": url}))
        self.assertEqual(self.store.get(key), {"url": url})
        media_path = self.root / "media" / url.rsplit("/", 1)[1]
        media_path.write_bytes(b"glTF" + b"\1" * 16)
        self.assertIsNone(self.store.get(key), "the media must still hold its exact bytes")
        media_path.unlink()
        self.assertIsNone(self.store.get(key))
        self.assertFalse(self.store.put(key, {"url": url}), "receipts only name media that exist")

        self.assertTrue(self.store.put(key, {"value": 1}))
        path = self.store.directory / (key + ".receipt")
        head, _, body = path.read_bytes().partition(b"\n")
        path.write_bytes(head + b"\n" + body[:-1] + bytes([body[-1] ^ 1]))
        self.assertIsNone(self.store.get(key))
        forged = json.loads(head)
        forged["key"] = "0" * 64
        path.write_bytes(json.dumps(forged).encode() + b"\n" + body)
        self.assertIsNone(self.store.get(key))
        self.assertIsNone(self.store.get("../" + key))

    def test_the_store_is_bounded(self):
        with patch.object(cache, "_MAX_ENTRIES", 3):
            keys = [self.store.key("audio", index) for index in range(5)]
            for index, key in enumerate(keys):
                self.assertTrue(self.store.put(key, {"index": index}))
                os.utime(self.store.directory / (key + ".receipt"), ns=(index * 10 ** 9, index * 10 ** 9))
            self.store._evict()
        self.assertEqual(sorted(path.stem for path in self.store.directory.glob("*.receipt")), sorted(keys[2:]))

    def test_store_needs_a_private_folder(self):
        private = self.root / "private"
        with patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": str(private)}):
            store = cache.open_cache(self.media)
            self.assertIsNotNone(store)
            self.assertEqual(stat.S_IMODE((private / "imports").stat().st_mode) & 0o077, 0)
            os.chmod(private / "imports", 0o755)
            self.assertIsNone(cache.open_cache(self.media))
        with patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": "relative/path"}):
            self.assertIsNone(cache.open_cache(self.media))
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(cache.open_cache(self.media))

    def test_actor_cache_recipe_does_not_depend_on_what_is_imported(self):
        directory = self.root / "actors"
        directory.mkdir(mode=0o700)
        first = mv_studio_actor_cache.ActorCache(directory, ("gl", "android"), self.media).recipe
        hidden = {name: None for name in ("UnityPy", "numpy", "PIL")}
        with patch.dict(sys.modules, hidden):
            second = mv_studio_actor_cache.ActorCache(directory, ("gl", "android"), self.media).recipe
        self.assertEqual(first, second)


class ImportStepReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "receipts").mkdir(mode=0o700)
        self.store = cache.ImportCache(self.root / "receipts", mv_studio.media)
        patcher = patch.object(mv_studio, "_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(mv_studio._STAGE_PREVIEWS.clear)

    def test_timeline_parse_is_reused_only_for_the_same_bytes(self):
        timeline = self.root / "game-1.unity"
        timeline.write_bytes(b"timeline v1")
        parsed = {"duration": 3.0, "tracks": [{"id": "t", "events": [], "curve": ("cubic", [(0.0, (1.0, 2.0, 3.0, 4.0))])}]}
        with patch("webtools.core.mv_studio_timeline.parse_timeline", return_value=parsed) as parse:
            reused = []
            self.assertEqual(mv_studio._timeline(timeline, store=self.store, reused=reused), (b"timeline v1", parsed))
            raw, again = mv_studio._timeline(timeline, store=self.store, reused=reused)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(reused, [False, True])
            self.assertTrue(cache._same(again, parsed))
            self.assertIsNot(again, parsed, "every import gets its own copy to edit")
            timeline.write_bytes(b"timeline v2")
            mv_studio._timeline(timeline, store=self.store)
            self.assertEqual(parse.call_count, 2)

    def test_stage_receipts_repeat_structural_warnings_and_skip_transient_ones(self):
        stage = self.root / "import-a" / "game-2.unity"
        stage.parent.mkdir()
        stage.write_bytes(b"Native stage effect")
        glb = model_viewer._Glb().finish()
        structural = [{"code": "linked_mesh_missing", "name": "fx", "message": "A linked mesh is missing."}]
        with (patch.object(model_viewer, "prepare", return_value={"id": "s", "warnings": structural}) as prepare,
              patch.object(model_viewer, "get_model", return_value=glb)):
            first, received = [], []
            output = mv_studio._preview(stage, reuse=True, stage_bindings=["/a"], native_stage_effect=True,
                                        warnings=first, store=self.store)
            mv_studio._STAGE_PREVIEWS.clear()  # a restart
            reused = []
            again = mv_studio._preview(stage, reuse=True, stage_bindings=["/a"], native_stage_effect=True,
                                       warnings=received, reused=reused, store=self.store)
            self.assertEqual((again, received, reused), (output, structural, [True]))
            self.assertEqual(prepare.call_count, 1)
            # Different bindings are a different conversion.
            mv_studio._preview(stage, reuse=True, stage_bindings=["/b"], native_stage_effect=True, store=self.store)
            self.assertEqual(prepare.call_count, 2)
            # A texture that failed to decode may succeed next time: never kept.
            prepare.return_value = {"id": "s", "warnings": [{"code": "texture_unavailable", "name": "x", "message": "m"}]}
            stage.write_bytes(b"Another stage")
            for _ in range(2):
                mv_studio._preview(stage, reuse=True, store=self.store)
            self.assertEqual(prepare.call_count, 4)

    def test_clip_names_are_reused_only_with_the_same_dependency_bytes(self):
        project = {"tracks": [{"id": "t", "label": "Dance", "events": [
            {"id": "e", "label": "clip", "values": {"playableClass": "AnimationPlayableAsset", "animation": "cab-1:5"}}]}],
            "warnings": []}
        packs = {"dance": b"pack v1"}
        # Every import reads its sections afresh.
        reads = lambda: mv_studio_external_clips.SharedReads(lambda descriptor: packs[descriptor["asset"]])
        result = {"clips": {"e": {"track": "t", "animation": "cab-1:5", "animationName": "ch0212_dance", "dependency": "dance"}},
                  "warnings": []}
        with patch.object(mv_studio_external_clips, "resolve", return_value=result) as resolve:
            for _ in range(2):
                reused = []
                names = mv_studio_external_clips.apply(json.loads(json.dumps(project)), b"timeline", [{"asset": "dance"}],
                                                       reads(), None, cache=self.store, reused=reused)
                self.assertEqual(names, {"e": "ch0212_dance"})
            self.assertEqual((resolve.call_count, reused), (1, [True]))
            packs["dance"] = b"pack v2"
            mv_studio_external_clips.apply(json.loads(json.dumps(project)), b"timeline", [{"asset": "dance"}], reads(), None,
                                           cache=self.store)
            self.assertEqual(resolve.call_count, 2)


if __name__ == "__main__":
    unittest.main()
