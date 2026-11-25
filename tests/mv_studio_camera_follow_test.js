/* MV Studio follow camera (mv-studio-camera-follow.js) on a stub editor context with the real
   undo history and the real camera keys bake (MVStudioCameraKeys), and the scene's member
   target sampler (MVStudioScene.sampleMemberPath) on a stub three.js renderer:

   - the look rotation is three's Matrix4.lookAt + setFromRotationMatrix, mapped to Unity;
   - a static target seen from the front/back/left/right presets (position and look direction);
     a member-facing reference turns the offsets with the member (and its turn damping);
   - the dead zone holds inside, follows outside, and the hysteresis stops it nearer;
   - a step leaves e^-1 of its error after one time constant (±1 %), XZ and Y independent, for
     the look-at point and for the camera body;
   - height lock off / camera / aim / both, at the rig start or a fixed height;
   - blend weights; a shot half a frame off the rig grid; continuity across two shots;
   - baking twice, in another order, or after a parameter change and its revert gives identical
     samples; undo/redo rebakes identical arrays; the path cache key follows the slot's dance;
   - the no-regression rule: a project without rigs is never written to and gets no editor;
   - cancel, a member that is not loaded, a scene still loading, save and export guards;
   - the scene sampler: positions and facing on a time grid, time-sliced, the playhead's frame
     restored after every slice, cancellable. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-split.js');
require('../webtools/web/static/mv-studio-camera-math.js');
require('../webtools/web/static/mv-studio-edit-history.js');
require('../webtools/web/static/mv-studio-timeline-interact.js');
require('../webtools/web/static/mv-studio-timeline-tabs.js');
require('../webtools/web/static/mv-studio-camera-keys.js');
require('../webtools/web/static/mv-studio-camera-follow.js');
const M = globalThis.MVStudioCameraMath, K = globalThis.MVStudioCameraKeys, H = globalThis.MVStudioEditHistory;
const F = globalThis.MVStudioCameraFollow;
const keysPlugin = K.plugin, plugin = F.plugin;
const copy = (value) => JSON.parse(JSON.stringify(value));
const near = (actual, expected, tolerance, message) => assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} != ${expected}`);
const nearVector = (actual, expected, tolerance, message) => Array.from(expected).forEach((value, index) => near(actual[index], value, tolerance, `${message}[${index}]`));
const angle = (a, b) => {
  const d = M.multiply(M.normalize(a), M.conjugate(M.normalize(b)));
  return 2 * Math.atan2(Math.hypot(d[0], d[1], d[2]), Math.abs(d[3])) * 180 / Math.PI;
};
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

assert(globalThis.MVStudioPlugins.includes(plugin), 'registers as an editor plugin');
assert.equal(plugin.id, 'camera-follow');
assert.equal(F.layer.order, 30, 'the follow camera is the camera keys layer at order 30');

// ---- helpers --------------------------------------------------------------------------------------
function samples(count, phase = 0) {
  return Array.from({ length: count }, (_, index) => {
    const s = index / (count - 1);
    return { time: index / 60, position: [10 - 2 * s, 3.35, 30 - 4 * s],
      rotation: M.normalize(M.eulerZXYToQuaternion({ pan: 160 + 30 * s + phase, tilt: -3, roll: 0 })), fov: 28 + 2 * s };
  });
}

function nativeProject() {
  const shot = (id, start, count, phase) => ({ id, start, duration: (count - 1) / 60, label: `${Math.round(start * 60)}_${Math.round(start * 60) + count - 1}`,
    values: { clipIn: 0, timeScale: 1, preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: 1 / 60,
      playableClass: 'AnimationPlayableAsset', keyframes: samples(count, phase) },
    editableValues: ['clipIn', 'timeScale', 'preExtrapolationMode', 'postExtrapolationMode', 'preExtrapolationTime', 'postExtrapolationTime', 'keyframes'] });
  return {
    version: 1, name: 'Follow MV', duration: 12, nativeTimeline: true, source: { kind: 'game' },
    performers: [{ id: 'p1', position: 1, glb: '/api/mv-studio/media/a.glb', transform: { position: [0, 0, 0] } },
      { id: 'p2', position: 2, glb: '/api/mv-studio/media/b.glb', transform: { position: [1, 0, 0] } }],
    tracks: [
      { id: 'cam', kind: 'camera', label: 'CameraMotion/Camera1', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera',
        events: [shot('cam:0', 0, 121, 0), shot('cam:1', 121 / 60, 181, 40), shot('cam:2', 302 / 60, 61, 80)] },
      { id: 'dance1', kind: 'dance', label: 'Members/Member1', nativeClass: 'LiveMemberMotionTrack', binding: '/EntryPoint/Live/Members/Member1',
        events: [{ id: 'dance1:0', start: 0, duration: 12, values: { playableClass: 'LiveMemberMotionClip' } }] },
      { id: 'dance2', kind: 'dance', label: 'Members/Member2', nativeClass: 'LiveMemberMotionTrack', binding: '/EntryPoint/Live/Members/Member2',
        events: [{ id: 'dance2:0', start: 0, duration: 12, values: { playableClass: 'LiveMemberMotionClip' } }] },
      { id: 'light', kind: 'lighting', label: 'BaseLight', nativeClass: 'LiveBaseLightTrack', events: [{ id: 'light:0', start: 0, duration: 3, values: { color: 1 } }] },
    ],
  };
}

// A scene stub: memberTargets and sampleMemberPath from an analytic path (Unity metres, yaw deg).
function fakeScene(path, { slots = [1, 2], parts = [0, 1, 3], facing = true, gate = null } = {}) {
  const calls = [];
  return {
    calls,
    memberTargets: () => slots.map((slot) => ({ slot, id: 'p' + slot, parts: parts.slice(), facing })),
    async sampleMemberPath({ slot, part, times, signal, onProgress }) {
      calls.push({ slot, part, times: Array.from(times) });
      if (gate) await gate(signal);
      if (signal && signal.aborted) throw new DOMException('cancelled', 'AbortError');
      const positions = new Float64Array(3 * times.length), yaw = facing ? new Float64Array(times.length) : null;
      times.forEach((time, index) => {
        const value = path(time, slot, part);
        positions.set(value.position, 3 * index);
        if (yaw) yaw[index] = value.yaw || 0;
      });
      if (onProgress) onProgress(times.length, times.length);
      return { positions, yaw };
    },
    onViewChange: () => () => {}, setGameCameraHelper() {},
  };
}

const dancing = (time, slot) => ({ position: [Math.sin(time) * .8 + (slot - 1), 1.5 + .2 * Math.sin(time * 3), Math.cos(time * .7) * .5], yaw: 20 * Math.sin(time) });

function harness(project, { scene = fakeScene(dancing), tab = 'camera' } = {}) {
  let time = 0, history, locked = false;
  const log = { seeks: [], refreshed: [], reports: [] };
  const ctx = {
    project: () => project, time: () => time, duration: () => project.duration, playing: () => false, pause() {},
    seek(seconds) { time = seconds; log.seeks.push(seconds); }, selection: () => null, select() {},
    editor(create = false) {
      if (create && !project.editor) project.editor = { version: 1, originals: {} };
      return project.editor || null;
    },
    edited: (id) => history.editedEvents().has(id), extrapolationAuto: () => false, scene: () => scene,
    t: (label) => label, format: (label, values) => label.replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match),
    make() { throw new Error('no DOM in this test'); },
    renderTimeline() { history.invalidate(); }, refreshLane(id) { history.invalidate(); log.refreshed.push(id); },
    renderPanel() {}, renderEvent() {}, report(message, error) { log.reports.push([message, !!error]); }, locked: () => locked,
    frameRate: 60, snap: (seconds) => Math.round(seconds * 60) / 60, activeTab: () => tab, snapTargets: () => [time],
  };
  history = H.create({ getProject: () => project, limit: 200,
    onChange: ({ command, direction }) => {
      keysPlugin.projectChanged(ctx, { reason: 'history', command, direction });
      plugin.projectChanged(ctx, { reason: 'history', command, direction });
    } });
  ctx.history = history;
  keysPlugin.attach(ctx);
  plugin.attach(ctx);
  keysPlugin.projectChanged(ctx, { reason: 'load' });
  plugin.projectChanged(ctx, { reason: 'load' });
  return { ctx, history, log, at(seconds) { time = seconds; }, lock(value) { locked = value; } };
}

const event = (project, id) => project.tracks.flatMap((track) => track.events).find((item) => item.id === id);
const original = (id) => nativeProject().tracks[0].events.find((item) => item.id === id).values.keyframes;
const settle = (ctx) => K.pending(ctx);
const rigOf = (fields) => F.normalizeRig({ id: 'rig-test', start: 0, end: 2, target: { slot: 1, part: 0 }, ...fields });
const constantPath = (count, point, yaw = null) => {
  const positions = new Float64Array(3 * count);
  for (let n = 0; n < count; n++) positions.set(point, 3 * n);
  return { count, positions, yaw: yaw === null ? null : new Float64Array(count).fill(yaw) };
};
const pathOf = (count, fn) => {
  const positions = new Float64Array(3 * count), yaw = new Float64Array(count);
  for (let n = 0; n < count; n++) { const value = fn(n); positions.set(value.position, 3 * n); yaw[n] = value.yaw || 0; }
  return { count, positions, yaw };
};
const at = (result, n, size = 3, key = 'positions') => Array.from(result[key].subarray(size * n, size * n + size));
const forwardOf = (rotation) => M.rotateVector(rotation, [0, 0, -1]);

// ---- tests ------------------------------------------------------------------------------------------
function lookRotationMatchesThree() {
  const random = (() => { let seed = 7; return () => (seed = (seed * 16807) % 2147483647) / 2147483647; })();
  for (let index = 0; index < 200; index++) {
    const eye = [random() * 20 - 10, random() * 6 - 1, random() * 20 - 10];
    const target = [random() * 4 - 2, random() * 2 + .5, random() * 4 - 2];
    const roll = index % 3 ? random() * 90 - 45 : 0;
    const matrix = new THREE.Matrix4().lookAt(new THREE.Vector3(-eye[0], eye[1], eye[2]), new THREE.Vector3(-target[0], target[1], target[2]),
      new THREE.Vector3(0, 1, 0));
    const three = new THREE.Quaternion().setFromRotationMatrix(matrix);
    let expected = M.normalize(M.multiply([three.x, -three.y, -three.z, three.w], M.eulerZXYToQuaternion({ roll })));
    const actual = F.lookRotation(eye, target, roll);
    if (M.dot(actual, expected) < 0) expected = expected.map((value) => -value);
    nearVector(actual, expected, 1e-12, `lookRotation ${index}`);
    const look = forwardOf(actual), toward = target.map((value, axis) => value - eye[axis]);
    const length = Math.hypot(...toward);
    nearVector(look, toward.map((value) => value / length), 1e-9, `rig -Z looks at the target ${index}`);
  }
}

function staticViews() {
  const point = [.4, 1.5, -.3];
  const cases = { front: [0, 0, 2.5], back: [0, 0, -2.5], right: [2.5, 0, 0], left: [-2.5, 0, 0] };
  for (const [view, offset] of Object.entries(cases)) {
    const rig = rigOf({ view });
    const { count } = F.frameRange(rig);
    const result = F.evaluateRig(rig, constantPath(count, point));
    for (const n of [0, 60, count - 1]) {
      nearVector(at(result, n), point.map((value, axis) => value + offset[axis]), 1e-12, `${view} camera position`);
      nearVector(forwardOf(at(result, n, 4, 'rotations')), offset.map((value) => -value / 2.5), 1e-12, `${view} looks at the target`);
    }
  }
  // Front is on the audience side (+Z) and its rotation is the identity (the rig looks along -Z).
  const front = F.evaluateRig(rigOf({}), constantPath(121, point));
  assert(angle(at(front, 0, 4, 'rotations'), [0, 0, 0, 1]) < 1e-9);
  // Custom yaw is added to the preset; height, side and look-at offsets; FOV and roll.
  const custom = F.evaluateRig(rigOf({ view: 'custom', yaw: 90, height: .5, lateral: .2, aim: { height: -.3, side: .1, forward: .2 }, fov: 40, roll: 10 }),
    constantPath(121, point));
  const aim = [point[0] + .1, point[1] - .3, point[2] + .2];
  nearVector(at(custom, 5, 3, 'aims'), aim, 1e-12, 'look-at offset in the stage frame');
  nearVector(at(custom, 5), [aim[0] + 2.5, aim[1] + .5, aim[2] - .2], 1e-12, 'custom 90° = right; lateral turns with the view');
  assert.equal(custom.fov, 40);
  const level = F.lookRotation(at(custom, 5), aim, 0), rolled = at(custom, 5, 4, 'rotations');
  near(angle(level, rolled), 10, 1e-9, 'roll about the view axis');
  nearVector(forwardOf(rolled), forwardOf(level), 1e-12, 'roll keeps the look direction');
}

function memberFrame() {
  const point = [0, 1.5, 0];
  // A member facing +X (yaw 90): the front view is on the member's front side.
  const rig = rigOf({ frame: 'member', turnDamping: 0, aim: { height: 0, side: .3, forward: .1 } });
  const result = F.evaluateRig(rig, constantPath(F.frameRange(rig).count, point, 90));
  const aim = [point[0] + .1, point[1], point[2] - .3];   // (side, forward) turned by 90°: side -> -Z, forward -> +X
  nearVector(at(result, 10, 3, 'aims'), aim, 1e-12, 'the look-at offset turns with the member');
  nearVector(at(result, 10), [aim[0] + 2.5, aim[1], aim[2]], 1e-12, 'the camera offset turns with the member');
  // Without facing data the stage front is used.
  const fallback = F.evaluateRig(rig, constantPath(F.frameRange(rig).count, point, null));
  nearVector(at(fallback, 10), [.3, 1.5, 2.5 + .1], 1e-12, 'member frame without facing = stage front');
  // Turn damping: the reference follows a 0 -> 90 turn with its time constant; turns unwrap (170 -> -170 is +20).
  const turning = F.normalizeRig({ ...rig, aim: { height: 0, side: 0, forward: 0 }, turnDamping: .5, damping: { aimXZ: 0, aimY: 0, bodyXZ: 0, bodyY: 0 } });
  const count = F.frameRange(turning).count;
  const turn = F.evaluateRig(turning, pathOf(count, (n) => ({ position: point, yaw: n ? 90 : 0 })));
  const yawAt = (n) => { const p = at(turn, n); return Math.atan2(p[0], p[2]) * 180 / Math.PI; };
  near(yawAt(30), 90 * (1 - Math.exp(-1)), .9, 'turn damping: 63 % after one time constant');
  const wrapped = F.evaluateRig(turning, pathOf(count, (n) => ({ position: point, yaw: n ? -170 : 170 })));
  const late = at(wrapped, count - 1);
  near(((Math.atan2(late[0], late[2]) * 180 / Math.PI) + 360) % 360, 190, .5, 'the facing unwraps across ±180');
}

function deadZone() {
  const rig = rigOf({ deadZone: { radius: .1, height: .1, hysteresis: .5 }, damping: { aimXZ: .5, aimY: .5, bodyXZ: 0, bodyY: 0 } });
  const count = F.frameRange(rig).count;
  // Inside the dead zone (XZ < 0.1, Y < 0.1): the look-at point does not move.
  const inside = F.evaluateRig(rig, pathOf(count, (n) => ({ position: [.09 * Math.sin(n / 7), 1.5 + .045 * Math.cos(n / 5), .05] })));
  for (let n = 0; n < count; n++) nearVector(at(inside, n, 3, 'aims'), [0, 1.545, .05], 0, `held inside the dead zone ${n}`);
  // Outside: it follows; with hysteresis 0.5 it keeps following until 0.05 m, without it it stops at 0.1 m.
  const step = (n) => ({ position: n ? [1, 1.5, 0] : [0, 1.5, 0] });
  const residual = (hysteresis) => {
    const result = F.evaluateRig(F.normalizeRig({ ...rig, deadZone: { radius: .1, height: .1, hysteresis } }), pathOf(count, step));
    assert(at(result, 1, 3, 'aims')[0] > 0, 'moves once outside');
    return 1 - at(result, count - 1, 3, 'aims')[0];
  };
  const alpha = F.alpha(.5);
  const loose = residual(0), tight = residual(.5);
  assert(loose <= .1 && loose > .1 * (1 - alpha), `without hysteresis it stops inside the radius (${loose})`);
  assert(tight <= .05 && tight > .05 * (1 - alpha), `with hysteresis it stops inside radius × 0.5 (${tight})`);
  // The Y band is separate: 0.09 m up holds, 0.3 m up follows.
  const band = (dy) => at(F.evaluateRig(rig, pathOf(count, (n) => ({ position: [0, 1.5 + (n ? dy : 0), 0] }))), count - 1, 3, 'aims')[1];
  near(band(.09), 1.5, 0, 'inside the height band');
  assert(band(.3) > 1.7, 'outside the height band');
}

function stepResponse() {
  // A step of 1 m in X and Y; no dead zone. After tau seconds e^-1 of the error is left (±1 %).
  const rig = rigOf({ end: 3, deadZone: { radius: 0, height: 0, hysteresis: 0 }, damping: { aimXZ: .25, aimY: .5, bodyXZ: 0, bodyY: 0 } });
  const count = F.frameRange(rig).count;
  const path = pathOf(count, (n) => ({ position: n ? [1, 2.5, 0] : [0, 1.5, 0] }));
  const aims = F.evaluateRig(rig, path);
  const error = (n, axis, goal) => Math.abs(goal - at(aims, n, 3, 'aims')[axis]);
  near(error(15, 0, 1) / 1, Math.exp(-1), .01 * Math.exp(-1), 'look-at XZ after 0.25 s');
  near(error(30, 1, 2.5) / 1, Math.exp(-1), .01 * Math.exp(-1), 'look-at Y after 0.5 s');
  // Independent: an X step leaves Y alone, a Y step leaves X alone.
  const xOnly = F.evaluateRig(rig, pathOf(count, (n) => ({ position: n ? [1, 1.5, 0] : [0, 1.5, 0] })));
  for (let n = 0; n < count; n++) assert.equal(at(xOnly, n, 3, 'aims')[1], 1.5, 'Y untouched by an XZ step');
  near(1 - at(xOnly, 15, 3, 'aims')[0], Math.exp(-1), .01 * Math.exp(-1), 'XZ alone');
  // Camera body: look-at instant, body XZ 0.4 s and Y 0.2 s.
  const body = F.normalizeRig({ ...rig, damping: { aimXZ: 0, aimY: 0, bodyXZ: .4, bodyY: .2 } });
  const moved = F.evaluateRig(body, path);
  const start = at(moved, 0), goal = [1, 2.5, 2.5];
  near(Math.abs(goal[0] - at(moved, 24)[0]) / Math.abs(goal[0] - start[0]), Math.exp(-1), .01 * Math.exp(-1), 'camera XZ after 0.4 s');
  near(Math.abs(goal[1] - at(moved, 12)[1]) / Math.abs(goal[1] - start[1]), Math.exp(-1), .01 * Math.exp(-1), 'camera Y after 0.2 s');
  // Zero damping follows at once.
  const instant = F.evaluateRig(F.normalizeRig({ ...rig, damping: { aimXZ: 0, aimY: 0, bodyXZ: 0, bodyY: 0 } }), path);
  nearVector(at(instant, 1), goal, 1e-12, 'no damping');
}

function heightLock() {
  const base = { deadZone: { radius: 0, height: 0, hysteresis: 0 }, damping: { aimXZ: 0, aimY: 0, bodyXZ: 0, bodyY: 0 }, height: .4 };
  const count = F.frameRange(rigOf(base)).count;
  const jump = pathOf(count, (n) => ({ position: [n / 100, 1.5 + .5 * Math.sin(n / 10) ** 2, 0] }));
  const run = (mode, value = 'start') => F.evaluateRig(rigOf({ ...base, heightLock: { mode, value } }), jump);
  const ys = (result, key) => Array.from({ length: count }, (_, n) => at(result, n, 3, key)[1]);
  const off = run('off');
  assert(new Set(ys(off, 'aims')).size > 10 && new Set(ys(off, 'positions')).size > 10, 'off: both follow the jumps');
  const aim = run('aim');
  assert(ys(aim, 'aims').every((value) => value === 1.5), 'aim lock holds the look-at height at the rig start');
  assert(new Set(ys(aim, 'positions')).size === 1, 'the camera then keeps the same height too (height above the held point)');
  const camera = run('camera');
  assert(ys(camera, 'positions').every((value) => value === 1.9), 'camera lock: the camera at its start height');
  assert(new Set(ys(camera, 'aims')).size > 10, 'the camera still tilts to the look-at point');
  const both = run('both', 1.2);
  assert(ys(both, 'aims').every((value) => value === 1.2) && ys(both, 'positions').every((value) => value === 1.2), 'both at a fixed height');
  // XZ still follows under every lock.
  for (const result of [aim, camera, both]) near(at(result, count - 1)[0], (count - 1) / 100, 1e-12, 'XZ follows');
}

function weights() {
  const rig = rigOf({ start: 1, end: 3, blendIn: .5, blendOut: .4 });
  assert.equal(F.weight(rig, .99), 0, 'before the rig');
  assert.equal(F.weight(rig, 1), 0, 'at the start');
  near(F.weight(rig, 1.25), .5, 1e-12, 'halfway through the blend in (smoothstep)');
  assert.equal(F.weight(rig, 1.5), 1, 'after the blend in');
  assert.equal(F.weight(rig, 2), 1, 'midpoint');
  near(F.weight(rig, 2.8), .5, 1e-12, 'halfway through the blend out');
  assert.equal(F.weight(rig, 3), 0, 'at the end');
  const cut = rigOf({ start: 1, end: 3, blendIn: 0, blendOut: 0 });
  assert.equal(F.weight(cut, 1), 1, 'a zero blend is a cut');
  assert.equal(F.weight(cut, 3), 1);
  const short = rigOf({ start: 1, end: 1.5, blendIn: 2, blendOut: 2 });
  assert.equal(F.weight(short, 1.25), 1, 'blends are at most half the rig');
}

// The pipeline through MVStudioCameraKeys: a rig over cam:1 bakes the rig pose into every sample.
async function bake() {
  const project = nativeProject();
  const scene = fakeScene(dancing);
  const { ctx, history, at: seek } = harness(project, { scene });
  const shot1 = event(project, 'cam:1');
  seek(shot1.start + .5);
  const rig = F.addRig(ctx, { blendIn: 0, blendOut: 0 });
  assert(rig, 'Add follow camera');
  assert.equal(rig.start, shot1.start, 'covers the shot at the playhead');
  near(rig.end, shot1.start + shot1.duration, 1e-12, 'to its end');
  assert.deepEqual(rig.target, { slot: 1, part: 0 }, 'the lowest member, head');
  assert.equal(history.peekUndo().label, 'Add follow camera');
  assert.equal(plugin.editedCount(ctx), 1);
  await settle(ctx);
  const stored = project.editor.camera.rigs;
  assert.equal(stored.length, 1);
  assert.equal(project.editor.camera.shots, undefined, 'the follow camera never writes editor.camera.shots');
  const before = original('cam:1');
  assert.equal(shot1.values.keyframes.length, before.length, 'same sample count');
  const { first, count } = F.frameRange(F.normalizeRig(stored[0]));
  const times = Array.from({ length: count }, (_, n) => (first + n) / 60);
  const path = { count, positions: new Float64Array(3 * count), yaw: new Float64Array(count) };
  times.forEach((time, n) => { const value = dancing(time, 1); path.positions.set(value.position, 3 * n); path.yaw[n] = value.yaw; });
  const expected = F.evaluateRig(F.normalizeRig(stored[0]), path);
  shot1.values.keyframes.forEach((sample, index) => {
    assert.equal(sample.time, before[index].time, 'identical time floats');
    assert.deepEqual(Object.keys(sample), ['time', 'position', 'rotation', 'fov'], 'the exporter key set');
    nearVector(sample.position, at(expected, index), 1e-12, `sample ${index} = the rig pose`);
    assert(angle(sample.rotation, at(expected, index, 4, 'rotations')) < 1e-6, `sample ${index} rotation`);
    assert.equal(sample.fov, 30);
  });
  assert.deepEqual(event(project, 'cam:0').values.keyframes, original('cam:0'), 'shots outside the rig keep their samples');
  assert.deepEqual(event(project, 'cam:2').values.keyframes, original('cam:2'));
  assert.deepEqual(project.editor.originals['cam:1'].values.keyframes, before, 'originals captured before the first bake');
  // Bake twice: identical; the path is sampled once (cache).
  const first1 = copy(shot1.values.keyframes);
  const sampled = scene.calls.length;
  await F.requestBake(ctx);
  assert.deepEqual(shot1.values.keyframes, first1, 'baking again gives identical samples');
  assert.equal(scene.calls.length, sampled, 'the member path is cached');
  // A parameter change and its revert give the first samples again, bit for bit.
  F.setField(ctx, rig.id, 'distance', 3.4);
  await settle(ctx);
  assert.notDeepEqual(shot1.values.keyframes, first1);
  F.setField(ctx, rig.id, 'distance', 2.5);
  await settle(ctx);
  assert.deepEqual(shot1.values.keyframes, first1, 'change + revert = the same bake');
  // Undo / redo rebake identical arrays.
  history.undo(); await settle(ctx);
  const changed = copy(shot1.values.keyframes);
  history.undo(); await settle(ctx);
  assert.deepEqual(shot1.values.keyframes, first1);
  history.redo(); await settle(ctx);
  assert.deepEqual(shot1.values.keyframes, changed);
  history.redo(); await settle(ctx);
  assert.deepEqual(shot1.values.keyframes, first1);
  // Undo the rig itself: the shot is its original again.
  while (history.canUndo()) history.undo();
  await settle(ctx);
  assert.deepEqual(shot1.values.keyframes, before, 'no rig: the original samples');
  assert.equal(project.editor.camera?.rigs, undefined);
  assert.equal(plugin.editedCount(ctx), 0);
}

// Order independence: a scoped bake first, then all, equals one bake of all; two rigs keep array order.
async function orderIndependence() {
  const run = async (scoped) => {
    const project = nativeProject();
    const { ctx, at: seek } = harness(project);
    seek(.5);
    const a = F.addRig(ctx, { blendIn: .3, blendOut: .3 });
    F.setRange(ctx, a.id, .5, 6);
    await settle(ctx);
    if (scoped) { await K.requestBake(ctx, { events: ['cam:2'] }); await K.requestBake(ctx, { events: ['cam:0', 'cam:1'] }); }
    await K.requestBake(ctx, {});
    return project.tracks[0].events.map((item) => item.values.keyframes);
  };
  assert.deepEqual(await run(true), await run(false), 'independent of the bake order and scope');
}

// A shot half a frame off the rig grid samples between two grid poses.
async function halfFrame() {
  const project = nativeProject();
  const shot = event(project, 'cam:1');
  shot.start = 2 + .5 / 60;
  const { ctx, at: seek } = harness(project);
  seek(.5);
  const rig = F.addRig(ctx, { blendIn: 0, blendOut: 0 });
  F.setRange(ctx, rig.id, 0, 8);
  await settle(ctx);
  const stored = F.normalizeRig(project.editor.camera.rigs[0]);
  const { first, count } = F.frameRange(stored);
  const path = { count, positions: new Float64Array(3 * count), yaw: new Float64Array(count) };
  for (let n = 0; n < count; n++) { const value = dancing((first + n) / 60, 1); path.positions.set(value.position, 3 * n); path.yaw[n] = value.yaw; }
  const result = F.evaluateRig(stored, path);
  for (const index of [0, 1, 37, 180]) {
    const sample = shot.values.keyframes[index], u = 120 + index;   // shot start = grid 120.5
    const a = at(result, u), b = at(result, u + 1);
    nearVector(sample.position, a.map((value, axis) => value + (b[axis] - value) * .5), 1e-9, `half-frame sample ${index}: lerp`);
    const q = M.slerp(at(result, u, 4, 'rotations'), at(result, u + 1, 4, 'rotations'), .5);
    assert(angle(sample.rotation, q) < 1e-6, `half-frame sample ${index}: slerp`);
  }
}

// One continuous follow across a native cut: the two shots meet at the same pose.
async function continuity() {
  const project = nativeProject();
  // Two shots that meet at a cut (cam:1 starts where cam:0 ends).
  event(project, 'cam:1').start = 2;
  const { ctx, at: seek } = harness(project);
  seek(.5);
  const rig = F.addRig(ctx, { blendIn: 0, blendOut: 0 });
  F.setRange(ctx, rig.id, 0, 7);
  await settle(ctx);
  const a = event(project, 'cam:0'), b = event(project, 'cam:1');
  const last = a.values.keyframes[a.values.keyframes.length - 1], firstB = b.values.keyframes[0];
  near(a.start + last.time, b.start + firstB.time, 1e-12, 'the cut time');
  nearVector(last.position, firstB.position, 1e-12, 'same position across the cut');
  assert(angle(last.rotation, firstB.rotation) < 1e-6, 'same rotation across the cut');
  // The step between consecutive samples stays small everywhere (no jump at the cut).
  const samplesAll = [...a.values.keyframes, ...b.values.keyframes.slice(1)];
  for (let index = 1; index < samplesAll.length; index++) {
    const step = Math.hypot(...samplesAll[index].position.map((value, axis) => value - samplesAll[index - 1].position[axis]));
    assert(step < .1, `continuous at ${index} (${step})`);
  }
}

function cacheKey() {
  const project = nativeProject();
  const { ctx } = harness(project);
  const rig = rigOf({});
  const key = F.pathKey(ctx, rig);
  assert.equal(F.pathKey(ctx, rig), key, 'stable');
  assert.equal(F.pathKey(ctx, rigOf({ start: 3, end: 5, distance: 4 })), key, 'rig range and framing do not change the path');
  project.tracks[2].events[0].start = .5;
  assert.equal(F.pathKey(ctx, rig), key, "another member's dance does not change it");
  project.tracks[1].events[0].start = .25;
  const moved = F.pathKey(ctx, rig);
  assert.notEqual(moved, key, "the slot's dance timing changes the key");
  project.tracks[1].events[0].duration = 11;
  assert.notEqual(F.pathKey(ctx, rig), moved, 'and its duration');
  const timed = F.pathKey(ctx, rig);
  project.performers[0].transform.position = [.5, 0, 0];
  assert.notEqual(F.pathKey(ctx, rig), timed, 'the performer transform changes it');
  assert.notEqual(F.pathKey(ctx, rigOf({ target: { slot: 1, part: 3 } })), F.pathKey(ctx, rig), 'the body part changes it');
  project.tracks.push({ id: 'scale1', kind: 'dance', nativeClass: 'LiveMemberScalingTrack', binding: '/EntryPoint/Live/Members/Member1/Model',
    events: [{ id: 'scale1:0', start: 1, duration: 2, values: { playableClass: 'LiveMemberScalingClip', intensity: 1 } }] });
  const scaled = F.pathKey(ctx, rig);
  project.tracks[project.tracks.length - 1].events[0].start = 2;
  assert.notEqual(F.pathKey(ctx, rig), scaled, 'the slot scaling timing changes it');
}

// A moved or longer rig samples only the frames the cache lacks; a performer move resamples.
async function pathCache() {
  const project = nativeProject();
  const scene = fakeScene(dancing);
  const { ctx, history, at: seek } = harness(project, { scene });
  seek(.5);
  const rig = F.addRig(ctx);
  await settle(ctx);
  assert.equal(scene.calls.length, 1);
  assert.equal(scene.calls[0].times.length, 121, 'the rig grid (2 s + 1)');
  near(scene.calls[0].times[1], 1 / 60, 0, 'absolute frame times');
  F.setRange(ctx, rig.id, 0, 3);
  await settle(ctx);
  assert.equal(scene.calls.length, 2);
  assert.deepEqual(scene.calls[1].times, Array.from({ length: 60 }, (_, n) => (121 + n) / 60), 'only the new frames');
  history.apply({ label: 'Edit value', changes: [{ target: { kind: 'performer', id: 'p1' }, path: ['transform', 'position'], after: [.5, 0, 0] }] });
  await settle(ctx);
  assert.equal(scene.calls.length, 3, 'a performer move rebakes from a new path');
  assert.equal(scene.calls[2].times.length, 181);
}

// No rig: nothing is sampled, written or created (spec R1).
async function noRegression() {
  const project = nativeProject(), before = copy(project);
  const arrays = project.tracks[0].events.map((item) => item.values.keyframes);
  const scene = fakeScene(dancing);
  const { ctx, history } = harness(project, { scene });
  plugin.projectChanged(ctx, { reason: 'reload' });
  keysPlugin.projectChanged(ctx, { reason: 'reload' });
  history.apply({ label: 'Edit value', changes: [{ target: { kind: 'performer', id: 'p1' }, path: ['transform', 'position'], after: [2, 0, 0] }] });
  history.undo();
  await settle(ctx);
  await plugin.beforeSave(ctx);
  await plugin.beforeExport(ctx);
  assert.equal(scene.calls.length, 0, 'the member sampler never runs without a rig');
  assert.deepEqual(project, before, 'the project is unchanged');
  assert.equal(project.editor, undefined, 'no editor layer');
  project.tracks[0].events.forEach((item, index) => assert.equal(item.values.keyframes, arrays[index], 'samples never rewritten'));
  assert.equal(plugin.editedCount(ctx), 0);
  for (const tab of ['edit', 'camera', 'all']) assert.deepEqual(plugin.extraLanes(ctx, tab), [], `no rig lane without rigs (${tab})`);
}

// A shot the native writer cannot take (no keyframes in editableValues) is never baked.
async function nonEditableShots() {
  const project = nativeProject();
  const locked = event(project, 'cam:2');
  locked.editableValues = locked.editableValues.filter((key) => key !== 'keyframes');
  const keyframes = locked.values.keyframes;
  const { ctx, at: seek } = harness(project);
  seek(.5);
  const rig = F.addRig(ctx);
  F.setRange(ctx, rig.id, 0, 12);
  await settle(ctx);
  assert.equal(locked.values.keyframes, keyframes, 'not rewritten');
  assert.notDeepEqual(event(project, 'cam:0').values.keyframes, original('cam:0'), 'the editable shots are');
}

async function memberStates() {
  // A member that is not loaded: the rig is skipped, the shots keep the original motion, export refuses.
  const project = nativeProject();
  const { ctx, at: seek } = harness(project, { scene: fakeScene(dancing, { slots: [1] }) });
  seek(.5);
  const rig = F.addRig(ctx);
  await settle(ctx);
  F.setField(ctx, rig.id, 'target.slot', 2);
  await settle(ctx);
  assert.deepEqual(F.state(ctx).unavailable, [rig.id]);
  assert.deepEqual(event(project, 'cam:0').values.keyframes, original('cam:0'), 'nothing applied for a member that is not loaded');
  await plugin.beforeSave(ctx);
  await assert.rejects(plugin.beforeExport(ctx), /no member to follow/);
  F.setField(ctx, rig.id, 'target.slot', 1);
  await settle(ctx);
  assert.deepEqual(F.state(ctx).unavailable, []);
  await plugin.beforeExport(ctx);

  // A body part the member does not have.
  F.setField(ctx, rig.id, 'target.part', 2);
  await settle(ctx);
  assert.deepEqual(F.state(ctx).unavailable, [rig.id]);
  F.setField(ctx, rig.id, 'target.part', 0);
  await settle(ctx);

  // While an open/import runs (locked) the members are still loading: the bake waits and runs once unlocked.
  const later = nativeProject();
  const targets = { slots: [] };
  const scene = fakeScene(dancing);
  scene.memberTargets = () => targets.slots.map((slot) => ({ slot, id: 'p' + slot, parts: [0, 3], facing: true }));
  const h = harness(later, { scene });
  targets.slots = [1];
  h.at(.5);
  const loaded = F.addRig(h.ctx);
  await settle(h.ctx);
  const baked = copy(event(later, 'cam:0').values.keyframes);
  targets.slots = [];
  h.lock(true);
  keysPlugin.projectChanged(h.ctx, { reason: 'reload' });
  plugin.projectChanged(h.ctx, { reason: 'reload' });
  await settle(h.ctx);
  assert.deepEqual(event(later, 'cam:0').values.keyframes, baked, 'a bake while the scene loads keeps the shots as they are');
  assert(loaded);
  targets.slots = [1];
  h.lock(false);
  for (let index = 0; index < 50 && !F.state(h.ctx).dirty; index++) await tick();
  await new Promise((resolve) => setTimeout(resolve, 260));
  await settle(h.ctx);
  assert.equal(F.state(h.ctx).dirty, false, 'the bake runs once the editor is unlocked');
  assert.deepEqual(event(later, 'cam:0').values.keyframes, baked);
}

async function cancelling() {
  const project = nativeProject();
  let release = null;
  const scene = fakeScene(dancing, { gate: (signal) => new Promise((resolve, reject) => {
    release = resolve;
    signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true });
  }) });
  const { ctx, at: seek } = harness(project, { scene });
  seek(.5);
  F.addRig(ctx);
  await tick();
  assert(F.state(ctx).progress, 'sampling in progress');
  F.cancel(ctx);
  await settle(ctx);
  assert.deepEqual(event(project, 'cam:0').values.keyframes, original('cam:0'), 'a cancelled bake writes nothing');
  assert.equal(F.state(ctx).cancelled, true);
  assert.equal(F.state(ctx).dirty, true);
  // Save bakes what is due; cancelling that too refuses the save.
  const saving = plugin.beforeSave(ctx);
  await tick(); await tick();
  F.cancel(ctx);
  await assert.rejects(saving, /cancelled/);
  // Let it finish this time.
  const again = plugin.beforeSave(ctx);
  for (let index = 0; index < 20 && !release; index++) await tick();
  await tick();
  release();
  await again;
  assert.equal(F.state(ctx).dirty, false);
  assert.notDeepEqual(event(project, 'cam:0').values.keyframes, original('cam:0'), 'the save baked the rig');
}

// Commands: duplicate, delete, view presets, framing presets, the lane on the Edit tab.
async function commands() {
  const project = nativeProject();
  const { ctx, history, at: seek } = harness(project);
  seek(.5);
  const rig = F.addRig(ctx);
  const copyRig = F.duplicateRig(ctx, rig.id);
  assert(copyRig && copyRig.id !== rig.id);
  assert.equal(copyRig.start, rig.end, 'the copy follows the original');
  assert.equal(copyRig.end - copyRig.start, rig.end - rig.start);
  assert.equal(history.peekUndo().label, 'Duplicate follow camera');
  for (const tab of ['edit', 'camera', 'all']) {
    const lanes = plugin.extraLanes(ctx, tab);
    assert.equal(lanes.length, 1, `the rig lane is listed on the ${tab} tab`);
    assert.equal(lanes[0].id, 'camera-rigs');
    assert.equal(lanes[0].after, 'cam', 'after the MainCamera track');
    assert.deepEqual(lanes[0].members, [1], 'the followed members (member filter)');
  }
  assert.deepEqual(plugin.extraLanes(ctx, 'dance'), [], 'not on other tabs');
  F.setView(ctx, rig.id, 'right');
  F.setField(ctx, rig.id, 'yaw', 15);
  F.setView(ctx, rig.id, 'custom');
  let stored = F.rigs(ctx).find((item) => item.id === rig.id);
  assert.equal(stored.view, 'custom');
  assert.equal(stored.yaw, 105, 'switching to Custom keeps the direction');
  F.setView(ctx, rig.id, 'back');
  stored = F.rigs(ctx).find((item) => item.id === rig.id);
  assert.equal(stored.yaw, 0, 'a preset from Custom starts at its own direction');
  F.setFraming(ctx, rig.id, 'close');
  stored = F.rigs(ctx).find((item) => item.id === rig.id);
  assert.equal(stored.distance, 1.3);
  F.setField(ctx, rig.id, 'distance', 99);
  assert.equal(F.rigs(ctx).find((item) => item.id === rig.id).distance, 30, 'stored values are clamped to the spec ranges');
  F.setRange(ctx, rig.id, 1.004, 1.01);
  stored = F.rigs(ctx).find((item) => item.id === rig.id);
  assert.equal(stored.start, 1, 'frame-snapped start');
  assert.equal(Math.round((stored.end - stored.start) * 60), 2, 'at least two frames');
  assert(F.deleteRig(ctx, copyRig.id));
  assert.equal(F.rigs(ctx).length, 1);
  await settle(ctx);
}

// The scene sampler (mv-studio-scene.js) on a stub renderer: a member whose hips move and turn.
async function sceneSampler() {
  const Three = Object.create(THREE);
  Three.WebGLRenderer = class {
    constructor() {
      this.domElement = { setAttribute() {}, remove() {}, width: 1280, height: 720 };
      this.shadowMap = { enabled: false }; this.capabilities = { isWebGL2: true }; this.size = new THREE.Vector2();
    }
    setClearColor() {} getSize(out) { return out.copy(this.size); } setSize(width, height) { this.size.set(width, height); }
    getPixelRatio() { return 1; } setPixelRatio() {} render() {} dispose() {}
  };
  Three.OrbitControls = class { constructor() { this.target = new THREE.Vector3(); } update() {} addEventListener() {} dispose() {} };
  Three.GLTFLoader = class {
    parse(_bytes, _base, onLoad) {
      const root = new THREE.Group(), hips = new THREE.Bone(), head = new THREE.Bone();
      hips.name = 'Hips'; hips.userData.elichika_node = 3; hips.position.set(0, 1, 0);
      head.name = 'Head'; head.userData.elichika_node = 5; head.position.set(0, .5, 0);
      root.add(hips); hips.add(head);
      // Hips walk +X (three) 1 m/s and turn 90° about +Y over 4 s.
      const turn = (degrees) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), degrees * Math.PI / 180).toArray();
      const clip = new THREE.AnimationClip('walk', 4, [
        new THREE.VectorKeyframeTrack('Hips.position', [0, 4], [0, 1, 0, 4, 1, 0]),
        new THREE.QuaternionKeyframeTrack('Hips.quaternion', [0, 4], [...turn(0), ...turn(90)]),
      ]);
      onLoad({ scene: root, animations: [clip] });
    }
  };
  const window = { THREE: Three, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
    ResizeObserver: class { observe() {} disconnect() {} }, console: { warn() {} }, performance };
  const context = vm.createContext({ window, fetch: async () => ({ ok: true, async arrayBuffer() { return new ArrayBuffer(1); } }),
    AbortController, DOMException, Uint8Array, Uint16Array, Float64Array, setTimeout, Promise });
  for (const file of ['mv-studio-lighting.js', 'mv-studio-split.js', 'mv-studio-scene.js']) {
    vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/' + file), 'utf8'), context);
  }
  const scene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, { visible: true, onError(message) { throw new Error(message); } });
  const project = { token: 'follow', quality: { mode: 10, values: {} }, duration: 4,
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb',
      rig: { focusParts: { 0: 5, 2: { world: [3, 0, 4] }, 3: 3 } }, transform: { position: [0, 0, 0] } }],
    tracks: [] };
  await scene.load(project);
  assert.deepEqual(JSON.parse(JSON.stringify(scene.memberTargets())), [{ slot: 1, id: 'solo', parts: [0, 2, 3], facing: true }]);
  scene.seek(1, project, true);
  const headAt = () => scene.sampleMemberPath({ slot: 1, part: 0, times: [scene.inspect().time] });
  const playhead = await headAt();
  nearVector(playhead.positions, [-1, 1.5, 0], 1e-9, 'the head at the playhead (Unity, mirrored X)');
  const times = Float64Array.from({ length: 241 }, (_, n) => n / 60);
  const slices = [];
  const result = await scene.sampleMemberPath({ slot: 1, part: 0, times, budgetMs: .01, onProgress: (done) => slices.push(done) });
  assert(slices.length > 3, `time-sliced (${slices.length} slices)`);
  assert.equal(slices[slices.length - 1], 241);
  // (The GLB clip loops at 4 s in three's mixer, so the last sample is checked at 239.)
  for (const n of [0, 60, 120, 239]) {
    nearVector(Array.from(result.positions.subarray(3 * n, 3 * n + 3)), [-n / 60, 1.5, 0], 1e-6, `head at ${n / 60} s`);
    near(result.yaw[n], -90 * (n / 240), 1e-4, `facing yaw at ${n / 60} s (Unity: three +Y turn = negative yaw)`);
  }
  // The playhead's own frame is back after the sampling (the member stands at t = 1).
  assert.equal(scene.inspect().time, 1);
  nearVector((await headAt()).positions, [-1, 1.5, 0], 1e-9, 'the playhead pose is restored');
  // The fixed world point part (Face) and a member without hips have no time dependence / facing.
  const face = await scene.sampleMemberPath({ slot: 1, part: 2, times: [0, 2] });
  nearVector(face.positions, [3, 0, 4, 3, 0, 4], 1e-12, 'a fixed world point');
  // Cancellable between slices.
  const controller = new AbortController();
  const cancelled = scene.sampleMemberPath({ slot: 1, part: 0, times, budgetMs: .01, signal: controller.signal,
    onProgress: () => controller.abort() });
  await assert.rejects(cancelled, (error) => error.name === 'AbortError');
  await assert.rejects(scene.sampleMemberPath({ slot: 4, part: 0, times: [0] }), /not loaded/);
  scene.dispose();
}

(async () => {
  lookRotationMatchesThree();
  staticViews();
  memberFrame();
  deadZone();
  stepResponse();
  heightLock();
  weights();
  cacheKey();
  await bake();
  await orderIndependence();
  await halfFrame();
  await continuity();
  await pathCache();
  await noRegression();
  await nonEditableShots();
  await memberStates();
  await cancelling();
  await commands();
  await sceneSampler();
  console.log('mv_studio_camera_follow_test: ok');
})().catch((error) => { console.error(error); process.exit(1); });
