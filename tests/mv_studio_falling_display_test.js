"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-falling-simulation.js");
require("../webtools/web/static/mv-studio-falling-display.js");

const white = [255, 255, 255, 255], identity = [0, 0, 0, 1];
const firstStart = 11.166666666666666, secondStart = 62.95;
const constant = value => ["constant", value];

function controlEvent(id, start, duration) {
  return {id, start, duration, values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
    offset: {x: 0, y: 0, z: 0}}};
}

function sourceFixture() {
  const emitters = [["light_big", 6, -7], ["light_smole", 6, -5], ["light_smole_R", 6, -10],
    ["light_smole_L", 6, -3], ["stars", 2.5748562812805176, -9]].map(([name, y, z]) => {
    const stars = name === "stars";
    return {name, position: [0, y, z], rotation: identity, lifetime: stars ? 5 : 8, maxViewportWidth: 2,
      sortBias: name.startsWith("light_smole") ? 1 : 0, texture: Number(stars), colorKeys: [[0, ...white]]};
  });
  const lightAtlasPeriod = .17567867040634155;
  const cue = (variant, tint, resting, pulse) => ({trackId: "lights", eventId: variant, lightAtlasPeriod,
    starPalette: {rgb: [[32768, ...tint], [65535, 255, 255, 255]], alpha: [[0, 255], [65535, 255]]},
    lightAtlasCurve: ["cubic", [[0, [0, 0, 0, resting]], [.1, [0, 0, 0, pulse]],
      [.11, [0, 0, 0, resting]], [lightAtlasPeriod, [0, 0, 0, resting]]]]});
  return {emitters, textures: ["displayLights", "speedBackCenterStars"], cues: [
    cue("05", [128, 170, 255], 0, .29997000694155673), cue("07", [255, 128, 128], .7018528087845226, .9998999834060669),
  ]};
}

async function makeTitle(root) {
  const pose = (name, position) => ({name, position, rotation: identity, scale: [1, 1, 1]});
  const material = {queue: 2900, tint: [1, 1, 1, 1], uv: [1, 1, 0, 0]};
  const event = controlEvent("title", 10, 9);
  event.values.prefabGameObject = {m_FileID: 0, m_PathID: "678762954342101232"};
  const track = {id: "title", label: "StageEffect/Expert/Display/Title_mainDis", nativeClass: "CustomControlTrack",
    events: [event]};
  const emitter = (name, z) => ({...pose(name, [0, 0, z]), texture: 0, material, active: [0, null],
    size: [1, 1], lifetime: 8, sizeCurves: [constant(1), constant(1)], atlas: {tiles: [1, 1], row: 0, frame: constant(0)},
    color: {rgb: [[0, 1, 1, 1]], alpha: [[0, 1]]}});
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12);
  png.writeUInt32BE(1, 16);
  png.writeUInt32BE(1, 20);
  const descriptor = {geometry: {positions: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
    uv: [[0, 0], [1, 0], [1, 1], [0, 1]], indices: [0, 1, 2, 0, 2, 3]},
  textures: [{png: png.toString("base64"), width: 1, height: 1}],
  cues: [{trackId: "inactive", eventId: "mesh", texture: 0, material,
    meshes: [{...pose("mesh", [0, 0, 0]), path: 1}], animation: {start: 0, duration: 1, loop: false, channels: []}}],
  particles: [{trackId: track.id, eventId: event.id,
    emitters: [emitter("title_sub", -6), emitter("title_main_vanish", -12), emitter("block", -2), emitter("other", -20)]}]};
  const local = {...T, TextureLoader: class {async loadAsync() { return new T.Texture({width: 1, height: 1}); }}};
  const title = await MVStudioTitle.apply(local, root, descriptor);
  assert.ok(title);
  return {title, track};
}

function particles(mesh, name) {
  const attribute = mesh.geometry.getAttribute(name);
  const values = Array.from(attribute.array.subarray(0, mesh.geometry.instanceCount * attribute.itemSize));
  return Array.from({length: mesh.geometry.instanceCount}, (_, index) =>
    values.slice(index * attribute.itemSize, (index + 1) * attribute.itemSize));
}

function verifyNativeWarmState() {
  const f32 = Math.fround, base = {rotation: identity, cycle: 50,
    rollRange: [f32(6.283185), f32(-6.283185)], rollSpeedRange: [f32(-.2617994), f32(.2617994)]};
  const sway = sign => ["cubic", [[0, [32 * sign, -24 * sign, 0, sign]],
    [.5, [-32 * sign, 24 * sign, 0, -sign]], [1, [0, 0, 0, sign]]]];
  const falling = [
    {...base, name: "light_big", seed: 0, position: [0, f32(6.3), f32(-6.53)],
      box: [8, 1, 1], size: [4, 1, f32(.1)], lifetime: 8, rate: 0, burstPeriod: 1, velocityY: [-.5, -1.5]},
    {...base, name: "stars", seed: 397783150, position: [0, 5, -7], box: [8, 1, 0],
      size: [f32(.3), .5], lifetime: 5, rate: 10, burstPeriod: 0, sizePeriod: f32(.05),
      sizeCurve: ["cubic", [[0, [31999.998092651433, -799.9999523162854, -20, 1]],
        [f32(.025), [-31999.998092651433, 1599.9999403953566, 0, .5]], [f32(.05), [0, 0, 0, 1]]]],
      velocityMultipliers: [f32(.2), 1.5, 1], velocityCurves: [[sway(1), sway(-1)], [
        ["cubic", [[0, [2.9802322387695312e-8, -4.470348358154297e-8, -.39402538537979126, -.10473863780498505]],
          [1, [0, 0, 0, -.4987640380859375]]]],
        ["cubic", [[0, [0, 0, -.646807849407196, -.35319215059280396]], [1, [0, 0, 0, -1]]]],
      ], [constant(0), constant(0)]]},
  ];
  const sample = (simulation, time, fps = 60) => {
    const output = [];
    simulation.sample(time, fps, (...particle) => output.push(particle));
    return output;
  };
  const [light, stars] = falling.map(row => MVStudioFallingSimulation.create(row));
  assert.ok(light && stars);
  const lightWarm = sample(light, 0), starWarm = sample(stars, 0);
  assert.deepEqual([lightWarm.length, starWarm.length], [9, 51]);
  function compareNative(particle, position, roll, age) {
    const expected = [...position, roll, age], actual = [...particle.slice(0, 3), ...particle.slice(5, 7)];
    assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) < .00001), `${actual} differs from ${expected}`);
  }
  // Native ARM non-looping prewarm snapshots, reflected in X and normalized in age.
  compareNative(lightWarm[0], [-.6731171607971191, -.8746415972709656, -6.356393337249756],
    -2.7737183570861816, .9750025177001953);
  assert.deepEqual(lightWarm[0].slice(3, 5), [4, 1]);
  compareNative(starWarm[0], [2.663102149963379, 1.6578537225723267, -7], -1.252691626548767, .999981460571289);
  assert.ok(Math.abs(starWarm[0][3] - .3800473213195801) < .000001);
  assert.ok(starWarm[0][7] < 32768 && starWarm.at(-1)[7] > 32768);
  const lightNext = sample(light, 61 / 60), starNext = sample(stars, 61 / 60);
  assert.deepEqual([lightNext.length, starNext.length], [8, 50]);
  compareNative(lightNext[0], [-3.828301429748535, 5.062197208404541, -6.216256141662598],
    1.9576174020767212, .12708416938781738);
  compareNative(starNext[0], [2.2865188121795654, 4.679867267608643, -7], 4.270015239715576, .20333620071411133);
  assert.deepEqual(sample(light, 0, 30), lightWarm);
  assert.deepEqual(sample(stars, 0, 30), starWarm);
  assert.deepEqual(sample(light, 61 / 60), lightNext);
  assert.deepEqual(sample(stars, 61 / 60), starNext);

  // The native clock has cleared a light slot on tick 60. A single
  // old 1/30-second integration per frame used to leave nine live.
  for (const fps of [30, 60]) {
    const lightsAtOne = sample(light, 1, fps), starsAtOne = sample(stars, 1, fps);
    assert.deepEqual([lightsAtOne.length, starsAtOne.length], [8, 51]);
    compareNative(lightsAtOne[0], [-3.828301429748535, 5.078756809234619, -6.216256141662598],
      1.9538403749465942, .12500083923339844);
    compareNative(starsAtOne[0], [2.2861599922180176, 4.690165042877197, -7], 4.269911766052246, .2000028610229492);
    for (const [emitter, expected] of [[light, lightsAtOne], [stars, starsAtOne]]) {
      sample(emitter, 6.5, fps); // Advance beyond several seek checkpoints.
      assert.deepEqual(sample(emitter, 1 + .5 / fps, fps), expected, "seek restores the last completed frame");
      sample(emitter, 3, 90 - fps);
      assert.deepEqual(sample(emitter, 1, fps), expected, "a change of display cadence preserves deterministic seeks");
    }
  }
}

async function verifyPackets() {
  const root = new T.Scene(), source = sourceFixture(), calls = [];
  const displayLights = new T.Texture(), speedBackCenterStars = new T.Texture(), borrowed = {displayLights, speedBackCenterStars};
  // A known warm stream isolates renderer ordering and palette/atlas selection
  // from the separate native simulation oracle.
  const originalSimulation = global.MVStudioFallingSimulation;
  global.MVStudioFallingSimulation = {create(row) {
    return {sample(elapsed, fps, emit) {
      calls.push([row.name, elapsed, fps]);
      emit(0, 1, -4, 2, 1, .5, .102, 32768);
      emit(0, 1, -8, 3, 1, 1, .02, 32769);
      emit(2, 1, -4, 4, 1, -1, .28, 32);
    }};
  }};
  let display;
  try {
    assert.equal(await MVStudioFallingDisplay.apply(T, root, source, {displayLights}), null);
    assert.equal(root.children.length, 0);
    display = await MVStudioFallingDisplay.apply(T, root, source, borrowed);
    assert.ok(display);
  } finally {
    global.MVStudioFallingSimulation = originalSimulation;
  }
  let textureDisposals = 0, geometries = 0, materials = 0;
  for (const texture of Object.values(borrowed)) texture.addEventListener("dispose", () => textureDisposals++);
  const meshes = new Map(root.children.map((mesh, index) => [source.emitters[index].name, mesh]));
  assert.equal(meshes.size, 5);
  assert.equal(root.children.length, 5);
  for (const [name, mesh] of meshes) {
    const {geometry, material} = mesh, stars = name === "stars";
    assert.equal(mesh.name, `Native stage falling ${name}`);
    assert.equal(mesh.visible, false);
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.groups.length, 0);
    assert.equal(geometry.index.count, 6);
    assert.equal(geometry.instanceCount, 0);
    assert.equal(geometry.getAttribute("centerAndTile").count, stars ? 52 : 9);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.ok(geometry.getAttribute("particleColor").array instanceof Uint8Array);
    assert.equal(geometry.getAttribute("particleRoll").isInstancedBufferAttribute, true);
    assert.equal(material.defines.PARTICLE_ROLL, 1);
    assert.equal(material.uniforms.uTexture.value, stars ? speedBackCenterStars : displayLights);
    assert.deepEqual(material.uniforms.uAtlas.value.toArray(), stars ? [.25, .25, .75, .25] : [1, .25, 0, 0]);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, stars ? T.OneFactor : T.OneMinusSrcAlphaFactor);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilWriteMask, 255);
    geometry.addEventListener("dispose", () => geometries++);
    material.addEventListener("dispose", () => materials++);
  }

  const {title, track: titleTrack} = await makeTitle(root);
  const event05 = controlEvent("05", firstStart, 48.28333333333333 - firstStart);
  const event07 = controlEvent("07", secondStart, 77.05 - secondStart);
  const track = {id: "lights", nativeClass: "CustomControlTrack", events: [event05, event07]};
  const settings = {stage_display: true, stage_control: false, frame_rate_60fps: true};
  const project = {tracks: [track, titleTrack], quality: {values: settings}};
  const perspective = new T.PerspectiveCamera();
  const ortho = new T.OrthographicCamera();
  const update = (time, camera = perspective) => {
    calls.length = 0;
    title.update(time, project);
    display.update(time, project);
    display.sort(camera, title.displaySortEntries);
  };
  const big = meshes.get("light_big"), stars = meshes.get("stars");
  const tiles = () => particles(big, "centerAndTile").map(row => row[3]);
  const colors = () => particles(stars, "particleColor");
  function cleared() {
    assert.equal(calls.length, 0);
    for (const mesh of meshes.values()) {
      assert.equal(mesh.visible, false);
      assert.equal(mesh.geometry.instanceCount, 0);
    }
  }
  update(firstStart - .001);
  cleared();
  update(firstStart);
  assert.deepEqual(calls, source.emitters.map(row => [row.name, 0, 60]));
  assert.deepEqual(particles(big, "centerAndTile").map(row => row.slice(0, 3)), [[0, 1, -8], [2, 1, -4], [0, 1, -4]]);
  assert.deepEqual(particles(big, "particleRoll"), [[1], [-1], [.5]]);
  assert.equal(big.geometry.getAttribute("centerAndTile").updateRange.count, 12);
  assert.deepEqual(tiles(), [0, 1, 1]);
  assert.deepEqual(colors(), [white, [128, 170, 255, 255], [128, 170, 255, 255]]);

  const peers = title.displaySortEntries();
  assert.deepEqual(peers.map(({mesh}) => mesh.name), ["title_sub", "title_main_vanish", "block"]);
  const drawOrder = [...meshes, ...peers.map(({mesh}) => [mesh.name, mesh])]
    .sort((a, b) => a[1].renderOrder - b[1].renderOrder).map(([name]) => name);
  assert.deepEqual(drawOrder, ["title_main_vanish", "light_smole_R", "stars", "light_big", "title_sub",
    "light_smole", "light_smole_L", "block"]);
  display.sort(ortho, title.displaySortEntries);
  assert.deepEqual(particles(big, "centerAndTile").map(row => row.slice(0, 3)), [[0, 1, -8], [0, 1, -4], [2, 1, -4]]);
  assert.deepEqual(particles(big, "particleRoll"), [[1], [.5], [-1]], "equal-depth particles retain their emission order");
  track.muted = true;
  update(firstStart);
  cleared();
  assert.ok(peers.every(({mesh}) => mesh.renderOrder === 2900), "title-only rendering resumes its original queue");
  track.muted = false;

  settings.frame_rate_60fps = false;
  update(secondStart);
  assert.deepEqual(calls, source.emitters.map(row => [row.name, 0, 30]));
  assert.deepEqual(tiles(), [2, 3, 3]);
  assert.deepEqual(colors(), [white, [255, 128, 128, 255], [255, 128, 128, 255]]);
  update(77.05);
  cleared();
  settings.stage_display = false;
  update(secondStart);
  cleared();
  settings.stage_display = true;
  event07.values.offset.z = 1;
  update(secondStart);
  cleared();
  event07.values.offset.z = 0;
  project.tracks[0] = {...track, events: [event05, {...event07, start: 82}]};
  display.invalidate();
  update(secondStart);
  cleared();
  update(82);
  assert.deepEqual(tiles(), [2, 3, 3]);
  update(firstStart);
  assert.deepEqual(tiles(), [0, 1, 1]);
  assert.deepEqual(colors(), [white, [128, 170, 255, 255], [128, 170, 255, 255]]);

  display.dispose();
  display.dispose();
  update(firstStart);
  assert.equal(calls.length, 0);
  assert.equal(materials, 5);
  assert.equal(geometries, 5);
  assert.equal(textureDisposals, 0);
  title.dispose();
  assert.equal(root.children.length, 0);
  for (const texture of Object.values(borrowed)) texture.dispose();
  assert.equal(textureDisposals, 2);
}

verifyPackets().then(() => {
  verifyNativeWarmState();
  console.log("Native falling display: prewarm, shared atlases, cue variants, inner and cross-title sorting, and cleanup.");
}).catch(error => { console.error(error); process.exitCode = 1; });
