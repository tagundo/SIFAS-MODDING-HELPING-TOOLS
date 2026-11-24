"""Baked cheek blush: the AS/Member _CHEEK_ON rule applied to texture pixels.

The cheek arrays here are synthetic: no game texture data is stored in the
repository. Real-array checks run only when REAL_MV_SAMPLES points at bundles.
"""
import hashlib
import math
import os
from pathlib import Path
import random
import struct
import unittest
from unittest.mock import patch

from webtools.core import texture_blush as tb

SIZE = tb.CHEEK_SIZE


def white_layer():
    return bytearray(b"\xff" * tb.CHEEK_LAYER_BYTES)


def put(layer, x, y, rgb):
    """(x, y) in Unity rows: y = 0 is the bottom (v = 0)."""
    offset = (y * SIZE + x) * 4
    layer[offset:offset + 3] = bytes(rgb)


def blob_layer(seed=7, darkest=(255, 215, 206)):
    """A stock-like layer: white edges, two soft blobs whose centres reach `darkest`."""
    layer = white_layer()
    for cx, cy in ((110, 136), (185, 136)):
        for y in range(cy - 22, cy + 23):
            for x in range(cx - 36, cx + 37):
                d = math.hypot((x - cx) / 36, (y - cy) / 22)
                if d < 1:
                    put(layer, x, y, [255 - round((255 - c) * (1 - d)) for c in darkest])
    return bytes(layer)


def random_image(width, height, seed):
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(width * height * 4))


class FormulaTests(unittest.TestCase):
    def test_shader_constants_are_the_float32_literals(self):
        self.assertEqual(tb.UV_SCALE, struct.unpack("<f", struct.pack("<f", 2.22))[0])
        self.assertEqual(tb.UV_OFFSET_V, struct.unpack("<f", struct.pack("<f", -1.22100008))[0])
        self.assertAlmostEqual(tb.UV_SCALE, 2.22000003, places=8)
        self.assertAlmostEqual(tb.UV_OFFSET_V, -1.22100008, places=8)

    def test_factor_is_one_plus_intensity_times_cheek_minus_one(self):
        rng = random.Random(3)
        for _ in range(200):
            cheek = [rng.random() for _ in range(3)]
            k = rng.uniform(0.05, tb.MAX_K)
            self.assertEqual(tb.factor(cheek, k), [1 + k * (value - 1) for value in cheek])
        darkest = [value / 255 for value in tb.DARKEST_TEXEL[0]]
        self.assertEqual(tb.factor(darkest, 1.0), [1.0, 215 / 255, 206 / 255])
        # White never changes anything, at any strength.
        self.assertEqual(tb.factor([1.0, 1.0, 1.0], tb.MAX_K), [1.0, 1.0, 1.0])

    def test_rounding_is_half_up_and_clamped(self):
        self.assertEqual(tb.bake_value(100, 0.995), 100)   # 99.5 -> 100
        self.assertEqual(tb.bake_value(101, 0.995), 100)   # 100.495 -> 100
        self.assertEqual(tb.bake_value(255, 1.0), 255)
        self.assertEqual(tb.bake_value(10, -1.0), 0)

    def test_bilinear_sample_and_clamp_edges(self):
        layer = white_layer()
        put(layer, 10, 20, (255, 0, 0))
        layer = bytes(layer)
        centre = ((10 + 0.5) / SIZE, (20 + 0.5) / SIZE)
        self.assertEqual(tb.sample(layer, *centre), [1.0, 0.0, 0.0])
        halfway = tb.sample(layer, (11 + 0.0) / SIZE, (20 + 0.5) / SIZE)
        self.assertEqual(halfway, [1.0, 0.5, 0.5])
        # Far outside [0, 1] Clamp repeats the white edge texel exactly.
        for cu, cv in ((-3.0, 0.5), (0.5, -1.2), (2.2, 0.5), (0.5, 1.7)):
            self.assertEqual(tb.sample(layer, cu, cv), [1.0, 1.0, 1.0])
        edge = white_layer()
        put(edge, 255, 128, (255, 100, 50))
        self.assertEqual(tb.sample(bytes(edge), 1.9, (128 + 0.5) / SIZE), [1.0, 100 / 255, 50 / 255])


class MappingTests(unittest.TestCase):
    def test_v_up_mapping_puts_the_blob_on_the_texture_rows_the_shader_samples(self):
        layer = white_layer()
        for x in range(120, 140):
            for y in range(130, 140):   # Unity rows (v up)
                put(layer, x, y, (255, 120, 120))
        layer = bytes(layer)
        width = height = 256
        _, changed, box = tb.bake_rgba(bytes([200] * width * height * 4), width, height, layer, 1.0)
        self.assertGreater(changed, 0)
        x0, y0, x1, y1 = box
        # Texel centres whose cheek UV lands inside the coloured texels.
        def rows(j0, j1):
            v_low = ((j0 - 0.5) / SIZE - tb.UV_OFFSET_V) / tb.UV_SCALE
            v_high = ((j1 + 1.5) / SIZE - tb.UV_OFFSET_V) / tb.UV_SCALE
            return (1 - v_high) * height - 0.5, (1 - v_low) * height - 0.5
        low, high = rows(130, 139)
        self.assertTrue(low <= y0 and y1 <= high, (box, low, high))
        # The vertically flipped (v-down) interpretation would land elsewhere.
        flipped_low, flipped_high = height - 1 - high, height - 1 - low
        self.assertTrue(y1 < flipped_low or y0 > flipped_high)
        self.assertTrue(((120 - 0.5) / SIZE / tb.UV_SCALE) * width - 0.5 <= x0)
        self.assertTrue(x1 <= ((139 + 1.5) / SIZE / tb.UV_SCALE) * width - 0.5)

    def test_texture_outside_the_cheek_rectangle_never_changes(self):
        layer = blob_layer()
        width, height = 128, 64
        image = random_image(width, height, 11)
        out, _, _ = tb.bake_rgba(image, width, height, layer, tb.MAX_K)
        for y in range(height):
            for x in range(width):
                u, v = tb.texel_uv(x, y, width, height)
                cu, cv = tb.cheek_uv(u, v)
                if not (0 <= cu <= 1 and 0 <= cv <= 1):
                    offset = (y * width + x) * 4
                    self.assertEqual(out[offset:offset + 4], image[offset:offset + 4], (x, y))

    def test_non_white_clamped_edges_reach_the_texture_border(self):
        # Not the stock data (its edges are white, a fact the hash pins down),
        # but proves the optimised region follows Clamp exactly.
        layer = white_layer()
        for y in range(SIZE):
            put(layer, SIZE - 1, y, (255, 128, 128))
        layer = bytes(layer)
        width = height = 64
        image = bytes([200, 200, 200, 255] * width * height)
        out, changed, box = tb.bake_rgba(image, width, height, layer, 1.0)
        brute = bytearray(image)
        for y in range(height):
            for x in range(width):
                u, v = tb.texel_uv(x, y, width, height)
                f = tb.factor(tb.sample(layer, *tb.cheek_uv(u, v)), 1.0)
                for c in range(3):
                    brute[(y * width + x) * 4 + c] = tb.bake_value(image[(y * width + x) * 4 + c], f[c])
        self.assertEqual(out, bytes(brute))
        self.assertEqual(box[2], width - 1)


class PixelContractTests(unittest.TestCase):
    def test_region_optimisation_equals_brute_force_and_alpha_is_untouched(self):
        layer = blob_layer()
        for width, height, k in ((97, 61, 1.65), (64, 64, 0.5), (33, 17, 3.0), (5, 3, 2.3), (1, 1, 1.0)):
            image = random_image(width, height, width * height)
            out, changed, _ = tb.bake_rgba(image, width, height, layer, k)
            brute, count = bytearray(image), 0
            for y in range(height):
                for x in range(width):
                    offset = (y * width + x) * 4
                    f = tb.factor(tb.sample(layer, *tb.cheek_uv(*tb.texel_uv(x, y, width, height))), k)
                    touched = False
                    for c in range(3):
                        value = tb.bake_value(image[offset + c], f[c])
                        touched |= value != image[offset + c]
                        brute[offset + c] = value
                    count += touched
            self.assertEqual(out, bytes(brute))
            self.assertEqual(changed, count)
            self.assertEqual(out[3::4], image[3::4], "alpha never changes")
            for offset in range(0, len(image), 4):
                if out[offset:offset + 3] == image[offset:offset + 3]:
                    self.assertEqual(out[offset:offset + 4], image[offset:offset + 4])

    def test_bake_only_darkens_inside_the_blob(self):
        layer = blob_layer()
        image = random_image(80, 80, 5)
        out, _, _ = tb.bake_rgba(image, 80, 80, layer, 2.3)
        for offset in range(0, len(image), 4):
            self.assertEqual(out[offset], image[offset], "R of the stock-like layer is 255")
            self.assertLessEqual(out[offset + 1], image[offset + 1])
            self.assertLessEqual(out[offset + 2], image[offset + 2])

    def test_invalid_inputs_are_refused(self):
        layer = blob_layer()
        for k in (0, -1, tb.MAX_K + 0.01, float("nan"), float("inf"), True, "1"):
            with self.assertRaises(tb.BlushError):
                tb.bake_rgba(bytes(4), 1, 1, layer, k)
        with self.assertRaises(tb.BlushError):
            tb.bake_rgba(bytes(8), 1, 1, layer, 1.0)
        for value in (2, -1, 0.0, True, "0", None):
            with self.assertRaises(tb.BlushError):
                tb.checked_layer(value)

    def test_payload_verification_and_missing_array(self):
        self.assertFalse(tb.verify_payload(None))
        self.assertFalse(tb.verify_payload(b""))
        self.assertFalse(tb.verify_payload(bytes(tb.CHEEK_PAYLOAD_BYTES)))
        payload = blob_layer() + blob_layer(darkest=(255, 210, 207))
        self.assertFalse(tb.verify_payload(payload), "a synthetic array never passes the stock hash")
        with patch.object(tb, "CHEEK_SHA256", hashlib.sha256(payload).hexdigest()):
            self.assertTrue(tb.verify_payload(payload))
        self.assertEqual(tb.layer_bytes(payload, 1), payload[tb.CHEEK_LAYER_BYTES:])
        with self.assertRaises(tb.BlushError):
            tb.layer_bytes(payload[:-1], 0)


class LevelTests(unittest.TestCase):
    # Cheek-centre colours of ten real heads (5x5 means at the darkest layer-0
    # texel); measurements only, no texture data.
    REAL_SKINS = ((250, 207, 203), (250, 194, 188), (250, 201, 194), (250, 200, 193), (249, 207, 202),
                  (252, 191, 188), (250, 195, 191), (250, 207, 203), (251, 200, 194), (250, 211, 206))

    def test_ciede2000_matches_published_reference_pairs(self):
        # Sharma, Wu and Dalal (2005), Table 1: pairs 1, 7, 17, 25 and 34.
        for lab1, lab2, expected in (
                ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
                ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
                ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
                ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
                ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373)):
            self.assertAlmostEqual(tb.ciede2000(lab1, lab2), expected, places=4)

    def test_named_levels_are_ordered_and_evenly_distinguishable(self):
        ks = [k for _, k in tb.LEVELS]
        self.assertEqual([name for name, _ in tb.LEVELS], ["veryLight", "light", "medium", "strong", "veryStrong"])
        self.assertEqual(ks, sorted(ks))
        self.assertEqual(tb.DEFAULT_LEVEL, "medium")
        self.assertEqual(tb.DEFAULT_LAYER, 0)
        steps = tb.level_differences()
        # Documented values (texture_blush.LEVELS comment).
        self.assertEqual([round(step, 2) for step in steps], [4.69, 4.59, 4.93, 4.90, 5.01])
        self.assertLess(max(steps) - min(steps), 0.5, "equal perceptual steps")
        self.assertEqual([tb.centre_colour(tb.REFERENCE_SKIN, k) for k in ks],
                         [(250, 184, 175), (250, 167, 155), (250, 148, 132), (250, 128, 108), (250, 106, 82)])
        for skin in self.REAL_SKINS:
            for layer in tb.LAYERS:
                self.assertGreaterEqual(min(tb.level_differences(skin, layer)), 4.2, (skin, layer))

    def test_strongest_level_and_limit_stay_far_from_clipping(self):
        for layer, texel in tb.DARKEST_TEXEL.items():
            t = [value / 255 for value in texel]
            self.assertGreater(min(tb.factor(t, tb.LEVELS[-1][1])), 0.4)
            self.assertGreater(min(tb.factor(t, tb.MAX_K)), 0.2)
            # Every channel reaches 0 only well above the strongest level.
            self.assertGreater(min(1 / (1 - value) for value in t if value < 1), tb.MAX_K + 1)


@unittest.skipUnless(os.environ.get("REAL_MV_SAMPLES"), "set REAL_MV_SAMPLES to a folder with costume bundles")
class RealArrayTests(unittest.TestCase):
    def test_stock_layers_match_the_documented_texels(self):
        import UnityPy
        payload = None
        for path in sorted(Path(os.environ["REAL_MV_SAMPLES"]).glob("*costume*.unity")):
            for obj in UnityPy.load(str(path)).objects:
                if obj.type.name == "Texture2DArray":
                    data = bytes(obj.read().image_data)
                    if tb.verify_payload(data):
                        payload = data
            if payload:
                break
        self.assertIsNotNone(payload)
        for layer, bounds in ((0, (70, 114, 220, 158)), (1, (69, 106, 220, 169))):
            data = tb.layer_bytes(payload, layer)
            self.assertEqual(tb.layer_bounds(data), bounds)
            darkest = min((data[i + 1] + data[i + 2], tuple(data[i:i + 3])) for i in range(0, len(data), 4))[1]
            self.assertEqual(darkest, tb.DARKEST_TEXEL[layer])
            for x in range(SIZE):
                for y in (0, SIZE - 1):
                    self.assertEqual(data[(y * SIZE + x) * 4:(y * SIZE + x) * 4 + 3], b"\xff\xff\xff")
                    self.assertEqual(data[(x * SIZE + y) * 4:(x * SIZE + y) * 4 + 3], b"\xff\xff\xff")


if __name__ == "__main__":
    unittest.main()
