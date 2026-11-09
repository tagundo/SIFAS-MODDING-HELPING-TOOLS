"""Real UnityFS costume grafts and source-bound workspace validation."""
import os
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy

from webtools.core import model_edits, model_viewer, viewer_transplants
from webtools.jobs import Job
from viewer_scene_fixture import bundle_fixture


def costume_fixture():
    """Give original neutral geometry the game's three-stream skin layout.

    One visible triangle at Y=.60–.70 is leg-weighted. Other independently
    weighted triangles exercise the real tool's anatomical region filtering.
    """
    env = UnityPy.load(bundle_fixture())
    mesh = next(obj for obj in env.objects if obj.type.name == "Mesh")
    tree = mesh.read_typetree(); vertex = tree["m_VertexData"]
    channels = vertex["m_Channels"]; count = vertex["m_VertexCount"]
    raw = vertex["m_DataSize"]; stride = len(raw) // count
    streams = [bytearray(), bytearray(), bytearray()]
    for index in range(count):
        row = raw[index * stride:(index + 1) * stride]
        position = struct.pack("<3f", *[(-.2, .6, 0), (.2, .7, 0), (0, .65, .1)][index]) if index < 3 else row[:12]
        streams[0] += position + row[12:24] + row[52:56]
        streams[1] += row[24:32]
        bones = (8, 0, 0, 0) if index < 3 else struct.unpack("<4B", row[48:52])
        streams[2] += row[32:48] + struct.pack("<4i", *bones)
    for stream in streams:
        stream += bytes(-len(stream) % 16)
    channels[3]["offset"] = 24
    channels[4].update(stream=1, offset=0)
    channels[12].update(stream=2, offset=0)
    channels[13].update(stream=2, offset=16, format=10)
    vertex["m_DataSize"] = b"".join(streams)
    mesh.save_typetree(tree)
    return env.file.save()


class ViewerTransplantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = costume_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "costume.unity"
            path.write_bytes(cls.raw)
            cls.rig = model_viewer.prepare([str(path)], rigged=True,
                face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.source = self.root / "extracted/wearer.unity"
        self.source.parent.mkdir(); self.source.write_bytes(self.raw)
        self.donor = self.source.with_name("donor.unity"); self.donor.write_bytes(self.raw)
        self.token = secrets.token_hex(16)
        self.metadata = model_edits.register_session(self.token, [str(self.source)], self.rig)
        self.node = next(row["node"] for row in self.metadata["nodes"] if row["name"] == "BreastSize")

    def request(self, **changes):
        value = {"token": self.token, "state": {"version": 1, "savedSettingsEnabled": True, "edits": []},
                 "donor": str(self.donor), "variant": "primary", "operation": "costume", "partRoot": "",
                 "cutLow": .5, "cutHigh": .96, "region": "lower"}
        value.update(changes); return value

    def run_graft(self, request):
        validated = viewer_transplants.validate_request(request)
        job = Job(secrets.token_hex(6), "viewer_transplant")
        viewer_transplants.run_transplant(job, validated,
            output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(len(job.output_paths()), 1)
        output = Path(job.output_paths()[0]); self.assertTrue(output.is_file())
        self.assertNotEqual(output, self.source)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)
        self.assertTrue(any(obj.type.name == "SkinnedMeshRenderer" for obj in UnityPy.load(str(output)).objects))
        self.last_job = job
        return output

    def test_real_full_transplant_preserves_current_breast_body_edit(self):
        state = {"version": 1, "savedSettingsEnabled": True,
                 "edits": [{"node": self.node, "method": "node", "scale": [1.25, 1.1, .9]}]}
        output = self.run_graft(self.request(state=state))
        inspected = model_edits._inspect(output.read_bytes())
        key = next(key for key, name in inspected["names"].items() if name == "BreastSize")
        for actual, expected in zip(inspected["effective"][key]["scale"], [1.25, 1.1, .9]):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_real_part_transplant_supports_an_unedited_wearer(self):
        output = self.run_graft(self.request(operation="part", partRoot="BreastSize"))
        self.assertGreater(output.stat().st_size, 0)

    def test_real_lower_body_swap_replaces_only_the_selected_vertical_band(self):
        output = self.run_graft(self.request(operation="lower", cutLow=.5, cutHigh=.96))
        logs = "\n".join(event.get("line", "") for event in self.last_job._events)
        self.assertIn("target drop: 1 tris   donor take: 1 tris", logs)
        self.assertGreater(output.stat().st_size, 0)

    def test_inspection_returns_real_donor_part_roots(self):
        result = viewer_transplants.inspect_donor(str(self.donor), cache_root=self.root / ".viewer-cache")
        self.assertIn("BreastSize", [part["value"] for part in result["parts"]])
        self.assertEqual(result["platform"], 13)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_invalid_cut_values_and_extra_paths_are_rejected_before_writes(self):
        for changes in ({"cutLow": 1., "cutHigh": .5}, {"cutLow": float("nan")},
                        {"cutHigh": True}, {"out_dir": "/tmp/attacker"}, {"operation": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                viewer_transplants.validate_request(self.request(**changes))
        self.assertFalse((self.root / "modded").exists())

    def test_donor_bytes_are_snapshotted_before_the_background_job(self):
        validated = viewer_transplants.validate_request(self.request())
        self.donor.write_bytes(b"changed after donor selection")
        self.assertEqual(validated["donorRaw"], self.raw)
        job = Job(secrets.token_hex(6), "viewer_transplant")
        viewer_transplants.run_transplant(job, validated,
            output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(len(job.output_paths()), 1)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_paired_target_archive_is_refused_instead_of_leaving_stale_models(self):
        archive = self.root / "extracted/paired.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("android.unity", self.raw)
            output.writestr("ios.unity", self.raw)
        context = model_edits.mod_source_context(self.token)
        context["containers"][0]["raw"] = archive.read_bytes()
        context["sources"][0]["member"] = "android.unity"
        with patch.object(model_edits, "mod_source_context", return_value=context), self.assertRaisesRegex(ValueError, "Paired platform"):
            viewer_transplants.validate_request(self.request())

    def test_mismatched_platform_donor_does_not_publish_a_result(self):
        self.donor.write_bytes(bundle_fixture(platform=9))
        request = viewer_transplants.validate_request(self.request())
        job = Job(secrets.token_hex(6), "viewer_transplant")
        with self.assertRaisesRegex(ValueError, "matching Unity platforms"):
            viewer_transplants.run_transplant(job, request,
                output_root=self.root / "modded/viewer", cache_root=self.root / ".viewer-cache")
        self.assertEqual(job.output_paths(), [])
        self.assertFalse(any((self.root / "modded/viewer").glob(".viewer-transplant-*")))
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
