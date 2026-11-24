/* MemberCheekClip drives the cheek through MemberCheekMixer.Process:
   ApplyEnable(true) + ApplyCheek(cheekType, intensity * input weight) for each
   active input (the last one wins), and ApplyEnable(false) when none is active,
   which keeps the floats of the last frame a clip was processed in (the 12035
   dumps hold 0.0782, 0.0321 and 0.0310 after eased-out clips). The frame clock
   says which frame that was: an advancing playback frame keeps the previous
   frame's floats, a seek with the game's rendered frame times replays them. */
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
  { kind: 'cheek', index: 1, intensity: .4, start: 25, duration: 1, weight: 0 },
];
for (const indexTiming of [true, false]) {
  const player = timeline.create(new THREE.Group(), [], { clips: [] },
    { version: 2, category: 'mv', bodySegments: [], facial: { duration: 30, events } }, { indexTiming });
  assert.equal(player.cheek(15), null, 'before any clip ResetAll keeps the cheek off at 0/0');
  near(player.cheek(15.983).intensity, .317 * .5, 'half way through the ease in');
  assert.equal(player.cheek(15.983).enabled, true);
  near(player.cheek(16.5).intensity, .317, 'full intensity between the eases');
  // No serialized mix curve: TimelineClip.get_mixOutCurve's EaseInOut(0, 1, 1, 0),
  // 1 - smoothstep(1/3) = 20/27 a third into the .6 s ease-out.
  near(player.cheek(16.983).intensity, .317 * 20 / 27, 'ease out');
  assert.equal(player.cheek(16.5).index, 0);
  assert.deepEqual(player.cheek(17.5), { index: 0, intensity: 0, enabled: false },
    'after an eased-out clip the keyword is off and the floats keep its last (faded) value');
  assert.deepEqual(player.cheek(20.25), { index: 1, intensity: .5, enabled: true });
  assert.deepEqual(player.cheek(20.75), { index: 0, intensity: .25, enabled: true }, 'the last active input overwrites the earlier one');
  assert.deepEqual(player.cheek(22), { index: 0, intensity: .25, enabled: false }, 'a clip without ease-out leaves its full value');
  assert.deepEqual(player.cheek(30), { index: 0, intensity: .25, enabled: false }, 'a muted clip never applied its values');
  assert.equal(player.warnings.length, 0, 'cheek events need no facial clip');
}
// A muted track (weight 0, set by the MV scene) never enables the cheek.
const muted = timeline.create(new THREE.Group(), [], { clips: [] },
  { version: 2, category: 'mv', bodySegments: [], facial: { duration: 30, events: [{ ...events[0], weight: 0 }] } }, { indexTiming: true });
assert.equal(muted.cheek(16.5), null);
assert.equal(muted.cheek(20), null);

// The frame clock: MemberCheekMixer.PostProcess keeps the floats of the last
// processed frame, which inside the .6 s ease-out is that frame's faded weight.
const smooth = (u) => u * u * (3 - 2 * u);
const faded = (time) => Math.fround(Math.fround(.317) * Math.fround(1 - smooth((time - 16.783333333333333) / .6)));
const clip = [{ ...events[0], start: 15.883333333333333 }];
const make = (list = clip) => timeline.create(new THREE.Group(), [], { clips: [] },
  { version: 2, category: 'mv', bodySegments: [], facial: { duration: 120, events: list } }, { indexTiming: true });
{
  // dump4: frame 12584 at 17.189 is the last rendered frame inside the clip
  // (ends 17.3833), the next one 17.394; the material record at 38.785 holds 0.07822213.
  const player = make();
  const history = [15.5, 16.7416, 16.977, 17.189, 17.394, 20, 38.6];
  const replayed = player.cheek(38.785, { advancing: false, history });
  assert.equal(replayed.enabled, false);
  assert.equal(replayed.index, 0);
  near(replayed.intensity, faded(17.189), 'a seek replays the last rendered frame inside the clip');
  assert(Math.abs(replayed.intensity - 0.07822213) < 2e-6, `the dump's 0.07822213, got ${replayed.intensity}`);
  // Frames listed after the seek time are not rendered yet; unsorted input is the caller's (scene's) concern.
  near(player.cheek(17.3, { advancing: false, history: history.concat([17.25]).sort((a, b) => a - b) }).intensity, faded(17.3),
    'inside the clip the current frame applies');
  assert.equal(player.cheek(17.25, { advancing: false, history }).enabled, true);
  // Without rendered frames a seek uses the clip's end (0 after an eased-out clip).
  assert.deepEqual(player.cheek(38.785, { advancing: false, history: [] }), { index: 0, intensity: 0, enabled: false });
  assert.deepEqual(player.cheek(38.785), { index: 0, intensity: 0, enabled: false }, 'no clock is a seek without frames');
  // A clip the history does not cover (it starts before the first listed frame) uses its end.
  assert.deepEqual(player.cheek(38.785, { advancing: false, history: [16, 20] }), { index: 0, intensity: 0, enabled: false });
  // Rendered frames that skip the whole clip never processed it: ResetAll's state stays.
  assert.equal(player.cheek(38.785, { advancing: false, history: [15, 17.5, 20] }), null);
  // Before the first clip ResetAll's 0/0.
  assert.equal(player.cheek(10, { advancing: false, history: [1, 5, 9] }), null);
}
{
  // Advancing playback frames continue from the previous frame's floats.
  const player = make();
  player.cheek(16.5, { advancing: false, history: [] });
  for (const time of [16.9, 17.2]) assert.equal(player.cheek(time, { advancing: true, history: [] }).enabled, true);
  const after = player.cheek(17.45, { advancing: true, history: [] });
  assert.equal(after.enabled, false, 'no input ran: _CHEEK_ON off');
  near(after.intensity, faded(17.2), 'the floats of the last processed frame (17.2) stay');
  near(player.cheek(30, { advancing: true, history: [] }).intensity, faded(17.2), 'until a later clip applies');
  // A seek recomputes; an advancing frame without an earlier call has no state to keep.
  assert.deepEqual(player.cheek(30, { advancing: false, history: [] }), { index: 0, intensity: 0, enabled: false });
  assert.equal(make().cheek(30, { advancing: true, history: [] }).intensity, 0, 'first call: the seek rule');
  // A rewind before the first clip is a seek: ResetAll (CommonCoreMember.ResetComponentsState).
  assert.equal(player.cheek(5, { advancing: false, history: [] }), null);
  assert.equal(player.cheek(5.1, { advancing: true, history: [] }), null, 'advancing from ResetAll keeps it');
}
{
  // Several clips: the latest processed frame wins, and at that frame the last active input.
  const list = [
    { kind: 'cheek', index: 1, intensity: .5, start: 20, duration: 1, weight: 1 },
    { kind: 'cheek', index: 0, intensity: .25, start: 20.5, duration: 1, weight: 1 },
    { kind: 'cheek', index: 1, intensity: .4, start: 25, duration: 1, weight: 0 },
  ];
  const player = make(list);
  assert.deepEqual(player.cheek(30, { advancing: false, history: [19, 20.2, 20.7, 21.6, 25.5] }),
    { index: 0, intensity: .25, enabled: false }, 'frame 20.7: input 1 overwrites input 0; the muted clip never ran');
  assert.deepEqual(player.cheek(30, { advancing: false, history: [19, 20.2, 20.4, 21.6] }),
    { index: 1, intensity: .5, enabled: false }, 'only the first clip was processed (20.4)');
}
console.log('PASS: cheek clip intensity x eased input weight, last active input, disabled without input, last processed frame');
