"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-confetti-air-simulation.js");
require("../webtools/web/static/mv-studio-rain-simulation.js");
require("../webtools/web/static/mv-studio-rain-floor-simulation.js");
require("../webtools/web/static/mv-studio-autumn-leaves-simulation.js");
require("../webtools/web/static/mv-studio-autumn-red-burst-simulation.js");
require("../webtools/web/static/mv-studio-autumn-floor-simulation.js");
require("../webtools/web/static/mv-studio-autumn-burst-simulation.js");
require("../webtools/web/static/mv-studio-momiji-leaves-simulation.js");
require("../webtools/web/static/mv-studio-momiji-fan-simulation.js");

// The loader stands in for the browser's PNG decoder. It gives the same
// per-level image sizes so the controller can build the authored mip chain.
T.TextureLoader = class {
  async loadAsync(url) {
    const header = Buffer.from(url.split(",")[1], "base64");
    return new T.Texture({width: header.readUInt32BE(16), height: header.readUInt32BE(20)});
  }
};

function level(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {width: size, height: size, png: header.toString("base64")};
}

async function test() {
  const root = new T.Group();
  const shape = {positions: [[-1,0,1],[1,0,1],[1,0,-1]], uv: [[0,0],[1,0],[1,1]], indices: [0,1,2]};
  const native = {geometry: shape, texture: 0, position: [0,.01,0], rotation: [0,0,0,1], scale: [1,1,1],
    birth: .05, lifetime: 1, size: .75, sizeCurve: ["constant", 1], yaw: .5, yawSpeed: -.25,
    color: {rgb: [[0,1,1,1]], alpha: [[0,.6]]}, uvOffset: [["constant", .25], ["constant", .5]],
    material: {queue: 3010, cull: 0, blend: "add", tint: [1,1,1,1], uv: [.5,.25,.125,.25], premultiply: true}};
  const orbit = {...native, texture: 1, position: [2, .05, 0], orbitY: Math.PI / 2,
    color: {rgba8: {start: [189, 255, 128, 77], keys: [[0, 200, 100, 255, 20], [1, 90, 254, 0, 100]]}},
    material: {...native.material, premultiply: false}};
  const tilt = 1.570796251296997;
  const glow = {...native, rollRange: [-tilt, tilt], yaw: 0, yawSpeed: 0,
    rotation: [-Math.sin(tilt / 2), 0, 0, Math.cos(tilt / 2)]};
  const descriptor = {textures: [Array.from({length:10}, (_, index) => level(512 >> index)),
    Array.from({length:9}, (_, index) => level(256 >> index))],
    templates: [[native, orbit, glow]], cues: [{trackId: "track", eventId: "first", template: 0},
      {trackId: "track", eventId: "second", template: 0}]};
  const previous = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const seeds = [2914, 1];
  Object.defineProperty(globalThis, "crypto", {
    configurable: true, value: {getRandomValues(words) { words[0] = seeds.shift(); return words; }},
  });
  let controller;
  try {
    controller = await MVStudioStageParticles.apply(T, root, descriptor);
  } finally {
    if (previous) Object.defineProperty(globalThis, "crypto", previous);
    else delete globalThis.crypto;
  }
  assert.deepEqual(seeds, []);
  assert(controller);
  const [first, second] = root.children;
  assert.equal(first.children[0].geometry, second.children[0].geometry);
  const event = {id: "first", start: 42.85, duration: 1.6, values: {
    playableClass: "CustomControlClip", clipIn: 6.4833, timeScale: 1, weight: 1, offset: {x: -.3,y:0,z:1.2},
  }};
  const track = {id:"track", events: [event, {...event,id:"second",start:46}]};
  const project = {tracks: [track], quality: {values:{stage_control:true}}};
  controller.update(event.start, project);
  assert.equal(first.visible, true);
  assert.equal(first.children[0].visible, false);
  controller.update(43.15, project);
  const mesh = first.children[0], uniforms = mesh.material.uniforms;
  assert.equal(mesh.visible, true);
  assert.equal(second.visible, false);
  assert.deepEqual(first.position.toArray(), [.3,0,1.2]);
  assert.deepEqual(mesh.position.toArray(), [0,.01,0]);
  assert.deepEqual(mesh.scale.toArray(), [.75,.75,.75]);
  assert.deepEqual(uniforms.uTextureST.value.toArray(), [.5,.25,.25,.375]);
  assert.deepEqual(uniforms.uTint.value.toArray(), [1,1,1,.6]);
  assert.equal(uniforms.uTexture.value.mipmaps.length, 10);
  assert.equal(uniforms.uTexture.value.generateMipmaps, false);
  assert.equal(mesh.material.defines.SOURCE_ALPHA, 1);
  assert.equal(mesh.material.blendDst, T.OneFactor);
  assert.equal(mesh.material.depthWrite, false);
  const orbitMesh = first.children[1], angle = (43.15 - event.start - orbit.birth) * orbit.orbitY;
  assert(Math.abs(orbitMesh.position.x - 2 * Math.cos(angle)) < 1e-9);
  assert(Math.abs(orbitMesh.position.z + 2 * Math.sin(angle)) < 1e-9);
  assert.equal(orbitMesh.position.y, .05);
  assert.equal(orbitMesh.material.uniforms.uTexture.value.mipmaps.length, 9);
  assert.deepEqual(orbitMesh.material.uniforms.uTint.value.toArray(), [128,138,96,12].map(byte => byte / 255));
  assert.deepEqual(orbitMesh.material.defines, {});
  const glowMesh = first.children[2];
  const expectedGlow = new T.Quaternion().fromArray(glow.rotation).multiply(
    new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 0, 1), -.8231363296508789));
  assert(glowMesh.quaternion.angleTo(expectedGlow) < 1e-6);
  controller.update(46.17, project);
  assert.equal(first.visible, false);
  assert.equal(second.visible, true);
  assert(second.children[2].quaternion.angleTo(glowMesh.quaternion) > .1);
  controller.update(43.15, project);
  assert.equal(first.visible, true);
  assert(glowMesh.quaternion.angleTo(expectedGlow) < 1e-6);
  assert(Math.abs(orbitMesh.position.x - 2 * Math.cos(angle)) < 1e-9);
  project.quality.values.stage_control = false;
  controller.update(43.15, project);
  assert.equal(first.visible, false);
  project.quality.values.stage_control = true;
  track.muted = true;
  controller.update(43.15, project);
  assert.equal(first.visible, false);
  controller.dispose();
  assert.equal(root.children.length, 0);
  console.log("Native stage particles preserve activation age, world offsets, separate cues, UV offsets and original mips.");
}

async function testFinaleFlash() {
  const root = new T.Group();
  const geometry = {
    positions: [[.5,-.5,0],[-.5,.5,0],[-.5,-.5,0],[.5,.5,0]],
    uv: [[0,1],[1,0],[1,1],[0,0]], indices: [0,2,1,1,3,0],
  };
  const flash = {
    geometry, material: {queue: 3010, cull: 0, blend: "add", tint: [2,2,2,1], uv: [1,1,0,0]},
    texture: 0, position: [0,0,-.10999999940395355], rotation: [0,0,0,1], scale: [1,1,1],
    birth: 0, lifetime: 6, size: 55, sizeCurve: ["constant", 1], yaw: 0, yawSpeed: 0, maxViewportWidth: 4,
    color: {rgba8: {start: [170,128,255,242], keys: [[0,255,255,255,0],
      [0.3000076413154602,255,255,255,0], [0.3199969530105591,255,255,255,255], [1,255,255,255,255]]}},
  };
  const horizontal = {...flash, position: [0,.009999999776482582,-.10000000149011612],
    rotation: [Math.SQRT1_2,0,0,Math.SQRT1_2]};
  const descriptor = {
    schema: 3, textures: [Array.from({length:10}, (_, index) => level(512 >> index))],
    templates: [[flash, horizontal]], cues: [{trackId: "stage", eventId: "flash", template: 0}],
  };
  const event = {id: "flash", start: 113.03333333333333, duration: 5.583333333333385, values: {
    playableClass: "CustomControlClip", timeScale: 1, weight: 1, offset: {x:0,y:0,z:0},
  }};
  const project = {tracks: [{id: "stage", events: [event]}], quality: {values: {stage_control:true}}};
  assert.equal(await MVStudioStageParticles.apply(T, root, {
    ...descriptor, templates: [[{...flash, maxViewportWidth: undefined}]],
  }), null);
  const controller = await MVStudioStageParticles.apply(T, root, descriptor);
  assert(controller);
  const [group] = root.children;
  const [verticalMesh, horizontalMesh] = group.children;
  const uniforms = verticalMesh.material.uniforms;
  assert.equal(uniforms.uTexture.value, horizontalMesh.material.uniforms.uTexture.value);
  assert.equal(verticalMesh.geometry, horizontalMesh.geometry);
  assert.deepEqual(verticalMesh.material.defines, {VIEWPORT_SIZE_LIMIT: 1});
  controller.update(114.83, project);
  assert.equal(uniforms.uTint.value.w, 0);
  controller.update(114.9, project);
  assert(uniforms.uTint.value.w > 0 && uniforms.uTint.value.w < 242/255);
  controller.update(115, project);
  assert.deepEqual(uniforms.uTint.value.toArray(), [340/255,256/255,2,242/255]);

  const camera = new T.PerspectiveCamera(31.890792846679688, 16/9, .1, 1000);
  camera.position.set(-.08395847776131166, .9213643821069722, 10.883033130660202);
  camera.quaternion.set(.04636735570090267, 0, 0, .9989244557649524).normalize();
  camera.updateMatrixWorld();
  root.updateMatrixWorld(true);
  for (const [mesh, expected] of [[verticalMesh,44.131207727776435], [horizontalMesh,44.09451175360153]]) {
    mesh.onBeforeRender(null, null, camera);
    assert(Math.abs(mesh.material.uniforms.uViewportScale.value * 55 - expected) < 1e-5);
    assert.deepEqual(mesh.scale.toArray(), [55,55,55]);
  }
  assert.deepEqual(horizontalMesh.quaternion.toArray(), horizontal.rotation);
  camera.position.z = 20;
  camera.updateMatrixWorld();
  verticalMesh.onBeforeRender(null, null, camera);
  assert.equal(uniforms.uViewportScale.value, 1);

  const orthographic = new T.OrthographicCamera(-3, 3, 2, -2, .1, 1000);
  orthographic.updateMatrixWorld();
  verticalMesh.onBeforeRender(null, null, orthographic);
  assert.equal(uniforms.uViewportScale.value * 55, 24);
  controller.update(event.start + event.duration, project);
  assert.equal(group.visible, false);
  controller.dispose();
  assert.equal(root.children.length, 0);
  console.log("Monster Girls finale flash preserves native fade, local planes and the per-camera width limit.");
}

function testAionRain() {
  const source = {
    rotation: [Math.SQRT1_2, 0, 0, Math.SQRT1_2],
    sizeKeys: [
      [[0, .48181650042533875, 0, 0], [.11518724262714386, .624366283416748, 1.4387071132659912, 1.4387071132659912],
        [1, 1, 0, 0]],
      [[0, 0, 0, 0], [.16759809851646423, .33066192269325256, 1.7415918111801147, 1.7415918111801147],
        [1, 0, -.4135459065437317, -.4135459065437317]],
    ],
    startRGB: [
      [0, .5801886916160583, .877376139163971, 1], [28045, .989980936050415, 1, .6596245765686035],
      [65535, .6745283007621765, 1, .8095535635948181],
    ],
    colorKeys: {
      rgb: [[0, 1, .7971698045730591, .8793900609016418], [65535, 1, 1, 1]],
      alpha: [[0, 0], [14637, 1], [49922, .48235294222831726], [65535, 0]],
    },
  };
  const createRain = globalThis.MVStudioRainSimulation.create, f32 = Math.fround;
  const opening = {...source, profile: "01", position: [-.19, 15.01, -3.88].map(f32)};
  const ending = {...source, profile: "02", position: [-.19, 8.54, -3.88].map(f32)};
  assert.equal(createRain({...opening, sizeKeys: {length: 2}}), null);
  assert.equal(createRain({...ending, position: [0, 0, 0]}), null);
  const continuing = createRain(opening);
  const fading = createRain(ending);
  const at = (stream, frame, fps) => {
    const results = [];
    stream.sample(frame / fps, fps, (...packet) => results.push(packet));
    return results;
  };
  const matchesNative = (packet, expected) => {
    assert.ok(packet);
    for (let field = 0; field < 6; field++) {
      assert.ok(Math.abs(packet[field] - expected[field]) <= 2e-6, `rain position or velocity field ${field}`);
    }
    assert.deepEqual(packet.slice(6), expected.slice(6));
  };

  // Connected original Android worker, warming to 168 live particles before the first update.
  const warm = at(continuing, 0, 60);
  assert.equal(warm.length, 168);
  matchesNative(warm[0], [1.304569959640503, -5.445957183837891, -8.121582984924316,
    0, -24.81845474243164, -.18065208196640015, .29021546244621277, 1.3251445293426514, 187, 234, 223, 7]);
  const grouped = at(continuing, 1, 30);
  assert.deepEqual(grouped, at(continuing, 2, 60));
  matchesNative(grouped[0], [6.39950704574585, 14.827088356018066, .8662109375,
    0, -4.5859055519104, -.15722298622131348, .06587917357683182, .33306992053985596, 243, 205, 152, 33]);
  const wrap = at(continuing, 30, 60);
  assert.equal(wrap.length, 168);
  matchesNative(wrap[4], [8.466684341430664, 11.772109985351562, 3.451857089996338,
    0, -10.383543968200684, -.15059418976306915, .1950044184923172, 1.000145673751831, 232, 220, 163, 231]);

  // Seek near the end of the native cue, then use checkpoints to rewind deterministically.
  const late = at(continuing, 1281, 30);
  assert.equal(late.length, 168);
  matchesNative(late[57], [9.687050819396973, 8.857813835144043, -11.227054595947266,
    0, -13.734615325927734, -.151360884308815, .15392673015594482, .6711877584457397, 215, 220, 187, 185]);
  assert.deepEqual(at(continuing, 0, 30), warm);
  assert.deepEqual(at(continuing, 1, 30), grouped);
  assert.deepEqual(at(continuing, 2562, 60), late);

  assert.deepEqual(at(fading, 0, 60), []);
  assert.deepEqual(at(fading, 1, 60), []);
  const first = at(fading, 1, 30);
  assert.equal(first.length, 1);
  matchesNative(first[0], [1.304569959640503, 8.539999961853027, -10.117005348205566,
    .0667838379740715, -10.512883186340332, -.02260831743478775, .13980631530284882, .42304930090904236, 187, 187, 196, 0]);
  assert.deepEqual(first, at(fading, 2, 60));
  const lastEmission = at(fading, 150, 60);
  assert.equal(lastEmission.length, 53);
  matchesNative(lastEmission[0], [-3.4947824478149414, .3153972625732422, 1.0431108474731445,
    .12405794858932495, -9.48993968963623, .04278596490621567, .17133168876171112, .30916571617126465, 189, 210, 206, 200]);
  assert.equal(at(fading, 240, 60).length, 6);
  assert.deepEqual(at(fading, 270, 60), []);
  assert.deepEqual(at(fading, 1, 30), first);
}

function testAionRainFloor() {
  const color02 = [
    [0, .5, .5387755632400513, 1], [22359, .5, .7534246444702148, 1],
    [50597, .7557470798492432, .5, 1], [65535, .5, 1, .5176470279693604],
  ];
  const start02 = [
    [0, .5801886916160583, .877376139163971, 1], [28045, .989980936050415, 1, .6596245765686035],
    [65535, .6745283007621765, 1, .8095535635948181],
  ];
  const size02 = [[0, .5, 1.405066967010498, 1.405066967010498], [1, 1, 0, 0]];
  const f32 = Math.fround;
  const second = {
    wave: {
      position: [0, f32(.02), 1], sizeKeys: size02, frameKeys: [[0, 0, 0, 1], [1, 1, 1, 0]],
      startColor: {mode: 4, rgb: start02, alpha: [[0, 1], [65535, 1]]},
      colorKeys: {rgb: color02, alpha: [[0, 0], [7806, 1], [22166, 1], [65535, 0]]},
    },
    glow: {
      sizeKeys: size02, startColor: [1, 1, 1, f32(.4)],
      colorKeys: {rgb: color02, alpha: [[0, 0], [13203, 1], [65535, 0]]},
    },
  };
  const first = {
    wave: {
      position: [0, f32(.02), 0], frameKeys: [[0, 0, 1, 1], [1, 1, 1, 1]],
      sizeKeys: [[0, .15517425537109375, 2.1027917861938477, 2.1027917861938477], [1, 1, 0, 0]],
      startColor: {mode: 1, rgb: [
        [0, .8349056243896484, .9521689414978027, 1], [28045, .9946324229240417, 1, .8443396091461182],
        [65535, .8443396091461182, 1, .9081041216850281],
      ], alpha: [[0, f32(.8)], [65535, .501960813999176]]},
      colorKeys: {rgb: [
        [0, .6247774958610535, .9504353404045105, .9811320900917053], [65535, .501960813999176, .8025936484336853, 1],
      ], alpha: [[0, 0], [7806, 1], [28334, .7058823704719543], [65535, 0]]},
    },
    glow: {...second.glow, startColor: [1, 1, 1, .14901961386203766]},
  };
  const createFloor = globalThis.MVStudioRainFloorSimulation.create;
  const at = (stream, frame, fps) => {
    const rows = {wave: [], glow: []};
    stream.sample(frame / fps, fps, (role, ...packet) => rows[role].push(packet));
    return rows;
  };
  assert.equal(createFloor("02", {...second, glow: null}), null);
  assert.equal(createFloor("01", second), null);
  const ending = createFloor("02", second);
  assert.deepEqual(at(ending, 1, 60), {wave: [], glow: []});
  const birth = at(ending, 2, 60);
  assert.equal(birth.wave.length, 1);
  assert.deepEqual(birth.wave[0], [-7.994955062866211, .019999999552965164, 2.80983829498291,
    .1340492069721222, -.12423050403594971, 115, 137, 179, 0, 0]);
  assert.equal(birth.glow.length, 1);
  assert.deepEqual(birth.glow[0], [-7.994955062866211, .019999999552965164, 2.80983829498291,
    .20729269087314606, -.12423050403594971, 128, 145, 255, 24, 3]);
  const groupedBirth = at(ending, 1, 30);
  assert.deepEqual(groupedBirth.wave, birth.wave);
  assert.deepEqual(groupedBirth.glow[0], [-7.994955062866211, .019999999552965164, 2.80983829498291,
    .22850120067596436, -.12423050403594971, 128, 152, 255, 47, 3]);
  // A parent born in the first 30 Hz substep also gives its child an inline .02 update.
  const groupedLater = at(ending, 4, 30);
  assert.deepEqual(groupedLater.wave, at(ending, 8, 60).wave);
  assert.deepEqual(groupedLater.glow[2], [-6.63014030456543, .019999999552965164, -1.4310824871063232,
    .2534416615962982, -1.0620362758636475, 128, 170, 255, 101, 3]);
  const later = at(ending, 30, 60);
  assert.equal(later.wave.length, 15);
  assert.deepEqual(later.wave[5], [-5.39581298828125, .019999999552965164, 4.264213562011719,
    .2514597475528717, -1.1507439613342285, 119, 157, 213, 191, 8]);
  assert.deepEqual(at(ending, 186, 60), {wave: [], glow: []});
  assert.deepEqual(at(ending, 2, 60), birth);

  const opening = createFloor("01", first);
  const warm = at(opening, 0, 60);
  assert.equal(warm.wave.length, 60);
  assert.equal(warm.glow.length, 24);
  assert.deepEqual(warm.wave[0], [-6.584455490112305, .019999999552965164, 2.817981243133545,
    .3434379994869232, .7300889492034912, 120, 217, 227, 56, 10]);
  assert.deepEqual(warm.glow[0], [2.170072078704834, .019999999552965164, -.12683212757110596,
    .35785460472106934, .862252950668335, 146, 220, 166, 3, 3]);
  const last = at(opening, 2562, 60);
  assert.equal(last.wave.length, 60);
  assert.equal(last.glow.length, 28);
  assert.deepEqual(last.wave[0], [-1.4188928604125977, .019999999552965164, -1.3924572467803955,
    .30205437541007996, -.525391697883606, 130, 209, 214, 21, 14]);
  assert.deepEqual(last.glow[0], [-4.052278518676758, .019999999552965164, 3.970980644226074,
    .3477473855018616, .43382763862609863, 177, 144, 255, 16, 3]);
  assert.deepEqual(at(opening, 0, 30), warm);
  const groupedLast = at(opening, 1281, 30);
  assert.deepEqual(groupedLast.wave, last.wave);
  assert.equal(groupedLast.glow.length, 26);
  assert.deepEqual(groupedLast.glow[0], [2.883307933807373, .019999999552965164, 3.9993906021118164,
    .29809996485710144, -.38672399520874023, 153, 167, 255, 23, 3]);
  assert.deepEqual(at(opening, 0, 60), warm);
  assert.deepEqual(at(opening, 1281, 30), groupedLast);
  assert.deepEqual(at(opening, 2562, 60), last);
}

function testAionAutumnLeaves() {
  const source = {
    position: [Math.fround(.65), 5, Math.fround(-.46)],
    rotation: [Math.SQRT1_2, 0, 0, Math.SQRT1_2],
    alphaKeys: [[0, 0], [6554, 1], [58982, 1], [65535, 0]],
  };
  const green = {...source, profile: "03", rate: 12, startColor: {
    rgb: [[0, .7924528121948242, .7491843700408936, .5494837760925293], [29141, 1, 1, 1],
      [65535, 1, .9386792182922363, .9645374417304993]],
    alpha: [[0, 1], [65535, 1]],
  }};
  const yellow = {...source, profile: "04", rate: 10, startColor: [1, 1, 1, 1]};
  const createLeaves = globalThis.MVStudioAutumnLeavesSimulation.create;
  assert.equal(createLeaves({...green, rate: 11}), null);
  assert.equal(createLeaves({...yellow, alphaKeys: {length: 4}}), null);
  const g = createLeaves(green), y = createLeaves(yellow);
  const sample = (stream, frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...packet) => rows.push(packet));
    return rows;
  };
  const matchesNative = (packet, native) => {
    assert.ok(Math.abs(packet[1] - native[1]) <= 2e-6);
    assert.deepEqual([packet[0], ...packet.slice(2)], [native[0], ...native.slice(2)]);
  };
  assert.deepEqual(sample(g, 0, 60), []);
  assert.deepEqual(sample(g, 4, 60), []);
  const birth = sample(g, 5, 60);
  assert.equal(birth.length, 1);
  matchesNative(birth[0], [-2.0827956199645996, 4.8440704345703125, -3.954949378967285,
    .6733894348144531, 1.2100321633568001e-8, 2.3756719258472003e-8, .6410994529724121, 203, 192, 142, 0]);
  const next = sample(g, 6, 60);
  assert.deepEqual(sample(g, 3, 30), next);
  matchesNative(next[0], [-2.0789833068847656, 4.832780838012695, -3.940342664718628,
    .6733894348144531, .012100333347916603, .023756742477416992, .651531994342804, 203, 192, 142, 6]);
  // The third source birth occupies most of its 60 Hz substep.
  const withPartialBirth = sample(g, 16, 60);
  assert.equal(withPartialBirth.length, 3);
  matchesNative(withPartialBirth[2], [-2.337169647216797, 5.311887741088867, .3666634261608124,
    .6703197956085205, -.015979524701833725, -.015322314575314522, -.3291763365268707, 205, 195, 147, 6]);
  assert.equal(sample(g, 599, 60).length, 80);
  const wrap = sample(g, 600, 60);
  assert.equal(wrap.length, 81);
  assert.deepEqual(sample(g, 300, 30), wrap);
  matchesNative(wrap[20], [-1.1150826215744019, 4.056926250457764, -5.795388698577881,
    .6968000531196594, .7486633658409119, 1.7617182731628418, 2.4434900283813477, 255, 245, 249, 255]);
  const tail = sample(g, 482, 30);
  assert.equal(tail.length, 79);
  matchesNative(tail[54], [-5.408440589904785, 2.3767902851104736, .844658613204956,
    .7736560106277466, 4.006777763366699, 15.496355056762695, 14.351055145263672, 217, 209, 172, 255]);
  assert.deepEqual(sample(g, 5, 60), birth);
  assert.deepEqual(sample(g, 964, 60), tail);
  assert.deepEqual(sample(g, 1, 120), []);

  assert.deepEqual(sample(y, 6, 60), []);
  const firstYellow = sample(y, 7, 60);
  assert.equal(firstYellow.length, 1);
  matchesNative(firstYellow[0], [-2.0789833068847656, 4.8327813148498535, -3.940342664718628,
    .6733894348144531, .012100310996174812, .02375669591128826, .651531994342804, 255, 255, 255, 6]);
  assert.deepEqual(sample(y, 4, 30), sample(y, 8, 60));
  const lastYellow = sample(y, 630, 60);
  assert.equal(lastYellow.length, 66);
  matchesNative(lastYellow[45], [-1.1643598079681396, .20392990112304688, -.13010355830192566,
    .6534518599510193, 6.48788595199585, 11.209589958190918, 1.3245729207992554, 255, 255, 255, 176]);
  assert.deepEqual(sample(y, 7, 60), firstYellow);

  const red = {...source, profile: "06", rate: 20, seed: 670425550, startColor: {
    rgb: [[0, .7264150977134705, .6489201784133911, .2912513315677643], [29141, 1, 1, 1],
      [65535, 1, .4575471878051758, .5265886187553406]],
    alpha: [[0, 1], [65535, 1]],
  }};
  assert.equal(createLeaves({...red, seed: -1}), null);
  assert.equal(createLeaves({...red, seed: undefined}), null);
  const firstRed = createLeaves(red), secondRed = createLeaves({...red, seed: 8958});
  const finaleRed = createLeaves({...red, seed: 2336});
  const warm = sample(firstRed, 0, 60);
  assert.equal(warm.length, 126);
  matchesNative(warm[0], [.5765321254730225, 3.1425230503082275, 3.474757671356201,
    .659930944442749, -.47279468178749084, 1.4611642360687256, 3.9852848052978516, 204, 190, 124, 255]);
  assert.deepEqual(sample(firstRed, 0, 30), warm);
  // The warm remainder follows the first full display update in either mode.
  const twoTicks = sample(firstRed, 2, 60), groupedTicks = sample(firstRed, 1, 30);
  assert.equal(twoTicks.length, 124);
  assert.equal(groupedTicks.length, 124);
  matchesNative(twoTicks[3], [3.8315510749816895, 3.5062804222106934, -2.5263102054595947,
    .7407283186912537, 1.2374897003173828, 4.251684188842773, 4.16989803314209, 255, 149, 163, 255]);
  matchesNative(groupedTicks[3], [3.8315510749816895, 3.5062804222106934, -2.526310443878174,
    .7407283186912537, 1.2374897003173828, 4.251684188842773, 4.16989803314209, 255, 149, 163, 255]);
  const longRed = sample(firstRed, 625, 30);
  assert.equal(longRed.length, 125);
  matchesNative(longRed[80], [4.3906660079956055, .03859996795654297, .8465116024017334,
    .7504371404647827, -7.97491455078125, -15.896864891052246, 2.595726728439331, 220, 210, 164, 42]);
  assert.deepEqual(sample(firstRed, 2, 60), twoTicks);
  assert.deepEqual(sample(firstRed, 625, 30), longRed);
  assert.deepEqual(sample(createLeaves(red), 0, 30), warm);

  const secondWarm = sample(secondRed, 0, 60), finaleEnd = sample(finaleRed, 331, 60);
  assert.equal(secondWarm.length, 129);
  matchesNative(secondWarm[0], [-6.121110916137695, 4.732097625732422, -2.984006643295288,
    .7801257967948914, -.20978125929832458, 2.689093828201294, 5.500187873840332, 255, 175, 185, 255]);
  assert.equal(finaleEnd.length, 125);
  matchesNative(finaleEnd[14], [-4.124294757843018, 2.072416067123413, -1.3240665197372437,
    .6866532564163208, 2.9302151203155518, 17.458295822143555, 21.145315170288086, 255, 143, 157, 178]);

  const redIn = createLeaves({...red, profile: "05", role: "red-in", rate: 26, seed: 1722352272,
    position: [red.position[0], 4, red.position[2]]});
  assert.deepEqual(sample(redIn, 35, 60), []);
  const entrance = sample(redIn, 36, 60);
  assert.equal(entrance.length, 30);
  matchesNative(entrance[0], [4.950591564178467, 5.402165412902832, .9676176309585571,
    .5097834467887878, 1.748797944834974e-14, 2.456627803471608e-14, .5981311798095703, 255, 143, 158, 0]);
  assert.deepEqual(sample(redIn, 18, 30), entrance);
  const continuous = sample(redIn, 39, 60);
  assert.equal(continuous.length, 31);
  matchesNative(continuous[30], [-4.0948381423950195, 5.440464496612549, 2.0229790210723877,
    .5845345258712769, .014632106758654118, .03817937895655632, .14613686501979828, 255, 144, 158, 4]);
  const transitionEnd = sample(redIn, 195, 60);
  assert.equal(transitionEnd.length, 98);
  matchesNative(transitionEnd[90], [4.49331521987915, 2.7718241214752197, -1.9583169221878052,
    .5276740193367004, .10592936724424362, -.44781625270843506, -.7526700496673584, 255, 127, 144, 123]);
  assert.deepEqual(sample(redIn, 36, 60), entrance);
}

function testAionAutumnFloor() {
  const source = {
    profile: "07", position: [0, Math.fround(.06), 0], rotation: [0, 0, 0, 1],
    alphaKeys: [[0, 0], [6554, 1], [58982, 1], [65535, 0]],
    startColor: {
      rgb: [[0, 1, .8994349241256714, .4292452931404114], [29141, 1, 1, 1],
        [65535, 1, .4575471878051758, .5265886187553406]],
      alpha: [[0, 1], [65535, 1]],
    },
  };
  const create = globalThis.MVStudioAutumnFloorSimulation.create;
  const alphaRow = {...source, role: "alpha", rate: 7, seed: 3279275062};
  const addRow = {...source, role: "add", rate: 3, seed: 363848346};
  assert.equal(create({...alphaRow, seed: addRow.seed}), null);
  assert.equal(create({...addRow, alphaKeys: {length: 4}}), null);
  const alpha = create(alphaRow), add = create(addRow);
  const sample = (stream, frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...packet) => rows.push(packet));
    return rows;
  };
  const prewarmAlpha = sample(alpha, 0, 60), prewarmAdd = sample(add, 0, 60);
  assert.equal(prewarmAlpha.length, 43);
  assert.deepEqual(prewarmAlpha[0], [6.447775840759277, .060000184923410416, 3.0984199047088623,
    .7857333421707153, 1, .34067052602767944, 1.570796251296997, 0, .6694448590278625, 255, 250, 250, 255]);
  assert.equal(prewarmAdd.length, 13);
  assert.deepEqual(prewarmAdd[0], [.1774028241634369, .060000237077474594, 4.017148971557617,
    .5201356410980225, .800000011920929, .38656529784202576, 1.570796251296997, 0, -1.8080730438232422, 255, 132, 148, 2]);
  assert.equal(sample(alpha, 1, 30)[33][8], .016444509848952293);
  assert.equal(sample(alpha, 2, 60)[33][8], .016444507986307144);
  assert.equal(sample(alpha, 599, 60).length, 32);
  const wrap = sample(alpha, 600, 60);
  assert.equal(wrap.length, 43);
  assert.deepEqual(wrap[42], [-7.01458740234375, .06000002101063728, .35168397426605225,
    .8115791082382202, 1, .49814334511756897, 1.570796251296997, 0, -7.37999528155342e-9, 255, 255, 254, 0]);
  assert.equal(sample(alpha, 601, 60)[42][12], 10);
  assert.equal(sample(add, 600, 60).length, 12);
  const last = sample(alpha, 1275, 60);
  assert.equal(last.length, 41);
  assert.deepEqual(last[18], [8.250864028930664, .06000002846121788, .5184648633003235,
    .6193529963493347, 1, .38605621457099915, 1.570796251296997, 0, -.34349626302719116, 255, 141, 156, 255]);
  assert.deepEqual(sample(alpha, 0, 30), prewarmAlpha);
  assert.deepEqual(sample(create(alphaRow), 0, 60), prewarmAlpha);
  assert.deepEqual(sample(create(addRow), 0, 30), prewarmAdd);
  assert.deepEqual(sample(alpha, 1275, 60), last);
}

function testAionLeafBursts() {
  const position = [0, Math.fround(.57), 0], rotation = [-Math.SQRT1_2, 0, 0, Math.SQRT1_2];
  const alphaKeys = [[0, 1], [58982, 1], [65535, 0]];
  const create = globalThis.MVStudioAutumnBurstSimulation.create;
  const cases = [
    {
      role: "green-burst", seed: 3279275062, rgb: [.7233373522758484, .7921568751335144, .5490196347236633],
      first: [.8436978459358215, 2.0149118900299072, 4.019004821777344, .6733894348144531,
        1.2100321633568001e-8, 2.3756719258472003e-8, .6410994529724121, 185, 202, 140, 255],
      grouped: [.8457433581352234, 2.020505905151367, 4.027272701263428],
    },
    {
      role: "yellow-burst", seed: 3364901415, rgb: [.7924528121948242, .7491843700408936, .5494837760925293],
      first: [2.771296262741089, 2.537299871444702, .20554675161838531, .7360759973526001,
        9.237621334534651e-9, 1.6175603079204848e-8, -.6389018297195435, 202, 191, 141, 255],
      grouped: [2.768643617630005, 2.550642967224121, .21512798964977264],
    },
  ];
  for (const {role, seed, rgb, first, grouped} of cases) {
    const source = {role, seed, rate: 0, position, rotation, alphaKeys, startColor: {
      rgb: [[0, ...rgb], [29141, 1, 1, 1], [65535, 1, .9386792182922363, .9645374417304993]],
      alpha: [[0, 1], [65535, 1]],
    }};
    assert.equal(create({...source, seed: 0}), null);
    const stream = create(source);
    const sample = (time, fps) => {
      const rows = [];
      stream.sample(time, fps, (...packet) => rows.push(packet));
      return rows;
    };
    assert.deepEqual(sample(0, 60), []);
    const release = sample(1 / 60, 60);
    assert.equal(release.length, 50);
    assert(release[0].slice(0, 3).every((value, axis) => Math.abs(value - first[axis]) < 2e-6));
    assert.deepEqual(release[0].slice(3), first.slice(3));
    const at30 = sample(1 / 30, 30);
    assert.equal(at30.length, 50);
    assert(at30[0].slice(0, 3).every((value, axis) => Math.abs(value - grouped[axis]) < 2e-6));
    assert.deepEqual(sample(1.6, 60), []);
    assert.deepEqual(sample(1 / 60, 60), release);
  }
}

function testAionRedBurst() {
  const f32 = Math.fround;
  const source = {
    profile: "05", role: "red-burst", seed: 1586243424, rate: 0,
    position: [f32(.512), f32(.021), f32(4.133)], rotation: [0, .983316296761958, 0, -.18190398709854855],
    alphaKeys: [[0, 0], [1311, 1], [58982, 1], [65535, 0]],
    startColor: {
      rgb: [[[0, 1, .7701709866523743, .5137255191802979], [65535, 1, 1, 1]],
        [[9445, 1, .6000000238418579, .6796650290489197], [65535, 1, 1, 1]]],
      alpha: [[[0, 1], [65535, 1]], [[0, 1], [65535, 1]]],
    },
  };
  const create = globalThis.MVStudioAutumnRedBurstSimulation.create;
  assert.equal(create({...source, role: "red-in"}), null);
  const stream = create(source);
  const sample = (frames, fps) => {
    const rows = [];
    stream.sample(frames / fps, fps, (...packet) => rows.push(packet));
    return rows;
  };
  const native = (actual, expected) => {
    assert.ok(actual.slice(0, 3).every((p, i) => Math.abs(p - expected[i]) <= 1e-6));
    assert.deepEqual(actual.slice(3), expected.slice(3));
  };
  assert.deepEqual(sample(6, 60), []);
  const beginning = sample(7, 60);
  assert.equal(beginning.length, 30);
  native(beginning[0], [.08517506718635559, .22827157378196716, 4.014399528503418,
    .284058541059494, 0, .006578462664037943, 0, 255, 193, 136, 0]);
  native(sample(8, 60)[0], [.1112821102142334, .29470095038414, 3.975200653076172,
    .284058541059494, 0, .1226159855723381, 0, 255, 193, 136, 18]);
  assert.equal(sample(13, 60).length, 130);
  assert.equal(sample(24, 60).length, 230);
  const burst = sample(36, 60);
  assert.equal(burst.length, 290);
  native(burst[230], [.036619335412979126, .625893771648407, 5.065024375915527,
    .3543529212474823, 0, .13743512332439423, 0, 255, 191, 143, 0]);
  assert.deepEqual(sample(18, 30), burst);
  const end = sample(195, 60);
  assert.equal(end.length, 290);
  native(end[50], [2.3118722438812256, 4.1183576583862305, 1.0767631530761719,
    .23893672227859497, 0, 17.30269432067871, 0, 255, 166, 161, 255]);
  assert.deepEqual(sample(7, 60), beginning);
  assert.deepEqual(sample(195, 60), end);
}

function testAionMomijiDisplayLeaves() {
  const f32 = Math.fround;
  const startColor = {
    rgb: [[482, .47213301062583923, .7924528121948242, .3850124776363373],
      [2506, .9245283007621765, .7669764757156372, .22241008281707764],
      [4530, .849056601524353, .4465811848640442, .23629406094551086],
      [8192, .9245283007621765, .008959945291280746, 0]],
    alpha: [[0, 1], [65535, 1]],
  };
  const greenRow = {role: "leaf-green", seed: 1586243424,
    position: [f32(-.11), f32(-2.05), f32(.35)], rotation: [0, 0, .1342455893754959, .9909480810165405],
    alphaKeys: [[0, 0], [2602, 1], [50501, 1], [65535, 0]], startColor};
  const redRow = {...greenRow, role: "leaf-red", position: [f32(-.11), f32(-2.05), f32(.45)], startColor: [1, 1, 1, 1]};
  const create = globalThis.MVStudioMomijiLeavesSimulation.create;
  assert.equal(create({...greenRow, seed: 0}), null);
  assert.equal(create({...redRow, startColor}), null);
  const green = create(greenRow), red = create(redRow);
  const sample = (stream, frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...packet) => rows.push(packet));
    return rows;
  };
  const native = (packet, source) => {
    assert.ok(packet.slice(0, 3).every((value, i) => Math.abs(value - source[i]) <= 5e-6));
    assert.deepEqual(packet.slice(3), source.slice(3));
  };
  assert.deepEqual(sample(green, 2, 60), []);
  const greenStart = sample(green, 3, 60);
  assert.equal(greenStart.length, 25);
  native(greenStart[0], [-2.5222363471984863, 2.7449355125427246, 1.636109203673186e-7,
    5.259414196014404, 0, .7749069929122925, -6.643908327278814e-15, 120, 202, 98, 0]);
  const groupedGreen = sample(green, 2, 30);
  assert.deepEqual(groupedGreen, sample(green, 4, 60));
  native(groupedGreen[1], [-3.4174842834472656, 1.866597294807434, -.04829944297671318,
    6.076663970947266, 0, 1.3502097129821777, -.029601503163576126, 120, 202, 98, 197]);
  const secondBurst = sample(green, 10, 60);
  assert.equal(secondBurst.length, 40);
  native(secondBurst[25], [-1.1260584592819214, 2.6193671226501465, .19077037274837494,
    5.904061794281006, 0, .3052603304386139, 6.578919453659182e-8, 202, 197, 69, 0]);
  native(sample(green, 44, 60)[0], [-2.7617220878601074, 8.411262512207031, 5.148306740920816e-7,
    .09264229238033295, 0, .7749069929122925, -1.2186986207962036, 120, 202, 98, 2]);
  assert.equal(sample(green, 64, 60).length, 1);
  assert.deepEqual(sample(green, 65, 60), []);
  assert.deepEqual(sample(green, 3, 60), greenStart);

  assert.deepEqual(sample(red, 12, 60), []);
  const redStart = sample(red, 13, 60);
  assert.equal(redStart.length, 10);
  native(redStart[0], [-2.5222363471984863, 1.3724678754806519, 8.180546728908666e-8,
    5.259414196014404, 0, .7749069929122925, -2.972434565151616e-8, 255, 255, 255, 0]);
  assert.equal(sample(red, 7, 30)[0][10], 109);
  assert.equal(sample(red, 22, 60).length, 20);
  assert.equal(sample(red, 30, 60).length, 30);
  assert.equal(sample(red, 86, 60).length, 1);
  assert.deepEqual(sample(red, 87, 60), []);
  assert.deepEqual(sample(red, 13, 60), redStart);
}

function testAionMomijiFan() {
  const create = globalThis.MVStudioMomijiFanSimulation.create;
  assert.equal(create({role: "fan", seed: 0}), null);
  const stream = create({role: "fan", seed: 1498035885});
  function sample(frame, fps = 60) {
    const packets = [];
    stream.sample(frame / fps, fps, (...packet) => packets.push(packet));
    return packets;
  }
  const first = sample(1);
  assert.deepEqual(first.map(packet => packet.slice(3, 5)), Array.from({length: 5}, () => [4, 2]));
  assert.deepEqual(first.map(packet => packet[6]), [1, 0, 0, 1, 0]);
  assert.equal(first[0][0], -1.714034080505371);
  assert.equal(first[0][5], -.20124727487564087);
  assert.equal(sample(14).length, 5);
  assert.deepEqual(sample(15).map(packet => packet[6]), [1, 0, 0, 1, 0, 1, 0, 1, 0, 0]);
  assert.deepEqual(sample(8, 30), sample(16));
  assert.equal(sample(79).length, 10);
  assert.equal(sample(80).length, 5);
  assert.deepEqual(sample(94), []);
  assert.deepEqual(sample(1), first);
}

function testAionAirConfetti() {
  const row = {
    role: "air", seed: 1425677110, rate: 70, position: [0, 15, 0], rotation: [0, 0, 0, 1],
    startColors: [[1, .7585158348083496, .34433960914611816, 1], [1, .8903166651725769, .43867921829223633, 1]],
    alphaKeys: [[0, 0], [6554, 1], [62258, 1], [65535, 0]],
  };
  const create = globalThis.MVStudioConfettiAirSimulation.create;
  assert.equal(create({...row, seed: 8392}), null);
  const stream = create(row);
  const sample = (frame, fps) => {
    const rows = [];
    stream.sample(frame / fps, fps, (...packet) => rows.push(packet));
    return rows;
  };
  const native = (packet, source) => {
    assert.ok(packet.slice(0, 3).every((value, i) => Math.abs(value - source[i]) <= 4e-6));
    assert.deepEqual(packet.slice(3), source.slice(3));
  };
  const warmed = sample(0, 60);
  assert.equal(warmed.length, 574);
  native(warmed[0], [11.995593070983887, -4.8703932762146, .3671360909938812, .6030478477478027,
    -4.634464263916016, -1.0106258392333984, 77.15988159179688, 255, 201, 93, 120]);
  const first = sample(1, 60);
  assert.equal(first.length, 574);
  native(first[0], [11.99647045135498, -4.886133193969727, .3810846209526062, .5480924248695374,
    -4.634464263916016, -1.0106258392333984, 77.31837463378906, 255, 201, 93, 109]);
  // 30 Hz consumes the warm fraction after its second ordinary step.
  assert.equal(sample(1, 30).length, 573);
  assert.equal(sample(1, 30)[200][6], 32.062110900878906);
  assert.equal(sample(2, 60)[200][6], 32.06211471557617);
  const finale = sample(1581, 60);
  assert.equal(finale.length, 574);
  native(finale[185], [.19686438143253326, -13.3834810256958, 2.1080939769744873, 1.0108728408813477,
    .5450973510742188, .9530658721923828, 55.910926818847656, 255, 204, 96, 255]);
  assert.deepEqual(sample(0, 30), warmed);
  assert.deepEqual(sample(1, 60), first);
  assert.deepEqual(sample(1581, 60), finale);
}

testAionRain();
testAionRainFloor();
testAionAutumnLeaves();
testAionAutumnFloor();
testAionRedBurst();
testAionLeafBursts();
testAionAirConfetti();
testAionMomijiDisplayLeaves();
testAionMomijiFan();
test().then(testFinaleFlash).catch(error => {console.error(error); process.exitCode = 1;});
