"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-stage-overlay.js");

async function run() {
  const root = new T.Scene(), marker = new T.Group(), material = new T.MeshBasicMaterial();
  const mesh = new T.Mesh(new T.PlaneGeometry(), material);
  root.add(marker);
  marker.add(mesh);
  root.background = new T.Color("black");
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_ove_so2056_01/Effect_root";
  marker.userData.mvStageNode = { active: true, path: 0, binding };
  mesh.geometry.userData.mvStageOverlay = {
    texture: null, tint: [1, 1, 1, 1], uv: [1, 1, 0, 0], vertexColor: true, queue: 3000
  };
  const overlay = await MVStudioStageOverlay.apply(T, root);
  assert.equal(mesh.layers.mask, 1 << 20);
  assert.equal(mesh.material.blendDst, T.OneFactor);
  assert.equal(mesh.material.depthTest, false);
  assert.equal(mesh.material.depthWrite, false);
  assert.equal(mesh.material.side, T.DoubleSide);

  const motion = MVStudioStageMotion.apply(T, root);
  const values = { animation: "clip", timeScale: 1, clipIn: 0 };
  const controls = {
    quality: { values: { stage_overlay_effect: true } },
    tracks: [{ id: "track", nativeClass: "AnimationTrack", binding,
      events: [{ id: "event", start: 0, duration: 2, values }] }],
    stageMotion: { quality: { track: "stage_overlay_effect" }, mix: { event: {} }, clips: {
      clip: { start: 0, duration: 2, channels: [
        { path: 0, kind: "overlayTint", curves: [["constant", 1], ["constant", 1], ["constant", .5], ["linear", [[0, 0], [1, .6]]]] },
        { path: 0, kind: "overlayUV", curves: [1, 2, .25, .8].map((value) => ["constant", value]) }
      ] }
    } }
  };
  motion.update(0, controls);
  assert.equal(overlay.hasVisible(), false);
  motion.update(.5, controls);
  assert.equal(overlay.hasVisible(), true);
  assert.equal(overlay.hasDepthTest(), false);
  assert.deepEqual(mesh.material.uniforms.uTint.value.toArray(), [1, 1, .5, .3]);
  assert.deepEqual(mesh.material.uniforms.uTextureST.value.toArray(), [1, 2, .25, .8]);

  const renderer = { autoClear: true, domElement: { width: 1600, height: 900 }, render(scene, camera) {
    assert.equal(scene.background, null);
    assert.equal(this.autoClear, false);
    assert.equal(camera.layers.mask, 1 << 20);
    assert.deepEqual(camera.position.toArray(), [0, 200, -10]);
    assert.equal(camera.top, 5);
    assert.equal(camera.right, 5 * (1600 / 900));
  } };
  const background = root.background;
  MVStudioStageOverlay.create(T, renderer).draw(root);
  assert.equal(root.background, background);
  assert.equal(root.autoUpdate, true);
  assert.equal(renderer.autoClear, true);
  controls.quality.values.stage_overlay_effect = false;
  motion.update(.5, controls);
  assert.equal(overlay.hasVisible(), false);
  overlay.dispose();
  assert.equal(mesh.layers.mask, 1);
  assert.equal(mesh.material, material);
  for (const [cull, side] of [[1, T.BackSide], [2, T.FrontSide]]) {
    mesh.geometry.userData.mvStageOverlay.cull = cull;
    const sidedOverlay = await MVStudioStageOverlay.apply(T, root);
    assert.equal(mesh.material.side, side);
    sidedOverlay.dispose();
  }
  mesh.geometry.userData.mvStageOverlay.depthTest = true;
  marker.visible = true;
  const depthOverlay = await MVStudioStageOverlay.apply(T, root);
  assert.equal(mesh.material.depthTest, true);
  assert.equal(mesh.material.depthFunc, T.LessEqualDepth);
  assert.equal(mesh.material.depthWrite, false);
  assert.equal(depthOverlay.hasDepthTest(), true);
  marker.visible = false;
  assert.equal(depthOverlay.hasDepthTest(), false);
  marker.visible = true;
  mesh.material.uniforms.uTint.value.w = 0;
  assert.equal(depthOverlay.hasDepthTest(), false);
  mesh.material.uniforms.uTint.value.w = 1;
  assert.equal(depthOverlay.hasDepthTest(), true);
  depthOverlay.dispose();
  assert.equal(depthOverlay.hasDepthTest(), false);
  console.log("Native screen overlay: layer and camera, per-renderer material curves, blending and no clear.");
}

async function testRequiredMaterial() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_ove_stock/Efect_root";
  const addScene = (ambiguous) => {
    const scene = new T.Scene(), group = new T.Group();
    scene.add(group);
    group.userData.mvStageNode = {active: true, path: 0, binding};
    const overlayNode = (path, active) => {
      const owner = new T.Group();
      owner.userData.mvStageNode = {active, path, binding};
      group.add(owner);
      const mesh = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial());
      mesh.geometry.userData.mvStageOverlay = {
        texture: null, tint: [1, 1, 1, .25], uv: [1, 1, 0, 0], vertexColor: false, queue: 3000,
      };
      owner.add(mesh);
      if (ambiguous && path === 2) {
        owner.add(mesh.clone());
        owner.userData.mvStageOverlayChannels = {overlayTint: new T.Vector4(1, 1, 1, .25), overlayUV: new T.Vector4()};
      }
      return {owner, mesh};
    };
    return {scene, group, first: overlayNode(1, true), second: overlayNode(2, false)};
  };
  const scalar = (value) => ["constant", value];
  const controls = {
    quality: {values: {stage_control: false, stage_overlay_effect: true}},
    tracks: [{id: "track", nativeClass: "AnimationTrack", binding, events: [
      {id: "event", start: 1, duration: 1, values: {animation: "clip"}},
    ]}],
    stageMotion: {quality: {track: "stage_overlay_effect"}, mix: {event: {}}, clips: {
      clip: {start: 0, duration: 1, sampleTimeF32: true, requiresOverlayMaterial: true, channels: [
        {path: 1, kind: "translation", curves: [4, 5, 6].map(scalar)},
        {path: 1, kind: "overlayTint", curves: [scalar(1), scalar(1), scalar(1), ["linear", [[0, 0], [1, 1]]]]},
        {path: 2, kind: "visibility", curves: [scalar(.002)]},
        {path: 2, kind: "overlayUV", curves: [1, 2, .25, .75].map(scalar)},
      ]},
    }},
  };

  const ready = addScene(false);
  const overlay = await MVStudioStageOverlay.apply(T, ready.scene);
  const motion = MVStudioStageMotion.apply(T, ready.scene);
  motion.update(1.6, controls);
  assert.deepEqual(ready.first.owner.position.toArray(), [-4, 5, 6]);
  assert.equal(ready.first.mesh.material.uniforms.uTint.value.w, Math.fround(.6), "native AnimationClipPlayable reconstructs f32 time");
  assert.deepEqual(ready.second.mesh.material.uniforms.uTextureST.value.toArray(), [1, 2, .25, .75]);
  assert.equal(ready.second.owner.visible, true, "the native GameObject binding treats .002 as active");
  assert.equal(overlay.hasVisible(), true, "quality StageControl is independent of this OverlayEffect track");

  motion.update(.5, controls);
  assert.deepEqual(ready.first.owner.position.toArray(), [0, 0, 0]);
  assert.equal(ready.first.mesh.material.uniforms.uTint.value.w, .25);
  assert.equal(ready.second.owner.visible, false);
  assert.deepEqual(ready.second.mesh.material.uniforms.uTextureST.value.toArray(), [1, 1, 0, 0]);
  motion.update(1.5, controls);
  controls.quality.values.stage_overlay_effect = false;
  motion.update(1.5, controls);
  assert.equal(ready.group.visible, false);
  assert.equal(overlay.hasVisible(), false);
  assert.deepEqual(ready.first.owner.position.toArray(), [0, 0, 0]);
  controls.quality.values.stage_overlay_effect = true;
  overlay.dispose();

  const ambiguous = addScene(true);
  const partialOverlay = await MVStudioStageOverlay.apply(T, ambiguous.scene);
  assert.equal(ambiguous.first.mesh.layers.mask, 1 << 20);
  assert.equal(ambiguous.second.mesh.layers.mask, 1);
  const partialMotion = MVStudioStageMotion.apply(T, ambiguous.scene);
  partialMotion.update(1.6, controls);
  assert.deepEqual(ambiguous.first.owner.position.toArray(), [0, 0, 0], "a missing unique overlay holder skips the whole clip");
  assert.equal(ambiguous.first.mesh.material.uniforms.uTint.value.w, .25);
  assert.equal(ambiguous.second.owner.visible, false);
  partialOverlay.dispose();
  console.log("Required native overlay channels are atomic, float32-sampled and independently quality-gated.");
}

async function testSkinnedOverlayMaterial() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_ove_stock/Effect_root";
  const root = new T.Group(), owner = new T.Group(), partition = new T.Group();
  root.add(owner);
  owner.add(partition);
  owner.userData.mvStageNode = {active: true, path: 0, binding};
  partition.userData.mvStageSkin = true;
  const staticGeometry = new T.PlaneGeometry(), skinGeometry = new T.PlaneGeometry();
  const fields = {texture: null, tint: [1, 1, 1, .25], uv: [1, 1, 0, 0], vertexColor: false, queue: 3000};
  staticGeometry.userData.mvStageOverlay = {...fields};
  skinGeometry.userData.mvStageOverlay = {...fields, rendererClass: 137};
  skinGeometry.setAttribute("skinIndex", new T.Uint16BufferAttribute(Array(4).fill([0, 1, 0, 0]).flat(), 4));
  skinGeometry.setAttribute("skinWeight", new T.Float32BufferAttribute(Array(4).fill([.75, .25, 0, 0]).flat(), 4));
  const original = new T.MeshBasicMaterial();
  const plane = new T.Mesh(staticGeometry, original);
  const skin = new T.SkinnedMesh(skinGeometry, original);
  const firstJoint = new T.Bone(), secondJoint = new T.Bone();
  root.add(firstJoint);
  firstJoint.add(secondJoint);
  owner.add(plane);
  partition.add(skin);
  skin.bind(new T.Skeleton([firstJoint, secondJoint]), new T.Matrix4());

  const worldMotion = (rendererClasses) => {
    const scalar = (value) => ["constant", value];
    const channels = [
      {path: 0, kind: "translation", curves: [3, 0, 0].map(scalar)},
      ...rendererClasses.map((rendererClass, index) =>
        ({path: 0, rendererClass, kind: "overlayTint", curves: [1, 1, 1, .5 + index * .25].map(scalar)})),
    ];
    return {
      tracks: [{id: "motion", nativeClass: "AnimationTrack", binding, events: [
        {id: "event", start: 1, duration: 1, values: {animation: "clip"}},
      ]}],
      stageMotion: {clips: {clip: {start: 0, duration: 1, requiresOverlayMaterial: true, channels}}, mix: {event: {}}},
    };
  };

  const overlay = await MVStudioStageOverlay.apply(T, root);
  assert.equal(plane.material.skinning, false);
  assert.equal(skin.material.skinning, true);
  assert.equal(skin.frustumCulled, false);
  assert.equal(skin.layers.mask, 1 << 20);
  assert.equal(skin.material.depthTest, false);
  assert.equal(skin.material.depthWrite, false);
  assert.equal(skin.material.blendDst, T.OneFactor);
  assert.match(skin.material.vertexShader, /#include <skinbase_vertex>\s+#include <skinning_vertex>/);
  const stageMotion = MVStudioStageMotion.apply(T, root), both = worldMotion([undefined, 137]);
  stageMotion.update(1.5, both);
  assert.equal(plane.material.uniforms.uTint.value.w, .5);
  assert.equal(skin.material.uniforms.uTint.value.w, .75);
  assert.equal(owner.position.x, -3);
  stageMotion.update(.5, both);
  assert.equal(plane.material.uniforms.uTint.value.w, .25);
  assert.equal(skin.material.uniforms.uTint.value.w, .25);
  assert.equal(owner.position.x, 0);

  secondJoint.position.x = 4;
  root.updateMatrixWorld(true);
  const point = new T.Vector3().fromBufferAttribute(skinGeometry.getAttribute("position"), 0);
  assert.deepEqual(skin.boneTransform(0, point.clone()).toArray(), [point.x + 1, point.y, point.z]);
  overlay.dispose();
  overlay.dispose();
  assert.equal(skin.material, original);
  assert.equal(skin.frustumCulled, true);
  assert.equal(skin.layers.mask, 1);

  delete skinGeometry.userData.mvStageOverlay.rendererClass;
  const legacyOnly = await MVStudioStageOverlay.apply(T, root);
  assert.equal(skin.material, original, "a skinned mesh needs authenticated class 137 metadata");
  const bad = worldMotion([23, 137]);
  stageMotion.update(1.5, bad);
  assert.equal(owner.position.x, 0, "missing class 137 cannot use the static holder or move the root");
  assert.equal(plane.material.uniforms.uTint.value.w, .25);
  legacyOnly.dispose();

  owner.remove(plane);
  skinGeometry.userData.mvStageOverlay.rendererClass = 137;
  const skinnedOnly = await MVStudioStageOverlay.apply(T, root);
  stageMotion.update(1.5, worldMotion([undefined]));
  assert.equal(skin.material.uniforms.uTint.value.w, .25, "a legacy classless required channel targets static only");
  assert.equal(owner.position.x, 0);
  skinnedOnly.dispose();
  Object.assign(skinGeometry.userData.mvStageOverlay, {world: true, depthTest: true, queue: 3010});
  const worldSkin = await MVStudioStageOverlay.apply(T, root);
  assert.equal(skin.material.skinning, true);
  assert.equal(skin.frustumCulled, false);
  assert.equal(skin.layers.mask, 1);
  assert.equal(skin.renderOrder, 3010);
  assert.equal(worldSkin.hasVisible(), false);
  assert.equal(worldSkin.hasDepthTest(), false);
  worldSkin.dispose();
  console.log("Weighted overlay deforms on layer 20 and isolates both native renderer classes.");
}

async function testWorldMaterialScope() {
  const root = new T.Group(), owner = new T.Group();
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/Floor";
  owner.userData.mvStageNode = {active: true, path: 0, binding};
  root.add(owner);
  const add = (fields, parent = owner) => {
    const mesh = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial());
    mesh.geometry.userData.mvStageOverlay = {
      texture: null, tint: [1, 1, 1, .25], uv: [1, 1, 0, 0], vertexColor: false, queue: 3010, ...fields,
    };
    parent.add(mesh);
    return mesh;
  };
  const closed = [], borrowed = new T.Texture({width: 4, height: 4});
  borrowed.encoding = T.sRGBEncoding;
  borrowed.minFilter = T.LinearFilter;
  const mip = (size) => new T.Texture({width: size, height: size, close: () => closed.push(size)});
  const levels = [borrowed, mip(2), mip(1)];
  const authored = {texture: 0, mainSampler: {mipmaps: [1, 2], filterMode: 1, anisotropy: 8}};
  const overlayMesh = add(authored), worldMesh = add({...authored, world: true, depthTest: true, cull: 2});
  overlayMesh.material.map = worldMesh.material.map = borrowed;
  const unknownDepth = add({world: true});
  const original = unknownDepth.material;
  const readerOwner = new T.Group();
  readerOwner.userData.mvStageNode = {active: true, path: 7, binding};
  owner.add(readerOwner);
  const reader = add({world: true, depthTest: true, alphaBlend: true, stencilRef: 2, queue: 2910,
    sortCenter: [0, 0, 0]}, readerOwner);
  const unsupportedReader = add({world: true, depthTest: true, alphaBlend: true, stencilRef: 256}, readerOwner);
  const unsupportedOriginal = unsupportedReader.material;
  const panel = await MVStudioStageOverlay.apply(T, root, {async getDependency(type, index) { return levels[index]; }});
  assert.equal(worldMesh.layers.mask, 1);
  assert.equal(worldMesh.renderOrder, 3010);
  assert.equal(worldMesh.material.depthTest, true);
  assert.equal(worldMesh.material.depthFunc, T.LessEqualDepth);
  assert.equal(worldMesh.material.depthWrite, false);
  assert.equal(worldMesh.material.side, T.FrontSide);
  assert.equal(worldMesh.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(worldMesh.material.blendDst, T.OneFactor);
  assert.equal(worldMesh.material.stencilWrite, false);
  assert.equal(reader.layers.mask, 1);
  assert.equal(reader.renderOrder, 2910);
  assert.equal(reader.material.depthTest, true);
  assert.equal(reader.material.depthFunc, T.LessEqualDepth);
  assert.equal(reader.material.depthWrite, false);
  assert.equal(reader.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(reader.material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(reader.material.blendSrcAlpha, T.SrcAlphaFactor);
  assert.equal(reader.material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
  assert.equal(reader.material.stencilWrite, true);
  assert.equal(reader.material.stencilFunc, T.EqualStencilFunc);
  assert.equal(reader.material.stencilRef, 2);
  assert.equal(reader.material.stencilWriteMask, 255);
  assert.equal(reader.material.stencilFuncMask, 255);
  for (const key of ["stencilFail", "stencilZFail", "stencilZPass"]) assert.equal(reader.material[key], T.KeepStencilOp);
  assert.equal(unsupportedReader.material, unsupportedOriginal);
  const worldTexture = worldMesh.material.uniforms.uTexture.value;
  assert.deepEqual(worldTexture.mipmaps, levels.map(level => level.image));
  assert.equal(worldTexture.minFilter, T.LinearMipmapNearestFilter);
  assert.equal(worldTexture.magFilter, T.LinearFilter);
  assert.equal(worldTexture.anisotropy, 8);
  assert.equal(worldTexture.generateMipmaps, false);
  assert.equal(worldTexture.encoding, T.LinearEncoding);
  assert.deepEqual(overlayMesh.material.uniforms.uTexture.value.mipmaps, []);
  assert.deepEqual(borrowed.mipmaps, []);
  assert.equal(borrowed.encoding, T.sRGBEncoding);
  assert.equal(unknownDepth.material, original, "sources outside the proved world pass are unmodified");
  assert.equal(overlayMesh.layers.mask, 1 << 20);
  assert.equal(panel.hasDepthTest(), false, "world draws never request a layer-20 depth copy");
  overlayMesh.visible = false;
  assert.equal(panel.hasVisible(), false, "visible world draws cannot schedule the layer-20 camera");

  const projectFor = (materialScope) => {
    const scalar = (value) => ["constant", value];
    return {
      tracks: [{id: "motion", nativeClass: "AnimationTrack", binding, events: [
        {id: "event", start: 1, duration: 1, values: {animation: "clip"}},
      ]}],
      stageMotion: {mix: {event: {materialScope}}, clips: {clip: {start: 0, duration: 1, requiresOverlayMaterial: true, channels: [
        {path: 0, kind: "translation", curves: [3, 0, 0].map(scalar)},
        {path: 0, kind: "overlayTint", curves: [1, 1, 1, .75].map(scalar)},
      ]}}},
    };
  };
  const alpha = (mesh) => mesh.material.uniforms.uTint.value.w;
  const motion = MVStudioStageMotion.apply(T, root);
  const sharedClip = projectFor("world");
  sharedClip.tracks[0].events.push({id: "legacy", start: 2, duration: 1, values: {animation: "clip"}});
  sharedClip.stageMotion.mix.legacy = {};
  motion.update(1.5, sharedClip);
  assert.equal(owner.position.x, -3);
  assert.equal(alpha(worldMesh), .75);
  assert.equal(alpha(overlayMesh), .25);
  motion.update(2.5, sharedClip);
  assert.equal(alpha(worldMesh), .25);
  assert.equal(alpha(overlayMesh), .75);
  motion.update(1.5, projectFor("invalid"));
  assert.equal(owner.position.x, 0);
  assert.equal(alpha(overlayMesh), .25);
  panel.dispose();
  assert.deepEqual(closed, [2, 1]);
  console.log("Native transparent world draws use authored depth and keep isolated layer-20 ownership.");
}

async function testTransparentBoundsRecords() {
  const root = new T.Group();
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/Curtain";
  const fields = {world: true, depthTest: true, alphaBlend: true, stencilRef: 2, queue: 2910,
    texture: null, tint: [1, 1, 1, .25], uv: [1, 1, 0, 0], vertexColor: false};
  const owner = (path) => {
    const group = new T.Group();
    group.userData.mvStageNode = {active: true, binding, path};
    root.add(group);
    return group;
  };
  const planeGeometry = new T.PlaneGeometry(), skinGeometry = new T.PlaneGeometry();
  planeGeometry.userData.mvStageOverlay = {...fields, sortCenter: [0, 0, 19]};
  skinGeometry.userData.mvStageOverlay = {...fields, rendererClass: 137, sortJoint: 0, sortCenter: [0, 0, 0]};
  skinGeometry.setAttribute("skinIndex", new T.Uint16BufferAttribute(new Uint16Array(16), 4));
  skinGeometry.setAttribute("skinWeight", new T.Float32BufferAttribute(Array(4).fill([1, 0, 0, 0]).flat(), 4));
  const plane = new T.Mesh(planeGeometry, new T.MeshBasicMaterial());
  const skin = new T.SkinnedMesh(skinGeometry, new T.MeshBasicMaterial());
  const joint = new T.Bone();
  skin.userData.mvStageSkin = true;
  plane.position.z = -20;
  plane.renderOrder = 17;
  skin.position.z = -2;
  joint.position.z = -16;
  owner(1).add(plane);
  owner(2).add(skin, joint);
  skin.bind(new T.Skeleton([joint]), new T.Matrix4());

  const invalidGeometry = new T.PlaneGeometry();
  invalidGeometry.userData.mvStageOverlay = {...fields, sortCenter: [0, 0]};
  const invalidMaterial = new T.MeshBasicMaterial();
  const invalid = new T.Mesh(invalidGeometry, invalidMaterial);
  owner(3).add(invalid);

  const controller = await MVStudioStageOverlay.apply(T, root);
  const entries = controller.sortEntries();
  assert.equal(controller.sortEntries(), entries);
  assert.deepEqual(entries, [
    {node: plane, anchor: plane, center: new T.Vector3(0, 0, 19), queue: 2910},
    {node: skin, anchor: joint, center: new T.Vector3(), queue: 2910},
  ]);
  assert.equal(plane.renderOrder, 2910);
  assert.equal(skin.renderOrder, 2910);
  assert.equal(invalid.material, invalidMaterial);
  controller.dispose();
  assert.equal(plane.renderOrder, 17);
  assert.equal(skin.renderOrder, 0);
  assert.deepEqual(entries, []);
  console.log("Native transparent readers supply stable mesh or root-joint bounds in their authored queue.");
}

async function testWorldMatcap() {
  const scene = new T.Group();
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/Matcap";
  const original = new T.MeshBasicMaterial();
  const fields = {matcap: true, world: true, alphaBlend: true, depthTest: true, cull: 2, queue: 3000,
    texture: 0, mainSampler: {mipmaps: [1], filterMode: 1, anisotropy: 8}, sortCenter: [0, 0, 0],
    tint: [.4, .8, .9, .6], addColor: [.2, .3, -.1], vertexColor: true};
  const make = (path, overrides = {}, skinned = false) => {
    const owner = new T.Group(), geometry = new T.PlaneGeometry();
    scene.add(owner);
    owner.userData.mvStageNode = {active: true, binding, path};
    geometry.deleteAttribute("uv");
    geometry.setAttribute("_stage_color", new T.Uint8BufferAttribute(Array(4).fill([255, 128, 64, 192]).flat(), 4, true));
    geometry.userData.mvStageOverlay = {...fields, ...overrides};
    const mesh = skinned ? new T.SkinnedMesh(geometry, original) : new T.Mesh(geometry, original);
    owner.add(mesh);
    if (skinned) {
      mesh.userData.mvStageSkin = true;
      geometry.setAttribute("skinIndex", new T.Uint16BufferAttribute(new Uint16Array(16), 4));
      geometry.setAttribute("skinWeight", new T.Float32BufferAttribute(Array(4).fill([1, 0, 0, 0]).flat(), 4));
      const joint = new T.Bone();
      owner.add(joint);
      mesh.bind(new T.Skeleton([joint]), new T.Matrix4());
    }
    return {owner, mesh, geometry};
  };
  const rigid = make(1), skin = make(2, {rendererClass: 137, sortJoint: 0}, true);
  const white = make(3, {texture: null, queue: 3001});
  const noNormal = make(4);
  noNormal.geometry.deleteAttribute("normal");
  const noColor = make(5);
  noColor.geometry.deleteAttribute("_stage_color");
  const badStencil = make(6, {stencilRef: 2}), wrongScope = make(7, {world: false});
  const opaqueQueue = make(8, {queue: 2000}), badAdd = make(9, {addColor: [0, Infinity, 0]});
  const base = new T.Texture({width: 2, height: 2}), mip = new T.Texture({width: 1, height: 1});
  const controller = await MVStudioStageOverlay.apply(T, scene, {
    async getDependency(type, index) { return [base, mip][index]; },
  });
  for (const {mesh} of [rigid, skin, white]) {
    const material = mesh.material;
    assert.equal(material.defines.MATCAP, 1);
    assert.equal(material.side, T.FrontSide);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.depthTest, true);
    assert.equal(material.depthWrite, false);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendSrcAlpha, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneMinusSrcAlphaFactor);
    assert.equal(material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
    assert.equal(material.stencilWrite, false);
    assert.equal(material.uniforms.uTextureST, undefined);
    assert.deepEqual(material.uniforms.uAddColor.value.toArray(), fields.addColor);
    assert.equal(mesh.layers.mask, 1);
  }
  assert.equal(rigid.mesh.material.uniforms.uTexture.value, skin.mesh.material.uniforms.uTexture.value);
  assert.deepEqual(skin.mesh.material.uniforms.uTexture.value.mipmaps, [base.image, mip.image]);
  assert.equal(white.mesh.material.uniforms.uTexture.value.isDataTexture, true);
  assert.equal(controller.hasVisible(), false);
  assert.equal(controller.hasDepthTest(), false);
  assert.equal(skin.mesh.material.skinning, true);
  assert.equal(skin.mesh.frustumCulled, false);
  assert.match(skin.mesh.material.vertexShader, /#include <skinnormal_vertex>\s+vec3 viewNormal = normalize\(normalMatrix \* objectNormal\)/);
  assert.match(skin.mesh.material.vertexShader, /vec2\(0\.5, -0\.5\) \* viewNormal\.xy/);
  assert.match(skin.mesh.material.fragmentShader, /surface\.rgb \+= uAddColor;[\s\S]+surface \* vColor \* uTint/);
  for (const {mesh} of [noNormal, noColor, badStencil, wrongScope, opaqueQueue, badAdd]) assert.equal(mesh.material, original);
  assert.equal(MVStudioStageOverlay.materialChannel(skin.owner, "overlayUV", 137, "world"), undefined);

  const event = {id: "ev", start: 1, duration: 1, values: {animation: "clip"}};
  const project = {
    tracks: [{id: "track", nativeClass: "AnimationTrack", binding, events: [event]}],
    stageMotion: {mix: {ev: {materialScope: "world"}}, clips: {
      clip: {start: 0, duration: 1, requiresOverlayMaterial: true, channels: [
        {path: 2, rendererClass: 137, kind: "overlayTint", curves: [1, .5, 0, .25].map(value => ["constant", value])},
      ]},
    }},
  };
  const motion = MVStudioStageMotion.apply(T, scene);
  motion.update(1.5, project);
  assert.equal(motion.accepts(event), true);
  assert.deepEqual(skin.mesh.material.uniforms.uTint.value.toArray(), [1, .5, 0, .25]);
  assert.deepEqual(rigid.mesh.material.uniforms.uTint.value.toArray(), fields.tint);
  motion.update(.5, project);
  assert.deepEqual(skin.mesh.material.uniforms.uTint.value.toArray(), fields.tint);
  controller.dispose();
  assert.equal(skin.mesh.material, original);
  assert.equal(skin.mesh.frustumCulled, true);
  assert.equal(MVStudioStageOverlay.materialChannel(skin.owner, "overlayTint", 137, "world"), undefined);
  console.log("Native MatCap uses camera-space normals and vertex RGBA with the authored world pass.");
}

async function testWorldAdditiveDepthWrites() {
  const root = new T.Group();
  function add(path, fields) {
    const owner = new T.Group();
    owner.userData.mvStageNode = {active: true, path, binding: "/EntryPoint/Live/Stages/MainStage/Effect/Floor"};
    const original = new T.MeshBasicMaterial();
    const mesh = new T.Mesh(new T.PlaneGeometry(), original);
    mesh.geometry.userData.mvStageOverlay = {
      world: true, depthTest: true, queue: 3000, texture: null,
      tint: [1, 1, 1, 0], uv: [1, 1, 0, 0], vertexColor: true, cull: 0, ...fields,
    };
    owner.add(mesh);
    root.add(owner);
    return {mesh, original};
  }
  const floor = add(1, {depthWrite: true, sortCenter: [.25, .5, .75]}), legacy = add(2, {sortCenter: [.5, 0]});
  const invalid = [
    add(3, {depthWrite: true, world: false}),
    add(4, {depthWrite: true, alphaBlend: true, stencilRef: 2, sortCenter: [0, 0, 0]}),
    add(5, {depthWrite: "true"}),
    add(6, {depthWrite: true, queue: 2000}),
  ];
  const panel = await MVStudioStageOverlay.apply(T, root);
  assert.equal(floor.mesh.material.transparent, true);
  assert.equal(floor.mesh.material.uniforms.uTint.value.w, 0);
  assert.equal(floor.mesh.material.depthTest, true);
  assert.equal(floor.mesh.material.depthWrite, true);
  assert.equal(floor.mesh.material.depthFunc, T.LessEqualDepth);
  assert.equal(floor.mesh.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(floor.mesh.material.blendDst, T.OneFactor);
  assert.equal(floor.mesh.material.stencilWrite, false);
  assert.equal(floor.mesh.renderOrder, 3000);
  assert.equal(legacy.mesh.material.depthWrite, false);
  assert.deepEqual(panel.sortEntries(), [
    {node: floor.mesh, anchor: floor.mesh, center: new T.Vector3(.25, .5, .75), queue: 3000},
  ]);
  for (const {mesh, original} of invalid) assert.equal(mesh.material, original);
  assert.equal(panel.hasDepthTest(), false);
  panel.dispose();
  assert.equal(floor.mesh.material, floor.original);
  console.log("Native main-camera additive transparency retains authored depth writes.");
}

run().then(testRequiredMaterial).then(testSkinnedOverlayMaterial).then(testWorldMaterialScope)
  .then(testTransparentBoundsRecords).then(testWorldMatcap).then(testWorldAdditiveDepthWrites).catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
