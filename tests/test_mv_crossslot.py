"""Another MV slot, MV timeline packs and the MV timeline platform conversion.

- webtools/core/mv_timeline_platform.py: convert_timeline on the synthetic root of the registration
  tests (JSON stand-in timelines) and, when real timelines are at hand, an Android -> iOS -> Android
  round trip of an edited real 12035 timeline (MV_TIMELINE_SAMPLES or ELICHIKA_STUDIO_TIMELINE_DIR
  holding a-1203503-live_timeline.unity and i-1203503-live_timeline.unity).
- webtools/core/mv_studio_apply.py: plan, apply and restore for another slot against a fake Elichika
  store with the cross-slot arguments (source_asset_id, stage).
- webtools/core/mv_studio_pack.py and tools/mv_timeline.py against a fake mv_timeline_pack.
No game data is stored in this file.
"""
import copy
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
for folder in (REPO, REPO / "tests"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import test_mv_studio_register as reg_tests  # noqa: E402
from webtools.core import mv_studio, mv_studio_apply as apply, mv_studio_register as register  # noqa: E402
from webtools.core import mv_studio_pack, mv_studio_timeline, mv_timeline_platform as conversion  # noqa: E402

mv_studio_live = reg_tests.mv_studio_live
NEEDS_STORE = reg_tests.NEEDS_STORE
FakeJob = reg_tests.FakeJob
timeline_bytes = reg_tests.timeline_bytes


def _samples():
    for value in (os.environ.get("MV_TIMELINE_SAMPLES"), os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR")):
        if value and all((Path(value) / f"{p}-1203503-live_timeline.unity").is_file() for p in "ai"):
            return Path(value)
    return None


SAMPLES = _samples()
STAGE_2101 = {"live_stage_master_id": 101, "stage_effect_asset_path": "E2101", "live_prop_skeleton_asset_path": None,
              "quality_setitng_set_id": 3, "shader_variant_asset_path": None}


class FakeStore:
    """Elichika's stock MV store with the cross-slot arguments, on the synthetic GL root (assets 2101, 2201)."""

    def __init__(self, *, cross=True, regions=("gl",)):
        self.calls, self.overrides, self.originals, self.regions = [], {}, [], regions
        self.checks, self.refuse_stage = [], {}  # refuse_stage: {region: message} for a stage the region lacks
        if not cross:
            self.apply_mv_timeline = self._legacy_apply

    def describe_mv_timeline(self, repo_root, *, region, asset_id):
        if region not in self.regions or asset_id not in (2101, 2201):
            raise ValueError("The selected MV has no 3D timeline in this region.")
        record = self.overrides.get((region, asset_id))
        source = record.get("source") if record else None
        return {"assetId": asset_id, "region": region, "stockKey": f"A{asset_id}",
                "timelineKey": record["key"] if record else f"A{asset_id}", "override": record is not None,
                "platforms": {p: "custom" if record and isinstance(record["timelines"].get(p), bytes) else "stock"
                              for p in ("android", "ios")},
                "revision": 1 if record else 0, "updatedAt": None, "fingerprints": {},
                "lives": [21] if asset_id == 2101 else [22], "song": False,
                "source": {"assetId": source, "stockKey": f"A{source}"} if source else None,
                **({"stage": {"current": record.get("stage"), "stock": record["stockStage"], "changed": True}}
                   if record and record.get("stockStage") else {})}

    def validate_mv_timelines(self, repo_root, *, region, asset_id, timelines, originals=None, source_asset_id=None,
                              stage="keep"):
        # ("validate", region, the asset whose stock checks the payloads, platforms); ``checks`` has the rest.
        self.calls.append(("validate", region, source_asset_id or asset_id, sorted(timelines)))
        self.checks.append((region, asset_id, source_asset_id, stage))
        self.originals.append(("validate", region, dict(originals or {})))
        if self.refuse_stage and isinstance(stage, dict) and region in self.refuse_stage:
            raise ValueError(self.refuse_stage[region])
        return {"assetId": asset_id, "validated": sorted(timelines)}

    def apply_mv_timeline(self, repo_root, *, region, asset_id, timelines, expected_key, originals=None, fingerprints=None,
                          backup=True, log=print, source_asset_id=None, stage="keep"):
        if expected_key != self.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)["timelineKey"]:
            raise ValueError("stale")
        self.calls.append(("apply", region, asset_id, source_asset_id, stage, dict(timelines)))
        self.originals.append(("apply", region, dict(originals or {})))
        self.overrides[(region, asset_id)] = {"key": "X1", "stage": stage, "timelines": dict(timelines),
                                              "source": source_asset_id}
        return {"changed": True, "parts": sorted(timelines), "backup": "/backup", "warnings": [],
                "timeline": self.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)}

    def _legacy_apply(self, repo_root, *, region, asset_id, timelines, expected_key, originals=None, fingerprints=None,
                      backup=True, log=print):
        raise AssertionError("not called")

    def restore_mv_timeline(self, repo_root, *, region, asset_id, expected_key, backup=True, log=print):
        self.calls.append(("restore", region, asset_id, expected_key))
        self.overrides.pop((region, asset_id))
        return {"changed": True, "parts": ["android", "ios"], "backup": "/backup", "warnings": [],
                "timeline": self.describe_mv_timeline(repo_root, region=region, asset_id=asset_id)}


# ---------------------------------------------------------------- platform conversion

class ConversionCase(reg_tests.Case):
    def edited_android(self, tracks=None):
        tracks = copy.deepcopy(tracks or reg_tests.base_tracks())
        tracks[1]["events"][0]["values"]["intensity"] = 2.5
        return timeline_bytes("android", tracks, tag="edited")

    def test_android_to_ios_keeps_every_track_and_uses_the_ios_stock(self):
        source = self.edited_android()
        output = conversion.convert_timeline(source, "android", "ios", "gl", 2101, root=self.root)
        document = json.loads(output[8:].rstrip(b" "))
        self.assertEqual(document["platform"], "ios")  # the iOS stock is the template
        self.assertEqual(document["tracks"], json.loads(source[8:].rstrip(b" "))["tracks"])
        back = conversion.convert_timeline(output, "ios", "android", "gl", 2101, root=self.root)
        self.assertEqual(json.loads(back[8:].rstrip(b" "))["tracks"], document["tracks"])
        # An unedited stock converts to the other platform's stock bytes exactly.
        self.assertEqual(conversion.convert_timeline(self.local["tl2101"], "android", "ios", "gl", 2101, root=self.root),
                         self.local["tl2101i"])

    def test_refusals(self):
        source = self.edited_android()
        cases = [((source, "android", "android", "gl", 2101), conversion.SAME_PLATFORM),
                 ((self.local["tl2101i"], "android", "ios", "gl", 2101), conversion.WRONG_PLATFORM),
                 ((b"nope", "android", "ios", "gl", 2101), conversion.NOT_TIMELINE),
                 ((source, "android", "ios", "gl", 9999), conversion.NO_ASSET),
                 ((source, "android", "ios", "kr", 2101), conversion.REGION),
                 ((source, "pc", "ios", "gl", 2101), conversion.PLATFORM)]
        for arguments, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(message)):
                conversion.convert_timeline(*arguments, root=self.root)

    def test_content_the_export_cannot_carry_is_refused_not_dropped(self):
        tracks = reg_tests.base_tracks()
        tracks[1]["events"][0]["values"]["mixIn"] = [0, 0.5]  # not an editable value: the export cannot write it
        with self.assertRaises(conversion.ConversionError) as caught:
            conversion.convert_timeline(timeline_bytes("android", tracks), "android", "ios", "gl", 2101, root=self.root)
        self.assertEqual((str(caught.exception), caught.exception.labels), (conversion.LOSSY, ["StageEffect/Bloom"]))
        tracks = reg_tests.base_tracks()[:2]
        with self.assertRaises(conversion.ConversionError) as caught:
            conversion.convert_timeline(timeline_bytes("android", tracks), "android", "ios", "gl", 2101, root=self.root)
        self.assertEqual(str(caught.exception), conversion.NOT_THIS_ASSET)

    def test_a_template_that_needs_a_download(self):
        self.remote["tl2101i"] = self.local.pop("tl2101i")
        self.assertEqual(conversion.template_status(self.root, "gl", 2101, "ios"), {"status": "download",
                                                                                     "bytes": reg_tests.TIMELINE_SIZE})
        with self.assertRaisesRegex(ValueError, conversion.TEMPLATE_DOWNLOAD):
            conversion.convert_timeline(self.edited_android(), "android", "ios", "gl", 2101, root=self.root)
        output = conversion.convert_timeline(self.edited_android(), "android", "ios", "gl", 2101, root=self.root,
                                             download=True)
        self.assertEqual(json.loads(output[8:].rstrip(b" "))["platform"], "ios")
        # A template the caller already fetched (Elichika's installer shares one download) is not read again.
        self.loads.clear()
        again = conversion.convert_timeline(self.edited_android(), "android", "ios", "gl", 2101, root=self.root,
                                            template_bytes=self.remote["tl2101i"])
        self.assertEqual((again, self.loads), (output, []))

    def test_only_what_mv_studio_writes_passes_the_editor_bytes_check(self):
        stock, stock_ios = self.local["tl2101"], self.local["tl2101i"]
        edited = conversion.convert_parsed(self.edited_android(), stock)  # an edit exported onto the stock
        self.assertNotEqual(edited, stock)
        conversion.check_editor_bytes(stock, stock)  # the original itself
        conversion.check_editor_bytes(edited, stock)  # MV Studio's export onto the source's stock
        converted = conversion.convert_timeline(edited, "android", "ios", "gl", 2101, root=self.root)
        conversion.check_editor_bytes(converted, stock_ios)  # and its conversion
        document = json.loads(edited[8:].rstrip(b" "))
        tampered = [b"UnityFS\0" + json.dumps({**document, "hidden": [float("nan")]}, sort_keys=True).encode(),
                    edited + b"\0", b"UnityFS\0garbage", b"not a timeline", edited.replace(b'"edited"', b'"hand"')]
        for raw in tampered:
            with self.subTest(raw=raw[:24]), self.assertRaisesRegex(
                    ValueError, "^" + __import__("re").escape(conversion.NOT_EDITOR) + "$"):
                conversion.check_editor_bytes(raw, stock)
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(conversion.NOT_EDITOR) + "$"):
            conversion.check_editor_bytes(edited, stock_ios)  # checked against the other platform's stock

    def test_stage_bound_tracks(self):
        tracks = reg_tests.base_tracks() + [
            {"id": "g", "label": "StageEffect", "nativeClass": "GroupTrack", "events": []},
            {"id": "m", "label": "MemberMotion/Member1", "nativeClass": "AnimationTrack", "events": [],
             "binding": "/EntryPoint/Live/Members/Member1"},
            {"id": "s", "label": "Props/Lamp", "nativeClass": "AnimationTrack", "events": [],
             "binding": "/EntryPoint/Live/Stages/MainStage/Model/lamp"}]
        self.assertEqual(conversion.stage_bound_tracks(tracks), ["StageEffect/Bloom", "StageEffect/Ambient", "Props/Lamp"])


class NoIOSCatalogCase(reg_tests.Case):
    ios_timeline = False

    def test_no_template_in_the_catalog(self):
        with self.assertRaisesRegex(ValueError, conversion.NO_TEMPLATE):
            conversion.convert_timeline(self.local["tl2101"], "android", "ios", "gl", 2101, root=self.root)
        self.assertEqual(conversion.template_status(self.root, "gl", 2101, "ios"), {"status": "missing"})


@unittest.skipUnless(SAMPLES, "Real 12035 timelines (MV_TIMELINE_SAMPLES) are not available")
class RealSampleConversionTests(unittest.TestCase):
    """Android -> iOS -> Android of an edited real 12035 timeline with the real parser and native export."""

    def test_round_trip_of_an_edited_12035_timeline(self):
        android = (SAMPLES / "a-1203503-live_timeline.unity").read_bytes()
        ios = (SAMPLES / "i-1203503-live_timeline.unity").read_bytes()
        self.assertEqual(conversion.convert_parsed(android, ios), ios)  # unedited: the iOS stock exactly
        tracks = register._parse(android)["tracks"]
        bloom = next(event for track in tracks if track["nativeClass"] == "LiveBloomTrack" for event in track["events"]
                     if "intensity" in event["editableValues"])
        bloom["values"]["intensity"] = round(float(bloom["values"]["intensity"]) + 0.75, 3)
        camera = next(event for track in tracks if track["kind"] == "camera" for event in track["events"]
                      if "keyframes" in event["editableValues"])
        camera["start"] = round(camera["start"] + 0.05, 4)
        edited = mv_studio_timeline.export_timeline(android, "edited", tracks)
        self.assertNotEqual(edited, android)
        converted = conversion.convert_parsed(edited, ios)
        self.assertEqual(conversion.blob_platform(converted), "ios")
        self.assertEqual(register._parse(converted)["tracks"], register._parse(edited)["tracks"])
        self.assertEqual(conversion.convert_parsed(converted, android), edited)
        # The editor bytes check: MV Studio's outputs pass byte for byte; one flipped byte inside a clip
        # (which the parser does not see) fails.
        conversion.check_editor_bytes(edited, android)
        conversion.check_editor_bytes(converted, ios)
        flipped = bytearray(edited)
        flipped[len(flipped) // 2] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(conversion.NOT_EDITOR) + "$"):
            conversion.check_editor_bytes(bytes(flipped), android)


# ---------------------------------------------------------------- another MV slot

@NEEDS_STORE
class CrossSlotTests(reg_tests.Case):
    def setUp(self):
        super().setUp()
        self.store = FakeStore()
        patcher = mock.patch.object(register, "store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def imported(self, edit=True):
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        if edit:
            project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        return project

    def run_cross(self, project, plan, *, platforms=("android", "ios"), download=False, target=None):
        target = target or {"assetId": 2201, "stage": True}
        request = apply.validate_apply(self.root, {"mode": "all", "project": project, "platforms": list(platforms),
                                                   "download": download, "target": target,
                                                   "expected": {"key": plan["expected"]["key"],
                                                                "keys": plan["expected"]["keys"]}})
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=True):
            summary = apply.run_apply(job, self.root, request)
        return job, summary

    def test_plan_for_another_slot_with_its_stage(self):
        project = self.imported()
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": True})
        self.assertEqual(plan["blocked"], [])
        self.assertIsNone(plan["edits"])
        cross = plan["cross"]
        self.assertEqual((cross["assetId"], cross["stage"], cross["platform"], cross["supported"]), (2201, True, "android", True))
        gl = cross["regions"]["gl"]
        self.assertEqual((gl["available"], gl["key"], gl["restore"]), (True, "A2201", False))
        self.assertEqual(gl["stageAfter"], STAGE_2101)
        self.assertEqual(gl["stageNow"], {**STAGE_2101, "live_stage_master_id": 102, "stage_effect_asset_path": "E2201"})
        self.assertEqual(gl["lives"]["count"], 1)
        self.assertEqual(cross["stageBound"], {"count": 2, "labels": ["StageEffect/Bloom", "StageEffect/Ambient"]})
        self.assertEqual(plan["target"]["assetId"], 2201)
        self.assertEqual(plan["expected"], {"key": "A2201", "keys": {"gl": "A2201"}})
        self.assertEqual(plan["platforms"], {"android": {"payload": {"status": "project"}},
                                             "ios": {"payload": {"status": "local"}}})
        self.assertEqual((plan["all"]["download"], plan["all"]["missing"]), ([], []))
        self.assertEqual(plan["loaded"]["assetId"], 2101)
        # The loaded slot is the old plan (edits and apply all), not another slot.
        same = apply.plan(self.root, project, target={"assetId": 2101, "stage": True})
        self.assertIsNone(same["cross"])
        self.assertIsNotNone(same["edits"])

    def test_both_regions_and_an_old_store_are_blocked_in_the_plan(self):
        project = self.imported()
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": False, "regions": ["gl", "jp"]})
        self.assertIn({"message": apply.TARGET_MISSING, "values": {"asset": 2201, "region": "JP"}}, plan["blocked"])
        self.assertIsNone(plan["cross"]["regions"]["gl"]["stageAfter"])
        self.store.__init__(cross=False)
        plan = apply.plan(self.root, project, target={"assetId": 2201})
        self.assertEqual(plan["blocked"], [{"message": apply.NO_CROSS_STORE}])
        for bad in ({"assetId": 0}, {"assetId": 2201, "stage": "yes"}, {"assetId": 2201, "regions": ["jp"]},
                    {"assetId": 2201, "regions": ["gl", "gl"]}, {"assetId": 2201, "extra": 1}):
            with self.subTest(target=bad), self.assertRaisesRegex(ValueError, apply.TARGET_REQUEST):
                apply.plan(self.root, project, target=bad)

    def test_apply_puts_the_whole_timeline_and_the_stage_into_the_slot_then_restore(self):
        project = self.imported()
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": True})
        with self.assertRaisesRegex(ValueError, apply.CROSS_EDITS):
            apply.validate_apply(self.root, {"mode": "edits", "project": project, "platforms": ["android", "ios"],
                                             "target": {"assetId": 2201}, "expected": plan["expected"]})
        job, summary = self.run_cross(project, plan)
        self.assertTrue(summary.startswith("Applied to the game: ") and summary.endswith(" · 3D 2201."), summary)
        validate = [call for call in self.store.calls if call[0] == "validate"]
        self.assertEqual(validate, [("validate", "gl", 2101, ["android", "ios"])])  # the SOURCE asset's stock
        # The check is the write's own: the target slot, its source and the stage.
        self.assertEqual(self.store.checks, [("gl", 2201, 2101, STAGE_2101)])
        _, region, asset, source, stage, timelines = next(call for call in self.store.calls if call[0] == "apply")
        self.assertEqual((region, asset, source, stage), ("gl", 2201, 2101, STAGE_2101))
        android = json.loads(timelines["android"][8:].rstrip(b" "))
        ios = json.loads(timelines["ios"][8:].rstrip(b" "))
        self.assertEqual((android["platform"], ios["platform"]), ("android", "ios"))
        self.assertEqual(android["tracks"], ios["tracks"])
        self.assertEqual(android["tracks"][1]["events"][0]["values"]["intensity"], 2.5)
        result = next(event for event in job.events if event["type"] == "mv-timeline")
        self.assertNotIn("applied", result)  # the project's record of its own slot stays
        self.assertEqual((result["cross"]["assetId"], result["changed"], result["restart"]), (2201, True, "done"))
        # An unedited project still carries its whole (stock) timeline into the other slot.
        self.store.overrides.clear()
        self.store.calls.clear()
        plain = self.imported(edit=False)
        self.run_cross(plain, apply.plan(self.root, plain, target={"assetId": 2201, "stage": False}),
                       target={"assetId": 2201, "stage": False})
        _, _, _, _, stage, timelines = next(call for call in self.store.calls if call[0] == "apply")
        self.assertIsNone(stage)
        self.assertEqual(self.store.checks[-1], ("gl", 2201, 2101, None))  # the slot's own original stage
        self.assertEqual(timelines, {"android": self.local["tl2101"], "ios": self.local["tl2101i"]})
        # Restore per target slot.
        plan = apply.plan(self.root, plain, target={"assetId": 2201, "stage": False})
        self.assertEqual(plan["restore"], {"available": True, "regions": ["gl"]})
        request = apply.validate_restore({"assetId": 2201, "regions": {"gl": {"key": plan["expected"]["keys"]["gl"]}}})
        with mock.patch.object(register, "managed", return_value=True):
            apply.run_restore(FakeJob(), self.root, request)
        self.assertEqual(self.store.calls[-1], ("restore", "gl", 2201, "X1"))

    def test_a_platform_without_its_original_asks_and_can_be_left_out(self):
        self.remote["tl2101i"] = self.local.pop("tl2101i")
        project = self.imported()
        plan = apply.plan(self.root, project, target={"assetId": 2201})
        self.assertEqual(plan["all"]["download"], ["ios"])
        self.assertEqual(plan["platforms"]["ios"], {"payload": {"status": "download", "bytes": reg_tests.TIMELINE_SIZE}})
        self.run_cross(project, plan, platforms=("android",))
        _, _, _, _, _, timelines = next(call for call in self.store.calls if call[0] == "apply")
        self.assertIsNone(timelines["ios"])  # plays the source's original timeline (the store refuses KEEP here)
        self.assertIsInstance(timelines["android"], bytes)
        # Convert: the download is allowed, so the iOS timeline is made from the Android one.
        self.store.overrides.clear()
        self.store.calls.clear()
        self.run_cross(project, apply.plan(self.root, project, target={"assetId": 2201}), download=True)
        _, _, _, _, _, timelines = next(call for call in self.store.calls if call[0] == "apply")
        self.assertEqual(json.loads(timelines["ios"][8:].rstrip(b" "))["platform"], "ios")
        # Not downloadable at all: the job refuses that platform.
        self.store.overrides.clear()
        self.remote.clear()
        with self.assertRaisesRegex(ValueError, apply.CROSS_MISSING_IOS):
            apply._cross_payloads(self.root, project, apply._target(self.root, project, self.store, "en"),
                                  ["android", "ios"], download=True)

    def test_an_out_of_date_slot_is_refused(self):
        project = self.imported()
        plan = apply.plan(self.root, project, target={"assetId": 2201})
        self.store.overrides[("gl", 2201)] = {"key": "Z9", "stage": None, "timelines": {}}
        job = FakeJob()
        request = apply.validate_apply(self.root, {"mode": "all", "project": project, "platforms": ["android", "ios"],
                                                   "target": {"assetId": 2201},
                                                   "expected": {"key": "A2201", "keys": plan["expected"]["keys"]}})
        with mock.patch.object(register, "managed", return_value=True), self.assertRaisesRegex(ValueError, apply.STALE):
            apply.run_apply(job, self.root, request)
        self.assertFalse([call for call in self.store.calls if call[0] == "apply"])


def add_jp(root):
    """A JP copy of the synthetic GL databases whose timeline packs have their own names (j…), as GL and
    JP keep the same stock timeline in different packs; none of them is local."""
    import shutil
    import sqlite3
    gl, jp = Path(root) / "assets/db/gl", Path(root) / "assets/db/jp"
    jp.mkdir(parents=True)
    shutil.copyfile(gl / "masterdata.db", jp / "masterdata.db")
    for platform in ("a", "i"):
        target = jp / f"asset_{platform}_ja.db"
        shutil.copyfile(gl / f"asset_{platform}_en.db", target)
        with sqlite3.connect(target) as database:
            for table in ("live_timeline", "m_asset_package_mapping", "m_asset_pack"):
                columns = {row[1] for row in database.execute(f"PRAGMA table_info({table})")}
                if "pack_name" in columns:
                    database.execute(f"UPDATE {table} SET pack_name='j'||pack_name WHERE pack_name LIKE 'tl%'")


@NEEDS_STORE
class TwoRegionCrossSlotTests(reg_tests.Case):
    """GL and JP: each region checks the payloads against its own original of the source MV."""

    def setUp(self):
        super().setUp()
        add_jp(self.root)
        for name in ("tl2101", "tl2101i", "tl2201", "tl2201i"):
            self.remote["j" + name] = self.local[name]  # the JP packs: downloadable only
        self.store = FakeStore(regions=("gl", "jp"))
        patcher = mock.patch.object(register, "store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def imported(self):
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        return project

    def apply(self, project, plan, *, download):
        request = apply.validate_apply(self.root, {"mode": "all", "project": project, "platforms": ["android", "ios"],
                                                   "download": download, "target": plan["_target"],
                                                   "expected": {"key": plan["expected"]["key"],
                                                                "keys": plan["expected"]["keys"]}})
        with mock.patch.object(register, "managed", return_value=True):
            return apply.run_apply(FakeJob(), self.root, request)

    def test_the_second_region_downloads_its_own_original_for_the_check(self):
        project = self.imported()
        target = {"assetId": 2201, "stage": True, "regions": ["gl", "jp"]}
        plan = apply.plan(self.root, project, target=target)
        plan["_target"] = target
        self.assertEqual(plan["blocked"], [])
        self.assertEqual(plan["all"]["download"], [])  # GL has both originals: nothing to convert onto
        self.assertEqual(plan["cross"]["verify"],
                         [{"region": "jp", "platform": "android", "bytes": reg_tests.TIMELINE_SIZE},
                          {"region": "jp", "platform": "ios", "bytes": reg_tests.TIMELINE_SIZE}])
        self.assertEqual(plan["cross"]["regions"]["jp"]["originals"],
                         {"android": {"status": "download", "bytes": reg_tests.TIMELINE_SIZE},
                          "ios": {"status": "download", "bytes": reg_tests.TIMELINE_SIZE}})
        self.assertEqual(plan["cross"]["regions"]["gl"]["originals"],
                         {"android": {"status": "project"}, "ios": {"status": "local"}})
        self.assertEqual(plan["cross"]["regions"]["jp"]["stageAfter"], STAGE_2101)
        # Without the download nothing is checked or written.
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(apply.CROSS_VERIFY_DOWNLOAD) + "$"):
            self.apply(project, plan, download=False)
        self.assertEqual([call for call in self.store.calls if call[0] != "validate" or call[1] == "jp"], [])
        # Allowed: JP is checked and written with JP's own originals; GL reads its local ones.
        self.store.calls.clear()
        self.store.originals.clear()
        self.apply(project, plan, download=True)
        self.assertEqual([call[:3] for call in self.store.calls],
                         [("validate", "gl", 2101), ("validate", "jp", 2101), ("apply", "gl", 2201),
                          ("apply", "jp", 2201)])
        jp_originals = {"android": self.local["tl2101"], "ios": self.local["tl2101i"]}
        gl_originals = {"android": self.local["tl2101"]}  # the project's own snapshot; iOS is read locally
        self.assertTrue(self.store.originals == [("validate", "gl", gl_originals), ("validate", "jp", jp_originals),
                                                 ("apply", "gl", gl_originals), ("apply", "jp", jp_originals)],
                        [(kind, region, sorted(value)) for kind, region, value in self.store.originals])
        self.assertIn(("jtl2101", True), self.loads)
        self.assertIn(("jtl2101i", True), self.loads)

    def test_a_stage_the_second_region_lacks_is_refused_before_anything_is_written(self):
        """"Both GL and JP": JP's catalogs lack the source's stage. The store's check refuses it before the
        game server stops and before GL is written (no PARTIAL_GL)."""
        missing = "The chosen stage, stage effect, prop skeleton or shader variant is not in this region's game catalogs."
        self.store.refuse_stage = {"jp": missing}
        project = self.imported()
        target = {"assetId": 2201, "stage": True, "regions": ["gl", "jp"]}
        plan = apply.plan(self.root, project, target=target)
        plan["_target"] = target
        with mock.patch.object(register, "_store_step", side_effect=AssertionError("the server was stopped")), \
                self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(missing) + "$"):
            self.apply(project, plan, download=True)
        self.assertEqual([call[:2] for call in self.store.calls], [("validate", "gl"), ("validate", "jp")])
        self.assertEqual(self.store.checks, [("gl", 2201, 2101, STAGE_2101), ("jp", 2201, 2101, STAGE_2101)])


@NEEDS_STORE
class ForeignSourceSlotTests(reg_tests.Case):
    """A slot that plays a timeline put there from another slot is edited through that source MV."""

    def setUp(self):
        super().setUp()
        self.store = FakeStore()
        self.store.overrides[("gl", 2101)] = {"key": "X7", "stage": STAGE_2101, "source": 2201,
                                              "timelines": {"android": b"x", "ios": None}}
        patcher = mock.patch.object(register, "store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_editing_it_directly_is_refused_and_restore_stays(self):
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "X7"})
        project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        plan = apply.plan(self.root, project)
        blocked = {"message": apply.SLOT_FROM_OTHER, "values": {"source": 2201}}
        self.assertEqual((plan["edits"]["blocked"][0], plan["all"]["blocked"][0]), (blocked, blocked))
        self.assertEqual(plan["blocked"], [])
        self.assertTrue(plan["restore"]["available"])
        for mode in ("all", "edits"):
            request = apply.validate_apply(self.root, {"mode": mode, "project": project, "platforms": ["android", "ios"],
                                                       "expected": {"key": "X7"}})
            with self.subTest(mode=mode), mock.patch.object(register, "managed", return_value=True), \
                    self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(apply.SLOT_FROM_OTHER_JOB) + "$"):
                apply.run_apply(FakeJob(), self.root, request)
        cross = apply.plan(self.root, project, target={"assetId": 2201})
        self.assertIn(blocked, cross["blocked"])
        self.assertFalse([call for call in self.store.calls if call[0] == "apply"])
        # The panel reads the loaded slot's foreign source to disable the pack export.
        self.assertEqual((plan["loaded"]["foreignSource"], cross["loaded"]["foreignSource"]), (2201, 2201))

    def test_a_pack_cannot_be_exported_from_it(self):
        """The pack would name 3D 2101 as its source while its timeline is 2201's: Elichika would then
        refuse it at install against 2101's true stock."""
        written = []
        with mock.patch.dict(sys.modules, {"mv_timeline_pack": fake_pack_module(written)}):
            project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                           "assetId": 2101, "mvOnly": False, "registered": False,
                                           "timelineKey": "X7"})
            for target in (None, {"assetId": 2201, "stage": True}, {"assetId": 2101}):
                request = mv_studio_pack.validate_export({"project": project, "name": "p", "target": target})
                with self.subTest(target=target), self.assertRaisesRegex(
                        ValueError, "^" + __import__("re").escape(apply.SLOT_FROM_OTHER_JOB) + "$"):
                    mv_studio_pack.export_pack(self.root, request)
            self.assertEqual(written, [])
            self.assertEqual(list(self.library.glob("modded/**/*.sifasmv")), [])
            # Its own slot again (restored): the export works.
            del self.store.overrides[("gl", 2101)]
            project["source"]["timelineKey"] = "A2101"
            self.assertIsNone(apply.plan(self.root, project)["loaded"]["foreignSource"])
            mv_studio_pack.export_pack(self.root, mv_studio_pack.validate_export(
                {"project": project, "name": "p", "target": {"assetId": 2201}}))
            self.assertEqual(written[-1]["source"], {"region": "gl", "assetId": 2101})


# ---------------------------------------------------------------- MV timeline packs

def fake_pack_module(written):
    """Elichika's mv_timeline_pack contract (write_pack keywords, {manifest, timelines, legacy} readers)."""
    def write_pack(*, name, song, source, target_asset_id, timelines, stage=None, note="", created=None,
                   target_stage=None, source_timeline_key=None):
        written.append({"name": name, "note": note, "song": song, "source": source, "target": {"assetId": target_asset_id},
                        "stage": stage, "platforms": dict(timelines), "targetStage": target_stage,
                        "sourceKey": source_timeline_key})
        return b"PK-fake-pack"

    def read_pack(data):
        if not data.startswith(b"PK-fake-pack"):
            raise ValueError("This file is not an MV timeline pack.")
        entry = written[-1]
        return {"manifest": {"format": "elichika-mv-timeline-pack", "version": 1, **{key: entry[key] for key in
                                                                                     ("name", "note", "song", "source",
                                                                                      "target", "stage")}},
                "timelines": entry["platforms"], "legacy": False}

    def read_legacy_livetimeline_zip(data):
        if not data.startswith(b"PK-legacy"):
            raise ValueError("The live timeline zip has no readable livetimeline.txt or timeline file.")
        return {"manifest": {"target": {"assetId": 2201}, "source": None, "song": None, "stage": None,
                             "legacyTimelineKey": "A2101"}, "timelines": {"android": written[-1]}, "legacy": True}

    def read_any(data):
        return read_legacy_livetimeline_zip(data) if data.startswith(b"PK-legacy") else read_pack(data)

    return types.SimpleNamespace(write_pack=write_pack, read_pack=read_pack, read_any=read_any,
                                 read_legacy_livetimeline_zip=read_legacy_livetimeline_zip)


@NEEDS_STORE
class PackTests(reg_tests.Case):
    def setUp(self):
        super().setUp()
        self.written = []
        patcher = mock.patch.dict(sys.modules, {"mv_timeline_pack": fake_pack_module(self.written)})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(register, "store", return_value=FakeStore())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_export_open_and_load_a_pack(self):
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        request = mv_studio_pack.validate_export({"project": project, "name": " 내 팩 ", "note": "메모",
                                                  "target": {"assetId": 2201, "stage": True}})
        receipt = mv_studio_pack.export_pack(self.root, request)
        self.assertEqual((receipt["platforms"], receipt["skipped"]), (["android", "ios"], []))
        written = self.written[-1]
        self.assertEqual((written["name"], written["note"], written["song"], written["source"], written["target"],
                          written["stage"]), ("내 팩", "메모", {"liveId": 21, "title": "Base song"},
                                              {"region": "gl", "assetId": 2101}, {"assetId": 2201}, STAGE_2101))
        # The legacy layout's inputs: the target slot's own stage and the source's stock key.
        self.assertEqual((written["targetStage"]["live_stage_master_id"], written["sourceKey"]), (102, "A2101"))
        self.assertEqual(json.loads(written["platforms"]["ios"][8:].rstrip(b" "))["platform"], "ios")
        path = Path(receipt["path"])
        self.assertEqual((path.suffix, path.read_bytes()), (".sifasmv", b"PK-fake-pack"))
        opened = mv_studio_pack.open_pack(self.root, str(path), platform="ios")
        self.assertEqual((opened["region"], opened["platform"], opened["liveId"], opened["assetId"]), ("gl", "ios", 21, 2101))
        self.assertEqual((opened["info"]["targetAssetId"], opened["info"]["stage"], opened["info"]["name"]), (2201, True, "내 팩"))
        raw, info = mv_studio_pack.staged(opened["pack"], "ios")
        self.assertEqual(raw, written["platforms"]["ios"])
        self.assertEqual(info["token"], opened["pack"])
        with self.assertRaisesRegex(ValueError, mv_studio_pack.PACK_STALE):
            mv_studio_pack.staged(opened["pack"], "android")
        with self.assertRaisesRegex(ValueError, mv_studio_pack.PACK_STALE):
            mv_studio_pack.staged("../" + "0" * 61, "ios")

    def test_the_size_limit_is_the_readers_own(self):
        """MV Studio opens every pack Elichika's reader opens (its MAX_PACK_BYTES) and names a larger one
        too large, not "not a pack"; a reader without the constant keeps MV Studio's own limit."""
        path = self.library / "modded" / "big.sifasmv"
        path.write_bytes(b"x" * 32)
        module = sys.modules["mv_timeline_pack"]
        with mock.patch.object(mv_studio_pack, "PACK_BYTES", 16):
            with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(mv_studio_pack.TOO_LARGE) + "$"):
                mv_studio_pack.read(path)  # no MAX_PACK_BYTES: MV Studio's own 16 bytes
            module.MAX_PACK_BYTES = 64
            self.addCleanup(delattr, module, "MAX_PACK_BYTES")
            with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(mv_studio_pack.NOT_PACK) + "$"):
                mv_studio_pack.read(path)  # within the reader's 64 bytes: the reader decides (not a pack)
            path.write_bytes(b"x" * 65)
            with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(mv_studio_pack.TOO_LARGE) + "$"):
                mv_studio_pack.read(path)
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(mv_studio_pack.NOT_PACK) + "$"):
                mv_studio_pack.read(path)

    def test_the_pack_carries_the_source_stock_stage(self):
        """A source slot whose stage MV Studio changed (its own timeline, another stage) exports its STOCK
        stage, as "Change the stage too" does in apply, not the masterdata row it has now."""
        stock = {**STAGE_2101, "live_stage_master_id": 109, "stage_effect_asset_path": "E-stock"}
        register.store.return_value.overrides[("gl", 2101)] = {"key": "A2101", "stage": STAGE_2101, "source": None,
                                                               "timelines": {}, "stockStage": stock}
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        self.assertEqual(apply.stage_fields(self.root, "gl", 2101), STAGE_2101)  # the row now
        mv_studio_pack.export_pack(self.root, mv_studio_pack.validate_export(
            {"project": project, "name": "p", "target": {"assetId": 2201, "stage": True}}))
        self.assertEqual(self.written[-1]["stage"], stock)
        # Without the stage, or for the loaded slot itself, no stage is carried.
        for target in ({"assetId": 2201, "stage": False}, None):
            mv_studio_pack.export_pack(self.root, mv_studio_pack.validate_export(
                {"project": project, "name": "p", "target": target}))
            self.assertIsNone(self.written[-1]["stage"])

    def test_a_pack_without_its_other_original_and_a_legacy_zip(self):
        self.remote["tl2101i"] = self.local.pop("tl2101i")
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        receipt = mv_studio_pack.export_pack(self.root, mv_studio_pack.validate_export(
            {"project": project, "name": "a", "target": None}))
        self.assertEqual((receipt["platforms"], receipt["skipped"]), (["android"], ["ios"]))
        self.assertIsNone(self.written[-1]["stage"])  # the loaded slot: no stage change
        legacy = self.library / "modded" / "legacy.zip"
        self.written.append(self.local["tl2101"])
        legacy.write_bytes(b"PK-legacy")
        opened = mv_studio_pack.open_pack(self.root, str(legacy))
        # A legacy zip names only its target (2201): its source is the asset whose key the txt names.
        self.assertEqual((opened["assetId"], opened["liveId"], opened["platform"], opened["info"]["legacy"],
                          opened["info"]["targetAssetId"]), (2101, 21, "android", True, 2201))
        for bad in ({"project": project, "name": ""}, {"project": project, "name": "a", "note": "x" * 501},
                    {"project": project, "name": "a", "target": {"assetId": -1}}, {"project": project, "name": "a", "x": 1}):
            with self.subTest(bad=sorted(bad)), self.assertRaises(ValueError):
                mv_studio_pack.validate_export(bad)

    def test_the_platform_tool_adds_the_missing_platform_to_a_pack(self):
        from webtools.tools import mv_timeline
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        self.remote["tl2101i"] = self.local.pop("tl2101i")
        receipt = mv_studio_pack.export_pack(self.root, mv_studio_pack.validate_export(
            {"project": project, "name": "p", "target": {"assetId": 2201}}))
        self.local["tl2101i"] = self.remote.pop("tl2101i")
        out = self.library / "modded" / "out"
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        job = types.SimpleNamespace(log=lambda line: None, progress=lambda done, total: None, outputs=[])
        job.add_output = job.outputs.append
        summary = mv_timeline.run_mv_timeline_platform(job, {"direction": "android_to_ios", "source": receipt["path"],
                                                             "out_dir": str(out)})
        self.assertTrue(summary.startswith("Converted: "))
        self.assertEqual(sorted(self.written[-1]["platforms"]), ["android", "ios"])
        self.assertEqual(self.written[-1]["stage"], STAGE_2101)
        # The legacy layout's inputs survive the conversion: the target slot's stage and the source's stock key.
        self.assertEqual((self.written[-1]["targetStage"]["live_stage_master_id"], self.written[-1]["sourceKey"]),
                         (102, "A2101"))
        # A raw .unity needs the region and the 3D asset id of its MV.
        source = self.library / "modded" / "edited.unity"
        source.write_bytes(timeline_bytes("android", tag="edited"))
        mv_timeline.run_mv_timeline_platform(job, {"direction": "android_to_ios", "source": str(source), "region": "gl",
                                                   "asset_id": "2101", "out_dir": str(out)})
        self.assertEqual(Path(job.outputs[-1]).name, "edited_iOS.unity")
        with self.assertRaisesRegex(ValueError, conversion.ASSET):
            mv_timeline.run_mv_timeline_platform(job, {"direction": "android_to_ios", "source": str(source),
                                                       "out_dir": str(out)})


@NEEDS_STORE
class RealPackModuleTests(reg_tests.Case):
    """MV Studio's pack code and the platform tool with Elichika's own mv_timeline_pack (reader and writer)."""

    def setUp(self):
        super().setUp()
        try:
            import mv_timeline_pack
        except ImportError:
            self.skipTest("This Elichika has no MV timeline packs")
        self.pack = mv_timeline_pack

    def hand_made(self, stage):
        """A hand-made pack whose manifest stage names only ``stage`` (MV Studio exports all five or none)."""
        import io
        import zipfile
        data = self.pack.write_pack(name="hand", song={"liveId": 21, "title": "Base song"},
                                    source={"region": "gl", "assetId": 2101}, target_asset_id=2201,
                                    timelines={"android": self.local["tl2101"]}, stage=None)
        source, output = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
        with source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in source.infolist():
                raw = source.read(info)
                if info.filename == "manifest.json":
                    raw = json.dumps(dict(json.loads(raw), stage=stage)).encode()
                archive.writestr(info.filename, raw)
        path = self.library / "modded" / "hand.sifasmv"
        path.write_bytes(output.getvalue())
        return path

    def convert(self, path):
        """The platform tool's android -> ios conversion of the pack at ``path``: (written bytes, job log)."""
        from webtools.tools import mv_timeline
        out = self.library / "modded" / "out"
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            logs = []
            job = types.SimpleNamespace(log=logs.append, progress=lambda done, total: None, outputs=[])
            job.add_output = job.outputs.append
            mv_timeline.run_mv_timeline_platform(job, {"direction": "android_to_ios", "source": str(path),
                                                       "out_dir": str(out)})
        finally:
            os.chdir(cwd)
        return Path(job.outputs[-1]).read_bytes(), logs

    def installed_stage(self, data):
        """The stage Elichika's install gives the target 2201 for the pack ``data`` (then restored)."""
        import database_maintenance
        import mv_studio_stock
        before = apply.stage_fields(self.root, "gl", 2201)
        self.pack.install_pack(self.root, data, regions=("gl",), log=None,
                               convert=lambda raw, src, dst, region, asset_id: timeline_bytes(dst, tag="converted"))
        stage = apply.stage_fields(self.root, "gl", 2201)
        described = mv_studio_stock.describe_mv_timeline(self.root, region="gl", asset_id=2201)
        with database_maintenance.guard(self.root):
            mv_studio_stock.restore_mv_timeline(self.root, region="gl", asset_id=2201,
                                                expected_key=described["timelineKey"], log=None)
        self.assertEqual(apply.stage_fields(self.root, "gl", 2201), before)
        return stage

    def test_a_partial_stage_installs_the_same_stage_after_the_conversion(self):
        """The install fills the stage fields a pack leaves out from the TARGET slot's original stage, so the
        platform tool passes a partial stage through (the writer takes it), or, with an older writer that
        needs all five, fills it from the target's stock stage: the converted pack installs what the
        original pack installs. The source's stage (E2101) never fills it."""
        import io
        import zipfile
        partial = {"live_stage_master_id": 101}
        path = self.hand_made(partial)
        self.assertEqual(self.pack.read_pack(path)["manifest"]["stage"], partial)
        original = self.installed_stage(path.read_bytes())
        target_stock = apply.stage_fields(self.root, "gl", 2201)
        self.assertEqual(original, {**target_stock, **partial})
        self.assertNotEqual(original["stage_effect_asset_path"], STAGE_2101["stage_effect_asset_path"])
        # This Elichika's writer takes the partial stage: it goes through as it is.
        self.assertTrue(getattr(self.pack, "PARTIAL_STAGE", False))
        written, logs = self.convert(path)
        result = self.pack.read_pack(written)
        self.assertEqual((sorted(result["timelines"]), result["manifest"]["stage"]), (["android", "ios"], partial))
        self.assertFalse(any("whole stage" in line for line in logs), logs)
        self.assertEqual(self.installed_stage(written), original)
        # The legacy layout: the target's file, the source's stock key, and the stage the install gives the target.
        with zipfile.ZipFile(io.BytesIO(written)) as archive:
            self.assertIn("2201android.unity", archive.namelist())
            text = archive.read("livetimeline.txt").decode()
        self.assertIn("timeline = 'A2101'", text)
        self.assertIn("live_stage_master_id = 101", text)
        self.assertIn(f"stage_effect_asset_path = {target_stock['stage_effect_asset_path']!r}", text)
        # An older writer needs the whole stage: the left-out fields come from the target's stock stage (logged).
        with mock.patch.object(self.pack, "PARTIAL_STAGE", False):
            written, logs = self.convert(path)
        self.assertEqual(self.pack.read_pack(written)["manifest"]["stage"], original)
        self.assertTrue(any("stage_effect_asset_path" in line and "3D 2201" in line for line in logs), logs)
        self.assertEqual(self.installed_stage(written), original)

    def test_a_damaged_compressed_entry_is_not_a_pack(self):
        """A corrupt deflate stream or LZMA entry is a refusal (ValueError, HTTP 400), whether the reader
        names it itself or lets zlib.error / LZMAError out."""
        import io
        import struct
        import zipfile
        data = self.pack.write_pack(name="p", song={"liveId": 21, "title": "Base song"},
                                    source={"region": "gl", "assetId": 2101}, target_asset_id=2201,
                                    timelines={"android": self.local["tl2101"]})
        for method in (zipfile.ZIP_DEFLATED, zipfile.ZIP_LZMA):
            source, output = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
            with source, zipfile.ZipFile(output, "w") as archive:
                for info in source.infolist():
                    archive.writestr(info.filename, source.read(info),
                                     compress_type=method if info.filename == "manifest.json" else zipfile.ZIP_DEFLATED)
            raw = bytearray(output.getvalue())
            info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("manifest.json")
            name, extra = struct.unpack("<HH", raw[info.header_offset + 26:info.header_offset + 30])
            start = info.header_offset + 30 + name + extra
            if method == zipfile.ZIP_DEFLATED:
                raw[start] = 0x07  # a final block of the reserved type: "invalid block type"
            else:
                for index in range(start + info.compress_size // 2, start + info.compress_size // 2 + 8):
                    raw[index] ^= 0xFF
            path = self.library / "modded" / f"damaged-{method}.sifasmv"
            path.write_bytes(bytes(raw))
            with self.subTest(method=method), self.assertRaises(ValueError) as caught:
                mv_studio_pack.read(path)
            self.assertIn(str(caught.exception), (mv_studio_pack.NOT_PACK, self.pack.INVALID))
            with self.subTest(method=method, route="open"), self.assertRaises(ValueError):
                mv_studio_pack.open_pack(self.root, str(path))


if __name__ == "__main__":
    unittest.main()


@NEEDS_STORE
class RealStoreCrossSlotTests(reg_tests.Case):
    """The Elichika store itself (when it has the cross-slot arguments) on the synthetic GL root."""

    def setUp(self):
        super().setUp()
        import mv_studio_stock
        if "source_asset_id" not in __import__("inspect").signature(mv_studio_stock.apply_mv_timeline).parameters:
            self.skipTest("This Elichika store cannot apply another slot")
        mv_studio_stock._VALIDATED.clear()
        self.addCleanup(mv_studio_stock._VALIDATED.clear)
        for name, value in (("prepare_tracks", lambda raw, name, tracks, original: tracks),
                            ("_rewrite_timeline", __import__("test_mv_studio_apply").fake_rewrite)):
            patcher = mock.patch.object(mv_studio_timeline, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_apply_with_the_stage_and_restore_exactly(self):
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        before = apply.stage_fields(self.root, "gl", 2201)
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": True})
        self.assertEqual(plan["blocked"], [])
        self.assertTrue(plan["cross"]["supported"])
        request = apply.validate_apply(self.root, {"mode": "all", "project": project, "platforms": ["android", "ios"],
                                                   "target": {"assetId": 2201, "stage": True},
                                                   "expected": plan["expected"]})
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=False):
            apply.run_apply(job, self.root, request)
        failed = [event for event in job.events if event["type"] == "mv-failed"]
        self.assertEqual(failed, [])
        self.assertEqual(apply.stage_fields(self.root, "gl", 2201), STAGE_2101)
        described = mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2201)
        self.assertEqual((described["override"], described["platforms"]), (True, {"android": "custom", "ios": "custom"}))
        served = register._registered_timelines(self.root, described)
        self.assertEqual(json.loads(served["android"][8:].rstrip(b" "))["tracks"][1]["events"][0]["values"]["intensity"], 2.5)
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": True})
        self.assertEqual(plan["restore"], {"available": True, "regions": ["gl"]})
        with mock.patch.object(register, "managed", return_value=False):
            apply.run_restore(FakeJob(), self.root, apply.validate_restore(
                {"assetId": 2201, "regions": {"gl": {"key": plan["expected"]["keys"]["gl"]}}}))
        self.assertEqual(apply.stage_fields(self.root, "gl", 2201), before)
        self.assertFalse(mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2201)["override"])

    def test_a_stage_missing_from_the_catalog_is_refused_by_the_check(self):
        """The real store's check gets the target slot, its source and the stage, so STAGE_MISSING comes
        from the validation step, before the game server would be stopped."""
        import mv_studio_stock
        import sqlite3
        project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                       "assetId": 2101, "mvOnly": False, "registered": False, "timelineKey": "A2101"})
        project["tracks"][1]["events"][0]["values"]["intensity"] = 2.5
        plan = apply.plan(self.root, project, target={"assetId": 2201, "stage": True})
        self.assertEqual(plan["blocked"], [])
        # The source's stage 101 leaves the catalog (an inconsistent region, as a JP-only stage in GL).
        with sqlite3.connect(Path(self.root) / "assets/db/gl/masterdata.db") as master:
            master.execute("DELETE FROM m_live_stage WHERE id=101")
        request = apply.validate_apply(self.root, {"mode": "all", "project": project, "platforms": ["android", "ios"],
                                                   "target": {"assetId": 2201, "stage": True},
                                                   "expected": plan["expected"]})
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=True), \
                mock.patch.object(register, "_store_step", side_effect=AssertionError("the server was stopped")), \
                self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(mv_studio_stock.STAGE_MISSING) + "$"):
            apply.run_apply(job, self.root, request)
        self.assertEqual([event["stage"] for event in job.events if event["type"] == "mv-stage"][-1], "validate")
        self.assertFalse(mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2201)["override"])
