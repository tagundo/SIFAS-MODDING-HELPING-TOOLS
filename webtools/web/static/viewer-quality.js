/* SIFAS Smooth3D: native display density and a two-sample MSAA request.
 * Source models, textures and their UVs are never changed by this render pass.
 */
(function () {
  "use strict";

  function create(renderer) {
    var T = window.THREE;
    var enabled = false;
    var cssWidth = 0;
    var cssHeight = 0;
    var target = null;
    var targetNeedsCheck = false;
    var copyScene = null;
    var copyCamera = null;
    var copyMesh = null;
    var disposed = false;
    var interrupted = false;
    var ready = false;
    var effectiveSamples = 0;
    var contextSamples = 0;
    var targetRequestedSamples = 0;
    var fallbackReason = "";
    var allocationFailed = false;
    var allocationErrors = [];
    var recoveredAllocationErrors = 0;
    var allocationFailures = 0;
    var pendingGLErrors = [];
    var externalErrorCount = 0;
    var nativePixelRatio = 1;
    var effectivePixelRatio = 1;
    var dimensionLimited = false;
    var modelInfo = { triangles: 0, calls: 0, lines: 0, points: 0 };
    var size = new T.Vector2();

    function context() { return renderer.getContext(); }
    function isWebGL2() { return !!renderer.capabilities.isWebGL2; }
    function releaseTarget() {
      if (target) target.dispose();
      target = null;
      targetNeedsCheck = false;
      targetRequestedSamples = 0;
      ready = false;
    }
    function setEnabled(value) {
      value = !!value;
      if (value === enabled) return;
      enabled = value;
      allocationFailed = false;
      fallbackReason = "";
      releaseTarget();
    }
    function resize(width, height) {
      if (disposed || interrupted || !width || !height) return;
      cssWidth = Math.max(1, width);
      cssHeight = Math.max(1, height);
      var ratio = Number(window.devicePixelRatio) || 1;
      nativePixelRatio = isFinite(ratio) && ratio > 0 ? ratio : 1;
      var requested = enabled ? nativePixelRatio : Math.min(nativePixelRatio, 1.75);
      var gl = context();
      var viewport = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
      var maximum = Math.min(renderer.capabilities.maxTextureSize,
        gl.getParameter(gl.MAX_RENDERBUFFER_SIZE), viewport[0], viewport[1]);
      effectivePixelRatio = Math.min(requested, maximum / cssWidth, maximum / cssHeight);
      dimensionLimited = effectivePixelRatio < requested;
      renderer.setPixelRatio(effectivePixelRatio);
      renderer.setSize(cssWidth, cssHeight, false);
      contextSamples = gl.getParameter(gl.SAMPLES);
      renderer.getDrawingBufferSize(size);
      if (target && (target.width !== size.x || target.height !== size.y)) {
        target.setSize(size.x, size.y);
        targetNeedsCheck = true;
      }
      ready = false;
    }
    function createCopyPass() {
      if (copyScene) return;
      var geometry = new T.BufferGeometry();
      geometry.setAttribute("position", new T.Float32BufferAttribute([-1, -1, 3, -1, -1, 3], 2));
      geometry.setAttribute("uv", new T.Float32BufferAttribute([0, 0, 2, 0, 0, 2], 2));
      var material = new T.RawShaderMaterial({
        uniforms: { image: { value: null } },
        vertexShader: "precision highp float;attribute vec2 position;attribute vec2 uv;varying vec2 imageUV;void main(){imageUV=uv;gl_Position=vec4(position,0.0,1.0);}",
        fragmentShader: "precision highp float;uniform sampler2D image;varying vec2 imageUV;void main(){gl_FragColor=texture2D(image,imageUV);}",
        depthTest: false, depthWrite: false, blending: T.NoBlending, toneMapped: false
      });
      copyMesh = new T.Mesh(geometry, material);
      copyMesh.frustumCulled = false;
      copyScene = new T.Scene();
      copyScene.add(copyMesh);
      copyCamera = new T.Camera();
    }
    function canMultisample() {
      return isWebGL2() && !!T.WebGLMultisampleRenderTarget && renderer.capabilities.maxSamples >= 2;
    }
    function takeGLErrors() {
      var gl = context();
      var errors = [];
      // WebGL keeps a small set of error flags. Bound the read even if a
      // broken driver repeatedly reports the same error.
      for (var count = 0; count < 16; count += 1) {
        var error = gl.getError();
        if (error === gl.NO_ERROR) break;
        errors.push(error);
      }
      return errors;
    }
    function preserveExternalErrors() {
      takeGLErrors().forEach(function (error) {
        externalErrorCount += 1;
        if (pendingGLErrors.indexOf(error) < 0) pendingGLErrors.push(error);
      });
    }
    function recordAllocationErrors(errors) {
      errors.forEach(function (error) {
        // Context loss belongs to the renderer's interruption lifecycle, not
        // to a successfully recovered framebuffer allocation.
        if (error === 0x9242) {
          externalErrorCount += 1;
          if (pendingGLErrors.indexOf(error) < 0) pendingGLErrors.push(error);
        } else {
          recoveredAllocationErrors += 1;
          if (allocationErrors.indexOf(error) < 0) allocationErrors.push(error);
        }
      });
    }
    function readGLError() {
      if (pendingGLErrors.length) return pendingGLErrors.shift();
      var error = context().getError();
      if (error !== context().NO_ERROR) externalErrorCount += 1;
      return error;
    }
    function ensureTarget() {
      if (!target) {
        renderer.getDrawingBufferSize(size);
        target = new T.WebGLMultisampleRenderTarget(size.x, size.y, {
          minFilter: T.NearestFilter, magFilter: T.NearestFilter,
          generateMipmaps: false, depthBuffer: true, stencilBuffer: true
        });
        // Keep stronger default-framebuffer AA rather than lowering it merely
        // to reproduce the game's minimum. The device may round this up again.
        targetRequestedSamples = Math.min(renderer.capabilities.maxSamples, Math.max(2, contextSamples));
        target.samples = targetRequestedSamples;
        // Match direct rendering's output encoding. RGBA8 stores those display
        // bytes; the final raw copy deliberately applies no second conversion.
        target.texture.encoding = renderer.outputEncoding;
        createCopyPass();
        targetNeedsCheck = true;
      }
      if (!targetNeedsCheck) return true;
      var gl = context();
      // This boundary covers only our render-target setup, never model or
      // post-process rendering. Preserve any preexisting error for the normal
      // viewer probe before recording errors caused by this optional setup.
      preserveExternalErrors();
      var complete = false;
      try {
        renderer.setRenderTarget(target);
        complete = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
        if (complete) effectiveSamples = actualTargetSamples();
      } catch (error) {
        complete = false;
      }
      var ownedErrors = takeGLErrors();
      if (!complete || ownedErrors.length) {
        try { renderer.setRenderTarget(null); releaseTarget(); }
        finally { recordAllocationErrors(ownedErrors.concat(takeGLErrors())); }
        allocationFailures += 1;
        allocationFailed = true;
        fallbackReason = "multisample-framebuffer-unavailable";
        return false;
      }
      targetNeedsCheck = false;
      return true;
    }
    function actualTargetSamples() {
      var gl = context();
      var properties = renderer.properties.get(target);
      var color = properties.__webglColorRenderbuffer;
      if (!color) return 0;
      var previous = gl.getParameter(gl.RENDERBUFFER_BINDING);
      gl.bindRenderbuffer(gl.RENDERBUFFER, color);
      var samples = gl.getRenderbufferParameter(gl.RENDERBUFFER, gl.RENDERBUFFER_SAMPLES);
      gl.bindRenderbuffer(gl.RENDERBUFFER, previous);
      return samples;
    }
    function snapshotModelInfo() {
      var info = renderer.info.render;
      modelInfo = { triangles: info.triangles, calls: info.calls, lines: info.lines, points: info.points };
    }
    function render(scene, camera) {
      if (disposed || interrupted) return modelInfo;
      var multisample = enabled && !allocationFailed && canMultisample();
      if (multisample) {
        try { multisample = ensureTarget(); }
        catch (error) {
          renderer.setRenderTarget(null);
          releaseTarget();
          allocationFailed = true;
          allocationFailures += 1;
          fallbackReason = "multisample-framebuffer-unavailable";
          multisample = false;
        }
      }
      if (context().isContextLost()) { ready = false; return modelInfo; }
      if (multisample) {
        renderer.setRenderTarget(target);
        renderer.render(scene, camera);
        snapshotModelInfo();
        renderer.setRenderTarget(null);
        copyMesh.material.uniforms.image.value = target.texture;
        renderer.render(copyScene, copyCamera);
        fallbackReason = effectiveSamples === 2 ? "" : "sample-count-adjusted";
      } else {
        renderer.setRenderTarget(null);
        renderer.render(scene, camera);
        snapshotModelInfo();
        effectiveSamples = contextSamples;
        if (enabled && !fallbackReason) fallbackReason = isWebGL2() ? "multisampling-unavailable" : "webgl2-unavailable";
        if (!enabled) fallbackReason = "";
      }
      ready = true;
      return modelInfo;
    }
    function invalidateGPU() {
      interrupted = true;
      ready = false;
      // Three replaces its GPU-property cache on context restoration. Detach
      // the old target's disposal listener while its old handles still exist.
      releaseTarget();
      if (copyMesh) { copyMesh.geometry.dispose(); copyMesh.material.dispose(); }
    }
    function restoreGPU() {
      interrupted = false;
      allocationFailed = false;
      fallbackReason = "";
      pendingGLErrors = pendingGLErrors.filter(function (error) { return error !== 0x9242; });
      if (cssWidth && cssHeight) resize(cssWidth, cssHeight);
    }
    function getState() {
      renderer.getDrawingBufferSize(size);
      return { enabled: enabled, gameSamples: enabled ? 2 : 0,
        requestedSamples: targetRequestedSamples, targetRequestedSamples: targetRequestedSamples,
        effectiveSamples: effectiveSamples, actualSamples: effectiveSamples,
        contextSamples: contextSamples, webgl2: isWebGL2(), nativePixelRatio: nativePixelRatio,
        effectivePixelRatio: effectivePixelRatio, width: size.x, height: size.y,
        cssWidth: cssWidth, cssHeight: cssHeight, dimensionLimited: dimensionLimited,
        fallbackReason: fallbackReason, ready: ready && !interrupted && !disposed,
        allocationErrors: allocationErrors.slice(), recoveredAllocationErrors: recoveredAllocationErrors,
        allocationFailures: allocationFailures, pendingGLErrors: pendingGLErrors.slice(),
        externalErrorCount: externalErrorCount,
        targetAllocated: !!target, mode: !enabled ? "standard" : target ? "multisample" : effectiveSamples > 1 ? "context-aa" : "native-resolution" };
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      releaseTarget();
      if (copyMesh) { copyMesh.geometry.dispose(); copyMesh.material.dispose(); }
      copyScene = null;
      copyMesh = null;
      copyCamera = null;
    }
    return { setEnabled: setEnabled, resize: resize, render: render, getState: getState,
      invalidateGPU: invalidateGPU, restoreGPU: restoreGPU, readGLError: readGLError, dispose: dispose };
  }

  window.ViewerQuality = { create: create };
}());
