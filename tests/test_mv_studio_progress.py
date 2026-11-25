"""Opt-in import progress records, cancellation and their effect on the imported project."""
from copy import deepcopy
from hashlib import sha256
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from webtools.core import (cri_audio_decode, mv_studio, mv_studio_actor_cache, mv_studio_game, mv_studio_progress,
                           mv_studio_quality)
from webtools.server import Handler


class ProgressTests(unittest.TestCase):
    def test_ticks_are_throttled_but_states_and_phases_always_report(self):
        now = [10.]
        events = []
        progress = mv_studio_progress.Progress(events.append, interval=.15, clock=lambda: now[0])
        progress.plan([{"id": "resolve"}, {"id": "member", "index": 1, "of": 1, "bytes": 5}], 1, 5)
        progress.state("member", "start", index=1, of=1, name="Ayumu")
        with mv_studio_progress.active(progress):
            mv_studio_progress.tick("textures", 1)  # inside the interval: dropped
            now[0] += .2
            mv_studio_progress.tick("textures", 2)
            mv_studio_progress.tick("textures", 3)  # dropped again
            progress.phase("animation")  # a phase change always reports
            other = threading.Thread(target=mv_studio_progress.tick, args=("textures", 9))
            now[0] += 1
            other.start()
            other.join()  # another thread never reports into this import
        mv_studio_progress.tick("textures", 4)  # no import active on this thread any more
        progress.read(7)
        progress.state("member", "done", index=1, of=1)
        self.assertEqual([event.get("state") or event.get("phase") for event in events],
                         [None, "start", "textures", "animation", "done"])
        plan = events[0]
        self.assertEqual(plan["type"], "plan")
        self.assertEqual(plan["steps"][1], {"id": "member", "w": mv_studio_progress.WEIGHTS["member"],
                                            "label": mv_studio_progress.LABELS["member"], "bytes": 5, "index": 1, "of": 1})
        self.assertEqual(events[2], {"type": "progress", "step": "member", "phase": "textures", "index": 1, "of": 1,
                                     "name": "Ayumu", "done": 2, "t": .2, "read": 0})
        self.assertEqual(events[-1]["read"], 7)
        for event in events:
            self.assertLess(len(json.dumps(event, ensure_ascii=False).encode()), 600)
        with self.assertRaises(ValueError):
            progress.state("unknown", "start")

    def test_cancellation_is_not_an_ordinary_exception(self):
        self.assertTrue(issubclass(mv_studio_progress.ImportCancelled, BaseException))
        self.assertFalse(issubclass(mv_studio_progress.ImportCancelled, Exception))

    def test_deadline_checks_are_throttled_cancellation_points(self):
        from webtools.core import decode, model_viewer
        now = [5.]
        events = []
        progress = mv_studio_progress.Progress(events.append, interval=.15, clock=lambda: now[0])
        model_viewer._remaining(time.monotonic() + 10)  # no import on this thread: nothing happens
        with mv_studio_progress.active(progress):
            model_viewer._remaining(time.monotonic() + 10)
            decode._remaining(time.monotonic() + 10)  # inside the interval
            now[0] += .2
            decode._remaining(time.monotonic() + 10)
            other = threading.Thread(target=mv_studio_progress.alive)
            now[0] += 1
            other.start()
            other.join()  # another thread (a mip decode) never reports into this import
        self.assertEqual(events, [None, None], "a check has nothing to report")
        progress.tick("textures", 1)
        self.assertEqual(len(events), 3, "checks do not hold back the next record")

        def leave(event):
            if event is None:
                raise mv_studio_progress.ImportCancelled()

        with mv_studio_progress.active(mv_studio_progress.Progress(leave)):
            with self.assertRaises(mv_studio_progress.ImportCancelled):
                model_viewer._remaining(time.monotonic() + 10)


class GameImportErrorTextTests(unittest.TestCase):
    def test_errors_a_person_can_meet_have_korean_and_japanese_text(self):
        from webtools import i18n
        sources = "".join(Path(module.__file__).read_text(encoding="utf-8") for module in (mv_studio, mv_studio_game))
        for message in ("An MV is already being prepared. Try again when it finishes.",
                        "The original MV timeline pack is missing. Download its missing assets or choose a local mod file.",
                        "This file does not contain an original live timeline.",
                        "Reading the selected MV assets took too long. Try again.",
                        "The selected game MV and stage are no longer available. Refresh the list.",
                        "The selected game pack changed during import. Try again.",
                        "A requested costume has no member at its position in this MV."):
            with self.subTest(message=message):
                self.assertIn(json.dumps(message), sources, "the text the import raises")
                for language in ("ko", "ja"):
                    self.assertNotEqual(i18n.tr(message, language), message, language)


class TimelineParseProgressTests(unittest.TestCase):
    """The timeline step reports its bundle, tracks and effect readers, and stops inside the parse."""

    def parse(self, progress=None):
        from types import SimpleNamespace
        from webtools.core import mv_studio_timeline
        files = SimpleNamespace(name="CAB-x")

        def item(path, tree):
            return SimpleNamespace(type=SimpleNamespace(name="MonoBehaviour"), path_id=path, assets_file=files,
                                   read_typetree=lambda: deepcopy(tree), peek_name=lambda: tree.get("m_Name"))

        objects = {("cab-x", 2): item(2, {"m_Name": "Timeline", "m_Script": {"m_FileID": 0, "m_PathID": 1},
                                          "m_Tracks": [{"m_FileID": 0, "m_PathID": 3}], "m_FixedDuration": 2.}),
                   ("cab-x", 3): item(3, {"m_Name": "Bloom", "m_Script": {"m_FileID": 0, "m_PathID": 4},
                                          "m_Parent": {"m_FileID": 0, "m_PathID": 2}, "m_Clips": [], "m_Children": []})}
        source = {"scripts": {("cab-x", 1): "TimelineAsset", ("cab-x", 4): "BloomTrack"}, "name": "x"}
        flags = {name: True for name in ("preview_split", "preview_stage_motion", "preview_stage_title",
                                         "preview_particle_systems", "preview_control_prefabs")}
        with patch.object(mv_studio_timeline, "_read", return_value=(None, objects, source)):
            if progress is None:
                return mv_studio_timeline.parse_timeline(b"raw", "x", **flags)
            with mv_studio_progress.active(progress):
                return mv_studio_timeline.parse_timeline(b"raw", "x", **flags)

    def test_phases_follow_the_parse_and_leave_it_unchanged(self):
        events = []
        parsed = self.parse(mv_studio_progress.Progress(events.append, interval=0))
        self.assertEqual(parsed, self.parse())
        phases = [(event["phase"], event.get("done"), event.get("total")) for event in events if event and "phase" in event]
        self.assertEqual(phases, [("bundle", None, None), ("tracks", None, None)] + [("effects", k, 5) for k in range(5)])

    def test_a_client_that_left_stops_the_parse(self):
        def leave(event):
            if event is None:
                raise mv_studio_progress.ImportCancelled()

        with self.assertRaises(mv_studio_progress.ImportCancelled):
            self.parse(mv_studio_progress.Progress(leave, interval=0))


class LoadGameProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.missing, self.failed, self.history = set(), set(), []
        self.selection = {
            "name": "Progress fixture", "region": "gl", "platform": "android", "liveId": 10, "assetId": 11,
            "timeline": self.asset("timeline", 300),
            "choreography": [self.asset("dance", 40)],
            "stage": {"name": "Original stage", "model": self.asset("stage", 200), "effect": self.asset("effect", 100),
                      "props": self.asset("props", 10)},
            "performers": [{"position": 1, "memberId": 210, "memberName": "Ayumu", "model": self.asset("actor", 900),
                            "companions": [self.asset("face", 50)]},
                           {"position": 2, "memberId": 211, "memberName": "Kasumi", "model": self.asset("actor2", 800)}],
            "audio": {"cue": "song", "acb": self.asset("audio", 70), "awb": self.asset("wave", 30)},
        }
        self.addCleanup(patch.stopall)
        patch.object(mv_studio_game, "resolve", return_value=self.selection).start()
        patch.object(mv_studio_game, "load_asset", side_effect=self.load_asset).start()
        patch.object(mv_studio_quality, "read_quality", return_value={"values": {}}).start()
        patch.object(mv_studio_actor_cache, "open_cache", return_value=None).start()
        patch.object(mv_studio, "_root", return_value=self.root).start()
        patch.object(mv_studio, "_timeline", side_effect=lambda path: (path.read_bytes(), {
            "duration": 12.0, "tracks": [{"id": "t", "kind": "camera", "label": "camera", "events": []}]})).start()
        patch.object(mv_studio, "_preview", side_effect=self.preview).start()
        patch.object(mv_studio, "_motion", side_effect=lambda *args: ([], {"bodySegments": []})).start()
        patch.object(mv_studio, "_facial", side_effect=lambda timeline, motion, *args: motion).start()
        patch.object(cri_audio_decode, "decode_cue").start()
        patch.object(mv_studio, "_song_audio", return_value={"url": "/api/mv-studio/media/test.wav", "duration": 14.0}).start()
        patch.object(mv_studio, "_register", side_effect=lambda project, native: {**project, "token": "t" * 32}).start()

    @staticmethod
    def asset(name, size):
        return {"table": "test-assets", "asset": name, "available": True, "size": size}

    def load_asset(self, root, descriptor, *, download, deadline):
        name = descriptor["asset"]
        self.history.append(("load", name))
        return None if name in self.missing else name.encode()

    def preview(self, path, **kwargs):
        name = path.read_bytes().decode()
        self.history.append(("preview", name))
        if name in self.failed:
            raise ValueError("Invalid preview")
        if name == "actor":
            mv_studio_progress.tick("textures", 1)
        return f"/api/mv-studio/media/{sha256(name.encode()).hexdigest()[:32]}.glb", {"clips": []} if kwargs.get("performer") else {}

    def import_game(self, **kwargs):
        return mv_studio.load_game(self.root, region="gl", platform="android", live_id=10, asset_id=11, language="en",
                                   **kwargs)

    def test_events_follow_the_import_and_leave_the_project_unchanged(self):
        baseline = self.import_game()
        events, order = [], []
        project = self.import_game(on_progress=lambda event: (events.append(deepcopy(event)), order.append("progress")),
                                   on_stage=lambda preview: order.append("stage"))
        self.assertEqual(project, baseline)
        plan = events[0]
        self.assertEqual((plan["type"], plan["v"], plan["members"], plan["bytes"]), ("plan", 1, 2, 2500))
        self.assertEqual([(step["id"], step.get("index"), step.get("bytes")) for step in plan["steps"]],
                         [("resolve", None, None), ("timeline", None, 340), ("stage", None, 200), ("effect", None, 100),
                          ("props", None, 10), ("member", 1, 950), ("member", 2, 800), ("audio", None, 100),
                          ("finish", None, None)])
        states = [(event["step"], event.get("index"), event["state"]) for event in events if "state" in event]
        self.assertEqual(states, [
            ("resolve", None, "done"), ("timeline", None, "start"), ("timeline", None, "done"),
            ("stage", None, "start"), ("stage", None, "done"), ("effect", None, "start"), ("effect", None, "done"),
            ("props", None, "start"), ("props", None, "done"),
            ("member", 1, "start"), ("member", 1, "done"), ("member", 2, "start"), ("member", 2, "done"),
            ("audio", None, "start"), ("audio", None, "done"), ("finish", None, "start"), ("finish", None, "done")])
        member = next(event for event in events if event.get("state") == "start" and event.get("index") == 2)
        self.assertEqual((member["name"], member["of"]), ("Kasumi", 2))
        self.assertEqual([event["phase"] for event in events if "phase" in event][:1], ["motion"])
        # The stage preview still precedes the cast.
        self.assertEqual(order.index("stage"), 1 + next(index for index, event in enumerate(events)
                                                         if event.get("step") == "props" and event.get("state") == "done"))
        # Bytes actually read: the fixture's sections are their names.
        self.assertEqual(events[-1]["read"], sum(len(name) for kind, name in self.history[len(self.history) // 2:]
                                                 if kind == "load"))
        self.assertTrue(all(earlier["t"] <= later["t"] for earlier, later in zip(events, events[1:])))
        json.dumps(events, allow_nan=False)

    def test_missing_and_failed_steps_are_reported(self):
        self.missing.add("effect")
        self.failed.add("stage")
        self.missing.add("actor2")
        events = []
        project = self.import_game(on_progress=events.append)
        states = {(event["step"], event.get("index")): event["state"] for event in events if "state" in event}
        self.assertEqual(states[("stage", None)], "failed")
        self.assertEqual(states[("effect", None)], "skipped")
        self.assertEqual(states[("member", 2)], "skipped")
        self.assertEqual(states[("member", 1)], "done")
        self.assertIn("Original stage: Invalid preview", project["warnings"])

    def test_receipts_are_written_only_after_a_complete_import(self):
        from webtools.core import mv_studio_import_cache
        directory = self.root / "receipts"
        directory.mkdir(mode=0o700)
        parsed = {"duration": 12.0, "tracks": [{"id": "t", "kind": "camera", "label": "camera", "events": []}]}

        def open_cache(media, folder="imports", **limits):
            return mv_studio_import_cache.ImportCache(directory, media, **limits) if folder == "imports" else None

        def timeline(path, store=None, reused=None):
            if store is not None:
                store.put(store.key("timeline", path.read_bytes().decode()), parsed)
            # The import edits what it parsed; the receipt keeps it as parsed.
            return path.read_bytes(), deepcopy(parsed)

        receipts = lambda: sorted(directory.glob("*.receipt"))
        with (patch.object(mv_studio_import_cache, "open_cache", side_effect=open_cache),
              patch.object(mv_studio, "_timeline", side_effect=timeline)):
            later = []
            self.import_game(later=later)
            self.assertEqual(receipts(), [], "nothing is written while the project is on its way")
            self.assertEqual(len(later), 1)
            later[0]()
            written = receipts()
            self.assertEqual(len(written), 2, "the timeline and the soundtrack")
            store = open_cache(mv_studio.media)
            self.assertEqual(store.get(store.key("timeline", "timeline")), parsed)
            for path in written:
                path.unlink()
            # Without a list the receipts are written before the import returns.
            self.import_game()
            self.assertEqual(receipts(), written)
            for path in written:
                path.unlink()

            # A cancelled or failed import writes none.
            def cancel(event):
                if event and event.get("step") == "audio":
                    raise mv_studio_progress.ImportCancelled()

            later = []
            with self.assertRaises(mv_studio_progress.ImportCancelled):
                self.import_game(on_progress=cancel, later=later)
            self.assertEqual((later, receipts()), ([], []))
            with self.assertRaises(TypeError):
                self.import_game(later=())

    def test_a_new_import_waits_for_one_that_is_stopping(self):
        mv_studio._IMPORT.acquire()
        timer = threading.Timer(.3, mv_studio._IMPORT.release)
        timer.start()
        self.addCleanup(timer.join)
        started = time.monotonic()
        self.assertEqual(self.import_game()["name"], "Progress fixture")
        self.assertGreaterEqual(time.monotonic() - started, .25)
        # One that keeps running past the wait is still refused.
        mv_studio._IMPORT.acquire()
        self.addCleanup(mv_studio._IMPORT.release)
        with patch.object(mv_studio, "_IMPORT_WAIT_SECONDS", .1), self.assertRaisesRegex(ValueError, "already being prepared"):
            self.import_game()

    def test_cancelling_from_a_report_unwinds_and_releases_the_import(self):
        def cancel(event):
            if event and event.get("step") == "member" and event.get("state") == "start":
                raise mv_studio_progress.ImportCancelled()

        with self.assertRaises(mv_studio_progress.ImportCancelled):
            self.import_game(on_progress=cancel)
        self.assertNotIn(("preview", "actor"), self.history)
        self.assertTrue(mv_studio._IMPORT.acquire(blocking=False))
        mv_studio._IMPORT.release()
        self.assertEqual(list(self.root.glob("import-*")), [])
        # The next import runs normally and nothing reports on this thread any more.
        self.assertEqual(self.import_game()["name"], "Progress fixture")
        self.assertIsNone(getattr(mv_studio_progress._LOCAL, "progress", None))


class PeerWatchTests(unittest.TestCase):
    def test_open_closed_and_reset_peers(self):
        from webtools.server import _PeerWatch
        for how in ("open", "close", "reset", "data"):
            with self.subTest(how=how):
                server, client = socket.socketpair()
                try:
                    watch = _PeerWatch(server, interval=0)
                    self.assertFalse(watch.check())
                    if how == "close":
                        client.close()
                    elif how == "reset":
                        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\1\0\0\0\0\0\0\0")
                        client.close()
                    elif how == "data":
                        client.sendall(b"x")  # unexpected bytes are not a disconnect, and stay unread
                    self.assertEqual(watch.check(), how in ("close", "reset"))
                    if how == "data":
                        self.assertEqual(server.recv(1), b"x")
                finally:
                    server.close()
                    if how in ("open", "data"):
                        client.close()

    def test_checks_are_throttled(self):
        from webtools.server import _PeerWatch
        server, client = socket.socketpair()
        try:
            watch = _PeerWatch(server, interval=60)
            self.assertFalse(watch.check())
            client.close()
            self.assertFalse(watch.check(), "the next look is not due yet")
        finally:
            server.close()


class ServerProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.server.server_address

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def setUp(self):
        self.request = {"region": "gl", "platform": "android", "liveId": 12002, "assetId": 1200203}
        self.stage = {"stage": {"glb": "/api/mv-studio/media/" + "c" * 32 + ".glb"}, "assets": [], "tracks": [],
                      "quality": {}, "duration": 3}
        self.project = {**self.stage, "token": "a" * 32, "performers": []}

    def connect(self, query=""):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("POST", "/api/mv-studio/game-stream?lang=ko" + query, json.dumps(self.request),
                           {"Content-Type": "application/json"})
        return connection.getresponse()

    def fake_import(self, *_args, on_stage, on_progress, **_kwargs):
        on_progress({"type": "plan", "v": 1, "members": 0, "bytes": 0, "steps": [{"id": "resolve", "w": 1}]})
        on_progress(None)  # a cancellation check: nothing is written
        on_progress({"type": "progress", "step": "stage", "state": "start", "t": .1, "read": 0})
        on_stage(self.stage)
        on_progress(None)
        on_progress({"type": "progress", "step": "finish", "state": "done", "t": .2, "read": 0})
        return self.project

    def test_records_are_added_only_when_requested(self):
        with patch.object(mv_studio, "load_game", side_effect=self.fake_import):
            with self.connect("&progress=1") as response:
                self.assertEqual(response.status, 200)
                lines = response.read().split(b"\n")
            self.assertGreaterEqual(len(lines[0]) + 1, 4096, "the first record passes browser buffering")
            self.assertEqual([json.loads(line)["type"] for line in lines if line],
                             ["plan", "progress", "stage", "progress", "complete"])
            with self.connect() as response:
                legacy = response.read()
        self.assertEqual([json.loads(line) for line in legacy.split(b"\n") if line],
                         [{"type": "stage", "preview": self.stage}, {"type": "complete", "project": self.project}])

    def test_the_stream_ends_before_the_deferred_receipt_writes(self):
        # The page waits for the end of the stream; slow deferred writes must not hold it.
        written = threading.Event()

        def slow_write():
            time.sleep(2)
            written.set()

        def fake_import(*args, later, **kwargs):
            later.append(slow_write)
            return self.fake_import(*args, **kwargs)

        with patch.object(mv_studio, "load_game", side_effect=fake_import):
            for query in ("&progress=1", ""):
                written.clear()
                with self.subTest(query=query):
                    started = time.monotonic()
                    with self.connect(query) as response:
                        lines = [json.loads(line) for line in response.read().split(b"\n") if line]
                    self.assertLess(time.monotonic() - started, 1.)
                    self.assertFalse(written.is_set())
                    self.assertEqual(lines[-1], {"type": "complete", "project": self.project})
                    self.assertTrue(written.wait(5), "the deferred writes still run")

    def test_a_closed_client_releases_the_real_import_at_its_next_report(self):
        reports, released = [], threading.Event()

        def busy_quality(*_args, **_kwargs):
            # Converters report ticks from deep inside the import, like texture decoding.
            try:
                for index in range(2000):
                    mv_studio_progress.tick("textures", index)
                    reports.append(time.monotonic())
                    time.sleep(.005)
                raise AssertionError("The import was never cancelled.")
            finally:
                released.set()

        selection = {"name": "Busy", "region": "gl", "platform": "android", "liveId": 1, "assetId": 2, "performers": []}
        with (patch.object(mv_studio_game, "resolve", return_value=selection),
              patch.object(mv_studio_quality, "read_quality", side_effect=busy_quality)):
            for query in ("&progress=1", ""):
                reports.clear()
                released.clear()
                with self.subTest(query=query):
                    client = socket.create_connection((self.host, self.port), timeout=5)
                    body = json.dumps(self.request).encode()
                    client.sendall((f"POST /api/mv-studio/game-stream?lang=en{query} HTTP/1.1\r\n"
                                    f"Host: {self.host}:{self.port}\r\nContent-Type: application/json\r\n"
                                    f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
                    deadline = time.monotonic() + 5
                    while len(reports) < 20 and time.monotonic() < deadline:
                        time.sleep(.01)
                    closed = time.monotonic()
                    client.close()
                    self.assertTrue(released.wait(5))
                    self.assertLess(reports[-1] - closed, 1.)
                    for _ in range(100):
                        if mv_studio._IMPORT.acquire(blocking=False):
                            mv_studio._IMPORT.release()
                            break
                        time.sleep(.01)
                    else:
                        self.fail("The cancelled import kept the import slot.")


if __name__ == "__main__":
    unittest.main()
