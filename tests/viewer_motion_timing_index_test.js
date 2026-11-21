/* Compare indexed MV playback with the original evaluator on the same authored input. */
'use strict';
const assert = require('assert'), fs = require('fs'), vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });

function setup(indexTiming) {
  const root = new THREE.Group();
  const body = new THREE.Bone();
  body.name = 'hips'; body.userData.elichika_node = 1; root.add(body);
  const eye = new THREE.Bone();
  eye.name = 'LeftEye1'; eye.userData.elichika_node = 2; root.add(eye);
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'face'; face.userData.elichika_node = 3; face.morphTargetInfluences = [.2]; root.add(face);
  const animations = [], metadata = { clips: [], expressionCatalog: {
    rawChannels: [{ node: 3, index: 0, name: 'MouthBlendShape.mouth_facial_001', group: 'mouth' }]
  } };
  const descriptor = { version: 2, category: 'mv', bodySegments: [], facialClips: [], facial: { events: [] } };
  let timingReads = 0;
  function timed(segment, spec = {}) {
    Object.defineProperty(segment, 'timing', { get() { timingReads += 1; return spec; } });
    return segment;
  }
  function clip(name, tracks, visibility) {
    animations.push(new THREE.AnimationClip(name, 1, tracks));
    const identity = { sourceHash: name, sourceName: name };
    metadata.clips.push({ name, ...identity, visibility });
    return identity;
  }
  for (let i = 0; i < 12; i += 1) {
    const rotation = new THREE.Quaternion().setFromEuler(new THREE.Euler(.1 * i, .02, -.05 * i));
    const identity = clip('body' + i, [
      new THREE.VectorKeyframeTrack('hips.position', [0, 1], [0, 0, 0, i + 1, 0, 0]),
      new THREE.QuaternionKeyframeTrack('hips.quaternion', [0, 1], [0, 0, 0, 1, ...rotation.toArray()])
    ]);
    descriptor.bodySegments.push(timed({ ...identity, start: (12 - i) / 10, duration: .65,
      clipIn: .1, timeScale: 1.3 }, { easeIn: .12, blendOut: .22,
      m_PreExtrapolationMode: 2, m_PreExtrapolationTime: .12, postMode: 3, postTime: .2 }));
  }
  const falseMouth = clip('mouth-a', [new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 1], [.2, .8])],
    [{ node: 3, values: [false] }]);
  const trueMouth = clip('mouth-b', [new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 1], [.2, .1])],
    [{ node: 3, values: [true] }]);
  descriptor.facialClips.push({ kind: 'mouth', index: 2, ...falseMouth }, { kind: 'mouth', index: 3, ...trueMouth });
  for (let i = 0; i < 12; i += 1) {
    // Later starts are authored first. The second overlapping clip must still
    // win visibility, and all overlapping poses must use the same order.
    descriptor.facial.events.push(timed({ kind: 'mouth', index: 2, start: i * 2 + .5, duration: .8 }));
    descriptor.facial.events.push(timed({ kind: 'mouth', index: 3, start: i * 2 + .3, duration: .7 }));
    descriptor.facial.events.push(timed({ kind: 'mouth', index: 1, start: i * 2, duration: .6, weight: .2 }));
    descriptor.facial.events.push(timed({ kind: 'gaze', target: 31, start: i * 2, duration: 1 },
      { preMode: 1, preTime: .1, postMode: 1, postTime: .15 }));
  }
  const gaze = clip('eye-direction', [new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1], [0, 0, 0, 0, .2, 0])]);
  descriptor.facialClips.push({ kind: 'eyes', index: 8, ...gaze });
  const player = window.ViewerMotionTimeline.create(root, animations, metadata, descriptor, { indexTiming });
  function frame(time) {
    body.position.set(0, 0, 0);
    body.quaternion.identity();
    eye.position.set(0, 0, 0);
    face.morphTargetInfluences[0] = .2;
    face.visible = true;
    const before = JSON.stringify(player.animatedProperties(time));
    player.evaluate(time);
    player.applyVisibility(time);
    return { transform: body.position.toArray().concat(body.quaternion.toArray()), eye: eye.position.toArray(),
      shape: face.morphTargetInfluences[0], visible: face.visible, before,
      after: JSON.stringify(player.animatedProperties(time)), gaze: JSON.stringify(player.getGazeState()) };
  }
  function edit() {
    const bodyClip = descriptor.bodySegments[2];
    bodyClip.start = 8.5; bodyClip.duration = .03; bodyClip.timing.postTime = .475; bodyClip.weight = .5;
    const faceEvent = descriptor.facial.events[0];
    faceEvent.start = 7.6; faceEvent.duration = 1.5; faceEvent.timing.preMode = 1; faceEvent.timing.preTime = .7;
    descriptor.facial.events.push(timed({ kind: 'mouth', index: 1, start: 8.2, duration: 2, weight: .75 }));
    player.invalidateTiming();
  }
  return { frame, edit, reads: () => timingReads };
}

const legacy = setup(false), indexed = setup(true);
const boundaries = [-1, -.1, 0, .1, .3, .5, .6, 1, 1.15, 2, 23, 7.4, .7, 0];
for (const time of boundaries) assert.deepStrictEqual(indexed.frame(time), legacy.frame(time), 'playhead ' + time);
assert.strictEqual(indexed.frame(.7).visible, true, 'authored later visibility wins regardless of start order');
assert.strictEqual(indexed.frame(1.1).visible, false, 'the remaining active clip still controls visibility');
const before = indexed.reads();
for (let i = 0; i < 250; i += 1) {
  const time = (i * 97 % 2350) / 100 - .125;
  assert.deepStrictEqual(indexed.frame(time), legacy.frame(time), 'seek ' + time);
}
assert.strictEqual(indexed.reads(), before, 'timing specs remain cached across active and inactive seeks');
const editedTime = 8.501;
const old = indexed.frame(editedTime);
indexed.edit();
legacy.edit();
const updated = indexed.frame(editedTime);
assert.deepStrictEqual(updated, legacy.frame(editedTime), 'same-time edits after invalidation');
assert.notDeepStrictEqual(updated, old, 'rebuild observes edited intervals and new morph event');
for (const time of [6.9, 7.1, 8.5, 8.53, 9.005, 9.006, 0, .7, 42]) {
  assert.deepStrictEqual(indexed.frame(time), legacy.frame(time), 'edited playhead ' + time);
}
console.log('PASS: indexed timeline matches authored order, extrapolation, random seeks and same-time edits');
