(function (global) {
  "use strict";

  const vertexShader = [
    "uniform vec4 uTextureST;",
    "varying vec2 vTitle;",
    "void main() {",
    "  vTitle = uv * uTextureST.xy + uTextureST.zw;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "varying vec2 vTitle;",
    "void main() { gl_FragColor = texture2D(uTexture, vTitle) * uTint; }"
  ].join("\n");

  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const dimension = value => Number.isInteger(value) && value > 0 && value <= 1024 && (value & (value - 1)) === 0;
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const channelWidth = { translation: 3, overlayTint: 4, overlayUV: 4 };

  function validTexture(source) {
    const { png, width, height } = source || {};
    if (!dimension(width) || !dimension(height) || typeof png !== "string" || png.length < 32 ||
        png.length > 1024 * 1024 || png.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(png)) return false;
    // Check the decoded dimensions before passing the data to the image decoder.
    const header = global.atob(png.slice(0, 32));
    const int32 = index => header.charCodeAt(index) * 0x1000000 + header.charCodeAt(index + 1) * 0x10000 +
      header.charCodeAt(index + 2) * 0x100 + header.charCodeAt(index + 3);
    return header.slice(0, 8) === "\x89PNG\r\n\x1a\n" && int32(8) === 13 && header.slice(12, 16) === "IHDR" &&
      int32(16) === width && int32(20) === height;
  }

  function boundedCurve(curve, validCurve) {
    return Array.isArray(curve) && (curve[0] === "constant" ||
      (Array.isArray(curve[1]) && curve[1].length <= 512)) && validCurve(curve);
  }

  function checkedCues(source, validCurve) {
    const { geometry, textures, cues } = source;
    if (!Array.isArray(geometry?.positions) || geometry.positions.length !== 4 ||
        !geometry.positions.every(position => vector(position, 3)) ||
        !Array.isArray(geometry.uv) || geometry.uv.length !== 4 || !geometry.uv.every(uv => vector(uv, 2)) ||
        !Array.isArray(geometry.indices) || geometry.indices.length !== 6 ||
        !geometry.indices.every(index => Number.isInteger(index) && index >= 0 && index < 4) ||
        !Array.isArray(textures) || !textures.length || textures.length > 8 || !textures.every(validTexture) ||
        !Array.isArray(cues) || !cues.length || cues.length > 24) return null;
    const records = new Map();
    for (const cue of cues) {
      const { trackId, eventId, texture, material, meshes, animation } = cue || {};
      if (!id(trackId) || !id(eventId) || !textures[texture] || !Number.isInteger(texture) ||
          material?.queue !== 2900 || !vector(material.tint, 4) || !vector(material.uv, 4) ||
          !Array.isArray(meshes) || !meshes.length || meshes.length > 8 || !Array.isArray(animation?.channels) ||
          !Number.isFinite(animation.start) || !Number.isFinite(animation.duration) || !(animation.duration > 0) ||
          animation.loop !== false || animation.channels.length > meshes.length * 3) return null;
      const curves = new Map();
      for (const mesh of meshes) {
        if (!Number.isInteger(mesh?.path) || curves.has(mesh.path) || !id(mesh.name) ||
            !vector(mesh.position, 3) || !vector(mesh.rotation, 4) || !vector(mesh.scale, 3)) return null;
        curves.set(mesh.path, {});
      }
      for (const channel of animation.channels) {
        const { kind, path, curves: values } = channel || {};
        const fields = curves.get(path);
        if (!fields || !Object.hasOwn(channelWidth, kind) || Object.hasOwn(fields, kind) ||
            !Array.isArray(values) || values.length !== channelWidth[kind] ||
            !values.every(curve => boundedCurve(curve, validCurve))) return null;
        fields[kind] = values;
      }
      const key = JSON.stringify([trackId, eventId]);
      if (records.has(key)) return null;
      records.set(key, { ...cue, curves });
    }
    return records.values();
  }

  function gradientKeys(keys, axes) {
    return Array.isArray(keys) && keys.length > 0 && keys.length <= 8 && keys.every((row, index) =>
      vector(row, axes + 1) && row[0] >= 0 && row[0] <= 1 && (index === 0 || row[0] > keys[index - 1][0]));
  }

  function validEmitter(emitter, textures, validCurve) {
    if (!emitter || !id(emitter.name) || !Number.isInteger(emitter.texture) || !textures[emitter.texture] ||
        !vector(emitter.position, 3) || !vector(emitter.rotation, 4) || !vector(emitter.scale, 3) ||
        !vector(emitter.size, 2) || !emitter.size.every(value => value > 0) ||
        !Number.isFinite(emitter.lifetime) || !(emitter.lifetime > 0) || emitter.lifetime > 15 ||
        emitter.material?.queue !== 2900 || !vector(emitter.material.tint, 4) || !vector(emitter.material.uv, 4) ||
        !Array.isArray(emitter.active) || emitter.active.length !== 2 ||
        !Array.isArray(emitter.sizeCurves) || emitter.sizeCurves.length !== 2 ||
        !emitter.sizeCurves.every(curve => boundedCurve(curve, validCurve)) ||
        !gradientKeys(emitter.color?.rgb, 3) || !gradientKeys(emitter.color?.alpha, 1)) return false;
    const [from, to] = emitter.active;
    if (!Number.isFinite(from) || from < 0 || (to !== null && (!Number.isFinite(to) || to <= from))) return false;
    const { tiles, row, frame } = emitter.atlas || {};
    return Array.isArray(tiles) && tiles.length === 2 &&
      tiles.every(value => Number.isInteger(value) && value >= 1 && value <= 16) &&
      (row === null || (Number.isInteger(row) && row >= 0 && row < tiles[1])) &&
      boundedCurve(frame, validCurve);
  }

  function checkedParticles(descriptor, validCurve) {
    const { particles, textures } = descriptor;
    if (!Array.isArray(particles) || particles.length > 8) return [];
    return particles.filter(cue => id(cue?.trackId) && id(cue.eventId) && Array.isArray(cue.emitters) &&
      cue.emitters.length > 0 && cue.emitters.length <= 8 &&
      cue.emitters.every(emitter => validEmitter(emitter, textures, validCurve)));
  }

  function gradient(keys, time, channel) {
    if (time <= keys[0][0]) return keys[0][channel];
    for (let i = 1; i < keys.length; i++) {
      const before = keys[i - 1], after = keys[i];
      if (time > after[0]) continue;
      const weight = (time - before[0]) / (after[0] - before[0]);
      return before[channel] + weight * (after[channel] - before[channel]);
    }
    return keys[keys.length - 1][channel];
  }

  function updateParticle({ emitter, mesh, uv }, elapsed, evaluate) {
    const [from, to] = emitter.active, age = elapsed - from;
    mesh.visible = age >= 0 && age < emitter.lifetime && (to === null || elapsed < to);
    if (!mesh.visible) return;
    const time = age / emitter.lifetime;
    const [sx, sy, sz] = emitter.scale;
    mesh.scale.set(sx * emitter.size[0] * evaluate(emitter.sizeCurves[0], time),
      sy * emitter.size[1] * evaluate(emitter.sizeCurves[1], time), sz);

    const { tint, uv: [uScale, vScale, uOffset, vOffset] } = emitter.material;
    const { rgb, alpha } = emitter.color;
    // Every vertex of this single quad has the same authored particle color.
    mesh.material.uniforms.uTint.value.set(tint[0] * gradient(rgb, time, 1),
      tint[1] * gradient(rgb, time, 2), tint[2] * gradient(rgb, time, 3), tint[3] * gradient(alpha, time, 1));

    const { tiles: [columns, rows], row, frame } = emitter.atlas;
    const count = row === null ? columns * rows : columns;
    const index = Math.max(0, Math.min(count - 1, Math.floor(evaluate(frame, time) * count)));
    const column = index % columns;
    const textureRow = row === null ? Math.floor(index / columns) : row;
    const x = uOffset + uScale * column / columns, y = vOffset + vScale * (rows - 1 - textureRow) / rows;
    uv.set(uScale / columns, vScale / rows, x, 1 - vScale / rows - y);
  }

  function updateMesh({ mesh, uv, tint, channels }, time, evaluate) {
    const { translation, overlayTint, overlayUV } = channels;
    if (translation) {
      const [x, y, z] = translation;
      mesh.position.set(-evaluate(x, time), evaluate(y, time), evaluate(z, time));
    }
    if (overlayTint) {
      const [r, g, b, a] = overlayTint;
      tint.set(evaluate(r, time), evaluate(g, time), evaluate(b, time), evaluate(a, time));
    }
    if (overlayUV) {
      const [sx, sy, x, y] = overlayUV;
      const verticalScale = evaluate(sy, time);
      uv.set(evaluate(sx, time), verticalScale, evaluate(x, time), 1 - verticalScale - evaluate(y, time));
    }
  }

  function neutralClip(event) {
    const value = event?.values;
    return value?.playableClass === "CustomControlClip" && Number.isFinite(event.start) &&
      Number.isFinite(event.duration) && event.duration > 0 && value.clipIn === 0 && value.timeScale === 1 &&
      value.weight === 1 && value.offset?.x === 0 && value.offset.y === 0 && value.offset.z === 0 &&
      !(value.easeIn > 0 || value.easeOut > 0 || value.blendIn > 0 || value.blendOut > 0 ||
        value.preExtrapolationMode || value.postExtrapolationMode);
  }

  function materialFor(T, texture, fields) {
    const [sx, sy, x, y] = fields.uv;
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, transparent: true, toneMapped: false, side: T.DoubleSide,
      depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, blending: T.CustomBlending,
      blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      // Three needs stencilWrite to enable the test. Keep all outcomes and
      // leave the write mask open so later framebuffer clears work.
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: { uTexture: { value: texture }, uTint: { value: new T.Vector4().fromArray(fields.tint) },
        uTextureST: { value: new T.Vector4(sx, sy, x, 1 - sy - y) } }
    });
    material.name = "Native stage title";
    return material;
  }

  async function apply(T, root, descriptor) {
    const curves = global.MVStudioStageMotion;
    if (!descriptor || !root?.isObject3D || !curves?.evaluate || !curves?.validCurve) return null;
    const source = checkedCues(descriptor, curves.validCurve);
    if (!source) return null;
    const particles = checkedParticles(descriptor, curves.validCurve);
    const { geometry: fields } = descriptor;
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(fields.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(fields.uv.flat(), 2));
    geometry.setIndex(fields.indices);

    const textures = [], groups = [], loader = new T.TextureLoader();
    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const { group, meshes } of groups) {
        root.remove(group);
        for (const { mesh } of meshes) mesh.material.dispose();
      }
      for (const texture of textures) texture.dispose();
      geometry.dispose();
    }
    try {
      for (const { png, width, height } of descriptor.textures) {
        const texture = await loader.loadAsync("data:image/png;base64," + png);
        textures.push(texture);
        if (texture.image.width !== width || texture.image.height !== height) {
          throw new Error("The stage title texture has invalid dimensions.");
        }
        texture.flipY = false;
        texture.encoding = T.LinearEncoding;
        texture.wrapS = T.RepeatWrapping;
        texture.wrapT = T.RepeatWrapping;
        texture.magFilter = T.LinearFilter;
        texture.minFilter = T.LinearMipmapNearestFilter;
        texture.generateMipmaps = true;
        texture.needsUpdate = true;
      }
      for (const cue of source) {
        const group = new T.Group(), meshes = [];
        group.name = "Native stage title";
        group.visible = false;
        groups.push({ cue, group, meshes });
        for (const authored of cue.meshes) {
          const mesh = new T.Mesh(geometry, materialFor(T, textures[cue.texture], cue.material));
          mesh.name = authored.name;
          mesh.position.fromArray(authored.position);
          mesh.quaternion.fromArray(authored.rotation);
          mesh.scale.fromArray(authored.scale);
          mesh.renderOrder = cue.material.queue;
          group.add(mesh);
          const uniforms = mesh.material.uniforms;
          meshes.push({ mesh, uv: uniforms.uTextureST.value, tint: uniforms.uTint.value,
            channels: cue.curves.get(authored.path) });
        }
        root.add(group);
      }
      for (const cue of particles) {
        const group = new T.Group(), meshes = [];
        group.name = "Native stage title particles";
        group.visible = false;
        groups.push({ cue, group, meshes, isParticle: true });
        for (const emitter of cue.emitters) {
          const mesh = new T.Mesh(geometry, materialFor(T, textures[emitter.texture], emitter.material));
          mesh.material.name = "Native stage title particle";
          mesh.name = emitter.name;
          mesh.position.fromArray(emitter.position);
          mesh.quaternion.fromArray(emitter.rotation);
          mesh.visible = false;
          mesh.renderOrder = emitter.material.queue;
          group.add(mesh);
          meshes.push({ emitter, mesh, uv: mesh.material.uniforms.uTextureST.value });
        }
        root.add(group);
      }
    } catch {
      dispose();
      return null;
    }

    let tracks;
    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const record of groups) {
            const hits = (tracks || []).filter(track => track.id === record.cue.trackId && track.nativeClass === "CustomControlTrack");
            record.track = hits.length === 1 ? hits[0] : null;
            const events = record.track?.events?.filter(event => event.id === record.cue.eventId);
            record.event = events?.length === 1 ? events[0] : null;
          }
        }
        const enabled = project?.quality?.values?.stage_display !== false;
        for (const { cue, track, event, group, meshes, isParticle } of groups) {
          group.visible = Boolean(enabled && !track?.muted && neutralClip(event) &&
            time >= event.start && time < event.start + event.duration);
          if (!group.visible) continue;
          const elapsed = time - event.start;
          if (isParticle) {
            for (const particle of meshes) updateParticle(particle, elapsed, curves.evaluate);
            continue;
          }
          const { start, duration } = cue.animation;
          const local = start + Math.min(duration, elapsed);
          for (const mesh of meshes) updateMesh(mesh, local, curves.evaluate);
        }
      },
      dispose
    };
  }
  global.MVStudioTitle = { apply };
})(typeof window !== "undefined" ? window : globalThis);
