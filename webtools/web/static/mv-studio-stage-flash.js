(function (global) {
  "use strict";

  const vertexShader = `
    attribute vec2 _stage_flash_uv;
    uniform vec4 uTextureST, uAtlasST;
    uniform float uTime, uSpeed, uLength;
    varying vec2 vTexture, vAtlas;

    float truncate(float value) { return sign(value) * floor(abs(value)); }
    float signedFraction(float value) { return sign(value) * fract(abs(value)); }

    void main() {
      vec2 sourceUV = vec2(uv.x, 1.0 - uv.y) * uTextureST.xy + uTextureST.zw;
      vTexture = vec2(sourceUV.x, 1.0 - sourceUV.y);
      float frame = truncate(signedFraction(uSpeed * uTime / uLength) * uLength);
      float row = frame / uAtlasST.x;
      vec2 tile = vec2(truncate(signedFraction(row) * uAtlasST.x), uAtlasST.y - 1.0 - truncate(row));
      vec2 atlasUV = (_stage_flash_uv + tile) / uAtlasST.xy + uAtlasST.zw;
      vAtlas = vec2(atlasUV.x, 1.0 - atlasUV.y);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture, uAtlas;
    uniform vec4 uTint;
    uniform bool uAll, uSaturate;
    varying vec2 vTexture, vAtlas;

    void main() {
      vec4 source = texture2D(uTexture, vTexture);
      vec4 color = source * uTint;
      if (!uAll) color *= texture2D(uAtlas, vAtlas);
      if (uSaturate) {
        vec3 squared = source.rgb * source.rgb;
        color.rgb += squared * squared;
      }
      gl_FragColor = color;
    }
  `;

  function mix(track, project, time) {
    const state = { tint: [0, 0, 0, 0], status: 0, speed: 0, time: 0 };
    let strongest = 0;
    for (const event of track.events) {
      const value = event.values;
      if (value?.playableClass !== "LiveFlashLightClip" || ![0, 1, 2].includes(value.status) ||
          !Number.isFinite(value.speed)) continue;
      const weight = global.MVStudioLighting.nativeWeight(event, time);
      if (!(weight > 0)) continue;
      const tint = global.MVStudioLighting.memberColor(project, value.colorSpecifiedType, value.memberPosition, value.tintColor);
      for (let i = 0; i < 4; i++) state.tint[i] += (tint?.[i] ?? 0) * weight;
      state.speed += value.speed * weight;
      if (weight > strongest) {
        strongest = weight;
        state.status = value.status;
        const elapsed = Math.min(event.duration, Math.max(0, time - event.start));
        state.time = elapsed * (value.timeScale ?? 1) + (value.clipIn ?? 0);
      }
    }
    return state;
  }

  async function apply(T, root, parser) {
    const candidates = [], ready = [], textures = new Map();
    root.traverse(node => {
      const fields = node.geometry?.userData?.mvStageFlash;
      if (!node.isMesh || !fields) return;
      const visible = node.visible;
      node.visible = false;
      if (!Array.isArray(node.material) && node.geometry.getAttribute("_stage_flash_uv") &&
          typeof fields.binding === "string" && [fields.texture, fields.atlas].every(Number.isInteger) &&
          [fields.textureST, fields.atlasST].every(value => Array.isArray(value) && value.length === 4 &&
            value.every(Number.isFinite)) && fields.atlasST[0] > 0 && fields.atlasST[1] > 0 &&
          Number.isFinite(fields.length) && fields.length > 0) {
        candidates.push({ node, fields, visible, original: node.material, order: node.renderOrder });
      }
    });
    if (!candidates.length) return null;
    function texture(index) {
      if (!textures.has(index)) textures.set(index, parser.getDependency("texture", index).then(original => {
        const copy = original.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        return copy;
      }));
      return textures.get(index);
    }
    for (const candidate of candidates) {
      const { node, fields } = candidate;
      let image, atlas;
      try {
        [image, atlas] = await Promise.all([texture(fields.texture), texture(fields.atlas)]);
      } catch {
        continue;
      }
      const uniforms = {
        uTexture: { value: image }, uAtlas: { value: atlas },
        uTextureST: { value: new T.Vector4().fromArray(fields.textureST) },
        uAtlasST: { value: new T.Vector4().fromArray(fields.atlasST) },
        uLength: { value: fields.length }, uSpeed: { value: 0 }, uTime: { value: 0 },
        uTint: { value: new T.Vector4() }, uAll: { value: false }, uSaturate: { value: fields.saturate === true },
      };
      const material = new T.ShaderMaterial({
        name: "Native stage flash lighting", vertexShader, fragmentShader, uniforms, toneMapped: false,
        transparent: true, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, side: T.DoubleSide,
        blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
        blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      });
      node.material = material;
      node.renderOrder = fields.queue;
      ready.push({ ...candidate, material });
    }
    let registered, tracks = new Map();
    return {
      update(time, project) {
        if (registered !== project.tracks) {
          registered = project.tracks;
          tracks = new Map();
          for (const track of project.tracks || []) if (track.nativeClass === "LiveFlashLightTrack") {
            tracks.set(track.binding, tracks.has(track.binding) ? null : track);
          }
        }
        for (const { node, fields, material } of ready) {
          const track = tracks.get(fields.binding);
          const state = track && !track.muted && project.quality?.values?.stage_flash_light !== false
            ? mix(track, project, time) : null;
          node.visible = Boolean(state && state.status !== 0);
          if (!node.visible) continue;
          const u = material.uniforms;
          u.uTint.value.fromArray(state.tint);
          u.uSpeed.value = state.speed;
          // Use project time for the native Auto Play built-in clock so seek
          // and repeat renders keep the same phase.
          u.uTime.value = fields.autoPlay ? time : state.time;
          u.uAll.value = state.status === 2;
        }
      },
      invalidate() { registered = undefined; },
      dispose() {
        for (const { node, material, original, visible, order } of ready) {
          node.material = original;
          node.visible = visible;
          node.renderOrder = order;
          material.dispose();
        }
        for (const copy of textures.values()) copy.then(texture => texture.dispose(), () => {});
      },
    };
  }

  global.MVStudioStageFlash = { apply };
})(typeof window === "undefined" ? globalThis : window);
