/* Expected outputs were produced by original ARM64 instructions, not this JS. */
'use strict';
const assert = require('assert');
const fixture = require('./fixtures/game_physics_native_collisions.json');
require('../webtools/web/static/viewer-game-physics-collision.js');
const collision = globalThis.ViewerGamePhysicsCollision;
const tolerance = fixture.provenance.comparisonToleranceAbsolute;
let maximumError = 0;
function compare(actual, expected, label) {
  assert.equal(actual.length, expected.length, label);
  actual.forEach((value, axis) => {
    assert(Number.isFinite(value), `${label}[${axis}] is finite`);
    const error = Math.abs(value - expected[axis]); maximumError = Math.max(maximumError, error);
    assert(error <= tolerance, `${label}[${axis}]: JS ${value}, original ARM64 ${expected[axis]}, error ${error}`);
  });
}
const methods = { sphere_sphere: 'sphereSphere', sphere_capsule: 'sphereCapsule', capsule_sphere: 'capsuleSphere', capsule_capsule: 'capsuleCapsule' };
const movingCases = {};
for (const row of fixture.radiusCases) {
  const value = collision.radius(row.radius, row.siblingIndex < 0 ? null : row.siblingRadius, row.ratio);
  compare([value], [row.nativeRadius], `GetRadius(${row.radius},${row.siblingRadius},${row.ratio})`);
}
for (const recorded of fixture.collisionCases) {
  const row = JSON.parse(JSON.stringify(recorded)), bone = row.bone, firstTipArray = bone.tip, siblingTipArray = bone.sibling.tip;
  row.colliderA.sibling = row.colliderB;
  collision[methods[row.method]](bone, row.colliderA, row.colliderB);
  assert.strictEqual(bone.tip, firstTipArray, 'The manager keeps its existing endpoint array');
  assert.strictEqual(bone.sibling.tip, siblingTipArray, 'The manager keeps its sibling endpoint array');
  compare(bone.tip, row.expectedTip, `${row.name}/${row.method}/tip`);
  compare(bone.sibling.tip, row.expectedSiblingTip, `${row.name}/${row.method}/sibling`);
  if (recorded.expectedTip.some((v, i) => Math.abs(v - recorded.bone.tip[i]) > 1e-6)) movingCases[row.method] = (movingCases[row.method] || 0) + 1;
}
Object.keys(methods).forEach(name => assert(movingCases[name] >= 20, `${name} has at least twenty independently recorded nontrivial native responses`));
// These regressions distinguish the source behavior from plausible alternate
// solvers: sibling capsule contact moves both ends; parallel axes skip NaNs;
// collision projection restores the independently stored endpoint length.
const capsule = fixture.collisionCases.find(r => r.name === 'sphere_inside' && r.method === 'capsule_sphere');
assert(capsule.expectedSiblingTip.some((v, i) => Math.abs(v - capsule.bone.sibling.tip[i]) > .001), 'Native capsule contact really moves the sibling');
for (const name of ['parallel_bone_and_collider_axes', 'coincident_bone_and_collider_axes']) {
  const row = fixture.collisionCases.find(r => r.name === name && r.method === 'capsule_capsule');
  compare(row.expectedTip, row.bone.tip.map(Math.fround), `${name} preserves authored endpoint`);
  compare(row.expectedSiblingTip, row.bone.sibling.tip.map(Math.fround), `${name} preserves authored sibling`);
}
assert.equal(collision.radius(.2, null, .5), Math.fround(.2), 'No sibling keeps the raw serialized radius');
assert.equal(collision.radius(.2, .5), Math.fround(.2), 'The original optional ratio defaults to zero');
console.log(`GAME_COLLISION_NATIVE_PASS: ${fixture.radiusCases.length} radius + ${fixture.collisionCases.length} collision cases; max absolute error ${maximumError}; tolerance ${tolerance}; synthetic Unity boundaries, not live-client parity`);
