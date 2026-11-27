"use strict";

// AS/General/Transparent binds its whole pass state to material floats: the native stage
// overlay and world transparent pass apply the exported blend factors, ZTest, ZWrite and
// stencil (UnityEngine.Rendering enum values) and the _SATURATE_ON program.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-stage-overlay.js");

const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_test_01/root";

function scene(fields) {
  const root = new T.Scene(), owner = new T.Group(), original = new T.MeshBasicMaterial();
  const mesh = new T.Mesh(new T.PlaneGeometry(), original);
  owner.userData.mvStageNode = { active: true, path: 0, binding };
  owner.add(mesh);
  root.add(owner);
  mesh.geometry.userData.mvStageOverlay = { texture: null, tint: [1, 1, 1, 1], uv: [1, 1, 0, 0], vertexColor: true,
    cull: 0, queue: 3000, ...fields };
  return { root, mesh, original };
}

function full(blend, zTest, stencil, extra = {}) {
  return { blend, zTest, stencil, ...(zTest === 4 ? { depthTest: true } : {}), ...extra };
}

async function run() {
  // World alpha blend without stencil (12026 shadow mat_stg_so2026_oth_03): sorted, LEqual.
  {
    const { root, mesh } = scene({ ...full([5, 10], 4, [8, 2, 0, 0]), alphaBlend: true, world: true,
      sortCenter: [1, 0, 0] });
    const overlay = await MVStudioStageOverlay.apply(T, root);
    const m = mesh.material;
    assert.equal(m.name, "Native stage transparent");
    assert.deepEqual([m.blendSrc, m.blendDst, m.blendSrcAlpha, m.blendDstAlpha],
      [T.SrcAlphaFactor, T.OneMinusSrcAlphaFactor, T.SrcAlphaFactor, T.OneMinusSrcAlphaFactor]);
    assert.deepEqual([m.depthTest, m.depthFunc, m.depthWrite, m.stencilWrite], [true, T.LessEqualDepth, false, false]);
    assert.equal(overlay.sortEntries().length, 1);
    overlay.dispose();
  }
  // A world alpha blend without sort bounds is refused, as before.
  {
    const { root, mesh, original } = scene({ ...full([5, 10], 4, [8, 2, 0, 0]), alphaBlend: true, world: true });
    assert.equal(await MVStudioStageOverlay.apply(T, root), null);
    assert.equal(mesh.material, original);
  }
  // World ZTest Always with ZWrite (12030 shadow mat_stg_so2030_alb_oth_02 writes depth):
  // WebGL writes depth only with its test on, so the test stays on with ALWAYS.
  {
    const { root, mesh } = scene({ ...full([5, 10], 8, [8, 2, 0, 0]), alphaBlend: true, depthWrite: true, world: true,
      sortCenter: [0, 0, 0] });
    const overlay = await MVStudioStageOverlay.apply(T, root);
    assert.deepEqual([mesh.material.depthTest, mesh.material.depthFunc, mesh.material.depthWrite], [true, T.AlwaysDepth, true]);
    overlay.dispose();
    const additive = scene({ ...full([5, 1], 8, [8, 2, 0, 0]), world: true });
    const second = await MVStudioStageOverlay.apply(T, additive.root);
    assert.deepEqual([additive.mesh.material.depthTest, additive.mesh.material.depthWrite], [false, false]);
    second.dispose();
  }
  // Every BlendMode, CompareFunction and StencilOp value maps to its WebGL counterpart.
  const factors = [T.ZeroFactor, T.OneFactor, T.DstColorFactor, T.SrcColorFactor, T.OneMinusDstColorFactor,
    T.SrcAlphaFactor, T.OneMinusSrcColorFactor, T.DstAlphaFactor, T.OneMinusDstAlphaFactor,
    T.SrcAlphaSaturateFactor, T.OneMinusSrcAlphaFactor];
  for (let value = 0; value <= 10; value++) {
    const { root, mesh } = scene(full([value, value], 4, [8, 2, 0, 0], { alphaBlend: true }));
    const overlay = await MVStudioStageOverlay.apply(T, root);
    assert.deepEqual([mesh.material.blendSrc, mesh.material.blendDst], [factors[value], factors[value]], `blend ${value}`);
    overlay.dispose();
  }
  const depths = [T.AlwaysDepth, T.NeverDepth, T.LessDepth, T.EqualDepth, T.LessEqualDepth, T.GreaterDepth,
    T.NotEqualDepth, T.GreaterEqualDepth, T.AlwaysDepth];
  for (let value = 0; value <= 8; value++) {
    const { root, mesh } = scene(full([5, 1], value, [8, 2, 0, 0]));
    const overlay = await MVStudioStageOverlay.apply(T, root);
    assert.equal(mesh.material.depthFunc, depths[value], `ZTest ${value}`);
    assert.equal(mesh.material.depthTest, value !== 0 && value !== 8, `ZTest ${value} test`);
    overlay.dispose();
  }
  const functions = [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc, T.EqualStencilFunc,
    T.LessEqualStencilFunc, T.GreaterStencilFunc, T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc];
  const operations = [T.KeepStencilOp, T.ZeroStencilOp, T.ReplaceStencilOp, T.IncrementStencilOp, T.DecrementStencilOp,
    T.InvertStencilOp, T.IncrementWrapStencilOp, T.DecrementWrapStencilOp];
  for (let comparison = 0; comparison <= 8; comparison++) {
    for (const [pass, zFail] of [[0, 0], [2, 0], [0, 7], [5, 3]]) {
      const { root, mesh } = scene(full([5, 1], 4, [comparison, 4, pass, zFail]));
      const overlay = await MVStudioStageOverlay.apply(T, root);
      const m = mesh.material, active = !(comparison === 0 || comparison === 8) || pass !== 0 || zFail !== 0;
      assert.equal(m.stencilWrite, active, `stencil ${comparison} ${pass} ${zFail}`);
      if (active) {
        assert.deepEqual([m.stencilFunc, m.stencilRef, m.stencilZPass, m.stencilZFail, m.stencilFail],
          [functions[comparison], 4, operations[pass], operations[zFail], T.KeepStencilOp]);
      }
      overlay.dispose();
    }
  }
  // Overlay (layer 20) alpha blend: the orthographic overlay camera needs no sort bounds.
  {
    const { root, mesh } = scene({ ...full([5, 10], 4, [8, 2, 0, 0]), alphaBlend: true });
    const overlay = await MVStudioStageOverlay.apply(T, root);
    assert.equal(mesh.layers.mask, 1 << 20);
    assert.equal(mesh.material.blendDst, T.OneMinusSrcAlphaFactor);
    assert.equal(overlay.hasVisible(), true);
    mesh.material.uniforms.uTint.value.w = 0;
    assert.equal(overlay.hasVisible(), false, "SrcAlpha/OneMinusSrcAlpha leaves the target unchanged at zero alpha");
    overlay.dispose();
    // One/One adds the colour whatever the tint alpha.
    const added = scene({ ...full([1, 1], 4, [8, 2, 0, 0]), tint: [1, 1, 1, 0] });
    const second = await MVStudioStageOverlay.apply(T, added.root);
    assert.equal(second.hasVisible(), true);
    second.dispose();
  }
  // _SATURATE_ON adds (tex.rgb^2)^2 after the tint and vertex colour, alpha unchanged.
  {
    const { root, mesh } = scene(full([5, 1], 4, [8, 2, 0, 0], { saturate: true }));
    const overlay = await MVStudioStageOverlay.apply(T, root);
    assert.equal(mesh.material.defines.SATURATE, 1);
    assert.match(mesh.material.fragmentShader, /#ifdef SATURATE\s+vec3 square = surface\.rgb \* surface\.rgb;\s+gl_FragColor\.rgb \+= square \* square;/);
    overlay.dispose();
    const plain = scene(full([5, 1], 4, [8, 2, 0, 0]));
    const second = await MVStudioStageOverlay.apply(T, plain.root);
    assert.equal(plain.mesh.material.defines.SATURATE, undefined);
    second.dispose();
  }
  // Malformed full-state descriptors are refused.
  for (const bad of [full([5, 11], 4, [8, 2, 0, 0]), full([5], 4, [8, 2, 0, 0]), full([5, 1], 9, [8, 2, 0, 0]),
    full([5, 1], 4, [9, 2, 0, 0]), full([5, 1], 4, [8, 256, 0, 0]), full([5, 1], 4, [8, 2, 8, 0]),
    full([5, 1], 4, [8, 2, 0, 0], { saturate: 1 }), { ...full([5, 1], 8, [8, 2, 0, 0]), depthTest: true },
    full([5, 1.5], 4, [8, 2, 0, 0])]) {
    const { root, mesh, original } = scene(bad);
    assert.equal(await MVStudioStageOverlay.apply(T, root), null, JSON.stringify(bad));
    assert.equal(mesh.material, original);
  }
  console.log("Native transparent pass state: blend, ZTest, ZWrite, stencil and saturate from the material floats.");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
