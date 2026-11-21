"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-moving-companions.js");
require("../webtools/web/static/mv-studio-sparks-b-simulation.js");
require("../webtools/web/static/mv-studio-stage-sparks.js");

const f32 = Math.fround, start = 77.41666666666667, duration = 5.716666666666669;
const alias = "speedBackCenterStars", tint = [2, 2, 2, 1];
const cubic = rows => ["cubic", rows.map(([time, a, b, c, d]) => [time, [a, b, c, d]])];
const step = (time, value) => [time, 0, 0, 0, value];
const sparksColors = [[1, .9511772990226746, .551886796951294, 1], [1, .8011445999145508, .49528300762176514, 1]];

function growFixture() {
  const size = cubic([[0, -.19588834047317505, -.23830905556678772, 1.0642831325531006, .3699142634868622], step(1, 1)]);
  const color = [1, 1, 1, f32(128 / 255)];
  const life = [[0, 255, 255, 255, 80], [.14999619126319885, 255, 255, 255, 200],
    [f32(.2), 255, 255, 255, 178], [f32(.6), 244, 231, 169, 0], [1, 233, 207, 83, 0]];
  return {name: "grow", shape: {type: 0, radius: f32(.1), radiusThickness: 1, arc: 360, arcMode: 0,
    scale: [1, 1, 1], rotation: [0, 0, 0]}, uv: [.25, .25, 0, .5], maxViewportWidth: .5, stretch: null,
    rate: 0, duration: f32(.4), bursts: [[0, 1]], capacity: 200, seed: null, delay: [0, 0],
    lifetime: [f32(.3), f32(.3)], size: [8, 8], speed: [0, 0], roll: [0, f32(Math.PI)], gravity: 0,
    sizeCurves: [size, size], sizeMultiplier: 1, velocityCurves: null, velocityMultipliers: null, clamp: null,
    startColors: [color, color], lifeColors: [life, life]};
}

function hibanaFixture() {
  const velocity = [cubic([[0, 358796.280509804, -4305.555293267526, -51.66666793823242, -.3799999952316284],
    [.012000000104308128, -2.072305080002828, 3.071156128239954, 0, -1], step(1, -.0007031243294477463)]),
  cubic([[0, -356299.3912526515, 4275.592873845752, 51.30710983276367, .3843146562576294],
    [.012000000104308128, 2.0723209015603947, -3.071179575788265, 0, 1], step(1, .0006954949349164963)])];
  return {name: "hibana", shape: {type: 0, radius: .5, radiusThickness: 1, arc: 180, arcMode: 3,
    scale: [1.5, .25, 1], rotation: [90, 0, 0]}, uv: [.25, .25, .75, .25], maxViewportWidth: .5,
    stretch: {lengthScale: 2.5, velocityScale: f32(.02)}, duration: f32(1.8), rate: 0,
    bursts: [[0, 100], [f32(.03), 75], [f32(.06), 50]], seed: 0, delay: [0, 0],
    lifetime: [1, 2], size: [f32(.06), f32(.14)], speed: [2, 20], roll: [0, 0], gravity: f32(.8), capacity: 1000,
    sizeCurves: [cubic([[0, 9.81696919095336, 10.285335938879275, -4.7270588874816895, 1],
      step(.1768110990524292, .5400086641311646), step(.30486735701560974, .49963128566741943),
      step(.522357702255249, .4290432631969452), step(.6808990240097046, .3388473689556122),
      step(.8556905388832092, .2525733411312103), step(1, .19608214497566223)]),
    cubic([[0, -46.94844928131856, 35.79968602290368, -8.409653663635254, 1],
      step(.17681105434894562, .37274813652038574), step(.4552859961986542, .23870223760604858),
      step(.5461310148239136, .16156314313411713), step(.6342512369155884, .12914639711380005),
      step(.750648021697998, .08134487271308899), step(.9113887548446655, .025256618857383728), step(1, 0)])],
    sizeMultiplier: 2, velocityCurves: [velocity, velocity, velocity], velocityMultipliers: [1, 1, 1],
    clamp: {limit: 1, dampen: f32(.15)},
    startColors: sparksColors,
    lifeColors: [[[0, 253, 249, 194, 0], [.3000076413154602, 253, 249, 194, 244],
      [.48477911949157715, 248, 190, 151, 247], [.9499961733818054, 211, 103, 37, 255], [1, 207, 93, 24, 0]],
    [[0, 255, 251, 198, 0], [.3000076413154602, 255, 251, 198, 244], [.5000076293945312, 253, 243, 182, 247],
      [.6675059199333191, 253, 219, 135, 250], [.9499961733818054, 241, 149, 60, 255], [1, 241, 149, 60, 0]]]};
}

function lateFixture() {
  const zero = ["constant", 0];
  // Keep the authored curve segments evaluated through the first two live ticks.
  return {name: "late_kirakira", shape: {type: 0, radius: 1.5, radiusThickness: 1, arc: 180, arcMode: 0,
    scale: [4, .5, 1], rotation: [90, 0, 0]}, uv: [.25, .25, .75, .25], maxViewportWidth: .5, stretch: null,
    duration: 1, rate: 75, bursts: [[0, 150]], seed: null, delay: [f32(.1), f32(.2)], lifetime: [2, 1.5],
    size: [f32(.2), f32(.3)], speed: [0, 0], roll: [0, f32(6.283185)], gravity: f32(.2), capacity: 1000,
    sizeCurves: [cubic([step(0, 1), step(.02631571888923645, .325486421585083)]),
      cubic([step(0, 1), step(.06390973925590515, .8696273565292358)])], sizeMultiplier: 1,
    velocityCurves: [[zero, zero], [cubic([[0, 3.978537756659827, -2.4391149013926334, 0, -.48827266693115234],
      step(f32(.3), -.6003724932670593)]), cubic([[0, 3.541188193581161, -2.1754187637724205, 0, -.08631116896867752],
      step(f32(.3), -.18648678064346313)])], [zero, zero]], velocityMultipliers: [1, 4, 1], clamp: null,
    startColors: sparksColors, lifeColors: [[[0, 253, 249, 194, 0], [.3000076413154602, 253, 249, 194, 146]],
      [[0, 255, 251, 198, 0], [.3000076413154602, 255, 251, 198, 146]]]};
}

function fixture() {
  return {textures: [alias], cues: [{trackId: "spark-left", eventId: "left"}, {trackId: "spark-right", eventId: "right"}],
    emitters: [growFixture(), hibanaFixture(), lateFixture()]};
}

function near(actual, expected, tolerance = .0001) {
  assert.equal(actual.length, expected.length);
  assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) < tolerance), `${actual} differs from ${expected}`);
}

function nativeSamples(row, seed) {
  const simulation = MVStudioSparksBSimulation.create(row, seed);
  assert.ok(simulation);
  return (age, fps = 60) => {
    const output = [];
    simulation.sample(age, fps, (...fields) => output.push(fields));
    return output;
  };
}

function verifyNativeHibana() {
  const row = hibanaFixture(), sample = nativeSamples(row, 0);
  assert.equal(MVStudioSparksBSimulation.create({...row, bursts: [[0, 100]]}, 0), null);
  assert.deepEqual(sample(0), []);
  const first = sample(1 / 60), second = sample(2 / 60), fourth = sample(4 / 60);
  assert.deepEqual([first.length, second.length, fourth.length], [100, 175, 225]);
  assert.deepEqual([first, second, fourth].map(frame => frame.filter(particle => particle[11] > 0).length), [0, 100, 175]);
  // Stock ARM seed 1900725526. Positions and combined render velocities
  // are reflected along X before comparison to browser coordinates.
  near(second[0].slice(0, 8), [-.8127917051315308, -.09521688520908356, -.004421795252710581,
    -15.49837875366211, -1.9266817569732666, -.26530763506889343, .21507808566093445, 0], .00001);
  assert.deepEqual(second[0].slice(8), [255, 227, 105, 8]);
  assert.deepEqual(fourth[0].slice(8), [255, 227, 105, 25]);
  assert.deepEqual(sample(1 / 30, 30), second);
  assert.deepEqual(sample(3 / 60, 30), second);
  assert.deepEqual(sample(2 / 30, 30), fourth);
  const bright = sample(1);
  assert.equal(bright.length, 225);
  near(bright[0].slice(0, 8), [-4.41758394241333, -2.092609405517578, -.08229437470436096,
    -.49596431851387024, -2.404886484146118, .1728937029838562, .08559295535087585, 0], .00001);
  assert.deepEqual(bright[0].slice(8), [250, 193, 76, 249]);
  assert.deepEqual(sample(3, 30), []);
  assert.deepEqual(sample(1, 30), bright);
  assert.deepEqual(sample(2 / 60), second);
}

function verifyNativeAutoEmitters() {
  const grow = nativeSamples(growFixture(), 2914), late = nativeSamples(lateFixture(), 2914);
  const first = grow(1 / 60);
  assert.equal(first.length, 1);
  near(first[0].slice(0, 8), [-.03631781041622162, .05654456093907356, .00249236891977489,
    0, 0, 0, 2.9593145847320557, .7476599812507629], .00001);
  assert.deepEqual(first[0].slice(8), [255, 255, 255, 40]);
  assert.deepEqual(late(.1), []);
  const birth = late(7 / 60), next = late(8 / 60);
  assert.deepEqual([birth.length, next.length], [150, 151]);
  assert.deepEqual(birth[0].slice(8), [253, 216, 100, 0]);
  near(next[0].slice(0, 8), [-3.5387144088745117, -.045142240822315216, .24161158502101898,
    0, -.46540361642837524, 0, .26992347836494446, 1.4953198432922363], .00001);
  assert.deepEqual(next[0].slice(8), [253, 216, 100, 5]);
  assert.deepEqual(late(4 / 30, 30), next);
  assert.deepEqual(late(.1, 30), []);
  assert.deepEqual(late(7 / 60), birth);
}

function verifyNativeStretchCorners(mesh) {
  const {material, geometry} = mesh;
  const corner = geometry.getAttribute("position"), uv = geometry.getAttribute("uv");
  const {uAtlas, uStretch} = material.uniforms;
  assert.match(material.vertexShader, /vec2 across = cross\(head\.xyz, movement\)\.xy;/);
  const head = new T.Vector3(-4, 5.5, -5), motion = new T.Vector3(0, 2, 0);
  const side = new T.Vector3().crossVectors(head, motion).setZ(0).normalize();
  // Native ARM reciprocal estimate for this velocity is .4990234375.
  const tail = uStretch.value.y + .06 * uStretch.value.x * .4990234375 * 1.0019569397;
  const position = [], coordinates = [];
  for (let i = 0; i < corner.count; i++) {
    const point = head.clone().addScaledVector(side, .02 * corner.getY(i));
    if (corner.getX(i) > 0) point.addScaledVector(motion, -tail);
    position.push(...point.toArray());
    coordinates.push(uAtlas.value.x * uv.getX(i) + uAtlas.value.z, uAtlas.value.y * uv.getY(i) + uAtlas.value.w);
  }
  near(position, [-3.98, 5.5, -5, -3.98, 5.31, -5, -4.02, 5.31, -5, -4.02, 5.5, -5], .00001);
  assert.deepEqual(coordinates, [.75, .25, 1, .25, 1, .5, .75, .5]);
}

async function verifyPackets() {
  const source = fixture(), root = new T.Scene(), texture = new T.Texture();
  const actual = global.MVStudioSparksBSimulation, particles = MVStudioStageParticles, originalSeed = particles.autoSeed;
  const created = [], calls = [];
  const colors = {grow: [255, 255, 255, 40], hibana: [255, 227, 105, 8], late_kirakira: [248, 205, 96, 5]};
  let nextSeed = 11, controller;
  try {
    particles.autoSeed = () => nextSeed++;
    global.MVStudioSparksBSimulation = {create(row, seed) {
      created.push([row.name, seed]);
      return {sample(age, fps, emit) {
        const tick = particles.nativeFrame(age, fps);
        calls.push([row.name, seed, tick]);
        if (tick < (row.name === "late_kirakira" ? 10 : row.name === "hibana" ? 2 : 1)) return;
        emit(0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0);
        emit(seed + tick / 60, -.25, .5, -3, 2, 1, .75, -.5, ...colors[row.name]);
      }};
    }};
    assert.equal(await MVStudioStageSparks.apply(T, root, source, {}, "B"), null);
    assert.equal(root.children.length, 0);
    controller = await MVStudioStageSparks.apply(T, root, source, {[alias]: texture}, "B");
    assert.ok(controller);
  } finally {
    particles.autoSeed = originalSeed;
    global.MVStudioSparksBSimulation = actual;
  }
  assert.deepEqual(created, [["grow", 11], ["hibana", 0], ["late_kirakira", 12], ["grow", 13], ["late_kirakira", 14]]);
  assert.equal(root.children.length, 6);
  const meshes = root.children.slice();
  let textureDisposals = 0, materials = 0, geometries = 0;
  texture.addEventListener("dispose", () => textureDisposals++);
  for (const [i, mesh] of meshes.entries()) {
    const row = source.emitters[i % 3], {material, geometry} = mesh;
    assert.equal(mesh.name, `Native spark B ${1 + Math.floor(i / 3)} ${row.name}`);
    assert.equal(mesh.renderOrder, 3010);
    assert.equal(mesh.frustumCulled, false);
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.index.count, 6);
    assert.equal(geometry.groups.length, 0);
    assert.equal(geometry.instanceCount, 0);
    assert.equal(mesh.visible, false);
    assert.equal(geometry.getAttribute("particleColor").count, row.name === "grow" ? 2 : 226);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.ok(geometry.getAttribute("particleColor").array instanceof Uint8Array);
    assert.equal(Boolean(material.defines.STRETCHED), Boolean(row.stretch));
    assert.equal(Boolean(material.defines.VIEW_ALIGNED), !row.stretch);
    assert.equal(Boolean(geometry.getAttribute("velocity")), Boolean(row.stretch));
    assert.equal(Boolean(geometry.getAttribute("particleRoll")), !row.stretch);
    assert.deepEqual(material.uniforms.uTint.value.toArray(), tint);
    assert.deepEqual(material.uniforms.uAtlas.value.toArray(), row.uv);
    assert.equal(material.uniforms.uTexture.value, texture);
    assert.equal(material.uniforms.uMaxWidth.value, .5);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneFactor);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.depthWrite, false);
    assert.equal(material.stencilFunc, T.AlwaysStencilFunc);
    assert.equal(material.stencilRef, 0);
    assert.equal(material.stencilWriteMask, 255);
    material.addEventListener("dispose", () => materials++);
    geometry.addEventListener("dispose", () => geometries++);
  }
  verifyNativeStretchCorners(meshes[1]);

  const tracks = source.cues.map(({eventId, trackId}, i) => ({id: trackId, nativeClass: "CustomControlTrack", events: [
    {id: eventId, start, duration, values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1, weight: 1,
      offset: {x: i ? -4 : 4, y: 5.5, z: -5}}},
  ]}));
  const settings = {frame_rate_60fps: true, stage_control: true, stage_display: false};
  const project = {tracks, quality: {values: settings}};
  const frameState = () => meshes.map(mesh => mesh.geometry.instanceCount);
  const shown = n => frames(n, n);
  function frames(left, right) { return [...left, ...right]; }
  const clear = [0, 0, 0];
  function update(time, counts) {
    controller.update(time, project);
    assert.deepEqual(frameState(), counts);
    assert.deepEqual(meshes.map(mesh => mesh.visible), counts.map(count => count > 0));
  }
  update(start - .001, shown(clear));
  update(start, shown(clear));
  update(start + 1 / 60, shown([1, 0, 0]));
  update(start + 2 / 60, shown([1, 1, 0]));
  update(start + 10 / 60, shown([1, 1, 1]));
  for (let i = 0; i < meshes.length; i++) {
    const mesh = meshes[i], row = source.emitters[i % 3], buffer = mesh.geometry.getAttribute("particleColor");
    assert.deepEqual(mesh.position.toArray(), [i < 3 ? -4 : 4, 5.5, -5]);
    assert.deepEqual([...buffer.array.slice(0, 4)], colors[row.name]);
    assert.equal(buffer.updateRange.count, 4);
  }
  const leftGrow = meshes[0].geometry.getAttribute("centerAndTile");
  const rightGrow = meshes[3].geometry.getAttribute("centerAndTile");
  assert.notEqual(leftGrow.getX(0), rightGrow.getX(0), "auto-seeded previews keep independent cue instances");
  const startOffset = tracks[0].events[0].values.offset, uploadVersion = leftGrow.version;
  startOffset.x = 4.5;
  calls.length = 0;
  update(start + 10 / 60, shown([1, 1, 1]));
  assert.equal(meshes[0].position.x, -4.5);
  assert.deepEqual(calls, []);
  assert.equal(leftGrow.version, uploadVersion);

  settings.frame_rate_60fps = false;
  update(start + 1 / 60, shown(clear));
  update(start + 2 / 60, shown([1, 1, 0]));
  update(start + 3 / 60, shown([1, 1, 0]));
  settings.stage_control = false;
  settings.stage_display = true;
  update(start + 10 / 60, shown(clear));
  settings.stage_control = true;
  tracks[0].muted = true;
  update(start + 10 / 60, frames(clear, [1, 1, 1]));
  tracks[0].muted = false;
  tracks[1] = {...tracks[1], events: [{...tracks[1].events[0], start: 91, duration: .5}]};
  controller.invalidate();
  update(start + 10 / 60, frames([1, 1, 1], clear));
  update(start + duration, shown(clear));
  update(89, shown(clear));
  update(91 + 10 / 60, frames(clear, [1, 1, 1]));
  update(91.5, shown(clear));
  update(start + 10 / 60, frames([1, 1, 1], clear));
  assert.equal(leftGrow.getX(0), f32(11 + 10 / 60));
  controller.dispose();
  controller.dispose();
  assert.equal(root.children.length, 0);
  assert.deepEqual([materials, geometries, textureDisposals], [6, 6, 0]);
  texture.dispose();
  assert.equal(textureDisposals, 1);
}

async function run() {
  verifyNativeHibana();
  verifyNativeAutoEmitters();
  await verifyPackets();
  console.log("Native Sparks B packets: separate control cues, stretch and camera-facing geometry, atlas ownership, and seek gates.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
