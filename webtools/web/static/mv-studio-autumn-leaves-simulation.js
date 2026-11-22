(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 3279275062, cycle = 10, ageScale = f32(.01), birthBias = f32(1e-6);
  const fixedStep = f32(.02), catchUpStep = f32(.2);
  const velocitySalt = 0xe0fbd834, speedSalt = 0x96aa4de3;
  const rotationSalt = 0x6aed452e, rotationBySpeedSalt = 0xdec4aea1, rotationSignSalt = 0xff2bb1a4;
  const maxSize = f32(.8), quarterPi = f32(.7853981256484985);
  const lifeRates = [[f32(-.8726646304130554), 1], [f32(-.5235987901687622), 1], [quarterPi * 2, -quarterPi * 2]];
  const speedRates = [[-quarterPi, quarterPi], [-quarterPi * 4, quarterPi * 4], [-quarterPi * 2, quarterPi * 4]];
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const stamp = value => Number.isInteger(value) && value >= 0 && value <= 65535;
  const vector = (values, count) => Array.isArray(values) && values.length === count && values.every(Number.isFinite);

  function keysValid(keys, count, channels) {
    return Array.isArray(keys) && keys.length === count && keys.every((key, i) =>
      vector(key, channels + 1) && stamp(key[0]) && (!i || key[0] > keys[i - 1][0]) &&
      key.slice(1).every(unit));
  }

  function supported(row) {
    if (!row || !["03", "04", "06"].includes(row.profile)) return false;
    const {position, rotation, startColor, alphaKeys} = row, red = row.profile === "06", yellow = row.profile === "04";
    return row.rate === (red ? 20 : yellow ? 10 : 12) &&
      (!red || (Number.isInteger(row.seed) && row.seed >= 0 && row.seed <= 0xffffffff)) && vector(position, 3) &&
      position[0] === f32(.65) && position[1] === 5 && position[2] === f32(-.46) &&
      vector(rotation, 4) && !rotation[1] && !rotation[2] &&
      Math.abs(rotation[0] - Math.SQRT1_2) < 1e-6 && Math.abs(rotation[3] - Math.SQRT1_2) < 1e-6 &&
      keysValid(alphaKeys, 4, 1) && (yellow ? vector(startColor, 4) && startColor.every(unit) :
        keysValid(startColor?.rgb, 3, 3) && keysValid(startColor?.alpha, 2, 1));
  }

  function inverse(value) {
    // NEON reciprocal estimate followed by two refinements.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function eased(from, to) {
    const delta = f32(to - from), a = f32(-2 * delta), b = f32(f32(delta + delta) + delta);
    return time => f32(from + f32(time * f32(time * f32(b + f32(time * a)))));
  }

  const decreasing = eased(1, 0), increasing = eased(0, 1);
  const speedCeiling = eased(.00040886178612709045, 1);
  const positive = eased(1, -1), negative = eased(-1, 1);

  function trigPolynomial(triangle) {
    const square = f32(triangle * triangle), fourth = f32(square * square);
    const c2 = f32(f32(square * -76.56861877441406) + 81.60182189941406);
    const c1 = f32(f32(square * -41.34165954589844) + 6.283185005187988);
    return f32(triangle * f32(f32(f32(fourth * fourth) * 39.65703201293945) + f32(c1 + f32(fourth * c2))));
  }

  function orbit(step) {
    // Only the source Z orbit is active, and each update is below one quarter turn.
    const turns = f32(f32(step * f32(.2)) * f32(.15915493667125702));
    const cosine = trigPolynomial(f32(.25 - turns));
    const sine = trigPolynomial(f32(.25 - Math.abs(f32(turns - .25))));
    return [cosine, sine, step > birthBias ? inverse(step) : 0];
  }

  function palette(keys, time) {
    const at = f32(time * 65535), next = keys.findIndex(row => row[0] > at);
    const b = keys[next < 0 ? keys.length - 1 : next], a = next > 0 ? keys[next - 1] : b;
    const blend = a === b ? 0 : f32(f32(at - a[0]) / (b[0] - a[0]));
    return a.slice(1).map((value, i) => byte(lerp(value, b[i + 1], blend)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeFrame, nativeStep, nativeStepRate, nativeRandom, nativeUnit, nativeColorAtTime} = particles;
    const {rate, position, startColor, alphaKeys} = row;
    const red = row.profile === "06", constant = row.profile === "04" ? startColor.map(byte) : null;
    const gradient = alphaKeys.map(([time, alpha]) => [f32(time / 65535), 255, 255, 255, byte(alpha)]);
    const streams = Array.from({length: red ? 4 : 1}, (_, lane) => {
      const word = red ? (row.seed + 367 * lane) >>> 0 : seed;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const birthGroups = [];
    const stepMotion = orbit(nativeStep), stepGravity = gravity(nativeStep);
    let frame = 0, clock = 0, carry = 0, group = 0, active = [];
    let displayFps, firstFrameRemainder = 0, warmRemainder = 0;
    let checkpoints;

    function random(word, salt) {
      return nativeUnit(nativeRandom((word + salt) >>> 0)());
    }

    function gravity(step) {
      return f32(f32(f32(9.81) * step) * f32(.01));
    }

    function prepareBirth({initial, shape}) {
      const word = initial(), life = inverse(lerp(red ? 5.5 : 6, 7, nativeUnit(initial())));
      const size = lerp(.5, maxSize, nativeUnit(initial()));
      const roll = lerp(-quarterPi, quarterPi, nativeUnit(initial()));
      const colorPhase = nativeUnit(initial()); // InitialModule also draws for fixed color.
      const x = f32(f32(nativeUnit(shape()) - .5) * 13);
      const y = f32(f32(nativeUnit(shape()) - .5) * 10);
      const z = f32(f32(nativeUnit(shape()) - .5) * 2);
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      const velocityX = nativeUnit(velocity()), velocityY = nativeUnit(velocity());
      // Both authored two-constant rotation modules add their rates using
      // separate draws, with one interpolation shared by all three axes.
      const rotationWeight = random(word, rotationSalt), speedWeight = random(word, rotationBySpeedSalt);
      const sign = random(word, rotationSignSalt) > 0 ? 1 : -1;
      const [ax, ay, az] = lifeRates.map(([a, b], axis) =>
        f32(sign * f32(lerp(a, b, rotationWeight) + lerp(...speedRates[axis], speedWeight))));
      return {x, y, z, roll, life, size, colorPhase, velocityX, velocityY, ax, ay, az, speed: random(word, speedSalt)};
    }

    function advance(particle, step, speedGain, [cosine, sine, inverseStep]) {
      const {source, x, y} = particle, phase = f32(particle.age * ageScale);
      const low = negative(phase), high = positive(phase);
      const rawX = lerp(low, high, source.velocityX), rawY = lerp(high, low, source.velocityY);
      const rotatedX = f32(f32(x * cosine) - f32(y * sine));
      const rotatedY = f32(f32(x * sine) + f32(y * cosine));
      const vx = f32(rawX + f32(f32(rotatedX - x) * inverseStep));
      const vy = f32(rawY + f32(f32(rotatedY - y) * inverseStep));
      particle.x = f32(x + f32(vx * step));
      particle.y = f32(y + f32(vy * step));
      particle.vz = f32(particle.vz + speedGain);
      particle.z = f32(particle.z + f32(particle.vz * step));
      particle.rx = f32(particle.rx + f32(source.ax * step));
      particle.ry = f32(particle.ry + f32(source.ay * step));
      particle.rz = f32(particle.rz + f32(source.az * step));
      particle.age = f32(particle.age + f32(f32(step * 100) * source.life));
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

    function step(delta) {
      const motion = delta === nativeStep ? stepMotion : orbit(delta);
      const gain = delta === nativeStep ? stepGravity : gravity(delta);
      for (const particle of active) advance(particle, delta, gain, motion);
      cull();
      const previous = clock, next = f32(clock + delta);
      clock = next > cycle ? f32(next - cycle) : next;
      const amount = next > cycle ?
        f32(f32(f32(cycle - previous) * rate) + f32(clock * rate)) : f32(f32(clock - previous) * rate);
      const combined = f32(amount + carry), count = Math.trunc(combined);
      carry = f32(combined - count);
      if (!count) return;
      if (group === birthGroups.length) birthGroups.push(streams.map(prepareBirth));
      const sources = birthGroups[group++], reciprocal = f32(1 / amount);
      for (let lane = 0; lane < count; lane++) {
        const source = sources[lane], phase = red ? source.colorPhase : f32(clock / cycle);
        const color = constant || [...palette(startColor.rgb, phase), ...palette(startColor.alpha, phase)];
        const fraction = Math.max(birthBias, Math.min(1, f32(f32(lane + carry) * reciprocal)));
        const partial = f32(delta * fraction);
        // ShapeModule samples speed at birth. Green InitialModule colors use the step's end phase.
        const speedTime = f32(f32(clock - partial) / cycle);
        const vz = lerp(decreasing(speedTime), speedCeiling(speedTime), source.speed);
        const atom = {source, color, x: source.x, y: source.y, z: source.z, vz, rx: 0, ry: 0, rz: source.roll, age: 0};
        advance(atom, partial, gravity(partial), orbit(partial));
        active.push(atom);
      }
    }

    function snapshot() {
      return {clock, carry, group, active: active.map(particle => ({...particle}))};
    }

    function restore(saved, savedFrame) {
      ({clock, carry, group} = saved);
      frame = savedFrame;
      active = saved.active.map(particle => ({...particle}));
    }

    if (red) {
      // The original bounds prepass seeds this rate remainder seven seconds before activation.
      clock = 3;
      carry = .9992798566818237;
      warmRemainder = 7;
      for (let stepSize = catchUpStep; warmRemainder >= stepSize;
          stepSize = warmRemainder > 5 ? catchUpStep : fixedStep) {
        step(stepSize);
        warmRemainder = f32(warmRemainder - stepSize);
      }
    }
    const initialState = snapshot();
    checkpoints = [initialState];

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > 60) return;
      const firstFrameSteps = nativeStepRate / fps;
      if (red && displayFps !== fps) {
        displayFps = fps;
        restore(initialState, 0);
        checkpoints = [initialState];
        firstFrameRemainder = f32(f32(1 / fps) + warmRemainder);
        for (let i = 0; i < firstFrameSteps; i++) firstFrameRemainder = f32(firstFrameRemainder - nativeStep);
      }
      const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
      const savedFrame = index * nativeStepRate;
      if (target < frame || savedFrame > frame) restore(checkpoints[index], savedFrame);
      while (frame < target) {
        step(nativeStep);
        frame++;
        // Run the remaining warm-up time after the first display's full particle steps.
        if (frame === firstFrameSteps && firstFrameRemainder >= birthBias) step(firstFrameRemainder);
        if (frame === checkpoints.length * nativeStepRate) checkpoints.push(snapshot());
      }
      const [px, py, pz] = position;
      for (const atom of active) {
        const phase = f32(atom.age * ageScale);
        const rgba = nativeColorAtTime({start: atom.color, keys: gradient}, phase).map(value => Math.round(value * 255));
        emit(f32(px - atom.x), f32(py - atom.z), f32(pz + atom.y),
          atom.source.size, atom.rx, atom.ry, atom.rz, ...rgba);
      }
    }};
  }

  global.MVStudioAutumnLeavesSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
