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

// LiveCoreMember.Initialize merges the ske_ prop skeleton into the member:
// the renderer follows its own merged node (chp*/Attach_*/Decor), which the
// member's dance clip animates, never the bare hand bone.
const hand2 = "Reference/Move/RightHand";
const decorPath = hand2 + "/chp0001/Attach_01/Attach_02/Attach_03/Decor";
const merged = { root: new T.Group(), rig: { bones: [
  { path: hand2, node: 5 }, { path: hand2 + "/chp0001", node: 6, propSkeleton: true },
  { path: hand2 + "/chp0001/Attach_01", node: 7, propSkeleton: true },
  { path: decorPath, node: 8, propSkeleton: true }
] } };
const handNode = new T.Bone(), attach = new T.Object3D(), decor = new T.Object3D();
handNode.userData.elichika_node = 5; attach.userData.elichika_node = 7; decor.userData.elichika_node = 8;
merged.root.add(handNode); handNode.add(attach); attach.add(decor);
handNode.position.set(0, 1, 0);
const fanRoot = new T.Group(), fanGeometry = new T.BufferGeometry();
fanGeometry.setAttribute("position", new T.Float32BufferAttribute([0, 0, 0], 3));
fanGeometry.setAttribute("_mv_fan_uv", new T.Float32BufferAttribute([0, 0], 2));
fanRoot.add(new T.Mesh(fanGeometry));
const fan = MVStudioProps.create(fanRoot, {
  kind: "fan", bone: decorPath, track: "motion", activation: ["active"], limit: 135,
  defaultVisible: true, defaultAngle: 0, curves: {}
});
fan.setTracks([{ id: "active", events: [{ start: 0, duration: 2 }] }]);
fan.bind(merged);
assert.equal(fanRoot.parent, decor);
// The dance clip moves Attach_01 (here 7 cm out of the fist): the fan follows.
attach.position.set(.0718, .0338, .0082);
attach.quaternion.setFromEuler(new T.Euler(.5, -1.2, 1.1));
merged.root.updateMatrixWorld(true);
const world = new T.Vector3().setFromMatrixPosition(fanRoot.matrixWorld);
assert.ok(world.distanceTo(new T.Vector3(.0718, 1.0338, .0082)) < 1e-6);
assert.ok(new T.Quaternion().setFromRotationMatrix(fanRoot.matrixWorld).angleTo(attach.quaternion) < 1e-6);
// An actor whose rig has no merged node shows no prop rather than one at the hand.
fan.detach(merged);
fan.bind({ root: merged.root, rig: { bones: [{ path: hand2, node: 5 }] } });
fan.evaluate(0);
assert.equal(fanRoot.parent, null);
assert.equal(fanRoot.visible, false);
console.log("MV prop native coverage: exact merged node, dance-driven attach, shader rotation limits, activation, and detach.");
