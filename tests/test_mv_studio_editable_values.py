"""Editable MV timeline values: the whitelist, its export guards and the editableValues migration.

Original game samples are optional (ELICHIKA_STUDIO_TIMELINE_DIR with a-1203503-live_timeline.unity; every
other *timeline*.unity there is checked against the inspector's bounds too)."""
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
        controls = {"number", "slider", "vector", "color", "enum", "enum-observed", "enum-members", "member-slot",
                    "member-colors", "bool-int", "text", "facial-index", "readonly"}
        for native, fields in table.items():
            for field, spec in fields.items():
                self.assertIn(spec["control"], controls, f"{native}.{field}")
                if "set" in spec:
                    self.assertIn(spec["set"], sets)
                if field not in studio._EDITABLE_VALUES.get(native, set()):
                    self.assertEqual(spec["control"], "readonly", f"{native}.{field} is not exportable")

    def test_member_positions_pick_a_member_slot_and_float_ranges_match_their_boxes(self):
        table = descriptors()["classes"]
        for native, field in studio._MEMBER_POSITIONS:
            with self.subTest(native=native, field=field):
                self.assertIn(field, studio._EDITABLE_VALUES[native])
                self.assertEqual((table[native][field]["control"], table[native][field]["member"]), ("member-slot", True))
        slots = {(native, field) for native, fields in table.items() for field, spec in fields.items()
                 if spec["control"] == "member-slot"}
        self.assertEqual(slots, set(studio._MEMBER_POSITIONS))
        for (native, field), (low, high) in studio._FLOAT_RANGES.items():
            spec = table[native][field]
            with self.subTest(native=native, field=field):
                self.assertIn(spec["control"], ("number", "slider"))
                self.assertEqual((spec["min"], spec["max"]), (low, high))

    def test_member_targets_and_ranges_are_refused_outside_them(self):
        for native, field, good, bad in [("LiveDepthOfFieldClip", "cameraAutoDistanceMode", 2, 3),
                                         ("LiveBaseLightClip", "ambientColorType", 1, 3),
                                         ("LiveBaseLightClip", "rimlightColorType", 2, -1)]:
            with self.subTest(native=native, field=field):
                tree = {field: 0}
                studio._set_playable_value(tree, native, field, good)
                self.assertEqual(tree[field], good)
                with self.assertRaisesRegex(ValueError, "outside the supported native range"):
                    studio._set_playable_value(tree, native, field, bad)
        for native, field in (("LiveDepthOfFieldClip", "memberPosition"), ("LiveCameraOffsetClip", "memberPosition"),
                              ("LiveFlareClip", "memberPosition"), ("LiveBaseLightClip", "rimlightMemberPosition")):
            with self.subTest(native=native, field=field):
                tree = {field: 1}
                studio._set_playable_value(tree, native, field, 12)
                self.assertEqual(tree[field], 12)
                for bad in (0, 13, 2.0, True):
                    with self.assertRaisesRegex(ValueError, r"^Choose a member this MV has\.$"):
                        studio._set_playable_value(tree, native, field, bad)
        tree = {"focusTransitionTime": 1.0}
        studio._set_playable_value(tree, "LiveDepthOfFieldClip", "focusTransitionTime", 2.5)
        self.assertEqual(tree["focusTransitionTime"], 2.5)
        for bad in (-.5, 61.0):
            with self.assertRaisesRegex(ValueError, "invalid focusTransitionTime"):
                studio._set_playable_value(tree, "LiveDepthOfFieldClip", "focusTransitionTime", bad)

    def test_penlight_motion_ranges_and_palette(self):
        tree = {"swingMode": 1, "basicYZMoveY": .5, "growthYZSwingBottomZ": .8, "basicYZSwingPowerZ": 4.,
                "position": {"x": 0., "y": -.4, "z": 0.}}
        for mode in range(5):
            studio._set_playable_value(tree, "LivePenlightClip", "swingMode", mode)
        self.assertEqual(tree["swingMode"], 4)
        for bad in (5, -1, 1.0):
            with self.assertRaisesRegex(ValueError, "outside the supported native range"):
                studio._set_playable_value(tree, "LivePenlightClip", "swingMode", bad)
        for field, good, bad in (("basicYZMoveY", -10, 10.5), ("growthYZSwingBottomZ", .99, 1.0),
                                 ("growthYZSwingBottomZ", .01, 0.0), ("basicYZSwingPowerZ", 0, -.1)):
            with self.subTest(field=field):
                studio._set_playable_value(tree, "LivePenlightClip", field, good)
                self.assertEqual(tree[field], good)
                with self.assertRaisesRegex(ValueError, f"invalid {field}"):
                    studio._set_playable_value(tree, "LivePenlightClip", field, bad)
        studio._set_playable_value(tree, "LivePenlightClip", "position", {"x": 1., "y": 0., "z": -2.})
        self.assertEqual(tree["position"], {"x": 1., "y": 0., "z": -2.})
        self.assertNotIn("growthYZSwingPowerY", studio._EDITABLE_VALUES["LivePenlightClip"])

        def entry(slot, kind=1, color=None):
            return {"color": color or {"r": 1., "g": 1., "b": 1., "a": 1.}, "colorSpecifiedType": kind, "memberPosition": slot}

        palette = {"memberColors": [entry(1), entry(2), entry(0, 0)]}
        revised = [entry(2, 2), entry(2), entry(0, 0, {"r": 2., "g": .5, "b": 0., "a": 1.})]
        studio._set_playable_value(palette, "LivePenlightClip", "memberColors", deepcopy(revised))
        self.assertEqual(palette["memberColors"], revised)
        for bad, message in (([entry(1)], "length and fields"), ([*revised, entry(3)], "length and fields"),
                             ([{**entry(1), "extra": 1}, entry(2), entry(0, 0)], "length and fields"),
                             ([entry(1, 3), entry(2), entry(0, 0)], "colorSpecifiedType"),
                             ([entry(13), entry(2), entry(0, 0)], "Choose a member this MV has"),
                             ([entry(1, True), entry(2), entry(0, 0)], "colorSpecifiedType"),
                             ("x", "length and fields")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                studio._set_playable_value(deepcopy(palette), "LivePenlightClip", "memberColors", bad)
        # An unchanged entry keeps its stock value (slot 0 here) as it is.
        self.assertEqual(palette["memberColors"][2]["memberPosition"], 0)

    def test_the_track_mute_note_data_is_the_export_rule(self):
        rule = descriptors()["trackMute"]
        self.assertEqual(rule["notes"], {"group": studio.GROUP_MUTE, "quality": studio.QUALITY_MUTE})
        self.assertEqual({root: set(names) for root, names in rule["qualityRoots"].items()},
                         {root: set(names) for root, names in studio._QUALITY_CATEGORIES.items()})

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

    def test_a_changed_member_position_must_be_a_performer_slot(self):
        bound = deepcopy(self.original)
        for slot in (1, 2, 3):
            bound["tracks"].append({"id": f"dance{slot}", "kind": "dance", "nativeClass": "AnimationTrack", "label": f"d{slot}",
                                    "binding": f"/EntryPoint/Live/Members/Member{slot}/Model", "events": []})
        self.assertEqual(studio.performer_slots(bound["tracks"]), {1, 2, 3})
        self.assertEqual(studio.performer_slots([{"bindings": ["/EntryPoint/Live/Members/Member4/Model", "/x"]}, None]), {4})

        def revise(event_id, **values):
            revised = deepcopy(bound)
            for track in revised["tracks"]:
                for item in track["events"]:
                    if item["id"] == event_id:
                        item["values"].update(values)
            return revised

        studio._check_values(bound, revise("dof:0", memberPosition=3))
        studio._check_values(bound, revise("rim:0", memberPosition=2, colorSpecifiedType=1))
        for value in (4, 0, 2.0, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r"^Choose a member this MV has\.$"):
                studio._check_values(bound, revise("dof:0", memberPosition=value))
        # Without performer bindings no slot can be chosen; the unchanged value is never judged.
        with self.assertRaisesRegex(ValueError, "Choose a member this MV has"):
            studio._check_values(self.original, self.revise("dof:0", memberPosition=2))
        studio._check_values(self.original, self.revise("dof:0", memberPosition=1))
        # A member colour or focus follows the revised member position.
        studio._check_values(bound, revise("rim:1", memberPosition=1, colorSpecifiedType=2))
        studio._check_values(bound, revise("dof:1", memberPosition=2, useMemberDistance=1))
        with self.assertRaisesRegex(ValueError, "member position to be 1 to 12"):
            studio._check_values(bound, revise("rim:2", colorSpecifiedType=1))

    def test_base_light_colour_sources_follow_their_own_member_positions(self):
        # LiveBaseLightClip has two colour sources, each with its own member position field.
        light = {"ambientColorType": 0, "ambientMemberPosition": 0, "rimlightColorType": 0, "rimlightMemberPosition": 0}
        original = timeline(("base", [event("base:0", "LiveBaseLightClip", light)]))
        original["tracks"].extend({"id": f"d{slot}", "kind": "dance", "nativeClass": "AnimationTrack", "label": f"d{slot}",
                                   "binding": f"/EntryPoint/Live/Members/Member{slot}/Model", "events": []} for slot in (1, 2, 3))

        def revise(**values):
            revised = deepcopy(original)
            revised["tracks"][0]["events"][0]["values"].update(values)
            return revised

        for kind in (1, 2):
            with self.subTest(kind=kind):
                studio._check_values(original, revise(ambientColorType=kind, ambientMemberPosition=3))
                studio._check_values(original, revise(rimlightColorType=kind, rimlightMemberPosition=2))
                # Each source reads its own position: the other source's slot does not count.
                with self.assertRaisesRegex(ValueError, r"^This colour source needs the clip's member position to be 1 to 12\.$"):
                    studio._check_values(original, revise(ambientColorType=kind, rimlightMemberPosition=2))
                with self.assertRaisesRegex(ValueError, "member position to be 1 to 12"):
                    studio._check_values(original, revise(rimlightColorType=kind, ambientMemberPosition=3))
                with self.assertRaisesRegex(ValueError, "member position to be 1 to 12"):
                    studio._check_values(original, revise(ambientColorType=kind))
                with self.assertRaisesRegex(ValueError, "member position to be 1 to 12"):
                    studio._check_values(original, revise(rimlightColorType=kind))
        studio._check_values(original, revise(ambientColorType=0, rimlightColorType=0))
        with self.assertRaisesRegex(ValueError, r"^Choose a member this MV has\.$"):
            studio._check_values(original, revise(ambientColorType=1, ambientMemberPosition=4))
        with self.assertRaisesRegex(ValueError, "Choose a member this MV has"):
            studio._check_values(original, revise(rimlightColorType=1, rimlightMemberPosition=4))

    def test_a_penlight_palette_entry_names_a_performer_slot(self):
        def entry(slot, kind=1):
            return {"color": {"r": 1., "g": 1., "b": 1., "a": 1.}, "colorSpecifiedType": kind, "memberPosition": slot}

        original = timeline(("crowd", [event("crowd:0", "LivePenlightClip", {"memberColors": [entry(1), entry(2), entry(0, 0)]})]))
        original["tracks"].extend({"id": f"d{slot}", "kind": "dance", "nativeClass": "AnimationTrack", "label": f"d{slot}",
                                   "binding": f"/EntryPoint/Live/Members/Member{slot}/Model", "events": []} for slot in (1, 2))

        def revise(*entries):
            revised = deepcopy(original)
            revised["tracks"][0]["events"][0]["values"]["memberColors"] = list(entries)
            return revised

        studio._check_values(original, revise(entry(2), entry(1), entry(0, 0)))
        studio._check_values(original, revise(entry(1, 0), entry(2, 2), entry(0, 0)))
        with self.assertRaisesRegex(ValueError, "Choose a member this MV has"):
            studio._check_values(original, revise(entry(3), entry(2), entry(0, 0)))
        with self.assertRaisesRegex(ValueError, "member position to be 1 to 12"):
            studio._check_values(original, revise(entry(1), entry(2), entry(0, 1)))
        # Malformed palettes are left to the export's own check.
        studio._check_values(original, revise(entry(1)))
        studio._check_values(original, revise("x", entry(2), entry(0, 0)))

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

    def test_shared_playables_never_need_a_sync(self):
        # The parser lists no value field for a playable that more than one clip references.
        timing = ["clipIn"]
        shared = [event("s:0", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, timing),
                  event("s:1", "LiveColoringClip", {"textureIndex": 0, "shift": 0}, timing)]
        shared[1]["values"]["asset"] = shared[0]["values"]["asset"]
        same_track = {"id": "s", "kind": "stage", "events": shared}
        self.assertEqual(studio.shared_playables([same_track]), {"cab:s:0"})
        self.assertFalse(studio.needs_editable_values_sync(same_track))
        # Across tracks only the whole project tells.
        first = {"id": "a", "kind": "stage", "events": [shared[0]]}
        second = {"id": "b", "kind": "stage", "events": [deepcopy(shared[1])]}
        self.assertTrue(studio.needs_editable_values_sync(first))
        project = studio.shared_playables([first, second])
        self.assertFalse(any(studio.needs_editable_values_sync(track, project) for track in (first, second)))
        # An unshared clip saved with an older list still needs one, beside a shared playable.
        old = event("s:2", "LivePropAmbientClip", {"color": {"r": 1, "g": 1, "b": 1, "a": 1}}, timing)
        self.assertTrue(studio.needs_editable_values_sync({**same_track, "events": [*shared, old]}))
        for value in (None, [None, {"events": [None, {"values": {"asset": 3}}, {"values": {"asset": {}}}]}]):
            self.assertEqual(studio.shared_playables(value), frozenset())
        self.assertFalse(studio.needs_editable_values_sync(
            {"events": [{"values": {"asset": {}, "playableClass": "LiveColoringClip"}, "editableValues": []}]}))

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
            # Nor does one whose only listless clips play a shared playable (on two tracks here).
            project["tracks"] = deepcopy(self.fresh)
            twin = deepcopy(project["tracks"][0]["events"][0])
            twin.update(id="u:0", editableValues=["clipIn"])
            project["tracks"][1]["events"] = [twin]
            project["tracks"][0]["events"][0]["editableValues"] = ["clipIn"]
            saved = mv_studio.save(mv_studio._register(project, native))
            with ZipFile(saved["path"]) as archive, patch("webtools.core.mv_studio_timeline.parse_timeline") as parse:
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
            parse.assert_not_called()
            self.assertEqual(reopened["tracks"], project["tracks"])


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
                (revised("LiveRimlightClip", memberPosition=2), "Choose a member this MV has"),
                (revised("LiveDepthOfFieldClip", cameraAutoDistanceMode=3), "outside the supported native range")]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                studio._rewrite_timeline(self.raw, self.fresh, {**self.fresh, "tracks": tracks})


def group_sample():
    """(path, raw, parse) of the first sample timeline with several performer slots and a DOF clip that
    can take a member target, or None."""
    for path in sample_timelines():
        raw = path.read_bytes()
        parsed = studio.parse_timeline(raw, path.name)
        if len(studio.performer_slots(parsed["tracks"])) > 1 and any(
                "memberPosition" in item["editableValues"] and "cameraAutoDistanceMode" in item["editableValues"]
                for track in parsed["tracks"] for item in track["events"]):
            return path, raw, parsed
    return None


class GroupMemberTests(unittest.TestCase):
    """Member targets of a group MV on a real timeline (11054 here): export, parse back, Elichika's validator."""

    @classmethod
    def setUpClass(cls):
        cls.sample = group_sample()
        if cls.sample is None:
            raise unittest.SkipTest("No original group MV timeline sample")

    def test_member_targets_export_parse_back_and_pass_the_install_validator(self):
        path, raw, parsed = self.sample
        slots = sorted(studio.performer_slots(parsed["tracks"]))
        tracks = deepcopy(parsed["tracks"])
        edited = {}
        for track in tracks:
            for item in track["events"]:
                values, native = item["values"], item["values"].get("playableClass")
                if native == "LiveDepthOfFieldClip" and "cameraAutoDistanceMode" in item["editableValues"] and not edited.get("dof"):
                    values["memberPosition"] = next(slot for slot in slots if slot != values["memberPosition"])
                    values["cameraAutoDistanceMode"] = 1
                    edited["dof"] = item
                elif native == "LiveCameraOffsetClip" and "memberPosition" in item["editableValues"] and not edited.get("offset"):
                    values["memberPosition"] = slots[-1] if values["memberPosition"] != slots[-1] else slots[0]
                    edited["offset"] = item
                elif native in studio._COLOR_SOURCE_CLASSES and "memberPosition" in item["editableValues"] and not edited.get("colour"):
                    values["memberPosition"] = slots[1] if values["memberPosition"] != slots[1] else slots[0]
                    values["colorSpecifiedType"] = 1
                    edited["colour"] = item
        self.assertEqual(sorted(edited), ["colour", "dof", "offset"], path.name)
        output = studio.export_timeline(raw, path.name, tracks)
        again = studio.parse_timeline(output, path.name)["tracks"]
        self.assertEqual(again, tracks)
        try:
            import UnityPy
            import mv_studio_native_assets as native
        except ImportError:
            return
        platform = int(list(UnityPy.load(raw).assets)[0].target_platform)
        import time
        native._validate_timeline(output, raw, platform, time.monotonic() + 120)

    def test_a_project_saved_before_the_member_targets_exports_unchanged(self):
        path, raw, parsed = self.sample
        added = {"memberPosition", "cameraAutoDistanceMode", "focusTransitionTime", "ambientColorType", "rimlightColorType",
                 "ambientMemberPosition", "rimlightMemberPosition"}
        old = deepcopy(parsed["tracks"])
        for track in old:
            for item in track["events"]:
                item["editableValues"] = [field for field in item["editableValues"] if field not in added]
        self.assertNotEqual(old, parsed["tracks"])
        self.assertTrue(any(studio.needs_editable_values_sync(track) for track in old))
        self.assertIs(studio.export_timeline(raw, path.name, old), raw)

    def test_a_member_the_mv_does_not_have_is_refused(self):
        path, raw, parsed = self.sample
        tracks = deepcopy(parsed["tracks"])
        item = next(item for track in tracks for item in track["events"] if "memberPosition" in item["editableValues"])
        item["values"]["memberPosition"] = max(studio.performer_slots(parsed["tracks"])) + 1
        with self.assertRaisesRegex(ValueError, "Choose a member this MV has"):
            studio.export_timeline(raw, path.name, tracks)


class BaseLightTests(unittest.TestCase):
    """Base light colour sources on a real timeline (12056 here): export, parse back, Elichika's validator."""

    FIELDS = ("ambientColorType", "ambientMemberPosition", "rimlightColorType", "rimlightMemberPosition")

    @classmethod
    def setUpClass(cls):
        for path in sample_timelines():
            raw = path.read_bytes()
            parsed = studio.parse_timeline(raw, path.name)
            if len(studio.performer_slots(parsed["tracks"])) >= 3 and any(
                    set(cls.FIELDS) <= set(item["editableValues"]) for track in parsed["tracks"] for item in track["events"]):
                cls.sample = path, raw, parsed
                return
        raise unittest.SkipTest("No original timeline sample with an editable base light clip and three members")

    def test_member_colour_sources_export_parse_back_and_pass_the_install_validator(self):
        path, raw, parsed = self.sample
        slots = sorted(studio.performer_slots(parsed["tracks"]))
        tracks = deepcopy(parsed["tracks"])
        clip = next(item for track in tracks for item in track["events"] if set(self.FIELDS) <= set(item["editableValues"]))
        clip["values"].update(ambientColorType=2, ambientMemberPosition=slots[2], rimlightColorType=1,
                              rimlightMemberPosition=slots[1])
        output = studio.export_timeline(raw, path.name, tracks)
        self.assertEqual(studio.parse_timeline(output, path.name)["tracks"], tracks)
        try:
            import UnityPy
            import mv_studio_native_assets as native
        except ImportError:
            return
        import time
        platform = int(list(UnityPy.load(raw).assets)[0].target_platform)
        native._validate_timeline(output, raw, platform, time.monotonic() + 120)


class PenlightTests(unittest.TestCase):
    """Penlight crowd motion on a real timeline (12035 here): export, parse back, Elichika's validator."""

    @classmethod
    def setUpClass(cls):
        for path in sample_timelines():
            raw = path.read_bytes()
            parsed = studio.parse_timeline(raw, path.name)
            if any("memberColors" in item["editableValues"] for track in parsed["tracks"] for item in track["events"]):
                cls.sample = path, raw, parsed
                return
        raise unittest.SkipTest("No original timeline sample with an editable penlight clip")

    def test_motion_fields_export_parse_back_and_pass_the_install_validator(self):
        path, raw, parsed = self.sample
        slots = sorted(studio.performer_slots(parsed["tracks"]))
        tracks = deepcopy(parsed["tracks"])
        clip = next(item for track in tracks for item in track["events"] if "memberColors" in item["editableValues"])
        values = clip["values"]
        values["swingMode"] = 4 if values["swingMode"] != 4 else 2
        values["basicXMoveX"] = .45
        values["growthYZSwingBottomZ"] = .6
        values["position"] = {**values["position"], "z": values["position"]["z"] - 1.5}
        colors = deepcopy(values["memberColors"])
        colors[0] = {**colors[0], "color": {"r": 2., "g": .25, "b": .5, "a": 1.}, "colorSpecifiedType": 0,
                     "memberPosition": slots[-1]}
        values["memberColors"] = colors
        output = studio.export_timeline(raw, path.name, tracks)
        again = {item["id"]: item for track in studio.parse_timeline(output, path.name)["tracks"] for item in track["events"]}
        got = again[clip["id"]]["values"]
        self.assertEqual((got["swingMode"], got["memberColors"][0]["colorSpecifiedType"],
                          got["memberColors"][0]["memberPosition"]), (values["swingMode"], 0, slots[-1]))
        for field in ("basicXMoveX", "growthYZSwingBottomZ"):
            self.assertAlmostEqual(got[field], values[field], places=6)
        self.assertAlmostEqual(got["position"]["z"], values["position"]["z"], places=5)
        self.assertAlmostEqual(got["memberColors"][0]["color"]["g"], .25, places=6)
        try:
            import UnityPy
            import mv_studio_native_assets as native
        except ImportError:
            return
        import time
        platform = int(list(UnityPy.load(raw).assets)[0].target_platform)
        native._validate_timeline(output, raw, platform, time.monotonic() + 120)

    def test_a_project_saved_before_the_motion_fields_exports_unchanged(self):
        path, raw, parsed = self.sample
        added = set(studio._EDITABLE_VALUES["LivePenlightClip"]) - {
            "tintColor", "fogIntensity", "randomBrightness", "beatLength", "beatOffset", "randomDelay", "randomUp",
            "randomSwingIntensity"}
        old = deepcopy(parsed["tracks"])
        for track in old:
            for item in track["events"]:
                if item["values"].get("playableClass") == "LivePenlightClip":
                    item["editableValues"] = [field for field in item["editableValues"] if field not in added]
        self.assertNotEqual(old, parsed["tracks"])
        self.assertIs(studio.export_timeline(raw, path.name, old), raw)


class ServerGuardMessageTests(unittest.TestCase):
    """The export guards reach the page in its language: the server translates them for ?lang=."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        import threading
        from webtools.server import Handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def post(self, language, refusal):
        import http.client
        with patch.object(mv_studio, "export_timeline", side_effect=refusal) as export:
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
            self.addCleanup(connection.close)
            connection.request("POST", "/api/mv-studio/export-timeline?lang=" + language,
                               json.dumps({"project": {"name": "Guarded"}}), {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = json.load(response)
        export.assert_called_once_with({"name": "Guarded"})
        return response.status, body

    def test_guard_messages_are_translated_for_the_requested_language(self):
        original = timeline(("coloring", [
            event("coloring:0", "LiveColoringClip", {"textureIndex": 0}, ["textureIndex"]),
            event("coloring:1", "LiveColoringClip", {"textureIndex": 5}, ["textureIndex"])]))
        revised = deepcopy(original)
        revised["tracks"][0]["events"][0]["values"]["textureIndex"] = 3

        def refuse(_project):
            studio._check_values(original, revised)  # The real guard and its exact message.
            raise AssertionError("the guard accepted an unobserved textureIndex")

        message = "Choose a value this MV already uses for 'textureIndex'."
        for language, wanted in (("ko", "이 MV에서 이미 쓰는 'textureIndex' 값 중에서 고르세요."),
                                 ("ja", "このMVですでに使われている'textureIndex'の値から選んでください。"),
                                 ("en", message), ("xx", message)):
            with self.subTest(language=language):
                self.assertEqual(self.post(language, refuse), (400, {"error": wanted}))
        slot = "Member focus needs the clip's member position to be 1 to 12."
        self.assertEqual(self.post("ko", ValueError(slot)), (400, {"error": "멤버에 초점을 맞추려면 클립의 멤버 위치가 1~12여야 합니다."}))
        # A message without a translation is sent as it is.
        self.assertEqual(self.post("ko", ValueError("Some other refusal.")), (400, {"error": "Some other refusal."}))

    def test_every_range_refusal_has_korean_and_japanese(self):
        from webtools import i18n
        bounded = [(native, field, "int", bounds[1] + 1) for (native, field), bounds in studio._LIMITED_VALUES.items()]
        bounded += [(native, field, "float", bounds[1] + 1.) for (native, field), bounds in studio._FLOAT_RANGES.items()]
        for native, field, kind, value in bounded:
            with self.subTest(field=field):
                with self.assertRaises(ValueError) as caught:  # The real guard and its exact message.
                    studio._set_playable_value({field: 0 if kind == "int" else 0.}, native, field, value)
                message = str(caught.exception)
                self.assertEqual(message, f"'{field}' is outside the supported native range." if kind == "int"
                                 else f"The timeline has an invalid {field}.")
                for language in ("ko", "ja"):
                    translated = i18n.tr(message, language)
                    self.assertNotEqual(translated, message, language)
                    self.assertIn(f"'{field}'", translated)


def sample_timelines():
    """Every original timeline bundle in ELICHIKA_STUDIO_TIMELINE_DIR (choreography bundles excluded)."""
    if not SAMPLES.is_dir():
        return []
    return sorted(path for path in SAMPLES.glob("*timeline*.unity") if "choreography" not in path.name)


@unittest.skipUnless(sample_timelines(), "Original game samples are optional")
class SampleTimelineTests(unittest.TestCase):
    # colorControl and vectorControl bound their number boxes with these (mv-studio-event-fields.js).
    CHANNELS = (0, 1000)
    AXES = (-1000000, 1000000)

    @classmethod
    def setUpClass(cls):
        cls.parsed = {path.name: studio.parse_timeline(path.read_bytes(), path.name)["tracks"] for path in sample_timelines()}

    def test_a_fresh_parse_never_needs_a_sync(self):
        for name, tracks in self.parsed.items():
            shared = studio.shared_playables(tracks)
            self.assertEqual([track["id"] for track in tracks if studio.needs_editable_values_sync(track, shared)], [], name)

    def test_inspector_bounds_hold_every_native_value(self):
        """A native value outside its box's bounds would be clamped on the first edit and could not be typed back."""
        table = descriptors()["classes"]
        outside = []
        for name, tracks in self.parsed.items():
            for track in tracks:
                for item in track["events"]:
                    values = item["values"]
                    specs = table.get(values.get("playableClass"), {})
                    for field in item["editableValues"]:
                        spec, value = specs.get(field), values.get(field)
                        if spec is None:
                            continue
                        if spec["control"] in ("number", "slider") and "min" in spec:
                            numbers, (low, high) = [value], (spec["min"], spec["max"])
                        elif spec["control"] == "color" and isinstance(value, dict):
                            numbers, (low, high) = list(value.values()), self.CHANNELS
                        elif spec["control"] == "vector" and isinstance(value, dict):
                            numbers, (low, high) = list(value.values()), self.AXES
                        else:
                            continue
                        for number in numbers:
                            if isinstance(number, (int, float)) and not low <= number <= high:
                                outside.append(f"{name} {item['id']} {values['playableClass']}.{field}={number} "
                                               f"outside [{low}, {high}]")
        self.assertEqual(outside, [])


if __name__ == "__main__":
    unittest.main()
