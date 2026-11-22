(function (global) {
  "use strict";

  // The original mobile player renders these surfaces in gamma space.
  // GlTF keeps the maps and shader inputs in the asset, while this pass
  // applies the original stage equations during playback.
  const vertexShader = `
    #ifdef TEXTURED
      uniform vec4 mainUVTransform;
      varying vec2 vStageUV;
    #endif
    #ifdef VERTEX_COLOR
      attribute vec4 _stage_color;
      varying vec4 vStageColor;
    #endif
    #ifdef LIGHTMAPPED
      attribute vec2 _stage_light_uv;
      varying vec2 vStageLightUV;
    #endif
    #ifdef EMISSIVE
      attribute vec2 _stage_emissive_uv;
      uniform vec4 emissiveUVTransform;
      varying vec2 vStageEmissiveUV;
    #endif
    #ifdef CUBEMAP
      varying vec3 vReflectionPosition;
      varying vec3 vReflectionNormal;
    #endif
    void main() {
      #ifdef TEXTURED
        vStageUV = uv * mainUVTransform.xy + mainUVTransform.zw;
      #endif
      #ifdef VERTEX_COLOR
        vStageColor = _stage_color;
      #endif
      #ifdef LIGHTMAPPED
        vStageLightUV = _stage_light_uv;
      #endif
      #ifdef EMISSIVE
        vStageEmissiveUV = _stage_emissive_uv * emissiveUVTransform.xy + emissiveUVTransform.zw;
      #endif
      #ifdef CUBEMAP
        const vec3 unityAxes = vec3(-1.0, 1.0, 1.0);
        vReflectionPosition = (modelMatrix * vec4(position, 1.0)).xyz * unityAxes;
        vec3 worldNormal = (vec4(normalMatrix * normal, 0.0) * viewMatrix).xyz;
        vReflectionNormal = normalize(worldNormal) * unityAxes;
      #endif
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `;

  const fragmentShader = `
    uniform vec4 tint;
    #ifdef TEXTURED
      uniform sampler2D mainMap;
      uniform vec4 ambient;
      varying vec2 vStageUV;
    #endif
    #ifdef VERTEX_COLOR
      varying vec4 vStageColor;
    #endif
    #ifdef LIGHTMAPPED
      uniform sampler2D lightMap;
      uniform float mipBias;
      uniform vec4 blendColor;
      varying vec2 vStageLightUV;
    #endif
    #ifdef CUTOUT
      uniform float alphaCutoff;
    #endif
    #ifdef EMISSIVE
      uniform sampler2D emissiveMap;
      uniform vec4 emissiveColor;
      uniform float emissiveIntensity;
      varying vec2 vStageEmissiveUV;
    #endif
    #ifdef CUBEMAP
      uniform bool useReflection;
      uniform samplerCube reflectionCube;
      uniform vec3 reflectionBoxMin, reflectionBoxMax, reflectionOrigin;
      varying vec3 vReflectionPosition;
      varying vec3 vReflectionNormal;
    #endif
    void main() {
      #ifdef LIGHTMAPPED
        vec4 surface = texture2D(mainMap, vStageUV, mipBias);
        #ifdef CUTOUT
          if (surface.a < alphaCutoff) discard;
        #endif
        vec3 baked = 2.0 * texture2D(lightMap, vStageLightUV).rgb;
        vec3 ambientSurface = mix(surface.rgb, ambient.rgb, ambient.a);
        vec3 lit = ambientSurface * baked * vStageColor.rgb;
        #ifdef CUBEMAP
          if (useReflection) {
            vec3 nativeCamera = cameraPosition * vec3(-1.0, 1.0, 1.0);
            vec3 ray = reflect(normalize(vReflectionPosition - nativeCamera), normalize(vReflectionNormal));
            vec3 walls = max((reflectionBoxMax - vReflectionPosition) / ray, (reflectionBoxMin - vReflectionPosition) / ray);
            float distance = min(min(walls.x, walls.y), walls.z);
            vec3 direction = ray * distance + vReflectionPosition - reflectionOrigin;
            vec3 reflected = mix(textureCube(reflectionCube, direction).rgb, ambient.rgb, ambient.a);
            #if defined(CUBEMAP_ADD)
              lit += reflected * clamp(surface.a, 0.0, 1.0);
            #elif defined(CUBEMAP_ADD_VERTEX_ALPHA)
              lit += reflected * clamp(vStageColor.a, 0.0, 1.0);
            #else
              lit = mix(lit, reflected, clamp(vStageColor.a, 0.0, 1.0));
            #endif
          }
        #endif
        vec3 color = mix(lit * tint.rgb, blendColor.rgb, blendColor.a);
        #ifdef EMISSIVE
          vec3 emission = mix(ambientSurface, emissiveColor.rgb, emissiveColor.a) * emissiveIntensity;
          color = mix(color, emission, texture2D(emissiveMap, vStageEmissiveUV).r);
        #endif
        gl_FragColor = vec4(color, surface.a * tint.a);
      #elif defined(TEXTURED)
        vec4 surface = texture2D(mainMap, vStageUV);
        #ifdef VERTEX_COLOR
          surface *= vStageColor;
        #endif
        gl_FragColor = vec4(mix(surface.rgb, ambient.rgb, ambient.a), surface.a) * tint;
      #else
        gl_FragColor = tint;
      #endif
    }
  `;

  const fields = ["color", "tintColor", "blendColor"];
  const propertyNames = ["_AmbientColor", "_TintColor", "_BlendColor"];
  const ambientUniforms = ["ambient", "tint", "blendColor"];
  // LiveCoreStageAmbient initializes these defaults independently of the material.
  const singleDefaults = [[1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 1, 0]];
  const mainStage = "/EntryPoint/Live/Stages/MainStage";
  const stageModel = mainStage + "/Model";

  function isColor(value) {
    return Array.isArray(value) && value.length === 4 && value.every(Number.isFinite);
  }

  function reflectionSource(value) {
    return Number.isSafeInteger(value?.bufferView) && value.bufferView >= 0 &&
      Number.isSafeInteger(value.size) && value.size >= 8 && value.size <= 256 &&
      (value.size & (value.size - 1)) === 0 &&
      ["vertex-alpha", "add-texture-alpha", "add-vertex-alpha"].includes(value.blend) &&
      [value.boxMin, value.boxMax, value.origin].every(row => Array.isArray(row) && row.length === 3 && row.every(Number.isFinite));
  }

  async function loadCube(T, parser, source) {
    let data;
    try { data = await parser.getDependency("bufferView", source.bufferView); }
    catch { return null; }
    const levels = [];
    let faceBytes = 0;
    for (let size = source.size; size > 0; size >>= 1) {
      const length = size * size * 4;
      levels.push({size, length, offset: faceBytes});
      faceBytes += length;
    }
    if (!(data instanceof ArrayBuffer) || data.byteLength !== 6 * faceBytes) return null;
    const faces = levels.map(level => Array.from({length: 6}, (_, face) => new T.DataTexture(
      new Uint8Array(data, face * faceBytes + level.offset, level.length), level.size, level.size, T.RGBAFormat,
    )));
    const cube = new T.CubeTexture(faces[0]);
    cube.format = T.RGBAFormat;
    cube.encoding = T.LinearEncoding;
    cube.minFilter = T.LinearMipmapLinearFilter;
    cube.magFilter = T.LinearFilter;
    cube.generateMipmaps = false;
    cube.mipmaps = faces.slice(1).map(image => ({image}));
    cube.flipY = false;
    cube.needsUpdate = true;
    return cube;
  }

  function stageAmbient(project, seconds, track) {
    const api = global.MVStudioLighting;
    if (!track || track.muted || project?.quality?.values?.stage_ambient === false ||
        !api?.nativeWeight || !api?.memberColor) return null;
    const colors = fields.map(() => [0, 0, 0, 0]);
    const clipClass = track.nativeClass === "LiveStageSingleAmbientTrack" ?
      "LiveStageSingleAmbientClip" : "LiveStageAmbientClip";
    let present = false;
    for (const event of track.events) {
      const values = event.values;
      if (values?.playableClass !== clipClass) continue;
      const weight = api.nativeWeight(event, seconds);
      if (!(weight > 0)) continue;
      present = true;
      fields.forEach((field, index) => {
        const paint = api.memberColor(project, values.colorSpecifiedType, values.memberPosition, values[field]);
        if (isColor(paint)) for (let channel = 0; channel < 4; channel++) colors[index][channel] += paint[channel] * weight;
      });
    }
    return present ? colors : null;
  }

  function stageEmissive(project, seconds, track) {
    const api = global.MVStudioLighting;
    if (!track || track.muted || project?.quality?.values?.stage_emissive === false ||
        !api?.nativeWeight || !api?.memberColor) return null;

    // The bound native mixer clears both properties even when its clip weights are zero.
    const color = [0, 0, 0, 0];
    let intensity = 0;
    const f32 = Math.fround;
    for (const event of track.events) {
      const values = event.values;
      if (values?.playableClass !== "LiveStageEmissiveClip" || !Number.isFinite(values.intensity)) continue;
      const weight = f32(api.nativeWeight(event, seconds));
      if (!(weight > 0)) continue;
      const paint = api.memberColor(project, values.colorSpecifiedType, values.memberPosition, values.color);
      if (isColor(paint)) {
        for (let channel = 0; channel < 4; channel++) {
          color[channel] = f32(color[channel] + f32(f32(paint[channel]) * weight));
        }
      }
      intensity = f32(intensity + f32(f32(values.intensity) * weight));
    }
    return {color, intensity};
  }

  async function apply(T, root, parser, {active = () => true, maxTextureSize = 4096} = {}) {
    const candidates = [], textures = new Map(), cubes = new Map(), records = [];
    const authoredTextures = new Map(), textureRequests = new Map(), mipTextures = new Set();
    const nativeBaseIndices = new Set(), nativeBaseMaps = new Set();
    const originalMaps = new Set(), originalImages = new Set();
    root.traverse((node) => {
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
        if (!material) continue;
        for (const value of Object.values(material)) {
          if (value?.isTexture) {
            originalMaps.add(value);
            if (value.image) originalImages.add(value.image);
          }
        }
      }
      const meta = node.geometry?.userData?.mvStageMaterial;
      if (!node.isMesh || !["stage", "general", "solid"].includes(meta?.shader) || !isColor(meta.colors?._TintColor)) return;
      if (meta.shader !== "solid" && (!node.material?.map || !isColor(meta.uvTransform) ||
          !isColor(meta.colors._AmbientColor))) return;
      if (meta.vertexColor && !node.geometry.getAttribute("_stage_color")) return;
      if (meta.shader === "stage" && (!parser || !Number.isSafeInteger(meta.lightmap) ||
          meta.lightmap < 0 || !node.geometry.getAttribute("_stage_light_uv") ||
          !isColor(meta.colors._BlendColor) || !Number.isFinite(meta.mipBias))) return;
      if (meta.alphaCutoff !== undefined && (meta.shader !== "stage" || !Number.isFinite(meta.alphaCutoff) ||
          meta.alphaCutoff < 0 || meta.alphaCutoff > 1)) return;
      if (meta.emissive && (meta.shader !== "stage" || meta.reflectionToggle ||
          !node.geometry.getAttribute("_stage_emissive_uv") || !Number.isSafeInteger(meta.emissive.texture) ||
          meta.emissive.texture < 0 || !isColor(meta.emissive.color) ||
          !isColor(meta.emissive.uvTransform) || !Number.isFinite(meta.emissive.intensity))) return;
      if (meta.shader === "stage") {
        nativeBaseIndices.add(meta.lightmap);
        if (meta.emissive) nativeBaseIndices.add(meta.emissive.texture);
      }
      candidates.push({node, original: node.material, meta});
    });
    if (!candidates.length) return null;

    function gammaTexture(texture) {
      if (!textures.has(texture)) {
        const copy = texture.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        textures.set(texture, copy);
      }
      return textures.get(texture);
    }

    function textureFromParser(index) {
      if (!textureRequests.has(index)) {
        const request = Promise.resolve().then(() => parser.getDependency("texture", index))
          .then(texture => texture?.isTexture ? texture : null).catch(() => null);
        textureRequests.set(index, request);
      }
      return textureRequests.get(index);
    }

    async function mipTexture(index) {
      if (nativeBaseIndices.has(index)) return null;
      const texture = await textureFromParser(index);
      if (!texture || originalMaps.has(texture) || originalImages.has(texture.image)) return null;
      mipTextures.add(texture);
      return texture;
    }

    async function sampledTexture(base, source) {
      const {mipmaps, filterMode, anisotropy = 1} = source || {};
      const {width, height} = base.image || {};
      if (!Array.isArray(mipmaps) || mipmaps.length > 12 ||
          !mipmaps.every(index => Number.isSafeInteger(index) && index >= 0) ||
          new Set(mipmaps).size !== mipmaps.length || ![0, 1, 2].includes(filterMode) ||
          !Number.isInteger(anisotropy) || anisotropy < 0 || anisotropy > 16 ||
          ![width, height].every(side => Number.isInteger(side) && side >= 1 && side <= Math.min(maxTextureSize, 4096)) ||
          (mipmaps.length && (!T.MathUtils.isPowerOfTwo(width) || !T.MathUtils.isPowerOfTwo(height) ||
            mipmaps.length !== Math.log2(Math.max(width, height))))) return gammaTexture(base);

      let samplers = authoredTextures.get(base);
      if (!samplers) authoredTextures.set(base, samplers = new Map());
      const key = [filterMode, anisotropy, ...mipmaps].join(",");
      if (samplers.has(key)) return samplers.get(key);
      // Observe every request before deciding whether the authored chain is usable.
      const levels = await Promise.all(mipmaps.map(mipTexture));
      if (!active()) return null;
      if (levels.some((texture, index) => texture?.image?.width !== Math.max(1, width >> (index + 1)) ||
          texture?.image?.height !== Math.max(1, height >> (index + 1)))) {
        const fallback = gammaTexture(base);
        samplers.set(key, fallback);
        return fallback;
      }

      const copy = base.clone();
      copy.encoding = T.LinearEncoding;
      copy.magFilter = filterMode === 0 ? T.NearestFilter : T.LinearFilter;
      const mipFilters = [T.NearestMipmapNearestFilter, T.LinearMipmapNearestFilter, T.LinearMipmapLinearFilter];
      copy.minFilter = levels.length ? mipFilters[filterMode] : copy.magFilter;
      copy.anisotropy = Math.max(1, anisotropy);
      copy.generateMipmaps = false;
      copy.mipmaps = levels.length ? [base.image, ...levels.map(texture => texture.image)] : [];
      copy.needsUpdate = true;
      samplers.set(key, copy);
      return copy;
    }

    async function sampledNativeTexture(index, sampler) {
      const texture = await textureFromParser(index);
      if (!texture) return null;
      if (!originalMaps.has(texture)) nativeBaseMaps.add(texture);
      if (!active()) return null;
      return sampler ? sampledTexture(texture, sampler) : gammaTexture(texture);
    }

    for (const entry of candidates) {
      if (!active()) break;
      const {node, original, meta} = entry;
      const uniforms = { tint: {value: new T.Vector4().fromArray(meta.colors._TintColor)} };
      const defines = {};
      let reflectionCube = null;
      if (meta.shader !== "solid") {
        defines.TEXTURED = 1;
        const map = meta.shader === "stage" && meta.mainSampler
          ? await sampledTexture(original.map, meta.mainSampler) : gammaTexture(original.map);
        if (!map || !active()) break;
        uniforms.mainMap = {value: map};
        uniforms.mainUVTransform = {value: new T.Vector4().fromArray(meta.uvTransform)};
        uniforms.ambient = {value: new T.Vector4().fromArray(meta.colors._AmbientColor)};
      }
      if (meta.vertexColor) defines.VERTEX_COLOR = 1;
      if (meta.shader === "stage") {
        const lightMap = await sampledNativeTexture(meta.lightmap, meta.lightmapSampler);
        if (!active()) break;
        if (!lightMap) continue;
        defines.LIGHTMAPPED = 1;
        uniforms.lightMap = {value: lightMap};
        uniforms.mipBias = {value: meta.mipBias};
        uniforms.blendColor = {value: new T.Vector4().fromArray(meta.colors._BlendColor)};
        if (meta.alphaCutoff !== undefined) {
          defines.CUTOUT = 1;
          uniforms.alphaCutoff = {value: meta.alphaCutoff};
        }
        if (meta.emissive) {
          const emissive = await sampledNativeTexture(meta.emissive.texture, meta.emissive.sampler);
          if (!active()) break;
          if (!emissive) continue;
          defines.EMISSIVE = 1;
          uniforms.emissiveMap = {value: emissive};
          uniforms.emissiveUVTransform = {value: new T.Vector4().fromArray(meta.emissive.uvTransform)};
          uniforms.emissiveColor = {value: new T.Vector4().fromArray(meta.emissive.color)};
          uniforms.emissiveIntensity = {value: meta.emissive.intensity};
        }
        const source = meta.reflection;
        if (meta.reflectionToggle && reflectionSource(source)) {
          if (!cubes.has(source.bufferView)) cubes.set(source.bufferView, await loadCube(T, parser, source));
          if (!active()) break;
          reflectionCube = cubes.get(source.bufferView);
          if (reflectionCube) {
            defines.CUBEMAP = 1;
            if (source.blend === "add-texture-alpha") defines.CUBEMAP_ADD = 1;
            else if (source.blend === "add-vertex-alpha") defines.CUBEMAP_ADD_VERTEX_ALPHA = 1;
            uniforms.useReflection = {value: false};
            uniforms.reflectionCube = {value: null};
            uniforms.reflectionBoxMin = {value: new T.Vector3().fromArray(source.boxMin)};
            uniforms.reflectionBoxMax = {value: new T.Vector3().fromArray(source.boxMax)};
            uniforms.reflectionOrigin = {value: new T.Vector3().fromArray(source.origin)};
          }
        }
      }
      const material = new T.ShaderMaterial({
        name: original.name, defines, uniforms, vertexShader, fragmentShader, toneMapped: false,
        side: meta.cull === 0 ? T.DoubleSide : meta.cull === 1 ? T.BackSide : T.FrontSide,
      });
      if (!meta.reflectionToggle || uniforms.useReflection) node.material = material;
      records.push({...entry, material, reflectionCube});
    }

    const singleBindings = new Set(records.map(({meta}) => meta.singleAmbientBinding).filter(Boolean));
    const hasEmissiveBinding = records.some(({meta}) => meta.emissive?.binding === stageModel);
    const singleTracks = new Map(), samples = new Map();
    let sourceTracks, ambientTrack, emissiveTrack;
    return {
      update(seconds, project, lighting) {
        if (sourceTracks !== project?.tracks) {
          sourceTracks = project?.tracks;
          const matches = sourceTracks?.filter(track => track.nativeClass === "LiveStageAmbientTrack" &&
            track.binding === mainStage);
          ambientTrack = matches?.length === 1 ? matches[0] : null;
          if (hasEmissiveBinding) {
            const emissiveMatches = sourceTracks?.filter(track => track.nativeClass === "LiveStageEmissiveTrack" &&
              track.binding === stageModel);
            emissiveTrack = emissiveMatches?.length === 1 ? emissiveMatches[0] : null;
          }
          singleTracks.clear();
          for (const track of sourceTracks || []) {
            if (track.nativeClass !== "LiveStageSingleAmbientTrack" || !singleBindings.has(track.binding)) continue;
            singleTracks.set(track.binding, singleTracks.has(track.binding) ? null : track);
          }
        }
        const active = stageAmbient(project, seconds, ambientTrack);
        const emissive = stageEmissive(project, seconds, emissiveTrack);
        samples.clear();
        const baseAmbient = isColor(lighting?.baseAmbient) && lighting.baseAmbient[3] >= 0 ? lighting.baseAmbient : null;
        for (const {node, original, meta, material, reflectionCube} of records) {
          if (meta.reflectionToggle) {
            const enable = meta.reflectionQualityControlled === false ||
              project?.quality?.values?.stage_cubemap !== false;
            const reflection = material.uniforms.useReflection;
            if (reflection) {
              reflection.value = enable;
              material.uniforms.reflectionCube.value = enable ? reflectionCube : null;
            }
            node.material = enable && !reflection ? original : material;
            if (node.material === original) continue;
          }
          if (meta.emissive?.binding === stageModel) {
            const {color, intensity} = emissive || meta.emissive;
            material.uniforms.emissiveColor.value.fromArray(color);
            material.uniforms.emissiveIntensity.value = intensity;
          }
          if (!meta.ambientDefaults) continue;
          const singleTrack = singleTracks.get(meta.singleAmbientBinding);
          if (singleTrack && !samples.has(singleTrack)) samples.set(singleTrack, stageAmbient(project, seconds, singleTrack));
          const single = samples.get(singleTrack);
          for (let index = 0; index < ambientUniforms.length; index++) {
            const uniform = material.uniforms[ambientUniforms[index]];
            if (!uniform) continue;
            if (singleTrack) {
              const base = index === 0 ? baseAmbient : index === 1 ? lighting?.baseTint : null;
              const paint = single ? single[index] : (index === 0 && baseAmbient) || singleDefaults[index];
              uniform.value.fromArray(single && isColor(base) ? paint.map((value, channel) => value * base[channel]) : paint);
              continue;
            }
            const name = propertyNames[index];
            const fallback = meta.ambientDefaults[name] || meta.colors[name];
            const base = index === 0 ? lighting?.baseAmbient : index === 1 && lighting?.baseAmbient ? lighting.baseTint : null;
            let color = active?.[index] || fallback;
            if (isColor(base) && (index < 2)) color = active ? color.map((c, n) => c * base[n]) :
              ambientTrack && !ambientTrack.muted && project?.quality?.values?.stage_ambient !== false ? fallback : base;
            if (isColor(color)) uniform.value.fromArray(color);
          }
        }
      },
      dispose() {
        for (const {node, original, material} of records) {
          node.material = original;
          material.dispose();
        }
        const copies = new Set(textures.values()), images = new Set();
        for (const samplers of authoredTextures.values()) for (const copy of samplers.values()) copies.add(copy);
        for (const copy of copies) copy.dispose();
        for (const texture of mipTextures) {
          if (nativeBaseMaps.has(texture)) continue;
          texture.dispose();
          if (texture.image) images.add(texture.image);
        }
        for (const texture of nativeBaseMaps) {
          images.delete(texture.image);
          texture.dispose();
        }
        for (const image of images) image.close?.();
        for (const cube of cubes.values()) cube?.dispose();
      },
    };
  }

  global.MVStudioStageMaterial = { apply };
})(typeof window !== "undefined" ? window : globalThis);
