"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-moving-companions.js");
require("../webtools/web/static/mv-studio-sparks-roop-simulation.js");
require("../webtools/web/static/mv-studio-stage-sparks.js");

const f32 = Math.fround, alias = "speedBackCenterStars";
const start = 77.05, duration = 15.783333333333331, splitTime = 79.55;
const trackId = "spark-loop", eventId = "fx_par_so2056_03";
const names = ["sparks_R1", "sparks_R2", "sparks_L1", "sparks_L2"];
const seeds = [4276993775, 4276993775, 2914, 2914];

function emitters() {
  const cubic = parts => ["cubic", parts.map(([time, a, b, c, d]) => [time, [a, b, c, d]])];
  const step = parts => cubic(parts.map(([time, value]) => [time, 0, 0, 0, value]));
  const sizeCurves = [step([[0, 1], [.02631571888923645, .325486421585083], [.12781953811645508, .6476469039916992],
    [.20676890015602112, .8253834247589111], [.30075183510780334, .5921568870544434], [.3947349190711975, .22989508509635925],
    [.48872172832489014, .8391483426094055], [.5601502656936646, .3098050057888031], [.6616540551185608, .6737014651298523],
    [.7293232083320618, .27843138575553894], [.8345920443534851, .4924238622188568], [.9172931909561157, .254901260137558],
    [1, .20783782005310059]]), step([[0, 1], [.06390973925590515, .8696273565292358], [.16165222227573395, .38039588928222656],
    [.25563719868659973, .6941176652908325], [.3421091139316559, .3075854182243347], [.43984395265579224, .6784303188323975],
    [.5225601196289062, .13577282428741455], [.605257511138916, .46814632415771484], [.6879622340202332, .11728429794311523],
    [.7781878113746643, .3854280710220337], [.8609253168106079, .12157309055328369], [1, .011767581105232239]])];
  const zero = [step([[0, 0]]), step([[0, 0], [1, 0]])];
  const velocityY = [cubic([[0, 3.978537756659827, -2.4391149013926334, 0, -.48827266693115234],
    [f32(.3), -.24779667399010868, .5382320217939636, -.38926371932029724, -.6003724932670593], [1, 0, 0, 0, -.6941176652908325]]),
  cubic([[0, 3.541188193581161, -2.1754187637724205, 0, -.08631116896867752],
    [f32(.3), -.34788825811746543, .6146615418187285, -.34913042187690735, -.18648678064346313], [1, 0, 0, 0, -.249019593000412]])];
  const lifeColors = [[[0, 253, 249, 194, 0], [.3000076413154602, 253, 249, 194, 146], [.48477911949157715, 248, 190, 151, 237],
    [.5000076293945312, 247, 187, 147, 244], [.9499961733818054, 211, 103, 37, 255], [1, 207, 93, 24, 0]],
  [[0, 255, 251, 198, 0], [.3000076413154602, 255, 251, 198, 146], [.5000076293945312, 253, 243, 182, 244],
    [.6675059199333191, 253, 219, 135, 248], [.9499961733818054, 241, 149, 60, 255], [1, 241, 149, 60, 0]]];
  const positions = [7, 9.5, -7, -9.5], quarter = .7071067811865475;
  return names.map((name, index) => {
    const side = index % 2 === 1;
    return {name, seed: null, duration: 13, rate: side ? 200 : 100, delay: [0, 0], lifetime: [3, 2],
      size: [f32(.2), f32(.3)], speed: [0, 0], roll: [0, f32(6.283185)], gravity: f32(.1),
      shape: {type: 0, radius: 1.5, radiusThickness: 1, arc: 180, arcMode: 0, scale: side ? [4, .5, 1] : [2, .5, .5],
        rotation: [90, 0, 0]}, capacity: 1000, bursts: [], uv: [.25, .25, .75, .25], sizeCurves, sizeMultiplier: 1,
      velocityCurves: [zero, velocityY, zero], velocityMultipliers: [1, 4, 1], clamp: null,
      startColors: [[1, .9511772990226746, .551886796951294, 1], [1, .8011445999145508, .49528300762176514, 1]],
      lifeColors, maxViewportWidth: .5, stretch: null, position: [positions[index], f32(9.2), f32(side ? -.95 : -4.8)],
      rotation: [0, side ? (index < 2 ? -quarter : quarter) : -0, -0, side ? quarter : 1]};
  });
}

function sourceFor(emitters) {
  return {textures: [alias], cues: [{trackId, eventId}], emitters};
}

function projectFor(source) {
  const event = {id: eventId, start, duration, values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1,
    weight: 1, particleRandomSeed: 5440, overwriteRandomSeed: 0, offset: {x: 0, y: 0, z: 0}}};
  const track = {id: trackId, nativeClass: "CustomControlTrack", events: [event]};
  const settings = {stage_control: true, stage_display: false, split_screen: true, frame_rate_60fps: true};
  return {stageSparksRoop: source, tracks: [track], quality: {values: settings}};
}

function near(actual, expected, tolerance = .00002) {
  assert.equal(actual.length, expected.length);
  assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) <= tolerance), `${actual} differs from ${expected}`);
}

function nativeSamples(row, seed) {
  const stream = MVStudioSparksRoopSimulation.create(row, seed);
  assert.ok(stream);
  return (elapsed, fps = 60) => {
    const sample = [];
    stream.sample(elapsed, fps, (...values) => sample.push(values));
    return sample;
  };
}

function verifyNative(rows) {
  assert.equal(MVStudioSparksRoopSimulation.create({...rows[0], rate: 200}, seeds[0]), null);
  const expected = [
    {early: [6.9241533279, 9.470085144, -4.1161446571, .2001391947, 1.1908051968, 253, 208, 99, 4],
      afterCull: [9.0532398224, 8.7061767578, -4.5380272865, .1051971391, .086178571, 253, 229, 105, 58], tail: [251, 253, 45]},
    {early: [8.8161439896, 9.7844581604, -1.1016931534, .2001391947, 1.1908051968, 253, 208, 99, 3],
      afterCull: [9.3488864899, 9.6959009171, -1.7125967741, .188035965, 4.8716006279, 254, 203, 97, 50], tail: [504, 507, 94]},
    {early: [-8.7693576813, 9.1707839966, -4.55838871, .2699234784, 1.4953198433, 253, 216, 100, 4],
      afterCull: [-8.595864296, 9.2156972885, -4.5946345329, .1134047061, 6.1815357208, 254, 209, 99, 120], tail: [249, 252, 50]},
    {early: [-9.2583875656, 9.154378891, 2.588714838, .2699234784, 1.4953198433, 253, 216, 100, 3],
      afterCull: [-9.0964632034, 7.946000576, -5.3285031319, .2041565478, 4.2957172394, 255, 230, 106, 119], tail: [504, 505, 113]},
  ];
  function exactPacket(actual, expected) {
    const [x, y, z, size, roll, ...rgba] = expected;
    near(actual.slice(0, 6), [x, y, z, size, size, roll]);
    assert.deepEqual(actual.slice(6), rgba);
  }
  for (const [index, row] of rows.entries()) {
    const sample = nativeSamples(row, seeds[index]), reference = expected[index];
    assert.deepEqual(sample(0), []);
    assert.deepEqual([1, 2, 3].map(tick => sample(tick / 60).length), row.rate === 100 ? [1, 3, 5] : [3, 6, 10]);
    const early = sample(2 / 60), afterCull = sample(3);
    exactPacket(early[0], reference.early);
    exactPacket(afterCull[0], reference.afterCull);
    assert.deepEqual([afterCull.length, sample(13).length, sample(15).length], reference.tail);
    assert.deepEqual(sample(16), []);
    assert.deepEqual(sample(1 / 30, 30), early);
    assert.deepEqual(sample(3 / 60, 30), early);
    assert.deepEqual(sample(3, 30), afterCull);
    assert.deepEqual(sample(2 / 60), early);
  }
}

function verifyThreeViews(project, snapshot) {
  const scope = {window: {}};
  vm.runInNewContext(fs.readFileSync(require.resolve("../webtools/web/static/mv-studio-split.js"), "utf8"), scope);
  const binding = "/EntryPoint/Live/Cameras/SplitScreenEffect";
  const pointer = {m_FileID: 0, m_PathID: "-42"};
  const cuts = {id: "three-views", start: splitTime, duration: 1,
    values: {playableClass: "LiveSplitScreenClip", mainCamera: 0}};
  const mask = {positions: [1, -1, .01, -1, -1, .01, -1, 1, .01, 1, 1, .01],
    indices: [0, 1, 2, 0, 2, 3], uv: [1, 0, 0, 0, 0, 1, 1, 1], bounds: [2, 2]};
  const splitProject = {...project, tracks: [...project.tracks, {binding, nativeClass: "LiveSplitScreenTrack", events: [cuts]}],
    splitScreen: {masks: {mask}, events: {[cuts.id]: []}}};
  const cameras = [new T.Vector3(-3, 6, 4), new T.Vector3(0, 4, 8), new T.Vector3(3, 8, 10)];
  cameras.forEach((_, index) => {
    const slot = index + 1;
    cuts.values[`subCamera${slot}`] = 1;
    cuts.values[`mask${slot}`] = pointer;
    splitProject.tracks.push({binding: `${binding}/Cameras/SubCamera${slot}`, nativeClass: "AnimationTrack", index, events: []});
    splitProject.splitScreen.events[cuts.id].push({key: "mask", pointer});
  });

  let target = null, color = new T.Color(0), alpha = .5, overlays = 0;
  const renderer = {domElement: {width: 640, height: 360}, capabilities: {maxTextureSize: 4096}, autoClear: true,
    getRenderTarget() { return target; }, setRenderTarget(value) { target = value; },
    getClearColor(value) { return value.copy(color); }, getClearAlpha() { return alpha; },
    setClearColor(value, opacity) { color.set(value); alpha = opacity; }, clear() {}, clearDepth() {},
    render(scene) { overlays = scene.children.filter(mesh => mesh.visible).length; }};
  const split = scope.window.MVStudioSplit.create(T, renderer), views = [], expected = snapshot();
  try {
    split.setProject(splitProject);
    split.sample(splitTime, (camera, track) => Boolean(camera.position.copy(cameras[track.index])));
    assert.equal(split.draw(camera => {
      assert.equal(target.stencilBuffer, true);
      views.push(camera.position.toArray());
      assert.deepEqual(snapshot(), expected);
    }, null), true);
    assert.deepEqual(views, cameras.map(camera => camera.toArray()));
    assert.equal(overlays, 3);
    assert.equal(target, null);
  } finally {
    split.dispose();
  }
}

async function verifyPackets(rows, sampleSeeds) {
  const source = sourceFor(rows), project = projectFor(source);
  const {tracks: [track], quality: {values: quality}} = project;
  const root = new T.Scene(), texture = new T.Texture(), atlases = {[alias]: texture};
  const originalSeed = MVStudioStageParticles.autoSeed;
  let effect, used = 0;
  try {
    MVStudioStageParticles.autoSeed = () => sampleSeeds[used++];
    assert.equal(await MVStudioStageSparks.apply(T, root, undefined, atlases, "roop"), null);
    assert.equal(await MVStudioStageSparks.apply(T, root, source, {}, "roop"), null);
    assert.equal(used, 0);
    assert.equal(root.children.length, 0);
    effect = await MVStudioStageSparks.apply(T, root, source, atlases, "roop");
  } finally {
    MVStudioStageParticles.autoSeed = originalSeed;
  }
  assert.ok(effect);
  assert.equal(used, 4);
  const meshes = root.children.slice();
  assert.deepEqual(meshes.map(mesh => mesh.name), names.map(name => `Native spark roop 1 ${name}`));
  let materials = 0, geometries = 0, textures = 0;
  texture.addEventListener("dispose", () => textures++);
  for (const {geometry, material, renderOrder} of meshes) {
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.index.count, 6);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.equal(material.defines.VIEW_ALIGNED, 1);
    assert.equal(material.defines.PARTICLE_ROLL, 1);
    assert.equal(renderOrder, 3010);
    assert.equal(material.uniforms.uTexture.value, texture);
    assert.equal(material.uniforms.uMaxWidth.value, .5);
    assert.deepEqual(material.uniforms.uAtlas.value.toArray(), [.25, .25, .75, .25]);
    assert.deepEqual(material.uniforms.uTint.value.toArray(), [2, 2, 2, 1]);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneFactor);
    assert.equal(material.depthWrite, false);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.stencilFunc, T.AlwaysStencilFunc);
    material.addEventListener("dispose", () => materials++);
    geometry.addEventListener("dispose", () => geometries++);
  }

  const features = ["centerAndTile", "particleSize", "particleRoll", "particleColor"];
  const snapshots = () => meshes.map(({geometry}) => {
    const count = geometry.instanceCount;
    return {count, attributes: features.map(name => {
      const attribute = geometry.getAttribute(name);
      return [...attribute.array.slice(0, count * attribute.itemSize)];
    })};
  });
  const versions = () => meshes.map(mesh => mesh.geometry.getAttribute("centerAndTile").version);

  effect.update(start - .001, project);
  assert.ok(meshes.every(mesh => !mesh.visible));
  effect.update(start, project);
  assert.ok(meshes.every(mesh => !mesh.visible));
  effect.update(splitTime, project);
  const active = snapshots();
  for (const [index, {count, attributes}] of active.entries()) {
    const sample = nativeSamples(rows[index], sampleSeeds[index])(splitTime - start)
      .filter(particle => Math.max(particle[3], particle[4]) > 0 && particle[9] > 0);
    assert.ok(count > 0);
    assert.equal(count, sample.length);
    const [x, y, z, width, height, roll, r, g, b, a] = sample[0];
    near(attributes[0].slice(0, 4), [x, y, z, 0]);
    near(attributes[1].slice(0, 2), [width, height]);
    near(attributes[2].slice(0, 1), [roll]);
    assert.deepEqual(attributes[3].slice(0, 4), [r, g, b, a]);
  }
  assert.notDeepEqual(active[0].attributes[3], active[2].attributes[3]);
  const beforeViews = versions();
  verifyThreeViews(project, snapshots);
  assert.deepEqual(versions(), beforeViews);

  track.events[0].values.offset = {x: 1, y: 2, z: 3};
  effect.update(splitTime, project);
  assert.deepEqual(meshes.map(mesh => mesh.position.toArray()), Array.from({length: 4}, () => [-1, 2, 3]));
  assert.deepEqual(versions(), beforeViews);
  track.muted = true;
  effect.update(splitTime, project);
  assert.ok(meshes.every(mesh => !mesh.visible));
  track.muted = false;
  quality.stage_control = false;
  quality.stage_display = true;
  effect.update(splitTime, project);
  assert.ok(meshes.every(mesh => !mesh.visible));

  quality.stage_control = true;
  quality.frame_rate_60fps = false;
  effect.update(start + 944 / 60, project);
  assert.ok(meshes[3].visible, "the outer emitter still has a native tail near the cue end");
  effect.update(start + duration, project);
  assert.ok(meshes.every(mesh => !mesh.visible));
  effect.update(splitTime, project);
  assert.deepEqual(snapshots(), active);
  effect.update(splitTime + 1 / 60, project);
  assert.deepEqual(snapshots(), active);
  track.events[0].start += 1;
  effect.invalidate();
  effect.update(start + .5, project);
  assert.ok(meshes.every(mesh => !mesh.visible));
  effect.update(splitTime + 1, project);
  assert.deepEqual(snapshots(), active);
  effect.dispose();
  assert.equal(root.children.length, 0);
  assert.deepEqual([materials, geometries, textures], [4, 4, 0]);
  texture.dispose();
  assert.equal(textures, 1);
}

async function run() {
  const rows = emitters();
  verifyNative(rows);
  await verifyPackets(rows, seeds);
  console.log("Native sparks_roop: all four emitters, live culling, stable seeks and shared three-view packets.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
