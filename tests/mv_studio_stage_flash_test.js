"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-overlay.js");
require("../webtools/web/static/mv-studio-stage-flash.js");

async function run() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fla_01/flash_light_01";
  const geometry = new T.PlaneGeometry(2, 2);
  geometry.setAttribute("_stage_flash_uv", geometry.getAttribute("uv"));
  const fields = { binding, texture: 0, atlas: 1, textureST: [1, 1, 0, 0], atlasST: [4, 2, 0, 0],
    length: 8, saturate: false, autoPlay: true, queue: 3000 };
  geometry.userData.mvStageFlash = fields;
  const original = new T.MeshBasicMaterial();
  const node = new T.Mesh(geometry, original);
  const loaded = [];
  const parser = { async getDependency(kind, index) {
    assert.equal(kind, "texture");
    loaded.push(index);
    return new T.Texture();
  } };
  const lighting = await globalThis.MVStudioStageFlash.apply(T, new T.Group().add(node), parser);
  assert.deepEqual(loaded, [0, 1]);
  assert.equal(node.visible, false);
  assert.equal(node.renderOrder, 3000);
  assert.equal(node.material.depthWrite, false);
  assert.equal(node.material.depthTest, true);
  assert.equal(node.material.blendSrc, T.SrcAlphaFactor);
  const clip = (start, status, speed, type, rgba) => ({ start, duration: 4, values: {
    playableClass: "LiveFlashLightClip", status, speed, colorSpecifiedType: type,
    memberPosition: 1, tintColor: rgba, timeScale: 2, clipIn: 0.125,
  } });
  const first = clip(0, 1, 2, 1, [1, 1, 1, 1]);
  const second = clip(2, 2, 4, 0, [1, 0, 0, 1]);
  first.values.blendOut = second.values.blendIn = 2;
  const track = { nativeClass: "LiveFlashLightTrack", binding, events: [first, second] };
  const quality = { stage_flash_light: true };
  const project = { performers: [{ position: 1, themeColor: [0.2, 0.6, 0.8, 1] }],
    quality: { values: quality }, tracks: [track] };
  const u = node.material.uniforms;
  lighting.update(3, project);
  assert.equal(node.visible, true);
  assert.deepEqual(u.uTint.value.toArray(), [0.6, 0.3, 0.4, 1]);
  assert.equal(u.uSpeed.value, 3);
  assert.equal(u.uAll.value, false);
  assert.equal(u.uTime.value, 3);
  lighting.update(3.5, project);
  assert.equal(u.uAll.value, true);
  fields.autoPlay = false;
  lighting.update(3.5, project);
  assert.equal(u.uTime.value, 3.125);
  lighting.update(6.5, project);
  assert.equal(node.visible, false);
  track.muted = true;
  lighting.update(1, project);
  assert.equal(node.visible, false);
  track.muted = false;
  quality.stage_flash_light = false;
  lighting.update(1, project);
  assert.equal(node.visible, false);
  let disposed = 0;
  node.material.addEventListener("dispose", () => disposed++);
  lighting.dispose();
  assert.equal(disposed, 1);
  assert.equal(node.material, original);
  assert.equal(node.renderOrder, 0);
  console.log("Native flash lighting mixer, atlas controls and quality gate passed");
}

// A LiveCoreStageFlashLight whose material is AS/General/Transparent (the position-1 flash lights,
// mat_fla_01_gen_add_no_01): the mixer sets _TintColor and the renderer's enabled state only.
async function transparentFlash() {
  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fla_01/flash_light_01";
  const geometry = new T.PlaneGeometry(2, 2);
  const transparent = { texture: 0, tint: [1, 1, 1, 1], uv: [1, 1, 0, 0], vertexColor: false, cull: 0, queue: 3000,
    blend: [5, 1], zTest: 4, stencil: [8, 2, 0, 0] };
  geometry.userData.mvStageFlash = { binding, kind: "transparent", enabled: true, transparent, queue: 3000 };
  const original = new T.MeshBasicMaterial();
  const node = new T.Mesh(geometry, original);
  const parser = { async getDependency(kind, index) {
    assert.deepEqual([kind, index], ["texture", 0]);
    return new T.Texture();
  } };
  const lighting = await globalThis.MVStudioStageFlash.apply(T, new T.Group().add(node), parser);
  assert.equal(node.material.name, "Native stage transparent");
  assert.deepEqual([node.material.blendSrc, node.material.blendDst], [T.SrcAlphaFactor, T.OneFactor]);
  assert.equal(node.visible, true);
  assert.equal(node.renderOrder, 3000);
  const event = (start, status) => ({ start, duration: 1, values: { playableClass: "LiveFlashLightClip", status, speed: 3,
    colorSpecifiedType: 0, memberPosition: 1, tintColor: [0.5, 0.25, 1, 0.75] } });
  const track = { nativeClass: "LiveFlashLightTrack", binding, events: [event(0, 2), event(2, 0)] };
  const quality = { stage_flash_light: true };
  const project = { performers: [], quality: { values: quality }, tracks: [track] };
  lighting.update(0.5, project);
  assert.equal(node.visible, true);
  assert.deepEqual(node.material.uniforms.uTint.value.toArray(), [0.5, 0.25, 1, 0.75]);
  assert.equal(node.material.uniforms.uTextureST.value.x, 1, "_Speed and _SelfTime have no input here");
  lighting.update(2.5, project);
  assert.equal(node.visible, false, "status 0 disables the renderer");
  lighting.update(1.5, project);
  assert.equal(node.visible, false, "between clips the mixer applies clear and status 0");
  quality.stage_flash_light = false;
  lighting.invalidate();
  lighting.update(0.5, project);
  assert.equal(node.visible, true, "a muted track runs no mixer: the serialized renderer state stays");
  assert.deepEqual(node.material.uniforms.uTint.value.toArray(), [1, 1, 1, 1]);
  geometry.userData.mvStageFlash.enabled = false;
  lighting.dispose();
  assert.equal(node.material, original);
  const disabled = await globalThis.MVStudioStageFlash.apply(T, new T.Group().add(node), parser);
  assert.equal(node.visible, false);
  disabled.dispose();
  console.log("AS/General/Transparent flash light: mixer tint and renderer status, serialized state without a mixer");
}

run().then(transparentFlash).catch(error => { console.error(error); process.exitCode = 1; });
