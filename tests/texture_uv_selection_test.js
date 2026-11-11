"use strict";
const assert = require("node:assert/strict");
const UV = require("../webtools/web/static/texture-uv-selection.js");
let cases = 0;
function test(name, run) { run(); cases++; process.stdout.write("ok " + name + "\n"); }
function triangle(points, extra) { return Object.assign({ points, meshId: "body", group: 0 }, extra); }
function square(x, y, size, extra) {
  return [triangle([[x, y], [x + size, y], [x, y + size]], extra), triangle([[x + size, y], [x + size, y + size], [x, y + size]], extra)];
}
test("face click selects the containing UV triangle and island follows its full edge", () => {
  const index = UV.build(square(.1, .1, .4));
  assert.deepEqual(index.hit(.15, .15, "face"), [0]);
  assert.deepEqual(index.hit(.15, .15, "island"), [0, 1]);
  assert.deepEqual(index.hit(.45, .45, "face"), [1]);
});
test("UV-island adjacency works with reversed winding and duplicate vertex storage", () => {
  const first = triangle([[.1, .1], [.5, .1], [.1, .5]]);
  const second = triangle([[.1, .5], [.5, .5], [.5, .1]]);
  assert.deepEqual(UV.build([first, second]).hit(.15, .15, "island"), [0, 1]);
});
test("sharing only a UV vertex does not join separate islands", () => {
  const polygons = square(.1, .1, .3).concat(triangle([[.4, .4], [.7, .4], [.4, .7]]));
  const index = UV.build(polygons);
  assert.deepEqual(index.hit(.15, .15, "island"), [0, 1]);
  assert.deepEqual(index.hit(.45, .45, "island"), [2]);
});
test("a UV seam stays split even when the caller gives the same original face identity", () => {
  const index = UV.build([triangle([[.05, .1], [.35, .1], [.05, .4]], { face: 6 }), triangle([[.65, .6], [.95, .6], [.65, .9]], { face: 6 })]);
  assert.deepEqual(index.hit(.1, .15, "island"), [0]);
  assert.deepEqual(index.hit(.7, .65, "island"), [1]);
});
test("material and mesh boundaries keep coincident UV edges separate", () => {
  const pair = square(.1, .1, .4);
  for (const extra of [{ meshId: "accessory" }, { group: 1 }]) {
    const index = UV.build([pair[0], Object.assign({}, pair[1], extra)]);
    assert.deepEqual(index.hit(.15, .15, "island"), [0]);
  }
});
test("overlapping triangles all select because the same texture pixel affects them all", () => {
  const polygons = square(.1, .1, .4).concat(square(.1, .1, .4, { meshId: "sleeve" }));
  const index = UV.build(polygons);
  assert.deepEqual(index.hit(.15, .15, "face"), [0, 2]);
  assert.deepEqual(index.hit(.15, .15, "island"), [0, 1, 2, 3]);
});
test("small UV rounding noise joins an edge while a real seam does not", () => {
  const pair = square(.1, .1, .4), noisy = pair[1].points.map(p => [p[0] + .2e-6, p[1] + .2e-6]);
  assert.deepEqual(UV.build([pair[0], triangle(noisy)]).hit(.15, .15, "island"), [0, 1]);
  const split = pair[1].points.map(p => [p[0] + 4e-6, p[1] + 4e-6]);
  assert.deepEqual(UV.build([pair[0], triangle(split)]).hit(.15, .15, "island"), [0]);
});
test("caller-transformed flip, offset and rectangular UV placement is used without another transform", () => {
  const transformed = square(.6, .05, .2);
  const index = UV.build(transformed);
  assert.deepEqual(index.hit(.65, .1, "select-uv-island"), [0, 1]);
  assert.deepEqual(index.hit(.1, .65, "select-uv-face"), []);
});
test("clicks on a common edge include both faces without duplicate island members", () => {
  const index = UV.build(square(.1, .1, .4));
  assert.deepEqual(index.hit(.3, .3, "face"), [0, 1]);
  assert.deepEqual(index.hit(.3, .3, "island"), [0, 1]);
});
test("degenerate line UVs can be picked at the image border but have no artificial area", () => {
  const index = UV.build([triangle([[1, 0], [1, .5], [1, 1]]), triangle([[.4, .4], [.4, .4], [.4, .4]])]);
  assert.deepEqual(index.hit(1, .25), [0]);
  assert.deepEqual(index.hit(.95, .25), []);
  assert.deepEqual(index.hit(.4, .4), [1]);
  assert.equal(index.getState().components, 2);
});
test("pixels outside the image and wholly outside triangles cannot select hidden atlas regions", () => {
  const index = UV.build(square(1.1, 1.1, .2).concat(square(.1, .1, .2)));
  assert.deepEqual(index.hit(1.15, 1.15), []);
  assert.deepEqual(index.hit(-.1, .1), []);
  assert.deepEqual(index.hit(.9, .9), []);
  assert.deepEqual(index.hit(.15, .15, "island"), [2, 3]);
});
test("source mutations and returned-array changes cannot corrupt a built index", () => {
  const polygons = square(.1, .1, .4), before = JSON.stringify(polygons), index = UV.build(polygons);
  assert.equal(JSON.stringify(polygons), before);
  polygons[0].points[0][0] = 100;
  const result = index.hit(.15, .15, "island"); result.length = 0;
  assert.deepEqual(index.hit(.15, .15, "island"), [0, 1]);
});
test("empty input is valid and invalid input fails before an index is exposed", () => {
  assert.deepEqual(UV.build([]).hit(.5, .5), []);
  for (const value of [null, {}, [triangle([[0, 0], [1, 0], [NaN, 1]])], [triangle([[0, 0], [1, 0], [1, Infinity]])], [triangle([[0, 0], [1, 0]])]]) assert.throws(() => UV.build(value));
  assert.throws(() => UV.build([triangle([[0, 0], [1, 0], [0, 1]], { meshId: {} })]), /identities/);
  assert.throws(() => UV.build(square(0, 0, 1), { maxPolygons: 1 }), /at most 1/);
  assert.throws(() => UV.build([], { maxPolygons: 100001 }), /limit/);
  assert.throws(() => UV.build([]).hit(0, 0, "paint"), /UV face or UV island/);
});
test("a nonmanifold shared edge does not require a quadratic neighbor graph", () => {
  const polygons = Array.from({ length: 3000 }, (_, n) => triangle([[.1, .1], [.9, .1], [.1 + .7 * n / 3000, .9]]));
  const index = UV.build(polygons), hits = index.hit(.1, .1, "island");
  assert.equal(hits.length, polygons.length);
  assert.equal(new Set(hits).size, polygons.length);
  assert.equal(index.getState().components, 1);
});
test("large sparse atlas lookup uses a bounded spatial index without losing the face", () => {
  const polygons = [], across = 224;
  for (let y = 0; y < across; y++) for (let x = 0; x < across; x++) polygons.push(triangle([[x / across, y / across], [(x + .4) / across, y / across], [x / across, (y + .4) / across]], { meshId: "atlas", face: y * across + x }));
  const index = UV.build(polygons), x = 129, y = 87;
  assert.deepEqual(index.hit((x + .1) / across, (y + .1) / across), [y * across + x]);
  assert(index.getState().lastCandidates < 64, "sparse picking should not scan fifty thousand faces");
  assert(index.getState().gridReferences <= 2000000);
  assert.equal(index.getState().polygons, across * across);
});
test("one hundred thousand members are selected without browser argument-count limits", () => {
  const polygon = triangle([[.1, .1], [.9, .1], [.1, .9]]), index = UV.build(Array(100000).fill(polygon));
  const selected = index.hit(.2, .2, "island");
  assert.equal(selected.length, 100000); assert.equal(selected[0], 0); assert.equal(selected[99999], 99999);
  assert.throws(() => UV.build(Array(100001).fill(polygon)), /at most 100000/);
});
process.stdout.write("PASS " + cases + " UV region selection cases\n");
