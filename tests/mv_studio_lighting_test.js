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

// UtilColor.CheckSame (0x2960e4c, squared RGBA distance < 1e-5): an ambient
// component keeps the color it last wrote until the new one moves by sqrt(1e-5).
{
  const { heldColor, HOLD_EPSILON } = globalThis.MVStudioLighting;
  assert.equal(HOLD_EPSILON, Math.fround(1e-5), "the float at 0x56f60fc");
  const ramp = (time) => [0, 0, 1, .1 + .001 * time];
  const hold = {};
  assert.deepEqual(heldColor(hold, ramp, 2, null), ramp(2), "no frame clock: exact");
  assert.deepEqual(heldColor(hold, ramp, 3, { advancing: true, history: [] }), ramp(2), "0.001 is not written");
  assert.deepEqual(heldColor(hold, ramp, 6, { advancing: true, history: [] }), ramp(6), "0.004 is written");
  assert.deepEqual(heldColor(hold, ramp, 8, { advancing: false, history: [0, 3, 5] }), ramp(5),
    "a seek replays the rendered frames: 0 -> 3 (held 0), 5 written, 8 held");
  assert.deepEqual(heldColor(hold, ramp, 8, { advancing: false, history: [] }), ramp(8), "a seek without frames: exact");
  assert.equal(heldColor(hold, () => null, 9, { advancing: true, history: [] }), null);
  assert.deepEqual(heldColor(hold, ramp, 9.5, { advancing: true, history: [] }), ramp(9.5), "no color restarts the hold");
}

async function testStageAmbientHold() {
  const root = new T.Group(), texture = new T.Texture();
  const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
  const colors = {_AmbientColor: [0, 0, 0, 0], _TintColor: [1, 1, 1, 1], _BlendColor: [0, 0, 0, 0]};
  node.geometry.userData.mvStageMaterial = {shader: "general", colors, ambientDefaults: colors, uvTransform: [1, 1, 0, 0]};
  root.add(node);
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => texture});
  const clip = (start, alpha, fade) => ({start, duration: 2, values: {playableClass: "LiveStageAmbientClip",
    colorSpecifiedType: 0, color: [0, .5, 1, alpha], tintColor: [1, 1, 1, 1], blendColor: [1, 1, 1, 0], ...fade}});
  const ambient = track("LiveStageAmbientTrack", "/EntryPoint/Live/Stages/MainStage",
    [clip(0, .2, {blendOut: 1}), clip(1, .21, {blendIn: 1})]);
  const stageProject = {tracks: [ambient], quality: {values: {}}};
  const alpha = () => node.material.uniforms.ambient.value.w;
  controller.update(1.8, stageProject, {});
  assert(Math.abs(alpha() - (.2 + .01 * .896)) < 1e-7, "exact without frame history");
  controller.update(1.8, stageProject, {}, {advancing: false, history: [.5, 1.2, 1.6]});
  assert(Math.abs(alpha() - (.2 + .01 * .648)) < 1e-7, "LiveCoreStageAmbient keeps the 1.6 s write");
  controller.update(1.8, stageProject, {baseTrack: true}, {advancing: false, history: [.5, 1.2, 1.6]});
  assert(Math.abs(alpha() - (.2 + .01 * .896)) < 1e-7, "a base light track also writes the component: exact");
  controller.dispose();
  console.log("Ambient component write threshold (UtilColor.CheckSame) holds on rendered frames passed");
}

// LiveStageSingleAmbientMixer.PostProcess (0x20f75bc) writes through the same CheckSame-gated
// LiveCoreStageAmbient methods as the MainStage mixer, and the ApplyDefault* writers share their
// cached color: a default within the threshold of the last clip write keeps that write.
async function testStageAmbientComponentHolds() {
  const stage = "/EntryPoint/Live/Stages/MainStage", binding = stage + "/Model/Ambient/Ambient2";
  const root = new T.Group(), texture = new T.Texture();
  const colors = {_AmbientColor: [0, 0, 0, 0], _TintColor: [1, 1, 1, 1], _BlendColor: [0, 0, 0, 0]};
  const addSurface = (details) => {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
    node.geometry.userData.mvStageMaterial = {shader: "general", colors, ambientDefaults: colors, uvTransform: [1, 1, 0, 0], ...details};
    root.add(node);
    return node;
  };
  const single = addSurface({singleAmbientBinding: binding}), twin = addSurface({singleAmbientBinding: binding});
  const main = addSurface({});
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => texture});
  const clip = (playableClass, start, duration, color, fade) => ({start, duration, values: {playableClass,
    colorSpecifiedType: 0, color, tintColor: [1, 1, 1, 1], blendColor: [1, 1, 1, 0], ...fade}});
  const singleTrack = track("LiveStageSingleAmbientTrack", binding, [
    clip("LiveStageSingleAmbientClip", 0, 2, [0, .5, 1, .2], {blendOut: 1}),
    clip("LiveStageSingleAmbientClip", 1, 2, [0, .5, 1, .21], {blendIn: 1}),
    clip("LiveStageSingleAmbientClip", 4, 1, [1, 1, 1, .002])]);
  const mainTrack = track("LiveStageAmbientTrack", stage, [clip("LiveStageAmbientClip", 4, 1, [0, 0, 0, .002])]);
  const stageProject = {tracks: [singleTrack, mainTrack], quality: {values: {}}};
  const alpha = (node) => node.material.uniforms.ambient.value.w;
  const history = [.5, 1.2, 1.6];
  controller.update(1.8, stageProject, {});
  assert(Math.abs(alpha(single) - (.2 + .01 * .896)) < 1e-7, "exact without frame history");
  controller.update(1.8, stageProject, {}, {advancing: false, history});
  assert(Math.abs(alpha(single) - (.2 + .01 * .648)) < 1e-7, "the single ambient component keeps the 1.6 s write");
  assert.equal(alpha(twin), alpha(single), "materials of one component share its write");
  // An advancing frame continues the held color; a move past the threshold is written.
  controller.update(1.85, stageProject, {}, {advancing: true, history: []});
  assert(Math.abs(alpha(single) - (.2 + .01 * .648)) < 1e-7, "0.85 of the threshold: still held");
  controller.update(1.9, stageProject, {}, {advancing: true, history: []});
  assert(Math.abs(alpha(single) - (.2 + .01 * .972)) < 1e-7, "1.05 of the threshold: written");
  controller.update(3.5, stageProject, {}, {advancing: true, history: []});
  assert.deepEqual(single.material.uniforms.ambient.value.toArray(), [1, 1, 1, 0], "LiveCoreStageAmbient's default ambient");
  controller.update(1.8, stageProject, {baseTrack: true}, {advancing: false, history});
  assert(Math.abs(alpha(single) - (.2 + .01 * .896)) < 1e-7, "a base light track also writes the component: exact");

  // After the clip the defaults are written through the same cache: within the threshold the clip write stays.
  controller.update(5.5, stageProject, {}, {advancing: false, history: [4.2, 4.8, 5.2]});
  almost(single.material.uniforms.ambient.value.toArray(), [1, 1, 1, .002]);
  almost(main.material.uniforms.ambient.value.toArray(), [0, 0, 0, .002]);
  controller.update(5.5, stageProject, {});
  almost(single.material.uniforms.ambient.value.toArray(), [1, 1, 1, 0]);
  almost(main.material.uniforms.ambient.value.toArray(), [0, 0, 0, 0]);
  controller.dispose();
  console.log("Single and MainStage ambient components hold their clip and default writes passed");
}

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
  // Only the stage model and its children hold LiveCoreStageEmissive receivers.
  const wrongBinding = addSurface({...defaults, binding: "/EntryPoint/Live/Stages/MainStage/Effect"});

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
  const wrong = track("LiveStageEmissiveTrack", "/EntryPoint/Live/Stages/MainStage/Effect", enabled.events);
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

// LiveCoreStageEmissive.ApplyEmissiveColor (0x2f74e18) skips Material.SetColor while
// UtilColor.CheckSame holds for the color it last wrote, and ApplyEmissiveIntensity (0x2f74f5c)
// skips SetFloat while Mathf.Approximately holds: both keep their last write on the frame clock.
async function testStageEmissiveHold() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Model";
  const root = new T.Group(), decoded = [new T.Texture(), new T.Texture()];
  const geometry = new T.PlaneGeometry();
  geometry.setAttribute("_stage_light_uv", geometry.getAttribute("uv"));
  geometry.setAttribute("_stage_emissive_uv", geometry.getAttribute("uv"));
  geometry.userData.mvStageMaterial = {
    shader: "stage", uvTransform: [1, 1, 0, 0], lightmap: 1, mipBias: 0,
    emissive: {texture: 1, uvTransform: [1, 1, 0, 0], color: [1, 1, 1, 1], intensity: 1, binding},
    colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
  };
  const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: decoded[0]}));
  root.add(node);
  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency: async (type, index) => type === "texture" ? decoded[index] : null,
  });
  const emissiveTrack = track("LiveStageEmissiveTrack", binding, [
    {start: 0, duration: 2, values: {playableClass: "LiveStageEmissiveClip", colorSpecifiedType: 0,
      color: [.2, .2, .2, 1], intensity: 1, blendOut: 1}},
    {start: 1, duration: 3, values: {playableClass: "LiveStageEmissiveClip", colorSpecifiedType: 0,
      color: [.2, .2, .205, 1], intensity: 1.0000005, blendIn: 1}},
  ]);
  const stageProject = {tracks: [emissiveTrack], quality: {values: {stage_emissive: true}}};
  const read = () => [node.material.uniforms.emissiveColor.value.toArray(), node.material.uniforms.emissiveIntensity.value];
  const exact = (time) => (controller.update(time, stageProject), read());
  const distance = (a, b) => a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0);
  const [at12, at15, at16, at19] = [1.2, 1.5, 1.6, 1.9].map(exact);
  assert(distance(at15[0], at12[0]) < MVStudioLighting.HOLD_EPSILON, "precondition: 1.5 s is within CheckSame of 1.2 s");
  assert(distance(at16[0], at12[0]) < MVStudioLighting.HOLD_EPSILON, "precondition: 1.6 s is within CheckSame of 1.2 s");
  assert(distance(at19[0], at12[0]) >= MVStudioLighting.HOLD_EPSILON, "precondition: 1.9 s moves past the threshold");
  assert.notEqual(at16[1], at12[1], "precondition: the intensity moves below the Approximately step");

  controller.update(1.6, stageProject, {}, {advancing: false, history: [1.2, 1.5]});
  assert.deepEqual(read(), at12, "the 1.2 s write is kept for color and intensity");
  controller.update(1.9, stageProject, {}, {advancing: true, history: []});
  assert.deepEqual(read()[0], at19[0], "a move past the threshold is written on an advancing frame");
  assert.equal(read()[1], at12[1], "the intensity stays within Approximately of its last write");
  controller.update(1.6, stageProject, {}, {advancing: false, history: []});
  assert.deepEqual(read(), at16, "a seek without frame history writes the exact values");
  controller.update(3.5, stageProject, {}, {advancing: false, history: [3.2]});
  assert.deepEqual(read(), [[.2, .2, .205, 1].map(Math.fround), Math.fround(1.0000005)], "a held clip writes its own values");
  // The base light writes only the ambient components; the emissive hold stays.
  controller.update(1.6, stageProject, {baseTrack: true}, {advancing: false, history: [1.2, 1.5]});
  assert.deepEqual(read(), at12, "the emissive hold does not depend on a base light track");
  emissiveTrack.muted = true;
  controller.update(1.6, stageProject, {}, {advancing: false, history: [1.2, 1.5]});
  assert.deepEqual(read(), [[1, 1, 1, 1], 1], "without a mixer the material keeps its own values");
  controller.dispose();
  assert(MVStudioLighting.approximately(1, 1.0000005) && !MVStudioLighting.approximately(1, 1.000002),
    "Mathf.Approximately is a 1e-6 relative test");
  // Mathf.Epsilon is FloatMinDenormal (2^-149): the client never sets FPCR.FZ.
  const epsilon = 2 ** -149;
  assert.equal(MVStudioLighting.APPROXIMATELY_FLOOR, 8 * epsilon, "the floor is 8 * Mathf.Epsilon");
  assert(MVStudioLighting.approximately(0, 7 * epsilon) && !MVStudioLighting.approximately(0, 8 * epsilon) &&
    !MVStudioLighting.approximately(0, 1e-40), "Mathf.Approximately has an 8 * FloatMinDenormal floor");
  console.log("Native stage emissive holds (CheckSame color, Approximately intensity) passed");
}

// 10001/3: LiveCoreStageModel.emissives lists four receivers on Model/Emissives/Emissive1..4, each
// with its own materials, LiveStageEmissiveTrack and CheckSame/Approximately hold.
async function testStageChildEmissives() {
  const model = "/EntryPoint/Live/Stages/MainStage/Model";
  const [first, second] = [1, 2].map(index => `${model}/Emissives/Emissive${index}`);
  const root = new T.Group(), decoded = [new T.Texture(), new T.Texture()];
  const defaults = {texture: 1, uvTransform: [1, 1, 0, 0], color: [1, 1, 1, 1], intensity: 1};
  const addSurface = (binding) => {
    const geometry = new T.PlaneGeometry();
    geometry.setAttribute("_stage_light_uv", geometry.getAttribute("uv"));
    geometry.setAttribute("_stage_emissive_uv", geometry.getAttribute("uv"));
    geometry.userData.mvStageMaterial = {
      shader: "stage", uvTransform: [1, 1, 0, 0], lightmap: 1, mipBias: 0, emissive: {...defaults, binding},
      colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
    };
    const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: decoded[0]}));
    root.add(node);
    return node;
  };
  const [one, two, whole] = [first, second, model].map(addSurface);
  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency: async (type, index) => type === "texture" ? decoded[index] : null,
  });
  const read = (node) => [node.material.uniforms.emissiveColor.value.toArray(), node.material.uniforms.emissiveIntensity.value];
  const firstTrack = track("LiveStageEmissiveTrack", first, [
    {start: 0, duration: 2, values: {playableClass: "LiveStageEmissiveClip", colorSpecifiedType: 0,
      color: [.2, .2, .2, 1], intensity: 1, blendOut: 1}},
    {start: 1, duration: 3, values: {playableClass: "LiveStageEmissiveClip", colorSpecifiedType: 0,
      color: [.2, .2, .205, 1], intensity: 1.0000005, blendIn: 1}},
  ]);
  const secondTrack = track("LiveStageEmissiveTrack", second, [
    {start: 0, duration: 4, values: {playableClass: "LiveStageEmissiveClip", colorSpecifiedType: 0,
      color: [.9, .1, .1, 1], intensity: 3}},
  ]);
  const stageProject = {tracks: [secondTrack, firstTrack], quality: {values: {stage_emissive: true}}};
  const exact = (time) => (controller.update(time, stageProject), [read(one), read(two)]);
  const [at12, at15] = [1.2, 1.5].map(exact);
  assert.deepEqual(at15[1], [[.9, .1, .1, 1].map(Math.fround), 3], "each receiver samples its own track");
  assert.notDeepEqual(at15[0], at12[0], "precondition: the first receiver's color moves between 1.2 s and 1.5 s");
  assert.deepEqual(read(whole), [defaults.color, defaults.intensity], "the model binding has no track here");

  // Advancing frames: the first receiver keeps its 1.2 s write while the second writes its own color.
  controller.update(1.2, stageProject, {}, {advancing: false, history: []});
  controller.update(1.5, stageProject, {}, {advancing: true, history: []});
  assert.deepEqual([read(one), read(two)], [at12[0], at15[1]], "every receiver holds its own last write");

  stageProject.tracks = [secondTrack, firstTrack, {...secondTrack}];
  controller.update(1.5, stageProject, {}, {advancing: false, history: []});
  assert.deepEqual(read(two), [defaults.color, defaults.intensity], "two tracks on one receiver keep its defaults");
  assert.deepEqual(read(one), at15[0], "another receiver's ambiguity does not matter");
  controller.dispose();
  console.log("Native stage emissive receivers below the model, one track and hold each, passed");
}

async function testStageMainSampler() {
  const root = new T.Group(), disposed = [], closed = [], requests = [];
  const texture = (name, width, height) => {
    const value = new T.Texture({width, height, close: () => closed.push(name)});
    value.addEventListener("dispose", () => disposed.push(name));
    return value;
  };
  const base = texture("base", 8, 4);
  base.flipY = false;
  base.wrapS = T.RepeatWrapping;
  base.wrapT = T.MirroredRepeatWrapping;
  base.encoding = T.sRGBEncoding;
  base.minFilter = T.LinearFilter;
  const lightmap = texture("light", 4, 4);
  const levels = [texture("mip1", 4, 2), texture("mip2", 2, 1), texture("mip3", 1, 1)];
  const invalid = texture("wrong-size", 4, 1);
  const addSurface = (target, mainSampler, shader = "stage") => {
    const geometry = new T.PlaneGeometry();
    geometry.setAttribute("_stage_light_uv", geometry.getAttribute("uv"));
    geometry.userData.mvStageMaterial = {
      shader, lightmap: 0, mipBias: .25, uvTransform: [1, 1, 0, 0], mainSampler,
      colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
    };
    const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: base}));
    target.add(node);
    return node;
  };
  const authored = {mipmaps: [1, 2, 3], filterMode: 1, anisotropy: 8};
  const bilinear = addSurface(root, authored);
  const shared = addSurface(root, {...authored});
  const trilinear = addSurface(root, {...authored, filterMode: 2});
  const point = addSurface(root, {...authored, filterMode: 0, anisotropy: 0});
  const pointBase = addSurface(root, {mipmaps: [], filterMode: 0});
  const broken = addSurface(root, {...authored, mipmaps: [4, 2, 3]});
  const unresolved = addSurface(root, {...authored, mipmaps: [1, 2, 5]});
  const borrowed = addSurface(root, {...authored, mipmaps: [1, 2, 6]});
  const incomplete = addSurface(root, {...authored, mipmaps: [7]});
  const legacy = addSurface(root);
  const general = addSurface(root, authored, "general");
  const generalLegacy = addSurface(root, undefined, "general");
  const original = bilinear.material;
  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency(type, index) {
      assert.equal(type, "texture");
      requests.push(index);
      if (index === 5) throw new Error("missing mip");
      return Promise.resolve([lightmap, ...levels, invalid, null, base][index]);
    },
  });
  const map = (node) => node.material.uniforms.mainMap.value;
  assert.equal(bilinear.material.uniforms.mipBias.value, .25);
  assert.notEqual(map(bilinear), base);
  assert.equal(map(bilinear), map(shared));
  assert.equal(map(general), map(bilinear));
  assert.equal(map(generalLegacy), map(legacy));
  assert.equal(general.material.defines.LIGHTMAPPED, undefined);
  assert.equal(general.material.uniforms.mipBias, undefined);
  assert.equal(map(bilinear).image, base.image);
  assert.deepEqual(map(bilinear).mipmaps, [base.image, ...levels.map(item => item.image)]);
  assert.equal(map(bilinear).magFilter, T.LinearFilter);
  assert.equal(map(bilinear).minFilter, T.LinearMipmapNearestFilter);
  assert.equal(map(bilinear).anisotropy, 8);
  assert.equal(map(bilinear).generateMipmaps, false);
  assert.equal(map(bilinear).encoding, T.LinearEncoding);
  assert.equal(map(bilinear).flipY, false);
  assert.equal(map(bilinear).wrapS, base.wrapS);
  assert.equal(map(bilinear).wrapT, base.wrapT);
  assert.notEqual(map(trilinear), map(bilinear));
  assert.equal(map(trilinear).minFilter, T.LinearMipmapLinearFilter);
  assert.equal(map(point).magFilter, T.NearestFilter);
  assert.equal(map(point).minFilter, T.NearestMipmapNearestFilter);
  assert.equal(map(point).anisotropy, 1);
  assert.equal(map(pointBase).minFilter, T.NearestFilter);
  assert.deepEqual(map(pointBase).mipmaps, []);
  for (const node of [broken, unresolved, borrowed, incomplete]) assert.equal(map(node), map(legacy));
  assert.equal(map(legacy).minFilter, T.LinearFilter);
  assert.deepEqual(map(legacy).mipmaps, []);
  assert.equal(base.encoding, T.sRGBEncoding);
  assert.equal(base.minFilter, T.LinearFilter);
  assert.deepEqual(base.mipmaps, []);
  assert.deepEqual(requests.filter(index => index !== 0), [1, 2, 3, 4, 5, 6]);
  const owned = map(bilinear);
  owned.addEventListener("dispose", () => disposed.push("owned"));
  controller.dispose();
  assert.equal(bilinear.material, original);
  assert.deepEqual(disposed.sort(), ["light", "mip1", "mip2", "mip3", "owned", "wrong-size"]);
  assert.deepEqual(closed.sort(), ["mip1", "mip2", "mip3", "wrong-size"]);

  const limitedRoot = new T.Group(), limited = addSurface(limitedRoot, authored);
  const limitedRequests = [];
  const limitedController = await MVStudioStageMaterial.apply(T, limitedRoot, {
    async getDependency(type, index) {
      limitedRequests.push(index);
      return lightmap;
    },
  }, {maxTextureSize: 4});
  assert.deepEqual(limitedRequests, [0], "an over-limit base uses fallback without requesting extra levels");
  assert.deepEqual(map(limited).mipmaps, []);
  limitedController.dispose();

  const staleRoot = new T.Group(), stale = addSurface(staleRoot, authored), staleMaterial = stale.material;
  const staleRequests = [];
  const staleLevels = [texture("stale1", 4, 2), texture("stale2", 2, 1), texture("stale3", 1, 1)];
  let active = true;
  const staleController = await MVStudioStageMaterial.apply(T, staleRoot, {
    async getDependency(type, index) {
      assert.equal(type, "texture");
      staleRequests.push(index);
      if (index === 3) active = false;
      return staleLevels[index - 1];
    },
  }, {active: () => active});
  assert.deepEqual(staleRequests, [1, 2, 3], "a stale stage does not start further resource loads");
  assert.equal(stale.material, staleMaterial);
  staleController.dispose();
  assert.deepEqual(closed.slice(-3), ["stale1", "stale2", "stale3"]);
  console.log("Native stage MainTex mip dimensions, filter selection, sharing, fallback and canceled cleanup passed");
}

async function testStageAuxiliarySamplers() {
  const disposed = [], closed = [];
  const texture = (name, size, wrap = T.RepeatWrapping) => {
    const value = new T.Texture({width: size, height: size, close: () => closed.push(name)});
    value.wrapS = value.wrapT = wrap;
    value.minFilter = T.LinearFilter;
    value.encoding = T.sRGBEncoding;
    value.flipY = false;
    value.addEventListener("dispose", () => disposed.push(name));
    return value;
  };
  const original = texture("original", 4);
  const packed = [
    original, texture("light", 4, T.ClampToEdgeWrapping), texture("emissive", 4),
    texture("light1", 2), texture("light2", 1), texture("emissive1", 2), texture("emissive2", 1),
    texture("other-base", 1),
  ];
  const addSurface = (root, lightmap, lightmapSampler, sampler) => {
    const geometry = new T.PlaneGeometry();
    const uv = geometry.getAttribute("uv");
    geometry.setAttribute("_stage_light_uv", uv);
    geometry.setAttribute("_stage_emissive_uv", uv);
    geometry.userData.mvStageMaterial = {
      shader: "stage", lightmap, lightmapSampler, mipBias: .125, uvTransform: [1, 1, 0, 0],
      emissive: {texture: 2, color: [.75, .5, 1, 1], intensity: .75, uvTransform: [1, 1, 0, 0], sampler},
      colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
    };
    const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: original}));
    root.add(node);
    return node;
  };
  const lightSampler = {mipmaps: [3, 4], filterMode: 1, anisotropy: 3};
  const maskSampler = {mipmaps: [5, 6], filterMode: 1, anisotropy: 8};
  const root = new T.Group();
  const sampled = addSurface(root, 1, lightSampler, maskSampler);
  const shared = addSurface(root, 1, {...lightSampler}, {...maskSampler});
  const legacy = addSurface(root, 1);
  const malformed = addSurface(root, 1, {...lightSampler, mipmaps: [3, 7]}, {...maskSampler, mipmaps: [5, 8]});
  addSurface(root, 7);
  const borrowed = addSurface(root, 0);
  const requests = [];
  const controller = await MVStudioStageMaterial.apply(T, root, {
    async getDependency(type, index) {
      assert.equal(type, "texture");
      requests.push(index);
      if (index === 8) throw new Error("missing mask mip");
      return packed[index];
    },
  });
  const uniform = (node, name) => node.material.uniforms[name].value;
  for (const [name, indices, aniso, wrap] of [
    ["lightMap", [1, 3, 4], 3, T.ClampToEdgeWrapping],
    ["emissiveMap", [2, 5, 6], 8, T.RepeatWrapping],
  ]) {
    const map = uniform(sampled, name);
    assert.equal(map, uniform(shared, name));
    assert.notEqual(map, uniform(legacy, name));
    assert.equal(uniform(malformed, name), uniform(legacy, name));
    assert.deepEqual(uniform(legacy, name).mipmaps, []);
    assert.deepEqual(map.mipmaps, indices.map(index => packed[index].image));
    assert.equal(map.minFilter, T.LinearMipmapNearestFilter);
    assert.equal(map.magFilter, T.LinearFilter);
    assert.equal(map.encoding, T.LinearEncoding);
    assert.equal(map.generateMipmaps, false);
    assert.equal(map.anisotropy, aniso);
    assert.equal(map.flipY, false);
    assert.equal(map.wrapS, wrap);
    assert.equal(map.wrapT, wrap);
    assert.equal(packed[indices[0]].minFilter, T.LinearFilter);
  }
  assert.equal(uniform(sampled, "mipBias"), .125);
  assert.equal(uniform(sampled, "emissiveIntensity"), .75);
  assert.equal(uniform(borrowed, "mainMap"), uniform(borrowed, "lightMap"));
  assert.deepEqual(requests.slice().sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
  controller.dispose();
  assert.deepEqual(disposed.slice().sort(), ["emissive", "emissive1", "emissive2", "light", "light1", "light2", "other-base"]);
  assert.deepEqual(closed.slice().sort(), ["emissive1", "emissive2", "light1", "light2"]);

  const staleRoot = new T.Group();
  const stale = addSurface(staleRoot, 1, lightSampler, maskSampler), staleMaterial = stale.material;
  const staleRequests = [];
  let active = true;
  const late = {1: texture("late-light", 4), 3: texture("late-mip1", 2), 4: texture("late-mip2", 1)};
  const staleController = await MVStudioStageMaterial.apply(T, staleRoot, {
    async getDependency(type, index) {
      staleRequests.push(index);
      if (index === 4) active = false;
      return late[index];
    },
  }, {active: () => active});
  assert.deepEqual(staleRequests, [1, 3, 4], "cancellation stops before the emissive branch");
  assert.equal(stale.material, staleMaterial);
  staleController.dispose();
  assert.deepEqual(disposed.slice(-3).sort(), ["late-light", "late-mip1", "late-mip2"]);
  assert.deepEqual(closed.slice(-2).sort(), ["late-mip1", "late-mip2"]);
  console.log("Native stage lightmap and emissive mip routing, sharing, legacy fallback and cancellation passed");
}

async function testStageCubemapQuality() {
  const root = new T.Group(), base = new T.Texture(), lightmap = new T.Texture();
  const variants = {
    "add-vertex-alpha": {op: "add", reflectivity: "vertex"},
    "add-texture-alpha": {op: "add", reflectivity: "texture"},
    "vertex-alpha": {op: "alpha-blend", reflectivity: "vertex"},
  };
  const addSurface = (blend, controlled, bufferView = 0) => {
    const geometry = new T.PlaneGeometry();
    geometry.setAttribute("_stage_light_uv", geometry.getAttribute("uv"));
    geometry.setAttribute("_stage_color", new T.Float32BufferAttribute([
      1, 1, 1, 0, 1, 1, 1, .25, 1, 1, 1, .75, 1, 1, 1, 1,
    ], 4));
    geometry.userData.mvStageMaterial = {
      shader: "stage", lightmap: 0, mipBias: 0, uvTransform: [1, 1, 0, 0], vertexColor: true,
      reflectionToggle: true, reflectionQualityControlled: controlled,
      reflection: {bufferView, size: 8, boxMin: [-2, -1, -4], boxMax: [2, 5, 4], origin: [0, 2, 0],
        // "legacy" keeps the field a stage GLB converted before the variant fields carried.
        ...(controlled === undefined ? {blend} : {mode: "fragment", parallax: true, fresnel: false, ...variants[blend]})},
      colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [0, 0, 0, 0], _BlendColor: [0, 0, 0, 0]},
    };
    const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: base}));
    root.add(node);
    return node;
  };
  const cage = addSurface("add-vertex-alpha", true);
  const floor = addSurface("add-texture-alpha", true);
  const legacy = addSurface("vertex-alpha");
  const independent = addSurface("add-vertex-alpha", false);
  const missing = addSurface("add-texture-alpha", true, 1);
  const missingIndependent = addSurface("add-vertex-alpha", false, 1);
  const originals = [cage, floor, legacy, independent, missing, missingIndependent].map(node => node.material);
  const cubeRequests = [];
  const controller = await MVStudioStageMaterial.apply(T, root, {
    async getDependency(type, index) {
      if (type === "texture") return lightmap;
      cubeRequests.push(index);
      return new ArrayBuffer(index === 0 ? 6 * 4 * (64 + 16 + 4 + 1) : 4);
    },
  });
  assert.deepEqual(cubeRequests, [0, 1], "distinct modes and ownership share the same baked cube");
  const project = {quality: {values: {}}, tracks: []};
  controller.update(0, project);
  const cube = cage.material.uniforms.reflectionCube.value;
  assert(cube.isCubeTexture && cube.image.length === 6 && cube.mipmaps.length === 3);
  assert.deepEqual([cage.material.defines.CUBEMAP_ADD, cage.material.defines.CUBEMAP_REFLECTIVITY], [1, 0]);
  assert.deepEqual([floor.material.defines.CUBEMAP_ADD, floor.material.defines.CUBEMAP_REFLECTIVITY], [1, 1]);
  assert.deepEqual([legacy.material.defines.CUBEMAP_ADD, legacy.material.defines.CUBEMAP_REFLECTIVITY], [undefined, 0]);
  for (const node of [cage, floor, legacy]) {
    assert.deepEqual([node.material.defines.CUBEMAP_PARALLAX, node.material.defines.CUBEMAP_VERTEX,
      node.material.defines.CUBEMAP_FRESNEL], [1, undefined, undefined]);
  }
  for (const node of [cage, floor, legacy, independent]) {
    assert.equal(node.material.uniforms.reflectionCube.value, cube);
    assert.equal(node.material.side, T.FrontSide);
    assert.equal(node.material.depthFunc, T.LessEqualDepth);
    assert.equal(node.material.depthWrite, true);
    assert.equal(node.material.transparent, false);
  }
  assert.equal(missing.material, originals[4]);
  assert.equal(missingIndependent.material, originals[5]);
  const cageMaterial = cage.material;
  project.quality.values.stage_cubemap = false;
  controller.update(1, project);
  for (const node of [cage, floor, legacy]) {
    assert.equal(node.material.uniforms.useReflection.value, false);
    assert.equal(node.material.uniforms.reflectionCube.value, null);
  }
  assert.equal(cage.material, cageMaterial);
  assert.equal(independent.material.uniforms.useReflection.value, true);
  assert.equal(independent.material.uniforms.reflectionCube.value, cube);
  assert.equal(missing.material.isShaderMaterial, true);
  assert.equal(missingIndependent.material, originals[5]);
  project.quality.values.stage_cubemap = true;
  controller.update(0, project);
  assert.equal(cage.material.uniforms.reflectionCube.value, cube);
  assert.equal(missing.material, originals[4]);
  let disposed = 0;
  cube.addEventListener("dispose", () => { disposed++; });
  controller.dispose();
  assert.deepEqual([cage, floor, legacy, independent, missing, missingIndependent].map(node => node.material), originals);
  assert.equal(disposed, 1);
  console.log("Native stage cubemap blend selection, ownership, legacy fallback and opaque pass state passed");
}

async function testWeightedStageMaterial() {
  const root = new T.Group(), partition = new T.Group();
  partition.userData.mvStageSkin = true;
  root.add(partition);
  const map = new T.Texture({width: 4, height: 4});
  map.encoding = T.sRGBEncoding;
  map.minFilter = T.LinearFilter;
  const mips = [new T.Texture({width: 2, height: 2}), new T.Texture({width: 1, height: 1})];
  const description = {
    shader: "general", cull: 0, uvTransform: [1, 1, 0, 0],
    colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [1, 1, 1, 0]},
    mainSampler: {mipmaps: [0, 1], filterMode: 1, anisotropy: 8},
  };
  const geometry = new T.PlaneGeometry();
  geometry.userData.mvStageMaterial = description;
  geometry.setAttribute("skinIndex", new T.Uint16BufferAttribute(Array(4).fill([0, 1, 0, 0]).flat(), 4));
  geometry.setAttribute("skinWeight", new T.Float32BufferAttribute(Array(4).fill([.75, .25, 0, 0]).flat(), 4));
  const material = new T.MeshBasicMaterial({map});
  const mesh = new T.SkinnedMesh(geometry, material);
  const rootJoint = new T.Bone(), leafJoint = new T.Bone();
  root.add(rootJoint);
  rootJoint.add(leafJoint);
  partition.add(mesh);
  mesh.bind(new T.Skeleton([rootJoint, leafJoint]), new T.Matrix4());
  const baseline = new T.Mesh(new T.PlaneGeometry(), material);
  baseline.geometry.userData.mvStageMaterial = {...description, mainSampler: undefined};
  root.add(baseline);
  const controller = await MVStudioStageMaterial.apply(T, root, {
    getDependency: (type, index) => mips[index],
  });
  assert.equal(mesh.material.skinning, true);
  assert.match(mesh.material.vertexShader, /#include <skinbase_vertex>\s+#include <skinning_vertex>/);
  assert.match(mesh.material.vertexShader, /#include <skinnormal_vertex>/);
  assert.equal(mesh.material.side, T.DoubleSide);
  assert.equal(mesh.material.depthFunc, T.LessEqualDepth);
  assert.equal(mesh.material.depthWrite, true);
  assert.equal(mesh.material.transparent, false);
  assert.deepEqual(mesh.material.uniforms.mainMap.value.mipmaps, [map.image, ...mips.map(mip => mip.image)]);
  assert.equal(mesh.material.uniforms.mainMap.value.encoding, T.LinearEncoding);
  assert.equal(baseline.material.skinning, false);
  assert.equal(baseline.material.uniforms.mainMap.value.minFilter, T.LinearFilter);
  assert.deepEqual(baseline.material.uniforms.mainMap.value.mipmaps, []);

  leafJoint.position.x = 4;
  root.updateMatrixWorld(true);
  const vertex = new T.Vector3().fromBufferAttribute(geometry.getAttribute("position"), 0);
  const weighted = mesh.boneTransform(0, vertex.clone());
  assert.deepEqual(weighted.toArray(), [vertex.x + 1, vertex.y, vertex.z]);
  controller.dispose();
  assert.equal(mesh.material, material);
  console.log("Weighted native stage material selects Three skinning, opaque state and authored texture sampling.");
}

testStageAmbientHold().then(testStageAmbientComponentHolds).then(testSingleStageAmbient).then(testStageEmissive).then(testStageEmissiveHold).then(testStageChildEmissives).then(testStageMainSampler).then(testStageAuxiliarySamplers)
  .then(testStageCubemapQuality).then(testWeightedStageMaterial).catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
