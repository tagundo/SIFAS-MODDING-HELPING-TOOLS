/* Pure RGBA recolouring. RGB helpers use byte RGB; OKLCH uses L0..1 and degrees.
 * Masks are Uint8 coverage0..255. Recolouring never changes alpha or pixels
 * outside the confirmed mask. Null mask means all pixels only for cloth edits.
 * Canvas/DOM, texture uploads, history and source-file writes live elsewhere.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.TextureColorMath = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  var MAX_PIXELS = 16777216, DEG = Math.PI / 180;
  var LINEAR = new Float64Array(256);
  for (var index = 0; index < 256; index++) {
    var component = index / 255;
    LINEAR[index] = component <= .04045 ? component / 12.92 : Math.pow((component + .055) / 1.055, 2.4);
  }
  var TONES = Object.freeze(["bright", "default", "slight", "medium_tone"]);
  var REFERENCE = Object.freeze({
    bright: Object.freeze([237.67, 210.14, 189.17]),
    default: Object.freeze([219.81, 190.67, 156.66]),
    slight: Object.freeze([222.59, 194.58, 177.84]),
    medium_tone: Object.freeze([212.24, 187.15, 161.47])
  });
  // Same calibrated reference maps as skin_tone_changer.py. "slight" is a
  // separately drawn reference, so conversions involving it remain approximate.
  var SKIN_MAPS = {
    "bright/default": [[1.19907, .93389, .91160], [-48.2111, 7.7997, 9.1088]],
    "bright/slight": [[1.08141, 1.05401, .95964], [-23.0708, -13.9049, 5.5764]],
    "bright/medium_tone": [[1.23472, .88606, .82263], [-58.7773, 13.0090, 20.2567]],
    "default/bright": [[.83398, 1.07079, 1.09697], [40.2073, -8.3518, -9.9921]],
    "default/slight": [[.90188, 1.12862, 1.05270], [20.4097, -22.7077, -4.0124]],
    "default/medium_tone": [[1.02973, .94878, .90240], [-9.1327, 5.6088, 12.0370]],
    "slight/bright": [[.92472, .94876, 1.04206], [21.3340, 13.1924, -5.8110]],
    "slight/default": [[1.10880, .88604, .94994], [-22.6303, 20.1200, 3.8115]],
    "slight/medium_tone": [[1.14177, .84065, .85723], [-32.4359, 24.6982, 15.4765]],
    "medium_tone/bright": [[.80990, 1.12860, 1.21561], [47.6039, -14.6819, -24.6244]],
    "medium_tone/default": [[.97113, 1.05399, 1.10816], [8.8690, -5.9116, -13.3388]],
    "medium_tone/slight": [[.87584, 1.18955, 1.16655], [28.4085, -29.3797, -18.0541]]
  };

  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function finite(value, fallback, label) {
    if (value === undefined && fallback !== undefined) return fallback;
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Invalid " + label + ".");
    return value;
  }
  function wrap(hue) { return ((hue % 360) + 360) % 360; }
  function linear(value) {
    value = clamp(value, 0, 255);
    if (Number.isInteger(value)) return LINEAR[value];
    value /= 255;
    return value <= .04045 ? value / 12.92 : Math.pow((value + .055) / 1.055, 2.4);
  }
  function encoded(value) {
    value = clamp(value, 0, 1);
    return 255 * (value <= .0031308 ? 12.92 * value : 1.055 * Math.pow(value, 1 / 2.4) - .055);
  }
  function rgbLab(r, g, b, out) {
    r = linear(r); g = linear(g); b = linear(b);
    var l = Math.cbrt(.4122214708 * r + .5363325363 * g + .0514459929 * b);
    var m = Math.cbrt(.2119034982 * r + .6806995451 * g + .1073969566 * b);
    var s = Math.cbrt(.0883024619 * r + .2817188376 * g + .6299787005 * b);
    out[0] = .2104542553 * l + .7936177850 * m - .0040720468 * s;
    out[1] = 1.9779984951 * l - 2.4285922050 * m + .4505937099 * s;
    out[2] = .0259040371 * l + .7827717662 * m - .8086757660 * s;
    return out;
  }
  function labLinear(L, a, b, out) {
    var l = L + .3963377774 * a + .2158037573 * b;
    var m = L - .1055613458 * a - .0638541728 * b;
    var s = L - .0894841775 * a - 1.2914855480 * b;
    l *= l * l; m *= m * m; s *= s * s;
    out[0] = 4.0767416621 * l - 3.3077115913 * m + .2309699292 * s;
    out[1] = -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s;
    out[2] = -.0041960863 * l - .7034186147 * m + 1.7076147010 * s;
    return out;
  }
  function inGamut(rgb) {
    return rgb[0] >= -1e-7 && rgb[0] <= 1.0000001 && rgb[1] >= -1e-7 && rgb[1] <= 1.0000001 && rgb[2] >= -1e-7 && rgb[2] <= 1.0000001;
  }
  function lchRgb(L, C, hue, out) {
    L = clamp(L, 0, 1); C = Math.max(0, C);
    if (L <= 0 || L >= 1) { out[0] = out[1] = out[2] = L <= 0 ? 0 : 255; return out; }
    var angle = wrap(hue) * DEG, ca = Math.cos(angle), cb = Math.sin(angle);
    labLinear(L, C * ca, C * cb, out);
    if (!inGamut(out)) {
      // Reduce only chroma. Per-channel clipping would shift hue/lightness.
      var low = 0, high = C;
      for (var step = 0; step < 16; step++) {
        var middle = (low + high) / 2;
        labLinear(L, middle * ca, middle * cb, out);
        if (inGamut(out)) low = middle; else high = middle;
      }
      labLinear(L, low * ca, low * cb, out);
    }
    out[0] = encoded(out[0]); out[1] = encoded(out[1]); out[2] = encoded(out[2]);
    return out;
  }
  function rgbArguments(value, g, b) {
    var values = typeof value === "number" ? [value, g, b] : value;
    if (!values || values.length < 3) throw new Error("Provide three RGB components.");
    return [finite(values[0], undefined, "red"), finite(values[1], undefined, "green"), finite(values[2], undefined, "blue")];
  }
  function rgbToOklab(value, g, b) {
    var rgb = rgbArguments(value, g, b);
    return rgbLab(rgb[0], rgb[1], rgb[2], [0, 0, 0]);
  }
  function rgbToOklch(value, g, b) {
    var lab = rgbToOklab(value, g, b), C = Math.hypot(lab[1], lab[2]);
    return [lab[0], C, C < 1e-7 ? 0 : wrap(Math.atan2(lab[2], lab[1]) / DEG)];
  }
  function oklchToRgb(value, chroma, hue) {
    var v = typeof value === "number" ? [value, chroma, hue] : value;
    if (!v || v.length < 3) throw new Error("Provide lightness, chroma and hue.");
    var out = lchRgb(finite(v[0], undefined, "lightness"), finite(v[1], undefined, "chroma"), finite(v[2], undefined, "hue"), [0, 0, 0]);
    return out.map(function (channel) { return Math.round(channel); });
  }
  function dimensions(rgba, width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > MAX_PIXELS) throw new Error("Unsupported texture dimensions.");
    if (!(rgba instanceof Uint8Array || rgba instanceof Uint8ClampedArray) || rgba.length !== width * height * 4) throw new Error("Invalid RGBA pixel data.");
    return width * height;
  }
  function checkMask(mask, count, required) {
    if (mask === null || mask === undefined) {
      if (required) throw new Error("Select and confirm the skin area first.");
      return null;
    }
    if (!(mask instanceof Uint8Array || mask instanceof Uint8ClampedArray) || mask.length !== count) throw new Error("Invalid selection mask.");
    if (required && !mask.some(function (value) { return value > 0; })) throw new Error("Select and confirm the skin area first.");
    return mask;
  }
  function parseColor(value) {
    if (typeof value === "string") {
      if (/^#[0-9a-f]{3}$/i.test(value)) value = "#" + value.slice(1).split("").map(function (c) { return c + c; }).join("");
      if (!/^#[0-9a-f]{6}$/i.test(value)) throw new Error("Choose an RGB colour.");
      return [parseInt(value.slice(1, 3), 16), parseInt(value.slice(3, 5), 16), parseInt(value.slice(5, 7), 16)];
    }
    return rgbArguments(value);
  }
  function settings(options) {
    options = options || {};
    var mode = options.mode || "relative";
    if (mode !== "relative" && mode !== "colorize") throw new Error("Unknown colour adjustment mode.");
    var result = { mode: mode, lightness: clamp(finite(options.lightness, 0, "lightness"), -1, 1),
      chroma: clamp(finite(options.chroma, 1, "chroma"), 0, 3), hue: wrap(finite(options.hue, 0, "hue")),
      strength: clamp(finite(options.strength, 1, "strength"), 0, 1), preserveLightness: options.preserveLightness !== false };
    if (mode === "colorize") result.target = rgbToOklch(parseColor(options.color));
    result.identity = mode === "relative" && result.lightness === 0 && result.chroma === 1 && result.hue === 0;
    return result;
  }
  function adjustedPixel(r, g, b, options, lab, out) {
    rgbLab(r, g, b, lab);
    var C = Math.hypot(lab[1], lab[2]), hue = C < 1e-7 ? 0 : Math.atan2(lab[2], lab[1]) / DEG;
    var L = lab[0];
    if (options.mode === "colorize") {
      C = options.target[1]; hue = options.target[2];
      if (!options.preserveLightness) L = options.target[0];
    }
    return lchRgb(L + options.lightness, C * options.chroma, hue + options.hue, out);
  }
  function blendPixel(input, output, offset, rgb, coverage) {
    for (var channel = 0; channel < 3; channel++) output[offset + channel] = Math.round(input[offset + channel] + (rgb[channel] - input[offset + channel]) * coverage);
  }
  function adjustRGBA(rgba, width, height, mask, options) {
    var count = dimensions(rgba, width, height); mask = checkMask(mask, count, false);
    var config = settings(options), output = new Uint8ClampedArray(rgba);
    if (config.identity || config.strength === 0) return output;
    var lab = new Float64Array(3), rgb = new Float64Array(3);
    for (var pixel = 0; pixel < count; pixel++) {
      var offset = pixel * 4, coverage = (mask ? mask[pixel] / 255 : 1) * config.strength;
      if (!coverage || rgba[offset + 3] === 0) continue;
      adjustedPixel(rgba[offset], rgba[offset + 1], rgba[offset + 2], config, lab, rgb);
      blendPixel(rgba, output, offset, rgb, coverage);
    }
    return output;
  }
  function analyzeToneFromMask(rgba, width, height, mask) {
    var count = dimensions(rgba, width, height); mask = checkMask(mask, count, true);
    var sum = [0, 0, 0], total = 0;
    for (var pixel = 0; pixel < count; pixel++) {
      var offset = pixel * 4, weight = mask[pixel] / 255 * rgba[offset + 3] / 255;
      if (!weight) continue;
      total += weight;
      for (var channel = 0; channel < 3; channel++) sum[channel] += rgba[offset + channel] * weight;
    }
    if (!total) throw new Error("The selected skin area contains no visible pixels.");
    var mean = sum.map(function (value) { return value / total; });
    var ranks = TONES.map(function (tone) {
      var reference = REFERENCE[tone];
      return { tone: tone, distance: Math.hypot(mean[0] - reference[0], mean[1] - reference[1], mean[2] - reference[2]) };
    }).sort(function (a, b) { return a.distance - b.distance; });
    return { tone: ranks[0].tone, meanRGB: mean, meanOKLCH: rgbToOklch(mean), weight: total,
      confidence: clamp((ranks[1].distance - ranks[0].distance) / Math.max(1, ranks[1].distance), 0, 1), distances: ranks };
  }
  function detectToneFromMask(rgba, width, height, mask) { return analyzeToneFromMask(rgba, width, height, mask).tone; }
  function skinRGBA(rgba, width, height, mask, options) {
    var count = dimensions(rgba, width, height); mask = checkMask(mask, count, true); options = options || {};
    var source = options.source || "auto", target = options.target;
    if (source !== "auto" && TONES.indexOf(source) < 0 || TONES.indexOf(target) < 0) throw new Error("Choose supported source and target skin tones.");
    var strength = clamp(finite(options.strength, 1, "strength"), 0, 1), output = new Uint8ClampedArray(rgba);
    if (!strength) return output;
    if (source === "auto") source = detectToneFromMask(rgba, width, height, mask);
    var map = source === target ? null : SKIN_MAPS[source + "/" + target], fine = settings(options.fine);
    if (fine.mode !== "relative") throw new Error("Skin fine adjustment uses relative OKLCH values.");
    if (!map && fine.identity) return output;
    var rgb = new Float64Array(3), tuned = new Float64Array(3), lab = new Float64Array(3);
    for (var pixel = 0; pixel < count; pixel++) {
      var offset = pixel * 4, coverage = mask[pixel] / 255 * strength;
      if (!coverage || rgba[offset + 3] === 0) continue;
      for (var channel = 0; channel < 3; channel++) rgb[channel] = map ? clamp(rgba[offset + channel] * map[0][channel] + map[1][channel], 0, 255) : rgba[offset + channel];
      if (!fine.identity && fine.strength) {
        adjustedPixel(rgb[0], rgb[1], rgb[2], fine, lab, tuned);
        for (channel = 0; channel < 3; channel++) rgb[channel] += (tuned[channel] - rgb[channel]) * fine.strength;
      }
      blendPixel(rgba, output, offset, rgb, coverage);
    }
    return output;
  }
  function seedIndex(seed, width, height) {
    if (Number.isInteger(seed)) {
      if (seed < 0 || seed >= width * height) throw new Error("A selection seed is outside the image.");
      return seed;
    }
    var x = Array.isArray(seed) ? seed[0] : seed && seed.x;
    var y = Array.isArray(seed) ? seed[1] : seed && seed.y;
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= width || y >= height) throw new Error("A selection seed is outside the image.");
    return y * width + x;
  }
  function growMask(rgba, width, height, seeds, options) {
    var count = dimensions(rgba, width, height); options = options || {};
    var gate = checkMask(options.gate, count, false), output = new Uint8Array(count);
    if (!Array.isArray(seeds) || !seeds.length) return output;
    var tolerance = clamp(finite(options.tolerance, .08, "colour tolerance"), 0, 1), limit = tolerance * tolerance;
    var positive = [], negative = [], indices = [], excluded = new Set();
    function collect(values, target, positiveSeeds) {
      values.forEach(function (seed) {
        var i = seedIndex(seed, width, height), offset = i * 4;
        if (!positiveSeeds) excluded.add(i);
        if (!rgba[offset + 3] || gate && !gate[i]) return;
        target.push(rgbLab(rgba[offset], rgba[offset + 1], rgba[offset + 2], [0, 0, 0]));
        if (positiveSeeds) indices.push(i);
      });
    }
    collect(seeds, positive, true);
    if (options.excludeSeeds !== undefined && !Array.isArray(options.excludeSeeds)) throw new Error("Invalid excluded colour seeds.");
    collect(options.excludeSeeds || [], negative, false);
    if (!positive.length) return output;
    var lab = new Float64Array(3);
    function distance(prototypes) {
      var best = Infinity;
      for (var i = 0; i < prototypes.length; i++) {
        var sample = prototypes[i], dl = lab[0] - sample[0], da = lab[1] - sample[1], db = lab[2] - sample[2];
        best = Math.min(best, dl * dl + da * da + db * db);
      }
      return best;
    }
    function accepted(i) {
      var offset = i * 4;
      if (gate && !gate[i] || !rgba[offset + 3] || excluded.has(i)) return false;
      rgbLab(rgba[offset], rgba[offset + 1], rgba[offset + 2], lab);
      var best = distance(positive);
      return best <= limit + 1e-14 && (!negative.length || distance(negative) > best + 1e-14);
    }
    if (options.connected === false) {
      for (var i = 0; i < count; i++) if (accepted(i)) output[i] = gate ? gate[i] : 255;
      return output;
    }
    var visited = new Uint8Array(count), queue = new Uint32Array(count), head = 0, tail = 0;
    function visit(i) {
      if (visited[i]) return;
      visited[i] = 1;
      if (!accepted(i)) return;
      output[i] = gate ? gate[i] : 255; queue[tail++] = i;
    }
    indices.forEach(visit);
    while (head < tail) {
      var pixel = queue[head++], x = pixel % width, y = Math.floor(pixel / width);
      if (x) visit(pixel - 1);
      if (x + 1 < width) visit(pixel + 1);
      if (y) visit(pixel - width);
      if (y + 1 < height) visit(pixel + width);
      if (options.connectivity === 8) {
        if (x && y) visit(pixel - width - 1);
        if (x + 1 < width && y) visit(pixel - width + 1);
        if (x && y + 1 < height) visit(pixel + width - 1);
        if (x + 1 < width && y + 1 < height) visit(pixel + width + 1);
      }
    }
    return output;
  }
  function featherMask(mask, width, height, radius, gate) {
    var count = width * height;
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || count > MAX_PIXELS) throw new Error("Unsupported texture dimensions.");
    mask = checkMask(mask, count, true); gate = checkMask(gate, count, false);
    radius = clamp(Math.round(finite(radius, 0, "feather radius")), 0, 128);
    var output = new Uint8Array(mask), distance = new Uint16Array(count), max = radius + 1;
    for (var i = 0; i < count; i++) {
      if (gate) output[i] = Math.min(output[i], gate[i]);
      distance[i] = output[i] ? max : 0;
    }
    if (!radius) return output;
    // Inward-only Manhattan distance: the result's support is a strict subset
    // of the confirmed selection. It never dilates into costume neighbours.
    for (var y = 0; y < height; y++) for (var x = 0; x < width; x++) {
      var at = y * width + x;
      if (distance[at]) distance[at] = Math.min(distance[at], x ? distance[at - 1] + 1 : 1, y ? distance[at - width] + 1 : 1);
    }
    for (y = height - 1; y >= 0; y--) for (x = width - 1; x >= 0; x--) {
      at = y * width + x;
      if (distance[at]) distance[at] = Math.min(distance[at], x + 1 < width ? distance[at + 1] + 1 : 1, y + 1 < height ? distance[at + width] + 1 : 1);
      output[at] = Math.round(output[at] * Math.min(1, distance[at] / max));
    }
    return output;
  }
  function abortError(message) {
    var error = new Error(message || "Colour preview was superseded.");
    error.name = "AbortError";
    return error;
  }
  function createProcessor(options) {
    options = options || {};
    var worker = null, disposed = false, failure = null, running = null, queued = null, serial = 0;
    if (typeof Worker === "function") {
      try { worker = new Worker(options.workerUrl || "/static/texture-color-worker.js"); }
      catch (error) { failure = error; }
    }
    function execute(request) {
      if (request.kind === "adjust") return adjustRGBA(request.rgba, request.width, request.height, request.mask, request.options);
      if (request.kind === "skin") return skinRGBA(request.rgba, request.width, request.height, request.mask, request.options);
      var growOptions = Object.assign({}, request.options);
      if (request.mask) growOptions.gate = request.mask;
      return growMask(request.rgba, request.width, request.height, growOptions.seeds || [], growOptions);
    }
    function finish(error, result) {
      if (!running) return;
      var completed = running; running = null;
      if (error) completed.reject(error); else completed.resolve(result);
      if (!disposed && queued) { var next = queued; queued = null; start(next); }
    }
    function start(request) {
      running = request;
      if (!worker) {
        // Only runtimes without Web Workers use the synchronous algorithm.
        // A microtask still gives identical Promise/error/cancellation semantics.
        Promise.resolve().then(function () { return execute(request); }).then(function (result) {
          if (running === request) finish(null, result);
        }, function (error) { if (running === request) finish(error); });
        return;
      }
      var transfers = [request.rgba.buffer];
      if (request.mask) transfers.push(request.mask.buffer);
      if (request.options.gate) transfers.push(request.options.gate.buffer);
      try {
        worker.postMessage({ id: request.id, kind: request.kind, width: request.width, height: request.height,
          rgba: request.rgba.buffer, mask: request.mask ? request.mask.buffer : null, options: request.options }, transfers);
      } catch (error) { finish(error); }
    }
    if (worker) {
      worker.onmessage = function (event) {
        if (disposed || !running) return;
        var message = event.data || {};
        if (message.id !== running.id) { finish(new Error("Unexpected colour worker result.")); return; }
        if (message.ok !== true) { finish(new Error(message.error || "Colour worker failed.")); return; }
        if (!(message.rgba instanceof ArrayBuffer)) { finish(new Error("Invalid colour worker result.")); return; }
        var length = running.width * running.height * (running.kind === "grow" ? 1 : 4);
        if (message.rgba.byteLength !== length) { finish(new Error("Invalid colour worker pixel count.")); return; }
        finish(null, running.kind === "grow" ? new Uint8Array(message.rgba) : new Uint8ClampedArray(message.rgba));
      };
      worker.onerror = function (event) {
        if (disposed) return;
        failure = new Error(event && event.message || "The colour worker could not be loaded.");
        var pending = queued; queued = null;
        finish(failure);
        if (pending) pending.reject(failure);
        if (worker) worker.terminate(); worker = null;
      };
    }
    function process(kind, rgba, width, height, mask, config) {
      return new Promise(function (resolve, reject) {
        if (disposed) { reject(abortError("The colour editor was closed.")); return; }
        if (failure) { reject(failure); return; }
        try {
          if (kind !== "adjust" && kind !== "skin" && kind !== "grow") throw new Error("Unknown colour worker operation.");
          var count = dimensions(rgba, width, height); mask = checkMask(mask, count, kind === "skin");
          // Keep only one pending snapshot, and release a superseded snapshot
          // before copying the next. Transfer only these copies, never buffers
          // owned by the texture editor or undo history.
          if (queued) { queued.reject(abortError()); queued = null; }
          var copied = Object.assign({}, config || {});
          if (copied.fine) copied.fine = Object.assign({}, copied.fine);
          if (copied.seeds) copied.seeds = copied.seeds.map(function (seed) { return Array.isArray(seed) ? seed.slice() : typeof seed === "object" ? Object.assign({}, seed) : seed; });
          if (copied.excludeSeeds) copied.excludeSeeds = copied.excludeSeeds.map(function (seed) { return Array.isArray(seed) ? seed.slice() : typeof seed === "object" ? Object.assign({}, seed) : seed; });
          if (kind === "grow" && mask) delete copied.gate;
          else if (copied.gate) { checkMask(copied.gate, count, false); copied.gate = new Uint8Array(copied.gate); }
          var request = { id: ++serial, kind: kind, rgba: new Uint8ClampedArray(rgba), width: width, height: height,
            mask: mask ? new Uint8Array(mask) : null, options: copied, resolve: resolve, reject: reject };
          if (running) queued = request; else start(request);
        } catch (error) { reject(error); }
      });
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      var error = abortError("The colour editor was closed."), pending = queued; queued = null;
      if (running) { running.reject(error); running = null; }
      if (pending) pending.reject(error);
      if (worker) { worker.terminate(); worker = null; }
    }
    return { process: process, dispose: dispose,
      getState: function () { return { busy: !!running, queued: !!queued, disposed: disposed, worker: !!worker, error: failure && failure.message || "" }; } };
  }
  return Object.freeze({ rgbToOklab: rgbToOklab, rgbToOklch: rgbToOklch, oklchToRgb: oklchToRgb,
    adjustRGBA: adjustRGBA, skinRGBA: skinRGBA, detectToneFromMask: detectToneFromMask,
    analyzeToneFromMask: analyzeToneFromMask, growMask: growMask, featherMask: featherMask,
    createProcessor: createProcessor,
    tones: TONES, referenceSkinMean: REFERENCE, approximateTones: Object.freeze(["slight"]) });
});
