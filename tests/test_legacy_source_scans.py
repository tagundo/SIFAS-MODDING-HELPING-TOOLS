"""Exercise standalone discovery without importing Tk or SDK startup code."""
import ast
import builtins
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import viewer_cache

ROOT = Path(__file__).resolve().parents[1]
RFILES = ("sifas_breast_tuner.py", "skirt_length_changer.py", "Upleg_SwingCollider_changer.py",
          "hips_size_changer.py", "assetbundle_IosApk_batch_import_plus.py")
WFILES = ("sifas_mesh_baker.py", "skin_tone_changer.py", "lower_body_swap.py", "texture_importer.py")


def functions(filename, names, **extra):
    tree = ast.parse((ROOT / filename).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(nodes) != len(names):
        raise AssertionError("Missing scan functions in " + filename)
    env = {"Path": Path, "os": os, **extra}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / filename), "exec"), env)
    return env


class LegacySourceScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.library = self.root / "library"
        self.extracted = self.library / "extracted"
        self.paths = {}
        for key, relative in (("real", "body/source.unity"), ("user", "user/game-models/source.unity"),
                              ("oldmodel", "game-models/source.unity"), ("oldmotion", "game-motions/source.unity")):
            path = self.extracted / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"UnityFS\0fixture"); self.paths[key] = path
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        environment.start(); self.addCleanup(environment.stop)

    def test_active_recursive_scanners_delegate_and_keep_standalone_copy_fallback(self):
        for filename in RFILES + WFILES:
            helper = "_source_files" if filename in RFILES else "_source_walk"
            with self.subTest(filename=filename):
                env = functions(filename, [helper])
                if helper == "_source_files":
                    actual = list(env[helper](self.extracted))
                else:
                    actual = [Path(directory) / name for directory, _, files in env[helper](self.extracted) for name in files]
                self.assertEqual(set(actual), {self.paths["real"], self.paths["user"]})
                # A copied single script retains its old dependency-free walk.
                original_import = builtins.__import__
                def without_webtools(name, *args, **kwargs):
                    if name.startswith("webtools"):
                        raise ModuleNotFoundError("standalone copy", name="webtools")
                    return original_import(name, *args, **kwargs)
                with patch("builtins.__import__", side_effect=without_webtools):
                    list(env[helper](self.extracted))
                tree = ast.parse((ROOT / filename).read_text())
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef) and node.name == helper:
                        continue
                    for call in ast.walk(node):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                            self.assertNotEqual(call.func.attr, "rglob", filename + " still has an unfiltered scan")
                            self.assertFalse(call.func.attr == "walk" and isinstance(call.func.value, ast.Name) and call.func.value.id == "os",
                                             filename + " still has an unfiltered walk")

    def test_representative_real_file_filters_use_exact_legacy_boundary(self):
        unity = lambda path: Path(path).read_bytes().startswith(b"UnityFS")
        for filename in ("sifas_breast_tuner.py", "skirt_length_changer.py"):
            with self.subTest(filename=filename):
                env = functions(filename, ["_source_files", "find_asset_bundles"], is_unity_bundle=unity)
                self.assertEqual(set(env["find_asset_bundles"](self.extracted)), {self.paths["real"], self.paths["user"]})
                self.assertEqual(env["find_asset_bundles"](self.paths["oldmodel"].parent), [self.paths["oldmodel"]])
        env = functions("lower_body_swap.py", ["_source_walk", "iter_bundles"])
        self.assertEqual(set(env["iter_bundles"](self.extracted)), {str(self.paths["real"]), str(self.paths["user"])})
        env = functions("texture_importer.py", ["_source_walk", "iter_bundle_files"], SUPPORTED_BUNDLE_EXTS={".unity"})
        self.assertEqual(set(env["iter_bundle_files"](self.extracted, True)), {str(self.paths["real"]), str(self.paths["user"])})
        self.assertEqual(list(env["iter_bundle_files"](self.paths["oldmodel"], True)), [self.paths["oldmodel"]])

    def test_relative_inputs_remain_relative_for_output_mirroring(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            files = list(viewer_cache.iter_source_files("library/extracted"))
            self.assertTrue(files and all(not path.is_absolute() for path in files))
            self.assertEqual({path.relative_to("library/extracted") for path in files},
                             {Path("body/source.unity"), Path("user/game-models/source.unity")})
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
