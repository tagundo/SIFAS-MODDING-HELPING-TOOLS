"""Editing resolves selected Unity data without scanning unrelated game files."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import UnityPy
from UnityPy.files.SerializedFile import FileIdentifier
from fsspec.implementations.local import LocalFileSystem

from webtools.core import model_edits as edits, model_outlines as outlines, model_viewer
from test_model_outlines import colored_fixture
from test_model_viewer import unity_bundle


def external(path):
    value = FileIdentifier.__new__(FileIdentifier)
    value.path, value.temp_empty, value.guid, value.type = path, "", bytes(16), 0
    return value


def external_shader_fixture(cab="CAB-unselected-shader", identity=18):
    env = UnityPy.load(colored_fixture())
    asset = env.file
    material = next(obj for obj in env.objects if obj.type.name == "Material")
    tree = material.read_typetree()
    asset.externals.append(external(cab))
    tree["m_Shader"] = {"m_FileID": len(asset.externals), "m_PathID": identity}
    material.save_typetree(tree)
    del asset.objects[18]
    return asset.save()


class SelectedDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_missing_shader_never_searches_working_directory(self):
        raw = external_shader_fixture()
        # A large user library must have no bearing on an unresolved shader.
        for index in range(256):
            (self.root / f"unrelated-{index}.bin").write_bytes(b"unrelated")
        (self.root / "CAB-unselected-shader").write_bytes(colored_fixture())
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        with patch.object(LocalFileSystem, "walk", side_effect=AssertionError("Directory search is forbidden")) as walk, \
                patch.object(LocalFileSystem, "open", side_effect=AssertionError("Unselected files cannot be loaded")) as opened:
            info = edits._inspect(raw)
            self.assertFalse(outlines.catalogue(info, 0)["available"])
            walk.assert_not_called()
            opened.assert_not_called()
            self.assertEqual(info["env"].local_files, [])
        self.assertEqual((self.root / "CAB-unselected-shader").read_bytes(), colored_fixture())

    def test_original_member_fingerprint_survives_missing_external_shader(self):
        raw = external_shader_fixture("CAB-9382ea964987eceddd567506a3b21312", 8291131735116688333)
        info = edits._inspect(raw)
        material = next(obj for obj in info["objects"].values() if obj.type.name == "Material")
        # Only AssetBundle dependency metadata is a declared unit boundary;
        # material properties and its external PPtr are real serialized bytes.
        bundle = SimpleNamespace(path_id=901, assets_file=material.assets_file,
            type=SimpleNamespace(name="AssetBundle"),
            read_typetree=lambda: {"m_Dependencies": ["asmember.shader.unity3d"]})
        material.assets_file.objects[901] = bundle
        with patch.object(LocalFileSystem, "walk", side_effect=AssertionError("No external search")) as walk:
            self.assertTrue(outlines._member(info, material))
            tree = material.read_typetree()
            tree["m_SavedProperties"]["m_Colors"] = [row for row in tree["m_SavedProperties"]["m_Colors"] if row[0] != "_RimlightColor"]
            scene = SimpleNamespace(env=info["env"], tree=lambda obj: obj.read_typetree())
            self.assertFalse(model_viewer._as_member_material(scene, material, tree))
            walk.assert_not_called()

    def test_embedded_cross_cab_shader_and_resource_remain_resolvable(self):
        body = UnityPy.load(colored_fixture())
        shader_asset = UnityPy.load(colored_fixture()).file
        shader = shader_asset.objects[18]
        shader_asset.objects = {18: shader}
        material = body.file.objects[13]
        tree = material.read_typetree()
        body.file.externals.append(external("archive:/selected/CAB-selected-shader"))
        tree["m_Shader"] = {"m_FileID": len(body.file.externals), "m_PathID": 18}
        material.save_typetree(tree)
        del body.file.objects[18]
        raw = unity_bundle([("CAB-selected-body", body.file.save()),
                            ("CAB-selected-shader", shader_asset.save()),
                            ("CAB-selected.resS", b"original-selected-resource")])
        with patch.object(LocalFileSystem, "walk", side_effect=AssertionError("No directory search")) as walk:
            info = edits._inspect(raw)
            member = next(obj for obj in info["objects"].values() if obj.type.name == "Material")
            resolved = model_viewer._ref(member, member.read_typetree()["m_Shader"])
            self.assertEqual(resolved.type.name, "Shader")
            self.assertEqual(resolved.read_typetree()["m_Name"], "AS/Member")
            self.assertTrue(outlines.catalogue(info, 0)["available"])
            self.assertIs(info["env"].find_file(r"folder\CAB-selected-shader"), resolved.assets_file)
            resource = info["env"].find_file(r"folder\CAB-selected.resS")
            resource.Position = 0
            self.assertEqual(resource.read_bytes(len(b"original-selected-resource")), b"original-selected-resource")
            walk.assert_not_called()

    def test_edit_environment_rejects_unselected_dependency_files(self):
        outside = self.root / "unselected.unity"
        raw = colored_fixture()
        outside.write_bytes(raw)
        info = edits._inspect(raw)
        with self.assertRaises(FileNotFoundError):
            info["env"].load_file(str(outside), is_dependency=True)
        with self.assertRaises(FileNotFoundError):
            info["env"].load_file(outside, is_dependency=True)
        self.assertEqual(outside.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
