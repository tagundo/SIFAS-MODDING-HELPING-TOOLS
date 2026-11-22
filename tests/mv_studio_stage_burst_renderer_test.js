"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");

global.window = global;
global.THREE = T;
global.requestAnimationFrame = () => 1;
global.cancelAnimationFrame = () => {};
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-stage-lens.js");
require("../webtools/web/static/mv-studio-stage-overlay.js");
require("../webtools/web/static/mv-studio-scene.js");

let uploaded = 0, released = 0, disposedGeometry = 0, disposedMaterials = 0;
T.TextureLoader = class {
  async loadAsync(url) {
    const png = Buffer.from(url.split(",")[1], "base64");
    const texture = new T.Texture({width: png.readUInt32BE(16), height: png.readUInt32BE(20)});
    uploaded++;
    texture.addEventListener("dispose", () => released++);
    return texture;
  }
};
function mipChain(size) {
  const levels = [];
  for (let side = size; side >= 1; side >>= 1) {
    const header = Buffer.alloc(24);
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
    header.writeUInt32BE(13, 8);
    header.write("IHDR", 12);
    header.writeUInt32BE(side, 16);
    header.writeUInt32BE(side, 20);
    levels.push({width: side, height: side, png: header.toString("base64")});
  }
  return levels;
}

const draws = [], initialized = [], sampled = [];
let renderer;
T.GLTFLoader = class {};
T.OrbitControls = class {
  constructor() { this.target = new T.Vector3(); }
  update() {}
  addEventListener() {}
  dispose() {}
};
T.WebGLRenderer = class {
  constructor() {
    renderer = this;
    this.domElement = {width: 320, height: 180, setAttribute() {}, remove() {}};
    this.shadowMap = {enabled: false};
    this.autoClear = true;
    this.size = new T.Vector2(320, 180);
  }
  setClearColor() {}
  getSize(output) { return output.copy(this.size); }
  setSize(width, height) {
    this.size.set(width, height);
    this.domElement.width = width;
    this.domElement.height = height;
  }
  getPixelRatio() { return this.ratio; }
  setPixelRatio(value) { this.ratio = value; }
  render(scene, camera) {
    if (scene.autoUpdate) scene.updateMatrixWorld();
    const items = [];
    scene.traverseVisible(node => {
      if (!node.geometry?.getAttribute("centerAndTile") || !camera.layers.test(node.layers)) return;
      items.push({node, name: node.name, order: node.renderOrder,
        center: [0, 1, 2, 3].map((_, component) => node.geometry.getAttribute("centerAndTile").array[component])});
    });
    items.sort((left, right) => left.order - right.order);
    draws.push({overlay: camera.isOrthographicCamera === true, autoClear: this.autoClear, items,
      camera: camera.position.toArray(), right: camera.right});
  }
  dispose() {}
};

const initialize = (row, seed) => {
  initialized.push([row.id, seed]);
  return row.id === "unsupported" ? null : {
    sample(elapsed, fps, emit) {
      sampled.push([row.id, elapsed, fps]);
      if (elapsed < (row.delay || 0)) return;
      emit(1, 0, 0, 0.75, 210, 220, 230, 192, row.layer === 20 ? 4 : 0);
    },
  };
};
global.MVStudioStageBurstSimulation = {create: initialize};
global.MVStudioStageLensSimulation = {create: initialize};
let fresh = 20;
global.MVStudioStageParticles.autoSeed = () => ++fresh;

const material = {queue: 3010, cull: 0, blend: "add", stencil: "always", stencilRef: 2,
  premultiply: false, saturate: false, tint: [1, 1, 1, 1]};
const stars = (id, x) => ({id, kind: "stationaryBurst", layer: 1, blend: "add", maxParticles: 5,
  maxViewportWidth: 3, tiles: [1, 1], texture: 0, position: [x, 2, 3], sortCenter: [x, 2, 3],
  rotation: [0, 0, 0, 1], scale: [1, 1, 1], autoSeed: true, seed: 0});
const kira = (id, z, delay) => ({id, kind: "stationaryBurst", layer: 20, blend: "alpha", maxParticles: 1,
  maxViewportWidth: .5, tiles: [4, 4], texture: 1, position: [-1.5, 202.6, z], sortCenter: [-1.5, 202.6, z],
  rotation: [0, 0, 1, 0], scale: [1, 1, 1], delay, autoSeed: false, seed: 8784});
const cue = (eventId, emitterIds) => ({trackId: "effects", eventId, emitterIds, quality: "stage_control"});
const event = (id, start) => ({id, start, duration: .5, values: {playableClass: "CustomControlClip",
  timeScale: 1, weight: 1, overwriteRandomSeed: false, offset: {x: 0, y: 0, z: 0}}});
const fixture = () => ({schema: 4, textures: [mipChain(64), mipChain(512)], material, tiles: [2, 1],
  maxViewportWidth: .5, sortMode: 0,
  emitters: [stars("star-01", 1), stars("star-06", 4), kira("kira-01", -2, 0), kira("kira-02", 1, .1)],
  cues: [cue("a", ["star-01", "star-06"]), cue("overlay", ["kira-01", "kira-02"]), cue("b", ["star-01", "star-06"])]});

async function run() {
  const app = MVStudioScene.create({clientWidth: 320, clientHeight: 180, appendChild() {}});
  const quality = {values: {stage_control: true, stage_overlay_effect: true, frame_rate_60fps: true}};
  const track = {id: "effects", nativeClass: "CustomControlTrack", events: [event("a", 1), event("overlay", 1), event("b", 2)]};
  const project = {tracks: [track], quality, stageLensFlare: fixture()};
  await app.load(project);
  assert.equal(uploaded, 17, "load once per unique atlas despite reused emitters");

  const render = time => {
    draws.length = 0;
    app.playbackFrame(time);
    return draws.slice();
  };
  let [world, overlay] = render(1);
  assert.equal(world.overlay, false);
  assert.equal(overlay.overlay, true, "layer 20 alone must schedule its pass");
  assert.deepEqual(overlay.camera, [0, 200, -10]);
  assert.equal(overlay.autoClear, false);
  assert.equal(overlay.right, 5 * 16 / 9);
  assert.equal(renderer.autoClear, true);
  assert.deepEqual(world.items.map(item => item.name).sort(), ["Native stage burst 1.1", "Native stage burst 1.2"]);
  assert.deepEqual(overlay.items.map(item => item.name), ["Native stage burst 2.1"]);
  assert.deepEqual(overlay.items[0].center, [-2.5, Math.fround(202.6), -2, 4]);
  assert.equal(overlay.items[0].node.material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(overlay.items[0].node.material.blendDstAlpha, T.OneMinusSrcAlphaFactor);
  assert.equal(overlay.items[0].node.material.depthTest, true);
  assert.equal(overlay.items[0].node.material.depthFunc, T.LessEqualDepth);
  assert.equal(overlay.items[0].node.material.depthWrite, false);
  assert.equal(world.items[0].node.material.blendDst, T.OneFactor);
  assert.equal(world.items[0].node.material.defines.NATIVE_VIEW_AXES, 1);

  [world, overlay] = render(1.15);
  assert.deepEqual(overlay.items.map(item => item.name), ["Native stage burst 2.2", "Native stage burst 2.1"]);
  assert.equal(world.items.length, 2);
  assert.deepEqual(initialized, [["star-01", 21], ["star-06", 22], ["kira-01", 8784], ["kira-02", 8784]]);
  for (const {node} of [...world.items, ...overlay.items]) {
    node.geometry.addEventListener("dispose", () => disposedGeometry++);
    node.material.addEventListener("dispose", () => disposedMaterials++);
  }

  assert.equal(render(1.5).at(-1).items.length, 0, "half-open native cue window");
  assert.equal(render(2)[0].items.length, 2);
  assert.deepEqual(initialized.slice(4), [["star-01", 23], ["star-06", 24]]);
  assert.equal(render(1)[0].items.length, 2);
  assert.equal(initialized.length, 6, "a seek must not reroll auto seeds");

  quality.values.frame_rate_60fps = false;
  draws.length = 0;
  app.seek(1.15, project);
  app.flushSeekDraw();
  assert.deepEqual(sampled.slice(-4).map(row => row[2]), [30, 30, 30, 30]);
  assert.equal(draws.at(-1).items.length, 2);
  assert.equal(initialized.length, 6, "changing cadence reuses the same seeds");
  quality.values.frame_rate_60fps = true;

  quality.values.stage_control = false;
  draws.length = 0;
  app.seek(1.15, project);
  app.flushSeekDraw();
  assert.deepEqual(draws.map(draw => draw.items.length), [0]);
  quality.values.stage_control = true;

  quality.values.stage_overlay_effect = false;
  draws.length = 0;
  app.seek(1.15, project);
  app.flushSeekDraw();
  assert.equal(draws.length, 1);
  assert.equal(draws[0].items.length, 2);
  quality.values.stage_overlay_effect = true;
  track.muted = true;
  draws.length = 0;
  app.seek(1.15, project);
  app.flushSeekDraw();
  assert.equal(draws.length, 1);
  assert.equal(draws[0].items.length, 0);
  track.muted = false;

  const edited = track.events[0];
  edited.start = .5;
  edited.values.offset = {x: 2, y: 1, z: 3};
  edited.values.overwriteRandomSeed = true;
  edited.values.particleRandomSeed = 99;
  [world] = render(.65);
  assert.equal(world.items.length, 2);
  assert.deepEqual(initialized.slice(-2), [["star-01", 99], ["star-06", 99]]);
  const moved = world.items.find((item) => item.name === "Native stage burst 1.1");
  assert.deepEqual(moved.center, [2, 2, 3, 0]);
  assert.deepEqual(moved.node.position.toArray(), [-2, 1, 3]);
  app.setCamera("orbit");
  assert.equal(render(1.15).length, 1, "overlay camera stays off in orbit");
  app.setCamera("live");

  const legacy = {schema: 3, textures: [mipChain(64)], material, tiles: [2, 1], maxViewportWidth: .5, sortMode: 0,
    emitters: [{id: "legacy", texture: 0, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1],
      sortCenter: [0, 0, 0], rate: 2, lifetime: 5, autoSeed: false, seed: 4}],
    cues: [{trackId: "effects", eventId: "legacy-event", emitterId: "legacy", quality: "stage_control"}]};
  await app.load({tracks: [{...track, events: [event("legacy-event", 1)]}], quality, stageLensFlare: legacy});
  assert.equal(disposedGeometry, 4);
  assert.equal(disposedMaterials, 4);
  assert.equal(render(1)[0].items[0].name, "Native stage lens flare 1");

  for (const ids of [["star-01"], ["star-01", "star-01"], ["star-01", "missing"], ["star-01", "kira-01"]]) {
    const broken = fixture();
    broken.cues[0] = cue("a", ids);
    assert.equal(await MVStudioStageLens.apply(T, new T.Scene(), broken), null);
  }

  const incomplete = fixture(), detached = new T.Scene(), unavailable = "unsupported";
  incomplete.emitters[1].id = unavailable;
  incomplete.cues = [cue("a", ["star-01", unavailable])];
  const controller = await MVStudioStageLens.apply(T, detached, incomplete);
  controller.update(.65, project);
  assert.equal(controller.sortEntries().length, 0, "an unsupported child must not leave a partially active prefab");
  controller.dispose();
  assert.equal(detached.children.length, 0);
  app.dispose();
  assert.equal(uploaded, released, "dispose every loaded texture and mip staging owner");
  console.log("Stage billboard groups: unique child ownership, both cameras, edit scopes, seed reuse, legacy and disposal.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
