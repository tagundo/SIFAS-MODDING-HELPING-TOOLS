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
  //    libunity.so: the InitialModule (+0x180) and ShapeModule (+0x230) Rand4
  //    seed lane i with seed + 0x16f * i (0x4141e0), and ResetSeeds 0x1d24f8
  //    reseeds them from the serialized seed (or a fresh global draw with
  //    autoRandomSeed) on every Play from stopped and every restarting
  //    Simulate, so a fixed seed repeats its draws in every run.
  //  * InitialModule draw order per birth of a per-step start (0x60bd60):
  //    particle word, lifetime, size X (Y, Z when size3D), rotation (Z, X, Y
  //    when rotation3D), color. A procedural prewarm's particles are built
  //    from its batches instead (0x60fe08, lifetime first; regenerate()).
  //  * Per-particle module randoms come from a fresh stream seeded with the
  //    particle word plus the module salt (velocity, size, color, rotation...).
  //  * Age runs from 0 to 100 at dt * 100 / lifetime per step (reciprocal
  //    refined as on ARM), curves are sampled at age * .01.
  //  * Rate emission carries its fraction across steps; newborns advance by
  //    their fraction of the step. Prewarm (Play(1) from playOnAwake 0x1cdaa4
  //    -> Simulate 0x1cbf64 flags 3 -> 0x1d1e54, 0x1ce4b0) replays one maximum
  //    lifetime of system time from the loop time that ends it at a loop
  //    end: 1 s steps while more than 10 s remain, .2 s steps while more than
  //    5 s remain, then Time.fixedDeltaTime (.02) steps, and the remainder
  //    runs after the first display frame's full steps. Its rate carry starts
  //    at 1 - (scan carry) + 1e-4, so an enabled module emits one extra
  //    particle in the first step even at rate 0. A procedural system
  //    (culling.procedural) prewarms in one procedural update that records
  //    emission batches, whose cap counts every particle emitted so far, live
  //    or dead, and builds the particles from the batches at its end (burst
  //    particles at their step's end); after the prewarm the cap counts live
  //    particles again (per-frame updates run non-procedurally, 0x1ce1b8).
  //  * The clone root sits at the world origin plus the clip offset; its
  //    systems use their own serialized random seeds.
  //  * A system advances on the game's frame time (Time.deltaTime, so
  //    Time.time differences), the director follows the music: when frames
  //    hit Time.maximumDeltaTime (1/3 s) the game clock falls behind the
  //    director. Given the game's clock (update's `clock`: director seconds
  //    to Time.time, gameClock()), a clip's frames count the game seconds
  //    since its activation frame; the clip window stays on the director.
  //    Culled systems take each clone frame's cameras at the director time
  //    the game clock reached it.
  //    In the 12035 Max 3D dump4 kirakira_01 of fx_par_so2035_02 kept
  //    ParticleSystem.time - (Time.time since its clip start) within -0.12 ..
  //    -0.07 s across the clamped frames at 48.9-53.3 s, while the same
  //    difference on director time moved from -0.24 to -0.63 s.
  //  * Given the run's own device frames (update's `grid`, frameGrid(): every
  //    rendered frame's director time and Time.deltaTime, from a runtime
  //    dump's frame clock), a clip activates in the first frame whose
  //    director time reaches its start and that frame updates its systems by
  //    its own Time.deltaTime; every later frame by its own (stream.frames:
  //    the client's per-frame sub-steps, deviceFrame()); a culled system only
  //    in frames whose previous frame showed its box, on that frame's
  //    cameras. 12035 dump5: ParticleSystem.time and particleCount of all 213
  //    playing-system samples, culled ones included, match the game. The
  //    editor's own playback keeps the 30 / 60 fps display frames above,
  //    which are this rule at a steady frame rate and simulationSpeed 1 (two
  //    1/60 sub-steps per 1/30 s frame; at another speed the client scales
  //    the frame before it divides it, which the display frames do not).
  //  * EmissionModule (0x65b770): the rate is sampled at the end of the
  //    step's stretch of the loop clock, in live steps and in the prewarm's
  //    bounds scan, and each burst fires at most once per step (0x65bd78;
  //    emitted(), burstsIn()).
  //
  //  * Billboard quads with 3D start rotation turn by the negated X/Y/Z angles
  //    in Unity's Euler order (Z, then X, then Y) on the alignment's axes, as
  //    mv-studio-display-lights.js draws its Local strokes: the emitter's for
  //    Local, the world's for World, and camera right, up and back for View
  //    (libunity.so 0xd242c, axes from 0xc37d8).
  //  * Local scaling mode applies the system's own localScale s: local-space
  //    positions go through the scaled transform; billboard quads keep their
  //    unscaled size, roll and tilt, and their axes in world space are
  //    multiplied component-wise by s; the min/max size cap compares the
  //    unscaled larger side with the limit over s.x (libunity.so 0xc35c4,
  //    0xd2844; core/mv_studio_particle_systems.py _scaled_billboard).
  //
  //  * Unity culling (core/mv_studio_particle_systems.py culling()): a system
  //    whose clock culling freezes off screen (looping procedural Automatic,
  //    or Pause) and whose culling box the importer reproduced advances only
  //    in display frames whose previous frame showed its box to a camera
  //    that draws it: the main camera, and the split-screen sub cameras
  //    while a split clip is active (the activation frame always advances).
  //    The box is the local procedural box through the local-to-world
  //    matrix; View alignment takes the largest scale on every axis
  //    (libunity.so 0xc0e3c). Particles keep their state while culled;
  //    PauseAndCatchup systems keep simulating.
  //
  // Not reproduced, so the importer reports these systems and this runtime
  // refuses them as well: X/Y start rotation on other render modes than
  // Billboard, X/Y rotation over lifetime,
  // ShapeModule.alignToDirection except where a horizontal billboard cannot
  // show it, any other transform scale the scaling mode would apply to
  // particles (Hierarchy, Shape, world-space forces), and either billboard case
  // above on a system culling pauses off screen when its culling box is not
  // reproduced (its clock depends on the cameras' visibility history).

  const f32 = Math.fround;
  const gravityMagnitude = f32(9.81), ageScale = f32(.01);
  const fixedStep = f32(.02), catchUpStep = f32(.2), clockBias = f32(.0001), birthBias = f32(1e-6);
  // Device frames (deviceFrame): Time.maximumParticleDeltaTime of the APK's TimeManager, the
  // smallest sub-step that updates (0xb35ef0) and the accumulator floor of the step loop (0xb35ee8).
  const maxParticleStep = f32(.03), smallestSubStep = f32(1e-5), leftoverStep = f32(1e-6);
  // InitialModule +0x1e8 outside sub-emitter emission (see birth()).
  const inheritedLifetime = 1;
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
      const unitChain = unitScale(node.scale) && (!parent || parent.unitChain);
      poses.push({position, rotation, scale, local: node.scale, unitChain});
    }
    return poses;
  }

  const unitScale = scale => scale.every(value => Math.abs(value - 1) <= 1e-6);

  // Local mode's own scale is applied to billboards in local simulation space
  // without world-space forces (core/mv_studio_particle_systems.py
  // _scaled_billboard). Any other transform scale the scaling mode applies
  // (Hierarchy and Shape: every node up to the clone root) must be the
  // identity. alignToDirection also needs an emitter turned about Y only.
  function scaledBillboard(system, pose) {
    const {main, renderer, velocity, clamp} = system;
    return main.scalingMode === 1 && renderer.mode === 0 && !main.worldSpace && zeroCurve(main.gravity) &&
      !velocity?.worldSpace && !clamp?.worldSpace && pose.local.every(value => value > 1e-6) && !pausedOffScreen(system);
  }

  // Unity culling freezes a looping procedural Automatic (0) system and any
  // Pause (2) system while its renderer is invisible, and resumes it without
  // catching up (libunity.so renderer callbacks 0xc2618 / 0xc2648 -> uncull
  // 0x1cbd10 / cull 0x1cc5d8); core/mv_studio_particle_systems.py culling().
  // The runtime reproduces that from the importer's culling box; without one
  // (or from a descriptor older than it) the clock-dependent cases are refused.
  const cullingBox = ({culling}) => culling?.pauses && culling.bounds ? culling.bounds : null;
  const pausedOffScreen = system => system.culling ? !!system.culling.pauses && !system.culling.bounds :
    (system.main.cullingMode ?? 0) === 2 || ((system.main.cullingMode ?? 0) === 0 && !!system.main.looping);

  // The scaling-mode scale a billboard's quad axes and size cap carry, or null
  // when it is the identity. libunity.so: the ParticleSystem state keeps it at
  // +0x154 (0x1cca20: Hierarchy the lossy scale, Local the node's localScale,
  // Shape 1); the renderer job copies it (0xc3528) and the View/World/Local
  // billboard geometry (0xd242c, variants 0xd78f4/0xdd314/0xdf694) multiplies
  // its quad axes by it component-wise after the particle's roll and 3D
  // rotation, which stay in the unscaled quad.
  // reproducible() admits a non-identity one only for Local scaling.
  const billboardScale = ({main, renderer}, pose) =>
    main.scalingMode === 1 && renderer.mode === 0 && !unitScale(pose.local) ? pose.local : null;

  function reproducible(system, pose) {
    const scaled = system.main.scalingMode === 1 ? !unitScale(pose.local) && !scaledBillboard(system, pose) :
      !pose.unitChain;
    const tilted = Math.abs(pose.rotation[0]) > 1e-6 || Math.abs(pose.rotation[2]) > 1e-6;
    return !scaled && !(system.shape?.alignToDirection && tilted);
  }

  // ---------------------------------------------------------------- validation
  function zeroCurve(curve) {
    if (curve.mode === 0) return curve.scalar === 0;
    if (curve.mode === 3) return curve.scalar === 0 && curve.min === 0;
    return curve.scalar === 0 || [...curve.maxKeys, ...(curve.minKeys || [])].every(([, value, incoming, outgoing]) =>
      value === 0 && !incoming && !outgoing);
  }

  // The one alignToDirection set-up with native evidence (mv_studio_umbrella_particles.py):
  // a Circle or SingleSidedEdge turned 90 degrees about X aligns particles to
  // horizontal directions, which only writes their X/Y rotation, and a local
  // horizontal billboard reads Z alone.
  function planarAlignment({shape, renderer, main}) {
    const turn = value => ((value % 360) + 360) % 360;
    return renderer.mode === 2 && renderer.alignment === 2 && !main.rotation3D && [10, 12].includes(shape.type) &&
      turn(shape.rotation[0]) === 90 && turn(shape.rotation[2]) === 0 && !shape.randomDirection &&
      !shape.sphericalDirection;
  }

  function validSimulation(system) {
    const {main, emission, shape, renderer} = system || {};
    if (!main || !emission || !renderer) return false;
    if (!finite(main.duration) || main.duration <= 0 || !Number.isInteger(main.maxParticles) ||
        main.maxParticles < 0 || main.maxParticles > 4096 || !Number.isInteger(main.randomSeed) ||
        !["startDelay", "lifetime", "speed", "size", "rotation", "gravity"].every(name => validCurve(main[name])) ||
        (main.size3D && !(validCurve(main.sizeY) && validCurve(main.sizeZ))) ||
        (main.rotation3D && !(validCurve(main.rotationX) && validCurve(main.rotationY))) ||
        !validColor(main.color) || !finite(main.simulationSpeed) || main.simulationSpeed <= 0) return false;
    if ((emission.enabled !== undefined && typeof emission.enabled !== "boolean") ||
        !validCurve(emission.rate) || !Array.isArray(emission.bursts) || emission.bursts.length > 32 ||
        !emission.bursts.every(burst => finite(burst?.time) && validCurve(burst.count) &&
          Number.isInteger(burst.cycles) && finite(burst.interval) && finite(burst.probability))) return false;
    if (shape && !(Number.isInteger(shape.type) && vector(shape.position, 3) && vector(shape.rotation, 3) &&
        vector(shape.scale, 3) && finite(shape.radius) && finite(shape.arc) && finite(shape.angle))) return false;
    // BoxShell/BoxEdge and partial radius thickness have no native sampling here.
    const thickness = shape?.radiusThickness ?? 1;
    if (shape && ([15, 16].includes(shape.type) || ([0, 2].includes(shape.type) && thickness !== 1) ||
        ([4, 8, 10].includes(shape.type) && thickness !== 0 && thickness !== 1))) return false;
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
    if ((tilted(system) && (renderer.mode !== 0 || pausedOffScreen(system))) ||
        (system.rotation?.separateAxes && !(zeroCurve(system.rotation.x) && zeroCurve(system.rotation.y))) ||
        (shape?.alignToDirection && !planarAlignment(system))) return false;
    return [0, 1, 2, 3].includes(renderer.mode) && finite(renderer.maxParticleSize) &&
      finite(renderer.minParticleSize) && vector(renderer.pivot, 3) && vector(renderer.flip, 3);
  }

  // X/Y start rotation: drawn on View, World and Local billboards, on a system culling cannot
  // pause or whose culling the runtime reproduces (validSimulation).
  const tilted = ({main}) => main.rotation3D && !(zeroCurve(main.rotationX) && zeroCurve(main.rotationY));

  function validCulling(value) {
    return value === undefined || (!!value && typeof value.pauses === "boolean" && typeof value.uniform === "boolean" &&
      (value.procedural === undefined || typeof value.procedural === "boolean") &&
      (value.bounds === null || (vector(value.bounds, 6) && [0, 1, 2].every(axis => value.bounds[axis] <= value.bounds[axis + 3]))));
  }

  function validSystem(system, textures) {
    const material = system?.material;
    return validSimulation(system) && validCulling(system.culling) && !!material && vector(material.tint, 4) && vector(material.st, 4) && vector(material.blend, 2) && vector(material.stencil, 4) &&
      (material.texture === null || (Number.isInteger(material.texture) && !!textures[material.texture])) &&
      Number.isInteger(system.node) && Number.isInteger(system.layer);
  }

  // Prefab Animator curves the runtime plays (mv_studio_prefab_animator): a node
  // translation over local-space systems, and a system renderer's _TintColor or _MainTex_ST.
  function validAnimation({animation, nodes, systems}) {
    const curves = global.MVStudioStageMotion?.validCurve;
    if (!curves || !Array.isArray(animation?.clips) || !Array.isArray(animation.channels) ||
        !animation.clips.every(clip => finite(clip?.start) && finite(clip.duration) && clip.duration >= 0 &&
          typeof clip.loop === "boolean")) return false;
    return animation.channels.every(row => Number.isInteger(row?.clip) && !!animation.clips[row.clip] &&
      Array.isArray(row.curves) && row.curves.every(curves) &&
      (row.kind === "translation" ? Number.isInteger(row.node) && !!nodes[row.node] && row.curves.length === 3 :
        (row.kind === "tint" || row.kind === "uv") && Number.isInteger(row.system) && !!systems[row.system] &&
          row.curves.length === 4));
  }

  // State time of a prefab Animator whose clone was activated `frames` display frames
  // ago: it plays its default state on the player clock from the activation (clipIn
  // does not reach it), wrapped by m_LoopTime or held at the clip end.
  function animatorTime(clip, frames, fps) {
    return animatorTimeAfter(clip, frames / fps);
  }

  // The same after `elapsed` game seconds of clone frames (a game run's device frames).
  function animatorTimeAfter(clip, elapsed) {
    const local = clip.loop && clip.duration > 0 ? elapsed % clip.duration : Math.min(elapsed, clip.duration);
    return clip.start + local;
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
      template.systems.every(system => validSystem(system, textures) && template.nodes[system.node]) &&
      (template.animation === undefined || validAnimation(template))) &&
      cues.every(cue => id(cue?.trackId) && id(cue.eventId) && Number.isInteger(cue.template) &&
        !!templates[cue.template] && vector(cue.offset, 3) && typeof cue.quality === "string");
  }

  // ---------------------------------------------------------------- shapes
  // Unity ShapeModule sampling as the native modules reproduce it: heading in
  // turns through the native sine polynomial, area radius sqrt((1-u) + .001u)
  // at full thickness (radius 1 on the edge at thickness 0; nothing between is
  // accepted), cone directions normalize(sin(a) * xy, cos(a)) and a
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
        case 5: {
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

  // 0x1d7490 step sizes of a prewarm of `horizon` system seconds (fixed
  // step Time.fixedDeltaTime .02, TimeManager +0x48; the APK's TimeManager
  // keeps Unity's .02): while more than 10 s remain, the previous step if
  // above 1 s, else min(duration, 1); while more than 5 s remain, the
  // previous step if above .2 s, else min(duration, .2); then the fixed step,
  // until less than the last step is left. That remainder stays in the update
  // accumulator (state +0) for the next frame.
  function prewarmSteps(horizon, cycle) {
    const steps = [];
    let remainder = f32(horizon), last = fixedStep;
    if (!(remainder >= fixedStep)) return {steps, remainder};
    do {
      let dt;
      if (remainder > 10) dt = last > 1 ? last : f32(Math.min(cycle, 1));
      else {
        dt = remainder < fixedStep ? remainder : fixedStep;
        if (remainder > 5) dt = last > catchUpStep ? last : f32(Math.min(cycle, catchUpStep));
      }
      steps.push(dt);
      remainder = f32(remainder - dt);
      last = dt;
    } while (remainder >= last && steps.length < 100000);
    return {steps, remainder};
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
    // An enabled EmissionModule (a descriptor older than the flag: one that can emit at all).
    const emitting = typeof emission.enabled === "boolean" ? emission.enabled :
      !zeroCurve(emission.rate) || emission.bursts.length > 0;
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

    // InitialModule start values of one lane. A per-step start (0x60bd60)
    // draws the particle word first, then the lifetime; the procedural
    // regeneration (0x60fe08) has drawn the lifetime before the word and
    // passes it as `drawnLife`. The per-step start scales the lifetime by
    // InitialModule +0x1e8 and keeps at least 1e-5 (0x60c2b0-0x60c2cc).
    // +0x1e8 is the sub-emitter inherited lifetime: 1 (constructor 0x60bb38,
    // Reset 0x60bc84, restored at 0x1cf9d8 after every sub-emitter emission),
    // the parent's remaining lifetime only while a sub-emitter with Inherit
    // Lifetime emits (0x1c9aec bit 3 from 0x1c6420). This runtime runs no
    // sub-emitters, so the factor is always 1.
    function birth({initial}, systemTime, drawnLife) {
      const word = initial();
      const life = drawnLife ??
        Math.max(f32(1e-5), f32(lifetime.sample(systemTime, nativeUnit(initial())) * inheritedLifetime));
      const size = sizes.map(curve => curve.sample(systemTime, nativeUnit(initial())));
      const angles = rotations.map(curve => curve.sample(systemTime, nativeUnit(initial())));
      const rgba = startColor(nativeUnit(initial()), systemTime);
      const speed = startSpeed.sample(systemTime, salted(word, salts.speed));
      const stream = nativeRandom((word + salts.velocity) >>> 0);
      // Linear x, y, z, then (stand-in order) orbital x, y, z, offset x, y, z, radial and speed modifier.
      const weights = Array.from({length: orbital || speedModifier ? 11 : 3}, () => nativeUnit(stream()));
      const threshold = f32(main.randomizeRotationDirection * .5);
      return {
        word, life: nativeInverseLifetime(life), size, roll: angles[0], tilt: angles.length === 3 ? [angles[1], angles[2]] : null,
        rgba, speed, weights,
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

    // One step of a particle's motion; `falling` false leaves gravity out
    // (the procedural rebuild adds it in closed form, fall()).
    function advance(atom, dt, falling = true) {
      const {source} = atom, phase = f32(atom.age * ageScale);
      if (falling && source.gravity) {
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

    // 0x65bd78: the bursts of one call over the loop clock window [from, to). Each burst
    // fires at most once per call: when its time lies in the window, or, in a call that
    // checks repeats, when its time is before the window, it has repeats left
    // ((from - time) / interval below cycles - 1; cycles 0 repeats without end, 1 never) and
    // a repeat boundary falls inside (trunc((to - time) / interval) above
    // trunc((from - time) / interval)). The count is sampled at the call's end over the
    // duration (0x65bdac, passed to 0x65b444). `end` is the step end on the same clock as
    // the window, `loop` the loop the window belongs to (stand-in draws).
    function burstsIn(from, to, repeats, end, loop) {
      const found = [], scaled = f32(to / cycle);
      bursts.forEach((burst, index) => {
        const time = f32(burst.time);
        let at = null, k = 0;
        if (time >= from && time < to) at = time;
        else if (repeats && burst.cycles !== 1 && time < from) {
          const interval = f32(burst.interval);
          const before = f32(f32(from - time) / interval);
          if (burst.cycles !== 0 && before >= burst.cycles - 1) return;
          const after = f32(f32(to - time) / interval);
          if (!(Math.trunc(after) > Math.trunc(before))) return;
          k = Math.trunc(after);
          at = f32(time + f32(k * interval));
        }
        if (at === null) return;
        const draw = salt => nativeUnit(nativeRandom((seed + salts.burst + salt + loop * 977 + index * 131 + k) >>> 0)());
        if (burst.probability < 1 && draw(0) > burst.probability) return;
        const count = Math.round(burst.count.sample(scaled, draw(1)));
        if (count > 0) found.push({count, elapsed: f32(end - at)});
      });
      return found;
    }

    // 0x65b770: particles a step emits over the loop clock from `from` to `to` (0x1d77dc
    // passes the system time before and after the step), sampling the rate at the end of
    // its stretch over the duration, never below 0: a step that wraps (to below from) adds
    // to * rate(to / duration) and (duration - from) * rate(1). One weight per call for
    // rates between constants or curves (stand-in stream). The bursts of a wrapping step
    // come from [0, to), checking repeats, then [from, duration + 1e-4), not checking them
    // (0x65bcc8-0x65bd10); otherwise from [from, to) checking repeats.
    function emitted(state, from, to, wrapped, next) {
      const weight = nativeUnit(nativeRandom((seed + state.loop * 7919 + Math.trunc(from * 1e4)) >>> 0)());
      const rateAt = time => Math.max(0, rate.sample(time, weight));
      const atEnd = rateAt(f32(to / cycle));
      if (!wrapped) {
        return {amount: f32(f32(Math.max(0, f32(to - from))) * atEnd), pulses: burstsIn(from, to, true, next, state.loop)};
      }
      const amount = f32(f32(to * atEnd) + f32(f32(cycle - from) * rateAt(f32(cycle / cycle))));
      const pulses = [...burstsIn(0, to, true, to, state.loop + 1),
        ...burstsIn(from, f32(cycle + clockBias), false, next, state.loop)];
      return {amount, pulses};
    }

    // Particles the emission cap counts: the live ones, or during a
    // procedural prewarm every particle of every batch so far, live or dead.
    const used = state => state.batches ? state.batches.reduce((sum, batch) => sum + batch.count, 0) : state.active.length;

    function step(state, rawDt) {
      simulate(state, f32(rawDt * speedScale));
    }

    // One update step of dt system seconds.
    function simulate(state, dt) {
      const {active} = state;
      for (const atom of active) advance(atom, dt);
      cull(active);
      // 0x1d7490 ages every batch by the step before it emits (0x1d7634).
      if (state.batches) for (const batch of state.batches) batch.age = f32(batch.age + dt);
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
      const end = main.looping ? clock : Math.min(next, cycle);
      const systemTime = f32(previous / cycle);
      const {amount, pulses} = emitted(state, previous, end, wrapped, next);
      const total = f32(amount + state.carry), requested = Math.max(0, Math.trunc(total));
      state.carry = total > 0 ? f32(total - requested) : 0;
      state.clock = clock;
      if (wrapped) state.loop++;
      if (!main.looping && next >= cycle) state.stopped = true;
      // 0x65b770 leaves 1 / amount (1 below 1e-4) at emission state +0.
      const inverse = amount < clockBias ? 1 : f32(1 / amount);
      if (state.batches) {
        // A procedural step appends one emission batch (0x1d7908): the loop
        // time at the step end, age 0, the carry left over, the spacing
        // dt / amount, the rate and burst particles together capped by every
        // batch so far (maxNumParticles, ring buffer off), and the uncapped
        // rate count. 0x1d7a94 turns the batches into particles at the end.
        const before = used(state);
        const total = requested + pulses.reduce((sum, pulse) => sum + pulse.count, 0);
        const count = Math.min(before + total, main.maxParticles) - before;
        if (count > 0) {
          state.batches.push({time: clock, age: 0, carry: state.carry, spacing: f32(dt * inverse), count, rate: requested,
            step: state.step});
        }
        return;
      }
      const room = Math.max(0, main.maxParticles - used(state));
      const regular = Math.min(requested, room);
      if (regular > 0) {
        born(state, regular, index => f32(dt * Math.min(1, Math.max(birthBias, f32(f32(index + state.carry) * inverse)))),
          systemTime);
      }
      for (const {count, elapsed} of pulses) {
        const allowed = Math.min(count, Math.max(0, main.maxParticles - used(state)));
        if (!(allowed > 0)) continue;
        born(state, allowed, () => Math.max(birthBias, Math.min(dt, elapsed)), systemTime);
      }
    }

    // Gravity over `time` seconds in closed form, as the procedural rebuild
    // moves its particles (0x1d8284-0x1d8334): x += G t * (t * .5) and
    // v += G t, G the gravity times the particle's gravity modifier in the
    // simulation space.
    function fall(atom, time) {
      const pull = f32(gravityMagnitude * atom.source.gravity), half = f32(time * .5);
      ["x", "y", "z"].forEach((axis, index) => {
        const gained = f32(f32(pull * g[index]) * time);
        atom[axis] = f32(atom[axis] + f32(gained * half));
        atom[`v${axis}`] = f32(atom[`v${axis}`] + gained);
        atom[`m${axis}`] = f32(atom[`m${axis}`] + gained);
      });
    }

    // 0x1d7a94: the particles of a procedural prewarm's batches, built once
    // its steps are done (libunity.so GL 3.12.0, Unity 2018.4.23f1).
    //  * Per batch in order, the InitialModule's four lanes (0x60fe08) start
    //    groups of 4 lanes. A group first draws its lifetime; lane i of the
    //    batch is (lifetime - age) - (carry + i) * spacing seconds from death,
    //    the offset for rate lanes only (i < the rate count). When all four
    //    lanes are dead the group ends there, one draw spent, and keeps no
    //    particle. Otherwise the lanes draw the rest of their start values
    //    (word, size, rotation, colour) and the group keeps min(left, 4)
    //    particles, `left` going down by 4 only for kept groups, so a group
    //    after a skipped one can keep lanes past the batch count.
    //  * Their age is (1 - (seconds from death) / lifetime) * 100 (+0x3c0),
    //    from the lane's own offset.
    //  * The ShapeModule's lanes (0x15ab60 over all kept particles) give kept
    //    particle k lane k % 4 of group k / 4.
    //  * Positions advance by the kept particle's own offset age (0x1d7ed8:
    //    batch age + (carry + j) * spacing while carry + j is below the rate
    //    count, j counting the batch's kept particles), here by the step
    //    partition the batch lived through (the client integrates velocity
    //    and rotation curves in closed form, 0x5d9aec / 0x659264), and the
    //    kill pass (0x1d8370) removes particles older than 100 as cull() does.
    //  * Gravity is integrated in closed form over the particle's whole time
    //    t = batch age + offset (0x1d8284-0x1d8334): with G the gravity
    //    times the (constant) gravity modifier in the simulation space
    //    (0x60bc94 times InitialModule +0x15c, 0x1d7b14-0x1d7b9c),
    //    x += G t * (t * .5) and v += G t, beside v t.
    // Emulating 0x60fe08 under unicorn on crafted batches reproduced the
    // RNG state, kept count and words of this rule, skipped groups included.
    function regenerate(state, steps) {
      const kept = [];
      for (const batch of state.batches) {
        const time = f32(batch.time / cycle);
        const first = kept.length;
        let left = batch.count;
        for (let base = 0; base < batch.count; base += 4) {
          const lives = lanes.map(lane => Math.max(f32(1e-6), lifetime.sample(time, nativeUnit(lane.initial()))));
          const death = lives.map((life, lane) => {
            const index = base + lane;
            const offset = index < batch.rate ? f32(f32(batch.carry + index) * batch.spacing) : 0;
            return f32(f32(life - batch.age) - offset);
          });
          if (death.every(value => value <= 0)) continue;
          const group = lanes.map((lane, index) => birth(lane, time, lives[index]));
          for (let lane = 0; lane < Math.min(left, 4); lane++) {
            const inverse = group[lane].life;
            const age = f32(Math.max(0, f32(1 - f32(death[lane] * inverse))) * 100);
            kept.push({source: group[lane], age});
          }
          left -= 4;
        }
        const scaled = f32(batch.time * f32(1 / cycle));
        let order = f32(batch.carry);
        for (let index = first; index < kept.length; index++) {
          const offset = order < batch.rate ? f32(order * batch.spacing) : 0;
          kept[index].lived = offset;
          kept[index].batch = batch;
          kept[index].source.speed = startSpeed.sample(scaled, salted(kept[index].source.word, salts.speed));
          order = f32(order + 1);
        }
      }
      for (let base = 0; base < kept.length; base += 4) {
        lanes.forEach(({shape: draw}, lane) => {
          const {position, direction} = shape.draw(draw, base + lane, kept.length);
          const entry = kept[base + lane];
          if (!entry) return;
          entry.source.position = position;
          entry.source.velocity = direction.map(value => f32(value * entry.source.speed));
        });
      }
      state.active = kept.map(({source, age, lived, batch}) => {
        const atom = {source, x: source.position[0], y: source.position[1], z: source.position[2],
          vx: source.velocity[0], vy: source.velocity[1], vz: source.velocity[2], mx: 0, my: 0, mz: 0,
          age: 0, roll: source.roll};
        advance(atom, lived, false);
        for (let index = batch.step + 1; index < steps.length; index++) advance(atom, steps[index], false);
        if (atom.source.gravity) fall(atom, f32(batch.age + lived));
        atom.age = age;
        return atom;
      });
      cull(state.active);
      prewarmBatches = state.batches.map(batch => Object.freeze({...batch}));
      delete state.batches;
    }

    let prewarmBatches = null;
    const clone = state => ({...state, active: state.active.map(atom => ({...atom}))});
    const delay = main.prewarm && main.looping ? 0 : compileCurve(main.startDelay, native).sample(0, nativeUnit(nativeRandom(seed)()));
    let warm = {frame: 0, clock: 0, carry: 0, loop: 0, group: 0, delay: f32(delay), stopped: false, active: []};
    let remainder = 0;
    if (main.prewarm && main.looping) {
      // The bounds scan starts one maximum lifetime before the loop end and
      // feeds its rate carry into the actual prewarm.
      const horizon = f32(Math.max(f32(1e-3), maxCurve(main.lifetime)));
      const start = f32(f32(Math.ceil(f32(horizon / cycle)) * cycle) - horizon);
      // Each scan step calls the same 0x65b770 (0x1d2120: from and to the scan
      // times modulo the duration), so the rate is sampled at the end of the
      // step's stretch, never below 0 (weight .5 stands in for the scan's own
      // random stream).
      let time = start, phase = f32(start % cycle), carry = 0;
      const perSecond = to => Math.max(0, rate.sample(f32(to / cycle), .5));
      while (f32(time + clockBias) < f32(start + horizon)) {
        time = f32(time + fixedStep);
        const next = f32(time % cycle);
        const amount = next < phase ? f32(f32(next * perSecond(next)) + f32(f32(cycle - phase) * perSecond(cycle))) :
          f32(f32(next - phase) * perSecond(next));
        const combined = f32(amount + carry);
        carry = f32(combined - Math.trunc(combined));
        phase = next;
      }
      // 0x1d1e54 seeds the carry with 1 - (the scan's carry) + 1e-4 whatever the
      // rate: an enabled module emits that one extra particle in the first
      // step even at rate 0 (0x65b770 adds the carry after its rate branch).
      warm = {...warm, clock: f32(start % cycle), carry: emitting ? f32(f32(1 - carry) + clockBias) : 0};
      // A procedural system prewarms in one procedural update (Simulate
      // 0x1cbf64 -> 0x1ce4b0 with flag 2): 0x1d7490 appends emission batches
      // and caps each step by the particles of every batch so far, live or
      // dead, and the closing 0x1d7a94 builds the particles from the batches
      // (regenerate). Play and Simulate reseed every lane from the serialized
      // seed first (ResetSeeds 0x1d24f8 at 0x1cc3b8 / 0x1cbfb4), so the
      // prewarm's draws are the same in every run. A non-procedural prewarm
      // starts its particles step by step, as live updates do.
      if (system.culling?.procedural) warm.batches = [];
      const plan = prewarmSteps(horizon, cycle);
      plan.steps.forEach((dt, index) => {
        warm.step = index;
        simulate(warm, dt);
      });
      delete warm.step;
      if (warm.batches) regenerate(warm, plan.steps);
      remainder = plan.remainder;
    }
    const layouts = new Map(), checkpointInterval = 2 * nativeStepRate;

    function layout(fps) {
      const grouped = nativeStepRate / fps;
      // The prewarm's leftover system time runs after the first display
      // frame's full steps, in the raw time step() scales back to it.
      let residue = f32(f32(1 / fps) + f32(remainder / speedScale));
      for (let i = 0; i < grouped; i++) residue = f32(residue - nativeStep);
      const entry = {state: clone(warm), checkpoints: [warm], grouped, residue: main.prewarm && main.looping ? residue : 0};
      layouts.set(fps, entry);
      return entry;
    }

    // One device frame's update of `rawDt` seconds of Time.deltaTime (a game run's own frame
    // clock; libunity.so GL 3.12.0). The update job 0x1ce1f4 scales it by
    // max(simulationSpeed, 0) (0x1ce354) and asks 0x1cfbd4 for the sub-step: the scaled time,
    // or when it exceeds Time.maximumParticleDeltaTime (TimeManager +0x104, the APK's
    // "Maximum Particle Timestep" .03) the scaled time / ceil(scaled time / .03). A sub-step
    // below 1e-5 skips the update (0x1ce370). Otherwise the scaled time joins the update
    // accumulator (state +0, where a prewarm left its remainder) and 0x1d7490 runs the
    // accumulator down in steps of min(accumulator, sub-step) (.2 s steps above 5 s left, 1 s
    // above 10 s, at most the duration, as in the prewarm) until less than 1e-6 is left
    // (0x1d7970); a step of the remainder ends the frame.
    function deviceFrame(state, rawDt) {
      const dt = f32(f32(rawDt) * Math.max(speedScale, 0));
      const sub = maxParticleStep < dt ? f32(dt / Math.ceil(f32(dt / maxParticleStep))) : dt;
      if (sub < smallestSubStep) return;
      let left = f32(state.accumulator + dt), last = sub;
      while (left >= leftoverStep) {
        let dtStep;
        if (left > 10) dtStep = last > 1 ? last : f32(Math.min(cycle, 1));
        else {
          dtStep = left < sub ? left : sub;
          if (left > 5) dtStep = last > catchUpStep ? last : f32(Math.min(cycle, catchUpStep));
        }
        simulate(state, dtStep);
        left = f32(left - dtStep);
        last = dtStep;
      }
      state.accumulator = left;
    }

    let run = null;
    const runInterval = 32;

    return {
      // The emission batches a procedural prewarm built its particles from
      // (time, age, carry, spacing, count, rate, step), or null.
      batches: prewarmBatches,
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
      // A game run's own device frames: `updates` lists the raw Time.deltaTime of every frame
      // the system updated since its activation, the activation frame first (deviceFrame);
      // the particles after the first `count` of them. The array is the run's identity: the
      // stream continues from its last state while the same array grows.
      frames(updates, count) {
        if (!Array.isArray(updates) || !Number.isInteger(count) || count < 0 || count > updates.length) return [];
        if (!run || run.updates !== updates) {
          const start = {...clone(warm), applied: 0, accumulator: main.prewarm && main.looping ? f32(remainder) : 0};
          run = {updates, state: clone(start), checkpoints: [start]};
        }
        const saved = Math.min(run.checkpoints.length - 1, Math.floor(count / runInterval));
        if (count < run.state.applied || run.checkpoints[saved].applied > run.state.applied) run.state = clone(run.checkpoints[saved]);
        const {state} = run;
        while (state.applied < count) {
          const rawDt = updates[state.applied];
          if (!finite(rawDt) || rawDt < 0 || rawDt > 10) break;
          deviceFrame(state, rawDt);
          state.applied++;
          if (state.applied === run.checkpoints.length * runInterval) run.checkpoints.push(clone(state));
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
        return {position: [atom.x, atom.y, atom.z], velocity: [atom.mx, atom.my, atom.mz], size, roll: atom.roll,
          tilt: source.tilt, rgba, column, row, flipU: source.flipU, flipV: source.flipV, age: atom.age};
      },
    };
  }

  // Native activation timing of a PrefabControl clone (mv-studio-stage-particles.js
  // activeControlFrame) without its single-prefab limits: weight, easing and
  // time scale do not change when OnBehaviourPlay activates the clone.
  const timelineTick = time => Math.trunc(time / 1e-12 + .5);

  // Display frame index of the clip's activation frame (frame 1 below).
  function activationFrame(event, fps) {
    const start = timelineTick(event.start), first = Math.ceil(event.start * fps);
    return timelineTick((first - 1) / fps) === start ? first - 1 : first;
  }

  // `clock` (optional, gameClock()): director seconds -> the game's Time.time.
  // The window is the director's; the frames since activation are counted on
  // the game clock from the activation frame's director time.
  function activeFrames(event, time, fps, clock = null) {
    if (!event || !finite(event.start) || !finite(event.duration) || event.duration <= 0) return 0;
    const start = timelineTick(event.start), current = timelineTick(time);
    if (current < start || current >= timelineTick(event.start + event.duration)) return 0;
    const activated = activationFrame(event, fps);
    let local = time;
    if (typeof clock === "function") {
      const from = activated / fps, elapsed = clock(time) - clock(from);
      if (finite(elapsed) && Math.abs(elapsed - (time - from)) > 1e-9) local = from + Math.max(0, elapsed);
    }
    return Math.max(local === time ? 0 : 1, Math.floor(local * fps + 1e-9) - activated + 1);
  }

  // The game's clock as a function of director time from [directorTime,
  // Time.time] samples of rendered frames (ascending director times): linear
  // between samples, one game second per director second outside them. Null
  // without two usable samples.
  function gameClock(samples) {
    const rows = [];
    for (const sample of Array.isArray(samples) ? samples : []) {
      if (!vector(sample, 2)) continue;
      const last = rows[rows.length - 1];
      if (last && (sample[0] <= last[0] || sample[1] < last[1])) continue;
      rows.push([sample[0], sample[1]]);
    }
    if (rows.length < 2) return null;
    const clock = time => {
      if (!finite(time)) return time;
      if (time <= rows[0][0]) return rows[0][1] + (time - rows[0][0]);
      const end = rows[rows.length - 1];
      if (time >= end[0]) return end[1] + (time - end[0]);
      let low = 0, high = rows.length - 1;
      while (high - low > 1) {
        const middle = (low + high) >> 1;
        if (rows[middle][0] <= time) low = middle; else high = middle;
      }
      const [t0, u0] = rows[low], [t1, u1] = rows[high];
      return time === t0 ? u0 : u0 + (u1 - u0) * (time - t0) / (t1 - t0);
    };
    // The director time at which the game clock reached `game` (the first one where it stood still).
    clock.inverse = game => {
      if (!finite(game)) return game;
      if (game <= rows[0][1]) return rows[0][0] + (game - rows[0][1]);
      const end = rows[rows.length - 1];
      if (game >= end[1]) return end[0] + (game - end[1]);
      let low = 0, high = rows.length - 1;
      while (high - low > 1) {
        const middle = (low + high) >> 1;
        if (rows[middle][1] < game) low = middle; else high = middle;
      }
      const [t0, u0] = rows[low], [t1, u1] = rows[high];
      return u1 === u0 ? t1 : t0 + (t1 - t0) * (game - u0) / (u1 - u0);
    };
    clock.samples = rows.length;
    return clock;
  }

  // A game run's own device frames, every rendered frame in frame order: [director time,
  // Time.deltaTime, frameCount (optional)] (a runtime dump's frame clock rows). Null unless
  // there are two frames at least, every Time.deltaTime is in (0, 10] and the director time
  // never goes back. On these frames a clip activates in the first frame whose director time
  // reaches its start and that frame steps its own Time.deltaTime; a time shows the last
  // frame whose director time is not after it, unless `pin` names one of several frames at
  // that time (the song-end hold).
  //   12035 dump5 / 12023: ParticleSystem.time of every looping system that culling never
  //   paused is the sum of the Time.deltaTime of frames A .. N-1 (A the activation frame, N
  //   the record's frame, read before frame N's update) within 6e-5 s in all 40 / 19
  //   records, while A+1 .. N-1 or A .. N miss by 0.19 / 0.2 s on average.
  function frameGrid(rows) {
    if (!Array.isArray(rows) || rows.length < 2 || rows.length > 1000000) return null;
    const times = new Float64Array(rows.length), deltas = new Array(rows.length), counts = new Map();
    const sums = new Float64Array(rows.length + 1);
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index];
      if (!Array.isArray(row) || row.length < 2 || !finite(row[0]) || !finite(row[1]) || row[0] < 0 ||
          (index && row[0] < times[index - 1]) || !(row[1] > 0) || row[1] > 10) return null;
      times[index] = row[0];
      deltas[index] = f32(row[1]);
      sums[index + 1] = sums[index] + deltas[index];
      if (Number.isInteger(row[2]) && !counts.has(row[2])) counts.set(row[2], index);
    }
    const ticks = Array.from(times, timelineTick);
    // The first frame index whose tick is above (strict) or at least `tick`.
    const search = (tick, strict) => {
      let low = 0, high = ticks.length;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (strict ? ticks[middle] > tick : ticks[middle] >= tick) high = middle; else low = middle + 1;
      }
      return low;
    };
    const grid = {
      length: rows.length, times, deltas,
      // The activation frame of a clip starting at `start`: the first frame whose director time
      // reaches it, -1 when none does. A clip the first frame already shows was activated in it
      // or in an earlier frame the run did not record; it is taken from the first one, so its
      // time misses those frames (12023 dump5: fx_par_so2023_02, a clip from 0 s, runs 0.27 s
      // behind the game in every record, against 0.5 s and a third of its particles on the
      // display frames).
      activation(start) {
        const index = search(timelineTick(start), false);
        return index < ticks.length ? index : -1;
      },
      // The frame a director time shows, -1 before the first frame, null after the last one.
      shown(time) {
        const tick = timelineTick(time);
        if (tick > ticks[ticks.length - 1]) return null;
        const pinned = grid.pin === null ? -1 : counts.get(grid.pin) ?? -1;
        return pinned >= 0 && ticks[pinned] === tick ? pinned : search(tick, true) - 1;
      },
      // Game seconds from the start of frame `from` to the end of frame `to`.
      elapsed: (from, to) => to < from ? 0 : sums[to + 1] - sums[from],
      // frameCount of the frame to show among several at one director time (null: the last).
      pin: null,
    };
    return grid;
  }

  // ---------------------------------------------------------------- culling
  // World box (three.js space: Unity X mirrored) of a local culling box under a
  // node pose: the scaling-mode scale (Hierarchy the lossy scale, Local the
  // node's own, Shape 1) after the world rotation; View alignment widens each
  // scaled column to the largest scale (libunity.so 0xc0e78: max(s) / s_i when
  // s_i > 1e-9).
  function worldBox(bounds, system, pose) {
    const mode = system.main.scalingMode;
    let scale = mode === 0 ? pose.scale : mode === 1 ? pose.local : [1, 1, 1];
    if (system.culling.uniform) {
      const largest = Math.max(...scale);
      scale = scale.map(value => value > 1e-9 ? largest : value);
    }
    const center = [0, 1, 2].map(axis => (bounds[axis] + bounds[axis + 3]) / 2);
    const extent = [0, 1, 2].map(axis => (bounds[axis + 3] - bounds[axis]) / 2);
    const columns = [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map((axis, i) => quatRotate(pose.rotation, axis).map(value => value * scale[i]));
    const middle = [0, 1, 2].map(row => pose.position[row] + columns[0][row] * center[0] + columns[1][row] * center[1] +
      columns[2][row] * center[2]);
    const reach = [0, 1, 2].map(row => Math.abs(columns[0][row]) * extent[0] + Math.abs(columns[1][row]) * extent[1] +
      Math.abs(columns[2][row]) * extent[2]);
    return [-middle[0] - reach[0], middle[1] - reach[1], middle[2] - reach[2],
      -middle[0] + reach[0], middle[1] + reach[1], middle[2] + reach[2]];
  }

  // The six clip-space planes (a, b, c, d) of projection * view, as Unity's
  // camera culling planes.
  function cameraPlanes(camera) {
    const view = camera.matrixWorldInverse?.elements, projection = camera.projectionMatrix?.elements;
    if (!vector(view ? Array.from(view) : null, 16) || !vector(projection ? Array.from(projection) : null, 16)) return null;
    const m = new Float64Array(16);
    for (let column = 0; column < 4; column++) for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += projection[k * 4 + row] * view[column * 4 + k];
      m[column * 4 + row] = sum;
    }
    const row = index => [m[index], m[4 + index], m[8 + index], m[12 + index]];
    const [x, y, z, w] = [row(0), row(1), row(2), row(3)];
    return [0, 1, 2].flatMap(axis => [w.map((value, i) => value + [x, y, z][axis][i]),
      w.map((value, i) => value - [x, y, z][axis][i])]);
  }

  function boxVisible(box, planes) {
    for (const [a, b, c, d] of planes) {
      const px = a > 0 ? box[3] : box[0], py = b > 0 ? box[4] : box[1], pz = c > 0 ? box[5] : box[2];
      if (a * px + b * py + c * pz + d < 0) return false;
    }
    return true;
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
    #ifdef SCALED
    uniform vec3 uScale;
    #endif
    #ifdef TILTED
    attribute vec2 particleTilt;
    uniform vec3 uAxisZ;
    #endif
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
      #ifdef SCALED
      // The cap is checked on the unscaled quad against the limit over the
      // scaling-mode scale's X (libunity.so 0xc35c4: renderer min/max divided
      // by max(scale.x, 1e-5); billboard geometry 0xd2c30 compares the
      // particle's own larger side).
      sizeLimit /= max(uScale.x, 1.0e-5);
      #endif
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
      #if defined(TILTED)
      // 3D start rotation: the negated Z, X, Y angles in Unity's Euler order
      // (Z above, then X, then Y) on the alignment's three axes (libunity.so
      // 0xd242c): Local the emitter's, World the unit axes, View the columns of
      // the inverse world-to-camera matrix (0xc37d8 of Camera 0x2966b8, which
      // flips Z): camera right, up and back, three.js view x, y and z.
      float cx = cos(particleTilt.x), sx = sin(particleTilt.x);
      float cy = cos(particleTilt.y), sy = sin(particleTilt.y);
      vec3 turned = vec3(local.x, cx * local.y, -sx * local.y);
      turned = vec3(cy * turned.x - sy * turned.z, turned.y, sy * turned.x + cy * turned.z);
      #if defined(VIEW_FACING) && defined(SCALED)
      vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
      vec3 up = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
      vec3 back = vec3(viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2]);
      point.xyz += mat3(modelViewMatrix) * (uScale * (right * turned.x + up * turned.y + back * turned.z));
      #elif defined(VIEW_FACING)
      point.xyz += turned;
      #else
      point.xyz += mat3(modelViewMatrix) * (uAxisX * turned.x + uAxisY * turned.y + uAxisZ * turned.z);
      #endif
      #elif defined(VIEW_FACING) && defined(SCALED)
      // Camera right/up in world space times the scale, component-wise, like
      // the fixed axes of World and Local quads (libunity.so 0xd2844).
      vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
      vec3 up = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
      point.xyz += mat3(modelViewMatrix) * (uScale * (right * local.x + up * local.y));
      #elif defined(VIEW_FACING)
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

  // AS/General/Transparent render state from the material: blend, cull, depth and stencil
  // (shared with mv-studio-control-prefabs.js, whose meshes use the same shader).
  function renderState(T, material) {
    const [comparison, reference, pass, zFail] = material.stencil;
    const stencil = !(comparison === 0 || comparison === 8) || pass !== 0 || zFail !== 0;
    const depthFunc = depthFunction(T, material.zTest);
    return {
      // Cull Off draws both faces; camera-facing quads are wound to face the camera.
      transparent: true, toneMapped: false, side: [T.DoubleSide, T.BackSide, T.FrontSide][material.cull] ?? T.DoubleSide,
      depthTest: depthFunc !== null, depthFunc: depthFunc ?? T.AlwaysDepth, depthWrite: material.zWrite === 1,
      blending: T.CustomBlending,
      blendSrc: blendFactor(T, material.blend[0]), blendDst: blendFactor(T, material.blend[1]),
      blendSrcAlpha: blendFactor(T, material.blend[0]), blendDstAlpha: blendFactor(T, material.blend[1]),
      stencilWrite: stencil, stencilRef: reference, stencilFunc: stencilFunction(T, comparison),
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: stencilOperation(T, zFail), stencilZPass: stencilOperation(T, pass),
    };
  }

  function materialFor(T, system, texture, scale = null) {
    const {material, renderer} = system;
    const defines = {};
    if (scale) defines.SCALED = 1;
    if (material.vertexColor) defines.VERTEX_COLOR = 1;
    if (material.saturate) defines.SATURATE = 1;
    if (renderer.mode === 1) defines.STRETCHED = 1;
    else if (renderer.mode === 3) defines.VERTICAL = 1;
    else if (renderer.mode === 0 && renderer.alignment === 0) defines.VIEW_FACING = 1;
    if (renderer.mode === 0 && tilted(system)) defines.TILTED = 1;
    return new T.ShaderMaterial({
      name: `Original particle ${material.name}`, vertexShader, fragmentShader, defines,
      ...renderState(T, material),
      uniforms: {
        uTexture: {value: texture}, uTint: {value: new T.Vector4().fromArray(material.tint)},
        uMainST: {value: new T.Vector4().fromArray(material.st)},
        uTiles: {value: new T.Vector4(system.uv?.tiles[0] || 1, system.uv?.tiles[1] || 1, 0, 0)},
        uSizeLimit: {value: new T.Vector2(renderer.minParticleSize, renderer.maxParticleSize)},
        uPlaneScale: {value: renderer.mode === 2 ? Math.fround(Math.SQRT1_2) : 1},
        uAxisX: {value: new T.Vector3(1, 0, 0)}, uAxisY: {value: new T.Vector3(0, 1, 0)},
        uAxisZ: {value: new T.Vector3(0, 0, 1)},
        uPivot: {value: new T.Vector2(renderer.pivot[0], renderer.pivot[1])},
        ...(scale ? {uScale: {value: new T.Vector3().fromArray(scale)}} : {}),
        ...(renderer.mode === 1 ? {uStretch: {value: new T.Vector2(renderer.lengthScale, renderer.velocityScale)}} : {}),
      },
    });
  }

  function batch(T, system, texture, capacity, name, scale = null) {
    const geometry = new T.InstancedBufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute([-.5, -.5, 0, .5, -.5, 0, .5, .5, 0, -.5, .5, 0], 3));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);
    const attribute = (array, width, normalized = false) =>
      new T.InstancedBufferAttribute(array, width, normalized).setUsage(T.DynamicDrawUsage);
    const buffers = {
      centers: attribute(new Float32Array(capacity * 3), 3), sizes: attribute(new Float32Array(capacity * 3), 3),
      colors: attribute(new Uint8Array(capacity * 4), 4, true), frames: attribute(new Float32Array(capacity * 4), 4),
      velocities: system.renderer.mode === 1 ? attribute(new Float32Array(capacity * 3), 3) : null,
      tilts: system.renderer.mode === 0 && tilted(system) ? attribute(new Float32Array(capacity * 2), 2) : null,
    };
    geometry.setAttribute("particleCenter", buffers.centers);
    geometry.setAttribute("particleSize", buffers.sizes);
    geometry.setAttribute("particleColor", buffers.colors);
    geometry.setAttribute("particleFrame", buffers.frames);
    if (buffers.velocities) geometry.setAttribute("particleVelocity", buffers.velocities);
    if (buffers.tilts) geometry.setAttribute("particleTilt", buffers.tilts);
    geometry.instanceCount = 0;
    const mesh = new T.Mesh(geometry, materialFor(T, system, texture, scale));
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
        const drawn = ((mainCameraMask >>> system.layer) & 1) === 1 && system.layer < 32 && reproducible(system, pose);
        return {system, systemIndex, pose, restPose: pose, box: cullingBox(system), history: null, updates: 0,
          drawn, packet: null, stream: null, frame: -1, fps: 0, count: 0, mode: null, device: null, elapsed: 0, culledNow: false,
          seed: system.main.autoRandomSeed ?
            // The game draws a fresh auto seed per activation; keep a stable stand-in per clip.
            (Math.imul((cue.clipSeed >>> 0) ^ 0x9e3779b9, 0x85ebca6b) + Math.imul(systemIndex + 1, 0xc2b2ae35) + cueIndex) >>> 0 :
            system.main.randomSeed >>> 0};
      });
      return {cue, cueIndex, template, systems, animated: null};
    });
    const local = new T.Vector3(), center = new T.Vector3();
    let tracks, disposed = false;
    // Culling planes of every camera that draws the frame, per display frame
    // index, for the visibility pass (Unity counts a renderer visible when
    // any camera drawing its layer sees it).
    const frusta = new Map();
    let cullKey = null, cullFps = 0, cullClock = null, cullGrid = null;

    function frustaAt(index, fps, view) {
      if (frusta.has(index)) return frusta.get(index);
      const time = index / fps;
      const cameras = typeof view.camerasAt === "function" ? view.camerasAt(time) : [view.cameraAt(time)];
      const planes = (cameras || []).filter(Boolean).map(cameraPlanes).filter(Boolean);
      frusta.set(index, planes);
      return planes;
    }

    // Culling planes at a device frame's director time (frustaAt for a game run's own frames).
    const frustaByTime = new Map();
    function frustaAtTime(time, view) {
      if (frustaByTime.has(time)) return frustaByTime.get(time);
      const cameras = typeof view.camerasAt === "function" ? view.camerasAt(time) : [view.cameraAt(time)];
      const planes = (cameras || []).filter(Boolean).map(cameraPlanes).filter(Boolean);
      frustaByTime.set(time, planes);
      return planes;
    }

    // Node poses `elapsed` clone seconds after the activation when the prefab Animator moves
    // nodes, else null.
    function posesAt(entry, elapsed) {
      const animation = entry.template.animation;
      if (!animation?.channels.some(row => row.kind === "translation")) return null;
      if (!entry.poseCache) entry.poseCache = new Map();
      let poses = entry.poseCache.get(elapsed);
      if (!poses) {
        const evaluate = global.MVStudioStageMotion.evaluate;
        const times = animation.clips.map(clip => animatorTimeAfter(clip, elapsed));
        const moved = entry.template.nodes.map(node => ({...node}));
        for (const row of animation.channels) {
          if (row.kind === "translation") moved[row.node].position = row.curves.map(curve => evaluate(curve, times[row.clip]));
        }
        poses = nodePoses(moved, entry.cue.offset);
        entry.poseCache.set(elapsed, poses);
      }
      return poses;
    }

    // Display frames whose update the system ran by clone frame `frames`: the
    // activation frame always runs (Play adds the system to the update list),
    // and a later frame runs only when the previous frame's culling showed the
    // system's box to a camera drawing it; otherwise cull 0x1cc5d8 had taken it
    // off the list (the becameInvisible callback, or the update end 0x1cde54
    // finding the renderer not visible), and becameVisible's uncull put it back.
    // With the game's clock (cullClock) clone frame `index` ran at the director time where the game
    // clock had advanced (index - 1) / fps past the activation frame's; its cameras are taken at the
    // director display frame holding that time.
    function advanced(item, entry, event, frames, fps, view) {
      const activated = activationFrame(event, fps);
      let history = item.history;
      if (!history || history.activated !== activated) history = item.history = {activated, count: [0], visible: [false]};
      const from = cullClock ? cullClock(activated / fps) : 0;
      for (let index = history.count.length; index < frames; index++) {
        const plain = activated + index - 1, at = cullClock ? cullClock.inverse(from + (index - 1) / fps) * fps : plain;
        const display = Math.abs(at - plain) < 1e-6 ? plain : Math.floor(at + 1e-9);
        const planes = frustaAt(display, fps, view);
        const poses = planes.length ? posesAt(entry, index / fps) : null;
        const pose = poses ? poses[item.system.node] : item.restPose;
        const box = planes.length ? worldBox(item.box, item.system, pose) : null;
        const seen = planes.some(sides => boxVisible(box, sides));
        history.visible.push(seen);
        history.count.push(history.count[index - 1] + (seen ? 1 : 0));
      }
      return 1 + history.count[frames - 1];
    }

    // The same on a game run's own device frames (frameGrid): the activation frame
    // `activated` always updates, and frame k after it only when frame k - 1's culling showed
    // the box to a camera drawing it (its cameras at frame k - 1's director time, the prefab
    // Animator after the clone seconds up to frame k - 1). Each update steps its own frame's
    // Time.deltaTime (stream.frames), so a frame the culling skipped adds none. Returns the
    // number of updated frames up to frame `last`; item.device keeps the frames and their
    // Time.deltaTime in order.
    function deviceUpdates(item, entry, grid, activated, last, view) {
      let history = item.device;
      if (!history || history.grid !== grid || history.activated !== activated) {
        history = item.device = {grid, activated, checked: activated, frames: [activated], updates: [grid.deltas[activated]],
          visible: [true]};
      }
      const culled = !!(item.box && view);
      for (let index = history.checked + 1; index <= last; index++) {
        let seen = true;
        if (culled) {
          const planes = frustaAtTime(grid.times[index - 1], view);
          const poses = planes.length ? posesAt(entry, grid.elapsed(activated, index - 1)) : null;
          const pose = poses ? poses[item.system.node] : item.restPose;
          const box = planes.length ? worldBox(item.box, item.system, pose) : null;
          seen = planes.some(sides => boxVisible(box, sides));
        }
        history.visible.push(seen);
        if (seen) {
          history.frames.push(index);
          history.updates.push(grid.deltas[index]);
        }
        history.checked = index;
      }
      let low = 0, high = history.frames.length;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (history.frames[middle] <= last) low = middle + 1; else high = middle;
      }
      return low;
    }

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
          `Original particles ${cue.template.name}/${system.path}`, billboardScale(system, entry.pose));
        group.add(entry.packet.mesh);
        const axes = fixedAxes(system, entry.pose);
        if (axes) {
          entry.packet.mesh.material.uniforms.uAxisX.value.fromArray(axes[0]);
          entry.packet.mesh.material.uniforms.uAxisY.value.fromArray(axes[1]);
          entry.packet.mesh.material.uniforms.uAxisZ.value.fromArray(axes[2]);
        }
      }
      return entry.packet;
    }

    function fixedAxes(system, pose) {
      // Unity world axes of world/local/horizontal quads, reflected along X like the stage.
      const mirror = ([x, y, z]) => [-x, y, z];
      // The third axis is the quad normal that X/Y start rotation turns into.
      const {mode, alignment} = system.renderer;
      if (mode === 2) return [mirror([1, 0, 0]), mirror([0, 0, 1]), mirror([0, -1, 0])];
      // Billboard axes times the scaling-mode scale, component-wise in world
      // space (libunity.so 0xd2844; mirroring X commutes with it).
      const scale = billboardScale(system, pose) || [1, 1, 1];
      const grown = axis => axis.map((value, i) => value * scale[i]);
      if (mode === 0 && alignment === 1) return [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(axis => mirror(grown(axis)));
      if (mode === 0 && alignment === 2) {
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(axis => mirror(grown(quatRotate(pose.rotation, axis))));
      }
      return null;
    }

    // Sample the prefab Animator curves at the clone's state time: moved nodes give
    // the systems below them a new pose; renderer curves replace tint and _MainTex_ST.
    function animate(entry, elapsed) {
      const {template, cue, systems} = entry, animation = template.animation;
      if (!animation || entry.animated === elapsed) return;
      entry.animated = elapsed;
      const evaluate = global.MVStudioStageMotion.evaluate;
      const times = animation.clips.map(clip => animatorTimeAfter(clip, elapsed));
      const moved = template.nodes.map(node => ({...node}));
      let posed = false;
      for (const item of systems) item.tint = item.st = null;
      for (const row of animation.channels) {
        const values = row.curves.map(curve => evaluate(curve, times[row.clip]));
        if (row.kind === "translation") {
          moved[row.node].position = values;
          posed = true;
        } else {
          const item = systems[row.system];
          if (row.kind === "tint") item.tint = values;
          else item.st = values;
        }
      }
      if (!posed) return;
      const poses = nodePoses(moved, cue.offset);
      for (const item of systems) item.pose = poses[item.system.node];
    }

    function hide(entry) {
      if (entry.packet) {
        entry.packet.mesh.visible = false;
        entry.packet.mesh.geometry.instanceCount = 0;
      }
      entry.count = 0;
      entry.frame = -1;
    }

    // sample(stream) -> the particles to draw (stream.sample on display frames, stream.frames on
    // a game run's device frames).
    function write(entry, cue, sample) {
      const stream = simulationOf(entry);
      if (!stream) return hide(entry);
      const active = sample(stream);
      const packet = packetOf(entry, cue), {buffers, mesh} = packet, {system, pose} = entry;
      const uniforms = mesh.material.uniforms;
      uniforms.uTint.value.fromArray(entry.tint || system.material.tint);
      uniforms.uMainST.value.fromArray(entry.st || system.material.st);
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
        // Sizes stay unscaled: the quad axes and the size cap carry the scale (fixedAxes, SCALED).
        const [sx, sy, sz] = row.size;
        if (!(Math.max(sx, sy) > 0) || !row.rgba[3] && system.material.vertexColor) continue;
        local.fromArray(row.world).sub(center);
        buffers.centers.setXYZ(count, local.x, local.y, local.z);
        if (buffers.tilts) buffers.tilts.setXY(count, row.tilt?.[0] ?? 0, row.tilt?.[1] ?? 0);
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
      // view: {camerasAt(time) -> every posed camera drawing the frame (the
      // main camera, and split-screen sub cameras while a split clip is
      // active), or cameraAt(time) -> the main camera or null; key}; a new
      // key (camera tracks, split data or viewport aspect changed) restarts
      // the visibility pass.
      // Without a view, culled systems simulate as if always visible.
      // clock: the game's clock (gameClock()) or null for the director's.
      // grid: a game run's own device frames (frameGrid()) or null. A clip whose activation
      // frame and the frame a time shows are on the grid steps each of its frames' own
      // Time.deltaTime (stream.frames, deviceUpdates); any other clip keeps the clock's
      // 30 / 60 fps display frames.
      update(time, project, view = null, clock = null, grid = null) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const byId = new Map((tracks || []).map(track => [track.id, track]));
          for (const entry of cues) entry.track = byId.get(entry.cue.trackId);
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        const camera = typeof view?.camerasAt === "function" || typeof view?.cameraAt === "function" ? view : null;
        const gameClock = typeof clock === "function" ? clock : null;
        const frames = typeof grid?.shown === "function" && typeof grid.activation === "function" ? grid : null;
        if ((camera?.key ?? null) !== cullKey || fps !== cullFps || gameClock !== cullClock || frames !== cullGrid) {
          cullKey = camera?.key ?? null;
          cullFps = fps;
          cullClock = gameClock;
          cullGrid = frames;
          frusta.clear();
          frustaByTime.clear();
          for (const entry of cues) {
            entry.poseCache = null;
            for (const item of entry.systems) item.history = item.device = null;
          }
        }
        for (const entry of cues) {
          const {cue, track, systems} = entry;
          const event = track && !track.muted && quality?.[cue.quality] !== false &&
            track.events.find(row => row.id === cue.eventId);
          // On the device frames: the clip's activation frame and the frame `time` shows.
          let activated = -1, last = null;
          if (event && frames && activeFrames(event, time, fps) > 0) {
            activated = frames.activation(event.start);
            last = activated >= 0 ? frames.shown(time) : null;
          }
          const device = last !== null;
          const clone = device ? Math.max(0, last - activated + 1) : event ? activeFrames(event, time, fps, clock) : 0;
          if (clone) animate(entry, device ? frames.elapsed(activated, last) : clone / fps);
          else entry.animated = null;
          for (const item of systems) {
            if (!clone || !item.drawn) {
              hide(item);
              continue;
            }
            if (device) {
              const updates = deviceUpdates(item, entry, frames, activated, last, camera);
              const history = item.device;
              if (item.mode === history && item.frame === clone && item.updates === updates) continue;
              item.mode = history;
              item.frame = clone;
              item.fps = fps;
              item.updates = updates;
              // ParticleSystem.time: the scaled Time.deltaTime of the frames it updated.
              let elapsed = 0;
              for (let index = 0; index < updates; index++) elapsed += f32(f32(history.updates[index]) * Math.max(0, f32(item.system.main.simulationSpeed)));
              item.elapsed = elapsed;
              item.culledNow = !history.visible[last - activated];
              write(item, entry, stream => stream.frames(history.updates, updates));
              continue;
            }
            const updates = item.box && camera ? advanced(item, entry, event, clone, fps, camera) : clone;
            if (item.mode === "display" && item.frame === clone && item.fps === fps && item.updates === updates) continue;
            item.mode = "display";
            item.frame = clone;
            item.fps = fps;
            item.updates = updates;
            item.elapsed = updates / fps * item.system.main.simulationSpeed;
            item.culledNow = !!item.box && !!item.history && clone > 1 && !item.history.visible[clone - 1];
            write(item, entry, stream => stream.sample(updates, fps));
          }
        }
      },
      inspect(limit = 8) {
        const result = [];
        for (const entry of cues) for (const item of entry.systems) {
          if (item.frame <= 0) continue;
          const {main} = item.system, elapsed = item.elapsed;
          result.push({cue: entry.cue.eventId, track: entry.cue.trackId, template: entry.template.name,
            path: item.system.path, layer: item.system.layer, seed: item.seed, frames: item.frame,
            // Frames the system updated (fewer than frames while culling froze it) and its clock;
            // device: on a game run's own frames (frameGrid), each stepping its Time.deltaTime.
            updates: item.updates, time: main.looping ? elapsed % main.duration : Math.min(elapsed, main.duration),
            looping: !!main.looping,
            device: item.mode !== "display", culled: !!item.culledNow,
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
    apply, create, activeFrames, gameClock, frameGrid, animatorTime, animatorTimeAfter, validDescriptor, validSystem, validSimulation, compileCurve, gradientAt,
    nodePoses, eulerQuaternion, blendFactor, depthFunction, renderState, loadTexture, mainCameraMask, salts,
    activationFrame, worldBox, cameraPlanes, boxVisible, prewarmSteps,
  };
})(typeof window !== "undefined" ? window : globalThis);
