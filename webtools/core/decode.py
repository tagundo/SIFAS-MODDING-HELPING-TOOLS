"""Body-texture previews with platform-appropriate decoder isolation.

The native texture codecs (texture2ddecoder / astc-encoder / etcpak) can crash
with SIGILL on some Termux/ARM builds. The packer already ships a throwaway-child
decode worker exactly for this reason; we shell out to it so a codec crash kills
only the child and we fall back to "no thumbnail" instead of taking down the
server. Embedded Chaquopy cannot run a Python CLI child: there we allow only
bounded Pillow raw pixels and isolate ASTC/UnityCrunch in bundled executables.
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict

from . import mv_studio_progress, transient_failures
from .repo import ensure_repo_on_path, repo_root

# (path, mtime) -> PNG bytes; b"" marks a known-failed decode so we don't retry.
_CACHE: dict = {}
_ANDROID_LOCK = threading.Lock()
_ANDROID_CACHE = OrderedDict()
_ANDROID_CACHE_ENTRIES = 64
_ANDROID_CACHE_BYTES = 32 * 1024 * 1024
_TEXTURE65_SLOT = threading.BoundedSemaphore(1)
_MAX_DIMENSION = 8192
_MAX_PIXELS = 4096 * 4096
_MAX_SOURCE_BYTES = _MAX_PIXELS * 4 * 2  # base level plus mipmaps, bounded before stream reads
_RAW_FORMATS = {
    "RGBA32": ("RGBA", "RGBA", 4),
    "RGB24": ("RGB", "RGB", 3),
    "ARGB32": ("RGBA", "ARGB", 4),
    "BGRA32": ("RGBA", "BGRA", 4),
}
# "etc2a8" decodes in this process with numpy (_etc2_rgba8_image), the others in texture65.
_STAGE_BLOCK_FORMATS = {"ETC_RGB4": "etc1", "PVRTC_RGB4": "pvrtc4", "PVRTC_RGBA4": "pvrtc4a", "ETC2_RGBA8": "etc2a8"}
# ETC1/ETC2 and EAC tables (OpenGL ES 3.0 C.1), in the order of the pinned upstream
# texture2ddecoder etc.cpp (resources/texture65_decoder/upstream).
_ETC1_MODIFIERS = ((2, 8), (5, 17), (9, 29), (13, 42), (18, 60), (24, 80), (33, 106), (47, 183))
_ETC2_DISTANCES = (3, 6, 11, 16, 23, 32, 41, 64)
_EAC_MODIFIERS = (
    (-3, -6, -9, -15, 2, 5, 8, 14), (-3, -7, -10, -13, 2, 6, 9, 12), (-2, -5, -8, -13, 1, 4, 7, 12),
    (-2, -4, -6, -13, 1, 3, 5, 12), (-3, -6, -8, -12, 2, 5, 7, 11), (-3, -7, -9, -11, 2, 6, 8, 10),
    (-4, -7, -8, -11, 3, 6, 7, 10), (-3, -5, -8, -11, 2, 4, 7, 10), (-2, -6, -8, -10, 1, 5, 7, 9),
    (-2, -5, -8, -10, 1, 4, 7, 9), (-2, -4, -8, -10, 1, 3, 7, 9), (-2, -5, -7, -10, 1, 4, 6, 9),
    (-3, -4, -7, -10, 2, 3, 6, 9), (-1, -2, -3, -10, 0, 1, 2, 9), (-4, -6, -8, -9, 3, 5, 7, 8),
    (-3, -5, -7, -9, 2, 4, 6, 8))


def _etc2_rgb(blocks):
    """ETC2 RGB blocks (N, 8) -> (N, 16, 3) colours, pixel i = x * 4 + y (the bit order)."""
    import numpy as np

    d = [blocks[:, index].astype(np.int32)[:, None] for index in range(8)]
    pixel = np.arange(16)
    x, y = pixel // 4, pixel % 4
    j = (d[6] << 8 | d[7]) >> pixel & 1  # low index bit of pixel i
    k = (d[4] << 8 | d[5]) >> pixel & 1  # high index bit (the sign in the ETC1 modes)
    expand4 = lambda value: (value & 0xf0) | (value >> 4)
    clamp = lambda value: np.clip(value, 0, 255)
    # Individual and differential (ETC1) base colours, per subblock.
    r, g, b = d[0] & 0xf8, d[1] & 0xf8, d[2] & 0xf8
    delta = [(value << 3 & 0x18) - (value << 3 & 0x20) for value in d[:3]]
    differential = (d[3] & 2) != 0
    individual = [[expand4(value) for value in d[:3]], [expand4(value << 4 & 0xff) for value in d[:3]]]
    sums = [r + delta[0], g + delta[1], b + delta[2]]
    joined = [[value | value >> 5 for value in (r, g, b)],
              [np.clip(value, 0, 255) | np.clip(value, 0, 255) >> 5 for value in sums]]
    base = [np.stack([np.where(differential, joined[s][axis], individual[s][axis])[:, 0] for axis in range(3)], -1)
            for s in (0, 1)]
    flip = (d[3] & 1) != 0
    subblock = np.where(flip, y >= 2, x >= 2)
    table = np.asarray(_ETC1_MODIFIERS, np.int32)
    codes = np.where(subblock, d[3] >> 2 & 7, d[3] >> 5)
    modifier = table[codes, j]
    modifier = np.where(k == 1, -modifier, modifier)
    colors = np.where(subblock[..., None], base[1][:, None], base[0][:, None])
    result = clamp(colors + modifier[..., None])
    # T, H and planar: differential blocks whose red, green or blue sum overflows.
    t_mode = differential[:, 0] & ((sums[0] < 0) | (sums[0] > 255))[:, 0]
    h_mode = differential[:, 0] & ~t_mode & ((sums[1] < 0) | (sums[1] > 255))[:, 0]
    planar = differential[:, 0] & ~t_mode & ~h_mode & ((sums[2] < 0) | (sums[2] > 255))[:, 0]
    distances = np.asarray(_ETC2_DISTANCES, np.int32)
    select = 2 * k + j
    if t_mode.any():
        e = [value[t_mode] for value in d]
        first = np.stack([(e[0] << 3 & 0xc0) | (e[0] << 4 & 0x30) | (e[0] >> 1 & 0xc) | (e[0] & 3),
                          expand4(e[1]), expand4(e[1] << 4 & 0xff)], -1)
        second = np.stack([expand4(e[2]), expand4(e[2] << 4 & 0xff), expand4(e[3])], -1)
        step = distances[(e[3] >> 1 & 6) | (e[3] & 1)][..., None]
        palette = np.stack([first, clamp(second + step), second, clamp(second - step)], 1)[:, :, 0]
        result[t_mode] = np.take_along_axis(palette, select[t_mode][..., None], 1)
    if h_mode.any():
        e = [value[h_mode] for value in d]
        green = (e[0] << 5 & 0xe0) | (e[1] & 0x10)
        blue = (e[1] & 8) | (e[1] << 1 & 6) | e[2] >> 7
        first = np.stack([(e[0] << 1 & 0xf0) | (e[0] >> 3 & 0xf), green | green >> 4, blue | (blue << 4 & 0xff)], -1)
        green = (e[2] << 5 & 0xe0) | (e[3] >> 3 & 0x10)
        second = np.stack([(e[2] << 1 & 0xf0) | (e[2] >> 3 & 0xf), green | green >> 4,
                           (e[3] << 1 & 0xf0) | (e[3] >> 3 & 0xf)], -1)
        packed = lambda color: color[..., 0] << 16 | color[..., 1] << 8 | color[..., 2]
        index = (e[3] & 4) | (e[3] << 1 & 2) | (packed(first) >= packed(second)).astype(np.int32)
        step = distances[index][..., None]
        palette = np.stack([clamp(first + step), clamp(first - step), clamp(second + step), clamp(second - step)], 1)[:, :, 0]
        result[h_mode] = np.take_along_axis(palette, select[h_mode][..., None], 1)
    if planar.any():
        e = [value[planar] for value in d]
        blue = (e[1] << 7 & 0x80) | (e[2] << 2 & 0x60) | (e[2] << 3 & 0x18) | (e[3] >> 5 & 4)
        origin = np.stack([(e[0] << 1 & 0xfc) | (e[0] >> 5 & 3), (e[0] << 7 & 0x80) | (e[1] & 0x7e) | (e[0] & 1),
                           blue | blue >> 6], -1)
        blue = (e[4] << 7 & 0x80) | (e[5] >> 1 & 0x7c)
        horizontal = np.stack([(e[3] << 1 & 0xf8) | (e[3] << 2 & 4) | (e[3] >> 5 & 3), (e[4] & 0xfe) | e[4] >> 7,
                               blue | blue >> 6], -1)
        vertical = np.stack([(e[5] << 5 & 0xe0) | (e[6] >> 3 & 0x1c) | (e[5] >> 1 & 3),
                             (e[6] << 3 & 0xf8) | (e[7] >> 5 & 6) | (e[6] >> 4 & 1), (e[7] << 2 & 0xff) | (e[7] >> 4 & 3)], -1)
        result[planar] = clamp((x[:, None] * (horizontal - origin) + y[:, None] * (vertical - origin)
                                + 4 * origin + 2) >> 2)
    return result


def _etc2_rgba8_image(data, width, height):
    """Exact ETC2 RGBA8 (EAC alpha + ETC2 colour) pixels, unflipped, like texture65's output.

    A numpy port of upstream decode_etc2a8 (no native codec enters this process).
    """
    import numpy as np
    from PIL import Image

    columns, rows = (width + 3) // 4, (height + 3) // 4
    size = columns * rows * 16
    if len(data) < size:
        raise ValueError("Truncated compressed stage texture data.")
    blocks = np.frombuffer(bytes(data[:size]), np.uint8).reshape(-1, 16)
    pixels = np.empty((len(blocks), 16, 4), np.uint8)
    for start in range(0, len(blocks), 16384):  # bounds the int32 working arrays
        pixels[start:start + 16384, :, :3] = _etc2_rgb(blocks[start:start + 16384, 8:])
    alpha = blocks[:, :8].astype(np.int64)
    bits = np.zeros(len(blocks), np.uint64)
    for index in range(8):
        bits = bits << np.uint64(8) | alpha[:, index].astype(np.uint64)
    order = np.arange(16, dtype=np.uint64)
    codes = (bits[:, None] >> (np.uint64(3) * (np.uint64(15) - order)) & np.uint64(7)).astype(np.int64)
    multiplier = alpha[:, 1:2] >> 4
    modifiers = np.asarray(_EAC_MODIFIERS, np.int64)[alpha[:, 1] & 0xf]
    values = alpha[:, :1] + multiplier * np.take_along_axis(modifiers, codes, 1)
    # A zero multiplier keeps the base codeword for every pixel.
    pixels[..., 3] = np.where(multiplier == 0, alpha[:, :1], np.clip(values, 0, 255))
    # Pixel i = x * 4 + y -> rows of 4x4 blocks, cropped to the logical extent.
    image = pixels.reshape(rows, columns, 4, 4, 4).transpose(0, 3, 1, 2, 4).reshape(rows * 4, columns * 4, 4)
    return Image.fromarray(np.ascontiguousarray(image[:height, :width]), "RGBA")


def _embedded_android():
    """Chaquopy initializes this module before application Python code runs."""
    return sys.modules.get("java.android") is not None


def _remember_android_thumbnail(key, data):
    """Called under _ANDROID_LOCK; bound both PNG bytes and failed entries."""
    data = data or b""
    if len(data) > _ANDROID_CACHE_BYTES:
        return  # a single large preview may be served without retaining it
    _ANDROID_CACHE[key] = data
    _ANDROID_CACHE.move_to_end(key)
    while (len(_ANDROID_CACHE) > _ANDROID_CACHE_ENTRIES
           or sum(map(len, _ANDROID_CACHE.values())) > _ANDROID_CACHE_BYTES):
        _ANDROID_CACHE.popitem(last=False)


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        transient_failures.note()
        raise TimeoutError("Thumbnail decoding timed out")
    mv_studio_progress.alive()  # an MV import stops here for a client that left
    return seconds


def _texture65_profile(texture):
    """A mip proxy keeps original Crunch dimensions and immutable source data."""
    width = getattr(texture, "_texture65_source_width", texture.m_Width)
    height = getattr(texture, "_texture65_source_height", texture.m_Height)
    mip = getattr(texture, "_texture65_mip", 0)
    if (any(not isinstance(value, int) or isinstance(value, bool) for value in (width, height, mip))
            or not 0 < width <= _MAX_DIMENSION or not 0 < height <= _MAX_DIMENSION
            or width * height > _MAX_PIXELS or not 0 <= mip < max(width, height).bit_length()
            or (texture.m_Width, texture.m_Height) != (max(1, width >> mip), max(1, height >> mip))):
        raise ValueError("Invalid UnityCrunch mip dimensions or level")
    return width, height, mip


def _stage_block_image(format_name, data, width, height, deadline):
    from PIL import Image

    if format_name == "etc1":
        size = ((width + 3) // 4) * ((height + 3) // 4) * 8
    else:
        if min(width, height) < 8 or width & (width - 1) or height & (height - 1):
            raise ValueError("PVRTC stage textures must have power-of-two dimensions.")
        size = width * height // 2
    if len(data) < size:
        raise ValueError("Truncated compressed stage texture data.")
    binary = os.environ.get("ELICHIKA_TEXTURE65_BIN")
    if not binary or not os.path.isfile(binary):
        raise ValueError("The bundled stage texture decoder is unavailable.")
    if not _TEXTURE65_SLOT.acquire(timeout=_remaining(deadline)):
        transient_failures.note()
        raise TimeoutError("Another compressed texture is still decoding.")
    try:
        with tempfile.TemporaryDirectory(prefix="webtools_stage_texture_") as directory:
            source = os.path.join(directory, "texture.blocks")
            output = os.path.join(directory, "texture.rgba")
            with open(source, "wb") as stream:
                stream.write(data[:size])
            result = subprocess.run([binary, "--raw", format_name, str(width), str(height), source, output],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=min(12, _remaining(deadline)))
            if result.returncode:
                raise ValueError("The compressed stage texture could not be decoded.")
            expected = width * height * 4
            if os.path.islink(output) or not os.path.isfile(output) or os.path.getsize(output) != expected:
                raise ValueError("The stage texture decoder returned an incorrect pixel count.")
            with open(output, "rb") as stream:
                pixels = stream.read(expected + 1)
            if len(pixels) != expected:
                raise ValueError("The stage texture decoder output changed while reading.")
            return Image.frombytes("RGBA", (width, height), pixels)
    except BaseException:
        # The child may have been killed, timed out or failed to start.
        transient_failures.note()
        raise
    finally:
        _TEXTURE65_SLOT.release()


def _android_image(texture, deadline, *, stage=False):
    """Decode raw pixels or isolated ASTC/UnityCrunch ETC2A CLI results.

    Do not access Texture2D.image: unsupported formats can enter native texture
    decoders with known SIGILL failures. get_image_data() only reads bytes and
    also handles Unity's external/streamed texture storage. A failure of the
    machine (I/O, memory, a decoder child) is noted in transient_failures.
    """
    try:
        return _decode_android_image(texture, deadline, stage=stage)
    except transient_failures.ENVIRONMENT:
        transient_failures.note()
        raise


def _decode_android_image(texture, deadline, *, stage=False):
    _remaining(deadline)
    width, height = texture.m_Width, texture.m_Height
    if (not isinstance(width, int) or not isinstance(height, int)
            or isinstance(width, bool) or isinstance(height, bool)
            or not (0 < width <= _MAX_DIMENSION and 0 < height <= _MAX_DIMENSION)
            or width * height > _MAX_PIXELS):
        raise ValueError("Texture dimensions exceed the preview limit")
    if getattr(texture, "m_ImageCount", 1) != 1 or getattr(texture, "m_TextureDimension", 2) != 2:
        raise ValueError("Only ordinary 2D textures can be previewed")
    platform = getattr(getattr(texture, "object_reader", None), "platform", None)
    # Xbox 360 endian-swapped and Switch tiled data need a separate conversion.
    if platform == 11 or (platform == 38 and getattr(texture, "m_PlatformBlob", None)):
        raise ValueError("Swizzled texture previews are unavailable")

    from UnityPy.enums import TextureFormat
    name = TextureFormat(texture.m_TextureFormat).name
    raw = _RAW_FORMATS.get(name)
    astc = re.fullmatch(r"ASTC_(?:RGB|RGBA)_(4|5|6|8|10|12)x\1", name)
    crunch65 = name == "ETC2_RGBA8Crunched"
    stage_format = _STAGE_BLOCK_FORMATS.get(name) if stage else None
    if raw is None and astc is None and not crunch65 and not stage_format:
        raise ValueError(f"Texture format {name} is unavailable for Android previews")
    profile = _texture65_profile(texture) if crunch65 else None
    stream = getattr(texture, "m_StreamData", None)
    if stream and getattr(stream, "size", 0) > _MAX_SOURCE_BYTES:
        raise ValueError("Streamed texture data exceeds the preview limit")
    inline = getattr(texture, "image_data", b"")
    if inline and len(inline) > _MAX_SOURCE_BYTES:
        raise ValueError("Texture data exceeds the preview limit")
    data = texture.get_image_data()
    if len(data) > _MAX_SOURCE_BYTES:
        raise ValueError("Texture data exceeds the preview limit")

    from PIL import Image
    if raw is not None:
        mode, layout, channels = raw
        needed = width * height * channels
        if len(data) < needed:
            raise ValueError("Truncated raw texture data")
        image = Image.frombytes(mode, (width, height), bytes(data[:needed]), "raw", layout)
    elif stage_format == "etc2a8":
        image = _etc2_rgba8_image(data, width, height)
    elif stage_format:
        physical = (width, height)
        if stage_format == "etc1":
            physical = ((width + 3) // 4 * 4, (height + 3) // 4 * 4)
        elif stage_format in ("pvrtc4", "pvrtc4a"):
            if width & (width - 1) or height & (height - 1):
                raise ValueError("PVRTC stage textures must have power-of-two dimensions.")
            # The last authored levels retain PVRTC's two-block storage on
            # both axes. Crop to the logical extent before flipping Unity V.
            physical = (max(8, width), max(8, height))
        image = _stage_block_image(stage_format, data, *physical, deadline)
        if physical != (width, height):
            with image as padded:
                image = padded.crop((0, 0, width, height))
    elif crunch65:
        # Never load texture2ddecoder into the app interpreter. The trusted
        # executable validates/budgets Crunch and ETC2A in a disposable process.
        binary = os.environ.get("ELICHIKA_TEXTURE65_BIN")
        if not binary or not os.path.isfile(binary):
            raise ValueError("Bundled UnityCrunch ETC2A decoder is unavailable")
        if not _TEXTURE65_SLOT.acquire(timeout=_remaining(deadline)):
            transient_failures.note()
            raise TimeoutError("Another UnityCrunch texture is still decoding")
        try:
            with tempfile.TemporaryDirectory(prefix="webtools_texture65_") as directory:
                source = os.path.join(directory, "texture.crn")
                output = os.path.join(directory, "texture.rgba")
                with open(source, "wb") as stream:
                    stream.write(data)
                original_width, original_height, mip = profile
                command = [binary, str(original_width), str(original_height), source, output]
                if mip:
                    command += ["--mip", str(mip)]
                result = subprocess.run(command,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=min(12, _remaining(deadline)))
                if result.returncode:
                    raise ValueError("UnityCrunch ETC2A decoding failed (code " + str(result.returncode) + ")")
                needed = width * height * 4
                if os.path.islink(output) or not os.path.isfile(output) or os.path.getsize(output) != needed:
                    raise ValueError("UnityCrunch decoder returned an incorrect pixel count")
                with open(output, "rb") as stream:
                    pixels = stream.read(needed + 1)
                if len(pixels) != needed:
                    raise ValueError("UnityCrunch decoder output changed while reading")
                image = Image.frombytes("RGBA", (width, height), pixels)
        except BaseException:
            # The child may have been killed (a negative code), timed out or failed to start.
            transient_failures.note()
            raise
        finally:
            _TEXTURE65_SLOT.release()
    else:
        block = int(astc.group(1))
        needed = ((width + block - 1) // block) * ((height + block - 1) // block) * 16
        if len(data) < needed:
            raise ValueError("Truncated ASTC texture data")
        binary = os.environ.get("ASTCENC_BIN")
        if not binary or not os.path.isfile(binary):
            raise ValueError("Bundled ASTC decoder is unavailable")
        header = (b"\x13\xab\xa1\x5c" + bytes((block, block, 1))
                  + width.to_bytes(3, "little") + height.to_bytes(3, "little")
                  + b"\x01\x00\x00")
        with tempfile.TemporaryDirectory(prefix="webtools_astc_") as directory:
            source = os.path.join(directory, "texture.astc")
            # astcenc can emit a short TGA without a footer for a small mip.
            # Pillow's TGA reader seeks 26 bytes from the end when loading it.
            # Use PNG for these mips and keep the faster TGA path for 2D images.
            if min(width, height) == 1:
                from PIL.PngImagePlugin import PngImageFile as decoded_image
                output = os.path.join(directory, "texture.png")
            else:
                from PIL.TgaImagePlugin import TgaImageFile as decoded_image
                output = os.path.join(directory, "texture.tga")
            with open(source, "wb") as stream:
                stream.write(header)
                stream.write(data[:needed])  # the remaining bytes are lower mip levels
            # The CLI otherwise launches one worker per reported CPU, even for
            # a 1x1 authored mip. Thread startup then dominates a whole costume.
            # Decoding blocks is pixel-exact at every thread count; retain up
            # to four workers only for images large enough to use them.
            threads = max(1, min(4, os.cpu_count() or 1, (width * height + 8191) // 8192))
            try:
                subprocess.run([binary, "-dl", source, output, "-j", str(threads)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               timeout=_remaining(deadline))
                # Explicit readers avoid importing unrelated Pillow plugins.
                with decoded_image(output) as decoded:
                    if decoded.size != (width, height):
                        raise ValueError("ASTC decoder returned incorrect dimensions")
                    image = decoded.convert("RGBA")
            except BaseException:
                # The child may have been killed, timed out or failed to start.
                transient_failures.note()
                raise
    # UnityPy's Texture2D.image applies this same final flip by default.
    try:
        return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    finally:
        image.close()


def _android_thumbnail(bundle_path, deadline):
    ensure_repo_on_path()
    import unity_costumemod_packer as packer
    _, png = packer._extract_body_texture_core(
        bundle_path, image_decoder=lambda texture: _android_image(texture, deadline))
    _remaining(deadline)
    return png


def _packer_path():
    p = repo_root() / "unity_costumemod_packer.py"
    return str(p) if p.exists() else None


def thumbnail(bundle_path, timeout: int = 180):
    """Return PNG bytes for the body texture in `bundle_path`, or None on any
    failure (missing file, no packer, codec crash, timeout)."""
    try:
        bundle_path = os.path.realpath(os.path.expanduser(str(bundle_path)))
    except Exception:
        return None
    if not os.path.isfile(bundle_path):
        return None
    try:
        mtime = os.path.getmtime(bundle_path)
    except OSError:
        return None

    key = (bundle_path, mtime)
    if _embedded_android():
        # Serialize bounded image work to avoid several full-resolution texture
        # allocations at once when the gallery loads many cards in parallel.
        deadline = time.monotonic() + max(0, float(timeout))
        if not _ANDROID_LOCK.acquire(timeout=max(0, float(timeout))):
            return None  # a busy queue is transient; don't cache it as a bad texture
        try:
            if key in _ANDROID_CACHE:
                _ANDROID_CACHE.move_to_end(key)
                return _ANDROID_CACHE[key] or None
            data = _android_thumbnail(bundle_path, deadline)
            _remember_android_thumbnail(key, data)
            return data or None
        except Exception:
            _remember_android_thumbnail(key, None)
            return None
        finally:
            _ANDROID_LOCK.release()

    if key in _CACHE:
        return _CACHE[key] or None

    packer = _packer_path()
    if not packer:
        _CACHE[key] = b""
        return None

    fd, out_png = tempfile.mkstemp(prefix="webtools_thumb_", suffix=".png")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, packer, "--decode-worker", bundle_path, out_png],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        if proc.returncode == 0 and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
            with open(out_png, "rb") as f:
                data = f.read()
            _CACHE[key] = data
            return data
        _CACHE[key] = b""
        return None
    except Exception:
        _CACHE[key] = b""
        return None
    finally:
        try:
            os.remove(out_png)
        except OSError:
            pass
