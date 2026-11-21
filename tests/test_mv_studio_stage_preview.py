"""Optional stage previews preserve the complete game import."""
from copy import deepcopy
from hashlib import sha256
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from webtools.core import cri_audio_decode, mv_studio, mv_studio_actor_cache, mv_studio_game, mv_studio_quality


class StagePreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.history = []
        self.download_flags = []
        self.missing = set()
        self.failed = set()
        self.quality = {"values": {"rendering_resolution": 720}}
        light = self.track("light", "lighting")
        light["events"].extend([
            dict(light["events"][0], id="held-light", start=-2.0, duration=2.0),
            dict(light["events"][0], id="future-light", start=4.0),
        ])
        late_light = self.track("late-light", "lighting")
        late_light["events"][0]["start"] = 5.0
        self.tracks = [
            self.track("live", "camera", binding="/EntryPoint/Live/MainCamera"),
            self.track("unbound", "camera"),
            self.track("other-camera", "camera", binding="/EntryPoint/Live/Other"),
            light,
            late_light,
            self.track("muted-light", "lighting", muted=True),
            self.track("mouth", "mouth"),
        ]
        self.selection = {
            "name": "Stage fixture", "region": "gl", "platform": "android", "liveId": 10, "assetId": 11,
            "timeline": self.asset("timeline"),
            "stage": {
                "name": "Original stage", "sceneName": "native_stage",
                "model": self.asset("stage"), "effect": self.asset("effect"),
                "props": self.asset("props"), "background": self.asset("background"),
            },
            "performers": [{"position": 1, "memberId": 210, "model": self.asset("actor")}],
            "audio": {"cue": "song", "acb": self.asset("audio")},
        }
        self.addCleanup(patch.stopall)
        patch.object(mv_studio_game, "resolve", return_value=self.selection).start()
        patch.object(mv_studio_game, "load_asset", side_effect=self.load_asset).start()
        patch.object(mv_studio_quality, "read_quality", side_effect=lambda *a, **kw: deepcopy(self.quality)).start()
        patch.object(mv_studio_actor_cache, "open_cache", return_value=None).start()
        patch.object(mv_studio, "_root", return_value=self.root).start()
        patch.object(mv_studio, "_timeline", side_effect=lambda path: (path.read_bytes(), {
            "duration": 12.0, "tracks": deepcopy(self.tracks),
        })).start()
        patch.object(mv_studio, "_preview", side_effect=self.preview).start()
        patch.object(mv_studio, "_motion", side_effect=self.motion).start()
        patch.object(cri_audio_decode, "decode_cue").start()
        patch.object(mv_studio, "_song_audio", return_value={"url": "/api/mv-studio/media/test.wav", "duration": 14.0}).start()
        patch.object(mv_studio, "_register", side_effect=lambda project, native: {
            **project, "token": native.hex(), "nativeTimeline": True,
        }).start()

    @staticmethod
    def asset(name):
        return {"table": "test-assets", "asset": name, "available": True}

    @staticmethod
    def track(identity, kind, **fields):
        return {
            "id": identity, "kind": kind, "label": identity,
            "events": [{"id": identity + "-event", "start": 0.0, "duration": 12.0,
                        "values": {"keyframes": [{"time": 0, "position": [1, 2, 3]}]}}],
            **fields,
        }

    def load_asset(self, root, descriptor, *, download, deadline):
        name = descriptor["asset"]
        self.download_flags.append(download)
        self.history.append(("load", name))
        return None if name in self.missing else name.encode()

    def preview(self, path, **kwargs):
        name = path.read_bytes().decode()
        self.history.append(("preview", name))
        if name in self.failed:
            raise ValueError("Invalid preview")
        media = sha256(name.encode()).hexdigest()[:32]
        return f"/api/mv-studio/media/{media}.glb", {}

    def motion(self, *args):
        self.history.append(("motion", "actor"))
        return [], {"bodySegments": []}

    def import_game(self, **kwargs):
        return mv_studio.load_game(self.root, region="gl", platform="android", live_id=10,
                                   asset_id=11, language="en", **kwargs)

    def test_snapshot_is_detached_before_cast_and_uses_existing_download_consent(self):
        baseline = self.import_game(download=True)
        original_history = self.history[:]
        self.history.clear()
        self.download_flags.clear()
        received = []

        def on_stage(snapshot):
            self.assertEqual(self.history, original_history[:original_history.index(("load", "actor"))])
            self.assertEqual(set(snapshot), {"duration", "stage", "assets", "tracks", "quality"})
            self.assertEqual([track["id"] for track in snapshot["tracks"]], ["light"])
            self.assertEqual([event["id"] for event in snapshot["tracks"][0]["events"]], ["light-event", "held-light"])
            self.assertEqual([asset["kind"] for asset in snapshot["assets"]], ["effect", "props"])
            self.assertEqual(snapshot["duration"], 12.0)
            json.dumps(snapshot)
            received.append(snapshot)
            snapshot["stage"]["label"] = "changed stage"
            snapshot["assets"][0]["label"] = "changed effect"
            snapshot["quality"]["values"]["rendering_resolution"] = 300
            snapshot["tracks"][0]["events"][0]["values"]["keyframes"][0]["position"][0] = 100

        project = self.import_game(download=True, on_stage=on_stage)
        self.assertEqual(len(received), 1)
        self.assertEqual(self.history, original_history)
        self.assertEqual(project, baseline)
        self.assertEqual(project["duration"], 14.0)
        self.assertEqual(self.download_flags, [True] * len(self.download_flags))
        self.assertGreater(len(self.download_flags), 0)

    def test_missing_or_unrenderable_stage_does_not_publish_a_preview(self):
        for missing, failed in (({"stage"}, set()), (set(), {"stage"})):
            with self.subTest(missing=missing, failed=failed):
                self.missing, self.failed = missing, failed
                callback = Mock()
                project = self.import_game(on_stage=callback)
                callback.assert_not_called()
                self.assertIsNone(project["stage"])
                self.assertTrue(project["performers"][0]["glb"])
                self.assertIn("The original stage model is unavailable for preview.", project["warnings"])

    def test_valid_stage_is_published_when_effect_preview_fails(self):
        self.failed = {"effect"}
        callback = Mock()
        project = self.import_game(on_stage=callback)
        callback.assert_called_once()
        preview, = callback.call_args.args
        self.assertEqual(preview["stage"], project["stage"])
        self.assertEqual([asset["kind"] for asset in preview["assets"]], ["props"])
        self.assertIn("Stage effects: Invalid preview", project["warnings"])
        self.assertIn(("motion", "actor"), self.history)

    def test_missing_timeline_does_not_publish_a_preview(self):
        self.missing = {"timeline"}
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "original MV timeline pack is missing"):
            self.import_game(on_stage=callback)
        callback.assert_not_called()
        self.assertNotIn(("preview", "stage"), self.history)

    def test_callback_failure_releases_import_and_does_not_continue_cast(self):
        callback = Mock(side_effect=BrokenPipeError("preview client disconnected"))
        with self.assertRaisesRegex(BrokenPipeError, "preview client disconnected"):
            self.import_game(on_stage=callback)
        self.assertNotIn(("load", "actor"), self.history)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(self.import_game()["performers"][0]["glb"])
