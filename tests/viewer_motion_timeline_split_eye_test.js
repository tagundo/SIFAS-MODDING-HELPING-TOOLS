/* MemberEyeMixer.Process (GL 3.12.0 0x26e9878): with clip.splitScreenSetting.UseSetting
   and LiveCoreCameraManager.IsSplitScreenEnabled (SplitScreenEffect active in the
   hierarchy) the input adds setting.Weight * input weight to weightSums[setting.Index];
   otherwise clip.weight to weightSums[clip.index]. The clip's timing is shared. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const timeline = window.ViewerMotionTimeline;

function build(events, mask) {
  const root = new THREE.Group();
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'face'; face.userData.elichika_node = 2; face.morphTargetInfluences = [0, 0, 0];
  face.morphTargetDictionary = { E1: 0, E2: 1, E3: 2 }; root.add(face);
  const animations = [1, 2, 3].map((index) => new THREE.AnimationClip('eye-' + index, 1,
    [new THREE.NumberKeyframeTrack(`face.morphTargetInfluences[${index - 1}]`, [0, 1], [0, 1])]));
  const clips = animations.map((clip, index) => ({ name: clip.name, sourceHash: 'e' + index,
    sourceName: 'ch9999_LiveFacial_eye_00' + (index + 1) }));
  const facial = { duration: 8, events };
  if (mask !== undefined) facial.trackSelection = { faceDots: true, useRina: !mask, mask };
  const player = timeline.create(root, animations, { clips }, { version: 2, category: 'mv', bodySegments: [], facial },
    { indexTiming: true });
  return { player, face, events };
}

function at(model, time, split) {
  model.player.evaluatePose(time, { split });
  model.player.applyVisibility(time);
  return Array.from(model.face.morphTargetInfluences, (value) => Math.round(value * 1e6) / 1e6);
}

const split = build([
  { kind: 'eyes', index: 1, start: 0, duration: 2, weight: 1, splitIndex: 3, splitWeight: .5, timing: { easeOut: 1 } },
  { kind: 'eyes', index: 2, start: 4, duration: 1, weight: .8 },
]);
assert.deepEqual(at(split, .5, false), [1, 0, 0], 'without a split screen the clip index and weight play');
assert.deepEqual(at(split, .5, true), [0, 0, .5], 'an enabled split screen plays setting.Index at setting.Weight');
assert.deepEqual(at(split, 1.5, true), [0, 0, .25], 'the alternate input keeps the clip ease-out');
assert.deepEqual(at(split, 1.5, false), [.5, 0, 0]);
assert.deepEqual(at(split, 4.5, true), [0, .8, 0], 'clips without UseSetting ignore the split screen');
split.events[0].splitUse = false;
split.player.invalidateTiming();
assert.deepEqual(at(split, .5, true), [1, 0, 0], 'UseSetting off keeps the clip index during a split');
split.events[0].splitUse = true; split.events[0].splitWeight = .75;
split.player.invalidateTiming();
assert.deepEqual(at(split, .5, true), [0, 0, .75], 'the alternate weight follows the edited setting');

// A masked head sums per index too: the alternate index takes part in the
// winner-take-all in place of the clip index.
const masked = build([
  { kind: 'eyes', index: 1, start: 0, duration: 2, weight: 1, splitIndex: 3, splitWeight: 1 },
], true);
assert.deepEqual(at(masked, .5, false), [1, 0, 0]);
assert.deepEqual(at(masked, .5, true), [0, 0, 1], 'the masked winner is the split alternate index');

const plain = build([{ kind: 'eyes', index: 2, start: 0, duration: 2, weight: 1 }]);
assert.deepEqual(at(plain, .5, true), [0, 1, 0], 'facial inputs without a split setting are unchanged');
plain.player.evaluate(.5);
assert.deepEqual(Array.from(plain.face.morphTargetInfluences), [0, 1, 0], 'evaluate() without a context is unchanged');
console.log('PASS: MemberEyeClip.splitScreenSetting swaps index and weight while the split screen is enabled');
