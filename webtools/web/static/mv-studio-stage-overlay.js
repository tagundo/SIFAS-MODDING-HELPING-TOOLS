(function (global) {
  "use strict";

  const layer = 20;
  const materialOwners = new WeakMap();
  const materialKey = (scope, rendererClass) => `${scope}:${rendererClass}`;
  const vertexShader = [
    "#include <common>",
    "#include <skinning_pars_vertex>",
    "attribute vec4 _stage_color;",
    "uniform vec4 uTextureST;",
    "uniform bool uVertexColor;",
    "varying vec2 vTexture;",
    "varying vec4 vColor;",
    "void main() {",
    "  vTexture = uv * uTextureST.xy + vec2(uTextureST.z, 1.0 - uTextureST.y - uTextureST.w);",
    "  vColor = uVertexColor ? _stage_color : vec4(1.0);",
    "  #include <begin_vertex>",
    "  #include <skinbase_vertex>",
    "  #include <skinning_vertex>",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "varying vec2 vTexture;",
    "varying vec4 vColor;",
    "void main() { gl_FragColor = texture2D(uTexture, vTexture) * vColor * uTint; }"
  ].join("\n");

  function hasVisible({ node, material }) {
    if (material.uniforms.uTint.value.w <= 0) return false;
    let current = node;
    while (current) {
      if (!current.visible) return false;
      current = current.parent;
    }
    return true;
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
      if (rendererClass !== (skinned ? 137 : 23) || (scope === "world" && fields.depthTest !== true)) return;
      const alphaBlend = fields.alphaBlend === true, stencilRef = fields.stencilRef;
      if ((alphaBlend || stencilRef !== undefined) &&
          (scope !== "world" || !alphaBlend || !Number.isInteger(stencilRef) || stencilRef < 0 || stencilRef > 255)) return;
      if (skinned && (!(node.userData.mvStageSkin === true || node.parent?.userData.mvStageSkin === true) ||
          !node.skeleton || !node.geometry.getAttribute("skinIndex") || !node.geometry.getAttribute("skinWeight"))) return;
      let sortAnchor = null;
      if (alphaBlend) {
        const {queue, sortCenter, sortJoint} = fields;
        if (!Number.isInteger(queue) || queue < 0 || queue > 5000 ||
            !Array.isArray(sortCenter) || sortCenter.length !== 3 || !sortCenter.every(Number.isFinite)) return;
        if (skinned) {
          if (!Number.isInteger(sortJoint) || sortJoint < 0 || !node.skeleton.bones[sortJoint]?.isBone) return;
          sortAnchor = node.skeleton.bones[sortJoint];
        } else {
          if (sortJoint !== undefined) return;
          sortAnchor = node;
        }
      }
      let owner = node;
      while (owner && typeof owner.userData.mvStageNode?.binding !== "string") owner = owner.parent;
      if (!owner) return;
      let classes = owners.get(owner);
      if (!classes) owners.set(owner, classes = new Map());
      const key = materialKey(scope, rendererClass);
      classes.set(key, 1 + (classes.get(key) || 0));
      meshes.push({ node, owner, fields, rendererClass, scope, key, skinned, alphaBlend, stencilRef, sortAnchor, original: node.material,
        order: node.renderOrder, layer: node.layers.mask, frustumCulled: node.frustumCulled });
    });
    const ready = [], usable = meshes.filter(({ owner, key }) => owners.get(owner).get(key) === 1);
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
      sampler?.dispose();
      white.dispose();
    }
    try {
      for (const mesh of usable) {
        if (!active()) break;
        const { node, owner, fields, rendererClass, scope, key, skinned, alphaBlend, stencilRef } = mesh;
        const map = sampler && scope === "world" && fields.texture !== null && fields.mainSampler
          ? await sampler.sampledNativeTexture(fields.texture, fields.mainSampler) : await texture(fields.texture);
        if (!active()) break;
        if (!map) continue;
        const tint = new T.Vector4().fromArray(fields.tint), uv = new T.Vector4().fromArray(fields.uv);
        // Unity's CullMode values specify the side to discard. Three's side
        // specifies the faces to retain. Old previews are double-sided.
        const side = [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull] ?? T.DoubleSide;
        const blendDst = alphaBlend ? T.OneMinusSrcAlphaFactor : T.OneFactor;
        const material = new T.ShaderMaterial({
          vertexShader, fragmentShader, transparent: true, skinning: skinned,
          depthTest: fields.depthTest === true, depthFunc: T.LessEqualDepth, depthWrite: false,
          toneMapped: false, side, blending: T.CustomBlending,
          blendSrc: T.SrcAlphaFactor, blendDst, blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: blendDst,
          stencilWrite: alphaBlend, stencilFunc: alphaBlend ? T.EqualStencilFunc : T.AlwaysStencilFunc,
          stencilRef: stencilRef ?? 0, stencilFuncMask: 255, stencilWriteMask: 255,
          stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
          uniforms: { uTexture: { value: map }, uTint: { value: tint },
            uTextureST: { value: uv }, uVertexColor: { value: fields.vertexColor } }
        });
        material.name = scope === "world" ? "Native stage transparent" : "Native stage overlay";
        // Unity's built-in Plane has no authored vertex color.
        material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        node.material = material;
        node.renderOrder = fields.queue;
        if (scope === "overlay") node.layers.set(layer);
        if (skinned) node.frustumCulled = false;
        const channels = { overlayTint: tint, overlayUV: uv };
        let classes = materialOwners.get(owner);
        if (!classes) materialOwners.set(owner, classes = new Map());
        classes.set(key, channels);
        if (scope === "overlay" && rendererClass === 23) owner.userData.mvStageOverlayChannels = channels;
        ready.push({ ...mesh, material });
      }
    } catch (error) {
      dispose();
      throw error;
    }

    const byQueue = new Map();
    for (const {node, fields, sortAnchor} of ready) {
      if (!sortAnchor) continue;
      let group = byQueue.get(fields.queue);
      if (!group) byQueue.set(fields.queue, group = []);
      group.push({node, anchor: sortAnchor, center: new T.Vector3().fromArray(fields.sortCenter),
        order: group.length, distance: 0});
    }
    const groups = [...byQueue].filter(([, entries]) => entries.length > 1);
    const eye = new T.Vector3(), point = new T.Vector3();
    function sort(camera) {
      if (disposed || groups.length === 0) return;
      camera.updateWorldMatrix(true, false);
      eye.setFromMatrixPosition(camera.matrixWorld);
      for (const [queue, entries] of groups) {
        for (const entry of entries) {
          entry.anchor.updateWorldMatrix(true, false);
          point.copy(entry.center).applyMatrix4(entry.anchor.matrixWorld);
          entry.distance = Math.fround(camera.isOrthographicCamera
            ? -point.applyMatrix4(camera.matrixWorldInverse).z : eye.distanceToSquared(point));
        }
        entries.sort((a, b) => b.distance - a.distance || a.order - b.order);
        for (const [index, entry] of entries.entries()) entry.node.renderOrder = queue + index / entries.length;
      }
    }
    return {
      hasVisible: () => !disposed && ready.some(entry => entry.scope === "overlay" && hasVisible(entry)),
      hasDepthTest: () => !disposed && ready.some(entry =>
        entry.scope === "overlay" && entry.material.depthTest && hasVisible(entry)),
      sort, dispose,
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
    apply, create,
    materialChannel(owner, kind, rendererClass = 23, scope = "overlay") {
      if ((rendererClass === 23 || rendererClass === 137) && (scope === "overlay" || scope === "world")) {
        return materialOwners.get(owner)?.get(materialKey(scope, rendererClass))?.[kind];
      }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
