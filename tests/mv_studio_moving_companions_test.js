"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-companion-sim.js");
require("../webtools/web/static/mv-studio-moving-companions.js");

const f32 = Math.fround;
const cone = {type: 4, scale: [.6, .3, .1].map(f32), radius: f32(.0001), arc: 360, angle: 75};
const circle = {type: 10, scale: [1, 1, f32(.1)], radius: 1, arc: 90, angle: 75};
const rgb = [[16384, 255, 255, 255], [32768, 179, 204, 255], [49151, 255, 185, 179],
  [55705, 128, 170, 255], [65535, 179, 255, 216]];
const sideRGB = [rgb[0], rgb[1], rgb[2], rgb[4]];

function fixture() {
  const make = (name, seed, shape, position, rotation, alphaStart, alphaEnd) => {
    const star = name === "stars", main = name === "speed";
    return {name, seed, shape, position, rotation, lifetime: 2, rate: main ? 250 : 100,
      capacity: main ? 500 : 1000, cycle: 5, prewarm: false, size: [.5, star ? 2 : 1],
      speed: star ? [5, 10] : [15, 25], rollRange: [0, 0],
      palette: {rgb: (shape === circle ? sideRGB : rgb).map(key => key.slice()), alpha: [[0, 255], [65535, 255]]},
      colorKeys: [[0, 255, 255, 255, 0], [f32(alphaStart / 65535), 255, 255, 255, 0],
        [f32(alphaEnd / 65535), 255, 255, 255, 255], [1, 255, 255, 255, 255]],
      uv: [.25, .25, .75, star ? .25 : 0], maxViewportWidth: .5,
      stretch: star ? null : {lengthScale: 20, velocityScale: f32(.1)}};
  };
  return [make("speed", 0, cone, [0, f32(3.05), -7], [0, 0, 0, 1], 5243, 7864),
    make("speed_R", 1626203053, circle, [3.75, f32(2.6), -3.5],
      [0.48296293126222545, 0.8365163122171125, 0.1294094907026942, 0.2241438157463877], 6554, 11796),
    make("speed_L", 2207999926, circle, [-3.75, f32(2.6), -3.5],
      [0.1294095742900918, 0.22414395467820972, 0.4829629095433085, 0.8365162745988459], 6554, 11796),
    make("stars", 3710075818, cone, [0, f32(3.05), -7], [0, 0, 0, 1], 6554, 9830)];
}

function sample(simulation, age, fps) {
  const out = [];
  simulation.sample(age, fps, (...fields) => out.push(fields));
  return out;
}

function nearVector(actual, expected, tolerance) {
  assert.equal(actual.length, expected.length);
  actual.forEach((field, index) => assert.ok(Math.abs(field - expected[index]) < tolerance,
    `field ${index}: expected ${expected[index]}, received ${field}`));
}

function verifySimulation(rows) {
  const make = row => MVStudioCompanionSimulation.create(row);
  assert.equal(make({...rows[0], capacity: 1}), null);
  for (const row of rows) {
    const control = make(row);
    assert.deepEqual(sample(control, 0, 60), [], `${row.name} has no birth at cue start`);
    assert.deepEqual(sample(control, -.1, 60), []);
    assert.deepEqual(sample(control, 60.1, 60), []);
    const fadingIn = sample(control, .1, 60);
    assert.ok(fadingIn.length > 0 && fadingIn.every(particle => particle[10] === 0));
    const early = sample(control, .43, 30);
    const full = sample(control, 5.04, 60);
    assert.ok(early.length > 0);
    assert.ok(full.length > row.rate && full.length <= Math.min(row.capacity, row.rate * row.lifetime));
    assert.deepEqual(sample(control, .4, 60), sample(make(row), .4, 60),
      "a rewind at the same cadence does not reuse future births");
    assert.deepEqual(sample(control, .43, 30), early, "rewinding and changing cadence gives the same birth lanes");
    assert.deepEqual(sample(control, 5.04, 60), full);
    assert.deepEqual(sample(make(row), 5.04, 60), full, "direct seek equals a seek through earlier samples");
    const allowedColors = row.palette.rgb.map(key => key.slice(1));
    const partial = full.some(particle => particle[10] < 255);
    assert.ok(partial, `${row.name} has a visible alpha ramp`);
    for (const particle of full) {
      assert.equal(particle.length, 11);
      assert.ok(particle.every(Number.isFinite));
      const speed = Math.hypot(...particle.slice(3, 6));
      assert.ok(speed >= row.speed[0] - .001 && speed <= row.speed[1] + .001);
      assert.ok(particle[6] > 0 && particle[6] <= row.size[1]);
      assert.ok(particle.slice(7).every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255));
      assert.ok(allowedColors.some(tint => tint.every((byte, i) => particle[i + 7] === byte)));
    }
  }

  // Stock ARM 60 Hz birth jobs also run at 30 Hz display cadence, twice
  // per ordinary frame. Positions and velocities are reflected in X.
  function checkJob(row, tick, job) {
    const live = sample(make(row), .5, 30), sinceBirthJob = .5 - tick / 60;
    let previous = -1;
    for (const birth of job) {
      const index = live.findIndex(particle => birth.velocity.every((component, i) =>
        Math.abs(particle[i + 3] - component) < .0001));
      assert.ok(index > previous, `${row.name} keeps the native newest-to-oldest SIMD birth order`);
      const particle = live[index];
      nearVector(particle.slice(0, 3), birth.position.map((center, i) => center + sinceBirthJob * birth.velocity[i]), .0001);
      nearVector([particle[6]], [birth.startSize * (birth.age + sinceBirthJob / 2)], .00001);
      assert.deepEqual(particle.slice(7), birth.rgba);
      previous = index;
    }
  }

  checkJob(rows[3], 2, [
    {position: [-.015610327012836933, 3.0323071479797363, -6.995307922363281],
      velocity: [-4.680423259735107, -5.304830551147461, 1.4076714515686035],
      age: .0016666674613952637, startSize: 1.8421690464019775, rgba: [179, 204, 255, 255]},
    {position: [-.08710205554962158, 2.976325035095215, -6.991600513458252],
      velocity: [-6.530570030212402, -5.5238423347473145, .6299440860748291],
      age: .006666667461395264, startSize: 1.2671869993209839, rgba: [128, 170, 255, 255]},
  ]);
  checkJob(rows[1], 1, [{position: [4.581724166870117, 3.1046993732452393, -3.019804000854492],
    velocity: [12.251935958862305, 7.434611797332764, 7.073657035827637],
    age: .003333333730697632, startSize: .9445784091949463, rgba: [179, 204, 255, 255]}]);

  // Native 60 Hz speed tick 258 expires four of 500 particles and accepts
  // only four of the five requested births. The unused SIMD group must not
  // advance the seeded stream before the following tick.
  const speed = make(rows[0]);
  const beforeCap = sample(speed, 257 / 60, 60), atCap = sample(speed, 258 / 60, 60);
  const afterCap = sample(speed, 259 / 60, 60);
  const velocityKey = particle => particle.slice(3, 6).join(",");
  const beforeVelocities = new Set(beforeCap.map(velocityKey));
  assert.deepEqual([beforeCap.length, atCap.length, afterCap.length], [500, 500, 499]);
  assert.equal(atCap.filter(particle => !beforeVelocities.has(velocityKey(particle))).length, 4);
  const velocity = [-22.31905174255371, 2.3372881412506104, 1.588368535041809];
  const postCap = particles => particles.find(particle => velocity.every((component, i) =>
    Math.abs(particle[i + 3] - component) < .0001));
  const birth = postCap(afterCap);
  assert.ok(birth, "the native tick-259 birth keeps its random lane after the cap");
  assert.equal(postCap(atCap), undefined);
  nearVector(birth.slice(0, 3), [-.014937026426196098, 3.0515642166137695, -6.998939514160156], .0001);
  assert.deepEqual(birth.slice(7), [179, 255, 216, 0]);
  const fading = postCap(sample(speed, 271 / 60, 60));
  assert.ok(fading);
  nearVector(fading.slice(0, 3), [-4.478747367859, 3.519021034241, -6.681262969971], .0001);
  nearVector([fading[6]], [.05691439658403], .00001);
  assert.deepEqual(fading.slice(7), [179, 255, 216, 128]);

  assert.deepEqual(sample(speed, 129 / 30, 30), atCap);
  assert.deepEqual(sample(speed, 259 / 60, 30), atCap, "ordinary playback holds its completed frame between substeps");
  const nextOrdinary = sample(speed, 130 / 30, 30);
  assert.equal(nextOrdinary.length, 499);
  assert.deepEqual(nextOrdinary, sample(speed, 260 / 60, 60));
}

function prefix(attribute, count) {
  return [...attribute.array.subarray(0, count * attribute.itemSize)];
}

function sortCenter(row) {
  const depth = row.name === "speed" ? 25 : row.name === "stars" ? 10 : 0;
  return [row.position[0], row.position[1], row.position[2] + depth];
}

function verifyBatches(rows) {
  const root = new T.Group(), atlas = new T.Texture({width: 512, height: 512});
  let textures = 0, geometries = 0, materials = 0;
  atlas.addEventListener("dispose", () => textures++);
  assert.equal(MVStudioMovingCompanions.create(T, root, [rows[0], rows[0]], atlas), null);
  assert.equal(root.children.length, 0);
  const renderer = MVStudioMovingCompanions.create(T, root, rows, atlas);
  assert.ok(renderer);
  assert.equal(renderer.batches.length, rows.length);
  for (const [i, {mesh, center}] of renderer.batches.entries()) {
    const data = rows[i], {geometry, material} = mesh;
    assert.equal(mesh.parent, root);
    assert.equal(mesh.name, `Native stage moving ${data.name}`);
    assert.equal(mesh.visible, false);
    assert.equal(mesh.frustumCulled, false);
    assert.deepEqual(center.toArray(), sortCenter(data));
    assert.equal(geometry.instanceCount, 0);
    assert.equal(geometry.isInstancedBufferGeometry, true);
    assert.equal(geometry.groups.length, 0);
    assert.equal(geometry.getAttribute("position").count, 4);
    assert.equal(geometry.index.count, 6);
    assert.equal(geometry.getAttribute("centerAndSize").itemSize, 4);
    assert.equal(geometry.getAttribute("particleColor").isInstancedBufferAttribute, true);
    assert.equal(geometry.getAttribute("particleColor").normalized, true);
    assert.ok(geometry.getAttribute("particleColor").array instanceof Uint8Array);
    assert.equal(Boolean(geometry.getAttribute("velocity")), Boolean(data.stretch));
    for (const name of ["centerAndSize", "particleColor", ...(data.stretch ? ["velocity"] : [])]) {
      const attribute = geometry.getAttribute(name);
      assert.ok(attribute.isInstancedBufferAttribute);
      assert.ok(attribute.count <= data.capacity);
    }
    assert.deepEqual(material.uniforms.uAtlas.value.toArray(), data.uv);
    assert.equal(material.uniforms.uTexture.value, atlas);
    assert.equal(material.uniforms.uMaxWidth.value, .5);
    assert.equal(Boolean(material.defines.STRETCHED), Boolean(data.stretch));
    if (data.stretch) assert.deepEqual(material.uniforms.uStretch.value.toArray(), [20, f32(.1)]);
    assert.equal(material.transparent, true);
    assert.equal(material.depthFunc, T.LessEqualDepth);
    assert.equal(material.depthWrite, false);
    assert.equal(material.blendSrc, T.SrcAlphaFactor);
    assert.equal(material.blendDst, T.OneFactor);
    assert.equal(material.stencilWrite, true);
    assert.equal(material.stencilFunc, T.EqualStencilFunc);
    assert.equal(material.stencilRef, 2);
    assert.equal(material.stencilWriteMask, 255, "keep the stencil writable for the next raw WebGL clear");
    assert.deepEqual([material.stencilFail, material.stencilZFail, material.stencilZPass], Array(3).fill(T.KeepStencilOp));
    geometry.addEventListener("dispose", () => geometries++);
    material.addEventListener("dispose", () => materials++);
  }

  function update(age, fps) {
    renderer.update(age, fps, true);
    return renderer.batches.map(({mesh, center}, i) => {
      const {geometry} = mesh, count = geometry.instanceCount;
      const expected = sample(MVStudioCompanionSimulation.create(rows[i]), age, fps)
        .filter(particle => particle[6] > 0 && particle[10] > 0);
      assert.equal(count, expected.length);
      assert.equal(mesh.visible, count > 0);
      const positions = geometry.getAttribute("centerAndSize"), colors = geometry.getAttribute("particleColor");
      const velocities = geometry.getAttribute("velocity");
      if (count) {
        assert.equal(positions.updateRange.count, count * 4);
        assert.equal(colors.updateRange.count, count * 4);
        if (velocities) assert.equal(velocities.updateRange.count, count * 3);
      }
      const packed = prefix(colors, count), motion = prefix(positions, count);
      assert.deepEqual(packed, expected.flatMap(particle => particle.slice(7)));
      assert.deepEqual(motion, expected.flatMap(particle => [...particle.slice(0, 3), particle[6]].map(f32)));
      if (velocities) assert.deepEqual(prefix(velocities, count), expected.flatMap(particle => particle.slice(3, 6).map(f32)));
      assert.deepEqual(center.toArray(), sortCenter(rows[i]));
      return {motion, packed, center: center.toArray()};
    });
  }

  update(0, 60);
  const late = update(5.04, 60);
  renderer.update(5.04, 60, false);
  for (const {mesh} of renderer.batches) {
    assert.equal(mesh.visible, false);
    assert.equal(mesh.geometry.instanceCount, 0);
  }
  update(.43, 30);
  assert.deepEqual(update(5.04, 60), late);
  assert.equal(root.children.length, 4);
  renderer.dispose();
  renderer.dispose();
  assert.equal(root.children.length, 0);
  assert.equal(geometries, 4);
  assert.equal(materials, 4);
  assert.equal(textures, 0, "the atlas belongs to the caller that shares it with center stars");
  atlas.dispose();
  assert.equal(textures, 1);
}

const rows = fixture();
verifySimulation(rows);
verifyBatches(rows);
console.log("Native moving companions: fixed-cadence birth order, seeks, packed colors, bounded batches, masks, and cleanup.");
