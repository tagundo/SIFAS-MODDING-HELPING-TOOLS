"""Consumers follow the Body material after a graft retains old texture objects."""
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PIL import Image
import UnityPy

import costume_part_transplant as part
import unity_costumemod_packer as packer
from test_viewer_transplants import costume_fixture
from webtools.core import bodymatch, decode


def active_fixture(same_name=False, skin=False):
    env = UnityPy.load(costume_fixture())
    objects = {obj.path_id: obj for obj in env.objects}
    original = objects[14].read_typetree()
    original['m_Name'] = 'ch9999_co0001_body'
    original['image data'] = bytes((230, 170, 140, 255) if skin else (0, 0, 255, 255)) * 4
    objects[14].save_typetree(original)
    active = deepcopy(original)
    active['m_Name'] = original['m_Name'] if same_name else original['m_Name'] + '_graft_atlas'
    active.update(m_Width=2 if same_name else 4, m_Height=2)
    active['image data'] = bytes((230, 170, 140, 255) if skin else (255, 0, 0, 255)) * (active['m_Width'] * active['m_Height'])
    active['m_CompleteImageSize'] = len(active['image data'])
    active['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
    part._make_object(objects[14].assets_file, objects[14], 1001, active)
    material = objects[13].read_typetree()
    dict(material['m_SavedProperties']['m_TexEnvs'])['_MainTex']['m_Texture']['m_PathID'] = 1001
    objects[13].save_typetree(material)
    return env.file.save(packer='original')


class ActiveGraftTextureTests(unittest.TestCase):
    def test_thumbnail_uses_active_main_over_old_exact_name_and_same_name_copy(self):
        for same_name in (False, True):
            with self.subTest(same_name=same_name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'graft.unity'
                raw = active_fixture(same_name=same_name); path.write_bytes(raw)
                name, png = packer._extract_body_texture_core(str(path),
                    image_decoder=lambda texture: decode._android_image(texture, time.monotonic() + 10))
                with Image.open(io.BytesIO(png)) as image:
                    self.assertEqual(image.size, (2 if same_name else 4, 2))
                    self.assertEqual(image.convert('RGBA').getpixel((0, 0)), (255, 0, 0, 255))
                self.assertEqual(name, 'ch9999_co0001_body' + ('' if same_name else '_graft_atlas'))
                self.assertEqual(path.read_bytes(), raw)

    def test_skin_matching_changes_used_map_and_preserves_retained_old_map_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = (Path(directory) / name for name in ('graft.unity', 'matched.unity'))
            raw = active_fixture(skin=True); path.write_bytes(raw)
            before = {obj.path_id: obj for obj in UnityPy.load(raw).objects}
            self.assertEqual([obj.path_id for obj in packer._active_body_texture_objects(UnityPy.load(raw))], [1001])
            self.assertTrue(bodymatch.apply_skin_match(path, output, 'bright', 'medium_tone',
                skin_only=True, log=lambda message: None))
            after = {obj.path_id: obj for obj in UnityPy.load(str(output)).objects}
            self.assertEqual(after[14].get_raw_data(), before[14].get_raw_data())
            self.assertNotEqual(after[1001].read().get_image_data(), before[1001].read().get_image_data())
            np.testing.assert_array_equal(np.asarray(after[1001].read().image)[..., 3],
                                          np.asarray(before[1001].read().image)[..., 3])
            self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
