import base64
import io
import json
import os
import unittest
import zlib
from pathlib import Path
from unittest import mock

from webtools.core import mv_studio_control_prefabs as prefabs
from webtools.core import mv_studio_import_coverage as coverage
from webtools.core import mv_studio_prefab_animator as animator
from webtools.core import mv_studio_shader_identity as shaders


def node(path, parent, *, active=True, kinds=(), layer=26):
    parts = tuple(path.split("/"))
    return {"parent": parent, "game": None, "tree": {"m_Name": parts[-1], "m_Layer": layer}, "parts": parts,
            "path": path, "self": active, "authored": active, "position": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0, 1.0], "scale": [1.0, 1.0, 1.0],
            "components": {kind: None for kind in ("Transform", *kinds)}}


def binding(path, type_id, attribute, custom=0):
    return {"path": zlib.crc32(path.encode()), "typeID": type_id, "attribute": attribute, "customType": custom,
            "isPPtrCurve": 0, "script": {"m_FileID": 0, "m_PathID": 0}}


def lane(name, index):
    return (zlib.crc32(name.encode()) & 0x0FFFFFFF) | (index << 28)


def row(item, *curves):
    return item, [animator.flat(curve) for curve in curves], list(curves)


MOVING = ("linear", [(0.0, 0.0), (1.0, 1.0)])
ONE = ("constant", 1.0)


class AnimatorReaderTests(unittest.TestCase):
    walked = [node("fx", None), node("fx/root", 0, kinds=("Animator",)), node("fx/root/bar", 1, kinds=("MeshRenderer",)),
              node("fx/root/core", 1, kinds=("ParticleSystem", "ParticleSystemRenderer"))]

    def test_channels_resolve_paths_below_the_animator(self):
        rows = [row(binding("bar", 4, animator.POSITION), MOVING, ONE, ONE),
                row(binding("bar", 4, animator.EULER, custom=4), ONE, ONE, MOVING),
                row(binding("bar", 1, animator.ACTIVE), MOVING),
                row(binding("bar", 23, animator.ENABLED), ONE),
                *[row(binding("bar", 23, lane("_TintColor", 4 + index), custom=22), MOVING) for index in range(4)],
                *[row(binding("core", 199, lane("_MainTex_ST", index), custom=22), MOVING) for index in range(4)],
                # A path that is not in this prefab binds nothing, as in Unity.
                row(binding("missing", 4, animator.POSITION), ONE, ONE, ONE)]
        channels, unsupported = animator.channels(self.walked, 1, rows)
        self.assertEqual(unsupported, {})
        found = {(channel["node"], channel["kind"], channel.get("renderer")) for channel in channels}
        self.assertEqual(found, {(2, "translation", None), (2, "euler", None), (2, "active", None),
                                 (2, "enabled", "MeshRenderer"), (2, "tint", "MeshRenderer"),
                                 (3, "uv", "ParticleSystemRenderer")})
        euler = next(channel for channel in channels if channel["kind"] == "euler")
        self.assertEqual(euler["rotationOrder"], 4)
        tint = next(channel for channel in channels if channel["kind"] == "tint")
        self.assertEqual(tint["curves"], [MOVING] * 4)

    def test_both_lane_families_of_one_color_are_reported(self):
        # 12029's floor clips animate _TintColor as .xyzw and as .rgba; which Unity writes last is not established.
        rows = [*[row(binding("bar", 23, lane("_TintColor", index), custom=22), ONE) for index in range(4)],
                *[row(binding("bar", 23, lane("_TintColor", 4 + index), custom=22), MOVING) for index in range(4)]]
        channels, unsupported = animator.channels(self.walked, 1, rows)
        self.assertEqual(unsupported, {2: "Animator animates _TintColor through both its vector and color lanes"})
        partial, unsupported = animator.channels(self.walked, 1, rows[:2])
        self.assertEqual(unsupported, {2: "Animator animates part of _TintColor"})
        other, unsupported = animator.channels(self.walked, 1, [row(binding("bar", 23, lane("_Color", 0), custom=22), ONE)])
        self.assertEqual(other, [])
        self.assertIn(2, unsupported)

    def test_timing_and_json_curves(self):
        clip = {"m_Name": "clip_par", "m_MuscleClip": {"m_StartTime": 0.0, "m_StopTime": 48.0, "m_LoopTime": 1}}
        self.assertEqual(animator.timing(clip), {"name": "clip_par", "start": 0.0, "duration": 48.0, "loop": True})
        with self.assertRaisesRegex(animator.Unsupported, "cycle offset"):
            animator.timing({**clip, "m_MuscleClip": {**clip["m_MuscleClip"], "m_CycleOffset": .5}})
        # Unity's negative-infinity sentinel key becomes a finite JSON number the runtime treats the same.
        curve = animator.json_curve(("cubic", [(float("-inf"), (0, 0, 0, 2.0)), (0.0, (0, 0, 1.0, 2.0))]))
        self.assertEqual(curve, ["cubic", [[-1e30, [0.0, 0.0, 0.0, 2.0]], [0.0, [0.0, 0.0, 1.0, 2.0]]]])
        json.dumps(curve, allow_nan=False)

    def test_state_with_speed_or_parameters_is_not_read(self):
        machine = {"m_StateConstantArray": [{"data": {"m_Speed": 2.0}}], "m_DefaultState": 0,
                   "m_AnyStateTransitionConstantArray": []}
        with self.assertRaisesRegex(animator.Unsupported, "speed"):
            animator._state(machine)
        machine["m_StateConstantArray"][0]["data"] = {"m_Speed": 1.0, "m_SpeedParamID": 77}
        with self.assertRaisesRegex(animator.Unsupported, "parameter"):
            animator._state(machine)


class Reader:
    def __init__(self, tree):
        self.tree = tree

    def read_typetree(self):
        return self.tree


class TemplateTests(unittest.TestCase):
    def test_animator_inactive_at_clone_activation_is_reported(self):
        # fx/root's Animator activates fx/root/late; Unity starts late's own Animator
        # when that happens, not when the clone activates, so what it animates is
        # reported. fx/root/never is never activated: it draws nothing.
        walked = [node("fx", None), node("fx/root", 0, kinds=("Animator",)),
                  node("fx/root/late", 1, active=False, kinds=("Animator",)),
                  node("fx/root/late/bar", 2, kinds=("MeshRenderer",)),
                  node("fx/root/never", 1, active=False, kinds=("Animator",)),
                  node("fx/root/never/bar", 4, kinds=("MeshRenderer",))]
        for item in walked:
            item["authored"] = item["self"] and (item["parent"] is None or walked[item["parent"]]["authored"])
            item["components"] = {kind: Reader({"m_Enabled": 1}) for kind in item["components"]
                                  if kind != "Transform"}
        clip = {"m_Name": "clip", "m_MuscleClip": {"m_StartTime": 0.0, "m_StopTime": 1.0, "m_LoopTime": 1}}
        rows = {id(walked[1]["components"]["Animator"]): [row(binding("late", 1, animator.ACTIVE), MOVING)]}
        with mock.patch.object(animator, "default_clip", return_value=clip) as default, \
                mock.patch.object(animator, "bindings", side_effect=lambda clip, deadline: rows.pop(next(iter(rows)))):
            template, drawn, gaps, quiet = prefabs._template({}, walked, prefabs._Builder(0), 0)
        self.assertEqual(default.call_count, 1, "only the Animator active at the clone's activation is read")
        self.assertEqual((template, drawn), (None, 0))
        self.assertEqual(gaps, [{"path": "fx/root/late/bar", "reason": "under prefab animation that is not previewed "
                                 "(Animator activated after the clone; its state time is not reproduced)"}])
        self.assertEqual(quiet, ["inactive GameObject"])


class ShaderIdentityTests(unittest.TestCase):
    class Shader:
        def __init__(self, name, path_id=7):
            self.type = type("Type", (), {"name": "Shader"})
            self.path_id = path_id
            self.assets_file = None
            self.reads = 0
            self.name = name

        def read_typetree(self):
            self.reads += 1
            return {"m_ParsedForm": {"m_Name": self.name}}

    def material(self, externals=()):
        external = [type("External", (), {"path": path}) for path in externals]
        return type("Material", (), {"assets_file": type("File", (), {"externals": external})()})()

    def test_a_loaded_copy_is_identified_by_its_shaderlab_name(self):
        shader = self.Shader("AS/General/Transparent")
        shader.assets_file = type("File", (), {})()
        material = self.material()
        tree = {"m_Shader": {"m_FileID": 0, "m_PathID": 7}}
        with mock.patch.object(shaders.viewer, "_ref", return_value=shader):
            self.assertTrue(shaders.matches(material, tree, "AS/General/Transparent"))
            self.assertEqual(shaders.name(material, tree), "AS/General/Transparent")
        self.assertEqual(shader.reads, 1, "the compiled shader's type tree is read once")

    def test_an_external_shader_uses_the_verified_bundle_table(self):
        material = self.material(["archive:/cab-adf9ba7b61bd035c754bf74ae44927cb/cab-adf9ba7b61bd035c754bf74ae44927cb"])
        with mock.patch.object(shaders.viewer, "_ref", return_value=None):
            self.assertEqual(shaders.name(material, {"m_Shader": {"m_FileID": 1, "m_PathID": 7151384334892346267}}),
                             "AS/General/Transparent")
            self.assertIsNone(shaders.name(material, {"m_Shader": {"m_FileID": 1, "m_PathID": 1}}))
            self.assertIsNone(shaders.name(material, {"m_Shader": {"m_FileID": 2, "m_PathID": 7151384334892346267}}))


class LedgerTests(unittest.TestCase):
    def test_particle_outcomes(self):
        outcome = {"systems": [1, 26, 20, 5], "error": None,
                   "rejected": [{"path": "a", "reason": "mesh render mode"},
                                {"path": "b", "reason": "playOnAwake is off (the clone never starts it)"}]}
        drawn, gaps, quiet = prefabs._particle_summary(outcome)
        self.assertEqual(drawn, 2)
        self.assertEqual(gaps, ["particles on the overlay camera layer 20", "mesh render mode"])
        self.assertEqual(quiet, ["particles on layer 5, which the main camera does not draw",
                                 "playOnAwake is off (the clone never starts it)"])

    def test_coverage_report_reads_the_ledger(self):
        track = {"id": "t", "label": "StageEffect/Expert/Display/EQ", "nativeClass": "CustomControlTrack",
                 "events": [{"id": "t:0"}, {"id": "t:1"}, {"id": "t:2"}]}
        project = {"tracks": [track], "controlCoverage": [
            {"trackId": "t", "eventId": "t:0", "status": "rendered", "note": "drawn"},
            {"trackId": "t", "eventId": "t:1", "status": "partial", "note": "part"},
            {"trackId": "t", "eventId": "t:2", "status": "no effect", "note": "nothing"}]}
        rows = {(row["status"], row["note"]): row["clips"] for row in coverage.report(project)["tracks"]}
        self.assertEqual(rows, {("rendered", "drawn"): 1, ("partial", "part"): 1, ("no effect", "nothing"): 1})
        self.assertEqual([row["status"] for row in coverage.report(project)["gaps"]], ["partial"])

    def test_cue_budgets_are_ledgered(self):
        # The runtime refuses more than 512 cues; the extra clips are ledgered, not
        # reported as drawn. A cue the particle reader dropped draws no systems.
        rows = [{"track": {"id": "t"}, "event": {"id": f"t:{index}"}, "prefab": object(), "offset": [0, 0, 0],
                 "quality": "stage_control"} for index in range(3)]
        outcomes = {"k": {"systems": [26], "walked": [], "dropped": {("t", "t:1")}}}
        with mock.patch.object(prefabs, "_MAX_CUES", 2), \
                mock.patch.object(prefabs.particles, "control_clips", return_value=rows), \
                mock.patch.object(prefabs.viewer, "_key", return_value="k"), \
                mock.patch.object(prefabs, "_template", return_value=({"name": "fx"}, 1, [], [])):
            descriptor, ledger = prefabs.read({}, None, [], float("inf"), outcomes=outcomes)
        self.assertEqual([cue["eventId"] for cue in descriptor["cues"]], ["t:0", "t:1"])
        self.assertEqual([(row["eventId"], row["status"]) for row in ledger],
                         [("t:0", "rendered"), ("t:1", "partial"), ("t:2", "partial")])
        self.assertIn("particle cue budget of the preview", ledger[1]["note"])
        self.assertIn("prefab cue budget of the preview", ledger[2]["note"])
        outcomes["k"]["dropped"].add(("t", "t:2"))
        with mock.patch.object(prefabs, "_MAX_CUES", 2), \
                mock.patch.object(prefabs.particles, "control_clips", return_value=rows), \
                mock.patch.object(prefabs.viewer, "_key", return_value="k"), \
                mock.patch.object(prefabs, "_template", return_value=({"name": "fx"}, 1, [], [])):
            _, ledger = prefabs.read({}, None, [], float("inf"), outcomes=outcomes)
        self.assertEqual(ledger[2]["status"], "not rendered", "neither the systems nor the meshes are drawn")
        self.assertEqual(ledger[2]["note"], "The effect prefab is not previewed: particle cue budget of the preview, "
                                            "prefab cue budget of the preview.")

    def test_warning_lists_mesh_gaps_once_per_prefab(self):
        ledger = [{"meshGaps": ["Animator animates _TintColor through both its vector and color lanes"] * 2},
                  {"status": "rendered"}]
        self.assertEqual(prefabs.warning(ledger), "2 original effect prefab meshes are not previewed: Animator "
                                                  "animates _TintColor through both its vector and color lanes x2.")
        self.assertIsNone(prefabs.warning([{}]))


_CENSUS = Path(os.environ.get(
    "ELICHIKA_MV_CENSUS_BUNDLES",
    "/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/coverage/bundle-census/bundles"))
_TIMELINES = {"12007": "c5af86fe3f", "12023": "d089b1cd24", "12025": "ebeada5018", "12029": "969d214716",
              "12035": "bcc02fa813", "12036": "9b87bf5145", "12038": "c8b5b1d0b9"}
_FLAGS = dict(preview_split=True, preview_stage_motion=True, preview_member_shafts=True, preview_stage_title=True,
              preview_stage_particles=True, preview_stage_ribbons=True, preview_stage_spotlight=True,
              preview_stage_butterfly=True, preview_stage_rain=True, preview_stage_leaves=True,
              preview_stage_momiji=True, preview_stage_confetti=True, preview_stage_glow=True, preview_stage_lens=True,
              preview_stage_speed_back=True, preview_stage_display_lights=True, preview_stage_falling_effects=True,
              preview_stage_break=True, preview_stage_finale_floor=True, preview_stage_sparks_a=True,
              preview_stage_sparks_b=True, preview_stage_sparks_roop=True, preview_particle_systems=True,
              preview_control_prefabs=True)


def _parse(song, platform="android"):
    from webtools.core import mv_studio_timeline

    path = _CENSUS / platform / f"live_timeline-{_TIMELINES[song]}.unity3d"
    return mv_studio_timeline.parse_timeline(path.read_bytes(), song, **_FLAGS)


@unittest.skipUnless(all((_CENSUS / platform / f"live_timeline-{name}.unity3d").is_file()
                         for platform in ("android", "ios") for name in _TIMELINES.values())
                     and os.environ.get("ELICHIKA_TEXTURE65_BIN"),
                     "Set ELICHIKA_MV_CENSUS_BUNDLES and ELICHIKA_TEXTURE65_BIN for the original timelines")
class OriginalTimelineTests(unittest.TestCase):
    def test_every_custom_control_clip_has_one_ledger_row(self):
        for platform in ("android", "ios"):
            total = 0
            for song in _TIMELINES:
                with self.subTest(song=song, platform=platform):
                    parsed = _parse(song, platform)
                    clips = {(track["id"], event["id"]) for track in parsed["tracks"]
                             if track.get("nativeClass") == "CustomControlTrack" for event in track["events"]}
                    ledger = parsed["controlCoverage"]
                    self.assertEqual(len(ledger), len(clips))
                    self.assertEqual({(row["trackId"], row["eventId"]) for row in ledger}, clips)
                    self.assertTrue(all(row["status"] in {"rendered", "partial", "not rendered", "no effect", "muted"}
                                        and row["note"] for row in ledger))
                    total += len(clips)
            self.assertEqual(total, 132)

    def test_12036_laser_rigs_and_display_dragons(self):
        source = _parse("12036")["stageControlPrefabs"]
        names = {template["name"]: template for template in source["templates"]}
        self.assertEqual(set(names), {"fx_par_so2036_06", "fx_par_so2036_07", "fx_par_so2036_08", "fx_dis_par_so2036_06"})
        beam = names["fx_par_so2036_06"]
        renderer, = beam["renderers"]
        self.assertEqual((renderer["path"].rsplit("/", 1)[1], len(renderer["skin"]["bones"]), len(renderer["materials"])),
                         ("LaserBeam", 88, 2))
        animator_row, = beam["animators"]
        self.assertEqual(animator_row["clip"], {"name": "clip_par_so2036_06", "start": 0.0, "duration": 48.0, "loop": True})
        kinds = {channel["kind"] for channel in animator_row["channels"]}
        self.assertTrue({"euler", "scale", "tint"} <= kinds)
        self.assertEqual({source["templates"][cue["template"]]["name"] for cue in source["cues"]}, set(names))
        self.assertEqual({cue["quality"] for cue in source["cues"]}, {"stage_control", "stage_display"})
        # Authored pixels and mip levels only: each level halves, nothing is resampled.
        from PIL import Image
        for texture in source["textures"]:
            for index, level in enumerate(texture["levels"]):
                image = Image.open(io.BytesIO(base64.b64decode(level["png"])))
                self.assertEqual(image.size, (level["width"], level["height"]))
                self.assertEqual(level["width"], max(1, texture["levels"][0]["width"] >> index))

    def test_12025_spectrum_quads(self):
        parsed = _parse("12025")
        template, = parsed["stageControlPrefabs"]["templates"]
        self.assertEqual(template["name"], "fx_dis_so2025_01")
        self.assertEqual(len(template["renderers"]), 8)
        mesh, = parsed["stageControlPrefabs"]["meshes"]
        self.assertEqual((mesh["name"], mesh["vertexCount"], mesh["colorAbsent"]), ("Quad", 4, True))
        # Display effects keep their stencil test against the stage screens.
        self.assertEqual({tuple(item["stencil"]) for row in template["renderers"] for item in row["materials"]},
                         {(3, 2, 0, 0)})
        self.assertEqual(template["animators"][0]["clip"]["loop"], True)
        notes = {row["note"] for row in parsed["controlCoverage"]}
        self.assertIn("The clip is not played here: the clip names no prefab (the game instantiates nothing).", notes)

    def test_12035_has_no_prefab_meshes(self):
        parsed = _parse("12035")
        self.assertNotIn("stageControlPrefabs", parsed)
        self.assertEqual(sum(row["status"] == "rendered" for row in parsed["controlCoverage"]), 12)


if __name__ == "__main__":
    unittest.main()
