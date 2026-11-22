"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-lighting.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-laser-core-simulation.js");
require("../webtools/web/static/mv-studio-stage-laser-cores.js");

const f32 = Math.fround;
const alphaKeys = [[0,0], [655,255], [64880,255], [65535,0]].map(([stamp, a]) => [f32(stamp / 65535), a]);
const keys = alphaKeys.map(([phase, a]) => [phase, 255, 255, 255, a]);
const nativeStart = [153, 204, 255, 153];
const rollRange = [0, f32(6.283185)];
const seed = -1462782512;
const lifetime = .25, capacity = 20, period = f32(.08);
const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root";
const trackId = "-3114162657147975647", eventId = trackId + ":0", animation = "-7002476404608242900";
const branches = [1610778772, 4178303278];

function sampleOf(size, burstPeriod, start) {
  const stream = MVStudioResidentCoreSimulation.create({
    seed, burstPeriod, lifetime, rollRange, capacity, size, color: {start, keys},
  });
  assert.ok(stream);
  return (tick, fps) => {
    const rows = [];
    stream.sample(tick / fps, fps, (...fields) => rows.push(fields));
    return rows;
  };
}

function verifyNative() {
  // Original Android worker, Joint_root_02/L, timeline start color applied.
  const sample = sampleOf(f32(.6), period, nativeStart);
  const first = 5.545601844787598, second = .3970830738544464, third = 2.594749689102173, fourth = 4.10566520690918;
  const widths = [f32(.6), f32(.6)];
  const row = (roll, alpha, birth, fps) => [...widths, roll, 153, 204, 255, alpha, birth / fps, alpha ? 255 : 0];
  assert.deepEqual(sample(0, 60), []);
  assert.deepEqual(sample(1, 60), [row(first, 0, 1, 60)]);
  assert.deepEqual(sample(2, 60), [row(first, 153, 1, 60)]);
  assert.deepEqual(sample(1, 30), [row(first, 153, 1, 30)]);
  assert.deepEqual(sample(5, 60), [row(first, 153, 1, 60), row(second, 0, 5, 60)]);
  assert.deepEqual(sample(16, 60), [
    row(first, 0, 1, 60), row(second, 153, 5, 60), row(third, 153, 10, 60), row(fourth, 153, 15, 60),
  ]);
  // The expired first birth is replaced by the last stored live particle.
  assert.deepEqual(sample(17, 60), [row(fourth, 153, 15, 60), row(second, 153, 5, 60), row(third, 153, 10, 60)]);
  assert.deepEqual(sample(9, 30), [row(fourth, 153, 8, 30), row(second, 153, 3, 30), row(third, 153, 5, 30)]);
  assert.deepEqual(sample(2, 60), [row(first, 153, 1, 60)]);
  assert.deepEqual(sample(0, 30), []);
  assert.deepEqual(sample(60, 60).map(row => row[2]), [4.414874076843262, 1.959011197090149, 4.805095195770264]);
  assert.deepEqual(sample(12000, 60), []);
  assert.deepEqual(sample(1, 59), []);

  // The other exact stock period uses f32(index × interval). At .75 seconds
  // the next birth waits for tick 46; repeated interval addition misses it.
  const short = sampleOf(f32(.8), f32(.05), [255, 102, 179, 152]);
  assert.deepEqual(short(45, 60).at(-1).slice(2), [3.22727632522583, 255, 102, 179, 152, 42 / 60, 255]);
  assert.deepEqual(short(46, 60).at(-1).slice(2), [2.2844254970550537, 255, 102, 179, 0, 46 / 60, 0]);
}

async function verifyController() {
  const stage = new T.Group();
  function carrier(parent, path) {
    const object = new T.Group();
    object.userData.mvStageNode = {binding, path, active: true};
    parent.add(object);
    return object;
  }

  const hierarchy = carrier(stage, 0);
  const joints = branches.map(path => carrier(hierarchy, path));
  const paths = [2111430243, 1141226888, 4082555264, 3398089323];
  const emitters = paths.map((path, index) => {
    const branch = Math.floor(index / 2);
    const arm = carrier(joints[branch], 100 + index);
    arm.position.set(index - 2, 1, -4);
    arm.scale.setScalar(0);
    carrier(arm, path);
    const red = index === 2 ? .4729999899864197 : .458823561668396;
    return {path, activationPath: branches[branch], size: f32(branch ? .6 : .8),
      color: [red, .7765381932258606, 1, .597691535949707], animatedColor: [f32(.6), f32(.8), 1, f32(.6)]};
  });
  stage.userData.mvStageLaserCores = {binding, trackId, eventId, emitters, seed: seed >>> 0, burstPeriod: period,
    lifetime, rollRange, capacity, alphaKeys, uv: [.125,.125,.75,.125], maxViewportWidth: .5,
    texture: Array.from({length: 10}, (_, index) => index)};
  const maps = stage.userData.mvStageLaserCores.texture.map(level => new T.Texture({width: 512 >> level, height: 512 >> level}));
  const controller = await MVStudioStageLaserCores.apply(T, stage, {getDependency(kind, index) {
    assert.equal(kind, "texture");
    return Promise.resolve(maps[index]);
  }});
  assert.ok(controller);
  const meshes = stage.children.filter(node => node.isMesh);
  assert.equal(meshes.length, 4);
  assert.deepEqual(meshes.map(mesh => mesh.position.toArray()), [[-2,1,-4], [-1,1,-4], [0,1,-4], [1,1,-4]]);

  // Keep the first two real native activation windows and one branch's earlier off key.
  const channels = branches.map((path, index) => ({path, kind: "visibility", curves: [["cubic",
    [[0, 0], [77.71666717529297, 1], [index ? 79.55000305175781 : 80.58333587646484, 0],
      [81.18333435058594, 1], [83.11666870117188, 0]].map(([time, value]) => [time, [0, 0, 0, value]])]]}));
  const source = {id: trackId, binding, nativeClass: "AnimationTrack", muted: false,
    events: [{id: eventId, start: 1 / 60, duration: 118.6, values: {animation, timeScale: 1, clipIn: 0}}]};
  const quality = {frame_rate_60fps: true};
  const project = {tracks: [source], quality: {values: quality}, stageMotion: {mix: {[eventId]: {}},
    clips: {[animation]: {start: 0, duration: 118.81666564941406, sampleTimeF32: true, loop: false, channels}}}};
  const at = seconds => {
    controller.update(seconds, project);
    return meshes.map(mesh => mesh.geometry.instanceCount);
  };
  const packed = mesh => Array.from(mesh.geometry.attributes.particleColor.array.subarray(0, 4));
  const roll = mesh => mesh.geometry.attributes.particleRoll.getX(0);
  assert.deepEqual(at(77), [0,0,0,0]);
  assert.deepEqual(at(4664 / 60), [0,0,0,0]);
  assert.deepEqual(at(4665 / 60), [1,1,1,1]);
  assert.deepEqual(packed(meshes[2]), nativeStart);
  assert.equal(roll(meshes[2]), 5.545601844787598);
  assert.ok(at(4774 / 60).slice(0, 2).every(count => count > 1));
  assert.deepEqual(at(4774 / 60).slice(2), [0,0]);
  assert.deepEqual(at(80.9), [0,0,0,0]);
  assert.deepEqual(at(4873 / 60), [1,1,1,1]);
  assert.equal(roll(meshes[0]), 5.545601844787598);
  assert.deepEqual(at(4665 / 60), [1,1,1,1]);

  quality.frame_rate_60fps = false;
  assert.deepEqual(at(2332 / 30), [1,1,1,1]);
  quality.stage_control = false;
  assert.deepEqual(at(2332 / 30), [0,0,0,0]);
  quality.stage_control = true;
  source.muted = true;
  assert.deepEqual(at(0), [1,1,1,1]);
  assert.deepEqual(packed(meshes[0]), [117,198,255,152]);
  assert.deepEqual(packed(meshes[2]), [121,198,255,152]);
  source.muted = false;
  assert.deepEqual(at(77), [0,0,0,0]);
  controller.dispose();
  controller.dispose();
  assert.equal(stage.children.some(node => node.isMesh), false);
}

verifyNative();
verifyController().catch(error => { console.error(error); process.exitCode = 1; });
