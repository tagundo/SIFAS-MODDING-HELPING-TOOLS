"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");

function mip(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {png: header.toString("base64"), width: size, height: size};
}

const f32 = Math.fround, white = [255, 255, 255, 255];

function fixture(texture) {
  const shortAtlas = [[0, 0], [.04834102466702461, .2975870131876164], [.058341022580862045, 0],
    [.1, .29997000694155673], [.11, 0], [.21446533501148224, 0]];
  const sideAtlas = [[0, 0], [.05, .29997000694155673], [.06, 0], [.12, .29997000694155673],
    [.13, 0], [.3, .29997000694155673], [.31, 0], [.4, 0]];
  const center = [0, f32(3.08), -7], rightAngle = 1.570796251296997, halfTurn = Math.SQRT1_2;
  const emitter = (name, position, rotation, width, side = false) => {
    const base = side ? .5249999761581421 : 0, climb = side ? 1.5749999284744263 : 2.0999999046325684;
    const atlas = side ? sideAtlas : shortAtlas;
    return {name, position, rotation, size: [width, 1], duration: 50, lifetime: 4,
      particleRotation: side ? [0, rightAngle, rightAngle] : [rightAngle, 0, 0],
      speed: side ? -1 : 1, bursts: side ? [[0, 2], [1, 2]] : [[0, 1]],
      sizeCurve: ["cubic", [[0, [0, 0, climb, base]], [1, [0, 0, 0, 2.0999999046325684]]]],
      atlasCurve: ["cubic", atlas.map(([time, value]) => [f32(time), [0, 0, 0, value]])],
      atlasPeriod: f32(atlas.at(-1)[0]),
      color: {start: white, keys: side ? [[0, ...white]] : [[0, ...white],
        [f32(55705 / 65535), ...white], [f32(58982 / 65535), 255, 255, 255, 0], [1, 255, 255, 255, 0]]},
      maxViewportWidth: 2, sortBias: 0};
  };
  return {trackId: "display:light", eventId: "display:light:06", texture, emitters: [
    emitter("light_up", center, [-halfTurn, 0, 0, halfTurn], 4),
    emitter("light_down", center, [halfTurn, 0, 0, halfTurn], 4),
    emitter("light_left", center, [.5, -.5, -.5, .5], f32(4.7)),
    emitter("light_right", center, [-.5, .5, -.5, .5], f32(4.7)),
    emitter("light_R", [f32(5.4), f32(1.76), f32(-3.02)],
      [0, -.8660254406092593, 0, .49999993621753414], 3, true),
    emitter("light_L", [f32(-5.4), f32(1.76), f32(-3.02)],
      [0, -.8660253998985324, 0, -.5000000067305869], 3, true),
  ]};
}

function nearVector(actual, expected, tolerance = .00001) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < tolerance,
    `index ${index}: expected ${expected[index]}, received ${value}`));
}

function particle(mesh, i) {
  const geometry = mesh.geometry;
  assert.ok(i >= 0 && i < geometry.instanceCount);
  const [centerAndTile, size, color] = ["centerAndTile", "particleSize", "particleColor"].map(name => {
    const {array, itemSize} = geometry.getAttribute(name);
    return Array.from(array.subarray(i * itemSize, (i + 1) * itemSize));
  });
  const [x, y, z, tile] = centerAndTile;
  return {center: [x,y,z], tile, size, color};
}

function unclampedCorners(mesh, {center, size}) {
  const {uAxisX, uAxisY} = mesh.material.uniforms;
  const position = mesh.geometry.getAttribute("position"), origin = new T.Vector3().fromArray(center);
  return Array.from({length: position.count}, (_, i) => origin.clone()
    .addScaledVector(uAxisX.value, position.getX(i) * size[0])
    .addScaledVector(uAxisY.value, position.getY(i) * size[1]).toArray());
}

async function run() {
  const root = new T.Scene(), levels = Array.from({length: 10}, (_, i) => mip(512 >> i));
  const source = fixture(levels), loaded = [], disposed = [];
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
  assert.equal(await MVStudioDisplayLights.apply(local, root, {...source, texture: levels.slice(0, -1)}), null);
  assert.equal(await MVStudioDisplayLights.apply(local, root, {...source, emitters: source.emitters.slice(1)}), null);
  assert.equal(loaded.length, 0);
  assert.equal(root.children.length, 0);
  const display = await MVStudioDisplayLights.apply(local, root, source);
  assert.ok(display);
  assert.equal(root.children.length, 6);
  let geometries = 0, materials = 0;
  const meshes = root.children.slice(), byName = new Map();
  for (const [index, mesh] of meshes.entries()) {
    const row = source.emitters[index], {geometry, material} = mesh;
    assert.equal(mesh.name, `Native stage display ${row.name}`);
    byName.set(row.name, mesh);
    assert.equal(mesh.visible, false);
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.instanceCount, 0);
    assert.equal(geometry.groups.length, 0);
    assert.equal(geometry.getAttribute("position").count, 4);
    assert.deepEqual([...geometry.index.array], [0, 2, 1, 0, 3, 2]);
    assert.deepEqual([...geometry.getAttribute("uv").array], [0, 0, 1, 0, 1, 1, 0, 1]);
    for (const [name, width] of [["centerAndTile", 4], ["particleSize", 2], ["particleColor", 4]]) {
      const attribute = geometry.getAttribute(name);
      assert.equal(attribute.isInstancedBufferAttribute, true);
      assert.equal(attribute.itemSize, width);
      assert.equal(attribute.count, 5);
      assert.equal(attribute.normalized, name === "particleColor");
      assert.ok(attribute.array instanceof (attribute.normalized ? Uint8Array : Float32Array));
    }
    assert.equal(material.transparent, true);
    assert.equal(material.depthTest, true);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.depthWrite, false);
    assert.equal(material.side, T.DoubleSide);
    assert.equal(material.blending, T.CustomBlending);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneMinusSrcAlphaFactor);
    assert.equal(material.blendSrcAlpha, T.SrcAlphaFactor);
    assert.equal(material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
    assert.equal(material.stencilWrite, true);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilWriteMask, 255);
    assert.deepEqual([material.stencilFail, material.stencilZFail, material.stencilZPass], Array(3).fill(T.KeepStencilOp));
    assert.equal(material.uniforms.uMaxWidth.value, 2);
    assert.equal(material.uniforms.uTexture.value, loaded[0]);
    geometry.addEventListener("dispose", () => geometries++);
    material.addEventListener("dispose", () => materials++);
  }
  const levelSizes = levels.map(level => level.width);
  assert.equal(loaded[0].generateMipmaps, false);
  assert.equal(loaded[0].minFilter, T.LinearMipmapNearestFilter);
  assert.equal(loaded[0].magFilter, T.LinearFilter);
  assert.equal(loaded[0].wrapS, T.RepeatWrapping);
  assert.equal(loaded[0].wrapT, T.RepeatWrapping);
  assert.equal(loaded[0].flipY, false);
  assert.deepEqual(loaded[0].mipmaps.map(image => image.width), levelSizes);
  assert.deepEqual(disposed, levelSizes.slice(1));

  let start = 48.28333333333333;
  const event = {id: source.eventId, start, duration: 14.666666666666671,
    values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
      offset: {x: 0, y: 0, z: 0}}};
  const track = {id: source.trackId, nativeClass: "CustomControlTrack", events: [event]};
  const settings = {stage_display: true, stage_control: false, frame_rate_60fps: true};
  const project = {tracks: [track], quality: {values: settings}};
  function update(localTime, count) {
    display.update(start + localTime, project);
    const counts = Array.isArray(count) ? count : Array(6).fill(count);
    meshes.forEach(({geometry, visible}, index) => {
      const expected = counts[index];
      assert.equal(geometry.instanceCount, expected, `at cue age ${localTime}, emitter ${index}`);
      assert.equal(visible, expected > 0);
      if (expected) for (const name of ["centerAndTile", "particleSize", "particleColor"]) {
        const attribute = geometry.getAttribute(name);
        assert.equal(attribute.updateRange.count, expected * attribute.itemSize);
      }
    });
  }

  update(-.001, 0);
  update(0, 0);
  update(1 / 60, 1);
  update(60 / 60, 1);
  update(61 / 60, 2);
  settings.frame_rate_60fps = false;
  update(29 / 30, 1);
  update(30 / 30, 2);
  settings.frame_rate_60fps = true;

  const up = byName.get("light_up"), rightSide = byName.get("light_R");
  update(31 / 60, 1);
  // Stock Android ARM render probes at particle age .5, reflected in X.
  const rising = particle(up, 0), entering = particle(rightSide, 0);
  nearVector(rising.center, [0, 3.5799999237060547, -7]);
  nearVector(rising.size, [1.0499999523162842, .26249998807907104]);
  assert.deepEqual(rising.color, white);
  assert.equal(rising.tile, 0);
  nearVector(unclampedCorners(up, rising).flat(), [
    .524999976,3.448750019,-7, -.524999976,3.448750019,-7,
    -.524999976,3.711249828,-7, .524999976,3.711249828,-7,
  ]);
  nearVector(entering.center, [5.833012581, 1.75999999, -2.769999892]);
  nearVector(entering.size, [2.1656248569488525, .7218749523162842]);
  assert.deepEqual(entering.color, white);
  assert.equal(entering.tile, 1);
  nearVector(unclampedCorners(rightSide, entering).flat(), [
    5.520431519,2.842812538,-2.950468779, 5.520431519,.677187562,-2.950468779,
    6.145593643,.677187562,-2.589531183, 6.145593643,2.842812538,-2.589531183,
  ]);
  update(13 / 60, 1);
  assert.equal(particle(up, 0).tile, 1);
  update(65 / 60, 2);
  assert.deepEqual([particle(up, 0).tile, particle(up, 1).tile], [0, 1], "the atlas repeats by particle age");
  assert.ok(particle(up, 0).center[1] < particle(up, 1).center[1], "newest instances draw before the oldest");
  update(211 / 60, 4);
  assert.deepEqual(particle(up, 3).color, [255, 255, 255, 128]);
  update(217 / 60, 4);
  assert.deepEqual(particle(up, 3).color, [255, 255, 255, 2]);
  update(226 / 60, [3, 3, 3, 3, 4, 4]);
  assert.deepEqual(particle(rightSide, 3).color, white);
  update(31 / 60, 1);
  assert.deepEqual(particle(up, 0), rising);
  assert.deepEqual(particle(rightSide, 0), entering);

  const order = () => [...byName.keys()].sort((a, b) => byName.get(a).renderOrder - byName.get(b).renderOrder);
  const cameras = [new T.PerspectiveCamera(), new T.OrthographicCamera()];
  for (const camera of cameras) {
    camera.position.set(10, 10, 10);
    camera.lookAt(0, 1, -3);
    display.sort(camera);
    const [first, second] = camera.isOrthographicCamera ? ["light_left", "light_L"] : ["light_L", "light_left"];
    assert.deepEqual(order(), [first, second, "light_down", "light_up", "light_right", "light_R"]);
    assert.deepEqual(particle(up, 0), rising, "camera sort does not alter local particle geometry");
  }
  cameras[0].position.set(-10, -6, 10);
  display.sort(cameras[0]);
  assert.deepEqual(order(), ["light_right", "light_up", "light_R", "light_down", "light_left", "light_L"]);

  settings.stage_display = false;
  update(.5, 0);
  settings.stage_display = true;
  track.muted = true;
  update(.5, 0);
  track.muted = false;
  event.values.offset.x = 1;
  update(.5, 0);
  event.values.offset.x = 0;
  update(event.duration, 0);
  project.tracks[0] = {...track, events: [{...event, start: 19, duration: .8}]};
  display.invalidate();
  update(.5, 0);
  start = 19;
  update(31 / 60, 1);
  assert.deepEqual(particle(up, 0), rising);
  update(.8, 0);
  project.tracks[0].events[0].duration = 60;
  update(55, 0); // A longer Timeline event cannot extend the 50-second emitter.

  display.dispose();
  display.dispose();
  display.update(start + .5, project);
  assert.equal(root.children.length, 0);
  assert.equal(geometries, 6);
  assert.equal(materials, 6);
  assert.deepEqual(disposed, [...levelSizes.slice(1), 512]);
  console.log("Native display lights: six shared-atlas packets, native corners/cadence/color, masks, sorting, edits, and cleanup.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
