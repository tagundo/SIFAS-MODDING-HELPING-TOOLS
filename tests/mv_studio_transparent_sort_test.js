"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-transparent-sort.js");

const scene = new T.Scene();
const camera = new T.PerspectiveCamera(60, 1, .1, 100);
const orthographic = new T.OrthographicCamera(-10, 10, 10, -10, .1, 100);
const geometry = new T.PlaneGeometry();
const material = new T.MeshBasicMaterial({transparent: true});

function mesh(name, z, queue = 3000) {
  const object = new T.Mesh(geometry, material);
  object.position.z = z;
  object.renderOrder = queue;
  object.name = name;
  scene.add(object);
  return object;
}

const distantPivot = mesh("distant pivot", -8);
const unsupported = mesh("unsupported", -6);
const distantBounds = mesh("distant bounds", -4);
const laterQueue = mesh("later queue", -9, 3001);
const sortEntries = [
  {node: distantBounds, anchor: distantBounds, center: new T.Vector3(8, 0, 0), queue: 3000},
  {node: distantPivot, anchor: distantPivot, center: new T.Vector3(), queue: 3000},
];
const records = [{stageOverlay: {sortEntries: () => sortEntries}}];
const viewProjection = new T.Matrix4();
const frustum = new T.Frustum();
let order, comparator, fail = false;
const renderer = {
  setTransparentSort(sort) { comparator = sort; },
  render(source, currentCamera) {
    if (fail) throw new Error("render failed");
    source.updateMatrixWorld();
    currentCamera.updateMatrixWorld();
    viewProjection.multiplyMatrices(currentCamera.projectionMatrix, currentCamera.matrixWorldInverse);
    frustum.setFromProjectionMatrix(viewProjection);
    const items = [];
    source.traverseVisible((object) => {
      if (!object.isMesh || !object.layers.test(currentCamera.layers) ||
          object.frustumCulled && !frustum.intersectsObject(object)) return;
      items.push({object, id: object.id, groupOrder: 0, renderOrder: object.renderOrder,
        z: new T.Vector3().setFromMatrixPosition(object.matrixWorld).applyMatrix4(viewProjection).z});
    });
    items.sort(comparator || ((a, b) => a.renderOrder - b.renderOrder || b.z - a.z || a.id - b.id));
    order = items.map(({object}) => object.name);
  },
};
const sorter = MVStudioTransparentSort.create(T, renderer);
const stock = [distantPivot.name, unsupported.name, distantBounds.name, laterQueue.name];
const native = [distantBounds.name, unsupported.name, distantPivot.name, laterQueue.name];

renderer.render(scene, camera);
assert.deepEqual(order, stock);
sorter.draw(scene, camera, records);
assert.deepEqual(order, native);
assert.equal(comparator, null);

camera.position.x = 3;
sorter.draw(scene, camera, records);
assert.deepEqual(order, stock);
camera.position.x = 0;
sorter.draw(scene, orthographic, records);
assert.deepEqual(order, stock);

distantPivot.position.z = -5;
unsupported.position.z = -4;
distantBounds.position.z = -3;
sortEntries[0].center.x = 4;
sorter.draw(scene, camera, records);
assert.deepEqual(order, native, "equal authored distances preserve source order");
distantBounds.position.x = 100;
sorter.draw(scene, camera, records);
assert.deepEqual(order, [distantPivot.name, unsupported.name, laterQueue.name]);

distantBounds.position.x = 0;
fail = true;
assert.throws(() => sorter.draw(scene, camera, records), /render failed/);
assert.equal(comparator, null);
fail = false;
sorter.draw(scene, camera, []);
assert.deepEqual(order, stock);
console.log("Native transparent bounds ordering, camera changes, legacy draw slots and cleanup passed.");
