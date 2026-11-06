"""Real export/package receipts; installer hand-off unit tests mock the runner.

No test executes the costume installer. Runtime databases are tiny disposable
gate fixtures only. Real installer/backup integration is a separate QA flow.
"""
import ast
from collections import OrderedDict
import copy
import hashlib
from http.server import ThreadingHTTPServer
import http.client
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from webtools.core import viewer_mod_flow as flow

PARENT_ROOT = Path(__file__).resolve().parents[2]
PARENT_INSTALLERS = (PARENT_ROOT / "adminui/tools/installers.py").is_file()

try:
    import UnityPy
    from webtools.core import model_edits, model_viewer
    AVAILABLE = importlib.util.find_spec("webtools.core.viewer_mod_pair_edits") is not None
except ImportError:
    AVAILABLE = False


class Job:
    def __init__(self):
        self.stopped = False
        self.messages = []

    def should_stop(self):
        return self.stopped

    def log(self, message):
        self.messages.append(message)

    def progress(self, *values):
        pass


class ViewerModOptionsTests(unittest.TestCase):
    def test_options_require_valid_name_character_and_complete_counterpart_choice(self):
        self.assertEqual(flow.validate_options("  Edited costume  ", 6, None, None), "Edited costume")
        self.assertEqual(flow.validate_options("자동 이름", None, None, None), "자동 이름")
        self.assertEqual(flow.validate_options("Rina pair", 209, "/authorized/other.unity", "unmasked"), "Rina pair")
        cases = [("", 6, None, None), ("x" * 121, 6, None, None),
                 ("line\nbreak", 6, None, None), ("name", True, None, None),
                 ("name", 0, None, None), ("name", "6", None, None),
                 ("name", 6, "", None), ("name", 209, "/other", None),
                 ("name", 209, None, "primary"), ("name", 209, "/other", "guess")]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                flow.validate_options(*values)


class ViewerModWriteOriginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from webtools.server import Handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def request(self, path, body, host, origin, **headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", path, body=json.dumps(body), headers={
                "Host": host, "Origin": origin, "Content-Type": "application/json", **headers})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_matching_attacker_host_origin_and_wrong_bound_port_are_rejected(self):
        requests = [("/api/viewer/edit/install", {"package_token": "0" * 32}),
                    ("/api/viewer/edit/package", {"token": "0" * 32, "state": {}, "display_name": "QA",
                        "character_id": 6, "counterpart_path": None, "selected_variant": None})]
        for host in ("attacker.invalid:" + str(self.server.server_port), "127.0.0.1:1"):
            for path, body in requests:
                with self.subTest(host=host, path=path):
                    status, response = self.request(path, body, host, "http://" + host)
                    self.assertEqual(status, 403, response)
        host = "127.0.0.1:" + str(self.server.server_port)
        status, response = self.request("/api/viewer/edit/install", {"package_token": "0" * 32},
                                        host, "http://" + host, **{"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403, response)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            body = json.dumps({"package_token": "0" * 32}).encode()
            connection.putrequest("POST", "/api/viewer/edit/install", skip_host=True)
            connection.putheader("Host", host)
            connection.putheader("Host", host)
            connection.putheader("Origin", "http://" + host)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            self.assertEqual(response.status, 403, response.read())
        finally:
            connection.close()

    def test_real_bound_loopback_origin_reaches_opaque_token_guard(self):
        for name in ("127.0.0.1", "localhost"):
            host = name + ":" + str(self.server.server_port)
            with self.subTest(host=host):
                status, response = self.request("/api/viewer/edit/install", {"package_token": "0" * 32},
                                                host, "http://" + host)
                self.assertEqual(status, 400, response)
                self.assertIn("error", response)


@unittest.skipUnless(AVAILABLE, "Real UnityPy/numpy and the paired-edit module are required")
class ViewerModFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PARENT_INSTALLERS and str(PARENT_ROOT) not in sys.path:
            sys.path.insert(0, str(PARENT_ROOT))
            cls.addClassCleanup(lambda: sys.path.remove(str(PARENT_ROOT)))
        fixture = Path(__file__).parent / "fixtures/viewer_persistence.unity"
        environment = UnityPy.load(fixture.read_bytes())
        for obj in environment.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0006_co0001_body"
                obj.save_typetree(tree)
        cls.raw = next(iter(environment.files.values())).save()
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            path = Path(temporary) / "costume.unity"
            path.write_bytes(cls.raw)
            cls.rig = model_viewer.prepare([str(path)], rigged=True,
                face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "costume.unity"
        self.source.write_bytes(self.raw)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.library = self.root / "library"
        self.output = self.root / "exports"
        self.cache = self.root / "cache"
        self.job = Job()
        receipts = patch.object(flow, "_PACKAGES", OrderedDict())
        receipts.start()
        self.addCleanup(receipts.stop)
        if PARENT_INSTALLERS:
            for name in ("run_costume", "_install_one"):
                blocked = patch("adminui.tools.installers." + name,
                    side_effect=AssertionError("Installer execution is outside these hand-off unit tests"))
                blocked.start()
                self.addCleanup(blocked.stop)
        self.token = secrets.token_hex(16)
        metadata = model_edits.register_session(self.token, [str(self.source)], self.rig)
        target = next(node for node in metadata["nodes"] if node["name"] == "LeftUpLeg")
        self.state = {"version": 1, "savedSettingsEnabled": True, "edits": [
            {"node": target["node"], "method": "mesh", "scale": [1.6, 1.2, 1.0]}]}

    def package(self, **options):
        return flow.create_package(self.token, self.state, output_root=self.output,
            repo_root=self.runtime, cache_root=self.cache, display_name="Neutral edited costume",
            character_id=6, job=self.job, **options)

    def runtime_gates(self):
        for path in (self.runtime / "serverdata.db", self.runtime / "assets/db/gl/masterdata.db"):
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as database:
                database.execute("CREATE TABLE qa_gate_only(value INTEGER)")

    def test_real_http_raw_and_mod_exports_edit_both_declared_platforms(self):
        from webtools.server import Handler, MANAGER
        import unity_costumemod_packer as packer
        source = self.library / "extracted/3d_model/dual.zip"
        source.parent.mkdir(parents=True)
        environment = UnityPy.load(self.raw)
        # A declared transplant may retain Rina donor texture names while the
        # installer explicitly assigns this costume to character 6.
        for obj in environment.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0209_co0001_body"
                obj.save_typetree(tree)
        android = environment.file.save()
        environment.file._m_target_platform = 9
        ios = environment.file.save()
        manifest = packer.generate_modinstall_txt("Dual costume", "android.unity", "thumb.png", 6)
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(manifest).body}
        values["costume_file_ios"] = "ios.unity"
        manifest = "\n".join(key + " = " + repr(value) for key, value in values.items()) + "\n"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("android.unity", android)
            archive.writestr("ios.unity", ios)
            archive.writestr("modinstall.txt", manifest)
            archive.writestr("thumb.png", packer.make_name_thumbnail_png("Dual costume", 32, 6))
            archive.writestr("notes.txt", b"Original notes stay byte-identical.")
        original = source.read_bytes()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = "127.0.0.1:" + str(server.server_port)

        def request(path, body=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                connection.request("POST" if body is not None else "GET", path,
                    body=json.dumps(body) if body is not None else None,
                    headers={"Host": host, "Origin": "http://" + host, "Content-Type": "application/json"})
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200, payload)
                return payload
            finally:
                connection.close()

        try:
            with patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)}):
                prepared = request("/api/viewer/prepare", {"paths": [str(source)], "rigged": True, "auto_face": False})
                nodes = {node["name"]: node for node in prepared["editing"]["nodes"]}
                state = {"version": 1, "savedSettingsEnabled": True, "edits": [
                    {"node": nodes["BreastSize"]["node"], "method": "auto",
                     "scale": [value * 1.1 for value in nodes["BreastSize"]["baseline"]["scale"]]},
                    {"node": nodes["LeftUpLeg"]["node"], "method": "mesh",
                     "scale": [nodes["LeftUpLeg"]["baseline"]["scale"][0], 1.2, 1.1]}]}
                for endpoint in ("export", "package"):
                    with self.subTest(endpoint=endpoint):
                        body = {"token": prepared["editing"]["token"], "state": state}
                        if endpoint == "package":
                            body.update(display_name="Both platforms edited", character_id=6,
                                        counterpart_path=None, selected_variant=None)
                        started = request("/api/viewer/edit/" + endpoint, body)
                        job = MANAGER.get(started["job_id"])
                        deadline = time.monotonic() + 15
                        while not job.is_done and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertEqual(job.status, "done", job._events[-3:])
                        result = request("/api/viewer/edit/result/" + job.id)
                        target = result["preview_paths"][0] if endpoint == "export" else result["mod_package"]["package_path"]
                        with zipfile.ZipFile(target) as archive:
                            values = {node.targets[0].id: ast.literal_eval(node.value)
                                for node in ast.parse(archive.read("modinstall.txt").decode()).body}
                            for field, platform, old in (("costume_file", 13, android), ("costume_file_ios", 9, ios)):
                                raw = archive.read(values[field])
                                self.assertNotEqual(raw, old)
                                info = model_edits._inspect(raw)
                                breast = next(key for key, value in info["names"].items() if value == "BreastSize")
                                expected = state["edits"][0]["scale"]
                                for actual, wanted in zip(info["effective"][breast]["scale"], expected):
                                    self.assertAlmostEqual(actual, wanted, places=6)
                                self.assertEqual(int(UnityPy.load(raw).file.target_platform), platform)
                                self.assertNotEqual(next(obj for obj in UnityPy.load(raw).objects if obj.type.name == "Mesh").get_raw_data(),
                                    next(obj for obj in UnityPy.load(old).objects if obj.type.name == "Mesh").get_raw_data())
                            note = "notes.txt" if endpoint == "export" else "notes.txt.data"
                            self.assertEqual(archive.read(note), b"Original notes stay byte-identical.")
                        if endpoint == "package":
                            self.assertEqual(result["mod_package"]["platform"], "android+ios")
                        self.assertEqual(source.read_bytes(), original)
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def install(self, token, job=None):
        return flow.install_package(token, repo_root=self.runtime, library_root=self.library,
                                    job=job or self.job)

    def test_actual_package_response_matches_frontend_and_internal_receipt_is_immutable(self):
        expected = copy.deepcopy(model_edits.validate_state(self.token, self.state))
        result = self.package()
        public = copy.deepcopy(result["mod_package"])
        self.assertRegex(public["token"], r"^[a-f0-9]{32}$")
        self.assertIs(public["installable"], True)
        self.assertEqual(public["character_id"], 6)
        self.assertEqual(public["variants"], [{"id": "primary", "label": "Costume"}])
        self.assertIn(public["package_path"], result["output_paths"])
        self.assertIn(result["recipe_path"], result["output_paths"])
        self.assertTrue(result["preview_paths"] and result["original_paths"])
        package = Path(public["package_path"])
        self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), public["sha256"])
        self.assertEqual(package.stat().st_size, public["bytes"])
        with zipfile.ZipFile(package) as archive:
            values = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            self.assertEqual(values["chara_id"], 6)
            self.assertEqual(archive.read(values["costume_file"]), Path(result["preview_paths"][0]).read_bytes())
            self.assertNotEqual(archive.read(values["costume_file"]), self.raw)
        json.dumps(result)  # No raw source bytes/context accidentally enter HTTP output.
        result["mod_package"]["package_path"] = str(self.root / "forged.zip")
        result["mod_package"]["sha256"] = "0" * 64
        self.state["edits"][0]["scale"][0] = 9
        receipt = flow.validate_install(public["token"])
        self.assertEqual(receipt["public"], public)
        self.assertEqual(receipt["source_token"], self.token)
        self.assertEqual(receipt["state"], expected)
        receipt["public"]["sha256"] = "f" * 64
        self.assertEqual(flow.validate_install(public["token"])["public"], public)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_source_context_is_detached_and_changed_original_cannot_be_packaged(self):
        context = model_edits.mod_source_context(self.token)
        context["containers"][0]["path"] = "/forged/model.unity"
        context["sources"][0]["sha256"] = "0" * 64
        context["nodes"][0]["baseline"]["scale"][0] = 9
        clean = model_edits.mod_source_context(self.token)
        self.assertEqual(clean["containers"][0]["path"], str(self.source))
        self.assertEqual(clean["sources"][0]["sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertNotEqual(clean["nodes"][0]["baseline"]["scale"][0], 9)
        self.source.write_bytes(self.raw + b"changed after preview")
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.package()
        self.assertEqual(len(flow._PACKAGES), 0)
        self.assertFalse(self.output.exists())

    def test_failed_counterpart_mapping_removes_only_the_newly_created_export(self):
        from webtools.core import viewer_mod_pair_edits
        prior = self.output / "body-edit-20261101-120000-12345678"
        prior.mkdir(parents=True)
        sentinel = prior / "user-saved-original.unity"
        sentinel.write_bytes(self.raw)
        with patch.object(viewer_mod_pair_edits, "apply_pair_edits", side_effect=ValueError("Missing matching hierarchy")):
            with self.assertRaisesRegex(ValueError, "Missing matching hierarchy"):
                self.package()
        self.assertEqual(list(self.output.iterdir()), [prior])
        self.assertEqual(sentinel.read_bytes(), self.raw)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(len(flow._PACKAGES), 0)

    def test_invalid_state_and_busy_slot_do_not_create_receipts(self):
        self.state["edits"][0]["scale"][0] = 0
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())
        self.assertEqual(len(flow._PACKAGES), 0)
        self.assertTrue(flow._PACKAGE_SLOT.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(ValueError, "Another Mod ZIP"):
                self.package()
        finally:
            flow._PACKAGE_SLOT.release()

    def test_catalog_sql_failure_cannot_be_ignored_for_package_creation(self):
        from webtools.core import viewer_mod_sources
        with patch.object(viewer_mod_sources, "game_context", side_effect=sqlite3.OperationalError("QA catalog unavailable")):
            with self.assertRaisesRegex(sqlite3.OperationalError, "catalog unavailable"):
                self.package()
        self.assertEqual(len(flow._PACKAGES), 0)
        self.assertEqual(list(self.output.rglob("*.zip")), [])

    def test_cancellation_before_start_and_before_package_publication_has_no_receipt(self):
        self.job.stopped = True
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.package()
        self.assertFalse(self.output.exists())
        self.job.stopped = False
        original_log = self.job.log
        def cancel_at_publication(message):
            original_log(message)
            if message.startswith("Prepared installer Mod ZIP:"):
                self.job.stopped = True
        self.job.log = cancel_at_publication
        with self.assertRaises((ValueError, InterruptedError)):
            self.package()
        self.assertEqual(len(flow._PACKAGES), 0)
        self.assertEqual(list(self.output.rglob("*.zip")), [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    @unittest.skipUnless(PARENT_INSTALLERS, "Parent installer adapters are needed for mocked hand-off unit checks")
    def test_unknown_expired_and_tampered_receipts_never_reach_installer_unit_runner(self):
        self.runtime_gates()
        result = self.package()
        public = result["mod_package"]
        with patch("adminui.tools.installers.run_costume_file") as runner:
            for token in ("../path.zip", "0" * 32):
                with self.subTest(token=token), self.assertRaises(ValueError):
                    self.install(token)
            created = flow._PACKAGES[public["token"]]["created"]
            with patch.object(flow.time, "monotonic", return_value=created + flow.PACKAGE_SECONDS + 1):
                with self.assertRaisesRegex(ValueError, "expired"):
                    flow.validate_install(public["token"])
            with Path(public["package_path"]).open("ab") as output:
                output.write(b"changed after saving")
            with self.assertRaisesRegex(ValueError, "changed after saving"):
                flow.validate_install(public["token"])
            with self.assertRaisesRegex(ValueError, "changed after saving"):
                self.install(public["token"])
            runner.assert_not_called()
        self.assertEqual(flow._PACKAGES[public["token"]]["status"], "failed")

    @unittest.skipUnless(PARENT_INSTALLERS, "Parent installer adapters are needed for mocked hand-off unit checks")
    def test_installer_unit_receives_exact_immutable_copy_once_and_replay_is_refused(self):
        self.runtime_gates()
        public = self.package()["mod_package"]
        controller = Mock()
        controller.is_running.return_value = True
        def runner(job, source_path, expected_sha256, *, restart_server=False):
            self.assertTrue(restart_server)
            self.assertEqual(expected_sha256, public["sha256"])
            copied = Path(source_path)
            self.assertEqual(copied.parent, self.library / "suit")
            self.assertTrue(copied.is_absolute())
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), public["sha256"])
            return "Mock runner hand-off only; no installer executed"
        with patch("adminui.serverctl._controller", controller), patch("adminui.tools.installers.run_costume_file", side_effect=runner) as called:
            installed = self.install(public["token"])
            self.assertIs(installed["installed"], True)
            self.assertTrue(installed["was_running"])
            self.assertEqual(installed["mod_package"], public)
            with self.assertRaisesRegex(ValueError, "already being added|installed"):
                self.install(public["token"])
            called.assert_called_once()
        with self.assertRaises(ValueError):
            flow.validate_install(public["token"])

    @unittest.skipUnless(PARENT_INSTALLERS, "Parent installer adapters are needed for mocked hand-off unit checks")
    def test_installer_unit_double_install_is_blocked_while_first_runner_is_active(self):
        self.runtime_gates()
        public = self.package()["mod_package"]
        entered, release = threading.Event(), threading.Event()
        errors, results = [], []
        def runner(job, source_path, expected_sha256, *, restart_server=False):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test runner was not released")
            return "Mock runner hand-off only"
        def first_install():
            try:
                results.append(self.install(public["token"], Job()))
            except BaseException as error:
                errors.append(error)
        with patch("adminui.serverctl._controller", None), patch("adminui.tools.installers.run_costume_file", side_effect=runner) as called:
            thread = threading.Thread(target=first_install)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ValueError, "already being added"):
                    self.install(public["token"])
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
            called.assert_called_once()

    @unittest.skipUnless(PARENT_INSTALLERS, "Parent installer adapters are needed for mocked hand-off unit checks")
    def test_installer_unit_cancel_and_runner_failure_consume_receipt_without_success(self):
        self.runtime_gates()
        for failure in ("cancel", "runner error"):
            self.job.stopped = False
            public = self.package()["mod_package"]
            def runner(job, source_path, expected_sha256, *, restart_server=False):
                if failure == "runner error":
                    raise RuntimeError("Mock runner error")
                job.stopped = True
                return "Mock cancellation"
            with self.subTest(failure=failure), patch("adminui.tools.installers.run_costume_file", side_effect=runner):
                with self.assertRaises((RuntimeError, ValueError)):
                    self.install(public["token"])
                self.assertEqual(flow._PACKAGES[public["token"]]["status"], "failed")
                with self.assertRaises(ValueError):
                    flow.validate_install(public["token"])

    @unittest.skipUnless(PARENT_INSTALLERS, "Parent installer adapters are needed for mocked hand-off unit checks")
    def test_missing_runtime_data_refuses_install_without_consuming_ready_receipt(self):
        public = self.package()["mod_package"]
        with patch("adminui.tools.installers.run_costume_file") as runner:
            with self.assertRaisesRegex(ValueError, "Prepare the Elichika server data"):
                self.install(public["token"])
            runner.assert_not_called()
        self.assertEqual(flow._PACKAGES[public["token"]]["status"], "ready")


@unittest.skipUnless(AVAILABLE, "Real encrypted game-source fixtures require UnityPy and the paired-edit module")
class ViewerModPreservedProvenanceTests(unittest.TestCase):
    def setUp(self):
        import test_viewer_mod_sources as fixture_module
        self.fixture = fixture_module.ViewerModSourceTests(
            methodName="test_official_pair_both_directions_and_regions_preserve_originals")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def preserve(self):
        from webtools.core import viewer_mod_sources
        fixture = self.fixture
        imported, record, _ = fixture.imported()
        # Deliberately misleading names establish no region/suit/variant identity.
        preserved = fixture.write("jp-suit999999-unmasked-preserved.unity", imported.read_bytes())
        flow.remember_export_sources(fixture.context(imported, imported.read_bytes()),
            {"original_paths": [str(preserved)]}, repo_root=fixture.root, cache_root=fixture.cache)
        with viewer_mod_sources._LOCK:
            viewer_mod_sources._REGISTRY.clear()
        context = fixture.context(preserved, preserved.read_bytes())
        return preserved, record, context

    def test_byte_identical_renamed_preserved_original_recovers_catalog_and_pair_after_restart(self):
        from webtools.core import viewer_mod_sources
        preserved, record, context = self.preserve()
        fixture = self.fixture
        receipts = flow.cached_receipts(context, fixture.cache)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["path"], str(preserved))
        self.assertEqual(receipts[0]["record"], record)
        bindings = viewer_mod_sources.game_context(context, fixture.root, receipts=receipts)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["record"], record)
        edited = fixture.write("current-edit.unity", fixture.primary)
        pair = fixture.resolve(context, edited, receipts=receipts)
        self.assertEqual(pair["owner"], 209)
        self.assertEqual(Path(pair["unmasked"]["path"]).read_bytes(), fixture.unmasked)
        self.assertFalse(pair["explicit_source"])
        self.assertEqual(preserved.read_bytes(), fixture.primary)

    def test_wrong_preserved_bytes_and_tampered_persisted_hash_never_recover_identity(self):
        from webtools.core import viewer_mod_sources
        fixture = self.fixture
        imported, _, _ = fixture.imported()
        wrong = fixture.write("wrong-original.unity", fixture.unmasked)
        with self.assertRaisesRegex(ValueError, "preserved original no longer matches"):
            flow.remember_export_sources(fixture.context(imported, imported.read_bytes()),
                {"original_paths": [str(wrong)]}, repo_root=fixture.root, cache_root=fixture.cache)
        self.assertEqual(list(fixture.cache.glob(".provenance-*.json")), [])
        preserved, _, context = self.preserve()
        target = fixture.cache / (".provenance-" + hashlib.sha256(str(preserved).encode()).hexdigest()[:32] + ".json")
        value = json.loads(target.read_text())
        value["sha256"] = "0" * 64
        target.write_text(json.dumps(value))
        receipts = flow.cached_receipts(context, fixture.cache)
        self.assertEqual(receipts, [])
        self.assertEqual(viewer_mod_sources.game_context(context, fixture.root, receipts=receipts), [])
        with self.assertRaisesRegex(ValueError, "explicitly choose"):
            fixture.resolve(context, fixture.write("edit.unity", fixture.primary), receipts=receipts)

    def test_preserved_original_change_between_hash_and_registration_cannot_borrow_identity(self):
        from webtools.core import viewer_mod_sources
        fixture = self.fixture
        imported, _, _ = fixture.imported()
        preserved = fixture.write("preserved-during-race.unity", imported.read_bytes())
        real_hash = flow._hash_file
        def changed_after_hash(path):
            result = real_hash(path)
            if Path(path) == preserved:
                preserved.write_bytes(fixture.unmasked)
            return result
        with patch.object(flow, "_hash_file", side_effect=changed_after_hash):
            try:
                flow.remember_export_sources(fixture.context(imported, imported.read_bytes()),
                    {"original_paths": [str(preserved)]}, repo_root=fixture.root, cache_root=fixture.cache)
            except ValueError:
                pass  # Immediate refusal and an expected-hash-only receipt are both safe.
        changed = fixture.context(preserved, preserved.read_bytes())
        receipts = flow.cached_receipts(changed, fixture.cache)
        try:
            bindings = viewer_mod_sources.game_context(changed, fixture.root, receipts=receipts)
        except ValueError:
            bindings = []
        self.assertEqual(bindings, [], "Changed preserved bytes must not acquire the previous costume's catalog identity")
        with viewer_mod_sources._LOCK:
            viewer_mod_sources._REGISTRY.clear()
        self.assertEqual(viewer_mod_sources.game_context(changed, fixture.root,
            receipts=flow.cached_receipts(changed, fixture.cache)), [])

    def test_stale_catalog_rejects_preserved_provenance_after_registry_restart(self):
        from webtools.core import viewer_mod_sources
        _, _, context = self.preserve()
        fixture = self.fixture
        receipts = flow.cached_receipts(context, fixture.cache)
        self.assertEqual(len(receipts), 1)
        with sqlite3.connect(fixture.root / "assets/db/gl/asset_a_en.db") as database:
            database.execute("UPDATE member_model SET key1=19 WHERE asset_path='board'")
        with self.assertRaisesRegex(ValueError, "catalog changed"):
            viewer_mod_sources.game_context(context, fixture.root, receipts=receipts)
        with self.assertRaisesRegex(ValueError, "catalog changed"):
            fixture.resolve(context, fixture.write("edit.unity", fixture.primary), receipts=receipts)

    def test_sql_unavailable_naming_hints_and_optional_provenance_do_not_block_plain_export(self):
        from webtools.core import viewer_mod_sources
        fixture = self.fixture
        imported, _, _ = fixture.imported()
        context = fixture.context(imported, imported.read_bytes())
        preserved = fixture.write("preserved.unity", imported.read_bytes())
        with patch.object(viewer_mod_sources, "game_context", side_effect=sqlite3.OperationalError("QA catalog unavailable")):
            hints = flow.metadata(context, repo_root=fixture.root, cache_root=fixture.cache)
            self.assertTrue(hints["nameBase"])
            self.assertTrue(hints["characters"])
            self.assertIsNone(flow.remember_export_sources(context, {"original_paths": [str(preserved)]},
                repo_root=fixture.root, cache_root=fixture.cache))
        self.assertEqual(list(fixture.cache.glob(".provenance-*.json")), [])
        self.assertEqual(preserved.read_bytes(), imported.read_bytes())


if __name__ == "__main__":
    unittest.main()
