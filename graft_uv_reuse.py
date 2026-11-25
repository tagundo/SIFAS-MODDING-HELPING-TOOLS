"""Optional same-coordinate texture graft into geometry-unused receiver UVs.

Vacancy is measured from texture texels touched by triangles and their original
point/linear sampler, never from color or alpha. Optional detached enlargement
matches corresponding source maps before retrying. No border pixels, padding
or UV inset are generated. Unsupported combinations return None so the caller
can use the ordinary atlas path (or refuse, when the caller has no atlas).

``reserved`` occupancy lists texture areas that other surfaces sample from the
same receiver texture: their UV0 triangles and fixed UV rectangles. These masks
only decide where donor texels may go; they never add or change pixels.
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


def _reserved_texels(reserved, width, height, linear, wraps, budget):
    """Texels sampled by other receiver-texture surfaces at one texture size.

    ``reserved`` is ``{"surfaces": [(uv, faces), ...], "rects": [(u0, v0,
    u1, v1), ...]}`` in normalized receiver UVs. Rectangles are closed and are
    widened by the sampler's own support, exactly like triangle footprints.
    """
    import numpy as np
    mask = np.zeros((height, width), dtype=bool)
    if not reserved:
        return mask
    for uv, faces in reserved.get("surfaces", ()):
        if len(faces):
            mask |= _triangle_texels(uv, faces, width, height, linear, wraps, budget)
    radius = .5 if linear else 0.
    for u0, v0, u1, v1 in reserved.get("rects", ()):
        xs, ys = np.arange(width), np.arange(height)
        columns = (xs <= u1 * width + radius + 1e-9) & (xs + 1 >= u0 * width - radius - 1e-9)
        rows = (ys <= v1 * height + radius + 1e-9) & (ys + 1 >= v0 * height - radius - 1e-9)
        # Source images use top-left rows; Unity UVs use bottom-left.
        mask[np.ix_(rows[::-1], columns)] = True
    return mask


class PlacementDecline(str):
    """A decline diagnostic (its text) that also records why it declined.

    ``kind`` is "occupied" (same-position texels already used), "no_space"
    (no free texels for an island), "search_limit" or "other"; ``details``
    names the slot and island, so callers can phrase their own refusal.
    """

    def __new__(cls, text, kind="other", **details):
        value = super().__new__(cls, text)
        value.kind, value.details = kind, details
        return value


def _fallback_note(atlas_fallback):
    return "; using the texture atlas." if atlas_fallback else "."


def _prepare_same_uv(sources, mesh_tree, original_group_count, *, image_decoder=None,
                     diagnostics=None, max_pixels=16777216, max_total_bytes=268435456,
                     max_raster_tests=100000000, reserved=None, atlas_fallback=True):
    """Return a same-UV AtlasBake, or None with an optional fallback diagnostic.

    sources must align with the mesh's temporary material/submesh groups. The
    first implementation handles one original receiver material and any number
    of selected donor groups with equal native dimensions and mip layouts.
    Vacancy is required at every slot's base level. Coarser authored levels are
    copied under their own triangle footprints, with shared receiver/donor mip
    texels counted in diagnostics. Every other receiver texel stays unchanged.
    Texels in ``reserved`` count as used by the receiver.
    """
    import numpy as np
    from PIL import Image
    import costume_part_transplant as part

    sources = list(sources)
    def decline(reason, kind="other", **details):
        if diagnostics is not None:
            diagnostics.append(PlacementDecline("Empty UV reuse unavailable: " + str(reason) + _fallback_note(atlas_fallback),
                                                kind, **details))
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
                if group_index == 0 and reserved:
                    masks[key] |= _reserved_texels(reserved, width, height, linear, wraps, budget)
                mask_bytes[0] += width * height
            return masks[key]
        # Check every active texture's native sampling footprint before decode.
        for slot, (_, width, height, _, sampler) in slot_objects.items():
            receiver = coverage(0, width, height, sampler)
            for group_index in range(1, len(groups)):
                if np.any(receiver & coverage(group_index, width, height, sampler)):
                    return decline(slot + " donor UVs touch texture texels already used by retained receiver triangles"
                                   + (" or by other surfaces of this texture" if reserved else ""), "occupied", slot=slot)
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


def _overlap_counts(used, shape):
    """Count used texels under ``shape`` at every placement, by FFT correlation.

    Returns an array indexed by the shape's top-left image row/column. Only an
    exact zero count means the shape's own texels are all free there.
    """
    import numpy as np
    height, width = used.shape
    h, w = shape.shape
    spectrum = np.fft.rfft2(used.astype(np.float64)) * np.fft.rfft2(shape[::-1, ::-1].astype(np.float64), s=(height, width))
    correlation = np.fft.irfft2(spectrum, s=(height, width))
    # Circular entries at and after (h - 1, w - 1) equal the linear sums.
    return correlation[h - 1:, w - 1:] > .5


# Offsets on these power-of-two grids keep that many authored mip levels exact
# (level L is exact when the offset is a multiple of 2**L). Coarser grids are
# tried first; the minimal grid required by the auxiliary maps comes last. A
# grid is only preferred while it still offers 16 positions along each axis,
# so small textures keep the ordinary bottom-left first-fit search.
_PREFERRED_GRIDS = (64, 32, 16, 8, 4, 2, 1)
_MIN_GRID_POSITIONS = 16
# Coarse authored Main levels whose footprints are checked when choosing among
# free positions: an island is first placed where its level-L footprint (an
# exact shift for offsets on a 2**L grid) also misses used texels, so the
# donor's coarse mips do not cover a neighbour's. This only picks a position.
_COARSE_LEVELS = 6


def _grid_level(grid):
    """Mip levels shifted exactly by any offset on this grid (2**L divides it)."""
    return min((value & -value).bit_length() - 1 for value in grid)


def _prepare_relocated_uv(sources, mesh_tree, original_group_count, *, image_decoder,
                          diagnostics, max_pixels, max_total_bytes, max_raster_tests,
                          max_candidates=4096, reserved=None, atlas_fallback=True):
    """Move every donor group by its own integer pixel offset into free texels.

    Groups are placed largest first. Each placement needs only that group's own
    sampler footprint to be free, not a whole bounding rectangle, so a caller
    that splits a selection into UV islands places each island separately.
    Level 0 copies are exact native texels; coarse authored mips use their own
    images at the nearest texel, which is exact when the offset is a multiple
    of 2**level. Free space is the receiver's group 0 plus ``reserved``.
    Among free positions, those whose exactly shifted coarse Main footprints
    (up to _COARSE_LEVELS) also miss used texels are tried first.
    """
    import numpy as np
    from PIL import Image
    import costume_part_transplant as part
    def decline(reason, kind="other", **details):
        diagnostics.append(PlacementDecline("UV relocation unavailable: " + str(reason) + _fallback_note(atlas_fallback),
                                            kind, **details))
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
        # Island groups repeat one donor material: read each texture object once.
        key_cache = {}
        def texture_key(obj):
            if id(obj) not in key_cache:
                key_cache[id(obj)] = (obj, _texture_key(obj))
            return key_cache[id(obj)][1]
        keys = {slot: [texture_key(obj) for obj in row] for slot, row in objects.items()}
        main = slots[0]
        target_width, target_height = keys[main][0][:2]
        scales = [UVTransform().scale]
        for index in range(1, len(sources)):
            donor_width, donor_height = keys[main][index][:2]
            scales.append((donor_width / target_width, donor_height / target_height))
        output_bytes = decoded_bytes = 0
        align_x = align_y = 1
        counted = set()
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
                if id(objects[slot][index]) not in counted:
                    counted.add(id(objects[slot][index]))
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
            sampler = row[0][5]
            used[slot] = coverage(uv, 0, tw, th, sampler)
            if reserved:
                used[slot] |= _reserved_texels(reserved, tw, th, sampler[0] != 0, sampler[-2:], budget)
            mask_bytes[0] += tw * th
        # Used texels of the coarse authored Main levels, kept up to date as
        # islands are placed (placement preference only).
        main_sampler = keys[main][0][5]
        coarse_used = {}
        for level in range(1, min(_COARSE_LEVELS, keys[main][0][3] - 1) + 1):
            if target_width % (1 << level) or target_height % (1 << level):
                break
            w, h = target_width >> level, target_height >> level
            coarse_used[level] = coverage(uv, 0, w, h, main_sampler)
            if reserved:
                coarse_used[level] |= _reserved_texels(reserved, w, h, main_sampler[0] != 0, main_sampler[-2:], budget)
            mask_bytes[0] += w * h
        transforms = [UVTransform()] + [None] * (len(sources) - 1)
        placements = [None] * len(sources)
        footprints = {}
        for index in range(1, len(sources)):
            dw, dh = keys[main][index][:2]
            donor_mask = coverage(uv, index, dw, dh, keys[main][index][5])
            rows, columns = np.nonzero(donor_mask)
            footprints[index] = rows, columns
        groups_total = len(sources) - 1
        order = sorted(range(1, len(sources)), key=lambda index: (-len(footprints[index][0]), index))
        grids = []
        largest = max(1, min(target_width, target_height) // _MIN_GRID_POSITIONS)
        for step in _PREFERRED_GRIDS:
            if step > largest:
                continue
            grid = (math.lcm(align_x, step), math.lcm(align_y, step))
            if grid not in grids:
                grids.append(grid)
        if (align_x, align_y) not in grids:
            grids.append((align_x, align_y))
        for rank, index in enumerate(order, 1):
            dw, dh = keys[main][index][:2]
            rows, columns = footprints[index]
            if not len(rows):
                transforms[index] = UVTransform()
                placements[index] = {slot: (np.empty(0, "int64"), np.empty(0, "int64")) for slot in used}
                continue
            left, right = int(columns.min()), int(columns.max()) + 1
            bottom, top = dh - int(rows.max()) - 1, dh - int(rows.min())
            # Place the island's own texel footprint, not its bounding box: the
            # overlap count finds every position where those texels are free.
            shape = np.zeros((top - bottom, right - left), dtype=bool)
            shape[rows - int(rows.min()), columns - left] = True
            island = dict(island=rank, islands=groups_total, width=right - left, height=top - bottom)
            if shape.shape[0] > used[main].shape[0] or shape.shape[1] > used[main].shape[1]:
                return decline(f"island {rank} of {groups_total} is larger than the receiver texture",
                               "no_space", slot=main, **island)
            spectrum_bytes = target_height * (target_width // 2 + 1) * 16 * 3
            if working + mask_bytes[0] + spectrum_bytes > max_total_bytes:
                raise _CoverageLimit("the free-area search exceeds the memory budget")
            occupied = _overlap_counts(used[main], shape)
            vertices = np.unique(groups[index])
            # The island's own coarse Main footprints, for the same overlap
            # test at each level where an aligned offset shifts them exactly.
            coarse = []
            for level, used_level in coarse_used.items():
                if dw % (1 << level) or dh % (1 << level):
                    break
                level_rows, level_columns = np.nonzero(
                    coverage(uv, index, dw >> level, dh >> level, keys[main][index][5]))
                if not len(level_rows):
                    break
                level_left, level_top_row = int(level_columns.min()), int(level_rows.min())
                level_shape = np.zeros((int(level_rows.max()) - level_top_row + 1,
                                        int(level_columns.max()) - level_left + 1), dtype=bool)
                level_shape[level_rows - level_top_row, level_columns - level_left] = True
                if level_shape.shape[0] > used_level.shape[0] or level_shape.shape[1] > used_level.shape[1]:
                    break
                level_bottom = (dh >> level) - int(level_rows.max()) - 1
                coarse.append((level, _overlap_counts(used_level, level_shape), level_left, level_bottom,
                               level_shape.shape[0]))

            def clean_levels(xs, ys):
                """Consecutive coarse levels whose shifted footprint misses used texels."""
                xs, ys = np.asarray(xs, dtype=np.int64), np.asarray(ys, dtype=np.int64)
                dx, dy = xs - left, ys - bottom
                running = np.ones(xs.shape, dtype=bool)
                score = np.zeros(xs.shape, dtype=np.int64)
                for level, level_occupied, level_left, level_bottom, level_height in coarse:
                    running &= (dx % (1 << level) == 0) & (dy % (1 << level) == 0)
                    column = level_left + (dx >> level)
                    row = level_occupied.shape[0] - 1 - (level_bottom + (dy >> level))
                    inside = ((row >= 0) & (row < level_occupied.shape[0])
                              & (column >= 0) & (column < level_occupied.shape[1]))
                    free = np.zeros(xs.shape, dtype=bool)
                    free[inside] = ~level_occupied[row[inside], column[inside]]
                    running &= free
                    score += running
                return score

            chosen, tested, exhausted, rejected = None, set(), False, {}
            # Coarser grids first (more exact authored mips). On each grid the
            # free positions are tried in order of how many of their exactly
            # shifted coarse levels also miss used texels, then bottom-left
            # first; exactness is never traded for that preference.
            for grid in grids:
                if chosen is not None or exhausted:
                    break
                if coarse and _grid_level(grid):
                    xs, ys = _candidate_arrays(occupied, shape.shape, (left, bottom), grid)
                    order = np.argsort(-clean_levels(xs, ys), kind="stable")
                    positions = zip(xs[order].tolist(), ys[order].tolist())
                else:
                    positions = _candidate_positions(occupied, shape.shape, (left, bottom), grid)
                # Main-texture footprint prefilter; every candidate is still
                # rasterized and checked for each UV-driven slot below.
                for x, y in positions:
                    if (x, y) in tested:
                        continue
                    if len(tested) >= max_candidates:
                        exhausted = True
                        break
                    tested.add((x, y))
                    offset = ((x - left) / target_width, (y - bottom) / target_height)
                    transform = UVTransform(scales[index], offset)
                    moved = uv.copy()
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
                            rejected[slot] = rejected.get(slot, 0) + 1
                            valid = False
                            break
                        candidate[slot] = np.nonzero(mask)
                    if valid:
                        chosen = transform, candidate
                        break
            label = f"island {rank} of {groups_total} ({len(rows)} texels, {right - left}×{top - bottom} px)"
            if chosen is None:
                # Main texels decide the candidates; another map that rejected
                # every one of them is the map that had no room.
                limit = max(rejected, key=lambda slot: (rejected[slot], slot != main)) if rejected else main
                where = (f"; every position free in {main} was used in {limit}" if limit != main else f" in {main}")
                if exhausted:
                    return decline(f"the search limit of {max_candidates} positions was reached before {label} "
                                   f"found free texels{where}", "search_limit", slot=limit, count=max_candidates, **island)
                return decline(f"no common free native-pixel area fits {label}{where}", "no_space", slot=limit, **island)
            transform, candidate = chosen
            transforms[index] = transform
            placements[index] = candidate
            for slot, (ys, xs) in candidate.items():
                used[slot][ys, xs] = True
                mask_bytes[0] += ys.nbytes + xs.nbytes
            dx = round(transform.offset[0] * target_width)
            dy = round(transform.offset[1] * target_height)
            clean = int(clean_levels([left + dx], [bottom + dy])[0]) if coarse else 0
            if coarse_used:
                moved = uv.copy()
                moved[vertices] = transform.remap_uv(moved[vertices])
                for level, used_level in coarse_used.items():
                    used_level |= coverage(moved, index, used_level.shape[1], used_level.shape[0], main_sampler)
            exact = max(level for level in range(13) if dx % (1 << level) == 0 and dy % (1 << level) == 0)
            messages.append(f"{sources[index].name}: {label} moved by pixel offset ({dx}, {dy}) at native pixel detail; "
                            f"authored mip levels 0–{exact} are exact copies"
                            + (f"; coarse levels 1–{clean} keep clear of used texels." if clean else "."))
        decoder = image_decoder or _decode_default
        chain_cache = {}
        def chain(obj):
            if id(obj) not in chain_cache:
                chain_cache[id(obj)] = (obj, _mip_images(obj, decoder))
            return chain_cache[id(obj)][1]
        textures, shared_coarse = {}, 0
        for slot, row in keys.items():
            chains = [chain(obj) for obj in objects[slot]]
            tw, th, _, count, _, sampler, _ = row[0]
            payload = bytearray()
            for level in range(count):
                w, h = max(1, tw >> level), max(1, th >> level)
                result = np.asarray(chains[0][level]).copy()
                receiver_mask = coverage(uv, 0, w, h, sampler)
                if reserved and level:
                    receiver_mask |= _reserved_texels(reserved, w, h, sampler[0] != 0, sampler[-2:], budget)
                for index, transform in enumerate(transforms[1:], 1):
                    source_image = chains[index][min(level, len(chains[index]) - 1)]
                    sw, sh = source_image.size
                    if level == 0:
                        ys, xs = placements[index][slot]
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
            messages.append(f"Relocated authored coarse mip footprints share {shared_coarse} texels used by the receiver or "
                            "other surfaces; selected donor mip pixels are applied in material order.")
        return AtlasBake(tuple(transforms), textures, tuple(messages), False, len(sources))
    except (AtlasCompatibilityError, _CoverageLimit, NotImplementedError) as error:
        return decline(error)


def _candidate_arrays(occupied, shape_size, residue, grid):
    """All positions of _candidate_positions as arrays, in the same order."""
    import numpy as np
    h, _ = shape_size
    rows, columns = occupied.shape
    xs = np.arange(residue[0] % grid[0], columns, grid[0], dtype="int64")
    ys = np.arange(residue[1] % grid[1], rows, grid[1], dtype="int64")
    free = ~occupied[np.ix_(rows + h - 1 - ys - h, xs)]
    y_index, x_index = np.nonzero(free)
    return xs[x_index], ys[y_index]


def _candidate_positions(occupied, shape_size, residue, grid):
    """Bottom-left grid positions where the shape's own texels are all free.

    ``occupied`` comes from _overlap_counts. Positions run bottom-up, then left
    to right, through ``residue`` on ``grid``, like the original first-fit scan.
    """
    import numpy as np
    h, w = shape_size
    rows, columns = occupied.shape
    total_height = rows + h - 1
    xs = np.arange(residue[0] % grid[0], columns, grid[0], dtype="int64")
    for y in range(residue[1] % grid[1], rows, grid[1]):
        row = total_height - y - h
        for x in xs[~occupied[row, xs]]:
            yield int(x), y


def prepare_uv_reuse(sources, mesh_tree, original_group_count, *, image_decoder=None,
                     diagnostics=None, max_pixels=16777216, max_total_bytes=268435456,
                     max_raster_tests=100000000, relocate_empty_uv=False,
                     upscale_textures_for_uv_reuse=True, uv_placement=None,
                     reserved=None, atlas_fallback=True, keep_receiver_textures=False):
    """Use the selected UV placement strategy, or compatible legacy flags.

    ``same_position`` matches map sizes and keeps UV coordinates unchanged.
    ``move_to_empty`` retains Main resolution, adapts auxiliary map ratios and
    directly searches a free destination for each donor group. ``atlas``
    requests the caller's atlas path. None retains the older independent
    reuse/enlargement/relocation flags. ``reserved`` marks receiver-texture
    texels used by other surfaces. ``atlas_fallback`` only changes wording:
    False tells the diagnostics that the caller refuses instead of atlasing.
    ``keep_receiver_textures`` keeps every receiver map at its own size (other
    surfaces sample it): only smaller donor maps may be enlarged to match, and
    a donor map needing more texels raises graft_uv_upscale.ReceiverMapsLocked.
    """
    if type(upscale_textures_for_uv_reuse) is not bool:
        raise ValueError("Texture enlargement for UV reuse must be true or false.")
    if uv_placement is not None and (type(uv_placement) is not str or uv_placement not in
                                    ("same_position", "move_to_empty", "atlas")):
        raise ValueError("Choose original UV positions, empty UV areas, or a new texture atlas.")
    sources = list(sources)
    reasons = []
    options = dict(image_decoder=image_decoder, max_pixels=max_pixels,
                   max_total_bytes=max_total_bytes, max_raster_tests=max_raster_tests,
                   reserved=reserved, atlas_fallback=atlas_fallback)
    note = _fallback_note(atlas_fallback)
    if uv_placement == "atlas":
        if diagnostics is not None:
            diagnostics.append("A new texture atlas was explicitly selected.")
        return None
    if uv_placement == "same_position":
        relocate_empty_uv, upscale_textures_for_uv_reuse = False, True
    elif uv_placement == "move_to_empty":
        from graft_uv_upscale import ReceiverMapsLocked, prepare_upscaled_sources, finish_upscaled_reuse
        moving_sources, messages, target_views = sources, [], {}
        moving_options = options
        valid_limits = all(type(value) is int and value > 0 for value in
                           (max_pixels, max_total_bytes, max_raster_tests))
        if not valid_limits:
            reasons.append("Empty UV relocation unavailable: invalid texture or raster limits" + note)
        else:
            try:
                enlarged = None
                if original_group_count == 1 and 2 <= len(sources) <= 64:
                    enlarged = prepare_upscaled_sources(sources, image_decoder=image_decoder,
                        max_pixels=max_pixels, max_total_bytes=max_total_bytes, preserve_main=True,
                        fixed_receiver=keep_receiver_textures)
                if enlarged is not None:
                    moving_sources, messages, reserved_bytes, target_views = enlarged
                    moving_options = dict(options, max_total_bytes=max_total_bytes - reserved_bytes)
                result = _prepare_relocated_uv(moving_sources, mesh_tree, original_group_count,
                                                diagnostics=reasons, **moving_options)
                if result is not None:
                    messages.insert(0, "Main texture resolutions retained; each selected UV group and its UV-driven maps moved into unused areas.")
                    return finish_upscaled_reuse(result, messages, target_views)
            except ReceiverMapsLocked:
                raise
            except AtlasCompatibilityError as error:
                reasons.append("Auxiliary texture adjustment for empty UV relocation unavailable: " + str(error) + note)
        if diagnostics is not None:
            diagnostics.extend(reasons)
        return None
    result = _prepare_same_uv(sources, mesh_tree, original_group_count, diagnostics=reasons, **options)
    if result is not None:
        return result
    enlarged = locked = None
    if (upscale_textures_for_uv_reuse and original_group_count == 1 and 2 <= len(sources) <= 64
            and all(type(value) is int and value > 0 for value in (max_pixels, max_total_bytes, max_raster_tests))):
        from graft_uv_upscale import ReceiverMapsLocked, prepare_upscaled_sources, finish_upscaled_reuse
        try:
            enlarged = prepare_upscaled_sources(sources, image_decoder=image_decoder,
                                               max_pixels=max_pixels, max_total_bytes=max_total_bytes,
                                               fixed_receiver=keep_receiver_textures)
        except ReceiverMapsLocked as error:
            if not relocate_empty_uv:
                raise
            locked = error  # Native relocation below may still fit without enlargement.
        except AtlasCompatibilityError as error:
            reasons.append("Texture enlargement for UV reuse unavailable: " + str(error) + note)
    if enlarged is not None:
        enlarged_sources, messages, reserved_bytes, target_views = enlarged
        enlarged_options = dict(options, max_total_bytes=max_total_bytes - reserved_bytes)
        enlarged_reasons = []
        result = _prepare_same_uv(enlarged_sources, mesh_tree, original_group_count,
                                  diagnostics=enlarged_reasons, **enlarged_options)
        if result is None and relocate_empty_uv:
            result = _prepare_relocated_uv(enlarged_sources, mesh_tree, original_group_count,
                                          diagnostics=enlarged_reasons, **enlarged_options)
        if result is not None:
            return finish_upscaled_reuse(result, messages, target_views)
        reasons.extend(enlarged_reasons)
    if relocate_empty_uv and enlarged is None:
        relocated = []
        result = _prepare_relocated_uv(sources, mesh_tree, original_group_count,
                                      diagnostics=relocated, **options)
        if result is not None:
            return result
        reasons.extend(relocated)
    if locked is not None:
        raise locked
    if diagnostics is not None:
        diagnostics.extend(reasons)
    return None


def split_uv_islands(sources, mesh_tree, original_group_count, *, max_groups=64):
    """Split each donor group into separately placeable UV islands.

    An island is a set of triangles connected through shared vertices. Islands
    whose native Main-texture sampler footprints share a texel stay together, so
    shared source texels move once. Returns ``(sources, mesh_tree, counts)``:
    a new mesh tree whose donor submeshes are the islands, one MaterialSource
    per island (same material, own UV bounds), and the island count of every
    original donor group. Receiver groups, vertices and UVs are unchanged; with
    nothing to split, the inputs are returned. Groups above ``max_groups`` are
    merged smallest first into their nearest island of the same material.
    """
    import dataclasses
    import numpy as np
    import costume_part_transplant as part
    sources = list(sources)
    groups = part.submesh_triangles(mesh_tree)
    if len(groups) != len(sources) or original_group_count < 1 or len(groups) <= original_group_count:
        return sources, mesh_tree, None
    count, channels, strides, starts, _ = part.stream_layout(mesh_tree)
    data = np.frombuffer(bytes(mesh_tree["m_VertexData"]["m_DataSize"]), dtype="uint8")
    uv = part.read_attr(data, part.ATTR_UV0, channels, strides, starts, count)
    if uv is None or uv.shape[1] < 2 or not np.isfinite(uv[:, :2]).all():
        return sources, mesh_tree, None
    budget = [100000000]
    per_group = []
    for index in range(original_group_count, len(groups)):
        faces = groups[index]
        if not len(faces) or np.any(faces < 0) or np.any(faces >= count):
            per_group.append([faces])
            continue
        # Union-find over vertices: triangles sharing a vertex are one island.
        parent = np.arange(count)
        def find(value):
            root = value
            while parent[root] != root:
                root = parent[root]
            while parent[value] != root:
                parent[value], value = root, parent[value]
            return root
        for a, b, c in faces:
            ra, rb, rc = find(a), find(b), find(c)
            parent[rb] = ra
            parent[find(rc)] = ra
        roots = np.array([find(face[0]) for face in faces])
        islands = [faces[roots == root] for root in dict.fromkeys(roots.tolist())]
        # Islands sampling a common texel (mirrored copies, hard-edge seams)
        # move together, so each shared source texel is copied once.
        try:
            main = _texture(sources[index], "_MainTex")
            key = _texture_key(main) if main is not None else None
        except AtlasCompatibilityError:
            key = None
        if key is not None and len(islands) > 1:
            width, height, sampler = key[0], key[1], key[5]
            owners = np.full((height, width), -1, dtype=np.int64)
            labels = list(range(len(islands)))
            def label_of(value):
                while labels[value] != value:
                    value = labels[value]
                return value
            for number, island in enumerate(islands):
                try:
                    mask = _triangle_texels(uv, island, width, height, sampler[0] != 0, sampler[-2:], budget)
                except _CoverageLimit:
                    return sources, mesh_tree, None
                for other in np.unique(owners[mask & (owners >= 0)]):
                    labels[label_of(int(other))] = label_of(number)
                owners[mask] = number
            merged = {}
            for number, island in enumerate(islands):
                merged.setdefault(label_of(number), []).append(island)
            islands = [np.concatenate(parts) for parts in merged.values()]
        per_group.append(islands)
    limit = max_groups - original_group_count
    def bounds(faces):
        values = uv[np.unique(faces), :2]
        return (*values.min(axis=0), *values.max(axis=0))
    while sum(len(islands) for islands in per_group) > limit:
        candidates = [(len(island), group, number) for group, islands in enumerate(per_group)
                      if len(islands) > 1 for number, island in enumerate(islands)]
        if not candidates:
            return sources, mesh_tree, None
        _, group, number = min(candidates)
        islands = per_group[group]
        small = islands.pop(number)
        low = bounds(small)
        def growth(other):
            high = bounds(other)
            union = (min(low[0], high[0]), min(low[1], high[1]), max(low[2], high[2]), max(low[3], high[3]))
            return (union[2] - union[0]) * (union[3] - union[1])
        nearest = min(range(len(islands)), key=lambda position: (growth(islands[position]), position))
        islands[nearest] = np.concatenate([islands[nearest], small])
    if all(len(islands) == 1 for islands in per_group):
        return sources, mesh_tree, [1] * len(per_group)
    width = 2 if mesh_tree.get("m_IndexFormat", 0) == 0 else 4
    dtype = "<u2" if width == 2 else "<u4"
    tree = copy.deepcopy(mesh_tree)
    template = mesh_tree["m_SubMeshes"]
    buffer, submeshes, new_sources = bytearray(), [], []
    def append(faces, descriptor):
        entry = copy.deepcopy(descriptor)
        flat = np.asarray(faces, dtype=np.int64).reshape(-1)
        entry.update(firstByte=len(buffer), indexCount=int(flat.size), baseVertex=0)
        if flat.size:
            entry.update(firstVertex=int(flat.min()), vertexCount=int(flat.max() - flat.min() + 1))
        buffer.extend(flat.astype(dtype).tobytes())
        submeshes.append(entry)
    for index in range(original_group_count):
        append(groups[index], template[index])
        new_sources.append(sources[index])
    for offset, islands in enumerate(per_group):
        index = original_group_count + offset
        for island in islands:
            append(island, template[index])
            values = uv[np.unique(island), :2] if len(island) else None
            island_bounds = (tuple(float(value) for value in (*values.min(axis=0), *values.max(axis=0)))
                             if values is not None else sources[index].uv_bounds)
            new_sources.append(dataclasses.replace(sources[index], uv_bounds=island_bounds))
    tree["m_IndexBuffer"] = bytes(buffer)
    tree["m_SubMeshes"] = submeshes
    return new_sources, tree, [len(islands) for islands in per_group]
