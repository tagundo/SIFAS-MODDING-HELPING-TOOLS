"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");

const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/dtoAAAAASUVORK5CYII=";
const constant = value => ["constant", value];
const animation = (x, slope, end) => ["cubic", [
  [-3.4028234663852886e38, [0, 0, 0, x]],
  [0, [0, 0, slope, x]],
  [5.333333492279053, [0, 0, 0, end]]
]];
const windowStart = 5.833333333333333;
const windowLength = 5.333333333333333;
const track = { id: "title:track", nativeClass: "CustomControlTrack", events: [{
  id: "title:event", start: windowStart, duration: windowLength, values: { playableClass: "CustomControlClip",
    clipIn: 0, timeScale: 1, weight: 1, offset: { x: 0, y: 0, z: 0 }
  }
}] };
const descriptor = {
  textures: [{ png, width: 1, height: 1 }],
  geometry: {
    positions: [[.5, -.5, 0], [-.5, .5, 0], [-.5, -.5, 0], [.5, .5, 0]],
    uv: [[0, 1], [1, 0], [1, 1], [0, 0]], indices: [0, 2, 1, 1, 3, 0]
  },
  cues: [{
    trackId: track.id, eventId: track.events[0].id, texture: 0,
    material: { tint: [1, 1, 1, 1], uv: [1, 1, 0, 0], queue: 2900 },
    meshes: [
      { path: 123, name: "title_R", position: [6.5, 1.75, -2.4], rotation: [0, -.9659258, 0, -.258819], scale: [7, 8, 1] },
      { path: 456, name: "title_L", position: [-6.5, 1.75, -2.4], rotation: [0, -.9659258, 0, .258819], scale: [7, 8, 1] }
    ],
    animation: { start: 0, duration: 5.333333492279053, loop: false, channels: [
      { kind: "overlayUV", path: 123, curves: [constant(1), constant(.25),
        animation(-.16619427502155304, .09375, .33380573987960815), constant(.75)] },
      { kind: "overlayUV", path: 456, curves: [constant(1), constant(.25),
        animation(.16619427502155304, -.09375, -.33380573987960815), constant(.75)] }
    ] }
  }]
};

function compare(current, expected) {
  current.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-12,
    `index ${index}: expected ${expected[index]}, found ${value}`));
}

async function run() {
  const root = new T.Scene(), project = { tracks: [track], quality: { values: { stage_display: true } } };
  let texture, calls = 0, imagesDisposed = 0;
  const testThree = { ...T, TextureLoader: class {
    async loadAsync(url) {
      assert.equal(url, "data:image/png;base64," + png);
      calls++;
      texture = new T.Texture({ width: 1, height: 1 });
      texture.addEventListener("dispose", () => imagesDisposed++);
      return texture;
    }
  } };
  const wrong = structuredClone(descriptor);
  wrong.textures[0].width = 2;
  assert.equal(await MVStudioTitle.apply(testThree, root, wrong), null);
  assert.equal(calls, 0, "IHDR must be checked before decoding");
  wrong.textures[0].width = 1;
  wrong.cues[0].animation.channels[1].path = 123;
  assert.equal(await MVStudioTitle.apply(testThree, root, wrong), null);
  assert.equal(calls, 0);

  const title = await MVStudioTitle.apply(testThree, root, descriptor);
  assert.ok(title);
  assert.equal(calls, 1);
  const [group] = root.children;
  const [right, left] = group.children;
  assert.equal(group.visible, false);
  assert.deepEqual(right.position.toArray(), [6.5, 1.75, -2.4]);
  assert.equal(right.geometry, left.geometry);
  assert.notEqual(right.material, left.material);
  assert.equal(right.layers.mask, 1);
  assert.equal(right.material.stencilWrite, true);
  assert.equal(right.material.stencilFunc, T.EqualStencilFunc);
  assert.equal(right.material.stencilRef, 2);
  assert.equal(right.material.stencilFuncMask, 255);
  assert.equal(right.material.stencilWriteMask, 255);
  assert.equal(right.material.stencilFail, T.KeepStencilOp);
  assert.equal(right.material.stencilZFail, T.KeepStencilOp);
  assert.equal(right.material.stencilZPass, T.KeepStencilOp);
  assert.equal(right.material.depthTest, true);
  assert.equal(right.material.depthWrite, false);
  assert.equal(right.material.depthFunc, T.LessEqualDepth);
  assert.equal(right.material.side, T.DoubleSide);
  assert.equal(right.material.blendSrc, T.SrcAlphaFactor);
  assert.equal(right.material.blendDst, T.OneMinusSrcAlphaFactor);
  assert.equal(right.renderOrder, 2900);
  assert.equal(texture.encoding, T.LinearEncoding);
  assert.equal(texture.minFilter, T.LinearMipmapNearestFilter);
  assert.equal(texture.magFilter, T.LinearFilter);
  assert.equal(texture.wrapS, T.RepeatWrapping);
  assert.equal(texture.wrapT, T.RepeatWrapping);
  assert.equal(texture.flipY, false);

  title.update(windowStart - 1e-6, project);
  assert.equal(group.visible, false);
  title.update(windowStart, project);
  assert.equal(group.visible, true);
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.16619427502155304, 0]);
  title.update(windowStart + 1, project);
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);
  compare(left.material.uniforms.uTextureST.value.toArray(), [1, .25, .07244427502155304, 0]);
  title.update(windowStart + windowLength, project);
  assert.equal(group.visible, false);
  title.update(windowStart + 1, project);
  assert.equal(group.visible, true, "random access after end");
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);

  project.quality.values.stage_display = false;
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  project.quality.values.stage_display = true;
  track.muted = true;
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  track.muted = false;
  track.events[0].values.offset.x = 1;
  title.update(windowStart, project);
  assert.equal(group.visible, false, "non-neutral control offset");
  track.events[0] = { ...track.events[0], start: 15, values: { ...track.events[0].values, offset: { x: 0, y: 0, z: 0 } } };
  title.invalidate();
  title.update(windowStart, project);
  assert.equal(group.visible, false);
  title.update(16, project);
  assert.equal(group.visible, true, "timeline event timing stays editable");
  compare(right.material.uniforms.uTextureST.value.toArray(), [1, .25, -.07244427502155304, 0]);

  let materials = 0, geometries = 0;
  right.material.addEventListener("dispose", () => materials++);
  left.material.addEventListener("dispose", () => materials++);
  right.geometry.addEventListener("dispose", () => geometries++);
  title.dispose();
  title.dispose();
  assert.equal(imagesDisposed, 1);
  assert.equal(materials, 2);
  assert.equal(geometries, 1);
  assert.equal(root.children.length, 0);
  console.log("Native stage title: bounded texture and quad, stencil reader, authored UV motion, timeline edits and scene cleanup.");
}

async function runParticles() {
  const root = new T.Scene(), source = structuredClone(descriptor);
  const particleTrack = { id: "main:track", nativeClass: "CustomControlTrack", events: [{
    id: "main:event", start: 20, duration: 4, values: { playableClass: "CustomControlClip", clipIn: 0,
      timeScale: 1, weight: 1, offset: { x: 0, y: 0, z: 0 } }
  }] };
  const emitter = { ...source.cues[0].meshes[0], name: "title_main", texture: 0,
    material: { ...source.cues[0].material, tint: [.5, 1, 1, 1] },
    size: [4.65, 2.25], lifetime: 2, active: [0, 1.5], atlas: { tiles: [1, 4], row: 0, frame: constant(0) },
    sizeCurves: [constant(1), ["linear", [[0, 1], [1, 2]]]],
    color: { rgb: [[0, 1, 1, 1]], alpha: [[0, 1], [.5, .5], [1, 0]] }
  };
  const vanish = { ...emitter, name: "title_vanish", active: [1.5, null],
    atlas: { tiles: [2, 4], row: null, frame: ["linear", [[0, 0], [1, 1]]] } };
  const unsupported = { ...emitter, name: "unsupported", atlas: { ...emitter.atlas, row: 4 } };
  const eventId = particleTrack.events[0].id;
  source.particles = [
    { trackId: particleTrack.id, eventId, emitters: [emitter, vanish] },
    { trackId: particleTrack.id, eventId, emitters: [unsupported] }
  ];
  const secondCue = {
    ...structuredClone(source.cues[0]), trackId: particleTrack.id, eventId,
    animation: { start: 0, duration: 2, loop: false, channels: [
      { kind: "translation", path: 123, curves: [["linear", [[0, -8], [1, 0]]], constant(.47), constant(-7)] },
      { kind: "overlayTint", path: 123, curves: [["linear", [[0, 1], [1, 0]]], constant(.75), constant(1), constant(1)] },
      { kind: "overlayUV", path: 123, curves: [constant(1), constant(.25), constant(0), constant(.62)] },
      { kind: "overlayUV", path: 456, curves: [constant(1), constant(.25), constant(0), constant(.87)] }
    ] }
  };
  secondCue.meshes[0].name = "title_up";
  secondCue.meshes[1].name = "title_doun";
  source.cues.push(secondCue);
  const project = { tracks: [track, particleTrack], quality: { values: { stage_display: true } } };
  let loads = 0;
  const local = { ...T, TextureLoader: class {
    async loadAsync() {
      loads++;
      return new T.Texture({ width: 1, height: 1 });
    }
  } };
  const invalid = structuredClone(source);
  invalid.cues[1].animation.channels.push(invalid.cues[1].animation.channels[0]);
  assert.equal(await MVStudioTitle.apply(local, root, invalid), null, "reject duplicate writes to a single mesh channel");
  const title = await MVStudioTitle.apply(local, root, source);
  assert.ok(title);
  assert.equal(loads, 1, "mesh titles and particles share their texture");
  assert.equal(root.children.length, 3, "two mesh cues coexist with one supported particle group");
  const [quads, animated, group] = root.children;
  const [top, bottom] = animated.children;
  const [mesh, second] = group.children;
  assert.equal(mesh.geometry, quads.children[0].geometry);
  assert.equal(mesh.material.name, "Native stage title particle");
  assert.equal(mesh.material.stencilFunc, T.EqualStencilFunc);
  assert.equal(mesh.material.stencilRef, 2);
  assert.equal(mesh.renderOrder, 2900);

  title.update(19.99, project);
  assert.equal(group.visible, false);
  title.update(20.5, project);
  assert.equal(group.visible, true);
  assert.equal(mesh.visible, true);
  assert.equal(second.visible, false);
  assert.equal(animated.visible, true, "mesh and particle groups can share one track/event");
  compare(top.position.toArray(), [4, .47, -7]);
  compare(top.material.uniforms.uTint.value.toArray(), [.5, .75, 1, 1]);
  compare(top.material.uniforms.uTextureST.value.toArray(), [1, .25, 0, .13]);
  compare(bottom.position.toArray(), secondCue.meshes[1].position);
  compare(bottom.material.uniforms.uTint.value.toArray(), [1, 1, 1, 1]);
  compare(bottom.material.uniforms.uTextureST.value.toArray(), [1, .25, 0, -.12]);
  compare(mesh.scale.toArray(), [7 * 4.65, 8 * 2.25 * 1.25, 1]);
  compare(mesh.material.uniforms.uTint.value.toArray(), [.5, 1, 1, .75]);
  compare(mesh.material.uniforms.uTextureST.value.toArray(), [1, .25, 0, 0]);

  title.update(21.5, project);
  assert.equal(mesh.visible, false);
  assert.equal(second.visible, true);
  compare(second.material.uniforms.uTextureST.value.toArray(), [.5, .25, 0, 0]);
  title.update(22.8, project);
  compare(second.material.uniforms.uTextureST.value.toArray(), [.5, .25, .5, .5]);
  title.update(23.5, project);
  assert.equal(second.visible, false);
  title.update(24, project);
  assert.equal(group.visible, false);
  title.update(20.5, project);
  assert.equal(mesh.visible, true, "rewind reconstructs deterministic life and gradient");
  compare(mesh.material.uniforms.uTint.value.toArray(), [.5, 1, 1, .75]);
  compare(top.position.toArray(), [4, .47, -7]);
  compare(top.material.uniforms.uTint.value.toArray(), [.5, .75, 1, 1]);
  particleTrack.muted = true;
  title.update(20.5, project);
  assert.equal(group.visible, false);
  assert.equal(animated.visible, false);

  let disposed = 0;
  mesh.material.addEventListener("dispose", () => disposed++);
  second.material.addEventListener("dispose", () => disposed++);
  title.dispose();
  assert.equal(disposed, 2);
  assert.equal(root.children.length, 0);
  console.log("Native title cues: shared texture, absolute mesh translation and tint, fixed particle bursts, atlas, scrub and cleanup.");
}

async function runSeededParticles() {
  const root = new T.Scene(), source = structuredClone(descriptor);
  const event = { id: "pair:event", start: 8, duration: 1.9, values: { playableClass: "CustomControlClip",
    clipIn: 0, timeScale: 1, weight: 1, offset: { x: 0, y: 0, z: 0 } } };
  const pairTrack = { id: "pair:track", nativeClass: "CustomControlTrack", events: [event] };
  const atlas = { tiles: [2, 4], row: null, period: .5, frame: ["cubic", [
    [0, [0, 0, 0, 0]], [Math.fround(.05), [0, 0, 0, Math.fround(.9999)]], [.5, [0, 0, 0, Math.fround(.9999)]]
  ]] };
  const base = { ...source.cues[0].meshes[0], name: "title", texture: 0, material: source.cues[0].material,
    scale: [1.5, 1, 1], active: [0, null], atlas, sizeCurves: [constant(.75), constant(.75)] };
  source.particles = [{ trackId: pairTrack.id, eventId: event.id, emitters: [
    { ...base, size: [18.36803436279297, 18.36803436279297], lifetime: 2.9159176349639893,
      color: { rgb: [[0, 228 / 255, 10 / 255, 56 / 255]], alpha: [[0, 1]] } },
    { ...base, size: [18.04229736328125, 18.04229736328125], lifetime: 3.2112085819244385,
      color: { rgb: [[0, 1, 1, 1]], alpha: [[0, 1]] } }
  ] }];
  const local = { ...T, TextureLoader: class {
    async loadAsync() { return new T.Texture({ width: 1, height: 1 }); }
  } };
  const invalid = structuredClone(source);
  invalid.particles[0].emitters[1].atlas.period = 0.6;
  const rejected = await MVStudioTitle.apply(local, root, invalid);
  assert.ok(rejected);
  assert.equal(root.children.length, 1, "an unsupported loop drops the whole pair and keeps the mesh title");
  rejected.dispose();

  const title = await MVStudioTitle.apply(local, root, source);
  assert.ok(title);
  assert.equal(root.children.length, 2);
  const pair = root.children[1], [red, white] = pair.children;
  const project = { tracks: [track, pairTrack], quality: { values: { stage_display: true } } };
  title.update(8, project);
  assert.equal(pair.visible, true);
  compare(red.material.uniforms.uTint.value.toArray(), [228/255, 10/255, 56/255, 1]);
  compare(white.material.uniforms.uTint.value.toArray(), [1, 1, 1, 1]);
  compare(red.scale.toArray(), [1.5 * Math.fround(18.36803436279297 * .75), Math.fround(18.36803436279297 * .75), 1]);
  compare(red.material.uniforms.uTextureST.value.toArray(), [.5, .25, 0, 0]);

  title.update(8.2, project);
  compare(red.material.uniforms.uTextureST.value.toArray(), [.5, .25, .5, .75]);
  title.update(9.5, project);
  compare(red.material.uniforms.uTextureST.value.toArray(), [.5, .25, 0, 0]);
  compare(white.material.uniforms.uTextureST.value.toArray(), [.5, .25, .5, .75]);
  title.update(9.9, project);
  assert.equal(pair.visible, false, "the emitter stops at the cue end, even with surviving particles");
  title.update(9.5, project);
  compare(red.material.uniforms.uTextureST.value.toArray(), [.5, .25, 0, 0]);
  compare(white.material.uniforms.uTextureST.value.toArray(), [.5, .25, .5, .75]);
  project.quality.values.stage_display = false;
  title.update(9.5, project);
  assert.equal(pair.visible, false);
  title.dispose();
  assert.equal(root.children.length, 0);
  console.log("Native title pair: independent life, colors and looped sheets, rewind, and cue/quality gating.");
}

async function runStockParticleCadence() {
  const root = new T.Scene(), source = structuredClone(descriptor), f32 = Math.fround;
  const prefab = (id, path, start, duration) => ({id, start, duration, values: {playableClass: "CustomControlClip",
    clipIn: 0, timeScale: 1, weight: 1, offset: {x: 0, y: 0, z: 0}, prefabGameObject: {m_FileID: 0, m_PathID: path}}});
  const first = prefab("01", "-8435186680480702496", 5.833333333333333, 1.9333333333333336);
  const second = prefab("02", "4756982803957209729", 7.766666666666667, 1.9);
  const third = prefab("03", "678762954342101232", 9.666666666666666, 1.833333333333334);
  const nativeTrack = {id: "main-title", label: "StageEffect/Expert/Display/Title_mainDis",
    nativeClass: "CustomControlTrack", events: [first, second, third]};
  const base = {name: "title", texture: 0, scale: [1, 1, 1], active: [0, null], position: [0, f32(3.05), -7],
    rotation: [0, -1, 0, 0], size: [5, 5], lifetime: 1.5, sizeCurves: [constant(1), constant(1)],
    material: source.cues[0].material, atlas: {tiles: [1, 4], row: 0, frame: constant(0)},
    color: {rgb: [[0, 1, 1, 1]], alpha: [[0, 1]]}};
  // The .02 fixed seed pair has separate birth lifetimes, color and size
  // lanes. Its original 2x4 atlas repeats every half of normalized age.
  const pairAtlas = {tiles: [2, 4], row: null, period: .5, frame: ["cubic",
    [0, 1, .7, .2, .65, .1, .9, .4, .6, .2, 1].map((phase, index) =>
      [f32(index / 20), [0, 0, 0, f32(f32(phase) * f32(.9999))]])]};
  const redWidth = 18.36803436279297, whiteWidth = 18.04229736328125;
  const mainEnd = 1.1663333177566528, subStart = 1.1666666269302368, subEnd = 1.850000023841858;
  const emitters = [[{...base, name: "title_main", lifetime: 2, size: [f32(4.65), 2.25],
    color: {...base.color, alpha: [[42598 / 65535, 0], [49151 / 65535, 1]]}}], [
    {...base, atlas: pairAtlas, size: [redWidth, redWidth], lifetime: 2.9159176349639893,
      color: {...base.color, rgb: [[0, 228 / 255, 10 / 255, 56 / 255]]}},
    {...base, atlas: pairAtlas, size: [whiteWidth, whiteWidth], lifetime: 3.2112085819244385},
  ], [
    {...base, name: "title_main", active: [0, mainEnd]},
    {...base, name: "square", active: [0, subEnd]},
    {...base, name: "title_sub", active: [subStart, subEnd], atlas: {...base.atlas, row: 1}},
  ]];
  source.particles = nativeTrack.events.map((event, i) => ({trackId: nativeTrack.id, eventId: event.id, emitters: emitters[i]}));
  const local = {...T, TextureLoader: class {async loadAsync() { return new T.Texture({width: 1, height: 1}); }}};
  const title = await MVStudioTitle.apply(local, root, source);
  assert.ok(title);
  const [, opening, pair, closing] = root.children, [red, white] = pair.children;
  const [main, square, sub] = closing.children;
  const settings = {stage_display: true, frame_rate_60fps: true};
  const project = {tracks: [nativeTrack], quality: {values: settings}};
  const textureST = mesh => mesh.material.uniforms.uTextureST.value.toArray();
  title.update(first.start, project);
  assert.equal(opening.visible, true);
  assert.equal(opening.children[0].visible, false, "a native emitter has no particle before its first simulation tick");
  title.update(first.start + 1 / 60, project);
  assert.equal(opening.children[0].visible, true);
  settings.frame_rate_60fps = false;
  title.update(first.start + 1 / 60, project);
  assert.equal(opening.children[0].visible, false, "30 Hz paint has no completed frame at a single native tick");
  title.update(first.start + 1 / 30, project);
  assert.equal(opening.children[0].visible, true);

  title.update(second.start, project);
  assert.equal(opening.visible, false);
  assert.equal(pair.visible, true);
  assert.equal(red.visible, false);
  for (const fps of [30, 60]) {
    settings.frame_rate_60fps = fps === 60;
    title.update(second.start + 1 / 6, project);
    assert.equal(red.visible, true);
    compare(textureST(red), [.5, .25, .5, .75]); // Native lane 0 tile 7.
    compare(textureST(white), [.5, .25, 0, 0]); // Native lane 1 is still on tile 0.
    title.update(second.start + .2, project);
    compare(textureST(white), [.5, .25, .5, .75]);
    title.update(second.start + 1.5, project);
    compare(textureST(red), [.5, .25, 0, 0]);
    compare(textureST(white), [.5, .25, .5, 0]); // Native lane 1 tile 1 before its wrap.
  }

  title.update(third.start + mainEnd - 1e-6, project);
  assert.equal(main.visible, true);
  title.update(third.start + mainEnd, project);
  assert.equal(main.visible, false);
  title.update(third.start + subStart, project);
  assert.equal(sub.visible, false, "the late renderer owns its activation clock");
  title.update(third.start + subStart + 1 / 60, project);
  assert.equal(sub.visible, true);
  compare(textureST(sub), [1, .25, 0, .25]);
  title.update(third.start + 90 / 60, project);
  assert.equal(square.visible, true, "the 1.5-second square survives native tick 90");
  title.update(third.start + 91 / 60, project);
  assert.equal(square.visible, false);
  settings.frame_rate_60fps = false;
  title.update(third.start + 91 / 60, project);
  assert.equal(square.visible, true, "ordinary playback holds tick 90 until the next 30 Hz paint");
  title.update(third.start + 46 / 30, project);
  assert.equal(square.visible, false);
  title.update(third.start + third.duration, project);
  assert.equal(closing.visible, false);
  title.update(second.start + 1 / 6, project);
  assert.equal(pair.visible, true);
  compare(textureST(white), [.5, .25, 0, 0]);
  nativeTrack.muted = true;
  title.update(second.start + 1 / 6, project);
  assert.equal(pair.visible, false);
  title.dispose();
  assert.equal(root.children.length, 0);
  console.log("Native title particle cadence: independent activation epochs, 30/60 Hz atlas lanes, expiry, and rewind.");
}

async function runRibbons() {
  const root = new T.Scene();
  const levels = Array.from({length: 10}, (_, index) => {
    const width = 512 >> index;
    const header = Buffer.from(png, "base64").subarray(0, 24);
    header.writeUInt32BE(width, 16);
    header.writeUInt32BE(width, 20);
    return {png: header.toString("base64"), width, height: width};
  });
  const events = [{id: "ribbon:first", start: 10, duration: 2.75}, {id: "ribbon:second", start: 12.75, duration: 2.25}]
    .map(event => ({...event, values: {...track.events[0].values, offset: {x: 0, y: 0, z: 0}}}));
  const ribbonTrack = {id: "ribbon:track", nativeClass: "CustomControlTrack", events};
  const project = {tracks: [ribbonTrack], quality: {values: {stage_display: true}}};
  const material = {queue: 2900, cull: 2, tint: [.8, 1, 1, .9], uv: [.5, .25, .125, .5]};
  const rotation = [0, 0, 0, 1], unit = [1, 1, 1];
  const source = {
    textures: [levels],
    geometry: {
      positions: Array.from({length: 9}, (_, index) => [index % 3 - 1, 1 - Math.floor(index / 3), 0]),
      uv: Array.from({length: 9}, (_, index) => [index % 3 / 2, Math.floor(index / 3) / 2]),
      indices: [0, 3, 1, 1, 3, 4, 1, 4, 2, 2, 4, 5, 3, 6, 4, 4, 6, 7, 4, 7, 5, 5, 7, 8]
    },
    cues: [{
      trackId: ribbonTrack.id, eventId: events[0].id,
      parent: {position: [10, 2, -3], rotation, scale: [2, 1, 1]},
      meshes: [
        {path: 11, name: "ribbon_top", position: [5, 1, 0], rotation, scale: unit, active: false, texture: 0, material},
        {path: 12, name: "ribbon_bottom", position: [-1, 4, 2], rotation, scale: unit, active: true, texture: 0, material}
      ],
      animation: {start: .25, duration: 1, loop: true, channels: [
        {kind: "translation", path: 11, curves: [["linear", [[0, 0], [1, -4]]], constant(2), constant(6)]},
        {kind: "visibility", path: 11, curves: [["cubic", [[0, [0, 0, 0, 0]], [.5, [0, 0, 0, 1]]]]]},
        {kind: "overlayUV", path: 11, curves: [constant(.5), constant(.25), ["linear", [[0, 0], [1, .5]]], constant(.125)]},
        {kind: "overlayTint", path: 11, curves: [["linear", [[0, 0], [1, 1]]], constant(.75), constant(1), constant(.625)]}
      ]}
    }, {
      trackId: ribbonTrack.id, eventId: events[1].id,
      parent: {position: [-4, 3, 1], rotation, scale: unit},
      meshes: [{path: 11, name: "ribbon_other", position: [1, 2, 3], rotation, scale: unit, active: true, texture: 0, material}],
      animation: {start: 0, duration: 1, loop: true, channels: []}
    }]
  };
  const loaded = [], disposed = [];
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = levels[loaded.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const texture = new T.Texture({width: level.width, height: level.height});
      texture.addEventListener("dispose", () => disposed.push(level.width));
      loaded.push(texture);
      return texture;
    }
  }};
  const invalid = structuredClone(source);
  invalid.textures[0][5].png = invalid.textures[0][4].png;
  assert.equal(await MVStudioTitle.apply(local, root, invalid, {ribbons: true}), null);
  assert.equal(loaded.length, 0, "invalid authored mip is rejected before image loading");

  const ribbons = await MVStudioTitle.apply(local, root, source, {ribbons: true});
  assert.ok(ribbons);
  const [first, second] = root.children;
  const [top, bottom] = first.children, [other] = second.children;
  assert.equal(root.children.length, 2);
  assert.deepEqual([first.visible, second.visible, top.visible, bottom.visible, other.visible], [false, false, false, true, true]);
  assert.equal(top.geometry, bottom.geometry);
  assert.equal(top.geometry, other.geometry);
  assert.equal(top.geometry.getAttribute("position").count, 9);
  assert.equal(top.geometry.index.count, 24);
  assert.equal(top.material.side, T.FrontSide);
  assert.equal(top.material.stencilRef, 2);
  assert.equal(top.renderOrder, 2900);
  for (const mesh of [top, bottom, other]) assert.equal(mesh.material.uniforms.uTexture.value, loaded[0]);
  assert.deepEqual(loaded[0].mipmaps.map(image => image.width), levels.map(level => level.width));
  assert.equal(loaded[0].generateMipmaps, false);
  assert.equal(loaded[0].minFilter, T.LinearMipmapNearestFilter);
  assert.deepEqual(disposed, levels.slice(1).map(level => level.width), "temporary mip wrappers are released");

  ribbons.update(10, project);
  assert.equal(first.visible, true);
  assert.equal(top.visible, false);
  ribbons.update(10.5, project);
  assert.equal(top.visible, true);
  compare(top.position.toArray(), [3, 2, 6]);
  compare(top.getWorldPosition(new T.Vector3()).toArray(), [16, 4, 3]);
  compare(bottom.getWorldPosition(new T.Vector3()).toArray(), [8, 6, -1]);
  compare(top.material.uniforms.uTextureST.value.toArray(), [.5, .25, .375, .625]);
  compare(top.material.uniforms.uTint.value.toArray(), [.75, .75, 1, .625]);
  compare(bottom.material.uniforms.uTextureST.value.toArray(), [.5, .25, .125, .25]);
  compare(bottom.material.uniforms.uTint.value.toArray(), material.tint);
  ribbons.update(11, project);
  assert.equal(top.visible, false, "the authored animation loops within the cue window");
  compare(top.position.toArray(), [1, 2, 6]);
  ribbons.update(12.75, project);
  assert.deepEqual([first.visible, second.visible], [false, true]);
  compare(other.getWorldPosition(new T.Vector3()).toArray(), [-3, 5, 4]);
  ribbons.update(15, project);
  assert.deepEqual([first.visible, second.visible], [false, false]);
  ribbons.update(10.5, project);
  assert.deepEqual([first.visible, second.visible, top.visible], [true, false, true]);
  compare(top.material.uniforms.uTint.value.toArray(), [.75, .75, 1, .625]);
  project.quality.values.stage_display = false;
  ribbons.update(10.5, project);
  assert.equal(first.visible, false);
  project.quality.values.stage_display = true;
  ribbonTrack.muted = true;
  ribbons.update(12.75, project);
  assert.equal(second.visible, false);
  ribbonTrack.muted = false;
  ribbons.update(12.75, project);
  assert.equal(second.visible, true);

  let materials = 0, geometries = 0;
  for (const mesh of [top, bottom, other]) mesh.material.addEventListener("dispose", () => materials++);
  top.geometry.addEventListener("dispose", () => geometries++);
  ribbons.dispose();
  ribbons.dispose();
  assert.equal(root.children.length, 0);
  assert.equal(materials, 3);
  assert.equal(geometries, 1);
  assert.deepEqual(disposed, [...levels.slice(1).map(level => level.width), 512]);
  console.log("Native stage ribbons: authored mips, parent and leaf transforms, looped animation, cue transitions and cleanup.");
}

run().then(runParticles).then(runSeededParticles).then(runStockParticleCadence).then(runRibbons)
  .catch(error => { console.error(error); process.exitCode = 1; });
