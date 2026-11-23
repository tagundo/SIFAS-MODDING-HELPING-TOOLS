"""Timeline PPtrs resolve only inside the timeline's serialized dependency closure.

Unity resolves m_FileID > 0 through the referencing SerializedFile's
externals[m_FileID - 1] (a CAB). Only loaded bundles reached that way can
supply an object identity to the dance selection or the clip names.
"""
from types import SimpleNamespace
import unittest

from webtools.core import game_motion_selection as selection


def _file(name, *externals):
    return SimpleNamespace(name=name, externals=[SimpleNamespace(path=f"archive:/{item}/{item}") for item in externals])


def _object(assets_file, path_id, kind="AnimationClip", raw=b"clip"):
    return SimpleNamespace(assets_file=assets_file, path_id=path_id, type=SimpleNamespace(name=kind),
                           get_raw_data=lambda: raw)


def _source(label, *objects):
    return {"label": label, "objects": list(objects), "scripts": {}}


class DependencyClosureTests(unittest.TestCase):
    def test_closure_follows_externals_of_loaded_files_only(self):
        timeline = _source("timeline", _object(_file("CAB-timeline", "CAB-a"), 1, "MonoBehaviour"))
        a = _source("a", _object(_file("CAB-a", "CAB-b"), 1))
        b = _source("b", _object(_file("CAB-b"), 1))
        unrelated = _source("c", _object(_file("CAB-c"), 1))
        self.assertEqual(selection.dependency_closure(timeline, [a, b, unrelated]), {"cab-timeline", "cab-a", "cab-b"})
        self.assertEqual(selection.dependency_closure(timeline, [b]), {"cab-timeline", "cab-a"})

    def test_unrelated_bundle_cannot_inject_or_conflict(self):
        timeline = _source("timeline", _object(_file("CAB-timeline", "CAB-a"), 1, "MonoBehaviour", raw=b"t"))
        a = _source("a", _object(_file("CAB-a"), 7, raw=b"clip"))
        # An unrelated CAB with the same PathID and different bytes is ignored.
        unrelated = _source("c", _object(_file("CAB-c"), 7, raw=b"other"))
        objects, owners = selection.dependency_objects(timeline, [a, unrelated])
        self.assertEqual(set(objects), {("cab-timeline", 1), ("cab-a", 7)})
        self.assertIs(owners["cab-a", 7], a)
        clash = _source("clash", _object(_file("CAB-a"), 7, raw=b"different"))
        with self.assertRaisesRegex(ValueError, "conflicting serialized identities"):
            selection.dependency_objects(timeline, [a, clash])


if __name__ == "__main__":
    unittest.main()
