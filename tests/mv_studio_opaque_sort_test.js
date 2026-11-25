"use strict";

// Unity draws each opaque queue front to back by renderer bounds centre; the
// stage renderers take over the draw positions three.js's own opaque order
// gives them, in that order, and every other mesh keeps its position.
const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-material.js");
require("../webtools/web/static/mv-studio-opaque-sort.js");

const scene = new T.Scene();
const camera = new T.PerspectiveCamera(60, 16 / 9, .1, 1000);
camera.position.set(0, 1.5, 10);
camera.lookAt(0, 10, -50);
const geometry = new T.PlaneGeometry();
const programs = new Map();
let nextProgram = 1;

function surface(name, {program, position = [0, 0, 0], transparent = false, depthWrite = true, renderOrder = 0} = {}) {
  const material = new T.MeshBasicMaterial({transparent, depthWrite});
  material.name = name;
  if (program !== undefined) programs.set(material, {id: program});
  const node = new T.Mesh(geometry, material);
  node.name = name;
  node.position.fromArray(position);
  node.renderOrder = renderOrder;
  node.frustumCulled = false;
  scene.add(node);
  return node;
}

// 10120: the dome (bounds centre y 40.34) and the stage ground (y 39.10, its
// sky submesh among nine others) share the sky vertices. Three.js would draw
// the dome first: its program was linked first.
const dome = surface("dome", {program: 1});
const stageSky = surface("stage sky", {program: 2});
const stageFloor = surface("stage floor", {program: 2});
const unrelated = surface("unrelated", {program: 1, position: [0, 0, -5]});
const cutout = surface("cutout", {program: 3});
const glass = surface("glass", {program: 3, transparent: true});
const noDepth = surface("no depth", {program: 3, depthWrite: false});
const later = surface("later order", {program: 3, renderOrder: 1});
const groundCenter = new T.Vector3(0.0022125244140625, 39.09544372558594, -0.35707855224609375);
const entries = [
  {node: dome, material: dome.material, center: new T.Vector3(0.0022125244140625, 40.33617401123047, -1.64202880859375), queue: 2000},
  {node: stageSky, material: stageSky.material, center: groundCenter, queue: 2000},
  {node: stageFloor, material: stageFloor.material, center: groundCenter, queue: 2000},
  // A nearer AlphaTest queue renderer still follows every Geometry queue renderer.
  {node: cutout, material: cutout.material, center: new T.Vector3(0, 1, 9), queue: 2450},
  {node: glass, material: glass.material, center: new T.Vector3(0, 1, 9), queue: 2000},
  {node: noDepth, material: noDepth.material, center: new T.Vector3(0, 1, 9), queue: 2000},
  {node: later, material: later.material, center: new T.Vector3(0, 1, 9), queue: 2000},
];
const records = [{stageMaterial: {opaqueSortEntries: () => entries}}, {}];

let comparator = null, order;
const viewProjection = new T.Matrix4(), frustum = new T.Frustum();
// three.js r128 painterSortStable and WebGLRenderer.projectObject.
function painter(a, b) {
  return a.groupOrder !== b.groupOrder ? a.groupOrder - b.groupOrder :
    a.renderOrder !== b.renderOrder ? a.renderOrder - b.renderOrder :
    a.program !== b.program ? a.program.id - b.program.id :
    a.material.id !== b.material.id ? a.material.id - b.material.id :
    a.z !== b.z ? a.z - b.z : a.id - b.id;
}
const renderer = {
  properties: {get: material => ({program: programs.get(material)})},
  setOpaqueSort(sort) { comparator = sort; },
  render(source, view) {
    source.updateMatrixWorld();
    view.updateMatrixWorld();
    viewProjection.multiplyMatrices(view.projectionMatrix, view.matrixWorldInverse);
    frustum.setFromProjectionMatrix(viewProjection);
    const items = [];
    source.traverseVisible((object) => {
      if (!object.isMesh || object.material.transparent || object.frustumCulled && !frustum.intersectsObject(object)) return;
      items.push({object, id: object.id, groupOrder: 0, renderOrder: object.renderOrder, material: object.material,
        program: programs.get(object.material) || {id: -1},
        z: new T.Vector3().setFromMatrixPosition(object.matrixWorld).applyMatrix4(viewProjection).z});
    });
    items.sort(comparator || painter);
    order = items.map(({object}) => object.name);
  },
};

const sorter = MVStudioOpaqueSort.create(T, renderer);
assert.equal(MVStudioOpaqueSort.create(T, {}), null, "a renderer without setOpaqueSort keeps its own order");
const draw = (view) => {
  const sorting = sorter.begin(scene, view, records);
  try { renderer.render(scene, view); } finally { if (sorting) sorter.end(); }
  return sorting;
};

renderer.render(scene, camera);
const stock = ["dome", "unrelated", "stage sky", "stage floor", "cutout", "no depth", "later order"];
assert.deepEqual(order, stock);
assert.equal(draw(camera), true);
assert.deepEqual(order, ["stage sky", "unrelated", "stage floor", "dome", "cutout", "no depth", "later order"],
  "the nearer stage bounds draw first, so the coplanar dome draws last; other meshes keep their places");
assert.equal(comparator, null, "the native order applies to one render only");

// A camera above both centres reaches the dome's bounds first.
const crane = camera.clone();
crane.position.set(0, 60, 0);
crane.lookAt(0, 0, -20);
crane.updateMatrixWorld();
assert.equal(draw(crane), false, "the native order already matches three.js's order there");
assert.deepEqual(order.filter(name => ["dome", "stage sky", "stage floor"].includes(name)),
  ["dome", "stage sky", "stage floor"], "the stage's submeshes keep their order at one distance");

// Only the native material in use takes part.
const replaced = stageSky.material;
stageSky.material = new T.MeshBasicMaterial();
assert.equal(draw(camera), true);
assert.ok(order.indexOf("dome") > order.indexOf("stage floor"));
stageSky.material = replaced;

// A hidden or culled participant gives up its place.
dome.visible = false;
assert.equal(draw(camera), false, "one participant has no order to change");
assert.deepEqual(order, stock.filter(name => name !== "dome"));
dome.visible = true;
dome.frustumCulled = true;
dome.position.set(0, 0, 50);
draw(camera);
assert.ok(!order.includes("dome"));
dome.position.set(0, 0, 0);
dome.frustumCulled = false;

// An orthographic camera sorts by view depth.
const orthographic = new T.OrthographicCamera(-50, 50, 50, -50, .1, 1000);
orthographic.position.set(0, 0, 100);
orthographic.updateMatrixWorld();
draw(orthographic);
assert.ok(order.indexOf("dome") > order.indexOf("stage sky"), "the dome centre is farther along the view axis");
// MVStudioStageMaterial offers its native opaque materials with their bounds centre and queue.
(async () => {
  const root = new T.Group(), map = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
  const surface = (opaqueSort) => {
    const node = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial({map}));
    node.geometry.userData.mvStageMaterial = {shader: "general", colors: {_AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1]},
      uvTransform: [1, 1, 0, 0], cull: 2, opaqueSort};
    root.add(node);
    return node;
  };
  const sky = surface({queue: 2000, center: [0, 39.1, -.36]});
  surface({queue: 3000, center: [0, 0, 0]});
  surface({queue: 2000, center: [0, "1", 0]});
  surface(undefined);
  const controller = await MVStudioStageMaterial.apply(T, root, {getDependency: async () => map});
  const offered = controller.opaqueSortEntries();
  assert.equal(offered.length, 1, "only an opaque queue with a finite centre");
  assert.deepEqual([offered[0].node, offered[0].material, offered[0].queue, ...offered[0].center.toArray()],
    [sky, sky.material, 2000, 0, 39.1, -.36]);
  sky.material = new T.MeshBasicMaterial();
  assert.equal(controller.opaqueSortEntries().length, 0, "a replaced material leaves the native order");
  controller.dispose();
  console.log("Opaque stage renderers draw front to back within each queue.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
