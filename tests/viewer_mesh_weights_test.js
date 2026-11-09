/* The production skin brush math must preserve locks and the requested new bone
 * even when that adds a fifth influence to a four-slot Unity skin. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-mesh-tools.js'), 'utf8'), context);
const { redistributeInfluence: edit, normalizeInfluences: normalize, circleIntersectsTriangle: hits } = context.window.ViewerMeshTools;
const plain = value => JSON.parse(JSON.stringify(value));
function close(actual, expected) { assert(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`); }
function weight(values, bone) { return (values.find(([index]) => index === bone) || [bone, 0])[1]; }
function valid(values) { assert(values.length <= 4); values.forEach(([bone, weight]) => { assert(Number.isInteger(bone)); assert(weight > 0 && weight <= 1); }); close(values.reduce((sum, [, weight]) => sum + weight, 0), 1); }
const original = [[0, .4], [1, .3], [2, .2], [3, .1]];
const before = JSON.stringify(original);
const fifth = edit(original, 4, .05, {});
valid(fifth); close(weight(fifth, 4), .05); assert(!fifth.some(([bone]) => bone === 3), 'drop the weakest old influence, retaining the new painted bone');
const locked = edit(original, 4, .08, { 0: true });
valid(locked); close(weight(locked, 0), .4); close(weight(locked, 4), .08);
assert(!locked.some(([bone]) => bone === 3));
const threeLocks = edit(original, 4, .03, { 0: true, 1: true, 2: true });
valid(threeLocks); close(weight(threeLocks, 0), .4); close(weight(threeLocks, 1), .3); close(weight(threeLocks, 2), .2); close(weight(threeLocks, 4), .1);
assert.equal(threeLocks.length, 4, 'three locked slots leave exactly one normalized remaining slot');
assert.deepStrictEqual(plain(edit(original, 4, .5, { 0: true, 1: true, 2: true, 3: true })), original, 'four locked slots remain unchanged');
assert.deepStrictEqual(plain(edit(original, 0, .8, { 0: true })), original, 'a locked destination is unchanged');
assert.deepStrictEqual(plain(edit([[0, 1]], 0, 0, {})), [[0, 1]], 'removing the only influence must not create a zero sum');
const transfer = edit([[0, .8], [1, .2]], 1, .6, {}, { 0: .4, 1: .6 });
valid(transfer); close(weight(transfer, 0), .4); close(weight(transfer, 1), .6);
assert.equal(JSON.stringify(original), before, 'editing never changes the immutable input weights');
const combined = normalize([[0, .2], [0, .3], [1, .5]], {}, []); valid(combined); close(weight(combined, 0), .5);
assert(hits(.2, .2, .01, [0, 0], [1, 0], [0, 1]), 'inside a UV triangle');
assert(!hits(.8, .8, .01, [0, 0], [1, 0], [0, 1]), 'outside a UV triangle');
assert(hits(.8, .8, .43, [0, 0], [1, 0], [0, 1]), 'brush edge intersects UV triangle');
console.log('PASS: skin normalization, locked slots, fifth influence, transfer, UV brush intersection');
