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

    def test_cancelling_from_a_report_unwinds_and_releases_the_import(self):
        def cancel(event):
            if event.get("step") == "member" and event.get("state") == "start":
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
        on_progress({"type": "progress", "step": "stage", "state": "start", "t": .1, "read": 0})
        on_stage(self.stage)
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
