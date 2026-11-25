"""Apply to game ("게임에 적용", webtools/core/mv_studio_apply.py) on synthetic game databases.

The Elichika store (mv_studio_live with mv_studio_stock) runs for real when the Elichika server app is
importable (ELICHIKA_DIR). Synthetic native timelines are the registration tests' JSON stand-ins; the
real-sample tests use the real 12035 timelines (ELICHIKA_STUDIO_TIMELINE_DIR) with the real parser,
writer, the store's validator and installation_server with a stand-in controller.
No game data is stored in this file.
"""
import ast
import copy
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
for folder in (REPO, REPO / "tests"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import test_mv_studio_register as reg_tests  # noqa: E402
from webtools import i18n  # noqa: E402
from webtools.core import mv_studio, mv_studio_apply as apply, mv_studio_register as register  # noqa: E402
from webtools.core import mv_studio_timeline  # noqa: E402

mv_studio_live = reg_tests.mv_studio_live
NEEDS_STORE = reg_tests.NEEDS_STORE
if mv_studio_live is not None:
    import mv_studio_stock  # noqa: E402
    native = reg_tests.native
FakeJob = reg_tests.FakeJob
SAMPLES = reg_tests.SAMPLES
REAL_PREPARE, REAL_REWRITE = mv_studio_timeline.prepare_tracks, mv_studio_timeline._rewrite_timeline


def fake_rewrite(raw, original, revised):
    """The native rewrite's own rules (_check_values, _changes) on the JSON stand-ins."""
    mv_studio_timeline._check_values(original, revised)
    if not mv_studio_timeline._changes(original, revised):
        return raw
    document = json.loads(raw[8:].rstrip(b" ").decode())
    document.update(tracks=revised["tracks"], tag="rewritten")
    return b"UnityFS\0" + json.dumps(document, sort_keys=True).encode()


def tracks_of(raw):
    return reg_tests.fake_parse(raw, "x")["tracks"]


class ApplyCase(reg_tests.Case):
    """A synthetic GL root, the real Elichika store and the registration fakes (pack loads, parse, export)."""

    def setUp(self):
        super().setUp()
        if mv_studio_live is None:
            self.skipTest("The Elichika server app is not importable")
        mv_studio_stock._VALIDATED.clear()
        self.addCleanup(mv_studio_stock._VALIDATED.clear)
        for name, value in (("prepare_tracks", lambda raw, name, tracks, original: tracks),
                            ("_rewrite_timeline", fake_rewrite)):
            patcher = mock.patch.object(mv_studio_timeline, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def imported(self, platform="android", **source):
        """A game import of stock MV 21 / asset 2101 as it is now (the import records the key it read)."""
        key = self.timeline()["timelineKey"]
        raw = self.served(platform) if self.timeline()["platforms"][platform] == "custom" else None
        fields = {"kind": "game", "region": "gl", "platform": platform, "liveId": 21, "assetId": 2101, "mvOnly": False,
                  "registered": False, "timelineKey": key, **source}
        project = self.project(platform=platform, source=fields, native_bytes=raw)
        if raw is not None:
            project["tracks"] = copy.deepcopy(tracks_of(raw))
        return project

    def timeline(self):
        return mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2101)

    def served(self, platform):
        timeline = self.timeline()
        if timeline["platforms"][platform] == "custom":
            return register._registered_timelines(self.root, timeline, [platform])[platform]
        return self.local["tl2101" + ("i" if platform == "ios" else "")]

    def plan(self, project):
        return apply.plan(self.root, project)

    def run_apply(self, project, mode, *, managed=True, plan=None, download=False, platforms=("android", "ios"),
                  expected=None):
        plan = plan or self.plan(project)
        request = apply.validate_apply(self.root, {"mode": mode, "project": project, "platforms": list(platforms),
                                                   "download": download,
                                                   "expected": {"key": expected or plan["expected"]["key"]}})
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=managed):
            summary = apply.run_apply(job, self.root, request)
        return job, summary

    def run_restore(self, *, managed=True):
        request = apply.validate_restore({"region": "gl", "assetId": 2101,
                                          "expected": {"key": self.timeline()["timelineKey"]}})
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=managed):
            summary = apply.run_restore(job, self.root, request)
        return job, summary

    @staticmethod
    def result(job):
        return next(event for event in job.events if event["type"] == "mv-timeline")

    @staticmethod
    def bloom(tracks):
        return tracks[1]["events"][0]["values"]

    def static_files(self):
        return sorted(path.name for path in (self.root / "static").iterdir() if path.is_file())


@NEEDS_STORE
class PlanTests(ApplyCase):
    def test_a_stock_import_without_edits(self):
        plan = self.plan(self.imported())
        self.assertEqual(plan["target"], {"kind": "stock", "region": "gl", "liveId": 21, "assetId": 2101,
                                          "title": "Base song", "stage": "Star stage",
                                          "lives": {"count": 1, "shown": [{"liveId": 21, "title": "Base song"}]}})
        self.assertEqual(plan["game"], {"state": "original", "revision": 0, "updatedAt": None, "key": "A2101",
                                        "platforms": {"android": "stock", "ios": "stock"}})
        self.assertEqual(plan["source"], {"state": "original", "revision": None, "changedSince": False})
        self.assertEqual((plan["edits"]["unchanged"], plan["edits"]["blocked"]), (True, [{"message": apply.NO_EDITS}]))
        self.assertEqual((plan["all"]["unchanged"], plan["all"]["counts"]["clips"]), (True, 0))
        self.assertEqual(plan["restore"], {"available": False})
        self.assertEqual(plan["expected"]["key"], "A2101")
        self.assertEqual(plan["platforms"]["ios"], {"stock": {"status": "local"}, "served": {"status": "local"}})
        self.assertEqual(plan["blocked"], [])

    def test_projects_that_are_not_game_imports_point_to_registration(self):
        project = self.project(source={"kind": "mod", "name": "x"})
        self.assertEqual(self.plan(project)["blocked"], [{"message": apply.NO_TARGET}])
        scratch = mv_studio._blank("scratch")
        self.assertEqual(self.plan(scratch)["blocked"], [{"message": apply.NO_TARGET}])

    def test_edit_counts_and_a_structure_change(self):
        project = self.edited(self.imported())
        plan = self.plan(project)
        self.assertEqual(plan["edits"]["counts"], {"cameraShots": 1, "values": 1, "timing": 0, "clips": 2})
        self.assertEqual(sorted(plan["edits"]["apply"]), ["android", "ios"])
        self.assertEqual(plan["all"]["unchanged"], False)
        project["tracks"].pop()
        plan = self.plan(project)
        self.assertEqual(plan["blocked"], [{"message": register.STRUCTURE, "labels": ["StageEffect/Ambient"]}])


@NEEDS_STORE
class ApplyEditsTests(ApplyCase):
    def test_edits_go_onto_the_served_timeline_and_the_managed_server_restarts(self):
        project = self.imported()
        self.bloom(project["tracks"])["intensity"] = 2.5
        job, summary = self.run_apply(project, "edits")
        self.assertEqual(summary, apply.APPLIED.replace("{title}", "Base song"))
        result = self.result(job)
        self.assertEqual((result["mode"], result["changed"], result["parts"], result["restart"], result["managed"]),
                         ("edits", True, ["android", "ios"], "done", True))
        self.assertRegex(Path(result["backup"]).name, r"_mv-studio-timeline-2101\Z")
        self.assertEqual(result["game"]["state"], "custom")
        self.assertEqual(job.stages(), ["check", "merge-android", "merge-ios", "validate", "stop", "write", "restart"])
        self.assertEqual(len(self.server_sessions), 1)
        timeline = self.timeline()
        self.assertEqual((timeline["override"], timeline["platforms"], timeline["revision"]),
                         (True, {"android": "custom", "ios": "custom"}, 1))
        for platform in ("android", "ios"):
            served = tracks_of(self.served(platform))
            expected = copy.deepcopy(reg_tests.base_tracks())
            self.bloom(expected)["intensity"] = 2.5
            self.assertEqual(served, expected)
            self.assertEqual(json.loads(self.served(platform)[8:].rstrip(b" "))["platform"], platform,
                             "Each platform's edit is written on that platform's own timeline")
        # Validated against the true stock of each platform (before the stop; the store reuses it).
        self.assertEqual(sorted(self.validated), [("android", "android", 13), ("ios", "ios", 9)])

    def test_edits_on_top_of_an_earlier_apply_keep_both(self):
        first, second = self.imported(), self.imported()
        self.bloom(first["tracks"])["intensity"] = 2.5
        self.run_apply(first, "edits")
        second["tracks"][2]["events"][0]["start"] = 0.5
        plan = self.plan(second)
        self.assertEqual((plan["source"]["changedSince"], plan["edits"]["theirsOnly"], plan["edits"]["conflicts"]),
                         (True, 1, []))
        self.assertEqual(plan["game"]["revision"], 1)
        job, _ = self.run_apply(second, "edits")
        self.assertEqual(self.result(job)["parts"], ["android", "ios"])
        expected = copy.deepcopy(reg_tests.base_tracks())
        self.bloom(expected)["intensity"] = 2.5
        expected[2]["events"][0]["start"] = 0.5
        for platform in ("android", "ios"):
            self.assertEqual(tracks_of(self.served(platform)), expected)
        self.assertEqual(self.timeline()["revision"], 2)

    def test_a_field_changed_differently_in_the_game_is_a_conflict_and_nothing_is_written(self):
        first, second = self.imported(), self.imported()
        self.bloom(first["tracks"])["intensity"] = 2.5
        self.run_apply(first, "edits")
        self.bloom(second["tracks"])["intensity"] = 3.0
        second["tracks"][2]["events"][0]["start"] = 0.5
        plan = self.plan(second)
        conflict = {"track": "StageEffect/Bloom", "trackId": "cab-1:20", "clip": "LiveBloomClip", "eventId": "cab-1:20:0",
                    "start": 1.0, "field": "intensity", "loaded": "1", "project": "3", "game": "2.5"}
        self.assertEqual(plan["edits"]["conflicts"], [{"platform": "android", **conflict}, {"platform": "ios", **conflict}])
        self.assertIn({"message": apply.CONFLICTS}, plan["edits"]["blocked"])
        files, sessions, key = self.static_files(), len(self.server_sessions), self.timeline()["timelineKey"]
        with self.assertRaises(apply.ConflictError) as raised:
            self.run_apply(second, "edits")
        self.assertEqual(len(raised.exception.conflicts), 2)
        self.assertEqual((self.static_files(), len(self.server_sessions), self.timeline()["timelineKey"]),
                         (files, sessions, key))
        # The same value again is no conflict: it is already in the game.
        self.bloom(second["tracks"])["intensity"] = 2.5
        plan = self.plan(second)
        self.assertEqual(plan["edits"]["conflicts"], [])
        job, _ = self.run_apply(second, "edits")
        expected = copy.deepcopy(reg_tests.base_tracks())
        self.bloom(expected)["intensity"] = 2.5
        expected[2]["events"][0]["start"] = 0.5
        self.assertEqual(tracks_of(self.served("ios")), expected)

    def test_editing_the_same_field_again_after_an_apply_is_no_conflict(self):
        project = self.imported()
        self.bloom(project["tracks"])["intensity"] = 2.5
        job, _ = self.run_apply(project, "edits")
        applied = self.result(job)["applied"]
        self.assertEqual(list(applied["fields"]), ["cab-1:20:0"])
        older_page = copy.deepcopy(project)  # A page that did not keep the record of this apply.
        # The page keeps what the project and the game now agree on.
        project["source"]["applied"] = applied
        plan = self.plan(project)
        self.assertEqual((plan["edits"]["unchanged"], plan["edits"]["since"], plan["source"]["changedSince"]),
                         (True, "apply", False))
        self.bloom(project["tracks"])["intensity"] = 3.0
        plan = self.plan(project)
        self.assertEqual((plan["edits"]["counts"]["values"], plan["edits"]["conflicts"]), (1, []))
        job, _ = self.run_apply(project, "edits")
        project["source"]["applied"] = self.result(job)["applied"]
        self.assertEqual(self.bloom(tracks_of(self.served("ios")))["intensity"], 3.0)
        # Back to the loaded value is an edit too, once the game holds another one.
        self.bloom(project["tracks"])["intensity"] = 1.0
        self.assertEqual(self.plan(project)["edits"]["apply"], ["android", "ios"])
        job, _ = self.run_apply(project, "edits")
        project["source"]["applied"] = self.result(job)["applied"]
        self.assertEqual((self.bloom(tracks_of(self.served("android")))["intensity"],
                          project["source"]["applied"]["fields"]), (1.0, {}))
        # Without the record, the loaded value is the agreed one: the game holds it again, so 4.0 applies ...
        self.bloom(older_page["tracks"])["intensity"] = 4.0
        self.assertEqual(self.plan(older_page)["edits"]["conflicts"], [])
        self.run_apply(older_page, "edits")
        # ... and the first project's next change of that field is now a conflict with the game's 4.0.
        self.bloom(project["tracks"])["intensity"] = 5.0
        self.assertEqual([item["game"] for item in self.plan(project)["edits"]["conflicts"]], ["4", "4"])

    def test_unedited_apply_edits_is_a_no_op_that_never_stops_the_server(self):
        job, summary = self.run_apply(self.imported(), "edits")
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual((self.result(job)["changed"], self.result(job)["restart"]), (False, "none"))
        self.assertEqual((self.server_sessions, self.static_files(), self.backups()), ([], [], []))
        # A project whose edits are already in the game (applied before) is a no-op too.
        project = self.imported()
        self.bloom(project["tracks"])["intensity"] = 2.5
        self.run_apply(project, "edits")
        files, sessions, backups = self.static_files(), len(self.server_sessions), self.backups()
        for mode in ("edits", "all"):
            with self.subTest(mode=mode):
                job, summary = self.run_apply(project, mode)
                self.assertEqual(summary, register.NO_CHANGES)
                self.assertEqual((self.static_files(), len(self.server_sessions), self.backups()), (files, sessions, backups))

    def backups(self):
        folder = self.temp / "backups"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def test_an_out_of_date_check_is_refused_before_the_server_stops(self):
        project = self.imported()
        self.bloom(project["tracks"])["intensity"] = 2.5
        plan = self.plan(project)
        other = self.imported()
        other["tracks"][2]["events"][0]["start"] = 0.5
        self.run_apply(other, "edits")
        sessions = len(self.server_sessions)
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.run_apply(project, "edits", plan=plan)
        self.assertEqual(len(self.server_sessions), sessions)

    def test_an_unmanaged_server_asks_for_a_restart(self):
        project = self.edited(self.imported())
        job, _ = self.run_apply(project, "edits", managed=False)
        self.assertEqual((self.result(job)["restart"], self.server_sessions), ("manual", []))


@NEEDS_STORE
class ApplyAllTests(ApplyCase):
    def test_apply_all_replaces_the_game_timeline_and_restore_brings_back_the_stock(self):
        first, second = self.imported(), self.imported()
        self.bloom(first["tracks"])["intensity"] = 2.5
        first["tracks"][2]["events"][0]["start"] = 0.5
        self.run_apply(first, "edits")
        # Loaded from stock before that apply: Apply all makes the game play exactly this project.
        second["tracks"][0]["events"][0]["values"]["keyframes"][1]["position"] = [0, 2, -3]
        plan = self.plan(second)
        self.assertEqual(plan["all"]["counts"]["cameraShots"], 1)
        job, _ = self.run_apply(second, "all")
        self.assertEqual(job.stages()[:3], ["check", "android", "ios"])
        expected = copy.deepcopy(reg_tests.base_tracks())
        expected[0]["events"][0]["values"]["keyframes"][1]["position"] = [0, 2, -3]
        for platform in ("android", "ios"):
            self.assertEqual(tracks_of(self.served(platform)), expected)
        timeline = self.timeline()
        self.assertEqual((timeline["revision"], sorted(timeline["fingerprints"])), (2, ["android", "ios"]))
        # Apply all again without changes keeps the server running (fingerprints).
        sessions = len(self.server_sessions)
        _, summary = self.run_apply(second, "all")
        self.assertEqual((summary, len(self.server_sessions)), (register.NO_CHANGES, sessions))
        # Restore: the stock rows again, through a restorable backup.
        self.assertTrue(self.plan(second)["restore"]["available"])
        job, summary = self.run_restore()
        result = self.result(job)
        self.assertEqual((result["mode"], result["changed"], result["restart"]), ("restore", True, "done"))
        self.assertEqual(summary, apply.RESTORED.replace("{title}", "Base song"))
        self.assertRegex(Path(result["backup"]).name, r"_mv-studio-restore-2101\Z")
        self.assertEqual(self.timeline()["timelineKey"], "A2101")
        for platform, pack in (("android", "tl2101"), ("ios", "tl2101i")):
            descriptor, _ = register._first_catalog_row(self.root, "gl", platform, "en", "live_timeline", "A2101")
            self.assertEqual(register._load(self.root, descriptor, download=False), self.local[pack])
        self.assertEqual(self.static_files(), [])
        with self.assertRaisesRegex(ValueError, "already plays its original timeline"):
            self.run_restore()

    def test_apply_all_of_an_unedited_stock_project_plays_the_stock_again(self):
        first = self.edited(self.imported())
        self.run_apply(first, "edits")
        _, summary = self.run_apply(self.imported(), "edits")
        self.assertEqual(summary, register.NO_CHANGES)
        stock_project = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                             "assetId": 2101, "mvOnly": False, "registered": False,
                                             "timelineKey": "A2101"})
        job, _ = self.run_apply(stock_project, "all")
        self.assertEqual(self.result(job)["parts"], ["android", "ios"])
        self.assertEqual(self.timeline()["override"], False)

    def test_a_project_loaded_from_an_applied_timeline_bakes_against_the_true_stock(self):
        first = self.imported()
        self.bloom(first["tracks"])["intensity"] = 2.5
        self.run_apply(first, "edits")
        reopened = self.imported()
        self.assertNotEqual(reopened["source"]["timelineKey"], "A2101")
        facts = register._facts(self.root, "gl", 21, 2101)
        self.assertEqual((facts["timelineKey"], facts["servedKey"]), ("A2101", self.timeline()["timelineKey"]))
        self.assertEqual(register._project_blob(reopened, {"liveId": 21, "assetId": 2101}, facts)["kind"], "mod")
        plan = self.plan(reopened)
        self.assertEqual(plan["source"]["state"], "custom")
        self.assertEqual((plan["all"]["counts"]["values"], plan["all"]["unchanged"]), (1, True))
        # Registering it as an MV-only song keeps the applied edit and uses the true stock as the base.
        reg_plan = register.plan(self.root, reopened)
        self.assertEqual((reg_plan["timeline"]["kind"], reg_plan["timeline"]["unchanged"]), ("mod", False))
        job, _ = self.run_job(self.request(reopened))
        song = job.song()["song"]
        registered = register._registered_timelines(self.root, song)
        for platform in ("android", "ios"):
            self.assertEqual(self.bloom(tracks_of(registered[platform]))["intensity"], 2.5)


@NEEDS_STORE
class SongTargetTests(ApplyCase):
    def test_an_mv_only_song_takes_edits_and_apply_all_as_timeline_only_updates(self):
        job, _ = self.run_job(self.request(self.edited(self.imported()), title="내 곡", credit="작곡: 나"))
        song = job.song()["song"]
        registered = register._registered_timelines(self.root, song)
        source = {"kind": "game", "region": "gl", "platform": "ios", "liveId": song["liveId"],
                  "assetId": song["assetId"], "mvOnly": True, "registered": True,
                  "registeredSong": reg_tests.opened_song(song), "timelineKey": song["timelineKey"]}
        project = self.project(platform="ios", source=source, native_bytes=registered["ios"])
        project["tracks"] = copy.deepcopy(tracks_of(registered["ios"]))
        plan = self.plan(project)
        self.assertEqual((plan["target"]["kind"], plan["target"]["liveId"], plan["game"]["state"]),
                         ("song", song["liveId"], "custom"))
        self.assertEqual(plan["restore"], {"available": False})
        project["tracks"][2]["events"][0]["start"] = 0.75
        job, _ = self.run_apply(project, "edits")
        project["source"]["applied"] = self.result(job)["applied"]
        after = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=song["liveId"])
        self.assertEqual((after["title"], after["credit"], after["revision"], after["platforms"]),
                         ("내 곡", "작곡: 나", song["revision"] + 1, {"android": "custom", "ios": "custom"}))
        for platform, raw in register._registered_timelines(self.root, after).items():
            tracks = tracks_of(raw)
            self.assertEqual((tracks[2]["events"][0]["start"], self.bloom(tracks)["intensity"]), (0.75, 2.5))
        self.assertEqual(self.result(job)["target"]["kind"], "song")
        # The song changed since this check: refused before the server stops.
        stale = self.plan(project)
        project["tracks"][2]["events"][0]["start"] = 1.0
        other = copy.deepcopy(project)
        self.run_apply(other, "edits")
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.run_apply(project, "edits", plan=stale)


@NEEDS_STORE
class EndpointTests(ApplyCase):
    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        import threading
        from webtools import server
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]

    call = reg_tests.EndpointTests.call

    def wait(self, job_id):
        import threading
        from webtools.jobs import MANAGER
        job = MANAGER.get(job_id)
        for _ in range(400):
            if job.is_done:
                break
            threading.Event().wait(0.05)
        return [job.event_at(index, 0) for index in range(job.event_count)]

    def test_plan_apply_restore_and_the_host_rules(self):
        project = self.imported()
        self.bloom(project["tracks"])["intensity"] = 2.5
        status, plan = self.call("POST", "/api/mv-studio/apply-plan", {"project": project})
        self.assertEqual((status, plan["target"]["kind"]), (200, "stock"))
        status, _ = self.call("POST", "/api/mv-studio/apply-plan", {"project": project},
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, data = self.call("POST", "/api/mv-studio/apply-job", {"mode": "both", "project": project,
                                                                      "platforms": [], "expected": {"key": "A2101"}})
        self.assertEqual((status, data["error"]), (400, apply.MODE))
        body = {"mode": "edits", "project": project, "platforms": ["android", "ios"], "expected": plan["expected"]}
        with mock.patch.object(register, "managed", return_value=False):
            status, data = self.call("POST", "/api/mv-studio/apply-job?lang=ko", body)
            self.assertEqual(status, 200)
            events = self.wait(data["job_id"])
        self.assertEqual(events[-1]["status"], "done", events)
        result = next(event for event in events if event["type"] == "mv-timeline")
        self.assertEqual((result["changed"], result["restart"]), (True, "manual"))
        status, listed = self.call("GET", "/api/mv-studio/timelines?region=gl")
        self.assertEqual((status, [item["assetId"] for item in listed["timelines"]]), (200, [2101]))
        self.assertTrue(register.reserve())
        try:
            status, data = self.call("POST", "/api/mv-studio/restore-job",
                                     {"region": "gl", "assetId": 2101, "expected": {"key": listed["timelines"][0]["timelineKey"]}})
        finally:
            register.release()
        self.assertEqual((status, data["error"]), (409, register.BUSY))
        with mock.patch.object(register, "managed", return_value=False):
            status, data = self.call("POST", "/api/mv-studio/restore-job",
                                     {"region": "gl", "assetId": 2101, "expected": {"key": listed["timelines"][0]["timelineKey"]}})
            events = self.wait(data["job_id"])
        self.assertEqual(events[-1]["status"], "done", events)
        self.assertEqual(self.timeline()["override"], False)


class MergeTests(unittest.TestCase):
    """mv_studio_timeline.merge_changes on plain parse-shaped tracks."""

    def tracks(self, **values):
        return [{"id": "t", "label": "Track", "events": [
            {"id": "t:0", "start": 0.0, "duration": 1.0, "label": "c",
             "values": {"x": 0.5, "y": 1, "keyframes": [{"time": 0.0, "fov": 30.0}], **values}}]}]

    def test_three_way_rules(self):
        base, merge = self.tracks(), mv_studio_timeline.merge_changes
        ours, theirs = self.tracks(x=0.7), self.tracks(y=2)
        merged, conflicts, taken, theirs_only = merge(base, ours, theirs)
        self.assertEqual((merged[0]["events"][0]["values"]["x"], merged[0]["events"][0]["values"]["y"], conflicts, taken,
                          theirs_only), (0.7, 2, [], 1, 1))
        # Already in the game, also once stored as float32.
        for stored in (0.7, 0.699999988079071):
            self.assertEqual(merge(base, ours, self.tracks(x=stored))[1:], ([], 0, 0))
        _, conflicts, _, _ = merge(base, ours, self.tracks(x=0.25))
        self.assertEqual([(item["field"], item["loaded"], item["project"], item["game"]) for item in conflicts],
                         [("x", "0.5", "0.7", "0.25")])
        # Camera keys are one field.
        ours = self.tracks(keyframes=[{"time": 0.0, "fov": 31.0}])
        _, conflicts, _, _ = merge(base, ours, self.tracks(keyframes=[{"time": 0.0, "fov": 32.0}]))
        self.assertEqual((conflicts[0]["field"], conflicts[0]["project"]), ("keyframes", "1 keys"))
        # A boolean is not a number, but a page's JSON number 1 is the parse's 1.0.
        self.assertEqual(len(merge(base, self.tracks(y=True), self.tracks(y=3))[1]), 1)
        digest = mv_studio_timeline.field_digest
        self.assertEqual((digest(1), digest(1.0) == digest(1), digest(True) == digest(1)), (digest(1.0), True, False))
        self.assertEqual(merge(base, self.tracks(x=0.5, y=1.0), self.tracks())[1:], ([], 0, 0))
        self.assertEqual(mv_studio_timeline.synced_fields(base, self.tracks(y=1.0)), {})
        # Clip timing merges per field.
        ours = copy.deepcopy(base)
        ours[0]["events"][0]["start"] = 0.25
        theirs = copy.deepcopy(base)
        theirs[0]["events"][0]["duration"] = 2.0
        merged, conflicts, taken, _ = merge(base, ours, theirs)
        self.assertEqual((merged[0]["events"][0]["start"], merged[0]["events"][0]["duration"], taken), (0.25, 2.0, 1))

    def test_another_layout_is_refused(self):
        base = self.tracks()
        other = copy.deepcopy(base)
        other[0]["events"][0]["id"] = "t:9"
        with self.assertRaisesRegex(ValueError, "different track layout"):
            mv_studio_timeline.merge_changes(base, base, other)
        missing = copy.deepcopy(base)
        del missing[0]["events"][0]["values"]["x"]
        with self.assertRaisesRegex(ValueError, "different track layout"):
            mv_studio_timeline.merge_changes(base, base, missing)


class RequestTests(unittest.TestCase):
    def test_request_validation(self):
        project = mv_studio._blank("x")
        good = {"mode": "edits", "project": project, "platforms": ["android"], "expected": {"key": "A2101"}}
        self.assertEqual(apply.validate_apply(None, good)["platforms"], ("android",))
        for change, message in (({"mode": "x"}, apply.MODE), ({"expected": {"key": ""}}, apply.STALE),
                                ({"expected": "A2101"}, apply.STALE), ({"platforms": ["windows"]}, "Choose Android"),
                                ({"download": 1}, apply.REQUEST), ({"unbaked": [{"kind": "camera"}]}, "not baked"),
                                ({"extra": 1}, apply.REQUEST)):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, re.escape(message)):
                apply.validate_apply(None, {**good, **change})
        with self.assertRaisesRegex(ValueError, re.escape(apply.REQUEST)):
            apply.validate_restore({"region": "gl", "assetId": 0, "expected": {"key": "a"}})
        self.assertEqual(apply.validate_restore({"region": "jp", "assetId": 5, "expected": {"key": "a"}})["region"], "jp")


class MessageTests(unittest.TestCase):
    def assert_translated(self, messages):
        for message in sorted(messages):
            for language in ("ko", "ja"):
                with self.subTest(language=language, message=message):
                    self.assertIn(message, i18n._TABLES[language])
                    self.assertNotEqual(i18n.tr(message, language), message)

    def test_every_apply_message_and_stage_has_korean_and_japanese(self):
        self.assert_translated(set(apply.MESSAGES) | {mv_studio_timeline.MERGE_LAYOUT})

    def test_every_panel_string_has_korean_and_japanese(self):
        script = (REPO / "webtools/web/static/mv-studio-apply.js").read_text(encoding="utf-8")
        start = script.index("const STRINGS = Object.freeze([") + len("const STRINGS = Object.freeze([")
        strings = ast.literal_eval("[" + script[start:script.index("]);", start)] + "]")
        self.assertGreater(len(strings), 30)
        self.assert_translated(set(strings))
        used = set(re.findall(r'(?:\bt|format|button|ctx\.field)\(\s*"([^"]+)"', script))
        self.assertEqual(sorted(used - set(strings)), [])

    @NEEDS_STORE
    def test_every_stock_store_message_has_korean_and_japanese(self):
        self.assert_translated(set(mv_studio_stock.MESSAGES))


@NEEDS_STORE
@unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file()
                     and (SAMPLES / "i-1203503-live_timeline.unity").is_file(), "Original game samples are optional")
class RealSampleApplyTests(reg_tests.Case):
    """Real 12035 originals as the stock of MV 21 / asset 2101 (Android and iOS): the real parser and
    native rewrite, the store's validator against the TRUE stock, and installation_server with a
    stand-in controller (no real process is ever stopped)."""

    def setUp(self):
        super().setUp()
        self.local["tl2101"] = (SAMPLES / "a-1203503-live_timeline.unity").read_bytes()
        self.local["tl2101i"] = (SAMPLES / "i-1203503-live_timeline.unity").read_bytes()
        from adminui import serverctl
        self.serverctl = serverctl
        self.addCleanup(serverctl.register_controller, None)
        reg_tests.forbid_real_server_kills(self, serverctl)
        mv_studio_stock._VALIDATED.clear()
        self.addCleanup(mv_studio_stock._VALIDATED.clear)
        self.validations = []

        def validate(raw, original, platform, deadline):
            self.validations.append(platform)
            return reg_tests.REAL_VALIDATE(raw, original, platform, deadline)

        for target, name, value in ((mv_studio_timeline, "parse_timeline", reg_tests.REAL_PARSE),
                                    (mv_studio_timeline, "export_timeline", reg_tests.REAL_EXPORT),
                                    (register, "_blob_platform", reg_tests.REAL_BLOB_PLATFORM),
                                    (native, "_validate_timeline", validate),
                                    (register, "_server_session", reg_tests.REAL_SERVER_SESSION),
                                    (register, "_lifecycle", reg_tests.REAL_LIFECYCLE)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def imported(self):
        """The project MV Studio's game import makes of what the game plays now (Android)."""
        timeline = mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2101)
        raw = (register._registered_timelines(self.root, timeline, ["android"])["android"]
               if timeline["platforms"]["android"] == "custom" else self.local["tl2101"])
        path = self.temp / f"timeline-{len(list(self.temp.glob('timeline-*')))}.unity"
        path.write_bytes(raw)
        source = {"kind": "game", "region": "gl", "platform": "android", "liveId": 21, "assetId": 2101, "mvOnly": False,
                  "registered": False, "timelineKey": timeline["timelineKey"]}
        return self.project(platform="android", source=source, tracks=mv_studio._timeline(path)[1]["tracks"],
                            native_bytes=raw)

    def job(self, project, mode, plan=None):
        """One apply job with the app controlling the game server: (job, summary, controller calls)."""
        plan = plan or apply.plan(self.root, project)
        request = apply.validate_apply(self.root, {"mode": mode, "project": project, "platforms": ["android", "ios"],
                                                   "expected": plan["expected"]})
        controller = reg_tests.Controller()
        self.serverctl.register_controller(controller)
        try:
            job = FakeJob()
            summary = apply.run_apply(job, self.root, request)
        finally:
            self.serverctl.register_controller(None)
        return job, summary, controller.calls

    def served(self):
        timeline = mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2101)
        custom = register._registered_timelines(self.root, timeline)
        return {platform: custom.get(platform, self.local["tl2101" + ("i" if platform == "ios" else "")])
                for platform in ("android", "ios")}

    @staticmethod
    def bloom(tracks):
        return next(event for track in tracks if track["nativeClass"] == "LiveBloomTrack" for event in track["events"]
                    if "intensity" in event["editableValues"])

    @staticmethod
    def camera(tracks):
        return next(event for track in tracks if track["kind"] == "camera" for event in track["events"]
                    if "keyframes" in event["editableValues"])

    def test_12035_edits_on_top_conflicts_and_restore(self):
        # The unedited project is a no-op: no stop, no start, no write.
        job, summary, calls = self.job(self.imported(), "edits")
        self.assertEqual((summary, calls), (register.NO_CHANGES, ["begin_job", "finish_job:True"]))
        # Edit 1 (bloom) from the stock; edit 2 (camera fov) from a project also loaded from the stock.
        first, second, third = self.imported(), self.imported(), self.imported()
        self.bloom(first["tracks"])["values"]["intensity"] = 0.7
        job, _, calls = self.job(first, "edits")
        self.assertEqual(calls[:3], ["begin_job", "stop", "start"])
        self.assertEqual(sorted(self.validations), [9, 13], "Validated once per platform (iOS 9, Android 13), before the stop")
        for point in self.camera(second["tracks"])["values"]["keyframes"][:30]:
            point["fov"] = point["fov"] + 2
        self.validations.clear()
        job, _, calls = self.job(second, "edits")
        self.assertIn("stop", calls)
        served = self.served()
        for platform, raw in served.items():
            with self.subTest(platform=platform):
                tracks = register._parse(raw)["tracks"]
                self.assertAlmostEqual(self.bloom(tracks)["values"]["intensity"], 0.7, places=6)
                self.assertEqual([point["fov"] for point in self.camera(tracks)["values"]["keyframes"][:30]],
                                 [point["fov"] for point in self.camera(second["tracks"])["values"]["keyframes"][:30]])
        self.assertEqual(register._parse(served["android"])["tracks"], register._parse(served["ios"])["tracks"])
        # A third project changes the bloom differently: refused, nothing written, the server keeps running.
        self.bloom(third["tracks"])["values"]["intensity"] = 1.25
        plan = apply.plan(self.root, third)
        self.assertEqual({(item["platform"], item["field"]) for item in plan["edits"]["conflicts"]},
                         {("android", "intensity"), ("ios", "intensity")})
        before = self.served()
        controller = reg_tests.Controller()
        self.serverctl.register_controller(controller)
        try:
            request = apply.validate_apply(self.root, {"mode": "edits", "project": third, "platforms": ["android", "ios"],
                                                       "expected": plan["expected"]})
            with self.assertRaises(apply.ConflictError):
                apply.run_apply(FakeJob(), self.root, request)
        finally:
            self.serverctl.register_controller(None)
        self.assertNotIn("stop", controller.calls)
        self.assertEqual(self.served(), before)
        # Restore: the game plays the exact stock bytes again on both platforms.
        timeline = mv_studio_live.describe_mv_timeline(self.root, region="gl", asset_id=2101)
        request = apply.validate_restore({"region": "gl", "assetId": 2101, "expected": {"key": timeline["timelineKey"]}})
        controller = reg_tests.Controller()
        self.serverctl.register_controller(controller)
        try:
            job = FakeJob()
            apply.run_restore(job, self.root, request)
        finally:
            self.serverctl.register_controller(None)
        self.assertEqual(controller.calls[:3], ["begin_job", "stop", "start"])
        self.assertEqual(self.served(), {"android": self.local["tl2101"], "ios": self.local["tl2101i"]})
        for platform, pack in (("android", "tl2101"), ("ios", "tl2101i")):
            descriptor, _ = register._first_catalog_row(self.root, "gl", platform, "en", "live_timeline",
                                                        mv_studio_live.describe_mv_timeline(
                                                            self.root, region="gl", asset_id=2101)["timelineKey"])
            self.assertEqual(descriptor["pack_name"], pack)


if __name__ == "__main__":
    unittest.main()
