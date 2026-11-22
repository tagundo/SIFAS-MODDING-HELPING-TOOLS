(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 1498035885, burstSize = 5, repeatFrame = 15, lastFrame = 94;
  const width = 4, height = 2, inverseLife = f32(1 / f32(1.3)), ageScale = f32(.01);
  const tau = f32(2 * Math.PI), turnsPerRadian = f32(1 / (2 * Math.PI));
  const spread = f32(.5235987901687622), maxSpin = f32(3.141592502593994);
  const shapeWidth = f32(3.93), shapeDirectionZ = f32(5.960464477539063e-8);
  const terminalLimit = f32(.16091954708099365), change = f32(terminalLimit - 1);
  const cubic = f32(-2 * change - 2), quadratic = f32(3 * change + 4);
  const lerp = (from, to, weight) => f32(from + f32(f32(to - from) * weight));

  function shapeCos(turns) {
    const triangle = f32(.25 - Math.abs(f32(turns - Math.round(turns))));
    const square = f32(triangle * triangle), fourth = f32(square * square);
    const low = f32(f32(square * -41.34165954589844) + 6.283185005187988);
    const high = f32(f32(square * -76.56861877441406) + 81.60182189941406);
    return f32(triangle * f32(f32(f32(fourth * fourth) * 39.65703201293945) + f32(low + f32(fourth * high))));
  }

  function reciprocalSqrt(value) {
    // Shape and clamp use FRSQRTE followed by two FRSQRTS refinements.
    const scale = 2 ** -Math.floor(Math.log2(value) / 2), mantissa = value * scale * scale;
    const bins = mantissa < 2 ? 128 : 64;
    const midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let reciprocal = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return reciprocal;
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || row?.role !== "fan" || row.seed !== seed) return null;
    const {nativeFrame, nativeStep: dt, nativeRandom, nativeUnit} = particles;
    const firstStep = f32(dt * f32(1e-6));
    const damping = step => f32(1 - f32(Math.pow(f32(1 - f32(.03)), f32(step * 30))));
    const fullDamping = damping(dt), firstDamping = damping(firstStep);
    const streams = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const frames = [[]], active = [];

    function salted(word, salt) {
      return nativeUnit(nativeRandom((word + salt) >>> 0)());
    }

    function birth({initial, shape}) {
      const word = initial();
      initial(); // Lifetime draw, even though the authored bounds are fixed.
      initial(); initial(); initial(); // The three authored size channels.
      const roll = lerp(-spread, spread, nativeUnit(initial()));
      initial(); // Fixed starting white.
      const turns = f32(f32(tau * nativeUnit(shape())) * turnsPerRadian);
      const radial = nativeUnit(shape());
      const radiusSquared = f32(f32(1 - radial) + f32(f32(.001) * radial));
      const radius = f32(radiusSquared * reciprocalSqrt(radiusSquared));
      const x = f32(f32(shapeCos(turns) * radius) * shapeWidth);
      const vy = lerp(12, 15, salted(word, 0x96aa4de3));
      const spin = lerp(-maxSpin, maxSpin, salted(word, 0x6aed452e));
      const atlasPhase = f32(f32(.9999) + f32(.75 * salted(word, 0x56b3dbb0))) % 1;
      return {x, y: 0, z: 0, vy, vz: f32(vy * shapeDirectionZ), roll, spin, age: 0, tile: Math.floor(f32(atlasPhase * 2))};
    }

    function advance(atom, step, drag) {
      const phase = f32(atom.age * ageScale);
      const limit = f32(f32(f32(f32(f32(cubic * phase) + quadratic) * phase) - 2) * phase + 1);
      const square = f32(f32(atom.vy * atom.vy) + f32(atom.vz * atom.vz));
      const reciprocal = reciprocalSqrt(square), speed = f32(square * reciprocal);
      if (speed > limit) {
        const next = lerp(speed, limit, drag);
        atom.vy = f32(f32(atom.vy * reciprocal) * next);
        atom.vz = f32(f32(atom.vz * reciprocal) * next);
      }
      atom.y = f32(atom.y + f32(atom.vy * step));
      atom.z = f32(atom.z + f32(atom.vz * step));
      atom.roll = f32(atom.roll + f32(atom.spin * step));
      atom.age = f32(atom.age + f32(f32(step * 100) * inverseLife));
    }

    function emitBurst() {
      const born = [];
      for (let first = 0; first < burstSize; first += 4) {
        const group = streams.map(birth);
        for (let lane = 0; lane < Math.min(4, burstSize - first); lane++) {
          const atom = group[lane];
          advance(atom, firstStep, firstDamping);
          born.push(atom);
        }
      }
      // Native live storage fills the remaining lanes of a partial SIMD group
      // with the tail of a new burst before appending the complete groups.
      const empty = (4 - active.length % 4) % 4;
      const first = empty ? burstSize - empty : 0;
      for (let i = 0; i < burstSize; i++) active.push(born[(first + i) % burstSize]);
    }

    function advanceFrame(frame) {
      for (const atom of active) advance(atom, dt, fullDamping);
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
      if (frame === 1 || frame === repeatFrame) emitBurst();
      // World alignment and the authored billboard pivot are resolved by the renderer.
      frames.push(active.map(atom => [-atom.x, atom.y, atom.z, width, height, atom.roll, atom.tile]));
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 1 || target > lastFrame) return;
      while (frames.length <= target) advanceFrame(frames.length);
      for (const frame of frames[target]) emit(...frame);
    }};
  }

  global.MVStudioMomijiFanSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
