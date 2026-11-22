(function (global) {
  "use strict";

  const f32 = Math.fround;
  const seed = 1586243424, duration = 4, ageScale = f32(.01), birthBias = f32(1e-6);
  const speedSalt = 0x96aa4de3, spinSalt = 0x6aed452e, directionSalt = 0xff2bb1a4;
  const fullTurn = f32(2 * Math.PI), inverseTurn = f32(1 / (2 * Math.PI));
  const stride = 11, lastTick = 92;
  const profiles = {
    "leaf-green": {delay: f32(.05), life: [f32(.3), f32(.7)], depth: 2, bursts: [[3, 25], [10, 15], [17, 15], [24, 15], [27, 5]]},
    "leaf-red": {delay: f32(.1), life: [.5, 1], depth: 1, bursts: [[13, 10], [22, 10], [30, 10]]},
  };
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.trunc(f32(f32(value * 255) + .5));
  const vector = (row, size) => Array.isArray(row) && row.length === size && row.every(Number.isFinite);
  const unit = value => value >= 0 && value <= 1;

  function validKeys(rows, count, size) {
    return Array.isArray(rows) && rows.length === count && rows.every((row, i) => vector(row, size) &&
      Number.isInteger(row[0]) && row[0] >= 0 && row[0] <= 65535 && (!i || row[0] > rows[i - 1][0]) && row.slice(1).every(unit));
  }

  function supported(row) {
    if (!row || (row.role !== "leaf-green" && row.role !== "leaf-red")) return false;
    const green = row.role === "leaf-green", {position, rotation, startColor, alphaKeys} = row;
    return row.seed === seed && vector(position, 3) && position[0] === f32(-.11) && position[1] === f32(-2.05) &&
      position[2] === f32(green ? .35 : .45) && vector(rotation, 4) && rotation[0] === 0 && rotation[1] === 0 &&
      Math.abs(rotation[2] - .1342455893754959) < 1e-6 && Math.abs(rotation[3] - .9909480810165405) < 1e-6 &&
      validKeys(alphaKeys, 4, 2) && (green ? validKeys(startColor?.rgb, 4, 4) && validKeys(startColor?.alpha, 2, 2) :
        vector(startColor, 4) && startColor.every(value => value === 1));
  }

  function inverse(value) {
    const scale = 2 ** -Math.floor(Math.log2(value)), bin = Math.floor(value * scale * 256);
    let reciprocal = Math.floor((Math.floor(524288 / (2 * bin + 1)) + 1) / 2) * scale / 512;
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32(2 - value * reciprocal));
    return reciprocal;
  }

  function inverseRoot(value) {
    if (!(value > 0)) return 0;
    const scale = 2 ** -Math.floor(Math.log2(value) / 2), mantissa = value * scale * scale;
    const bins = mantissa < 2 ? 128 : 64, midpoint = (Math.floor(mantissa * bins) + .5) / bins;
    let reciprocal = Math.floor(512 / Math.sqrt(midpoint) + .5) * (scale / 512);
    for (let i = 0; i < 2; i++) reciprocal = f32(reciprocal * f32((3 - f32(value * reciprocal) * reciprocal) / 2));
    return reciprocal;
  }

  function cosine(turns) {
    const offset = turns < 0 ? -8388608 : 8388608;
    const folded = f32(turns - f32(f32(turns + offset) - offset));
    const x = f32(.25 - Math.abs(folded)), x2 = f32(x * x), x4 = f32(x2 * x2);
    const a = f32(39.65703201293945 * f32(x4 * x4));
    const b = f32(81.60182189941406 + f32(x2 * -76.56861877441406));
    const c = f32(6.283185005187988 + f32(x2 * -41.34165954589844));
    return f32(x * f32(a + f32(c + f32(x4 * b))));
  }

  function distanceSquared(x, y, z) {
    return f32(f32(x * x) + f32(f32(y * y) + f32(z * z)));
  }

  function palette(rows, stamp) {
    const next = rows.findIndex(row => row[0] > stamp);
    const b = rows[next < 0 ? rows.length - 1 : next], a = next > 0 ? rows[next - 1] : b;
    const weight = a === b ? 0 : f32(f32(stamp - a[0]) / (b[0] - a[0]));
    return a.slice(1).map((value, i) => byte(lerp(value, b[i + 1], weight)));
  }

  function sizeAt(phase) {
    const first = .8644065856933594, initial = f32(.9), inSlope = -17.877954483032227;
    if (phase <= first) return initial;
    if (phase >= 1) return 0;
    const span = f32(1 - first), incoming = f32(span * inSlope), delta = -initial;
    const invSquare = f32(1 / f32(span * span));
    const a = f32(f32(invSquare * f32(f32(incoming - delta) - delta)) / span);
    const b = f32(invSquare * f32(f32(f32(delta + delta) + delta) - incoming));
    const elapsed = f32(phase - first);
    return Math.max(0, f32(initial + f32(elapsed * f32(elapsed * f32(b + f32(elapsed * a))))));
  }

  function create(row) {
    const particles = global.MVStudioStageParticles;
    if (!particles || !supported(row)) return null;
    const {nativeFrame, nativeStep: dt, nativeRandom, nativeUnit, nativeColorAtTime} = particles;
    const profile = profiles[row.role], green = row.role === "leaf-green";
    const {startColor, alphaKeys} = row;
    const keys = alphaKeys.map(([stamp, alpha]) => [f32(stamp / 65535), 255, 255, 255, byte(alpha)]);
    const initial = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const shape = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const angle = f32(f32(f32(1.27) * f32(Math.PI / 180)) * inverseTurn);
    const sin = cosine(f32(angle - .25)), cos = cosine(angle);
    const scaleX = f32(4.36), scaleY = f32(.24), radius = f32(.9), length = f32(1.43);
    const cosShape = 5.960464477539063e-8, sinShape = .9999999403953552;
    const yy = f32(scaleY * cosShape), zy = f32(-scaleY * sinShape);
    const yz = f32(profile.depth * sinShape), zz = f32(profile.depth * cosShape);
    const shapePosition = (x, y, z) => [f32(x * scaleX), f32(f32(y * yy) + f32(z * yz)), f32(f32(y * zy) + f32(z * zz))];
    const frames = [new Float32Array()], active = [];
    const acceleration = [f32(f32(.2660608183531643) * f32(9.81)), f32(f32(-.9639562434664515) * f32(9.81))];
    const frameGravity = acceleration.map(axis => f32(f32(axis * dt) * f32(.1)));
    let clock = 0, delay = profile.delay, nextBurst = 0;

    function advance(atom, step, gravity) {
      atom.vx = f32(atom.vx + gravity[0]);
      atom.vy = f32(atom.vy + gravity[1]);
      atom.x = f32(atom.x + f32(atom.vx * step));
      atom.y = f32(atom.y + f32(atom.vy * step));
      atom.z = f32(atom.z + f32(atom.vz * step));
      atom.roll = f32(atom.roll + f32(atom.spin * step));
      atom.age = f32(atom.age + f32(f32(step * 100) * atom.life));
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

    function birth(count, step) {
      const births = [], stamp = f32(f32(clock / duration) * 65535);
      const color = {start: green ? [...palette(startColor.rgb, stamp), ...palette(startColor.alpha, stamp)] : [255, 255, 255, 255], keys};
      const within = f32(step * birthBias), gravity = acceleration.map(axis => f32(f32(axis * within) * f32(.1)));
      for (let i = 0; i < count; i += 4) {
        for (let lane = 0; lane < 4; lane++) {
          const draw = initial[lane], makeShape = shape[lane], word = draw();
          const life = inverse(lerp(...profile.life, nativeUnit(draw()))), size = lerp(5, 7, nativeUnit(draw()));
          draw(); draw(); // Fixed initial Z/X still consume the native random lanes.
          const yaw = lerp(0, f32(1.570796251296997), nativeUnit(draw()));
          draw(); // InitialModule always consumes a color word.
          const u = nativeUnit(makeShape()), depth = f32(length * nativeUnit(makeShape()));
          const index = i + lane;
          if (index >= count) continue;
          const turns = f32(f32(f32(index * f32(1 / count)) * fullTurn) * inverseTurn);
          const sq = f32(f32(1 - u) + f32(f32(.001) * u)), spread = f32(sq * inverseRoot(sq));
          const sx = f32(spread * cosine(turns)), sy = f32(spread * cosine(f32(turns - .25)));
          const dx = f32(sin * sx), dy = f32(sin * sy), dz = cos, inv = inverseRoot(distanceSquared(dx, dy, dz));
          const [x, y, z] = shapePosition(f32(f32(radius * sx) + f32(f32(dx * inv) * depth)),
            f32(f32(radius * sy) + f32(f32(dy * inv) * depth)), f32(f32(dz * inv) * depth));
          const [vx, vy, vz] = shapePosition(dx, dy, dz), direction = inverseRoot(distanceSquared(vx, vy, vz));
          const speed = lerp(6, 10, salted(word, speedSalt));
          const sign = salted(word, directionSalt) > 0 ? 1 : -1;
          const spin = f32(sign * lerp(f32(5.235987663269043), f32(-5.235987663269043), salted(word, spinSalt)));
          const atom = {x, y, z, vx: f32(f32(vx * direction) * speed), vy: f32(f32(vy * direction) * speed),
            vz: f32(f32(vz * direction) * speed), size, yaw, roll: 0, age: 0, life, spin, color};
          advance(atom, within, gravity);
          births.push(atom);
        }
      }
      const gap = (4 - active.length % 4) % 4;
      const first = gap ? Math.max(0, count - gap) : 0;
      for (let i = 0; i < count; i++) active.push(births[(first + i) % count]);
    }

    function step(tick) {
      if (delay >= dt) {
        delay = f32(delay - dt);
        frames.push(new Float32Array());
        return;
      }
      const advanceBy = f32(dt - delay);
      delay = 0;
      for (const atom of active) advance(atom, dt, frameGravity);
      cull();
      clock = f32(clock + advanceBy);
      // Float32 burst crossings at the original grouped 60 Hz simulation steps.
      const burst = profile.bursts[nextBurst];
      if (burst && burst[0] === tick) {
        birth(burst[1], advanceBy);
        nextBurst++;
      }
      const output = new Float32Array(active.length * stride);
      for (const [i, atom] of active.entries()) {
        const phase = f32(atom.age * ageScale), rgba = nativeColorAtTime(atom.color, phase).map(value => Math.round(value * 255));
        output.set([-atom.x, atom.y, atom.z, f32(atom.size * sizeAt(phase)), 0, atom.yaw, atom.roll, ...rgba], i * stride);
      }
      frames.push(output);
    }

    return {sample(elapsed, fps, emit) {
      const target = nativeFrame(elapsed, fps);
      if (target < 0 || target > lastTick) return;
      while (frames.length <= target) step(frames.length);
      const output = frames[target];
      for (let i = 0; i < output.length; i += stride) {
        emit(output[i], output[i + 1], output[i + 2], output[i + 3], output[i + 4], output[i + 5],
          output[i + 6], output[i + 7], output[i + 8], output[i + 9], output[i + 10]);
      }
    }};
  }

  global.MVStudioMomijiLeavesSimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
