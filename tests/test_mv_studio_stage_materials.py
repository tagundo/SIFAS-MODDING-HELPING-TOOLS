"""Cubemap import keeps each bounded original face and mip in sampler order."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from webtools.core import decode, mv_studio_stage_materials as stage


class StageCubemapTests(unittest.TestCase):
    @staticmethod
    def cube(format_id, block_sizes):
        face_bytes = sum(block_sizes)
        payload = b"".join(bytes([1 + 4 * face + mip]) * length
                           for face in range(6) for mip, length in enumerate(block_sizes))
        return SimpleNamespace(m_Width=8, m_Height=8, m_ImageCount=6, m_MipCount=4,
                               m_TextureFormat=format_id, m_TextureDimension=2, m_ColorSpace=1,
                               m_LightmapFormat=0, m_CompleteImageSize=face_bytes,
                               m_StreamData=SimpleNamespace(size=0), get_image_data=Mock(return_value=payload),
                               m_TextureSettings=SimpleNamespace(m_FilterMode=2, m_MipBias=0, m_Aniso=0,
                                                                 m_WrapU=1, m_WrapV=1, m_WrapW=1))

    def test_exact_face_and_mip_order_and_pvrtc_small_levels(self):
        for format_id, name, sizes, extents in ((34, "etc1", [32, 8, 8, 8], [8, 4, 2, 1]),
                                                  (32, "pvrtc4", [32, 32, 32, 32], [8, 8, 8, 8])):
            with self.subTest(format=name):
                recorded = []

                def decode_block(format_name, payload, width, height, deadline):
                    self.assertEqual(format_name, name)
                    level = len(recorded) % 4
                    self.assertEqual(len(payload), sizes[level])
                    self.assertEqual((width, height), (extents[level], extents[level]))
                    self.assertEqual(deadline, 123)
                    recorded.append(payload[0])
                    return Image.new("RGBA", (width, height), (payload[0], 0, 0, 255))

                with patch.object(decode, "_stage_block_image", side_effect=decode_block):
                    raw, width, pixels = stage._cube_pixels(self.cube(format_id, sizes), 1024, 123)
                self.assertEqual((width, pixels), (8, 6 * (64 + 16 + 4 + 1)))
                self.assertEqual(recorded, list(range(1, 25)))
                expected = bytearray()
                for index, value in enumerate(recorded):
                    side = 8 >> (index % 4)
                    expected.extend(bytes([value, 0, 0, 255]) * side ** 2)
                self.assertEqual(raw, expected)

    def test_rejects_invalid_budget_and_incomplete_native_data_before_decode(self):
        raw_cube = self.cube(34, [32, 8, 8, 8])
        with patch.object(decode, "_stage_block_image") as decoder:
            self.assertIsNone(stage._cube_pixels(raw_cube, 400, 123))
            raw_cube.get_image_data.assert_not_called()
            raw_cube.get_image_data.return_value = raw_cube.get_image_data.return_value[:-1]
            self.assertIsNone(stage._cube_pixels(raw_cube, 1024, 123))
            decoder.assert_not_called()
