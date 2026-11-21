(function (global) {
  "use strict";

  const vertexShader = [
    "uniform float uMaxViewportWidth;",
    "attribute vec3 particlePosition;",
    "attribute float particleSize;",
    "varying vec2 vShine;",
    "void main() {",
    "  vec4 center = modelViewMatrix * vec4(particlePosition, 1.0);",
    "  float depth = projectionMatrix[2].w == 0.0 ? 1.0 : max(0.0, -center.z);",
    "  float width = 2.0 * depth / abs(projectionMatrix[0].x);",
    "  float size = min(particleSize, uMaxViewportWidth * width);",
    "  center.xy += position.xy * size;",
    "  gl_Position = projectionMatrix * center;",
    "  vShine = uv;",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "varying vec2 vShine;",
    "void main() { gl_FragColor = texture2D(uTexture, vShine); }"
  ].join("\n");

  const durationLimit = 60;
  const inRange = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
  const vector = (value, length, min, max) => Array.isArray(value) && value.length === length &&
    value.every(item => inRange(item, min, max));
  const range = (value, max) => vector(value, 2, .01, max) && value[0] <= value[1];
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function validCue(cue, title, curves) {
    return id(cue?.trackId) && id(cue.eventId) && cue.rate === 10 && cue.cycle === 5 &&
      cue.maxViewportWidth === .5 && vector(cue.position, 3, -100, 100) &&
      vector(cue.parent?.position, 3, -100, 100) && vector(cue.parent.scale, 3, .01, 10) &&
      vector(cue.parent.rotation, 4, 0, 1) && cue.parent.rotation[3] === 1 &&
      cue.parent.rotation.slice(0, 3).every(value => value === 0) &&
      vector(cue.box, 3, .01, 10) && inRange(cue.shapeYaw, -2 * Math.PI, 2 * Math.PI) &&
      range(cue.size, 1) && range(cue.speed, 4) && range(cue.lifetime, 20) &&
      Array.isArray(cue.sizeCurves) && cue.sizeCurves.length === 2 &&
      cue.sizeCurves.every(curve => title.boundedCurve(curve, curves.validCurve));
  }

  function spawn(cue) {
    const {autoSeed, nativeRandom, nativeUnit} = global.MVStudioStageParticles;
    const seed = autoSeed(), initial = nativeRandom(seed), shape = nativeRandom(seed);
    const f32 = Math.fround;
    const lerp = ([min, max], word) => f32(min + f32(f32(max - min) * nativeUnit(word)));
    const sin = f32(Math.sin(cue.shapeYaw)), cos = f32(Math.cos(cue.shapeYaw));
    const prewarm = cue.lifetime[1], count = Math.ceil((prewarm + durationLimit) * cue.rate);
    const records = [];
    // Unity prewarms through the maximum start lifetime. Sample the constant
    // emission rate on its ideal time grid so edits and seeks stay repeatable.
    for (let index = 0; index < count; index++) {
      const particleSeed = initial(), life = lerp(cue.lifetime, initial()), size = lerp(cue.size, initial());
      initial();
      initial();
      const speed = lerp(cue.speed, nativeRandom(particleSeed + 0x96aa4de3)());
      const weight = nativeUnit(nativeRandom(particleSeed + 0x8d2c8431)());
      const [x, y, z] = cue.box.map(axis => f32(f32(nativeUnit(shape()) - .5) * axis));
      records.push({
        birth: (index + 1) / cue.rate - prewarm, life, size, weight,
        x: f32(-f32(f32(cos * x) + f32(sin * z))), y,
        z: f32(f32(cos * z) - f32(sin * x)), dx: f32(-sin * speed), dz: f32(cos * speed),
      });
    }
    return records;
  }

  function makeBatch(T, cue, texture) {
    const geometry = new T.InstancedBufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute([
      -.5,.5,0, .5,.5,0, .5,-.5,0, -.5,-.5,0,
    ], 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute([0,0, 1,0, 1,1, 0,1], 2));
    geometry.setIndex([0,2,1,0,3,2]);
    const capacity = Math.ceil(cue.lifetime[1] * cue.rate) + 1;
    const positions = new T.InstancedBufferAttribute(new Float32Array(capacity * 3), 3).setUsage(T.DynamicDrawUsage);
    const sizes = new T.InstancedBufferAttribute(new Float32Array(capacity), 1).setUsage(T.DynamicDrawUsage);
    geometry.setAttribute("particlePosition", positions);
    geometry.setAttribute("particleSize", sizes);
    geometry.instanceCount = 0;
    const material = new T.ShaderMaterial({
      name: "Native stage ribbon shine", vertexShader, fragmentShader, transparent: true,
      side: T.DoubleSide, toneMapped: false, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uMaxViewportWidth: {value: cue.maxViewportWidth}},
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = "Native stage ribbon shine";
    mesh.renderOrder = 2900;
    mesh.frustumCulled = false;
    mesh.visible = false;
    // Local particle scaling keeps the box, movement and sprite at the leaf
    // scale. Its position still inherits the parent's transform.
    mesh.position.fromArray(cue.parent.position.map((value, axis) =>
      Math.fround(value + Math.fround(cue.position[axis] * cue.parent.scale[axis]))));
    return {cue, mesh, positions, sizes, records: spawn(cue)};
  }

  function updateBatch(batch, elapsed, evaluate) {
    const {cue, mesh, positions, sizes, records} = batch;
    const [small, large] = cue.sizeCurves, f32 = Math.fround;
    let count = 0;
    const first = Math.max(0, Math.floor(elapsed * cue.rate) - 1);
    for (let index = first; index < records.length; index++) {
      const item = records[index], age = elapsed - item.birth;
      if (age < 0) break;
      if (age >= item.life) continue;
      const time = f32(f32(f32(age / item.life) * 100) * f32(.01));
      const min = f32(evaluate(small, time)), max = f32(evaluate(large, time));
      const width = f32(item.size * f32(min + f32(f32(max - min) * item.weight)));
      if (!(width > 0)) continue;
      positions.setXYZ(count, item.x + item.dx * age, item.y, item.z + item.dz * age);
      sizes.setX(count, width);
      count++;
    }
    mesh.geometry.instanceCount = count;
    positions.needsUpdate = true;
    sizes.needsUpdate = true;
  }

  async function apply(T, root, descriptor) {
    const title = global.MVStudioTitle, curves = global.MVStudioStageMotion;
    if (!descriptor || !root?.isObject3D || !title || !curves || !global.MVStudioStageParticles ||
        !title.validMipChain(descriptor.texture) || descriptor.texture[0].width !== 256 ||
        !Array.isArray(descriptor.cues) || !descriptor.cues.length || descriptor.cues.length > 2 ||
        !descriptor.cues.every(cue => validCue(cue, title, curves))) return null;
    const batches = [];
    let texture, tracks, disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {mesh} of batches) {
        root.remove(mesh);
        mesh.material.dispose();
        mesh.geometry.dispose();
      }
      texture?.dispose();
    }
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), descriptor.texture);
      for (const cue of descriptor.cues) {
        const batch = makeBatch(T, cue, texture);
        batches.push(batch);
        root.add(batch.mesh);
      }
    } catch {
      dispose();
      return null;
    }
    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const batch of batches) {
            const matches = (tracks || []).filter(track => track.id === batch.cue.trackId &&
              track.nativeClass === "CustomControlTrack");
            batch.track = matches.length === 1 ? matches[0] : null;
          }
        }
        for (const batch of batches) {
          const event = !batch.track?.muted && batch.track?.events.find(row => row.id === batch.cue.eventId);
          const enabled = project?.quality?.values?.stage_display !== false;
          batch.mesh.visible = Boolean(enabled && title.neutralClip(event) && event.duration <= durationLimit &&
            time >= event.start && time < event.start + event.duration);
          if (batch.mesh.visible) updateBatch(batch, time - event.start, curves.evaluate);
        }
      },
      dispose,
    };
  }

  global.MVStudioRibbonShine = {apply};
})(typeof window !== "undefined" ? window : globalThis);
