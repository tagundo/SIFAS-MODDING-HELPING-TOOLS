"use strict";
const assert = require("node:assert/strict");
const Clip = require("../webtools/web/static/viewer-near-clip.js");
let cases = 0;
function test(name, run) { run(); cases++; process.stdout.write("ok " + name + "\n"); }
const identity = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
function camera(extra) {
  return Object.assign({ near: .01, far: 100, userData: {}, matrixWorldInverse: { elements: identity() },
    projectionUpdates: 0, updateProjectionMatrix() { this.projectionUpdates++; } }, extra);
}
test("fresh settings keep close clipping OFF and preserve the existing automatic near policy exactly", () => {
  for (const radius of [.0001, .02, 1, 300, 1000000]) for (const distance of [0, NaN, Infinity, .00001, .12 * radius, radius, 60 * radius]) {
    const floor = Math.max(.001, radius / 1000);
    const previous = Number.isFinite(distance) && distance > 0 ? Math.max(floor, Math.min(radius / 100, distance / 120)) : floor;
    const value = Clip.resolve({ radius, orbitDistance: distance });
    assert.equal(value.enabled, false);
    assert.equal(value.near, previous);
    assert.equal(value.automaticNear, previous);
  }
});
test("stored non-boolean enable values cannot silently turn the option on", () => {
  for (const enabled of [undefined, null, false, 0, 1, "true", "false"]) assert.equal(Clip.resolve({ enabled }).enabled, false);
  assert.equal(Clip.resolve({ enabled: true }).enabled, true);
});
test("enabled clipping uses a positive model-unit distance and retains the normal depth precision floor", () => {
  assert.equal(Clip.resolve({ enabled: true, radius: 1, orbitDistance: 2, far: 100 }).near, .03);
  assert.equal(Clip.resolve({ enabled: true, distance: .2, radius: 1, orbitDistance: 2, far: 100 }).near, .2);
  assert.equal(Clip.resolve({ enabled: true, distance: .00001, radius: 1000, orbitDistance: 2000, far: 100000 }).near, 10);
});
test("invalid distance input recovers to the usable default without making the projection invalid", () => {
  for (const distance of [undefined, null, 0, -.5, NaN, Infinity, "broken"]) assert.equal(Clip.normalizeDistance(distance), .03);
  assert.equal(Clip.normalizeDistance("0.125"), .125);
  assert.equal(Clip.normalizeDistance(1e20), 1000000);
});
test("a typed distance beyond the far plane is safely bounded without changing far", () => {
  const c = camera({ far: .1 });
  const result = Clip.apply(c, { enabled: true, distance: 500, radius: .01, orbitDistance: .02 });
  assert(result.near > 0 && result.near < c.far);
  assert.equal(c.far, .1);
  assert.equal(c.near, .095);
});
test("applying and disabling the preview restores automatic near and changes no camera pose or authored state", () => {
  const c = camera({ fov: 35, position: { x: 1, y: 2, z: 3 }, target: { x: 0, y: 1, z: 0 }, up: { x: 0, y: 1, z: 0 },
    userData: { source: "immutable", meshRecipe: [{ vertex: 9, position: [1, 2, 3] }] } });
  const retained = JSON.stringify({ fov: c.fov, position: c.position, target: c.target, up: c.up, source: c.userData.source, recipe: c.userData.meshRecipe });
  Clip.apply(c, { radius: 1, orbitDistance: 3, enabled: true, distance: .3 });
  assert.equal(c.near, .3); assert.equal(c.userData.viewerNearClipEnabled, true);
  Clip.apply(c, { radius: 1, orbitDistance: 3, enabled: false, distance: .3 });
  assert.equal(c.near, .01); assert.equal(c.userData.viewerNearClipEnabled, false);
  assert.equal(JSON.stringify({ fov: c.fov, position: c.position, target: c.target, up: c.up, source: c.userData.source, recipe: c.userData.meshRecipe }), retained);
});
test("stable settings and distances do not rebuild the projection every rendered frame", () => {
  const c = camera();
  Clip.apply(c, { radius: 1, orbitDistance: 3, enabled: true, distance: .3 });
  for (let frame = 0; frame < 240; frame++) Clip.apply(c, { radius: 1, orbitDistance: 3, enabled: true, distance: .3 });
  assert.equal(c.projectionUpdates, 1);
});
test("OFF picking is exact pass-through and requires no matrix or hit allocation", () => {
  assert.equal(Clip.visiblePoint(null, null), true);
  const c = { userData: { viewerNearClipEnabled: false } };
  assert.equal(Clip.visiblePoint(c, { x: NaN }), true);
  assert.equal(Clip.filterForCamera(c), null);
});
test("picking clips by planar camera depth rather than radial ray distance", () => {
  const c = camera({ near: .5, userData: { viewerNearClipEnabled: true } });
  assert.equal(Clip.visiblePoint(c, { x: 20, y: -20, z: -.4 }), false, "A distant corner can still lie in the clipped front layer");
  assert.equal(Clip.visiblePoint(c, { x: 20, y: -20, z: -.6 }), true);
  assert.equal(Clip.visiblePoint(c, { x: 0, y: 0, z: .1 }), false, "Points behind the camera are hidden");
});
test("translated camera clipping uses world-to-view depth", () => {
  const matrix = identity(); matrix[12] = -4; matrix[13] = -2; matrix[14] = -3;
  const c = camera({ near: .5, matrixWorldInverse: { elements: matrix }, userData: { viewerNearClipEnabled: true } });
  assert.equal(Clip.visiblePoint(c, { x: 4, y: 2, z: 2.8 }), false);
  assert.equal(Clip.visiblePoint(c, { x: 4, y: 2, z: 2.4 }), true);
});
test("a rotated camera uses its own viewing direction rather than the world Z axis", () => {
  const c = camera({ near: .5, userData: { viewerNearClipEnabled: true },
    matrixWorldInverse: { elements: [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, -3, -2, 4, 1] } });
  assert.equal(Clip.visiblePoint(c, { x: 4.1, y: 200, z: 300 }), false);
  assert.equal(Clip.visiblePoint(c, { x: 4.8, y: 200, z: 300 }), true);
});
test("near and far boundaries agree with raster visibility while excluding genuinely out-of-range points", () => {
  const c = camera({ near: .5, userData: { viewerNearClipEnabled: true } });
  assert.equal(Clip.visiblePoint(c, { x: 0, y: 0, z: -.5 }), true);
  assert.equal(Clip.visiblePoint(c, { x: 0, y: 0, z: -100 }), true);
  assert.equal(Clip.visiblePoint(c, { x: 0, y: 0, z: -.49 }), false);
  assert.equal(Clip.visiblePoint(c, { x: 0, y: 0, z: -100.001 }), false);
});
test("invalid world points or camera intervals cannot expose a hidden pick when enabled", () => {
  const c = camera({ near: .5, userData: { viewerNearClipEnabled: true } });
  for (const point of [null, {}, { x: NaN, y: 0, z: -1 }, { x: 0, y: Infinity, z: -1 }]) assert.equal(Clip.visiblePoint(c, point), false);
  assert.equal(Clip.visiblePoint(camera({ near: 2, far: 1, userData: c.userData }), { x: 0, y: 0, z: -1 }), false);
});
test("cached ray filters observe current clip settings and remain independent between model cameras", () => {
  const c = camera({ near: .5, userData: { viewerNearClipEnabled: true } }), f = Clip.filterForCamera(c);
  assert.equal(f, Clip.filterForCamera(c)); assert.equal(f({ x: 0, y: 0, z: -.4 }), false);
  c.near = .25; assert.equal(f({ x: 0, y: 0, z: -.4 }), true);
  c.userData.viewerNearClipEnabled = false; assert.equal(Clip.filterForCamera(c), null); assert.equal(f({ x: 0, y: 0, z: .4 }), true);
  const other = camera({ near: .6, userData: { viewerNearClipEnabled: true } });
  assert.notEqual(f, Clip.filterForCamera(other)); assert.equal(Clip.filterForCamera(other)({ x: 0, y: 0, z: -.4 }), false);
});
process.stdout.write(JSON.stringify({ status: "PASS", cases }) + "\n");
