"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-axis-billboard.js");

function near(current, expected, range, label) {
  assert.ok(Math.abs(current - expected) <= range, `${label}: expected ${expected}, got ${current}`);
}

function quaternionNear(current, expected, range, label) {
  const sign = current.dot(expected) < 0 ? -1 : 1;
  for (const axis of ["x", "y", "z", "w"]) near(sign * current[axis], expected[axis], range, `${label} ${axis}`);
}

// Direct port of LLAS AxisBillboard.RunAxisBillboardY (0x27bfc14) in Unity space:
// up = transform.up, d = camera - position, right = normalize(Cross(up, d)),
// forward = normalize(Cross(right, up)), rotation = matrix columns (right, up, forward).
function unityAxisBillboardY(up, position, camera) {
  const d = camera.clone().sub(position);
  const right = new T.Vector3().crossVectors(up, d).normalize();
  const forward = new T.Vector3().crossVectors(right, up).normalize();
  return new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(right, up, forward));
}

// The exporter mirrors Unity X: positions (-x, y, z) and rotations (x, -y, -z, w).
const mirrorPoint = v => new T.Vector3(-v.x, v.y, v.z);
const mirrorRotation = q => new T.Quaternion(q.x, -q.y, -q.z, q.w);

let seed = 7;
function random() {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
}
const randomVector = scale => new T.Vector3(random() - .5, random() - .5, random() - .5).multiplyScalar(scale);
const randomRotation = () => new T.Quaternion(random() - .5, random() - .5, random() - .5, random() - .5).normalize();

// Unity world placement: position from the localToWorld matrix, rotation as
// the product of local rotations (Transform.rotation ignores parent scale).
function unityWorld(chain) {
  const rotation = new T.Quaternion(), matrix = new T.Matrix4(), local = new T.Matrix4();
  for (const link of chain) {
    matrix.multiply(local.compose(link.position, link.rotation, link.scale ?? new T.Vector3(1, 1, 1)));
    rotation.multiply(link.rotation);
  }
  return { rotation, position: new T.Vector3().setFromMatrixPosition(matrix) };
}

function scene(chain) {
  const root = new T.Group();
  let parent = root, node = null;
  for (const link of chain) {
    node = new T.Group();
    node.position.copy(mirrorPoint(link.position));
    node.quaternion.copy(mirrorRotation(link.rotation));
    if (link.scale) node.scale.copy(link.scale);
    node.matrixAutoUpdate = false;
    node.updateMatrix();
    parent.add(node);
    parent = node;
  }
  node.userData.mvAxisBillboard = 1;
  const mesh = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial());
  node.add(mesh);
  return { root, node, mesh };
}

function worldQuaternion(node) {
  return MVStudioAxisBillboard.worldRotation(node, new T.Quaternion());
}

// Random parent chains (rotated, translated, scaled), rest rotations and cameras.
for (let sample = 0; sample < 200; sample++) {
  const chain = [
    { position: randomVector(20), rotation: randomRotation() },
    { position: randomVector(4), rotation: randomRotation(), scale: new T.Vector3(1 + random(), 1 + random(), 1 + random()) },
    { position: randomVector(2), rotation: randomRotation() },
  ];
  const { root, node, mesh } = scene(chain);
  const billboard = MVStudioAxisBillboard.create(T, root);
  assert.equal(billboard.nodes.length, 1);
  assert.equal(mesh.frustumCulled, false, "AxisBillboard.Start enlarges the bounds, so the turned mesh is never culled");
  const world = unityWorld(chain);
  const up = new T.Vector3(0, 1, 0).applyQuaternion(world.rotation);
  for (let view = 0; view < 3; view++) {
    const cameraPosition = randomVector(40);
    const camera = new T.PerspectiveCamera();
    camera.position.copy(mirrorPoint(cameraPosition));
    billboard.apply(camera);
    const expected = mirrorRotation(unityAxisBillboardY(up, world.position, cameraPosition));
    quaternionNear(worldQuaternion(node), expected, 1e-9, `sample ${sample} view ${view}`);
    // The turn keeps the authored up axis and the parent-local position.
    const editorUp = new T.Vector3(0, 1, 0).applyQuaternion(worldQuaternion(node));
    const mirroredUp = mirrorPoint(up);
    for (const axis of ["x", "y", "z"]) near(editorUp[axis], mirroredUp[axis], 1e-9, `up ${axis}`);
    node.updateMatrixWorld(true);
    const forward = new T.Vector3(0, 0, 1).applyQuaternion(worldQuaternion(node));
    const toCamera = camera.position.clone().sub(new T.Vector3().setFromMatrixPosition(node.matrixWorld));
    assert.ok(forward.dot(toCamera) >= -1e-9, "the forward axis faces the camera side");
  }
}

// Recorded game frames (12035, CI runtime dump): the bilcone world rotation equals
// RunAxisBillboardY from its own up axis toward the previous frame's main camera.
for (const [name, position, rotation, camera] of [
  ["litC_06_bilcone 6.029", [-4.04255438, 1.50878227, -7.55924034], [-0.0239163656, 0.176362246, 0.13223362, 0.975109518], [10.0788155, 3.35774875, 30.1553516]],
  ["litB_10_bilcone 62.289", [-13.6299782, 10.1103153, -4.55852699], [0.0811374635, 0.049693197, -0.848904788, 0.519911587], [-3.81060028, 0.0199999996, 18.9101543]],
  ["litB_04_bilcone 91.425", [12.2977982, 10.126195, -8.22057438], [0.115093902, -0.0777361616, 0.820660114, 0.554281175], [-1.4806602, 0.72990495, 4.25710249]],
]) {
  const recorded = new T.Quaternion().fromArray(rotation);
  const up = new T.Vector3(0, 1, 0).applyQuaternion(recorded);
  quaternionNear(unityAxisBillboardY(up, new T.Vector3().fromArray(position), new T.Vector3().fromArray(camera)),
    recorded, 5e-4, name);
  // The mirrored preview formula gives the mirrored recorded rotation.
  const preview = new T.Quaternion();
  assert.ok(MVStudioAxisBillboard.axisRotation(mirrorPoint(up),
    mirrorPoint(new T.Vector3().fromArray(camera)).sub(mirrorPoint(new T.Vector3().fromArray(position))),
    preview, MVStudioAxisBillboard.scratch(T)));
  quaternionNear(preview, mirrorRotation(recorded), 5e-4, `${name} mirrored`);
}

// The up axis comes from the parent's current rotation and the authored local
// rotation, so animating the parent between draws needs no history.
{
  const chain = [{ position: new T.Vector3(1, 2, 3), rotation: randomRotation() },
    { position: new T.Vector3(0, 0, 0), rotation: randomRotation() }];
  const { root, node } = scene(chain);
  const rest = node.quaternion.clone();
  const billboard = MVStudioAxisBillboard.create(T, root);
  const camera = new T.PerspectiveCamera();
  camera.position.set(4, 5, 30);
  billboard.apply(camera);
  const parent = node.parent;
  parent.quaternion.copy(mirrorRotation(randomRotation()));
  parent.updateMatrix();
  billboard.apply(camera);
  const first = worldQuaternion(node);
  node.quaternion.copy(rest);
  node.updateMatrix();
  billboard.apply(camera);
  quaternionNear(worldQuaternion(node), first, 1e-12, "fresh and repeated draws agree");

  // A camera on the beam's axis has no defined turn; the authored rotation stays.
  const up = new T.Vector3(0, 1, 0).applyQuaternion(worldQuaternion(node.parent).multiply(rest));
  root.updateMatrixWorld(true);
  const position = new T.Vector3().setFromMatrixPosition(node.matrixWorld);
  camera.position.copy(position).addScaledVector(up, 5);
  billboard.apply(camera);
  quaternionNear(node.quaternion, rest, 1e-12, "degenerate camera keeps the authored rotation");

  // Hidden beams draw nothing and are left alone.
  parent.visible = false;
  node.quaternion.set(0, 0, 0, 1);
  camera.position.set(-9, 1, 2);
  billboard.apply(camera);
  quaternionNear(node.quaternion, new T.Quaternion(), 0, "hidden node untouched");
  billboard.reset();
  quaternionNear(node.quaternion, rest, 0, "reset restores the authored rotation");
}

assert.equal(MVStudioAxisBillboard.create(T, new T.Group()), null);
console.log("AxisBillboard: RunAxisBillboardY basis, X mirror, rotated/scaled parents, recorded game rotations, degenerate and hidden cases.");
