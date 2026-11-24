"""CRI @UTF tables, AFS2 banks and template-based cue sheets for MV-only songs.

``build_cue`` rebuilds a stock music ACB around a new HCA stream: the cue
sheet keeps every table, category, bus and command of the template and only
the fields that identify or describe the new audio change. ``verify_cue``
decodes the result again through the bundled clHCA decoder.

The @UTF writer keeps each column's storage flag (zero, constant or per row)
and lays tables out like the stock ACB writer, so a stock cue sheet read and
written again is byte-identical. Nothing here reads or writes files except
``verify_cue``'s temporary WAV.
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct
import tempfile
import uuid
import wave

import numpy as np

from . import cri_audio_decode
from .cri_hca_encode import (AudioEncodeError, SAMPLE_RATE, SNR_FLOOR_DB, encode_hca, hca_info, sabi_excerpt,
                             snr_db)

__all__ = [
    "AudioEncodeError", "UtfColumn", "UtfTable", "read_utf", "write_utf", "read_afs2", "write_afs2",
    "afs2_header_size", "build_cue", "excerpt_beat", "verify_cue", "template_info", "make_cue", "make_preview",
    "PREFETCH_BLOCKS",
]

ZERO, CONSTANT, PER_ROW = 0x10, 0x30, 0x50
_FORMATS = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i", 6: ">Q", 7: ">q", 8: ">f", 9: ">d"}
_WIDTHS = {**{kind: struct.calcsize(fmt) for kind, fmt in _FORMATS.items()}, 10: 4, 11: 8}
_ROOT_ALIGN = 32
#: Blocks of the stream kept in the ACB's in-memory prefetch bank when the template has none to copy.
PREFETCH_BLOCKS = 5


def _fail(message):
    raise AudioEncodeError(message)


def _zero(kind):
    return "" if kind == 10 else b"" if kind == 11 else 0.0 if kind in (8, 9) else 0


# ---------------------------------------------------------------------------
# @UTF tables
# ---------------------------------------------------------------------------

@dataclass
class UtfColumn:
    name: str
    kind: int
    storage: int
    value: object = None  # the constant for CONSTANT storage


@dataclass
class UtfTable:
    """One CRI @UTF table. ``rows`` hold only the per-row (0x50) columns."""
    name: str
    encoding: int
    columns: list
    rows: list
    align: int = 0

    def column(self, name):
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(name)

    def has(self, name):
        return any(column.name == name for column in self.columns)

    def value(self, row, name):
        column = self.column(name)
        if column.storage == PER_ROW:
            return self.rows[row][name]
        if column.storage == CONSTANT:
            return column.value
        return _zero(column.kind)

    def set_values(self, name, values):
        """Set one value per row, keeping the column's storage flag when possible.

        A zero or constant column stays so when every row gets the same value
        (a constant takes the new value); different values make it per row.
        """
        column = self.column(name)
        values = list(values)
        if len(values) != len(self.rows):
            raise ValueError("one value per row is required")
        for value in values:
            _check_value(column.kind, value)
        if column.storage == PER_ROW:
            for row, value in zip(self.rows, values):
                row[name] = value
            return
        if values and all(value == values[0] for value in values):
            if column.storage == ZERO and values[0] == _zero(column.kind):
                return
            column.storage, column.value = CONSTANT, values[0]
            return
        if not values:
            return
        column.storage, column.value = PER_ROW, None
        for row, value in zip(self.rows, values):
            row[name] = value

    def set(self, row, name, value):
        values = [self.value(index, name) for index in range(len(self.rows))]
        values[row] = value
        self.set_values(name, values)

    def resize(self, count):
        """Change the row count; new rows copy the last row (or zero values)."""
        if count < len(self.rows):
            del self.rows[count:]
        while len(self.rows) < count:
            if self.rows:
                self.rows.append(dict(self.rows[-1]))
            else:
                self.rows.append({c.name: _zero(c.kind) for c in self.columns if c.storage == PER_ROW})


def _check_value(kind, value):
    if kind == 10:
        ok = isinstance(value, str)
    elif kind == 11:
        ok = isinstance(value, (bytes, bytearray))
    elif kind in (8, 9):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    else:
        bits = _WIDTHS[kind] * 8
        signed = kind % 2 == 1
        low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        ok = type(value) is int and low <= value <= high
    if not ok:
        raise ValueError(f"value {value!r} does not fit @UTF column type {kind}")


def _codec(encoding):
    # Same rule as cri_audio_decode.utf_rows.
    return "shift_jis" if encoding == 0 else "utf-8"


def read_utf(raw):
    """Parse a @UTF table, keeping storage flags, constants and layout style."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 32 or bytes(raw[:4]) != b"@UTF":
        _fail("The cue sheet has no CRI UTF table.")
    raw = bytes(raw)
    _, size, encoding, rows_at, strings_at, data_at, name_at, count_columns, row_width, count_rows = struct.unpack_from(
        ">4sIHHIIIHHI", raw)
    end = size + 8
    rows_at += 8
    strings_at += 8
    data_at += 8
    if (end > len(raw) or not 32 <= rows_at <= strings_at <= data_at <= end or not 0 < count_columns <= 1024
            or count_rows > cri_audio_decode.MAX_ROWS or count_rows * row_width > strings_at - rows_at):
        _fail("The cue sheet contains invalid table bounds.")
    codec = _codec(encoding)

    def string(offset):
        position = strings_at + offset
        if not strings_at <= position < data_at:
            _fail("The cue sheet has an invalid string offset.")
        last = raw.find(b"\0", position, data_at)
        if last < 0:
            _fail("The cue sheet has an unterminated string.")
        try:
            return raw[position:last].decode(codec)
        except UnicodeDecodeError:
            _fail("The cue sheet has an undecodable string.")

    blobs = []

    def value(position, kind, limit):
        width = _WIDTHS.get(kind)
        if width is None:
            _fail("The cue sheet has an unsupported column type.")
        if not 0 <= position <= limit - width:
            _fail("The cue sheet has a truncated column.")
        if kind == 10:
            return string(struct.unpack_from(">I", raw, position)[0]), position + width
        if kind == 11:
            start, length = struct.unpack_from(">II", raw, position)
            if length and (data_at + start < data_at or data_at + start + length > end):
                _fail("The cue sheet has an invalid data offset.")
            if length:
                blobs.append((start, length))
            return raw[data_at + start:data_at + start + length], position + width
        return struct.unpack_from(_FORMATS[kind], raw, position)[0], position + width

    columns, position, names = [], 32, set()
    for _ in range(count_columns):
        if position + 5 > rows_at:
            _fail("The cue sheet has a truncated column declaration.")
        flag, offset = struct.unpack_from(">BI", raw, position)
        position += 5
        storage, kind = flag & 0xF0, flag & 0x0F
        name = string(offset)
        if name in names or kind not in _WIDTHS or storage not in (ZERO, CONSTANT, PER_ROW):
            _fail("The cue sheet has an unsupported column declaration.")
        names.add(name)
        constant = None
        if storage == CONSTANT:
            constant, position = value(position, kind, rows_at)
        columns.append(UtfColumn(name, kind, storage, constant))
    if position != rows_at or sum(_WIDTHS[c.kind] for c in columns if c.storage == PER_ROW) != row_width:
        _fail("The cue sheet has an inconsistent row layout.")
    rows = []
    for index in range(count_rows):
        position = rows_at + index * row_width
        row = {}
        for column in columns:
            if column.storage == PER_ROW:
                row[column.name], position = value(position, column.kind, rows_at + (index + 1) * row_width)
        rows.append(row)
    table_name = string(name_at)
    # Stock root tables (the ACB "Header") start data on a 32-byte boundary and
    # space blobs by 32 bytes; nested tables are packed without gaps.
    align = 0
    if blobs and data_at % _ROOT_ALIGN == 0 and all(start % _ROOT_ALIGN == 0 for start, _ in blobs):
        last = max(start + length for start, length in blobs)
        if end == data_at + (last // _ROOT_ALIGN + 1) * _ROOT_ALIGN:
            align = _ROOT_ALIGN
    return UtfTable(table_name, encoding, columns, rows, align)


def write_utf(table):
    """Serialise a ``UtfTable``.

    Strings are stored in the order the stock writer uses (table name, each
    column name followed by its constant, then row values) without sharing.
    Blobs follow in row order; empty blobs are (0, 0). With ``align == 32`` the
    data area starts on a 32-byte boundary and each blob is followed by padding
    to the next boundary past its end, otherwise blobs are packed and the
    table is padded to 4 bytes.
    """
    codec = _codec(table.encoding)
    pool = bytearray()
    data = bytearray()

    def string(text):
        offset = len(pool)
        pool.extend(text.encode(codec) + b"\0")
        return offset

    def blob(raw):
        if not raw:
            return 0, 0
        offset = len(data)
        data.extend(raw)
        if table.align:
            data.extend(b"\0" * ((len(data) // table.align + 1) * table.align - len(data)))
        return offset, len(raw)

    def encode(kind, value):
        _check_value(kind, value)
        if kind == 10:
            return struct.pack(">I", string(value))
        if kind == 11:
            return struct.pack(">II", *blob(bytes(value)))
        return struct.pack(_FORMATS[kind], value)

    name_offset = string(table.name)
    declarations = bytearray()
    seen = set()
    for column in table.columns:
        if column.name in seen or column.kind not in _WIDTHS or column.storage not in (ZERO, CONSTANT, PER_ROW):
            raise ValueError(f"invalid @UTF column {column.name!r}")
        seen.add(column.name)
        declarations += struct.pack(">BI", column.storage | column.kind, string(column.name))
        if column.storage == CONSTANT:
            declarations += encode(column.kind, column.value)
    per_row = [column for column in table.columns if column.storage == PER_ROW]
    rows = bytearray()
    for row in table.rows:
        for column in per_row:
            rows += encode(column.kind, row[column.name])
    rows_at = 32 + len(declarations)
    strings_at = rows_at + len(rows)
    data_at = strings_at + len(pool)
    if table.align:
        padding = (-data_at) % table.align
        pool.extend(b"\0" * padding)
        data_at += padding
        end = data_at + len(data)
    else:
        end = data_at + len(data)
        end += (-end) % 4
    row_width = sum(_WIDTHS[column.kind] for column in per_row)
    if rows_at - 8 > 0xFFFF or row_width > 0xFFFF or len(table.columns) > 0xFFFF:
        raise ValueError("@UTF table is too large")
    header = struct.pack(">4sIHHIIIHHI", b"@UTF", end - 8, table.encoding, rows_at - 8, strings_at - 8,
                         data_at - 8, name_offset, len(table.columns), row_width, len(table.rows))
    out = header + declarations + rows + pool + data
    return out + b"\0" * (end - len(out))


# ---------------------------------------------------------------------------
# AFS2 banks
# ---------------------------------------------------------------------------

def afs2_header_size(count, offset_size=4, id_size=2):
    return 16 + count * id_size + (count + 1) * offset_size


def read_afs2(raw):
    """AFS2 parameters and entries ``[(id, bytes)]`` (bounds as ``cri_audio_decode.awb_entries``)."""
    entries = cri_audio_decode.awb_entries(raw)
    version, offset_size, id_size = raw[4], raw[5], raw[6]
    _, alignment, subkey = struct.unpack_from("<IHH", raw, 8)
    return {"version": version, "offsetSize": offset_size, "idSize": id_size, "alignment": alignment,
            "subkey": subkey, "entries": [(entry["id"], raw[entry["start"]:entry["end"]]) for entry in entries]}


def write_afs2(entries, *, version=2, offset_size=4, id_size=2, alignment=32, subkey=0):
    """Write an AFS2 bank in the stock layout.

    Each offset is the unaligned end of the previous region (the first is the
    header end); entry data starts at the next ``alignment`` boundary and the
    last offset is the file size.
    """
    entries = [(ident, bytes(data)) for ident, data in entries]
    count = len(entries)
    if (not 0 < count <= cri_audio_decode.MAX_ROWS or offset_size not in (2, 4, 8) or id_size not in (2, 4)
            or not 0 < alignment <= 0xFFFF or not 0 <= subkey <= 0xFFFF or not 0 <= version <= 0xFF):
        raise ValueError("invalid AFS2 parameters")
    ids = [ident for ident, _ in entries]
    if len(set(ids)) != count or any(type(ident) is not int or not 0 <= ident < (1 << (8 * id_size)) for ident in ids):
        raise ValueError("invalid or duplicate AFS2 wave ids")
    if any(not data for _, data in entries):
        raise ValueError("AFS2 entries must not be empty")
    header_size = afs2_header_size(count, offset_size, id_size)
    offsets, position = [], header_size
    body = bytearray()
    for _, data in entries:
        offsets.append(position)
        start = (position + alignment - 1) // alignment * alignment
        body += b"\0" * (start - position) + data
        position = start + len(data)
    offsets.append(position)
    if position >= 1 << (8 * offset_size):
        raise ValueError("AFS2 bank too large for its offset size")
    out = bytearray(b"AFS2" + bytes([version, offset_size, id_size, 0]))
    out += struct.pack("<IHH", count, alignment, subkey)
    for ident in ids:
        out += ident.to_bytes(id_size, "little")
    for offset in offsets:
        out += offset.to_bytes(offset_size, "little")
    return bytes(out + body)


# ---------------------------------------------------------------------------
# Cue sheets
# ---------------------------------------------------------------------------

# Stock BeatSyncInfoTable schema, used only when a template has an empty beat table.
_BEAT_COLUMNS = (("Bpm", 8), ("NumBeats", 5), ("BeatDenominator", 5), ("SyncBeatFlags", 4), ("BaseRate", 4),
                 ("StartSample", 4), ("EndSample", 4))


def _nested(root, name):
    raw = root.value(0, name)
    if not isinstance(raw, bytes) or not raw:
        return None
    return read_utf(raw)


def _beat_rows(beat, sample_count, rate):
    """BeatSyncInfoTable rows: contiguous inclusive regions ending at ``sample_count``."""
    if not isinstance(beat, dict):
        _fail("BPM and the first beat are required for the cue's beat table.")
    beats = beat.get("numBeats", 4)
    denominator = beat.get("beatDenominator", 4)
    if type(beats) is not int or not 1 <= beats <= 32 or denominator not in (1, 2, 4, 8, 16, 32):
        _fail("The beat table needs a supported time signature.")
    if "segments" in beat:
        segments = [(item.get("bpm"), item.get("startSample")) for item in beat["segments"]]
    else:
        first = beat.get("firstBeat")
        if not isinstance(first, (int, float)) or isinstance(first, bool) or not math.isfinite(first) or first < 0:
            _fail("The first beat must be a time inside the song.")
        segments = [(beat.get("bpm"), int(round(first * rate)))]
    if not 0 < len(segments) <= cri_audio_decode.MAX_BEAT_SYNC_REGIONS:
        _fail("The beat table needs at least one tempo.")
    rows = []
    for index, (bpm, start) in enumerate(segments):
        if (not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or not math.isfinite(bpm)
                or not 0 < bpm <= 1000):
            _fail("The BPM must be a number between 0 and 1000.")
        end = segments[index + 1][1] - 1 if index + 1 < len(segments) else sample_count
        if type(start) is not int or not 0 <= start < end or (index and start != rows[-1]["EndSample"] + 1):
            _fail("The beats must start inside the song, in order.")
        rows.append({"Bpm": float(bpm), "NumBeats": beats, "BeatDenominator": denominator,
                     "SyncBeatFlags": 0xFFFFFFFF, "BaseRate": rate, "StartSample": start, "EndSample": end})
    if len(rows) > 1 and beats < 2:
        _fail("The beat table needs a supported time signature.")
    return rows


def excerpt_beat(beat, start_sample, length, rate=44100):
    """Beat description for the excerpt ``[start_sample, start_sample + length)`` of a song.

    The first beat moves to the first song beat at or after the excerpt start;
    tempo segments outside the excerpt are dropped. Returns the input form
    (``firstBeat`` or ``segments``) for ``build_cue``.
    """
    if beat is None:
        return None
    if type(start_sample) is not int or type(length) is not int or start_sample < 0 or length <= 0:
        _fail("The preview excerpt must lie inside the song.")
    tempos = [item.get("bpm") for item in beat.get("segments", [beat])]
    if not tempos or any(not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or not math.isfinite(bpm)
                         or not 0 < bpm <= 1000 for bpm in tempos):
        _fail("The BPM must be a number between 0 and 1000.")
    if "segments" in beat:
        segments = sorted(beat["segments"], key=lambda item: item["startSample"])
        kept = [item for item in segments if item["startSample"] >= start_sample]
        before = [item for item in segments if item["startSample"] < start_sample]
        if before:
            current = before[-1]
            period = rate * 60.0 / current["bpm"]
            steps = math.ceil((start_sample - current["startSample"]) / period - 1e-9)
            begin = int(round(current["startSample"] + steps * period))
            if not kept or begin < kept[0]["startSample"]:
                kept.insert(0, {"bpm": current["bpm"], "startSample": begin})
        shifted = [{"bpm": item["bpm"], "startSample": item["startSample"] - start_sample} for item in kept
                   if item["startSample"] - start_sample < length]
        if not shifted:
            shifted = [{"bpm": (before or segments)[-1]["bpm"], "startSample": 0}]
        return {**{k: v for k, v in beat.items() if k != "segments"}, "segments": shifted}
    period = 60.0 / beat["bpm"]
    first = beat["firstBeat"] - start_sample / rate
    if first < 0:
        first += math.ceil(-first / period - 1e-9) * period
    if round(first * rate) >= length:
        first = 0.0
    return {**beat, "firstBeat": max(first, 0.0)}


def build_cue(template_acb, template_awb, hca, *, sheet, beat, guid=None):
    """Build ``(acb, awb)`` for ``hca`` from a stock single-cue music cue sheet.

    The template's tables, categories, buses and commands are kept. Changed:
    the sheet and cue names (``sheet``), ``AcbGuid`` (``guid`` or random),
    ``StreamAwbHash`` (name and MD5 of the AWB), ``StreamAwbAfs2Header`` (the
    AWB header), the in-memory ``AwbFile`` (HCA header plus the first blocks,
    as many as the template prefetches), ``WaveformTable`` sample count, rate
    and channels, ``CueTable.Length`` (ms) and ``BeatSyncInfoTable``.

    ``beat`` is ``{"bpm": float, "firstBeat": seconds}`` or ``{"segments":
    [{"bpm": float, "startSample": int}, ...]}`` (optional ``numBeats`` and
    ``beatDenominator``, default 4/4); the last region ends at the sample count.
    The AWB uses the template bank's AFS2 version, offset size, alignment and
    subkey; ``hca`` must be keyed for that subkey. ``awb`` is ``None`` for an
    in-memory (Streaming 0) template.
    """
    if not isinstance(sheet, str) or not sheet or len(sheet) > 255 or "\0" in sheet:
        _fail("The cue sheet name is invalid.")
    try:
        return _build_cue(template_acb, template_awb, hca, sheet, beat, guid)
    except AudioEncodeError:
        raise
    except cri_audio_decode.AudioDecodeError as error:
        raise AudioEncodeError(f"The template cue sheet cannot be read: {error}") from error
    except (KeyError, IndexError, ValueError) as error:
        raise AudioEncodeError("The template cue sheet does not have the stock music layout.") from error


def _build_cue(template_acb, template_awb, hca, sheet, beat, guid):
    info = hca_info(hca)
    if info["frameCount"] * info["frameSize"] + info["headerSize"] != len(hca):
        _fail("The HCA stream length does not match its header.")
    sample_count, rate, channels = info["sampleCount"], info["sampleRate"], info["channels"]
    if sample_count <= 0:
        _fail("The HCA stream has no samples.")
    catalog = cri_audio_decode.inspect_cues(template_acb)
    root = read_utf(template_acb)
    if len(root.rows) != 1 or len(catalog["cues"]) != 1 or len(catalog["cues"][0]["waveforms"]) != 1:
        _fail("The template cue sheet must hold exactly one cue with one waveform.")
    waveforms, cues, names = (_nested(root, name) for name in ("WaveformTable", "CueTable", "CueNameTable"))
    if not waveforms or not cues or not names or len(waveforms.rows) != 1 or len(cues.rows) != 1 or len(names.rows) != 1:
        _fail("The template cue sheet must hold exactly one cue with one waveform.")
    if waveforms.value(0, "EncodeType") != 2:
        _fail("The template cue is not HCA audio.")
    streaming = waveforms.value(0, "Streaming") if waveforms.has("Streaming") else 0
    if streaming not in (0, 1, 2):
        _fail("The template cue uses an unsupported streaming mode.")

    def wave_id(kind):
        for name in (kind, "Id"):
            if waveforms.has(name):
                return waveforms.value(0, name)
        _fail("The template waveform has no bank id.")

    memory_bank = root.value(0, "AwbFile") if root.has("AwbFile") else b""
    memory = read_afs2(memory_bank) if memory_bank else None
    awb = None
    if streaming:
        stream_params = {"version": 2, "offsetSize": 4, "idSize": 2, "alignment": 32, "subkey": 0}
        if template_awb is not None:
            stream_params = read_afs2(template_awb)
        awb = write_afs2([(wave_id("StreamAwbId"), hca)], version=stream_params["version"],
                         offset_size=stream_params["offsetSize"], id_size=stream_params["idSize"],
                         alignment=stream_params["alignment"], subkey=stream_params["subkey"])
    if streaming == 1:
        if memory_bank:
            _fail("The template stream-only cue has an unexpected memory bank.")
        new_memory = b""
    else:
        memory_params = memory or {"version": 2, "offsetSize": 4, "idSize": 2, "alignment": 32,
                                   "subkey": stream_params["subkey"] if streaming else 0}
        if streaming == 2:
            blocks = PREFETCH_BLOCKS
            if memory and len(memory["entries"]) == 1:
                prefetch = memory["entries"][0][1]
                try:
                    old = hca_info(prefetch)
                    blocks = (len(prefetch) - old["headerSize"]) // old["frameSize"]
                except AudioEncodeError:
                    blocks = PREFETCH_BLOCKS
            blocks = max(1, min(blocks, info["frameCount"]))
            payload = hca[:info["headerSize"] + blocks * info["frameSize"]]
        else:
            payload = hca
        if streaming and memory_params["subkey"] != stream_params["subkey"]:
            _fail("The template's memory and stream banks use different keys.")
        new_memory = write_afs2([(wave_id("MemoryAwbId"), payload)], version=memory_params["version"],
                                offset_size=memory_params["offsetSize"], id_size=memory_params["idSize"],
                                alignment=memory_params["alignment"], subkey=memory_params["subkey"])

    waveforms.set(0, "NumSamples", sample_count)
    for name, value in (("SamplingRate", rate), ("NumChannels", channels)):
        if waveforms.has(name):
            waveforms.set(0, name, value)
    if cues.has("Length"):
        cues.set(0, "Length", sample_count * 1000 // rate)
    names.set(0, "CueName", sheet)
    root.set(0, "WaveformTable", write_utf(waveforms))
    root.set(0, "CueTable", write_utf(cues))
    root.set(0, "CueNameTable", write_utf(names))
    if root.has("Name"):
        root.set(0, "Name", sheet)
    if root.has("CueSheetName"):
        root.set(0, "CueSheetName", sheet)
    if root.has("AcbGuid"):
        guid = uuid.uuid4().bytes if guid is None else bytes(guid)
        if len(guid) != 16:
            _fail("The cue sheet GUID must be 16 bytes.")
        root.set(0, "AcbGuid", guid)
    if root.has("AwbFile"):
        root.set(0, "AwbFile", new_memory)
    elif streaming != 1:
        _fail("The template cue sheet has no memory bank column.")

    hashes = _nested(root, "StreamAwbHash") if root.has("StreamAwbHash") else None
    headers = _nested(root, "StreamAwbAfs2Header") if root.has("StreamAwbAfs2Header") else None
    if streaming:
        if hashes is None or len(hashes.rows) != 1:
            _fail("The template cue sheet has no stream bank hash.")
        hashes.set(0, "Name", sheet)
        hashes.set(0, "Hash", hashlib.md5(awb).digest())
        root.set(0, "StreamAwbHash", write_utf(hashes))
        if headers is not None:
            if len(headers.rows) != 1:
                _fail("The template cue sheet has an unsupported stream bank header table.")
            size = afs2_header_size(1, awb[5], awb[6])
            headers.set(0, "Header", awb[:size + (-size) % 4])
            root.set(0, "StreamAwbAfs2Header", write_utf(headers))

    beats = _nested(root, "BeatSyncInfoTable") if root.has("BeatSyncInfoTable") else None
    if beats is not None and not beats.rows and beat is None:
        beats = None  # an empty beat table stays as it is
    if beats is None and beat is not None:
        if not root.has("BeatSyncInfoTable"):
            _fail("The template cue sheet has no beat table.")
        beats = UtfTable("BeatSyncInfo", root.encoding, [UtfColumn(name, kind, PER_ROW) for name, kind in _BEAT_COLUMNS], [])
    if beats is not None:
        rows = _beat_rows(beat, sample_count, rate)
        beats.resize(len(rows))
        for column in beats.columns:
            if column.name in rows[0]:
                beats.set_values(column.name, [row[column.name] for row in rows])
        root.set(0, "BeatSyncInfoTable", write_utf(beats))

    acb = write_utf(root)
    result = cri_audio_decode.inspect_cues(acb)
    if result["sheet"] != sheet or [cue["name"] for cue in result["cues"]] != [sheet]:
        _fail("The rebuilt cue sheet does not name its cue.")  # pragma: no cover
    return acb, awb


# ---------------------------------------------------------------------------
# Decode-back verification
# ---------------------------------------------------------------------------

def verify_cue(acb, awb, pcm, *, cue=None, snr_floor=SNR_FLOOR_DB, scratch_dir=None):
    """Decode ``cue`` with the bundled clHCA decoder and compare it with ``pcm``.

    ``pcm`` is the int16 ``(samples, channels)`` input of the encode. The
    decoded audio must have exactly the same length and channels and an SNR
    of at least ``snr_floor`` dB. Returns ``{"frames", "snrDb", "decoder"}``.
    """
    pcm = np.asarray(pcm)
    if pcm.dtype != np.int16 or pcm.ndim != 2:
        _fail("The reference PCM must be int16 with shape (samples, channels).")
    if cri_audio_decode._native_library() is None:
        _fail("The app's HCA decoder is missing, so the new audio cannot be checked.")
    with tempfile.TemporaryDirectory(dir=scratch_dir) as directory:
        path = Path(directory) / "verify.wav"
        try:
            meta = cri_audio_decode.decode_cue(acb, awb, cue, path)
        except cri_audio_decode.AudioDecodeError as error:
            raise AudioEncodeError(f"The new audio does not decode: {error}") from error
        if meta.get("decoder") != "clhca":
            _fail("The new audio was not decoded by the app's HCA decoder.")
        with wave.open(str(path), "rb") as stream:
            channels = stream.getnchannels()
            decoded = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").reshape(-1, channels)
    if decoded.shape != pcm.shape:
        _fail(f"The new audio decodes to {decoded.shape[0]} samples instead of {pcm.shape[0]}.")
    snr = snr_db(pcm, decoded)
    if snr < snr_floor:
        _fail(f"The new audio decodes with {snr:.1f} dB SNR, below the {snr_floor:.1f} dB floor.")
    return {"frames": int(decoded.shape[0]), "snrDb": snr, "decoder": "clhca"}


# ---------------------------------------------------------------------------
# One-call helpers for registration
# ---------------------------------------------------------------------------

def template_info(template_acb, template_awb=None):
    """Facts about a template cue sheet that a caller needs before encoding.

    ``{"sheet", "sampleCount", "sampleRate", "streaming", "subkey", "hasBeats"}``:
    ``sampleCount`` is the template waveform's length (a stock ``_SABI``
    template gives the stock preview length) and ``subkey`` is the AFS2 key
    modifier of the bank that holds the stream.
    """
    try:
        root = read_utf(template_acb)
        waveforms = _nested(root, "WaveformTable")
        if root.rows == [] or waveforms is None or len(waveforms.rows) != 1:
            _fail("The template cue sheet must hold exactly one cue with one waveform.")
        streaming = waveforms.value(0, "Streaming") if waveforms.has("Streaming") else 0
        if streaming and template_awb is not None:
            subkey = read_afs2(template_awb)["subkey"]
        elif root.has("AwbFile") and root.value(0, "AwbFile"):
            subkey = read_afs2(root.value(0, "AwbFile"))["subkey"]
        else:
            subkey = 0
        beats = _nested(root, "BeatSyncInfoTable") if root.has("BeatSyncInfoTable") else None
        return {"sheet": root.value(0, "Name") if root.has("Name") else "",
                "sampleCount": waveforms.value(0, "NumSamples"),
                "sampleRate": waveforms.value(0, "SamplingRate") if waveforms.has("SamplingRate") else SAMPLE_RATE,
                "streaming": streaming, "subkey": subkey, "hasBeats": bool(beats and beats.rows)}
    except cri_audio_decode.AudioDecodeError as error:
        raise AudioEncodeError(f"The template cue sheet cannot be read: {error}") from error
    except (KeyError, IndexError, ValueError) as error:
        if isinstance(error, AudioEncodeError):
            raise
        raise AudioEncodeError("The template cue sheet does not have the stock music layout.") from error


def make_cue(pcm, template_acb, template_awb, *, sheet, beat, guid=None, progress=None, verify=True,
             scratch_dir=None):
    """Encode ``pcm`` and wrap it as cue ``sheet``: ``encode_hca`` + ``build_cue`` + ``verify_cue``.

    The stream is keyed for the template bank's subkey. Returns ``{"acb",
    "awb", "sampleCount", "snrDb"}`` (``snrDb`` is ``None`` without ``verify``).
    """
    info = template_info(template_acb, template_awb)
    hca = encode_hca(pcm, subkey=info["subkey"], progress=progress)
    acb, awb = build_cue(template_acb, template_awb, hca, sheet=sheet, beat=beat, guid=guid)
    snr = None
    if verify:
        snr = verify_cue(acb, awb, pcm, cue=sheet, scratch_dir=scratch_dir)["snrDb"]
    return {"acb": acb, "awb": awb, "sampleCount": int(len(pcm)), "snrDb": snr}


def make_preview(pcm, template_acb, template_awb, *, sheet, start_seconds, beat, length_samples=None, guid=None,
                 verify=True, scratch_dir=None):
    """Build the ``_SABI`` preview cue from the song PCM.

    The excerpt starts at ``start_seconds`` (moved back to fit), lasts
    ``length_samples`` (default 20 s; pass ``template_info(stock_sabi)["sampleCount"]``
    to match a cached stock preview) and fades 0.5 s at both ends. ``beat``
    describes the whole song; it is shifted into the excerpt and used only
    when the template has a beat table. Returns ``make_cue``'s result plus
    ``startSample``.
    """
    info = template_info(template_acb, template_awb)
    excerpt, start = sabi_excerpt(pcm, start_seconds, length_samples=length_samples)
    preview_beat = excerpt_beat(beat, start, len(excerpt)) if info["hasBeats"] else None
    result = make_cue(excerpt, template_acb, template_awb, sheet=sheet, beat=preview_beat, guid=guid, verify=verify,
                      scratch_dir=scratch_dir)
    return {**result, "startSample": start}
