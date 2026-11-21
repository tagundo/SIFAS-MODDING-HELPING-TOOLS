(function (global) {
  "use strict";

  const f32 = Math.fround;
  const stepRate = 60;
  const dt = f32(1 / stepRate);
  const frameLimit = 2.5 * stepRate;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const spinSalt = 0x6aed452e;
  const spinSignSalt = 0xff2bb1a4;
  const speedSalt = 0x96aa4de3;
  const atlasSalt = 0x56b3dbb0;
  const stride = 8;
  const vector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite);
  const matches = (value, ...expected) => vector(value, expected.length) &&
    value.every((number, index) => number === expected[index]);
  const lerp = (a, b, u) => f32(a + f32(f32(b - a) * u));

  function supported(row, motion) {
    if (!row || !vector(row.position, 3) || row.position.some(value => Math.abs(value) > 100)) return false;
    const {count, delay, seed, lifetime, shape, size, rollRange, spinRange, atlas} = row;
    const turn = f32(6.283185), angle = f32(1.04719758), spin = f32(12.56637);
    if (row.name === "light_big") {
      return count === 8 && delay === 0 && seed === 0 && lifetime === 1 &&
        shape?.type === 5 && matches(shape.scale, 8, 5, 1) && matches(size, 3, .75, f32(.1)) &&
        matches(rollRange, turn, -turn) && row.spinMultiplier === f32(13.962634) &&
        Array.isArray(row.spinCurves) && row.spinCurves.length === 2 && row.spinCurves.every(motion.validCurve) &&
        Array.isArray(row.velocityCurves) && row.velocityCurves.length === 3 &&
        row.velocityCurves.every(motion.validCurve);
    }
    if (seed !== 10354082 || delay !== .25 || !matches(spinRange, -spin, spin)) return false;
    if (row.name === "flash") {
      return count === 1 && lifetime === .75 && matches(size, 150, 150, 150) && matches(rollRange, 0, 0);
    }
    return row.name === "Fall" && count === 60 && lifetime === 1 && matches(size, .5, 1) &&
      matches(rollRange, -angle, angle) && matches(row.speedRange, 30, 10) &&
      shape?.type === 4 && shape.arcMode === 3 && matches(shape.scale, 1, 1, 1) &&
      shape.radius === f32(.1) && shape.arc === 360 && shape.angle === 45 && row.gravity === 2 &&
      row.clamp?.limit === 1 && row.clamp.dampen === f32(.1) &&
      matches(atlas?.tiles, 4, 4) && atlas.row === null && matches(atlas.start, .75, f32(.9999));
  }

  function substeps(elapsed, fps) {
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > frameLimit / stepRate ||
        (fps !== 30 && fps !== 60)) return -1;
    // Stock TimeManager limits a particle update to .03 seconds. A
    // 30 fps render therefore performs two of the same 60 Hz substeps.
    return Math.floor(elapsed * fps + 1e-9) * (stepRate / fps);
  }

  function birthStep(delay) {
    let frame = 1;
    while (delay >= dt) {
      delay = f32(delay - dt);
      frame++;
    }
    return {frame, elapsed: f32(f32(dt - delay) * birthBias)};
  }

  function phaseDelta(elapsed, inverseLife) {
    return f32(f32(elapsed * 100) * inverseLife);
  }

  function meshPhase(elapsed, fps, lifetime, delay) {
    if (lifetime !== f32(.6) || delay !== 0) return null;
    const target = substeps(elapsed, fps), start = birthStep(delay);
    if (target < start.frame) return null;
    // Exact reciprocal stored for the native .6-second Break particle.
    const inverseLife = 1.6666665077209473;
    let phase = phaseDelta(start.elapsed, inverseLife);
    const advance = phaseDelta(dt, inverseLife);
    for (let frame = start.frame; frame < target && phase <= 100; frame++) phase = f32(phase + advance);
    return phase <= 100 ? f32(phase * fraction) : null;
  }

  function create(row) {
    const motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    if (!motion || !particles || !supported(row, motion)) return null;
    const {nativeRandom, nativeUnit} = particles, {evaluate} = motion;
    const {seed, count, size, shape, rollRange, lifetime, delay, clamp} = row;
    const isFall = row.name === "Fall", isLight = row.name === "light_big";
    const inverseLife = f32(1 / lifetime);
    const first = birthStep(delay);
    const spinRanges = row.spinRange || [0, 0];
    const phasePerStep = phaseDelta(dt, inverseLife);
    const records = Array(frameLimit + 1);
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const acceleration = isFall ? f32(row.gravity * f32(-9.81)) : 0;
    const fallDamping = isFall ? damping(dt) : 0;
    let tick = first.frame - 1, population = [];

    function damping(elapsed) {
      return f32(1 - f32(Math.pow(f32(1 - clamp.dampen), f32(elapsed * 30))));
    }

    function sampleCone(slot, shapeDraw, particleSeed) {
      // Burst Spread places the shards at equal angles and consumes only
      // the radial word of each independent ShapeModule generator.
      const heading = 2 * Math.PI * slot / count;
      const u = nativeUnit(shapeDraw());
      const radius = f32(Math.sqrt(f32(f32(1 - u) + f32(f32(.001) * u))));
      const x = f32(-f32(Math.cos(heading)) * radius), y = f32(f32(Math.sin(heading)) * radius);
      const speed = lerp(row.speedRange[0], row.speedRange[1], salted(particleSeed, speedSalt));
      const sin = f32(Math.SQRT1_2), dx = f32(x * sin), dy = f32(y * sin), dz = sin;
      const magnitude = f32(Math.sqrt(f32(f32(dx * dx) + f32(f32(dy * dy) + f32(dz * dz)))));
      const reciprocal = f32(1 / magnitude);
      const velocity = [dx, dy, dz].map(axis => f32(f32(axis * reciprocal) * speed));
      return {offset: [f32(x * shape.radius), f32(y * shape.radius), 0], velocity};
    }

    function createBirths() {
      const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const shapeRand = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      for (let slot = 0; slot < count; slot++) {
        const lane = slot & 3, draw = initial[lane], shapeDraw = shapeRand[lane];
        const particleSeed = draw();
        draw(); // Lifetime draw is reserved even for a constant.
        const sizeWord = draw();
        const width = isFall ? lerp(size[0], size[1], nativeUnit(sizeWord)) : size[0];
        if (isLight) {
          draw(); // Independent starting Y size.
          draw(); // Independent starting Z size.
        }
        const roll = lerp(rollRange[0], rollRange[1], nativeUnit(draw()));
        draw(); // The packed starting color reserves the final draw.
        const spinWeight = salted(particleSeed, spinSalt);
        const spinSign = salted(particleSeed, spinSignSalt) > 0 ? 1 : -1;
        const spin = spinSign * lerp(spinRanges[0], spinRanges[1], spinWeight);
        let offset = [0, 0, 0], velocity = [0, 0, 0], atlasOffset = 0;
        if (isFall) {
          ({offset, velocity} = sampleCone(slot, shapeDraw, particleSeed));
          atlasOffset = lerp(row.atlas.start[0], row.atlas.start[1], salted(particleSeed, atlasSalt));
        } else if (isLight) {
          offset = shape.scale.map(scale => f32(scale * f32(nativeUnit(shapeDraw()) - .5)));
          offset[0] = -offset[0];
        }
        const position = row.position.map((axis, index) => f32(axis + offset[index]));
        population.push({position, velocity, width, height: isLight ? size[1] : width, roll, spin,
          spinSign, spinWeight, atlasOffset, phase: 0});
      }
    }

    function integrate(particle, elapsed, age, damp) {
      const {position, velocity} = particle;
      let vx = velocity[0], vy = velocity[1], vz = velocity[2], spin = particle.spin;
      if (isFall) {
        vy = f32(vy + f32(acceleration * elapsed));
        const speedSquare = f32(f32(vx * vx) + f32(f32(vy * vy) + f32(vz * vz)));
        const invSpeed = f32(1 / Math.sqrt(speedSquare));
        const speed = f32(speedSquare * invSpeed);
        const target = speed > clamp.limit ? lerp(speed, clamp.limit, damp) : speed;
        vx = velocity[0] = f32(f32(vx * invSpeed) * target);
        vy = velocity[1] = f32(f32(vy * invSpeed) * target);
        vz = velocity[2] = f32(f32(vz * invSpeed) * target);
      } else if (isLight) {
        const u = f32(particle.phase * fraction);
        const [velocityX, velocityY, velocityZ] = row.velocityCurves;
        vx = -f32(evaluate(velocityX, u));
        vy = f32(evaluate(velocityY, u));
        vz = f32(evaluate(velocityZ, u));
        const [low, high] = row.spinCurves, scalar = row.spinMultiplier;
        spin = particle.spinSign * lerp(f32(f32(evaluate(low, u)) * scalar),
          f32(f32(evaluate(high, u)) * scalar), particle.spinWeight);
      }
      position[0] = f32(position[0] + f32(vx * elapsed));
      position[1] = f32(position[1] + f32(vy * elapsed));
      position[2] = f32(position[2] + f32(vz * elapsed));
      particle.roll = f32(particle.roll + f32(spin * elapsed));
      particle.phase = f32(particle.phase + age);
    }

    function update(frame) {
      const spawned = frame === first.frame;
      if (spawned) createBirths();
      const elapsed = spawned ? first.elapsed : dt;
      const age = spawned ? phaseDelta(elapsed, inverseLife) : phasePerStep;
      const damp = isFall && spawned ? damping(elapsed) : fallDamping;
      for (const particle of population) integrate(particle, elapsed, age, damp);
      // Every particle in this burst has the same age and lifespan.
      if (population.length === 0 || population[0].phase > 100) {
        population = [];
        return;
      }
      const output = new Float32Array(population.length * stride);
      for (const [slot, particle] of population.entries()) {
        const {position, width, height, roll, phase, atlasOffset} = particle;
        output.set([position[0], position[1], position[2], width, height, roll, f32(phase * fraction), atlasOffset],
          slot * stride);
      }
      records[frame] = output;
    }

    return {
      sample(elapsed, fps, emit) {
        const frame = substeps(elapsed, fps);
        if (frame < first.frame) return;
        while (tick < frame) update(++tick);
        const values = records[frame];
        if (!values) return;
        for (let index = 0; index < values.length; index += stride) {
          emit(values[index], values[index + 1], values[index + 2], values[index + 3], values[index + 4],
            values[index + 5], values[index + 6], values[index + 7], index / stride);
        }
      },
    };
  }

  global.MVStudioBreakSimulation = {create, meshPhase};
})(typeof window !== "undefined" ? window : globalThis);
