(function (global) {
  "use strict";

  const vertex = `
    attribute vec3 position;
    attribute vec2 uv;
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`;

  const depthSampling = `
    uniform highp sampler2D dofDepth;
    uniform vec3 dofParams;
    uniform vec2 dofZParams;
    float nativeDofWeight(vec2 uv) {
      float depth = texture2D(dofDepth, uv).r;
      float eye = 1.0 / (dofZParams.x * depth + dofZParams.y);
      float coc = (eye - dofParams.x) * dofParams.y / (eye + 0.00001);
      float encodedCircle = clamp(0.5 * coc / dofParams.z + 0.5, 0.0, 1.0);
      return smoothstep(0.0, 0.003, abs(encodedCircle - 0.5) * dofParams.z);
    }`;

  const fragment = `
    uniform bool dofEnabled;
    uniform sampler2D dofImage;
    ${depthSampling}
    vec3 nativeDof(vec2 uv, vec3 linearSource) {
      if (!dofEnabled) return linearSource;
      return mix(linearSource, texture2D(dofImage, uv).rgb, nativeDofWeight(uv));
    }`;

  function uniforms(T) {
    return { dofEnabled: { value: false }, dofImage: { value: null }, dofDepth: { value: null },
      dofParams: { value: new T.Vector3() }, dofZParams: { value: new T.Vector2() } };
  }

  function apply(target, state) {
    target.dofEnabled.value = Boolean(state);
    target.dofImage.value = state?.image || null;
    target.dofDepth.value = state?.depth || null;
    if (state) {
      target.dofParams.value.fromArray(state.params);
      target.dofZParams.value.fromArray(state.zParams);
    }
  }

  // width/height: the camera image (CalculateMaxCoCRadius reads its height); image: the reduced image
  // the pyramid is built from.
  function plan(width, height, lens, camera, image = [width, height]) {
    const { distance, focalLength, aperture, kernelSize = 0 } = lens || {};
    const { near, far } = camera || {};
    if (!Number.isInteger(kernelSize) || kernelSize < 0 || kernelSize > 3 ||
        ![distance, focalLength, aperture, near, far].every(Number.isFinite) ||
        focalLength <= 0 || aperture < 0 || near <= 0 || far <= near) return null;
    const focus = Math.max(distance, focalLength);
    // Zero aperture is authored in native MV clips. The native shader
    // clamps its circle of confusion after evaluating the lens coefficient.
    const coefficient = focalLength ** 2 / (2 * 0.024 * aperture * (focus - focalLength));
    const maxCircle = Math.min(0.05, (6 + 4 * kernelSize) / height);
    const sizes = [];
    // DepthOfFieldComponent.CreateRenderTextures (0x2ccf0c0): ReducedImage.width / (2 << index) by
    // ReducedImage.height / (2 << index), ARGBHalf.
    for (let index = 0; index < kernelSize + 2; index++) {
      const size = [Math.floor(image[0] / (2 << index)), Math.floor(image[1] / (2 << index))];
      if (size[0] < 1 || size[1] < 1) return null;
      sizes.push(size);
    }
    return { sizes, params: [focus, coefficient, maxCircle], zParams: [1 / far - 1 / near, 1 / near] };
  }

  function create(T, renderer) {
    if (!renderer.capabilities.isWebGL2 || !renderer.extensions.has("EXT_color_buffer_float")) return null;
    const scene = new T.Scene(), camera = new T.Camera();
    const mesh = new T.Mesh(new T.PlaneGeometry(2, 2));
    mesh.material.dispose();
    mesh.frustumCulled = false;
    scene.add(mesh);
    const passUniforms = { ...uniforms(T), image: { value: null }, texel: { value: new T.Vector2() } };
    const common = `
      precision highp float;
      varying vec2 vUv;
      uniform sampler2D image;
      uniform vec2 texel;
      vec3 linearColor(vec3 gamma) {
        return gamma * (gamma * (gamma * 0.305306017 + 0.682171106) + 0.0125228781);
      }`;
    const passes = {
      prefilter: `vec4 average = (texture2D(image, a) + texture2D(image, b) +
        texture2D(image, c) + texture2D(image, d)) * 0.25;
        gl_FragColor = vec4(linearColor(average.rgb), average.a);`,
      antiAura: `gl_FragColor = vec4((
        linearColor(texture2D(image, a).rgb) * nativeDofWeight(a) +
        linearColor(texture2D(image, b).rgb) * nativeDofWeight(b) +
        linearColor(texture2D(image, c).rgb) * nativeDofWeight(c) +
        linearColor(texture2D(image, d).rgb) * nativeDofWeight(d)) * 0.25, 1.0);`,
      blur: `gl_FragColor = (texture2D(image, a) + texture2D(image, b) +
        texture2D(image, c) + texture2D(image, d)) * 0.25;`
    };
    const materials = Object.fromEntries(Object.entries(passes).map(([name, body]) => [name,
      new T.RawShaderMaterial({ vertexShader: vertex, uniforms: passUniforms,
        fragmentShader: `${common}${name === "antiAura" ? depthSampling : ""}
          void main() {
            vec2 shift = 0.5 * texel;
            vec2 a = vUv - shift;
            vec2 b = vUv + vec2(shift.x, -shift.y);
            vec2 c = vUv + vec2(-shift.x, shift.y);
            vec2 d = vUv + shift;
            ${body}
          }`, depthTest: false, depthWrite: false, toneMapped: false })]));
    const targets = [];

    function blit(pass, input, output) {
      mesh.material = materials[pass];
      passUniforms.image.value = input.texture;
      passUniforms.texel.value.set(1 / input.width, 1 / input.height);
      renderer.setRenderTarget(output);
      renderer.render(scene, camera);
    }

    // DepthOfFieldComponent.Prepare (0x2cce8b4) filters the context's reduced image
    // (get_ReducedImage at 0x2ccebd8, Blit at 0x2ccec58), not the camera image.
    function prepare(source, lens, viewCamera, image = source) {
      if (!source?.depthTexture || !image) return null;
      const settings = plan(source.width, source.height, lens, viewCamera, [image.width, image.height]);
      if (!settings) return null;
      const { sizes, params, zParams } = settings;
      sizes.forEach(([width, height], index) => {
        if (!targets[index]) targets[index] = new T.WebGLRenderTarget(width, height,
          { depthBuffer: false, type: T.HalfFloatType, minFilter: T.LinearFilter, magFilter: T.LinearFilter });
        targets[index].setSize(width, height);
      });
      const state = { image: targets[0].texture, depth: source.depthTexture, params, zParams };
      apply(passUniforms, state);
      const previous = renderer.getRenderTarget();
      try {
        // Stock game uses a pyramid of box-filter blits for all four kernel sizes.
        blit(lens.antiAura ? "antiAura" : "prefilter", image, targets[0]);
        for (let index = 1; index < sizes.length; index++) blit("blur", targets[index - 1], targets[index]);
        for (let index = sizes.length - 2; index >= 0; index--) blit("blur", targets[index + 1], targets[index]);
      } finally {
        renderer.setRenderTarget(previous);
      }
      return state;
    }

    return { prepare, dispose() {
      targets.forEach((target) => target.dispose());
      Object.values(materials).forEach((material) => material.dispose());
      mesh.geometry.dispose();
    } };
  }

  global.MVStudioDof = { create, uniforms, apply, fragment, plan };
})(typeof window !== "undefined" ? window : globalThis);
