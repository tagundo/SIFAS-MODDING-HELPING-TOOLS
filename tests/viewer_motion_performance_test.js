/* Compare one authored playhead across dense body/facial/gaze tracks. Optional
 * baseline executes the prior engine on the same independently built rig. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm'), { performance } = require('perf_hooks');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const current = path.resolve(__dirname, '../webtools/web/static/viewer-motion-timeline.js');
function engine(file) { const window = { THREE }; vm.runInNewContext(fs.readFileSync(file, 'utf8'), { window }); return window.ViewerMotionTimeline; }
function setup(factory) {
  const root = new THREE.Group(), bones = [], clips = [], metadata = { clips: [], expressionCatalog: { rawChannels: [], presets: [] } };
  for (let i = 0; i < 120; i++) { const b = new THREE.Bone(); b.name = 'bone' + i; b.userData.elichika_node = i + 1; (i ? bones[i - 1] : root).add(b); bones.push(b); }
  const head = new THREE.Bone(); head.name = 'Eye_Root'; root.add(head);
  const left = new THREE.Bone(); left.name = 'LeftEye1'; left.userData.elichika_node = 201; head.add(left);
  const right = new THREE.Bone(); right.name = 'RightEye1'; right.userData.elichika_node = 202; head.add(right);
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial()); face.name = 'face'; face.userData.elichika_node = 200;
  face.morphTargetInfluences = [.2, .4]; face.morphTargetDictionary = { A: 0, E: 1 }; root.add(face);
  metadata.expressionCatalog.rawChannels = [
    { node: 200, index: 0, name: 'MouthBlendShape.mouth_facial_001', group: 'mouth' },
    { node: 200, index: 1, name: 'MouthBlendShape.mouth_facial_004', group: 'mouth' }];
  const descriptor = { category: 'mv', targetCharacter: 1, bodySegments: [], facialClips: [], facial: { events: [] } };
  let timingReads = 0;
  function timed(segment, spec) { Object.defineProperty(segment, 'timing', { configurable: true, get() { timingReads++; return spec; } }); return segment; }
  for (let c = 0; c < 4; c++) {
    const tracks = [];
    for (let i = 0; i < bones.length; i++) {
      const q0 = new THREE.Quaternion().setFromEuler(new THREE.Euler(.01 * c, .02 * i, .03 * c));
      const q1 = new THREE.Quaternion().setFromEuler(new THREE.Euler(.02 * c, .01 * i, -.03 * c));
      tracks.push(new THREE.VectorKeyframeTrack('bone' + i + '.position', [0, 20], [i * .01, c, 0, i * .01 + .2, c + .5, .1]));
      tracks.push(new THREE.QuaternionKeyframeTrack('bone' + i + '.quaternion', [0, 20], q0.toArray().concat(q1.toArray())));
      tracks.push(new THREE.VectorKeyframeTrack('bone' + i + '.scale', [0, 20], [1, 1, 1, 1.02, 1.03, 1.01]));
    }
    const clip = new THREE.AnimationClip('body' + c, 20, tracks); clips.push(clip);
    metadata.clips.push({ name: clip.name, sourceHash: 'body-hash' + c, sourceName: 'body-source' + c });
    descriptor.bodySegments.push(timed({ sourceHash: 'body-hash' + c, sourceName: 'body-source' + c, start: c * 2, duration: 12, clipIn: .25, timeScale: .8 + c * .1 },
      { easeIn: .5, easeOut: .75, preMode: 2, preTime: .2, postMode: 3, postTime: .3 }));
  }
  const mouth = new THREE.AnimationClip('mouth', 1, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences', [0, 1], [1, 0, 1, 0])]); clips.push(mouth);
  metadata.clips.push({ name: 'mouth', sourceHash: 'mouth-hash', sourceName: 'mouth-source' });
  descriptor.facialClips.push({ kind: 'mouth', index: 13, sourceHash: 'mouth-hash', sourceName: 'mouth-source' });
  for (let i = 0; i < 180; i++) descriptor.facial.events.push(timed({ kind: 'mouth', index: i % 2 ? 4 : 13, start: i * .1, duration: .15, weight: .25 + i % 3 * .25 }, { easeIn: .025, easeOut: .025 }));
  for (let d = 6; d <= 11; d++) {
    const gaze = new THREE.AnimationClip('gaze' + d, 1, [new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1], [0, 0, 0, (d - 8) * .02, .01 * d, 0]), new THREE.VectorKeyframeTrack('RightEye1.position', [0, 1], [0, 0, 0, (d - 8) * .02, .01 * d, 0])]);
    clips.push(gaze); metadata.clips.push({ name: gaze.name, sourceHash: 'gaze-hash' + d, sourceName: 'gaze-source' + d });
    descriptor.facialClips.push({ kind: 'eyes', index: d, sourceHash: 'gaze-hash' + d, sourceName: 'gaze-source' + d });
  }
  descriptor.facial.events.push(timed({ kind: 'gaze', target: 21, start: 0, duration: 20, weight: .5 }, {}));
  descriptor.facial.events.push(timed({ kind: 'gaze', target: 31, start: 0, duration: 20, weight: .25 }, {}));
  const player = factory.create(root, clips, metadata, descriptor, { getGazeContext: () => ({ camera: [2, 1, 3] }) });
  const owned = () => player.animatedProperties(lastTime);
  let lastTime = 0;
  function sample(time) { lastTime = time; bones.forEach(b => { b.position.set(0, 0, 0); b.quaternion.set(0, 0, 0, 1); b.scale.set(1, 1, 1); }); left.position.set(0, 0, 0); right.position.set(0, 0, 0); face.morphTargetInfluences.splice(0, 2, .2, .4); player.evaluate(time); owned(); player.applyVisibility(time); }
  function snapshot(time) { sample(time); return bones.flatMap(b => b.position.toArray().concat(b.quaternion.toArray(), b.scale.toArray())).concat(left.position.toArray(), right.position.toArray(), face.morphTargetInfluences); }
  return { player, snapshot, sample, owned, timingReads: () => timingReads };
}
const factory = engine(current), next = setup(factory), previous = process.env.VIEWER_TIMELINE_BASELINE ? setup(engine(process.env.VIEWER_TIMELINE_BASELINE)) : null;
const times = [-.1, 0, .03, .1, .5, 1.25, 2.1, 4.5, 8.9, 13.5, 18, 20, 7.3, 0, 3.7];
for (const t of times) {
  const actual = next.snapshot(t); assert(actual.every(Number.isFinite));
  if (previous) { const expected = previous.snapshot(t); assert.equal(actual.length, expected.length); for (let i = 0; i < actual.length; i++) assert(Math.abs(actual[i] - expected[i]) < 1e-11, `playhead ${t}, component ${i}: ${actual[i]} vs ${expected[i]}`); assert.deepStrictEqual(JSON.parse(JSON.stringify(next.owned())), JSON.parse(JSON.stringify(previous.owned()))); }
}
function bench(s) { for (let i = 0; i < 100; i++) s.sample(i % 600 / 30); const reads = s.timingReads(), start = performance.now(); for (let i = 0; i < 1000; i++) s.sample(i % 600 / 30); return { milliseconds: performance.now() - start, frames: 1000, timingReads: s.timingReads() - reads }; }
const before = previous ? bench(previous) : null, after = bench(next);
if (before) assert(after.timingReads < before.timingReads / 4, 'Shared body/facial segment timing is sampled once per playhead, not once per bound property');
console.log(JSON.stringify({ status: 'PASS', scope: 'CPU-only timeline sampling on identical 120-bone/1440-track original-style body, facial and moving-camera gaze playhead; not device FPS', comparisons: times.length, before, after, speedup: before && before.milliseconds / after.milliseconds }));
