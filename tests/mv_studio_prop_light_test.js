"use strict";

const assert = require("node:assert/strict");

global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
const {create} = (require("../webtools/web/static/mv-studio-prop-light.js"), global.MVStudioPropLight);

const member = "/EntryPoint/Live/Members/ske_so2028/Member1";
const binding = member + "/Model/Reference/Move/RightHand/chp0001";
const otherProp = member + "/Model/Reference/Move/RightHand/chp0002";
const rgba = ([r, g, b, a]) => ({r, g, b, a});
const color = rgba([.2, .4, .6, .8]);
const tint = rgba([.2, .4, 1.4, 1]);
const colorTwo = rgba([.6, .4, .2, 1]);
const tintTwo = rgba([.6, .8, 1.8, 1]);
const close = (actual, values) => {
  assert.equal(actual.length, values.length);
  for (const [index, value] of values.entries()) assert(Math.abs(actual[index] - value) < 1e-9);
};
function clip(playableClass, start, duration, values) {
  return {start, duration, values: {playableClass, colorSpecifiedType: 0, memberPosition: 1, ...values}};
}

const ambient = {binding, nativeClass: "LivePropAmbientTrack", events: [
  clip("LivePropAmbientClip", 0, 4, {color, tintColor: tint, easeIn: 2, blendOut: 2}),
  clip("LivePropAmbientClip", 2, 2, {color: colorTwo, tintColor: tintTwo, blendIn: 2}),
]};
const rim = {binding, nativeClass: "LivePropRimlightTrack", events: [
  clip("LivePropRimlightClip", 0, 4, {color, intensity: .2, sharpness: 5,
    direction: {x: -2, y: 1, z: 4}, blendOut: 2}),
  clip("LivePropRimlightClip", 2, 2, {color: colorTwo, intensity: .6, sharpness: 9,
    direction: {x: 4, y: 3, z: 2}, blendIn: 2}),
]};
const project = {quality: {values: {}}, tracks: [
  {...ambient, binding: otherProp},
  {...rim, binding: member + "/Model/Reference/Move/LeftHand/chp0001"},
  {...ambient, nativeClass: "LiveMemberAmbientTrack"},
  ambient, rim,
]};

assert.equal(create(binding, 2), null);
assert.equal(create(binding + "/child", 1), null);
assert.equal(create(otherProp, "1"), null);

const light = create(binding, 1);
assert.equal(light.sample(1), null);
light.setProject(project);

const eased = light.sample(1);
close(eased.ambient, [.1, .2, .3, .4]);
close(eased.tint, [.6, .7, 1.2, 1]);

const blended = light.sample(3);
close(blended.ambient, [.4, .4, .4, .9]);
close(blended.tint, [.4, .6, 1.6, 1]);
close(blended.rim.color, [.4, .4, .4, .9]);
close(blended.rim.direction, [1, 2, 3, 0]);
assert.equal(blended.rim.intensity, .4);
assert.equal(blended.rim.power, 8);

project.quality.values.prop_ambient = false;
assert.deepEqual(light.sample(3), {rim: blended.rim});
project.quality.values.prop_ambient = true;
project.quality.values.prop_rim_light = false;
assert.deepEqual(light.sample(3), {...blended, rim: {intensity: 0}});
project.quality.values.prop_rim_light = true;

rim.muted = true;
assert.deepEqual(light.sample(3), {...blended, rim: {intensity: 0}});
rim.muted = false;
ambient.muted = true;
assert.deepEqual(light.sample(3), {rim: blended.rim});
ambient.muted = false;

assert.deepEqual(light.sample(4), {rim: {intensity: 0}});
assert.deepEqual(light.sample(3), blended);

rim.events[1].start = 4;
assert.equal(light.sample(3).rim.intensity, .1);
rim.events[1].start = 2;
assert.deepEqual(light.sample(3), blended);

// A replaced project must use its own native binding, tracks and quality.
light.setProject({...project, tracks: [ambient, {...rim, binding: otherProp}]});
assert.deepEqual(light.sample(3), {...blended, rim: {intensity: 0}});
light.setProject({...project, tracks: [{...ambient}, ambient, rim]});
assert.deepEqual(light.sample(3), {rim: blended.rim});

const themed = {binding, nativeClass: "LivePropAmbientTrack", events: [
  clip("LivePropAmbientClip", 0, 1, {color, tintColor: tint, colorSpecifiedType: 1, memberPosition: 2}),
]};
light.setProject({tracks: [themed], performers: [{position: 2, themeColor: [.5, 1, .25, .5]}]});
close(light.sample(0).ambient, [.1, .4, .15, .4]);
close(light.sample(0).tint, [.2, .4, 1.4, 1]);
assert.equal(light.sample(NaN), null);

console.log("MV Studio prop lighting checks passed.");
