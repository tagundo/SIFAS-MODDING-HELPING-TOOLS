"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-member-shadow.js");

const f32 = Math.fround;
const floor = f32(.01);
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} differs from ${expected}`);
const projectedScale = y => Math.min(f32(.2), Math.max(0, f32(f32(.15) - f32(y))));

async function verify() {
  const scene = new T.Scene(), actor = new T.Group(), shadowLayer = new T.Group();
  scene.add(actor, shadowLayer);
  actor.position.set(4, 0, -3);
  actor.rotation.y = .6;
  const child = (id, position) => {
    const object = new T.Object3D();
    object.userData.elichika_node = id;
    object.position.set(...position);
    actor.add(object);
    return object;
  };
  // The node IDs and accessor counts come from the paired Aion stock actor GLBs.
  // Add nodes in an order different from the serialized L/R pairs.
  const rightAnchor = child(103, [-7, 2, 9]);
  const rightToe = child(139, [.3, -.3, -.2]);
  const leftAnchor = child(141, [8, -5, 3]);
  const leftToe = child(99, [-.3, .05, .2]);
  child(104, [55, 0, 55]).name = "LeftToeBase";
  leftAnchor.scale.set(2, 3, 4);
  rightAnchor.scale.set(3, 4, 5);
  const source = {schema: 1, toes: [99,139], anchors: [141,103],
    geometry: {POSITION: 0, TEXCOORD_0: 1, indices: 2}, texture: 0};
  const geometry = new T.CircleGeometry(1, 10).rotateX(-Math.PI / 2);
  const texture = new T.Texture({width: 128, height: 128});
  const calls = [];
  const parser = {getDependency(kind, id) {
    calls.push([kind, id]);
    return Promise.resolve(kind === "texture" ? texture : [geometry.attributes.position, geometry.attributes.uv, geometry.index][id]);
  }};

  assert.equal(await MVStudioMemberShadow.apply(T, actor, parser, shadowLayer), null);
  actor.userData.mvMemberShadow = {...source, anchors: [141, 99]};
  assert.equal(await MVStudioMemberShadow.apply(T, actor, parser, shadowLayer), null);
  actor.userData.mvMemberShadow = source;
  const duplicate = child(99, [20, 1, 1]);
  assert.equal(await MVStudioMemberShadow.apply(T, actor, parser, shadowLayer), null);
  actor.remove(duplicate);
  assert.deepEqual(calls, []);

  const shadow = await MVStudioMemberShadow.apply(T, actor, parser, shadowLayer);
  assert.ok(shadow);
  assert.deepEqual(calls, [["accessor", 0], ["accessor", 1], ["accessor", 2], ["texture", 0]]);
  const [left, right] = shadowLayer.children;
  assert.equal(shadowLayer.children.length, 2);
  assert.equal(actor.children.some(node => node.isMesh), false);
  assert.equal(left.geometry, right.geometry);
  assert.equal(left.material, right.material);
  assert.equal(left.renderOrder, 2800);
  assert.equal(right.renderOrder, 2800);
  const {material} = left, atlas = material.uniforms.uTexture.value;
  assert.deepEqual([left.geometry.attributes.position.count, left.geometry.attributes.uv.count, left.geometry.index.count], [12, 12, 30]);
  assert.deepEqual([material.transparent, material.toneMapped, material.side, material.depthTest, material.depthFunc, material.depthWrite],
    [true, false, T.DoubleSide, true, T.LessEqualDepth, false]);
  assert.deepEqual([material.blending, material.blendSrc, material.blendDst, material.blendSrcAlpha, material.blendDstAlpha],
    [T.CustomBlending, T.DstColorFactor, T.ZeroFactor, T.DstAlphaFactor, T.ZeroFactor]);
  assert.notEqual(atlas, texture);
  assert.equal(atlas.image, texture.image);
  assert.deepEqual([atlas.encoding, atlas.wrapS, atlas.wrapT, atlas.magFilter, atlas.minFilter, atlas.generateMipmaps],
    [T.LinearEncoding, T.RepeatWrapping, T.RepeatWrapping, T.LinearFilter, T.LinearFilter, false]);

  function check(mesh, toe, factor) {
    scene.updateMatrixWorld(true);
    const c = Math.cos(actor.rotation.y), s = Math.sin(actor.rotation.y);
    const {x, z} = toe.position, {elements: m} = mesh.matrixWorld;
    assert.deepEqual(m.slice(12, 15), [f32(actor.position.x + c * x + s * z), floor, f32(actor.position.z - s * x + c * z)]);
    for (const [actual, expected] of [[m[0], c * factor], [m[2], -s * factor], [m[8], s * factor], [m[10], c * factor]]) {
      close(actual, expected);
    }
    const vertex = new T.Vector3();
    for (let index = 0; index < mesh.geometry.attributes.position.count; index++) {
      vertex.fromBufferAttribute(mesh.geometry.attributes.position, index).applyMatrix4(mesh.matrixWorld);
      close(vertex.y, floor);
    }
  }

  shadow.update(true, true);
  assert.ok(left.visible && right.visible);
  const original = projectedScale(.05);
  check(left, leftToe, original);
  check(right, rightToe, f32(.2));
  const before = left.matrix.clone();
  leftToe.rotation.set(1.2, -.7, .8);
  shadow.update(true, true);
  assert.deepEqual(left.matrix.elements, before.elements);

  // A change below .005 keeps the old width while world X still follows the toe.
  leftToe.position.set(-.24, .054, .2);
  shadow.update(true, true);
  check(left, leftToe, original);
  leftToe.position.y = .056;
  shadow.update(true, true);
  check(left, leftToe, projectedScale(.056));
  leftToe.position.y = .054;
  shadow.update(true, false);
  check(left, leftToe, projectedScale(.054));
  actor.position.set(-2, .02, 5);
  actor.rotation.y = -1.2;
  shadow.update(true, false);
  check(left, leftToe, projectedScale(.074));
  check(right, rightToe, f32(.2));

  leftToe.position.y = .3;
  shadow.update(true, false);
  assert.ok(!left.visible && right.visible);
  shadow.update(false, false);
  assert.ok(!left.visible && !right.visible);
  actor.visible = false;
  shadow.update(true, false);
  assert.ok(!left.visible && !right.visible);
  actor.visible = true;
  shadow.update(true, false);
  assert.ok(!left.visible && right.visible);

  const disposed = [];
  for (const [object, name] of [[left.geometry, "geometry"], [material, "material"], [atlas, "atlas"], [texture, "source"]]) {
    object.addEventListener("dispose", () => disposed.push(name));
  }
  shadow.dispose();
  shadow.dispose();
  shadow.update(true, true);
  assert.deepEqual(shadowLayer.children, []);
  assert.deepEqual(disposed, ["geometry", "material", "atlas"]);
}

verify().catch(error => { console.error(error); process.exitCode = 1; });
