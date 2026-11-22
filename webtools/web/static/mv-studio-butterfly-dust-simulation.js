(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 2915313312, duration = f32(1.3), radius = f32(.05);
  const lastBirthTick = 18, lastTick = 127;
  const stepFraction = f32(.01), birthFraction = f32(1e-6);
  const sizeSalt = 0x8d2c8431, velocitySalt = 0xe0fbd834, speedSalt = 0xba821f34, atlasSalt = 0x56b3dbb0;
  const fullCircle = f32(2 * Math.PI), inverseCircle = f32(1 / (2 * Math.PI));
  const white = [255, 255, 255, 255];
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const stamp = value => Number.isInteger(value) && value >= 0 && value <= 65535;
  const byte = value => Number.isInteger(value) && value >= 0 && value <= 255;
  const colorByte = value => Math.trunc(f32(f32(value * 255) + .5));
  const nativeMix = (from, to, weight) => from + ((128 + weight * (to - from)) >> 8);

  function keyList(keys, count, width, timeCheck, dataCheck) {
    return Array.isArray(keys) && keys.length === count && keys.every((row, index) =>
      Array.isArray(row) && row.length === width && timeCheck(row[0]) &&
      (!index || row[0] > keys[index - 1][0]) && dataCheck(row));
  }

  function curveKeys(keys, count) {
    return keyList(keys, count, 4, unit, row =>
      Number.isFinite(row[1]) && row.slice(2).every(slope => slope === null || Number.isFinite(slope)));
  }

  function rgbKeys(keys, count) {
    return keyList(keys, count, 4, stamp, row => row.slice(1).every(unit));
  }

  function alphaKeys(keys, count, valueCheck) {
    return keyList(keys, count, 2, stamp, row => valueCheck(row[1]));
  }

  function inverseLife(value) {
    // InitialModule uses a NEON estimate followed by two reciprocal refinements.
    const scale = 2 ** -Math.floor(Math.log2(value));
    const bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function gradientColor(keys, phase, channel) {
    const at = f32(phase * 65535);
    const next = keys.findIndex(row => row[0] > at);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const t = left === right ? 0 : f32(f32(at - left[0]) / (right[0] - left[0]));
    return colorByte(lerp(left[channel], right[channel], t));
  }

  function create(role, positionAt, source) {
    const particles = global.MVStudioStageParticles;
    if ((role !== "alpha" && role !== "add") || typeof positionAt !== "function" ||
        source?.profile !== "finale" || !Array.isArray(source.emitters) || !particles) return null;
    const {sizeKeys, velocity} = source;
    const sourceColor = source.emitters.find(emitter => emitter?.role === role)?.startColor;
    const velocityKeyCounts = [[4, 4], [2, 2], [2, 2]];
    if (!Array.isArray(sizeKeys) || sizeKeys.length !== 2 ||
        !curveKeys(sizeKeys[0], 10) || !curveKeys(sizeKeys[1], 12) ||
        !Array.isArray(velocity) || velocity.length !== 3 ||
        !velocity.every((axis, i) => axis && curveKeys(axis.min, velocityKeyCounts[i][0]) &&
          curveKeys(axis.max, velocityKeyCounts[i][1]) && Array.isArray(axis.scale) &&
          axis.scale.length === 2 && axis.scale.every(Number.isFinite)) ||
        !alphaKeys(source.alphaKeys, 3, byte)) return null;
    if (role === "alpha") {
      if (!Array.isArray(sourceColor) || sourceColor.length !== 4 || !sourceColor.every(unit)) return null;
    } else {
      const {rgb, alpha} = sourceColor || {};
      if (!Array.isArray(rgb) || rgb.length !== 2 || !rgbKeys(rgb[0], 4) || !rgbKeys(rgb[1], 5) ||
          !Array.isArray(alpha) || alpha.length !== 2 || !alphaKeys(alpha[0], 3, unit) ||
          !alphaKeys(alpha[1], 2, unit)) return null;
    }

    const {nativeFrame, nativeRandom, nativeUnit, nativeSpherePosition, nativeColorAtTime,
      nativeStep: dt, nativeStepRate, nativeCurve} = particles;
    const sizeCurves = sizeKeys.map(nativeCurve);
    const axes = velocity.map(axis => ({min: nativeCurve(axis.min), max: nativeCurve(axis.max), scalar: axis.scale[1]}));
    const lifeColor = {start: white, keys: source.alphaKeys.map(([time, alpha]) =>
      [f32(time / 65535), 255, 255, 255, alpha])};
    const fixedColor = role === "alpha" ? sourceColor.map(colorByte) : null;
    const layouts = new Map(), sphereScale = [1, 1, 1];
    const saltedUnit = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());

    function startColor(phase, weight) {
      if (fixedColor) return fixedColor;
      const {rgb, alpha} = sourceColor;
      const mix = Math.trunc(f32(weight * 255));
      const palette = [0, 1].map(index => [1, 2, 3].map(channel => gradientColor(rgb[index], phase, channel))
        .concat(gradientColor(alpha[index], phase, 1)));
      return palette[0].map((value, index) => nativeMix(value, palette[1][index], mix));
    }

    function makeLayout(fps) {
      const grouped = nativeStepRate / fps, displayStep = f32(1 / fps);
      const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const frames = [new Float32Array()], active = [];
      let clock = 0, failed = false;

      function advance(particle, step, speed) {
        const phase = f32(particle.age * stepFraction);
        for (const [axis, curve] of axes.entries()) {
          const low = f32(curve.min(phase) * curve.scalar), high = f32(curve.max(phase) * curve.scalar);
          const drift = lerp(low, high, particle.velocity[axis]);
          particle.position[axis] = f32(particle.position[axis] + f32(step * f32(speed * drift)));
        }
        particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
      }

      function birth(tick, count) {
        const display = Math.floor((tick - 1) / grouped);
        const current = positionAt(display, fps), last = display ? positionAt(display - 1, fps) : current;
        if (![current, last].every(origin => Array.isArray(origin) && origin.length === 3 && origin.every(Number.isFinite))) {
          failed = true;
          return;
        }
        // Simulate in Unity's coordinates and reflect X when writing the viewer packet.
        const nativeOrigin = ([x, y, z]) => [f32(-x), f32(y), f32(z)];
        const origin = nativeOrigin(current), previous = nativeOrigin(last);
        const originVelocity = origin.map((value, axis) => f32(f32(value - previous[axis]) / displayStep));
        const leftInFrame = (display + 1) * grouped - tick;
        const partial = f32(dt * birthFraction), backtrack = f32(dt * f32(leftInFrame + birthFraction));
        const phase = f32(clock / duration);
        for (let index = 0; index < count; index++) {
          const draw = initial[index % 4], nextShape = shape[index % 4];
          const word = draw();
          const life = inverseLife(lerp(f32(1.2), f32(1.8), nativeUnit(draw())));
          const size = lerp(f32(.03), f32(.05), nativeUnit(draw()));
          draw(); // The zero roll still has its own InitialModule random draw.
          const rgba = startColor(phase, nativeUnit(draw()));
          const turns = f32(f32(fullCircle * nativeUnit(nextShape())) * inverseCircle);
          const [sx, sy, sz] = nativeSpherePosition(turns, nativeUnit(nextShape()), nativeUnit(nextShape()), radius, sphereScale);
          const position = [sx, sy, sz].map((value, axis) =>
            f32(f32(origin[axis] + value) - f32(originVelocity[axis] * backtrack)));
          const drift = nativeRandom((word + velocitySalt) >>> 0);
          const velocity = [nativeUnit(drift()), nativeUnit(drift()), nativeUnit(drift())];
          const speed = lerp(f32(.2), .5, saltedUnit(word, speedSalt));
          const particle = {position, velocity, speed, age: 0, life, size, rgba,
            sizeMix: saltedUnit(word, sizeSalt), tile: Math.floor(f32(f32(.09375 * saltedUnit(word, atlasSalt)) * 16))};
          const firstLane = active.length & ~3;
          active.push(particle);
          advance(particle, partial, active[firstLane].speed);
        }
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
          // SpeedModifier uses the first particle's seeded factor for each current four-lane group.
          for (const [index, particle] of active.entries()) advance(particle, dt, active[index & ~3].speed);
          cull();
          clock = f32(clock + dt);
          if (frames.length === 1) birth(1, 40);
          else if (frames.length === lastBirthTick) birth(lastBirthTick, 20);
          if (failed) break;
          const data = new Float32Array(active.length * 9);
          for (const [index, particle] of active.entries()) {
            const phase = f32(particle.age * stepFraction);
            const size = f32(particle.size * Math.max(0, lerp(sizeCurves[0](phase), sizeCurves[1](phase), particle.sizeMix)));
            const colorAlpha = Math.round(nativeColorAtTime(lifeColor, phase)[3] * 255);
            const [x, y, z] = particle.position, [r, g, b, alpha] = particle.rgba;
            data.set([-x, y, z, size, r, g, b, Math.floor((alpha * colorAlpha + 127) / 255), particle.tile], index * 9);
          }
          frames.push(data);
        }
        return frames[target];
      }

      return extend;
    }

    return {sample(elapsed, fps, emit) {
      const frame = nativeFrame(elapsed, fps);
      if (frame < 1 || frame > lastTick) return;
      if (!layouts.has(fps)) layouts.set(fps, makeLayout(fps));
      const data = layouts.get(fps)(frame);
      if (!data) return;
      for (let i = 0; i < data.length; i += 9) {
        emit(data[i], data[i + 1], data[i + 2], data[i + 3], data[i + 4], data[i + 5], data[i + 6], data[i + 7], data[i + 8]);
      }
    }};
  }

  global.MVStudioButterflyDustSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
