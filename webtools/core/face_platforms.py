"""Recognize standalone faces and copy a proven mobile-compatible payload."""
from pathlib import PurePosixPath
import struct
import time

from . import model_platforms

_NATIVE = {model_platforms.ANDROID, model_platforms.IOS}
_MAX_BYTES = 16 * 1024 * 1024
_MAX_UNPACKED_BYTES = 64 * 1024 * 1024
_RAW_TEXTURES = {"Alpha8", "RGB24", "RGBA32", "ARGB32", "BGRA32", "RGB565", "RGBA4444"}
_FACE_OBJECTS = {
    "Animation", "AnimationClip", "Animator", "AssetBundle", "Avatar", "GameObject",
    "Material", "Mesh", "MeshFilter", "MeshRenderer", "MonoBehaviour", "MonoScript",
    "RectTransform", "SkinnedMeshRenderer", "Texture2D", "Transform",
}


def face_owner(scene):
    """Identify a standalone facial companion from its rendered objects."""
    from . import model_faces, model_viewer

    owners, dynamic = model_faces._names(scene)
    if len(owners) != 1 or model_faces.has_body(scene):
        return None

    found = False
    for renderer, tree, game_object in scene.renderers:
        if not tree.get("m_Enabled", True) or not scene.active(game_object):
            continue
        mesh = model_faces._mesh(scene, renderer, tree, game_object)
        if mesh is None or not model_faces.renderer_role(
                scene, renderer, game_object, mesh, model_viewer._source_path(renderer) in dynamic):
            return None
        found = True
    return next(iter(owners)) if found else None


def is_face(scene, owner=None):
    identified = face_owner(scene)
    return identified is not None and (owner is None or owner == identified)


def _bundle(raw):
    import UnityPy
    from UnityPy.files import BundleFile
    from .model_viewer import _bounded_bundle, _preflight_bundle

    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_BYTES or not raw.startswith(b"UnityFS\0"):
        raise ValueError("Choose a standalone UnityFS facial bundle.")
    size, layout = _preflight_bundle(raw, _with_layout=True)
    if size > _MAX_UNPACKED_BYTES:
        raise ValueError("The expanded face bundle exceeds the platform copy limit.")
    env = UnityPy.load(_bounded_bundle(raw, layout, time.monotonic() + 15))
    bundle = env.file
    if (len(env.files) != 1 or not isinstance(bundle, BundleFile) or bundle.signature != "UnityFS"
            or bundle.decryptor is not None):
        raise ValueError("The facial bundle uses an unsupported Unity container.")
    return bundle


def _snapshot(bundle):
    from UnityPy.files import BundleFile, SerializedFile
    from UnityPy.streams import EndianBinaryReader

    if not isinstance(bundle, BundleFile):
        raise ValueError("The face needs its own Unity bundle.")
    result = {}
    for name, entry in bundle.files.items():
        if isinstance(entry, SerializedFile):
            data = bytes(entry.reader.bytes)
        elif isinstance(entry, EndianBinaryReader) and name.lower().endswith((".ress", ".resource")):
            data = bytes(entry.bytes)
        else:
            raise ValueError("The facial bundle contains an unsupported resource.")
        result[name] = (entry.flags, data)
    return result


def _check_texture(obj, resources):
    from UnityPy.enums import TextureFormat

    tree = obj.read_typetree()
    try:
        codec = TextureFormat(tree["m_TextureFormat"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("The face contains an unrecognized texture format.") from exc
    if ((codec.name not in _RAW_TEXTURES and not 48 <= codec.value <= 59)
            or tree.get("m_PlatformBlob")):
        raise ValueError(f"The face texture '{tree.get('m_Name', '')}' uses {codec.name} or platform-specific data.")
    width, height, mips = (tree.get(key) for key in ("m_Width", "m_Height", "m_MipCount"))
    if (not all(type(value) is int for value in (width, height, mips))
            or not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 4096 * 4096
            or not 1 <= mips <= max(width, height).bit_length()
            or tree.get("m_ImageCount", 1) != 1 or tree.get("m_TextureDimension", 2) != 2):
        raise ValueError("The face contains an unsupported texture layout.")
    stream = tree.get("m_StreamData") or {}
    inline = tree.get("image data")
    if stream.get("size"):
        path = stream.get("path")
        resource = resources.get(PurePosixPath(path.replace("\\", "/")).name) if isinstance(path, str) else None
        start, size = stream.get("offset"), stream.get("size")
        if (inline or not isinstance(resource, tuple) or type(start) is not int or type(size) is not int
                or start < 0 or size <= 0 or start + size > len(resource[1])):
            raise ValueError("The face texture stream is missing or outside its bundle.")
    elif not inline or stream.get("path"):
        raise ValueError("The face texture is missing its pixel data.")


def _changed_platform(data, asset, source, target):
    """Patch the parsed platform field and preserve every other CAB byte."""
    header = asset.header
    version = header.version
    start = 48 if version >= 22 else 20
    if (not 14 <= version <= 22 or header.file_size != len(data)
            or not start < header.data_offset <= len(data) or header.endian not in ("<", ">")):
        raise ValueError("The face uses an unsupported serialized file header.")
    end = data.find(b"\0", start, min(start + 128, header.data_offset))
    if (end <= start or end + 5 > header.data_offset or
            data[start:end] != str(asset.unity_version).encode("ascii")):
        raise ValueError("The face's Unity version or build target could not be verified.")
    offset = end + 1
    fmt = header.endian + "i"
    if struct.unpack_from(fmt, data, offset)[0] != source:
        raise ValueError("The face's declared Unity platform could not be verified.")
    return data[:offset] + struct.pack(fmt, target) + data[offset + 4:]


def copy_for_platform(raw, scene, target, name):
    """Copy a verified standalone face, changing only its native target field."""
    from UnityPy.files import SerializedFile
    from UnityPy.streams import EndianBinaryReader

    bundle = _bundle(raw)
    assets = [entry for entry in bundle.files.values() if isinstance(entry, SerializedFile)]
    source = model_platforms.single_platform((asset.target_platform for asset in assets), name)
    if source == target:
        return raw
    if source not in _NATIVE or target not in _NATIVE:
        raise ValueError("A face copy needs confirmed Android and iOS build targets.")

    original = _snapshot(bundle)
    scene_files = scene.env.files
    if len(scene_files) != 1 or _snapshot(next(iter(scene_files.values()))) != original or not is_face(scene):
        raise ValueError("The selected file is not the verified standalone facial companion.")
    resources = {entry: value for entry, value in original.items() if not isinstance(bundle.files[entry], SerializedFile)}
    for asset in assets:
        for obj in asset.objects.values():
            kind = obj.type.name
            if kind not in _FACE_OBJECTS:
                raise ValueError(f"The face contains {kind}, which needs a native original on this platform.")
            if kind == "Texture2D":
                _check_texture(obj, resources)

    expected = dict(original)
    for entry, asset in list(bundle.files.items()):
        if isinstance(asset, SerializedFile):
            flags, data = original[entry]
            patched = _changed_platform(data, asset, source, target)
            replacement = EndianBinaryReader(patched)
            replacement.flags = flags
            bundle.files[entry] = replacement
            expected[entry] = (flags, patched)
    output = bundle.save(packer="original")
    verified = _bundle(output)
    if (_snapshot(verified) != expected or
            {int(asset.target_platform) for asset in verified.files.values() if isinstance(asset, SerializedFile)} != {target}):
        raise ValueError("The face copy did not preserve its original Unity assets.")
    return output
