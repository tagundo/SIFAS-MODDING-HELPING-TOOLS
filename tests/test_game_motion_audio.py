"""Original nonzero audio through catalog resolution and timeline scheduling."""
import array
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from webtools.core import game_motion_audio as audio
from webtools.jobs import Job
from test_cri_audio_decode import original_acb, original_awb


class TimelineTests(unittest.TestCase):
    def objects(self, *, muted=False, start=.7166666666666667, cue="original-tone"):
        objects = {}
        def obj(ident, kind, tree):
            value = SimpleNamespace(type=SimpleNamespace(name=kind), read_typetree=lambda: tree,
                assets_file=SimpleNamespace(objects=objects))
            objects[ident] = value
            return value
        obj(1, "MonoScript", {"m_ClassName": "NaviVoiceTrack"})
        obj(2, "MonoScript", {"m_ClassName": "NaviVoiceClip"})
        obj(3, "MonoBehaviour", {"m_Script": {"m_FileID": 0, "m_PathID": 2}, "cueName": cue})
        obj(4, "MonoBehaviour", {"m_Script": {"m_FileID": 0, "m_PathID": 1}, "m_Muted": muted,
            "m_Clips": [{"m_Start": start, "m_ClipIn": .125, "m_Duration": .75, "m_TimeScale": .8,
                         "m_Asset": {"m_FileID": 0, "m_PathID": 3}}]})
        return list(objects.values())

    def test_timeline_follows_verified_voice_clip_pointer_and_preserves_times(self):
        with tempfile.NamedTemporaryFile() as file:
            file.write(b"original typed scene placeholder"); file.flush()
            with patch("UnityPy.load", return_value=SimpleNamespace(objects=self.objects())):
                rows = audio.timeline_events([file.name, file.name])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"kind": "voice", "cue": "original-tone", "startTime": .7166666666666667,
                                  "offset": .125, "playDuration": .75, "playbackRate": .8})

    def test_muted_tracks_are_omitted_and_invalid_timing_is_rejected(self):
        with tempfile.NamedTemporaryFile() as file:
            file.write(b"typed scene"); file.flush()
            with patch("UnityPy.load", return_value=SimpleNamespace(objects=self.objects(muted=True))):
                self.assertEqual(audio.timeline_events([file.name]), [])
            for start in (float("nan"), -1, True, 50000):
                with patch("UnityPy.load", return_value=SimpleNamespace(objects=self.objects(start=start))), self.assertRaises(ValueError):
                    audio.timeline_events([file.name])


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg generates an original ADX test fixture")
class CatalogAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "assets/db/gl").mkdir(parents=True)
        (self.root / "static").mkdir()
        tone = self.root / "tone.adx"
        pcm = array.array("h", [int(18000 * math.sin(index * 2 * math.pi * 440 / 44100)) for index in range(44100)])
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", "44100", "-ac", "1", "-i", "pipe:0", "-c:a", "adpcm_adx", "-y", str(tone)], input=pcm.tobytes(), check=True)
        self.acb = original_acb(cue="original-tone", sheet="original-tone")
        self.awb = original_awb(tone.read_bytes())
        (self.root / "static/acbpack").write_bytes(self.acb)
        (self.root / "static/awbpack").write_bytes(self.awb)
        with sqlite3.connect(self.root / "assets/db/gl/asset_a_en.db") as db:
            db.execute("CREATE TABLE m_asset_sound(sheet_name TEXT, acb_pack_name TEXT, awb_pack_name TEXT)")
            db.execute("CREATE TABLE m_asset_package_mapping(pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER)")
            db.execute("INSERT INTO m_asset_sound VALUES('original-tone','acbpack','awbpack')")
            db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,NULL,0)", [("acbpack", len(self.acb)), ("awbpack", len(self.awb))])
        self.extractor = SimpleNamespace(detect_game_candidates=lambda: [], build_pack_roots=lambda root, extra, game: [str(Path(root) / "static")],
            indexed_pack_file=lambda root, name: str(Path(root) / name) if (Path(root) / name).is_file() else None)

    def prepare(self, *, category="voice", event=None, download=False):
        record = {"region": "gl", "category": category, "download": download, "music_key": "original-tone"}
        events = [] if category == "mv" else [event or {"kind": "voice", "cue": "original-tone", "startTime": .7166666666666667,
                                                       "offset": .125, "playDuration": .75, "playbackRate": .8}]
        with patch.object(audio, "timeline_events", return_value=events), patch.object(audio.game, "_extractor", return_value=self.extractor):
            return audio.prepare_audio(Job("original-audio", "motion-audio"), repo_root=self.root, output_root=self.root / "audio", record=record, timeline_paths=[])

    def test_catalog_raw_packs_decode_nonzero_pcm_and_keep_exact_timing(self):
        original = (self.root / "static/awbpack").read_bytes()
        result = self.prepare(); self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["tracks"]), 1)
        track = result["tracks"][0]
        self.assertEqual(track["startTime"], .7166666666666667)
        self.assertEqual(track["offset"], .125)
        self.assertEqual(track["playbackRate"], .8)
        self.assertEqual(track["envelope"]["kind"], "rms_mouth_openness")
        self.assertEqual(track["envelope"]["step"], .04)
        self.assertTrue(any(value > .5 for value in track["envelope"]["values"]))
        path, mime = audio.get_audio(track["token"])
        self.assertEqual(mime, "audio/wav")
        with wave.open(str(path), "rb") as decoded:
            samples = array.array("h"); samples.frombytes(decoded.readframes(decoded.getnframes()))
        self.assertGreater(sum(value != 0 for value in samples), 40000)
        self.assertGreater(max(abs(value) for value in samples), 10000)
        self.assertEqual((self.root / "static/awbpack").read_bytes(), original)
        self.assertNotIn(str(self.root), str(result))
        with patch.object(audio, "_read_pack", side_effect=AssertionError("A valid decoded cue must not fetch its source again")):
            again = self.prepare()
        self.assertEqual(audio.get_audio(again["tracks"][0]["token"])[0], path)
        (self.root / "static/acbpack").unlink(); (self.root / "static/awbpack").unlink()
        with patch.object(audio, "_read_pack", side_effect=AssertionError("A preserved decoded cue must work offline")):
            offline = self.prepare()
        self.assertEqual(audio.get_audio(offline["tracks"][0]["token"])[0], path)

    def test_selected_live_bgm_uses_exact_catalog_sheet(self):
        result = self.prepare(category="mv")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["tracks"][0]["kind"], "music")
        self.assertEqual(result["tracks"][0]["startTime"], 0)
        self.assertGreaterEqual(result["tracks"][0]["playDuration"], 1.)
        self.assertLess(result["tracks"][0]["playDuration"], 1.002)  # ADX encoder block padding

    def test_unknown_cue_and_missing_packs_report_audio_warning(self):
        event = {"kind": "voice", "cue": "unmapped", "startTime": 0, "offset": 0, "playDuration": 1, "playbackRate": 1}
        result = self.prepare(event=event)
        self.assertEqual(result["tracks"], [])
        self.assertIn("No game sound mapping", result["warnings"][0])
        (self.root / "static/awbpack").unlink()
        result = self.prepare()
        self.assertEqual(result["tracks"], [])
        self.assertIn("missing", result["warnings"][0])

    def test_audio_tokens_reject_paths_unknown_and_expired_entries(self):
        for token in ("../original.wav", "a" * 32, None):
            with self.assertRaises(ValueError):
                audio.get_audio(token)
        result = self.prepare(); token = result["tracks"][0]["token"]
        with audio._LOCK:
            audio._AUDIO[token]["expires"] = 0
        with self.assertRaisesRegex(ValueError, "expired"):
            audio.get_audio(token)

    def test_envelope_is_bounded_and_preserves_actual_silence(self):
        path = self.root / "silence.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000); output.writeframes(b"\0\0" * 80000)
        envelope = audio.mouth_envelope(path, point_limit=12)
        self.assertLessEqual(len(envelope["values"]), 12)
        self.assertTrue(all(value == 0 for value in envelope["values"]))

    def test_corrupted_decoded_cache_is_rebuilt_from_unchanged_original_packs(self):
        result = self.prepare(); path, _ = audio.get_audio(result["tracks"][0]["token"])
        original = path.read_bytes(); path.write_bytes(b"invalid original derivative" * 4)
        rebuilt = self.prepare()
        self.assertEqual(rebuilt["warnings"], [])
        self.assertEqual(audio.get_audio(rebuilt["tracks"][0]["token"])[0].read_bytes(), original)


@unittest.skipUnless(os.environ.get("SIFAS_TEST_TIMELINE"), "Set a private original navigation timeline for timing integration")
class PrivateTimelineTests(unittest.TestCase):
    def test_real_navigation_voice_cue_and_start_match_asset(self):
        rows = audio.timeline_events([os.environ["SIFAS_TEST_TIMELINE"]])
        self.assertTrue(rows)
        self.assertEqual(rows[0]["cue"], os.environ.get("SIFAS_TEST_CUE", "vo_ca_1000110014"))
        self.assertAlmostEqual(rows[0]["startTime"], .7166666666666667, places=8)


if __name__ == "__main__":
    unittest.main()
