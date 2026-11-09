/* Original Timeline scheduling must compose body segments and facial aliases. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const timeline = window.ViewerMotionTimeline;
const root = new THREE.Group();
const bone = new THREE.Bone(); bone.name = 'hips'; root.add(bone);
const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
face.name = 'face'; face.userData.elichika_node = 2; face.morphTargetInfluences = [0, 0]; face.morphTargetDictionary = { A: 0, E: 1 }; root.add(face);
const first = new THREE.AnimationClip('body-1', 2, [new THREE.VectorKeyframeTrack('hips.position', [0, 2], [0, 0, 0, 2, 0, 0])]);
const second = new THREE.AnimationClip('body-2', 2, [new THREE.VectorKeyframeTrack('hips.position', [0, 2], [10, 0, 0, 12, 0, 0])]);
const mouth = new THREE.AnimationClip('actual-mouth-e', 1, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences[1]', [0, 1], [0, 1])]);
const clips = [{ name: first.name, sourceHash: 'one', sourceName: 'one' }, { name: second.name, sourceHash: 'two', sourceName: 'two' },
  { name: mouth.name, sourceHash: 'mouth', sourceName: 'ch0201_LiveFacial_mouth_004' }];
const descriptor = { version: 2, category: 'mv', bodySegments: [
  { sourceHash: 'one', sourceName: 'one', start: 0, duration: 2, clipIn: .5, timeScale: .5 },
  { sourceHash: 'two', sourceName: 'two', start: 1, duration: 2, clipIn: 0, timeScale: 1 }],
  facialClips: [{ kind: 'mouth', index: 13, customIndex: 4, sourceHash: 'mouth', sourceName: clips[2].sourceName }],
  facial: { duration: 3, events: [{ kind: 'mouth', index: 13, start: .5, duration: 1, weight: .8 }] } };
const player = timeline.create(root, [first, second, mouth], { clips }, descriptor);
assert.equal(player.compatibleSegments, 2);
player.evaluate(.5); assert(Math.abs(bone.position.x - .75) < 1e-6);
assert(Math.abs(face.morphTargetInfluences[1] - .8) < 1e-6, 'index13 resolves the original alias to mouth004');
player.evaluate(1.5); assert(Math.abs(bone.position.x - 5.875) < 1e-6, 'overlapping body tracks blend on one playhead');
player.evaluate(2.5); assert(Math.abs(bone.position.x - 11.5) < 1e-6);
assert.equal(timeline.weight({ start: 1, duration: 2 }, .5), 0);
assert.equal(timeline.weight({ start: 1, duration: 2, timing: { easeIn: 1 } }, 1.5), .5);
assert.equal(timeline.weight({ start: 1, duration: 2, timing: { easeOut: 1 } }, 2.5), .5);
assert.equal(player.duration, 3);
assert.equal(player.warnings.length, 0);
console.log('PASS: timeline offsets, speed, overlapping body blending, original facial aliases, fades');
