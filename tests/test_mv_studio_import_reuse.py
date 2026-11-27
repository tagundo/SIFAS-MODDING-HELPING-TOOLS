"""An MV import reads each bundle once, with unchanged results.

game_motion_selection.shared_reads() keeps a parsed bundle for every member's dance
selection; write_selected must then leave a shared source exactly as it found it.
Outside the block nothing is kept.
"""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import game_motion_selection as selection
from webtools.core import model_viewer


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


if __name__ == "__main__":
    unittest.main()
