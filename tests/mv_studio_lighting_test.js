"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");

const { sample } = globalThis.MVStudioLighting;
const track = (name, binding, events) => ({ nativeClass: name, binding, events });
const transparent = [1, 1, 1, 0];
const opening = [0.15, 0.1847826, 0.25, 1];
const midway = [0.30, 0.3348837, 0.40, 1];
const localTint = [0.225, 0.25, 0.30, 0.9019608];
const base = (start, duration, tint, blend) => ({ start, duration, values: {
  playableClass: "LiveBaseLightClip", ambientColorType: 0, ambientMemberPosition: 1,
  ambientColor: transparent, ambientTintColor: tint, rimlightColorType: 0,
  rimlightColor: [0.5, 1, 0.5, 1], rimlightIntensity: 0.2, rimlightSharpness: 4, rimlightDirection: { x: 1, y: 2, z: 3 },
  ...blend,
}});
const local = (start, duration, easeIn) => ({ start, duration, values: {
  playableClass: "LiveMemberAmbientClip", colorSpecifiedType: 0, color: transparent, tintColor: localTint, easeIn,
}});
const project = { quality: { values: {} }, tracks: [
  track("LiveBaseLightTrack", "/EntryPoint/Live/Global/LiveBaseLightReciever",
    [base(0, 4, opening, { blendOut: 3 }), base(1, 6, midway, { blendIn: 3 })]),
  track("LiveMemberAmbientTrack", "/EntryPoint/Live/Members/Member2", [local(0, 5, 1)]),
  track("LiveRimlightTrack", "/EntryPoint/Live/Members/Member2", [{ start: 2, duration: 1, values: {
    playableClass: "LiveRimlightClip", colorSpecifiedType: 0, color: [1, 0.5, 0.5, 1],
    intensity: 0.3, sharpness: 2, direction: { x: -1, y: 3, z: 1 },
  } }]),
] };
const almost = (values, expected) => values.forEach((value, i) =>
  assert(Math.abs(value - expected[i]) < 1e-8, `${value} differs from ${expected[i]} at slot ${i}`));

let light = sample(project, 0.5);
almost(light.baseTint, opening);
almost(light.member(2).tint, [0.091875, 0.115489125, 0.1625, 0.9509804]);
light = sample(project, 1);
almost(light.member(2).ambient, transparent);
almost(light.member(2).tint, [0.03375, 0.04619565, 0.075, 0.9019608]);
light = sample(project, 2.5);
almost(light.baseTint, [0.225, 0.25983315, 0.325, 1]);
almost(light.member(2).tint, [0.050625, 0.0649582875, 0.0975, 0.9019608]);
assert.deepEqual(light.member(2).rim, { color: [0.5, 0.5, 0.25, 1], intensity: 0.5, power: 7, direction: [0, 5, 4, 0] });
light = sample(project, 5.5);
assert.equal(light.member(2).tint, null, "a native local gap restores default tint");
assert.deepEqual(light.member(2).ambient, transparent);
assert.deepEqual(light.member(1).tint, midway);

project.quality.values.base_light = false;
almost(sample(project, 1).member(2).tint, localTint);
project.quality.values.member_ambient = false;
project.quality.values.member_rim_light = false;
assert.equal(sample(project, 1).member(2), null);
console.log("Native MV base light crossfades, per-performer colors and quality gates passed");

async function testSingleStageAmbient() {
  const stage = "/EntryPoint/Live/Stages/MainStage";
  const plantBinding = stage + "/Model/Ambient/Ambient2", effectBinding = stage + "/Effect";
  const root = new T.Group(), texture = new T.Texture();
  const addSurface = (binding, shader, details = {}) => {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
    node.geometry.setAttribute("_stage_light_uv", node.geometry.getAttribute("uv"));
    node.geometry.setAttribute("_stage_emissive_uv", node.geometry.getAttribute("uv"));
    const colors = {_AmbientColor: [0, 0, 0, 0], _TintColor: [1, 1, 1, 1], _BlendColor: [0, 0, 0, 0]};
    node.geometry.userData.mvStageMaterial = {shader, colors, ambientDefaults: colors, uvTransform: [1, 1, 0, 0],
      singleAmbientBinding: binding, ...details};
    root.add(node);
    return node;
  };
  const plant = addSurface(plantBinding, "stage", {lightmap: 1, mipBias: 0, alphaCutoff: .5,
    emissive: {texture: 2, uvTransform: [1, 1, 0, 0], color: [1, .5, 0, 1], intensity: .75}});
  const effect = addSurface(effectBinding, "general"), original = plant.material;
  const decoded = [undefined, new T.Texture(), new T.Texture()];
  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency: async (type, index) => type === "texture" ? decoded[index] : null,
  });
  assert.equal(plant.material.defines.CUTOUT, 1);
  assert.equal(plant.material.defines.EMISSIVE, 1);
  assert.equal(plant.material.uniforms.alphaCutoff.value, .5);
  assert.equal(plant.material.uniforms.emissiveIntensity.value, .75);

  const clip = (start, ambient, tintColor, blendColor, fade) => ({
    start, duration: 2, values: {playableClass: "LiveStageSingleAmbientClip", colorSpecifiedType: 0,
      color: ambient, tintColor, blendColor, ...fade},
  });
  const localPlant = track("LiveStageSingleAmbientTrack", plantBinding, [
    clip(0, [0, 1, 0, .5], [1, 1, .5, 1], [0, 0, 1, 0], {blendOut: 1}),
    clip(1, [1, 0, 0, .5], [1, .5, 1, 1], [1, 0, 0, .5], {blendIn: 1}),
  ]);
  const localEffect = track("LiveStageSingleAmbientTrack", effectBinding, [
    clip(0, [0, 0, 1, .5], [1, 0, 1, 1], [1, 1, 1, 0]),
  ]);
  const stageProject = {tracks: [localPlant, localEffect], quality: {values: {stage_ambient: true}}};
  const lighting = {baseAmbient: [1, .5, 1, .5], baseTint: [.5, 1, 1, 1]};
  const channels = (node, name) => node.material.uniforms[name].value.toArray();
  controller.update(1.5, stageProject, lighting);
  almost(channels(plant, "ambient"), [.5, .25, 0, .25]);
  almost(channels(plant, "tint"), [.5, .75, .75, 1]);
  almost(channels(plant, "blendColor"), [.5, 0, .5, .25]);
  almost(channels(effect, "ambient"), [0, 0, 1, .25]);
  assert(!effect.material.uniforms.blendColor, "the opaque effect shader has no blend property");

  controller.update(4, stageProject, lighting);
  assert.deepEqual(channels(plant, "ambient"), lighting.baseAmbient);
  assert.deepEqual(channels(plant, "tint"), [1, 1, 1, 1]);
  stageProject.quality.values.stage_ambient = false;
  controller.update(1.5, stageProject, {baseAmbient: [1, 1, 1, -1]});
  assert.deepEqual(channels(plant, "ambient"), [1, 1, 1, 0]);
  assert.deepEqual(channels(plant, "blendColor"), [1, 1, 1, 0]);
  controller.dispose();
  assert.equal(plant.material, original);
  console.log("Independent stage ambient bindings, material defaults, native cutout and emissive inputs passed");
}

async function testStageEmissive() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Model";
  const root = new T.Group();
  const decoded = [new T.Texture(), new T.Texture(), new T.Texture()];
  const defaults = {texture: 2, uvTransform: [1, 1, 0, 0], color: [.75, 1, .5, 1], intensity: .75};
  const addSurface = (emissive) => {
    const geometry = new T.PlaneGeometry();
    const uv = geometry.getAttribute("uv");
    geometry.setAttribute("_stage_light_uv", uv);
    geometry.setAttribute("_stage_emissive_uv", uv);
    geometry.userData.mvStageMaterial = {
      shader: "stage", uvTransform: [1, 1, 0, 0], lightmap: 1, mipBias: 0,
      emissive, colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
    };
    const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: decoded[0]}));
    root.add(node);
    return node;
  };
  const bound = addSurface({...defaults, binding});
  const shared = addSurface({...defaults, binding});
  const unbound = addSurface(defaults);
  const wrongBinding = addSurface({...defaults, binding: binding + "/Other"});

  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency: async (type, index) => type === "texture" ? decoded[index] : null,
  });
  const originalShader = bound.material;
  const sampleUniforms = ({material: {uniforms}}) =>
    [uniforms.emissiveColor.value.toArray(), uniforms.emissiveIntensity.value];
  const expectedDefaults = [defaults.color, defaults.intensity];
  const enabled = track("LiveStageEmissiveTrack", binding, [
    {start: 0, duration: 2, values: {playableClass: "LiveStageEmissiveClip",
      colorSpecifiedType: 0, color: [1, .75, .375, .25], intensity: 1.75, blendOut: 1}},
    {start: 1, duration: 2, values: {playableClass: "LiveStageEmissiveClip",
      colorSpecifiedType: 1, memberPosition: 1, color: [.5, .5, 1, .5], intensity: .25, blendIn: 1}},
  ]);
  const wrong = track("LiveStageEmissiveTrack", binding + "/Other", enabled.events);
  const stageProject = {
    tracks: [wrong, enabled], quality: {values: {stage_emissive: true}},
    performers: [{position: 1, themeColor: [.25, .5, .5, .5]}],
  };

  controller.update(.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), [[1, .75, .375, .25], 1.75]);
  controller.update(1.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), [[.5625, .5, .4375, .25], 1]);
  assert.deepEqual(sampleUniforms(shared), sampleUniforms(bound), "each user of the owned material sees the same sample");
  assert.deepEqual(sampleUniforms(unbound), expectedDefaults);
  assert.deepEqual(sampleUniforms(wrongBinding), expectedDefaults);

  controller.update(3, stageProject);
  assert.deepEqual(sampleUniforms(bound), [[0, 0, 0, 0], 0], "an enabled clip gap clears both uniforms");
  stageProject.quality.values.stage_emissive = false;
  controller.update(1.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), expectedDefaults);
  assert.equal(bound.material, originalShader, "quality changes the owned properties with the same material pass");
  stageProject.quality.values.stage_emissive = true;
  controller.update(2.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), [[.125, .25, .5, .25], .25]);
  enabled.muted = true;
  controller.update(2.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), expectedDefaults);
  enabled.muted = false;
  stageProject.tracks = [enabled, {...enabled}];
  controller.update(1.5, stageProject);
  assert.deepEqual(sampleUniforms(bound), expectedDefaults, "ambiguous bound tracks retain authored material defaults");
  controller.dispose();
  console.log("Native stage emissive target ownership, crossfades, seek gaps and quality gates passed");
}

testSingleStageAmbient().then(testStageEmissive).catch(error => { console.error(error); process.exitCode = 1; });
