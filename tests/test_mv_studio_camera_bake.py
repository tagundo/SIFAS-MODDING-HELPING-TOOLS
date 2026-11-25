"""Exporting baked camera shots (camera keys and follow camera bakes): m_MuscleClipSize hardening.

A follow camera bakes dense samples into every shot it covers, and _write_camera writes them as a
DenseClip. A clip that was constant or streamed grows, past its stock m_MuscleClipSize (every
inspected stock camera clip records its serialized size + 188 bytes). The export grows that field
by the growth + 64 bytes, rounded up to 16, and never shrinks it.

Original game samples are optional and never stored here: ELICHIKA_STUDIO_TIMELINE_DIR with
[ai]-1203503-live_timeline.unity (12035) and, when present, [ai]-12036*-live_timeline.unity (12036,
whose so2036_2840f_2931f_camera grows). The Elichika store validator runs when ELICHIKA_DIR (or the
parent folder) holds Elichika's server app."""
from copy import deepcopy
from pathlib import Path
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
    if SAMPLES.is_dir():
        for prefix, platform in (("a", "android"), ("i", "ios")):
            paths = sorted(SAMPLES.glob(f"{prefix}-{live}??-live_timeline.unity"))
            if paths:
                found[platform] = paths[0]
    return found


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
    """One MV timeline with every main-camera shot rewritten densely."""

    def __init__(self, raw, name, *, pad=None):
        self.raw = raw
        self.original = studio.parse_timeline(raw, name)
        _, self.objects, _ = studio._read(raw, "original", time.monotonic() + 120)
        self.by_id = {studio._id(key): key for key in self.objects}
        self.tracks = deepcopy(self.original["tracks"])
        self.edited = {}
        for track in self.tracks:
            if track["kind"] != "camera" or not ("MainCamera" in (track.get("binding") or "")):
                continue
            for event in track["events"]:
                animation = event["values"].get("animation")
                if "keyframes" not in event["editableValues"] or animation not in self.by_id:
                    continue
                tree = self.objects[self.by_id[animation]].read_typetree()
                if abs(tree["m_MuscleClip"]["m_StopTime"] - event["duration"]) > 1e-3:
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
