(function (global) {
  "use strict";

  const f32 = Math.fround;
  const speed = f32(.001);
  const birthBias = f32(1e-6);
  const duration = 30;
  const streamSalt = 0x3fb09a55;
  let driftByFrame;

  function create(seed) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff) return null;
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

    return {random, sample(elapsed, fps) {
      const frame = nativeFrame(elapsed, fps);
      if (frame < 1 || frame >= driftByFrame.length) return null;
      const drift = -driftByFrame[frame];
      return [drift, drift, 0];
    }};
  }

  global.MVStudioButterflySimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
