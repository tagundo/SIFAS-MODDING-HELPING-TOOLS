(function (global) {
  "use strict";

  // The original does not overwrite the particle seed. Use the serialized
  // cue seed for a reproducible preview when scrubbing or reopening a project.
  const previewSeed = 1136;
  const vertexShader = `
    uniform vec3 uCenter;
    uniform vec3 uVelocity;
    uniform float uSize;
    uniform float uTime;
    uniform vec4 uRandom;
    uniform vec4 uFlap;
    uniform vec4 uRandomMove;
    uniform vec4 uRandomUp;
    varying vec2 vTexture;

    float variation(float seed, float phase) {
      return sin(seed * 87034.0 + phase) + .5 * sin(seed * 174068.0 + phase) +
        .25 * sin(seed * 348136.0 + phase);
    }

    void main() {
      float movePhase = uTime * uRandomMove.w;
      float upPhase = uTime * uRandomUp.w;
      vec3 center = uCenter + uRandomMove.xyz * vec3(variation(uRandom.y, movePhase),
        variation(uRandom.z, movePhase), variation(uRandom.w, movePhase));
      vec3 up = normalize(vec3(uRandomUp.x * variation(uRandom.x, upPhase), 1.0,
        uRandomUp.z * variation(uRandom.y, upPhase)));
      vec3 forward = normalize(uVelocity);
      vec3 right = normalize(cross(forward, up));
      vec3 normal = normalize(cross(right, forward));
      // The mesh importer already reflected X. Solve the authored wing motion
      // in the source basis and reflect the deformed position back at the end.
      vec3 local = vec3(-position.x, position.yz) * uSize;
      float angle = sign(local.x) * uFlap.y * (1.0 + uFlap.z * (uRandom.x - 1.0)) *
        sin((uTime + uFlap.w * uRandom.z) * uFlap.x);
      float s = sin(angle), c = cos(angle);
      vec3 world = center + right * (c * local.x + s * local.y) +
        normal * (-s * local.x + c * local.y) + forward * local.z;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(-world.x, world.yz, 1.0);
      vTexture = uv;
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uColor;
    uniform vec4 uAmbient;
    uniform vec4 uTint;
    varying vec2 vTexture;
    void main() {
      vec4 sampleColor = texture2D(uTexture, vTexture) * uColor;
      vec3 color = mix(sampleColor.rgb, uAmbient.rgb, uAmbient.a) * mix(vec3(1.0), uTint.rgb, uTint.a);
      gl_FragColor = vec4(color, sampleColor.a);
    }
  `;

  const vector = (values, count, bound) => Array.isArray(values) && values.length === count &&
    values.every(value => Number.isFinite(value) && Math.abs(value) <= bound);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const timelineTick = time => Math.trunc(time / 1e-12 + .5);
  function checked(source, title, motion, finale) {
    if (source?.schema !== 1 || !id(source.trackId) || !id(source.eventId) || !title.validMipChain(source.texture) ||
        source.texture[0].width !== 512) return false;
    const {geometry, animation, particle, material} = source;
    const bounded = curve => title.boundedCurve(curve, motion.validCurve);
    return Array.isArray(geometry?.positions) && geometry.positions.length === 6 &&
      geometry.positions.every(row => vector(row, 3, .01)) && Array.isArray(geometry.uv) && geometry.uv.length === 6 &&
      geometry.uv.every(row => vector(row, 2, 1) && row.every(value => value >= 0)) &&
      Array.isArray(geometry.indices) && geometry.indices.length === 12 &&
      geometry.indices.every(value => Number.isInteger(value) && value >= 0 && value < 6) &&
      Number.isFinite(animation?.duration) && animation.duration > 0 && animation.duration <= 15 &&
      Array.isArray(animation.curves) && animation.curves.length === 3 &&
      animation.curves.every(bounded) &&
      (!finale || (Array.isArray(animation.tintCurves) && animation.tintCurves.length === 4 && animation.tintCurves.every(bounded))) &&
      particle?.birth === 0 && particle.lifetime === (finale ? Math.fround(5.55) : 30) && particle.size === (finale ? 9 : 6) &&
      vector(particle.velocity, 3, .01) && Math.hypot(...particle.velocity) > .0001 && vector(particle.color, 4, 1) &&
      vector(material?.randomMove, 4, 16) && vector(material.randomUp, 4, 16) &&
      vector(material.ambient, 4, 1) && vector(material.tint, 4, 8) &&
      vector([material.flapSpeed, material.flapIntensity, material.randomFlapIntensity, material.randomFlapDelay], 4, 64);
  }

  async function prepare(T, source, finale, title, motion, simulation) {
    if (!checked(source, title, motion, finale)) return null;
    const stream = simulation.create(previewSeed, finale ? "finale" : undefined);
    if (!stream) return null;
    let texture;
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch { return null; }
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(source.geometry.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(source.geometry.uv.flat(), 2));
    geometry.setIndex(source.geometry.indices);
    const {particle, material: fields, animation} = source;
    const uniforms = {
      uTexture: {value: texture}, uCenter: {value: new T.Vector3()}, uVelocity: {value: new T.Vector3().fromArray(particle.velocity)},
      uSize: {value: particle.size}, uTime: {value: 0}, uRandom: {value: new T.Vector4().fromArray(stream.random)},
      uFlap: {value: new T.Vector4(fields.flapSpeed, fields.flapIntensity, fields.randomFlapIntensity, fields.randomFlapDelay)},
      uRandomMove: {value: new T.Vector4().fromArray(fields.randomMove)}, uRandomUp: {value: new T.Vector4().fromArray(fields.randomUp)},
      uColor: {value: new T.Vector4().fromArray(particle.color)}, uAmbient: {value: new T.Vector4().fromArray(fields.ambient)},
      uTint: {value: new T.Vector4().fromArray(fields.tint)},
    };
    const name = finale ? "Native Aion finale butterfly" : "Native Aion butterfly";
    const material = new T.ShaderMaterial({
      name, vertexShader, fragmentShader, uniforms, transparent: true,
      toneMapped: false, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, side: T.DoubleSide,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = name;
    mesh.renderOrder = 3000;
    mesh.frustumCulled = false; // The vertex shader places the wing in the animated world position.
    mesh.visible = false;
    const clip = {start: 0, duration: animation.duration, loop: false, sampleTimeF32: true};
    return {mesh, uniforms, stream, source, clip, finale};
  }

  async function apply(T, root, source) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    const simulation = global.MVStudioButterflySimulation;
    if (!source || !title || !motion || !particles || !simulation) return null;
    const prepared = await Promise.all([
      prepare(T, source, false, title, motion, simulation),
      prepare(T, source.finale, true, title, motion, simulation),
    ]);
    const entries = prepared.filter(Boolean);
    if (!entries.length) return null;
    for (const {mesh} of entries) root.add(mesh);
    let tracks, disposed = false;
    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const entry of entries) {
            entry.track = tracks?.find(row => row.id === entry.source.trackId && row.nativeClass === "CustomControlTrack");
          }
        }
        const quality = project?.quality?.values;
        const enabled = quality?.stage_control !== false;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        const frame = Math.floor(time * fps + 1e-9), tick = timelineTick(time);
        for (const {mesh, uniforms, stream, source, track, clip, finale} of entries) {
          mesh.visible = false;
          const event = enabled && !track?.muted && track?.events.find(row => row.id === source.eventId);
          if (!event) continue;
          // Unity Timeline queries its half-open clip intervals in 1 ps
          // ticks. Preserve the cue edge even when its serialized double is
          // slightly later than the matching display timestamp.
          const firstTick = timelineTick(event.start);
          if (tick < firstTick || tick >= timelineTick(event.start + event.duration)) continue;
          const stageTime = Math.max(time, event.start);
          const offset = particles.activeOffset(event, stageTime);
          if (!offset) continue;
          const firstFrame = Math.ceil(event.start * fps);
          const start = timelineTick((firstFrame - 1) / fps) === firstTick ? firstFrame - 1 : firstFrame;
          const elapsed = (frame - start + 1) / fps;
          const drift = stream.sample(elapsed, fps);
          if (!drift) continue;
          const stamp = motion.sampleTime(clip, stageTime - event.start);
          const [x, y, z] = source.animation.curves.map(curve => motion.evaluate(curve, stamp));
          uniforms.uCenter.value.set(x - offset[0] - drift[0], y + offset[1] + drift[1], z + offset[2] + drift[2]);
          if (finale) {
            const appearance = stream.appearance(elapsed, fps);
            if (!appearance || !appearance.alpha) continue;
            uniforms.uSize.value = appearance.size;
            uniforms.uColor.value.w = source.particle.color[3] * appearance.alpha / 255;
            uniforms.uTint.value.fromArray(source.animation.tintCurves.map(curve => motion.evaluate(curve, stamp)));
          }
          // _AUTO_PLAY_ON uses the scene clock in the original shader.
          uniforms.uTime.value = time;
          mesh.visible = true;
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {mesh, uniforms} of entries) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
          uniforms.uTexture.value.dispose();
        }
      },
    };
  }

  global.MVStudioButterfly = {apply};
})(typeof window !== "undefined" ? window : globalThis);
