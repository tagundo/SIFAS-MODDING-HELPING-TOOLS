(function (global) {
  "use strict";

  const vertexShader = `
    uniform vec3 uAxisX;
    uniform vec3 uAxisY;
    uniform float uMaxWidth;
    attribute vec4 centerAndTile;
    attribute vec2 particleSize;
    attribute vec4 particleColor;
    varying vec2 vParticleUV;
    varying vec4 vParticleColor;
    void main() {
      vec4 center = modelViewMatrix * vec4(centerAndTile.xyz, 1.0);
      float depth = projectionMatrix[3][3] == 1.0 ? 1.0 : -center.z;
      float largerSide = max(particleSize.x, particleSize.y);
      float sideLimit = 2.0 * uMaxWidth * depth / abs(projectionMatrix[0][0]);
      float scale = depth < 0.0 ? 1.0 : min(1.0, sideLimit / largerSide);
      vec3 offset = (uAxisX * (position.x * particleSize.x) + uAxisY * (position.y * particleSize.y)) * scale;
      gl_Position = projectionMatrix * (center + vec4(mat3(modelViewMatrix) * offset, 0.0));
      vParticleUV = vec2(uv.x, (uv.y + centerAndTile.w) * 0.25);
      vParticleColor = particleColor;
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    varying vec2 vParticleUV;
    varying vec4 vParticleColor;
    void main() { gl_FragColor = texture2D(uTexture, vParticleUV) * vParticleColor; }
  `;

  const names = new Set(["light_up", "light_down", "light_left", "light_right", "light_L", "light_R"]);
  const f32 = Math.fround;
  const between = (value, low, high) => Number.isFinite(value) && value >= low && value <= high;
  const vector = (value, length, min, max) => Array.isArray(value) && value.length === length &&
    value.every(number => between(number, min, max));
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function checked(source, title, motion, particles) {
    if (!source || !id(source.trackId) || !id(source.eventId) ||
        !title.validMipChain(source.texture) || source.texture[0].width !== 512 ||
        !Array.isArray(source.emitters) || source.emitters.length !== names.size ||
        new Set(source.emitters.map(row => row?.name)).size !== names.size) return false;
    return source.emitters.every(row => names.has(row?.name) &&
      vector(row.position, 3, -100, 100) && vector(row.rotation, 4, -1, 1) &&
      Math.abs(Math.hypot(...row.rotation) - 1) < 1e-5 && vector(row.particleRotation, 3, -7, 7) &&
      row.lifetime === 4 && row.duration === 50 && (row.speed === 1 || row.speed === -1) &&
      vector(row.size, 2, .01, 8) && row.maxViewportWidth === 2 && row.sortBias === 0 &&
      Array.isArray(row.bursts) && row.bursts.length === (row.speed === 1 ? 1 : 2) &&
      row.bursts.every((burst, index) => vector(burst, 2, 0, 2) &&
        burst[0] === index && burst[1] === row.bursts.length) &&
      between(row.atlasPeriod, .1, .5) && title.boundedCurve(row.atlasCurve, motion.validCurve) &&
      title.boundedCurve(row.sizeCurve, motion.validCurve) && particles.validNativeColor(row.color));
  }

  function useCadence(row, fps) {
    const dt = f32(1 / fps), phaseAges = [], birthTicks = [];
    // The six checked schedules each emit one particle per second. Native
    // bursts compare against their accumulated float32 clock, including at 0.
    let clock = 0, tick = 0;
    for (let burst = 0; burst < row.duration; burst++) {
      do {
        clock = f32(clock + dt);
        tick++;
      } while (clock < burst);
      birthTicks.push(tick);
    }
    const step = f32(f32(dt * 100) / row.lifetime);
    let age = f32(step * f32(1e-6));
    while (age <= 100) {
      phaseAges.push(age);
      age = f32(age + step);
    }
    return {fps, birthTicks: birthTicks.reverse(), phaseAges};
  }

  function makeEmitter(T, row, texture) {
    const geometry = new T.InstancedBufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute([.5,.5,0,-.5,.5,0,-.5,-.5,0,.5,-.5,0], 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute([0,0,1,0,1,1,0,1], 2));
    geometry.setIndex([0,2,1,0,3,2]);
    const capacity = Math.ceil(row.lifetime) + 1;
    const centers = new T.InstancedBufferAttribute(new Float32Array(capacity * 4), 4).setUsage(T.DynamicDrawUsage);
    const sizes = new T.InstancedBufferAttribute(new Float32Array(capacity * 2), 2).setUsage(T.DynamicDrawUsage);
    const colors = new T.InstancedBufferAttribute(new Uint8Array(capacity * 4), 4, true).setUsage(T.DynamicDrawUsage);
    geometry.setAttribute("centerAndTile", centers);
    geometry.setAttribute("particleSize", sizes);
    geometry.setAttribute("particleColor", colors);
    geometry.instanceCount = 0;
    const emitter = new T.Quaternion().fromArray(row.rotation);
    const [x, y, z] = row.particleRotation;
    // The native Local renderer applies the negative initial Z-X-Y angles
    // before the emitter rotation. The stage uses reflected X coordinates.
    const plane = emitter.clone().multiply(new T.Quaternion().setFromEuler(new T.Euler(-x, y, z, "YXZ")));
    const origin = new T.Vector3().fromArray(row.position);
    const velocity = new T.Vector3(0, 0, row.speed).applyQuaternion(emitter);
    const center = origin.clone().addScaledVector(velocity, row.lifetime * 0.5);
    const material = new T.ShaderMaterial({
      name: "Native stage display lights", vertexShader, fragmentShader, transparent: true,
      toneMapped: false, side: T.DoubleSide, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uMaxWidth: {value: row.maxViewportWidth},
        uAxisX: {value: new T.Vector3(1, 0, 0).applyQuaternion(plane)},
        uAxisY: {value: new T.Vector3(0, 1, 0).applyQuaternion(plane)}},
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = `Native stage display ${row.name}`;
    mesh.renderOrder = 2900;
    mesh.matrixAutoUpdate = false;
    mesh.frustumCulled = false;
    mesh.visible = false;
    return {row, mesh, center, origin, velocity, centers, sizes, colors, distance: 0};
  }

  async function apply(T, root, source) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    if (!root?.isObject3D || !title || !motion || !particles || !checked(source, title, motion, particles)) return null;
    let texture;
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }
    const emitters = source.emitters.map(row => makeEmitter(T, row, texture));
    const sorted = emitters.slice();
    emitters.forEach((entry, order) => { entry.order = order; });
    const eye = new T.Vector3(), scratch = new T.Vector3();
    for (const {mesh} of emitters) root.add(mesh);
    let disposed = false, tracks, track, cadence, visible = false;

    function updateEmitter(entry, frame) {
      const {row, mesh, origin, velocity, centers, sizes, colors} = entry;
      let count = 0;
      if (frame !== null) {
        const {birthTicks, phaseAges} = cadence;
        // OldestInFront draws the newest particles first on the same emitter.
        for (const tick of birthTicks) {
          const index = frame - tick;
          if (index < 0) continue;
          if (index >= phaseAges.length) break;
          const u = f32(phaseAges[index] * f32(.01));
          const age = f32(phaseAges[index] * f32(.04));
          const size = f32(motion.evaluate(row.sizeCurve, u));
          const color = particles.nativeColorAtTime(row.color, u);
          if (size <= 0 || color[3] <= 0) continue;
          // The native curve subtracts a rounded whole period before the
          // stepped key lookup. A double-precision remainder shifts edges.
          const phase = u <= row.atlasPeriod ? u :
            f32(u - f32(Math.floor(u / row.atlasPeriod) * row.atlasPeriod));
          const tile = Math.max(0, Math.min(3, Math.floor(f32(4 * motion.evaluate(row.atlasCurve, phase)))));
          centers.setXYZW(count, f32(origin.x + velocity.x * age), f32(origin.y + velocity.y * age),
            f32(origin.z + velocity.z * age), tile);
          sizes.setXY(count, f32(size * row.size[0]), f32(size * row.size[1]));
          colors.setXYZW(count, ...color.map(value => Math.round(value * 255)));
          count++;
        }
      }
      mesh.geometry.instanceCount = count;
      mesh.visible = count > 0;
      if (count) {
        for (const attribute of [centers, sizes, colors]) {
          attribute.updateRange.count = count * attribute.itemSize;
          attribute.needsUpdate = true;
        }
      }
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = (tracks || []).filter(row => row.id === source.trackId && row.nativeClass === "CustomControlTrack");
          track = matches.length === 1 ? matches[0] : null;
        }
        const event = !track?.muted && track?.events.find(row => row.id === source.eventId);
        const active = project?.quality?.values?.stage_display !== false && title.neutralClip(event) &&
          time >= event.start && time < event.start + event.duration;
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        if (active && cadence?.fps !== fps) cadence = useCadence(emitters[0].row, fps);
        const frame = active ? Math.floor((time - event.start) * fps + 1e-9) : null;
        for (const entry of emitters) updateEmitter(entry, frame);
        visible = emitters.some(({mesh}) => mesh.visible);
      },
      sort(camera) {
        if (disposed || !visible) return;
        camera.updateMatrixWorld();
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of sorted) {
          entry.distance = camera.isOrthographicCamera
            ? f32(-scratch.copy(entry.center).applyMatrix4(camera.matrixWorldInverse).z)
            : f32(eye.distanceToSquared(entry.center));
        }
        sorted.sort((a, b) => b.distance - a.distance || a.order - b.order);
        sorted.forEach(({mesh}, rank) => { mesh.renderOrder = 2900 + rank * .01; });
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {mesh} of emitters) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
        texture.dispose();
      },
    };
  }

  global.MVStudioDisplayLights = {apply};
})(typeof window !== "undefined" ? window : globalThis);
