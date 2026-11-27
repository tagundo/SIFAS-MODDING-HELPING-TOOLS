"""The common keyword rule: a material keyword outside its shader's keyword space selects no program."""
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_shader_identity as identity
from webtools.core import mv_studio_soft_billboards as soft
from webtools.core import mv_studio_stage_overlay as overlay


def _shader(names, parsed=True):
    passes = [{"m_NameIndices": [(name, index) for index, name in enumerate(group)]} for group in names]
    form = {"m_Name": "AS/General/Transparent"}
    if parsed:
        form["m_SubShaders"] = [{"m_Passes": passes}]
    return SimpleNamespace(type=SimpleNamespace(name="Shader"), path_id=7, assets_file=SimpleNamespace(),
                           read_typetree=lambda: {"m_ParsedForm": form})


def _external(cab, path_id, keywords):
    material = SimpleNamespace(type=SimpleNamespace(name="Material"),
                               assets_file=SimpleNamespace(externals=[SimpleNamespace(path=f"archive:/CAB-{cab[4:]}")]))
    return material, {"m_Shader": {"m_FileID": 1, "m_PathID": path_id}, "m_ShaderKeywords": keywords}


class KeywordSpaceTests(unittest.TestCase):
    def test_shared_shader_keeps_only_its_declared_keywords(self):
        material, tree = _external("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267,
                                   "_ALPHAPREMULTIPLY_ON _SATURATE_ON _VERTEXCOLOR_ON _VERTEX_COLOR_OFF _VERTEX_COLOR_ON")
        with patch.object(viewer, "_ref", return_value=None):
            self.assertEqual(identity.keywords(material, tree), {"_SATURATE_ON", "_VERTEX_COLOR_ON"})

    def test_soft_billboard_declares_no_keyword(self):
        material, tree = _external("cab-b214ce933be761e55a829d7470161d63", -1880739195722111294, "_RIMLIGHT_ON")
        with patch.object(viewer, "_ref", return_value=None):
            self.assertEqual(identity.keyword_space(material, tree), frozenset())
            self.assertEqual(identity.keywords(material, tree), frozenset())

    def test_loaded_shader_uses_its_own_passes(self):
        material = SimpleNamespace(type=SimpleNamespace(name="Material"), assets_file=SimpleNamespace(externals=[]))
        tree = {"m_Shader": {"m_FileID": 0, "m_PathID": 7}, "m_ShaderKeywords": "INSTANCING_ON _AUTO_PLAY_ON _VERTEX_COLOR_ON"}
        # The embedded copy of 12007 also declares INSTANCING_ON.
        shader = _shader([["INSTANCING_ON", "_SATURATE_ON", "_VERTEX_COLOR_ON"], ["SOFTPARTICLES_ON"]])
        with patch.object(viewer, "_ref", return_value=shader):
            self.assertEqual(identity.keywords(material, tree), {"INSTANCING_ON", "_VERTEX_COLOR_ON"})
        # A loaded shader without parsed passes falls back to the verified space of its name.
        with patch.object(viewer, "_ref", return_value=_shader([], parsed=False)):
            self.assertEqual(identity.keywords(material, tree), {"_VERTEX_COLOR_ON"})

    def test_unknown_shader_keeps_every_saved_keyword(self):
        material, tree = _external("cab-00000000000000000000000000000000", 1, "_FOO _BAR")
        with patch.object(viewer, "_ref", return_value=None):
            self.assertIsNone(identity.keyword_space(material, tree))
            self.assertEqual(identity.keywords(material, tree), {"_FOO", "_BAR"})


class StaleKeywordReaderTests(unittest.TestCase):
    def material(self, cab, path_id, keywords, floats=(), queue=-1):
        material, tree = _external(cab, path_id, keywords)
        tree.update(m_CustomRenderQueue=queue, m_SavedProperties={
            "m_Floats": list(floats), "m_Colors": [("_TintColor", {"r": 1, "g": 1, "b": 1, "a": 1})],
            "m_TexEnvs": [("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 0},
                                        "m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})]})
        return material, SimpleNamespace(tree=lambda _: tree)

    def test_transparent_overlay_ignores_stale_keywords(self):
        material, scene = self.material("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267,
                                        "_AUTO_PLAY_ON _FLASH_ALL_ON _VERTEX_COLOR_OFF _ZWRITEPARAM_ON")
        with patch.object(viewer, "_ref", return_value=None):
            fields = overlay.read_material(scene, material)
        self.assertEqual((fields["vertexColor"], fields["queue"], fields["depthTest"]), (False, 3000, True))

    def test_fog_with_stale_rimlight_keyword_is_a_soft_billboard(self):
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        material, scene = self.material("cab-b214ce933be761e55a829d7470161d63", -1880739195722111294, "_RIMLIGHT_ON")
        scene.tree(material)["stringTagMap"] = {}
        scene.tree(material)["disabledShaderPasses"] = []
        with patch.object(viewer, "_ref", side_effect=lambda owner, pointer: None if "m_FileID" in pointer and
                          pointer.get("m_PathID") in (-1880739195722111294,) else texture):
            fields = soft.read_material(scene, material)
        self.assertEqual(fields["kind"], "fog")

    def test_fog_keeps_an_authored_transparent_queue(self):
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        for queue, expected in ((3010, 3010), (-1, 3000), (5000, 5000), (2500, None), (5001, None)):
            material, scene = self.material("cab-b214ce933be761e55a829d7470161d63", -1880739195722111294, "_RIMLIGHT_ON",
                                            queue=queue)
            scene.tree(material).update(stringTagMap={}, disabledShaderPasses=[])
            with patch.object(viewer, "_ref", side_effect=lambda owner, pointer: None if pointer.get("m_PathID") ==
                              -1880739195722111294 else texture):
                fields = soft.read_material(scene, material)
            self.assertEqual(fields and fields["queue"], expected, queue)


def _bundle(variable):
    raw = os.environ.get(variable)
    return Path(raw) if raw and Path(raw).exists() else None


class ShaderBundleKeywordSpaceTests(unittest.TestCase):
    """Set SIFAS_TEST_SHADER_DIR to a folder of the original Android shader bundles (shader-*.unity3d)."""

    def test_verified_spaces_match_the_shared_shader_bundles(self):
        folder = _bundle("SIFAS_TEST_SHADER_DIR")
        if folder is None or not folder.is_dir():
            self.skipTest("Set SIFAS_TEST_SHADER_DIR to the original shader bundles")
        import UnityPy

        wanted = {key: name for key, name in identity.KNOWN.items() if name in identity.KEYWORD_SPACES}
        found = {}
        for path in sorted(folder.glob("*.unity3d")):
            env = UnityPy.load(str(path))
            for obj in env.objects:
                key = (Path(obj.assets_file.name).name.casefold(), obj.path_id)
                if obj.type.name != "Shader" or key not in wanted:
                    continue
                form = obj.read_typetree()["m_ParsedForm"]
                self.assertEqual(form["m_Name"], wanted[key])
                found[wanted[key]] = identity._loaded_space(SimpleNamespace(read_typetree=lambda form=form: {
                    "m_ParsedForm": form}))
        self.assertEqual(set(found), set(identity.KEYWORD_SPACES))
        self.assertEqual(found, identity.KEYWORD_SPACES)


class RealStageEffectKeywordTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_12060 / _12030 to the original Android stage_effect bundles."""

    def materials(self, variable):
        path = _bundle(variable)
        if path is None:
            self.skipTest(f"Set {variable} to the original stage_effect bundle")
        env = viewer._environment([str(path)], time.monotonic() + 120)
        scene = viewer._Scene(env, time.monotonic() + 120)
        return scene, {scene.tree(obj).get("m_Name"): obj for obj in env.objects if obj.type.name == "Material"}

    def test_12060_fog_keeps_its_billboard_despite_rimlight(self):
        scene, materials = self.materials("SIFAS_TEST_STAGE_EFFECT_12060")
        material = materials["mat_par_gen_sft_01"]
        self.assertIn("_RIMLIGHT_ON", scene.tree(material)["m_ShaderKeywords"].split())
        self.assertEqual(soft.read_material(scene, material)["kind"], "fog")

    def test_12030_display_door_is_a_masked_alpha_pass(self):
        scene, materials = self.materials("SIFAS_TEST_STAGE_EFFECT_12030")
        material = materials["mat_dis_par_so2030_alb_01"]
        self.assertTrue(set(scene.tree(material)["m_ShaderKeywords"].split()) - {"_VERTEX_COLOR_ON"})
        fields = overlay.read_material(scene, material, world=True)
        self.assertEqual((fields["alphaBlend"], fields["stencilRef"], fields["queue"]), (True, 2, 2900))


if __name__ == "__main__":
    unittest.main()
