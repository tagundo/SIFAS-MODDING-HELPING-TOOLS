"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-butterfly-simulation.js");
require("../webtools/web/static/mv-studio-butterfly-glow-simulation.js");

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

assert.equal(create(2914, "unknown"), null);
const finale = create(2914, "finale");
assert.deepEqual(finale.random, random);
assert.equal(finale.sample(0, 60), null);
assert.equal(finale.appearance(0, 60), null);
assert.equal(finale.sample(1 / 60, 30), null);
assert.equal(finale.appearance(1 / 60, 30), null);
assert.deepEqual(finale.sample(1 / 60, 60), [1.666666804567285e-11, -1.666666804567285e-11, 1.666666804567285e-11]);
assert.deepEqual(finale.sample(1 / 30, 30), [1.666668504185509e-5, -1.666668504185509e-5, 1.666668504185509e-5]);

// Original Android mesh size and packed RGBA alpha around the finale rise, fade, and expiry.
const appearance = (tick, fps = 60) => finale.appearance(tick / fps, fps);
assert.deepEqual(appearance(1), {size: 6.731137275695801, alpha: 255});
assert.deepEqual(appearance(318), {size: 6.731137275695801, alpha: 255});
assert.deepEqual(appearance(319), {size: 6.733858108520508, alpha: 255});
assert.deepEqual(appearance(320), {size: 6.765983581542969, alpha: 255});
assert.deepEqual(appearance(321), {size: 6.831321716308594, alpha: 251});
assert.deepEqual(appearance(325), {size: 7.349940299987793, alpha: 174});
assert.deepEqual(appearance(165, 30), {size: 8.296347618103027, alpha: 79});
assert.deepEqual(appearance(333), {size: 8.84354305267334, alpha: 21});
assert.equal(appearance(334), null);
assert.equal(appearance(167, 30), null);
assert.equal(finale.sample(334 / 60, 60), null);
assert.equal(finale.sample(167 / 30, 30), null);
assert.deepEqual(appearance(1), {size: 6.731137275695801, alpha: 255});
assert.deepEqual(simulation.sample(13, 60), late);

// Original billboard worker size and packed Color32 inputs, sampled at both
// display rates before and after the opening pulse wrap and finale fade.
const glows = MVStudioButterflyGlowSimulation;
assert.equal(glows.create("unknown"), null);
const openingGlow = glows.create("opening");
const blue = [11, 60, 255, 36];
assert.equal(openingGlow.sample(0, 60), null);
assert.deepEqual(openingGlow.sample(1 / 60, 60), {size: .3758937120437622, rgba: blue});
assert.deepEqual(openingGlow.sample(1 / 30, 30), {size: .3758782148361206, rgba: blue});
assert.deepEqual(openingGlow.sample(6, 60), {size: .30318084359169006, rgba: blue});
assert.deepEqual(openingGlow.sample(8, 30), {size: .3999679386615753, rgba: blue});
assert.deepEqual(openingGlow.sample(1048 / 60, 60), {size: .39999738335609436, rgba: blue});
assert.deepEqual(openingGlow.sample(1049 / 60, 60), {size: .37588736414909363, rgba: blue});
assert.deepEqual(openingGlow.sample(30, 30), {size: .39478302001953125, rgba: blue});
assert.equal(openingGlow.sample(1801 / 60, 60), null);
assert.deepEqual(openingGlow.sample(1 / 60, 60), {size: .3758937120437622, rgba: blue});

const finaleGlow = glows.create("finale");
const pink = alpha => [252, 143, 255, alpha];
assert.deepEqual(finaleGlow.sample(1 / 60, 60), {size: .2528753876686096, rgba: pink(0)});
assert.deepEqual(finaleGlow.sample(1 / 30, 30), {size: .26595911383628845, rgba: pink(5)});
assert.deepEqual(finaleGlow.sample(20 / 60, 60), {size: .4057421386241913, rgba: pink(108)});
assert.deepEqual(finaleGlow.sample(16 / 30, 30), {size: .4543570280075073, rgba: pink(119)});
assert.deepEqual(finaleGlow.sample(27 / 30, 30), {size: .49989715218544006, rgba: pink(9)});
assert.equal(finaleGlow.sample(55 / 60, 60), null);
assert.equal(finaleGlow.sample(28 / 30, 30), null);
assert.deepEqual(finaleGlow.sample(1 / 60, 60), {size: .2528753876686096, rgba: pink(0)});

async function checkCuePlayback() {
  const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
  require("../webtools/web/static/mv-studio-stage-motion.js");
  require("../webtools/web/static/mv-studio-display-lights.js");
  require("../webtools/web/static/mv-studio-butterfly.js");
  global.MVStudioTitle = {
    validMipChain: levels => levels?.length === 1,
    boundedCurve: (curve, valid) => valid(curve),
    loadTexture: async () => new T.Texture(),
  };
  const row = {
    schema: 1, trackId: "track", eventId: "event", texture: [{width: 512}],
    geometry: {positions: Array.from({length: 6}, () => [0,0,0]),
      uv: Array.from({length: 6}, () => [0,0]), indices: [0,1,2,0,2,3,2,3,4,2,4,5]},
    animation: {duration: Math.fround(5.7), curves: [0,0,0].map(value => ["constant", value]),
      tintCurves: [2,2,2,1].map(value => ["constant", value])},
    particle: {birth: 0, lifetime: Math.fround(5.55), size: 9, velocity: [-.001,-.001,.001], color: [1,1,1,1]},
    material: {randomMove: [.01,.0075,.01,10], randomUp: [.1,0,.1,10], ambient: [1,1,1,0], tint: [2,2,2,1],
      flapSpeed: 28, flapIntensity: .9, randomFlapIntensity: .3, randomFlapDelay: 1},
    glow: {profile: "finale", activation: Math.fround(5 + 5 / 60), maxViewportWidth: 1, position: [0,0,0],
      uv: [.5,.5,.5,.5], material: {queue: 3010, cull: 0, blend: "add", premultiply: false, tint: [1,1,1,1]}},
  };
  const root = new T.Group();
  const control = await MVStudioButterfly.apply(T, root, {schema: 1, finale: row, glowTexture: [{width: 256}]});
  assert.ok(control);
  const [mesh, glow] = root.children;
  assert.equal(glow.material.stencilFunc, T.AlwaysStencilFunc);
  assert.equal(glow.renderOrder, 3010);
  const event = {id: "event", start: 89.01666666666732, duration: 8.85,
    values: {playableClass: "CustomControlClip", weight: 1, timeScale: 1, offset: {x: 0, y: 0, z: 0}}};
  const track = {id: "track", nativeClass: "CustomControlTrack", events: [event]};
  const quality = {frame_rate_60fps: true};
  const project = {tracks: [track], quality: {values: quality}};
  const at = time => { control.update(time, project); return mesh.visible; };
  assert.equal(at(5341 / 60 - 2e-12), false);
  assert.equal(at(5341 / 60), true);
  const uniforms = mesh.material.uniforms;
  assert.equal(uniforms.uSize.value, 6.731137275695801);
  assert.equal(at(5673 / 60), true);
  assert.equal(uniforms.uSize.value, 8.84354305267334);
  assert.equal(uniforms.uColor.value.w, 21 / 255);
  assert.equal(at(5674 / 60), false);
  quality.frame_rate_60fps = false;
  assert.equal(at(5341 / 60), false);
  assert.equal(at(2671 / 30), true);
  assert.equal(at(2836 / 30), true);
  assert.equal(uniforms.uColor.value.w, 40 / 255);
  assert.equal(at(2837 / 30), false);
  assert.equal(at(2671 / 30), true);
  assert.equal(uniforms.uColor.value.w, 1);
  const glowGeometry = glow.geometry;
  const alpha = glowGeometry.getAttribute("particleColor");
  at(94.1);
  assert.equal(glowGeometry.instanceCount, 1);
  assert.equal(alpha.getW(0), 5);
  quality.frame_rate_60fps = true;
  at(94.1 - 1 / 60);
  assert.equal(glow.visible, false);
  at(94.1);
  assert.equal(glowGeometry.instanceCount, 1);
  assert.equal(alpha.getW(0), 0);
  assert.equal(at(5674 / 60), false);
  assert.equal(glow.visible, true);
  at(95);
  assert.equal(glowGeometry.instanceCount, 0);
  event.start += .25;
  at(94.1);
  assert.equal(glow.visible, false);
  at(94.35);
  assert.equal(glowGeometry.instanceCount, 1);
  assert.equal(alpha.getW(0), 0);
  track.muted = true;
  assert.equal(at(2671 / 30), false);
  control.dispose();
  assert.equal(root.children.length, 0);
}

checkCuePlayback().catch(error => { console.error(error); process.exitCode = 1; });
