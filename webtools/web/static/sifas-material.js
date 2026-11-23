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

  // An edge-on inner-mouth triangle can cover one MSAA sample while the
  // pixel center lies outside it. A center-extrapolated depth can then put
  // that rear surface in front of the skin. Evaluate depth at a covered
  // centroid, retaining the original geometry, texture and sample count.
  // These qualifiers/gl_FragDepth are enabled only for verified mouth nodes
  // on WebGL2. Keep the original programs byte-for-byte for every other mesh.
  var MOUTH_VERTEX = "centroid varying vec2 vSifasMouthClipZW;\n" + VERTEX.replace(/\n}$/, "\n  vSifasMouthClipZW = gl_Position.zw;\n}");
  var MOUTH_FRAGMENT = "centroid varying vec2 vSifasMouthClipZW;\n" + FRAGMENT.replace(/\n}$/, [
    "\n  float mouthDepth = 0.5 * (vSifasMouthClipZW.x / vSifasMouthClipZW.y) + 0.5;",
    "  gl_FragDepth = gl_DepthRange.near + gl_DepthRange.diff * mouthDepth;",
    "}"
  ].join("\n"));

  var OUTLINE_VERTEX = [
    "#include <common>",
    "#include <morphtarget_pars_vertex>",
    "#include <skinning_pars_vertex>",
    "attribute vec4 _sifas_color;",
    "uniform sampler2D uMainTex;",
    "uniform vec4 uTintColor;",
    "uniform vec4 uAmbientColor;",
    "uniform float uResolutionRatio;",
    "uniform float uOutlineScale;",
    "uniform float uOutlineEdited;",
    "uniform float uOutlineQuantized;",
    "attribute float _sifas_outline_width;",
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
    "  float outlineWidth = _sifas_color.r;",
    "  if (uOutlineEdited > 0.5) {",
    "    outlineWidth = clamp(outlineWidth * uOutlineScale, 0.0, 1.0);",
    "    if (uOutlineQuantized > 0.5) outlineWidth = floor(outlineWidth * 255.0 + 0.5) / 255.0;",
    "  }",
    "  if (_sifas_outline_width >= 0.0) outlineWidth = _sifas_outline_width;",
    "  vec2 shift = vec2(projectionMatrix[0][0], projectionMatrix[1][1]) * outlineNormal.xy * outlineWidth;",
    "  gl_Position.xy += shift * distanceFactor * 0.001;",
    "  gl_Position.z += (1.0 - _sifas_color.g) * 0.0007;",
    "  vec4 texel = texture2D(uMainTex, uv);",
    "  vec3 rgb = mix(texel.rgb * 0.35, uAmbientColor.rgb, uAmbientColor.a);",
    "  rgb *= mix(vec3(1.0), uTintColor.rgb, uTintColor.a);",
    "  vSifasOutlineColor = vec4(rgb, texel.a);",
    "}"
  ].join("\n");
  var OUTLINE_FRAGMENT = "varying vec4 vSifasOutlineColor;\nvoid main() { gl_FragColor = vSifasOutlineColor; }";
  // Back-facing inner-mouth surfaces also participate in the native outline
  // pass, including vertices with zero width. Keep its expansion/color intact
  // and capture clip depth only after the original outline XY and Z shifts.
  var MOUTH_OUTLINE_VERTEX = "centroid varying vec2 vSifasMouthClipZW;\n" + OUTLINE_VERTEX.replace(/\n}$/, "\n  vSifasMouthClipZW = gl_Position.zw;\n}");
  var MOUTH_OUTLINE_FRAGMENT = "centroid varying vec2 vSifasMouthClipZW;\n" + OUTLINE_FRAGMENT.replace(/}\s*$/, [
    "float mouthDepth = 0.5 * (vSifasMouthClipZW.x / vSifasMouthClipZW.y) + 0.5;",
    "  gl_FragDepth = gl_DepthRange.near + gl_DepthRange.diff * mouthDepth;",
    "}"
  ].join("\n"));

  // MainProp's UV2 angle is already applied to position by MVStudioProps.
  // Its source normal is unchanged and the rim direction is in view space.
  var PROP_VERTEX = [
    "attribute mediump vec4 _sifas_color;",
    "uniform vec4 uRimlightDirection;",
    "varying vec2 vPropUv;",
    "varying mediump float vPropBlue;",
    "varying vec3 vPropNormal;",
    "varying vec3 vPropRimDirection;",
    "void main() {",
    "  vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);",
    "  gl_Position = projectionMatrix * viewPosition;",
    "  vPropUv = uv;",
    "  vPropBlue = _sifas_color.b;",
    "  vPropNormal = mat3(modelViewMatrix) * normal;",
    "  vPropRimDirection = normalize(-viewPosition.xyz - uRimlightDirection.xyz);",
    "}"
  ].join("\n");
  var PROP_FRAGMENT = [
    "uniform sampler2D uMainTex;",
    "uniform sampler2D uRimlightTex;",
    "uniform mediump vec4 uTintColor;",
    "uniform mediump vec4 uAmbientColor;",
    "uniform mediump vec4 uRimlightColor;",
    "uniform mediump float uRimglightIntensity;",
    "uniform mediump float uRimglightPower;",
    "uniform float uMainTexMipmapBias;",
    "varying vec2 vPropUv;",
    "varying mediump float vPropBlue;",
    "varying vec3 vPropNormal;",
    "varying vec3 vPropRimDirection;",
    "void main() {",
    "  mediump vec4 texel = texture2D(uMainTex, vPropUv, uMainTexMipmapBias);",
    "  mediump vec3 rgb = texel.rgb * (vPropBlue < 0.1 ? 0.35 : 1.0);",
    "  rgb = mix(rgb, uAmbientColor.rgb, uAmbientColor.a);",
    "  rgb = mix(rgb, rgb * uTintColor.rgb, uTintColor.a);",
    "  mediump float rim = pow(1.0 - clamp(dot(vPropRimDirection, vPropNormal), 0.0, 1.0), uRimglightPower);",
    "  rim *= texture2D(uRimlightTex, vPropUv).r * (uRimlightColor.a * uRimglightIntensity);",
    "  rgb += rim * uRimlightColor.rgb;",
    "  gl_FragColor = max(vec4(rgb, texel.a), vec4(0.0));",
    "}"
  ].join("\n");
  // The native MainProp OUTLINE pass shades unexpanded back faces, with
  // the original main texture sampled at LOD 0 before interpolation.
  var PROP_OUTLINE_VERTEX = [
    "uniform sampler2D uMainTex;",
    "uniform mediump vec4 uTintColor;",
    "uniform mediump vec4 uAmbientColor;",
    "varying mediump vec4 vSifasOutlineColor;",
    "void main() {",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "  #if __VERSION__ >= 300",
    "    mediump vec4 texel = textureLod(uMainTex, uv, 0.0);",
    "  #else",
    "    mediump vec4 texel = texture2DLod(uMainTex, uv, 0.0);",
    "  #endif",
    "  mediump vec3 rgb = mix(texel.rgb * 0.35, uAmbientColor.rgb, uAmbientColor.a);",
    "  vSifasOutlineColor = vec4(mix(rgb, rgb * uTintColor.rgb, uTintColor.a), texel.a);",
    "}"
  ].join("\n");
  var PROP_OUTLINE_FRAGMENT = OUTLINE_FRAGMENT.replace("varying vec4", "varying mediump vec4");
  var PROP_TEXTURE_SIZES = { _MainTex: 1024, _RimlightTex: 256 };

  function validPropTexture(info, size) {
    var levels = info?.mipmaps;
    return info?.filterMode === 1 && !info.default && Array.isArray(levels) && levels.length === Math.log2(size) + 1 &&
      levels[0] === info.index && levels.every((index) => Number.isInteger(index) && index >= 0) &&
      new Set(levels).size === levels.length;
  }

  function metadata(material, mesh, memberProp) {
    var data = material && material.userData && material.userData.sifas;
    if (data?.version !== 1) return null;
    if (!memberProp) return data.shader === "AS/Member" ? data : null;
    var { position, normal, uv, _sifas_color: color, _mv_fan_uv: fan } = mesh.geometry.attributes;
    if (data.shader !== "AS/MemberProp" || data.pipeline !== "gamma" || data.floats?._CullMode !== 2 ||
        data.floats?._OutlineStencilComp !== 8 || !data.features?.rimlight || !data.features?.outline ||
        mesh.isSkinnedMesh || !position || !normal || !uv || color?.itemSize !== 4 || fan?.itemSize !== 2 ||
        color.count !== position.count || fan.count !== position.count ||
        !Object.entries(PROP_TEXTURE_SIZES).every(([name, size]) => validPropTexture(data.textures?.[name], size))) return null;
    return data;
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
    var memberProp = options.memberProp === true;
    // A live MV performer: CommonCoreMember.Initialize runs
    // LiveCoreMemberRimlight.Initialize then ApplyIntensity(0), so the rim
    // starts at intensity 0 (outline stencil Always) and the timeline decides.
    var liveMember = options.liveMember === true && !memberProp;
    var rimlightEnabled = memberProp || options.rimlight !== false;
    var mouthCentroidDepth = options.mouthCentroidDepth === true &&
      !!(renderer.capabilities && renderer.capabilities.isWebGL2);
    var disposed = false;
    var loading = true;
    var beat = 0;
    var entries = [];
    var outlineFactors = {};
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
    var releaseParserAfterLoad = options.releaseParserAfterLoad === true;
    // In the MV preview the material outlives the loader, whose parser caches
    // the original GLB and all buffer views. Track texture bindings separately.
    if (releaseParserAfterLoad) options = Object.assign({}, options, { parser: null });
    var textureBindings = [], textureOverrides = new Map();
    var animated = false;
    var state = { recognizedMaterials: 0, meshes: 0, outlines: 0, gpuInvalidations: 0, pipeline: "gamma",
      source: memberProp ? "AS/MemberProp" : "AS/Member", implementation: "reconstructed", gamePixelParityVerified: false };

    function textureIdentityKey(identity) {
      if (!identity || !Number.isInteger(identity.source) || !Number.isInteger(identity.file) || typeof identity.id !== "string") return "";
      return identity.source + ":" + identity.file + ":" + identity.id;
    }
    function textureIdentity(info, original) {
      var definition = parser && parser.json && parser.json.textures && info && parser.json.textures[info.index];
      return definition && definition.extras && definition.extras.viewerTexture ||
        original && original.userData && original.userData.viewerTexture || null;
    }
    function applyTextureBinding(binding) {
      var override = textureOverrides.get(binding.key);
      if (override && binding.baseline) {
        // Shader pixels use the game's Gamma convention, independently of the
        // generic glTF map's sRGB flag. New mip levels come from edited pixels.
        var target = override.texture, original = binding.baseline;
        target.encoding = T.LinearEncoding;
        target.flipY = original.flipY; target.wrapS = original.wrapS; target.wrapT = original.wrapT;
        target.magFilter = original.magFilter; target.minFilter = original.minFilter;
        target.mipmaps = []; target.generateMipmaps = !!(original.mipmaps && original.mipmaps.length) || original.generateMipmaps;
        target.needsUpdate = true;
      }
      if (binding.baseline) binding.uniform.value = override ? override.texture : binding.baseline;
    }
    function clearTextureOverride(key) {
      var previous = textureOverrides.get(key);
      if (!previous) return;
      textureOverrides.delete(key);
      textureBindings.forEach(function (binding) { if (binding.key === key) applyTextureBinding(binding); });
      ownedTextures.delete(previous.texture);
      previous.texture.dispose();
    }

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

    function stencilFunction(comparison) {
      return [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc,
        T.EqualStencilFunc, T.LessEqualStencilFunc, T.GreaterStencilFunc,
        T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc][comparison] || T.AlwaysStencilFunc;
    }

    function setOutlineStencil(pair, comparison) {
      if (pair.outlineStencilComp === comparison) return;
      pair.outlineStencilComp = comparison;
      pair.outline.stencilFunc = stencilFunction(comparison);
      pair.main.userData.sifasRuntime.outlineStencilComp = comparison;
    }

    // LiveCoreMemberRimlight.ApplyIntensity / ApplyBaseIntensity ->
    // ApplyEnable(final > 0); on the current (non-legacy) shader that only sets
    // _OutlineStencilComp: 3 (Equal, the outline is kept over stencil-1 member
    // pixels) while the rim is lit, 8 (Always) otherwise. The stencil follows
    // the rim the material draws, so a rim switched off here (setRimlight)
    // draws as intensity 0 and keeps Always.
    function liveOutlineStencil(pair) {
      return rimlightEnabled && pair.uniforms.uRimglightIntensity.value > 0 ? 3 : 8;
    }

    function cheekLayer(pair, index) {
      var layer = Math.floor(finite(index, 0) + .5);
      if (pair.cheekDepth > 0) layer = Math.min(pair.cheekDepth - 1, Math.max(0, layer));
      return pair.cheekLayers[layer] || null;
    }

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

    function loadTexture(info, fallback, originalMap, propSize) {
      if (!info || info.default) return Promise.resolve(constantTexture(info && info.default || fallback));
      var key = "index:" + info.index + (propSize ? ":" + propSize : "");
      if (textureCache.has(key)) return textureCache.get(key);
      var promise;
      if (propSize) {
        if (!parser || typeof parser.getDependency !== "function") return Promise.resolve(null);
        var source = parser;
        // Wait for every requested mip so a failed request cannot strand
        // other parser textures during cancellation or fallback.
        promise = Promise.all(info.mipmaps.map((index) => Promise.resolve()
          .then(() => source.getDependency("texture", index)).catch(() => null)))
          .then(([original, ...mips]) => ({ original, mips }));
      } else if (parser && typeof parser.getDependency === "function" && typeof info.index === "number") {
        promise = parser.getDependency("texture", info.index);
      } else if (originalMap) promise = Promise.resolve(originalMap);
      else {
        limitations.add("Auxiliary shader texture loading is unavailable.");
        return Promise.resolve(constantTexture(fallback));
      }
      if (!propSize) promise = promise.then(function (original) {
        if (!original || !original.isTexture) throw new Error("Invalid shader texture");
        var chain = Array.isArray(info.mipmaps) ? info.mipmaps : [];
        var mipRequests = chain.length > 1 && parser && typeof parser.getDependency === "function"
          ? chain.slice(1, 14).map(function (index) { return parser.getDependency("texture", index); }) : [];
        return Promise.all(mipRequests).then(function (mips) { return { original: original, mips: mips }; });
      });
      promise = promise.then(function (loaded) {
        var original = loaded.original, originals = [original].concat(loaded.mips);
        if (disposed) {
          originals.forEach(function (texture) {
            if (texture?.isTexture && !baselineTextures.has(texture)) { releaseTexture(texture); closeImage(texture.image); }
          });
          return null;
        }
        originals.forEach(function (item) {
          if (!item?.isTexture) return;
          if (!baselineTextures.has(item)) auxiliaryOriginals.add(item);
          if (item.image && !baselineImages.has(item.image)) auxiliaryImages.add(item.image);
        });
        if (originals.some((item) => !item?.isTexture)) throw new Error("Invalid authored mip texture");
        if (propSize && originals.some((item, level) => item.image?.width !== (propSize >> level) ||
            item.image?.height !== (propSize >> level))) throw new Error("Invalid prop mip dimensions");
        var texture = original.clone();
        // The Unity asset this texture holds (an array slice keeps its array's
        // name and layer), reported by the MV asset dump.
        if (typeof info.name === "string" && info.name) texture.name = info.name;
        if (Number.isInteger(info.arrayLayer)) (texture.userData || (texture.userData = {})).sifasArrayLayer = info.arrayLayer;
        // Pixel bytes and wrapping are shared unchanged. Only the sampling
        // color-space flag differs: the source APK calculates in Gamma space.
        texture.encoding = T.LinearEncoding;
        texture.generateMipmaps = false;
        if (propSize) {
          texture.wrapS = texture.wrapT = T.RepeatWrapping;
          texture.flipY = false;
          texture.anisotropy = 1;
        }
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
        return propSize ? null : constantTexture(fallback);
      });
      textureCache.set(key, promise);
      return promise;
    }

    function makeMaterials(original, data, mesh) {
      var morph = !!(mesh.geometry.morphAttributes && mesh.geometry.morphAttributes.position && mesh.geometry.morphAttributes.position.length);
      var morphNormals = morph && !!(mesh.geometry.morphAttributes.normal && mesh.geometry.morphAttributes.normal.length);
      var mouthDepth = false;
      if (mouthCentroidDepth) {
        for (var ancestor = mesh; ancestor; ancestor = ancestor.parent) {
          if (ancestor.userData && ancestor.userData.viewerFacialRole === "mouth") { mouthDepth = true; break; }
          if (ancestor === root) break;
        }
      }
      var key = original.uuid + ":" + !!mesh.isSkinnedMesh + ":" + morph + ":" + morphNormals + (mouthDepth ? ":mouth-centroid-depth" : "");
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
        uOutlineScale: { value: 1 },
        uOutlineEdited: { value: 0 },
        uOutlineQuantized: { value: 1 },
        uBeat: { value: 0 }
      };
      var defaults = { _RimglightIntensity: 1, _RimglightPower: 3, _MainTexMipmapBias: 0,
        _MatcapTexAdd: 0, _MatcapSpanColTexAdd: 0, _MatcapTexDarkenR: 1,
        _MatcapBrightR: 1, _MatcapBrightG: 1, _CheekTexArrayIndex: 0, _CheekIntensity: 0 };
      Object.keys(defaults).forEach(function (name) { uniforms["u" + name.slice(1)] = { value: finite(floats[name], defaults[name]) }; });
      if (!memberProp) uniforms.uRimglightPower.value = Math.max(.0001, uniforms.uRimglightPower.value);
      if (liveMember) uniforms.uRimglightIntensity.value = 0;
      var defines = {};
      // A cheek array present without the authored _CHEEK_ON keyword is only
      // available to the runtime cheek (setCheek); the static variant follows
      // the material's own keyword.
      var cheekKeyword = !Array.isArray(data.keywords) || data.keywords.indexOf("_CHEEK_ON") >= 0;
      if (!memberProp) ["rimlight", "matcap", "emissive", "cheek"].forEach(function (name) {
        if (features[name] && (name !== "rimlight" || rimlightEnabled) && (name !== "cheek" || cheekKeyword)) {
          defines["SIFAS_" + name.toUpperCase()] = 1;
        }
      });
      var parameters = { vertexShader: memberProp ? PROP_VERTEX : mouthDepth ? MOUTH_VERTEX : VERTEX,
        fragmentShader: memberProp ? PROP_FRAGMENT : mouthDepth ? MOUTH_FRAGMENT : FRAGMENT, uniforms: uniforms,
        defines: defines, skinning: !!mesh.isSkinnedMesh, morphTargets: morph,
        morphNormals: morphNormals, depthTest: true, depthWrite: true,
        side: floats._CullMode === 0 ? T.DoubleSide : floats._CullMode === 1 ? T.BackSide : T.FrontSide,
        blending: T.NoBlending, transparent: false, toneMapped: false,
        stencilWrite: true, stencilRef: 1, stencilFunc: T.AlwaysStencilFunc,
        stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.ReplaceStencilOp };
      var main = new T.ShaderMaterial(parameters);
      main.name = original.name + " (" + data.shader + ")";
      main.userData.sifas = data;
      if (!memberProp && options.nativeMemberDepth) main.userData.mvStageMemberDepthRim = { value: 0 };
      main.defaultAttributeValues._sifas_color = [1, 1, 1, 1];
      // _OutlineStencilComp (UnityEngine.Rendering.CompareFunction): the
      // OUTLINE pass is Stencil Ref 1 Comp [_OutlineStencilComp] Pass Keep.
      var outlineStencilComp = liveMember ? 8 : Math.floor(finite(floats._OutlineStencilComp, 8));
      main.userData.sifasRuntime = { outlineStencilComp: outlineStencilComp };
      var outlineParameters = Object.assign({}, parameters, {
        vertexShader: memberProp ? PROP_OUTLINE_VERTEX : mouthDepth ? MOUTH_OUTLINE_VERTEX : OUTLINE_VERTEX,
        fragmentShader: memberProp ? PROP_OUTLINE_FRAGMENT : mouthDepth ? MOUTH_OUTLINE_FRAGMENT : OUTLINE_FRAGMENT,
        uniforms: uniforms, side: T.BackSide, defines: {},
        stencilZPass: T.KeepStencilOp,
        stencilFunc: stencilFunction(outlineStencilComp)
      });
      var outline = new T.ShaderMaterial(outlineParameters);
      outline.name = original.name + " (" + data.shader + " outline)";
      outline.userData.viewerHelper = true;
      outline.defaultAttributeValues._sifas_color = [1, 1, 1, 1];
      outline.defaultAttributeValues._sifas_outline_width = [-1];
      ownedMaterials.add(main); ownedMaterials.add(outline);
      var pair = { main: main, outline: outline, uniforms: uniforms, features: features, usable: true,
        sourceName: original.name, cheek: null, cheekLayers: [], cheekDepth: 0, outlineStencilComp: outlineStencilComp,
        ambient: uniforms.uAmbientColor.value.clone(), tint: uniforms.uTintColor.value.clone(),
        rim: { color: uniforms.uRimlightColor.value.clone(), direction: uniforms.uRimlightDirection.value.clone(),
          intensity: uniforms.uRimglightIntensity.value, power: uniforms.uRimglightPower.value } };
      materialCache.set(key, pair);
      if (!memberProp && features.emissive) {
        animated = true;
        limitations.add("Preview emissive timing is not synchronized to game music.");
      }
      var textures = data.textures || {};
      var names = memberProp ? Object.keys(PROP_TEXTURE_SIZES) : ["_MainTex"];
      if (!memberProp) {
        if (features.rimlight) names.push("_RimlightTex");
        if (features.matcap) names.push("_MatcapTex", "_MatcapMaskTex");
        if (features.emissive) names.push("_EmissiveTex", "_EmissiveScrollTex");
        if (features.cheek) names.push("_CheekTex");
        // Every exported slice of the cheek array, by array layer, for
        // MemberCheekBase.ApplyCheek's _CheekTexArrayIndex. Only a loaded,
        // exported slice can show a blush; the white placeholder never tints.
        var cheekSlot = textures._CheekTex;
        if (features.cheek && cheekSlot && !cheekSlot.default) {
          var layers = Array.isArray(cheekSlot.layers) ? cheekSlot.layers : [cheekSlot];
          // sampler2DArray clamps the rounded layer into the array; only a
          // complete export (every slice, in order) can be clamped here.
          if (Array.isArray(cheekSlot.layers) && cheekSlot.depth === layers.length &&
              layers.every(function (layer, slice) { return layer && layer.arrayLayer === slice; })) pair.cheekDepth = layers.length;
          layers.forEach(function (layer) {
            if (!layer || !Number.isInteger(layer.index) || !Number.isInteger(layer.arrayLayer) || layer.arrayLayer < 0) return;
            pending.push(loadTexture(layer, [1, 1, 1, 1]).then(function (texture) {
              if (!disposed && texture && texture !== constantTexture([1, 1, 1, 1])) pair.cheekLayers[layer.arrayLayer] = texture;
            }));
          });
        }
      }
      names.forEach(function (name) {
        var binding = { key: textureIdentityKey(textureIdentity(textures[name], name === "_MainTex" ? original.map : null)),
          uniform: uniforms["u" + name.slice(1)], baseline: null };
        textureBindings.push(binding);
        pending.push(loadTexture(textures[name], name === "_EmissiveTex" ? [0, 0, 0, 1] : [1, 1, 1, 1],
          name === "_MainTex" ? original.map : null, memberProp ? PROP_TEXTURE_SIZES[name] : undefined)
          .then(function (texture) {
            if (disposed) return;
            if (!texture) pair.usable = false;
            else { binding.baseline = texture; applyTextureBinding(binding); }
          }));
      });
      return pair;
    }

    function refreshEntry(entry) {
      var active = enabled && (!memberProp || (!loading && entry.pairs.every((pair) => pair?.usable)));
      entry.mesh.material = active ? entry.custom : entry.original;
      entry.helper.visible = active;
      if (memberProp) {
        // The ordinary opaque GLTF meshes use 0 as Geometry (2000).
        entry.mesh.renderOrder = active ? -100 : entry.renderOrder;
        entry.helper.renderOrder = entry.mesh.renderOrder + .01;
      }
    }

    var meshes = [];
    root.traverse(function (mesh) { if (mesh.isMesh && !mesh.userData.viewerHelper) meshes.push(mesh); });
    meshes.forEach(function (mesh) {
      var originals = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      var sources = originals.map(function (material) { return metadata(material, mesh, memberProp); });
      if (!sources.some(Boolean) || (memberProp && !sources.every(Boolean))) return;
      var pairs = sources.map(function (data, index) { return data ? makeMaterials(originals[index], data, mesh) : null; });
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
      var entry = { mesh: mesh, original: mesh.material, renderOrder: mesh.renderOrder, pairs: pairs,
        custom: Array.isArray(mesh.material) ? main : main[0], helper: helper };
      if (!memberProp) helper.onBeforeRender = function (renderer, scene, camera, geometry, material) {
        if (material && material.uniforms && material.uniforms.uOutlineScale) {
          material.uniforms.uOutlineScale.value = entry.outlineFactor === undefined ? 1 : entry.outlineFactor;
          material.uniforms.uOutlineEdited.value = entry.outlineEdited ? 1 : 0;
          material.uniforms.uOutlineQuantized.value = entry.outlineFloat ? 0 : 1;
          material.uniformsNeedUpdate = true;
        }
      };
      entries.push(entry);
      refreshEntry(entry);
    });
    state.recognizedMaterials = recognized.size;
    state.meshes = entries.length;
    state.outlines = entries.length;
    var ready = Promise.all(pending).then(function () {
      if (releaseParserAfterLoad) parser = null;
      loading = false;
      if (!disposed && memberProp) entries.forEach(refreshEntry);
      if (!disposed && options.onChange) options.onChange();
      return controller;
    });
    var controller = {
      ready: ready,
      syncGeometry: function () {
        if (disposed) return;
        entries.forEach(function (entry) {
          // Editing owns geometry copies. The outline borrows the same current
          // object and never disposes a mesh editor's old or new geometry.
          entry.helper.geometry = entry.mesh.geometry;
          entry.helper.morphTargetInfluences = entry.mesh.morphTargetInfluences;
          entry.helper.morphTargetDictionary = entry.mesh.morphTargetDictionary;
          var mapping = entry.mesh.geometry && entry.mesh.geometry.userData && entry.mesh.geometry.userData.viewerMesh || entry.mesh.userData.viewerMesh;
          var mesh = mapping && mapping.mesh;
          var key = mesh && String(mesh.source) + ":" + String(mesh.file) + ":" + String(mesh.id);
          entry.outlineEdited = !!(key && Object.prototype.hasOwnProperty.call(outlineFactors, key));
          var edit = entry.outlineEdited ? outlineFactors[key] : null;
          entry.outlineFloat = !!(edit && edit.floatWidth);
          entry.outlineFactor = edit ? edit.factor : 1;
          var vertices = edit && edit.vertices || [], absolute = edit ? edit.absolute : undefined;
          var hasWidth = vertices.length || absolute !== undefined, signature = hasWidth ? edit.signature : "";
          if (entry.widthGeometry !== entry.mesh.geometry || entry.widthSignature !== signature) {
            var changedGeometry = entry.widthGeometry !== entry.mesh.geometry;
            entry.widthGeometry = entry.mesh.geometry; entry.widthSignature = signature;
            if (hasWidth && mapping && mapping.vertexOrder === "identity") {
              var count = entry.mesh.geometry.attributes.position.count;
              var base = absolute === undefined ? -1 : Math.min(1, Math.max(0, entry.outlineFloat ? absolute * edit.factor / 255 : Math.floor(absolute * edit.factor + .5) / 255));
              var attribute = entry.widthAttribute, full = changedGeometry || !attribute || attribute.count !== count || entry.widthBase !== base;
              if (!attribute || changedGeometry || attribute.count !== count) {
                attribute = new T.BufferAttribute(new Float32Array(count), 1);
                if (T.DynamicDrawUsage !== undefined) attribute.setUsage(T.DynamicDrawUsage);
                entry.mesh.geometry.setAttribute("_sifas_outline_width", attribute);
              }
              var values = attribute.array, low = count, high = -1;
              if (full) { values.fill(base); low = 0; high = count - 1; }
              else (entry.widthVertices || []).forEach(function (row) { if (row.vertex < count) { values[row.vertex] = base; low = Math.min(low, row.vertex); high = Math.max(high, row.vertex); } });
              vertices.forEach(function (row) { if (row.vertex >= 0 && row.vertex < count) { values[row.vertex] = Math.min(1, Math.max(0, entry.outlineFloat ? row.value * edit.factor : Math.floor(row.value * 255 * edit.factor + .5) / 255)); low = Math.min(low, row.vertex); high = Math.max(high, row.vertex); } });
              // Several pointer samples can arrive before the next GPU upload.
              // Upload the retained buffer together so a later sparse sample
              // cannot hide an earlier whole-mesh change.
              if (high >= low) { attribute.updateRange.offset = 0; attribute.updateRange.count = -1; attribute.needsUpdate = true; }
              entry.widthAttribute = attribute; entry.widthBase = base; entry.widthVertices = vertices;
            } else {
              if (entry.mesh.geometry.getAttribute("_sifas_outline_width")) entry.mesh.geometry.deleteAttribute("_sifas_outline_width");
              entry.widthAttribute = null; entry.widthVertices = null; entry.widthBase = undefined;
            }
          }
        });
      },
      setOutlineEdits: function (values, catalogue) {
        outlineFactors = {};
        var formats = Object.create(null); (catalogue && catalogue.meshes || []).forEach(function (mesh) { formats[mesh.id] = mesh.format; });
        (values || []).forEach(function (value) { var edit = { factor: value.factor, floatWidth: formats[value.id] === "Float32", vertices: (value.vertices || []).map(function (row) { return { vertex: row.vertex, value: row.value }; }) }; if (value.absolute !== undefined) edit.absolute = value.absolute; edit.signature = JSON.stringify([edit.factor, edit.absolute, edit.vertices, edit.floatWidth]); outlineFactors[value.id] = edit; });
        controller.syncGeometry();
        if (options.onChange) options.onChange();
      },
      setEnabled: function (value) {
        if (disposed) return;
        enabled = !!value;
        entries.forEach(refreshEntry);
        if (options.onChange) options.onChange();
      },
      getOriginalMaterials: function (mesh) {
        return originalMaterials.has(mesh) ? originalMaterials.get(mesh) : mesh.material;
      },
      setTextureOverride: function (identity, replacement) {
        if (disposed) return;
        var key = textureIdentityKey(identity);
        if (!key) throw new Error("The edited texture has no source identity.");
        if (replacement && !replacement.isTexture) throw new Error("Choose a valid texture preview.");
        var previous = textureOverrides.get(key);
        if (replacement && previous && previous.source === replacement) {
          previous.texture.image = replacement.image;
          textureBindings.forEach(function (binding) { if (binding.key === key) applyTextureBinding(binding); });
          if (options.onChange) options.onChange();
          return;
        }
        clearTextureOverride(key);
        if (replacement) {
          var texture = replacement.clone();
          texture.mipmaps = []; texture.encoding = T.LinearEncoding;
          textureOverrides.set(key, { texture: texture, source: replacement }); ownedTextures.add(texture);
          textureBindings.forEach(function (binding) { if (binding.key === key) applyTextureBinding(binding); });
        }
        if (options.onChange) options.onChange();
      },
      clearTextureOverrides: function () {
        Array.from(textureOverrides.keys()).forEach(clearTextureOverride);
        if (options.onChange) options.onChange();
      },
      setLiveLighting: function (value) {
        if (disposed) return;
        materialCache.forEach(function (pair) {
          var ambient = pair.uniforms.uAmbientColor.value, tint = pair.uniforms.uTintColor.value;
          if (value?.ambient) ambient.fromArray(value.ambient);
          else ambient.copy(pair.ambient);
          if (value?.tint) tint.fromArray(value.tint);
          else tint.copy(pair.tint);
          var rim = value?.rim, uniforms = pair.uniforms;
          if (rim?.color) uniforms.uRimlightColor.value.fromArray(rim.color);
          else uniforms.uRimlightColor.value.copy(pair.rim.color);
          if (rim?.direction) uniforms.uRimlightDirection.value.fromArray(rim.direction);
          else uniforms.uRimlightDirection.value.copy(pair.rim.direction);
          uniforms.uRimglightIntensity.value = rim?.intensity ?? pair.rim.intensity;
          uniforms.uRimglightPower.value = rim?.power ?? pair.rim.power;
          // LiveCoreMemberRimlight resets the depth pass intensity before
          // BaseLight and Member Rim Light write their current values.
          var depthRim = pair.main.userData.mvStageMemberDepthRim;
          if (depthRim) depthRim.value = finite(rim?.intensity, 0);
          if (liveMember) setOutlineStencil(pair, liveOutlineStencil(pair));
        });
      },
      // MemberCheekBase on BodyPartManager.headMaterial: Initialize -> ResetAll
      // (_CHEEK_ON off, _CheekTexArrayIndex 0, _CheekIntensity 0); each active
      // MemberCheekClip input -> ApplyEnable(true) + ApplyCheek(type, value);
      // no active input -> ApplyEnable(false), keeping the last floats
      // (state.enabled false carries those floats; null keeps the reset).
      setCheek: function (name, state) {
        if (disposed || memberProp) return;
        var changed = false;
        materialCache.forEach(function (pair) {
          if (pair.sourceName !== name) return;
          var uniforms = pair.uniforms;
          if (!pair.cheek) {
            pair.cheek = { enabled: false };
            uniforms.uCheekTexArrayIndex.value = 0;
            uniforms.uCheekIntensity.value = 0;
            changed = true;
          }
          if (state) {
            var index = Math.max(0, Math.floor(finite(state.index, 0))), intensity = finite(state.intensity, 0);
            if (uniforms.uCheekTexArrayIndex.value !== index || uniforms.uCheekIntensity.value !== intensity) changed = true;
            uniforms.uCheekTexArrayIndex.value = index;
            uniforms.uCheekIntensity.value = intensity;
          }
          var enabled = !!state && state.enabled !== false;
          // tex2DArray(_CheekTex, (uv, _CheekTexArrayIndex)): bind the slice
          // the index selects; an unexported slice is never substituted.
          var layer = enabled ? cheekLayer(pair, uniforms.uCheekTexArrayIndex.value) : null;
          var shown = !!layer;
          if (layer && uniforms.uCheekTex.value !== layer) { uniforms.uCheekTex.value = layer; changed = true; }
          if (enabled && !layer) {
            limitations.add(pair.cheekLayers.length ? "A selected cheek array slice is unavailable in this preview."
              : "This head carries no cheek array; the game binds its shared Live/Characters/facialAssets/cheek_array.");
          }
          pair.cheek.enabled = enabled;
          if (!!pair.main.defines.SIFAS_CHEEK !== shown) {
            if (shown) pair.main.defines.SIFAS_CHEEK = 1;
            else delete pair.main.defines.SIFAS_CHEEK;
            pair.main.needsUpdate = true;
            changed = true;
          }
        });
        if (changed && options.onChange) options.onChange();
      },
      setRimlight: function (value) {
        if (disposed || memberProp || rimlightEnabled === !!value) return;
        rimlightEnabled = !!value;
        materialCache.forEach(function (pair) {
          if (liveMember) setOutlineStencil(pair, liveOutlineStencil(pair));
          if (!pair.features.rimlight) return;
          if (rimlightEnabled) pair.main.defines.SIFAS_RIMLIGHT = 1;
          else delete pair.main.defines.SIFAS_RIMLIGHT;
          pair.main.needsUpdate = true;
        });
        if (options.onChange) options.onChange();
      },
      getMaterial: function (mesh) {
        for (var i = 0; i < entries.length; i += 1) {
          if (entries[i].mesh === mesh) return memberProp ? mesh.material : enabled ? entries[i].custom : entries[i].original;
        }
        return originalMaterials.has(mesh) ? originalMaterials.get(mesh) : mesh.material;
      },
      update: function (delta) {
        controller.syncGeometry();
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
          textureOverrides: textureOverrides.size,
          rimlightEnabled: rimlightEnabled,
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
          if (memberProp) entry.mesh.renderOrder = entry.renderOrder;
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
        textureOverrides.clear(); textureBindings.length = 0;
      }
    };
    return controller;
  }

  var api = { apply: apply, vertexShader: VERTEX, fragmentShader: FRAGMENT,
    outlineVertexShader: OUTLINE_VERTEX, outlineFragmentShader: OUTLINE_FRAGMENT };
  global.SifasMaterial = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
}(typeof window !== "undefined" ? window : globalThis));
