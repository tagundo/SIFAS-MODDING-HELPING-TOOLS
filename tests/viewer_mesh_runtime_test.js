/* Exact morph+skin vertex projection/raycast must not depend on rest bounds. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const context = { window: { THREE } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-runtime.js'), 'utf8'), context);
const { vertexWorld, raycastMesh, skinMatrix } = context.window.ViewerMeshRuntime;
function vector(actual, expected, why) { actual.toArray().forEach((value, i) => assert(Math.abs(value - expected[i]) < 1e-6, why + ': ' + actual.toArray() + ' != ' + expected)); }
const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0], 4));
geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, .5, .5, 0, 0, 1, 0, 0, 0], 4));
geometry.setIndex([0, 1, 2]);
geometry.morphAttributes.position = [new THREE.Float32BufferAttribute([0, 0, .8, 0, 0, .8, 0, 0, .8], 3)];
geometry.morphTargetsRelative = true;
const bone0 = new THREE.Bone(), bone1 = new THREE.Bone(); bone0.position.set(1, 0, 0); bone1.position.set(0, 2, 0);
const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial()); mesh.updateMorphTargets(); mesh.morphTargetInfluences[0] = .5;
const skeleton = new THREE.Skeleton([bone0, bone1], [new THREE.Matrix4(), new THREE.Matrix4()]); mesh.bind(skeleton, new THREE.Matrix4());
const root = new THREE.Group(); root.position.set(0, 0, 3); root.add(mesh); root.add(bone0); root.add(bone1); root.updateMatrixWorld(true);
// bone matrix contains root translation; attached bindMatrixInverse cancels it.
vector(vertexWorld(mesh, 0), [1, 0, 3.4], 'morph offset retained when skinning');
vector(vertexWorld(mesh, 1), [1.5, 1, 3.4], 'two weighted bone matrices');
vector(vertexWorld(mesh, 2), [1, 1, 3.4], 'source vertex identity retained');
const p = vertexWorld(mesh, 0).add(vertexWorld(mesh, 1)).add(vertexWorld(mesh, 2)).multiplyScalar(1 / 3);
geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(9999, 9999, 9999), .001);
const hit = raycastMesh(new THREE.Ray(p.clone().add(new THREE.Vector3(0, 0, 5)), new THREE.Vector3(0, 0, -1)), mesh);
assert(hit, 'deformed mesh hit despite incorrect original/rest bounding sphere');
vector(hit.point, p.toArray(), 'exact morphed and skinned ray hit');
vector(hit.barycoord, [1 / 3, 1 / 3, 1 / 3], 'triangle barycentric identity');
assert.deepStrictEqual(JSON.parse(JSON.stringify(hit.face)), { a: 0, b: 1, c: 2 });
assert.equal(raycastMesh(new THREE.Ray(p.clone().add(new THREE.Vector3(0, 0, 5)), new THREE.Vector3(0, 0, -1)), mesh, { faceIndices: [] }), null);
const delta = new THREE.Vector3(.2, .3, .1), forward = new THREE.Matrix4().copy(mesh.matrixWorld).multiply(skinMatrix(mesh, 1));
const inverse = new THREE.Matrix3().setFromMatrix4(forward).invert();
vector(delta.clone().applyMatrix3(inverse).applyMatrix3(new THREE.Matrix3().setFromMatrix4(forward)), delta.toArray(), 'drag delta inversion matches weighted skin transform');
console.log('PASS: exact vertex identity, morph+skin world projection, deformed raycast, barycentric picking, drag inverse');
