(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seeds = {"green-burst": 3279275062, "yellow-burst": 3364901415};
  const count = 50, ageScale = f32(.01), startFraction = f32(1e-6);
  const fadeStamp = 58982, fadeStart = f32(fadeStamp / 65535);
  const tau = f32(2 * Math.PI), invTau = f32(1 / (2 * Math.PI));
  const quarterPi = f32(.7853981256484985);
  const lifeRates = [[f32(-.8726646304130554), 1], [f32(-.5235987901687622), 1], [quarterPi * 2, -quarterPi * 2]];
  const speedRates = [[-quarterPi, quarterPi], [-quarterPi * 4, quarterPi * 4], [-quarterPi * 2, quarterPi * 4]];
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const unit = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const vector = (values, length) => Array.isArray(values) && values.length === length && values.every(Number.isFinite);

  function keysValid(keys, length, channels) {
    return Array.isArray(keys) && keys.length === length && keys.every((key, i) =>
      vector(key, channels + 1) && Number.isInteger(key[0]) && key[0] >= 0 && key[0] <= 65535 &&
      (!i || key[0] > keys[i - 1][0]) && key.slice(1).every(unit));
  }

  function supported(row) {
    if (!row || !Object.hasOwn(seeds, row.role) || row.seed !== seeds[row.role] || row.rate !== 0) return false;
    const {position, rotation, startColor, alphaKeys} = row;
    return vector(position, 3) && position[0] === 0 && position[1] === f32(.57) && position[2] === 0 &&
      vector(rotation, 4) && !rotation[1] && !rotation[2] &&
      Math.abs(rotation[0] + Math.SQRT1_2) < 1e-6 && Math.abs(rotation[3] - Math.SQRT1_2) < 1e-6 &&
      keysValid(startColor?.rgb, 3, 3) && keysValid(startColor?.alpha, 2, 1) && keysValid(alphaKeys, 3, 1) &&
      alphaKeys[0][0] === 0 && alphaKeys[0][1] === 1 && alphaKeys[1][0] === fadeStamp && alphaKeys[1][1] === 1 &&
      alphaKeys[2][0] === 65535 && alphaKeys[2][1] === 0;
  }

  function inverse(value) {
    // NEON reciprocal estimate and the two refinements used by the native modules.
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function cosine(turns) {
    const triangle = f32(.25 - Math.abs(f32(turns - Math.round(turns))));
    const square = f32(triangle * triangle), fourth = f32(square * square);
    const low = f32(f32(square * -41.34165954589844) + 6.283185005187988);
    const high = f32(f32(square * -76.56861877441406) + 81.60182189941406);
    return f32(triangle * f32(f32(f32(fourth * fourth) * 39.65703201293945) + f32(low + f32(fourth * high))));
  }

  function hermite(start, end, span, slope) {
    const delta = f32(end - start), tangent = f32(span * slope);
    const quadratic = f32(f32(f32(delta + delta) + delta) - f32(2 * tangent));
    const cubic = f32(tangent - f32(2 * delta));
    return time => {
      if (time >= span) return end;
      const phase = f32(time / span);
      return f32(start + f32(phase * f32(tangent + f32(phase * f32(quadratic + f32(phase * cubic))))));
    };
  }

  const lowerGravity = hermite(.09195709228515625, -.9195404052734375, .06452926248311996, 0);
  const upperGravity = hermite(.17645278573036194, -1, .037464167922735214, -7.342578887939453);
  const lowerDrift = hermite(-1, 1, 1, 0), upperDrift = hermite(1, -1, 1, 0);

  function palette(keys, at) {
    const next = keys.findIndex(key => key[0] > at);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const weight = left === right ? 0 : f32(f32(at - left[0]) / (right[0] - left[0]));
    return left.slice(1).map((value, index) => byte(lerp(value, right[index + 1], weight)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeFrame, nativeStep, nativeRandom, nativeUnit} = particles;
    const {seed, position, rotation, startColor} = row;
    const streams = Array.from({length: 4}, (_, lane) => {
      const word = (seed + lane * 367) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const firstStep = f32(nativeStep * startFraction), invStep = inverse(nativeStep);
    const orbitTurns = f32(f32(nativeStep * f32(.2)) * invTau);
    const orbitX = cosine(orbitTurns), orbitY = cosine(f32(orbitTurns - .25));
    const stamp = f32(f32(nativeStep / 10) * 65535);
    const [r, g, b] = palette(startColor.rgb, stamp);
    const [alpha] = palette(startColor.alpha, stamp);
    const invFade = inverse(f32(1 - fadeStart));
    const [px, py, pz] = position;
    const diagonal = f32(1 - f32(f32(rotation[0] + rotation[0]) * rotation[0]));
    const offDiagonal = f32(f32(rotation[0] + rotation[0]) * rotation[3]);
    const initial = [];
    const checkpointStep = 15, checkpoints = [{clock: 0, active: []}];
    let frame = 0, clock = 0, active = [];

    function salted(word, salt) {
      return nativeUnit(nativeRandom((word + salt) >>> 0)());
    }

    function prepareBirth({initial: drawInitial, shape}) {
      const word = drawInitial();
      const life = inverse(lerp(f32(1.2), 1.5, nativeUnit(drawInitial())));
      const size = lerp(.5, f32(.8), nativeUnit(drawInitial()));
      const roll = lerp(-quarterPi, quarterPi, nativeUnit(drawInitial()));
      drawInitial(); // The initial color draw is consumed even for fixed system-phase gradients.
      const turns = f32(f32(tau * nativeUnit(shape())) * invTau);
      const radial = nativeUnit(shape());
      const radius = f32(Math.sqrt(f32(f32(1 - radial) + f32(f32(.001) * radial))));
      const x = f32(f32(radius * cosine(turns)) * f32(3.7));
      const y = f32(f32(radius * cosine(f32(turns - .25))) * 4.5);
      const z = f32(f32(5 * nativeUnit(shape())) * .5);
      const velocity = nativeRandom((word + 0xe0fbd834) >>> 0);
      const driftX = nativeUnit(velocity()), driftY = nativeUnit(velocity()), driftZ = nativeUnit(velocity());
      const rotWeight = salted(word, 0x6aed452e), speedWeight = salted(word, 0xdec4aea1);
      const sign = salted(word, 0xff2bb1a4) > 0 ? 1 : -1;
      const rates = lifeRates.map(([min, max], axis) =>
        f32(sign * f32(lerp(min, max, rotWeight) + lerp(...speedRates[axis], speedWeight))));
      return {x, y, z, life, size, roll, driftX, driftY, driftZ, rates, gravity: salted(word, 0xe2b7c3c3)};
    }

    for (let i = 0; i < count; i++) initial.push(prepareBirth(streams[i % 4]));

    function advance(atom, dt, gravityLow, gravityHigh, orbit) {
      const {source, x, y} = atom;
      const phase = f32(atom.age * ageScale);
      const low = lowerDrift(phase), high = upperDrift(phase);
      const rotatedX = orbit ? f32(f32(x * orbitX) - f32(y * orbitY)) : x;
      const rotatedY = orbit ? f32(f32(x * orbitY) + f32(y * orbitX)) : y;
      const vx = f32(lerp(low, high, source.driftX) + f32(f32(rotatedX - x) * invStep));
      const vy = f32(lerp(low, high, source.driftY) + f32(f32(rotatedY - y) * invStep));
      const extraZ = lerp(low, high, source.driftZ);
      atom.vz = f32(atom.vz + f32(f32(f32(-9.81) * dt) * lerp(gravityLow, gravityHigh, source.gravity)));
      atom.x = f32(x + f32(vx * dt));
      atom.y = f32(y + f32(vy * dt));
      atom.z = f32(atom.z + f32(f32(atom.vz + extraZ) * dt));
      atom.rx = f32(atom.rx + f32(source.rates[0] * dt));
      atom.ry = f32(atom.ry + f32(source.rates[1] * dt));
      atom.rz = f32(atom.rz + f32(source.rates[2] * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * source.life));
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
      clock = f32(clock + nativeStep);
      const phase = f32(clock / 10);
      const gravityLow = lowerGravity(phase), gravityHigh = upperGravity(phase);
      if (!frame) {
        // The time-zero burst is born at the end of this update, with a
        // minimum nonzero particle step for its initial module outputs.
        active = initial.map(source => {
          const atom = {source, x: source.x, y: source.y, z: source.z, vz: 0, rx: 0, ry: 0, rz: source.roll, age: 0};
          advance(atom, firstStep, gravityLow, gravityHigh, false);
          return atom;
        });
      } else {
        for (const atom of active) advance(atom, nativeStep, gravityLow, gravityHigh, true);
        cull();
      }
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 1 || target > 91) return;
      if (target < frame) {
        const index = Math.floor(target / checkpointStep);
        const saved = checkpoints[index];
        frame = index * checkpointStep;
        clock = saved.clock;
        active = saved.active.map(atom => ({...atom}));
      }
      while (frame < target) {
        step();
        frame++;
        if (frame === checkpoints.length * checkpointStep) {
          checkpoints.push({clock, active: active.map(atom => ({...atom}))});
        }
      }
      for (const atom of active) {
        const phase = f32(atom.age * ageScale);
        const weight = Math.trunc(f32(f32(Math.max(0, f32(phase - fadeStart)) * invFade) * 255));
        const multiplier = 255 + ((128 - 255 * weight) >> 8);
        emit(f32(px - atom.x),
          f32(py + f32(f32(atom.y * diagonal) - f32(atom.z * offDiagonal))),
          f32(pz + f32(f32(atom.y * offDiagonal) + f32(atom.z * diagonal))),
          atom.source.size, atom.rx, atom.ry, atom.rz, r, g, b, Math.floor((alpha * multiplier + 127) / 255));
      }
    }};
  }

  global.MVStudioAutumnBurstSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
