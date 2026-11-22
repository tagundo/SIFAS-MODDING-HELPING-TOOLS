"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-stage-burst-simulation.js");

const {create} = globalThis.MVStudioStageBurstSimulation;
const f32 = Math.fround;

function sample(stream, frame, fps = 60) {
  const packets = [];
  stream.sample(frame / fps, fps, (...packet) => packets.push(packet));
  return packets;
}

const repeating = {
  kind: "stationaryBurst", duration: f32(1.7), delay: 0,
  burst: {count: 1, time: 0, cycles: 0, period: f32(.6)}, maxParticles: 5,
  lifetime: [.5, .5], size: [2, 2], tiles: [1, 1], sizeMultiplier: 1,
  startColor: [.7358490228652954, .48374712467193604, .2742078900337219, .48235294222831726],
  sizeKeys: [[0, .5, .9322583079338074, .9322583079338074], [1, 1, 0, 0]],
  colorOverLife: {rgb: [[0, 1, 1, 1], [65535, 1, 1, 1]],
    alpha: [[0, 0], [32768, 1], [65535, 0]]},
};
const stages = create(repeating, 2914);
const atBirth = [[0, 0, 0, 1.0000001192092896, 188, 123, 70, 0, 0]];
assert.deepEqual(sample(stages, 0), []);
assert.deepEqual(sample(stages, 1), atBirth);
assert.deepEqual(sample(stages, 16), [[0, 0, 0, 1.7330646514892578, 188, 123, 70, 122, 0]]);
assert.equal(sample(stages, 30)[0][7], 9);
assert.deepEqual(sample(stages, 31), []);
assert.deepEqual(sample(stages, 35), []);
assert.deepEqual(sample(stages, 36), atBirth);
assert.deepEqual(sample(stages, 18, 30), atBirth);
assert.deepEqual(sample(stages, 72), []);
assert.deepEqual(sample(stages, 73), atBirth);
assert.deepEqual(sample(stages, 37, 30), sample(stages, 74));
assert.equal(sample(stages, 102)[0][7], 9);
assert.deepEqual(sample(stages, 103), []);
assert.deepEqual(sample(stages, 73), atBirth);
assert.deepEqual(sample(create(repeating, 8392), 16), sample(stages, 16));

const dense = create({...repeating, duration: f32(.3), lifetime: [f32(.2), f32(.2)],
  maxParticles: 16, burst: {...repeating.burst, period: f32(.005)}}, 2914);
assert.deepEqual([1, 2, 8, 12, 13, 24].map(frame => sample(dense, frame).length), [1, 2, 8, 12, 12, 5]);
assert.deepEqual(sample(dense, 2), sample(dense, 1, 30));
assert.deepEqual(sample(dense, 13)[0], [0, 0, 0, 1.1502354145050049, 188, 123, 70, 20, 0]);

const atlas = {
  kind: "stationaryBurst", duration: 200, delay: 0,
  burst: {count: 1, time: 0, cycles: 1, period: f32(.01)}, maxParticles: 1,
  lifetime: [f32(.9), f32(.9)], size: [1.5, 1.5], tiles: [4, 4], sizeMultiplier: 1,
  startColor: [1, 1, 1, 1], atlas: {start: [0, 0], frame: [.25, .25]},
  sizeKeys: [[0, 0], [.19495202600955963, 1], [.3466334044933319, .3581085205078125],
    [.5212568044662476, 1], [.643391489982605, .22972972691059113], [.794781506061554, 1], [1, 0]]
    .map(([time, value]) => [time, value, 0, 0]),
};
const first = create(atlas, 8784), delayed = create({...atlas, delay: f32(.1), size: [f32(.8), f32(.8)]}, 8784);
assert.deepEqual(sample(first, 1), [[0, 0, 0, 4.060406931473068e-14, 255, 255, 255, 255, 4]]);
assert.deepEqual(sample(first, 13), [[0, 0, 0, 1.4178247451782227, 255, 255, 255, 255, 4]]);
assert.equal(sample(first, 54).length, 1);
assert.deepEqual(sample(first, 55), []);
assert.deepEqual(sample(delayed, 6), []);
assert.deepEqual(sample(delayed, 3, 30), []);
assert.deepEqual(sample(delayed, 7), [[0, 0, 0, 2.1655493357189935e-14, 255, 255, 255, 255, 4]]);
assert.deepEqual(sample(delayed, 4, 30), sample(delayed, 8));
assert.deepEqual(sample(delayed, 35), [[0, 0, 0, .7996253371238708, 255, 255, 255, 255, 4]]);
assert.equal(sample(delayed, 60).length, 1);
assert.deepEqual(sample(delayed, 61), []);
assert.deepEqual(sample(delayed, 13), [[0, 0, 0, .4833817481994629, 255, 255, 255, 255, 4]]);

assert.equal(create({...repeating, burst: {...repeating.burst, period: .001}}, 0), null);
assert.equal(create({...atlas, atlas: {start: [0, .25], frame: [.25, .25]}}, 0), null);
assert.equal(create({...atlas, lifetime: [.5, .75]}, 0), null);
assert.equal(create({...atlas, tiles: [1, 4], atlas: undefined}, 0), null);
assert.equal(create(repeating, -1), null);
console.log("Native stationary bursts preserve repeat edges, start delay, curves, packed color and atlas cells.");
