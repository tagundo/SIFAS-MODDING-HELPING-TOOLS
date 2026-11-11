"""Detached, bounded texture enlargement before the empty-UV graft attempts.

The original-position strategy matches each UV-driven slot to its largest
source width/height. The movement strategy retains Main sizes and matches only
auxiliary pixel ratios. Source objects, normal-driven MatCap textures and UVs
are never changed here. Pixels are replicated without padding or downscaling.
"""
import copy
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

from graft_texture_atlas import (
    AtlasCompatibilityError, AtlasTexture, _check_profiles, _decode_default,
    _mip_images, _pairs, _texture, _texture_key,
)


def _chain_bytes(width, height, count):
    return sum(max(1, width >> level) * max(1, height >> level) * 4
               for level in range(count))


class _UpscaledTexture:
    """Read-only Texture2D/ObjectReader view, decoded only after UV validation."""

    def __init__(self, template, size, count, mip_shift, decoder):
        self.template, self.size, self.count = template, size, count
        self.mip_shift, self.decoder, self._payload = mip_shift, decoder, None

    def __getattr__(self, name):
        return getattr(self.template, name)

    def _pixels(self):
        if self._payload is None:
            from PIL import Image
            originals = _mip_images(self.template, self.decoder)
            payload = bytearray()
            for level in range(self.count):
                # A 2x enlargement needs source mip 0 at output levels 0 and 1,
                # then source mip 1 at level 2. Copying mip N to N would make
                # implicit shader LOD select a coarser authored image too soon.
                source_level = max(0, level - self.mip_shift)
                original = originals[min(source_level, len(originals) - 1)]
                size = tuple(max(1, axis >> level) for axis in self.size)
                enlarged = original if original.size == size else original.resize(size, Image.Resampling.NEAREST)
                payload.extend(enlarged.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
            self._payload = bytes(payload)
        return self._payload

    def read(self):
        original = self.template.read()
        return SimpleNamespace(
            m_Name=original.m_Name, m_Width=self.size[0], m_Height=self.size[1],
            m_TextureFormat=4, m_MipCount=self.count, m_ImageCount=1, m_TextureDimension=2,
            m_CompleteImageSize=_chain_bytes(*self.size, self.count),
            m_TextureSettings=original.m_TextureSettings,
            m_ColorSpace=getattr(original, "m_ColorSpace", 1), m_StreamData=None,
            image_data=b"", object_reader=getattr(original, "object_reader", None),
            get_image_data=self._pixels,
        )

    def read_typetree(self):
        tree = copy.deepcopy(self.template.read_typetree())
        payload = self._pixels()
        tree.update(m_Width=self.size[0], m_Height=self.size[1], m_TextureFormat=4,
                    m_MipCount=self.count, m_CompleteImageSize=len(payload))
        tree["image data"] = payload
        tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        if "m_MipMap" in tree:
            tree["m_MipMap"] = self.count > 1
        if "m_StreamingMipmaps" in tree:
            tree["m_StreamingMipmaps"] = False
        return tree


def prepare_upscaled_sources(sources, *, image_decoder, max_pixels, max_total_bytes,
                             preserve_main=False):
    """Return enlarged source views, diagnostics and their reserved byte budget.

    With ``preserve_main``, Main images stay native and auxiliary maps are
    enlarged only enough to share the same texel-density ratio to Main across
    sources. This allows native Main pixels to move together with their maps.
    Returns None when no enlargement is necessary. Unsupported combinations
    raise AtlasCompatibilityError before decoding or changing any Unity object.
    Full authored mip chains require an isotropic power-of-two enlargement so
    their authored mip selection can be shifted exactly, rather than regenerated.
    """
    slots, _ = _check_profiles(sources, [])
    main_sizes = None
    if preserve_main:
        main_objects = [_texture(source, "_MainTex") for source in sources]
        if any(obj is None for obj in main_objects):
            raise AtlasCompatibilityError("every source needs its native Main texture")
        main_sizes = [_texture_key(obj)[:2] for obj in main_objects]
    plans, normalized_bytes, receiver_bytes = [], 0, 0
    largest_original, reserved = 0, 0
    for slot in slots:
        objects = [_texture(source, slot) for source in sources]
        if any(obj is None for obj in objects):
            raise AtlasCompatibilityError(slot + " needs a local texture on every source for enlargement")
        keys = [_texture_key(obj) for obj in objects]
        if not preserve_main:
            sizes = [(max(key[0] for key in keys), max(key[1] for key in keys))] * len(sources)
        elif slot == "_MainTex":
            sizes = main_sizes
        else:
            density = [max(Fraction(key[axis], main[axis]) for key, main in zip(keys, main_sizes))
                       for axis in (0, 1)]
            exact_sizes = [tuple(main[axis] * density[axis] for axis in (0, 1)) for main in main_sizes]
            if any(value.denominator != 1 for size in exact_sizes for value in size):
                raise AtlasCompatibilityError(slot + " cannot share the Main pixel ratio at integer texture dimensions")
            sizes = [tuple(int(value) for value in size) for size in exact_sizes]
        for key in keys:
            if key[4:6] != keys[0][4:6] or key[5][1] > 1:
                raise AtlasCompatibilityError(slot + " sampler/color-space settings are incompatible")
            if (key[3] > 1) != (keys[0][3] > 1):
                raise AtlasCompatibilityError(slot + " mipmapping policies differ")
            if key[3] not in (1, max(key[:2]).bit_length()):
                raise AtlasCompatibilityError(slot + " has an unsupported partial authored mip chain")
        for index, (obj, key, (width, height)) in enumerate(zip(objects, keys, sizes)):
            if width > 4096 or height > 4096 or width * height > max_pixels:
                raise AtlasCompatibilityError(slot + " enlargement exceeds the configured pixel budget or dimension limit")
            count = max(width, height).bit_length() if key[3] > 1 else 1
            size_bytes = _chain_bytes(width, height, count)
            normalized_bytes += size_bytes
            if index == 0:
                receiver_bytes += size_bytes
            old_width, old_height, _, old_count = key[:4]
            largest_original = max(largest_original, _chain_bytes(old_width, old_height, old_count))
            if (old_width, old_height) == (width, height):
                continue
            shift = 0
            if count > 1:
                factor, remainder = divmod(width, old_width)
                if (remainder or factor < 1 or factor & (factor - 1)
                        or height != old_height * factor):
                    raise AtlasCompatibilityError(slot + " authored mip enlargement requires a uniform power-of-two scale")
                shift = factor.bit_length() - 1
            plans.append((index, slot, obj, (width, height), count, shift))
            reserved += size_bytes
    if not plans:
        return None
    # Reserve lazy expanded payloads in addition to the reuse baker's decoded
    # arrays/output. Include bytearray->bytes copies and the original mip decode.
    if normalized_bytes + receiver_bytes + reserved * 2 + largest_original > max_total_bytes:
        raise AtlasCompatibilityError("texture enlargement and UV reuse exceed the memory budget")
    enlarged = [replace(source, tree=copy.deepcopy(source.tree), objects=dict(source.objects)) for source in sources]
    messages, target_views = [], {}
    decoder = image_decoder or _decode_default
    for index, slot, obj, size, count, shift in plans:
        source = enlarged[index]
        path_id = min([0, *source.objects]) - 1
        view = _UpscaledTexture(obj, size, count, shift, decoder)
        source.objects[path_id] = view
        env = _pairs(source.tree, "m_TexEnvs")[slot]
        env["m_Texture"] = {"m_FileID": 0, "m_PathID": path_id}
        old = obj.read()
        messages.append(f"{source.name}: enlarged {slot} from {old.m_Width}x{old.m_Height} to {size[0]}x{size[1]} for UV reuse with nearest pixels and no padding.")
        if index == 0:
            target_views[slot] = view
    return enlarged, messages, reserved, target_views


def finish_upscaled_reuse(baked, messages, target_views):
    """Keep enlarged receiver maps even if normalized sources became identical."""
    if baked.identity and target_views:
        for slot, view in target_views.items():
            baked.textures[slot] = AtlasTexture(view.read_typetree(), view.template,
                                              *view.size, view.count)
        baked.identity = False
    baked.diagnostics = tuple(messages) + baked.diagnostics
    return baked
