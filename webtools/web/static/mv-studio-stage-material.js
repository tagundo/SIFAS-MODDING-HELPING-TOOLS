(function (global) {
  "use strict";

  // The original mobile player renders these surfaces in gamma space.
  // GlTF keeps the maps and shader inputs in the asset, while this pass
  // applies the original non-reflective stage equations during playback.
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
    void main() {
      #ifdef LIGHTMAPPED
        vec4 surface = texture2D(mainMap, vStageUV, mipBias);
        vec3 baked = 2.0 * texture2D(lightMap, vStageLightUV).rgb;
        vec3 lit = mix(surface.rgb, ambient.rgb, ambient.a) * baked * vStageColor.rgb * tint.rgb;
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
    const candidates = [], textures = new Map(), nativeLightmaps = new Set(), records = [];
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
      }
      const material = new T.ShaderMaterial({
        name: original.name, defines, uniforms, vertexShader, fragmentShader, toneMapped: false,
        side: meta.cull === 0 ? T.DoubleSide : meta.cull === 1 ? T.BackSide : T.FrontSide,
      });
      if (!meta.reflectionToggle) node.material = material;
      records.push({...entry, material});
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
        for (const {node, original, meta, material} of records) {
          if (meta.reflectionToggle) {
            const enable = project?.quality?.values?.stage_cubemap !== false;
            node.material = enable ? original : material;
            if (enable) continue;
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
      },
    };
  }

  global.MVStudioStageMaterial = { apply };
})(typeof window !== "undefined" ? window : globalThis);
