"use strict";

// AS/Blend/Opaque (10120 fx_stg_so0120_01/root/sky_01, the so1017, so1022,
// so0012 and so1044 skies): the stage material draws both maps through their
// own _ST, then COLOR, _AmbientColor and _TintColor.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");

const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_stg_so0120_01/root";
const SKY = 769206466;  // crc32("sky_01")

function blendMeta(overrides = {}) {
  return {
    shader: "blend", colors: {_TintColor: [1, 1, 1, 1], _AmbientColor: [1, 1, 1, 0]}, ambientDefaults: null, cull: 2,
    blendRate: 0, uvTransform: [1, 1, 0, 0], blendUVTransform: [2, 1, .5, 0], vertexColor: true,
    mainTexture: 0, blendTexture: 1, ...overrides,
  };
}

function textures() {
  const made = [0, 1, 2].map((index) => {
    const texture = new T.DataTexture(new Uint8Array([index, 0, 0, 255]), 1, 1);
    texture.name = "texture " + index;
    return texture;
  });
  const requested = [];
  return {made, requested, parser: {getDependency: async (kind, index) => {
    requested.push([kind, index]);
    return made[index];
  }}};
}

function dome(parent, meta) {
  const geometry = new T.PlaneGeometry();
  geometry.setAttribute("_stage_color", new T.Float32BufferAttribute([1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0], 4));
  geometry.userData.mvStageMaterial = meta;
  const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial());
  parent.add(mesh);
  return mesh;
}

async function materialTest() {
  const root = new T.Group(), owner = new T.Group();
  owner.userData.mvStageNode = {active: true, binding, path: SKY};
  root.add(owner);
  const sky = dome(owner, blendMeta());
  const unset = dome(root, blendMeta({blendTexture: null}));
  const missing = dome(root, blendMeta({mainTexture: "0"}));
  const noColor = dome(root, blendMeta({vertexColorAbsent: true}));
  noColor.geometry.deleteAttribute("_stage_color");
  const {made, parser} = textures();
  const controller = await MVStudioStageMaterial.apply(T, root, parser);
  assert.ok(controller);

  const material = sky.material;
  assert.equal(material.isShaderMaterial, true);
  assert.deepEqual([material.defines.TEXTURED, material.defines.BLEND, material.defines.VERTEX_COLOR], [1, 1, 1]);
  assert.equal(material.side, T.FrontSide, "_CullMode 2 culls back faces");
  assert.equal(material.transparent, false);
  assert.equal(material.depthWrite && material.depthTest && material.depthFunc === T.LessEqualDepth, true,
    "the compiled pass keeps ZWrite On and ZTest LEqual");
  assert.equal(material.toneMapped, false);
  assert.equal(material.uniforms.mainMap.value.image, made[0].image, "_MainTexA is the first map");
  assert.equal(material.uniforms.blendMap.value.image, made[1].image, "_MainTexB is the second map");
  assert.equal(material.uniforms.mainMap.value.encoding, T.LinearEncoding, "gamma-space maps are sampled as stored");
  assert.deepEqual(material.uniforms.blendUVTransform.value.toArray(), [2, 1, .5, 0]);
  assert.equal(material.uniforms.blendRate.value, 0);
  assert.match(material.fragmentShader, /surface \+= blendRate \* \(texture2D\(blendMap, vStageBlendUV\) - surface\);/);
  assert.match(material.vertexShader, /vStageBlendUV = uv \* blendUVTransform\.xy \+ blendUVTransform\.zw;/);
  // _MainTexB unset: Unity's "white" default texture.
  const white = unset.material.uniforms.blendMap.value;
  assert.deepEqual([white.image.width, white.image.height, ...white.image.data], [1, 1, 255, 255, 255, 255]);
  assert.equal(missing.material.isMeshBasicMaterial, true, "an invalid texture reference keeps the glTF material");
  assert.deepEqual(noColor.material.defaultAttributeValues._stage_color, [1, 1, 1, 1],
    "a mesh without COLOR reads opaque white");

  assert.equal(MVStudioStageMaterial.materialChannel(owner, "overlayUV"), undefined,
    "_MainTex_ST is not an AS/Blend/Opaque property");
  controller.dispose();
  assert.equal(sky.material.isMeshBasicMaterial, true, "dispose restores the glTF material");
}

(async () => {
  await materialTest();
  console.log("AS/Blend/Opaque: both maps, COLOR, ambient and tint.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
