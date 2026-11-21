(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const speedSalt = 0x96aa4de3;
  const checkpointSeconds = 2;
  const maxTime = 60;
  const white = [255, 255, 255, 255];
  const vector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite);
  const matches = (value, ...expected) => vector(value, expected.length) &&
    value.every((number, index) => number === expected[index]);

  function validPalette(rows, components) {
    return Array.isArray(rows) && rows.length > 0 && rows.length <= 8 &&
      rows.every((row, index) => vector(row, components + 1) && row.every(Number.isInteger) &&
        row[0] >= 0 && row[0] <= 65535 && (!index || row[0] > rows[index - 1][0]) &&
        row.slice(1).every(byte => byte >= 0 && byte <= 255));
  }

  function supported(row, particles) {
    return row && row.seed === 0 && row.rate === 150 && row.cycle === 5 &&
      row.lifetime === .5 && row.capacity === 1000 && row.maxViewportWidth === 2 &&
      matches(row.position, 0, f32(.01), f32(-10.09)) && matches(row.box, 20, 0, 1) &&
      matches(row.size, f32(.3), 20, 1) && matches(row.speedRange, 15, 25) &&
      matches(row.uv, .25, .25, .75, 0) &&
      validPalette(row.palette?.rgb, 3) && validPalette(row.palette?.alpha, 1) &&
      particles.validNativeColor({start: white, keys: row.colorKeys});
  }

  function paletteAt(rows, stamp) {
    return rows.find(row => row[0] >= stamp) || rows[rows.length - 1];
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row, particles)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep, nativeStepRate} = particles;
    const {seed, position, box, cycle, rate, lifetime, size, speedRange, colorKeys, palette} = row;
    const inverseLife = f32(1 / lifetime), ageStep = f32(f32(nativeStep * 100) * inverseLife);
    const checkpointFrames = checkpointSeconds * nativeStepRate;
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const birthFrames = [[]], checkpoints = [[]];
    let frame = 0, clock = 0, carry = 0, active = [];

    function prepareBirths() {
      const previous = clock;
      clock = f32(clock + nativeStep);
      let amount = f32(f32(clock - previous) * rate);
      if (clock > cycle) {
        clock = f32(clock - cycle);
        amount = f32(f32(f32(cycle - previous) * rate) + f32(clock * rate));
      }
      const total = f32(amount + carry), count = Math.trunc(total);
      carry = f32(total - count);
      const inverseAmount = f32(1 / amount);
      const births = [];
      // One SIMD group per step at the checked source emission rate.
      // Both random streams advance for all four lanes, including padding.
      for (const [lane, draw] of initial.entries()) {
        const particleSeed = draw();
        draw(); // Fixed lifetime.
        draw(); // Fixed X size.
        draw(); // Fixed Y size.
        draw(); // Fixed Z size.
        draw(); // Fixed roll.
        const stamp = f32(nativeUnit(draw()) * 65535);
        const shapeDraw = shape[lane];
        const x = f32(-f32(f32(nativeUnit(shapeDraw()) - .5) * box[0]));
        shapeDraw(); // Box Y is zero, but still advances the source stream.
        const localZ = f32(f32(nativeUnit(shapeDraw()) - .5) * box[2]);
        if (lane >= count) continue;
        const randomSpeed = nativeUnit(nativeRandom((particleSeed + speedSalt) >>> 0)());
        const vz = f32(speedRange[0] + f32(f32(speedRange[1] - speedRange[0]) * randomSpeed));
        const ageFraction = f32(f32(lane + carry) * inverseAmount);
        const within = f32(nativeStep * Math.min(1, Math.max(birthBias, ageFraction)));
        const age = f32(f32(within * 100) * inverseLife);
        const z = f32(f32(position[2] + localZ) + f32(vz * within));
        const rgb = paletteAt(palette.rgb, stamp), alpha = paletteAt(palette.alpha, stamp);
        births.push({x, z, vz, age, color: {start: [rgb[1], rgb[2], rgb[3], alpha[1]], keys: colorKeys}});
      }
      birthFrames.push(births);
    }

    function cull() {
      // The native loop scans four lanes at a time and replaces expired
      // slots from the tail. Its SortMode=None renderer preserves this order.
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
      for (const particle of active) {
        particle.z = f32(particle.z + f32(particle.vz * nativeStep));
        particle.age = f32(particle.age + ageStep);
      }
      cull();
      frame++;
      if (frame === birthFrames.length) prepareBirths();
      const births = birthFrames[frame];
      // A SIMD write crossing a storage group fills its partial end with
      // the trailing new lanes and puts the leading lanes in the next group.
      const firstLane = Math.max(0, births.length - (4 - active.length % 4));
      for (let i = 0; i < births.length; i++) {
        active.push({...births[(firstLane + i) % births.length]});
      }
      if (frame === checkpoints.length * checkpointFrames) {
        checkpoints.push(active.map(particle => ({...particle})));
      }
    }

    return {
      sample(elapsed, fps, emit) {
        const target = nativeFrame(elapsed, fps);
        if (target < 0 || elapsed > maxTime) return;
        const index = Math.min(checkpoints.length - 1, Math.floor(target / checkpointFrames));
        const storedFrame = index * checkpointFrames;
        if (target < frame || storedFrame > frame) {
          active = checkpoints[index].map(particle => ({...particle}));
          frame = storedFrame;
        }
        while (frame < target) step();
        for (const particle of active) {
          const phase = f32(particle.age * fraction);
          const [r, g, b, a] = nativeColorAtTime(particle.color, phase);
          emit(particle.x, position[1], particle.z, particle.vz,
            f32(size[0] * phase), f32(size[1] * phase), f32(size[2] * phase),
            Math.round(r * 255), Math.round(g * 255), Math.round(b * 255), Math.round(a * 255));
        }
      },
    };
  }

  global.MVStudioFinaleFloorSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
