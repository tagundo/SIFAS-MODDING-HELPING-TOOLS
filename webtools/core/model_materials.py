"""Read-only AS/Member metadata for the offline renderer.

The caller identifies the shader, owns the image/GLB budgets, and supplies its
existing pixel-preserving texture exporter. Only authored, used shader inputs
are added here; stale Unity Standard material properties are not reinterpreted.
"""
import math
import re
from types import SimpleNamespace


COLORS = {
    "_TintColor": (1, 1, 1, 1), "_AmbientColor": (1, 1, 1, 0),
    "_RimlightColor": (1, 1, 1, 1), "_RimlightDirection": (0, 0, 0, 0),
    "_MatcapIntensity": (1, 1, 1, 1), "_MatcapSpanCol": (1, 1, 1, 1),
    "_EmissiveIntensity": (1, 1, 1, 1), "_EmissiveFlicker": (.1, .1, 0, 0),
}
FLOATS = {
    "_RimglightIntensity": 1, "_RimglightPower": 3,
    "_MatcapTexDarkenR": 1, "_MatcapTexAdd": 0,
    "_MatcapBrightR": 1, "_MatcapBrightG": 1, "_MatcapSpanColTexAdd": 0,
    "_CheekTexArrayIndex": 0, "_CheekIntensity": 0,
    "_MainTexMipmapBias": 0, "_CullMode": 2, "_OutlineStencilComp": 8,
}
MAX_ARRAY_BYTES = 64 * 1024 * 1024


def _finite(value):
    value = float(value)
    if not math.isfinite(value) or abs(value) > 65504:
        raise ValueError("A member shader property exceeds the preview range.")
    return value


def _array_layer(obj, layer):
    """Present one original array slice to the ordinary bounded image exporter.

    No array-native image decoder is called. Unity stores consecutive complete
    mip chains per slice; the selected chain is copied without resizing or
    changing pixels. Unknown/swizzled/streamed layouts are left unsupported.
    """
    from UnityPy.enums import TextureFormat
    texture = obj.read()
    width, height, depth = texture.m_Width, texture.m_Height, texture.m_Depth
    mips = int(texture.m_MipCount)
    if not (0 < width <= 4096 and 0 < height <= 4096 and 0 < depth <= 64 and 1 <= mips <= 16):
        raise ValueError("The cheek array exceeds the preview limits.")
    # sampler2DArray chooses the nearest integer slice and clamps its array
    # coordinate. It does not truncate .6 to0 or wrap beyond the last slice.
    layer = min(depth - 1, max(0, math.floor(_finite(layer) + .5)))
    data = texture.image_data
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= MAX_ARRAY_BYTES:
        raise ValueError("The cheek array has no bounded inline pixel data.")
    stream = getattr(texture, "m_StreamData", None)
    if stream is not None and getattr(stream, "size", 0):
        raise ValueError("Streamed cheek arrays are unavailable in this preview.")
    name = TextureFormat(texture.m_Format).name
    channels = {"RGBA32": 4, "ARGB32": 4, "BGRA32": 4, "RGB24": 3}.get(name)
    astc = re.fullmatch(r"ASTC_(?:RGB|RGBA)_(4|5|6|8|10|12)x\1", name)
    if channels is None and astc is None:
        raise ValueError("The cheek array format is unavailable in this preview.")
    stride = 0
    for level in range(mips):
        w, h = max(1, width >> level), max(1, height >> level)
        if channels is not None:
            stride += w * h * channels
        else:
            block = int(astc.group(1))
            stride += ((w + block - 1) // block) * ((h + block - 1) // block) * 16
    if stride * depth > len(data):
        raise ValueError("The cheek array pixel data is truncated.")
    pixels = bytes(data[layer * stride:(layer + 1) * stride])
    proxy = SimpleNamespace(
        m_Name=str(texture.m_Name) + "_layer_" + str(layer),
        m_Width=width, m_Height=height, m_TextureFormat=int(texture.m_Format),
        m_MipCount=mips, m_ImageCount=1, m_TextureDimension=2,
        m_TextureSettings=texture.m_TextureSettings,
        m_ColorSpace=getattr(texture, "m_ColorSpace", 1),
        m_StreamData=None, image_data=pixels,
        object_reader=getattr(texture, "object_reader", None),
        get_image_data=lambda: pixels,
    )
    # The normal exporter uses this hashable identity solely as its cache key.
    return SimpleNamespace(assets_file=obj.assets_file, preview_array_layer=layer,
                           path_id=(obj.path_id, "array-layer", layer),
                           type=SimpleNamespace(name="Texture2D"),
                           read=lambda: proxy)


def _original_mips(obj, texture):
    """Yield exact authored mip pixels to the same bounded image exporter."""
    from UnityPy.enums import TextureFormat
    count = int(getattr(texture, "m_MipCount", 1))
    if count <= 1:
        return []
    width, height = int(texture.m_Width), int(texture.m_Height)
    if not (0 < width <= 4096 and 0 < height <= 4096 and 1 < count <= 13):
        raise ValueError("The authored mip chain exceeds the preview limits.")
    if count != max(width, height).bit_length():
        raise ValueError("A partial authored mip chain is unavailable in this preview.")
    if getattr(texture, "m_ImageCount", 1) != 1 or getattr(texture, "m_TextureDimension", 2) != 2:
        raise ValueError("Only ordinary image mip chains are supported.")
    format_id = int(texture.m_TextureFormat)
    name = TextureFormat(format_id).name
    channels = {"RGBA32": 4, "ARGB32": 4, "BGRA32": 4, "RGB24": 3}.get(name)
    astc = re.fullmatch(r"ASTC_(?:RGB|RGBA)_(4|5|6|8|10|12)x\1", name)
    if channels is None and astc is None:
        raise ValueError("The authored mip format is unavailable in this preview.")
    data = texture.get_image_data()
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= MAX_ARRAY_BYTES:
        raise ValueError("The authored mip data exceeds the preview limits.")
    output, offset = [], 0
    for level in range(count):
        w, h = max(1, width >> level), max(1, height >> level)
        if channels is not None:
            size = w * h * channels
        else:
            block = int(astc.group(1))
            size = ((w + block - 1) // block) * ((h + block - 1) // block) * 16
        if offset + size > len(data):
            raise ValueError("The authored mip data is truncated.")
        if level:
            pixels = bytes(data[offset:offset + size])
            proxy = SimpleNamespace(
                m_Name=str(texture.m_Name) + "_mip_" + str(level),
                m_Width=w, m_Height=h, m_TextureFormat=format_id,
                m_MipCount=1, m_ImageCount=1, m_TextureDimension=2,
                m_TextureSettings=texture.m_TextureSettings,
                m_ColorSpace=getattr(texture, "m_ColorSpace", 1),
                m_StreamData=None, image_data=pixels,
                object_reader=getattr(texture, "object_reader", None),
                get_image_data=lambda data=pixels: data,
            )
            output.append(SimpleNamespace(assets_file=obj.assets_file,
                path_id=(obj.path_id, "authored-mip", level),
                type=SimpleNamespace(name="Texture2D"), read=lambda value=proxy: value))
        offset += size
    return output


def attach_member_metadata(scene, obj, tree, material, texture_resolver):
    """Attach JSON-safe inputs; caller invokes only for verified AS/Member.

    The supported APK uses Gamma rendering (PlayerSettings.m_ActiveColorSpace0).
    The WebGL implementation consequently evaluates these equations in original
    texture values rather than applying Three's lighting or linear tint math.
    """
    from .model_viewer import _ref
    saved = tree.get("m_SavedProperties", {})
    colors, floats, envs = (dict(saved.get(key, [])) for key in ("m_Colors", "m_Floats", "m_TexEnvs"))
    metadata = {"version": 1, "shader": "AS/Member", "pipeline": "gamma",
                "colors": {}, "floats": {}, "textures": {}, "limitations": []}
    for name, default in COLORS.items():
        value = colors.get(name, {})
        metadata["colors"][name] = [_finite(value.get(channel, default[index]))
                                     for index, channel in enumerate("rgba")]
    for name, default in FLOATS.items():
        metadata["floats"][name] = _finite(floats.get(name, default))
    keywords = str(tree.get("m_ShaderKeywords", "")).split()[:64]
    metadata["keywords"] = keywords
    features = {"rimlight": metadata["floats"]["_RimglightIntensity"] > 0
                and metadata["colors"]["_RimlightColor"][3] > 0,
                "matcap": "_MATCAP_ON" in keywords,
                "emissive": "_EMISSIVE_ON" in keywords,
                "cheek": "_CHEEK_ON" in keywords,
                "outline": True}
    metadata["features"] = features

    wanted = ["_MainTex"]
    if features["rimlight"]:
        wanted.append("_RimlightTex")
    if features["matcap"]:
        wanted.extend(("_MatcapTex", "_MatcapMaskTex"))
    if features["emissive"]:
        wanted.extend(("_EmissiveTex", "_EmissiveScrollTex"))
    if features["cheek"] and metadata["floats"]["_CheekIntensity"] != 0:
        wanted.append("_CheekTex")

    for name in wanted:
        source = envs.get(name, {})
        pointer = source.get("m_Texture", {})
        if not pointer.get("m_PathID"):
            # These are the actual ShaderLab defaults, not replacement assets.
            metadata["textures"][name] = {"default": [0, 0, 0, 1] if name == "_EmissiveTex" else [1, 1, 1, 1]}
            continue
        try:
            target = _ref(obj, pointer)
            if target is None:
                raise ValueError("A shader texture dependency is missing.")
            layer = None
            if target.type.name == "Texture2DArray" and name == "_CheekTex":
                target = _array_layer(target, metadata["floats"]["_CheekTexArrayIndex"])
                layer = target.preview_array_layer
            if target.type.name != "Texture2D":
                raise ValueError("This shader texture type is unsupported.")
            index = texture_resolver(target)
            texture = target.read()
            entry = {"index": index, "colorSpace": int(getattr(texture, "m_ColorSpace", 1)),
                     "scale": [_finite(source.get("m_Scale", {}).get(key, 1)) for key in "xy"],
                     "offset": [_finite(source.get("m_Offset", {}).get(key, 0)) for key in "xy"]}
            if layer is not None:
                entry["arrayLayer"] = layer
            entry["filterMode"] = int(getattr(getattr(texture, "m_TextureSettings", None), "m_FilterMode", 1))
            try:
                mips = _original_mips(target, texture)
                if mips:
                    entry["mipmaps"] = [index] + [texture_resolver(level) for level in mips]
                    entry["mipWidths"] = [max(1, int(texture.m_Width) >> level) for level in range(len(mips) + 1)]
                    entry["mipHeights"] = [max(1, int(texture.m_Height) >> level) for level in range(len(mips) + 1)]
            except Exception:
                metadata["limitations"].append("Authored mip levels unavailable: " + name)
            metadata["textures"][name] = entry
        except Exception:
            metadata["limitations"].append("Shader texture unavailable: " + name)
            # An unresolved nonzero dependency is different from a ShaderLab
            # default. Disable just its feature instead of inventing a glow.
            for feature, names in (("rimlight", ("_RimlightTex",)),
                                   ("matcap", ("_MatcapTex", "_MatcapMaskTex")),
                                   ("emissive", ("_EmissiveTex", "_EmissiveScrollTex")),
                                   ("cheek", ("_CheekTex",))):
                if name in names:
                    features[feature] = False
    material.setdefault("extras", {})["sifas"] = metadata
    return metadata
