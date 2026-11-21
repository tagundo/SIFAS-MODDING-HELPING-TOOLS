"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-penlight.js");

const geometry = new T.BufferGeometry();
geometry.userData.mvPenlight = {
  bindingSuffix: "aud_root/aud_01",
  localToPreview: new T.Matrix4().makeScale(-1, 1, 1).setPosition(8, 9, 10).toArray(),
  material: { floats: { _CullMode: 2 } },
};
for (const [attribute, size] of [["_penlight_center", 3], ["_penlight_color", 4], ["_penlight_corner", 3]]) {
  geometry.setAttribute(attribute, new T.Float32BufferAttribute(Array(size).fill(0), size));
}
const original = new T.MeshBasicMaterial({ map: new T.Texture() });
const light = new T.Mesh(geometry, original);
const root = new T.Group().add(light);
const preview = globalThis.MVStudioPenlight.apply(T, root);
const clip = (start, duration, swingMode, colorSpecifiedType, position) => ({ start, duration, values: {
  playableClass: "LivePenlightClip", swingMode, beatLength: 2, beatOffset: 0,
  position, tintColor: [1, 1, 1, 1],
  memberColors: [{ colorSpecifiedType, memberPosition: 1, color: [1, 1, 1, 1] }],
}});
const first = clip(0, 4, 0, 1, [2, 0, 0]), second = clip(2, 4, 1, 2, [8, 6, 0]);
first.values.blendOut = 2;
second.values.blendIn = 2;
const project = {
  stage: { beatSync: { startSample: 100, baseRate: 50, bpm: 120 }, originalMemberThemeColors: { 1: [0, 0, 1, 1] } },
  performers: [{ position: 1, themeColor: [1, 0, 0, 1] }],
  tracks: [{ kind: "crowd", binding: "/EntryPoint/Live/Stages/MainStage/Effect/aud_root/aud_01", events: [first, second] }],
};
const uniforms = (time) => {
  preview.update(time, project);
  return light.material.uniforms;
};

let data = uniforms(1);
assert.deepEqual(data.uPalette.value[0].toArray(), [1, 0, 0, 1]);
assert.deepEqual(data.uLocalToPreview.value.elements.slice(12, 15), [-2, 0, 0]);
assert.equal(data.uBeat.value, 0);
assert.equal(light.material.side, T.FrontSide);
assert.equal(light.material.blendSrc, T.SrcAlphaFactor);
assert.equal(light.material.blendDst, T.OneFactor);
assert.equal(light.material.depthWrite, false);
assert.equal(light.frustumCulled, false);

data = uniforms(2.5);
assert.deepEqual(data.uPalette.value[0].toArray(), [.84375, 0, .15625, 1], "Unity default curves have smoothstep easing");
data = uniforms(3);
assert.equal(data.uMode.value, 0, "first native input wins when weights tie");
assert.deepEqual(data.uPalette.value[0].toArray(), [.5, 0, .5, 1]);
assert.deepEqual(data.uLocalToPreview.value.elements.slice(12, 15), [-5, 3, 0]);
data = uniforms(3.5);
assert.equal(data.uMode.value, 1);
assert.equal(data.uBeat.value, 3);
data = uniforms(5);
assert.deepEqual(data.uPalette.value[0].toArray(), [0, 0, 1, 1], "original lineup palette is distinct from current cast");
second.values.beatLength = 4;
preview.invalidate();
assert.equal(uniforms(5).uBeatLength.value, 4, "seeking after an in-place edit refreshes uniforms");

uniforms(6.5);
assert.equal(light.material.visible, false, "no authored contribution during a gap");
uniforms(1);
assert.equal(light.material.visible, true);

let disposals = 0;
light.material.addEventListener("dispose", () => { disposals++; });
preview.dispose();
assert.equal(light.material, original);
assert.equal(light.frustumCulled, true);
assert.equal(disposals, 1);
console.log("Native MV penlight colors, weighted mixing, beat clock and material lifecycle passed");
