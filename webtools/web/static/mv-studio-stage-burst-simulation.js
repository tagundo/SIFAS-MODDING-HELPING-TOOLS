(function (global) {
  "use strict";

  const f32 = Math.fround, phaseScale = f32(.01), birthFraction = f32(1e-6), maxElapsed = 60;
  const range = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
  const vector = (row, length, min, max) => Array.isArray(row) && row.length === length &&
    row.every(value => range(value, min, max));
  const constant = (values, min, max) => vector(values, 2, min, max) && values[0] === values[1];
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));

  function gradientKeys(keys, width) {
    return Array.isArray(keys) && keys.length >= 2 && keys.length <= 8 &&
      keys[0]?.[0] === 0 && keys.at(-1)?.[0] === 65535 && keys.every((key, index) =>
        Array.isArray(key) && key.length === width && Number.isInteger(key[0]) &&
        (!index || key[0] > keys[index - 1][0]) && vector(key.slice(1), width - 1, 0, 1));
  }

  function supported(row, seed) {
    if (row?.kind !== "stationaryBurst" || !Number.isInteger(seed) || !range(seed, 0, 0xffffffff) ||
        !range(row.duration, .01, 240) || !range(row.delay, 0, maxElapsed) ||
        !constant(row.lifetime, .01, 10) || !constant(row.size, 0, 100) ||
        !Number.isInteger(row.maxParticles) || !range(row.maxParticles, 1, 1000) ||
        !vector(row.startColor, 4, 0, 1) || !range(row.sizeMultiplier, 0, 16)) return false;
    const {burst, atlas, colorOverLife, sizeKeys, tiles} = row;
    if (burst?.time !== 0 || burst.count !== 1 || (burst.cycles !== 0 && burst.cycles !== 1) ||
        !range(burst.period, .001, 240) || (burst.cycles === 0 && Math.ceil(row.duration / burst.period) > 64)) return false;
    if (!vector(tiles, 2, 1, 8) || !tiles.every(Number.isInteger) ||
        (atlas === undefined ? tiles.some(axis => axis !== 1) :
          !constant(atlas?.start, 0, 1) || !constant(atlas?.frame, 0, 1))) return false;
    if (colorOverLife !== undefined &&
        (!gradientKeys(colorOverLife?.rgb, 4) || !gradientKeys(colorOverLife?.alpha, 2))) return false;
    return Array.isArray(sizeKeys) && sizeKeys.length >= 2 && sizeKeys.length <= 16 &&
      sizeKeys[0]?.[0] === 0 && sizeKeys.at(-1)?.[0] === 1 &&
      sizeKeys.every((key, index) => Array.isArray(key) && key.length === 4 && range(key[0], 0, 1) &&
        (!index || f32(key[0]) > f32(sizeKeys[index - 1][0])) && range(key[1], 0, 16) &&
        key.slice(2).every(slope => slope === null || range(slope, -4096, 4096)));
  }

  function cull(active) {
    for (let first = 0; first < active.length;) {
      let removed = false;
      for (let lane = Math.min(first + 3, active.length - 1); lane >= first; lane--) {
        if (active[lane] <= 100) continue;
        const tail = active.pop();
        if (lane < active.length) active[lane] = tail;
        removed = true;
      }
      if (!removed) first += 4;
    }
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles;
    if (!particles?.nativeInverseLifetime || !supported(row, seed)) return null;
    const {nativeFrame, nativeStep, nativeCurve, nativePackedGradient, nativeColorAtTime, nativeInverseLifetime} = particles;
    const duration = f32(row.duration), period = f32(row.burst.period), width = f32(row.size[0]);
    const lifetime = nativeInverseLifetime(f32(row.lifetime[0])), multiplier = f32(row.sizeMultiplier);
    const sizeAt = nativeCurve(row.sizeKeys.map(key => key.map(value => value === null ? null : f32(value))));
    const start = row.startColor.map(byte);
    const gradient = row.colorOverLife && nativePackedGradient(row.colorOverLife, start);
    const tileCount = row.tiles[0] * row.tiles[1];
    const atlasPhase = row.atlas ? f32(f32(row.atlas.start[0]) + f32(row.atlas.frame[0])) : 0;
    const tile = Math.floor(f32(f32(atlasPhase - Math.floor(atlasPhase)) * tileCount));
    const active = [], frames = [null];
    const ageStep = f32(f32(nativeStep * 100) * lifetime);
    let delay = f32(row.delay), clock = 0, burst = 0;

    function emitStep() {
      if (clock >= duration || row.burst.cycles === 1 && burst === 1) return;
      if (delay >= nativeStep) {
        delay = f32(delay - nativeStep);
        return;
      }
      const interval = f32(nativeStep - delay);
      delay = 0;
      clock = f32(clock + interval);
      if (clock >= duration) return;
      const initialAge = f32(f32(f32(interval * birthFraction) * 100) * lifetime);
      // Unity evaluates the authored burst row once per simulation substep.
      if ((row.burst.cycles === 0 || burst === 0) && clock >= f32(burst * period)) {
        burst++;
        if (active.length < row.maxParticles) active.push(initialAge);
      }
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > maxElapsed) return;
      while (frames.length <= target) {
        for (let i = 0; i < active.length; i++) active[i] = f32(active[i] + ageStep);
        cull(active);
        emitStep();
        frames.push(active.length ? active.slice() : null);
      }
      for (const age of frames[target] || []) {
        const phase = f32(age * phaseScale);
        const size = f32(width * Math.max(0, f32(sizeAt(phase) * multiplier)));
        const color = gradient ? nativeColorAtTime(gradient, phase).map(value => Math.round(value * 255)) : start;
        // These source modules produce only constants at initialization.
        // The engine's seed changes its hidden particle words but no emitted attribute.
        emit(0, 0, 0, size, ...color, tile);
      }
    }};
  }

  global.MVStudioStageBurstSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
