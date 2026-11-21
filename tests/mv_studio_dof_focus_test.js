"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-dof-focus.js");
require("../webtools/web/static/mv-studio-dof.js");

const { sample } = globalThis.MVStudioDofFocus;
const binding = "/EntryPoint/Live/Cameras/MainCamera";
const event = (start, duration, values) => ({ start, duration, values: {
  playableClass: "LiveDepthOfFieldClip", focusDistance: 1, aperture: 2, focalLength: 15, kernelSize: 0, ...values,
} });
const member = event(0, 3, {
  useMemberDistance: 1, memberPosition: 2, bodyPart: 3, cameraAutoDistanceMode: 0, useCameraFov: 1, blendOut: 2,
});
const fixed = event(1, 2, { focusDistance: 2, aperture: 0, focalLength: 30, kernelSize: 2, antiAura: 1, blendIn: 2 });
const track = { binding, nativeClass: "LiveDepthOfFieldTrack", events: [member, fixed] };
const project = { quality: { values: { posteffect: true } }, tracks: [track] };
const memberDistance = (slot, part) => {
  assert.equal(slot, 2);
  assert.equal(part, 3);
  return 3.1;
};
const focalFromFov = 0.012 / Math.tan(Math.PI / 12);
const exact = (actual, expected) => assert(Math.abs(actual - expected) < 1e-7, String(actual));

let value = sample(project, 0.5, 30, memberDistance);
exact(value.distance, 3);
exact(value.focalLength, focalFromFov);
assert.equal(value.aperture, 2);
assert.equal(value.kernelSize, 0);
value = sample(project, 2, 30, memberDistance);
exact(value.distance, 2.5);
exact(value.focalLength, focalFromFov);
assert.equal(value.aperture, 1);
assert.equal(value.kernelSize, 0, "the first input keeps its discrete settings on a weight tie");

value = sample(project, 2.5, 30, memberDistance);
exact(value.distance, 2.15625);
exact(value.focalLength, 0.02765625);
exact(value.aperture, 0.3125);
assert.equal(value.kernelSize, 2);
assert.equal(value.antiAura, true);

track.events = [fixed];
assert.equal(sample(project, 2.5, 30, memberDistance).aperture, 0, "the native lens preserves zero aperture");
assert.equal(sample(project, 5, 30, memberDistance), null, "no authored input disables DOF");

track.events = [member];
assert.equal(sample(project, 0.5, 30, () => undefined), null, "an absent native focus locator does not invent a position");
member.values.cameraAutoDistanceMode = 2;
assert.equal(sample(project, 0.5, 30, memberDistance), null, "automatic focus tracking needs its native transition state");
project.quality.values.posteffect = false;
assert.equal(sample(project, 0.5, 30, memberDistance), null);
const camera = { near: 0.1, far: 1000 };
const layout = globalThis.MVStudioDof.plan(163, 93, { distance: 1, focalLength: 0.023, aperture: 0 }, camera);
assert.deepEqual(layout.sizes, [[81, 46], [40, 23]]);
assert.equal(layout.params[1], Infinity, "zero aperture keeps the native lens limit");
assert.equal(layout.params[2], 0.05);
console.log("Native DOF focus: posed body parts, weighted settings, dominant FOV, lens and quality gate.");
