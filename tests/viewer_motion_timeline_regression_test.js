/* Timeline composition regressions beyond timing: partial facial blends,
 * native/fallback overlap, neutral gaps, aliases and missing face bindings. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const factory = window.ViewerMotionTimeline;
const failures = [];
function check(name, fn) { try { fn(); console.log('PASS: ' + name); } catch (error) { failures.push({ name, error: String(error.stack || error) }); console.error('FAIL: ' + name + ': ' + error.message); } }
function close(actual, expected, label) { assert(Math.abs(actual - expected) < 1e-6, `${label}: ${actual} != ${expected}`); }
function setup(options = {}) {
  const root = new THREE.Group(), bone = new THREE.Bone(); bone.name = 'hips'; root.add(bone);
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial()); face.name = 'face'; face.userData.elichika_node = 2;
  face.morphTargetInfluences = options.noMorphs ? undefined : [.2, .4]; face.morphTargetDictionary = { A: 0, E: 1 }; root.add(face);
  const body = new THREE.AnimationClip('body', 3, [new THREE.VectorKeyframeTrack('hips.position', [0, 3], [0, 0, 0, 3, 0, 0])]);
  const native = new THREE.AnimationClip('native-a', 1, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 1], [1, 0, 1, 0])]);
  const metadata = { clips: [{ name: body.name, sourceHash: 'bodyhash', sourceName: 'body-source' }], expressionCatalog: {
    rawChannels: [{ node: 2, index: 0, name: 'MouthBlendShape.mouth_facial_001', group: 'mouth', defaultValue: .2 },
      { node: 2, index: 1, name: 'MouthBlendShape.mouth_facial_004', group: 'mouth', defaultValue: .4 }],
    presets: [{ semanticId: 10001, targets: [{ node: 2, index: 0, value: 1 }, { node: 2, index: 1, value: 0 }] },
      { semanticId: 10004, targets: [{ node: 2, index: 0, value: 0 }, { node: 2, index: 1, value: 1 }] }] } };
  if (options.native) metadata.clips.push({ name: native.name, sourceHash: 'nativehash', sourceName: 'ch0201_LiveFacial_mouth_001' });
  const descriptor = { version: 2, category: 'mv', bodySegments: [{ sourceHash: 'bodyhash', sourceName: 'body-source', start: 0, duration: 3, clipIn: 0, timeScale: 1 }],
    facial: { duration: 3, events: options.events || [] }, facialClips: options.native ? [{ kind: 'mouth', index: 13, sourceHash: 'nativehash', sourceName: 'ch0201_LiveFacial_mouth_001' }] : [] };
  const authored = [.2, .4];
  const player = factory.create(root, options.native ? [body, native] : [body], metadata, descriptor);
  // ViewerRig.evaluate restores its authored snapshot before each timeline
  // evaluation, including before scrubbing backwards or across neutral gaps.
  function frame(time) { bone.position.set(0, 0, 0); if (face.morphTargetInfluences) face.morphTargetInfluences.splice(0, authored.length, ...authored); player.evaluate(time); return face.morphTargetInfluences; }
  return { root, bone, face, body, native, metadata, descriptor, player, frame };
}
check('fallback half-weight pose retains the authored neutral remainder', () => {
  const s = setup({ events: [{ kind: 'mouth', index: 1, start: 0, duration: 1, weight: .5 }] }); s.frame(.5);
  close(s.face.morphTargetInfluences[0], .6, 'half target A + half authored A');
  close(s.face.morphTargetInfluences[1], .2, 'half neutral remainder on E');
});
check('native and fallback mouth clips blend together instead of overwrite', () => {
  const s = setup({ native: true, events: [{ kind: 'mouth', index: 13, start: 0, duration: 1, weight: .5 }, { kind: 'mouth', index: 4, start: 0, duration: 1, weight: .5 }] }); s.frame(.5);
  close(s.face.morphTargetInfluences[0], .5, 'native A half'); close(s.face.morphTargetInfluences[1], .5, 'fallback E half');
});
check('neutral gaps and backward scrubbing retain no stale facial/body tracks', () => {
  const s = setup({ native: true, events: [{ kind: 'mouth', index: 13, start: .5, duration: .5, weight: 1 }] });
  s.frame(.75); close(s.face.morphTargetInfluences[0], 1, 'inside facial interval');
  s.frame(1.5); close(s.face.morphTargetInfluences[0], .2, 'neutral authored A after interval'); close(s.face.morphTargetInfluences[1], .4, 'neutral authored E after interval');
  s.frame(.1); close(s.face.morphTargetInfluences[0], .2, 'before facial interval when scrubbing backward'); close(s.bone.position.x, .1, 'body sampled on current playhead');
});
check('two semantic aliases may reuse one exact native clip safely', () => {
  const s = setup({ native: true, events: [{ kind: 'mouth', index: 13, start: 0, duration: 1, weight: 1 }, { kind: 'mouth', index: 14, start: 2, duration: 1, weight: 1 }] });
  s.descriptor.facialClips.push({ kind: 'mouth', index: 14, sourceHash: 'nativehash', sourceName: 'ch0201_LiveFacial_mouth_001' });
  const player = factory.create(s.root, [s.body, s.native], s.metadata, s.descriptor);
  s.face.morphTargetInfluences.splice(0, 2, .2, .4); player.evaluate(.5); close(s.face.morphTargetInfluences[0], 1, 'first alias');
  s.face.morphTargetInfluences.splice(0, 2, .2, .4); player.evaluate(2.5); close(s.face.morphTargetInfluences[0], 1, 'second alias'); assert.equal(player.warnings.length, 0);
});
check('models without face bindings show a warning while the body remains usable', () => {
  const s = setup({ noMorphs: true, events: [{ kind: 'mouth', index: 1, start: 0, duration: 1, weight: 1 }] });
  s.frame(.5); close(s.bone.position.x, .5, 'body remains compatible'); assert.equal(s.player.compatibleSegments, 1);
  assert(s.player.warnings.some(text => /unavailable/i.test(text)), 'face availability must depend on actual loaded morph targets, not only metadata names');
});
check('audio tail contributes to one shared timeline duration', () => {
  const s = setup(); s.descriptor.audio = { tracks: [{ startTime: 2, duration: 5, offset: 0, playbackRate: 1 }] };
  const player = factory.create(s.root, [s.body], s.metadata, s.descriptor); close(player.duration, 7, 'voice/music tail must not be cut off at final body frame');
});
check('whole-array and UUID indexed native tracks share actual morph channels', () => {
  const s = setup({ native: true });
  const indexed = new THREE.AnimationClip('indexed', 1, [new THREE.NumberKeyframeTrack(s.face.uuid + '.morphTargetInfluences[0]', [0, 1], [0, 0])]);
  s.metadata.clips.push({ name: 'indexed', sourceHash: 'indexedhash', sourceName: 'indexed-source' });
  s.descriptor.facialClips.push({ kind: 'mouth', index: 14, sourceHash: 'indexedhash', sourceName: 'indexed-source' });
  s.descriptor.facial.events = [{ kind: 'mouth', index: 13, start: 0, duration: 1, weight: .25 }, { kind: 'mouth', index: 14, start: 0, duration: 1, weight: .25 }, { kind: 'mouth', index: 4, start: 0, duration: 1, weight: .5 }];
  const player = factory.create(s.root, [s.body, s.native, indexed], s.metadata, s.descriptor); player.evaluate(.5);
  close(s.face.morphTargetInfluences[0], .25, 'same channel blended once across whole/indexed native + fallback');
  close(s.face.morphTargetInfluences[1], .6, 'channel absent from indexed clip retains correct authored remainder');
});
check('verified directional gaze uses iris bones and leaves lids/morphs untouched', () => {
  const s = setup(), eye = new THREE.Bone(), lid = new THREE.Bone(); eye.name = 'LeftEye1'; lid.name = 'LeftEye_Lid'; s.root.add(eye); s.root.add(lid);
  const gaze = new THREE.AnimationClip('gaze', 1, [new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1], [0, 0, 0, 0, .2, 0]), new THREE.VectorKeyframeTrack('LeftEye_Lid.position', [0, 1], [0, 0, 0, 0, .9, 0]), new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 1], [1, 1, 1, 1])]);
  s.metadata.clips.push({ name: 'gaze', sourceHash: 'gazehash', sourceName: 'eye-direction-bank' });
  s.descriptor.facialClips = [{ kind: 'eyes', index: 8, sourceHash: 'gazehash', sourceName: 'eye-direction-bank' }];
  s.descriptor.facial.events = [{ kind: 'gaze', target: 31, start: 0, duration: 1, weight: .5 }];
  const player = factory.create(s.root, [s.body, gaze], s.metadata, s.descriptor); player.evaluate(.5);
  close(eye.position.y, .1, 'verified gaze target31 uses original eye008 pose'); close(lid.position.y, 0, 'gaze never overrides eyelid position'); close(s.face.morphTargetInfluences[0], .2, 'gaze never overrides mouth/eyelid morph');
});
if (failures.length) { console.error(JSON.stringify(failures, null, 2)); process.exitCode = 1; }
