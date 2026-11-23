/* Unity 2018.4 Rotation/PositionConstraint evaluation (GL 3.12 libunity.so
   ConstraintManager job 0x71b2d4) and its MV Studio scene adapter. */
'use strict';
const assert = require('node:assert/strict');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

global.window = { THREE };
require('../webtools/web/static/viewer-constraints.js');
const { create, reference: U } = window.ViewerConstraints;

const close = (actual, expected, tolerance, message) => {
  assert.equal(actual.length, expected.length, message);
  actual.forEach((value, index) => assert(Math.abs(value - expected[index]) <= tolerance,
    `${message}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`));
};
const sameRotation = (actual, expected, degrees, message) => {
  const dot = Math.abs(actual.reduce((sum, value, index) => sum + value * expected[index], 0));
  const angle = 2 * Math.acos(Math.min(1, dot)) * 180 / Math.PI;
  assert(angle <= degrees, `${message}: ${angle} degrees apart`);
};
const S = Math.SQRT1_2;

// Quaternion.Euler applies Z, then X, then Y (Unity degrees).
close(U.euler([90, 0, 0]), [S, 0, 0, S], 1e-12, 'Euler X');
close(U.euler([0, 90, 0]), [0, S, 0, S], 1e-12, 'Euler Y');
close(U.euler([0, 0, 90]), [0, 0, S, S], 1e-12, 'Euler Z');
close(U.euler([30, 40, 50]), U.quatMul(U.quatMul(U.euler([0, 40, 0]), U.euler([30, 0, 0])), U.euler([0, 0, 50])), 1e-12, 'ZXY order');
close(U.rotate(U.euler([0, 90, 0]), [1, 0, 0]), [0, 0, -1], 1e-12, 'Y quarter turn');
for (const angles of [[10, 20, 30], [-80, 170, -120], [45, -45, 0], [0, 0, 179]]) {
  close(U.toEuler(U.euler(angles)), angles, 1e-9, 'Euler round trip');
}
sameRotation(U.euler(U.toEuler(U.euler([90, 30, 10]))), U.euler([90, 30, 10]), 1e-6, 'gimbal pole keeps the rotation');

// A flat Unity-space hierarchy for solve(): nodes carry Unity local TRS.
const node = (p, r, parent = null) => ({ p, r, s: [1, 1, 1], parent });
const local = (item) => item;
const parent = node([0, 1, 0], U.euler([0, 90, 0]));
const position = (overrides = {}) => ({ kind: 'position', atRest: [0, 0, 1], offset: [.5, 0, 0], weight: .5, axes: [true, true, true], ...overrides });
const source = (p, weight = 1, r = [0, 0, 0, 1]) => ({ position: p, rotation: r, weight });
const current = { p: [9, 8, 7], r: U.euler([1, 2, 3]) };

// Source (2,1,0) is (0,0,2) in the parent; + offset, then half-way from rest.
close(U.solve(position(), [source([2, 1, 0])], current, parent, local).position, [.25, 0, 1.5], 1e-12, 'position lerp');
close(U.solve(position({ weight: 2 }), [source([2, 1, 0])], current, parent, local).position, [.5, 0, 2], 1e-12, 'weight clamps to 1');
close(U.solve(position({ weight: -1 }), [source([2, 1, 0])], current, parent, local).position, [0, 0, 1], 1e-12, 'weight clamps to 0');
close(U.solve(position({ axes: [true, false, true] }), [source([2, 1, 0])], current, parent, local).position, [.25, 8, 1.5], 1e-12, 'masked axis keeps the current value');
close(U.solve(position({ weight: 1 }), [source([2, 1, 0], .5)], current, parent, local).position, [.5, 0, 2], 1e-12, 'one source weight is normalized');
close(U.solve(position({ weight: 1, offset: [0, 0, 0] }), [source([2, 1, 0], 1), source([2, 1, 4], 3)], current, parent, local).position,
  [-3, 0, 2], 1e-12, 'weights are divided by their sum');
close(U.solve(position({ axes: [false, false, false] }), [source([2, 1, 0], 0)], current, parent, local).position, [0, 0, 1], 0, 'zero weight is at rest on every axis');
close(U.solve(position(), [], current, parent, local).position, [0, 0, 1], 0, 'no valid source is at rest');
close(U.solve(position({ weight: 1, offset: [0, 0, 0] }), [source([2, 1, 0])], current, null, local).position, [2, 1, 0], 1e-12, 'no parent: world is local');
const scaled = { ...parent, s: [2, 4, 1] };
close(U.solve(position({ weight: 1, offset: [0, 0, 0] }), [source([2, 3, 0])], current, scaled, local).position, [0, .5, 2], 1e-12, 'parent scale divides');

// Rotation: into the parent's space, * Euler(offset), nlerp from Euler(rest).
const rotation = (overrides = {}) => ({ kind: 'rotation', atRest: [0, 0, 0], offset: [0, 0, 0], weight: .5, axes: [true, true, true], ...overrides });
const sourceWorld = U.quatMul(U.euler([0, 90, 0]), U.euler([30, 0, 0]));
sameRotation(U.solve(rotation(), [source([0, 0, 0], 1, sourceWorld)], current, parent, local).rotation, U.euler([15, 0, 0]), 1e-9, 'half of 30 degrees');
sameRotation(U.solve(rotation({ weight: 1, offset: [0, 0, 90] }), [source([0, 0, 0], 1, sourceWorld)], current, parent, local).rotation,
  U.quatMul(U.euler([30, 0, 0]), U.euler([0, 0, 90])), 1e-9, 'offset multiplies on the right');
sameRotation(U.solve(rotation({ weight: 1 }), [source([0, 0, 0], 1, sourceWorld.map((v) => -v))], current, parent, local).rotation,
  U.euler([30, 0, 0]), 1e-9, 'antipodal source quaternion');
sameRotation(U.solve(rotation({ atRest: [0, 0, 40] }), [source([0, 0, 0], 0, sourceWorld)], current, parent, local).rotation,
  U.euler([0, 0, 40]), 1e-9, 'zero weight is Euler(at rest)');
const pair = [source([0, 0, 0], 1, U.euler([0, 0, 0])), source([0, 0, 0], 1, U.euler([60, 0, 0]))];
sameRotation(U.solve(rotation({ weight: 1 }), pair, current, null, local).rotation, U.euler([30, 0, 0]), 1e-9, 'first source whole, then nlerp by share');
sameRotation(U.solve(rotation({ weight: 1, axes: [true, false, false] }), [source([0, 0, 0], 1, U.euler([30, 50, 70]))], current, null, local).rotation,
  U.euler([30, 2, 3]), 1e-9, 'per-axis Euler ZXY selection');

// Real rigs: Unity's Activate stored at-rest/offset so the bind pose is a
// fixed point for every weight (12007 member h+, 12036 member 0c%, Android).
const bind = [
  { name: '12007 LeftSkirtB_Root_Dyna <- SkirtA1_Dyna', kind: 'rotation', weight: .5,
    parent: [[0, .896229029, .004076191], [.060084678, .060084678, -.704549432, .704549432]],
    source: [[0, .941880907, .084782051], [-.109111307, .109111307, .698637827, .698637827]],
    atRest: [32.620723724365234, -40.81444549560547, 143.5959014892578], offset: [-32.62073516845703, 13.312352180480957, -36.404109954833984],
    bind: [-.2356911450624466, -.35457998514175415, .8850963711738586, .18795524537563324] },
  { name: '12036 LeftShoulderPartsB_Root_Dyna <- LeftArmRoll', kind: 'rotation', weight: .5,
    parent: [[-.069635099, 1.321583516, -.007393919], [.002105522, -.039154049, .053571292, .997794093]],
    source: [[-.195755043, 1.203783572, -.013341336], [.009088003, -.003885694, .377738342, .925859897]],
    atRest: [-50.605796813964844, -81.878662109375, 86.73902130126953], offset: [-88.14356231689453, -35.06109619140625, 35.439430236816406],
    bind: [-.6415033340454102, -.20892465114593506, .26537907123565674, .6887655258178711] },
  { name: '12036 LeftCoatA_Root_Dyna <- LeftArm', kind: 'position', weight: .699999988079071,
    parent: [[0, 1.131362201, .015770785], [-.059744981, -.059744981, -.704578397, .704578397]],
    source: [[-.122294392, 1.275681369, -.011895866], [.009088003, -.003885694, .377738342, .925859897]],
    atRest: [-.12524409592151642, -.10756108909845352, -.08064904063940048], offset: [.021673128008842468, .014733336865901947, -.0776779055595398],
    bind: [-.12524409592151642, -.10756108909845352, -.08064904063940048] },
];
for (const row of bind) {
  const owner = node(row.parent[0], row.parent[1]);
  const result = U.solve({ kind: row.kind, atRest: row.atRest, offset: row.offset, weight: row.weight, axes: [true, true, true] },
    [source(row.source[0], 1, row.source[1])], current, owner, local);
  if (row.kind === 'rotation') sameRotation(result.rotation, row.bind, 2e-3, row.name);
  else close(result.position, row.bind, 2e-6, row.name);
  // Away from the bind pose the weight decides how far the target follows.
  const swung = U.quatMul(U.euler([0, 0, 40]), row.source[1]);
  const moved = U.solve({ kind: row.kind, atRest: row.atRest, offset: row.offset, weight: row.weight, axes: [true, true, true] },
    [source([row.source[0][0] + .1, row.source[0][1], row.source[0][2]], 1, swung)], current, owner, local);
  if (row.kind === 'rotation') assert.throws(() => sameRotation(moved.rotation, row.bind, 1, row.name), /degrees apart/);
  else close(U.rotate(U.quatMul([0, 0, 0, 1], row.parent[1]), moved.position.map((v, i) => v - row.bind[i])),
    [.1 * row.weight, 0, 0], 1e-6, `${row.name} follows ${row.weight} of the source move`);
}

// Scene adapter: glTF space mirrors X; nodes are addressed by elichika_node.
function sceneNode(id, unityPosition, unityRotation, parentObject) {
  const object = new THREE.Object3D();
  object.userData.elichika_node = id;
  object.position.set(-unityPosition[0], unityPosition[1], unityPosition[2]);
  object.quaternion.set(unityRotation[0], -unityRotation[1], -unityRotation[2], unityRotation[3]);
  parentObject.add(object);
  return object;
}
const toUnityRotation = (q) => [q.x, -q.y, -q.z, q.w];
const root = new THREE.Group();
const hips = sceneNode(1, [0, 1, 0], U.euler([0, 90, 0]), root);
const target = sceneNode(2, [0, 0, 1], [0, 0, 0, 1], hips);
const arm = sceneNode(3, [2, 1, 0], [0, 0, 0, 1], root);
const skirtRoot = sceneNode(4, [0, 0, 0], [0, 0, 0, 1], hips);
const skirt = sceneNode(5, [0, 0, 0], [0, 0, 0, 1], root);
const ignored = sceneNode(6, [0, 0, 0], [0, 0, 0, 1], root);
const catalog = { constraints: [
  { id: 'p', kind: 'position', node: 2, name: 'LeftCoatA_Root_Dyna', enabled: true, activeInHierarchy: true, constraintActive: true,
    weight: .5, atRest: [0, 0, 1], offset: [.5, 0, 0], axes: [true, true, true], sources: [{ node: 3, weight: 1 }, { node: 99, weight: 5 }] },
  { id: 'r', kind: 'rotation', node: 4, name: 'LeftSkirtB_Root_Dyna', enabled: true, activeInHierarchy: true, constraintActive: true,
    weight: 1, atRest: [0, 0, 0], offset: [0, 0, 0], axes: [true, true, true], sources: [{ node: 5, weight: 1 }] },
  { id: 'off', kind: 'rotation', node: 6, enabled: true, activeInHierarchy: true, constraintActive: false,
    weight: 1, atRest: [0, 0, 0], offset: [0, 0, 0], axes: [true, true, true], sources: [{ node: 5, weight: 1 }] },
] };
assert.equal(create(root, { constraints: [] }), null);
assert.equal(create(root, { constraints: [{ ...catalog.constraints[0], enabled: false }] }), null, 'disabled Behaviour');
assert.equal(create(root, { constraints: [{ ...catalog.constraints[0], activeInHierarchy: false }] }), null, 'inactive GameObject');
assert.equal(create(root, { constraints: [{ ...catalog.constraints[0], sources: [] }] }), null, 'no sources: not registered');
const solver = create(root, catalog);
assert.deepEqual(solver.getState().targets.map((row) => row.id), ['p', 'r'], 'constraintActive false is not evaluated');

solver.apply(null, () => ({}));
close(target.position.toArray(), [-.25, 0, 1.5], 1e-12, 'unresolved source dropped; result mirrored into the glTF space');
sameRotation(toUnityRotation(skirtRoot.quaternion), U.euler([0, -90, 0]), 1e-9, 'rest skirt source in parent space');
assert.equal(solver.getState().evaluated, 2);

// A swing-bone source reads the simulated local pose (this frame's Update job
// output in the game order) unless the Animator owns that property this frame.
const swingLocal = new THREE.Quaternion(); const swingUnity = U.euler([0, 0, 50]);
swingLocal.set(swingUnity[0], -swingUnity[1], -swingUnity[2], swingUnity[3]);
const simulated = new Map([[5, { position: null, quaternion: swingLocal }]]);
solver.apply(simulated, () => ({}));
sameRotation(toUnityRotation(skirtRoot.quaternion), U.quatMul(U.euler([0, -90, 0]), swingUnity), 1e-9, 'simulated swing result');
solver.apply(simulated, () => ({ 5: { quaternion: true } }));
sameRotation(toUnityRotation(skirtRoot.quaternion), U.euler([0, -90, 0]), 1e-9, 'animated property wins');
close(skirt.quaternion.toArray(), [0, 0, 0, 1], 0, 'the source node itself is not written');

// Every constraint reads its inputs before any result is written back.
const chained = create(root, { constraints: [
  { ...catalog.constraints[1], id: 'a', node: 5, sources: [{ node: 3, weight: 1 }] },
  { ...catalog.constraints[1], id: 'b', node: 4, sources: [{ node: 5, weight: 1 }] }] });
arm.quaternion.set(0, 0, Math.sin(Math.PI / 8), Math.cos(Math.PI / 8));
skirt.quaternion.identity();
chained.apply(null, null);
sameRotation(toUnityRotation(skirtRoot.quaternion), U.euler([0, -90, 0]), 1e-9, 'b read a\'s pre-solve pose');
chained.restorePose();
close(skirt.quaternion.toArray(), [0, 0, 0, 1], 0, 'restorePose returns targets to the loaded pose');

solver.restorePose();
close(target.position.toArray(), [-0, 0, 1], 0, 'restorePose');
close(skirtRoot.quaternion.toArray(), [0, 0, 0, 1], 0, 'restorePose rotation');
solver.dispose();
console.log('viewer constraints ok');
