"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-ribbon-shine.js");

function mip(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {png: header.toString("base64"), width: size, height: size};
}

function fixture(name, start, lifetime) {
  const event = {id: `${name}:cue`, start, duration: 4,
    values: {playableClass: "CustomControlClip", timeScale: 1, weight: 1, clipIn: 0,
      offset: {x: 0, y: 0, z: 0}}};
  const track = {id: `${name}:track`, nativeClass: "CustomControlTrack", events: [event]};
  const cue = {trackId: track.id, eventId: event.id, rate: 10, cycle: 5, maxViewportWidth: .5,
    position: [1, 2, -1], parent: {position: [3, 4, 5], rotation: [0, 0, 0, 1], scale: [2, .5, 3]},
    box: [2, 4, 6], shapeYaw: 0, lifetime: [lifetime, lifetime], size: [.25, .25], speed: [.5, .5],
    sizeCurves: [["constant", 1], ["constant", 1]]};
  return {cue, event, track};
}

function particles(mesh, count) {
  const geometry = mesh.geometry;
  assert.equal(geometry.instanceCount, count);
  const position = geometry.getAttribute("particlePosition"), size = geometry.getAttribute("particleSize");
  assert.equal(position.count, count + 1);
  assert.equal(size.count, count + 1);
  assert.deepEqual([...size.array.subarray(0, count)], Array(count).fill(.25));
  return [...position.array.subarray(0, count * 3)];
}

async function run() {
  const root = new T.Scene();
  const first = fixture("first", 5, 13), second = fixture("second", 7, 10);
  const project = {tracks: [first.track, second.track], quality: {values: {stage_display: true}}};
  const texture = Array.from({length: 9}, (_, index) => mip(256 >> index));
  const descriptor = {texture, cues: [first.cue, second.cue]};
  const loaded = [], released = [];
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = texture[loaded.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const item = new T.Texture({width: level.width, height: level.height});
      item.addEventListener("dispose", () => released.push(level.width));
      loaded.push(item);
      return item;
    }
  }};

  const invalid = {...descriptor, texture: texture.slice(0, -1)};
  assert.equal(await MVStudioRibbonShine.apply(local, root, invalid), null);
  assert.equal(loaded.length, 0, "an incomplete authored chain must fail before an image request");

  const crypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const seeds = [2914, 1];
  Object.defineProperty(globalThis, "crypto", {configurable: true, value: {
    getRandomValues(words) {
      assert.ok(seeds.length, "each cue chooses its seed once");
      words[0] = seeds.shift();
      return words;
    }
  }});
  let controller;
  try {
    controller = await MVStudioRibbonShine.apply(local, root, descriptor);
  } finally {
    if (crypto) Object.defineProperty(globalThis, "crypto", crypto);
    else delete globalThis.crypto;
  }
  assert.ok(controller);
  assert.deepEqual(seeds, []);
  assert.equal(root.children.length, 2, "each cue has one draw rather than individual particle meshes");
  const [a, b] = root.children;
  const levelSizes = texture.map(level => level.width);
  assert.deepEqual(released, levelSizes.slice(1));
  for (const mesh of [a, b]) {
    assert.equal(mesh.geometry.isInstancedBufferGeometry, true);
    assert.equal(mesh.geometry.getAttribute("position").count, 4);
    assert.deepEqual([...mesh.geometry.index.array], [0, 2, 1, 0, 3, 2]);
    assert.deepEqual(mesh.position.toArray(), [5, 5, 2]);
    assert.equal(mesh.geometry.instanceCount, 0);
    assert.equal(mesh.visible, false);
    assert.equal(mesh.renderOrder, 2900);
    const material = mesh.material;
    assert.equal(material.stencilWrite, true);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilFail, T.KeepStencilOp);
    assert.equal(material.stencilZFail, T.KeepStencilOp);
    assert.equal(material.stencilZPass, T.KeepStencilOp);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneFactor);
    assert.equal(material.depthWrite, false);
    assert.equal(material.uniforms.uMaxViewportWidth.value, .5);
    assert.equal(material.uniforms.uTexture.value, loaded[0]);
  }
  assert.equal(loaded[0].generateMipmaps, false);
  assert.equal(loaded[0].minFilter, T.LinearMipmapNearestFilter);
  assert.deepEqual(loaded[0].mipmaps.map(image => image.width), levelSizes);

  controller.update(4.999, project);
  assert.deepEqual([a.visible, b.visible], [false, false]);
  controller.update(5, project);
  assert.deepEqual([a.visible, b.visible], [true, false]);
  const birth = particles(a, 130);
  controller.update(5.0625, project);
  const beforeSecondCue = particles(a, 130);
  assert.equal(birth[0], beforeSecondCue[0]);
  assert.equal(birth[1], beforeSecondCue[1]);
  assert.ok(Math.abs(beforeSecondCue[2] - birth[2] - .03125) < 1e-6);
  controller.update(7, project);
  assert.deepEqual([a.visible, b.visible], [true, true]);
  particles(a, 130);
  const secondBirth = particles(b, 100);
  assert.notDeepEqual(secondBirth.slice(0, 3), birth.slice(0, 3));
  first.track.muted = true;
  controller.update(7, project);
  assert.deepEqual([a.visible, b.visible], [false, true]);
  first.track.muted = false;
  project.quality.values.stage_display = false;
  controller.update(7, project);
  assert.deepEqual([a.visible, b.visible], [false, false]);
  project.quality.values.stage_display = true;
  controller.update(9, project);
  assert.deepEqual([a.visible, b.visible], [false, true]);
  particles(b, 100);
  controller.update(11, project);
  assert.deepEqual([a.visible, b.visible], [false, false]);
  controller.update(5.0625, project);
  assert.deepEqual([a.visible, b.visible], [true, false]);
  assert.deepEqual(particles(a, 130), beforeSecondCue, "rewind recreates the exact same prewarmed history");
  controller.update(7, project);
  assert.deepEqual(particles(b, 100), secondBirth);

  let geometries = 0, materials = 0;
  for (const mesh of [a, b]) {
    mesh.geometry.addEventListener("dispose", () => geometries++);
    mesh.material.addEventListener("dispose", () => materials++);
  }
  controller.dispose();
  controller.dispose();
  controller.update(7, project);
  assert.equal(root.children.length, 0);
  assert.equal(geometries, 2);
  assert.equal(materials, 2);
  assert.deepEqual(released, [...levelSizes.slice(1), 256]);
  console.log("Aion ribbon shine: grouped 130/100-particle histories, independent cues and rewind, authored mips, stencil, and cleanup.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
