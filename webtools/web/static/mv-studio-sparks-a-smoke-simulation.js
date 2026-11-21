(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const velocitySalt = 0xe0fbd834;
  const speedSalt = 0x96aa4de3;
  const spinSalt = 0x6aed452e;
  const spinSignSalt = 0xff2bb1a4;
  const sizeSalt = 0x8d2c8431;
  const colorSalt = 0x591bc05c;
  const white = [255, 255, 255, 255];
  const stride = 10;
  const matches = (value, ...expected) => Array.isArray(value) && value.length === expected.length &&
    value.every((part, index) => part === expected[index]);
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const blendByte = (a, b, weight) => a + ((128 + weight * (b - a)) >> 8);
  const packByte = value => Math.trunc(f32(f32(value * 255) + .5));

  function inverseLifetime(value) {
    const scale = 2 ** -Math.floor(Math.log2(value));
    const bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    estimate = f32(estimate * f32(2 - value * estimate));
    return f32(estimate * f32(2 - value * estimate));
  }

  function supported(row, motion, particles) {
    const shape = row?.shape;
    const curve = value => motion.validCurve(value) && (value[0] === "constant" || value[1].length <= 2);
    const pair = value => Array.isArray(value) && value.length === 2 && value.every(curve);
    const initial = (profile, min, max) => profile?.minMultiplier === min &&
      profile.maxMultiplier === max && pair(profile.curves);
    return row?.name === "smoke" && row.delay === 0 && row.duration === f32(.3) && row.capacity === 1000 &&
      shape?.type === 8 && shape.radius === .25 && shape.radiusMode === 1 && shape.radiusSpeed === 10 &&
      shape.radiusThickness === 1 && shape.angle === 8 && shape.length === 6 && shape.arc === 360 &&
      shape.arcMode === 0 && matches(shape.scale, 1, 1, 1) && matches(shape.rotation, 0, 0, 0) &&
      matches(row.rotation?.map(f32), -f32(Math.SQRT1_2), 0, 0, f32(Math.SQRT1_2)) &&
      matches(row.roll, -f32(6.283185), f32(6.283185)) &&
      matches(row.rollSpeed, f32(1.57079625), -f32(1.57079625)) &&
      matches(row.velocityY, f32(.2), f32(.02)) && row.rateMultiplier === 30 && curve(row.rateCurve) &&
      initial(row.initialLifetime, 3, 1.5) && initial(row.initialSize, 1, 2) && initial(row.initialSpeed, 5, 15) &&
      row.clamp?.dampen === f32(.15) && curve(row.clamp.curve) &&
      row.sizeMultiplier === 2 && pair(row.sizeCurves) && row.sortMode === 3 &&
      Array.isArray(row.startGradients) && row.startGradients.length === 2 &&
      row.startGradients.every((gradient, i) => gradient?.rgb?.length === 2 && gradient?.alpha?.length === 2 &&
        matches(gradient.rgb[0], 0, 1, i ? 1 : f32(.9266637), i ? 1 : f32(.8028329)) &&
        matches(gradient.rgb[1], 65535, 1, 1, 1) &&
        matches(gradient.alpha[0], 0, f32((i ? 120 : 80) / 255)) &&
        matches(gradient.alpha[1], 65535, f32((i ? 120 : 80) / 255))) &&
      Array.isArray(row.lifeColors) && row.lifeColors.length === 2 &&
      row.lifeColors.every(keys => particles.validNativeColor({start: white, keys}));
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles, motion = global.MVStudioStageMotion;
    if (!particles || !motion || !supported(row, motion, particles) ||
        (seed !== 100 && seed !== 200)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep: dt, nativeStepRate} = particles;
    const positiveAge = f32(1e-6);
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const coneAngle = f32(row.shape.angle * f32(Math.PI / 180));
    const coneX = f32(Math.sin(coneAngle)), coneY = f32(Math.cos(coneAngle));
    const arc = f32(row.shape.arc * f32(Math.PI / 180));
    const maxFrame = Math.ceil((row.duration + row.initialLifetime.maxMultiplier) * nativeStepRate) + 2;
    const lifeColors = row.lifeColors.map(keys => ({start: white, keys}));
    const records = [], active = [];
    const normalDamping = damping(dt);
    let clock = 0, carry = 0, frame = 0;

    function damping(step) {
      return f32(1 - f32(Math.pow(f32(1 - row.clamp.dampen), f32(step * 30))));
    }

    function evaluate([kind, keys], time, multiplier = 1) {
      if (kind === "constant") return f32(keys * multiplier);
      const [start, coefficients] = keys[0];
      if (keys[1] && time >= keys[1][0]) {
        return f32((kind === "cubic" ? keys[1][1][3] : keys[1][1]) * multiplier);
      }
      const offset = Math.max(0, f32(time - start));
      if (kind === "linear") return f32(motion.evaluate([kind, keys], time) * multiplier);
      const [a,b,c,d] = coefficients.map(value => f32(f32(value) * multiplier));
      return f32(d + f32(offset * f32(c + f32(offset * f32(b + f32(offset * a))))));
    }

    function curvePair(pair, scalar, time, weight) {
      return lerp(evaluate(pair[0], time, scalar), evaluate(pair[1], time, scalar), weight);
    }

    function startColor(time, weight) {
      const [low, high] = row.startGradients;
      const t = f32(f32(time * 65535) / 65535);
      const min = low.rgb[0].slice(1).map((value, axis) => packByte(lerp(value, low.rgb[1][axis + 1], f32(t))));
      const max = high.rgb[0].slice(1).map(packByte);
      min.push(packByte(low.alpha[0][1]));
      max.push(packByte(high.alpha[0][1]));
      return min.map((value, axis) => blendByte(value, max[axis], weight));
    }

    function birth(lane, time, speedTime) {
      const draw = initial[lane], nextShape = shape[lane];
      const word = draw(), lifeWeight = nativeUnit(draw()), widthWeight = nativeUnit(draw());
      const roll = lerp(row.roll[0], row.roll[1], nativeUnit(draw()));
      const color = startColor(time, Math.trunc(f32(nativeUnit(draw()) * 255)));
      const curve = (profile, weight) => curvePair(profile.curves, profile.maxMultiplier, time, weight);
      const life = inverseLifetime(curve(row.initialLifetime, lifeWeight)), width = curve(row.initialSize, widthWeight);
      // ShapeModule evaluates speed at the substep birth time. InitialModule
      // uses the end-of-step emitter phase for lifetime, width and color.
      const speed = curvePair(row.initialSpeed.curves, row.initialSpeed.maxMultiplier,
        speedTime, salted(word, speedSalt));
      const heading = f32(arc * nativeUnit(nextShape())), radialWord = nativeUnit(nextShape());
      const radial = f32(Math.sqrt(f32(f32(1 - radialWord) + f32(f32(.001) * radialWord))));
      const x = f32(f32(Math.cos(heading)) * radial), z = f32(f32(Math.sin(heading)) * radial);
      const localX = -f32(coneX * x), localZ = -f32(coneX * z);
      const squared = f32(f32(localX * localX) + f32(f32(localZ * localZ) + f32(coneY * coneY)));
      const reciprocal = f32(1 / Math.sqrt(squared));
      const dx = f32(localX * reciprocal), dy = f32(coneY * reciprocal), dz = f32(localZ * reciprocal);
      const depth = f32(row.shape.length * nativeUnit(nextShape()));
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      velocity();
      const drift = lerp(row.velocityY[0], row.velocityY[1], nativeUnit(velocity()));
      const sign = salted(word, spinSignSalt) > 0 ? 1 : -1;
      const spin = sign * lerp(row.rollSpeed[0], row.rollSpeed[1], salted(word, spinSalt));
      return {
        x: f32(f32(-x * row.shape.radius) + f32(dx * depth)), y: f32(dy * depth),
        z: f32(f32(-z * row.shape.radius) + f32(dz * depth)),
        vx: f32(dx * speed), vy: f32(dy * speed), vz: f32(dz * speed),
        roll, spin, drift, age: 0, life, width, color,
        colorMix: Math.trunc(f32(salted(word, colorSalt) * 255)), sizeMix: salted(word, sizeSalt),
      };
    }

    function advance(particle, step, damp) {
      let {vx, vy, vz} = particle;
      vy = f32(vy + particle.drift);
      const squared = f32(f32(vx * vx) + f32(f32(vy * vy) + f32(vz * vz)));
      const reciprocal = f32(1 / Math.sqrt(squared)), speed = f32(squared * reciprocal);
      const limit = evaluate(row.clamp.curve, f32(particle.age * fraction));
      if (speed > limit) {
        const target = lerp(speed, limit, damp);
        vx = f32(f32(vx * reciprocal) * target);
        vy = f32(f32(vy * reciprocal) * target);
        vz = f32(f32(vz * reciprocal) * target);
      }
      particle.vx = vx;
      particle.vy = f32(vy - particle.drift);
      particle.vz = vz;
      particle.x = f32(particle.x + f32(vx * step));
      particle.y = f32(particle.y + f32(vy * step));
      particle.z = f32(particle.z + f32(vz * step));
      particle.roll = f32(particle.roll + f32(particle.spin * step));
      particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
    }

    function emitStep() {
      if (clock >= row.duration) return;
      const previous = clock;
      clock = f32(clock + dt);
      if (clock >= row.duration) return;
      const time = f32(clock / row.duration);
      const rate = evaluate(row.rateCurve, time, row.rateMultiplier);
      const amount = f32(f32(clock - previous) * rate);
      const total = f32(carry + amount), count = Math.trunc(total);
      carry = f32(total - count);
      if (count !== 1) return;
      // Slots for unrendered lanes still advance both SIMD RNG streams.
      const portion = Math.min(1, Math.max(positiveAge, f32(carry * f32(1 / amount))));
      const step = f32(dt * portion);
      const particle = birth(0, time, f32(f32(clock - step) / row.duration));
      for (let lane = 1; lane < 4; lane++) {
        for (let i = 0; i < 5; i++) initial[lane]();
        for (let i = 0; i < 3; i++) shape[lane]();
      }
      advance(particle, step, damping(step));
      active.push(particle);
    }

    function update(tick) {
      for (let index = 0; index < active.length; index++) {
        const particle = active[index];
        advance(particle, dt, normalDamping);
        if (particle.age <= 100) continue;
        const tail = active.pop();
        if (index < active.length) active[index] = tail;
        index--;
      }
      emitStep();
      if (!active.length) return;
      const output = new Float32Array(active.length * stride);
      const remainingTime = particle => f32(f32(100 - particle.age) / particle.life);
      const ordered = [...active].sort((a, b) => remainingTime(a) - remainingTime(b));
      for (const [index, particle] of ordered.entries()) {
        const age = f32(particle.age * fraction);
        const scale = Math.max(0, curvePair(row.sizeCurves, row.sizeMultiplier, age, particle.sizeMix));
        const width = f32(particle.width * scale);
        const low = nativeColorAtTime(lifeColors[0], age), high = nativeColorAtTime(lifeColors[1], age);
        const rgba = low.map((value, axis) => {
          const color = blendByte(Math.round(value * 255), Math.round(high[axis] * 255), particle.colorMix);
          return Math.floor((particle.color[axis] * color + 127) / 255);
        });
        output.set([particle.x, particle.y, particle.z, width, width, particle.roll, ...rgba], index * stride);
      }
      records[tick] = output;
    }

    return {
      sample(elapsed, fps, emit) {
        const target = nativeFrame(elapsed, fps);
        if (target < 1 || target > maxFrame) return;
        while (frame < target) update(++frame);
        const values = records[target];
        if (!values) return;
        for (let i = 0; i < values.length; i += stride) {
          emit(values[i], values[i + 1], values[i + 2], values[i + 3], values[i + 4],
            values[i + 5], values[i + 6], values[i + 7], values[i + 8], values[i + 9]);
        }
      },
    };
  }

  global.MVStudioSparksASmokeSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
