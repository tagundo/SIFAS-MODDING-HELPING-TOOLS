(function (global) {
  "use strict";

  const owners = new WeakMap();
  const fogScalars = [
    "_Density", "_SizeStartX", "_SizeStartY", "_SizeEndX", "_SizeEndY", "_SizeSpeed", "_SizeRandom", "_SizeAspect",
    "_AlphaAnimPower", "_AlphaAnimScale", "_MoveIntensity", "_MoveSpeed",
  ];
  const smokeScalars = [
    "_Density", "_DensitySaturate", "_TextureRate", "_FadeOutPower", "_FadeOutScale", "_DistortionAmplitude",
    "_DistortionSpeed", "_DistortionFreq", "_WaveAmplitude", "_WaveSpeed", "_WaveFreq", "_FlowAmplitude",
    "_FlowSpeed", "_FlowFreq", "_CurveIntensity", "_CurvePower", "_LightFlatness", "_LightSmoothness",
  ];
  const fogVertex = `
    attribute highp vec3 _soft_center;
    attribute mediump vec4 _stage_color;
    uniform highp float _MusicTime;
    uniform highp vec4 _MainTex_ST;
    uniform mediump vec4 _Color;
    uniform highp float _Density;
    uniform highp float _SizeStartX;
    uniform highp float _SizeStartY;
    uniform highp float _SizeEndX;
    uniform highp float _SizeEndY;
    uniform highp float _SizeSpeed;
    uniform highp float _SizeRandom;
    uniform highp float _SizeAspect;
    uniform highp float _AlphaAnimPower;
    uniform highp float _AlphaAnimScale;
    uniform highp float _MoveIntensity;
    uniform highp float _MoveSpeed;
    varying highp vec2 vTexture;
    varying highp vec4 vDepthPosition;
    varying mediump vec4 vColor;

    void main() {
      vec2 phase = _stage_color.g * vec2(870.0, 304.0);
      float time = _MusicTime * _MoveSpeed;
      vec2 move = sin(time + phase) + 0.5 * sin(time + 2.0 * phase) + 0.25 * sin(time + 4.0 * phase);
      vec3 center = _soft_center + _MoveIntensity * vec3(-move.x, 0.0, move.y);
      vec3 viewCenter = (modelViewMatrix * vec4(center, 1.0)).xyz;
      float sizePhase = fract(_MusicTime * _SizeSpeed + _stage_color.r);
      vec2 size = mix(vec2(_SizeStartX, _SizeStartY), vec2(_SizeEndX, _SizeEndY), sin(sizePhase * 1.57079637));
      size *= 1.0 + _SizeRandom * (2.0 * _stage_color.b - 1.0);
      vec3 delta = position - _soft_center;
      // The source local coordinates reflect X. The matched camera view basis does not.
      vec3 viewDelta = vec3(-delta.x * size.x * _SizeAspect, delta.y * size.y, -delta.z);
      vec4 clip = projectionMatrix * vec4(viewCenter + viewDelta, 1.0);
      gl_Position = clip;
      vTexture = uv * _MainTex_ST.xy + vec2(_MainTex_ST.z, 1.0 - _MainTex_ST.y - _MainTex_ST.w);
      float alpha = pow(max(0.0, sin(sizePhase * _AlphaAnimScale * 6.28318548)), _AlphaAnimPower);
      vColor = vec4(_Color.rgb, alpha * _Density * _Color.a);
      // Native compares opaque depth at the displaced screen position to the undeformed vertex eye depth.
      float particleDepth = -(modelViewMatrix * vec4(position, 1.0)).z;
      vDepthPosition = vec4(clip.xy, particleDepth, clip.w);
    }
  `;
  const depthFragment = `
    uniform highp sampler2D uOpaqueDepth;
    uniform highp vec2 uDepthRange;
    uniform bool uHasOpaqueDepth;
    uniform bool uOrthographic;
    varying highp vec4 vDepthPosition;
    varying mediump vec4 vColor;

    highp float eyeDepthGap() {
      vec2 screen = vDepthPosition.xy / vDepthPosition.w * 0.5 + 0.5;
      float cameraNear = uDepthRange.x, cameraFar = uDepthRange.y;
      float depth = uHasOpaqueDepth ? texture2D(uOpaqueDepth, screen).r : 1.0;
      float eyeDepth = uOrthographic ? mix(cameraNear, cameraFar, depth) :
        cameraNear * cameraFar / mix(cameraFar, cameraNear, depth);
      return abs(eyeDepth - vDepthPosition.z);
    }
  `;
  const fogFragment = `
    ${depthFragment}
    uniform mediump sampler2D uTexture;
    varying highp vec2 vTexture;

    void main() {
      float opacity = clamp(eyeDepthGap() * vColor.a, 0.0500000007, 1.0);
      mediump vec4 surface = texture2D(uTexture, vTexture);
      gl_FragColor = vec4(surface.rgb * vColor.rgb, surface.a * opacity);
    }
  `;
  const smokeVertex = `
    attribute mediump vec4 _stage_color;
    uniform highp float _MusicTime;
    uniform highp vec4 _MainTex_ST;
    uniform mediump vec4 _Color;
    uniform highp float _Density;
    uniform highp float _DistortionAmplitude;
    uniform highp float _DistortionSpeed;
    uniform highp float _DistortionFreq;
    uniform highp float _WaveAmplitude;
    uniform highp float _WaveSpeed;
    uniform highp float _WaveFreq;
    uniform highp float _FlowSpeed;
    uniform highp float _FlowFreq;
    uniform highp float _CurveIntensity;
    uniform highp float _CurvePower;
    uniform mediump vec4 _LightDirection;
    varying highp vec4 vTexture;
    varying highp vec4 vDepthPosition;
    varying highp vec3 vWaveNormal;
    varying highp vec3 vLightView;
    varying mediump vec4 vColor;

    void main() {
      // Distortion and flow operate in the source coordinate system. Flip V at each sample.
      vec2 sourceUV = vec2(uv.x, 1.0 - uv.y);
      float curve = _CurveIntensity * pow(length(sourceUV - 0.5), _CurvePower);
      float distortion = _MusicTime * _DistortionSpeed;
      vec2 warped = sourceUV;
      warped.x += _DistortionAmplitude * sin(_DistortionFreq * warped.y + distortion);
      warped.y += _DistortionAmplitude * sin(_DistortionFreq * warped.x + distortion);
      vec2 wave = _WaveFreq * warped + _MusicTime * _WaveSpeed;
      float height = _WaveAmplitude * (sin(wave.x) + sin(wave.y));
      vec3 displaced = position + normal * height - vec3(0.0, curve, 0.0);
      vec4 viewPosition = modelViewMatrix * vec4(displaced, 1.0);
      vec4 clip = projectionMatrix * viewPosition;
      gl_Position = clip;
      vDepthPosition = vec4(clip.xy, -viewPosition.z, clip.w);
      vTexture.xy = warped * _MainTex_ST.xy + _MainTex_ST.zw;
      vTexture.zw = _FlowFreq * vTexture.xy + _MusicTime * _FlowSpeed;
      vColor = _stage_color * _Color;
      vColor.a *= _Density;
      vec2 waveSlope = -_WaveFreq * _WaveAmplitude * cos(wave);
      vWaveNormal = -modelViewMatrix[0].xyz * waveSlope.x + modelViewMatrix[1].xyz + modelViewMatrix[2].xyz * waveSlope.y;
      vLightView = normalize(-viewPosition.xyz - _LightDirection.xyz);
    }
  `;
  const smokeFragment = `
    ${depthFragment}
    uniform mediump sampler2D uTexture;
    uniform highp float _DensitySaturate;
    uniform highp float _TextureRate;
    uniform highp float _FadeOutPower;
    uniform highp float _FadeOutScale;
    uniform highp float _FlowAmplitude;
    uniform mediump float _LightFlatness;
    uniform mediump float _LightSmoothness;
    varying highp vec4 vTexture;
    varying highp vec3 vWaveNormal;
    varying highp vec3 vLightView;

    void main() {
      float opacity = clamp(eyeDepthGap(), 0.00999999978, 1.0) * vColor.a;
      mediump float saturated = clamp(opacity, 0.0, 1.0);
      opacity = mix(opacity, saturated, _DensitySaturate);
      opacity *= pow(clamp(_FadeOutScale / max(vDepthPosition.z, 0.00100000005), 0.0, 1.0), _FadeOutPower);
      float light = clamp(dot(vWaveNormal, vLightView), 0.0, 1.0);
      mediump float lightOpacity = pow(mix(light, 1.0, _LightFlatness), 1.0 / _LightSmoothness);
      mediump vec2 flow = texture2D(uTexture, vec2(vTexture.z, 1.0 - vTexture.w)).rg;
      vec2 sampleUV = vTexture.xy + _FlowAmplitude * flow;
      mediump float surface = texture2D(uTexture, vec2(sampleUV.x, 1.0 - sampleUV.y)).r;
      gl_FragColor = vec4(vColor.rgb, opacity * lightOpacity * clamp(1.0 + _TextureRate * (surface - 1.0), 0.0, 1.0));
    }
  `;

  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);

  function valid(node, fields) {
    const geometry = node.geometry, uniforms = fields.uniforms;
    const position = geometry.getAttribute("position"), center = geometry.getAttribute("_soft_center");
    const uv = geometry.getAttribute("uv"), color = geometry.getAttribute("_stage_color");
    const smoke = fields.kind === "smoke", stencil = fields.stencil;
    const normal = geometry.getAttribute("normal");
    const hasColor = color?.itemSize === 4 && color.count === position?.count &&
      (color.normalized === true || color.array instanceof Float32Array);
    const shaderInputs = smoke
      ? normal?.itemSize === 3 && normal.count === position?.count && vector(uniforms?._LightDirection, 4)
      : fields.kind === "fog" && center?.itemSize === 3 && center.count === position?.count;
    return shaderInputs && Number.isInteger(fields.queue) && fields.queue >= 2501 && fields.queue <= 5000 && fields.cull === 2 &&
      fields.alphaBlend === true && fields.depthTest === true && fields.depthWrite === false &&
      stencil?.comparison === (smoke ? 6 : 8) && stencil.ref === (smoke ? 4 : 2) &&
      stencil.pass === (smoke ? 2 : 0) && stencil.zFail === 0 &&
      Number.isSafeInteger(fields.texture) && fields.texture >= 0 &&
      vector(uniforms?._Color, 4) && vector(uniforms?._MainTex_ST, 4) &&
      (smoke ? smokeScalars : fogScalars).every(property => Number.isFinite(uniforms[property])) &&
      position?.itemSize === 3 && position.count > 0 &&
      uv?.itemSize === 2 && uv.count === position.count && (hasColor || (smoke && !color));
  }

  async function apply(T, root, parser, options = {}) {
    const {active = () => true} = options;
    const candidates = [], counts = new Map();
    root.traverse(node => {
      const fields = node.geometry?.userData?.mvStageSoftBillboard;
      if (!node.isMesh || node.isSkinnedMesh || !fields || Array.isArray(node.material) || !valid(node, fields)) return;
      let owner = node;
      while (owner && typeof owner.userData.mvStageNode?.binding !== "string") owner = owner.parent;
      if (!owner) return;
      counts.set(owner, (counts.get(owner) || 0) + 1);
      candidates.push({node, owner, fields});
    });
    if (!candidates.length || !active()) return null;
    const sampler = global.MVStudioStageMaterial?.createTextureSampler?.(T, parser, options);
    if (!sampler) return null;
    root.traverse(node => sampler.retainOriginalMaterial(node.material));
    for (const {fields} of candidates) sampler.reserveBase(fields.texture);

    const ready = [], sortEntries = [];
    const sharedUniforms = {
      _MusicTime: {value: 0}, uOpaqueDepth: {value: null}, uHasOpaqueDepth: {value: false},
      uDepthRange: {value: new T.Vector2(0.1, 1000)}, uOrthographic: {value: false},
    };
    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      sharedUniforms.uOpaqueDepth.value = null;
      for (const {node, owner, original, material, order, frustumCulled} of ready) {
        owners.delete(owner);
        node.material = original;
        node.renderOrder = order;
        node.frustumCulled = frustumCulled;
        material.dispose();
      }
      sortEntries.length = 0;
      sampler.dispose();
    }
    try {
      for (const {node, owner, fields} of candidates) {
        if (counts.get(owner) !== 1 || owners.has(owner)) continue;
        const map = await sampler.sampledNativeTexture(fields.texture, fields.mainSampler);
        if (!active()) {
          dispose();
          return null;
        }
        if (!map) continue;
        const authored = fields.uniforms;
        const uniforms = { ...sharedUniforms, uTexture: {value: map},
          _Color: {value: new T.Vector4().fromArray(authored._Color)},
          _MainTex_ST: {value: new T.Vector4().fromArray(authored._MainTex_ST)} };
        const smoke = fields.kind === "smoke", scalars = smoke ? smokeScalars : fogScalars;
        for (const property of scalars) uniforms[property] = {value: authored[property]};
        if (smoke) uniforms._LightDirection = {value: new T.Vector4().fromArray(authored._LightDirection)};
        const material = new T.ShaderMaterial({
          uniforms, vertexShader: smoke ? smokeVertex : fogVertex, fragmentShader: smoke ? smokeFragment : fogFragment,
          transparent: true, side: T.FrontSide,
          depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, toneMapped: false,
          blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
          blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
          stencilWrite: smoke, stencilFunc: smoke ? T.NotEqualStencilFunc : T.AlwaysStencilFunc,
          stencilRef: smoke ? 4 : 0, stencilFuncMask: 255, stencilWriteMask: 255,
          stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: smoke ? T.ReplaceStencilOp : T.KeepStencilOp,
        });
        material.name = smoke ? "Native stage smoke" : "Native stage soft billboard";
        if (smoke) material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        ready.push({node, owner, original: node.material, material, order: node.renderOrder, frustumCulled: node.frustumCulled});
        node.material = material;
        node.renderOrder = fields.queue;
        node.frustumCulled = false;
        owners.set(owner, {uniforms, scalars});
        if (vector(fields.sortCenter, 3)) sortEntries.push({
          node, anchor: node, center: new T.Vector3().fromArray(fields.sortCenter), queue: fields.queue,
        });
      }
    } catch (error) {
      dispose();
      throw error;
    }
    if (!ready.length) {
      dispose();
      return null;
    }
    function update(time) {
      if (disposed || !Number.isFinite(time)) return;
      const f32 = Math.fround, milliseconds = Math.trunc(time * 1000);
      sharedUniforms._MusicTime.value = f32(f32(milliseconds) * f32(.001));
    }
    function setDepth(texture, camera) {
      if (disposed) return;
      const usable = texture?.isDepthTexture === true;
      if (camera && Number.isFinite(camera.near) && Number.isFinite(camera.far) && camera.far > camera.near) {
        sharedUniforms.uDepthRange.value.set(camera.near, camera.far);
        sharedUniforms.uOrthographic.value = camera.isOrthographicCamera === true;
      }
      sharedUniforms.uOpaqueDepth.value = usable ? texture : null;
      sharedUniforms.uHasOpaqueDepth.value = usable;
    }
    return {
      update, setDepth, dispose,
      sortEntries: () => sortEntries,
      hasVisible: () => !disposed && ready.some(({node, material}) => {
        if (!material.visible) return false;
        for (let current = node; current; current = current.parent) if (!current.visible) return false;
        return true;
      }),
    };
  }

  function materialChannel(owner, kind, property) {
    const material = owners.get(owner);
    if (kind === "overlayColor" && (property === undefined || property === "_Color")) return material?.uniforms._Color.value || null;
    if (kind === "overlayScalar" && material?.scalars.includes(property)) return material.uniforms[property];
    return null;
  }

  global.MVStudioSoftBillboards = {apply, materialChannel};
})(window);
