(function (global) {
  "use strict";

  // GL 3.12.0 client, MV playback only.
  //
  // LLAS.Scene.Live.Mv.LiveMvDarkFilterField: /EntryPoint/DarkFilterField, a 100x100
  // built-in Quad on layer 22, drawn by the MarginCoverCamera (depth 29) after the
  // live main camera (0) and the overlay camera (20). Its material is a clone of
  // AS_GAME/MeshColor (SV_TARGET0 = _Color, Blend SrcAlpha OneMinusSrcAlpha, ZWrite
  // Off) with renderQueue 1900, and Initialize sets _Color to black.
  //   OnInitializeMessage (LiveMvManager.StartAct): settingBrightness = 1,
  //     StartFade(to 1, over 2.0 s).
  //   OnEndEffectMessage (FinishLiveMv on LiveMusicMachine.OnFinishMusic):
  //     StartFade(to settingBrightness * 0.5, over 0.25 s).
  //   Update: brightness = Lerp(from, to, Clamp01(fadeTime / length)),
  //     _Color.a = 1 - brightness; once fadeTime passes the length the renderer is
  //     disabled when to > 0.999.
  // LiveCoreCameraManager.StartBlur at the live end: the overlay camera blurs the
  // captured frame while blurSpreadSize ramps linearly 0 -> 4.0 over
  // liveEndBlurTime 0.25 s (AnimationBlurIntensity, unscaled time).
  // LiveCoreOverlayCamera.Blur: _SampleSize = spread * 0.5, then
  // Hidden/AS_ImageEffect/GaussianBlur pass 0 (vertical) into a temporary of the
  // destination size and pass 1 (horizontal) into the destination. Each pass sums
  // 11 taps (i - 5) * _SampleSize texels apart with _GaussianKernel[i] =
  // exp(-(i - 5)^2 / 18) normalized (GetOneDimensionalKernel); alpha is 1, and
  // _SampleSize 0 copies the source.
  const START_LENGTH = 2, END_LENGTH = 0.25, END_BRIGHTNESS = 0.5, BLUR_TIME = 0.25, BLUR_SPREAD = 4;
  const KERNEL = (() => {
    const values = Array.from({length: 11}, (_, index) => Math.fround(Math.exp(-((index - 5) ** 2) / 18)));
    const total = values.reduce((sum, value) => Math.fround(sum + value), 0);
    return values.map(value => Math.fround(value / total));
  })();
  const clamp01 = value => Math.min(1, Math.max(0, value));

  // time: director time; end: the music end (FinishLiveMv); endElapsed: seconds
  // since the end effect began (Infinity once it has finished).
  function state(time, end, endElapsed = Infinity) {
    const now = Number.isFinite(time) ? Math.max(0, time) : 0;
    const startBrightness = at => clamp01(at / START_LENGTH);
    let brightness = startBrightness(now), spread = 0;
    if (Number.isFinite(end) && end > 0 && now >= end) {
      const elapsed = Number.isFinite(endElapsed) ? Math.max(0, endElapsed) : Infinity;
      const from = startBrightness(end);
      brightness = from + (END_BRIGHTNESS - from) * clamp01(elapsed / END_LENGTH);
      spread = BLUR_SPREAD * clamp01(elapsed / BLUR_TIME);
    }
    return {alpha: 1 - brightness, sampleSize: spread * 0.5};
  }

  const vertexShader = `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = vec4(position.xy, 0.0, 1.0);
    }
  `;
  const blurShader = `
    uniform sampler2D tSource;
    uniform vec2 uStep;
    uniform float uSampleSize;
    uniform float uKernel[11];
    varying vec2 vUv;
    void main() {
      if (uSampleSize == 0.0) { gl_FragColor = vec4(texture2D(tSource, vUv).rgb, 1.0); return; }
      vec2 point = vUv - uStep * 5.0;
      vec3 color = vec3(0.0);
      for (int index = 0; index < 11; index++) {
        color += texture2D(tSource, point).rgb * uKernel[index];
        point += uStep;
      }
      gl_FragColor = vec4(color, 1.0);
    }
  `;

  function create(T, renderer) {
    const camera = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const geometry = new T.PlaneGeometry(2, 2);
    const blur = new T.ShaderMaterial({
      name: "MV live end Gaussian blur", vertexShader, fragmentShader: blurShader,
      depthTest: false, depthWrite: false, blending: T.NoBlending, toneMapped: false,
      uniforms: {tSource: {value: null}, uStep: {value: new T.Vector2()}, uSampleSize: {value: 0}, uKernel: {value: KERNEL}},
    });
    const filter = new T.MeshBasicMaterial({
      name: "MV dark filter", color: 0x000000, transparent: true, opacity: 0,
      depthTest: false, depthWrite: false, toneMapped: false,
    });
    const quad = new T.Mesh(geometry, blur), shade = new T.Mesh(geometry, filter);
    quad.frustumCulled = shade.frustumCulled = false;
    const size = new T.Vector2(), origin = new T.Vector2();
    let copy = null, target = null;

    function buffers(width, height) {
      if (copy?.image.width !== width || copy?.image.height !== height) {
        copy?.dispose();
        copy = new T.DataTexture(null, width, height, T.RGBFormat);
        copy.minFilter = copy.magFilter = T.LinearFilter;
        copy.generateMipmaps = false;
        copy.needsUpdate = true;
      }
      if (target?.width !== width || target?.height !== height) {
        target?.dispose();
        target = new T.WebGLRenderTarget(width, height, {
          minFilter: T.LinearFilter, magFilter: T.LinearFilter, format: T.RGBAFormat, depthBuffer: false, stencilBuffer: false,
        });
      }
    }

    function pass(source, destination, stepX, stepY, sampleSize) {
      quad.material.uniforms.tSource.value = source;
      quad.material.uniforms.uStep.value.set(stepX, stepY);
      quad.material.uniforms.uSampleSize.value = sampleSize;
      renderer.setRenderTarget(destination);
      renderer.render(quad, camera);
    }

    // Draws over the finished frame in the default framebuffer.
    function draw(current) {
      if (!current || !(current.sampleSize > 0 || current.alpha > 0)) return false;
      const previousTarget = renderer.getRenderTarget(), autoClear = renderer.autoClear;
      renderer.autoClear = false;
      try {
        if (current.sampleSize > 0) {
          renderer.getDrawingBufferSize(size);
          const width = Math.max(1, Math.floor(size.x)), height = Math.max(1, Math.floor(size.y));
          buffers(width, height);
          renderer.setRenderTarget(null);
          renderer.copyFramebufferToTexture(origin, copy);
          pass(copy, target, 0, current.sampleSize / height, current.sampleSize);
          pass(target.texture, null, current.sampleSize / width, 0, current.sampleSize);
        }
        if (current.alpha > 0) {
          filter.opacity = Math.min(1, current.alpha);
          renderer.setRenderTarget(null);
          renderer.render(shade, camera);
        }
      } finally {
        renderer.autoClear = autoClear;
        renderer.setRenderTarget(previousTarget);
      }
      return true;
    }

    function dispose() {
      copy?.dispose();
      target?.dispose();
      geometry.dispose();
      blur.dispose();
      filter.dispose();
      copy = target = null;
    }

    return {draw, dispose};
  }

  global.MVStudioScreenFade = {create, state, kernel: KERNEL.slice()};
})(typeof window !== "undefined" ? window : globalThis);
