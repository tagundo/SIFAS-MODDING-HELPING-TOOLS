(function (global) {
  "use strict";

  const f32 = Math.fround;
  const ageScale = f32(.01), fixedStep = f32(.02), birthBias = f32(1e-6);
  const halfPi = f32(1.570796251296997);
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const stamp = value => Number.isInteger(value) && value >= 0 && value <= 65535;
  const vector = (values, count) => Array.isArray(values) && values.length === count && values.every(Number.isFinite);

  function keysValid(keys, count, width, timeCheck, valueCheck) {
    return Array.isArray(keys) && keys.length === count && keys.every((key, index) =>
      vector(key, width) && timeCheck(key[0]) && (!index || key[0] > keys[index - 1][0]) && valueCheck(key));
  }

  function supported(profile, impact) {
    if (profile !== "01" && profile !== "02") return false;
    const first = profile === "01", {wave, glow} = impact || {};
    const curve = keys => keysValid(keys, 2, 4, unit, key => unit(key[1])) && keys[0][0] === 0 && keys[1][0] === 1;
    const rgb = (keys, count) => keysValid(keys, count, 4, stamp, key => key.slice(1).every(unit));
    const alpha = (keys, count) => keysValid(keys, count, 2, stamp, key => unit(key[1]));
    return vector(wave?.position, 3) && wave.position[0] === 0 && f32(wave.position[1]) === f32(.02) &&
      wave.position[2] === (first ? 0 : 1) && wave.startColor?.mode === (first ? 1 : 4) &&
      rgb(wave.startColor.rgb, 3) && alpha(wave.startColor.alpha, 2) && curve(wave.sizeKeys) && curve(wave.frameKeys) &&
      rgb(wave.colorKeys?.rgb, first ? 2 : 4) && alpha(wave.colorKeys?.alpha, 4) &&
      vector(glow?.startColor, 4) && glow.startColor.every(unit) && curve(glow.sizeKeys) &&
      rgb(glow.colorKeys?.rgb, 4) && alpha(glow.colorKeys?.alpha, 3);
  }

  function curve(keys) {
    const [, start, , out] = keys[0], [, end, incoming] = keys[1];
    const delta = f32(end - start);
    const a = f32(f32(f32(out + incoming) - delta) - delta);
    const b = f32(f32(f32(f32(f32(delta + delta) + delta) - out) - out) - incoming);
    return t => f32(start + f32(t * f32(out + f32(t * f32(b + f32(t * a))))));
  }

  function inverseLife(value) {
    // Match the NEON reciprocal estimate and two refinements in InitialModule.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function colorAt(keys, at) {
    const next = keys.findIndex(row => row[0] > at);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const weight = left === right ? 0 : f32(f32(at - left[0]) / (right[0] - left[0]));
    return left.slice(1).map((value, i) => byte(lerp(value, right[i + 1], weight)));
  }

  function colorKeys({rgb, alpha}) {
    const stamps = [...new Set([...rgb, ...alpha].map(key => key[0]))].sort((a, b) => a - b);
    return stamps.map(time => [f32(time / 65535), ...colorAt(rgb, time), ...colorAt(alpha, time)]);
  }

  function tickAtoms(active, step) {
    for (const particle of active) particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
    // The original culls in groups of four, using the tail to fill each expired slot.
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

  function create(profile, impact) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(profile, impact)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeColorAtTime} = particles;
    const {wave, glow} = impact, first = profile === "01";
    const seed = first ? 1950736341 : 1, cycle = first ? 5 : 2.5, rate = first ? 100 : 30;
    const maxLife = f32(.6), minLife = first ? maxLife : f32(.4);
    const minSize = f32(first ? .3 : .2), maxSize = f32(first ? .4 : .3);
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const waveScale = curve(wave.sizeKeys), glowScale = curve(glow.sizeKeys), waveUV = curve(wave.frameKeys);
    const waveColors = colorKeys(wave.colorKeys), glowColors = colorKeys(glow.colorKeys);
    const glowTint = {start: glow.startColor.map(byte), keys: glowColors};
    const groups = [], childGroups = [], layouts = new Map();
    const childInitial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const [, y, anchorZ] = wave.position.map(f32);

    function makeGroup() {
      return initial.map((draw, lane) => {
        draw();
        const life = inverseLife(lerp(minLife, maxLife, nativeUnit(draw())));
        const width = lerp(minSize, maxSize, nativeUnit(draw()));
        const roll = lerp(-halfPi, halfPi, nativeUnit(draw()));
        const colorWeight = nativeUnit(draw());
        const box = shape[lane];
        const x = -f32(f32(nativeUnit(box()) - .5) * 16);
        box(); // The zero Box Y still advances the independent shape stream.
        const localZ = f32(f32(f32(nativeUnit(box()) - .5) * 10) + 1);
        const z = f32(localZ + (anchorZ - 1));
        return {x, z, life, width, roll, colorWeight};
      });
    }

    function makeChildGroup() {
      return childInitial.map(draw => {
        draw(); // Particle seed.
        const life = inverseLife(lerp(f32(.2), f32(.4), nativeUnit(draw())));
        const width = lerp(f32(.3), f32(.4), nativeUnit(draw()));
        const roll = lerp(-halfPi, halfPi, nativeUnit(draw()));
        draw(); // Fixed start color.
        return {life, width, roll};
      });
    }

    function render(role, list, scale, emit) {
      for (const particle of list) {
        const phase = f32(particle.age * ageScale);
        const size = f32(particle.width * Math.max(0, scale(phase)));
        const tint = role === "wave" ? particle.tint : glowTint;
        const rgba = nativeColorAtTime(tint, phase).map(value => Math.round(value * 255));
        const tile = role === "wave" ? Math.min(15, Math.floor(f32(16 * f32(f32(.9999) * waveUV(phase))))) : 3;
        emit(role, particle.x, y, particle.z, size, particle.roll, ...rgba, tile);
      }
    }

    function makeLayout(fps) {
      const grouped = nativeStepRate / fps, checkpoints = [];
      let frame = 0, clock = 0, carry = 0, groupIndex = 0, childIndex = 0, waves = [], glows = [];

      function emitGlow(parent, remaining) {
        if (childIndex === childGroups.length) childGroups.push(makeChildGroup());
        const group = childGroups[childIndex++];
        // The time-zero burst runs within the parent's fractional birth step.
        const partial = f32(f32(parent.within * birthBias) * 100);
        const ages = group.map(source => f32(partial * source.life));
        if (remaining >= fixedStep) {
          const increments = group.map(source => f32(f32(fixedStep * 100) * source.life));
          for (let left = remaining; left >= fixedStep; left = f32(left - fixedStep)) {
            for (let lane = 0; lane < ages.length; lane++) ages[lane] = f32(ages[lane] + increments[lane]);
            // Inline prewarm can discard a one-particle birth if any padded SIMD lane expires.
            if (ages.some(age => age > 100)) return;
          }
        }
        glows.push({...group[0], x: parent.x, z: parent.z, age: ages[0]});
      }

      function stepParent(dt, remaining) {
        tickAtoms(waves, dt);
        const previous = clock, next = f32(clock + dt);
        let amount;
        if (next <= cycle) {
          clock = next;
          amount = f32(f32(next - previous) * rate);
        } else if (first) {
          clock = f32(next - cycle);
          amount = f32(f32(f32(cycle - previous) * rate) + f32(clock * rate));
        } else {
          clock = cycle;
          amount = 0;
        }
        const combined = f32(amount + carry), count = Math.trunc(combined);
        carry = f32(combined - count);
        if (!count) return;
        if (groupIndex === groups.length) groups.push(makeGroup());
        const group = groups[groupIndex++], births = [];
        const reciprocal = f32(1 / amount);
        for (let lane = 0; lane < count; lane++) {
          const source = group[lane];
          const fraction = Math.min(1, Math.max(birthBias, f32(f32(lane + carry) * reciprocal)));
          const within = f32(dt * fraction);
          const time = f32(f32(first ? f32(clock / cycle) : source.colorWeight) * 65535);
          const tint = {start: [...colorAt(wave.startColor.rgb, time), ...colorAt(wave.startColor.alpha, time)], keys: waveColors};
          births.push({...source, tint, age: f32(f32(within * 100) * source.life), within});
        }
        for (const particle of births) emitGlow(particle, remaining);
        // Preserve native storage order on a write crossing a four-lane boundary.
        const firstLane = Math.max(0, count - (4 - waves.length % 4));
        for (let lane = 0; lane < count; lane++) {
          waves.push(births[(firstLane + lane) % count]);
        }
      }

      function checkpoint() {
        return {clock, carry, groupIndex, childIndex, waves: waves.map(particle => ({...particle})),
          glows: glows.map(particle => ({...particle}))};
      }

      if (first) {
        // The original bounds prepass includes the linked child's maximum life.
        const horizon = f32(maxLife + f32(.4));
        clock = f32(cycle - horizon);
        carry = .00019536743639037013;
        for (let left = horizon; left >= fixedStep; left = f32(left - fixedStep)) stepParent(fixedStep, left);
      }
      checkpoints.push(checkpoint());

      return (target, emit) => {
        const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
        const savedFrame = index * nativeStepRate;
        if (target < frame || savedFrame > frame) {
          const saved = checkpoints[index];
          ({clock, carry, groupIndex, childIndex} = saved);
          waves = saved.waves.map(particle => ({...particle}));
          glows = saved.glows.map(particle => ({...particle}));
          frame = savedFrame;
        }
        while (frame < target) {
          // Unity schedules the linked child's job after the entire parent display update.
          for (let i = 0; i < grouped; i++) stepParent(nativeStep, f32((grouped - i) * nativeStep));
          for (let i = 0; i < grouped; i++) tickAtoms(glows, nativeStep);
          frame += grouped;
          if (frame === checkpoints.length * nativeStepRate) checkpoints.push(checkpoint());
        }
        render("wave", waves, waveScale, emit);
        render("glow", glows, glowScale, emit);
      };
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > (first ? 60 : 3.1)) return;
      if (!layouts.has(fps)) layouts.set(fps, makeLayout(fps));
      layouts.get(fps)(target, emit);
    }};
  }

  global.MVStudioRainFloorSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
