"""Track mutes that reach the game: the rule, the export, registration, and "Apply only the edits".

Original game samples are optional (ELICHIKA_STUDIO_TIMELINE_DIR, every *timeline*.unity there, with
a-/i-1203503-live_timeline.unity as one MV on both platforms); Elichika's own install validator runs
when the Elichika server app is importable (PYTHONPATH)."""
from copy import deepcopy
from pathlib import Path
import os
import time
import unittest

from webtools.core import mv_studio_apply as apply, mv_studio_register as register, mv_studio_timeline as studio

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))
try:
    import mv_studio_native_assets as native  # Elichika
except ImportError:  # pragma: no cover - depends on PYTHONPATH
    native = None


def track(identity, label, native_class="LiveColoringTrack", muted=False, events=()):
    return {"id": identity, "kind": "display", "label": label, "events": list(events), "nativeClass": native_class,
            "muted": muted}


def clip(event_id, value=1.0):
    return {"id": event_id, "start": 0.0, "duration": 1.0, "label": "c", "values": {"intensity": value},
            "editableValues": ["intensity"]}


def timeline(*tracks):
    return {"duration": 1.0, "warnings": [], "tracks": list(tracks)}


class RuleTests(unittest.TestCase):
    def test_which_mutes_reach_the_game(self):
        reach = [("CameraMotion/Camera1", "AnimationTrack"), ("Member1/LipSync", "MemberLipSyncTrack"),
                 # One group deeper than a quality category: ApplyMuteToChildTracks does not recurse.
                 ("StageEffect/Expert/Coloring/LightShaft/LED_p", "LiveColoringTrack"),
                 # A StageEffect category the quality table has no entry for (12023's "Overlay").
                 ("StageEffect/Expert/Overlay/Flash", "CustomControlTrack"),
                 # The same under the other roots (12029's and 12035's prop animation; no stock names
                 # for the last three): each root's own names only.
                 ("PropEffect/Expert/PropAnimation/x", "AnimationTrack"),
                 ("MemberEffect/Expert/Member Coloring/x", "LiveColoringTrack"),
                 ("GlobalEffect/Expert/Split Screen/x", "CustomControlTrack"),
                 ("MotionMisc/Expert/BaseLight/x", "CustomControlTrack"),
                 ("Top", "LiveBloomTrack")]
        for label, native_class in reach:
            with self.subTest(label=label):
                self.assertIsNone(studio.track_mute_refusal(track("t", label, native_class)))
                self.assertEqual(studio.exportable_track_fields(track("t", label, native_class)), ("muted",))
        quality = [("StageEffect/Expert/Coloring/LED_panel_01", "coloring"),
                   ("StageEffect/Expert/Flash Light/Flash", "flashlight"),
                   ("StageEffect/Expert/OverlayEffect/Glow", "overlayeffect"),
                   ("StageEffect/Normal/Post/Bloom", "post"),
                   ("MemberEffect/Expert/Member Rim Light/Rim1", "memberrimlight"),
                   ("MemberEffect/Expert/Member Ambient/A", "memberambient"),
                   ("MemberEffect/Expert/Member Spot Light Area/A", "memberspotlightarea"),
                   ("MemberEffect/Expert/MemberSpotLightShaft/S", "memberspotlightshaft"),
                   ("PropEffect/Expert/Prop Ambient/Ambient", "propambient"),
                   ("PropEffect/Expert/Prop Rim Light/R", "proprimlight"),
                   ("PropEffect/Expert/Prop Coloring/C", "propcoloring"),
                   ("GlobalEffect/Expert/Base Light/Base", "baselight"),
                   ("MotionMisc/Expert/Split Screen/Split", "splitscreen")]
        for label, category in quality:
            with self.subTest(label=label):
                self.assertEqual(studio.quality_category(label), category)
                self.assertEqual(studio.track_mute_refusal(track("t", label)), studio.QUALITY_MUTE)
                self.assertEqual(studio.exportable_track_fields(track("t", label)), ())
        self.assertEqual(studio.track_mute_refusal(track("g", "StageEffect", "GroupTrack")), studio.GROUP_MUTE)
        self.assertEqual(studio.track_mute_refusal(track("g", "Member1", "GroupTrack")), studio.GROUP_MUTE)
        self.assertEqual(studio.track_mute_refusal(None), studio.GROUP_MUTE)
        for label in (None, 3, "", "StageEffect/Expert/Coloring", "Other/Expert/Coloring/LED"):
            self.assertIsNone(studio.quality_category(label))


class ExportRuleTests(unittest.TestCase):
    def setUp(self):
        self.original = timeline(track("leaf", "Member1/Gaze", "MemberGazeTrack", events=[clip("leaf:0")]),
                                 track("led", "StageEffect/Expert/Coloring/LED"),
                                 track("group", "StageEffect", "GroupTrack"))

    def revise(self, identity, **fields):
        revised = deepcopy(self.original)
        next(item for item in revised["tracks"] if item["id"] == identity).update(fields)
        return revised

    def test_a_leaf_mute_is_a_track_change(self):
        revised = self.revise("leaf", muted=True)
        self.assertEqual(studio._changes(self.original, revised), [])
        self.assertEqual(studio._track_changes(self.original, revised), [("leaf", "muted", True)])
        self.assertEqual(studio._track_changes(self.original, deepcopy(self.original)), [])
        # An equal value posted as another type is no change (JSON numbers and booleans).
        self.assertEqual(studio._track_changes(self.original, self.revise("leaf", muted=0)), [])

    def test_mutes_that_do_not_reach_the_game_are_refused(self):
        for identity, message in (("led", studio.QUALITY_MUTE), ("group", studio.GROUP_MUTE)):
            with self.subTest(identity=identity), self.assertRaises(ValueError) as caught:
                studio._changes(self.original, self.revise(identity, muted=True))
            self.assertEqual(str(caught.exception), message)
        with self.assertRaisesRegex(ValueError, r"^A track mute must be on or off\.$"):
            studio._changes(self.original, self.revise("leaf", muted=1))
        with self.assertRaisesRegex(ValueError, "original metadata are read-only"):
            studio._changes(self.original, self.revise("leaf", muted=True, binding="/elsewhere"))
        revised = self.revise("leaf", muted=True)
        del revised["tracks"][0]["muted"]
        with self.assertRaisesRegex(ValueError, "original metadata are read-only"):
            studio._changes(self.original, revised)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.original = timeline(track("leaf", "Member1/Gaze", "MemberGazeTrack", events=[clip("leaf:0")]),
                                 track("led", "StageEffect/Expert/Coloring/LED", events=[clip("led:0")]),
                                 track("group", "StageEffect", "GroupTrack"))["tracks"]

    def posted(self, **mutes):
        tracks = deepcopy(self.original)
        for item in tracks:
            if item["id"] in mutes:
                item["muted"] = mutes[item["id"]]
        return tracks

    def test_normalize_keeps_a_leaf_mute_and_reports_the_others(self):
        normalized, report = register.normalize(self.original, self.posted(leaf=True, led=True, group=True))
        self.assertEqual([item["muted"] for item in normalized], [True, False, False])
        self.assertEqual(report["trackSettings"], ["StageEffect", "StageEffect/Expert/Coloring/LED"])
        counts = register.count_edits(self.original, normalized)
        self.assertEqual(counts, {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0, "tracks": 1})
        self.assertTrue(register.has_edits(counts))
        self.assertFalse(register.has_edits(register.count_edits(self.original, deepcopy(self.original))))
        # The export rules accept what normalize keeps.
        base = timeline(*self.original)
        self.assertEqual(studio._track_changes(base, timeline(*normalized)), [("leaf", "muted", True)])

    def test_the_fingerprint_follows_exportable_mutes_only(self):
        identity = "tl:0:1:1:1"
        plain = register.timeline_fingerprint("android", identity, self.original)
        self.assertNotEqual(plain, register.timeline_fingerprint("android", identity, self.posted(leaf=True)))
        self.assertEqual(plain, register.timeline_fingerprint("android", identity, self.posted(led=True, group=True)))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.base = timeline(track("leaf", "Member1/Gaze", "MemberGazeTrack", events=[clip("leaf:0")]))["tracks"]

    def tracks(self, muted=False, value=1.0):
        result = deepcopy(self.base)
        result[0]["muted"] = muted
        result[0]["events"][0]["values"]["intensity"] = value
        return result

    def test_apply_only_the_edits_keeps_a_track_mute(self):
        merge = studio.merge_changes
        merged, conflicts, taken, theirs_only = merge(self.base, self.tracks(muted=True), self.tracks(value=2.0))
        self.assertEqual((merged[0]["muted"], merged[0]["events"][0]["values"]["intensity"], conflicts, taken, theirs_only),
                         (True, 2.0, [], 1, 1))
        # Already muted in the game: nothing to take.
        self.assertEqual(merge(self.base, self.tracks(muted=True), self.tracks(muted=True))[1:], ([], 0, 0))
        # After this project applied its mute, the agreed value is the mute.
        synced = studio.synced_fields(self.base, self.tracks(muted=True))
        self.assertEqual(synced, {"leaf": {"muted": [studio.field_digest(True), "true"]}})
        # The project unmuted it again and the game still holds the applied mute: ours is taken.
        merged, conflicts, taken, theirs_only = merge(self.base, self.tracks(muted=False), self.tracks(muted=True), synced)
        self.assertEqual((merged[0]["muted"], conflicts, taken, theirs_only), (False, [], 1, 0))
        # The game unmuted it since and the project kept its mute: the game's change stays.
        merged, conflicts, taken, theirs_only = merge(self.base, self.tracks(muted=True), self.tracks(muted=False), synced)
        self.assertEqual((merged[0]["muted"], conflicts, taken, theirs_only), (False, [], 0, 1))

    def test_a_track_field_conflict_names_the_track(self):
        # A bool cannot differ from both sides; the conflict row of a track field, on three values.
        base, ours, theirs = (self.tracks(muted=value) for value in ("a", "b", "c"))
        merged, conflicts, taken, _ = studio.merge_changes(base, ours, theirs)
        self.assertEqual((merged[0]["muted"], taken), ("c", 0))
        self.assertEqual(conflicts, [{"track": "Member1/Gaze", "trackId": "leaf", "clip": "", "eventId": "leaf",
                                      "start": 0.0, "scope": "track", "field": "muted", "basis": "load",
                                      "loaded": '"a"', "project": '"b"', "game": '"c"'}])

    def test_pending_counts_a_mute_since_the_last_apply(self):
        base = {"tracks": self.base}
        ours = self.tracks(muted=True)
        self.assertEqual(apply._pending(base, ours, None)["tracks"], 1)
        self.assertEqual(apply._pending(base, ours, {})["tracks"], 1)
        synced = studio.synced_fields(self.base, ours)
        self.assertEqual(apply._pending(base, ours, synced), {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0,
                                                              "tracks": 0})
        self.assertEqual(apply._pending(base, self.tracks(), synced)["tracks"], 1)

    def test_a_missing_track_field_in_the_game_is_another_layout(self):
        theirs = self.tracks()
        del theirs[0]["muted"]
        with self.assertRaisesRegex(ValueError, "different track layout"):
            studio.merge_changes(self.base, self.tracks(muted=True), theirs)


def sample_timelines():
    if not SAMPLES.is_dir():
        return []
    return sorted(path for path in SAMPLES.glob("*timeline*.unity") if "choreography" not in path.name)


@unittest.skipUnless(sample_timelines(), "Original game samples are optional")
class ActualTimelineTests(unittest.TestCase):
    def test_a_leaf_mute_exports_parses_back_and_passes_the_install_validator(self):
        import UnityPy

        for path in sample_timelines():
            with self.subTest(sample=path.name):
                raw = path.read_bytes()
                parsed = studio.parse_timeline(raw, path.name)
                self.assertIs(studio.export_timeline(raw, path.name, deepcopy(parsed["tracks"])), raw)
                tracks = deepcopy(parsed["tracks"])
                leaf = next(item for item in tracks if item["events"] and studio.track_mute_refusal(item) is None)
                leaf["muted"] = not leaf["muted"]
                started = time.monotonic()
                edited = studio.export_timeline(raw, path.name, tracks)
                seconds = time.monotonic() - started
                self.assertNotEqual(edited, raw)
                self.assertEqual(studio.parse_timeline(edited, path.name)["tracks"], tracks)
                self.assertLess(seconds, 30)
                platform = int(list(UnityPy.load(raw).assets)[0].target_platform)
                if native is not None:
                    native._validate_timeline(edited, raw, platform, time.monotonic() + 120)
                # A track directly in a category group of a quality root whose name no quality option
                # has (PropEffect/<difficulty>/PropAnimation on 12029 and 12035, 12023's Overlay).
                tracks = deepcopy(parsed["tracks"])
                other = next((item for item in tracks if item["nativeClass"] != "GroupTrack"
                              and item["label"].count("/") == 3
                              and item["label"].split("/")[0] in studio._QUALITY_CATEGORIES
                              and studio.track_mute_refusal(item) is None), None)
                if other is not None:
                    other["muted"] = not other["muted"]
                    edited = studio.export_timeline(raw, path.name, tracks)
                    self.assertEqual(studio.parse_timeline(edited, path.name)["tracks"], tracks)
                    if native is not None:
                        native._validate_timeline(edited, raw, platform, time.monotonic() + 120)
                for refused in (next((item for item in parsed["tracks"]
                                      if studio.track_mute_refusal(item) == studio.QUALITY_MUTE), None),
                                next(item for item in parsed["tracks"] if item["nativeClass"] == "GroupTrack")):
                    if refused is None:
                        continue
                    attempt = deepcopy(parsed["tracks"])
                    next(item for item in attempt if item["id"] == refused["id"])["muted"] = not refused["muted"]
                    with self.assertRaisesRegex(ValueError, "does not reach the game"):
                        studio.export_timeline(raw, path.name, attempt)

    @unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file()
                         and (SAMPLES / "i-1203503-live_timeline.unity").is_file(), "Both platforms are optional")
    def test_registration_keeps_the_mute_on_both_platforms(self):
        raw = {platform: (SAMPLES / f"{prefix}-1203503-live_timeline.unity").read_bytes()
               for platform, prefix in (("android", "a"), ("ios", "i"))}
        android = studio.parse_timeline(raw["android"], "a")["tracks"]
        tracks = deepcopy(android)
        leaf = next(item for item in tracks if item["events"] and studio.track_mute_refusal(item) is None)
        leaf["muted"] = True
        for platform, data in raw.items():
            with self.subTest(platform=platform):
                reference = studio.parse_timeline(data, platform)["tracks"]
                normalized, report = register.normalize(reference, tracks)
                self.assertEqual(report["trackSettings"], [])
                self.assertEqual(register.count_edits(reference, normalized)["tracks"], 1)
                exported = studio.export_timeline(data, platform, normalized)
                again = {item["id"]: item for item in studio.parse_timeline(exported, platform)["tracks"]}
                self.assertTrue(again[leaf["id"]]["muted"])


if __name__ == "__main__":
    unittest.main()
