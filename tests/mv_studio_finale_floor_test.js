"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-finale-floor-simulation.js");
require("../webtools/web/static/mv-studio-finale-floor.js");

const f32 = Math.fround, start = 114.5, planeScale = f32(Math.SQRT1_2), alias = "speedBackCenterStars";

function fixture(reference = alias) {
  return {seed: 0, rate: 150, cycle: 5, lifetime: .5, size: [f32(.3), 20, 1], speedRange: [15, 25],
    box: [20, 0, 1], palette: {rgb: [[16384, 255, 255, 255], [32768, 179, 204, 255], [49151, 255, 185, 179],
      [55705, 128, 170, 255], [65535, 179, 255, 216]], alpha: [[0, 255], [65535, 255]]},
    colorKeys: [[0, 0], [f32(5243 / 65535), 0], [f32(7864 / 65535), 255], [f32(42598 / 65535), 255], [1, 0]]
      .map(([time, alpha]) => [time, 255, 255, 255, alpha]),
    uv: [.25, .25, .75, 0], capacity: 1000, position: [0, f32(.01), f32(-10.09)], maxViewportWidth: 2,
    trackId: "floor", eventId: "flo", textures: [reference]};
}

function timeline(source) {
  const event = {id: source.eventId, start, duration: 4.11666666666666, values: {playableClass: "CustomControlClip",
    clipIn: 0, timeScale: 1, weight: 1, offset: {x: 0, y: 0, z: 0}}};
  const track = {id: source.trackId, nativeClass: "CustomControlTrack", events: [event]};
  const settings = {stage_control: true, stage_display: false, frame_rate_60fps: true};
  return {event, track, settings, project: {stageFinaleFloor: source, tracks: [track], quality: {values: settings}}};
}

function near(actual, expected, tolerance = .00001) {
  assert.equal(actual.length, expected.length);
  assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) < tolerance), `${actual} differs from ${expected}`);
}

function mip(size) {
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12);
  png.writeUInt32BE(size, 16);
  png.writeUInt32BE(size, 20);
  return {png: png.toString("base64"), width: size, height: size};
}

function verifySimulation(source) {
  const sim = MVStudioFinaleFloorSimulation.create(source);
  assert.ok(sim);
  assert.equal(MVStudioFinaleFloorSimulation.create({...source, rate: 151}), null);
  const sample = (age, fps = 60) => {
    const packets = [];
    sim.sample(age, fps, (...fields) => packets.push(fields));
    return packets;
  };
  assert.deepEqual(sample(0), []);
  const third = sample(3 / 60), fourth = sample(4 / 60);
  assert.deepEqual([third.length, fourth.length], [7, 10]);
  assert.deepEqual(third.filter(row => row[10] > 0).map(row => row.slice(7)), [[255, 255, 255, 42]]);
  assert.deepEqual(fourth.filter(row => row[10] > 0).map(row => row.slice(7)),
    [[255, 185, 179, 169], [255, 255, 255, 255], [255, 185, 179, 84]]);
  // Original ARM slot zero at tick four, after reflection into viewer space.
  near(fourth[0].slice(0, 7), [-1.6827929019927979, .009999999776482582, -8.678420066833496,
    23.212017059326172, .03200000524520874, 2.133333444595337, .1066666767001152]);
  assert.deepEqual(sample(2 / 30, 30), fourth);
  assert.deepEqual(sample(3 / 60, 30), sample(2 / 60));
  sample(3.8, 30);
  assert.deepEqual(sample(4 / 60), fourth, "rewind restores the native slot order after a checkpoint");
}

function firstSprite(mesh) {
  const geometry = mesh.geometry;
  const center = new T.Vector3().fromBufferAttribute(geometry.getAttribute("centerAndTile"), 0);
  center.applyMatrix4(mesh.matrix);
  return {position: center.toArray(), size: [...geometry.getAttribute("particleSize").array.slice(0, 2)],
    rgba: [...geometry.getAttribute("particleColor").array.slice(0, 4)]};
}

async function verifyController(source) {
  const root = new T.Scene(), atlas = new T.Texture();
  let materials = 0, geometries = 0, borrowedDisposals = 0;
  atlas.addEventListener("dispose", () => borrowedDisposals++);
  assert.equal(await MVStudioFinaleFloor.apply(T, root, source, {}), null);
  assert.equal(root.children.length, 0);
  const controller = await MVStudioFinaleFloor.apply(T, root, source, {[alias]: atlas});
  assert.ok(controller);
  assert.equal(root.children.length, 1);
  const [mesh] = root.children, {geometry, material} = mesh;
  material.addEventListener("dispose", () => materials++);
  geometry.addEventListener("dispose", () => geometries++);
  assert.equal(mesh.renderOrder, 3000);
  assert.equal(mesh.frustumCulled, false);
  assert.equal(geometry.isInstancedBufferGeometry, true);
  assert.equal(geometry.getAttribute("centerAndTile").count, 78);
  assert.equal(geometry.getAttribute("particleColor").normalized, true);
  assert.ok(geometry.getAttribute("particleColor").array instanceof Uint8Array);
  assert.equal(material.uniforms.uTexture.value, atlas);
  assert.deepEqual(material.uniforms.uAtlas.value.toArray(), [.25, .25, .75, 0]);
  assert.equal(Boolean(material.defines.VIEW_ALIGNED), false);
  assert.equal(material.uniforms.uMaxWidth.value, 2 * planeScale);
  near(material.uniforms.uAxisX.value.toArray(), [1, 0, 0]);
  near(material.uniforms.uAxisY.value.toArray(), [0, 0, 1]);
  assert.equal(material.stencilFunc, T.AlwaysStencilFunc);
  assert.equal(material.stencilWriteMask, 255);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, false);
  assert.equal(material.blendSrc, T.SrcAlphaFactor);
  assert.equal(material.blendDst, T.OneFactor);

  const {event, track, settings, project} = timeline(source);
  let origin = event.start;
  function update(age, count) {
    controller.update(origin + age, project);
    assert.equal(mesh.visible, count > 0);
    assert.equal(geometry.instanceCount, count);
  }
  update(0, 0);
  update(2 / 60, 0);
  update(3 / 60, 1);
  near(firstSprite(mesh).position, [-5.955872535705566, .009999999776482582, -9.216980934143066]);
  assert.deepEqual(firstSprite(mesh).rgba, [255, 255, 255, 42]);
  update(4 / 60, 3);
  const original = firstSprite(mesh), centers = geometry.getAttribute("centerAndTile");
  near(original.position, [-1.6827929019927979, .009999999776482582, -8.678420066833496]);
  near(original.size, [.03200000524520874 * planeScale, 2.133333444595337 * planeScale]);
  assert.deepEqual(original.rgba, [255, 185, 179, 169]);
  assert.equal(centers.getW(0), 0);
  assert.equal(centers.updateRange.count, 12);
  // Paired native Horizontal writer at tick 4 with a .25 m raw size cap.
  const camera = new T.OrthographicCamera(-.0625, .0625, .0625, -.0625, .1, 100);
  const {uAxisX, uAxisY, uMaxWidth} = material.uniforms;
  const limit = 2 * uMaxWidth.value / camera.projectionMatrix.elements[0];
  const clip = Math.min(1, limit / Math.max(...original.size));
  const corner = geometry.getAttribute("position"), center = new T.Vector3().fromArray(original.position);
  const plane = Array.from({length: corner.count}, (_, i) => center.clone()
    .addScaledVector(uAxisX.value, corner.getX(i) * original.size[0] * clip)
    .addScaledVector(uAxisY.value, corner.getY(i) * original.size[1] * clip).toArray());
  near(plane.flat(), [-1.681467056, .01, -8.590031624, -1.684118748, .01, -8.590031624,
    -1.684118748, .01, -8.766808510, -1.681467056, .01, -8.766808510]);
  const version = centers.version;
  event.values.offset = {x: 1.25, y: .5, z: -2};
  update(4 / 60, 3);
  near(firstSprite(mesh).position, [original.position[0] - 1.25, original.position[1] + .5, original.position[2] - 2]);
  assert.equal(centers.version, version, "editing a cue offset moves its packet without re-evaluating the same frame");
  event.values.offset = {x: 0, y: 0, z: 0};

  settings.frame_rate_60fps = false;
  update(3 / 60, 0);
  update(2 / 30, 3);
  assert.deepEqual(firstSprite(mesh), original);
  settings.stage_control = false;
  settings.stage_display = true;
  update(2 / 30, 0);
  settings.stage_control = true;
  track.muted = true;
  update(2 / 30, 0);
  track.muted = false;
  update(event.duration, 0);
  project.tracks[0] = {...track, events: [{...event, start: 13, duration: .08}]};
  controller.invalidate();
  update(2 / 30, 0);
  origin = 13;
  update(2 / 30, 3);
  assert.deepEqual(firstSprite(mesh), original);
  update(.08, 0);

  controller.dispose();
  controller.dispose();
  assert.equal(root.children.length, 0);
  assert.deepEqual([materials, geometries, borrowedDisposals], [1, 1, 0]);
  atlas.dispose();
  assert.equal(borrowedDisposals, 1);
}

async function verifyEmbedded() {
  const root = new T.Scene(), levels = Array.from({length: 10}, (_, i) => mip(512 >> i));
  const loaded = [], released = [];
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = levels[loaded.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const texture = new T.Texture({width: level.width, height: level.height});
      texture.addEventListener("dispose", () => released.push(level.width));
      loaded.push(texture);
      return texture;
    }
  }};
  assert.equal(await MVStudioFinaleFloor.apply(local, root, fixture(levels.slice(1))), null);
  const controller = await MVStudioFinaleFloor.apply(local, root, fixture(levels));
  assert.ok(controller);
  const texture = root.children[0].material.uniforms.uTexture.value;
  assert.equal(texture, loaded[0]);
  assert.equal(texture.generateMipmaps, false);
  assert.equal(texture.minFilter, T.LinearMipmapNearestFilter);
  assert.equal(texture.flipY, false);
  assert.deepEqual(texture.mipmaps.map(image => image.width), levels.map(level => level.width));
  assert.deepEqual(released, levels.slice(1).map(level => level.width));
  controller.dispose();
  assert.deepEqual(released, [...levels.slice(1).map(level => level.width), 512]);
  assert.equal(root.children.length, 0);
}

async function verifySceneWire(source) {
  const atlas = new T.Texture(), name = "Native stage finale floor";
  let world, releases = 0;
  const local = {...T, GLTFLoader: class {}, OrbitControls: class {
    target = new T.Vector3();
    addEventListener() {}
    update() {}
    dispose() {}
  }, WebGLRenderer: class {
    domElement = {setAttribute() {}, remove() {}, width: 640, height: 360};
    shadowMap = {};
    size = new T.Vector2();
    setClearColor() {}
    getSize(target) { return target.copy(this.size); }
    setSize(width, height) { this.size.set(width, height); }
    getPixelRatio() { return this.ratio; }
    setPixelRatio(value) { this.ratio = value; }
    render(scene) { world = scene; }
    dispose() {}
  }};
  const window = {THREE: local, MVStudioFinaleFloor, MVStudioSpeedBack: {async apply(_three, _root, value) {
    if (!value) return null;
    return {centerTexture: atlas, invalidate() {}, update() {}, sort() {}, dispose() {
      assert.equal(world.getObjectByName(name), undefined, "the borrowing floor releases before its atlas owner");
      releases++;
      atlas.dispose();
    }};
  }}};
  const scene = fs.readFileSync(require.resolve("../webtools/web/static/mv-studio-scene.js"), "utf8");
  vm.runInNewContext(scene, {window, AbortController});
  const app = window.MVStudioScene.create({clientWidth: 640, clientHeight: 360, appendChild() {}}, {});
  const {project} = timeline(source);
  project.stageSpeedBack = {};
  await app.load(project);
  app.seek(start + 4 / 60, project);
  const mesh = world.getObjectByName(name);
  assert.ok(mesh);
  assert.equal(mesh.geometry.instanceCount, 3);
  assert.equal(mesh.material.uniforms.uTexture.value, atlas);
  await app.load({tracks: []});
  assert.equal(world.getObjectByName(name), undefined);
  assert.equal(releases, 1);
  app.dispose();
}

async function run() {
  const source = fixture();
  verifySimulation(source);
  await verifyController(source);
  await verifyEmbedded();
  await verifySceneWire(source);
  console.log("Native finale floor: scene wiring, horizontal geometry, exact tick colors, atlas ownership, and seek gates.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
