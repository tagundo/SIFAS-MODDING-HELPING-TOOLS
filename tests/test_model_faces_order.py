"""The face completion order, pinned on a scenario matrix in virtual time.

The face-order probes of earlier review rounds run here with the real
constants (FACE_SECONDS, FALLBACK_SECONDS, MEASURE_SECONDS) on a virtual clock.
The asset server is a script of answers and transfer times per pack, and only
the network worker is replaced: a stand-in transfer advances the clock instead
of sleeping, so the real _Transfer.result and _behind decide when a download is
stopped, and the real FacePlan decides what is downloaded and chosen.

Each row also records what the order before body references (0fcfd4d) chose,
and when, measured in real time with the same scripts. The invariants hold for
every row: a face is found whenever that order found one; the face the body
references is chosen whenever an earlier version chose it and it is obtainable
in the face time; the choice never takes more than max(2 s, 10 %) longer than
that order unless it is the referenced face; and no pack is requested, or its
bytes reserved, twice.
"""
import csv
import importlib.util
import math
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from webtools.core import model_faces as faces
from webtools.core import model_viewer as viewer
import test_model_faces as face_tests

HAS_EXTRACTOR = importlib.util.find_spec("llas_asset_extractor") is not None
NETWORK = unittest.skipUnless(HAS_EXTRACTOR, "Elichika's parent llas_asset_extractor is needed for catalog downloads")


class Clock:
    def __init__(self):
        self.now = 1000.

    def __call__(self):
        return self.now


class Pack:
    """One pack on the scripted asset server.

    ``seconds`` spreads the pack evenly over chunks of ``chunk`` bytes, each
    arriving after its share of the time (the probes' model); ``rate`` sends
    ``chunk`` bytes every chunk/rate seconds. ``answer`` is 404, "unanswered"
    or "hang". ``reports=False`` models a downloader that reports no progress.
    """

    def __init__(self, data, *, seconds=0., chunk=512, rate=None, answer=None, reports=True):
        self.data, self.chunk, self.answer, self.reports = data, chunk, answer, reports
        chunks = max(1, math.ceil(len(data) / chunk))
        self.pause = chunk / rate if rate else seconds / chunks
        self.chunks = chunks

    def finish(self):
        if self.answer == "hang":
            return None
        return 0. if self.answer in (404, "unanswered") else self.chunks * self.pause

    def received(self, elapsed):
        if self.answer is not None:
            return 0
        if not self.pause:
            return len(self.data)
        return min(len(self.data), int(elapsed / self.pause + 1e-9) * self.chunk)


class _Completion:
    def __init__(self, transfer):
        self.transfer = transfer

    def wait(self, timeout):
        transfer, clock = self.transfer, self.transfer.clock
        if transfer.state.get("abandoned"):
            # A stopped worker leaves at its next chunk.
            return True
        target = clock.now + max(0., timeout)
        end = transfer.pack.finish()
        if end is not None and transfer.opened + end <= target:
            clock.now = max(clock.now, transfer.opened + end)
            transfer.report()
            pack = transfer.pack
            if pack.answer == 404:
                transfer.state.update(data=None, error=HTTPError(transfer.url, 404, "Not Found", {}, None))
            elif pack.answer == "unanswered":
                transfer.state.update(data=None, error=URLError("no route to host"))
            else:
                transfer.state.update(data=pack.data, error=None)
            return True
        clock.now = target
        transfer.report()
        return False


class VirtualTransfer(faces._Transfer):
    """_Transfer without its worker thread: the scripted pack advances the clock."""

    clock = network = None

    def __init__(self, url, expected, deadline, byte_limit, limit=None):
        faces._check(deadline)
        self.url, self.deadline, self.limit = url, deadline, limit
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.state, self.progress = {"abandoned": False}, {}
        self.started = self.clock.now if limit is not None else None
        name = url.rsplit("/", 1)[1]
        self.network["requests"].append(name)
        self.pack, self.opened = self.network["packs"][name], self.clock.now
        self.completed = _Completion(self)

    def report(self):
        if self.pack.reports:
            self.progress.update(reported=True, total=len(self.pack.data),
                                 received=self.pack.received(self.clock.now - self.opened))


def cab(digit):
    return "CAB-" + digit * 32


# Scenario: (face seconds, catalog [(asset, pack, cab digit, Pack options)],
# referenced cab digit, default-suit body assets, library {path: cab digit},
# cached faces {name: cab digit}, downloads allowed).
SCENARIOS = {
    # r4 review (test_rv_slow_order): face time 12 s.
    "S1": (12, [("X", "xpack", "1", {"seconds": 4}), ("F", "fpack", "2", {"seconds": .2})], "2", (), {}, {}, True),
    "S2": (12, [("F", "fpack", "2", {"seconds": 30}), ("G", "gpack", "1", {"seconds": .2})], "2", (), {}, {}, True),
    "S3": (12, [("S", "spack", "1", {"seconds": .2}), ("F", "fpack", "2", {"seconds": 30})], "2", ("S",), {}, {}, True),
    "S4": (12, [("F", "fpack", "2", {"seconds": 5})], "2", (), {}, {}, True),
    "S5": (12, [("F", "fpack", "2", {"seconds": 30})], "2", (), {}, {}, True),
    # r5 verifier (test_adv_order).
    "C1": (12, [("S", "spack", "1", {"answer": 404}), ("F", "fpack", "2", {"seconds": 9})], "2", ("S",), {}, {}, True),
    "C2": (40, [("S", "spack", "1", {"seconds": 6}), ("F", "fpack", "2", {"chunk": 16, "rate": 40})], "2", ("S",), {}, {}, True),
    "C3": (40, [("S", "spack", "1", {"answer": 404}), ("F", "fpack", "2", {"seconds": 37})], "2", ("S",), {}, {}, True),
    "C4": (40, [("S", "spack", "1", {"seconds": 3}), ("F", "fpack", "2", {"chunk": 16, "rate": 40})], "2", ("S",), {}, {}, True),
    "C5": (40, [("F", "fpack", "2", {"answer": 404}), ("G", "gpack", "1", {"seconds": 12})], "2", (),
           {"mods/my_face.unity": "2"}, {}, True),
    # As C5, but the first catalog face answers with another prefab.
    "C6": (40, [("F", "fpack", "1", {"seconds": .2}), ("G", "gpack", "3", {"seconds": 12})], "2", (),
           {"mods/my_face.unity": "2"}, {}, True),
    # A hung named download while another prefab is cached; a steady 19 s one
    # beside a library prefab; the suit body first and the named face 5 s away.
    "H1": (40, [("F", "fpack", "2", {"answer": "hang"})], "2", (), {}, {"ch0207_" + "a" * 24 + ".unity": "1"}, True),
    "H2": (40, [("F", "fpack", "2", {"chunk": 64, "rate": 160})], "2", (), {"costume_face_copy.unity": "4"}, {}, True),
    "H3": (12, [("S", "spack", "1", {"seconds": .2}), ("F", "fpack", "2", {"seconds": 5})], "2", ("S",), {}, {}, True),
    # Three candidates that never send a byte while another prefab is cached:
    # the first one stopped ends the downloads.
    "H4": (40, [(name, name.lower() + "pack", "2", {"answer": "hang"}) for name in ("F", "G", "K")], "2", (), {},
           {"ch0207_" + "a" * 24 + ".unity": "1"}, True),
    # rv2/r4 verifier slow CDN (a downloader that reports no progress).
    "D20L": (40, [("F", "fpack", "2", {"seconds": 20, "reports": False})], "2", (), {"costume_face_copy.unity": "4"}, {}, True),
    "D32L": (40, [("F", "fpack", "2", {"seconds": 32, "reports": False})], "2", (), {"costume_face_copy.unity": "4"}, {}, True),
    "D38": (40, [("F", "fpack", "2", {"seconds": 38, "reports": False})], "2", (), {}, {}, True),
    "D45": (40, [("F", "fpack", "2", {"seconds": 45, "reports": False})], "2", (), {}, {}, True),
    # An asset server that does not answer while another prefab is cached; offline.
    "U1": (40, [("F", "fpack", "2", {"answer": "unanswered"})], "2", (), {}, {"ch0207_" + "a" * 24 + ".unity": "1"}, True),
    "OFF": (40, [("F", "fpack", "2", {})], "2", (), {}, {"ch0207_" + "a" * 24 + ".unity": "1"}, False),
    # The trade-off (informational): H2's download when the body names a face
    # found nowhere. Until it ends it cannot be told from H2.
    "T1": (40, [("F", "fpack", "2", {"chunk": 64, "rate": 160})], "3", (), {"costume_face_copy.unity": "4"}, {}, True),
}

# What 0fcfd4d chose and when (real time, the same scripts), and whether an
# earlier version chose the referenced face.
BEFORE = {
    "S1": ("X", 4.0, False), "S2": (None, 12.0, False), "S3": ("S", .2, False), "S4": ("F", 5.0, True),
    "S5": (None, 12.0, False), "C1": ("F", 9.0, True), "C2": ("S", 6.0, False), "C3": ("F", 37.0, True),
    "C4": ("S", 3.0, False), "C5": ("LIB", 0., True), "C6": ("LIB", 0., True), "H1": ("CACHE", 0., False), "H2": ("LIB", 0., True),
    "H3": ("S", .2, True), "H4": ("CACHE", 0., False), "D20L": ("LIB", 0., True), "D32L": ("LIB", 0., False), "D38": ("F", 38.1, True),
    "D45": (None, 40.0, False), "U1": ("CACHE", 0., False), "OFF": ("CACHE", 0., False), "T1": ("LIB", 0., False),
}

# This version, pinned: choice, seconds, packs requested in order.
AFTER = {
    "S1": ("F", 4.2, ["xpack", "fpack"]),
    "S2": (None, 12.0, ["fpack"]),
    "S3": ("S", 1.2, ["spack", "fpack"]),
    "S4": ("F", 5.0, ["fpack"]),
    "S5": (None, 12.0, ["fpack"]),
    "C1": ("F", 9.0, ["spack", "fpack"]),
    "C2": ("S", 7.0, ["spack", "fpack"]),
    "C3": ("F", 37.0, ["spack", "fpack"]),
    "C4": ("S", 4.0, ["spack", "fpack"]),
    "C5": ("LIB", 0., ["fpack"]),
    "C6": ("LIB", .2, ["fpack"]),
    "H1": ("CACHE", 1.0, ["fpack"]),
    "H2": ("F", 19.6, ["fpack"]),
    "H3": ("F", 5.2, ["spack", "fpack"]),
    "H4": ("CACHE", 1.0, ["fpack"]),
    "D20L": ("F", 20.0, ["fpack"]),
    "D32L": ("F", 32.0, ["fpack"]),
    "D38": ("F", 38.0, ["fpack"]),
    "D45": (None, 40.0, ["fpack"]),
    "U1": ("CACHE", 0., ["fpack"]),
    "OFF": ("CACHE", 0., []),
    "T1": ("LIB", 19.6, ["fpack"]),
}
# Rows where waiting is the documented trade-off rather than a regression.
TRADE_OFF = {"T1"}


class FaceOrderMatrixTests(unittest.TestCase):
    setUpClass = classmethod(face_tests.FaceTests.setUpClass.__func__)
    setUp, tearDown = face_tests.FaceTests.setUp, face_tests.FaceTests.tearDown
    scene, plan = face_tests.FaceTests.scene, face_tests.FaceTests.plan
    databases, descriptor, encrypted = (face_tests.FaceTests.databases, face_tests.FaceTests.descriptor,
                                        face_tests.FaceTests.encrypted)

    def donor(self, digit):
        return face_tests.bundle([(cab(digit), self.scene("Face")), (cab(digit) + "-eyes", self.scene("Eyes"))])

    def run_scenario(self, name):
        face_seconds, catalog, referenced, suit, library, cache, allow = SCENARIOS[name]
        import llas_asset_extractor as extractor
        labels, descriptors, packs = {}, [], {}
        for relative, digit in library.items():
            target = self.library / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.donor(digit))
        for cached, digit in cache.items():
            directory = Path(self.context["cache_dir"]) / "models"
            directory.mkdir(parents=True, exist_ok=True)
            faces._save(directory / cached, self.donor(digit), 207)
            labels[str(directory / cached)] = "CACHE"
        for asset, pack, digit, options in catalog:
            data = self.donor(digit)
            descriptor = dict(self.descriptor(data, name=pack), asset_path=asset)
            descriptors.append(descriptor)
            encrypted = bytearray(data)
            extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
            packs[pack] = Pack(bytes(encrypted), **options)
            labels[data] = asset

        def iterate(plan):
            for descriptor in descriptors:
                if descriptor["asset_path"] in suit:
                    plan._suit_models.add(tuple(descriptor[key] for key in ("pack_name", "head", "size", "key1", "key2", "pack_size")))
                yield dict(descriptor)

        clock, network = Clock(), {"packs": packs, "requests": []}
        self.context["allow_download"] = allow
        with patch.object(faces.time, "monotonic", clock), patch.object(faces, "FACE_SECONDS", face_seconds), \
                patch.object(VirtualTransfer, "clock", clock), patch.object(VirtualTransfer, "network", network), \
                patch.object(faces, "_Transfer", VirtualTransfer), \
                patch.object(faces.FacePlan, "_descriptor_iter", iterate), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + referenced * 32}):
            plan = self.plan()
            started = clock.now
            chosen = plan.resolve()
            elapsed = clock.now - started
        library_root = os.path.realpath(self.library)
        picked = []
        for path in chosen:
            if os.path.realpath(path).startswith(library_root + os.sep):
                picked.append("LIB")
            else:
                picked.append(labels.get(path) or labels.get(Path(path).read_bytes()))
        self.assertLessEqual(len(picked), 1)
        sizes = {pack: len(script.data) for pack, script in packs.items()}
        return (picked[0] if picked else None), elapsed, network["requests"], plan.transferred, sizes

    def check_invariants(self, name, choice, elapsed, requests, reserved, sizes):
        face_seconds, catalog, referenced = SCENARIOS[name][:3]
        before, before_time, earlier_referenced = BEFORE[name]
        named = {asset for asset, _, digit, _ in catalog if digit == referenced}
        library_named = referenced in SCENARIOS[name][4].values()
        is_referenced = choice in named or choice == "LIB" and library_named
        if before is not None:
            self.assertIsNotNone(choice, "0fcfd4d found a face here")
        if earlier_referenced:
            self.assertTrue(is_referenced, "an earlier version chose the referenced face")
        if not is_referenced and name not in TRADE_OFF:
            self.assertLessEqual(elapsed, max(before_time + 2, before_time * 1.1) + 1e-6)
        # Each pack is requested once; its bytes are reserved once.
        self.assertEqual(len(requests), len(set(requests)))
        self.assertEqual(reserved, sum(sizes[pack] for pack in requests))
        self.assertLessEqual(elapsed, face_seconds + 1e-6)

    @NETWORK
    def test_every_scenario_keeps_the_invariants_and_its_pinned_row(self):
        for name in SCENARIOS:
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                choice, elapsed, requests, reserved, sizes = self.run_scenario(name)
                expected_choice, expected_time, expected_requests = AFTER[name]
                self.assertEqual((choice, requests), (expected_choice, expected_requests))
                self.assertAlmostEqual(elapsed, expected_time, delta=.051)
                self.check_invariants(name, choice, elapsed, requests, reserved, sizes)

    def test_downloads_are_judged_only_after_their_measuring_time(self):
        progress, started = {"reported": True, "total": 1000, "received": 0}, 0.
        limit = 10.
        # Not judged before MEASURE_SECONDS, nor without reported progress.
        self.assertFalse(faces._behind(progress, started, faces.MEASURE_SECONDS - .01, limit))
        self.assertFalse(faces._behind({}, started, 5., limit))
        # Nothing received once measured: stalled.
        self.assertTrue(faces._behind(progress, started, faces.MEASURE_SECONDS, limit))
        # 100 of 1000 bytes in 1 s: 9 s more, so it ends at 10 s.
        progress["received"] = 100
        self.assertFalse(faces._behind(progress, started, 1., limit))
        self.assertTrue(faces._behind(progress, started, 1., limit - .01))
        # Without a size only a stall is judged; a finished one never is.
        self.assertFalse(faces._behind(dict(progress, total=None), started, 5., 1.))
        self.assertFalse(faces._behind(dict(progress, received=1000), started, 5., 1.))

    def extracted_names(self, *, manifest, sized, folder="extracted/3d_model"):
        """Faces the bundled extractor wrote: whether each is used without a download."""
        stock = self.donor("2")
        names = ("ch0207_facedynamic.unity", "x_h_.unity", "Emma_ch0207_co0001_face.unity", "ch0207_face_dynamic.unity")
        results = {}
        for relative in names:
            face = self.library / folder / relative
            face.parent.mkdir(parents=True, exist_ok=True)
            face.write_bytes(stock)
            out_dir = face.parent.parent
            if manifest:
                with open(out_dir / "_extract_manifest.csv", "w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["table", "asset_path", "pack_name", "head", "size", "key1", "key2", "output_file", "status"])
                    writer.writerow(["member_model", "stockface", "stockpack", 0, manifest, 0, 0,
                                     os.path.join(face.parent.name, relative), "OK"])
            descriptor = {"asset_path": "stockface", "pack_name": "stockpack", "head": 0,
                          "size": len(stock) if sized else 1000, "key1": 0, "key2": 0, "pack_size": None}
            calls = []

            def resource(plan, value, download=True):
                calls.append(download)
                raise faces.FaceUnavailable("Only on the asset server")

            self.context["allow_download"] = True
            with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(descriptor)])), \
                    patch.object(faces.FacePlan, "_resource", resource):
                chosen = [os.path.realpath(path) for path in self.plan().resolve()]
            self.assertEqual(chosen, [str(face.resolve())])
            results[relative] = True not in calls
            face.unlink()
            (out_dir / "_extract_manifest.csv").unlink(missing_ok=True)
        return results

    def test_extracted_member_models_are_used_without_a_download_whatever_their_name(self):
        stock_size = len(self.donor("2"))
        everything = dict.fromkeys(("ch0207_facedynamic.unity", "x_h_.unity", "Emma_ch0207_co0001_face.unity",
                                    "ch0207_face_dynamic.unity"), True)
        # The manifest the extractor writes, or the catalog face's own size.
        self.assertEqual(self.extracted_names(manifest=stock_size, sized=False), everything)
        self.assertEqual(self.extracted_names(manifest=None, sized=True), everything)
        # Neither: only the extractor's own name is trusted; the others are
        # tried after the catalog's copy (the asset server is asked first).
        only_native = dict(everything, **{"x_h_.unity": False, "Emma_ch0207_co0001_face.unity": False,
                                          "ch0207_face_dynamic.unity": False})
        self.assertEqual(self.extracted_names(manifest=None, sized=False), only_native)
        # A manifest row of another size (an edited copy) is not trusted either.
        self.assertEqual(self.extracted_names(manifest=stock_size + 1, sized=False), only_native)
        # Its other library folder: also the top of the library root (where the
        # extractor writes no member model under another name), by size.
        self.assertEqual(self.extracted_names(manifest=None, sized=True, folder="3d_model"), everything)
        self.assertEqual(self.extracted_names(manifest=None, sized=True, folder=""), only_native)
        # Outside the extractor's folders nothing is trusted by name or size.
        self.assertEqual(self.extracted_names(manifest=stock_size, sized=True, folder="extracted/models"),
                         dict.fromkeys(everything, False))


if __name__ == "__main__":
    unittest.main()
