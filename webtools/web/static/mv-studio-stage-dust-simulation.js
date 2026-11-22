(function (global) {
  "use strict";

  const f32 = Math.fround;
  const cycle = 5, gravityMagnitude = f32(9.81), ageScale = f32(.01);
  const birthBias = f32(1e-6), clockBias = f32(.0001), velocitySalt = 0xe0fbd834;
  const maxElapsed = 120;
  // The source emitter's +90° X quaternion is used as serialized by Unity.
  const quarterTurnX = f32(.7071068286895752);
  const gravityY = f32(2 * quarterTurnX * quarterTurnX - 1);
  const gravityZ = f32(2 * quarterTurnX * quarterTurnX);
  const range = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
  const vector = (values, length, low, high) => Array.isArray(values) && values.length === length &&
    values.every(value => range(value, low, high));
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));

  function supported(row, seed) {
    if (row?.duration !== cycle || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff ||
        !range(row.rate, 0, 120) || f32(row.rate) <= 0 || !range(row.gravity, 0, 1) ||
        !Number.isInteger(row.maxParticles) || !range(row.maxParticles, 1, 512) ||
        !vector(row.lifetime, 2, .1, 5) || !vector(row.size, 2, 0, 20) ||
        !vector(row.shapeScale, 3, 0, 100) || !vector(row.startColor, 4, 0, 1) ||
        !range(row.sizeMultiplier, 0, 16) || !Array.isArray(row.velocity) || row.velocity.length !== 3 ||
        !row.velocity.every(axis => Array.isArray(axis) && axis.length === 5 &&
          vector(axis.slice(0, 4), 4, -16, 16) && range(axis[4], 0, 4))) return false;
    const keys = row.sizeKeys;
    return Array.isArray(keys) && keys.length >= 2 && keys.length <= 16 &&
      keys[0]?.[0] === 0 && keys.at(-1)?.[0] === 1 &&
      keys.every((key, i) => Array.isArray(key) && key.length === 4 && range(key[0], 0, 1) &&
        (!i || f32(key[0]) > f32(keys[i - 1][0])) && range(key[1], 0, 16) &&
        key.slice(2).every(slope => slope === null || range(slope, -4096, 4096)));
  }

  function inverseLifetime(value) {
    // Native reciprocal estimate with two Newton updates.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let reciprocal = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32(2 - value * reciprocal));
    return reciprocal;
  }

  function cull(active) {
    for (let first = 0; first < active.length;) {
      let removed = false;
      for (let index = Math.min(first + 3, active.length - 1); index >= first; index--) {
        if (active[index].age <= 100) continue;
        const tail = active.pop();
        if (index < active.length) active[index] = tail;
        removed = true;
      }
      if (!removed) first += 4;
    }
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles;
    if (!particles?.nativeCurve || !supported(row, seed)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeCurve} = particles;
    const rate = f32(row.rate), gravity = f32(row.gravity), multiplier = f32(row.sizeMultiplier);
    const [lifeMin, lifeMax] = row.lifetime.map(f32), [sizeMin, sizeMax] = row.size.map(f32);
    const [sx, sy, sz] = row.shapeScale.map(f32), [r, g, b, a] = row.startColor.map(byte);
    const sizeAt = nativeCurve(row.sizeKeys.map(([time, value, incoming, outgoing]) =>
      [f32(time), f32(value), incoming === null ? null : f32(incoming), outgoing === null ? null : f32(outgoing)]));
    const velocity = row.velocity.map(values => {
      const [min0, min1, max0, max1, scale] = values.map(f32);
      const curve = (first, last) => {
        // Unity scales these optimized zero-tangent coefficients before sampling.
        const difference = f32(last - first);
        const a = f32(f32(-2 * difference) * scale), b = f32(f32(3 * difference) * scale), d = f32(first * scale);
        return phase => f32(d + f32(phase * f32(phase * f32(b + f32(phase * a)))));
      };
      const min = curve(min0, min1), max = curve(max0, max1);
      const sample = (phase, unit) => lerp(min(phase), max(phase), unit);
      return {sample, constant: min0 === min1 && max0 === max1};
    });
    const lanes = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [], checkpointInterval = 2 * nativeStepRate;
    let state = {frame: 0, group: 0, phase: 0, carry: 0, active: []};
    const checkpoints = [state];

    function birth({initial, shape}) {
      const word = initial();
      const life = inverseLifetime(lerp(lifeMin, lifeMax, nativeUnit(initial())));
      const width = lerp(sizeMin, sizeMax, nativeUnit(initial()));
      initial(); initial(); // Fixed starting roll and color still consume stream words.
      const box = span => f32(f32(nativeUnit(shape()) - .5) * span);
      const stream = nativeRandom((word + velocitySalt) >>> 0);
      const weight = [nativeUnit(stream()), nativeUnit(stream()), nativeUnit(stream())];
      const fixed = velocity.map((axis, i) => axis.constant ? axis.sample(0, weight[i]) : null);
      return {life, width, x: box(sx), y: box(sy), z: box(sz), weight, fixed};
    }

    const gravityStep = dt => f32(f32(gravityMagnitude * dt) * gravity);
    const ordinaryGravity = gravityStep(nativeStep);

    function advance(atom, dt, force) {
      const {source, age} = atom;
      const phase = f32(age * ageScale);
      const dx = source.fixed[0] ?? velocity[0].sample(phase, source.weight[0]);
      const dy = source.fixed[1] ?? velocity[1].sample(phase, source.weight[1]);
      const dz = source.fixed[2] ?? velocity[2].sample(phase, source.weight[2]);
      atom.vy = f32(atom.vy + f32(force * gravityY));
      atom.vz = f32(atom.vz + f32(force * gravityZ));
      atom.x = f32(atom.x + f32(dx * dt));
      atom.y = f32(atom.y + f32(f32(atom.vy + dy) * dt));
      atom.z = f32(atom.z + f32(f32(atom.vz + dz) * dt));
      atom.age = f32(age + f32(f32(dt * 100) * source.life));
    }

    function step() {
      const {active, phase: previous} = state;
      for (const atom of active) advance(atom, nativeStep, ordinaryGravity);
      cull(active);
      const next = f32(previous + nativeStep);
      state.phase = next > cycle ? f32(next - cycle) : next;
      const amount = next > cycle
        ? f32(f32(f32(cycle - previous) * rate) + f32(state.phase * rate))
        : f32(f32(next - previous) * rate);
      const total = f32(amount + state.carry), requested = Math.trunc(total);
      state.carry = f32(total - requested);
      const count = Math.min(requested, row.maxParticles - active.length);
      if (!count) return;
      if (state.group === groups.length) groups.push(lanes.map(birth));
      const sources = groups[state.group++], births = [];
      const inverse = amount < clockBias ? 1 : f32(1 / amount);
      for (let lane = 0; lane < count; lane++) {
        const source = sources[lane], {x, y, z} = source;
        const fraction = Math.min(1, Math.max(birthBias, f32(f32(lane + state.carry) * inverse)));
        const within = f32(nativeStep * fraction);
        const atom = {source, x, y, z, vy: 0, vz: 0, age: 0};
        advance(atom, within, gravityStep(within));
        births.push(atom);
      }
      // Native SoA storage fills the existing trailing SIMD lanes from the new batch tail.
      const remaining = (4 - active.length % 4) % 4;
      const pivot = remaining ? Math.max(0, count - remaining) : 0;
      for (let i = 0; i < count; i++) active.push(births[(pivot + i) % count]);
    }

    const clone = value => ({...value, active: value.active.map(atom => ({...atom}))});
    state = clone(state);
    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > maxElapsed) return;
      const saved = checkpoints[Math.min(checkpoints.length - 1, Math.floor(target / checkpointInterval))];
      if (target < state.frame || saved.frame > state.frame) state = clone(saved);
      while (state.frame < target) {
        step();
        state.frame++;
        if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(clone(state));
      }
      for (const {source, x, y, z, age} of state.active) {
        const size = Math.max(0, f32(sizeAt(f32(age * ageScale)) * multiplier));
        emit(-x, y, z, f32(source.width * size), r, g, b, a);
      }
    }};
  }

  global.MVStudioStageDustSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
