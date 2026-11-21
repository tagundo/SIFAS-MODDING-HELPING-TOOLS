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

    def test_legacy_originals_stay_readable(self):
        token = "a" * 32
        legacy = self.root / "native" / (token + ".unity")
        legacy.parent.mkdir()
        legacy.write_bytes(self.original)
        self.assertEqual(mv_studio._native({"token": token}), self.original)
        self.assertIsNone(mv_studio._native({"token": "../" + token}))
        self.assertIsNone(mv_studio._native({"token": "b" * 32}))
