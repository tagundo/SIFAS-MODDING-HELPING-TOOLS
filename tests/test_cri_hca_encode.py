"""HCA encoder port: tables against the vendored clHCA, frames, and decode-back.

Only synthetic audio is used. The clHCA decoder is compiled from the vendored
source into a temporary directory; those tests are skipped without a C compiler.
Set MODTOOLS_SLOW_TESTS=1 to time a 4-minute stereo encode.
"""
import ctypes
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

import numpy as np

from webtools.core import cri_audio_decode as cri
from webtools.core import cri_hca_encode as enc

RATE = 44100
CLHCA = Path(enc.__file__).parent / "resources" / "cri_hca"


def compiler():
    return shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


def clhca_table(name, kind="hex"):
    source = (CLHCA / "clhca_data.h").read_text()
    match = re.search(re.escape(name) + r"\[[^\]]*\](?:\[[^\]]*\])? = \{(.*?)\};", source, re.S)
    body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    if kind == "float":
        return [float(value.rstrip("f")) for value in re.findall(r"[+-]?\d+\.\d+f", body)]
    return [int(value, 0) for value in re.findall(r"0x[0-9A-Fa-f]+|\d+", body)]


def as_float32(words):
    return np.array(words, dtype=np.uint32).view(np.float32)


def stereo(left, right=None):
    right = left if right is None else right
    return np.clip(np.rint(np.stack([left, right], axis=1) * 32767), -32768, 32767).astype(np.int16)


class ClhcaBuild:
    """clHCA plus a probe for its static type-56 table, built once per run."""
    directory = None
    library = None

    @classmethod
    def get(cls):
        if cls.library is None:
            cc = compiler()
            if not cc:
                raise unittest.SkipTest("No C compiler to build the vendored clHCA decoder")
            cls.directory = tempfile.TemporaryDirectory()
            harness = Path(cls.directory.name) / "harness.c"
            harness.write_text(
                f'#include "{(CLHCA / "clhca.c").as_posix()}"\n'
                "void probe_cipher56(unsigned long long key, unsigned char* out) { cipher_init56(out, key); }\n")
            library = Path(cls.directory.name) / "libelichika_hca.so"
            subprocess.run([cc, "-O2", "-shared", "-fPIC", str(harness), "-o", str(library)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cls.library = str(library)
        return cls.library


def decode(hca, subkey=0):
    with patch.dict(os.environ, {"ELICHIKA_HCA_LIBRARY": ClhcaBuild.get()}), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "decoded.wav"
        meta = cri._decode_native(hca, path, subkey)
        with wave.open(str(path), "rb") as stream:
            pcm = np.frombuffer(stream.readframes(stream.getnframes()), "<i2").reshape(-1, stream.getnchannels())
    return meta, pcm.copy()


def mdct_reference(current, previous):
    """Per-subframe Mdct.RunMdct with the fast Dct4 of src/VGAudio/Utilities/Mdct.cs."""
    bits, size, half = 7, 128, 64
    window, scale = enc.MDCT_WINDOW, math.sqrt(2.0 / 128)

    def trig(size_bits):
        n = 1 << size_bits
        values = [math.pi * (4 * i + 1) / (4 * n) for i in range(n)]
        return [math.sin(v) for v in values], [math.cos(v) for v in values]

    def reverse(value, count):  # src/VGAudio/Utilities/Bit.cs BitReverse32(value, bitCount)
        result = int(f"{value:032b}"[::-1], 2)
        return result >> (32 - count)

    sin_tables, cos_tables = zip(*[trig(i) for i in range(bits + 1)])
    shuffle = [reverse(i ^ (i // 2), bits) for i in range(size)]
    dct_in = [0.0] * size
    for i in range(half):
        a = window[half - i - 1] * -current[half + i]
        b = window[half + i] * current[half - i - 1]
        c = window[i] * previous[i]
        d = window[size - i - 1] * previous[size - i - 1]
        dct_in[i] = a - b
        dct_in[half + i] = c - d
    temp = [0.0] * size
    for i in range(half):
        a, b = dct_in[2 * i], dct_in[size - 1 - 2 * i]
        temp[2 * i] = a * cos_tables[bits][i] + b * sin_tables[bits][i]
        temp[2 * i + 1] = a * sin_tables[bits][i] - b * cos_tables[bits][i]
    stages = bits - 1
    for stage in range(stages):
        blocks, block_bits = 1 << stage, stages - stage
        block_size, block_half = 1 << block_bits, 1 << (block_bits - 1)
        sin, cos = sin_tables[block_bits - 1], cos_tables[block_bits - 1]
        for block in range(blocks):
            for i in range(block_half):
                front = (block * block_size + i) * 2
                back = front + block_size
                a = temp[front] - temp[back]
                b = temp[front + 1] - temp[back + 1]
                temp[front] += temp[back]
                temp[front + 1] += temp[back + 1]
                temp[back] = a * cos[i] + b * sin[i]
                temp[back + 1] = a * sin[i] - b * cos[i]
    return [temp[shuffle[i]] * scale for i in range(size)]


class TableTests(unittest.TestCase):
    def test_stock_parameters_follow_the_upstream_band_rule(self):
        self.assertEqual(enc.band_counts(2, 44100, 176400), {
            "frameSize": 512, "totalBandCount": 128, "baseBandCount": 64, "stereoBandCount": 64,
            "hfrGroupCount": 0, "bandsPerHfrGroup": 0})
        self.assertEqual(enc.UPSTREAM_COMMIT, "9d8f6ea04c83cccccb3dd7851a631bbd53a8dbbe")
        readme = (Path(enc.__file__).parent / "resources" / "cri_hca_encoder" / "README.md").read_text()
        self.assertIn(enc.UPSTREAM_COMMIT, readme)
        licence = (Path(enc.__file__).parent / "resources" / "cri_hca_encoder" / "LICENSE").read_text()
        self.assertTrue(licence.startswith("The MIT License (MIT)"))

    def test_crc_resolution_scaling_and_window_match_clhca(self):
        self.assertEqual(enc.CRC16_TABLE.tolist(), clhca_table("hcacommon_crc_mask_table"))
        np.testing.assert_array_equal(as_float32(clhca_table("hcadequantizer_scaling_table_float_hex")),
                                      enc.DEQUANTIZER_SCALING_TABLE.astype(np.float32))
        self.assertEqual(enc.QUANTIZED_SPECTRUM_MAX_BITS.tolist(), clhca_table("hcatbdecoder_max_bit_table"))
        window = as_float32(clhca_table("hcaimdct_window_float_hex"))
        mine = enc.MDCT_WINDOW.astype(np.float32)
        np.testing.assert_array_equal(window[:64], mine[:64])
        np.testing.assert_array_equal(window[64:], -mine[64:])
        ratios = as_float32(clhca_table("hcadecoder_intensity_ratio_table_hex"))
        np.testing.assert_allclose(enc.INTENSITY_RATIO_BOUNDS_TABLE, (ratios[:14] + ratios[1:15]) / 2, rtol=1e-6)

        invert = clhca_table("hcadecoder_invert_table")
        scale = np.arange(1, 64)[:, None]
        noise = np.arange(0, 320)[None, :]
        mine = enc.calculate_resolution(np.broadcast_to(scale, (63, 320)), np.broadcast_to(noise, (63, 320)))
        for (row, column), value in np.ndenumerate(mine):
            position = int(noise[0, column]) + 1 - ((5 * int(scale[row, 0])) >> 1)
            decoder = 15 if position < 0 else invert[position] if position <= 65 else 0
            self.assertEqual(int(value), min(max(decoder, 1), 15), (row, column))
        self.assertEqual(int(enc.calculate_resolution(np.array(0), np.array(10))), 0)

    def test_spectrum_codes_are_the_decoder_prefix_codes(self):
        read_bits = clhca_table("hcatbdecoder_read_bit_table")
        read_values = clhca_table("hcatbdecoder_read_val_table", kind="float")
        max_bits = enc.QUANTIZED_SPECTRUM_MAX_BITS
        for resolution in range(1, 8):
            for value in range(-resolution, resolution + 1):
                code = int(enc.QUANTIZE_SPECTRUM_VALUE[resolution][value + 8])
                bits = int(enc.QUANTIZE_SPECTRUM_BITS[resolution][value + 8])
                spare = int(max_bits[resolution]) - bits
                self.assertGreater(bits, 0)
                for suffix in range(1 << spare):
                    peek = (code << spare) | suffix
                    self.assertEqual(read_bits[resolution * 16 + peek], bits, (resolution, value))
                    self.assertEqual(read_values[resolution * 16 + peek], value, (resolution, value))

    def test_folded_mdct_equals_the_upstream_mdct_and_fast_dct4(self):
        rng = np.random.default_rng(3)
        current, previous = rng.standard_normal((2, 128)), rng.standard_normal((2, 128))
        ported = enc.mdct(current, previous)
        np.testing.assert_allclose(ported[0], mdct_reference(current[0], previous[0]), atol=1e-12)
        blocks = np.stack([previous, current], axis=1)  # (2 channels, 2 blocks, 128)
        np.testing.assert_allclose(enc._mdct_blocks(blocks)[:, 0], ported, atol=1e-12)


class CipherTests(unittest.TestCase):
    def test_type56_tables_match_clhca_and_invert(self):
        library = ctypes.CDLL(ClhcaBuild.get())
        library.probe_cipher56.argtypes = [ctypes.c_ulonglong, ctypes.c_char_p]
        for key in (enc.SIFAS_HCA_KEY, 1, 0x0123456789ABCDEF, enc.awb_key(enc.SIFAS_HCA_KEY, 0x1234)):
            out = ctypes.create_string_buffer(256)
            library.probe_cipher56(key, out)
            table = enc.decryption_table(key)
            self.assertEqual(table, out.raw, hex(key))
            self.assertEqual(sorted(table), list(range(256)))
            self.assertEqual(table[0xFF], 0xFF)
            data = bytes(np.random.default_rng(key & 0xFFFF).integers(0, 256, 510, dtype=np.uint8))
            self.assertEqual(data.translate(enc.encryption_table(key)).translate(table), data)
        with self.assertRaises(enc.AudioEncodeError):
            enc.decryption_table(0)

    def test_awb_subkey_rule_matches_the_decoder(self):
        self.assertEqual(enc.awb_key(enc.SIFAS_HCA_KEY, 0), enc.SIFAS_HCA_KEY)
        subkey = 0x2A
        self.assertEqual(enc.awb_key(enc.SIFAS_HCA_KEY, subkey),
                         (enc.SIFAS_HCA_KEY * ((subkey << 16) | ((~subkey + 2) & 0xFFFF))) & ((1 << 64) - 1))


class FrameTests(unittest.TestCase):
    def test_header_has_the_stock_parameter_set(self):
        for samples, padding in ((1, 1024 - 129), (896, 0), (1024, 896), (4704000, 128), (4838400, 896)):
            header = enc.hca_header(samples)
            self.assertEqual(len(header), 96)
            self.assertEqual(enc.crc16(header), 0)
            info = enc.hca_info(header)
            self.assertEqual({key: info[key] for key in (
                "version", "headerSize", "channels", "sampleRate", "frameSize", "minResolution", "maxResolution",
                "trackCount", "channelConfig", "totalBandCount", "baseBandCount", "stereoBandCount",
                "bandsPerHfrGroup", "cipherType", "encoderDelay", "encoderPadding", "sampleCount")}, {
                "version": 0x0200, "headerSize": 96, "channels": 2, "sampleRate": 44100, "frameSize": 512,
                "minResolution": 1, "maxResolution": 15, "trackCount": 1, "channelConfig": 0,
                "totalBandCount": 128, "baseBandCount": 64, "stereoBandCount": 64, "bandsPerHfrGroup": 0,
                "cipherType": 56, "encoderDelay": 128, "encoderPadding": padding, "sampleCount": samples})
            self.assertEqual(info["frameCount"] * 1024, samples + 128 + padding)
            # Keyed streams mask chunk names like stock files do.
            self.assertEqual(header[:4], b"\xc8\xc3\xc1\x00")
        self.assertEqual(enc.hca_info(enc.hca_header(100, encrypted=False))["cipherType"], 0)

    def test_header_reads_back_through_the_bundled_decoder(self):
        library = ctypes.CDLL(ClhcaBuild.get())
        library.clHCA_new.restype = ctypes.c_void_p
        library.clHCA_delete.argtypes = [ctypes.c_void_p]
        library.clHCA_SetKey.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong]
        library.clHCA_DecodeHeader.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        library.clHCA_getInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(cri._HCAInfo)]
        handle = library.clHCA_new()
        try:
            library.clHCA_SetKey(handle, enc.SIFAS_HCA_KEY)
            header = ctypes.create_string_buffer(enc.hca_header(44100 * 3))
            self.assertEqual(library.clHCA_DecodeHeader(handle, header, 96), 0)
            info = cri._HCAInfo()
            self.assertEqual(library.clHCA_getInfo(handle, ctypes.byref(info)), 0)
            self.assertEqual((info.version, info.headerSize, info.samplingRate, info.channelCount, info.blockSize,
                              info.encoderDelay, info.samplesPerBlock, info.encryptionEnabled, info.sampleCount),
                             (0x0200, 96, 44100, 2, 512, 128, 1024, 1, 44100 * 3))
        finally:
            library.clHCA_delete(handle)

    def test_frames_have_valid_crc_sync_and_cipher(self):
        t = np.arange(RATE) / RATE
        pcm = stereo(0.4 * np.sin(2 * np.pi * 330 * t), 0.3 * np.sin(2 * np.pi * 495 * t))
        plain = enc.encode_hca(pcm, encrypt=False)
        keyed = enc.encode_hca(pcm)
        info = enc.hca_info(keyed)
        self.assertEqual(len(keyed), 96 + info["frameCount"] * 512)
        self.assertEqual(info["frameCount"], -(-(RATE + 128) // 1024))
        table = enc.decryption_table(enc.SIFAS_HCA_KEY)
        for index in range(info["frameCount"]):
            frame = keyed[96 + index * 512:96 + (index + 1) * 512]
            clear = plain[96 + index * 512:96 + (index + 1) * 512]
            self.assertEqual(enc.crc16(frame), 0, index)
            self.assertEqual(enc.crc16(clear), 0, index)
            self.assertEqual(frame[:2], b"\xff\xff")
            self.assertEqual(frame[:510].translate(table), clear[:510], index)
            self.assertEqual(enc.decrypt_frame(frame)[:510], clear[:510])

    def test_counted_bits_equal_packed_bits(self):
        rng = np.random.default_rng(9)
        pcm = stereo(np.clip(rng.standard_normal(1024 * 24) * 0.3, -1, 1),
                     np.clip(rng.standard_normal(1024 * 24) * 0.1, -1, 1))
        # The analysis steps of _encode_chunk, keeping the packer's bit lengths.
        blocks = enc._float_range(pcm, -128, 24 * 1024).reshape(2, -1, 128)
        spectra = enc._mdct_blocks(blocks).reshape(2, 24, 8, 128)
        intensity = enc._encode_intensity_stereo(spectra)
        factors = enc._scale_factors(spectra)
        scaled = enc._scale_spectra(spectra, factors)
        headers, delta_bits = enc._header_lengths(factors)
        costs = enc._bit_costs(scaled)
        level = enc._search_level(costs, factors, headers, 4096)
        self.assertTrue((level > 0).all())
        boundary = enc._search_boundary(costs, factors, headers, level, 4096)
        counted = enc._used_bits(costs, factors, headers, level, boundary)
        noise = level[:, None] - (np.arange(128)[None, :] < boundary[:, None])
        resolution = np.stack([enc.calculate_resolution(factors[c], noise) for c in range(2)])
        quantized = np.where(resolution[:, :, None, :] == 0, 0, enc._quantize(scaled, resolution[:, :, None, :]))
        packed, used = enc._pack_frames(level, boundary, factors, delta_bits, intensity, resolution, quantized)
        # Counted bits include the 16-bit checksum the packer leaves for later.
        np.testing.assert_array_equal(used + 16, counted)
        self.assertTrue((counted <= 4096).all())
        self.assertGreater(int(counted.min()), 4096 - 64)
        np.testing.assert_array_equal(packed, enc._encode_chunk(pcm, 0, 24))
        for frame, length in zip(packed, used):
            self.assertFalse(np.unpackbits(frame)[length:].any())

    def test_band_removal_frees_bits_from_the_top_band_pair(self):
        factors = np.zeros((2, 1, 128), dtype=np.int64)
        factors[0, 0, :] = 40
        factors[1, 0, :64] = 40
        costs = np.zeros((2, 1, 128, 16), dtype=np.int64)
        costs[..., 1:] = 40
        headers, _ = enc._header_lengths(factors)
        self.assertEqual(enc._search_level(costs, factors, headers, 4096).tolist(), [-1])
        kept, level = enc._remove_bands(costs, factors, 4096, 0)
        self.assertGreaterEqual(level, 0)
        removed = int((kept[0] == 0).sum())
        self.assertEqual(removed % 2, 0)
        self.assertTrue((kept[0, 128 - removed:] == 0).all() and (kept[0, :128 - removed] == 40).all())
        headers, _ = enc._header_lengths(kept[:, None, :])
        used = enc._used_bits(costs, kept[:, None, :], headers, np.array([level]), np.array([0]))
        self.assertLessEqual(int(used[0]), 4096)

    def test_frame_pipeline_names_its_upstream_function(self):
        import inspect
        self.assertIn("src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (EncodeFrame", inspect.getcomments(enc._encode_chunk))

    def test_rejects_unsupported_pcm(self):
        for bad in (np.zeros((10, 1), np.int16), np.zeros((10, 2), np.int32), np.zeros((0, 2), np.int16),
                    np.zeros(20, np.int16)):
            with self.assertRaises(enc.AudioEncodeError):
                enc.encode_hca(bad)

    def test_progress_reports_and_can_cancel(self):
        pcm = stereo(np.zeros(1024 * 600))
        seen = []
        enc.encode_hca(pcm, progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (601, 601))
        self.assertEqual(len(seen), 2)

        class Cancelled(Exception):
            pass

        def cancel(done, total):
            raise Cancelled()
        with self.assertRaises(Cancelled):
            enc.encode_hca(pcm, progress=cancel)


class RoundTripTests(unittest.TestCase):
    def check(self, pcm, minimum):
        hca = enc.encode_hca(pcm)
        meta, decoded = decode(hca)
        self.assertEqual(meta["backend"], "clhca")
        self.assertEqual(meta["frames"], len(pcm))
        self.assertEqual(decoded.shape, pcm.shape)
        snr = enc.snr_db(pcm, decoded)
        self.assertGreaterEqual(snr, max(minimum, enc.SNR_FLOOR_DB))
        return snr, decoded

    def test_signals_decode_with_exact_length_and_snr(self):
        rng = np.random.default_rng(21)
        t = np.arange(RATE * 2) / RATE
        pink = np.fft.irfft(np.fft.rfft(rng.standard_normal(len(t))) / np.sqrt(np.maximum(np.arange(len(t) // 2 + 1), 1)), len(t))
        pink = 0.5 * pink / np.abs(pink).max()
        cases = {
            "sine": (stereo(0.5 * np.sin(2 * np.pi * 440 * t), 0.4 * np.sin(2 * np.pi * 660 * t)), 50),
            "chirp": (stereo(0.5 * np.sin(2 * np.pi * (60 * t + 2500 * t * t))), 45),
            "noise": (stereo(0.25 * rng.standard_normal(len(t)).clip(-4, 4)), 10),
            "pink stereo": (stereo(pink, np.roll(pink, 4410)), 12),
            "mono-duplicated": (stereo(0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * pink), 30),
            "one sample": (stereo(np.array([0.5])), -math.inf),
            "shorter than one frame": (stereo(0.5 * np.sin(2 * np.pi * 1000 * t[:700])), 30),
            "exactly 40 frames": (stereo(0.5 * np.sin(2 * np.pi * 300 * t[:1024 * 40])), 50),
            "frames minus delay": (stereo(0.5 * np.sin(2 * np.pi * 300 * t[:1024 * 40 - 128])), 50),
            "full scale square": (stereo(np.sign(np.sin(2 * np.pi * 100 * t))), 20),
        }
        for name, (pcm, minimum) in cases.items():
            with self.subTest(name):
                if name == "one sample":
                    hca = enc.encode_hca(pcm)
                    meta, decoded = decode(hca)
                    self.assertEqual(meta["frames"], 1)
                    self.assertEqual(decoded.shape, (1, 2))
                    continue
                snr, decoded = self.check(pcm, minimum)
                if name == "mono-duplicated":
                    np.testing.assert_array_equal(decoded[:, 0], decoded[:, 1])

    def test_silence_decodes_to_silence(self):
        pcm = np.zeros((RATE, 2), dtype=np.int16)
        meta, decoded = decode(enc.encode_hca(pcm))
        self.assertEqual(meta["frames"], RATE)
        self.assertFalse(decoded.any())
        self.assertEqual(enc.snr_db(pcm, decoded), math.inf)

    def test_snr_helper(self):
        reference = np.array([[1000, -1000], [500, 0]], dtype=np.int16)
        self.assertEqual(enc.snr_db(reference, reference), math.inf)
        self.assertAlmostEqual(enc.snr_db(reference, reference // 2), 10 * math.log10(4), places=2)
        self.assertEqual(enc.snr_db(np.zeros((2, 2)), reference), -math.inf)
        with self.assertRaises(enc.AudioEncodeError):
            enc.snr_db(reference, reference[:1])


class WavTests(unittest.TestCase):
    def test_reads_plain_and_extensible_pcm_and_skips_other_chunks(self):
        pcm = (np.arange(400, dtype=np.int16).reshape(200, 2) * 37)
        raw = enc.write_wav(pcm)
        np.testing.assert_array_equal(enc.read_wav(raw), pcm)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "std.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(44100)
                stream.writeframes(pcm.tobytes())
            np.testing.assert_array_equal(enc.read_wav(path.read_bytes()), pcm)
        body = pcm.tobytes()
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, 2, 44100, 44100 * 4, 4, 16, 22, 16, 3) + bytes.fromhex(
            "0100000000001000800000aa00389b71")
        listing = b"LIST" + struct.pack("<I", 5) + b"INFOx\0"
        chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + listing + b"data" + struct.pack("<I", len(body)) + body
        extensible = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks
        np.testing.assert_array_equal(enc.read_wav(extensible), pcm)

    def test_rejects_anything_but_exact_16_bit_stereo_44100(self):
        pcm = np.zeros((10, 2), dtype=np.int16)
        good = enc.write_wav(pcm)
        mono = enc.write_wav(np.zeros((10, 1), dtype=np.int16))
        rate = enc.write_wav(pcm, sample_rate=48000)
        float_format = bytearray(good); struct.pack_into("<H", float_format, 20, 3)
        eight_bit = bytearray(good); struct.pack_into("<H", eight_bit, 34, 8)
        bad_align = bytearray(good); struct.pack_into("<H", bad_align, 32, 3)
        wrong_size = bytearray(good); struct.pack_into("<I", wrong_size, 4, len(good))
        odd_data = good[:44 - 4] + struct.pack("<I", 39) + bytes(39) + b"\0"
        odd_data = b"RIFF" + struct.pack("<I", len(odd_data) - 8) + odd_data[8:]
        data_first = b"RIFF" + struct.pack("<I", 4 + 8 + 40 + 8 + 16) + b"WAVE" + good[36:] + good[12:36]
        two_data = good + good[36:]
        two_data = b"RIFF" + struct.pack("<I", len(two_data) - 8) + two_data[8:]
        empty = enc.write_wav(pcm)[:40] + struct.pack("<I", 0)
        empty = b"RIFF" + struct.pack("<I", len(empty) - 8) + empty[8:]
        truncated = good[:-3]
        for name, raw in (("mono", mono), ("rate", rate), ("float", float_format), ("8-bit", eight_bit),
                          ("align", bad_align), ("riff size", wrong_size), ("odd data", odd_data),
                          ("data first", data_first), ("two data", two_data), ("empty", empty),
                          ("truncated", truncated), ("not riff", b"RIFX" + good[4:]), ("short", b"RIFF")):
            with self.subTest(name), self.assertRaises(enc.AudioEncodeError):
                enc.read_wav(bytes(raw))
        with self.assertRaises(enc.AudioEncodeError):
            enc.read_wav(good, max_bytes=len(good) - 1)
        self.assertEqual(enc.read_wav(mono, channels=1).shape, (10, 1))

    def test_format_refusal_is_a_fixed_sentence_with_details(self):
        rate = enc.write_wav(np.zeros((10, 2), dtype=np.int16), sample_rate=48000)
        with self.assertRaises(enc.AudioEncodeError) as caught:
            enc.read_wav(rate)
        self.assertEqual(str(caught.exception), "The WAV file must be 44100 Hz stereo.")
        self.assertEqual(caught.exception.details, {"sampleRate": 48000, "channels": 2, "expectedSampleRate": 44100,
                                                    "expectedChannels": 2})
        with self.assertRaises(enc.AudioEncodeError) as caught:
            enc.read_wav(enc.write_wav(np.zeros((10, 2), dtype=np.int16)), sample_rate=22050)
        self.assertEqual(str(caught.exception), "The WAV file has the wrong sample rate or channel count.")
        self.assertEqual(caught.exception.details["expectedSampleRate"], 22050)


class MessageTests(unittest.TestCase):
    def test_every_audio_encode_error_message_is_a_fixed_sentence(self):
        # The UI translates messages by exact English key (webtools/i18n.py tr()),
        # so no message may be built from numbers or nested errors.
        import ast
        from webtools.core import cri_acb_write
        messages = set()
        for module in (enc, cri_acb_write):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            # The _fail helpers forward their caller's message; every other raise names a literal.
            helpers = {id(node) for function in ast.walk(tree)
                       if isinstance(function, ast.FunctionDef) and function.name == "_fail"
                       for node in ast.walk(function)}
            for node in ast.walk(tree):
                if (not isinstance(node, ast.Call) or id(node) in helpers or not isinstance(node.func, ast.Name)
                        or node.func.id not in ("_fail", "AudioEncodeError")):
                    continue
                with self.subTest(module=module.__name__, line=node.lineno):
                    self.assertTrue(node.args, "message argument missing")
                    message = node.args[0]
                    self.assertIsInstance(message, ast.Constant)
                    self.assertIsInstance(message.value, str)
                    self.assertTrue(message.value.endswith("."), message.value)
                    self.assertEqual(len(node.args), 1, "extra values go in keyword details")
                    messages.add(message.value)
        self.assertGreater(len(messages), 40)
        error = enc.AudioEncodeError("Fixed.", value=3)
        self.assertIsInstance(error, ValueError)
        self.assertEqual((str(error), error.details), ("Fixed.", {"value": 3}))
        self.assertEqual(enc.AudioEncodeError("Plain.").details, {})


class SabiTests(unittest.TestCase):
    def test_excerpt_window_fades_and_clamping(self):
        song = np.full((RATE * 60, 2), 10000, dtype=np.int16)
        song[:, 1] = -8000
        excerpt, start = enc.sabi_excerpt(song, 12.5)
        self.assertEqual(start, int(12.5 * RATE))
        self.assertEqual(excerpt.shape, (RATE * 20, 2))
        fade = RATE // 2
        np.testing.assert_array_equal(excerpt[fade:-fade], song[start + fade:start + RATE * 20 - fade])
        self.assertLess(abs(int(excerpt[0, 0])), 20)
        self.assertLess(abs(int(excerpt[-1, 1])), 20)
        self.assertTrue((np.diff(excerpt[:fade, 0].astype(int)) >= 0).all())
        late, late_start = enc.sabi_excerpt(song, 55.0, length_samples=RATE * 10)
        self.assertEqual((late_start, len(late)), (RATE * 50, RATE * 10))
        short, short_start = enc.sabi_excerpt(song[:RATE * 5], 3.0)
        self.assertEqual((short_start, len(short)), (0, RATE * 5))
        for args in ((-1.0,), (float("nan"),)):
            with self.assertRaises(enc.AudioEncodeError):
                enc.sabi_excerpt(song, *args)
        with self.assertRaises(enc.AudioEncodeError):
            enc.sabi_excerpt(song, 1.0, length_samples=0)


@unittest.skipUnless(os.environ.get("MODTOOLS_SLOW_TESTS"), "Set MODTOOLS_SLOW_TESTS=1 to time a 4-minute stereo encode")
class SlowEncodeTests(unittest.TestCase):
    def test_four_minute_stereo_encode_time(self):
        rng = np.random.default_rng(4)
        samples = RATE * 240
        t = np.arange(samples) / RATE
        music = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.05 * rng.standard_normal(samples)
        pcm = stereo(music, np.roll(music, 300))
        wall, cpu = time.perf_counter(), time.process_time()
        hca = enc.encode_hca(pcm)
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
        print(f"\n4-minute stereo HCA encode: {wall:.1f} s wall, {cpu:.1f} s CPU, {len(hca)} bytes")
        meta, decoded = decode(hca)
        self.assertEqual(meta["frames"], samples)
        self.assertGreaterEqual(enc.snr_db(pcm, decoded), enc.SNR_FLOOR_DB)


def tearDownModule():
    if ClhcaBuild.directory is not None:
        ClhcaBuild.directory.cleanup()
        ClhcaBuild.directory = ClhcaBuild.library = None


if __name__ == "__main__":
    unittest.main()
