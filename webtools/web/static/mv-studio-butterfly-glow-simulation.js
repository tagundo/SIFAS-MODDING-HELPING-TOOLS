(function (global) {
  "use strict";

  const f32 = Math.fround;
  const birthFraction = f32(1e-6), percentToUnit = f32(.01);
  const framesByProfile = new Map();

  // Native SizeModule caches each segment as start time, followed by
  // float32 cubic coefficients. The readers verify the source keys.
  const opening = {
    inverseLife: 0.03333333134651184,
    startSize: f32(.2),
    sizeMultiplier: 2,
    sizePeriod: .5818743109703064,
    sizeCurve: [
      [0, 1165.893798828125, -126.197265625, 0, .9397342801094055],
      [.07216052711009979, -2098.32421875, 202.4778289794922, 0, .7206919193267822],
      [.13649053871631622, 1025.80908203125, -125.65316772460938, 0, 1],
      [.21815171837806702, -5376.5, 379.1364440917969, 0, .7206919193267822],
      [.26516327261924744, 621.8660278320312, -90.00369262695312, 0, 1],
      [.3616510331630707, -2097.365234375, 202.4161376953125, 0, .7206919193267822],
      [.42599084973335266, 937.887451171875, -118.36670684814453, 0, 1],
      [.5101279616355896, -1512.565185546875, 162.7815399169922, 0, .7206919193267822],
    ],
    startColor: [11, 60, 255, 36],
  };
  const finale = {
    inverseLife: 1.1111111640930176,
    startSize: .5,
    sizeMultiplier: 1,
    sizeCurve: [
      [0, 1.6807677745819092, -2.254844903945923, 1.4542194604873657, .5057507753372192],
      [.45689523220062256, -.2373366504907608, -.21758662164211273, .44636112451553345, .859779417514801],
    ],
    startColor: [252, 143, 255, 153],
    alphaKeys: [[0, 0], [23805, 187], [38839, 200], [46356, 220], [65535, 0]],
  };

  function prepare(source, {nativeColorAtTime, nativeStep}) {
    const {inverseLife, startSize, sizeMultiplier, sizePeriod, sizeCurve, startColor, alphaKeys} = source;
    const colors = alphaKeys && {start: startColor, keys: alphaKeys.map(([stamp, alpha]) =>
      [f32(stamp / 65535), 255, 255, 255, alpha])};
    const frames = [null];
    const step = f32(f32(nativeStep * 100) * inverseLife);
    let age = f32(f32(f32(nativeStep * birthFraction) * 100) * inverseLife);
    const fixedColor = Object.freeze(startColor);
    while (age <= 100) {
      const phase = f32(age * percentToUnit);
      const curvePhase = sizePeriod && phase >= sizePeriod
        ? f32(phase - f32(Math.floor(f32(phase / sizePeriod)) * sizePeriod)) : phase;
      // The opening uses the generic cached curve (right-open segments).
      // The finale uses the two-segment native optimized dispatch.
      let segment = 0;
      while (segment + 1 < sizeCurve.length && (source === finale
        ? curvePhase > sizeCurve[segment + 1][0] : curvePhase >= sizeCurve[segment + 1][0])) segment++;
      const [start, a, b, c, d] = sizeCurve[segment];
      const t = f32(phase - f32(start + f32(phase - curvePhase)));
      let scale = f32(f32(a * t) + b);
      scale = f32(f32(scale * t) + c);
      scale = f32(f32(scale * t) + d);
      const size = f32(startSize * f32(scale * sizeMultiplier));
      const rgba = colors ? Object.freeze(nativeColorAtTime(colors, phase).map(value => Math.round(value * 255))) : fixedColor;
      frames.push(Object.freeze({size, rgba}));
      age = f32(age + step);
    }
    return frames;
  }

  function create(profile) {
    const particles = global.MVStudioStageParticles;
    if (!particles || (profile !== "opening" && profile !== "finale")) return null;
    let frames = framesByProfile.get(profile);
    if (!frames) {
      frames = prepare(profile === "opening" ? opening : finale, particles);
      framesByProfile.set(profile, frames);
    }
    return {sample(elapsed, fps) {
      return frames[particles.nativeFrame(elapsed, fps)] || null;
    }};
  }

  global.MVStudioButterflyGlowSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
