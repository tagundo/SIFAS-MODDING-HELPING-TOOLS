(function (global) {
  "use strict";

  const f32 = Math.fround;
  const checkpointSeconds = 2;
  const fixedStep = f32(.02);
  const catchUpStep = f32(.2);
  const firstFrameBias = f32(.0001);
  const birthBias = f32(1e-6);
  const fraction = f32(.01);
  const velocitySalt = 0xe0fbd834;
  const spinSalt = 0x6aed452e;
  const spinSignSalt = 0xff2bb1a4;
  const lightNames = new Set(["light_big", "light_smole", "light_smole_L", "light_smole_R"]);
  const vector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite);
  const pairOf = (value, a, b) => vector(value, 2) && value[0] === a && value[1] === b;
  const lerp = (a, b, u) => f32(a + f32(f32(b - a) * u));

  function supported(row, motion) {
    if (!row || !vector(row.position, 3) || row.position.some(value => Math.abs(value) > 100) ||
        !vector(row.rotation, 4) || row.rotation[0] || row.rotation[2] ||
        Math.abs(Math.hypot(...row.rotation) - 1) >= 1e-5 ||
        !vector(row.box, 3) || !Number.isInteger(row.seed) || row.seed < 0 || row.seed > 0xffffffff ||
        row.cycle !== 50 || !pairOf(row.rollRange, f32(6.283185), f32(-6.283185)) ||
        !pairOf(row.rollSpeedRange, f32(-.2617994), f32(.2617994))) return false;
    if (lightNames.has(row.name)) {
      const big = row.name === "light_big", side = row.name.endsWith("_L") || row.name.endsWith("_R");
      return row.lifetime === 8 && row.rate === 0 && row.burstPeriod === 1 &&
        row.box[0] === (side ? 2 : 8) && row.box[1] === 1 && row.box[2] === 1 &&
        vector(row.size, 3) && row.size[0] === (big ? 4 : 2) && row.size[1] === (big ? 1 : .5) &&
        pairOf(row.velocityY, -.5, -1.5);
    }
    return row.name === "stars" && row.lifetime === 5 && row.rate === 10 && row.burstPeriod === 0 &&
      row.box[0] === 8 && row.box[1] === 1 && row.box[2] === 0 &&
      pairOf(row.size, f32(.3), .5) && row.sizePeriod === f32(.05) &&
      motion.validCurve(row.sizeCurve) && vector(row.velocityMultipliers, 3) &&
      Array.isArray(row.velocityCurves) && row.velocityCurves.length === 3 &&
      row.velocityCurves.every(pair => Array.isArray(pair) && pair.length === 2 && pair.every(motion.validCurve));
  }

  function clockStep(previous, dt, cycle, rate) {
    const next = f32(previous + dt);
    if (next <= cycle) return [next, f32(f32(next - previous) * rate)];
    const wrapped = f32(next - cycle);
    return [wrapped, f32(f32(f32(cycle - previous) * rate) + f32(wrapped * rate))];
  }

  function initialCarry(lifetime, cycle, rate) {
    // Unity's startup counts continuous births on a fixed .02-scan.
    // It carries the remaining fraction back to the actual warm simulation.
    let clock = cycle - lifetime, elapsed = 0, carry = 0;
    while (f32(elapsed + firstFrameBias) < lifetime) {
      const [next, amount] = clockStep(clock, fixedStep, cycle, rate);
      const emitted = f32(amount + carry);
      carry = f32(emitted - Math.trunc(emitted));
      clock = next;
      elapsed = f32(elapsed + fixedStep);
    }
    return f32(f32(1 - carry) + firstFrameBias);
  }

  function create(row) {
    const motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    if (!motion || !particles || !supported(row, motion)) return null;
    const {nativeRandom, nativeUnit} = particles, {evaluate} = motion;
    const {seed, lifetime, cycle, rate, burstPeriod, box, position, rotation} = row;
    const stars = row.name === "stars", inverseLife = f32(1 / lifetime);
    const [rollStart, rollEnd] = row.rollRange, [spinStart, spinEnd] = row.rollSpeedRange;
    const cosine = f32(1 - 2 * rotation[1] * rotation[1]), sine = f32(2 * rotation[1] * rotation[3]);
    let frame = 0, fps = 0, clock, carry, births, active, initial, shape, warmed;
    let checkpoints;

    function starVelocity(axis, phase, weight) {
      const [lowCurve, highCurve] = row.velocityCurves[axis];
      // The native two-curve kernel applies the same scalar to both curves.
      const scalar = row.velocityMultipliers[axis];
      const low = f32(f32(evaluate(lowCurve, phase)) * scalar);
      const high = f32(f32(evaluate(highCurve, phase)) * scalar);
      return lerp(low, high, weight);
    }

    function advance(particle, dt, phaseDelta) {
      const {weights} = particle;
      let vx = 0, vy = particle.velocityY, vz = 0;
      if (stars) {
        const phase = f32(particle.phase * fraction);
        const localX = -starVelocity(0, phase, weights[0]), localZ = starVelocity(2, phase, weights[2]);
        vx = f32(f32(cosine * localX) + f32(sine * localZ));
        vy = starVelocity(1, phase, weights[1]);
        vz = f32(f32(-sine * localX) + f32(cosine * localZ));
      }
      particle.x = f32(particle.x + f32(vx * dt));
      particle.y = f32(particle.y + f32(vy * dt));
      particle.z = f32(particle.z + f32(vz * dt));
      particle.roll = f32(particle.roll + f32(particle.spin * dt));
      particle.phase = f32(particle.phase + phaseDelta);
    }

    function birth(index, dt, amount, continuous) {
      const particleSeed = initial();
      initial(); // Lifetime consumes its draw even when fixed.
      const widthWord = initial();
      const width = stars ? lerp(row.size[0], row.size[1], nativeUnit(widthWord)) : row.size[0];
      if (!stars) {
        initial(); // Authored independent Y size.
        initial(); // Authored independent Z size.
      }
      const roll = lerp(rollStart, rollEnd, nativeUnit(initial()));
      const colorWord = initial();
      const stamp = stars ? f32(nativeUnit(colorWord) * 65535) : 0;
      const local = box.map(scale => f32(scale * f32(nativeUnit(shape()) - .5)));
      const [x, y, z] = [-local[0], local[1], local[2]];
      const drawVelocity = nativeRandom((particleSeed + velocitySalt) >>> 0);
      const weights = [nativeUnit(drawVelocity()), nativeUnit(drawVelocity()), nativeUnit(drawVelocity())];
      const velocityY = stars ? 0 : lerp(row.velocityY[0], row.velocityY[1], weights[1]);
      const spinUnit = nativeUnit(nativeRandom((particleSeed + spinSalt) >>> 0)());
      const spinSign = nativeUnit(nativeRandom((particleSeed + spinSignSalt) >>> 0)()) > 0 ? 1 : -1;
      const spin = spinSign * lerp(spinStart, spinEnd, spinUnit);
      const particle = {
        x: f32(position[0] + f32(f32(cosine * x) + f32(sine * z))),
        y: f32(position[1] + y),
        z: f32(position[2] + f32(f32(-sine * x) + f32(cosine * z))),
        phase: 0, roll, spin, width, height: stars ? width : row.size[1], stamp, weights, velocityY,
      };
      const ageFraction = index < continuous ? f32(f32(index + carry) * (amount >= firstFrameBias ? f32(1 / amount) : 1)) : 0;
      const param = Math.min(1, Math.max(birthBias, ageFraction));
      const within = f32(dt * param);
      advance(particle, within, f32(f32(within * 100) * inverseLife));
      active.push(particle);
      births++;
    }

    function step(dt) {
      const phaseDelta = f32(f32(dt * 100) * inverseLife);
      for (const particle of active) advance(particle, dt, phaseDelta);
      // The native cull removes a dead slot by moving the final live slot.
      let index = 0;
      while (index < active.length) {
        if (active[index].phase <= 100) {
          index++;
        } else {
          const last = active.pop();
          if (index < active.length) active[index] = last;
        }
      }
      const previous = clock;
      const [next, amount] = clockStep(previous, dt, cycle, rate);
      clock = next;
      const combined = f32(amount + carry);
      const continuous = Math.trunc(combined);
      carry = f32(combined - continuous);
      const burst = burstPeriod && (next < previous || previous === 0 ||
        Math.trunc(next / burstPeriod) > Math.trunc(previous / burstPeriod)) ? 1 : 0;
      // These profiles emit at most one particle per update. The earliest
      // active time begins with a separate fractional continuous birth.
      for (let i = 0; i < continuous + burst; i++) {
        birth(i, dt, amount, continuous);
      }
    }

    function snapshot() {
      return {clock, carry, births, active: active.map(particle => ({...particle}))};
    }

    function restore(source, target) {
      ({clock, carry, births} = source);
      active = source.active.map(particle => ({...particle}));
      frame = target;
      initial = nativeRandom(seed);
      shape = nativeRandom(seed);
      // One accepted birth advances its two independent random streams.
      const drawsPerBirth = stars ? 5 : 7;
      for (let draw = 0; draw < births * drawsPerBirth; draw++) initial();
      for (let draw = 0; draw < births * 3; draw++) shape();
    }

    function resetCadence(cadence) {
      if (!warmed) {
        initial = nativeRandom(seed);
        shape = nativeRandom(seed);
        active = [];
        births = 0;
        clock = cycle - lifetime;
        carry = initialCarry(lifetime, cycle, rate);
        let remaining = lifetime;
        for (let dt = remaining > 5 ? catchUpStep : fixedStep; remaining >= dt;
            dt = remaining > 5 ? catchUpStep : fixedStep) {
          step(dt);
          remaining = f32(remaining - dt);
        }
        warmed = snapshot();
        frame = 0;
      } else {
        restore(warmed, 0);
      }
      fps = cadence;
      checkpoints = [warmed];
    }

    return {
      sample(elapsed, cadence, emit) {
        if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > 60 || (cadence !== 30 && cadence !== 60)) return;
        const target = Math.floor(elapsed * cadence + 1e-9);
        if (fps !== cadence) resetCadence(cadence);
        const checkpointFrames = fps * checkpointSeconds;
        const index = Math.min(checkpoints.length - 1, Math.floor(target / checkpointFrames));
        const storedFrame = index * checkpointFrames;
        if (target < frame || storedFrame > frame) restore(checkpoints[index], storedFrame);
        const dt = f32(1 / fps);
        while (frame < target) {
          step(dt);
          frame++;
          if (frame === checkpoints.length * checkpointFrames) checkpoints.push(snapshot());
        }
        for (const particle of active) {
          const phase = f32(particle.phase * fraction);
          let width = particle.width, height = particle.height;
          if (stars) {
            const period = row.sizePeriod;
            const time = phase <= period ? phase : f32(phase - f32(Math.floor(phase / period) * period));
            const scale = Math.max(0, f32(evaluate(row.sizeCurve, time)));
            width = f32(width * scale);
            height = width;
          }
          emit(particle.x, particle.y, particle.z, width, height, particle.roll, phase, particle.stamp);
        }
      },
    };
  }

  global.MVStudioFallingSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
