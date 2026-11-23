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


if __name__ == "__main__":
    unittest.main()
