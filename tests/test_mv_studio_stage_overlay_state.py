"""The native stage transparent pass reads AS/General/Transparent's whole property-bound state."""
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_stage_overlay as overlay

_SHARED = ("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267)


def _material(floats, keywords="_VERTEX_COLOR_ON", queue=-1):
    material = SimpleNamespace(type=SimpleNamespace(name="Material"), assets_file=SimpleNamespace(
        externals=[SimpleNamespace(path="archive:/CAB-" + _SHARED[0][4:])]))
    tree = {"m_Shader": {"m_FileID": 1, "m_PathID": _SHARED[1]}, "m_ShaderKeywords": keywords,
            "m_CustomRenderQueue": queue, "m_SavedProperties": {
                "m_Floats": list(floats.items()), "m_Colors": [("_TintColor", {"r": 1, "g": .5, "b": .25, "a": .75})],
                "m_TexEnvs": [("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 0},
                                            "m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}})]}}
    return material, SimpleNamespace(tree=lambda _: tree)


def _read(floats, keywords="_VERTEX_COLOR_ON", **options):
    material, scene = _material(floats, keywords)
    with patch.object(viewer, "_ref", return_value=None):
        return overlay.read_material(scene, material, **options)


class FullStateTests(unittest.TestCase):
    def test_alpha_blend_without_stencil(self):
        # 12026 mat_stg_so2026_oth_03 / mat_ove_gen_alb_01: Blend SrcAlpha OneMinusSrcAlpha, Comp Always.
        floats = {"_BlendSrc": 5, "_BlendDst": 10, "_StencilComp": 8, "_ZTestMode": 4, "_CullMode": 2}
        self.assertIsNone(_read(floats, world=True))
        fields = _read(floats, world=True, full=True)
        self.assertEqual((fields["blend"], fields["zTest"], fields["stencil"], fields["cull"]),
                         ([5, 10], 4, [8, 2, 0, 0], 2))
        self.assertTrue(fields["alphaBlend"] and fields["depthTest"])
        self.assertNotIn("stencilRef", fields)
        self.assertEqual(_read(floats, full=True)["blend"], [5, 10])  # the overlay scope too

    def test_ztest_always_and_depth_write_in_world(self):
        floats = {"_BlendDst": 10, "_ZTestMode": 8, "_ZWriteParam": 1}
        fields = _read(floats, "_VERTEX_COLOR_OFF _VERTEX_COLOR_ON _ZWRITEPARAM_ON", world=True, full=True)
        self.assertEqual((fields["zTest"], fields["depthWrite"], fields["alphaBlend"]), (8, True, True))
        self.assertNotIn("depthTest", fields)

    def test_saturate_program(self):
        fields = _read({}, "_SATURATE_ON _VERTEX_COLOR_ON", full=True)
        self.assertEqual((fields["saturate"], fields["vertexColor"], fields["blend"]), (True, True, [5, 1]))
        self.assertIsNone(_read({}, "_SATURATE_ON _VERTEX_COLOR_ON"))
        self.assertNotIn("saturate", _read({}, full=True))

    def test_order_independent_blends_are_not_sorted(self):
        for blend in ((5, 1), (1, 1), (0, 1), (2, 0), (0, 3)):
            fields = _read({"_BlendSrc": blend[0], "_BlendDst": blend[1]}, full=True)
            self.assertNotIn("alphaBlend", fields, blend)
        for blend in ((5, 10), (1, 10), (4, 1), (2, 1)):
            self.assertTrue(_read({"_BlendSrc": blend[0], "_BlendDst": blend[1]}, full=True)["alphaBlend"], blend)

    def test_stencil_masks_and_writes(self):
        fields = _read({"_BlendDst": 10, "_StencilComp": 3, "_StencilRef": 2}, world=True, full=True)
        self.assertEqual((fields["stencil"], fields["stencilRef"]), ([3, 2, 0, 0], 2))
        fields = _read({"_StencilComp": 8, "_StencilRef": 4, "_StencilPassOp": 2}, full=True)
        self.assertEqual(fields["stencil"], [8, 4, 2, 0])
        self.assertNotIn("stencilRef", fields)

    def test_invalid_state_floats_and_particle_programs_are_refused(self):
        for floats in ({"_BlendDst": 11}, {"_ZTestMode": 9}, {"_StencilRef": 256}, {"_StencilPassOp": 2.5},
                       {"_CullMode": 3}, {"_ZWriteParam": float("nan")}):
            self.assertIsNone(_read(floats, full=True), floats)
        for keywords in ("SOFTPARTICLES_ON", "PROCEDURAL_INSTANCING_ON _VERTEX_COLOR_ON"):
            self.assertIsNone(_read({}, keywords, full=True), keywords)

    def test_legacy_profile_is_unchanged(self):
        # The per-effect readers keep the additive and stencil-masked alpha profiles only.
        additive = _read({}, world=True)
        self.assertEqual(additive, {"texture": None, "tint": [1, .5, .25, .75], "uv": [1, 1, 0, 0], "vertexColor": True,
                                    "cull": 0, "queue": 3000, "depthTest": True})
        masked = _read({"_BlendDst": 10, "_StencilComp": 3, "_StencilRef": 2}, world=True)
        self.assertEqual((masked["alphaBlend"], masked["stencilRef"]), (True, 2))
        self.assertNotIn("blend", masked)
        for floats in ({"_BlendDst": 10}, {"_BlendSrc": 1}, {"_ZTestMode": 3}, {"_StencilPassOp": 2}):
            self.assertIsNone(_read(floats, world=True), floats)
        full = _read({"_BlendDst": 10, "_StencilComp": 3, "_StencilRef": 2}, world=True, full=True)
        self.assertEqual({key: value for key, value in full.items() if key not in ("blend", "zTest", "stencil")}, masked)

    def test_overlay_export_needs_no_sort_bounds(self):
        fields = _read({"_BlendDst": 10}, full=True)
        materials = SimpleNamespace(texture=lambda texture: 0)
        self.assertIsNone(overlay.export_material(materials, fields))
        self.assertEqual(overlay.export_material(materials, fields, overlay=True)["blend"], [5, 10])


def _bundle(variable):
    raw = os.environ.get(variable)
    return Path(raw) if raw and Path(raw).is_file() else None


class RealTransparentStateTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_12026 / _12030 / _12035 to the original Android stage_effect bundles."""

    def materials(self, variable):
        path = _bundle(variable)
        if path is None:
            self.skipTest(f"Set {variable} to the original stage_effect bundle")
        env = viewer._environment([str(path)], time.monotonic() + 120)
        scene = viewer._Scene(env, time.monotonic() + 120)
        return scene, {scene.tree(obj).get("m_Name"): obj for obj in env.objects if obj.type.name == "Material"}

    def test_12026_black_out_and_shadow_alpha_passes(self):
        scene, materials = self.materials("SIFAS_TEST_STAGE_EFFECT_12026")
        black_out = overlay.read_material(scene, materials["mat_ove_gen_alb_01"], full=True)
        self.assertEqual((black_out["blend"], black_out["zTest"], black_out["stencil"]), ([5, 10], 4, [8, 2, 0, 0]))
        self.assertIsNone(overlay.read_material(scene, materials["mat_ove_gen_alb_01"]))
        shadow = overlay.read_material(scene, materials["mat_stg_so2026_oth_03"], world=True, full=True)
        self.assertEqual((shadow["blend"], shadow["cull"], shadow["tint"]), ([5, 10], 2, [0, 0, 0, 1]))

    def test_12030_shadow_writes_depth_with_stale_keywords(self):
        scene, materials = self.materials("SIFAS_TEST_STAGE_EFFECT_12030")
        material = materials["mat_stg_so2030_alb_oth_02"]
        self.assertIn("_ZWRITEPARAM_ON", scene.tree(material)["m_ShaderKeywords"].split())
        fields = overlay.read_material(scene, material, world=True, full=True)
        self.assertEqual((fields["blend"], fields["depthWrite"], fields["vertexColor"]), ([5, 10], True, True))

    def test_12035_full_reader_keeps_every_legacy_field(self):
        scene, materials = self.materials("SIFAS_TEST_STAGE_EFFECT_12035")
        compared = 0
        for name, material in materials.items():
            for world in (False, True):
                legacy = overlay.read_material(scene, material, world=world)
                if legacy is None or legacy.get("matcap"):
                    continue
                full = overlay.read_material(scene, material, world=world, full=True)
                self.assertEqual({key: value for key, value in full.items()
                                  if key not in ("blend", "zTest", "stencil", "saturate")}, legacy, name)
                compared += 1
        self.assertGreater(compared, 10)


if __name__ == "__main__":
    unittest.main()
