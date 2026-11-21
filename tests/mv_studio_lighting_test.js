"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-lighting.js");

const { sample } = globalThis.MVStudioLighting;
const track = (name, binding, events) => ({ nativeClass: name, binding, events });
const transparent = [1, 1, 1, 0];
const opening = [0.15, 0.1847826, 0.25, 1];
const midway = [0.30, 0.3348837, 0.40, 1];
const localTint = [0.225, 0.25, 0.30, 0.9019608];
const base = (start, duration, tint, blend) => ({ start, duration, values: {
  playableClass: "LiveBaseLightClip", ambientColorType: 0, ambientMemberPosition: 1,
  ambientColor: transparent, ambientTintColor: tint, rimlightColorType: 0,
  rimlightColor: [0.5, 1, 0.5, 1], rimlightIntensity: 0.2, rimlightSharpness: 4, rimlightDirection: { x: 1, y: 2, z: 3 },
  ...blend,
}});
const local = (start, duration, easeIn) => ({ start, duration, values: {
  playableClass: "LiveMemberAmbientClip", colorSpecifiedType: 0, color: transparent, tintColor: localTint, easeIn,
}});
const project = { quality: { values: {} }, tracks: [
  track("LiveBaseLightTrack", "/EntryPoint/Live/Global/LiveBaseLightReciever",
    [base(0, 4, opening, { blendOut: 3 }), base(1, 6, midway, { blendIn: 3 })]),
  track("LiveMemberAmbientTrack", "/EntryPoint/Live/Members/Member2", [local(0, 5, 1)]),
  track("LiveRimlightTrack", "/EntryPoint/Live/Members/Member2", [{ start: 2, duration: 1, values: {
    playableClass: "LiveRimlightClip", colorSpecifiedType: 0, color: [1, 0.5, 0.5, 1],
    intensity: 0.3, sharpness: 2, direction: { x: -1, y: 3, z: 1 },
  } }]),
] };
const almost = (values, expected) => values.forEach((value, i) =>
  assert(Math.abs(value - expected[i]) < 1e-8, `${value} differs from ${expected[i]} at slot ${i}`));

let light = sample(project, 0.5);
almost(light.baseTint, opening);
almost(light.member(2).tint, [0.091875, 0.115489125, 0.1625, 0.9509804]);
light = sample(project, 1);
almost(light.member(2).ambient, transparent);
almost(light.member(2).tint, [0.03375, 0.04619565, 0.075, 0.9019608]);
light = sample(project, 2.5);
almost(light.baseTint, [0.225, 0.25983315, 0.325, 1]);
almost(light.member(2).tint, [0.050625, 0.0649582875, 0.0975, 0.9019608]);
assert.deepEqual(light.member(2).rim, { color: [0.5, 0.5, 0.25, 1], intensity: 0.5, power: 7, direction: [0, 5, 4, 0] });
light = sample(project, 5.5);
assert.equal(light.member(2).tint, null, "a native local gap restores default tint");
assert.deepEqual(light.member(2).ambient, transparent);
assert.deepEqual(light.member(1).tint, midway);

project.quality.values.base_light = false;
almost(sample(project, 1).member(2).tint, localTint);
project.quality.values.member_ambient = false;
project.quality.values.member_rim_light = false;
assert.equal(sample(project, 1).member(2), null);
console.log("Native MV base light crossfades, per-performer colors and quality gates passed");
