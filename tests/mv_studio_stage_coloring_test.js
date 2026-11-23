"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-coloring.js");

const increasing = [{ time: 0, value: 0 }, { time: 1, value: 1 }];
const decreasing = [{ time: 0, value: 1 }, { time: 1, value: 0 }];
const track = { events: [
  { start: 0, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [1, 2, 3, 0],
    blendOut: 1, mixOut: decreasing, shift: 3, speed: 2, clipIn: .25, timeScale: 2 } },
  { start: 1, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [3, 2, 1, 1],
    blendIn: 1, mixIn: increasing, shift: 12, speed: 3 } }
] };
assert.deepEqual(MVStudioStageColoring.sample(track, 0).tint, [1, 2, 3, 0]);
assert.deepEqual(MVStudioStageColoring.sample(track, 1.5), {
  tint: [2, 2, 2, .5], shift: 3, speed: 2, selfTime: 3.25, textureIndex: 0
});
assert.equal(MVStudioStageColoring.sample(track, 1.75).shift, 12);
assert.equal(MVStudioStageColoring.sample(track, 3).tint[3], 0);

const native = new Uint8Array([16, 255, 128, 129, 26, 128, 0, 129, 36, 255, 8, 255, 56, 255, 8, 129]);
const palette = new Uint8Array(native.length);
MVStudioStageColoring.customize(native, palette, { 1: [1, 0, .5, 1], 2: [1, .5, 0, 1], 3: [0, 0, 0, 1] });
assert.deepEqual([...palette], [255, 0, 128, 255, 128, 64, 0, 255, 36, 255, 8, 255, 56, 255, 8, 129]);

// LiveColoringMixer textureIndex: the strictly heaviest input wins, 0 without an active clip.
const indexed = { events: [
  { start: 0, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [1, 1, 1, 1],
    blendOut: 1, mixOut: decreasing, shift: 0, speed: 0, textureIndex: 1 } },
  { start: 1, duration: 2, values: { playableClass: "LiveColoringClip", tintColor: [1, 1, 1, 1],
    blendIn: 1, mixIn: increasing, shift: 0, speed: 0, textureIndex: 5 } }
] };
assert.equal(MVStudioStageColoring.sample(indexed, .5).textureIndex, 1);
assert.equal(MVStudioStageColoring.sample(indexed, 1.25).textureIndex, 1);
assert.equal(MVStudioStageColoring.sample(indexed, 1.5).textureIndex, 1);
assert.equal(MVStudioStageColoring.sample(indexed, 1.75).textureIndex, 5);
assert.equal(MVStudioStageColoring.sample(indexed, 4).textureIndex, 0);

// LiveCoreStageColoring.ApplyTextureIndex: empty list and current index are no-ops; out of range throws in the client.
const state = { currentIndex: null };
assert.equal(MVStudioStageColoring.applyTextureIndex(state, [], 0), false);
assert.equal(state.currentIndex, null);
assert.equal(MVStudioStageColoring.applyTextureIndex(state, ["a", "b"], 0), true);
assert.equal(MVStudioStageColoring.applyTextureIndex(state, ["a", "b"], 0), false);
assert.equal(MVStudioStageColoring.applyTextureIndex(state, ["a", "b"], 5), false);
assert.equal(state.currentIndex, 0);
assert.equal(MVStudioStageColoring.applyTextureIndex(state, ["a", "b"], 1), true);
assert.equal(state.currentIndex, 1);

async function controller() {
  const effect = "/EntryPoint/Live/Stages/MainStage/Effect/lit_01/litA_All";
  const fields = { target: effect, tint: [1, 1, 1, 1], speed: 0, shift: 0, cull: 0, queue: 3000,
    mainUV: [1, 1, 0, 0], indexScale: 1, indexOffset: 0, palette: { bytes: 3, size: [256, 1] } };
  const mesh = (extra) => {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial());
    node.geometry.setAttribute("_stage_color_index", new T.Float32BufferAttribute(new Float32Array(8), 2));
    node.geometry.userData.mvStageColoring = { ...fields, ...extra };
    return node;
  };
  const root = new T.Group();
  const shafted = mesh({ main: 7, shaftTextures: [8, 9] });
  const plain = mesh({ target: effect.replace("litA", "litB"), main: 7, shaftTextures: [] });
  root.add(shafted, plain);
  const decoded = new Map([7, 8, 9].map(index => [index, Object.assign(new T.Texture(), { name: "tex" + index })]));
  const parser = { getDependency: (type, index) => Promise.resolve(
    type === "bufferView" ? new Uint8Array(256 * 4).buffer : decoded.get(index)) };
  const coloring = await MVStudioStageColoring.apply(T, root, parser);
  const main = (node) => node.material.uniforms.uMain.value.name;
  const clip = (start, duration, textureIndex) => ({ start, duration, values: {
    playableClass: "LiveColoringClip", tintColor: [1, 1, 1, 1], shift: 0, speed: 0, textureIndex } });
  const project = { tracks: [
    { nativeClass: "LiveColoringTrack", binding: effect, events: [clip(1, 1, 1), clip(3, 1, 7)] },
    { nativeClass: "LiveColoringTrack", binding: effect.replace("litA", "litB"), events: [clip(1, 1, 1)] }
  ] };
  // Before any bound mixer runs, the material keeps its own _MainTex.
  coloring.update(0, { tracks: [] });
  assert.equal(main(shafted), "tex7");
  // First mixer frame with no clip: index 0 replaces _MainTex.
  coloring.update(0, project);
  assert.equal(main(shafted), "tex8");
  coloring.update(1.5, project);
  assert.equal(main(shafted), "tex9");
  // An out-of-range index keeps the current texture.
  coloring.update(3.5, project);
  assert.equal(main(shafted), "tex9");
  coloring.update(5, project);
  assert.equal(main(shafted), "tex8");
  // A component without light shaft textures keeps its material texture.
  assert.equal(main(plain), "tex7");
  // A muted track leaves no mixer, so the material texture returns.
  coloring.update(5, { tracks: project.tracks.map(track => ({ ...track, muted: true })) });
  assert.equal(main(shafted), "tex7");
  coloring.dispose();
}

controller().then(() => {
  console.log("Native stage coloring: RGBA blend, first winner at tie, clip time, lossless palette masks and light shaft textures.");
}).catch(error => { console.error(error); process.exitCode = 1; });
