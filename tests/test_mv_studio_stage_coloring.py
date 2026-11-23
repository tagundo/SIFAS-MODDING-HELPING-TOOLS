"""LiveCoreStageColoring import: palette binding and light shaft textures."""
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_stage_coloring as coloring


_FILE = SimpleNamespace(externals=[])


def _object(path_id, kind, tree=None, name=""):
    return SimpleNamespace(path_id=path_id, assets_file=_FILE, type=SimpleNamespace(name=kind),
                           tree=tree or {}, name=name, read_typetree=lambda: tree or {})


class ColoringBindingTests(unittest.TestCase):
    def setUp(self):
        pointer = lambda path_id: {"m_FileID": 0, "m_PathID": path_id}
        shader = _object(30, "Shader", {"m_ParsedForm": {"m_Name": "AS/Coloring/Transparent"}})
        self.material = _object(20, "Material", {
            "m_Name": "mat_lit_B_gen_add_05", "m_Shader": pointer(30), "m_ShaderKeywords": "", "m_CustomRenderQueue": -1,
            "m_SavedProperties": {
                "m_Floats": [("_BlendSrc", 5), ("_BlendDst", 1), ("_CullMode", 0), ("_Speed", 1), ("_Shift", 0)],
                "m_Colors": [("_TintColor", {"r": 1, "g": 1, "b": 1, "a": 1})],
                "m_TexEnvs": [
                    ("_MainTex", {"m_Texture": pointer(40), "m_Scale": {"x": 1, "y": 2}, "m_Offset": {"x": 0, "y": .5}}),
                    ("_ColorIdTex", {"m_Texture": pointer(0), "m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}}),
                ],
            }})
        script = _object(10, "MonoScript", {"m_AssemblyName": "Assembly-CSharp.dll", "m_Namespace": "LLAS.Scene.Live.Components",
                                            "m_ClassName": "LiveCoreStageColoring"})
        root, game = _object(50, "GameObject", name="lit_01"), _object(51, "GameObject", name="litB_All")
        root_transform = _object(60, "Transform", {"m_Father": pointer(0)})
        transform = _object(61, "Transform", {"m_Father": pointer(60)})
        root_transform.tree["m_GameObject"] = pointer(50)
        self.textures = {path_id: _object(path_id, "Texture2D", name=f"tex_{path_id}") for path_id in (40, 41, 42, 43)}
        self.objects = {item.path_id: item for item in (
            shader, self.material, script, root, game, root_transform, transform, *self.textures.values())}
        self.scene = SimpleNamespace(
            tree=lambda item: item.tree, name=lambda item: item.name,
            transforms={viewer._key(root): root_transform, viewer._key(game): transform})
        self.component = _object(1, "MonoBehaviour")
        self.tree = {"m_Enabled": 1, "m_Script": pointer(10), "m_GameObject": pointer(51), "material": pointer(20),
                     "paletteTexture": pointer(41), "lightShaftTextures": [pointer(42), pointer(43)]}

    def resolve(self, _, pointer):
        return self.objects.get((pointer or {}).get("m_PathID"))

    def binding(self):
        with patch.object(viewer, "_ref", side_effect=self.resolve):
            return coloring.binding(self.scene, self.component, self.tree)

    def test_light_shaft_textures_no_longer_reject_the_component(self):
        identity, entry = self.binding()
        path, palette, main, fields, shafts = entry
        self.assertEqual(identity, viewer._key(self.material))
        self.assertEqual(path, ("lit_01", "litB_All"))
        self.assertEqual(fields["target"], "/EntryPoint/Live/Stages/MainStage/Effect/litB_All")
        self.assertIs(main, self.textures[40])
        self.assertIs(palette, self.textures[41])
        self.assertEqual([shaft.path_id for shaft in shafts], [42, 43])
        # SetTexture(_MainTex, ...) leaves the material's _MainTex_ST alone.
        self.assertEqual(fields["mainUV"], [1, 2, 0, .5])

    def test_an_unresolvable_light_shaft_texture_rejects_the_component(self):
        self.tree["lightShaftTextures"].append({"m_FileID": 0, "m_PathID": 99})
        self.assertIsNone(self.binding())
        self.tree["lightShaftTextures"][-1] = {"m_FileID": 0, "m_PathID": 0}
        self.assertIsNone(self.binding())

    def test_without_light_shaft_textures_the_list_is_empty(self):
        self.tree["lightShaftTextures"] = []
        self.assertEqual(self.binding()[1][4], ())
        del self.tree["lightShaftTextures"]
        self.assertEqual(self.binding()[1][4], ())

    def test_export_lists_light_shaft_texture_indices_in_order(self):
        _, entry = self.binding()
        palette = Mock()
        palette.read.return_value = SimpleNamespace(
            m_TextureSettings=SimpleNamespace(m_FilterMode=1, m_WrapU=0, m_WrapV=0), m_Width=256, m_Height=1,
            m_TextureFormat=4, m_MipCount=1, get_image_data=lambda: bytes(1024))
        palette.assets_file, palette.path_id = _FILE, 41
        entry = (entry[0], palette, *entry[2:])
        indices = {40: 3, 42: 5, 43: 6}
        materials = SimpleNamespace(texture=lambda texture: indices[texture.path_id])
        glb = SimpleNamespace(view=Mock(return_value=9))
        descriptor = coloring.export(glb, materials, entry, {})
        self.assertEqual((descriptor["main"], descriptor["shaftTextures"]), (3, [5, 6]))
        self.assertEqual(descriptor["palette"], {"bytes": 9, "size": [256, 1]})


def _bundle(variable):
    raw = os.environ.get(variable)
    return Path(raw) if raw and Path(raw).is_file() else None


class ActualStageColoringTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_12035 / _12025 to the original Android stage_effect bundles."""

    def components(self, path):
        deadline = time.monotonic() + 120
        env = viewer._environment([str(path)], deadline)
        scene = viewer._Scene(env, deadline)
        result, rejected = {}, []
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = scene.tree(obj)
            if "paletteTexture" not in tree or "lightShaftTextures" not in tree:
                continue
            found = coloring.binding(scene, obj, tree)
            name = scene.name(viewer._ref(obj, tree["m_GameObject"]))
            if found is None:
                rejected.append(name)
            else:
                result[name] = [scene.name(shaft) for shaft in found[1][4]]
        return result, rejected

    def test_12035_light_shafts(self):
        path = _bundle("SIFAS_TEST_STAGE_EFFECT_12035")
        if path is None:
            self.skipTest("Set SIFAS_TEST_STAGE_EFFECT_12035 to the original 12035 stage_effect bundle")
        result, rejected = self.components(path)
        self.assertEqual(rejected, [])
        self.assertEqual(result["litB_All"], ["tex_grs_lit_gen_12"])
        self.assertEqual(result["litC_All"], ["tex_grs_lit_gen_12"])
        self.assertEqual(result["LED_light_03"], ["tex_led_l03_so2035_01"])
        self.assertEqual(result["LED_panel_01"], [])

    def test_12025_light_shafts(self):
        path = _bundle("SIFAS_TEST_STAGE_EFFECT_12025")
        if path is None:
            self.skipTest("Set SIFAS_TEST_STAGE_EFFECT_12025 to the original 12025 stage_effect bundle")
        result, rejected = self.components(path)
        self.assertEqual(rejected, [])
        self.assertEqual(result["litA_All"], ["tex_grs_lit_gen_04", "tex_grs_lit_gen_12"])
        self.assertEqual(result["litB_All"], ["tex_grs_lit_gen_01", "tex_grs_lit_gen_12"])


if __name__ == "__main__":
    unittest.main()
