"""Exercise native stage shader inputs and ownership metadata."""
from io import BytesIO
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from webtools.core import decode, model_materials, model_viewer, mv_studio_stage_materials as stage
from webtools.core import mv_studio_stage_display as displays
from webtools.core import mv_studio_stage_overlay as overlay


class StageDisplayMaterialTests(unittest.TestCase):
    def test_vertex_color_follows_the_compiled_keyword(self):
        original = SimpleNamespace(type=SimpleNamespace(name="Material"))
        floats = {"_StencilComp": 8, "_StencilRef": 2, "_StencilPassOp": 2,
                  "_StencilZFailOp": 0, "_VERTEX_COLOR": 0}
        tree = {"m_ShaderKeywords": "_VERTEX_COLOR_ON _AUTO_PLAY_ON", "m_CustomRenderQueue": -1,
                "m_SavedProperties": {"m_Floats": floats.items()}}
        scene = SimpleNamespace(tree=lambda _: tree)
        with patch.object(displays, "shader_name", return_value="AS/General/Opaque"):
            # The [Toggle] float and keywords outside the shader's keyword space do nothing in Unity.
            variant = displays.read(scene, None, original)
            self.assertTrue(variant["vertexColor"])
            self.assertEqual((variant["kind"], variant["queue"], variant["stencil"]), ("general", 2000, 2))
            tree["m_ShaderKeywords"] = ""
            floats["_VERTEX_COLOR"] = 1
            fallback = displays.read(scene, None, original)
            self.assertNotIn("vertexColor", fallback)
            self.assertEqual({k: v for k, v in variant.items() if k != "vertexColor"}, fallback)
            tree["m_ShaderKeywords"] = "SOFTPARTICLES_ON"
            with self.assertRaises(displays.Unsupported):
                displays.read(scene, None, original)
        tree["m_ShaderKeywords"] = "_VERTEX_COLOR_ON"
        with patch.object(displays, "shader_name", return_value="AS/General/Transparent"):
            self.assertTrue(displays.read(scene, None, original)["vertexColor"])

    def test_stencil_state_is_read_from_the_material(self):
        original = SimpleNamespace(type=SimpleNamespace(name="Material"))
        floats = {"_StencilComp": 8, "_StencilRef": 2, "_StencilPassOp": 2, "_StencilZFailOp": 2}
        tree = {"m_ShaderKeywords": "", "m_CustomRenderQueue": -1, "m_SavedProperties": {"m_Floats": floats.items()}}
        scene = SimpleNamespace(tree=lambda _: tree)
        with patch.object(displays, "shader_name", return_value="AS/General/Opaque"):
            # mat_dis_bg_so2035_opa_0x / so2036_opa_0x: _StencilZFailOp 2 (Replace).
            self.assertEqual(displays.read(scene, None, original)["stencilZFail"], 2)
            # mat_dis_so0122_01 (10122/3): Always, Keep -- the screen writes no reference.
            floats.update(_StencilPassOp=0, _StencilZFailOp=0)
            self.assertEqual({key: displays.read(scene, None, original)[key] for key in
                              ("stencil", "stencilComp", "stencilPass", "stencilZFail")},
                             {"stencil": 2, "stencilComp": 8, "stencilPass": 0, "stencilZFail": 0})
            for value in (8, 2.5, float("nan")):
                floats["_StencilZFailOp"] = value
                with self.assertRaises(displays.Unsupported):
                    displays.read(scene, None, original)


class ActualStageDisplayTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_12035 / _12036 to the original Android stage_effect bundles."""

    def screens(self, variable):
        import os
        from pathlib import Path
        raw = os.environ.get(variable)
        if not raw or not Path(raw).is_file():
            self.skipTest(f"Set {variable} to the original stage_effect bundle")
        deadline = time.monotonic() + 120
        env = model_viewer._environment([raw], deadline)
        scene = model_viewer._Scene(env, deadline)
        materials = SimpleNamespace(texture=lambda texture: texture.path_id)
        result = {}
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            tree = scene.tree(obj)
            if "materialReferences" not in tree:
                continue
            found = displays.binding(scene, obj, tree)
            exported = displays.export(scene, materials, found[1]) if found else None
            result[found[1][0].rsplit("/", 1)[-1] if found else None] = exported
        return result

    def test_12035_screens_keep_their_native_backgrounds(self):
        screens = self.screens("SIFAS_TEST_STAGE_EFFECT_12035")
        self.assertEqual({name: len(screen["variants"]) for name, screen in screens.items()}, {"main_01": 4, "sub_01": 3})
        for screen in screens.values():
            self.assertEqual({variant["background"]["stencilZFail"] for variant in screen["variants"]}, {2})
            self.assertEqual(screen["fallback"]["stencilZFail"], 0)

    def test_12036_screens_keep_their_native_backgrounds(self):
        screens = self.screens("SIFAS_TEST_STAGE_EFFECT_12036")
        self.assertEqual({name: len(screen["variants"]) for name, screen in screens.items()}, {"main_01": 2, "sub_01": 2})


class StageMatCapMaterialTests(unittest.TestCase):
    def test_world_matcap_uses_compiled_state_and_keeps_exact_queued_sort(self):
        original = SimpleNamespace(type=SimpleNamespace(name="Material"), assets_file=SimpleNamespace(
            externals=[SimpleNamespace(path="archive:/CAB-2700399fc9d3cc42e6ceeda597765088")]))
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        tree = {"m_Shader": {"m_FileID": 1, "m_PathID": 4078992641913009367},
                "m_ShaderKeywords": "_VERTEX_COLOR_OFF _VERTEX_COLOR_ON", "m_CustomRenderQueue": -1,
                "m_SavedProperties": {
                    "m_Floats": [("_BlendDst", 1), ("_StencilComp", 3), ("_StencilRef", 2), ("_CullMode", 0)],
                    "m_Colors": [("_TintColor", {"r": 7.5, "g": 13, "b": 32, "a": .2}),
                                 ("_AddColor", {"r": 1, "g": .6, "b": .7, "a": 5})],
                    "m_TexEnvs": [("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 91}})],
                }}
        scene = SimpleNamespace(tree=lambda _: tree)
        materials = SimpleNamespace(texture=Mock(return_value=17))
        root = {"m_FileID": 0, "m_PathID": 21}
        skin = {"m_RootBone": root, "m_Bones": [root], "m_AABB": {"m_Center": {"x": 2, "y": 4, "z": -3}}}
        with patch.object(model_viewer, "_ref", return_value=texture):
            self.assertIsNone(overlay.read_material(scene, original))
            admitted = overlay.read_material(scene, original, world=True)
            exported = overlay.export_material(materials, admitted, renderer_tree=skin, skinned=True)
            self.assertEqual(exported, {
                "matcap": True, "alphaBlend": True, "depthTest": True, "vertexColor": True,
                "texture": 17, "cull": 2, "queue": 3000, "tint": [7.5, 13, 32, .2],
                "addColor": [1, .6, .7], "sortJoint": 0, "sortCenter": [-2, 4, -3],
            })
            tree["m_CustomRenderQueue"] = 2000
            self.assertIsNone(overlay.read_material(scene, original, world=True))
            tree["m_CustomRenderQueue"] = 3010
            tree["m_SavedProperties"] = {}
            default = overlay.read_material(scene, original, world=True)
            self.assertEqual((default["queue"], default["texture"], default["addColor"], default["tint"]),
                             (3010, None, [0, 0, 0], [1, 1, 1, 1]))
            original.assets_file.externals[0].path = "archive:/CAB-unverified"
            self.assertIsNone(overlay.read_material(scene, original, world=True))


class StageOpaqueMaterialTests(unittest.TestCase):
    def test_camera_depth_uses_the_native_pass_queue_and_casting_mode(self):
        material = SimpleNamespace(assets_file=SimpleNamespace(
            externals=[SimpleNamespace(path="CAB-fc0511ca63f2d94bbfe211260d08ddd1")]))
        tree = {"m_Shader": {"m_FileID": 1, "m_PathID": -6509019661097744245}, "m_CustomRenderQueue": -1}
        scene = SimpleNamespace(tree=lambda _: tree)
        renderer = {"m_CastShadows": 0}
        self.assertEqual(stage.camera_depth(scene, material, renderer, supports_cutout=False), {"kind": "opaque"})
        self.assertIsNone(stage.camera_depth(scene, material, {"m_CastShadows": 3}, supports_cutout=True))
        tree["m_CustomRenderQueue"] = 2501
        self.assertIsNone(stage.camera_depth(scene, material, renderer, supports_cutout=True))
        tree["m_CustomRenderQueue"] = 2500
        tree["m_ShaderKeywords"] = "_ALPHATEST_ON"
        self.assertIsNone(stage.camera_depth(scene, material, renderer, supports_cutout=False))
        self.assertEqual(stage.camera_depth(scene, material, renderer, supports_cutout=True), {"kind": "cutout"})
        tree["disabledShaderPasses"] = ["SHADOWCASTER"]
        self.assertIsNone(stage.camera_depth(scene, material, renderer, supports_cutout=True))

    def test_general_opaque_uses_compiled_blend_and_depth_but_authored_stencil(self):
        material = SimpleNamespace(
            path_id=11, type=SimpleNamespace(name="Material"),
            assets_file=SimpleNamespace(externals=[SimpleNamespace(path="CAB-618a998abe328b9a2b05b370a5907b3e")]),
        )
        floats = [("_SrcBlend", 1), ("_DstBlend", 10), ("_ZWrite", 0), ("_CullMode", 0)]
        color = dict.fromkeys("rgba", 1)
        tree = {
            "m_Shader": {"m_FileID": 1, "m_PathID": 8330475765356442367},
            "m_ShaderKeywords": "_ALPHAPREMULTIPLY_ON",
            "m_SavedProperties": {
                "m_Floats": floats,
                "m_Colors": [("_AmbientColor", color), ("_TintColor", color)],
                "m_TexEnvs": [("_MainTex", {"m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})],
            },
        }
        scene = SimpleNamespace(tree=lambda _: tree)
        descriptor = stage.read_material(scene, material, {}, {})
        self.assertEqual(descriptor["shader"], "general")
        self.assertEqual(descriptor["cull"], 0)
        floats.append(("_StencilPassOp", 2))
        self.assertIsNone(stage.read_material(scene, material, {}, {}))


class StageAlphaMaterialTests(unittest.TestCase):
    def test_world_additive_depth_write_uses_authored_material_state(self):
        material = SimpleNamespace(type=SimpleNamespace(name="Material"), assets_file=SimpleNamespace(
            parent=None, externals=[SimpleNamespace(path="CAB-adf9ba7b61bd035c754bf74ae44927cb")]))
        floats = {"_BlendSrc": 5., "_BlendDst": 1., "_ZTestMode": 4., "_ZWriteParam": 1., "_CullMode": 0.,
                  "_StencilComp": 8., "_StencilRef": 2., "_StencilPassOp": 0., "_StencilZFailOp": 0.}
        tree = {"m_Shader": {"m_FileID": 1, "m_PathID": 7151384334892346267},
                "m_CustomRenderQueue": 3000, "m_ShaderKeywords": "_VERTEX_COLOR_ON",
                "m_SavedProperties": {"m_Floats": floats.items()}}
        scene = SimpleNamespace(tree=lambda _: tree)
        self.assertIsNone(overlay.read_material(scene, material))
        fields = overlay.read_material(scene, material, world=True)
        self.assertEqual(fields, {"texture": None, "tint": [1, 1, 1, 1], "uv": [1, 1, 0, 0],
                                  "vertexColor": True, "cull": 0, "queue": 3000,
                                  "depthTest": True, "depthWrite": True})
        self.assertEqual(overlay.export_material(None, fields), fields)
        for rejected in ({"_ZWriteParam": 2.}, {"_BlendDst": 10., "_StencilComp": 3.},
                         {"_StencilComp": 3.}, {"_ZTestMode": 8.}, {"_SATURATE": 1.}):
            with self.subTest(rejected=rejected), patch.dict(floats, rejected):
                self.assertIsNone(overlay.read_material(scene, material, world=True))
        floats["_ZWriteParam"] = 0.
        self.assertNotIn("depthWrite", overlay.read_material(scene, material, world=True))
        self.assertNotIn("depthWrite", overlay.read_material(scene, material))

    def test_world_alpha_blend_keeps_authored_stencil_comparison(self):
        from webtools.core import mv_studio_stage_overlay as transparent

        material = SimpleNamespace(type=SimpleNamespace(name="Material"))
        floats = [("_BlendSrc", 5), ("_BlendDst", 10), ("_ZTestMode", 4), ("_ZWriteParam", 0),
                  ("_StencilComp", 3), ("_StencilRef", 2), ("_StencilPassOp", 0), ("_StencilZFailOp", 0)]
        scene = SimpleNamespace(tree=lambda _: {
            "m_SavedProperties": {"m_Floats": floats},
            "m_CustomRenderQueue": 2910,
            "m_ShaderKeywords": "_VERTEX_COLOR_ON",
        })
        with patch.object(transparent, "_shader_matches", return_value=True):
            self.assertIsNone(transparent.read_material(scene, material))
            fields = transparent.read_material(scene, material, world=True)
            self.assertEqual(fields, {"texture": None, "tint": [1, 1, 1, 1], "uv": [1, 1, 0, 0],
                                      "vertexColor": True, "cull": 0, "queue": 2910, "depthTest": True,
                                      "alphaBlend": True, "stencilRef": 2})
            floats.append(("_StencilZFailOp", 2))
            self.assertIsNone(transparent.read_material(scene, material, world=True))


class StageTextureSamplerTests(unittest.TestCase):
    @staticmethod
    def source():
        settings = SimpleNamespace(m_FilterMode=1, m_Aniso=8, m_MipBias=0, m_WrapU=2, m_WrapV=1)
        rgba = b"".join(bytes([level, 77, 123, 255]) * pixels
                        for level, pixels in enumerate((32, 8, 2, 1)))
        texture = SimpleNamespace(m_Name="stage_main", m_Width=8, m_Height=4, m_TextureFormat=4,
                                  m_MipCount=4, m_ImageCount=1, m_TextureDimension=2, m_ColorSpace=1,
                                  m_TextureSettings=settings, get_image_data=lambda: rgba)
        return SimpleNamespace(read=lambda: texture, path_id=11, assets_file=object(),
                               type=SimpleNamespace(name="Texture2D"))

    def test_shared_native_texture_retains_one_chain_across_roles(self):
        deadline = time.monotonic() + 5
        source, material = self.source(), object()
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=deadline, preview_stage=True, stats={"textures": 0},
                                tree=lambda _: {"m_SavedProperties": {"m_TexEnvs": [
                                    ("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 11}}),
                                ]}})
        materials = model_viewer._Materials(scene, glb)
        base = materials.texture(source)
        first, second = {"mipBias": -1.25}, {}
        emissive = {"texture": base}
        static = {}
        with patch.object(stage, "_ref", return_value=source):
            stage.collect_main_sampler(scene, materials, material, static, static_opaque=True)
            stage.collect_main_sampler(scene, materials, material, first)
        stage.collect_texture_sampler(materials, source, second, "lightmapSampler")
        stage.collect_texture_sampler(materials, source, emissive, "sampler")
        self.assertTrue(stage.attach_texture_samplers(materials, deadline, priority=stage.MAIN_SAMPLERS))
        self.assertFalse(stage.attach_texture_samplers(materials, deadline, priority=stage.AUXILIARY_SAMPLERS))
        self.assertFalse(stage.attach_texture_samplers(materials, deadline, priority=stage.STATIC_OPAQUE_SAMPLERS))
        expected = {"mipmaps": [1, 2, 3], "filterMode": 1, "anisotropy": 8}
        self.assertEqual(first, {"mipBias": -1.25, "mainSampler": expected})
        self.assertEqual(static, {"mainSampler": expected})
        self.assertEqual(second, {"lightmapSampler": expected})
        self.assertEqual(emissive, {"texture": 0, "sampler": expected})
        self.assertEqual(base, 0)
        self.assertEqual(scene.stats["textures"], 4)
        for level, image in enumerate(glb.doc["images"]):
            view = glb.doc["bufferViews"][image["bufferView"]]
            begin, size = view["byteOffset"], view["byteLength"]
            with Image.open(BytesIO(glb.data[begin:begin + size])) as png:
                self.assertEqual(png.size, (max(1, 8 >> level), max(1, 4 >> level)))
                self.assertEqual(png.getpixel((0, 0)), (level, 77, 123, 255))
        self.assertEqual(glb.doc["samplers"][base]["wrapS"], 33648)
        self.assertEqual(glb.doc["samplers"][base]["wrapT"], 33071)

    def test_partial_append_cannot_consume_baseline_texture_budget(self):
        deadline = time.monotonic() + 5
        source = self.source()
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=deadline, preview_stage=True, stats={"textures": 0})
        materials = model_viewer._Materials(scene, glb)
        materials.texture(source)
        baseline = glb.finish()
        descriptor = {}
        stage.collect_texture_sampler(materials, source, descriptor, "lightmapSampler")

        def fail(levels):
            materials.texture(levels[0])
            raise ValueError("missing authored mip")

        with patch.object(materials, "mip_textures", side_effect=fail):
            self.assertFalse(stage.attach_texture_samplers(materials, deadline, priority=stage.AUXILIARY_SAMPLERS))
        self.assertEqual(glb.finish(), baseline)
        self.assertFalse(descriptor)
        self.assertEqual(materials.textures, {stage._key(source): 0})
        self.assertEqual(materials.pixels, 32)
        self.assertEqual(scene.stats["textures"], 1)

    def test_expired_auxiliary_pass_retains_completed_main_glb(self):
        deadline = time.monotonic() + 5
        main, lightmap = self.source(), self.source()
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=deadline, preview_stage=True, stats={"textures": 0})
        materials = model_viewer._Materials(scene, glb)
        materials.texture(main)
        lightmap_index = materials.texture(lightmap)
        descriptor = {"lightmap": lightmap_index}
        glb.doc["nodes"].append({"extras": {"mvStageMaterial": descriptor}})
        stage.collect_texture_sampler(materials, lightmap, descriptor, "lightmapSampler")
        stage.collect_texture_sampler(materials, main, descriptor, "mainSampler")
        baseline = glb.finish(), dict(scene.stats), [], {}
        clock = [deadline - 1]
        decoder = stage._texture_sampler

        def expires_after_decoding_auxiliary(materials, source):
            sampler = decoder(materials, source)
            if source is lightmap:
                clock[0] = deadline
            return sampler

        with patch.object(time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(stage, "_texture_sampler", side_effect=expires_after_decoding_auxiliary):
            result = model_viewer._finish_stage_samplers(materials, deadline, baseline)

        size = int.from_bytes(result[0][12:16], "little")
        doc = json.loads(result[0][20:20 + size])
        self.assertEqual(doc["nodes"][0]["extras"]["mvStageMaterial"], {
            "lightmap": lightmap_index,
            "mainSampler": {"mipmaps": [2, 3, 4], "filterMode": 1, "anisotropy": 8},
        })
        self.assertEqual(len(doc["textures"]), 5)
        self.assertEqual(result[1], {"textures": 5})

    def test_static_opaque_sampler_uses_only_remaining_texture_budget(self):
        deadline = time.monotonic() + 5
        static, lightmap, main = self.source(), self.source(), self.source()
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=deadline, preview_stage=True, stats={"textures": 0})
        materials = model_viewer._Materials(scene, glb)
        for source in (static, lightmap, main):
            materials.texture(source)
        descriptor, surface = {}, {}
        glb.doc["nodes"].append({"extras": {"stage": descriptor, "surface": surface}})
        stage.collect_texture_sampler(materials, static, surface, "mainSampler", priority=stage.STATIC_OPAQUE_SAMPLERS)
        stage.collect_texture_sampler(materials, lightmap, descriptor, "lightmapSampler")
        stage.collect_texture_sampler(materials, main, descriptor, "mainSampler")
        base = glb.finish(), dict(scene.stats), [], {}
        with patch.object(stage, "MAX_TEXTURE_PIXELS", 118):
            result = model_viewer._finish_stage_samplers(materials, deadline, base)
        size = int.from_bytes(result[0][12:16], "little")
        doc = json.loads(result[0][20:20 + size])
        extras = doc["nodes"][0]["extras"]
        self.assertEqual(len(doc["textures"]), 9)
        self.assertEqual(extras["stage"]["mainSampler"]["mipmaps"], [3, 4, 5])
        self.assertEqual(extras["stage"]["lightmapSampler"]["mipmaps"], [6, 7, 8])
        self.assertEqual(extras["surface"], {})

    def test_stage_block_mips_keep_padded_blocks_and_crop_before_flip(self):
        deadline = time.monotonic() + 5
        source = self.source()
        for format_id, mode, sizes, extent in (
                (32, "pvrtc4", (32, 32, 32, 32), 8),
                (33, "pvrtc4a", (32, 32, 32, 32), 8),
                (34, "etc1", (16, 8, 8, 8), 4)):
            with self.subTest(format=format_id):
                data = bytes(64) + b"".join(bytes([level]) * size for level, size in enumerate(sizes, 1))
                texture = SimpleNamespace(m_Width=16, m_Height=8, m_MipCount=5, m_Name="stage",
                                          m_TextureFormat=format_id, m_TextureSettings=None,
                                          get_image_data=lambda: data)
                with self.assertRaises(ValueError):
                    model_materials._original_mips(source, texture)
                levels = model_materials._original_mips(source, texture, stage=True)
                self.assertEqual([(m.read().m_Width, m.read().m_Height) for m in levels],
                                 [(8, 4), (4, 2), (2, 1), (1, 1)])
                self.assertEqual([m.read().image_data for m in levels],
                                 [bytes([level]) * size for level, size in enumerate(sizes, 1)])

                def block_image(format_name, payload, width, height, limit):
                    self.assertEqual((format_name, payload, width, height, limit),
                                     (mode, bytes([2]) * sizes[1], extent, extent, deadline))
                    return Image.frombytes("RGBA", (extent, extent),
                                           bytes(ch for y in range(extent) for x in range(extent) for ch in (x, y, 0, 100)))

                with patch.object(decode, "_stage_block_image", side_effect=block_image):
                    with decode._android_image(levels[1].read(), deadline, stage=True) as image:
                        self.assertEqual(image.size, (4, 2))
                        self.assertEqual(image.getpixel((3, 0)), (3, 1, 0, 100))
                        self.assertEqual(image.getpixel((0, 1)), (0, 0, 0, 100))


class StageCubemapTests(unittest.TestCase):
    @staticmethod
    def cube(format_id, block_sizes):
        face_bytes = sum(block_sizes)
        payload = b"".join(bytes([1 + 4 * face + mip]) * length
                           for face in range(6) for mip, length in enumerate(block_sizes))
        return SimpleNamespace(m_Width=8, m_Height=8, m_ImageCount=6, m_MipCount=4,
                               m_TextureFormat=format_id, m_TextureDimension=2, m_ColorSpace=1,
                               m_LightmapFormat=0, m_CompleteImageSize=face_bytes,
                               m_StreamData=SimpleNamespace(size=0), get_image_data=Mock(return_value=payload),
                               m_TextureSettings=SimpleNamespace(m_FilterMode=2, m_MipBias=0, m_Aniso=0,
                                                                 m_WrapU=1, m_WrapV=1, m_WrapW=1))

    def test_exact_face_and_mip_order_and_pvrtc_small_levels(self):
        for format_id, name, sizes, extents in ((34, "etc1", [32, 8, 8, 8], [8, 4, 2, 1]),
                                                  (32, "pvrtc4", [32, 32, 32, 32], [8, 8, 8, 8])):
            with self.subTest(format=name):
                recorded = []

                def decode_block(format_name, payload, width, height, deadline):
                    self.assertEqual(format_name, name)
                    level = len(recorded) % 4
                    self.assertEqual(len(payload), sizes[level])
                    self.assertEqual((width, height), (extents[level], extents[level]))
                    self.assertEqual(deadline, 123)
                    recorded.append(payload[0])
                    return Image.new("RGBA", (width, height), (payload[0], 0, 0, 255))

                with patch.object(decode, "_stage_block_image", side_effect=decode_block):
                    raw, width, pixels = stage._cube_pixels(self.cube(format_id, sizes), 1024, 123)
                self.assertEqual((width, pixels), (8, 6 * (64 + 16 + 4 + 1)))
                self.assertEqual(recorded, list(range(1, 25)))
                expected = bytearray()
                for index, value in enumerate(recorded):
                    side = 8 >> (index % 4)
                    expected.extend(bytes([value, 0, 0, 255]) * side ** 2)
                self.assertEqual(raw, expected)

    def test_rejects_invalid_budget_and_incomplete_native_data_before_decode(self):
        raw_cube = self.cube(34, [32, 8, 8, 8])
        with patch.object(decode, "_stage_block_image") as decoder:
            self.assertIsNone(stage._cube_pixels(raw_cube, 400, 123))
            raw_cube.get_image_data.assert_not_called()
            raw_cube.get_image_data.return_value = raw_cube.get_image_data.return_value[:-1]
            self.assertIsNone(stage._cube_pixels(raw_cube, 1024, 123))
            decoder.assert_not_called()

    def test_additive_vertex_alpha_selects_the_original_blend(self):
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=1, tree=lambda _: {
            "m_ShaderKeywords": "_CUBEMAP_MODE_FRAGMENT _PARALLAX_CORRECTED_CUBEMAP_ON "
                                "_CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
            "m_SavedProperties": {
                "m_Colors": [(field, {"r": 0, "g": 0, "b": 0})
                             for field in ("_BoxMin", "_BoxMax", "_CubemapPos")],
                "m_TexEnvs": [("_Cube", {"m_Texture": {}})],
            },
        })
        materials = SimpleNamespace(pixels=0)
        cube = SimpleNamespace(assets_file=object(), path_id=1, type=SimpleNamespace(name="Cubemap"), read=Mock())
        with patch.object(stage, "_ref", return_value=cube), patch.object(stage, "_cube_pixels", return_value=(b"data", 8, 4)):
            result = stage.export_reflection(scene, glb, materials, object(), {})
        self.assertEqual({key: result[key] for key in ("mode", "parallax", "op", "reflectivity", "fresnel")},
                         {"mode": "fragment", "parallax": True, "op": "add", "reflectivity": "vertex", "fresnel": False})
        self.assertEqual(result["bufferView"], 0)
        self.assertEqual(materials.pixels, 4)

    def test_every_reflection_keyword_combination_selects_its_variant(self):
        variant = stage.reflection_variant
        # 12035/1 and 12023/1 bg0007_02_stageA_opa_ref_mt: a fragment cube without parallax correction.
        self.assertEqual(variant("_CUBEMAP_MODE_FRAGMENT _CUBEMAP_BLEND_OP_ALPHA_BLEND _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA "
                                 "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _THIRD_TEX_MODE_OFF".split()),
                         {"mode": "fragment", "parallax": False, "op": "alpha-blend", "reflectivity": "vertex", "fresnel": False})
        # 12035/2 and 12023/2 bg0008_01_stageA_opa_ref_mt: alpha blend by _MainTex alpha.
        self.assertEqual(variant("_CUBEMAP_MODE_FRAGMENT _PARALLAX_CORRECTED_CUBEMAP_ON _CUBEMAP_BLEND_OP_ALPHA_BLEND "
                                 "_CUBEMAP_REFLECTIVITY_MAIN_TEX_ALPHA".split())["reflectivity"], "texture")
        # 11054/3 bg0022_01_floorA_opa_ref_mt: _MainTex alpha times COLOR alpha.
        self.assertEqual(variant("_CUBEMAP_MODE_FRAGMENT _CUBEMAP_BLEND_OP_ALPHA_BLEND "
                                 "_CUBEMAP_REFLECTIVITY_MULTIPLY".split())["reflectivity"], "multiply")
        # 11078/3 bg0024_01_stageA1_opa_emi_ref_mt: per-vertex direction with fresnel.
        self.assertEqual(variant("_CUBEMAP_MODE_VERTEX _PARALLAX_CORRECTED_CUBEMAP_ON _CUBEMAP_BLEND_OP_ALPHA_BLEND "
                                 "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA _FRESNEL_ON".split()),
                         {"mode": "vertex", "parallax": True, "op": "alpha-blend", "reflectivity": "vertex", "fresnel": True})
        # A stale keyword outside AS/Stage's keyword space selects nothing.
        self.assertEqual(variant("_CUBEMAP_MODE_FRAGMENT _CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA "
                                 "_EMISSION _ZWRITEPARAM_ON".split())["op"], "add")
        for keywords in ("_CUBEMAP_MODE_OFF _CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
                         "_CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
                         "_CUBEMAP_MODE_FRAGMENT _CUBEMAP_MODE_VERTEX _CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
                         "_CUBEMAP_MODE_FRAGMENT _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
                         "_CUBEMAP_MODE_FRAGMENT _CUBEMAP_BLEND_OP_ADD"):
            self.assertIsNone(variant(keywords.split()), keywords)

    def test_non_parallax_reflection_needs_no_box(self):
        glb = model_viewer._Glb()
        scene = SimpleNamespace(deadline=1, tree=lambda _: {
            "m_ShaderKeywords": "_CUBEMAP_MODE_FRAGMENT _CUBEMAP_BLEND_OP_ALPHA_BLEND _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA",
            "m_SavedProperties": {"m_Colors": [], "m_TexEnvs": [("_Cube", {"m_Texture": {}})]},
        })
        cube = SimpleNamespace(assets_file=object(), path_id=1, type=SimpleNamespace(name="Cubemap"), read=Mock())
        with patch.object(stage, "_ref", return_value=cube), patch.object(stage, "_cube_pixels", return_value=(b"data", 8, 4)):
            result = stage.export_reflection(scene, glb, SimpleNamespace(pixels=0), object(), {})
        self.assertEqual(result, {"bufferView": 0, "size": 8, "mode": "fragment", "parallax": False,
                                  "op": "alpha-blend", "reflectivity": "vertex", "fresnel": False})

    def test_emissive_third_texture_keeps_its_reflection(self):
        # 10001/3 bg0001_01_stageB1_opa_emi_ref_mt.
        material = SimpleNamespace(
            path_id=12, type=SimpleNamespace(name="Material"),
            assets_file=SimpleNamespace(externals=[SimpleNamespace(path="CAB-fc0511ca63f2d94bbfe211260d08ddd1")]))
        color = dict.fromkeys("rgba", 1)
        tree = {
            "m_Shader": {"m_FileID": 1, "m_PathID": -6509019661097744245},
            "m_ShaderKeywords": "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _CUBEMAP_BLEND_OP_ALPHA_BLEND _CUBEMAP_MODE_FRAGMENT "
                                "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA _FRESNEL_ON _PARALLAX_CORRECTED_CUBEMAP_ON "
                                "_THIRD_TEX_MODE_EMISSIVE",
            "m_SavedProperties": {
                "m_Floats": [("_SrcBlend", 1), ("_DstBlend", 0), ("_ZWrite", 1)],
                "m_Colors": [("_AmbientColor", color), ("_TintColor", color), ("_BlendColor", color)],
                "m_TexEnvs": [("_MainTex", {"m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})],
            },
        }
        descriptor = stage.read_material(SimpleNamespace(tree=lambda _: tree), material, {}, {})
        self.assertEqual((descriptor["reflectionToggle"], descriptor["usesEmissive"]), (True, True))

    @staticmethod
    def stage_material(keywords, floats, queue=-1):
        material = SimpleNamespace(
            path_id=13, type=SimpleNamespace(name="Material"),
            assets_file=SimpleNamespace(externals=[SimpleNamespace(path="CAB-fc0511ca63f2d94bbfe211260d08ddd1")]))
        color = dict.fromkeys("rgba", 1)
        tree = {
            "m_Shader": {"m_FileID": 1, "m_PathID": -6509019661097744245}, "m_ShaderKeywords": keywords,
            "m_CustomRenderQueue": queue,
            "m_SavedProperties": {
                "m_Floats": list(floats.items()),
                "m_Colors": [("_AmbientColor", color), ("_TintColor", color), ("_BlendColor", color)],
                "m_TexEnvs": [("_MainTex", {"m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})],
            },
        }
        return stage.read_material(SimpleNamespace(tree=lambda _: tree), material, {}, {})

    def test_blend_mode_floats_set_the_pass_state(self):
        off = "_CUBEMAP_MODE_OFF _CUBEMAP_BLEND_OP_ALPHA_BLEND _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA _THIRD_TEX_MODE_OFF "
        # 10006/3 bg0004_01_stageB_cut_mt: _BlendMode 1 in the Geometry queue.
        opaque_queue = self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA",
                                           {"_BlendMode": 1, "_SrcBlend": 5, "_DstBlend": 10, "_ZWrite": 0})
        self.assertEqual({key: opaque_queue.get(key) for key in ("blend", "depthWrite", "queue", "alphaSource", "stencil")},
                         {"blend": [5, 10], "depthWrite": False, "queue": 2000, "alphaSource": None, "stencil": None})
        # 10022/3 bg0007_04_plantsA_tra_mt: alpha from _MainTex.a * COLOR.a, queue 3000.
        plants = self.stage_material(off + "_ALPHA_TRANSPARENCY_MULTIPLY",
                                     {"_SrcBlend": 5, "_DstBlend": 10, "_ZWrite": 0}, queue=3000)
        self.assertEqual((plants["queue"], plants["alphaSource"]), (3000, "multiply"))
        # 11009/3 bg0010_01_stageA_add_ref_mt: additive by COLOR.a.
        additive = self.stage_material("_CUBEMAP_MODE_VERTEX _CUBEMAP_BLEND_OP_ADD _CUBEMAP_REFLECTIVITY_VERTEX_ALPHA "
                                       "_THIRD_TEX_MODE_OFF _ALPHA_TRANSPARENCY_VERTEX_ALPHA",
                                       {"_BlendMode": 2, "_SrcBlend": 5, "_DstBlend": 1, "_ZWrite": 0}, queue=3000)
        self.assertEqual((additive["blend"], additive["alphaSource"], additive["reflectionToggle"]), ([5, 1], "vertex", True))
        # 12021/3 bg0025_01_stageC_prj_mt writes stencil reference 2.
        writer = self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA",
                                     {"_StencilComp": 8, "_StencilPassOp": 2, "_StencilRef": 2, "_StencilZFailOp": 0})
        self.assertEqual(writer["stencil"], {"ref": 2, "comp": 8, "pass": 2, "zfail": 0})
        self.assertNotIn("blend", writer)
        # CompareFunction 0 (Disabled) turns the stencil off whatever its operations say.
        disabled = self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA",
                                       {"_StencilComp": 0, "_StencilPassOp": 2, "_StencilRef": 2, "_StencilZFailOp": 2})
        self.assertNotIn("stencil", disabled)
        # Opaque defaults keep the descriptor free of pass-state fields.
        plain = self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _EMISSION _ZWRITEPARAM_ON",
                                    {"_BlendMode": 0, "_SrcBlend": 1, "_DstBlend": 0, "_ZWrite": 1, "_StencilComp": 8})
        self.assertEqual([key for key in ("blend", "depthWrite", "stencil", "alphaSource") if key in plain], [])
        for floats in ({"_SrcBlend": 11}, {"_DstBlend": 9}, {"_ZWrite": 2}, {"_SrcBlend": 1.5},
                       {"_StencilComp": 9}, {"_StencilPassOp": 8}):
            self.assertIsNone(self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA", floats), floats)
        self.assertIsNone(self.stage_material(off + "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _ALPHA_TRANSPARENCY_MULTIPLY", {}))
        self.assertIsNone(self.stage_material(off, {}))

    @staticmethod
    def cutout_material(keywords, floats, queue=-1, colors=None):
        material = SimpleNamespace(
            path_id=14, type=SimpleNamespace(name="Material"),
            assets_file=SimpleNamespace(externals=[SimpleNamespace(path="CAB-ac0988328357841c205babac78d7cf4e")]))
        white = dict.fromkeys("rgba", 1)
        tree = {
            "m_Shader": {"m_FileID": 1, "m_PathID": -6136900368392166873}, "m_ShaderKeywords": keywords,
            "m_CustomRenderQueue": queue,
            "m_SavedProperties": {
                "m_Floats": list(floats.items()),
                "m_Colors": colors if colors is not None else [("_AmbientColor", {**white, "a": 0}), ("_TintColor", white),
                                                               ("_Color", white)],
                "m_TexEnvs": [("_MainTex", {"m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})],
            },
        }
        scene = SimpleNamespace(tree=lambda _: tree)
        return scene, material, stage.read_material(scene, material, {}, {})

    def test_transparent_cutout_always_tests_its_cutoff(self):
        floats = {"_CullMode": 0, "_Cutoff": .5, "_ZTestMode": 4, "_ZWriteParam": 1, "_StencilComp": 8,
                  "_StencilPassOp": 0, "_VERTEX_COLOR": 0, "_SATURATE": 0}
        # 12128/3 bg0038_01_skyA_cut_mt: only the stale _ZWRITEPARAM_ON is saved.
        _, _, sky = self.cutout_material("_ZWRITEPARAM_ON", floats)
        self.assertEqual({key: sky.get(key) for key in ("shader", "cull", "queue", "alphaCutoff", "vertexColor", "depthWrite")},
                         {"shader": "cutout", "cull": 0, "queue": 2450, "alphaCutoff": .5, "vertexColor": False,
                          "depthWrite": None})
        self.assertNotIn("_Color", sky["colors"])
        # 10022/3 bg0007_04_plantsA_cut_mt keeps AS/Stage keywords from a shader swap.
        _, _, plants = self.cutout_material(
            "_ALPHATEST_ON _ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _CUBEMAP_MODE_OFF _VERTEX_COLOR_ON _ZWRITEPARAM_ON", floats)
        self.assertEqual((plants["shader"], plants["vertexColor"]), ("cutout", True))
        # 12026/3 mat_stg_so2026_oth_02 (the moon chair): Cull Back in queue 3000.
        _, _, chair = self.cutout_material("_VERTEX_COLOR_ON", {**floats, "_CullMode": 2}, queue=3000)
        self.assertEqual((chair["cull"], chair["queue"]), (2, 3000))
        # 12030/3 mat_stg_so2030_alb_oth_01: saturate with a stale _VERTEX_COLOR_OFF.
        _, _, torch = self.cutout_material("_SATURATE_ON _VERTEX_COLOR_OFF _VERTEX_COLOR_ON _ZWRITEPARAM_ON", floats)
        self.assertEqual((torch["saturate"], torch["vertexColor"]), (True, True))
        # 10008/3 bg0014_01_grassA_cut_mt: ZWrite Off and _Cutoff 0.4.
        _, _, grass = self.cutout_material("", {**floats, "_ZWriteParam": 0, "_Cutoff": .4, "_ZTestMode": 2})
        self.assertEqual((grass["depthWrite"], grass["depthTest"], grass["alphaCutoff"]), (False, 2, .4))
        # Unset floats read the shader defaults: Cull Off, ZWrite On, ZTest LEqual, _Cutoff 0.5.
        _, _, defaults = self.cutout_material("", {})
        self.assertEqual({key: defaults.get(key) for key in ("cull", "alphaCutoff", "depthWrite", "depthTest", "stencil")},
                         {"cull": 0, "alphaCutoff": .5, "depthWrite": None, "depthTest": None, "stencil": None})
        _, _, stencil = self.cutout_material("", {"_StencilComp": 3, "_StencilRef": 2})
        self.assertEqual(stencil["stencil"], {"ref": 2, "comp": 3, "pass": 0, "zfail": 0})
        # Its particle variants are not stage surfaces.
        for keywords in ("PROCEDURAL_INSTANCING_ON", "SOFTPARTICLES_ON _VERTEX_COLOR_ON"):
            self.assertIsNone(self.cutout_material(keywords, floats)[2], keywords)
        for bad in ({"_Cutoff": 1.5}, {"_CullMode": 3}, {"_ZTestMode": 9}, {"_ZWriteParam": .5}, {"_StencilPassOp": 9}):
            self.assertIsNone(self.cutout_material("", {**floats, **bad})[2], bad)
        self.assertIsNone(self.cutout_material("", floats, colors=[("_TintColor", {"r": 1, "g": 1, "b": 1, "a": 1})])[2])

    def test_transparent_cutout_depth_pass_alpha_tests_without_a_keyword(self):
        scene, material, _ = self.cutout_material("", {})
        renderer = {"m_CastShadows": 1}
        self.assertEqual(stage.camera_depth(scene, material, renderer, supports_cutout=True), {"kind": "cutout"})
        self.assertIsNone(stage.camera_depth(scene, material, renderer, supports_cutout=False))
        scene, material, _ = self.cutout_material("", {}, queue=3000)
        self.assertIsNone(stage.camera_depth(scene, material, renderer, supports_cutout=True))

    def test_coloring_opaque_reads_the_default_white_palette(self):
        def coloring(keywords, floats, palette=0, queue=-1):
            material = SimpleNamespace(
                path_id=15, type=SimpleNamespace(name="Material"),
                assets_file=SimpleNamespace(externals=[SimpleNamespace(path="CAB-a82d81c63f90a9578a472659ba4c195f")]))
            white = dict.fromkeys("rgba", 1)
            tree = {
                "m_Shader": {"m_FileID": 1, "m_PathID": -6110577314968069779}, "m_ShaderKeywords": keywords,
                "m_CustomRenderQueue": queue,
                "m_SavedProperties": {
                    "m_Floats": list(floats.items()),
                    "m_Colors": [("_AmbientColor", {**white, "a": 0}), ("_TintColor", white), ("_Color", white)],
                    "m_TexEnvs": [("_MainTex", {"m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}}),
                                  ("_ColorIdTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 0}}),
                                  ("_PaletteTex", {"m_Texture": {"m_FileID": 0, "m_PathID": palette}})],
                },
            }
            scene = SimpleNamespace(tree=lambda _: tree)
            return scene, material, stage.read_material(scene, material, {}, {})

        # 10008/3, 11008/3, 11044/3 cmn_mat_lit_02 (litC bodies): stale AS/Stage keywords and floats.
        stale = ("_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA _CUBEMAP_BLEND_OP_ALPHA_BLEND _CUBEMAP_MODE_FRAGMENT "
                 "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA _FRESNEL_ON _PARALLAX_CORRECTED_CUBEMAP_ON _THIRD_TEX_MODE_OFF "
                 "_VERTEX_COLOR_ON")
        floats = {"_AUTO_PLAY": 0, "_CullMode": 0, "_Cutoff": .5, "_Shift": 0, "_Speed": 1, "_VERTEX_COLOR": 1}
        scene, material, body = coloring(stale, floats)
        self.assertEqual({key: body.get(key) for key in ("shader", "cull", "queue", "vertexColor", "alphaCutoff")},
                         {"shader": "coloring", "cull": 0, "queue": 2000, "vertexColor": True, "alphaCutoff": None})
        self.assertEqual(stage.camera_depth(scene, material, {"m_CastShadows": 1}, supports_cutout=False), {"kind": "opaque"})
        # The pass fixes blend and depth; stale floats from another shader do not reject it.
        self.assertEqual(coloring("_AUTO_PLAY_ON", {**floats, "_SrcBlend": 5, "_DstBlend": 10, "_ZWrite": 0})[2]["vertexColor"],
                         False)
        self.assertEqual(coloring("", {})[2]["cull"], 0)
        self.assertIsNone(coloring("", floats, palette=77)[2], "an assigned palette is not drawn without its lookup")
        self.assertIsNone(coloring("", {**floats, "_CullMode": 4})[2])

    def test_quality_ownership_uses_only_typed_primary_model_ambient(self):
        def node(kind, path):
            return SimpleNamespace(type=SimpleNamespace(name=kind), assets_file=object(), path_id=path)

        root = node("GameObject", 1)
        model, primary, secondary = (node("MonoBehaviour", value) for value in (2, 3, 4))
        controlled, uncontrolled = (node("Material", value) for value in (5, 6))
        model_tree = {"m_GameObject": root, "ambient": primary, "ambients": [secondary]}
        trees = {obj.path_id: data for obj, data in (
            (root, {"m_Component": [{"component": model}, {"component": primary}]}),
            (primary, {"materials": [controlled]}),
            (secondary, {"materials": [uncontrolled]}),
        )}
        identities = {model.path_id: stage._MODEL_SCRIPT, primary.path_id: stage._AMBIENT_SCRIPT,
                      secondary.path_id: stage._AMBIENT_SCRIPT}
        scene = SimpleNamespace(tree=lambda obj: trees[obj.path_id])
        with patch.object(stage, "_ref", side_effect=lambda _, ptr: ptr), \
                patch.object(stage, "_object_path", return_value=("Model",)), \
                patch.object(stage, "_component_identity", side_effect=lambda _, obj, __: identities.get(obj.path_id)):
            self.assertEqual(stage.cubemap_model_ownership(scene, model, model_tree), (True, {stage._key(controlled)}))
            self.assertEqual(stage.cubemap_model_ownership(scene, model, {**model_tree, "ambient": None}), (True, None))
            scene.native_stage_effect = True
            self.assertEqual(stage.cubemap_model_ownership(scene, model, model_tree), (False, None))

class StageEmissiveOwnershipTests(unittest.TestCase):
    def test_model_binding_uses_only_the_unique_root_receiver(self):
        stage_file, materials_file = object(), object()

        def node(kind, identifier, serialized=stage_file):
            return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=identifier, assets_file=serialized)

        def ref(identifier, file_id=0):
            return {"m_FileID": file_id, "m_PathID": identifier}

        root, child = node("GameObject", 1), node("GameObject", 2)
        model, receiver, child_receiver = (node("MonoBehaviour", value) for value in (10, 11, 12))
        extra_root_receiver = node("MonoBehaviour", 13)
        model_script, receiver_script = (node("MonoScript", value, materials_file) for value in (20, 21))
        material, child_material = (node("Material", value, materials_file) for value in (30, 31))
        objects = {stage._key(obj): obj for obj in (root, child, model, receiver, child_receiver, extra_root_receiver,
                                                    model_script, receiver_script, material, child_material)}
        root_data = {"m_Component": [{"component": ref(10)}, {"component": ref(11)}]}
        model_data = {"m_GameObject": ref(1), "m_Script": ref(20, 1), "emissives": [ref(11), ref(12)]}
        receiver_data = {"m_GameObject": ref(1), "m_Script": ref(21, 1), "materials": [ref(30, 1)]}
        child_data = {**receiver_data, "m_GameObject": ref(2), "materials": [ref(31, 1)]}
        script_fields = ("m_ClassName", "m_Namespace", "m_AssemblyName")
        trees = {stage._key(obj): data for obj, data in (
            (root, root_data), (model, model_data), (receiver, receiver_data), (child_receiver, child_data),
            (extra_root_receiver, receiver_data), (model_script, dict(zip(script_fields, stage._MODEL_SCRIPT))),
            (receiver_script, dict(zip(script_fields, stage._EMISSIVE_SCRIPT))),
        )}
        scene = SimpleNamespace(tree=lambda obj: trees[stage._key(obj)])

        def resolve(owner, pointer):
            if pointer is None:
                return None
            target = owner.assets_file if pointer["m_FileID"] == 0 else materials_file
            return objects.get((id(target), pointer["m_PathID"]))

        with patch.object(stage, "_ref", side_effect=resolve), patch.object(stage, "_object_path", return_value=("Model",)):
            self.assertEqual(stage.emissive_materials(scene, model, model_data), {stage._key(material)})
            self.assertFalse(stage.emissive_materials(scene, model, {**model_data, "emissives": [ref(12)]}))
            root_data["m_Component"].append({"component": ref(13)})
            self.assertFalse(stage.emissive_materials(scene, model, model_data))


class StagePassQueueTests(unittest.TestCase):
    def test_only_kinds_with_a_queued_pass_state_keep_the_queue(self):
        # The JS pass state draws queue > 2500 in Unity's transparent order; a kind that
        # lost its queue would draw a queue-3000 _BlendMode floor opaque.
        for kind, queue in (("stage", 3000), ("stage", 2000), ("cutout", 2450), ("coloring", 2000)):
            descriptor = {"shader": kind, "queue": queue}
            self.assertEqual(stage.pass_queue(descriptor), queue)
            self.assertEqual(descriptor, {"shader": kind, "queue": queue}, kind)
        for kind in ("general", "blend", "solid"):
            descriptor = {"shader": kind, "queue": 2000}
            self.assertEqual(stage.pass_queue(descriptor), 2000, "the opaque sort still reads it")
            self.assertEqual(descriptor, {"shader": kind}, kind)


class StageSkinnedMotionTests(unittest.TestCase):
    def test_skinned_stage_motion_draws_general_and_cutout_materials(self):
        # A TransparentCutout skinned renderer under a stage-motion binding is posed by its clip
        # like an AS/General/Opaque one; the other kinds stay on their own paths.
        floats = {"_CullMode": 0, "_Cutoff": .5, "_ZTestMode": 4, "_ZWriteParam": 1, "_StencilComp": 8,
                  "_StencilPassOp": 0, "_VERTEX_COLOR": 0, "_SATURATE": 0}
        _, _, cutout = StageCubemapTests.cutout_material("", floats)
        self.assertEqual(cutout["shader"], "cutout")
        self.assertEqual(stage.SKINNED_MOTION_KINDS, {"general", cutout["shader"]})


class ActualStageFloorTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_10001, SIFAS_TEST_STAGE_12035_1, SIFAS_TEST_STAGE_12035_2,
    SIFAS_TEST_STAGE_EFFECT_12026 and SIFAS_TEST_STAGE_EFFECT_10008 to the original Android bundles
    (stage-e274af832d, stage-048468c62c, stage-d7eb918585, stage_effect-65e5b9311b, stage_effect-108cc2d4fe),
    and SIFAS_TEST_STAGE_10022 to the original Android 10022/3 (asset 1002203) stage bundle."""

    def descriptors(self, variable, effect=False):
        import os
        import struct
        from pathlib import Path
        raw = os.environ.get(variable)
        if not raw or not Path(raw).is_file():
            self.skipTest(f"Set {variable} to the original bundle")
        prepared = model_viewer.prepare([raw], face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_native_stage_effect": effect})
        payload = model_viewer.get_model(prepared["id"])
        size = struct.unpack_from("<I", payload, 12)[0]
        doc = json.loads(payload[20:20 + size])
        result = {}
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                name = doc["materials"][primitive["material"]].get("name")
                result.setdefault(name, []).append(primitive.get("extras", {}))
        return result

    def test_10001_emissive_floors_keep_their_fresnel_reflection(self):
        found = self.descriptors("SIFAS_TEST_STAGE_10001")
        for index in range(1, 5):
            extras, = found[f"bg0001_01_stageB{index}_opa_emi_ref_mt"]
            descriptor = extras["mvStageMaterial"]
            self.assertEqual(descriptor["shader"], "stage")
            self.assertIn("lightmap", descriptor)
            self.assertEqual({key: descriptor["reflection"][key] for key in ("mode", "parallax", "op", "reflectivity", "fresnel")},
                             {"mode": "fragment", "parallax": True, "op": "alpha-blend", "reflectivity": "vertex", "fresnel": True})
            self.assertEqual(descriptor["emissive"]["intensity"], 1)
        plain, = found["bg0001_01_stageB_opa_ref_mt"]
        self.assertFalse(plain["mvStageMaterial"]["reflection"]["fresnel"])
        self.assertIn("emissive", plain["mvStageMaterial"])

    def test_12035_position_1_and_2_floor_reflections(self):
        first, = self.descriptors("SIFAS_TEST_STAGE_12035_1")["bg0007_02_stageA_opa_ref_mt"]
        reflection = first["mvStageMaterial"]["reflection"]
        self.assertEqual((reflection["mode"], reflection["parallax"], reflection["reflectivity"]), ("fragment", False, "vertex"))
        self.assertNotIn("boxMin", reflection)
        second, = self.descriptors("SIFAS_TEST_STAGE_12035_2")["bg0008_01_stageA_opa_ref_mt"]
        reflection = second["mvStageMaterial"]["reflection"]
        self.assertEqual((reflection["mode"], reflection["parallax"], reflection["op"], reflection["reflectivity"]),
                         ("fragment", True, "alpha-blend", "texture"))

    def test_10022_queues_survive_the_export_for_stage_and_cutout_only(self):
        found = self.descriptors("SIFAS_TEST_STAGE_10022")
        meta = lambda name: found[name][0]["mvStageMaterial"]
        # bg0007_04_plantsA_tra_mt: AS/Stage with _BlendMode transparent, queue 3000 (SrcAlpha OneMinusSrcAlpha).
        plants = meta("bg0007_04_plantsA_tra_mt")
        self.assertEqual((plants["shader"], plants["queue"], plants["blend"]), ("stage", 3000, [5, 10]))
        self.assertNotIn("opaqueSort", plants, "queue 3000 is sorted back to front, not in the opaque rule")
        floor = meta("bg0007_04_stageA_opa_mt")
        self.assertEqual((floor["shader"], floor["queue"], floor["opaqueSort"]["queue"]), ("stage", 2000, 2000))
        cutout = meta("bg0007_04_plantsA_cut_mt")
        self.assertEqual((cutout["shader"], cutout["queue"], cutout["opaqueSort"]["queue"]), ("cutout", 2450, 2450))
        solid = meta("bg0007_02_out_opa_mt")
        self.assertEqual(solid["shader"], "solid")
        self.assertNotIn("queue", solid)
        self.assertEqual(solid["opaqueSort"]["queue"], 2000)

    def test_12026_moon_chair_is_a_cutout_lit_by_its_prop(self):
        chair, = self.descriptors("SIFAS_TEST_STAGE_EFFECT_12026", effect=True)["mat_stg_so2026_oth_02"]
        self.assertEqual({key: chair["mvStageMaterial"].get(key) for key in ("shader", "cull", "queue", "alphaCutoff", "vertexColor")},
                         {"shader": "cutout", "cull": 2, "queue": 3000, "alphaCutoff": .5, "vertexColor": True})
        self.assertTrue(chair["mvPropLight"]["ambient"])

    def test_10008_light_bodies_use_the_coloring_kind(self):
        bodies = self.descriptors("SIFAS_TEST_STAGE_EFFECT_10008", effect=True)["cmn_mat_lit_02"]
        self.assertEqual(len(bodies), 18)
        for extras in bodies:
            self.assertEqual({key: extras["mvStageMaterial"].get(key) for key in ("shader", "cull", "vertexColor")},
                             {"shader": "coloring", "cull": 0, "vertexColor": True})
            self.assertEqual(extras["mvStageCameraDepth"], {"kind": "opaque"})
