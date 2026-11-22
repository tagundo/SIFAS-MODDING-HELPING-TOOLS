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


class StageDisplayMaterialTests(unittest.TestCase):
    def test_only_exact_opaque_stencil_writers_add_authored_vertex_color(self):
        original = SimpleNamespace(type=SimpleNamespace(name="Material"))
        floats = {"_StencilComp": 8, "_StencilRef": 2, "_StencilPassOp": 2,
                  "_StencilZFailOp": 0, "_VERTEX_COLOR": 1}
        tree = {"m_ShaderKeywords": "_VERTEX_COLOR_ON", "m_CustomRenderQueue": -1,
                "m_SavedProperties": {"m_Floats": floats.items()}}
        scene = SimpleNamespace(tree=lambda _: tree)
        with patch.object(displays, "_shader_matches", return_value=True):
            variant = displays._material(scene, None, original, False)
            self.assertTrue(variant["vertexColor"])
            self.assertEqual((variant["queue"], variant["stencil"]), (2000, 2))
            self.assertIsNone(displays._material(scene, None, original, True))
            floats["_StencilPassOp"] = 0
            self.assertIsNone(displays._material(scene, None, original, False))
            floats.update(_StencilPassOp=2, _VERTEX_COLOR=0)
            tree["m_ShaderKeywords"] = ""
            fallback = displays._material(scene, None, original, False)
            self.assertNotIn("vertexColor", fallback)
            self.assertEqual({k: v for k, v in variant.items() if k != "vertexColor"}, fallback)


class StageOpaqueMaterialTests(unittest.TestCase):
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
        with patch.object(stage, "_ref", return_value=source):
            stage.collect_main_sampler(scene, materials, material, first)
        stage.collect_texture_sampler(materials, source, second, "lightmapSampler")
        stage.collect_texture_sampler(materials, source, emissive, "sampler")
        self.assertTrue(stage.attach_texture_samplers(materials, deadline, main=True))
        self.assertFalse(stage.attach_texture_samplers(materials, deadline, main=False))
        expected = {"mipmaps": [1, 2, 3], "filterMode": 1, "anisotropy": 8}
        self.assertEqual(first, {"mipBias": -1.25, "mainSampler": expected})
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
            self.assertFalse(stage.attach_texture_samplers(materials, deadline, main=False))
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

    def test_stage_pvrtc_levels_keep_padded_blocks_and_crop_before_flip(self):
        deadline = time.monotonic() + 5
        source = self.source()
        for format_id, mode in ((32, "pvrtc4"), (33, "pvrtc4a")):
            with self.subTest(format=format_id):
                data = bytes(64) + b"".join(bytes([level]) * 32 for level in range(1, 5))
                texture = SimpleNamespace(m_Width=16, m_Height=8, m_MipCount=5, m_Name="stage",
                                          m_TextureFormat=format_id, m_TextureSettings=None,
                                          get_image_data=lambda: data)
                with self.assertRaises(ValueError):
                    model_materials._original_mips(source, texture)
                levels = model_materials._original_mips(source, texture, stage=True)
                self.assertEqual([(m.read().m_Width, m.read().m_Height) for m in levels],
                                 [(8, 4), (4, 2), (2, 1), (1, 1)])
                self.assertEqual([m.read().image_data for m in levels],
                                 [bytes([level]) * 32 for level in range(1, 5)])

                def block_image(format_name, payload, width, height, limit):
                    self.assertEqual((format_name, payload, width, height, limit),
                                     (mode, bytes([2]) * 32, 8, 8, deadline))
                    return Image.frombytes("RGBA", (8, 8),
                                           bytes(ch for y in range(8) for x in range(8) for ch in (x, y, 0, 100)))

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
        self.assertEqual(result["blend"], "add-vertex-alpha")
        self.assertEqual(result["bufferView"], 0)
        self.assertEqual(materials.pixels, 4)

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
