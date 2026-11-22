"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
for (const name of ["viewer-motion-timeline", "mv-studio-lighting", "mv-studio-stage-motion", "mv-studio-stage-particles",
  "mv-studio-stage-burst-simulation", "mv-studio-stage-material", "mv-studio-display-lights", "mv-studio-stage-laser-cores",
  "mv-studio-stationary-bursts"]) require(`../webtools/web/static/${name}.js`);

async function run() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/Display";
  const root = new T.Group(), group = new T.Group(), activation = new T.Group();
  root.add(group);
  group.add(activation);
  group.scale.set(4, 5, 6);
  group.userData.mvStageNode = {binding, path: 0, active: true};
  activation.userData.mvStageNode = {binding, path: 1, active: false};
  activation.visible = false;
  const carrier = (path, z) => {
    const node = new T.Group();
    node.userData.mvStageNode = {binding, path, active: true};
    node.position.set(1, 2, z);
    activation.add(node);
    return node;
  };
  carrier(2, 3);
  const glyph = carrier(3, 5);
  glyph.scale.set(1, 2, 1);
  const phase = {binding, activationPath: 1, delay: 0, duration: 5, lifetime: .5, size: [1, 1, 1], texture: 0,
    mainSampler: {mipmaps: [1], filterMode: 1, anisotropy: 8}, startColor: [1, .5, .25, 1],
    material: {tint: [1, 1, 1, 1], queue: 2900, alphaBlend: true, depthTest: true, cull: 2, stencilRef: 2}};
  root.userData.mvStageStationaryBursts = [
    {...phase, mode: "mesh", path: 2, uv: [10, 1, 0, 0],
      geometry: {positions: [[0,0,0], [1,0,0], [0,1,0]], uv: [[0,0], [1,0], [0,1]], indices: [0,1,2]}},
    {...phase, mode: "billboard", path: 3, uv: [.25, .125, .5, .375], delay: .1, size: [2, 1, 1],
      flipX: true, material: {...phase.material, cull: 0},
      maxViewportWidth: .5, sizeKeys: [[0, 1, 0, 0], [.2, 1, 0, 0]], sizeMultiplier: 1},
  ];
  const base = new T.Texture({width: 2, height: 2}), mip = new T.Texture({width: 1, height: 1});
  const parser = {getDependency: async (_type, index) => [base, mip][index]};
  const controller = await MVStudioStationaryBursts.apply(T, root, parser);
  const [mesh, billboard] = [2, 3].map(path => root.getObjectByName(`Native stationary stage burst ${path}`));
  for (const object of [mesh, billboard]) {
    const material = object.material;
    assert.equal(material.depthTest, true);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.depthWrite, false);
    assert.equal(material.side, object === mesh ? T.FrontSide : T.DoubleSide);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilWriteMask, 255);
    assert.equal(object.layers.mask, 1);
  }
  assert.equal(mesh.material.uniforms.uTexture.value, billboard.material.uniforms.uTexture.value);
  assert.deepEqual(mesh.material.uniforms.uTexture.value.mipmaps, [base.image, mip.image]);
  assert.equal(mesh.material.uniforms.uTextureST.value.x, 10);
  assert.deepEqual(billboard.material.uniforms.uAtlas.value.toArray(), [.25,.125,.5,.375]);
  const event = {id: "event", start: 1, duration: 5, values: {animation: "clip"}};
  const project = {
    quality: {values: {frame_rate_60fps: true, stage_display: true}},
    tracks: [{id: "track", binding, nativeClass: "AnimationTrack", events: [event]}],
    stageMotion: {quality: {track: "stage_display"}, mix: {event: {}}, clips: {
      clip: {start: 0, duration: 5, sampleTimeF32: true, channels: [
        {path: 1, kind: "visibility", visibilityType: "gameObject", curves: [["constant", 1]]},
      ]},
    }},
  };
  const motion = MVStudioStageMotion.apply(T, root);
  const show = time => { motion.update(time, project); controller.update(time, project, motion); };
  show(.99);
  assert.equal(mesh.visible, false);
  show(1);
  assert.equal(mesh.visible, true);
  assert.equal(billboard.visible, false);
  assert.deepEqual(mesh.position.toArray(), [4, 10, 18]);
  assert.deepEqual(mesh.scale.toArray(), [1, 1, 1]);
  assert.deepEqual(mesh.material.uniforms.uParticleColor.value.toArray(), [1, 128/255, 64/255, 1]);
  show(1.2);
  assert.equal(billboard.geometry.instanceCount, 1);
  assert.deepEqual(billboard.material.uniforms.uAxisX.value.toArray(), [1, 0, 0]);
  assert.deepEqual(Array.from(billboard.geometry.getAttribute("uv").array), [1,0,0,0,0,1,1,1]);
  assert.deepEqual(Array.from(billboard.geometry.getAttribute("particleSize").array), [2, 2]);
  assert.deepEqual(Array.from(billboard.geometry.getAttribute("particleColor").array), [255, 128, 64, 255]);
  controller.sort(new T.PerspectiveCamera());
  assert.equal(billboard.renderOrder, 2900);
  assert.equal(mesh.renderOrder, 2900.5);
  show(1.8);
  assert.equal(mesh.visible, false);
  assert.equal(billboard.visible, false);
  show(1.2);
  assert.equal(mesh.visible, true);
  project.quality.values.stage_display = false;
  show(1.2);
  assert.equal(mesh.visible, false);
  assert.equal(billboard.visible, false);
  project.quality.values.stage_display = true;
  motion.update(1.2, project);
  controller.update(1.2, project, {accepts: () => false});
  assert.equal(mesh.visible, false);
  controller.dispose();
  assert.equal(root.children.length, 1);

  let active = true;
  const canceled = await MVStudioStationaryBursts.apply(T, root, {
    getDependency: async () => { active = false; return base; },
  }, {active: () => active});
  assert.equal(canceled, null);
  assert.equal(root.children.length, 1);
  console.log("Resident stationary mesh and billboard bursts share native activation, timing, and the display pass.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
