(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 1950736341, fixedStep = f32(.02), ageScale = f32(.01);
  const birthBias = f32(1e-6);
  const speedSalt = 0x96aa4de3, velocitySalt = 0xe0fbd834, sizeSalt = 0x8d2c8431;
  const white = [255, 255, 255, 255];
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const finiteVector = (values, count) => Array.isArray(values) && values.length === count && values.every(Number.isFinite);
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const stamp = value => Number.isInteger(value) && value >= 0 && value <= 65535;
  const colorByte = value => Math.trunc(f32(f32(value * 255) + .5));

  function validKeys(keys, count, width, timeCheck, dataCheck) {
    return Array.isArray(keys) && keys.length === count && keys.every((row, i) =>
      finiteVector(row, width) && timeCheck(row[0]) && (!i || row[0] > keys[i - 1][0]) && dataCheck(row));
  }

  function supported(row) {
    if (!row || (row.profile !== "01" && row.profile !== "02")) return false;
    const expectedY = f32(f32(row.profile === "01" ? 15 : 8.53) + f32(.01));
    const {position, rotation, sizeKeys, colorKeys, startRGB} = row;
    return finiteVector(position, 3) && position[0] === f32(-.19) && position[1] === expectedY &&
      position[2] === f32(-3.88) && finiteVector(rotation, 4) && !rotation[1] && !rotation[2] &&
      Math.abs(rotation[0] - Math.SQRT1_2) < 1e-6 && Math.abs(rotation[3] - Math.SQRT1_2) < 1e-6 &&
      Array.isArray(sizeKeys) && sizeKeys.length === 2 &&
      sizeKeys.every(keys => validKeys(keys, 3, 4, unit, values => unit(values[1]))) &&
      validKeys(startRGB, 3, 4, stamp, values => values.slice(1).every(unit)) &&
      validKeys(colorKeys?.rgb, 2, 4, stamp, values => values.slice(1).every(unit)) &&
      validKeys(colorKeys?.alpha, 4, 2, stamp, values => unit(values[1]));
  }

  function inverseLife(value) {
    // InitialModule refines the NEON reciprocal estimate twice.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function sizeCurve(keys) {
    const segments = keys.slice(0, 2).map(([from, value, , outSlope], i) => {
      const [to, next, inSlope] = keys[i + 1];
      const span = f32(to - from), delta = f32(next - value);
      const out = f32(span * outSlope), incoming = f32(span * inSlope), invSquare = f32(1 / f32(span * span));
      const a = f32(f32(invSquare * f32(f32(f32(out + incoming) - delta) - delta)) / span);
      const b = f32(invSquare * f32(f32(f32(f32(f32(delta + delta) + delta) - out) - out) - incoming));
      return [from, a, b, outSlope, value];
    });
    return phase => {
      const [origin, a, b, c, d] = segments[phase > keys[1][0] ? 1 : 0];
      const time = f32(phase - origin);
      return f32(d + f32(time * f32(c + f32(time * f32(b + f32(time * a))))));
    };
  }

  function colorAt(keys, at) {
    const next = keys.findIndex(row => row[0] > at);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const weight = left === right ? 0 : f32(f32(at - left[0]) / (right[0] - left[0]));
    return left.slice(1).map((value, i) => colorByte(lerp(value, right[i + 1], weight)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep, nativeStepRate} = particles;
    const opening = row.profile === "01", cycle = opening ? .5 : 2.5, rate = opening ? 120 : 30;
    const gravity = opening ? 1.5 : 0, boxY = opening ? 16 : 25;
    const minLife = opening ? f32(1.4) : 1.5, maxLife = opening ? minLife : 2;
    const minLength = opening ? f32(1.2) : f32(.2), minSpeed = opening ? 3 : 1, maxSpeed = opening ? 5 : 2;
    const minWidth = f32(.2), maxWidth = f32(.3), maxLength = 1.5;
    const [px, py, pz] = row.position, [lowSize, highSize] = row.sizeKeys.map(sizeCurve);
    const {rgb, alpha} = row.colorKeys;
    // Build the packed lifetime gradient at the union of its authored RGB and alpha keys.
    const colorStamps = [...new Set([...rgb, ...alpha].map(key => key[0]))].sort((a, b) => a - b);
    const colorKeys = colorStamps.map(time => [f32(time / 65535), ...colorAt(rgb, time), ...colorAt(alpha, time)]);
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shapes = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const groups = [], checkpoints = [];
    let frame = 0, clock = 0, carry = 0, groupIndex = 0, active = [];

    function interval(previous, step) {
      const next = f32(previous + step);
      if (next <= cycle) return [next, f32(f32(next - previous) * rate)];
      if (!opening) return [cycle, 0];
      const wrapped = f32(next - cycle);
      return [wrapped, f32(f32(f32(cycle - previous) * rate) + f32(wrapped * rate))];
    }

    function prepareGroup() {
      // The original emits a four-lane group, advancing padding lanes too.
      return initial.map((draw, lane) => {
        const word = draw();
        const life = inverseLife(lerp(minLife, maxLife, nativeUnit(draw())));
        const width = lerp(minWidth, maxWidth, nativeUnit(draw()));
        const length = lerp(minLength, maxLength, nativeUnit(draw()));
        draw(); // The Z dimension is not used by the stretched billboard.
        draw(); // Fixed roll.
        const color = {start: [...colorAt(row.startRGB, f32(nativeUnit(draw()) * 65535)), 255], keys: colorKeys};
        const shape = shapes[lane];
        const x = f32(f32(nativeUnit(shape()) - .5) * 25);
        const y = f32(f32(nativeUnit(shape()) - .5) * boxY);
        shape(); // Zero Box Z still advances its lane.
        const speed = lerp(minSpeed, maxSpeed, nativeUnit(nativeRandom((word + speedSalt) >>> 0)()));
        const velocity = nativeRandom((word + velocitySalt) >>> 0);
        const drift = opening ? [0, 0, 0] : [lerp(f32(-.15), f32(.1), nativeUnit(velocity())),
          lerp(f32(-.1), f32(.1), nativeUnit(velocity())), lerp(3, 10, nativeUnit(velocity()))];
        if (opening) {
          velocity();
          drift[1] = lerp(f32(-.2), f32(-.15), nativeUnit(velocity()));
        }
        return {x, y, speed, life, width, length, drift, color,
          sizeMix: nativeUnit(nativeRandom((word + sizeSalt) >>> 0)())};
      });
    }

    function advance(particle, step, gravityStep) {
      const [vx, vy, vz] = particle.source.drift;
      particle.vz = f32(particle.vz + gravityStep);
      particle.x = f32(particle.x + f32(vx * step));
      particle.y = f32(particle.y + f32(vy * step));
      particle.z = f32(particle.z + f32(f32(particle.vz + vz) * step));
      particle.age = f32(particle.age + f32(f32(100 * step) * particle.source.life));
    }

    function grav(step) {
      return f32(f32(f32(9.81) * step) * gravity);
    }

    function cull() {
      for (let first = 0; first < active.length;) {
        let removed = false;
        for (let i = Math.min(first + 3, active.length - 1); i >= first; i--) {
          if (active[i].age <= 100) continue;
          const tail = active.pop();
          if (i < active.length) active[i] = tail;
          removed = true;
        }
        if (!removed) first += 4;
      }
    }

    function step(dt) {
      const gravityStep = grav(dt);
      for (const particle of active) advance(particle, dt, gravityStep);
      cull();
      let amount;
      [clock, amount] = interval(clock, dt);
      const combined = f32(amount + carry), count = Math.trunc(combined);
      carry = f32(combined - count);
      if (!count) return;
      if (groupIndex === groups.length) groups.push(prepareGroup());
      const sources = groups[groupIndex++];
      const births = [];
      const reciprocal = f32(1 / amount);
      for (let lane = 0; lane < count; lane++) {
        const source = sources[lane];
        const ageFraction = f32(f32(lane + carry) * reciprocal);
        const partial = f32(dt * Math.min(1, Math.max(birthBias, ageFraction)));
        const particle = {source, x: source.x, y: source.y, z: 0, vz: source.speed, age: 0};
        advance(particle, partial, grav(partial));
        births.push(particle);
      }
      // A partial storage group fills from the trailing lanes of a crossing write.
      const firstLane = Math.max(0, count - (4 - active.length % 4));
      for (let i = 0; i < count; i++) active.push(births[(firstLane + i) % count]);
    }

    function save() {
      return {clock, carry, groupIndex, active: active.map(particle => ({...particle}))};
    }

    function warm() {
      // The original bounds prepass seeds this stock emitter's warm simulation
      // with fmod(1.4, .5) subtracted from its cycle and this measured rate carry.
      clock = f32(cycle - f32(minLife % cycle));
      carry = .00020204315660521388;
      for (let left = minLife; left >= fixedStep; left = f32(left - fixedStep)) step(fixedStep);
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > (opening ? 60 : 4.5)) return;
      if (!checkpoints.length) {
        if (opening) warm();
        checkpoints.push(save());
      }
      const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
      const savedFrame = index * nativeStepRate;
      if (target < frame || savedFrame > frame) {
        const saved = checkpoints[index];
        ({clock, carry, groupIndex} = saved);
        active = saved.active.map(particle => ({...particle}));
        frame = savedFrame;
      }
      while (frame < target) {
        step(nativeStep);
        frame++;
        if (frame === checkpoints.length * nativeStepRate) checkpoints.push(save());
      }
      // The authored +90 degree X rotation maps local +Z to stage down.
      for (const particle of active) {
        const {width, length, drift, color, sizeMix} = particle.source;
        const phase = f32(particle.age * ageScale);
        const size = Math.max(0, lerp(lowSize(phase), highSize(phase), sizeMix));
        const rgba = nativeColorAtTime(color, phase).map(value => Math.round(value * 255));
        emit(f32(px - particle.x), f32(py - particle.z), f32(pz + particle.y),
          -drift[0], -f32(particle.vz + drift[2]), drift[1],
          f32(width * size), f32(length * size), ...rgba);
      }
    }};
  }

  global.MVStudioRainSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
