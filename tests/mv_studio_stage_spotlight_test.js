"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-spotlight.js");

const constant = value => ["constant", value];
const linear = (...keys) => ["linear", keys];

function near(actual, expected) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-10,
    `index ${index}: expected ${expected[index]}, received ${value}`));
}

const root = new T.Group();
root.position.set(10, 2, -4);
const track = {id: "spot:track", nativeClass: "CustomControlTrack", events: [{
  id: "spot:event", start: 10, duration: 4,
  values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
    offset: {x: 0, y: 0, z: 0}},
}]};
const settings = {stage_control: true, stage_display: false};
const project = {tracks: [track], quality: {values: settings}};
const firstMatrix = new T.Matrix4().makeRotationZ(Math.PI / 2).setPosition(3, 4, 5);
const secondMatrix = new T.Matrix4().makeScale(2, 3, 4).setPosition(-2, 1, 3);
const base = {positions: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], indices: [0, 1, 2]};
const descriptor = {trackId: track.id, eventId: track.events[0].id, duration: 1.8, meshes: [
  {...base, name: "spot_left", alpha: [0, 128, 255], matrix: firstMatrix.toArray(),
    tintCurves: [constant(.25), linear([0, .2], [1.8, .8], [2.7, .1]), constant(.6),
      linear([0, 0], [1.8, .9], [2.7, .1])]},
  {...base, name: "spot_right", alpha: [255, 0, 64], matrix: secondMatrix.toArray(),
    tintCurves: [constant(.75), constant(.5), constant(.25), linear([0, 1], [1.8, .5], [2.7, .9])]},
]};

const invalid = structuredClone(descriptor);
invalid.meshes[0].alpha[1] = 256;
assert.equal(MVStudioStageSpotlight.apply(T, root, invalid), null);
assert.equal(root.children.length, 0);
const spotlight = MVStudioStageSpotlight.apply(T, root, descriptor);
assert.ok(spotlight);
const [group] = root.children, [left, right] = group.children;
assert.equal(root.children.length, 1);
assert.equal(group.children.length, 2);
assert.equal(group.visible, false);
root.updateMatrixWorld();
near(new T.Vector3(1, 0, 0).applyMatrix4(left.matrixWorld).toArray(), [13, 7, 1]);
near(new T.Vector3(1, 0, 0).applyMatrix4(right.matrixWorld).toArray(), [10, 3, -1]);
for (const [mesh, original] of [[left, descriptor.meshes[0]], [right, descriptor.meshes[1]]]) {
  assert.equal(mesh.name, original.name);
  assert.equal(mesh.matrixAutoUpdate, false);
  assert.deepEqual(mesh.matrix.toArray(), original.matrix);
  assert.deepEqual([...mesh.geometry.getAttribute("position").array], original.positions.flat());
  assert.deepEqual([...mesh.geometry.index.array], original.indices);
  const opacity = mesh.geometry.getAttribute("vertexOpacity");
  assert.equal(opacity.normalized, true);
  assert.equal(opacity.itemSize, 1);
  assert.ok(opacity.array instanceof Uint8Array);
  assert.deepEqual([...opacity.array], original.alpha);
  assert.equal(mesh.renderOrder, 3010);
  const material = mesh.material;
  assert.match(material.fragmentShader, /uTint\.a\s*\*\s*vOpacity/);
  assert.equal(material.side, T.DoubleSide);
  assert.equal(material.transparent, true);
  assert.equal(material.depthTest, true);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, false);
  assert.equal(material.blending, T.CustomBlending);
  assert.equal(material.blendSrc, T.SrcAlphaFactor);
  assert.equal(material.blendDst, T.OneFactor);
  assert.equal(material.blendSrcAlpha, T.SrcAlphaFactor);
  assert.equal(material.blendDstAlpha, T.OneFactor);
}
const tint = mesh => mesh.material.uniforms.uTint.value.toArray();

spotlight.update(9.999, project);
assert.equal(group.visible, false);
spotlight.update(10, project);
assert.equal(group.visible, true, "stage_display does not gate a stage_control effect");
near(tint(left), [.25, .2, .6, 0]);
near(tint(right), [.75, .5, .25, 1]);
spotlight.update(10.9, project);
near(tint(left), [.25, .5, .6, .45]);
near(tint(right), [.75, .5, .25, .75]);
spotlight.update(12.7, project);
assert.equal(group.visible, true);
near(tint(left), [.25, .8, .6, .9]);
near(tint(right), [.75, .5, .25, .5]);
spotlight.update(14, project);
assert.equal(group.visible, false);
spotlight.update(10.9, project);
assert.equal(group.visible, true);
near(tint(left), [.25, .5, .6, .45]);
near(tint(right), [.75, .5, .25, .75]);

settings.stage_control = false;
settings.stage_display = true;
spotlight.update(10.9, project);
assert.equal(group.visible, false);
settings.stage_control = true;
track.muted = true;
spotlight.update(10.9, project);
assert.equal(group.visible, false);
track.muted = false;
track.events[0] = {...track.events[0], start: 20};
spotlight.invalidate();
spotlight.update(10.9, project);
assert.equal(group.visible, false);
spotlight.update(20.9, project);
assert.equal(group.visible, true, "editing the cue moves the entire effect");
near(tint(left), [.25, .5, .6, .45]);

let materials = 0, geometries = 0;
for (const mesh of [left, right]) {
  mesh.material.addEventListener("dispose", () => materials++);
  mesh.geometry.addEventListener("dispose", () => geometries++);
}
spotlight.dispose();
spotlight.dispose();
spotlight.update(20.9, project);
assert.equal(materials, 2);
assert.equal(geometries, 2);
assert.equal(root.children.length, 0);
console.log("Native stage spotlight: normalized vertex opacity, fixed skin matrices, additive material, 1.8s hold, cue edits and cleanup.");
