"""Independent pixel/mip and compatibility oracles for the Body atlas baker."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from graft_texture_atlas import AtlasCompatibilityError, MaterialSource, bake_game_atlas


class Asset:
    def __init__(self, path_id, kind, tree, texture=None, assets_file=None):
        self.path_id = path_id
        self.type = SimpleNamespace(name=kind)
        self.tree = tree
        self.texture = texture
        self.assets_file = assets_file or SimpleNamespace(externals=[])

    def read(self):
        return self.texture

    def read_typetree(self):
        return copy.deepcopy(self.tree)


def texture_asset(path_id, images, *, wrap=0, filter_mode=1, color_space=1):
    pixels = b"".join(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes() for image in images)
    settings = dict(m_FilterMode=filter_mode, m_Aniso=1, m_MipBias=0., m_WrapU=wrap, m_WrapV=wrap, m_WrapW=0)
    tree = dict(m_Name="original", m_Width=images[0].width, m_Height=images[0].height,
                m_TextureFormat=4, m_MipCount=len(images), m_CompleteImageSize=len(pixels),
                m_ColorSpace=color_space, m_ImageCount=1, m_TextureDimension=2,
                m_TextureSettings=settings, m_StreamData=dict(path="old.resS", offset=12, size=len(pixels)),
                m_StreamingMipmaps=True, **{"image data": pixels})
    value = SimpleNamespace(**{key: val for key, val in tree.items() if key != "image data"})
    value.m_TextureSettings = SimpleNamespace(**settings)
    value.m_StreamData = None
    value.image_data = pixels
    value.object_reader = SimpleNamespace(platform=0, version=(2019, 4, 0, 0))
    value.get_image_data = lambda: pixels
    return Asset(path_id, "Texture2D", tree, value)


def source(name, images, *, rim=None, keywords="", floats=None, colors=None, wrap=0, bounds=None):
    main = texture_asset(2, images, wrap=wrap)
    objects = {1: Asset(1, "Shader", {"m_Name": "AS/Member"}), 2: main}
    envs = [("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 2},
                            "m_Scale": {"x": .2, "y": .7}, "m_Offset": {"x": .1, "y": .3}})]
    if rim:
        objects[3] = texture_asset(3, rim, wrap=wrap)
        envs.append(("_RimlightTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 3}}))
    tree = dict(m_Name=name, m_Shader={"m_FileID": 0, "m_PathID": 1}, m_ShaderKeywords=keywords,
                m_SavedProperties={"m_TexEnvs": envs, "m_Floats": list((floats or {}).items()),
                                   "m_Colors": list((colors or {}).items())})
    return MaterialSource(name, tree, objects, uv_bounds=bounds)


def image(size, color):
    return Image.new("RGBA", size, color)


def levels(texture):
    """Read output RGBA bytes independently of the production mip exporter."""
    tree, offset, output = texture.tree, 0, []
    for level in range(tree["m_MipCount"]):
        width, height = max(1, tree["m_Width"] >> level), max(1, tree["m_Height"] >> level)
        size = width * height * 4
        raw = tree["image data"][offset:offset + size]
        output.append(np.asarray(Image.frombytes("RGBA", (width, height), raw).transpose(Image.Transpose.FLIP_TOP_BOTTOM)))
        offset += size
    if offset != len(tree["image data"]):
        raise AssertionError("Unexpected mip payload bytes")
    return output


class GameAtlasTests(unittest.TestCase):
    def test_touching_cells_copy_asymmetric_pixels_with_no_padding_or_st_transform(self):
        pixels = np.arange(4 * 4 * 4, dtype="uint8").reshape(4, 4, 4)
        wearer = source("wearer", [Image.fromarray(pixels)])
        donor = source("donor", [Image.fromarray(255 - pixels)])
        before = copy.deepcopy(wearer.tree), copy.deepcopy(wearer.objects[2].tree)
        baked = bake_game_atlas(wearer, [donor])
        texture = baked.textures["_MainTex"]
        self.assertEqual((texture.width, texture.height), (8, 4))
        np.testing.assert_array_equal(levels(texture)[0], np.concatenate([pixels, 255 - pixels], axis=1))
        self.assertEqual(baked.transforms[0].scale, (.5, 1.))
        self.assertEqual(baked.transforms[1].offset, (.5, 0.))
        self.assertEqual(texture.tree["m_StreamData"], dict(path="", offset=0, size=0))
        self.assertEqual(texture.tree["m_TextureSettings"], wearer.objects[2].tree["m_TextureSettings"])
        self.assertFalse(texture.tree["m_StreamingMipmaps"])
        self.assertEqual((wearer.tree, wearer.objects[2].tree), before)
        with self.assertRaisesRegex(AtlasCompatibilityError, "no padding"):
            bake_game_atlas(wearer, [donor], gutter=1)

    def test_authored_mips_including_one_pixel_survive_and_shared_tail_averages(self):
        wearer_images = [image((4, 4), (240, 0, 0, 255)), image((2, 2), (0, 220, 0, 255)), image((1, 1), (0, 0, 200, 255))]
        donor_images = [image((4, 4), (10, 0, 0, 255)), image((2, 2), (0, 20, 0, 255)), image((1, 1), (0, 0, 40, 255))]
        baked = bake_game_atlas(source("wearer", wearer_images), [source("donor", donor_images)])
        output = levels(baked.textures["_MainTex"])
        self.assertEqual([value.shape[:2] for value in output], [(4, 8), (2, 4), (1, 2), (1, 1)])
        for level in range(3):
            expected = np.concatenate([np.asarray(wearer_images[level]), np.asarray(donor_images[level])], axis=1)
            np.testing.assert_array_equal(output[level], expected)
        np.testing.assert_array_equal(output[-1][0, 0], [0, 0, 120, 255])

    def test_duplicate_materials_are_identity_and_repeated_donors_share_one_cell(self):
        wearer = source("wearer", [image((4, 4), "red")])
        identical = source("copy", [image((4, 4), "red")])
        with patch("graft_texture_atlas._mip_images", side_effect=AssertionError("Identity must not decode")):
            baked = bake_game_atlas(wearer, [identical])
        self.assertTrue(baked.identity)
        self.assertFalse(baked.textures)
        np.testing.assert_array_equal(baked.transforms[1].remap_uv([[.25, .75]]), [[.25, .75]])
        donor = source("donor", [image((4, 4), "blue")])
        baked = bake_game_atlas(wearer, [donor, donor])
        self.assertEqual(baked.unique_sources, 2)
        self.assertEqual(baked.transforms[1], baked.transforms[2])
        self.assertEqual(baked.textures["_MainTex"].width, 8)

    def test_auxiliary_slot_uses_common_layout_at_its_own_native_scale(self):
        wearer = source("wearer", [image((8, 8), "red")], rim=[image((4, 4), (3, 4, 5, 255))])
        donor = source("donor", [image((8, 8), "blue")], rim=[image((2, 2), (8, 9, 10, 255))])
        baked = bake_game_atlas(wearer, [donor])
        self.assertEqual((baked.textures["_MainTex"].width, baked.textures["_MainTex"].height), (16, 8))
        rim = baked.textures["_RimlightTex"]
        self.assertEqual((rim.width, rim.height), (8, 4))
        np.testing.assert_array_equal(levels(rim)[0][:, :4], np.full((4, 4, 4), [3, 4, 5, 255], dtype="uint8"))
        np.testing.assert_array_equal(levels(rim)[0][:, 4:], np.full((4, 4, 4), [8, 9, 10, 255], dtype="uint8"))

    def test_retained_wearer_rim_profile_accepts_stock_differences(self):
        wearer = source("wearer", [image((4, 4), "red")], floats={"_RimglightIntensity": 0, "_RimglightPower": 8})
        donor = source("donor", [image((4, 4), "blue")], keywords="_RIMLIGHT_ON", floats={"_RimglightIntensity": 1, "_RimglightPower": 3})
        baked = bake_game_atlas(wearer, [donor])
        self.assertTrue(any("wearer rim-light shader settings retained" in message for message in baked.diagnostics))
        self.assertEqual(dict(wearer.tree["m_SavedProperties"]["m_Floats"])["_RimglightIntensity"], 0)

    def test_incompatible_active_shader_input_and_samplers_are_actionable(self):
        wearer = source("wearer", [image((4, 4), "red")])
        for donor, text in ((source("donor", [image((4, 4), "blue")], floats={"_CullMode": 0}), "_CullMode"),
                            (source("donor", [image((4, 4), "blue")], wrap=1), "sampler"),
                            (source("donor", [image((4, 4), "blue")], keywords="_CHEEK_ON"), "variants")):
            with self.subTest(text=text), self.assertRaisesRegex(AtlasCompatibilityError, text):
                bake_game_atlas(wearer, [donor])
        moving = source("moving", [image((4, 4), "red")], keywords="_EMISSIVE_ON")
        with self.assertRaisesRegex(AtlasCompatibilityError, "animated emissive"):
            bake_game_atlas(moving, [moving])

    def test_normal_driven_matcap_difference_is_rejected(self):
        wearer = source("wearer", [image((4, 4), "red")], keywords="_MATCAP_ON")
        donor = source("donor", [image((4, 4), "blue")], keywords="_MATCAP_ON")
        for material, color in ((wearer, "white"), (donor, "black")):
            material.objects[4] = texture_asset(4, [image((4, 4), color)])
            material.tree["m_SavedProperties"]["m_TexEnvs"].append(("_MatcapTex", {"m_Texture": {"m_PathID": 4}}))
        with self.assertRaisesRegex(AtlasCompatibilityError, "Normal-driven _MatcapTex"):
            bake_game_atlas(wearer, [donor])

    def test_cull_mismatch_keeps_guard_and_names_values_and_matching_target(self):
        wearer = source("Body", [image((4, 4), "red")], floats={"_CullMode": 0})
        donor = source("Head accessory", [image((4, 4), "blue")], floats={"_CullMode": 2})
        before = copy.deepcopy(wearer.tree), copy.deepcopy(donor.tree)
        with self.assertRaisesRegex(AtlasCompatibilityError, r"Head accessory: _CullMode is 2, while Body uses 0.*Hair"):
            bake_game_atlas(wearer, [donor])
        self.assertEqual((wearer.tree, donor.tree), before)

    def test_registered_stock_character_outline_stencil_uses_wearer_state_only(self):
        wearer = source("wearer Hair", [image((4, 4), "red")], floats={"_OutlineStencilComp": 3})
        donor = source("donor head accessory", [image((4, 4), "blue")], floats={"_OutlineStencilComp": 8})
        for material in (wearer, donor):
            sf = SimpleNamespace(externals=[SimpleNamespace(path="archive:/CAB-9382ea964987eceddd567506a3b21312")])
            material.tree["m_Shader"] = {"m_FileID": 1, "m_PathID": 8291131735116688333}
            material.material_object = Asset(9, "Material", material.tree, assets_file=sf)
            material.objects[8] = Asset(8, "MonoScript", {"m_ClassName": "LiveCoreMemberRimlight",
                "m_Namespace": "LLAS.Scene.Live.Components", "m_AssemblyName": "Assembly-CSharp.dll"}, assets_file=sf)
            material.objects[7] = Asset(7, "MonoBehaviour", {"m_Script": {"m_FileID": 0, "m_PathID": 8},
                "materials": [{"m_FileID": 0, "m_PathID": 9}]}, assets_file=sf)
        before = copy.deepcopy(wearer.tree), copy.deepcopy(donor.tree)
        baked = bake_game_atlas(wearer, [donor])
        self.assertTrue(any("8 -> 3" in message and "wearer Hair" in message for message in baked.diagnostics))
        self.assertEqual((wearer.tree, donor.tree), before)
        # Neither numeric similarity nor a similarly named unrelated component
        # establishes the original game's character stencil protocol.
        for edit in ("unregistered", "wrong namespace", "local shader", "other stencil", "cull"):
            with self.subTest(edit=edit):
                changed = source("unrelated", [image((4, 4), "blue")], floats={"_OutlineStencilComp": 8})
                changed.tree = copy.deepcopy(donor.tree)
                changed.objects = dict(donor.objects)
                changed.material_object = donor.material_object
                if edit == "unregistered":
                    changed.objects.pop(7)
                elif edit == "wrong namespace":
                    changed.objects[8] = Asset(8, "MonoScript", {"m_ClassName": "LiveCoreMemberRimlight",
                        "m_Namespace": "Unrelated", "m_AssemblyName": "Assembly-CSharp.dll"}, assets_file=donor.material_object.assets_file)
                elif edit == "other stencil":
                    changed.tree["m_SavedProperties"]["m_Floats"] = [("_OutlineStencilComp", 5)]
                elif edit == "local shader":
                    changed.tree["m_Shader"] = {"m_FileID": 0, "m_PathID": 1}
                else:
                    changed.tree["m_SavedProperties"]["m_Floats"].append(("_CullMode", 0))
                with self.assertRaisesRegex(AtlasCompatibilityError, "_OutlineStencilComp|_CullMode"):
                    bake_game_atlas(wearer, [changed])

    def test_repeat_and_mirror_domains_copy_whole_periods_without_borders(self):
        pattern = Image.fromarray(np.array([[[1, 2, 3, 255], [4, 5, 6, 255]]], dtype="uint8"))
        for wrap, expected in ((0, [1, 4, 1, 4, 1, 4]), (2, [4, 1, 1, 4, 4, 1])):
            wearer = source("wearer", [pattern], wrap=wrap, bounds=(-1, 0, 2, 1))
            donor = source("donor", [image((2, 1), "blue")], wrap=wrap)
            baked = bake_game_atlas(wearer, [donor])
            pixels = levels(baked.textures["_MainTex"])[0]
            self.assertEqual(pixels[0, :6, 0].tolist(), expected)
            mapped = baked.transforms[0].remap_uv([[-1, 0], [2, 1]])
            self.assertTrue(np.all(mapped >= 0) and np.all(mapped <= 1))

    def test_limits_fail_before_decoding_and_inputs_are_unchanged(self):
        wearer = source("wearer", [image((4, 4), "red")])
        donor = source("donor", [image((4, 4), "blue")])
        with patch("graft_texture_atlas._mip_images", side_effect=AssertionError("Too large must fail before decode")):
            with self.assertRaisesRegex(AtlasCompatibilityError, "cannot fit original texture detail"):
                bake_game_atlas(wearer, [donor], max_dimension=4)
            with self.assertRaisesRegex(AtlasCompatibilityError, "memory budget"):
                bake_game_atlas(wearer, [donor], max_total_bytes=16)
        oversized = source("oversized", [image((4, 4), "blue")])
        oversized.objects[2].read().m_Width = 100000000
        oversized.objects[2].read().get_image_data = lambda: self.fail("Dimensions must be checked before reading source payloads")
        with self.assertRaisesRegex(AtlasCompatibilityError, "source texture exceeds"):
            bake_game_atlas(wearer, [oversized])
        invalid_wrap = source("invalid wrap", [image((4, 4), "blue")], wrap=99)
        with self.assertRaisesRegex(AtlasCompatibilityError, "sampler/filter/wrap"):
            bake_game_atlas(wearer, [invalid_wrap])
        partial = source("partial", [image((4, 4), "blue"), image((2, 2), "green")])
        with self.assertRaisesRegex(AtlasCompatibilityError, "partial authored mip"):
            bake_game_atlas(wearer, [partial])

    def test_default_decoder_uses_isolated_codecs_on_desktop_too(self):
        from graft_texture_atlas import _decode_default
        from webtools.core import decode
        texture = object()
        expected = image((1, 1), "red")
        with patch.object(decode, "_embedded_android", return_value=False), patch.object(decode, "_android_image", return_value=expected) as isolated:
            self.assertIs(_decode_default(texture), expected)
        self.assertIs(isolated.call_args.args[0], texture)


if __name__ == "__main__":
    unittest.main()
