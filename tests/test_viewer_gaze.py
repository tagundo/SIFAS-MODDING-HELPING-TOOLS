"""Neutral serialized eye-pose bank survives real Unity to glTF conversion."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import shutil
import subprocess

try:
    import UnityPy
    import numpy  # noqa: F401
except ImportError:
    UnityPy = None


class GazeEngineTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is only needed for the optional JS regression runner")
    def test_original_gaze_targets_axes_pose_rebinding_and_property_ownership(self):
        subprocess.run([shutil.which("node"), str(Path(__file__).with_name("viewer_gaze_test.js"))],
                       check=True, capture_output=True, text=True, timeout=30)


@unittest.skipUnless(UnityPy, "Unity conversion dependencies are optional")
class SerializedGazeTests(unittest.TestCase):
    def test_neutral_original_format_bank_has_real_bound_iris_joints_without_extra_geometry(self):
        from generate_viewer_gaze_fixture import fixture_bytes
        from webtools.core import model_viewer
        raw = fixture_bytes()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "neutral-gaze.unity"
            source.write_bytes(raw)
            result = model_viewer.prepare([str(source)], rigged=True,
                                          face_context={"enabled": False, "allow_download": False})
            self.assertEqual(result["stats"], {"meshes": 1, "vertices": 6, "triangles": 4, "materials": 1, "textures": 1})
            gaze = result["rig"]["expressionCatalog"]["gaze"]
            self.assertTrue(gaze["available"])
            self.assertEqual([entry["index"] for entry in gaze["clips"]], list(range(6, 12)))
            self.assertEqual(len(gaze["nodes"]), 4)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertTrue(all(entry["sourceHash"] == digest for entry in gaze["clips"]))
            self.assertEqual(len(result["rig"]["clips"]), 7)
            self.assertTrue(all(entry["bindingComplete"] for entry in result["rig"]["clips"][1:]))
            data = model_viewer.get_model(result["id"])
            length = struct.unpack_from("<I", data, 12)[0]
            doc = json.loads(data[20:20 + length])
            joints = {index for skin in doc["skins"] for index in skin["joints"]}
            self.assertTrue(set(gaze["nodes"]) <= joints)
            self.assertEqual(source.read_bytes(), raw)
            self.assertTrue(result["rig"]["available"])
            self.assertEqual(len(result["rig"]["morphs"]), 0)


if __name__ == "__main__":
    unittest.main()
