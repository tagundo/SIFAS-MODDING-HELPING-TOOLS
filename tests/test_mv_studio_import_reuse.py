"""An MV import reads each bundle and downloads each pack once, with unchanged results.

game_motion_selection.shared_reads() keeps a parsed bundle for every member's dance
selection; write_selected must then leave a shared source exactly as it found it.
mv_studio_game.shared_downloads() keeps a downloaded pack for the import's other
sections of the same pack. Outside these blocks nothing is kept.
"""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import game_motion_selection as selection
from webtools.core import cri_audio_decode, model_viewer, mv_studio, mv_studio_actor_cache, mv_studio_quality
from webtools.core import mv_studio_game as studio


def _environment(names):
    """A stand-in for model_viewer._environment: one file of MonoScript-free objects per read."""
    reads = []

    def read(paths, deadline):
        reads.append(paths[0])
        table = {}
        assets_file = SimpleNamespace(name="CAB-dance", externals=[], objects=table)
        for path_id, name in enumerate(names, 1):
            table[path_id] = SimpleNamespace(assets_file=assets_file, path_id=path_id, type=SimpleNamespace(name="AnimationClip"),
                                             peek_name=lambda name=name: name)
        container = SimpleNamespace(saved=[])
        container.save = lambda packer: container.saved.append(list(table)) or repr(sorted(table)).encode()
        return SimpleNamespace(objects=list(table.values()), files={"CAB-dance": container})
    return read, reads


class SharedReadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.path = self.dir / "dance.unity"
        self.path.write_bytes(b"one")
        self.deadline = time.monotonic() + 30

    def test_one_parse_per_file_inside_the_block_only(self):
        read, reads = _environment(["a", "b"])
        with patch.object(model_viewer, "_environment", side_effect=read):
            first, second = selection._read(self.path, self.deadline), selection._read(self.path, self.deadline)
            self.assertIsNot(first, second)
            self.assertEqual(len(reads), 2)
            with selection.shared_reads():
                shared = selection._read(self.path, self.deadline)
                self.assertIs(selection._read(str(self.path), self.deadline), shared)
                with selection.shared_reads():   # a nested block keeps the outer one's reads
                    self.assertIs(selection._read(self.path, self.deadline), shared)
                self.assertIs(selection._read(self.path, self.deadline), shared)
                self.assertEqual(len(reads), 3)
                # A rewritten file (other size or mtime) is read again.
                self.path.write_bytes(b"other")
                self.assertIsNot(selection._read(self.path, self.deadline), shared)
                self.assertEqual(len(reads), 4)
            selection._read(self.path, self.deadline)
            self.assertEqual(len(reads), 5)

    def test_a_rewrite_that_changes_only_the_size_or_only_the_mtime_is_read_again(self):
        read, reads = _environment(["a"])
        original = os.stat(self.path)
        with patch.object(model_viewer, "_environment", side_effect=read), selection.shared_reads():
            shared = selection._read(self.path, self.deadline)
            # The same size and inode; only the mtime moves.
            self.path.write_bytes(b"two")
            os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns + 10**9))
            info = os.stat(self.path)
            self.assertEqual((info.st_size, info.st_ino), (original.st_size, original.st_ino))
            moved = selection._read(self.path, self.deadline)
            self.assertIsNot(moved, shared)
            self.assertEqual(len(reads), 2)
            # Another size on the same inode, with the original mtime put back.
            self.path.write_bytes(b"longer")
            os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
            info = os.stat(self.path)
            self.assertEqual((info.st_mtime_ns, info.st_ino), (original.st_mtime_ns, original.st_ino))
            self.assertNotEqual(info.st_size, original.st_size)
            resized = selection._read(self.path, self.deadline)
            self.assertIsNot(resized, shared)
            self.assertIsNot(resized, moved)
            self.assertEqual(len(reads), 3)
            self.assertIs(selection._read(self.path, self.deadline), resized)

    def test_expired_deadline_still_refuses_a_kept_read(self):
        read, _ = _environment(["a"])
        with patch.object(model_viewer, "_environment", side_effect=read), selection.shared_reads():
            selection._read(self.path, self.deadline)
            with self.assertRaises(Exception):
                selection._read(self.path, time.monotonic() - 1)

    def test_write_selected_restores_a_shared_source(self):
        read, _ = _environment(["keep", "drop", "also"])
        with patch.object(model_viewer, "_environment", side_effect=read), selection.shared_reads():
            source = selection._read(self.path, self.deadline)
            table = source["objects"][0].assets_file.objects
            before = list(table.items())

            def write(keys, directory):
                chosen = {("cab-dance", key): {"object": table[key], "source": source} for key in keys}
                return selection.write_selected({"selected": chosen, "segments": []}, directory)

            first = self.dir / "first"
            first.mkdir()
            files, _, _, _ = write([1], first)
            container = source["env"].files["CAB-dance"]
            # Saved with only the kept clip, then put back in place and in order.
            self.assertEqual(container.saved, [[1]])
            self.assertEqual(list(table.items()), before)
            # The next member's selection sees the whole file and writes the same bytes
            # as a fresh read would.
            second = self.dir / "second"
            second.mkdir()
            files_again, _, _, _ = write([1], second)
            self.assertEqual(files_again[0]["sha256"], files[0]["sha256"])
            third = self.dir / "third"
            third.mkdir()
            write([2, 3], third)
            self.assertEqual(container.saved, [[1], [1], [2, 3]])
            self.assertEqual(list(table.items()), before)

    def test_write_selected_restores_after_a_failed_save(self):
        read, _ = _environment(["keep", "drop"])
        with patch.object(model_viewer, "_environment", side_effect=read), selection.shared_reads():
            source = selection._read(self.path, self.deadline)
            table = source["objects"][0].assets_file.objects
            before = list(table.items())
            source["env"].files["CAB-dance"].save = lambda packer: (_ for _ in ()).throw(OSError("disk full"))
            chosen = {("cab-dance", 1): {"object": table[1], "source": source}}
            with self.assertRaises(OSError):
                selection.write_selected({"selected": chosen, "segments": []}, self.dir)
            self.assertEqual(list(table.items()), before)


class SharedDownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pack = b"@UTF@UTF" + bytes(range(56))
        self.addCleanup(patch.stopall)
        # Sound sections (acb) are not decrypted: no Elichika extractor is needed.
        patch.object(studio.game, "_extractor", return_value=object()).start()
        patch.object(studio, "_local_section", return_value=None).start()
        self.remote = patch.object(studio.game, "_remote_pack", return_value=self.pack).start()

    def section(self, head, size, name="pack1"):
        return {"pack_name": name, "head": head, "size": size, "format": "acb", "pack_size": len(self.pack)}

    def test_each_pack_downloads_once_per_block(self):
        first, second = self.section(0, 8), self.section(4, 12)
        with studio.shared_downloads():
            self.assertEqual(studio.load_asset(self.root, first, download=True), self.pack[:8])
            with studio.shared_downloads():
                self.assertEqual(studio.load_asset(self.root, second, download=True), self.pack[4:16])
            self.assertEqual(self.remote.call_count, 1)
            # Another pack name, or the same name in another metapack, is its own download.
            studio.load_asset(self.root, self.section(0, 8, "pack2"), download=True)
            meta = dict(first, metapack={"name": "bucket", "offset": 0, "size": len(self.pack)})
            studio.load_asset(self.root, meta, download=True)
            studio.load_asset(self.root, meta, download=True)
            self.assertEqual(self.remote.call_count, 3)
        # Outside the block every section downloads again, and nothing is kept.
        studio.load_asset(self.root, first, download=True)
        studio.load_asset(self.root, second, download=True)
        self.assertEqual(self.remote.call_count, 5)
        self.assertIsNone(getattr(studio._SHARED, "packs", None))

    def test_kept_packs_stay_within_the_budget(self):
        with patch.object(studio, "_SHARED_PACK_BYTES", len(self.pack) + 1), studio.shared_downloads():
            studio.load_asset(self.root, self.section(0, 8), download=True)
            studio.load_asset(self.root, self.section(0, 8, "pack2"), download=True)
            studio.load_asset(self.root, self.section(0, 8, "pack2"), download=True)
            studio.load_asset(self.root, self.section(0, 8), download=True)
            # pack1 fits and is kept; pack2 would exceed the budget, so it downloads each time.
            self.assertEqual(self.remote.call_count, 3)

    def test_missing_pack_is_not_kept(self):
        from urllib.error import HTTPError
        self.remote.side_effect = HTTPError("https://cdn.invalid/pack1", 404, "missing", {}, None)
        with studio.shared_downloads():
            self.assertIsNone(studio.load_asset(self.root, self.section(0, 8), download=True))
            self.assertIsNone(studio.load_asset(self.root, self.section(0, 8), download=True))
        self.assertEqual(self.remote.call_count, 2)


class LoadGameWiringTests(unittest.TestCase):
    """load_game holds one shared read and download store for the whole import, and none after it."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.seen = []
        asset = lambda name, size: {"table": "test-assets", "asset": name, "available": True, "size": size}
        chosen = {
            "name": "Wiring fixture", "region": "gl", "platform": "android", "liveId": 10, "assetId": 11,
            "timeline": asset("timeline", 300), "choreography": [asset("dance", 40)],
            "stage": {"name": "Original stage", "model": asset("stage", 200)},
            "performers": [{"position": 1, "memberId": 210, "memberName": "Ayumu", "model": asset("actor", 900)},
                           {"position": 2, "memberId": 211, "memberName": "Kasumi", "model": asset("actor2", 800)}],
            "audio": {"cue": "song", "acb": asset("audio", 70), "awb": asset("wave", 30)},
        }
        self.addCleanup(patch.stopall)
        patch.object(studio, "resolve", return_value=chosen).start()
        patch.object(studio, "load_asset", side_effect=self.load_asset).start()
        patch.object(mv_studio_quality, "read_quality", return_value={"values": {}}).start()
        patch.object(mv_studio_actor_cache, "open_cache", return_value=None).start()
        patch.object(mv_studio, "_root", return_value=self.root).start()
        patch.object(mv_studio, "_timeline", side_effect=lambda path: (path.read_bytes(), {
            "duration": 12.0, "tracks": [{"id": "t", "kind": "camera", "label": "camera", "events": []}]})).start()
        patch.object(mv_studio, "_preview", side_effect=lambda path, **kwargs: (
            "/api/mv-studio/media/" + "0" * 32 + ".glb", {"clips": []} if kwargs.get("performer") else {})).start()
        patch.object(mv_studio, "_motion", side_effect=self.motion).start()
        patch.object(mv_studio, "_facial", side_effect=lambda timeline, motion, *args: motion).start()
        patch.object(cri_audio_decode, "decode_cue").start()
        patch.object(mv_studio, "_song_audio", return_value={"url": "/api/mv-studio/media/test.wav", "duration": 14.0}).start()
        patch.object(mv_studio, "_register", side_effect=lambda project, native: {**project, "token": "t" * 32}).start()

    def note(self, where):
        reads, packs = getattr(selection._SHARED, "reads", None), getattr(studio._SHARED, "packs", None)
        self.seen.append((where, isinstance(reads, dict) and id(reads), isinstance(packs, dict) and id(packs)))

    def load_asset(self, root, descriptor, *, download, deadline):
        self.note("load")
        return descriptor["asset"].encode()

    def motion(self, *args):
        self.note("motion")
        return [], {"bodySegments": []}

    def test_one_store_of_each_kind_spans_the_import(self):
        mv_studio.load_game(self.root, region="gl", platform="android", live_id=10, asset_id=11, language="en",
                            download=True)
        self.assertEqual([where for where, _, _ in self.seen].count("motion"), 2)
        self.assertGreater([where for where, _, _ in self.seen].count("load"), 2)
        # Every member's dance selection and every section read sees the same two stores.
        self.assertTrue(all(reads and packs for _, reads, packs in self.seen), self.seen)
        self.assertEqual(len({(reads, packs) for _, reads, packs in self.seen}), 1)
        # Nothing is kept once the import returns.
        self.assertIsNone(getattr(selection._SHARED, "reads", None))
        self.assertIsNone(getattr(studio._SHARED, "packs", None))


if __name__ == "__main__":
    unittest.main()
