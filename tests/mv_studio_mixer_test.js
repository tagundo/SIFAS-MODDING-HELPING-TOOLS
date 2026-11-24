"use strict";

// LiveMixerBase`2.ProcessWithoutSeek(V2) (GL 3.12.0 0x2b39dbc / 0x2b3a224): the Live* mixers'
// input walk during playback, replayed on the scene's frame clock.
const assert = require("node:assert/strict");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-mixer.js");

const { walk, create, controller, liveTracks, playableTime } = MVStudioMixer;
const { nativeWeight, clipWeight } = MVStudioLighting;
const clip = (start, duration, values = {}) => ({ start, duration, values: { playableClass: "LiveColoringClip", ...values } });

// 12035 LED_panel_03 around 47.3 s: two clips end within one 0.19 s frame while the next two start.
// The frame step is below the shortest clip (0.216 s), so the walk looks at completedIndex + 1
// to + 3 only, and a finished input completes only when it is the next one: the clip starting at
// 47.233 s waits a frame although it already has most of the weight.
const panel = [
  clip(42.6, 2.533), clip(46.467, .566, { blendOut: .25 }), clip(46.783, .384, { blendIn: .25 }),
  clip(47.167, .216, { blendOut: .15 }), clip(47.233, .7, { blendIn: .15 }),
];
const grid = (step, last) => {
  const times = [];
  for (let time = last; time > 42; time -= step) times.unshift(Math.round(time * 1e4) / 1e4);
  return times;
};
function run(clips, times, mode = 2) {
  const state = create(), out = [];
  for (const time of times) out.push(walk(state, clips, time, (index) => clipWeight(clips[index], time), mode));
  return out;
}
const coarse = grid(.19, 47.328);
assert.deepEqual(coarse.slice(-2), [47.138, 47.328]);
const processed = run(panel, coarse);
assert.deepEqual(processed.at(-2), [2], "47.138 s: only the clip still playing");
assert.deepEqual(processed.at(-1), [3], "47.328 s: the 47.233 s clip waits");
assert(clipWeight(panel[4], 47.328) > .6);
assert.deepEqual(run(panel, [...coarse, 47.518]).at(-1), [4], "the next frame takes it (the 47.167 s clip has ended)");
// With frames 0.1 s apart the window keeps up with the clips.
assert.deepEqual(run(panel, grid(.1, 47.328)).at(-1), [3, 4], "every weighted input at 10 fps");
// A step longer than the shortest clip ("maybe skipped") walks to the last input.
assert.deepEqual(run(panel, [46.587, 47.328]).at(-1), [3, 4]);
// ProcessWithoutSeek (mode 1) and V2 agree here.
assert.deepEqual(run(panel, coarse, 1), processed);
// The playable time Timeline gives an active clip (clipIn, timeScale, extrapolation).
assert.equal(playableTime(clip(1, 2, { clipIn: .5, timeScale: 2 }), 1.5), 1.5);
assert.equal(playableTime(clip(1, 2), 3), null);
assert.equal(playableTime(clip(1, 2, { postExtrapolationMode: 1, postExtrapolationTime: 1 }), 3.5), 2);
assert.equal(playableTime(clip(1, 2, { preExtrapolationMode: 1, preExtrapolationTime: 1 }), .5), 0);

// The scene controller: live tracks are the Live*/Member* mixer tracks of a timeline with a
// StageEffect root (LiveMixerBase.IsLiveTrack); others run ProcessWithSeek (EnableSeek).
const coloring = { nativeClass: "LiveColoringTrack", label: "StageEffect/Expert/Coloring/LED_panel_03", binding: "b",
  events: [panel[4], panel[1], panel[0], panel[3], panel[2]] };
const animation = { nativeClass: "AnimationTrack", label: "StageEffect/Expert/Animation/x", events: [clip(47.233, .7)] };
const project = { tracks: [coloring, animation] };
assert.deepEqual(liveTracks(project), [coloring]);
assert.deepEqual(liveTracks({ tracks: [{ ...coloring, label: "Coloring/LED" }] }), [], "no StageEffect root: seek semantics");
assert.deepEqual(liveTracks({ tracks: [coloring, { ...coloring, muted: true }] }), [coloring]);
const mixers = controller((event, time) => clipWeight(event, time));
MVStudioMixer.activate(mixers);
mixers.update(project, 47.328, { advancing: false, history: [] });
assert(nativeWeight(panel[4], 47.328) > .6, "a seek without frame history processes every input");
mixers.update(project, 47.328, { advancing: false, history: coarse.slice(0, -1) });
assert.equal(nativeWeight(panel[4], 47.328), 0, "the replayed frames leave the 47.233 s clip out");
assert.equal(nativeWeight(panel[3], 47.328), clipWeight(panel[3], 47.328));
assert.equal(nativeWeight(panel[4], 47.33), clipWeight(panel[4], 47.33), "only the evaluated frame times are filtered");
assert.equal(nativeWeight(animation.events[0], 47.328), 1, "AnimationTrack has no LiveMixerBase");
mixers.update(project, 47.518, { advancing: true, history: [] });
assert(nativeWeight(panel[4], 47.518) > .9, "the next playback frame takes it");
assert.equal(nativeWeight(panel[4], 47.328), clipWeight(panel[4], 47.328), "earlier frames are forgotten while advancing");
mixers.update({ ...project }, 47.328, { advancing: false, history: coarse.slice(0, -1) });
assert.equal(nativeWeight(panel[4], 47.328), 0, "a new project starts new walks");
MVStudioMixer.release({});
assert.equal(nativeWeight(panel[4], 47.328), 0, "release only drops its own controller");
MVStudioMixer.release(mixers);
assert(nativeWeight(panel[4], 47.328) > .6);
console.log("LiveMixerBase ProcessWithoutSeek input walk, live track rule and frame-clock replay passed");
