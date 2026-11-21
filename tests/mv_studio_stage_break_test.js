"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-break-simulation.js");
require("../webtools/web/static/mv-studio-speed-back.js");
require("../webtools/web/static/mv-studio-stage-break.js");

const f32 = Math.fround, start = 77.05, position = [0, f32(3.05), -7];
const white = [255, 255, 255, 255], mauve = [95, 71, 75, 255];
const constant = value => ["constant", value];
const step = keys => ["cubic", keys.map(([time, value]) => [f32(time), [0, 0, 0, value]])];
const color = (start, keys) => ({start, keys: keys.map(([time, alpha]) => [f32(time), 255, 255, 255, alpha])});

function mip(size) {
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12);
  png.writeUInt32BE(size, 16);
  png.writeUInt32BE(size, 20);
  return {png: png.toString("base64"), width: size, height: size};
}

function fixture(levels) {
  const positions = [], uv = [], indices = [];
  // Synthetic 7x7 patch with the exact first source vertex for the native mesh check.
  for (let y = 0; y < 7; y++) for (let x = 0; x < 7; x++) {
    const i = y * 7 + x;
    positions.push([(x - 3) / 8, (y - 3) / 8, 0]);
    uv.push([1 - x / 6, 1 - y / 6]);
    if (x < 6 && y < 6) indices.push(i, i + 7, i + 1, i + 1, i + 7, i + 8);
  }
  positions[0] = [-.35817041993141174, -.35817041993141174, 0];
  uv[0] = [.999026894569397, 1];
  const mesh = {positions, uv, indices, vertexColors: null, position, scale: [11, 6, 1], lifetime: f32(.6), delay: 0,
    sortBias: 0, color: color(mauve, [[0, 255], [1, 255]]), atlasCurve: ["cubic", [
      [.25, [1.4127095305917058e-7, -1.5892982219156693e-7, 1.3332000176072114, 0]],
      [1, [0, 0, 0, f32(.9999)]],
    ]]};
  const spinRange = [f32(-12.56637), f32(12.56637)], delay = .25, seed = 10354082;
  const atlas = (tiles, row, frame, start = [0, 0]) => ({tiles, row, frame, start, period: 0});
  const emitters = [
    {name: "Fall", position, seed, delay, lifetime: 1, count: 60, size: [.5, 1],
      rollRange: [f32(-1.04719758), f32(1.04719758)], speedRange: [30, 10], gravity: 2, spinRange,
      shape: {type: 4, scale: [1, 1, 1], radius: f32(.1), angle: 45, arc: 360, arcMode: 3},
      clamp: {limit: 1, dampen: f32(.1)}, sortBias: -1, maxViewportWidth: 2, texture: 2,
      atlas: atlas([4, 4], null, constant(0), [.75, f32(.9999)]),
      color: color(mauve, [[0, 255], [.5000076293945312, 255], [1, 0]])},
    {name: "light_big", position: [0, f32(3.05), f32(-6.53)], seed: 0, delay: 0, lifetime: 1, count: 8,
      size: [3, .75, f32(.1)], rollRange: [f32(6.283185), f32(-6.283185)], spinMultiplier: f32(13.962634),
      shape: {type: 5, scale: [8, 5, 1], radius: 1, angle: 25, arc: 360, arcMode: 0},
      spinCurves: [step([[0, 0], [.25, -1]]), step([[0, 0], [.25, 1]])], velocityCurves: [
        step([[0, 0], [1, 0]]), ["cubic", [[0, [-4.470348358154297e-8, 6.705522537231445e-8,
          -1.2000000178813934, -.30000000447034836]], [1, [0, 0, 0, -1.5]]]], step([[.25, 0], [.3, 25]]),
      ], sortBias: 0, maxViewportWidth: 2, texture: 1,
      atlas: atlas([1, 4], null, step([[0, .7018528087845226], [.1, f32(.9999)], [.11, .7018528087845226],
        [.1556786745786667, .7018528087845226], [.16567866504192352, f32(.9999)],
        [.17567867040634155, .7018528087845226], [.38, f32(.9999)]])),
      color: color(white, [[0, 255], [.4, 255], [.6, 0], [.7499961853027344, 0], [1, 0]])},
    {name: "flash", position, seed, delay, lifetime: .75, count: 1, size: [150, 150, 150], rollRange: [0, 0], spinRange,
      sortBias: 2, maxViewportWidth: 4, texture: 2, atlas: atlas([4, 4], 0, constant(f32(.9999))),
      color: color([217, 230, 255, 242], [[0, 0], [.2500038146972656, 255], [.4, 255], [1, 0]])},
  ];
  return {trackId: "break", eventId: "08", mesh, emitters, textures: [levels, "displayLights", "speedBackCenterStars"]};
}

function control(id, start, duration) {
  return {id, start, duration, values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
    offset: {x: 0, y: 0, z: 0}}};
}

function near(actual, expected, tolerance = .00001) {
  assert.equal(actual.length, expected.length);
  assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) < tolerance), `${actual} differs from ${expected}`);
}

function particles(mesh, name) {
  const {array, itemSize} = mesh.geometry.getAttribute(name);
  return Array.from({length: mesh.geometry.instanceCount}, (_, index) =>
    [...array.subarray(itemSize * index, itemSize * (index + 1))]);
}

function verifyFallCamera(mesh) {
  // Android and iOS ARM view-billboard probe with a tilted camera, 45°
  // particle roll and an unclamped 0.5 m square. Unity looks along +Z.
  const nativeCamera = new T.Matrix4().makeRotationX(Math.PI / 7).setPosition(-3, 8, -4);
  const camera = new T.Matrix4().makeScale(-1, 1, 1).multiply(nativeCamera).scale(new T.Vector3(1, 1, -1));
  const basis = new T.Matrix3().setFromMatrix4(camera), center = new T.Vector3().fromArray(position);
  const corners = mesh.geometry.getAttribute("position");
  const points = Array.from({length: corners.count}, (_, i) => {
    const offset = new T.Vector2(-.5 * corners.getX(i), .5 * corners.getY(i));
    offset.rotateAround(new T.Vector2(), -Math.PI / 4);
    return new T.Vector3(offset.x, offset.y, 0).applyMatrix3(basis).add(center).toArray();
  }).flat();
  near(points, [0, 3.368540525, -6.846599102, -.353553385, 3.049999952, -7,
    0, 2.731459379, -7.153400898, .353553385, 3.049999952, -7]);
  assert.match(mesh.material.vertexShader, /#ifdef VIEW_ALIGNED\s+local\.x = -local\.x;/);
  assert.match(mesh.material.vertexShader, /#ifdef VIEW_ALIGNED\s+angle = -angle;/);
}

function nativeSimulation(source) {
  const sim = MVStudioBreakSimulation, [fall, light, flash] = source.emitters.map(row => sim.create(row));
  assert.ok(fall && light && flash);
  const sample = (emitter, age, fps = 60) => {
    const live = [];
    emitter.sample(age, fps, (...fields) => live.push(fields));
    return live;
  };
  assert.deepEqual([fall, light, flash].map(emitter => sample(emitter, 0).length), [0, 0, 0]);
  assert.deepEqual([fall, light, flash].map(emitter => sample(emitter, 15 / 60).length), [0, 8, 0]);
  const fracture = sample(fall, 16 / 60), flare = sample(flash, 16 / 60), stroke = sample(light, 1 / 60);
  assert.deepEqual([fracture.length, flare.length, stroke.length], [60, 1, 8]);
  // Original Android tick traces, including BurstSpread, delayed emission and native Color32 atlas seed.
  near(fracture[0].slice(0, 8), [-.04435155168175697, 3.049999952316284, -6.999999523162842,
    .9945150017738342, .9945150017738342, .052749235183000565, 1.6666655255903606e-8, .9913555979728699]);
  near(stroke[0].slice(0, 6), [-.6731171607971191, 3.470412015914917, -6.356393337249756, 3, .75, -1.8834056854248047]);
  near(flare[0].slice(0, 6), [0, 3.049999952316284, -7, 150, 150, -1.6168445426956168e-7]);
  const next = sample(fall, 17 / 60);
  near(next[0].slice(0, 7), [-.17924050986766815, 3.044816255569458, -6.695862770080566,
    .9945150017738342, .9945150017738342, -.10893534123897552, .0166666841506958]);
  assert.deepEqual(sample(fall, 8 / 30, 30), fracture);
  assert.deepEqual(sample(fall, 16 / 60), fracture);
  assert.equal(sim.meshPhase(0, 60, f32(.6), 0), null);
  near([sim.meshPhase(16 / 60, 60, f32(.6), 0)], [.4166667556762695]);
  assert.equal(sim.meshPhase(38 / 60, 60, f32(.6), 0), null);
}

async function run() {
  const root = new T.Scene(), levels = Array.from({length: 10}, (_, i) => mip(512 >> i));
  const source = fixture(levels), loaded = [], textureDisposals = [];
  nativeSimulation(source);
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = levels[loaded.length % levels.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const texture = new T.Texture({width: level.width, height: level.height});
      texture.addEventListener("dispose", () => textureDisposals.push(texture));
      loaded.push(texture);
      return texture;
    }
  }};
  const borrowed = {displayLights: new T.Texture(), speedBackCenterStars: new T.Texture()};
  let borrowedDisposals = 0;
  for (const texture of Object.values(borrowed)) texture.addEventListener("dispose", () => borrowedDisposals++);
  assert.equal(await MVStudioStageBreak.apply(local, root, {...source, emitters: source.emitters.slice(1)}, borrowed), null);
  assert.equal(loaded.length, 0);
  const fracture = await MVStudioStageBreak.apply(local, root, source, borrowed);
  assert.ok(fracture);
  assert.equal(root.children.length, 4);
  assert.equal(loaded.length, 10);
  const [mesh, fall, light, flash] = root.children;
  assert.equal(mesh.geometry.isInstancedBufferGeometry, undefined);
  assert.equal(mesh.geometry.getAttribute("position").count, 49);
  assert.equal(mesh.geometry.index.count, 216);
  assert.deepEqual(mesh.scale.toArray(), [11, 6, 1]);
  near(new T.Vector3().fromBufferAttribute(mesh.geometry.getAttribute("position"), 0).applyMatrix4(mesh.matrix).toArray(),
    [-3.939874619245529, .9009774327278137, -7]);
  const sprites = [fall, light, flash], counts = [60, 8, 1];
  for (const [index, sprite] of sprites.entries()) {
    const {material, geometry} = sprite;
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.groups.length, 0);
    assert.equal(geometry.getAttribute("centerAndTile").count, counts[index]);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.ok(geometry.getAttribute("particleColor").array instanceof Uint8Array);
    assert.equal(Boolean(material.defines.VIEW_ALIGNED), sprite === fall);
    assert.equal(material.defines.PARTICLE_ROLL, 1);
    assert.equal(material.uniforms.uTexture.value, sprite === light ? borrowed.displayLights : borrowed.speedBackCenterStars);
  }
  verifyFallCamera(fall);
  assert.deepEqual(sprites.map(sprite => sprite.material.uniforms.uAtlasColumns.value), [4, 1, 4]);
  assert.deepEqual(sprites.map(sprite => sprite.material.uniforms.uMaxWidth.value), [2, 2, 4]);
  assert.equal(mesh.material.uniforms.uTexture.value, loaded[0]);
  assert.deepEqual(loaded[0].mipmaps.map(level => level.width), levels.map(level => level.width));
  for (const child of root.children) {
    const {material} = child;
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, child === flash ? T.OneFactor : T.OneMinusSrcAlphaFactor);
    assert.equal(material.depthWrite, false);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilWriteMask, 255);
  }

  const background = await MVStudioSpeedBack.apply(local, root, {trackId: "background", eventId: "09",
    duration: 50, lifetime: 60, texture: levels, matrix: new T.Matrix4().setPosition(0, f32(3.05), -9).toArray(),
    positions: [[-1, 0, 0], [0, 1, 0], [1, 0, 0]], uv: [[0, 0], [.5, 1], [1, 0]], indices: [0, 1, 2],
    rgb: [109, 117, 128], alpha: [0, 38, 0], uvCurves: [constant(1), constant(1), constant(0), constant(0)]});
  assert.ok(background);
  const backgroundMesh = root.children.at(-1);
  const event = control("08", start, 2.5);
  const track = {id: "break", nativeClass: "CustomControlTrack", events: [event]};
  const project = {tracks: [track, {id: "background", nativeClass: "CustomControlTrack", events: [control("09", start, 41.5)]}],
    quality: {values: {stage_display: true, stage_control: false, frame_rate_60fps: true}}};
  const camera = new T.PerspectiveCamera(), state = () => [mesh.visible, ...sprites.map(sprite => sprite.geometry.instanceCount)];
  let offset = start;
  function update(age) {
    background.update(offset + age, project);
    fracture.update(offset + age, project);
    return fracture.sort(camera, background.displaySortEntries);
  }
  assert.equal(update(0), false);
  assert.deepEqual(state(), [false, 0, 0, 0]);
  update(1 / 60);
  assert.deepEqual(state(), [true, 0, 8, 0]);
  assert.deepEqual(mesh.material.uniforms.uUV.value.toArray(), [.5, .25, 0, 0]);
  near(mesh.material.uniforms.uColor.value.toArray(), mauve.map(byte => byte / 255));
  update(15 / 60);
  assert.deepEqual(state(), [true, 0, 8, 0]);
  update(16 / 60);
  assert.deepEqual(state(), [true, 60, 8, 0], "delayed flash exists in simulation with zero visible alpha at birth");
  assert.deepEqual(mesh.material.uniforms.uUV.value.toArray(), [.5, .25, .5, 0]);
  const fallCenters = particles(fall, "centerAndTile");
  const nativeIndex = fallCenters.findIndex(([x]) => Math.abs(x + .04435155168175697) < .00001);
  assert.ok(nativeIndex >= 0);
  assert.equal(fallCenters[nativeIndex][3], 15);
  assert.deepEqual(particles(fall, "particleColor")[nativeIndex], mauve);
  update(17 / 60);
  assert.deepEqual(state(), [true, 60, 8, 1]);
  assert.equal(particles(flash, "centerAndTile")[0][3], 3);
  assert.deepEqual(particles(flash, "particleColor")[0].slice(0, 3), [217, 230, 255]);
  assert.equal(fall.geometry.getAttribute("centerAndTile").updateRange.count, 240);
  const order = () => [mesh, ...sprites, backgroundMesh].sort((a, b) => a.renderOrder - b.renderOrder);
  assert.deepEqual(order(), [backgroundMesh, flash, mesh, fall, light]);
  const frontFall = particles(fall, "centerAndTile");
  camera.position.set(0, f32(3.05), -20);
  camera.lookAt(...position);
  fracture.sort(camera, background.displaySortEntries);
  assert.deepEqual(order(), [light, backgroundMesh, flash, mesh, fall]);
  const backFall = particles(fall, "centerAndTile");
  assert.notDeepEqual(backFall, frontFall);
  assert.deepEqual(backFall.sort(), frontFall.sort(), "a second camera changes depth order while preserving the same sprites");
  camera.position.set(0, 0, 0);
  camera.quaternion.identity();
  project.quality.values.frame_rate_60fps = false;
  update(8 / 30);
  assert.deepEqual(particles(fall, "centerAndTile"), fallCenters);

  project.quality.values.stage_display = false;
  assert.equal(update(.5), false);
  assert.deepEqual(state(), [false, 0, 0, 0]);
  project.quality.values.stage_display = true;
  track.muted = true;
  assert.equal(update(.5), false);
  assert.deepEqual(background.displaySortEntries().map(entry => entry.mesh), [backgroundMesh]);
  track.muted = false;
  update(16 / 60);
  assert.deepEqual(particles(fall, "centerAndTile"), fallCenters);
  project.tracks[0] = {...track, events: [{...event, start: 15, duration: .2}]};
  fracture.invalidate();
  assert.equal(update(.1), false);
  offset = 15;
  assert.equal(update(.1), true);
  assert.deepEqual(state(), [true, 0, 8, 0]);
  assert.equal(update(.2), false);
  assert.deepEqual(state(), [false, 0, 0, 0]);

  let geometries = 0, materials = 0;
  for (const child of [mesh, ...sprites]) {
    child.geometry.addEventListener("dispose", () => geometries++);
    child.material.addEventListener("dispose", () => materials++);
  }
  fracture.dispose();
  fracture.dispose();
  assert.equal(fracture.sort(camera, background.displaySortEntries), false);
  assert.equal(geometries, 4);
  assert.equal(materials, 4);
  assert.deepEqual(root.children, [backgroundMesh]);
  assert.equal(textureDisposals.filter(texture => texture === loaded[0]).length, 1);
  assert.equal(textureDisposals.filter(texture => texture === loaded[10]).length, 0);
  assert.equal(borrowedDisposals, 0);
  background.dispose();
  assert.equal(root.children.length, 0);
  for (const texture of Object.values(borrowed)) texture.dispose();
  assert.equal(borrowedDisposals, 2);
  console.log("Native stage break: delayed tick traces, atlas and Color32, borrowed textures, camera cohort, edits, and cleanup.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
