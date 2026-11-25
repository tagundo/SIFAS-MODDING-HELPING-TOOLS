(function (global) {
  "use strict";

  const vertexShader = `
    #ifdef MEMBER
      #include <common>
      #include <morphtarget_pars_vertex>
      #include <skinning_pars_vertex>
      attribute highp vec4 _sifas_color;
      uniform mediump float memberRimIntensity;
      uniform highp float memberResolutionRatio;
    #endif
    #ifdef CUTOUT
      uniform vec4 mainUVTransform;
      varying highp vec2 vUv;
    #endif
    void main() {
      #ifdef CUTOUT
        vUv = uv * mainUVTransform.xy + mainUVTransform.zw;
      #endif
      #ifdef MEMBER
        #include <beginnormal_vertex>
        #include <morphnormal_vertex>
        #include <skinbase_vertex>
        #include <skinnormal_vertex>
        #include <begin_vertex>
        #include <morphtarget_vertex>
        #include <skinning_vertex>
        #include <project_vertex>
        if (memberRimIntensity <= 0.0) {
          vec3 viewNormal = normalize(normalMatrix * objectNormal);
          if (projectionMatrix[3].w == 0.0) {
            float scale = max(-mvPosition.z, 0.0) * memberResolutionRatio;
            scale /= abs(projectionMatrix[1].y) * 0.267949194;
            scale = scale < 0.899999976 ? scale * 1.11111116 : scale * 0.555555582 + 0.5;
            vec2 shift = projectionMatrix[0].xy * viewNormal.x + projectionMatrix[1].xy * viewNormal.y;
            gl_Position.xy += shift * _sifas_color.r * scale * 0.00100000005;
          }
          gl_Position.z += (1.0 - _sifas_color.g) * 0.000699999975;
        }
      #else
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      #endif
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
    const depth = extras?.mvStageCameraDepth;
    const kind = depth?.kind;
    if (kind === "member" || kind === "memberFace") {
      const {position, normal, _sifas_color: color, skinIndex, skinWeight} = node.geometry.attributes;
      const matching = (attribute, size) => attribute?.itemSize === size && attribute.count === position?.count;
      const skinned = node.isSkinnedMesh === true;
      if (kind === "memberFace") {
        const {bones, boneInverses} = node.skeleton || {};
        if (!skinned || bones?.length !== 1 || !bones[0]?.isBone ||
            boneInverses?.length !== 1 || !boneInverses[0]?.isMatrix4) return null;
      }
      return material.isShaderMaterial && material.userData.sifas?.shader === "AS/Member" &&
        !material.userData.viewerHelper && !material.transparent && material.depthWrite &&
        Number.isInteger(depth.queue) && depth.queue >= 0 && depth.queue <= 2500 &&
        Number.isFinite(material.userData.mvStageMemberDepthRim?.value) &&
        position?.itemSize === 3 && position.count > 0 && matching(normal, 3) && matching(color, 4) &&
        (!skinned || node.skeleton?.bones?.length && matching(skinIndex, 4) && matching(skinWeight, 4)) ? kind : null;
    }
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

  // The scissor box, depth clear value and depth write mask a context holds: the values
  // getParameter returns, kept from the context's own setters, which are wrapped once per
  // context. capture() runs every frame with soft billboards in view, and each getParameter
  // there is a synchronous round trip that waits for every command queued so far.
  const rasterStates = new WeakMap();
  function rasterState(gl) {
    let state = rasterStates.get(gl);
    if (state) return state;
    const read = () => {
      state.scissor = Array.from(gl.getParameter(gl.SCISSOR_BOX));
      state.clearDepth = gl.getParameter(gl.DEPTH_CLEAR_VALUE);
      state.depthMask = gl.getParameter(gl.DEPTH_WRITEMASK);
    };
    state = {};
    read();
    const {scissor, clearDepth, depthMask} = gl;
    // The same conversions as the WebGL IDL (GLint/GLsizei, GLclampf clamped by GL, GLboolean).
    // A negative size is INVALID_VALUE and leaves the box unchanged; a lost context changes nothing.
    gl.scissor = function (x, y, width, height) {
      const result = scissor.call(this, x, y, width, height);
      const box = [x | 0, y | 0, width | 0, height | 0];
      if (box[2] >= 0 && box[3] >= 0 && !gl.isContextLost()) state.scissor = box;
      return result;
    };
    gl.clearDepth = function (depth) {
      const result = clearDepth.call(this, depth);
      if (!gl.isContextLost()) state.clearDepth = Math.min(1, Math.max(0, Math.fround(depth)));
      return result;
    };
    gl.depthMask = function (flag) {
      const result = depthMask.call(this, flag);
      if (!gl.isContextLost()) state.depthMask = Boolean(flag);
      return result;
    };
    // A restored context starts again from the defaults.
    gl.canvas?.addEventListener?.("webglcontextrestored", read);
    rasterStates.set(gl, state);
    return state;
  }

  function create(T, renderer) {
    if (!renderer.capabilities.isWebGL2) return null;
    const gl = renderer.getContext(), scene = new T.Scene(), proxies = new WeakMap();
    const raster = rasterState(gl);
    const materials = new Map(), viewport = new T.Vector4(), scissor = new T.Vector4();
    const targetViewport = new T.Vector4(), targetScissor = new T.Vector4();
    let target = null, ready = false, disposed = false;
    scene.autoUpdate = false;

    function pass(kind, skinning, morphTargets, morphNormals) {
      const members = kind === "member";
      const key = members ? `${kind}:${skinning}:${morphTargets}:${morphNormals}` : kind;
      if (!materials.has(key)) {
        const cutout = kind === "cutout";
        const uniforms = {};
        if (cutout) Object.assign(uniforms, {mainMap: {value: null}, mainUVTransform: {value: new T.Vector4()},
          alphaCutoff: {value: 0}});
        if (members) Object.assign(uniforms, {memberRimIntensity: {value: 0}, memberResolutionRatio: {value: 1}});
        materials.set(key, new T.ShaderMaterial({
          vertexShader, fragmentShader, defines: members ? {MEMBER: 1} : cutout ? {CUTOUT: 1} : {},
          uniforms, skinning, morphTargets, morphNormals,
          side: T.FrontSide, depthTest: true, depthWrite: true, depthFunc: T.LessEqualDepth,
          colorWrite: false, blending: T.NoBlending, toneMapped: false,
        }));
      }
      return materials.get(key);
    }

    function bindMemberUniforms() {
      const {source, ratio} = this.userData;
      const {material} = this;
      material.uniforms.memberRimIntensity.value = source.userData.mvStageMemberDepthRim.value;
      material.uniforms.memberResolutionRatio.value = ratio;
      material.uniformsNeedUpdate = true;
    }

    function addCaster(node, camera, ratio) {
      const source = node.material;
      if (!node.isMesh || node.isInstancedMesh || !source?.visible || !node.layers.test(camera.layers)) return false;
      const kind = depthKind(node, source);
      if (!kind) return false;
      const rigidFace = kind === "memberFace", members = rigidFace || kind === "member";
      const skinning = node.isSkinnedMesh === true && !rigidFace;
      const morphed = Boolean(node.morphTargetInfluences?.length);
      if (!members && (skinning || morphed)) return false;
      const morphTargets = morphed && source.morphTargets === true;
      const morphNormals = morphTargets && source.morphNormals === true;
      const depthMaterial = pass(rigidFace ? "member" : kind, skinning, morphTargets, morphNormals);
      let surrogate = proxies.get(node);
      if (!surrogate || Boolean(surrogate.isSkinnedMesh) !== skinning) {
        surrogate = skinning ? new T.SkinnedMesh(node.geometry, depthMaterial) : new T.Mesh(node.geometry, depthMaterial);
        proxies.set(node, surrogate);
      }
      surrogate.geometry = node.geometry;
      surrogate.material = depthMaterial;
      surrogate.frustumCulled = node.frustumCulled;
      surrogate.layers.mask = node.layers.mask;
      surrogate.matrixWorld.copy(node.matrixWorld);
      if (members) {
        if (rigidFace) {
          // MergeFace is rigid in game. Use the carrier in the model matrix
          // so the depth shader inverse-transposes the entire posed basis.
          const {bones, boneInverses} = node.skeleton;
          surrogate.matrixWorld.multiply(node.bindMatrixInverse).multiply(bones[0].matrixWorld)
            .multiply(boneInverses[0]).multiply(node.bindMatrix);
        } else if (skinning) {
          surrogate.skeleton = node.skeleton;
          surrogate.bindMatrix.copy(node.bindMatrix);
          surrogate.bindMatrixInverse.copy(node.bindMatrixInverse);
        }
        surrogate.morphTargetInfluences = node.morphTargetInfluences;
        surrogate.userData.source = source;
        surrogate.userData.ratio = ratio;
        surrogate.onBeforeRender = bindMemberUniforms;
      } else if (kind === "cutout") {
        surrogate.onBeforeRender = () => {
          depthMaterial.uniforms.mainMap.value = source.uniforms.mainMap.value;
          depthMaterial.uniforms.mainUVTransform.value.copy(source.uniforms.mainUVTransform.value);
          depthMaterial.uniforms.alphaCutoff.value = source.uniforms.alphaCutoff.value;
          depthMaterial.uniformsNeedUpdate = true;
        };
      } else surrogate.onBeforeRender = T.Object3D.prototype.onBeforeRender;
      scene.add(surrogate);
      return skinning;
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
      scissor.fromArray(raster.scissor);
      const scissorTest = gl.isEnabled(gl.SCISSOR_TEST), depthTest = gl.isEnabled(gl.DEPTH_TEST);
      const clearDepth = raster.clearDepth, depthMask = raster.depthMask;
      const state = renderer.state, renderInfo = renderer.info;
      const previousAutoReset = renderInfo?.autoReset;
      let skinned = false;
      try {
        if (source.autoUpdate) source.updateMatrixWorld();
        const ratio = Math.min(1, renderer.domElement.height / (viewport.w || height));
        source.traverseVisible(node => {
          if (addCaster(node, camera, ratio)) skinned = true;
        });
        // Three r128 updates a shared skeleton once per info.render.frame.
        // Keep this prepass in the same frame as the subsequent camera draw.
        if (skinned && renderInfo) renderInfo.autoReset = false;
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
        if (skinned && renderInfo) renderInfo.autoReset = previousAutoReset;
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
