/* A classic worker: copied pixel buffers enter here; original/undo pixels stay
 * on the UI thread. Results transfer back without an extra full-image clone.
 */
"use strict";
importScripts("texture-color-math.js");
self.onmessage = function (event) {
  var request = event.data || {};
  try {
    var rgba = new Uint8ClampedArray(request.rgba), mask = request.mask ? new Uint8Array(request.mask) : null;
    var options = request.options || {}, result;
    if (request.kind === "adjust") result = TextureColorMath.adjustRGBA(rgba, request.width, request.height, mask, options);
    else if (request.kind === "skin") result = TextureColorMath.skinRGBA(rgba, request.width, request.height, mask, options);
    else if (request.kind === "grow") {
      if (mask) options.gate = mask;
      result = TextureColorMath.growMask(rgba, request.width, request.height, options.seeds || [], options);
    } else throw new Error("Unknown colour worker operation.");
    self.postMessage({ id: request.id, ok: true, rgba: result.buffer }, [result.buffer]);
  } catch (error) {
    self.postMessage({ id: request.id, ok: false, error: error && error.message || String(error) });
  }
};
