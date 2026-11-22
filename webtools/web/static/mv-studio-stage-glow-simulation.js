(function (global) {
  "use strict";

  const f32 = Math.fround;
  const cycle = f32(.1), rate = 5, maxLife = 8, ageScale = f32(.01);
  const fixedStep = f32(.02), clockBias = f32(.0001), birthBias = f32(1e-6), maxElapsed = 60;
  const velocitySalt = 0xe0fbd834, sizeSalt = 0x8d2c8431, colorSalt = 0x591bc05c;
  const turn = f32(6.283185005187988), colorLimit = 65535;
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const colorLerp = (a, b, weight) => a + ((128 + weight * (b - a)) >> 8);

  function validKeys(keys, count, width) {
    return Array.isArray(keys) && keys.length === count && keys.every((row, index) =>
      Array.isArray(row) && row.length === width && Number.isInteger(row[0]) && row[0] >= 0 && row[0] <= colorLimit &&
      (!index || row[0] > keys[index - 1][0]) && row.slice(1).every(x => Number.isFinite(x) && x >= 0 && x <= 1));
  }

  function supported(row, seed) {
    const start = row?.startColor;
    return row?.rate === rate && Number.isInteger(seed) && seed >= 0 && seed <= 0xffffffff &&
      validKeys(start?.rgb, 4, 4) && validKeys(start?.alpha, 5, 2) &&
      Array.isArray(row.alphaKeys) && row.alphaKeys.length === 2 &&
      validKeys(row.alphaKeys[0], 8, 2) && validKeys(row.alphaKeys[1], 7, 2);
  }

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let reciprocal = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32(2 - value * reciprocal));
    return reciprocal;
  }

  function emission(previous, next, carry) {
    const amount = next < previous ? f32(f32(f32(cycle - previous) * rate) + f32(next * rate)) :
      f32(f32(next - previous) * rate);
    const combined = f32(amount + carry), count = Math.trunc(combined);
    return {count, carry: f32(combined - count), reciprocal: amount < clockBias ? 1 : f32(1 / amount)};
  }

  function startState() {
    let time = 0, phase = 0, carry = 0;
    // The bounds prepass advances an absolute clock before wrapping each endpoint into the cycle.
    while (f32(time + clockBias) < maxLife) {
      time = f32(time + fixedStep);
      const next = f32(time % cycle);
      ({carry} = emission(phase, next, carry));
      phase = next;
    }
    return {frame: 0, clock: 0, carry: f32(f32(1 - carry) + clockBias), group: 0, active: []};
  }

  function compileSizeCurve(values, slope) {
    // The source authoring has five quarter-cycle knots and only the two
    // outer tangents. Cache the native unweighted Hermite coefficients.
    const span = .25, inverseSquared = 16;
    return values.slice(0, -1).map((value, index) => {
      const delta = f32(values[index + 1] - value);
      const outSlope = index === 0 ? slope : 0, inSlope = index === 3 ? -slope : 0;
      const out = f32(span * outSlope), incoming = f32(span * inSlope);
      const a = f32(f32(inverseSquared * f32(f32(f32(out + incoming) - delta) - delta)) / span);
      const b = f32(inverseSquared * f32(f32(f32(f32(delta + delta) + delta) - out - out) - incoming));
      return [a, b, outSlope, value];
    });
  }

  const small = f32(.8), slope = f32(.7999999523162842);
  const minSize = compileSizeCurve([small, 1, small, 1, small], slope);
  const maxSize = compileSizeCurve([1, small, 1, small, 1], -slope);

  function sizeAt(phase, weight) {
    if (phase >= 1) return lerp(small, 1, weight);
    const index = Math.floor(phase * 4), t = f32(phase - index * .25);
    const evaluate = ([a, b, c, d]) => f32(d + f32(t * f32(c + f32(t * f32(b + f32(t * a))))));
    return lerp(evaluate(minSize[index]), evaluate(maxSize[index]), weight);
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
    if (!particles || !supported(row, seed)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeColorAtTime} = particles;
    const {startColor, alphaKeys} = row;
    const palettes = alphaKeys.map(keys => ({start: [255, 255, 255, 255],
      keys: keys.map(([stamp, alpha]) => [f32(stamp / colorLimit), 255, 255, 255, byte(alpha)])}));
    const streams = Array.from({length: 4}, (_, index) => {
      const word = (seed + 367 * index) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [], checkpointInterval = 2 * nativeStepRate;
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const cos = 5.960464477539063e-8, sin = .9999999403953552;
    const xx = f32(f32(2.98) * cos), xz = f32(f32(11.69) * sin);
    const zx = f32(f32(-2.98) * sin), zz = f32(f32(11.69) * cos);
    const packedRange = f32(.3);

    function birth({initial, shape}) {
      const word = initial(), life = inverse(lerp(6, maxLife, nativeUnit(initial())));
      const width = lerp(3, 1.5, nativeUnit(initial())), height = lerp(3, 1.5, nativeUnit(initial()));
      initial(); // Anisotropic InitialModule still draws the fixed zero depth.
      const roll = lerp(turn, 0, nativeUnit(initial())), stamp = f32(nativeUnit(initial()) * colorLimit);
      const stepped = keys => (keys.find(key => key[0] >= stamp) || keys[keys.length - 1]).slice(1).map(byte);
      const color = [...stepped(startColor.rgb), ...stepped(startColor.alpha)];
      const sx = f32(nativeUnit(shape()) - .5), sy = f32(nativeUnit(shape()) - .5), sz = f32(nativeUnit(shape()) - .5);
      shape(); shape(); // Random direction reserves two words even when start speed is zero.
      const x = f32(f32(sx * xx) + f32(sz * xz)), y = f32(sy * f32(2.6)), z = f32(f32(sx * zx) + f32(sz * zz));
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      const vx = lerp(-packedRange, packedRange, nativeUnit(velocity()));
      const vy = lerp(-packedRange, packedRange, nativeUnit(velocity()));
      const colorWeight = Math.trunc(f32(salted(word, colorSalt) * 255));
      return {x, y, z, vx, vy, life, width, height, roll, color, colorWeight, sizeWeight: salted(word, sizeSalt)};
    }

    function advance(atom, dt) {
      const {source} = atom;
      atom.x = f32(atom.x + f32(source.vx * dt));
      atom.y = f32(atom.y + f32(source.vy * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * source.life));
    }

    function step(state, dt) {
      const {active} = state;
      for (const atom of active) advance(atom, dt);
      cull(active);
      const previous = state.clock, next = f32(previous + dt);
      state.clock = next > cycle ? f32(next - cycle) : next;
      const previousTime = dt >= cycle ? f32(previous + birthBias) : previous;
      const {count, carry, reciprocal} = emission(previousTime, state.clock, state.carry);
      state.carry = carry;
      if (!count) return;
      if (state.group === groups.length) groups.push(streams.map(birth));
      const source = groups[state.group++][0];
      const atom = {source, x: source.x, y: source.y, age: 0};
      const fraction = Math.max(birthBias, Math.min(1, f32(carry * reciprocal)));
      advance(atom, f32(dt * fraction));
      active.push(atom);
    }

    function copy(state) {
      return {...state, active: state.active.map(atom => ({...atom}))};
    }

    const warm = startState(), layouts = new Map();
    let remainder = maxLife;
    for (let dt = cycle; remainder >= dt; dt = remainder > 5 ? cycle : fixedStep) {
      step(warm, dt);
      remainder = f32(remainder - dt);
    }

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
        step(state, nativeStep);
        state.frame++;
        if (state.frame === grouped && residue >= birthBias) step(state, residue);
        if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(copy(state));
      }
      const remaining = atom => f32(f32(100 - atom.age) / atom.source.life);
      const ordered = [...state.active].sort((a, b) => remaining(a) - remaining(b));
      for (const atom of ordered) {
        const {source} = atom, age = f32(atom.age * ageScale), scale = sizeAt(age, source.sizeWeight);
        const lower = Math.round(nativeColorAtTime(palettes[0], age)[3] * 255);
        const upper = Math.round(nativeColorAtTime(palettes[1], age)[3] * 255);
        const alpha = Math.floor((source.color[3] * colorLerp(lower, upper, source.colorWeight) + 127) / 255);
        emit(-atom.x, atom.y, source.z, f32(source.width * scale), f32(source.height * scale), source.roll,
          source.color[0], source.color[1], source.color[2], alpha);
      }
    }};
  }

  global.MVStudioStageGlowSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
