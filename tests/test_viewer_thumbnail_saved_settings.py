"""Portable pure-Three shape checks; Node is an isolated QA tool, not app runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


class ThumbnailSavedSettingsTests(unittest.TestCase):
    def test_verified_saved_endpoints_are_absolute_and_independent(self):
        node = os.environ.get("VIEWER_QA_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node is only required by the optional frontend QA driver")
        result = subprocess.run([node, str(Path(__file__).with_name("viewer_thumbnail_saved_settings_test.js"))],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"status":"PASS"', result.stdout)
