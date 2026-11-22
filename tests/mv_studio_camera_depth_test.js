"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-camera-depth.js");

function rendererStub() {
  const gl = {
    FRAMEBUFFER: 0, FRAMEBUFFER_COMPLETE: 1, SCISSOR_BOX: 2, SCISSOR_TEST: 3,
    DEPTH_TEST: 4, DEPTH_CLEAR_VALUE: 5, DEPTH_WRITEMASK: 6,
    isContextLost: () => false, isEnabled: () => false, checkFramebufferStatus: () => 1,
    getParameter(key) { return key === 2 ? [0, 0, 320, 180] : 1; },
  };
  let target = null;
  return {
    capabilities: {isWebGL2: true, maxTextureSize: 4096}, domElement: {width: 640, height: 360},
    autoClear: true, viewportHeight: 180, shadowMap: {enabled: true}, getContext: () => gl,
    info: {autoReset: true, render: {frame: 0}},
    getRenderTarget: () => target, setRenderTarget(value) { target = value; },
    getActiveCubeFace: () => 0, getActiveMipmapLevel: () => 0,
    getCurrentViewport(viewport) { return viewport.set(0, 0, 320, this.viewportHeight); }, clearDepth() {},
    state: {buffers: {depth: {setClear() {}, setMask() {}, setTest() {}}}, viewport() {}, scissor() {}, setScissorTest() {}},
    render(scene) {
      scene.traverseVisible(node => {
        if (node.isSkinnedMesh && node.skeleton.frame !== this.info.render.frame) {
          node.skeleton.update();
          node.skeleton.frame = this.info.render.frame;
        }
      });
      if (this.info.autoReset) this.info.render.frame++;
      this.inspectDraw?.(scene);
    },
  };
}

function makeMember() {
  const geometry = new T.PlaneGeometry();
  const normals = new T.Float32BufferAttribute(Array(4).fill([0, 0, 1]).flat(), 3);
  geometry.setAttribute("skinIndex", new T.Uint16BufferAttribute(new Uint16Array(16), 4));
  geometry.setAttribute("skinWeight", new T.Float32BufferAttribute(Array(4).fill([1, 0, 0, 0]).flat(), 4));
  geometry.setAttribute("_sifas_color", new T.Uint8BufferAttribute(Array(4).fill([93, 38, 255, 255]).flat(), 4, true));
  geometry.morphAttributes = {position: [normals.clone()], normal: [normals]};
  geometry.morphTargetsRelative = true;
  geometry.userData.mvStageCameraDepth = {kind: "member", queue: 1900};
  const material = new T.ShaderMaterial({skinning: true, morphTargets: true, morphNormals: true,
    uniforms: {uRimglightIntensity: {value: 1}}});
  material.userData.sifas = {shader: "AS/Member"};
  material.userData.mvStageMemberDepthRim = {value: 0};
  const mesh = new T.SkinnedMesh(geometry, material);
  mesh.position.set(-.5, 1.2, -3);
  mesh.morphTargetInfluences[0] = .65;
  const joint = new T.Bone();
  mesh.add(joint);
  mesh.bind(new T.Skeleton([joint]), new T.Matrix4());
  return mesh;
}

const renderer = rendererStub(), source = new T.Scene(), camera = new T.PerspectiveCamera(50, 16 / 9, .1, 1000);
const actor = makeMember();
actor.scale.set(-2, 3, .5);
source.add(actor);
const helper = makeMember();
helper.material.userData.viewerHelper = true;
source.add(helper);
const stage = new T.Mesh(new T.PlaneGeometry(), new T.MeshBasicMaterial());
stage.geometry.userData.mvStageCameraDepth = {kind: "opaque"};
source.add(stage);
const original = new T.WebGLRenderTarget(320, 180);
renderer.setRenderTarget(original);
const depth = MVStudioCameraDepth.create(T, renderer);
const update = actor.skeleton.update.bind(actor.skeleton);
let skeletonUpdates = 0, firstProxy, ratio = 1, activeCamera = camera;
actor.skeleton.update = () => { skeletonUpdates++; update(); };

renderer.inspectDraw = scene => {
  assert.equal(renderer.info.autoReset, false);
  assert.deepEqual(scene.children.map(node => node.geometry), [actor.geometry, stage.geometry]);
  const [member, stageProxy] = scene.children;
  firstProxy ||= member;
  assert.equal(member, firstProxy);
  assert.equal(member.skeleton, actor.skeleton);
  assert.equal(member.morphTargetInfluences, actor.morphTargetInfluences);
  assert.deepEqual(member.bindMatrix, actor.bindMatrix);
  assert.deepEqual(member.bindMatrixInverse, actor.bindMatrixInverse);
  assert.deepEqual(member.matrixWorld, actor.matrixWorld);
  const material = member.material;
  assert.equal(material.skinning, true);
  assert.equal(material.morphTargets, true);
  assert.equal(material.morphNormals, true);
  assert.equal(material.side, T.FrontSide);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, true);
  assert.equal(material.stencilWrite, false);
  assert.equal(material.colorWrite, false);
  assert.equal(stageProxy.material.defines.MEMBER, undefined);
  assert.match(material.vertexShader, /#include <morphnormal_vertex>\s+#include <skinbase_vertex>\s+#include <skinnormal_vertex>/);
  assert.match(material.vertexShader, /normalize\(normalMatrix \* objectNormal\)/);
  assert.match(material.vertexShader, /if \(projectionMatrix\[3\]\.w == 0\.0\) \{[\s\S]*?gl_Position\.xy[^;]+;\s*}\s*gl_Position\.z/);
  member.modelViewMatrix.multiplyMatrices(activeCamera.matrixWorldInverse, member.matrixWorld);
  member.normalMatrix.getNormalMatrix(member.modelViewMatrix);
  const transformed = new T.Vector3(.5, 1, 1).applyMatrix3(member.normalMatrix).normalize();
  assert.ok(transformed.distanceTo(new T.Vector3(-.25, 1 / 3, 2).normalize()) < 1e-7);
  member.onBeforeRender();
  assert.equal(material.uniforms.memberResolutionRatio.value, ratio);
  assert.equal(material.uniforms.memberRimIntensity.value, actor.material.userData.mvStageMemberDepthRim.value);
  assert.equal(material.uniformsNeedUpdate, true);
};
assert.equal(depth.capture(source, camera).isDepthTexture, true);
assert.equal(renderer.getRenderTarget(), original);
assert.equal(renderer.info.autoReset, true);
assert.equal(skeletonUpdates, 1);
const inspectDepth = renderer.inspectDraw;
renderer.inspectDraw = null;
renderer.render(source);
assert.equal(skeletonUpdates, 1, "the World pass consumes the already updated source skeleton in the same r128 frame");
actor.position.z = -2;
actor.children[0].position.y = .9;
actor.morphTargetInfluences[0] = .33;
actor.material.userData.mvStageMemberDepthRim.value = 1.2;
renderer.inspectDraw = inspectDepth;
assert.equal(depth.capture(source, camera).isDepthTexture, true);
assert.equal(skeletonUpdates, 2);
assert.notEqual(actor.material, firstProxy.material);
assert.equal(renderer.shadowMap.enabled, true);
assert.equal(renderer.autoClear, true);

activeCamera = new T.OrthographicCamera(-2, 2, 2, -2, .5, 300);
const oversize = new T.WebGLRenderTarget(320, 720);
renderer.setRenderTarget(oversize);
renderer.viewportHeight = 720;
ratio = .5;
assert.equal(depth.capture(source, activeCamera).image.height, 720);
assert.equal(renderer.getRenderTarget(), oversize);
assert.equal(skeletonUpdates, 2, "camera-only capture uses the already evaluated frame");
renderer.setRenderTarget(original);
renderer.viewportHeight = 180;

actor.geometry.userData.mvStageCameraDepth.queue = 3000;
renderer.inspectDraw = scene => {
  assert.equal(renderer.info.autoReset, true);
  assert.deepEqual(scene.children.map(node => node.geometry), [stage.geometry]);
};
assert.equal(depth.capture(source, camera).isDepthTexture, true);
assert.equal(skeletonUpdates, 2);
actor.geometry.userData.mvStageCameraDepth.queue = 1900;
renderer.inspectDraw = () => { throw Error("drawing failed"); };
assert.throws(() => depth.capture(source, camera), /drawing failed/);
assert.equal(renderer.info.autoReset, true);
assert.equal(renderer.getRenderTarget(), original);
depth.dispose();
assert.equal(depth.capture(source, camera), null);
console.log("Native member depth shares evaluated skin and morphs with the visible renderer and preserves stage capture state.");

function testRigidFace() {
  const renderer = rendererStub(), source = new T.Scene(), camera = new T.PerspectiveCamera();
  const parent = new T.Group(), face = makeMember(), carrier = face.skeleton.bones[0];
  face.geometry.userData.mvStageCameraDepth.kind = "memberFace";
  source.add(parent, carrier);
  parent.add(face);
  parent.scale.set(-2, .6, 1.4);
  parent.rotation.set(.17, -.31, .46);
  face.bindMode = "detached";
  face.bindMatrix.makeRotationY(.36).setPosition(.3, -.8, .4);
  face.skeleton.boneInverses[0].makeRotationX(-.18).setPosition(-.2, .35, .1);
  carrier.rotation.set(.6, .21, -.4);
  carrier.scale.set(.8, 1.3, .5);
  carrier.position.set(.3, .4, -.7);
  let skeletonUpdates = 0, cachedProxy;
  face.skeleton.update = () => { skeletonUpdates++; };

  function world(point) {
    return point.clone().applyMatrix4(face.bindMatrix).applyMatrix4(face.skeleton.boneInverses[0])
      .applyMatrix4(carrier.matrixWorld).applyMatrix4(face.bindMatrixInverse).applyMatrix4(face.matrixWorld);
  }
  renderer.inspectDraw = scene => {
    assert.equal(renderer.info.autoReset, true);
    assert.equal(scene.children.length, 1);
    const [proxy] = scene.children;
    cachedProxy ||= proxy;
    assert.equal(proxy, cachedProxy);
    assert.equal(proxy.isMesh, true);
    assert.equal(proxy.isSkinnedMesh, undefined);
    assert.equal(proxy.material.skinning, false);
    assert.equal(proxy.material.morphTargets, true);
    assert.equal(proxy.material.morphNormals, true);
    assert.equal(proxy.geometry, face.geometry);
    assert.equal(proxy.morphTargetInfluences, face.morphTargetInfluences);
    const weight = face.morphTargetInfluences[0];
    const morphed = new T.Vector3(.2, .7, -.4).addScaledVector(new T.Vector3(.01, -.03, .06), weight);
    assert.ok(world(morphed).distanceTo(morphed.clone().applyMatrix4(proxy.matrixWorld)) < 1e-10);

    const origin = world(new T.Vector3());
    const x = world(new T.Vector3(1, 0, 0)).sub(origin);
    const y = world(new T.Vector3(0, 1, 0)).sub(origin);
    const z = world(new T.Vector3(0, 0, 1)).sub(origin);
    assert.ok(Math.abs(x.dot(y)) > .1, "effective basis has shear");
    const normal = new T.Vector3(.2, -.45, .75);
    const yz = new T.Vector3().crossVectors(y, z), zx = new T.Vector3().crossVectors(z, x);
    const xy = new T.Vector3().crossVectors(x, y), det = x.dot(yz);
    assert.ok(det < 0, "fixture also covers a reflected carrier");
    const expectedNormal = yz.multiplyScalar(normal.x).addScaledVector(zx, normal.y).addScaledVector(xy, normal.z)
      .multiplyScalar(1 / det).normalize();
    const actualNormal = normal.clone().applyMatrix3(new T.Matrix3().getNormalMatrix(proxy.matrixWorld)).normalize();
    assert.ok(actualNormal.distanceTo(expectedNormal) < 1e-10);
    proxy.onBeforeRender();
    assert.equal(proxy.material.uniforms.memberRimIntensity.value, face.material.userData.mvStageMemberDepthRim.value);
  };

  const depth = MVStudioCameraDepth.create(T, renderer);
  assert.ok(depth.capture(source, camera));
  face.morphTargetInfluences[0] = .1;
  face.material.userData.mvStageMemberDepthRim.value = 2;
  carrier.position.z = .65;
  assert.ok(depth.capture(source, camera));
  assert.equal(skeletonUpdates, 0, "the rigid native face never submits a second GPU skin");

  renderer.inspectDraw = scene => assert.equal(scene.children.length, 0);
  const inverses = face.skeleton.boneInverses;
  face.skeleton.boneInverses = [];
  assert.ok(depth.capture(source, camera));
  face.skeleton.boneInverses = inverses;
  face.skeleton.bones.push(new T.Bone());
  assert.ok(depth.capture(source, camera));
  depth.dispose();
  console.log("Native merged-face depth uses the full rigid carrier matrix with live morphs and rejects unsupported skins.");
}

testRigidFace();
