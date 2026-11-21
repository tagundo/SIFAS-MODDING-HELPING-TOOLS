"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.window = global;
require("../webtools/web/static/mv-studio-props.js");

const root = new T.Group(), geometry = new T.BufferGeometry();
const positions = new T.Float32BufferAttribute([1, 0, 0, 1, 0, 0], 3);
geometry.setAttribute("position", positions);
geometry.setAttribute("_mv_fan_uv", new T.Float32BufferAttribute([0, 0, .25, 0], 2));
root.add(new T.Mesh(geometry));
const path = "Reference/Move/RightHand";
const actor = { root: new T.Group(), rig: { bones: [{ path: "Model/" + path, node: 42 }] } };
const hand = new T.Bone();
hand.userData.elichika_node = 42;
actor.root.add(hand);

const prop = MVStudioProps.create(root, {
  kind: "fan", bone: path, track: "motion", activation: ["active"], limit: 135,
  defaultVisible: true, defaultAngle: 0,
  curves: { cue: { mode: "cubic", first: 0, last: 1,
    keys: [[0, [0, 0, 90, 0]], [1, [0, 0, 0, 90]]] } }
});
assert.ok(prop);
prop.setTracks([
  { id: "motion", events: [{ id: "cue", start: 0, duration: 2, values: {} }] },
  { id: "active", events: [{ start: 0, duration: 2 }] }
]);
prop.bind(actor);
assert.equal(root.parent, hand);
prop.evaluate(0);
assert.equal(root.visible, true);
assert.deepEqual([...positions.array], [1, 0, 0, 1, 0, 0]);
prop.evaluate(1);
assert.ok(Math.abs(positions.getX(0)) < 1e-7);
assert.ok(Math.abs(positions.getZ(0) - 1) < 1e-7);
assert.ok(Math.abs(positions.getZ(1) - Math.sin(7 * Math.PI / 180)) < 1e-7);
prop.evaluate(2);
assert.equal(root.visible, false);
prop.detach(actor);
assert.equal(root.parent, null);
prop.bind({ root: actor.root, rig: { bones: [
  { path, node: 42 }, { path: "Model/" + path, node: 77 }
] } });
prop.evaluate(0);
assert.equal(root.parent, null);
assert.equal(root.visible, false);
console.log("MV prop native coverage: exact hand, shader rotation limits, activation, and detach.");
