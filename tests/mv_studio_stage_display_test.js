"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-display.js");

async function run() {
  const effect = "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main";
  const material = (texture, queue, uv = [1, 1, 0, 0]) => ({
    texture, queue, uv, cull: queue === 3000 ? 0 : 2, stencil: 2,
    tint: [1, 1, 1, 1], ambient: [1, 1, 1, 0]
  });
  const track = { nativeClass: "LiveDisplayTrack", binding: effect, events: [
    { start: 0, duration: 2, values: { playableClass: "LiveDisplayClip", materialIndex: 0,
      scrollSpeed: { x: 0, y: 0 }, ambientColor: { r: .04, g: .04, b: .04, a: 1 }, blendOut: 1 } },
    { start: 1, duration: 3, values: { playableClass: "LiveDisplayClip", materialIndex: 1,
      scrollSpeed: { x: 0, y: -.125 }, ambientColor: { r: .08, g: .08, b: .08, a: .5 }, blendIn: 1 } }
  ] };
  const fade = MVStudioStageDisplay.sample(track, 1.5);
  assert.equal(fade.material, 1);
  assert.deepEqual(fade.ambient, [.06, .06, .06, .75]);
  assert.deepEqual(fade.offset, [0, -.09375]);

  const root = new T.Group(), original = new T.MeshBasicMaterial();
  const node = new T.Mesh(new T.PlaneGeometry(), original);
  node.geometry.setAttribute("_stage_color", new T.Float32BufferAttribute(Array(4).fill([.5, .75, 1, .25]).flat(), 4));
  node.geometry.userData.mvStageDisplay = {
    target: effect, fallback: material(7, 2000, [1, 1, 0, -.125]),
    variants: [
      { background: material(null, 2000), logo: material(8, 3000) },
      { background: {...material(9, 2000), vertexColor: true, stencilZFail: 2}, logo: material(8, 3000) }
    ]
  };
  root.add(node);
  const decoded = new Map([7, 8, 9].map(index => [index, Object.assign(new T.Texture(), { name: String(index) })]));
  const parser = { getDependency: (_, index) => Promise.resolve(decoded.get(index)) };
  const controller = await MVStudioStageDisplay.apply(T, root, parser);
  const project = { tracks: [track], quality: { values: { stage_display: true } } };

  controller.update(0, project);
  const [logo] = node.children;
  assert.equal(logo.geometry, node.geometry);
  assert.equal(logo.visible, true);
  assert.equal(logo.material.depthWrite, false);
  assert.equal(logo.material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(node.material.stencilWrite, true);
  assert.equal(node.material.stencilFunc, T.AlwaysStencilFunc);
  assert.equal(node.material.stencilZPass, T.ReplaceStencilOp);
  assert.equal(node.material.stencilRef, 2);
  assert.equal(node.material.stencilZFail, T.KeepStencilOp);
  assert.equal(node.material.depthWrite, true);
  assert.equal(node.material.transparent, false);
  assert.equal(node.material.uniforms.uVertexColor.value, false);
  assert.deepEqual(node.material.uniforms.uAmbient.value.toArray(), [.04, .04, .04, 1]);
  assert.deepEqual([...node.material.uniforms.uTexture.value.image.data], [255, 255, 255, 255]);
  controller.update(2.5, project);
  assert.equal(node.material.uniforms.uTexture.value.name, "9");
  assert.equal(node.material.uniforms.uTextureST.value.w, .3125);
  assert.equal(node.material.uniforms.uVertexColor.value, true);
  // _StencilZFailOp 2 also writes the reference where the screen fails the depth test.
  assert.equal(node.material.stencilZFail, T.ReplaceStencilOp);
  assert.equal(logo.material.stencilZFail, T.KeepStencilOp);
  assert.equal(logo.material.uniforms.uVertexColor.value, false);
  project.quality.values.stage_display = false;
  controller.update(2.5, project);
  assert.equal(node.material.uniforms.uTexture.value.name, "7");
  assert.equal(node.material.uniforms.uTextureST.value.w, .125);
  assert.equal(node.material.uniforms.uVertexColor.value, false);
  assert.equal(node.material.stencilZFail, T.KeepStencilOp);
  assert.equal(logo.visible, false);
  controller.dispose();
  assert.equal(node.children.length, 0);
  assert.equal(node.material, original);
  node.geometry.deleteAttribute("_stage_color");
  const uncolored = await MVStudioStageDisplay.apply(T, root, parser);
  project.quality.values.stage_display = true;
  uncolored.update(2.5, project);
  assert.equal(node.material.uniforms.uVertexColor.value, true);
  assert.deepEqual(node.material.defaultAttributeValues._stage_color, [1, 1, 1, 1]);
  assert.equal(node.material.stencilZPass, T.ReplaceStencilOp);
  assert.equal(node.material.stencilRef, 2);
  uncolored.dispose();
  assert.equal(node.material, original);
  console.log("Native stage display: mixed ambient/scroll, backdrop variants, logo pass, stencil, and static fallback, depth-fail stencil replace.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
