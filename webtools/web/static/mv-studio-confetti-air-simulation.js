(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 1425677110, cycle = 90, rate = 70, lifetime = f32(8.2), ageScale = f32(.01);
  const fixedStep = f32(.02), catchUpStep = f32(.2), clockBias = f32(.0001), birthBias = f32(1e-6);
  const roll = f32(6.283185005187988), spinSalt = 0x6aed452e, directionSalt = 0xff2bb1a4, velocitySalt = 0xe0fbd834;
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const vector = (row, size) => Array.isArray(row) && row.length === size && row.every(Number.isFinite);
  const unit = value => value >= 0 && value <= 1;
  const bits = new Float32Array(1), words = new Uint32Array(bits.buffer);
  const rootSeeds = Float32Array.from({length: 256}, (_, index) => {
    const bins = index < 128 ? 128 : 64;
    return Math.floor(512 / Math.sqrt((128 + index % 128 + .5) / bins) + .5) / 512;
  });
  const rootScales = Float32Array.from({length: 256}, (_, exponent) => 2 ** -((exponent - 127) >> 1));

  function supported(row) {
    return row?.role === "air" && row.seed === seed && row.rate === rate && vector(row.position, 3) &&
      row.position[0] === 0 && row.position[1] === 15 && row.position[2] === 0 && vector(row.rotation, 4) &&
      row.rotation[0] === 0 && row.rotation[1] === 0 && row.rotation[2] === 0 && row.rotation[3] === 1 &&
      Array.isArray(row.startColors) && row.startColors.length === 2 && row.startColors.every(rgba => vector(rgba, 4) && rgba.every(unit)) &&
      Array.isArray(row.alphaKeys) && row.alphaKeys.length === 4 && row.alphaKeys.every((key, i) =>
        vector(key, 2) && Number.isInteger(key[0]) && key[0] >= 0 && key[0] <= 65535 &&
        (!i || key[0] > row.alphaKeys[i - 1][0]) && unit(key[1]));
  }

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let reciprocal = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32(2 - value * reciprocal));
    return reciprocal;
  }

  function inverseRoot(value) {
    if (value <= 1e-30) return 0;
    // The ARM estimate is constant within each mantissa bin. The exponent
    // parity selects the [1,2) or [2,4) table before the same refinements.
    bits[0] = value;
    const word = words[0], exponent = word >>> 23;
    const bin = ((word & 0x7fffff) >>> 16) + 128 * ((exponent - 127) & 1);
    let reciprocal = rootSeeds[bin] * rootScales[exponent];
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return reciprocal;
  }

  function emission(previous, next, carry) {
    const amount = next < previous ? f32(f32(f32(cycle - previous) * rate) + f32(next * rate)) :
      f32(f32(next - previous) * rate);
    const combined = f32(amount + carry), count = Math.trunc(combined);
    return {count, carry: f32(combined - count), reciprocal: amount < clockBias ? 1 : f32(1 / amount)};
  }

  function startState() {
    // The bounds scan uses absolute fixed steps and feeds back its rate carry.
    const start = f32(cycle - lifetime), end = f32(start + lifetime);
    let time = start, phase = start, carry = 0;
    while (f32(time + clockBias) < end) {
      time = f32(time + fixedStep);
      const next = f32(time % cycle);
      ({carry} = emission(phase, next, carry));
      phase = next;
    }
    return {frame: 0, clock: start, carry: f32(f32(1 - carry) + clockBias), group: 0, active: []};
  }

  // The X and Z curves repeat every half of normalized lifetime. The two
  // authored sides have equal and opposite tangent-free Hermite segments.
  function side(phase) {
    const wrapped = f32(phase % .5), second = wrapped >= .25;
    const t = f32(wrapped - (second ? .25 : 0));
    const sample = f32(-1 + f32(t * f32(t * f32(96 - f32(t * 256)))));
    return second ? -sample : sample;
  }

  function sizeAt(phase) {
    const first = f32(.95), inSlope = f32(-19.999996185302734);
    if (phase <= first) return 1;
    if (phase >= 1) return 0;
    const span = f32(1 - first), incoming = f32(span * inSlope), inverseSpanSquared = f32(1 / f32(span * span));
    const a = f32(f32(inverseSpanSquared * f32(f32(incoming + 1) + 1)) / span);
    const b = f32(inverseSpanSquared * f32(-3 - incoming));
    const t = f32(phase - first);
    return Math.max(0, f32(1 + f32(t * f32(t * f32(b + f32(t * a))))));
  }

  function cull(active) {
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

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeRandom, nativeUnit, nativeFrame, nativeStep, nativeStepRate, nativeColorAtTime} = particles;
    const inverseLife = inverse(lifetime), checkpointInterval = 2 * nativeStepRate;
    const {alphaKeys, startColors: [from, to]} = row;
    const keys = alphaKeys.map(([stamp, alpha]) => [f32(stamp / 65535), 255, 255, 255, byte(alpha)]);
    const streams = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [];
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());

    function birth({initial, shape}) {
      const word = initial();
      initial(); // Fixed lifetime still consumes its lane.
      const size = lerp(f32(1.2), f32(.9), nativeUnit(initial()));
      const rz = lerp(-roll, roll, nativeUnit(initial())), rx = lerp(-roll, roll, nativeUnit(initial()));
      const ry = lerp(-roll, roll, nativeUnit(initial())), weight = nativeUnit(initial());
      const tint = {start: from.map((value, axis) => byte(lerp(value, to[axis], weight))), keys};
      const x = f32(f32(nativeUnit(shape()) - .5) * 30);
      const y = f32(f32(nativeUnit(shape()) - .5) * 5);
      const z = f32(f32(nativeUnit(shape()) - .5) * 10);
      const drift = nativeRandom((word + velocitySalt) >>> 0);
      const wx = nativeUnit(drift()), vy = lerp(-.75, -1.5, nativeUnit(drift())), wz = nativeUnit(drift());
      const sign = salted(word, directionSalt) > 0 ? 1 : -1;
      const spin = f32(sign * lerp(f32(10.471975326538086), f32(5.235987663269043), salted(word, spinSalt)));
      return {x, y, z, rx, ry, rz, size, tint, spin, wx, vy, wz};
    }

    function advance(atom, dt, inverseStep) {
      const {source, x, y, z} = atom, phase = f32(atom.age * ageScale);
      const wave = side(phase), lowX = f32(wave * 2);
      let vx = lerp(lowX, -lowX, source.wx), vy = source.vy, vz = lerp(wave, -wave, source.wz);
      if (inverseStep) {
        const squared = f32(f32(x * x) + f32(f32(y * y) + f32(z * z)));
        const reciprocal = inverseRoot(squared), radial = f32(dt * .5);
        const displacement = axis => f32(f32(f32(axis + f32(f32(axis * reciprocal) * radial)) - axis) * inverseStep);
        vx = f32(vx + displacement(x));
        vy = f32(vy + displacement(y));
        vz = f32(vz + displacement(z));
      }
      atom.x = f32(x + f32(vx * dt));
      atom.y = f32(y + f32(vy * dt));
      atom.z = f32(z + f32(vz * dt));
      atom.roll = f32(atom.roll + f32(source.spin * dt));
      atom.age = f32(atom.age + f32(f32(dt * 100) * inverseLife));
    }

    function step(state, dt) {
      const inverseStep = dt > birthBias ? inverse(dt) : 0;
      const {active} = state;
      for (const atom of active) advance(atom, dt, inverseStep);
      cull(active);
      const previous = state.clock, current = f32(previous + dt);
      state.clock = current > cycle ? f32(current - cycle) : current;
      const {count, carry, reciprocal} = emission(previous, state.clock, state.carry);
      state.carry = carry;
      if (!count) return;
      const newborns = [];
      for (let i = 0; i < count; i += 4) {
        if (state.group === groups.length) groups.push(streams.map(birth));
        const sources = groups[state.group++];
        for (let lane = 0; lane < Math.min(4, count - i); lane++) {
          const source = sources[lane], atom = {source, x: source.x, y: source.y, z: source.z, roll: source.rz, age: 0};
          const fraction = Math.max(birthBias, Math.min(1, f32(f32(i + lane + state.carry) * reciprocal)));
          const within = f32(dt * fraction);
          advance(atom, within, within > birthBias ? inverse(within) : 0);
          newborns.push(atom);
        }
      }
      const gap = (4 - active.length % 4) % 4, first = gap ? Math.max(0, count - gap) : 0;
      for (let i = 0; i < count; i++) active.push(newborns[(first + i) % count]);
    }

    function copy(state) {
      return {...state, active: state.active.map(atom => ({...atom}))};
    }

    const warm = startState(), layouts = new Map();
    let remainder = lifetime;
    for (let dt = catchUpStep; remainder >= dt; dt = remainder > 5 ? catchUpStep : fixedStep) {
      step(warm, dt);
      remainder = f32(remainder - dt);
    }

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      let residue = f32(f32(1 / fps) + remainder);
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const entry = {state: copy(warm), checkpoints: [warm], grouped, residue};
      layouts.set(fps, entry);
      return entry;
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > cycle) return;
      const entry = layouts.get(fps) || layout(fps);
      const {checkpoints, grouped, residue} = entry;
      const saved = Math.min(checkpoints.length - 1, Math.floor(target / checkpointInterval));
      if (target < entry.state.frame || checkpoints[saved].frame > entry.state.frame) entry.state = copy(checkpoints[saved]);
      const {state} = entry;
      while (state.frame < target) {
        step(state, nativeStep);
        state.frame++;
        if (state.frame === grouped && residue >= birthBias) step(state, residue);
        if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(copy(state));
      }
      for (const atom of state.active) {
        const {source} = atom, phase = f32(atom.age * ageScale);
        const rgba = nativeColorAtTime(source.tint, phase).map(value => Math.round(value * 255));
        emit(-atom.x, atom.y, atom.z, f32(source.size * sizeAt(phase)), source.rx, source.ry, atom.roll, ...rgba);
      }
    }};
  }

  global.MVStudioConfettiAirSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
