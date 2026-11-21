"""Native MV descriptors and copy-only edits; original samples are optional."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import os
import unittest
import zipfile

from webtools.core import mv_studio_timeline as studio

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))


class TimelineContractTests(unittest.TestCase):
    def test_non_timeline_input_has_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "UnityFS live timeline"):
            studio.parse_timeline(b"not a bundle", "invalid.unity")

    def test_unmodified_native_output_is_the_same_blob(self):
        raw = b"preserve source file bytes"
        original = {"duration": 0, "tracks": [], "warnings": []}
        self.assertIs(studio.edit_timeline(raw, original, deepcopy(original)), raw)

    def test_fov_uses_the_camera_monoscript_property_binding(self):
        rows = [
            {"path": 0, "typeID": 4, "attribute": 4},
            {"path": 0, "typeID": 114, "attribute": 2282594708},
            {"path": 0, "typeID": 4, "attribute": 1},
        ]
        clip = {"m_ClipBindingConstant": {"genericBindings": rows}}
        self.assertEqual(studio._camera_sample_order(clip), ["euler", "fov", "position"])
        for wrong in ({"path": 1}, {"typeID": 20}, {"attribute": 17}, {"isPPtrCurve": True}):
            with self.subTest(wrong=wrong):
                amended = deepcopy(clip)
                amended["m_ClipBindingConstant"]["genericBindings"][1].update(wrong)
                with self.assertRaisesRegex(ValueError, "camera bindings"):
                    studio._camera_sample_order(amended)

    def test_stage_motion_rejects_partial_native_clip_playback(self):
        from webtools.core import mv_studio_stage_motion as stage

        reader = SimpleNamespace(read_typetree=lambda: {})
        data = {"start": 0, "duration": 0, "loop": False, "unsupported": 0, "tracks": [
            {"path": 17, "kind": "visibility", "visibilityType": "gameObject", "curves": [("constant", 1)]},
        ]}
        with patch.object(stage.animation, "decode_clip", return_value=data):
            self.assertEqual(stage._read_clip(reader, None)[0]["channels"], data["tracks"])
            for unsupported in (
                {"path": 17, "kind": "visibility", "visibilityType": "renderer", "curves": [("constant", 1)]},
                {"path": 0, "kind": "translation", "curves": [("constant", 1)] * 3},
            ):
                with self.subTest(unsupported=unsupported):
                    data["tracks"].append(unsupported)
                    self.assertIsNone(stage._read_clip(reader, None))
                    data["tracks"].pop()
            data["unsupported"] = 1
            self.assertIsNone(stage._read_clip(reader, None))


@unittest.skipUnless((SAMPLES / "a-1205603-live_timeline.unity").is_file() and
                     (SAMPLES / "i-1205603-live_timeline.unity").is_file(), "Original game samples are optional")
class ActualTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = {platform: (SAMPLES / f"{platform}-1205603-live_timeline.unity").read_bytes()
                   for platform in ("a", "i")}
        cls.original = {platform: studio.parse_timeline(raw, platform) for platform, raw in cls.raw.items()}

    def camera(self, data):
        return next(track for track in data["tracks"] if track["label"] == "CameraMotion/Camera1")

    def test_native_special_stage_tracks_and_camera_samples_agree_on_android_and_ios(self):
        before = self.original["a"]
        self.assertEqual(before, self.original["i"])
        self.assertEqual(len(before["tracks"]), 105)
        self.assertEqual(sum(len(track["events"]) for track in before["tracks"]), 2064)
        self.assertAlmostEqual(before["duration"], 118.6166667)
        self.assertTrue({"camera", "dance", "lighting", "bloom", "dof", "effects", "crowd",
                         "display", "split", "mouth", "eyes", "gaze", "cheek"} <=
                        {track["kind"] for track in before["tracks"]})
        camera = self.camera(before)
        self.assertEqual(camera["binding"], "/EntryPoint/Live/Cameras/MainCamera")
        self.assertEqual(len(camera["events"]), 78)
        first = camera["events"][0]
        self.assertAlmostEqual(first["duration"], 241 / 60)
        points = first["values"]["keyframes"]
        self.assertEqual(len(points), 242)
        self.assertAlmostEqual(points[0]["fov"], 41.112091, places=5)
        self.assertAlmostEqual(points[-1]["time"], first["duration"])
        self.assertTrue(all(a["time"] < b["time"] for a, b in zip(points, points[1:])))
        self.assertIn("exact companion asset packs", " ".join(before["warnings"]))
        json.dumps(before, allow_nan=False)

    def test_native_member_shaft_preview_binding_preserves_timeline_export(self):
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                preview = studio.parse_timeline(raw, platform, preview_member_shafts=True)
                shafts = [track for track in preview["tracks"]
                          if track["nativeClass"] == "LiveMemberSpotLightShaftTrack"]
                self.assertEqual([track["shaftSlot"] for track in shafts], [1, 2, 3])
                self.assertEqual([len(track["events"]) for track in shafts], [5, 6, 3])
                self.assertEqual([track["binding"].rsplit("/", 1)[-1] for track in shafts],
                                 ["Member1", "Member2", "Member3"])
                self.assertIs(studio.export_timeline(raw, platform, preview["tracks"]), raw)
                for shaft in shafts:
                    del shaft["shaftSlot"]
                self.assertEqual(preview, self.original[platform])

    def test_original_split_masks_and_clip_pointers_match_both_platforms(self):
        split = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_split=True)
            composition = parsed.pop("splitScreen")
            self.assertEqual(parsed, self.original[platform], "preview-only data leaves the native revision schema intact")
            self.assertEqual(len(composition["masks"]), 9)
            self.assertEqual(len(composition["events"]), 8)
            track = next(track for track in parsed["tracks"] if track["nativeClass"] == "LiveSplitScreenTrack")
            first = track["events"][0]
            self.assertAlmostEqual(first["start"], 242 / 60)
            self.assertEqual([first["values"][key] for key in ("mainCamera", "subCamera1", "subCamera2", "subCamera3")], [0, 1, 0, 0])
            mask, _, _, fourth = composition["events"][first["id"]]
            self.assertIsNone(fourth)
            self.assertEqual(mask["pointer"], first["values"]["mask1"])
            geometry = composition["masks"][mask["key"]]
            self.assertEqual(len(geometry["positions"]), 12)
            self.assertEqual(geometry["indices"], [0, 1, 2, 0, 2, 3])
            self.assertAlmostEqual(geometry["bounds"][0], 3.5, places=5)
            self.assertAlmostEqual(geometry["bounds"][1], 2.0, places=5)
            self.assertIs(studio.export_timeline(raw, platform, parsed["tracks"]), raw)
            split.append(composition)
        self.assertEqual(*split)

    def test_original_stage_animator_curves_and_infinite_holds_match_both_platforms(self):
        motion = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_stage_motion=True)
            stage = parsed.pop("stageMotion")
            self.assertEqual(parsed, self.original[platform], "stage playback must not change the native revision")
            roots = [f"/EntryPoint/Live/Stages/MainStage/Effect/lit_01/lit{group}_All" for group in "ABCD"]
            overlay = "/EntryPoint/Live/Stages/MainStage/Effect/fx_ove_so2056_01/Effect_root"
            self.assertEqual(stage["bindings"], [*roots, overlay])
            self.assertEqual(len(stage["clips"]), 15)
            self.assertEqual(len(stage["mix"]), 25)
            tracks = [track for track in parsed["tracks"] if stage["quality"].get(track["id"]) == "stage_animation"]
            self.assertEqual([track["binding"] for track in tracks], roots)
            overlay_tracks = [track for track in parsed["tracks"]
                              if stage["quality"].get(track["id"]) == "stage_overlay_effect"]
            self.assertEqual([track["binding"] for track in overlay_tracks], [overlay])
            self.assertEqual(len(overlay_tracks[0]["events"]), 1)
            for track in [*tracks, *overlay_tracks]:
                event = track["events"][-1]
                self.assertIsNone(event["values"]["postExtrapolationTime"])
                self.assertTrue(stage["mix"][event["id"]]["postInfinite"])
            self.assertEqual({channel["kind"] for clip in stage["clips"].values()
                              for channel in clip["channels"]},
                             {"euler", "overlayTint", "overlayUV", "scale", "translation", "visibility"})
            self.assertTrue(any(clip["duration"] == 0 for clip in stage["clips"].values()))
            json.dumps(stage, allow_nan=False)
            motion.append(stage)
        self.assertEqual(*motion)

    def test_saved_project_without_split_metadata_recovers_original_mask_bindings(self):
        from webtools.core import mv_studio

        project = mv_studio._blank("Older project")
        project.update(duration=self.original["a"]["duration"], tracks=deepcopy(self.original["a"]["tracks"]))
        split_track = next(track for track in project["tracks"] if track["nativeClass"] == "LiveSplitScreenTrack")
        split_track["events"][0]["start"] = 4.1
        with io.BytesIO() as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                archive.writestr("project.json", json.dumps(project))
                archive.writestr("source-timeline.unity", self.raw["a"])
            with zipfile.ZipFile(handle, "r") as archive, patch.object(mv_studio, "_register", side_effect=lambda value, source: value):
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(len(reopened["splitScreen"]["masks"]), 9)

    def test_native_world_display_title_uses_same_assets_on_both_platforms(self):
        descriptors = []
        for platform, raw in self.raw.items():
            parsed = studio.parse_timeline(raw, platform, preview_stage_title=True)
            title = parsed.pop("stageTitle")
            self.assertEqual(parsed, self.original[platform])
            cue, main = title["cues"]
            self.assertEqual({mesh["name"] for mesh in cue["meshes"]}, {"title_L", "title_R"})
            self.assertEqual({mesh["name"] for mesh in main["meshes"]}, {"title_up", "title_doun"})
            self.assertEqual({row["kind"] for row in main["animation"]["channels"]},
                             {"overlayUV", "overlayTint", "translation"})
            self.assertEqual(main["texture"], cue["texture"])
            self.assertEqual(title["particleSchema"], 2)
            self.assertEqual(len(title["textures"]), 4)
            self.assertTrue(all((texture["width"], texture["height"]) == (512, 512)
                                for texture in title["textures"]))
            track = next(track for track in parsed["tracks"] if track["id"] == cue["trackId"])
            event = next(event for event in track["events"] if event["id"] == cue["eventId"])
            self.assertAlmostEqual(event["start"], 350 / 60)
            self.assertAlmostEqual(event["start"] + event["duration"], 670 / 60)
            first, middle, last = title["particles"]
            self.assertEqual((main["trackId"], main["eventId"]), (first["trackId"], first["eventId"]))
            self.assertEqual([emitter["name"] for emitter in first["emitters"]], ["title_main"])
            red, white = middle["emitters"]
            self.assertEqual(red["lifetime"], 2.9159176349639893)
            self.assertEqual(white["lifetime"], 3.2112085819244385)
            self.assertEqual(red["size"], [18.36803436279297] * 2)
            self.assertEqual(white["size"], [18.04229736328125] * 2)
            self.assertEqual(red["color"]["rgb"], [[0, 228 / 255, 10 / 255, 56 / 255]])
            self.assertEqual(white["color"]["rgb"], [[0, 1, 1, 1]])
            self.assertEqual(red["texture"], white["texture"])
            self.assertEqual(red["atlas"], white["atlas"])
            self.assertEqual(red["atlas"]["tiles"], [2, 4])
            self.assertEqual(red["atlas"]["period"], .5)
            self.assertIsNone(red["atlas"]["row"])
            self.assertEqual({emitter["name"] for emitter in last["emitters"]},
                             {"title_main", "title_sub", "title_main_vanish", "square", "block"})
            for group, start in ((first, 350 / 60), (middle, 466 / 60), (last, 580 / 60)):
                track = next(track for track in parsed["tracks"] if track["id"] == group["trackId"])
                event = next(event for event in track["events"] if event["id"] == group["eventId"])
                self.assertAlmostEqual(event["start"], start)
            self.assertIs(studio.export_timeline(raw, platform, parsed["tracks"]), raw)
            descriptors.append(title)
        self.assertEqual(*descriptors)

    def test_native_speed_background_preserves_paired_mesh_color_and_animation(self):
        from webtools.core.model_animation import _evaluate

        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True)
                effect = parsed.pop("stageSpeedBack")
                self.assertEqual(parsed, self.original[platform])
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/light")
                self.assertEqual(event["label"], "fx_dis_so2056_09")
                self.assertAlmostEqual(event["start"], 77.05)
                self.assertAlmostEqual(event["start"] + event["duration"], 118.6166667)
                self.assertEqual((effect["duration"], effect["lifetime"]), (50, 60))
                self.assertEqual(len(effect["positions"]), 1701)
                self.assertEqual(len(effect["uv"]), 1701)
                self.assertEqual(len(effect["indices"]), 9600)
                self.assertEqual(effect["rgb"], [109, 117, 128])
                self.assertEqual(set(effect["alpha"]), {0, 7, 15, 22, 30, 38})
                self.assertEqual(effect["matrix"][::5], [2.5, 1.5, 0, 1])
                self.assertEqual([row["width"] for row in effect["texture"]],
                                 [512 >> index for index in range(10)])
                for curve, expected in zip(effect["uvCurves"], (1.535, 1, .465, 69.75)):
                    self.assertAlmostEqual(_evaluate(curve, 23.25), expected, places=6)
                stars = effect["centerStars"]
                self.assertEqual(stars["seed"], 3710075818)
                self.assertEqual((stars["size"], stars["lifetime"], stars["rate"], stars["cycle"]), (2, 1, 2, 5))
                self.assertEqual(stars["uv"], [.25, .25, 0, .25])
                self.assertAlmostEqual(stars["sizePeriod"], .2)
                self.assertEqual([row["width"] for row in stars["texture"]],
                                 [512 >> index for index in range(10)])
                moving = effect["movingCompanions"]
                self.assertEqual([row["name"] for row in moving], ["speed", "speed_R", "speed_L", "stars"])
                self.assertEqual([row["rate"] for row in moving], [250, 100, 100, 100])
                self.assertEqual([row["seed"] for row in moving], [0, 1626203053, 2207999926, 3710075818])
                self.assertEqual([row["shape"]["type"] for row in moving], [4, 10, 10, 4])
                self.assertEqual([row["uv"] for row in moving], [[.25, .25, .75, 0]] * 3 + [[.25, .25, .75, .25]])
                self.assertTrue(all("texture" not in row for row in moving))
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_display_lights_match_across_android_and_ios(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_display_lights=True)
                effect = parsed.pop("stageDisplayLights")
                self.assertEqual(parsed, self.original[platform])
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/light")
                self.assertEqual(event["label"], "fx_dis_so2056_06")
                self.assertAlmostEqual(event["start"], 2897 / 60)
                self.assertAlmostEqual(event["start"] + event["duration"], 62.95)
                self.assertEqual([row["width"] for row in effect["texture"]], [512 >> index for index in range(10)])
                emitters = {row["name"]: row for row in effect["emitters"]}
                self.assertEqual(set(emitters), {"light_up", "light_down", "light_right", "light_left", "light_L", "light_R"})
                for name, row in emitters.items():
                    side = name in {"light_L", "light_R"}
                    self.assertEqual(row["bursts"], [[0, 2], [1, 2]] if side else [[0, 1]])
                    self.assertEqual((row["speed"], row["lifetime"], row["sortBias"]), (-1 if side else 1, 4, 0))
                    self.assertNotIn("texture", row)
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_falling_effects_reuse_the_existing_paired_atlases(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_display_lights=True,
                                               preview_stage_speed_back=True, preview_stage_falling_effects=True)
                effect = parsed.pop("stageFallingEffects")
                self.assertEqual(effect["textures"], ["displayLights", "speedBackCenterStars"])
                self.assertEqual(len(parsed.pop("stageDisplayLights")["texture"]), 10)
                self.assertEqual(len(parsed.pop("stageSpeedBack")["centerStars"]["texture"]), 10)
                self.assertEqual(parsed, self.original[platform])
                emitters = {row["name"]: row for row in effect["emitters"]}
                self.assertEqual(set(emitters), {"light_big", "light_smole", "light_smole_L", "light_smole_R", "stars"})
                self.assertEqual(emitters["stars"]["rate"], 10)
                self.assertTrue(all(emitters[name]["burstPeriod"] == 1 for name in emitters if name != "stars"))
                starts = {"fx_dis_so2056_05": 670 / 60, "fx_dis_so2056_07": 62.95}
                palettes = {"fx_dis_so2056_05": [32768, 128, 170, 255], "fx_dis_so2056_07": [32768, 255, 128, 128]}
                for cue in effect["cues"]:
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertAlmostEqual(event["start"], starts[event["label"]])
                    self.assertEqual(cue["starPalette"]["rgb"][0], palettes[event["label"]])
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_stage_break_reuses_paired_atlases_and_retains_the_fracture_mesh(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_display_lights=True, preview_stage_break=True)
                effect = parsed.pop("stageBreak")
                self.assertEqual(effect["textures"][1:], ["displayLights", "speedBackCenterStars"])
                self.assertEqual([level["width"] for level in effect["textures"][0]], [512 >> i for i in range(10)])
                self.assertEqual(effect["mesh"]["color"]["start"], [95, 71, 75, 255])
                self.assertEqual(effect["mesh"]["scale"], [11, 6, 1])
                self.assertIsNone(effect["mesh"]["vertexColors"])
                self.assertEqual((len(effect["mesh"]["positions"]), len(effect["mesh"]["indices"])), (49, 216))
                roles = {row["name"]: (row["count"], row["delay"], row["texture"]) for row in effect["emitters"]}
                self.assertEqual(roles, {"flash": (1, .25, 2), "Fall": (60, .25, 2), "light_big": (8, 0, 1)})
                track, = [row for row in parsed["tracks"] if row["id"] == effect["trackId"]]
                event, = [row for row in track["events"] if row["id"] == effect["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Display/break")
                self.assertAlmostEqual(event["start"], 77.05)
                self.assertAlmostEqual(event["start"] + event["duration"], 79.55)
                del parsed["stageDisplayLights"], parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                descriptors.append(effect)
        self.assertEqual(*descriptors)

    def test_native_finale_floor_matches_the_paired_source_and_shares_the_star_atlas(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_finale_floor=True)
                floor = parsed.pop("stageFinaleFloor")
                stars = parsed.pop("stageSpeedBack")["centerStars"]
                self.assertEqual(floor["textures"], ["speedBackCenterStars"])
                self.assertEqual(len(stars["texture"]), 10)
                self.assertEqual(parsed, self.original[platform])
                self.assertEqual((floor["seed"], floor["rate"], floor["cycle"], floor["lifetime"]), (0, 150, 5, .5))
                self.assertEqual(floor["box"], [20, 0, 1])
                self.assertEqual(tuple(floor["speedRange"]), (15, 25))
                self.assertEqual(floor["uv"], [.25, .25, .75, 0])
                track, = [row for row in parsed["tracks"] if row["id"] == floor["trackId"]]
                event, = [row for row in track["events"] if row["id"] == floor["eventId"]]
                self.assertEqual(track["label"], "StageEffect/Expert/Control/flo")
                self.assertAlmostEqual(event["start"], 114.5)
                self.assertAlmostEqual(event["start"] + event["duration"], 118.6166666667)
                descriptors.append(floor)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_front_spark_cues_preserve_the_distinct_seed_overrides(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_sparks_a=True)
                sparks = parsed.pop("stageSparksA")
                self.assertEqual(sparks["textures"], ["speedBackCenterStars"])
                del parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                emitter, secondary = sparks["emitters"]
                self.assertEqual(emitter["name"], "hibana_01")
                self.assertEqual(secondary["name"], "hibana_02")
                self.assertAlmostEqual(secondary["delay"], .12)
                self.assertEqual(secondary["shape"]["length"], 7)
                self.assertEqual(secondary["bursts"][0][:3], [0, 60, 3])
                self.assertAlmostEqual(secondary["bursts"][0][3], .15)
                self.assertEqual(len(secondary["size3D"]), 3)
                self.assertEqual(secondary["atlas"], {"tiles": [4, 4], "start": (0, .125)})
                self.assertAlmostEqual(secondary["minViewportWidth"], .02)
                self.assertEqual(secondary["maxViewportWidth"], 2)
                self.assertEqual(emitter["shape"]["type"], 8)
                self.assertEqual(emitter["bursts"], [[0, 1000]])
                self.assertEqual(emitter["maxViewportWidth"], 1)
                self.assertAlmostEqual(emitter["stretch"]["velocityScale"], .025)
                self.assertEqual(emitter["uv"], [.25, .25, .75, 0])
                self.assertEqual(len(sparks["cues"]), 2)
                for index, (cue, x, y) in enumerate(zip(sparks["cues"], (7, -4), (-1, -2)), 1):
                    self.assertEqual(cue["seed"], 100 * index)
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertTrue(track["label"].endswith(f"/Control/sparks_A_{index:02}"))
                    self.assertAlmostEqual(event["start"], 77.7333333333)
                    self.assertAlmostEqual(event["start"] + event["duration"], 83.1333333333)
                    self.assertEqual(event["values"]["offset"], {"x": x, "y": y, "z": 8})
                descriptors.append(sparks)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_spark_pair_matches_the_source_and_shares_the_star_atlas(self):
        descriptors = []
        for platform, raw in self.raw.items():
            with self.subTest(platform=platform):
                parsed = studio.parse_timeline(raw, platform, preview_stage_speed_back=True,
                                               preview_stage_sparks_b=True)
                sparks = parsed.pop("stageSparksB")
                self.assertEqual(sparks["textures"], ["speedBackCenterStars"])
                del parsed["stageSpeedBack"]
                self.assertEqual(parsed, self.original[platform])
                self.assertEqual([row["name"] for row in sparks["emitters"]], ["grow", "hibana", "late_kirakira"])
                self.assertEqual([row["seed"] for row in sparks["emitters"]], [None, 0, None])
                glow, streak, glimmer = sparks["emitters"]
                self.assertEqual(glow["uv"], [.25, .25, 0, .5])
                self.assertEqual([burst[1] for burst in streak["bursts"]], [100, 75, 50])
                self.assertEqual(streak["stretch"]["lengthScale"], 2.5)
                self.assertEqual(glimmer["rate"], 75)
                self.assertEqual(len(sparks["cues"]), 2)
                for index, (cue, x) in enumerate(zip(sparks["cues"], (4, -4)), 1):
                    track, = [row for row in parsed["tracks"] if row["id"] == cue["trackId"]]
                    event, = [row for row in track["events"] if row["id"] == cue["eventId"]]
                    self.assertTrue(track["label"].endswith(f"/Control/sparks_B_{index:02}"))
                    self.assertAlmostEqual(event["start"], 77.4166666667)
                    self.assertAlmostEqual(event["start"] + event["duration"], 83.1333333333)
                    self.assertEqual(event["values"]["offset"], {"x": x, "y": 5.5, "z": -5})
                descriptors.append(sparks)
        self.assertEqual(len(descriptors), 2)
        self.assertEqual(*descriptors)

    def test_native_title_pair_with_forced_seed_keeps_other_title_cues(self):
        from UnityPy.files.ObjectReader import ObjectReader

        track = next(track for track in self.original["a"]["tracks"] if track["label"].endswith("/Title_mainDis"))
        event = track["events"][1]
        source = int(event["values"]["asset"].rsplit(":", 1)[-1])
        read = ObjectReader.read_typetree

        def force_seed(reader, *args, **kwargs):
            tree = read(reader, *args, **kwargs)
            return {**tree, "overwriteRandomSeed": 1} if reader.path_id == source else tree

        with patch.object(ObjectReader, "read_typetree", force_seed):
            title = studio.parse_timeline(self.raw["a"], "android", preview_stage_title=True)["stageTitle"]
        self.assertEqual(len(title["cues"]), 2)
        self.assertEqual(len(title["textures"]), 3)
        self.assertEqual([group["eventId"] for group in title["particles"]],
                         [track["events"][0]["id"], track["events"][2]["id"]])

    def test_native_existing_point_and_bloom_edit_reopen_with_original_platform(self):
        import UnityPy

        for platform, target in (("a", 13), ("i", 9)):
            with self.subTest(platform=platform):
                old = self.original[platform]
                revision = deepcopy(old)
                event = self.camera(revision)["events"][0]
                event["label"] = "Edited cut"
                point = event["values"]["keyframes"][12]
                point["fov"] += 1.5
                point["position"][0] += .25
                bloom = next(track for track in revision["tracks"] if track["kind"] == "bloom")["events"][0]
                bloom["start"] += .01
                bloom["values"]["intensity"] = .45
                changed = studio.edit_timeline(self.raw[platform], old, revision)
                with patch.object(studio, "parse_timeline", wraps=studio.parse_timeline) as parse:
                    self.assertEqual(studio.export_timeline(self.raw[platform], platform, revision["tracks"]), changed)
                    self.assertEqual(parse.call_count, 1)
                self.assertIs(studio.export_timeline(self.raw[platform], platform, old["tracks"]), self.raw[platform])
                current = studio.parse_timeline(changed, platform)
                self.assertEqual({int(asset.target_platform) for asset in UnityPy.load(changed).assets}, {target})
                actual = self.camera(current)["events"][0]
                self.assertEqual(actual["label"], "Edited cut")
                self.assertAlmostEqual(actual["values"]["keyframes"][12]["fov"], point["fov"], places=4)
                self.assertAlmostEqual(actual["values"]["keyframes"][12]["position"][0], point["position"][0], places=4)
                actual_bloom = next(track for track in current["tracks"] if track["kind"] == "bloom")["events"][0]
                self.assertAlmostEqual(actual_bloom["values"]["intensity"], .45, places=6)
                self.assertAlmostEqual(actual_bloom["start"], bloom["start"])
                self.assertEqual(self.camera(current)["events"][1:], self.camera(old)["events"][1:])

    def test_native_copy_refuses_replacement_refs_and_stale_baseline(self):
        original = self.original["a"]
        revision = deepcopy(original)
        self.camera(revision)["events"][0]["values"]["animation"] = "cab:1"
        with self.assertRaisesRegex(ValueError, "read-only"):
            studio.edit_timeline(self.raw["a"], original, revision)
        baseline = deepcopy(original)
        self.camera(baseline)["events"][0]["label"] = "Stale source"
        with self.assertRaisesRegex(ValueError, "changed after opening"):
            studio.edit_timeline(self.raw["a"], baseline, revision)

    def test_shared_playable_allows_timing_only_and_keeps_other_clip(self):
        import UnityPy

        def bloom(data):
            return next(track for track in data["tracks"] if track["kind"] == "bloom")

        track_id = int(bloom(self.original["a"])["id"].rsplit(":", 1)[1])
        environment = UnityPy.load(self.raw["a"])
        component = next(obj for obj in environment.objects if obj.path_id == track_id)
        tree = component.read_typetree()
        tree["m_Clips"][1]["m_Asset"] = tree["m_Clips"][0]["m_Asset"]
        component.save_typetree(tree)
        shared = environment.file.save(packer="lz4")
        original = studio.parse_timeline(shared, "shared")
        revision = deepcopy(original)
        first = bloom(revision)["events"][0]
        first["values"]["intensity"] = .51
        with self.assertRaisesRegex(ValueError, "shared or external"):
            studio.edit_timeline(shared, original, revision)
        first["values"]["intensity"] = bloom(original)["events"][0]["values"]["intensity"]
        first["start"] += .01
        changed = studio.edit_timeline(shared, original, revision)
        current = studio.parse_timeline(changed, "changed")
        self.assertAlmostEqual(bloom(current)["events"][0]["start"], first["start"])
        self.assertEqual(bloom(current)["events"][1], bloom(original)["events"][1])
