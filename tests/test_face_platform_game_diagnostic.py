"""A generic preview face must not acquire an invented native game platform."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import UnityPy

from viewer_scene_fixture import bundle_fixture
from webtools.core import viewer_mod_package as package


def facial_fixture(platform, role):
    environment = UnityPy.load(bundle_fixture(platform=platform))
    for obj in environment.objects:
        if obj.type.name == 'Texture2D':
            tree = obj.read_typetree(); tree['m_Name'] = 'ch0006_co0001_' + role; obj.save_typetree(tree)
    return environment.file.save()


class GameFacePlatformDiagnosticTests(unittest.TestCase):
    def test_unassigned_face_reports_actual_header_file_and_required_native_platform_without_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            body, original = root / 'body-ios.unity', root / 'original-face-ios.unity'
            body.write_bytes(facial_fixture(9, 'body')); original.write_bytes(facial_fixture(9, 'head'))
            sha = lambda data: hashlib.sha256(data).hexdigest()
            sources = [{'name':path.name, 'container':index, 'member':None, 'sha256':sha(path.read_bytes())}
                       for index, path in enumerate((body, original))]
            exported = {'recipe':{'sources':sources, 'originals':[{'name':path.name, 'sha256':sha(path.read_bytes())}
                        for path in (body, original)]}, 'original_paths':[str(body), str(original)]}
            for platform, label in [(-2, 'NoTarget'), (13, 'Android (13)'), (9, None)]:
                current = root / ('edited-face-' + str(platform) + '.unity')
                raw = facial_fixture(platform, 'head'); current.write_bytes(raw)
                record = {'path':str(current), 'sha256':sha(raw), 'original_path':str(original),
                    'original_sha256':sha(original.read_bytes()), 'source_sha256':sources[1]['sha256'],
                    'source_index':1, 'container':1, 'member':None, 'owner':6, 'platform':'ios',
                    'body_source_sha256':sources[0]['sha256']}
                with self.subTest(platform=platform):
                    if platform == 9:
                        self.assertEqual(package._verified_face_companions(exported, [record])[0]['platform'], 'ios')
                    else:
                        with self.assertRaises(package.ModPackageError) as failure:
                            package._verified_face_companions(exported, [record])
                        message = str(failure.exception)
                        self.assertIn(current.name, message)
                        self.assertIn(label, message)
                        self.assertIn('required: iOS (9)', message)
                        self.assertIn('matching native original face', message)
                        if platform == -2:
                            self.assertIn('unassigned', message)
                            self.assertNotIn('changed its original member', message)
                    self.assertEqual(current.read_bytes(), raw)
                    self.assertEqual({int(a.target_platform) for a in UnityPy.load(current.read_bytes()).assets}, {platform})


if __name__ == '__main__':
    unittest.main()
