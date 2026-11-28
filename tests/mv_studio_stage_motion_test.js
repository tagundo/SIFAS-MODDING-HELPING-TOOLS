"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-motion.js");

const { apply, clipTime } = globalThis.MVStudioStageMotion;
const binding = "/EntryPoint/Live/Stages/MainStage/Effect/LightRig";
const fixture = new T.Group();
const rig = new T.Group(), pivot = new T.Group(), lens = new T.Group();
fixture.add(rig); rig.add(pivot); pivot.add(lens);
rig.userData.mvStageNode = { active: true, binding, path: 0 };
pivot.userData.mvStageNode = { active: true, binding, path: 10 };
lens.userData.mvStageNode = { active: false, binding, path: 20 };
pivot.matrixAutoUpdate = false;
pivot.position.set(0, 1, 0);
pivot.updateMatrix();

const clip = (id, animation, start, duration, values) => ({ id, start, duration, values: { animation, ...values } });
const track = { id: "light", nativeClass: "AnimationTrack", binding, events: [
  clip("move", "moving", 0, 4, { postExtrapolationMode: 1, postExtrapolationTime: 2 }),
  clip("stop", "constant", 6, 2, { postExtrapolationMode: 1, postExtrapolationTime: null }),
] };
const zero = ["constant", 0];
const project = { tracks: [track], quality: { values: {} }, stageMotion: {
  mix: { move: {}, stop: { postInfinite: true } },
  quality: { light: "stage_animation" },
  clips: {
    moving: { start: 0, duration: 2, channels: [
      { path: 10, kind: "euler", curves: [zero, zero, ["cubic", [[0, [0, 0, 30, 0]], [2, [0, 0, 0, 60]]]]] },
      { path: 20, kind: "visibility", curves: [["constant", 1]] },
    ] },
    constant: { start: 0, duration: 0, channels: [
      { path: 10, kind: "scale", curves: [["constant", 3], ["constant", 2], ["constant", 1]] },
      { path: 20, kind: "visibility", curves: [zero] },
    ] },
  },
} };
const controller = apply(T, fixture);
const nearAngle = (angle) => {
  const original = new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 0, 1), -angle * Math.PI / 180);
  assert(Math.abs(original.dot(pivot.quaternion)) > 1 - 1e-10, `expected mirrored Euler Z ${angle}`);
};

assert.equal(lens.visible, false);
controller.update(1, project);
nearAngle(30);
assert.equal(lens.visible, true);
controller.update(5, project);
nearAngle(60);
assert.equal(lens.visible, true);
controller.update(6.5, project);
nearAngle(0);
assert.deepEqual(pivot.scale.toArray(), [3, 2, 1]);
assert.equal(lens.visible, false);
controller.update(9, project);
assert.deepEqual(pivot.scale.toArray(), [3, 2, 1], "source duration zero and infinite authored Hold");
controller.update(1, project);
nearAngle(30);
assert.deepEqual(pivot.scale.toArray(), [1, 1, 1], "backwards seek restores other channels");
track.muted = true;
controller.update(1, project);
nearAngle(0);
assert.equal(lens.visible, false);
track.muted = false;
project.quality.values.stage_animation = false;
controller.update(1, project);
nearAngle(0);
assert.equal(lens.visible, false);
assert.equal(rig.visible, false, "native quality handling also disables the bound animation object");
project.quality.values.stage_animation = true;

const loop = clip("loop", "moving", 3, 4, { timeScale: 2, clipIn: 1, postExtrapolationMode: 2, postExtrapolationTime: 10 });
assert.equal(clipTime(loop, {}, 8), 3, "looping uses timeline duration before source time scale and offset");
loop.values.postExtrapolationMode = 3;
assert.equal(clipTime(loop, {}, 8), 7, "ping-pong uses timeline duration before source time scale and offset");
assert.equal(clipTime(loop, {}, 18), null);
assert.equal(clipTime(track.events[1], {}, 9), null, "JSON null does not authorize infinite holds");
const activation = { id: "activation", binding, nativeClass: "ActivationTrack",
  label: "StageEffect/Expert/Display/LightRig", events: [clip("on", undefined, 2, 1, {})] };
project.tracks = [activation];
project.stageMotion = { activations: { activation: ["on"] } };
project.quality.values.stage_display = false;
controller.update(0, project);
assert.equal(rig.visible, false);
controller.update(2.5, project);
assert.equal(rig.visible, true, "native ActivationTrack ignores category quality mute");
controller.update(3, project);
assert.equal(rig.visible, false);
activation.muted = true;
controller.update(3, project);
assert.equal(rig.visible, true, "a muted track restores its authored prefab state");

const display = { id: "display", nativeClass: "AnimationTrack", binding, events: [clip("show", "display", 0, 2, {})] };
project.tracks = [display];
project.quality.values.stage_display = true;
project.stageMotion = {
  quality: { display: "stage_display" },
  mix: { show: {} },
  clips: { display: { start: 0, duration: 2, sampleTimeF32: true, channels: [
    { path: 20, kind: "visibility", visibilityType: "gameObject", curves: [["constant", .002]] },
  ] } },
};
controller.update(1, project);
assert.equal(lens.visible, true, "typed Display curves use Unity's float-to-GameObject threshold");
project.quality.values.stage_display = false;
controller.update(1, project);
assert.equal(lens.visible, false);
assert.equal(rig.visible, false);

const fogColor = new T.Vector4(1, 1, 1, .5), floorTint = new T.Vector4(1, 1, 1, 1);
const density = { value: 2 }, movement = { value: 6 };
let hasFloor = true;
global.MVStudioSoftBillboards = { materialChannel(node, kind, property) {
  if (node !== pivot) return;
  if (kind === "overlayColor" && property === "_Color") return fogColor;
  if (kind === "overlayScalar" && property === "_Density") return density;
  if (kind === "overlayScalar" && property === "_MoveIntensity") return movement;
} };
global.MVStudioStageOverlay = { materialChannel(node, kind, _, scope) {
  if (node === lens && hasFloor && kind === "overlayTint" && scope === "world") return floorTint;
} };
const fogEvent = clip("fog", "fogSource", 0, 4, { blendIn: 2 });
project.tracks = [{ id: "fog", nativeClass: "AnimationTrack", binding, events: [fogEvent] }];
project.stageMotion = {
  quality: { fog: "stage_animation" },
  mix: { fog: { materialScope: "world" } },
  clips: { fogSource: { start: 0, duration: 4, sampleTimeF32: true, requiresOverlayMaterial: true, channels: [
    { path: 10, kind: "overlayColor", curves: [zero, zero, zero, ["constant", 1]] },
    { path: 10, kind: "overlayScalar", property: "_Density", curves: [["linear", [[0, 2], [4, 10]]]] },
    { path: 10, kind: "overlayScalar", property: "_MoveIntensity", curves: [["constant", 22]] },
    { path: 20, kind: "overlayTint", curves: [zero, zero, zero, zero] },
    { path: 10, kind: "translation", curves: [["constant", 3], ["constant", 1], zero] },
  ] } },
};
controller.update(1, project);
assert(controller.accepts(fogEvent));
// The curve-bound material values (MaterialPropertyBlocks in the game) for the runtime value dump.
assert.deepEqual(new Set(controller.curveTargets()), new Set([fogColor, density, movement, floorTint]));
assert.deepEqual(fogColor.toArray(), [.5, .5, .5, .75]);
assert.deepEqual(floorTint.toArray(), [.5, .5, .5, .5]);
assert.equal(density.value, 3);
assert.equal(movement.value, 14);
controller.update(3, project);
assert.deepEqual(fogColor.toArray(), [0, 0, 0, 1]);
assert.equal(density.value, 8);
assert.equal(movement.value, 22);
assert.deepEqual(pivot.position.toArray(), [-3, 1, 0]);
controller.update(4, project);
assert.deepEqual(fogColor.toArray(), [1, 1, 1, .5]);
assert.deepEqual(floorTint.toArray(), [1, 1, 1, 1]);
assert.equal(density.value, 2);
assert.equal(movement.value, 6);

controller.update(3, project);
hasFloor = false;
project.stageMotion = { ...project.stageMotion };
controller.update(3, project);
assert(!controller.accepts(fogEvent));
assert.equal(controller.curveTargets().size, 0, "a rejected clip binds no material value");
assert.deepEqual(fogColor.toArray(), [1, 1, 1, .5]);
assert.deepEqual(pivot.position.toArray(), [0, 1, 0], "missing material holder rejects the entire native clip");
assert.equal(density.value, 2);
assert.equal(movement.value, 6);

// Euler GenericBindings carry Unity's RotationOrder (customType): 0 = XYZ is
// q = qZ*qY*qX, 4 = ZXY (default) is q = qY*qX*qZ, both before the X mirror.
const axis = (x, y, z, degrees) => new T.Quaternion().setFromAxisAngle(new T.Vector3(x, y, z), degrees * Math.PI / 180);
const unityXYZ = axis(0, 0, 1, -90).multiply(axis(0, 1, 0, -60)).multiply(axis(1, 0, 0, 30));
const unityZXY = axis(0, 1, 0, -60).multiply(axis(1, 0, 0, 30)).multiply(axis(0, 0, 1, -90));
const ordered = clip("ordered", "orderedSource", 0, 2, {});
project.tracks = [{ id: "ordered", nativeClass: "AnimationTrack", binding, events: [ordered] }];
for (const [rotationOrder, expected, label] of [[0, unityXYZ, "XYZ"], [undefined, unityZXY, "default ZXY"],
  [4, unityZXY, "ZXY"], [7, new T.Quaternion(), "unknown order rejected"]]) {
  project.stageMotion = { quality: { ordered: "stage_animation" }, mix: { ordered: {} }, clips: { orderedSource: {
    start: 0, duration: 2, channels: [{ path: 10, kind: "euler", rotationOrder,
      curves: [["constant", 30], ["constant", 60], ["constant", 90]] }] } } };
  controller.update(1, project);
  assert(Math.abs(expected.dot(pivot.quaternion)) > 1 - 1e-12, `Euler rotation order ${label}`);
}
assert(Math.abs(unityXYZ.dot(unityZXY)) < 1 - 1e-3, "the fixture distinguishes the two orders");

console.log("Native stage motion: packed curves, handedness, visibility, zero-length assets and extrapolation.");
