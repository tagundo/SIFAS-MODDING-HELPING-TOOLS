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
  console.log("Native screen overlay: layer and camera, per-renderer material curves, blending and no clear.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
