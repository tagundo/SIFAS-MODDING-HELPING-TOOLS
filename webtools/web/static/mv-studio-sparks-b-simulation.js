(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const speedSalt = 0x96aa4de3;
  const velocitySalt = 0xe0fbd834;
  const sizeSalt = 0x8d2c8431;
  const colorSalt = 0x591bc05c;
  const white = [255, 255, 255, 255];
  const stride = 12;
  const vector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite);
  const matches = (value, ...expected) => vector(value, expected.length) &&
    value.every((number, index) => number === expected[index]);
  const lerp = (a, b, u) => f32(a + f32(f32(b - a) * u));
  const blendByte = value => Math.trunc(f32(value * 255));
  const colorLerp = (a, b, weight) => a + ((128 + weight * (b - a)) >> 8);

  function supported(row, motion, particles) {
    if (!row || row.shape?.type !== 0 || row.shape.radiusThickness !== 1 ||
        !vector(row.shape.scale, 3) || !vector(row.shape.rotation, 3) ||
        ![row.delay, row.lifetime, row.size, row.speed, row.roll].every(pair => vector(pair, 2)) ||
        !Array.isArray(row.startColors) || row.startColors.length !== 2 ||
        !row.startColors.every(color => vector(color, 4) && color.every(v => v >= 0 && v <= 1)) ||
        !Array.isArray(row.lifeColors) || row.lifeColors.length !== 2 ||
        !row.lifeColors.every(keys => particles.validNativeColor({start: white, keys}))) return false;
    const curvePair = pair => Array.isArray(pair) && pair.length === 2 &&
      pair.every(value => motion.validCurve(value) && (value[0] === "constant" || value[1].length <= 16));
    if (!curvePair(row.sizeCurves) || !Array.isArray(row.bursts) || row.bursts.length > 3) return false;
    if (row.name === "grow") {
      return row.seed === null && row.capacity === 200 && row.duration === f32(.4) && row.rate === 0 &&
        row.shape.arcMode === 0 && row.shape.arc === 360 && row.shape.radius === f32(.1) &&
        matches(row.shape.scale, 1, 1, 1) && matches(row.shape.rotation, 0, 0, 0) &&
        matches(row.delay, 0, 0) && matches(row.lifetime, f32(.3), f32(.3)) && matches(row.size, 8, 8) &&
        matches(row.speed, 0, 0) && matches(row.roll, 0, f32(Math.PI)) && row.gravity === 0 &&
        row.bursts.length === 1 && matches(row.bursts[0], 0, 1) && row.sizeMultiplier === 1 &&
        row.velocityCurves === null && row.velocityMultipliers === null && row.clamp === null;
    }
    if (row.capacity !== 1000 || row.shape.arc !== 180 || !matches(row.shape.rotation, 90, 0, 0) ||
        !Array.isArray(row.velocityCurves) || row.velocityCurves.length !== 3 ||
        !row.velocityCurves.every(curvePair)) return false;
    if (row.name === "hibana") {
      return row.seed === 0 && row.duration === f32(1.8) && row.rate === 0 && row.shape.arcMode === 3 &&
        row.shape.radius === .5 && matches(row.shape.scale, 1.5, .25, 1) &&
        matches(row.delay, 0, 0) && matches(row.lifetime, 1, 2) &&
        matches(row.size, f32(.06), f32(.14)) && matches(row.speed, 2, 20) && matches(row.roll, 0, 0) &&
        row.gravity === f32(.8) && row.bursts.length === 3 && matches(row.bursts[0], 0, 100) &&
        matches(row.bursts[1], f32(.03), 75) && matches(row.bursts[2], f32(.06), 50) &&
        row.sizeMultiplier === 2 && matches(row.velocityMultipliers, 1, 1, 1) &&
        row.clamp?.limit === 1 && row.clamp.dampen === f32(.15);
    }
    return row.name === "late_kirakira" && row.seed === null && row.duration === 1 && row.rate === 75 &&
      row.shape.arcMode === 0 && row.shape.radius === 1.5 && matches(row.shape.scale, 4, .5, 1) &&
      matches(row.delay, f32(.1), f32(.2)) && matches(row.lifetime, 2, 1.5) &&
      matches(row.size, f32(.2), f32(.3)) && matches(row.speed, 0, 0) &&
      matches(row.roll, 0, f32(6.283185)) && row.gravity === f32(.2) &&
      row.bursts.length === 1 && matches(row.bursts[0], 0, 150) && row.sizeMultiplier === 1 &&
      matches(row.velocityMultipliers, 1, 4, 1) && row.clamp === null;
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

  function create(row, requestedSeed) {
    const particles = global.MVStudioStageParticles, motion = global.MVStudioStageMotion;
    if (!particles || !motion || !supported(row, motion, particles)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep: dt, nativeStepRate,
      nativeSpherePosition} = particles;
    const {evaluate} = motion;
    const seed = row.seed ?? requestedSeed;
    if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) return null;
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shapeDraw = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const acceleration = f32(row.gravity * f32(-9.81));
    const grow = row.name === "grow";
    const lifeSources = row.lifeColors.map(keys => ({start: white, keys}));
    const records = [];
    const active = [];
    const maxFrame = Math.ceil((row.delay[1] + row.duration + Math.max(...row.lifetime) + dt) * nativeStepRate);
    let frame = 0, clock = 0, carry = 0, burst = 0;
    let delay = lerp(row.delay[0], row.delay[1], nativeUnit(nativeRandom(seed)()));

    function damping(step) {
      return row.clamp ? f32(1 - f32(Math.pow(f32(1 - row.clamp.dampen), f32(step * 30)))) : 0;
    }
    const ordinaryDamping = damping(dt);
    function particleCurve(curves, scalar, u, weight) {
      const low = f32(f32(evaluate(curves[0], u)) * scalar);
      const high = f32(f32(evaluate(curves[1], u)) * scalar);
      return lerp(low, high, weight);
    }

    function birth(lane, slot, count) {
      const draw = initial[lane], shape = shapeDraw[lane];
      const word = draw();
      const life = lerp(row.lifetime[0], row.lifetime[1], nativeUnit(draw()));
      const size = lerp(row.size[0], row.size[1], nativeUnit(draw()));
      const roll = lerp(row.roll[0], row.roll[1], nativeUnit(draw()));
      const startWeight = nativeUnit(draw());
      const startColor = row.startColors[0].map((value, i) =>
        Math.trunc(f32(f32(lerp(value, row.startColors[1][i], startWeight) * 255) + .5)));
      const speed = lerp(row.speed[0], row.speed[1], salted(word, speedSalt));
      const turnLimit = f32(f32(f32(row.shape.arc / 360) * 2) * f32(Math.PI));
      const angleFraction = row.shape.arcMode === 3 ? f32(slot * f32(1 / Math.max(1, count - 1))) :
        nativeUnit(shape());
      const turns = f32(f32(turnLimit * angleFraction) * .15915493667125702);
      const axes = nativeSpherePosition(turns, nativeUnit(shape()), nativeUnit(shape()), row.shape.radius, row.shape.scale);
      const position = grow ? [-axes[0], axes[1], axes[2]] : [-axes[0], -axes[2], axes[1]];
      const magnitude = Math.sqrt(position.reduce((sum, v) => sum + v * v, 0));
      const velocity = position.map(value => magnitude > 0 ? f32(f32(value / magnitude) * speed) : 0);
      const weights = nativeRandom((word + velocitySalt) >>> 0);
      // ARM reciprocal refinement rounds one ULP below division for .3.
      return {position, velocity, startColor, size, roll, life: grow ? 3.3333330154418945 : f32(1 / life), age: 0,
        sizeWeight: salted(word, sizeSalt), colorWeight: blendByte(salted(word, colorSalt)),
        motionWeights: Array.from({length: 3}, () => nativeUnit(weights())), movement: [...velocity]};
    }

    function advance(particle, step, damp) {
      const {position, velocity, movement} = particle;
      const phase = f32(particle.age * fraction);
      const extra = row.velocityCurves ? row.velocityCurves.map((curve, axis) => (axis === 0 ? -1 : 1) *
        particleCurve(curve, row.velocityMultipliers[axis], phase, particle.motionWeights[axis])) : [0, 0, 0];
      velocity[1] = f32(velocity[1] + f32(acceleration * step));
      for (let axis = 0; axis < 3; axis++) movement[axis] = f32(velocity[axis] + extra[axis]);
      if (row.clamp) {
        const [x, y, z] = movement;
        const square = f32(f32(x * x) + f32(f32(y * y) + f32(z * z)));
        const reciprocal = f32(1 / Math.sqrt(square)), speed = f32(square * reciprocal);
        if (speed > row.clamp.limit) {
          const target = lerp(speed, row.clamp.limit, damp);
          for (let axis = 0; axis < 3; axis++) {
            velocity[axis] = f32(f32(f32(movement[axis] * reciprocal) * target) - extra[axis]);
            movement[axis] = f32(velocity[axis] + extra[axis]);
          }
        }
      }
      for (let axis = 0; axis < 3; axis++) position[axis] = f32(position[axis] + f32(movement[axis] * step));
      particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
    }

    function emitStep() {
      if (clock >= row.duration) return;
      if (delay >= dt) {
        delay = f32(delay - dt);
        return;
      }
      const interval = delay > 0 ? f32(dt - delay) : dt;
      delay = 0;
      const previous = clock;
      clock = f32(clock + interval);
      // The native nonlooping emitter stops at the first step that crosses
      // duration. Existing particles continue moving and fading.
      if (clock >= row.duration) return;
      const amount = f32(f32(clock - previous) * row.rate);
          const total = f32(amount + carry), continuous = Math.trunc(total);
          carry = f32(total - continuous);
          let burstCount = 0;
          while (burst < row.bursts.length && row.bursts[burst][0] < clock) {
            burstCount += row.bursts[burst++][1];
          }
          const count = burstCount + continuous, births = [];
          for (let slot = 0; slot < count; slot += 4) {
            for (let lane = 0; lane < 4; lane++) {
              const index = slot + lane;
              const particle = birth(lane, index, count);
              if (index >= count) continue;
              const phase = index >= continuous ? birthBias : Math.min(1, Math.max(birthBias,
                f32(f32(index + carry) * f32(1 / amount))));
              const within = f32(interval * phase);
              advance(particle, within, damping(within));
              births.push(particle);
            }
          }
          // The native SIMD writer fills the partial group's trailing slots.
          const remainder = active.length % 4;
          const pivot = remainder ? Math.max(0, births.length - (4 - remainder)) : 0;
          for (let i = 0; i < births.length; i++) {
            active.push(births[(pivot + i) % births.length]);
          }
    }

    function step() {
      for (const particle of active) advance(particle, dt, ordinaryDamping);
      cull(active);
      emitStep();
      if (!active.length) return;
      const output = new Float32Array(active.length * stride);
      for (const [index, particle] of active.entries()) {
        const u = f32(particle.age * fraction);
        const size = f32(particle.size * Math.max(0, particleCurve(row.sizeCurves, row.sizeMultiplier, u, particle.sizeWeight)));
        const from = nativeColorAtTime(lifeSources[0], u), to = grow ? from : nativeColorAtTime(lifeSources[1], u);
        const rgba = particle.startColor.map((start, axis) => {
          const color = colorLerp(Math.round(from[axis] * 255), Math.round(to[axis] * 255), particle.colorWeight);
          return Math.floor((start * color + 127) / 255);
        });
        output.set([...particle.position, ...particle.movement, size, particle.roll, ...rgba], index * stride);
      }
      records[frame] = output;
    }

    return {
      sample(time, fps, emit) {
        const target = nativeFrame(time, fps);
        if (target < 1 || target > maxFrame) return;
        while (frame < target) {
          frame++;
          step();
        }
        const values = records[target];
        if (!values) return;
        for (let i = 0; i < values.length; i += stride) {
          emit(values[i], values[i + 1], values[i + 2], values[i + 3], values[i + 4], values[i + 5],
            values[i + 6], values[i + 7], values[i + 8], values[i + 9], values[i + 10], values[i + 11]);
        }
      },
    };
  }

  global.MVStudioSparksBSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
