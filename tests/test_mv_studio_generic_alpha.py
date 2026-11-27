"""The generic glTF fallback never draws an AS/* material whose pass blends with OneMinusSrcAlpha as opaque."""
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_shader_identity as identity


def _material(cab, path_id, floats=(), keywords=""):
    material = SimpleNamespace(type=SimpleNamespace(name="Material"), path_id=5, assets_file=SimpleNamespace(
        externals=[SimpleNamespace(path=f"archive:/CAB-{cab[4:]}", name=f"archive:/CAB-{cab[4:]}")]))
    tree = {"m_Name": "mat_test_alb_01", "m_Shader": {"m_FileID": 1, "m_PathID": path_id}, "m_ShaderKeywords": keywords,
            "m_SavedProperties": {"m_Floats": list(floats), "m_Colors": [], "m_TexEnvs": []}}
    return material, tree


_TRANSPARENT = ("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267)
_OPAQUE = ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367)
_SMOKE = ("cab-c559ebedb55c9abf2ff34a672d5d7a6d", -5163972902431082470)


class AlphaBlendedTests(unittest.TestCase):
    def blended(self, shader, floats=()):
        material, tree = _material(*shader, floats)
        with patch.object(viewer, "_ref", return_value=None):
            return identity.alpha_blended(material, tree)

    def test_property_bound_destination(self):
        self.assertTrue(self.blended(_TRANSPARENT, [("_BlendDst", 10.)]))
        self.assertFalse(self.blended(_TRANSPARENT, [("_BlendDst", 1.)]))
        self.assertFalse(self.blended(_TRANSPARENT), "the ShaderLab default _BlendDst is One")

    def test_fixed_destination_and_unbound_float(self):
        self.assertTrue(self.blended(_SMOKE))
        # AS/General/Opaque binds no blend float: a stale _BlendDst changes nothing.
        self.assertFalse(self.blended(_OPAQUE, [("_BlendDst", 10.)]))
        self.assertFalse(self.blended(("cab-00000000000000000000000000000000", 3), [("_BlendDst", 10.)]))

    def test_loaded_shader_pass_state(self):
        material, tree = _material(*_TRANSPARENT, [("_BlendDst", 10.)])

        def shader(name, destination):
            form = {"m_Name": name, "m_SubShaders": [{"m_Passes": [{"m_State": {"rtBlend0": {"destBlend": destination}}}]}]}
            return SimpleNamespace(type=SimpleNamespace(name="Shader"), path_id=9, assets_file=SimpleNamespace(),
                                   read_typetree=lambda: {"m_ParsedForm": form})

        with patch.object(viewer, "_ref", return_value=shader("AS/Custom/Transparent", {"name": "_BlendDst", "val": 0.})):
            self.assertTrue(identity.alpha_blended(material, tree))
        with patch.object(viewer, "_ref", return_value=shader("AS/Custom/Transparent", {"name": "<noninit>", "val": 1.})):
            self.assertFalse(identity.alpha_blended(material, tree))
        with patch.object(viewer, "_ref", return_value=shader("Unlit/Transparent", {"name": "<noninit>", "val": 10.})):
            self.assertFalse(identity.alpha_blended(material, tree), "only AS/* shaders")


class GenericMaterialTests(unittest.TestCase):
    def material(self, floats):
        material, tree = _material(*_TRANSPARENT, floats, "_ALPHAPREMULTIPLY_ON" if not floats else "")
        scene = SimpleNamespace(tree=lambda _: tree, stats={"materials": 0}, warn=lambda *args: None)
        glb = SimpleNamespace(doc={"materials": []})
        with patch.object(viewer, "_ref", return_value=None):
            index = viewer._Materials(scene, glb).material(material)
        return glb.doc["materials"][index]

    def test_alpha_blended_transparent_material_is_blended(self):
        self.assertEqual(self.material([("_BlendSrc", 5.), ("_BlendDst", 10.)])["alphaMode"], "BLEND")
        self.assertNotIn("alphaMode", self.material([("_BlendSrc", 5.), ("_BlendDst", 1.)]))


class RealGenericAlphaTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_11030 to the original Android stage_effect bundle."""

    def test_11030_unbound_alpha_light_model_is_blended(self):
        raw = os.environ.get("SIFAS_TEST_STAGE_EFFECT_11030")
        if not raw or not Path(raw).is_file():
            self.skipTest("Set SIFAS_TEST_STAGE_EFFECT_11030 to the original stage_effect bundle")
        prepared = viewer.prepare([raw], face_context={"enabled": False, "allow_download": False, "_mv_stage": True})
        import json
        import struct
        payload = viewer.get_model(prepared["id"])
        doc = json.loads(payload[20:20 + struct.unpack_from("<I", payload, 12)[0]])
        modes = {material.get("name"): material.get("alphaMode", "OPAQUE") for material in doc["materials"]}
        self.assertEqual(modes["mat_stg_so1030_alb_01"], "BLEND")


if __name__ == "__main__":
    unittest.main()
