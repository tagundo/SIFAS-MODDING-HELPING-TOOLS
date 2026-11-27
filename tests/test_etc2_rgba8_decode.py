"""ETC2 RGBA8 stage textures decode exactly in numpy (no native codec in the app process)."""
import builtins
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from webtools.core import decode, model_materials

# (mode, block, unflipped RGBA of its 16 pixels in rows), from the pinned upstream
# decode_etc2a8 (K0lb3/texture2ddecoder 1.0.6, resources/texture65_decoder/upstream).
_VECTORS = (
    ("differential", "aa3912da04acce2dbf4cc3066759d1a3",
     "b542bea4bb48c4b6a418cdb6c63aefc5c552ceadc552cea4b024d98cb024d9a4bf4cc8b6bb48c4a4b024d99ba418cdb6bb48c4b6c552ceadba2ee3adc63aefb6"),
    ("individual", "ea318f5de5e69e77739c6f145f1fd95e",
     "759764f06f915eff007cafff007cafff6f915ec3799b68ff1bb4e7d54be4ffd56f915eff7fa16ef01bb4e7fc007cafff6f915efc799b68fc007cafd583ffffff"),
    ("H", "6431fdf4847d26cc871c5a874b53519b",
     "922c0088922c0046922c003d00d65f3d922c008829ffb146e47e298829ffb13d29ffb13de47e295b29ffb146922c004f00d65f8800d65f6ae47e294629ffb16a"),
    # Equal H base colours (44 99 bb twice): the tie sets the distance index's low bit.
    ("H-tie", "7a935d452040de7024f9a4de2436f44b",
     "24799b4464b9db4464b9db4424799be624799be664b9db8364b9db6824799b5664b9db4424799b8324799b5624799ba724799b8364b9db6864b9db9524799b68"),
    ("T", "a534b8fa66d2174805e9231a9cc9fcab",
     "0b1c00b411ee99b411ee99ba0b1c0081394a28ba394a289311ee99ab394a28b411ee9993223311ab0b1c00ab394a28930b1c00c60b1c00ba0b1c00930b1c009c"),
    ("planar", "17334a0f6ed3c37c9c1e0d163f8bc717",
     "381e28053426503b302e78262c369f0b48253505442d5d204035851a3c3dad20592b431a55336a20513b923b4d43ba3b69325011653a782661429f1a5d4ac71a"),
    # A zero EAC multiplier keeps the base codeword (0x9b) for every pixel.
    ("alpha-base", "9b07305c8fa74a03a96ac0d9d06fb49a",
     "8945ab9bffd0ff9bcb87ed9b4000629b4000629b8945ab9bcb87ed9bffd0ff9b7889009b7889009bffff6a9b7889009b2f40009bffff6a9bbacb219b2f40009b"),
)


class _Format:
    def __init__(self, value):
        self.name = {47: "ETC2_RGBA8", 34: "ETC_RGB4"}[value]


def _texture(data, width, height, mips=1):
    return SimpleNamespace(m_Name="tex", m_Width=width, m_Height=height, m_TextureFormat=47, m_MipCount=mips,
                           m_ImageCount=1, m_TextureDimension=2, m_StreamData=None, image_data=data,
                           m_TextureSettings=None, m_ColorSpace=1, object_reader=None, get_image_data=lambda: data)


class Etc2Rgba8Tests(unittest.TestCase):
    def test_every_block_mode_matches_the_upstream_decoder(self):
        for mode, block, pixels in _VECTORS:
            with self.subTest(mode=mode):
                image = decode._etc2_rgba8_image(bytes.fromhex(block), 4, 4)
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.tobytes().hex(), pixels)

    def test_blocks_are_laid_out_in_rows_and_cropped_to_the_logical_extent(self):
        blocks = b"".join(bytes.fromhex(block) for _, block, _ in _VECTORS[:4])
        pixels = [np.frombuffer(bytes.fromhex(expected), np.uint8).reshape(4, 4, 4) for _, _, expected in _VECTORS[:4]]
        expected = np.concatenate([np.concatenate(pixels[:2], 1), np.concatenate(pixels[2:], 1)], 0)
        self.assertTrue((np.asarray(decode._etc2_rgba8_image(blocks, 8, 8)) == expected).all())
        self.assertTrue((np.asarray(decode._etc2_rgba8_image(blocks, 7, 5)) == expected[:5, :7]).all())
        with self.assertRaisesRegex(ValueError, "Truncated"):
            decode._etc2_rgba8_image(blocks[:-1], 8, 8)

    def test_random_blocks_match_the_upstream_decoder(self):
        try:
            import texture2ddecoder
        except ImportError:
            self.skipTest("texture2ddecoder is not installed")
        rng = np.random.default_rng(1)
        for width, height in ((256, 256), (13, 7), (1, 1)):
            data = rng.integers(0, 256, ((width + 3) // 4) * ((height + 3) // 4) * 16, dtype=np.uint8).tobytes()
            reference = np.frombuffer(texture2ddecoder.decode_etc2a8(data, width, height), np.uint8)
            reference = reference.reshape(height, width, 4)[..., [2, 1, 0, 3]]
            self.assertTrue((np.asarray(decode._etc2_rgba8_image(data, width, height)) == reference).all(), (width, height))

    def test_stage_previews_decode_in_process_with_one_flip(self):
        _, block, pixels = _VECTORS[2]
        texture = _texture(bytes.fromhex(block) * 2, 4, 8)
        original_import = builtins.__import__

        def no_codec(name, *args, **kwargs):
            if name == "texture2ddecoder":
                raise AssertionError("In-process codec import attempted")
            return original_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {"UnityPy.enums": SimpleNamespace(TextureFormat=_Format)}), \
                patch.object(builtins, "__import__", no_codec):
            image = decode._android_image(texture, time.monotonic() + 30, stage=True)
            with self.assertRaisesRegex(ValueError, "ETC2_RGBA8 is unavailable"):
                decode._android_image(texture, time.monotonic() + 30)
        rows = np.frombuffer(bytes.fromhex(pixels), np.uint8).reshape(4, 4, 4)
        self.assertTrue((np.asarray(image) == np.concatenate([rows, rows], 0)[::-1]).all())

    def test_stage_mips_slice_sixteen_byte_blocks(self):
        # 8x4 -> 4x2 -> 2x1 -> 1x1: 2 + 1 + 1 + 1 blocks.
        data = bytes(range(80))
        with patch.dict("sys.modules", {"UnityPy.enums": SimpleNamespace(TextureFormat=_Format)}):
            levels = model_materials._original_mips(SimpleNamespace(assets_file=None, path_id=1),
                                                    _texture(data, 8, 4, 4), stage=True)
            self.assertEqual([(level.read().m_Width, level.read().m_Height, level.read().get_image_data())
                              for level in levels], [(4, 2, data[32:48]), (2, 1, data[48:64]), (1, 1, data[64:80])])
            with self.assertRaisesRegex(ValueError, "do(es)? not match"):
                model_materials._original_mips(SimpleNamespace(assets_file=None, path_id=1),
                                               _texture(data + bytes(16), 8, 4, 4), stage=True)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                model_materials._original_mips(SimpleNamespace(assets_file=None, path_id=1), _texture(data, 8, 4, 4))


if __name__ == "__main__":
    unittest.main()
