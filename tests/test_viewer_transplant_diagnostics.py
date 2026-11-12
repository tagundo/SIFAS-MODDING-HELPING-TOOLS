"""Transplant phases retain underlying errors and survive real reopened chains."""
import hashlib
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from test_viewer_transplants import costume_fixture
from webtools.core import model_edits, model_viewer, viewer_transplants
from webtools.jobs import Job


class ViewerTransplantDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = costume_fixture()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wearer.unity"
            source.write_bytes(cls.raw)
            cls.rig = model_viewer.prepare([str(source)], rigged=True,
                face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="transplant-diagnostics-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)})
        environment.start(); self.addCleanup(environment.stop)
        inputs = self.root / "extracted"
        inputs.mkdir()
        self.source = inputs / "wearer.unity"
        self.donor = inputs / "donor.unity"
        self.source.write_bytes(self.raw); self.donor.write_bytes(self.raw)
        self.token = secrets.token_hex(16)
        model_edits.register_session(self.token, [str(self.source)], self.rig)

    def request(self, operation="costume"):
        return viewer_transplants.validate_request({"token": self.token,
            "state": {"version": 1, "savedSettingsEnabled": True, "edits": []},
            "donor": str(self.donor), "variant": "primary", "operation": operation,
            "partRoot": "Head_Hair" if operation == "part" else "",
            "cutLow": .5, "cutHigh": .96, "region": "lower"})

    def run_request(self, job, request, **options):
        return viewer_transplants.run_transplant(job, request,
            output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache", **options)

    def stages(self, job):
        return [event for event in job._events if event.get("type") == "transplant-stage"]

    def test_missing_job_preserves_static_model_guard_before_pipeline_work(self):
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(self.source)], {"available": False, "bones": []})
        with self.assertRaises(model_edits.ModelEditError) as original:
            model_edits.require_body_editing(token)
        for job in (None, object()):
            with self.subTest(job=type(job).__name__), \
                    patch.object(viewer_transplants, "_donor_model", side_effect=AssertionError("Donor must not be read")), \
                    self.assertRaises(model_edits.ModelEditError) as caught:
                viewer_transplants.run_transplant(job, {"token": token},
                    output_root=self.root / "forbidden-output", cache_root=self.root / "forbidden-cache")
            self.assertEqual(str(caught.exception), str(original.exception))
        self.assertFalse((self.root / "forbidden-output").exists())
        self.assertFalse((self.root / "forbidden-cache").exists())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def assert_unpublished(self, job):
        self.assertEqual(job.output_paths(), [])
        self.assertEqual(list((self.root / "modded/viewer").glob(".viewer-transplant-*")), [])
        self.assertEqual(list((self.root / "modded/viewer").glob("transplant-*")), [])
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def assert_last_stage(self, job, stage, filename):
        event = self.stages(job)[-1]
        self.assertEqual(event, {"type": "transplant-stage", "operation": "costume", "stage": stage,
            "filename": filename, "donor": "donor.unity", "source_index": 0,
            "container_index": 0, "member": None})
        logs = [event["line"] for event in job._events if event.get("type") == "log"]
        self.assertTrue(any(f"[costume · {stage} · {filename}]" in line for line in logs))

    def test_exporter_error_keeps_its_object_message_and_preceding_phase(self):
        request = self.request(); job = Job(secrets.token_hex(6), "viewer_transplant")
        failure = OSError("The original source cannot be read.")
        def exporter(*args, **kwargs):
            raise failure
        with self.assertRaises(OSError) as caught:
            self.run_request(job, request, export_fn=exporter)
        self.assertIs(caught.exception, failure)
        self.assertEqual(str(caught.exception), "The original source cannot be read.")
        self.assertEqual([event["stage"] for event in self.stages(job)],
            ["validate_wearer", "prepare_output_folders", "save_current_edits"])
        self.assert_last_stage(job, "save_current_edits", "wearer.unity")
        self.assert_unpublished(job)

    def test_donor_selection_error_keeps_its_object_and_concrete_filename(self):
        request = self.request(); job = Job(secrets.token_hex(6), "viewer_transplant")
        failure = ValueError("Choose a donor containing one costume model.")
        with patch.object(viewer_transplants, "_donor_model", side_effect=failure):
            with self.assertRaises(ValueError) as caught:
                self.run_request(job, request)
        self.assertIs(caught.exception, failure)
        self.assertEqual([event["stage"] for event in self.stages(job)][-2:],
            ["expand_donor", "select_donor_model"])
        self.assert_last_stage(job, "select_donor_model", "donor.unity")
        self.assert_unpublished(job)

    def test_graft_error_keeps_its_object_after_real_preexport_and_platform_check(self):
        from webtools.tools import costume
        request = self.request(); job = Job(secrets.token_hex(6), "viewer_transplant")
        failure = RuntimeError("The graft could not resolve a donor bone.")
        with patch.object(costume, "run_costume_transplant", side_effect=failure):
            with self.assertRaises(RuntimeError) as caught:
                self.run_request(job, request)
        self.assertIs(caught.exception, failure)
        self.assertEqual([event["stage"] for event in self.stages(job)][-3:],
            ["extract_wearer", "check_platforms", "graft_model"])
        self.assert_last_stage(job, "graft_model", "wearer.unity")
        self.assert_unpublished(job)

    def test_phase_is_available_even_before_invalid_source_index_is_dereferenced(self):
        request = self.request(); request["sourceIndex"] = len(request["context"]["sources"])
        job = Job(secrets.token_hex(6), "viewer_transplant")
        with self.assertRaises(IndexError):
            self.run_request(job, request)
        events = self.stages(job)
        self.assertEqual([event["stage"] for event in events],
            ["validate_wearer", "prepare_output_folders"])
        self.assertEqual(events[0]["source_index"], 1)
        self.assertIsNone(events[0]["container_index"])
        self.assert_unpublished(job)

    def test_final_directory_rename_error_retains_publication_phase_and_original_error(self):
        request = self.request(); job = Job(secrets.token_hex(6), "viewer_transplant")
        failure = OSError("The completed transplant directory cannot be moved.")
        original_rename = Path.rename
        def rename(source, target):
            if source.name.startswith(".viewer-transplant-"):
                raise failure
            return original_rename(source, target)
        with patch.object(Path, "rename", new=rename):
            with self.assertRaises(OSError) as caught:
                self.run_request(job, request)
        self.assertIs(caught.exception, failure)
        self.assert_last_stage(job, "publish_output", "wearer.unity")
        self.assert_unpublished(job)

    def test_real_costume_head_part_lower_chain_reopens_and_keeps_all_inputs_immutable(self):
        current = self.source
        originals = {self.source: hashlib.sha256(self.raw).hexdigest(), self.donor: hashlib.sha256(self.raw).hexdigest()}
        expected = ["validate_wearer", "prepare_output_folders", "save_current_edits", "locate_edited_wearer",
            "prepare_transplant_files", "expand_donor", "select_donor_model", "extract_wearer", "check_platforms",
            "graft_model", "validate_output", "package_output", "preserve_face_companions", "publish_output", "publish_output"]
        for operation in ("costume", "part", "lower"):
            with self.subTest(operation=operation):
                rig = model_viewer.prepare([str(current)], rigged=True,
                    face_context={"enabled": False, "allow_download": False})["rig"]
                self.assertTrue(rig["available"])
                self.token = secrets.token_hex(16)
                model_edits.register_session(self.token, [str(current)], rig)
                request = self.request(operation); job = Job(secrets.token_hex(6), "viewer_transplant")
                self.run_request(job, request)
                self.assertEqual(len(job.output_paths()), 1)
                output = Path(job.output_paths()[0])
                self.assertNotEqual(output, current)
                self.assertEqual([event["stage"] for event in self.stages(job)], expected)
                self.assertTrue(all(event["operation"] == operation and event["source_index"] == 0
                    and event["container_index"] == 0 for event in self.stages(job)))
                self.assertEqual(self.stages(job)[-1]["filename"], output.name)
                for original, digest in originals.items():
                    self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
                originals[output] = hashlib.sha256(output.read_bytes()).hexdigest()
                current = output
        reopened = model_viewer.prepare([str(current)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        self.assertTrue(reopened["rig"]["available"])


if __name__ == "__main__":
    unittest.main()
