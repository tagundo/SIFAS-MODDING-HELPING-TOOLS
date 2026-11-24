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
const exact = (actual, expected, message) => assert(Math.abs(actual - expected) < 1e-6, `${message || ""} ${actual} vs ${expected}`);

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
const warnings = [];
value = sample(project, 0.5, 30, () => undefined, { warn: (message) => warnings.push(message) });
exact(value.distance, 1, "an absent native focus locator falls back to the clip focusDistance");
assert.equal(warnings.length, 1);
assert.match(warnings[0], /body part 3 of member 2/);

// LiveDepthOfFieldClip..ctor initialisers for fields a timeline never serialized.
const legacy = event(0, 3, { useMemberDistance: 1, memberPosition: 2, bodyPart: 2, useCameraFov: 1 });
delete legacy.values.focusDistance;
track.events = [legacy];
const seen = [];
value = sample(project, 0.5, 30, (slot, part) => (seen.push([slot, part]), 4.1));
exact(value.distance, Math.fround(Math.fround(4.1) - Math.fround(0.1)), "a missing cameraAutoDistanceMode is 0 (explicit member)");
assert.deepEqual(seen, [[2, 2]], "BodyPartType Face 2 is a native focus part");
for (const part of [0, 1, 3, 4]) {
  legacy.values.bodyPart = part;
  assert(Math.abs(sample(project, 0.5, 30, () => 2).distance - 1.9) < 1e-6, `BodyPartType ${part} is in partMap`);
}
// The client's exception path: GetPart(5) is null, CalcFocusDistance throws a
// NullReferenceException, ProcessFrame skips PostProcess and the camera keeps
// the DepthOfFieldModel.Settings the previous frame wrote. Their lens resolves
// when the camera renders (DepthOfFieldComponent.CalculateFocalLength), so a
// useCameraFov lens follows the current FOV and a fixed one keeps focalLength / 1000.
const previousClip = event(0, 3, { focusDistance: 7, aperture: 3, focalLength: 50, kernelSize: 1, useCameraFov: 1 });
track.events = [previousClip];
const previous = Object.freeze(sample(project, 0.5, 30, () => 2));
const { focalLength: previousFocal, ...previousSettings } = previous;
assert.deepEqual(previousSettings, { distance: 7, aperture: 3, kernelSize: 1, antiAura: false, useCameraFov: true,
  clipFocalLength: 50 }, "a result carries the unresolved lens");
exact(previousFocal, focalFromFov);
previousClip.values.useCameraFov = 0;
const previousFixed = Object.freeze(sample(project, 0.5, 30, () => 2));
exact(previousFixed.focalLength, 0.05);
assert.equal(previousFixed.useCameraFov, false);
const focalAt60 = 0.012 / Math.tan(Math.PI / 6);
const kept = (actual, settings, fov, message) => {
  assert.notEqual(actual, settings, `${message}: a new lens, not the previous object`);
  const { focalLength, ...rest } = actual;
  const { focalLength: _, ...expected } = settings;
  assert.deepEqual(rest, expected, `${message}: distance, aperture, kernelSize, antiAura and the lens settings stay`);
  exact(focalLength, settings.useCameraFov ? 0.012 / Math.tan(fov * Math.PI / 360) : settings.clipFocalLength / 1000, message);
};
track.events = [legacy];
legacy.values.bodyPart = 5;
const partWarnings = [];
value = sample(project, 0.5, 60, () => 2, { previous, warn: (message) => partWarnings.push(message) });
kept(value, previous, 60, "HeadMaterial 5 is not in partMap: the previous frame's depth of field stays");
exact(value.focalLength, focalAt60, "a useCameraFov lens resolves at the current FOV");
assert(Math.abs(value.focalLength - previous.focalLength) > 0.02, "not the previous frame's resolved focal length");
value = sample(project, 0.5, 60, () => 2, { previous: previousFixed, warn: () => {} });
kept(value, previousFixed, 60, "a fixed lens");
exact(value.focalLength, 0.05, "a fixed lens keeps focalLength / 1000 at any FOV");
assert.equal(partWarnings.length, 1);
assert.match(partWarnings[0], /body part 5, which BodyPartManager never holds/);
assert.equal(sample(project, 0.5, 30, () => 2, { warn: () => {} }), null, "no earlier frame: nothing was applied");
legacy.values.bodyPart = 0;

// Members[memberPosition - 1] out of range or not loaded: the same exception path.
legacy.values.memberPosition = 3;
const memberWarnings = [];
const memberOptions = (extra) => ({ members: [1, 2], previous, warn: (message) => memberWarnings.push(message), ...extra });
kept(sample(project, 0.5, 45, () => 2, memberOptions({ performers: [1, 2] })), previous, 45,
  "a member the MV does not have keeps the previous frame's depth of field");
assert.equal(memberWarnings.length, 1);
assert.match(memberWarnings[0], /member 3, which this MV does not have/);
kept(sample(project, 0.5, 45, () => 2, memberOptions({ performers: [1, 2, 3] })), previous, 45,
  "a performer that has not loaded keeps the previous frame's depth of field");
assert.equal(memberWarnings.length, 1, "a performer still loading is not reported");
const keptState = globalThis.MVStudioDofFocus.createState();
keptState.prevPos = 1;
sample(project, 0.5, 30, () => 2, memberOptions({ performers: [1, 2], state: keptState }));
assert.equal(keptState.prevPos, 1, "the throwing clip never reaches the transition state update");
// A clip that blends with a throwing one is discarded with the whole frame.
const blended = event(0, 3, { focusDistance: 4 });
track.events = [blended, legacy];
kept(sample(project, 0.5, 30, () => 2, memberOptions({ performers: [1, 2] })), previous, 30, "a blended frame");
// Consecutive throwing frames keep the first settings and follow the FOV.
let chained = previous;
for (const fov of [40, 20, 70]) {
  chained = sample(project, 0.5, fov, () => 2, memberOptions({ performers: [1, 2], previous: chained }));
  kept(chained, previous, fov, `a throwing frame at FOV ${fov}`);
}
track.events = [legacy];
legacy.values.memberPosition = 2;
// A loaded member without the exported part is a preview gap: focusDistance stays.
const gapWarnings = [];
value = sample(project, 0.5, 30, () => undefined, { members: [1, 2], performers: [1, 2], previous,
  warn: (message) => gapWarnings.push(message) });
exact(value.distance, 1, "a loaded member lacking the exported part keeps the clip focusDistance");
assert.match(gapWarnings[0], /which this preview cannot locate/);
legacy.values.useMemberDistance = 0;
value = sample(project, 0.5, 30, () => 2);
exact(value.distance, 1);
exact(value.aperture, 2);
assert.equal(value.antiAura, false);

// cameraAutoDistanceMode 1: nearest member, no transition.
const nearest = event(0, 10, { useMemberDistance: 1, cameraAutoDistanceMode: 1, bodyPart: 0, useCameraFov: 1 });
track.events = [nearest];
const distances = { 1: 5, 2: 3.5, 3: 7 };
value = sample(project, 1, 30, (slot) => distances[slot], { members: [1, 2, 3] });
exact(value.distance, Math.fround(3.5 + Math.fround(-0.1)));

// cameraAutoDistanceMode 2: member nearest the view axis, lerped over
// focusTransitionTime from the previous member's distance when it changes.
const axis = event(0, 10, { useMemberDistance: 1, cameraAutoDistanceMode: 2, bodyPart: 0, useCameraFov: 1,
  focusTransitionTime: 2 });
track.events = [axis];
const state = globalThis.MVStudioDofFocus.createState();
let angles = { 1: 5, 2: 30 };
const options = () => ({ members: [1, 2], angle: (slot) => angles[slot], state });
const axisDistance = { 1: 2.1, 2: 6.1 };
const focusAt = (time) => sample(project, time, 30, (slot) => axisDistance[slot], options()).distance;
exact(focusAt(1), Math.fround(2.1 + Math.fround(-0.1)), "the first evaluation settles on the chosen member");
assert.equal(state.prevPos, 0);
angles = { 1: 30, 2: 5 };
const start = focusAt(2);
exact(start, Math.fround(Math.fround(2.1) + Math.fround(-0.1)), "the transition starts at the previous distance");
assert.equal(state.startTime, 2);
const half = focusAt(3);
exact(half, Math.fround(Math.fround(Math.fround(2.1) + Math.fround(Math.fround(Math.fround(6.1) - Math.fround(2.1)) * 0.5)) + Math.fround(-0.1)));
exact(state.prevUnfinishedDistance, Math.fround(Math.fround(2.1) + Math.fround(Math.fround(Math.fround(6.1) - Math.fround(2.1)) * 0.5)));
exact(focusAt(4), Math.fround(Math.fround(6.1) + Math.fround(-0.1)), "the transition ends after focusTransitionTime");
assert.deepEqual({ ...state }, { startTime: -1, prevPos: 1, prevDistance: Math.fround(6.1),
  prevUnfinishedDistance: Math.fround(6.1), unfinishedStartTime: -1 });
// An explicit clip resets the shared transition state.
axis.values.cameraAutoDistanceMode = 0;
axis.values.memberPosition = 1;
sample(project, 5, 30, (slot) => axisDistance[slot], options());
assert.equal(state.prevPos, -1);
exact(state.prevDistance, Math.fround(2.1));
// Modes 1 and 2 with no member loaded yet keep the previous frame's depth of field.
for (const mode of [1, 2]) {
  axis.values.cameraAutoDistanceMode = mode;
  kept(sample(project, 5, 30, () => 2, { members: [], angle: () => 0, previous }), previous, 30, `mode ${mode} without members`);
}
const vectorAngle = globalThis.MVStudioDofFocus.vectorAngle;
exact(vectorAngle({ x: 0, y: 0, z: -1 }, { x: 1, y: 0, z: -1 }), 45);
assert.equal(vectorAngle({ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }), 0, "Unity returns 0 for a zero vector");

track.events = [member];
project.quality.values.posteffect = false;
assert.equal(sample(project, 0.5, 30, memberDistance), null);
const camera = { near: 0.1, far: 1000 };
const layout = globalThis.MVStudioDof.plan(163, 93, { distance: 1, focalLength: 0.023, aperture: 0 }, camera);
assert.deepEqual(layout.sizes, [[81, 46], [40, 23]]);
assert.equal(layout.params[1], Infinity, "zero aperture keeps the native lens limit");
assert.equal(layout.params[2], 0.05);
console.log("Native DOF focus: BodyPartType parts, clip defaults, member modes 0/1/2 with the mode-2 transition, the client exception path keeping the previous frame, weighted settings, dominant FOV, lens and quality gate.");
