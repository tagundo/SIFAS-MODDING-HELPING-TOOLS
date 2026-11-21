(function (global) {
  "use strict";

  const vertexShader = [
    "uniform vec4 uTextureST;",
    "varying vec2 vParticle;",
    "void main() {",
    "  vParticle = uv * uTextureST.xy + uTextureST.zw;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
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

  function checked(source, curve, particle) {
    const { textures, templates, cues } = source || {};
    if (!Array.isArray(textures) || textures.length < 1 || textures.length > 4 ||
        !textures.every(levels => Array.isArray(levels) && levels.length === 10 &&
          levels.every((bitmap, level) => bitmap?.width === (512 >> level) &&
            bitmap.height === (512 >> level) && particle.validTexture(bitmap))) ||
        !Array.isArray(templates) || templates.length < 1 || templates.length > 8 ||
        !Array.isArray(cues) || cues.length < 1 || cues.length > 32 ||
        !cues.every(cue => id(cue?.trackId) && id(cue.eventId) &&
          Number.isInteger(cue.template) && templates[cue.template])) return false;
    return templates.every(emitters => Array.isArray(emitters) && emitters.length > 0 && emitters.length <= 8 &&
      emitters.every(emitter => {
        const { geometry, material, texture, uvOffset, color } = emitter || {};
        const packed = value => particle.boundedCurve(value, curve.validCurve);
        return !!textures[texture] && Number.isInteger(texture) && !!geometry && validGeometry(geometry) &&
          material?.blend === "add" && (material.queue === 3000 || material.queue === 3010) &&
          (material.cull === 0 || material.cull === 2) && vector(material.tint, 4) && vector(material.uv, 4) &&
          vector(emitter.position, 3) && vector(emitter.rotation, 4) && vector(emitter.scale, 3) &&
          inRange(emitter.birth, 0, 15) && inRange(emitter.lifetime, 0.01, 120) && inRange(emitter.size, 0.01, 32) &&
          inRange(emitter.yaw, -40, 40) && inRange(emitter.yawSpeed, -40, 40) &&
          packed(emitter.sizeCurve) && (uvOffset === undefined ||
            (Array.isArray(uvOffset) && uvOffset.length === 2 && uvOffset.every(packed))) &&
          particle.gradientKeys(color?.rgb, 3) && particle.gradientKeys(color?.alpha, 1);
      }));
  }

  async function apply(T, root, descriptor) {
    const curve = global.MVStudioStageMotion, particle = global.MVStudioTitle;
    if (!root?.isObject3D || !descriptor || !curve?.evaluate || !particle?.validTexture ||
        !checked(descriptor, curve, particle)) return null;
    const textures = [], geometry = new Map(), groups = [], loader = new T.TextureLoader();
    const vertical = new T.Vector3(0, 1, 0), turn = new T.Quaternion();
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
      for (const levels of descriptor.textures) {
        const images = [];
        let native;
        for (const { png, width, height } of levels) {
          const bitmap = await loader.loadAsync("data:image/png;base64," + png);
          if (bitmap.image.width !== width || bitmap.image.height !== height) {
            bitmap.dispose();
            throw Error("The native stage particle texture has invalid dimensions.");
          }
          images.push(bitmap.image);
          if (native) bitmap.dispose();
          else {
            native = bitmap;
            textures.push(native);
          }
        }
        native.mipmaps = images;
        native.generateMipmaps = false;
        native.flipY = false;
        native.encoding = T.LinearEncoding;
        native.wrapS = native.wrapT = T.RepeatWrapping;
        native.magFilter = T.LinearFilter;
        native.minFilter = T.LinearMipmapNearestFilter;
        native.needsUpdate = true;
      }
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
          const shader = new T.ShaderMaterial({
            name: "Native stage particle", vertexShader, fragmentShader,
            defines: fields.premultiply === true ? {SOURCE_ALPHA: 1} : {},
            transparent: true, toneMapped: false, side: fields.cull === 0 ? T.DoubleSide : T.FrontSide,
            depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, blending: T.CustomBlending,
            blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
            blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
            uniforms: {uTexture: {value: textures[emitter.texture]},
              uTint: {value: new T.Vector4()}, uTextureST: {value: new T.Vector4()}},
          });
          const mesh = new T.Mesh(geometry.get(key), shader);
          mesh.position.fromArray(emitter.position);
          mesh.renderOrder = fields.queue;
          group.add(mesh);
          meshes.push({emitter, mesh, orientation: new T.Quaternion().fromArray(emitter.rotation)});
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
            const [x, y, z] = emitter.scale, { yaw, yawSpeed, material, color, uvOffset } = emitter;
            mesh.scale.set(x * size, y * size, z * size);
            mesh.quaternion.copy(orientation).multiply(turn.setFromAxisAngle(vertical, yaw + yawSpeed * age));
            const {uTint, uTextureST} = mesh.material.uniforms;
            uTint.value.set(...material.tint.map((value, i) => value *
              particle.gradient(i === 3 ? color.alpha : color.rgb, normalized, i === 3 ? 1 : i + 1)));
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

  global.MVStudioStageParticles = { apply };
})(typeof window !== "undefined" ? window : globalThis);
