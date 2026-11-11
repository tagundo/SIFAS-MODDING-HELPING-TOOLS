"""Bounded, non-executable layer documents with exact straight-RGBA PNGs.

Projects are explicit authoring files. Game textures remain flattened through
the existing source-bound texture writer; project metadata never changes a
model's material, UV or texture identity.
"""
import base64
import binascii
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import zlib

FORMAT = "elichika-texture-project"
VERSION = 1
EXTENSION = ".elichika-texture.json"
MAX_BYTES = 32 * 1024 * 1024
MAX_LAYER_PNG_BYTES = 8 * 1024 * 1024
MAX_LAYERS = 8
MAX_PIXELS = 16 * 1024 * 1024
MAX_TOTAL_PIXELS = 32 * 1024 * 1024
MAX_DECODED_BYTES = 128 * 1024 * 1024
MAX_DIMENSION = 8192
_PREFIX = "data:image/png;base64,"
_LAYER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_TOP_KEYS = {"format", "version", "width", "height", "activeLayer", "layers"}
_LAYER_KEYS = {"id", "name", "visible", "opacity", "png"}


class TextureProjectError(ValueError):
    pass


def _require(value, message):
    if not value:
        raise TextureProjectError(message)


def _pairs(rows):
    result = {}
    for key, value in rows:
        _require(key not in result, "The texture project contains duplicate JSON keys.")
        result[key] = value
    return result


def _payload(value):
    if type(value) is dict:
        return value
    _require(type(value) in (str, bytes) and 0 < len(value) <= MAX_BYTES,
             "Choose a texture project within the 32 MiB document limit.")
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        _require(len(value.encode("utf-8")) <= MAX_BYTES, "The texture project exceeds its document size limit.")
        return json.loads(value, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(TextureProjectError("Nonfinite texture project metadata.")))
    except TextureProjectError:
        raise
    except (ValueError, RecursionError) as error:
        raise TextureProjectError("The texture project JSON is invalid.") from error


def _png_parts(value, width, height):
    _require(type(value) is str and value.startswith(_PREFIX) and
             len(value) <= len(_PREFIX) + ((MAX_LAYER_PNG_BYTES + 2) // 3) * 4,
             "Each project layer must contain a PNG within the 8 MiB limit.")
    try:
        raw = base64.b64decode(value[len(_PREFIX):], validate=True)
    except (ValueError, binascii.Error) as error:
        raise TextureProjectError("A project layer has invalid PNG encoding.") from error
    _require(0 < len(raw) <= MAX_LAYER_PNG_BYTES and raw[:8] == b"\x89PNG\r\n\x1a\n",
             "A project layer must contain a bounded PNG image.")
    offset, count, seen_header, seen_data, ended_data, seen_palette = 8, 0, False, False, False, False
    data, interlace = [], None
    while offset < len(raw):
        _require(offset + 12 <= len(raw), "A project layer PNG is truncated.")
        length, = struct.unpack_from(">I", raw, offset)
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        count += 1
        _require(count <= 4096 and end <= len(raw) and
                 all(65 <= char <= 90 or 97 <= char <= 122 for char in kind) and not kind[2] & 32,
                 "A project layer PNG has invalid or excessive chunks.")
        body = memoryview(raw)[offset + 8:offset + 8 + length]
        checksum, = struct.unpack_from(">I", raw, end - 4)
        _require(zlib.crc32(body, zlib.crc32(kind)) & 0xffffffff == checksum,
                 "A project layer PNG has an invalid checksum.")
        _require(kind not in (b"acTL", b"fcTL", b"fdAT", b"zTXt", b"iTXt", b"iCCP"),
                 "Use a single-frame RGBA PNG without compressed ancillary metadata in each project layer.")
        if not seen_header:
            _require(kind == b"IHDR" and length == 13, "A project layer PNG has no valid image header.")
            actual_width, actual_height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            _require((actual_width, actual_height) == (width, height) and depth == 8 and color == 6 and
                     compression == filtering == 0 and interlace in (0, 1),
                     "Project layers must be 8-bit RGBA PNGs matching the document dimensions.")
            seen_header = True
        elif kind == b"IHDR":
            raise TextureProjectError("A project layer PNG has duplicate image headers.")
        elif kind == b"IDAT":
            _require(not ended_data, "A project layer PNG has an invalid image-data sequence.")
            seen_data = True
            data.append(body)
        elif kind == b"IEND":
            _require(length == 0 and end == len(raw) and seen_data,
                     "A project layer PNG has trailing, missing or invalid image data.")
            return raw, data, interlace
        elif kind == b"PLTE":
            _require(not seen_palette and not seen_data and 3 <= length <= 768 and length % 3 == 0,
                     "A project layer PNG has an invalid suggested palette.")
            seen_palette = True
        else:
            _require(kind[0] & 32, "A project layer PNG has an unsupported critical chunk.")
            if seen_data:
                ended_data = True
        offset = end
    raise TextureProjectError("A project layer PNG is incomplete.")


def _scanlines(width, height, interlace):
    if not interlace:
        return [(width * 4 + 1, height)]
    rows = []
    for x, y, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                         (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
        columns = max(0, (width - x + dx - 1) // dx)
        count = max(0, (height - y + dy - 1) // dy)
        if columns and count:
            rows.append((columns * 4 + 1, count))
    return rows


def _verify_pixels(parts, width, height):
    # Check the full zlib stream and scanline filters in bounded blocks. No
    # RGBA image allocation, premultiplication, conversion or recompression is
    # needed to validate and preserve the exact authored PNG bytes.
    raw, chunks, interlace = parts
    rows = _scanlines(width, height, interlace)
    expected = sum(size * count for size, count in rows)
    total, segment, remaining_rows = 0, 0, rows[0][1]
    row_size = remaining = rows[0][0]
    inflater = zlib.decompressobj()
    try:
        for chunk in chunks:
            pending = chunk
            while pending:
                block = inflater.decompress(pending, min(65536, expected + 1 - total))
                pending = inflater.unconsumed_tail
                total += len(block)
                _require(total <= expected and not inflater.unused_data,
                         "A project layer PNG expands beyond its declared image dimensions.")
                at = 0
                while at < len(block):
                    _require(segment < len(rows), "A project layer PNG has excess pixel data.")
                    if remaining == row_size:
                        _require(block[at] <= 4, "A project layer PNG has an invalid scanline filter.")
                    amount = min(remaining, len(block) - at)
                    remaining -= amount
                    at += amount
                    if not remaining:
                        remaining_rows -= 1
                        if not remaining_rows:
                            segment += 1
                            if segment < len(rows):
                                row_size, remaining_rows = rows[segment]
                        remaining = row_size
                _require(not inflater.eof or not pending, "A project layer PNG contains extra compressed data.")
        _require(inflater.eof and total == expected and segment == len(rows),
                 "A project layer PNG has truncated or invalid pixel data.")
    except zlib.error as error:
        raise TextureProjectError("A project layer PNG has damaged pixel data.") from error


def validate_project(payload):
    """Return canonical portable metadata; retain every layer PNG byte exactly."""
    project = _payload(payload)
    _require(type(project) is dict and set(project) == _TOP_KEYS and project["format"] == FORMAT and
             type(project["version"]) is int and project["version"] == VERSION,
             "The texture project format or fields are unsupported.")
    width, height, layers = project["width"], project["height"], project["layers"]
    _require(type(width) is int and type(height) is int and 0 < width <= MAX_DIMENSION and
             0 < height <= MAX_DIMENSION and width * height <= MAX_PIXELS,
             "The texture project exceeds the supported 16-megapixel image dimensions.")
    _require(type(layers) is list and 1 <= len(layers) <= MAX_LAYERS,
             "A texture project must contain between one and eight layers.")
    pixels = width * height * len(layers)
    _require(pixels <= MAX_TOTAL_PIXELS and pixels * 4 <= MAX_DECODED_BYTES,
             "The texture project layers exceed the aggregate decoded image budget.")
    canonical, ids, encoded_size = [], set(), 0
    for layer in layers:
        _require(type(layer) is dict and set(layer) == _LAYER_KEYS, "A texture project layer has unsupported fields.")
        identity, name, opacity = layer["id"], layer["name"], layer["opacity"]
        _require(type(identity) is str and _LAYER_ID.fullmatch(identity) and identity not in ids,
                 "Project layers need unique, bounded text identities.")
        _require(type(name) is str and 0 < len(name) <= 128 and not any(ord(char) < 32 or ord(char) == 127 for char in name),
                 "Choose a bounded layer name without control characters.")
        _require(type(layer["visible"]) is bool and type(opacity) in (int, float) and 0 <= opacity <= 1 and math.isfinite(opacity),
                 "Layer visibility and opacity must be valid finite values.")
        _require(type(layer["png"]) is str, "A project layer needs an inline PNG image.")
        encoded_size += len(layer["png"])
        _require(encoded_size <= MAX_BYTES, "The texture project exceeds its document size limit.")
        ids.add(identity)
        canonical.append({"id": identity, "name": name, "visible": layer["visible"], "opacity": opacity, "png": layer["png"]})
    _require(type(project["activeLayer"]) is str and project["activeLayer"] in ids,
             "Choose an active layer from this texture project.")
    result = {"format": FORMAT, "version": VERSION, "width": width, "height": height,
              "activeLayer": project["activeLayer"], "layers": canonical}
    _require(len(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) <= MAX_BYTES,
             "The texture project exceeds its document size limit.")
    # Preflight every image header, checksum and shared budget before inflating
    # any pixel stream; process images individually to keep memory bounded.
    for layer in canonical:
        _png_parts(layer["png"], width, height)
    for layer in canonical:
        _verify_pixels(_png_parts(layer["png"], width, height), width, height)
    return result


def _safe_path(value):
    try:
        path = Path(value).absolute()
    except (TypeError, ValueError, OSError) as error:
        raise TextureProjectError("Choose a valid texture project file path.") from error
    _require(not any(item.is_symlink() for item in (path, *path.parents)),
             "Texture project files must not use symbolic links.")
    return path


def open_project(path):
    source = _safe_path(path)
    _require(source.name.lower().endswith(EXTENSION), "Choose an .elichika-texture.json project file.")
    try:
        before = source.stat()
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_BYTES,
                 "Choose a regular texture project within the 32 MiB document limit.")
        with source.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = source.stat()
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
                 "The texture project changed while reading.")
        return validate_project(raw)
    except OSError as error:
        raise TextureProjectError("The texture project could not be opened.") from error


def save_project(project, name, output_root):
    canonical = validate_project(project)
    _require(type(name) is str and 0 < len(name) <= 1024, "Choose a texture project file name.")
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", name).strip(". ")
    if stem.lower().endswith(EXTENSION):
        stem = stem[:-len(EXTENSION)]
    stem = stem.encode("utf-8")[:180].decode("utf-8", errors="ignore").strip(". ") or "texture"
    directory = _safe_path(output_root)
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    for attempt in range(1000):
        suffix = "" if not attempt else " (" + str(attempt + 1) + ")"
        target = directory / (stem + suffix + EXTENSION)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return {"path": str(target), "name": target.name}
    raise TextureProjectError("Choose another texture project name; too many copies already exist.")
