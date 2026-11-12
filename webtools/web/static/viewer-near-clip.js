/* Preview-only camera clipping. Model geometry, materials and export recipes
 * are deliberately untouched. Picking uses the same planar camera interval. */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ViewerNearClip = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  var DEFAULT_DISTANCE = 0.03, filters = typeof WeakMap === "function" ? new WeakMap() : null;
  function positive(value, fallback) {
    value = Number(value);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  }
  function normalizeDistance(value) {
    return Math.min(1000000, positive(value, DEFAULT_DISTANCE));
  }
  function automaticNear(radius, orbitDistance) {
    radius = positive(radius, 1);
    orbitDistance = Number(orbitDistance);
    var floor = Math.max(0.001, radius / 1000);
    // This is the viewer's existing depth-precision policy, unchanged when OFF.
    return Number.isFinite(orbitDistance) && orbitDistance > 0
      ? Math.max(floor, Math.min(radius / 100, orbitDistance / 120)) : floor;
  }
  function resolve(options) {
    options = options || {};
    var automatic = automaticNear(options.radius, options.orbitDistance);
    var enabled = options.enabled === true, distance = normalizeDistance(options.distance), near = automatic;
    if (enabled) {
      near = Math.max(automatic, distance);
      var far = positive(options.far, Infinity);
      // A saved or typed distance must never invert the projection interval.
      if (Number.isFinite(far)) near = Math.min(near, far * 0.95);
    }
    return { enabled: enabled, distance: distance, automaticNear: automatic, near: near };
  }
  function apply(camera, options) {
    if (!camera) return null;
    options = options || {};
    var state = resolve({ radius: options.radius, orbitDistance: options.orbitDistance,
      enabled: options.enabled, distance: options.distance, far: camera.far });
    camera.userData = camera.userData || {};
    camera.userData.viewerNearClipEnabled = state.enabled;
    if (!Number.isFinite(camera.near) || Math.abs(camera.near - state.near) > Math.max(1e-9, Math.abs(camera.near) * 1e-6)) {
      camera.near = state.near;
      if (camera.updateProjectionMatrix) camera.updateProjectionMatrix();
    }
    return state;
  }
  function viewDepth(camera, point) {
    var matrix = camera && camera.matrixWorldInverse && camera.matrixWorldInverse.elements;
    if (!point || !matrix || matrix.length !== 16 || !Number.isFinite(point.x) || !Number.isFinite(point.y) || !Number.isFinite(point.z)) return NaN;
    // Matrix4 is column-major. A perspective camera looks along its local -Z.
    return -(matrix[2] * point.x + matrix[6] * point.y + matrix[10] * point.z + matrix[14]);
  }
  function visiblePoint(camera, point) {
    if (!camera || !camera.userData || camera.userData.viewerNearClipEnabled !== true) return true;
    var depth = viewDepth(camera, point), near = camera.near, far = camera.far;
    if (!Number.isFinite(depth) || !Number.isFinite(near) || !(near > 0) || !(far > near)) return false;
    var nearTolerance = Math.max(1e-8, Math.abs(near) * 1e-7), farTolerance = Math.max(1e-8, Math.abs(far) * 1e-7);
    return depth >= near - nearTolerance && depth <= far + farTolerance;
  }
  function filterForCamera(camera) {
    if (!camera || !camera.userData || camera.userData.viewerNearClipEnabled !== true) return null;
    var filter = filters && filters.get(camera);
    if (!filter) {
      filter = function (point) { return visiblePoint(camera, point); };
      if (filters) filters.set(camera, filter);
    }
    return filter;
  }
  return { DEFAULT_DISTANCE: DEFAULT_DISTANCE, normalizeDistance: normalizeDistance, automaticNear: automaticNear,
    resolve: resolve, apply: apply, viewDepth: viewDepth, visiblePoint: visiblePoint, filterForCamera: filterForCamera };
}));
