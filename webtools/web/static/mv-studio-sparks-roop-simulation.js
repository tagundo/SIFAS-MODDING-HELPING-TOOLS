(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const velocitySalt = 0xe0fbd834;
  const sizeSalt = 0x8d2c8431;
  const colorSalt = 0x591bc05c;
  const white = [255, 255, 255, 255];
  const checkpointSize = 4;
  const matches = (value, ...expected) => Array.isArray(value) && value.length === expected.length &&
    value.every((part, index) => part === expected[index]);
  const lerp = (start, end, weight) => f32(start + f32(f32(end - start) * weight));

  function inverseLifetime(value) {
    // The two float32 Newton steps preserve InitialModule's cull ages.
    const scale = 2 ** -Math.floor(Math.log2(value));
    const bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    estimate = f32(estimate * f32(2 - value * estimate));
    return f32(estimate * f32(2 - value * estimate));
  }

  function supported(row, motion, particles) {
    const shape = row?.shape;
    const role = /^sparks_([LR])([12])$/.exec(row?.name);
    if (!role) return false;
    const side = role[1] === "L" ? -1 : 1;
    const outer = role[2] === "2";
    const turn = f32(Math.SQRT1_2);
    const curvePair = pair => Array.isArray(pair) && pair.length === 2 &&
      pair.every(value => motion.validCurve(value) && (value[0] === "constant" || value[1].length <= 16));
    return row.seed === null && row.duration === 13 && row.rate === (outer ? 200 : 100) &&
      row.capacity === 1000 && row.maxViewportWidth === .5 && row.clamp === null && row.stretch === null &&
      matches(row.delay, 0, 0) && matches(row.lifetime, 3, 2) && matches(row.speed, 0, 0) &&
      matches(row.size, f32(.2), f32(.3)) && matches(row.roll, 0, f32(6.283185)) &&
      row.gravity === f32(.1) && Array.isArray(row.bursts) && row.bursts.length === 0 &&
      matches(row.position, side * (outer ? 9.5 : 7), f32(9.2), f32(outer ? -.95 : -4.8)) &&
      Array.isArray(row.rotation) && matches(row.rotation.map(f32), 0, outer ? -side * turn : 0, 0, outer ? turn : 1) &&
      shape?.type === 0 && shape.radius === 1.5 && shape.radiusThickness === 1 &&
      shape.arc === 180 && shape.arcMode === 0 && matches(shape.rotation, 90, 0, 0) &&
      matches(shape.scale, outer ? 4 : 2, .5, outer ? 1 : .5) &&
      matches(row.uv, .25, .25, .75, .25) && row.sizeMultiplier === 1 && curvePair(row.sizeCurves) &&
      matches(row.velocityMultipliers, 1, 4, 1) && Array.isArray(row.velocityCurves) &&
      row.velocityCurves.length === 3 && row.velocityCurves.every(curvePair) &&
      Array.isArray(row.startColors) && row.startColors.length === 2 &&
      row.startColors.every(color => Array.isArray(color) && color.length === 4 &&
        color.every(value => Number.isFinite(value) && value >= 0 && value <= 1)) &&
      Array.isArray(row.lifeColors) && row.lifeColors.length === 2 &&
      row.lifeColors.every(keys => particles.validNativeColor({start: white, keys}));
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles, motion = global.MVStudioStageMotion;
    if (!particles || !motion || !supported(row, motion, particles) ||
        !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) return null;
    const {nativeRandom, nativeUnit, nativeSpherePosition, nativeColorAtTime, nativeFrame,
      nativeStep: dt, nativeStepRate: checkpointFrames} = particles;
    const {evaluate} = motion;
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shapeDraw = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const turnLimit = f32(f32(f32(row.shape.arc / 360) * 2) * f32(Math.PI));
    const [px, py, pz] = row.position;
    const cosine = f32(1 - 2 * row.rotation[1] ** 2);
    const sine = f32(2 * row.rotation[1] * row.rotation[3]);
    const gravityStep = gravityDelta(dt);
    const lifeColors = row.lifeColors.map(keys => ({start: white, keys}));
    const authored = [], birthFrames = [[]], checkpoints = [new Float32Array()];
    const maxFrame = Math.ceil((row.duration + row.lifetime[0]) * checkpointFrames) + 2;
    let frame = 0, clock = 0, carry = 0, active = [];

    function gravityDelta(step) {
      return f32(f32(f32(-9.81) * step) * row.gravity);
    }

    function advance(particle, step, gravity) {
      const source = authored[particle.id];
      const phase = f32(particle.age * fraction);
      const [low, high] = row.velocityCurves[1];
      const scalar = row.velocityMultipliers[1];
      const drift = lerp(f32(f32(evaluate(low, phase)) * scalar), f32(f32(evaluate(high, phase)) * scalar),
        source.velocityWeight);
      particle.velocity = f32(particle.velocity + gravity);
      particle.y = f32(particle.y + f32(f32(particle.velocity + drift) * step));
      particle.age = f32(particle.age + f32(f32(step * 100) * source.inverseLife));
    }

    function birth(lane) {
      const draw = initial[lane], shape = shapeDraw[lane];
      const word = draw();
      const life = lerp(row.lifetime[0], row.lifetime[1], nativeUnit(draw()));
      const width = lerp(row.size[0], row.size[1], nativeUnit(draw()));
      const roll = lerp(row.roll[0], row.roll[1], nativeUnit(draw()));
      const colorWeight = nativeUnit(draw());
      const turns = f32(f32(turnLimit * nativeUnit(shape())) * .15915493667125702);
      const [x, y, z] = nativeSpherePosition(turns, nativeUnit(shape()), nativeUnit(shape()),
        row.shape.radius, row.shape.scale);
      const birthX = f32(px + f32(f32(-x * cosine) + f32(y * sine)));
      const birthZ = f32(pz + f32(f32(y * cosine) + f32(x * sine)));
      const color = row.startColors[0].map((value, index) =>
        Math.trunc(f32(f32(lerp(value, row.startColors[1][index], colorWeight) * 255) + .5)));
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      velocity(); // Native X consumes a draw even with both zero curves.
      const id = authored.length;
      authored.push({x: birthX, z: birthZ, roll, width, color, inverseLife: inverseLifetime(life),
        velocityWeight: nativeUnit(velocity()), sizeWeight: nativeUnit(nativeRandom((word + sizeSalt) >>> 0)()),
        colorMix: Math.trunc(f32(nativeUnit(nativeRandom((word + colorSalt) >>> 0)()) * 255))});
      return {id, y: f32(py - z), velocity: 0, age: 0};
    }

    function prepareBirths() {
      const births = [];
      birthFrames.push(births);
      if (clock >= row.duration) return;
      const previous = clock;
      clock = f32(clock + dt);
      if (clock >= row.duration) return;
      const amount = f32(f32(clock - previous) * row.rate), total = f32(amount + carry);
      const count = Math.trunc(total);
      carry = f32(total - count);
      if (!count) return;
      // A 100 or 200 Hz source emits at most four lanes per 60 Hz step.
      for (let lane = 0; lane < 4; lane++) {
        if (lane >= count) {
          for (let i = 0; i < 5; i++) initial[lane]();
          for (let i = 0; i < 3; i++) shapeDraw[lane]();
          continue;
        }
        const particle = birth(lane);
        const portion = f32(f32(lane + carry) * f32(1 / amount));
        const step = f32(dt * Math.min(1, Math.max(birthBias, portion)));
        advance(particle, step, gravityDelta(step));
        births.push(particle);
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

    function step() {
      for (const particle of active) advance(particle, dt, gravityStep);
      cull();
      frame++;
      if (frame === birthFrames.length) prepareBirths();
      const births = birthFrames[frame];
      // A partial storage group takes the last lanes of a crossing write.
      const firstLane = Math.max(0, births.length - (4 - active.length % 4));
      for (let i = 0; i < births.length; i++) active.push({...births[(i + firstLane) % births.length]});
      if (frame === checkpoints.length * checkpointFrames) {
        const saved = new Float32Array(active.length * checkpointSize);
        for (let i = 0; i < active.length; i++) {
          const particle = active[i];
          saved.set([particle.id, particle.y, particle.velocity, particle.age], i * checkpointSize);
        }
        checkpoints.push(saved);
      }
    }

    function restore(snapshot, at) {
      active = [];
      for (let i = 0; i < snapshot.length; i += checkpointSize) {
        active.push({id: snapshot[i], y: snapshot[i + 1], velocity: snapshot[i + 2], age: snapshot[i + 3]});
      }
      frame = at;
    }

    return {
      sample(elapsed, fps, emit) {
        const target = nativeFrame(elapsed, fps);
        if (target < 1 || target > maxFrame) return;
        const i = Math.min(checkpoints.length - 1, Math.floor(target / checkpointFrames));
        const savedFrame = i * checkpointFrames;
        if (target < frame || savedFrame > frame) restore(checkpoints[i], savedFrame);
        while (frame < target) step();
        for (const particle of active) {
          const {x, z, width, roll, color, sizeWeight, colorMix} = authored[particle.id];
          const phase = f32(particle.age * fraction);
          const scale = Math.max(0, lerp(f32(evaluate(row.sizeCurves[0], phase)),
            f32(evaluate(row.sizeCurves[1], phase)), sizeWeight));
          const size = f32(width * scale);
          const low = nativeColorAtTime(lifeColors[0], phase), high = nativeColorAtTime(lifeColors[1], phase);
          const rgba = color.map((start, index) => {
            const a = Math.round(low[index] * 255), b = Math.round(high[index] * 255);
            const dye = a + ((128 + colorMix * (b - a)) >> 8);
            return Math.floor((start * dye + 127) / 255);
          });
          emit(x, particle.y, z, size, size, roll, ...rgba);
        }
      },
    };
  }

  global.MVStudioSparksRoopSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
