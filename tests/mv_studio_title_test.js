"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");

const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/dtoAAAAASUVORK5CYII=";
const constant = value => ["constant", value];
const animation = (x, slope, end) => ["cubic", [
  [-3.4028234663852886e38, [0, 0, 0, x]],
  [0, [0, 0, slope, x]],
  [5.333333492279053, [0, 0, 0, end]]
]];
const windowStart = 5.833333333333333;
const windowLength = 5.333333333333333;
const track = { id: "title:track", nativeClass: "CustomControlTrack", events: [{
  id: "title:event", start: windowStart, duration: windowLength, values: { playableClass: "CustomControlClip",
    clipIn: 0, timeScale: 1, weight: 1, offset: { x: 0, y: 0, z: 0 }
  }
}] };
const descriptor = {
  textures: [{ png, width: 1, height: 1 }],
  geometry: {
    positions: [[.5, -.5, 0], [-.5, .5, 0], [-.5, -.5, 0], [.5, .5, 0]],
    uv: [[0, 1], [1, 0], [1, 1], [0, 0]], indices: [0, 2, 1, 1, 3, 0]
  },
  cues: [{
    trackId: track.id, eventId: track.events[0].id, texture: 0,
    material: { tint: [1, 1, 1, 1], uv: [1, 1, 0, 0], queue: 2900 },
    meshes: [
      { path: 123, name: "title_R", position: [6.5, 1.75, -2.4], rotation: [0, -.9659258, 0, -.258819], scale: [7, 8, 1] },
      { path: 456, name: "title_L", position: [-6.5, 1.75, -2.4], rotation: [0, -.9659258, 0, .258819], scale: [7, 8, 1] }
    ],
    animation: { start: 0, duration: 5.333333492279053, loop: false, channels: [
      { kind: "overlayUV", path: 123, curves: [constant(1), constant(.25),
        animation(-.16619427502155304, .09375, .33380573987960815), constant(.75)] },
      { kind: "overlayUV", path: 456, curves: [constant(1), constant(.25),
        animation(.16619427502155304, -.09375, -.33380573987960815), constant(.75)] }
    ] }
  }]
};

function compare(current, expected) {
  current.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-12,
    `index ${index}: expected ${expected[index]}, found ${value}`));
}

async function run() {
  const root = new T.Scene(), project = { tracks: [track], quality: { values: { stage_display: true } } };
  let texture, calls = 0, imagesDisposed = 0;
  const testThree = { ...T, TextureLoader: class {
    async loadAsync(url) {
      assert.equal(url, "data:image/png;base64," + png);
      calls++;
      texture = new T.Texture({ width: 1, height: 1 });
      texture.addEventListener("dispose", () => imagesDisposed++);
      return texture;
    }
  } };
  const wrong = structuredClone(descriptor);
  wrong.textures[0].width = 2;
  assert.equal(await MVStudioTitle.apply(testThree, root, wrong), null);
  assert.equal(calls, 0, "IHDR must be checked before decoding");
  wrong.textures[0].width = 1;
  wrong.cues[0].animation.channels[1].path = 123;
  assert.equal(await MVStudioTitle.apply(testThree, root, wrong), null);
  assert.equal(calls, 0);

  const title = await MVStudioTitle.apply(testThree, root, descriptor);
  assert.ok(title);
  assert.equal(calls, 1);
  const [group] = root.children;
  const [right, left] = group.children;
  assert.equal(group.visible, false);
  assert.deepEqual(right.position.toArray(), [6.5, 1.75, -2.4]);
  assert.equal(right.geometry, left.geometry);
  assert.notEqual(right.material, left.material);
  assert.equal(right.layers.mask, 1);
  assert.equal(right.material.stencilWrite, true);
  assert.equal(right.material.stencilFunc, T.EqualStencilFunc);
  assert.equal(right.material.stencilRef, 2);
  assert.equal(right.material.stencilFuncMask, 255);
  assert.equal(right.material.stencilWriteMask, 255);
  assert.equal(right.material.stencilFail, T.KeepStencilOp);
  assert.equal(right.material.stencilZFail, T.KeepStencilOp);
  assert.equal(right.material.stencilZPass, T.KeepStencilOp);
  assert.equal(right.material.depthTest, true);
  assert.equal(right.material.depthWrite, false);
  assert.equal(right.material.depthFunc, T.LessEqualDepth);
  assert.equal(right.material.side, T.DoubleSide);
  assert.equal(right.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(right.material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(right.renderOrder, 2900);
  assert.equal(texture.encoding, T.LinearEncoding);
  assert.equal(texture.minFilter, T.LinearMipmapNearestFilter);
  assert.equal(texture.magFilter, T.LinearFilter);
  assert.equal(texture.wrapS, T.RepeatWrapping);
  assert.equal(texture.wrapT, T.RepeatWrapping);
  assert.equal(texture.flipY, false);

  title.update(windowStart - 1e-6, project);
  assert.equal(group.visible, false);
  title.update(windowStart, project);
  assert.equal(group.visible, true);
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.16619427502155304, 0]);
  title.update(windowStart + 1, project);
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);
  compare(left.material.uniforms.uTextureST.value.toArray(), [1, .25, .07244427502155304, 0]);
  title.update(windowStart + windowLength, project);
  assert.equal(group.visible, false);
  title.update(windowStart + 1, project);
  assert.equal(group.visible, true, "random access after end");
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);

  project.quality.values.stage_display = false;
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  project.quality.values.stage_display = true;
  track.muted = true;
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  track.muted = false;
  track.events[0].values.offset.x = 1;
  title.update(windowStart, project);
  assert.equal(group.visible, false, "non-neutral control offset");
  track.events[0] = { ...track.events[0], start: 15, values: { ...track.events[0].values, offset: { x: 0, y: 0, z: 0 } } };
  title.invalidate();
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  title.update(16, project);
  assert.equal(group.visible, true, "timeline event timing stays editable");
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);

  let materials = 0, geometries = 0;
  right.material.addEventListener("dispose", () => materials++);
  left.material.addEventListener("dispose", () => materials++);
  right.geometry.addEventListener("dispose", () => geometries++);
  title.dispose();
  title.dispose();
  assert.equal(imagesDisposed, 1);
  assert.equal(materials, 2);
  assert.equal(geometries, 1);
  assert.equal(root.children.length, 0);
  console.log("Native stage title: bounded texture and quad, stencil reader, authored UV motion, timeline edits and scene cleanup.");
}

async function runParticles() {
  const root = new T.Scene(), source = structuredClone(descriptor);
  const particleTrack = { id: "main:track", nativeClass: "CustomControlTrack", events: [{
    id: "main:event", start: 20, duration: 4, values: { playableClass: "CustomControlClip", clipIn: 0,
      timeScale: 1, weight: 1, offset: { x: 0, y: 0, z: 0 } }
  }] };
  const emitter = { ...source.cues[0].meshes[0], name: "title_main", texture: 0,
    material: { ...source.cues[0].material, tint: [.5, 1, 1, 1] },
    size: [4.65, 2.25], lifetime: 2, active: [0, 1.5], atlas: { tiles: [1, 4], row: 0, frame: constant(0) },
    sizeCurves: [constant(1), ["linear", [[0, 1], [1, 2]]]],
    color: { rgb: [[0, 1, 1, 1]], alpha: [[0, 1], [.5, .5], [1, 0]] }
  };
  const vanish = { ...emitter, name: "title_vanish", active: [1.5, null],
    atlas: { tiles: [2, 4], row: null, frame: ["linear", [[0, 0], [1, 1]]] } };
  const unsupported = { ...emitter, name: "unsupported", atlas: { ...emitter.atlas, row: 4 } };
  source.particles = [
    { trackId: particleTrack.id, eventId: particleTrack.events[0].id, emitters: [emitter, vanish] },
    { trackId: particleTrack.id, eventId: particleTrack.events[0].id, emitters: [unsupported] }
  ];
  const project = { tracks: [track, particleTrack], quality: { values: { stage_display: true } } };
  let loads = 0;
  const local = { ...T, TextureLoader: class {
    async loadAsync() {
      loads++;
      return new T.Texture({ width: 1, height: 1 });
    }
  } };
  const title = await MVStudioTitle.apply(local, root, source);
  assert.ok(title);
  assert.equal(loads, 1, "mesh titles and particles share their texture");
  assert.equal(root.children.length, 2, "an unsupported optional emitter leaves valid groups intact");
  const [quads, group] = root.children;
  const [mesh, second] = group.children;
  assert.equal(mesh.geometry, quads.children[0].geometry);
  assert.equal(mesh.material.name, "Native stage title particle");
  assert.equal(mesh.material.stencilFunc, T.EqualStencilFunc);
  assert.equal(mesh.material.stencilRef, 2);
  assert.equal(mesh.renderOrder, 2900);

  title.update(19.99, project);
  assert.equal(group.visible, false);
  title.update(20.5, project);
  assert.equal(group.visible, true);
  assert.equal(mesh.visible, true);
  assert.equal(second.visible, false);
  compare(mesh.scale.toArray(), [7 * 4.65, 8 * 2.25 * 1.25, 1]);
  compare(mesh.material.uniforms.uTint.value.toArray(), [.5, 1, 1, .75]);
  compare(mesh.material.uniforms.uTextureST.value.toArray(), [1, .25, 0, 0]);

  title.update(21.5, project);
  assert.equal(mesh.visible, false);
  assert.equal(second.visible, true);
  compare(second.material.uniforms.uTextureST.value.toArray(), [.5, .25, 0, 0]);
  title.update(22.8, project);
  compare(second.material.uniforms.uTextureST.value.toArray(), [.5, .25, .5, .5]);
  title.update(23.5, project);
  assert.equal(second.visible, false);
  title.update(24, project);
  assert.equal(group.visible, false);
  title.update(20.5, project);
  assert.equal(mesh.visible, true, "rewind reconstructs deterministic life and gradient");
  compare(mesh.material.uniforms.uTint.value.toArray(), [.5, 1, 1, .75]);
  particleTrack.muted = true;
  title.update(20.5, project);
  assert.equal(group.visible, false);

  let disposed = 0;
  mesh.material.addEventListener("dispose", () => disposed++);
  second.material.addEventListener("dispose", () => disposed++);
  title.dispose();
  assert.equal(disposed, 2);
  assert.equal(root.children.length, 0);
  console.log("Native title particles: fixed bursts, atlas rows and whole sheets, size/color, scrub and shared cleanup.");
}

run().then(runParticles).catch(error => { console.error(error); process.exitCode = 1; });
