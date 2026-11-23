"""Runtime value comparison: conventions, joins, phase, hypotheses, FOV verdict, ranking and inputs."""
import copy
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mv_runtime_compare as compare  # noqa: E402
import mv_runtime_synthetic as synthetic  # noqa: E402
from mv_runtime_compare import Conventions  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mv_runtime_dump.example.json"
CAPTURE_JS = Path(__file__).resolve().parent / "mv_runtime_capture.js"
EFFECT = "/EntryPoint/Live/Stages/MainStage/Effect"
GROUND_KEY = "renderer:/EntryPoint/Live/Stages/MainStage/ground"
LAMP_KEY = f"renderer:{EFFECT}/lamp_root/lamp"
DT = 1 / 15
ASPECT = 16 / 9
BINDING = "/EntryPoint/Live/Stages/MainStage/Effect/lit_01/litC_All"
EDITOR_CONVENTIONS = {"space": "three-rh-mirror-x", "matrixLayout": "column-major", "angles": "degrees", "quaternion": "xyzw",
                      "color": "raw", "time": "director-seconds"}


# ------------------------------------------------------------------ synthetic editor document

def perspective(fov, aspect, near=0.1, far=1000.0):
    focal = 1 / math.tan(math.radians(fov) / 2)
    return [focal / aspect, 0, 0, 0, 0, focal, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0]


def quat_axis(axis, angle):
    s = math.sin(angle / 2)
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2)]


def rotation_matrix(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def view_matrix(position, q):
    """Inverse of the rigid camera pose, column-major."""
    r = rotation_matrix(q)
    t = [-sum(r[row][k] * position[row] for row in range(3)) for k in range(3)]
    return [r[0][0], r[0][1], r[0][2], 0, r[1][0], r[1][1], r[1][2], 0, r[2][0], r[2][1], r[2][2], 0, t[0], t[1], t[2], 1]


def camera_at(t, uniform=False):
    """Editor-space camera: a moving, panning shot with an animated authored FoV.

    The default motion changes speed between samples, like real camera work."""
    wobble = 0.0 if uniform else 1.0
    position = [1.5 - 0.4 * t + 0.3 * wobble * math.sin(1.3 * t), 1.2 + 0.05 * t, 8 - 0.3 * t + 0.2 * wobble * math.cos(0.8 * t)]
    yaw = 0.2 + 0.03 * t + 0.05 * wobble * math.sin(0.7 * t)
    q = compare.qnorm(compare.qmul(quat_axis([0, 1, 0], yaw), quat_axis([1, 0, 0], -0.05)))
    return position, q, 20 + 0.5 * t + wobble * math.sin(0.9 * t)


def frame_values(t, shots=2.0, uniform=False):
    position, q, fov = camera_at(t, uniform)
    start = math.floor(t / shots + 1e-9) * shots
    return {
        "directors": [{"key": "director:main", "time": t, "duration": 12}],
        "cameras": [{"key": "camera:main", "role": "main", "liveShot": True, "authoredFov": fov, "nativeLens": True,
                     "event": {"track": "cam", "label": "Camera", "clipIndex": int(start / shots), "start": start, "duration": shots},
                     "fieldOfView": fov, "aspect": ASPECT, "nearClipPlane": 0.1, "farClipPlane": 1000.0,
                     "projection": perspective(fov, ASPECT), "worldToCamera": view_matrix(position, q),
                     "transform": {"position": position, "rotation": q}}],
        "correctors": [{"key": "corrector:camera:main", "correction": 1, "aspectInput": ASPECT, "bounds": {"min": 0.75, "max": 1},
                        "nativeLens": True, "mode": {"modeled": False}}],
        "cameraWork": [{"key": "cameraWork:/EntryPoint/Live/Cameras/MainCamera", "authoredFov": fov}],
        "globals": {"global:_Beat": {"f": 1.5 * t, "from": "uBeat@penlight"}, "global:_MusicTime": {"f": t, "from": "uMusicTime@penlight"},
                    "global:_SelfTime": {"f": 0.5 * t, "from": "uSelfTime@mat_lamp (per material)", "perMaterial": True},
                    "global:_Colors": None},
        "renderSettings": {"modeled": False}, "lights": {"modeled": False},
        "members": [{"slot": 1, "memberId": 212, "costumeId": 100212001}],
        "anchors": [{"key": "anchor:member1:Head", "position": [0.03 + 0.01 * t, 1.5, 1.87]},
                    {"key": "anchor:member1:Hips", "position": [0.03, 0.95, 1.87]}, {"key": "anchor:stageOrigin", "position": [0, 0, 0]}],
    }


def transform(position, angle=0.0):
    return {"position": position, "rotation": quat_axis([0, 1, 0], angle), "lossyScale": [1, 1, 1]}


# Editor renderers: the stage ground and the performer body are flattened by the server (no
# GameObject chain, path null); the lamp keeps its animated prefab hierarchy (stage nodes).
RENDERERS = {"ground": {"key": "renderer:stage:ground", "scope": "stage", "mesh": "ground", "path": None, "pathSource": "flattened"},
             "lamp": {"key": "renderer:effect:lamp", "scope": "effect", "mesh": "lamp", "path": "fx_root/lamp_root/lamp", "pathSource": "stageNodes"},
             "body": {"key": "renderer:member1:Body", "scope": "member1", "mesh": "Body", "path": None, "pathSource": "flattened"}}
# Non-default _MainTex tiling/offset, in the editor's V-flipped form: Unity (2, 2, 0, 0.15).
GROUND_ST_EDITOR = [2, 2, 0, 1 - 2 - 0.15]


def part_values(part, t):
    if part == "renderers":
        return [dict(RENDERERS["ground"], **{"class": "MeshRenderer", "visible": True, "culled": False,
                 "transform": transform([0, 0, 0]), "materials": [{"slot": 0, "name": "bg_ground_mt", "kind": "stage"}]}),
                dict(RENDERERS["lamp"], **{"class": "MeshRenderer", "visible": True, "culled": False,
                 "transform": transform([1.2, 6.4, -3.1], 0.1 * t), "materials": [{"slot": 0, "name": "mat_lamp", "kind": "coloring"}]}),
                dict(RENDERERS["body"], **{"class": "SkinnedMeshRenderer", "visible": True, "culled": False,
                 "transform": transform([-0.03, 0, 1.87]), "materials": [{"slot": 0, "name": "ch0212_co0001_body", "kind": "member"}]})]
    if part == "materials":
        return [{"key": "material:renderer:stage:ground#0", "renderer": "renderer:stage:ground", "slot": 0, "name": "bg_ground_mt", "kind": "stage",
                 "properties": {"_TintColor": {"t": "color", "v": [0.6, 0.6, 0.7, 1], "from": "tint"},
                                "_MainTex": {"t": "tex", "v": {"name": "bg_ground_col", "width": 1024, "height": 1024}, "st": list(GROUND_ST_EDITOR),
                                             "stFrom": "mainUVTransform", "from": "mainMap"},
                                "_MainTexMipmapBias": {"t": "float", "v": 0, "from": "mipBias"}}, "unmapped": ["lightMap"], "editorOnly": []},
                {"key": "material:renderer:effect:lamp#0", "renderer": "renderer:effect:lamp", "slot": 0, "name": "mat_lamp", "kind": "coloring",
                 "properties": {"_Shift": {"t": "float", "v": 0.25 + 0.01 * t, "from": "uShift"}}, "unmapped": [], "editorOnly": []},
                {"key": "material:renderer:member1:Body#0", "renderer": "renderer:member1:Body", "slot": 0, "name": "ch0212_co0001_body",
                 "kind": "member", "properties": {"_TintColor": {"t": "color", "v": [0.4989, 0.5149, 0.649, 1], "from": "uTintColor"},
                                                  "_RimglightPower": {"t": "float", "v": 13, "from": "uRimglightPower"},
                                                  "_EmissiveTex": {"t": "tex", "v": {"name": None, "width": 1, "height": 1, "placeholder": True},
                                                                   "from": "uEmissiveTex"}},
                 "unmapped": [], "editorOnly": ["uOutlineScale"]}]
    if part == "stageNodes":
        crc = zlib.crc32(b"litC_04_All/litC_04_Yrot_Ani") & 0xFFFFFFFF
        return [{"key": f"stageNode:{BINDING}#0", "binding": BINDING, "crc": 0, "name": "litC_All", "activeSelf": True, "visible": True,
                 **transform([0, -0.4, 0.75])},
                {"key": f"stageNode:{BINDING}#{crc}", "binding": BINDING, "crc": crc, "name": "litC_04_Yrot_Ani", "activeSelf": True,
                 "visible": True, **transform([3, 1, -7.25], 0.2 * t)}]
    if part == "members":
        return [{"slot": 1, "physics": True,
                 "bones": [{"key": "member:1:Reference/Move", **transform([-0.03, 0, 1.87]), "localPosition": [-0.03, 0, 1.87],
                            "localRotation": [0, 0, 0, 1]},
                           {"key": "member:1:Reference/Move/Hips_Position/Hips", **transform([-0.03, 0.95, 1.87], 0.05 * t),
                            "localPosition": [0, 0.95, 0], "localRotation": quat_axis([0, 1, 0], 0.05 * t)}],
                 "morphs": [{"rendererKey": "renderer:member1:Body", "unit": "influence01", "weights": {"eye_close": 0.125}}]}]
    if part == "springs":
        return [{"managerKey": "springs:member1",
                 "bones": [{"key": "member:1:Reference/Move/Hips_Position/Hips/LeftSkirtB_Root_Dyna/LeftSkirtB1_Dyna",
                            "localRotation": quat_axis([1, 0, 0], 0.2 + 0.1 * math.sin(t)), "rotation": quat_axis([1, 0, 0], 0.3)}]}]
    if part == "post":
        return {"bloom": None, "dof": None, "flare": None, "applied": False, "enablePostEffect": False}
    if part == "quality":
        return {"mode": 30, "values": {"posteffect": False, "rendering_resolution": 720, "frame_rate_60fps": False, "member_swing_bone_mv": True}}
    if part == "census":
        return {"nodes": [{"key": item["key"], "kind": "renderer", "scope": item["scope"], "mesh": item["mesh"], "path": item["path"]}
                          for item in RENDERERS.values()]}
    return {"modeled": False}


def editor_doc(times=(1.0, 2.5, 3.3, 4.7, 6.1, 7.9, 9.4, 10.6), full_at=(3.3, 7.9), phases=(-1, 0, 1),
               parts=("census", "quality", "renderers", "materials", "stageNodes", "members", "post"), uniform=False, status="matched"):
    records = []
    sources = [("f%04d" % (index + 1), "frame", None, None, t) for index, t in enumerate(times)]
    sources += [(f"p{index}-{part}-00", "full", index, part, t) for index, t in enumerate(full_at) for part in parts]
    for rid, kind, pass_index, part, t0 in sources:
        for phase in phases:
            t = t0 + phase * DT
            record = {"id": f"{rid}@{phase}", "kind": kind, "sourceRecord": rid, "phase": phase,
                      "clock": {"directorTime": t, "sourceDirectorTime": t0, "phase": phase, "phaseSeconds": phase * DT, "deltaTime": DT, "rate": 30},
                      "cost": {"elapsedMs": 1}, "nonFinite": []}
            if kind == "frame":
                record.update(frame_values(t, uniform=uniform))
            else:
                record.update({"pass": pass_index, "part": part, "chunk": 0, part: part_values(part, t)})
            records.append(record)
    header = {"createdAt": "2026-11-23T00:00:00Z", "producer": {"name": "test"}, "conventions": dict(EDITOR_CONVENTIONS),
              "source": {"region": "gl", "platform": "android", "liveId": 12035, "assetId": 1203503}, "screen": {"width": 1280, "height": 720},
              "fovmod": {"aspectBounds": {"min": 0.75, "max": 1}},
              "quality": {"mode": 30, "values": part_values("quality", 0)["values"], "source": "game", "status": status,
                          "reasons": [] if status == "matched" else ["the game quality could not be applied: synthetic"]}}
    return {"schema": compare.SCHEMA, "side": "editor", "header": header, "records": records, "trailer": {"records": {}}}


def run(game, editor, **options):
    return compare.Comparison(copy.deepcopy(game), copy.deepcopy(editor), **options).run()


def frames(doc):
    return [record for record in doc["records"] if record["kind"] == "frame"]


def main_camera(record):
    return next(camera for camera in record["cameras"] if camera["key"] == "camera:main")


def top(report, type_):
    return report["ranked"]["perType"][type_][0]


# ------------------------------------------------------------------ tests

class ConventionsTest(unittest.TestCase):
    def test_involutions(self):
        p, q = [1.5, -2.0, 3.25], compare.qnorm([0.1, 0.2, -0.3, 0.9])
        self.assertEqual(Conventions.position(Conventions.position(p)), p)
        self.assertEqual(Conventions.quaternion(Conventions.quaternion(q)), q)
        m = list(range(16))
        self.assertEqual(Conventions.node_matrix(Conventions.node_matrix(m)), m)
        view = view_matrix(*camera_at(2)[:2])
        for hypothesis in Conventions.HYPOTHESES:
            self.assertEqual(Conventions.editor_view(Conventions.world_to_camera(view, hypothesis), hypothesis), view)

    def test_h180_matches_the_schema_example(self):
        # Editor view of the 12035 baseline camera at t=11.5 (schema section 10) against the game example record.
        editor_view = [0.941243277, 0.050958343, 0.333862756, 0, 7.83415388e-18, 0.988551298, -0.150885162, 0,
                       -0.337729319, 0.142019644, 0.930467263, 0, 0.946718759, -1.57333134, -9.33014399, 1]
        game = json.loads(FIXTURE.read_text("utf-8"))
        camera = main_camera(game["records"][0])
        expected = Conventions.world_to_camera(editor_view, "H180")
        self.assertLess(max(abs(a - b) for a, b in zip(expected, camera["worldToCamera"])), 1e-8)
        self.assertGreater(max(abs(a - b) for a, b in zip(Conventions.world_to_camera(editor_view, "H0"), camera["worldToCamera"])), 1)
        rig = Conventions.quaternion([0.0745397825, 0.170909886, -0.012968117, 0.982377453])
        self.assertLess(compare.qangle(rig, camera["rig"]["rotation"]), 1e-6)
        self.assertLess(compare.qangle(Conventions.camera_component_rotation(rig, "H180"), camera["transform"]["rotation"]), 1e-6)

    def test_keys_and_names(self):
        self.assertEqual(Conventions.stage_node_key(BINDING, "litC_04_All/litC_04_Yrot_Ani/litC_04_handle"),
                         f"stageNode:{BINDING}#{zlib.crc32(b'litC_04_All/litC_04_Yrot_Ani/litC_04_handle')}")
        self.assertEqual(Conventions.stage_node_key(BINDING, ""), f"stageNode:{BINDING}#0")
        self.assertEqual(Conventions.quality_key("PostEffect"), "posteffect")
        self.assertEqual(Conventions.quality_key("FrameRate60Fps"), "frame_rate_60fps")
        self.assertEqual(Conventions.quality_key("MemberSwingBone"), "member_swing_bone_mv")
        self.assertEqual(Conventions.quality_key("StageOverlayEffect"), "stage_overlay_effect")
        self.assertEqual(Conventions.quality_name("posteffect"), "PostEffect")
        self.assertEqual(Conventions.material_property("uRimglightPower"), "_RimglightPower")
        self.assertEqual(Conventions.material_property("tint"), "_TintColor")
        self.assertEqual(Conventions.material_property("mipBias"), "_MainTexMipmapBias")
        self.assertIsNone(Conventions.material_property("uOutlineScale"))
        self.assertIsNone(Conventions.material_property("lightMap"))
        self.assertEqual(Conventions.blend_weight(0.125, "influence01"), 12.5)
        self.assertEqual(Conventions.renderer_scope_mesh("renderer:member1:Body#2"), ("member1", "Body"))

    def test_quaternion_angle_is_exact_for_equal_inputs(self):
        q = compare.qnorm([0.0433749122, -0.467890086, 0.022998851, 0.882421972])
        self.assertEqual(compare.qangle(q, q), 0.0)
        self.assertEqual(compare.qangle(q, [-value for value in q]), 0.0)
        self.assertAlmostEqual(compare.qangle([0, 0, 0, 1], quat_axis([0, 1, 0], math.radians(30))), 30, places=9)

    def test_expected_keys_from_the_inventory(self):
        keys = {"tracks": [{"nativeClass": "AnimationTrack", "binding": BINDING}],
                "prefab:effect": {"fx/lit_01/litC_All/litC_04_All": {"components": ["MeshRenderer"]},
                                  "fx_spo_are_01": {"components": ["MeshRenderer", "MeshFilter"]}},
                "prefab:stage": {"bg/ground": {"components": ["MeshRenderer", "MeshFilter"]}},
                "member1": {"bones": ["", "Reference"]}, "shaderGlobalCandidates": ["_Beat"]}
        expected = compare.expected_keys(keys)
        self.assertEqual(expected["renderers"], {("effect", "lit_01/litC_All/litC_04_All"), ("effect", "fx_spo_are_01"), ("stage", "ground")})
        self.assertEqual(expected["stageNodes"], {Conventions.stage_node_key(BINDING, "litC_04_All")})
        self.assertEqual(expected["bones"], {"member:1:", "member:1:Reference"})
        self.assertEqual(expected["globals"], {"global:_Beat"})


class SelfCompareTest(unittest.TestCase):
    """(a) The editor against itself: through the inverse conventions, and as an identity join."""

    def test_mirrored_editor_has_zero_error(self):
        editor = editor_doc()
        report = run(synthetic.game_from_editor(editor), editor)
        self.assertEqual(report["summary"]["beyondTolerance"], 0)
        self.assertLess(report["summary"]["worstScore"], 1e-6)
        self.assertEqual(report["join"]["phase"]["chosen"], 0)
        self.assertEqual(report["join"]["hypothesis"]["fitted"], "H180")
        self.assertEqual(report["fov"]["verdict"], "FOVMOD_DEFAULT_NO_CORRECTION")
        self.assertEqual(report["fov"]["editor"], "EDITOR_FOV_MATCH")
        self.assertEqual(report["fov"]["authoredField"], "fieldOfView")
        self.assertIn("cameraAspect", report["fov"]["correctionInput"])
        self.assertEqual(report["join"]["missingEditorRecordsCount"], 0)
        for type_ in ("camera", "aspect", "globals", "visibility", "transforms", "materials", "post", "quality"):
            self.assertGreater(report["types"][type_]["n"], 0, type_)
        self.assertEqual(report["coverage"]["renderers"]["missingInEditorCount"], 0)
        self.assertEqual(report["coverage"]["renderers"]["extraInEditorCount"], 0)
        # The lamp joins on its GameObject path; only the flattened ground and body fall back to the mesh name.
        self.assertEqual(report["join"]["renderers"], {"path": 1, "mesh": 2})
        self.assertEqual(report["validity"]["status"], "valid")
        self.assertEqual(report["coverage"]["ambiguousRenderersCount"], 0)

    def test_identity_join_is_exactly_zero(self):
        editor = editor_doc()
        report = run(editor, editor)
        self.assertEqual(report["join"]["mode"], "identity")
        self.assertEqual(report["summary"]["worstScore"], 0.0)
        self.assertTrue(all(item["error"] == 0 for item in report["ranked"]["overall"]))
        self.assertEqual(report["join"]["joinedRecords"], len(editor["records"]))


class PerturbedTest(unittest.TestCase):
    """(b) Known discrepancies are ranked under their own asset type."""

    def setUp(self):
        self.editor = editor_doc()
        game = synthetic.game_from_editor(self.editor)
        for record in frames(game)[1:4]:
            camera = main_camera(record)
            camera["fieldOfView"] += 0.5
            camera["projection"] = perspective(camera["fieldOfView"], camera["aspect"])
            record["cameraWork"][0]["fields"]["fieldOfView"]["v"] += 0.5
        for record in frames(game):
            record["globals"]["global:_Beat"]["f"] += 0.01
        for record in game["records"]:
            if record.get("part") == "stageNodes" and record["id"].startswith("p0"):
                record["stageNodes"][1]["position"][0] += 0.02
            if record.get("part") == "materials" and record["id"].startswith("p0"):
                record["materials"][0]["properties"]["_TintColor"]["v"][1] += 0.05
            if record.get("part") == "renderers":
                record["renderers"] = [item for item in record["renderers"] if item["key"] != LAMP_KEY]
                record["renderers"].append({"key": f"renderer:{EFFECT}/ghost_root/ghost", "path": f"{EFFECT}/ghost_root/ghost", "scope": "effect",
                                            "mesh": "ghost", "layer": 0, "enabled": True, "activeInHierarchy": True,
                                            "transform": transform([0, 0, 0]), "materials": []})
            if record.get("part") == "post":
                record["post"]["enablePostEffect"] = True
        self.report = run(game, self.editor)

    def test_each_discrepancy_ranks_under_its_type(self):
        report = self.report
        self.assertEqual((top(report, "camera")["metric"], top(report, "camera")["key"]), ("fovAbsDeg", "camera:main"))
        self.assertAlmostEqual(top(report, "camera")["error"], 0.5, places=9)
        self.assertEqual(top(report, "globals")["key"], "global:_Beat")
        self.assertEqual((top(report, "materials")["key"], top(report, "materials")["field"]), (f"material:{GROUND_KEY}#0", "_TintColor"))
        self.assertAlmostEqual(top(report, "materials")["score"], 0.05 * 512, places=6)
        crc = zlib.crc32(b"litC_04_All/litC_04_Yrot_Ani") & 0xFFFFFFFF
        self.assertEqual((top(report, "transforms")["metric"], top(report, "transforms")["key"]), ("stageNodePositionM", f"stageNode:{BINDING}#{crc}"))
        self.assertEqual((top(report, "post")["metric"], top(report, "post")["score"]), ("postEnabled", compare.EXACT_SCORE))
        camera = [group for group in report["_worst"] if group["type"] == "camera"]
        self.assertEqual({record for group in camera for record in group["records"]}, {"f0002", "f0003", "f0004"})
        self.assertEqual({group["metric"] for group in camera}, {"fovAbsDeg", "projectionMaxRel", "anchorNdcMax", "anchorNdcCameraOnly"})
        fov = next(group for group in camera if group["metric"] == "fovAbsDeg")
        self.assertEqual((fov["beyond"], fov["count"], fov["tFirst"], fov["tLast"]), (3, 8, 1.0, 10.6))
        self.assertEqual(report["types"]["transforms"]["beyondTolerance"], 1)
        self.assertEqual(report["types"]["visibility"]["beyondTolerance"], 0)
        # Overall order follows error / tolerance: post (exact), fov 500, _Beat 100, colour 25.6, stage node 20.
        order = []
        for item in report["ranked"]["overall"]:
            if item["score"] > 1 and item["type"] not in order:
                order.append(item["type"])
        self.assertEqual(order, ["post", "camera", "globals", "materials", "transforms"])

    def test_coverage_lists_missing_and_extra_renderers(self):
        coverage = self.report["coverage"]["renderers"]
        self.assertEqual(coverage["missingInEditor"], ["effect:ghost_root/ghost"])
        self.assertEqual(coverage["extraInEditor"], ["renderer:effect:lamp"])

    def test_editor_fov_mismatch_is_separate_from_the_fovmod_verdict(self):
        self.assertEqual(self.report["fov"]["verdict"], "FOVMOD_DEFAULT_NO_CORRECTION")
        self.assertEqual(self.report["fov"]["editor"], "EDITOR_FOV_MISMATCH")


class FovVerdictTest(unittest.TestCase):
    def corrected(self, form, bounds=(0.9, 1.0), aspect=1.0):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for block in (game["header"]["fovmod"], game["trailer"]["fovmodEnd"]):
            block["sfovrw22"] = {"min": bounds[0], "max": bounds[1]}
        game["header"]["fovmod"]["decoded"] = {"min": bounds[0], "max": bounds[1]}
        for record in frames(game):
            camera, authored = main_camera(record), record["cameraWork"][0]["fields"]["fieldOfView"]["v"]
            correction = min(bounds[1], max(bounds[0], aspect / ASPECT))
            record["correctors"][0]["correction"] = correction
            camera["aspect"] = aspect
            camera["fieldOfView"] = authored / correction if form == "linear" else \
                math.degrees(2 * math.atan(math.tan(math.radians(authored) / 2) / correction))
            camera["projection"] = perspective(camera["fieldOfView"], aspect)
        return run(game, editor)["fov"]

    def test_linear_correction(self):
        fov = self.corrected("linear")
        self.assertEqual(fov["verdict"], "FOVMOD_CORRECTION_ACTIVE_LINEAR")
        self.assertEqual(fov["authoredField"], "fieldOfView")
        self.assertEqual(fov["correctionInput"], ["cameraAspect"])
        self.assertAlmostEqual(fov["fovGameOverAuthored"]["p50"], 1 / 0.9, places=9)
        self.assertEqual(fov["editor"], "EDITOR_FOV_MISMATCH")
        self.assertTrue(fov["discriminates"])

    def test_tan_correction(self):
        self.assertEqual(self.corrected("tan")["verdict"], "FOVMOD_CORRECTION_ACTIVE_TAN")

    def test_nondefault_bounds_inactive_at_16_9(self):
        fov = self.corrected("linear", bounds=(0.5, 1.0), aspect=ASPECT)
        self.assertEqual(fov["verdict"], "FOVMOD_NONDEFAULT_INACTIVE")
        self.assertFalse(fov["discriminates"])

    def test_unexplained(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in frames(game):
            main_camera(record)["fieldOfView"] += 3
        self.assertEqual(run(game, editor)["fov"]["verdict"], "RUNTIME_FOV_UNEXPLAINED")


class TimingTest(unittest.TestCase):
    def test_phase_calibration_detects_a_one_frame_shift(self):
        for uniform in (False, True):
            editor = editor_doc(uniform=uniform)
            for phase in (-1, 1):
                report = run(synthetic.game_from_editor(editor, source_phase=phase), editor)
                self.assertEqual(report["join"]["phase"]["chosen"], phase, (uniform, phase))
                self.assertEqual(report["join"]["phase"]["histogram"][str(phase)], 8)
                self.assertEqual(report["summary"]["beyondTolerance"], 0)
            # Uniform speed leaves the bias-free residual flat; the per-record mode decides.
            self.assertEqual(report["join"]["phase"]["method"].startswith("mode"), uniform)

    def test_phase_override(self):
        editor = editor_doc()
        report = run(synthetic.game_from_editor(editor), editor, phase="1")
        self.assertEqual(report["join"]["phase"]["chosen"], 1)
        self.assertEqual(report["join"]["phase"]["calibrated"], 0)
        self.assertGreater(report["summary"]["beyondTolerance"], 0)

    def test_constant_camera_offset_does_not_move_the_phase(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in frames(game):
            camera = main_camera(record)
            for holder in (camera["rig"], camera["transform"]):
                holder["position"][0] += 0.1
        report = run(game, editor)
        self.assertEqual(report["join"]["phase"]["chosen"], 0)
        self.assertTrue(report["join"]["phase"]["method"].startswith("bias-invariant"))
        self.assertAlmostEqual(report["types"]["camera"]["metrics"]["rigPositionM"]["max"], 0.1, places=9)

    def test_h0_hypothesis_is_detected(self):
        editor = editor_doc()
        report = run(synthetic.game_from_editor(editor, hypothesis="H0"), editor)
        self.assertEqual(report["join"]["hypothesis"]["fitted"], "H0")
        self.assertEqual(report["summary"]["beyondTolerance"], 0)

    def test_record_at_a_cut_is_not_ranked(self):
        editor = editor_doc(times=(1.0, 2.5, 3.3, 4.03, 6.1, 7.9))
        game = synthetic.game_from_editor(editor)
        cut = next(record for record in frames(game) if record["id"] == "f0004")
        main_camera(cut)["fieldOfView"] += 5
        report = run(game, editor)
        self.assertEqual(report["summary"]["beyondTolerance"], 0)
        self.assertGreater(report["types"]["camera"]["nearCut"], 0)
        self.assertTrue(all(item["record"] != "f0004" for item in report["ranked"]["overall"] if item["type"] == "camera"))


class ToleranceTest(unittest.TestCase):
    """(f) Tolerance boundaries are inclusive."""

    def beyond(self, tolerance):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in frames(game) + frames(editor):
            for key in ("global:_Beat", "global:_MusicTime"):
                record["globals"][key]["f"] = 2.0
        frames(game)[0]["globals"]["global:_Beat"]["f"] = 2.25
        return run(game, editor, tolerances={"globalAbs": tolerance})["summary"]["beyondTolerance"]

    def test_inclusive_boundary(self):
        self.assertEqual(self.beyond(0.25), 0)
        self.assertEqual(self.beyond(0.2499), 1)


class InputTest(unittest.TestCase):
    """(g) rejections and (h) job-log input."""

    def write(self, doc, name):
        path = Path(self.directory.name) / name
        synthetic.write_dump(doc, path)
        return path

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.directory.cleanup()

    def test_example_fixture_loads(self):
        doc = compare.load_dump(FIXTURE)
        self.assertEqual(doc["side"], "game")
        self.assertEqual(len(doc["records"]), 11)

    def test_unknown_schema_is_refused(self):
        doc = json.loads(FIXTURE.read_text("utf-8"))
        doc["schema"] = "sifas-mv-runtime-dump/2"
        with self.assertRaisesRegex(compare.DumpError, "Unknown dump schema"):
            compare.load_dump(self.write(doc, "v2.json"))

    def test_row_major_projection_is_refused(self):
        doc = json.loads(FIXTURE.read_text("utf-8"))
        camera = main_camera(doc["records"][0])
        camera["projection"] = [camera["projection"][row * 4 + column] for column in range(4) for row in range(4)]
        with self.assertRaisesRegex(compare.DumpError, "column-major perspective"):
            compare.load_dump(self.write(doc, "rows.json.gz"))

    def test_wrong_space_is_refused(self):
        doc = json.loads(FIXTURE.read_text("utf-8"))
        doc["header"]["conventions"]["space"] = "three-rh-mirror-x"
        with self.assertRaisesRegex(compare.DumpError, "must declare space"):
            compare.load_dump(self.write(doc, "space.json"))

    def test_game_document_is_not_an_editor_document(self):
        doc = compare.load_dump(FIXTURE)
        with self.assertRaisesRegex(compare.DumpError, "editor dump"):
            compare.Comparison(doc, doc)

    def test_job_log_equals_the_gzip_document(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        gz = self.write(game, "game.json.gz")
        log = Path(self.directory.name) / "job.log"
        log.write_text("2026-11-23T12:00:00.0000000Z unrelated line\n" + synthetic.job_log(compare.load_dump(gz)), "utf-8")
        from_log, from_gz = compare.load_dump(log), compare.load_dump(gz)
        self.assertEqual(from_log["records"], from_gz["records"])
        self.assertEqual(from_log["header"], from_gz["header"])
        editor_path = self.write(editor, "editor.json.gz")
        out_log, out_gz = Path(self.directory.name) / "log", Path(self.directory.name) / "gz"
        a = compare.compare_files(log, editor_path, out_log)
        b = compare.compare_files(gz, editor_path, out_gz)
        self.assertEqual(a["summary"], b["summary"])
        self.assertTrue((out_log / "report.md").read_text("utf-8").startswith("# MV runtime value comparison"))
        self.assertTrue((out_log / "worst.csv").exists())

    def test_tampered_log_is_refused(self):
        game = synthetic.game_from_editor(editor_doc())
        text = synthetic.job_log(game)
        lines = text.splitlines()
        index = next(i for i, line in enumerate(lines) if line.endswith("@@RTDUMP-BEGIN rtdump-core")) + 1
        lines[index] = lines[index][:-4] + ("AAAA" if not lines[index].endswith("AAAA") else "BBBB")
        log = Path(self.directory.name) / "bad.log"
        log.write_text("\n".join(lines) + "\n", "utf-8")
        with self.assertRaises((compare.DumpError, OSError, EOFError, zlib.error, ValueError)):
            compare.load_dump(log)

    def test_cli_regression_exit_code(self):
        editor = editor_doc()
        editor_path = self.write(editor, "editor.json.gz")
        clean = self.write(synthetic.game_from_editor(editor), "clean.json.gz")
        worse_doc = synthetic.game_from_editor(editor)
        for record in frames(worse_doc):
            main_camera(record)["fieldOfView"] += 1
        worse = self.write(worse_doc, "worse.json.gz")
        base = Path(self.directory.name) / "base"
        self.assertEqual(compare.main(["--game", str(clean), "--editor", str(editor_path), "--out", str(base)]), 0)
        self.assertEqual(compare.main(["--game", str(worse), "--editor", str(editor_path), "--out", str(Path(self.directory.name) / "new"),
                                       "--baseline", str(base / "report.json"), "--fail-on-regression"]), 2)


class SyntheticTest(unittest.TestCase):
    def test_skeleton_is_a_valid_game_document(self):
        doc = synthetic.skeleton([14.85, 35.2167, 50.3333], [14.85], ["renderers", "members"])
        with tempfile.TemporaryDirectory() as directory:
            path = synthetic.write_dump(doc, Path(directory) / "skeleton.json.gz")
            loaded = compare.load_dump(path)
            self.assertEqual(loaded["side"], "game")
            self.assertEqual([record["id"] for record in loaded["records"]], ["f0001", "p0-renderers-00", "p0-members-00", "f0002", "f0003"])
            with gzip.open(path) as handle:
                self.assertEqual(json.load(handle)["schema"], compare.SCHEMA)

    def test_perturb_manifest(self):
        doc, manifest = synthetic.perturb(synthetic.game_from_editor(editor_doc()), fov=2, camera_move=0.1, material_delta=0.05, hide=True)
        self.assertEqual(manifest["expected"]["camera"], ["fovAbsDeg", "rigPositionM"])
        self.assertEqual(manifest["hidden"], LAMP_KEY)
        self.assertEqual(manifest["material"]["key"], f"material:{GROUND_KEY}#0")
        report = run(doc, editor_doc())
        self.assertEqual(top(report, "visibility")["key"], LAMP_KEY)
        self.assertEqual(top(report, "materials")["key"], f"material:{GROUND_KEY}#0")
        metrics = report["types"]["camera"]["metrics"]
        self.assertAlmostEqual(metrics["fovAbsDeg"]["max"], 2, places=9)
        self.assertAlmostEqual(metrics["rigPositionM"]["max"], 0.1, places=9)
        self.assertEqual(metrics["rigRotationDeg"]["max"], 0)



# ------------------------------------------------------------------ review fixes

def records_of(doc, part):
    return [record for record in doc["records"] if record.get("part") == part]


def items_of(report, type_, metric=None):
    return [group for group in report["ranked"]["perType"][type_] if metric is None or group["metric"] == metric]


class ConventionsReviewTest(unittest.TestCase):
    def test_texture_st_v_flip_is_its_own_inverse(self):
        # The three non-default _MainTex transforms of the 12035 effect bundle (Unity form).
        for unity, editor in (([2, 2, 0, 0.15], [2, 2, 0, -1.15]), ([1, 1, 0, -0.15], [1, 1, 0, 0.15]), ([3, 3, 0, 0], [3, 3, 0, -2])):
            converted = Conventions.texture_st(editor)
            self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(converted, unity)), (editor, converted))
            self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(Conventions.texture_st(converted), editor)))
        self.assertEqual(Conventions.texture_st([1, 1, 0, 0]), [1, 1, 0, 0], "the default transform is unchanged")

    def test_object_names_drop_clone_and_instance_suffixes(self):
        self.assertEqual(Conventions.object_name("bg0006_01_stageB_opa_mt(Clone)"), "bg0006_01_stageB_opa_mt")
        self.assertEqual(Conventions.object_name("mat (Instance)"), "mat")
        self.assertEqual(Conventions.object_name("mat(Clone) (Instance)"), "mat")
        self.assertEqual(Conventions.object_name("mat(Clone)(Clone)"), "mat")
        self.assertEqual(Conventions.object_name("Clone (x)"), "Clone (x)")
        self.assertEqual(compare.strip_instance("tex(Clone)"), "tex")

    def test_quality_values_compare_bool_and_flags(self):
        self.assertTrue(Conventions.same_quality(1, True))
        self.assertTrue(Conventions.same_quality(False, 0))
        self.assertFalse(Conventions.same_quality(2, True))
        self.assertFalse(Conventions.same_quality(720, 1080))
        self.assertEqual(Conventions.quality_key("SetId"), "set_id")
        self.assertIn("set_id", Conventions.QUALITY_IGNORED)

    def test_game_relative_paths_per_scope(self):
        roots = {1: "/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member"}
        self.assertEqual(Conventions.game_relative_path(f"{EFFECT}/dis_01/main_01", "effect"), "dis_01/main_01")
        self.assertEqual(Conventions.game_relative_path("/EntryPoint/Live/Stages/MainStage/Model/bg0006_01_mdl/ground", "stage"),
                         "Model/bg0006_01_mdl/ground")
        self.assertEqual(Conventions.game_relative_path(roots[1] + "/Body", "member1", roots), "Body")
        self.assertEqual(Conventions.game_relative_path("/EntryPoint/Live/Members/Member2/Model/x/Body", "member2", roots), "Model/x/Body")
        self.assertEqual(Conventions.editor_relative_path("bg0006_01_fx_so2035_ex/dis_01/main_01"), "dis_01/main_01")
        self.assertIsNone(Conventions.editor_relative_path(None))
        self.assertTrue(Conventions.path_suffix("Model/bg0006_01_mdl/ground", "ground"))
        self.assertFalse(Conventions.path_suffix("Model/bg0006_01_mdl/underground", "ground"))
        self.assertFalse(Conventions.path_suffix("ground", ""))

    def test_culling_bit_and_spring_keys(self):
        self.assertTrue(Conventions.culling_bit(-1, 30))
        self.assertFalse(Conventions.culling_bit(-1 ^ (1 << 30), 30))
        self.assertTrue(Conventions.culling_bit(0xFFFFFFFF, 31), "an unsigned mask works too")
        self.assertIsNone(Conventions.culling_bit(-1, None))
        self.assertIsNone(Conventions.culling_bit(None, 3))
        roots = {1: "/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member"}
        self.assertEqual(Conventions.spring_bone_key(roots[1] + "/Reference/Move/X_Dyna", roots), ("member:1:Reference/Move/X_Dyna", None))
        self.assertEqual(Conventions.spring_bone_key("/EntryPoint/Live/Members/Member2/Model/r/X_Dyna", roots), (None, (2, "Model/r/X_Dyna")))
        self.assertEqual(Conventions.spring_bone_key("/EntryPoint/Live/Props/X_Dyna", roots), (None, None))

    def test_capture_runner_uses_the_same_quality_table(self):
        text = CAPTURE_JS.read_text("utf-8")
        block = re.search(r"const QUALITY_NAMES = Object\.freeze\(\{(.*?)\}\);", text, re.S).group(1)
        table = dict(re.findall(r"(\w+): '([a-z0-9_]+)'", block))
        self.assertEqual(table, Conventions.QUALITY)
        node = shutil.which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)
        if not node:
            self.skipTest("node is not installed")
        names = ["PostEffect", "MemberSwingBone", "StageCubemap", "HDRMode", "MovieLive", "RefreshRateMode", "SetId", "ABCTest", "Quality"]
        env = dict(os.environ)
        env.setdefault("NODE_PATH", "/usr/local/lib/node_modules_global")
        script = f"const m = require({json.dumps(str(CAPTURE_JS))}); console.log(JSON.stringify({json.dumps(names)}.map(m.snakeCase)));"
        result = subprocess.run([node, "-e", script], capture_output=True, text=True, env=env)
        if result.returncode != 0:
            self.skipTest(f"the capture runner cannot be loaded here: {result.stderr.strip()[:200]}")
        self.assertEqual(json.loads(result.stdout), [Conventions.quality_key(name) for name in names])


class QualityValidityTest(unittest.TestCase):
    """BLOCKER: the editor must run at the quality the game ran (contract 5)."""

    def test_matching_quality_is_valid(self):
        report = run(synthetic.game_from_editor(editor_doc()), editor_doc())
        self.assertEqual(report["validity"]["status"], "valid")
        self.assertGreater(report["validity"]["quality"]["compared"], 0)

    def test_a_remaining_difference_marks_the_report_invalid(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        game["header"]["quality"]["values"]["PostEffect"] = True
        report = run(game, editor)
        self.assertEqual(report["validity"]["status"], "invalid:quality")
        self.assertEqual([item["game"] for item in report["validity"]["quality"]["differences"]], ["PostEffect"])
        self.assertEqual(report["summary"]["validity"], "invalid:quality")

    def test_unknown_game_quality_is_invalid(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        game["header"]["quality"]["values"] = {}
        report = run(game, editor)
        self.assertEqual(report["validity"]["status"], "invalid:quality")
        self.assertIn("no quality values", report["validity"]["reasons"][0])

    def test_editor_capture_failure_is_invalid(self):
        editor = editor_doc(status="invalid:quality")
        report = run(synthetic.game_from_editor(editor), editor)
        self.assertEqual(report["validity"]["status"], "invalid:quality")
        self.assertTrue(report["validity"]["reasons"][0].startswith("editor capture:"))

    def test_raw_flags_and_ignored_preset_id(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        values = game["header"]["quality"]["values"]
        values["PostEffect"], values["MemberSwingBone"], values["SetId"] = 0, 1, 99
        values["Quality"] = {"v": 30, "n": None}
        self.assertEqual(run(game, editor)["validity"]["status"], "valid")

    def test_identity_is_valid_and_cli_require_valid_exits_3(self):
        editor = editor_doc()
        self.assertEqual(run(editor, editor)["validity"]["status"], "valid")
        with tempfile.TemporaryDirectory() as directory:
            game = synthetic.game_from_editor(editor)
            game["header"]["quality"]["values"]["RenderingResolution"] = 1080
            game_path = synthetic.write_dump(game, Path(directory) / "game.json.gz")
            editor_path = synthetic.write_dump(editor, Path(directory) / "editor.json.gz")
            args = ["--game", str(game_path), "--editor", str(editor_path), "--out", str(Path(directory) / "out")]
            self.assertEqual(compare.main(args), 0)
            self.assertEqual(compare.main(args + ["--require-valid"]), 3)
            self.assertIn("INVALID:QUALITY", (Path(directory) / "out" / "report.md").read_text("utf-8"))


class TextureStTest(unittest.TestCase):
    """The editor's mainUVTransform is V-flipped; Unity reports GetTextureScale/Offset as is."""

    def test_non_default_st_has_zero_error(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        unity = records_of(game, "materials")[0]["materials"][0]["properties"]["_MainTex"]["st"]
        self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(unity, [2, 2, 0, 0.15])), unity)
        st = run(game, editor)["types"]["materials"]["metrics"]["textureStAbs"]
        self.assertGreater(st["n"], 0)
        self.assertLess(st["max"], 1e-12)

    def test_unflipped_comparison_would_score_a_false_discrepancy(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in records_of(editor, "materials"):
            record["materials"][0]["properties"]["_MainTex"]["stFrom"] = "uvTransformWithoutFlip"
        report = run(game, editor)
        top_st = next(group for group in report["_worst"] if group["metric"] == "textureStAbs")
        self.assertAlmostEqual(top_st["error"], 1.3, places=9)
        self.assertGreater(top_st["score"], 1e5)

    def test_a_real_st_difference_is_still_reported(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in records_of(game, "materials"):
            record["materials"][0]["properties"]["_MainTex"]["st"][3] += 0.01
        group = next(group for group in run(game, editor)["_worst"] if group["metric"] == "textureStAbs")
        self.assertAlmostEqual(group["error"], 0.01, places=9)


class GlobalsReviewTest(unittest.TestCase):
    def test_per_material_self_time_is_a_note_not_a_global(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in frames(game):
            record["globals"]["global:_SelfTime"] = {"f": 0.0, "v": [0, 0, 0, 0]}
        report = run(game, editor)
        self.assertFalse([group for group in report["ranked"]["perType"]["globals"] if group["key"] == "global:_SelfTime"])
        self.assertEqual(report["types"]["globals"]["beyondTolerance"], 0)
        self.assertIn("globals.perMaterial", report["notes"])


class NameSuffixTest(unittest.TestCase):
    def test_clone_material_names_join(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in records_of(game, "renderers"):
            for renderer in record["renderers"]:
                for slot in renderer["materials"]:
                    slot["name"] += "(Clone)"
        report = run(game, editor)
        self.assertEqual(report["types"]["materials"]["metrics"]["slotName"]["max"], 0)
        self.assertEqual(report["summary"]["beyondTolerance"], 0)


class GroupingTest(unittest.TestCase):
    """Ranking and regressions work on distinct (type, key, metric) defects."""

    def test_one_constant_defect_is_one_ranked_group(self):
        editor = editor_doc(times=tuple(0.5 + 0.4 * index for index in range(25)))
        game = synthetic.game_from_editor(editor)
        for record in frames(game):
            camera = main_camera(record)
            for holder in (camera["rig"], camera["transform"]):
                holder["position"][0] += 0.1
        report = run(game, editor)
        overall = report["ranked"]["overall"]
        idents = [(group["type"], group["key"], group["metric"]) for group in overall]
        self.assertEqual(len(idents), len(set(idents)), "each defect appears once in the top 25")
        rig = next(group for group in overall if group["metric"] == "rigPositionM")
        self.assertEqual((rig["count"], rig["beyond"], rig["tFirst"]), (25, 25, 0.5))
        self.assertAlmostEqual(rig["tLast"], 0.5 + 0.4 * 24, places=9)
        self.assertEqual(report["types"]["camera"]["beyondSamples"], sum(group["beyond"] for group in report["_worst"] if group["type"] == "camera"))

    def write(self, directory, name, doc):
        return synthetic.write_dump(doc, Path(directory) / name)

    def test_a_longer_run_of_the_same_defect_is_not_a_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            def perturbed(editor):
                game = synthetic.game_from_editor(editor)
                for record in frames(game):
                    main_camera(record)["fieldOfView"] += 1
                return game
            short_editor, long_editor = editor_doc(), editor_doc(times=tuple(0.5 + 0.3 * index for index in range(30)))
            base = Path(directory) / "base"
            self.assertEqual(compare.main(["--game", str(self.write(directory, "short.json.gz", perturbed(short_editor))),
                                           "--editor", str(self.write(directory, "short-editor.json.gz", short_editor)), "--out", str(base)]), 0)
            long_editor_path = self.write(directory, "long-editor.json.gz", long_editor)

            def against_base(game_name, game_doc, out):
                return compare.main(["--game", str(self.write(directory, game_name, game_doc)), "--editor", str(long_editor_path),
                                     "--out", str(Path(directory) / out), "--baseline", str(base / "report.json"), "--fail-on-regression"])
            self.assertEqual(against_base("long.json.gz", perturbed(long_editor), "long"), 0, "more samples of the same defect")
            report = json.loads((Path(directory) / "long" / "report.json").read_text("utf-8"))
            self.assertEqual(report["baseline"]["regressions"], [])
            self.assertGreater(report["summary"]["beyondSamples"], json.loads((base / "report.json").read_text("utf-8"))["summary"]["beyondSamples"])
            new_defect = perturbed(long_editor)
            for record in frames(new_defect):
                record["globals"]["global:_Beat"]["f"] += 0.5
            self.assertEqual(against_base("new.json.gz", new_defect, "new"), 2, "a new (type, key, metric) defect regresses")
            regressions = json.loads((Path(directory) / "new" / "report.json").read_text("utf-8"))["baseline"]["regressions"]
            self.assertEqual(len(regressions), 1)
            self.assertIn("global:_Beat", regressions[0])

    def test_old_baseline_without_groups_fails_loudly(self):
        report = {"groups": {"beyond": []}}
        self.assertIn("regenerate", compare.regressions(report, {"schema": "sifas-mv-runtime-compare/1", "summary": {}})[0])

    def test_placeholder_textures_are_notes_not_exact_mismatches(self):
        editor = editor_doc()
        game = synthetic.game_from_editor(editor)
        for record in records_of(game, "materials"):
            for material in record["materials"]:
                if "_EmissiveTex" in material["properties"]:
                    material["properties"]["_EmissiveTex"]["v"] = {"name": "ch0212_co0001_emi", "width": 512, "height": 512}
        report = run(game, editor)
        self.assertEqual(report["summary"]["beyondTolerance"], 0)
        self.assertIn("materials.placeholderTextures", report["notes"])
        self.assertTrue(all(group["field"] != "_EmissiveTex" for group in report["ranked"]["perType"]["materials"]))


class RendererJoinTest(unittest.TestCase):
    """Contract 4: renderers join on (scope, GameObject path); the mesh name is only a check."""

    def docs(self):
        editor = editor_doc(full_at=(3.3,), parts=("census", "quality", "renderers"))
        shared = [("renderer:effect:ver_color_01", "fx_root/ver/ver_color_01", "ver_color_01"),
                  ("renderer:effect:ver_color_01#2", "fx_root/ver/ver_color_02", "ver_color_01"),
                  ("renderer:effect:Plane", "fx_root/flare/flares_01", "Plane"),
                  ("renderer:effect:Plane#2", "fx_root/flare/flares_02", "Plane"),
                  ("renderer:effect:default", None, "default"), ("renderer:effect:default#2", None, "default")]
        for record in editor["records"]:
            if record.get("part") == "renderers":
                for key, path, mesh in shared:
                    record["renderers"].append({"key": key, "scope": "effect", "mesh": mesh, "path": path, "visible": True, "culled": False,
                                                "transform": transform([0, 1, 2]), "materials": []})
        game = synthetic.game_from_editor(editor)
        for record in records_of(game, "renderers"):
            for renderer in record["renderers"]:
                if renderer["mesh"] == "Plane":
                    renderer["mesh"] = "Quad"  # Unity's built-in quad; the editor names its plane "Plane"
        return game, editor

    def test_shared_mesh_objects_join_by_path(self):
        game, editor = self.docs()
        comparison = compare.Comparison(copy.deepcopy(game), copy.deepcopy(editor))
        report = comparison.run()
        joins = {key: value for key, value in comparison.joins.items()}
        self.assertEqual(joins[f"renderer:{EFFECT}/ver/ver_color_01"], ("renderer:effect:ver_color_01", "path"))
        self.assertEqual(joins[f"renderer:{EFFECT}/ver/ver_color_02"], ("renderer:effect:ver_color_01#2", "path"))
        self.assertEqual(joins[f"renderer:{EFFECT}/flare/flares_02"], ("renderer:effect:Plane#2", "path"))
        self.assertEqual(joins[GROUND_KEY], ("renderer:stage:ground", "mesh"))
        # Two flattened editor renderers with one mesh name cannot be told apart.
        self.assertEqual(report["coverage"]["ambiguousRenderersCount"], 2)
        self.assertEqual(report["coverage"]["renderers"]["extraInEditorCount"], 0)
        self.assertEqual(report["summary"]["beyondTolerance"], 0)
        checks = [entry["value"] for entry in report["notes"]["renderers.meshCheck"]["unique"]]
        self.assertTrue(any("'Quad'" in value and "'Plane'" in value for value in checks), checks)

    def test_path_suffix_joins_through_scope_root_containers(self):
        game, editor = self.docs()
        for record in records_of(game, "renderers"):
            for renderer in record["renderers"]:
                if renderer["path"].startswith(EFFECT + "/ver/"):
                    renderer["path"] = renderer["path"].replace(EFFECT + "/", EFFECT + "/bg0006_01_fx(Clone)/")
                    renderer["key"] = "renderer:" + renderer["path"]
        comparison = compare.Comparison(game, editor)
        comparison.run()
        self.assertEqual(comparison.joins[f"renderer:{EFFECT}/bg0006_01_fx(Clone)/ver/ver_color_02"], ("renderer:effect:ver_color_01#2", "pathSuffix"))

    def test_mesh_never_overrides_a_path(self):
        game, editor = self.docs()
        for record in records_of(game, "renderers"):
            record["renderers"].append({"key": f"renderer:{EFFECT}/elsewhere/ver_color_09", "path": f"{EFFECT}/elsewhere/ver_color_09",
                                        "scope": "effect", "mesh": "ver_color_01", "layer": 0, "enabled": True, "activeInHierarchy": True,
                                        "transform": transform([0, 0, 0]), "materials": []})
        comparison = compare.Comparison(game, editor)
        report = comparison.run()
        self.assertEqual(comparison.joins[f"renderer:{EFFECT}/elsewhere/ver_color_09"], (None, "none"))
        self.assertIn("effect:elsewhere/ver_color_09", report["coverage"]["renderers"]["missingInEditor"])


class MemberVisibilityTest(unittest.TestCase):
    """Contract 1: the game culls members through the layer and the main camera culling mask."""

    def docs(self, culled):
        editor = editor_doc(full_at=(3.3,), parts=("census", "quality", "renderers"))
        for record in records_of(editor, "renderers"):
            for renderer in record["renderers"]:
                if renderer["scope"] == "member1":
                    renderer["culled"] = culled
        return synthetic.game_from_editor(editor), editor

    def test_culled_member_agrees(self):
        game, editor = self.docs(True)
        body = next(renderer for record in records_of(game, "renderers") for renderer in record["renderers"] if renderer["scope"] == "member1")
        self.assertEqual((body["enabled"], body["activeInHierarchy"], body["layer"]), (True, True, synthetic.INVISIBLE_LAYER))
        report = run(game, editor)
        self.assertEqual(report["types"]["visibility"]["beyondTolerance"], 0)
        self.assertGreater(report["types"]["visibility"]["n"], 0)

    def test_culler_disagreement_is_an_exact_mismatch(self):
        game, editor = self.docs(True)
        for record in records_of(game, "renderers"):
            for renderer in record["renderers"]:
                renderer["layer"] = 0  # the game never moved the member to the Invisible layer
        report = run(game, editor)
        top_visibility = top(report, "visibility")
        self.assertEqual((top_visibility["key"], top_visibility["score"]), ("renderer:/EntryPoint/Live/Members/Member1/Model/synthetic_member/Body",
                                                                            compare.EXACT_SCORE))
        self.assertIn("culled=True", top_visibility["field"])

    def test_missing_layer_falls_back_to_enabled_and_active(self):
        game, editor = self.docs(False)
        for record in records_of(game, "renderers"):
            for renderer in record["renderers"]:
                del renderer["layer"]
        report = run(game, editor)
        self.assertEqual(report["types"]["visibility"]["beyondTolerance"], 0)
        self.assertIn("visibility.layerUnknown", report["notes"])


class SpringJoinTest(unittest.TestCase):
    def docs(self):
        editor = editor_doc(full_at=(3.3,), parts=("census", "quality", "members", "springs"))
        return synthetic.game_from_editor(editor), editor

    def test_springs_join_below_the_member_root(self):
        game, editor = self.docs()
        bone = records_of(game, "springs")[0]["springs"][0]["bones"][0]
        self.assertTrue(bone["key"].startswith("spring:/EntryPoint/Live/Members/Member1/"))
        report = run(game, editor)
        self.assertGreater(report["types"]["springs"]["n"], 0)
        self.assertLess(report["types"]["springs"]["metrics"]["springLocalRotationDeg"]["max"], 1e-6)

    def test_springs_join_without_a_member_root(self):
        game, editor = self.docs()
        for record in records_of(game, "members"):
            for member in record["members"]:
                del member["rootPath"]
        report = run(game, editor)
        self.assertGreater(report["types"]["springs"]["n"], 0)


class ProbeBlobTest(unittest.TestCase):
    def test_probe_blob_is_kept_aside(self):
        game = synthetic.game_from_editor(editor_doc())
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "job.log"
            log.write_text(synthetic.job_log(game), "utf-8")
            loaded = compare.load_dump(log)
            self.assertEqual(loaded["_source"]["auxiliaryBlobs"], ["rtdump-probe"])
            self.assertEqual(loaded["_auxiliary"]["rtdump-probe"]["classesFound"], ["Camera"])
            self.assertEqual(len(loaded["records"]), len(game["records"]))

    def test_skeleton_carries_the_manifest_quality_mode(self):
        doc = synthetic.skeleton([1.0], [], [], quality_mode=30)
        self.assertEqual(doc["header"]["quality"]["values"], {"Quality": {"v": 30, "n": None}})


if __name__ == "__main__":
    unittest.main()
