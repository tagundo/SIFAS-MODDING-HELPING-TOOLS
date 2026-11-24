"""Source-bound, lossless pixel editing of existing Unity Texture2D objects.

Pixel images use top-left PNG coordinates. Writing restores Unity's vertical
orientation and keeps object/material/UV identities and authored mip counts.
A baked blush saved with the opt-in "astc-keep" encoding, alone on an ASTC
texture, is the one exception to lossless RGBA32: it keeps the ASTC data and
re-encodes only the blocks it changes (texture_block_splice).
"""
import base64
import binascii
import copy
import hashlib
import io
import re
import secrets
import threading
import time
import zlib
from collections import OrderedDict

from . import model_edits, texture_blush

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
    groups = [(index, info["env"], info["objects"].values(),
               lambda obj, info=info: info["file_indices"][id(obj.assets_file)]) for info, index in inspected_sources]
    return _with_blush({"textures": rows, "originalsPreserved": True}, groups, sources)


# --- cheek blush bake --------------------------------------------------------
# A head material is BodyPartManager.headMaterial (the client's CombineFace
# material, LiveCoreMemberHead.InitializeDefault). Its _MainTex, or a suit's
# MemberAttachTable texture bound to it (CommonCoreMember.ApplyAttachData sets
# that texture as the head mainTexture at runtime), can take a baked blush.
_MEMBERS = "LLAS.Components.Members"
_PLATFORMS = {13: "android", 9: "ios"}
# Save-summary sentences (translated in webtools/i18n.py): the blush encoding
# used, and why an "astc-keep" request saved exact pixels instead.
SAVED_EXACT = ("The baked blush was saved as exact pixels (lossless RGBA32): every texel it does not change keeps "
               "its value.")
SAVED_ASTC = ("The baked blush kept the game's ASTC compression: only the blocks it touches were compressed again, "
              "and every other block keeps its original bytes.")
KEEP_PAINTED = "This texture is also painted, and painted pixels are always saved exactly, so its ASTC compression was not kept."
KEEP_NOT_ASTC = "This texture is not ASTC-compressed, so there was no ASTC compression to keep."
CHEEK_UNAVAILABLE = ("No verified stock blush pattern (cheek_array) is available. Open another costume that "
                     "contains it once (most costume bundles do) so it is kept automatically, then reopen this model.")


def _cheek_cache_file():
    from .viewer_cache import viewer_cache_root
    return viewer_cache_root() / "cheek-array" / (texture_blush.CHEEK_SHA256 + ".rgba")


def _read_cached_cheek():
    import os
    try:
        path = _cheek_cache_file()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            payload = stream.read(texture_blush.CHEEK_PAYLOAD_BYTES + 1)
    except (OSError, ValueError):
        return None
    return payload if texture_blush.verify_payload(payload) else None


def _remember_cheek(payload):
    """Keep a verified copy in the user's own viewer cache (never the repo)."""
    import os
    if not texture_blush.verify_payload(payload) or _read_cached_cheek() is not None:
        return
    try:
        path = _cheek_cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except OSError:
        pass


def _array_payload(obj):
    try:
        texture = obj.read()
        stream = getattr(texture, "m_StreamData", None)
        if stream is not None and getattr(stream, "size", 0):
            return None
        data = texture.image_data
        return bytes(data) if isinstance(data, (bytes, bytearray)) else None
    except Exception:
        return None


def _blush_scan(groups):
    """Eligible head textures and cheek array candidates; metadata reads only.

    ``groups`` holds (source index, environment, objects, file-index function).
    Returns ({(source, file, id): descriptor}, [Texture2DArray objects]).
    """
    import ntpath
    from types import SimpleNamespace
    located, by_name = {}, {}
    for index, _, objects, file_of in groups:
        for obj in objects:
            located[id(obj)] = (index, file_of(obj))
            by_name[(ntpath.basename(str(obj.assets_file.name)).casefold(), obj.path_id)] = obj

    def lookup(owner, pointer):
        if not isinstance(pointer, dict) or type(pointer.get("m_PathID")) is not int or not pointer["m_PathID"]:
            return None
        file_id = pointer.get("m_FileID", 0)
        if file_id == 0:
            return owner.assets_file.objects.get(pointer["m_PathID"])
        externals = getattr(owner.assets_file, "externals", ()) or ()
        if type(file_id) is not int or not 1 <= file_id <= len(externals):
            return None
        return by_name.get((ntpath.basename(str(externals[file_id - 1].path)).casefold(), pointer["m_PathID"]))

    def script(obj, tree):
        target = lookup(obj, tree.get("m_Script"))
        if target is None or target.type.name != "MonoScript":
            return None
        value = target.read_typetree()
        return value.get("m_ClassName"), value.get("m_Namespace")

    def child(transform, name):
        for pointer in transform.read_typetree().get("m_Children") or ():
            node = lookup(transform, pointer)
            owner = node is not None and lookup(node, node.read_typetree().get("m_GameObject"))
            if owner and owner.read_typetree().get("m_Name") == name:
                return node
        return None

    def masked(head_all):
        # CommonCoreMemberHead.GetFaceDots: headAll.transform.Find("Head_Face/mesh_facedots").
        try:
            components = head_all.read_typetree().get("m_Component") or ()
            transform = next((item for item in (lookup(head_all, row.get("component")) for row in components)
                              if item is not None and item.type.name == "Transform"), None)
            face = transform is not None and child(transform, "Head_Face")
            return bool(face and child(face, "mesh_facedots"))
        except Exception:  # an unreadable transform only drops the mask note
            return False

    rules, arrays, heads, tables = {}, [], {}, []
    for index, env, objects, _ in groups:
        scene = SimpleNamespace(env=env, tree=lambda obj: obj.read_typetree())
        for obj in objects:
            if obj.type.name == "Texture2DArray":
                arrays.append(obj)
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
                if "headMaterial" not in tree and "datas" not in tree:
                    continue
                kind = script(obj, tree)
                if kind == ("MemberAttachTable", _MEMBERS):
                    tables.append((obj, tree))
                    continue
                if kind != ("BodyPartManager", _MEMBERS):
                    continue
                material = lookup(obj, tree.get("headMaterial"))
                if material is None or material.type.name != "Material":
                    continue
                material_tree = material.read_typetree()
                from .model_viewer import _as_member_material  # only once a head is found
                if not _as_member_material(scene, material, material_tree):
                    continue
                envs = dict(material_tree.get("m_SavedProperties", {}).get("m_TexEnvs", []))
                main = lookup(material, (envs.get("_MainTex") or {}).get("m_Texture"))
                cheek = lookup(material, (envs.get("_CheekTex") or {}).get("m_Texture"))
                if cheek is not None and cheek.type.name == "Texture2DArray":
                    arrays.insert(0, cheek)
                head_all = lookup(obj, tree.get("headAll"))
                name = str(material_tree.get("m_Name") or "")
                keywords = str(material_tree.get("m_ShaderKeywords") or "").split()
                attach = tree.get("attachTable") or {}
                descriptor = {"role": "head", "material": name, "matcap": "_MATCAP_ON" in keywords,
                              "masked": head_all is not None and masked(head_all),
                              "recolourSuits": bool(isinstance(attach, dict) and attach.get("m_PathID")),
                              "platform": _PLATFORMS.get(getattr(material.assets_file, "_m_target_platform", None), "")}
                heads[name] = descriptor
                if main is not None and main.type.name == "Texture2D" and id(main) in located:
                    source, file_index = located[id(main)]
                    rules[(source, file_index, str(main.path_id))] = descriptor
            except Exception:
                # UnityPy raises many kinds of errors (TypeTreeError, struct.error,
                # EOFError, ...) for a malformed MonoBehaviour. Skipping it only
                # removes a blush offer; the texture tools keep working.
                continue
    for obj, tree in tables:
        try:
            _attach_rules(obj, tree, lookup, located, heads, rules)
        except Exception:  # as above: an unreadable table offers nothing
            continue
    return rules, arrays


def _attach_rules(obj, tree, lookup, located, heads, rules):
    # CommonCoreMember.ApplyAttachData: only attachType 1 (MaterialColor);
    # a Texture2D becomes the mainTexture of the material named replaceBindName.
    for data in tree.get("datas") or ():
        if not isinstance(data, dict) or data.get("attachType") != 1:
            continue
        for item in data.get("replaceObjects") or ():
            name = item.get("replaceBindName") if isinstance(item, dict) else None
            target = lookup(obj, item.get("replaceObject")) if isinstance(name, str) and name else None
            if target is None or target.type.name != "Texture2D" or id(target) not in located:
                continue
            if name not in heads and not name.endswith("_head"):
                continue
            head = heads.get(name, {})
            source, file_index = located[id(target)]
            rules.setdefault((source, file_index, str(target.path_id)), {
                "role": "attach", "material": name, "attachKey": str(data.get("attachName") or ""),
                "verifiedHead": name in heads, "matcap": head.get("matcap", False), "masked": head.get("masked", False),
                "recolourSuits": False,
                "platform": _PLATFORMS.get(getattr(target.assets_file, "_m_target_platform", None), "")})


def _resolve_cheek(arrays, source_names):
    """(payload, public info): the bundle's own verified array, else the cache."""
    for obj in arrays:
        payload = _array_payload(obj)
        if payload is not None and texture_blush.verify_payload(payload):
            _remember_cheek(payload)
            return payload, {"available": True, "source": "bundle", "sourceName": source_names.get(id(obj), ""),
                             "sha256": texture_blush.CHEEK_SHA256, "reason": ""}
    payload = _read_cached_cheek()
    if payload is not None:
        return payload, {"available": True, "source": "cache", "sourceName": "",
                         "sha256": texture_blush.CHEEK_SHA256, "reason": ""}
    return None, {"available": False, "source": "", "sourceName": "", "sha256": "", "reason": CHEEK_UNAVAILABLE}


def _safe_scan(groups):
    """_blush_scan that can only remove the blush offer, never the catalogue."""
    try:
        return _blush_scan(groups)
    except Exception:
        return {}, []


def _with_blush(catalogue, groups, sources):
    rules, arrays = _safe_scan(groups)
    names = {}
    for index, _, objects, _ in groups:
        for obj in objects:
            if obj.type.name == "Texture2DArray":
                names[id(obj)] = sources[index]["name"]
    cheek = None
    if rules:
        _, cheek = _resolve_cheek(arrays, names)
    for row in catalogue["textures"]:
        identity = row["texture"]
        rule = rules.get((identity["source"], identity["file"], identity["id"]))
        if rule is not None and row["available"]:
            row["blush"] = copy.deepcopy(rule)
    catalogue["blush"] = {"cheek": cheek or {"available": False, "source": "", "sourceName": "", "sha256": "", "reason": ""},
                          "levels": [{"id": name, "k": k} for name, k in texture_blush.LEVELS],
                          "defaultLevel": texture_blush.DEFAULT_LEVEL, "defaultLayer": texture_blush.DEFAULT_LAYER,
                          "layers": list(texture_blush.LAYERS), "maxK": texture_blush.MAX_K}
    return catalogue


def _session_groups(session):
    from .viewer_mesh_tools import _objects
    groups = []
    for index, source in enumerate(session["sources"]):
        env, files, objects = _objects(source["raw"])
        groups.append((index, env, list(objects.values()), lambda obj, files=files: files[id(obj.assets_file)]))
    return groups


def cheek_payload(session):
    """The verified 524288-byte array for this session, or a TextureToolError."""
    payload = session.get("cheekPayload")
    if payload is None or not texture_blush.verify_payload(payload):
        # Every verified array is the same bytes (CHEEK_SHA256), and opening a
        # bundle that holds one keeps a copy in the cache (_resolve_cheek), so
        # the bundle is scanned again only when no verified copy is cached.
        payload = _read_cached_cheek()
        if payload is None:
            _, arrays = _safe_scan(_session_groups(session))
            payload, info = _resolve_cheek(arrays, {})
            if payload is None:
                _fail(info["reason"])
        session["cheekPayload"] = payload
    return payload


def checked_blush(value):
    """Canonical recipe operation: {"layer": 0 | 1, "k": strength, "encoding": "exact" | "astc-keep"}.

    A row without ``encoding`` (written before the field existed) is "exact":
    lossless RGBA32, the default. "astc-keep" keeps an ASTC texture's
    compression and re-encodes only the blocks the bake touches
    (texture_blush.ENCODINGS). Same rule as texture-blush.js checkedOperation.
    """
    if not isinstance(value, dict) or not {"layer", "k"} <= set(value) or not set(value) <= {"layer", "k", "encoding"}:
        _fail("The blush bake takes only a blush type, a strength and a save mode.")
    try:
        return {"layer": texture_blush.checked_layer(value["layer"]), "k": texture_blush.checked_k(value["k"]),
                "encoding": texture_blush.checked_encoding(value.get("encoding", texture_blush.DEFAULT_ENCODING))}
    except texture_blush.BlushError as error:
        raise TextureToolError(str(error)) from error


def cheek(token):
    """Both stock layers (Unity row order) for the editor's preview and swatches."""
    session = _session(token)
    catalogue = _catalog(session)
    if not any("blush" in row for row in catalogue["textures"]):
        _fail("This model has no head texture that can take a baked blush.")
    cached = session.get("cheekPreview")
    if cached is None:
        payload = cheek_payload(session)
        cached = {"width": texture_blush.CHEEK_SIZE, "height": texture_blush.CHEEK_SIZE * texture_blush.CHEEK_LAYERS,
                  "rowOrder": "unity", "layers": texture_blush.CHEEK_LAYERS, "sha256": texture_blush.CHEEK_SHA256,
                  "source": catalogue.get("blush", {}).get("cheek", {}).get("source", ""),
                  "rgbaZlib": base64.b64encode(zlib.compress(payload, 6)).decode("ascii")}
        session["cheekPreview"] = cached
    return copy.deepcopy(cached)


def _session(token):
    with model_edits._LOCK:
        return model_edits._session(token)


def _catalog(session):
    if "textures" not in session:
        from .viewer_mesh_tools import _objects
        rows, groups = [], []
        for index, source in enumerate(session["sources"]):
            env, files, objects = _objects(source["raw"])
            groups.append((index, env, list(objects.values()), lambda obj, files=files: files[id(obj.assets_file)]))
            for (file_index, _), obj in objects.items():
                if obj.type.name == "Texture2D":
                    rows.append(_record(obj, index, file_index, source["name"], source["sha256"],
                                        index in session.get("outlineOnlySources", set())))
                    if len(rows) > MAX_TEXTURES:
                        _fail("The selected model has too many textures for pixel editing.")
        session["textures"] = _with_blush({"textures": rows, "originalsPreserved": True}, groups, session["sources"])
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
        if (not isinstance(operation, dict) or not {"texture", "sourceSha256", "png", "kind"} <= set(operation)
                or not set(operation) <= {"texture", "sourceSha256", "png", "kind", "blush"}):
            _fail("Unsupported texture edit property.")
        row = _identity(operation["texture"], session)
        identity = operation["texture"]
        key = (identity["source"], identity["file"], identity["id"])
        if key in seen:
            _fail("The same texture occurs more than once in the edit recipe.")
        seen.add(key)
        if not isinstance(operation["sourceSha256"], str) or not _SHA.fullmatch(operation["sourceSha256"]) or operation["sourceSha256"] != row["sourceSha256"]:
            _fail("The texture edit belongs to different original model bytes.")
        if operation["kind"] not in ("costume", "skin", "paint", "blush"):
            _fail("Choose a supported texture edit mode.")
        if "blush" in operation or operation["kind"] == "blush":
            operation = dict(operation, blush=checked_blush(operation.get("blush")))
            if "blush" not in row:
                _fail("Baked blush is available only for a head material's main texture or its recolour texture.")
            cheek_payload(session)
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


def _splice_blush(obj, original, levels, before, layer, bounds, blush, block, deadline):
    """The opt-in "astc-keep" save: bake every authored ASTC level and
    re-encode only the touched blocks.

    The texture keeps its format, size and mip count. Each level's blocks
    without a changed texel keep their original bytes; the others are encoded
    again from the exact bake, so their texels (also those the rule leaves
    alone) approximate it. Every spliced level is decoded again and must keep
    every texel outside those blocks and every alpha value.
    """
    from types import SimpleNamespace
    from PIL import Image
    from . import decode, texture_block_splice as splice
    width, height = int(original.m_Width), int(original.m_Height)
    layout = splice.level_layout(width, height, len(levels), block)
    data = bytes(original.get_image_data())
    if len(data) < layout[-1][2] + layout[-1][3]:
        raise splice.SpliceUnavailable("The original ASTC data is shorter than its mip chain.")
    out = bytearray(data)
    changed_counts, block_counts, off_bake, collateral, worst, means, base = [], [], 0, 0, [], [], None
    for level, (source, (w, h, offset, size)) in enumerate(zip(levels, layout)):
        authored = before if level == 0 else decode._android_image(source, deadline).convert("RGBA")
        try:
            if authored.size != (w, h):
                _fail("An original mip has invalid image dimensions.")
            pixels = authored.tobytes()
            baked, changed, box = texture_blush.bake_rgba(pixels, w, h, layer, blush["k"], bounds)
            blocks = splice.touched_blocks(pixels, baked, w, h, block, box)
            changed_counts.append(changed)
            block_counts.append(len(blocks))
            if not blocks:
                worst.append(0)
                means.append(0.0)
                if level == 0:
                    base = pixels
                continue
            with Image.frombytes("RGBA", (w, h), baked) as baked_image:
                spliced = splice.splice_level(data[offset:offset + size], w, h, block, baked_image, blocks, deadline)
            proxy = SimpleNamespace(m_Width=w, m_Height=h, m_TextureFormat=original.m_TextureFormat, m_MipCount=1,
                                    m_ImageCount=1, m_TextureDimension=2, m_StreamData=None, image_data=spliced,
                                    object_reader=getattr(original, "object_reader", None),
                                    get_image_data=lambda value=spliced: value)
            with decode._android_image(proxy, deadline) as decoded, decoded.convert("RGBA") as rgba:
                after = rgba.tobytes()
            stats = splice.check_level(pixels, baked, after, w, h, block, blocks)
            off_bake += stats["texelsOffBake"]
            collateral += stats["untouchedTexelsChanged"]
            worst.append(stats["maxChannelError"])
            means.append(stats["meanChannelError"])
            out[offset:offset + size] = spliced
            if level == 0:
                base = after
        finally:
            if authored is not before:
                authored.close()
    if not any(changed_counts):
        return None
    payload = bytes(out)
    tree = copy.deepcopy(obj.read_typetree())
    tree["image data"] = payload
    tree["m_CompleteImageSize"] = len(payload)
    if "m_StreamData" in tree:
        tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
    obj.save_typetree(tree)
    name = _format(int(tree["m_TextureFormat"]))
    return {"name": str(tree.get("m_Name") or "Texture"), "width": width, "height": height,
            "mipCount": len(levels), "sourceFormat": name, "resultFormat": name, "encodingChanged": False,
            "encodingReason": SAVED_ASTC,
            # Texels inside the re-encoded blocks approximate the bake, so some
            # the rule leaves alone change as well (untouchedTexelsChanged).
            "unchangedPixelsPreserved": collateral == 0, "alphaChanged": False,
            "blush": {"layer": blush["layer"], "k": blush["k"], "changedTexels": changed_counts,
                      "requested": blush["encoding"], "encoding": "astc-keep", "note": SAVED_ASTC,
                      "reencodedBlocks": block_counts, "texelsOffBake": off_bake, "untouchedTexelsChanged": collateral,
                      "maxChannelError": worst, "meanChannelError": means},
            "payloadSha256": hashlib.sha256(payload).hexdigest(), "baseSha256": hashlib.sha256(base).hexdigest()}


def _write(obj, edited, blush=None, cheek=None):
    """Write one edited texture with its authored mip count.

    Painted texels propagate into the authored mips through their binary
    footprint; every other authored mip texel is kept. A blush bake is not a
    pixel edit: the shader rule is applied to each level in place, at each mip
    texel's own UV centre, after the paint, so mips are never regenerated and
    only texels whose rounded RGB changes are touched (alpha never).

    Everything is saved as lossless RGBA32 by default, so every texel the
    edit leaves alone keeps its decoded value and every baked texel is
    exactly the shader result (blush encoding "exact"). Only a bake that asks
    for "astc-keep", alone on an ASTC texture, keeps the ASTC format and
    re-encodes the blocks holding changed texels (_splice_blush); paint on the
    same texture, a non-ASTC source or an encoder failure saves exact pixels
    instead, and the summary says why.
    """
    from PIL import Image
    from . import decode, texture_block_splice
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
    painted = mask.getbbox() is not None
    if not painted and blush is None:
        before.close()
        return None
    layer = texture_blush.layer_bytes(cheek, blush["layer"]) if blush is not None else None
    bounds = texture_blush.layer_bounds(layer) if layer is not None else None
    fallback = ""
    block = texture_block_splice.astc_block(_format(int(getattr(original, "m_TextureFormat", 0))))
    try:
        if blush is not None and blush.get("encoding") == "astc-keep":
            if painted:
                fallback = KEEP_PAINTED
            elif not block:
                fallback = KEEP_NOT_ASTC
            else:
                try:
                    return _splice_blush(obj, original, levels, before, layer, bounds, blush, block, deadline)
                except texture_block_splice.SpliceUnavailable as error:
                    fallback = str(error)
                    deadline = time.monotonic() + 60
    finally:
        before.close()
    width, height = edited.size
    payload = bytearray()
    footprint = mask
    alpha_footprint = alpha_mask
    baked = []
    for level, source in enumerate(levels):
        size = (max(1, width >> level), max(1, height >> level))
        if level == 0:
            image = edited
        else:
            authored = decode._android_image(source, deadline).convert("RGBA")
            if authored.size != size:
                _fail("An original mip has invalid image dimensions.")
            if painted:
                # Preserve every authored mip texel whose source footprint was not
                # changed. Binary propagation at each halving retains tiny strokes.
                footprint = footprint.resize(size, Image.Resampling.BOX).point(lambda value: 255 if value else 0)
                alpha_footprint = alpha_footprint.resize(size, Image.Resampling.BOX).point(lambda value: 255 if value else 0)
                updated = edited.resize(size, Image.Resampling.BOX)
                updated.putalpha(Image.composite(updated.getchannel("A"), authored.getchannel("A"), alpha_footprint))
                image = Image.composite(updated, authored, footprint)
                authored.close(); updated.close()
            else:
                image = authored
        if layer is not None:
            data, changed, _ = texture_blush.bake_rgba(image.tobytes(), image.width, image.height, layer, blush["k"], bounds)
            baked.append(changed)
            if changed:
                if level:
                    image.close()
                image = Image.frombytes("RGBA", image.size, data)
        payload.extend(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
        if image is not edited:
            image.close()
    if not painted and not any(baked):
        return None
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
    result = {"name": str(tree.get("m_Name") or "Texture"), "width": width, "height": height,
              "mipCount": count, "sourceFormat": _format(source_format), "resultFormat": "RGBA32",
              "encodingChanged": source_format != 4,
              "encodingReason": ("Lossless original-format encoding is unavailable; RGBA32 preserves unselected pixels and alpha."
                                 if source_format != 4 else "Lossless RGBA32 pixels retained."),
              "unchangedPixelsPreserved": True, "alphaChanged": alpha_changed,
              "payloadSha256": hashlib.sha256(payload).hexdigest()}
    if blush is not None:
        result["blush"] = {"layer": blush["layer"], "k": blush["k"], "changedTexels": baked,
                           "requested": blush.get("encoding", texture_blush.DEFAULT_ENCODING), "encoding": "exact",
                           "note": SAVED_EXACT}
        if source_format != 4:
            result["encodingReason"] = SAVED_EXACT
        if fallback:
            result["blush"]["fallback"] = fallback
            result["encodingReason"] = fallback + " " + SAVED_EXACT
    return result


def apply_edits(raw, source_index, operations, catalogue, cheek=None):
    """Apply validated final PNGs to existing objects in a fresh Unity source.

    ``cheek`` is the verified cheek_array payload, required by blush bakes.
    """
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
        blush = operation.get("blush")
        if blush is not None and not texture_blush.verify_payload(cheek):
            _fail(CHEEK_UNAVAILABLE)
        _, image = _png(operation["png"], row)
        try:
            change = _write(obj, image, blush, cheek)
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
    # identity and the exact edited base-level RGBA, including transparent RGB,
    # and that every written mip level survived byte for byte.
    _, _, reloaded = _objects(result)
    written = {(row["texture"]["file"], row["texture"]["id"]): row for row in changes}
    for operation in selected:
        identity = operation["texture"]
        obj = reloaded.get((identity["file"], identity["id"]))
        if obj is None or obj.type.name != "Texture2D":
            _fail("The saved texture failed its original-identity reload check.")
        row = entries[(identity["source"], identity["file"], identity["id"])]
        key = (identity["file"], identity["id"])
        change = written.get(key)
        texture = obj.read()
        actual = decode._android_image(texture, time.monotonic() + 60).convert("RGBA")
        try:
            if change is not None and change.get("baseSha256"):
                # Re-encoded ASTC blocks approximate the bake; the decoded base
                # level must be the one verified while splicing.
                if hashlib.sha256(actual.tobytes()).hexdigest() != change["baseSha256"]:
                    _fail("The saved texture pixels failed exact reload validation.")
            else:
                _, expected = _png(operation["png"], row)
                if operation.get("blush") is not None:
                    baked, _ = texture_blush.bake_image(expected, texture_blush.layer_bytes(cheek, operation["blush"]["layer"]),
                                                        operation["blush"]["k"])
                    expected.close()
                    expected = baked
                try:
                    if actual.size != expected.size or actual.tobytes() != expected.tobytes():
                        _fail("The saved texture pixels failed exact reload validation.")
                finally:
                    expected.close()
            if change is not None and hashlib.sha256(bytes(texture.get_image_data())).hexdigest() != change["payloadSha256"]:
                _fail("The saved texture mip levels failed exact reload validation.")
        finally:
            actual.close()
    for row in changes:
        row.pop("payloadSha256", None)
        row.pop("baseSha256", None)
    return result, changes
