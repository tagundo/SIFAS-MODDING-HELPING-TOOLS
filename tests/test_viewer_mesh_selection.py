"""Independent source-face topology and zoom-coordinate contracts."""
from pathlib import Path
import shutil
import subprocess
import unittest


class MeshSelectionJavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for browser mesh selection math')
    def test_connected_components_and_texture_view_coordinates(self):
        driver = Path(__file__).with_name('viewer_mesh_connected_zoom_test.js')
        result = subprocess.run(['node', str(driver)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS:', result.stdout)


if __name__ == '__main__':
    unittest.main()
