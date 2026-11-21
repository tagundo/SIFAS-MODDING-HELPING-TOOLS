import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import UnityPy

from viewer_scene_fixture import bundle_fixture
from webtools.core.tkstub import ensure_tk_stub

ensure_tk_stub()
import assetbundle_IosApk_batch_import_plus as converter


_BODY_TEXTURE = 14
_SWING = 16
_ADDED_TEXTURE = 22501


def _fixture(platform, texture_format, pixels, *, streamed=False, graft=False, dangling=False):
    env = UnityPy.load(bundle_fixture(platform))
    file = env.assets[0]
    objects = file.objects
    asset = objects[9999]
    tree = asset.read_typetree()
    tree.update(m_Name="Neutral costume", m_AssetBundleName="Neutral costume")
    asset.save_typetree(tree)
    script = objects[17]
    tree = script.read_typetree()
    tree["m_ClassName"] = "SwingBone"
    script.save_typetree(tree)
    swing = objects[_SWING]
    tree = swing.read_typetree()
    tree["m_Enabled"] = int(not graft)
    swing.save_typetree(tree)

    texture = objects[_BODY_TEXTURE]
    tree = texture.read_typetree()
    tree.update(m_TextureFormat=texture_format, m_MipCount=2, m_CompleteImageSize=len(pixels))
    if streamed:
        resource = next(name for name in env.file.files if name.endswith(".resS"))
        tree["image data"] = b""
        tree["m_StreamData"] = {"offset": 0, "size": len(pixels), "path": resource}
        if pixels != env.file.files[resource].bytes[:len(pixels)]:
            raise AssertionError("Synthetic stream does not contain the expected pixels")
    else:
        tree["image data"] = pixels
    texture.save_typetree(tree)

    if graft or dangling:
        material = objects[13]
        changed = material.read_typetree()
        changed["m_SavedProperties"]["m_TexEnvs"][0][1]["m_Texture"]["m_PathID"] = _ADDED_TEXTURE
        material.save_typetree(changed)
    if graft:
        added = dict(tree)
        added.update(m_Name="Added atlas", m_TextureFormat=4, m_CompleteImageSize=20)
        added["image data"] = bytes([17, 92, 233, 147]) * 5
        added["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        converter._make_object(file, texture, _ADDED_TEXTURE, added)
    return env.file.save(packer="original")


class CostumePlatformConverterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "converted.unity"
        self.source = self.root / "android.unity"
        self.target = self.root / "ios.unity"
        self.native = _fixture(9, 5, bytes([255, 20, 40, 50]) * 5)
        self.target.write_bytes(self.native)

    def convert(self, **kwargs):
        return converter.convert_costume_bundle(self.source, self.target, self.output, platform="ios", **kwargs)

    def test_matching_decoded_mips_preserve_native_encoding(self):
        source = _fixture(13, 3, bytes([20, 40, 50]) * 5)
        self.source.write_bytes(source)
        counts = self.convert(source_expected_sha256=hashlib.sha256(source).hexdigest())
        target = UnityPy.load(self.native).assets[0]
        output = UnityPy.load(self.output.read_bytes())
        self.assertEqual(int(output.assets[0].target_platform), 9)
        self.assertEqual(output.assets[0].objects[_BODY_TEXTURE].get_raw_data(), target.objects[_BODY_TEXTURE].get_raw_data())
        self.assertEqual(counts["textures_retained"], 1)
        self.assertEqual(self.target.read_bytes(), self.native)

    def test_streamed_source_and_added_texture_are_self_contained_with_both_physics_modes(self):
        rgb = b"original-neutra"
        source = _fixture(13, 3, rgb, streamed=True, graft=True)
        self.source.write_bytes(source)
        expected = b"".join(rgb[offset:offset + 3] + b"\xff" for offset in range(0, len(rgb), 3))
        for mode, enabled in (("target", 1), ("source", 0)):
            with self.subTest(mode=mode):
                self.output = self.root / (mode + ".unity")
                counts = self.convert(physics=mode)
                output = UnityPy.load(self.output.read_bytes())
                objects = output.assets[0].objects
                texture = objects[_BODY_TEXTURE].read()
                self.assertEqual((texture.m_TextureFormat, texture.m_MipCount), (4, 2))
                self.assertEqual(texture.get_image_data(), expected)
                self.assertEqual(texture.m_StreamData.size, 0)
                self.assertEqual(objects[_ADDED_TEXTURE].read().get_image_data(), bytes([17, 92, 233, 147]) * 5)
                self.assertEqual(objects[_SWING].read_typetree()["m_Enabled"], enabled)
                self.assertEqual(counts["added"], 1)
                self.assertEqual(counts["physics_preserved"], enabled)

    def test_source_original_proves_untouched_pixels_across_stock_encodings(self):
        source = _fixture(13, 3, bytes([75, 30, 14]) * 5)
        self.source.write_bytes(source)
        original = self.root / "original.unity"
        original.write_bytes(source)
        self.convert(source_original_bundle=original)
        target = UnityPy.load(self.native).assets[0]
        output = UnityPy.load(self.output.read_bytes()).assets[0]
        self.assertEqual(output.objects[_BODY_TEXTURE].get_raw_data(), target.objects[_BODY_TEXTURE].get_raw_data())

    def test_rejects_same_platform_stale_hash_and_new_dangling_references(self):
        self.source.write_bytes(self.native)
        with self.assertRaisesRegex(ValueError, "native platform"):
            self.convert()
        self.source.write_bytes(_fixture(13, 3, bytes([20, 40, 50]) * 5, dangling=True))
        with self.assertRaisesRegex(ValueError, "changed before conversion"):
            self.convert(source_expected_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "dangling object references"):
            self.convert()
        self.assertFalse(self.output.exists())

    def test_publishing_refuses_existing_output_and_cleans_up_failed_reservation(self):
        self.source.write_bytes(_fixture(13, 3, bytes([20, 40, 50]) * 5))
        self.output.write_bytes(b"previous result")
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(self.output.read_bytes(), b"previous result")
        self.output.unlink()
        with patch.object(converter._os, "replace", side_effect=OSError("test disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                self.convert()
        self.assertEqual(set(self.root.iterdir()), {self.source, self.target})


if __name__ == "__main__":
    unittest.main()
