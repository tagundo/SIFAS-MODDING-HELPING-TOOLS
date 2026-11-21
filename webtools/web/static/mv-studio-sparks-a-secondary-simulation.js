(function (global) {
  "use strict";

  const f32 = Math.fround;
  const ageScale = f32(.01);
  const birthBias = f32(1e-6);
  const velocitySalt = 0xe0fbd834;
  const atlasSalt = 0x56b3dbb0;
  const stride = 11;
  const white = [255, 255, 255, 255];
  const matches = (value, ...expected) => Array.isArray(value) && value.length === expected.length &&
    value.every((part, index) => part === expected[index]);
  const lerp = (start, end, weight) => f32(start + f32(f32(end - start) * weight));

  function inverseLifetime(value) {
    // InitialModule takes an ARM reciprocal estimate and refines it twice.
    const scale = 2 ** -Math.floor(Math.log2(value));
    const bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    estimate = f32(estimate * f32(2 - value * estimate));
    return f32(estimate * f32(2 - value * estimate));
  }

  function supported(row, motion, particles) {
    const shape = row?.shape;
    return row?.name === "hibana_02" && row.capacity === 1000 && row.duration === .5 &&
      row.delay === f32(.12) && row.gravity === f32(.1) &&
      shape?.type === 8 && shape.radius === .25 && shape.radiusThickness === 1 &&
      shape.angle === 18 && shape.length === 7 && shape.arc === 360 && shape.arcMode === 0 &&
      matches(shape.scale, 1, 1, 1) && matches(shape.rotation, -90, 0, 0) &&
      matches(row.lifetime, f32(.16), f32(.2)) && matches(row.roll, 0, f32(6.283185)) &&
      Array.isArray(row.size3D) && row.size3D.length === 3 &&
      row.size3D.every(range => matches(range, f32(.4), f32(.1))) &&
      matches(row.velocityY, 6, 2) && row.bursts?.length === 1 &&
      matches(row.bursts[0], 0, 60, 3, f32(.15)) &&
      row.sizeMultiplier === 1 && motion.validCurve(row.sizeCurve) &&
      (row.sizeCurve[0] === "constant" || row.sizeCurve[1].length <= 16) &&
      row.lifeColors?.length === 1 && particles.validNativeColor({start: white, keys: row.lifeColors[0]}) &&
      matches(row.atlas?.tiles, 4, 4) && matches(row.atlas.start, 0, .125);
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles, motion = global.MVStudioStageMotion;
    if (!particles || !motion || !supported(row, motion, particles) ||
        (seed !== 100 && seed !== 200)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep: dt, nativeStepRate} = particles;
    const {evaluate} = motion;
    const [start, burstSize, cycles, period] = row.bursts[0];
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const coneAngle = f32(row.shape.angle * f32(Math.PI / 180));
    const coneX = f32(Math.sin(coneAngle)), coneZ = f32(Math.cos(coneAngle));
    const arc = f32(row.shape.arc * f32(Math.PI / 180));
    const colors = {start: white, keys: row.lifeColors[0]};
    const maxFrame = Math.ceil((row.delay + row.duration + row.lifetime[1]) * nativeStepRate) + 2;
    const records = [], active = [];
    let frame = 0, cycle = 0, clock = 0, delay = row.delay;

    function birth(index, step) {
      const random = initial[index % 4], nextShape = shape[index % 4];
      const word = random();
      const life = lerp(row.lifetime[0], row.lifetime[1], nativeUnit(random()));
      const [[minX, maxX], [minY, maxY]] = row.size3D;
      const width = lerp(minX, maxX, nativeUnit(random()));
      const height = lerp(minY, maxY, nativeUnit(random()));
      random(); // A camera-facing quad has no depth axis, but the draw is reserved.
      const roll = lerp(row.roll[0], row.roll[1], nativeUnit(random()));
      random(); // Fixed white still advances the InitialModule color stream.
      const heading = f32(arc * nativeUnit(nextShape()));
      const radialWord = nativeUnit(nextShape());
      const radial = f32(Math.sqrt(f32(f32(1 - radialWord) + f32(f32(.001) * radialWord))));
      const x = f32(f32(Math.cos(heading)) * radial), y = f32(f32(Math.sin(heading)) * radial);
      const localX = f32(coneX * x), localY = f32(coneX * y);
      const length = f32(f32(localX * localX) + f32(f32(localY * localY) + f32(coneZ * coneZ)));
      const reciprocal = f32(1 / Math.sqrt(length));
      const depth = f32(row.shape.length * nativeUnit(nextShape()));
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      velocity(); // VelocityModule's X range is zero but takes the first draw.
      const drift = lerp(row.velocityY[0], row.velocityY[1], nativeUnit(velocity()));
      const tileWord = nativeUnit(nativeRandom((word + atlasSalt) >>> 0)());
      const tile = Math.floor(f32(f32(row.atlas.start[1] * tileWord) * 16));
      const particle = {
        x: f32(f32(-x * row.shape.radius) + f32(f32(-localX * reciprocal) * depth)),
        y: f32(f32(coneZ * reciprocal) * depth),
        z: f32(f32(-y * row.shape.radius) + f32(f32(-localY * reciprocal) * depth)),
        life: inverseLifetime(life), age: 0, sizeX: width, sizeY: height, roll, drift, gravityVelocity: 0, tile,
      };
      advance(particle, step);
      active.push(particle);
    }

    function advance(particle, step) {
      const gravity = f32(f32(f32(-9.81) * step) * row.gravity);
      particle.gravityVelocity = f32(particle.gravityVelocity + gravity);
      particle.y = f32(particle.y + f32(f32(particle.gravityVelocity + particle.drift) * step));
      particle.age = f32(particle.age + f32(f32(step * 100) * particle.life));
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

    function emitStep() {
      if (cycle >= cycles) return;
      if (delay >= dt) {
        delay = f32(delay - dt);
        return;
      }
      const interval = f32(dt - delay);
      delay = 0;
      clock = f32(clock + interval);
      if (clock <= f32(start + f32(cycle * period)) || clock >= row.duration) return;
      cycle++;
      const substep = f32(interval * birthBias);
      for (let index = 0; index < burstSize; index++) birth(index, substep);
    }

    function update(tick) {
      for (const particle of active) advance(particle, dt);
      cull();
      emitStep();
      if (!active.length) return;
      const output = new Float32Array(active.length * stride);
      for (const [index, particle] of active.entries()) {
        const age = f32(particle.age * ageScale);
        const scale = Math.max(0, f32(f32(evaluate(row.sizeCurve, age)) * row.sizeMultiplier));
        const rgba = nativeColorAtTime(colors, age).map(value => Math.round(value * 255));
        output.set([particle.x, particle.y, particle.z, f32(scale * particle.sizeX),
          f32(scale * particle.sizeY), particle.roll, ...rgba, particle.tile], index * stride);
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
            values[i + 5], values[i + 6], values[i + 7], values[i + 8], values[i + 9], values[i + 10]);
        }
      },
    };
  }

  global.MVStudioSparksASecondarySimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
