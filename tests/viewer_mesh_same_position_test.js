/* "Move vertices at the same position together": the position groups (exact
 * float32 values or within SAME_POSITION_ULPS steps on every axis), the partner
 * sets an edit writes, and the free-drag rule that keeps a group coincident. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const context = { window: { THREE } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-tools.js'), 'utf8'), context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-runtime.js'), 'utf8'), context);
const { buildPositionGroups: build, samePositionPartners: partners, samePositionUlps } = context.window.ViewerMeshTools;
const { planeDragPlan, planeDragValues, skinMatrix } = context.window.ViewerMeshRuntime;
const plain = value => JSON.parse(JSON.stringify(value));
const groupsOf = (positions, tolerance) => plain(build(positions.length, v => positions[v], tolerance).groups);

// float32 neighbours: k steps up from value (positive values only here).
const f32 = new Float32Array(1), i32 = new Int32Array(f32.buffer);
function step(value, k) { f32[0] = value; i32[0] += k; return f32[0]; }
function ulps(a, b) { const o = x => { f32[0] = x; const bits = i32[0]; return bits < 0 ? -(bits & 0x7fffffff) : bits; }; return Math.abs(o(a) - o(b)); }

assert.equal(samePositionUlps, 4, 'the census-chosen tolerance is four float32 steps per axis');

// 1. Exact seams, signed zero, several groups and ascending order.
const exact = [[0, 1, 2], [0.5, 0.25, 0], [0, 1, 2], [-0, 0.25, 0], [0.5, 0.25, -0], [3, 3, 3], [0, 1, 2]];
assert.deepStrictEqual(groupsOf(exact, 0), [[0, 2, 6], [1, 4]], 'exact equality');
assert.deepStrictEqual(groupsOf([[0, 0.25, 0], [-0, 0.25, -0]], 0), [[0, 1]], '-0 and +0 are the same position');
assert.deepStrictEqual(groupsOf([[1, 2, 3]], 0), [], 'a single vertex is never a group');
assert.deepStrictEqual(groupsOf([], 4), [], 'an empty mesh has no groups');

// 2. Float32 steps: within 4 steps on every axis join, 5 do not. Values are
// compared as the float32 the mesh stores: a double below one step rounds.
const base = 0.0234375, high = 1.4375;
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 1), high, -0.5]]), [[0, 1]], 'one step (real Hair seam noise) joins');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 4), step(high, 4), -0.5]]), [[0, 1]], 'four steps on two axes join');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 5), high, -0.5]]), [], 'five steps stay apart');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 1), high, -0.5]], 0), [], 'the exact rule keeps one step apart');
assert.deepStrictEqual(groupsOf([[base, high, 0], [base + 1e-12, high, 0]], 0), [[0, 1]], 'doubles closer than half a float32 step are one stored value');
// The smallest distinct pair in the census: two vertices of one triangle
// 1.2e-6 apart (81 float32 steps at their magnitude). Never merged.
const near = 0.1220703125, far = near + 1.2073619305464415e-6;
assert(ulps(near, far) >= 80);
assert.deepStrictEqual(groupsOf([[near, 0.5, 0.5], [far, 0.5, 0.5]]), [], 'distinct sliver-edge vertices stay apart');
// Negative values and the step across zero.
assert.deepStrictEqual(groupsOf([[-base, 1, 1], [-step(base, 3), 1, 1]]), [[0, 1]], 'negative coordinates count steps the same way');
assert.deepStrictEqual(groupsOf([[1e-45, 1, 1], [-1e-45, 1, 1]]), [[0, 1]], 'the smallest values either side of zero are two steps apart');
// Chains are one group (every link is within the tolerance).
assert.deepStrictEqual(groupsOf([[step(base, 8), 0, 0], [base, 0, 0], [step(base, 4), 0, 0]]), [[0, 1, 2]], 'a chain of near copies is one group');

// 3. The spatial hash equals a brute-force comparison, including values on
// both sides of a cell edge (cells are 256 float32 steps wide).
function ordered32(x) { f32[0] = x; const bits = i32[0]; return bits < 0 ? -(bits & 0x7fffffff) : bits; }
for (const sign of [1, -1]) {
  let edge = sign * 0.3; while (((ordered32(edge) % 256) + 256) % 256 !== 255) edge = step(edge, 1);
  for (const [a, b] of [[0, 1], [-3, 1], [0, 4], [-1, 4]]) {
    const positions = [[step(edge, a), 0.5, 0.5], [step(edge, b), 0.5, 0.5]], gap = ulps(positions[0][0], positions[1][0]);
    assert.deepStrictEqual(groupsOf(positions), gap <= 4 ? [[0, 1]] : [], 'across a cell edge: ' + [sign, a, b]);
    assert.deepStrictEqual(groupsOf([positions[1], positions[0]]), gap <= 4 ? [[0, 1]] : [], 'either order: ' + [sign, a, b]);
  }
  const corner = [step(edge, 0), step(edge, 0), step(edge, 0)];
  assert.deepStrictEqual(groupsOf([corner, corner.map(x => step(x, 2))]), [[0, 1]], 'across a cell corner on all three axes');
}
function brute(positions, tolerance) {
  const parent = positions.map((_, i) => i), root = v => parent[v] === v ? v : (parent[v] = root(parent[v]));
  for (let a = 0; a < positions.length; a++) for (let b = a + 1; b < positions.length; b++)
    if (positions[a].every((x, axis) => ulps(x, positions[b][axis]) <= tolerance)) { const ra = root(a), rb = root(b); if (ra !== rb) parent[Math.max(ra, rb)] = Math.min(ra, rb); }
  const groups = new Map(); positions.forEach((_, v) => { const r = root(v); groups.set(r, (groups.get(r) || []).concat([v])); });
  return Array.from(groups.values()).filter(g => g.length > 1);
}
let seed = 12345; const random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
for (const tolerance of [0, 1, 4, 9]) {
  for (let round = 0; round < 6; round++) {
    const positions = [];
    for (let i = 0; i < 160; i++) {
      if (positions.length && random() < 0.55) { const from = positions[Math.floor(random() * positions.length)]; positions.push(from.map(x => step(x, Math.floor(random() * 13) - 6))); }
      else positions.push([0, 0, 0].map(() => Math.fround((random() - 0.5) * (random() < 0.3 ? 0.001 : 3))));
    }
    assert.deepStrictEqual(groupsOf(positions, tolerance), brute(positions, tolerance), 'spatial hash = brute force, tolerance ' + tolerance + ' round ' + round);
  }
}

// 4. Partners: the chosen vertices' other group members, each tied to the
// group's lowest chosen vertex; ungrouped and out-of-range picks are ignored.
const index = build(exact.length, v => exact[v], 0);
let result = partners(index, new Set([6, 5]));
assert.deepStrictEqual(plain(result.partners), [0, 2], 'partners of a selected seam vertex');
assert.deepStrictEqual(plain(Array.from(result.seeds.entries())), [[0, 6], [2, 6]], 'partners copy their seed');
assert.deepStrictEqual(plain(result.groups), [{ members: [0, 2, 6], chosen: [6] }]);
result = partners(index, [2, 0, 4, 99, -1, 'x']);
assert.deepStrictEqual(plain(result.partners), [6, 1], 'chosen members are never partners; groups follow the lowest chosen vertex');
assert.deepStrictEqual(plain(Array.from(result.seeds.entries())), [[6, 0], [1, 4]]);
assert.deepStrictEqual(plain(result.groups), [{ members: [0, 2, 6], chosen: [0, 2] }, { members: [1, 4], chosen: [4] }]);
assert.deepStrictEqual(plain(partners(index, []).partners), []);

// 5. Grouping follows the current positions: a group moved together stays a
// group; a vertex moved alone (option off) leaves it.
const current = exact.map(p => p.slice());
[0, 2, 6].forEach(v => { current[v] = current[v].map((x, axis) => x + [0.025, 0, -0.5][axis]); });
assert.deepStrictEqual(groupsOf(current, 4)[0], [0, 2, 6], 'moved together, still one point');
current[2][1] += 0.01;
assert.deepStrictEqual(groupsOf(current, 4)[0], [0, 6], 'a vertex torn away earlier is no longer grouped');

// 6. Free camera-plane drag. A real skinned mesh: vertices 0 and 1 share a
// position but not their weights (277 of 113,025 real groups do), vertex 2 is
// alone. Each vertex's own inverse skin map gives the seam copies different
// deltas (the seam opens); the plan gives the group one delta.
const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute([0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 1, 0, 0], 3));
geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0], 4));
geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 0.3, 0.7, 0, 0, 1, 0, 0, 0], 4));
geometry.setIndex([0, 1, 2]);
const bone0 = new THREE.Bone(), bone1 = new THREE.Bone(); bone1.position.set(0, 1, 0); bone1.rotation.set(0.4, 0.2, -0.3); bone1.scale.set(1.3, 0.8, 1);
const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial()), skeleton = new THREE.Skeleton([bone0, bone1], [new THREE.Matrix4(), new THREE.Matrix4()]);
mesh.bind(skeleton, new THREE.Matrix4()); const root = new THREE.Group(); root.add(mesh); root.add(bone0); root.add(bone1); root.updateMatrixWorld(true);
const linearOf = vertex => new THREE.Matrix3().setFromMatrix4(new THREE.Matrix4().copy(mesh.matrixWorld).multiply(skinMatrix(mesh, vertex)));
const sources = [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [1, 0, 0]], positionOf = v => sources[v].slice(), delta = new THREE.Vector3(0.02, -0.035, 0.011);
const together = { partners: [1], groups: [{ members: [0, 1], chosen: [0] }] };
let plan = planeDragPlan(new Set([0, 2]), together, 0, positionOf, linearOf), values = plain(planeDragValues(plan, delta));
assert.deepStrictEqual(Object.keys(values), ['0', '1', '2'], 'the partner moves with the selection');
assert.deepStrictEqual(values[1], values[0], 'the seam copy takes exactly the seed delta (bit-identical)');
const seedWorld = new THREE.Vector3().fromArray(values[0]).sub(new THREE.Vector3().fromArray(sources[0])).applyMatrix3(linearOf(0));
assert(seedWorld.distanceTo(delta) < 1e-12, 'the picked vertex follows the pointer exactly');
const own = v => new THREE.Vector3().fromArray(sources[v]).add(delta.clone().applyMatrix3(linearOf(v).invert())).toArray();
assert.deepStrictEqual(values[2], own(2), 'an ungrouped vertex keeps its own inverse skin map');
assert(Math.hypot(...own(0).map((x, axis) => x - own(1)[axis])) > 1e-3, 'per-vertex maps would have opened this seam');
// The pointer picked the partner side: it leads, the selected vertex copies it.
plan = planeDragPlan(new Set([0, 1]), { partners: [], groups: [{ members: [0, 1], chosen: [0, 1] }] }, 1, positionOf, linearOf); values = plain(planeDragValues(plan, delta));
assert.deepStrictEqual(values[0], values[1]); assert.deepStrictEqual(values[1], own(1), 'the picked member is the seed');
// A seed with a singular map hands the group to the next selected member;
// a group with no invertible chosen member does not move (as before).
const singular = vertex => vertex === 0 ? new THREE.Matrix3().set(0, 0, 0, 0, 1, 0, 0, 0, 1) : linearOf(vertex);
plan = planeDragPlan(new Set([0, 1]), { partners: [], groups: [{ members: [0, 1], chosen: [0, 1] }] }, 0, positionOf, singular); values = plain(planeDragValues(plan, delta));
assert.deepStrictEqual(values[0], own(1)); assert.deepStrictEqual(values[1], own(1));
plan = planeDragPlan(new Set([0]), together, 0, positionOf, singular);
assert.deepStrictEqual(plain(planeDragValues(plan, delta)), {}, 'no invertible member: the group stays');
assert.deepStrictEqual(Object.keys(plan.positions), [], 'and is not part of the drag');

console.log('PASS: exact and four-step float32 groups, brute-force spatial hash, partners and seeds, current-position regrouping, shared free-drag delta');
