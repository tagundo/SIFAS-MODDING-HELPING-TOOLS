"""The array samplers in model_animation must give the reference floats bit for bit."""
import bisect
import math
import random
import struct
import unittest

import numpy as np

from webtools.core import model_animation as ma


def bits(values):
    return struct.pack(f"<{len(values)}d", *values)


def reference_evaluate(curve, stamp):
    # The original per-stamp evaluation (bisect over the keys for every stamp).
    mode, keys = curve
    if mode == "constant":
        return keys
    if not keys:
        raise ma.AnimationError("An animation binding has no scalar curve values.")
    index = max(0, bisect.bisect_right(keys, stamp, key=lambda item: item[0]) - 1)
    start, value = keys[index]
    if mode == "cubic":
        if abs(start) > 1e20:
            return value[3]
        delta = max(0., stamp - start)
        return ((value[0] * delta + value[1]) * delta + value[2]) * delta + value[3]
    if index + 1 < len(keys):
        stop, other = keys[index + 1]
        if stop > start:
            fraction = min(1., max(0., (stamp - start) / (stop - start)))
            return value + (other - value) * fraction
    return value


def reference_rotation(columns, euler, order):
    values = []
    for row in zip(*columns):
        row = ma.unity_euler_quaternion(row, order) if euler else row
        length = math.sqrt(sum(value * value for value in row))
        if not math.isfinite(length) or length < 1e-12:
            raise ma.AnimationError("An animated rotation is invalid.")
        x, y, z, w = (value / length for value in row)
        values.append([x, -y, -z, w])
    for previous, current in zip(values, values[1:]):
        if sum(a * b for a, b in zip(previous, current)) < 0:
            current[:] = [-value for value in current]
    return values


def odd_float(rng):
    choice = rng.random()
    if choice < .05:
        return rng.choice([0., -0., 1., -1., 5e-324, -5e-324, 1e-300, 1e300])
    if choice < .25:
        return rng.uniform(-1, 1) * 10 ** rng.randint(-12, 12)
    return rng.uniform(-3, 3)


def grid(rng, count):
    stamps = sorted(rng.uniform(-1, 9) for _ in range(count))
    # Repeated and signed-zero stamps occur on real grids (authored boundaries).
    stamps[count // 3:count // 3 + 3] = [stamps[count // 3]] * 3
    if count > 10:
        stamps[5] = -0.
        stamps[6] = 0.
        stamps.sort()
    return stamps


def keys_for(rng, mode, count):
    stamps = sorted(rng.uniform(-2, 10) for _ in range(count))
    if count > 4:
        stamps[2] = stamps[1]  # equal key times
    if mode == "cubic":
        rows = [(stamp, tuple(odd_float(rng) for _ in range(4))) for stamp in stamps]
        if count > 3 and rng.random() < .5:
            rows[0] = (-3.4028234663852886e38, rows[0][1])  # Unity's negative sentinel
        return rows
    return [(stamp, odd_float(rng)) for stamp in stamps]


class ArraySamplingTests(unittest.TestCase):
    def test_curve_samples_match_the_per_stamp_reference(self):
        rng = random.Random(20261125)
        for case in range(300):
            mode = rng.choice(["cubic", "linear", "constant"])
            times = grid(rng, rng.choice([1, 2, 63, 64, 65, 400]))
            curve = (mode, odd_float(rng)) if mode == "constant" else (mode, keys_for(rng, mode, rng.choice([1, 2, 3, 40, 900])))
            expected = [reference_evaluate(curve, stamp) for stamp in times]
            with self.subTest(case=case, mode=mode, samples=len(times)):
                walked = ma._sample(curve, times)
                self.assertEqual(bits(walked), bits(expected))
                column, = ma._columns([curve], times)
                self.assertEqual(bits(column), bits(expected))
                self.assertTrue(all(type(value) is float for value in column))
                if mode != "constant":
                    self.assertEqual(bits(ma._sample_array(curve, np.array(times))), bits(expected))

    def test_unordered_key_tables_keep_the_per_stamp_bisect(self):
        # bisect_right over keys that are not ascending lands on keys a forward walk never
        # reaches; small grids (the walk) and large ones (the array path) both repeat it.
        rng = random.Random(5)
        for mode in ("cubic", "linear"):
            keys = keys_for(rng, mode, 40)
            keys[10], keys[30] = keys[30], keys[10]
            keys.insert(3, (keys[-1][0] + 1., keys[3][1]))
            curve = (mode, keys)
            for count in (5, 63, 64, 400):
                times = grid(rng, count)
                expected = [reference_evaluate(curve, stamp) for stamp in times]
                with self.subTest(mode=mode, samples=count):
                    self.assertIsNone(ma._sample_array(curve, np.array(times)))
                    self.assertEqual(bits(ma._sample(curve, times)), bits(expected))
                    self.assertEqual(bits(ma._columns([curve], times)[0]), bits(expected))
        # A table whose walk and bisect disagree: the walk would stop at the key at 5.
        curve = ("linear", [(0., 0.), (5., 10.), (1., 20.), (6., 30.)])
        times = [0.5, 2., 5.5]
        self.assertEqual(ma._sample(curve, times), [reference_evaluate(curve, stamp) for stamp in times])

    def test_unordered_grid_and_empty_curve_keep_reference_behaviour(self):
        curve = ("linear", [(0., 1.), (1., 3.)])
        times = [.5, .25, 1.]
        self.assertEqual(ma._columns([curve], times)[0], [reference_evaluate(curve, stamp) for stamp in times])
        for times in ([0.] * 100, [0.]):
            with self.assertRaisesRegex(ma.AnimationError, "no scalar curve values"):
                ma._columns([("cubic", [])], times)
        self.assertEqual(ma._columns([("cubic", [])], []), [[]])

    def test_sum4_is_this_interpreters_sum(self):
        self.assertTrue(ma._array_sum_matches())
        rng = random.Random(7)
        rows = [tuple(odd_float(rng) * rng.choice([1, 1e16, 1e-16]) for _ in range(4)) for _ in range(20000)]
        with np.errstate(all="ignore"):
            found = ma._sum4(*(np.array(column) for column in zip(*rows))).tolist()
        self.assertEqual(bits(found), bits([sum(row) for row in rows]))

    def test_rotation_rows_match_the_row_reference(self):
        rng = random.Random(11)
        for case in range(60):
            count = rng.choice([2, 63, 64, 500])
            euler = case % 3 == 0
            order = rng.randrange(6)
            if euler:
                columns = [[rng.uniform(-720, 720) for _ in range(count)] for _ in range(3)]
            else:
                # Neighbouring rows of opposite hemispheres exercise the continuity flip.
                base = [rng.uniform(-1, 1) for _ in range(4)]
                columns = [[(value + rng.uniform(-.3, .3)) * rng.choice([1, 1, -1]) * 10 ** rng.randint(-3, 3)
                            for _ in range(count)] for value in base]
            with self.subTest(case=case, euler=euler, rows=count):
                expected = reference_rotation(columns, euler, order)
                found = ma._rotation_rows(columns, euler, order)
                self.assertEqual(len(found), len(expected))
                self.assertEqual(bits([v for row in found for v in row]), bits([v for row in expected for v in row]))

    def test_invalid_rotation_raises_like_the_reference(self):
        columns = [[0.] * 100, [0.] * 100, [0.] * 100, [1.] * 99 + [0.]]
        with self.assertRaisesRegex(ma.AnimationError, "rotation is invalid"):
            reference_rotation(columns, False, 4)
        with self.assertRaisesRegex(ma.AnimationError, "rotation is invalid"):
            ma._rotation_rows(columns, False, 4)


if __name__ == "__main__":
    unittest.main()
