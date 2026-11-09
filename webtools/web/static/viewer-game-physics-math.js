/* Original Unity Quaternion numeric paths, using Unity [x,y,z,w] arrays.
 * Sources: libunity 212460/206024/211ed4 (FromTo), 2f0bc4 (Inverse),
 * 20bc68 order 4 (Euler), 2f0cbc/20b87c order 4 (Euler angles).
 * Arithmetic is rounded after each original float instruction. JS Math supplies
 * transcendental functions; native Android libm fixtures bound that difference.
 */
(function (global) {
  'use strict';
  var f = Math.fround;
  function add(a, b) { return f(a + b); }
  function sub(a, b) { return f(a - b); }
  function mul(a, b) { return f(a * b); }
  function div(a, b) { return f(a / b); }
  function square(a) { return mul(a, a); }
  function length(v) {
    var sum = add(square(v[0]), square(v[1]));
    sum = add(sum, square(v[2]));
    if (v.length === 4) sum = add(sum, square(v[3]));
    return f(Math.sqrt(sum));
  }
  var epsilon = f(0.00001);
  function normalized(v, fallback) {
    var values = v.map(f), magnitude = length(values);
    return magnitude < epsilon ? fallback.slice() : values.map(function (x) { return div(x, magnitude); });
  }
  function inverse(q) { return [-f(q[0]), -f(q[1]), -f(q[2]), f(q[3])]; }

  // Unity's column-major matrix-to-quaternion conversion includes a final
  // normalization. Its diagonal tie rule and hemisphere are significant for
  // antiparallel vectors and are preserved here.
  function matrixQuaternion(m) {
    var trace = add(add(m[0], m[4]), m[8]), q = [0, 0, 0, 0], s, scale;
    if (trace > 0) {
      s = f(Math.sqrt(add(trace, 1)));
      q[3] = mul(s, 0.5); scale = div(0.5, s);
      q[0] = mul(scale, sub(m[5], m[7]));
      q[1] = mul(scale, sub(m[6], m[2]));
      q[2] = mul(scale, sub(m[1], m[3]));
    } else {
      var i = m[4] > m[0] ? 1 : 0;
      if (m[8] > m[i * 4]) i = 2;
      var j = (i + 1) % 3, k = (j + 1) % 3;
      s = f(Math.sqrt(add(sub(sub(m[i * 4], m[j * 4]), m[k * 4]), 1)));
      q[i] = mul(s, 0.5); scale = div(0.5, s);
      q[3] = mul(scale, sub(m[j * 3 + k], m[k * 3 + j]));
      q[j] = mul(scale, add(m[i * 3 + j], m[j * 3 + i]));
      q[k] = mul(scale, add(m[i * 3 + k], m[k * 3 + i]));
    }
    var magnitude = length(q);
    return q.map(function (x) { return div(x, magnitude); });
  }
  function fromToRotation(from, to) {
    var a = from.map(f), b = to.map(f), al = length(a), bl = length(b);
    if (al < epsilon || bl < epsilon) return [0, 0, 0, 1];
    a = a.map(function (x) { return div(x, al); });
    b = b.map(function (x) { return div(x, bl); });
    var x = a[0], y = a[1], z = a[2];
    var dot = add(mul(b[1], y), mul(b[0], x));
    dot = add(mul(b[2], z), dot);
    if (dot > 0.9999990000000025) return [0, 0, 0, 1];
    var m;
    if (dot < -0.9999990000000025) {
      // Original deterministic orthogonal-basis branch (206084). In particular
      // X to -X uses +Y; choosing an arbitrary cross-product axis changes it.
      var xx = square(x), yy = square(y), zz = square(z);
      var ax, ay, az;
      if (add(add(zz, 0), yy) < f(0.000001)) { ax = f(-z); ay = 0; az = x; }
      else { ax = 0; ay = z; az = f(-y); }
      var reciprocal = div(1, f(Math.sqrt(add(square(az), add(square(ax), square(ay))))));
      ax = mul(reciprocal, ax); ay = mul(reciprocal, ay); az = mul(reciprocal, az);
      var cx = sub(mul(z, ay), mul(y, az));
      var cy = sub(mul(az, x), mul(z, ax));
      var cz = sub(mul(y, ax), mul(ay, x));
      var xy = sub(sub(mul(cx, cy), mul(x, y)), mul(ax, ay));
      var xz = sub(sub(mul(cx, cz), mul(x, z)), mul(ax, az));
      var yz = sub(sub(mul(cy, cz), mul(y, z)), mul(ay, az));
      m = [sub(sub(square(cx), xx), square(ax)), xy, xz,
        xy, sub(sub(square(cy), yy), square(ay)), yz,
        xz, yz, sub(sub(square(cz), zz), square(az))];
    } else {
      var vx = sub(mul(y, b[2]), mul(z, b[1]));
      var vy = sub(mul(z, b[0]), mul(x, b[2]));
      var vz = sub(mul(x, b[1]), mul(y, b[0]));
      var h = div(sub(1, dot), add(square(vz), add(square(vx), square(vy))));
      var hx = mul(vx, h), hz = mul(vz, h), hy = mul(vy, h);
      var hxy = mul(vy, hx), hxz = mul(vz, hx), hyz = mul(vy, hz);
      m = [add(dot, mul(vx, hx)), add(vz, hxy), sub(hxz, vy),
        sub(hxy, vz), add(dot, mul(vy, hy)), add(vx, hyz),
        add(vy, hxz), sub(hyz, vx), add(dot, mul(vz, hz))];
    }
    return matrixQuaternion(m);
  }

  function fromEulerRad(radians) {
    var r = radians.map(function (x) { return mul(f(x), 0.5); });
    var sx = f(Math.sin(r[0])), cx = f(Math.cos(r[0]));
    var sy = f(Math.sin(r[1])), cy = f(Math.cos(r[1]));
    var sz = f(Math.sin(r[2])), cz = f(Math.cos(r[2]));
    // Original order-4 branch first combines X and Y, then Z (20bfd4).
    var a = mul(sx, sy), b = mul(cx, cy), c = mul(cx, sy), d = mul(sx, cy);
    return [add(mul(d, cz), mul(sz, c)), sub(mul(cz, c), mul(d, sz)),
      add(mul(sz, b), mul(cz, f(-a))), sub(mul(cz, b), mul(sz, f(-a)))];
  }
  function euler(degrees) { return fromEulerRad(degrees.map(function (x) { return mul(f(x), f(0.0174532924)); })); }

  function toEulerRad(q) {
    q = normalized(q, [0, 0, 0, 1]);
    var x = q[0], y = q[1], z = q[2], w = q[3];
    var xx = square(x), yy = square(y), zz = square(z), ww = square(w);
    var xy = mul(x, y), xz = mul(x, z), xw = mul(x, w);
    var yz = mul(y, z), yw = mul(y, w), zw = mul(z, w);
    var test = sub(yz, xw), xAngle = f(-Math.asin(Math.max(-1, Math.min(1, add(test, test)))));
    var yAngle, zAngle;
    if (Math.abs(test) < f(0.4999989867210388)) {
      yAngle = f(Math.atan2(add(add(xz, yw), add(xz, yw)), add(ww, sub(sub(zz, xx), yy))));
      zAngle = f(Math.atan2(add(add(xy, zw), add(xy, zw)), add(ww, sub(sub(yy, zz), xx))));
    } else {
      var a = add(xy, zw), b = sub(xw, yz), c = sub(xy, zw), d = add(yz, xw);
      yAngle = f(Math.atan2(add(mul(a, d), mul(b, c)), sub(mul(b, d), mul(a, c))));
      zAngle = 0;
    }
    return [xAngle, yAngle, zAngle];
  }
  function angles(q) {
    var negativeFlip = mul(f(-0.0001), f(57.29578)), positiveFlip = add(360, negativeFlip);
    return toEulerRad(q).map(function (r) {
      var v = mul(r, f(57.29578));
      return v < negativeFlip ? add(v, 360) : (v > positiveFlip ? sub(v, 360) : v);
    });
  }
  global.ViewerGamePhysicsMath = Object.freeze({fromToRotation: fromToRotation, inverse: inverse,
    euler: euler, angles: angles, fromEulerRad: fromEulerRad, toEulerRad: toEulerRad});
})(typeof window === 'undefined' ? globalThis : window);
