(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 3279275062, rate = 3, cycle = 10, horizon = 8, prepassCarry = .9999798536300659;
  const fixedStep = f32(.02), warmStep = f32(.2), birthBias = f32(1e-6), rateBias = f32(.0001);
  const rollRange = f32(.7853981256484985), initialX = f32(1.570796251296997), ageScale = f32(.01);
  const tau = f32(2 * Math.PI), turnsPerRadian = f32(1 / (2 * Math.PI));
  const shapeY = f32(4 * 5.960464477539063e-8), shapeZ = f32(4 * .9999999403953552);
  const fadeIn = f32(6554 / 65535), fadeOut = f32(58982 / 65535);
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const fading = [[0, 0], [6554, 1], [58982, 1], [65535, 0]];

  function supported(row) {
    return row?.role === "floor" && row.seed === seed && row.rate === rate &&
      Array.isArray(row.startColors) && row.startColors.length === 2 && row.startColors.every(color =>
        Array.isArray(color) && color.length === 4 && color.every(value => Number.isFinite(value) && value >= 0 && value <= 1) &&
        color[3] === 1) &&
      Array.isArray(row.alphaKeys) && row.alphaKeys.length === fading.length && row.alphaKeys.every((key, i) =>
        Array.isArray(key) && key.length === 2 && key[0] === fading[i][0] && key[1] === fading[i][1]);
  }

  function inverse(value) {
    // Native NEON reciprocal estimate followed by two refinements.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  const invFadeIn = inverse(fadeIn), invFadeOut = inverse(f32(1 - fadeOut));

  function opacity(phase) {
    if (phase > fadeIn && phase <= fadeOut) return 255;
    const rising = phase <= fadeIn;
    const distance = rising ? phase : f32(phase - fadeOut);
    const weight = Math.trunc(f32(f32(distance * (rising ? invFadeIn : invFadeOut)) * 255));
    return rising ? (128 + 255 * weight) >> 8 : 255 + ((128 - 255 * weight) >> 8);
  }

  function circleRadius(value) {
    if (!value) return 0;
    // The native Circle kernel computes its square root with FRSQRTE/FRSQRTS.
    const scale = 2 ** -Math.floor(Math.log2(value) / 2), mantissa = value * scale * scale;
    const bins = mantissa < 2 ? 128 : 64;
    const midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let reciprocal = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return f32(value * reciprocal);
  }

  function cosine(turns) {
    const offset = turns < 0 ? -8388608 : 8388608;
    const nearest = f32(f32(turns + offset) - offset);
    const triangle = f32(.25 - Math.abs(f32(turns - nearest)));
    const square = f32(triangle * triangle), fourth = f32(square * square);
    const low = f32(6.283185005187988 + f32(square * -41.34165954589844));
    const high = f32(81.60182189941406 + f32(square * -76.56861877441406));
    return f32(triangle * f32(f32(low + f32(fourth * high)) + f32(f32(fourth * fourth) * 39.65703201293945)));
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

  function copy(state) {
    return {...state, active: state.active.map(atom => ({...atom}))};
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate} = particles;
    // At 3 births/second even the .2-second warm step can emit at most one.
    // Only lane zero can ever enter the live pool for this source.
    const initial = nativeRandom(seed), shape = nativeRandom(seed);
    const births = [], layouts = new Map();
    const [low, high] = row.startColors;

    function birth() {
      const word = initial(), life = inverse(lerp(5, horizon, nativeUnit(initial())));
      const size = lerp(f32(1.2), f32(.9), nativeUnit(initial()));
      initial(); initial(); initial(); // Fixed X, Y and Z starting rotations.
      const colorWeight = nativeUnit(initial());
      const rgb = [0, 1, 2].map(channel => byte(lerp(low[channel], high[channel], colorWeight)));
      const angle = f32(f32(tau * nativeUnit(shape())) * turnsPerRadian);
      const radius = circleRadius(nativeUnit(shape()));
      const x = f32(f32(-cosine(angle) * radius) * 6);
      const y = f32(cosine(f32(angle - .25)) * radius);
      const spinWeight = nativeUnit(nativeRandom((word + 0x6aed452e) >>> 0)());
      const sign = nativeUnit(nativeRandom((word + 0xff2bb1a4) >>> 0)()) > 0 ? 1 : -1;
      const spin = f32(sign * lerp(rollRange, -rollRange, spinWeight));
      return {x, y: f32(y * shapeY), z: f32(y * shapeZ), life, size, spin, rgb};
    }

    function advance(atom, dt) {
      atom.roll = f32(atom.roll + f32(atom.source.spin * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * atom.source.life));
    }

    function step(state, dt) {
      const active = state.active;
      for (const atom of active) advance(atom, dt);
      cull(active);
      const previous = state.clock, next = f32(previous + dt), wrapped = next > cycle;
      state.clock = wrapped ? f32(next - cycle) : next;
      const amount = wrapped ? f32(f32(f32(cycle - previous) * rate) + f32(state.clock * rate)) :
        f32(f32(state.clock - previous) * rate);
      const combined = f32(amount + state.carry), count = Math.trunc(combined);
      state.carry = f32(combined - count);
      if (!count) return;
      if (state.group === births.length) births.push(birth());
      const fraction = f32(state.carry * (amount >= rateBias ? f32(1 / amount) : 1));
      const atom = {source: births[state.group++], age: 0, roll: 0};
      advance(atom, f32(dt * Math.min(1, Math.max(birthBias, fraction))));
      active.push(atom);
    }

    const warmed = {frame: 0, clock: cycle - horizon, carry: prepassCarry, group: 0, active: []};
    let remainder = horizon;
    // The bounds prepass seeds the rate carry. Regular prewarm uses .2s
    // while more than five seconds remain, then switches to .02s.
    for (let dt = warmStep; remainder >= dt; dt = remainder > 5 ? warmStep : fixedStep) {
      step(warmed, dt);
      remainder = f32(remainder - dt);
    }

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      let residue = f32(f32(1 / fps) + remainder);
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const entry = {state: copy(warmed), checkpoints: [warmed], grouped, residue};
      layouts.set(fps, entry);
      return entry;
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > 60) return;
      const entry = layouts.get(fps) || layout(fps), {checkpoints, grouped, residue} = entry;
      const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
      if (target < entry.state.frame || checkpoints[index].frame > entry.state.frame) entry.state = copy(checkpoints[index]);
      const state = entry.state;
      while (state.frame < target) {
        step(state, nativeStep);
        state.frame++;
        if (state.frame === grouped && residue >= birthBias) step(state, residue);
        if (state.frame === checkpoints.length * nativeStepRate) checkpoints.push(copy(state));
      }
      for (const atom of state.active) {
        const {x, y, z, size, rgb} = atom.source;
        emit(x, y, z, size, size, size, initialX, 0, atom.roll, ...rgb, opacity(f32(atom.age * ageScale)));
      }
    }};
  }

  global.MVStudioConfettiFloorSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
