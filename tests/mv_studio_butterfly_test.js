"use strict";

const assert = require("node:assert/strict");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-butterfly-simulation.js");
require("../webtools/web/static/mv-studio-butterfly-glow-simulation.js");
require("../webtools/web/static/mv-studio-butterfly-shine-simulation.js");
require("../webtools/web/static/mv-studio-butterfly-dust-simulation.js");

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

function checkShineSimulation() {
  // Original Expert par_shine source curves and packed gradient keys from the paired bundles.
  const source = {
    sizeKeys: [
      [[0, 1], [.04789190739393234, .5412497520446777], [.10946407914161682, .9522058367729187],
        [.15849487483501434, .38295912742614746], [.21892815828323364, .8736255764961243],
        [.2827822268009186, .5016687512397766], [.38198402523994446, .20885176956653595],
        [.44127708673477173, .5412388443946838], [.5245153903961182, .3038196265697479],
        [.5883444547653198, .49571478366851807], [.6727480292320251, .6995182633399963],
        [.8072975873947144, .2642497420310974], [.8642685413360596, .6303539276123047],
        [.9245991706848145, .09368271380662918], [1, 0]],
      [[0, 1], [.015933051705360413, .2490587681531906], [.08008640259504318, .7750393152236938],
        [.13226911425590515, .5217978358268738], [.1948753297328949, 1],
        [.24826061725616455, .2736821174621582], [.311288446187973, .8118323087692261],
        [.36898064613342285, .5886486768722534], [.4104903042316437, .8339818120002747],
        [.46387240290641785, .15667565166950226], [.5051339268684387, .8610309958457947],
        [.5537682175636292, .08005019277334213], [.6152468919754028, .8574442863464355],
        [.6465222239494324, .9790809154510498], [.7056977152824402, .2867186367511749],
        [.7662485837936401, .4924817681312561], [.8360212445259094, .92377769947052],
        [.8866571187973022, .4357251822948456], [.9496652483940125, .77158522605896], [1, 0]],
    ],
    startRGB: [
      [1349, .9201741814613342, 1, .6367924213409424], [12529, .75, .9375, 1],
      [26792, 1, .7594339847564697, .954177975654602], [40670, .8518779873847961, .8349056243896484, 1],
      [54548, .5896226167678833, .9650065898895264, 1], [65535, .9450549483299255, 1, .75],
    ],
    alphaKeys: [
      [[0, 0], [7903, 255], [21588, 119], [33924, 255], [36623, 123], [39321, 255], [47224, 255], [65535, 0]],
      [[0, 0], [9059, 255], [14264, 255], [16962, 95], [19275, 255], [31033, 185], [47224, 255], [65535, 0]],
    ],
  };
  const stationaryOrigin = () => [-.02, -.0369, 0];
  const simulate = MVStudioButterflyShineSimulation.create;
  assert.equal(simulate("finale", stationaryOrigin, source), null);
  assert.equal(simulate("opening", stationaryOrigin, {...source, alphaKeys: {length: 2}}), null);
  assert.equal(simulate("opening", stationaryOrigin, {...source, sizeKeys: {length: 2}}), null);
  const stationary = simulate("opening", stationaryOrigin, source);
  const sample = (stream, frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...row) => rows.push(row));
    return rows;
  };
  const matchNative = (row, expected) => {
    assert.ok(row);
    for (let axis = 0; axis < 3; axis++) {
      assert.ok(Math.abs(row[axis] - expected[axis]) <= 5e-8, `position export axis ${axis}`);
    }
    assert.deepEqual(row.slice(3), expected.slice(3));
  };
  assert.deepEqual(sample(stationary, 0, 60), []);
  assert.deepEqual(sample(stationary, 1, 120), []);
  const birth = sample(stationary, 1, 60);
  assert.equal(birth.length, 10);
  matchNative(birth[0], [-.010669597424566746, -.05559857189655304, .003236304270103574,
    .03309192508459091, 229, 253, 174, 0]);
  const next = sample(stationary, 2, 60);
  assert.deepEqual(sample(stationary, 1, 30), next);
  matchNative(next[0], [-.011299611069262028, -.056183844804763794, .003236304270103574,
    .03309192508459091, 229, 253, 174, 26]);

  // Compare worker output for the first continuing birth under a moving emitter.
  // Grouped 30 Hz uses the previous and current display centers around both steps.
  const moving = simulate("opening", (index, fps) => {
    const time = index / fps;
    return [-time, .25 * time, -.5 * time];
  }, source);
  assert.equal(sample(moving, 6, 60).length, 10);
  const firstContinuous = sample(moving, 7, 60);
  assert.equal(firstContinuous.length, 11);
  matchNative(firstContinuous[10], [-.10366445779800415, .0139396321028471, -.06300190091133118,
    .034015558660030365, 211, 246, 212, 22]);
  const grouped = sample(moving, 4, 30);
  assert.equal(grouped.length, 11);
  matchNative(grouped[10], [-.08840207010507584, .009437602013349533, -.05466856807470322,
    .008831566199660301, 211, 246, 212, 45]);
  assert.deepEqual(sample(moving, 60, 60).length, 19);
  assert.deepEqual(sample(moving, 7, 60), firstContinuous);
  assert.deepEqual(sample(moving, 4, 30), grouped);
  assert.deepEqual(sample(moving, 1000, 60), []);
}

function checkTerminalDust() {
  // Original Aion Expert cue .14 tracks. Null is Unity's positive infinite step tangent.
  const stepped = rows => rows.map(([time, value, slope = 0]) => [time, value, slope, null]);
  const cubic = rows => rows.map(([time, value, slope = 0]) => [time, value, slope, slope]);
  const source = {
    profile: "finale",
    sizeKeys: [
      [[0, 0, 0, 0], ...stepped([
        [.07092845439910889, .99871826171875], [.08488550037145615, .5823833346366882],
        [.2837209403514862, .8923704028129578], [.38720932602882385, .3696727156639099],
        [.4872093200683594, .7432135343551636], [.575581431388855, .05838865041732788],
        [.6720680594444275, .7159703969955444], [.8337240815162659, .12453973293304443, -1.8227180242538452],
        [.94537353515625, 0],
      ])],
      [[0, 0, 14.061713218688965, 14.061713218688965], ...stepped([
        [.07093019783496857, .9974001049995422], [.1360969841480255, .4648019075393677],
        [.22637861967086792, .8279175758361816], [.3290593922138214, .5685369968414307, -2.9959564208984375],
        [.4372093081474304, .19627803564071655], [.5175036191940308, .8752418756484985],
        [.6212199926376343, .12713623046875], [.699932336807251, .42780134081840515],
        [.7810105085372925, 0], [.882636547088623, .22521525621414185], [.9988372325897217, 0],
      ])],
    ],
    velocity: [
      {min: cubic([[0, -.06557464599609375, 3.3360631465911865], [.35082143545150757, .41491127014160156],
        [.6757609844207764, .32975369691848755, 1.1653300523757935], [1, .42529296875]]),
      max: cubic([[0, -.00601959228515625, -2.2723231315612793], [.3628977835178375, -.38587719202041626],
        [.6899983882904053, -.35462987422943115, -.6594409942626953], [1, -.7930992841720581, .4548633098602295]]),
      scale: [-Math.fround(.2), .5]},
      {min: cubic([[Math.fround(.01), .05303030461072922], [1, .05303030461072922]]),
      max: cubic([[0, .997406005859375], [1, .33333396911621094]]), scale: [Math.fround(.1), Math.fround(.6)]},
      {min: cubic([[0, 1], [1, .1212158203125]]), max: cubic([[0, -1], [1, .05303001403808594]]), scale: [-.5, .5]},
    ],
    alphaKeys: [[0, 0], [9445, 255], [65535, 255]],
    emitters: [
      {role: "add", startColor: {rgb: [
        [[0, 1, .5209566354751587, .2971698045730591], [27274, .47641509771347046, 1, .5943034291267395],
          [52139, .39150941371917725, .7363207340240479, 1], [65535, .9905660152435303, .6655070781707764, .6494749188423157]],
        [[0, .8057403564453125, 0, 1], [9638, .9938510656356812, 1, .6556603908538818],
          [24768, .47641509771347046, 1, .5943034291267395], [48380, .9905660152435303, .6655070781707764, .6494749188423157],
          [63029, 1, .5869981646537781, .39150941371917725]],
      ], alpha: [
        [[0, .6784313917160034], [7421, .5960784554481506], [65535, .5960784554481506]],
        [[0, Math.fround(.8)], [65535, Math.fround(.8)]],
      ]}},
      {role: "alpha", startColor: [.011172260157763958, 0, .1320754885673523, Math.fround(.4)]},
    ],
  };
  const createDust = MVStudioButterflyDustSimulation.create;
  const origin = () => [0, 0, 0];
  assert.equal(createDust("opening", origin, source), null);
  assert.equal(createDust("alpha", origin, {...source, velocity: {length: 3}}), null);
  assert.equal(createDust("add", origin, {...source, emitters: source.emitters.slice(1)}), null);
  const alpha = createDust("alpha", origin, source);
  const add = createDust("add", origin, source);
  const sample = (stream, frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...row) => rows.push(row));
    return rows;
  };
  const matchNative = (row, expected) => {
    assert.ok(row);
    for (let axis = 0; axis < 3; axis++) {
      assert.ok(Math.abs(row[axis] - expected[axis]) <= 2e-8, `position export axis ${axis}`);
    }
    assert.deepEqual(row.slice(3), expected.slice(3));
  };
  assert.deepEqual(sample(add, 0, 60), []);
  assert.deepEqual(sample(add, 1, 120), []);
  const first = sample(add, 1, 60);
  assert.equal(first.length, 40);
  matchNative(first[0], [.0401667095720768, .025382693856954575, .012935043312609196,
    2.151601563582517e-9, 218, 44, 214, 0, 0]);
  const grouped = sample(add, 1, 30);
  assert.deepEqual(grouped, sample(add, 2, 60));
  matchNative(grouped[4], [-.002966873114928603, .024780267849564552, .018527839332818985,
    .0037842944730073214, 231, 80, 163, 17, 1]);
  matchNative(sample(alpha, 1, 30)[0], [.040275100618600845, .026696721091866493, .014043327420949936,
    .0034054333809763193, 3, 0, 34, 7, 0]);
  assert.equal(sample(add, 17, 60).length, 40);
  const secondBurst = sample(add, 18, 60);
  assert.equal(secondBurst.length, 60);
  assert.deepEqual(sample(add, 9, 30), secondBurst);
  matchNative(secondBurst[40], [.0007994604529812932, -.013364840298891068, .01431858167052269,
    7.735687646004408e-9, 189, 219, 133, 0, 1]);
  const tail = sample(add, 110, 60);
  assert.equal(tail.length, 9);
  matchNative(tail[0], [-.01795092597603798, .07271098345518112, -.0911276713013649,
    .005893088411539793, 189, 219, 133, 169, 0]);
  assert.deepEqual(sample(add, 126, 60), []);
  assert.deepEqual(sample(add, 1, 60), first);
  assert.deepEqual(sample(add, 18, 60), secondBurst);
  assert.deepEqual(sample(createDust("add", origin, source), 110, 60), tail);
}

checkShineSimulation();
checkTerminalDust();
checkCuePlayback().catch(error => { console.error(error); process.exitCode = 1; });
