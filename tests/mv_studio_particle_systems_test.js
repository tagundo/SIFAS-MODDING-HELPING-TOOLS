"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-particle-systems.js");

const P = globalThis.MVStudioParticleSystems;
const native = globalThis.MVStudioStageParticles;
const f32 = Math.fround;

T.TextureLoader = class {
  async loadAsync(url) {
    const header = Buffer.from(url.split(",")[1], "base64");
    return new T.Texture({width: header.readUInt32BE(16), height: header.readUInt32BE(20)});
  }
};

function level(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {width: size, height: size, png: header.toString("base64")};
}

const constant = value => ({mode: 0, scalar: value, min: value});
const between = (min, max) => ({mode: 3, scalar: max, min});
const linear = {mode: 1, scalar: 1, min: 1, maxKeys: [[0, 0, 1, 1], [1, 1, 1, 1]]};
const white = {mode: 0, max: [1, 1, 1, 1]};

function system(overrides = {}) {
  const {main, emission, ...rest} = overrides;
  return {
    path: "root/dust", node: 0, layer: 1,
    main: {duration: 5, looping: true, prewarm: false, startDelay: constant(0), worldSpace: false, scalingMode: 1,
      autoRandomSeed: false, randomSeed: 1234, maxParticles: 1000, lifetime: between(2, 3), speed: constant(0),
      size: between(.1, .04), rotation: constant(0), color: white, gravity: constant(0), size3D: false,
      rotation3D: false, randomizeRotationDirection: 0, stopAction: 0, cullingMode: 0, simulationSpeed: 1, ...main},
    emission: {rate: constant(60), bursts: [], ...emission},
    shape: {type: 5, radius: 1, radiusThickness: 1, arc: 360, angle: 25, length: 5, boxThickness: [0, 0, 0],
      position: [0, 0, 0], rotation: [0, 0, 0], scale: [12, 12, 10], alignToDirection: false, randomDirection: 0,
      sphericalDirection: 0, randomPosition: 0, donutRadius: 0},
    velocity: null, clamp: null, size: null, rotation: null, color: null, uv: null, rotationBySpeed: null,
    renderer: {mode: 0, alignment: 0, sortMode: 0, sortingFudge: 0, minParticleSize: 0, maxParticleSize: .5,
      lengthScale: 2, velocityScale: 0, cameraVelocityScale: 0, pivot: [0, 0, 0], flip: [0, 0, 0], allowRoll: true},
    material: {name: "mat", queue: 3000, tint: [1, 1, 1, 1], st: [1, 1, 0, 0], vertexColor: true, saturate: false,
      blend: [5, 1], cull: 0, zTest: 4, zWrite: 0, stencil: [8, 2, 0, 0], texture: 0},
    ...rest,
  };
}

function snapshot(stream, active) {
  return active.map(atom => stream.describe(atom));
}

function testDrawOrderMatchesNativeLanes() {
  // The first birth of lane 0 reads its own stream: word, lifetime, size, rotation, color.
  const seed = 1339252716;
  const stream = P.create(system({main: {randomSeed: seed}, emission: {rate: constant(60)}}), seed);
  const [first] = stream.sample(1, 30);
  const draw = native.nativeRandom(seed);
  const word = draw();
  const life = native.nativeInverseLifetime(f32(2 + f32(f32(1) * native.nativeUnit(draw()))));
  const size = f32(f32(.1) + f32(f32(f32(.04) - f32(.1)) * native.nativeUnit(draw())));
  assert.equal(first.source.word, word);
  assert.equal(first.source.life, life);
  assert.equal(first.source.size[0], size);
  // Box positions come from the separate shape stream of the same lane.
  const shape = native.nativeRandom(seed);
  assert.equal(first.source.position[0], f32(f32(native.nativeUnit(shape()) - .5) * 12));
}

function testSeekMatchesPlayback() {
  const row = system({main: {prewarm: true}, velocity: {x: constant(0), y: between(-.2, .2), z: constant(.1), worldSpace: false},
    size: {separateAxes: false, curve: linear}});
  const played = P.create(row, 77), jumped = P.create(row, 77), back = P.create(row, 77);
  let expected;
  for (let frame = 1; frame <= 410; frame++) expected = snapshot(played, played.sample(frame, 30));
  assert.deepEqual(snapshot(jumped, jumped.sample(410, 30)), expected);
  back.sample(600, 30);
  assert.deepEqual(snapshot(back, back.sample(410, 30)), expected, "seeking back restores the checkpointed state");
}

function testPrewarmedSteadyState() {
  const stream = P.create(system({main: {prewarm: true}}), 5);
  const count = stream.sample(1, 30).length;
  // rate x mean lifetime = 60 x 2.5
  assert.ok(Math.abs(count - 150) <= 15, `prewarmed count ${count}`);
  const capped = P.create(system({main: {prewarm: true, maxParticles: 60}}), 5);
  assert.equal(capped.sample(1, 30).length, 60);
  const cold = P.create(system(), 5);
  assert.ok(cold.sample(1, 30).length <= 2, "without prewarm the first frame holds only its own births");
}

function testBurstsCyclesAndExpiry() {
  const row = system({main: {looping: false, duration: 3, lifetime: constant(1.5)},
    emission: {rate: constant(0), bursts: [{time: 0, count: constant(5), cycles: 3, interval: .5, probability: 1}]}});
  const stream = P.create(row, 9);
  assert.equal(stream.sample(3, 30).length, 5);
  assert.equal(stream.sample(16, 30).length, 10);
  assert.equal(stream.sample(31, 30).length, 15);
  assert.equal(stream.sample(52, 30).length, 10, "the first burst has expired after 1.5 s");
  assert.equal(stream.sample(120, 30).length, 0);
  const looping = P.create(system({main: {looping: true, duration: 1, lifetime: constant(5), maxParticles: 100},
    emission: {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]}}), 3);
  assert.equal(looping.sample(91, 30).length, 4, "a time-zero burst fires once per loop");
}

function testCurvesAndColorsOverLifetime() {
  const row = system({main: {looping: false, duration: 1, lifetime: constant(2), size: constant(2)},
    emission: {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]},
    size: {separateAxes: false, curve: linear},
    color: {mode: 1, maxGradient: {mode: 0, rgb: [[0, 1, 1, 1], [65535, 1, 1, 1]], alpha: [[0, 0], [32768, 1], [65535, 0]]}}});
  const stream = P.create(row, 1);
  const [atom] = stream.sample(30, 30);
  const row1 = stream.describe(atom);
  // About half of the 2 s lifetime: linear size near 1, alpha at the gradient peak.
  assert.ok(Math.abs(row1.size[0] - 1) < .05, `size ${row1.size[0]}`);
  assert.ok(row1.rgba[3] > 245, `alpha ${row1.rgba[3]}`);
  assert.ok(Math.abs(atom.age - 50) < 2.5, `age ${atom.age}`);
}

function testOrbitalRadialAndBurstSpread() {
  const once = {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]};
  const point = {type: 5, radius: 1, radiusThickness: 1, arc: 360, angle: 25, length: 5, boxThickness: [0, 0, 0],
    position: [1, 0, 0], rotation: [0, 0, 0], scale: [0, 0, 0], alignToDirection: false, randomDirection: 0,
    sphericalDirection: 0, randomPosition: 0, donutRadius: 0};
  const orbit = (z, radial) => ({x: constant(0), y: constant(0), z: constant(0), worldSpace: false,
    orbital: {orbitalX: constant(0), orbitalY: constant(0), orbitalZ: constant(z), orbitalOffsetX: constant(0),
      orbitalOffsetY: constant(0), orbitalOffsetZ: constant(0), radial: constant(radial)}});
  const base = {main: {looping: false, duration: 10, lifetime: constant(10)}, emission: once, shape: point};
  // A quarter turn per second about Z moves (1, 0, 0) to (0, 1, 0).
  const spin = P.create(system({...base, velocity: orbit(Math.PI / 2, 0)}), 2);
  const [turned] = spin.sample(30, 30);
  assert.ok(Math.abs(turned.x) < .03 && Math.abs(turned.y - 1) < .03, `${turned.x},${turned.y}`);
  const push = P.create(system({...base, velocity: orbit(0, .5)}), 2);
  const [pushed] = push.sample(60, 30);
  assert.ok(Math.abs(pushed.x - 2) < .03 && Math.abs(pushed.y) < 1e-6, `radial ${pushed.x}`);
  // BurstSpread places one batch evenly over the arc instead of drawing a heading.
  const ring = {...point, type: 10, position: [0, 0, 0], scale: [1, 1, 1], radiusThickness: 0, arc: 180, arcMode: 3};
  const spread = P.create(system({main: {looping: false, duration: 10, lifetime: constant(10)}, shape: ring,
    emission: {rate: constant(0), bursts: [{time: 0, count: constant(5), cycles: 1, interval: 0, probability: 1}]}}), 4);
  const angles = spread.sample(1, 30).map(atom => Math.atan2(atom.source.position[1], atom.source.position[0]))
    .sort((a, b) => a - b);
  angles.forEach((angle, index) => assert.ok(Math.abs(angle - index * Math.PI / 4) < 1e-3, `slot ${index}: ${angle}`));
}

function testLimitVelocityDampenAndDrag() {
  const once = {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]};
  const base = {main: {looping: false, duration: 10, lifetime: constant(10), speed: constant(10), size: constant(1)},
    emission: once};
  const speedAt = (row, frames) => {
    const stream = P.create(system({...base, ...row}), 1);
    const [atom] = stream.sample(frames, 30);
    return Math.hypot(atom.mx, atom.my, atom.mz);
  };
  // Full dampen clamps at once; half dampen per 1/30 s halves the excess every 1/30 s
  // (two display frames: 8 over the limit becomes 2).
  assert.ok(Math.abs(speedAt({clamp: {separateAxes: false, worldSpace: false, dampen: 1, magnitude: constant(2)}}, 1) - 2) < 1e-5);
  const half = speedAt({clamp: {separateAxes: false, worldSpace: false, dampen: .5, magnitude: constant(2)}}, 2);
  assert.ok(Math.abs(half - 4) < .05, `half dampen ${half}`);
  // Quadratic drag on a unit-size particle: dv/dt = -v^2 * drag * pi / 4.
  const dragged = speedAt({clamp: {separateAxes: false, worldSpace: false, dampen: 0, magnitude: constant(100),
    drag: constant(1)}}, 30);
  const expected = 1 / (1 / 10 + Math.PI / 4);
  assert.ok(Math.abs(dragged - expected) / expected < .05, `drag ${dragged} vs ${expected}`);
}

function testActivationTiming() {
  const event = {start: 7.383333333333334, duration: 40.55};
  assert.equal(P.activeFrames(event, 7.3, 30), 0);
  assert.equal(P.activeFrames(event, 7.4, 30), 1, "the clone updates in its activation frame");
  assert.equal(P.activeFrames(event, 11.5, 30), 124);
  assert.equal(P.activeFrames(event, 47.95, 30), 0, "OnBehaviourPause deactivates the clone at the clip end");
}

function testMaterialMappingAndLayers() {
  assert.equal(P.blendFactor(T, 5), T.SrcAlphaFactor);
  assert.equal(P.blendFactor(T, 1), T.OneFactor);
  assert.equal(P.blendFactor(T, 10), T.OneMinusSrcAlphaFactor);
  assert.equal(P.depthFunction(T, 4), T.LessEqualDepth);
  assert.equal(P.depthFunction(T, 0), null);
  const drawn = layer => ((P.mainCameraMask >>> layer) & 1) === 1;
  assert.deepEqual([1, 15, 26, 20, 5].map(drawn), [true, true, true, false, false]);
  // Unity's Quaternion.Euler(90, 0, 0) turns +Y to +Z.
  const q = P.eulerQuaternion([90, 0, 0]);
  const v = new T.Vector3(0, 1, 0).applyQuaternion(new T.Quaternion(...q));
  assert.ok(Math.abs(v.z - 1) < 1e-6 && Math.abs(v.y) < 1e-6);
}

async function testApplyDrawsActiveCuesOnly() {
  const root = new T.Group();
  const nodes = [{parent: null, path: "fx", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]},
    {parent: 0, path: "fx/dust", layer: 1, position: [1, 5.85, 0], rotation: [.7071068, 0, 0, .7071068], scale: [1, 1, 1]}];
  const descriptor = {schema: 1, textures: [{name: "tex", filter: 1, wrap: [1, 1], levels: Array.from({length: 7}, (_, i) => level(64 >> i))}],
    templates: [{name: "fx", nodes, systems: [system({node: 1}), system({node: 1, layer: 20, path: "fx/overlay"}),
      system({node: 1, layer: 15, path: "fx/floor", renderer: {...system().renderer, mode: 2, maxParticleSize: 2}})]}],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [0, 13, 59], quality: "stage_control", clipSeed: 7}]};
  assert.equal(P.validDescriptor(descriptor), true);
  assert.equal(P.validDescriptor({...descriptor, cues: [{...descriptor.cues[0], template: 3}]}), false);
  const controller = await P.apply(T, root, descriptor);
  assert.ok(controller);
  const project = {tracks: [{id: "track", events: [{id: "track:0", start: 1, duration: 2}]}],
    quality: {values: {stage_control: true, frame_rate_60fps: false}}};
  controller.update(.5, project);
  const group = root.children[0];
  assert.equal(group.children.filter(mesh => mesh.visible).length, 0);
  controller.update(2, project);
  const visible = group.children.filter(mesh => mesh.visible && mesh.name.endsWith("root/dust"));
  assert.equal(group.children.filter(mesh => mesh.visible).length, 2, "the layer-20 system is left to the overlay camera");
  const floor = group.children.find(mesh => mesh.name.endsWith("fx/floor"));
  assert.equal(floor.material.uniforms.uPlaneScale.value, Math.fround(Math.SQRT1_2));
  assert.deepEqual(floor.material.uniforms.uAxisX.value.toArray(), [-1, 0, 0], "Unity +X is reflected like the stage");
  assert.equal(visible[0].material.blendSrc, T.SrcAlphaFactor);
  assert.equal(visible[0].material.blendDst, T.OneFactor);
  assert.equal(visible[0].material.depthWrite, false);
  assert.equal(visible[0].material.uniforms.uTexture.value.wrapS, T.ClampToEdgeWrapping);
  assert.equal(visible[0].material.uniforms.uPlaneScale.value, 1);
  const [state] = controller.inspect(2);
  assert.equal(state.alive, visible[0].geometry.instanceCount);
  // Unity X is reflected; the clone sits at the clip offset plus the node pose.
  for (const [x, y, z] of state.positions) {
    assert.ok(x >= -1 - 6.01 && x <= -1 + 6.01 && Math.abs(z - 59) <= 6.01 && Math.abs(y - 18.85) <= 5.01, `${x},${y},${z}`);
  }
  controller.update(2, {...project, quality: {values: {stage_control: false}}});
  assert.equal(group.children.filter(mesh => mesh.visible).length, 0, "the quality category gates the clip");
  controller.update(3.5, project);
  assert.equal(group.children.filter(mesh => mesh.visible).length, 0);
  controller.dispose();
  assert.equal(root.children.length, 0);
}

(async () => {
  testDrawOrderMatchesNativeLanes();
  testSeekMatchesPlayback();
  testPrewarmedSteadyState();
  testBurstsCyclesAndExpiry();
  testCurvesAndColorsOverLifetime();
  testOrbitalRadialAndBurstSpread();
  testLimitVelocityDampenAndDrag();
  testActivationTiming();
  testMaterialMappingAndLayers();
  await testApplyDrawsActiveCuesOnly();
  console.log("mv_studio_particle_systems_test: ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
