(function (global) {
  "use strict";

  const vertex = [
    "attribute vec4 _stage_color;",
    "uniform vec4 uTextureST;",
    "uniform bool uVertexColor;",
    "varying vec2 vScreen;",
    "varying vec4 vColor;",
    "void main() {",
    "  vScreen = uv * uTextureST.xy + uTextureST.zw;",
    "  vColor = uVertexColor ? _stage_color : vec4(1.0);",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragment = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "uniform vec4 uAmbient;",
    "varying vec2 vScreen;",
    "varying vec4 vColor;",
    "void main() {",
    "  vec4 texel = texture2D(uTexture, vScreen) * vColor;",
    "  gl_FragColor = vec4(mix(texel.rgb, uAmbient.rgb, uAmbient.a), texel.a) * uTint;",
    "}"
  ].join("\n");

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
    const white = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    white.needsUpdate = true;
    function texture(index) {
      if (index === null) return Promise.resolve(white);
      if (!textures.has(index)) textures.set(index, parser.getDependency("texture", index).then((source) => {
        const copy = source.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        return copy;
      }));
      return textures.get(index);
    }
    function shader(logo) {
      const uniforms = {
        uTexture: { value: white }, uTextureST: { value: new T.Vector4(1, 1, 0, 0) },
        uVertexColor: { value: false },
        uTint: { value: new T.Vector4(1, 1, 1, 1) }, uAmbient: { value: new T.Vector4(0, 0, 0, 0) }
      };
      const material = new T.ShaderMaterial({
        vertexShader: vertex, fragmentShader: fragment, uniforms, toneMapped: false,
        transparent: logo, depthWrite: !logo, depthTest: true, depthFunc: T.LessEqualDepth,
        blending: logo ? T.CustomBlending : T.NoBlending,
        blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
        blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
        stencilWrite: !logo, stencilFunc: T.AlwaysStencilFunc, stencilZPass: T.ReplaceStencilOp
      });
      material.name = logo ? "Native stage display logo" : "Native stage display background";
      material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
      owned.push(material);
      return material;
    }
    function setPass(node, material, fields, state, logo) {
      const uniforms = material.uniforms;
      const [sx, sy, x, y] = fields.uv, [ox, oy] = state?.offset || [x, y];
      uniforms.uTexture.value = fields.image;
      uniforms.uVertexColor.value = !logo && fields.vertexColor === true;
      uniforms.uTextureST.value.set(sx, sy, ox, 1 - sy - oy);
      uniforms.uAmbient.value.fromArray(logo ? [0, 0, 0, 0] : state?.ambient || fields.ambient);
      uniforms.uTint.value.fromArray(fields.tint);
      const side = [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull];
      if (material.side !== side) {
        material.side = side;
        material.needsUpdate = true;
      }
      material.stencilRef = fields.stencil;
      node.renderOrder = fields.queue;
    }
    const load = async (fields) => fields ? { ...fields, image: await texture(fields.texture) } : null;
    function dispose() {
      for (const screen of screens) {
        if (screen.logo) screen.node.remove(screen.logo);
        screen.node.material = screen.original;
        screen.node.renderOrder = screen.renderOrder;
      }
      for (const material of owned) material.dispose();
      for (const task of textures.values()) task.then((copy) => copy.dispose(), () => {});
      white.dispose();
    }
    try {
      for (const screen of screens) {
        screen.fallback = await load(screen.fields.fallback);
        screen.variants = await Promise.all(screen.fields.variants.map(async ({ background, logo }) =>
          ({ background: await load(background), logo: await load(logo) })));
        screen.background = shader(false);
        screen.node.material = screen.background;
        setPass(screen.node, screen.background, screen.fallback, null, false);
        // Unity submits the extra logo material over the same final submesh.
        screen.logo = new T.Mesh(screen.node.geometry, shader(true));
        screen.logo.name = "Native stage display logo";
        screen.logo.visible = false;
        screen.node.add(screen.logo);
      }
    } catch (error) {
      dispose();
      throw error;
    }
    let source;
    return {
      invalidate() { source = null; },
      update(time, project) {
        if (source !== project) {
          const tracks = project?.tracks || [];
          for (const screen of screens) {
            const matches = tracks.filter((track) => track.nativeClass === "LiveDisplayTrack" &&
              track.binding === screen.fields.target && !track.muted);
            screen.track = matches.length === 1 ? matches[0] : null;
          }
          source = project;
        }
        for (const screen of screens) {
          const state = project?.quality?.values?.stage_display !== false && screen.track
            ? sample(screen.track, time) : null;
          const selected = state ? screen.variants[Math.max(0, Math.min(screen.variants.length - 1, state.material))] : null;
          setPass(screen.node, screen.background, selected?.background || screen.fallback, state, false);
          screen.logo.visible = !!selected?.logo;
          if (screen.logo.visible) setPass(screen.logo, screen.logo.material, selected.logo, null, true);
        }
      },
      dispose
    };
  }
  global.MVStudioStageDisplay = { apply, sample };
})(window);
