"""Texture-based rename copies must work with source-less Android modules."""
import hashlib
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    "webtools/__init__.py", "webtools/core/__init__.py", "webtools/tools/__init__.py",
    "webtools/core/repo.py", "webtools/core/sukusta.py", "webtools/core/tkstub.py",
    "webtools/tools/common.py", "webtools/tools/renamer.py",
    "sifas-assetbundle-renamer-by-texture.py",
)


class RenamerBytecodeTests(unittest.TestCase):
    def test_source_and_bytecode_only_rename_real_bundles_without_touching_inputs(self):
        import UnityPy
        from viewer_scene_fixture import bundle_fixture

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "app.imy"
            with zipfile.ZipFile(package, "w") as archive:
                for name in MODULES:
                    compiled = root / "module.pyc"
                    py_compile.compile(str(ROOT / name), cfile=str(compiled), doraise=True)
                    archive.write(compiled, name + "c")
                    compiled.unlink()
            source = root / "input"
            source.mkdir()
            environment = UnityPy.load(bundle_fixture())
            for obj in environment.objects:
                if obj.type.name == "Texture2D":
                    tree = obj.read_typetree()
                    tree["m_Name"] = "ch0002_co0123_body"
                    obj.save_typetree(tree)
            authored = environment.file.save()
            self.assertTrue(authored.startswith(b"UnityFS"))
            for obj in environment.objects:
                if obj.type.name == "Texture2D":
                    tree = obj.read_typetree()
                    tree["m_Name"] = "Unrecognized fixture texture"
                    obj.save_typetree(tree)
            fixture = environment.file.save()
            (source / "A original.unity").write_bytes(authored)
            (source / "B original.unity").write_bytes(authored)
            (source / "untouched.unity").write_bytes(fixture)
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in source.iterdir()}
            probe = r'''
import pathlib, sys, types
module_root, inputs, outputs, is_zip = sys.argv[1:]
sys.path.insert(0, module_root)
from webtools.tools import renamer
loaded = renamer._module()
assert renamer._module() is loaded
suffix = '.pyc' if is_zip == 'yes' else '.py'
assert loaded.__file__ == str(pathlib.Path(module_root) / ('sifas-assetbundle-renamer-by-texture' + suffix)), loaded.__file__
if is_zip == 'yes':
    assert renamer.__file__ == str(pathlib.Path(module_root) / 'webtools/tools/renamer.pyc')
    assert not pathlib.Path(loaded.__file__).with_suffix('.py').exists()
inputs, outputs = pathlib.Path(inputs), pathlib.Path(outputs)
for special in (False, True):
    logs, progress = [], []
    job = types.SimpleNamespace(log=logs.append, should_stop=lambda: False,
        progress=lambda done, total: progress.append((done, total)))
    target = outputs / str(special)
    result = renamer.run_renamer(job, {'in_dir': str(inputs), 'out_dir': str(target),
        'include_costume_id': True, 'remove_original_name': True,
        'remove_special_chars': special, 'filename_length_limit': '1'})
    second = '2eli01232.unity' if special else '2eli0123_2.unity'
    assert sorted(path.name for path in target.iterdir()) == sorted(['2eli0123.unity', second, 'untouched.unity'])
    assert (target / '2eli0123.unity').read_bytes() == (inputs / 'A original.unity').read_bytes()
    assert (target / second).read_bytes() == (inputs / 'B original.unity').read_bytes()
    assert (target / 'untouched.unity').read_bytes() == (inputs / 'untouched.unity').read_bytes()
    assert 'copied=3 renamed=2' in result, (result, logs)
    assert not any(line.startswith('FAIL') for line in logs), logs
    assert progress[-1] == (3, 3), progress
print('RENAMER_SOURCELESS_AND_SOURCE_OK')
'''
            for module_root, packaged in ((ROOT, "no"), (package, "yes")):
                with self.subTest(source_less=packaged):
                    completed = subprocess.run([sys.executable, "-I", "-B", "-c", probe,
                        str(module_root), str(source), str(root / ("output-" + packaged)), packaged],
                        cwd=root, capture_output=True, text=True, timeout=45)
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertIn("RENAMER_SOURCELESS_AND_SOURCE_OK", completed.stdout)
            self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in source.iterdir()})


if __name__ == "__main__":
    unittest.main()
