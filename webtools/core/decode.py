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
        raise TimeoutError("Thumbnail decoding timed out")
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


def _android_image(texture, deadline):
    """Decode raw pixels or isolated ASTC/UnityCrunch ETC2A CLI results.

    Do not access Texture2D.image: unsupported formats can enter native texture
    decoders with known SIGILL failures. get_image_data() only reads bytes and
    also handles Unity's external/streamed texture storage.
    """
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
    if raw is None and astc is None and not crunch65:
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
    elif crunch65:
        # Never load texture2ddecoder into the app interpreter. The trusted
        # executable validates/budgets Crunch and ETC2A in a disposable process.
        binary = os.environ.get("ELICHIKA_TEXTURE65_BIN")
        if not binary or not os.path.isfile(binary):
            raise ValueError("Bundled UnityCrunch ETC2A decoder is unavailable")
        if not _TEXTURE65_SLOT.acquire(timeout=_remaining(deadline)):
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
            # The viewer will encode the final PNG after Unity's vertical flip.
            # A lossless TGA intermediate avoids compressing that image twice.
            output = os.path.join(directory, "texture.tga")
            with open(source, "wb") as stream:
                stream.write(header)
                stream.write(data[:needed])  # the remaining bytes are lower mip levels
            # The CLI otherwise launches one worker per reported CPU, even for
            # a 1x1 authored mip. Thread startup then dominates a whole costume.
            # Decoding blocks is pixel-exact at every thread count; retain up
            # to four workers only for images large enough to use them.
            threads = max(1, min(4, os.cpu_count() or 1, (width * height + 8191) // 8192))
            subprocess.run([binary, "-dl", source, output, "-j", str(threads)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           timeout=_remaining(deadline))
            # This output is always TGA. Generic Image.open falls back to
            # importing every Pillow plugin when TGA is not preinitialized.
            from PIL.TgaImagePlugin import TgaImageFile
            with TgaImageFile(output) as decoded:
                if decoded.size != (width, height):
                    raise ValueError("ASTC decoder returned incorrect dimensions")
                image = decoded.convert("RGBA")
    # UnityPy's Texture2D.image applies this same final flip by default.
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


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
