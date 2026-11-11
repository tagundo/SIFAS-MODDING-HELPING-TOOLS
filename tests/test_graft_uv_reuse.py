"""Native-resolution empty-UV graft behavior, using independent pixel probes."""
import copy
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import costume_part_transplant as part
from graft_uv_reuse import prepare_uv_reuse
from test_graft_texture_atlas import source, image, levels


def mesh(groups):
    coordinates = np.asarray([uv for triangle in groups for uv in triangle], dtype="<f4")
    count = len(coordinates)
    channels = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(5)]
    channels[0] = dict(stream=0, offset=0, format=0, dimension=3)
    channels[4] = dict(stream=1, offset=0, format=0, dimension=2)
    positions = np.zeros((count, 3), dtype="<f4").tobytes()
    data = positions + bytes(-len(positions) % 16) + coordinates.tobytes()
    data += bytes(-len(data) % 16)
    indices = np.arange(count, dtype="<u2").tobytes()
    return dict(m_VertexData=dict(m_VertexCount=count, m_Channels=channels, m_DataSize=data),
                m_IndexFormat=0, m_IndexBuffer=indices,
                m_SubMeshes=[dict(firstByte=index * 6, indexCount=3, baseVertex=0, topology=0) for index in range(len(groups))])


RECEIVER = ((.05, .05), (.25, .05), (.05, .25))
DONOR = ((.55, .55), (.85, .55), (.55, .85))


class EmptyUVReuseTests(unittest.TestCase):
    def test_identical_texture_sets_skip_coverage_and_decoding_even_with_shared_uvs(self):
        target = source("receiver", [image((32, 32), "red")])
        donor = source("same outfit", [image((32, 32), "red")])
        with patch("graft_uv_reuse._triangle_texels", side_effect=AssertionError("identical textures need no coverage")), patch("graft_uv_reuse._mip_images", side_effect=AssertionError("identical textures need no decode")):
            result = prepare_uv_reuse([target, donor], mesh([DONOR, DONOR]), 1)
        self.assertTrue(result.identity)
        self.assertFalse(result.textures)

    def test_disjoint_island_keeps_uvs_dimensions_and_every_unselected_pixel(self):
        raw = np.arange(32 * 32 * 4, dtype="uint8").reshape(32, 32, 4)
        target = source("receiver", [Image.fromarray(raw)])
        donor = source("donor", [image((32, 32), (190, 23, 71, 255))])
        geometry = mesh([RECEIVER, DONOR])
        before = copy.deepcopy(geometry), copy.deepcopy(target.objects[2].tree), copy.deepcopy(donor.objects[2].tree)
        result = prepare_uv_reuse([target, donor], geometry, 1)
        self.assertIsNotNone(result)
        self.assertFalse(result.identity)
        self.assertEqual(result.textures["_MainTex"].width, 32)
        self.assertEqual(result.textures["_MainTex"].height, 32)
        saved = levels(result.textures["_MainTex"])[0]
        np.testing.assert_array_equal(saved[11, 20], [190, 23, 71, 255])
        np.testing.assert_array_equal(saved[28, 3], raw[28, 3])  # retained receiver island
        np.testing.assert_array_equal(saved[5, 26], raw[5, 26])  # inside donor bbox, outside triangle
        np.testing.assert_array_equal(saved[:2], raw[:2])
        for transform in result.transforms:
            np.testing.assert_array_equal(transform.remap_uv([[.6, .7]]), [[.6, .7]])
        self.assertEqual((geometry, target.objects[2].tree, donor.objects[2].tree), before)

    def test_used_receiver_uvs_decline_even_when_receiver_pixels_are_transparent(self):
        target = source("receiver", [image((32, 32), (0, 0, 0, 0))])
        donor = source("donor", [image((32, 32), "blue")])
        reasons = []
        with patch("graft_uv_reuse._mip_images", side_effect=AssertionError("occupied UVs must fail before decode")):
            result = prepare_uv_reuse([target, donor], mesh([DONOR, DONOR]), 1, diagnostics=reasons)
        self.assertIsNone(result)
        self.assertIn("already used", reasons[0])

    def test_unused_opaque_black_pixels_are_vacant_by_geometry(self):
        target = source("receiver", [image((32, 32), (0, 0, 0, 255))])
        donor = source("donor", [image((32, 32), "white")])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        np.testing.assert_array_equal(levels(result.textures["_MainTex"])[0][11, 20], [255, 255, 255, 255])

    def test_overlapping_bounding_boxes_with_disjoint_triangles_are_allowed(self):
        lower_left = ((0., 0.), (.7, 0.), (0., .7))
        upper_right = ((.4, 1.), (1., .4), (1., 1.))
        target = source("receiver", [image((64, 64), "red")], wrap=1)
        donor = source("donor", [image((64, 64), "blue")], wrap=1)
        result = prepare_uv_reuse([target, donor], mesh([lower_left, upper_right]), 1)
        self.assertIsNotNone(result)
        pixels = levels(result.textures["_MainTex"])[0]
        np.testing.assert_array_equal(pixels[52, 10], [255, 0, 0, 255])
        np.testing.assert_array_equal(pixels[10, 52], [0, 0, 255, 255])
        np.testing.assert_array_equal(pixels[31, 31], [255, 0, 0, 255])

    def test_conflicting_selected_donor_pixels_decline_but_equal_pixels_can_share(self):
        target = source("receiver", [image((32, 32), "red")])
        first = source("first donor", [image((32, 32), "blue")])
        second = source("second donor", [image((32, 32), "green")])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, first, second], mesh([RECEIVER, DONOR, DONOR]), 1, diagnostics=reasons))
        self.assertIn("different source pixels", reasons[0])
        self.assertIsNotNone(prepare_uv_reuse([target, first, first], mesh([RECEIVER, DONOR, DONOR]), 1))

    def test_every_authored_mip_is_patched_directly_and_other_texels_are_original(self):
        receiver_images = [image((32 >> level, 32 >> level), (20 + level, 30, 40, 255)) for level in range(6)]
        donor_images = [image((32 >> level, 32 >> level), (120 + level, 130, 140, 255)) for level in range(6)]
        target, donor = source("receiver", receiver_images), source("donor", donor_images)
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        output = levels(result.textures["_MainTex"])
        self.assertEqual(len(output), 6)
        for level, pixels in enumerate(output):
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            self.assertTrue(colors <= {(20 + level, 30, 40, 255), (120 + level, 130, 140, 255)})
            self.assertIn((120 + level, 130, 140, 255), colors)
        np.testing.assert_array_equal(output[0][28, 3], [20, 30, 40, 255])
        np.testing.assert_array_equal(output[1][14, 1], [21, 30, 40, 255])
        np.testing.assert_array_equal(output[-1][0, 0], [125, 130, 140, 255])
        self.assertTrue(any("Authored coarse mip footprints" in value for value in result.diagnostics))
        self.assertEqual(result.textures["_MainTex"].tree["m_StreamData"], dict(offset=0, size=0, path=""))

    def test_native_resolution_mismatch_and_outside_uvs_fall_back_without_resizing(self):
        target = source("receiver", [image((32, 32), "red")], rim=[image((8, 8), "white")])
        donor = source("donor", [image((32, 32), "blue")], rim=[image((4, 4), "white")])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, diagnostics=reasons,
                                          upscale_textures_for_uv_reuse=False))
        self.assertIn("native texture dimensions", reasons[0])
        target, donor = source("receiver", [image((32, 32), "red")]), source("donor", [image((32, 32), "blue")])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, ((1.1, .5), (.9, .7), (.8, .6))]), 1, diagnostics=reasons))
        self.assertIn("0–1 range", reasons[0])

    def test_sampler_footprint_rejects_nearby_pixels_and_coverage_budget_is_bounded(self):
        target = source("receiver", [image((32, 32), "red")])
        donor = source("donor", [image((32, 32), "blue")])
        # These UV islands have a sub-texel gap, so native linear filtering can
        # still sample common texels even though their triangles do not touch.
        left = ((.1, .1), (.4, .1), (.4, .4))
        right = ((.41, .1), (.7, .1), (.41, .4))
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([left, right]), 1))
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, diagnostics=reasons, max_raster_tests=1))
        self.assertIn("raster budget", reasons[0])

    def test_repeat_boundary_contributors_are_checked_and_copied_at_opposite_edge(self):
        near_zero = ((0., .55), (.015, .55), (0., .8))
        near_one = ((.985, .55), (1., .55), (1., .8))
        target = source("receiver", [image((32, 32), "red")])
        donor_pixels = np.full((32, 32, 4), [0, 0, 255, 255], dtype="uint8")
        donor_pixels[:, -1] = [100, 30, 210, 255]
        donor = source("donor", [Image.fromarray(donor_pixels)])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([near_one, near_zero]), 1, diagnostics=reasons))
        self.assertIn("already used", reasons[0])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, near_zero]), 1)
        self.assertIsNotNone(result)
        pixels = levels(result.textures["_MainTex"])[0]
        np.testing.assert_array_equal(pixels[11, -1], donor_pixels[11, -1])
        np.testing.assert_array_equal(pixels[11, 0], donor_pixels[11, 0])
        np.testing.assert_array_equal(pixels[28, 3], [255, 0, 0, 255])
        # Independent native linear sample straddles the repeat boundary.
        fraction = .002 * 32 + .5
        expected = donor_pixels[11, -1] * (1 - fraction) + donor_pixels[11, 0] * fraction
        actual = pixels[11, -1] * (1 - fraction) + pixels[11, 0] * fraction
        np.testing.assert_array_equal(actual, expected)

    def test_decode_and_mask_memory_budgets_are_checked_before_decode(self):
        target = source("receiver", [image((32, 32), "red")])
        donor = source("donor", [image((32, 32), "blue")])
        for limit, text in ((10000, "decoded source images"), (14000, "occupancy masks")):
            reasons = []
            with self.subTest(limit=limit), patch("graft_uv_reuse._mip_images", side_effect=AssertionError("budget must fail before decode")):
                self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, diagnostics=reasons, max_total_bytes=limit))
            self.assertIn(text, reasons[0])


def linear_sample(pixels, uv):
    """Independent original Repeat bilinear sampler, in Unity UV coordinates."""
    height, width = pixels.shape[:2]
    x, y = uv[0] * width - .5, uv[1] * height - .5
    left, bottom = int(np.floor(x)), int(np.floor(y))
    fx, fy = x - left, y - bottom
    result = np.zeros(4)
    for dx, wx in ((0, 1 - fx), (1, fx)):
        for dy, wy in ((0, 1 - fy), (1, fy)):
            result += pixels[height - 1 - ((bottom + dy) % height), (left + dx) % width] * (wx * wy)
    return result


class RelocatedUVReuseTests(unittest.TestCase):
    def test_different_aspect_native_pixels_and_uv_scale_preserve_linear_samples(self):
        receiver = source("receiver", [image((32, 16), "blue")], rim=[image((16, 8), "white")])
        raw = np.arange(16 * 16 * 4, dtype="uint8").reshape(16, 16, 4)
        rim = np.arange(8 * 8 * 4, dtype="uint8").reshape(8, 8, 4)
        donor = source("donor", [Image.fromarray(raw)], rim=[Image.fromarray(rim)])
        triangle = ((.1, .1), (.5, .1), (.1, .5))
        geometry = mesh([triangle, triangle])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([receiver, donor], geometry, 1, diagnostics=reasons, upscale_textures_for_uv_reuse=False))
        result = prepare_uv_reuse([receiver, donor], geometry, 1, relocate_empty_uv=True, upscale_textures_for_uv_reuse=False)
        self.assertIsNotNone(result)
        self.assertEqual(result.transforms[0].scale, (1., 1.))
        self.assertEqual(result.transforms[1].scale, (.5, 1.))
        self.assertEqual((result.textures["_MainTex"].width, result.textures["_MainTex"].height), (32, 16))
        self.assertEqual((result.textures["_RimlightTex"].width, result.textures["_RimlightTex"].height), (16, 8))
        for slot, pixels in (("_MainTex", raw), ("_RimlightTex", rim)):
            output = levels(result.textures[slot])[0]
            for uv in ((.2, .2), (.15, .25), (.3, .15)):
                moved = result.transforms[1].remap_uv([uv])[0]
                np.testing.assert_allclose(linear_sample(output, moved), linear_sample(pixels, uv), atol=1e-10)
        self.assertFalse(any("using the texture atlas" in message for message in result.diagnostics))

    def test_occupied_same_coordinates_move_only_when_secondary_option_is_enabled(self):
        target = source("receiver", [image((32, 32), "red")])
        donor = source("donor", [image((32, 32), "blue")])
        geometry = mesh([RECEIVER, RECEIVER])
        self.assertIsNone(prepare_uv_reuse([target, donor], geometry, 1, upscale_textures_for_uv_reuse=False))
        result = prepare_uv_reuse([target, donor], geometry, 1, relocate_empty_uv=True, upscale_textures_for_uv_reuse=False)
        self.assertIsNotNone(result)
        self.assertEqual(result.transforms[1].scale, (1., 1.))
        self.assertNotEqual(result.transforms[1].offset, (0., 0.))
        np.testing.assert_array_equal(levels(result.textures["_MainTex"])[0][28, 3], [255, 0, 0, 255])

    def test_free_same_coordinates_remain_identity_with_relocation_enabled(self):
        target = source("receiver", [image((32, 32), "red")])
        donor = source("donor", [image((32, 32), "blue")])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, relocate_empty_uv=True, upscale_textures_for_uv_reuse=False)
        self.assertEqual(result.transforms[1].scale, (1., 1.))
        self.assertEqual(result.transforms[1].offset, (0., 0.))

    def test_slot_ratio_mismatch_and_full_receiver_fall_back(self):
        target = source("receiver", [image((32, 16), "red")], rim=[image((16, 8), "white")])
        donor = source("donor", [image((16, 16), "blue")], rim=[image((8, 4), "white")])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, RECEIVER]), 1, diagnostics=reasons,
                                          relocate_empty_uv=True, upscale_textures_for_uv_reuse=False))
        self.assertTrue(any("ratios" in reason for reason in reasons))
        target = source("receiver", [image((32, 32), "red")])
        donor = source("donor", [image((16, 16), "blue")])
        full = mesh([((0, 0), (1, 0), (0, 1)), ((1, 0), (1, 1), (0, 1)), DONOR])
        full["m_SubMeshes"] = [dict(firstByte=0, indexCount=6, baseVertex=0, topology=0),
                               dict(firstByte=12, indexCount=3, baseVertex=0, topology=0)]
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], full, 1, diagnostics=reasons, relocate_empty_uv=True, upscale_textures_for_uv_reuse=False))
        self.assertTrue(any("no common free" in reason for reason in reasons))

    def test_multiple_donors_claim_different_free_areas_and_leave_receiver_untouched(self):
        target = source("receiver", [image((32, 32), "red")])
        first = source("first", [image((16, 16), "blue")])
        second = source("second", [image((16, 16), "green")])
        result = prepare_uv_reuse([target, first, second], mesh([RECEIVER, RECEIVER, RECEIVER]), 1, relocate_empty_uv=True, upscale_textures_for_uv_reuse=False)
        self.assertIsNotNone(result)
        self.assertNotEqual(result.transforms[1].offset, result.transforms[2].offset)
        output = levels(result.textures["_MainTex"])[0]
        for index, color in ((1, (0, 0, 255, 255)), (2, (0, 128, 0, 255))):
            moved = result.transforms[index].remap_uv([[.1, .1]])[0]
            np.testing.assert_allclose(linear_sample(output, moved), color)
        np.testing.assert_array_equal(output[28, 3], [255, 0, 0, 255])


if __name__ == "__main__":
    unittest.main()
