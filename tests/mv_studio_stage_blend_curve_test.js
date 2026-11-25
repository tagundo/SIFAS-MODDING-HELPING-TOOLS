"use strict";

// A world AnimationClip's MeshRenderer _TintColor, _AmbientColor and
// _BlendRate curves drive an AS/Blend/Opaque renderer's values, which its
// property block holds over the shared material (10120 sky_01: _BlendRate
// steps from the day map to the night map at 92.0167 s).
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-stage-motion.js");

const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so0120_01/root";
const SKY = 769206466;  // crc32("sky_01")

function blendMeta(overrides = {}) {
  return {
    shader: "blend", colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [1, 1, 1, 0]}, ambientDefaults: null, cull: 2,
    blendRate: 0, uvTransform: [1, 1, 0, 0], blendUVTransform: [2, 1, .5, 0], vertexColor: true,
    mainTexture: 0, blendTexture: 1, ...overrides,
  };
}

function textures() {
  const made = [0, 1, 2].map((index) => {
    const texture = new T.DataTexture(new Uint8Array([index, 0, 0, 255]), 1, 1);
    texture.name = "texture " + index;
    return texture;
  });
  const requested = [];
  return {made, requested, parser: {getDependency: async (kind, index) => {
    requested.push([kind, index]);
    return made[index];
  }}};
}

function dome(parent, meta) {
  const geometry = new T.PlaneGeometry();
  geometry.setAttribute("_stage_color", new T.Float32BufferAttribute([1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0], 4));
  geometry.userData.mvStageMaterial = meta;
  const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial());
  parent.add(mesh);
  return mesh;
}

async function channelTest() {
  const root = new T.Group(), owner = new T.Group();
  owner.userData.mvStageNode = {active: true, binding, path: SKY};
  root.add(owner);
  const sky = dome(owner, blendMeta());
  const {parser} = textures();
  const controller = await MVStudioStageMaterial.apply(T, root, parser);
  const material = sky.material;
  const tint = MVStudioStageMaterial.materialChannel(owner, "overlayTint");
  const ambient = MVStudioStageMaterial.materialChannel(owner, "overlayAmbient");
  const rate = MVStudioStageMaterial.materialChannel(owner, "overlayScalar", "_BlendRate");
  assert.equal(tint, material.uniforms.tint.value);
  assert.equal(ambient, material.uniforms.ambient.value);
  assert.equal(rate, material.uniforms.blendRate);
  assert.equal(MVStudioStageMaterial.materialChannel(owner, "overlayScalar", "_Density"), undefined);
  assert.equal(MVStudioStageMaterial.materialChannel(owner, "overlayUV"), undefined,
    "_MainTex_ST is not an AS/Blend/Opaque property");
  // A renderer with two AS/Blend/Opaque materials has no single property holder.
  const pair = new T.Group();
  pair.userData.mvStageNode = {active: true, binding, path: 7};
  root.add(pair);
  controller.dispose();
  assert.equal(MVStudioStageMaterial.materialChannel(owner, "overlayTint"), undefined, "dispose releases the holder");
  dome(pair, blendMeta());
  dome(pair, blendMeta());
  const second = await MVStudioStageMaterial.apply(T, root, parser);
  assert.equal(MVStudioStageMaterial.materialChannel(pair, "overlayScalar", "_BlendRate"), undefined);
  assert.ok(MVStudioStageMaterial.materialChannel(owner, "overlayScalar", "_BlendRate"));
  second.dispose();
}

async function curveTest() {
  const root = new T.Group(), effect = new T.Group(), owner = new T.Group();
  effect.userData.mvStageNode = {active: true, binding, path: 0};
  owner.userData.mvStageNode = {active: true, binding, path: SKY};
  root.add(effect);
  effect.add(owner);
  const sky = dome(owner, blendMeta());
  const {parser} = textures();
  const material = await MVStudioStageMaterial.apply(T, root, parser);
  const motion = MVStudioStageMotion.apply(T, root);
  // clip_stg_so0120_01: _TintColor constant 1, _BlendRate 0 until 92.01667 s, then 1.
  const step = ["cubic", [[-3.4028234663852886e+38, [0, 0, 0, 0]], [0, [0, 0, 0, 0]],
    [92.01667022705078, [0, 0, 0, 1]], [121.9000015258789, [0, 0, 0, 1]]]];
  const one = ["cubic", [[-3.4028234663852886e+38, [0, 0, 0, 1]], [0, [0, 0, 0, 1]]]];
  const event = {id: "sky", start: 0, duration: 121.9, values: {animation: "clip_stg_so0120_01", postExtrapolationMode: 1}};
  const project = {
    tracks: [{id: "control", nativeClass: "AnimationTrack", binding, events: [event]}],
    quality: {values: {stage_control: true}},
    stageMotion: {
      quality: {control: "stage_control"},
      mix: {sky: {materialScope: "world", postInfinite: true}},
      clips: {clip_stg_so0120_01: {start: 0, duration: 121.9, loop: false, requiresOverlayMaterial: true,
        sampleTimeF32: true, channels: [
          {path: SKY, kind: "overlayTint", curves: [one, one, one, one]},
          {path: SKY, kind: "overlayScalar", property: "_BlendRate", curves: [step]},
        ]}},
    },
  };
  const uniforms = sky.material.uniforms;
  motion.update(44.5, project);
  material.update(44.5, project, null, null);
  assert.equal(uniforms.blendRate.value, 0, "the day map before the switch");
  assert.ok(motion.accepts(event));
  motion.update(92, project);
  assert.equal(uniforms.blendRate.value, 0);
  motion.update(92.1, project);
  assert.equal(uniforms.blendRate.value, 1, "the night map from 92.017 s");
  assert.deepEqual(uniforms.tint.value.toArray(), [1, 1, 1, 1]);
  motion.update(130, project);
  assert.equal(uniforms.blendRate.value, 1, "post-extrapolation holds the last value");
  assert.ok(motion.curveTargets().has(uniforms.blendRate));
  project.tracks[0].muted = true;
  motion.update(100, project);
  assert.equal(uniforms.blendRate.value, 0, "a muted track restores the material value");
  project.tracks[0].muted = false;

  // An ambient component writing the shared material does not override the
  // property the renderer's property block holds.
  const held = {...project, stageMotion: {...project.stageMotion, clips: {clip_stg_so0120_01: {
    ...project.stageMotion.clips.clip_stg_so0120_01, channels: [
      ...project.stageMotion.clips.clip_stg_so0120_01.channels,
      {path: SKY, kind: "overlayAmbient", curves: [["constant", .2], ["constant", .3], ["constant", .4], ["constant", .5]]},
    ]}}}};
  motion.update(10, held);
  assert.deepEqual(uniforms.ambient.value.toArray().map(v => Math.round(v * 10) / 10), [.2, .3, .4, .5]);

  // A clip whose renderer has no AS/Blend/Opaque holder is skipped whole.
  const other = new T.Group();
  other.userData.mvStageNode = {active: true, binding, path: 5};
  effect.add(other);
  const partial = {...project, stageMotion: {...project.stageMotion, clips: {clip_stg_so0120_01: {
    ...project.stageMotion.clips.clip_stg_so0120_01, channels: [
      {path: 5, kind: "overlayScalar", property: "_BlendRate", curves: [step]}]}}}};
  const lone = MVStudioStageMotion.apply(T, root);
  lone.update(100, partial);
  assert.equal(lone.accepts(event), false);
  material.dispose();
}

async function ambientHoldTest() {
  // A blend material in a LiveCoreStageAmbient list keeps its curve-held tint.
  const root = new T.Group(), owner = new T.Group();
  owner.userData.mvStageNode = {active: true, binding, path: SKY};
  root.add(owner);
  const sky = dome(owner, blendMeta({ambientDefaults: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]}}));
  const {parser} = textures();
  const material = await MVStudioStageMaterial.apply(T, root, parser);
  const project = {tracks: []};
  const lighting = {baseAmbient: [.5, .5, .5, .5], baseTint: [.25, .25, .25, 1]};
  material.update(1, project, lighting, null);
  assert.deepEqual(sky.material.uniforms.tint.value.toArray(), [.25, .25, .25, 1]);
  assert.deepEqual(sky.material.uniforms.ambient.value.toArray(), [.5, .5, .5, .5], "the base light writes the material");
  const tint = MVStudioStageMaterial.materialChannel(owner, "overlayTint");
  tint.set(.1, .2, .3, 1);
  material.update(2, project, {baseAmbient: [.6, .6, .6, .6], baseTint: [.5, .5, .5, 1]}, null);
  assert.deepEqual(tint.toArray(), [.1, .2, .3, 1], "the property block value wins over the material");
  assert.deepEqual(sky.material.uniforms.ambient.value.toArray(), [.6, .6, .6, .6]);
  material.dispose();
}

(async () => {
  await channelTest();
  await curveTest();
  await ambientHoldTest();
  console.log("AS/Blend/Opaque curves: _BlendRate, _TintColor and _AmbientColor on the renderer.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
