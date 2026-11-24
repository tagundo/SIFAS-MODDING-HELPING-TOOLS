import hashlib
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
        self.assertEqual(output["extras"]["other"], 1)

    def test_rim_is_a_used_input_even_when_authored_off(self):
        # Every Hidden/AS/Member/Main variant evaluates the rim; the timeline
        # writes its intensity, so authored zeros do not drop the texture.
        for floats, color in (({"_RimglightIntensity": 0}, None), ({"_RIMLIGHT": 0}, (0, 0, 0, 0)),
                              ({"_RimglightIntensity": 1}, None)):
            with self.subTest(floats=floats, color=color):
                tree = self.tree(**floats)
                if color:
                    tree["m_SavedProperties"]["m_Colors"] = [("_RimlightColor", dict(zip("rgba", color)))]
                metadata = materials.attach_member_metadata(None, object(), tree, {}, lambda _: self.fail("No image expected"))
                self.assertTrue(metadata["features"]["rimlight"])
                # Unassigned slot: the ShaderLab default ("white"), not a replacement asset.
                self.assertEqual(metadata["textures"]["_RimlightTex"], {"default": [1, 1, 1, 1]})
                self.assertEqual(materials.authored_rimlight(metadata), floats.get("_RimglightIntensity") == 1)

    def test_authored_zero_rim_exports_the_rim_texture_and_its_mips(self):
        obj, texture = fake_texture()
        tree = self.tree(_RimglightIntensity=0)
        tree["m_SavedProperties"]["m_TexEnvs"] = [("_RimlightTex", {"m_Texture": {"m_PathID": 7}})]
        seen = []

        def export(image):
            seen.append(image.read().get_image_data())
            return len(seen) - 1

        with patch("webtools.core.model_viewer._ref", return_value=obj):
            metadata = materials.attach_member_metadata(None, object(), tree, {}, export)
        rim = metadata["textures"]["_RimlightTex"]
        self.assertEqual((rim["index"], rim["mipmaps"], rim["name"]), (0, [0, 1, 2], "Neutral image"))
        self.assertEqual(seen, [texture.image_data, texture.image_data[64:80], texture.image_data[80:84]])
        self.assertTrue(metadata["features"]["rimlight"])
        self.assertFalse(materials.authored_rimlight(metadata))

    def test_keywords_select_variants_not_stale_toggle_floats(self):
        first = materials.attach_member_metadata(None, object(), self.tree(_MATCAP=1), {}, lambda _: 0)
        second = materials.attach_member_metadata(None, object(), self.tree("_MATCAP_ON _EMISSIVE_ON _CHEEK_ON"), {}, lambda _: 0)
        self.assertFalse(first["features"]["matcap"])
        self.assertTrue(all(second["features"][name] for name in ("matcap", "emissive", "cheek")))
        self.assertEqual(second["textures"]["_EmissiveTex"]["default"], [0, 0, 0, 1])

    def test_cheek_array_exports_every_slice_as_exact_bytes(self):
        # A stock head: no _CHEEK_ON, _CheekIntensity 0, a 2-slice array
        # (Clamp, 1 mip) that MemberCheekMixer drives at runtime.
        slices = [bytes([index] * 16 * 4) for index in (17, 230)]
        obj, array = fake_texture(width=4, height=4, count=1, depth=2, pixels=b"".join(slices), wrap=1, name="cheek_array")
        tree = self.tree(_CheekIntensity=0, _CheekTexArrayIndex=1)
        tree["m_SavedProperties"]["m_TexEnvs"] = [("_CheekTex", {"m_Texture": {"m_PathID": 7}})]
        exported, by_key = [], {}

        def export(image):
            key = image.path_id
            if key not in by_key:
                texture = image.read()
                by_key[key] = len(exported)
                exported.append((texture.get_image_data(), texture.m_TextureSettings.m_WrapU,
                                 texture.m_TextureSettings.m_WrapV, texture.m_Width, texture.m_Height))
            return by_key[key]

        with patch("webtools.core.model_viewer._ref", return_value=obj):
            metadata = materials.attach_member_metadata(None, object(), tree, {}, export)
        cheek = metadata["textures"]["_CheekTex"]
        self.assertTrue(metadata["features"]["cheek"])
        self.assertEqual([layer["arrayLayer"] for layer in cheek["layers"]], [0, 1])
        self.assertEqual([exported[layer["index"]][0] for layer in cheek["layers"]], slices)
        self.assertTrue(all(row[1:] == (1, 1, 4, 4) for row in exported), "Clamp and the original size are kept")
        self.assertEqual(len(exported), 2, "the authored slice reuses its exported layer")
        self.assertEqual((cheek["arrayLayer"], cheek["index"], cheek["depth"], cheek["name"]),
                         (1, cheek["layers"][1]["index"], 2, "cheek_array"))
        self.assertTrue(all("mipmaps" not in layer for layer in cheek["layers"]))
        self.assertEqual(array.image_data, b"".join(slices))
        self.assertEqual(metadata["limitations"], [])

    def test_cheek_array_identity_against_the_shared_resources_array(self):
        # MemberCheekBase.SetCheekTexture binds Resources cheek_array, never the
        # head's own; only its recorded identity can say the copy is exact.
        shared = materials.SHARED_CHEEK_ARRAY
        self.assertEqual(shared["resource"], "Live/Characters/facialAssets/cheek_array")
        self.assertEqual(shared["width"] * shared["height"] * shared["depth"] * 4, shared["bytes"])

        def metadata_for(pixels, **settings):
            obj, array = fake_texture(width=4, height=4, count=1, depth=2, pixels=pixels, wrap=1, name="cheek_array")
            for key, value in settings.items():
                setattr(array, key, value)
            tree = self.tree()
            tree["m_SavedProperties"]["m_TexEnvs"] = [("_CheekTex", {"m_Texture": {"m_PathID": 7}})]
            with patch("webtools.core.model_viewer._ref", return_value=obj):
                return materials.attach_member_metadata(None, object(), tree, {}, lambda image: 0)

        pixels = bytes(range(128))
        modded = metadata_for(pixels)["textures"]["_CheekTex"]["sharedArray"]
        self.assertEqual(modded, {"resource": shared["resource"], "matches": False})
        identity = materials._array_identity(fake_texture(width=4, height=4, count=1, depth=2, pixels=pixels, wrap=1)[1])
        self.assertEqual((identity["bytes"], identity["sha256"]), (128, hashlib.sha256(pixels).hexdigest()))
        self.assertEqual({key: identity[key] for key in ("width", "height", "depth", "format", "mips", "filter", "wrapU", "wrapV",
                                                         "colorSpace")}, {"width": 4, "height": 4, "depth": 2, "format": 4,
                                                                          "mips": 1, "filter": 1, "wrapU": 1, "wrapV": 1,
                                                                          "colorSpace": 1})
        # Same layout, sampler and bytes as the shared array: the head's copy is exact.
        with patch.object(materials, "_array_identity", return_value={key: value for key, value in shared.items()
                                                                       if key != "resource"}):
            exact = metadata_for(pixels)["textures"]["_CheekTex"]["sharedArray"]
        self.assertTrue(exact["matches"])
        with patch.object(materials, "_array_identity", return_value=None):
            unknown = metadata_for(pixels)["textures"]["_CheekTex"]["sharedArray"]
        self.assertIsNone(unknown["matches"])

    def test_cheek_slot_without_array_keeps_authored_feature(self):
        none = materials.attach_member_metadata(None, object(), self.tree(), {}, lambda _: self.fail("No image expected"))
        self.assertFalse(none["features"]["cheek"])
        self.assertNotIn("_CheekTex", none["textures"])
        obj, _ = fake_texture()
        tree = self.tree()
        tree["m_SavedProperties"]["m_TexEnvs"] = [("_CheekTex", {"m_Texture": {"m_PathID": 7}})]
        with patch("webtools.core.model_viewer._ref", return_value=obj):
            flat = materials.attach_member_metadata(None, object(), tree, {}, lambda _: self.fail("No image expected"))
        # Only a Texture2DArray feeds MemberCheekBase; an authored-off 2D slot stays unused.
        self.assertFalse(flat["features"]["cheek"])
        self.assertNotIn("_CheekTex", flat["textures"])
        self.assertEqual(flat["limitations"], [])

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


def fake_texture(*, width=4, height=4, count=3, depth=None, pixels=None, wrap=0, name="Neutral image"):
    """A raw RGBA32 Unity texture (or array) with its complete authored mip chain."""
    settings = SimpleNamespace(m_FilterMode=1, m_WrapU=wrap, m_WrapV=wrap)
    data = pixels if pixels is not None else bytes(range(84))
    value = SimpleNamespace(m_Name=name, m_Width=width, m_Height=height,
        m_MipCount=count, m_ImageCount=1, m_TextureDimension=2, m_TextureFormat=4,
        m_Format=4, m_TextureSettings=settings, m_ColorSpace=1,
        image_data=data, m_StreamData=SimpleNamespace(size=0), get_image_data=lambda: data)
    if depth is not None:
        value.m_Depth = depth
    obj = SimpleNamespace(assets_file=object(), path_id=7,
                          type=SimpleNamespace(name="Texture2D" if depth is None else "Texture2DArray"), read=lambda: value)
    return obj, value


class OriginalImageLevelTests(unittest.TestCase):
    def texture(self, **arguments):
        return fake_texture(**arguments)

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
