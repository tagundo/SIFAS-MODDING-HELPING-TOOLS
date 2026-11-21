'use strict';
const assert = require('node:assert/strict');

global.window = {};
require('../webtools/web/static/viewer-motion-timeline.js');
require('../webtools/web/static/mv-studio-lighting.js');
require('../webtools/web/static/mv-studio-post.js');

const post = window.MVStudioPost;
const first = { start: 0, duration: 2, values: { playableClass: 'LiveBloomClip', intensity: .25,
  threshold: 1, softKnee: .3, radius: 4, antiFlicker: 0, blendOut: 1 } };
const second = { start: 1, duration: 2, values: { ...first.values, intensity: .75, threshold: .5, radius: 6,
  antiFlicker: 1, blendIn: 1, blendOut: -1 } };
const track = { nativeClass: 'LiveBloomTrack', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [first, second] };
const project = { quality: { values: { posteffect: true } }, tracks: [track] };

const handoff = post.sample(project, 1.5);
assert.equal(handoff.intensity, .5);
assert.equal(handoff.threshold, .75);
assert.equal(handoff.radius, 5);
assert.equal(handoff.antiFlicker, false, 'ties retain the first native input flag');
assert.equal(post.sample(project, 1.75).antiFlicker, true);
assert.equal(post.sample(project, 3), null);
track.muted = true;
assert.equal(post.sample(project, 1.5), null);
track.muted = false;
project.quality.values.posteffect = false;
assert.equal(post.sample(project, 1.5), null);

const setup = post.plan(1280, 720, { threshold: 1, softKnee: .3, radius: 4 });
assert.deepEqual(setup.reduced, [747,420]);
assert.deepEqual(setup.prefilter, [373,210]);
assert.deepEqual(setup.levels, [[186,105],[93,52],[46,26]]);
assert.equal(setup.threshold, 1);
assert(Math.abs(setup.curve[0] - .69999) < 1e-9);
assert(Math.abs(setup.scale - 1.214246) < 1e-6);
console.log('MV Studio native Bloom mixer, quality gate and pyramid passed');
