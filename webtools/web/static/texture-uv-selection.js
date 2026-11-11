/* Texture-space face and UV-island selection. Input points are already in the
 * sampled texture's coordinates (matrix, wrapping and flip applied by caller).
 * Islands share full UV edges within the same mesh/material, never 3D edges.
 * No image-sized mask or source geometry is retained or changed here. */
(function (global) {
  "use strict";
  var EPSILON = 1e-6, MAX_POLYGONS = 100000, MAX_REFERENCES = 2000000;
  function finite(value) { return typeof value === "number" && isFinite(value); }
  function identity(value) {
    if (value === undefined) return "undefined";
    if (value === null) return "null";
    if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean" || typeof value === "number" && !finite(value)) throw new Error("UV selection mesh and material identities must be scalar values.");
    return JSON.stringify([typeof value, value]);
  }
  function endpoint(point) { return Math.round(point[0] / EPSILON) + "," + Math.round(point[1] / EPSILON); }
  function cross(a, b, x, y) { return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]); }
  function onSegment(a, b, x, y) {
    var dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
    if (!length) return Math.hypot(x - a[0], y - a[1]) <= EPSILON;
    var t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length));
    return Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy) <= EPSILON;
  }
  function contains(row, x, y) {
    var bounds = row.bounds;
    if (x < bounds[0] - EPSILON || y < bounds[1] - EPSILON || x > bounds[2] + EPSILON || y > bounds[3] + EPSILON) return false;
    var points = row.points, area = cross(points[0], points[1], points[2][0], points[2][1]);
    if (Math.abs(area) <= EPSILON * EPSILON) return onSegment(points[0], points[1], x, y) || onSegment(points[1], points[2], x, y) || onSegment(points[2], points[0], x, y);
    var positive = false, negative = false;
    for (var i = 0; i < 3; i++) {
      var a = points[i], b = points[(i + 1) % 3], side = cross(a, b, x, y), tolerance = EPSILON * Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (side > tolerance) positive = true;
      if (side < -tolerance) negative = true;
    }
    return !(positive && negative);
  }
  function build(polygons, options) {
    options = options || {};
    var limit = options.maxPolygons === undefined ? MAX_POLYGONS : options.maxPolygons;
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_POLYGONS) throw new Error("UV selection polygon limit must be between 1 and " + MAX_POLYGONS + ".");
    if (!Array.isArray(polygons) || polygons.length > limit) throw new Error("UV selection supports at most " + limit + " polygons per texture.");
    var count = polygons.length, rows = new Array(count), parents = new Int32Array(count), ranks = new Uint8Array(count), edges = new Map();
    var resolution = Math.max(8, Math.min(128, Math.ceil(Math.sqrt(Math.max(1, count) / 4)))), cells = new Map(), broad = [], references = 0;
    var components = new Map(), componentIds = new Int32Array(count), lastCandidates = 0, lastHits = 0;
    function find(index) {
      var root = index;
      while (parents[root] !== root) root = parents[root];
      while (parents[index] !== index) { var next = parents[index]; parents[index] = root; index = next; }
      return root;
    }
    function join(left, right) {
      left = find(left); right = find(right); if (left === right) return;
      if (ranks[left] < ranks[right]) parents[left] = right;
      else { parents[right] = left; if (ranks[left] === ranks[right]) ranks[left]++; }
    }
    function cell(value) { return Math.max(0, Math.min(resolution - 1, Math.floor(value * resolution))); }
    polygons.forEach(function (polygon, index) {
      if (!polygon || !Array.isArray(polygon.points) || polygon.points.length !== 3) throw new Error("UV selection requires triangle points.");
      var points = polygon.points.map(function (point) {
        if (!Array.isArray(point) || point.length !== 2 || !point.every(function (n) { return finite(n) && Math.abs(n) <= 1000000; })) throw new Error("UV selection coordinates must be finite pairs.");
        return point.slice();
      });
      var xs = points.map(function (p) { return p[0]; }), ys = points.map(function (p) { return p[1]; });
      rows[index] = { points: points, bounds: [Math.min.apply(Math, xs), Math.min.apply(Math, ys), Math.max.apply(Math, xs), Math.max.apply(Math, ys)], scope: identity(polygon.meshId) + "/" + identity(polygon.group) };
      parents[index] = index;
    });
    rows.forEach(function (row, index) {
      for (var i = 0; i < 3; i++) {
        var a = endpoint(row.points[i]), b = endpoint(row.points[(i + 1) % 3]);
        if (a === b) continue; // A collapsed edge is only a vertex, not adjacency.
        var key = row.scope + "/" + (a < b ? a + "/" + b : b + "/" + a), previous = edges.get(key);
        if (previous === undefined) edges.set(key, index); else join(index, previous);
      }
      var bounds = row.bounds;
      if (bounds[2] < -EPSILON || bounds[3] < -EPSILON || bounds[0] > 1 + EPSILON || bounds[1] > 1 + EPSILON) return;
      var left = cell(bounds[0] - EPSILON), top = cell(bounds[1] - EPSILON), right = cell(bounds[2] + EPSILON), bottom = cell(bounds[3] + EPSILON), size = (right - left + 1) * (bottom - top + 1);
      // Full-image and long triangles are cheaper in a single shared list.
      // A hard reference budget prevents pathological UVs growing the grid.
      if (size > 64 || references + size > MAX_REFERENCES) { broad.push(index); return; }
      for (var y = top; y <= bottom; y++) for (var x = left; x <= right; x++) {
        var id = y * resolution + x, bucket = cells.get(id);
        if (!bucket) { bucket = []; cells.set(id, bucket); }
        bucket.push(index);
      }
      references += size;
    });
    rows.forEach(function (_, index) {
      var root = find(index), members = components.get(root);
      if (!members) { members = []; components.set(root, members); }
      members.push(index); componentIds[index] = root;
    });
    // Union-find is complete. Drop its edge strings before repeated picking.
    edges.clear();
    return {
      hit: function (x, y, mode) {
        if (mode !== undefined && mode !== "face" && mode !== "island" && mode !== "select-uv-face" && mode !== "select-uv-island") throw new Error("Choose UV face or UV island selection.");
        lastCandidates = 0; lastHits = 0;
        if (!finite(x) || !finite(y) || x < 0 || y < 0 || x > 1 || y > 1) return [];
        var bucket = cells.get(cell(y) * resolution + cell(x)) || [], hits = [];
        lastCandidates = bucket.length + broad.length;
        bucket.forEach(function (index) { if (contains(rows[index], x, y)) hits.push(index); });
        broad.forEach(function (index) { if (contains(rows[index], x, y)) hits.push(index); });
        lastHits = hits.length;
        if (mode === "island" || mode === "select-uv-island") {
          var roots = new Set(), selected = [];
          hits.forEach(function (index) { roots.add(componentIds[index]); });
          roots.forEach(function (root) { components.get(root).forEach(function (index) { selected.push(index); }); });
          hits = selected;
        }
        return hits.sort(function (a, b) { return a - b; });
      },
      getState: function () { return { polygons: count, components: components.size, gridSize: resolution, occupiedCells: cells.size, gridReferences: references, broadPolygons: broad.length, lastCandidates: lastCandidates, lastHits: lastHits, tolerance: EPSILON }; }
    };
  }
  var exported = { build: build, tolerance: EPSILON, maxPolygons: MAX_POLYGONS };
  global.TextureUVSelection = exported;
  if (typeof module === "object" && module.exports) module.exports = exported;
}(typeof window !== "undefined" ? window : globalThis));
