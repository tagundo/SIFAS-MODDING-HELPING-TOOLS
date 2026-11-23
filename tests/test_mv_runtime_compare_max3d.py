"""Device conventions of mv_runtime_compare.py found on the Max 3D (Quality 10) run of live 12035: runtime member
meshes, the overlay camera, clamped deltaTime, AxisBillboard transforms, editor shader materials and curve-driven
(MaterialPropertyBlock) properties, cheek floats under _CHEEK 0, the render-target size, particle systems,
blend shapes joined by channel name and the per-part coverage of the game dump."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mv_runtime_compare as C  # noqa: E402

MEMBER = "/EntryPoint/Live/Members/Member1"
HEAD = MEMBER + "/Model/Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/Neck/Head/Head_All"


def frame(t, dt, overlay_mask=1 << 20, ident=None):
    return {"kind": "frame", "id": ident or f"f{t}", "seq": 1, "clock": {"directorTime": t, "deltaTime": dt},
            "cameras": [{"key": "camera:main", "cullingMask": 202096659, "isActiveAndEnabled": True},
                        {"key": "camera:overlay", "cullingMask": overlay_mask, "isActiveAndEnabled": True}]}


def documents(records, editor_records=(), trailer=None):
    game = {"schema": C.SCHEMA, "side": "game", "header": {"conventions": {"matrixLayout": "column-major"}}, "records": list(records)}
    if trailer is not None:
        game["trailer"] = trailer
    editor = {"schema": C.SCHEMA, "side": "editor", "header": {}, "records": list(editor_records)}
    return game, editor


def comparison(records=(), editor_records=()):
    game, editor = documents(records or [frame(5.0, 0.2)], editor_records)
    result = C.Comparison(game, editor)
    result.renderer_map["renderer:/x/microphone"] = "renderer:effect:mic"
    return result


class MemberMeshAliasTest(unittest.TestCase):
    def test_runtime_meshes_map_to_editor_sources(self):
        self.assertEqual(C.Conventions.member_mesh_alias(HEAD + "/mesh_face/CombineFace", "member1"), "Face")
        self.assertEqual(C.Conventions.member_mesh_alias(HEAD + "/mesh_hair/Hair/ch0212_co0002_head_Bone2", "member1"), "Hair")
        self.assertEqual(C.Conventions.member_mesh_alias(MEMBER + "/Model/mesh_body/Body/ch0212_co0002_body_Bone1", "member1"), "Body")
        self.assertIsNone(C.Conventions.member_mesh_alias(HEAD + "/display_OnOff/LeftEyeWhiteLine", "member1"))
        self.assertIsNone(C.Conventions.member_mesh_alias(HEAD + "/mesh_face/CombineFace", "effect"))

    def test_split_hair_renderers_join_the_flattened_editor_hair(self):
        game, editor = documents([frame(5.0, 0.2)], [{"id": "r", "sourceRecord": "x", "phase": 0, "renderers": [
            {"key": "renderer:member1:Hair", "scope": "member1", "mesh": "Hair", "path": None}]}])
        result = C.Comparison(game, editor)
        for bone in (1, 2):
            joined = result.join_renderer({"key": f"renderer:hair{bone}", "scope": "member1", "mesh": f"ch0212_co0002_head_Bone{bone}",
                                           "path": HEAD + f"/mesh_hair/Hair/ch0212_co0002_head_Bone{bone}"})
            self.assertEqual(joined, "renderer:member1:Hair")
        self.assertEqual(result.join_methods["mesh"], 2)


class OverlayCameraTest(unittest.TestCase):
    def test_layer_20_is_drawn_when_the_overlay_camera_draws_it(self):
        game, editor = documents([frame(5.0, 0.2)])
        drawn, why = C.Comparison(game, editor).game_drawn({"enabled": True, "activeInHierarchy": True, "layer": 20},
                                                            {"clock": {"directorTime": 5.0}})
        self.assertTrue(drawn)
        self.assertIn("overlayCamera=1", why)

    def test_quality_40_overlay_mask_0_is_not_drawn(self):
        game, editor = documents([frame(5.0, 0.2, overlay_mask=0)])
        drawn, _ = C.Comparison(game, editor).game_drawn({"enabled": True, "activeInHierarchy": True, "layer": 20},
                                                         {"clock": {"directorTime": 5.0}})
        self.assertFalse(drawn)


class ClampedDeltaTest(unittest.TestCase):
    def test_clamped_delta_time_is_timing_uncertain_once(self):
        game, editor = documents([frame(5.0, 1 / 3)])
        result = C.Comparison(game, editor)
        self.assertTrue(result.near_cut(game["records"][0], -1, []))
        self.assertTrue(result.near_cut(game["records"][0], -1, []))
        self.assertEqual(result.notes["timing.clampedDeltaTime"], ["f5.0"])
        self.assertFalse(result.near_cut(dict(game["records"][0], clock={"directorTime": 5.0, "deltaTime": 0.2}), -1, []))
        # Phase 0 reads the frame itself: the clamp does not matter.
        self.assertFalse(result.near_cut(game["records"][0], 0, []))


class ParticleTest(unittest.TestCase):
    def test_control_track_instance_path(self):
        self.assertEqual(C.Comparison.particle_key("/fx_dis_par_so2035_01 [Timeline]/root/left_dis/kira_up"),
                         "fx_dis_par_so2035_01/root/left_dis/kira_up")
        self.assertIsNone(C.Comparison.particle_key("/EntryPoint/SkillCutin/Effects/x"))

    def test_playing_count_and_seed(self):
        result = comparison()
        record = {"id": "p", "clock": {"directorTime": 21.98}, "particles": [
            {"path": "/fx_a [Timeline]/root/kira", "isPlaying": True, "particleCount": 31, "randomSeed": -5, "useAutoRandomSeed": False},
            {"path": "/fx_a [Timeline]/root/cloud", "isPlaying": True, "particleCount": 1},
            {"path": "/fx_a [Timeline]/root/stopped", "isPlaying": False, "particleCount": 0},
            {"path": "/EntryPoint/SkillCutin/x", "isPlaying": True, "particleCount": 3}]}
        partner = {"particles": [{"path": "fx_a/root/kira", "alive": 45, "seed": 2 ** 32 - 5}]}
        result.compare_particles(record, partner)
        found = {(item["key"], item["metric"]): item for item in result.items}
        self.assertEqual(found[("particles:fx_a/root/kira", "particleSystemPlaying")]["score"], 0.0)
        self.assertEqual(found[("particles:fx_a/root/cloud", "particleSystemPlaying")]["score"], C.EXACT_SCORE)
        self.assertAlmostEqual(found[("particles:fx_a/root/kira", "particleCount")]["score"], 14 / 4.5)
        self.assertEqual(found[("particles:fx_a/root/kira", "particleSeed")]["score"], 0.0)
        self.assertEqual(len(result.items), 4)
        self.assertIn("particles", C.DIAGNOSTIC_TYPES)


class VectorGlobalTest(unittest.TestCase):
    def test_render_texture_resolution_is_exact(self):
        result = comparison()
        record = {"id": "f1", "clock": {"directorTime": 5.0, "deltaTime": 0.2},
                  "globals": {"global:_RenderTextureResolution": {"f": 0, "v": [1280, 720, 0, 0]}}}
        result.compare_globals(record, {"globals": {"global:_RenderTextureResolution": {"f": 0, "v": [1920, 1080, 0, 0]}}}, False)
        self.assertEqual((result.items[-1]["metric"], result.items[-1]["score"]), ("globalVector", C.EXACT_SCORE))
        result.compare_globals(record, {"globals": {"global:_RenderTextureResolution": {"f": 0, "v": [1280, 720, 0, 0]}}}, False)
        self.assertEqual(result.items[-1]["score"], 0.0)


def material_record(name, properties):
    return {"id": "m", "clock": {"directorTime": 5.0}, "materials": [{"name": name, "usedBy": ["renderer:/x/microphone#0"],
                                                                      "properties": properties}]}


def editor_material(kind="shader", **fields):
    return {"materials": [dict({"key": "material:renderer:effect:mic#0", "kind": kind, "visible": True}, **fields)]}


class ShaderMaterialTest(unittest.TestCase):
    def test_prop_light_uniforms_are_compared_and_hidden_materials_skipped(self):
        result = comparison()
        game = material_record("mat", {"_TintColor": {"t": "color", "v": [0.4, 0.4, 0.4, 1]}, "_Color": {"t": "color", "v": [1, 1, 1, 1]}})
        editor = editor_material(values={"uTintColor": {"t": "vector", "v": [0.4, 0.4, 0.4, 1]}, "uColor": {"t": "vector", "v": [1, 1, 1, 0.2]}})
        result.compare_materials(game, editor, False)
        self.assertEqual([item["field"] for item in result.items], ["_TintColor"])   # uColor is no C#-written property
        editor["materials"][0]["visible"] = False
        result.items.clear()
        result.compare_materials(game, editor, False)
        self.assertEqual(result.items, [])

    def test_flash_light_aliases_and_texture_st_spaces(self):
        game = material_record("mat_fla_01", {"_Speed": {"t": "float", "v": 0.7}, "_Length": {"t": "float", "v": 8},
                                              "_TintColor": {"t": "color", "v": [1, 1, 1, 1]},
                                              "_MainTex": {"t": "tex", "v": {"name": "tex", "width": 512, "height": 512}, "st": [1, 2, 0.25, 0.5]}})
        values = {"uSpeed": {"t": "float", "v": 0.7}, "uLength": {"t": "float", "v": 8}, "uTint": {"t": "vector", "v": [1, 1, 1, 1]},
                  "uTextureST": {"t": "vector", "v": [1, 2, 0.25, 0.5]}, "uAtlasST": {"t": "vector", "v": [4, 2, 0, 0]}}
        for space, st, expected in (("unity", [1, 2, 0.25, 0.5], 0.0), ("gltf", [1, 2, 0.25, 1 - 2 - 0.5], 0.0),
                                    ("gltf", [1, 2, 0.25, 0.5], C.EXACT_SCORE), (None, [9, 9, 9, 9], None)):
            result = comparison()
            result.compare_materials(game, editor_material(values=dict(values, uTextureST={"t": "vector", "v": st}), textureSTSpace=space), False)
            fields = {item["field"]: item for item in result.items}
            self.assertEqual(fields["_Speed (abs 0)"]["score"], 0.0)
            self.assertEqual(fields["_Length (abs 0)"]["score"], 0.0)
            self.assertEqual(fields["_TintColor"]["metric"], "colorAbs")
            if expected is None:
                self.assertNotIn("_MainTex", fields)
            else:
                self.assertEqual(fields["_MainTex"]["metric"], "textureStAbs")
                self.assertEqual(min(fields["_MainTex"]["score"], C.EXACT_SCORE), expected)

    def test_curve_driven_uniforms_are_labelled_not_compared(self):
        result = comparison()
        game = material_record("mat_ove_so2035_add_01", {"_TintColor": {"t": "color", "v": [1, 1, 1, 1]},
                                                         "_Density": {"t": "float", "v": 0.8},
                                                         "_MainTex": {"t": "tex", "v": None, "st": [1, 1, 0, 0]}})
        editor = editor_material(editorName="Native stage overlay", curveDriven=["uTextureST", "uTint"], textureSTSpace="unity",
                                 values={"uTint": {"t": "vector", "v": [0.65, 0.65, 0.89, 0.6]}, "_Density": {"t": "float", "v": 0.8},
                                         "uTextureST": {"t": "vector", "v": [2, 1, 0.3, 0]}})
        result.compare_materials(game, editor, False)
        self.assertEqual([item["field"] for item in result.items], ["_Density (abs 0)"])
        self.assertEqual(sorted(result.notes["materials.notComparableMPB"]),
                         ["Native stage overlay:_MainTex_ST (uTextureST)", "Native stage overlay:_TintColor (uTint)"])

    def test_a_curve_driven_stage_st_keeps_the_texture_comparison(self):
        result = comparison()
        game = material_record("mat_stg", {"_MainTex": {"t": "tex", "v": {"name": "t", "width": 256, "height": 256}, "st": [1, 1, 0, 0]}})
        editor = editor_material(kind="stage", editorName="mat_stg", curveDriven=["mainUVTransform"], properties={"_MainTex": {
            "t": "tex", "v": {"name": "t", "width": 256, "height": 256}, "from": "mainMap", "st": [1, 1, 0.5, 0], "stFrom": "mainUVTransform"}})
        result.compare_materials(game, editor, False)
        self.assertEqual([(item["metric"], item["score"]) for item in result.items], [("textureSize", 0.0)])
        self.assertEqual(result.notes["materials.notComparableMPB"], ["mat_stg:_MainTex_ST (mainUVTransform)"])

    def test_cheek_floats_are_ignored_under_cheek_keyword_off(self):
        result = comparison()
        game = material_record("head", {"_CHEEK": {"t": "float", "v": 0}, "_CheekIntensity": {"t": "float", "v": 0.045},
                                        "_RimglightIntensity": {"t": "float", "v": 0.5}})
        editor = editor_material(kind="member", properties={"_CheekIntensity": {"t": "float", "v": 0},
                                                            "_RimglightIntensity": {"t": "float", "v": 0.5}})
        result.compare_materials(game, editor, False)
        self.assertEqual([item["field"].split(" ")[0] for item in result.items], ["_RimglightIntensity"])
        self.assertEqual(result.notes["materials.cheekKeywordOff"], ["_CheekIntensity"])
        result.items.clear()
        game["materials"][0]["properties"]["_CHEEK"]["v"] = 1
        result.compare_materials(game, editor, False)
        self.assertIn("_CheekIntensity", [item["field"].split(" ")[0] for item in result.items])


class BillboardTest(unittest.TestCase):
    def test_off_screen_billboard_rotation_is_not_compared(self):
        game, editor = documents([frame(5.0, 0.2)], [{"id": "r", "sourceRecord": "x", "phase": 0, "renderers": [
            {"key": "renderer:effect:cone", "scope": "effect", "mesh": "cone", "path": "Effect/lit/cone"}]}])
        result = C.Comparison(game, editor)
        result.joins["renderer:cone"] = ("renderer:effect:cone", "path")
        transform = {"position": [1, 2, 3], "rotation": [0, 0, 0, 1]}
        record = {"id": "g", "clock": {"directorTime": 5.0}, "renderers": [
            {"key": "renderer:cone", "scope": "effect", "path": "/EntryPoint/Live/Stages/MainStage/Effect/lit/cone",
             "enabled": True, "activeInHierarchy": True, "isVisible": False, "transform": transform}]}
        partner = {"renderers": [{"key": "renderer:effect:cone", "visible": True, "axisBillboard": True,
                                  "transform": {"position": [-1, 2, 3], "rotation": [0, 0.7071068, 0, 0.7071068]}}]}
        result.compare_renderers(record, partner, False)
        metrics = [item["metric"] for item in result.items if item["type"] == "transforms"]
        self.assertEqual(metrics, ["rendererPositionM"])
        self.assertEqual(result.notes["transforms.offscreenAxisBillboard"], ["renderer:effect:cone"])
        record["renderers"][0]["isVisible"] = True
        result.items.clear()
        result.compare_renderers(record, partner, False)
        self.assertIn("rendererRotationDeg", [item["metric"] for item in result.items])


class BlendShapeTest(unittest.TestCase):
    GAME = {"slot": 1, "blendShapes": [
        {"rendererKey": f"renderer:{HEAD}/mesh_face/CombineFace", "count": 27,
         "weights": {"MouthBlendShape.mouth_facial_004": 35.8, "EyeBlendShape.eye_facial_002": 100}},
        {"rendererKey": f"renderer:{HEAD}/display_OnOff/LeftEyeWhiteLine", "count": 3, "weights": {}},
        {"rendererKey": f"renderer:{MEMBER}/Model/mesh_body/Body/x_body_Bone1", "count": 0, "weights": {}}]}

    def test_channels_join_across_combine_face_and_the_editor_face_meshes(self):
        result = comparison()
        editor = {"slot": 1, "morphs": [
            {"rendererKey": "renderer:member1:Eye_Around", "unit": "influence01", "weights": {"EyeBlendShape.eye_facial_002": 1}},
            {"rendererKey": "renderer:member1:Eye", "unit": "influence01", "weights": {"EyeBlendShape.eye_facial_002": 1}},
            {"rendererKey": "renderer:member1:Mouth", "unit": "influence01", "weights": {"MouthBlendShape.mouth_facial_001": 0.25}}]}
        result.compare_blend_shapes({"id": "m", "clock": {"directorTime": 17.86}}, self.GAME, editor, False)
        found = {item["key"]: item for item in result.items}
        self.assertEqual(sorted(found), ["blendShape:member1:EyeBlendShape.eye_facial_002",
                                         "blendShape:member1:MouthBlendShape.mouth_facial_001",
                                         "blendShape:member1:MouthBlendShape.mouth_facial_004"])
        self.assertEqual(found["blendShape:member1:EyeBlendShape.eye_facial_002"]["score"], 0.0)
        self.assertAlmostEqual(found["blendShape:member1:MouthBlendShape.mouth_facial_004"]["error"], 35.8)   # closed in the editor
        self.assertAlmostEqual(found["blendShape:member1:MouthBlendShape.mouth_facial_001"]["editorConverted"], 25.0)
        self.assertEqual(dict(result.blend_coverage), {"members": 1, "gameRenderers": 2, "editorRenderers": 3,
                                                       "gameChannels": 2, "editorChannels": 2, "samples": 3})

    def test_no_editor_face_renderer_gives_no_sample_but_counts(self):
        result = comparison()
        result.compare_blend_shapes({"id": "m", "clock": {"directorTime": 1}}, self.GAME, {"slot": 1, "morphs": []}, False)
        self.assertEqual(result.items, [])
        self.assertEqual(result.blend_coverage["samples"], 0)
        self.assertEqual(result.notes["blendShapes.noFaceRenderer"], ["slot 1: game 2, editor 0"])


class PartCoverageTest(unittest.TestCase):
    def test_parts_report_their_time_span_joins_and_samples(self):
        records = [frame(0.5, 0.2, ident="f1"), frame(100.0, 0.2, ident="f2"),
                   {"kind": "full", "part": "members", "id": "p0-members-00", "clock": {"directorTime": 18.0}, "members": []},
                   {"kind": "full", "part": "members", "id": "p2-members-00", "clock": {"directorTime": 76.5}, "members": []}]
        editor_records = [{"id": "e1", "sourceRecord": "p0-members-00", "phase": -1, "clock": {"directorTime": 17.8}, "members": []}]
        trailer = {"coverage": {"directorLast": 106.666}, "passes": [
            {"pass": 3, "parts": ["renderers"], "startedAt": 80.8, "endedAt": 99.2, "complete": False, "closed": "preempted by the end pass"}]}
        game, editor = documents(records, editor_records, trailer)
        result = C.Comparison(game, editor)
        result.phase = -1
        result.items.append({"record": "p0-members-00"})
        coverage = result.part_coverage()
        members = coverage["parts"]["members"]
        self.assertEqual((members["records"], members["joined"], members["samples"]), (2, 1, 1))
        self.assertEqual((members["tFirst"], members["tLast"]), (18.0, 76.5))
        self.assertAlmostEqual(members["uncoveredTail"], 106.666 - 76.5)
        self.assertEqual(coverage["parts"]["frame"]["records"], 2)
        self.assertEqual(coverage["passes"][0]["closed"], "preempted by the end pass")

    def test_markdown_lists_the_part_coverage(self):
        game, editor = documents([frame(1.0, 0.2, ident="f1")], [], {"coverage": {"directorLast": 10.0}, "passes": []})
        report = C.Comparison(game, editor).run()
        report.pop("_worst")
        with tempfile.TemporaryDirectory() as folder:
            C.write_markdown(report, Path(folder) / "report.md")
            text = (Path(folder) / "report.md").read_text("utf-8")
        self.assertIn("### Coverage per game part", text)
        self.assertIn("| frame | 1 | 0 | 0 |", text)
        self.assertIn("Blend shapes (per member slot, joined by channel name): 0 samples", text)


if __name__ == "__main__":
    unittest.main()
