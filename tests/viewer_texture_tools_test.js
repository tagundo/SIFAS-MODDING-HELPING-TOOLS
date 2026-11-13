"use strict";
const assert = require("assert");
const tools = require("../webtools/web/static/viewer-texture-tools.js");
let cases = 0;
function test(name, run) { run(); cases++; process.stdout.write("ok " + name + "\n"); }
function texture(extra) { return Object.assign({ wrapS: 1001, wrapT: 1001, flipY: false, matrixAutoUpdate: false, matrix: { elements: [1, 0, 0, 0, 1, 0, 0, 0, 1] } }, extra || {}); }
test("Unity identity ignores object property insertion order and distinguishes files", () => {
  assert(tools.sameIdentity({ source: 0, file: 2, id: "-55" }, { id: "-55", file: 2, source: 0 }));
  assert(!tools.sameIdentity({ source: 0, file: 2, id: "55" }, { source: 0, file: 3, id: "55" }));
  assert(!tools.sameIdentity({ source: 0, file: 2, id: 55 }, { source: 0, file: 2, id: "55" }));
});
test("RGBA comparison includes hidden RGB and alpha", () => {
  const left = { width: 1, height: 1, data: new Uint8ClampedArray([13, 29, 71, 0]) };
  assert(tools.equalPixels(left, { width: 1, height: 1, data: new Uint8ClampedArray([13, 29, 71, 0]) }));
  assert(!tools.equalPixels(left, { width: 1, height: 1, data: new Uint8ClampedArray([0, 0, 0, 0]) }));
  assert(!tools.equalPixels(left, { width: 1, height: 1, data: new Uint8ClampedArray([13, 29, 71, 1]) }));
});
test("GLB UV is not flipped twice", () => {
  assert.deepStrictEqual(tools.sampledUv(texture(), [.25, .75]), [.25, .75]);
  assert.deepStrictEqual(tools.sampledUv(texture({ flipY: true }), [.25, .75]), [.25, .25]);
});
test("Texture matrix precedes wrapping and flipY", () => {
  const map = texture({ wrapS: 1000, wrapT: 1002, flipY: true, matrix: { elements: [2, 0, 0, 0, 3, 0, .1, .2, 1] } });
  const point = tools.sampledUv(map, [.75, .5]);
  assert(Math.abs(point[0] - .6) < 1e-12);
  assert(Math.abs(point[1] - .7) < 1e-12);
});
test("Clamp and mirror modes match Texture.transformUv at negative and positive UVs", () => {
  assert.deepStrictEqual(tools.sampledUv(texture(), [-.2, 1.3]), [0, 1]);
  const point = tools.sampledUv(texture({ wrapS: 1002, wrapT: 1002 }), [-.2, 1.3]);
  assert(Math.abs(point[0] - .2) < 1e-12 && Math.abs(point[1] - .7) < 1e-12);
});
test("Non-square masks rasterize image coordinates, without square stretching", () => {
  const mask = tools.rasterFaces(8, 4, [[0, 1, 2]], [[0, 0], [1, 0], [0, 1]], [0], texture());
  assert.strictEqual(mask.length, 32);
  assert.strictEqual(mask.filter(Boolean).length, 20);
  assert(mask[0] && mask[24] && mask[7] && !mask[15] && !mask[31]);
});
test("Repeat seam selects both image borders, not the intervening atlas", () => {
  const mask = tools.rasterFaces(8, 4, [[0, 1, 2]], [[.75, 0], [1.25, 0], [.75, 1]], [0], texture({ wrapS: 1000 }));
  assert(mask[0] && mask[6] && mask[7]);
  assert.strictEqual(mask[4], 0);
});
test("Mirror seam remains on the mirrored border", () => {
  const mask = tools.rasterFaces(8, 4, [[0, 1, 2]], [[.75, 0], [1.25, 0], [.75, 1]], [0], texture({ wrapS: 1002 }));
  assert(mask[6] && mask[7]);
  assert.strictEqual(mask[0], 0);
});
test("Triangle selection does not mutate source UVs or input face arrays", () => {
  const uv = [[.1, .1], [.9, .1], [.1, .9]], triangles = [[0, 1, 2]], before = JSON.stringify([uv, triangles]);
  tools.rasterFaces(16, 8, triangles, uv, [0], texture({ flipY: true }));
  assert.strictEqual(JSON.stringify([uv, triangles]), before);
});
test("Clamped degenerate UV keeps the edge texels editable", () => {
  const mask = tools.rasterFaces(8, 4, [[0, 1, 2]], [[2, 0], [2, .5], [2, 1]], [0], texture());
  assert(mask[7] && mask[15] && mask[23] && mask[31]);
  assert.strictEqual(mask.filter(Boolean).length, 4);
});
test("Unbounded repeat geometry is rejected rather than blocking the editor", () => {
  assert.throws(() => tools.triangleCopies(texture({ wrapS: 1000 }), [[0, 0], [10000, 0], [0, 1]]), /repeats too many/);
});
test("Invalid or missing faces do not alter unrelated texels", () => {
  const mask = tools.rasterFaces(4, 4, [[0, 1, 2]], [[0, 0], [1, 0], [NaN, 1]], [0, 4], texture());
  assert.strictEqual(mask.filter(Boolean).length, 0);
});
test("Fine model brush covers texels within its diameter rather than whole faces", () => {
  const mask = tools.brushMask(null, 32 * 16, "replace");
  const dirty = tools.stampMaskCircle(mask, null, 32, 16, 12, 8, 2, "replace");
  assert.deepStrictEqual(dirty, {left:10,top:6,right:14,bottom:10});
  assert.strictEqual(mask.filter(Boolean).length, 12);
  assert.strictEqual(mask[8 * 32 + 12], 255);
  assert.strictEqual(mask[8 * 32 + 15], 0);
});
test("Model brush add/subtract preserves untouched coverage and source mask", () => {
  const source = new Uint8Array(64); source[0] = 117; source[27] = 200;
  const original = Array.from(source), add = tools.brushMask(source, 64, "add");
  tools.stampMaskCircle(add, source, 8, 8, 4, 4, 1.5, "add");
  assert.strictEqual(add[0], 117); assert.strictEqual(add[27], 255);
  const subtract = tools.brushMask(source, 64, "subtract");
  tools.stampMaskCircle(subtract, source, 8, 8, 4, 4, 1.5, "subtract");
  assert.strictEqual(subtract[0], 117); assert.strictEqual(subtract[27], 0);
  assert.deepStrictEqual(Array.from(source), original);
});
test("Intersect model brush retains only existing selection within painted pixels", () => {
  const source = new Uint8Array(64); source[27] = 121; source[0] = 255;
  const intersection = tools.brushMask(source, 64, "intersect");
  tools.stampMaskCircle(intersection, source, 8, 8, 4, 4, 1.5, "intersect");
  assert.strictEqual(intersection[27], 121); assert.strictEqual(intersection[28], 0); assert.strictEqual(intersection[0], 0);
  const unrestricted = tools.brushMask(null, 64, "subtract");
  tools.stampMaskCircle(unrestricted, null, 8, 8, 4, 4, 1.5, "subtract");
  assert.strictEqual(unrestricted[0], 255); assert.strictEqual(unrestricted[27], 0);
});
test("Model brush is bounded on rectangular textures and cannot spill into another row", () => {
  const mask = tools.brushMask(null, 64, "replace");
  tools.stampMaskCircle(mask, null, 16, 4, 0, 0, 1.5, "replace");
  assert.strictEqual(mask[0],255); assert.strictEqual(mask[15],0); assert.strictEqual(mask[48],0);
  assert.strictEqual(mask.filter(Boolean).length,1);
});
test("One-pixel model brush at a UV grid corner selects its sampled texel", () => {
  const mask = tools.brushMask(null, 64, "replace");
  tools.stampMaskCircle(mask, null, 8, 8, 4, 4, .5, "replace");
  assert.strictEqual(mask[36], 255); assert.strictEqual(mask.filter(Boolean).length, 1);
  const edge = tools.brushMask(null, 64, "replace");
  tools.stampMaskCircle(edge, null, 8, 8, 8, 8, .5, "replace");
  assert.strictEqual(edge[63],255); assert.strictEqual(edge.filter(Boolean).length,1);
});
test("UV border texels are selected even when their centres are outside the face", () => {
  const mask = new Uint8Array(8 * 4);
  tools.rasterTriangle(mask, 8, 4, [[0, 0], [1, 0], [0, 1]]);
  assert.strictEqual(mask[7], 255, "the slanted edge covers part of the top-right texel");
  assert.strictEqual(mask[13], 255, "the slanted edge covers part of the next border texel");
  assert.strictEqual(mask[14], 0, "a cell touching only the triangle corner is not extra padding");
  assert.strictEqual(mask[31], 0, "the unrelated atlas corner remains outside the selection");
});
test("subpixel UV detail still selects its partially covered texel", () => {
  const mask = new Uint8Array(8 * 4);
  tools.rasterTriangle(mask, 8, 4, [[1.05 / 8, 2.05 / 4], [1.4 / 8, 2.05 / 4], [1.05 / 8, 2.3 / 4]]);
  assert.strictEqual(mask[17], 255);
  assert.strictEqual(mask.filter(Boolean).length, 1);
});
test("a thin detail spanning a texel boundary selects both covered cells", () => {
  const mask = new Uint8Array(8 * 4);
  tools.rasterTriangle(mask, 8, 4, [[2.9 / 8, 1.05 / 4], [3.1 / 8, 1.05 / 4], [3 / 8, 1.3 / 4]]);
  assert.strictEqual(mask[10], 255); assert.strictEqual(mask[11], 255);
  assert.strictEqual(mask.filter(Boolean).length, 2);
});
test("grid-aligned UV islands do not gain a ring of unrelated atlas pixels", () => {
  const mask = new Uint8Array(8 * 4), points = [[2 / 8, 1 / 4], [4 / 8, 1 / 4], [2 / 8, 3 / 4], [4 / 8, 3 / 4]];
  tools.rasterTriangle(mask, 8, 4, [points[0], points[1], points[2]]);
  tools.rasterTriangle(mask, 8, 4, [points[2], points[1], points[3]]);
  assert.deepStrictEqual(Array.from(mask, (value, index) => value ? index : -1).filter(index => index >= 0), [10, 11, 18, 19]);
});
function clipToPixel(points, x, y) {
  for (const [axis, boundary, above] of [[0, x, true], [0, x + 1, false], [1, y, true], [1, y + 1, false]]) {
    const output = [];
    if (!points.length) return output;
    let previous = points[points.length - 1], wasInside = above ? previous[axis] >= boundary : previous[axis] <= boundary;
    for (const point of points) {
      const inside = above ? point[axis] >= boundary : point[axis] <= boundary;
      if (inside !== wasInside) {
        const fraction = (boundary - previous[axis]) / (point[axis] - previous[axis]);
        output.push([previous[0] + fraction * (point[0] - previous[0]), previous[1] + fraction * (point[1] - previous[1])]);
      }
      if (inside) output.push(point);
      previous = point; wasInside = inside;
    }
    points = output;
  }
  return points;
}
function polygonArea(points) {
  let area = 0;
  for (let index = 0; index < points.length; index++) { const next = points[(index + 1) % points.length]; area += points[index][0] * next[1] - points[index][1] * next[0]; }
  return Math.abs(area) / 2;
}
test("both windings and rectangular atlases match independent clipped-cell area coverage", () => {
  let seed = 0x1234abcd;
  function random() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 0x100000000; }
  for (let sample = 0; sample < 96; sample++) {
    const width = [7, 13, 31][sample % 3], height = [9, 17][sample % 2];
    const uv = Array.from({ length: 3 }, () => [random() * 1.6 - .3, random() * 1.6 - .3]);
    if (sample % 2) uv.reverse();
    const mask = new Uint8Array(width * height), points = uv.map(point => [point[0] * width, point[1] * height]);
    tools.rasterTriangle(mask, width, height, uv);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const area = polygonArea(clipToPixel(points, x, y));
      assert.strictEqual(Boolean(mask[y * width + x]), area > 1e-8, "clipped coverage at sample " + sample + ", cell " + x + "," + y);
    }
  }
});
test("large UV regions fill row spans while keeping the untouched corner clear", () => {
  const width = 4096, mask = new Uint8Array(width * width);
  tools.rasterTriangle(mask, width, width, [[0, 0], [1, 0], [0, 1]]);
  let covered = 0; for (const value of mask) if (value) covered++;
  assert.strictEqual(covered, width * (width + 1) / 2);
  assert.strictEqual(mask[mask.length - 1], 0);
});
process.stdout.write("PASS " + cases + " texture controller geometry cases\n");
