(function (global) {
  "use strict";

  // One common runtime for the original Shuriken ParticleSystems that
  // CustomControl clips start (see core/mv_studio_particle_systems.py).
  //
  // Simulation rules shared with the per-effect native modules in this folder:
  //  * 60 Hz particle updates, two per 30 fps display frame (nativeFrame), the
  //    first one in the clip's activation frame (activeControlFrame).
  //  * Unity's xorshift128 stream (nativeRandom). Four SIMD lanes each own an
  //    "initial" and a "shape" stream seeded with seed + 367 * lane; a birth
  //    group always draws all four lanes (mv-studio-stage-dust-simulation.js).
  //  * InitialModule draw order per birth: particle word, lifetime, size X
  //    (Y, Z when size3D), rotation (Z, X, Y when rotation3D), color.
  //  * Per-particle module randoms come from a fresh stream seeded with the
  //    particle word plus the module salt (velocity, size, color, rotation...).
  //  * Age runs from 0 to 100 at dt * 100 / lifetime per step (reciprocal
  //    refined as on ARM), curves are sampled at age * .01.
  //  * Rate emission carries its fraction across steps; newborns advance by
  //    their fraction of the step. Prewarm replays one maximum lifetime with
  //    .2 s steps while more than 5 s remain, then .02 s steps, and the
  //    remainder runs after the first display frame's full steps.
  //  * The clone root sits at the world origin plus the clip offset; its
  //    systems use their own serialized random seeds.

  const f32 = Math.fround;
  const gravityMagnitude = f32(9.81), ageScale = f32(.01);
  const fixedStep = f32(.02), catchUpStep = f32(.2), clockBias = f32(.0001), birthBias = f32(1e-6);
  const maxElapsed = 1200;
  const salts = {
    speed: 0x96aa4de3, gravity: 0xe2b7c3c3, velocity: 0xe0fbd834, size: 0x8d2c8431, color: 0x591bc05c,
    rotation: 0x6aed452e, rotationSign: 0xff2bb1a4, rotationBySpeed: 0xdec4aea1, startFrame: 0x56b3dbb0,
    frame: 0x13740583, drag: 0xa6790296,
    // Stand-ins: these draws exist in Unity but their salts are not identified yet.
    clamp: 0x2c1b3c6d, row: 0x297a2d39, flipU: 0x5f356495, flipV: 0x2a2f6b71, burst: 0x3c6ef372,
  };
  // level35 MainCamera culling mask (layers 0, 1, 4, 14-17, 19, 26 and 27).
  const mainCameraMask = 0x0C0BC013;
  const lerp = (a, b, t) => f32(a + f32(f32(b - a) * t));
  const byte = value => Math.max(0, Math.min(255, Math.trunc(f32(f32(value * 255) + .5))));
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(finite);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 256;

  function engine() {
    const particles = global.MVStudioStageParticles;
    return particles?.nativeRandom && particles.nativeCurve && particles.nativeInverseLifetime ? particles : null;
  }

  // ---------------------------------------------------------------- curves
  function validKeys(keys) {
    return Array.isArray(keys) && keys.length >= 1 && keys.length <= 64 && keys.every((key, index) =>
      Array.isArray(key) && key.length === 4 && finite(key[0]) && finite(key[1]) &&
      (key[2] === null || finite(key[2])) && (key[3] === null || finite(key[3])) &&
      (!index || key[0] >= keys[index - 1][0]));
  }

  function validCurve(curve) {
    if (!curve || ![0, 1, 2, 3].includes(curve.mode) || !finite(curve.scalar) || !finite(curve.min)) return false;
    if ((curve.mode === 1 || curve.mode === 2) && !validKeys(curve.maxKeys)) return false;
    return curve.mode !== 2 || validKeys(curve.minKeys);
  }

  function compileCurve(curve, native) {
    const scalar = f32(curve.scalar), low = f32(curve.min);
    if (curve.mode === 0) return {sample: () => scalar, constant: true, max: scalar};
    if (curve.mode === 3) return {sample: (t, weight) => lerp(low, scalar, weight), max: Math.max(low, scalar)};
    const keys = rows => rows.map(([time, value, incoming, outgoing]) =>
      [f32(time), f32(value), incoming === null ? null : f32(incoming), outgoing === null ? null : f32(outgoing)]);
    const upper = native.nativeCurve(keys(curve.maxKeys));
    const peak = rows => Math.max(...rows.map(row => row[1]));
    if (curve.mode === 1) return {sample: t => f32(upper(t) * scalar), max: scalar * peak(curve.maxKeys)};
    const lower = native.nativeCurve(keys(curve.minKeys));
    return {sample: (t, weight) => f32(lerp(lower(t), upper(t), weight) * scalar),
      max: scalar * Math.max(peak(curve.maxKeys), peak(curve.minKeys))};
  }

  // ---------------------------------------------------------------- colors
  function validGradient(value) {
    const keys = (rows, width) => Array.isArray(rows) && rows.length >= 1 && rows.length <= 8 && rows.every((row, index) =>
      vector(row, width) && Number.isInteger(row[0]) && row[0] >= 0 && row[0] <= 65535 &&
      (!index || row[0] >= rows[index - 1][0]));
    return (value?.mode === 0 || value?.mode === 1) && keys(value.rgb, 4) && keys(value.alpha, 2);
  }

  function validColor(value) {
    if (!value || ![0, 1, 2, 3, 4].includes(value.mode)) return false;
    if ((value.mode === 0 || value.mode === 2) && !vector(value.max, 4)) return false;
    if (value.mode === 2 && !vector(value.min, 4)) return false;
    if ([1, 3, 4].includes(value.mode) && !validGradient(value.maxGradient)) return false;
    return value.mode !== 3 || validGradient(value.minGradient);
  }

  // Float gradient for the InitialModule start color (Color32 output).
  function gradientAt(gradient, time) {
    const stamp = time * 65535;
    const channel = (rows, index) => {
      if (gradient.mode === 1) return (rows.find(row => row[0] >= stamp) || rows[rows.length - 1])[index];
      if (stamp <= rows[0][0]) return rows[0][index];
      for (let i = 1; i < rows.length; i++) {
        const before = rows[i - 1], after = rows[i];
        if (stamp > after[0]) continue;
        const span = after[0] - before[0];
        return span > 0 ? before[index] + (after[index] - before[index]) * (stamp - before[0]) / span : after[index];
      }
      return rows[rows.length - 1][index];
    };
    return [channel(gradient.rgb, 1), channel(gradient.rgb, 2), channel(gradient.rgb, 3), channel(gradient.alpha, 1)];
  }

  // Over-lifetime gradients use Unity's packed byte gradient (nativeColorAtTime).
  function packed(gradient, native) {
    if (gradient.mode === 1) return null;
    return native.nativePackedGradient({rgb: gradient.rgb, alpha: gradient.alpha}, [255, 255, 255, 255]).keys;
  }

  function packedAt(keys, gradient, time) {
    if (!keys) return gradientAt(gradient, time).map(byte);
    const next = keys.findIndex(row => row[0] > time);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const blend = left === right ? 0 : Math.trunc(f32(f32(f32(time - left[0]) *
      f32(1 / f32(right[0] - left[0]))) * 255));
    return [0, 1, 2, 3].map(index => left[index + 1] + ((128 + blend * (right[index + 1] - left[index + 1])) >> 8));
  }

  function multiply(start, bytes) {
    return start.map((value, index) => Math.floor((value * bytes[index] + 127) / 255));
  }

  // ---------------------------------------------------------------- transforms (Unity space)
  function quatRotate([x, y, z, w], [vx, vy, vz]) {
    const tx = 2 * (y * vz - z * vy), ty = 2 * (z * vx - x * vz), tz = 2 * (x * vy - y * vx);
    return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)];
  }

  function quatMultiply([ax, ay, az, aw], [bx, by, bz, bw]) {
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
      aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz];
  }

  const conjugate = ([x, y, z, w]) => [-x, -y, -z, w];

  function eulerQuaternion([x, y, z]) {
    // Unity's Quaternion.Euler applies Z, then X, then Y.
    const half = Math.PI / 360;
    const axis = (angle, index) => {
      const q = [0, 0, 0, Math.cos(angle * half)];
      q[index] = Math.sin(angle * half);
      return q;
    };
    return quatMultiply(quatMultiply(axis(y, 1), axis(x, 0)), axis(z, 2));
  }

  // World pose of every prefab node: the clone root keeps its own local pose
  // and is moved by the clip offset (CustomControlClip.ConnectPlayablesToMixer).
  function nodePoses(nodes, offset) {
    const poses = [];
    for (const node of nodes) {
      const parent = node.parent === null ? null : poses[node.parent];
      let position = node.position, rotation = node.rotation, scale = node.scale;
      if (parent) {
        const scaled = node.position.map((value, i) => value * parent.scale[i]);
        position = quatRotate(parent.rotation, scaled).map((value, i) => value + parent.position[i]);
        rotation = quatMultiply(parent.rotation, node.rotation);
        scale = node.scale.map((value, i) => value * parent.scale[i]);
      } else {
        position = position.map((value, i) => value + offset[i]);
      }
      poses.push({position, rotation, scale, local: node.scale});
    }
    return poses;
  }

  // ---------------------------------------------------------------- validation
  function validSimulation(system) {
    const {main, emission, shape, renderer} = system || {};
    if (!main || !emission || !renderer) return false;
    if (!finite(main.duration) || main.duration <= 0 || !Number.isInteger(main.maxParticles) ||
        main.maxParticles < 0 || main.maxParticles > 4096 || !Number.isInteger(main.randomSeed) ||
        !["startDelay", "lifetime", "speed", "size", "rotation", "gravity"].every(name => validCurve(main[name])) ||
        (main.size3D && !(validCurve(main.sizeY) && validCurve(main.sizeZ))) ||
        (main.rotation3D && !(validCurve(main.rotationX) && validCurve(main.rotationY))) ||
        !validColor(main.color) || !finite(main.simulationSpeed) || main.simulationSpeed <= 0) return false;
    if (!validCurve(emission.rate) || !Array.isArray(emission.bursts) || emission.bursts.length > 32 ||
        !emission.bursts.every(burst => finite(burst?.time) && validCurve(burst.count) &&
          Number.isInteger(burst.cycles) && finite(burst.interval) && finite(burst.probability))) return false;
    if (shape && !(Number.isInteger(shape.type) && vector(shape.position, 3) && vector(shape.rotation, 3) &&
        vector(shape.scale, 3) && finite(shape.radius) && finite(shape.arc) && finite(shape.angle))) return false;
    const curves = (value, names) => !value || names.every(name => validCurve(value[name]));
    if (!curves(system.velocity, ["x", "y", "z"]) ||
        !curves(system.velocity?.orbital, ["orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY",
          "orbitalOffsetZ", "radial"]) ||
        (system.velocity?.speedModifier && !validCurve(system.velocity.speedModifier))) return false;
    if (system.clamp && (!(system.clamp.separateAxes ? curves(system.clamp, ["x", "y", "z"]) :
      validCurve(system.clamp.magnitude)) || (system.clamp.drag && !validCurve(system.clamp.drag)))) return false;
    for (const name of ["size", "rotation"]) {
      const value = system[name];
      if (value && !(value.separateAxes ? curves(value, ["x", "y", "z"]) : validCurve(value.curve))) return false;
    }
    if (system.color && !validColor(system.color)) return false;
    const uv = system.uv;
    if (uv && !(vector(uv.tiles, 2) && uv.tiles.every(value => Number.isInteger(value) && value >= 1 && value <= 256) &&
        validCurve(uv.frame) && validCurve(uv.startFrame) && finite(uv.cycles))) return false;
    if (system.rotationBySpeed && !(validCurve(system.rotationBySpeed.curve) && vector(system.rotationBySpeed.range, 2))) {
      return false;
    }
    return [0, 1, 2, 3].includes(renderer.mode) && finite(renderer.maxParticleSize) &&
      finite(renderer.minParticleSize) && vector(renderer.pivot, 3) && vector(renderer.flip, 3);
  }

  function validSystem(system, textures) {
    const material = system?.material;
    return validSimulation(system) && !!material && vector(material.tint, 4) && vector(material.st, 4) && vector(material.blend, 2) && vector(material.stencil, 4) &&
      (material.texture === null || (Number.isInteger(material.texture) && !!textures[material.texture])) &&
      Number.isInteger(system.node) && Number.isInteger(system.layer);
  }

  function validDescriptor(source) {
    const {textures, templates, cues} = source || {};
    if (source?.schema !== 1 || !Array.isArray(textures) || !Array.isArray(templates) || !Array.isArray(cues) ||
        cues.length > 512 || templates.length > 192) return false;
    if (!textures.every(texture => Array.isArray(texture?.levels) && texture.levels.length >= 1 &&
      texture.levels.every((level, index) => typeof level?.png === "string" &&
        level.width === Math.max(1, texture.levels[0].width >> index) &&
        level.height === Math.max(1, texture.levels[0].height >> index)))) return false;
    return templates.every(template => Array.isArray(template?.nodes) && Array.isArray(template.systems) &&
      template.nodes.every((node, index) => vector(node?.position, 3) && vector(node.rotation, 4) &&
        vector(node.scale, 3) && (node.parent === null || (Number.isInteger(node.parent) && node.parent < index))) &&
      template.systems.every(system => validSystem(system, textures) && template.nodes[system.node])) &&
      cues.every(cue => id(cue?.trackId) && id(cue.eventId) && Number.isInteger(cue.template) &&
        !!templates[cue.template] && vector(cue.offset, 3) && typeof cue.quality === "string");
  }

  // ---------------------------------------------------------------- shapes
  // Unity ShapeModule sampling as the native modules reproduce it: heading in
  // turns through the native sine polynomial, area radius sqrt((1-u) + .001u)
  // at full thickness, cone directions normalize(sin(a) * xy, cos(a)) and a
  // cone-volume depth draw (mv-studio-sparks-a-*-simulation.js); BurstSpread
  // replaces the heading draw with slot / (count - 1) (sparks-b).
  function makeShape(shape, native) {
    if (!shape) return {draw: () => ({position: [0, 0, 0], direction: [0, 0, 1]})};
    const rotation = eulerQuaternion(shape.rotation), {scale, position: origin, type} = shape;
    const radius = f32(shape.radius), thickness = f32(shape.radiusThickness ?? 1);
    const arcTurns = f32(f32(shape.arc * f32(Math.PI / 180)) * .15915493667125702);
    const cone = f32(shape.angle * Math.PI / 180), coneX = f32(Math.sin(cone)), coneZ = f32(Math.cos(cone));
    const inner = Math.max(f32(.001), f32(f32(1 - thickness) * f32(1 - thickness)));
    const cos = native.nativeCosine;
    function heading(draw, slot, count) {
      const fraction = shape.arcMode === 3 ? f32(slot * f32(1 / Math.max(1, count - 1))) : native.nativeUnit(draw());
      return f32(arcTurns * fraction);
    }
    const areaRadius = draw => {
      const weight = native.nativeUnit(draw());
      return f32(Math.sqrt(f32(f32(1 - weight) + f32(inner * weight))));
    };
    function local(draw, slot, count) {
      const unit = () => native.nativeUnit(draw());
      switch (type) {
        case 5: case 15: case 16: {
          const box = [f32(f32(unit() - .5) * scale[0]), f32(f32(unit() - .5) * scale[1]), f32(f32(unit() - .5) * scale[2])];
          return {position: box, direction: [0, 0, 1], scaled: true};
        }
        case 0: case 1: case 2: case 3: {
          const turns = heading(draw, slot, count);
          const point = type < 2 ? native.nativeSpherePosition(turns, unit(), type === 1 ? 0 : unit(), radius, scale) :
            native.nativeHemispherePosition(turns, unit(), type === 3 ? 0 : unit(), radius, scale);
          const length = Math.hypot(...point);
          return {position: point, direction: length > 0 ? point.map(value => value / length) : [0, 0, 1], scaled: true};
        }
        case 10: case 11: {
          const turns = heading(draw, slot, count), r = type === 11 ? 1 : areaRadius(draw);
          const x = f32(cos(turns) * r), y = f32(cos(f32(turns - .25)) * r);
          const length = Math.hypot(x, y) || 1;
          return {position: [f32(x * radius), f32(y * radius), 0], direction: [x / length, y / length, 0]};
        }
        case 4: case 7: case 8: case 9: {
          const turns = heading(draw, slot, count), r = type === 7 || type === 9 ? 1 : areaRadius(draw);
          const x = f32(cos(turns) * r), y = f32(cos(f32(turns - .25)) * r);
          const localX = f32(coneX * x), localY = f32(coneX * y);
          const inverse = f32(1 / Math.sqrt(f32(f32(localX * localX) + f32(f32(localY * localY) + f32(coneZ * coneZ)))));
          const direction = [f32(localX * inverse), f32(localY * inverse), f32(coneZ * inverse)];
          const base = [f32(x * radius), f32(y * radius), 0];
          if (type >= 8) {
            const depth = f32(shape.length * unit());
            return {position: base.map((value, i) => f32(value + f32(direction[i] * depth))), direction};
          }
          return {position: base, direction};
        }
        case 12: {
          return {position: [f32(f32(f32(unit() * 2) - 1) * radius), 0, 0], direction: [0, 1, 0]};
        }
        case 18: {
          return {position: [f32(f32(unit() - .5) * scale[0]), f32(f32(unit() - .5) * scale[1]), 0], direction: [0, 0, 1],
            scaled: true};
        }
        default:
          return {position: [0, 0, 0], direction: [0, 0, 1]};
      }
    }
    return {draw(draw, slot = 0, count = 1) {
      const sample = local(draw, slot, count);
      let {position, direction} = sample;
      if (!sample.scaled) position = position.map((value, i) => value * scale[i]);
      if (shape.randomDirection > 0 || shape.sphericalDirection > 0) {
        const turns = native.nativeUnit(draw()), polar = native.nativeUnit(draw());
        const random = native.nativeSpherePosition(turns, polar, 0, 1, [1, 1, 1]);
        const length = Math.hypot(...position) || 1;
        const outward = position.map(value => value / length);
        direction = direction.map((value, i) => value + (random[i] - value) * shape.randomDirection);
        direction = direction.map((value, i) => value + (outward[i] - value) * shape.sphericalDirection);
        const norm = Math.hypot(...direction) || 1;
        direction = direction.map(value => value / norm);
      }
      if (shape.randomPosition > 0) {
        position = position.map(value => value + (native.nativeUnit(draw()) * 2 - 1) * shape.randomPosition);
      }
      position = quatRotate(rotation, position).map((value, i) => f32(value + origin[i]));
      return {position, direction: quatRotate(rotation, direction)};
    }};
  }

  // ---------------------------------------------------------------- simulation
  function maxCurve(curve) {
    return curve.mode === 0 ? curve.scalar : curve.mode === 3 ? Math.max(curve.min, curve.scalar) :
      Math.abs(curve.scalar) * Math.max(...curve.maxKeys.map(key => key[1]), ...(curve.minKeys || []).map(key => key[1]));
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

  // system: one normalized ParticleSystem; seed: its effective random seed;
  // gravity: the world down axis in the emitter's simulation space.
  function create(system, seed, {gravity = [0, -1, 0], worldVelocity = null} = {}) {
    const native = engine();
    if (!native || !validSimulation(system) || !Number.isInteger(seed)) return null;
    const {nativeRandom, nativeUnit, nativeInverseLifetime, nativeStep, nativeStepRate} = native;
    const {main, emission} = system;
    const cycle = f32(main.duration), speedScale = f32(main.simulationSpeed);
    const compile = curve => compileCurve(curve, native);
    const lifetime = compile(main.lifetime), startSpeed = compile(main.speed), gravityModifier = compile(main.gravity);
    const sizes = [compile(main.size), ...(main.size3D ? [compile(main.sizeY), compile(main.sizeZ)] : [])];
    const rotations = main.rotation3D ? [compile(main.rotation), compile(main.rotationX), compile(main.rotationY)] :
      [compile(main.rotation)];
    const rate = compile(emission.rate);
    const bursts = emission.bursts.map(burst => ({...burst, count: compile(burst.count)}));
    const shape = makeShape(system.shape, native);
    const velocity = system.velocity && ["x", "y", "z"].map(axis => compile(system.velocity[axis]));
    const orbital = system.velocity?.orbital && ["orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY",
      "orbitalOffsetZ", "radial"].map(name => compile(system.velocity.orbital[name]));
    const speedModifier = system.velocity?.speedModifier && compile(system.velocity.speedModifier);
    const clamp = system.clamp && (system.clamp.separateAxes ? ["x", "y", "z"].map(axis => compile(system.clamp[axis])) :
      compile(system.clamp.magnitude));
    const drag = system.clamp?.drag && compile(system.clamp.drag);
    const sizeOverLife = system.size && (system.size.separateAxes ? ["x", "y", "z"].map(axis => compile(system.size[axis])) :
      [compile(system.size.curve)]);
    const spin = system.rotation && compile(system.rotation.separateAxes ? system.rotation.z : system.rotation.curve);
    const spinBySpeed = system.rotationBySpeed && compile(system.rotationBySpeed.curve);
    const uv = system.uv && {...system.uv, frame: compile(system.uv.frame), startFrame: compile(system.uv.startFrame)};
    const color = system.color;
    const colorKeys = color && [1, 3, 4].includes(color.mode) && packed(color.maxGradient, native);
    const colorKeysMin = color && color.mode === 3 && packed(color.minGradient, native);
    const g = gravity.map(f32), velocityToLocal = worldVelocity;
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const lanes = Array.from({length: 4}, (_, lane) => {
      const word = (seed + 367 * lane) >>> 0;
      return {initial: nativeRandom(word), shape: nativeRandom(word)};
    });
    const groups = [];

    function startColor(unit, systemTime) {
      const value = main.color;
      switch (value.mode) {
        case 0: return value.max.map(byte);
        case 1: return gradientAt(value.maxGradient, systemTime).map(byte);
        case 2: return value.min.map((low, i) => byte(lerp(low, value.max[i], unit)));
        case 3: {
          const low = gradientAt(value.minGradient, systemTime), high = gradientAt(value.maxGradient, systemTime);
          return low.map((entry, i) => byte(lerp(entry, high[i], unit)));
        }
        default: return gradientAt(value.maxGradient, unit).map(byte);
      }
    }

    function birth({initial}, systemTime) {
      const word = initial();
      const life = Math.max(f32(1e-4), lifetime.sample(systemTime, nativeUnit(initial())));
      const size = sizes.map(curve => curve.sample(systemTime, nativeUnit(initial())));
      const angles = rotations.map(curve => curve.sample(systemTime, nativeUnit(initial())));
      const rgba = startColor(nativeUnit(initial()), systemTime);
      const speed = startSpeed.sample(systemTime, salted(word, salts.speed));
      const stream = nativeRandom((word + salts.velocity) >>> 0);
      // Linear x, y, z, then (stand-in order) orbital x, y, z, offset x, y, z, radial and speed modifier.
      const weights = Array.from({length: orbital || speedModifier ? 11 : 3}, () => nativeUnit(stream()));
      const threshold = f32(main.randomizeRotationDirection * .5);
      return {
        word, life: nativeInverseLifetime(life), size, roll: angles[0], rgba, speed, weights,
        gravity: gravityModifier.sample(systemTime, salted(word, salts.gravity)),
        sizeWeight: salted(word, salts.size), colorWeight: salted(word, salts.color),
        spinWeight: salted(word, salts.rotation), spinSign: salted(word, salts.rotationSign) > threshold ? 1 : -1,
        speedSpinWeight: spinBySpeed ? salted(word, salts.rotationBySpeed) : 0,
        clampWeight: clamp ? salted(word, salts.clamp) : 0, dragWeight: drag ? salted(word, salts.drag) : 0,
        frameStart: uv ? salted(word, salts.startFrame) : 0, frameWeight: uv ? salted(word, salts.frame) : 0,
        row: uv?.randomRow ? salted(word, salts.row) : 0,
        flipU: salted(word, salts.flipU) < Math.max(system.renderer.flip[0], uv?.flipU || 0),
        flipV: salted(word, salts.flipV) < Math.max(system.renderer.flip[1], uv?.flipV || 0),
      };
    }

    function advance(atom, dt) {
      const {source} = atom, phase = f32(atom.age * ageScale);
      if (source.gravity) {
        const force = f32(f32(gravityMagnitude * dt) * source.gravity);
        atom.vx = f32(atom.vx + f32(force * g[0]));
        atom.vy = f32(atom.vy + f32(force * g[1]));
        atom.vz = f32(atom.vz + f32(force * g[2]));
      }
      let ex = 0, ey = 0, ez = 0;
      if (velocity) {
        ex = velocity[0].sample(phase, source.weights[0]);
        ey = velocity[1].sample(phase, source.weights[1]);
        ez = velocity[2].sample(phase, source.weights[2]);
        if (velocityToLocal) [ex, ey, ez] = velocityToLocal([ex, ey, ez]).map(f32);
      }
      const modifier = speedModifier ? speedModifier.sample(phase, source.weights[10]) : 1;
      let mx = f32(atom.vx + ex), my = f32(atom.vy + ey), mz = f32(atom.vz + ez);
      if (modifier !== 1) {
        mx = f32(mx * modifier);
        my = f32(my * modifier);
        mz = f32(mz * modifier);
      }
      if (clamp) {
        // Dampen is per 1/30 s: 1 - (1 - dampen)^(dt * 30) (mv-studio-moving-burst-simulation.js).
        const dampen = f32(1 - f32(Math.pow(f32(1 - f32(system.clamp.dampen)), f32(dt * 30))));
        if (Array.isArray(clamp)) {
          const limits = clamp.map(curve => Math.abs(curve.sample(phase, source.clampWeight)));
          const fix = (moving, extra, limit, key) => {
            if (Math.abs(moving) <= limit) return moving;
            atom[key] = f32(f32(Math.sign(moving) * lerp(Math.abs(moving), limit, dampen)) - extra);
            return f32(atom[key] + extra);
          };
          mx = fix(mx, ex, limits[0], "vx");
          my = fix(my, ey, limits[1], "vy");
          mz = fix(mz, ez, limits[2], "vz");
        } else {
          const limit = clamp.sample(phase, source.clampWeight);
          const speed = f32(Math.sqrt(f32(f32(mx * mx) + f32(f32(my * my) + f32(mz * mz)))));
          if (speed > limit && speed > 0) {
            const scale = f32(lerp(speed, limit, dampen) / speed);
            atom.vx = f32(f32(mx * scale) - ex);
            atom.vy = f32(f32(my * scale) - ey);
            atom.vz = f32(f32(mz * scale) - ez);
            mx = f32(atom.vx + ex);
            my = f32(atom.vy + ey);
            mz = f32(atom.vz + ez);
          }
        }
        if (drag) {
          // Speed loses dt * speed^2 * drag * area, area = pi * (size / 2)^2.
          const coefficient = drag.sample(phase, source.dragWeight);
          const width = sizeOverLife ? f32(source.size[0] * Math.max(0, sizeOverLife[0].sample(phase, source.sizeWeight))) :
            source.size[0];
          const half = f32(width * .5), area = f32(half * f32(half * f32(Math.PI)));
          const square = f32(f32(mx * mx) + f32(f32(my * my) + f32(mz * mz))), speed = f32(Math.sqrt(square));
          if (speed > f32(1e-15)) {
            const scale = f32(Math.max(0, f32(speed - f32(dt * f32(square * f32(coefficient * area))))) / speed);
            atom.vx = f32(f32(mx * scale) - ex);
            atom.vy = f32(f32(my * scale) - ey);
            atom.vz = f32(f32(mz * scale) - ez);
            mx = f32(atom.vx + ex);
            my = f32(atom.vy + ey);
            mz = f32(atom.vz + ez);
          }
        }
      }
      atom.mx = mx;
      atom.my = my;
      atom.mz = mz;
      if (orbital && dt > birthBias) {
        // Rotate about the orbital offset point, then push along the rotated
        // radius; the displacement joins the linear motion of this step.
        const value = (index, weight) => orbital[index].sample(phase, source.weights[weight]);
        const motion = f32(dt * modifier);
        const center = [value(3, 6), value(4, 7), value(5, 8)];
        let relative = [f32(atom.x - center[0]), f32(atom.y - center[1]), f32(atom.z - center[2])];
        const turns = [0, 1, 2].map(axis => f32(f32(motion * value(axis, axis + 3)) * .15915493667125702));
        const turn = (vector, axis, angle) => {
          if (!angle) return vector;
          const c = native.nativeCosine(angle), s = native.nativeCosine(f32(angle - .25));
          const [a, b] = axis === 0 ? [1, 2] : axis === 1 ? [2, 0] : [0, 1];
          const next = [...vector];
          next[a] = f32(f32(c * vector[a]) - f32(s * vector[b]));
          next[b] = f32(f32(s * vector[a]) + f32(c * vector[b]));
          return next;
        };
        const rotated = turn(turn(turn(relative, 0, turns[0]), 1, turns[1]), 2, turns[2]);
        const push = f32(motion * value(6, 9)), length = Math.hypot(...rotated);
        const moved = length > 0 ? rotated.map(axis => f32(axis + f32(f32(axis / length) * push))) : rotated;
        atom.x = f32(atom.x + f32(moved[0] - relative[0]));
        atom.y = f32(atom.y + f32(moved[1] - relative[1]));
        atom.z = f32(atom.z + f32(moved[2] - relative[2]));
      }
      atom.x = f32(atom.x + f32(mx * dt));
      atom.y = f32(atom.y + f32(my * dt));
      atom.z = f32(atom.z + f32(mz * dt));
      if (spin || spinBySpeed) {
        let angular = spin ? spin.sample(phase, source.spinWeight) : 0;
        if (spinBySpeed) {
          const [low, high] = system.rotationBySpeed.range;
          const speed = Math.hypot(mx, my, mz);
          const t = high > low ? Math.min(1, Math.max(0, (speed - low) / (high - low))) : 0;
          angular += spinBySpeed.sample(t, source.speedSpinWeight);
        }
        atom.roll = f32(atom.roll + f32(f32(angular * source.spinSign) * dt));
      }
      atom.age = f32(atom.age + f32(f32(dt * 100) * source.life));
    }

    function born(state, count, within, systemTime) {
      const sources = [];
      while (sources.length < count) {
        if (state.group === groups.length) {
          // Every lane of a group draws its InitialModule and ShapeModule words.
          const base = sources.length;
          const group = lanes.map(lane => birth(lane, systemTime));
          group.forEach((source, lane) => {
            const {position, direction} = shape.draw(lanes[lane].shape, base + lane, count);
            source.position = position;
            source.velocity = direction.map(value => f32(value * source.speed));
          });
          groups.push(group);
        }
        sources.push(...groups[state.group++].slice(0, count - sources.length));
      }
      const births = sources.map((source, index) => {
        const atom = {source, x: source.position[0], y: source.position[1], z: source.position[2],
          vx: source.velocity[0], vy: source.velocity[1], vz: source.velocity[2], mx: 0, my: 0, mz: 0,
          age: 0, roll: source.roll};
        advance(atom, within(index));
        return atom;
      });
      // Native SoA storage fills the existing trailing SIMD lanes from the new batch tail.
      const {active} = state, remaining = (4 - active.length % 4) % 4;
      const pivot = remaining ? Math.max(0, count - remaining) : 0;
      for (let i = 0; i < count; i++) active.push(births[(pivot + i) % count]);
    }

    // Bursts whose loop time falls in [previous, end) on the unwrapped clock.
    function burstsBetween(state, previous, end) {
      const found = [];
      for (let index = 0; index < bursts.length; index++) {
        const burst = bursts[index];
        const repeats = burst.cycles > 0 ? burst.cycles : Math.ceil(cycle / Math.max(burst.interval, 1e-3));
        for (let k = 0; k < Math.min(repeats, 100000); k++) {
          const at = f32(burst.time + k * burst.interval);
          if (at >= cycle) break;
          for (const base of main.looping ? [0, cycle] : [0]) {
            const time = at + base;
            if (time < previous || time >= end) continue;
            const loop = state.loop + (base ? 1 : 0);
            const draw = salt => nativeUnit(nativeRandom((seed + salts.burst + salt + loop * 977 + index * 131 + k) >>> 0)());
            if (burst.probability < 1 && draw(0) > burst.probability) continue;
            const count = Math.round(burst.count.sample(f32(at / cycle), draw(1)));
            if (count > 0) found.push({count, elapsed: f32(end - time)});
          }
        }
      }
      return found;
    }

    function step(state, rawDt) {
      let dt = f32(rawDt * speedScale);
      const {active} = state;
      for (const atom of active) advance(atom, dt);
      cull(active);
      if (state.delay > 0) {
        state.delay = f32(state.delay - dt);
        if (state.delay > 0) return;
        dt = f32(-state.delay);
        state.delay = 0;
      }
      if (state.stopped) return;
      const previous = state.clock, next = f32(previous + dt);
      const wrapped = main.looping && next > cycle;
      const clock = wrapped ? f32(next - cycle) : next;
      const end = main.looping ? next : Math.min(next, cycle);
      const systemTime = f32(previous / cycle);
      const perSecond = rate.sample(systemTime, nativeUnit(nativeRandom((seed + state.loop * 7919 + Math.trunc(previous * 1e4)) >>> 0)()));
      const amount = wrapped ? f32(f32(f32(cycle - previous) * perSecond) + f32(clock * perSecond)) :
        f32(f32(Math.max(0, f32(end - previous))) * perSecond);
      const total = f32(amount + state.carry), requested = Math.max(0, Math.trunc(total));
      state.carry = total > 0 ? f32(total - requested) : 0;
      const pulses = burstsBetween(state, previous, next);
      state.clock = clock;
      if (wrapped) state.loop++;
      if (!main.looping && next >= cycle) state.stopped = true;
      const room = Math.max(0, main.maxParticles - active.length);
      const regular = Math.min(requested, room);
      if (regular > 0) {
        const inverse = amount < clockBias ? 1 : f32(1 / amount);
        born(state, regular, index => f32(dt * Math.min(1, Math.max(birthBias, f32(f32(index + state.carry) * inverse)))),
          systemTime);
      }
      for (const {count, elapsed} of pulses) {
        const allowed = Math.min(count, Math.max(0, main.maxParticles - active.length));
        if (allowed > 0) born(state, allowed, () => Math.max(birthBias, Math.min(dt, elapsed)), systemTime);
      }
    }

    const clone = state => ({...state, active: state.active.map(atom => ({...atom}))});
    const delay = main.prewarm && main.looping ? 0 : compileCurve(main.startDelay, native).sample(0, nativeUnit(nativeRandom(seed)()));
    let warm = {frame: 0, clock: 0, carry: 0, loop: 0, group: 0, delay: f32(delay), stopped: false, active: []};
    let remainder = 0;
    if (main.prewarm && main.looping) {
      // The bounds scan starts one maximum lifetime before the loop end and
      // feeds its rate carry into the actual prewarm.
      const horizon = f32(Math.max(f32(1e-3), maxCurve(main.lifetime)));
      const start = f32(f32(Math.ceil(f32(horizon / cycle)) * cycle) - horizon);
      let time = start, phase = f32(start % cycle), carry = 0;
      const perSecond = rate.sample(0, .5);
      while (f32(time + clockBias) < f32(start + horizon)) {
        time = f32(time + fixedStep);
        const next = f32(time % cycle);
        const amount = next < phase ? f32(f32(f32(cycle - phase) * perSecond) + f32(next * perSecond)) :
          f32(f32(next - phase) * perSecond);
        const combined = f32(amount + carry);
        carry = f32(combined - Math.trunc(combined));
        phase = next;
      }
      warm = {...warm, clock: f32(start % cycle), carry: perSecond > 0 ? f32(f32(1 - carry) + clockBias) : 0};
      remainder = horizon;
      for (let dt = remainder > 5 ? catchUpStep : fixedStep; remainder >= dt; dt = remainder > 5 ? catchUpStep : fixedStep) {
        step(warm, dt);
        remainder = f32(remainder - dt);
      }
    }
    const layouts = new Map(), checkpointInterval = 2 * nativeStepRate;

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      let residue = f32(f32(1 / fps) + remainder);
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const entry = {state: clone(warm), checkpoints: [warm], grouped, residue: main.prewarm && main.looping ? residue : 0};
      layouts.set(fps, entry);
      return entry;
    }

    return {
      // frames: display frames since activation (1 in the activation frame).
      sample(frames, fps) {
        if (!Number.isInteger(frames) || frames < 0 || (fps !== 30 && fps !== 60) || frames / fps > maxElapsed) return [];
        const target = frames * (nativeStepRate / fps);
        const entry = layouts.get(fps) || layout(fps);
        const {checkpoints, grouped, residue} = entry;
        const saved = Math.min(checkpoints.length - 1, Math.floor(target / checkpointInterval));
        if (target < entry.state.frame || checkpoints[saved].frame > entry.state.frame) entry.state = clone(checkpoints[saved]);
        const {state} = entry;
        while (state.frame < target) {
          step(state, nativeStep);
          state.frame++;
          if (state.frame === grouped && residue >= birthBias) step(state, residue);
          if (state.frame === checkpoints.length * checkpointInterval) checkpoints.push(clone(state));
        }
        return state.active;
      },
      describe(atom) {
        const {source} = atom, phase = f32(atom.age * ageScale);
        let size = source.size.length === 3 ? source.size : [source.size[0], source.size[0], source.size[0]];
        if (sizeOverLife) {
          const scales = sizeOverLife.map(curve => Math.max(0, curve.sample(phase, source.sizeWeight)));
          size = size.map((value, i) => f32(value * scales[sizeOverLife.length === 3 ? i : 0]));
        }
        let rgba = source.rgba;
        if (color) {
          const weight = Math.trunc(f32(source.colorWeight * 255));
          let over;
          switch (color.mode) {
            case 0: over = color.max.map(byte); break;
            case 1: over = packedAt(colorKeys, color.maxGradient, phase); break;
            case 2: over = color.min.map((low, i) => byte(lerp(low, color.max[i], source.colorWeight))); break;
            case 3: {
              const low = packedAt(colorKeysMin, color.minGradient, phase), high = packedAt(colorKeys, color.maxGradient, phase);
              over = low.map((value, i) => value + ((128 + weight * (high[i] - value)) >> 8));
              break;
            }
            default: over = packedAt(colorKeys, color.maxGradient, source.colorWeight);
          }
          rgba = multiply(rgba, over);
        }
        let column = 0, row = 0;
        if (uv) {
          const [columns, rows] = uv.tiles;
          const frames = uv.animation === 0 ? columns * rows : columns;
          const value = uv.startFrame.sample(phase, source.frameStart) +
            uv.frame.sample(f32(f32(phase * uv.cycles) % 1), source.frameWeight);
          const index = value >= 0 && value <= 1 ? Math.min(frames - 1, Math.floor(value * frames)) :
            Math.floor((value - Math.floor(value)) * frames);
          if (uv.animation === 0) {
            column = index % columns;
            row = Math.floor(index / columns);
          } else {
            column = index;
            row = uv.randomRow ? Math.min(rows - 1, Math.floor(source.row * rows)) : Math.min(rows - 1, Math.max(0, uv.rowIndex));
          }
        }
        return {position: [atom.x, atom.y, atom.z], velocity: [atom.mx, atom.my, atom.mz], size, roll: atom.roll, rgba,
          column, row, flipU: source.flipU, flipV: source.flipV, age: atom.age};
      },
    };
  }

  // Native activation timing of a PrefabControl clone (mv-studio-stage-particles.js
  // activeControlFrame) without its single-prefab limits: weight, easing and
  // time scale do not change when OnBehaviourPlay activates the clone.
  const timelineTick = time => Math.trunc(time / 1e-12 + .5);

  function activeFrames(event, time, fps) {
    if (!event || !finite(event.start) || !finite(event.duration) || event.duration <= 0) return 0;
    const start = timelineTick(event.start), current = timelineTick(time);
    if (current < start || current >= timelineTick(event.start + event.duration)) return 0;
    const first = Math.ceil(event.start * fps);
    const activated = timelineTick((first - 1) / fps) === start ? first - 1 : first;
    return Math.max(0, Math.floor(time * fps + 1e-9) - activated + 1);
  }

  // ---------------------------------------------------------------- rendering
  const vertexShader = `
    attribute vec3 particleCenter;
    attribute vec3 particleSize;
    attribute vec4 particleColor;
    attribute vec4 particleFrame;
    uniform vec4 uTiles;
    uniform vec4 uMainST;
    uniform vec2 uSizeLimit;
    uniform float uPlaneScale;
    uniform vec3 uAxisX;
    uniform vec3 uAxisY;
    uniform vec2 uPivot;
    #ifdef STRETCHED
    attribute vec3 particleVelocity;
    uniform vec2 uStretch;
    #endif
    varying vec2 vMainUV;
    varying vec4 vColor;
    void main() {
      vec4 center = modelViewMatrix * vec4(particleCenter, 1.0);
      bool orthographic = projectionMatrix[3][3] == 1.0;
      float depth = orthographic ? 1.0 : -center.z;
      float viewWidth = 2.0 * depth / abs(projectionMatrix[0][0]);
      // Horizontal billboards scale the quad and its size cap by sqrt(1/2)
      // (mv-studio-finale-floor.js planeScale); other modes use 1.
      vec2 size = particleSize.xy * uPlaneScale;
      vec2 sizeLimit = uSizeLimit * uPlaneScale;
      vec2 corner = position.xy;
      vec4 point = center;
      #ifdef STRETCHED
      // Head at the particle, tail behind it along the velocity
      // (mv-studio-moving-companions.js velocityBillboards).
      float width = size.x;
      if (depth >= 0.0) width = min(width, sizeLimit.y * viewWidth);
      if (sizeLimit.x > 0.0 && depth >= 0.0) width = max(width, sizeLimit.x * viewWidth);
      vec3 movement = mat3(modelViewMatrix) * particleVelocity;
      float squared = dot(movement, movement);
      if (squared > 1.0e-30) {
        vec2 across = cross(center.xyz, movement).xy;
        float sideSquared = dot(across, across);
        if (sideSquared > 1.0e-30) point.xy += across * inversesqrt(sideSquared) * (width * corner.y);
        if (corner.x > 0.0) point.xyz -= movement * (uStretch.y + size.y * uStretch.x * inversesqrt(squared));
      }
      #else
      // Unity caps the larger side of a camera-facing quad to a fraction of
      // the viewport width at the particle depth and keeps the aspect ratio.
      float larger = max(max(size.x, size.y), 1.0e-6);
      float limited = larger;
      if (depth >= 0.0) limited = min(limited, sizeLimit.y * viewWidth);
      if (sizeLimit.x > 0.0 && depth >= 0.0) limited = max(limited, sizeLimit.x * viewWidth);
      vec2 local = corner * size * (limited / larger) + uPivot * size;
      float c = cos(particleFrame.z), s = sin(particleFrame.z);
      // Positive particle rotation turns the quad clockwise.
      local = vec2(c * local.x + s * local.y, -s * local.x + c * local.y);
      #if defined(VIEW_FACING)
      point.xy += local;
      #elif defined(VERTICAL)
      // Camera right in world space, kept horizontal; world up stays vertical.
      vec3 right = normalize(vec3(viewMatrix[0][0], 0.0, viewMatrix[2][0]) + vec3(1.0e-6, 0.0, 0.0));
      point.xyz += mat3(viewMatrix) * (right * local.x + vec3(0.0, local.y, 0.0));
      #else
      point.xyz += mat3(modelViewMatrix) * (uAxisX * local.x + uAxisY * local.y);
      #endif
      #endif
      gl_Position = projectionMatrix * point;
      vec2 quad = corner + 0.5;
      float flips = particleFrame.w;
      if (mod(flips, 2.0) >= 1.0) quad.x = 1.0 - quad.x;
      if (flips >= 2.0) quad.y = 1.0 - quad.y;
      // Unity UV: tile row 0 is the top row of the sheet; then _MainTex_ST.
      vec2 unity = (vec2(particleFrame.x, uTiles.y - 1.0 - particleFrame.y) + quad) / uTiles.xy;
      unity = unity * uMainST.xy + uMainST.zw;
      vMainUV = vec2(unity.x, 1.0 - unity.y);
      #ifdef VERTEX_COLOR
      vColor = particleColor;
      #else
      vColor = vec4(1.0);
      #endif
    }
  `;
  // AS/General/Transparent: texture * _TintColor (* vertex color), plus the
  // _SATURATE_ON term texture.rgb^4.
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uTint;
    varying vec2 vMainUV;
    varying vec4 vColor;
    void main() {
      vec4 texel = texture2D(uTexture, vMainUV);
      vec4 color = texel * uTint * vColor;
      #ifdef SATURATE
      vec3 square = texel.rgb * texel.rgb;
      color.rgb = square * square + color.rgb;
      #endif
      gl_FragColor = color;
    }
  `;

  function blendFactor(T, value) {
    return [T.ZeroFactor, T.OneFactor, T.DstColorFactor, T.SrcColorFactor, T.OneMinusDstColorFactor,
      T.SrcAlphaFactor, T.OneMinusSrcColorFactor, T.DstAlphaFactor, T.OneMinusDstAlphaFactor,
      T.SrcAlphaSaturateFactor, T.OneMinusSrcAlphaFactor][value] ?? T.OneFactor;
  }

  function depthFunction(T, value) {
    if (value === 0) return null; // CompareFunction.Disabled: no depth test
    return [T.AlwaysDepth, T.NeverDepth, T.LessDepth, T.EqualDepth, T.LessEqualDepth, T.GreaterDepth, T.NotEqualDepth,
      T.GreaterEqualDepth, T.AlwaysDepth][value] ?? T.LessEqualDepth;
  }

  function stencilFunction(T, value) {
    return [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc, T.EqualStencilFunc, T.LessEqualStencilFunc,
      T.GreaterStencilFunc, T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc][value] ??
      T.AlwaysStencilFunc;
  }

  function stencilOperation(T, value) {
    return [T.KeepStencilOp, T.ZeroStencilOp, T.ReplaceStencilOp, T.IncrementStencilOp, T.DecrementStencilOp,
      T.InvertStencilOp, T.IncrementWrapStencilOp, T.DecrementWrapStencilOp][value] ?? T.KeepStencilOp;
  }

  function materialFor(T, system, texture) {
    const {material, renderer} = system;
    const [comparison, reference, pass, zFail] = material.stencil;
    const stencil = !(comparison === 0 || comparison === 8) || pass !== 0 || zFail !== 0;
    const defines = {};
    if (material.vertexColor) defines.VERTEX_COLOR = 1;
    if (material.saturate) defines.SATURATE = 1;
    if (renderer.mode === 1) defines.STRETCHED = 1;
    else if (renderer.mode === 3) defines.VERTICAL = 1;
    else if (renderer.mode === 0 && renderer.alignment === 0) defines.VIEW_FACING = 1;
    const depthFunc = depthFunction(T, material.zTest);
    return new T.ShaderMaterial({
      name: `Original particle ${material.name}`, vertexShader, fragmentShader, defines,
      // Cull Off draws both faces; camera-facing quads are wound to face the camera.
      transparent: true, toneMapped: false, side: [T.DoubleSide, T.BackSide, T.FrontSide][material.cull] ?? T.DoubleSide,
      depthTest: depthFunc !== null, depthFunc: depthFunc ?? T.AlwaysDepth, depthWrite: material.zWrite === 1,
      blending: T.CustomBlending,
      blendSrc: blendFactor(T, material.blend[0]), blendDst: blendFactor(T, material.blend[1]),
      blendSrcAlpha: blendFactor(T, material.blend[0]), blendDstAlpha: blendFactor(T, material.blend[1]),
      stencilWrite: stencil, stencilRef: reference, stencilFunc: stencilFunction(T, comparison),
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: stencilOperation(T, zFail), stencilZPass: stencilOperation(T, pass),
      uniforms: {
        uTexture: {value: texture}, uTint: {value: new T.Vector4().fromArray(material.tint)},
        uMainST: {value: new T.Vector4().fromArray(material.st)},
        uTiles: {value: new T.Vector4(system.uv?.tiles[0] || 1, system.uv?.tiles[1] || 1, 0, 0)},
        uSizeLimit: {value: new T.Vector2(renderer.minParticleSize, renderer.maxParticleSize)},
        uPlaneScale: {value: renderer.mode === 2 ? Math.fround(Math.SQRT1_2) : 1},
        uAxisX: {value: new T.Vector3(1, 0, 0)}, uAxisY: {value: new T.Vector3(0, 1, 0)},
        uPivot: {value: new T.Vector2(renderer.pivot[0], renderer.pivot[1])},
        ...(renderer.mode === 1 ? {uStretch: {value: new T.Vector2(renderer.lengthScale, renderer.velocityScale)}} : {}),
      },
    });
  }

  function batch(T, system, texture, capacity, name) {
    const geometry = new T.InstancedBufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute([-.5, -.5, 0, .5, -.5, 0, .5, .5, 0, -.5, .5, 0], 3));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);
    const attribute = (array, width, normalized = false) =>
      new T.InstancedBufferAttribute(array, width, normalized).setUsage(T.DynamicDrawUsage);
    const buffers = {
      centers: attribute(new Float32Array(capacity * 3), 3), sizes: attribute(new Float32Array(capacity * 3), 3),
      colors: attribute(new Uint8Array(capacity * 4), 4, true), frames: attribute(new Float32Array(capacity * 4), 4),
      velocities: system.renderer.mode === 1 ? attribute(new Float32Array(capacity * 3), 3) : null,
    };
    geometry.setAttribute("particleCenter", buffers.centers);
    geometry.setAttribute("particleSize", buffers.sizes);
    geometry.setAttribute("particleColor", buffers.colors);
    geometry.setAttribute("particleFrame", buffers.frames);
    if (buffers.velocities) geometry.setAttribute("particleVelocity", buffers.velocities);
    geometry.instanceCount = 0;
    const mesh = new T.Mesh(geometry, materialFor(T, system, texture));
    mesh.name = name;
    mesh.renderOrder = system.material.queue;
    mesh.frustumCulled = false;
    mesh.matrixAutoUpdate = false;
    mesh.visible = false;
    return {mesh, buffers, capacity};
  }

  function loadTexture(T, title, source) {
    if (!source) {
      const white = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1, T.RGBAFormat);
      white.needsUpdate = true;
      return Promise.resolve(white);
    }
    return title.loadTexture(T, new T.TextureLoader(), source.levels.length > 1 ? source.levels : source.levels[0])
      .then(texture => {
        // The original sampler settings: wrap U/V (0 repeat, 1 clamp) and filter (0 point, 1 bilinear, 2 trilinear).
        const wrap = value => value === 1 ? T.ClampToEdgeWrapping : value === 2 ? T.MirroredRepeatWrapping : T.RepeatWrapping;
        texture.wrapS = wrap(source.wrap?.[0]);
        texture.wrapT = wrap(source.wrap?.[1]);
        const mipmapped = source.levels.length > 1;
        texture.magFilter = source.filter === 0 ? T.NearestFilter : T.LinearFilter;
        texture.minFilter = !mipmapped ? texture.magFilter : source.filter === 0 ? T.NearestMipmapNearestFilter :
          source.filter === 2 ? T.LinearMipmapLinearFilter : T.LinearMipmapNearestFilter;
        texture.needsUpdate = true;
        return texture;
      });
  }

  async function apply(T, root, descriptor) {
    const title = global.MVStudioTitle, native = engine();
    if (!root?.isObject3D || !title?.loadTexture || !native || !validDescriptor(descriptor)) return null;
    const textures = [];
    try {
      for (const source of descriptor.textures) textures.push(await loadTexture(T, title, source));
      textures.push(await loadTexture(T, title, null));
    } catch {
      for (const texture of textures) texture.dispose();
      return null;
    }
    const white = textures[textures.length - 1];
    const group = new T.Group();
    group.name = "Original particle systems";
    group.matrixAutoUpdate = false;
    root.add(group);
    // Each clip owns its clone, clock and meshes (PrefabControlPlayable per clip).
    const cues = descriptor.cues.map((cue, cueIndex) => {
      const template = descriptor.templates[cue.template];
      const poses = nodePoses(template.nodes, cue.offset);
      const systems = template.systems.map((system, systemIndex) => {
        const pose = poses[system.node];
        // Drawn by the main camera only on its culling-mask layers; layer 20
        // belongs to the overlay camera, which this module does not drive.
        const drawn = ((mainCameraMask >>> system.layer) & 1) === 1 && system.layer < 32;
        return {system, systemIndex, pose, drawn, packet: null, stream: null, frame: -1, fps: 0, count: 0,
          seed: system.main.autoRandomSeed ?
            // The game draws a fresh auto seed per activation; keep a stable stand-in per clip.
            (Math.imul((cue.clipSeed >>> 0) ^ 0x9e3779b9, 0x85ebca6b) + Math.imul(systemIndex + 1, 0xc2b2ae35) + cueIndex) >>> 0 :
            system.main.randomSeed >>> 0};
      });
      return {cue, cueIndex, template, systems};
    });
    const local = new T.Vector3(), center = new T.Vector3();
    let tracks, disposed = false;

    function simulationOf(entry) {
      if (entry.stream === undefined || entry.stream) return entry.stream;
      const {system, pose} = entry;
      const inverse = conjugate(pose.rotation);
      const worldVelocity = system.velocity?.worldSpace ? value => quatRotate(inverse, value) : null;
      entry.stream = create(system, entry.seed, {gravity: quatRotate(inverse, [0, -1, 0]), worldVelocity}) || undefined;
      return entry.stream;
    }

    function packetOf(entry, cue) {
      if (!entry.packet) {
        const {system} = entry, texture = system.material.texture === null ? white : textures[system.material.texture];
        entry.packet = batch(T, system, texture, Math.max(1, system.main.maxParticles),
          `Original particles ${cue.template.name}/${system.path}`);
        group.add(entry.packet.mesh);
        const axes = fixedAxes(system, entry.pose);
        if (axes) {
          entry.packet.mesh.material.uniforms.uAxisX.value.fromArray(axes[0]);
          entry.packet.mesh.material.uniforms.uAxisY.value.fromArray(axes[1]);
        }
      }
      return entry.packet;
    }

    function fixedAxes(system, pose) {
      // Unity world axes of world/local/horizontal quads, reflected along X like the stage.
      const mirror = ([x, y, z]) => [-x, y, z];
      const {mode, alignment} = system.renderer;
      if (mode === 2) return [mirror([1, 0, 0]), mirror([0, 0, 1])];
      if (mode === 0 && alignment === 1) return [mirror([1, 0, 0]), mirror([0, 1, 0])];
      if (mode === 0 && alignment === 2) {
        return [mirror(quatRotate(pose.rotation, [1, 0, 0])), mirror(quatRotate(pose.rotation, [0, 1, 0]))];
      }
      return null;
    }

    function hide(entry) {
      if (entry.packet) {
        entry.packet.mesh.visible = false;
        entry.packet.mesh.geometry.instanceCount = 0;
      }
      entry.count = 0;
      entry.frame = -1;
    }

    function write(entry, cue, frames, fps) {
      const stream = simulationOf(entry);
      if (!stream) return hide(entry);
      const active = stream.sample(frames, fps);
      const packet = packetOf(entry, cue), {buffers, mesh} = packet, {system, pose} = entry;
      const {mode, sortMode} = system.renderer;
      const scale = system.main.scalingMode === 0 ? pose.scale : system.main.scalingMode === 1 ? pose.local : [1, 1, 1];
      const toWorld = position => {
        const scaled = position.map((value, i) => value * scale[i]);
        const world = quatRotate(pose.rotation, scaled).map((value, i) => value + pose.position[i]);
        return [-world[0], world[1], world[2]];
      };
      let rows = active.map(atom => stream.describe(atom));
      rows = rows.map(row => ({...row, world: toWorld(row.position)}));
      if (sortMode === 2) rows.sort((a, b) => a.age - b.age);
      else if (sortMode === 3) rows.sort((a, b) => b.age - a.age);
      center.set(0, 0, 0);
      for (const row of rows) center.x += row.world[0], center.y += row.world[1], center.z += row.world[2];
      if (rows.length) center.multiplyScalar(1 / rows.length);
      mesh.position.copy(center);
      mesh.updateMatrix();
      let count = 0;
      for (const row of rows) {
        if (count >= packet.capacity) break;
        const [sx, sy, sz] = row.size;
        if (!(Math.max(sx, sy) > 0) || !row.rgba[3] && system.material.vertexColor) continue;
        local.fromArray(row.world).sub(center);
        buffers.centers.setXYZ(count, local.x, local.y, local.z);
        buffers.sizes.setXYZ(count, sx, sy, sz);
        buffers.colors.setXYZW(count, ...row.rgba);
        buffers.frames.setXYZW(count, row.column, row.row, row.roll, (row.flipU ? 1 : 0) + (row.flipV ? 2 : 0));
        if (buffers.velocities) {
          const moving = quatRotate(pose.rotation, row.velocity.map((value, i) => value * scale[i]));
          buffers.velocities.setXYZ(count, -moving[0], moving[1], moving[2]);
        }
        count++;
      }
      mesh.geometry.instanceCount = count;
      mesh.visible = count > 0;
      for (const attribute of Object.values(buffers)) if (attribute) attribute.needsUpdate = true;
      entry.count = count;
      entry.rows = rows;
      return undefined;
    }

    return {
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const byId = new Map((tracks || []).map(track => [track.id, track]));
          for (const entry of cues) entry.track = byId.get(entry.cue.trackId);
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        for (const entry of cues) {
          const {cue, track, systems} = entry;
          const event = track && !track.muted && quality?.[cue.quality] !== false &&
            track.events.find(row => row.id === cue.eventId);
          const frames = event ? activeFrames(event, time, fps) : 0;
          for (const item of systems) {
            if (!frames || !item.drawn) {
              hide(item);
              continue;
            }
            if (item.frame === frames && item.fps === fps) continue;
            item.frame = frames;
            item.fps = fps;
            write(item, entry, frames, fps);
          }
        }
      },
      inspect(limit = 8) {
        const result = [];
        for (const entry of cues) for (const item of entry.systems) {
          if (item.frame <= 0) continue;
          result.push({cue: entry.cue.eventId, track: entry.cue.trackId, template: entry.template.name,
            path: item.system.path, layer: item.system.layer, seed: item.seed, frames: item.frame,
            alive: item.stream ? (item.rows?.length ?? 0) : 0, drawn: item.count,
            positions: (item.rows || []).slice(0, limit).map(row => row.world.map(value => Math.round(value * 1e4) / 1e4))});
        }
        return result;
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(group);
        for (const entry of cues) for (const item of entry.systems) {
          if (!item.packet) continue;
          item.packet.mesh.geometry.dispose();
          item.packet.mesh.material.dispose();
        }
        for (const texture of textures) texture.dispose();
      },
    };
  }

  global.MVStudioParticleSystems = {
    apply, create, activeFrames, validDescriptor, validSystem, validSimulation, compileCurve, gradientAt, nodePoses, eulerQuaternion,
    blendFactor, depthFunction, mainCameraMask, salts,
  };
})(typeof window !== "undefined" ? window : globalThis);
