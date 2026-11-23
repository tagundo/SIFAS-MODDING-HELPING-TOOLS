/* MemberCheekClip drives the cheek through MemberCheekMixer.Process:
   ApplyEnable(true) + ApplyCheek(cheekType, intensity * input weight) for each
   active input (the last one wins), and ApplyEnable(false) when none is active. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const timeline = window.ViewerMotionTimeline;

const near = (actual, expected, message) => assert(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);
// 12035 Member1 Cheek clip 1: start 15.883, 1.5 s, ease in .2, ease out .6, intensity .317, cheekType 0.
const events = [
  { kind: 'cheek', index: 0, intensity: .317, start: 15.883, duration: 1.5, weight: 1, timing: { easeIn: .2, easeOut: .6 } },
  { kind: 'cheek', index: 1, intensity: .5, start: 20, duration: 1, weight: 1 },
  { kind: 'cheek', index: 0, intensity: .25, start: 20.5, duration: 1, weight: 1 },
];
for (const indexTiming of [true, false]) {
  const player = timeline.create(new THREE.Group(), [], { clips: [] },
    { version: 2, category: 'mv', bodySegments: [], facial: { duration: 30, events } }, { indexTiming });
  assert.equal(player.cheek(15), null, 'no active input disables the cheek');
  near(player.cheek(15.983).intensity, .317 * .5, 'half way through the ease in');
  near(player.cheek(16.5).intensity, .317, 'full intensity between the eases');
  near(player.cheek(16.983).intensity, .317 * (.4 / .6), 'ease out');
  assert.equal(player.cheek(16.5).index, 0);
  assert.equal(player.cheek(17.5), null, 'after the clip the keyword is off again');
  assert.deepEqual(player.cheek(20.25), { index: 1, intensity: .5 });
  assert.deepEqual(player.cheek(20.75), { index: 0, intensity: .25 }, 'the last active input overwrites the earlier one');
  assert.equal(player.cheek(22), null);
  assert.equal(player.warnings.length, 0, 'cheek events need no facial clip');
}
// A muted track (weight 0, set by the MV scene) never enables the cheek.
const muted = timeline.create(new THREE.Group(), [], { clips: [] },
  { version: 2, category: 'mv', bodySegments: [], facial: { duration: 30, events: [{ ...events[0], weight: 0 }] } }, { indexTiming: true });
assert.equal(muted.cheek(16.5), null);
console.log('PASS: cheek clip intensity x eased input weight, last active input, disabled without input');
