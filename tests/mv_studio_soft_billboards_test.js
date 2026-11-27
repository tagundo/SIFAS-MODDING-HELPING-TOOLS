"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-soft-billboards.js");

function fog(root) {
  const owner = new T.Group();
  owner.userData.mvStageNode = {binding: "/Effect/root", path: 1, active: true};
  root.add(owner);
  const geo = new T.PlaneGeometry();
  geo.setAttribute("_soft_center", new T.Float32BufferAttribute(geo.getAttribute("position").count * 3, 3));
  geo.setAttribute("_stage_color", new T.Uint8BufferAttribute(new Uint8Array([
    64, 96, 128, 255, 64, 96, 128, 255, 64, 96, 128, 255, 64, 96, 128, 255,
  ]), 4, true));
  const data = {kind: "fog", texture: 0, queue: 3000, sortCenter: [.2, .4, .6], cull: 2, alphaBlend: true,
    depthTest: true, depthWrite: false, stencil: {comparison: 8, ref: 2, pass: 0, zFail: 0},
    mainSampler: {mipmaps: [1], filterMode: 1, anisotropy: 1},
    uniforms: {_Color: [1, .8, .6, 1], _MainTex_ST: [1, 1, 0, 0], _Density: .3,
      _SizeStartX: 2, _SizeStartY: 2, _SizeEndX: 3, _SizeEndY: 3, _SizeSpeed: 0, _SizeRandom: .5,
      _SizeAspect: 1.5, _AlphaAnimPower: 6, _AlphaAnimScale: .5, _MoveIntensity: .1, _MoveSpeed: .5},
  };
  geo.userData.mvStageSoftBillboard = data;
  const original = new T.MeshBasicMaterial();
  const mesh = new T.Mesh(geo, original);
  owner.add(mesh);
  return {owner, mesh, original, data};
}

async function run() {
  const root = new T.Scene();
  const {owner, mesh, original, data} = fog(root);
  const base = new T.Texture({width: 2, height: 2}), mip = new T.Texture({width: 1, height: 1});
  const parser = {getDependency(type, index) {
    assert.equal(type, "texture");
    return Promise.resolve([base, mip][index]);
  }};
  const {apply, materialChannel} = MVStudioSoftBillboards;
  const controller = await apply(T, root, parser);
  const {material} = mesh, u = material.uniforms;
  assert.equal(material.side, T.FrontSide);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, false);
  assert.equal(material.stencilWrite, false);
  assert.equal(material.blendSrcAlpha, T.SrcAlphaFactor);
  assert.equal(material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
  assert.equal(mesh.renderOrder, 3000);
  const entries = controller.sortEntries();
  assert.equal(controller.sortEntries(), entries);
  assert.deepEqual(entries, [{node: mesh, anchor: mesh, center: new T.Vector3(.2, .4, .6), queue: 3000}]);
  assert.equal(mesh.frustumCulled, false);
  assert.notEqual(u.uTexture.value, base);
  assert.equal(u.uTexture.value.minFilter, T.LinearMipmapNearestFilter);
  assert.deepEqual(u.uTexture.value.mipmaps, [base.image, mip.image]);
  assert.deepEqual(base.mipmaps, []);
  assert.equal(controller.hasVisible(), true);
  // The fade has a native .05 floor, so animated zero alpha cannot skip the mesh/depth pass.
  assert.equal(materialChannel(owner, "overlayColor"), u._Color.value);
  assert.equal(materialChannel(owner, "overlayColor", "_Color"), u._Color.value);
  assert.equal(materialChannel(owner, "overlayScalar", "_Density"), u._Density);
  assert.equal(materialChannel(owner, "overlayScalar", "_MusicTime"), null);
  u._Color.value.w = 0;
  assert.equal(data.uniforms._Color[3], 1);
  assert.equal(controller.hasVisible(), true);
  owner.visible = false;
  assert.equal(controller.hasVisible(), false);
  owner.visible = true;
  controller.update(13.23456, {});
  assert.equal(u._MusicTime.value, Math.fround(Math.fround(13234) * Math.fround(.001)));
  controller.update(-.00172, {});
  assert.equal(u._MusicTime.value, -Math.fround(.001));
  const depth = new T.DepthTexture(320, 180, T.UnsignedInt248Type);
  const perspective = new T.PerspectiveCamera(40, 16 / 9, .37, 450);
  controller.setDepth(depth, perspective);
  assert.equal(u.uOpaqueDepth.value, depth);
  assert.deepEqual(u.uDepthRange.value.toArray(), [.37, 450]);
  assert.equal(u.uHasOpaqueDepth.value, true);
  assert.equal(u.uOrthographic.value, false);
  controller.setDepth(null, new T.OrthographicCamera(-2, 2, 2, -2, .02, 500));
  assert.equal(u.uOpaqueDepth.value, null);
  assert.equal(u.uHasOpaqueDepth.value, false);
  assert.equal(u.uOrthographic.value, true);
  assert.deepEqual(u.uDepthRange.value.toArray(), [.02, 500]);
  controller.dispose();
  controller.dispose();
  assert.equal(mesh.material, original);
  assert.equal(mesh.frustumCulled, true);
  assert.equal(mesh.renderOrder, 0);
  assert.equal(controller.hasVisible(), false);
  assert.deepEqual(entries, []);
  assert.equal(materialChannel(owner, "overlayColor"), null);

  const duplicate = mesh.clone();
  owner.add(duplicate);
  assert.equal(await apply(T, root, parser), null);
  assert.equal(mesh.material, original);
  owner.remove(duplicate);
  data.stencil.comparison = 3;
  assert.equal(await apply(T, root, parser), null);
  data.stencil.comparison = 8;

  let finish, active = true;
  const pending = apply(T, root, {getDependency: (_, index) => index ? Promise.resolve(mip) :
    new Promise(resolve => { finish = resolve; })}, {active: () => active});
  await Promise.resolve();
  active = false;
  finish(base);
  assert.equal(await pending, null);
  assert.equal(mesh.material, original);
  assert.equal(materialChannel(owner, "overlayColor"), null);
  console.log("Native fog sampler, view depth binding, typed live uniforms, visibility and cleanup passed.");
}

async function testSmoke() {
  const root = new T.Scene(), first = fog(root), second = fog(root);
  second.owner.userData.mvStageNode.path = 2;
  second.mesh.geometry.deleteAttribute("_soft_center");
  second.mesh.geometry.deleteAttribute("_stage_color");
  Object.assign(second.data, {kind: "smoke", sortCenter: undefined, stencil: {comparison: 6, ref: 4, pass: 2, zFail: 0}, uniforms: {
    _Color: [.8, .6, .4, 1], _MainTex_ST: [1, 1, 0, 0], _Density: .6, _DensitySaturate: .2,
    _TextureRate: .75, _FadeOutPower: 2, _FadeOutScale: 7, _DistortionAmplitude: .1,
    _DistortionSpeed: .3, _DistortionFreq: 4, _WaveAmplitude: .6, _WaveSpeed: .2, _WaveFreq: 4,
    _FlowAmplitude: .1, _FlowSpeed: .2, _FlowFreq: 3, _CurveIntensity: 1.2, _CurvePower: 3,
    _LightFlatness: .7, _LightSmoothness: .5, _LightDirection: [0, -1, .2, 0],
  }});
  const base = new T.Texture({width: 2, height: 2}), mip = new T.Texture({width: 1, height: 1});
  const textures = [base, mip], requests = [];
  const parser = {getDependency(type, index) {
    requests.push([type, index]);
    return Promise.resolve(textures[index]);
  }};
  // The unmodified GLTF material is another user of this base map.
  first.original.map = base;
  let baseDisposals = 0, copyDisposals = 0, mipDisposals = 0;
  base.addEventListener("dispose", () => baseDisposals++);
  mip.addEventListener("dispose", () => mipDisposals++);
  const {apply, materialChannel} = MVStudioSoftBillboards;
  const controller = await apply(T, root, parser);
  const smoke = second.mesh.material, fogMaterial = first.mesh.material;
  assert.equal(smoke.name, "Native stage smoke");
  assert.equal(controller.sortEntries().length, 1);
  assert.deepEqual(smoke.defaultAttributeValues._stage_color, [1, 1, 1, 1]);
  assert.equal(smoke.stencilWrite, true);
  assert.equal(smoke.stencilFunc, T.NotEqualStencilFunc);
  assert.equal(smoke.stencilRef, 4);
  assert.equal(smoke.stencilFail, T.KeepStencilOp);
  assert.equal(smoke.stencilZFail, T.KeepStencilOp);
  assert.equal(smoke.stencilZPass, T.ReplaceStencilOp);
  assert.equal(smoke.stencilWriteMask, 255);
  assert.equal(smoke.uniforms.uTexture.value, fogMaterial.uniforms.uTexture.value);
  assert.equal(smoke.uniforms._MusicTime, fogMaterial.uniforms._MusicTime);
  assert.equal(smoke.uniforms.uOpaqueDepth, fogMaterial.uniforms.uOpaqueDepth);
  assert.deepEqual(requests, [["texture", 0], ["texture", 1]]);
  smoke.uniforms.uTexture.value.addEventListener("dispose", () => copyDisposals++);
  const paint = materialChannel(second.owner, "overlayColor", "_Color");
  assert.deepEqual(paint.toArray(), [.8, .6, .4, 1]);
  assert.equal(materialChannel(second.owner, "overlayScalar", "_FadeOutScale"), smoke.uniforms._FadeOutScale);
  assert.equal(materialChannel(second.owner, "overlayScalar", "_SizeAspect"), null);
  assert.deepEqual(smoke.uniforms._LightDirection.value.toArray(), [0, -1, .2, 0]);
  controller.dispose();
  assert.equal(first.mesh.material, first.original);
  assert.equal(second.mesh.material, second.original);
  assert.equal(baseDisposals, 0);
  assert.equal(copyDisposals, 1);
  assert.equal(mipDisposals, 1);

  second.mesh.geometry.deleteAttribute("normal");
  const fogOnly = await apply(T, root, parser);
  assert.equal(second.mesh.material, second.original);
  assert.equal(materialChannel(second.owner, "overlayColor"), null);
  fogOnly.dispose();
  console.log("Native smoke inputs and first-touch stencil, shared depth, sampler ownership and role validation passed.");
}

async function testQueue() {
  // 11060/3's fog keeps its authored transparent queue 3010; queues outside the transparent range are refused.
  const parser = {getDependency: () => Promise.resolve(new T.Texture({width: 1, height: 1}))};
  for (const [queue, drawn] of [[3010, true], [2501, true], [5000, true], [2500, false], [5001, false], [3000.5, false]]) {
    const root = new T.Scene();
    const {mesh, original, data} = fog(root);
    data.queue = queue;
    data.mainSampler = {mipmaps: [0], filterMode: 1, anisotropy: 1};
    const controller = await MVStudioSoftBillboards.apply(T, root, parser);
    assert.equal(mesh.material !== original, drawn, `queue ${queue}`);
    if (drawn) {
      assert.equal(mesh.renderOrder, queue);
      assert.equal(controller.sortEntries()[0].queue, queue);
      controller.dispose();
    } else {
      assert.equal(controller, null);
    }
  }
  console.log("Native soft billboards keep their authored transparent queue.");
}

run().then(testSmoke).then(testQueue).catch(error => { console.error(error); process.exitCode = 1; });
