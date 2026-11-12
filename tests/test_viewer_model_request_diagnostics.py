"""Real HTTP coverage for bounded native-path requests and concrete failures."""
from contextlib import contextmanager
import http.client
import json
from types import SimpleNamespace
from unittest.mock import patch

from test_viewer_workbench_routes import WorkbenchHTTPBase
from webtools.core import model_viewer


class ModelRequestDiagnosticsTests(WorkbenchHTTPBase):
    def setUp(self):
        super().setUp()
        self.source = self.library / "body.unity"
        self.source.write_bytes(b"transport fixture; decoder is patched separately")

    @staticmethod
    @contextmanager
    def expanded(paths, *args, **kwargs):
        # Exercise the real HTTP parser/path jail before the costly asset decoder.
        yield SimpleNamespace(paths=list(paths), manifest_paths=[], origins={},
                              source_names=[str(path) for path in paths], variants=[])

    def payload(self, motions=()):
        return {"paths": [str(self.source)], "motion_paths": list(motions),
                "auto_face": False, "rigged": True, "preview_only": True}

    def long_paths(self, count):
        directory = self.library / "캐릭터 모션"
        for index in range(7):
            directory /= "native-folder-" + str(index) + "-" + "x" * 64
        directory.mkdir(parents=True)
        result = []
        for index in range(count):
            path = directory / ("motion-%03d.unity" % index)
            path.write_bytes(b"transport fixture")
            result.append(str(path))
        return result

    def assert_accepted(self, count):
        paths = self.long_paths(count)
        request = self.payload(paths)
        wire = json.dumps(request).encode()
        self.assertGreater(len(wire), 16384)
        self.assertLess(len(wire), 256 * 1024)
        result = {"id": "a" * 32, "url": "/api/viewer/model/" + "a" * 32 + ".glb", "rig": {}}
        with patch("webtools.core.viewer_archive.expand_inputs", self.expanded), \
                patch.object(model_viewer, "prepare", return_value=result) as prepare:
            status, data = self.request("/api/viewer/prepare", request)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["id"], "a" * 32)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(prepare.call_args.kwargs["motion_paths"], paths)
        self.assertEqual(self.source.read_bytes(), b"transport fixture; decoder is patched separately")

    def test_32_long_native_paths_pass_the_former_16k_request_limit(self):
        self.assert_accepted(32)

    def test_256_long_native_paths_reach_the_bounded_decoder_together(self):
        self.assert_accepted(256)

    def test_257_sources_report_the_exact_count_and_limit_without_decoding(self):
        with patch.object(model_viewer, "prepare") as prepare:
            status, data = self.request("/api/viewer/prepare", self.payload([str(self.source)] * 257))
        self.assertEqual(status, 400)
        self.assertEqual(data["error_code"], "motion_source_limit")
        self.assertEqual(data["motion_files"], 257)
        self.assertEqual(data["max_motion_files"], 256)
        self.assertIn("257", data["error"])
        self.assertIn("256", data["error"])
        prepare.assert_not_called()

    def test_invalid_path_identifies_its_kind_and_ordinal(self):
        cases = [(self.payload([""]), "motion_path", "Motion source 1"),
                 ({**self.payload(), "paths": ["/" + "x" * 4096]}, "model_path_size", "4097")]
        with patch.object(model_viewer, "prepare") as prepare:
            for payload, code, detail in cases:
                with self.subTest(code=code):
                    status, data = self.request("/api/viewer/prepare", payload)
                    self.assertEqual(status, 400)
                    self.assertEqual(data["error_code"], code)
                    self.assertIn(detail, data["error"])
        prepare.assert_not_called()

    def test_oversize_header_reports_bytes_without_reading_an_unbounded_body(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        self.addCleanup(connection.close)
        connection.putrequest("POST", "/api/viewer/prepare")
        connection.putheader("Content-Length", str(256 * 1024 + 1))
        connection.putheader("Content-Type", "application/json")
        connection.endheaders()
        response = connection.getresponse()
        data = json.loads(response.read())
        self.assertEqual(response.status, 400)
        self.assertEqual(data["error_code"], "request_size")
        self.assertEqual(data["request_bytes"], 256 * 1024 + 1)
        self.assertEqual(data["max_request_bytes"], 256 * 1024)

    def test_decoder_and_server_errors_keep_the_underlying_reason(self):
        for error, expected in [(ValueError("Donor mesh Hair has no readable UV0"), 400),
                                (RuntimeError("Model cache write failed: disk full"), 500)]:
            with self.subTest(error=type(error).__name__), \
                    patch("webtools.core.viewer_archive.expand_inputs", self.expanded), \
                    patch.object(model_viewer, "prepare", side_effect=error):
                status, data = self.request("/api/viewer/prepare", self.payload())
                self.assertEqual(status, expected, data)
                self.assertEqual(data["error"], str(error))
