(function (global) {
  "use strict";

  const f32 = Math.fround;
  const cycle = 5, life = f32(1 / cycle), warmStep = f32(.02), maxElapsed = 60;
  const clockBias = f32(.0001), birthBias = f32(1e-6), ageScale = f32(.01);
  const inverseTurn = f32(1 / (2 * Math.PI));
  const rotationCos = 2 ** -24, rotationSin = 1 - rotationCos;
  const alphaSalt = 0x591bc05c, atlasSalt = 0x13740583, stampMax = 65535;
  const white = [255, 255, 255, 255];
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));

  function validKeys(rows, width) {
    return Array.isArray(rows) && rows.length >= 2 && rows.length <= 8 && rows[0]?.[0] === 0 &&
      rows.at(-1)?.[0] === stampMax && rows.every((key, i) =>
        Array.isArray(key) && key.length === width && Number.isInteger(key[0]) &&
        (!i || key[0] > rows[i - 1][0]) && key.slice(1).every(x => Number.isFinite(x) && x >= 0 && x <= 1));
  }

  function validVector(values, length, minimum) {
    return Array.isArray(values) && values.length === length &&
      values.every(value => typeof value === "number" && Number.isFinite(f32(value)) && value >= minimum);
  }

  function colorAt(keys, stamp) {
    const next = keys.findIndex(key => key[0] > stamp);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const mix = left === right ? 0 : f32(f32(stamp - left[0]) / (right[0] - left[0]));
    return left.slice(1).map((value, i) => byte(lerp(value, right[i + 1], mix)));
  }

  function emission(previous, next, carry, rate) {
    const amount = next < previous ? f32(f32(f32(cycle - previous) * rate) + f32(next * rate)) :
      f32(f32(next - previous) * rate);
    const total = f32(amount + carry), count = Math.trunc(total);
    return {count, carry: f32(total - count), inverse: amount < clockBias ? 1 : f32(1 / amount)};
  }

  function prepass(rate) {
    let time = 0, phase = 0, carry = 0;
    // The bounds expansion advances an absolute clock before wrapping each endpoint.
    while (f32(time + clockBias) < cycle) {
      time = f32(time + warmStep);
      const next = f32(time % cycle);
      ({carry} = emission(phase, next, carry, rate));
      phase = next;
    }
    return f32(f32(1 - carry) + clockBias);
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
    if (row?.cycle !== cycle || row?.lifetime !== cycle || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff ||
        !Number.isFinite(row.rate) || f32(row.rate) <= 0 || row.rate > 30 ||
        !Number.isFinite(row.arcDegrees) || f32(row.arcDegrees) <= 0 || row.arcDegrees > 360 ||
        !validVector(row.size, 2, 0) || !validVector(row.shapeScale, 3, 0) ||
        !validKeys(row.startColor?.rgb, 4) || !validKeys(row.startColor?.alpha, 2) || !Array.isArray(row.alphaKeys) ||
        row.alphaKeys.length !== 2 || !row.alphaKeys.every(keys => validKeys(keys, 2))) return null;
    const particles = global.MVStudioStageParticles;
    if (typeof particles?.nativeHemispherePosition !== "function") return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeColorAtTime,
      nativeHemispherePosition} = particles;
    const rate = f32(row.rate);
    const [minSize, maxSize] = row.size.map(f32);
    const [sx, sy, sz] = row.shapeScale.map(f32);
    const yy = f32(sy * rotationCos), yz = f32(sz * rotationSin);
    const zy = f32(-sy * rotationSin), zz = f32(sz * rotationCos);
    const arcRadians = f32(f32(f32(f32(row.arcDegrees) / 360) * 2) * f32(Math.PI));
    const unitScale = [1, 1, 1], layouts = new Map(), births = [];
    const initial = nativeRandom(seed), shape = nativeRandom(seed);
    const gradients = row.alphaKeys.map(keys => ({start: white, keys: keys.map(([stamp, a]) =>
      [f32(stamp / stampMax), 255, 255, 255, byte(a)])}));

    function birth() {
      // At these rates each native update emits at most one particle. The
      // padded SIMD lanes advance their own independent streams.
      const word = initial();
      initial(); // Fixed lifetime.
      const width = lerp(minSize, maxSize, nativeUnit(initial()));
      initial(); // Fixed Z rotation.
      const stamp = f32(nativeUnit(initial()) * stampMax);
      const rgb = colorAt(row.startColor.rgb, stamp), [alpha] = colorAt(row.startColor.alpha, stamp);
      const turns = f32(f32(arcRadians * nativeUnit(shape())) * inverseTurn);
      const [x, y, z] = nativeHemispherePosition(turns, nativeUnit(shape()), nativeUnit(shape()), 1, unitScale);
      const sample = salt => nativeUnit(nativeRandom((word + salt) >>> 0)());
      return {x: -f32(x * sx), y: f32(f32(y * yy) + f32(z * yz)), z: f32(f32(y * zy) + f32(z * zz)),
        width, rgb, alpha, mix: Math.trunc(f32(sample(alphaSalt) * 255)),
        tile: Math.floor(f32(2 * f32(sample(atlasSalt) * .75)))};
    }

    function advance(state, dt) {
      const {active} = state;
      const increment = f32(f32(dt * 100) * life);
      for (const atom of active) atom.age = f32(atom.age + increment);
      cull(active);
      const previous = state.clock, next = f32(previous + dt);
      state.clock = next > cycle ? f32(next - cycle) : next;
      const {count, carry, inverse} = emission(previous, state.clock, state.carry, rate);
      state.carry = carry;
      if (count === 0) return;
      if (state.group === births.length) births.push(birth());
      const portion = Math.max(birthBias, Math.min(1, f32(carry * inverse)));
      active.push({particle: births[state.group++], age: f32(f32(f32(dt * portion) * 100) * life)});
    }

    function copy(state) {
      return {...state, active: state.active.map(atom => ({...atom}))};
    }

    const warm = {clock: 0, carry: prepass(rate), frame: 0, group: 0, active: []};
    let remainder = cycle;
    while (remainder >= warmStep) {
      advance(warm, warmStep);
      remainder = f32(remainder - warmStep);
    }
    const checkpointInterval = 2 * nativeStepRate;

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      let residue = f32(f32(1 / fps) + remainder);
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const result = {state: copy(warm), checkpoints: [warm], grouped, residue};
      layouts.set(fps, result);
      return result;
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > maxElapsed) return;
      const entry = layouts.get(fps) || layout(fps);
      const {checkpoints, grouped, residue} = entry;
      const saved = Math.min(checkpoints.length - 1, Math.floor(target / checkpointInterval));
      if (target < entry.state.frame || checkpoints[saved].frame > entry.state.frame) entry.state = copy(checkpoints[saved]);
      const {state} = entry;
      while (state.frame < target) {
        advance(state, nativeStep);
        state.frame++;
        if (state.frame === grouped && residue >= birthBias) advance(state, residue);
        if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(copy(state));
      }
      for (const {particle, age} of state.active) {
        const phase = f32(age * ageScale);
        const low = Math.round(nativeColorAtTime(gradients[0], phase)[3] * 255);
        const high = Math.round(nativeColorAtTime(gradients[1], phase)[3] * 255);
        const opacity = low + ((128 + particle.mix * (high - low)) >> 8);
        const alpha = Math.floor((particle.alpha * opacity + 127) / 255);
        emit(particle.x, particle.y, particle.z, particle.width, ...particle.rgb, alpha, particle.tile);
      }
    }};
  }

  global.MVStudioStageLensSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
