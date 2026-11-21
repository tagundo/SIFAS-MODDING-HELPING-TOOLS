"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-spotlight-area.js");

const layer = new T.Scene();
layer.userData.mvSpotlightArea = {
  prefabPathId: "-3988590574941623676",
  geometry: { position: 0, uv: 1, index: 2 }, textures: [3, 4, 5],
  translation: [0, .01, 0], rotation: [Math.SQRT1_2, 0, 0, Math.SQRT1_2],
  scale: [1.8, 1.8, 1.8], uv: [1, 1, 0, 0], queue: 3000,
};
const inputs = [
  new T.Float32BufferAttribute([.5,-.5,0, -.5,.5,0, -.5,-.5,0, .5,.5,0], 3),
  new T.Float32BufferAttribute([0,1,1,0,1,1,0,0], 2), new T.Uint16BufferAttribute([0,2,1,1,3,0], 1),
  ...[4,2,1].map(size => new T.Texture({ width: size, height: size }))
];
const event = { start: 1, duration: 1, values: {
  playableClass: "LiveMemberSpotLightAreaClip", colorSpecifiedType: 1, memberPosition: 7,
  easeIn: .5, color: { r: .5, g: .75, b: 1, a: 1 }
}};
const project = { performers: [{ position: 7, themeColor: [.5, 1, .5, .5] }] };

async function run() {
  const parser = { async getDependency(kind,index) {
    assert.equal(kind, index < 3 ? "accessor" : "texture");
    return inputs[index];
  } };
  const template = await MVStudioSpotlightArea.prepare(T,{scene:layer,parser});
  assert.ok(template);
  assert.equal(template.texture.encoding,T.LinearEncoding);
  assert.equal(template.texture.minFilter,T.LinearMipmapNearestFilter);
  assert.equal(template.texture.magFilter,T.LinearFilter);
  assert.deepEqual(template.texture.mipmaps.map(image => image.width),[4,2,1]);
  assert.equal(template.texture.generateMipmaps,false);
  assert.notEqual(template.texture,inputs[3]);
  const invalid = new T.Scene();
  invalid.userData.mvSpotlightArea = { ...layer.userData.mvSpotlightArea, textures:[3,5] };
  assert.equal(await MVStudioSpotlightArea.prepare(T,{scene:invalid,parser}),null);

  const a = new T.Group(), move = new T.Group(), otherMove = new T.Group();
  a.add(move,otherMove);
  a.position.set(1,2,3);
  move.position.set(4,5,6);
  const area = MVStudioSpotlightArea.create(T,template,move);
  const other = MVStudioSpotlightArea.create(T,template,otherMove);
  const [mesh] = move.children, [otherMesh] = otherMove.children;
  assert.equal(mesh.parent,move);
  assert.equal(mesh.geometry,otherMesh.geometry);
  assert.equal(mesh.material.uniforms.uTexture.value,otherMesh.material.uniforms.uTexture.value);
  assert.notEqual(mesh.material,otherMesh.material);
  assert.equal(mesh.material.blendSrc,T.SrcAlphaFactor);
  assert.equal(mesh.material.blendDst,T.OneFactor);
  assert.equal(mesh.material.depthTest,true);
  assert.equal(mesh.material.depthFunc,T.LessEqualDepth);
  assert.equal(mesh.material.depthWrite,false);
  assert.equal(mesh.material.stencilWrite,false);
  assert.equal(mesh.material.side,T.DoubleSide);
  assert.equal(mesh.layers.mask,1);
  assert.equal(mesh.renderOrder,3000);
  assert.deepEqual(mesh.getWorldPosition(new T.Vector3()).toArray(),[5,7.01,9]);

  area.frame([event],.9,project);
  assert.equal(mesh.visible,false);
  area.frame([event],1.25,project);
  assert.equal(mesh.visible,true);
  assert.equal(otherMesh.visible,false);
  const tint = mesh.material.uniforms.uTint.value;
  assert.deepEqual(tint.toArray(),[.125,.375,.25,.25]);
  area.frame([event],1.250001,project);
  assert.deepEqual(tint.toArray(),[.125,.375,.25,.25],"sub-threshold native tint stays cached");
  area.reset();
  area.frame([event],1.250001,project);
  assert.ok(tint.w>.25);
  area.frame([event],1.5,project);
  assert.deepEqual(tint.toArray(),[.25,.75,.5,.5]);
  area.frame(null,1.5,project);
  assert.equal(mesh.visible,false);
  area.frame([event],1.5,project);
  assert.equal(mesh.visible,true);
  area.frame([event],2,project);
  assert.equal(mesh.visible,false);

  let geometryFreed = 0, textureFreed = 0, materialFreed = 0;
  template.geometry.addEventListener("dispose",() => geometryFreed++);
  template.texture.addEventListener("dispose",() => textureFreed++);
  mesh.material.addEventListener("dispose",() => materialFreed++);
  area.dispose();
  assert.equal(move.children.length,0);
  assert.equal(otherMove.children[0],otherMesh);
  assert.equal(materialFreed,1);
  assert.equal(geometryFreed,0);
  assert.equal(textureFreed,0);
  other.dispose();
  template.dispose();
  assert.equal(geometryFreed,1);
  assert.equal(textureFreed,1);
  console.log("Native spotlight areas: authored mip chain, Move attachment, blend/depth, weight, cached color, seek and ownership.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
