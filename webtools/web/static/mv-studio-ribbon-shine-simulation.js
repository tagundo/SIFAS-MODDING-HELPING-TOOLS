(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fixedStep = f32(.02), birthBias = f32(1e-6), clockBias = f32(.0001);
  const phaseScale = f32(.01), maxElapsed = 60;
  const speedSalt = 0x96aa4de3, sizeSalt = 0x8d2c8431;
  const profiles = {
    13: {advance: 1, boundsCenter: Object.freeze([-6.480669021606445, 0, -.5009363889694214])},
    10: {advance: f32(.2), boundsCenter: Object.freeze([-4.985130310058594, 0, -.3853357136249542])},
  };
  const rangeIs = (value, a, b) => Array.isArray(value) && value.length === 2 && value[0] === a && value[1] === b;
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let estimate = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) estimate = f32(estimate * f32(2 - value * estimate));
    return estimate;
  }

  function emission(previous, next, carry, cycle, rate) {
    const amount = next < previous ? f32(f32(f32(cycle - previous) * rate) + f32(next * rate)) :
      f32(f32(next - previous) * rate);
    const combined = f32(amount + carry), count = Math.trunc(combined);
    return {count, carry: f32(combined - count), reciprocal: amount < clockBias ? 1 : f32(1 / amount)};
  }

  function startState(horizon, cycle, rate) {
    // The analytic bounds prepass uses an absolute clock, then maps each
    // endpoint into the loop; actual prewarm starts from the scan's carry.
    const start = f32(f32(Math.ceil(f32(horizon / cycle)) * cycle) - horizon);
    const end = f32(start + horizon);
    let time = start, phase = f32(start % cycle), carry = 0;
    while (f32(time + clockBias) < end) {
      time = f32(time + fixedStep);
      const next = f32(time % cycle);
      ({carry} = emission(phase, next, carry, cycle, rate));
      phase = next;
    }
    return {frame: 0, clock: f32(start % cycle), carry: f32(f32(1 - carry) + clockBias), group: 0, active: []};
  }

  function checked(cue, seed, curves, title) {
    const horizon = Array.isArray(cue?.lifetime) && cue.lifetime[1];
    return (horizon === 10 || horizon === 13) && rangeIs(cue.lifetime, 10, horizon) &&
      cue.cycle === 5 && cue.rate === 10 && rangeIs(cue.speed, .5, 1) && rangeIs(cue.size, f32(.05), f32(.3)) &&
      Array.isArray(cue.box) && cue.box.length === 3 && cue.box[0] === f32(.42) && cue.box[1] === f32(3.86) && cue.box[2] === 1 &&
      Number.isFinite(cue.shapeYaw) && f32(cue.shapeYaw * 180 / Math.PI) === f32(94.42) &&
      Array.isArray(cue.sizeCurves) && cue.sizeCurves.length === 2 &&
      cue.sizeCurves.every(curve => title.boundedCurve(curve, curves.validCurve)) &&
      Number.isInteger(seed) && seed >= 0 && seed <= 0xffffffff;
  }

  function create(cue, seed) {
    const particles = global.MVStudioStageParticles, curves = global.MVStudioStageMotion, title = global.MVStudioTitle;
    if (!particles || !curves || !title || !checked(cue, seed, curves, title)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate} = particles;
    const {cycle, rate, sizeCurves: [lower, upper]} = cue;
    const maximumLife = cue.lifetime[1], profile = profiles[maximumLife];
    // Native ShapeModule converts the authored 94.42-degree local Y rotation
    // into this scale-and-rotation matrix before drawing from the box.
    const boxXX = -.03236819803714752, boxXZ = .9970260262489319;
    const boxZX = -.41875091195106506, boxZZ = -.07706713676452637;
    const streams = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const births = [];
    const checkpointInterval = nativeStepRate * 2;

    function birth({initial, shape}) {
      const word = initial(), life = inverse(lerp(10, maximumLife, nativeUnit(initial())));
      const size = lerp(cue.size[0], cue.size[1], nativeUnit(initial()));
      initial(); initial(); // Fixed roll and white color consume their own words.
      const sx = f32(nativeUnit(shape()) - .5), sy = f32(nativeUnit(shape()) - .5), sz = f32(nativeUnit(shape()) - .5);
      const x = f32(f32(boxXX * sx) + f32(boxXZ * sz)), y = f32(cue.box[1] * sy);
      const z = f32(f32(boxZX * sx) + f32(boxZZ * sz));
      const speed = lerp(.5, 1, nativeUnit(nativeRandom((word + speedSalt) >>> 0)()));
      const weight = nativeUnit(nativeRandom((word + sizeSalt) >>> 0)());
      const vx = f32(.9970259070396423 * speed), vz = f32(-.07706712931394577 * speed);
      return {x, y, z, vx, vz, size, life, weight};
    }

    function advance(atom, dt) {
      atom.x = f32(atom.x + f32(atom.source.vx * dt));
      atom.z = f32(atom.z + f32(atom.source.vz * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * atom.source.life));
    }

    function cull(active) {
      // Remove expired lanes in reverse order within each group of four.
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

    function step(state, dt) {
      const {active} = state;
      for (const atom of active) advance(atom, dt);
      cull(active);
      const previous = state.clock, next = f32(previous + dt);
      state.clock = next > cycle ? f32(next - cycle) : next;
      const {count, carry, reciprocal} = emission(previous, state.clock, state.carry, cycle, rate);
      state.carry = carry;
      if (!count) return;
      const newborns = [];
      for (let i = 0; i < count; i += 4) {
        if (state.group === births.length) births.push(streams.map(birth));
        const sources = births[state.group++];
        for (let lane = 0; lane < Math.min(4, count - i); lane++) {
          const source = sources[lane], atom = {source, x: source.x, z: source.z, age: 0};
          const fraction = Math.max(birthBias, Math.min(1, f32(f32(i + lane + state.carry) * reciprocal)));
          advance(atom, f32(dt * fraction));
          newborns.push(atom);
        }
      }
      // The native allocator moves the batch tail into unused slots of the previous SIMD group.
      const gap = (4 - active.length % 4) % 4;
      const firstLane = gap ? Math.max(0, count - gap) : 0;
      for (let i = 0; i < count; i++) active.push(newborns[(firstLane + i) % count]);
    }

    function copy(state) {
      return {...state, active: state.active.map(atom => ({...atom}))};
    }

    const warm = startState(maximumLife, cycle, rate);
    let remainder = maximumLife;
    // A fixed bounds scan supplies the initial phase/carry. The actual
    // prewarm reuses its chosen coarse step until five seconds remain.
    for (let dt = profile.advance; remainder >= dt; dt = remainder > 5 ? profile.advance : fixedStep) {
      step(warm, dt);
      remainder = f32(remainder - dt);
    }

    const layouts = new Map();

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      let residue = f32(f32(1 / fps) + remainder);
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const entry = {state: copy(warm), checkpoints: [warm], grouped, residue};
      layouts.set(fps, entry);
      return entry;
    }

    return {boundsCenter: profile.boundsCenter, sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > maxElapsed) return;
      const entry = layouts.get(fps) || layout(fps);
      const {checkpoints, grouped, residue} = entry;
      const saved = Math.min(checkpoints.length - 1, Math.floor(target / checkpointInterval));
      if (target < entry.state.frame || checkpoints[saved].frame > entry.state.frame) {
        entry.state = copy(checkpoints[saved]);
      }
      const {state} = entry;
      while (state.frame < target) {
        step(state, nativeStep);
        state.frame++;
        // Apply the surviving fraction of prewarm after the first display's full steps.
        if (state.frame === grouped && residue >= birthBias) step(state, residue);
        if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(copy(state));
      }
      for (const atom of state.active) {
        const {y, size, weight} = atom.source, phase = f32(atom.age * phaseScale);
        const min = f32(curves.evaluate(lower, phase)), max = f32(curves.evaluate(upper, phase));
        emit(-atom.x, y, atom.z, f32(size * Math.max(0, lerp(min, max, weight))));
      }
    }};
  }

  global.MVStudioRibbonShineSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
