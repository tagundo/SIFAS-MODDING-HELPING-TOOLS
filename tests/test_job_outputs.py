"""Saved-file events must identify the actual generated model for the viewer."""
from pathlib import Path
import tempfile
import unittest

from webtools.jobs import JobManager


class SavedModelEventsTests(unittest.TestCase):
    def test_success_reports_actual_counter_named_output_without_parsing_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "costume_baked.unity"
            original.write_bytes(b"previous output")
            saved = Path(directory) / "costume_baked2.unity"
            missing = Path(directory) / "not-saved.unity"
            empty = Path(directory) / "empty.unity"
            empty.touch()
            manager = JobManager()
            job = manager.create("mesh_baker")
            def bake(current):
                current.add_output(missing)
                current.add_output(empty)
                saved.write_bytes(b"new baked model")
                current.add_output(saved)
                current.add_output(saved)
                return "baked -> " + str(saved)
            manager.run_async(job, bake).join(3)
            self.assertTrue(job.is_done)
            event = job.event_at(job.event_count - 1, 0)
            self.assertEqual(event["status"], "done")
            self.assertEqual(event["output_paths"], [str(saved.resolve())])
            self.assertEqual(original.read_bytes(), b"previous output")

    def test_cancelled_batch_retains_completed_outputs_without_advertising_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "first.unity"
            manager = JobManager()
            job = manager.create("mesh_baker")
            def partial(current):
                saved.write_bytes(b"completed")
                current.add_output(saved)
                current.cancel_event.set()
                return "stopped"
            manager.run_async(job, partial).join(3)
            event = job.event_at(job.event_count - 1, 0)
            self.assertEqual(event["status"], "cancelled")
            self.assertEqual(event["output_paths"], [str(saved.resolve())])


if __name__ == "__main__":
    unittest.main()
