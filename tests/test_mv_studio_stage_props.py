"""Stage-effect props lit by LivePropBasic (LivePropAmbient / LivePropRimlight).

Set SIFAS_TEST_MV_EFFECT (optionally with SIFAS_TEST_MV_TIMELINE) to an original
stage_effect bundle with a LivePropBasic, such as 12035 or 12029, for the real
export check.
"""
import json
import os
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_viewer as viewer
from webtools.core import mv_studio_stage_props as props


def _object(kind, path_id, tree, name=""):
    return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=path_id, assets_file=SimpleNamespace(externals=[]),
                           tree=tree, name=name)


def _script(path_id, name):
    return _object("MonoScript", path_id, {"m_AssemblyName": "Assembly-CSharp.dll",
                                           "m_Namespace": "LLAS.Scene.Live.Components", "m_ClassName": name})


class StagePropBindingTests(unittest.TestCase):
    def setUp(self):
        self.objects = {
            1: _script(1, "LivePropBasic"), 2: _script(2, "LivePropAmbient"), 3: _script(3, "LivePropRimlight"),
            4: _script(4, "LiveCoreStageAmbient"),
            30: _object("Material", 30, {}, "mat_stg_so2035_oth_01"), 31: _object("Material", 31, {}, "mat_other"),
            40: _object("GameObject", 40, {}, "fx_stg_so2035_01"),
            20: _object("MonoBehaviour", 20, {"m_Script": {"m_PathID": 2}, "materials": [{"m_PathID": 30}]}),
            21: _object("MonoBehaviour", 21, {"m_Script": {"m_PathID": 3},
                                              "materials": [{"m_PathID": 30}, {"m_PathID": 31}]}),
            22: _object("MonoBehaviour", 22, {"m_Script": {"m_PathID": 4}, "materials": [{"m_PathID": 31}]}),
        }
        self.scene = SimpleNamespace(tree=lambda obj: obj.tree, name=lambda obj: obj.name)
        for patcher in (patch.object(viewer, "_ref", lambda owner, pointer: self.objects.get((pointer or {}).get("m_PathID"))),
                        patch.object(props, "_path", lambda scene, game: {
                            40: ("bg0006_01_fx_so2035_ex", "fx_stg_so2035_01")}.get(game.path_id, ()))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_prop_basic_binds_its_ambient_and_rimlight_material_names(self):
        tree = {"m_Script": {"m_PathID": 1}, "m_GameObject": {"m_PathID": 40},
                "ambient": {"m_FileID": 0, "m_PathID": 20}, "rimlight": {"m_FileID": 0, "m_PathID": 21}}
        path, entry = props.binding(self.scene, _object("MonoBehaviour", 9, tree), tree)
        self.assertEqual(path, ("bg0006_01_fx_so2035_ex", "fx_stg_so2035_01"))
        self.assertEqual(entry, {"binding": "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so2035_01",
                                 "ambient": {"mat_stg_so2035_oth_01"}, "rim": {"mat_stg_so2035_oth_01", "mat_other"}})
        self.assertEqual(props.light(entry, "mat_other"),
                         {"binding": entry["binding"], "ambient": False, "rim": True})
        self.assertIsNone(props.light(entry, "mat_unlisted"))
        # Fields must point at the matching component classes.
        wrong = {**tree, "ambient": {"m_FileID": 0, "m_PathID": 22}, "rimlight": {"m_FileID": 0, "m_PathID": 22}}
        self.assertIsNone(props.binding(self.scene, _object("MonoBehaviour", 9, wrong), wrong))
        other = {**tree, "m_Script": {"m_PathID": 2}}
        self.assertIsNone(props.binding(self.scene, _object("MonoBehaviour", 9, other), other))

    def test_stage_effect_initializes_every_prop_below_its_game_object(self):
        files = SimpleNamespace(externals=[])
        prop_tree = {"m_Script": {"m_PathID": 1}, "m_GameObject": {"m_PathID": 40},
                     "ambient": {"m_FileID": 0, "m_PathID": 20}, "rimlight": {"m_FileID": 0, "m_PathID": 21}}
        outside_tree = {**prop_tree, "m_GameObject": {"m_PathID": 41}}
        prop, outside = _object("MonoBehaviour", 50, prop_tree), _object("MonoBehaviour", 51, outside_tree)
        effect_tree = {"m_Script": {"m_PathID": 5}, "m_GameObject": {"m_PathID": 42}}
        effect = _object("MonoBehaviour", 52, effect_tree)
        self.objects.update({5: _script(5, "LiveCoreStageEffect"), 41: _object("GameObject", 41, {}, "loose"),
                             42: _object("GameObject", 42, {}, "bg0006_01_fx_so2035_ex")})
        for obj in (prop, outside, effect):
            obj.assets_file = files
        self.scene.env = SimpleNamespace(objects=[prop, outside, effect])
        paths = {40: ("bg0006_01_fx_so2035_ex", "fx_stg_so2035_01"), 41: ("other_root", "loose"),
                 42: ("bg0006_01_fx_so2035_ex",)}
        with patch.object(props, "_path", lambda scene, game: paths.get(game.path_id, ())):
            found = props.props(self.scene, effect, effect_tree)
            self.assertEqual([path for path, _ in found], [paths[40]])
            self.assertEqual(props.props(self.scene, prop, prop_tree), [])

    def test_renderers_below_the_prop_use_the_innermost_prop(self):
        outer, inner = ("root", "prop"), ("root", "prop", "child")
        entries = [(outer, {"binding": "outer"}), (inner, {"binding": "inner"})]
        paths = {1: ("root", "prop", "child", "mesh"), 2: ("root", "prop", "mesh"), 3: ("root", "other")}
        with patch.object(props, "_path", lambda scene, game: paths[game]):
            self.assertEqual(props.renderer_entry(None, 1, entries), {"binding": "inner"})
            self.assertEqual(props.renderer_entry(None, 2, entries), {"binding": "outer"})
            self.assertIsNone(props.renderer_entry(None, 3, entries))
        self.assertIsNone(props.renderer_entry(None, 1, []))


class RimlightMaterialTests(unittest.TestCase):
    def material(self, floats=(), colors=(), shader=("cab-6cf8387efa4151b6220fceb9384d0e8e", 7983779172275908372)):
        tree = {"m_Shader": {"m_FileID": 1, "m_PathID": shader[1]}, "m_CustomRenderQueue": -1,
                "m_SavedProperties": {
                    "m_Floats": [("_CullMode", 2), ("_RimglightIntensity", 0), ("_RimglightPower", 3), *floats],
                    "m_Colors": [("_TintColor", {"r": 1, "g": 1, "b": 1, "a": 1}),
                                 ("_RimlightDirection", {"r": 0, "g": 0, "b": 0, "a": 0}), *colors],
                    "m_TexEnvs": [("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 5},
                                                "m_Scale": {"x": 2, "y": 1}, "m_Offset": {"x": .5, "y": 0}}),
                                  ("_RimlightTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 0}})]}}
        material = SimpleNamespace(type=SimpleNamespace(name="Material"), assets_file=SimpleNamespace(
            externals=[SimpleNamespace(path=f"archive:/{shader[0].upper()}/{shader[0].upper()}")]))
        return SimpleNamespace(tree=lambda _: tree), material

    def test_reads_the_inputs_of_the_rimlight_pass_with_shader_defaults(self):
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"))
        scene, material = self.material()
        with patch.object(viewer, "_ref", lambda owner, pointer: texture if pointer.get("m_PathID") == 5 else None):
            fields = props.rimlight_material(scene, material)
            self.assertEqual(fields, {"texture": texture, "rimlightTexture": None, "uv": [2, 1, .5, 0],
                                      "tint": [1, 1, 1, 1], "ambient": [1, 1, 1, 0], "rimlightColor": [1, 1, 1, 1],
                                      "rimlightDirection": [0, 0, 0, 0], "intensity": 0, "power": 3, "cull": 2,
                                      "queue": 2000})
            materials = SimpleNamespace(texture=lambda obj: 7)
            self.assertEqual(props.export_rimlight(materials, fields)["texture"], 7)
            # Another shader or a stencil-testing variant is not this pass.
            self.assertIsNone(props.rimlight_material(*self.material(shader=("cab-other", 7983779172275908372))))
            self.assertIsNone(props.rimlight_material(*self.material(floats=[("_StencilComp", 3)])))
            self.assertIsNone(props.rimlight_material(*self.material(floats=[("_CullMode", 7)])))


@unittest.skipUnless(os.environ.get("SIFAS_TEST_MV_EFFECT"), "Set a private local stage_effect bundle path")
class StagePropBundleTests(unittest.TestCase):
    def test_prop_primitives_carry_their_binding(self):
        bindings = ()
        if os.environ.get("SIFAS_TEST_MV_TIMELINE"):
            from pathlib import Path

            from webtools.core import mv_studio_timeline

            timeline = Path(os.environ["SIFAS_TEST_MV_TIMELINE"])
            bindings = tuple(mv_studio_timeline.parse_timeline(
                timeline.read_bytes(), timeline.name, preview_stage_motion=True)["stageMotion"]["bindings"])
        prepared = viewer.prepare([os.environ["SIFAS_TEST_MV_EFFECT"]], face_context={
            "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_stage_motion_bindings": bindings,
            "_mv_native_stage_effect": bool(bindings)})
        payload = viewer.get_model(prepared["id"])
        size = struct.unpack_from("<I", payload, 12)[0]
        doc = json.loads(payload[20:20 + size])
        lit = [primitive["extras"] for mesh in doc["meshes"] for primitive in mesh["primitives"]
               if "mvPropLight" in primitive["extras"]]
        self.assertTrue(lit)
        for extras in lit:
            self.assertTrue(extras["mvPropLight"]["binding"].startswith("/EntryPoint/Live/Stages/MainStage/Effect/"))
            if "mvStageRimlight" in extras:
                self.assertIn("cull", extras["mvStageRimlight"])


if __name__ == "__main__":
    unittest.main()
