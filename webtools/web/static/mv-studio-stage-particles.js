(function (global) {
  "use strict";

  const vertexShader = [
    "uniform vec4 uTextureST;",
    "#ifdef VIEWPORT_SIZE_LIMIT",
    "uniform float uViewportScale;",
    "#endif",
    "varying vec2 vParticle;",
    "void main() {",
    "  vParticle = uv * uTextureST.xy + uTextureST.zw;",
    "  vec3 vertex = position;",
    "#ifdef VIEWPORT_SIZE_LIMIT",
    "  vertex *= uViewportScale;",
    "#endif",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(vertex, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "varying vec2 vParticle;",
    "void main() {",
    "  vec4 source = texture2D(uTexture, vParticle);",
    "  gl_FragColor = source * uTint;",
    "#ifdef SOURCE_ALPHA",
    "  gl_FragColor *= source.a;",
    "#endif",
    "}"
  ].join("\n");
  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const inRange = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;

  function validGeometry({positions, uv, indices} = {}) {
    return Array.isArray(positions) && positions.length >= 3 && positions.length <= 128 &&
      positions.every(row => vector(row, 3)) && Array.isArray(uv) && uv.length === positions.length &&
      uv.every(row => vector(row, 2)) && Array.isArray(indices) && indices.length > 0 &&
      indices.length <= 768 && indices.length % 3 === 0 &&
      indices.every(index => Number.isInteger(index) && index >= 0 && index < positions.length);
  }

  function activeOffset(event, time) {
    const fields = event?.values;
    if (fields?.playableClass !== "CustomControlClip" || fields.weight !== 1 || fields.timeScale !== 1 ||
        !Number.isFinite(event.start) || !inRange(event.duration, 0.001, 60) ||
        time < event.start || time >= event.start + event.duration ||
        ["easeIn", "easeOut", "blendIn", "blendOut"].some(field => fields[field] > 0) ||
        fields.preExtrapolationMode || fields.postExtrapolationMode) return null;
    const { x, y, z } = fields.offset || {};
    return [x, y, z].every(value => inRange(value, -1000, 1000)) ? [-x, y, z] : null;
  }

  function validNativeColor(source) {
    const {start, keys} = source || {};
    const byte = value => Number.isInteger(value) && value >= 0 && value <= 255;
    return Array.isArray(start) && start.length === 4 && start.every(byte) &&
      Array.isArray(keys) && keys.length > 0 && keys.length <= 16 &&
      keys.every((row, index) => Array.isArray(row) && row.length === 5 && inRange(row[0], 0, 1) &&
        (index === 0 || Math.fround(row[0]) - Math.fround(keys[index - 1][0]) >= Number.EPSILON) &&
        row.slice(1).every(byte));
  }

  function nativeColor(source, normalized) {
    const f32 = Math.fround;
    return nativeColorAtTime(source, f32(f32(f32(normalized) * 100) * f32(.01)));
  }

  function nativeColorAtTime({start, keys}, time) {
    // Unity's particle ColorModule interpolates its packed byte gradient and
    // multiplies the resulting bytes by the generated starting color.
    const f32 = Math.fround;
    const next = keys.findIndex(row => row[0] > time);
    const right = keys[next < 0 ? keys.length - 1 : next];
    const left = next > 0 ? keys[next - 1] : right;
    const blend = left === right ? 0 : Math.trunc(f32(f32(f32(time - left[0]) *
      f32(1 / f32(right[0] - left[0]))) * 255));
    return start.map((value, index) => {
      const from = left[index + 1], to = right[index + 1];
      const gradient = from + ((128 + blend * (to - from)) >> 8);
      return Math.floor((value * gradient + 127) / 255) / 255;
    });
  }

  const nativeStepRate = 60;
  const nativeStep = Math.fround(1 / nativeStepRate);

  function nativeFrame(elapsed, fps) {
    if (!Number.isFinite(elapsed) || elapsed < 0 || (fps !== 30 && fps !== 60)) return -1;
    // The stock TimeManager caps a particle update at .03 seconds. Each
    // 30 fps display frame contains two ordinary 60 Hz particle updates.
    const step = Math.floor(elapsed * fps + 1e-9) * (nativeStepRate / fps);
    return Number.isSafeInteger(step) ? step : -1;
  }

  function autoSeed() {
    if (global.crypto?.getRandomValues) return global.crypto.getRandomValues(new Uint32Array(1))[0];
    return Math.floor(Math.random() * 0x100000000);
  }

  function nativeRandom(seed = autoSeed()) {
    const words = new Uint32Array(4);
    words[0] = seed;
    for (let i = 1; i < words.length; i++) words[i] = Math.imul(words[i - 1], 0x6c078965) + 1;
    return function draw() {
      const first = words[0] ^ (words[0] << 11), last = words[3];
      words.copyWithin(0, 1);
      words[3] = first ^ (first >>> 8) ^ last ^ (last >>> 19);
      return words[3];
    };
  }

  function nativeUnit(word) {
    return Math.fround((word & 0x7fffff) * Math.fround(1 / 0x7fffff));
  }

  function nativeRoll([min, max]) {
    const draw = nativeRandom();
    // Unity's InitialModule stores the Z roll from the fourth draw.
    draw();
    draw();
    draw();
    return Math.fround(min + Math.fround(Math.fround(max - min) * nativeUnit(draw())));
  }

  function checked(source, curve, particle) {
    const { textures, templates, cues } = source || {};
    if (!Array.isArray(textures) || textures.length < 1 || textures.length > 4 ||
        !textures.every(particle.validMipChain) ||
        !Array.isArray(templates) || templates.length < 1 || templates.length > 8 ||
        !Array.isArray(cues) || cues.length < 1 || cues.length > 32 ||
        !cues.every(cue => id(cue?.trackId) && id(cue.eventId) &&
          Number.isInteger(cue.template) && templates[cue.template])) return false;
    return templates.every(emitters => Array.isArray(emitters) && emitters.length > 0 && emitters.length <= 12 &&
      emitters.every(emitter => {
        const { geometry, material, texture, uvOffset, color, orbitY, maxViewportWidth, rollRange } = emitter || {};
        const packed = value => particle.boundedCurve(value, curve.validCurve);
        return !!textures[texture] && Number.isInteger(texture) && !!geometry && validGeometry(geometry) &&
          material?.blend === "add" && (material.queue === 3000 || material.queue === 3010) &&
          (material.cull === 0 || material.cull === 2) && vector(material.tint, 4) && vector(material.uv, 4) &&
          vector(emitter.position, 3) && vector(emitter.rotation, 4) && vector(emitter.scale, 3) &&
          inRange(emitter.birth, 0, 15) && inRange(emitter.lifetime, 0.01, 120) &&
          (maxViewportWidth === undefined ? inRange(emitter.size, 0.01, 32) :
            inRange(maxViewportWidth, 0.01, 4) && emitter.scale.every(value => value === 1) &&
              inRange(emitter.size, 0.01, 64)) &&
          inRange(emitter.yaw, -40, 40) && inRange(emitter.yawSpeed, -40, 40) &&
          (orbitY === undefined || inRange(orbitY, -40, 40)) &&
          (rollRange === undefined || (vector(rollRange, 2) && inRange(rollRange[0], -3.15, rollRange[1]) &&
            rollRange[1] <= 3.15)) &&
          packed(emitter.sizeCurve) && (uvOffset === undefined ||
            (Array.isArray(uvOffset) && uvOffset.length === 2 && uvOffset.every(packed))) &&
          (color?.rgba8 === undefined
            ? particle.gradientKeys(color?.rgb, 3) && particle.gradientKeys(color?.alpha, 1)
            : validNativeColor(color.rgba8));
      }));
  }

  async function apply(T, root, descriptor) {
    const curve = global.MVStudioStageMotion, particle = global.MVStudioTitle;
    if (!root?.isObject3D || !descriptor || !curve?.evaluate || !particle?.validMipChain || !particle?.loadTexture ||
        !checked(descriptor, curve, particle)) return null;
    const textures = [], geometry = new Map(), groups = [], loader = new T.TextureLoader();
    const vertical = new T.Vector3(0, 1, 0), forward = new T.Vector3(0, 0, 1), turn = new T.Quaternion();
    const particleCenter = new T.Vector3();
    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const { group, meshes } of groups) {
        root.remove(group);
        for (const { mesh } of meshes) mesh.material.dispose();
      }
      for (const texture of textures) texture.dispose();
      for (const shape of geometry.values()) shape.dispose();
    }
    try {
      for (const levels of descriptor.textures) textures.push(await particle.loadTexture(T, loader, levels));
      for (const cue of descriptor.cues) {
        const group = new T.Group(), meshes = [];
        group.name = "Native stage particles";
        group.visible = false;
        groups.push({cue, group, meshes});
        for (const emitter of descriptor.templates[cue.template]) {
          const key = JSON.stringify(emitter.geometry);
          if (!geometry.has(key)) {
            const authored = emitter.geometry, shape = new T.BufferGeometry();
            shape.setAttribute("position", new T.Float32BufferAttribute(authored.positions.flat(), 3));
            shape.setAttribute("uv", new T.Float32BufferAttribute(authored.uv.flat(), 2));
            shape.setIndex(authored.indices);
            geometry.set(key, shape);
          }
          const fields = emitter.material;
          const limit = emitter.maxViewportWidth;
          const defines = fields.premultiply === true ? {SOURCE_ALPHA: 1} : {};
          if (limit !== undefined) defines.VIEWPORT_SIZE_LIMIT = 1;
          const shader = new T.ShaderMaterial({
            name: "Native stage particle", vertexShader, fragmentShader,
            defines,
            transparent: true, toneMapped: false, side: fields.cull === 0 ? T.DoubleSide : T.FrontSide,
            depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, blending: T.CustomBlending,
            blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
            blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
            uniforms: {uTexture: {value: textures[emitter.texture]},
              uTint: {value: new T.Vector4()}, uTextureST: {value: new T.Vector4()},
              ...(limit === undefined ? {} : {uViewportScale: {value: 1}})},
          });
          const mesh = new T.Mesh(geometry.get(key), shader);
          mesh.position.fromArray(emitter.position);
          mesh.renderOrder = fields.queue;
          if (limit !== undefined) {
            mesh.onBeforeRender = (_renderer, _scene, camera) => {
              // Unity clamps size at the particle center to a fraction of the
              // current camera's horizontal frustum width before making the quad.
              const depth = camera.isPerspectiveCamera
                ? -particleCenter.setFromMatrixPosition(mesh.matrixWorld).applyMatrix4(camera.matrixWorldInverse).z
                : 1;
              const width = 2 * depth / Math.abs(camera.projectionMatrix.elements[0]);
              shader.uniforms.uViewportScale.value = (camera.isPerspectiveCamera || camera.isOrthographicCamera) &&
                depth >= 0 && Number.isFinite(width) ? Math.min(1, limit * width / mesh.scale.x) : 1;
              shader.uniformsNeedUpdate = true;
            };
          }
          group.add(mesh);
          const orientation = new T.Quaternion().fromArray(emitter.rotation);
          // Each activated preview cue gets its own auto seed. Keep that
          // realization while seeking so inspecting the same frame is stable.
          if (emitter.rollRange) orientation.multiply(turn.setFromAxisAngle(forward, nativeRoll(emitter.rollRange)));
          meshes.push({emitter, mesh, orientation});
        }
        root.add(group);
      }
    } catch {
      dispose();
      return null;
    }
    let registeredTracks;
    return {
      update(time, project) {
        if (disposed) return;
        if (registeredTracks !== project?.tracks) {
          registeredTracks = project?.tracks;
          const tracks = new Map((registeredTracks || []).map(track => [track.id, track]));
          for (const record of groups) record.track = tracks.get(record.cue.trackId);
        }
        for (const {cue, group, meshes, track} of groups) {
          const event = !track?.muted && track?.events.find(row => row.id === cue.eventId);
          const offset = project?.quality?.values?.stage_control !== false && activeOffset(event, time);
          group.visible = !!offset;
          if (!offset) continue;
          group.position.fromArray(offset);
          for (const {emitter, mesh, orientation} of meshes) {
            const age = time - event.start - emitter.birth;
            const size = age >= 0 && age < emitter.lifetime ?
              emitter.size * curve.evaluate(emitter.sizeCurve, age / emitter.lifetime) : 0;
            mesh.visible = size > 0;
            if (!mesh.visible) continue;
            const normalized = age / emitter.lifetime;
            const [x, y, z] = emitter.scale, { yaw, yawSpeed, material, color, uvOffset, orbitY } = emitter;
            mesh.scale.set(x * size, y * size, z * size);
            if (orbitY) {
              const [px, py, pz] = emitter.position;
              const cos = Math.cos(orbitY * age), sin = Math.sin(orbitY * age);
              mesh.position.set(cos * px + sin * pz, py, cos * pz - sin * px);
            }
            mesh.quaternion.copy(orientation).multiply(turn.setFromAxisAngle(vertical, yaw + yawSpeed * age));
            const {uTint, uTextureST} = mesh.material.uniforms;
            const bytes = color.rgba8 && nativeColor(color.rgba8, normalized);
            uTint.value.set(...material.tint.map((value, i) => value * (bytes ? bytes[i] :
              particle.gradient(i === 3 ? color.alpha : color.rgb, normalized, i === 3 ? 1 : i + 1))));
            const [sx, sy, u, v] = material.uv;
            const ox = uvOffset ? curve.evaluate(uvOffset[0], normalized) : 0;
            const oy = uvOffset ? curve.evaluate(uvOffset[1], normalized) : 0;
            uTextureST.value.set(sx, sy, u + sx * ox, 1 - sy - v - sy * oy);
          }
        }
      },
      dispose,
    };
  }

  global.MVStudioStageParticles = {
    apply, autoSeed, nativeRandom, nativeUnit, nativeColor, nativeColorAtTime, validNativeColor,
    nativeFrame, nativeStep, nativeStepRate,
  };
})(typeof window !== "undefined" ? window : globalThis);
