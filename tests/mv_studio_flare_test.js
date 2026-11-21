/* Authored camera flare mixer and the live Uber shader's uniform contract. */
'use strict';
const assert = require('node:assert/strict');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
require('../webtools/web/static/mv-studio-lighting.js');
require('../webtools/web/static/mv-studio-flare.js');
const { sample, uniforms, apply } = global.MVStudioFlare;
const close = (a, b) => assert(Math.abs(a - b) < 1e-6, `${a} != ${b}`);
const event = (start, extra) => ({ start, duration: 2, values: {
  playableClass: 'LiveFlareClip', center: { x: .8, y: 1.4 }, colorSpecifiedType: 0,
  color: { r: .4, g: .7, b: 1, a: 1 }, memberPosition: 1, intensity: .2, smoothness: 2,
  roundness: .4, rounded: 1, ...extra,
} });
const track = (suffix, events) => ({ nativeClass: 'LiveFlareTrack',
  binding: `/EntryPoint/Live/Cameras/${suffix}`, events });
const one = track('MainCamera/Flares/Flare1', [event(0, { easeIn: 1 })]);
const two = track('SubCamera1/Flares/Flare2', [event(0)]);
const three = track('MainCamera/Flares/Flare3', [event(1), event(1, { rounded: 0, colorSpecifiedType: 1 })]);
const project = { quality: { values: { posteffect: true } }, tracks: [one, two, three],
  performers: [{ position: 1, themeColor: [.5, 1, .5, 1] }] };
const before = sample(project, .5);
assert.deepEqual(before.slice(1), [null, null]);
close(before[0].center[0], .4);
close(before[0].center[1], .7);
close(before[0].color[0], .2);
close(before[0].settings[0], .3);
close(before[0].settings[1], 5);
close(before[0].settings[2], 5);
assert.equal(before[0].settings[3], 1);
const overlapping = sample(project, 1.5)[2];
close(overlapping.color[0], .6);
close(overlapping.center[1], 2.8);
assert.equal(overlapping.settings[3], 1, 'the first equally weighted input supplies rounded');
assert.equal(sample(project, 3), null, 'end of the clip does not carry over');
project.tracks.push(track('MainCamera/Flares/Flare1', [event(0)]));
assert.equal(sample(project, .5), null, 'duplicate native output bindings are ambiguous');
project.tracks.pop();
project.quality.values.posteffect = false;
assert.equal(sample(project, 1.5), null);
const live = uniforms(THREE);
apply(THREE, live, before, 1920, 1080);
close(live.mvFlareAspect.value, 16 / 9);
close(live.mvFlareCenter.value[0].y, .7);
close(live.mvFlareSettings.value[0].x, .3);
apply(THREE, live, null, 1080, 1920);
assert.deepEqual(live.mvFlareSettings.value[0].toArray(), [0, 1, 1, 0]);
console.log('Native flare target selection, timing, accumulated values, aspect and uniform reset passed.');
