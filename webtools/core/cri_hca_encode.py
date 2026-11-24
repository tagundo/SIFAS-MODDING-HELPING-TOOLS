"""CRI HCA encoder for MV Studio song registration (Python + numpy).

This is a port of the HCA encoder in VGAudio by Alex Barney (MIT licence),
https://github.com/Thealexbarney/VGAudio at commit
9d8f6ea04c83cccccb3dd7851a631bbd53a8dbbe. The licence text and the pinned
commit are kept in ``resources/cri_hca_encoder/``. Each ported function names
the upstream file it comes from; paths are relative to ``src/`` upstream.

Scope: the encoder writes exactly the stock SIFAS music parameter set (HCA
v2.0, 44 100 Hz stereo, 512-byte frames, bands 128/64/64, no HFR, encoder
delay 128, cipher type 56 with the game key). Frames are vectorised over many
frames at once with numpy; the arithmetic per value follows the upstream
encoder. Every encode is meant to be checked by decoding it again with the
bundled clHCA decoder (``core.cri_acb_write.verify_cue``).

The module also holds the strict 16-bit PCM WAV reader and the preview
(``_SABI``) excerpt builder used by registration.
"""
import math
import numbers
import struct

import numpy as np

from . import cri_audio_decode

UPSTREAM = "https://github.com/Thealexbarney/VGAudio"
UPSTREAM_COMMIT = "9d8f6ea04c83cccccb3dd7851a631bbd53a8dbbe"

# src/VGAudio/Codecs/CriHca/CriHcaConstants.cs
SUBFRAMES_PER_FRAME = 8
SUBFRAME_SAMPLES_BITS = 7
SAMPLES_PER_SUBFRAME = 1 << SUBFRAME_SAMPLES_BITS
SAMPLES_PER_FRAME = SUBFRAMES_PER_FRAME * SAMPLES_PER_SUBFRAME

SAMPLE_RATE = 44100
CHANNELS = 2
#: Stock music bitrate: frame size 512 bytes at 44.1 kHz (VGAudio CriHcaQuality.Middle for stereo).
BITRATE = 176400
#: CriHcaEncoder.Initialize: InsertedSamples = SamplesPerSubFrame (the MDCT delay).
ENCODER_DELAY = SAMPLES_PER_SUBFRAME
HCA_VERSION = 0x0200
CIPHER_TYPE = 56
SIFAS_HCA_KEY = cri_audio_decode.SIFAS_HCA_KEY
#: Upper bound for one encode: 20 minutes of stereo audio.
MAX_SAMPLES = SAMPLE_RATE * 60 * 20

_FRAMES_PER_CHUNK = 512


class AudioEncodeError(ValueError):
    """Raised for audio that cannot be encoded or verified.

    ``str(error)`` is always one fixed English sentence, so the UI can look it
    up as an exact key in its translation tables. Numbers and the text of a
    nested error are kept apart in ``details`` (a dict, possibly empty).
    """

    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def _fail(message, **details):
    raise AudioEncodeError(message, **details)


def _finite(value):
    """True for a finite real number; ``bool`` is not a number here."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int too large for a float
        return False


def _integer(value, low, high):
    return isinstance(value, numbers.Integral) and not isinstance(value, bool) and low <= value <= high


def _array(pcm, message):
    """``np.asarray(pcm)``, refusing ragged or non-numeric input with ``message``."""
    try:
        return np.asarray(pcm)
    except (TypeError, ValueError, OverflowError):
        _fail(message)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

# src/VGAudio/Codecs/CriHca/CriHcaTables.cs (generated tables)
def _dequantizer_scaling_function(x):
    return math.sqrt(128) * math.pow(math.pow(2, 53.0 / 128), x - 63)


def _resolution_max_value_function(x):
    if x < 8:
        return x
    return (1 << (x - 4)) - 1


def _quantizer_inverse_step_size_function(x):
    return _resolution_max_value_function(x) + 0.5


def _intensity_ratio_bounds_function(x):
    return (27 - x * 2) / 14.0


DEQUANTIZER_SCALING_TABLE = np.array([_dequantizer_scaling_function(i) for i in range(64)], dtype=np.float64)
QUANTIZER_SCALING_TABLE = np.array([1 / _dequantizer_scaling_function(i) for i in range(64)], dtype=np.float64)
QUANTIZER_INVERSE_STEP_SIZE = np.array([_quantizer_inverse_step_size_function(i) for i in range(16)], dtype=np.float64)
RESOLUTION_MAX_VALUES = np.array([_resolution_max_value_function(i) for i in range(16)], dtype=np.int64)
INTENSITY_RATIO_BOUNDS_TABLE = np.array([_intensity_ratio_bounds_function(i) for i in range(14)], dtype=np.float64)

# The packed tables of CriHcaTables.cs, as listed unpacked upstream in
# src/VGAudio.Tests/Formats/CriHca/UnpackedTables.cs (whose tests assert they
# equal the packed tables).
DEFAULT_CHANNEL_MAPPING = (0, 1, 0, 4, 0, 1, 3, 7, 3)
VALID_CHANNEL_MAPPINGS = (
    (0, 1, 0, 0, 0, 0, 0, 0),
    (1, 0, 0, 0, 0, 0, 0, 0),
    (0, 1, 1, 0, 1, 0, 0, 0),
    (1, 0, 0, 1, 0, 1, 0, 0),
    (0, 1, 1, 0, 0, 0, 0, 1),
    (0, 0, 0, 1, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0, 0, 1),
    (0, 0, 0, 1, 0, 0, 0, 0),
)
QUANTIZED_SPECTRUM_MAX_BITS = np.array([0, 2, 3, 3, 4, 4, 4, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=np.int64)
QUANTIZE_SPECTRUM_BITS = np.array([
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 2, 1, 2, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 3, 2, 2, 2, 3, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 3, 3, 3, 2, 3, 3, 3, 0, 0, 0, 0],
    [0, 0, 0, 0, 4, 3, 3, 3, 3, 3, 3, 3, 4, 0, 0, 0],
    [0, 0, 0, 4, 4, 4, 3, 3, 3, 3, 3, 4, 4, 4, 0, 0],
    [0, 0, 4, 4, 4, 4, 4, 3, 3, 3, 4, 4, 4, 4, 4, 0],
    [0, 4, 4, 4, 4, 4, 4, 4, 3, 4, 4, 4, 4, 4, 4, 4],
], dtype=np.int64)
QUANTIZE_SPECTRUM_VALUE = np.array([
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 3, 0, 2, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 7, 2, 0, 1, 6, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 7, 5, 3, 0, 2, 4, 6, 0, 0, 0, 0],
    [0, 0, 0, 0, 15, 6, 4, 2, 0, 1, 3, 5, 14, 0, 0, 0],
    [0, 0, 0, 15, 13, 11, 4, 2, 0, 1, 3, 10, 12, 14, 0, 0],
    [0, 0, 15, 13, 11, 9, 7, 2, 0, 1, 6, 8, 10, 12, 14, 0],
    [0, 15, 13, 11, 9, 7, 5, 3, 0, 2, 4, 6, 8, 10, 12, 14],
], dtype=np.int64)
SCALE_TO_RESOLUTION_CURVE = np.array([
    15, 14, 14, 14, 14, 14, 14, 13, 13, 13, 13, 13, 13, 12, 12, 12,
    12, 12, 12, 11, 11, 11, 11, 11, 11, 10, 10, 10, 10, 10, 10, 10,
    9, 9, 9, 9, 9, 9, 8, 8, 8, 8, 8, 8, 7, 6, 6, 5,
    4, 4, 4, 3, 3, 3, 2, 2, 2, 2, 1,
], dtype=np.int64)
# The window literals are C# float literals stored in a double[] upstream, so
# each value is the float32 value widened to float64.
MDCT_WINDOW = np.array([
    6.90533780e-4, 1.97623484e-3, 3.67386453e-3, 5.72424009e-3, 8.09670333e-3, 1.07731819e-2, 1.37425177e-2, 1.69978570e-2,
    2.05352642e-2, 2.43529025e-2, 2.84505188e-2, 3.28290947e-2, 3.74906212e-2, 4.24378961e-2, 4.76744287e-2, 5.32043017e-2,
    5.90321124e-2, 6.51628822e-2, 7.16020092e-2, 7.83552229e-2, 8.54284912e-2, 9.28280205e-2, 1.00560151e-1, 1.08631350e-1,
    1.17048122e-1, 1.25816986e-1, 1.34944350e-1, 1.44436508e-1, 1.54299513e-1, 1.64539129e-1, 1.75160721e-1, 1.86169162e-1,
    1.97568730e-1, 2.09362969e-1, 2.21554622e-1, 2.34145418e-1, 2.47135997e-1, 2.60525763e-1, 2.74312705e-1, 2.88493186e-1,
    3.03061932e-1, 3.18011731e-1, 3.33333343e-1, 3.49015296e-1, 3.65043819e-1, 3.81402701e-1, 3.98073107e-1, 4.15033519e-1,
    4.32259798e-1, 4.49725032e-1, 4.67399567e-1, 4.85251158e-1, 5.03244936e-1, 5.21343827e-1, 5.39508522e-1, 5.57697773e-1,
    5.75868905e-1, 5.93978047e-1, 6.11980557e-1, 6.29831433e-1, 6.47486031e-1, 6.64900243e-1, 6.82031155e-1, 6.98837578e-1,
    7.15280414e-1, 7.31323123e-1, 7.46932149e-1, 7.62077332e-1, 7.76731849e-1, 7.90872812e-1, 8.04481268e-1, 8.17542017e-1,
    8.30044091e-1, 8.41980159e-1, 8.53346705e-1, 8.64143789e-1, 8.74374807e-1, 8.84046197e-1, 8.93167078e-1, 9.01749134e-1,
    9.09806132e-1, 9.17353690e-1, 9.24408972e-1, 9.30990338e-1, 9.37117040e-1, 9.42809045e-1, 9.48086798e-1, 9.52970862e-1,
    9.57481921e-1, 9.61640537e-1, 9.65466917e-1, 9.68980789e-1, 9.72201586e-1, 9.75147963e-1, 9.77837980e-1, 9.80289042e-1,
    9.82517719e-1, 9.84539866e-1, 9.86370564e-1, 9.88024116e-1, 9.89514053e-1, 9.90853190e-1, 9.92053449e-1, 9.93126273e-1,
    9.94082093e-1, 9.94930983e-1, 9.95682180e-1, 9.96344328e-1, 9.96925533e-1, 9.97433305e-1, 9.97874618e-1, 9.98256087e-1,
    9.98583674e-1, 9.98862922e-1, 9.99099135e-1, 9.99296963e-1, 9.99460995e-1, 9.99595225e-1, 9.99703407e-1, 9.99789119e-1,
    9.99855518e-1, 9.99905586e-1, 9.99941945e-1, 9.99967217e-1, 9.99983609e-1, 9.99993265e-1, 9.99998033e-1, 9.99999762e-1,
], dtype=np.float32).astype(np.float64)


# src/VGAudio/Utilities/Crc16.cs (GenerateTable, polynomial 0x8005 as used by
# CriHcaEncoder and HcaWriter)
def _crc16_table(polynomial=0x8005):
    table = []
    for i in range(256):
        value = i << 8
        for _ in range(8):
            value = ((value << 1) ^ polynomial) if value & 0x8000 else value << 1
            value &= 0xFFFF
        table.append(value)
    return np.array(table, dtype=np.uint32)


CRC16_TABLE = _crc16_table()


# src/VGAudio/Utilities/Crc16.cs (Compute)
def crc16(data):
    crc = 0
    table = CRC16_TABLE
    for byte in bytes(data):
        crc = ((crc << 8) & 0xFFFF) ^ int(table[(crc >> 8) ^ byte])
    return crc


def _crc16_rows(rows):
    """Crc16.Compute for every row of a 2-D uint8 array at once."""
    crc = np.zeros(rows.shape[0], dtype=np.uint32)
    table = CRC16_TABLE
    for column in range(rows.shape[1]):
        crc = ((crc << 8) & 0xFFFF) ^ table[(crc >> 8) ^ rows[:, column]]
    return crc


# ---------------------------------------------------------------------------
# Encryption (cipher type 56)
# ---------------------------------------------------------------------------

# src/VGAudio/Codecs/CriHca/CriHcaKey.cs (CreateRandomRow)
def _random_row(seed):
    row = []
    xor = seed >> 4
    mult = ((seed & 1) << 3) | 5
    inc = (seed & 0xE) | 1
    for _ in range(16):
        xor = (xor * mult + inc) % 16
        row.append(xor)
    return row


# src/VGAudio/Codecs/CriHca/CriHcaKey.cs (ShuffleTable)
def _shuffle_table(table_in):
    table = [0] * 256
    x = 0
    out_pos = 1
    for _ in range(256):
        x = (x + 17) & 0xFF
        if table_in[x] != 0 and table_in[x] != 0xFF:
            table[out_pos] = table_in[x]
            out_pos += 1
    table[0xFF] = 0xFF
    return table


# src/VGAudio/Codecs/CriHca/CriHcaKey.cs (CreateDecryptionTable, CreateTable)
def decryption_table(key_code):
    """Type-56 decryption substitution table for a 64-bit key code."""
    if not 0 < key_code < (1 << 64):
        _fail("The HCA key must be a nonzero 64-bit value.")
    kc = list((key_code - 1).to_bytes(8, "little"))
    seed = [
        kc[1], kc[6] ^ kc[1], kc[2] ^ kc[3], kc[2],
        kc[1] ^ kc[2], kc[3] ^ kc[4], kc[3], kc[2] ^ kc[3],
        kc[4] ^ kc[5], kc[4], kc[3] ^ kc[4], kc[5] ^ kc[6],
        kc[5], kc[4] ^ kc[5], kc[6] ^ kc[1], kc[6],
    ]
    row = _random_row(kc[0])
    table = [0] * 256
    for r in range(16):
        column = _random_row(seed[r])
        for c in range(16):
            table[16 * r + c] = ((row[r] << 4) | (column[c] & 0xF)) & 0xFF
    return bytes(_shuffle_table(table))


# src/VGAudio/Codecs/CriHca/CriHcaKey.cs (InvertTable)
def invert_table(table_in):
    table = bytearray(len(table_in))
    for index, value in enumerate(table_in):
        table[value] = index
    return bytes(table)


def encryption_table(key_code):
    return invert_table(decryption_table(key_code))


def awb_key(key_code, subkey):
    """Key used for a stream stored in an AFS2 bank with ``subkey``.

    Same rule as ``cri_audio_decode._decode_native`` (vgmstream ``hca_keys``).
    """
    if subkey:
        key_code = (key_code * ((subkey << 16) | ((~subkey + 2) & 0xFFFF))) & ((1 << 64) - 1)
    return key_code


# ---------------------------------------------------------------------------
# Parameters and header
# ---------------------------------------------------------------------------

# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateBandCounts)
def band_counts(channels, sample_rate, bitrate, cutoff_frequency=None):
    """Frame size and band split VGAudio derives from a bitrate."""
    if cutoff_frequency is None:
        cutoff_frequency = sample_rate // 2
    frame_size = bitrate * 1024 // sample_rate // 8
    num_groups = 0
    pcm_bitrate = sample_rate * channels * 16
    if channels <= 1 or pcm_bitrate // bitrate <= 6:
        hfr_ratio, cutoff_ratio = 6, 12
    else:
        hfr_ratio, cutoff_ratio = 8, 16
    if bitrate < pcm_bitrate // cutoff_ratio:
        cutoff_frequency = min(cutoff_frequency, cutoff_ratio * bitrate // (32 * channels))
    total_band_count = _round_half_even(cutoff_frequency * 256.0 / sample_rate)
    hfr_start_band = int(min(total_band_count, _round_half_even((hfr_ratio * bitrate * 128.0) / pcm_bitrate)))
    stereo_start_band = hfr_start_band if hfr_ratio == 6 else (hfr_start_band + 1) // 2
    hfr_band_count = total_band_count - hfr_start_band
    bands_per_group = -(-hfr_band_count // 8)
    if bands_per_group > 0:
        num_groups = -(-hfr_band_count // bands_per_group)
    return {
        "frameSize": frame_size,
        "totalBandCount": total_band_count,
        "baseBandCount": stereo_start_band,
        "stereoBandCount": hfr_start_band - stereo_start_band,
        "hfrGroupCount": num_groups,
        "bandsPerHfrGroup": bands_per_group,
    }


def _round_half_even(value):
    # C# Math.Round(double) rounds half to even, like Python's round().
    return int(round(value))


def _stock_parameters():
    params = band_counts(CHANNELS, SAMPLE_RATE, BITRATE)
    # src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (SetChannelConfiguration)
    channel_config = DEFAULT_CHANNEL_MAPPING[CHANNELS]
    if VALID_CHANNEL_MAPPINGS[CHANNELS - 1][channel_config] != 1:
        raise AssertionError("invalid channel mapping")
    params.update(channels=CHANNELS, sampleRate=SAMPLE_RATE, minResolution=1, maxResolution=15,
                  trackCount=1, channelConfig=channel_config)
    return params


STOCK_PARAMETERS = _stock_parameters()
FRAME_SIZE = STOCK_PARAMETERS["frameSize"]
TOTAL_BAND_COUNT = STOCK_PARAMETERS["totalBandCount"]
BASE_BAND_COUNT = STOCK_PARAMETERS["baseBandCount"]
STEREO_BAND_COUNT = STOCK_PARAMETERS["stereoBandCount"]
if (FRAME_SIZE, TOTAL_BAND_COUNT, BASE_BAND_COUNT, STEREO_BAND_COUNT, STOCK_PARAMETERS["hfrGroupCount"]) != (512, 128, 64, 64, 0):
    raise AssertionError("stock HCA parameters changed")  # pragma: no cover
# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateHeaderSize): 96 rounded to 32, no comment, no loop.
HEADER_SIZE = 96


def frame_layout(sample_count):
    """Frame count and padding for ``sample_count`` input samples (no loop).

    src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (Initialize).
    """
    total = sample_count + ENCODER_DELAY
    frame_count = -(-total // SAMPLES_PER_FRAME)
    return frame_count, frame_count * SAMPLES_PER_FRAME - ENCODER_DELAY - sample_count


# src/VGAudio/Containers/Hca/HcaWriter.cs (WriteHeader and the chunk writers)
def hca_header(sample_count, *, encrypted=True):
    frame_count, appended = frame_layout(sample_count)
    params = STOCK_PARAMETERS

    def chunk(name):
        raw = name.encode("ascii")
        return bytes(value | 0x80 if value and encrypted else value for value in raw)

    out = bytearray()
    out += chunk("HCA\0") + struct.pack(">hh", HCA_VERSION, HEADER_SIZE)
    out += chunk("fmt\0") + bytes([params["channels"], params["sampleRate"] >> 16 & 0xFF])
    out += struct.pack(">H", params["sampleRate"] & 0xFFFF)
    out += struct.pack(">IHH", frame_count, ENCODER_DELAY, appended)
    out += chunk("comp") + struct.pack(">h", params["frameSize"])
    out += bytes([params["minResolution"], params["maxResolution"], params["trackCount"], params["channelConfig"],
                  params["totalBandCount"], params["baseBandCount"], params["stereoBandCount"],
                  params["bandsPerHfrGroup"]])
    out += struct.pack(">h", 0)
    out += chunk("ciph") + struct.pack(">h", CIPHER_TYPE if encrypted else 0)
    out += chunk("pad")
    out = out.ljust(HEADER_SIZE - 2, b"\0")
    out += struct.pack(">H", crc16(out))
    return bytes(out)


def hca_info(hca):
    """Parse the fixed-order v2.0 HCA header fields this encoder writes or reads back."""
    if not isinstance(hca, (bytes, bytearray)) or len(hca) < 8:
        _fail("The HCA stream has no complete header.")
    mask = lambda raw: bytes(value & 0x7F for value in raw)
    if mask(hca[:4]) != b"HCA\0":
        _fail("The HCA stream has no HCA header.")
    version, header_size = struct.unpack_from(">HH", hca, 4)
    if not 8 <= header_size <= len(hca) or crc16(hca[:header_size]) != 0:
        _fail("The HCA header is truncated or fails its checksum.")
    info = {"version": version, "headerSize": header_size, "cipherType": 0}
    sizes = {b"fmt\0": 16, b"comp": 16, b"ciph": 6, b"loop": 16, b"rva\0": 8}
    position = 8
    while position + 4 <= header_size - 2:
        name = mask(hca[position:position + 4])
        if name[:3] != b"pad" and name not in sizes:
            _fail("The HCA header has an unsupported chunk.")
        if name[:3] != b"pad" and position + sizes[name] > header_size - 2:
            _fail("The HCA header is truncated or fails its checksum.")
        if name == b"fmt\0":
            channels = hca[position + 4]
            rate = int.from_bytes(hca[position + 5:position + 8], "big")
            frames, delay, padding = struct.unpack_from(">IHH", hca, position + 8)
            info.update(channels=channels, sampleRate=rate, frameCount=frames, encoderDelay=delay,
                        encoderPadding=padding)
            position += 16
        elif name == b"comp":
            frame_size, = struct.unpack_from(">H", hca, position + 4)
            values = hca[position + 6:position + 14]
            info.update(frameSize=frame_size, minResolution=values[0], maxResolution=values[1],
                        trackCount=values[2], channelConfig=values[3], totalBandCount=values[4],
                        baseBandCount=values[5], stereoBandCount=values[6], bandsPerHfrGroup=values[7])
            position += 16
        elif name == b"ciph":
            info["cipherType"], = struct.unpack_from(">H", hca, position + 4)
            position += 6
        elif name == b"loop":
            info["loop"] = struct.unpack_from(">IIHH", hca, position + 4)
            position += 16
        elif name == b"rva\0":
            info["volume"], = struct.unpack_from(">f", hca, position + 4)
            position += 8
        else:
            break  # "pad": the rest of the header is padding before the CRC
    if "frameCount" not in info or "frameSize" not in info:
        _fail("The HCA header has no format or compression chunk.")
    if not info["channels"] or not info["sampleRate"] or not info["frameSize"]:
        _fail("The HCA header has no channels, sample rate or frame size.")
    info["sampleCount"] = info["frameCount"] * SAMPLES_PER_FRAME - info["encoderDelay"] - info["encoderPadding"]
    info["dataSize"] = info["frameCount"] * info["frameSize"]
    return info


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

# src/VGAudio/Utilities/Mdct.cs (Dct4Slow: the reference type-4 DCT that the
# fast Dct4 implements; a matrix product is the fast form in numpy).
def _dct4_matrix(size=SAMPLES_PER_SUBFRAME, scale=math.sqrt(2.0 / SAMPLES_PER_SUBFRAME)):
    k = np.arange(size, dtype=np.float64)
    return np.cos(math.pi / size * (k[:, None] + 0.5) * (k[None, :] + 0.5)) * scale


# CriHcaChannel.cs: new Mdct(SubFrameSamplesBits, CriHcaTables.MdctWindow, Math.Sqrt(2.0 / SamplesPerSubFrame))
_DCT4 = _dct4_matrix()
_HALF = np.arange(SAMPLES_PER_SUBFRAME // 2)


# src/VGAudio/Utilities/Mdct.cs (RunMdct), for many subframes at once.
# ``current`` and ``previous`` have shape (..., 128): previous is the block the
# upstream encoder keeps in ``_mdctPrevious``.
def mdct(current, previous):
    size, half, window = SAMPLES_PER_SUBFRAME, SAMPLES_PER_SUBFRAME // 2, MDCT_WINDOW
    i = _HALF
    a = window[half - i - 1] * -current[..., half + i]
    b = window[half + i] * current[..., half - i - 1]
    c = window[i] * previous[..., i]
    d = window[size - i - 1] * previous[..., size - i - 1]
    dct_in = np.concatenate((a - b, c - d), axis=-1)
    return dct_in @ _DCT4.T


# ``mdct`` is linear in (previous, current), so its windowing and DCT fold
# into one 256x128 matrix; applying it equals ``mdct`` up to float rounding.
_IDENTITY = np.eye(2 * SAMPLES_PER_SUBFRAME)
_MDCT_MATRIX = mdct(_IDENTITY[:, SAMPLES_PER_SUBFRAME:], _IDENTITY[:, :SAMPLES_PER_SUBFRAME])
_MDCT_PREVIOUS = np.ascontiguousarray(_MDCT_MATRIX[:SAMPLES_PER_SUBFRAME])
_MDCT_CURRENT = np.ascontiguousarray(_MDCT_MATRIX[SAMPLES_PER_SUBFRAME:])
del _IDENTITY


def _mdct_blocks(blocks):
    """MDCT of consecutive 128-sample blocks; ``blocks[:, 0]`` is the initial previous block."""
    return blocks[:, :-1] @ _MDCT_PREVIOUS + blocks[:, 1:] @ _MDCT_CURRENT


# ---------------------------------------------------------------------------
# Frame analysis (all functions work on a chunk of F frames)
# Shapes: spectra (C, F, 8, 128); scale factors (C, F, 128).
# ---------------------------------------------------------------------------

# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (EncodeIntensityStereo)
def _encode_intensity_stereo(spectra):
    base, total = BASE_BAND_COUNT, TOTAL_BAND_COUNT
    left = spectra[0, :, :, base:total]
    right = spectra[1, :, :, base:total]
    energy_l = np.abs(left).sum(axis=-1)
    energy_r = np.abs(right).sum(axis=-1)
    energy_total = np.abs(left + right).sum(axis=-1) * 2
    energy_lr = energy_r + energy_l
    silent = ~((energy_r > 0) | (energy_l > 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        stored = 2 * energy_l / energy_lr
        ratio = energy_lr / energy_total
    ratio = np.clip(ratio, 0.5, math.sqrt(2) / 2)
    bounds = INTENSITY_RATIO_BOUNDS_TABLE[1:13]
    quantized = 1 + (bounds[None, None, :] >= stored[..., None]).sum(axis=-1)
    quantized = np.where(silent, 0, quantized)
    ratio = np.where(silent, 1.0, ratio)
    spectra[0, :, :, base:total] = (left + right) * ratio[..., None]
    spectra[1, :, :, base:total] = 0
    return quantized.astype(np.int64)


def _coded_counts():
    # src/VGAudio/Codecs/CriHca/CriHcaFrame.cs (channel types for 2 channels per track)
    return (BASE_BAND_COUNT + STEREO_BAND_COUNT, BASE_BAND_COUNT)


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateScaleFactors, FindScaleFactor)
def _scale_factors(spectra):
    peak = np.abs(spectra).max(axis=2)
    factors = np.minimum(np.searchsorted(DEQUANTIZER_SCALING_TABLE, peak, side="right"), 63).astype(np.int64)
    for channel, count in enumerate(_coded_counts()):
        factors[channel, :, count:] = 0
    return factors


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (ScaleSpectra)
def _scale_spectra(spectra, factors):
    scale = QUANTIZER_SCALING_TABLE[factors][:, :, None, :]
    scaled = np.clip(spectra * scale, -0.999999999999, 0.999999999999)
    return np.where(factors[:, :, None, :] == 0, 0.0, scaled)


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateOptimalDeltaLength)
def _delta_lengths(factors, count):
    """Scale-factor header bits and delta width per frame for one channel."""
    coded = factors[:, :count]
    empty = ~(coded != 0).any(axis=1)
    delta = np.abs(np.diff(coded, axis=1))
    best_length = np.full(coded.shape[0], 3 + 6 * count, dtype=np.int64)
    best_bits = np.full(coded.shape[0], 6, dtype=np.int64)
    for delta_bits in range(1, 6):
        max_delta = (1 << (delta_bits - 1)) - 1
        length = 3 + 6 + delta_bits * (count - 1) + 6 * (delta > max_delta).sum(axis=1)
        better = length < best_length
        best_length = np.where(better, length, best_length)
        best_bits = np.where(better, delta_bits, best_bits)
    best_length = np.where(empty, 3, best_length)
    best_bits = np.where(empty, 0, best_bits)
    return best_length, best_bits


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateFrameHeaderLength)
def _header_lengths(factors):
    lengths, delta_bits = [], []
    for channel, count in enumerate(_coded_counts()):
        length, bits = _delta_lengths(factors[channel], count)
        if channel == 1:  # ChannelType.StereoSecondary: 8 intensity values of 4 bits
            length = length + 32
        lengths.append(length)
        delta_bits.append(bits)
    return np.stack(lengths), np.stack(delta_bits)


# src/VGAudio/Codecs/CriHca/CriHcaPacking.cs (CalculateResolution)
def calculate_resolution(scale_factor, noise_level):
    position = np.clip(noise_level - (5 * scale_factor) // 2 + 2, 0, 58)
    return np.where(scale_factor == 0, 0, SCALE_TO_RESOLUTION_CURVE[position])


# calculate_resolution for every scale factor (0..63) and noise level (-1..255),
# the only levels the searches use: level - 1 for bands under the boundary.
_RESOLUTION_TABLE = calculate_resolution(np.arange(64)[:, None], np.arange(-1, 256)[None, :]).astype(np.int64)


def _resolutions(factors, noise):
    return _RESOLUTION_TABLE[factors, noise + 1]


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (QuantizeSpectra)
def _quantize(scaled, resolution):
    step_inverse = QUANTIZER_INVERSE_STEP_SIZE[resolution]
    shift_up = step_inverse + 1
    shift_down = (step_inverse + 0.5).astype(np.int64)
    # The argument is always > 1, so truncation equals the upstream (int) cast.
    return (scaled * step_inverse + shift_up).astype(np.int64) - shift_down


def _bit_costs(scaled):
    """Bits each band needs over its 8 subframes, for every resolution 0..15.

    This tabulates CriHcaEncoder.CalculateUsedBits per band. Deviation from
    upstream: resolutions 8..15 test the exact quantized value instead of the
    dead-zone shortcut (an upstream speed hack), so the counted bits always
    equal the packed bits. The float steps are the ones ``_quantize`` takes:
    ``t = scaled * inverse + (inverse + 1)`` and ``q = floor(t) - shift``.
    """
    channels, frames = scaled.shape[:2]
    costs = np.zeros((channels, frames, SAMPLES_PER_SUBFRAME, 16), dtype=np.int32)
    for resolution in range(1, 16):
        inverse = QUANTIZER_INVERSE_STEP_SIZE[resolution]
        t = scaled * inverse
        t += inverse + 1
        shift = int(inverse + 0.5)
        if resolution < 8:
            index = t.astype(np.int32)
            index += 8 - shift
            bits = QUANTIZE_SPECTRUM_BITS[resolution].astype(np.int8)[index]
            costs[..., resolution] = bits.sum(axis=2, dtype=np.int32)
        else:
            zero = (t >= shift) & (t < shift + 1)
            costs[..., resolution] = SUBFRAMES_PER_FRAME * int(QUANTIZED_SPECTRUM_MAX_BITS[resolution]) - zero.sum(axis=2, dtype=np.int32)
    return costs


def _used_bits(costs, factors, headers, level, boundary):
    """CriHcaEncoder.CalculateUsedBits for each frame's level and boundary."""
    band = np.arange(SAMPLES_PER_SUBFRAME)
    noise = level[:, None] - (band[None, :] < boundary[:, None])
    total = 16 + 16 + 16 + headers.sum(axis=0)
    frames = factors.shape[1]
    slots = np.arange(frames * SAMPLES_PER_SUBFRAME, dtype=np.int64) * 16
    for channel in range(costs.shape[0]):
        resolution = _resolutions(factors[channel], noise)
        picked = np.ascontiguousarray(costs[channel]).reshape(-1)[slots + resolution.reshape(-1)]
        total = total + picked.reshape(frames, SAMPLES_PER_SUBFRAME).sum(axis=1)
    return total


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (BinarySearchLevel)
def _search_level(costs, factors, headers, available):
    frames = factors.shape[1]
    low = np.zeros(frames, dtype=np.int64)
    high = np.full(frames, 255, dtype=np.int64)
    mid_value = np.zeros(frames, dtype=np.int64)
    zero = np.zeros(frames, dtype=np.int64)
    active = low != high
    while active.any():
        mid = (low + high) // 2
        value = _used_bits(costs, factors, headers, mid, zero)
        over = value > available
        low = np.where(active & over, mid + 1, low)
        high = np.where(active & ~over, mid, high)
        mid_value = np.where(active, value, mid_value)
        active = low != high
    return np.where((low == 255) & (mid_value > available), -1, low)


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (BinarySearchBoundary, CalculateEvaluationBoundary)
def _search_boundary(costs, factors, headers, level, available):
    frames = factors.shape[1]
    low = np.zeros(frames, dtype=np.int64)
    high = np.full(frames, 127, dtype=np.int64)
    active = np.abs(high - low) > 1
    while active.any():
        mid = (low + high) // 2
        value = _used_bits(costs, factors, headers, level, mid)
        over = available < value
        high = np.where(active & over, mid - 1, high)
        low = np.where(active & ~over, mid, low)
        active = np.abs(high - low) > 1
    high_value = _used_bits(costs, factors, headers, level, high)
    result = np.where(low == high, np.where(low < 127, low, -1), np.where(high_value > available, low, high))
    if ((result < 0) & (level > 0)).any():  # upstream throws NotImplementedException here
        _fail("The HCA encoder could not fit a frame.")
    return np.where(level == 0, 0, result)


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateNoiseLevel): the band
# removal loop for frames that do not fit even at the highest noise level.
def _remove_bands(costs, factors, available, frame):
    one = factors[:, frame:frame + 1].copy()
    cost = costs[:, frame:frame + 1]
    highest = BASE_BAND_COUNT + STEREO_BAND_COUNT - 1
    level = np.array([-1])
    while level[0] < 0:
        highest -= 2
        if highest < 0:
            _fail("The HCA bitrate is too low for this audio.")
        one[:, :, highest + 1] = 0
        one[:, :, highest + 2] = 0
        headers, _ = _header_lengths(one)
        level = _search_level(cost, one, headers, available)
    return one[:, 0], int(level[0])


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------

def _spectrum_code_tables():
    """(code, bits) written by CriHcaPacking.WriteSpectra for each resolution and value.

    Index ``(resolution << 12) + quantized + 2048``. For resolutions 8..15 the
    magnitude and the sign bit that follows it are one field.
    """
    codes = np.zeros(16 << 12, dtype=np.int64)
    widths = np.zeros(16 << 12, dtype=np.int64)
    for resolution in range(1, 16):
        limit = int(RESOLUTION_MAX_VALUES[resolution])
        values = np.arange(-limit, limit + 1)
        at = (resolution << 12) + values + 2048
        if resolution < 8:
            codes[at] = QUANTIZE_SPECTRUM_VALUE[resolution][values + 8]
            widths[at] = QUANTIZE_SPECTRUM_BITS[resolution][values + 8]
        else:
            codes[at] = (np.abs(values) << 1) | (values < 0)
            widths[at] = QUANTIZED_SPECTRUM_MAX_BITS[resolution] - 1 + (values != 0)
    return codes, widths


_SPECTRUM_CODES, _SPECTRUM_WIDTHS = _spectrum_code_tables()


# src/VGAudio/Codecs/CriHca/CriHcaPacking.cs (PackFrame, WriteScaleFactors,
# WriteSpectra) with src/VGAudio/Utilities/BitWriter.cs semantics (MSB first).
# Every field is a (value, bit count) slot; a slot with 0 bits writes nothing,
# so all frames share one slot layout and are packed together. Two upstream
# writes that always follow each other are merged into one slot: an escaped
# scale factor (escape code, then the 6-bit value) and a large coefficient
# (magnitude, then the sign bit).
def _pack_frames(level, boundary, factors, delta_bits, intensity, resolution, quantized):
    """Packed frames without checksum bytes, and the bits each frame used."""
    frames = level.shape[0]
    band = np.arange(SAMPLES_PER_SUBFRAME)
    values = [np.full((frames, 1), 0xFFFF, dtype=np.int64), level[:, None], boundary[:, None]]
    widths = [np.full((frames, 1), 16, dtype=np.int64), np.full((frames, 1), 9, dtype=np.int64),
              np.full((frames, 1), 7, dtype=np.int64)]
    for channel, count in enumerate(_coded_counts()):
        bits = delta_bits[channel]
        scales = factors[channel]
        coded = band < count
        value = scales.copy()
        width = np.where((bits == 6)[:, None] & coded[None, :], 6, 0)
        delta_mode = (bits > 0) & (bits < 6)
        width[:, 0] = np.where(delta_mode, 6, width[:, 0])
        max_delta = (1 << np.maximum(bits - 1, 0)) - 1
        escape = (1 << bits) - 1
        delta = scales[:, 1:] - scales[:, :-1]
        later = delta_mode[:, None] & coded[None, 1:]
        escaped = np.abs(delta) > max_delta[:, None]
        value[:, 1:] = np.where(later, np.where(escaped, (escape[:, None] << 6) | scales[:, 1:],
                                                max_delta[:, None] + delta), value[:, 1:])
        width[:, 1:] = np.where(later, bits[:, None] + np.where(escaped, 6, 0), width[:, 1:])
        values += [bits[:, None], value]
        widths += [np.full((frames, 1), 3, dtype=np.int64), width]
        if channel == 1:  # ChannelType.StereoSecondary: intensity per subframe
            values.append(intensity)
            widths.append(np.full((frames, SUBFRAMES_PER_FRAME), 4, dtype=np.int64))
    # Spectra: subframe-major, then channel, then band (order (F, 8, C, 128)).
    order = (1, 2, 0, 3)
    index = np.add(resolution[:, :, None, :].transpose(order) << 12, quantized.transpose(order) + 2048, order="C")
    values.append(_SPECTRUM_CODES[index].reshape(frames, -1))
    widths.append(_SPECTRUM_WIDTHS[index].reshape(frames, -1))
    values = np.concatenate(values, axis=1)
    widths = np.concatenate(widths, axis=1)
    ends = np.cumsum(widths, axis=1)
    frame_bits = FRAME_SIZE * 8
    if (ends[:, -1] > frame_bits - 16).any():
        _fail("The HCA encoder overflowed a frame.")
    starts = ((ends - widths) + (np.arange(frames, dtype=np.int64) * frame_bits)[:, None]).reshape(-1)
    widths, values = widths.reshape(-1), values.reshape(-1)
    # Each field (at most 16 bits) lies inside a 24-bit window starting at its
    # first byte. Fields never share a bit, so summing bytes equals OR-ing
    # them; a slot with no bits always holds the value 0 and adds nothing.
    window = values << (24 - widths - (starts & 7))
    byte = starts >> 3
    size = frames * FRAME_SIZE + 2
    out = np.bincount(byte, weights=window >> 16, minlength=size)
    out += np.bincount(byte + 1, weights=(window >> 8) & 0xFF, minlength=size)
    out += np.bincount(byte + 2, weights=window & 0xFF, minlength=size)
    return out[:frames * FRAME_SIZE].astype(np.uint8).reshape(frames, FRAME_SIZE), ends[:, -1]


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def _as_pcm(pcm):
    array = _array(pcm, "The encoder needs 16-bit stereo PCM samples.")
    if array.dtype != np.int16 or array.ndim != 2 or array.shape[1] != CHANNELS:
        _fail("The encoder needs 16-bit stereo PCM samples.")
    if not 0 < array.shape[0] <= MAX_SAMPLES:
        _fail("The audio is empty or longer than the encoder limit.")
    return array


def _float_range(pcm, start, stop):
    """PCM samples [start, stop) as float channels, zero outside the input.

    src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (PcmToFloat); the zero tail is
    EncodePostAudio's 128 post samples plus the cleared final frame.
    """
    out = np.zeros((CHANNELS, stop - start), dtype=np.float64)
    lo, hi = max(start, 0), min(stop, pcm.shape[0])
    if lo < hi:
        out[:, lo - start:hi - start] = pcm[lo:hi].T * (1.0 / 32768.0)
    return out


# src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (EncodeFrame: PcmToFloat, RunMdct,
# EncodeIntensityStereo, CalculateScaleFactors, ScaleSpectra, CalculateFrameHeaderLength,
# CalculateNoiseLevel, CalculateEvaluationBoundary, CalculateFrameResolutions,
# QuantizeSpectra, PackFrame), run on ``frame_count`` frames at once. The HFR
# steps are left out: the stock parameters have no HFR bands.
def _encode_chunk(pcm, first_frame, frame_count):
    start = first_frame * SAMPLES_PER_FRAME
    stop = start + frame_count * SAMPLES_PER_FRAME
    samples = _float_range(pcm, start - SAMPLES_PER_SUBFRAME, stop)
    blocks = samples.reshape(CHANNELS, -1, SAMPLES_PER_SUBFRAME)
    spectra = _mdct_blocks(blocks).reshape(CHANNELS, frame_count, SUBFRAMES_PER_FRAME, SAMPLES_PER_SUBFRAME)
    intensity = _encode_intensity_stereo(spectra)
    factors = _scale_factors(spectra)
    scaled = _scale_spectra(spectra, factors)
    headers, delta_bits = _header_lengths(factors)
    costs = _bit_costs(scaled)
    available = FRAME_SIZE * 8
    level = _search_level(costs, factors, headers, available)
    for frame in np.flatnonzero(level < 0):
        factors[:, frame], level[frame] = _remove_bands(costs, factors, available, frame)
    headers, delta_bits = _header_lengths(factors)
    boundary = _search_boundary(costs, factors, headers, level, available)
    # src/VGAudio/Codecs/CriHca/CriHcaEncoder.cs (CalculateFrameResolutions)
    band = np.arange(SAMPLES_PER_SUBFRAME)
    noise = level[:, None] - (band[None, :] < boundary[:, None])
    resolution = np.stack([_resolutions(factors[channel], noise) for channel in range(CHANNELS)])
    quantized = _quantize(scaled, resolution[:, :, None, :])
    quantized = np.where(resolution[:, :, None, :] == 0, 0, quantized)
    packed, _ = _pack_frames(level, boundary, factors, delta_bits, intensity, resolution, quantized)
    return packed


def encode_hca(pcm, *, key=SIFAS_HCA_KEY, subkey=0, encrypt=True, progress=None):
    """Encode 16-bit stereo 44.1 kHz PCM (shape ``(samples, 2)``) to HCA bytes.

    The result is a complete HCA v2.0 stream with the stock SIFAS music
    parameters. With ``encrypt`` (the default) frames use cipher type 56 with
    ``key`` and the AFS2 ``subkey`` of the bank that will hold the stream.
    ``progress(done_frames, total_frames)`` is called after each chunk; an
    exception raised by it cancels the encode.
    """
    pcm = _as_pcm(pcm)
    if not _integer(key, 0, (1 << 64) - 1) or not _integer(subkey, 0, 0xFFFF):
        _fail("The HCA key or bank subkey is invalid.")
    if progress is not None and not callable(progress):
        _fail("The encode progress callback is not callable.")
    sample_count = pcm.shape[0]
    frame_count, _ = frame_layout(sample_count)
    table = None
    if encrypt:
        table = np.frombuffer(encryption_table(awb_key(int(key), int(subkey))), dtype=np.uint8)
    out = bytearray(hca_header(sample_count, encrypted=encrypt))
    for first in range(0, frame_count, _FRAMES_PER_CHUNK):
        count = min(_FRAMES_PER_CHUNK, frame_count - first)
        frames = _encode_chunk(pcm, first, count)
        body = frames[:, :FRAME_SIZE - 2]
        if table is not None:
            # src/VGAudio/Codecs/CriHca/CriHcaEncryption.cs (CryptFrame)
            body = table[body]
        crc = _crc16_rows(body)
        frames = np.concatenate((body, (crc >> 8).astype(np.uint8)[:, None], (crc & 0xFF).astype(np.uint8)[:, None]), axis=1)
        out += frames.tobytes()
        if progress is not None:
            progress(first + count, frame_count)
    return bytes(out)


def decrypt_frame(frame, key=SIFAS_HCA_KEY, subkey=0):
    """Decrypt one keyed frame (all bytes but the CRC) for inspection and tests."""
    table = decryption_table(awb_key(key, subkey))
    return bytes(frame[:-2]).translate(table) + bytes(frame[-2:])


# ---------------------------------------------------------------------------
# Decode-back quality
# ---------------------------------------------------------------------------

#: Lowest whole-song SNR (dB) a decode-back check accepts. Measured with this
#: encoder and the bundled clHCA decoder: two stock songs decoded and encoded
#: again with the stock parameters reach 28.6 and 30.2 dB (1 s segments: at
#: least 18.2 dB); pink noise, a music-like spectrum, reaches 14.0 dB with
#: independent channels and 17.7 dB in mono. Broken output stays below the
#: floor: swapped channels 3.7 dB, a one-sample shift 6.0 dB, half gain 6.0 dB,
#: and a wrong key fails in the decoder. Full-band white noise with
#: independent channels (4.8 dB, intensity stereo above 11 kHz) is refused.
SNR_FLOOR_DB = 8.0


def snr_db(reference, decoded):
    """Signal-to-noise ratio of ``decoded`` against ``reference`` over all samples.

    Returns ``inf`` for an exact match (including digital silence) and
    ``-inf`` when the reference is silent but the decoded audio is not.
    """
    reference = _array(reference, "The decoded audio does not have the input's length and channels.")
    decoded = _array(decoded, "The decoded audio does not have the input's length and channels.")
    if reference.dtype.kind not in "biuf" or decoded.dtype.kind not in "biuf":
        _fail("The decoded audio does not have the input's length and channels.")
    reference, decoded = reference.astype(np.float64), decoded.astype(np.float64)
    if reference.shape != decoded.shape:
        _fail("The decoded audio does not have the input's length and channels.")
    error = float(((reference - decoded) ** 2).sum())
    signal = float((reference ** 2).sum())
    if error == 0:
        return math.inf
    if signal == 0:
        return -math.inf
    return 10 * math.log10(signal / error)


# ---------------------------------------------------------------------------
# PCM input
# ---------------------------------------------------------------------------

WAV_MAX_BYTES = 96 * 1024 * 1024
_PCM_SUBFORMAT = bytes.fromhex("0100000000001000800000aa00389b71")


def read_wav(data, *, sample_rate=SAMPLE_RATE, channels=CHANNELS, max_bytes=WAV_MAX_BYTES):
    """Strict RIFF/WAVE reader for 16-bit integer PCM.

    Returns an int16 array of shape ``(frames, channels)``. The RIFF size must
    match the data exactly, ``fmt `` must come once before the only ``data``
    chunk, and the format must be plain PCM (or WAVE_FORMAT_EXTENSIBLE PCM)
    at ``sample_rate`` with ``channels`` channels. Other chunks are skipped.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        _fail("The WAV data must be bytes.")
    data = bytes(data)
    if not 12 <= len(data) <= max_bytes:
        _fail("The WAV file is empty or larger than the upload limit.")
    magic, size, form = struct.unpack_from("<4sI4s", data)
    if magic != b"RIFF" or form != b"WAVE" or size + 8 != len(data):
        _fail("The file is not a complete RIFF/WAVE file.")
    position, fmt, pcm = 12, None, None
    while position < len(data):
        if position + 8 > len(data):
            _fail("The WAV file has a truncated chunk.")
        name, length = struct.unpack_from("<4sI", data, position)
        body = position + 8
        end = body + length
        if end > len(data):
            _fail("The WAV file has a truncated chunk.")
        if name == b"fmt ":
            if fmt is not None or pcm is not None:
                _fail("The WAV file has a misplaced format chunk.")
            fmt = data[body:end]
        elif name == b"data":
            if fmt is None or pcm is not None:
                _fail("The WAV file has a misplaced data chunk.")
            pcm = data[body:end]
        position = end + (length & 1)
        if position > len(data):
            _fail("The WAV file has a truncated chunk.")
    if fmt is None or pcm is None:
        _fail("The WAV file has no format or data chunk.")
    if len(fmt) not in (16, 18, 40):
        _fail("The WAV format chunk has an unsupported size.")
    tag, count, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", fmt)
    if tag == 0xFFFE:
        if len(fmt) != 40:
            _fail("The WAV format chunk has an unsupported size.")
        extra, valid_bits, _mask = struct.unpack_from("<HHI", fmt, 16)
        if extra != 22 or valid_bits != 16 or fmt[24:40] != _PCM_SUBFORMAT:
            _fail("The WAV file is not 16-bit integer PCM.")
    elif tag != 1:
        _fail("The WAV file is not 16-bit integer PCM.")
    if bits != 16:
        _fail("The WAV file is not 16-bit integer PCM.")
    if count != channels or rate != sample_rate:
        found = {"sampleRate": rate, "channels": count, "expectedSampleRate": sample_rate, "expectedChannels": channels}
        if (sample_rate, channels) == (SAMPLE_RATE, CHANNELS):
            _fail("The WAV file must be 44100 Hz stereo.", **found)
        _fail("The WAV file has the wrong sample rate or channel count.", **found)
    if align != channels * 2 or byte_rate != sample_rate * align:
        _fail("The WAV format chunk is inconsistent.")
    if not pcm or len(pcm) % align:
        _fail("The WAV data is empty or ends inside a sample.")
    return np.frombuffer(pcm, dtype="<i2").astype(np.int16).reshape(-1, channels)


def write_wav(pcm, *, sample_rate=SAMPLE_RATE):
    """Plain 16-bit PCM WAV bytes for an int16 ``(frames, channels)`` array."""
    array = _array(pcm, "The PCM samples must be int16 with shape (frames, channels).")
    if array.dtype != np.int16 or array.ndim != 2 or not 1 <= array.shape[1] <= 8:
        _fail("The PCM samples must be int16 with shape (frames, channels).")
    body = array.astype("<i2").tobytes()
    channels = array.shape[1]
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(body), b"WAVE", b"fmt ", 16, 1, channels,
                         sample_rate, sample_rate * channels * 2, channels * 2, 16, b"data", len(body))
    return header + body + (b"\0" if len(body) & 1 else b"")


# ---------------------------------------------------------------------------
# Preview excerpt
# ---------------------------------------------------------------------------

SABI_SECONDS = 20.0
SABI_FADE_SECONDS = 0.5


def sabi_excerpt(pcm, start_seconds, *, length_samples=None, fade_seconds=SABI_FADE_SECONDS,
                 sample_rate=SAMPLE_RATE):
    """Preview excerpt for ``music_<id>_SABI``: a window with linear fades.

    ``length_samples`` defaults to 20 s; pass the length of a stock SABI cue
    when one is available. The window starts at ``start_seconds`` and is moved
    back so it ends inside the song; a song shorter than the window is used
    whole. Returns ``(excerpt, start_sample)``. Samples inside the window are
    copied unchanged except within ``fade_seconds`` of either end.
    """
    pcm = _array(pcm, "The PCM samples must be int16 with shape (frames, channels).")
    if pcm.dtype != np.int16 or pcm.ndim != 2 or pcm.shape[0] == 0:
        _fail("The PCM samples must be int16 with shape (frames, channels).")
    if not _finite(start_seconds) or start_seconds < 0:
        _fail("The preview start must be a time inside the song.")
    if not _finite(fade_seconds) or fade_seconds < 0:
        _fail("The preview fade must be zero or more seconds.")
    if length_samples is None:
        length_samples = int(round(SABI_SECONDS * sample_rate))
    if type(length_samples) is not int or length_samples <= 0:
        _fail("The preview length must be a positive sample count.")
    length = min(length_samples, pcm.shape[0])
    # Clamp before rounding: a start far past the end (even one whose sample
    # position overflows a float) moves back to the last window.
    start = int(round(min(start_seconds * sample_rate, pcm.shape[0] - length)))
    excerpt = pcm[start:start + length].astype(np.float64)
    fade = int(round(min(fade_seconds * sample_rate, length // 2)))
    if fade > 0:
        ramp = (np.arange(fade, dtype=np.float64) + 0.5) / fade
        excerpt[:fade] *= ramp[:, None]
        excerpt[length - fade:] *= ramp[::-1, None]
    return np.clip(np.rint(excerpt), -32768, 32767).astype(np.int16), start
