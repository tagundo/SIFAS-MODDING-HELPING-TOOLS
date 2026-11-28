/* Camera math of the MV Studio camera editor (MVStudioCameraMath).

   Data space is Unity, exactly as the project stores a MainCamera shot: the rig
   root's left-handed position [x, y, z], its quaternion [x, y, z, w] and the
   authored vertical FOV (before the client's aspect correction). The rig looks
   along its -Z axis.

   - three.js mapping (poseCamera's, and its own inverse): position (-x, y, z),
     quaternion (x, -y, -z, w).
   - Editing Euler = Unity's inspector convention, ZXY: q = qY(pan) * qX(tilt) *
     qZ(roll) in degrees, so for this rig pan + turns the view right, tilt + looks
     up and roll is Unity Z. Quaternions stay the stored truth; an Euler readout
     is unwrapped to a reference (the previous key or sample).
   - sampleFrames() interpolates the dense samples exactly as poseCamera does
     (binary search, Vector3.lerp, three's Quaternion.slerp, FOV lerp).
   - curve() is a Blender-style F-curve per channel: constant / linear / bezier
     segments, auto-clamped / auto / flat / free handles, constant extrapolation.
   - simplify() is a joint Ramer-Douglas-Peucker pass with a tolerance per
     channel group (position m, rotation deg, FOV deg). */
(function (global) {
  "use strict";

  const RAD = Math.PI / 180, DEG = 180 / Math.PI;
  const finite = Number.isFinite;
  const CHANNELS = Object.freeze(["x", "y", "z", "pan", "tilt", "roll", "fov"]);
  const POSITION = Object.freeze(["x", "y", "z"]);
  const ROTATION = Object.freeze(["pan", "tilt", "roll"]);
  const INTERPOLATIONS = Object.freeze(["constant", "linear", "bezier"]);
  const HANDLES = Object.freeze(["auto-clamped", "auto", "flat", "free"]);
  const TOLERANCE = Object.freeze({ position: .002, rotation: .05, fov: .01 });

  const vector = (value, size) => Array.isArray(value) && value.length >= size && value.slice(0, size).every(finite);

  // ---- three.js <-> Unity (poseCamera's mapping; each is its own inverse) --------------
  function unityToThreePosition(p) { return [-p[0], p[1], p[2]]; }
  function threeToUnityPosition(p) { return [-p[0], p[1], p[2]]; }
  function unityToThreeQuaternion(q) { return [q[0], -q[1], -q[2], q[3]]; }
  function threeToUnityQuaternion(q) { return [q[0], -q[1], -q[2], q[3]]; }

  // ---- quaternions [x, y, z, w] ----------------------------------------------------------
  function multiply(a, b) {
    const [x, y, z, w] = a, [X, Y, Z, W] = b;
    return [w * X + x * W + y * Z - z * Y, w * Y - x * Z + y * W + z * X, w * Z + x * Y - y * X + z * W, w * W - x * X - y * Y - z * Z];
  }

  function conjugate(q) { return [-q[0], -q[1], -q[2], q[3]]; }

  // three's Quaternion.normalize (multiplies by the reciprocal length).
  function normalize(q) {
    let length = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    if (length === 0) return [0, 0, 0, 1];
    length = 1 / length;
    return [q[0] * length, q[1] * length, q[2] * length, q[3] * length];
  }

  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]; }

  // three r128 Quaternion.slerp, operation for operation (a is `this`).
  function slerp(a, b, t) {
    if (t === 0) return a.slice(0, 4);
    if (t === 1) return b.slice(0, 4);
    const x = a[0], y = a[1], z = a[2], w = a[3];
    let cosHalf = w * b[3] + x * b[0] + y * b[1] + z * b[2];
    let bx = b[0], by = b[1], bz = b[2], bw = b[3];
    if (cosHalf < 0) { bw = -bw; bx = -bx; by = -by; bz = -bz; cosHalf = -cosHalf; }
    if (cosHalf >= 1) return [x, y, z, w];
    const sqrSin = 1 - cosHalf * cosHalf;
    if (sqrSin <= Number.EPSILON) {
      const s = 1 - t;
      return normalize([s * x + t * bx, s * y + t * by, s * z + t * bz, s * w + t * bw]);
    }
    const sinHalf = Math.sqrt(sqrSin), half = Math.atan2(sinHalf, cosHalf);
    const ra = Math.sin((1 - t) * half) / sinHalf, rb = Math.sin(t * half) / sinHalf;
    return [x * ra + bx * rb, y * ra + by * rb, z * ra + bz * rb, w * ra + bw * rb];
  }

  // three's Vector3.applyQuaternion.
  function rotateVector(q, v) {
    const [qx, qy, qz, qw] = q, [x, y, z] = v;
    const ix = qw * x + qy * z - qz * y, iy = qw * y + qz * x - qx * z;
    const iz = qw * z + qx * y - qy * x, iw = -qx * x - qy * y - qz * z;
    return [ix * qw + iw * -qx + iy * -qz - iz * -qy, iy * qw + iw * -qy + iz * -qx - ix * -qz,
      iz * qw + iw * -qz + ix * -qy - iy * -qx];
  }

  function axisQuaternion(axis, degrees) {
    const half = degrees * RAD * .5, q = [0, 0, 0, Math.cos(half)];
    q[axis] = Math.sin(half);
    return q;
  }

  // Unity Quaternion.Euler(tilt, pan, roll): q = qY(pan) * qX(tilt) * qZ(roll).
  function eulerZXYToQuaternion(euler) {
    const pan = finite(euler?.pan) ? euler.pan : 0, tilt = finite(euler?.tilt) ? euler.tilt : 0, roll = finite(euler?.roll) ? euler.roll : 0;
    return multiply(axisQuaternion(1, pan), multiply(axisQuaternion(0, tilt), axisQuaternion(2, roll)));
  }

  // model_animation.quat_to_unity_euler for order ZXY (a = z, b = x, c = y, even order).
  function principalZXY(q) {
    const n = normalize(q), [x, y, z, w] = n;
    const m = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
      [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
      [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
    const cb = Math.hypot(m[1][0], m[1][1]);
    const angles = [0, 0, 0];   // Unity x (tilt), y (pan), z (roll)
    angles[0] = Math.atan2(-m[1][2], cb);
    if (cb > 1e-9) {
      angles[2] = Math.atan2(m[1][0], m[1][1]);
      angles[1] = Math.atan2(m[0][2], m[2][2]);
    } else angles[1] = Math.atan2(-m[2][0], m[0][0]);
    return angles.map((value) => value * DEG);
  }

  // model_animation.unity_euler_near: the Euler solution nearest `near` ({pan, tilt, roll}),
  // unwrapped by whole turns; at the tilt +-90 gimbal roll is pinned to near and pan solved.
  function quaternionToEulerZXY(q, near) {
    const euler = principalZXY(q);
    const pack = (angles) => ({ pan: angles[1], tilt: angles[0], roll: angles[2] });
    if (!near || ![near.pan, near.tilt, near.roll].every(finite)) return pack(euler);
    const reference = [near.tilt, near.pan, near.roll];
    const candidates = [euler.slice(), [euler[0], euler[1], euler[2]]];
    // The other branch: (a + 180, 180 - b, c + 180) with a = z, b = x, c = y.
    candidates[1][2] += 180; candidates[1][0] = 180 - candidates[1][0]; candidates[1][1] += 180;
    if (Math.abs(Math.cos(euler[0] * RAD)) < 1e-6) {
      const qa = axisQuaternion(2, reference[2]), qb = axisQuaternion(0, euler[0]);
      const qc = multiply(normalize(q), conjugate(multiply(qb, qa)));
      const pinned = euler.slice();
      pinned[2] = reference[2];
      pinned[1] = 2 * Math.atan2(qc[1], qc[3]) * DEG;
      candidates.push(pinned);
    }
    let best = null, distance = Infinity;
    for (const candidate of candidates) {
      const unwrapped = candidate.map((value, index) => value + 360 * Math.round((reference[index] - value) / 360));
      const gap = unwrapped.reduce((sum, value, index) => sum + (value - reference[index]) ** 2, 0);
      if (gap < distance) { best = unwrapped; distance = gap; }
    }
    return pack(best);
  }

  // ---- lens -------------------------------------------------------------------------------
  // CameraAspectCorrector (mv-studio-split.js): fov shown = authored / correction.
  function aspectCorrection(aspect) {
    if (global.MVStudioSplit?.aspectCorrection) return global.MVStudioSplit.aspectCorrection(aspect);
    return Math.min(1, Math.max(.75, aspect / (16 / 9)));
  }

  // The preview applies the correction to the native MainCamera AnimationTrack only.
  function nativeLens(track) {
    return !!track && track.nativeClass === "AnimationTrack" && /(?:^|\/)MainCamera$/i.test(track.binding || "");
  }

  // ---- dense samples (poseCamera) ------------------------------------------------------------
  function sampleIndex(frames, local) {
    let lower = 0, upper = frames.length;
    while (lower < upper) {
      const mid = (lower + upper) >>> 1;
      if (frames[mid].time <= local) lower = mid + 1;
      else upper = mid;
    }
    return [Math.max(0, lower - 1), Math.min(lower, frames.length - 1)];
  }

  // The pose poseCamera gives at `local` seconds into a shot; `values` is the event's
  // values (static fallback FOV). null when the samples have no pose.
  function sampleFrames(frames, local, values = {}) {
    let left = values, right = values;
    if (Array.isArray(frames) && frames.length) {
      const ordered = frames.every((frame, index) => !index || frame.time >= frames[index - 1].time);
      if (ordered) {
        const [a, b] = sampleIndex(frames, local);
        left = frames[a]; right = frames[b];
      } else {
        left = frames[0]; right = left;
        for (const sample of frames) {
          right = sample;
          if (sample.time > local) break;
          left = sample;
        }
      }
    }
    if (!vector(left.position, 3) || !vector(left.rotation, 4)) return null;
    const fraction = left !== right && right.time > left.time ? Math.max(0, Math.min(1, (local - left.time) / (right.time - left.time))) : 0;
    let position = left.position.slice(0, 3);
    if (vector(right.position, 3)) position = position.map((value, index) => value + (right.position[index] - value) * fraction);
    let rotation = normalize(left.rotation);
    if (vector(right.rotation, 4)) rotation = slerp(rotation, normalize(right.rotation), fraction);
    let fov = finite(left.fov) ? left.fov : values.fov;
    if (finite(fov)) {
      const next = finite(right.fov) ? right.fov : fov;
      fov = Math.min(170, Math.max(1, fov + (next - fov) * fraction));
    } else fov = null;
    return { position, rotation, fov };
  }

  // ---- curves -------------------------------------------------------------------------------
  const isKey = (key) => key && Number.isInteger(key.frame) && key.values && typeof key.values === "object";

  function channelValue(key, channel) {
    const value = key.values[channel];
    return finite(value) ? value : 0;
  }

  // Slope of key i's handles on `channel` for its handle type (free handles are stored).
  function autoSlope(keys, index, channel, clamped) {
    const key = keys[index], previous = keys[index - 1], next = keys[index + 1];
    // Constant extrapolation: the first and last automatic handles are flat (as Blender).
    if (!previous || !next) return 0;
    const v0 = channelValue(previous, channel), v1 = channelValue(key, channel), v2 = channelValue(next, channel);
    const f0 = previous.frame, f1 = key.frame, f2 = next.frame;
    let slope = (v2 - v0) / (f2 - f0);
    if (!clamped) return slope;
    if ((v1 - v0) * (v2 - v1) <= 0) return 0;   // a local extremum stays flat
    // Both handles stay inside their segment's value range: no overshoot.
    const limit = Math.min(3 * Math.abs(v2 - v1) / (f2 - f1), 3 * Math.abs(v1 - v0) / (f1 - f0));
    if (Math.abs(slope) > limit) slope = Math.sign(slope) * limit;
    return slope;
  }

  // Handles of key `index` on `channel`: { in: [dFrames <= 0, dValue], out: [dFrames >= 0, dValue] }.
  function handles(keys, index, channel) {
    const key = keys[index], previous = keys[index - 1], next = keys[index + 1];
    const before = previous ? (key.frame - previous.frame) / 3 : next ? (next.frame - key.frame) / 3 : 1;
    const after = next ? (next.frame - key.frame) / 3 : before;
    const stored = key.handle === "free" && key.handles && key.handles[channel];
    if (stored && vector(stored.in, 2) && vector(stored.out, 2)) {
      return { in: [Math.min(0, stored.in[0]), stored.in[1]], out: [Math.max(0, stored.out[0]), stored.out[1]] };
    }
    const type = HANDLES.includes(key.handle) && key.handle !== "free" ? key.handle : "auto-clamped";
    const slope = type === "flat" ? 0 : autoSlope(keys, index, channel, type === "auto-clamped");
    return { in: [-before, -slope * before], out: [after, slope * after] };
  }

  function bezierPoint(p0, p1, p2, p3, s) {
    const u = 1 - s;
    return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3;
  }

  // Value of the bezier segment from key a to key b at frame f.
  function bezierSegment(a, outHandle, b, inHandle, f) {
    const length = b.frame - a.frame;
    let [ox, oy] = outHandle, [ix, iy] = inHandle;
    // Handle time lengths in [0, length], and together at most the segment (monotonic time).
    if (ox > length) { oy *= length / ox; ox = length; }
    if (-ix > length) { iy *= length / -ix; ix = -length; }
    const total = ox - ix;
    if (total > length && total > 0) { const scale = length / total; ox *= scale; oy *= scale; ix *= scale; iy *= scale; }
    const x0 = a.frame, x1 = a.frame + ox, x2 = b.frame + ix, x3 = b.frame;
    const y0 = a.value, y1 = a.value + oy, y2 = b.value + iy, y3 = b.value;
    // Solve x(s) = f: Newton from the linear guess, bisection when it leaves the bracket.
    let lo = 0, hi = 1, s = (f - x0) / length;
    for (let step = 0; step < 12; step++) {
      const x = bezierPoint(x0, x1, x2, x3, s) - f;
      if (Math.abs(x) < 1e-10) break;
      if (x > 0) hi = s; else lo = s;
      const u = 1 - s;
      const slope = 3 * (u * u * (x1 - x0) + 2 * u * s * (x2 - x1) + s * s * (x3 - x2));
      let next = slope > 1e-12 ? s - x / slope : NaN;
      if (!(next > lo && next < hi)) next = (lo + hi) / 2;
      s = next;
    }
    return bezierPoint(y0, y1, y2, y3, s);
  }

  function sortedKeys(keys) {
    return (Array.isArray(keys) ? keys.filter(isKey) : []).slice().sort((a, b) => a.frame - b.frame);
  }

  // Value of `channel` at frame f (fractional allowed). Keys must be sorted by frame.
  function curve(keys, channel, f) {
    if (!keys.length) return 0;
    if (f <= keys[0].frame) return channelValue(keys[0], channel);
    const last = keys[keys.length - 1];
    if (f >= last.frame) return channelValue(last, channel);
    let lower = 0, upper = keys.length - 1;
    while (upper - lower > 1) {
      const mid = (lower + upper) >> 1;
      if (keys[mid].frame <= f) lower = mid; else upper = mid;
    }
    const a = keys[lower], b = keys[upper];
    const va = channelValue(a, channel), vb = channelValue(b, channel);
    const interp = INTERPOLATIONS.includes(a.interp) ? a.interp : "bezier";
    if (interp === "constant") return va;
    if (interp === "linear") return va + (vb - va) * (f - a.frame) / (b.frame - a.frame);
    return bezierSegment({ frame: a.frame, value: va }, handles(keys, lower, channel).out,
      { frame: b.frame, value: vb }, handles(keys, upper, channel).in, f);
  }

  // Every channel at frame f.
  function evaluate(keys, f) {
    const values = {};
    for (const channel of CHANNELS) values[channel] = curve(keys, channel, f);
    return values;
  }

  // ---- simplify (joint RDP over the channel groups) ---------------------------------------
  // samples: [{ x, y, z, pan, tilt, roll, fov }] on consecutive frames (Euler unwrapped).
  // Returns the kept sample indices (always the first and the last).
  function simplify(samples, tolerance = TOLERANCE) {
    const count = samples.length;
    if (count <= 2) return [...Array(count).keys()];
    const limit = (channel) => POSITION.includes(channel) ? tolerance.position : ROTATION.includes(channel) ? tolerance.rotation : tolerance.fov;
    const channels = CHANNELS.filter((channel) => samples.some((sample) => finite(sample[channel])));
    const keep = new Uint8Array(count);
    keep[0] = keep[count - 1] = 1;
    const stack = [[0, count - 1]];
    while (stack.length) {
      const [first, last] = stack.pop();
      let worst = -1, ratio = 1;
      for (let index = first + 1; index < last; index++) {
        const amount = (index - first) / (last - first);
        for (const channel of channels) {
          const a = samples[first][channel], b = samples[last][channel], value = samples[index][channel];
          if (![a, b, value].every(finite)) continue;
          const gap = Math.abs(value - (a + (b - a) * amount)) / limit(channel);
          if (gap > ratio) { ratio = gap; worst = index; }
        }
      }
      if (worst < 0) continue;
      keep[worst] = 1;
      stack.push([first, worst], [worst, last]);
    }
    const result = [];
    keep.forEach((value, index) => { if (value) result.push(index); });
    return result;
  }

  global.MVStudioCameraMath = Object.freeze({
    CHANNELS, POSITION, ROTATION, INTERPOLATIONS, HANDLES, TOLERANCE,
    unityToThreePosition, threeToUnityPosition, unityToThreeQuaternion, threeToUnityQuaternion,
    multiply, conjugate, normalize, dot, slerp, rotateVector,
    eulerZXYToQuaternion, quaternionToEulerZXY,
    aspectCorrection, nativeLens, sampleFrames, sampleIndex,
    sortedKeys, handles, curve, evaluate, simplify,
  });
})(typeof window !== "undefined" ? window : globalThis);
