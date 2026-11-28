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
assert.equal(data.uBeat.value, 2, "before the first CRI callback LiveDirectorBase runs its constructor bpm 120 from origin 0");
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
assert.equal(light.material.userData.mvHiddenUniforms, "stale", "a hidden penlight keeps the last clip's uniforms");
uniforms(1);
assert.equal(light.material.visible, true);

const region = (bpm, startSample, endSample) => ({ bpm, startSample, endSample, numBeats: 4, baseRate: 10000 });
const regions = [region(120, 0, 22999), region(60, 23000, 28999), region(120, 29000, 42999),
  region(60, 43000, 66999)];
project.stage.beatSync = { ...regions[0], segments: regions };
const animated = clip(0, 10, 2, 1, [0, 0, 0]);
project.tracks[0].events = [animated];
preview.invalidate();
assert.equal(uniforms(2.25).uBeat.value, 4.5);
assert.equal(uniforms(2.5).uBeat.value, 5, "same-index transition retains the previous callback");
assert.equal(uniforms(2.75).uBeat.value, 5.5, "a short region publishes no callback at the same index");
assert.ok(Math.abs(uniforms(2.95).uBeat.value - 5.9) < 1e-9);
assert.equal(uniforms(3.4).uBeat.value, 1, "the first changed beat index resets to the local row's count");
assert.ok(Math.abs(uniforms(4.45).uBeat.value - .15) < 1e-9, "a changed index can reset at the region start");
assert.ok(Math.abs(uniforms(7).uBeat.value - 2.7) < 1e-9, "the director extrapolates the last callback");
assert.equal(uniforms(1.25).uBeat.value, 2.5, "seeking does not depend on previous render frames");
assert.equal(uniforms(1.25).uMode.value, 2);

for (const segments of [[regions[0], null], Array(257).fill(regions[0])]) {
  project.stage.beatSync = { ...regions[0], segments };
  preview.update(1.25, project);
  assert.equal(light.material, original, "invalid saved timing uses the base material");
}
project.stage.beatSync = { ...regions[0], segments: regions };
assert.equal(uniforms(1.25).uBeat.value, 2.5);

// LiveDirectorBase.SyncBeat stores the music time of the frame that dispatches
// the CRI callback: the beat restarts from its count at that frame.
const api = globalThis.MVStudioPenlight;
const real = api.prepareBeatClock({ bpm: 90, startSample: 235185, baseRate: 44100 });
const frameBeat = (time, history) => api.beatValue(time, api.dispatchBeat(null, time, real, { advancing: false, history }));
assert.equal(frameBeat(1.5, []), 3, "no callback yet: 120 bpm from the director's origin 0");
// 12035 Max 3D dump: beat 84 at 61.333 s, previous frame 61.251 s, frame 61.511 s reads exactly 84.
assert.equal(frameBeat(61.511, [60.954, 61.251]), 84);
assert.ok(Math.abs(frameBeat(61.511, []) - 84.2665) < 1e-3, "a seek without history counts from the beat itself");
// Beat 85 at 62.000 s was dispatched by the frame at 62.049 s; the dump reads 85.4155 at 62.326 s.
assert.ok(Math.abs(frameBeat(62.326, [61.511, 61.771, 62.049]) - 85.4155) < 1e-9);
// Frames from before the region start: the first callback restarts the count at its frame.
assert.equal(frameBeat(5.435, [4.72, 5.2434]), 0);
// Advancing frames continue the stored state; a later beat is dispatched by the next frame.
let state = api.dispatchBeat(null, 61.251, real, { advancing: false, history: [60.954] });
assert.equal(state.event.count, 83);
state = api.dispatchBeat(state, 61.511, real, { advancing: true, history: [] });
assert.deepEqual([state.event.count, state.origin], [84, 61.511]);
const kept = api.dispatchBeat(state, 61.6, real, { advancing: true, history: [] });
assert.equal(kept, state, "no new callback keeps the dispatch frame");
assert.ok(Math.abs(api.beatValue(61.6, kept) - (84 + .089 * 1.5)) < 1e-9);

// The scene hands its frame clock to the penlights.
project.stage.beatSync = { bpm: 90, startSample: 235185, baseRate: 44100 };
project.tracks[0].events = [clip(0, 100, 2, 1, [0, 0, 0])];
preview.invalidate();
preview.update(61.251, project, { advancing: false, history: [60.954] });
preview.update(61.511, project, { advancing: true, history: [] });
assert.equal(light.material.uniforms.uBeat.value, 84);
preview.update(61.511, project, { advancing: false, history: [] });
assert.ok(Math.abs(light.material.uniforms.uBeat.value - 84.2665) < 1e-3);
project.stage.beatSync = { ...regions[0], segments: regions };

let disposals = 0;
light.material.addEventListener("dispose", () => { disposals++; });
preview.dispose();
assert.equal(light.material, original);
assert.equal(light.frustumCulled, true);
assert.equal(disposals, 1);
console.log("Native MV penlight colors, weighted mixing, beat clock and material lifecycle passed");
