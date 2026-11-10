"""Portable native PCM transport and controller QA against actual viewer sources."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node is required for native PCM transport QA")
class NativePCMTransportTests(unittest.TestCase):
    def run_driver(self, name, marker):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name(name))],
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(marker, result.stdout)

    def test_player_lifecycle_budget_and_clock(self):
        self.run_driver("viewer_native_pcm_test.js", "NATIVE_PCM_PLAYER_PASS")

    def test_controller_transport_and_stale_binding(self):
        self.run_driver("viewer_native_pcm_controller_test.js", "NATIVE_PCM_CONTROLLER_PASS")


if __name__ == "__main__":
    unittest.main()
