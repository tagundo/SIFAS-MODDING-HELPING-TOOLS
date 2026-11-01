/* AS/Member reconstruction for the local viewer. Source textures remain intact. */
(function (global) {
  "use strict";

  var VERTEX = [
    "#include <common>",
    "#include <morphtarget_pars_vertex>",
    "#include <skinning_pars_vertex>",
    "attribute vec4 _sifas_color;",
    "uniform vec4 uRimlightDirection;",
    "varying vec2 vSifasUv;",
    "varying vec4 vSifasMask;",
    "varying vec3 vSifasViewNormal;",
    "varying vec3 vSifasRimDirection;",
    "void main() {",
    "  #include <beginnormal_vertex>",
    "  #include <morphnormal_vertex>",
    "  #include <skinbase_vertex>",
    "  #include <skinnormal_vertex>",
    "  #include <begin_vertex>",
    "  #include <morphtarget_vertex>",
    "  #include <skinning_vertex>",
    "  #include <project_vertex>",
    "  vSifasUv = uv;",
    "  vSifasMask = _sifas_color;",
    // The source deliberately uses the model-view 3x3 here, not an inverse
    // transpose and not a normalized normal. Its rim/matcap equations depend
    // on that distinction. The outline pass uses the normalized normalMatrix.
    "  vSifasViewNormal = mat3(modelViewMatrix) * objectNormal;",
    "  vec3 rimVector = -mvPosition.xyz - uRimlightDirection.xyz;",
    "  vSifasRimDirection = rimVector / max(length(rimVector), 0.000001);",
    "}"
  ].join("\n");

  var FRAGMENT = [
    "uniform sampler2D uMainTex;",
    "uniform sampler2D uRimlightTex;",
    "uniform sampler2D uMatcapTex;",
    "uniform sampler2D uMatcapMaskTex;",
    "uniform sampler2D uEmissiveTex;",
    "uniform sampler2D uEmissiveScrollTex;",
    "uniform sampler2D uCheekTex;",
    "uniform vec4 uTintColor;",
    "uniform vec4 uAmbientColor;",
    "uniform vec4 uRimlightColor;",
    "uniform float uRimglightIntensity;",
    "uniform float uRimglightPower;",
    "uniform float uMainTexMipmapBias;",
    "uniform vec4 uMatcapIntensity;",
    "uniform vec4 uMatcapSpanCol;",
    "uniform float uMatcapTexAdd;",
    "uniform float uMatcapSpanColTexAdd;",
    "uniform float uMatcapTexDarkenR;",
    "uniform float uMatcapBrightR;",
    "uniform float uMatcapBrightG;",
    "uniform vec4 uEmissiveIntensity;",
    "uniform vec4 uEmissiveFlicker;",
    "uniform float uBeat;",
    "uniform float uCheekIntensity;",
    "varying vec2 vSifasUv;",
    "varying vec4 vSifasMask;",
    "varying vec3 vSifasViewNormal;",
    "varying vec3 vSifasRimDirection;",
    "vec3 applyMatcap(vec4 mainSample, vec3 maskedBase) {",
    "  vec4 cap = texture2D(uMatcapTex, vec2(vSifasViewNormal.x * 0.5 + 0.5, 0.5 - vSifasViewNormal.y * 0.5));",
    "  vec3 mask = texture2D(uMatcapMaskTex, vSifasUv).rgb;",
    "  vec3 spangle = dot(cap.rgb, vec3(0.299, 0.587, 0.114)) * uMatcapSpanCol.rgb;",
    "  spangle *= mix(vec3(1.0), mainSample.rgb, uMatcapSpanColTexAdd);",
    "  spangle = mix(cap.rgb, spangle, mask.b);",
    "  vec3 bright = mix(spangle, (spangle * uMatcapBrightG + mainSample.rgb), uMatcapTexAdd);",
    "  bright = mix(mainSample.rgb, bright, mask.g * uMatcapIntensity.rgb);",
    "  vec3 darken = mainSample.rgb * uMatcapTexDarkenR;",
    "  vec3 metallicLow = 2.0 * darken * cap.a;",
    "  vec3 metallicHigh = 1.0 - 2.0 * (1.0 - darken) * (1.0 - cap.a);",
    "  vec3 metallic = mix(metallicLow, metallicHigh, step(vec3(0.5), darken));",
    "  metallic = mix(vec3(cap.a), metallic, uMatcapTexAdd) * uMatcapBrightR;",
    "  metallic = mix(mainSample.rgb, metallic, mask.r * uMatcapIntensity.rgb);",
    "  vec3 combined = mix(metallic, bright, mask.g);",
    "  return mix(maskedBase, combined, uMatcapIntensity.a);",
    "}",
    "void main() {",
    // The reference APK uses Gamma color space. Sampling PNG bytes and emitting
    // their gamma-space result is intentional; Three's sRGB decoding/encoding
    // chunks must not turn the source's .35 multiplier into a linear operation.
    "  vec4 mainSample = texture2D(uMainTex, vSifasUv, uMainTexMipmapBias);",
    "  vec3 rgb = mainSample.rgb * (vSifasMask.b < 0.1 ? 0.35 : 1.0);",
    "  #ifdef SIFAS_CHEEK",
    // Unity UVs and decoded PNGs are flipped by the converter. Conjugating the
    // source cheek UV transform (2.22*v - 1.221) gives 2.22*v + .001 here.
    "    vec3 cheek = texture2D(uCheekTex, vSifasUv * 2.22 + vec2(0.0, 0.00100005)).rgb;",
    "    rgb *= mix(vec3(1.0), cheek, uCheekIntensity);",
    "  #endif",
    "  #ifdef SIFAS_MATCAP",
    "    rgb = applyMatcap(mainSample, rgb);",
    "  #endif",
    "  rgb = mix(rgb, uAmbientColor.rgb, uAmbientColor.a);",
    "  rgb *= mix(vec3(1.0), uTintColor.rgb, uTintColor.a);",
    "  #ifdef SIFAS_EMISSIVE",
    "    vec2 scrollUv = vSifasUv + vec2(uEmissiveFlicker.x, -uEmissiveFlicker.y) * uBeat;",
    "    vec4 emission = texture2D(uEmissiveScrollTex, scrollUv) * texture2D(uEmissiveTex, vSifasUv) * uEmissiveIntensity;",
    "    rgb += emission.rgb * emission.a;",
    "  #endif",
    "  #ifdef SIFAS_RIMLIGHT",
    "    float rim = pow(1.0 - clamp(dot(vSifasRimDirection, vSifasViewNormal), 0.0, 1.0), uRimglightPower);",
    "    rim *= texture2D(uRimlightTex, vSifasUv).r * uRimlightColor.a * uRimglightIntensity;",
    "    rgb += rim * uRimlightColor.rgb;",
    "  #endif",
    "  gl_FragColor = max(vec4(rgb, mainSample.a), vec4(0.0));",
    "}"
  ].join("\n");

  var OUTLINE_VERTEX = [
    "#include <common>",
    "#include <morphtarget_pars_vertex>",
    "#include <skinning_pars_vertex>",
    "attribute vec4 _sifas_color;",
    "uniform sampler2D uMainTex;",
    "uniform vec4 uTintColor;",
    "uniform vec4 uAmbientColor;",
    "uniform float uResolutionRatio;",
    "varying vec4 vSifasOutlineColor;",
    "void main() {",
    "  #include <beginnormal_vertex>",
    "  #include <morphnormal_vertex>",
    "  #include <skinbase_vertex>",
    "  #include <skinnormal_vertex>",
    "  #include <begin_vertex>",
    "  #include <morphtarget_vertex>",
    "  #include <skinning_vertex>",
    "  #include <project_vertex>",
    "  vec3 outlineNormal = normalMatrix * objectNormal;",
    "  outlineNormal /= max(length(outlineNormal), 0.000001);",
    "  float distanceFactor = max(-mvPosition.z, 0.0) * clamp(uResolutionRatio, 0.0, 1.0);",
    "  distanceFactor /= max(abs(projectionMatrix[1][1]) * 0.267949194, 0.000001);",
    "  distanceFactor = distanceFactor < 0.9 ? distanceFactor * 1.11111116 : distanceFactor * 0.555555582 + 0.5;",
    "  distanceFactor *= projectionMatrix[3][3] == 0.0 ? 1.0 : 0.0;",
    "  vec2 shift = vec2(projectionMatrix[0][0], projectionMatrix[1][1]) * outlineNormal.xy * _sifas_color.r;",
    "  gl_Position.xy += shift * distanceFactor * 0.001;",
    "  gl_Position.z += (1.0 - _sifas_color.g) * 0.0007;",
    "  vec4 texel = texture2D(uMainTex, uv);",
    "  vec3 rgb = mix(texel.rgb * 0.35, uAmbientColor.rgb, uAmbientColor.a);",
    "  rgb *= mix(vec3(1.0), uTintColor.rgb, uTintColor.a);",
    "  vSifasOutlineColor = vec4(rgb, texel.a);",
    "}"
  ].join("\n");
  var OUTLINE_FRAGMENT = "varying vec4 vSifasOutlineColor;\nvoid main() { gl_FragColor = vSifasOutlineColor; }";

  function metadata(material) {
    var data = material && material.userData && material.userData.sifas;
    return data && data.version === 1 && data.shader === "AS/Member" ? data : null;
  }
  function finite(value, fallback) {
    return typeof value === "number" && isFinite(value) && Math.abs(value) <= 65504 ? value : fallback;
  }
  function vector(T, value, fallback) {
    value = Array.isArray(value) ? value : fallback;
    return new T.Vector4(finite(value[0], fallback[0]), finite(value[1], fallback[1]),
      finite(value[2], fallback[2]), finite(value[3], fallback[3]));
  }

  function apply(root, renderer, options) {
    options = options || {};
    var T = global.THREE;
    if (!T || !root || !renderer) throw new Error("The shader renderer is unavailable.");
    var enabled = options.enabled !== false;
    var disposed = false;
    var loading = true;
    var beat = 0;
    var entries = [];
    var originalMaterials = new Map();
    var ownedMaterials = new Set();
    var ownedTextures = new Set();
    var baselineTextures = new Set();
    var baselineImages = new Set();
    var auxiliaryOriginals = new Set();
    var auxiliaryImages = new Set();
    var releasedTextures = new Set();
    var closedImages = new Set();
    var materialCache = new Map();
    var textureCache = new Map();
    var recognized = new Set();
    var limitations = new Set();
    var pending = [];
    var parser = options.parser;
    var animated = false;
    var state = { recognizedMaterials: 0, meshes: 0, outlines: 0, gpuInvalidations: 0, pipeline: "gamma",
      source: "AS/Member", implementation: "reconstructed", gamePixelParityVerified: false };

    function releaseTexture(texture) {
      if (texture && !releasedTextures.has(texture)) {
        releasedTextures.add(texture);
        texture.dispose();
      }
    }
    function closeImage(image) {
      if (image && !baselineImages.has(image) && !closedImages.has(image) && typeof image.close === "function") {
        closedImages.add(image);
        image.close();
      }
    }

    root.traverse(function (mesh) {
      if (!mesh.isMesh || mesh.userData.viewerHelper) return;
      originalMaterials.set(mesh, mesh.material);
      var list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      list.forEach(function (material) {
        if (!material) return;
        Object.keys(material).forEach(function (key) {
          if (material[key] && material[key].isTexture) {
            baselineTextures.add(material[key]);
            if (material[key].image) baselineImages.add(material[key].image);
          }
        });
      });
    });

    function constantTexture(value) {
      var key = "constant:" + value.join(",");
      if (textureCache.has(key)) return textureCache.get(key);
      var rgba = value.map(function (v) { return Math.max(0, Math.min(255, Math.round(v * 255))); });
      var texture = new T.DataTexture(new Uint8Array(rgba), 1, 1, T.RGBAFormat);
      texture.minFilter = texture.magFilter = T.NearestFilter;
      texture.generateMipmaps = false;
      texture.encoding = T.LinearEncoding;
      texture.needsUpdate = true;
      ownedTextures.add(texture);
      textureCache.set(key, texture);
      return texture;
    }

    function loadTexture(info, fallback, originalMap) {
      if (!info || info.default) return Promise.resolve(constantTexture(info && info.default || fallback));
      var key = "index:" + info.index;
      if (textureCache.has(key)) return textureCache.get(key);
      var promise;
      if (parser && typeof parser.getDependency === "function" && typeof info.index === "number") {
        promise = parser.getDependency("texture", info.index);
      } else if (originalMap) promise = Promise.resolve(originalMap);
      else {
        limitations.add("Auxiliary shader texture loading is unavailable.");
        return Promise.resolve(constantTexture(fallback));
      }
      promise = promise.then(function (original) {
        if (!original || !original.isTexture) throw new Error("Invalid shader texture");
        var chain = Array.isArray(info.mipmaps) ? info.mipmaps : [];
        var mipRequests = chain.length > 1 && parser && typeof parser.getDependency === "function"
          ? chain.slice(1, 14).map(function (index) { return parser.getDependency("texture", index); }) : [];
        return Promise.all(mipRequests).then(function (mips) { return { original: original, mips: mips }; });
      }).then(function (loaded) {
        if (disposed) {
          [loaded.original].concat(loaded.mips).forEach(function (texture) {
            if (texture && !baselineTextures.has(texture)) { releaseTexture(texture); closeImage(texture.image); }
          });
          return null;
        }
        var original = loaded.original;
        [original].concat(loaded.mips).forEach(function (item) {
          if (!item || !item.isTexture) throw new Error("Invalid authored mip texture");
          if (!baselineTextures.has(item)) auxiliaryOriginals.add(item);
          if (item.image && !baselineImages.has(item.image)) auxiliaryImages.add(item.image);
        });
        var texture = original.clone();
        // Pixel bytes and wrapping are shared unchanged. Only the sampling
        // color-space flag differs: the source APK calculates in Gamma space.
        texture.encoding = T.LinearEncoding;
        texture.generateMipmaps = false;
        texture.magFilter = info.filterMode === 0 ? T.NearestFilter : T.LinearFilter;
        texture.minFilter = texture.magFilter;
        if (loaded.mips.length) {
          var images = [original].concat(loaded.mips).map(function (item) { return item.image; });
          var width = images[0].width, height = images[0].height;
          var pot = T.MathUtils.isPowerOfTwo(width) && T.MathUtils.isPowerOfTwo(height);
          var valid = images.length === Math.floor(Math.log(Math.max(width, height)) / Math.LN2) + 1;
          images.forEach(function (image, level) {
            valid = valid && image && image.width === Math.max(1, width >> level)
              && image.height === Math.max(1, height >> level);
          });
          if (valid && (renderer.capabilities.isWebGL2 || pot)) {
            texture.mipmaps = images;
            texture.minFilter = info.filterMode === 0 ? T.NearestMipmapNearestFilter
              : info.filterMode === 2 ? T.LinearMipmapLinearFilter : T.LinearMipmapNearestFilter;
          } else limitations.add("Authored mip levels are unavailable for this WebGL texture.");
        }
        texture.needsUpdate = true;
        ownedTextures.add(texture);
        return texture;
      }).catch(function () {
        if (disposed) return null;
        limitations.add("A shader texture could not be loaded.");
        return constantTexture(fallback);
      });
      textureCache.set(key, promise);
      return promise;
    }

    function makeMaterials(original, data, mesh) {
      var morph = !!(mesh.geometry.morphAttributes && mesh.geometry.morphAttributes.position && mesh.geometry.morphAttributes.position.length);
      var morphNormals = morph && !!(mesh.geometry.morphAttributes.normal && mesh.geometry.morphAttributes.normal.length);
      var key = original.uuid + ":" + !!mesh.isSkinnedMesh + ":" + morph + ":" + morphNormals;
      if (materialCache.has(key)) return materialCache.get(key);
      recognized.add(original);
      var colors = data.colors || {}, floats = data.floats || {}, features = data.features || {};
      (data.limitations || []).forEach(function (item) { limitations.add(String(item)); });
      var uniforms = {
        uMainTex: { value: constantTexture([1, 1, 1, 1]) },
        uRimlightTex: { value: constantTexture([1, 1, 1, 1]) },
        uMatcapTex: { value: constantTexture([1, 1, 1, 1]) },
        uMatcapMaskTex: { value: constantTexture([1, 1, 1, 1]) },
        uEmissiveTex: { value: constantTexture([0, 0, 0, 1]) },
        uEmissiveScrollTex: { value: constantTexture([1, 1, 1, 1]) },
        uCheekTex: { value: constantTexture([1, 1, 1, 1]) },
        uTintColor: { value: vector(T, colors._TintColor, [1, 1, 1, 1]) },
        uAmbientColor: { value: vector(T, colors._AmbientColor, [1, 1, 1, 0]) },
        uRimlightColor: { value: vector(T, colors._RimlightColor, [1, 1, 1, 1]) },
        uRimlightDirection: { value: vector(T, colors._RimlightDirection, [0, 0, 0, 0]) },
        uMatcapIntensity: { value: vector(T, colors._MatcapIntensity, [1, 1, 1, 1]) },
        uMatcapSpanCol: { value: vector(T, colors._MatcapSpanCol, [1, 1, 1, 1]) },
        uEmissiveIntensity: { value: vector(T, colors._EmissiveIntensity, [1, 1, 1, 1]) },
        uEmissiveFlicker: { value: vector(T, colors._EmissiveFlicker, [.1, .1, 0, 0]) },
        uResolutionRatio: { value: finite(options.resolutionRatio, 1) },
        uBeat: { value: 0 }
      };
      var defaults = { _RimglightIntensity: 1, _RimglightPower: 3, _MainTexMipmapBias: 0,
        _MatcapTexAdd: 0, _MatcapSpanColTexAdd: 0, _MatcapTexDarkenR: 1,
        _MatcapBrightR: 1, _MatcapBrightG: 1, _CheekIntensity: 0 };
      Object.keys(defaults).forEach(function (name) { uniforms["u" + name.slice(1)] = { value: finite(floats[name], defaults[name]) }; });
      uniforms.uRimglightPower.value = Math.max(.0001, uniforms.uRimglightPower.value);
      var defines = {};
      ["rimlight", "matcap", "emissive", "cheek"].forEach(function (name) {
        if (features[name]) defines["SIFAS_" + name.toUpperCase()] = 1;
      });
      var parameters = { vertexShader: VERTEX, fragmentShader: FRAGMENT, uniforms: uniforms,
        defines: defines, skinning: !!mesh.isSkinnedMesh, morphTargets: morph,
        morphNormals: morphNormals, depthTest: true, depthWrite: true,
        side: floats._CullMode === 0 ? T.DoubleSide : floats._CullMode === 1 ? T.BackSide : T.FrontSide,
        blending: T.NoBlending, transparent: false, toneMapped: false,
        stencilWrite: true, stencilRef: 1, stencilFunc: T.AlwaysStencilFunc,
        stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.ReplaceStencilOp };
      var main = new T.ShaderMaterial(parameters);
      main.name = original.name + " (AS/Member)";
      main.userData.sifas = data;
      main.defaultAttributeValues._sifas_color = [1, 1, 1, 1];
      var outlineParameters = Object.assign({}, parameters, {
        vertexShader: OUTLINE_VERTEX, fragmentShader: OUTLINE_FRAGMENT,
        uniforms: uniforms, side: T.BackSide, defines: {},
        stencilZPass: T.KeepStencilOp,
        stencilFunc: [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc,
          T.EqualStencilFunc, T.LessEqualStencilFunc, T.GreaterStencilFunc,
          T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc][Math.floor(finite(floats._OutlineStencilComp, 8))] || T.AlwaysStencilFunc
      });
      var outline = new T.ShaderMaterial(outlineParameters);
      outline.name = original.name + " (AS/Member outline)";
      outline.userData.viewerHelper = true;
      outline.defaultAttributeValues._sifas_color = [1, 1, 1, 1];
      ownedMaterials.add(main); ownedMaterials.add(outline);
      var pair = { main: main, outline: outline, uniforms: uniforms, features: features };
      materialCache.set(key, pair);
      if (features.emissive) {
        animated = true;
        limitations.add("Preview emissive timing is not synchronized to game music.");
      }
      var textures = data.textures || {};
      var names = ["_MainTex"];
      if (features.rimlight) names.push("_RimlightTex");
      if (features.matcap) names.push("_MatcapTex", "_MatcapMaskTex");
      if (features.emissive) names.push("_EmissiveTex", "_EmissiveScrollTex");
      if (features.cheek && uniforms.uCheekIntensity.value !== 0) names.push("_CheekTex");
      names.forEach(function (name) {
        pending.push(loadTexture(textures[name], name === "_EmissiveTex" ? [0, 0, 0, 1] : [1, 1, 1, 1], name === "_MainTex" ? original.map : null)
          .then(function (texture) { if (!disposed && texture) uniforms["u" + name.slice(1)].value = texture; }));
      });
      return pair;
    }

    var meshes = [];
    root.traverse(function (mesh) { if (mesh.isMesh && !mesh.userData.viewerHelper) meshes.push(mesh); });
    meshes.forEach(function (mesh) {
      var originals = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      var hasMember = originals.some(function (material) { return !!metadata(material); });
      if (!hasMember) return;
      var pairs = originals.map(function (material) { var data = metadata(material); return data ? makeMaterials(material, data, mesh) : null; });
      var main = pairs.map(function (pair, index) { return pair ? pair.main : originals[index]; });
      var skip = null;
      var outline = pairs.map(function (pair) {
        if (pair) return pair.outline;
        if (!skip) { skip = new T.MeshBasicMaterial(); skip.visible = false; ownedMaterials.add(skip); }
        return skip;
      });
      var helper = mesh.isSkinnedMesh ? new T.SkinnedMesh(mesh.geometry, Array.isArray(mesh.material) ? outline : outline[0])
        : new T.Mesh(mesh.geometry, Array.isArray(mesh.material) ? outline : outline[0]);
      helper.name = "SIFAS outline";
      helper.userData.viewerHelper = true;
      helper.userData.sifasOutline = true;
      helper.frustumCulled = false;
      helper.renderOrder = mesh.renderOrder + .01;
      if (mesh.isSkinnedMesh) {
        helper.bindMode = mesh.bindMode;
        helper.bind(mesh.skeleton, mesh.bindMatrix);
      }
      if (mesh.morphTargetInfluences) helper.morphTargetInfluences = mesh.morphTargetInfluences;
      if (mesh.morphTargetDictionary) helper.morphTargetDictionary = mesh.morphTargetDictionary;
      mesh.add(helper);
      var entry = { mesh: mesh, original: mesh.material,
        custom: Array.isArray(mesh.material) ? main : main[0], helper: helper };
      entries.push(entry);
      mesh.material = enabled ? entry.custom : entry.original;
      helper.visible = enabled;
    });
    state.recognizedMaterials = recognized.size;
    state.meshes = entries.length;
    state.outlines = entries.length;
    var ready = Promise.all(pending).then(function () {
      loading = false;
      if (!disposed && options.onChange) options.onChange();
      return controller;
    });
    var controller = {
      ready: ready,
      setEnabled: function (value) {
        if (disposed) return;
        enabled = !!value;
        entries.forEach(function (entry) {
          entry.mesh.material = enabled ? entry.custom : entry.original;
          entry.helper.visible = enabled;
        });
        if (options.onChange) options.onChange();
      },
      getMaterial: function (mesh) {
        for (var i = 0; i < entries.length; i += 1) {
          if (entries[i].mesh === mesh) return enabled ? entries[i].custom : entries[i].original;
        }
        return originalMaterials.has(mesh) ? originalMaterials.get(mesh) : mesh.material;
      },
      update: function (delta) {
        if (disposed || !enabled || loading || !animated) return false;
        beat += Math.max(0, Math.min(.1, finite(delta, 0))) * finite(options.beatsPerSecond, 1);
        materialCache.forEach(function (pair) { pair.uniforms.uBeat.value = beat; });
        return true;
      },
      setBeat: function (value) {
        beat = finite(value, 0);
        materialCache.forEach(function (pair) { pair.uniforms.uBeat.value = beat; });
        if (options.onChange) options.onChange();
      },
      getState: function () {
        return Object.assign({}, state, { enabled: enabled, loading: loading, disposed: disposed,
          animated: enabled && animated, ownedMaterials: ownedMaterials.size,
          ownedTextures: ownedTextures.size, limitations: Array.from(limitations) });
      },
      invalidateGPU: function () {
        if (disposed) return;
        // Called while WebGL is lost: release renderer listeners/old-context
        // handles now, retaining every CPU image, mip level, uniform and node.
        // Releasing after restoration can otherwise send stale WebGL objects
        // to the new context. This is not final resource/image disposal.
        var materials = new Set(), textures = new Set();
        function material(value) {
          if (Array.isArray(value)) { value.forEach(material); return; }
          if (!value || materials.has(value)) return;
          materials.add(value);
          Object.keys(value).forEach(function (key) {
            if (value[key] && value[key].isTexture) textures.add(value[key]);
          });
          Object.keys(value.uniforms || {}).forEach(function (key) {
            var item = value.uniforms[key].value;
            if (item && item.isTexture) textures.add(item);
            else if (Array.isArray(item)) item.forEach(function (entry) { if (entry && entry.isTexture) textures.add(entry); });
          });
        }
        ownedMaterials.forEach(material);
        originalMaterials.forEach(material);
        ownedTextures.forEach(function (texture) { textures.add(texture); });
        auxiliaryOriginals.forEach(function (texture) { textures.add(texture); });
        materials.forEach(function (item) { item.dispose(); item.needsUpdate = true; });
        textures.forEach(function (texture) { texture.dispose(); texture.needsUpdate = true; });
        state.gpuInvalidations += 1;
      },
      dispose: function () {
        if (disposed) return;
        disposed = true;
        entries.forEach(function (entry) {
          entry.mesh.material = entry.original;
          entry.mesh.remove(entry.helper);
        });
        originalMaterials.forEach(function (material, mesh) { mesh.material = material; });
        ownedMaterials.forEach(function (material) { material.dispose(); });
        ownedTextures.forEach(releaseTexture);
        auxiliaryOriginals.forEach(releaseTexture);
        auxiliaryImages.forEach(closeImage);
        ownedMaterials.clear(); ownedTextures.clear(); auxiliaryOriginals.clear(); auxiliaryImages.clear();
        entries.length = 0;
        originalMaterials.clear();
        materialCache.clear(); textureCache.clear();
      }
    };
    return controller;
  }

  var api = { apply: apply, vertexShader: VERTEX, fragmentShader: FRAGMENT,
    outlineVertexShader: OUTLINE_VERTEX, outlineFragmentShader: OUTLINE_FRAGMENT };
  global.SifasMaterial = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
}(typeof window !== "undefined" ? window : globalThis));
