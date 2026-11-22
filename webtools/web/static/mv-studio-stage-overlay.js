(function (global) {
  "use strict";

  const layer = 20;
  const vertexShader = [
    "attribute vec4 _stage_color;",
    "uniform vec4 uTextureST;",
    "uniform bool uVertexColor;",
    "varying vec2 vTexture;",
    "varying vec4 vColor;",
    "void main() {",
    "  vTexture = uv * uTextureST.xy + vec2(uTextureST.z, 1.0 - uTextureST.y - uTextureST.w);",
    "  vColor = uVertexColor ? _stage_color : vec4(1.0);",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
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

  async function apply(T, root, parser) {
    const meshes = [], owners = new Map(), textures = new Map();
    root.traverse((node) => {
      const fields = node.geometry?.userData?.mvStageOverlay;
      if (!node.isMesh || !fields || Array.isArray(node.material)) return;
      let owner = node;
      while (owner && typeof owner.userData.mvStageNode?.binding !== "string") owner = owner.parent;
      if (!owner) return;
      owners.set(owner, 1 + (owners.get(owner) || 0));
      meshes.push({ node, owner, fields, original: node.material, order: node.renderOrder, layer: node.layers.mask });
    });
    const ready = [], usable = meshes.filter(({ owner }) => owners.get(owner) === 1);
    if (!usable.length) return null;
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
    function dispose() {
      for (const { node, owner, order, layer, original, material } of ready) {
        delete owner.userData.mvStageOverlayChannels;
        node.material = original;
        node.renderOrder = order;
        node.layers.mask = layer;
        material.dispose();
      }
      for (const task of textures.values()) task.then((copy) => copy.dispose(), () => {});
      white.dispose();
    }
    try {
      for (const mesh of usable) {
        const { node, owner, fields } = mesh;
        const tint = new T.Vector4().fromArray(fields.tint), uv = new T.Vector4().fromArray(fields.uv);
        // Unity's CullMode values specify the side to discard. Three's side
        // specifies the faces to retain. Old previews are double-sided.
        const side = [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull] ?? T.DoubleSide;
        const material = new T.ShaderMaterial({
          vertexShader, fragmentShader, transparent: true, depthTest: false, depthWrite: false,
          toneMapped: false, side, blending: T.CustomBlending,
          blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor, blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
          uniforms: { uTexture: { value: await texture(fields.texture) }, uTint: { value: tint },
            uTextureST: { value: uv }, uVertexColor: { value: fields.vertexColor } }
        });
        material.name = "Native stage overlay";
        // Unity's built-in Plane has no authored vertex color.
        material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        node.material = material;
        node.renderOrder = fields.queue;
        node.layers.set(layer);
        owner.userData.mvStageOverlayChannels = { overlayTint: tint, overlayUV: uv };
        ready.push({ ...mesh, material });
      }
    } catch (error) {
      dispose();
      throw error;
    }
    return { hasVisible: () => ready.some(hasVisible), dispose };
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
  global.MVStudioStageOverlay = { apply, create };
})(typeof window !== "undefined" ? window : globalThis);
