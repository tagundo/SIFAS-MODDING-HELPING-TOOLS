"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-shaft.js");

const meshName = "Native member spotlight shaft";
const tint = mesh => mesh.material.uniforms.uTint.value.toArray();

function template(index) {
  const node = name => ({ name, translation: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1] });
  return {
    index, nodes: [node("variant " + index), node("native renderer")],
    geometry: { position: index * 3, color: index * 3 + 1, index: index * 3 + 2 },
    material: { tint: [1, 1, 1, 1], queue: 3000 }
  };
}

function event(values = {}, start = 0, duration = 20) {
  return { start, duration, values: {
    playableClass: "LiveMemberSpotLightShaftClip", color: { r: .6, g: .8, b: .4, a: 1 },
    colorSpecifiedType: 0, drawObjectIndex: 0, scale: { x: 5, y: 7, z: 1 },
    offsetHeight: 2.5, smoothTime: .5, ...values
  } };
}

function near(current, expected, range = 1e-10) {
  assert.ok(Math.abs(current - expected) < range, `Expected ${expected}, got ${current}`);
}

function pointNear(current, target) {
  assert.equal(current.length, target.length);
  current.forEach((value, axis) => near(value, target[axis]));
}

function worldDirection(mesh, direction) {
  for (let node = mesh; node; node = node.parent) direction.applyQuaternion(node.quaternion);
  return direction.normalize();
}

async function run() {
  const source = new T.Scene();
  source.userData.mvShaftTemplates = [template(0), template(1)];
  const gradient = new T.Float32BufferAttribute([1, 1, 1, 0, 1, 1, 1, .2, 1, 1, 1, 1], 4);
  const attributes = [
    new T.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3), gradient,
    new T.Uint16BufferAttribute([0, 1, 2], 1),
    new T.Float32BufferAttribute([0, 0, 0, 2, 0, 0, 0, 1, 0], 3), gradient,
    new T.Uint16BufferAttribute([0, 1, 2], 1)
  ];
  const accesses = [];
  const prepared = await MVStudioShaft.prepare(T, { scene: source, parser: {
    async getDependency(type, index) {
      assert.equal(type, "accessor");
      accesses.push(index);
      return attributes[index];
    }
  } });
  assert.deepEqual(accesses, [0, 1, 2, 3, 4, 5]);
  assert.equal(source.children.length, 0);

  const stage = new T.Scene(), actor = new T.Group(), move = new T.Group();
  actor.position.set(0, 12, 0);
  actor.scale.set(1, 2, 1);
  actor.add(move);
  stage.add(actor);
  move.position.set(4, 100, -3);
  const other = new T.Group(), otherMove = new T.Group();
  other.add(otherMove);
  stage.add(other);
  const controller = MVStudioShaft.create(T, prepared, actor, move);
  const another = MVStudioShaft.create(T, prepared, other, otherMove);
  const root = actor.getObjectByName("variant 0"), root2 = actor.getObjectByName("variant 1");
  const mesh = root.getObjectByName(meshName), mesh2 = root2.getObjectByName(meshName);
  const shared = other.getObjectByName(meshName);
  const camera = new T.PerspectiveCamera(), subCamera = new T.PerspectiveCamera();
  camera.position.set(0, 30, 40);
  subCamera.position.set(10, 19, -6);
  assert.equal(mesh.geometry, shared.geometry);
  assert.notEqual(mesh.material, shared.material);
  assert.equal(mesh.geometry.getAttribute("shaftColor"), gradient);
  assert.equal(mesh.material.side, T.DoubleSide);
  assert.equal(mesh.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(mesh.material.blendDst, T.OneFactor);
  assert.equal(mesh.material.blendSrcAlpha, T.SrcAlphaFactor);
  assert.equal(mesh.material.blendDstAlpha, T.OneFactor);
  assert.equal(mesh.material.depthTest, false);
  assert.equal(mesh.material.depthWrite, false);
  assert.equal(mesh.renderOrder, 3000);
  assert.equal(mesh.layers.mask, 1);

  const clips = [event()];
  assert.equal(controller.frame(clips, 0, 0, camera, {}), true);
  assert.equal(shared.visible, false);
  pointNear(root.scale.toArray(), [6, 8, 2]);
  pointNear(root.getWorldPosition(new T.Vector3()).toArray(), [4, 17, -3]);
  pointNear(tint(mesh), [.6, .8, .4, 1]);

  // Each camera applies local +Z around the preserved up, despite nonuniform scale.
  for (const view of [camera, subCamera, camera]) {
    controller.billboard(view);
    const expected = view.position.clone().sub(root.getWorldPosition(new T.Vector3()));
    expected.y = 0;
    pointNear(worldDirection(mesh, new T.Vector3(0, 0, 1)).toArray(), expected.normalize().toArray());
    pointNear(worldDirection(mesh, new T.Vector3(0, 1, 0)).toArray(), [0, 1, 0]);
  }

  // Exact finite-time Unity damp, then a color change forces a horizontal snap.
  move.position.x += .2;
  const dt = .1, x = 2 * dt / .5;
  const expectedDamped = 4.2 - .2 * (1 + x) / (1 + x + .48 * x * x + .235 * x * x * x);
  controller.frame(clips, .1, dt, camera, {});
  near(root.position.x, expectedDamped);
  move.position.x += .2;
  controller.frame([event({ color: { r: .6001, g: .8, b: .4, a: 1 } })], .2, dt, camera, {});
  near(tint(mesh)[0], .6);
  assert.ok(root.position.x < move.position.x);
  controller.frame([event({ color: { r: .61, g: .8, b: .4, a: 1 } })], .3, dt, camera, {});
  near(root.position.x, move.position.x);
  move.position.x += 1;
  controller.frame([event({ color: { r: .61, g: .8, b: .4, a: 1 } })], .4, dt, camera, {});
  near(root.position.x, move.position.x);

  // The last processed clip selects the native prefab slot. Mix preserves
  // exact scale bias and can get a color from a different member's palette.
  const themed = event({ drawObjectIndex: 1, colorSpecifiedType: 1, memberPosition: 7, easeIn: 2 }, 1);
  const first = event({ easeOut: 2 }, 0, 2);
  const project = { performers: [{ position: 7, themeColor: [.5, 1, .5, .5] }] };
  controller.frame([first, themed], 1.5, dt, camera, project, true);
  assert.equal(mesh.visible, false);
  assert.equal(mesh2.visible, true);
  pointNear(root2.scale.toArray(), [2.5625, 3.1875, 1.3125]);
  pointNear(tint(mesh2), [.140625, .25, .09375, .234375]);

  controller.frame([event({ color: { r: .6, g: .8, b: .4, a: .005 } })], 0, 0, camera, {}, true);
  assert.equal(mesh.visible, false);
  controller.frame([event({ color: { r: .6, g: .8, b: .4, a: .01 } })], 0, 0, camera, {}, true);
  assert.equal(mesh.visible, true);
  controller.frame([], 0, 0, camera, {});
  assert.equal(mesh.visible, false);
  controller.frame([event({}, 1, 1)], 3, 0, camera, {});
  assert.equal(mesh.visible, false);
  controller.frame(clips, 0, 0, camera, {}, true);
  near(root.position.x, move.position.x);

  let materialDisposals = 0, geometryDisposals = 0;
  mesh.material.addEventListener("dispose", () => materialDisposals++);
  shared.geometry.addEventListener("dispose", () => geometryDisposals++);
  controller.dispose();
  assert.equal(materialDisposals, 1);
  assert.equal(geometryDisposals, 0);
  assert.deepEqual(actor.children, [move]);
  assert.equal(other.getObjectByName(meshName), shared);
  another.dispose();
  prepared.dispose();
  assert.equal(geometryDisposals, 1);
  console.log("Native spotlight shafts: template ownership, shape mixing, GPU state, move anchor, damping and per-camera billboard.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
