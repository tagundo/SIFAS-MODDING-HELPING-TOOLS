(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const cycle = 200;
  const seed = -1462782512;
  const lifetime = .25;
  const maximumRoll = f32(6.283185);
  const white = [255, 255, 255, 255];
  const schedules = new Map();

  function supported(row, particles) {
    return row?.seed === seed && row.lifetime === lifetime && row.capacity === 20 &&
      (row.burstPeriod === f32(.08) || row.burstPeriod === f32(.05)) &&
      (row.size === f32(.6) || row.size === f32(.8)) &&
      Array.isArray(row.rollRange) && row.rollRange.length === 2 &&
      row.rollRange[0] === 0 && row.rollRange[1] === maximumRoll &&
      particles.validNativeColor(row.color);
  }

  function createSchedule(period, particles) {
    const {nativeRandom, nativeUnit, nativeStep: dt} = particles;
    const ageStep = f32(f32(dt * 100) / lifetime);
    const ages = [];
    let phaseAge = f32(f32(f32(dt * birthBias) * 100) / lifetime);
    while (phaseAge <= 100) {
      ages.push(f32(phaseAge * fraction));
      phaseAge = f32(phaseAge + ageStep);
    }

    // Each burst is one particle. The initial worker advances four SIMD lanes,
    // but only lane zero is used and its stream never depends on the padding.
    const draw = nativeRandom(seed);
    const frames = [[]], active = [];
    let clock = 0, burst = 0;
    function frameAt(frame) {
      while (frame >= frames.length) {
        const tick = frames.length;
        const expired = active.findIndex(particle => tick - particle.tick >= ages.length);
        if (expired !== -1) {
          const tail = active.pop();
          if (expired < active.length) active[expired] = tail;
        }

        // Native compares its float32 clock against repeat index × interval.
        // Adding interval to a prior burst boundary changes the schedule.
        clock = f32(clock + dt);
        if (clock >= f32(burst * period)) {
          draw(); // Particle seed.
          draw(); // Fixed lifetime.
          draw(); // Fixed scalar size.
          const roll = f32(maximumRoll * nativeUnit(draw()));
          draw(); // Fixed start color.
          active.push({tick, roll});
          burst++;
        }
        frames.push(active.slice());
      }
      return frames[frame];
    }

    return {ages, frameAt};
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row, particles)) return null;
    const {burstPeriod, size, color} = row;
    let schedule = schedules.get(burstPeriod);
    if (!schedule) {
      schedule = createSchedule(burstPeriod, particles);
      schedules.set(burstPeriod, schedule);
    }
    const colors = schedule.ages.map(age => particles.nativeColorAtTime(color, age)
      .map(value => Math.round(value * 255)));
    const gradient = {start: white, keys: color.keys};
    const gradientAlphas = schedule.ages.map(age => Math.round(particles.nativeColorAtTime(gradient, age)[3] * 255));
    return {
      sample(elapsed, fps, emit) {
        const frame = particles.nativeFrame(elapsed, fps);
        if (frame < 0 || elapsed >= cycle) return;
        const ticksPerFrame = particles.nativeStepRate / fps;
        for (const particle of schedule.frameAt(frame)) {
          const age = frame - particle.tick;
          const [r, g, b, a] = colors[age];
          // The Animator supplies one start color to all particle substeps
          // in the same display frame.
          const birthElapsed = Math.ceil(particle.tick / ticksPerFrame) / fps;
          emit(size, size, particle.roll, r, g, b, a, birthElapsed, gradientAlphas[age]);
        }
      },
    };
  }

  global.MVStudioResidentCoreSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
