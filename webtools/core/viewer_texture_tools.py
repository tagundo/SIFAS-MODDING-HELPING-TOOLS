"""Source-bound, lossless pixel editing of existing Unity Texture2D objects.

Pixel images use top-left PNG coordinates. Writing restores Unity's vertical
orientation and keeps object/material/UV identities and authored mip counts.
"""
import base64
import binascii
import copy
import hashlib
import io
import re
import threading
import time
import zlib
from collections import OrderedDict

from . import model_edits

MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_TOTAL_PNG_BYTES = 12 * 1024 * 1024
MAX_TEXTURE_PIXELS = 16 * 1024 * 1024
MAX_TOTAL_PIXELS = 32 * 1024 * 1024
MAX_TEXTURES = 128
MAX_STATE_BYTES = 18 * 1024 * 1024
_DATA_SLOT = threading.BoundedSemaphore(1)
_PNG_PREFIX = "data:image/png;base64,"
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class TextureToolError(ValueError):
    pass


def _fail(message):
    raise TextureToolError(message)


def _format(value):
    try:
        from UnityPy.enums import TextureFormat
        return TextureFormat(value).name
    except (TypeError, ValueError):
        return str(value)


def _record(obj, source, file_index, source_name, source_hash, automatic=False):
    tree = obj.read_typetree()
    width, height = int(tree.get("m_Width", 0)), int(tree.get("m_Height", 0))
    count = int(tree.get("m_MipCount", 1) or 1)
    reason = ""
    if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > MAX_TEXTURE_PIXELS:
        reason = "This texture exceeds the supported 16-megapixel editing limit."
    elif int(tree.get("m_ImageCount", 1) or 1) != 1 or int(tree.get("m_TextureDimension", 2)) != 2:
        reason = "Only individual two-dimensional textures can be edited."
    elif not 1 <= count <= max(width, height).bit_length():
        reason = "The original texture has an unsupported mip chain."
    elif tree.get("m_PlatformBlob"):
        reason = "This platform-specific texture layout cannot be edited safely."
    return {"texture": {"source": source, "file": file_index, "id": str(obj.path_id)},
            "name": str(tree.get("m_Name") or "Texture"), "sourceName": source_name,
            "sourceSha256": source_hash, "width": width, "height": height,
            "format": _format(tree.get("m_TextureFormat")), "mipCount": count,
            "available": not reason, "reason": reason, "automaticFace": bool(automatic)}


def catalogue_sources(inspected_sources, sources, automatic=()):
    """Use an existing metadata inspection, never decoding texture pixels."""
    rows = []
    for info, index in inspected_sources:
        source = sources[index]
        for (file_index, _), obj in info["objects"].items():
            if obj.type.name == "Texture2D":
                rows.append(_record(obj, index, file_index, source["name"], source["sha256"], index in automatic))
                if len(rows) > MAX_TEXTURES:
                    _fail("The selected model has too many textures for pixel editing.")
    return {"textures": rows, "originalsPreserved": True}


def _session(token):
    with model_edits._LOCK:
        return model_edits._session(token)


def _catalog(session):
    if "textures" not in session:
        from .viewer_mesh_tools import _objects
        rows = []
        for index, source in enumerate(session["sources"]):
            _, _, objects = _objects(source["raw"])
            for (file_index, _), obj in objects.items():
                if obj.type.name == "Texture2D":
                    rows.append(_record(obj, index, file_index, source["name"], source["sha256"],
                                        index in session.get("outlineOnlySources", set())))
                    if len(rows) > MAX_TEXTURES:
                        _fail("The selected model has too many textures for pixel editing.")
        session["textures"] = {"textures": rows, "originalsPreserved": True}
    return session["textures"]


def inspect(token):
    return copy.deepcopy(_catalog(_session(token)))


def _identity(value, session):
    if (not isinstance(value, dict) or set(value) != {"source", "file", "id"}
            or type(value["source"]) is not int or not 0 <= value["source"] < len(session["sources"])
            or type(value["file"]) is not int or not 0 <= value["file"] <= 1024
            or not isinstance(value["id"], str) or not re.fullmatch(r"-?[0-9]{1,20}", value["id"])
            or not -(2 ** 63) <= int(value["id"]) < 2 ** 63 or str(int(value["id"])) != value["id"]):
        _fail("Choose a texture from this original model.")
    matches = [row for row in _catalog(session)["textures"] if row["texture"] == value]
    if len(matches) != 1:
        _fail("The texture is outside this original model.")
    if not matches[0]["available"]:
        _fail(matches[0]["reason"])
    return matches[0]


def _source_object(session, identity, raw=None):
    from .viewer_mesh_tools import _objects
    env, _, objects = _objects(session["sources"][identity["source"]]["raw"] if raw is None else raw)
    obj = objects.get((identity["file"], identity["id"]))
    if obj is None or obj.type.name != "Texture2D":
        _fail("The original texture identity is no longer available.")
    return env, obj


def data(token, texture):
    session = _session(token)
    row = _identity(texture, session)
    key = (texture["source"], texture["file"], texture["id"])
    cache = session.setdefault("texturePreviewCache", OrderedDict())
    if key in cache:
        cache.move_to_end(key)
        return {**copy.deepcopy(row), **cache[key]}
    if not _DATA_SLOT.acquire(blocking=False):
        _fail("Another texture is being prepared. Try again after it finishes.")
    try:
        from . import decode
        _, obj = _source_object(session, texture)
        image = decode._android_image(obj.read(), time.monotonic() + 60).convert("RGBA")
        if image.size != (row["width"], row["height"]):
            _fail("The texture decoder returned unexpected image dimensions.")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        raw = stream.getvalue()
        if not 0 < len(raw) <= MAX_PNG_BYTES:
            _fail("The decoded texture exceeds the supported PNG size limit.")
        decoded = {"image": _PNG_PREFIX + base64.b64encode(raw).decode("ascii"),
                   "rgbaZlib": base64.b64encode(zlib.compress(image.tobytes(), 3)).decode("ascii")}
        image.close()
        cache[key] = decoded
        while len(cache) > 4 or sum(sum(len(part) for part in value.values()) for value in cache.values()) > 12 * 1024 * 1024:
            cache.popitem(last=False)
        return {**copy.deepcopy(row), **decoded}
    except TextureToolError:
        raise
    except Exception as error:
        raise TextureToolError("This texture could not be decoded: " + str(error)) from error
    finally:
        _DATA_SLOT.release()


def decode(token, texture, png):
    """Decode an imported/restored PNG without Canvas premultiplication."""
    session = _session(token)
    row = _identity(texture, session)
    if not _DATA_SLOT.acquire(blocking=False):
        _fail("Another texture is being prepared. Try again after it finishes.")
    try:
        _, image = _png(png, row)
        try:
            compressed = base64.b64encode(zlib.compress(image.tobytes(), 3)).decode("ascii")
        finally:
            image.close()
        return {**copy.deepcopy(row), "image": png, "rgbaZlib": compressed}
    finally:
        _DATA_SLOT.release()


def decode_image(png):
    """Decode a standalone PNG into bounded, unpremultiplied RGBA pixels."""
    from PIL import Image, UnidentifiedImageError
    if (not isinstance(png, str) or not png.startswith(_PNG_PREFIX)
            or len(png) > len(_PNG_PREFIX) + ((MAX_PNG_BYTES + 2) // 3) * 4):
        _fail("Choose a PNG image within the 8 MiB texture limit.")
    try:
        raw = base64.b64decode(png[len(_PNG_PREFIX):], validate=True)
    except (ValueError, binascii.Error) as error:
        raise TextureToolError("The texture PNG encoding is invalid.") from error
    if not 0 < len(raw) <= MAX_PNG_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        _fail("The texture edit must contain a bounded PNG image.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            width, height = probe.size
            if (probe.format != "PNG" or not 0 < width <= 8192 or not 0 < height <= 8192
                    or width * height > MAX_TEXTURE_PIXELS or getattr(probe, "n_frames", 1) != 1):
                _fail("Choose a single PNG within the 16-megapixel texture limit.")
    except TextureToolError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise TextureToolError("The texture PNG is damaged or unsupported.") from error
    if not _DATA_SLOT.acquire(blocking=False):
        _fail("Another texture is being prepared. Try again after it finishes.")
    try:
        _, image = _png(png, {"width": width, "height": height})
        try:
            compressed = base64.b64encode(zlib.compress(image.tobytes(), 3)).decode("ascii")
        finally:
            image.close()
        return {"width": width, "height": height, "image": png, "rgbaZlib": compressed}
    finally:
        _DATA_SLOT.release()


def _png(value, row, *, load=True):
    from PIL import Image, UnidentifiedImageError
    if (not isinstance(value, str) or not value.startswith(_PNG_PREFIX)
            or len(value) > len(_PNG_PREFIX) + ((MAX_PNG_BYTES + 2) // 3) * 4):
        _fail("Choose a PNG image within the 8 MiB texture limit.")
    try:
        raw = base64.b64decode(value[len(_PNG_PREFIX):], validate=True)
    except (ValueError, binascii.Error) as error:
        raise TextureToolError("The texture PNG encoding is invalid.") from error
    if not 0 < len(raw) <= MAX_PNG_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        _fail("The texture edit must contain a bounded PNG image.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format != "PNG" or probe.size != (row["width"], row["height"]) or getattr(probe, "n_frames", 1) != 1:
                _fail("The edited PNG dimensions must match the original texture exactly.")
            probe.verify()
        if not load:
            return raw, None
        with Image.open(io.BytesIO(raw)) as probe:
            probe.load()
            image = probe.convert("RGBA")
        return raw, image
    except TextureToolError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise TextureToolError("The texture PNG is damaged or unsupported.") from error


def validate(session, operations):
    if not isinstance(operations, list) or len(operations) > MAX_TEXTURES:
        _fail("Invalid texture edit list.")
    out, seen, total, pixels = [], set(), 0, 0
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"texture", "sourceSha256", "png", "kind"}:
            _fail("Unsupported texture edit property.")
        row = _identity(operation["texture"], session)
        identity = operation["texture"]
        key = (identity["source"], identity["file"], identity["id"])
        if key in seen:
            _fail("The same texture occurs more than once in the edit recipe.")
        seen.add(key)
        if not isinstance(operation["sourceSha256"], str) or not _SHA.fullmatch(operation["sourceSha256"]) or operation["sourceSha256"] != row["sourceSha256"]:
            _fail("The texture edit belongs to different original model bytes.")
        if operation["kind"] not in ("costume", "skin", "paint"):
            _fail("Choose a supported texture edit mode.")
        raw, image = _png(operation["png"], row)
        image.close()
        total += len(raw); pixels += row["width"] * row["height"]
        if total > MAX_TOTAL_PNG_BYTES or pixels > MAX_TOTAL_PIXELS:
            _fail("The selected texture edits exceed the 12 MiB PNG or 32-megapixel total limit.")
        out.append(copy.deepcopy(operation))
    return sorted(out, key=lambda value: (value["texture"]["source"], value["texture"]["file"], int(value["texture"]["id"])))


def _change_mask(before, after):
    from PIL import ImageChops
    difference = ImageChops.difference(before, after)
    mask = difference.getchannel("R")
    for channel in ("G", "B", "A"):
        mask = ImageChops.lighter(mask, difference.getchannel(channel))
    alpha_mask = difference.getchannel("A").point(lambda value: 255 if value else 0)
    difference.close()
    return mask.point(lambda value: 255 if value else 0), alpha_mask


def _write(obj, edited):
    from PIL import Image, ImageChops
    from . import decode
    from .model_materials import _original_mips
    original = obj.read()
    count = int(getattr(original, "m_MipCount", 1) or 1)
    levels = [original] + [proxy.read() for proxy in _original_mips(obj, original)]
    if len(levels) != count:
        _fail("The complete original mip chain is unavailable for precise texture editing.")
    deadline = time.monotonic() + 60
    before = decode._android_image(original, deadline).convert("RGBA")
    mask, alpha_mask = _change_mask(before, edited)
    alpha_changed = alpha_mask.getbbox() is not None
    before.close()
    if mask.getbbox() is None:
        return None
    width, height = edited.size
    payload = bytearray()
    footprint = mask
    alpha_footprint = alpha_mask
    for level, source in enumerate(levels):
        size = (max(1, width >> level), max(1, height >> level))
        if level == 0:
            image = edited
        else:
            # Preserve every authored mip texel whose source footprint was not
            # changed. Binary propagation at each halving retains tiny strokes.
            footprint = footprint.resize(size, Image.Resampling.BOX).point(lambda value: 255 if value else 0)
            alpha_footprint = alpha_footprint.resize(size, Image.Resampling.BOX).point(lambda value: 255 if value else 0)
            authored = decode._android_image(source, deadline).convert("RGBA")
            if authored.size != size:
                _fail("An original mip has invalid image dimensions.")
            updated = edited.resize(size, Image.Resampling.BOX)
            updated.putalpha(Image.composite(updated.getchannel("A"), authored.getchannel("A"), alpha_footprint))
            image = Image.composite(updated, authored, footprint)
            authored.close(); updated.close()
        payload.extend(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
        if level:
            image.close()
    tree = copy.deepcopy(obj.read_typetree())
    source_format = int(tree["m_TextureFormat"])
    tree["m_TextureFormat"] = 4  # lossless RGBA32 is supported by both game clients
    tree["m_CompleteImageSize"] = len(payload)
    tree["m_MipCount"] = count
    if "m_MipMap" in tree:
        tree["m_MipMap"] = count > 1
    tree["image data"] = bytes(payload)
    if "m_StreamData" in tree:
        tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
    if "m_StreamingMipmaps" in tree:
        tree["m_StreamingMipmaps"] = False
    obj.save_typetree(tree)
    return {"name": str(tree.get("m_Name") or "Texture"), "width": width, "height": height,
            "mipCount": count, "sourceFormat": _format(source_format), "resultFormat": "RGBA32",
            "encodingChanged": source_format != 4,
            "encodingReason": ("Lossless original-format encoding is unavailable; RGBA32 preserves unselected pixels and alpha."
                               if source_format != 4 else "Lossless RGBA32 pixels retained."),
            "unchangedPixelsPreserved": True, "alphaChanged": alpha_changed}


def apply_edits(raw, source_index, operations, catalogue):
    """Apply validated final PNGs to existing objects in a fresh Unity source."""
    selected = [row for row in operations if row["texture"]["source"] == source_index]
    if not selected:
        return raw, []
    from .viewer_mesh_tools import _objects
    from . import decode
    env, _, objects = _objects(raw)
    entries = {tuple(row["texture"][key] for key in ("source", "file", "id")): row for row in catalogue["textures"]}
    changes = []
    for operation in selected:
        identity = operation["texture"]
        row = entries.get((identity["source"], identity["file"], identity["id"]))
        obj = objects.get((identity["file"], identity["id"]))
        if row is None or obj is None or obj.type.name != "Texture2D":
            _fail("An edited texture no longer belongs to its original model.")
        _, image = _png(operation["png"], row)
        try:
            change = _write(obj, image)
        finally:
            image.close()
        if change is not None:
            changes.append({"texture": dict(identity), "kind": operation["kind"], **change})
    if not changes:
        return raw, []
    try:
        result = env.file.save(packer="original")
    except TypeError:
        result = env.file.save()
    if len(result) > model_edits.MAX_SOURCE_BYTES:
        _fail("The lossless edited model exceeds the supported model size. Edit fewer textures in one model.")
    # Reload emitted native bytes and prove every selected object retains its
    # identity and the exact edited base-level RGBA, including transparent RGB.
    _, _, reloaded = _objects(result)
    for operation in selected:
        identity = operation["texture"]
        obj = reloaded.get((identity["file"], identity["id"]))
        if obj is None or obj.type.name != "Texture2D":
            _fail("The saved texture failed its original-identity reload check.")
        row = entries[(identity["source"], identity["file"], identity["id"])]
        _, expected = _png(operation["png"], row)
        actual = decode._android_image(obj.read(), time.monotonic() + 60).convert("RGBA")
        try:
            if actual.size != expected.size or actual.tobytes() != expected.tobytes():
                _fail("The saved texture pixels failed exact reload validation.")
        finally:
            actual.close(); expected.close()
    return result, changes
