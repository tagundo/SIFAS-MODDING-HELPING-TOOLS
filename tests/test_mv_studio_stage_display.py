"""Stage display screens: each variant by its own shader program, the client's switching rules, coverage."""
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer, mv_studio_import_coverage as coverage
from webtools.core import mv_studio_stage_display as displays


def _material(floats=(), colors=(), envs=(), keywords="", queue=-1, path_id=7):
    tree = {"m_ShaderKeywords": keywords, "m_CustomRenderQueue": queue,
            "m_SavedProperties": {"m_Floats": list(floats), "m_Colors": list(colors), "m_TexEnvs": list(envs)}}
    return SimpleNamespace(type=SimpleNamespace(name="Material"), tree=tree, path_id=path_id,
                           assets_file=SimpleNamespace(name="CAB-display"))


def _scene(**attributes):
    return SimpleNamespace(tree=lambda material: material.tree, **attributes)


def _env(scale=(1, 1), offset=(0, 0), texture=0):
    return {"m_Texture": {"m_FileID": 0, "m_PathID": texture}, "m_Scale": dict(zip("xy", scale)),
            "m_Offset": dict(zip("xy", offset))}


def _read(shader, material, scene=None, materials=None):
    with patch.object(displays, "shader_name", return_value=shader):
        return displays.read(scene or _scene(), materials, material)


class DisplayMaterialTests(unittest.TestCase):
    def test_additive_opaque_reads_both_maps_and_always_vertex_color(self):
        # mat_dis_bg_so1054_opa_01_oth (11054/3): no _MainTex, _AdditiveTex_ST (.5, 1, .25, 0), _CullMode 2.
        material = _material(floats=[("_CullMode", 2), ("_StencilPassOp", 2), ("_VERTEX_COLOR", 0)],
                             colors=[("_AmbientColor", {"r": 0, "g": 0, "b": 0, "a": 0})],
                             envs=[("_AdditiveTex", _env((.5, 1), (.25, 0))), ("_MainTex", _env())])
        fields = _read("AS/Blend/AdditiveOpaque", material)
        self.assertEqual(fields, {
            "material": "CAB-display:7", "kind": "blendAdditive", "texture": None, "uv": [1, 1, 0, 0], "tint": [1, 1, 1, 1], "ambient": [0, 0, 0, 0],
            "cull": 2, "queue": 2000, "stencil": 2, "stencilComp": 8, "stencilPass": 2, "stencilZFail": 0,
            "additive": {"texture": None, "uv": [.5, 1, .25, 0]}, "vertexColor": True})
        # _CullMode defaults to Back.
        material.tree["m_SavedProperties"]["m_Floats"] = []
        fields = _read("AS/Blend/AdditiveOpaque", material)
        self.assertEqual((fields["cull"], fields["stencilPass"]), (2, 0))

    def test_additive_opaque_fed_by_the_display_camera_is_unsupported(self):
        # LiveCoreStageDisplayCamera replaces _AdditiveTex with its live image of the members, which
        # the preview does not render: the screen keeps its own material while such a variant is selected.
        material = _material(envs=[("_AdditiveTex", _env((.5, 1), (.25, 0)))])
        with self.assertRaisesRegex(displays.Unsupported, "display camera"):
            _read("AS/Blend/AdditiveOpaque", material, _scene(mv_stage_display_camera=True))
        self.assertEqual(_read("AS/General/Opaque", material, _scene(mv_stage_display_camera=True))["kind"], "general")

    def test_wave_texture_reads_four_layers_with_shader_defaults(self):
        # mat_dis_shd_so1005_uni_01 (11005/3): _MainTex_ST scale (1, 0), _TintColor black, one layer left at defaults.
        floats = [("_RepeatX1", .2), ("_RepeatY1", .8), ("_SpeedX1", -.05), ("_SpeedY1", 0),
                  ("_RepeatX2", .2), ("_RepeatY2", .75), ("_SpeedX2", -.07), ("_SpeedY2", 0),
                  ("_RepeatX3", .2), ("_RepeatY3", .8), ("_SpeedX3", -.03), ("_StencilPassOp", 2), ("_StencilZFailOp", 2),
                  ("_CullMode", 0)]
        material = _material(floats=floats, colors=[("_TintColor", {"r": 0, "g": 0, "b": 0, "a": 1}),
                                                    ("_WaveColor", {"r": 1, "g": 1, "b": 1, "a": .4})],
                             envs=[("_MainTex", _env((1, 0))), ("_WaveTex", _env((3, 3), (.5, .5)))])
        fields = _read("AS/Uniq/so1005-DisplayWaveTexture", material)
        self.assertEqual(fields["kind"], "waveTexture")
        self.assertEqual(fields["uv"], [1, 0, 0, 0])
        self.assertEqual(fields["cull"], 2, "the pass culls back faces; _CullMode is not bound")
        self.assertEqual((fields["tint"], fields["ambient"]), ([0, 0, 0, 1], [1, 1, 1, 0]))
        self.assertEqual(fields["wave"], {"texture": None, "color": [1, 1, 1, .4], "layers": [
            [.2, .8, -.05, 0], [.2, .75, -.07, 0], [.2, .8, -.03, 0.0], [2.0, 3.0, .5, 0.0]]})
        self.assertEqual((fields["stencilPass"], fields["stencilZFail"]), (2, 2))
        self.assertNotIn("vertexColor", fields)

    def test_transparent_backgrounds_and_logos_keep_their_compiled_state(self):
        # mat_dis_so0122_02 (10122/3): Blend Zero One, ZTest Greater, both keywords.
        material = _material(floats=[("_BlendSrc", 0), ("_BlendDst", 1), ("_ZTestMode", 5), ("_ZWriteParam", 0),
                                     ("_SATURATE", 1), ("_VERTEX_COLOR", 1)],
                             keywords="_SATURATE_ON _VERTEX_COLOR_ON")
        fields = _read("AS/General/Transparent", material)
        self.assertEqual({key: fields[key] for key in ("kind", "blend", "zTest", "zWrite", "cull", "queue")},
                         {"kind": "transparent", "blend": [0, 1], "zTest": 5, "zWrite": False, "cull": 0, "queue": 3000})
        self.assertTrue(fields["saturate"] and fields["vertexColor"])
        self.assertNotIn("ambient", fields, "AS/General/Transparent has no _AmbientColor")
        # mat_dis_logo_so2022_add_01 (12022/3): additive logo with an HDR tint.
        material = _material(floats=[("_BlendSrc", 5), ("_BlendDst", 1)],
                             colors=[("_TintColor", {"r": 1.498, "g": 1.498, "b": 1.498, "a": 1})])
        fields = _read("AS/General/Transparent", material)
        self.assertEqual((fields["blend"], fields["tint"]), ([5, 1], [1.498, 1.498, 1.498, 1]))
        for floats in ([("_BlendSrc", 11)], [("_ZTestMode", 9)], [("_ZWriteParam", .5)], [("_CullMode", 3)]):
            material.tree["m_SavedProperties"]["m_Floats"] = floats
            with self.assertRaises(displays.Unsupported):
                _read("AS/General/Transparent", material)

    def test_unknown_shaders_and_undecodable_textures_are_reported(self):
        with self.assertRaisesRegex(displays.Unsupported, "AS/Smoke"):
            _read("AS/Smoke", _material())
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        materials = SimpleNamespace(texture=lambda _: (_ for _ in ()).throw(ValueError("ETC2_RGBA8 is unavailable")))
        with patch.object(model_viewer, "_ref", return_value=texture):
            with self.assertRaisesRegex(displays.Unsupported, "_MainTex could not be decoded"):
                _read("AS/General/Opaque", _material(envs=[("_MainTex", _env(texture=5))]), materials=materials)


class DisplayExportTests(unittest.TestCase):
    def export(self, variants, own, fallback="fallback"):
        names = {"fallback": "AS/General/Opaque", "opaque": "AS/General/Opaque", "logo": "AS/General/Transparent",
                 "smoke": "AS/Smoke"}
        objects = {name: _material(path_id=index) for index, name in enumerate(names)}
        for name, material in objects.items():
            material.label = name
        renderer = SimpleNamespace(tree={"m_Materials": [{"m_PathID": index + 1} for index in range(len(own))]})
        scene = _scene(warnings=[])
        pointers = {index + 1: objects[name] for index, name in enumerate(own)}
        binding = ("/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main", objects.get(fallback),
                   [(objects[bg], objects.get(logo)) for bg, logo in variants], renderer)
        with patch.object(displays, "shader_name", side_effect=lambda material, tree: names[material.label]), \
                patch.object(model_viewer, "_ref", side_effect=lambda owner, pointer: pointers.get(pointer["m_PathID"])):
            return displays.export(scene, None, binding), scene.warnings

    def test_one_unsupported_variant_keeps_the_display(self):
        exported, warnings = self.export([("opaque", "logo"), ("smoke", "logo"), ("opaque", None)], ["opaque", "logo"])
        self.assertEqual([sorted(variant) for variant in exported["variants"]],
                         [["background", "logo"], ["unsupported"], ["background", "logo"]])
        self.assertEqual(exported["variants"][1]["unsupported"], "shader AS/Smoke has no display reader")
        self.assertEqual((exported["initial"]["background"]["kind"], exported["initial"]["logo"]["kind"]),
                         ("general", "transparent"), "the renderer's own two materials over its one submesh")
        self.assertEqual(warnings, [{
            "code": "stage_display_variant_unsupported", "name": "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main",
            "message": warnings[0]["message"], "target": "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main",
            "variants": 3, "unsupported": [[1, "shader AS/Smoke has no display reader"]]}])

    def test_a_logo_that_is_the_background_material_shares_the_mixer_writes(self):
        exported, _ = self.export([("opaque", "opaque")], ["opaque"], fallback=None)
        self.assertIsNone(exported["fallback"], "no material2DReference: the client keeps the display enabled")
        variant = exported["variants"][0]
        # The Material asset identity: LiveDisplayMixer's writes reach every pass that draws it.
        self.assertEqual(variant["logo"]["material"], variant["background"]["material"])
        self.assertEqual(exported["initial"]["background"]["material"], variant["background"]["material"])
        self.assertIsNone(exported["initial"]["logo"])

    def test_a_display_with_nothing_to_draw_is_left_to_its_renderer(self):
        exported, warnings = self.export([("smoke", "logo")], ["smoke"])
        self.assertIsNone(exported)
        self.assertEqual(warnings[0]["unsupported"], [[0, "shader AS/Smoke has no display reader"]])


class DisplayCoverageTests(unittest.TestCase):
    def test_clips_selecting_an_unsupported_variant_are_not_rendered(self):
        target = "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main"
        events = [{"id": f"d:{index}", "start": index, "duration": 1, "values": {"materialIndex": material}}
                  for index, material in enumerate((0, 1, 7, -2))]
        project = {"tracks": [{"id": "d", "nativeClass": "LiveDisplayTrack", "binding": target, "events": events}],
                   "warnings": []}
        gap = {"code": coverage.DISPLAY_VARIANTS_UNSUPPORTED, "target": target, "variants": 2,
               "unsupported": [[1, "_MainTex could not be decoded"]]}
        report = coverage.apply(project, display_gaps=[gap])
        rows = {(row["status"], row["note"]): row["clips"] for row in report["tracks"]}
        # materialIndex 7 clamps to the last variant (1), -2 to the first (0).
        self.assertEqual(rows, {
            (coverage.RENDERED, "Stage display screens."): 2,
            (coverage.NOT_RENDERED, "Display clips selecting a variant MV Studio cannot draw (_MainTex could not be "
                                    "decoded); the screen keeps its own material."): 2})
        self.assertIn("LiveDisplayTrack x1 (2 clips: Display clips selecting a variant", project["warnings"][0])
        self.assertEqual(coverage.report(project)["gaps"], [], "without the preview's warning the track is rendered")


class ActualDisplayVariantTests(unittest.TestCase):
    """Set SIFAS_TEST_STAGE_EFFECT_<live> to the original Android stage_effect bundle of <live>/3."""

    def screens(self, live):
        raw = os.environ.get(f"SIFAS_TEST_STAGE_EFFECT_{live}")
        if not raw or not Path(raw).is_file():
            self.skipTest(f"Set SIFAS_TEST_STAGE_EFFECT_{live} to the original stage_effect bundle")
        deadline = time.monotonic() + 120
        env = model_viewer._environment([raw], deadline)
        scene = model_viewer._Scene(env, deadline)
        materials = SimpleNamespace(texture=lambda texture: texture.path_id)
        found = []
        for obj in env.objects:
            if obj.type.name == "MonoBehaviour":
                tree = scene.tree(obj)
                found.append(displays.binding(scene, obj, tree))
        result = {entry[1][0].rsplit("/", 1)[-1]: displays.export(scene, materials, entry[1]) for entry in found if entry}
        return result, scene

    @staticmethod
    def kinds(screen):
        return [(variant["background"]["kind"], variant["logo"] and variant["logo"]["kind"])
                for variant in screen["variants"]]

    def test_11054_main_display_camera_screen_keeps_the_own_material(self):
        screens, scene = self.screens(11054)
        self.assertTrue(scene.mv_stage_display_camera)
        main = screens["main"]
        self.assertIn("display camera", main["variants"][0]["unsupported"])
        self.assertEqual((main["variants"][1]["background"]["kind"], main["variants"][1]["logo"]["kind"]),
                         ("general", "transparent"))
        self.assertEqual((main["initial"]["background"]["kind"], main["initial"]["logo"]), ("general", None))
        self.assertEqual(self.kinds(screens["sub_01"]), [("general", "transparent")])
        self.assertEqual([warning["unsupported"][0][0] for warning in scene.warnings
                          if warning["code"] == coverage.DISPLAY_VARIANTS_UNSUPPORTED], [0])

    def test_12074_screens_keep_all_six_variants(self):
        screens, _ = self.screens(12074)
        for name in ("main_01", "sub_01"):
            variants = screens[name]["variants"]
            self.assertEqual([variant["background"]["kind"] for variant in variants[:5]], ["general"] * 5)
            self.assertIn("display camera", variants[5]["unsupported"])

    def test_11005_and_12030_wave_screens(self):
        screens, scene = self.screens(11005)
        self.assertFalse(getattr(scene, "mv_stage_display_camera", False))
        wave = screens["main"]["variants"][6]["background"]
        rounded = lambda values: [round(value, 6) for value in values]  # noqa: E731 (float32 properties)
        self.assertEqual((wave["kind"], wave["uv"], wave["tint"], rounded(wave["wave"]["color"])),
                         ("waveTexture", [1, 0, 0, 0], [0, 0, 0, 1], [1, 1, 1, .4]))
        self.assertEqual(rounded(wave["wave"]["layers"][3]), [.2, .7, -.06, 0])
        screens, _ = self.screens(12030)
        for name in ("main_01", "sub_01"):
            self.assertIsNone(screens[name]["fallback"], "no material2DReference")
            self.assertEqual(self.kinds(screens[name])[0], ("waveTexture", "transparent"))
            self.assertEqual(screens[name]["initial"]["logo"]["kind"], "transparent")

    def test_logo_and_background_gates(self):
        screens, _ = self.screens(10122)
        self.assertEqual(self.kinds(screens["main"]), [("general", "transparent"), ("transparent", "transparent")])
        self.assertEqual(screens["main"]["fallback"]["stencilPass"], 0)
        screens, _ = self.screens(12055)
        self.assertEqual(self.kinds(screens["litE_01_display"]), [("general", "general")] * 2)
        variant = screens["litE_01_display"]["variants"][0]
        self.assertEqual(variant["logo"]["material"], variant["background"]["material"])
        self.assertNotEqual(screens["main"]["variants"][0]["background"]["material"],
                            screens["main"]["variants"][0]["logo"]["material"])
        screens, _ = self.screens(11046)
        self.assertTrue(screens["main"]["variants"][5]["logo"]["saturate"])
        screens, _ = self.screens(12022)
        self.assertEqual(screens["main"]["variants"][0]["logo"]["blend"], [5, 1])
        self.assertNotIn("sub_01", screens, "a display without materialReferences switches nothing")


class ActualDisplayExportTests(unittest.TestCase):
    """The whole model_viewer export of real ETC2_RGBA8 screen textures (decoded in numpy, not stubbed).
    Set SIFAS_TEST_STAGE_EFFECT_11005 and SIFAS_TEST_STAGE_EFFECT_11046 to the original Android
    stage_effect bundles of 11005/3 and 11046/3."""

    def export(self, live):
        import io
        import json
        import struct
        from PIL import Image
        raw = os.environ.get(f"SIFAS_TEST_STAGE_EFFECT_{live}")
        if not raw or not Path(raw).is_file():
            self.skipTest(f"Set SIFAS_TEST_STAGE_EFFECT_{live} to the original stage_effect bundle")
        prepared = model_viewer.prepare([raw], rigged=False, face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
            "_mv_stage_motion_bindings": (), "_mv_performer": False, "_mv_native_stage_effect": True})
        payload = model_viewer.get_model(prepared["id"])
        size = struct.unpack_from("<I", payload, 12)[0]
        doc, binary = json.loads(payload[20:20 + size]), payload[28 + size:]
        screens = {extras["mvStageDisplay"]["target"].rsplit("/", 1)[-1]: extras["mvStageDisplay"]
                   for mesh in doc["meshes"] for primitive in mesh["primitives"]
                   for extras in [primitive.get("extras") or {}] if "mvStageDisplay" in extras}

        def image(index):
            source = doc["images"][doc["textures"][index]["source"]]
            view = doc["bufferViews"][source["bufferView"]]
            start = view.get("byteOffset", 0)
            return source["name"], Image.open(io.BytesIO(binary[start:start + view["byteLength"]])).convert("RGBA")
        codes = [item.get("code") for item in prepared.get("warnings") or () if isinstance(item, dict)]
        return screens, image, codes, raw

    @staticmethod
    def source(path, name):
        import UnityPy
        texture, = [obj.read() for obj in UnityPy.load(path).objects
                    if obj.type.name == "Texture2D" and obj.read().m_Name == name]
        return int(texture.m_TextureFormat), texture.image.convert("RGBA")

    def assert_exact(self, embedded, path):
        from PIL import ImageChops
        name, image = embedded
        texture_format, original = self.source(path, name)
        self.assertEqual(texture_format, 47, "ETC2_RGBA8")
        self.assertEqual(image.size, original.size, "no resampling")
        self.assertIsNone(ImageChops.difference(image, original).getbbox(), f"{name} is decoded exactly")

    def test_11005_wave_screen_draws_its_etc2_wave_texture(self):
        screens, image, codes, path = self.export(11005)
        self.assertNotIn(coverage.DISPLAY_VARIANTS_UNSUPPORTED, codes)
        wave = screens["main"]["variants"][6]["background"]
        self.assertEqual(wave["kind"], "waveTexture")
        self.assertIsInstance(wave["wave"]["texture"], int)
        self.assert_exact(image(wave["wave"]["texture"]), path)

    def test_11046_logo_draws_its_etc2_texture(self):
        screens, image, codes, path = self.export(11046)
        self.assertNotIn(coverage.DISPLAY_VARIANTS_UNSUPPORTED, codes)
        logo = screens["main"]["variants"][5]["logo"]
        self.assertEqual((logo["kind"], logo["saturate"]), ("transparent", True))
        self.assert_exact(image(logo["texture"]), path)


if __name__ == "__main__":
    unittest.main()
