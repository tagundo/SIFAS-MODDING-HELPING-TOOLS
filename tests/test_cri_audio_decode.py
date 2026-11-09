"""Original cue tables and nonzero audio, plus opt-in private game assets."""
import array
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from webtools.core import cri_audio_decode as cri


def utf_table(name, columns, rows):
    """Small original @UTF writer used only to build test containers."""
    strings, positions, blobs = bytearray(), {}, bytearray()
    def string(value):
        if value not in positions:
            positions[value] = len(strings); strings.extend(value.encode() + b"\0")
        return positions[value]
    name_index = string(name)
    declarations = b"".join(struct.pack(">BI", 0x50 | kind, string(key)) for key, kind in columns)
    payload = bytearray()
    widths = {0: 1, 2: 2, 4: 4, 10: 4, 11: 8}
    for row in rows:
        for key, kind in columns:
            value = row[key]
            if kind == 10:
                payload.extend(struct.pack(">I", string(value)))
            elif kind == 11:
                payload.extend(struct.pack(">II", len(blobs), len(value))); blobs.extend(value)
            else:
                payload.extend(struct.pack({0: ">B", 2: ">H", 4: ">I"}[kind], value))
    row_at = 32 + len(declarations)
    string_at = row_at + len(payload)
    data_at = string_at + len(strings)
    end = data_at + len(blobs)
    return struct.pack(">4sIHHIIIHHI", b"@UTF", end - 8, 1, row_at - 8, string_at - 8, data_at - 8,
        name_index, len(columns), sum(widths[k] for _, k in columns), len(rows)) + declarations + payload + strings + blobs


def original_acb(*, cue="original-tone", sheet="original-sheet", wave_id=17, reference_type=2, duplicate=False):
    waveforms = utf_table("Waveform", [("Id", 2), ("Streaming", 0)], [{"Id": wave_id, "Streaming": 1}])
    synths = utf_table("Synth", [("Type", 0), ("ReferenceItems", 11)], [{"Type": 0, "ReferenceItems": struct.pack(">HH", 1, 0)}])
    cues = utf_table("Cue", [("CueId", 4), ("ReferenceType", 0), ("ReferenceIndex", 2)], [{"CueId": 901, "ReferenceType": reference_type, "ReferenceIndex": 0}])
    names = [{"CueName": cue, "CueIndex": 0}]
    if duplicate:
        names.append(dict(names[0]))
    name_table = utf_table("CueName", [("CueName", 10), ("CueIndex", 2)], names)
    return utf_table("Header", [("Name", 10), ("WaveformTable", 11), ("SynthTable", 11), ("CueTable", 11), ("CueNameTable", 11)],
        [{"Name": sheet, "WaveformTable": waveforms, "SynthTable": synths, "CueTable": cues, "CueNameTable": name_table}])


def original_awb(stream, ident=17):
    start = 32
    return struct.pack("<4sBBBBIHHHII", b"AFS2", 1, 4, 2, 0, 1, 16, 0, ident, start, start + len(stream)).ljust(start, b"\0") + stream


class CriTableTests(unittest.TestCase):
    def test_exact_cue_name_and_id_follow_synth_to_distinct_awb_id(self):
        result = cri.inspect_cues(original_acb())
        self.assertEqual(result["sheet"], "original-sheet")
        self.assertEqual(result["cues"][0]["id"], 901)
        self.assertEqual(result["cues"][0]["waveforms"], [{"waveformIndex": 0, "awbId": 17, "streaming": True}])
        entries = cri.awb_entries(original_awb(b"original-stream"))
        self.assertEqual(entries, [{"id": 17, "start": 32, "end": 47, "subkey": 0}])

    def test_corrupt_offsets_counts_and_wave_ranges_are_rejected(self):
        raw = original_acb()
        cases = [b"", b"@UTF", raw[:31]]
        for at, value in ((4, 0xffffffff), (12, 0xffffffff), (16, 0xffffffff), (28, 0xffffffff)):
            corrupt = bytearray(raw); struct.pack_into(">I", corrupt, at, value); cases.append(bytes(corrupt))
        for corrupt in cases:
            with self.subTest(length=len(corrupt)), self.assertRaises(cri.AudioDecodeError):
                cri.utf_rows(corrupt)
        for raw in (b"", b"AFS2", original_awb(b"x")[:31]):
            with self.assertRaises(cri.AudioDecodeError):
                cri.awb_entries(raw)

    def test_unknown_or_duplicate_cue_never_plays_bank_entry_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out.wav"
            for acb, cue in ((original_acb(), "different-cue"), (original_acb(duplicate=True), "original-tone")):
                with self.assertRaisesRegex(cri.AudioDecodeError, "missing or ambiguous"):
                    cri.decode_cue(acb, original_awb(b"not-a-codec"), cue, out)
                self.assertFalse(out.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg generates original ADX fixture")
    def test_original_nonzero_adx_audio_decodes_selected_cue_to_pcm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adx = root / "tone.adx"
            pcm = array.array("h", [int(18000 * math.sin(index * 2 * math.pi * 440 / 44100)) for index in range(44100)])
            process = subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", "44100", "-ac", "1", "-i", "pipe:0", "-c:a", "adpcm_adx", "-y", str(adx)],
                input=pcm.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = cri.decode_cue(original_acb(), original_awb(adx.read_bytes()), "original-tone", root / "tone.wav")
            self.assertEqual(result["waveId"], 17)
            self.assertEqual(result["cueId"], 901)
            with wave.open(str(root / "tone.wav"), "rb") as decoded:
                self.assertEqual(decoded.getnchannels(), 1)
                samples = array.array("h"); samples.frombytes(decoded.readframes(decoded.getnframes()))
            self.assertGreater(sum(value != 0 for value in samples), 40000)
            self.assertGreater(max(samples), 10000)


@unittest.skipUnless(os.environ.get("SIFAS_TEST_ACB") and os.environ.get("SIFAS_TEST_AWB"), "Set private local ACB/AWB paths for real game audio integration")
class PrivateNativeHcaTests(unittest.TestCase):
    def test_actual_selected_game_cue_has_nonzero_pcm_with_ffmpeg_disabled(self):
        acb, awb = Path(os.environ["SIFAS_TEST_ACB"]).read_bytes(), Path(os.environ["SIFAS_TEST_AWB"]).read_bytes()
        cue = os.environ.get("SIFAS_TEST_CUE")
        with tempfile.TemporaryDirectory() as directory, patch.object(cri.shutil, "which", return_value=None):
            out = Path(directory) / "private.wav"
            result = cri.decode_cue(acb, awb, cue, out)
            self.assertEqual(result["decoder"], "clhca")
            self.assertGreater(result["duration"], 1)
            with wave.open(str(out), "rb") as stream:
                samples = array.array("h"); samples.frombytes(stream.readframes(stream.getnframes()))
            self.assertGreater(sum(sample != 0 for sample in samples), result["frames"] // 2)
            self.assertGreater(max(abs(sample) for sample in samples), 1000)


if __name__ == "__main__":
    unittest.main()
