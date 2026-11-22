"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-butterfly-simulation.js");

const {create} = MVStudioButterflySimulation;
assert.equal(create(-1), null);
assert.equal(create(2 ** 32), null);
assert.equal(create(10.5), null);

// Android Unity seed 2914 emitted native particle seed 311713401.
// Its four StableRandomXYZW fields were read from the original mesh writer.
const simulation = create(2914);
const random = [0.09466506540775299, 0.556060254573822, 0.1459573656320572, 0.8557432889938354];
assert.deepEqual(simulation.random, random);
assert.deepEqual(create(2914).random, random);
assert.notDeepEqual(create(0).random, random);
assert.equal(simulation.sample(0, 60), null);
assert.equal(simulation.sample(1 / 60, 30), null);
assert.equal(simulation.sample(1, 120), null);
assert.equal(simulation.sample(30, 60), null);

// Original native XYZ coordinates reflected on X for the viewer.
const first = [-1.666666804567285e-11, -1.666666804567285e-11, 0];
const second = [-1.666668504185509e-5, -1.666668504185509e-5, 0];
const late = [-0.012983386404812336, -0.012983386404812336, 0];
assert.deepEqual(simulation.sample(1 / 60, 60), first);
assert.deepEqual(simulation.sample(2 / 60, 60), second);
assert.deepEqual(simulation.sample(1 / 30, 30), second);
assert.deepEqual(simulation.sample(2, 60), [-0.001983335940167308, -0.001983335940167308, 0]);
assert.deepEqual(simulation.sample(13, 60), late);
assert.deepEqual(simulation.sample(13, 30), late);
assert.deepEqual(simulation.sample(1 / 60, 60), first);
assert.deepEqual(simulation.random, random);
