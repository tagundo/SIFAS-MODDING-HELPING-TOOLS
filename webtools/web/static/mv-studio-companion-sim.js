(function (global) {
  "use strict";

  const f32 = Math.fround;
  const speedSalt = 0x96aa4de3;
  const maxTime = 60;
  const stride = 8;
  const white = [255, 255, 255, 255];
  const between = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
  const vector = (value, size, min, max) => Array.isArray(value) && value.length === size &&
    value.every(number => between(number, min, max));

  function validPalette(rows, size) {
    return Array.isArray(rows) && rows.length >= 1 && rows.length <= 8 &&
      rows.every((row, index) => vector(row, size, 0, 65535) && row.every(Number.isInteger) &&
        row.slice(1).every(byte => byte <= 255) && (!index || row[0] > rows[index - 1][0]));
  }

  function supported(row, particles) {
    if (!row || !["speed", "speed_R", "speed_L", "stars"].includes(row.name)) return false;
    const {shape, colorKeys} = row;
    const side = row.name === "speed_R" || row.name === "speed_L";
    const center = row.name === "speed";
    const stars = row.name === "stars";
    return between(row.seed, 0, 0xffffffff) && Number.isInteger(row.seed) &&
      row.prewarm === false && row.cycle === 5 && row.lifetime === 2 &&
      row.rate === (center ? 250 : 100) && row.capacity === (center ? 500 : 1000) &&
      vector(row.size, 2, .5, 2) && row.size[0] === .5 && row.size[1] === (stars ? 2 : 1) &&
      vector(row.speed, 2, 5, 25) && row.speed[0] === (stars ? 5 : 15) && row.speed[1] === (stars ? 10 : 25) &&
      vector(row.position, 3, -100, 100) && vector(row.rotation, 4, -1, 1) &&
      Math.abs(Math.hypot(...row.rotation) - 1) < 1e-5 &&
      shape?.type === (side ? 10 : 4) && shape.arc === (side ? 90 : 360) && shape.angle === 75 &&
      between(shape.radius, .00009, 1) && vector(shape.scale, 3, .09, 1) &&
      validPalette(row.palette?.rgb, 4) && validPalette(row.palette?.alpha, 2) &&
      row.palette.alpha.every(key => key[1] === 255) &&
      particles.validNativeColor({start: white, keys: colorKeys}) &&
      colorKeys.every(key => key.slice(1, 4).every(byte => byte === 255));
  }

  function rotationMatrix([x, y, z, w]) {
    return [
      1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w),
      2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w),
      2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y),
    ].map(f32);
  }

  function paletteAt(rows, stamp) {
    return rows.find(row => row[0] >= stamp) || rows[rows.length - 1];
  }

  function cosineTurns(turns) {
    // Unity's native ShapeModule evaluates a polynomial over a folded turn.
    const offset = turns < 0 ? -8388608 : 8388608;
    const nearest = f32(f32(turns + offset) - offset);
    const x = f32(.25 - Math.abs(f32(turns - nearest)));
    const square = f32(x * x), fourth = f32(square * square);
    const low = f32(6.283185005187988 + f32(square * -41.34165954589844));
    const high = f32(81.60182189941406 + f32(square * -76.56861877441406));
    return f32(x * f32(f32(low + f32(fourth * high)) + f32(f32(fourth * fourth) * 39.65703201293945)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row, particles)) return null;
    const {seed, cycle, lifetime, capacity, rate, position, shape, colorKeys, palette} = row;
    const {nativeRandom, nativeUnit, nativeColor} = particles;
    const [minSize, maxSize] = row.size;
    const [minSpeed, maxSpeed] = row.speed;
    const matrix = rotationMatrix(row.rotation);
    const cone = shape.type === 4, degrees = f32(Math.PI / 180);
    const arc = f32(shape.arc * degrees), angle = f32(shape.angle * degrees);
    const inverseTurn = f32(1 / (2 * Math.PI));
    const angleTurns = f32(angle * inverseTurn);
    const sin = cosineTurns(f32(angleTurns - .25)), cos = cosineTurns(angleTurns);
    const [sx, sy, sz] = shape.scale;
    const ageColor = {start: white, keys: colorKeys};

    // One piece of shared scenery lasts at most the original 60-second
    // particle lifetime. Keep one cadence's packed births for exact seeking.
    let records = new Float64Array(0), colors = new Uint8Array(0), expiry = new Uint16Array(0);
    const frameEnds = new Uint16Array(60 * maxTime + 1);
    const frameStarts = new Uint16Array(frameEnds.length);
    let initial, shaping, tick = 0, phase = 0, carry = 0, length = 0, firstAlive = 0, fps = 0;
    function useCadence(value) {
      initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      shaping = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      fps = value;
      tick = phase = carry = length = firstAlive = 0;
    }

    function ensureCapacity(wanted) {
      if (colors.length / 3 >= wanted) return;
      const next = Math.min(maxTime * rate + 16, Math.max(128, wanted * 2));
      const nextRecords = new Float64Array(next * stride);
      const nextColors = new Uint8Array(next * 3);
      const nextExpiry = new Uint16Array(next);
      nextRecords.set(records);
      nextColors.set(colors);
      nextExpiry.set(expiry);
      records = nextRecords;
      colors = nextColors;
      expiry = nextExpiry;
    }

    function step(dt) {
      const previous = phase;
      phase = f32(phase + dt);
      let amount;
      if (phase > cycle) {
        phase = f32(phase - cycle);
        amount = f32(f32(f32(cycle - previous) * rate) + f32(phase * rate));
      } else {
        amount = f32(f32(phase - previous) * rate);
      }
      const countAndCarry = f32(amount + carry);
      const requested = Math.trunc(countAndCarry);
      carry = f32(countAndCarry - requested);
      const fraction = f32(1 / amount);
      const time = ++tick / fps;
      while (firstAlive < length && expiry[firstAlive] <= tick) firstAlive++;
      const count = Math.min(requested, capacity - (length - firstAlive));
      const ageStep = f32(f32(dt * 100) / lifetime);
      ensureCapacity(length + count);
      // Unity advances all four random lanes in each SIMD group, including
      // padded births. Only the real births enter the stream.
      for (let i = 0; i < count; i += 4) {
        for (let lane = 0; lane < 4; lane++) {
          const draw = initial[lane], shapeDraw = shaping[lane];
          const particleSeed = draw();
          draw();
          const size = f32(minSize + f32(f32(maxSize - minSize) * nativeUnit(draw())));
          draw();
          const stamp = f32(nativeUnit(draw()) * 65535);
          const heading = f32(f32(arc * nativeUnit(shapeDraw())) * inverseTurn);
          const radialDraw = nativeUnit(shapeDraw());
          const index = i + lane;
          if (index >= count) continue;
          const areaRadius = cone ? f32(f32(1 - radialDraw) + f32(f32(.001) * radialDraw)) : radialDraw;
          const radius = f32(Math.sqrt(areaRadius));
          const x = -cosineTurns(heading), y = cosineTurns(f32(heading - .25));
          const px = f32(f32(f32(x * radius) * shape.radius) * sx);
          const py = f32(f32(f32(y * radius) * shape.radius) * sy);
          const dx = f32(sx * (cone ? f32(f32(x * radius) * sin) : x));
          const dy = f32(sy * (cone ? f32(f32(y * radius) * sin) : y));
          const dz = cone ? f32(cos * sz) : 0;
          const speedUnit = nativeUnit(nativeRandom((particleSeed + speedSalt) >>> 0)());
          const speed = f32(minSpeed + f32(f32(maxSpeed - minSpeed) * speedUnit));
          const scale = speed / Math.hypot(dx, dy, dz);
          const within = f32(dt * Math.max(1e-6, Math.min(1, f32(f32(index + carry) * fraction))));
          // Unity expires particles after their accumulated age exceeds 100.
          // This capacity check runs before births reach the SIMD initializer.
          const slot = length + count - 1 - index;
          const offset = slot * stride;
          let age = f32(f32(within * 100) / lifetime), deathFrame = tick;
          do {
            age = f32(age + ageStep);
            deathFrame++;
          } while (age <= 100);
          expiry[slot] = deathFrame;
          records[offset] = time - within;
          records[offset + 1] = f32(position[0] + matrix[0] * px + matrix[1] * py);
          records[offset + 2] = f32(position[1] + matrix[3] * px + matrix[4] * py);
          records[offset + 3] = f32(position[2] + matrix[6] * px + matrix[7] * py);
          records[offset + 4] = f32((matrix[0] * dx + matrix[1] * dy + matrix[2] * dz) * scale);
          records[offset + 5] = f32((matrix[3] * dx + matrix[4] * dy + matrix[5] * dz) * scale);
          records[offset + 6] = f32((matrix[6] * dx + matrix[7] * dy + matrix[8] * dz) * scale);
          records[offset + 7] = size;
          const rgb = paletteAt(palette.rgb, stamp);
          colors[slot * 3] = rgb[1];
          colors[slot * 3 + 1] = rgb[2];
          colors[slot * 3 + 2] = rgb[3];
        }
      }
      length += count;
      frameStarts[tick] = firstAlive;
      frameEnds[tick] = length;
    }

    return {
      sample(time, cadence, emit) {
        if (!between(time, 0, maxTime) || ![30, 60].includes(cadence)) return;
        if (fps !== cadence) useCadence(cadence);
        const frame = Math.floor(time * fps + 1e-9), dt = f32(1 / fps);
        while (tick < frame) step(dt);
        // A seek between two ticks only sees the births already submitted.
        for (let slot = frameEnds[frame] - 1; slot >= frameStarts[frame]; slot--) {
          const offset = slot * stride;
          const age = f32(time - records[offset]);
          const ratio = Math.min(1, f32(age / lifetime));
          const size = f32(records[offset + 7] * f32(f32(ratio * 100) * f32(.01)));
          const alpha = Math.round(nativeColor(ageColor, ratio)[3] * 255);
          const vx = records[offset + 4], vy = records[offset + 5], vz = records[offset + 6];
          emit(f32(records[offset + 1] + vx * age), f32(records[offset + 2] + vy * age),
            f32(records[offset + 3] + vz * age), vx, vy, vz, size,
            colors[slot * 3], colors[slot * 3 + 1], colors[slot * 3 + 2], alpha);
        }
      },
    };
  }

  global.MVStudioCompanionSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
