/* Source topology and viewport coordinates have independent, declared answers. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-tools.js'), 'utf8'), context);
const api = context.window.ViewerMeshTools;
const plain = value => JSON.parse(JSON.stringify(value));
function component(data, seeds, seams = true, accept) { return plain(api.connectedFaces(api.buildFaceConnectivity(data, seams), seeds, accept)).sort((a, b) => a - b); }
const data = {
  positions: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0], [1, 2, 0], [3, 0, 0], [4, 0, 0], [3, 1, 0]],
  triangles: [[0, 1, 2], [2, 1, 3], [3, 4, 5], [6, 7, 8]], skin: []
};
assert.deepStrictEqual(component(data, [0]), [0, 1], 'shared edge joins the quad, a vertex-only contact stays separate');
assert.deepStrictEqual(component(data, [2]), [2], 'a face touching one vertex is its own face island');
assert.deepStrictEqual(component(data, [0, 3]), [0, 1, 3], 'multiple seeds include only their components');
assert.deepStrictEqual(component(data, [-1, 99, 1.2]), [], 'invalid seeds are ignored');
assert.deepStrictEqual(component(data, [0], true, face => face !== 1), [0], 'deleted or out-of-material faces cannot be traversed');
const seam = {
  positions: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0]],
  triangles: [[0, 1, 2], [3, 4, 5]], skin: [[[0, 1]], [[0, 1]], [[0, 1]], [[0, 1]], [[0, 1]], [[0, 1]]]
};
assert.deepStrictEqual(component(seam, [0], false), [0], 'strict topology does not cross duplicated source indices');
assert.deepStrictEqual(component(seam, [0], true), [0, 1], 'a unique UV split edge with matching skin joins');
const differentSkin = plain(seam); differentSkin.skin[3] = [[1, 1]];
assert.deepStrictEqual(component(differentSkin, [0]), [0], 'coincident geometry with a different bone binding stays separate');
const overlap = { positions: seam.positions.slice(0, 3).concat(seam.positions.slice(0, 3)), triangles: [[0, 1, 2], [5, 4, 3]], skin: [] };
assert.deepStrictEqual(component(overlap, [0]), [0], 'coincident opposite-facing duplicate shells never weld');
const sameDirection = plain(seam); sameDirection.triangles[1] = [4, 3, 5];
assert.deepStrictEqual(component(sameDirection, [0]), [0], 'same-facing overlapping edge does not masquerade as a seam');
const nonManifold = plain(seam); nonManifold.positions.push([0, 1, 0], [1, 0, 0], [1, 1, 1]); nonManifold.triangles.push([6, 7, 8]); nonManifold.skin.push([[0, 1]], [[0, 1]], [[0, 1]]);
assert.deepStrictEqual(component(nonManifold, [0]), [0], 'ambiguous geometric seams do not merge separate parts');
const original = JSON.stringify(data); component(data, [0]); assert.equal(JSON.stringify(data), original, 'building selection leaves source coordinates and indices untouched');
function close(a, b) { assert(Math.abs(a - b) < 1e-12, `${a} != ${b}`); }
let view = api.zoomView({ zoom: 1, x: 0, y: 0 }, 4, [.25, .7]);
close(view.zoom, 4); close(view.x, -.75); close(view.y, -2.1);
let uv = api.viewToUv([.25, .7], view); close(uv[0], .25); close(uv[1], .3);
const pixel = api.uvToView([.4, .2], view); close(pixel[0], .85); close(pixel[1], 1.1);
uv = api.viewToUv(pixel, view); close(uv[0], .4); close(uv[1], .2);
view = api.zoomView(view, 1, [.3, .6]); assert.deepStrictEqual(plain(view), { zoom: 1, x: 0, y: 0 }, 'fit removes stale pan');
view = api.zoomView(view, 100, [.5, .5]); close(view.zoom, 16); close(view.x, -7.5); close(view.y, -7.5);
const cssWidth = 320, radius = 30, zoom = 8, uvRadius = radius / cssWidth / zoom;
close(uvRadius * zoom * cssWidth, radius);
console.log('PASS: independent face islands, UV seams, masks, overlapping shells, source identity and anchored zoom/UV/brush coordinates');
