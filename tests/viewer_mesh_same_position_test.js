/* "Move vertices at the same position together": the position groups (current
 * positions within SAME_POSITION_TOLERANCE model units on every axis), the
 * partner sets an edit writes, and the free-drag rule that keeps a group
 * coincident. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const context = { window: { THREE } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-tools.js'), 'utf8'), context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-runtime.js'), 'utf8'), context);
const { buildPositionGroups: build, samePositionPartners: partners, samePositionTolerance } = context.window.ViewerMeshTools;
const { planeDragPlan, planeDragValues, skinMatrix } = context.window.ViewerMeshRuntime;
const plain = value => JSON.parse(JSON.stringify(value));
const groupsOf = (positions, tolerance) => plain(build(positions.length, v => positions[v], tolerance).groups);

// float32 neighbours: k steps up from value (positive values only here).
const f32 = new Float32Array(1), i32 = new Int32Array(f32.buffer);
function step(value, k) { f32[0] = value; i32[0] += k; return f32[0]; }
function ulps(a, b) { const o = x => { f32[0] = x; const bits = i32[0]; return bits < 0 ? -(bits & 0x7fffffff) : bits; }; return Math.abs(o(a) - o(b)); }

assert.equal(samePositionTolerance, 5e-7, 'the census-chosen tolerance is 5e-7 model units per axis');
const T = samePositionTolerance;

// 1. Exact seams, signed zero, several groups and ascending order.
const exact = [[0, 1, 2], [0.5, 0.25, 0], [0, 1, 2], [-0, 0.25, 0], [0.5, 0.25, -0], [3, 3, 3], [0, 1, 2]];
assert.deepStrictEqual(groupsOf(exact, 0), [[0, 2, 6], [1, 4]], 'exact equality');
assert.deepStrictEqual(groupsOf([[0, 0.25, 0], [-0, 0.25, -0]], 0), [[0, 1]], '-0 and +0 are the same position');
assert.deepStrictEqual(groupsOf([[0, 0.25, 0], [1e-300, 0.25, 0]], 0), [], 'the exact rule keeps any difference apart');
assert.deepStrictEqual(groupsOf([[1, 2, 3]], 0), [], 'a single vertex is never a group');
assert.deepStrictEqual(groupsOf([], T), [], 'an empty mesh has no groups');
assert.deepStrictEqual(groupsOf(exact), [[0, 2, 6], [1, 4]], 'the default rule keeps exact groups');

// 2. Absolute tolerance: within 5e-7 on every axis join, beyond it stay apart,
// at any magnitude (float32 steps shrink towards zero, model units do not).
const base = 0.0234375, high = 1.4375;
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 1), high, -0.5]]), [[0, 1]], 'one float32 step joins');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [base + 4.9e-7, high - 4.9e-7, -0.5]]), [[0, 1]], '4.9e-7 on two axes joins');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [base + 5.1e-7, high, -0.5]]), [], '5.1e-7 stays apart');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [base, high, -0.5 - 5.1e-7]]), [], 'on any axis');
assert.deepStrictEqual(groupsOf([[base, high, -0.5], [step(base, 1), high, -0.5]], 0), [], 'the exact rule keeps one step apart');
assert.deepStrictEqual(groupsOf([[0, 0.5, 0.5], [T, 0.5, 0.5]]), [[0, 1]], 'a gap of exactly the tolerance joins');
// Seams at and across zero. Real Hair copies of member 1 (Android): X
// 2.78e-9 and 6.41e-9 (3.6e-9 apart, ten million float32 steps), Z 2.7e-9
// apart near -0.0017 (23 steps). Four-step rules missed them.
const hairX = [2.7830977522569356e-09, 6.410225239505962e-09], hairZ = [-0.00167236162815243, -0.001672358950600028];
assert(ulps(hairX[0], hairX[1]) > 1e7 && ulps(hairZ[0], hairZ[1]) === 23);
assert.deepStrictEqual(groupsOf([[hairX[0], 1.3842971324920654, -0.10343645513057709], [hairX[1], 1.3842971324920654, -0.10343645513057709]]), [[0, 1]], 'real Hair seam 3.6e-9 apart at x≈0');
assert.deepStrictEqual(groupsOf([[-0.07500281929969788, 1.440385103225708, hairZ[0]], [-0.07500281929969788, 1.440385103225708, hairZ[1]]]), [[0, 1]], 'real Hair seam 23 steps apart');
assert.deepStrictEqual(groupsOf([[1e-9, 0.5, 0.1], [-1e-9, 0.5, 0.1]]), [[0, 1]], '+1e-9 and -1e-9 join across zero');
assert.deepStrictEqual(groupsOf([[0, 0.5, 0.1], [3.6e-9, 0.5, 0.1]]), [[0, 1]], '0 and 3.6e-9 join');
assert.deepStrictEqual(groupsOf([[0, 0.5, 0.1], [1e-30, 0.5, 0.1], [-1e-45, 0.5, 0.1]]), [[0, 1, 2]], '0, 1e-30 and -1e-45 join');
assert.deepStrictEqual(groupsOf([[2.5e-7, 0.5, 0.1], [-2.6e-7, 0.5, 0.1]]), [], 'but 5.1e-7 across zero stays apart');
// The smallest distinct pairs in the census: two corners of one triangle,
// 1.207e-6 (Hat) and 1.28e-6 (Body) apart on their widest axis. Never merged.
const near = 0.1220703125;
assert.deepStrictEqual(groupsOf([[near, 0.5, 0.5], [near + 1.2069940567016602e-06, 0.5, 0.5]]), [], 'distinct sliver-edge vertices stay apart');
assert.deepStrictEqual(groupsOf([[near, 0.5, 0.5], [near + 1.2814998626708984e-06, 0.5 + 1e-7, 0.5]]), [], 'and the other sliver');
// Every pair the four-step rule grouped below 2 is still grouped.
let seed = 12345; const random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
for (let i = 0; i < 400; i++) {
  const sign = random() < 0.5 ? -1 : 1, value = Math.fround(sign * 2 * Math.pow(random(), 6)), k = 1 + Math.floor(random() * 4), other = step(value, sign * k);
  if (!value || !Number.isFinite(other) || Math.abs(other) >= 2) continue;
  assert.deepStrictEqual(groupsOf([[value, 0.5, 0.5], [other, 0.5, 0.5]]), [[0, 1]], 'four steps below 2: ' + value + ' ' + other);
}
// Chains are one group (every link is within the tolerance).
assert.deepStrictEqual(groupsOf([[base + 8e-7, 0, 0], [base, 0, 0], [base + 4e-7, 0, 0]]), [[0, 1, 2]], 'a chain of near copies is one group');

// 3. Moved together, still together: a shared move keeps the absolute gap,
// across zero and across powers of two (float32 steps double or halve there).
function translate(positions, members, delta) { return positions.map((p, v) => members.includes(v) ? p.map((x, axis) => x + delta[axis]) : p.slice()); }
{
  const at = [[0.26, 0.5, 0.1], [step(0.26, 3), 0.5, 0.1]];
  assert.deepStrictEqual(groupsOf(translate(at, [0, 1], [-0.02, 0, 0])), [[0, 1]], 'a 3-step pair at 0.26 moved by -0.02 together (now 6 steps)');
  const at75 = [[0.75, 0.5, 0.1], [step(0.75, 1), 0.5, 0.1]];
  assert.deepStrictEqual(groupsOf(translate(at75, [0, 1], [-0.7, 0, 0])), [[0, 1]], 'a 1-step pair at 0.75 moved by -0.7 (now 16 steps)');
  assert.deepStrictEqual(groupsOf(translate(at75, [0, 1], [-0.75, 0, 0])), [[0, 1]], 'and onto zero');
  // Real member 207 Hair copies 645/1344: 4 steps at -0.086; Translate X +0.084716
  // made them 256 steps apart at -0.0013 and the four-step rule split them.
  const m207 = [[-0.08606104552745819, 1.4599024057388306, 0.013800970278680325], [-0.0860610157251358, 1.4599024057388306, 0.013800970278680325]];
  const moved = translate(m207, [0, 1], [0.084716, 0, 0]); assert(ulps(moved[0][0], moved[1][0]) >= 256);
  assert.deepStrictEqual(groupsOf(moved), [[0, 1]], 'the m207 Hair pair translated to -0.0013 is still one group');
  const index = build(moved.length, v => moved[v]); assert.deepStrictEqual(plain(partners(index, [0]).partners), [1], 'and the next nudge moves both');
}
// Random near groups and shared moves: the grouping never changes.
for (let round = 0; round < 40; round++) {
  const positions = [];
  for (let i = 0; i < 60; i++) {
    if (positions.length && random() < 0.5) { const from = positions[Math.floor(random() * positions.length)]; positions.push(from.map(x => x + (random() - 0.5) * 0.9 * T)); }
    else positions.push([0, 0, 0].map(() => Math.fround((random() - 0.5) * (random() < 0.3 ? 2e-5 : 3))));
  }
  const before = groupsOf(positions);
  // Move whole groups (and some ungrouped vertices) by one random delta each.
  let moved = positions;
  const loose = positions.map((_, v) => v).filter(v => !before.some(group => group.includes(v)));
  before.concat(loose.length ? [[loose[Math.floor(random() * loose.length)]]] : []).forEach(group => { const delta = [0, 0, 0].map(() => (random() - 0.5) * (random() < 0.5 ? 2 : 0.01)); moved = translate(moved, group, delta); });
  const after = groupsOf(moved), stillTogether = before.every(group => after.some(other => group.every(v => other.includes(v))));
  assert(stillTogether, 'groups moved together stay together, round ' + round);
}

// 4. The spatial hash equals a brute-force comparison, including values on
// both sides of a cell edge (cells are a power of two, 2^-19 by default,
// doubled until wider than the tolerance).
const CELL = 1 / 524288, cellFor = tolerance => { let cell = CELL; while (cell <= tolerance) cell *= 2; return cell; };
for (const sign of [1, -1]) {
  const edge = sign * 9830 * CELL;
  for (const [a, b] of [[-1e-7, 1e-7], [-4.9e-7, 0], [0, 4.99e-7], [-3e-7, 3e-7], [-2.6e-7, 2.6e-7], [-1e-12, 0]]) {
    const positions = [[edge + a, 0.5, 0.5], [edge + b, 0.5, 0.5]], gap = Math.abs(positions[0][0] - positions[1][0]);
    assert.deepStrictEqual(groupsOf(positions), gap <= T ? [[0, 1]] : [], 'across a cell edge: ' + [sign, a, b]);
    assert.deepStrictEqual(groupsOf([positions[1], positions[0]]), gap <= T ? [[0, 1]] : [], 'either order: ' + [sign, a, b]);
  }
  const corner = [edge, edge, edge];
  assert.deepStrictEqual(groupsOf([corner.map(x => x - 2e-7), corner.map(x => x + 2e-7)]), [[0, 1]], 'across a cell corner on all three axes');
}
assert.deepStrictEqual(groupsOf([[1e6, -1e6, 999999.99], [1e6, -1e6, 999999.99]]), [[0, 1]], 'very large coordinates still hash to one cell');
// Exact edge cases with a power-of-two tolerance: a neighbour exactly one
// tolerance away sits on the next cell's first value.
for (const k of [9830, -9830, 1]) {
  const edge = k * CELL, small = Math.pow(2, -22);
  assert.deepStrictEqual(groupsOf([[edge - small, 0.5, 0.5], [edge, 0.5, 0.5]], small), [[0, 1]], 'exactly one tolerance below a cell edge: ' + k);
  assert.deepStrictEqual(groupsOf([[edge, 0.5, 0.5], [edge - small, 0.5, 0.5]], small), [[0, 1]], 'either order: ' + k);
  assert.deepStrictEqual(groupsOf([[0.5, edge - small, edge], [0.5, edge, edge - small]], small), [[0, 1]], 'on the other axes: ' + k);
}
function brute(positions, tolerance) {
  const parent = positions.map((_, i) => i), root = v => parent[v] === v ? v : (parent[v] = root(parent[v]));
  for (let a = 0; a < positions.length; a++) for (let b = a + 1; b < positions.length; b++)
    if (positions[a].every((x, axis) => Math.abs(x - positions[b][axis]) <= tolerance)) { const ra = root(a), rb = root(b); if (ra !== rb) parent[Math.max(ra, rb)] = Math.min(ra, rb); }
  const groups = new Map(); positions.forEach((_, v) => { const r = root(v); groups.set(r, (groups.get(r) || []).concat([v])); });
  return Array.from(groups.values()).filter(g => g.length > 1);
}
for (const tolerance of [0, 1e-7, T, 4e-6, 5e-5, 1.5e-4]) {
  for (let round = 0; round < 6; round++) {
    const positions = [];
    for (let i = 0; i < 160; i++) {
      if (positions.length && random() < 0.55) { const from = positions[Math.floor(random() * positions.length)]; positions.push(from.map(x => random() < 0.3 ? x : x + (random() - 0.5) * 3 * tolerance)); }
      else positions.push([0, 0, 0].map(() => Math.fround((random() - 0.5) * (random() < 0.3 ? 0.001 : 3))));
      // Some values right at cell edges.
      if (random() < 0.1) positions[positions.length - 1][0] = Math.round(positions[positions.length - 1][0] / cellFor(tolerance)) * cellFor(tolerance) + (random() - 0.5) * 2 * tolerance;
    }
    assert.deepStrictEqual(groupsOf(positions, tolerance), brute(positions, tolerance), 'spatial hash = brute force, tolerance ' + tolerance + ' round ' + round);
  }
}

// 4b. Degenerate meshes stay linear: many copies at one point, dense clusters
// of near copies (a collapsed or shrunken part), a big group beside separate
// vertices of its cell, and separate components packed as tightly as the
// tolerance allows. Bounds are on counted work, not on time: `visits` counts
// bucket visits (a cell holds at most 4^3 buckets: their first vertices are
// more than the tolerance apart), `compares` member tests (only in buckets
// whose box is within the tolerance, stopping at the first match). The chain
// scan before cb3d612 took 2.3 s for 4,000 copies at one point and 56 s for a
// 7,555-vertex mesh plus 20,000 vertices collapsed onto the origin; cb3d612
// made 3.5 M compares for 3,000 copies beside 1,000 separate vertices and
// 12.5 M visits for 2,500 seam pairs on a 6e-7 lattice.
const cost = (positions, tolerance) => { const index = build(positions.length, v => positions[v], tolerance); return { compares: index.compares, visits: index.visits }; };
function bounded(positions, compares, visits, why, tolerance) {
  const n = positions.length, work = cost(positions, tolerance);
  assert(work.compares <= compares * n, why + ': ' + work.compares + ' compares for ' + n + ' vertices');
  assert(work.visits <= visits * n, why + ': ' + work.visits + ' bucket visits for ' + n + ' vertices');
}
const onePoint = Array.from({ length: 4000 }, () => [0.25, 1.5, -0.125]);
bounded(onePoint, 1, 1, '4000 copies at one point: one comparison and one bucket visit each'); bounded(onePoint, 1, 1, 'also with the exact rule', 0);
assert.deepStrictEqual(cost(onePoint), { compares: 3999, visits: 3999 }, 'every copy after the first visits the one bucket and matches its newest member');
assert.deepStrictEqual(groupsOf(onePoint).map(group => group.length), [4000]);
const line = Array.from({ length: 4000 }, (_, i) => [i * 1e-9, 0, 0]);
bounded(line, 1, 3, 'distinct vertices 1e-9 apart in vertex order');
assert.deepStrictEqual(groupsOf(line).map(group => group.length), [4000], 'one chain');
bounded(line.slice().sort(() => random() - 0.5), 8, 8, 'the same vertices shuffled');
bounded(Array.from({ length: 4000 }, () => [0.1 + random() * 1e-6, 0.2 + random() * 1e-6, 0.3 + random() * 1e-6]), 8, 8, '4000 vertices in a 1e-6 cube');
{
  const mesh = Array.from({ length: 7555 }, () => [random() - 0.5, random() * 1.7, random() - 0.5].map(Math.fround));
  const collapsed = mesh.concat(Array.from({ length: 20000 }, () => [0, 0, 0])), started = Date.now();
  const index = build(collapsed.length, v => collapsed[v]);
  assert(index.compares < 2 * collapsed.length && index.visits < 3 * collapsed.length, 'a mesh plus 20,000 vertices collapsed onto the origin: ' + [index.compares, index.visits]);
  assert.equal(index.groups.find(group => group.length === 20000)[0], 7555); assert(Date.now() - started < 2000);
}
// A big group of copies beside separate vertices of its cell (grids 1e-6 and
// 1.2e-6 apart, more than the tolerance): the bucket's box keeps the separate
// vertices from walking its members, in either insertion order.
const grid = (n, side, spacing, origin) => Array.from({ length: n }, (_, i) => [origin[0] + spacing * (1 + (i % side)), origin[1] + spacing * (1 + Math.floor(i / side) % side), origin[2] + spacing * (1 + Math.floor(i / side / side))]);
{
  const copies = Array.from({ length: 3000 }, () => [0.5, 0.5, 0.5]), separate = grid(1000, 10, 1e-6, [0.5, 0.5, 0.5]);
  bounded(copies.concat(separate), 1, 16, '3000 copies, then 1000 separate vertices beside them');
  bounded(separate.concat(copies), 1, 16, '1000 separate vertices, then 3000 copies');
  assert.deepStrictEqual(groupsOf(copies.concat(separate)).map(group => group.length), [3000], 'the separate vertices stay apart');
  const big = Array.from({ length: 20000 }, () => [1e-7, 1e-7, 1e-7]).concat(grid(8000, 20, 1.2e-6, [0, 0, 0]));
  bounded(big, 1, 16, '20,000 copies beside 8,000 separate vertices');
}
// Separate components packed as tightly as the tolerance allows: seam pairs on
// a 6e-7 lattice, the lattice alone, and a 20^3 grid 5.2e-7 apart (up to 4^3
// components per 2^-19 cell). At most 8 cells of 64 buckets per vertex: 512.
{
  const lattice = []; for (let x = 0; x < 50; x++) for (let y = 0; y < 50; y++) { lattice.push([x * 6e-7, y * 6e-7, 0.25]); lattice.push([x * 6e-7, y * 6e-7, 0.25]); }
  bounded(lattice, 1, 32, '2,500 seam pairs on a 6e-7 lattice');
  assert.equal(groupsOf(lattice).length, 2500, 'one group per lattice point');
  bounded(lattice.filter((_, i) => i % 2 === 0), 1, 32, '2,500 separate vertices 6e-7 apart');
  const packed = grid(8000, 20, 5.2e-7, [0.125, 0.25, 0.375]);
  bounded(packed, 1, 512, '8,000 separate vertices 5.2e-7 apart'); assert.deepStrictEqual(groupsOf(packed), []);
}
// Brute force on small degenerate sets. Clusters sit in two cells whose hashes
// collide (cells (-60,-1,59) and (-60,1,-59)), so their buckets share one
// list; exact copies, chains, cluster-joining vertices, outliers and cell
// edges mix. The cell is the base 2^-19, doubled until wider than the tolerance.
const hashOf = (x, y, z) => Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663) ^ Math.imul(z | 0, 83492791);
assert.equal(hashOf(-60, -1, 59), hashOf(-60, 1, -59), 'the two cells share a hash');
const inCell = (c, offset, cell) => c.map((k, axis) => (k + 0.5) * cell + offset[axis]);
for (let round = 0; round < 30; round++) {
  const tolerance = [T, 0, 4e-6][round % 3], cell = cellFor(tolerance), spread = Math.max(tolerance, 1e-7), positions = [];
  const centres = [inCell([-60, -1, 59], [0, 0, 0], cell), inCell([-60, 1, -59], [0, 0, 0], cell), inCell([-60, -1, 59], [0.3 * cell, -0.25 * cell, 0], cell), [0.5, 0.5, 0.5]];
  for (let i = 0; i < 220; i++) {
    const centre = centres[Math.floor(random() * centres.length)], kind = random();
    if (kind < 0.35) positions.push(centre.slice());
    else if (kind < 0.7) positions.push(centre.map(x => x + (random() - 0.5) * 2.4 * spread));
    else if (kind < 0.9 && positions.length) { const from = positions[Math.floor(random() * positions.length)]; positions.push(from.map(x => x + (random() - 0.5) * 1.9 * spread)); }
    else positions.push(centre.map(x => x + (random() - 0.5) * 0.9 * cell));
  }
  assert.deepStrictEqual(groupsOf(positions, tolerance), brute(positions, tolerance), 'degenerate clusters = brute force, round ' + round);
}
{
  // Bucket merging in one 2^-19 cell (3.8 tolerances wide): u1 and u2 are 1.8
  // tolerances apart (two buckets), w is another bucket of the cell inserted
  // between them, c joins u1 and u2 (one bucket whose box spans both from then
  // on), and later vertices near u1, u2 or w only: -0.6 reaches the merged
  // box only through u1's part of it.
  const corner = [-60, -1, 59].map(k => k * CELL), x = dx => corner[0] + (0.65 + dx) * T, y = corner[1] + 1.9 * T, z = corner[2] + 1.9 * T;
  const positions = [[x(0), y, z], [x(0), y - 1.8 * T, z], [x(1.8), y, z], [x(0.9), y, z], [x(-0.6), y, z], [x(2.5), y, z], [x(0), y - 1.3 * T, z], inCell([-60, 1, -59], [0, 0, 0], CELL), [x(3), y, z]];
  positions.forEach((p, v) => { if (v !== 7) assert.deepStrictEqual(p.map(value => Math.floor(value / CELL)), [-60, -1, 59], 'vertex ' + v + ' is in the cell'); });
  assert.deepStrictEqual(groupsOf(positions), brute(positions, T));
  assert.deepStrictEqual(groupsOf(positions), [[0, 2, 3, 4, 5, 8], [1, 6]]);
}

// 5. Partners: the chosen vertices' other group members, each tied to the
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

// 6. Grouping follows the current positions: a group moved together stays a
// group; a vertex moved alone (option off) leaves it.
const current = exact.map(p => p.slice());
[0, 2, 6].forEach(v => { current[v] = current[v].map((x, axis) => x + [0.025, 0, -0.5][axis]); });
assert.deepStrictEqual(groupsOf(current)[0], [0, 2, 6], 'moved together, still one point');
current[2][1] += 0.01;
assert.deepStrictEqual(groupsOf(current)[0], [0, 6], 'a vertex torn away earlier is no longer grouped');

// 7. Free camera-plane drag. A real skinned mesh: vertices 0 and 1 share a
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

console.log('PASS: exact and 5e-7 absolute groups (zero crossings, real near-zero seams, moved groups stay), brute-force spatial hash, partners and seeds, current-position regrouping, shared free-drag delta');
