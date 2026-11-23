"use strict";

// MVStudioAssetDump helpers the Max 3D runtime comparison relies on: runtime-built renderers
// (member spotlight shaft/area) are their own renderer owners, and an editor shader reports the
// space of its uTextureST from the way its vertex shader applies it.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-asset-dump.js");
const fs = require("node:fs");
const path = require("node:path");

const D = global.MVStudioAssetDump;

function shader(vertexShader) {
  return new T.ShaderMaterial({ vertexShader, fragmentShader: "void main() {}", uniforms: { uTextureST: { value: new T.Vector4(1, 1, 0, 0) } } });
}

// Unity-space values: the shader flips V itself (stage overlay, prop light) or flips the glTF UV first (flash light).
assert.equal(D.textureSTSpace(shader("void main() { vTexture = uv * uTextureST.xy + vec2(uTextureST.z, 1.0 - uTextureST.y - uTextureST.w); }")), "unity");
assert.equal(D.textureSTSpace(shader("void main() { vec2 sourceUV = vec2(uv.x, 1.0 - uv.y) * uTextureST.xy + uTextureST.zw; }")), "unity");
// glTF-space values: applied to the glTF UV directly (spotlight area, title, display).
assert.equal(D.textureSTSpace(shader("void main() {\n  vArea = uv * uTextureST.xy + uTextureST.zw;\n}")), "gltf");
assert.equal(D.textureSTSpace(shader("void main() { vX = uTextureST.xy; }")), null);
assert.equal(D.textureSTSpace(new T.ShaderMaterial({ vertexShader: "void main() {}", uniforms: {} })), null);
// The statements the editor's own shader modules use.
for (const [file, space] of [["mv-studio-stage-overlay.js", "unity"], ["mv-studio-prop-light.js", "unity"], ["mv-studio-stage-flash.js", "unity"],
  ["mv-studio-spotlight-area.js", "gltf"], ["mv-studio-stage-display.js", "gltf"], ["mv-studio-title.js", "gltf"]]) {
  const text = fs.readFileSync(path.join(__dirname, "../webtools/web/static", file), "utf8");
  const line = text.split("\n").find((row) => /uTextureST\.(?:xy|y)/.test(row) && !/uniform/.test(row));
  assert.ok(line, file);
  assert.equal(D.textureSTSpace(shader(line.replace(/^[\s"']+|[\s"',]+$/g, ""))), space, file);
}
const flash = D.materialProperties(shader("void main() { vec2 sourceUV = vec2(uv.x, 1.0 - uv.y) * uTextureST.xy + uTextureST.zw; }"));
assert.equal(flash.kind, "shader");
assert.equal(flash.textureSTSpace, "unity");

// A runtime-built mesh below a named glTF node is its own renderer, not grouped under that node.
const root = new T.Group(), move = new T.Group();
root.userData.name = "Character";
move.userData.name = "Move";
root.add(move);
const glbMesh = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial());
move.add(glbMesh);
const area = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial());
area.userData.mvGameObjectName = "fx_spo_are_01";
move.add(area);
const shaft = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial());
shaft.userData.mvGameObjectPath = "fx_spo_sha_01/root/spotlight_01";
root.add(shaft);
const owners = D.renderersOf(root);
assert.deepEqual(owners.get(move), [glbMesh], "a glTF primitive still belongs to its named node");
assert.deepEqual(owners.get(area), [area]);
assert.deepEqual(owners.get(shaft), [shaft]);
assert.equal(D.runtimeObject(area), true);
assert.equal(D.runtimeObject(glbMesh), false);

console.log("MV asset dump: runtime renderer owners and uTextureST spaces of the editor shaders.");
