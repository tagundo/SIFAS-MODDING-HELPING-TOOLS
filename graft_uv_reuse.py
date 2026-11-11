"""Optional same-coordinate texture graft into geometry-unused receiver UVs.

Vacancy is measured from native texture texels touched by triangles and their
original point/linear sampler, never from color or alpha. No border pixels,
padding, UV inset, or texture resizing are generated. Unsupported combinations
return None so the caller can use the ordinary atlas path.
"""
import copy
import math

from graft_texture_atlas import (
    AtlasBake, AtlasCompatibilityError, AtlasTexture, UVTransform,
    _check_profiles, _decode_default, _mip_images, _pairs, _pointer_identity,
    _indices, _texture, _texture_key, _verify_member,
)


class _CoverageLimit(ValueError):
    pass


def _triangle_texels(uv, faces, width, height, linear, wraps, budget):
    """Closed triangle/AABB intersection, tiled to bound temporary arrays.

    A native texel contributes to a nearest sample within its unit square.
    Linear sampling extends that support by half a texel on each side. This
    copies existing contributing source texels; it does not create padding.
    """
    import numpy as np
    mask = np.zeros((height, width), dtype=bool)
    radius = .5 if linear else 0.
    half = .5 + radius
    for face in faces:
        triangle = uv[face, :2] * (width, height)
        low, high = triangle.min(axis=0), triangle.max(axis=0)
        x0, y0 = np.floor(low - radius).astype(int) - 1
        x1, y1 = np.floor(high + radius).astype(int)
        # Keep the native sampler's small virtual border, then fold covered
        # contributors through Repeat/Clamp/Mirror. Clipping first would miss
        # opposite-edge texels sampled by a triangle near UV 0 or 1.
        if x1 < x0 or y1 < y0:
            continue
        budget[0] -= (x1 - x0 + 1) * (y1 - y0 + 1)
        if budget[0] < 0:
            raise _CoverageLimit("UV triangle coverage exceeds the bounded reuse raster budget")
        axes = []
        for first, second in zip(triangle, np.roll(triangle, -1, axis=0)):
            edge = second - first
            axis = np.array([-edge[1], edge[0]])
            projection = triangle @ axis
            axes.append((axis, projection.min(), projection.max()))
        xs = np.arange(x0, x1 + 1, dtype=float)[None, :] + .5
        mapped_x = _indices(np.arange(x0, x1 + 1), width, wraps[0])
        for start in range(y0, y1 + 1, 64):
            stop = min(y1 + 1, start + 64)
            ys = np.arange(start, stop, dtype=float)[:, None] + .5
            covered = ((xs + half >= low[0] - 1e-9) & (xs - half <= high[0] + 1e-9)
                       & (ys + half >= low[1] - 1e-9) & (ys - half <= high[1] + 1e-9))
            for axis, minimum, maximum in axes:
                center = xs * axis[0] + ys * axis[1]
                extent = half * (abs(axis[0]) + abs(axis[1]))
                covered &= (center + extent >= minimum - 1e-9) & (center - extent <= maximum + 1e-9)
            rows, columns = np.nonzero(covered)
            mapped_y = _indices(np.arange(start, stop), height, wraps[1])
            # Source images use top-left rows; Unity mesh UVs use bottom-left.
            mask[height - 1 - mapped_y[rows], mapped_x[columns]] = True
    return mask


def _prepare_same_uv(sources, mesh_tree, original_group_count, *, image_decoder=None,
                     diagnostics=None, max_pixels=16777216, max_total_bytes=268435456,
                     max_raster_tests=100000000):
    """Return a same-UV AtlasBake, or None with an optional fallback diagnostic.

    sources must align with the mesh's temporary material/submesh groups. The
    first implementation handles one original receiver material and any number
    of selected donor groups with equal native dimensions and mip layouts.
    Vacancy is required at every slot's base level. Coarser authored levels are
    copied under their own triangle footprints, with shared receiver/donor mip
    texels counted in diagnostics. Every other receiver texel stays unchanged.
    """
    import numpy as np
    from PIL import Image
    import costume_part_transplant as part

    sources = list(sources)
    def decline(reason):
        if diagnostics is not None:
            diagnostics.append("Empty UV reuse unavailable: " + str(reason) + "; using the texture atlas.")
        return None
    if original_group_count != 1:
        return decline("this mode requires one original receiver Body material")
    if not 2 <= len(sources) <= 64:
        return decline("choose between one and 63 donor material groups")
    if any(type(value) is not int or value <= 0 for value in (max_pixels, max_total_bytes, max_raster_tests)):
        return decline("invalid texture or raster limits")
    local_diagnostics = []
    try:
        for source in sources:
            _verify_member(source)
        slots, features = _check_profiles(sources, local_diagnostics)
        if "_MATCAP_ON" in features:
            caps = []
            for source in sources:
                pointer = _pairs(source.tree, "m_TexEnvs").get("_MatcapTex", {}).get("m_Texture", {})
                identity = _pointer_identity(source, pointer)
                caps.append(("external", identity) if identity and identity[0] != "local" else _texture_key(_texture(source, "_MatcapTex")))
            if any(value != caps[0] for value in caps):
                return decline("normal-driven matcap textures differ")
        groups = part.submesh_triangles(mesh_tree)
        if len(groups) != len(sources) or not any(len(group) for group in groups[1:]):
            return decline("source material groups do not match selected donor geometry")
        count, channels, strides, starts, _ = part.stream_layout(mesh_tree)
        data = np.frombuffer(bytes(mesh_tree["m_VertexData"]["m_DataSize"]), dtype="uint8")
        uv = part.read_attr(data, part.ATTR_UV0, channels, strides, starts, count)
        if uv is None or uv.shape[1] < 2 or not np.isfinite(uv[:, :2]).all():
            return decline("ordinary finite UV0 coordinates are required")
        for group in groups:
            if np.any(group < 0) or np.any(group >= count):
                return decline("a source triangle references an invalid vertex")
            if len(group) and (np.any(uv[group, :2] < 0) or np.any(uv[group, :2] > 1)):
                return decline("selected or retained UVs repeat outside the ordinary 0–1 range")
        slot_objects = {}
        output_bytes = decoded_bytes = 0
        identical = True
        for slot in slots:
            objects = [_texture(source, slot) for source in sources]
            if any(obj is None for obj in objects):
                return decline(slot + " has an implicit or missing source texture")
            keys = [_texture_key(obj) for obj in objects]
            identical &= all(key == keys[0] for key in keys)
            width, height, _, mip_count, color_space, sampler, _ = keys[0]
            if width * height > max_pixels:
                return decline(slot + " exceeds the configured pixel budget")
            for key in keys[1:]:
                if key[:2] != (width, height) or key[3] != mip_count:
                    return decline(slot + " native texture dimensions or authored mip counts differ")
                if key[4:6] != (color_space, sampler):
                    return decline(slot + " sampler or color-space settings differ")
            if sampler[1] > 1:
                return decline(slot + " uses anisotropic sampling, which requires the atlas path")
            chain_bytes = sum(max(1, width >> level) * max(1, height >> level) * 4 for level in range(mip_count))
            output_bytes += chain_bytes
            decoded_bytes += chain_bytes * len(objects)
            slot_objects[slot] = (objects, width, height, mip_count, sampler)
        if identical:
            local_diagnostics.append("Original texture sets are identical; original UVs and texture objects retained.")
            return AtlasBake(tuple(UVTransform() for _ in sources), {}, tuple(local_diagnostics), True, 1)
        if output_bytes + decoded_bytes > max_total_bytes:
            return decline("decoded source images and patched RGBA32 mip payloads exceed the memory budget")
        masks = {}
        budget = [max_raster_tests]
        mask_bytes = [0]
        def coverage(group_index, width, height, sampler):
            linear, wraps = sampler[0] != 0, sampler[-2:]
            key = group_index, width, height, linear, wraps
            if key not in masks:
                if output_bytes + decoded_bytes + mask_bytes[0] + width * height > max_total_bytes:
                    raise _CoverageLimit("UV occupancy masks and decoded images exceed the memory budget")
                masks[key] = _triangle_texels(uv, groups[group_index], width, height, linear, wraps, budget)
                mask_bytes[0] += width * height
            return masks[key]
        # Check every active texture's native sampling footprint before decode.
        for slot, (_, width, height, _, sampler) in slot_objects.items():
            receiver = coverage(0, width, height, sampler)
            for group_index in range(1, len(groups)):
                if np.any(receiver & coverage(group_index, width, height, sampler)):
                    return decline(slot + " donor UVs touch texture texels already used by retained receiver triangles")
        textures = {}
        decoder = image_decoder or _decode_default
        coarse_receiver = coarse_donors = 0
        for slot, (objects, width, height, mip_count, sampler) in slot_objects.items():
            chains = [_mip_images(obj, decoder) for obj in objects]
            base_masks = [coverage(index, width, height, sampler) for index in range(len(groups))]
            for first in range(1, len(groups)):
                for second in range(1, first):
                    overlap = base_masks[first] & base_masks[second]
                    if np.any(overlap) and np.any(np.asarray(chains[first][0])[overlap] != np.asarray(chains[second][0])[overlap]):
                        return decline(slot + " selected donor groups overlap with different source pixels")
            payload = bytearray()
            for level in range(mip_count):
                w, h = max(1, width >> level), max(1, height >> level)
                receiver = coverage(0, w, h, sampler)
                result = np.asarray(chains[0][level]).copy()
                prior_donors = np.zeros((h, w), dtype=bool)
                for group_index in range(1, len(groups)):
                    mask = coverage(group_index, w, h, sampler)
                    if level:
                        coarse_receiver += int(np.count_nonzero(receiver & mask))
                        coarse_donors += int(np.count_nonzero(prior_donors & mask))
                    result[mask] = np.asarray(chains[group_index][level])[mask]
                    prior_donors |= mask
                payload.extend(Image.fromarray(result, "RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
            template = objects[0]
            tree = copy.deepcopy(template.read_typetree())
            tree.update(m_TextureFormat=4, m_CompleteImageSize=len(payload), m_MipCount=mip_count)
            tree["image data"] = bytes(payload)
            tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
            if "m_MipMap" in tree:
                tree["m_MipMap"] = mip_count > 1
            if "m_StreamingMipmaps" in tree:
                tree["m_StreamingMipmaps"] = False
            textures[slot] = AtlasTexture(tree, template, width, height, mip_count)
        local_diagnostics.append("Reused empty receiver UV areas at the original texture resolution; donor UVs unchanged, selected source pixels copied directly with no padding.")
        if coarse_receiver or coarse_donors:
            local_diagnostics.append(f"Authored coarse mip footprints share {coarse_receiver} receiver and {coarse_donors} donor texels; selected donor mip pixels are applied in material order.")
        return AtlasBake(tuple(UVTransform() for _ in sources), textures, tuple(local_diagnostics), False, len(sources))
    except (AtlasCompatibilityError, _CoverageLimit, NotImplementedError) as error:
        return decline(error)


def _empty_rectangles(used, width, height, residue, alignment, maximum):
    """Yield bounded empty native-pixel rectangles using a summed-area table."""
    import numpy as np
    if width > used.shape[1] or height > used.shape[0]:
        return
    integral = np.zeros((used.shape[0] + 1, used.shape[1] + 1), dtype="uint32")
    integral[1:, 1:] = used[::-1]
    integral.cumsum(axis=0, out=integral)
    integral.cumsum(axis=1, out=integral)
    xs = np.arange(residue[0] % alignment[0], used.shape[1] - width + 1, alignment[0], dtype="int64")
    found = 0
    for y in range(residue[1] % alignment[1], used.shape[0] - height + 1, alignment[1]):
        occupied = (integral[y + height, xs + width] - integral[y, xs + width]
                    - integral[y + height, xs] + integral[y, xs])
        for x in xs[occupied == 0]:
            yield int(x), y
            found += 1
            if found >= maximum:
                return


def _prepare_relocated_uv(sources, mesh_tree, original_group_count, *, image_decoder,
                          diagnostics, max_pixels, max_total_bytes, max_raster_tests,
                          max_candidates=4096):
    import numpy as np
    from PIL import Image
    import costume_part_transplant as part
    def decline(reason):
        diagnostics.append("UV relocation unavailable: " + str(reason) + "; using the texture atlas.")
        return None
    if original_group_count != 1 or not 2 <= len(sources) <= 64:
        return decline("one original receiver material and at most 63 donor groups are required")
    messages = []
    try:
        for source in sources:
            _verify_member(source)
        slots, features = _check_profiles(sources, messages)
        # Matcap is normal-driven and cannot be relocated by a UV transform.
        if "_MATCAP_ON" in features:
            caps = []
            for source in sources:
                pointer = _pairs(source.tree, "m_TexEnvs").get("_MatcapTex", {}).get("m_Texture", {})
                identity = _pointer_identity(source, pointer)
                caps.append(("external", identity) if identity and identity[0] != "local" else _texture_key(_texture(source, "_MatcapTex")))
            if any(key != caps[0] for key in caps):
                return decline("normal-driven matcap textures differ")
        groups = part.submesh_triangles(mesh_tree)
        if len(groups) != len(sources) or not any(len(group) for group in groups[1:]):
            return decline("material groups do not match selected donor geometry")
        count, channels, strides, starts, _ = part.stream_layout(mesh_tree)
        data = np.frombuffer(bytes(mesh_tree["m_VertexData"]["m_DataSize"]), dtype="uint8")
        uv = part.read_attr(data, part.ATTR_UV0, channels, strides, starts, count)
        if uv is None or uv.shape[1] < 2 or not np.isfinite(uv[:, :2]).all():
            return decline("ordinary finite UV0 coordinates are required")
        for group in groups:
            if np.any(group < 0) or np.any(group >= count):
                return decline("a triangle references an invalid vertex")
            if len(group) and (np.any(uv[group, :2] < 0) or np.any(uv[group, :2] > 1)):
                return decline("source UVs repeat outside the ordinary 0–1 range")
        objects = {slot: [_texture(source, slot) for source in sources] for slot in slots}
        if any(obj is None for row in objects.values() for obj in row):
            return decline("every relocated shader slot needs a native local texture")
        keys = {slot: [_texture_key(obj) for obj in row] for slot, row in objects.items()}
        main = slots[0]
        target_width, target_height = keys[main][0][:2]
        scales = [UVTransform().scale]
        for index in range(1, len(sources)):
            donor_width, donor_height = keys[main][index][:2]
            scales.append((donor_width / target_width, donor_height / target_height))
        output_bytes = decoded_bytes = 0
        align_x = align_y = 1
        for slot, row in keys.items():
            tw, th = row[0][:2]
            align_x = math.lcm(align_x, target_width // math.gcd(target_width, tw))
            align_y = math.lcm(align_y, target_height // math.gcd(target_height, th))
            if tw * th > max_pixels:
                return decline(slot + " exceeds the configured pixel budget")
            for index, key in enumerate(row):
                dw, dh, _, mip_count, _, sampler, _ = key
                if dw * dh > max_pixels:
                    return decline(slot + " source exceeds the configured pixel budget")
                if key[4:6] != row[0][4:6] or sampler[1] > 1:
                    return decline(slot + " sampler/color-space settings are incompatible")
                mw, mh = keys[main][index][:2]
                if dw * target_width != mw * tw or dh * target_height != mh * th:
                    return decline("Main/Rim/native slot resolution ratios do not share one UV transform")
                if mip_count not in (1, max(dw, dh).bit_length()):
                    return decline(slot + " has an unsupported partial authored mip chain")
                chain_size = sum(max(1, dw >> level) * max(1, dh >> level) * 4 for level in range(mip_count))
                decoded_bytes += chain_size
                if index == 0:
                    output_bytes += chain_size
            if any((key[3] > 1) != (row[0][3] > 1) for key in row):
                return decline(slot + " mipmapping policies differ")
            if any(key[3] > row[0][3] for key in row):
                return decline(slot + " donor authored mip chain is longer than the unchanged receiver texture can hold")
        # Include the integral search table and copied destination arrays in the
        # working budget before decoding any original texture.
        working = output_bytes * 2 + decoded_bytes + (target_width + 1) * (target_height + 1) * 4
        if working > max_total_bytes:
            return decline("decoded images and relocation search exceed the memory budget")
        budget, mask_bytes = [max_raster_tests], [0]
        def coverage(coordinates, index, width, height, sampler):
            required = width * height
            if working + mask_bytes[0] + required > max_total_bytes:
                raise _CoverageLimit("relocation occupancy masks exceed the memory budget")
            return _triangle_texels(coordinates, groups[index], width, height, sampler[0] != 0, sampler[-2:], budget)
        used = {}
        for slot, row in keys.items():
            tw, th = row[0][:2]
            used[slot] = coverage(uv, 0, tw, th, row[0][5])
            mask_bytes[0] += tw * th
        transforms = [UVTransform()]
        placements = []
        for index in range(1, len(sources)):
            dw, dh = keys[main][index][:2]
            donor_mask = coverage(uv, index, dw, dh, keys[main][index][5])
            rows, columns = np.nonzero(donor_mask)
            if not len(rows):
                transforms.append(UVTransform())
                placements.append({slot: np.zeros_like(value) for slot, value in used.items()})
                continue
            left, right = int(columns.min()), int(columns.max()) + 1
            bottom, top = dh - int(rows.max()) - 1, dh - int(rows.min())
            chosen = None
            for x, y in _empty_rectangles(used[main], right - left, top - bottom,
                                           (left, bottom), (align_x, align_y), max_candidates):
                offset = ((x - left) / target_width, (y - bottom) / target_height)
                transform = UVTransform(scales[index], offset)
                moved = uv.copy()
                vertices = np.unique(groups[index])
                moved[vertices] = transform.remap_uv(moved[vertices])
                if len(vertices) and (np.any(moved[vertices, :2] < 0) or np.any(moved[vertices, :2] > 1)):
                    continue
                candidate = {}
                valid = True
                for slot, row in keys.items():
                    tw, th = row[0][:2]
                    sw, sh = row[index][:2]
                    sampler = row[0][5]
                    # If target wrapping crosses a differently sized source
                    # period, a single real texel could require two colors.
                    if sampler[0] != 0 and len(vertices):
                        if tw % sw and (moved[vertices, 0].min() * tw < .5 or moved[vertices, 0].max() * tw > tw - .5):
                            valid = False
                            break
                        if th % sh and (moved[vertices, 1].min() * th < .5 or moved[vertices, 1].max() * th > th - .5):
                            valid = False
                            break
                    mask = coverage(moved, index, tw, th, sampler)
                    if np.any(mask & used[slot]):
                        valid = False
                        break
                    candidate[slot] = mask
                if valid:
                    chosen = transform, candidate
                    break
            if chosen is None:
                return decline("no common free native-pixel rectangle fits the selected donor patch within the bounded search")
            transform, candidate = chosen
            transforms.append(transform)
            placements.append(candidate)
            for slot, mask in candidate.items():
                used[slot] |= mask
                mask_bytes[0] += mask.nbytes
            messages.append(f"{sources[index].name}: moved selected UV patch to pixel offset ({round(transform.offset[0] * target_width)}, {round(transform.offset[1] * target_height)}) at native pixel detail.")
        decoder = image_decoder or _decode_default
        textures, shared_coarse = {}, 0
        for slot, row in keys.items():
            chains = [_mip_images(obj, decoder) for obj in objects[slot]]
            tw, th, _, count, _, sampler, _ = row[0]
            payload = bytearray()
            for level in range(count):
                w, h = max(1, tw >> level), max(1, th >> level)
                result = np.asarray(chains[0][level]).copy()
                receiver_mask = coverage(uv, 0, w, h, sampler)
                for index, transform in enumerate(transforms[1:], 1):
                    source_image = chains[index][min(level, len(chains[index]) - 1)]
                    sw, sh = source_image.size
                    if level == 0:
                        mask = placements[index - 1][slot]
                    else:
                        moved = uv.copy()
                        vertices = np.unique(groups[index])
                        moved[vertices] = transform.remap_uv(moved[vertices])
                        mask = coverage(moved, index, w, h, sampler)
                        shared_coarse += int(np.count_nonzero(mask & receiver_mask))
                    ys, xs = np.nonzero(mask)
                    # Grid-aligned at level 0. At coarse authored levels use
                    # nearest texel centers; source mip images remain original.
                    dx, dy = transform.offset[0] * w, transform.offset[1] * h
                    sx = _indices(np.floor(xs - dx + .5).astype("int64"), sw, sampler[-2])
                    sy = _indices(np.floor((h - 1 - ys) - dy + .5).astype("int64"), sh, sampler[-1])
                    result[ys, xs] = np.asarray(source_image)[sh - 1 - sy, sx]
                payload.extend(Image.fromarray(result, "RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
            template = objects[slot][0]
            tree = copy.deepcopy(template.read_typetree())
            tree.update(m_TextureFormat=4, m_CompleteImageSize=len(payload), m_MipCount=count)
            tree["image data"] = bytes(payload)
            tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
            if "m_MipMap" in tree:
                tree["m_MipMap"] = count > 1
            if "m_StreamingMipmaps" in tree:
                tree["m_StreamingMipmaps"] = False
            textures[slot] = AtlasTexture(tree, template, tw, th, count)
        messages.append("Relocated selected donor UVs into unused receiver texture areas; native source pixels copied directly, original texture dimensions retained, no padding.")
        if shared_coarse:
            messages.append(f"Relocated authored coarse mip footprints share {shared_coarse} receiver texels; selected donor mip pixels are applied in material order.")
        return AtlasBake(tuple(transforms), textures, tuple(messages), False, len(sources))
    except (AtlasCompatibilityError, _CoverageLimit, NotImplementedError) as error:
        return decline(error)


def prepare_uv_reuse(sources, mesh_tree, original_group_count, *, image_decoder=None,
                     diagnostics=None, max_pixels=16777216, max_total_bytes=268435456,
                     max_raster_tests=100000000, relocate_empty_uv=False):
    """Prefer original donor UVs; optionally relocate a native-pixel patch."""
    sources = list(sources)
    reasons = []
    options = dict(image_decoder=image_decoder, max_pixels=max_pixels,
                   max_total_bytes=max_total_bytes, max_raster_tests=max_raster_tests)
    result = _prepare_same_uv(sources, mesh_tree, original_group_count, diagnostics=reasons, **options)
    if result is not None:
        return result
    if relocate_empty_uv:
        relocated = []
        result = _prepare_relocated_uv(sources, mesh_tree, original_group_count,
                                      diagnostics=relocated, **options)
        if result is not None:
            return result
        reasons.extend(relocated)
    if diagnostics is not None:
        diagnostics.extend(reasons)
    return None
