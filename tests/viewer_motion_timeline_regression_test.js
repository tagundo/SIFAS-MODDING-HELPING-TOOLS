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
check('sampleLocal reads a dance property at another time without posing', () => {
  const s = setup(); s.frame(.5); close(s.bone.position.x, .5, 'posed at the playhead');
  const out = [9, 9, 9];
  assert.strictEqual(s.player.sampleLocal(s.bone, 'position', 2, out), out, 'the blended value lands in the caller buffer');
  close(out[0], 2, 'the dance at 2 s'); close(s.bone.position.x, .5, 'the pose is left alone');
  assert.strictEqual(s.player.sampleLocal(s.bone, 'quaternion', 2), null, 'an unanimated property has no sample');
  assert.strictEqual(s.player.sampleLocal(new THREE.Bone(), 'position', 2), null, 'nor has another node');
  s.frame(.75); close(s.bone.position.x, .75, 'the next evaluation is unaffected');
  const sampled = s.player.sampleLocal(s.bone, 'position', 1.25); close(sampled[0], 1.25, 'without a buffer a new array');
  s.player.evaluatePose(.75); close(s.bone.position.x, .75, 'a re-evaluation at the same time after a sample is fresh');
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
check('identical source copies reuse one motion while conflicting same-name clips stay ambiguous', () => {
  const s = setup(), duplicate = s.body.clone(); duplicate.name = 'body-copy';
  s.metadata.clips.push({ name: duplicate.name, sourceHash: 'bodyhash', sourceName: 'body-source' });
  const player = factory.create(s.root, [s.body, duplicate], s.metadata, s.descriptor);
  assert.equal(player.compatibleSegments, 1); player.evaluate(.5); close(s.bone.position.x, .5, 'identical copy uses original motion');
  duplicate.tracks[0].values[3] = 9;
  const conflict = factory.create(s.root, [s.body, duplicate], s.metadata, s.descriptor);
  assert.equal(conflict.compatibleSegments, 0, 'different actual tracks with the same source label must never be guessed');
});
check('shared facial tracks retain each source clip endpoint and repeated-time changes', () => {
  const s = setup(), track = new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 2], [0, 0, 1, 0]);
  const short = new THREE.AnimationClip('short-mouth', 1, [track]), long = new THREE.AnimationClip('long-mouth', 2, [track]);
  s.metadata.clips.push({ name: short.name, sourceHash: 'short-hash', sourceName: 'short-source' }, { name: long.name, sourceHash: 'long-hash', sourceName: 'long-source' });
  s.descriptor.facialClips = [{ kind: 'mouth', index: 13, sourceHash: 'short-hash', sourceName: 'short-source' }, { kind: 'mouth', index: 14, sourceHash: 'long-hash', sourceName: 'long-source' }];
  s.descriptor.facial.events = [{ kind: 'mouth', index: 13, start: 0, duration: 1, weight: 1 }, { kind: 'mouth', index: 14, start: 2, duration: 1, weight: 1 }];
  const player = factory.create(s.root, [s.body, short, long], s.metadata, s.descriptor);
  player.evaluate(.5); close(s.face.morphTargetInfluences[0], .5, 'short source uses its own endpoint');
  player.evaluate(2.5); close(s.face.morphTargetInfluences[0], 1, 'same underlying track uses the long source endpoint');
  s.descriptor.facial.events[1].weight = .5;
  s.face.morphTargetInfluences.splice(0, 2, .2, .4); player.evaluate(2.5);
  close(s.face.morphTargetInfluences[0], .6, 'a new evaluation at the same time observes current authored segment values');
});
check('native MV eye poses synchronize source time and mixer weight for the animated renderer', () => {
  const s = setup(), white = new THREE.Mesh(), eye = new THREE.Mesh();
  white.name = 'LeftEyeWhiteLine'; white.userData.elichika_node = 3; white.morphTargetInfluences = [0, 0];
  white.geometry.userData.mvStageCameraDepth = { kind: 'memberFace' };
  const display = new THREE.Bone(); display.userData.originalName = 'display_OnOff'; white.skeleton = new THREE.Skeleton([display]);
  eye.name = 'eye'; eye.userData.elichika_node = 4; eye.morphTargetInfluences = [0]; eye.morphTargetDictionary = { iris: 0 };
  s.root.add(white, eye);
  const clip = new THREE.AnimationClip('native-wink', 1, [
    new THREE.NumberKeyframeTrack('LeftEyeWhiteLine.morphTargetInfluences', [0, .75, 1], [0, 0, 0, .5, 1, 1]),
    new THREE.NumberKeyframeTrack('eye.morphTargetInfluences[0]', [0, 1], [0, 1])
  ]);
  s.metadata.clips.push({ name: clip.name, sourceName: 'ch0201_LiveFacial_eye_018', sourceRole: 'facial',
    bindingComplete: true, duration: 1, visibility: [{ node: 3, sourceProperty: 'Renderer.m_Enabled',
      interpolation: 'STEP', times: [0, 1], values: [false, true] }] });
  function event(start, weight, id) { return { kind: 'eyes', index: 18, start, duration: 1, weight, nativeEventId: 'original:' + id }; }
  s.descriptor.facial.events = [event(0, .75, 0), event(2, .4, 1), event(2, .6, 2), event(4, .75, 3), event(4, .75, 4)];
  const controller = factory.create(s.root, [s.body, clip], s.metadata, s.descriptor, { indexTiming: true });
  function frame(time) { controller.evaluatePose(time); controller.applyVisibility(time); }
  frame(.5);
  close(white.morphTargetInfluences[0], 0, 'stock WhiteLine ramp is still zero at source weight .75');
  close(white.morphTargetInfluences[1], .375, 'sampled morph is still scaled by the playable input weight');
  assert.equal(white.visible, false, 'display_OnOff initializes disabled and this source sample is still zero');
  close(eye.morphTargetInfluences[0], .75, 'the unbound iris renderer keeps the existing static pose');
  frame(2.5);
  close(white.morphTargetInfluences[0], 1, 'two active references to the same pose synchronize to their summed input weight');
  assert.equal(white.visible, true, 'the full-weight source sample enables the renderer');
  frame(4.5);
  close(white.morphTargetInfluences[0], 1.5, 'the native eye mixer does not normalize overlapping inputs');
  frame(1.5);
  assert.equal(white.visible, false, 'an idle sample after an enabled frame restores the game-initialized disabled state');
  frame(.5);
  assert.equal(white.visible, false, 'rewind restores the earlier source visibility');
  close(white.morphTargetInfluences[0], 0, 'rewind samples the earlier source pose');
  frame(1.5);
  assert.equal(white.visible, false, 'a neutral gap restores the game-initialized disabled state');
  close(white.morphTargetInfluences[1], 0, 'a neutral gap restores the authored morph state');

  const standalone = factory.create(s.root, [s.body, clip], s.metadata, s.descriptor);
  standalone.evaluatePose(.5); standalone.applyVisibility(.5);
  close(white.morphTargetInfluences[0], .75, 'standalone tools retain endpoint facial poses');
  assert.equal(white.visible, true);

  const track = s.metadata.clips.at(-1).visibility[0];
  track.sourceScalarKeys = [[0, 0, 0, 0, 0], [0.9999898672103882, 17737904553984, -2660685568, 98689.5078125, 0], [1, 0, 0, 0, 1]];
  s.descriptor.facial.events = [event(0, .9999952912330627, 0), event(2, .9999898672103882, 1)];
  const packed = factory.create(s.root, [s.body, clip], s.metadata, s.descriptor, { indexTiming: true });
  packed.applyVisibility(.5);
  assert.equal(white.visible, true, 'the original pre-endpoint cubic crosses the native visibility threshold');
  packed.applyVisibility(2.5);
  assert.equal(white.visible, false, 'the original transition key starts at zero');
  packed.applyVisibility(.5);
  assert.equal(white.visible, true, 'backward seeking samples the packed visibility curve again');

  s.metadata.clips.at(-1).visibility = [];
  white.morphTargetInfluences.fill(0);
  s.descriptor.facial.events = [event(0, .75, 0)];
  const morphOnly = factory.create(s.root, [s.body, clip], s.metadata, s.descriptor, { indexTiming: true });
  morphOnly.evaluatePose(.5); morphOnly.applyVisibility(.5);
  close(white.morphTargetInfluences[1], .375, 'native WhiteLine morphs synchronize without an enable lane');
  assert.equal(white.visible, false, 'a verified renderer without an enable lane uses the native default');

  white.visible = true;
  s.descriptor.facial.events = [];
  const noEyes = factory.create(s.root, [s.body, clip], s.metadata, s.descriptor, { indexTiming: true });
  noEyes.applyVisibility(.5);
  assert.equal(white.visible, false, 'removing every eye event still initializes native WhiteLine visibility');
});
if (failures.length) { console.error(JSON.stringify(failures, null, 2)); process.exitCode = 1; }
