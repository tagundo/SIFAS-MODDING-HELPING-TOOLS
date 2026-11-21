"use strict";

const assert = require("node:assert/strict");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-coloring.js");

const increasing = [{ time: 0, value: 0 }, { time: 1, value: 1 }];
const decreasing = [{ time: 0, value: 1 }, { time: 1, value: 0 }];
const track = { events: [
  { start: 0, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [1, 2, 3, 0],
    blendOut: 1, mixOut: decreasing, shift: 3, speed: 2, clipIn: .25, timeScale: 2 } },
  { start: 1, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [3, 2, 1, 1],
    blendIn: 1, mixIn: increasing, shift: 12, speed: 3 } }
] };
assert.deepEqual(MVStudioStageColoring.sample(track, 0).tint, [1, 2, 3, 0]);
assert.deepEqual(MVStudioStageColoring.sample(track, 1.5), {
  tint: [2, 2, 2, .5], shift: 3, speed: 2, selfTime: 3.25
});
assert.equal(MVStudioStageColoring.sample(track, 1.75).shift, 12);
assert.equal(MVStudioStageColoring.sample(track, 3).tint[3], 0);

const native = new Uint8Array([16, 255, 128, 129, 26, 128, 0, 129, 36, 255, 8, 255, 56, 255, 8, 129]);
const palette = new Uint8Array(native.length);
MVStudioStageColoring.customize(native, palette, { 1: [1, 0, .5, 1], 2: [1, .5, 0, 1], 3: [0, 0, 0, 1] });
assert.deepEqual([...palette], [255, 0, 128, 255, 128, 64, 0, 255, 36, 255, 8, 255, 56, 255, 8, 129]);
console.log("Native stage coloring: RGBA blend, first winner at tie, clip time and lossless palette masks.");
