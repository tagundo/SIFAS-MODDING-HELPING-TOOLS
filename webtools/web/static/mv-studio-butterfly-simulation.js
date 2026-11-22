(function (global) {
  "use strict";

  const f32 = Math.fround;
  const speed = f32(.001);
  const birthBias = f32(1e-6);
  const duration = 30;
  const streamSalt = 0x3fb09a55;
  let driftByFrame, finaleByFrame;

  function prepareFinale({nativeStep, nativeColorAtTime}) {
    const inverseLife = 0.18018017709255219;
    const step = f32(f32(nativeStep * 100) * inverseLife);
    const colors = {start: [255,255,255,255], keys: [[0,255,255,255,255],
      [f32(62933 / 65535),255,255,255,255], [1,255,255,255,0]]};
    const frames = [null];
    let age = f32(f32(f32(nativeStep * birthBias) * 100) * inverseLife);
    while (age <= 100) {
      const phase = f32(age * f32(.01));
      // The original optimized SizeModule cache has a constant segment
      // followed by this float32 cubic. Each operation rounds separately.
      const delta = Math.max(0, f32(phase - 0.9538178443908691));
      const quadratic = f32(f32(-2559.42919921875 * delta) + 236.39991760253906);
      const scale = f32(f32(f32(quadratic * delta) * delta) + 0.7479041218757629);
      const alpha = Math.round(nativeColorAtTime(colors, phase)[3] * 255);
      frames.push(Object.freeze({size: f32(9 * scale), alpha}));
      age = f32(age + step);
    }
    return frames;
  }

  function create(seed, profile) {
    const particles = global.MVStudioStageParticles;
    const finale = profile === "finale";
    if (!particles || !Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff ||
        (!finale && profile !== undefined)) return null;
    const {nativeFrame, nativeStep, nativeStepRate, nativeRandom, nativeUnit} = particles;
    const particleSeed = nativeRandom(seed)() >>> 0;
    const random = Array.from({length: 4}, (_, lane) => nativeUnit(nativeRandom((particleSeed + streamSalt + lane) >>> 0)()));
    if (!driftByFrame) {
      const step = f32(nativeStep * speed);
      driftByFrame = new Float32Array(duration * nativeStepRate);
      // The single burst uses the native minimum birth fraction. Thereafter
      // its combined base and additional velocities advance at fixed steps.
      driftByFrame[1] = f32(f32(nativeStep * birthBias) * speed);
      for (let frame = 2; frame < driftByFrame.length; frame++) {
        driftByFrame[frame] = f32(driftByFrame[frame - 1] + step);
      }
    }
    if (finale && !finaleByFrame) finaleByFrame = prepareFinale(particles);

    const maxFrame = finale ? finaleByFrame.length : driftByFrame.length;
    function sample(elapsed, fps) {
      const frame = nativeFrame(elapsed, fps);
      if (frame < 1 || frame >= maxFrame) return null;
      const drift = driftByFrame[frame];
      return finale ? [drift, -drift, drift] : [-drift, -drift, 0];
    }
    if (!finale) return {random, sample};
    return {random, sample, appearance(elapsed, fps) {
      return finaleByFrame[nativeFrame(elapsed, fps)] || null;
    }};
  }

  global.MVStudioButterflySimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
