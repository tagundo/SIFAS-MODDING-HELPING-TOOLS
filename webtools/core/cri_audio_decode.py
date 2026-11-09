"""Bounded local CRI cue selection, AFS2 extraction and HCA/ADX decoding.

ACB references are followed by exact cue name/ID; an AWB file's entry ordinal
is never assumed to equal its cue ID. The bundled ISC decoder keeps Android
and macOS independent of an installed FFmpeg executable.
"""
import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import wave

MAX_ACB_BYTES = 32 * 1024 * 1024
MAX_AWB_BYTES = 128 * 1024 * 1024
MAX_PCM_BYTES = 256 * 1024 * 1024
MAX_ROWS = 65536
SIFAS_HCA_KEY = 6498535309877346413
_RESOURCE = Path(__file__).parent / "resources" / "cri_hca"


class AudioDecodeError(ValueError):
    pass


def _fail(message):
    raise AudioDecodeError(message)


def _bytes(value, limit):
    if not isinstance(value, bytes) or not 0 < len(value) <= limit:
        _fail("The local audio asset is empty or exceeds the decoder limit.")
    return value


def utf_rows(raw):
    """Read one CRI @UTF table; all offsets are confined to that table."""
    _bytes(raw, MAX_ACB_BYTES)
    if len(raw) < 32 or raw[:4] != b"@UTF":
        _fail("The audio cue sheet has no supported CRI UTF table.")
    _, size, encoding, rows_at, strings_at, data_at, name_at, columns, row_width, count = struct.unpack_from(
        ">4sIHHIIIHHI", raw)
    end = size + 8
    rows_at += 8; strings_at += 8; data_at += 8
    if end > len(raw) or not 32 <= rows_at <= strings_at <= data_at <= end or not 0 < columns <= 512 or count > MAX_ROWS or count * row_width > strings_at - rows_at:
        _fail("The audio cue sheet contains invalid table bounds.")
    codec = "shift_jis" if encoding == 0 else "utf-8"
    def string(offset):
        position = strings_at + offset
        if not strings_at <= position < data_at:
            _fail("The audio cue sheet has an invalid string offset.")
        last = raw.find(b"\0", position, min(data_at, position + 4097))
        if last < 0:
            _fail("The audio cue sheet has an unterminated string.")
        return raw[position:last].decode(codec, errors="replace")
    formats = {0: (">B", 1), 1: (">b", 1), 2: (">H", 2), 3: (">h", 2), 4: (">I", 4),
               5: (">i", 4), 6: (">Q", 8), 7: (">q", 8), 8: (">f", 4), 9: (">d", 8), 10: (">I", 4), 11: (">II", 8)}
    def read_value(position, kind, limit):
        if kind not in formats:
            _fail("The audio cue sheet has an unsupported column type.")
        fmt, width = formats[kind]
        if not 0 <= position <= limit - width:
            _fail("The audio cue sheet has a truncated column.")
        values = struct.unpack_from(fmt, raw, position)
        if kind == 10:
            value = string(values[0])
        elif kind == 11:
            start, length = values
            start += data_at
            if start < data_at or length > end - start:
                _fail("The audio cue sheet has an invalid data offset.")
            value = raw[start:start + length]
        else:
            value = values[0]
        return value, position + width
    descriptors, position, names = [], 32, set()
    for _ in range(columns):
        if position + 5 > rows_at:
            _fail("The audio cue sheet has a truncated column declaration.")
        flag, offset = struct.unpack_from(">BI", raw, position); position += 5
        storage, kind = flag & 0xf0, flag & 15
        name = string(offset)
        if name in names or kind not in formats or storage not in (0x10, 0x30, 0x50):
            _fail("The audio cue sheet has an ambiguous column declaration.")
        names.add(name)
        constant = b"" if kind == 11 else "" if kind == 10 else 0
        if storage == 0x30:
            constant, position = read_value(position, kind, rows_at)
        descriptors.append((name, kind, storage, constant))
    rows = []
    for index in range(count):
        start = rows_at + index * row_width
        position = start
        row = {}
        for name, kind, storage, constant in descriptors:
            value = constant
            if storage == 0x50:
                value, position = read_value(position, kind, start + row_width)
            row[name] = value
        rows.append(row)
    return {"name": string(name_at), "rows": rows}


def _acb(raw):
    header = utf_rows(raw)
    if len(header["rows"]) != 1:
        _fail("The audio cue sheet must contain one header.")
    root, tables = header["rows"][0], {}
    def table(name):
        if name not in tables:
            blob = root.get(name, b"")
            tables[name] = utf_rows(blob)["rows"] if isinstance(blob, bytes) and blob else []
        return tables[name]
    def row(name, index):
        rows = table(name)
        if type(index) is not int or not 0 <= index < len(rows):
            _fail("An audio cue references a missing CRI table row.")
        return rows[index]
    return root, table, row


def inspect_cues(acb):
    """Return sheet identity and each exact named cue's playable wave refs."""
    root, table, row = _acb(_bytes(acb, MAX_ACB_BYTES))
    budget = [100000]
    def references(kind, index, active):
        budget[0] -= 1
        if budget[0] < 0:
            _fail("The cue sheet exceeds the bounded audio reference limit.")
        key = kind, index
        if key in active or len(active) > 16:
            _fail("An audio cue contains a circular or excessively deep reference.")
        active = active | {key}
        if kind == 1:
            item = row("WaveformTable", index)
            streaming = bool(item.get("Streaming", 0))
            ident = item.get("Id", item.get("StreamAwbId" if streaming else "MemoryAwbId"))
            if type(ident) is not int or not 0 <= ident <= 65535:
                _fail("An audio cue references an invalid waveform ID.")
            return [{"waveformIndex": index, "awbId": ident, "streaming": streaming}]
        if kind == 2:
            item = row("SynthTable", index)
            blob = item.get("ReferenceItems", b"")
            if not isinstance(blob, bytes) or len(blob) % 4 or len(blob) > 4096:
                _fail("The audio synth has invalid waveform references.")
            found = []
            for at in range(0, len(blob), 4):
                child_kind, child_index = struct.unpack_from(">HH", blob, at)
                if child_kind == 0:
                    continue
                found.extend(references(child_kind, child_index, active))
                if len(found) > 4096:
                    _fail("The cue references too many audio waveform layers.")
            return found
        if kind == 3:
            item = row("SequenceTable", index)
            tracks, count = item.get("TrackIndex", b""), item.get("NumTracks", 0)
            if type(count) is not int or not isinstance(tracks, bytes) or not 0 <= count <= 1024 or len(tracks) < count * 2:
                _fail("The audio sequence has invalid track references.")
            found = []
            for at in range(count):
                track_index, = struct.unpack_from(">H", tracks, at * 2)
                track = row("TrackTable", track_index)
                event_index = track.get("EventIndex", 65535)
                if event_index == 65535:
                    continue
                name = "TrackEventTable" if table("TrackEventTable") else "CommandTable"
                commands = row(name, event_index).get("Command", b"")
                if not isinstance(commands, bytes) or len(commands) > 65536:
                    _fail("The audio sequence contains invalid event commands.")
                pos = 0
                while pos < len(commands):
                    if pos + 3 > len(commands):
                        _fail("The audio event command is truncated.")
                    code, size = struct.unpack_from(">HB", commands, pos); pos += 3
                    if pos + size > len(commands):
                        _fail("The audio event data is truncated.")
                    if code in (2000, 2003, 2004) and size >= 4:
                        child_kind, child_index = struct.unpack_from(">HH", commands, pos)
                        found.extend(references(child_kind, child_index, active))
                        if len(found) > 4096:
                            _fail("The cue references too many audio waveform layers.")
                    pos += size
            return found
        _fail("This audio cue uses an unsupported CRI playback reference.")
    cues = []
    if len(table("CueNameTable")) > 4096:
        _fail("The cue sheet exceeds the bounded cue-name limit.")
    for item in table("CueNameTable"):
        index = item.get("CueIndex")
        name = item.get("CueName")
        if not isinstance(name, str) or not name:
            continue
        cue = row("CueTable", index)
        try:
            waveforms = references(cue.get("ReferenceType"), cue.get("ReferenceIndex"), set())
            unique = {(w["awbId"], w["streaming"]): w for w in waveforms}
            entry = {"name": name, "id": cue.get("CueId", index), "index": index, "waveforms": list(unique.values())}
        except AudioDecodeError as error:
            entry = {"name": name, "id": cue.get("CueId", index), "index": index, "waveforms": [], "error": str(error)}
        cues.append(entry)
    return {"sheet": root.get("Name", root.get("CueSheetName", "")), "cues": cues}


def awb_entries(raw):
    _bytes(raw, MAX_AWB_BYTES)
    if len(raw) < 16 or raw[:4] != b"AFS2":
        _fail("The audio bank is not a supported AFS2 AWB file.")
    offset_size, id_size = raw[5], raw[6]
    count, alignment, subkey = struct.unpack_from("<IHH", raw, 8)
    if offset_size not in (2, 4, 8) or id_size not in (2, 4) or not 0 < count <= MAX_ROWS or not 0 < alignment <= 65535:
        _fail("The audio bank has invalid entry metadata.")
    table_end = 16 + count * id_size + (count + 1) * offset_size
    if table_end > len(raw):
        _fail("The audio bank has a truncated entry table.")
    ids = [int.from_bytes(raw[16 + i * id_size:16 + (i + 1) * id_size], "little") for i in range(count)]
    pos = 16 + count * id_size
    offsets = [int.from_bytes(raw[pos + i * offset_size:pos + (i + 1) * offset_size], "little") for i in range(count + 1)]
    if len(set(ids)) != count:
        _fail("The audio bank contains duplicate wave IDs.")
    entries = []
    for i, ident in enumerate(ids):
        start = (offsets[i] + alignment - 1) // alignment * alignment
        end = offsets[i + 1]
        if not table_end <= start < end <= len(raw):
            _fail("The audio bank contains an invalid waveform range.")
        entries.append({"id": ident, "start": start, "end": end, "subkey": subkey})
    return entries


class _HCAInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint) for name in ("version", "headerSize", "samplingRate", "channelCount", "blockSize", "blockCount", "encoderDelay", "encoderPadding", "loopEnabled", "loopStartBlock", "loopEndBlock", "loopStartDelay", "loopEndPadding", "samplesPerBlock")] + [
        ("comment", ctypes.c_char_p), ("encryptionEnabled", ctypes.c_uint), ("sampleCount", ctypes.c_uint),
        ("loopStartSample", ctypes.c_uint), ("loopEndSample", ctypes.c_uint), ("ambisonics", ctypes.c_int)]


def _native_library():
    explicit = os.environ.get("ELICHIKA_HCA_LIBRARY")
    candidates = [explicit] if explicit else []
    native = os.environ.get("ELICHIKA_NATIVE_DIR")
    names = ("libelichika_hca.dylib", "libelichika_hca.so", "elichika_hca.dll")
    if native:
        candidates.extend(str(Path(native) / name) for name in names)
    candidates.extend(str(_RESOURCE / name) for name in names)
    candidates.extend(names)
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate)
            lib.clHCA_new.restype = ctypes.c_void_p
            lib.clHCA_delete.argtypes = [ctypes.c_void_p]
            lib.clHCA_SetKey.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong]
            lib.clHCA_DecodeHeader.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            lib.clHCA_getInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HCAInfo)]
            lib.clHCA_DecodeBlock.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            lib.clHCA_ReadSamples16.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16)]
            return lib
        except (OSError, AttributeError):
            continue
    return None


def _decode_native(stream, path, subkey=0):
    lib = _native_library()
    if lib is None:
        return None
    if len(stream) < 8:
        _fail("The HCA waveform has no complete header.")
    header_size = int.from_bytes(stream[6:8], "big")
    if not 8 <= header_size <= min(len(stream), 65535):
        _fail("The HCA waveform has an invalid header size.")
    handle = lib.clHCA_new()
    if not handle:
        _fail("The HCA decoder could not allocate its state.")
    try:
        key = SIFAS_HCA_KEY
        if subkey:
            key = (key * ((subkey << 16) | ((~subkey + 2) & 0xffff))) & ((1 << 64) - 1)
        lib.clHCA_SetKey(handle, key)
        header = ctypes.create_string_buffer(stream[:header_size])
        if lib.clHCA_DecodeHeader(handle, header, header_size) < 0:
            _fail("The HCA decoder rejected the waveform header.")
        info = _HCAInfo()
        if lib.clHCA_getInfo(handle, ctypes.byref(info)) < 0 or not 1 <= info.channelCount <= 8 or not 8000 <= info.samplingRate <= 192000 or info.samplesPerBlock != 1024:
            _fail("The HCA waveform uses unsupported playback metadata.")
        total = info.blockCount * info.samplesPerBlock
        if info.encoderDelay + info.encoderPadding >= total or (total - info.encoderDelay - info.encoderPadding) * info.channelCount * 2 > MAX_PCM_BYTES or info.headerSize + info.blockSize * info.blockCount > len(stream):
            _fail("The HCA waveform exceeds its sample or byte bounds.")
        samples = (ctypes.c_int16 * (info.samplesPerBlock * info.channelCount))()
        block = ctypes.create_string_buffer(info.blockSize)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(info.channelCount); output.setsampwidth(2); output.setframerate(info.samplingRate)
            for index in range(info.blockCount):
                at = info.headerSize + index * info.blockSize
                ctypes.memmove(block, stream[at:at + info.blockSize], info.blockSize)
                if lib.clHCA_DecodeBlock(handle, block, info.blockSize) < 0:
                    _fail("The HCA decoder rejected an audio frame or encryption key.")
                lib.clHCA_ReadSamples16(handle, samples)
                start = max(0, info.encoderDelay - index * info.samplesPerBlock)
                end = min(info.samplesPerBlock, total - info.encoderPadding - index * info.samplesPerBlock)
                if start < end:
                    frame = bytes(samples)[start * info.channelCount * 2:end * info.channelCount * 2]
                    if sys.byteorder != "little":
                        import array
                        pcm = array.array("h"); pcm.frombytes(frame); pcm.byteswap(); frame = pcm.tobytes()
                    output.writeframesraw(frame)
        return {"backend": "clhca", "rate": info.samplingRate, "channels": info.channelCount, "frames": total - info.encoderDelay - info.encoderPadding,
                "duration": (total - info.encoderDelay - info.encoderPadding) / info.samplingRate}
    finally:
        lib.clHCA_delete(handle)


def decode_cue(acb, awb, cue, wav_output):
    """Decode one exact named/numeric ACB cue to a browser-compatible PCM WAV.

    ``acb``/``awb`` are immutable bytes; ``awb`` may be None for memory cues.
    The output location is selected by the server's private cache, not by a
    request path. This function does not download assets or publish them.
    """
    catalog = inspect_cues(acb)
    choices = [item for item in catalog["cues"] if (isinstance(cue, str) and item["name"] == cue) or (type(cue) is int and item["id"] == cue)]
    if not choices and cue == catalog["sheet"] and len(catalog["cues"]) == 1:
        choices = catalog["cues"]
    if cue is None and len(catalog["cues"]) == 1:
        choices = catalog["cues"]
    if len(choices) != 1:
        _fail("The requested voice or music cue is missing or ambiguous in its cue sheet.")
    selected = choices[0]
    if len(selected["waveforms"]) != 1:
        _fail(selected.get("error") or "This cue uses several waveform layers; a single exact stream cannot be selected.")
    waveform = selected["waveforms"][0]
    root, _, _ = _acb(acb)
    bank = awb if waveform["streaming"] else root.get("AwbFile")
    if not isinstance(bank, bytes) or not bank:
        _fail("The selected cue requires its external audio bank.")
    entries = awb_entries(bank)
    matches = [entry for entry in entries if entry["id"] == waveform["awbId"]]
    if len(matches) != 1:
        _fail("The selected cue's waveform is missing from its audio bank.")
    entry = matches[0]
    stream = bank[entry["start"]:entry["end"]]
    signature = bytes(value & 0x7f for value in stream[:4])
    path = Path(wav_output)
    if signature == b"HCA\0":
        metadata = _decode_native(stream, path, entry["subkey"])
        if metadata is not None:
            return {**metadata, "sampleRate": metadata["rate"], "decoder": metadata["backend"], "cue": selected["name"], "cueId": selected["id"], "waveId": entry["id"]}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _fail("The app's HCA decoder is missing. Install the updated app or configure a local FFmpeg decoder.")
    # Native HCA handles keyed streams; FFmpeg is a bounded alternate for plain
    # HCA and ADX. Pipes avoid temporary copies of the source game audio.
    try:
        process = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "hca" if signature == b"HCA\0" else "adx", "-i", "pipe:0",
                                  "-fs", str(MAX_PCM_BYTES), "-c:a", "pcm_s16le", "-f", "wav", "-y", str(path)],
                                 input=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)
    except (subprocess.TimeoutExpired, OSError) as error:
        raise AudioDecodeError("The local audio decoder could not finish this cue.") from error
    if process.returncode or not path.is_file():
        _fail("The local audio decoder could not decode this cue.")
    if path.stat().st_size >= MAX_PCM_BYTES:
        _fail("The decoded voice or music exceeds the PCM limit.")
    try:
        with wave.open(str(path), "rb") as output:
            frames, rate, channels = output.getnframes(), output.getframerate(), output.getnchannels()
            if output.getsampwidth() != 2 or not 0 < frames * channels * 2 <= MAX_PCM_BYTES:
                _fail("The decoded voice or music exceeds the PCM limit.")
    except (wave.Error, EOFError) as error:
        _fail("The decoded voice or music has invalid PCM data.")
    return {"backend": "ffmpeg", "decoder": "ffmpeg", "rate": rate, "sampleRate": rate, "channels": channels, "frames": frames, "duration": frames / rate,
            "cue": selected["name"], "cueId": selected["id"], "waveId": entry["id"]}
