"""Exporting baked camera shots (camera keys and follow camera bakes): the camera writer.

A follow camera bakes dense samples into every shot it covers, and _write_camera writes them as a
DenseClip. A clip that was constant or streamed grows, past its stock m_MuscleClipSize (every
inspected stock camera clip records its serialized size + 188 bytes). The export grows that field
by the growth + 64 bytes, rounded up to 16, and never shrinks it.

The parse marks a shot's keyframes editable by the writer's own rule (_camera_rewrite_refusal), and
the writer sets the clip's m_StopTime to the shot's length: the split-screen sub cameras of 12056
stop a frame before their clip ends (1.7833 s in 1.8 s) or run past it (1.8 s in 0.8667 s).

Original game samples are optional and never stored here: ELICHIKA_STUDIO_TIMELINE_DIR with
[ai]-1203503-live_timeline.unity (12035), and when present [ai]-12036*-live_timeline.unity (12036,
whose so2036_2840f_2931f_camera grows) and i-12056*-live_timeline.unity (12056 and its 12056s1
variant, with three split-screen sub cameras). The Elichika store validator runs when ELICHIKA_DIR
(or the parent folder) holds Elichika's server app."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import math
import os
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webtools.core import mv_studio, mv_studio_register, mv_studio_timeline as studio  # noqa: E402

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))


def _elichika():
    for candidate in (os.environ.get("ELICHIKA_DIR"), ROOT.parent):
        if candidate and (Path(candidate) / "mv_studio_native_assets.py").is_file():
            path = str(Path(candidate).resolve())
            if path not in sys.path:
                sys.path.append(path)
            try:
                import mv_studio_native_assets
            except ImportError:
                return None
            return mv_studio_native_assets
    return None


NATIVE = _elichika()


def samples(live):
    """{platform: path} of one MV's original timelines in the sample folder."""
    found = {}
    for platform, paths in every_sample(live):
        found.setdefault(platform, paths)
    return found


def every_sample(live):
    """[(platform, path)] of every original timeline of one MV in the sample folder (variants too)."""
    found = []
    if SAMPLES.is_dir():
        for prefix, platform in (("a", "android"), ("i", "ios")):
            found += [(platform, path) for path in sorted(SAMPLES.glob(f"{prefix}-{live}??-live_timeline.unity"))]
    return found


MAIN = lambda track: "MainCamera" in (track.get("binding") or "")  # noqa: E731
SUB = lambda track: "/SplitScreenEffect/Cameras/SubCamera" in (track.get("binding") or "")  # noqa: E731


f32 = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]  # noqa: E731


def normalize(q):
    length = math.sqrt(sum(value * value for value in q))
    return [value / length for value in q]


def baked(frames, phase):
    """A follow-like dense bake of a shot: every sample moves and turns a little, differently per
    sample (a constant shot becomes dense). Values are float32 so the round trip is exact up to the
    rotation encoding."""
    result = []
    for index, frame in enumerate(frames):
        s = math.sin(index * .07 + phase)
        position = [f32(value + .3 * s + .01 * axis) for axis, value in enumerate(frame["position"])]
        half = math.radians(2 * s) / 2
        turn = [0., math.sin(half), 0., math.cos(half)]
        x, y, z, w = frame["rotation"]
        X, Y, Z, W = turn
        rotation = normalize([w * X + x * W + y * Z - z * Y, w * Y - x * Z + y * W + z * X,
                              w * Z + x * Y - y * X + z * W, w * W - x * X - y * Y - z * Z])
        fov = f32((frame["fov"] if isinstance(frame["fov"], (int, float)) else 30.) + 1 + s)
        result.append({"time": frame["time"], "position": position, "rotation": rotation, "fov": fov})
    return result


class Exported:
    """One MV timeline with every editable shot of the chosen camera tracks rewritten densely."""

    def __init__(self, raw, name, *, pad=None, cameras=MAIN):
        self.raw = raw
        self.original = studio.parse_timeline(raw, name)
        _, self.objects, _ = studio._read(raw, "original", time.monotonic() + 120)
        self.by_id = {studio._id(key): key for key in self.objects}
        self.tracks = deepcopy(self.original["tracks"])
        self.edited = {}
        for track in self.tracks:
            if track["kind"] != "camera" or track["nativeClass"] != "AnimationTrack" or not cameras(track):
                continue
            for event in track["events"]:
                animation = event["values"].get("animation")
                if "keyframes" not in event["editableValues"] or animation not in self.by_id:
                    continue
                event["values"]["keyframes"] = baked(event["values"]["keyframes"], len(self.edited))
                self.edited[event["id"]] = self.by_id[animation]
        if pad is None:
            self.output = studio.export_timeline(raw, name, self.tracks)
        else:
            # Grows the payload of the rewritten clips by a longer name (a test-only stand-in for a
            # clip that the dense rewrite grows; the camera data are unchanged).
            write = studio._write_camera

            def padded(tree, *args):
                write(tree, *args)
                tree["m_Name"] = tree["m_Name"] + "_" * pad

            with mock.patch.object(studio, "_write_camera", padded):
                self.output = studio.export_timeline(raw, name, self.tracks)
        _, self.after, _ = studio._read(self.output, "edited", time.monotonic() + 120)

    def stops(self):
        """[(clip name, shot length, old m_StopTime, new m_StopTime)] of the rewritten clips."""
        events = {event["id"]: event for track in self.tracks for event in track["events"]}
        return [(self.objects[key].peek_name(), events[event_id]["duration"],
                 self.objects[key].read_typetree()["m_MuscleClip"]["m_StopTime"],
                 self.after[key].read_typetree()["m_MuscleClip"]["m_StopTime"]) for event_id, key in self.edited.items()]

    def sizes(self):
        """[(clip name, old raw length, new raw length, old m_MuscleClipSize, new m_MuscleClipSize)]"""
        rows = []
        for key in self.edited.values():
            old, new = self.objects[key], self.after[key]
            rows.append((old.peek_name(), len(old.get_raw_data()), len(new.get_raw_data()),
                         old.read_typetree()["m_MuscleClipSize"], new.read_typetree()["m_MuscleClipSize"]))
        return rows


def ceil16(value):
    return (value + 15) // 16 * 16


class Checks(unittest.TestCase):
    def check_sizes(self, exported, *, pad=0):
        grown = []
        for name, old_raw, new_raw, old_size, new_size in exported.sizes():
            growth = new_raw - old_raw
            if growth > 0:
                grown.append(name)
                self.assertGreaterEqual(new_size, old_size + growth, name)
                self.assertEqual(new_size, ceil16(old_size + growth + 64), name)
                self.assertGreater(new_size, new_raw, f"{name}: the recorded size covers the grown clip")
            else:
                self.assertEqual(new_size, old_size, f"{name}: never shrunk")
        return grown

    def check_reparse(self, exported):
        parsed = studio.parse_timeline(exported.output, "edited")
        events = {event["id"]: event for track in parsed["tracks"] for event in track["events"]}
        submitted = {event["id"]: event for track in exported.tracks for event in track["events"]}
        worst = 0.
        for event_id in exported.edited:
            got, want = events[event_id]["values"]["keyframes"], submitted[event_id]["values"]["keyframes"]
            self.assertEqual(len(got), len(want))
            for a, b in zip(got, want):
                self.assertEqual(a["time"], b["time"])
                sign = 1 if sum(x * y for x, y in zip(a["rotation"], b["rotation"])) >= 0 else -1
                worst = max(worst, *(abs(x - y) for x, y in zip(a["position"], b["position"])),
                            *(abs(x - sign * y) for x, y in zip(a["rotation"], b["rotation"])), abs(a["fov"] - b["fov"]))
        self.assertLess(worst, 1e-6, "re-parsed samples")
        return worst

    def check_validator(self, exported, platform):
        if NATIVE is None:
            return False
        NATIVE._validate_timeline(exported.output, exported.raw, NATIVE.PLATFORMS[platform][1], time.monotonic() + 120)
        return True


@unittest.skipUnless(samples(12035), "Original game samples are optional")
class Real12035Tests(Checks):
    @classmethod
    def setUpClass(cls):
        cls.exports = {platform: Exported(path.read_bytes(), path.name) for platform, path in samples(12035).items()}

    def test_dense_rewrite_of_every_main_camera_shot(self):
        for platform, exported in self.exports.items():
            self.assertEqual(len(exported.edited), 36, platform)
            self.assertEqual(self.check_sizes(exported), [], "no 12035 camera clip grows (export notes 6.3)")
            self.check_reparse(exported)

    @unittest.skipUnless(NATIVE is not None, "The Elichika server app is not importable")
    def test_the_store_validator_accepts_the_rewrite(self):
        for platform, exported in self.exports.items():
            self.assertTrue(self.check_validator(exported, platform))

    def test_a_grown_clip_records_its_growth(self):
        platform, path = next(iter(samples(12035).items()))
        # Most 12035 clips shrink when rewritten dense (they were streamed); the ones within 150 bytes
        # of their old size grow with the padding, the others keep their recorded size.
        exported = Exported(path.read_bytes(), path.name, pad=150)
        grown = self.check_sizes(exported)
        self.assertTrue(grown, "some padded clips grew")
        self.assertLess(len(grown), len(exported.edited))
        self.check_reparse(exported)
        self.check_validator(exported, platform)

    def test_export_with_an_editor_layer_and_unedited_tracks_returns_the_original_bytes(self):
        path = next(iter(samples(12035).values()))
        raw = path.read_bytes()
        parsed = studio.parse_timeline(raw, path.name)
        project = {"version": 1, "name": "12035", "duration": parsed["duration"], "nativeTimeline": True, "token": "t",
                   "tracks": parsed["tracks"], "assets": [], "performers": [], "warnings": [], "quality": {}, "source": {},
                   "editor": {"version": 1, "originals": {}, "camera": {"version": 1, "shots": {}, "rigs": [
                       {"id": "rig-00000001", "type": "follow", "label": "Follow camera 1", "start": 1, "end": 3,
                        "target": {"slot": 1, "part": 0}, "view": "front", "yaw": 0, "frame": "stage", "turnDamping": .5,
                        "distance": 2.5, "height": 0, "lateral": 0, "aim": {"height": 0, "side": 0, "forward": 0},
                        "fov": 30, "roll": 0, "deadZone": {"radius": .1, "height": .1, "hysteresis": .5},
                        "heightLock": {"mode": "camera", "value": "start"},
                        "damping": {"aimXZ": .15, "aimY": .3, "bodyXZ": .35, "bodyY": .5}, "blendIn": .5, "blendOut": .5}]}}}
        written = {}
        with mock.patch.object(mv_studio, "_native", lambda value: raw), \
                mock.patch.object(mv_studio, "_destination", lambda name, suffix: Path("/unused") / (name + suffix)), \
                mock.patch.object(mv_studio, "_write", lambda target, data: written.setdefault("data", data) and target):
            mv_studio.export_timeline(project)
        self.assertIs(written["data"], raw, "the editor layer never reaches the native export")


@unittest.skipUnless(every_sample(12056), "The 12056 original timelines are optional")
class Real12056SubCameraTests(Checks):
    """The split-screen sub cameras: m_StopTime 1.7833 / 1.1 / 2.7167 / 1.8 in clips of 1.8 / 1.1167 /
    2.7333 / 0.8667 s. Every one of them takes camera edits now, written with m_StopTime = length."""

    @classmethod
    def setUpClass(cls):
        cls.exports = [(platform, path.name, Exported(path.read_bytes(), path.name, cameras=SUB))
                       for platform, path in every_sample(12056)]

    def test_every_sub_camera_shot_is_editable_and_exports(self):
        for platform, name, exported in self.exports:
            with self.subTest(name=name):
                self.assertEqual(len(exported.edited), 12, "three sub cameras with four shots each")
                rows = exported.stops()
                self.assertTrue(any(abs(old - length) > 1e-3 for _, length, old, _ in rows), "stock stop times differ")
                for clip, length, _, new in rows:
                    self.assertEqual(new, f32(length), clip)
                self.check_sizes(exported)
                self.check_reparse(exported)

    def test_unedited_export_returns_the_original_bytes(self):
        for platform, name, exported in self.exports:
            self.assertIs(studio.export_timeline(exported.raw, name, deepcopy(exported.original["tracks"])), exported.raw)

    @unittest.skipUnless(NATIVE is not None, "The Elichika server app is not importable")
    def test_the_store_validator_accepts_the_sub_camera_rewrite(self):
        for platform, name, exported in self.exports:
            with self.subTest(name=name):
                self.assertTrue(self.check_validator(exported, platform))


@unittest.skipUnless(samples(12036), "The 12036 original timeline is optional")
class Real12036Tests(Checks):
    @classmethod
    def setUpClass(cls):
        cls.exports = {platform: Exported(path.read_bytes(), path.name) for platform, path in samples(12036).items()}

    def test_dense_rewrite_grows_so2036_2840f_2931f_camera_and_its_recorded_size(self):
        for platform, exported in self.exports.items():
            grown = self.check_sizes(exported)
            self.assertEqual(grown, ["so2036_2840f_2931f_camera"], platform)
            self.check_reparse(exported)

    @unittest.skipUnless(NATIVE is not None, "The Elichika server app is not importable")
    def test_the_store_validator_accepts_the_grown_clip(self):
        for platform, exported in self.exports.items():
            self.assertTrue(self.check_validator(exported, platform))


def dense_camera(count, *, stop=None, rate=60.):
    """A native camera clip with `count` dense position, XYZ Euler and FOV samples at 1/rate s, its
    source stopping at `stop` (by default at its last sample)."""
    rows = [{"path": 0, "typeID": 4, "attribute": 1, "customType": 0, "isPPtrCurve": 0},
            {"path": 0, "typeID": 4, "attribute": 4, "customType": 0, "isPPtrCurve": 0},
            {"path": 0, "typeID": 114, "attribute": studio._FOV, "customType": 0, "isPPtrCurve": 0}]
    samples = [value for index in range(count)
               for value in (f32(index * .01), 1.5, -4., f32(3 + index * .2), f32(170 - index * .1), 0., f32(30 + index * .05))]
    return {"m_SampleRate": rate, "m_ClipBindingConstant": {"genericBindings": rows}, "m_MuscleClip": {
        "m_StartTime": 0., "m_StopTime": (count - 1) / rate if stop is None else stop, "m_Clip": {"data": {
            "m_StreamedClip": {"curveCount": 0, "data": []}, "m_ConstantClip": {"data": []},
            "m_DenseClip": {"m_CurveCount": 7, "m_FrameCount": count, "m_SampleRate": rate,
                            "m_BeginTime": 0., "m_SampleArray": samples}}}}}


def points(tree, duration, clip=None):
    return studio._camera_frames(SimpleNamespace(read_typetree=lambda: tree), clip or {}, duration, None, 100_000)


def shot(duration, keyframes):
    return {"duration": duration, "values": {"keyframes": keyframes}}


class WriterRuleTests(unittest.TestCase):
    """_write_camera and the rule the parse shares with it, on synthetic dense clips."""

    def test_a_source_that_stops_off_the_clip_end_takes_edits_and_ends_at_the_clip(self):
        # 12056 sub cameras: 107 frames of motion in a 108-frame clip, 108 frames in a 52-frame clip.
        for frames, stop, length in ((108, 107 / 60, 108 / 60), (109, 108 / 60, 52 / 60)):
            with self.subTest(stop=stop, length=length):
                tree = dense_camera(frames, stop=stop)
                self.assertIsNone(studio._camera_rewrite_refusal(tree, {}, length))
                before = points(tree, length)
                self.assertEqual(len(before), round(length * 60) + 1)
                after = deepcopy(before)
                for point in after:
                    point["fov"] += 1
                studio._write_camera(tree, {"m_Duration": length}, shot(length, before), shot(length, after))
                self.assertEqual(tree["m_MuscleClip"]["m_StopTime"], length)
                dense = tree["m_MuscleClip"]["m_Clip"]["data"]["m_DenseClip"]
                self.assertEqual(dense["m_FrameCount"], len(after))
                again = points(tree, length)
                self.assertEqual([point["time"] for point in again], [point["time"] for point in after])
                for got, want in zip(again, after):
                    self.assertAlmostEqual(got["fov"], want["fov"], places=9)
                    for a, b in zip(got["position"], want["position"]):
                        self.assertAlmostEqual(a, b, places=9)

    def test_a_stop_time_at_the_clip_end_is_kept_as_stored(self):
        tree = dense_camera(61, stop=f32(1.))
        stored = tree["m_MuscleClip"]["m_StopTime"]
        before = points(tree, 1.)
        studio._write_camera(tree, {}, shot(1., before), shot(1., deepcopy(before)))
        self.assertIs(tree["m_MuscleClip"]["m_StopTime"], stored, "the same float32 value is not rewritten")

    def test_refusals(self):
        tree = dense_camera(61)
        self.assertIsNone(studio._camera_rewrite_refusal(tree, {"m_ClipIn": 0., "m_TimeScale": 1.}, 1.))
        source = studio._CAMERA_SOURCE
        cases = [
            ({"m_ClipIn": .5}, tree, 1., source), ({"m_TimeScale": 2.}, tree, 1., source),
            ({}, {**tree, "m_SampleRate": 0.}, 1., source), ({}, {**tree, "m_SampleRate": 120.}, 1., source),
            ({}, {**tree, "m_MuscleClip": {**tree["m_MuscleClip"], "m_StartTime": .1}}, 1., source),
            ({}, {**tree, "m_ClipBindingConstant": {"genericBindings": tree["m_ClipBindingConstant"]["genericBindings"][:2]}}, 1., source),
            ({}, tree, 1.005, studio._CAMERA_FRAMES), ({}, tree, .5 / 60, studio._CAMERA_FRAMES), ({}, tree, 0., studio._CAMERA_FRAMES),
        ]
        for clip, case, length, reason in cases:
            with self.subTest(clip=clip, length=length):
                self.assertEqual(studio._camera_rewrite_refusal(case, clip, length), reason)
        before = points(tree, 1.)
        for wrong in (before[:-1], before + [dict(before[-1])], [{**point, "time": point["time"] + 1e-7} for point in before],
                      [{**point, "extra": 1} for point in before]):
            with self.subTest(count=len(wrong)), self.assertRaisesRegex(ValueError, "one camera point per frame"):
                studio._write_camera(deepcopy(tree), {}, shot(1., before), shot(1., wrong))
        with self.assertRaisesRegex(ValueError, "untrimmed native shot"):
            studio._write_camera(deepcopy(tree), {"m_ClipIn": .5}, shot(1., before), shot(1., before))


class FingerprintTests(unittest.TestCase):
    def test_registered_songs_rebake_after_the_size_rule(self):
        # The size rule changes exported bytes: a song registered before it rebakes on its next update.
        self.assertNotEqual(mv_studio_register.FINGERPRINT_VERSION, "mv-studio-register-1")


class TranslationTests(unittest.TestCase):
    def test_follow_camera_strings_are_translated_once(self):
        import json
        import re
        import subprocess
        from webtools import i18n
        source = (ROOT / "webtools" / "i18n.py").read_text(encoding="utf-8")
        block = re.search(r"_MV_EDITOR_D_TRANSLATIONS = \{(.*?)\n\}\n", source, re.S).group(1)
        keys = re.findall(r'^    "((?:[^"\\]|\\.)*)": \(', block, re.M)
        self.assertTrue(keys)
        for key in keys:
            text = json.loads('"' + key + '"')
            self.assertEqual(source.count('"' + key + '": ('), 1, f"{text!r} is defined once")
        node = os.environ.get("NODE_BINARY") or "node"
        script = ("globalThis.window=globalThis;const b=process.argv[1];"
                  "for (const f of ['mv-studio-camera-math.js','mv-studio-camera-keys.js','mv-studio-camera-follow.js']) require(b+f);"
                  "console.log(JSON.stringify(MVStudioCameraFollow.STRINGS));")
        try:
            output = subprocess.run([node, "-e", script, str(ROOT / "webtools" / "web" / "static") + "/"], capture_output=True,
                                    text=True, timeout=60, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            self.skipTest("Node is not available")
        for text in json.loads(output):
            for language in ("ko", "ja"):
                self.assertNotEqual(i18n.tr(text, language), text, f"{language}: {text!r}")


if __name__ == "__main__":
    unittest.main()
