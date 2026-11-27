"""LiveCoreStageFlashLight with an AS/General/Transparent material (the position-1 flash lights)."""
import json
import os
from pathlib import Path
import struct
import unittest

from webtools.core import model_viewer as viewer


class RealTransparentFlashTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_12035_1 to the original Android stage_effect bundle of 12035/1."""

    def test_12035_position_1_flash_light_keeps_its_transparent_pass(self):
        raw = os.environ.get("SIFAS_TEST_STAGE_EFFECT_12035_1")
        if not raw or not Path(raw).is_file():
            self.skipTest("Set SIFAS_TEST_STAGE_EFFECT_12035_1 to the original stage_effect bundle")
        prepared = viewer.prepare([raw], face_context={"enabled": False, "allow_download": False, "_mv_stage": True})
        payload = viewer.get_model(prepared["id"])
        doc = json.loads(payload[20:20 + struct.unpack_from("<I", payload, 12)[0]])
        flashes = [(mesh["name"], primitive) for mesh in doc["meshes"] for primitive in mesh["primitives"]
                   if "mvStageFlash" in primitive.get("extras", {})]
        self.assertEqual([name for name, _ in flashes], ["flash_light_01"])
        fields = flashes[0][1]["extras"]["mvStageFlash"]
        self.assertEqual((fields["kind"], fields["enabled"], fields["queue"]), ("transparent", True, 3000))
        self.assertTrue(fields["binding"].endswith("/flash_light_01"))
        transparent = fields["transparent"]
        # mat_fla_01_gen_add_no_01: Blend SrcAlpha One, ZTest LEqual, Cull Off; its saved
        # _AUTO_PLAY_ON and _FLASH_ALL_ON are not AS/General/Transparent keywords.
        self.assertEqual((transparent["blend"], transparent["zTest"], transparent["cull"], transparent["vertexColor"]),
                         ([5, 1], 4, 0, False))
        self.assertIsInstance(transparent["texture"], int)
        self.assertNotIn("saturate", transparent)


if __name__ == "__main__":
    unittest.main()
