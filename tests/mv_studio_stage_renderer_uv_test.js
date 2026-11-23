"use strict";

// A world-scope stage AnimationClip with a MeshRenderer _MainTex_ST curve
// (12025 Anim_root: speaker _MainTex_ST plus cap m_IsActive) drives the
// renderer's own native stage material instead of rejecting the clip.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-stage-motion.js");

const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so2025_01/root";
const SPEAKER = 11, CAP = 22, PANEL = 33;

function surface(parent, uvTransform) {
  const geometry = new T.PlaneGeometry();
  geometry.userData.mvStageMaterial = {
    shader: "general", uvTransform, cull: 0,
    colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [1, 1, 1, 0]},
  };
  const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial({map: new T.Texture()}));
  parent.add(mesh);
  return mesh;
}

async function run() {
  const root = new T.Group(), stageRoot = new T.Group();
  const speaker = new T.Group(), cap = new T.Group(), panel = new T.Group();
  root.add(stageRoot);
  stageRoot.add(speaker, cap, panel);
  stageRoot.userData.mvStageNode = {active: true, binding, path: 0};
  speaker.userData.mvStageNode = {active: true, binding, path: SPEAKER};
  cap.userData.mvStageNode = {active: true, binding, path: CAP};
  panel.userData.mvStageNode = {active: true, binding, path: PANEL};
  // Unity _MainTex_ST (1, 0.9, 0, 0) in glTF space.
  const speakerMesh = surface(speaker, [1, .9, 0, .1]);
  surface(cap, [1, 1, 0, 0]);
  // A renderer with two stage materials has no single _MainTex_ST holder.
  surface(panel, [1, 1, 0, 0]);
  surface(panel, [2, 2, 0, 0]);

  const material = await MVStudioStageMaterial.apply(T, root, {});
  const motion = MVStudioStageMotion.apply(T, root);
  assert.equal(MVStudioStageMaterial.materialChannel(speaker, "overlayTint"), undefined);
  assert.equal(MVStudioStageMaterial.materialChannel(panel, "overlayUV"), undefined);

  const event = {id: "anim", start: 0, duration: 108, values: {animation: "clip_stg_so2025_01"}};
  const project = {
    tracks: [{id: "track", nativeClass: "AnimationTrack", binding, events: [event]}],
    quality: {values: {stage_animation: true}},
    stageMotion: {
      quality: {track: "stage_animation"},
      mix: {anim: {materialScope: "world"}},
      clips: {clip_stg_so2025_01: {start: 0, duration: 108, sampleTimeF32: true, requiresOverlayMaterial: true, channels: [
        {path: CAP, kind: "visibility", visibilityType: "gameObject", curves: [["linear", [[0, 1], [60, 1], [60.1, 0]]]]},
        {path: SPEAKER, kind: "overlayUV", curves: [
          ["constant", 1], ["linear", [[0, 1], [4, 1.2]]], ["constant", 0], ["linear", [[0, 0], [4, -.2]]],
        ]},
      ]}},
    },
  };
  const frame = (time) => {
    motion.update(time, project);
    material.update(time, project, null);
  };
  const transform = () => speakerMesh.material.uniforms.mainUVTransform.value.toArray();
  const near = (actual, expected) => actual.forEach((value, index) => assert(Math.abs(value - expected[index]) < 1e-6,
    `${actual} != ${expected}`));

  frame(2);
  assert(motion.accepts(event));
  // Unity (sx, sy, ox, oy) = (1, 1.1, 0, -0.1) -> glTF (sx, sy, ox, 1 - sy - oy).
  near(transform(), [1, 1.1, 0, 0]);
  assert.equal(cap.visible, true);
  frame(4);
  near(transform(), [1, 1.2, 0, 0]);
  frame(61);
  assert.equal(cap.visible, false, "the cap's m_IsActive curve is kept with the renderer material curve");
  // Hold past the clip's last key, then the authored value once no clip is active.
  near(transform(), [1, 1.2, 0, 0]);
  frame(120);
  near(transform(), [1, .9, 0, .1]);
  assert.equal(cap.visible, true);

  // A material curve on a renderer without its own holder rejects the whole clip.
  project.stageMotion = {...project.stageMotion, clips: {clip_stg_so2025_01: {
    ...project.stageMotion.clips.clip_stg_so2025_01,
    channels: [project.stageMotion.clips.clip_stg_so2025_01.channels[0],
      {...project.stageMotion.clips.clip_stg_so2025_01.channels[1], path: PANEL}],
  }}};
  frame(61);
  assert(!motion.accepts(event));
  assert.equal(cap.visible, true);
  near(transform(), [1, .9, 0, .1]);

  material.dispose();
  assert.equal(MVStudioStageMaterial.materialChannel(speaker, "overlayUV"), undefined);
  console.log("Native stage renderer UV: world MeshRenderer _MainTex_ST curves drive the renderer's own stage material.");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
