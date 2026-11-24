"""Game-vs-editor frame comparison: alignment, geometry and report contract."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mv_frame_compare as compare  # noqa: E402

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def scene(width=320, height=180, seed=7, phase=0.0):
    """Smooth, structured test frame: gradient, blocks and a moving disc."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.stack([x / width, y / height, 0.5 + 0.5 * np.sin(x / 17 + y / 23)], -1) * 160
    image = Image.fromarray(base.astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for _ in range(14):
        x0, y0 = rng.integers(0, width - 30), rng.integers(0, height - 30)
        draw.rectangle([x0, y0, x0 + rng.integers(8, 30), y0 + rng.integers(8, 30)], fill=tuple(int(v) for v in rng.integers(40, 255, 3)))
    cx = width / 2 + math.cos(phase) * width / 3
    cy = height / 2 + math.sin(phase) * height / 4
    draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(250, 250, 250))
    return np.asarray(image)


def shifted(image, dx, dy):
    result = np.roll(image, (dy, dx), axis=(0, 1))
    return result


class Geometry(unittest.TestCase):
    def test_identical_frames(self):
        frame = scene()
        result = compare.compare(frame, frame, 30)
        self.assertAlmostEqual(result["metrics"]["ssim"], 1, places=5)
        self.assertEqual(result["metrics"]["psnr"], float("inf"))
        self.assertAlmostEqual(result["geometry"]["scale"], 1, places=3)
        self.assertLess(abs(result["geometry"]["dx"]) + abs(result["geometry"]["dy"]), 0.5)

    def test_shift_reports_the_move_that_aligns_the_editor(self):
        game = scene(640, 360)
        editor = shifted(game, 9, -5)  # editor content sits 9 px right and 5 px up
        geometry = compare.compare(game, editor, 30)["geometry"]
        self.assertAlmostEqual(geometry["dx"], -9, delta=1.0)
        self.assertAlmostEqual(geometry["dy"], 5, delta=1.0)

    def test_zoom_estimates_the_game_fov(self):
        game = scene(640, 360)
        # The editor sees a wider view: its content is 5 % smaller than the game's.
        editor = compare._scaled(game.astype(np.float32).mean(-1), 1 / 1.05)
        editor = np.repeat(editor[..., None], 3, -1).clip(0, 255).astype(np.uint8)
        geometry = compare.compare(game, editor, 30)["geometry"]
        self.assertAlmostEqual(geometry["scale"], 1.05, delta=0.011)
        expected = math.degrees(2 * math.atan(math.tan(math.radians(15)) / geometry["scale"]))
        self.assertAlmostEqual(geometry["impliedGameFov"], expected, places=6)
        self.assertLess(geometry["impliedGameFov"], 30)

    def test_smaller_frame_sets_the_comparison_size(self):
        game, editor = scene(640, 360), scene(320, 180)
        result = compare.compare(game, editor)
        self.assertEqual(result["size"], [320, 180])
        self.assertGreater(result["metrics"]["ssim"], 0.8)

    def test_aspect_mismatch_is_refused(self):
        with self.assertRaisesRegex(ValueError, "aspect"):
            compare.compare(scene(320, 180), scene(320, 240))

    def test_worst_tiles_locate_a_local_difference(self):
        game = scene(640, 360)
        editor = game.copy()
        editor[0:45, 560:640] = 0
        tile = compare.compare(game, editor)["worstTiles"][0]
        self.assertEqual((tile["row"], tile["column"]), (0, 7))


class AudioAlignment(unittest.TestCase):
    def test_lag_and_confidence(self):
        rng = np.random.default_rng(3)
        soundtrack = rng.standard_normal(compare.AUDIO_RATE * 20).astype(np.float32)
        lag = 0.75
        video = soundtrack[int(lag * compare.AUDIO_RATE):] + 0.05 * rng.standard_normal(len(soundtrack) - int(lag * compare.AUDIO_RATE))
        result = compare.audio_lag(video, soundtrack, max_lag=5)
        self.assertAlmostEqual(result["lag"], lag, places=3)
        self.assertTrue(result["confident"])
        # Video audio that starts before the soundtrack gives a negative lag.
        early = np.concatenate([np.zeros(compare.AUDIO_RATE // 2, np.float32), soundtrack])
        self.assertAlmostEqual(compare.audio_lag(early, soundtrack, max_lag=5)["lag"], -0.5, places=3)

    def test_looped_audio_is_ambiguous_and_resolved_toward_the_expected_lag(self):
        rng = np.random.default_rng(5)
        bar = rng.standard_normal(compare.AUDIO_RATE * 2).astype(np.float32)
        soundtrack = np.tile(bar, 8)  # exact two-second loop
        video = soundtrack[int(0.25 * compare.AUDIO_RATE):]
        free = compare.audio_lag(video, soundtrack, max_lag=5)
        self.assertTrue(free["ambiguous"])
        self.assertFalse(free["confident"])
        guided = compare.audio_lag(video, soundtrack, max_lag=5, expected=0.25)
        self.assertAlmostEqual(guided["lag"], 0.25, places=3)
        self.assertTrue(guided["ambiguous"] and guided["confident"])

    def test_silence_is_not_aligned(self):
        self.assertIsNone(compare.audio_lag(np.zeros(16000, np.float32), np.zeros(16000, np.float32)))


class Baseline(unittest.TestCase):
    def test_regression_flag(self):
        now = [{"time": 1.0, "metrics": {"ssim": 0.80}, "geometry": {"structureNCC": 0.5}},
               {"time": 2.0, "metrics": {"ssim": 0.90}, "geometry": {"structureNCC": 0.6}}]
        old = {"frames": [{"time": 1.0, "metrics": {"ssim": 0.82}, "geometry": {"structureNCC": 0.5}},
                          {"time": 2.0, "metrics": {"ssim": 0.899}, "geometry": {"structureNCC": 0.6}}]}
        deltas = compare.baseline_deltas(now, old, 0.005)
        self.assertEqual([delta["regressed"] for delta in deltas], [True, False])


@unittest.skipUnless(FFMPEG, "FFmpeg is not installed")
class VideoEndToEnd(unittest.TestCase):
    """Synthetic game export: 30 fps H.264 + AAC whose audio starts 0.4 s into the soundtrack."""

    fps, frames, lag, offset = 30, 90, 0.4, 0.25

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="mv-frame-compare-"))
        rng = np.random.default_rng(11)
        rate = 48000
        soundtrack = (0.3 * rng.standard_normal(rate * 6)).astype(np.float32)
        cls.frames_rgb = [scene(320, 180, seed=5, phase=index * 0.2) for index in range(cls.frames)]
        raw = b"".join(frame.tobytes() for frame in cls.frames_rgb)
        audio = cls.root / "game-audio.wav"
        cls.write_wav(audio, soundtrack[int(cls.lag * rate):], rate)
        cls.write_wav(cls.root / "soundtrack.wav", soundtrack, rate)
        cls.video = cls.root / "game.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "320x180",
                        "-r", str(cls.fps), "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a",
                        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
                        "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-g", "15", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", str(cls.video)], input=raw, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @staticmethod
    def write_wav(path, samples, rate):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())

    def capture(self, name, entries):
        directory = self.root / name
        directory.mkdir()
        shutil.copy(self.root / "soundtrack.wav", directory / "soundtrack.wav")
        frames = []
        for time, image in entries:
            file = f"editor-{time:.4f}.png"
            Image.fromarray(image).save(directory / file)
            frames.append({"time": time, "image": file, "state": {"camera": {"fov": 30}, "liveShot": True}})
        manifest = {"source": {"region": "gl", "platform": "ios", "liveId": 1, "assetId": 2}, "quality": {"mode": 30}, "frames": []}
        capture = {"schema": 1, "kind": "elichika-mv-editor-frames", "manifest": manifest, "soundtrack": "soundtrack.wav",
                   "project": {"soundtrack": {"offset": self.offset}, "warnings": []},
                   "environment": {"webgl": {"renderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))"}}, "frames": frames}
        path = directory / "capture.json"
        path.write_text(json.dumps(capture))
        return path

    def run_compare(self, capture, *extra):
        out = capture.parent / "report"
        code = compare.run(compare.parser().parse_args(["--capture", str(capture), "--video", str(self.video), "--out", str(out), *extra]))
        return code, json.loads((out / "report.json").read_text())

    def test_probe_and_exact_frame_decode(self):
        probe = compare.probe_video(self.video)
        self.assertEqual((probe["width"], probe["height"], probe["fps"]), (320, 180, 30))
        decoded = compare.extract_frames(self.video, probe, {0, 44, 45, 89})
        self.assertEqual(sorted(decoded), [0, 44, 45, 89])
        for index, frame in decoded.items():
            scores = {other: compare.quick_ssim(frame, self.frames_rgb[other], 180) for other in (index - 1, index, index + 1) if 0 <= other < self.frames}
            self.assertEqual(max(scores, key=scores.get), index)

    def test_audio_alignment_maps_timeline_time_to_video_frames(self):
        # videoTime = time + offset - lag = time - 0.15 s, so t = 1.65 s is video frame 45.
        entries = [(1.65, self.frames_rgb[45]), (2.0, self.frames_rgb[round((2.0 - 0.15) * 30)])]
        code, report = self.run_compare(self.capture("aligned", entries))
        self.assertEqual(code, 0)
        self.assertEqual(report["alignment"]["method"], "audio")
        self.assertAlmostEqual(report["alignment"]["lag"], self.lag, delta=0.002)
        self.assertEqual(report["alignment"]["color"], {"matrix": "bt709", "range": "tv", "assumed": False})
        self.assertEqual([frame["videoFrame"] for frame in report["frames"]], [45, 56])
        for frame in report["frames"]:
            self.assertEqual(frame["bestOffset"], 0)
            self.assertFalse(frame["timingSuspect"])
            self.assertGreater(frame["metrics"]["ssim"], 0.95)
            self.assertLess(max(frame["metrics"]["mae"]), 0.03)
            self.assertTrue(Path(frame["composite"]).exists())
        self.assertTrue(report["scope"]["editorFrames"]["software"])

    def test_off_by_one_editor_frame_is_reported_as_timing(self):
        code, report = self.run_compare(self.capture("late", [(1.65, self.frames_rgb[46])]))
        frame = report["frames"][0]
        self.assertEqual(frame["videoFrame"], 45)
        self.assertEqual(frame["bestOffset"], 1)
        self.assertTrue(frame["timingSuspect"])
        self.assertEqual(report["summary"]["timingSuspects"], [1.65])

    def test_manual_offset_and_baseline_regression(self):
        capture = self.capture("manual", [(1.5, self.frames_rgb[45])])
        out = capture.parent / "manual"
        args = ["--capture", str(capture), "--video", str(self.video), "--align", "0", "--out", str(out)]
        compare.run(compare.parser().parse_args(args))
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["frames"][0]["videoFrame"], 45)
        worse = self.capture("worse", [(1.5, np.zeros_like(self.frames_rgb[45]))])
        code = compare.run(compare.parser().parse_args(["--capture", str(worse), "--video", str(self.video), "--align", "0",
                                                        "--baseline", str(out / "report.json"), "--fail-on-regression",
                                                        "--out", str(worse.parent / "report")]))
        self.assertEqual(code, 2)


def runtime_dump(rows):
    """A runtime dump with frame records (id, frameCount, directorTime, deltaTime)."""
    return {"records": [{"id": ident, "kind": "frame", "clock": {"frameCount": frame, "directorTime": t, "deltaTime": dt}}
                        for ident, frame, t, dt in rows]}


class ScreencapGameFrames(unittest.TestCase):
    """Runtime-dump screencaps lag their 'before' record by a few game frames on a software-GPU device."""

    DUMP = runtime_dump([("f1", 100, 10.0, 0.2), ("f2", 104, 11.0, 0.3), ("f3", 106, 11.6, 1 / 3), ("f0", 90, 0.0, 0.1)])

    def test_game_frames_follow_frame_counts_and_unclamped_deltas(self):
        frames = compare.game_frame_times(self.DUMP)
        self.assertEqual(sorted(frames), [100, 101, 102, 103, 104, 105, 106])
        self.assertAlmostEqual(frames[103], 10.7)            # 11.0 - deltaTime 0.3
        self.assertAlmostEqual(frames[101], 10 + 0.7 / 3)    # the rest spread evenly
        self.assertAlmostEqual(frames[105], 11.3)            # 1/3 s is clamped: evenly spread

    def test_candidates_are_the_before_frame_and_the_frames_before_it(self):
        shots = [{"n": 1, "before": {"id": "f3", "directorTime": 11.6}}, {"n": 2, "before": {"id": "f0", "directorTime": 0.0}}]
        times = compare.shot_candidates(shots, self.DUMP, frames_back=3)
        self.assertEqual([(item["shot"], item["frame"], item["time"]) for item in times],
                         [(1, 0, 11.6), (1, 1, 11.3), (1, 2, 11.0), (1, 3, 10.7), (2, 0, 0.0)])

    def test_pinned_director_at_song_end_shows_its_last_time(self):
        # dump3b shot 48: frames 9870-9878 all at 106.666 while the director holds the song end.
        dump = runtime_dump([("e0", 196, 19.4, 0.2), ("e1", 199, 20.0, 0.2), ("e2", 200, 20.0, 1 / 3), ("e3", 204, 20.0, 0.12),
                             ("r1", 300, 30.0, 0.2), ("r2", 302, 29.0, 0.2)])
        frames = compare.game_frame_times(dump)
        self.assertEqual([frames[frame] for frame in range(199, 205)], [20.0] * 6)
        self.assertAlmostEqual(frames[198], 20.0 - 0.2)
        self.assertNotIn(301, frames, "a director that goes back leaves its frames unknown")
        self.assertEqual((frames[300], frames[302]), (30.0, 29.0))
        shots = [{"n": 48, "before": {"id": "e3", "directorTime": 20.0}}, {"n": 47, "before": {"id": "e1", "directorTime": 20.0}},
                 {"n": 50, "before": {"id": "r2", "directorTime": 29.0}}]
        times = compare.shot_candidates(shots, dump, frames_back=3)
        self.assertEqual([(item["shot"], item["frame"], item["time"]) for item in times],
                         [(48, 0, 20.0), (47, 0, 20.0), (47, 1, 19.8), (47, 2, 19.6), (47, 3, 19.4), (50, 0, 29.0), (50, 2, 30.0), (50, 3, 29.8)],
                         "no times the game never showed and no repeats; the fallback spacing only before the first frame")
        times = compare.shot_candidates([{"n": 1, "before": {"id": "e0", "directorTime": 19.4}}], dump, frames_back=2)
        self.assertEqual([item["time"] for item in times], [19.4, 19.2, 19.0], "before the first reconstructed frame")

    def test_screencap_mode_compares_only_game_frame_candidates(self):
        root = Path(tempfile.mkdtemp(prefix="mv-frame-shots-"))
        try:
            game = scene(seed=3, phase=1.0)
            Image.fromarray(game).save(root / "shot-001.png")
            shots = [{"n": 1, "file": "shot-001.png", "before": {"id": "f3", "directorTime": 11.6},
                      "after": {"id": "f4", "directorTime": 12.0}}]
            (root / "shots.json").write_text(json.dumps(shots))
            (root / "dump.json").write_text(json.dumps(self.DUMP))
            frames = []
            # The exact match sits two game frames back; 11.45 is off the game grid and never compared.
            for time, image in ((11.6, scene(seed=3, phase=1.6)), (11.45, game), (11.0, game), (10.7, scene(seed=3, phase=0.4))):
                name = f"editor-{time:.4f}.png"
                Image.fromarray(image).save(root / name)
                frames.append({"time": time, "image": name, "state": {"camera": {"fov": 30}}})
            capture = {"schema": 1, "kind": "elichika-mv-editor-frames", "manifest": {"source": {"liveId": 1}}, "project": {"warnings": []},
                       "frames": frames}
            (root / "capture.json").write_text(json.dumps(capture))
            out = root / "report"
            code = compare.run(compare.parser().parse_args(["--capture", str(root / "capture.json"), "--game-shots", str(root / "shots.json"),
                                                            "--game-dump", str(root / "dump.json"), "--out", str(out)]))
            self.assertEqual(code, 0)
            report = json.loads((out / "report.json").read_text())
            frame = report["frames"][0]
            self.assertEqual((frame["time"], frame["gameFramesBack"]), (11.0, 2))
            self.assertEqual([item["time"] for item in frame["candidates"]], [10.7, 11.0, 11.6])
            self.assertEqual(report["alignment"]["method"], "screencap-game-frames")
            self.assertEqual(report["summary"]["gameFramesBack"], {"2": 1})
            self.assertGreater(frame["metrics"]["ssim"], 0.999)
            written = root / "times.json"
            compare.run(compare.parser().parse_args(["--game-shots", str(root / "shots.json"), "--game-dump", str(root / "dump.json"),
                                                     "--write-shot-times", str(written)]))
            self.assertEqual([item["time"] for item in json.loads(written.read_text())], [11.6, 11.3, 11.0, 10.7])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
