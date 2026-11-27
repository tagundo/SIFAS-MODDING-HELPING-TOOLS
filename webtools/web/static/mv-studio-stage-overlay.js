(function (global) {
  "use strict";

  const layer = 20;
  const materialOwners = new WeakMap();
  const materialKey = (scope, rendererClass) => `${scope}:${rendererClass}`;
  const varyings = [
    "#ifdef MATCAP",
    "  varying highp vec2 vTexture;",
    "  varying mediump vec4 vColor;",
    "#else",
    "  varying vec2 vTexture;",
    "  varying vec4 vColor;",
    "#endif",
  ];
  const vertexShader = [
    "#include <common>",
    "#include <skinning_pars_vertex>",
    "#ifdef MATCAP",
    "  attribute mediump vec4 _stage_color;",
    "#else",
    "  attribute vec4 _stage_color;",
    "  uniform vec4 uTextureST;",
    "  uniform bool uVertexColor;",
    "#endif",
    ...varyings,
    "void main() {",
    "  #include <begin_vertex>",
    "  #include <skinbase_vertex>",
    "  #include <skinning_vertex>",
    "  #ifdef MATCAP",
    "    #include <beginnormal_vertex>",
    "    #include <skinnormal_vertex>",
    "    vec3 viewNormal = normalize(normalMatrix * objectNormal);",
    "    vTexture = vec2(0.5) + vec2(0.5, -0.5) * viewNormal.xy;",
    "    vColor = _stage_color;",
    "  #else",
    "    vTexture = uv * uTextureST.xy + vec2(uTextureST.z, 1.0 - uTextureST.y - uTextureST.w);",
    "    vColor = uVertexColor ? _stage_color : vec4(1.0);",
    "  #endif",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "#ifdef MATCAP",
    "  uniform mediump sampler2D uTexture;",
    "  uniform mediump vec4 uTint;",
    "  uniform mediump vec3 uAddColor;",
    "#else",
    "  uniform sampler2D uTexture;",
    "  uniform vec4 uTint;",
    "#endif",
    ...varyings,
    "void main() {",
    "  #ifdef MATCAP",
    "    mediump vec4 surface = texture2D(uTexture, vTexture);",
    "    surface.rgb += uAddColor;",
    "  #else",
    "    vec4 surface = texture2D(uTexture, vTexture);",
    "  #endif",
    "  gl_FragColor = surface * vColor * uTint;",
    // AS/General/Transparent _SATURATE_ON: SV_Target.rgb = (tex.rgb^2)^2 + tex * tint * COLOR,
    // alpha unchanged (its GLES3 fragment program).
    "  #ifdef SATURATE",
    "    vec3 square = surface.rgb * surface.rgb;",
    "    gl_FragColor.rgb += square * square;",
    "  #endif",
    "}"
  ].join("\n");

  // UnityEngine.Rendering.BlendMode, CompareFunction and StencilOp, in their enum order.
  function blendFactor(T, value) {
    return [T.ZeroFactor, T.OneFactor, T.DstColorFactor, T.SrcColorFactor, T.OneMinusDstColorFactor,
      T.SrcAlphaFactor, T.OneMinusSrcColorFactor, T.DstAlphaFactor, T.OneMinusDstAlphaFactor,
      T.SrcAlphaSaturateFactor, T.OneMinusSrcAlphaFactor][value];
  }
  function depthFunction(T, value) {
    return [T.AlwaysDepth, T.NeverDepth, T.LessDepth, T.EqualDepth, T.LessEqualDepth, T.GreaterDepth,
      T.NotEqualDepth, T.GreaterEqualDepth, T.AlwaysDepth][value];
  }
  function stencilFunction(T, value) {
    return [T.AlwaysStencilFunc, T.NeverStencilFunc, T.LessStencilFunc, T.EqualStencilFunc, T.LessEqualStencilFunc,
      T.GreaterStencilFunc, T.NotEqualStencilFunc, T.GreaterEqualStencilFunc, T.AlwaysStencilFunc][value];
  }
  function stencilOperation(T, value) {
    return [T.KeepStencilOp, T.ZeroStencilOp, T.ReplaceStencilOp, T.IncrementStencilOp, T.DecrementStencilOp,
      T.InvertStencilOp, T.IncrementWrapStencilOp, T.DecrementWrapStencilOp][value];
  }
  const integer = (value, high) => Number.isInteger(value) && value >= 0 && value <= high;

  // The pass state of one descriptor: [src, dst] blend, ZTest, ZWrite and [comp, ref, pass, zFail]
  // stencil, all property-bound in AS/General/Transparent. Descriptors exported before those
  // fields carry the additive profile or the world alpha profile masked by stencil Equal.
  function passState(fields) {
    if (fields.blend === undefined && fields.zTest === undefined && fields.stencil === undefined) {
      const alpha = fields.alphaBlend === true;
      return { blend: [5, alpha ? 10 : 1], zTest: fields.depthTest === true ? 4 : 8, zWrite: fields.depthWrite === true,
        stencil: fields.stencilRef === undefined ? [8, 2, 0, 0] : [3, fields.stencilRef, 0, 0], full: false };
    }
    const { blend, zTest, stencil } = fields;
    if (!Array.isArray(blend) || blend.length !== 2 || !blend.every(value => integer(value, 10)) || !integer(zTest, 8) ||
        !Array.isArray(stencil) || stencil.length !== 4 || !integer(stencil[0], 8) || !integer(stencil[1], 255) ||
        !integer(stencil[2], 7) || !integer(stencil[3], 7) || fields.depthTest !== undefined && fields.depthTest !== (zTest === 4) ||
        fields.saturate !== undefined && fields.saturate !== true) return null;
    return { blend, zTest, zWrite: fields.depthWrite === true, stencil, full: true };
  }

  // One native AS/General/Transparent (or MatCap) pass: its uniforms, blend, cull, depth and stencil state.
  function createMaterial(T, fields, state, map, { skinned = false, matcap = false, depthWrite = false } = {}) {
    const tint = new T.Vector4().fromArray(fields.tint), channels = { overlayTint: tint };
    const uniforms = { uTexture: { value: map }, uTint: { value: tint } };
    if (matcap) {
      uniforms.uAddColor = { value: new T.Vector3().fromArray(fields.addColor) };
    } else {
      channels.overlayUV = new T.Vector4().fromArray(fields.uv);
      uniforms.uTextureST = { value: channels.overlayUV };
      uniforms.uVertexColor = { value: fields.vertexColor };
    }
    // Unity's CullMode values specify the side to discard. Three's side
    // specifies the faces to retain. Old previews are double-sided.
    const side = [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull] ?? T.DoubleSide;
    const [blendSrc, blendDst] = state.blend.map(value => blendFactor(T, value));
    const [comparison, reference, pass, zFail] = state.stencil;
    // Comp Disabled/Always with Keep on pass and depth fail leaves the stencil untouched.
    const stencilTest = !(comparison === 0 || comparison === 8) || pass !== 0 || zFail !== 0;
    // ZTest Disabled/Always passes every fragment; WebGL writes depth only with its test on.
    const always = state.zTest === 0 || state.zTest === 8;
    const defines = matcap ? { MATCAP: 1 } : fields.saturate === true ? { SATURATE: 1 } : {};
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, defines, transparent: true, skinning: skinned,
      depthTest: !always || depthWrite, depthFunc: always ? T.AlwaysDepth : depthFunction(T, state.zTest), depthWrite,
      toneMapped: false, side, blending: T.CustomBlending,
      blendSrc, blendDst, blendSrcAlpha: blendSrc, blendDstAlpha: blendDst,
      stencilWrite: stencilTest, stencilFunc: stencilTest ? stencilFunction(T, comparison) : T.AlwaysStencilFunc,
      stencilRef: stencilTest ? reference : 0, stencilFuncMask: 255, stencilWriteMask: 255,
      stencilFail: T.KeepStencilOp, stencilZFail: stencilOperation(T, zFail), stencilZPass: stencilOperation(T, pass),
      uniforms
    });
    return { material, channels };
  }

  // A full-state AS/General/Transparent pass for another stage module (a LiveCoreStageFlashLight
  // whose material uses this shader), or null when the descriptor is not one.
  function transparentMaterial(T, fields, map) {
    const state = fields && typeof fields === "object" ? passState(fields) : null;
    if (!state?.full || !Array.isArray(fields.tint) || fields.tint.length !== 4 || !fields.tint.every(Number.isFinite) ||
        !Array.isArray(fields.uv) || fields.uv.length !== 4 || !fields.uv.every(Number.isFinite) ||
        typeof fields.vertexColor !== "boolean" || ![0, 1, 2].includes(fields.cull)) return null;
    const { material } = createMaterial(T, fields, state, map, { depthWrite: fields.depthWrite === true });
    material.name = "Native stage transparent";
    material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
    return material;
  }

  function hasVisible({ node, material, state }) {
    // SrcAlpha with One or OneMinusSrcAlpha leaves the target unchanged at zero alpha.
    if (material.uniforms.uTint.value.w <= 0 && state.blend[0] === 5 && (state.blend[1] === 1 || state.blend[1] === 10)) {
      return false;
    }
    let current = node;
    while (current) {
      if (!current.visible) return false;
      current = current.parent;
    }
    return true;
  }

  function validMatcap(geometry, fields) {
    const count = geometry.getAttribute("position")?.count;
    const normal = geometry.getAttribute("normal"), color = geometry.getAttribute("_stage_color");
    const isVector = (row, length) => Array.isArray(row) && row.length === length && row.every(Number.isFinite);
    return fields.world === true && fields.alphaBlend === true && fields.stencilRef === undefined &&
      Number.isInteger(fields.queue) && fields.queue >= 2501 && fields.queue <= 5000 &&
      fields.cull === 2 && fields.vertexColor === true &&
      (fields.texture === null || Number.isSafeInteger(fields.texture) && fields.texture >= 0) &&
      isVector(fields.addColor, 3) && isVector(fields.tint, 4) &&
      count > 0 && normal?.itemSize === 3 && normal.count === count && color?.itemSize === 4 && color.count === count &&
      (color.normalized === true || color.array instanceof Float32Array);
  }

  function sortEntry(T, node, fields, skinned) {
    const {queue, sortCenter, sortJoint} = fields;
    if (fields.world !== true || !Number.isInteger(queue) || queue < 0 || queue > 5000 ||
        !Array.isArray(sortCenter) || sortCenter.length !== 3 || !sortCenter.every(Number.isFinite)) return null;
    const anchor = skinned
      ? Number.isInteger(sortJoint) && sortJoint >= 0 && node.skeleton.bones[sortJoint]
      : sortJoint === undefined && node;
    if (!anchor || skinned && !anchor.isBone) return null;
    return {node, anchor, center: new T.Vector3().fromArray(sortCenter), queue};
  }

  async function apply(T, root, parser, options = {}) {
    const {active = () => true} = options;
    const meshes = [], owners = new Map(), textures = new Map();
    root.traverse((node) => {
      const fields = node.geometry?.userData?.mvStageOverlay;
      if (!node.isMesh || !fields || Array.isArray(node.material)) return;
      const rendererClass = fields.rendererClass === undefined ? 23 : fields.rendererClass;
      const scope = fields.world === true ? "world" : "overlay";
      const skinned = node.isSkinnedMesh === true;
      const state = passState(fields);
      if (!state || rendererClass !== (skinned ? 137 : 23) ||
          (scope === "world" && !state.full && fields.depthTest !== true)) return;
      const alphaBlend = fields.alphaBlend === true, stencilRef = fields.stencilRef;
      const matcap = fields.matcap === true, depthWrite = fields.depthWrite === true;
      if (fields.depthWrite !== undefined && typeof fields.depthWrite !== "boolean") return;
      if (matcap && state.full) return;
      if (!state.full && depthWrite && (scope !== "world" || alphaBlend || matcap || stencilRef !== undefined ||
          fields.queue !== 3000 || fields.texture !== null || fields.vertexColor !== true)) return;
      if (matcap) {
        if (!validMatcap(node.geometry, fields)) return;
      } else if (!state.full && (alphaBlend || stencilRef !== undefined) &&
          (scope !== "world" || !alphaBlend || !Number.isInteger(stencilRef) || stencilRef < 0 || stencilRef > 255)) return;
      if (skinned && (!(node.userData.mvStageSkin === true || node.parent?.userData.mvStageSkin === true) ||
          !node.skeleton || !node.geometry.getAttribute("skinIndex") || !node.geometry.getAttribute("skinWeight"))) return;
      const sort = sortEntry(T, node, fields, skinned);
      // World alpha blends draw in Unity's back-to-front order; the orthographic overlay camera
      // keeps Three's view-depth order.
      if (alphaBlend && !sort && (scope === "world" || !state.full)) return;
      let owner = node;
      while (owner && typeof owner.userData.mvStageNode?.binding !== "string") owner = owner.parent;
      if (!owner) return;
      let classes = owners.get(owner);
      if (!classes) owners.set(owner, classes = new Map());
      const key = materialKey(scope, rendererClass);
      classes.set(key, 1 + (classes.get(key) || 0));
      meshes.push({ node, owner, fields, rendererClass, scope, key, skinned, matcap, alphaBlend, depthWrite, stencilRef, sort,
        state, original: node.material,
        order: node.renderOrder, layer: node.layers.mask, frustumCulled: node.frustumCulled });
    });
    const ready = [], sortEntries = [], usable = meshes.filter(({ owner, key }) => owners.get(owner).get(key) === 1);
    if (!usable.length) return null;
    const sampler = usable.some(({scope, fields}) => scope === "world" && fields.texture !== null && fields.mainSampler)
      ? global.MVStudioStageMaterial?.createTextureSampler?.(T, parser, options) : null;
    if (sampler) {
      root.traverse((node) => sampler.retainOriginalMaterial(node.material));
      for (const {fields} of meshes) if (fields.texture !== null) sampler.reserveBase(fields.texture);
    }
    const white = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    white.needsUpdate = true;
    function texture(index) {
      if (index === null) return Promise.resolve(white);
      if (!textures.has(index)) textures.set(index, parser.getDependency("texture", index).then((original) => {
        const copy = original.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        return copy;
      }));
      return textures.get(index);
    }
    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const { node, owner, rendererClass, scope, key, order, layer, frustumCulled, original, material } of ready) {
        const classes = materialOwners.get(owner);
        classes.delete(key);
        if (!classes.size) materialOwners.delete(owner);
        if (scope === "overlay" && rendererClass === 23) delete owner.userData.mvStageOverlayChannels;
        node.material = original;
        node.renderOrder = order;
        node.layers.mask = layer;
        if (rendererClass === 137) node.frustumCulled = frustumCulled;
        material.dispose();
      }
      for (const task of textures.values()) task.then((copy) => copy.dispose(), () => {});
      sortEntries.length = 0;
      sampler?.dispose();
      white.dispose();
    }
    try {
      for (const mesh of usable) {
        if (!active()) break;
        const { node, owner, fields, rendererClass, scope, key, skinned, matcap, depthWrite, state } = mesh;
        const map = sampler && scope === "world" && fields.texture !== null && fields.mainSampler
          ? await sampler.sampledNativeTexture(fields.texture, fields.mainSampler) : await texture(fields.texture);
        if (!active()) break;
        if (!map) continue;
        const { material, channels } = createMaterial(T, fields, state, map, { skinned, matcap, depthWrite });
        material.name = scope === "world" ? "Native stage transparent" : "Native stage overlay";
        // Unity's built-in Plane has no authored vertex color.
        material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        node.material = material;
        node.renderOrder = fields.queue;
        if (scope === "overlay") node.layers.set(layer);
        if (skinned) node.frustumCulled = false;
        let classes = materialOwners.get(owner);
        if (!classes) materialOwners.set(owner, classes = new Map());
        classes.set(key, channels);
        if (scope === "overlay" && rendererClass === 23) owner.userData.mvStageOverlayChannels = channels;
        ready.push({ ...mesh, material });
        if (mesh.sort) sortEntries.push(mesh.sort);
      }
    } catch (error) {
      dispose();
      throw error;
    }

    return {
      hasVisible: () => !disposed && ready.some(entry => entry.scope === "overlay" && hasVisible(entry)),
      hasDepthTest: () => !disposed && ready.some(entry =>
        entry.scope === "overlay" && entry.material.depthTest && hasVisible(entry)),
      sortEntries: () => sortEntries,
      dispose,
    };
  }

  function create(T, renderer) {
    // GL live scene level35: OverlayCamera, layer 20, depth 20, clear Nothing.
    const camera = new T.OrthographicCamera(-5, 5, 5, -5, 1, 40);
    camera.position.set(0, 200, -10);
    camera.lookAt(0, 200, 0);
    camera.layers.set(layer);
    let lastAspect = 1;
    return {
      draw(scene, beforeDraw) {
        const { width, height } = renderer.domElement;
        if (!width || !height) return;
        const aspect = width / height;
        if (lastAspect !== aspect) {
          camera.left = -5 * aspect;
          camera.right = 5 * aspect;
          camera.updateProjectionMatrix();
          lastAspect = aspect;
        }
        const background = scene.background, autoClear = renderer.autoClear, autoUpdate = scene.autoUpdate;
        scene.background = null;
        renderer.autoClear = false;
        scene.autoUpdate = false;
        try {
          beforeDraw?.(camera);
          renderer.render(scene, camera);
        } finally {
          scene.background = background;
          renderer.autoClear = autoClear;
          scene.autoUpdate = autoUpdate;
        }
      }
    };
  }
  global.MVStudioStageOverlay = {
    apply, create, transparentMaterial,
    materialChannel(owner, kind, rendererClass = 23, scope = "overlay") {
      if ((rendererClass === 23 || rendererClass === 137) && (scope === "overlay" || scope === "world")) {
        return materialOwners.get(owner)?.get(materialKey(scope, rendererClass))?.[kind];
      }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
