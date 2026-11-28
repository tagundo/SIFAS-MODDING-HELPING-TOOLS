"""AS/Blend/Opaque, the 10120 sky dome's shader (also so0012, so1017, so1022 and so1044)."""
import io
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from webtools.core import model_viewer, mv_studio_shader_identity as identity
from webtools.core import mv_studio_stage_materials as stage

_BLEND_CAB = "CAB-f8a6d724e5bbefa191ed2e1f27102738"
_BLEND_ID = -3111404110691668338


def _blend_material(floats=None, colors=None, envs=None, queue=-1):
    material = SimpleNamespace(path_id=7, type=SimpleNamespace(name="Material"),
                               assets_file=SimpleNamespace(externals=[SimpleNamespace(path="archive:/" + _BLEND_CAB, name=_BLEND_CAB)]))
    # The 10120 material keeps stale Standard-shader values (_SrcBlend, _DstBlend 0, _ZWrite) and
    # AS/General/Transparent ones (_BlendSrc 5, _BlendDst 10) that AS/Blend/Opaque never reads.
    saved = {"_BlendDst": 10., "_BlendSrc": 5., "_BlendRate": 0., "_CullMode": 2., "_DstBlend": 10., "_SrcBlend": 5.,
             "_ZWrite": 0., "_StencilComp": 8., "_StencilPassOp": 0., "_StencilRef": 2., "_StencilZFailOp": 0.}
    saved.update(floats or {})
    color = {"_AmbientColor": {"r": 1., "g": 1., "b": 1., "a": 0.}, "_TintColor": dict.fromkeys("rgba", 1.)}
    color.update(colors or {})
    texture = {"m_Texture": {"m_FileID": 0, "m_PathID": 0}, "m_Scale": {"x": 1., "y": 1.}, "m_Offset": {"x": 0., "y": 0.}}
    maps = {"_MainTexA": dict(texture), "_MainTexB": dict(texture)}
    maps.update(envs or {})
    tree = {"m_Shader": {"m_FileID": 1, "m_PathID": _BLEND_ID}, "m_ShaderKeywords": "", "m_CustomRenderQueue": queue,
            "m_SavedProperties": {"m_Floats": [(k, v) for k, v in saved.items() if v is not None],
                                  "m_Colors": [(k, v) for k, v in color.items() if v is not None],
                                  "m_TexEnvs": [(k, v) for k, v in maps.items() if v is not None]}}
    return material, SimpleNamespace(tree=lambda _: tree), tree


class BlendMaterialTests(unittest.TestCase):
    def test_reads_both_maps_rate_and_the_compiled_opaque_state(self):
        material, scene, _ = _blend_material(envs={"_MainTexB": {
            "m_Texture": {"m_FileID": 0, "m_PathID": 0}, "m_Scale": {"x": 2., "y": .5}, "m_Offset": {"x": .25, "y": .125}}},
            floats={"_BlendRate": .25})
        meta = stage.read_material(scene, material, {}, {})
        self.assertEqual(meta["shader"], "blend")
        self.assertEqual(meta["blendRate"], .25)
        self.assertEqual(meta["uvTransform"], [1., 1., 0., 0.])
        # Unity (u * 2 + .25, v * .5 + .125) in glTF's flipped V.
        self.assertEqual(meta["blendUVTransform"], [2., .5, .25, 1 - .5 - .125])
        self.assertIs(meta["vertexColor"], True, "the only program reads COLOR without a keyword")
        self.assertEqual(meta["cull"], 2.)
        self.assertEqual(meta["colors"], {"_AmbientColor": [1., 1., 1., 0.], "_TintColor": [1., 1., 1., 1.]})

    def test_unsaved_properties_read_the_shader_defaults(self):
        material, scene, _ = _blend_material(floats={"_BlendRate": None}, colors={"_AmbientColor": None},
                                             envs={"_MainTexB": None}, queue=2001)
        meta = stage.read_material(scene, material, {}, {})
        self.assertEqual(meta["blendRate"], 0.)
        self.assertEqual(meta["colors"]["_AmbientColor"], [1., 1., 1., 0.])
        self.assertEqual(meta["blendUVTransform"], [1., 1., 0., 0.])

    def test_rejects_states_the_preview_does_not_draw(self):
        for change in ({"_StencilPassOp": 2.}, {"_StencilComp": 3.}, {"_CullMode": 3.}, {"_BlendRate": float("nan")}):
            material, scene, _ = _blend_material(floats=change)
            self.assertIsNone(stage.read_material(scene, material, {}, {}), change)
        material, scene, _ = _blend_material(envs={"_MainTexA": {"m_Scale": {"x": float("inf"), "y": 1.}}})
        self.assertIsNone(stage.read_material(scene, material, {}, {}))

    def test_blend_maps_embed_each_set_map_and_leave_an_unset_one_white(self):
        # so1044's dome leaves _MainTexB unset (m_PathID 0): Unity binds its "white" default.
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        material, scene, tree = _blend_material(envs={"_MainTexA": {"m_Texture": {"m_FileID": 0, "m_PathID": 41}}})
        materials = SimpleNamespace(scene=scene, texture=lambda value: 5 if value is texture else None)
        with patch.object(stage, "_ref", return_value=texture) as ref, \
                patch.object(stage, "collect_texture_sampler") as sampler:
            descriptor = {}
            self.assertTrue(stage.export_blend_maps(materials, material, descriptor))
            self.assertEqual(descriptor, {"mainTexture": 5, "blendTexture": None})
            ref.assert_called_once_with(material, {"m_FileID": 0, "m_PathID": 41})
            self.assertEqual([call.args[3] for call in sampler.call_args_list], ["mainSampler"])
            tree["m_SavedProperties"]["m_TexEnvs"] = [("_MainTexA", {"m_Texture": {"m_FileID": 0, "m_PathID": 0}})]
            descriptor = {}
            self.assertTrue(stage.export_blend_maps(materials, material, descriptor), "both maps unset")
            self.assertEqual(descriptor, {"mainTexture": None, "blendTexture": None})
            # A set reference that is not a Texture2D is not drawn.
            tree["m_SavedProperties"]["m_TexEnvs"] = [("_MainTexB", {"m_Texture": {"m_FileID": 0, "m_PathID": 9}})]
            ref.return_value = SimpleNamespace(type=SimpleNamespace(name="Cubemap"))
            self.assertFalse(stage.export_blend_maps(materials, material, {}))

    @patch.object(model_viewer, "_ref", return_value=None)  # The stage preview loads no shader bundle.
    def test_shader_identity_tint_default_and_camera_depth(self, _):
        material, scene, tree = _blend_material()
        self.assertEqual(identity.name(material, tree), "AS/Blend/Opaque")
        self.assertTrue(model_viewer._as_blend_material(material, tree))
        self.assertEqual(model_viewer._as_tint_default(scene, material, tree), dict.fromkeys("rgba", 1.))
        # Its second pass is UsePass "Hidden/AS/Depth/DEPTH", as AS/General/Opaque's.
        self.assertEqual(stage.camera_depth(scene, material, {"m_CastShadows": 0}, supports_cutout=False), {"kind": "opaque"})
        material.assets_file.externals[0] = SimpleNamespace(path="archive:/CAB-unverified", name="CAB-unverified")
        self.assertIsNone(stage.read_material(scene, material, {}, {}))
        self.assertFalse(model_viewer._as_blend_material(material, tree))


def _glb(data):
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + length])
    binary = data[20 + length + 8:]
    return doc, binary


def _accessor(doc, binary, index):
    accessor = doc["accessors"][index]
    view = doc["bufferViews"][accessor["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    dtype = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[accessor["componentType"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return np.frombuffer(binary, dtype=dtype, count=accessor["count"] * width, offset=start).reshape(-1, width)


def _primitives(doc, material_name):
    return [primitive for mesh in doc["meshes"] for primitive in mesh["primitives"]
            if doc["materials"][primitive["material"]]["name"] == material_name]


class ActualSkyTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_10120 to the original Android 10120 (asset 1012003) stage_effect bundle."""

    @staticmethod
    def bundle(variable):
        raw = os.environ.get(variable)
        if not raw or not Path(raw).is_file():
            raise unittest.SkipTest(f"Set {variable} to the original 10120 bundle")
        return Path(raw)

    @staticmethod
    def export(path, bindings=(), effect=False):
        prepared = model_viewer.prepare([str(path)], rigged=False, face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
            "_mv_stage_motion_bindings": bindings, "_mv_performer": False, "_mv_native_stage_effect": effect})
        return _glb(model_viewer.get_model(prepared["id"]))

    def test_dome_exports_both_exact_maps_and_its_color(self):
        from PIL import Image, ImageChops
        import UnityPy
        path = self.bundle("SIFAS_TEST_STAGE_EFFECT_10120")
        doc, binary = self.export(path)
        primitive, = _primitives(doc, "mat_stg_so0120_opa_01")
        meta = primitive["extras"]["mvStageMaterial"]
        self.assertEqual((meta["shader"], meta["blendRate"], meta["cull"], meta["vertexColor"]), ("blend", 0., 2., True))
        self.assertEqual((meta["uvTransform"], meta["blendUVTransform"]), ([1., 1., 0., 0.], [1., 1., 0., 0.]))
        self.assertEqual(meta["mainSampler"]["mipmaps"], [], "_MainTexA has one level")
        self.assertEqual(len(meta["blendSampler"]["mipmaps"]), 9, "_MainTexB keeps its nine authored levels")
        material = doc["materials"][primitive["material"]]
        self.assertEqual(material["pbrMetallicRoughness"]["baseColorTexture"]["index"], meta["mainTexture"])
        self.assertIn("KHR_materials_unlit", material["extensions"])
        color = _accessor(doc, binary, primitive["attributes"]["_STAGE_COLOR"])
        self.assertEqual(color.shape, (92, 4))
        self.assertTrue((color == np.array([1, 1, 1, 0], dtype=np.float32)).all(), "the authored COLOR (1, 1, 1, 0)")
        sources = {texture.m_Name: texture.image.convert("RGBA") for texture in
                   (obj.read() for obj in UnityPy.load(str(path)).objects if obj.type.name == "Texture2D")
                   if texture.m_Name in ("tex_stg_so0120_01", "tex_stg_so0120_02")}
        for index, name in ((meta["mainTexture"], "tex_stg_so0120_01"), (meta["blendTexture"], "tex_stg_so0120_02")):
            image = doc["images"][doc["textures"][index]["source"]]
            view = doc["bufferViews"][image["bufferView"]]
            embedded = Image.open(io.BytesIO(binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]))
            self.assertEqual((image["name"], embedded.size), (name, (512, 512)))
            self.assertIsNone(ImageChops.difference(embedded.convert("RGBA"), sources[name]).getbbox(), "no resampling")


if __name__ == "__main__":
    unittest.main()
