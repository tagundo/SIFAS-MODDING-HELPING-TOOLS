"use strict";
/* LiveCoreLossyScale.LateUpdate: localScale = localScale / lossyScale + offsetScale, so the
   tagged node's local scale is 1 / parent lossy scale + offset after every animation step. */
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lossy-scale.js");
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);

const root = new T.Group(), joint = new T.Group(), iris = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial()), plain = new T.Group();
root.add(joint); joint.add(iris, plain);
joint.scale.set(3, 1, 1);
iris.userData.mvLossyScaleOffset = [.3, .3, .3];
assert.equal(MVStudioLossyScale.create(T, new T.Group()), null);
const lossy = MVStudioLossyScale.create(T, root);
assert.deepEqual(lossy.nodes, [iris]);
lossy.apply();
close(iris.scale.x, 1 / 3 + .3, "x"); close(iris.scale.y, 1.3, "y"); close(iris.scale.z, 1.3, "z");
iris.updateWorldMatrix(true, false);
const world = new T.Vector3().setFromMatrixScale(iris.matrixWorld);
close(world.x, 1 + .3 * 3, "world size grows with the parent only through the offset");
// An animated parent scale and an animated own scale give the same result.
joint.scale.set(2, 2, 2); iris.scale.set(5, 5, 5);
lossy.apply();
close(iris.scale.x, .5 + .3, "re-derived every frame");
assert.deepEqual(plain.scale.toArray(), [1, 1, 1], "untagged nodes keep their scale");
lossy.dispose();
assert.deepEqual(iris.scale.toArray(), [1, 1, 1], "dispose restores the authored scale");
console.log("PASS: LiveCoreLossyScale local = 1 / parent lossy scale + offsetScale");
