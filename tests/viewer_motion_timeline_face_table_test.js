/* Lip-sync and eye indices resolve through the face's own MemberFaceData tables
 * (rig memberHead.facialTables), as LiveMemberLipSync / LiveMemberEyeAnimation do:
 * the first row with the index plays its clip; a missing row or a null clip adds
 * nothing (no zero pose), and the Live enums bound the indices. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const factory = window.ViewerMotionTimeline;
const failures = [];
function check(name, fn) { try { fn(); console.log('PASS: ' + name); } catch (error) { failures.push(name); console.error('FAIL: ' + name + ': ' + (error.stack || error)); } }
function close(actual, expected, label) { assert(Math.abs(actual - expected) < 1e-6, `${label}: ${actual} != ${expected}`); }

const FACE = 'facebundlehash';
function row(index, clip, extra = {}) {
  return Object.assign({ index, customIndex: 0, summary: index }, clip ? { sourceHash: FACE, sourceName: clip } : {}, extra);
}
// Morph channels: 0 = mouth_facial_001 (A), 1 = mouth_facial_004 (E), 2 = eye_facial_001.
function setup(options = {}) {
  const root = new THREE.Group(), bone = new THREE.Bone(); bone.name = 'hips'; root.add(bone);
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'face'; face.userData.elichika_node = 2; face.morphTargetInfluences = [.1, .2, .3]; face.morphTargetDictionary = { A: 0, E: 1, eye: 2 }; root.add(face);
  const body = new THREE.AnimationClip('body', 9, [new THREE.VectorKeyframeTrack('hips.position', [0, 9], [0, 0, 0, 9, 0, 0])]);
  // LiveFacial clips are poses: each key holds the original endpoint.
  const pose = (name, index, value) => new THREE.AnimationClip(name, 1, [new THREE.NumberKeyframeTrack(`face.morphTargetInfluences[${index}]`, [0, 1], [value, value])]);
  const animations = [body, pose('mouth-001', 0, 1), pose('mouth-004', 1, 1), pose('eye-001', 2, 1), pose('eye-007', 2, .5)];
  const clips = [{ name: 'body', sourceHash: 'bodyhash', sourceName: 'body-source' },
    { name: 'mouth-001', sourceHash: FACE, sourceName: 'ch0212_LiveFacial_mouth_001' },
    { name: 'mouth-004', sourceHash: FACE, sourceName: 'ch0212_LiveFacial_mouth_004' },
    { name: 'eye-001', sourceHash: FACE, sourceName: 'ch0212_LiveFacial_eye_001' },
    { name: 'eye-007', sourceHash: FACE, sourceName: 'ch0212_LiveFacial_eye_007' }].filter(entry => !(options.unloaded || []).includes(entry.name));
  const metadata = { clips, memberHead: { faceDots: false, facialTables: options.tables || {
    mouth: [row(1, 'ch0212_LiveFacial_mouth_001'), row(4, 'ch0212_LiveFacial_mouth_004'),
      row(13, 'ch0212_LiveFacial_mouth_004', { customIndex: 4, summary: 10013 }), row(14, null, { summary: 10014 }),
      row(13, 'ch0212_LiveFacial_mouth_001', { summary: 10013 })],
    eyes: [row(1, 'ch0212_LiveFacial_eye_001'), row(7, 'ch0212_LiveFacial_eye_007'), row(20, null)] } },
    expressionCatalog: { rawChannels: [
      { node: 2, index: 0, name: 'MouthBlendShape.mouth_facial_001', group: 'mouth' },
      { node: 2, index: 1, name: 'MouthBlendShape.mouth_facial_004', group: 'mouth' },
      { node: 2, index: 2, name: 'EyeBlendShape.eye_facial_001', group: 'eyes' }] } };
  const descriptor = { version: 2, category: options.category || 'mv', bodySegments: [{ sourceHash: 'bodyhash', sourceName: 'body-source', start: 0, duration: 9, clipIn: 0, timeScale: 1 }],
    facialClips: options.facialClips || [], facial: { duration: 9, events: options.events || [] } };
  const player = factory.create(root, animations.filter(clip => !(options.unloaded || []).includes(clip.name)), metadata, descriptor);
  function frame(time) { face.morphTargetInfluences.splice(0, 3, .1, .2, .3); player.evaluate(time); return face.morphTargetInfluences.slice(); }
  return { player, frame };
}
const mouth = (index, weight, start = 0) => ({ kind: 'mouth', index, start, duration: 1, weight });
const eyes = (index, weight, start = 0) => ({ kind: 'eyes', index, start, duration: 1, weight });

check('index 13 plays the row clip (mouth_004), not a mouth_013 shape or the first-row mouth_001 duplicate', () => {
  const s = setup({ events: [mouth(13, .358)] }), m = s.frame(.5);
  close(m[1], .2 * (1 - .358) + .358, 'E follows the alias clip at the clip weight');
  close(m[0], .1, 'A is untouched: no zero pose for every other mouth channel');
  assert.equal(s.player.warnings.length, 0);
});
check('an index with a null clip adds nothing while a co-active clip keeps its weight', () => {
  const s = setup({ events: [mouth(4, .5), mouth(14, .5)] }), m = s.frame(.5);
  close(m[1], .2 * .5 + .5, 'E as if index 14 were absent (remainder stays authored)');
  close(m[0], .1, 'A untouched');
  assert.equal(s.player.warnings.length, 0, 'an original null clip is not a warning');
});
check('an index absent from the face table adds nothing and warns once', () => {
  const s = setup({ events: [mouth(16, .7), mouth(16, .7, 2), mouth(17, .4, 4)] });
  assert.deepStrictEqual(s.frame(.5), [.1, .2, .3]);
  assert.deepStrictEqual(s.frame(4.5), [.1, .2, .3]);
  assert.equal(s.player.warnings.filter(text => /not in this face's animation table/.test(text)).length, 1);
});
check('eye rows: null clip adds nothing, Live enum ids outside MemberEyeClip.AnimationIndex add nothing in an MV', () => {
  const s = setup({ events: [eyes(1, .25), eyes(20, .5), eyes(7, .5, 2)] });
  close(s.frame(.5)[2], .3 * .75 + .25, 'eye 1 alone; eye 20 (null clip) adds nothing');
  close(s.frame(2.5)[2], .3, 'eye 7 is a gaze direction, not an eye-animation id');
  const navi = setup({ category: 'voice', events: [eyes(7, .5)] });
  close(navi.frame(.5)[2], .3 * .5 + .25, 'the Live enum gate applies to MV live heads only');
});
check("a motion's explicit table for a kind wins over the face table", () => {
  const s = setup({ facialClips: [{ kind: 'mouth', index: 13, sourceHash: FACE, sourceName: 'ch0212_LiveFacial_mouth_001' }], events: [mouth(13, 1), mouth(1, 1, 2)] });
  const first = s.frame(.5); close(first[0], 1, 'explicit alias to mouth_001'); close(first[1], .2, 'face table row ignored');
  close(s.frame(2.5)[0], 1, 'the explicit table keeps the earlier regex fallback for its other indices');
});
check('an unloaded row clip falls back to the shape the row names, never a zero pose', () => {
  const s = setup({ unloaded: ['mouth-004'], events: [mouth(13, .5)] }), m = s.frame(.5);
  close(m[1], .2 * .5 + .5, 'mouth_facial_004 one-hot pose for row 13 -> mouth_004');
  close(m[0], .1 * .5, 'the one-hot pose of a resolved shape sets the other mouth channels');
});
check('without a face table an index with no shape of its own adds nothing', () => {
  const s = setup({ tables: {}, events: [mouth(4, .5), mouth(13, .5)] }), m = s.frame(.5);
  close(m[1], .2 * .5 + .5, 'index 4 resolves by name; index 13 has no mouth_013 clip or shape');
  close(m[0], .1, 'A keeps its authored value: no zero pose');
  assert(s.player.warnings.some(text => /unavailable/.test(text)), 'the unresolved shape still warns');
});
check('gaze directions resolve through the face eye table (LiveMemberEyeContact gets animationTableEye)', () => {
  function gazeSetup(row8) {
    const root = new THREE.Group(), eye = new THREE.Bone(); eye.name = 'LeftEye1'; root.add(eye);
    const clip = new THREE.AnimationClip('direction', 1, [new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1], [0, 0, 0, 0, .2, 0])]);
    const metadata = { clips: [{ name: 'direction', sourceHash: FACE, sourceName: 'ch0212_eye_direction_bank' }],
      memberHead: { facialTables: { eyes: [row8] } } };
    const descriptor = { version: 2, category: 'mv', bodySegments: [], facialClips: [],
      facial: { duration: 1, events: [{ kind: 'gaze', target: 31, start: 0, duration: 1, weight: .5 }] } };
    const player = factory.create(root, [clip], metadata, descriptor); player.evaluate(.5);
    return { eye, player };
  }
  close(gazeSetup(row(8, 'ch0212_eye_direction_bank')).eye.position.y, .1, 'target31 -> direction 8 row clip, found by identity not by name');
  const empty = gazeSetup(row(8, null));
  close(empty.eye.position.y, 0, 'a null direction row has no pose');
  assert(empty.player.warnings.some(text => /gaze poses are unavailable/.test(text)));
});
if (failures.length) { console.error(failures.length + ' face-table checks failed'); process.exit(1); }
console.log('PASS: face animation tables resolve lip-sync and eye indices like the live head');
