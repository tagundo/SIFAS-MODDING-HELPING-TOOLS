/* QA candidate: missing song correction metadata must not stop native Update.
 * Native control-flow evidence is in ../native-semantics.json. No shader,
 * quality, collision equations, source-rest pose or known flags are mocked. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const product = process.env.PRODUCT_ROOT || path.resolve(__dirname, '..');
const THREE = require(path.join(product, 'webtools/web/static/vendor/three-r128/three.min.js'));
global.window = { THREE };
require(path.join(product, 'webtools/web/static/viewer-game-physics-math.js'));
require(path.join(product, 'webtools/web/static/viewer-game-physics-collision.js'));
const source = process.env.PHYSICS_SOURCE || path.join(product, 'webtools/web/static/viewer-game-physics.js');
vm.runInThisContext(fs.readFileSync(source, 'utf8'), { filename: source });
const API = window.ViewerGamePhysics, cases = [];
function fixture(skirt, collider, configuration) {
  configuration = configuration || {};
  const root = new THREE.Group(), parent = new THREE.Bone(), bone = new THREE.Bone(), child = new THREE.Bone(), left = new THREE.Bone(), right = new THREE.Bone();
  [parent, bone, child, left, right].forEach((object, index) => { object.userData.elichika_node = index; });
  root.add(parent, left, right); parent.add(bone); bone.add(child); child.position.set(-1, 0, skirt ? -.1 : 0);
  const record = { id: 'b', node: 1, name: skirt ? 'SkirtA1_Dyna' : 'Tail1_Dyna', kind: 'bone', sourceIndex: 0,
    values: { stiffnessForce: .02, dragForce: .6, lowRotationLimit: [-180, -180, -180], highRotationLimit: [180, 180, 180] },
    simulation: { childNode: 2, parentIndex: -1, siblingIndex: -1, childIndex: -1, radius: .02, boneAxis: [1, 0, 0], externalForce: [0, .03, 0], colliderIds: [], colliderBits: 0,
      skirtSafeEnable: true, skirtLimitDotMin: -1, skirtLimitDotMax: 1, skirtRotDegMax: 0, kneeSpaceOffsetFront: .1, kneeSpaceOffsetOther: .1, kneeSpaceOffsetForce: .2 } };
  const catalog = { native: { available: true, missing: [] }, components: [record], managers: [{ id: 'm', sourceIndex: 0, node: 0, bones: ['b'], lodBones: [], colliders: [], kneeTransforms: [3, 4] }] };
  if (collider) {
    const object = new THREE.Object3D(); object.userData.elichika_node = 5; object.position.set(-.8, .1, 0); root.add(object);
    catalog.components.push({ id: 'c', node: 5, name: 'Collider', kind: 'collider', sourceIndex: 0, sibling: null, values: { radius: .3, offset: [0, 0, 0] } });
    catalog.managers[0].colliders = ['c']; record.simulation.colliderIds = ['c']; record.simulation.colliderBits = 1;
  }
  function pose() { const result = {}; root.traverse(object => { if (object.userData.elichika_node !== undefined) result[object.userData.elichika_node] = { position: object.position.toArray(), quaternion: object.quaternion.toArray(), scale: object.scale.toArray() }; }); return result; }
  root.updateMatrixWorld(true); const rest = pose();
  const engine = API.create(root, catalog, component => component.values, { getInitializationPose: () => configuration.missingRest ? null : rest });
  const live = { bones: true, colliders: true, profile: 'live', enableLod: true, skirtsafeDisableBySource: { 0: false }, safeSwingBone: false };
  function capture(context = {}) { root.updateMatrixWorld(true); engine.captureAnimationPose(context); }
  function resetPose() { root.traverse(object => { const saved = rest[object.userData.elichika_node]; if (saved) { object.position.fromArray(saved.position); object.quaternion.fromArray(saved.quaternion); object.scale.fromArray(saved.scale); } }); root.updateMatrixWorld(true); }
  return { root, bone, child, record, catalog, rest, engine, live, capture, resetPose };
}
function coreSnapshot(s) { const state = s.engine.getState(); return { bones: state.bones, capsules: state.capsules, quaternion: s.bone.quaternion.toArray(), child: s.child.position.toArray(), totalSteps: state.totalNativeSteps, dynamicGeneration: state.dynamicGeneration, initializationGeneration: state.initializationGeneration, contacts: state.contacts, safeCorrections: state.safeCorrections }; }
function run(name, fn) { try { fn(); cases.push({ name, pass: true }); } catch (error) { cases.push({ name, pass: false, error: String(error.stack || error) }); } }
run('Unknown song flag after actual clip reset advances original core and preserves forced startup', () => {
  for (const skirt of [false, true]) {
    const reference = fixture(skirt), unknown = fixture(skirt);
    for (const value of [reference, unknown]) { value.capture(); value.engine.apply(1 / 60, value.live); value.resetPose(); value.engine.resetSimulation('rig:clip-change'); value.capture({ clipId: 'new-mv', motionCategory: 'mv' }); }
    const settings = { ...unknown.live, safeSwingBone: undefined };
    for (let frame = 0; frame < 5; frame++) {
      reference.capture({ clipId: 'new-mv', motionCategory: 'mv', safeSwingBone: false });
      unknown.capture({ clipId: 'new-mv', motionCategory: 'mv' });
      reference.engine.apply(1 / 60, reference.live); unknown.engine.apply(1 / 60, settings);
      assert.deepStrictEqual(coreSnapshot(unknown), coreSnapshot(reference), 'Unknown correction metadata must retain every exact core float and startup output of known-false reference');
      const state = unknown.engine.getState();
      assert.equal(state.nativeSteps, 1); assert.equal(state.available, true); assert.deepStrictEqual(state.initializationMissing, []);
      assert.deepStrictEqual(state.skirtCorrectionMissing, ['motion-skirt-runtime']);
    }
  }
});
run('Verified per-component derived costume maps retain active core when the next song flag is unknown', () => {
  for (const flag of [false, true]) {
    const original = fixture(true), derived = fixture(true);
    const settings = { ...derived.live, skirtsafeDisableBySource: {}, skirtsafeDisableByComponent: { b: flag }, safeSwingBone: undefined };
    for (let frame = 0; frame < 4; frame++) {
      original.capture(); derived.capture();
      original.engine.apply(1 / 30, { ...original.live, skirtsafeDisableBySource: { 0: flag } }); derived.engine.apply(1 / 30, settings);
      assert.deepStrictEqual(coreSnapshot(derived), coreSnapshot(original), 'Derived proof is per-component but must preserve exact source-wide core results');
      assert.equal(derived.engine.getState().nativeSteps, 1);
    }
  }
  function mixedFixture() {
    const s = fixture(true), other = new THREE.Bone(), child = new THREE.Bone();
    other.userData.elichika_node = 6; child.userData.elichika_node = 7; other.position.x = .3; child.position.set(-1, 0, -.1);
    s.bone.parent.add(other); other.add(child); s.record.simulation.externalForce = [0, 0, 0];
    const record = { ...s.record, id: 'mixed', node: 6, name: 'SkirtE1_Dyna', simulation: { ...s.record.simulation, childNode: 7 } };
    s.catalog.components.push(record); s.catalog.managers[0].bones.push(record.id); s.root.updateMatrixWorld(true);
    const rest = {}; s.root.traverse(object => { if (object.userData.elichika_node !== undefined) rest[object.userData.elichika_node] = { position: object.position.toArray(), quaternion: object.quaternion.toArray(), scale: object.scale.toArray() }; });
    s.engine.dispose(); s.engine = API.create(s.root, s.catalog, component => component.values, { getInitializationPose: () => rest });
    s.capture = context => { s.root.updateMatrixWorld(true); s.engine.captureAnimationPose(context || {}); };
    s.resetPose = () => { s.root.traverse(object => { const row = rest[object.userData.elichika_node]; if (row) { object.position.fromArray(row.position); object.quaternion.fromArray(row.quaternion); object.scale.fromArray(row.scale); } }); s.root.updateMatrixWorld(true); };
    return s;
  }
  const reference = mixedFixture(), partial = mixedFixture();
  const known = { ...reference.live, safeSwingBone: true, skirtsafeDisableBySource: {}, skirtsafeDisableByComponent: { b: false, mixed: true } };
  const unknown = { ...partial.live, safeSwingBone: true, skirtsafeDisableBySource: {}, skirtsafeDisableByComponent: { b: false } };
  reference.capture(); partial.capture(); reference.engine.apply(1 / 30, known); partial.engine.apply(1 / 30, unknown);
  assert.equal(reference.engine.getState().safeCorrections, 2); assert.equal(partial.engine.getState().safeCorrections, 2, 'Initial force is independent of both known and unknown costume flags');
  for (const s of [reference, partial]) { s.resetPose(); s.engine.resetSimulation('seek'); s.capture(); }
  reference.engine.apply(1 / 30, known); partial.engine.apply(1 / 30, unknown);
  assert.equal(partial.engine.getState().nativeSteps, 1); assert.equal(partial.engine.getState().safeCorrections, 1, 'Only the verified correction chain runs in a partially known derived manager');
  assert.deepStrictEqual(coreSnapshot(partial), coreSnapshot(reference), 'An unknown correction chain is skipped, rather than guessed false and corrected');
  assert(partial.engine.getState().skirtCorrectionMissing.includes('source-skirt-runtime:0'));
});
run('Losing and restoring only song metadata does not discard history or reinitialize', () => {
  const s = fixture(false); s.capture(); s.engine.apply(1 / 30, s.live);
  const generation = s.engine.getState().dynamicGeneration;
  const before = s.engine.getState().totalNativeSteps;
  for (const known of [false, false, true, false, true]) {
    s.capture(); s.engine.apply(1 / 30, { ...s.live, safeSwingBone: known ? false : undefined });
    assert.equal(s.engine.getState().dynamicGeneration, generation);
    assert.deepStrictEqual(s.engine.getState().skirtCorrectionMissing, known ? [] : ['motion-skirt-runtime']);
  }
  assert.equal(s.engine.getState().totalNativeSteps, before + 5);
});
run('Unknown song flag retains real capsule contacts and exactly matches known core collision output', () => {
  const reference = fixture(false, true), unknown = fixture(false, true); let contacts = 0;
  for (let frame = 0; frame < 8; frame++) {
    reference.capture(); unknown.capture();
    reference.engine.apply(1 / 60, reference.live); unknown.engine.apply(1 / 60, { ...unknown.live, safeSwingBone: undefined });
    assert.deepStrictEqual(coreSnapshot(unknown), coreSnapshot(reference)); contacts += unknown.engine.getState().contacts;
  }
  assert(contacts > 0, 'At least one real native capsule collision must be exercised');
});
run('Paused redraw does not advance; genuine catalog, math, rest and child failures remain blocked', () => {
  const s = fixture(false); s.capture(); s.engine.apply(0, { ...s.live, safeSwingBone: undefined });
  assert.equal(s.engine.getState().totalNativeSteps, 0); assert.equal(s.engine.getState().available, true);
  s.catalog.native.available = false; s.catalog.native.missing = ['verified-job-input']; s.engine.resetSimulation('model-load'); s.capture(); s.engine.apply(1 / 30, s.live);
  assert.equal(s.engine.getState().totalNativeSteps, 0); assert.equal(s.engine.getState().available, false);
  assert(s.engine.getState().initializationMissing.includes('verified-job-input'));
  for (const reasons of [[], ['foreign-manager:kneeTransforms'], ['m:bones:reference'], ['b:child'], [null]]) {
    const invalid = fixture(false); invalid.catalog.native.available = false; invalid.catalog.native.missing = reasons;
    invalid.capture(); invalid.engine.apply(1 / 30, invalid.live);
    assert.equal(invalid.engine.getState().totalNativeSteps, 0); assert.equal(invalid.engine.getState().available, false);
  }
  const noRest = fixture(false, false, { missingRest: true }); noRest.capture(); noRest.engine.apply(1 / 30, noRest.live);
  assert.equal(noRest.engine.getState().totalNativeSteps, 0); assert(noRest.engine.getState().initializationMissing.includes('original-rest-pose'));
  const math = window.ViewerGamePhysicsMath; let noMath;
  try { window.ViewerGamePhysicsMath = undefined; noMath = fixture(false); }
  finally { window.ViewerGamePhysicsMath = math; }
  noMath.capture(); noMath.engine.apply(1 / 30, noMath.live);
  assert.equal(noMath.engine.getState().totalNativeSteps, 0); assert(noMath.engine.getState().initializationMissing.includes('native-math-module'));
});
run('Unknown source, knee and song combinations preserve core and isolate only unavailable correction', () => {
  for (const missingSource of [false, true]) for (const missingKnees of [false, true]) for (const missingMotion of [false, true]) {
    const reference = fixture(false, true), unknown = fixture(false, true);
    // Prime the same native home job, then switch both to MV. Both receive
    // one original load force if and only if the required knees are present.
    reference.capture(); unknown.capture(); reference.engine.apply(1 / 60, { ...reference.live, profile: 'navi' }); unknown.engine.apply(1 / 60, { ...unknown.live, profile: 'navi' });
    reference.resetPose(); unknown.resetPose(); reference.engine.resetSimulation('seek'); unknown.engine.resetSimulation('seek');
    if (missingKnees) unknown.catalog.managers[0].kneeTransforms = [];
    const settings = { ...unknown.live, safeSwingBone: missingMotion ? undefined : false,
      skirtsafeDisableBySource: missingSource ? {} : { 0: false } };
    // Independently known-false reference runs exactly the same core math.
    // Missing knees are a documented unavailable extra pass in both scenes.
    const referenceSettings = reference.live;
    if (missingKnees) reference.catalog.managers[0].kneeTransforms = [];
    for (let frame = 0; frame < 4; frame++) {
      reference.capture(); unknown.capture(); reference.engine.apply(1 / 60, referenceSettings); unknown.engine.apply(1 / 60, settings);
      assert.deepStrictEqual(coreSnapshot(unknown), coreSnapshot(reference));
      const state = unknown.engine.getState(); assert.equal(state.nativeSteps, 1); assert.equal(state.available, true); assert.deepStrictEqual(state.initializationMissing, []);
      assert.equal(state.skirtCorrectionMissing.includes('source-skirt-runtime:0'), missingSource);
      assert.equal(state.skirtCorrectionMissing.includes('source-knee-transforms:0'), missingKnees);
      assert.equal(state.skirtCorrectionMissing.includes('motion-skirt-runtime'), missingMotion);
    }
  }
  const serialized = fixture(true); serialized.catalog.managers[0].kneeTransforms = null;
  serialized.catalog.native.available = false; serialized.catalog.native.missing = ['m:kneeTransforms'];
  serialized.capture(); serialized.engine.apply(1 / 30, { ...serialized.live, safeSwingBone: true });
  assert.equal(serialized.engine.getState().nativeSteps, 1); assert.equal(serialized.engine.getState().safeCorrections, 0);
  assert.equal(serialized.engine.getState().available, true); assert.deepStrictEqual(serialized.engine.getState().initializationMissing, []);
  assert(serialized.engine.getState().skirtCorrectionMissing.includes('source-knee-transforms:0'));
});
const report = { source, status: cases.every(value => value.pass) ? 'PASS' : 'FAIL', cases };
if (process.env.EVIDENCE_FILE) fs.writeFileSync(process.env.EVIDENCE_FILE, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (report.status !== 'PASS') process.exitCode = 1;
