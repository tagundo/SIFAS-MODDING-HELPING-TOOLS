"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-moving-burst-simulation.js");

const f32 = Math.fround;
// Original paired Countdown star, first fixed-seed emitter.
const profile = {
  mode: "movingBillboard", seed: 1168667589, duration: 5, delay: 0, count: 10,
  lifetime: [f32(.6), f32(.4)], size: [f32(.2), 1], startSpeed: 10, startRoll: .2094395011663437,
  startColor: {rgb: [[0, 1, .8809999823570251, .9392603635787964], [65535, 1, .20779696106910706, 0]],
    alpha: [[0, 1], [65535, 1]]},
  shape: {angle: 90, radius: f32(1.18)}, sizeMultiplier: 1,
  sizeKeys: [[0, .5902205109596252, 3.2275702953338623, 3.2275702953338623],
    [.23725487291812897, 1, 0, 0], [1, 0, -2.6208386421203613, -2.6208386421203613]],
  spin: [-1.570796251296997, 1.570796251296997],
  clamp: {limit: 1, dampen: f32(.15), drag: {multiplier: 10,
    minKeys: [[0, 0, 0, 18.467145919799805], [.029518306255340576, .5451188683509827, 0, 0]],
    maxKeys: [[0, 0, 30.958646774291992, 50.7831916809082], [.019691554829478264, 1, 0, 0]],
  }},
};

function sample(stream, time, fps) {
  const result = [];
  stream.sample(time, fps, (...packet) => result.push(packet));
  return result;
}

function check(rows, expected) {
  for (const [index, packet] of expected.entries()) {
    for (let axis = 0; axis < 3; axis++) assert.ok(Math.abs(rows[index][axis] - packet[axis]) <= 3e-7);
    assert.deepEqual(rows[index].slice(3), packet.slice(3));
  }
}

const stream = MVStudioMovingBurstSimulation.create(profile);
assert.ok(stream);
assert.deepEqual(sample(stream, 0, 60), []);
const first = sample(stream, 1 / 60, 60);
assert.equal(first.length, 10);
check(first, [
  [.973302960395813, 0, 0, .29053547978401184, .29053547978401184, .2094395011663437, 255, 164, 155, 255],
  [.6911735534667969, .5021669864654541, 0, .41914102435112, .41914102435112, .20943951606750488, 255, 190, 191, 255],
]);
const grouped = sample(stream, 1 / 30, 30);
assert.deepEqual(grouped, sample(stream, 2 / 60, 60));
// The second shape normalization changes these coordinates by one float32 step.
assert.deepEqual(grouped[7].slice(0, 3), [-.18804310262203217, -.5787362456321716, 0]);
check(grouped, [
  [1.1282627582550049, 0, 0, .33709916472435, .33709916472435, .2028735727071762, 255, 164, 155, 255],
  [.8165386319160461, .5932500958442688, 0, .4891122579574585, .4891122579574585, .22467191517353058, 255, 190, 191, 255],
]);
check(sample(stream, 8 / 60, 60), [
  [1.675052523612976, 0, 0, .49052995443344116, .49052995443344116, .16347800195217133, 255, 164, 155, 255],
]);
const tail = sample(stream, 36 / 60, 60);
assert.equal(tail.length, 3);
check(tail, [
  [1.0630265474319458, -.7723339200019836, 0, .0011921970872208476, .0011921970872208476, -.5216621160507202, 255, 69, 22, 255],
  [-1.9749295711517334, 1.4348701238632202, 0, .02438276633620262, .02438276633620262, -.2555437386035919, 255, 204, 210, 255],
]);
assert.deepEqual(sample(stream, 37 / 60, 60), []);
assert.deepEqual(sample(stream, 1 / 60, 60), first, "backward scrubs recover the same burst");

const delayed = MVStudioMovingBurstSimulation.create({...profile, seed: 3690583535, delay: f32(.4)});
assert.equal(sample(delayed, 23 / 60, 60).length, 0);
const delayedWake = sample(delayed, 24 / 60, 60);
assert.equal(delayedWake.length, 10);
assert.deepEqual(delayedWake, sample(delayed, 12 / 30, 30));
check(delayedWake, [
  [.7392835021018982, 0, 0, .5522946715354919, .5522946715354919, .2094395011663437, 255, 207, 215, 255],
]);
assert.equal(MVStudioMovingBurstSimulation.create({...profile, shape: {...profile.shape, angle: 45}}), null);
assert.equal(MVStudioMovingBurstSimulation.create({...profile, count: 65}), null);
console.log("Native moving bursts match the seeded Cone4 launch, damping/drag, raw spin, and compacted order.");
