"""Independent world-space collision measurements, never used by the solver.

A tapered capsule is the union of linearly interpolated endpoint balls. Surface
clearance minimizes point/triangle distance minus radius over that centerline.
The 1D function is convex because triangles are convex. Golden-section search
measures actual skinned triangles rather than assuming a joint endpoint controls
all cloth. Negative results prove an intersecting triangle; a tolerance applies.
"""
import math
import numpy as np


def closest_segment(points, a, b):
    points = np.asarray(points, float); a = np.asarray(a, float); b = np.asarray(b, float)
    line = b - a; length = float(line @ line)
    t = np.clip(np.sum((points - a) * line, axis=-1) / length, 0, 1) if length > 1e-24 else np.zeros(points.shape[:-1])
    return a + t[..., None] * line, t


def point_triangle_distance(points, triangles):
    """Distance from one point per triangle to the finite triangle (not plane)."""
    points, triangles = np.asarray(points, float), np.asarray(triangles, float)
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    candidates = []
    for first, last in ((a, b), (b, c), (c, a)):
        line = last - first; denominator = np.sum(line * line, axis=1)
        t = np.clip(np.divide(np.sum((points - first) * line, axis=1), denominator,
                              out=np.zeros(len(points)), where=denominator > 1e-24), 0, 1)
        candidates.append(first + t[:, None] * line)
    normal = np.cross(b - a, c - a); norm2 = np.sum(normal * normal, axis=1)
    scale = np.divide(np.sum((points - a) * normal, axis=1), norm2, out=np.zeros(len(points)), where=norm2 > 1e-24)
    projected = points - scale[:, None] * normal
    ab, ac, ap = b - a, c - a, projected - a
    d00, d01, d11 = np.sum(ab * ab, axis=1), np.sum(ab * ac, axis=1), np.sum(ac * ac, axis=1)
    d20, d21 = np.sum(ap * ab, axis=1), np.sum(ap * ac, axis=1)
    divisor = d00 * d11 - d01 * d01
    u = np.divide(d11 * d20 - d01 * d21, divisor, out=np.full(len(points), -1.), where=np.abs(divisor) > 1e-24)
    v = np.divide(d00 * d21 - d01 * d20, divisor, out=np.full(len(points), -1.), where=np.abs(divisor) > 1e-24)
    interior = (u >= -1e-12) & (v >= -1e-12) & (u + v <= 1 + 1e-12) & (norm2 > 1e-24)
    distance2 = np.min(np.asarray([np.sum((points - value) ** 2, axis=1) for value in candidates]), axis=0)
    distance2 = np.where(interior, np.minimum(distance2, np.sum((points - projected) ** 2, axis=1)), distance2)
    return np.sqrt(np.maximum(0, distance2))


def triangle_capsule_clearance(triangles, a, b, r0, r1, iterations=48):
    """Signed clearance per actual triangle to the continuous tapered capsule."""
    triangles = np.asarray(triangles, float); a, b = np.asarray(a, float), np.asarray(b, float)
    if triangles.shape[0] == 0:
        return np.empty(0)
    def value(t):
        return point_triangle_distance(a + t[:, None] * (b - a), triangles) - (r0 + t * (r1 - r0))
    lo, hi = np.zeros(len(triangles)), np.ones(len(triangles)); ratio = (math.sqrt(5) - 1) / 2
    left, right = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fl, fr = value(left), value(right)
    for _ in range(iterations):
        choose = fl < fr
        hi, lo = np.where(choose, right, hi), np.where(choose, lo, left)
        left, right = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
        fl, fr = value(left), value(right)
    return np.minimum.reduce([fl, fr, value(np.zeros(len(triangles))), value(np.ones(len(triangles)))])


def point_capsule_clearance(points, a, b, r0, r1, point_radius=0., iterations=48):
    """Same independent convex minimum for joint spheres or mesh vertices."""
    points = np.asarray(points, float); a, b = np.asarray(a, float), np.asarray(b, float)
    def value(t):
        return np.linalg.norm(points - a - t[:, None] * (b - a), axis=1) - (r0 + t * (r1 - r0)) - point_radius
    lo, hi = np.zeros(len(points)), np.ones(len(points)); ratio = (math.sqrt(5) - 1) / 2
    for _ in range(iterations):
        left, right = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
        choose = value(left) < value(right)
        hi, lo = np.where(choose, right, hi), np.where(choose, lo, left)
    return np.minimum.reduce([value((lo + hi) / 2), value(np.zeros(len(points))), value(np.ones(len(points)))])


def fixed_length_sphere_minimum_angle(length, pivot_distance, radius):
    """Analytic feasible cone boundary; independent of iterative projection."""
    if radius > length + pivot_distance:
        return None
    if pivot_distance < 1e-12 or radius <= abs(length - pivot_distance):
        return 0.
    return math.acos(max(-1., min(1., (length * length + pivot_distance * pivot_distance - radius * radius) / (2 * length * pivot_distance))))
