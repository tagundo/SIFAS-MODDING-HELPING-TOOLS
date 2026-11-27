(function (global) {
  "use strict";

  // The screen programs, one per display shader (GLES3 programs of the shader bundles):
  //   GENERAL      AS/General/Opaque        main x COLOR (_VERTEX_COLOR_ON), lerp to _AmbientColor, x _TintColor
  //   TRANSPARENT  AS/General/Transparent   main x _TintColor x COLOR, + main^4 (_SATURATE_ON), blended
  //   ADDITIVE     AS/Blend/AdditiveOpaque  _AdditiveTex where its rgb sum >= 0.001, else main; then COLOR,
  //                                         _AmbientColor and _TintColor
  //   WAVE         AS/Uniq/so1005|so2030-DisplayWaveTexture: main lerped to _AmbientColor x _TintColor plus
  //                four _WaveTex layers (uv * _RepeatXYn + _Time.y * _SpeedXYn) x _WaveColor, premultiplied
  const vertex = [
    "attribute vec4 _stage_color;",
    "uniform vec4 uTextureST;",
    "uniform bool uVertexColor;",
    "varying vec2 vScreen;",
    "varying vec4 vColor;",
    "#if defined(ADDITIVE)",
    "uniform vec4 uSecondST;",
    "varying vec2 vSecond;",
    "#elif defined(WAVE)",
    "uniform float uTime;",
    "uniform vec4 uWave[4];",
    "varying vec4 vWaveA;",
    "varying vec4 vWaveB;",
    // Unity's uv * repeat + _Time.y * speed, in the glTF V-flipped space.
    "vec2 wave(vec4 layer) {",
    "  return uv * layer.xy + vec2(uTime * layer.z, 1.0 - layer.y - uTime * layer.w);",
    "}",
    "#endif",
    "void main() {",
    "  vScreen = uv * uTextureST.xy + uTextureST.zw;",
    "  vColor = uVertexColor ? _stage_color : vec4(1.0);",
    "#if defined(ADDITIVE)",
    "  vSecond = uv * uSecondST.xy + uSecondST.zw;",
    "#elif defined(WAVE)",
    "  vWaveA = vec4(wave(uWave[0]), wave(uWave[1]));",
    "  vWaveB = vec4(wave(uWave[2]), wave(uWave[3]));",
    "#endif",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragment = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "uniform vec4 uAmbient;",
    "varying vec2 vScreen;",
    "varying vec4 vColor;",
    "#if defined(ADDITIVE)",
    "uniform sampler2D uSecond;",
    "varying vec2 vSecond;",
    "#elif defined(WAVE)",
    "uniform sampler2D uSecond;",
    "uniform vec4 uWaveColor;",
    "varying vec4 vWaveA;",
    "varying vec4 vWaveB;",
    "vec3 layer(vec2 at) {",
    "  vec4 wave = texture2D(uSecond, at) * uWaveColor;",
    "  return wave.rgb * wave.a;",
    "}",
    "#endif",
    "void main() {",
    "#if defined(TRANSPARENT)",
    "  vec4 texel = texture2D(uTexture, vScreen);",
    "  vec4 color = texel * uTint * vColor;",
    "#ifdef SATURATE",
    "  vec3 square = texel.rgb * texel.rgb;",
    "  color.rgb = square * square + color.rgb;",
    "#endif",
    "  gl_FragColor = color;",
    "#elif defined(ADDITIVE)",
    "  vec3 feed = texture2D(uSecond, vSecond).rgb;",
    "  float drawn = feed.y + feed.x + feed.z >= 0.00100000005 ? 1.0 : 0.0;",
    "  vec4 texel = texture2D(uTexture, vScreen);",
    "  vec3 base = drawn * (feed - texel.rgb) + texel.rgb;",
    "  vec3 shaded = base * vColor.rgb;",
    "  gl_FragColor = vec4(uAmbient.a * (uAmbient.rgb - shaded) + shaded, texel.a * vColor.a) * uTint;",
    "#elif defined(WAVE)",
    "  vec4 texel = texture2D(uTexture, vScreen);",
    "  vec3 color = (uAmbient.a * (uAmbient.rgb - texel.rgb) + texel.rgb) * uTint.rgb + layer(vWaveA.xy);",
    "  color += layer(vWaveA.zw);",
    "  color += layer(vWaveB.xy);",
    "  color += layer(vWaveB.zw);",
    "  gl_FragColor = vec4(color, texel.a * uTint.a);",
    "#else",
    "  vec4 texel = texture2D(uTexture, vScreen) * vColor;",
    "  gl_FragColor = vec4(mix(texel.rgb, uAmbient.rgb, uAmbient.a), texel.a) * uTint;",
    "#endif",
    "}"
  ].join("\n");

  const DEFINES = { general: null, transparent: "TRANSPARENT", blendAdditive: "ADDITIVE", waveTexture: "WAVE" };

  function sample(track, time) {
    const ambient = [0, 0, 0, 0], scroll = [0, 0];
    let material = 0;
    for (const event of track.events) {
      const fields = event.values;
      if (fields?.playableClass !== "LiveDisplayClip" || !Number.isInteger(fields.materialIndex)) continue;
      const rgba = ["r", "g", "b", "a"].map((axis) => fields.ambientColor?.[axis]);
      const speed = [fields.scrollSpeed?.x, fields.scrollSpeed?.y];
      if (![...rgba, ...speed].every(Number.isFinite)) continue;
      const weight = global.MVStudioLighting?.nativeWeight(event, time) ?? 0;
      if (weight <= 0) continue;
      for (let axis = 0; axis < 4; axis++) ambient[axis] += rgba[axis] * weight;
      for (let axis = 0; axis < 2; axis++) scroll[axis] += speed[axis] * weight;
      material = fields.materialIndex;
    }
    return { ambient, material, offset: scroll.map((speed) => speed * time) };
  }

  // GLBs exported before the display kinds carry the AS/General/Opaque background
  // (stencil pass Replace) and the AS/General/Transparent alpha-blended logo.
  function normalize(fields, logo) {
    if (!fields || fields.unsupported || fields.kind) return fields;
    return logo ? { ...fields, kind: "transparent", blend: [5, 10], zTest: 4, zWrite: false, stencilPass: 0 }
      : { ...fields, kind: "general", stencilPass: 2 };
  }

  // UnityEngine.Rendering enums -> three.js.
  function blendFactor(T, value) {
    return [T.ZeroFactor, T.OneFactor, T.DstColorFactor, T.SrcColorFactor, T.OneMinusDstColorFactor,
      T.SrcAlphaFactor, T.OneMinusSrcColorFactor, T.DstAlphaFactor, T.OneMinusDstAlphaFactor,
      T.SrcAlphaSaturateFactor, T.OneMinusSrcAlphaFactor][value] ?? T.OneFactor;
  }
  function depthFunction(T, value) {
    return [T.AlwaysDepth, T.NeverDepth, T.LessDepth, T.EqualDepth, T.LessEqualDepth, T.GreaterDepth,
      T.NotEqualDepth, T.GreaterEqualDepth, T.AlwaysDepth][value] ?? T.LessEqualDepth;
  }
  function stencilFunction(T, value) {
    return [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc, T.EqualStencilFunc, T.LessEqualStencilFunc,
      T.GreaterStencilFunc, T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc][value] ??
      T.AlwaysStencilFunc;
  }
  function stencilOperation(T, value) {
    return [T.KeepStencilOp, T.ZeroStencilOp, T.ReplaceStencilOp, T.IncrementStencilOp, T.DecrementStencilOp,
      T.InvertStencilOp, T.IncrementWrapStencilOp, T.DecrementWrapStencilOp][value] ?? T.KeepStencilOp;
  }

  // `clock` (optional, the scene's game clock): director seconds -> the game's Time.time. The
  // wave screens read _Time.y (Time.timeSinceLevelLoad); the editor has no level-load time,
  // so it uses the game run's Time.time when one is set and the director time otherwise.
  async function apply(T, root, parser) {
    const screens = [];
    root.traverse((node) => {
      const fields = node.geometry?.userData?.mvStageDisplay;
      if (node.isMesh && !Array.isArray(node.material) && fields) {
        screens.push({ node, fields, original: node.material, renderOrder: node.renderOrder });
      }
    });
    if (!screens.length) return null;
    const textures = new Map(), owned = [];
    function constant(rgba) {
      const texture = new T.DataTexture(new Uint8Array(rgba), 1, 1);
      texture.needsUpdate = true;
      return texture;
    }
    // Unity's "white" property default, and the display camera's render texture as the
    // editor has it: cleared to (0, 0, 0, 0) with nothing drawn (no display camera image).
    const white = constant([255, 255, 255, 255]), cleared = constant([0, 0, 0, 0]);
    function texture(index) {
      if (index === null || index === undefined) return Promise.resolve(white);
      if (!textures.has(index)) textures.set(index, parser.getDependency("texture", index).then((source) => {
        const copy = source.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        return copy;
      }));
      return textures.get(index);
    }
    function shader(kind, saturate, logo) {
      const uniforms = {
        uTexture: { value: white }, uTextureST: { value: new T.Vector4(1, 1, 0, 0) },
        uVertexColor: { value: false },
        uTint: { value: new T.Vector4(1, 1, 1, 1) }, uAmbient: { value: new T.Vector4(0, 0, 0, 0) },
        uSecond: { value: white }, uSecondST: { value: new T.Vector4(1, 1, 0, 0) },
        uTime: { value: 0 }, uWave: { value: [0, 1, 2, 3].map(() => new T.Vector4()) },
        uWaveColor: { value: new T.Vector4(1, 1, 1, .5) }
      };
      const defines = {};
      if (DEFINES[kind]) defines[DEFINES[kind]] = 1;
      if (saturate) defines.SATURATE = 1;
      const material = new T.ShaderMaterial({
        vertexShader: vertex, fragmentShader: fragment, uniforms, defines, toneMapped: false,
        depthTest: true, depthFunc: T.LessEqualDepth
      });
      material.name = logo ? "Native stage display logo" : "Native stage display background";
      material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
      owned.push(material);
      return material;
    }
    // One material per screen pass and shader program (switching variants swaps them).
    function program(screen, fields, logo) {
      const key = `${logo ? "logo" : "background"}:${fields.kind}:${fields.saturate === true}`;
      if (!screen.programs.has(key)) screen.programs.set(key, shader(fields.kind, fields.saturate === true, logo));
      return screen.programs.get(key);
    }
    function setPass(node, material, fields, state, shaderTime) {
      const uniforms = material.uniforms;
      const [sx, sy, x, y] = fields.uv, [ox, oy] = state?.offset || [x, y];
      uniforms.uTexture.value = fields.image;
      uniforms.uVertexColor.value = fields.vertexColor === true;
      uniforms.uTextureST.value.set(sx, sy, ox, 1 - sy - oy);
      uniforms.uAmbient.value.fromArray(state?.ambient || fields.ambient || [0, 0, 0, 0]);
      uniforms.uTint.value.fromArray(fields.tint);
      if (fields.kind === "blendAdditive") {
        const [ax, ay, aox, aoy] = fields.additive.uv;
        uniforms.uSecond.value = fields.secondImage;
        uniforms.uSecondST.value.set(ax, ay, aox, 1 - ay - aoy);
      } else if (fields.kind === "waveTexture") {
        uniforms.uSecond.value = fields.secondImage;
        uniforms.uTime.value = shaderTime;
        fields.wave.layers.forEach((layer, index) => uniforms.uWave.value[index].fromArray(layer));
        uniforms.uWaveColor.value.fromArray(fields.wave.color);
      }
      const side = [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull] ?? T.DoubleSide;
      const transparent = fields.kind === "transparent";
      const render = {
        side, transparent, depthWrite: transparent ? fields.zWrite === true : true,
        depthTest: !transparent || fields.zTest !== 0,
        depthFunc: transparent ? depthFunction(T, fields.zTest) : T.LessEqualDepth,
        blending: transparent ? T.CustomBlending : T.NoBlending
      };
      for (const [key, value] of Object.entries(render)) {
        if (material[key] !== value) {
          material[key] = value;
          if (key === "side" || key === "transparent") material.needsUpdate = true;
        }
      }
      if (transparent) {
        material.blendSrc = material.blendSrcAlpha = blendFactor(T, fields.blend[0]);
        material.blendDst = material.blendDstAlpha = blendFactor(T, fields.blend[1]);
      }
      const comparison = fields.stencilComp ?? 8, pass = fields.stencilPass ?? 0, zFail = fields.stencilZFail ?? 0;
      material.stencilWrite = !(comparison === 0 || comparison === 8) || pass !== 0 || zFail !== 0;
      material.stencilRef = fields.stencil;
      material.stencilFunc = stencilFunction(T, comparison);
      material.stencilFail = T.KeepStencilOp;
      material.stencilZPass = stencilOperation(T, pass);
      // _StencilZFailOp 2 (Replace) also writes the reference where the depth test fails.
      material.stencilZFail = stencilOperation(T, zFail);
      node.renderOrder = fields.queue;
    }
    async function load(fields, logo) {
      fields = normalize(fields, logo);
      if (!fields || fields.unsupported) return fields;
      const loaded = { ...fields, image: await texture(fields.texture) };
      if (fields.kind === "blendAdditive") {
        loaded.secondImage = fields.displayCamera ? cleared : await texture(fields.additive.texture);
      } else if (fields.kind === "waveTexture") loaded.secondImage = await texture(fields.wave.texture);
      return loaded;
    }
    async function loadVariant(variant) {
      if (!variant || variant.unsupported) return variant || null;
      return { background: await load(variant.background, false), logo: await load(variant.logo, true) };
    }
    function dispose() {
      for (const screen of screens) {
        if (screen.logo) screen.node.remove(screen.logo);
        screen.node.material = screen.original;
        screen.node.renderOrder = screen.renderOrder;
      }
      for (const material of owned) material.dispose();
      for (const task of textures.values()) task.then((copy) => copy.dispose(), () => {});
      white.dispose();
      cleared.dispose();
    }
    try {
      for (const screen of screens) {
        screen.programs = new Map();
        screen.fallback = await load(screen.fields.fallback, false);
        screen.initial = await loadVariant(screen.fields.initial);
        screen.variants = await Promise.all(screen.fields.variants.map(loadVariant));
        // Unity submits the extra logo material over the same final submesh.
        screen.logo = new T.Mesh(screen.node.geometry, shader("transparent", false, true));
        screen.logo.name = "Native stage display logo";
        screen.logo.visible = false;
        screen.node.add(screen.logo);
      }
    } catch (error) {
      dispose();
      throw error;
    }
    // `writes`: the mixer state last written into each material this frame (LiveDisplayMixer writes
    // _AmbientColor and _MainTex_ST into the shared Material asset, so every screen drawing that
    // material shows the last write; the mixers run in timeline track order).
    function show(screen, pass, writes, own, shaderTime) {
      if (!pass || pass.unsupported || !pass.background) {
        // Nothing the editor can draw natively (a variant or own materials it cannot read):
        // the screen keeps its glTF material.
        screen.node.material = screen.original;
        screen.node.renderOrder = screen.renderOrder;
        screen.logo.visible = false;
        return;
      }
      // GLBs exported before the material identity: a screen's own write lands on its bg only.
      const written = (fields) => (fields.material !== undefined ? writes.get(fields.material)
        : fields === pass.background ? own : null) || null;
      const background = program(screen, pass.background, false);
      screen.node.material = background;
      setPass(screen.node, background, pass.background, written(pass.background), shaderTime);
      screen.logo.visible = !!pass.logo;
      if (pass.logo) {
        screen.logo.material = program(screen, pass.logo, true);
        setPass(screen.logo, screen.logo.material, pass.logo, written(pass.logo), shaderTime);
      }
    }
    let source, ordered = screens;
    return {
      invalidate() { source = null; },
      update(time, project, clock = null) {
        if (source !== project) {
          const tracks = project?.tracks || [];
          for (const screen of screens) {
            const matches = tracks.filter((track) => track.nativeClass === "LiveDisplayTrack" &&
              track.binding === screen.fields.target && !track.muted);
            screen.track = matches.length === 1 ? matches[0] : null;
            screen.order = screen.track ? tracks.indexOf(screen.track) : -1;
          }
          ordered = [...screens].sort((a, b) => a.order - b.order);
          source = project;
        }
        const shaderTime = typeof clock === "function" ? clock(time) : time;
        const writes = new Map(), passes = new Map();
        for (const screen of ordered) {
          // A disabled stage display shows material2DReference; one without it is forced on.
          const enabled = !screen.fallback || project?.quality?.values?.stage_display !== false;
          if (!enabled) {
            passes.set(screen, screen.fallback.unsupported ? screen.fallback : { background: screen.fallback, logo: null });
          } else if (!screen.track) {
            // Without a LiveDisplayTrack nothing switches the renderer's own materials.
            passes.set(screen, screen.initial);
          } else {
            const state = sample(screen.track, time);
            const selected = screen.variants[Math.max(0, Math.min(screen.variants.length - 1, state.material))];
            if (selected?.unsupported) {
              passes.set(screen, screen.initial?.unsupported ? selected : screen.initial);
            } else {
              passes.set(screen, selected);
              screen.state = state;
              if (selected.background.material !== undefined) writes.set(selected.background.material, state);
            }
          }
        }
        for (const screen of screens) {
          const pass = passes.get(screen);
          show(screen, pass, writes, screen.variants.includes(pass) ? screen.state : null, shaderTime);
        }
      },
      dispose
    };
  }
  global.MVStudioStageDisplay = { apply, sample };
})(window);
