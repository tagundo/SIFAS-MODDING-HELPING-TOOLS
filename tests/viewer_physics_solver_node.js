/* Real production solver, independent geometric assertions (no DOM doubles). */
'use strict';
const assert = require('assert');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
global.window = { THREE };
require('../webtools/web/static/viewer-physics.js');
const V = THREE.Vector3;
function setup(options = {}) {
  const root = new THREE.Group(), bone = new THREE.Bone(), child = new THREE.Bone(), leg = new THREE.Bone();
  bone.userData.elichika_node = 0; child.userData.elichika_node = 1; leg.userData.elichika_node = 2;
  root.add(bone, leg); bone.add(child); child.position.set(options.length || 1, 0, 0); leg.position.set(.7, 0, 0);
  const bound = options.bound === undefined ? 90 : options.bound;
  const b = { id: '0:b', node: 0, sourceIndex: 0, name: options.surface ? 'Skirt1_Dyna' : 'Tail1_Dyna', kind: 'bone', enabled: true,
    values: { stiffnessForce: .02, dragForce: .6, lowRotationLimit: [-bound, -bound, -bound], highRotationLimit: [bound, bound, bound] },
    simulation: { childNode: 1, radius: options.boneRadius === undefined ? .05 : options.boneRadius, colliders: ['0:c'] } };
  const c = { id: '0:c', node: 2, sourceIndex: 0, name: 'LeftUpLeg', kind: 'collider', enabled: true, values: { radius: options.radius || .5, offset: [0, 0, 0] } };
  const components = [b, c];
  function start() { root.updateMatrixWorld(true); return window.ViewerPhysics.createSolver(root, { components }, r => r.values); }
  function resetPose() { bone.quaternion.identity(); root.updateMatrixWorld(true); }
  return { root, bone, child, leg, b, c, components, start, resetPose };
}
function pointSegment(p, a, b) { const line = b.clone().sub(a); const t = line.lengthSq() ? Math.max(0, Math.min(1, p.clone().sub(a).dot(line) / line.lengthSq())) : 0; return p.distanceTo(a.clone().addScaledVector(line, t)); }
{
  // Old push-then-renormalize returned x=1 inside radius .5. The solver must
  // preserve both rod length and full inflated-capsule clearance together.
  const s = setup(), solver = s.start(); solver.apply(0, { bones: true, colliders: true });
  const tip = s.child.getWorldPosition(new V()), origin = s.bone.getWorldPosition(new V());
  assert(Math.abs(tip.distanceTo(origin) - 1) < 1e-8);
  assert(pointSegment(s.leg.getWorldPosition(new V()), origin, tip) >= .55 - .001);
  assert(solver.getState().contacts > 0, 'paused enable resolves contacts');
  assert.equal(solver.getState().unresolvedBones, 0);
}
{
  const s = setup({ bound: 10 }), solver = s.start(); solver.apply(0, { bones: true, colliders: true });
  const e = new THREE.Euler().setFromQuaternion(s.bone.quaternion, 'YXZ');
  assert(Math.abs(e.x) <= Math.PI / 18 + 1e-7 && Math.abs(e.y) <= Math.PI / 18 + 1e-7 && Math.abs(e.z) <= Math.PI / 18 + 1e-7, 'iterations cannot accumulate past authored limits');
  assert(solver.getState().unresolvedBones > 0, 'infeasible authored limits are diagnosed');
}
{
  const s = setup(); s.b.simulation.colliders = []; const solver = s.start(); solver.apply(1 / 60, { bones: true, colliders: true });
  assert(s.bone.quaternion.angleTo(new THREE.Quaternion()) < 1e-8, 'an explicitly empty membership does not collide with arbitrary body components');
}
{
  // The leg crosses the cloth rod between render frames; both endpoint poses
  // are clear. Substeps must inspect the moving collider, including delta=0.
  const s = setup({ radius: .2, boneRadius: .02 }); s.leg.position.z = 1;
  const solver = s.start(); solver.apply(0, { bones: true, colliders: true });
  s.resetPose(); s.leg.position.z = -1; solver.apply(0, { bones: true, colliders: true });
  assert(solver.getState().substeps >= 20); assert(solver.getState().contacts > 0, 'swept collider path responds between frames');
  assert(s.child.getWorldPosition(new V()).z < -.05, 'the approaching leg pushes the skirt along its continuous path');
}
for (const blend of [1, .5]) {
  const s = setup({ length: .2, radius: .15, boneRadius: 0, surface: true }); s.leg.position.x = .8;
  const fixed = new THREE.Bone(); s.root.add(fixed);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([.8, -.4, -.4, .8, .4, -.4, .8, 0, .4], 3));
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0], 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([blend, 1 - blend, 0, 0, blend, 1 - blend, 0, 0, blend, 1 - blend, 0, 0], 4));
  geometry.setIndex([0, 1, 2]);
  const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial()); s.root.add(mesh); s.root.updateMatrixWorld(true);
  mesh.bind(new THREE.Skeleton([s.bone, fixed]));
  const outlineGroup = new THREE.Group(); outlineGroup.userData.viewerHelper = true;
  const outline = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial()); outline.skeleton = mesh.skeleton;
  outline.bindMatrix.copy(mesh.bindMatrix); outline.bindMatrixInverse.copy(mesh.bindMatrixInverse); outline.userData.elichika_node = 2;
  outlineGroup.add(outline); s.root.add(outlineGroup);
  const solver = s.start(); solver.apply(0, { bones: true, colliders: true });
  const vertices = [0, 1, 2].map(i => mesh.boneTransform(i, new V()).applyMatrix4(mesh.matrixWorld));
  const triangle = new THREE.Triangle(...vertices), center = s.leg.getWorldPosition(new V());
  const gap = triangle.closestPointToPoint(center, new V()).distanceTo(center) - .15;
  assert(gap >= -.002, `triangle interior with ${blend} skin weight remains inside leg by ${-gap}`);
  assert.equal(solver.getState().surfaceTriangles, 1, 'skinned outline helpers are not duplicate collision surfaces'); assert(solver.getState().contacts > 0);
}
{
  // Colliders disabled preserves the animated pose; no invented gravity moves
  // original components whose externalForce is exactly zero.
  const s = setup(), solver = s.start(); solver.apply(1 / 60, { bones: true, colliders: false });
  assert(s.bone.quaternion.angleTo(new THREE.Quaternion()) < 1e-8);
  s.bone.quaternion.setFromAxisAngle(new V(0, 1, 0), .3); solver.apply(1 / 60, { bones: false, colliders: true });
  assert(Math.abs(s.bone.quaternion.angleTo(new THREE.Quaternion()) - .3) < 1e-8);
}
console.log('PHYSICS_SOLVER_PASS: fixed length + radius, limits, membership, paused collision, moving sweep, exact blended triangle interiors, toggles');
{
  // Two roots share a cloth panel. Neither independent joint can fully clear
  // this sphere alone; the finished blended surface needs coupled relaxation.
  const s = setup({ surface: true, boneRadius: 0 }), second = new THREE.Bone(), end = new THREE.Bone();
  second.userData.elichika_node = 3; end.userData.elichika_node = 4; second.add(end); end.position.x = 1; s.root.add(second);
  s.b.values.lowRotationLimit = [0, 0, 0]; s.b.values.highRotationLimit = [0, 0, 60];
  const other = JSON.parse(JSON.stringify(s.b)); other.id = '0:b2'; other.node = 3; other.name = 'Skirt2_Dyna'; other.simulation.childNode = 4; s.components.push(other);
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute([1, -.05, 0, 1, .05, 0, 1, 0, .05], 3));
  g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0], 4));
  g.setAttribute('skinWeight', new THREE.Float32BufferAttribute([.5, .5, 0, 0, .5, .5, 0, 0, .5, .5, 0, 0], 4)); g.setIndex([0, 1, 2]);
  const mesh = new THREE.SkinnedMesh(g, new THREE.MeshBasicMaterial()); s.root.add(mesh); s.root.updateMatrixWorld(true); mesh.bind(new THREE.Skeleton([s.bone, second]));
  const solver = s.start(); solver.apply(0, { bones: true, colliders: true });
  const triangle = new THREE.Triangle(...[0, 1, 2].map(i => mesh.boneTransform(i, new V()).applyMatrix4(mesh.matrixWorld))), center = s.leg.getWorldPosition(new V());
  assert(triangle.closestPointToPoint(center, new V()).distanceTo(center) >= .5 - .002, 'two-joint blended triangle stays clear after the final neighboring joint');
  for (const bone of [s.bone, second]) { const e = new THREE.Euler().setFromQuaternion(bone.quaternion, 'YXZ'); assert(e.z >= -Math.PI / 3 - 1e-7 && e.z <= 1e-7); }
}
{
  const s = setup({ length: .2, radius: .15, boneRadius: 0, surface: true }); s.leg.position.x = .8;
  const fixed = new THREE.Bone(); s.root.add(fixed);
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute([.8, -.4, -.4, .8, .4, -.4, .8, 0, .4], 3));
  g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0], 4));
  g.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4)); g.setIndex([0, 1, 2]);
  const mesh = new THREE.SkinnedMesh(g, new THREE.MeshBasicMaterial()); s.root.add(mesh); s.root.updateMatrixWorld(true); mesh.bind(new THREE.Skeleton([s.bone, fixed]));
  const solver = s.start(); solver.apply(0, { bones: true, colliders: true }); assert(solver.getState().contacts > 0);
  const first = solver.getState().geometryRevision;
  g.setIndex([]); s.resetPose(); solver.apply(0, { bones: true, colliders: true });
  assert(solver.getState().geometryRevision > first); assert.equal(solver.getState().surfaceTriangles, 0); assert(s.bone.quaternion.angleTo(new THREE.Quaternion()) < 1e-8, 'deleted cloth cannot create phantom collisions');
  g.setIndex([0, 1, 2]); g.attributes.skinWeight.copyArray(new Float32Array([0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0])); g.attributes.skinWeight.needsUpdate = true;
  s.resetPose(); solver.apply(0, { bones: true, colliders: true });
  assert.equal(solver.getState().surfaceSupports, 0, 'live weight reassignment rebuilds collision membership');
  mesh.visible = false; s.resetPose(); solver.apply(0, { bones: true, colliders: true }); assert.equal(solver.getState().surfaceTriangles, 0);
}
console.log('PHYSICS_COUPLED_AND_EDIT_INVALIDATION_PASS');
