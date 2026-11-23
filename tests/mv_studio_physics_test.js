/* Use the original-game solver through the Studio pose/clock adapter. */
'use strict';
const assert = require('node:assert/strict');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

global.window = { THREE };
require('../webtools/web/static/viewer-game-physics-math.js');
require('../webtools/web/static/viewer-game-physics-collision.js');
require('../webtools/web/static/viewer-game-physics.js');
require('../webtools/web/static/mv-studio-physics.js');

const clock = window.MVStudioPhysics.createClock();
assert.equal(clock.step(undefined, 30), 0);
assert.equal(clock.step(1000, 30), 1/30);
assert.equal(clock.step(1000 + 1000/60, 30), 0);
assert.equal(clock.step(1000 + 1000/30, 30), 1/30);
assert.equal(clock.step(1500, 30), 1/30, 'one job after delayed presentation');
assert.equal(clock.step(1500, 30), 0, 'no catch-up jobs against the same pose');
clock.reset();
assert.equal(clock.step(1500, 60), 1/60);
assert.equal(clock.step(1500 + 1000/60, 60), 1/60);

const root = new THREE.Group();
const [parent, bone, tip, extra, extraTip, collider] = Array.from({ length: 6 }, (_, id) => {
  const node = new THREE.Bone(); node.userData.elichika_node = id; return node;
});
root.add(parent, collider);
parent.add(bone, extra);
bone.add(tip); extra.add(extraTip);
tip.position.x = extraTip.position.x = -1;
collider.position.x = -.85;
extra.position.y = 2;
const sourceBone = (id, node, childNode) => ({ id, kind: 'bone', node, name: 'Hair_Dyna',
  values: { stiffnessForce: .02, dragForce: .6, lowRotationLimit: [-180,-180,-180], highRotationLimit: [180,180,180] },
  simulation: { childNode, parentIndex: -1, childIndex: -1, siblingIndex: -1, boneAxis: [1,0,0], externalForce: [0,.05,0],
    radius: .06, colliderIds: [1], colliderBits: 1 } });
const records = [sourceBone('root-bone', 1, 2), sourceBone('lod-bone', 3, 4),
  { id: 'collider', node: 5, kind: 'collider', values: { radius: .35, offset: [0,0,0] } }];
const catalog = { available: true, components: records, native: { available: true,
  runtime: { sources: [{ sourceIndex: 0, known: true, skirtsafeDisable: true }] } },
  managers: [{ id: 'manager', sourceIndex: 0, bones: ['root-bone'], lodBones: ['lod-bone'], colliders: ['collider'], kneeTransforms: [] }] };
const createSolver = window.ViewerGamePhysics.create;
let solver;
window.ViewerGamePhysics.create = (...args) => { solver = createSolver(...args); return solver; };
const model = window.MVStudioPhysics.create(root, catalog, { safeSwingBoneKnown: true, safeSwingBone: false });
assert(model);
assert.equal(window.MVStudioPhysics.create(root, { ...catalog, managers: [{}] }), null);
const invalidBone = { ...records[0], simulation: { ...records[0].simulation, boneAxis: [] } };
assert.equal(window.MVStudioPhysics.create(root, { ...catalog, components: [invalidBone, ...records.slice(1)] }), null);
model.apply(0, 0, {});
assert.equal(solver, undefined, 'paused first paint has no speculative physics job');
model.apply(0, 1/30, {});
assert.equal(solver.getState().dynamicBones, 2, 'old projects with no explicit flag retain the default LOD bones');
assert.equal(solver.getState().capsules.length, 1);
assert(solver.getState().contacts > 0, 'native contact uses the original collider');
const physical = bone.quaternion.toArray();
assert.notDeepEqual(physical, [0,0,0,1]);
model.restorePose();
assert.deepEqual(bone.quaternion.toArray(), [0,0,0,1]);
model.apply(0, 0, {});
assert.deepEqual(bone.quaternion.toArray(), physical, 'pause retains the last physics pose without a step');
assert.equal(solver.getTimingState().totalNativeSteps, 1);
model.reset('seek');
model.restorePose();
model.apply(2, 0, {});
assert.deepEqual(bone.quaternion.toArray(), [0,0,0,1], 'seeking discards prior output before authoring the target pose');
model.apply(2, 1/30, { member_swing_bone_mv: false });
assert.equal(solver.getState().dynamicBones, 1, 'low quality excludes original LOD bones only');
assert.equal(solver.getState().capsules.length, 1);
assert.equal(solver.getTimingState().totalNativeSteps, 2);
model.dispose();
assert.deepEqual(bone.quaternion.toArray(), [0,0,0,1]);
console.log('MV Studio native SwingBone clock, colliders, pause, seek and quality LOD passed');

// ---------------------------------------------------------------- frame-rate rule
// Live3DScene.<OnLoad>d__16: set_FPS(RefreshRateMode ? 0 : FrameRate60Fps ? 60 : 30),
// CoolAssist clears FrameRate60Fps; m_live_quality_setting.frame_rate_60fps is 1 only
// for quality modes 10 and 50.
{
  const P = window.MVStudioPhysics;
  const preset = { 10: true, 20: false, 30: false, 40: false };
  for (const [mode, sixty] of Object.entries(preset)) {
    assert.equal(P.gameFrameRate({ quality_mode: Number(mode), frame_rate_60fps: sixty }), sixty ? 60 : 30, `quality ${mode}`);
  }
  assert.equal(P.gameFrameRate({ frame_rate_60fps: true }, { coolAssist: true }), 30, 'cool assist clears 60 fps');
  assert.equal(P.gameFrameRate({ frame_rate_60fps: false }, { refreshRateMode: true, displayRate: 90 }), 90);
  assert.equal(P.gameFrameRate({ frame_rate_60fps: true }, { refreshRateMode: true, displayRate: 120, coolAssist: true }), 120,
    'refresh-rate mode uses set_FPS(0), the display rate');
  assert.throws(() => P.gameFrameRate({}, { refreshRateMode: true }), /display refresh rate/);
  assert.equal(P.exportTickRate(30), 60, 'a 30 fps FOVMOD export ticks the game at 60 Hz');
  assert.equal(P.exportTickRate(60), 60);
  assert.equal(P.exportTickRate(120), 120);
  for (const fps of [24, 25, 50, 90, '30']) assert.throws(() => P.exportTickRate(fps), /30, 60 or 120/);
  assert.deepEqual(P.normalizeTiming(), { order: 'game', device: { refreshRateMode: false, displayRate: null, coolAssist: false }, exportFps: null });
  assert.throws(() => P.normalizeTiming({ order: 'late' }), /game or same-frame/);
  assert.throws(() => P.normalizeTiming({ device: { refreshRateMode: true, displayRate: 75 } }), /60, 90 or 120/);
  assert.throws(() => P.normalizeTiming({ exportFps: 24 }), /30, 60 or 120/);
  assert.equal(P.frameRate({ frame_rate_60fps: false }, P.normalizeTiming()), 30);
  assert.equal(P.frameRate({ frame_rate_60fps: true }, P.normalizeTiming()), 60);
  assert.equal(P.frameRate({ frame_rate_60fps: false }, P.normalizeTiming({ exportFps: 30 })), 60);
  assert.equal(P.frameRate({ frame_rate_60fps: false }, P.normalizeTiming({ device: { refreshRateMode: true, displayRate: 120 } })), 120);
}

// ---------------------------------------------------------------- game update order
// LiveCoreMemberManager.Update runs the group job before LiveTimeSynchronizer
// evaluates the director, so job N reads the pose frame N-1 ended with and writes
// world rotations against those parents; the timeline then moves the parents and the
// bones keep their local rotations; LateUpdate corrects skirts with frame N's knees.
const engines = new Map();
{
  const create = window.ViewerGamePhysics.create;
  window.ViewerGamePhysics.create = (root, ...rest) => { const engine = create(root, ...rest); engines.set(root, engine); return engine; };
}
function springRig({ skirt = false, safeSwingBone = false } = {}) {
  const root = new THREE.Group();
  const [parent, dyna, tip, kneeL, kneeR] = Array.from({ length: 5 }, (_, id) => {
    const node = new THREE.Bone(); node.userData.elichika_node = id; return node;
  });
  root.add(parent, kneeL, kneeR); parent.add(dyna); dyna.add(tip);
  parent.position.y = 1; tip.position.set(-.3, 0, skirt ? -.04 : 0);
  const simulation = { childNode: 2, parentIndex: -1, childIndex: -1, siblingIndex: -1, boneAxis: [1, 0, 0],
    externalForce: skirt ? [0, 0, -.01] : [0, -.01, 0], radius: .02, colliderIds: [], colliderBits: 0 };
  if (skirt) Object.assign(simulation, { skirtSafeEnable: true, skirtLimitDotMin: 0, skirtLimitDotMax: 1, skirtRotDegMax: 0,
    kneeSpaceOffsetFront: .05, kneeSpaceOffsetOther: .05, kneeSpaceOffsetForce: 0 });
  const record = { id: 'b', kind: 'bone', node: 1, name: skirt ? 'SkirtA1_Dyna' : 'Hair_Dyna',
    values: { stiffnessForce: .02, dragForce: .4, lowRotationLimit: [-180, -180, -180], highRotationLimit: [180, 180, 180] }, simulation };
  const catalog = { available: true, components: [record],
    native: { available: true, runtime: { sources: [{ sourceIndex: 0, known: true, skirtsafeDisable: !skirt }] } },
    managers: [{ id: 'm', sourceIndex: 0, bones: ['b'], lodBones: [], colliders: [], kneeTransforms: skirt ? [3, 4] : [] }] };
  root.updateMatrixWorld(true);
  const model = window.MVStudioPhysics.create(root, catalog, { safeSwingBoneKnown: true, safeSwingBone });
  const animated = { 0: { quaternion: true }, 3: { quaternion: true }, 4: { quaternion: true } };
  const motion = { animatedProperties: () => animated };
  const quality = { member_swing_bone_mv: true };
  let time = 0;
  // One scene frame (mv-studio-scene.js playbackFrame): the update hook, the actor
  // loop (restorePose, then the timeline writes the animated transforms), the late hook.
  function frame(order, pose, delta = 1 / 30) {
    time += delta;
    model.frame('update', time, delta, quality, motion, order);
    model.restorePose();
    parent.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), pose.parent * Math.PI / 180);
    kneeL.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), (pose.knee || 0) * Math.PI / 180);
    kneeR.quaternion.copy(kneeL.quaternion);
    root.updateMatrixWorld(true);
    model.frame('late', time, delta, quality, motion, order);
    root.updateMatrixWorld(true);
  }
  return { root, parent, dyna, tip, kneeL, model, frame, get engine() { return engines.get(root); } };
}
const close = (a, b, message, tolerance = 1e-6) =>
  assert(a.every((value, index) => Math.abs(value - b[index]) <= tolerance), `${message}: ${a} vs ${b}`);
{
  // Game order with animation a1..an steps exactly like the same-frame order
  // with a0..a(n-1): every job sees the previous frame's pose.
  const angles = [0, 30, 30, -20, 45, 10];
  const game = springRig(), lagged = springRig(), sameFrame = springRig();
  game.parent.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0);
  for (let index = 0; index < angles.length; index++) {
    game.frame('game', { parent: angles[index] });
    lagged.frame('same-frame', { parent: index ? angles[index - 1] : 0 });
    sameFrame.frame('same-frame', { parent: angles[index] });
    close(game.dyna.quaternion.toArray(), lagged.dyna.quaternion.toArray(), `frame ${index + 1} local rotation is the lagged job's`);
  }
  assert.notDeepEqual(game.dyna.quaternion.toArray(), sameFrame.dyna.quaternion.toArray(), 'the order changes the result');
  // Frame 2 detail: the parent turned by 30 deg, the job ran on the frame-1 parent,
  // so the bone's world rotation is R_new times the local rotation from the R0 job.
  const order = springRig(), reference = springRig();
  order.frame('game', { parent: 0 }); order.frame('game', { parent: 30 });
  reference.frame('same-frame', { parent: 0 }); reference.frame('same-frame', { parent: 0 });
  const local = reference.dyna.quaternion.clone();
  close(order.dyna.quaternion.toArray(), local.toArray(), 'local = inverse(R0 parent) * W2');
  const expected = order.parent.getWorldQuaternion(new THREE.Quaternion()).multiply(local);
  close(order.dyna.getWorldQuaternion(new THREE.Quaternion()).toArray(), expected.toArray(), 'world = R_new * local');
  assert.equal(order.engine.getTimingState().totalNativeSteps, 2);

  // Pause (SwingBoneManager.Paused): no job, the held output stays on the bone.
  const held = order.dyna.quaternion.toArray();
  order.frame('game', { parent: 30 }, 0);
  assert.deepEqual(order.dyna.quaternion.toArray(), held, 'a paused frame holds the last output');
  assert.equal(order.engine.getTimingState().totalNativeSteps, 2, 'a paused frame runs no job');
  order.frame('game', { parent: 30 });
  assert.equal(order.engine.getTimingState().totalNativeSteps, 3, 'resume keeps history and steps once');

  // Seek: history is discarded and the target frame shows the authored pose.
  order.model.reset('seek');
  order.frame('game', { parent: -10 }, 0);
  assert.deepEqual(order.dyna.quaternion.toArray(), [0, 0, 0, 1], 'a seek shows the authored pose');
  order.frame('game', { parent: -10 });
  assert.equal(order.engine.getState().initialized, true);
  assert.notDeepEqual(order.dyna.quaternion.toArray(), [0, 0, 0, 1], 'the next frame steps from the seek pose');
}
{
  // Properties the timeline animates are written after the job, so they win.
  const rig = springRig();
  const animated = { 0: { quaternion: true }, 1: { quaternion: true } };
  const motion = { animatedProperties: () => animated };
  rig.model.frame('update', 1 / 30, 1 / 30, {}, motion, 'game');
  rig.model.restorePose();
  rig.dyna.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), .3);
  const authored = rig.dyna.quaternion.toArray();
  rig.model.frame('late', 1 / 30, 1 / 30, {}, motion, 'game');
  assert.deepEqual(rig.dyna.quaternion.toArray(), authored, 'an animated bone keeps the timeline value');
}
{
  // AllSafeCorrect runs in LateUpdate, after the timeline: frame 2's knees decide the
  // correction even though the job ran on frame 1's pose. With skirtRotDegMax 0 the
  // corrected tip lies at z = kneeSpaceOffsetFront * (1 - knee ratio) in the parent frame.
  const turned = springRig({ skirt: true, safeSwingBone: true }), straight = springRig({ skirt: true, safeSwingBone: true });
  for (const rig of [turned, straight]) rig.frame('game', { parent: 0, knee: 0 });
  turned.frame('game', { parent: 0, knee: 90 });
  straight.frame('game', { parent: 0, knee: 0 });
  const kneeAxis = new THREE.Vector3(-1, 0, 0).applyQuaternion(turned.kneeL.getWorldQuaternion(new THREE.Quaternion()));
  close([kneeAxis.z], [1], 'the turned knee faces the parent forward (Unity +Z)');
  const tipZ = (rig) => rig.parent.worldToLocal(rig.tip.getWorldPosition(new THREE.Vector3())).z;
  assert(Math.abs(tipZ(turned)) < 1e-6, `frame-2 knees give cutoff 0 (z ${tipZ(turned)})`);
  // SafeCorrect places the tip along (-length, y, cutoff) at the bone length, so z/|x| = cutoff/length.
  const length = Math.hypot(.3, .04), local = straight.parent.worldToLocal(straight.tip.getWorldPosition(new THREE.Vector3()));
  close([local.z], [.05 * Math.abs(local.x) / length], 'frame-1 knees would give cutoff 0.05');
  assert(turned.engine.getTimingState().safeCorrections === 1 && straight.engine.getTimingState().safeCorrections === 1);
}
console.log('MV Studio spring frame-rate rule, game update order, pause, seek and LateUpdate knees passed');
