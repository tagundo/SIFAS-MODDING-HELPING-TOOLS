"use strict";

// The stage display screen programs (AS/General/Opaque and Transparent, AS/Blend/AdditiveOpaque,
// so1005/so2030 DisplayWaveTexture), the per-variant tolerance and LiveCoreStageDisplay's
// rules for the renderer's own materials and material2DReference.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-display.js");

const effect = "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main";
const stencil = { stencil: 2, stencilComp: 8, stencilPass: 2, stencilZFail: 0 };
const general = (texture, extra = {}) => ({ kind: "general", material: `bg${texture}`, texture, uv: [1, 1, 0, 0], tint: [1, 1, 1, 1],
  ambient: [1, 1, 1, 0], cull: 2, queue: 2000, ...stencil, ...extra });
const logo = (texture, extra = {}) => ({ kind: "transparent", material: `logo${texture}`, texture, uv: [1, 1, 0, 0],
  tint: [1, 1, 1, 1], cull: 0,
  queue: 3000, blend: [5, 10], zTest: 4, zWrite: false, stencil: 2, stencilComp: 8, stencilPass: 0, stencilZFail: 0,
  ...extra });
// mat_dis_bg_so1054_opa_01_oth (11054/3): _AdditiveTex is the display camera's render texture.
const additive = (texture, extra = {}) => ({ ...general(texture), kind: "blendAdditive", vertexColor: true,
  additive: { texture: null, uv: [.5, 1, .25, 0] }, displayCamera: true, ...extra });
// mat_dis_shd_so2030_uni_01 (12030/3).
const wave = (texture, waveTexture) => ({ ...general(texture), kind: "waveTexture", cull: 2, stencilZFail: 2,
  ambient: [0, 0, 0, 0], wave: { texture: waveTexture, color: [1.1608, 1.0039, 2, .251],
    layers: [[.15, 1.75, .05, 0], [.39, 3.82, .05, 0], [.1, .78, .025, 0], [.25, .75, .02, 0]] } });
const clip = (start, duration, materialIndex, extra = {}) => ({ start, duration, values: {
  playableClass: "LiveDisplayClip", materialIndex, scrollSpeed: { x: 0, y: 0 }, ambientColor: { r: 0, g: 0, b: 0, a: 0 },
  ...extra } });

async function build(fields) {
  const root = new T.Group(), original = new T.MeshBasicMaterial();
  const node = new T.Mesh(new T.PlaneGeometry(), original);
  node.renderOrder = 7;
  node.geometry.userData.mvStageDisplay = { target: effect, ...fields };
  root.add(node);
  const decoded = new Map([1, 2, 3, 4, 5, 6].map((index) => [index, Object.assign(new T.Texture(), { name: String(index) })]));
  const parser = { getDependency: (_, index) => Promise.resolve(decoded.get(index)) };
  return { node, original, controller: await MVStudioStageDisplay.apply(T, root, parser) };
}

async function kinds() {
  const fields = {
    fallback: general(1), initial: { background: general(1), logo: null },
    variants: [
      { background: additive(2), logo: logo(3) },
      { background: wave(4, 5), logo: logo(3) },
      // 10122/3 mat_dis_so0122_02: Blend Zero One, ZTest Greater, _SATURATE_ON _VERTEX_COLOR_ON.
      { background: logo(6, { blend: [0, 1], zTest: 5, saturate: true, vertexColor: true }), logo: logo(3) },
      // 12055/3 litE: the logo material is the bg material itself.
      { background: general(6), logo: general(6) }
    ]
  };
  const { node, original, controller } = await build(fields);
  const track = { nativeClass: "LiveDisplayTrack", binding: effect, events: [
    clip(0, 1, 0), clip(1, 1, 1), clip(2, 1, 2),
    clip(3, 1, 3, { ambientColor: { r: .5, g: .25, b: 0, a: .75 }, scrollSpeed: { x: .25, y: 0 } })] };
  const project = { tracks: [track], quality: { values: { stage_display: true } } };
  const [logoMesh] = node.children;

  controller.update(.5, project);
  let material = node.material;
  assert.equal(material.defines.ADDITIVE, 1);
  assert.equal(material.uniforms.uTexture.value.name, "2");
  const feed = material.uniforms.uSecond.value;
  assert.deepEqual([...feed.image.data], [0, 0, 0, 0], "the display camera's cleared render texture");
  assert.deepEqual(material.uniforms.uSecondST.value.toArray(), [.5, 1, .25, 0], "_AdditiveTex_ST, V flipped");
  assert.equal(material.uniforms.uVertexColor.value, true, "the program always reads COLOR");
  assert.equal(material.blending, T.NoBlending);
  assert.equal(material.depthWrite && material.side === T.FrontSide, true);
  assert.match(material.fragmentShader, /float drawn = feed\.y \+ feed\.x \+ feed\.z >= 0\.00100000005 \? 1\.0 : 0\.0;/);
  assert.equal(logoMesh.visible, true);

  controller.update(1.5, project, (time) => time + 990);
  material = node.material;
  assert.equal(material.defines.WAVE, 1);
  assert.equal(material.uniforms.uSecond.value.name, "5", "_WaveTex");
  assert.equal(material.uniforms.uTime.value, 991.5, "_Time.y follows the game clock when one is set");
  assert.deepEqual(material.uniforms.uWave.value.map((layer) => layer.toArray()), fields.variants[1].background.wave.layers);
  assert.deepEqual(material.uniforms.uWaveColor.value.toArray(), [1.1608, 1.0039, 2, .251]);
  assert.equal(material.stencilZFail, T.ReplaceStencilOp);
  assert.match(material.vertexShader, /return uv \* layer\.xy \+ vec2\(uTime \* layer\.z, 1\.0 - layer\.y - uTime \* layer\.w\);/);
  controller.update(1.5, project);
  assert.equal(node.material.uniforms.uTime.value, 1.5, "the director time without a game clock");

  controller.update(2.5, project);
  material = node.material;
  assert.equal(material.defines.TRANSPARENT, 1);
  assert.equal(material.defines.SATURATE, 1);
  assert.equal(material.transparent, true);
  assert.equal(material.blending, T.CustomBlending);
  assert.deepEqual([material.blendSrc, material.blendDst], [T.ZeroFactor, T.OneFactor]);
  assert.deepEqual([material.depthWrite, material.depthFunc], [false, T.GreaterDepth]);
  assert.equal(material.stencilWrite, false, "Always / Keep writes nothing");
  assert.equal(material.uniforms.uVertexColor.value, true);
  assert.equal(node.renderOrder, 3000, "the Transparent queue of AS/General/Transparent");

  controller.update(3.5, project);
  material = node.material;
  assert.equal(material.defines.TRANSPARENT, undefined);
  assert.equal(logoMesh.material.defines.TRANSPARENT, undefined, "an AS/General/Opaque logo");
  assert.deepEqual(logoMesh.material.uniforms.uAmbient.value.toArray(), [.5, .25, 0, .75],
    "the mixer's _AmbientColor lands on the shared material");
  assert.equal(logoMesh.material.uniforms.uTextureST.value.z, .875);
  assert.equal(logoMesh.material.transparent, false);

  // A disabled stage display shows material2DReference without its logo.
  project.quality.values.stage_display = false;
  controller.update(3.5, project);
  assert.equal(node.material.uniforms.uTexture.value.name, "1");
  assert.equal(logoMesh.visible, false);
  controller.dispose();
  assert.equal(node.material, original);
}

async function tolerance() {
  // 12030/3: no material2DReference, so the display stays enabled; variant 0 cannot be drawn here.
  const fields = {
    fallback: null, initial: { background: general(1), logo: logo(3) },
    variants: [{ unsupported: "_MainTex could not be decoded" }, { background: general(2), logo: logo(3) }]
  };
  const { node, original, controller } = await build(fields);
  const [logoMesh] = node.children;
  const track = { nativeClass: "LiveDisplayTrack", binding: effect, events: [clip(0, 1, 0), clip(1, 1, 1)] };
  const project = { tracks: [track], quality: { values: { stage_display: false } } };
  controller.update(.5, project);
  assert.equal(node.material.uniforms.uTexture.value.name, "1", "the renderer's own materials, not the variant");
  assert.equal(logoMesh.visible, true, "its own second material is drawn over the submesh");
  assert.deepEqual(node.material.uniforms.uAmbient.value.toArray(), [1, 1, 1, 0], "the mixer writes the variant, not them");
  controller.update(1.5, project);
  assert.equal(node.material.uniforms.uTexture.value.name, "2", "the other variants still switch");
  // Without a LiveDisplayTrack, nothing changes the renderer's own materials.
  controller.update(1.5, { tracks: [], quality: { values: { stage_display: true } } });
  assert.equal(node.material.uniforms.uTexture.value.name, "1");
  controller.dispose();

  const bare = await build({ fallback: general(1), initial: { unsupported: "the renderer has 3 materials" },
    variants: [{ unsupported: "shader AS/Unknown has no display reader" }, { background: general(2), logo: null }] });
  bare.controller.update(.5, project);
  assert.equal(bare.node.material.uniforms.uTexture.value.name, "1", "disabled: material2DReference");
  project.quality.values.stage_display = true;
  bare.controller.update(.5, project);
  assert.equal(bare.node.material, bare.original, "nothing native to draw: the glTF material");
  assert.equal(bare.node.renderOrder, 7);
  bare.controller.update(1.5, project);
  assert.equal(bare.node.material.uniforms.uTexture.value.name, "2");
  bare.controller.dispose();
  assert.equal(original.isMeshBasicMaterial, true);
}

async function shared() {
  // 12023/3 mat_dis_bg_gen_opa_09 is variant 0 of both screens: LiveDisplayMixer writes _AmbientColor and
  // _MainTex_ST into the one Material, and the game draws both screens with the later track's write
  // (dump5 at 11.224 s: sub_01's ambient on main too; 12035 dump3b/dump5 likewise).
  const root = new T.Group(), nodes = {};
  for (const name of ["main", "sub_01"]) {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial());
    node.geometry.userData.mvStageDisplay = { target: `${effect}/../${name}`, fallback: general(1),
      initial: { background: general(1), logo: null },
      variants: [{ background: general(9), logo: logo(3) }, { background: general(name === "main" ? 4 : 5), logo: logo(3) }] };
    root.add(node);
    nodes[name] = node;
  }
  const parser = { getDependency: (_, index) => Promise.resolve(Object.assign(new T.Texture(), { name: String(index) })) };
  const controller = await MVStudioStageDisplay.apply(T, root, parser);
  const track = (name, ambient, speed, material = 0) => ({ nativeClass: "LiveDisplayTrack", binding: `${effect}/../${name}`,
    events: [clip(0, 10, material, { ambientColor: ambient, scrollSpeed: { x: 0, y: speed } })] });
  const project = { tracks: [track("main", { r: .1, g: .081, b: .081, a: 1 }, 0),
    track("sub_01", { r: .12, g: .084, b: .084, a: 1 }, .5)], quality: { values: { stage_display: true } } };
  controller.update(2, project);
  for (const node of Object.values(nodes)) {
    assert.deepEqual(node.material.uniforms.uAmbient.value.toArray().map((v) => Math.round(v * 1000) / 1000),
      [.12, .084, .084, 1], "the later track's write");
    assert.equal(node.material.uniforms.uTextureST.value.w, -1, "_MainTex_ST offset (0, 2 x .5), V flipped");
  }
  project.tracks.reverse();
  controller.invalidate();
  controller.update(2, project);
  assert.deepEqual(nodes.sub_01.material.uniforms.uAmbient.value.toArray().map((v) => Math.round(v * 1000) / 1000),
    [.1, .081, .081, 1]);
  // Different materials keep their own writes.
  project.tracks = [track("main", { r: 1, g: 0, b: 0, a: .5 }, 0, 1), track("sub_01", { r: 0, g: 1, b: 0, a: .5 }, 0, 1)];
  controller.invalidate();
  controller.update(2, project);
  assert.deepEqual(nodes.main.material.uniforms.uAmbient.value.toArray(), [1, 0, 0, .5]);
  assert.deepEqual(nodes.sub_01.material.uniforms.uAmbient.value.toArray(), [0, 1, 0, .5]);
  controller.dispose();
}

(async () => {
  await kinds();
  await tolerance();
  await shared();
  console.log("Stage display kinds: additive feed, wave layers on _Time.y, transparent and opaque logos, variant tolerance, shared materials.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
