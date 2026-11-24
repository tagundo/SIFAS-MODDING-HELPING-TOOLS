"""CRI @UTF tables and AFS2 banks for MV-only songs.

The @UTF writer keeps each column's storage flag (zero, constant or per row)
and lays tables out like the stock ACB writer, so a stock cue sheet read and
written again is byte-identical.
"""
from dataclasses import dataclass
import math
import struct

from . import cri_audio_decode
from .cri_hca_encode import AudioEncodeError

__all__ = ["AudioEncodeError", "UtfColumn", "UtfTable", "read_utf", "write_utf", "read_afs2", "write_afs2",
           "afs2_header_size"]

ZERO, CONSTANT, PER_ROW = 0x10, 0x30, 0x50
_FORMATS = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i", 6: ">Q", 7: ">q", 8: ">f", 9: ">d"}
_WIDTHS = {**{kind: struct.calcsize(fmt) for kind, fmt in _FORMATS.items()}, 10: 4, 11: 8}
_ROOT_ALIGN = 32


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
