/* Enhanced solver dynamics at different display rates; no DOM or fake math.
 * Frame-rate invariance is an enhanced feature, not native frame-unit fidelity. */
'use strict';
const assert = require('assert');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
global.window = { THREE };
require('../webtools/web/static/viewer-physics.js');

function simulate(deltas) {
  const root = new THREE.Group(), bone = new THREE.Bone(), child = new THREE.Bone();
  root.add(bone); bone.add(child); child.position.x = 1;
  bone.userData.elichika_node = 0; child.userData.elichika_node = 1;
  root.updateMatrixWorld(true);
  const record = { id: 'original:bone', node: 0, sourceIndex: 0, name: 'Tail_Dyna', kind: 'bone', enabled: true,
    values: { stiffnessForce: .02, dragForce: .3, lowRotationLimit: [-90, -90, -90], highRotationLimit: [90, 90, 90] },
    simulation: { childNode: 1, colliders: [], externalForce: [0, -.02, 0] } };
  const solver = window.ViewerPhysics.createSolver(root, { components: [record] }, value => value.values);
  for (const delta of deltas) {
    // ViewerRig restores the authored/animated pose before each physics frame.
    bone.quaternion.identity(); root.updateMatrixWorld(true);
    solver.apply(delta, { bones: true, colliders: false });
  }
  return { tip: child.getWorldPosition(new THREE.Vector3()), solver, root, bone, child };
}

const rates = [30, 60, 90, 120, 144, 240], report = {};
const reference = simulate(Array(120).fill(1 / 120)).tip;
for (const rate of rates) {
  const result = simulate(Array(rate).fill(1 / rate));
  assert(result.tip.toArray().every(Number.isFinite), `${rate} FPS produced nonfinite dynamics`);
  assert(Math.abs(result.tip.length() - 1) < 1e-8, `${rate} FPS changed the original bone length`);
  const error = result.tip.distanceTo(reference);
  assert(error < .0006, `${rate} FPS changed one-second swing by ${error}; expected timestep-correct dynamics`);
  report[rate] = { tip: result.tip.toArray(), error };
}
const variable = [...Array(10).fill(1 / 30), ...Array(48).fill(1 / 144), ...Array(20).fill(1 / 60)];
assert(Math.abs(variable.reduce((total, delta) => total + delta, 0) - 1) < 1e-12);
const switched = simulate(variable);
assert(switched.tip.distanceTo(reference) < .0006, 'changing display frame rate rescales the previous frame velocity incorrectly');
switched.solver.reset(); switched.bone.quaternion.identity(); switched.root.updateMatrixWorld(true);
switched.solver.apply(0, { bones: true, colliders: false });
assert(switched.child.getWorldPosition(new THREE.Vector3()).distanceTo(new THREE.Vector3(1, 0, 0)) < 1e-8,
  'reset clears stored displacement and velocity without advancing a paused motion');

console.log('ENHANCED_PHYSICS_TIMING_PASS: 30/60/90/120/144/240 FPS, mid-motion rate changes, fixed length, paused reset');
console.log(JSON.stringify(report));

{
  // Two source colliders may occupy the same location but have different
  // radii. Endpoint-only deduplication silently discarded the larger one.
  const root = new THREE.Group(), bone = new THREE.Bone(), end = new THREE.Bone(), leg = new THREE.Bone();
  root.add(bone, leg); bone.add(end); end.position.x = 1; leg.position.x = .7;
  bone.userData.elichika_node = 0; end.userData.elichika_node = 1; leg.userData.elichika_node = 2;
  const b = { id: 'bone', node: 0, sourceIndex: 0, name: 'Tail_Dyna', kind: 'bone', enabled: true,
    values: { stiffnessForce: .02, dragForce: .3, lowRotationLimit: [-90, -90, -90], highRotationLimit: [90, 90, 90] },
    simulation: { childNode: 1, radius: .05, colliders: ['small', 'large'] } };
  const small = { id: 'small', node: 2, sourceIndex: 0, name: 'LeftUpLeg', kind: 'collider', enabled: true,
    values: { radius: .1, offset: [0, 0, 0] } };
  const large = { ...small, id: 'large', values: { radius: .5, offset: [0, 0, 0] } };
  root.updateMatrixWorld(true);
  const solver = window.ViewerPhysics.createSolver(root, { components: [b, small, large] }, value => value.values);
  solver.apply(0, { bones: true, colliders: true });
  assert.deepStrictEqual(solver.getState().bones[0].colliders, ['small', 'large'], 'different source radii must remain separate constraints');
  const origin = bone.getWorldPosition(new THREE.Vector3()), tip = end.getWorldPosition(new THREE.Vector3()), center = leg.getWorldPosition(new THREE.Vector3());
  const line = tip.clone().sub(origin), t = Math.max(0, Math.min(1, center.clone().sub(origin).dot(line) / line.lengthSq()));
  const clearance = center.distanceTo(origin.clone().addScaledVector(line, t));
  assert(clearance >= .55 - .002, `the larger collider still penetrates the rod by ${.55 - clearance}`);
  console.log(`ENHANCED_PHYSICS_COLOCATED_RADII_PASS: clearance=${clearance}, required=0.55`);
}
