"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-particle-systems.js");
require("../webtools/web/static/mv-studio-control-prefabs.js");

const C = globalThis.MVStudioControlPrefabs;
const P = globalThis.MVStudioParticleSystems;

T.TextureLoader = class {
  async loadAsync(url) {
    const header = Buffer.from(url.split(",")[1], "base64");
    return new T.Texture({width: header.readUInt32BE(16), height: header.readUInt32BE(20)});
  }
};

const b64 = (Type, values) => Buffer.from(new Type(values).buffer).toString("base64");
const material = (overrides = {}) => ({name: "mat", queue: 3000, tint: [1, 1, 1, 1], st: [1, 1, 0, 0],
  vertexColor: true, saturate: false, blend: [5, 1], cull: 0, zTest: 4, zWrite: 0, stencil: [8, 2, 0, 0],
  texture: null, ...overrides});
// Unity's built-in Quad in the editor basis (X mirrored).
const quad = {name: "Quad", vertexCount: 4, positions: b64(Float32Array, [.5, -.5, 0, -.5, .5, 0, -.5, -.5, 0, .5, .5, 0]),
  uv: b64(Float32Array, [0, 0, 1, 1, 1, 0, 0, 1]), colors: null, colorAbsent: true,
  submeshes: [b64(Uint32Array, [0, 2, 1, 1, 3, 0])]};
const node = (parent, path, position = [0, 0, 0], active = true) =>
  ({parent, path, layer: 26, active, position, rotation: [0, 0, 0, 1], scale: [1, 1, 1]});
const linear = (...keys) => ["linear", keys];

function descriptor({loop = true, animators} = {}) {
  return {
    schema: 1, textures: [], meshes: [quad],
    templates: [{
      name: "fx_eq", nodes: [node(null, "fx_eq"), node(0, "fx_eq/root", [1, 0, 0]), node(1, "fx_eq/root/bar", [0, 2, 0]),
        node(1, "fx_eq/root/off", [0, 0, 0], false)],
      renderers: [
        {node: 2, mesh: 0, materials: [material()], draws: [[0, 0]], enabled: true, path: "fx_eq/root/bar", sortCenter: [0, .25, 0]},
        {node: 3, mesh: 0, materials: [material()], draws: [[0, 0]], enabled: true, path: "fx_eq/root/off", sortCenter: [0, 0, 0]},
      ],
      animators: animators ?? [{node: 1, clip: {name: "clip", start: 0, duration: 1, loop}, channels: [
        {target: 2, kind: "translation", curves: [["constant", 0], linear([0, 0], [1, 4]), ["constant", 0]]},
        {target: 0, kind: "tint", curves: [["constant", 1], ["constant", .5], ["constant", .25], linear([0, 1], [1, 0])]},
        {target: 3, kind: "active", curves: [linear([0, 0], [.5, 0], [.5001, 1], [1, 1])]},
      ]}],
    }],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [2, 0, 0], quality: "stage_display"}],
  };
}

const project = (start = 10, duration = 5, extra = {}) => ({
  quality: {values: {stage_display: true, ...extra}},
  tracks: [{id: "track", muted: false, events: [{id: "track:0", start, duration, values: {clipIn: 3}}]}],
});

async function run() {
  assert.equal(C.validDescriptor(descriptor()), true);
  const broken = descriptor();
  broken.templates[0].animators[0].channels[0].target = 99;
  assert.equal(C.validDescriptor(broken), false, "a channel must name a template node");
  const rogue = descriptor();
  rogue.templates[0].renderers[0].draws = [[3, 0]];
  assert.equal(C.validDescriptor(rogue), false, "a draw must name a submesh");

  // One texture table with the particle systems: indices below sharedTextures name the
  // stageParticleSystems descriptor's textures, the rest this descriptor's own.
  const png = (width, height) => {
    const header = Buffer.alloc(24); header.writeUInt32BE(width, 16); header.writeUInt32BE(height, 20);
    return header.toString("base64");
  };
  const level = (width) => ({levels: [{png: png(width, width), width, height: width}], filter: 1, wrap: [0, 0]});
  const particleSide = {textures: [level(4), level(8)]};
  const sharing = descriptor();
  sharing.textures = [level(16)];
  sharing.sharedTextures = 2;
  sharing.templates[0].renderers[0].materials = [material({texture: 1})];
  sharing.templates[0].renderers[1].materials = [material({texture: 2})];
  assert.equal(C.validDescriptor(sharing, particleSide), true);
  assert.equal(C.validDescriptor(sharing), false, "shared indices need the particle descriptor");
  assert.equal(C.validDescriptor(sharing, {textures: [level(4)]}), false, "the shared count must match");
  const outside = structuredClone(sharing);
  outside.templates[0].renderers[1].materials = [material({texture: 3})];
  assert.equal(C.validDescriptor(outside, particleSide), false);
  const loaded = [];
  const loadTexture = P.loadTexture;
  P.loadTexture = async (T, title, source) => { loaded.push(source?.levels[0].width ?? "white"); return loadTexture(T, title, source); };
  const sharedScene = new T.Scene();
  const sharedPrefabs = await C.apply(T, sharedScene, sharing, particleSide);
  P.loadTexture = loadTexture;
  assert.ok(sharedPrefabs);
  assert.deepEqual(loaded, [8, 16, "white"], "only the sampled textures are uploaded: shared index 1 and own index 0");
  sharedPrefabs.update(10.6, project());
  const sampled = [];
  sharedScene.traverse(object => { if (object.isMesh) sampled.push(object.material.uniforms.uTexture.value.image?.width); });
  assert.deepEqual(sampled.sort((a, b) => a - b), [8, 16]);
  sharedPrefabs.dispose();

  // The state time runs from the activation frame (clipIn does not reach the Animator),
  // wraps for a looping clip and holds the end otherwise.
  const clip = {start: 0, duration: 1, loop: true};
  assert.equal(P.animatorTime(clip, 15, 30), .5);
  assert.equal(P.animatorTime(clip, 45, 30), .5);
  assert.equal(P.animatorTime({...clip, loop: false}, 45, 30), 1);
  assert.equal(P.animatorTime({...clip, start: 2}, 15, 30), 2.5);

  const scene = new T.Scene();
  const prefabs = await C.apply(T, scene, descriptor());
  assert.ok(prefabs);
  const group = scene.children.find(child => child.name === "Original control prefabs");
  const meshes = () => { const found = []; group.traverse(object => object.isMesh && found.push(object)); return found; };

  // Before the clip nothing is instantiated; at the start the clone appears at the offset.
  prefabs.update(9.9, project());
  assert.equal(meshes().length, 0);
  prefabs.update(10, project());
  const [bar, off] = meshes();
  assert.ok(bar && off);
  const world = object => object.parent.parent.getWorldPosition(new T.Vector3()).toArray().map(value => Math.round(value * 1e4) / 1e4);
  // Frame 1 of the clone: state time 1/30 s. Offset (2,0,0) and the root's (1,0,0) mirror to -3;
  // the animated local position replaces the authored (0,2,0).
  assert.deepEqual(world(bar), [-3, Math.round(4 / 30 * 1e4) / 1e4, 0]);
  // The mesh origin is the renderer bounds center (three.js sorts by it); the vertices stay put.
  scene.updateMatrixWorld(true);
  const node = bar.parent.parent.getWorldPosition(new T.Vector3());
  assert.ok(bar.getWorldPosition(new T.Vector3()).distanceTo(node.clone().add(new T.Vector3(0, .25, 0))) < 1e-6);
  const corner = new T.Vector3().fromBufferAttribute(bar.geometry.attributes.position, 0).applyMatrix4(bar.matrixWorld);
  assert.ok(corner.distanceTo(node.clone().add(new T.Vector3(.5, -.5, 0))) < 1e-6);
  const tint = bar.material.uniforms.uTint.value.toArray().map(value => Math.round(value * 1e4) / 1e4);
  assert.deepEqual(tint, [1, .5, .25, Math.round((1 - 1 / 30) * 1e4) / 1e4]);
  // The inactive node is activated by its curve only after half a second.
  const shown = object => { for (let item = object; item; item = item.parent) if (!item.visible) return false; return true; };
  assert.equal(shown(off), false);
  prefabs.update(10 + 20 / 30, project());
  assert.equal(shown(off), true);
  // The clip loops: frame 31 samples the state at 1/30 s again.
  prefabs.update(10 + 30 / 30, project());
  assert.deepEqual(world(bar)[1], Math.round(4 / 30 * 1e4) / 1e4);
  // Quality gate and the clip end hide the clone.
  prefabs.update(12, project(10, 5, {stage_display: false}));
  assert.equal(shown(bar), false);
  prefabs.update(15, project());
  assert.equal(shown(bar), false);
  prefabs.update(14.5, project());
  assert.equal(shown(bar), true);
  // Display effects keep the material's stencil test (Equal 2 over the stage screens).
  const masked = descriptor();
  masked.templates[0].renderers[0].materials[0].stencil = [3, 2, 0, 0];
  const maskedScene = new T.Scene();
  const second = await C.apply(T, maskedScene, masked);
  second.update(10, project());
  const stencilled = [];
  maskedScene.traverse(object => object.isMesh && stencilled.push(object.material));
  assert.equal(stencilled[0].stencilFunc, T.EqualStencilFunc);
  assert.equal(stencilled[0].stencilRef, 2);
  assert.equal(stencilled[1].stencilWrite, false);
  const inspected = second.inspect();
  assert.equal(inspected.length, 1);
  assert.equal(inspected[0].template, "fx_eq");
  assert.equal(inspected[0].frames, 1);
  second.dispose();
  prefabs.dispose();
  assert.equal(scene.children.includes(group), false);

  // Skinned renderers: CPU linear blend skinning with mirrored bind poses.
  const skinned = descriptor({animators: [{node: 1, clip: {name: "swing", start: 0, duration: 2, loop: false}, channels: [
    {target: 2, kind: "euler", rotationOrder: 4, curves: [["constant", 0], ["constant", 0], linear([0, 0], [2, 90])]},
  ]}]});
  skinned.meshes.push({...quad, name: "Beam", joints: b64(Uint16Array, [0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]),
    weights: b64(Float32Array, [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])});
  const identity = new T.Matrix4().toArray();
  const inverse = new T.Matrix4().makeTranslation(0, -2, 0).toArray();
  skinned.templates[0].renderers = [{node: 1, mesh: 1, materials: [material()], draws: [[0, 0]], enabled: true,
    path: "fx_eq/root/beam", skin: {bones: [1, 2], bindPoses: [identity, inverse], root: 1, rootCenter: [0, 0, 0]}}];
  assert.equal(C.validDescriptor(skinned), true);
  const beamScene = new T.Scene();
  const beams = await C.apply(T, beamScene, skinned);
  beams.update(10 + 59 / 30, project());
  const states = beams.inspect()[0].renderers;
  assert.equal(states.length, 1);
  assert.equal(states[0].visible, true);
  let beam;
  beamScene.traverse(object => { if (object.isMesh) beam = object; });
  beamScene.updateMatrixWorld(true);
  // Independent expectation: the bar bone at its rest translation, turned -90 deg about Z
  // (Unity +90 mirrored) at state time 2 s, applied to the vertex bound to it.
  const bone1 = new T.Matrix4().makeTranslation(-3, 0, 0);
  const bone2 = bone1.clone().multiply(new T.Matrix4().makeTranslation(0, 2, 0))
    .multiply(new T.Matrix4().makeRotationZ(-Math.PI / 2)).multiply(new T.Matrix4().fromArray(inverse));
  const rest = [[.5, -.5, 0], [-.5, .5, 0], [-.5, -.5, 0], [.5, .5, 0]];
  const position = beam.geometry.attributes.position;
  rest.forEach(([x, y, z], vertex) => {
    const expected = new T.Vector3(x, y, z).applyMatrix4(vertex === 1 || vertex === 2 ? bone2 : bone1);
    const actual = new T.Vector3().fromBufferAttribute(position, vertex).applyMatrix4(beam.matrixWorld);
    assert.ok(actual.distanceTo(expected) < 1e-5, `vertex ${vertex}: ${actual.toArray()} vs ${expected.toArray()}`);
  });
  // m_AABB about the root bone: the sort center is the root's rest point.
  assert.deepEqual(beams.inspect()[0].renderers[0].center.map(value => +value.toFixed(6)), [-3, 0, 0]);
  beams.dispose();

  // m_UpdateWhenOffscreen: Unity recomputes the bounds from the skinned pose every
  // frame, so the sort center is the skinned vertices' AABB center.
  skinned.templates[0].renderers[0].skin.updateWhenOffscreen = true;
  assert.equal(C.validDescriptor(skinned), true);
  const offscreenScene = new T.Scene();
  const offscreen = await C.apply(T, offscreenScene, skinned);
  offscreen.update(10 + 59 / 30, project());
  let moved;
  offscreenScene.traverse(object => { if (object.isMesh) moved = object; });
  offscreenScene.updateMatrixWorld(true);
  const expected = rest.map(([x, y, z], vertex) => new T.Vector3(x, y, z).applyMatrix4(vertex === 1 || vertex === 2 ? bone2 : bone1));
  const bounds = new T.Box3().setFromPoints(expected), middle = bounds.getCenter(new T.Vector3());
  const center = new T.Vector3().fromArray(offscreen.inspect()[0].renderers[0].center);
  assert.ok(center.distanceTo(middle) < 1e-5, `sort center ${center.toArray()} vs ${middle.toArray()}`);
  assert.ok(center.distanceTo(new T.Vector3(-3, 0, 0)) > .1, "not the root bone's m_AABB center");
  const moving = moved.geometry.attributes.position;
  expected.forEach((point, vertex) => {
    const actual = new T.Vector3().fromBufferAttribute(moving, vertex).applyMatrix4(moved.matrixWorld);
    assert.ok(actual.distanceTo(point) < 1e-5, `offscreen vertex ${vertex}: ${actual.toArray()} vs ${point.toArray()}`);
  });
  skinned.templates[0].renderers[0].skin.updateWhenOffscreen = 1;
  assert.equal(C.validDescriptor(skinned), false);
  offscreen.dispose();
}

run().then(() => console.log("mv_studio_control_prefabs_test: ok")).catch(error => {
  console.error(error);
  process.exit(1);
});
