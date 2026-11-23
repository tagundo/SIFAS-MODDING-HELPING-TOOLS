/* Browser-free checks of tests/mv_runtime_capture.js against shapes of the real
   12035 runtime dump (CI run 2). Run: node tests/mv_runtime_capture_test.js */
'use strict';
const assert = require('node:assert/strict');
const capture = require('./mv_runtime_capture');

const frame = (extra) => ({ kind: 'frame', id: 'f0001', clock: { directorTime: 1, deltaTime: 1 / 60 }, ...extra });
const mainCamera = (fields) => ({ key: 'camera:main', ...fields });

(async () => {
  // RenderingResolution 640 on a 1280x720 screen: the main camera draws 1138x640 (aspect 1.778125),
  // which no width at the screen height reproduces. The camera's own pixel size is pinned.
  const real = { header: { screen: { width: 1280, height: 720 } },
    records: [frame({ cameras: [mainCamera({ aspect: 1.778125, pixelWidth: 1138, pixelHeight: 640, targetTexture: null })] })] };
  const viewport = capture.viewportFor(real);
  assert.deepEqual([viewport.width, viewport.height, viewport.gameAspect], [1138, 640, 1.778125]);
  assert.match(viewport.notes.join(' '), /1138x640/);
  // A camera drawing the whole screen keeps the screen size.
  const full = { header: { screen: { width: 1280, height: 720 } },
    records: [frame({ cameras: [mainCamera({ aspect: 1280 / 720, pixelWidth: 1280, pixelHeight: 720 })] })] };
  assert.deepEqual([capture.viewportFor(full).width, capture.viewportFor(full).height, capture.viewportFor(full).notes], [1280, 720, []]);
  // Without pixel sizes the aspect fallback still applies; a pixel size that contradicts the aspect is ignored.
  const aspectOnly = { header: { screen: { width: 1280, height: 720 } }, records: [frame({ cameras: [mainCamera({ aspect: 2 })] })] };
  assert.deepEqual([capture.viewportFor(aspectOnly).width, capture.viewportFor(aspectOnly).height], [1440, 720]);
  const contradictory = { header: { screen: { width: 1280, height: 720 } },
    records: [frame({ cameras: [mainCamera({ aspect: 2, pixelWidth: 1138, pixelHeight: 640 })] })] };
  assert.deepEqual([capture.viewportFor(contradictory).width, capture.viewportFor(contradictory).height], [1440, 720]);

  // The additively loaded stage scene (bg0006_01_s1) has roots outside /EntryPoint.
  assert.deepEqual(capture.rendererSelector({ key: 'renderer:/Model/ground', scope: 'other', mesh: 'ground', path: '/Model/ground' }),
    { key: 'renderer:/Model/ground', scope: 'stage', mesh: 'ground', path: 'ground' });
  const effect = { key: 'renderer:/EntryPoint/Live/Stages/MainStage/Effect/a', scope: 'effect', mesh: 'a',
    path: '/EntryPoint/Live/Stages/MainStage/Effect/a' };
  assert.deepEqual(capture.rendererSelector(effect), effect);
  assert.deepEqual(capture.rendererSelector({ key: 'k', scope: 'other', path: '/Model' }), { key: 'k', scope: 'other', mesh: null, path: '/Model' });

  // --suits dump: the suit each slot wore (12035: ch0212 suit 102111001, the mapping says 102112001).
  const worn = (suitId, memberId = 211) => frame({ members: [{ slot: 1, formationPosition: 1, memberId, suitId, active: true }] });
  const dump = { records: [worn(102111001), worn(102111001), { kind: 'full', part: 'members', members: [{ slot: 1 }] }] };
  assert.deepEqual(capture.suitPlan('dump', dump), { source: 'dump', costumes: { 1: 102111001 }, members: { 1: 211 } });
  assert.equal(capture.suitPlan(undefined, dump), null);
  assert.deepEqual(capture.suitPlan('2:102112001, 01:102111001', dump),
    { source: 'option', costumes: { 1: 102111001, 2: 102112001 }, members: {} });
  for (const bad of ['', '1', '1:x', '0:5', '65:5', '1:5,1:6', '1:0']) assert.throws(() => capture.suitPlan(bad, dump), /--suits/, bad);
  assert.throws(() => capture.suitPlan('dump', { records: [worn(102111001), worn(102112001)] }), /changes the member or suit of slot 1/);
  assert.throws(() => capture.suitPlan('dump', { records: [worn(102111001), worn(102111001, 212)] }), /slot 1/);
  assert.throws(() => capture.suitPlan('dump', { records: [frame({})] }), /records no member suits/);

  const plan = capture.suitPlan('dump', dump);
  assert.deepEqual(capture.checkCostumes(plan, [{ position: 1, memberId: 211, costumeId: 102111001, label: 'x' }]),
    [{ position: 1, memberId: 211, costumeId: 102111001 }]);
  assert.throws(() => capture.checkCostumes(plan, [{ position: 1, memberId: 211, costumeId: 102112001 }]), /wears 102112001, not 102111001/);
  assert.throws(() => capture.checkCostumes(plan, [{ position: 1, memberId: 212, costumeId: 102111001 }]), /the game had 211/);
  assert.throws(() => capture.checkCostumes(plan, []), /position 1 has no performer/);
  // A pinned suit whose pack is not local leaves the member without a model: never capture that silently.
  assert.throws(() => capture.checkCostumes(plan, [{ position: 1, memberId: 211, costumeId: 102111001, loaded: false }]),
    /no model for suit 102111001.*"download": true/);
  assert.deepEqual(capture.checkCostumes(plan, [{ position: 1, memberId: 211, costumeId: 102111001, loaded: true }]),
    [{ position: 1, memberId: 211, costumeId: 102111001, loaded: true }]);

  // The import request (game and game-stream) carries the pinned costumes; nothing else is touched.
  const routes = [];
  const page = { route: async (pattern, handler) => routes.push([pattern, handler]),
    unroute: async (pattern, handler) => routes.splice(routes.findIndex((item) => item[0] === pattern && item[1] === handler), 1) };
  const unpin = await capture.pinCostumes(page, plan);
  const [[pattern, handler]] = routes;
  for (const url of ['http://x/api/mv-studio/game-stream?lang=en', 'http://x/api/mv-studio/game?lang=en']) assert.match(url, pattern);
  for (const url of ['http://x/api/mv-studio/games', 'http://x/api/mv-studio/catalog?region=gl']) assert.doesNotMatch(url, pattern);
  const sent = [];
  const route = (method, body) => ({ request: () => ({ method: () => method, postData: () => body }),
    continue: async (options) => sent.push(options ?? null) });
  await handler(route('POST', JSON.stringify({ region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503, download: false })));
  await handler(route('GET', null));
  assert.deepEqual(sent, [{ postData: JSON.stringify({ region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503, download: false,
    costumes: { 1: 102111001 } }) }, null]);
  await unpin();
  assert.equal(routes.length, 0);

  // Runtime member meshes select the editor's source meshes (CombineFace -> Face, <suit>_head/body_BoneN -> Hair/Body).
  const head = '/EntryPoint/Live/Members/Member1/Model/Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/Neck/Head/Head_All';
  assert.equal(capture.rendererSelector({ key: 'f', scope: 'member1', mesh: 'CombineFace', path: head + '/mesh_face/CombineFace' }).mesh, 'Face');
  assert.equal(capture.rendererSelector({ key: 'h', scope: 'member1', mesh: 'x', path: head + '/mesh_hair/Hair/ch0212_co0002_head_Bone2' }).mesh, 'Hair');
  assert.equal(capture.memberMeshAlias({ scope: 'effect', path: head + '/mesh_face/CombineFace' }), null);

  // The spring preroll steps on the game's own frame times: a record is a frame, the frame
  // before it is at t - deltaTime unless deltaTime was clamped (1/3 s), the rest is spread evenly.
  const clocked = (frameCount, directorTime, deltaTime) => ({ kind: 'frame', clock: { frameCount, directorTime, deltaTime } });
  const grid = capture.gameFrameTimes({ records: [clocked(100, 10, 0.2), clocked(104, 11, 0.3), clocked(106, 11.6, 1 / 3),
    { kind: 'full', part: 'springs', clock: { frameCount: 104, directorTime: 11, deltaTime: 0.3 } }, clocked(90, 0, 0.1)] });
  const rounded = grid.map((value) => Math.round(value * 1e9) / 1e9);
  assert.deepEqual(rounded, [10, 10.233333333, 10.466666667, 10.7, 11, 11.3, 11.6]);
  const before = capture.prerollTimes(11.3, 1, 5, grid);
  assert.deepEqual([before.source, before.times.map((value) => Math.round(value * 1e9) / 1e9)],
    ['game-frames', [10.466666667, 10.7, 11]]);
  // Outside the recorded frames the fixed-rate grid ending exactly at t is kept.
  const fixed = capture.prerollTimes(3, 1, 4, grid);
  assert.deepEqual([fixed.source, fixed.times], ['fixed-rate', [2, 2.25, 2.5, 2.75]]);
  assert.deepEqual(capture.prerollTimes(0.1, 1, 4).times, []);

  console.log('MV_RUNTIME_CAPTURE_PASS viewport, stage-scene selector and pinned suits');
})().catch((error) => { console.error(error); process.exitCode = 1; });
