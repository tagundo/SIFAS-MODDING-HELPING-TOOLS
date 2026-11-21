(function (global) {
  "use strict";

  const vertexShader = [
    "uniform float uMaxViewportWidth;",
    "attribute vec3 rollAndSize;",
    "attribute vec4 starColor;",
    "varying vec2 vStarUV;",
    "varying vec4 vStarColor;",
    "void main() {",
    "  vec4 center = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);",
    "  float depth = projectionMatrix[2].w == 0.0 ? 1.0 : max(0.0, -center.z);",
    "  float width = 2.0 * depth / abs(projectionMatrix[0].x);",
    "  float size = min(rollAndSize.z, uMaxViewportWidth * width);",
    "  vec2 plane = mat2(rollAndSize.x, rollAndSize.y, -rollAndSize.y, rollAndSize.x) * position.xy;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(plane * size, 0.0, 1.0);",
    "  vStarUV = uv;",
    "  vStarColor = starColor;",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "varying vec2 vStarUV;",
    "varying vec4 vStarColor;",
    "void main() { gl_FragColor = texture2D(uTexture, vStarUV) * vStarColor; }"
  ].join("\n");

  const inRange = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
  const vector = (value, length, min, max) => Array.isArray(value) && value.length === length &&
    value.every(item => inRange(item, min, max));
  const white = [255, 255, 255, 255];

  function validPalette(entries, components) {
    return Array.isArray(entries) && entries.length > 0 && entries.length <= 8 &&
      entries.every((row, i) => Array.isArray(row) && row.length === components + 1 &&
        Number.isInteger(row[0]) && inRange(row[0], 0, 65535) && (i === 0 || row[0] > entries[i - 1][0]) &&
        row.slice(1).every(byte => Number.isInteger(byte) && inRange(byte, 0, 255)));
  }

  function checked(data, title, motion, particles) {
    return vector(data.position, 3, -100, 100) && Number.isInteger(data.seed) && inRange(data.seed, 0, 0xffffffff) &&
      data.size === 2 && data.lifetime === 1 && data.rate === 2 && data.cycle === 5 &&
      vector(data.rollRange, 2, -7, 7) && data.rollRange[0] <= data.rollRange[1] &&
      vector(data.uv, 4, 0, 1) && data.uv[0] === .25 && data.uv[1] === .25 &&
      data.uv[2] === 0 && data.uv[3] === .25 && data.maxViewportWidth === .5 &&
      validPalette(data.palette?.rgb, 3) && validPalette(data.palette?.alpha, 1) &&
      particles.validNativeColor({start: white, keys: data.colorKeys}) &&
      title.boundedCurve(data.sizeCurve, motion.validCurve) && inRange(data.sizePeriod, 0, 1) &&
      title.validMipChain(data.texture) && data.texture[0].width === 512;
  }

  function birthStream(data, particles) {
    const draw = particles.nativeRandom(data.seed), f32 = Math.fround;
    const [min, max] = data.rollRange;
    let regular = 1, burst = 0;
    const records = [];
    function paletteAt(entries, time) {
      return entries.find(row => row[0] >= time) || entries[entries.length - 1];
    }
    return {
      records,
      through(time) {
        for (;;) {
          const nextRegular = regular / data.rate, nextBurst = burst * data.cycle;
          const birth = Math.min(nextRegular, nextBurst);
          if (birth > time) return;
          // A particle due at the loop boundary is emitted by the preceding
          // interval before the new cycle's zero-time burst.
          if (nextRegular <= nextBurst) regular++;
          else burst++;
          draw(); // stored particle seed
          draw(); // lifetime lane
          draw(); // size lane
          const roll = f32(min + f32(f32(max - min) * particles.nativeUnit(draw())));
          const stamp = f32(particles.nativeUnit(draw()) * 65535);
          const rgb = paletteAt(data.palette.rgb, stamp);
          const alpha = paletteAt(data.palette.alpha, stamp);
          records.push({birth, cosine: Math.cos(roll), sine: Math.sin(roll),
            color: {start: [rgb[1], rgb[2], rgb[3], alpha[1]], keys: data.colorKeys}});
        }
      },
    };
  }

  function lastBirth(records, time) {
    let min = 0, max = records.length;
    while (min < max) {
      const middle = (min + max) >> 1;
      if (records[middle].birth <= time) min = middle + 1;
      else max = middle;
    }
    return min - 1;
  }

  async function apply(T, root, data) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    if (!root?.isObject3D || !data || !title || !motion || !particles || !checked(data, title, motion, particles)) return null;
    let texture;
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), data.texture);
    } catch {
      return null;
    }
    const [sx, sy, x, y] = data.uv;
    const geometry = new T.InstancedBufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute([
      .5,.5,0, -.5,.5,0, -.5,-.5,0, .5,-.5,0,
    ], 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute([x,y, x+sx,y, x+sx,y+sy, x,y+sy], 2));
    geometry.setIndex([0,2,1,0,3,2]);
    const capacity = Math.ceil(data.lifetime * data.rate) + 2;
    const shapes = new T.InstancedBufferAttribute(new Float32Array(capacity * 3), 3).setUsage(T.DynamicDrawUsage);
    const colors = new T.InstancedBufferAttribute(new Float32Array(capacity * 4), 4).setUsage(T.DynamicDrawUsage);
    geometry.setAttribute("rollAndSize", shapes);
    geometry.setAttribute("starColor", colors);
    geometry.instanceCount = 0;
    const material = new T.ShaderMaterial({
      name: "Native stage center stars", vertexShader, fragmentShader, transparent: true,
      side: T.DoubleSide, toneMapped: false, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uMaxViewportWidth: {value: data.maxViewportWidth}},
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = "Native stage center stars";
    // The native background's sort bias exceeds the stars' by 4 units and
    // their bounds centers are .255 units apart. The background draws first
    // within queue 2900 for either camera type.
    mesh.renderOrder = 2900.01;
    mesh.position.fromArray(data.position);
    mesh.frustumCulled = false;
    mesh.visible = false;
    root.add(mesh);
    const stream = birthStream(data, particles);
    let disposed = false;
    return {
      mesh, texture,
      update(time) {
        if (disposed) return;
        if (!inRange(time, 0, 3600)) {
          mesh.visible = false;
          return;
        }
        stream.through(time);
        let count = 0;
        for (let index = lastBirth(stream.records, time); index >= 0; index--) {
          const entry = stream.records[index], age = time - entry.birth;
          if (age >= data.lifetime) break;
          const ratio = age / data.lifetime, f32 = Math.fround;
          const normalized = f32(f32(f32(ratio) * 100) * f32(.01));
          const phase = data.sizePeriod > 0 && normalized > data.sizePeriod ?
            f32(normalized % data.sizePeriod) : normalized;
          const size = f32(data.size * f32(motion.evaluate(data.sizeCurve, phase)));
          const color = particles.nativeColor(entry.color, ratio);
          if (!(size > 0) || !(color[3] > 0)) continue;
          shapes.setXYZ(count, entry.cosine, entry.sine, size);
          colors.setXYZW(count, ...color);
          count++;
        }
        geometry.instanceCount = count;
        shapes.needsUpdate = true;
        colors.needsUpdate = true;
        mesh.visible = count > 0;
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(mesh);
        geometry.dispose();
        texture.dispose();
        material.dispose();
      },
    };
  }

  global.MVStudioCenterStars = {apply};
})(typeof window !== "undefined" ? window : globalThis);
