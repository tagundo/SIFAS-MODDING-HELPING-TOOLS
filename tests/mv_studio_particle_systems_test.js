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

// Activation prewarm (Play(1) -> Simulate 0x1cbf64 -> 0x1d1e54 / 0x1ce4b0): step plan, rate carry and
// the procedural batch cap. Game values (dump4 / dump3b, 12035): a procedural display kira_up
// (rate 15, lifetime 1..10, max 40) holds 15 particles 0.886 s after activation, not a full pool;
// a rate-0 burst cloud with maxParticles 2 holds none during its first loop, one with 10 holds one.
function testPrewarmActivationBuildUp() {
  const plan = P.prewarmSteps(12.5, 30);
  assert.deepEqual(plan.steps.slice(0, 8), Array(8).fill(1), "1 s steps above 10 s, kept while above 5 s");
  assert.equal(plan.steps[8], f32(.02));
  assert.ok(plan.steps.slice(8).every(step => step === f32(.02)));
  assert.ok(plan.remainder >= 0 && plan.remainder < f32(.02));
  assert.deepEqual(P.prewarmSteps(8, 30).steps.slice(0, 3), [f32(.2), f32(.2), f32(.2)]);
  assert.deepEqual(P.prewarmSteps(25, .5).steps.slice(0, 2), [.5, .5], "steps never exceed the duration");
  assert.deepEqual(P.prewarmSteps(.01, 5), {steps: [], remainder: f32(.01)});

  const procedural = {pauses: true, bounds: [-1, -1, -1, 1, 1, 1], uniform: true, procedural: true};
  const kira = (flag, extra = {}) => system({main: {prewarm: true, duration: 50, lifetime: between(1, 10), maxParticles: 40},
    emission: {enabled: true, rate: constant(15), bursts: []}, culling: {...procedural, procedural: flag}, ...extra});
  const alive = (stream, frames) => stream.sample(frames, 30).filter(atom => atom.age <= 100).length;
  const counts = flag => Array.from({length: 8}, (_, seed) => alive(P.create(kira(flag), 100 + seed), 27));
  const mean = rows => rows.reduce((sum, value) => sum + value, 0) / rows.length;
  // The procedural prewarm stops emitting once 40 particles were emitted (2.7 s of its 10 s), so most are
  // dead at activation and the pool builds up again; a non-procedural prewarm keeps the pool full.
  assert.ok(mean(counts(true)) < 24, `procedural prewarm build-up ${counts(true)}`);
  assert.ok(mean(counts(false)) > 36, `non-procedural prewarm ${counts(false)}`);
  assert.ok(alive(P.create(kira(true), 5), 300) >= 36, "the pool is full again later");

  const cloud = (max, emission = {}) => system({main: {prewarm: true, duration: 10, lifetime: between(10, 10), maxParticles: max},
    emission: {enabled: true, rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: .01, probability: 1}],
      ...emission}, culling: procedural});
  const loop = stream => [1, 9, 27, 150, 290, 301, 450].map(frames => alive(stream, frames));
  // The prewarm's first .2 s step emits the burst plus the seeded carry: one batch of 2 particles, 9.8 s old
  // at activation (a procedural batch ages from its step's end); the wrap at the loop end fires the burst
  // again only if the batch cap leaves room.
  assert.deepEqual(loop(P.create(cloud(10), 3)), [3, 1, 1, 1, 1, 1, 1]);
  assert.deepEqual(loop(P.create(cloud(2), 3)), [2, 0, 0, 0, 0, 1, 1], "maxParticles 2: an empty first loop");
  // Older descriptors without the flag keep the live-particle cap.
  const legacy = kira(true);
  delete legacy.culling.procedural;
  assert.ok(alive(P.create(legacy, 100), 27) > 36);
  // The carry particle needs an enabled module: an enabled module at rate 0 without bursts emits it once,
  // a disabled one never.
  const idle = (enabled, lifetime) => P.create(system({main: {prewarm: true, duration: 10, lifetime: between(lifetime, lifetime),
    maxParticles: 10}, emission: {enabled, rate: constant(0), bursts: []}, culling: procedural}), 3);
  // Born at the end of the first (1 s) step of a 12 s prewarm, it is 11 s old at activation.
  assert.equal(alive(idle(true, 12), 25), 1, "the carry particle of an enabled rate-0 module");
  assert.equal(alive(idle(true, 12), 35), 0);
  assert.equal(alive(idle(false, 12), 1), 0, "a disabled module emits nothing");
  const unflagged = system({main: {prewarm: true, duration: 10, lifetime: between(12, 12), maxParticles: 10},
    emission: {rate: constant(0), bursts: []}, culling: procedural});
  assert.equal(alive(P.create(unflagged, 3), 1), 0, "an old descriptor's empty module counts as disabled");
}

// The particles of a procedural prewarm come from its batches (libunity.so 0x1d7a94), checked against an
// independent model of the client rule, which a unicorn emulation of 0x60fe08 reproduced: per batch, groups
// of four InitialModule lanes draw the lifetime first; a group whose four lanes are all dead stops after that
// one draw and keeps nothing; a kept group draws word, size, rotation and colour and keeps min(left, 4)
// lanes, `left` going down only for kept groups; the ShapeModule lanes then run over the kept particles.
// Motion and time (0x1d7ed8 / 0x1d7fd8): the batch time is the loop time at the end of its step; a kept
// particle's lived offset is (carry + j) * spacing while carry + j is below the batch's rate count, else 0
// (j counting the batch's kept particles, carry + j summed one at a time as the client does); its start
// speed is drawn again from salted(word, 0x96aa4de3) at batch time * (1 / duration), and it moves along its
// box direction by that offset and then by every step after its batch's step.

// A MinMaxCurve as Unity evaluates it (states 0-3), on the native curve emulation.
function curveOf(curve) {
  const keys = rows => native.nativeCurve(rows.map(([time, value, incoming, outgoing]) =>
    [f32(time), f32(value), incoming === null ? null : f32(incoming), outgoing === null ? null : f32(outgoing)]));
  const mix = (a, b, weight) => f32(a + f32(f32(b - a) * weight));
  const scalar = f32(curve.scalar), low = f32(curve.min);
  if (curve.mode === 0) return () => scalar;
  if (curve.mode === 3) return (time, weight) => mix(low, scalar, weight);
  const upper = keys(curve.maxKeys);
  if (curve.mode === 1) return time => f32(upper(time) * scalar);
  const lower = keys(curve.minKeys);
  return (time, weight) => f32(mix(lower(time), upper(time), weight) * scalar);
}

// The prewarm's steps and the loop time at the end of each (0x1d7908 stores it after the clock advance).
function prewarmClock(row, horizon) {
  const cycle = f32(row.main.duration);
  const {steps} = P.prewarmSteps(f32(horizon), cycle);
  let clock = f32(f32(f32(Math.ceil(f32(f32(horizon) / cycle)) * cycle) - f32(horizon)) % cycle);
  const ends = steps.map(dt => {
    const next = f32(clock + dt);
    clock = next > cycle ? f32(next - cycle) : next;
    return clock;
  });
  return {steps, ends};
}

function regenerated(row, seed, batches, {steps, ends}) {
  const lanes = [0, 1, 2, 3].map(lane => ({initial: native.nativeRandom((seed + 367 * lane) >>> 0),
    shape: native.nativeRandom((seed + 367 * lane) >>> 0)}));
  const unit = draw => native.nativeUnit(draw());
  const lifetime = curveOf(row.main.lifetime), speed = curveOf(row.main.speed);
  const cycle = f32(row.main.duration);
  const kept = [];
  let skipped = 0, phantoms = 0;
  for (const batch of batches) {
    const time = f32(ends[batch.step] / cycle), first = kept.length;
    let left = batch.count;
    for (let base = 0; base < batch.count; base += 4) {
      const lives = lanes.map(({initial}) => Math.max(f32(1e-6), lifetime(time, unit(initial))));
      const death = lives.map((life, lane) => f32(f32(life - batch.age) -
        (base + lane < batch.rate ? f32(f32(batch.carry + base + lane) * batch.spacing) : 0)));
      if (death.every(value => value <= 0)) {
        skipped++;
        continue;
      }
      const words = lanes.map(({initial}) => initial());
      for (const {initial} of lanes) {
        initial();  // size
        initial();  // rotation
        initial();  // colour
      }
      for (let lane = 0; lane < Math.min(left, 4); lane++) {
        if (base + lane >= batch.count) phantoms++;
        const inverse = native.nativeInverseLifetime(lives[lane]);
        kept.push({word: words[lane], life: inverse, age: f32(Math.max(0, f32(1 - f32(death[lane] * inverse))) * 100)});
      }
      left -= 4;
    }
    const at = f32(ends[batch.step] * f32(1 / cycle));
    let order = f32(batch.carry);
    for (const entry of kept.slice(first)) {
      entry.unspaced = !(order < batch.rate);
      entry.offset = entry.unspaced ? 0 : f32(order * batch.spacing);
      entry.speed = speed(at, native.nativeUnit(native.nativeRandom((entry.word + 0x96aa4de3) >>> 0)()));
      entry.later = steps.slice(batch.step + 1);
      order = f32(order + 1);
    }
  }
  for (let base = 0; base < kept.length; base += 4) {
    lanes.forEach(({shape}, lane) => {
      const box = row.shape.scale.map(span => f32(f32(unit(shape) - .5) * span));
      const entry = kept[base + lane];
      if (!entry) return;
      entry.position = box;
      // A box emits along +Z: the particle moves by its lived offset, then by each later step.
      entry.velocity = [0, 0, 1].map(axis => f32(axis * entry.speed));
      entry.at = box.slice();
      for (const dt of [entry.offset, ...entry.later]) {
        entry.at = entry.at.map((value, axis) => f32(value + f32(entry.velocity[axis] * dt)));
      }
    });
  }
  return {kept, skipped, phantoms};
}

function testProceduralPrewarmRegeneration() {
  const procedural = {pauses: true, bounds: [-1, -1, -1, 1, 1, 1], uniform: true, procedural: true};
  // Start speeds between two curves rising over the loop: where a batch samples them matters.
  const rising = {mode: 2, scalar: 1, min: 1, minKeys: [[0, 1, 1, 1], [1, 2, 1, 1]], maxKeys: [[0, 2, 2, 2], [1, 4, 2, 2]]};
  const kira = (rate, max) => system({main: {prewarm: true, duration: 50, lifetime: between(1, 10), maxParticles: max,
    speed: rate === 15 ? between(1, 2) : rising}, emission: {enabled: true, rate: constant(rate), bursts: []},
  culling: procedural});
  // A lifetime growing over the loop, 1 s and .2 s steps, and a burst: kept particles past the batch's rate
  // count move from their batch's step end without a spacing offset.
  const burst = system({main: {prewarm: true, duration: 50, maxParticles: 1000, speed: rising,
    lifetime: {mode: 2, scalar: 1, min: 1, minKeys: [[0, 4, 4, 4], [1, 8, 4, 4]], maxKeys: [[0, 6, 6, 6], [1, 12, 6, 6]]}},
  emission: {enabled: true, rate: constant(10), bursts: [{time: 41.5, count: constant(6), cycles: 1, interval: 1,
    probability: 1}]}, culling: procedural});
  let skippedAny = 0, phantomAny = 0, unspacedAny = 0, moved = 0;
  const cases = [[kira(15, 40), 10, 3127128034], [kira(30, 60), 10, 3127128034], [kira(30, 60), 10, 77],
    [kira(30, 60), 10, 2], [kira(15, 40), 10, 5], [burst, 12, 3127128034], [burst, 12, 9]];
  for (const [row, horizon, seed] of cases) {
    const label = `rate ${row.emission.rate.scalar}, seed ${seed}`;
    const stream = P.create(row, seed), clock = prewarmClock(row, horizon);
    assert.ok(stream.batches.length > 3, "the procedural prewarm keeps its batches");
    if (row.main.maxParticles < 1000) {
      assert.equal(stream.batches.reduce((sum, batch) => sum + batch.count, 0), row.main.maxParticles,
        "the batch cap stops at maxParticles");
    }
    for (const batch of stream.batches) {
      assert.equal(batch.time, clock.ends[batch.step], `batch time is the loop time at its step's end (${label})`);
      const age = clock.steps.slice(batch.step + 1).reduce((sum, dt) => f32(sum + dt), 0);
      assert.equal(batch.age, age, `a batch ages by every later step (${label})`);
    }
    const {kept, skipped, phantoms} = regenerated(row, seed, stream.batches, clock);
    skippedAny += skipped;
    phantomAny += phantoms;
    const alive = kept.filter(entry => entry.age <= 100);
    unspacedAny += alive.filter(entry => entry.unspaced).length;
    const atoms = stream.sample(0, 30);
    assert.deepEqual(atoms.map(atom => atom.source.word).sort(), alive.map(entry => entry.word).sort(),
      `kept words (${label})`);
    const byWord = new Map(alive.map(entry => [entry.word, entry]));
    for (const atom of atoms) {
      const expected = byWord.get(atom.source.word);
      assert.equal(atom.source.life, expected.life);
      assert.equal(atom.age, expected.age);
      assert.deepEqual(atom.source.position, expected.position);
      assert.equal(atom.source.speed, expected.speed, `start speed at the batch time (${label})`);
      assert.deepEqual([atom.vx, atom.vy, atom.vz], expected.velocity, `velocity (${label})`);
      assert.deepEqual([atom.x, atom.y, atom.z], expected.at, `position after the lived offset and later steps (${label})`);
      if (atom.z !== atom.source.position[2]) moved++;
    }
  }
  assert.ok(skippedAny > 0 && phantomAny > 0, `cases cover skipped groups (${skippedAny}) and phantom lanes (${phantomAny})`);
  assert.ok(unspacedAny > 0, `cases cover live particles past the rate count (${unspacedAny})`);
  assert.ok(moved > 100, `prewarmed particles moved (${moved})`);
  // A non-procedural prewarm keeps no batches.
  assert.equal(P.create(system({main: {prewarm: true}}), 5).batches, null);
}

// A prewarm whose step plan leaves a remainder, at simulationSpeed .5: 0x1d1e54 divides the prewarm time by
// simulationSpeed, so the leftover is raw time remainder / speed, and the first display frame's update scales
// 1/fps plus that leftover by the speed (0x1ce1f4). Every prewarmed particle ages speed / fps + remainder system
// seconds in the activation frame.
function testPrewarmRemainderAtSimulationSpeed() {
  const lifetime = 1.01, speed = .5, fps = 30;
  const {steps, remainder} = P.prewarmSteps(f32(lifetime), 10);
  assert.ok(steps.length === 50 && remainder > .005 && remainder < f32(.02), `prewarm remainder ${remainder}`);
  const stream = P.create(system({main: {prewarm: true, duration: 10, lifetime: constant(lifetime), maxParticles: 100,
    simulationSpeed: speed}, emission: {enabled: true, rate: constant(20), bursts: []}}), 7);
  const warm = new Map(stream.sample(0, fps).map(atom => [atom.source, atom.age]));
  assert.ok(warm.size > 10, `prewarmed particles ${warm.size}`);
  const kept = stream.sample(1, fps).filter(atom => warm.has(atom.source));
  assert.ok(kept.length > 5, `prewarmed particles alive after the first frame ${kept.length}`);
  // atom.age is percent of the particle's lifetime (source.life holds 1 / lifetime).
  for (const atom of kept) {
    const advanced = (atom.age - warm.get(atom.source)) / (100 * atom.source.life);
    assert.ok(Math.abs(advanced - (speed / fps + remainder)) < 1e-5,
      `first frame system time ${advanced}, expected ${speed / fps + remainder} (not ${speed / fps + speed * remainder})`);
  }
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

async function testUnreproducedSystemsAreRefused() {
  const base = system();
  assert.equal(P.validSimulation(system({main: {rotation3D: true, rotationX: constant(0), rotationY: between(0, 0)}})),
    true, "3D rotation that stays on Z is drawn");
  // X/Y start rotation: Billboards (View, World and Local), on systems culling cannot pause or
  // whose culling box the runtime replays.
  const tumbling = (cullingMode, looping, alignment = 2, mode = 0, culling = undefined) => system({
    main: {rotation3D: true, rotationX: constant(0), rotationY: constant(.35), cullingMode, looping},
    renderer: {...base.renderer, alignment, mode}, ...(culling === undefined ? {} : {culling})});
  for (const alignment of [0, 1, 2]) {
    assert.equal(P.validSimulation(tumbling(3, true, alignment)), true, "billboards turn by X/Y start rotation on their axes");
  }
  for (const mode of [1, 2, 3]) {
    assert.equal(P.validSimulation(tumbling(3, true, 2, mode)), false, "other render modes do not draw X/Y start rotation");
  }
  // A descriptor without the importer's culling field keeps the earlier rule: looping Automatic and
  // Pause culling freeze the clock off screen.
  for (const [cullingMode, looping, valid] of [[0, true, false], [0, false, true], [1, true, true], [2, false, false],
    [3, false, true]]) {
    assert.equal(P.validSimulation(tumbling(cullingMode, looping)), valid,
      `culling ${cullingMode} looping ${looping}: Automatic (looping) and Pause culling freeze the clock off screen`);
  }
  // With it, a system culling pauses is drawn when its culling box is known.
  const box = [-1, -1, -1, 1, 1, 1];
  assert.equal(P.validSimulation(tumbling(0, true, 0, 0, {pauses: true, bounds: box, uniform: true})), true);
  assert.equal(P.validSimulation(tumbling(0, true, 0, 0, {pauses: true, bounds: null, uniform: true})), false);
  assert.equal(P.validSimulation(tumbling(0, true, 0, 0, {pauses: false, bounds: null, uniform: true})), true,
    "a looping Automatic system without the procedural flag is never culled");
  assert.equal(P.validSystem(tumbling(0, true, 0, 0, {pauses: true, bounds: [1, 0, 0, 0, 0, 0], uniform: true}),
    [{}]), false, "an inverted box is rejected");
  const spin = {separateAxes: true, x: constant(0), y: constant(0), z: constant(2)};
  assert.equal(P.validSimulation(system({rotation: spin})), true);
  assert.equal(P.validSimulation(system({rotation: {...spin, y: {mode: 1, scalar: 1, min: 0,
    maxKeys: [[0, 0, 0, 0], [1, 1, 0, 0]]}}})), false);
  const planar = {...base.shape, type: 10, rotation: [90, 15, 0], alignToDirection: true};
  const horizontal = {...base.renderer, mode: 2, alignment: 2};
  assert.equal(P.validSimulation(system({shape: planar, renderer: horizontal})), true);
  assert.equal(P.validSimulation(system({shape: planar, renderer: {...horizontal, mode: 3}})), false);
  assert.equal(P.validSimulation(system({shape: {...planar, rotation: [0, 0, 0]}, renderer: horizontal})), false);
  // BoxShell/BoxEdge and partial radius thickness have no native sampling.
  for (const [type, radiusThickness, valid] of [[15, 1, false], [16, 1, false], [5, 0, true], [0, 1, true],
    [0, 0, false], [10, 0, true], [10, .5, false], [4, .6, false], [12, .3, true]]) {
    assert.equal(P.validSimulation(system({shape: {...base.shape, type, radiusThickness}})), valid, `${type}/${radiusThickness}`);
  }
  assert.equal(P.validSimulation(system({main: {maxParticles: 5000}})), false, "the importer reports larger pools");
  // A transform scale the scaling mode applies is drawn only for Local billboards.
  const root = new T.Group();
  const nodes = [{parent: null, path: "fx", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [2, 2, 2]},
    {parent: 0, path: "fx/a", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]}];
  const descriptor = {schema: 1, textures: [{name: "tex", filter: 1, wrap: [1, 1], levels: [level(4), level(2), level(1)]}],
    templates: [{name: "fx", nodes, systems: [system({node: 1, path: "fx/a/local"}),
      system({node: 1, path: "fx/a/hierarchy", main: {scalingMode: 0}}), system({node: 1, path: "fx/a/shape",
        main: {scalingMode: 2}})]}],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [0, 0, 0], quality: "stage_control", clipSeed: 1}]};
  const controller = await P.apply(T, root, descriptor);
  controller.update(2, {tracks: [{id: "track", events: [{id: "track:0", start: 1, duration: 2}]}],
    quality: {values: {stage_control: true}}});
  assert.deepEqual(controller.inspect().map(row => row.path), ["fx/a/local"],
    "Local scaling ignores the parent; Hierarchy and Shape would scale the particles");
  controller.dispose();
}

async function testTiltedAndLocallyScaledBillboards() {
  // fx_par_so2035_04 light_02: a Local billboard tilted 5 degrees on Y on a 1.1x1.1 node, and a
  // View billboard on a 5x3 node (fx_dis_par_so2035_02 main_dis/cloud_L), both with a culling mode that
  // cannot pause them; the same clouds under looping Automatic culling stay refused.
  const once = {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]};
  const cloud = system({path: "fx/cloud", node: 1, shape: null, emission: once,
    main: {duration: 10, lifetime: constant(10), size: constant(1.2), cullingMode: 1}});
  const paused = system({path: "fx/paused", node: 1, shape: null, emission: once,
    main: {duration: 10, lifetime: constant(10), size: constant(1.2), cullingMode: 0, looping: true}});
  // The same cloud with the importer's culling box (side display: View, tilted 20 degrees on Y).
  const replayed = system({path: "fx/replayed", node: 1, shape: null, emission: once,
    culling: {pauses: true, bounds: [-.852, -.852, -.852, .852, .852, .852], uniform: true},
    main: {duration: 10, lifetime: constant(10), size: constant(1.2), cullingMode: 0, looping: true, rotation3D: true,
      rotationX: constant(0), rotationY: constant(.3490658503988659)}});
  const beam = system({path: "fx/beam", node: 2, shape: null, emission: once, renderer: {...cloud.renderer, alignment: 2},
    main: {duration: 5, lifetime: constant(5), size: constant(17), rotation3D: true, rotationX: constant(.25),
      rotationY: constant(.0872664600610733), cullingMode: 3}});
  const flat = system({path: "fx/flat", node: 3, shape: null, emission: once,
    main: {duration: 5, lifetime: constant(5), size: constant(2)}});
  const turn = [0, Math.sin(Math.PI / 8), 0, Math.cos(Math.PI / 8)];
  const nodes = [{parent: null, path: "fx", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]},
    {parent: 0, path: "fx/cloud", layer: 1, position: [1, 2, 3], rotation: [0, 0, 0, 1], scale: [5, 3, 1]},
    {parent: 0, path: "fx/beam", layer: 1, position: [0, 0, 0], rotation: turn, scale: [1.1, 1.1, 1]},
    {parent: 0, path: "fx/flat", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]}];
  const descriptor = {schema: 1, textures: [{name: "tex", filter: 1, wrap: [1, 1], levels: [level(4), level(2), level(1)]}],
    templates: [{name: "fx", nodes, systems: [cloud, paused, beam, flat, replayed]}],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [0, 0, 0], quality: "stage_display", clipSeed: 1}]};
  assert.equal(P.validDescriptor(descriptor), true);
  const root = new T.Group();
  const controller = await P.apply(T, root, descriptor);
  controller.update(2, {tracks: [{id: "track", events: [{id: "track:0", start: 1, duration: 5}]}],
    quality: {values: {stage_display: true}}});
  const meshes = Object.fromEntries(root.children[0].children.map(mesh => [mesh.name.split("/").pop(), mesh]));
  assert.deepEqual(Object.keys(meshes).sort(), ["beam", "cloud", "flat", "replayed"],
    "Automatic culling would pause fx/paused, whose culling box is unknown");
  assert.deepEqual(controller.inspect().map(row => row.path).sort(), ["fx/beam", "fx/cloud", "fx/flat", "fx/replayed"]);
  // A tilted View quad turns on camera right, up and back (three.js view x, y, z).
  assert.equal(meshes.replayed.material.defines.TILTED, 1);
  assert.equal(meshes.replayed.material.defines.VIEW_FACING, 1);
  assert.match(meshes.replayed.material.vertexShader,
    /uScale \* \(right \* turned\.x \+ up \* turned\.y \+ back \* turned\.z\)/);
  assert.match(meshes.replayed.material.vertexShader, /#elif defined\(VIEW_FACING\)\n\s*point\.xyz \+= turned;/);
  const attribute = (mesh, name) => Array.from(mesh.geometry.getAttribute(name).array.slice(0, 3));
  // Local scaling: the quad keeps its 1.2 units; the node's (5, 3, 1) reaches the shader, which scales
  // the camera axes by it in world components and caps the quad at the limit over 5 (libunity.so
  // 0xd2844, 0xc35c4). The particle sits at the node.
  assert.deepEqual(attribute(meshes.cloud, "particleSize"), [f32(1.2), f32(1.2), f32(1.2)]);
  assert.deepEqual(meshes.cloud.position.toArray(), [-1, 2, 3], "Unity X is reflected like the stage");
  assert.equal(meshes.cloud.material.defines.TILTED, undefined);
  assert.equal(meshes.cloud.material.defines.VIEW_FACING, 1);
  assert.equal(meshes.cloud.material.defines.SCALED, 1);
  assert.deepEqual(meshes.cloud.material.uniforms.uScale.value.toArray(), [5, 3, 1]);
  assert.match(meshes.cloud.material.vertexShader, /sizeLimit \/= max\(uScale\.x, 1\.0e-5\);/);
  assert.match(meshes.cloud.material.vertexShader, /uScale \* \(right \* local\.x \+ up \* local\.y\)/);
  assert.deepEqual(attribute(meshes.beam, "particleSize"), [17, 17, 17]);
  assert.equal(meshes.beam.material.defines.SCALED, 1);
  // The X/Y start angles reach the vertex shader; the Z angle stays the roll.
  assert.equal(meshes.beam.material.defines.TILTED, 1);
  assert.deepEqual(Array.from(meshes.beam.geometry.getAttribute("particleTilt").array.slice(0, 2)),
    [f32(.25), f32(.0872664600610733)]);
  // A Local billboard turns inside the reflected emitter basis, normal included; each axis is then
  // scaled by the node's (1.1, 1.1, 1) in world components, not along the emitter's own axes.
  const close = (actual, expected) => actual.every((value, i) => Math.abs(value - expected[i]) < 1e-6);
  const uniforms = meshes.beam.material.uniforms;
  assert.ok(close(uniforms.uAxisX.value.toArray(), [-Math.SQRT1_2 * 1.1, 0, -Math.SQRT1_2]), uniforms.uAxisX.value.toArray());
  assert.ok(close(uniforms.uAxisY.value.toArray(), [0, 1.1, 0]));
  assert.ok(close(uniforms.uAxisZ.value.toArray(), [-Math.SQRT1_2 * 1.1, 0, Math.SQRT1_2]), uniforms.uAxisZ.value.toArray());
  // Untilted, unscaled systems keep the plain roll shader and unit axes.
  assert.equal(meshes.flat.material.defines.TILTED, undefined);
  assert.equal(meshes.flat.material.defines.SCALED, undefined);
  assert.equal(meshes.flat.material.uniforms.uScale, undefined);
  assert.equal(meshes.flat.geometry.getAttribute("particleTilt"), undefined);
  assert.deepEqual(attribute(meshes.flat, "particleSize"), [2, 2, 2]);
  assert.match(meshes.beam.material.vertexShader, /vec3 turned = vec3\(local.x, cx \* local.y, -sx \* local.y\)/);
  assert.doesNotMatch(meshes.beam.material.vertexShader, /turned\.xy, -turned\.z/, "camera back is +z in three.js view space");
  controller.dispose();
}

async function testPrefabAnimatorCurves() {
  // A prefab Animator moves a local-space emitter and fades its renderer's _TintColor:
  // both are sampled at the clone's state time (time since activation, looped).
  const root = new T.Group();
  const nodes = [{parent: null, path: "fx", layer: 26, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]},
    {parent: 0, path: "fx/ryuu", layer: 26, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]}];
  const animated = system({node: 1, path: "fx/ryuu", layer: 26, shape: null, emission: {rate: constant(0),
    bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]},
    main: {lifetime: constant(100), size: constant(1)}});
  const descriptor = {schema: 1, textures: [{name: "tex", filter: 1, wrap: [1, 1], levels: [level(4), level(2), level(1)]}],
    templates: [{name: "fx", nodes, systems: [animated], animation: {
      clips: [{name: "clip", start: 0, duration: 2, loop: true}],
      channels: [{node: 1, clip: 0, kind: "translation", curves: [["linear", [[0, 0], [2, 4]]], ["constant", 1], ["constant", 0]]},
        {system: 0, clip: 0, kind: "tint", curves: [["constant", 1], ["constant", 1], ["constant", 1],
          ["linear", [[0, 1], [2, 0]]]]}]}}],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [0, 0, 0], quality: "stage_display", clipSeed: 1}]};
  assert.equal(P.validDescriptor(descriptor), true);
  const broken = structuredClone(descriptor);
  broken.templates[0].animation.channels[0].node = 7;
  assert.equal(P.validDescriptor(broken), false);
  assert.equal(P.animatorTime({start: 0, duration: 2, loop: true}, 75, 30), .5);
  assert.equal(P.animatorTime({start: 0, duration: 2, loop: false}, 75, 30), 2);
  const controller = await P.apply(T, root, descriptor);
  const project = {tracks: [{id: "track", events: [{id: "track:0", start: 1, duration: 10}]}],
    quality: {values: {stage_display: true}}};
  controller.update(1 + 29 / 30, project);
  let [state] = controller.inspect(1);
  // 30 frames since activation: state time 1 s, emitter at Unity x = 2 (mirrored), y = 1.
  assert.deepEqual(state.positions[0].map(value => Math.round(value * 1e3) / 1e3), [-2, 1, 0]);
  const mesh = root.children[0].children.find(child => child.name.endsWith("fx/ryuu"));
  assert.ok(Math.abs(mesh.material.uniforms.uTint.value.w - .5) < 1e-6);
  controller.update(1 + 74 / 30, project);
  [state] = controller.inspect(1);
  assert.deepEqual(state.positions[0].map(value => Math.round(value * 1e3) / 1e3), [-1, 1, 0], "the clip loops");
  controller.dispose();
}

// Unity culling replayed from the main camera: an Automatic looping procedural system advances only
// in frames whose previous frame showed its box (libunity.so cull 0x1cc5d8 / uncull 0x1cbd10).
async function testCullingFreezesTheClockOffScreen() {
  // Boxes and planes: the box of a local box under rotation and the scaling-mode scale.
  const turn = [0, Math.sin(Math.PI / 4), 0, Math.cos(Math.PI / 4)];
  const pose = {position: [1, 2, 3], rotation: turn, scale: [2, 2, 2], local: [4, 1, 1]};
  const near = (actual, expected) => actual.every((value, i) => Math.abs(value - expected[i]) < 1e-9);
  const local = {main: {scalingMode: 1}, culling: {uniform: false}};
  // Local mode, 90 degrees about Y: Unity X (scaled 4) turns onto -Z; X is reflected for three.js.
  assert.ok(near(P.worldBox([-1, -1, -1, 1, 1, 1], local, pose), [-2, 1, -1, 0, 3, 7]), P.worldBox([-1, -1, -1, 1, 1, 1], local, pose));
  // View alignment widens every scaled column to the largest scale (libunity.so 0xc0e78).
  assert.ok(near(P.worldBox([-1, -1, -1, 1, 1, 1], {main: {scalingMode: 1}, culling: {uniform: true}}, pose),
    [-5, -2, -1, 3, 6, 7]));
  // Hierarchy mode takes the lossy scale, Shape mode none.
  assert.ok(near(P.worldBox([-1, -1, -1, 1, 1, 1], {main: {scalingMode: 0}, culling: {uniform: false}}, pose), [-3, 0, 1, 1, 4, 5]));
  assert.ok(near(P.worldBox([-1, -1, -1, 1, 1, 1], {main: {scalingMode: 2}, culling: {uniform: false}}, pose), [-2, 1, 2, 0, 3, 4]));
  const camera = new T.PerspectiveCamera(30, 16 / 9, .1, 1000);
  camera.position.set(0, 0, 0);
  camera.lookAt(0, 0, 10);
  camera.updateMatrixWorld();
  const planes = P.cameraPlanes(camera);
  assert.equal(planes.length, 6);
  assert.equal(P.boxVisible([-1, -1, 9, 1, 1, 11], planes), true);
  assert.equal(P.boxVisible([-1, -1, -11, 1, 1, -9], planes), false, "behind the camera");
  assert.equal(P.boxVisible([20, -1, 9, 22, 1, 11], planes), false, "beside the frustum");
  assert.equal(P.boxVisible([-1, -1, 1001, 1, 1, 1003], planes), false, "past the far plane");

  const nodes = [{parent: null, path: "fx", layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1]},
    {parent: 0, path: "fx/cloud", layer: 1, position: [0, 0, 10], rotation: [0, 0, 0, 1], scale: [1, 1, 1]}];
  const once = {rate: constant(0), bursts: [{time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1}]};
  const culled = system({path: "fx/culled", node: 1, shape: null, emission: once,
    culling: {pauses: true, bounds: [-1, -1, -1, 1, 1, 1], uniform: true},
    main: {duration: 10, lifetime: constant(10), size: constant(1), cullingMode: 0, looping: true}});
  const kept = system({path: "fx/kept", node: 1, shape: null, emission: once,
    culling: {pauses: false, bounds: null, uniform: true},
    main: {duration: 10, lifetime: constant(10), size: constant(1), cullingMode: 0, looping: true}});
  const descriptor = {schema: 1, textures: [{name: "tex", filter: 1, wrap: [1, 1], levels: [level(4), level(2), level(1)]}],
    templates: [{name: "fx", nodes, systems: [culled, kept]}],
    cues: [{trackId: "track", eventId: "track:0", template: 0, offset: [0, 0, 0], quality: "stage_display", clipSeed: 1}]};
  assert.equal(P.validDescriptor(descriptor), true);
  const root = new T.Group();
  const controller = await P.apply(T, root, descriptor);
  const event = {id: "track:0", start: 1, duration: 10};
  const project = {tracks: [{id: "track", events: [event]}], quality: {values: {stage_display: true}}};
  // The main camera looks at the cloud before 2 s and from 3 s on, away from it in between.
  const asked = [];
  const view = {key: {}, cameraAt(time) {
    asked.push(time);
    camera.lookAt(0, 0, time >= 2 && time < 3 ? -10 : 10);
    camera.updateMatrixWorld();
    return camera;
  }};
  const rows = () => Object.fromEntries(controller.inspect().map(row => [row.path, row]));
  controller.update(4, project, view);
  const frames = P.activeFrames(event, 4, 30), activated = P.activationFrame(event, 30);
  let seen = 0;
  for (let frame = 1; frame < frames; frame++) {
    const time = (activated + frame - 1) / 30;
    if (time < 2 || time >= 3) seen++;
  }
  // The activation frame always updates; each later frame only after a visible frame.
  let state = rows();
  assert.equal(state["fx/culled"].frames, frames);
  assert.equal(state["fx/culled"].updates, 1 + seen);
  assert.equal(state["fx/culled"].updates, frames - 30, "the 30 frames the camera looked away froze the clock");
  assert.ok(Math.abs(state["fx/culled"].time - (1 + seen) / 30) < 1e-9);
  assert.equal(state["fx/culled"].culled, false);
  assert.equal(state["fx/kept"].updates, frames, "a system culling never pauses keeps the clip clock");
  // In the looked-away second the clock stops at the frame that last saw the cloud.
  controller.update(2.5, project, view);
  state = rows();
  assert.equal(state["fx/culled"].culled, true);
  const stopped = state["fx/culled"].updates;
  controller.update(2.9, project, view);
  assert.equal(rows()["fx/culled"].updates, stopped);
  // Each display frame's camera is asked for once per view key; a new key starts the pass again.
  assert.equal(new Set(asked).size, asked.length);
  controller.update(4, project, {...view, key: {}});
  assert.equal(rows()["fx/culled"].updates, 1 + seen);
  // Without a view (no main camera), the system simulates as if always visible.
  controller.update(4, project);
  assert.equal(rows()["fx/culled"].updates, frames);
  // Several cameras draw the frame (split-screen sub cameras): the box counts as seen when any of them
  // sees it, and a frame no camera draws sees nothing.
  const away = new T.PerspectiveCamera(30, 1, .1, 1000);
  away.lookAt(0, 0, -10);
  away.updateMatrixWorld();
  const split = {key: {}, camerasAt(time) {
    camera.lookAt(0, 0, 10);
    camera.updateMatrixWorld();
    return time >= 2 && time < 3 ? [away, camera] : [away];
  }};
  controller.update(4, project, split);
  let lit = 0;
  for (let frame = 1; frame < frames; frame++) {
    const time = (activated + frame - 1) / 30;
    if (time >= 2 && time < 3) lit++;
  }
  assert.equal(rows()["fx/culled"].updates, 1 + lit);
  controller.update(4, project, {key: {}, camerasAt: () => []});
  assert.equal(rows()["fx/culled"].updates, 1, "no camera draws the frame: the clock stays at the activation frame");
  controller.dispose();
}

(async () => {
  testDrawOrderMatchesNativeLanes();
  testSeekMatchesPlayback();
  testPrewarmedSteadyState();
  testPrewarmActivationBuildUp();
  testProceduralPrewarmRegeneration();
  testPrewarmRemainderAtSimulationSpeed();
  testBurstsCyclesAndExpiry();
  testCurvesAndColorsOverLifetime();
  testOrbitalRadialAndBurstSpread();
  testLimitVelocityDampenAndDrag();
  testActivationTiming();
  testMaterialMappingAndLayers();
  await testApplyDrawsActiveCuesOnly();
  await testUnreproducedSystemsAreRefused();
  await testTiltedAndLocallyScaledBillboards();
  await testPrefabAnimatorCurves();
  await testCullingFreezesTheClockOffScreen();
  console.log("mv_studio_particle_systems_test: ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
