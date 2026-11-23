"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-prop-light.js");
require("../webtools/web/static/mv-studio-stage-material.js");

const {create, apply} = global.MVStudioPropLight;
const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so2035_01";
const close = (actual, expected, label) => {
  assert.equal(actual.length, expected.length, label);
  actual.forEach((value, index) => assert(Math.abs(value - expected[index]) < 1e-6,
    `${label}: ${value} differs from ${expected[index]} at ${index}`));
};
const rgba = ([r, g, b, a]) => ({r, g, b, a});
const clip = (playableClass, start, duration, values) =>
  ({start, duration, values: {playableClass, colorSpecifiedType: 0, memberPosition: 1, ...values}});

// 12035 fx_stg_so2035_01 clips: a blue ambient with a 0.3 tint and a white rim from the left.
const ambientTrack = {binding, nativeClass: "LivePropAmbientTrack", events: [
  clip("LivePropAmbientClip", 0, 5, {color: rgba([0, 1 / 3, 1, .25]), tintColor: rgba([.3, .3, .3, 1])}),
]};
const rimTrack = {binding, nativeClass: "LivePropRimlightTrack", events: [
  clip("LivePropRimlightClip", 0, 5, {color: rgba([1, 1, 1, 0]), intensity: 1, sharpness: 10,
    direction: {x: -2, y: 0, z: 0}}),
]};
const project = {quality: {values: {}}, tracks: [ambientTrack, rimTrack]};

// Stage-effect bindings have no member; member bindings still need theirs.
assert.equal(create(binding, 1), null);
assert.equal(create("/EntryPoint/Live/Stages/MainStage/Effect"), null);
assert.equal(create("/EntryPoint/Live/Stages/MainStage/Model/fx"), null);
const light = create(binding);
light.setProject(project);
const sampled = light.sample(1);
close(sampled.ambient, [0, 1 / 3, 1, .25], "stage prop ambient");
close(sampled.tint, [.3, .3, .3, 1], "stage prop tint");
assert.equal(sampled.rim.power, 11);

function mesh(fields, light, color = true) {
  const geometry = new T.BufferGeometry();
  geometry.setAttribute("position", new T.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
  geometry.setAttribute("normal", new T.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1], 3));
  geometry.setAttribute("uv", new T.Float32BufferAttribute([0, 0, 1, 0, 0, 1], 2));
  if (color) geometry.setAttribute("_stage_color", new T.Float32BufferAttribute(new Array(12).fill(1), 4));
  geometry.userData = {mvStageRimlight: fields, mvPropLight: light};
  return new T.Mesh(geometry, new T.MeshBasicMaterial({name: "mat_stg_so2035_oth_01"}));
}
const fields = {texture: 3, rimlightTexture: null, uv: [1, 1, 0, 0], tint: [1, 1, 1, 1], ambient: [1, 1, 1, 0],
  rimlightColor: [1, 1, 1, 1], rimlightDirection: [.5, 0, 0, 0], intensity: 0, power: 3, cull: 2, queue: 2000};

async function run() {
  const root = new T.Group();
  const prop = mesh(fields, {binding, ambient: true, rim: true});
  const ambientOnly = mesh({...fields, cull: 0}, {binding, ambient: true, rim: false}, false);
  const ignored = mesh(fields, {binding: "/EntryPoint/Live/Members/Member1", ambient: true, rim: true});
  const original = prop.material;
  root.add(prop, ambientOnly, ignored);
  const loaded = [];
  const parser = {async getDependency(type, index) {
    assert.equal(type, "texture");
    loaded.push(index);
    return new T.Texture();
  }};
  const controller = await apply(T, root, parser);
  assert.deepEqual(loaded, [3], "the main texture loads once; a missing rim texture is white");
  assert.equal(ignored.material.isShaderMaterial, undefined, "member bindings are not stage props");
  const material = prop.material, uniforms = material.uniforms;
  assert.equal(material.side, T.FrontSide, "_CullMode Back keeps front faces");
  assert.equal(ambientOnly.material.side, T.DoubleSide);
  assert.deepEqual(ambientOnly.material.defaultAttributeValues._stage_color, [1, 1, 1, 1]);
  assert.equal(material.transparent, false);
  assert.equal(material.depthWrite, true);
  assert.deepEqual(uniforms.uRimlightDirection.value.toArray(), [.5, 0, 0], "preview view space is Unity's");
  assert.match(material.fragmentShader, /mix\(surface\.rgb, uAmbientColor\.rgb, uAmbientColor\.a\)/);
  assert.match(material.fragmentShader, /exp2\(log2\(facing\) \* uRimglightPower\)/);

  controller.setProject(project);
  controller.update(1);
  close(uniforms.uAmbientColor.value.toArray(), [0, 1 / 3, 1, .25], "mixed ambient");
  close(uniforms.uTintColor.value.toArray(), [.3, .3, .3, 1], "mixed tint");
  close(uniforms.uRimlightColor.value.toArray(), [1, 1, 1, 0], "mixed rim color");
  close(uniforms.uRimlightDirection.value.toArray(), [-2, 0, 0], "mixed rim direction");
  assert.equal(uniforms.uRimglightIntensity.value, 1);
  assert.equal(uniforms.uRimglightPower.value, 11, "ApplySharpness writes 1 + sharpness");
  // Rim is not listed for this material: its own rim values stay authored.
  assert.equal(ambientOnly.material.uniforms.uRimglightPower.value, 3);
  close(ambientOnly.material.uniforms.uTintColor.value.toArray(), [.3, .3, .3, 1], "ambient-only tint");

  // A gap restores the default ambient and zero rim intensity.
  controller.update(6);
  close(uniforms.uAmbientColor.value.toArray(), [1, 1, 1, 0], "default ambient");
  close(uniforms.uTintColor.value.toArray(), [1, 1, 1, 1], "default tint");
  assert.equal(uniforms.uRimglightIntensity.value, 0);

  // Quality gates and muting follow the member prop components.
  project.quality.values.prop_ambient = false;
  project.quality.values.prop_rim_light = false;
  controller.update(1);
  close(uniforms.uAmbientColor.value.toArray(), [1, 1, 1, 0], "gated ambient");
  assert.equal(uniforms.uRimglightIntensity.value, 0);
  project.quality.values.prop_ambient = true;
  project.quality.values.prop_rim_light = true;

  // General/Opaque stage materials instanced by the prop follow its ambient, not the stage ambient.
  const stageRoot = new T.Group(), texture = new T.Texture();
  const antenna = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
  const stageOnly = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
  const colors = {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]};
  for (const node of [antenna, stageOnly]) {
    node.geometry.userData.mvStageMaterial = {shader: "general", colors, ambientDefaults: colors,
      uvTransform: [1, 1, 0, 0], singleAmbientBinding: "/EntryPoint/Live/Stages/MainStage/Effect"};
    stageRoot.add(node);
  }
  antenna.geometry.userData.mvPropLight = {binding, ambient: true, rim: true};
  const stageMaterials = await MVStudioStageMaterial.apply(T, stageRoot, {getDependency: async () => texture});
  const stageAmbient = {binding: "/EntryPoint/Live/Stages/MainStage/Effect", nativeClass: "LiveStageSingleAmbientTrack",
    events: [{start: 0, duration: 5, values: {playableClass: "LiveStageSingleAmbientClip", colorSpecifiedType: 0,
      color: [1, 0, 0, .5], tintColor: [0, 1, 0, 1], blendColor: [0, 0, 0, 0]}}]};
  const stageProject = {quality: {values: {}}, tracks: [ambientTrack, stageAmbient]};
  stageMaterials.update(1, stageProject, {});
  close(antenna.material.uniforms.ambient.value.toArray(), [0, 1 / 3, 1, .25], "prop-owned ambient");
  close(antenna.material.uniforms.tint.value.toArray(), [.3, .3, .3, 1], "prop-owned tint");
  close(stageOnly.material.uniforms.ambient.value.toArray(), [1, 0, 0, .5], "stage ambient elsewhere");
  stageMaterials.update(6, stageProject, {});
  close(antenna.material.uniforms.ambient.value.toArray(), [1, 1, 1, 0], "prop default ambient");

  // Why the rim vector is not mirrored: the preview camera is the mirrored rig
  // rotation (mv-studio-scene poseCamera) and the native Offset/Camera child turns
  // 180 degrees about Y, so preview view space equals unity_MatrixV view space.
  const rig = new T.Quaternion(.2, -.5, .1, .8).normalize(), at = new T.Vector3(1.5, 2, -7);
  const unityCamera = new T.Matrix4().compose(at, rig.clone().multiply(new T.Quaternion(0, 1, 0, 0)), new T.Vector3(1, 1, 1));
  const unityView = new T.Matrix4().makeScale(1, 1, -1).multiply(unityCamera.clone().invert());
  const camera = new T.PerspectiveCamera();
  camera.position.set(-at.x, at.y, at.z);
  camera.quaternion.set(rig.x, -rig.y, -rig.z, rig.w);
  camera.updateMatrixWorld();
  const point = new T.Vector3(.3, 1.2, 4);
  close(new T.Vector3(-point.x, point.y, point.z).applyMatrix4(camera.matrixWorldInverse).toArray(),
    point.clone().applyMatrix4(unityView).toArray(), "preview and Unity view spaces agree");

  controller.dispose();
  assert.equal(prop.material, original);
  assert.equal(await apply(T, new T.Group(), parser), null);
  console.log("Stage prop lighting: stage bindings, AS/Rimlight/Opaque inputs, rim, defaults, gates, instanced General/Opaque.");
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
