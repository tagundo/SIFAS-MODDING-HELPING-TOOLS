"""Portable original-game equations and scene lifecycle regressions."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node is required for the browser physics runtime")
class OriginalGamePhysicsEngineTests(unittest.TestCase):
    def run_node(self, script, marker):
        completed = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name(script))],
            check=False, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(marker, completed.stdout)

    def test_native_collision_equations(self):
        self.run_node("viewer_game_physics_collision_test.js", "NATIVE")

    def test_native_job_collision_profiles(self):
        self.run_node("viewer_game_physics_job_collision_test.js", "GAME_JOB_COLLISION_NATIVE_PASS")

    def test_native_unity_quaternion_equations(self):
        self.run_node("viewer_game_physics_math_test.js", "NATIVE")

    def test_native_whole_jobs_and_safe_correct(self):
        self.run_node("viewer_game_physics_native_test.js", '"status":"PASS"')

    def test_native_initialization_cache_lifecycle(self):
        self.run_node("viewer_game_physics_initialization_test.js", "GAME_PHYSICS_NATIVE_INITIALIZATION_PASS")

    def test_scene_adapter_lifecycle(self):
        self.run_node("viewer_game_physics_adapter_test.js", "GAME_PHYSICS_ADAPTER_PASS")


if __name__ == "__main__":
    unittest.main()
