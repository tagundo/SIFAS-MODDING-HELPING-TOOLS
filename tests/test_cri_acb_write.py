"""@UTF and AFS2 writers, template cue builder and decode-back verifier.

Every container here is synthetic: the template cue sheet copies only the
stock table schema (column names and types) and carries synthetic audio. Set
SIFAS_TEST_ACB and SIFAS_TEST_AWB to private local stock music files for the
optional rebuild check.
"""
import hashlib
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from webtools.core import cri_acb_write as acbw
from webtools.core import cri_audio_decode as cri
from webtools.core import cri_hca_encode as enc
from webtools.core.cri_acb_write import CONSTANT, PER_ROW, ZERO, UtfColumn, UtfTable

RATE = 44100
CLHCA = Path(enc.__file__).parent / "resources" / "cri_hca"


class Clhca:
    directory = None
    library = None

    @classmethod
    def get(cls):
        if cls.library is None:
            cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
            if not cc:
                raise unittest.SkipTest("No C compiler to build the vendored clHCA decoder")
            cls.directory = tempfile.TemporaryDirectory()
            library = Path(cls.directory.name) / "libelichika_hca.so"
            subprocess.run([cc, "-O2", "-shared", "-fPIC", str(CLHCA / "clhca.c"), "-o", str(library)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cls.library = str(library)
        return cls.library


def tearDownModule():
    if Clhca.directory is not None:
        Clhca.directory.cleanup()
        Clhca.directory = Clhca.library = None


def tone(seconds, frequency, other=None, level=0.4):
    t = np.arange(int(seconds * RATE)) / RATE
    left = level * np.sin(2 * np.pi * frequency * t)
    right = level * np.sin(2 * np.pi * (other or frequency) * t)
    return np.clip(np.rint(np.stack([left, right], axis=1) * 32767), -32768, 32767).astype(np.int16)


def table(name, columns, rows, align=0):
    return acbw.write_utf(UtfTable(name, 1, [UtfColumn(n, kind, PER_ROW) for n, kind in columns], rows, align))


def synthetic_template(hca, *, streaming=2, beat_rows=1, cues=1, encode_type=2, prefetch_blocks=5, subkey=0):
    """A single-cue music cue sheet with the stock schema and synthetic content."""
    info = enc.hca_info(hca)
    samples = info["sampleCount"]
    waveform = table("Waveform", [("MemoryAwbId", 2), ("EncodeType", 0), ("Streaming", 0), ("NumChannels", 0),
                                  ("LoopFlag", 0), ("SamplingRate", 2), ("NumSamples", 4), ("ExtensionData", 2),
                                  ("StreamAwbPortNo", 2), ("StreamAwbId", 2)],
                     [{"MemoryAwbId": 0, "EncodeType": encode_type, "Streaming": streaming, "NumChannels": 2,
                       "LoopFlag": 1, "SamplingRate": RATE, "NumSamples": samples, "ExtensionData": 0xFFFF,
                       "StreamAwbPortNo": 0, "StreamAwbId": 0}])
    cue = table("Cue", [("CueId", 4), ("ReferenceType", 0), ("ReferenceIndex", 2), ("UserData", 10), ("Worksize", 2),
                        ("AisacControlMap", 11), ("Length", 4), ("NumAisacControlMaps", 0), ("HeaderVisibility", 0)],
                [{"CueId": index, "ReferenceType": 3, "ReferenceIndex": 0, "UserData": "", "Worksize": 0,
                  "AisacControlMap": b"", "Length": samples * 1000 // RATE, "NumAisacControlMaps": 0,
                  "HeaderVisibility": 1} for index in range(cues)])
    names = table("CueName", [("CueName", 10), ("CueIndex", 2)],
                  [{"CueName": f"template_{index}" if index else "template", "CueIndex": index} for index in range(cues)])
    synth = table("Synth", [("Type", 0), ("VoiceLimitGroupName", 10), ("CommandIndex", 2), ("ReferenceItems", 11),
                            ("LocalAisacs", 11), ("GlobalAisacStartIndex", 2), ("GlobalAisacNumRefs", 2),
                            ("ControlWorkArea1", 2), ("ControlWorkArea2", 2), ("TrackValues", 11),
                            ("ParameterPallet", 2), ("ActionTrackStartIndex", 2), ("NumActionTracks", 2)],
                  [{"Type": 0, "VoiceLimitGroupName": "", "CommandIndex": 0, "ReferenceItems": struct.pack(">HH", 1, 0),
                    "LocalAisacs": b"", "GlobalAisacStartIndex": 0xFFFF, "GlobalAisacNumRefs": 0, "ControlWorkArea1": 0,
                    "ControlWorkArea2": 0, "TrackValues": b"", "ParameterPallet": 0xFFFF,
                    "ActionTrackStartIndex": 0xFFFF, "NumActionTracks": 0}])
    track = table("Track", [("EventIndex", 2), ("CommandIndex", 2), ("LocalAisacs", 11), ("GlobalAisacStartIndex", 2),
                            ("GlobalAisacNumRefs", 2), ("ParameterPallet", 2), ("TargetType", 0), ("TargetName", 10),
                            ("TargetId", 4), ("TargetAcbName", 10), ("Scope", 0), ("TargetTrackNo", 2)],
                  [{"EventIndex": 0, "CommandIndex": 0xFFFF, "LocalAisacs": b"", "GlobalAisacStartIndex": 0xFFFF,
                    "GlobalAisacNumRefs": 0, "ParameterPallet": 0xFFFF, "TargetType": 0, "TargetName": "",
                    "TargetId": 0xFFFFFFFF, "TargetAcbName": "", "Scope": 0, "TargetTrackNo": 0xFFFF}])
    sequence = table("Sequence", [("PlaybackRatio", 2), ("NumTracks", 2), ("TrackIndex", 11), ("CommandIndex", 2),
                                  ("Type", 0)],
                     [{"PlaybackRatio": 100, "NumTracks": 1, "TrackIndex": struct.pack(">H", 0), "CommandIndex": 0,
                       "Type": 0}])
    command = lambda raw: table("Command", [("Command", 11)], [{"Command": raw}])
    acf = acbw.write_utf(UtfTable("AcfReference", 1, [UtfColumn("Type", 0, PER_ROW), UtfColumn("Name", 10, PER_ROW),
                                                      UtfColumn("Name2", 10, CONSTANT, ""), UtfColumn("Id", 4, PER_ROW)],
                                  [{"Type": 3, "Name": "CATEGORY_A", "Id": 1}, {"Type": 9, "Name": "BUS_A", "Id": 0xFFFFFFFF}]))
    beats = table("BeatSyncInfo", [("Bpm", 8), ("NumBeats", 5), ("BeatDenominator", 5), ("SyncBeatFlags", 4),
                                   ("BaseRate", 4), ("StartSample", 4), ("EndSample", 4)],
                  [{"Bpm": 100.0 + index, "NumBeats": 4, "BeatDenominator": 4, "SyncBeatFlags": 0xFFFFFFFF,
                    "BaseRate": RATE, "StartSample": 1000 + index * 50000, "EndSample": 50999 + index * 50000
                    if index + 1 < beat_rows else samples} for index in range(beat_rows)]) if beat_rows else b""
    awb = acbw.write_afs2([(0, hca)], subkey=subkey) if streaming else None
    if streaming == 2:
        memory = acbw.write_afs2([(0, hca[:96 + prefetch_blocks * 512])], subkey=subkey)
    elif streaming == 0:
        memory = acbw.write_afs2([(0, hca)], subkey=subkey)
    else:
        memory = b""
    stream_hash = table("StreamAwb", [("Name", 10), ("Hash", 11)],
                        [{"Name": "template", "Hash": hashlib.md5(awb).digest()}]) if streaming else b""
    afs2_header = table("StreamAwbHeader", [("Header", 11)], [{"Header": awb[:28]}]) if streaming else b""
    root_columns = [("FileIdentifier", 4), ("Size", 4), ("Version", 4), ("Type", 0), ("Target", 0), ("AcfMd5Hash", 11),
                    ("CategoryExtension", 0), ("CueTable", 11), ("CueNameTable", 11), ("WaveformTable", 11),
                    ("AisacTable", 11), ("SynthTable", 11), ("SeqCommandTable", 11), ("TrackTable", 11),
                    ("SequenceTable", 11), ("AwbFile", 11), ("VersionString", 10), ("AcbGuid", 11),
                    ("StreamAwbHash", 11), ("AcbVolume", 8), ("Name", 10), ("CharacterEncodingType", 0),
                    ("AcfReferenceTable", 11), ("BeatSyncInfoTable", 11), ("CuePriorityType", 0),
                    ("SynthCommandTable", 11), ("TrackEventTable", 11), ("StreamAwbTocWork", 11),
                    ("StreamAwbAfs2Header", 11)]
    root = {"FileIdentifier": 0, "Size": 0, "Version": 0x01320000, "Type": 0, "Target": 0,
            "AcfMd5Hash": bytes(range(16)), "CategoryExtension": 0, "CueTable": cue, "CueNameTable": names,
            "WaveformTable": waveform, "AisacTable": b"", "SynthTable": synth,
            "SeqCommandTable": command(bytes.fromhex("0041080000000100000017")), "TrackTable": track,
            "SequenceTable": sequence, "AwbFile": memory, "VersionString": "\nsynthetic template\n",
            "AcbGuid": bytes(16), "StreamAwbHash": stream_hash, "AcbVolume": 1.0, "Name": "template",
            "CharacterEncodingType": 0, "AcfReferenceTable": acf, "BeatSyncInfoTable": beats, "CuePriorityType": 255,
            "SynthCommandTable": command(bytes.fromhex("00220200ff")),
            "TrackEventTable": command(struct.pack(">HBHH", 2000, 4, 2, 0) + bytes(3)),
            "StreamAwbTocWork": bytes(64), "StreamAwbAfs2Header": afs2_header}
    return table("Header", root_columns, [root], align=32), awb


class UtfTests(unittest.TestCase):
    def sample_table(self, align=0):
        values = {0: 200, 1: -100, 2: 60000, 3: -30000, 4: 4000000000, 5: -2000000000, 6: 2 ** 63 + 5,
                  7: -(2 ** 62), 8: 1.5, 9: 1 / 3, 10: "문자열 text", 11: b"\x01\x02\x03"}
        columns = []
        for kind, value in values.items():
            columns.append(UtfColumn(f"zero{kind}", kind, ZERO))
            columns.append(UtfColumn(f"const{kind}", kind, CONSTANT, value))
            columns.append(UtfColumn(f"row{kind}", kind, PER_ROW))
        rows = []
        for index in range(3):
            row = {}
            for kind, value in values.items():
                if kind == 10:
                    row[f"row{kind}"] = f"{value} {index}" if index != 1 else ""
                elif kind == 11:
                    row[f"row{kind}"] = value * (index + 1) if index != 1 else b""
                elif kind in (8, 9):
                    row[f"row{kind}"] = value * (index + 1)
                else:
                    row[f"row{kind}"] = value - index if value > 0 else value + index
            rows.append(row)
        return UtfTable("Sample", 1, columns, rows, align)

    def test_every_column_type_and_storage_round_trips(self):
        for align in (0, 32):
            with self.subTest(align=align):
                original = self.sample_table(align)
                raw = acbw.write_utf(original)
                self.assertEqual(len(raw) % 4, 0)
                parsed = acbw.read_utf(raw)
                self.assertEqual(parsed.name, "Sample")
                self.assertEqual([(c.name, c.kind, c.storage) for c in parsed.columns],
                                 [(c.name, c.kind, c.storage) for c in original.columns])
                self.assertEqual(parsed.align, align)
                self.assertEqual(acbw.write_utf(parsed), raw)
                repo = cri.utf_rows(raw)
                self.assertEqual(repo["name"], "Sample")
                for index, row in enumerate(repo["rows"]):
                    for column in original.columns:
                        expected = original.value(index, column.name)
                        if column.kind == 8:
                            expected = struct.unpack(">f", struct.pack(">f", expected))[0]
                        self.assertEqual(row[column.name], expected, (index, column.name))
                        self.assertEqual(parsed.value(index, column.name), expected)

    def test_root_layout_aligns_blobs_to_32_bytes(self):
        raw = acbw.write_utf(self.sample_table(32))
        _, size, _, _, strings_at, data_at, *_ = struct.unpack_from(">4sIHHIIIHHI", raw)
        self.assertEqual((data_at + 8) % 32, 0)
        self.assertEqual(len(raw) % 32, 0)
        parsed = acbw.read_utf(raw)
        offsets = []
        position = 32 + sum(5 + (acbw._WIDTHS[c.kind] if c.storage == CONSTANT else 0) for c in parsed.columns)
        for _ in parsed.rows:
            for column in parsed.columns:
                if column.storage == PER_ROW:
                    if column.kind == 11:
                        start, length = struct.unpack_from(">II", raw, position)
                        if length:
                            offsets.append(start)
                        else:
                            self.assertEqual(start, 0)
                    position += acbw._WIDTHS[column.kind]
        self.assertTrue(offsets and all(offset % 32 == 0 for offset in offsets))

    def test_string_pool_order_has_no_sharing(self):
        raw = table("Names", [("A", 10), ("B", 10)], [{"A": "", "B": ""}, {"A": "x", "B": "x"}])
        _, _, _, _, strings_at, data_at, *_ = struct.unpack_from(">4sIHHIIIHHI", raw)
        pool = raw[strings_at + 8:data_at + 8]
        self.assertEqual(pool, b"Names\0A\0B\0\0\0x\0x\0")

    def test_set_values_keeps_storage_flags_when_possible(self):
        parsed = acbw.read_utf(acbw.write_utf(self.sample_table()))
        parsed.set_values("const4", [7, 7, 7])
        self.assertEqual((parsed.column("const4").storage, parsed.column("const4").value), (CONSTANT, 7))
        parsed.set_values("zero2", [0, 0, 0])
        self.assertEqual(parsed.column("zero2").storage, ZERO)
        parsed.set_values("zero2", [5, 5, 5])
        self.assertEqual((parsed.column("zero2").storage, parsed.column("zero2").value), (CONSTANT, 5))
        parsed.set_values("const10", ["a", "b", "a"])
        self.assertEqual(parsed.column("const10").storage, PER_ROW)
        parsed.set(1, "row4", 9)
        self.assertEqual([parsed.value(i, "row4") for i in range(3)], [4000000000, 9, 3999999998])
        again = acbw.read_utf(acbw.write_utf(parsed))
        self.assertEqual([again.value(i, "const10") for i in range(3)], ["a", "b", "a"])
        for name, value in (("row0", 256), ("row1", -129), ("row10", 5), ("row11", "x"), ("row8", math.inf),
                            ("row2", True)):
            with self.subTest(name), self.assertRaises(ValueError):
                parsed.set(0, name, value)

    def test_rejects_corrupt_tables(self):
        raw = acbw.write_utf(self.sample_table())
        broken = []
        for at, value in ((4, 0xFFFFFFFF), (12, 0xFFFFFFFF), (16, 0xFFFFFFFF), (28, 0xFFFFFFFF)):
            corrupt = bytearray(raw)
            struct.pack_into(">I", corrupt, at, value)
            broken.append(bytes(corrupt))
        bad_storage = bytearray(raw)
        bad_storage[32] = 0x70
        broken += [bytes(bad_storage), b"", b"@UTF", raw[:31], b"XUTF" + raw[4:]]
        for corrupt in broken:
            with self.assertRaises(enc.AudioEncodeError):
                acbw.read_utf(corrupt)


class Afs2Tests(unittest.TestCase):
    def test_stock_layout_and_parsing(self):
        bank = acbw.write_afs2([(0, b"first entry"), (7, b"second")], alignment=32, subkey=0x1234)
        self.assertEqual(bank[:8], b"AFS2\x02\x04\x02\x00")
        count, alignment, subkey = struct.unpack_from("<IHH", bank, 8)
        self.assertEqual((count, alignment, subkey), (2, 32, 0x1234))
        header = acbw.afs2_header_size(2)
        self.assertEqual(header, 16 + 4 + 12)
        offsets = struct.unpack_from("<III", bank, 20)
        self.assertEqual(offsets[0], header)
        self.assertEqual(offsets[1], 32 + len(b"first entry"))
        self.assertEqual(offsets[2], len(bank))
        self.assertEqual(cri.awb_entries(bank), [{"id": 0, "start": 32, "end": 43, "subkey": 0x1234},
                                                 {"id": 7, "start": 64, "end": 70, "subkey": 0x1234}])
        parsed = acbw.read_afs2(bank)
        self.assertEqual(parsed["entries"], [(0, b"first entry"), (7, b"second")])
        rebuilt = acbw.write_afs2(parsed["entries"], version=parsed["version"], offset_size=parsed["offsetSize"],
                                  id_size=parsed["idSize"], alignment=parsed["alignment"], subkey=parsed["subkey"])
        self.assertEqual(rebuilt, bank)
        single = acbw.write_afs2([(0, b"x" * 100)])
        self.assertEqual(acbw.afs2_header_size(1), 26)
        self.assertEqual(struct.unpack_from("<II", single, 18), (26, 132))
        for entries, options in (([], {}), ([(0, b"a"), (0, b"b")], {}), ([(0, b"")], {}), ([(70000, b"a")], {}),
                                 ([(0, b"a")], {"offset_size": 3}), ([(0, b"a")], {"alignment": 0})):
            with self.assertRaises(ValueError):
                acbw.write_afs2(entries, **options)


class BuildCueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_pcm = tone(1.5, 300)
        cls.template_hca = enc.encode_hca(cls.template_pcm)
        cls.pcm = tone(3.2, 523.25, 659.25)
        cls.hca = enc.encode_hca(cls.pcm)
        cls.template_acb, cls.template_awb = synthetic_template(cls.template_hca)

    def build(self, **overrides):
        options = {"sheet": "music_93001", "beat": {"bpm": 128.0, "firstBeat": 0.52},
                   "guid": bytes(range(16, 32))}
        options.update(overrides)
        return acbw.build_cue(self.template_acb, self.template_awb, self.hca, **options)

    def test_replaces_only_the_audio_identity_fields(self):
        acb, awb = self.build()
        catalog = cri.inspect_cues(acb)
        self.assertEqual(catalog["sheet"], "music_93001")
        self.assertEqual([cue["name"] for cue in catalog["cues"]], ["music_93001"])
        samples = len(self.pcm)
        self.assertEqual(cri.inspect_beat_sync(acb, "music_93001"), {
            "bpm": 128.0, "numBeats": 4, "beatDenominator": 4, "baseRate": RATE,
            "startSample": round(0.52 * RATE), "endSample": samples})
        root = acbw.read_utf(acb)
        nested = lambda name: acbw.read_utf(root.value(0, name))
        self.assertEqual(nested("StreamAwbHash").value(0, "Hash"), hashlib.md5(awb).digest())
        self.assertEqual(nested("StreamAwbHash").value(0, "Name"), "music_93001")
        self.assertEqual(nested("StreamAwbAfs2Header").value(0, "Header"), awb[:28])
        self.assertEqual(root.value(0, "AcbGuid"), bytes(range(16, 32)))
        memory = acbw.read_afs2(root.value(0, "AwbFile"))
        self.assertEqual(memory["entries"], [(0, self.hca[:96 + 5 * 512])])
        self.assertEqual(cri.awb_entries(awb), [{"id": 0, "start": 32, "end": 32 + len(self.hca), "subkey": 0}])
        self.assertEqual(awb[32:], self.hca)
        waveform = nested("WaveformTable")
        self.assertEqual((waveform.value(0, "NumSamples"), waveform.value(0, "SamplingRate"),
                          waveform.value(0, "NumChannels")), (samples, RATE, 2))
        self.assertEqual(nested("CueTable").value(0, "Length"), samples * 1000 // RATE)

        template = acbw.read_utf(self.template_acb)
        self.assertEqual([(c.name, c.kind, c.storage) for c in root.columns],
                         [(c.name, c.kind, c.storage) for c in template.columns])
        replaced = {"Name", "AcbGuid", "AwbFile", "StreamAwbHash", "StreamAwbAfs2Header", "WaveformTable", "CueTable",
                    "CueNameTable", "BeatSyncInfoTable"}
        for column in template.columns:
            if column.name not in replaced:
                self.assertEqual(root.value(0, column.name), template.value(0, column.name), column.name)
        changed_fields = {
            "WaveformTable": {"NumSamples"}, "CueTable": {"Length"}, "CueNameTable": {"CueName"},
            "BeatSyncInfoTable": {"Bpm", "StartSample", "EndSample"}, "StreamAwbHash": {"Name", "Hash"},
            "StreamAwbAfs2Header": {"Header"}}
        for name, fields in changed_fields.items():
            old, new = acbw.read_utf(template.value(0, name)), nested(name)
            self.assertEqual([(c.name, c.kind, c.storage) for c in old.columns],
                             [(c.name, c.kind, c.storage) for c in new.columns], name)
            for column in old.columns:
                if column.name not in fields:
                    self.assertEqual(new.value(0, column.name), old.value(0, column.name), (name, column.name))
        # Rebuilding is deterministic for a given GUID.
        self.assertEqual(self.build(), (acb, awb))

    def test_tempo_segments_and_errors(self):
        acb, _ = self.build(beat={"segments": [{"bpm": 120.0, "startSample": 1000},
                                               {"bpm": 90.5, "startSample": 60000}]})
        beat = cri.inspect_beat_sync(acb, "music_93001")
        self.assertEqual([(s["bpm"], s["startSample"], s["endSample"]) for s in beat["segments"]],
                         [(120.0, 1000, 59999), (90.5, 60000, len(self.pcm))])
        for bad in (None, {"bpm": 0, "firstBeat": 0.1}, {"bpm": 120, "firstBeat": -1},
                    {"bpm": 120, "firstBeat": 99.0}, {"bpm": 120, "firstBeat": 0.1, "beatDenominator": 3},
                    {"segments": [{"bpm": 120.0, "startSample": 500}, {"bpm": 100.0, "startSample": 400}]},
                    {"segments": []}):
            with self.subTest(beat=bad), self.assertRaises(enc.AudioEncodeError):
                self.build(beat=bad)
        for sheet in ("", "a\0b", 5):
            with self.assertRaises(enc.AudioEncodeError):
                self.build(sheet=sheet)
        with self.assertRaises(enc.AudioEncodeError):
            self.build(guid=b"short")
        with self.assertRaises(enc.AudioEncodeError):
            acbw.build_cue(self.template_acb, self.template_awb, self.hca[:-1], sheet="x", beat={"bpm": 1, "firstBeat": 0})

    def test_malformed_caller_input_raises_audio_encode_error(self):
        bad_beats = (
            [], "beat", 5, {"segments": [1, 2]}, {"segments": [None]}, {"segments": "x"}, {"segments": None},
            {"segments": {"bpm": 120.0}}, {"segments": [{"bpm": 120.0}]}, {"segments": [{"startSample": 0}]},
            {"segments": [{"bpm": "120", "startSample": 0}]}, {"segments": [{"bpm": 120.0, "startSample": "0"}]},
            {"segments": [{"bpm": 120.0, "startSample": 1.5}]}, {"segments": [{"bpm": 120.0, "startSample": 10 ** 30}]},
            {"segments": [{"bpm": 120.0, "startSample": -5}]}, {"bpm": 120.0}, {"firstBeat": 0.0},
            {"bpm": "120", "firstBeat": 0}, {"bpm": None, "firstBeat": 0}, {"bpm": 120.0, "firstBeat": "0"},
            {"bpm": 120.0, "firstBeat": None}, {"bpm": 120.0, "firstBeat": True}, {"bpm": 120.0, "firstBeat": 1e305},
            {"bpm": 120.0, "firstBeat": 10 ** 400}, {"bpm": 120.0, "firstBeat": math.inf},
            {"bpm": 10 ** 400, "firstBeat": 0}, {"bpm": 120.0, "firstBeat": 0, "numBeats": 4.0},
            {"bpm": 120.0, "firstBeat": 0, "numBeats": "4"}, {"bpm": 120.0, "firstBeat": 0, "beatDenominator": 4.0},
            {"bpm": 120.0, "firstBeat": 0, "beatDenominator": []})
        for beat in bad_beats:
            with self.subTest(beat=beat):
                with self.assertRaises(enc.AudioEncodeError):
                    self.build(beat=beat)
                with self.assertRaises(enc.AudioEncodeError):
                    acbw.excerpt_beat(beat, 0, RATE)
                with self.assertRaises(enc.AudioEncodeError):
                    acbw.excerpt_beat(beat, 5 * RATE, RATE)
        for guid in ("0123456789abcdef", 1.5, 16, [0] * 16, object(), bytes(15)):
            with self.subTest(guid=guid), self.assertRaises(enc.AudioEncodeError):
                self.build(guid=guid)
        for guid in (bytearray(range(16)), memoryview(bytes(range(16)))):
            acb, _ = self.build(guid=guid)
            self.assertEqual(acbw.read_utf(acb).value(0, "AcbGuid"), bytes(range(16)))
        for sheet in ("music_あ", "music_\udcff", "music\n1", "a" * 256, b"music_1", None):
            with self.subTest(sheet=sheet), self.assertRaises(enc.AudioEncodeError):
                self.build(sheet=sheet)
        for raw in (None, "AFS2", 5, bytearray(self.template_awb), b"AFS2" + bytes(28)):
            with self.subTest(awb=raw), self.assertRaises(enc.AudioEncodeError):
                acbw.read_afs2(raw)
            if raw is not None:  # a missing stream template AWB means the stock AFS2 defaults
                with self.subTest(awb=raw), self.assertRaises(enc.AudioEncodeError):
                    self.build_with(template_awb=raw)
        for template in (None, "x", 5, memoryview(self.template_acb)):
            with self.subTest(template=template), self.assertRaises(enc.AudioEncodeError):
                self.build_with(template_acb=template)
            with self.subTest(template=template), self.assertRaises(enc.AudioEncodeError):
                acbw.template_info(template, self.template_awb)
        for hca in (None, "HCA", self.hca[:20], memoryview(self.hca)):
            with self.subTest(hca=type(hca)), self.assertRaises(enc.AudioEncodeError):
                self.build_with(hca=hca)
        # Whatever else goes wrong while a template is walked is reported as a layout error.
        for error in (TypeError("x"), AttributeError("x"), ZeroDivisionError("x"), struct.error("x")):
            with self.subTest(error=error), patch.object(acbw, "_nested", side_effect=error):
                with self.assertRaisesRegex(enc.AudioEncodeError, "stock music layout"):
                    self.build()
                with self.assertRaisesRegex(enc.AudioEncodeError, "stock music layout"):
                    acbw.template_info(self.template_acb, self.template_awb)

    def test_preview_refuses_malformed_input_even_without_a_beat_table(self):
        memory_acb, _ = synthetic_template(self.template_hca, streaming=0, beat_rows=0)
        song = tone(2.0, 330)
        options = {"sheet": "music_93001_SABI", "verify": False, "length_samples": RATE}
        for beat, start in (({"segments": [1]}, 0.0), ({"bpm": 120.0, "firstBeat": "0"}, 0.0),
                            ({"bpm": 120.0, "firstBeat": 0.0}, "1"), ({"bpm": 120.0, "firstBeat": 0.0}, None)):
            with self.subTest(beat=beat, start=start), self.assertRaises(enc.AudioEncodeError):
                acbw.make_preview(song, memory_acb, None, start_seconds=start, beat=beat, **options)
        preview = acbw.make_preview(song, memory_acb, None, start_seconds=1e305, beat={"bpm": 120.0, "firstBeat": 0.0},
                                    **options)
        self.assertEqual(preview["startSample"], len(song) - RATE)
        self.assertIsNone(cri.inspect_beat_sync(preview["acb"], "music_93001_SABI"))

    def test_excerpt_beat_keeps_the_caller_form(self):
        beat = {"bpm": np.float64(120.0), "firstBeat": 0.3, "numBeats": 3, "label": "kept"}
        moved = acbw.excerpt_beat(beat, RATE, 20 * RATE)
        self.assertEqual((moved["numBeats"], moved["label"]), (3, "kept"))
        self.assertAlmostEqual(moved["firstBeat"], 0.3)

    def build_with(self, **overrides):
        arguments = {"template_acb": self.template_acb, "template_awb": self.template_awb, "hca": self.hca}
        arguments.update(overrides)
        return acbw.build_cue(arguments["template_acb"], arguments["template_awb"], arguments["hca"],
                              sheet="music_93001", beat={"bpm": 128.0, "firstBeat": 0.52})

    def test_template_without_prefetch_or_stream(self):
        memory_acb, memory_awb = synthetic_template(self.template_hca, streaming=0, beat_rows=0)
        self.assertIsNone(memory_awb)
        acb, awb = acbw.build_cue(memory_acb, None, self.hca, sheet="music_93001_SABI", beat=None)
        self.assertIsNone(awb)
        root = acbw.read_utf(acb)
        self.assertEqual(acbw.read_afs2(root.value(0, "AwbFile"))["entries"], [(0, self.hca)])
        self.assertEqual(cri.inspect_cues(acb)["cues"][0]["waveforms"], [{"waveformIndex": 0, "awbId": 0, "streaming": False}])
        # A beat for a template with an empty beat table creates one in the stock schema.
        acb, _ = acbw.build_cue(memory_acb, None, self.hca, sheet="music_93001_SABI", beat={"bpm": 100, "firstBeat": 0})
        self.assertEqual(cri.inspect_beat_sync(acb, "music_93001_SABI")["bpm"], 100.0)
        stream_acb, stream_awb = synthetic_template(self.template_hca, streaming=1)
        acb, awb = acbw.build_cue(stream_acb, stream_awb, self.hca, sheet="music_93002", beat={"bpm": 1, "firstBeat": 0})
        self.assertEqual(acbw.read_utf(acb).value(0, "AwbFile"), b"")
        self.assertEqual(awb[32:], self.hca)

    def test_empty_beat_table_stays_empty_without_a_beat(self):
        root = acbw.read_utf(self.template_acb)
        beats = acbw.read_utf(root.value(0, "BeatSyncInfoTable"))
        beats.resize(0)
        root.set(0, "BeatSyncInfoTable", acbw.write_utf(beats))
        template = acbw.write_utf(root)
        acb, _ = acbw.build_cue(template, self.template_awb, self.hca, sheet="music_93001_SABI", beat=None)
        self.assertEqual(acbw.read_utf(acb).value(0, "BeatSyncInfoTable"), acbw.write_utf(beats))
        self.assertIsNone(cri.inspect_beat_sync(acb, "music_93001_SABI"))
        self.assertFalse(acbw.template_info(template)["hasBeats"])

    def test_prefetch_follows_the_template_and_short_streams(self):
        acb_two, awb_two = synthetic_template(self.template_hca, prefetch_blocks=2)
        acb, _ = acbw.build_cue(acb_two, awb_two, self.hca, sheet="music_93001", beat={"bpm": 1, "firstBeat": 0})
        self.assertEqual(acbw.read_afs2(acbw.read_utf(acb).value(0, "AwbFile"))["entries"][0][1], self.hca[:96 + 2 * 512])
        tiny = enc.encode_hca(tone(0.01, 440))
        acb, awb = acbw.build_cue(self.template_acb, self.template_awb, tiny, sheet="music_93003",
                                  beat={"bpm": 120, "firstBeat": 0})
        self.assertEqual(acbw.read_afs2(acbw.read_utf(acb).value(0, "AwbFile"))["entries"][0][1], tiny)

    def test_rejects_unsupported_templates(self):
        for options in ({"cues": 2}, {"encode_type": 0}):
            acb, awb = synthetic_template(self.template_hca, **options)
            with self.subTest(options), self.assertRaises(enc.AudioEncodeError):
                acbw.build_cue(acb, awb, self.hca, sheet="music_1", beat={"bpm": 120, "firstBeat": 0})
        acb, awb = synthetic_template(self.template_hca, beat_rows=2)
        with self.assertRaises(enc.AudioEncodeError):
            acbw.build_cue(acb, awb, self.hca, sheet="music_1", beat=None)
        with self.assertRaises(enc.AudioEncodeError):
            acbw.build_cue(b"not a cue sheet", awb, self.hca, sheet="music_1", beat={"bpm": 120, "firstBeat": 0})

    def test_two_row_template_beats_keep_flags(self):
        acb, awb = synthetic_template(self.template_hca, beat_rows=2)
        new_acb, _ = acbw.build_cue(acb, awb, self.hca, sheet="music_1", beat={"bpm": 150.0, "firstBeat": 0.25})
        beats = acbw.read_utf(acbw.read_utf(new_acb).value(0, "BeatSyncInfoTable"))
        self.assertEqual(len(beats.rows), 1)
        self.assertEqual({c.storage for c in beats.columns}, {PER_ROW})
        self.assertEqual(cri.inspect_beat_sync(new_acb, "music_1")["bpm"], 150.0)


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pcm = tone(2.0, 440, 550)
        cls.hca = enc.encode_hca(cls.pcm)
        template_acb, template_awb = synthetic_template(enc.encode_hca(tone(1.0, 200)))
        cls.acb, cls.awb = acbw.build_cue(template_acb, template_awb, cls.hca, sheet="music_93001",
                                          beat={"bpm": 120.0, "firstBeat": 0.0})

    def setUp(self):
        patcher = patch.dict(os.environ, {"ELICHIKA_HCA_LIBRARY": Clhca.get()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_decodes_with_exact_length_and_snr(self):
        result = acbw.verify_cue(self.acb, self.awb, self.pcm, cue="music_93001")
        self.assertEqual(result["frames"], len(self.pcm))
        self.assertEqual(result["decoder"], "clhca")
        self.assertGreater(result["snrDb"], 40)

    def test_refuses_mismatched_audio(self):
        cases = {"length": self.pcm[:-1], "content": tone(2.0, 300), "channels": self.pcm[:, ::-1] // 2}
        for name, pcm in cases.items():
            with self.subTest(name), self.assertRaises(enc.AudioEncodeError):
                acbw.verify_cue(self.acb, self.awb, pcm)
        wrong_key = enc.encode_hca(self.pcm, key=enc.SIFAS_HCA_KEY + 2)
        with self.assertRaises(enc.AudioEncodeError) as caught:
            acbw.verify_cue(self.acb, acbw.write_afs2([(0, wrong_key)]), self.pcm)
        self.assertEqual(str(caught.exception), "The new audio does not decode.")
        self.assertTrue(caught.exception.details["cause"])

    def test_refusals_keep_numbers_out_of_the_message(self):
        # The message is a fixed sentence (a translation key); the numbers are in details.
        with self.assertRaises(enc.AudioEncodeError) as caught:
            acbw.verify_cue(self.acb, self.awb, self.pcm[:-1])
        self.assertEqual(str(caught.exception), "The new audio does not decode to the input's length and channels.")
        self.assertEqual(caught.exception.details, {"samples": len(self.pcm), "channels": 2,
                                                    "expectedSamples": len(self.pcm) - 1, "expectedChannels": 2})
        with self.assertRaises(enc.AudioEncodeError) as caught:
            acbw.verify_cue(self.acb, self.awb, self.pcm, snr_floor=200.0)
        self.assertEqual(str(caught.exception), "The decoded audio differs too much from the input.")
        self.assertEqual(caught.exception.details["snrFloorDb"], 200.0)
        self.assertGreater(caught.exception.details["snrDb"], 40)
        with self.assertRaises(enc.AudioEncodeError) as caught:
            acbw.build_cue(b"not a cue sheet", self.awb, self.hca, sheet="music_1", beat=None)
        self.assertEqual(str(caught.exception), "The template cue sheet cannot be read.")
        self.assertIn("cause", caught.exception.details)

    def test_requires_the_bundled_decoder(self):
        self.assertTrue(acbw.encoder_available())
        with patch.object(cri, "_native_library", return_value=None):
            self.assertFalse(acbw.encoder_available())
            with self.assertRaisesRegex(enc.AudioEncodeError, "decoder is missing"):
                acbw.verify_cue(self.acb, self.awb, self.pcm)


class RegistrationHelperTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"ELICHIKA_HCA_LIBRARY": Clhca.get()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_template_info_and_one_call_cue(self):
        template_acb, template_awb = synthetic_template(enc.encode_hca(tone(1.0, 200)))
        self.assertEqual(acbw.template_info(template_acb, template_awb), {
            "sheet": "template", "sampleCount": RATE, "sampleRate": RATE, "streaming": 2, "subkey": 0,
            "hasBeats": True})
        song = tone(30.0, 330, 440, level=0.3)
        seen = []
        result = acbw.make_cue(song, template_acb, template_awb, sheet="music_93001",
                               beat={"bpm": 128.0, "firstBeat": 0.5}, progress=lambda done, total: seen.append(done))
        self.assertEqual(result["sampleCount"], len(song))
        self.assertGreater(result["snrDb"], 40)
        self.assertEqual(cri.inspect_cues(result["acb"])["sheet"], "music_93001")
        self.assertTrue(seen)

        preview = acbw.make_preview(song, template_acb, template_awb, sheet="music_93001_SABI", start_seconds=25.0,
                                    beat={"bpm": 120.0, "firstBeat": 0.3})
        self.assertEqual(preview["startSample"], 10 * RATE)
        self.assertEqual(preview["sampleCount"], 20 * RATE)
        beat = cri.inspect_beat_sync(preview["acb"], "music_93001_SABI")
        self.assertEqual((beat["bpm"], beat["startSample"], beat["endSample"]), (120.0, round(0.3 * RATE), 20 * RATE))
        short = acbw.make_preview(song, template_acb, template_awb, sheet="music_93001_SABI", start_seconds=3.0,
                                  beat={"bpm": 120.0, "firstBeat": 0.3}, length_samples=5 * RATE, verify=False)
        self.assertEqual((short["startSample"], short["sampleCount"], short["snrDb"]), (3 * RATE, 5 * RATE, None))

    def test_snr_floor_reaches_the_decode_check(self):
        template_acb, template_awb = synthetic_template(enc.encode_hca(tone(1.0, 200)))
        song = tone(3.0, 330, 440, level=0.3)
        beat = {"bpm": 120.0, "firstBeat": 0.0}
        cue = acbw.make_cue(song, template_acb, template_awb, sheet="music_93001", beat=beat, snr_floor=30.0)
        self.assertGreater(cue["snrDb"], 30.0)
        # The tone decodes well above the default floor but not at 200 dB.
        with self.assertRaisesRegex(enc.AudioEncodeError, "differs too much"):
            acbw.make_cue(song, template_acb, template_awb, sheet="music_93001", beat=beat, snr_floor=200.0)
        with self.assertRaisesRegex(enc.AudioEncodeError, "differs too much"):
            acbw.make_preview(song, template_acb, template_awb, sheet="music_93001_SABI", start_seconds=0.5,
                              beat=beat, length_samples=RATE, snr_floor=200.0)
        preview = acbw.make_preview(song, template_acb, template_awb, sheet="music_93001_SABI", start_seconds=0.5,
                                    beat=beat, length_samples=RATE, snr_floor=-math.inf)
        self.assertGreater(preview["snrDb"], 30.0)
        # A floor that is not a number is refused before any encoding starts.
        with patch.object(acbw, "encode_hca", side_effect=AssertionError("encoded")):
            for floor in ("8", None, math.nan, True, [8.0]):
                with self.subTest(floor=floor), self.assertRaises(enc.AudioEncodeError):
                    acbw.make_cue(song, template_acb, template_awb, sheet="music_93001", beat=beat, snr_floor=floor)
                with self.subTest(floor=floor), self.assertRaises(enc.AudioEncodeError):
                    acbw.make_preview(song, template_acb, template_awb, sheet="music_93001_SABI", start_seconds=0.0,
                                      beat=beat, snr_floor=floor)
        with self.assertRaises(enc.AudioEncodeError):
            acbw.verify_cue(cue["acb"], cue["awb"], song, snr_floor="8")
        # Without verification the floor is not used.
        unchecked = acbw.make_cue(song, template_acb, template_awb, sheet="music_93001", beat=beat, verify=False,
                                  snr_floor=200.0)
        self.assertIsNone(unchecked["snrDb"])

    def test_subkey_of_the_template_bank_keys_the_stream(self):
        template_hca = enc.encode_hca(tone(1.0, 200), subkey=0x51)
        template_acb, template_awb = synthetic_template(template_hca, subkey=0x51)
        self.assertEqual(acbw.template_info(template_acb, template_awb)["subkey"], 0x51)
        result = acbw.make_cue(tone(2.0, 440), template_acb, template_awb, sheet="music_93001",
                               beat={"bpm": 90.0, "firstBeat": 0.0})
        self.assertEqual(cri.awb_entries(result["awb"])[0]["subkey"], 0x51)
        self.assertGreater(result["snrDb"], 40)
        with self.assertRaises(enc.AudioEncodeError):
            acbw.template_info(b"@UTF" + bytes(40))


class ExcerptBeatTests(unittest.TestCase):
    def test_first_beat_moves_into_the_excerpt(self):
        beat = {"bpm": 120.0, "firstBeat": 0.3}
        moved = acbw.excerpt_beat(beat, 44100 * 10, 44100 * 20)
        self.assertAlmostEqual(moved["firstBeat"], 0.3)
        moved = acbw.excerpt_beat(beat, int(44100 * 10.1), 44100 * 20)
        self.assertAlmostEqual(moved["firstBeat"], 0.2, places=4)
        self.assertIsNone(acbw.excerpt_beat(None, 0, 10))
        segments = {"segments": [{"bpm": 100.0, "startSample": 1000}, {"bpm": 150.0, "startSample": 500000}]}
        moved = acbw.excerpt_beat(segments, 441000, 882000)
        self.assertEqual(moved["segments"][0]["bpm"], 100.0)
        self.assertGreaterEqual(moved["segments"][0]["startSample"], 0)
        self.assertEqual(moved["segments"][1], {"bpm": 150.0, "startSample": 500000 - 441000})
        self.assertEqual(acbw.excerpt_beat(segments, 441000, 1000)["segments"][0]["bpm"], 100.0)
        with self.assertRaises(enc.AudioEncodeError):
            acbw.excerpt_beat(beat, -1, 10)


@unittest.skipUnless(os.environ.get("SIFAS_TEST_ACB") and os.environ.get("SIFAS_TEST_AWB"),
                     "Set private local music ACB/AWB paths for the stock rebuild check")
class PrivateStockRebuildTests(unittest.TestCase):
    def test_stock_cue_sheet_round_trips_and_rebuilds_around_its_own_audio(self):
        acb = Path(os.environ["SIFAS_TEST_ACB"]).read_bytes()
        awb = Path(os.environ["SIFAS_TEST_AWB"]).read_bytes()
        size = struct.unpack_from(">I", acb, 4)[0] + 8
        self.assertEqual(acbw.write_utf(acbw.read_utf(acb)), acb[:size])
        sheet = cri.inspect_cues(acb)["sheet"]
        with patch.dict(os.environ, {"ELICHIKA_HCA_LIBRARY": Clhca.get()}), tempfile.TemporaryDirectory() as directory:
            cri.decode_cue(acb, awb, sheet, Path(directory) / "stock.wav")
            pcm = enc.read_wav((Path(directory) / "stock.wav").read_bytes())
            beat = cri.inspect_beat_sync(acb, sheet)
            spec = ({"segments": [{"bpm": s["bpm"], "startSample": s["startSample"]} for s in beat["segments"]]}
                    if "segments" in beat else {"bpm": beat["bpm"], "firstBeat": beat["startSample"] / RATE})
            new_acb, new_awb = acbw.build_cue(acb, awb, enc.encode_hca(pcm), sheet=sheet, beat=spec,
                                              guid=acbw.read_utf(acb).value(0, "AcbGuid"))
            result = acbw.verify_cue(new_acb, new_awb, pcm)
        self.assertEqual(result["frames"], len(pcm))
        old, new = acbw.read_utf(acb), acbw.read_utf(new_acb)
        differing = {c.name for c in old.columns if old.value(0, c.name) != new.value(0, c.name)}
        self.assertLessEqual(differing, {"AwbFile", "StreamAwbHash", "StreamAwbAfs2Header", "BeatSyncInfoTable"})


if __name__ == "__main__":
    unittest.main()
