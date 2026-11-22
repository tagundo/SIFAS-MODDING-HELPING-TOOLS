(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 727550837, rate = 10, burstCount = 10, duration = 15;
  const gravitySalt = 0xe2b7c3c3, velocitySalt = 0xe0fbd834, sizeSalt = 0x8d2c8431, colorSalt = 0x591bc05c;
  const ageScale = f32(.01), birthBias = f32(1e-6), radius = f32(.03);
  const fullCircle = f32(2 * Math.PI), inverseCircle = f32(1 / (2 * Math.PI));
  const white = [255, 255, 255, 255];
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const stamp = value => Number.isInteger(value) && value >= 0 && value <= 65535;
  const byte = value => Number.isInteger(value) && value >= 0 && value <= 255;
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));

  function validKeys(rows, count, width, validTime, validValue) {
    return Array.isArray(rows) && rows.length === count && rows.every((row, index) =>
      Array.isArray(row) && row.length === width && validTime(row[0]) && (!index || row[0] > rows[index - 1][0]) &&
      row.slice(1).every(validValue));
  }

  function inverseLifetime(value) {
    // Native NEON reciprocal estimate followed by two rounded Newton steps.
    const power = Math.floor(Math.log2(value));
    const normalized = Math.floor(value * 2 ** -power * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * normalized + 1)) + 1) / 2) * 2 ** -power / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function startColor(keys, weight) {
    const stamp = f32(weight * 65535);
    const next = keys.findIndex(row => row[0] > stamp);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const mix = left === right ? 0 : f32(f32(stamp - left[0]) / (right[0] - left[0]));
    return left.slice(1).map((value, channel) =>
      Math.trunc(f32(f32(lerp(value, right[channel + 1], mix) * 255) + .5)));
  }

  function steppedValue(keys, phase) {
    for (let i = keys.length - 1; i >= 0; i--) {
      if (phase >= keys[i][0]) return keys[i][1];
    }
    return keys[0][1];
  }

  function create(profile, positionAt, source) {
    const particles = global.MVStudioStageParticles;
    const {startRGB, sizeKeys, alphaKeys} = source || {};
    if (profile !== "opening" || typeof positionAt !== "function" || !particles ||
        !Array.isArray(sizeKeys) || sizeKeys.length !== 2 || !validKeys(sizeKeys[0], 15, 2, unit, unit) ||
        !validKeys(sizeKeys[1], 20, 2, unit, unit) || !Array.isArray(alphaKeys) || alphaKeys.length !== 2 ||
        !alphaKeys.every(rows => validKeys(rows, 8, 2, stamp, byte)) ||
        !validKeys(startRGB, 6, 4, stamp, unit)) return null;
    const {nativeFrame, nativeRandom, nativeUnit, nativeStep: dt, nativeStepRate,
      nativeColorAtTime, nativeSpherePosition} = particles;
    const gradients = alphaKeys.map(rows => ({start: white, keys: rows.map(([stamp, alpha]) =>
      [f32(stamp / 65535), 255, 255, 255, alpha])}));
    const layouts = new Map(), maxFrame = Math.ceil((duration + 1.5) * nativeStepRate);

    function makeLayout(fps) {
      const grouped = nativeStepRate / fps, displayStep = f32(1 / fps);
      const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const frames = [new Float32Array()], active = [];
      let clock = 0, carry = 0, failed = false;

      function advance(particle, step) {
        const gravityStep = f32(f32(f32(-9.81) * step) * particle.gravity);
        particle.vy = f32(particle.vy + gravityStep);
        particle.x = f32(particle.x + f32(particle.dx * step));
        particle.y = f32(particle.y + f32(f32(particle.vy + particle.dy) * step));
        particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
      }

      function emitStep(tick) {
        if (clock >= duration) return;
        const previous = clock;
        clock = Math.min(duration, f32(clock + dt));
        const amount = f32(f32(clock - previous) * rate);
        const total = f32(amount + carry), continuous = Math.trunc(total);
        carry = f32(total - continuous);
        const count = continuous + (previous === 0 ? burstCount : 0);
        if (!count) return;
        const display = Math.floor((tick - 1) / grouped);
        const current = positionAt(display, fps), last = display ? positionAt(display - 1, fps) : current;
        if (![current, last].every(origin => Array.isArray(origin) && origin.length === 3 && origin.every(Number.isFinite))) {
          failed = true;
          return;
        }
        const origin = current.map(f32), previousOrigin = last.map(f32);
        const emitterVelocity = origin.map((value, axis) => f32(f32(value - previousOrigin[axis]) / displayStep));
        const leftInFrame = (display + 1) * grouped - tick;
        const births = [];
        const roundedCount = Math.ceil(count / 4) * 4;
        const sameSize = [1, 1, 1];
        for (let index = 0; index < roundedCount; index++) {
          const draw = initial[index % 4], sampleShape = shape[index % 4];
          const word = draw() >>> 0;
          const life = lerp(1, 1.5, nativeUnit(draw()));
          const size = lerp(f32(.02), f32(.04), nativeUnit(draw()));
          draw(); // Fixed rotation still occupies its initial RNG lane.
          const colorWeight = nativeUnit(draw());
          const turns = f32(f32(fullCircle * nativeUnit(sampleShape())) * inverseCircle);
          const [sx, sy, sz] = nativeSpherePosition(turns, nativeUnit(sampleShape()), nativeUnit(sampleShape()),
            radius, sameSize);
          if (index >= count) continue;
          const fraction = index < continuous ? f32(f32(index + carry) * f32(1 / amount)) : 0;
          const within = Math.min(1, Math.max(birthBias, fraction));
          const step = f32(dt * within), backtrack = f32(dt * f32(leftInFrame + within));
          const velocity = nativeRandom((word + velocitySalt) >>> 0);
          const driftX = -lerp(f32(.03), f32(.09), nativeUnit(velocity()));
          const driftY = lerp(0, f32(-.05), nativeUnit(velocity()));
          const salted = salt => nativeUnit(nativeRandom((word + salt) >>> 0)());
          const rgba = startColor(startRGB, colorWeight);
          const particle = {x: f32(f32(origin[0] - sx) - f32(emitterVelocity[0] * backtrack)),
            y: f32(f32(origin[1] + sy) - f32(emitterVelocity[1] * backtrack)),
            z: f32(f32(origin[2] + sz) - f32(emitterVelocity[2] * backtrack)),
            dx: driftX, dy: driftY, vy: 0, age: 0, life: inverseLifetime(life), size, rgba,
            gravity: lerp(f32(.005), f32(.012), salted(gravitySalt)), sizeMix: salted(sizeSalt),
            colorMix: Math.trunc(f32(salted(colorSalt) * 255))};
          advance(particle, step);
          births.push(particle);
        }
        active.push(...births);
      }

      function cull() {
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

      function extend(target) {
        while (!failed && frames.length <= target) {
          for (const particle of active) advance(particle, dt);
          cull();
          emitStep(frames.length);
          if (failed) break;
          const data = new Float32Array(active.length * 8);
          for (const [index, particle] of active.entries()) {
            const phase = f32(particle.age * ageScale);
            const size = f32(particle.size * lerp(steppedValue(sizeKeys[0], phase), steppedValue(sizeKeys[1], phase), particle.sizeMix));
            const low = Math.round(nativeColorAtTime(gradients[0], phase)[3] * 255);
            const high = Math.round(nativeColorAtTime(gradients[1], phase)[3] * 255);
            const alpha = low + ((128 + particle.colorMix * (high - low)) >> 8);
            data.set([particle.x, particle.y, particle.z, size, ...particle.rgba, alpha], index * 8);
          }
          frames.push(data);
        }
        return frames[target];
      }

      return extend;
    }

    return {sample(elapsed, fps, emit) {
      const frame = nativeFrame(elapsed, fps);
      if (frame < 1 || frame > maxFrame) return;
      if (!layouts.has(fps)) layouts.set(fps, makeLayout(fps));
      const data = layouts.get(fps)(frame);
      if (!data) return;
      for (let i = 0; i < data.length; i += 8) {
        emit(data[i], data[i + 1], data[i + 2], data[i + 3], data[i + 4], data[i + 5], data[i + 6], data[i + 7]);
      }
    }};
  }

  global.MVStudioButterflyShineSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
