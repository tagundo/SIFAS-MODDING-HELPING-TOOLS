(function (global) {
  "use strict";

  const f32 = Math.fround;
  const percent = f32(.01), birthFraction = f32(1e-6);
  const degrees = f32(Math.PI / 180), inverseTurn = f32(1 / (2 * Math.PI));
  const dragSalt = 0xa6790296, spinSalt = 0x6aed452e, spinSignSalt = 0xff2bb1a4;
  const range = (x, lo, hi) => Number.isFinite(x) && x >= lo && x <= hi;
  const pair = (row, lo, hi) => Array.isArray(row) && row.length === 2 && row.every(x => range(x, lo, hi));
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));

  function keys(rows) {
    return Array.isArray(rows) && rows.length >= 2 && rows.length <= 16 && rows[0]?.[0] === 0 &&
      rows.every((row, i) => Array.isArray(row) && row.length === 4 && range(row[0], 0, 1) &&
        (!i || f32(row[0]) > f32(rows[i - 1][0])) && range(row[1], 0, 16) &&
        row.slice(2).every(value => range(value, -4096, 4096)));
  }

  function gradient(rows, dimensions) {
    return Array.isArray(rows) && rows.length === 2 && rows[0]?.[0] === 0 && rows[1]?.[0] === 65535 &&
      rows.every(row => Array.isArray(row) && row.length === dimensions + 1 && row.slice(1).every(x => range(x, 0, 1)));
  }

  function supported(row) {
    const {clamp, shape, startColor} = row || {};
    return row?.mode === "movingBillboard" && Number.isInteger(row.seed) && range(row.seed, 0, 0xffffffff) &&
      Number.isInteger(row.count) && range(row.count, 1, 64) && range(row.duration, .01, 120) &&
      range(row.delay, 0, row.duration) && pair(row.lifetime, .01, 10) && pair(row.size, .001, 20) &&
      range(row.startSpeed, .001, 64) && range(row.startRoll, -20, 20) && pair(row.spin, -20, 20) &&
      shape?.angle === 90 && range(shape.radius, .001, 4) && keys(row.sizeKeys) && range(row.sizeMultiplier, 0, 16) &&
      gradient(startColor?.rgb, 3) && gradient(startColor?.alpha, 1) &&
      range(clamp?.limit, .001, 64) && range(clamp.dampen, 0, 1) && range(clamp.drag?.multiplier, 0, 64) &&
      keys(clamp.drag.minKeys) && keys(clamp.drag.maxKeys);
  }

  function inverseSquareRoot(value) {
    if (!(value > 0)) return 0;
    // ARM FRSQRTE followed by the two FRSQRTS refinements in the native jobs.
    const scale = 2 ** -Math.floor(Math.log2(value) / 2);
    const mantissa = value * scale * scale, bins = mantissa < 2 ? 128 : 64;
    const midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let inverse = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let step = 0; step < 2; step++) inverse = f32(inverse * f32((3 - f32(value * inverse) * inverse) / 2));
    return inverse;
  }

  const squaredSpeed = (x, y) => f32(f32(x * x) + f32(y * y));

  function compact(population) {
    // The engine checks each four-lane block in reverse order and fills an
    // expired slot with the current tail before rechecking that block.
    for (let first = 0; first < population.length;) {
      let removed = false;
      for (let lane = Math.min(first + 3, population.length - 1); lane >= first; lane--) {
        if (population[lane].age <= 100) continue;
        const tail = population.pop();
        if (lane < population.length) population[lane] = tail;
        removed = true;
      }
      if (!removed) first += 4;
    }
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles?.nativeCosine || !supported(row)) return null;
    const {nativeFrame, nativeStep, nativeRandom, nativeUnit, nativeCosine, nativeInverseLifetime, nativeCurve} = particles;
    const curve = keys => nativeCurve(keys.map(key => key.map(f32)));
    const sizeAt = curve(row.sizeKeys), sizeMultiplier = f32(row.sizeMultiplier);
    const {minKeys, maxKeys, multiplier} = row.clamp.drag;
    const minDrag = curve(minKeys), maxDrag = curve(maxKeys), dragMultiplier = f32(multiplier);
    const speedLimit = f32(row.clamp.limit), shapeRadius = f32(row.shape.radius), startSpeed = f32(row.startSpeed);
    const arc = f32(360 * degrees), angle = f32(f32(row.shape.angle * degrees) * inverseTurn);
    const coneSin = nativeCosine(f32(angle - .25)), coneCos = nativeCosine(angle);
    const arcStep = nativeInverseLifetime(row.count);
    const rgb = row.startColor.rgb.map(key => key.slice(1).map(f32));
    const alpha = row.startColor.alpha.map(key => f32(key[1]));
    const lifetime = row.lifetime.map(f32), size = row.size.map(f32), spinRange = row.spin.map(f32);
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());

    let first = 1, delay = f32(row.delay);
    while (delay >= nativeStep) {
      delay = f32(delay - nativeStep);
      first++;
    }
    const interval = f32(nativeStep - delay);
    if (interval >= f32(row.duration)) return null;
    const wakeStep = f32(interval * birthFraction);
    const last = first + Math.ceil(Math.max(...lifetime) / nativeStep) + 4;
    const population = [], frames = [];
    let through = first - 1;

    function damping(step) {
      return f32(1 - f32(Math.pow(f32(1 - f32(row.clamp.dampen)), f32(step * 30))));
    }
    const regularDamping = damping(nativeStep), wakeDamping = damping(wakeStep);

    function spawn() {
      const streams = Array.from({length: 4}, (_, lane) => {
        const seed = (row.seed + 367 * lane) >>> 0;
        return {initial: nativeRandom(seed), shape: nativeRandom(seed)};
      });
      for (let slot = 0; slot < row.count; slot++) {
        const {initial, shape} = streams[slot & 3];
        const seed = initial(), life = nativeInverseLifetime(lerp(...lifetime, nativeUnit(initial())));
        const start = lerp(...size, nativeUnit(initial()));
        initial(); // Even a constant start rotation advances the initial stream.
        const tint = nativeUnit(initial());
        const color = rgb[0].map((value, i) => byte(lerp(value, rgb[1][i], tint)));
        color.push(byte(lerp(alpha[0], alpha[1], tint)));
        const spin = lerp(...spinRange, salted(seed, spinSalt)) * (salted(seed, spinSignSalt) > 0 ? 1 : -1);
        const dragWeight = salted(seed, dragSalt);
        const turns = f32(f32(f32(slot * arcStep) * arc) * inverseTurn);
        const radial = nativeUnit(shape()), area = f32(f32(1 - radial) + f32(f32(.001) * radial));
        const radius = f32(area * inverseSquareRoot(area));
        const px = f32(nativeCosine(turns) * radius), py = f32(nativeCosine(f32(turns - .25)) * radius);
        const dx = f32(px * coneSin), dy = f32(py * coneSin);
        const direction = inverseSquareRoot(f32(squaredSpeed(dx, dy) + f32(coneCos * coneCos)));
        const vx = f32(dx * direction), vy = f32(dy * direction);
        // The native shape transform normalizes its output again, including
        // when the emitter's shape transform is identity.
        const transformedDirection = inverseSquareRoot(squaredSpeed(vx, vy));
        population.push({
          life, start, width: start, color, spin, dragWeight, age: 0, roll: f32(row.startRoll),
          x: f32(px * shapeRadius), y: f32(py * shapeRadius),
          vx: f32(f32(vx * transformedDirection) * startSpeed), vy: f32(f32(vy * transformedDirection) * startSpeed),
        });
      }
    }

    function advance(atom, step, damp) {
      let {vx, vy} = atom;
      let square = squaredSpeed(vx, vy), inverse = inverseSquareRoot(square);
      let speed = f32(square * inverse);
      const capped = speed > speedLimit ? lerp(speed, speedLimit, damp) : speed;
      vx = f32(f32(vx * inverse) * capped);
      vy = f32(f32(vy * inverse) * capped);

      const phase = f32(atom.age * percent);
      const drag = lerp(f32(minDrag(phase) * dragMultiplier), f32(maxDrag(phase) * dragMultiplier), atom.dragWeight);
      const half = f32(atom.width * .5), area = f32(half * f32(half * f32(Math.PI)));
      square = squaredSpeed(vx, vy);
      inverse = inverseSquareRoot(square);
      speed = f32(square * inverse);
      const nextSpeed = Math.max(0, f32(speed - f32(step * f32(square * f32(drag * area)))));
      atom.vx = speed > f32(1e-15) ? f32(f32(vx / speed) * nextSpeed) : 0;
      atom.vy = speed > f32(1e-15) ? f32(f32(vy / speed) * nextSpeed) : 0;
      atom.x = f32(atom.x + f32(atom.vx * step));
      atom.y = f32(atom.y + f32(atom.vy * step));
      atom.roll = f32(atom.roll + f32(atom.spin * step));
      atom.age = f32(atom.age + f32(f32(step * 100) * atom.life));
      atom.width = f32(atom.start * Math.max(0, f32(sizeAt(f32(atom.age * percent)) * sizeMultiplier)));
    }

    function update(tick) {
      if (tick === first) spawn();
      const wake = tick === first;
      for (const atom of population) advance(atom, wake ? wakeStep : nativeStep, wake ? wakeDamping : regularDamping);
      compact(population);
      frames[tick - first] = population.map(({x, y, width, roll, color}) => [x, y, width, roll, ...color]);
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < first || target > last) return;
      while (through < target) update(++through);
      for (const [x, y, width, roll, r, g, b, a] of frames[target - first]) {
        emit(x, y, 0, width, width, roll, r, g, b, a);
      }
    }};
  }

  global.MVStudioMovingBurstSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
