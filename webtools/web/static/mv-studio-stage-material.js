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
        vec3 baked = 2.0 * texture2D(lightMap, vStageLightUV).rgb;
        vec3 lit = mix(surface.rgb, ambient.rgb, ambient.a) * baked * vStageColor.rgb;
        #ifdef CUBEMAP
          if (useReflection) {
            vec3 nativeCamera = cameraPosition * vec3(-1.0, 1.0, 1.0);
            vec3 ray = reflect(normalize(vReflectionPosition - nativeCamera), normalize(vReflectionNormal));
            vec3 walls = max((reflectionBoxMax - vReflectionPosition) / ray, (reflectionBoxMin - vReflectionPosition) / ray);
            float distance = min(min(walls.x, walls.y), walls.z);
            vec3 direction = ray * distance + vReflectionPosition - reflectionOrigin;
            vec3 reflected = mix(textureCube(reflectionCube, direction).rgb, ambient.rgb, ambient.a);
            #ifdef CUBEMAP_ADD
              lit += reflected * clamp(surface.a, 0.0, 1.0);
            #else
              lit = mix(lit, reflected, clamp(vStageColor.a, 0.0, 1.0));
            #endif
          }
        #endif
        lit *= tint.rgb;
        gl_FragColor = vec4(mix(lit, blendColor.rgb, blendColor.a), surface.a * tint.a);
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
  const mainStage = "/EntryPoint/Live/Stages/MainStage";

  function isColor(value) {
    return Array.isArray(value) && value.length === 4 && value.every(Number.isFinite);
  }

  function reflectionSource(value) {
    return Number.isSafeInteger(value?.bufferView) && value.bufferView >= 0 &&
      Number.isSafeInteger(value.size) && value.size >= 8 && value.size <= 256 &&
      (value.size & (value.size - 1)) === 0 &&
      ["vertex-alpha", "add-texture-alpha"].includes(value.blend) &&
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
    let present = false;
    for (const event of track.events) {
      const values = event.values;
      if (values?.playableClass !== "LiveStageAmbientClip") continue;
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

  async function apply(T, root, parser) {
    const candidates = [], textures = new Map(), nativeLightmaps = new Set(), cubes = new Map(), records = [];
    root.traverse((node) => {
      const meta = node.geometry?.userData?.mvStageMaterial;
      if (!node.isMesh || !["stage", "general", "solid"].includes(meta?.shader) || !isColor(meta.colors?._TintColor)) return;
      if (meta.shader !== "solid" && (!node.material?.map || !isColor(meta.uvTransform) ||
          !isColor(meta.colors._AmbientColor))) return;
      if (meta.vertexColor && !node.geometry.getAttribute("_stage_color")) return;
      if (meta.shader === "stage" && (!parser || !Number.isSafeInteger(meta.lightmap) ||
          meta.lightmap < 0 || !node.geometry.getAttribute("_stage_light_uv") ||
          !isColor(meta.colors._BlendColor) || !Number.isFinite(meta.mipBias))) return;
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

    for (const entry of candidates) {
      const {node, original, meta} = entry;
      const uniforms = { tint: {value: new T.Vector4().fromArray(meta.colors._TintColor)} };
      const defines = {};
      let reflectionCube = null;
      if (meta.shader !== "solid") {
        defines.TEXTURED = 1;
        uniforms.mainMap = {value: gammaTexture(original.map)};
        uniforms.mainUVTransform = {value: new T.Vector4().fromArray(meta.uvTransform)};
        uniforms.ambient = {value: new T.Vector4().fromArray(meta.colors._AmbientColor)};
      }
      if (meta.vertexColor) defines.VERTEX_COLOR = 1;
      if (meta.shader === "stage") {
        let lightMap;
        try { lightMap = await parser.getDependency("texture", meta.lightmap); }
        catch { continue; }
        if (!lightMap?.isTexture) continue;
        nativeLightmaps.add(lightMap);
        defines.LIGHTMAPPED = 1;
        uniforms.lightMap = {value: gammaTexture(lightMap)};
        uniforms.mipBias = {value: meta.mipBias};
        uniforms.blendColor = {value: new T.Vector4().fromArray(meta.colors._BlendColor)};
        const source = meta.reflection;
        if (meta.reflectionToggle && reflectionSource(source)) {
          if (!cubes.has(source.bufferView)) cubes.set(source.bufferView, await loadCube(T, parser, source));
          reflectionCube = cubes.get(source.bufferView);
          if (reflectionCube) {
            defines.CUBEMAP = 1;
            if (source.blend === "add-texture-alpha") defines.CUBEMAP_ADD = 1;
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

    let sourceTracks, ambientTrack;
    return {
      update(seconds, project, lighting) {
        if (sourceTracks !== project?.tracks) {
          sourceTracks = project?.tracks;
          const matches = sourceTracks?.filter(track => track.nativeClass === "LiveStageAmbientTrack" &&
            track.binding === mainStage);
          ambientTrack = matches?.length === 1 ? matches[0] : null;
        }
        const active = stageAmbient(project, seconds, ambientTrack);
        for (const {node, original, meta, material, reflectionCube} of records) {
          if (meta.reflectionToggle) {
            const enable = project?.quality?.values?.stage_cubemap !== false;
            const reflection = material.uniforms.useReflection;
            if (reflection) {
              reflection.value = enable;
              material.uniforms.reflectionCube.value = enable ? reflectionCube : null;
            }
            node.material = enable && !reflection ? original : material;
            if (node.material === original) continue;
          }
          if (!meta.ambientDefaults) continue;
          const property = ["ambient", "tint", "blendColor"];
          for (let index = 0; index < property.length; index++) {
            const uniform = material.uniforms[property[index]];
            if (!uniform) continue;
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
        for (const copy of textures.values()) copy.dispose();
        for (const original of nativeLightmaps) original.dispose();
        for (const cube of cubes.values()) cube?.dispose();
      },
    };
  }

  global.MVStudioStageMaterial = { apply };
})(typeof window !== "undefined" ? window : globalThis);
