(function (global) {
  "use strict";

  const vertexShader = `
    #ifdef CUTOUT
      uniform vec4 mainUVTransform;
      varying highp vec2 vUv;
    #endif
    void main() {
      #ifdef CUTOUT
        vUv = uv * mainUVTransform.xy + mainUVTransform.zw;
      #endif
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `;

  const fragmentShader = `
    #ifdef CUTOUT
      uniform mediump sampler2D mainMap;
      uniform float alphaCutoff;
      varying highp vec2 vUv;
    #endif
    void main() {
      #ifdef CUTOUT
        if (texture2D(mainMap, vUv).a < alphaCutoff) discard;
      #endif
      gl_FragColor = vec4(0.0);
    }
  `;

  function depthKind(node, material) {
    const extras = node.geometry?.userData;
    const kind = extras?.mvStageCameraDepth?.kind;
    if (kind === "opaque") return kind;
    if (kind === "cutout") {
      const uniforms = material.uniforms;
      return node.geometry.getAttribute("uv") && uniforms?.mainMap?.value?.isTexture &&
        uniforms.mainUVTransform?.value?.isVector4 && Number.isFinite(uniforms.alphaCutoff?.value) ? kind : null;
    }
    // The display controller may submit a translucent logo with the same
    // geometry as the opaque screen. Only the native background writes depth.
    if (extras?.mvStageDisplay && material.isShaderMaterial && material.uniforms?.uTexture &&
        !material.transparent && material.depthWrite && node.renderOrder > 0 && node.renderOrder <= 2500) return "opaque";
    return null;
  }

  function create(T, renderer) {
    if (!renderer.capabilities.isWebGL2) return null;
    const gl = renderer.getContext(), scene = new T.Scene(), proxies = new WeakMap();
    const materials = new Map(), viewport = new T.Vector4(), scissor = new T.Vector4();
    const targetViewport = new T.Vector4(), targetScissor = new T.Vector4();
    let target = null, ready = false, disposed = false;
    scene.autoUpdate = false;

    function pass(kind) {
      if (!materials.has(kind)) {
        const cutout = kind === "cutout";
        materials.set(kind, new T.ShaderMaterial({
          vertexShader, fragmentShader, defines: cutout ? {CUTOUT: 1} : {},
          uniforms: cutout ? {mainMap: {value: null}, mainUVTransform: {value: new T.Vector4()},
            alphaCutoff: {value: 0}} : {},
          side: T.FrontSide, depthTest: true, depthWrite: true, depthFunc: T.LessEqualDepth,
          colorWrite: false, blending: T.NoBlending, toneMapped: false,
        }));
      }
      return materials.get(kind);
    }

    function addCaster(node, camera) {
      const source = node.material;
      if (!node.isMesh || node.isSkinnedMesh || node.isInstancedMesh || node.morphTargetInfluences?.length ||
          !source?.visible || !node.layers.test(camera.layers)) return;
      const kind = depthKind(node, source);
      if (!kind) return;
      const depthMaterial = pass(kind);
      let surrogate = proxies.get(node);
      if (!surrogate) {
        surrogate = new T.Mesh(node.geometry, depthMaterial);
        proxies.set(node, surrogate);
      }
      surrogate.geometry = node.geometry;
      surrogate.material = depthMaterial;
      surrogate.frustumCulled = node.frustumCulled;
      surrogate.layers.mask = node.layers.mask;
      surrogate.matrixWorld.copy(node.matrixWorld);
      if (kind === "cutout") {
        surrogate.onBeforeRender = () => {
          depthMaterial.uniforms.mainMap.value = source.uniforms.mainMap.value;
          depthMaterial.uniforms.mainUVTransform.value.copy(source.uniforms.mainUVTransform.value);
          depthMaterial.uniforms.alphaCutoff.value = source.uniforms.alphaCutoff.value;
          depthMaterial.uniformsNeedUpdate = true;
        };
      } else surrogate.onBeforeRender = T.Object3D.prototype.onBeforeRender;
      scene.add(surrogate);
    }

    function capture(source, camera) {
      if (disposed || !source?.isScene || !camera?.isCamera || gl.isContextLost()) return null;
      const previousTarget = renderer.getRenderTarget(), previousClear = renderer.autoClear;
      const width = previousTarget?.width ?? renderer.domElement.width;
      const height = previousTarget?.height ?? renderer.domElement.height;
      if (!(width > 0 && height > 0 && Math.max(width, height) <= renderer.capabilities.maxTextureSize)) return null;
      if (!target || target.width !== width || target.height !== height) {
        target?.dispose();
        const depth = new T.DepthTexture(width, height, T.UnsignedIntType);
        depth.name = "Native Camera DepthTexture";
        depth.minFilter = depth.magFilter = T.NearestFilter;
        target = new T.WebGLRenderTarget(width, height, {
          depthTexture: depth, minFilter: T.NearestFilter, magFilter: T.NearestFilter,
          depthBuffer: true, stencilBuffer: false,
        });
        ready = false;
      }
      const shadow = renderer.shadowMap, shadowsEnabled = shadow.enabled;
      const cubeFace = renderer.getActiveCubeFace(), mipLevel = renderer.getActiveMipmapLevel();
      renderer.getCurrentViewport(viewport);
      scissor.fromArray(gl.getParameter(gl.SCISSOR_BOX));
      const scissorTest = gl.isEnabled(gl.SCISSOR_TEST), depthTest = gl.isEnabled(gl.DEPTH_TEST);
      const clearDepth = gl.getParameter(gl.DEPTH_CLEAR_VALUE), depthMask = gl.getParameter(gl.DEPTH_WRITEMASK);
      const state = renderer.state;
      try {
        if (source.autoUpdate) source.updateMatrixWorld();
        source.traverseVisible(node => addCaster(node, camera));
        renderer.autoClear = false;
        shadow.enabled = false;
        renderer.setRenderTarget(target);
        if (!ready) ready = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
        if (!ready) return null;
        state.buffers.depth.setClear(1);
        state.buffers.depth.setMask(true);
        renderer.clearDepth();
        renderer.render(scene, camera);
        return target.depthTexture;
      } finally {
        scene.clear();
        renderer.autoClear = previousClear;
        shadow.enabled = shadowsEnabled;
        state.buffers.depth.setClear(clearDepth);
        state.buffers.depth.setMask(depthMask);
        state.buffers.depth.setTest(depthTest);
        if (previousTarget) {
          // A caller may have set a viewport or scissor after binding its
          // target. Restore the active raster state and the target defaults.
          targetViewport.copy(previousTarget.viewport);
          targetScissor.copy(previousTarget.scissor);
          const targetScissorTest = previousTarget.scissorTest;
          previousTarget.viewport.copy(viewport);
          previousTarget.scissor.copy(scissor);
          previousTarget.scissorTest = scissorTest;
          try {
            renderer.setRenderTarget(previousTarget, cubeFace, mipLevel);
          } finally {
            previousTarget.viewport.copy(targetViewport);
            previousTarget.scissor.copy(targetScissor);
            previousTarget.scissorTest = targetScissorTest;
          }
        } else {
          renderer.setRenderTarget(null, cubeFace, mipLevel);
          state.viewport(viewport);
          state.scissor(scissor);
          state.setScissorTest(scissorTest);
        }
      }
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      target?.dispose();
      target = null;
      for (const material of materials.values()) material.dispose();
      materials.clear();
    }

    return {capture, dispose};
  }

  global.MVStudioCameraDepth = {create};
})(window);
