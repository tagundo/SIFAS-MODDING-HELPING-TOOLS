"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
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

run().then(testRequiredMaterial).catch(error => { console.error(error); process.exitCode = 1; });
