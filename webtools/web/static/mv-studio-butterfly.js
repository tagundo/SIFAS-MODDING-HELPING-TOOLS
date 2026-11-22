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
  const f32 = Math.fround;
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
    return {mesh, uniforms, stream, source, clip, finale, billboards: []};
  }

  function checkedMaterial(material, blend) {
    return material?.queue === 3010 && material.cull === 0 && material.blend === blend &&
      material.premultiply === false && vector(material.tint, 4, 8);
  }

  function checkedBillboard(row) {
    return vector(row?.position, 3, 1) && vector(row.uv, 4, 1);
  }

  function checkedGlow({source, finale}) {
    const glow = source.glow;
    return glow?.profile === (finale ? "finale" : "opening") &&
      glow.activation === (finale ? Math.fround(5 + 5 / 60) : 0) && glow.activation <= source.animation.duration &&
      glow.maxViewportWidth === (finale ? 1 : .5) && checkedBillboard(glow) &&
      checkedMaterial(glow.material, "add") && glow.uv.every(value => value === .5);
  }

  function checkedShine({source, finale}) {
    const row = source.shine;
    return !finale && row?.profile === "opening" && row.maxViewportWidth === .5 && checkedBillboard(row) &&
      checkedMaterial(row.material, "add") &&
      row.uv[0] === .25 && row.uv[1] === .25 && row.uv[2] === .75 && row.uv[3] === 0;
  }

  function checkedDust({source, finale}) {
    const row = source.dust;
    return finale && row?.profile === "finale" && row.activation === f32(5 + 25 / 60) &&
      row.activation <= source.animation.duration && row.maxViewportWidth === f32(.12) && checkedBillboard(row) &&
      row.uv[0] === .25 && row.uv[1] === .25 && row.uv[2] === 0 && row.uv[3] === 0 &&
      Array.isArray(row.emitters) && row.emitters.length === 2 &&
      ["add", "alpha"].every(role => checkedMaterial(row.emitters.find(emitter => emitter?.role === role)?.material, role));
  }

  async function prepareBillboards(T, entries, levels, title) {
    const renderer = global.MVStudioDisplayLights, glowSimulation = global.MVStudioButterflyGlowSimulation;
    const shineSimulation = global.MVStudioButterflyShineSimulation;
    const dustSimulation = global.MVStudioButterflyDustSimulation;
    if (!renderer || !title.validMipChain(levels) || levels[0].width !== 256) return null;
    const glows = glowSimulation ? entries.filter(checkedGlow) : [];
    const shine = shineSimulation && entries.find(checkedShine);
    const dust = dustSimulation && entries.find(checkedDust);
    if (!glows.length && !shine && !dust) return null;
    let texture;
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), levels);
    } catch { return null; }
    function make(entry, name, row, capacity, material = row.material, columns = 1) {
      name = `${entry.mesh.name} ${name}`;
      const draw = renderer.localBillboards(T, {texture, rotation: new T.Quaternion(), capacity,
        maxViewportWidth: row.maxViewportWidth, atlas: row.uv, additive: material.blend === "add", viewAligned: true,
        tint: material.tint, columns, name});
      draw.mesh.name = name;
      draw.mesh.renderOrder = material.queue;
      draw.mesh.material.stencilFunc = T.AlwaysStencilFunc;
      const billboard = {...draw, row};
      entry.billboards.push(billboard);
      return billboard;
    }
    for (const entry of glows) {
      const row = entry.source.glow;
      const stream = glowSimulation.create(row.profile);
      if (stream) {
        entry.glow = make(entry, "glow", row, 1);
        entry.glow.stream = stream;
      }
    }
    if (shine) {
      // The short initial burst overlaps up to fifteen continuously emitted particles.
      const row = shine.source.shine;
      const draw = make(shine, "shine", row, 32);
      draw.createStream = positionAt => shineSimulation.create(row.profile, positionAt, row);
    }
    if (dust) {
      const row = dust.source.dust;
      const activationClock = {row};
      for (const {role, material} of row.emitters) {
        const draw = make(dust, `dust ${role}`, row, 60, material, 4);
        draw.activationClock = activationClock;
        draw.bounds = new T.Box3();
        draw.sortCenter = new T.Vector3();
        draw.createStream = positionAt => dustSimulation.create(role, positionAt, row);
      }
      if (dust.glow) dust.glow.sortCenter = new T.Vector3();
    }
    return texture;
  }

  function updateWorldBillboard(draw, animation, clip, motion, cueStart, start, fps, elapsed, offset) {
    if (draw.cueStart !== cueStart || draw.fps !== fps ||
        offset.some((value, axis) => value !== draw.offset?.[axis])) {
      draw.cueStart = cueStart;
      draw.fps = fps;
      draw.offset = offset;
      const [sx, sy, sz] = draw.row.position;
      draw.stream = draw.createStream(index => {
        const stamp = motion.sampleTime(clip, (start + index) / fps - cueStart);
        const [x, y, z] = animation.curves.map(curve => motion.evaluate(curve, stamp));
        // The decoder already reflects the emitter's local X. Record the
        // Animator pose at birth so the emitted particles stay in world space.
        return [f32(f32(offset[0] - f32(x)) + sx), f32(f32(offset[1] + f32(y)) + sy),
          f32(f32(offset[2] + f32(z)) + sz)];
      });
    }
    let count = 0;
    draw.bounds?.makeEmpty();
    draw.stream?.sample(elapsed, fps, (x, y, z, size, r, g, b, a, tile = 0) => {
      draw.bounds?.expandByPoint(draw.sortCenter.set(x, y, z));
      if (!(size > 0) || !a || count >= draw.centers.count) return;
      draw.centers.setXYZW(count, x, y, z, tile);
      draw.sizes.setXY(count, size, size);
      draw.colors.setXYZW(count++, r, g, b, a);
    });
    draw.bounds?.getCenter(draw.sortCenter);
    if (count) draw.centers.needsUpdate = draw.sizes.needsUpdate = draw.colors.needsUpdate = true;
    draw.mesh.geometry.instanceCount = count;
    draw.mesh.visible = count > 0;
  }

  function activationFrame(clock, clip, motion, cueStart, firstFrame, fps) {
    if (!clock.row.activation) return firstFrame;
    if (clock.cueStart !== cueStart || clock.fps !== fps) {
      clock.cueStart = cueStart;
      clock.fps = fps;
      let left = firstFrame, right = Math.ceil((cueStart + clip.duration) * fps);
      while (left < right) {
        const frame = (left + right) >>> 1;
        if (motion.sampleTime(clip, frame / fps - cueStart) >= clock.row.activation) right = frame;
        else left = frame + 1;
      }
      clock.firstFrame = left;
    }
    return clock.firstFrame;
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
    const billboardTexture = await prepareBillboards(T, entries, source.glowTexture, title);
    for (const {mesh, billboards} of entries) {
      root.add(mesh);
      for (const draw of billboards) root.add(draw.mesh);
    }
    const sortable = entries.find(entry => entry.finale)?.billboards.filter(draw => draw.sortCenter) || [];
    const eye = new T.Vector3(), scratch = new T.Vector3();
    // Equal-distance dust lanes use the order of their authored children.
    sortable.forEach((draw, index) => { draw.order = draw.bounds ? index : sortable.length; });
    let tracks, disposed = false;
    return {
      billboardAtlas: billboardTexture && {texture: billboardTexture, levels: source.glowTexture},
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
        for (const {mesh, uniforms, stream, source, track, clip, finale, glow, billboards} of entries) {
          mesh.visible = false;
          for (const draw of billboards) {
            draw.mesh.visible = false;
            draw.mesh.geometry.instanceCount = 0;
          }
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
          for (const draw of billboards) {
            if (!draw.createStream) continue;
            const epoch = draw.activationClock ? activationFrame(draw.activationClock, clip, motion, event.start, start, fps) : start;
            if (frame >= epoch) updateWorldBillboard(draw, source.animation, clip, motion, event.start, epoch, fps, (frame - epoch + 1) / fps, offset);
          }
          const drift = stream.sample(elapsed, fps);
          const light = glow && glow.stream.sample((frame - activationFrame(glow, clip, motion, event.start, start, fps) + 1) / fps, fps);
          if (!drift && !light) continue;
          const stamp = motion.sampleTime(clip, stageTime - event.start);
          const [x, y, z] = source.animation.curves.map(curve => motion.evaluate(curve, stamp));
          if (light) {
            // The original emitter is attached to the Animator's ctrl node.
            // The principal particle's drift and shader motion are independent.
            const [gx, gy, gz] = glow.row.position;
            glow.centers.setXYZW(0, -x + offset[0] - gx, y + offset[1] + gy, z + offset[2] + gz, 0);
            glow.sortCenter?.fromArray(glow.centers.array);
            glow.sizes.setXY(0, light.size, light.size);
            glow.colors.setXYZW(0, ...light.rgba);
            glow.centers.needsUpdate = glow.sizes.needsUpdate = glow.colors.needsUpdate = true;
            glow.mesh.geometry.instanceCount = 1;
            glow.mesh.visible = true;
          }
          if (!drift) continue;
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
      sort(camera) {
        if (disposed || !sortable.length) return;
        const visible = sortable.filter(draw => draw.mesh.visible);
        if (!visible.length) return;
        camera.updateMatrixWorld();
        root.updateWorldMatrix(true, false);
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const draw of visible) {
          scratch.copy(draw.sortCenter).applyMatrix4(root.matrixWorld);
          draw.distance = camera.isOrthographicCamera ? f32(-scratch.applyMatrix4(camera.matrixWorldInverse).z) :
            f32(eye.distanceToSquared(scratch));
        }
        // The world-space dust sorts by the center of its particle bounds.
        // The attached glow sorts by its own center within that same queue.
        visible.sort((a, b) => b.distance - a.distance || a.order - b.order);
        visible.forEach(({mesh}, rank) => { mesh.renderOrder = 3010 + rank * .01; });
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {mesh, uniforms, billboards} of entries) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
          uniforms.uTexture.value.dispose();
          for (const draw of billboards) {
            root.remove(draw.mesh);
            draw.mesh.geometry.dispose();
            draw.mesh.material.dispose();
          }
        }
        billboardTexture?.dispose();
      },
    };
  }

  global.MVStudioButterfly = {apply};
})(typeof window !== "undefined" ? window : globalThis);
