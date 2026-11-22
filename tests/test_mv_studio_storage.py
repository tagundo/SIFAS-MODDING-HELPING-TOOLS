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

    def test_saved_butterfly_recovers_shine_with_the_original_atlas_and_cue(self):
        project = mv_studio._blank("Edited butterfly")
        project["duration"] = 60
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        cue = {"id": "original-cue", "label": "Edited cue", "start": 33, "duration": 12,
               "values": {"offset": {"x": .125, "y": 0, "z": -2}, "clipIn": .5}}
        track = {"id": "opening", "kind": "effects", "nativeClass": "CustomControlTrack",
                 "label": "StageEffect/Expert/Control/par_13_butterfly", "events": [cue]}
        legacy = {"schema": 1, "trackId": track["id"], "eventId": cue["id"],
                  "glow": {"profile": "opening"}, "glowTexture": [{"png": "original atlas"}]}
        shine = {"profile": "opening", "uv": [.25, .25, .75, 0]}
        rebuilt = {**legacy, "shine": shine}
        for previous, events, source, restores in (
                (legacy, [cue], self.original, True),
                ({**legacy, "glowTexture": [{"png": "custom atlas"}]}, [cue], self.original, False),
                ({**legacy, "eventId": "different"}, [cue], self.original, False),
                (legacy, [], self.original, False),
                (legacy, [cue], None, False)):
            with self.subTest(previous=previous, events=events, source=source):
                document = {**project, "tracks": [{**track, "events": events}], "stageButterfly": previous}
                saved = mv_studio.save(mv_studio._register(document, source))
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageButterfly": rebuilt},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                if source is not None:
                    parse.assert_called_once_with(self.original, "Edited butterfly", preview_split=False,
                                                  preview_stage_title=False, preview_stage_butterfly=True)
                else:
                    parse.assert_not_called()
                self.assertEqual(reopened["tracks"], document["tracks"])
                self.assertEqual(reopened["stageButterfly"], rebuilt if restores else previous)

        document = {**project, "tracks": [track], "stageButterfly": rebuilt}
        saved = mv_studio.save(mv_studio._register(document, self.original))
        with ZipFile(saved["path"]) as archive, patch("webtools.core.mv_studio_timeline.parse_timeline") as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_not_called()
        self.assertEqual(reopened["stageButterfly"], rebuilt)

    def test_saved_butterfly_finale_carries_original_dust_without_replacing_edits(self):
        project = mv_studio._blank("Edited finale")
        project["duration"] = 110
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        cue = {"id": "finale-cue", "label": "Edited cue", "start": 93, "duration": 8,
               "values": {"offset": {"x": -2, "y": .5, "z": 0}, "clipIn": 1}}
        track = {"id": "finale-track", "kind": "effects", "nativeClass": "CustomControlTrack",
                 "label": "StageEffect/Expert/Control/par_14_butterfly", "events": [cue]}
        finale = {"schema": 1, "trackId": track["id"], "eventId": cue["id"], "glow": {"profile": "finale"}}
        legacy = {"schema": 1, "finale": finale, "glowTexture": [{"png": "authentic atlas"}],
                  "shine": {"profile": "opening"}}
        dust = {"profile": "finale", "emitters": [{"role": "add"}, {"role": "alpha"}]}
        rebuilt = {**legacy, "finale": {**finale, "dust": dust}}
        wrong_cue = {**legacy, "finale": {**finale, "eventId": "different"}}
        wrong_atlas = {**legacy, "glowTexture": [{"png": "custom atlas"}]}
        edited = {**legacy, "finale": {**finale, "dust": {"profile": "custom"}}}
        for previous, events, source, expected, reparses in (
                (legacy, [cue], self.original, rebuilt, True),
                (wrong_cue, [cue], self.original, wrong_cue, True),
                (wrong_atlas, [cue], self.original, wrong_atlas, True),
                (legacy, [], self.original, legacy, True),
                (legacy, [cue], None, legacy, False),
                (edited, [cue], self.original, edited, False),
                (rebuilt, [cue], self.original, rebuilt, False)):
            with self.subTest(previous=previous, events=events, source=source):
                document = {**project, "tracks": [{**track, "events": events}], "stageButterfly": previous}
                saved = mv_studio.save(mv_studio._register(document, source))
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageButterfly": rebuilt},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                if reparses:
                    parse.assert_called_once_with(self.original, "Edited finale", preview_split=False,
                                                  preview_stage_title=False, preview_stage_butterfly=True)
                else:
                    parse.assert_not_called()
                self.assertEqual(reopened["stageButterfly"], expected)
                self.assertEqual(reopened["tracks"], document["tracks"])

    def test_saved_rain_recovers_the_original_cues_still_in_the_edited_project(self):
        from webtools.core import mv_studio_rain

        project = mv_studio._blank("Edited rain")
        project["duration"] = 60
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        first = {"id": "rain:0", "label": "Edited cue", "start": 1, "duration": 40,
                 "values": {"offset": {"x": -.125, "y": .5, "z": 2}, "clipIn": 1}}
        second = {"id": "rain:1", "label": "Second rain", "start": 41, "duration": 6, "values": {}}
        track = {"id": "rain", "kind": "effects", "nativeClass": "CustomControlTrack", "label": mv_studio_rain.TRACK}
        cues = [{"trackId": track["id"], "eventId": cue["id"], "profile": profile}
                for cue, profile in ((first, "01"), (second, "02"))]
        rain = {"schema": 1, "cues": cues, "texture": [{"png": "original atlas"}]}
        custom = {**rain, "texture": [{"png": "custom atlas"}]}
        for events, source, previous, expected in (
                ([first, second], self.original, None, rain),
                ([first], self.original, None, {**rain, "cues": cues[:1]}),
                ([], self.original, None, None),
                ([first], None, None, None),
                ([first, second], self.original, custom, custom)):
            with self.subTest(events=events, source=source, previous=previous):
                document = {**project, "tracks": [{**track, "events": events}]}
                if previous is not None:
                    document["stageRain"] = previous
                saved = mv_studio.save(mv_studio._register(document, source))
                with ZipFile(saved["path"]) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageRain": rain},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                if source and events:
                    parse.assert_called_once_with(self.original, "Edited rain", preview_split=False,
                                                  preview_stage_title=False, preview_stage_rain=True)
                else:
                    parse.assert_not_called()
                self.assertEqual(reopened.get("stageRain"), expected)
                self.assertEqual(reopened["tracks"], document["tracks"])

    def test_saved_rain_adds_floor_effects_only_for_compatible_original_cues(self):
        from webtools.core import mv_studio_rain

        project = mv_studio._blank("Edited rain floor")
        project["duration"] = 52
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        first = {"id": "rain:0", "label": "Edited cue", "start": 3, "duration": 39,
                 "values": {"offset": {"x": -.125, "y": .5, "z": 2}, "clipIn": 1}}
        second = {"id": "rain:1", "label": "Second rain", "start": 42, "duration": 6, "values": {}}
        track = {"id": "rain", "kind": "effects", "nativeClass": "CustomControlTrack", "label": mv_studio_rain.TRACK}
        cues = [{"trackId": track["id"], "eventId": cue["id"], "profile": profile, "position": [0, 1, 2]}
                for cue, profile in ((first, "01"), (second, "02"))]
        atlas = {"wave": [{"png": "original wave"}], "glow": [{"png": "original glow"}]}
        native_impact = {"wave": {"tiles": [4, 4]}, "glow": {"uv": [.5] * 4}}
        original = {"schema": 1, "cues": [{**cue, "impact": native_impact} for cue in cues],
                    "texture": [{"png": "original rain"}], "impactTextures": atlas}
        saved = {"schema": 1, "texture": [{"png": "custom rain"}], "cues": cues}
        upgraded = {**saved, "impactTextures": atlas, "cues": original["cues"]}
        partial = {**saved, "impactTextures": atlas, "cues": [original["cues"][0], cues[1]]}
        wrong_profile = {**saved, "cues": [{**cues[0], "profile": "02"}, cues[1]]}
        incompatible = {**partial, "impactTextures": {**atlas, "glow": [{"png": "custom floor glow"}]}}
        custom_impact_without_atlas = {**saved, "cues": [{**cues[0], "impact": {"wave": {}}}, cues[1]]}
        for loaded, events, source, expected, reparses in (
                (saved, [first, second], self.original, upgraded, True),
                (saved, [first], self.original, partial, True),
                (partial, [first, second], self.original, upgraded, True),
                (wrong_profile, [first], self.original, wrong_profile, True),
                (incompatible, [first, second], self.original, incompatible, True),
                (custom_impact_without_atlas, [first, second], self.original, custom_impact_without_atlas, True),
                (saved, [first, second], None, saved, False),
                (upgraded, [first, second], self.original, upgraded, False)):
            with self.subTest(loaded=loaded, events=events, source=source):
                document = {**project, "tracks": [{**track, "events": events}], "stageRain": loaded}
                archive_path = mv_studio.save(mv_studio._register(document, source))["path"]
                with ZipFile(archive_path) as archive, patch(
                    "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageRain": original},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                if reparses:
                    parse.assert_called_once_with(self.original, "Edited rain floor", preview_split=False,
                                                  preview_stage_title=False, preview_stage_rain=True)
                else:
                    parse.assert_not_called()
                self.assertEqual(reopened["stageRain"], expected)
                self.assertEqual(reopened["tracks"], document["tracks"])

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

    def test_saved_sparks_gain_missing_emitters_when_they_share_the_authentic_atlas(self):
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
        edited_secondary = {**secondary, "preservedField": "another saved value"}
        smoke = {"name": "smoke"}
        cues = [{"trackId": "front", "eventId": "burst", "seed": 100}]
        original = {"textures": [authentic], "emitters": [{"name": "hibana_01"}, secondary, smoke], "cues": cues}
        cases = (
            (authentic, [primary], [primary, secondary, smoke]),
            (authentic, [primary, edited_secondary], [primary, edited_secondary, smoke]),
            ([{"png": "custom"}], [primary, edited_secondary], [primary, edited_secondary]),
        )
        for atlas, emitters, expected in cases:
            with self.subTest(atlas=atlas, emitters=len(emitters)):
                saved = {"textures": [alias], "emitters": emitters, "cues": cues}
                project["stageSparksA"] = saved
                project["stageSpeedBack"] = {"centerStars": {"texture": atlas}}
                result = mv_studio.save(mv_studio._register(project, self.original))
                with ZipFile(result["path"]) as archive, patch(
                        "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSparksA": original},
                ) as parse:
                    reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
                self.assertTrue(parse.call_args.kwargs["preview_stage_sparks_a"])
                self.assertEqual(reopened["tracks"], project["tracks"])
                self.assertEqual(reopened["stageSparksA"], {**saved, "emitters": expected})

    def test_saved_roop_restores_native_atlas_and_preserves_the_edited_cue(self):
        project = mv_studio._blank("Edited sparks_roop")
        project["stageParticles"] = {"schema": mv_studio_stage_particles.SCHEMA}
        project["tracks"] = [{
            "id": "roop", "kind": "effects", "nativeClass": "CustomControlTrack",
            "label": "StageEffect/Expert/Control/sparks_roop",
            "events": [{"id": "spray", "label": "Retimed spray", "start": 75.5, "duration": 16,
                        "values": {"prefabGameObject": {"m_FileID": 0, "m_PathID": "1069439206166195116"},
                                   "offset": {"x": 3, "y": 1, "z": 2}}}],
        }]
        project["stageSpeedBack"] = {"centerStars": {"texture": [{"png": "edited atlas"}]}}
        original_atlas = [{"png": "native sparks"}]
        project["stageSparksB"] = {"textures": ["speedBackCenterStars"]}
        descriptor = {"textures": [original_atlas], "cues": [{"trackId": "roop", "eventId": "spray"}]}
        saved = mv_studio.save(mv_studio._register(project, self.original))
        with ZipFile(saved["path"]) as archive, patch(
                "webtools.core.mv_studio_timeline.parse_timeline", return_value={"stageSparksRoop": descriptor},
        ) as parse:
            reopened = mv_studio._open_saved(archive, mv_studio._archive_entries(archive))
        parse.assert_called_once_with(self.original, "Edited sparks_roop", preview_split=False,
                                      preview_stage_title=False, preview_stage_sparks_roop=True)
        self.assertEqual(reopened["tracks"], project["tracks"])
        self.assertEqual(reopened["stageSparksB"], project["stageSparksB"])
        self.assertEqual(reopened["stageSpeedBack"], project["stageSpeedBack"])
        self.assertEqual(reopened["stageSparksRoop"], descriptor)

    def test_legacy_originals_stay_readable(self):
        token = "a" * 32
        legacy = self.root / "native" / (token + ".unity")
        legacy.parent.mkdir()
        legacy.write_bytes(self.original)
        self.assertEqual(mv_studio._native({"token": token}), self.original)
        self.assertIsNone(mv_studio._native({"token": "../" + token}))
        self.assertIsNone(mv_studio._native({"token": "b" * 32}))
