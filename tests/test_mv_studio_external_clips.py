"""Timeline AnimationClips resolved through the timeline's dependency packs.

The rule under test: a timeline PPtr with m_FileID > 0 names a CAB through
its SerializedFile's externals; only loaded dependency packs inside that
serialized closure supply the object, by exact (CAB, PathID). Original samples
are optional (ELICHIKA_STUDIO_TIMELINE_DIR), see RealDependencyClipTests.
"""
from copy import deepcopy
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_external_clips as external
from webtools.core import mv_studio_timeline

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))
GENERIC = mv_studio_timeline.EXTERNAL_CLIP_WARNING


def _file(name, *externals):
    return SimpleNamespace(name=name, externals=[SimpleNamespace(path=f"archive:/{item}/{item}") for item in externals])


def _object(assets_file, path_id, kind="AnimationClip", name="", raw=b"clip"):
    return SimpleNamespace(assets_file=assets_file, path_id=path_id, type=SimpleNamespace(name=kind),
                           peek_name=lambda: name, get_raw_data=lambda: raw)


def _source(label, *objects):
    return {"label": label, "objects": list(objects), "scripts": {}}


def _track(identity, label, display, animation, **values):
    return {"id": identity, "kind": "dance", "label": label, "nativeClass": "AnimationTrack",
            "binding": "/EntryPoint/Live/Members/Member1/Model",
            "events": [{"id": identity + ":0", "start": 0., "duration": 106.6667, "label": display,
                        "values": {"playableClass": "AnimationPlayableAsset", "animation": animation, **values},
                        "editableValues": []}]}


class ExternalClipResolutionTests(unittest.TestCase):
    def setUp(self):
        # 12035 in miniature: the timeline's externals are a shader pack and the
        # choreography CAB; its dance playable points at {m_FileID: 2, PathID 5}.
        self.timeline_file = _file("CAB-timeline", "CAB-shader", "CAB-dance")
        self.timeline = _source("timeline", _object(self.timeline_file, 1, "MonoBehaviour"))
        self.dance = _source("UGp", _object(_file("CAB-dance"), 5, name="ch0212_so2035"))
        self.tracks = [_track("timeline-track", "MemberMotion/Member1", "ch0211_so2035", "cab-dance:5")]

    def resolve(self, *sources, tracks=None):
        loaded = {source["label"]: source for source in sources if source is not None}

        def read(raw, label, deadline):
            if label == "timeline":
                return self.timeline
            if raw is None or label not in loaded:
                raise ValueError("not a bundle")
            return loaded[label]

        with patch.object(external, "_source", side_effect=read):
            dependencies = [(source["label"], b"bundle") for source in sources if source is not None]
            dependencies += [("UGp", None)] if None in sources else []
            return external.resolve(self.tracks if tracks is None else tracks, b"timeline", dependencies,
                                    time.monotonic() + 30)

    def test_references_are_the_clips_the_track_parser_could_not_name(self):
        tracks = deepcopy(self.tracks)
        tracks[0]["events"].extend([
            {"id": "local", "label": "camera", "values": {"playableClass": "AnimationPlayableAsset",
                                                          "animation": "cab-timeline:9", "animationName": "cam"}},
            {"id": "light", "label": "light", "values": {"playableClass": "LiveBaseLightClip", "asset": "cab-timeline:3"}},
            {"id": "broken", "label": "broken", "values": {"playableClass": "AnimationPlayableAsset", "animation": "x"}},
        ])
        rows = external.references(tracks)
        self.assertEqual([(event["id"], key) for _, event, key in rows], [("timeline-track:0", ("cab-dance", 5))])

    def test_dependency_clip_resolves_by_exact_cab_and_path_id(self):
        before = deepcopy(self.tracks)
        result = self.resolve(self.dance)
        self.assertEqual(result, {"warnings": [], "clips": {"timeline-track:0": {
            "track": "timeline-track", "animation": "cab-dance:5", "animationName": "ch0212_so2035", "dependency": "UGp"}}})
        self.assertEqual(self.tracks, before)

    def test_missing_pack_warns_with_track_clip_and_identity(self):
        result = self.resolve(None)
        self.assertEqual(result["clips"], {})
        self.assertEqual(result["warnings"], [
            "Track 'MemberMotion/Member1' clip 'ch0211_so2035' plays AnimationClip cab-dance:5, but no loaded "
            "dependency of this timeline provides cab-dance. Unavailable dependency packs: UGp."])

    def test_pack_outside_the_serialized_closure_cannot_supply_the_identity(self):
        # Same CAB name in the pointer, but this bundle is a different CAB.
        other = _source("other", _object(_file("CAB-other"), 5, name="ch0212_so2035"))
        result = self.resolve(other)
        self.assertEqual(result["clips"], {})
        self.assertIn("Loaded packs this timeline does not reference: other.", result["warnings"][0])

    def test_wrong_path_id_and_wrong_type_are_reported_precisely(self):
        empty = _source("UGp", _object(_file("CAB-dance"), 6, name="ch0212_so2035"))
        self.assertIn("the loaded dependency cab-dance has no object 5.", self.resolve(empty)["warnings"][0])
        texture = _source("UGp", _object(_file("CAB-dance"), 5, "Texture2D"))
        self.assertIn("that object is a Texture2D, not an AnimationClip.", self.resolve(texture)["warnings"][0])

    def test_conflicting_copies_of_a_dependency_are_refused(self):
        copy = _source("copy", _object(_file("CAB-dance"), 5, name="ch0212_so2035", raw=b"other bytes"))
        result = self.resolve(self.dance, copy)
        self.assertEqual(result["clips"], {})
        self.assertIn("conflicting serialized identities", result["warnings"][0])

    def test_corrupt_pack_is_reported_unavailable_and_others_still_resolve(self):
        def read(raw, label, deadline):
            if label == "timeline":
                return self.timeline
            if label == "corrupt":
                raise struct.error("unpack requires a buffer of 4 bytes")
            return self.dance

        with patch.object(external, "_source", side_effect=read):
            result = external.resolve(self.tracks, b"timeline", [("corrupt", b"bundle"), ("UGp", b"bundle")],
                                      time.monotonic() + 30)
        self.assertEqual(result["clips"]["timeline-track:0"]["animationName"], "ch0212_so2035")
        with patch.object(external, "_source", side_effect=read):
            result = external.resolve(self.tracks, b"timeline", [("corrupt", b"bundle")], time.monotonic() + 30)
        self.assertIn("Unavailable dependency packs: corrupt.", result["warnings"][0])

    def test_no_external_reference_needs_no_dependency(self):
        tracks = deepcopy(self.tracks)
        tracks[0]["events"][0]["values"]["animationName"] = "ch0212_so2035"
        with patch.object(external, "_source", side_effect=AssertionError("no bundle is opened")):
            self.assertIsNone(external.resolve(tracks, b"timeline", [], time.monotonic() + 30))


class SharedReadTests(unittest.TestCase):
    def test_prefetched_section_is_read_once_and_errors_surface_at_load(self):
        calls = []

        def read(descriptor):
            calls.append(descriptor["asset"])
            if descriptor["asset"] == "bad":
                raise OSError("pack unreadable")
            return descriptor["asset"].encode()

        reads = external.SharedReads(read)
        good, bad = {"table": "live_timeline", "asset": "UGp"}, {"table": "live_timeline", "asset": "bad"}
        reads.prefetch([good, bad, dict(good), None])
        self.assertEqual(calls, ["UGp", "bad"])
        self.assertEqual(reads.peek(good), b"UGp")
        self.assertIsNone(reads.peek(bad))
        self.assertEqual(reads(dict(good)), b"UGp")
        with self.assertRaisesRegex(OSError, "pack unreadable"):
            reads(bad)
        self.assertEqual(calls, ["UGp", "bad"])
        self.assertEqual(reads(good), b"UGp")
        self.assertEqual(calls, ["UGp", "bad", "UGp"])


class ApplyToProjectTests(unittest.TestCase):
    def project(self):
        return {"tracks": [_track("t", "MemberMotion/Member1", "ch0211_so2035", "cab-dance:5")],
                "warnings": ["first", GENERIC, "last"]}

    def test_resolved_clips_replace_the_generic_warning_and_keep_event_values(self):
        project = self.project()
        tracks = deepcopy(project["tracks"])
        reads = external.SharedReads(lambda descriptor: b"pack")
        resolved = {"clips": {"t:0": {"track": "t", "animation": "cab-dance:5", "animationName": "ch0212_so2035",
                                      "dependency": "UGp"}}, "warnings": []}
        with patch.object(external, "resolve", return_value=resolved) as resolve:
            names = external.apply(project, b"timeline", [{"asset": "UGp"}], reads, time.monotonic() + 30)
        self.assertEqual(resolve.call_args.args[2], [("UGp", b"pack")])
        self.assertEqual(names, {"t:0": "ch0212_so2035"})
        self.assertEqual(project["warnings"], ["first", "last"])
        self.assertEqual(project["companionClips"], resolved["clips"])
        self.assertEqual(project["tracks"], tracks)

    def test_missing_dependency_warning_takes_the_generic_warning_place(self):
        project = self.project()
        with patch.object(external, "resolve", return_value={"clips": {}, "warnings": ["precise"]}):
            self.assertEqual(external.apply(project, b"timeline", [], external.SharedReads(bytes), 0), {})
        self.assertEqual(project["warnings"], ["first", "precise", "last"])
        self.assertNotIn("companionClips", project)

    def test_projects_without_external_clips_read_nothing_early(self):
        project = self.project()
        project["tracks"][0]["events"][0]["values"]["animationName"] = "ch0212_so2035"
        reads = external.SharedReads(lambda descriptor: self.fail("no early read"))
        self.assertEqual(external.apply(project, b"timeline", [{"asset": "UGp"}], reads, 0), {})
        self.assertEqual(project["warnings"], ["first", GENERIC, "last"])

    def test_unreadable_timeline_keeps_the_generic_warning(self):
        project = self.project()
        with patch.object(external, "resolve", side_effect=ValueError("broken")):
            self.assertEqual(external.apply(project, b"timeline", [], external.SharedReads(bytes), 0), {})
        self.assertEqual(project["warnings"], ["first", GENERIC, "last"])

    def test_any_resolver_failure_keeps_the_import_going_with_the_generic_warning(self):
        for error in (struct.error("unpack requires a buffer"), IndexError("list index out of range"),
                      RuntimeError("unexpected")):
            with self.subTest(error=type(error).__name__):
                project = self.project()
                with patch.object(external, "resolve", side_effect=error):
                    self.assertEqual(external.apply(project, b"timeline", [{"asset": "UGp"}],
                                                    external.SharedReads(lambda descriptor: b"pack"), 0), {})
                self.assertEqual(project["warnings"], ["first", GENERIC, "last"])
                self.assertNotIn("companionClips", project)


class CastByClipTests(unittest.TestCase):
    def tracks(self, *displays):
        return [_track(f"member-{slot}", f"MemberMotion/Member{slot}", display, f"cab-dance-{slot}:5")
                | {"binding": f"/EntryPoint/Live/Members/Member{slot}/Model"}
                for slot, display in enumerate(displays, start=1)]

    def test_the_played_clip_identifies_the_slot_member_before_the_display_name(self):
        from webtools.core import mv_studio
        performers = [{"position": 1, "memberId": 211}, {"position": 2, "memberId": 212}]
        # Display names carry the swapped Mia/Lanzhu code (as 12035/12036 do).
        tracks = self.tracks("ch0211_so9999", "ch0212_so9999")
        by_display = mv_studio._cast_in_timeline_order(performers, tracks)
        self.assertEqual([(row["position"], row["memberId"]) for row in by_display], [(1, 212), (2, 211)])
        names = {"member-1:0": "ch0212_so9999", "member-2:0": "ch0211_so9999"}
        by_clip = mv_studio._cast_in_timeline_order(performers, tracks, names)
        self.assertEqual([(row["position"], row["memberId"]) for row in by_clip], [(1, 211), (2, 212)])

    def test_a_name_without_a_member_code_falls_through_to_the_next_name(self):
        from webtools.core import mv_studio
        performers = [{"position": 1, "memberId": 211}, {"position": 2, "memberId": 212}]
        tracks = self.tracks("ch0211_so9999", "ch0212_so9999")
        # No resolved clip name carries a chNNNN code, so the display names decide.
        cast = mv_studio._cast_in_timeline_order(performers, tracks, {"member-1:0": "dance_loop", "member-2:0": ""})
        self.assertEqual([(row["position"], row["memberId"]) for row in cast], [(1, 212), (2, 211)])
        # animationName comes before the display name.
        tracks[0]["events"][0]["values"]["animationName"] = "ch0212_so9999"
        tracks[1]["events"][0]["values"]["animationName"] = "ch0211_so9999"
        cast = mv_studio._cast_in_timeline_order(performers, tracks, {"member-1:0": "dance_loop"})
        self.assertIsNot(cast, performers)
        self.assertEqual([(row["position"], row["memberId"]) for row in cast], [(1, 211), (2, 212)])

    def test_12035_solo_casts_by_its_clip_instead_of_falling_back(self):
        from webtools.core import mv_studio
        performers = [{"position": 1, "memberId": 211}]
        tracks = self.tracks("ch0211_so2035")
        self.assertIs(mv_studio._cast_in_timeline_order(performers, tracks), performers)
        cast = mv_studio._cast_in_timeline_order(performers, tracks, {"member-1:0": "ch0212_so2035"})
        self.assertIsNot(cast, performers)
        self.assertEqual(cast, performers)


class LoadGameWiringTests(unittest.TestCase):
    """The import resolves dance clips before casting, reading each pack once."""

    def setUp(self):
        import tempfile
        from webtools.core import mv_studio, mv_studio_actor_cache, mv_studio_game, mv_studio_quality

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reads = []
        self.motions = []
        self.tracks = [
            {**_track(f"member-{slot}", f"MemberMotion/Member{slot}", display, f"cab-dance-{slot}:5"),
             "binding": f"/EntryPoint/Live/Members/Member{slot}/Model"}
            for slot, display in ((1, "ch0211_so9999"), (2, "ch0212_so9999"))]
        asset = lambda name: {"table": "live_timeline", "asset": name, "available": True}
        self.selection = {
            "name": "Fixture", "region": "gl", "platform": "ios", "liveId": 1, "assetId": 2,
            "timeline": asset("timeline"), "stage": {"model": asset("stage")},
            "performers": [{"position": 1, "memberId": 211, "model": asset("actor-211")},
                           {"position": 2, "memberId": 212, "model": asset("actor-212")}],
            "dependencies": [dict(asset("dance-a"), role="choreography"), dict(asset("dance-b"), role="choreography")],
            "choreography": [dict(asset("dance-a"), role="choreography"), dict(asset("dance-b"), role="choreography")],
        }
        self.resolved = {"clips": {"member-1:0": {"track": "member-1", "animation": "cab-dance-1:5",
                                                  "animationName": "ch0212_so9999", "dependency": "dance-a"},
                                   "member-2:0": {"track": "member-2", "animation": "cab-dance-2:5",
                                                  "animationName": "ch0211_so9999", "dependency": "dance-b"}},
                         "warnings": []}
        self.addCleanup(patch.stopall)
        patch.object(mv_studio_game, "resolve", side_effect=lambda *a, **k: deepcopy(self.selection)).start()
        patch.object(mv_studio_game, "load_asset", side_effect=self.load_asset).start()
        patch.object(mv_studio_quality, "read_quality", return_value={"values": {}}).start()
        patch.object(mv_studio_actor_cache, "open_cache", return_value=None).start()
        patch.object(mv_studio, "_root", return_value=self.root).start()
        patch.object(mv_studio, "_timeline", side_effect=lambda path: (path.read_bytes(), {
            "duration": 10.0, "tracks": deepcopy(self.tracks), "warnings": ["earlier", GENERIC]})).start()
        patch.object(mv_studio, "_preview", return_value=("/api/mv-studio/media/" + "a" * 32 + ".glb", {})).start()
        patch.object(mv_studio, "_motion", side_effect=self.motion).start()
        # The fixture timeline is not a real bundle: the facial pass that runs
        # on the loaded head is outside this wiring test.
        patch.object(mv_studio, "_facial", side_effect=lambda timeline, motion, *rest: motion).start()
        patch.object(mv_studio, "_register", side_effect=lambda project, native: project).start()
        self.mv_studio = mv_studio

    def load_asset(self, root, descriptor, *, download, deadline):
        self.reads.append(descriptor["asset"])
        return descriptor["asset"].encode()

    def motion(self, timeline, dependencies, facial, directory, position, owner, tracks, deadline):
        self.motions.append((position, owner, [path.name for path in dependencies]))
        return [], {"bodySegments": []}

    def import_game(self):
        return self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")

    def test_import_names_dependency_clips_and_casts_by_them(self):
        with patch.object(external, "resolve", return_value=deepcopy(self.resolved)) as resolve:
            project = self.import_game()
        tracks, raw, dependencies, _ = resolve.call_args.args
        self.assertEqual(raw, b"timeline")
        self.assertEqual(dependencies, [("dance-a", b"dance-a"), ("dance-b", b"dance-b")])
        self.assertEqual(self.reads.count("dance-a"), 1)
        self.assertEqual(self.reads.count("dance-b"), 1)
        self.assertEqual(project["warnings"], ["earlier"])
        self.assertEqual(project["importCoverage"]["gaps"], [])
        self.assertEqual(project["companionClips"], self.resolved["clips"])
        self.assertEqual(project["tracks"], self.tracks)
        self.assertEqual([(row["position"], row["memberId"]) for row in project["performers"]], [(1, 211), (2, 212)])
        self.assertLess(self.reads.index("dance-a"), self.reads.index("stage"))
        # Asset rows and the staged choreography file names (actor cache
        # inputs) are those of an import that reads the packs at their row.
        early = (self.motions[:], [(row["id"], row["path"], row["status"]) for row in project["assets"]])
        self.motions.clear()
        self.reads.clear()
        for track in self.tracks:
            track["events"][0]["values"]["animationName"] = "ch0212_so9999"
        with patch.object(external, "resolve", side_effect=AssertionError("no external clip")):
            later = self.import_game()
        self.assertGreater(self.reads.index("dance-a"), self.reads.index("stage"))
        self.assertEqual(early, (self.motions, [(row["id"], row["path"], row["status"]) for row in later["assets"]]))
        self.assertEqual(self.motions[0], (1, 211, ["game-3.unity", "game-4.unity"]))

    def test_missing_pack_keeps_a_precise_warning(self):
        precise = "Track 'MemberMotion/Member1' clip 'ch0211_so9999' plays AnimationClip cab-dance-1:5, but ..."
        with patch.object(external, "resolve", return_value={"clips": {}, "warnings": [precise]}):
            project = self.import_game()
        self.assertEqual(project["warnings"], ["earlier", precise])
        self.assertNotIn("companionClips", project)
        # Without clip names the display names decide, as before.
        self.assertEqual([(row["position"], row["memberId"]) for row in project["performers"]], [(1, 212), (2, 211)])


def _samples(*names):
    return all((SAMPLES / name).is_file() for name in names)


@unittest.skipUnless(_samples("a-1203503-live_timeline.unity", "i-1203503-live_timeline.unity",
                              "a-1203503-choreography.unity", "i-1203503-choreography.unity"),
                     "Original 12035 timeline and choreography samples are optional")
class RealDependencyClipTests(unittest.TestCase):
    def check(self, timeline, choreography, expected):
        raw = (SAMPLES / timeline).read_bytes()
        parsed = mv_studio_timeline.parse_timeline(raw, timeline)
        self.assertIn(GENERIC, parsed["warnings"])
        tracks = deepcopy(parsed["tracks"])
        dependencies = [(name, (SAMPLES / name).read_bytes()) for name in choreography]
        result = external.resolve(tracks, raw, dependencies, time.monotonic() + 60)
        self.assertEqual(result["warnings"], [])
        found = {}
        for track in tracks:
            for event in track["events"]:
                if event["id"] in result["clips"]:
                    found[track["label"]] = (event["label"], result["clips"][event["id"]]["animationName"])
        self.assertEqual(found, expected)
        self.assertEqual(tracks, parsed["tracks"])
        self.assertIs(mv_studio_timeline.export_timeline(raw, timeline, tracks), raw)
        missing = external.resolve(tracks, raw, [(name, None) for name in choreography], time.monotonic() + 60)
        self.assertEqual(missing["clips"], {})
        self.assertEqual(len(missing["warnings"]), len(expected))
        return result

    def test_12035_dance_clip_is_the_choreography_pack_clip_on_both_platforms(self):
        for platform in ("a", "i"):
            with self.subTest(platform=platform):
                result = self.check(f"{platform}-1203503-live_timeline.unity", [f"{platform}-1203503-choreography.unity"],
                                    {"MemberMotion/Member1": ("ch0211_so2035", "ch0212_so2035")})
                clip, = result["clips"].values()
                self.assertEqual(clip["animation"], "cab-a1600f34dce5a67c3abab6068c0996fe:6826311605069373343")

    @unittest.skipUnless(_samples("i-1205603-group-live_timeline.unity", "i-1205603-choreography-0.unity",
                                  "i-1205603-choreography-1.unity", "i-1205603-choreography-2.unity"),
                         "Original 12056 group samples are optional")
    def test_12056_group_clips_resolve_per_member_pack(self):
        self.check("i-1205603-group-live_timeline.unity", [f"i-1205603-choreography-{index}.unity" for index in range(3)],
                   {f"MemberMotion/Member{slot}": (f"ch02{slot + 9}_so2056", f"ch02{slot + 9}_so2056")
                    for slot in (1, 2, 3)})


if __name__ == "__main__":
    unittest.main()
