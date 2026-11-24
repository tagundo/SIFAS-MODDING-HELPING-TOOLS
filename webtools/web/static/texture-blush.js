/* Cheek blush bake: the AS/Member _CHEEK_ON multiplier baked into a head texture.
 *
 * Bit-for-bit twin of webtools/core/texture_blush.py (see its docstring for the
 * client and shader evidence). f = 1 + k * (cheek.rgb - 1), with cheek sampled
 * bilinearly (Clamp) from one 256x256 layer of the stock cheek_array at
 * uv * 2.22 + (0, -1.221), uv in Unity's v-up convention. Images here are
 * straight RGBA in top-left row order; cheek layers keep Unity row order (row
 * 0 is v = 0). Alpha and every texel whose rounded RGB does not change keep
 * their exact bytes. Both implementations use doubles in the same order and
 * round with floor(x + .5).
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TextureBlush = factory();
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";
  var SIZE = 256, LAYER_BYTES = SIZE * SIZE * 4;
  var UV_SCALE = Math.fround(2.22), UV_OFFSET_V = Math.fround(-1.22100008);
  // Keep identical to texture_blush.LEVELS (tests compare both tables).
  var LEVELS = [
    { id: "veryLight", k: 0.5, label: "Very light" },
    { id: "light", k: 1.05, label: "Light" },
    { id: "medium", k: 1.65, label: "Medium" },
    { id: "strong", k: 2.3, label: "Strong" },
    { id: "veryStrong", k: 3.0, label: "Very strong" }
  ];
  // The two layers differ in SHAPE, not strength (strength is only the level
  // or k): the labels name the shape and never use a strength word.
  var LAYERS = [{ id: 0, label: "Cheeks (Ppo)", hint: "Round patches on both cheeks" },
    { id: 1, label: "Cheeks and nose (Akarame)", hint: "Band across the nose and both cheeks" }];
  var MAX_K = 4;
  function checkedK(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || !(value > 0) || value > MAX_K) throw new Error("Choose a blush strength between 0 and " + MAX_K + ".");
    return value;
  }
  function checkedLayer(value) { if (value !== 0 && value !== 1) throw new Error("Choose the Ppo or Akarame blush type."); return value; }
  // How the baked texture is saved (texture_blush.ENCODINGS): "exact" (default)
  // is lossless RGBA32, every untouched texel keeps its value; "astc-keep"
  // keeps an ASTC texture's compression and re-encodes the touched blocks.
  var ENCODINGS = ["exact", "astc-keep"], DEFAULT_ENCODING = "exact";
  function checkedEncoding(value) { if (ENCODINGS.indexOf(value) < 0) throw new Error("Choose how to save the baked blush: exact pixels or the game's ASTC compression."); return value; }
  // A recipe operation {layer, k, encoding} (viewer_texture_tools.checked_blush):
  // the canonical form always names the encoding; a row without one is "exact".
  function checkedOperation(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("The blush bake takes only a blush type, a strength and a save mode.");
    var keys = Object.keys(value).sort().join(",");
    if (keys !== "k,layer" && keys !== "encoding,k,layer") throw new Error("The blush bake takes only a blush type, a strength and a save mode.");
    return { layer: checkedLayer(value.layer), k: checkedK(value.k), encoding: checkedEncoding(value.encoding === undefined ? DEFAULT_ENCODING : value.encoding) };
  }
  function encodingOf(value) { return value && value.encoding === "astc-keep" ? "astc-keep" : DEFAULT_ENCODING; }
  function sameOperation(a, b) { return !a && !b || !!a && !!b && a.layer === b.layer && a.k === b.k && encodingOf(a) === encodingOf(b); }
  function copyOperation(value) { return value ? { layer: value.layer, k: value.k, encoding: encodingOf(value) } : null; }
  function levelK(id) { for (var i = 0; i < LEVELS.length; i++) if (LEVELS[i].id === id) return LEVELS[i].k; throw new Error("Choose a supported blush level."); }
  function levelFor(k) { for (var i = 0; i < LEVELS.length; i++) if (LEVELS[i].k === k) return LEVELS[i].id; return null; }
  function layerBounds(layer) {
    if (!layer || layer.length !== LAYER_BYTES) throw new Error("The cheek layer has unexpected dimensions.");
    var x0 = SIZE, y0 = SIZE, x1 = -1, y1 = -1;
    for (var y = 0; y < SIZE; y++) for (var x = 0; x < SIZE; x++) {
      var o = (y * SIZE + x) * 4;
      if (layer[o] !== 255 || layer[o + 1] !== 255 || layer[o + 2] !== 255) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    return x1 < 0 ? null : [x0, y0, x1, y1];
  }
  // Lerp form: four identical texels (white) return that value exactly.
  function sample(layer, cu, cv) {
    var x = cu * SIZE - 0.5, y = cv * SIZE - 0.5, xf = Math.floor(x), yf = Math.floor(y), fx = x - xf, fy = y - yf, last = SIZE - 1;
    var x0 = Math.min(Math.max(xf, 0), last), x1 = Math.min(Math.max(xf + 1, 0), last), y0 = Math.min(Math.max(yf, 0), last), y1 = Math.min(Math.max(yf + 1, 0), last);
    var a = (y0 * SIZE + x0) * 4, b = (y0 * SIZE + x1) * 4, c = (y1 * SIZE + x0) * 4, d = (y1 * SIZE + x1) * 4, out = [0, 0, 0];
    for (var channel = 0; channel < 3; channel++) {
      var p = layer[a + channel] / 255, q = layer[b + channel] / 255, r = layer[c + channel] / 255, s = layer[d + channel] / 255;
      var bottom = p + (q - p) * fx, top = r + (s - r) * fx;
      out[channel] = bottom + (top - bottom) * fy;
    }
    return out;
  }
  function factor(cheek, k) { return [1 + k * (cheek[0] - 1), 1 + k * (cheek[1] - 1), 1 + k * (cheek[2] - 1)]; }
  function bakeValue(value, f) { return Math.min(255, Math.max(0, Math.floor(value * f + 0.5))); }
  function texelUv(x, y, width, height) { return [(x + 0.5) / width, 1 - (y + 0.5) / height]; }
  function span(low, high, size) { return [Math.max(0, Math.floor(low * size - 0.5) - 2), Math.min(size - 1, Math.ceil(high * size - 0.5) + 2)]; }
  function region(width, height, bounds) {
    if (!bounds) return null;
    var cuLow = (bounds[0] - 0.5) / SIZE, cuHigh = (bounds[2] + 1.5) / SIZE, cvLow = (bounds[1] - 0.5) / SIZE, cvHigh = (bounds[3] + 1.5) / SIZE;
    var uLow = cuLow / UV_SCALE, uHigh = cuHigh / UV_SCALE, vLow = (cvLow - UV_OFFSET_V) / UV_SCALE, vHigh = (cvHigh - UV_OFFSET_V) / UV_SCALE, last = SIZE - 1;
    // Clamp wrap repeats an edge texel beyond it; a non-white edge reaches the border.
    if (bounds[0] === 0) uLow = 0; if (bounds[2] === last) uHigh = 1; if (bounds[1] === 0) vLow = 0; if (bounds[3] === last) vHigh = 1;
    var xs = span(uLow, uHigh, width), ys = span(1 - vHigh, 1 - vLow, height);
    return xs[0] > xs[1] || ys[0] > ys[1] ? null : [xs[0], ys[0], xs[1], ys[1]];
  }
  // Returns { data: a new Uint8ClampedArray, changed, box: [x0, y0, x1, y1] | null }.
  function bakeRGBA(rgba, width, height, layer, k, bounds) {
    checkedK(k);
    if (!rgba || rgba.length !== width * height * 4 || !layer || layer.length !== LAYER_BYTES) throw new Error("The blush image or cheek layer has unexpected dimensions.");
    var out = new Uint8ClampedArray(rgba), area = region(width, height, bounds === undefined ? layerBounds(layer) : bounds), changed = 0, box = null;
    if (!area) return { data: out, changed: 0, box: null };
    for (var y = area[1]; y <= area[3]; y++) {
      var v = 1 - (y + 0.5) / height, cv = v * UV_SCALE + UV_OFFSET_V;
      for (var x = area[0]; x <= area[2]; x++) {
        var u = (x + 0.5) / width, f = factor(sample(layer, u * UV_SCALE, cv), k), offset = (y * width + x) * 4, touched = false;
        for (var channel = 0; channel < 3; channel++) {
          var before = out[offset + channel], after = bakeValue(before, f[channel]);
          if (after !== before) { out[offset + channel] = after; touched = true; }
        }
        if (touched) { changed++; box = box ? [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)] : [x, y, x, y]; }
      }
    }
    return { data: out, changed: changed, box: box };
  }
  function bakeImage(image, layer, k, bounds) {
    var result = bakeRGBA(image.data, image.width, image.height, layer, k, bounds);
    return { width: image.width, height: image.height, data: result.data, changed: result.changed, box: result.box };
  }
  // The texture texel at the darkest point of a layer (the cheek centre), and
  // its colour baked at each strength. Used for the level swatches.
  function centre(image, layer) {
    var best = null;
    for (var y = 0; y < SIZE; y++) for (var x = 0; x < SIZE; x++) {
      var o = (y * SIZE + x) * 4, value = layer[o + 1] + layer[o + 2];
      if (best === null || value < best.value) best = { value: value, x: x, y: y };
    }
    var u = (best.x + 0.5) / SIZE / UV_SCALE, v = ((best.y + 0.5) / SIZE - UV_OFFSET_V) / UV_SCALE;
    var px = Math.min(image.width - 1, Math.max(0, Math.floor(u * image.width))), py = Math.min(image.height - 1, Math.max(0, Math.floor((1 - v) * image.height)));
    return { x: px, y: py, texel: [best.x, best.y] };
  }
  function swatches(image, layer, ks) {
    var point = centre(image, layer), o = (point.y * image.width + point.x) * 4, base = [image.data[o], image.data[o + 1], image.data[o + 2]];
    var uv = texelUv(point.x, point.y, image.width, image.height), cheek = sample(layer, uv[0] * UV_SCALE, uv[1] * UV_SCALE + UV_OFFSET_V);
    return { point: point, base: base, colours: (ks || LEVELS.map(function (level) { return level.k; })).map(function (k) { var f = factor(cheek, k); return [bakeValue(base[0], f[0]), bakeValue(base[1], f[1]), bakeValue(base[2], f[2])]; }) };
  }
  function layerView(payload, index) {
    checkedLayer(index);
    if (!payload || payload.length !== LAYER_BYTES * 2) throw new Error("The cheek array payload has an unexpected size.");
    return payload.subarray(index * LAYER_BYTES, (index + 1) * LAYER_BYTES);
  }
  return { SIZE: SIZE, LAYER_BYTES: LAYER_BYTES, UV_SCALE: UV_SCALE, UV_OFFSET_V: UV_OFFSET_V, LEVELS: LEVELS, LAYERS: LAYERS, DEFAULT_LEVEL: "medium", DEFAULT_LAYER: 0, MAX_K: MAX_K,
    ENCODINGS: ENCODINGS.slice(), DEFAULT_ENCODING: DEFAULT_ENCODING,
    CHEEK_SHA256: "26de3c60f632112a8a9617cbaac04d390936a8da3849ddfd9e28fdc5b7a34b09",
    checkedK: checkedK, checkedLayer: checkedLayer, checkedEncoding: checkedEncoding, checkedOperation: checkedOperation, sameOperation: sameOperation, copyOperation: copyOperation, levelK: levelK, levelFor: levelFor, layerBounds: layerBounds, sample: sample, factor: factor, bakeValue: bakeValue,
    texelUv: texelUv, region: region, bakeRGBA: bakeRGBA, bakeImage: bakeImage, centre: centre, swatches: swatches, layerView: layerView };
});
