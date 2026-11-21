"""Original MV timelines remain exportable when project sessions share their bytes."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from webtools.core import mv_studio, mv_studio_stage_particles


class MVStudioStorageTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name).resolve()
        native_root = patch.object(mv_studio, "_root", return_value=self.root)
        self.addCleanup(native_root.stop)
        native_root.start()
        output = patch.object(mv_studio, "_destination", side_effect=lambda name, suffix: self.root / (name + suffix))
        self.addCleanup(output.stop)
        output.start()
        self.original = b"original timeline bytes"

    def test_each_session_keeps_its_own_token_and_saved_zip_contains_the_original(self):
        first = mv_studio._register(mv_studio._blank("First"), self.original)
        with patch.object(mv_studio, "_write", wraps=mv_studio._write) as write:
            second = mv_studio._register(mv_studio._blank("Second"), self.original)
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[0].suffix, ".sha256")
        self.assertNotEqual(first["token"], second["token"])
        self.assertEqual(mv_studio._native(first), self.original)
        self.assertEqual(mv_studio._native(second), self.original)
        with ZipFile(mv_studio.save(second)["path"]) as archive:
            self.assertEqual(archive.read("source-timeline.unity"), self.original)
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        self.assertNotEqual(reopened["token"], second["token"])
        self.assertEqual(mv_studio._native(reopened), self.original)
        self.assertEqual(len(list((self.root / "native" / "blobs").glob("*.unity"))), 1)

    def test_corrupt_blob_fails_save_until_source_is_reopened(self):
        first = mv_studio._register(mv_studio._blank("Recorded"), self.original)
        blob, = (self.root / "native" / "blobs").glob("*.unity")
        blob.write_bytes(b"x" * len(self.original))
        self.assertIsNone(mv_studio._native(first))
        with self.assertRaisesRegex(ValueError, "original MV timeline is unavailable"):
            mv_studio.save(first)
        mv_studio._register(mv_studio._blank("Reopened"), self.original)
        self.assertEqual(mv_studio._native(first), self.original)

    def test_old_title_descriptor_refresh_keeps_edited_event_times(self):
        project = mv_studio._blank("Edited")
        project["duration"] = 9.5
        project["stageTitle"] = {"cues": [], "particles": []}
        project["tracks"] = [{
            "id": "title", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/Title_mainDis",
            "events": [{"id": "clip", "label": "Edited title", "start": 8.0, "duration": 1.5,
                        "values": {"playableClass": "CustomControlClip"}}],
        }]
        upgraded = {"cues": [], "particles": [{"eventId": "clip"}], "particleSchema": 2}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
            "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageTitle": upgraded},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited", preview_split=False, preview_stage_title=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageTitle"], upgraded)

        saved = mv_studio.save(reopened)
        with ZipFile(saved["path"]) as archive, patch("webtools.core.mv_studio_timeline.parse_timeline") as parse:
            current = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_not_called()
        self.assertEqual(current["stageTitle"], upgraded)

    def test_saved_control_project_recovers_particles_from_original_timeline(self):
        project = mv_studio._blank("Edited effects")
        project["duration"] = 45
        project["tracks"] = [{
            "id": "effect", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/par_15_foot_wave",
            "events": [{"id": "clip", "label": "Edited cue", "start": 43, "duration": 1.6,
                        "values": {"playableClass": "CustomControlClip", "offset": {"x": 0, "y": 0, "z": 1.25}}}],
        }]
        restored = {"schema": mv_studio_stage_particles.SCHEMA,
                    "cues": [{"trackId": "effect", "eventId": "clip", "template": 0}]}
        for previous in ({}, {"stageParticles": {"cues": []}}):
            with self.subTest(previous=previous):
                saved = mv_studio.save(mv_studio._register({**project, **previous}, self.original))
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageParticles": restored},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                parse.assert_called_once_with(self.original, "Edited effects", preview_split=False,
                                              preview_stage_title=False, preview_stage_particles=True)
                self.assertEqual(reopened["tracks"], project["tracks"])
                self.assertEqual(reopened["stageParticles"], restored)

        saved = mv_studio.save(mv_studio._register({**project, "stageParticles": restored}, self.original))
        with ZipFile(saved["path"]) as archive, patch(
            "webtools.core.mv_studio_timeline.parse_timeline",
        ) as parse:
            current = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_not_called()
        self.assertEqual(current["stageParticles"], restored)

    def test_saved_particle_upgrade_preserves_existing_cue_and_emitter_coverage(self):
        project = mv_studio._blank("Edited effects")
        project["duration"] = 62
        project["tracks"] = [{
            "id": "effect", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/par_15_foot_wave",
            "events": [{"id": event, "label": event, "start": time, "duration": 1.6,
                        "values": {"playableClass": "CustomControlClip"}}
                       for event, time in (("first", 44), ("second", 59))],
        }]
        wave, umbrella, added = ([{"png": value, "width": 1, "height": 1}] for value in (
            "d2F2ZQ==", "dW1icmVsbGE=", "YWRkZWQ=",
        ))
        waves = [{"texture": 0, "birth": time} for time in (0, .15)]
        center = {"texture": 1, "birth": 0}
        first = {"trackId": "effect", "eventId": "first", "template": 0}
        second = {"trackId": "effect", "eventId": "second", "template": 1}
        legacy = {"cues": [first, second], "textures": [wave, umbrella], "templates": [waves, [center]]}
        project["stageParticles"] = legacy
        upgraded_waves = [{**emitter, "texture": 1} for emitter in waves]
        upgraded_center = {**center, "texture": 2}
        new_emitter = {"texture": 0, "birth": 0}
        upgraded = {
            "schema": mv_studio_stage_particles.SCHEMA,
            "cues": [{**second, "template": 0}, {**first, "template": 1}],
            "textures": [added, wave, umbrella],
            "templates": [[upgraded_center, new_emitter], [*upgraded_waves, new_emitter]],
        }
        saved = mv_studio.save(mv_studio._register(project, self.original))
        incomplete = {
            "missing cue": {**upgraded, "cues": upgraded["cues"][:1]},
            "missing emitter": {**upgraded, "templates": [upgraded["templates"][0], upgraded_waves[:1]]},
            "changed emitter texture": {**upgraded, "templates": [[new_emitter], upgraded["templates"][1]]},
            "changed emitter birth": {**upgraded, "templates": [
                upgraded["templates"][0], [upgraded_waves[0], {**upgraded_waves[1], "birth": .85}, new_emitter],
            ]},
        }
        cases = [(reason, {"return_value": {"stageParticles": partial}}, legacy)
                 for reason, partial in incomplete.items()]
        cases += [
            ("absent output", {"return_value": {}}, legacy),
            ("failed parse", {"side_effect": ValueError("Original preview could not be regenerated.")}, legacy),
            ("complete upgrade", {"return_value": {"stageParticles": upgraded}}, upgraded),
        ]
        for reason, parse_result, expected in cases:
            with self.subTest(reason=reason):
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", **parse_result,
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                parse.assert_called_once_with(self.original, "Edited effects", preview_split=False,
                                              preview_stage_title=False, preview_stage_particles=True)
                self.assertEqual(reopened["tracks"], project["tracks"])
                self.assertEqual(reopened["stageParticles"], expected)
                self.assertEqual(mv_studio._native(reopened), self.original)

    def test_saved_ribbon_can_add_shine_without_replacing_meshes(self):
        project = mv_studio._blank("Edited ribbon")
        project["tracks"] = [{
            "id": "ribbon", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/dis_par_01-02_obi",
            "events": [{"id": "first", "start": 12, "duration": 30, "values": {}}],
        }]
        original = {"cues": [{"eventId": "first"}], "geometry": {"positions": [[0, 1, 2]]}}
        shine = {"cues": [{"trackId": "ribbon", "eventId": "first"}]}
        project["stageRibbons"] = original
        saved = mv_studio.save(mv_studio._register(project, self.original))
        new_ribbon = {"geometry": {"positions": [[2, 1, 0]]}}
        for added in ({}, {"shine": shine}):
            with self.subTest(has_shine=bool(added)), ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline",
                return_value={"stageRibbons": {**new_ribbon, **added}},
            ) as parse:
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                self.assertEqual(reopened["stageRibbons"], {**original, **added})
                self.assertEqual(reopened["tracks"], project["tracks"])
                parse.assert_called_once_with(self.original, "Edited ribbon", preview_split=False,
                                              preview_stage_title=True, preview_stage_ribbons=True)

    def test_saved_spotlight_source_restores_effect_without_changing_event_time(self):
        project = mv_studio._blank("Edited spotlight")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA, "cues": []}
        project["tracks"] = [{
            "id": "spot", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/par_12_spot",
            "events": [{"id": "clip", "start": 76, "duration": 3, "values": {}}],
        }]
        spotlight = {"trackId": "spot", "eventId": "clip", "duration": 1.8}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
            "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSpotlight": spotlight},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited spotlight", preview_split=False,
                                      preview_stage_title=False, preview_stage_spotlight=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSpotlight"], spotlight)

    def test_saved_speed_background_uses_original_binding_after_event_rename(self):
        project = mv_studio._blank("Edited display")
        project["stageTitle"] = {"particleSchema": 2}
        project["tracks"] = [{
            "id": "display", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/light",
            "events": [{"id": "clip", "label": "Edited name", "start": 78, "duration": 24,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "9155575924868579619"}}}],
        }]
        display = {"trackId": "display", "eventId": "clip", "duration": 50}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
            "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSpeedBack": display},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited display", preview_split=False,
                                      preview_stage_title=False, preview_stage_speed_back=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageTitle"], project["stageTitle"])
        self.assertEqual(reopened["stageSpeedBack"], display)

        legacy_display = {**display, "matrix": [1, 2, 3]}
        project["stageSpeedBack"] = legacy_display
        saved = mv_studio.save(mv_studio._register(project, self.original))
        stars = {"seed": 3710075818}
        for companion in ({}, {"centerStars": stars}):
            with self.subTest(restored=bool(companion)), ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={
                    "stageSpeedBack": {**display, "matrix": [3, 2, 1], **companion},
                },
            ):
                reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                self.assertEqual(reopened["stageSpeedBack"], {**legacy_display, **companion})
                self.assertEqual(reopened["tracks"], project["tracks"])

        original_stars = {"seed": 3710075818, "texture": [{"width": 512, "height": 512, "png": "source"}]}
        moving = [{"name": "speed", "rate": 250}]
        rebuilt = {**display, "centerStars": original_stars, "movingCompanions": moving}
        edited_stars = {**original_stars, "position": [2, 3, 4]}
        incompatible = {**edited_stars, "texture": [{"width": 512, "height": 512, "png": "modified"}]}
        cases = [
            ({}, {"centerStars": original_stars, "movingCompanions": moving}),
            ({"centerStars": edited_stars}, {"movingCompanions": moving}),
            ({"centerStars": incompatible}, {}),
            ({"centerStars": None}, {}),
            ({"eventId": "unrelated"}, {}),
            ({"movingCompanions": [{"name": "user value"}]}, {"centerStars": original_stars}),
        ]
        for previous, additions in cases:
            with self.subTest(previous=previous):
                project["stageSpeedBack"] = {**legacy_display, **previous}
                saved = mv_studio.save(mv_studio._register(project, self.original))
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSpeedBack": rebuilt},
                ):
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                self.assertEqual(reopened["stageSpeedBack"], {**legacy_display, **previous, **additions})
                self.assertEqual(reopened["tracks"], project["tracks"])

    def test_saved_display_lights_retain_edited_cue_after_atlas_recovery(self):
        project = mv_studio._blank("Edited display")
        project["stageTitle"] = {"particleSchema": 2}
        project["tracks"] = [{
            "id": "display", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/light",
            "events": [{"id": "clip", "label": "Edited lights", "start": 45, "duration": 12,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "-3728220010162171534"}}}],
        }]
        descriptor = {"trackId": "display", "eventId": "clip", "emitters": [{"name": "light_up"}]}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageDisplayLights": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited display", preview_split=False,
                                      preview_stage_title=False, preview_stage_display_lights=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageDisplayLights"], descriptor)

    def test_saved_falling_effects_share_only_matching_atlases_and_keep_edits(self):
        base = mv_studio._blank("Edited display pairs")
        base["stageTitle"] = {"particleSchema": 2}
        base["tracks"] = [{
            "id": "display", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/light",
            "events": [{"id": "early", "label": "Renamed lights", "start": 14, "duration": 8,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "-1918126523244823858"}}}],
        }]
        light, star = [{"png": "source light"}], [{"png": "source star"}]
        base["stageDisplayLights"] = {"texture": light}
        descriptor = {"textures": [light, star], "cues": [{"eventId": "early"}]}
        for saved_star, expected in ((star, "speedBackCenterStars"), ([{"png": "edited star"}], star)):
            with self.subTest(saved_star=saved_star):
                base["stageSpeedBack"] = {"centerStars": {"texture": saved_star}, "movingCompanions": []}
                saved = mv_studio.save(mv_studio._register(base, self.original))
                with ZipFile(saved["path"]) as archive, patch(
                        "webtools.core.mv_studio_timeline.parse_timeline",
                        return_value={"stageFallingEffects": descriptor},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                parse.assert_called_once_with(self.original, "Edited display pairs", preview_split=False,
                                              preview_stage_title=False, preview_stage_falling_effects=True)
                self.assertEqual(reopened["tracks"], base["tracks"])
                self.assertEqual(reopened["stageSpeedBack"], base["stageSpeedBack"])
                self.assertEqual(reopened["stageFallingEffects"]["textures"], ["displayLights", expected])

    def test_saved_fracture_cue_preserves_edited_timing_and_embeds_a_conflicting_atlas(self):
        project = mv_studio._blank("Edited fracture")
        project["stageTitle"] = {"particleSchema": 2}
        project["tracks"] = [{
            "id": "fracture", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Display/break",
            "events": [{"id": "transition", "label": "Edited transition", "start": 76.7, "duration": 2,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "-277186095147178148"}}}],
        }]
        crack, light, original_stars = [{"png": "break"}], [{"png": "lights"}], [{"png": "source atlas"}]
        project["stageDisplayLights"] = {"texture": light}
        project["stageSpeedBack"] = {"centerStars": {"texture": [{"png": "edited atlas"}]}, "movingCompanions": []}
        descriptor = {"textures": [crack, light, original_stars], "trackId": "fracture", "eventId": "transition"}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageBreak": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited fracture", preview_split=False,
                                      preview_stage_title=False, preview_stage_break=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSpeedBack"], project["stageSpeedBack"])
        self.assertEqual(reopened["stageBreak"], {**descriptor, "textures": [crack, "displayLights", original_stars]})

    def test_saved_finale_floor_preserves_shifted_cue_and_display_atlas(self):
        project = mv_studio._blank("Edited floor")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        project["tracks"] = [{
            "id": "flo", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/flo",
            "events": [{"id": "floor", "label": "Retimed floor", "start": 110, "duration": 3,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "-1916851570489530364"},
                                   "offset": {"x": 1, "y": 2, "z": -1}}}],
        }]
        texture = [{"png": "native stars"}]
        project["stageSpeedBack"] = {"centerStars": {"texture": texture}, "movingCompanions": []}
        descriptor = {"trackId": "flo", "eventId": "floor", "textures": [texture]}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageFinaleFloor": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited floor", preview_split=False,
                                      preview_stage_title=False, preview_stage_finale_floor=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSpeedBack"], project["stageSpeedBack"])
        self.assertEqual(reopened["stageFinaleFloor"], {**descriptor, "textures": ["speedBackCenterStars"]})

    def test_saved_spark_pair_preserves_shifted_cues_and_uses_the_original_atlas(self):
        project = mv_studio._blank("Edited sparks")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        project["tracks"] = [{
            "id": f"sparks-{index}", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": f"StageEffect/Expert/Control/sparks_B_{index:02}",
            "events": [{"id": f"sparks-cue-{index}", "label": f"Retimed sparks {index}",
                        "start": 76 + .25 * index, "duration": 3,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "-8184682665616244301"},
                                   "offset": {"x": index, "y": 5, "z": -1}}}],
        } for index in (1, 2)]
        texture = [{"png": "native stars"}]
        project["stageSpeedBack"] = {"centerStars": {"texture": [{"png": "edited stars"}]}}
        descriptor = {"textures": [texture], "cues": [
            {"trackId": track["id"], "eventId": track["events"][0]["id"]} for track in project["tracks"]
        ]}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSparksB": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited sparks", preview_split=False,
                                      preview_stage_title=False, preview_stage_sparks_b=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSpeedBack"], project["stageSpeedBack"])
        self.assertEqual(reopened["stageSparksB"], descriptor)

    def test_saved_front_sparks_restore_the_clip_seeds_without_replacing_side_sparks(self):
        project = mv_studio._blank("Edited front sparks")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        project["tracks"] = [{
            "id": "front-sparks", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/sparks_A_02",
            "events": [{"id": "front-cue", "label": "Retimed front sparks", "start": 78.75, "duration": 2.5,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "6581900986414377151"},
                                   "offset": {"x": 2, "y": 3, "z": 4}}}],
        }]
        texture = [{"png": "native stars"}]
        project["stageSpeedBack"] = {"centerStars": {"texture": texture}}
        project["stageSparksB"] = {"textures": ["speedBackCenterStars"], "cues": [{"trackId": "other"}]}
        descriptor = {"textures": [texture], "cues": [{"trackId": "front-sparks", "eventId": "front-cue", "seed": 200}]}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSparksA": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited front sparks", preview_split=False,
                                      preview_stage_title=False, preview_stage_sparks_a=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSparksB"], project["stageSparksB"])
        self.assertEqual(reopened["stageSparksA"], {**descriptor, "textures": ["speedBackCenterStars"]})

    def test_saved_spark_primary_upgrades_when_it_shares_the_authentic_atlas(self):
        project = mv_studio._blank("Existing front sparks")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        project["tracks"] = [{
            "id": "front", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/sparks_A_01",
            "events": [{"id": "burst", "label": "Moved sparks", "start": 75, "duration": 5,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "6581900986414377151"},
                                   "offset": {"x": 2, "y": 5, "z": -3}}}],
        }]
        alias = "speedBackCenterStars"
        authentic = [{"png": "native sparks"}]
        primary = {"name": "hibana_01", "preservedField": "saved value"}
        secondary = {"name": "hibana_02"}
        cues = [{"trackId": "front", "eventId": "burst", "seed": 100}]
        original = {"textures": [authentic], "emitters": [{"name": "hibana_01"}, secondary], "cues": cues}
        saved = {"textures": [alias], "emitters": [primary], "cues": cues}
        project["stageSparksA"] = saved
        for atlas, expected in ((authentic, [primary, secondary]), ([{"png": "custom"}], [primary])):
            with self.subTest(atlas=atlas):
                project["stageSpeedBack"] = {"centerStars": {"texture": atlas}}
                result = mv_studio.save(mv_studio._register(project, self.original))
                with ZipFile(result["path"]) as archive, patch(
                        "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSparksA": original},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                self.assertTrue(parse.call_args.kwargs["preview_stage_sparks_a"])
                self.assertEqual(reopened["tracks"], project["tracks"])
                self.assertEqual(reopened["stageSparksA"], {**saved, "emitters": expected})

    def test_legacy_originals_stay_readable(self):
        token = "a" * 32
        legacy = self.root / "native" / (token + ".unity")
        legacy.parent.mkdir()
        legacy.write_bytes(self.original)
        self.assertEqual(mv_studio._native({"token": token}), self.original)
        self.assertIsNone(mv_studio._native({"token": "../" + token}))
        self.assertIsNone(mv_studio._native({"token": "b" * 32}))
