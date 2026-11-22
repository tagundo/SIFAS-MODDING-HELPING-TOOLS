(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 1586243424, duration = 12;
  const ageScale = f32(.01), birthBias = f32(1e-6);
  const velocitySalt = 0xe0fbd834, speedSalt = 0x96aa4de3, speedModifierSalt = 0xba821f34;
  const spinSalt = 0x6aed452e, directionSalt = 0xff2bb1a4;
  const fullTurn = f32(6.283185005187988);
  const schedule = [[f32(.1), 30], [f32(.2), 100], [f32(.4), 100], [f32(.6), 60]];
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = x => Math.trunc(f32(f32(x * 255) + .5));
  const valid = (a, n) => Array.isArray(a) && a.length === n && a.every(Number.isFinite);

  const startSpeed = [
    [[0, 1, -2.207141160964966], [.9980774521827698, .27537664771080017, 0]],
    [[0, .6278756856918335, -1.1490671634674072], [.9980774521827698, .3180050849914551, -.12376324832439423]],
  ];
  const speedOverLife = [
    [[0, 1, -12.329466819763184], [.15709102153778076, .1557157337665558, -.6902754306793213], [1, .025065496563911438, 0]],
    [[0, 1, -6.630202770233154], [.2608562409877777, .3196832239627838, -.9326057434082031], [1, .094718337059021, -.19471216201782227]],
  ];
  const sizeOverLife = [[.8644065856933594, f32(.9), 0], [1, 0, -17.877954483032227]];

  function keys(rows, count, width) {
    return Array.isArray(rows) && rows.length === count && rows.every((row, index) =>
      valid(row, width) && Number.isInteger(row[0]) && row[0] >= 0 && row[0] <= 65535 &&
      (!index || row[0] > rows[index - 1][0]) && row.slice(1).every(x => x >= 0 && x <= 1));
  }

  function supported(row) {
    const color = row?.startColor, rotation = row?.rotation;
    return row?.profile === "05" && row.role === "red-burst" && row.seed === seed && row.rate === 0 &&
      valid(row.position, 3) && row.position[0] === f32(.512) && row.position[1] === f32(.021) && row.position[2] === f32(4.133) &&
      valid(rotation, 4) && rotation[0] === 0 && rotation[2] === 0 &&
      Math.abs(rotation[1] - .983316296761958) < 1e-6 && Math.abs(rotation[3] + .18190398709854855) < 1e-6 &&
      keys(row.alphaKeys, 4, 2) && keys(color?.rgb?.[0], 2, 4) && keys(color?.rgb?.[1], 2, 4) &&
      keys(color?.alpha?.[0], 2, 2) && keys(color?.alpha?.[1], 2, 2);
  }

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let reciprocal = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32(2 - value * reciprocal));
    return reciprocal;
  }

  function inverseSquareRoot(value) {
    if (!(value > 0)) return 0;
    const scale = 2 ** -Math.floor(Math.log2(value) / 2), mantissa = value * scale * scale;
    const bins = mantissa < 2 ? 128 : 64, midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let reciprocal = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return reciprocal;
  }

  function cosine(turns) {
    const nearby = turns < 0 ? -8388608 : 8388608;
    const folded = f32(turns - f32(f32(turns + nearby) - nearby));
    const x = f32(.25 - Math.abs(folded)), x2 = f32(x * x), x4 = f32(x2 * x2);
    const a = f32(39.65703201293945 * f32(x4 * x4));
    const b = f32(81.60182189941406 + f32(x2 * -76.56861877441406));
    const c = f32(6.283185005187988 + f32(x2 * -41.34165954589844));
    return f32(x * f32(a + f32(c + f32(x4 * b))));
  }

  function compile(keys) {
    // Unity's AnimationCurve caches these unweighted cubic coefficients.
    const segments = [];
    for (let i = 0; i < keys.length - 1; i++) {
      const [from, value, outSlope] = keys[i], [to, target, inSlope] = keys[i + 1];
      const span = f32(to - from), delta = f32(target - value), square = f32(1 / f32(span * span));
      const out = f32(span * outSlope), incoming = f32(span * inSlope);
      const quadratic = f32(f32(f32(f32(delta + delta) + delta) - out) - out);
      const cubic = f32(f32(f32(out + incoming) - delta) - delta);
      segments.push([from, to, value, f32(f32(square * cubic) / span),
        f32(square * f32(quadratic - incoming)), outSlope]);
    }
    return phase => {
      if (phase <= keys[0][0]) return keys[0][1];
      for (const [from, to, value, a, b, c] of segments) {
        if (phase >= to) continue;
        const t = f32(phase - from);
        return f32(value + f32(t * f32(c + f32(t * f32(b + f32(t * a))))));
      }
      return keys[keys.length - 1][1];
    };
  }

  function gradient(rows, stamp) {
    const [first, last] = rows;
    const weight = Math.min(1, Math.max(0, f32(f32(stamp - first[0]) / (last[0] - first[0]))));
    return first.slice(1).map((x, i) => byte(lerp(x, last[i + 1], weight)));
  }

  function dot(x, y, z) {
    return f32(f32(x * x) + f32(f32(y * y) + f32(z * z)));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep: dt, nativeStepRate} = particles;
    const {position: [px, py, pz], rotation: [, qy, , qw], startColor, alphaKeys} = row;
    const cosYaw = f32(1 - 2 * qy * qy), sinYaw = f32(2 * qy * qw);
    const gradients = alphaKeys.map(([phase, alpha]) => [f32(phase / 65535), 255, 255, 255, byte(alpha)]);
    const startCurves = startSpeed.map(compile), speedCurves = speedOverLife.map(compile), sizeCurve = compile(sizeOverLife);
    const angle = f32(f32(f32(19.18) * f32(Math.PI / 180)) * f32(1 / (2 * Math.PI)));
    const sinCone = cosine(f32(angle - .25)), cosCone = cosine(angle);
    const shapeY = .4330301284790039, shapeZ = -.9013794660568237;
    const nativeStreams = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [], checkpoints = [{clock: 0, group: 0, burst: 0, active: []}];
    let frame = 0, clock = 0, group = 0, burst = 0, active = [];
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());

    function readBirth({initial, shape}) {
      const word = initial(), life = inverse(lerp(5, 12, nativeUnit(initial())));
      const width = lerp(f32(.4), f32(.2), nativeUnit(initial())), roll = nativeUnit(initial()), color = nativeUnit(initial());
      const turns = f32(f32(f32(2 * Math.PI) * nativeUnit(shape())) * f32(1 / (2 * Math.PI)));
      const u = nativeUnit(shape()), area = f32(f32(1 - u) + f32(f32(.001) * u));
      const radius = f32(area * inverseSquareRoot(area)), coneX = f32(radius * cosine(turns));
      const coneY = f32(radius * cosine(f32(turns - .25)));
      const vx = f32(sinCone * coneX), vy = f32(sinCone * coneY), vz = cosCone;
      const depth = f32(f32(1.43) * nativeUnit(shape())), inv = inverseSquareRoot(dot(vx, vy, vz));
      const localX = f32(f32(f32(.9) * coneX) + f32(f32(vx * inv) * depth));
      const localY = f32(f32(f32(.9) * coneY) + f32(f32(vy * inv) * depth));
      const localZ = f32(f32(vz * inv) * depth);
      const x = f32(localX * f32(2.1));
      const y = f32(f32(localY * shapeY) + f32(localZ * f32(-shapeZ * .5)));
      const z = f32(f32(localY * shapeZ) + f32(localZ * f32(shapeY * .5)));
      const dx = f32(vx * f32(2.1));
      const dy = f32(f32(vy * shapeY) + f32(vz * f32(-shapeZ * .5)));
      const dz = f32(f32(vy * shapeZ) + f32(vz * f32(shapeY * .5)));
      const direction = inverseSquareRoot(dot(dx, dy, dz));
      const velocity = nativeRandom((word + velocitySalt) >>> 0);
      const ux = lerp(f32(-.1), 3, nativeUnit(velocity())), uy = lerp(f32(1.2), 2.5, nativeUnit(velocity()));
      const uz = lerp(f32(-.1), 1, nativeUnit(velocity()));
      const sign = salted(word, directionSalt) > 0 ? 1 : -1;
      const spin = f32(sign * lerp(f32(10.471975326538086), f32(5.235987663269043), salted(word, spinSalt)));
      return {x, y, z, dx: f32(dx * direction), dy: f32(dy * direction), dz: f32(dz * direction),
        ux, uy, uz, life, width, roll, color, spin, speed: salted(word, speedSalt), modifier: salted(word, speedModifierSalt)};
    }

    function start(atom, phase) {
      const stamp = f32(phase * 65535), source = atom.source;
      const min = gradient(startColor.rgb[0], stamp).concat(gradient(startColor.alpha[0], stamp));
      const max = gradient(startColor.rgb[1], stamp).concat(gradient(startColor.alpha[1], stamp));
      const mix = Math.trunc(f32(255 * source.color));
      atom.color = {start: min.map((x, i) => x + ((128 + mix * (max[i] - x)) >> 8)), keys: gradients};
      const time = Math.min(1, f32(phase * 2));
      const ease = f32(time * f32(time * f32(3 - f32(2 * time))));
      atom.roll = lerp(f32(ease * fullTurn), f32(-ease * fullTurn), source.roll);
      const speed = lerp(f32(3 * startCurves[0](phase)), f32(3 * startCurves[1](phase)), source.speed);
      atom.vx = f32(speed * source.dx); atom.vy = f32(speed * source.dy); atom.vz = f32(speed * source.dz);
    }

    const inverseStep = inverse(dt);

    function advance(atom, step, modifier) {
      const phase = f32(atom.age * ageScale), source = atom.source;
      const speed = lerp(speedCurves[0](phase), speedCurves[1](phase), modifier);
      let {ux, uy, uz} = source;
      if (step > birthBias) {
        // Unity applies the speed modifier before orbital/radial displacement,
        // then divides it out when reconstructing the additive velocity.
        const motionStep = f32(step * speed);
        const theta = f32(f32(motionStep * f32(.1)) * f32(1 / (2 * Math.PI)));
        const cosOrbit = cosine(theta), sinOrbit = cosine(f32(theta - .25));
        const x = f32(atom.x - f32(-.2)), y = atom.y, z = atom.z;
        const nextX = f32(f32(cosOrbit * x) - f32(sinOrbit * y));
        const nextY = f32(f32(sinOrbit * x) + f32(cosOrbit * y));
        const inv = inverseSquareRoot(dot(nextX, nextY, z)), radial = f32(motionStep * f32(-.2));
        const offset = (previous, rotated) => {
          const moved = f32(rotated + f32(f32(rotated * inv) * radial));
          return f32(f32(f32(moved - previous) / speed) * inverseStep);
        };
        ux = f32(ux + offset(x, nextX));
        uy = f32(uy + offset(y, nextY));
        uz = f32(uz + offset(z, z));
      }
      atom.vy = f32(atom.vy - f32(f32(f32(9.81) * step) * f32(.1)));
      atom.x = f32(atom.x + f32(f32(f32(atom.vx + ux) * speed) * step));
      atom.y = f32(atom.y + f32(f32(f32(atom.vy + uy) * speed) * step));
      atom.z = f32(atom.z + f32(f32(f32(atom.vz + uz) * speed) * step));
      atom.roll = f32(atom.roll + f32(source.spin * step));
      atom.age = f32(atom.age + f32(f32(step * 100) * source.life));
    }

    function cull() {
      for (let first = 0; first < active.length;) {
        let removed = false;
        for (let i = Math.min(first + 3, active.length - 1); i >= first; i--) {
          if (active[i].age <= 100) continue;
          const tail = active.pop();
          if (i < active.length) active[i] = tail;
          removed = true;
        }
        if (!removed) first += 4;
      }
    }

    function step() {
      for (let i = 0; i < active.length; i++) advance(active[i], dt, active[i & ~3].source.modifier);
      cull();
      if (burst === schedule.length) return;
      clock = f32(clock + dt);
      const [begin, count] = schedule[burst];
      if (clock <= begin) return;
      burst++;
      const phase = f32(clock / duration), step = f32(dt * birthBias), births = [];
      for (let i = 0; i < count; i += 4) {
        if (group === groups.length) groups.push(nativeStreams.map(readBirth));
        const sources = groups[group++];
        for (let lane = 0; lane < Math.min(4, count - i); lane++) {
          const source = sources[lane], atom = {source, x: source.x, y: source.y, z: source.z, age: 0};
          start(atom, phase);
          advance(atom, step, sources[0].modifier);
          births.push(atom);
        }
      }
      // The original allocator fills the existing partial SIMD group from the new batch tail.
      const gap = (4 - active.length % 4) % 4;
      const first = gap ? Math.max(0, count - gap) : 0;
      for (let i = 0; i < count; i++) active.push(births[(first + i) % count]);
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || elapsed > 60) return;
      const index = Math.min(checkpoints.length - 1, Math.floor(target / nativeStepRate));
      const savedFrame = index * nativeStepRate;
      if (target < frame || savedFrame > frame) {
        const saved = checkpoints[index];
        ({clock, group, burst} = saved);
        frame = savedFrame;
        active = saved.active.map(atom => ({...atom}));
      }
      while (frame < target) {
        step();
        frame++;
        if (frame === checkpoints.length * nativeStepRate) {
          checkpoints.push({clock, group, burst, active: active.map(atom => ({...atom}))});
        }
      }
      for (const atom of active) {
        const phase = f32(atom.age * ageScale);
        const rgba = nativeColorAtTime(atom.color, phase).map(x => Math.round(x * 255));
        const x = f32(px + f32(f32(-atom.x * cosYaw) + f32(atom.z * sinYaw)));
        const y = f32(py + atom.y), z = f32(pz + f32(f32(atom.x * sinYaw) + f32(atom.z * cosYaw)));
        // The native 2D Mesh path uses +Y when its custom rotation axis is zero.
        emit(x, y, z, f32(atom.source.width * sizeCurve(phase)), 0, atom.roll, 0, ...rgba);
      }
    }};
  }

  global.MVStudioAutumnRedBurstSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
