"use strict";
/* LiveMemberShadowMixer (GL 3.12.0): Process takes the shadowIndex of the input with
   the largest weight (strictly greater, so the first one wins a tie) and sums the
   weighted scales; PostProcess applies (index, scaleX, scaleZ), or (0, 1, 1) when no
   input ran. ShadowComponent.UpdateScale writes (factor * scaleX, 1, factor * scaleZ)
   only when the toe factor moves past the threshold. */
const assert = require("node:assert/strict");
const fs = require("fs");
const vm = require("vm");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
const context = { THREE: T };
context.window = context;
vm.runInNewContext(fs.readFileSync(require.resolve("../webtools/web/static/viewer-motion-timeline.js"), "utf8"), context);
vm.runInNewContext(fs.readFileSync(require.resolve("../webtools/web/static/mv-studio-member-shadow.js"), "utf8"), context);
const shadow = context.MVStudioMemberShadow;
const f32 = Math.fround;
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);

const clip = (start, duration, shadowIndex, shadowScaleX, shadowScaleZ, extra = {}) => ({
  start, duration, values: { playableClass: "LiveMemberShadowClip", shadowIndex, shadowScaleX, shadowScaleZ, easeIn: 0, easeOut: 0,
    blendIn: -1, blendOut: -1, preExtrapolationMode: 0, postExtrapolationMode: 0, preExtrapolationTime: 0, postExtrapolationTime: 0, ...extra } });
// The 11015 track: two index-1 clips, then an index-0 clip blending in over 2.1167 s.
const track = { nativeClass: "LiveMemberShadowTrack", muted: false, events: [
  clip(0, 58.8667, 1, .7, .5), clip(58.8667, 3.6333, 1, .7, 2.5, { blendOut: 2.1167 }),
  clip(60.3833, 55.8167, 0, 1, 1, { blendIn: 2.1167 }) ] };

let result = shadow.sample([track], 10);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [1, f32(.7), f32(.5)]);
result = shadow.sample([track], 59);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [1, f32(.7), f32(2.5)]);
// Mid blend: both inputs run; the scales are summed without normalization.
result = shadow.sample([track], 61.4416);
const w0 = context.ViewerMotionTimeline.weight({ start: 58.8667, duration: 3.6333, timing: { blendOut: 2.1167, blendIn: -1,
  mixOut: [{ time: 0, value: 1 }, { time: 1, value: 0 }] } }, 61.4416);
const w1 = context.ViewerMotionTimeline.weight({ start: 60.3833, duration: 55.8167, timing: { blendIn: 2.1167, blendOut: -1,
  mixIn: [{ time: 0, value: 0 }, { time: 1, value: 1 }] } }, 61.4416);
close(w0 + w1, 1, "blend weights");
assert.equal(result.index, w1 > w0 ? 0 : 1);
close(result.scaleX, .7 * w0 + w1, "weighted X");
close(result.scaleZ, 2.5 * w0 + w1, "weighted Z");
result = shadow.sample([track], 80);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [0, 1, 1]);
// No running input: ApplyShadowParameters(0, 1, 1). No track: nothing applied.
result = shadow.sample([track], 130);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [0, 1, 1]);
assert.equal(shadow.sample([], 10), null);
assert.equal(shadow.sample([{ ...track, muted: true }], 10), null);
// The last track bound to the member manager wins.
const second = { nativeClass: "LiveMemberShadowTrack", muted: false, events: [clip(0, 5, 3, 2, 2)] };
result = shadow.sample([track, second], 1);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [3, 2, 2]);
result = shadow.sample([second, track], 1);
assert.deepEqual([result.index, result.scaleX, result.scaleZ], [1, f32(.7), f32(.5)]);
// Ties keep the first input's index (maxWeight < w is strict).
const tie = { nativeClass: "LiveMemberShadowTrack", events: [clip(0, 5, 4, 1, 1), clip(0, 5, 6, 1, 1)] };
assert.equal(shadow.sample([tie], 1).index, 4);

async function scales() {
  const actor = new T.Group(), layer = new T.Group();
  const node = (id, position) => { const object = new T.Object3D(); object.userData.elichika_node = id; object.position.set(...position); actor.add(object); return object; };
  const leftToe = node(1, [-.2, .05, 0]); node(2, [.2, .05, 0]); node(3, [0, 0, 0]); node(4, [0, 0, 0]);
  actor.userData.mvMemberShadow = { schema: 1, toes: [1, 2], anchors: [3, 4], geometry: { POSITION: 0, TEXCOORD_0: 1, indices: 2 }, texture: 0 };
  const geometry = new T.CircleGeometry(1, 10).rotateX(-Math.PI / 2), texture = new T.Texture({ width: 128, height: 128 });
  const parser = { getDependency: (kind, id) => Promise.resolve(kind === "texture" ? texture : [geometry.attributes.position, geometry.attributes.uv, geometry.index][id]) };
  const instance = await shadow.apply(T, actor, parser, layer);
  const [left] = layer.children;
  const factor = f32(f32(.15) - f32(.05));
  const width = () => { left.matrix.decompose(new T.Vector3(), new T.Quaternion(), scaleOut); return [scaleOut.x, scaleOut.z]; };
  const scaleOut = new T.Vector3();
  instance.update(true, false, null);
  width().forEach((value, axis) => close(value, factor, "default scale " + axis));
  instance.update(true, false, { index: 1, scaleX: .7, scaleZ: 2.5 });
  close(width()[0], f32(factor * f32(.7)), "scrub X");
  close(width()[1], f32(factor * f32(2.5)), "scrub Z");
  // Playback keeps the latched width until the factor moves past the threshold.
  instance.update(true, true, { index: 0, scaleX: 1, scaleZ: 1 });
  close(width()[1], f32(factor * f32(2.5)), "latched Z");
  leftToe.position.y = .03;
  instance.update(true, true, { index: 0, scaleX: 1, scaleZ: 1 });
  close(width()[1], f32(f32(.15) - f32(.03)), "updated with the factor");
  instance.dispose();
}

scales().then(() => console.log("PASS: LiveMemberShadowMixer index/scale rule and UpdateScale latch"),
  (error) => { console.error(error); process.exitCode = 1; });
