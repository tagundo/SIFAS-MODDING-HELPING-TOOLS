"""Re-encode only the ASTC blocks that hold changed texels.

A baked blush changes a few thousand texels around the cheeks of a face
texture. The default save (blush encoding "exact") writes the whole texture as
RGBA32: every texel exact, but an ASTC 6x6 face about nine times larger. The
opt-in "astc-keep" encoding uses this module to keep the original ASTC format
instead: in every level, each block whose texels the bake leaves alone keeps
its original 16 bytes, and only the blocks that contain a changed texel are
compressed again from the exact baked pixels (astcenc 4.8, LDR, exhaustive).

ASTC is lossy, so a re-encoded block approximates the bake: its decoded texels,
including ones the rule does not change, can differ from the exact bake by a
few levels. The caller decodes every spliced level again and refuses the
result unless the texels outside the re-encoded blocks are unchanged and alpha
is unchanged everywhere.

Layout: Unity stores rows bottom-up, so block row 0 of a level is the bottom of
the image (v = 0). The images passed here are in top-left (PNG) row order.
No pixel is resampled, padded or shifted: a crop aligned to the block grid of
the baked level is compressed and its blocks are copied to the same positions.
"""
import math
import os
import re
import subprocess
import tempfile
import time

_ASTC = re.compile(r"ASTC_(?:RGB|RGBA)_(4|5|6|8|10|12)x\1")
_MAGIC = b"\x13\xab\xa1\x5c"
# Sanity limits for a re-encoded level, per RGB channel against the exact bake:
# beyond them the encoder did not compress what it was given (a wrong
# orientation or a broken tool). Measured on a real ASTC 6x6 face: mean error
# 0.14 (1024x1024) to 4.1 (8x8, where a block spans the whole face), maximum
# 4 at full size and up to 25 in the 32x32/16x16 mips, whose blocks are dense.
MAX_MEAN_CHANNEL_ERROR = 8.0
MAX_CHANNEL_ERROR = 64


class SpliceUnavailable(Exception):
    """The original compression cannot be kept; the caller saves losslessly."""


# Also the reason the caller gives when its own decoding of the levels runs
# out of the splice's time budget.
TOO_LONG = "Re-encoding the baked blocks took too long."


def astc_block(format_name):
    """The block edge of a square ASTC format name, or None."""
    match = _ASTC.fullmatch(str(format_name or ""))
    return int(match.group(1)) if match else None


def level_layout(width, height, count, block):
    """[(width, height, byte offset, byte size)] of each mip level."""
    rows, offset = [], 0
    for level in range(count):
        w, h = max(1, width >> level), max(1, height >> level)
        size = math.ceil(w / block) * math.ceil(h / block) * 16
        rows.append((w, h, offset, size))
        offset += size
    return rows


def touched_blocks(before, after, width, height, block, box):
    """Blocks (x, y counted from the bottom row) holding a texel whose RGB changed.

    ``before``/``after`` are straight RGBA bytes in top-left row order and
    ``box`` is the bake's inclusive changed rectangle (or None).
    """
    blocks = set()
    if box is None:
        return blocks
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        row, by = y * width * 4, (height - 1 - y) // block
        for x in range(x0, x1 + 1):
            offset = row + x * 4
            if before[offset:offset + 3] != after[offset:offset + 3]:
                blocks.add((x // block, by))
    return blocks


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise SpliceUnavailable(TOO_LONG)
    return seconds


def encode(image, block, deadline):
    """Raw ASTC blocks of an RGBA image whose first row is block row 0.

    Uses the app's astcenc (ASTCENC_BIN), the same tool that decodes these
    textures. Tools without an encoder raise SpliceUnavailable. The command
    line ``-cl IN.png OUT.astc BxB -exhaustive -decode_unorm8 -j N`` is the
    one ARM astcenc 4.8.0 (the version the apps build) accepts; set
    REAL_ASTCENC_BIN to run tests/test_viewer_texture_blush.py
    RealAstcencTests against such a binary.
    """
    binary = os.environ.get("ASTCENC_BIN")
    if not binary or not os.path.isfile(binary):
        raise SpliceUnavailable("The ASTC encoder is unavailable.")
    width, height = image.size
    needed = math.ceil(width / block) * math.ceil(height / block) * 16
    threads = max(1, min(4, os.cpu_count() or 1))
    with tempfile.TemporaryDirectory(prefix="webtools_astc_splice_") as directory:
        source = os.path.join(directory, "blocks.png")
        output = os.path.join(directory, "blocks.astc")
        image.save(source)
        # -decode_unorm8 matches how the game and these tools decode LDR ASTC
        # (8-bit). An astcenc without that option is asked again without it.
        for extra in (["-decode_unorm8"], []):
            if os.path.lexists(output):
                os.remove(output)
            try:
                result = subprocess.run([binary, "-cl", source, output, f"{block}x{block}", "-exhaustive", *extra,
                                         "-j", str(threads)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=_remaining(deadline))
            except subprocess.TimeoutExpired as error:
                raise SpliceUnavailable(TOO_LONG) from error
            except OSError as error:
                raise SpliceUnavailable("The ASTC encoder could not be started.") from error
            if result.returncode == 0 and os.path.isfile(output) and not os.path.islink(output):
                break
        else:
            raise SpliceUnavailable("The ASTC encoder could not re-encode the baked blocks.")
        with open(output, "rb") as stream:
            raw = stream.read(16 + needed + 1)
    if (len(raw) != 16 + needed or raw[:4] != _MAGIC or tuple(raw[4:7]) != (block, block, 1)
            or int.from_bytes(raw[7:10], "little") != width or int.from_bytes(raw[10:13], "little") != height
            or int.from_bytes(raw[13:16], "little") != 1):
        raise SpliceUnavailable("The ASTC encoder returned unexpected data.")
    return raw[16:]


def splice_level(data, width, height, block, baked, blocks, deadline):
    """``data`` (one level's blocks) with ``blocks`` re-encoded from ``baked``.

    ``baked`` is the exact baked level as a top-left RGBA PIL image. Every
    other block keeps its original bytes.
    """
    from PIL import Image
    if not blocks:
        return bytes(data)
    columns = math.ceil(width / block)
    bx0, bx1 = min(x for x, _ in blocks), max(x for x, _ in blocks)
    by0, by1 = min(y for _, y in blocks), max(y for _, y in blocks)
    # The crop starts on the block grid, so its blocks are the level's blocks.
    with baked.transpose(Image.Transpose.FLIP_TOP_BOTTOM) as unity:
        with unity.crop((bx0 * block, by0 * block, min(width, (bx1 + 1) * block),
                         min(height, (by1 + 1) * block))) as crop:
            crop_columns = math.ceil(crop.width / block)
            encoded = encode(crop, block, deadline)
    out = bytearray(data)
    for x, y in blocks:
        source = ((y - by0) * crop_columns + (x - bx0)) * 16
        target = (y * columns + x) * 16
        out[target:target + 16] = encoded[source:source + 16]
    return bytes(out)


def check_level(before, baked, after, width, height, block, blocks):
    """Statistics of a decoded spliced level; refuses an unsafe result.

    ``before`` is the decoded original level, ``baked`` the exact bake and
    ``after`` the decoded spliced level (all top-left RGBA bytes).
    """
    off, collateral, worst, total, samples = 0, 0, 0, 0, 0
    block_rows = {y for _, y in blocks}
    stride = width * 4
    for y in range(height):
        by = (height - 1 - y) // block
        row = y * stride
        if by not in block_rows:
            # The bake changes nothing in this row either (its texels are in
            # untouched blocks), so the decoded row must be the original row.
            if after[row:row + stride] != before[row:row + stride]:
                raise SpliceUnavailable("Re-encoded blocks changed texels outside the baked area.")
            continue
        for x in range(width):
            offset = row + x * 4
            if (x // block, by) in blocks:
                if after[offset + 3] != before[offset + 3]:
                    raise SpliceUnavailable("Re-encoding the baked blocks would change alpha.")
                samples += 3
                if after[offset:offset + 3] != baked[offset:offset + 3]:
                    off += 1
                    errors = [abs(after[offset + c] - baked[offset + c]) for c in range(3)]
                    total += sum(errors)
                    worst = max(worst, *errors)
                    if baked[offset:offset + 3] == before[offset:offset + 3]:
                        # A texel the rule leaves alone, changed by the re-encode.
                        collateral += 1
            elif after[offset:offset + 4] != before[offset:offset + 4]:
                raise SpliceUnavailable("Re-encoded blocks changed texels outside the baked area.")
    mean = total / samples if samples else 0.0
    if worst > MAX_CHANNEL_ERROR or mean > MAX_MEAN_CHANNEL_ERROR:
        raise SpliceUnavailable("The re-encoded blocks are not close enough to the bake.")
    return {"texelsOffBake": off, "untouchedTexelsChanged": collateral, "maxChannelError": worst,
            "meanChannelError": round(mean, 3)}
