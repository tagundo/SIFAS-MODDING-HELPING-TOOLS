(function (global) {
  "use strict";

  const f32 = Math.fround;
  const cycle = 10, fixedStep = f32(.02), birthBias = f32(1e-6);
  const rollRange = f32(.7853981256484985), initialX = f32(1.570796251296997);
  const ageScale = f32(.01), shapeWidth = f32(8.77);
  // Entries of the native Circle's precomputed scale-and-rotation matrix.
  const shapeY = f32(f32(4.9) * 5.960464477539063e-8);
  const shapeZ = f32(f32(4.9) * .9999999403953552);
  const profiles = {
    alpha: {seed: 3279275062, rate: 7, horizon: 5, minWidth: 1, height: 1, burst: 10, carry: .9997996091842651},
    add: {seed: 363848346, rate: 3, horizon: 4, minWidth: f32(.8), height: f32(.8), burst: 0, carry: .999968409538269},
  };
  const lerp = (min, max, weight) => f32(min + f32(f32(max - min) * weight));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));

  function checkedKeys(rows, count, width) {
    return Array.isArray(rows) && rows.length === count && rows.every((row, i) =>
      Array.isArray(row) && row.length === width && Number.isInteger(row[0]) && row[0] >= 0 && row[0] <= 65535 &&
      (!i || row[0] > rows[i - 1][0]) && row.slice(1).every(value => Number.isFinite(value) && value >= 0 && value <= 1));
  }

  function supported(row) {
    if (row?.profile !== "07" || (row.role !== "alpha" && row.role !== "add")) return false;
    const {position, rotation, startColor, alphaKeys} = row, profile = profiles[row.role];
    return row.seed === profile.seed && row.rate === profile.rate &&
      Array.isArray(position) && position.length === 3 && position[0] === 0 && position[1] === f32(.06) && position[2] === 0 &&
      Array.isArray(rotation) && rotation.length === 4 && rotation[0] === 0 && rotation[1] === 0 && rotation[2] === 0 && rotation[3] === 1 &&
      checkedKeys(startColor?.rgb, 3, 4) && checkedKeys(startColor?.alpha, 2, 2) && checkedKeys(alphaKeys, 4, 2);
  }

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function nativeRadius(value) {
    // FRSQRTE followed by two FRSQRTS refinements in Unity's Circle kernel.
    if (!value) return 0;
    const scale = 2 ** -Math.floor(Math.log2(value) / 2), mantissa = value * scale * scale;
    const bins = mantissa < 2 ? 128 : 64;
    const midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let reciprocal = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return f32(value * reciprocal);
  }

  function nativeCosine(turns) {
    const offset = turns < 0 ? -8388608 : 8388608;
    const nearest = f32(f32(turns + offset) - offset);
    const reduced = f32(.25 - Math.abs(f32(turns - nearest)));
    const square = f32(reduced * reduced), fourth = f32(square * square);
    const low = f32(6.283185005187988 + f32(square * -41.34165954589844));
    const high = f32(81.60182189941406 + f32(square * -76.56861877441406));
    return f32(reduced * f32(f32(low + f32(fourth * high)) + f32(f32(fourth * fourth) * 39.65703201293945)));
  }

  function palette(keys, stamp) {
    const next = keys.findIndex(row => row[0] > stamp);
    const b = keys[next < 0 ? keys.length - 1 : next], a = next > 0 ? keys[next - 1] : b;
    const weight = a === b ? 0 : f32(f32(stamp - a[0]) / (b[0] - a[0]));
    return a.slice(1).map((value, i) => byte(lerp(value, b[i + 1], weight)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeColorAtTime} = particles;
    const {seed, rate, horizon, minWidth, height, burst} = profiles[row.role];
    const {startColor, alphaKeys, position} = row;
    const keys = alphaKeys.map(([phase, alpha]) => [f32(phase / 65535), 255, 255, 255, byte(alpha)]);
    const streams = Array.from({length: 4}, (_, i) => {
      const word = (seed + 367 * i) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [];
    let frame = 0, clock = cycle - horizon, carry = profiles[row.role].carry, group = 0, active = [];
    let displayRate, firstFrameRemainder = 0, checkpoints;

    function drawBirth({initial, shape}) {
      const word = initial(), life = inverse(lerp(4, horizon, nativeUnit(initial())));
      const width = lerp(minWidth, .5, nativeUnit(initial()));
      initial(); // Fixed native Y size consumes its own stream value.
      const depth = lerp(.5, f32(.3), nativeUnit(initial()));
      initial(); initial(); initial(); // Three fixed Euler angle channels.
      const stamp = f32(nativeUnit(initial()) * 65535);
      const angle = f32(f32(f32(2 * Math.PI) * nativeUnit(shape())) * f32(1 / (2 * Math.PI)));
      const radius = nativeRadius(nativeUnit(shape()));
      const x = f32(f32(-nativeCosine(angle) * radius) * shapeWidth);
      const circleY = f32(nativeCosine(f32(angle - .25)) * radius);
      const y = f32(position[1] + f32(circleY * shapeY)), z = f32(circleY * shapeZ);
      const rollDraw = nativeUnit(nativeRandom((word + 0x6aed452e) >>> 0)());
      const sign = nativeUnit(nativeRandom((word + 0xff2bb1a4) >>> 0)()) > 0 ? 1 : -1;
      const spin = f32(sign * lerp(rollRange, -rollRange, rollDraw));
      const start = [...palette(startColor.rgb, stamp), ...palette(startColor.alpha, stamp)];
      return {x, y, z, life, width, height, depth, spin, color: {start, keys}};
    }

    function advance(atom, dt) {
      atom.roll = f32(atom.roll + f32(atom.source.spin * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * atom.source.life));
    }

    function cull() {
      // Unity examines each SIMD group from its last lane and fills a dead slot from the tail.
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

    function step(dt) {
      for (const atom of active) advance(atom, dt);
      cull();
      const previous = clock, next = f32(clock + dt), wrapped = next > cycle;
      clock = wrapped ? f32(next - cycle) : next;
      const amount = wrapped ? f32(f32(f32(cycle - previous) * rate) + f32(clock * rate)) :
        f32(f32(clock - previous) * rate);
      const combined = f32(amount + carry), continuous = Math.trunc(combined);
      carry = f32(combined - continuous);
      // The one authored time-zero burst is emitted on the cycle boundary.
      const count = continuous + (wrapped ? burst : 0);
      if (!count) return;
      const reciprocal = amount >= birthBias ? f32(1 / amount) : 1;
      const births = [];
      for (let i = 0; i < count; i += 4) {
        if (group === groups.length) groups.push(streams.map(drawBirth));
        const sources = groups[group++];
        for (let lane = 0; lane < Math.min(4, count - i); lane++) {
          const index = i + lane, atom = {source: sources[lane], age: 0, roll: 0};
          const fraction = index < continuous ? f32(f32(index + carry) * reciprocal) : 0;
          advance(atom, f32(dt * Math.min(1, Math.max(birthBias, fraction))));
          births.push(atom);
        }
      }
      // Fill the partly occupied native SIMD group with the tail of the new batch.
      const gap = (4 - active.length % 4) % 4;
      const firstLane = gap ? Math.max(0, count - gap) : 0;
      for (let i = 0; i < count; i++) active.push(births[(firstLane + i) % count]);
    }

    function snapshot() {
      return {clock, carry, group, active: active.map(atom => ({...atom}))};
    }

    function restore(saved, savedFrame) {
      ({clock, carry, group} = saved);
      frame = savedFrame;
      active = saved.active.map(atom => ({...atom}));
    }

    // The bounds prepass supplies each profile's carry at the start of prewarm.
    // Replay its fixed .02-second particle updates before the first display tick.
    let remaining = horizon;
    while (remaining >= fixedStep) {
      step(fixedStep);
      remaining = f32(remaining - fixedStep);
    }
    const warmed = snapshot();

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > 60) return;
      const firstFrameSteps = nativeStepRate / fps;
      if (displayRate !== fps) {
        displayRate = fps;
        restore(warmed, 0);
        checkpoints = [warmed];
        firstFrameRemainder = f32(f32(1 / fps) + remaining);
        for (let i = 0; i < firstFrameSteps; i++) firstFrameRemainder = f32(firstFrameRemainder - nativeStep);
      }
      const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
      const savedFrame = index * nativeStepRate;
      if (target < frame || savedFrame > frame) restore(checkpoints[index], savedFrame);
      while (frame < target) {
        step(nativeStep);
        frame++;
        if (frame === firstFrameSteps && firstFrameRemainder >= birthBias) step(firstFrameRemainder);
        if (frame === checkpoints.length * nativeStepRate) checkpoints.push(snapshot());
      }
      for (const atom of active) {
        const {x, y, z, width, height, depth, color} = atom.source;
        const rgba = nativeColorAtTime(color, f32(atom.age * ageScale)).map(value => Math.round(value * 255));
        emit(x, y, z, width, height, depth, initialX, 0, atom.roll, ...rgba);
      }
    }};
  }

  global.MVStudioAutumnFloorSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
