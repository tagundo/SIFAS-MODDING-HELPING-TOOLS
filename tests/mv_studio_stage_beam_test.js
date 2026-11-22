"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/viewer-motion-timeline.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-stage-beam.js");

const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root";
const beamPath = 587684620, jointPath = 1373847302;
const dimensions = [512, 256, 128, 64, 32, 16, 8, 4, 2, 1];
const tint = [2, 2, 2, 1], channels = [Math.fround(.6), Math.fround(.8), 1];
const strip = {shader: "AS/General/Transparent", binding: `${binding}/joint_all/LaserBeam`, renderOrder: 3010,
  texture: 6, mips: [7, 8, 9, 10, 11, 12, 13, 14, 15], tint, uv: [1, 1, 0, 0], vertexColor: false};

function fixture() {
  const root = new T.Scene(), animated = new T.Group(), owner = new T.Group(), bone = new T.Bone();
  const geometry = new T.BufferGeometry(), base = new T.MeshBasicMaterial();
  geometry.setAttribute("position", new T.Float32BufferAttribute([0, 0, 0, .01, 0, 0, .01, 1, 0], 3));
  geometry.setAttribute("uv", new T.Float32BufferAttribute([.75, 0, 1, 0, 1, .25], 2));
  geometry.setAttribute("skinIndex", new T.Uint16BufferAttribute([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 4));
  geometry.setAttribute("skinWeight", new T.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4));
  geometry.setIndex([0, 1, 2]);
  geometry.userData.mvStageBeam = {...strip};
  const mesh = new T.SkinnedMesh(geometry, base);
  animated.userData.mvStageNode = {binding, path: 0, active: true};
  owner.userData.mvStageNode = {binding, path: beamPath, active: true};
  bone.userData.mvStageNode = {binding, path: jointPath, active: true};
  const other = new T.Mesh(geometry, new T.MeshBasicMaterial());
  root.add(animated, other);
  animated.add(owner, bone);
  owner.add(mesh);
  root.updateMatrixWorld(true);
  mesh.bind(new T.Skeleton([bone]), mesh.matrixWorld);
  mesh.renderOrder = 44;
  mesh.layers.enable(4);
  return {root, animated, owner, bone, mesh, base, geometry, other};
}

function textureParser() {
  const indices = [strip.texture, ...strip.mips], reads = [];
  const originals = new Map(indices.map((id, index) => [id, new T.Texture({width: dimensions[index], height: dimensions[index]})]));
  originals.get(strip.texture).encoding = T.sRGBEncoding;
  const parser = {getDependency(kind, id) {
    assert.equal(kind, "texture");
    assert.ok(originals.has(id));
    reads.push(id);
    return Promise.resolve(originals.get(id));
  }};
  return {indices, reads, originals, parser};
}

function controlProject() {
  const firstFrame = 1 / 60;
  const alpha = ["cubic", [[0, [0, 0, 0, 0]], [Math.fround(77.73333333333333 - firstFrame), [0, 0, 0, 1]],
    [Math.fround(107.45 - firstFrame), [0, 0, 0, 0]]]];
  const constant = value => ["constant", value];
  const event = {id: "beam-event", start: firstFrame, duration: 118.6, values: {animation: "beam", timeScale: 1, clipIn: 0}};
  const track = {id: "beam-track", nativeClass: "AnimationTrack", binding, events: [event]};
  const project = {quality: {values: {stage_control: true}}, tracks: [track], stageMotion: {quality: {[track.id]: "stage_control"},
    mix: {[event.id]: {}}, clips: {beam: {start: 0, duration: Math.fround(118.81666666666667), sampleTimeF32: true, channels: [
      {path: beamPath, kind: "overlayTint", curves: [...channels.map(constant), alpha]},
      {path: jointPath, kind: "translation", curves: [["linear", [[0, 0], [78, 1]]], constant(0), constant(0)]},
    ]}}}};
  return {project, track};
}

async function run() {
  const {root, animated, owner, mesh, base, geometry, other} = fixture();
  const {indices, reads, originals, parser} = textureParser();
  const priorOther = other.material, skeleton = mesh.skeleton, layerMask = mesh.layers.mask;
  const beam = await MVStudioStageBeam.apply(T, root, parser);
  assert.ok(beam);
  assert.deepEqual(reads.slice().sort((a, b) => a - b), indices);
  assert.equal(other.material, priorOther);
  assert.equal(mesh.geometry, geometry);
  assert.equal(mesh.skeleton, skeleton);
  const material = mesh.material;
  assert.notEqual(material, base);
  assert.equal(material.skinning, true);
  assert.match(material.vertexShader, /<skinning_pars_vertex>/);
  assert.match(material.vertexShader, /<skinning_vertex>/);
  assert.equal(material.transparent, true);
  assert.equal(material.blending, T.CustomBlending);
  assert.equal(material.blendSrc, T.SrcAlphaFactor);
  assert.equal(material.blendDst, T.OneFactor);
  assert.equal(material.blendSrcAlpha, T.SrcAlphaFactor);
  assert.equal(material.blendDstAlpha, T.OneFactor);
  assert.equal(material.depthWrite, false);
  assert.equal(material.depthTest, true);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.side, T.DoubleSide);
  assert.equal(material.toneMapped, false);
  assert.equal(material.stencilFunc, T.AlwaysStencilFunc);
  assert.deepEqual([material.stencilFail, material.stencilZFail, material.stencilZPass], Array(3).fill(T.KeepStencilOp));
  assert.equal(mesh.renderOrder, 3010);
  assert.equal(mesh.frustumCulled, false);
  assert.equal(mesh.layers.mask, layerMask);

  const original = originals.get(strip.texture), installed = material.uniforms.uTexture.value;
  assert.notEqual(installed, original);
  assert.deepEqual(installed.mipmaps.map(image => [image.width, image.height]), dimensions.map(size => [size, size]));
  assert.equal(installed.generateMipmaps, false);
  assert.equal(installed.encoding, T.LinearEncoding);
  assert.equal(installed.minFilter, T.LinearMipmapNearestFilter);
  assert.equal(installed.magFilter, T.LinearFilter);
  assert.deepEqual([installed.wrapS, installed.wrapT], [T.RepeatWrapping, T.RepeatWrapping]);
  assert.equal(original.encoding, T.sRGBEncoding);
  assert.deepEqual(original.mipmaps, []);
  const animatedTint = owner.userData.mvStageOverlayChannels.overlayTint;
  assert.equal(animatedTint, material.uniforms.uTint.value);
  assert.deepEqual(animatedTint.toArray(), tint);

  const stageMotion = MVStudioStageMotion.apply(T, root), {project, track} = controlProject();
  stageMotion.update(77.55, project);
  assert.deepEqual(animatedTint.toArray(), [...channels, 0]);
  stageMotion.update(79.55, project);
  assert.deepEqual(animatedTint.toArray(), [...channels, 1]);
  root.updateMatrixWorld(true);
  assert.deepEqual(mesh.boneTransform(0, new T.Vector3()).toArray(), [-1, 0, 0]);
  stageMotion.update(107.45, project);
  assert.deepEqual(animatedTint.toArray(), [...channels, 1]);
  stageMotion.update(107.46666666666667, project);
  assert.deepEqual(animatedTint.toArray(), [...channels, 0]);
  stageMotion.update(79.55, project);
  assert.deepEqual(animatedTint.toArray(), [...channels, 1]);
  track.muted = true;
  stageMotion.update(79.55, project);
  assert.deepEqual(animatedTint.toArray(), tint);
  track.muted = false;
  project.quality.values.stage_control = false;
  stageMotion.update(79.55, project);
  assert.equal(animated.visible, false);
  assert.deepEqual(animatedTint.toArray(), tint);
  project.quality.values.stage_control = true;
  stageMotion.update(79.55, {...project, stageMotion: {...project.stageMotion, mix: {}}});
  assert.equal(animated.visible, true);
  assert.deepEqual(animatedTint.toArray(), tint);

  let disposedMaterial = 0, disposedOriginal = 0, disposedTexture = 0;
  material.addEventListener("dispose", () => disposedMaterial++);
  base.addEventListener("dispose", () => disposedOriginal++);
  for (const texture of originals.values()) texture.addEventListener("dispose", () => disposedOriginal++);
  installed.addEventListener("dispose", () => disposedTexture++);
  beam.dispose();
  beam.dispose();
  assert.deepEqual([disposedMaterial, disposedTexture, disposedOriginal], [1, 1, 0]);
  assert.equal(mesh.material, base);
  assert.equal(mesh.renderOrder, 44);
  assert.equal(mesh.frustumCulled, true);
  assert.equal(mesh.layers.mask, layerMask);
  assert.equal(owner.userData.mvStageOverlayChannels, undefined);

  originals.get(indices[1]).image = {width: 128, height: 128};
  await assert.rejects(MVStudioStageBeam.apply(T, root, parser), /texture is incomplete/);
  assert.equal(mesh.material, base);
  assert.equal(owner.userData.mvStageOverlayChannels, undefined);
  assert.equal(disposedOriginal, 0);
  delete geometry.userData.mvStageBeam;
  const readCount = reads.length;
  assert.equal(await MVStudioStageBeam.apply(T, root, parser), null);
  assert.equal(reads.length, readCount);
  console.log("Native stage laser beam: skinned world mesh, authored mips, tint timeline, and material ownership.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
