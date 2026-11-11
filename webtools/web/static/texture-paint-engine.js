/* Pixel editing and masks for the model texture tools. No source files are changed.
 *
 * TexturePaintEngine.create({canvas?, onChange?, onSelectionChange?, onPick?,
 *   onViewChange?, onError?, drawOverlay?, maxHistoryBytes?, maxHistoryEntries?})
 * accepts top-left, straight-alpha RGBA image coordinates. setImage/getImage and
 * applyImageData use {width,height,data:Uint8ClampedArray}. getImage() copies;
 * getImage(false) is a read-only live view. getMask() copies coverage bytes, or
 * returns null for an unrestricted image. clearSelection removes a restriction;
 * selectNone deliberately selects no pixels. Selection does not change pixels.
 *
 * setTool: brush, eraser, picker, fill, line, rectangle, ellipse, select-brush,
 * select-rectangle, select-ellipse, select-lasso, select-wand, pan.
 * setBrush: size (image-pixel diameter), opacity/softness (0..1), RGBA color,
 * tolerance (0..255), contiguous (fill/wand), fill (shapes). Selection modes are
 * replace/add/subtract/intersect. A whole stroke is one bounded tile undo entry.
 * setPreviewImage is nonpersistent: use it for color-slider previews, then
 * applyImageData to commit once. onChange fires on commit, never pointer frames.
 * setSelectionVisible only hides mask display. setReadOnly locks pointer and
 * keyboard edits while retaining pan/zoom/picker; hosts guard their toolbar
 * actions, while programmatic image/mask restoration remains available.
 *
 * Layers are bottom-to-top. getImage is the committed flattened composite;
 * getActiveImage is the active layer. applyImageData and setPreviewImage edit
 * or preview that layer, while replaceImageData atomically replaces the stack.
 * getProject/restoreProject use version-1 raw layers[].image RGBA snapshots;
 * the host encodes each layer as PNG for portable project files. Metadata and
 * unique retained image owners are undoable. Pixel history defaults to 64 MiB;
 * structural changes and combined pixel/mask moves can use up to 128 MiB.
 *
 * copySelection/cutSelection use a bounded in-app clipboard shared by engines.
 * pasteClipboard/startMoveSelection create pending floating pixels: getImage
 * remains committed, getDisplayImage previews movement. Enter commits one undo
 * operation, Escape cancels exactly. Float coordinates are image-pixel origins.
 */
(function (global) {
  "use strict";
  var TILE = 64, MAX_PIXELS = 16777216, MAX_LAYER_PIXELS = 33554432, MAX_LAYERS = 8, clipboard = null, layerSerial = 0;
  var TOOLS = ["brush", "eraser", "picker", "fill", "line", "rectangle", "ellipse", "select-brush", "select-rectangle", "select-ellipse", "select-lasso", "select-wand", "select-uv-face", "select-uv-island", "move", "pan"];
  function clamp(value, low, high) { return Math.min(high, Math.max(low, value)); }
  function finite(value, fallback) { return typeof value === "number" && Number.isFinite(value) ? value : fallback; }
  function color(value) {
    if (typeof value === "string" && /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value)) {
      return [parseInt(value.slice(1, 3), 16), parseInt(value.slice(3, 5), 16), parseInt(value.slice(5, 7), 16), value.length === 9 ? parseInt(value.slice(7, 9), 16) : 255];
    }
    if (!value || value.length < 3) throw new Error("Choose an RGB or RGBA brush color.");
    return [0, 1, 2, 3].map(function (index) { return Math.round(clamp(finite(value[index], index === 3 ? 255 : 0), 0, 255)); });
  }
  function image(value, expected) {
    if (!value || !Number.isInteger(value.width) || !Number.isInteger(value.height) || value.width < 1 || value.height < 1 || value.width * value.height > MAX_PIXELS || !value.data || value.data.length !== value.width * value.height * 4) throw new Error("The texture must be a bounded RGBA image.");
    if (expected && (value.width !== expected.width || value.height !== expected.height)) throw new Error("Texture editing must preserve the original image dimensions.");
    return { width: value.width, height: value.height, data: new Uint8ClampedArray(value.data) };
  }
  function mask(value, length) {
    if (value === null) return null;
    if (!value || value.length !== length) throw new Error("The selection mask must match the texture dimensions.");
    return new Uint8Array(value);
  }
  function point(value) {
    if (!value || !Number.isFinite(value.x) || !Number.isFinite(value.y) || Math.abs(value.x) > 1000000000 || Math.abs(value.y) > 1000000000) throw new Error("Choose a finite image position within the supported range.");
    return { x: value.x, y: value.y };
  }
  function mergeRect(left, right) {
    if (!right) return left;
    if (!left) return { x: right.x, y: right.y, width: right.width, height: right.height };
    var x = Math.min(left.x, right.x), y = Math.min(left.y, right.y);
    return { x: x, y: y, width: Math.max(left.x + left.width, right.x + right.width) - x, height: Math.max(left.y + left.height, right.y + right.height) - y };
  }
  function blendPixel(data, offset, rgba, coverage, erase) {
    var amount = clamp(finite(coverage, 0), 0, 1), oldAlpha = data[offset + 3], alpha = oldAlpha / 255;
    if (!amount) return false;
    if (erase) {
      var nextAlpha = Math.round(oldAlpha * (1 - amount));
      if (nextAlpha === oldAlpha) return false;
      data[offset + 3] = nextAlpha; // retain hidden RGB to avoid introducing black fringes
      return true;
    }
    amount *= rgba[3] / 255;
    if (!amount) return false;
    var outAlpha = amount + alpha * (1 - amount), changed = false;
    for (var channel = 0; channel < 3; channel++) {
      var next = Math.round((rgba[channel] * amount + data[offset + channel] * alpha * (1 - amount)) / outAlpha);
      if (data[offset + channel] !== next) { data[offset + channel] = next; changed = true; }
    }
    var nextA = Math.round(outAlpha * 255);
    if (oldAlpha !== nextA) { data[offset + 3] = nextA; changed = true; }
    return changed;
  }
  function distance(data, offset, reference) {
    if (!data[offset + 3] && !reference[3]) return 0;
    var dr = data[offset] - reference[0], dg = data[offset + 1] - reference[1], db = data[offset + 2] - reference[2];
    return Math.max(Math.sqrt((dr * dr + dg * dg + db * db) / 3), Math.abs(data[offset + 3] - reference[3]));
  }
  function connectedRegion(value, x, y, tolerance, gate, contiguous) {
    var width = value.width, height = value.height, data = value.data, length = width * height, result = new Uint8Array(length);
    if (gate && gate.length !== length) throw new Error("The selection mask must match the texture dimensions.");
    if (!Number.isFinite(x) || !Number.isFinite(y)) return result;
    x = Math.floor(x); y = Math.floor(y); tolerance = clamp(finite(tolerance, 0), 0, 255);
    if (x < 0 || y < 0 || x >= width || y >= height || gate && !gate[y * width + x]) return result;
    var start = y * width + x, reference = Array.from(data.subarray(start * 4, start * 4 + 4));
    function accepts(index) { return (!gate || gate[index] > 0) && distance(data, index * 4, reference) <= tolerance; }
    if (contiguous === false) { for (var i = 0; i < length; i++) if (accepts(i)) result[i] = 255; return result; }
    var seen = new Uint8Array(length), queue = new Uint32Array(length), head = 0, tail = 0;
    seen[start] = 1; queue[tail++] = start;
    function add(index) { if (!seen[index]) { seen[index] = 1; if (accepts(index)) queue[tail++] = index; } }
    while (head < tail) {
      var index = queue[head++]; result[index] = 255;
      if (index % width) add(index - 1);
      if (index % width !== width - 1) add(index + 1);
      if (index >= width) add(index - width);
      if (index + width < length) add(index + width);
    }
    return result;
  }
  function shapeMask(width, height, kind, points, options) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > MAX_PIXELS || !Array.isArray(points)) throw new Error("Choose bounded shape dimensions and positions.");
    if (["rectangle", "ellipse", "line", "lasso"].indexOf(kind) < 0) throw new Error("Choose a supported shape.");
    options = options || {}; points = points.map(point);
    var result = new Uint8Array(width * height);
    if (!points.length) return result;
    var a = points[0], b = points[points.length - 1], radius = Math.max(.5, finite(options.size, 1) / 2);
    var minX = Math.min.apply(null, points.map(function (p) { return p.x; })), maxX = Math.max.apply(null, points.map(function (p) { return p.x; }));
    var minY = Math.min.apply(null, points.map(function (p) { return p.y; })), maxY = Math.max.apply(null, points.map(function (p) { return p.y; }));
    var filled = options.fill !== false, margin = filled && kind !== "line" ? 0 : radius;
    var left = clamp(Math.floor(minX - margin), 0, width - 1), right = clamp(Math.ceil(maxX + margin), 0, width - 1);
    var top = clamp(Math.floor(minY - margin), 0, height - 1), bottom = clamp(Math.ceil(maxY + margin), 0, height - 1);
    var cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, rx = Math.max(.5, (maxX - minX) / 2), ry = Math.max(.5, (maxY - minY) / 2);
    // Scan polygon edges once per row, instead of once per texture pixel.
    if (kind === "lasso") {
      for (var row = top; row <= bottom; row++) {
        var scan = row + .5, crossings = [];
        for (var edge = 0, previous = points.length - 1; edge < points.length; previous = edge++) if ((points[edge].y > scan) !== (points[previous].y > scan)) crossings.push((points[previous].x - points[edge].x) * (scan - points[edge].y) / (points[previous].y - points[edge].y) + points[edge].x);
        crossings.sort(function (left, right) { return left - right; });
        for (var crossing = 0; crossing + 1 < crossings.length; crossing += 2) {
          var from = clamp(Math.ceil(crossings[crossing] - .5), 0, width), to = clamp(Math.ceil(crossings[crossing + 1] - .5), 0, width);
          if (to > from) result.fill(255, row * width + from, row * width + to);
        }
      }
      return result;
    }
    for (var y = top; y <= bottom; y++) for (var x = left; x <= right; x++) {
      var px = x + .5, py = y + .5, inside = false;
      if (kind === "rectangle") {
        inside = px >= minX && px <= maxX && py >= minY && py <= maxY;
        if (!filled) inside = Math.abs(px - minX) <= radius && py >= minY - radius && py <= maxY + radius || Math.abs(px - maxX) <= radius && py >= minY - radius && py <= maxY + radius || Math.abs(py - minY) <= radius && px >= minX - radius && px <= maxX + radius || Math.abs(py - maxY) <= radius && px >= minX - radius && px <= maxX + radius;
      } else if (kind === "ellipse") {
        var outer = Math.pow((px - cx) / rx, 2) + Math.pow((py - cy) / ry, 2);
        inside = outer <= 1;
        if (!filled) { var innerX = Math.max(0, rx - radius * 2), innerY = Math.max(0, ry - radius * 2); inside = outer <= 1 && (!innerX || !innerY || Math.pow((px - cx) / innerX, 2) + Math.pow((py - cy) / innerY, 2) >= 1); }
      } else if (kind === "line") {
        var dx = b.x - a.x, dy = b.y - a.y, length = dx * dx + dy * dy;
        var t = length ? clamp(((px - a.x) * dx + (py - a.y) * dy) / length, 0, 1) : 0;
        inside = Math.hypot(px - a.x - t * dx, py - a.y - t * dy) <= radius;
      }
      if (inside) result[y * width + x] = 255;
    }
    return result;
  }

  function create(options) {
    options = options || {};
    var canvas = options.canvas || null, context = canvas && canvas.getContext("2d"), doc = null, selected = null, preview = null, selectionVisible = true, readOnly = false;
    var layers = [], activeLayerId = null, projectRevision = 0, composite = null, displayComposite = null, displayOverride = null, floating = null, compositeDirty = null, displayDirty = null, compositeOwned = false, displayOwned = false;
    var selectedBounds = null, boundaryPath = null, antsTimer = null, previewCanvasDirty = null, previewCanvasImage = null;
    if (canvas && !context) throw new Error("The texture editor requires Canvas2D support.");
    var tool = "brush", selectionMode = "replace", brush = { size: 20, opacity: 1, softness: 0, color: [255, 0, 0, 255], tolerance: 24, contiguous: true, fill: false };
    var history = [], future = [], historyBytes = 0, revision = 0, selectionRevision = 0, selectedPixels = 0, transaction = null;
    var maxBytes = Math.max(1024, finite(options.maxHistoryBytes, 64 * 1024 * 1024)), maxEntries = Math.max(1, Math.floor(finite(options.maxHistoryEntries, 40)));
    var view = { zoom: 1, x: 0, y: 0 }, pendingImage = null, pendingMask = null, frame = null, disposed = false, hover = null, stroke = null, space = false, pointers = new Map(), pinch = null;
    var imageCanvas = canvas && canvas.ownerDocument.createElement("canvas"), maskCanvas = canvas && canvas.ownerDocument.createElement("canvas"), previewCanvas = canvas && canvas.ownerDocument.createElement("canvas");
    var imageContext = imageCanvas && imageCanvas.getContext("2d"), maskContext = maskCanvas && maskCanvas.getContext("2d"), previewContext = previewCanvas && previewCanvas.getContext("2d"), maskPixels = null;
    var events = [], resizeObserver = null, pixelScratch = new Uint8ClampedArray(4);
    function requireImage() { if (!doc) throw new Error("Open a texture before editing."); }
    function dimensions() { return doc ? { x: 0, y: 0, width: doc.width, height: doc.height } : null; }
    function layerRows() { return layers.map(function (layer) { return { id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, width: layer.image.width, height: layer.image.height }; }); }
    function layerBytes() { return layers.reduce(function (sum, layer) { return sum + layer.image.data.byteLength; }, 0); }
    function getState() { return { width: doc ? doc.width : 0, height: doc ? doc.height : 0, revision: revision, projectRevision: projectRevision, selectionRevision: selectionRevision, activeLayer: activeLayerId, activeLayerId: activeLayerId, layers: layerRows(), layerBytes: layerBytes(), clipboardAvailable: !!clipboard, floatingSelection: floating ? { x: floating.x, y: floating.y, width: floating.image.width, height: floating.image.height, cut: floating.cut, layerId: floating.layerId } : null, selectionActive: selected !== null, selectionVisible: selectionVisible, readOnly: readOnly, selectedPixels: selectedPixels, undoCount: history.length, redoCount: future.length, historyBytes: historyBytes, preview: !!preview, tool: tool, brush: Object.assign({}, brush, { color: brush.color.slice() }), view: Object.assign({}, view) }; }
    function invalidate(rect) { compositeDirty = mergeRect(compositeDirty, rect || dimensions()); displayDirty = mergeRect(displayDirty, rect || dimensions()); previewCanvasDirty = mergeRect(previewCanvasDirty, rect || dimensions()); }
    function layerChanged(preserveComposite) { projectRevision++; if (!preserveComposite) invalidate(); else { displayDirty = dimensions(); previewCanvasDirty = dimensions(); } if (options.onLayerChange) options.onLayerChange({ layers: layerRows(), state: getState() }); }
    function floatingChanged(rect) { displayDirty = mergeRect(displayDirty, rect || dimensions()); previewCanvasDirty = mergeRect(previewCanvasDirty, rect || dimensions()); redraw(); if (options.onFloatingChange) options.onFloatingChange({ state: getState() }); }
    function notify(pixels, selection, dirty) {
      if (pixels) invalidate(dirty);
      if (pixels) { revision++; if (options.onChange) options.onChange({ revision: revision, dirty: dirty || dimensions(), state: getState() }); }
      if (selection) { selectionRevision++; if (options.onSelectionChange) options.onSelectionChange({ revision: selectionRevision, state: getState() }); }
      if (options.onHistoryChange) options.onHistoryChange(getState());
    }
    function redraw(rect, selectionRect) {
      if (rect) invalidate(rect);
      pendingImage = mergeRect(pendingImage, rect); pendingMask = mergeRect(pendingMask, selectionRect);
      if (!canvas || disposed || frame !== null) return;
      var draw = function () { frame = null; render(); };
      frame = global.requestAnimationFrame ? global.requestAnimationFrame(draw) : global.setTimeout(draw, 16);
    }
    function countSelection() {
      selectedPixels = 0; selectedBounds = null; boundaryPath = null; if (!selected) return;
      var left = doc.width, top = doc.height, right = -1, bottom = -1;
      for (var i = 0; i < selected.length; i++) if (selected[i]) { selectedPixels++; var x = i % doc.width, y = Math.floor(i / doc.width); left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y); }
      if (right >= left) selectedBounds = { x: left, y: top, width: right - left + 1, height: bottom - top + 1 };
    }
    function activeLayer() { return layers.filter(function (layer) { return layer.id === activeLayerId; })[0]; }
    function findLayer(id) { var layer = layers.filter(function (value) { return value.id === (id || activeLayerId); })[0]; if (!layer) throw new Error("Choose an existing texture layer."); return layer; }
    function requireEditable() { requireImage(); if (floating) throw new Error("Apply or cancel the floating selection first."); var layer = activeLayer(); if (!layer.visible || layer.opacity === 0) throw new Error("Show the active layer before editing it."); }
    function compositeImage(display) {
      if (!doc) return null;
      if (display && displayOverride) return displayOverride;
      if (display && !preview && !floating) return compositeImage(false);
      var visible = layers.filter(function (layer) { return layer.visible && layer.opacity > 0; });
      var sources = visible.map(function (layer) { return display && layer.id === activeLayerId ? floating ? floatingImage() : preview || layer.image : layer.image; });
      if (visible.length === 1 && visible[0].opacity === 1) {
        if (display) { displayComposite = sources[0]; displayOwned = false; displayDirty = null; }
        else { composite = sources[0]; compositeOwned = false; compositeDirty = null; }
        return sources[0];
      }
      var result = display ? displayComposite : composite, owned = display ? displayOwned : compositeOwned, dirty = display ? displayDirty : compositeDirty;
      if (!result || !owned || result.width !== doc.width || result.height !== doc.height) { result = { width: doc.width, height: doc.height, data: new Uint8ClampedArray(doc.data.length) }; dirty = dimensions(); }
      if (dirty) {
        for (var y = dirty.y; y < dirty.y + dirty.height; y++) for (var x = dirty.x; x < dirty.x + dirty.width; x++) {
          var offset = (y * doc.width + x) * 4, red = 0, green = 0, blue = 0, alphaByte = 0;
          for (var layerIndex = 0; layerIndex < visible.length; layerIndex++) {
            var source = sources[layerIndex].data, opacity = visible[layerIndex].opacity;
            if (!layerIndex) { red = source[offset]; green = source[offset + 1]; blue = source[offset + 2]; alphaByte = Math.round(source[offset + 3] * opacity); continue; }
            var alpha = source[offset + 3] / 255 * opacity; if (!alpha) continue;
            var old = alphaByte / 255, combined = alpha + old * (1 - alpha);
            red = Math.round((source[offset] * alpha + red * old * (1 - alpha)) / combined);
            green = Math.round((source[offset + 1] * alpha + green * old * (1 - alpha)) / combined);
            blue = Math.round((source[offset + 2] * alpha + blue * old * (1 - alpha)) / combined);
            alphaByte = Math.round(combined * 255);
          }
          result.data[offset] = red; result.data[offset + 1] = green; result.data[offset + 2] = blue; result.data[offset + 3] = alphaByte;
        }
      }
      if (display) { displayComposite = result; displayOwned = true; displayDirty = null; }
      else { composite = result; compositeOwned = true; compositeDirty = null; }
      return result;
    }
    function nextLayerId() { var id; do { id = "layer_" + (++layerSerial).toString(36); } while (layers.some(function (layer) { return layer.id === id; })); return id; }
    function checkedName(value) { if (typeof value !== "string" || !value.trim() || /[\u0000-\u001f\u007f]/.test(value) || Array.from(value).length > 128) throw new Error("Use a layer name of 1 to 128 characters."); return value.trim(); }
    function snapshot(copy) { return { format: "elichika-texture-project", version: 1, width: doc.width, height: doc.height, activeLayer: activeLayerId, layers: layers.map(function (layer) { return { id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, image: copy ? image(layer.image) : layer.image }; }) }; }
    function assignProject(value) {
      layers = value.layers.map(function (layer) { return Object.assign({}, layer); }); activeLayerId = value.activeLayer; doc = findLayer(activeLayerId).image; preview = null; displayOverride = null; invalidate();
    }
    function retainedBytes() {
      var current = new Set(layers.map(function (layer) { return layer.image.data; })), retained = new Set(), total = 0;
      history.concat(future).forEach(function (record) { total += record.bytes || 0; if (record.project) record.project.layers.forEach(function (layer) { var bytes = layer.image.data; if (!current.has(bytes) && !retained.has(bytes)) { retained.add(bytes); total += bytes.byteLength; } }); }); return total;
    }
    function trimHistory() {
      historyBytes = retainedBytes();
      var limit = history.concat(future).some(function (record) { return !!record.project || record.allowLarge; }) ? Math.min(128 * 1024 * 1024, maxBytes * 2) : maxBytes;
      while (history.length + future.length > maxEntries || historyBytes > limit) {
        if (history.length > 1 || history.length && !future.length) history.shift(); else if (future.length) future.shift(); else break;
        historyBytes = retainedBytes();
      }
    }
    function changeLayers(label, callback, config) {
      requireImage(); if (floating) throw new Error("Apply or cancel the floating selection first."); if (transaction) rollback();
      var before = snapshot(false), oldHistory = history.slice(), oldFuture = future.slice(); callback();
      if (layers.length > MAX_LAYERS || layerBytes() > MAX_LAYER_PIXELS * 4) { assignProject(before); throw new Error("Texture layers exceed the 8-layer or 128 MiB image limit."); }
      preview = null; displayOverride = null;
      if (config && config.history === false) { history = []; future = []; }
      else {
        future = []; history.push({ label: label, project: before, image: [], mask: [], bytes: 0, dirty: dimensions() });
        // A single operation must remain undoable; never silently discard it.
        if (retainedBytes() > Math.min(128 * 1024 * 1024, maxBytes * 2) && before.layers.reduce(function (sum, layer) { return sum + (layers.some(function (next) { return next.image.data === layer.image.data; }) ? 0 : layer.image.data.byteLength); }, 0) > Math.min(128 * 1024 * 1024, maxBytes * 2)) {
          assignProject(before); history = oldHistory; future = oldFuture; historyBytes = retainedBytes(); throw new Error("This layer operation exceeds the texture undo memory limit.");
        }
      }
      trimHistory(); layerChanged(); redraw(dimensions(), dimensions()); notify(true, false, dimensions()); return activeLayerId;
    }
    function checkedProject(value) {
      if (!value || value.format !== "elichika-texture-project" || value.version !== 1 || !Array.isArray(value.layers) || !value.layers.length || value.layers.length > MAX_LAYERS) throw new Error("Invalid texture layer project.");
      var width = Number(value.width), height = Number(value.height), ids = new Set();
      if (doc && (width !== doc.width || height !== doc.height)) throw new Error("Texture dimensions must match the original.");
      if (width * height * value.layers.length > MAX_LAYER_PIXELS) throw new Error("Texture layers exceed the 128 MiB image limit.");
      var checked = value.layers.map(function (layer) {
        if (!layer || typeof layer.id !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(layer.id) || ids.has(layer.id) || typeof layer.visible !== "boolean" || typeof layer.opacity !== "number" || !Number.isFinite(layer.opacity) || layer.opacity < 0 || layer.opacity > 1) throw new Error("Invalid texture layer project.");
        ids.add(layer.id); var pixels = image(layer.image); if (pixels.width !== width || pixels.height !== height) throw new Error("Layer dimensions must match the texture.");
        return { id: layer.id, name: checkedName(layer.name), visible: layer.visible, opacity: layer.opacity, image: pixels };
      });
      if (!ids.has(value.activeLayer)) throw new Error("Choose an existing texture layer."); return { format: value.format, version: 1, width: width, height: height, activeLayer: value.activeLayer, layers: checked };
    }
    function copyTile(key, channel) {
      var columns = Math.ceil(doc.width / TILE), tx = key % columns * TILE, ty = Math.floor(key / columns) * TILE;
      var width = Math.min(TILE, doc.width - tx), height = Math.min(TILE, doc.height - ty), stride = channel === "image" ? 4 : 1;
      var src = channel === "image" ? doc.data : selected, bytes = new Uint8Array(width * height * stride);
      if (src) for (var y = 0; y < height; y++) bytes.set(src.subarray(((ty + y) * doc.width + tx) * stride, ((ty + y) * doc.width + tx + width) * stride), y * width * stride);
      return { key: key, x: tx, y: ty, width: width, height: height, bytes: bytes };
    }
    function writeTile(tile, channel) {
      var stride = channel === "image" ? 4 : 1, target = channel === "image" ? doc.data : selected;
      if (!target) return;
      for (var y = 0; y < tile.height; y++) target.set(tile.bytes.subarray(y * tile.width * stride, (y + 1) * tile.width * stride), ((tile.y + y) * doc.width + tile.x) * stride);
    }
    function begin(label, limit) { requireImage(); if (transaction) throw new Error("Finish the current texture edit first."); preview = null; redraw(); transaction = { label: label, image: new Map(), mask: new Map(), activeBefore: selected !== null, dirty: null, maskDirty: null, bytes: 0, limit: limit || maxBytes }; }
    function touch(index, channel) {
      var x = index % doc.width, y = Math.floor(index / doc.width), key = Math.floor(y / TILE) * Math.ceil(doc.width / TILE) + Math.floor(x / TILE), tiles = transaction[channel];
      if (!tiles.has(key)) {
        var tile = copyTile(key, channel); tiles.set(key, tile); transaction.bytes += tile.bytes.byteLength;
        if (transaction.bytes > transaction.limit) throw new Error("This edit exceeds the texture undo history limit. Use a smaller selection.");
      }
      var rect = { x: x, y: y, width: 1, height: 1 };
      if (channel === "image") transaction.dirty = mergeRect(transaction.dirty, rect); else transaction.maskDirty = mergeRect(transaction.maskDirty, rect);
    }
    function rollback() {
      if (!transaction) return;
      transaction.image.forEach(function (tile) { writeTile(tile, "image"); });
      if (transaction.mask.size && !selected) selected = new Uint8Array(doc.width * doc.height);
      transaction.mask.forEach(function (tile) { writeTile(tile, "mask"); });
      if (!transaction.activeBefore) selected = null;
      var maskChanged = transaction.mask.size || transaction.activeBefore !== (selected !== null); transaction = null; if (maskChanged) countSelection(); redraw(dimensions(), dimensions());
    }
    function commit() {
      if (!transaction) return false;
      var record = { label: transaction.label, layerId: activeLayerId, allowLarge: transaction.limit > maxBytes, activeBefore: transaction.activeBefore, activeAfter: selected !== null, image: [], mask: [], dirty: transaction.dirty, maskDirty: transaction.maskDirty, bytes: 0 };
      ["image", "mask"].forEach(function (channel) {
        transaction[channel].forEach(function (before) {
          var after = copyTile(before.key, channel), differs = before.bytes.some(function (v, i) { return v !== after.bytes[i]; });
          // Keep the opposite state once. Undo and redo exchange each retained
          // tile with the document, so a full 4K edit fits a 64 MiB history.
          if (differs) { record[channel].push(before); record.bytes += before.bytes.byteLength; }
        });
      });
      transaction = null;
      if (!record.image.length && !record.mask.length && record.activeBefore === record.activeAfter) return false;
      future = []; history.push(record); trimHistory();
      preview = null; if (record.mask.length || record.activeBefore !== record.activeAfter) countSelection(); redraw(record.dirty, record.maskDirty || (record.activeBefore !== record.activeAfter ? dimensions() : null));
      notify(!!record.image.length, !!record.mask.length || record.activeBefore !== record.activeAfter, record.dirty);
      return true;
    }
    function perform(label, fn, limit) { begin(label, limit); try { fn(); return commit(); } catch (error) { rollback(); throw error; } }
    function setMaskRaw(next) {
      var length = doc.width * doc.height;
      if (next === null) { if (selected) for (var i = 0; i < length; i++) if (selected[i]) { touch(i, "mask"); selected[i] = 0; } selected = null; return; }
      if (!selected) selected = new Uint8Array(length);
      for (var j = 0; j < length; j++) if (selected[j] !== next[j]) { touch(j, "mask"); selected[j] = next[j]; }
    }
    function setMask(value, config) {
      requireImage(); var next = mask(value, doc.width * doc.height);
      if (config && config.history === false) { if (transaction) throw new Error("Finish the current texture edit first."); selected = next; countSelection(); redraw(null, dimensions()); notify(false, true); return true; }
      return perform("Selection", function () { setMaskRaw(next); });
    }
    function selectRegion(value, mode) {
      requireImage(); mode = mode || selectionMode; var next = mask(value, doc.width * doc.height);
      if (next === null || ["replace", "add", "subtract", "intersect"].indexOf(mode) < 0) throw new Error("Choose a supported selection mode.");
      return perform("Selection", function () { mergeMask(next, mode); });
    }
    function mergeMask(next, mode) {
      var old = selected, initial = mode === "subtract" || mode === "intersect" ? 255 : 0;
      if (!old) { selected = new Uint8Array(next.length); if (initial) selected.fill(initial); }
      for (var i = 0; i < next.length; i++) {
        var before = old ? old[i] : initial, value = mode === "replace" ? next[i] : mode === "add" ? Math.max(before, next[i]) : mode === "subtract" ? Math.round(before * (1 - next[i] / 255)) : Math.min(before, next[i]);
        if (selected[i] !== value) { touch(i, "mask"); selected[i] = value; }
      }
    }
    function brushConfig(overrides) { var cfg = Object.assign({}, brush, overrides || {}); cfg.color = color(cfg.color); cfg.size = clamp(finite(cfg.size, 20), .5, 4096); cfg.opacity = clamp(finite(cfg.opacity, 1), 0, 1); cfg.softness = clamp(finite(cfg.softness, 0), 0, 1); return cfg; }
    function put(index, rgba, amount, erase) {
      amount *= selected ? selected[index] / 255 : 1;
      if (!amount) return;
      var offset = index * 4;
      pixelScratch[0] = doc.data[offset]; pixelScratch[1] = doc.data[offset + 1]; pixelScratch[2] = doc.data[offset + 2]; pixelScratch[3] = doc.data[offset + 3];
      if (!blendPixel(pixelScratch, 0, rgba, amount, erase)) return;
      touch(index, "image");
      doc.data[offset] = pixelScratch[0]; doc.data[offset + 1] = pixelScratch[1]; doc.data[offset + 2] = pixelScratch[2]; doc.data[offset + 3] = pixelScratch[3];
    }
    function dab(p, cfg, selecting, erase, selectionLimit) {
      var radius = cfg.size / 2, left = Math.max(0, Math.floor(p.x - radius - .5)), right = Math.min(doc.width - 1, Math.ceil(p.x + radius + .5));
      var top = Math.max(0, Math.floor(p.y - radius - .5)), bottom = Math.min(doc.height - 1, Math.ceil(p.y + radius + .5)), hard = 1 - cfg.softness;
      for (var y = top; y <= bottom; y++) for (var x = left; x <= right; x++) {
        var normalized = Math.hypot(x + .5 - p.x, y + .5 - p.y) / radius;
        var coverage = cfg.softness ? normalized <= hard ? 1 : clamp((1 - normalized) / Math.max(.001, 1 - hard), 0, 1) : clamp(radius + .5 - Math.hypot(x + .5 - p.x, y + .5 - p.y), 0, 1);
        coverage *= cfg.opacity; if (!coverage) continue;
        var index = y * doc.width + x;
        if (selecting) {
          var old = selected[index], next = erase ? Math.round(old * (1 - coverage)) : Math.round(old + (255 - old) * coverage);
          if (selectionLimit) next = Math.min(next, selectionLimit[index]);
          if (next !== old) { touch(index, "mask"); selected[index] = next; }
        } else put(index, cfg.color, coverage, erase);
      }
    }
    function segment(a, b, cfg, selecting, erase, first, selectionLimit) {
      // A fast pointer can leave the viewport. Clip off-image travel before
      // generating dabs so panning/zoom never creates billions of empty stamps.
      var ax = a.x, ay = a.y, dx = b.x - ax, dy = b.y - ay, lower = 0, upper = 1, pad = cfg.size / 2 + 1;
      var tests = [[-dx, ax + pad], [dx, doc.width + pad - ax], [-dy, ay + pad], [dy, doc.height + pad - ay]];
      for (var test = 0; test < tests.length; test++) {
        var denominator = tests[test][0], numerator = tests[test][1];
        if (!denominator) { if (numerator < 0) return; continue; }
        var limit = numerator / denominator;
        if (denominator < 0) lower = Math.max(lower, limit); else upper = Math.min(upper, limit);
        if (lower > upper) return;
      }
      if (lower > 0 || upper < 1) { a = { x: ax + dx * lower, y: ay + dy * lower }; b = { x: ax + dx * upper, y: ay + dy * upper }; if (lower > 0) first = true; }
      var length = Math.hypot(b.x - a.x, b.y - a.y), steps = Math.ceil(length / Math.max(.5, cfg.size * .12));
      if (first) dab(a, cfg, selecting, erase, selectionLimit);
      for (var i = 1; i <= steps; i++) dab({ x: a.x + (b.x - a.x) * i / steps, y: a.y + (b.y - a.y) * i / steps }, cfg, selecting, erase, selectionLimit);
    }
    function paintStroke(points, overrides) {
      requireEditable();
      points = points.map(point); if (!points.length) return false;
      var cfg = brushConfig(overrides), erase = overrides && Object.prototype.hasOwnProperty.call(overrides, "erase") ? overrides.erase : tool === "eraser";
      return perform(erase ? "Erase" : "Brush", function () { segment(points[0], points[0], cfg, false, erase, true); for (var i = 1; i < points.length; i++) segment(points[i - 1], points[i], cfg, false, erase, false); });
    }
    function fillAt(x, y) {
      requireEditable(); var region = connectedRegion(doc, x, y, brush.tolerance, selected, brush.contiguous);
      return perform("Fill", function () { for (var i = 0; i < region.length; i++) if (region[i]) put(i, brush.color, brush.opacity, false); });
    }
    function drawShape(kind, start, end, overrides) {
      requireEditable();
      var cfg = brushConfig(overrides), region = shapeMask(doc.width, doc.height, kind, [start, end], cfg);
      return perform(kind, function () { for (var i = 0; i < region.length; i++) if (region[i]) put(i, cfg.color, cfg.opacity, false); });
    }
    function applyImageData(value, config) {
      requireEditable(); var next = image(value, doc);
      return perform(config && config.label || "Image edit", function () {
        for (var ty = 0; ty < doc.height; ty += TILE) for (var tx = 0; tx < doc.width; tx += TILE) {
          var right = Math.min(doc.width, tx + TILE), bottom = Math.min(doc.height, ty + TILE), different = false;
          for (var y = ty; y < bottom && !different; y++) for (var offset = (y * doc.width + tx) * 4; offset < (y * doc.width + right) * 4; offset++) if (doc.data[offset] !== next.data[offset]) { different = true; break; }
          if (!different) continue;
          touch(ty * doc.width + tx, "image");
          transaction.dirty = mergeRect(transaction.dirty, { x: tx, y: ty, width: right - tx, height: bottom - ty });
          for (var row = ty; row < bottom; row++) { var start = (row * doc.width + tx) * 4, end = (row * doc.width + right) * 4; doc.data.set(next.data.subarray(start, end), start); }
        }
        if (config && Object.prototype.hasOwnProperty.call(config, "selection")) setMaskRaw(config.selection);
      }, config && Object.prototype.hasOwnProperty.call(config, "selection") ? Math.min(128 * 1024 * 1024, maxBytes + doc.width * doc.height) : maxBytes);
    }
    function travel(from, to, useAfter) {
      if (floating) { cancelFloating(); return true; }
      if (transaction) rollback(); if (!from.length) return false;
      var record = from.pop(); // moving between undo and redo does not free its retained tiles
      if (record.project) {
        var oppositeProject = snapshot(false); assignProject(record.project); record.project = oppositeProject; to.push(record); trimHistory(); layerChanged(); redraw(dimensions(), dimensions()); notify(true, false, dimensions()); return true;
      }
      var currentDoc = doc, sourceLayer = findLayer(record.layerId); doc = sourceLayer.image;
      var activeTarget = useAfter ? record.activeAfter : record.activeBefore;
      if (!selected && record.mask.length) selected = new Uint8Array(doc.width * doc.height);
      ["image", "mask"].forEach(function (channel) { record[channel] = record[channel].map(function (tile) { var opposite = copyTile(tile.key, channel); writeTile(tile, channel); return opposite; }); });
      selected = activeTarget ? selected || new Uint8Array(doc.width * doc.height) : null;
      doc = currentDoc; to.push(record); trimHistory(); preview = null; if (record.mask.length || record.activeBefore !== record.activeAfter) countSelection(); redraw(record.dirty, dimensions()); notify(!!record.image.length, !!record.mask.length || record.activeBefore !== record.activeAfter, record.dirty); return true;
    }
    function setImage(value) {
      if (transaction) rollback(); if (floating) cancelFloating(); doc = image(value); layers = [{ id: nextLayerId(), name: "Background", visible: true, opacity: 1, image: doc }]; activeLayerId = layers[0].id; composite = null; displayComposite = null; compositeOwned = displayOwned = false; compositeDirty = displayDirty = previewCanvasDirty = null; previewCanvasImage = null; pendingImage = pendingMask = null; invalidate(); displayOverride = null; selected = null; selectedBounds = null; boundaryPath = null; preview = null; history = []; future = []; historyBytes = 0; revision = 0; projectRevision = 0; selectionRevision = 0; selectedPixels = 0;
      if (canvas) [imageCanvas, maskCanvas, previewCanvas].forEach(function (target) { target.width = doc.width; target.height = doc.height; });
      maskPixels = null; pendingImage = dimensions(); pendingMask = dimensions(); fit(); redraw(dimensions(), dimensions()); if (options.onHistoryChange) options.onHistoryChange(getState());
    }
    function setPreviewImage(value) {
      requireImage(); preview = value === null ? null : image(value, doc);
      displayDirty = dimensions(); previewCanvasDirty = dimensions();
      redraw();
    }
    function selectLayer(id) {
      if (floating) throw new Error("Apply or cancel the floating selection first."); if (transaction) rollback();
      var layer = findLayer(id); if (layer.id === activeLayerId) return layer.id;
      activeLayerId = layer.id; doc = layer.image; preview = null; displayOverride = null; layerChanged(true); redraw(); return layer.id;
    }
    function addLayer(value) {
      requireImage(); value = value || {};
      if (layers.length >= MAX_LAYERS || (layers.length + 1) * doc.width * doc.height > MAX_LAYER_PIXELS) throw new Error("Texture layers exceed the 8-layer or 128 MiB image limit.");
      var pixels = value.image ? image(value.image, doc) : { width: doc.width, height: doc.height, data: new Uint8ClampedArray(doc.data.length) }, name = checkedName(value.name || "Layer " + (layers.length + 1));
      return changeLayers("Add layer", function () { var index = layers.findIndex(function (layer) { return layer.id === activeLayerId; }); var layer = { id: nextLayerId(), name: name, visible: true, opacity: 1, image: pixels }; layers.splice(index + 1, 0, layer); activeLayerId = layer.id; doc = layer.image; });
    }
    function duplicateLayer(id) {
      var source = findLayer(id); if (layers.length >= MAX_LAYERS || (layers.length + 1) * doc.width * doc.height > MAX_LAYER_PIXELS) throw new Error("Texture layers exceed the 8-layer or 128 MiB image limit.");
      var pixels = image(source.image);
      return changeLayers("Duplicate layer", function () { var duplicate = { id: nextLayerId(), name: Array.from(source.name + " copy").slice(0, 128).join(""), visible: source.visible, opacity: source.opacity, image: pixels }; layers.splice(layers.indexOf(source) + 1, 0, duplicate); activeLayerId = duplicate.id; doc = duplicate.image; });
    }
    function renameLayer(id, name) { var layer = findLayer(id); name = checkedName(name); if (layer.name === name) return false; return changeLayers("Rename layer", function () { layer.name = name; }); }
    function removeLayer(id) {
      var layer = findLayer(id); if (layers.length < 2) throw new Error("Keep at least one texture layer.");
      return changeLayers("Remove layer", function () { var index = layers.indexOf(layer); layers.splice(index, 1); if (activeLayerId === layer.id) activeLayerId = layers[Math.min(index, layers.length - 1)].id; doc = findLayer(activeLayerId).image; });
    }
    function moveLayer(id, index) { var layer = findLayer(id); index = Math.floor(Number(index)); if (!Number.isFinite(index) || index < 0 || index >= layers.length) throw new Error("Choose a valid layer position."); if (layers.indexOf(layer) === index) return false; return changeLayers("Reorder layer", function () { layers.splice(layers.indexOf(layer), 1); layers.splice(index, 0, layer); }); }
    function setLayerVisible(id, value) { var layer = findLayer(id); if (typeof value !== "boolean") throw new Error("Choose layer visibility."); if (layer.visible === value) return false; return changeLayers("Layer visibility", function () { layer.visible = value; }); }
    function setLayerOpacity(id, value) { var layer = findLayer(id); if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) throw new Error("Layer opacity must be between 0 and 1."); if (layer.opacity === value) return false; return changeLayers("Layer opacity", function () { layer.opacity = value; }); }
    function mergeLayerDown(id) {
      var top = findLayer(id), index = layers.indexOf(top); if (index < 1) throw new Error("Choose a layer above another layer."); var bottom = layers[index - 1], pixels = { width: doc.width, height: doc.height, data: new Uint8ClampedArray(doc.data.length) };
      // Composite only this pair, baking their individual visibility/opacity.
      var saved = layers, savedActive = activeLayerId, savedDoc = doc, savedComposite = composite, savedOwned = compositeOwned, savedDirty = compositeDirty; layers = [bottom, top]; composite = null; pixels = image(compositeImage(false)); layers = saved; activeLayerId = savedActive; doc = savedDoc; composite = savedComposite; compositeOwned = savedOwned; compositeDirty = savedDirty;
      return changeLayers("Merge layer down", function () { var merged = { id: bottom.id, name: bottom.name, visible: true, opacity: 1, image: pixels }; layers.splice(index - 1, 2, merged); activeLayerId = merged.id; doc = merged.image; });
    }
    function restoreProject(value, config) {
      var checked = checkedProject(value);
      if (!doc) { setImage(checked.layers[0].image); assignProject(checked); history = []; future = []; historyBytes = 0; layerChanged(); redraw(dimensions(), dimensions()); return activeLayerId; }
      return changeLayers("Open texture project", function () { assignProject(checked); }, config);
    }
    function replaceImageData(value, config) {
      requireImage(); var pixels = image(value, doc), id = nextLayerId();
      return changeLayers(config && config.label || "Replace texture", function () { layers = [{ id: id, name: "Background", visible: true, opacity: 1, image: pixels }]; activeLayerId = id; doc = pixels; }, config);
    }
    function selectionBounds() {
      if (!doc) return null;
      if (!selected) return { x: 0, y: 0, width: doc.width, height: doc.height };
      return transaction && transaction.maskDirty ? mergeRect(selectedBounds, transaction.maskDirty) : selectedBounds;
    }
    function captureSelection() {
      var bounds = selectionBounds(); if (!bounds) return null;
      var pixels = { width: bounds.width, height: bounds.height, data: new Uint8ClampedArray(bounds.width * bounds.height * 4) }, coverage = new Uint8Array(bounds.width * bounds.height);
      for (var y = 0; y < bounds.height; y++) for (var x = 0; x < bounds.width; x++) { var source = ((bounds.y + y) * doc.width + bounds.x + x), dest = (y * bounds.width + x) * 4; coverage[y * bounds.width + x] = selected ? selected[source] : 255; pixels.data.set(doc.data.subarray(source * 4, source * 4 + 4), dest); if (selected) pixels.data[dest + 3] = Math.round(pixels.data[dest + 3] * selected[source] / 255); }
      return { version: 1, x: bounds.x, y: bounds.y, image: pixels, mask: coverage };
    }
    function copySelection() { requireImage(); var captured = captureSelection(); if (!captured) return false; clipboard = captured; if (options.onClipboardChange) options.onClipboardChange({ state: getState() }); return true; }
    function clearSelected() { for (var p = 0; p < doc.width * doc.height; p++) if (!selected || selected[p]) put(p, [0, 0, 0, 255], 1, true); }
    function cutSelection() { requireEditable(); if (!copySelection()) return false; return perform("Cut selection", clearSelected); }
    function importClipboard(value) { if (!value || value.version !== 1 || !Number.isInteger(value.x) || !Number.isInteger(value.y) || Math.abs(value.x) > 1000000 || Math.abs(value.y) > 1000000) throw new Error("Invalid texture clipboard."); var pixels = image(value.image), coverage = value.mask ? mask(value.mask, pixels.width * pixels.height) : null; clipboard = { version: 1, x: value.x, y: value.y, image: pixels, mask: coverage }; if (options.onClipboardChange) options.onClipboardChange({ state: getState() }); return true; }
    function startFloating(value, cut) {
      requireEditable(); if (transaction) rollback(); preview = null; displayOverride = null;
      floating = { layerId: activeLayerId, image: image(value.image), coverage: value.mask && new Uint8Array(value.mask), x: value.x, y: value.y, originX: value.x, originY: value.y, cut: cut, sourceMask: selected && new Uint8Array(selected), cached: null };
      floatingChanged(); return true;
    }
    function pasteClipboard(value) { requireEditable(); if (!clipboard) return false; value = value || {}; return startFloating({ image: clipboard.image, mask: clipboard.mask, x: Number.isFinite(value.x) ? Math.round(value.x) : clipboard.x, y: Number.isFinite(value.y) ? Math.round(value.y) : clipboard.y }, false); }
    function startMoveSelection() { requireEditable(); var captured = captureSelection(); return captured ? startFloating(captured, true) : false; }
    function floatRect(x, y, width, height) { var left = Math.max(0, x), top = Math.max(0, y), right = Math.min(doc.width, x + width), bottom = Math.min(doc.height, y + height); return right > left && bottom > top ? { x: left, y: top, width: right - left, height: bottom - top } : null; }
    function moveFloating(x, y) {
      if (!floating) return false; if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1000000 || Math.abs(y) > 1000000) throw new Error("Choose a valid selection position.");
      var dirty = floatRect(floating.x, floating.y, floating.image.width, floating.image.height); floating.x = Math.round(x); floating.y = Math.round(y); floating.needsUpdate = true;
      dirty = mergeRect(dirty, floatRect(floating.x, floating.y, floating.image.width, floating.image.height)); if (floating.cut) dirty = mergeRect(dirty, floatRect(floating.originX, floating.originY, floating.image.width, floating.image.height)); floatingChanged(dirty); return true;
    }
    function floatingImage() {
      if (!floating) return doc; if (floating.cached && !floating.needsUpdate) return floating.cached;
      if (floating.cut && floating.x === floating.originX && floating.y === floating.originY) return doc;
      var float = floating, result = float.cached, dirty = floatRect(float.x, float.y, float.image.width, float.image.height);
      if (float.cut) dirty = mergeRect(dirty, floatRect(float.originX, float.originY, float.image.width, float.image.height));
      if (result) { dirty = mergeRect(dirty, floatRect(float.cachedX, float.cachedY, float.image.width, float.image.height)); if (dirty) for (var row = dirty.y; row < dirty.y + dirty.height; row++) { var start = (row * doc.width + dirty.x) * 4; result.data.set(doc.data.subarray(start, start + dirty.width * 4), start); } }
      else result = image(doc);
      if (float.cut) for (var sy = float.originY; sy < float.originY + float.image.height; sy++) for (var sx = float.originX; sx < float.originX + float.image.width; sx++) { var pixel = sy * doc.width + sx, strength = float.sourceMask ? float.sourceMask[pixel] / 255 : 1; if (strength) result.data[pixel * 4 + 3] = Math.round(doc.data[pixel * 4 + 3] * (1 - strength)); }
      for (var y = Math.max(0, -float.y); y < Math.min(float.image.height, doc.height - float.y); y++) for (var x = Math.max(0, -float.x); x < Math.min(float.image.width, doc.width - float.x); x++) {
        var source = (y * float.image.width + x) * 4, dest = ((float.y + y) * doc.width + float.x + x) * 4;
        if (float.coverage && !float.coverage[y * float.image.width + x]) continue;
        if (!float.image.data[source + 3] && !result.data[dest + 3]) result.data.set(float.image.data.subarray(source, source + 3), dest);
        blendPixel(result.data, dest, float.image.data.subarray(source, source + 4), 1, false);
      }
      float.cached = result; float.cachedX = float.x; float.cachedY = float.y; float.needsUpdate = false; return result;
    }
    function cancelFloating() { if (!floating) return false; floating = null; floatingChanged(); return true; }
    function commitFloating() {
      if (!floating) return false; var value = floatingImage(), float = floating; floating = null; displayComposite = null;
      if (float.cut && float.x === float.originX && float.y === float.originY) { floatingChanged(); return false; }
      var nextMask = new Uint8Array(doc.width * doc.height);
      for (var y = 0; y < float.image.height; y++) for (var x = 0; x < float.image.width; x++) {
        var dx = float.x + x, dy = float.y + y; if (dx < 0 || dy < 0 || dx >= doc.width || dy >= doc.height) continue;
        var sx = float.originX + x, sy = float.originY + y, coverage = float.coverage ? float.coverage[y * float.image.width + x] : float.cut && float.sourceMask ? float.sourceMask[sy * doc.width + sx] : 255; nextMask[dy * doc.width + dx] = coverage;
      }
      var changed = false; try { changed = applyImageData(value, { label: float.cut ? "Move selection" : "Paste selection", selection: nextMask }); } catch (error) { floating = float; throw error; } finally { floatingChanged(); }
      return changed;
    }
    function setView(next) {
      view = { zoom: clamp(finite(next.zoom, view.zoom), .025, 128), x: finite(next.x, view.x), y: finite(next.y, view.y) };
      redraw(); if (options.onViewChange) options.onViewChange(Object.assign({}, view)); return Object.assign({}, view);
    }
    function screenSize() { var rect = canvas && canvas.getBoundingClientRect(); return { width: rect && rect.width || canvas && canvas.clientWidth || 300, height: rect && rect.height || canvas && canvas.clientHeight || 300 }; }
    function fit() { if (!doc) return; var size = screenSize(), zoom = clamp(Math.min((size.width - 16) / doc.width, (size.height - 16) / doc.height), .025, 128); setView({ zoom: zoom, x: (size.width - doc.width * zoom) / 2, y: (size.height - doc.height * zoom) / 2 }); }
    function viewToImage(p) { return { x: (p.x - view.x) / view.zoom, y: (p.y - view.y) / view.zoom }; }
    function imageToView(p) { return { x: p.x * view.zoom + view.x, y: p.y * view.zoom + view.y }; }
    function sample(x, y) { requireImage(); x = Math.floor(x); y = Math.floor(y); return x < 0 || y < 0 || x >= doc.width || y >= doc.height ? null : Array.from(doc.data.subarray((y * doc.width + x) * 4, (y * doc.width + x) * 4 + 4)); }
    function maskBoundary(bounds) {
      if (boundaryPath || !global.Path2D || transaction) return boundaryPath;
      var path = new global.Path2D();
      if (selectedPixels === bounds.width * bounds.height) path.rect(bounds.x, bounds.y, bounds.width, bounds.height);
      else for (var y = bounds.y; y < bounds.y + bounds.height; y++) for (var x = bounds.x; x < bounds.x + bounds.width; x++) {
        var p = y * doc.width + x; if (!selected[p]) continue;
        if (!y || !selected[p - doc.width]) { path.moveTo(x, y); path.lineTo(x + 1, y); }
        if (y + 1 === doc.height || !selected[p + doc.width]) { path.moveTo(x, y + 1); path.lineTo(x + 1, y + 1); }
        if (!x || !selected[p - 1]) { path.moveTo(x, y); path.lineTo(x, y + 1); }
        if (x + 1 === doc.width || !selected[p + 1]) { path.moveTo(x + 1, y); path.lineTo(x + 1, y + 1); }
      }
      boundaryPath = path; return path;
    }
    function render() {
      if (!canvas || disposed) return;
      var size = screenSize(), ratio = Math.min(2, global.devicePixelRatio || 1), width = Math.max(1, Math.round(size.width * ratio)), height = Math.max(1, Math.round(size.height * ratio));
      if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
      context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, size.width, size.height); context.fillStyle = "#20242b"; context.fillRect(0, 0, size.width, size.height);
      if (!doc) return;
      var flattened = compositeImage(false), display = compositeImage(true);
      if (pendingImage) { var r = pendingImage; imageContext.putImageData(new ImageData(flattened.data, doc.width, doc.height), 0, 0, r.x, r.y, r.width, r.height); pendingImage = null; }
      if (display !== flattened && (previewCanvasImage !== display || previewCanvasDirty)) { var displayRect = previewCanvasImage !== display ? dimensions() : previewCanvasDirty; previewContext.putImageData(new ImageData(display.data, doc.width, doc.height), 0, 0, displayRect.x, displayRect.y, displayRect.width, displayRect.height); previewCanvasImage = display; previewCanvasDirty = null; }
      if (selected && pendingMask) {
        if (!maskPixels) maskPixels = new Uint8ClampedArray(doc.width * doc.height * 4);
        var rect = pendingMask;
        for (var y = rect.y; y < rect.y + rect.height; y++) for (var x = rect.x; x < rect.x + rect.width; x++) { var i = y * doc.width + x; maskPixels[i * 4] = 0; maskPixels[i * 4 + 1] = 190; maskPixels[i * 4 + 2] = 255; maskPixels[i * 4 + 3] = Math.round(selected[i] * .3); }
        maskContext.putImageData(new ImageData(maskPixels, doc.width, doc.height), 0, 0, rect.x, rect.y, rect.width, rect.height);
      }
      pendingMask = null;
      context.save(); context.beginPath(); context.rect(view.x, view.y, doc.width * view.zoom, doc.height * view.zoom); context.clip();
      for (var cy = Math.max(0, Math.floor(view.y / 12) * 12); cy < Math.min(size.height, view.y + doc.height * view.zoom); cy += 12) for (var cx = Math.max(0, Math.floor(view.x / 12) * 12); cx < Math.min(size.width, view.x + doc.width * view.zoom); cx += 12) { context.fillStyle = (Math.round(cx / 12) + Math.round(cy / 12)) % 2 ? "#5d626a" : "#41464e"; context.fillRect(cx, cy, 12, 12); }
      context.imageSmoothingEnabled = view.zoom < 1; context.drawImage(display !== flattened ? previewCanvas : imageCanvas, view.x, view.y, doc.width * view.zoom, doc.height * view.zoom);
      if (selected && selectionVisible) context.drawImage(maskCanvas, view.x, view.y, doc.width * view.zoom, doc.height * view.zoom); context.restore();
      context.strokeStyle = "#969da8"; context.lineWidth = 1; context.strokeRect(view.x, view.y, doc.width * view.zoom, doc.height * view.zoom);
      if (options.drawOverlay) options.drawOverlay(context, Object.assign({}, view), getState());
      if (selectionVisible && selected && selectedPixels && !floating) {
        var bounds = selectionBounds(); if (bounds) { var path = maskBoundary(bounds); context.save(); context.translate(view.x, view.y); context.scale(view.zoom, view.zoom); context.strokeStyle = "#fff"; context.lineWidth = 1 / view.zoom; context.setLineDash([4 / view.zoom, 4 / view.zoom]); context.lineDashOffset = -(Date.now() / 150 % 8) / view.zoom; if (path) context.stroke(path); else context.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height); context.strokeStyle = "#111"; context.lineDashOffset += 4 / view.zoom; if (path) context.stroke(path); else context.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height); context.restore(); }
      }
      if (floating) { context.save(); context.strokeStyle = "#fff"; context.lineWidth = 1.5; context.setLineDash([5, 3]); context.strokeRect(view.x + floating.x * view.zoom, view.y + floating.y * view.zoom, floating.image.width * view.zoom, floating.image.height * view.zoom); context.setLineDash([]); [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(function (corner) { context.fillStyle = "#fff"; context.fillRect(view.x + (floating.x + floating.image.width * corner[0]) * view.zoom - 3, view.y + (floating.y + floating.image.height * corner[1]) * view.zoom - 3, 6, 6); }); context.restore(); }
      if (stroke && stroke.shape) { context.save(); context.strokeStyle = "#fff"; context.setLineDash([5, 3]); context.lineWidth = 1; var a = imageToView(stroke.start), b = imageToView(stroke.last); context.beginPath(); if (tool.indexOf("lasso") >= 0) { stroke.points.forEach(function (p, i) { p = imageToView(p); if (!i) context.moveTo(p.x, p.y); else context.lineTo(p.x, p.y); }); } else if (tool.indexOf("ellipse") >= 0) context.ellipse((a.x + b.x) / 2, (a.y + b.y) / 2, Math.abs(b.x - a.x) / 2, Math.abs(b.y - a.y) / 2, 0, 0, Math.PI * 2); else if (tool === "line") { context.moveTo(a.x, a.y); context.lineTo(b.x, b.y); } else context.rect(a.x, a.y, b.x - a.x, b.y - a.y); context.stroke(); context.restore(); }
      if (hover && ["brush", "eraser", "select-brush"].indexOf(tool) >= 0 && !space && !readOnly) { context.save(); context.beginPath(); context.arc(hover.x, hover.y, Math.max(.5, brush.size * view.zoom / 2), 0, Math.PI * 2); context.strokeStyle = "#000"; context.lineWidth = 3; context.stroke(); context.strokeStyle = "#fff"; context.lineWidth = 1; context.stroke(); context.restore(); }
      if (!antsTimer && selectionVisible && selectedPixels && canvas.getClientRects().length) antsTimer = global.setTimeout(function () { antsTimer = null; redraw(); }, 150);
    }
    function reportError(error) { if (options.onError) options.onError(error); else if (global.console) global.console.error(error); }
    function local(event) { var rect = canvas.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top }; }
    function listen(name, fn, target, config) { target = target || canvas; target.addEventListener(name, fn, config); events.push(function () { target.removeEventListener(name, fn, config); }); }
    function cancelStroke() { var previous = stroke; stroke = null; if (transaction) rollback(); if (previous && previous.moving && floating) { if (previous.created) cancelFloating(); else moveFloating(previous.x, previous.y); } redraw(); }
    function updateCursor() { if (canvas) canvas.style.cursor = readOnly && tool !== "picker" || tool === "pan" ? "grab" : ["brush", "eraser", "select-brush"].indexOf(tool) >= 0 ? "none" : "crosshair"; }
    function pointerDown(event) {
      if (!doc) return; event.preventDefault(); canvas.focus({ preventScroll: true });
      var p = local(event); pointers.set(event.pointerId, p); if (canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
      if (pointers.size > 1) {
        cancelStroke(); var pair = Array.from(pointers.values()); pinch = { distance: Math.max(1, Math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y)), center: { x: (pair[0].x + pair[1].x) / 2, y: (pair[0].y + pair[1].y) / 2 }, view: Object.assign({}, view) }; return;
      }
      if (pinch) return;
      var q = viewToImage(p), cfg = brushConfig(); hover = p;
      if (tool === "pan" || space || event.button === 1 || event.button === 2 || event.altKey || readOnly && tool !== "picker") { stroke = { pan: true, previous: p }; return; }
      try {
        if (floating || tool === "move") { var created = !floating; if (!floating && !startMoveSelection()) return; stroke = { moving: true, created: created, start: q, x: floating.x, y: floating.y }; return; }
        if (tool === "picker") { var picked = sample(q.x, q.y); if (picked) { brush.color = picked; if (options.onPick) options.onPick(picked.slice(), q); } return; }
        if (tool === "fill") { fillAt(q.x, q.y); return; }
        if (tool === "select-wand") { selectRegion(connectedRegion(doc, q.x, q.y, brush.tolerance, null, brush.contiguous), event.shiftKey ? "add" : event.ctrlKey || event.metaKey ? "subtract" : selectionMode); return; }
        if (tool === "select-uv-face" || tool === "select-uv-island") {
          if (options.onSelectUV) options.onSelectUV(q, tool, event.shiftKey ? "add" : event.ctrlKey || event.metaKey ? "subtract" : selectionMode);
          return;
        }
        if (tool === "brush" || tool === "eraser" || tool === "select-brush") {
          if (tool !== "select-brush") requireEditable();
          begin(tool); var selecting = tool === "select-brush", mode = event.shiftKey ? "add" : event.ctrlKey || event.metaKey ? "subtract" : selectionMode, subtract = mode === "subtract", selectionLimit = null;
          if (selecting) {
            if (mode === "intersect") { selectionLimit = selected && new Uint8Array(selected); setMaskRaw(new Uint8Array(doc.width * doc.height)); }
            else if (mode === "replace") setMaskRaw(new Uint8Array(doc.width * doc.height));
            else if (!selected) { selected = new Uint8Array(doc.width * doc.height); if (subtract) selected.fill(255); }
          }
          stroke = { previous: q, cfg: cfg, selecting: selecting, erase: selecting ? subtract : tool === "eraser", selectionLimit: selectionLimit };
          dab(q, cfg, selecting, stroke.erase, selectionLimit); redraw(transaction.dirty, transaction.maskDirty); return;
        }
        stroke = { shape: true, start: q, last: q, points: [q], mode: event.shiftKey ? "add" : event.ctrlKey || event.metaKey ? "subtract" : selectionMode };
      } catch (error) { cancelStroke(); reportError(error); }
    }
    function pointerMove(event) {
      var p = local(event); hover = p; if (pointers.has(event.pointerId)) pointers.set(event.pointerId, p);
      if (pinch && pointers.size >= 2) { var pair = Array.from(pointers.values()), center = { x: (pair[0].x + pair[1].x) / 2, y: (pair[0].y + pair[1].y) / 2 }, scale = Math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y) / pinch.distance, zoom = clamp(pinch.view.zoom * scale, .025, 128); setView({ zoom: zoom, x: center.x - (pinch.center.x - pinch.view.x) * zoom / pinch.view.zoom, y: center.y - (pinch.center.y - pinch.view.y) * zoom / pinch.view.zoom }); return; }
      if (!stroke || !pointers.has(event.pointerId)) { redraw(); return; }
      if (stroke.pan) { setView({ x: view.x + p.x - stroke.previous.x, y: view.y + p.y - stroke.previous.y }); stroke.previous = p; return; }
      var q = viewToImage(p);
      if (stroke.moving) { moveFloating(stroke.x + q.x - stroke.start.x, stroke.y + q.y - stroke.start.y); return; }
      if (stroke.shape) { stroke.last = q; if (Math.hypot(q.x - stroke.points[stroke.points.length - 1].x, q.y - stroke.points[stroke.points.length - 1].y) >= .5) stroke.points.push(q); redraw(); return; }
      try { segment(stroke.previous, q, stroke.cfg, stroke.selecting, stroke.erase, false, stroke.selectionLimit); stroke.previous = q; redraw(transaction.dirty, transaction.maskDirty); } catch (error) { cancelStroke(); reportError(error); }
    }
    function pointerUp(event) {
      pointers.delete(event.pointerId);
      if (pinch) { if (!pointers.size) pinch = null; return; }
      if (!stroke) return;
      var previous = stroke; stroke = null;
      try {
        if (previous.shape) {
          if (tool.indexOf("select-") === 0) { var kind = tool.slice(7), pts = kind === "lasso" ? previous.points : [previous.start, previous.last]; selectRegion(shapeMask(doc.width, doc.height, kind, pts, { fill: true }), previous.mode); }
          else drawShape(tool, previous.start, previous.last);
        } else if (!previous.pan && !previous.moving) commit();
      } catch (error) { cancelStroke(); reportError(error); }
      redraw();
    }
    function handleShortcut(event) {
      var key = String(event.key || "").toLowerCase();
      if (key === "escape") { cancelStroke(); cancelFloating(); return true; }
      if (key === "enter" && floating) { event.preventDefault(); if (!readOnly) commitFloating(); return true; }
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return false;
      if (readOnly && ["z", "y", "a", "x", "v"].indexOf(key) >= 0) { event.preventDefault(); return true; }
      if (key === "c") { event.preventDefault(); copySelection(); return true; }
      if (key === "x") { event.preventDefault(); if (!floating) cutSelection(); return true; }
      if (key === "v") { event.preventDefault(); if (!floating) pasteClipboard(); return true; }
      if (floating && key === "a") { event.preventDefault(); return true; }
      if (key === "z") { event.preventDefault(); if (event.shiftKey) travel(future, history, true); else travel(history, future, false); return true; }
      if (key === "y") { event.preventDefault(); travel(future, history, true); return true; }
      if (key === "a" && doc) { event.preventDefault(); var all = new Uint8Array(doc.width * doc.height); all.fill(255); setMask(all); return true; }
      return false;
    }
    if (canvas) {
      canvas.style.touchAction = "none"; canvas.style.cursor = "none"; if (!canvas.hasAttribute("tabindex")) canvas.tabIndex = 0;
      listen("pointerdown", pointerDown); listen("pointermove", pointerMove); listen("pointerup", pointerUp);
      listen("pointercancel", function (event) { pointers.delete(event.pointerId); cancelStroke(); if (!pointers.size) pinch = null; });
      listen("lostpointercapture", function (event) { if (pointers.has(event.pointerId)) { pointers.delete(event.pointerId); cancelStroke(); if (!pointers.size) pinch = null; } });
      listen("pointerleave", function () { hover = null; redraw(); }); listen("contextmenu", function (event) { event.preventDefault(); });
      listen("wheel", function (event) { if (!doc) return; event.preventDefault(); var p = local(event), q = viewToImage(p), zoom = clamp(view.zoom * Math.exp(-event.deltaY * .0015), .025, 128); setView({ zoom: zoom, x: p.x - q.x * zoom, y: p.y - q.y * zoom }); }, null, { passive: false });
      listen("keydown", function (event) { if (event.code === "Space") { event.preventDefault(); event.stopPropagation(); space = true; redraw(); } else if (handleShortcut(event)) event.stopPropagation(); });
      listen("keyup", function (event) { if (event.code === "Space") { space = false; redraw(); } });
      listen("blur", function () { space = false; });
      if (global.ResizeObserver) { resizeObserver = new global.ResizeObserver(function () { redraw(); }); resizeObserver.observe(canvas); }
      redraw();
    }
    return {
      setImage: setImage, getImage: function (copy) { var value = compositeImage(false); return value ? copy === false ? value : image(value) : null; }, getActiveImage: function (copy) { return doc ? copy === false ? doc : image(doc) : null; }, getDisplayImage: function () { return compositeImage(true); }, applyImageData: applyImageData, replaceImageData: replaceImageData, setPreviewImage: setPreviewImage,
      setDisplayOverride: function (value) { displayOverride = value === null ? null : image(value, doc); displayComposite = null; previewCanvasDirty = dimensions(); redraw(); },
      getLayers: layerRows, selectLayer: selectLayer, addLayer: addLayer, duplicateLayer: duplicateLayer, renameLayer: renameLayer, removeLayer: removeLayer, moveLayer: moveLayer, setLayerVisible: setLayerVisible, setLayerOpacity: setLayerOpacity, mergeLayerDown: mergeLayerDown,
      getProject: function (copy) { requireImage(); return snapshot(copy !== false); }, restoreProject: restoreProject,
      copySelection: copySelection, cutSelection: cutSelection, pasteClipboard: pasteClipboard, startMoveSelection: startMoveSelection, moveFloating: moveFloating, commitFloating: commitFloating, cancelFloating: cancelFloating,
      exportClipboard: function () { return clipboard ? { version: 1, x: clipboard.x, y: clipboard.y, image: image(clipboard.image), mask: clipboard.mask && new Uint8Array(clipboard.mask) } : null; }, importClipboard: importClipboard,
      getMask: function () { return selected ? new Uint8Array(selected) : null; }, setMask: setMask, selectRegion: selectRegion,
      setSelectionVisible: function (value) { selectionVisible = !!value; redraw(); },
      // Interaction lock for saved previews. Programmatic restore APIs remain
      // available; the host controls its own toolbar and persistence commands.
      setReadOnly: function (value) { value = !!value; if (readOnly === value) return; readOnly = value; if (readOnly) cancelStroke(); updateCursor(); redraw(); },
      clearSelection: function () { return setMask(null); }, selectNone: function () { requireImage(); return setMask(new Uint8Array(doc.width * doc.height)); },
      selectAll: function () { requireImage(); var all = new Uint8Array(doc.width * doc.height); all.fill(255); return setMask(all); },
      invertSelection: function () { requireImage(); var next = new Uint8Array(doc.width * doc.height); if (selected) for (var i = 0; i < next.length; i++) next[i] = 255 - selected[i]; return setMask(next); },
      setTool: function (value) { if (TOOLS.indexOf(value) < 0) throw new Error("Choose a supported texture tool."); cancelStroke(); tool = value; updateCursor(); redraw(); },
      setBrush: function (value) { brush = brushConfig(value); redraw(); return getState().brush; },
      setSelectionMode: function (mode) { if (["replace", "add", "subtract", "intersect"].indexOf(mode) < 0) throw new Error("Choose a supported selection mode."); selectionMode = mode; },
      paintStroke: paintStroke, fillAt: fillAt, drawShape: drawShape, sample: sample,
      undo: function () { return travel(history, future, false); }, redo: function () { return travel(future, history, true); }, getState: getState, handleShortcut: handleShortcut,
      setView: setView, getView: function () { return Object.assign({}, view); }, fit: fit, viewToImage: viewToImage, imageToView: imageToView, render: function () { redraw(); },
      destroy: function () { disposed = true; cancelStroke(); cancelFloating(); events.forEach(function (remove) { remove(); }); if (resizeObserver) resizeObserver.disconnect(); if (antsTimer) global.clearTimeout(antsTimer); if (frame !== null) { if (global.cancelAnimationFrame) global.cancelAnimationFrame(frame); else global.clearTimeout(frame); } history = []; future = []; layers = []; composite = null; displayComposite = null; displayOverride = null; doc = null; selected = null; preview = null; }
    };
  }
  var exported = { create: create, blendPixel: blendPixel, connectedRegion: connectedRegion, shapeMask: shapeMask, color: color, tools: TOOLS.slice(), maxPixels: MAX_PIXELS };
  global.TexturePaintEngine = exported;
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
}(typeof window !== "undefined" ? window : globalThis));
