"""Member head facial rules of the original live director.

Synthetic checks always run. REAL_MV_SAMPLES (optional, never bundled) points at
privately decrypted originals named <live>-timeline.unity, <live>-costume.unity and
<live>-face-<n>.unity for the verification songs.
"""
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from webtools.core import game_motion_selection, game_motion_timeline, model_faces


SAMPLES = Path(os.environ.get("REAL_MV_SAMPLES", "/nonexistent-private-mv-samples"))


class _Type:
    def __init__(self, name):
        self.name = name


class _Object:
    def __init__(self, path_id, kind, tree, source="costume"):
        self.path_id, self.type, self.tree, self.source = path_id, _Type(kind), tree, source

    def read_typetree(self):
        return self.tree


def _timeline(tracks):
    """MonoBehaviours of a TimelineAsset: Member groups, facial tracks and clips."""
    objects, classes, next_id = [], {}, [1000]

    def add(cls, tree):
        next_id[0] += 1
        objects.append(_Object(next_id[0], "MonoBehaviour", tree))
        classes[next_id[0]] = cls
        return next_id[0]

    groups = {member: add("GroupTrack", {"m_Name": f"Member{member}"}) for member in {row[0] for row in tracks}}
    for member, cls, rina, muted, clips in tracks:
        rows = []
        for start, index, *fields in clips:
            asset = add("Clip", fields[0] if fields else {"index": index, "weight": 1.0})
            rows.append({"m_Asset": {"m_FileID": 0, "m_PathID": asset}, "m_Start": start, "m_Duration": 1.0,
                         "m_DisplayName": f"{cls}-{index}"})
        tree = {"m_Name": cls, "m_Parent": {"m_FileID": 0, "m_PathID": groups[member]}, "m_Muted": muted, "m_Clips": rows}
        if rina is not None:
            tree["isRinaFacial"] = rina
        add(cls, tree)
    return {"objects": objects}, classes


class _Parse:
    def parse(self, tracks, **options):
        source, classes = _timeline(tracks)
        with patch.object(game_motion_selection, "_read", return_value=source), \
                patch.object(game_motion_selection, "_class", side_effect=lambda src, obj, tree: classes[obj.path_id]):
            return game_motion_timeline.parse_timeline("timeline.unity", 1, **options)


class SyntheticFacialSelectionTests(_Parse, unittest.TestCase):
    TRACKS = [
        (1, "MemberEyeTrack", 0, 0, [(0, 1), (2, 3)]),
        (1, "MemberEyeTrack", 1, 0, [(0, 101), (2, 102)]),
        (1, "MemberLipSyncTrack", 0, 0, [(0, 1)]),
        (1, "MemberLipSyncTrack", 1, 0, [(0, 999)]),
        (1, "MemberGazeTrack", None, 0, [(0, 0)]),
        (1, "MemberCheekTrack", None, 0, [(0, 0)]),
        (2, "MemberEyeTrack", 1, 0, [(5, 101)]),
    ]

    @staticmethod
    def indices(parsed, kind):
        return sorted(event["index"] for event in parsed["events"] if event["kind"] == kind)

    def test_unknown_head_keeps_every_unmuted_track(self):
        parsed = self.parse(self.TRACKS)
        self.assertEqual(self.indices(parsed, "eyes"), [1, 3, 101, 102])
        self.assertEqual(self.indices(parsed, "mouth"), [1, 999])
        self.assertNotIn("trackSelection", parsed)

    def test_masked_head_plays_only_rina_tracks(self):
        parsed = self.parse(self.TRACKS, face_dots=True)
        self.assertEqual(self.indices(parsed, "eyes"), [101, 102])
        self.assertEqual(self.indices(parsed, "mouth"), [999])
        self.assertEqual(len([e for e in parsed["events"] if e["kind"] in ("gaze", "cheek")]), 2)
        self.assertEqual(parsed["trackSelection"], {"faceDots": True, "useRina": True, "mask": False, "mutedTracks": 2})

    def test_unmasked_head_mutes_rina_tracks(self):
        parsed = self.parse(self.TRACKS, face_dots=False)
        self.assertEqual(self.indices(parsed, "eyes"), [1, 3])
        self.assertEqual(self.indices(parsed, "mouth"), [1])
        self.assertEqual(parsed["trackSelection"], {"faceDots": False, "useRina": False, "mask": False, "mutedTracks": 2})

    def test_masked_head_without_rina_tracks_uses_the_mask(self):
        tracks = [row for row in self.TRACKS if row[2] != 1 or row[0] != 1]
        parsed = self.parse(tracks, face_dots=True)
        self.assertEqual(self.indices(parsed, "eyes"), [1, 3])
        self.assertEqual(parsed["trackSelection"], {"faceDots": True, "useRina": False, "mask": True, "mutedTracks": 0})

    def test_selection_replaces_authored_mute_of_facial_tracks_only(self):
        tracks = [(1, "MemberEyeTrack", 1, 1, [(0, 101)]), (1, "MemberEyeTrack", 0, 1, [(0, 1)]),
                  (1, "MemberGazeTrack", None, 1, [(0, 0)])]
        # SetupFacialTrackMute writes muted = isRinaFacial XOR useRina.
        self.assertEqual(self.indices(self.parse(tracks, face_dots=True), "eyes"), [101])
        self.assertEqual(self.indices(self.parse(tracks, face_dots=False), "eyes"), [1])
        self.assertEqual(self.parse(tracks, face_dots=True)["events"][0]["kind"], "eyes")
        self.assertEqual(len(self.parse(tracks, face_dots=True)["events"]), 1, "gaze keeps its authored mute")
        self.assertEqual(self.parse(tracks)["events"], [], "an unknown head keeps the authored mute")


class SyntheticCheekEventTests(_Parse, unittest.TestCase):
    def test_cheek_events_carry_type_and_intensity(self):
        cheek = {"cheekType": 1, "intensity": .317}
        parsed = self.parse([(1, "MemberCheekTrack", None, 0, [(2, 0, cheek), (5, 0, {"cheekType": 0, "intensity": 7})])],
                            face_dots=False)
        rows = [(event["index"], event["intensity"], event["weight"]) for event in parsed["events"]]
        self.assertEqual(rows, [(1, .317, 1.0), (0, 1.0, 1.0)], "intensity is a finite 0-1 value")


class _Scene:
    def __init__(self, objects, names, deadline):
        self.env = type("Env", (), {"objects": objects})()
        self.objects = {obj.path_id: obj for obj in objects}
        self.names, self.deadline = names, deadline
        self.transforms = {obj.tree["m_GameObject"]["m_PathID"]: obj for obj in objects if obj.type.name == "Transform"}

    def tree(self, obj):
        return obj.tree

    def name(self, obj):
        return self.names[obj.path_id]


def _pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


class SyntheticMemberHeadTests(unittest.TestCase):
    def scene(self, dots_path=("Head_Face", "mesh_facedots"), managers=1, script=("BodyPartManager", "LLAS.Components.Members")):
        objects, names, ids = [], {}, iter(range(1, 1000))

        def node(name, parent=None):
            game, transform = next(ids), next(ids)
            names[game] = name
            objects.append(_Object(game, "GameObject", {"m_Name": name}))
            objects.append(_Object(transform, "Transform", {"m_GameObject": _pointer(game), "m_Children": [],
                                                            "m_Father": _pointer(parent.path_id) if parent else {}}))
            if parent is not None:
                parent.tree["m_Children"].append(_pointer(transform))
            return objects[-2], objects[-1]

        _, head = node("Head")
        head_all_game, head_all = node("Head_All", head)
        node("Other", head_all)
        parent = head_all
        for name in dots_path:
            _, parent = node(name, parent)
        monoscript = next(ids)
        objects.append(_Object(monoscript, "MonoScript", {"m_ClassName": script[0], "m_Namespace": script[1],
                                                          "m_AssemblyName": "Assembly-CSharp.dll"}))
        for _ in range(managers):
            objects.append(_Object(next(ids), "MonoBehaviour", {"m_Script": _pointer(monoscript), "head": _pointer(head.path_id),
                                                                "headAll": _pointer(head_all_game.path_id), "face": {}}))
        return _Scene(objects, names, time.monotonic() + 30)

    def head(self, scene, sources=("costume",)):
        from webtools.core import model_viewer
        with patch.object(model_viewer, "_ref", side_effect=lambda owner, p: scene.objects.get((p or {}).get("m_PathID"))), \
                patch.object(model_viewer, "_key", side_effect=lambda obj: obj.path_id), \
                patch.object(model_viewer, "_source_path", side_effect=lambda obj: obj.source):
            return model_faces.member_head(scene, set(sources))

    def test_face_dots_follow_transform_find_below_head_all(self):
        self.assertEqual(self.head(self.scene()), {"faceDots": True})
        self.assertEqual(self.head(self.scene(dots_path=("Head_Face", "mesh_face"))), {"faceDots": False})
        self.assertEqual(self.head(self.scene(dots_path=("Head_Face", "mask", "mesh_facedots"))), {"faceDots": False},
                         "Find matches the exact relative path, not any descendant")
        self.assertEqual(self.head(self.scene(dots_path=("head_face", "mesh_facedots"))), {"faceDots": False},
                         "Transform names are case sensitive")

    def test_only_one_verified_body_part_manager_describes_the_head(self):
        self.assertEqual(self.head(self.scene(managers=2)), {})
        self.assertEqual(self.head(self.scene(script=("BodyPartManager", "Other"))), {})
        self.assertEqual(self.head(self.scene(), sources=("other",)), {})


@unittest.skipUnless((SAMPLES / "12029-timeline.unity").is_file(), "Private original MV samples are optional")
class OriginalFacialSelectionTests(unittest.TestCase):
    def events(self, live, **options):
        parsed = game_motion_timeline.parse_timeline(str(SAMPLES / f"{live}-timeline.unity"), 1, **options)
        counts = {kind: sum(event["kind"] == kind for event in parsed["events"]) for kind in ("eyes", "mouth")}
        return parsed, counts

    @staticmethod
    def overlaps(parsed, kind):
        spans = sorted((event["start"], event["start"] + event["duration"]) for event in parsed["events"] if event["kind"] == kind)
        return sum(spans[i + 1][0] < spans[i][1] - 1e-6 for i in range(len(spans) - 1))

    def test_12029_board_plays_only_its_rina_tracks(self):
        parsed, counts = self.events(12029, face_dots=True)
        self.assertEqual(counts, {"eyes": 62, "mouth": 289})
        self.assertEqual(self.overlaps(parsed, "mouth"), 0)
        self.assertEqual(parsed["trackSelection"], {"faceDots": True, "useRina": True, "mask": False, "mutedTracks": 2})
        self.assertEqual(self.events(12029, face_dots=False)[1], {"eyes": 43, "mouth": 315})
        self.assertEqual(self.events(12029)[1], {"eyes": 105, "mouth": 604})

    def test_other_songs_are_unchanged_for_an_unmasked_head(self):
        for live in (12007, 12023, 12025, 12035, 12036, 12038):
            path = SAMPLES / f"{live}-timeline.unity"
            if not path.is_file():
                continue
            with self.subTest(live=live):
                legacy, _ = self.events(live)
                selected, _ = self.events(live, face_dots=False)
                self.assertEqual(selected.pop("trackSelection")["mutedTracks"], 0)
                self.assertEqual(selected, legacy)

    def test_12035_cheek_clips(self):
        parsed, _ = self.events(12035, face_dots=False)
        cheeks = [(round(e["start"], 3), e["index"], round(e["intensity"], 3), e["timing"]["easeIn"], round(e["timing"]["easeOut"], 3))
                  for e in parsed["events"] if e["kind"] == "cheek"]
        self.assertEqual(cheeks, [(15.883, 0, .317, .2, .6), (57.263, 0, .317, .2, .6), (78.467, 0, .317, .2, .6)])

    def test_member_head_reads_the_loaded_board(self):
        from webtools.core import model_viewer as viewer
        for live, expected in ((12029, True), (12035, False)):
            paths = [SAMPLES / f"{live}-costume.unity", *sorted(SAMPLES.glob(f"{live}-face-*.unity"))]
            if not paths[0].is_file():
                continue
            with self.subTest(live=live):
                deadline = time.monotonic() + 60
                scene = viewer._Scene(viewer._environment([str(path) for path in paths], deadline), deadline)
                head = model_faces.member_head(scene, {str(paths[0])})
                self.assertEqual(head["faceDots"], expected)
                # InitializeDefault binds the cheek to the merged face's head material; a mask has none.
                self.assertEqual(head.get("cheekMaterial"), None if expected else "ch0212_co0001_head")


if __name__ == "__main__":
    unittest.main()
