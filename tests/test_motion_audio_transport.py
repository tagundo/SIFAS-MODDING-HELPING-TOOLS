"""Portable transport regression against the actual viewer audio module."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node is required for the viewer audio transport QA")
class MotionAudioTransportTests(unittest.TestCase):
    def test_continuous_clock_and_transport_discontinuities(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("viewer_motion_audio_transport_test.js"))],
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MOTION_AUDIO_TRANSPORT_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
