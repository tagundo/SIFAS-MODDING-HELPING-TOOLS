"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-speed-back.js");

function mip(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {png: header.toString("base64"), width: size, height: size};
}

function near(actual, expected) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-10,
    `index ${index}: expected ${expected[index]}, received ${value}`));
}

async function run() {
  const root = new T.Scene();
  const start = 77.05;
  const event = {id: "display:light:09", start, duration: 41.56666666666667,
    values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
      offset: {x: 0, y: 0, z: 0}}};
  const track = {id: "display:light", nativeClass: "CustomControlTrack", events: [event]};
  const settings = {stage_display: true, stage_control: false};
  const project = {tracks: [track], quality: {values: settings}};
  const levels = Array.from({length: 10}, (_, index) => mip(512 >> index));
  const descriptor = {
    trackId: track.id, eventId: event.id, duration: 50, lifetime: 60, texture: levels,
    matrix: new T.Matrix4().makeScale(2.5, 1.5, 0).setPosition(.05, 3.05, -6.75).toArray(),
    positions: [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 1], [1, 1, 1], [2, 1, 1]],
    uv: [[0, 0], [.5, 0], [1, 0], [0, 1], [.5, 1], [1, 1]],
    indices: [0, 1, 3, 1, 4, 3, 1, 2, 4, 2, 5, 4],
    rgb: [109, 117, 128], alpha: [0, 7, 15, 22, 30, 38],
    // Continue beyond the animation duration to make the controller's hold observable.
    uvCurves: [["linear", [[0, 2], [50, 1], [60, 0]]], ["constant", 1],
      ["linear", [[0, 0], [50, 1], [60, 2]]], ["linear", [[0, 0], [50, 150], [60, 180]]]],
  };
  const loaded = [], disposed = [];
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = levels[loaded.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const texture = new T.Texture({width: level.width, height: level.height});
      texture.addEventListener("dispose", () => disposed.push(level.width));
      loaded.push(texture);
      return texture;
    }
  }};

  const invalid = {...descriptor, texture: levels.slice(0, -1)};
  assert.equal(await MVStudioSpeedBack.apply(local, root, invalid), null);
  assert.equal(await MVStudioSpeedBack.apply(local, root, {...descriptor, alpha: [256, ...descriptor.alpha.slice(1)]}), null);
  assert.equal(loaded.length, 0);
  assert.equal(root.children.length, 0);
  const speedBack = await MVStudioSpeedBack.apply(local, root, descriptor);
  assert.ok(speedBack);
  assert.equal(root.children.length, 1);
  const [mesh] = root.children;
  assert.equal(mesh.visible, false);
  assert.equal(mesh.matrixAutoUpdate, false);
  assert.deepEqual(mesh.matrix.toArray(), descriptor.matrix);
  near(new T.Vector3(1, 1, 1).applyMatrix4(mesh.matrix).toArray(), [2.55, 4.55, -6.75]);
  assert.deepEqual([...mesh.geometry.getAttribute("position").array], descriptor.positions.flat());
  assert.deepEqual([...mesh.geometry.getAttribute("uv").array], descriptor.uv.flat());
  assert.deepEqual([...mesh.geometry.index.array], descriptor.indices);
  const opacity = mesh.geometry.getAttribute("vertexOpacity");
  assert.ok(opacity.array instanceof Uint8Array);
  assert.equal(opacity.normalized, true);
  assert.equal(opacity.itemSize, 1);
  assert.deepEqual([...opacity.array], descriptor.alpha);

  const material = mesh.material, uniforms = material.uniforms;
  assert.deepEqual(uniforms.uVertexColor.value.toArray(), descriptor.rgb.map(byte => byte / 255));
  assert.match(material.fragmentShader, /squareRGB \* squareRGB \+ texel\.rgb \* uVertexColor/);
  assert.match(material.fragmentShader, /texel\.a \* vOpacity/);
  assert.equal(mesh.renderOrder, 2900);
  assert.equal(material.side, T.DoubleSide);
  assert.equal(material.transparent, true);
  assert.equal(material.depthTest, true);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, false);
  assert.equal(material.blendSrc, T.SrcAlphaFactor);
  assert.equal(material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(material.stencilWrite, true);
  assert.equal(material.stencilFunc, T.EqualStencilFunc);
  assert.equal(material.stencilRef, 2);
  assert.equal(material.stencilFail, T.KeepStencilOp);
  assert.equal(material.stencilZFail, T.KeepStencilOp);
  assert.equal(material.stencilZPass, T.KeepStencilOp);
  const levelSizes = levels.map(level => level.width);
  assert.equal(uniforms.uTexture.value, loaded[0]);
  assert.equal(loaded[0].generateMipmaps, false);
  assert.equal(loaded[0].minFilter, T.LinearMipmapNearestFilter);
  assert.equal(loaded[0].flipY, false);
  assert.deepEqual(loaded[0].mipmaps.map(image => image.width), levelSizes);
  assert.deepEqual(disposed, levelSizes.slice(1));

  const textureST = () => uniforms.uTextureST.value.toArray();
  speedBack.update(start - .001, project);
  assert.equal(mesh.visible, false);
  speedBack.update(start, project);
  assert.equal(mesh.visible, false, "native burst has not run at tick zero");
  near(textureST(), [2, 1, 0, 0]);
  speedBack.update(start + 1 / 60, project);
  assert.equal(mesh.visible, false, "30 fps paints after both particle updates");
  speedBack.update(start + 1 / 30, project);
  assert.equal(mesh.visible, true, "the display effect is independent of stage_control");
  speedBack.update(start + 10.5, project);
  near(textureST(), [1.79, 1, .21, -31.5]);
  speedBack.update(start + event.duration, project);
  assert.equal(mesh.visible, false);

  event.duration = 75;
  speedBack.update(start + 55, project);
  assert.equal(mesh.visible, true, "an extended cue holds the completed Animator");
  near(textureST(), [1, 1, 1, -150]);
  speedBack.update(start + 59.999, project);
  assert.equal(mesh.visible, true);
  near(textureST(), [1, 1, 1, -150]);
  speedBack.update(start + 60, project);
  assert.equal(mesh.visible, true, "native particle is still live on its last frame");
  speedBack.update(start + 60 + 1 / 30, project);
  assert.equal(mesh.visible, false, "the particle expires on the next rendered frame");
  speedBack.update(start + 10.5, project);
  assert.equal(mesh.visible, true);
  near(textureST(), [1.79, 1, .21, -31.5]);

  settings.stage_display = false;
  speedBack.update(start + 1, project);
  assert.equal(mesh.visible, false);
  settings.stage_display = true;
  track.muted = true;
  speedBack.update(start + 1, project);
  assert.equal(mesh.visible, false);
  track.muted = false;
  event.values.offset.x = 1;
  speedBack.update(start + 1, project);
  assert.equal(mesh.visible, false, "a non-neutral clip is unsupported");
  track.events[0] = {...event, start: 15, values: {...event.values, offset: {x: 0, y: 0, z: 0}}};
  speedBack.invalidate();
  speedBack.update(14.999, project);
  assert.equal(mesh.visible, false);
  speedBack.update(25.5, project);
  assert.equal(mesh.visible, true);
  near(textureST(), [1.79, 1, .21, -31.5]);

  let materials = 0, geometries = 0;
  material.addEventListener("dispose", () => materials++);
  mesh.geometry.addEventListener("dispose", () => geometries++);
  speedBack.dispose();
  speedBack.dispose();
  speedBack.update(25.5, project);
  assert.equal(materials, 1);
  assert.equal(geometries, 1);
  assert.equal(root.children.length, 0);
  assert.deepEqual(disposed, [...levelSizes.slice(1), 512]);
  console.log("Native speed background: packed vertex color, mask, authored mips, UV scroll/hold, particle lifetime, and cleanup.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
