"""Texture baking for the original SIFAS Body material and its unchanged shader.

This module never mutates Unity objects.  Geometry callers split vertices by
source material, apply ``transforms``, clone the returned texture trees, and
retain their original renderer/material/submesh contract.  Source mip images
are decoded individually: authored levels are never regenerated from level 0.
The coarse tail of an ordinary atlas necessarily shares texels between cells;
diagnostics describe that limitation instead of promising all-LOD parity.
"""
from dataclasses import dataclass
import copy
import hashlib
import math
import ntpath


class AtlasCompatibilityError(ValueError):
    """The original shader cannot represent the requested material combination."""


@dataclass
class MaterialSource:
    name: str
    tree: dict
    objects: dict
    material_object: object = None
    uv_bounds: tuple = None  # Unity UVs: min u, min v, max u, max v


@dataclass(frozen=True)
class UVTransform:
    scale: tuple = (1.0, 1.0)
    offset: tuple = (0.0, 0.0)

    def remap_uv(self, values):
        import numpy as np
        result = np.asarray(values, dtype=float).copy()
        result[..., :2] = result[..., :2] * self.scale + self.offset
        return result


@dataclass
class AtlasTexture:
    tree: dict
    template: object
    width: int
    height: int
    mip_count: int


@dataclass
class AtlasBake:
    transforms: tuple
    textures: dict
    diagnostics: tuple
    identity: bool
    unique_sources: int


_MEMBER_EXTERNAL = ("cab-9382ea964987eceddd567506a3b21312", 8291131735116688333)
_FEATURES = {"_MATCAP_ON", "_EMISSIVE_ON", "_CHEEK_ON"}
_RIM_FLOATS = ("_RimglightIntensity", "_RimglightPower")
_RIM_COLORS = ("_RimlightColor", "_RimlightDirection")


def _pairs(tree, key):
    result = {}
    for entry in tree.get("m_SavedProperties", {}).get(key, []):
        if isinstance(entry, (list, tuple)):
            result[entry[0]] = entry[1]
        else:
            result[entry["first"]] = entry["second"]
    return result


def _pointer_identity(source, pointer):
    pid, fid = int(pointer.get("m_PathID", 0)), int(pointer.get("m_FileID", 0))
    if not pid:
        return None
    if not fid:
        return ("local", pid)
    try:
        external = source.material_object.assets_file.externals[fid - 1]
        return (ntpath.basename(getattr(external, "path", None) or external.name).casefold(), pid)
    except (AttributeError, IndexError, TypeError):
        raise AtlasCompatibilityError(f"{source.name}: cannot resolve external material dependency {fid}:{pid}.")


def _verify_member(source):
    pointer = source.tree.get("m_Shader", {})
    identity = _pointer_identity(source, pointer)
    if identity and identity[0] == "local":
        shader = source.objects.get(identity[1])
        if shader is not None and shader.type.name == "Shader":
            tree = shader.read_typetree()
            name = tree.get("m_Name") or tree.get("m_ParsedForm", {}).get("m_Name")
            if name == "AS/Member":
                return
    elif identity == _MEMBER_EXTERNAL:
        return
    raise AtlasCompatibilityError(f"{source.name}: game Body atlasing requires the verified AS/Member shader.")


def _profile(source):
    from webtools.core.model_materials import COLORS, FLOATS
    floats, colors = _pairs(source.tree, "m_Floats"), _pairs(source.tree, "m_Colors")
    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise AtlasCompatibilityError(f"{source.name}: a material property is not finite.")
        return value
    f = {name: number(floats.get(name, default)) for name, default in FLOATS.items()}
    c = {name: tuple(number(colors.get(name, {}).get(channel, default[index]))
                     for index, channel in enumerate("rgba")) for name, default in COLORS.items()}
    keywords = set(str(source.tree.get("m_ShaderKeywords", "")).split())
    return f, c, keywords


def _equal(a, b):
    if isinstance(a, tuple):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7)


def _check_profiles(sources, diagnostics):
    profiles = [_profile(source) for source in sources]
    tf, tc, tk = profiles[0]
    features = tk & _FEATURES
    if "_CHEEK_ON" in features:
        raise AtlasCompatibilityError("Active AS/Member cheek arrays cannot be moved into a Body atlas; disable cheek on the source material first.")
    for source, (floats, colors, keywords) in zip(sources, profiles):
        if keywords & _FEATURES != features:
            raise AtlasCompatibilityError(f"{source.name}: MATCAP/EMISSIVE/CHEEK shader variants differ from the wearer; one Body material cannot retain both variants.")
        # _RIMLIGHT_ON is a legacy runtime switch, not a compiled shader variant.
        if keywords - _FEATURES - {"_RIMLIGHT_ON"} != tk - _FEATURES - {"_RIMLIGHT_ON"}:
            raise AtlasCompatibilityError(f"{source.name}: unsupported shader keywords differ from the wearer.")
        wanted_floats = ["_MainTexMipmapBias", "_CullMode", "_OutlineStencilComp"]
        wanted_colors = ["_TintColor", "_AmbientColor"]
        if "_MATCAP_ON" in features:
            wanted_floats += ["_MatcapTexDarkenR", "_MatcapTexAdd", "_MatcapBrightR", "_MatcapBrightG", "_MatcapSpanColTexAdd"]
            wanted_colors += ["_MatcapIntensity", "_MatcapSpanCol"]
        if "_EMISSIVE_ON" in features:
            wanted_colors += ["_EmissiveIntensity", "_EmissiveFlicker"]
            if any(abs(value) > 1e-8 for value in colors["_EmissiveFlicker"][:2]):
                raise AtlasCompatibilityError(f"{source.name}: animated emissive scrolling cannot stay inside atlas cells with the original shader; use a static emissive material.")
        for name in wanted_floats:
            if not _equal(floats[name], tf[name]):
                raise AtlasCompatibilityError(f"{source.name}: active {name} differs from the wearer; match this material setting before combining Body materials.")
        for name in wanted_colors:
            # RGB values of a zero-strength tint/ambient operation are dormant.
            left, right = colors[name], tc[name]
            if name in ("_TintColor", "_AmbientColor") and left[3] == right[3] == 0:
                continue
            if not _equal(left, right):
                raise AtlasCompatibilityError(f"{source.name}: active {name} differs from the wearer; match this material setting before combining Body materials.")
        for name, default in (("m_CustomRenderQueue", -1), ("disabledShaderPasses", [])):
            if source.tree.get(name, default) != sources[0].tree.get(name, default):
                raise AtlasCompatibilityError(f"{source.name}: {name} differs from the wearer.")
        if any(not _equal(floats[name], tf[name]) for name in _RIM_FLOATS) or any(not _equal(colors[name], tc[name]) for name in _RIM_COLORS):
            diagnostics.append(f"{source.name}: original wearer rim-light shader settings retained; donor rim texture is preserved, but donor lighting settings are not reproduced.")
    slots = ["_MainTex"]
    # Keep authored rim maps even when the saved intensity is zero: the game can
    # enable rim lighting at runtime without rebuilding the mesh.
    if any(_pairs(source.tree, "m_TexEnvs").get("_RimlightTex", {}).get("m_Texture", {}).get("m_PathID") for source in sources):
        slots.append("_RimlightTex")
    if "_MATCAP_ON" in features:
        slots.append("_MatcapMaskTex")
    if "_EMISSIVE_ON" in features:
        slots.extend(("_EmissiveTex", "_EmissiveScrollTex"))
    return slots, features


def _texture(source, slot):
    pointer = _pairs(source.tree, "m_TexEnvs").get(slot, {}).get("m_Texture", {})
    identity = _pointer_identity(source, pointer)
    if identity is None:
        return None
    if identity[0] != "local":
        raise AtlasCompatibilityError(f"{source.name}: {slot} is an external texture; load its dependency before baking the atlas.")
    obj = source.objects.get(identity[1])
    if obj is None or obj.type.name != "Texture2D":
        raise AtlasCompatibilityError(f"{source.name}: {slot} is missing or is not an ordinary Texture2D.")
    return obj


def _settings(texture):
    value = texture.m_TextureSettings
    def get(name, default):
        return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)
    return tuple(get(name, default) for name, default in (("m_FilterMode", 1), ("m_Aniso", 1), ("m_MipBias", 0), ("m_WrapU", 0), ("m_WrapV", 0)))


def _texture_key(obj):
    if obj is None:
        return None
    texture = obj.read()
    width, height = int(texture.m_Width), int(texture.m_Height)
    count = int(getattr(texture, "m_MipCount", 1) or 1)
    if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 16777216 or not 1 <= count <= 13:
        raise AtlasCompatibilityError("A source texture exceeds the supported 4096-pixel dimension or mip limits.")
    if getattr(texture, "m_ImageCount", 1) != 1 or getattr(texture, "m_TextureDimension", 2) != 2:
        raise AtlasCompatibilityError("Only ordinary 2D source textures can be combined.")
    sampler = _settings(texture)
    if (sampler[0] not in (0, 1, 2) or sampler[3] not in (0, 1, 2, 3) or sampler[4] not in (0, 1, 2, 3)
            or not isinstance(sampler[1], (int, float)) or not 0 <= sampler[1] <= 16
            or not isinstance(sampler[2], (int, float)) or not math.isfinite(sampler[2])):
        raise AtlasCompatibilityError("A source texture uses unsupported sampler/filter/wrap settings.")
    inline = getattr(texture, "image_data", b"")
    stream = getattr(texture, "m_StreamData", None)
    stream_size = stream.get("size", 0) if isinstance(stream, dict) else getattr(stream, "size", 0)
    if (inline and len(inline) > 134217728) or stream_size > 134217728:
        raise AtlasCompatibilityError("A source texture exceeds the bounded source-data budget.")
    pixels = texture.get_image_data()
    if not isinstance(pixels, (bytes, bytearray)) or not 0 < len(pixels) <= 134217728:
        raise AtlasCompatibilityError("A source texture has missing or oversized pixel data.")
    return (width, height, int(texture.m_TextureFormat),
            count, int(getattr(texture, "m_ColorSpace", 1)),
            sampler, hashlib.sha256(pixels).digest())


def _pow2(value):
    return 1 << (max(1, int(value)) - 1).bit_length()


def _decode_default(texture):
    # Raw pixels use Pillow; compressed formats run only in bundled disposable
    # executables on every platform, including desktop rehearsal/test hosts.
    import time
    from webtools.core import decode
    return decode._android_image(texture, time.monotonic() + 60)


def _mip_images(obj, decoder):
    from webtools.core.model_materials import _original_mips
    texture = obj.read()
    count = int(getattr(texture, "m_MipCount", 1) or 1)
    try:
        levels = [texture] + [proxy.read() for proxy in _original_mips(obj, texture)]
    except (ValueError, AttributeError) as error:
        raise AtlasCompatibilityError(f"{getattr(texture, 'm_Name', 'Texture')}: cannot preserve the authored mip chain: {error}") from error
    if len(levels) != count:
        raise AtlasCompatibilityError("The authored mip chain could not be read completely.")
    images = []
    for level in levels:
        image = decoder(level).convert("RGBA")
        if image.size != (level.m_Width, level.m_Height):
            raise AtlasCompatibilityError("A texture decoder returned the wrong authored mip dimensions.")
        images.append(image)
    return images


def _pack(rectangles, limit):
    # Shelves are deterministic; test each power-of-two width and choose the
    # smallest area. Material order remains independent of packing order.
    best = None
    width = _pow2(max(rect[0] for rect in rectangles))
    while width <= limit:
        placements = [None] * len(rectangles)
        x = y = shelf = 0
        for index in sorted(range(len(rectangles)), key=lambda i: (-rectangles[i][1], -rectangles[i][0], i)):
            w, h = rectangles[index]
            if x + w > width:
                y += shelf
                x = shelf = 0
            placements[index] = (x, y)
            x += w
            shelf = max(shelf, h)
        height = _pow2(y + shelf)
        if height <= limit:
            candidate = (width * height, max(width, height), width, height, placements)
            if best is None or (candidate[0], candidate[1], candidate[3]) < (best[0], best[1], best[3]):
                best = candidate
        width *= 2
    return None if best is None else best[2:]


def _indices(values, length, mode):
    import numpy as np
    values = np.asarray(values, dtype="int64")
    if mode == 0:
        return values % length
    if mode == 1:
        return np.clip(values, 0, length - 1)
    if mode == 2:
        period = values % (length * 2)
        return np.where(period < length, period, length * 2 - period - 1)
    if mode == 3:
        return np.clip(np.where(values < 0, -values - 1, values), 0, length - 1)
    raise AtlasCompatibilityError(f"Unsupported texture wrap mode {mode}.")


def _region_patch(canvas_size, image, basis, crop, position, wraps):
    """Copy a touching source cell, with Unity bottom-left UV coordinates."""
    import numpy as np
    from PIL import Image
    bw, bh = basis
    # A shared UV rectangle can require nearest replication of smaller maps.
    # It never reduces a source authored mip's resolution.
    if image.size != (bw, bh):
        image = image.resize((bw, bh), Image.Resampling.NEAREST)
    left, bottom, right, top = crop
    px, py = position  # bottom-left coordinates in the atlas
    xs = _indices(np.arange(left, right), bw, wraps[0])
    ys = _indices(np.arange(bottom, top), bh, wraps[1])
    pixels = np.asarray(image)[bh - 1 - ys[:, None], xs[None, :]]
    patch = Image.fromarray(pixels[::-1], "RGBA")
    return patch, (px, canvas_size[1] - (py + top - bottom))


def _compose_level(size, patches):
    from PIL import Image
    rectangles = [(x, y, x + patch.width, y + patch.height) for patch, (x, y) in patches]
    overlaps = any(max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
                   for i, a in enumerate(rectangles) for b in rectangles[:i])
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    if not overlaps:
        for patch, position in patches:
            canvas.paste(patch, position)
        return canvas
    # Distinct cells eventually share texels in the coarse atlas tail. Average
    # those authored samples rather than silently letting the last source win.
    import numpy as np
    sums = np.zeros((size[1], size[0], 4), dtype="uint32")
    counts = np.zeros((size[1], size[0], 1), dtype="uint16")
    for patch, (x, y) in patches:
        left, top = max(0, x), max(0, y)
        right, bottom = min(size[0], x + patch.width), min(size[1], y + patch.height)
        if right <= left or bottom <= top:
            continue
        sums[top:bottom, left:right] += np.asarray(patch, dtype="uint32")[top - y:bottom - y, left - x:right - x]
        counts[top:bottom, left:right] += 1
    return Image.fromarray(((sums + counts // 2) // np.maximum(counts, 1)).astype("uint8"), "RGBA")


def bake_game_atlas(target, donors, *, image_decoder=None, max_dimension=4096,
                    max_pixels=16777216, gutter=0, max_total_bytes=268435456):
    """Build original-shader atlases without mutating any input object.

    ``image_decoder`` accepts a Texture2D (including an immutable mip proxy).
    All output slots share material UV transforms. Smaller source maps may be
    enlarged by nearest replication; no authored source mip is downsampled to
    fit. The original target sampler is retained per slot. Cells touch with no
    padding or extruded borders. Bounds support bounded repeated/mirrored UVs.
    """
    from PIL import Image
    sources = [target] + list(donors)
    if not sources:
        raise AtlasCompatibilityError("At least one Body material is required.")
    if any(type(value) is not int or value <= 0 for value in (max_dimension, max_pixels, max_total_bytes)) or type(gutter) is not int or gutter < 0:
        raise AtlasCompatibilityError("Atlas limits and gutter must be bounded positive integers (gutter may be zero).")
    if gutter:
        raise AtlasCompatibilityError("Body texture atlases use no padding or gutters; gutter must be zero.")
    diagnostics = []
    for source in sources:
        _verify_member(source)
    slots, features = _check_profiles(sources, diagnostics)
    textures = [[_texture(source, slot) for slot in slots] for source in sources]
    keys = [[_texture_key(obj) for obj in row] for row in textures]
    if "_MATCAP_ON" in features:
        caps = []
        for source in sources:
            pointer = _pairs(source.tree, "m_TexEnvs").get("_MatcapTex", {}).get("m_Texture", {})
            identity = _pointer_identity(source, pointer)
            caps.append(("external", identity) if identity and identity[0] != "local" else _texture_key(_texture(source, "_MatcapTex")))
        if any(key != caps[0] for key in caps):
            raise AtlasCompatibilityError("Normal-driven _MatcapTex differs between sources; the original Body shader can use only one shared matcap texture.")
    # Material uniforms have been checked independently; texture equality can
    # safely avoid repeated atlas growth for identical source materials.
    if all(key == keys[0] for key in keys):
        return AtlasBake(tuple(UVTransform() for _ in sources), {}, tuple(diagnostics), True, 1)
    unique, source_ids, unique_textures = [], [], []
    for source, key, row in zip(sources, keys, textures):
        signature = tuple(key)
        try:
            index = unique.index(signature)
        except ValueError:
            index = len(unique)
            unique.append(signature)
            unique_textures.append(row)
        source_ids.append(index)
    # Equal source pixels can appear with different selected UV bounds. Union
    # their bounds before packing so every mapped face remains inside its cell.
    bounds = [None] * len(unique)
    for source, index in zip(sources, source_ids):
        value = source.uv_bounds or (0., 0., 1., 1.)
        if len(value) != 4 or not all(math.isfinite(float(v)) for v in value) or value[2] < value[0] or value[3] < value[1]:
            raise AtlasCompatibilityError(f"{source.name}: invalid or non-finite atlas UV bounds.")
        if any(abs(v) > 16 for v in value):
            raise AtlasCompatibilityError(f"{source.name}: repeated UV extent exceeds the atlas limit; reduce the selected UV range.")
        old = bounds[index]
        bounds[index] = tuple(value) if old is None else (min(old[0], value[0]), min(old[1], value[1]), max(old[2], value[2]), max(old[3], value[3]))
    bases, crops = [], []
    for row, bound in zip(unique_textures, bounds):
        bases.append(tuple(_pow2(max([getattr(obj.read(), attr) for obj in row if obj is not None] or [1])) for attr in ("m_Width", "m_Height")))
        bw, bh = bases[-1]
        # Keep complete source tiles. Repeated UVs expand to whole periods;
        # no sampling margin, transparent border, or edge extrusion is added.
        left, bottom = math.floor(min(0, bound[0])) * bw, math.floor(min(0, bound[1])) * bh
        right, top = math.ceil(max(1, bound[2])) * bw, math.ceil(max(1, bound[3])) * bh
        crops.append((left, bottom, max(left + 1, right), max(bottom + 1, top)))
    rectangles = [(r - l, t - b) for l, b, r, t in crops]
    packed = _pack(rectangles, max_dimension)
    if packed is None:
        raise AtlasCompatibilityError(f"The atlas cannot fit original texture detail within {max_dimension}×{max_dimension}. Select fewer material textures or increase the explicit atlas dimension limit; source textures were not downsampled.")
    width, height, positions = packed
    if width * height > max_pixels:
        raise AtlasCompatibilityError("The atlas exceeds the configured pixel budget; select a smaller UV region.")
    transforms = []
    for index in source_ids:
        bw, bh = bases[index]
        l, b, _, _ = crops[index]
        x, y = positions[index]
        transforms.append(UVTransform((bw / width, bh / height), ((x - l) / width, (y - b) / height)))
    result, total_bytes = {}, 0
    decoder = image_decoder or _decode_default
    for slot_index, slot in enumerate(slots):
        originals = [row[slot_index] for row in unique_textures]
        available = [obj for obj in originals if obj is not None]
        target_obj = textures[0][slot_index]
        if not available:
            continue
        template = target_obj
        if template is None:
            template = next((obj for obj in target.objects.values() if obj.type.name == "Texture2D" and (target.material_object is None or obj.assets_file is target.material_object.assets_file)), None)
        if template is None:
            raise AtlasCompatibilityError(f"The wearer has no local Texture2D template for {slot}.")
        reference = (target_obj or available[0]).read()
        sampler = _settings(reference)
        color_space = int(getattr(reference, "m_ColorSpace", 1))
        for obj in available:
            texture = obj.read()
            if getattr(texture, "m_ImageCount", 1) != 1 or getattr(texture, "m_TextureDimension", 2) != 2:
                raise AtlasCompatibilityError(f"{slot}: only ordinary 2D textures can be combined.")
            if _settings(texture) != sampler or int(getattr(texture, "m_ColorSpace", 1)) != color_space:
                raise AtlasCompatibilityError(f"{slot}: source sampler or color-space settings differ; match them before atlasing.")
            if texture.m_Width > max_dimension or texture.m_Height > max_dimension:
                raise AtlasCompatibilityError(f"{slot}: a source texture exceeds the configured atlas dimension limit.")
        # Choose a smaller atlas for auxiliary slots when every source still
        # fits its common UV cell at native resolution. Layout/UVs stay shared.
        factor = 1
        while width >= factor * 2 and height >= factor * 2 and all(
                obj is None or (bases[index][0] // (factor * 2) >= obj.read().m_Width and
                                bases[index][1] // (factor * 2) >= obj.read().m_Height)
                for index, obj in enumerate(originals)):
            factor *= 2
        slot_width, slot_height = width // factor, height // factor
        has_mips = any(int(getattr(obj.read(), "m_MipCount", 1) or 1) > 1 for obj in available)
        count = max(slot_width, slot_height).bit_length() if has_mips else 1
        size = sum(max(1, slot_width >> level) * max(1, slot_height >> level) * 4 for level in range(count))
        total_bytes += size
        if total_bytes > max_total_bytes:
            raise AtlasCompatibilityError("The RGBA32 atlas mip payloads exceed the configured memory budget; select fewer materials or a smaller UV region.")
        chains = [_mip_images(obj, decoder) if obj is not None else None for obj in originals]
        payload = bytearray()
        for level in range(count):
            aw, ah = max(1, slot_width >> level), max(1, slot_height >> level)
            divisor = factor << level
            patches = []
            for index, chain in enumerate(chains):
                # Decode authored level N directly. Once a source reaches its
                # final authored level, replicate that image into the tail.
                image = chain[min(level, len(chain) - 1)] if chain else Image.new("RGBA", (1, 1), (0, 0, 0, 255) if slot == "_EmissiveTex" else (255, 255, 255, 255))
                bw, bh = (max(1, value // divisor) for value in bases[index])
                l, b, r, t = crops[index]
                crop = (math.floor(l / divisor), math.floor(b / divisor), math.ceil(r / divisor), math.ceil(t / divisor))
                x, y = positions[index]
                px, py = x // divisor, y // divisor
                patches.append(_region_patch((aw, ah), image, (bw, bh), crop, (px, py), sampler[-2:]))
            canvas = _compose_level((aw, ah), patches)
            payload.extend(canvas.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
        tree = copy.deepcopy(template.read_typetree())
        tree.update(m_Name=f"{tree.get('m_Name', 'Body')}_graft_atlas", m_Width=slot_width, m_Height=slot_height,
                    m_TextureFormat=4, m_CompleteImageSize=len(payload), m_MipCount=count,
                    m_ImageCount=1, m_TextureDimension=2, m_ColorSpace=color_space)
        if "m_MipMap" in tree:
            tree["m_MipMap"] = count > 1
        tree["image data"] = bytes(payload)
        tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        if "m_StreamingMipmaps" in tree:
            tree["m_StreamingMipmaps"] = False
        # A fallback template may belong to another slot: retain the selected
        # slot's actual original sampler rather than that template's sampler.
        source_tree = (target_obj or available[0]).read_typetree()
        tree["m_TextureSettings"] = copy.deepcopy(source_tree["m_TextureSettings"])
        result[slot] = AtlasTexture(tree, template, slot_width, slot_height, count)
    diagnostics.append(f"Body atlas {width}×{height}, {len(unique)} distinct material texture sets, no padding; authored mip images copied directly, smaller maps may use nearest replication.")
    return AtlasBake(tuple(transforms), result, tuple(diagnostics), False, len(unique))
