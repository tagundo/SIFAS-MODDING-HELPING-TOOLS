(function (global) {
  "use strict";

  const mainBinding = "/EntryPoint/Live/Cameras/MainCamera";
  const reducedHeight = 420;

  function sample(project, time) {
    if (project?.quality?.values?.posteffect !== true) return null;
    const tracks = (project.tracks || []).filter((track) => !track.muted && track.nativeClass === "LiveBloomTrack" &&
      track.binding === mainBinding);
    if (tracks.length !== 1 || !global.MVStudioLighting?.nativeWeight) return null;
    const fields = ["intensity", "threshold", "softKnee", "radius"];
    const value = { intensity: 0, threshold: 0, softKnee: 0, radius: 0, antiFlicker: false };
    let highest = 0;
    for (const event of tracks[0].events) {
      const settings = event.values;
      if (settings?.playableClass !== "LiveBloomClip" || !fields.every((key) => Number.isFinite(settings[key]))) continue;
      const weight = global.MVStudioLighting.nativeWeight(event, time);
      if (!(weight > 0)) continue;
      for (const key of fields) value[key] = Math.fround(value[key] + Math.fround(settings[key] * weight));
      if (weight > highest) {
        highest = weight;
        value.antiFlicker = settings.antiFlicker === true || settings.antiFlicker === 1;
      }
    }
    return value.intensity > 0 && value.threshold >= 0 && value.softKnee >= 0 ? value : null;
  }

  function toLinear(value) {
    if (value <= 0.04045) return value / 12.92;
    if (value < 1) return ((value + 0.055) / 1.055) ** 2.4;
    return value ** 2.2;
  }

  function plan(width, height, value) {
    const reduced = [Math.max(1, Math.round(width / height * reducedHeight)), reducedHeight];
    const prefilter = reduced.map((length) => Math.floor(length / 2));
    const levels = [];
    let size = prefilter;
    while (size[0] >= 3 && size[1] >= 3 && levels.length < 16) {
      size = size.map((length) => Math.floor(length / 2));
      levels.push(size);
    }
    const range = Math.fround(Math.fround(Math.log2(prefilter[1]) + value.radius) - 8);
    const whole = Math.trunc(range);
    const threshold = toLinear(value.threshold), knee = threshold * value.softKnee + 0.00001;
    return { reduced, prefilter, levels: levels.slice(0, Math.max(1, whole)), scale: 0.5 + range - whole,
      threshold, curve: [threshold - knee, 2 * knee, 0.25 / knee] };
  }

  const vertex = `
    attribute vec3 position;
    attribute vec2 uv;
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`;
  const common = `
    precision highp float;
    varying vec2 vUv;
    uniform sampler2D image;
    uniform sampler2D baseImage;
    uniform vec2 texel;
    uniform vec3 curve;
    uniform float threshold;
    uniform float sampleScale;
    uniform float intensity;
    uniform bool antiFlicker;
    uniform bool bloomEnabled;
    float brightest(vec3 color) { return max(color.r, max(color.g, color.b)); }
    vec4 rgbm(vec3 color) {
      color *= 0.125;
      float multiplier = ceil(max(brightest(color), 0.000001) * 255.0) / 255.0;
      return vec4(color / multiplier, multiplier);
    }
    vec3 decoded(vec2 at) { vec4 rgba = texture2D(image, at); return rgba.rgb * rgba.a * 8.0; }
    vec3 linearColor(vec3 gamma) {
      return gamma * (gamma * (gamma * 0.305306017 + 0.682171106) + 0.0125228781);
    }
    vec3 median3(vec3 a, vec3 b, vec3 c) {
      return a + b + c - min(a, min(b, c)) - max(a, max(b, c));
    }
    vec3 sourceAt(vec2 at) { return min(texture2D(image, at).rgb, vec3(65504.0)); }
    vec3 corners(vec2 shift) {
      return decoded(vUv - shift) + decoded(vUv + vec2(shift.x, -shift.y)) +
        decoded(vUv + vec2(-shift.x, shift.y)) + decoded(vUv + shift);
    }
  `;
  const passes = {
    reduce: `gl_FragColor = texture2D(image, vUv);`,
    prefilter: `
      vec2 at = vUv + (antiFlicker ? -0.5 * texel : vec2(0.0));
      vec3 sampleColor = sourceAt(at);
      if (antiFlicker) sampleColor = median3(sourceAt(at - vec2(0.0, texel.y)),
        median3(sourceAt(at - vec2(texel.x, 0.0)), sampleColor, sourceAt(at + vec2(texel.x, 0.0))),
        sourceAt(at + vec2(0.0, texel.y)));
      vec3 color = linearColor(sampleColor);
      float light = brightest(color);
      float soft = clamp(light - curve.x, 0.0, curve.y);
      gl_FragColor = rgbm(color * (max(soft * soft * curve.z, light - threshold) / max(light, 0.00001)));`,
    down: `
      vec3 a = decoded(vUv - texel), b = decoded(vUv + vec2(texel.x, -texel.y));
      vec3 c = decoded(vUv + vec2(-texel.x, texel.y)), d = decoded(vUv + texel);
      if (antiFlicker) {
        vec4 weight = 1.0 / (vec4(brightest(a), brightest(b), brightest(c), brightest(d)) + 1.0);
        gl_FragColor = rgbm((a * weight.x + b * weight.y + c * weight.z + d * weight.w) / dot(weight, vec4(1.0)));
      } else gl_FragColor = rgbm((a + b + c + d) * 0.25);`,
    up: `
      vec2 shift = texel * sampleScale;
      vec3 sides = decoded(vUv + vec2(shift.x, 0.0)) + decoded(vUv - vec2(shift.x, 0.0)) +
        decoded(vUv + vec2(0.0, shift.y)) + decoded(vUv - vec2(0.0, shift.y));
      vec4 base = texture2D(baseImage, vUv);
      gl_FragColor = rgbm((corners(shift) + 2.0 * sides + 4.0 * decoded(vUv)) / 16.0 + base.rgb * base.a * 8.0);`,
    combine: `
      vec3 color = nativeDof(vUv, linearColor(texture2D(baseImage, vUv).rgb));
      if (bloomEnabled) color += corners(0.5 * sampleScale * texel) * (0.25 * intensity);
      color = nativeFlare(color, vUv);
      color = max(vec3(0.0), 1.055 * pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.4)) - 0.055);
      gl_FragColor = vec4(color, 1.0);`
  };

  function create(T, renderer) {
    if (!renderer.capabilities.isWebGL2) return null;
    const gl = renderer.getContext();
    const samples = gl.getParameter(gl.SAMPLES);
    let hdr = global.MVStudioHDR?.create(T, renderer) || null;
    const scene = new T.Scene(), camera = new T.Camera();
    const geometry = new T.PlaneGeometry(2, 2), mesh = new T.Mesh(geometry);
    mesh.material.dispose();
    mesh.frustumCulled = false;
    scene.add(mesh);
    const dofApi = global.MVStudioDof, flareApi = global.MVStudioFlare;
    const dof = dofApi?.create(T, renderer);
    const combine = (dofApi?.fragment || "vec3 nativeDof(vec2 uv, vec3 color) { return color; }") +
      (flareApi?.fragment || "vec3 nativeFlare(vec3 color, vec2 uv) { return color; }");
    const uniforms = { image: { value: null }, baseImage: { value: null }, texel: { value: new T.Vector2() },
      curve: { value: new T.Vector3() }, threshold: { value: 0 }, sampleScale: { value: 0 }, intensity: { value: 0 },
      antiFlicker: { value: false }, bloomEnabled: { value: false },
      ...dofApi?.uniforms(T), ...flareApi?.uniforms(T) };
    const materials = Object.fromEntries(Object.entries(passes).map(([name, source]) => [name,
      new T.RawShaderMaterial({ vertexShader: vertex,
        fragmentShader: `${common}
${name === "combine" ? combine : ""}
void main() {${source}}`, uniforms,
        depthTest: false, depthWrite: false, toneMapped: false })]));
    let source = null, reduced = null, prefilter = null, effect = null, flare = null, sourceReady = null;
    const down = [], up = [];

    function target(width, height, options, multisample = false) {
      const format = { depthBuffer: false, minFilter: T.LinearFilter, magFilter: T.LinearFilter, ...options };
      if (multisample && samples && T.WebGLMultisampleRenderTarget) {
        const buffer = new T.WebGLMultisampleRenderTarget(width, height, format);
        buffer.samples = samples;
        return buffer;
      }
      return new T.WebGLRenderTarget(width, height, format);
    }

    function makeSource(width, height, needsDepth) {
      source?.dispose();
      const options = { depthBuffer: true, stencilBuffer: true };
      if (needsDepth) {
        const depth = new T.DepthTexture(width, height, T.UnsignedInt248Type);
        depth.format = T.DepthStencilFormat;
        options.depthTexture = depth;
      }
      source = target(width, height, options, true);
      source.texture.encoding = T.sRGBEncoding;
      source.texture.internalFormat = "RGBA8";
      sourceReady = null;
    }

    function makeReduced(size) {
      reduced?.dispose();
      reduced = target(...size);
      reduced.texture.internalFormat = "RGBA8";
    }

    function prepareHDR(useReduced) {
      if (!hdr.prepare(source)) return false;
      if (!useReduced || hdr.ready(reduced)) return true;
      renderer.setRenderTarget(reduced);
      if (!hdr.prepare(reduced)) return false;
      renderer.setRenderTarget(source);
      return true;
    }

    function blit(pass, input, destination, base = null) {
      mesh.material = materials[pass];
      uniforms.image.value = input.texture;
      uniforms.baseImage.value = base?.texture || null;
      uniforms.texel.value.set(1 / input.width, 1 / input.height);
      renderer.setRenderTarget(destination);
      renderer.render(scene, camera);
    }

    function renderBloom(setup) {
      uniforms.threshold.value = setup.threshold;
      uniforms.curve.value.fromArray(setup.curve);
      uniforms.sampleScale.value = setup.scale;
      uniforms.intensity.value = effect.intensity;
      uniforms.antiFlicker.value = effect.antiFlicker;
      blit("reduce", source, reduced);
      blit("prefilter", reduced, prefilter);
      let image = prefilter;
      for (let index = 0; index < setup.levels.length; index++) {
        if (!down[index]) down[index] = target(...setup.levels[index]);
        down[index].setSize(...setup.levels[index]);
        blit("down", image, down[index]);
        uniforms.antiFlicker.value = false;
        image = down[index];
      }
      for (let index = setup.levels.length - 2; index >= 0; index--) {
        if (!up[index]) up[index] = target(...setup.levels[index]);
        up[index].setSize(...setup.levels[index]);
        blit("up", image, up[index], down[index]);
        image = up[index];
      }
      return image;
    }

    function draw(renderScene, needsDepth = false, lens = null, viewCamera = null) {
      if (!dof) lens = null;
      if (!effect && !lens && !flare) return false;
      const { width, height } = renderer.domElement;
      if (!width || !height) return false;
      const dimensions = effect ? plan(width, height, effect) : null;
      const setup = dimensions?.levels.length && dimensions.reduced[0] <= renderer.capabilities.maxTextureSize ? dimensions : null;
      if (!setup && !lens && !flare) return false;
      if (!source || (needsDepth && !source.depthTexture)) makeSource(width, height, needsDepth);
      if (setup) {
        if (!reduced) makeReduced(setup.reduced);
        if (!prefilter) prefilter = target(...setup.prefilter);
        reduced.setSize(...setup.reduced);
        prefilter.setSize(...setup.prefilter);
      }
      if (source.width !== width || source.height !== height) {
        source.setSize(width, height);
        sourceReady = null;
      }
      if (sourceReady === false) return false;
      const previousTarget = renderer.getRenderTarget(), previousClear = renderer.autoClear;
      try {
        renderer.autoClear = true;
        renderer.setRenderTarget(source);
        if (hdr && !prepareHDR(Boolean(setup))) {
          // Rebuild both native ARGB32 fallback attachments together if packed
          // color or its multisample resolve is unavailable on this device.
          hdr = null;
          renderer.setRenderTarget(previousTarget);
          makeSource(width, height, needsDepth || Boolean(source.depthTexture));
          if (setup) makeReduced(setup.reduced);
          renderer.setRenderTarget(source);
        }
        if (sourceReady === null) sourceReady = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
        if (!sourceReady) return false;
        renderScene(source);
        const focus = lens ? dof.prepare(source, lens, viewCamera) : null;
        const bloomImage = setup ? renderBloom(setup) : null;
        dofApi?.apply(uniforms, focus);
        flareApi?.apply(T, uniforms, flare, width, height);
        uniforms.bloomEnabled.value = Boolean(bloomImage);
        if (focus || flare || bloomImage) blit("combine", bloomImage || source, previousTarget, source);
        else blit("reduce", source, previousTarget);
      } finally {
        renderer.setRenderTarget(previousTarget);
        renderer.autoClear = previousClear;
      }
      return true;
    }

    return { draw, evaluate(project, time) {
      effect = sample(project, time);
      flare = flareApi?.sample(project, time) || null;
    }, dispose() {
      dof?.dispose();
      for (const item of [source, reduced, prefilter, ...down, ...up]) item?.dispose();
      for (const material of Object.values(materials)) material.dispose();
      geometry.dispose();
    } };
  }

  global.MVStudioPost = { create, sample, plan };
}(window));
