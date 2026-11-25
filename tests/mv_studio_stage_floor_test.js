"use strict";

// Float-bound pass state of the stage materials: AS/Stage _SrcBlend/_DstBlend/_ZWrite,
// the stencil floats and the render queue.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");

function stageMeta(overrides = {}) {
  return {
    shader: "stage", colors: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1], _BlendColor: [1, 1, 1, 0]},
    cull: 2, uvTransform: [1, 1, 0, 0], vertexColor: true, mipBias: 0, lightmap: 0, reflectionToggle: false,
    queue: 2000, ...overrides,
  };
}

function surface(root, meta) {
  const geometry = new T.PlaneGeometry();
  geometry.setAttribute("_stage_light_uv", geometry.getAttribute("uv").clone());
  geometry.setAttribute("_stage_color", new T.Float32BufferAttribute(new Array(16).fill(1), 4));
  geometry.userData.mvStageMaterial = meta;
  const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: new T.Texture()}));
  node.renderOrder = 7;
  root.add(node);
  return node;
}

async function passStateTest() {
  const root = new T.Group();
  const opaque = surface(root, stageMeta());
  // 10006/3 bg0004_01_stageB_cut_mt: _BlendMode 1 left in the Geometry queue.
  const geometryQueue = surface(root, stageMeta({blend: [5, 10], depthWrite: false}));
  // 10022/3 bg0007_04_plantsA_tra_mt and 11009/3 bg0010_01_stageA_add_ref_mt: queue 3000.
  const plants = surface(root, stageMeta({blend: [5, 10], depthWrite: false, queue: 3000, alphaSource: "multiply"}));
  const additive = surface(root, stageMeta({blend: [5, 1], depthWrite: false, queue: 3000, alphaSource: "vertex"}));
  // 12021/3 bg0025_01_stageC_prj_mt: Comp Always, Pass Replace, Ref 2.
  const writer = surface(root, stageMeta({stencil: {ref: 2, comp: 8, pass: 2, zfail: 0}}));
  const tester = surface(root, stageMeta({stencil: {ref: 3, comp: 3, pass: 0, zfail: 7}}));
  const rejected = [
    stageMeta({blend: [5, 9]}), stageMeta({blend: [11, 0]}), stageMeta({blend: [5]}), stageMeta({depthWrite: true}),
    stageMeta({queue: 5001}), stageMeta({queue: 2.5}), stageMeta({stencil: {ref: 256, comp: 8, pass: 2, zfail: 0}}),
    stageMeta({stencil: {ref: 2, comp: 9, pass: 2, zfail: 0}}), stageMeta({stencil: {ref: 2, comp: 8, pass: 8, zfail: 0}}),
    stageMeta({alphaSource: "color"}),
  ].map(meta => surface(root, meta));
  const originals = rejected.map(node => node.material);
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => new T.Texture()});
  assert.ok(controller);

  assert.deepEqual([opaque.material.blending, opaque.material.transparent, opaque.material.depthWrite, opaque.renderOrder],
    [T.NormalBlending, false, true, 7], "opaque defaults keep three.js's opaque pass");
  assert.equal(opaque.material.defines.STAGE_ALPHA, 1, "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA");
  assert.equal(opaque.material.stencilWrite, false);

  const blended = geometryQueue.material;
  assert.deepEqual([blended.blending, blended.blendSrc, blended.blendDst, blended.blendSrcAlpha, blended.blendDstAlpha],
    [T.CustomBlending, T.SrcAlphaFactor, T.OneMinusSrcAlphaFactor, T.SrcAlphaFactor, T.OneMinusSrcAlphaFactor]);
  assert.deepEqual([blended.transparent, blended.depthWrite, geometryQueue.renderOrder], [false, false, 7],
    "queue 2000 blends inside the opaque pass");

  assert.deepEqual([plants.material.transparent, plants.renderOrder, plants.material.defines.STAGE_ALPHA], [true, 3000, 2]);
  assert.deepEqual([additive.material.blendSrc, additive.material.blendDst, additive.material.transparent,
    additive.renderOrder, additive.material.defines.STAGE_ALPHA], [T.SrcAlphaFactor, T.OneFactor, true, 3000, 0]);

  assert.deepEqual([writer.material.stencilWrite, writer.material.stencilRef, writer.material.stencilFunc,
    writer.material.stencilZPass, writer.material.stencilZFail, writer.material.stencilFail, writer.material.stencilFuncMask],
  [true, 2, T.AlwaysStencilFunc, T.ReplaceStencilOp, T.KeepStencilOp, T.KeepStencilOp, 0xff]);
  assert.deepEqual([tester.material.stencilRef, tester.material.stencilFunc, tester.material.stencilZPass,
    tester.material.stencilZFail], [3, T.EqualStencilFunc, T.KeepStencilOp, T.DecrementWrapStencilOp]);

  rejected.forEach((node, index) => assert.equal(node.material, originals[index], `rejected pass state ${index}`));
  controller.dispose();
  assert.deepEqual([plants.renderOrder, additive.renderOrder, opaque.renderOrder], [7, 7, 7], "dispose restores the order");
  assert.equal(plants.material.isMeshBasicMaterial, true);
}

function cutoutMeta(overrides = {}) {
  return {shader: "cutout", colors: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]}, cull: 0,
    uvTransform: [1, 1, 0, 0], vertexColor: false, alphaCutoff: .5, queue: 2450, ...overrides};
}

function plain(root, meta, color = false) {
  const geometry = new T.PlaneGeometry();
  if (color) geometry.setAttribute("_stage_color", new T.Float32BufferAttribute(new Array(16).fill(1), 4));
  geometry.userData.mvStageMaterial = meta;
  const node = new T.Mesh(geometry, new T.MeshBasicMaterial({map: new T.Texture()}));
  root.add(node);
  return node;
}

async function cutoutTest() {
  const root = new T.Group();
  // 12128/3 bg0038_01_skyA_cut_mt: Cull Off, ZWrite On, the AlphaTest queue.
  const sky = plain(root, cutoutMeta());
  // 12026/3 mat_stg_so2026_oth_02: COLOR, Cull Back, queue 3000 without blending.
  const chair = plain(root, cutoutMeta({cull: 2, queue: 3000, vertexColor: true}), true);
  // 10008/3 bg0014_01_grassA_cut_mt: ZWrite Off; 12030/3 torches: saturate; a Greater ZTest.
  const grass = plain(root, cutoutMeta({depthWrite: false, alphaCutoff: .4, depthTest: 5}));
  const torch = plain(root, cutoutMeta({saturate: true, vertexColor: true}), true);
  const rejected = [cutoutMeta({alphaCutoff: undefined}), cutoutMeta({alphaCutoff: 2}), cutoutMeta({saturate: false}),
    cutoutMeta({depthTest: 9}), cutoutMeta({depthTest: 4}), {...cutoutMeta(), shader: "general", saturate: true},
    cutoutMeta({vertexColor: true})].map(meta => plain(root, meta));
  const originals = rejected.map(node => node.material);
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => new T.Texture()});
  assert.ok(controller);
  const material = sky.material;
  assert.deepEqual([material.defines.TINT_THEN_COLOR, material.defines.CUTOUT, material.defines.SATURATE,
    material.defines.VERTEX_COLOR, material.defines.LIGHTMAPPED], [1, 1, undefined, undefined, undefined]);
  assert.deepEqual([material.side, material.transparent, material.depthWrite, material.depthFunc, material.uniforms.alphaCutoff.value],
    [T.DoubleSide, false, true, T.LessEqualDepth, .5]);
  assert.ok(material.uniforms.mainMap.value.isTexture && material.uniforms.mainUVTransform.value.isVector4,
    "the camera depth pass reads the cutout's map, transform and _Cutoff");
  assert.deepEqual([chair.material.side, chair.material.transparent, chair.material.blending, chair.renderOrder,
    chair.material.defines.VERTEX_COLOR], [T.FrontSide, true, T.NoBlending, 3000, 1], "Blend One Zero in queue 3000");
  assert.deepEqual([grass.material.depthWrite, grass.material.depthFunc, grass.material.uniforms.alphaCutoff.value],
    [false, T.GreaterDepth, .4]);
  assert.equal(torch.material.defines.SATURATE, 1);
  rejected.forEach((node, index) => assert.equal(node.material, originals[index], `rejected cutout ${index}`));
  controller.dispose();
  assert.equal(chair.renderOrder, 0);
}

async function coloringTest() {
  const root = new T.Group();
  // 10008/3 cmn_mat_lit_02 (the litC bodies): Cull Off, COLOR, the white default palette.
  const body = plain(root, {shader: "coloring", colors: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]}, cull: 0,
    uvTransform: [1, 1, 0, 0], vertexColor: true, queue: 2000}, true);
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => new T.Texture()});
  const {defines, side, transparent, uniforms} = body.material;
  assert.deepEqual([defines.TINT_THEN_COLOR, defines.CUTOUT, defines.VERTEX_COLOR, side, transparent, uniforms.alphaCutoff],
    [1, undefined, 1, T.DoubleSide, false, undefined]);
  controller.dispose();
}

(async () => {
  await passStateTest();
  await cutoutTest();
  await coloringTest();
  console.log("Stage pass state, TransparentCutout and Coloring/Opaque: blend, ZWrite, ZTest, cull, queue and stencil follow the material floats.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
