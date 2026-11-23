"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");

// General/Opaque with _VERTEX_COLOR_ON on a mesh that has no COLOR stream
// (12036 laserLight, 12038 LaserBox, 12025 laserLight): Unity reads opaque white.
async function run() {
  const root = new T.Group(), texture = new T.Texture();
  const surface = (meta) => {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map: texture}));
    node.geometry.userData.mvStageMaterial = {shader: "general", colors: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]},
      uvTransform: [1, 1, 0, 0], cull: 2, vertexColor: true, ...meta};
    root.add(node);
    return node;
  };
  const absent = surface({vertexColorAbsent: true});
  const unknown = surface({});
  const original = unknown.material;
  const colored = surface({});
  colored.geometry.setAttribute("_stage_color", new T.Float32BufferAttribute(new Array(16).fill(.5), 4));
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => texture});
  assert.ok(controller);
  assert.equal(absent.material.isShaderMaterial, true, "an absent COLOR stream keeps the native shader");
  assert.equal(absent.material.defines.VERTEX_COLOR, 1);
  assert.deepEqual(absent.material.defaultAttributeValues._stage_color, [1, 1, 1, 1]);
  assert.equal(unknown.material, original, "an unreadable COLOR stream is still not guessed");
  assert.equal(colored.material.isShaderMaterial, true);
  assert.equal(colored.material.defaultAttributeValues._stage_color, undefined, "authored colors are used as is");
  controller.dispose();
  console.log("Stage materials: a missing COLOR stream reads opaque white.");
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
