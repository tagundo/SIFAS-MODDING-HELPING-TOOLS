(function (global) {
  "use strict";

  const f32 = Math.fround;
  const fraction = f32(.01);
  const birthBias = f32(1e-6);
  const speedSalt = 0x96aa4de3;
  const gravitySalt = 0xe2b7c3c3;
  const sizeSalt = 0x8d2c8431;
  const colorSalt = 0x591bc05c;
  const white = [255, 255, 255, 255];
  const checkpointFrames = 12;
  const stateSize = 8;
  const matches = (value, ...expected) => Array.isArray(value) && value.length === expected.length &&
    value.every((part, index) => part === expected[index]);
  const lerp = (a, b, weight) => f32(a + f32(f32(b - a) * weight));

  function supported(row, motion, particles) {
    const shape = row?.shape;
    return row?.name === "hibana_01" && row.capacity === 1000 && row.duration === f32(.1) && row.rate === 0 &&
      shape?.type === 8 && shape.radius === f32(.3) && shape.radiusThickness === 1 &&
      shape.angle === 15 && shape.length === 2 && shape.arc === 360 && shape.arcMode === 0 &&
      matches(shape.scale, 1, 1, 1) && matches(shape.rotation, -90, 0, 0) &&
      matches(row.delay, 0, 0) && matches(row.lifetime, f32(1.2), f32(2.4)) &&
      matches(row.size, f32(.02), f32(.04)) && matches(row.speed, 3, 30) &&
      matches(row.gravity, .5, f32(1.2)) && matches(row.roll, 0, 0) &&
      row.bursts?.length === 1 && matches(row.bursts[0], 0, 1000) &&
      row.clamp?.limit === 1 && row.clamp.dampen === f32(.1) &&
      matches(row.uv, .25, .25, .75, 0) && row.stretch?.lengthScale === 0 &&
      row.stretch.velocityScale === f32(.025) && Array.isArray(row.startColors) && row.startColors.length === 2 &&
      row.startColors.every(color => matches(color, 1, 1, 1, 1)) &&
      row.sizeMultiplier === 1 && Array.isArray(row.sizeCurves) && row.sizeCurves.length === 2 &&
      row.sizeCurves.every(value => motion.validCurve(value) && (value[0] === "constant" || value[1].length <= 16)) &&
      Array.isArray(row.lifeColors) && row.lifeColors.length === 2 &&
      row.lifeColors.every(keys => particles.validNativeColor({start: white, keys}));
  }

  function coneCos(turns) {
    // Unity's shape evaluator uses this float32 polynomial on reduced turns.
    const triangle = f32(.25 - Math.abs(f32(turns - Math.round(turns))));
    const square = f32(triangle * triangle), fourth = f32(square * square);
    const last = f32(f32(square * -76.56861877441406) + 81.60182189941406);
    const first = f32(f32(square * -41.34165954589844) + 6.283185005187988);
    return f32(triangle * f32(f32(f32(fourth * fourth) * 39.65703201293945) +
      f32(first + f32(fourth * last))));
  }

  function create(row, seed) {
    const particles = global.MVStudioStageParticles, motion = global.MVStudioStageMotion;
    if (!particles || !motion || !supported(row, motion, particles) ||
        (seed !== 100 && seed !== 200)) return null;
    const {nativeRandom, nativeUnit, nativeColorAtTime, nativeFrame, nativeStep: dt, nativeStepRate} = particles;
    const {evaluate} = motion;
    const salted = (word, salt) => nativeUnit(nativeRandom((word + salt) >>> 0)());
    const basisAngle = f32(f32(row.shape.angle * f32(Math.PI / 180)) * .15915493667125702);
    const coneX = coneCos(f32(basisAngle - .25)), coneZ = coneCos(basisAngle);
    const maxFrame = 2 + Math.ceil(row.lifetime[1] * nativeStepRate);
    const normalDamping = damping(dt);
    const lifeSources = row.lifeColors.map(keys => ({start: white, keys}));
    const initial = [];
    const checkpoints = [];
    let frame = 0, active = [];

    function damping(step) {
      return f32(1 - f32(Math.pow(f32(1 - row.clamp.dampen), f32(step * 30))));
    }

    function birth() {
      const draw = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const shapeDraw = Array.from({length: 4}, (_, lane) => nativeRandom((seed + 367 * lane) >>> 0));
      const arc = f32(f32(row.shape.arc * f32(Math.PI / 180)) * .15915493667125702);
      const firstStep = f32(dt * birthBias);
      const firstDamping = damping(firstStep);
      for (let index = 0; index < row.capacity; index++) {
        const random = draw[index % 4], shape = shapeDraw[index % 4];
        const word = random();
        const life = lerp(row.lifetime[0], row.lifetime[1], nativeUnit(random()));
        const size = lerp(row.size[0], row.size[1], nativeUnit(random()));
        random(); // The fixed rotation still reserves the fourth lane word.
        random(); // The fixed starting color reserves the fifth lane word.
        const speed = lerp(row.speed[0], row.speed[1], salted(word, speedSalt));
        const turns = f32(arc * nativeUnit(shape()));
        const weight = nativeUnit(shape());
        const radial = f32(Math.sqrt(f32(f32(1 - weight) + f32(f32(.001) * weight))));
        const x = f32(coneCos(turns) * radial), y = f32(coneCos(f32(turns - .25)) * radial);
        const localX = f32(coneX * x), localY = f32(coneX * y);
        const square = f32(f32(localX * localX) + f32(f32(localY * localY) + f32(coneZ * coneZ)));
        const inverse = f32(1 / Math.sqrt(square));
        const dx = -f32(localX * inverse), dy = f32(coneZ * inverse), dz = -f32(localY * inverse);
        const depth = f32(row.shape.length * nativeUnit(shape()));
        const particle = {
          index, x: f32(f32(-x * row.shape.radius) + f32(dx * depth)), y: f32(dy * depth),
          z: f32(f32(-y * row.shape.radius) + f32(dz * depth)),
          vx: f32(dx * speed), vy: f32(dy * speed), vz: f32(dz * speed), phase: 0,
        };
        initial.push({
          size, life: f32(1 / life), gravity: lerp(row.gravity[0], row.gravity[1], salted(word, gravitySalt)),
          sizeWeight: salted(word, sizeSalt), colorWeight: Math.trunc(f32(salted(word, colorSalt) * 255)),
        });
        advance(particle, firstStep, firstDamping);
        active.push(particle);
      }
    }

    function advance(particle, step, damp) {
      const {life, gravity} = initial[particle.index];
      let {vx, vy, vz} = particle;
      vy = f32(vy + f32(f32(f32(-9.81) * step) * gravity));
      const squared = f32(f32(vx * vx) + f32(f32(vy * vy) + f32(vz * vz)));
      const reciprocal = f32(1 / Math.sqrt(squared)), speed = f32(squared * reciprocal);
      if (speed > row.clamp.limit) {
        const target = lerp(speed, row.clamp.limit, damp);
        vx = f32(f32(vx * reciprocal) * target);
        vy = f32(f32(vy * reciprocal) * target);
        vz = f32(f32(vz * reciprocal) * target);
      }
      particle.vx = vx;
      particle.vy = vy;
      particle.vz = vz;
      particle.x = f32(particle.x + f32(vx * step));
      particle.y = f32(particle.y + f32(vy * step));
      particle.z = f32(particle.z + f32(vz * step));
      particle.phase = f32(particle.phase + f32(f32(step * 100) * life));
    }

    function cull() {
      // Native SIMD culling replaces expired slots from the end of the list.
      for (let first = 0; first < active.length;) {
        let removed = false;
        for (let index = Math.min(first + 3, active.length - 1); index >= first; index--) {
          if (active[index].phase <= 100) continue;
          const tail = active.pop();
          if (index < active.length) active[index] = tail;
          removed = true;
        }
        if (!removed) first += 4;
      }
    }

    function save() {
      const state = new Float32Array(active.length * stateSize);
      for (const [slot, {index,x,y,z,vx,vy,vz,phase}] of active.entries()) {
        state.set([index, x, y, z, vx, vy, vz, phase], slot * stateSize);
      }
      checkpoints[Math.floor(frame / checkpointFrames)] = state;
    }

    function restore(state, target) {
      active = [];
      for (let i = 0; i < state.length; i += stateSize) {
        active.push({index: state[i], x: state[i+1], y: state[i+2], z: state[i+3],
          vx: state[i+4], vy: state[i+5], vz: state[i+6], phase: state[i+7]});
      }
      frame = target;
    }

    return {
      sample(elapsed, fps, emit) {
        const target = nativeFrame(elapsed, fps);
        if (target < 1 || target > maxFrame) return;
        if (frame === 0) {
          birth();
          frame = 1;
          save();
        }
        const checkpoint = Math.min(checkpoints.length - 1, Math.floor(target / checkpointFrames));
        const storedFrame = checkpoint ? checkpoint * checkpointFrames : 1;
        if (frame > target || frame < storedFrame) restore(checkpoints[checkpoint], storedFrame);
        while (frame < target) {
          for (const particle of active) advance(particle, dt, normalDamping);
          cull();
          if (++frame % checkpointFrames === 0 && frame / checkpointFrames >= checkpoints.length) save();
        }
        for (const {index, x, y, z, vx, vy, vz, phase} of active) {
          const u = f32(phase * fraction), {size, sizeWeight, colorWeight} = initial[index];
          const a = f32(evaluate(row.sizeCurves[0], u)), b = f32(evaluate(row.sizeCurves[1], u));
          const width = f32(size * Math.max(0, lerp(a, b, sizeWeight)));
          const low = nativeColorAtTime(lifeSources[0], u), high = nativeColorAtTime(lifeSources[1], u);
          const rgba = low.map((value, index) => {
            const from = Math.round(value * 255), to = Math.round(high[index] * 255);
            return from + ((128 + colorWeight * (to - from)) >> 8);
          });
          emit(x, y, z, vx, vy, vz, width, 0, ...rgba);
        }
      },
    };
  }

  global.MVStudioSparksASimulation = {create};
})(typeof window !== "undefined" ? window : globalThis);
