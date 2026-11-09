'use strict';

// Compact expected cache values came from actual original ARM64 Initialize.
// These tests use no game binaries, DOM, WebGL, or native emulator at runtime.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
global.THREE = THREE;
require('../webtools/web/static/viewer-game-physics-math.js');
require('../webtools/web/static/viewer-game-physics-collision.js');
require('../webtools/web/static/viewer-game-physics.js');

const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/game_physics_native_initialize.json'), 'utf8'));
const engine = global.ViewerGamePhysics;
const math = global.ViewerGamePhysicsMath;
const F = Math.fround;
const fvec = values => values.map(F);
const clone = value => JSON.parse(JSON.stringify(value));
const mirrorPosition = a => [-a[0], a[1], a[2]];
const mirrorQuaternion = a => [a[0], -a[1], -a[2], a[3]];
const settings = { bones: true, colliders: true, profile: 'navi' };
const bitsBuffer = new ArrayBuffer(4);
const bitsFloat = new Float32Array(bitsBuffer);
const bitsWord = new Uint32Array(bitsBuffer);
function bits(value) { bitsFloat[0] = value; return bitsWord[0]; }
function lengthF32(a, b) {
  const d = a.map((value, axis) => F(F(value) - F(b[axis])));
  return F(Math.sqrt(F(F(F(d[0] * d[0]) + F(d[1] * d[1])) + F(d[2] * d[2]))));
}
function close(actual, expected, tolerance, label) {
  assert.strictEqual(actual.length, expected.length, label);
  actual.forEach((value, axis) => assert(Number.isFinite(value) && Math.abs(value - expected[axis]) <= tolerance,
    `${label}[${axis}]: ${value} != ${expected[axis]} (tolerance ${tolerance})`));
}
function distance(a, b) { return Math.hypot(...a.map((value, axis) => value - b[axis])); }
function nativeWorldPosition(object) { return fvec(mirrorPosition(object.getWorldPosition(new THREE.Vector3()).toArray())); }
function nativeLocalRotation(object) { return fvec(mirrorQuaternion(object.quaternion.toArray())); }
function nativeWorldRotation(object) {
  const chain = [];
  for (let item = object; item; item = item.parent) chain.push(item);
  return chain.reverse().reduce((result, item) => engine.reference.quatMul(result, nativeLocalRotation(item)), [0, 0, 0, 1]);
}

assert.strictEqual(fixtures.provenance.numericStubs, 0);
assert.strictEqual(fixtures.provenance.entryRva, '0x2c97150');
assert.strictEqual(fixtures.provenance.originalEulerWrapperRva, '0x4408180');
assert.strictEqual(Object.keys(fixtures.provenance.images).length, 3);
assert.strictEqual(fixtures.cases.length, 8);

// Native Initializer foundation checks are independent of the scene adapter's
// cache implementation. JS OS-math rounding is allowed a small degree tolerance;
// the original native fixture itself retains the exact float32 outputs.
let nativeCacheChecks = 0;
for (const fixture of fixtures.cases) {
  const expected = fixture.expectedCache, rest = fixture.restInputs;
  close(math.angles(rest.localRotation), expected.initialAngles, 1e-4, `${fixture.name}: original rest Euler`);
  assert.strictEqual(bits(lengthF32(rest.bonePosition, rest.childPosition)), bits(expected.springLength),
    `${fixture.name}: original rest distance float32 bits`);
  assert.strictEqual(engine.reference.classify(rest.name), expected.skirtData, `${fixture.name}: original skirt classification`);
  close(expected.localRotation, rest.localRotation, 0, `${fixture.name}: native cached local rotation`);
  close(expected.currentTipPosition, rest.childPosition, 0, `${fixture.name}: native initial current tip`);
  close(expected.previousTipPosition, rest.childPosition, 0, `${fixture.name}: native initial previous tip`);
  assert(expected.hasTrans && expected.isInitialized && fixture.expectedCacheUnchangedWithoutInitialize);
  if (fixture.explicitReinitialize) {
    const reset = fixture.explicitReinitialize.expectedCache, pose = fixture.animatedGetterInputs;
    close(math.angles(pose.localRotation), reset.initialAngles, 1e-4, `${fixture.name}: original explicit-reset Euler`);
    assert.strictEqual(bits(lengthF32(pose.bonePosition, pose.childPosition)), bits(reset.springLength));
    assert.strictEqual(engine.reference.classify(pose.name), reset.skirtData);
  }
  nativeCacheChecks++;
}

function sceneFor(fixture) {
  const root = new THREE.Group(), bone = new THREE.Bone(), child = new THREE.Bone();
  const parent = fixture.expectedCache.hasParent ? new THREE.Object3D() : root;
  bone.userData.elichika_node = 0; child.userData.elichika_node = 1;
  bone.name = fixture.name; child.name = 'DeclaredChild';
  if (parent !== root) { parent.userData.elichika_node = 2; root.add(parent); }
  parent.add(bone); bone.add(child);
  function setPose(input) {
    if (parent !== root) { parent.position.set(0, 0, 0); parent.quaternion.identity(); parent.scale.set(1, 1, 1); }
    bone.position.fromArray(mirrorPosition(input.bonePosition));
    bone.quaternion.fromArray(mirrorQuaternion(input.localRotation)); bone.scale.set(1, 1, 1);
    child.quaternion.identity(); child.scale.set(1, 1, 1);
    root.updateMatrixWorld(true);
    child.position.copy(bone.worldToLocal(new THREE.Vector3().fromArray(mirrorPosition(input.childPosition))));
    root.updateMatrixWorld(true);
  }
  function pose() {
    const result = {};
    root.traverse(object => {
      if (object.userData.elichika_node === undefined) return;
      result[String(object.userData.elichika_node)] = {
        position: object.position.toArray(), quaternion: object.quaternion.toArray(),
        scale: object.scale.toArray(), matrixAutoUpdate: true,
      };
    });
    return result;
  }
  setPose(fixture.restInputs);
  const restPose = pose();
  const record = {
    id: '0:bone', node: 0, sourceIndex: 0, name: fixture.name, kind: 'bone', enabled: true,
    values: { stiffnessForce: .7, dragForce: .1, lowRotationLimit: [-180, -180, -180], highRotationLimit: [180, 180, 180] },
    simulation: { childNode: 1, parentIndex: -1, siblingIndex: -1, childIndex: -1,
      boneAxis: [0, 1, 0], radius: .05, externalForce: [0, 0, 0], colliderIds: [], colliderBits: 0 },
  };
  const catalog = { native: { available: true }, components: [record],
    managers: [{ id: '0:manager', sourceIndex: 0, bones: [record.id], lodBones: [], colliders: [] }] };
  return { root, bone, child, parent, setPose, pose, restPose, record, catalog };
}

function expectedStep(scene, cache) {
  // Only the basis is taken from independent original Initialize output. Dynamic
  // history starts at the captured animated child, as the adapter's reset does.
  const tip = nativeWorldPosition(scene.child);
  const buffer = {
    parentPosition: nativeWorldPosition(scene.bone.parent), parentRotation: nativeWorldRotation(scene.bone.parent),
    position: nativeWorldPosition(scene.bone), rotation: nativeWorldRotation(scene.bone),
    localRotation: nativeLocalRotation(scene.bone), previousTipPosition: tip.slice(), currentTipPosition: tip.slice(),
  };
  const data = {
    localPosition: fvec(mirrorPosition(scene.restPose['0'].position)), baseLocalRotation: cache.localRotation.slice(),
    parentIndex: -1, childIndex: -1, siblingIndex: -1, colliderCount: 0,
    boneLength: cache.springLength, boneAxis: [0, 1, 0], radius: .05,
    stiffnessForce: scene.record.values.stiffnessForce, dragForce: scene.record.values.dragForce,
    externalForce: [0, 0, 0], lowRotationLimit: [-180, -180, -180], highRotationLimit: [180, 180, 180],
    colliderIndexBit: 0, boneIndex: 0, colliderIndex: 0, colliderDataCount: 0,
  };
  engine.reference.stepJob([data], [buffer], [], [], { kind: 'single', math });
  return mirrorPosition(buffer.currentTipPosition);
}
function cacheFromPose(input) { return { localRotation: input.localRotation.slice(), springLength: lengthF32(input.bonePosition, input.childPosition) }; }
function ready(solver, generation, label) {
  const state = solver.getState();
  assert(state.available && state.initialized, `${label}: original runtime initializes`);
  assert.deepStrictEqual(state.initializationMissing, [], `${label}: no missing initialization inputs`);
  assert.strictEqual(state.initializationGeneration, generation, `${label}: rest generation`);
  assert.strictEqual(state.bones.length, 1);
  return state;
}

let sceneChecks = 0, explicitRestChanges = 0, separateQuaternionControls = 0;
for (const fixture of fixtures.cases) {
  const scene = sceneFor(fixture);
  scene.setPose(fixture.animatedGetterInputs);
  const solver = engine.create(scene.root, scene.catalog, record => record.values, { initializationPose: clone(scene.restPose) });
  solver.captureAnimationPose({ time: .5 });
  solver.apply(0, settings);
  ready(solver, 1, fixture.name);
  const expected = expectedStep(scene, fixture.expectedCache);
  const animatedCache = cacheFromPose(fixture.animatedGetterInputs);
  const incorrectlyRebased = expectedStep(scene, animatedCache);
  assert(distance(expected, incorrectlyRebased) > 1e-3, `${fixture.name}: fixture detects animated-pose rebasing`);
  assert(distance(expected, expectedStep(scene, Object.assign({}, fixture.expectedCache,
    { springLength: animatedCache.springLength }))) > 1e-3,
  `${fixture.name}: fixture independently detects animated-distance replacement`);
  if (fixture.expectedCache.springLength > 0) {
    assert(distance(expected, expectedStep(scene, Object.assign({}, fixture.expectedCache,
      { localRotation: animatedCache.localRotation }))) > 1e-3,
    `${fixture.name}: fixture independently detects animated-quaternion replacement`);
    separateQuaternionControls++;
  }
  solver.apply(1 / 60, settings);
  close(ready(solver, 1, fixture.name).bones[0].tip, expected, 3e-6, `${fixture.name}: native REST basis after animation capture`);
  sceneChecks++;

  // Repeated pose capture and ordinary seeks/resets must retain the same base
  // quaternion/length, even if an author reset asks to reconsider an unchanged
  // initialization-pose snapshot.
  scene.setPose(fixture.animatedGetterInputs);
  solver.captureAnimationPose({ time: .75 }); solver.apply(0, settings);
  ready(solver, 1, `${fixture.name}: animation capture`);
  for (const reason of ['seek', 'manual-reset', 'author-edit']) {
    scene.setPose(fixture.animatedGetterInputs); solver.captureAnimationPose({ time: 2 });
    solver.resetSimulation(reason); solver.apply(0, settings);
    ready(solver, 1, `${fixture.name}: ${reason}`);
    const expectedReset = expectedStep(scene, fixture.expectedCache);
    solver.apply(1 / 60, settings);
    close(ready(solver, 1, `${fixture.name}: ${reason}`).bones[0].tip, expectedReset, 3e-6,
      `${fixture.name}: reset retains original native REST basis`);
    sceneChecks++;
  }

  if (fixture.explicitReinitialize) {
    // Explicit rest replacement is the one operation allowed to change the
    // initialization generation. Keep the displayed pose different from it.
    scene.setPose(fixture.animatedGetterInputs); const newRest = scene.pose();
    scene.record.name = fixture.animatedGetterInputs.name;
    scene.setPose(fixture.restInputs); solver.captureAnimationPose({ time: 4 });
    solver.setInitializationPose(clone(newRest)); solver.apply(0, settings);
    ready(solver, 2, `${fixture.name}: explicit new REST`);
    const expectedNewRest = expectedStep(scene, fixture.explicitReinitialize.expectedCache);
    assert(distance(expectedNewRest, expectedStep(scene, fixture.expectedCache)) > 1e-3,
      `${fixture.name}: fixture detects retaining the old REST after explicit replacement`);
    solver.apply(1 / 60, settings);
    close(ready(solver, 2, fixture.name).bones[0].tip, expectedNewRest, 3e-6,
      `${fixture.name}: explicit REST uses original native recaptured cache`);
    scene.setPose(fixture.restInputs); solver.captureAnimationPose({ time: 5 });
    solver.setInitializationPose(clone(newRest)); solver.apply(0, settings);
    ready(solver, 2, `${fixture.name}: identical REST replacement is idempotent`);
    explicitRestChanges++;
  }
  solver.dispose();
}

console.log(`GAME_PHYSICS_NATIVE_INITIALIZATION_PASS: ${nativeCacheChecks} native cache fixtures, ${sceneChecks} animated/seek/reset basis checks, ${separateQuaternionControls} independent quaternion controls, ${explicitRestChanges} explicit REST replacements; three original ELF hashes retained`);
