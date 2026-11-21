"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");

// The loader stands in for the browser's PNG decoder. It gives the same
// per-level image sizes so the controller can build the authored mip chain.
T.TextureLoader = class {
  async loadAsync(url) {
    const header = Buffer.from(url.split(",")[1], "base64");
    return new T.Texture({width: header.readUInt32BE(16), height: header.readUInt32BE(20)});
  }
};

function level(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {width: size, height: size, png: header.toString("base64")};
}

async function test() {
  const root = new T.Group();
  const shape = {positions: [[-1,0,1],[1,0,1],[1,0,-1]], uv: [[0,0],[1,0],[1,1]], indices: [0,1,2]};
  const native = {geometry: shape, texture: 0, position: [0,.01,0], rotation: [0,0,0,1], scale: [1,1,1],
    birth: .05, lifetime: 1, size: .75, sizeCurve: ["constant", 1], yaw: .5, yawSpeed: -.25,
    color: {rgb: [[0,1,1,1]], alpha: [[0,.6]]}, uvOffset: [["constant", .25], ["constant", .5]],
    material: {queue: 3010, cull: 0, blend: "add", tint: [1,1,1,1], uv: [.5,.25,.125,.25], premultiply: true}};
  const orbit = {...native, texture: 1, position: [2, .05, 0], orbitY: Math.PI / 2,
    color: {rgba8: {start: [189, 255, 128, 77], keys: [[0, 200, 100, 255, 20], [1, 90, 254, 0, 100]]}},
    material: {...native.material, premultiply: false}};
  const descriptor = {textures: [Array.from({length:10}, (_, index) => level(512 >> index)),
    Array.from({length:9}, (_, index) => level(256 >> index))],
    templates: [[native, orbit]], cues: [{trackId: "track", eventId: "first", template: 0},
      {trackId: "track", eventId: "second", template: 0}]};
  const controller = await MVStudioStageParticles.apply(T, root, descriptor);
  assert(controller);
  const [first, second] = root.children;
  assert.equal(first.children[0].geometry, second.children[0].geometry);
  const event = {id: "first", start: 42.85, duration: 1.6, values: {
    playableClass: "CustomControlClip", clipIn: 6.4833, timeScale: 1, weight: 1, offset: {x: -.3,y:0,z:1.2},
  }};
  const track = {id:"track", events: [event, {...event,id:"second",start:46}]};
  const project = {tracks: [track], quality: {values:{stage_control:true}}};
  controller.update(event.start, project);
  assert.equal(first.visible, true);
  assert.equal(first.children[0].visible, false);
  controller.update(43.15, project);
  const mesh = first.children[0], uniforms = mesh.material.uniforms;
  assert.equal(mesh.visible, true);
  assert.equal(second.visible, false);
  assert.deepEqual(first.position.toArray(), [.3,0,1.2]);
  assert.deepEqual(mesh.position.toArray(), [0,.01,0]);
  assert.deepEqual(mesh.scale.toArray(), [.75,.75,.75]);
  assert.deepEqual(uniforms.uTextureST.value.toArray(), [.5,.25,.25,.375]);
  assert.deepEqual(uniforms.uTint.value.toArray(), [1,1,1,.6]);
  assert.equal(uniforms.uTexture.value.mipmaps.length, 10);
  assert.equal(uniforms.uTexture.value.generateMipmaps, false);
  assert.equal(mesh.material.defines.SOURCE_ALPHA, 1);
  assert.equal(mesh.material.blendDst, T.OneFactor);
  assert.equal(mesh.material.depthWrite, false);
  const orbitMesh = first.children[1], angle = (43.15 - event.start - orbit.birth) * orbit.orbitY;
  assert(Math.abs(orbitMesh.position.x - 2 * Math.cos(angle)) < 1e-9);
  assert(Math.abs(orbitMesh.position.z + 2 * Math.sin(angle)) < 1e-9);
  assert.equal(orbitMesh.position.y, .05);
  assert.equal(orbitMesh.material.uniforms.uTexture.value.mipmaps.length, 9);
  assert.deepEqual(orbitMesh.material.uniforms.uTint.value.toArray(), [128,138,96,12].map(byte => byte / 255));
  assert.deepEqual(orbitMesh.material.defines, {});
  controller.update(46.17, project);
  assert.equal(first.visible, false);
  assert.equal(second.visible, true);
  controller.update(43.15, project);
  assert.equal(first.visible, true);
  assert(Math.abs(orbitMesh.position.x - 2 * Math.cos(angle)) < 1e-9);
  project.quality.values.stage_control = false;
  controller.update(43.15, project);
  assert.equal(first.visible, false);
  project.quality.values.stage_control = true;
  track.muted = true;
  controller.update(43.15, project);
  assert.equal(first.visible, false);
  controller.dispose();
  assert.equal(root.children.length, 0);
  console.log("Native stage particles preserve activation age, world offsets, separate cues, UV offsets and original mips.");
}
test().catch(error => {console.error(error); process.exitCode = 1;});
