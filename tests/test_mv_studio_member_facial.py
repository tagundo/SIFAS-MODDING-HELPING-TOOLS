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
    def scene(self, dots_path=("Head_Face", "mesh_facedots"), managers=1, script=("BodyPartManager", "LLAS.Components.Members"),
              face_data=None):
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
        face, material = {}, {}
        if face_data is not None:
            # MemberFace lives in the separate face bundle for merged faces.
            face_script, face_id, material_id = next(ids), next(ids), next(ids)
            objects.append(_Object(face_script, "MonoScript", {"m_ClassName": "MemberFace", "m_Namespace": "LLAS.Components.Members",
                                                               "m_AssemblyName": "Assembly-CSharp.dll"}, "face"))
            objects.append(_Object(face_id, "MonoBehaviour", {"m_Script": _pointer(face_script), "memberFaceData": face_data}, "face"))
            objects.append(_Object(material_id, "Material", {"m_Name": "ch0212_co0001_head"}))
            face, material = _pointer(face_id), _pointer(material_id)
        for _ in range(managers):
            objects.append(_Object(next(ids), "MonoBehaviour", {"m_Script": _pointer(monoscript), "head": _pointer(head.path_id),
                                                                "headAll": _pointer(head_all_game.path_id), "face": face,
                                                                "headMaterial": material}))
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

    def test_unmasked_merged_face_reports_cheek_material_and_lip_sync_weight(self):
        data = {"lipSync": {"weight": 0.8999999761581421}, "needsMergingFace": 1}
        unmasked = self.head(self.scene(dots_path=("Head_Face",), face_data=data))
        self.assertEqual(unmasked, {"faceDots": False, "cheekMaterial": "ch0212_co0001_head",
                                    "lipSyncWeight": 0.8999999761581421})
        self.assertEqual(self.head(self.scene(face_data=data)), {"faceDots": True},
                         "InitializeMask/ForRinaTrack add no cheek and create mouth clips at rate 1")
        unmerged = self.head(self.scene(dots_path=("Head_Face",), face_data={"lipSync": {"weight": 1.5}, "needsMergingFace": 0}))
        self.assertEqual(unmerged, {"faceDots": False}, "no CombineFace, and an out-of-range weight is not used")

    def test_face_tables_keep_rows_aliases_and_null_clips_in_serialized_order(self):
        """InitializeDefault hands MemberFaceData.animationTableEye/Mouth to the eye and lip-sync controls."""
        data = {"lipSync": {"weight": 1.0}, "needsMergingFace": 0,
                "animationTableEye": _pointer(900), "animationTableMouth": _pointer(901)}
        scene = self.scene(dots_path=("Head_Face",), face_data=data)
        added = [_Object(910, "MonoScript", {"m_ClassName": "MemberFacialAnimationDataTable", "m_Namespace": "LLAS.Scene.Live.Components",
                                             "m_AssemblyName": "Assembly-CSharp.dll"}, "eye-table"),
                 _Object(911, "MonoScript", {"m_ClassName": "Other", "m_Namespace": "LLAS.Scene.Live.Components",
                                             "m_AssemblyName": "Assembly-CSharp.dll"}, "eye-table"),
                 _Object(920, "AnimationClip", {}, "mouth-table"), _Object(921, "AnimationClip", {}, "mouth-table"),
                 _Object(922, "AnimationClip", {}, "eye-table")]
        scene.names.update({920: "ch0212_LiveFacial_mouth_004", 921: "ch0212_LiveFacial_mouth_007", 922: "ch0212_LiveFacial_eye_005"})

        def table(path_id, script, rows, source):
            return _Object(path_id, "MonoBehaviour", {"m_Script": _pointer(script), "datas": [
                {"index": index, "customIndex": custom, "summary": summary, "clip": _pointer(clip) if clip else {"m_FileID": 0, "m_PathID": 0}}
                for index, custom, summary, clip in rows]}, source)
        eye = table(900, 910, [(101, 5, 101, 922), (20, 0, 20, None)], "eye-table")
        mouth = table(901, 910, [(4, 0, 10004, 920), (13, 4, 10013, 920), (14, 0, 10014, None), (999, 7, 10999, 921)], "mouth-table")
        for obj in (*added, eye, mouth):
            scene.objects[obj.path_id] = obj
            scene.env.objects.append(obj)
        from webtools.core import model_viewer
        with patch.object(model_viewer, "_source_hash", side_effect=lambda obj: "sha-" + obj.source):
            head = self.head(scene)
        self.assertEqual(head["facialTables"], {
            "eyes": [{"index": 101, "customIndex": 5, "summary": 101, "sourceHash": "sha-eye-table", "sourceName": "ch0212_LiveFacial_eye_005"},
                     {"index": 20, "customIndex": 0, "summary": 20}],
            "mouth": [{"index": 4, "customIndex": 0, "summary": 10004, "sourceHash": "sha-mouth-table", "sourceName": "ch0212_LiveFacial_mouth_004"},
                      {"index": 13, "customIndex": 4, "summary": 10013, "sourceHash": "sha-mouth-table", "sourceName": "ch0212_LiveFacial_mouth_004"},
                      {"index": 14, "customIndex": 0, "summary": 10014},
                      {"index": 999, "customIndex": 7, "summary": 10999, "sourceHash": "sha-mouth-table", "sourceName": "ch0212_LiveFacial_mouth_007"}]})
        # Another script, or a row whose clip is not loaded, leaves that table out (the old name lookup applies).
        eye.tree["m_Script"] = _pointer(911)
        del scene.objects[921]
        with patch.object(model_viewer, "_source_hash", side_effect=lambda obj: "sha-" + obj.source):
            self.assertNotIn("facialTables", self.head(scene))

    def test_unreadable_face_table_keeps_the_rest_of_the_head(self):
        data = {"lipSync": {"weight": 0.5}, "needsMergingFace": 1, "animationTableMouth": _pointer(901)}
        scene = self.scene(dots_path=("Head_Face",), face_data=data)
        for error in (KeyError, TypeError, ValueError, AttributeError):
            with self.subTest(error=error.__name__), patch.object(model_faces, "_facial_tables", side_effect=error("bad table")):
                self.assertEqual(self.head(scene), {"faceDots": False, "cheekMaterial": "ch0212_co0001_head", "lipSyncWeight": 0.5})

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

    def test_facial_banks_keep_null_clip_rows(self):
        paths = sorted(SAMPLES.glob("12035-face-*.unity"))
        if not paths:
            self.skipTest("12035 face bundles are required")
        selected, entries = game_motion_selection.facial_banks(paths, deadline=time.monotonic() + 60)
        rows = {(entry["kind"], entry["index"]): entry["key"] and selected["selected"][entry["key"]]["object"].peek_name() for entry in entries}
        self.assertEqual(rows["mouth", 13], "ch0212_LiveFacial_mouth_004")
        self.assertEqual(rows["mouth", 101], "ch0212_LiveFacial_mouth_008")
        self.assertIsNone(rows["mouth", 14])
        self.assertIsNone(rows["eyes", 20])

    def test_member_head_reads_the_loaded_board(self):
        from webtools.core import model_viewer as viewer
        # (faceDots, cheekMaterial, MemberFaceData.lipSync.weight) of the loaded head.
        expected = {12029: (True, None, None), 12035: (False, "ch0212_co0001_head", .9),
                    12007: (False, "ch0206_co0001_head", .9), 12038: (False, "ch0210_co0017_head", .95)}
        for live, (dots, cheek, lip_sync) in expected.items():
            paths = [SAMPLES / f"{live}-costume.unity", *sorted(SAMPLES.glob(f"{live}-face-*.unity"))]
            if not paths[0].is_file():
                continue
            with self.subTest(live=live):
                deadline = time.monotonic() + 60
                scene = viewer._Scene(viewer._environment([str(path) for path in paths], deadline), deadline)
                head = model_faces.member_head(scene, {str(paths[0])})
                self.assertEqual(head["faceDots"], dots)
                # InitializeDefault binds the cheek to the merged face's head material; a mask has none.
                self.assertEqual(head.get("cheekMaterial"), cheek)
                # InitializeDefault passes LipSync.Weight; a masked head's mouth control uses rate 1.
                if lip_sync is None:
                    self.assertNotIn("lipSyncWeight", head)
                else:
                    self.assertAlmostEqual(head["lipSyncWeight"], lip_sync, places=6)
                # The face's own tables: mouth 13 (E2) plays mouth_004, mouth 14 has a null clip.
                tables = {kind: {row["index"]: row.get("sourceName") for row in rows} for kind, rows in head["facialTables"].items()}
                self.assertTrue(tables["mouth"][13].endswith("_LiveFacial_mouth_004"))
                self.assertIsNone(tables["mouth"][14])
                self.assertIsNone(tables["eyes"][20])
                self.assertEqual(tables["eyes"][2] is None, live == 12029, "the Rina board has no eye 002 clip")

if __name__ == "__main__":
    unittest.main()
