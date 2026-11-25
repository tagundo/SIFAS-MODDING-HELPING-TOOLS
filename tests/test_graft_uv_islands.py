"""move_to_empty places every UV island on its own and never over reserved texels.

Pixel oracles read the payload independently (``levels``) and compare exact
native texels; nothing here resamples or pads. The receiver occupancy and the
reserved areas only decide placement.
"""
import copy
import unittest
import unittest.mock

import numpy as np
from PIL import Image

import costume_part_transplant as part
import graft_uv_reuse
from graft_uv_reuse import (_CoarseScorer, _reserved_texels, _triangle_texels, prepare_uv_reuse,
                           split_uv_islands)
from test_graft_texture_atlas import image, levels, source


def grouped_mesh(groups):
    """One submesh per entry; each entry is a list of UV triangles."""
    triangles = [triangle for group in groups for triangle in group]
    coordinates = np.asarray([uv for triangle in triangles for uv in triangle], dtype="<f4")
    count = len(coordinates)
    channels = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(5)]
    channels[0] = dict(stream=0, offset=0, format=0, dimension=3)
    channels[4] = dict(stream=1, offset=0, format=0, dimension=2)
    positions = np.zeros((count, 3), dtype="<f4").tobytes()
    data = positions + bytes(-len(positions) % 16) + coordinates.tobytes()
    data += bytes(-len(data) % 16)
    submeshes, first = [], 0
    for group in groups:
        submeshes.append(dict(firstByte=first * 2, indexCount=3 * len(group), baseVertex=0, topology=0))
        first += 3 * len(group)
    return dict(m_VertexData=dict(m_VertexCount=count, m_Channels=channels, m_DataSize=data),
                m_IndexFormat=0, m_IndexBuffer=np.arange(count, dtype="<u2").tobytes(), m_SubMeshes=submeshes)


def square(x, y, size, texture=32):
    """Two triangles covering texel rectangle [x, x+size) x [y, y+size) (bottom-left)."""
    u0, v0, u1, v1 = x / texture, y / texture, (x + size) / texture, (y + size) / texture
    return [((u0, v0), (u1, v0), (u0, v1)), ((u1, v0), (u1, v1), (u0, v1))]


def uv_of(geometry):
    count, channels, strides, starts, _ = part.stream_layout(geometry)
    data = np.frombuffer(bytes(geometry["m_VertexData"]["m_DataSize"]), np.uint8)
    return part.read_attr(data, part.ATTR_UV0, channels, strides, starts, count)


def nearest(image_rows, u, v):
    height, width = image_rows.shape[:2]
    return image_rows[height - 1 - int(np.floor(v * height)), int(np.floor(u * width))]


class IslandPlacementTests(unittest.TestCase):
    def setUp(self):
        self.donor_pixels = np.arange(32 * 32 * 4, dtype=np.uint8).reshape(32, 32, 4)
        self.donor_pixels[..., 3] = 255

    def sources(self):
        target = source("receiver", [image((32, 32), (9, 9, 9, 255))])
        donor = source("donor", [Image.fromarray(self.donor_pixels)])
        for value in (target, donor):  # nearest sampling: footprints equal the drawn texels
            value.objects[2].texture.m_TextureSettings.m_FilterMode = 0
            value.objects[2].tree["m_TextureSettings"]["m_FilterMode"] = 0
        return target, donor

    def test_islands_whose_union_box_cannot_fit_are_placed_separately_with_exact_texels(self):
        # Free pockets at bottom-left and top-right; every other texel is reserved.
        occupied = np.ones((32, 32), bool)
        for x, y, size in ((1, 1, 7), (24, 24, 7)):
            occupied[32 - y - size:32 - y, x:x + size] = False
        target, donor = self.sources()
        # The donor islands sit at a relative offset no rigid move can match.
        islands = [square(2, 20, 5), square(20, 2, 5)]
        geometry = grouped_mesh([[((.0, .0), (.001, .0), (.0, .001))], islands[0] + islands[1]])
        mask = _reserved_from(occupied)
        whole = prepare_uv_reuse([target, donor], copy.deepcopy(geometry), 1, uv_placement="move_to_empty",
                                 reserved={"surfaces": [mask], "rects": []}, diagnostics=(reasons := []))
        self.assertIsNone(whole, "one rigid move of both islands cannot fit the two pockets")
        self.assertTrue(any("no common free" in reason for reason in reasons))
        sources, split, counts = split_uv_islands([target, donor], geometry, 1)
        self.assertEqual(counts, [2])
        self.assertEqual(len(split["m_SubMeshes"]), 3)
        result = prepare_uv_reuse(sources, split, 1, uv_placement="move_to_empty",
                                  reserved={"surfaces": [mask], "rects": []})
        self.assertIsNotNone(result)
        output = levels(result.textures["_MainTex"])[0]
        coordinates = uv_of(split)
        groups = part.submesh_triangles(split)
        for index in (1, 2):
            transform = result.transforms[index]
            self.assertEqual(transform.scale, (1., 1.))
            for vertex in np.unique(groups[index]):
                original = coordinates[vertex, :2]
                moved = transform.remap_uv(original[None])[0]
                inside = np.clip(original * 32, .5, 31.5) / 32  # sample at texel centers
                inside_moved = transform.remap_uv(inside[None])[0]
                np.testing.assert_array_equal(nearest(output, *inside_moved), nearest(self.donor_pixels, *inside))
                self.assertFalse(occupied[31 - int(np.floor(inside_moved[1] * 32)), int(np.floor(inside_moved[0] * 32))],
                                 "every island lands in a free pocket")
        changed = np.any(output != np.array([9, 9, 9, 255], np.uint8), axis=2)
        self.assertTrue(np.any(changed))
        self.assertFalse(np.any(changed & occupied), "reserved texels keep their receiver pixels")

    def test_reserved_triangles_block_same_position_and_are_avoided_when_moving(self):
        target, donor = self.sources()
        donor_island = square(4, 4, 6)
        geometry = grouped_mesh([[((.9, .9), (.95, .9), (.9, .95))], donor_island])
        reserved_uv = np.asarray([uv for triangle in donor_island for uv in triangle], dtype=float)
        reserved = {"surfaces": [(reserved_uv, np.arange(6).reshape(2, 3))], "rects": []}
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], copy.deepcopy(geometry), 1, uv_placement="same_position",
                                           reserved=reserved, diagnostics=reasons, atlas_fallback=False))
        self.assertIn("other surfaces of this texture", reasons[0])
        self.assertNotIn("atlas", reasons[0], "a caller without an atlas is not promised one")
        result = prepare_uv_reuse([target, donor], copy.deepcopy(geometry), 1, uv_placement="move_to_empty",
                                  reserved=reserved)
        self.assertIsNotNone(result)
        output = levels(result.textures["_MainTex"])[0]
        blocked = _triangle_texels(reserved_uv, np.arange(6).reshape(2, 3), 32, 32, False, (0, 0), [10 ** 9])
        np.testing.assert_array_equal(output[blocked], np.full((int(blocked.sum()), 4), (9, 9, 9, 255), np.uint8))
        self.assertNotEqual(result.transforms[1].offset, (0., 0.))

    def test_reserved_rectangles_cover_their_closed_uv_area(self):
        from graft_uv_reuse import _reserved_texels
        mask = _reserved_texels({"rects": [(0., .5, .25, 1.)]}, 16, 16, False, (0, 0), [10 ** 6])
        expected = np.zeros((16, 16), bool)
        expected[:9, :5] = True  # closed edges touch row v=.5 and column u=.25
        np.testing.assert_array_equal(mask, expected)

    def test_overlapping_vertex_islands_stay_together_and_receiver_is_untouched(self):
        target, donor = self.sources()
        left, right = square(2, 2, 6), square(20, 2, 6)
        mirror = [tuple((u, v) for u, v in triangle) for triangle in left]  # same texels, own vertices
        geometry = grouped_mesh([[((.5, .9), (.55, .9), (.5, .95))], left + mirror + right])
        before = copy.deepcopy(geometry)
        sources, split, counts = split_uv_islands([target, donor], geometry, 1)
        self.assertEqual(geometry, before, "the input mesh is never mutated")
        self.assertEqual(counts, [2], "texel-sharing copies move as one island")
        groups = part.submesh_triangles(split)
        np.testing.assert_array_equal(groups[0], part.submesh_triangles(before)[0])
        self.assertEqual(sorted(len(group) for group in groups[1:]), [2, 4])
        self.assertIs(sources[0], target)
        self.assertEqual(split["m_VertexData"], before["m_VertexData"])
        self.assertTrue(all(value.tree is donor.tree for value in sources[1:]))

    def test_offsets_prefer_power_of_two_grids_so_coarse_mips_stay_exact(self):
        import re
        target = source("receiver", [image((256, 256), (9, 9, 9, 255))])
        donor = source("donor", [image((256, 256), (200, 10, 10, 255))])
        geometry = grouped_mesh([[((.95, .95), (.96, .95), (.95, .96))], square(3, 5, 10, 256)])
        # The left half is reserved, so the island must move; the first free
        # texel column (129) would give an odd offset on the minimal grid.
        result = prepare_uv_reuse([target, donor], geometry, 1, uv_placement="move_to_empty",
                                  reserved={"rects": [(0., 0., .5, 1.)]})
        self.assertIsNotNone(result)
        dx, dy = (round(value * 256) for value in result.transforms[1].offset)
        self.assertGreater(dx, 0)
        self.assertEqual((dx % 16, dy % 16), (0, 0))
        exact = [int(match) for message in result.diagnostics
                 for match in re.findall(r"authored mip levels 0–(\d+) are exact", message)]
        self.assertTrue(exact and exact[0] >= 4, result.diagnostics)

    def test_failure_names_the_island_that_did_not_fit(self):
        target, donor = self.sources()
        geometry = grouped_mesh([[((.5, .5), (.51, .5), (.5, .51))], square(2, 2, 6)])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], geometry, 1, uv_placement="move_to_empty",
                                           reserved={"rects": [(0., 0., 1., 1.)]}, diagnostics=reasons))
        self.assertTrue(any("island 1 of 1" in reason and "texels" in reason for reason in reasons), reasons)


def _reserved_from(occupied):
    """A reserved surface whose footprint is exactly the given texel mask (nearest sampling)."""
    height, width = occupied.shape
    triangles = []
    for row, column in zip(*np.nonzero(occupied)):
        y = height - 1 - row
        triangles.extend(square(column, y, 1, width))
    uv = np.asarray([uv for triangle in triangles for uv in triangle], dtype=float)
    # Shrink each texel square slightly so a nearest footprint cannot spill.
    centers = np.repeat(uv.reshape(-1, 3, 2).mean(axis=1), 3, axis=0)
    uv = centers + (uv - centers) * .98
    return uv, np.arange(len(uv)).reshape(-1, 3)


class LimitingMapTests(unittest.TestCase):
    def test_failure_names_the_map_that_had_no_room(self):
        """Main texels are free in every 8x8 block, but each rim texel is already used."""
        target = source("receiver", [image((32, 32), "red")], rim=[image((4, 4), "red")])
        donor = source("donor", [image((32, 32), "blue")], rim=[image((4, 4), "blue")])
        # Off the donor's 8-pixel placement grid, so free Main candidates exist.
        dots = [((8 * x + 6.2) / 32, (8 * y + 6.2) / 32, (8 * x + 6.8) / 32, (8 * y + 6.8) / 32)
                for x in range(4) for y in range(4)]
        geometry = grouped_mesh([[((.1, .1), (.11, .1), (.1, .11))], [((.55, .55), (.6, .55), (.55, .6))]])
        reasons = []
        result = prepare_uv_reuse([target, donor], geometry, 1, uv_placement="move_to_empty",
                                  reserved={"surfaces": [], "rects": dots}, diagnostics=reasons, atlas_fallback=False)
        self.assertIsNone(result)
        failure = next(reason for reason in reasons if getattr(reason, "kind", None) == "no_space")
        self.assertEqual(failure.details["slot"], "_RimlightTex")
        self.assertEqual((failure.details["island"], failure.details["islands"]), (1, 1))
        self.assertIn("every position free in _MainTex was used in _RimlightTex", failure)

def inset(x, y, size, texture=32):
    """Two triangles strictly inside texels x..x+size-1, y..y+size-1 (nearest footprint is exact)."""
    u0, v0, u1, v1 = (x + .25) / texture, (y + .25) / texture, (x + size - .25) / texture, (y + size - .25) / texture
    return [((u0, v0), (u1, v0), (u0, v1)), ((u1, v0), (u1, v1), (u0, v1))]


class CoarseMipPlacementTests(unittest.TestCase):
    """Free level-0 positions are preferred where the coarse mips also stay clear.

    Receiver and donor have full 32-pixel mip chains with nearest sampling. The
    island (4x4 texels, original columns 21-24) must move into the free columns
    5-12. First fit on the 2-pixel grid is column 5, whose level-1 footprint
    shares level-1 column 2 with the reserved left block; column 7 is clean.
    """

    def sources(self):
        receiver = [image((32 >> level, 32 >> level), (9, 9, 9, 255)) for level in range(6)]
        donor = [image((32 >> level, 32 >> level), (200, 10 + level, 10, 255)) for level in range(6)]
        target, part_source = source("receiver", receiver), source("donor", donor)
        for value in (target, part_source):
            value.objects[2].texture.m_TextureSettings.m_FilterMode = 0
            value.objects[2].tree["m_TextureSettings"]["m_FilterMode"] = 0
        return target, part_source

    def place(self, free_columns):
        target, donor = self.sources()
        first, last = free_columns
        reserved = {"rects": [(0., 0., (first - .5) / 32, 1.), ((last + 1.5) / 32, 0., 1., 1.)]}
        geometry = grouped_mesh([[((.01, .01), (.02, .01), (.01, .02))], inset(21, 10, 4)])
        return prepare_uv_reuse([target, donor], geometry, 1, uv_placement="move_to_empty", reserved=reserved)

    def test_a_position_whose_coarse_mips_miss_used_texels_is_preferred(self):
        result = self.place((5, 12))
        self.assertIsNotNone(result)
        dx = round(result.transforms[1].offset[0] * 32)
        self.assertEqual(21 + dx, 7, "column 5 is free at level 0 but not at level 1")
        level1 = levels(result.textures["_MainTex"])[1]
        np.testing.assert_array_equal(level1[:, 0:3], np.full((16, 3, 4), (9, 9, 9, 255), np.uint8),
                                      "the reserved block keeps its level-1 texels")
        self.assertTrue(any("keeps off other surfaces' texels at mip levels 0–1" in message
                            for message in result.diagnostics), result.diagnostics)
        changes = result.reserved_changes["_MainTex"]
        self.assertEqual(changes[:2], (0, 0))
        self.assertTrue(any(f"keep their texels at _MainTex mip levels 0–1; coarser mips change {sum(changes)} of "
                            "their texels (measured)." in message for message in result.diagnostics), result.diagnostics)

    def test_without_a_clean_position_the_first_free_one_is_still_used(self):
        result = self.place((5, 8))
        self.assertIsNotNone(result, "coarse texels only steer placement; they never refuse it")
        self.assertEqual(21 + round(result.transforms[1].offset[0] * 32), 5)
        self.assertTrue(any("share" in message and "other surfaces" in message for message in result.diagnostics))


class ReservedCoarsePlacementTests(unittest.TestCase):
    """Coarse footprints are scored against reserved texels first, folded through the wrap mode.

    A 64-pixel bilinear texture with a full mip chain. The top band (v >= 60/64)
    is reserved, like the face block of a head texture. Receiver cells cover
    most of the rest, leaving two free slots for the 10x10-texel island
    footprint: B in the bottom-left corner and A at (24, 24). B keeps off the
    receiver's coarse texels for more levels than A. At B, the island's level-2
    footprint reaches one texel below row 0, which Repeat folds onto the top
    row: the reserved band. Clamp folds it onto row 0 instead.
    """
    SIZE = 64

    def receiver_cells(self):
        cells = []
        for x0 in range(0, 52, 4):
            for y0 in range(0, 56, 4):
                if (x0 < 16 and y0 < 16) or (20 <= x0 <= 32 and 20 <= y0 <= 32):
                    continue
                cells += inset(x0, y0, 4, self.SIZE)
        return cells

    def place(self, wrap):
        size = self.SIZE
        receiver = [image((size >> level, size >> level), (9, 9, 9, 255)) for level in range(7)]
        donor = [image((size >> level, size >> level), (200, 10 + level, 10, 255)) for level in range(7)]
        target, part_source = source("receiver", receiver, wrap=wrap), source("donor", donor, wrap=wrap)
        geometry = grouped_mesh([self.receiver_cells(), inset(33, 33, 8, size)])
        result = prepare_uv_reuse([target, part_source], geometry, 1, uv_placement="move_to_empty",
                                  reserved={"rects": [(0., 60 / size, 1., 1.)]})
        self.assertIsNotNone(result)
        position = tuple(33 + round(offset * size) for offset in result.transforms[1].offset)
        return result, position

    def test_repeat_wrap_onto_reserved_texels_moves_the_island_off_the_edge(self):
        result, position = self.place(wrap=0)
        self.assertEqual(position, (25, 25), "slot B's wrapped level-2 footprint reaches the reserved band")
        payload = levels(result.textures["_MainTex"])
        for level in range(5):
            np.testing.assert_array_equal(payload[level][0], np.full((self.SIZE >> level, 4), (9, 9, 9, 255), np.uint8),
                                          f"level {level}: the reserved top row keeps its texels")
        self.assertEqual(result.reserved_changes["_MainTex"][:5], (0, 0, 0, 0, 0))
        self.assertTrue(any("keeps off other surfaces' texels at mip levels 0–4 and off the receiver's at mip "
                            "levels 0–1" in message for message in result.diagnostics), result.diagnostics)

    def test_clamp_keeps_the_first_free_corner(self):
        result, position = self.place(wrap=1)
        self.assertEqual(position, (1, 1), "nothing folds onto the reserved band, so bottom-left order decides")
        self.assertEqual(result.reserved_changes["_MainTex"][:6], (0,) * 6)

    def test_reserved_changes_are_measured_from_the_written_texels(self):
        result, _ = self.place(wrap=0)
        payload = levels(result.textures["_MainTex"])
        self.assertEqual(len(result.reserved_changes["_MainTex"]), 7)
        for level, count in enumerate(result.reserved_changes["_MainTex"]):
            size = self.SIZE >> level
            # Bilinear support widens the closed band v >= 60/64 by 1.5 texels downwards.
            rows = size - max(0, int(np.ceil(60 / 64 * size - 1.5)))
            changed = np.any(payload[level][:rows] != (9, 9, 9, 255), axis=2)
            self.assertEqual(count, int(changed.sum()), f"level {level}")
        self.assertGreater(sum(result.reserved_changes["_MainTex"]), 0, "the 2x2 and 1x1 levels cannot avoid the band")



class CoarseScorerTests(unittest.TestCase):
    """The coarse scores equal what the moved footprints really touch, wrap included.

    Brute force: move the island's UVs by every level-0 offset, rasterize them
    at each coarse level with the sampler's wrap, and count consecutive levels
    that keep off each mask. The scorer must give the same numbers (and, with
    its whole-texel bound, never more).
    """
    SIZE = 32
    LEVELS = (1, 2, 3, 4)
    ISLAND = np.array([[.4113, .4227], [.5521, .4519], [.4702, .5788], [.5317, .5602]])
    FACES = np.array([[0, 1, 2], [1, 3, 2]])

    def masks(self, wraps):
        reserved, receiver = {}, {}
        for level in self.LEVELS:
            size = self.SIZE >> level
            reserved[level] = _reserved_texels({"rects": [(0., .875, .5, 1.)],
                                                "surfaces": [(np.array([[.8, .05], [.97, .05], [.9, .3]]), [[0, 1, 2]])]},
                                               size, size, True, wraps, [10 ** 9])
            receiver[level] = _triangle_texels(np.array([[.05, .1], [.3, .12], [.1, .35]]), [[0, 1, 2]],
                                               size, size, True, wraps, [10 ** 9])
        return reserved, receiver

    def brute(self, masks, wraps, dx, dy):
        scores = []
        for mask in masks:
            score = 0
            for level in self.LEVELS:
                size = self.SIZE >> level
                moved = self.ISLAND + (dx / self.SIZE, dy / self.SIZE)
                if np.any(_triangle_texels(moved, self.FACES, size, size, True, wraps, [10 ** 9]) & mask[level]):
                    break
                score += 1
            scores.append(score)
        return tuple(scores)

    def shifts(self):
        low, high = self.ISLAND.min(axis=0) * self.SIZE, self.ISLAND.max(axis=0) * self.SIZE
        return [(dx, dy) for dx in range(int(np.ceil(-low[0])), int(np.floor(self.SIZE - high[0])) + 1)
                for dy in range(int(np.ceil(-low[1])), int(np.floor(self.SIZE - high[1])) + 1)]

    def scorer(self, masks, wraps):
        return _CoarseScorer(self.ISLAND, self.FACES, (self.SIZE, self.SIZE), self.LEVELS, True, wraps,
                             masks[0], masks[1], [10 ** 9])

    def test_scores_equal_the_moved_footprints_at_every_offset_and_wrap(self):
        for wraps in ((0, 0), (1, 1), (2, 2)):
            with self.subTest(wraps=wraps):
                masks = self.masks(wraps)
                shifts = self.shifts()
                # Every offset here is its own level-4 phase: score them all exactly.
                with unittest.mock.patch.object(graft_uv_reuse, "_MAX_COARSE_PHASES", 256):
                    reserved, receiver = self.scorer(masks, wraps).scores([dx for dx, _ in shifts],
                                                                          [dy for _, dy in shifts])
                expected = [self.brute(masks, wraps, dx, dy) for dx, dy in shifts]
                self.assertEqual(list(zip(reserved.tolist(), receiver.tolist())), expected)
                self.assertGreater(len({value for value, _ in expected}), 2, "the masks separate the offsets")

    def test_the_whole_texel_bound_never_overcounts(self):
        wraps = (0, 0)
        masks = self.masks(wraps)
        shifts = self.shifts()
        with unittest.mock.patch.object(graft_uv_reuse, "_MAX_COARSE_PHASES", 0):
            reserved, receiver = self.scorer(masks, wraps).scores([dx for dx, _ in shifts], [dy for _, dy in shifts])
        expected = [self.brute(masks, wraps, dx, dy) for dx, dy in shifts]
        for (dx, dy), bound, exact in zip(shifts, zip(reserved.tolist(), receiver.tolist()), expected):
            self.assertLessEqual(bound[0], exact[0], (dx, dy))
            self.assertLessEqual(bound[1], exact[1], (dx, dy))


if __name__ == "__main__":
    unittest.main()
