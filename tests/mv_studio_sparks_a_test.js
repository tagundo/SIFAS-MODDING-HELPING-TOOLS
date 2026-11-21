"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-display-lights.js");
require("../webtools/web/static/mv-studio-moving-companions.js");
require("../webtools/web/static/mv-studio-sparks-a-simulation.js");
require("../webtools/web/static/mv-studio-stage-sparks.js");

const f32 = Math.fround, alias = "speedBackCenterStars";
const start = 77.73333333333333, duration = 5.400000000000006;

function hibanaFixture() {
  const taper = slope => ["cubic", [[0, [0, 0, slope, 1]], [1, [0, 0, 0, f32(1 + slope)]]]];
  const life = rows => rows.map(([stamp, ...rgba]) => [f32(stamp / 65535), ...rgba]);
  return {name: "hibana_01", delay: [0, 0], lifetime: [f32(1.2), f32(2.4)], size: [f32(.02), f32(.04)],
    speed: [3, 30], roll: [0, 0], gravity: [.5, f32(1.2)],
    shape: {type: 8, radius: f32(.3), radiusThickness: 1, angle: 15, length: 2, arc: 360, arcMode: 0,
      scale: [1, 1, 1], rotation: [-90, 0, 0]},
    duration: f32(.1), rate: 0, bursts: [[0, 1000]], sizeCurves: [taper(f32(-.3)), taper(-.7272720336914062)],
    sizeMultiplier: 1, clamp: {limit: 1, dampen: f32(.1)}, startColors: [[1, 1, 1, 1], [1, 1, 1, 1]],
    lifeColors: [life([[0, 255, 255, 255, 0], [4587, 255, 253, 241, 255], [26214, 255, 242, 177, 255],
      [55705, 186, 58, 18, 255], [58982, 178, 38, 0, 0]]),
    life([[0, 255, 255, 255, 0], [4587, 255, 254, 248, 255], [32768, 255, 247, 208, 255],
      [62258, 186, 58, 21, 255], [65535, 178, 38, 0, 0]])],
    uv: [.25, .25, .75, 0], capacity: 1000, maxViewportWidth: 1,
    stretch: {lengthScale: 0, velocityScale: f32(.025)}};
}

function sourceFor(row) {
  const cues = [100, 200].map((seed, index) => ({trackId: `sparks_A_0${index + 1}`, eventId: `spark-${index + 1}`, seed}));
  return {textures: [alias], cues, emitters: [row]};
}

function projectFor(source) {
  const offsets = [{x: 7, y: -1, z: 8}, {x: -4, y: -2, z: 8}];
  const tracks = source.cues.map(({trackId, eventId, seed}, index) => ({id: trackId, nativeClass: "CustomControlTrack",
    events: [{id: eventId, start, duration, values: {playableClass: "CustomControlClip", clipIn: 0, timeScale: 1,
      weight: 1, particleRandomSeed: seed, overwriteRandomSeed: 1, offset: offsets[index]}}]}));
  const settings = {stage_control: true, stage_display: false, frame_rate_60fps: true};
  return {tracks, quality: {values: settings}};
}

function near(actual, expected, tolerance = .00002) {
  assert.equal(actual.length, expected.length);
  assert.ok(actual.every((value, index) => Math.abs(value - expected[index]) <= tolerance), `${actual} differs from ${expected}`);
}

function sampleOf(row, seed) {
  const simulation = MVStudioSparksASimulation.create(row, seed);
  assert.ok(simulation);
  return (time, fps = 60) => {
    const particles = [];
    simulation.sample(time, fps, (...fields) => particles.push(fields));
    return particles;
  };
}

function verifyNative(row) {
  assert.equal(MVStudioSparksASimulation.create({...row, bursts: [[0, 999]]}, 100), null);
  assert.equal(MVStudioSparksASimulation.create({...row, startColors: [[0, 1, 1, 1], [0, 1, 1, 1]]}, 100), null);
  const expected = [
    {seed: 100, warm: [[-.5630433559417725, 1.6696743965148926, -.32639431953430176,
      -4.8984222412109375, 24.159692764282227, -2.8395979404449463, .03278101235628128, 0, 255, 255, 253, 40],
    [.03810860961675644, 1.5312227010726929, -.2810545861721039, .2235577255487442,
      15.436427116394043, -1.6487590074539185, .032736845314502716, 0, 255, 255, 254, 27]],
    mature: [222, 155, 109, 255], survivors: 361},
    {seed: 200, warm: [[.2121001034975052, 1.1169469356536865, .17425082623958588,
      .7649533748626709, 7.895934104919434, .6284476518630981, .02980913408100605, 0, 255, 255, 254, 28],
    [-.2548983097076416, 1.7657700777053833, .06045803800225258, -.8117082118988037,
      9.028348922729492, .19252519309520721, .03612671047449112, 0, 255, 255, 254, 26]],
    mature: [254, 244, 204, 255], survivors: 328},
  ];
  // Controlled Android Unity steps, using the actual two clip seeds and native storage order.
  return expected.map(({seed, warm: golden, mature, survivors}) => {
    const sample = sampleOf(row, seed);
    assert.deepEqual(sample(0), []);
    const birth = sample(1 / 60), warm = sample(2 / 60);
    assert.equal(birth.length, 1000);
    assert.ok(birth.every(particle => particle[11] === 0));
    assert.equal(warm.length, 1000);
    assert.ok(warm.every(particle => particle[11] > 0));
    golden.forEach((particle, index) => {
      near(warm[index].slice(0, 8), particle.slice(0, 8));
      assert.deepEqual(warm[index].slice(8), particle.slice(8));
    });
    const atOneSecond = sample(1);
    assert.equal(atOneSecond.length, 1000);
    assert.deepEqual(atOneSecond[0].slice(8), mature);
    assert.equal(sample(2).length, survivors);
    assert.deepEqual(sample(145 / 60), []);
    assert.deepEqual(sample(1 / 30, 30), warm);
    assert.deepEqual(sample(3 / 60, 30), warm);
    assert.deepEqual(sample(1, 30), atOneSecond);
    assert.deepEqual(sample(2 / 60), warm);
    return {warm};
  });
}

function verifyStretch(mesh) {
  const {geometry, material} = mesh, corners = geometry.getAttribute("position"), uv = geometry.getAttribute("uv");
  const {uStretch, uAtlas} = material.uniforms;
  // Paired native render-view sample with a 0.02 width and nonzero velocity on all axes.
  const head = new T.Vector3(-4, -2, 8), velocity = new T.Vector3(3, 9, 4);
  const side = new T.Vector3().crossVectors(head, velocity).setZ(0).normalize();
  const positions = [], atlas = [];
  for (let i = 0; i < corners.count; i++) {
    const point = head.clone().addScaledVector(side, .01 * corners.getY(i));
    if (corners.getX(i) > 0) point.addScaledVector(velocity, -uStretch.value.y);
    positions.push(...point.toArray());
    atlas.push(uAtlas.value.x * uv.getX(i) + uAtlas.value.z, uAtlas.value.y * uv.getY(i) + uAtlas.value.w);
  }
  near(positions, [-4.0089445114, -1.9955278635, 8, -4.0839443207, -2.2205278873, 7.9000000954,
    -4.0660552979, -2.2294719219, 7.9000000954, -3.9910557270, -2.0044720173, 8]);
  assert.deepEqual(atlas, [.75, 0, 1, 0, 1, .25, .75, .25]);
}

async function run() {
  const row = hibanaFixture();
  await verifyPackets(row, verifyNative(row));
  console.log("Native Sparks A: seeded cone burst, ordinary cadence, velocity stretch, independent cue control and atlas ownership.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });

async function verifyPackets(row, native) {
  const source = sourceFor(row), project = projectFor(source), {tracks, quality: {values: quality}} = project;
  const root = new T.Scene(), atlas = new T.Texture(), atlases = {[alias]: atlas};
  assert.equal(await MVStudioStageSparks.apply(T, root, source, {}, "A"), null);
  const invalid = {...source, cues: [{...source.cues[0], seed: undefined}]};
  assert.equal(await MVStudioStageSparks.apply(T, root, invalid, atlases, "A"), null);
  assert.equal(root.children.length, 0);
  const effect = await MVStudioStageSparks.apply(T, root, source, atlases, "A");
  assert.ok(effect);
  const meshes = root.children.slice();
  assert.deepEqual(meshes.map(mesh => mesh.name), ["Native spark A 1 hibana_01", "Native spark A 2 hibana_01"]);
  let materials = 0, geometries = 0, textures = 0;
  atlas.addEventListener("dispose", () => textures++);
  for (const {geometry, material, renderOrder} of meshes) {
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.index.count, 6);
    assert.equal(geometry.getAttribute("centerAndSize").count, 1000);
    assert.equal(geometry.getAttribute("velocity").itemSize, 3);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.equal(renderOrder, 3010);
    assert.equal(material.defines.STRETCHED, 1);
    assert.equal(material.uniforms.uTexture.value, atlas);
    assert.equal(material.uniforms.uMaxWidth.value, 1);
    assert.deepEqual(material.uniforms.uAtlas.value.toArray(), [.25, .25, .75, 0]);
    assert.deepEqual(material.uniforms.uTint.value.toArray(), [2, 2, 2, 1]);
    assert.deepEqual(material.uniforms.uStretch.value.toArray(), [0, f32(.025)]);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneFactor);
    assert.equal(material.depthWrite, false);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.stencilFunc, T.AlwaysStencilFunc);
    geometry.addEventListener("dispose", () => geometries++);
    material.addEventListener("dispose", () => materials++);
  }
  verifyStretch(meshes[0]);

  const state = () => meshes.map(mesh => mesh.geometry.instanceCount);
  function update(time, expected) {
    effect.update(time, project);
    assert.deepEqual(state(), expected);
    assert.deepEqual(meshes.map(mesh => mesh.visible), expected.map(count => count > 0));
  }

  function assertRendered(mesh, expected) {
    const centers = mesh.geometry.getAttribute("centerAndSize"), velocities = mesh.geometry.getAttribute("velocity");
    const colors = mesh.geometry.getAttribute("particleColor");
    const first = expected.find(particle => particle[6] > 0 && particle[11] > 0);
    near([...centers.array.slice(0, 4)], [first[0], first[1], first[2], first[6]]);
    near([...velocities.array.slice(0, 3)], first.slice(3, 6));
    assert.deepEqual([...colors.array.slice(0, 4)], first.slice(8));
    assert.equal(centers.updateRange.count, mesh.geometry.instanceCount * 4);
    assert.equal(colors.updateRange.count, mesh.geometry.instanceCount * 4);
  }

  const warm = native.map(frames => frames.warm), live = warm.map(frame => frame.filter(row => row[6] > 0 && row[11] > 0).length);
  update(start - .001, [0, 0]);
  update(start, [0, 0]);
  update(start + 1 / 60, [0, 0]);
  update(start + 2 / 60, live);
  meshes.forEach((mesh, index) => assertRendered(mesh, warm[index]));
  assert.deepEqual(meshes.map(mesh => mesh.position.toArray()), [[-7, -1, 8], [4, -2, 8]]);

  quality.frame_rate_60fps = false;
  update(start + 1 / 60, [0, 0]);
  update(start + 2 / 60, live);
  const version = meshes[0].geometry.getAttribute("centerAndSize").version;
  update(start + 3 / 60, live);
  assert.equal(meshes[0].geometry.getAttribute("centerAndSize").version, version);
  quality.stage_control = false;
  quality.stage_display = true;
  update(start + 2 / 60, [0, 0]);
  quality.stage_control = true;
  tracks[1].muted = true;
  update(start + 2 / 60, [live[0], 0]);
  tracks[1].muted = false;
  tracks[1].events[0].start = 86;
  tracks[1].events[0].duration = .5;
  effect.invalidate();
  update(86 + 2 / 60, [0, live[1]]);
  update(86.5, [0, 0]);
  update(start + 2 / 60, [live[0], 0]);
  assertRendered(meshes[0], warm[0]);
  update(start + 3, [0, 0]);
  update(start + 2 / 60, [live[0], 0]);
  assertRendered(meshes[0], warm[0]);

  effect.dispose();
  effect.dispose();
  assert.equal(root.children.length, 0);
  assert.deepEqual([materials, geometries, textures], [2, 2, 0]);
  atlas.dispose();
  assert.equal(textures, 1);
}
