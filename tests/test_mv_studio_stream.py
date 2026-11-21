"""HTTP contract for the opt-in stage-first MV import."""

import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import struct
import threading
import unittest
from unittest.mock import patch

from webtools.core import mv_studio
from webtools.server import Handler


class MVStudioStreamTests(unittest.TestCase):
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
        self.stage = {"stage": {"glb": "/api/mv-studio/media/" + "c" * 32 + ".glb"},
                      "assets": [], "tracks": [], "quality": {}, "duration": 3}
        self.project = {**self.stage, "token": "a" * 32, "performers": [{"name": "School idol"}]}
        patcher = patch.object(mv_studio, "load_game", return_value=self.project)
        self.load = patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, action="game-stream", *, payload=None, headers=None, method="POST"):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        self.addCleanup(connection.close)
        body = json.dumps(self.request if payload is None else payload) if method == "POST" else None
        connection.request(method, "/api/mv-studio/" + action + "?lang=ko", body,
                           {"Content-Type": "application/json", **(headers or {})})
        return connection.getresponse()

    def request_bytes(self):
        body = json.dumps(self.request).encode()
        head = (f"POST /api/mv-studio/game-stream HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode()
        return head + body

    def test_flushes_stage_before_cast_and_matches_standard_response(self):
        allow_cast = threading.Event()

        def load(*_args, on_stage=None, **_kwargs):
            if on_stage is not None:
                on_stage(self.stage)
                if not allow_cast.wait(5):
                    raise RuntimeError("Client did not receive the staged preview.")
            return self.project

        self.load.side_effect = load
        payload = {**self.request, "download": True}
        local_origin = {"Origin": f"http://{self.host}:{self.port}", "Sec-Fetch-Site": "same-origin"}
        try:
            with self.connect(payload=payload, headers=local_origin) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "application/x-ndjson; charset=utf-8")
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                self.assertEqual(response.getheader("Connection"), "close")
                self.assertIsNone(response.getheader("Content-Length"))
                self.assertIsNone(response.getheader("Transfer-Encoding"))
                stage = response.readline()
                self.assertTrue(stage.endswith(b"\n"))
                self.assertGreaterEqual(len(stage), 4096)
                self.assertEqual(json.loads(stage), {"type": "stage", "preview": self.stage})
                self.assertFalse(allow_cast.is_set())
                allow_cast.set()
                terminal = response.readline()
                self.assertTrue(terminal.endswith(b"\n"))
                self.assertEqual(json.loads(terminal), {"type": "complete", "project": self.project})
                self.assertEqual(response.read(), b"")
            self.load.assert_called_once()
        finally:
            allow_cast.set()

        with self.connect("game", payload=payload, headers=local_origin) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
            self.assertIsNotNone(response.getheader("Content-Length"))
            self.assertEqual(json.load(response), self.project)
        stream, legacy = self.load.call_args_list
        options = dict(stream.kwargs)
        self.assertTrue(callable(options.pop("on_stage")))
        self.assertEqual(stream.args, legacy.args)
        self.assertEqual(stream.args, (Path.cwd(),))
        self.assertEqual(options, legacy.kwargs)
        self.assertEqual(legacy.kwargs, {"language": "ko", "region": "gl", "platform": "android",
                                        "live_id": 12002, "asset_id": 1200203, "download": True})

    def test_complete_without_stage(self):
        with self.connect() as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/x-ndjson; charset=utf-8")
            lines = response.readlines()
        self.assertEqual([json.loads(line) for line in lines], [{"type": "complete", "project": self.project}])
        self.load.assert_called_once()
        self.assertIs(self.load.call_args.kwargs["download"], False)

    def test_reports_one_terminal_error_after_stage(self):
        def load(*_args, on_stage, **_kwargs):
            on_stage(self.stage)
            raise ValueError("The cast could not be loaded.")

        self.load.side_effect = load
        with self.connect() as response:
            self.assertEqual(response.status, 200)
            lines = response.readlines()
        self.assertEqual([json.loads(line) for line in lines], [
            {"type": "stage", "preview": self.stage}, {"type": "error", "error": "The cast could not be loaded."}])
        self.assertTrue(all(line.endswith(b"\n") for line in lines))

    def test_pre_stream_error_keeps_standard_http_status(self):
        self.load.side_effect = ValueError("Choose a supported game selection.")
        for action in ("game", "game-stream"):
            with self.connect(action) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
                self.assertEqual(json.load(response), {"error": "Choose a supported game selection."})

    def test_shared_origin_and_field_guards(self):
        for action in ("game", "game-stream"):
            with self.connect(action, headers={"Origin": "https://foreign.example"}) as response:
                self.assertEqual(response.status, 403)
                self.assertIn("Open the editor", json.load(response)["error"])
            with self.connect(action, headers={"Sec-Fetch-Site": "cross-site"}) as response:
                self.assertEqual(response.status, 403)
                self.assertIn("Open the editor", json.load(response)["error"])
            with self.connect(action, payload={**self.request, "callerPath": "/tmp/bad"}) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual(json.load(response), {"error": "Unsupported editing request."})
        self.load.assert_not_called()

    def test_unavailable_method_or_route_remains_standard_json_404(self):
        for action, method in (("game-stream", "GET"), ("unsupported-stream", "POST")):
            with self.connect(action, method=method) as response:
                self.assertEqual(response.status, 404)
                self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
                self.assertEqual(json.load(response), {"error": "not found"})
        self.load.assert_not_called()

    def test_reset_peer_stops_work_at_stage_write(self):
        entered, send_stage, released, cast_started = (threading.Event() for _ in range(4))

        def load(*_args, on_stage, **_kwargs):
            try:
                entered.set()
                if not send_stage.wait(5):
                    raise RuntimeError("Client did not close the connection.")
                on_stage(self.stage)
                cast_started.set()
                return self.project
            finally:
                released.set()

        self.load.side_effect = load
        with socket.create_connection((self.host, self.port), timeout=5) as client:
            client.sendall(self.request_bytes())
            try:
                self.assertTrue(entered.wait(5))
                # Close with TCP RST so the server's first write observes disconnect.
                layout = "hh" if os.name == "nt" else "ii"
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(layout, 1, 0))
            finally:
                client.close()
                send_stage.set()
        self.assertTrue(released.wait(5))
        self.assertFalse(cast_started.is_set())
        self.load.assert_called_once()

    def test_slow_peer_stops_work_at_the_write_deadline(self):
        released, cast_started = threading.Event(), threading.Event()

        def load(*_args, on_stage, **_kwargs):
            try:
                on_stage({**self.stage, "assets": [{"label": "x" * (1024 * 1024)}]})
                cast_started.set()
                return self.project
            finally:
                released.set()

        accept = self.server.get_request

        def accept_with_small_buffer():
            connection, address = accept()
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            return connection, address

        self.load.side_effect = load
        with (patch.object(self.server, "get_request", side_effect=accept_with_small_buffer),
              patch("webtools.server._MV_STREAM_WRITE_TIMEOUT", 0.1),
              socket.create_connection((self.host, self.port), timeout=5) as client):
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            client.sendall(self.request_bytes())
            # Keep the peer connected without consuming any response bytes.
            self.assertTrue(released.wait(5))
            self.assertFalse(cast_started.is_set())
        self.load.assert_called_once()


if __name__ == "__main__":
    unittest.main()
