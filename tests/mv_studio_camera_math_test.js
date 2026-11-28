/* MV Studio camera math (mv-studio-camera-math.js): the three.js mapping is
   poseCamera's inverse, Unity ZXY Euler round trips and unwraps like
   core/model_animation, pan/tilt turn the view the way the editor labels say,
   sampleFrames interpolates exactly as poseCamera (three's lerp/slerp), the
   Blender-style curves (linear handles reproduce linear, auto-clamped never
   overshoots, constant holds, monotonic time solve), and simplify keeps its
   tolerances.

   The Euler constants below were generated once from core/model_animation with:
     python3 -c "from webtools.core import model_animation as a; import json
     cases=[[10.,20.,30.],[-35.,170.,-120.],[89.,45.,10.],[90.,30.,0.],[60.,-150.,175.]]
     refs=[[12.,15.,25.],[-30.,-185.,240.],[85.,50.,15.],[89.,40.,-5.],[60.,200.,-180.]]
     for e,r in zip(cases,refs):
       q=a.unity_euler_quaternion(e,4)
       print(json.dumps({'euler':e,'q':[float('%.15g'%v) for v in q],'ref':r,
                         'near':[float('%.12g'%v) for v in a.unity_euler_near(q,4,r)]}))"
   (euler / ref / near are Unity [x, y, z] = [tilt, pan, roll] degrees, order 4 = ZXY).

   The simplify check runs on a synthetic 120-sample camera move (no game data in
   Git). Set MV_STUDIO_CAMERA_SAMPLES to a JSON array of real dense samples
   ({time, position, rotation, fov}, e.g. 12035 shot 0) to also check those. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const T = require('../webtools/web/static/vendor/three-r128/three.min.js');
globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-split.js');
require('../webtools/web/static/mv-studio-camera-math.js');
const M = globalThis.MVStudioCameraMath;

const near = (actual, expected, tolerance, message) => assert(Math.abs(actual - expected) <= tolerance,
  `${message}: ${actual} != ${expected} (±${tolerance})`);
// Rotation angle between two quaternions in degrees (atan2 form: exact near zero).
const angle = (a, b) => {
  const d = M.multiply(M.normalize(a), M.conjugate(M.normalize(b)));
  return 2 * Math.atan2(Math.hypot(d[0], d[1], d[2]), Math.abs(d[3])) * 180 / Math.PI;
};

// Deterministic generator (mulberry32).
function random(seed) {
  return () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let value = Math.imul(seed ^ seed >>> 15, 1 | seed);
    value = value + Math.imul(value ^ value >>> 7, 61 | value) ^ value;
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

const MODEL_ANIMATION = [
  { euler: [10.0, 20.0, 30.0], q: [0.127679440695781, 0.144878125417369, 0.23929833774473, 0.951548524643789], ref: [12.0, 15.0, 25.0], near: [10.0, 20.0, 30.0] },
  { euler: [-35.0, 170.0, -120.0], q: [-0.835904263137382, 0.45234688561385, 0.0777950765858491, 0.300988843652389], ref: [-30.0, -185.0, 240.0], near: [-35.0, -190.0, 240.0] },
  { euler: [89.0, 45.0, 10.0], q: [0.66888066256316, 0.215472276126547, -0.209773751134382, 0.679827427223206], ref: [85.0, 50.0, 15.0], near: [89.0, 45.0, 10.0] },
  { euler: [90.0, 30.0, 0.0], q: [0.683012701892219, 0.183012701892219, -0.183012701892219, 0.683012701892219], ref: [89.0, 40.0, -5.0], near: [90.0, 30.0, 0.0] },
  { euler: [60.0, -150.0, 175.0], q: [-0.83007536148056, -0.165774682050753, 0.244997079137395, -0.472726221261351], ref: [60.0, 200.0, -180.0], near: [60.0, 210.0, -185.0] },
];

function mapping() {
  const next = random(3), camera = new T.PerspectiveCamera();
  for (let count = 0; count < 200; count++) {
    const position = [next() * 40 - 20, next() * 10, next() * 60 - 30];
    const rotation = M.normalize([next() - .5, next() - .5, next() - .5, next() - .5]);
    // poseCamera: camera.position.set(-x, y, z); camera.quaternion.set(x, -y, -z, w).
    camera.position.set(-position[0], position[1], position[2]);
    camera.quaternion.set(rotation[0], -rotation[1], -rotation[2], rotation[3]);
    assert.deepEqual(M.unityToThreePosition(position), camera.position.toArray());
    assert.deepEqual(M.unityToThreeQuaternion(rotation), camera.quaternion.toArray());
    assert.deepEqual(M.threeToUnityPosition(camera.position.toArray()), position, 'position round trip');
    assert.deepEqual(M.threeToUnityQuaternion(camera.quaternion.toArray()), rotation, 'quaternion round trip');
  }
}

function euler() {
  for (const item of MODEL_ANIMATION) {
    const [tilt, pan, roll] = item.euler;
    const q = M.eulerZXYToQuaternion({ pan, tilt, roll });
    q.forEach((value, index) => near(value, item.q[index], 2e-15, `unity_euler_quaternion ${item.euler}`));
    const [refTilt, refPan, refRoll] = item.ref;
    const found = M.quaternionToEulerZXY(item.q, { pan: refPan, tilt: refTilt, roll: refRoll });
    near(found.tilt, item.near[0], 1e-9, `unity_euler_near tilt ${item.euler}`);
    near(found.pan, item.near[1], 1e-9, `unity_euler_near pan ${item.euler}`);
    near(found.roll, item.near[2], 1e-9, `unity_euler_near roll ${item.euler}`);
  }
  // Round trip with unwrap: a slow turn through ±180 stays continuous.
  let previous = { pan: 170, tilt: 5, roll: -3 };
  for (let pan = 170; pan <= 560; pan += 7) {
    const q = M.eulerZXYToQuaternion({ pan, tilt: 5 + pan / 100, roll: -3 });
    const found = M.quaternionToEulerZXY(q, previous);
    near(found.pan, pan, 1e-9, 'unwrapped pan');
    near(found.tilt, 5 + pan / 100, 1e-9, 'tilt');
    near(found.roll, -3, 1e-9, 'roll');
    previous = found;
  }
  // Random round trips: the found angles give the same rotation.
  const next = random(9);
  for (let count = 0; count < 300; count++) {
    const value = { pan: next() * 720 - 360, tilt: next() * 178 - 89, roll: next() * 720 - 360 };
    const q = M.eulerZXYToQuaternion(value);
    const found = M.quaternionToEulerZXY(q, value);
    for (const key of ['pan', 'tilt', 'roll']) near(found[key], value[key], 1e-8, 'near the reference itself');
    assert(angle(M.eulerZXYToQuaternion(M.quaternionToEulerZXY(q)), q) < 1e-6, 'principal angles give the same rotation');
  }
}

// The editor's labels: pan + turns the view right, tilt + looks up (rig looks along -Z).
function directions() {
  const camera = new T.PerspectiveCamera();
  const view = (euler) => {
    camera.quaternion.fromArray(M.unityToThreeQuaternion(M.eulerZXYToQuaternion(euler)));
    return { forward: new T.Vector3(0, 0, -1).applyQuaternion(camera.quaternion), right: new T.Vector3(1, 0, 0).applyQuaternion(camera.quaternion),
      up: new T.Vector3(0, 1, 0).applyQuaternion(camera.quaternion) };
  };
  const base = view({});
  assert(base.forward.distanceTo(new T.Vector3(0, 0, -1)) < 1e-12);
  const panned = view({ pan: 20 });
  assert(panned.forward.dot(base.right) > .3, 'pan + turns the view right');
  assert(Math.abs(panned.forward.y) < 1e-12, 'pan keeps the horizon');
  const tilted = view({ tilt: 20 });
  assert(tilted.forward.y > .3, 'tilt + looks up');
  const rolled = view({ roll: 20 });
  assert(rolled.forward.distanceTo(base.forward) < 1e-12, 'roll keeps the view direction');
  assert(Math.abs(rolled.up.x) > .3, 'roll turns the up vector');
  // Unity: rotating the rig's -Z by its quaternion (rotateVector) agrees with three's view.
  const q = M.eulerZXYToQuaternion({ pan: 33, tilt: -12, roll: 50 });
  const forward = M.rotateVector(q, [0, 0, -1]);
  const three = view({ pan: 33, tilt: -12, roll: 50 }).forward;
  near(forward[0], -three.x, 1e-12, 'Unity forward x mirrors three');
  near(forward[1], three.y, 1e-12, 'forward y');
  near(forward[2], three.z, 1e-12, 'forward z');
}

// sampleFrames is poseCamera's interpolation: three's Vector3.lerp and Quaternion.slerp.
function sampling() {
  const next = random(21);
  const frames = [];
  let q = M.normalize([.1, .9, .05, .4]);
  for (let index = 0; index < 61; index++) {
    q = M.normalize(M.multiply(q, M.eulerZXYToQuaternion({ pan: next() * 4 - 2, tilt: next() * 2 - 1, roll: next() - .5 })));
    // Some samples are stored in the other hemisphere: slerp takes the short way.
    const stored = index % 7 === 3 ? q.map((value) => -value) : q;
    frames.push({ time: index / 60, position: [next() * 3, 1 + next(), 20 + next()], rotation: stored, fov: 25 + next() * 10 });
  }
  const a = new T.Quaternion(), b = new T.Quaternion(), position = new T.Vector3(), other = new T.Vector3();
  for (let count = 0; count < 400; count++) {
    const local = next() * 1.1 - .05;
    const pose = M.sampleFrames(frames, local);
    const clamped = Math.min(1, Math.max(0, local));
    let left = 0;
    while (left + 1 < frames.length && frames[left + 1].time <= clamped) left++;
    const right = Math.min(left + 1, frames.length - 1);
    const fraction = left !== right ? Math.max(0, Math.min(1, (local - frames[left].time) / (frames[right].time - frames[left].time))) : 0;
    position.fromArray(frames[left].position).lerp(other.fromArray(frames[right].position), fraction);
    a.fromArray(frames[left].rotation).normalize().slerp(b.fromArray(frames[right].rotation).normalize(), fraction);
    assert.deepEqual(pose.position, position.toArray(), 'Vector3.lerp');
    assert.deepEqual(pose.rotation, a.toArray(), 'Quaternion.slerp, bit for bit');
    const fov = Math.min(170, Math.max(1, frames[left].fov + (frames[right].fov - frames[left].fov) * fraction));
    assert.equal(pose.fov, fov);
  }
  assert.equal(M.sampleFrames([], 0, { position: [0, 1, 2], rotation: [0, 0, 0, 1], fov: 40 }).fov, 40, 'static shot');
  assert.equal(M.sampleFrames([{ time: 0, position: [0, 0, 0] }], 0), null, 'no rotation: no pose');
}

const key = (frame, values, interp = 'bezier', handle = 'auto-clamped', extra = {}) => ({ frame, values, interp, handle, ...extra });

function curves() {
  // Constant holds until the next key; outside the keys the curve holds (constant extrapolation).
  const constant = [key(10, { x: 1 }, 'constant'), key(20, { x: 3 }, 'constant')];
  near(M.curve(constant, 'x', 0), 1, 0, 'before the first key');
  near(M.curve(constant, 'x', 19.999), 1, 0, 'constant holds');
  near(M.curve(constant, 'x', 20), 3, 0, 'at the next key');
  near(M.curve(constant, 'x', 90), 3, 0, 'after the last key');
  // Linear.
  const linear = [key(0, { x: 0 }, 'linear'), key(30, { x: 6 }, 'linear')];
  near(M.curve(linear, 'x', 15), 3, 1e-12, 'linear halfway');
  // Free handles on the straight line reproduce it exactly (Bernstein linear precision).
  const line = [key(0, { x: 2 }, 'bezier', 'free', { handles: { x: { in: [-5, -1], out: [5, 1] } } }),
    key(15, { x: 5 }, 'bezier', 'free', { handles: { x: { in: [-5, -1], out: [5, 1] } } })];
  for (let f = 0; f <= 15; f += .25) near(M.curve(line, 'x', f), 2 + f / 5, 1e-9, `free linear handles at ${f}`);
  // Two auto-clamped keys: flat ends, an S between them, inside the key range.
  const pair = [key(0, { x: 0 }), key(60, { x: 1 })];
  near(M.curve(pair, 'x', 30), .5, 1e-9, 'symmetric ease midpoint');
  assert(M.curve(pair, 'x', 6) < .05, 'flat start');
  for (let f = 0; f < 60; f++) assert(M.curve(pair, 'x', f + 1) >= M.curve(pair, 'x', f) - 1e-12, 'monotonic between two keys');
  // Auto-clamped never overshoots: each segment stays in its endpoints' range.
  const next = random(33);
  for (let trial = 0; trial < 200; trial++) {
    const keys = [];
    let frame = 0;
    for (let index = 0; index < 6; index++) {
      keys.push(key(frame, { x: next() * 10 - 5 }));
      frame += 1 + Math.floor(next() * 40);
    }
    for (let index = 0; index + 1 < keys.length; index++) {
      const a = keys[index], b = keys[index + 1];
      const low = Math.min(a.values.x, b.values.x) - 1e-9, high = Math.max(a.values.x, b.values.x) + 1e-9;
      for (let f = a.frame; f <= b.frame; f += .5) {
        const value = M.curve(keys, 'x', f);
        assert(value >= low && value <= high, `auto-clamped overshoot at ${f}: ${value} not in [${low}, ${high}]`);
      }
    }
    // Plain auto may overshoot but stays finite; flat handles are zero slope at the keys.
    const auto = keys.map((item) => ({ ...item, handle: 'auto' }));
    for (let f = 0; f <= frame; f += 3) assert(Number.isFinite(M.curve(auto, 'x', f)));
    const flat = keys.map((item) => ({ ...item, handle: 'flat' }));
    flat.forEach((item, index) => {
      const { in: before, out: after } = M.handles(flat, index, 'x');
      assert(before[1] === 0 && after[1] === 0 && before[0] <= 0 && after[0] >= 0, 'flat handle');
      // One-sided slopes at the key tend to zero.
      if (index + 1 < flat.length) assert(Math.abs(M.curve(flat, 'x', item.frame + 1e-6) - item.values.x) < 1e-6, 'flat out');
    });
  }
  // Extreme free handles: the time solve stays monotonic (handle lengths are clamped).
  const wild = [key(0, { x: 0 }, 'bezier', 'free', { handles: { x: { in: [-50, 0], out: [80, 40] } } }),
    key(20, { x: 1 }, 'bezier', 'free', { handles: { x: { in: [-90, -30], out: [10, 0] } } })];
  let previous = -Infinity;
  for (let f = 0; f <= 20; f += .1) {
    const value = M.curve(wild, 'x', f);
    assert(Number.isFinite(value), 'finite');
    previous = value;
  }
  assert(Number.isFinite(previous));
  // A local extremum is flat with auto-clamped handles.
  const peak = [key(0, { x: 0 }), key(10, { x: 5 }), key(20, { x: 0 })];
  assert.deepEqual(M.handles(peak, 1, 'x').out.map((value) => Math.abs(value)), [10 / 3, 0]);
  near(M.curve(peak, 'x', 10), 5, 0, 'key value');
  assert(M.curve(peak, 'x', 9) < 5 && M.curve(peak, 'x', 11) < 5, 'the peak is the key');
  // evaluate() returns every channel; a missing channel reads 0.
  assert.deepEqual(Object.keys(M.evaluate(pair, 0)), M.CHANNELS.slice());
  assert.equal(M.evaluate(pair, 0).fov, 0);
}

// Synthetic 120-sample move: eased dolly, a pan through 180, a short tilt bump, a FOV pull.
function syntheticSamples() {
  const samples = [];
  for (let index = 0; index < 120; index++) {
    const s = index / 119, ease = s * s * (3 - 2 * s);
    samples.push({ x: 10 - 4 * ease, y: 3.35 + .2 * Math.sin(s * 6), z: 30 - 9 * s, pan: 150 + 70 * ease,
      tilt: -2 + 3 * Math.exp(-((s - .6) ** 2) / .01), roll: .5 * Math.sin(s * 9), fov: 28 + 4 * s * s });
  }
  return samples;
}

function realSamples() {
  const file = process.env.MV_STUDIO_CAMERA_SAMPLES;
  if (!file || !fs.existsSync(file)) return null;
  const frames = JSON.parse(fs.readFileSync(file, 'utf8')).slice(0, 120);
  let previous = null;
  return frames.map((frame) => {
    const euler = M.quaternionToEulerZXY(frame.rotation, previous);
    previous = euler;
    return { x: frame.position[0], y: frame.position[1], z: frame.position[2], ...euler, fov: frame.fov };
  });
}

function simplification(samples, label) {
  const kept = M.simplify(samples);
  assert.equal(kept[0], 0);
  assert.equal(kept.at(-1), samples.length - 1);
  assert(kept.length < samples.length, `${label}: fewer keys (${kept.length})`);
  const keys = kept.map((index) => key(index, { ...samples[index] }, 'linear'));
  let worst = { position: 0, rotation: 0, fov: 0 };
  samples.forEach((sample, index) => {
    const value = M.evaluate(keys, index);
    for (const channel of M.CHANNELS) {
      const group = M.POSITION.includes(channel) ? 'position' : M.ROTATION.includes(channel) ? 'rotation' : 'fov';
      worst[group] = Math.max(worst[group], Math.abs(value[channel] - sample[channel]));
    }
  });
  assert(worst.position <= .002 + 1e-12, `${label}: position within 2 mm (${worst.position})`);
  assert(worst.rotation <= .05 + 1e-12, `${label}: rotation within 0.05 deg (${worst.rotation})`);
  assert(worst.fov <= .01 + 1e-12, `${label}: FOV within 0.01 deg (${worst.fov})`);
  // A straight line needs only its two ends.
  const straight = samples.map((_, index) => ({ x: index * .01, y: 1, z: 2, pan: index * .1, tilt: 0, roll: 0, fov: 30 }));
  assert.deepEqual(M.simplify(straight), [0, samples.length - 1]);
  return { kept: kept.length, worst };
}

mapping();
euler();
directions();
sampling();
curves();
const synthetic = simplification(syntheticSamples(), 'synthetic');
const real = realSamples();
const realResult = real ? simplification(real, 'MV_STUDIO_CAMERA_SAMPLES') : null;
console.log('mv studio camera math tests passed', JSON.stringify({ synthetic, real: realResult }));
