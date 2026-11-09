import math
import unittest
import numpy as np
from physics_collision_oracle import (point_triangle_distance, triangle_capsule_clearance,
    point_capsule_clearance, fixed_length_sphere_minimum_angle)


class IndependentCollisionOracleTests(unittest.TestCase):
    def test_finite_triangle_distance_not_infinite_plane(self):
        triangle = np.array([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]])
        for point, distance in (([.2, .2, .5], .5), ([1, 1, 0], math.sqrt(.5)), ([-1, 0, 0], 1)):
            self.assertAlmostEqual(point_triangle_distance([point], triangle)[0], distance, places=10)

    def test_triangle_can_intersect_while_every_vertex_and_bone_endpoint_are_clear(self):
        triangle = np.array([[[-1., -1., 0.], [1., -1., 0.], [0., 1., 0.]]])
        a, b, radius = [0, 0, -.2], [0, 0, .2], .1
        vertex_gap = point_capsule_clearance(triangle[0], a, b, radius, radius)
        self.assertTrue((vertex_gap > .8).all())
        self.assertAlmostEqual(triangle_capsule_clearance(triangle, a, b, radius, radius)[0], -.1, places=8)

    def test_unequal_radii_find_true_nearest_ball_not_centerline_projection(self):
        points = np.array([[.5, .3, 0.]])
        gap = point_capsule_clearance(points, [0, 0, 0], [1, 0, 0], .1, .5)[0]
        dense = min(np.linalg.norm(points[0] - [t, 0, 0]) - (.1 + .4 * t) for t in np.linspace(0, 1, 10001))
        self.assertAlmostEqual(gap, dense, places=7)
        self.assertLess(gap, 0, 'point is inside the authored taper despite centerline-closest sphere tangent at t=.5')

    def test_length_normalization_can_reintroduce_real_collision(self):
        tip, center = np.array([1., 0., 0.]), np.array([.7, 0., 0.])
        pushed = center + (tip - center) / np.linalg.norm(tip - center) * .5
        normalized = pushed / np.linalg.norm(pushed)
        self.assertAlmostEqual(np.linalg.norm(normalized - center) - .5, -.2)
        angle = fixed_length_sphere_minimum_angle(1, .7, .5)
        feasible = np.array([math.cos(angle), math.sin(angle), 0])
        self.assertAlmostEqual(np.linalg.norm(feasible - center), .5)
        self.assertGreater(fixed_length_sphere_minimum_angle(1, .7, .55), angle, 'SwingBone radius requires extra clearance')

    def test_blended_cloth_can_require_two_joints_to_move_together(self):
        angle = math.radians(60)
        rest = np.array([1., 0., 0.]); moved = np.array([math.cos(angle), math.sin(angle), 0.])
        one_joint = .5 * rest + .5 * moved
        both_joints = moved
        first_gap = point_capsule_clearance([one_joint], [.7, 0, 0], [.7, 0, 0], .5, .5)[0]
        coupled_gap = point_capsule_clearance([both_joints], [.7, 0, 0], [.7, 0, 0], .5, .5)[0]
        self.assertLess(first_gap, -.06, 'one permitted joint alone cannot clear the blended cloth point')
        self.assertGreater(coupled_gap, .38, 'a feasible coupled joint response exists')


if __name__ == '__main__':
    unittest.main()
