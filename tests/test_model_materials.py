import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_materials as materials


class MemberMetadataTests(unittest.TestCase):
    def tree(self, keywords="", **floats):
        return {"m_ShaderKeywords": keywords, "m_SavedProperties": {
            "m_Floats": list(floats.items()), "m_Colors": [], "m_TexEnvs": []}}

    def test_unused_standard_color_is_not_a_shader_input(self):
        tree = self.tree(_RimglightIntensity=0)
        tree["m_SavedProperties"]["m_Colors"] = [("_Color", dict(r=.1, g=.2, b=.3, a=.4))]
        output = {"extras": {"other": 1}}
        metadata = materials.attach_member_metadata(None, object(), tree, output, lambda _: self.fail("No image expected"))
        self.assertEqual(metadata["pipeline"], "gamma")
        self.assertNotIn("_Color", metadata["colors"])
        self.assertEqual(metadata["colors"]["_TintColor"], [1, 1, 1, 1])
        self.assertEqual(metadata["textures"]["_MainTex"], {"default": [1, 1, 1, 1]})
        self.assertFalse(metadata["features"]["rimlight"])
        self.assertEqual(output["extras"]["other"], 1)

    def test_keywords_select_variants_not_stale_toggle_floats(self):
        first = materials.attach_member_metadata(None, object(), self.tree(_MATCAP=1), {}, lambda _: 0)
        second = materials.attach_member_metadata(None, object(), self.tree("_MATCAP_ON _EMISSIVE_ON _CHEEK_ON"), {}, lambda _: 0)
        self.assertFalse(first["features"]["matcap"])
        self.assertTrue(all(second["features"][name] for name in ("matcap", "emissive", "cheek")))
        self.assertEqual(second["textures"]["_EmissiveTex"]["default"], [0, 0, 0, 1])

    def test_missing_nonzero_dependency_disables_only_that_feature(self):
        tree = self.tree("_MATCAP_ON", _RimglightIntensity=1)
        tree["m_SavedProperties"]["m_TexEnvs"] = [("_RimlightTex", {"m_Texture": {"m_PathID": 12}})]
        with patch("webtools.core.model_viewer._ref", return_value=None):
            value = materials.attach_member_metadata(None, object(), tree, {}, lambda _: self.fail("No source"))
        self.assertFalse(value["features"]["rimlight"])
        self.assertTrue(value["features"]["matcap"])
        self.assertIn("Shader texture unavailable: _RimlightTex", value["limitations"])

    def test_nonfinite_authored_values_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf, 1e10):
            with self.subTest(value=value), self.assertRaises(ValueError):
                materials.attach_member_metadata(None, object(), self.tree(_RimglightPower=value), {}, lambda _: 0)


class OriginalImageLevelTests(unittest.TestCase):
    def texture(self, *, width=4, height=4, count=3, depth=None, pixels=None):
        settings = SimpleNamespace(m_FilterMode=1)
        data = pixels if pixels is not None else bytes(range(84))
        value = SimpleNamespace(m_Name="Neutral image", m_Width=width, m_Height=height,
            m_MipCount=count, m_ImageCount=1, m_TextureDimension=2, m_TextureFormat=4,
            m_Format=4, m_TextureSettings=settings, m_ColorSpace=1,
            image_data=data, m_StreamData=SimpleNamespace(size=0), get_image_data=lambda: data)
        if depth is not None:
            value.m_Depth = depth
        obj = SimpleNamespace(assets_file=object(), path_id=7, type=SimpleNamespace(name="Texture2D"), read=lambda: value)
        return obj, value

    def test_authored_raw_mips_are_exact_slices_and_source_is_unchanged(self):
        obj, texture = self.texture()
        before = texture.image_data
        levels = materials._original_mips(obj, texture)
        self.assertEqual([(p.read().m_Width, p.read().m_Height) for p in levels], [(2, 2), (1, 1)])
        self.assertEqual(levels[0].read().get_image_data(), before[64:80])
        self.assertEqual(levels[1].read().get_image_data(), before[80:84])
        self.assertEqual(texture.image_data, before)
        self.assertNotEqual(levels[0].path_id, levels[1].path_id)

    def test_partial_and_truncated_mip_data_do_not_generate_pixels(self):
        for arguments in ({"count": 2}, {"pixels": bytes(83)}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                obj, texture = self.texture(**arguments)
                materials._original_mips(obj, texture)

    def test_array_layer_retains_original_mip_chain(self):
        obj, texture = self.texture(depth=2, pixels=bytes(range(168)))
        obj.type.name = "Texture2DArray"
        proxy = materials._array_layer(obj, 1)
        self.assertEqual(proxy.read().get_image_data(), texture.image_data[84:168])
        levels = materials._original_mips(proxy, proxy.read())
        self.assertEqual(levels[0].read().get_image_data(), texture.image_data[148:164])
        self.assertEqual(levels[1].read().get_image_data(), texture.image_data[164:168])
        self.assertEqual(materials._array_layer(obj, .6).read().get_image_data(), texture.image_data[84:168])
        self.assertEqual(materials._array_layer(obj, 200).preview_array_layer, 1)
        self.assertEqual(materials._array_layer(obj, -.6).preview_array_layer, 0)
        self.assertEqual(materials._array_layer(obj, .49).preview_array_layer, 0)
        with self.assertRaises(ValueError):
            materials._array_layer(obj, math.nan)

    def test_active_texture_metadata_reuses_top_and_exports_authored_levels(self):
        obj, texture = self.texture()
        tree = {"m_ShaderKeywords": "", "m_SavedProperties": {
            "m_Floats": [("_RimglightIntensity", 0)], "m_Colors": [],
            "m_TexEnvs": [("_MainTex", {"m_Texture": {"m_PathID": 7}})]}}
        seen = []

        def export(image):
            seen.append(image.read().get_image_data())
            return len(seen) - 1

        with patch("webtools.core.model_viewer._ref", return_value=obj):
            value = materials.attach_member_metadata(None, object(), tree, {}, export)
        main = value["textures"]["_MainTex"]
        self.assertEqual(main["mipmaps"], [0, 1, 2])
        self.assertEqual(main["mipWidths"], [4, 2, 1])
        self.assertEqual(seen, [texture.image_data, texture.image_data[64:80], texture.image_data[80:84]])
        self.assertEqual(value["limitations"], [])


if __name__ == "__main__":
    unittest.main()
