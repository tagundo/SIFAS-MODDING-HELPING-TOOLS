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
        self.store.max_entries = 3
        keys = [self.store.key("audio", index) for index in range(5)]
        for index, key in enumerate(keys):
            self.assertTrue(self.store.put(key, {"index": index}))
            os.utime(self.store.directory / (key + ".receipt"), ns=(index * 10 ** 9, index * 10 ** 9))
        self.store._evict()
        self.assertEqual(sorted(path.stem for path in self.store.directory.glob("*.receipt")), sorted(keys[2:]))
        self.store.max_entries, self.store.max_bytes = 100, 1
        self.store._evict()
        self.assertEqual(list(self.store.directory.glob("*.receipt")), [], "the byte bound applies too")

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

    def test_code_is_read_through_the_import_system_also_from_a_zip(self):
        """An edit is a new recipe whether the code is files or packed (the APK ships it packed)."""
        import subprocess
        import zipfile
        repository = Path(cache.__file__).resolve().parents[2]
        sources = sorted(path for path in (repository / "webtools").rglob("*.py") if "__pycache__" not in path.parts)
        recipes = {}
        for variant, edit in (("a", b""), ("b", b"\n# an edit\n")):
            for layout in ("zip", "folder"):
                target = self.root / f"{variant}-{layout}"
                if layout == "zip":
                    target = target.with_suffix(".zip")
                    with zipfile.ZipFile(target, "w") as archive:
                        for path in sources:
                            data = path.read_bytes() + (edit if path.name == "mv_studio_timeline.py" else b"")
                            archive.writestr(path.relative_to(repository).as_posix(), data)
                else:
                    for path in sources:
                        copy = target / path.relative_to(repository)
                        copy.parent.mkdir(parents=True, exist_ok=True)
                        copy.write_bytes(path.read_bytes() + (edit if path.name == "mv_studio_timeline.py" else b""))
                script = ("import sys; sys.path.insert(0, sys.argv[1]); "
                          "from webtools.core import mv_studio_import_cache as c; "
                          "assert c.__file__.startswith(sys.argv[1]), c.__file__; print(c._source_recipe())")
                result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(target)], capture_output=True,
                                        text=True, timeout=120, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                recipes[variant, layout] = result.stdout.strip()
        self.assertNotIn("None", recipes.values())
        for layout in ("zip", "folder"):
            self.assertNotEqual(recipes["a", layout], recipes["b", layout], layout)

    def test_unreadable_code_keeps_every_store_closed(self):
        readable = cache._module_bytes

        def unreadable(spec):
            return None if spec is not None and spec.name == "webtools.core.decode" else readable(spec)

        cache._source_recipe.cache_clear()
        self.addCleanup(cache._source_recipe.cache_clear)
        private = self.root / "private"
        private.mkdir(mode=0o700)
        with patch.object(cache, "_module_bytes", side_effect=unreadable), \
                patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": str(private.resolve())}):
            self.assertIsNone(cache._source_recipe())
            self.assertIsNone(cache.recipe())
            self.assertIsNone(cache.open_cache(self.media))
            self.assertIsNone(cache.open_texture_cache(self.media))
            self.assertIsNone(mv_studio_actor_cache.open_cache(("gl", "android"), self.media))
            with self.assertRaises(ValueError):
                cache.ImportCache(self.root / "receipts", self.media)
        cache._source_recipe.cache_clear()
        with patch.dict(os.environ, {"ELICHIKA_MV_PRIVATE_CACHE": str(private.resolve())}):
            self.assertIsNotNone(cache.open_cache(self.media))
            self.assertIsNotNone(mv_studio_actor_cache.open_cache(("gl", "android"), self.media))

    def test_recipe_holds_the_format_and_library_releases(self):
        cache._source_recipe.cache_clear()
        self.addCleanup(cache._source_recipe.cache_clear)
        first = cache._source_recipe()
        cache._source_recipe.cache_clear()
        with patch.object(cache, "RECEIPT_FORMAT", cache.RECEIPT_FORMAT + 1):
            self.assertNotEqual(cache._source_recipe(), first)
        library = cache._library("PIL")
        self.assertEqual(library[0], "PIL")
        self.assertIsInstance(library[1], str, "the Pillow release")
        cache._source_recipe.cache_clear()
        with patch.object(cache, "_library", side_effect=lambda name: [name, "0.0", None, None]):
            self.assertNotEqual(cache._source_recipe(), first)

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


def _script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o700)
    return path


@unittest.skipIf(os.name == "nt", "the fake decoders are shell scripts")
class TransientFailureTests(unittest.TestCase):
    """A result shaped by a failure that may not repeat (a killed decoder, a deadline) is used but never kept."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "receipts").mkdir(mode=0o700)
        patcher = patch.object(mv_studio, "_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(mv_studio._STAGE_PREVIEWS.clear)
        self.flag = self.root / "low-memory"
        # Like the Android low-memory killer: the decoder child dies with SIGKILL while the flag exists.
        self.texture65 = _script(self.root / "texture65", f'if [ -e "{self.flag}" ]; then kill -9 $$; fi\n'
                                 'head -c $(( $1 * $2 * 4 )) /dev/zero > "$4"\n')

    def store(self):
        """A store as a fresh process opens it."""
        return cache.ImportCache(self.root / "receipts", mv_studio.media)

    @staticmethod
    def crunched():
        from types import SimpleNamespace
        texture = SimpleNamespace(m_Width=4, m_Height=4, m_TextureFormat=65, m_ImageCount=1, m_TextureDimension=2,
                                  image_data=b"crunched", m_StreamData=None, object_reader=None)
        texture.get_image_data = lambda: texture.image_data
        return texture

    def parse(self, raw, name, **flags):
        """A timeline parse that, like the particle importer, shows a texture it cannot decode as unavailable."""
        import time
        from webtools.core import decode, mv_studio_stage_title as title
        try:
            with decode._android_image(self.crunched(), time.monotonic() + 10, stage=True):
                coverage = "rendered"
        except title._UNSUPPORTED as error:
            coverage = f"not rendered: texture is unavailable ({error})"
        return {"duration": 1.0, "tracks": [{"id": "t", "events": [], "coverage": coverage}]}

    def test_a_decoder_killed_once_does_not_outlive_a_restart(self):
        timeline = self.root / "game-1.unity"
        timeline.write_bytes(b"timeline")
        coverage = lambda parsed: parsed["tracks"][0]["coverage"]
        with (patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": str(self.texture65)}),
              patch("webtools.core.mv_studio_timeline.parse_timeline", side_effect=self.parse) as parse):
            self.flag.touch()
            reused = []
            _, degraded = mv_studio._timeline(timeline, store=self.store(), reused=reused)
            self.assertIn("code -9", coverage(degraded))
            self.assertEqual(list((self.root / "receipts").glob("*.receipt")), [], "a degraded parse is never kept")
            self.flag.unlink()
            # After a restart the parse runs again and heals; the clean parse is then kept and reused.
            _, healed = mv_studio._timeline(timeline, store=self.store(), reused=reused)
            _, again = mv_studio._timeline(timeline, store=self.store(), reused=reused)
            self.assertEqual((coverage(healed), coverage(again)), ("rendered", "rendered"))
            self.assertEqual((parse.call_count, reused), (2, [False, False, True]))

    def test_machine_failures_of_the_decoders_are_noted_and_data_errors_are_not(self):
        import subprocess
        import time
        from types import SimpleNamespace
        from webtools.core import decode, transient_failures
        astc = SimpleNamespace(m_Width=4, m_Height=4, m_TextureFormat=48, m_ImageCount=1, m_TextureDimension=2,
                               image_data=b"\0" * 16, m_StreamData=None, object_reader=None)  # ASTC_RGB_4x4
        astc.get_image_data = lambda: astc.image_data
        unsupported = SimpleNamespace(**{**vars(astc), "m_TextureFormat": 10})  # DXT1
        unsupported.get_image_data = lambda: b""
        failing = _script(self.root / "astcenc", "exit 3\n")
        not_executable = self.root / "astcenc-plain"
        not_executable.write_bytes(b"not a program")
        cases = [("ASTCENC_BIN", failing, astc, subprocess.CalledProcessError),
                 ("ASTCENC_BIN", not_executable, astc, OSError),
                 ("ELICHIKA_TEXTURE65_BIN", self.texture65, self.crunched(), ValueError)]
        self.flag.touch()
        for variable, binary, texture, error in cases:
            with self.subTest(binary=binary.name), patch.dict(os.environ, {variable: str(binary)}):
                watch = transient_failures.Watch()
                with self.assertRaises(error):
                    decode._android_image(texture, time.monotonic() + 10)
                self.assertFalse(watch.clean)
        # A format no decoder handles fails the same way every time.
        watch = transient_failures.Watch()
        with self.assertRaises(ValueError):
            decode._android_image(unsupported, time.monotonic() + 10)
        self.assertTrue(watch.clean)
        # So does a run out of time.
        with self.assertRaises(TimeoutError):
            decode._android_image(astc, time.monotonic() - 1)
        self.assertFalse(watch.clean)

    def test_stage_and_clip_receipts_skip_conversions_with_noted_failures(self):
        from webtools.core import transient_failures
        stage = self.root / "import-a" / "game-2.unity"
        stage.parent.mkdir()
        stage.write_bytes(b"Native stage")
        glb = model_viewer._Glb().finish()
        failures = [True]

        def prepare(*args, **kwargs):
            if failures[0]:
                transient_failures.note()  # e.g. a reflection cubemap whose decoder timed out
            return {"id": "s", "warnings": []}

        with (patch.object(model_viewer, "prepare", side_effect=prepare) as converted,
              patch.object(model_viewer, "get_model", return_value=glb)):
            for _ in range(2):
                mv_studio._preview(stage, reuse=True, store=self.store())
            self.assertEqual(converted.call_count, 2, "neither the receipt nor the in-memory cache kept it")
            failures[0] = False
            for _ in range(2):
                mv_studio._preview(stage, reuse=True, store=self.store())
                mv_studio._STAGE_PREVIEWS.clear()
            self.assertEqual(converted.call_count, 3)
        project = {"tracks": [{"id": "t", "label": "Dance", "events": [
            {"id": "e", "label": "clip", "values": {"playableClass": "AnimationPlayableAsset", "animation": "cab-1:5"}}]}],
            "warnings": []}
        result = {"clips": {}, "warnings": ["no loaded dependency provides cab-1"]}

        def resolve(*args):
            transient_failures.note()  # a pack that failed to load for want of memory
            return result

        with patch.object(mv_studio_external_clips, "resolve", side_effect=resolve) as clips:
            for _ in range(2):
                mv_studio_external_clips.apply(json.loads(json.dumps(project)), b"timeline", [{"asset": "dance"}],
                                               mv_studio_external_clips.SharedReads(lambda descriptor: b"pack"), None,
                                               cache=self.store())
            self.assertEqual(clips.call_count, 2)


class TextureStoreTests(unittest.TestCase):
    """Decoded PNGs outlive the process only through an import's texture store, under the full source key."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name) / "textures"
        directory.mkdir(mode=0o700)
        self.store = cache.ImportCache(directory, mv_studio.media, max_entries=8, max_bytes=1 << 20)
        model_viewer._TEXTURE_PNGS.clear()
        self.addCleanup(model_viewer._TEXTURE_PNGS.clear)
        model_viewer._REQUEST_STATE.reimport = False

    @staticmethod
    def texture(red=20):
        from types import SimpleNamespace
        data = bytes([red, 40, 60, 255] * 4)
        texture = SimpleNamespace(m_Width=2, m_Height=2, m_TextureFormat=4, m_ImageCount=1, m_TextureDimension=2,
                                  image_data=data, m_StreamData=None, object_reader=None)
        texture.get_image_data = lambda: texture.image_data
        return texture

    def test_png_is_reused_after_a_restart_only_inside_an_import(self):
        import time
        with patch.object(model_viewer.decode, "_android_image", wraps=model_viewer.decode._android_image) as decode:
            with model_viewer.texture_store(self.store):
                first = model_viewer._texture_png(self.texture(), time.monotonic() + 10)
            model_viewer._TEXTURE_PNGS.clear()  # a restart
            with model_viewer.texture_store(self.store):
                self.assertEqual(model_viewer._texture_png(self.texture(), time.monotonic() + 10), first)
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(len(list(self.store.directory.glob("*.receipt"))), 1)
            # Other pixels are another key.
            model_viewer._TEXTURE_PNGS.clear()
            with model_viewer.texture_store(self.store):
                self.assertNotEqual(model_viewer._texture_png(self.texture(red=21), time.monotonic() + 10), first)
            self.assertEqual(decode.call_count, 2)
            # Outside an import (other tools) nothing is read from or written to the store.
            model_viewer._TEXTURE_PNGS.clear()
            model_viewer._texture_png(self.texture(red=22), time.monotonic() + 10)
            self.assertEqual(decode.call_count, 3)
            self.assertEqual(len(list(self.store.directory.glob("*.receipt"))), 2)
            # Reimport decodes again and refreshes the receipt.
            model_viewer._TEXTURE_PNGS.clear()
            model_viewer._REQUEST_STATE.reimport = True
            try:
                with model_viewer.texture_store(self.store):
                    self.assertEqual(model_viewer._texture_png(self.texture(), time.monotonic() + 10), first)
            finally:
                model_viewer._REQUEST_STATE.reimport = False
            self.assertEqual(decode.call_count, 4)
        self.assertIsNone(getattr(model_viewer._REQUEST_STATE, "texture_store", None))

    def test_a_corrupt_png_receipt_is_decoded_again(self):
        import time
        with model_viewer.texture_store(self.store):
            first = model_viewer._texture_png(self.texture(), time.monotonic() + 10)
        receipt, = self.store.directory.glob("*.receipt")
        data = receipt.read_bytes()
        receipt.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        model_viewer._TEXTURE_PNGS.clear()
        with patch.object(model_viewer.decode, "_android_image", wraps=model_viewer.decode._android_image) as decode:
            with model_viewer.texture_store(self.store):
                self.assertEqual(model_viewer._texture_png(self.texture(), time.monotonic() + 10), first)
            self.assertEqual(decode.call_count, 1)


if __name__ == "__main__":
    unittest.main()
