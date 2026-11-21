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

run().catch(error => { console.error(error); process.exitCode = 1; });
