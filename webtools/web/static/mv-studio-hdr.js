(function (global) {
  "use strict";

  function create(T, renderer) {
    if (T.REVISION !== "128" || !renderer.capabilities.isWebGL2 || !renderer.properties?.get) return null;
    const gl = renderer.getContext();
    if (!gl.getExtension("EXT_color_buffer_float")) return null;
    const packedColor = new WeakSet();
    const textureOf = (target) => renderer.properties.get(target.texture).__webglTexture;

    function hasPackedAttachment(framebuffer) {
      if (gl.checkFramebufferStatus(framebuffer) !== gl.FRAMEBUFFER_COMPLETE) return false;
      const info = (key) => gl.getFramebufferAttachmentParameter(framebuffer, gl.COLOR_ATTACHMENT0, key);
      return info(gl.FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE) === gl.FLOAT &&
        info(gl.FRAMEBUFFER_ATTACHMENT_RED_SIZE) === 11 && info(gl.FRAMEBUFFER_ATTACHMENT_GREEN_SIZE) === 11 &&
        info(gl.FRAMEBUFFER_ATTACHMENT_BLUE_SIZE) === 10 && info(gl.FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE) === 0;
    }

    // Three r128 coerces RGB float render targets to RGBA. Keep ownership of all
    // handles with Three and replace the color storage before the first draw.
    // The caller disposes this target if either attachment cannot be made packed.
    function prepare(target) {
      const texture = textureOf(target);
      if (packedColor.has(texture)) return true;
      if (!texture || renderer.getRenderTarget() !== target || !gl.getExtension("EXT_color_buffer_float")) return false;
      const framebuffer = renderer.properties.get(target);
      const multisample = target.isWebGLMultisampleRenderTarget;
      const drawFramebuffer = multisample ? framebuffer.__webglMultisampledFramebuffer : framebuffer.__webglFramebuffer;
      if (!drawFramebuffer || !framebuffer.__webglFramebuffer ||
          gl.getParameter(gl.DRAW_FRAMEBUFFER_BINDING) !== drawFramebuffer) return false;

      const format = gl.R11F_G11F_B10F;
      const samples = multisample ? gl.getParameter(gl.SAMPLES) : 0;
      if (multisample && (!framebuffer.__webglColorRenderbuffer || !samples ||
          !gl.getInternalformatParameter(gl.RENDERBUFFER, format, gl.SAMPLES)?.includes(samples))) return false;

      const { width, height } = target;
      const previousTexture = gl.getParameter(gl.TEXTURE_BINDING_2D);
      try {
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, format, width, height, 0, gl.RGB, gl.UNSIGNED_INT_10F_11F_11F_REV, null);
      } finally {
        gl.bindTexture(gl.TEXTURE_2D, previousTexture);
      }

      if (multisample) {
        const previousColor = gl.getParameter(gl.RENDERBUFFER_BINDING);
        try {
          gl.bindRenderbuffer(gl.RENDERBUFFER, framebuffer.__webglColorRenderbuffer);
          gl.renderbufferStorageMultisample(gl.RENDERBUFFER, samples, format, width, height);
        } finally {
          gl.bindRenderbuffer(gl.RENDERBUFFER, previousColor);
        }
        const previousRead = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
        try {
          gl.bindFramebuffer(gl.READ_FRAMEBUFFER, framebuffer.__webglFramebuffer);
          if (!hasPackedAttachment(gl.READ_FRAMEBUFFER)) return false;
        } finally {
          gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previousRead);
        }
      }
      if (!hasPackedAttachment(gl.DRAW_FRAMEBUFFER)) return false;
      packedColor.add(texture);
      return true;
    }

    return { prepare, ready(target) { return packedColor.has(textureOf(target)); } };
  }

  global.MVStudioHDR = { create };
}(window));
