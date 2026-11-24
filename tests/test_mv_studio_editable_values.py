"""Editable MV timeline values: the whitelist, its export guards and the editableValues migration.

Original game samples are optional (ELICHIKA_STUDIO_TIMELINE_DIR with a-1203503-live_timeline.unity)."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
import json
import os
import re
import unittest

from webtools.core import mv_studio, mv_studio_timeline as studio

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))
FIELDS_JS = ROOT / "webtools" / "web" / "static" / "mv-studio-event-fields.js"

# What this change added to the whitelist (a project saved before it carries lists without these).
ADDED = {
    "LiveDepthOfFieldClip": {"kernelSize", "useMemberDistance", "bodyPart"},
    "LiveMemberAmbientClip": {"colorSpecifiedType"},
    "LiveStageAmbientClip": {"colorSpecifiedType"},
    "LiveStageSingleAmbientClip": {"colorSpecifiedType"},
    "LiveStageEmissiveClip": {"colorSpecifiedType"},
    "LiveMemberSpotLightAreaClip": {"colorSpecifiedType"},
    "LiveMemberSpotLightShaftClip": {"colorSpecifiedType", "drawObjectIndex"},
    "LiveRimlightClip": {"colorSpecifiedType"},
    "LiveFlareClip": {"colorSpecifiedType"},
    "LiveFlashLightClip": {"colorSpecifiedType", "status"},
    "LiveDisplayClip": {"materialIndex"},
    "LiveColoringClip": {"textureIndex"},
    "LiveMemberScalingClip": {"intensity"},
    "LivePropAmbientClip": {"color", "tintColor", "colorSpecifiedType"},
    "LivePropRimlightClip": {"color", "intensity", "sharpness", "direction", "colorSpecifiedType"},
}


def descriptors():
    """The JSON descriptor table of mv-studio-event-fields.js."""
    source = FIELDS_JS.read_text(encoding="utf-8")
    match = re.search(r"/\* descriptors:begin \*/(.*?)/\* descriptors:end \*/", source, re.S)
    if not match:
        raise AssertionError("mv-studio-event-fields.js has no descriptors block")
    return json.loads(match.group(1))


def old_lists(tracks):
    """The tracks as a project saved before the whitelist grew carries them."""
    tracks = deepcopy(tracks)
    for track in tracks:
        for event in track["events"]:
            added = ADDED.get(event["values"].get("playableClass"), set())
            event["editableValues"] = [field for field in event["editableValues"] if field not in added]
    return tracks


def event(event_id, native, values, editable=(), start=0., memberPosition=None):
    values = {"asset": "cab:" + event_id, "playableClass": native, **values}
    if memberPosition is not None:
        values["memberPosition"] = memberPosition
    return {"id": event_id, "start": start, "duration": 1., "label": event_id, "values": values,
            "editableValues": list(editable)}


def timeline(*tracks):
    return {"duration": 10., "warnings": [], "tracks": [
        {"id": track_id, "kind": "lighting", "nativeClass": "Track", "label": track_id, "events": list(events)}
        for track_id, events in tracks]}


class WhitelistTests(unittest.TestCase):
    def test_every_whitelisted_field_has_a_descriptor(self):
        table = descriptors()["classes"]
        missing = sorted(f"{native}.{field}" for native, fields in studio._EDITABLE_VALUES.items()
                         for field in fields if field not in table.get(native, {}))
        self.assertEqual(missing, [])

    def test_descriptors_for_limited_and_observed_fields_match_the_server(self):
        data = descriptors()
        table, sets = data["classes"], data["sets"]
        for (native, field), (low, high) in studio._LIMITED_VALUES.items():
            spec = table[native][field]
            with self.subTest(native=native, field=field):
                if spec["control"] == "bool-int":
                    values = [0, 1]
                elif spec["control"] == "enum":
                    values = [option[0] for option in sets[spec["set"]]]
                else:
                    self.assertIn(spec["control"], ("facial-index", "enum-members"))
                    continue
                self.assertEqual((min(values), max(values)), (low, high), values)
        for (native, field), scope in studio._OBSERVED_VALUES.items():
            self.assertEqual(table[native][field]["control"], "enum-observed")
            self.assertEqual(table[native][field]["scope"], scope)
        scaling = table["LiveMemberScalingClip"]["intensity"]
        self.assertEqual((scaling["control"], scaling["min"], scaling["max"]), ("slider", 0, 1))
        controls = {"number", "slider", "vector", "color", "enum", "enum-observed", "enum-members", "bool-int", "text",
                    "facial-index", "readonly"}
        for native, fields in table.items():
            for field, spec in fields.items():
                self.assertIn(spec["control"], controls, f"{native}.{field}")
                if "set" in spec:
                    self.assertIn(spec["set"], sets)
                if field not in studio._EDITABLE_VALUES.get(native, set()):
                    self.assertEqual(spec["control"], "readonly", f"{native}.{field} is not exportable")

    def test_colour_source_classes_are_the_ones_with_a_member_colour_preview(self):
        self.assertEqual(studio._COLOR_SOURCE_CLASSES, {
            "LiveMemberAmbientClip", "LiveStageAmbientClip", "LiveStageSingleAmbientClip", "LiveStageEmissiveClip",
            "LiveMemberSpotLightAreaClip", "LiveMemberSpotLightShaftClip", "LiveRimlightClip", "LiveFlareClip",
            "LiveFlashLightClip", "LivePropAmbientClip", "LivePropRimlightClip"})
        for native in studio._COLOR_SOURCE_CLASSES:
            self.assertEqual(studio._LIMITED_VALUES[(native, "colorSpecifiedType")], (0, 2))

    def test_limited_values_and_scaling_intensity_are_refused_outside_their_range(self):
        cases = [("LiveDepthOfFieldClip", "kernelSize", 0, 3, 4), ("LiveDepthOfFieldClip", "useMemberDistance", 0, 1, 2),
                 ("LiveFlashLightClip", "status", 1, 2, 3), ("LiveRimlightClip", "colorSpecifiedType", 0, 2, 3),
                 ("LivePropAmbientClip", "colorSpecifiedType", 0, 1, -1)]
        for native, field, native_value, good, bad in cases:
            with self.subTest(native=native, field=field):
                tree = {field: native_value}
                studio._set_playable_value(tree, native, field, good)
                self.assertEqual(tree[field], good)
                with self.assertRaisesRegex(ValueError, "outside the supported native range"):
                    studio._set_playable_value(tree, native, field, bad)
                with self.assertRaisesRegex(ValueError, "outside the supported native range"):
                    studio._set_playable_value(tree, native, field, float(good))
        tree = {"intensity": 1.}
        studio._set_playable_value(tree, "LiveMemberScalingClip", "intensity", .25)
        self.assertEqual(tree["intensity"], .25)
        for bad in (1.5, -.1):
            with self.assertRaisesRegex(ValueError, "invalid intensity"):
                studio._set_playable_value(tree, "LiveMemberScalingClip", "intensity", bad)
        # Other classes' intensities stay unclamped (a bloom intensity above 1 is a native value).
        tree = {"intensity": 1.}
        studio._set_playable_value(tree, "LiveBloomClip", "intensity", 3.5)
        self.assertEqual(tree["intensity"], 3.5)


class CheckValuesTests(unittest.TestCase):
    def setUp(self):
        self.original = timeline(
            ("coloring-a", [event("coloring-a:0", "LiveColoringClip", {"textureIndex": 0}),
                            event("coloring-a:1", "LiveColoringClip", {"textureIndex": 2}, start=2.)]),
            ("coloring-b", [event("coloring-b:0", "LiveColoringClip", {"textureIndex": 5})]),
            ("dof", [event("dof:0", "LiveDepthOfFieldClip", {"bodyPart": 0, "useMemberDistance": 0}, memberPosition=1),
                     event("dof:1", "LiveDepthOfFieldClip", {"bodyPart": 0, "useMemberDistance": 0}, memberPosition=0)]),
            ("dof-b", [event("dof-b:0", "LiveDepthOfFieldClip", {"bodyPart": 3, "useMemberDistance": 1}, memberPosition=2)]),
            ("rim", [event("rim:0", "LiveRimlightClip", {"colorSpecifiedType": 0}, memberPosition=6),
                     event("rim:1", "LiveRimlightClip", {"colorSpecifiedType": 1}, memberPosition=0, start=2.),
                     event("rim:2", "LiveRimlightClip", {"colorSpecifiedType": 0}, memberPosition=13, start=4.)]),
        )

    def revise(self, event_id, **values):
        revised = deepcopy(self.original)
        for track in revised["tracks"]:
            for item in track["events"]:
                if item["id"] == event_id:
                    item["values"].update(values)
        return revised

    def test_unchanged_values_are_never_checked(self):
        # rim:1 already has a member colour without a member slot: the original data is not judged.
        studio._check_values(self.original, deepcopy(self.original))

    def test_observed_values_on_the_same_track(self):
        studio._check_values(self.original, self.revise("coloring-a:0", textureIndex=2))
        with self.assertRaisesRegex(ValueError, r"^Choose a value this MV already uses for 'textureIndex'\.$"):
            studio._check_values(self.original, self.revise("coloring-a:0", textureIndex=5))  # Only on coloring-b.
        with self.assertRaisesRegex(ValueError, "already uses for 'textureIndex'"):
            studio._check_values(self.original, self.revise("coloring-a:0", textureIndex=1))
        with self.assertRaisesRegex(ValueError, "already uses for 'textureIndex'"):
            studio._check_values(self.original, self.revise("coloring-a:0", textureIndex=2.0))
        with self.assertRaisesRegex(ValueError, "already uses for 'textureIndex'"):
            studio._check_values(self.original, self.revise("coloring-a:0", textureIndex=True))

    def test_observed_body_parts_anywhere_in_the_timeline(self):
        studio._check_values(self.original, self.revise("dof:0", bodyPart=3))  # From the other DOF track.
        with self.assertRaisesRegex(ValueError, "already uses for 'bodyPart'"):
            studio._check_values(self.original, self.revise("dof:0", bodyPart=2))

    def test_member_colour_and_member_focus_need_a_member_slot(self):
        studio._check_values(self.original, self.revise("rim:0", colorSpecifiedType=1))
        studio._check_values(self.original, self.revise("rim:0", colorSpecifiedType=2))
        studio._check_values(self.original, self.revise("rim:1", colorSpecifiedType=0))
        for event_id in ("rim:1", "rim:2"):
            with self.assertRaisesRegex(ValueError, r"^This colour source needs the clip's member position to be 1 to 12\.$"):
                studio._check_values(self.original, self.revise(event_id, colorSpecifiedType=2))
        studio._check_values(self.original, self.revise("dof:0", useMemberDistance=1))
        with self.assertRaisesRegex(ValueError, r"^Member focus needs the clip's member position to be 1 to 12\.$"):
            studio._check_values(self.original, self.revise("dof:1", useMemberDistance=1))
        studio._check_values(self.original, self.revise("dof-b:0", useMemberDistance=0))

    def test_malformed_revisions_are_left_to_the_structure_check(self):
        for revised in (None, {}, {"tracks": None}, {"tracks": [None, {"events": [None, {"id": 3}]}]}):
            studio._check_values(self.original, revised)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            studio._rewrite_timeline(b"", self.original, {"tracks": []})


class SyncEditableValuesTests(unittest.TestCase):
    fresh = [{"id": "t", "kind": "stage", "events": [
        event("t:0", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, ["clipIn", "shift", "textureIndex"]),
        event("t:1", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, ["clipIn", "shift", "textureIndex"]),
        event("t:2", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, ["clipIn", "shift", "textureIndex"]),
        event("t:3", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, ["clipIn", "shift", "textureIndex"]),
    ]}, {"id": "u", "kind": "stage", "events": []}]

    def test_subsets_take_the_fresh_list_and_nothing_else_changes(self):
        saved = deepcopy(self.fresh)
        events = saved[0]["events"]
        events[0]["editableValues"] = ["clipIn", "shift"]                       # Saved before: upgraded.
        events[0]["values"]["shift"] = 12                                     # Its edit stays.
        events[1]["editableValues"] = ["clipIn", "shift", "other"]            # Not a subset: kept.
        events[2]["editableValues"] = ["clipIn"]
        events[2]["values"]["asset"] = "cab:elsewhere"                        # Another playable: kept.
        events[3]["editableValues"] = ["shift", "clipIn", "textureIndex"]     # Same set, other order: fresh order.
        saved.append({"id": "user", "kind": "stage", "events": [event("user:0", "LiveColoringClip", {"textureIndex": 1}, ["clipIn"])]})
        before = deepcopy(saved)
        synced = studio.sync_editable_values(saved, self.fresh)
        self.assertEqual(saved, before)
        self.assertEqual(synced[0]["events"][0], {**before[0]["events"][0], "editableValues": ["clipIn", "shift", "textureIndex"]})
        self.assertEqual(synced[0]["events"][1:3], before[0]["events"][1:3])
        self.assertEqual(synced[0]["events"][3]["editableValues"], ["clipIn", "shift", "textureIndex"])
        self.assertIs(synced[1], saved[1])
        self.assertIs(synced[2], saved[2])
        self.assertEqual(studio.sync_editable_values(deepcopy(self.fresh), self.fresh), self.fresh)

    def test_needs_sync_only_for_missing_whitelisted_fields(self):
        current = self.fresh[0]
        self.assertFalse(studio.needs_editable_values_sync(current))
        old = deepcopy(current)
        old["events"][2]["editableValues"] = ["clipIn", "shift"]
        self.assertTrue(studio.needs_editable_values_sync(old))
        for value in (None, {}, {"events": None}, {"events": [None, {"values": None}, {"values": {"playableClass": 3}}]}):
            self.assertFalse(studio.needs_editable_values_sync(value))

    def test_saved_project_reopens_with_the_current_lists(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        root = Path(work.name).resolve()
        with patch.object(mv_studio, "_root", return_value=root), \
                patch.object(mv_studio, "_destination", side_effect=lambda name, suffix: root / (name + suffix)):
            native = b"original timeline bytes"
            project = mv_studio._blank("Old lists")
            project["duration"] = 10
            project["tracks"] = deepcopy(self.fresh)
            project["tracks"][0]["events"][0]["editableValues"] = ["clipIn", "shift"]
            project["tracks"][0]["events"][0]["values"]["shift"] = 7
            saved = mv_studio.save(mv_studio._register(project, native))
            with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"tracks": self.fresh}) as parse:
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
            parse.assert_called_once_with(native, "Old lists", preview_split=False, preview_stage_title=False)
            first = reopened["tracks"][0]["events"][0]
            self.assertEqual(first["editableValues"], ["clipIn", "shift", "textureIndex"])
            self.assertEqual(first["values"]["shift"], 7)
            # A project with current lists opens without parsing for this reason.
            project["tracks"] = deepcopy(self.fresh)
            saved = mv_studio.save(mv_studio._register(project, native))
            with ZipFile(saved["path"]) as archive, patch("webtools.core.mv_studio_timeline.parse_timeline") as parse:
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
            parse.assert_not_called()
            self.assertEqual(reopened["tracks"], self.fresh)


@unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file(), "Original game samples are optional")
class ActualTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (SAMPLES / "a-1203503-live_timeline.unity").read_bytes()
        cls.fresh = studio.parse_timeline(cls.raw, "a")

    @staticmethod
    def find(tracks, native, label=None):
        for track in tracks:
            for item in track["events"]:
                if item["values"].get("playableClass") == native and (label is None or track["label"].endswith(label)):
                    return track, item
        raise AssertionError(native)

    def test_new_fields_are_listed_for_unshared_clips(self):
        listed = {(item["values"]["playableClass"], field) for track in self.fresh["tracks"] for item in track["events"]
                  for field in item["editableValues"]}
        for native, field in [("LiveColoringClip", "textureIndex"), ("LiveDisplayClip", "materialIndex"),
                              ("LiveMemberScalingClip", "intensity"), ("LivePropAmbientClip", "color"),
                              ("LivePropRimlightClip", "direction"), ("LiveDepthOfFieldClip", "bodyPart"),
                              ("LiveFlashLightClip", "status"), ("LiveRimlightClip", "colorSpecifiedType")]:
            self.assertIn((native, field), listed)

    def test_project_saved_with_the_old_lists_exports_unedited_bytes_and_edits(self):
        old = old_lists(self.fresh["tracks"])
        self.assertNotEqual(old, self.fresh["tracks"])
        self.assertTrue(any(studio.needs_editable_values_sync(track) for track in old))
        self.assertIs(studio.export_timeline(self.raw, "a", old), self.raw)
        self.assertIs(studio.export_timeline(self.raw, "a", deepcopy(self.fresh["tracks"])), self.raw)
        # Without the migration the unedited old project would be refused.
        with self.assertRaisesRegex(ValueError, "which native clip fields are editable"):
            studio._rewrite_timeline(self.raw, self.fresh, {**self.fresh, "tracks": old})
        _, bloom = self.find(old, "LiveBloomClip")
        bloom["values"]["intensity"] = .45
        changed = studio.export_timeline(self.raw, "a", old)
        self.assertNotEqual(changed, self.raw)
        _, actual = self.find(studio.parse_timeline(changed, "a")["tracks"], "LiveBloomClip")
        self.assertAlmostEqual(actual["values"]["intensity"], .45, places=6)

    def test_new_fields_export_and_parse_back(self):
        tracks = deepcopy(self.fresh["tracks"])
        coloring_track, _ = self.find(tracks, "LiveColoringClip", "/LED_panel_01")
        observed = {item["values"]["textureIndex"] for item in coloring_track["events"]}
        self.assertEqual(observed, {0, 5})
        coloring = next(item for item in coloring_track["events"] if item["values"]["textureIndex"] == 0)
        coloring["values"]["textureIndex"] = 5
        _, prop = self.find(tracks, "LivePropAmbientClip")
        prop["values"]["color"] = {"r": 2.0, "g": 1.0, "b": .5, "a": prop["values"]["color"]["a"]}
        prop["values"]["colorSpecifiedType"] = 1
        _, rim = self.find(tracks, "LivePropRimlightClip")
        rim["values"]["direction"] = {"x": 10.0, "y": -5.0, "z": 0.0}
        rim["values"]["sharpness"] = 12.5
        _, scaling = self.find(tracks, "LiveMemberScalingClip")
        scaling["values"]["intensity"] = .8
        _, dof = self.find(tracks, "LiveDepthOfFieldClip")
        dof_before = deepcopy(dof["values"])
        dof["values"].update(kernelSize=3, bodyPart=2 if dof_before["bodyPart"] != 2 else 0)
        _, flash = self.find(tracks, "LiveFlashLightClip")
        flash["values"]["status"] = 2
        edited = {item["id"]: item for item in (coloring, prop, rim, scaling, dof, flash)}

        changed = studio.export_timeline(self.raw, "a", tracks)
        current = studio.parse_timeline(changed, "a")
        before = {item["id"]: item for track in self.fresh["tracks"] for item in track["events"]}
        for track in current["tracks"]:
            for item in track["events"]:
                if item["id"] not in edited:
                    self.assertEqual(item, before[item["id"]])
                    continue
                wanted = edited[item["id"]]["values"]
                for field, value in wanted.items():
                    if isinstance(value, float):
                        self.assertAlmostEqual(item["values"][field], value, places=5, msg=field)
                    elif isinstance(value, dict) and field in ("color", "direction"):
                        for axis, number in value.items():
                            self.assertAlmostEqual(item["values"][field][axis], number, places=5, msg=field)
                    else:
                        self.assertEqual(item["values"][field], value, field)

    def test_unobserved_and_out_of_range_values_are_refused(self):
        def revised(native, label=None, **values):
            tracks = deepcopy(self.fresh["tracks"])
            _, item = self.find(tracks, native, label)
            item["values"].update(values)
            return tracks

        with self.assertRaisesRegex(ValueError, "already uses for 'textureIndex'"):
            studio.export_timeline(self.raw, "a", revised("LiveColoringClip", "/LED_panel_01", textureIndex=3))
        for tracks, message in [
                (revised("LiveDepthOfFieldClip", bodyPart=4), "already uses for 'bodyPart'"),
                (revised("LiveMemberScalingClip", intensity=1.5), "invalid intensity"),
                (revised("LiveDepthOfFieldClip", kernelSize=4), "outside the supported native range"),
                (revised("LiveFlashLightClip", status=3), "outside the supported native range"),
                (revised("LiveRimlightClip", colorSpecifiedType=3), "outside the supported native range"),
                (revised("LiveRimlightClip", memberPosition=2), "read-only")]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                studio._rewrite_timeline(self.raw, self.fresh, {**self.fresh, "tracks": tracks})


if __name__ == "__main__":
    unittest.main()
