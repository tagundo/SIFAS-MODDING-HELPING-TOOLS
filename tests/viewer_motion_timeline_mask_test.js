/* A masked head without Rina tracks plays one facial index at a time.
   LiveMemberAnimationMask.ProcessFrameMask / UpdateAnimationMask: each mixer sums
   its inputs per index, ignores sums below minRateToActive 0.51 and gives the last
   qualifying index weight 1 and every other input 0. Without the mask the
   default facial blend is unchanged. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const timeline = window.ViewerMotionTimeline;

function build(mask) {
  const root = new THREE.Group();
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'face'; face.userData.elichika_node = 2; face.morphTargetInfluences = [0, 0, 0];
  face.morphTargetDictionary = { A: 0, I: 1, U: 2 }; root.add(face);
  const animations = [1, 2, 3].map((index) => new THREE.AnimationClip('mouth-' + index, 1,
    [new THREE.NumberKeyframeTrack(`face.morphTargetInfluences[${index - 1}]`, [0, 1], [0, 1])]));
  const clips = animations.map((clip, index) => ({ name: clip.name, sourceHash: 'm' + index,
    sourceName: 'ch9999_LiveFacial_mouth_00' + (index + 1) }));
  const events = [
    { kind: 'mouth', index: 1, start: 0, duration: 2, weight: 1, timing: { easeOut: 1 } },
    { kind: 'mouth', index: 2, start: 1, duration: 2, weight: 1, timing: { easeIn: 1 } },
    // Two inputs of one index: their summed rate qualifies although neither does alone.
    { kind: 'mouth', index: 3, start: 4, duration: 1, weight: .3 },
    { kind: 'mouth', index: 3, start: 4, duration: 1, weight: .3 },
    // A lone input below minRateToActive leaves the default face.
    { kind: 'mouth', index: 1, start: 6, duration: 1, weight: .5 },
  ];
  const descriptor = { version: 2, category: 'mv', bodySegments: [],
    facial: { duration: 8, events, trackSelection: { faceDots: true, useRina: !mask, mask } } };
  const player = timeline.create(root, animations, { clips }, descriptor, { indexTiming: true });
  return { player, face };
}

function at(build, time) {
  build.player.evaluate(time);
  return Array.from(build.face.morphTargetInfluences, (value) => Math.round(value * 1e6) / 1e6);
}

const masked = build(true);
assert.deepEqual(at(masked, .5), [1, 0, 0], 'one full input before the cross-fade');
assert.deepEqual(at(masked, 1.25), [1, 0, 0], 'rate .75 of index 1 wins at full weight, index 2 (.25) is reset');
assert.deepEqual(at(masked, 1.5), [0, 0, 0], 'neither .5 reaches .51: every input stays 0');
assert.deepEqual(at(masked, 1.75), [0, 1, 0], 'index 2 wins once its rate reaches .51');
assert.deepEqual(at(masked, 4.5), [0, 0, 1], 'per-index sums (.3 + .3) qualify, and the index plays at weight 1');
assert.deepEqual(at(masked, 6.5), [0, 0, 0], 'a .5 input never activates a masked index');

const blended = build(false);
// The events carry no mix curves: Timeline's default EaseInOut gives
// 1 - smoothstep(.25) = .84375 and smoothstep(.25) = .15625.
assert.deepEqual(at(blended, 1.25), [.84375, .15625, 0], 'a Rina-track head keeps the default blend in an MV');
assert.deepEqual(at(blended, 4.5), [0, 0, .6]);
assert.deepEqual(at(blended, 6.5), [.5, 0, 0]);
console.log('PASS: masked-head facial winner-take-all (0.51), default blend without the mask');
