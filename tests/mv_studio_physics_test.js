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
