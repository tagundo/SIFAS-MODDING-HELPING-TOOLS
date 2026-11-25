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
  // The director pinned at the song end: every frame between two records shows that time.
  const end = capture.gameFrameTimes({ records: [clocked(196, 19.4, 0.2), clocked(199, 20, 0.2), clocked(200, 20, 1 / 3),
    clocked(204, 20, 0.12)] });
  assert.deepEqual(end.map((value) => Math.round(value * 1e9) / 1e9), [19.4, 19.6, 19.8, 20, 20, 20, 20, 20, 20]);
  // A director that goes back leaves the frames between those records unknown; the map keeps both
  // records (as mv_frame_compare.py game_frame_times does), the ascending preroll grid leaves out the
  // rewound record and the frames after it until the director passes the listed time again.
  assert.deepEqual(capture.gameFrameTimes({ records: [clocked(300, 30, 0.2), clocked(302, 29, 0.2)] }), [30]);
  const rewound = { records: [clocked(300, 30, 0.2), clocked(302, 29, 0.2), clocked(304, 29.5, 0.2), clocked(306, 31, 0.2)] };
  assert.deepEqual([...capture.gameFrames(rewound)].map(([frame, time]) => [frame, Math.round(time * 1e9) / 1e9]),
    [[300, 30], [302, 29], [303, 29.3], [304, 29.5], [305, 30.8], [306, 31]]);
  const times = capture.gameFrameTimes(rewound);
  assert.deepEqual(times.map((value) => Math.round(value * 1e9) / 1e9), [30, 30.8, 31]);
  assert(times.every((value, index) => index === 0 || value >= times[index - 1]), 'the preroll grid never goes back');
  // Pinned records that differ by rounding still hold the listed time.
  const pinned = capture.gameFrameTimes({ records: [clocked(10, 5 + 5e-10, 0.2), clocked(12, 5, 0.2)] });
  assert.deepEqual(pinned, [5 + 5e-10, 5 + 5e-10, 5 + 5e-10]);

  // The director follows the millisecond music clock, so t - deltaTime misses the previous frame
  // (12035 Max 3D: frame 9847 at 100.554 s, deltaTime 0.219193786, frame 9846 recorded at 100.335 s).
  const at = (id, frameCount, directorTime, deltaTime, extra = {}) => ({ id, kind: 'frame', ...extra,
    clock: { frameCount, directorTime, deltaTime } });
  const neighbours = { records: [at('f0163', 9846, 100.335, 0.2), at('f0164', 9847, 100.554, 0.219193786),
    at('p4-full', 9848, 100.78, 0.226, { kind: 'full', part: 'quality' }), at('f0200', 9900, 104, 0.3),
    at('f0201', 9901, 104.9, 1 / 3), at('f0202', 9903, 105.5, 0.2), at('f0203', 9902, 105.3, 0.2)] };
  assert.deepEqual([...capture.recordedFrameTimes(neighbours)].slice(0, 3), [[9846, 100.335], [9847, 100.554], [9848, 100.78]]);
  const planned = new Map(capture.planRequests(neighbours, [-1, 0, 1]).map((request) => [request.id, request]));
  const phase = (id) => [planned.get(id).t, planned.get(id).phaseSource];
  assert.deepEqual(phase('f0164@-1'), [100.335, 'recorded']);
  assert.deepEqual(phase('f0164@0'), [100.554, 'record']);
  assert.deepEqual(phase('f0164@1'), [100.78, 'recorded']);
  assert.equal(planned.get('f0163@-1').phaseSource, 'deltaTime', 'no record of frame 9845');
  // A clamped deltaTime (1/3 s) hides the real interval: the recorded previous frame is used at any distance.
  assert.deepEqual(phase('f0201@-1'), [104, 'recorded']);
  assert.deepEqual(phase('f0202@-1'), [105.3, 'recorded']);
  assert.deepEqual(phase('f0203@1'), [105.5, 'recorded']);
  // A recorded neighbour is the time of the evaluation that frame ran, however far it lies from
  // t +/- deltaTime: a jittered next frame (12035 dump4 f0070: 35.675 s, deltaTime 0.125641406, frame
  // +1 at 35.885 s), a director pinned at the song end (106.666 s in both frames) or a director that
  // went back.
  const jitter = capture.planRequests({ records: [at('f0070', 7000, 35.675, 0.125641406), at('f0071', 7001, 35.885, 0.21)] }, [1])[0];
  assert.deepEqual([jitter.t, jitter.phaseSource], [35.885, 'recorded']);
  const songEnd = new Map(capture.planRequests({ records: [at('f0170', 9000, 106.666, 0.155343145), at('f0171', 9001, 106.666, 0.314309984)] },
    [-1, 1]).map((request) => [request.id, request]));
  assert.deepEqual([songEnd.get('f0171@-1').t, songEnd.get('f0171@-1').phaseSource], [106.666, 'recorded']);
  assert.deepEqual([songEnd.get('f0170@1').t, songEnd.get('f0170@1').phaseSource], [106.666, 'recorded']);
  const sparse = new Map(capture.planRequests({ records: [at('a', 10, 0.5, 1 / 15), at('b', 11, 1, 1 / 15), at('c', 13, 2, 1 / 15)] }, [-1])
    .map((request) => [request.id, request]));
  assert.deepEqual([sparse.get('b@-1').phaseSource, sparse.get('b@-1').t], ['recorded', 0.5]);
  assert.deepEqual([sparse.get('c@-1').phaseSource, sparse.get('c@-1').t], ['deltaTime', 1.933],
    'the director follows the millisecond music clock: the estimate is rounded to it');
  // 12035 Max 3D f0089: frame 9614 at 46.934 s, deltaTime 0.186060965, no record of frame 9613: the
  // previous frame is estimated at 46.748 s (the camera fov there matches the game to 1e-4 degrees).
  const estimated = capture.planRequests({ records: [at('f0089', 9614, 46.934, 0.186060965)] }, [-1])[0];
  assert.deepEqual([estimated.t, estimated.phaseSource], [46.748, 'deltaTime']);
  const fractional = capture.planRequests({ records: [at('x', 5, 1.0005, 0.2)] }, [-1])[0];
  assert(Math.abs(fractional.t - 0.8005) < 1e-12, 'a dump whose times are not whole milliseconds keeps the estimate');
  const flipped = new Map(capture.planRequests({ records: [at('a', 10, 2, 0.2), at('b', 11, 1.9, 0.2)] }, [-1, 1])
    .map((request) => [request.id, request]));
  assert.deepEqual([flipped.get('b@-1').t, flipped.get('b@-1').phaseSource], [2, 'recorded'], 'the evaluation before a rewind');
  assert.deepEqual([flipped.get('a@1').t, flipped.get('a@1').phaseSource], [1.9, 'recorded']);

  // Members and springs records are read after the next frame's pre-timeline spring step
  // (PHYSICS_READ_POINT); --physics-read-point none leaves it out. Pure parts never take it.
  const parts = { records: [at('m', 20, 3, 0.2, { kind: 'full', part: 'members' }), at('s', 21, 3.2, 0.2, { kind: 'full', part: 'springs' }),
    at('r', 21, 3.2, 0.2, { kind: 'full', part: 'renderers' }), at('f', 21, 3.2, 0.2)] };
  const readPoints = (options) => Object.fromEntries(capture.planRequests(parts, [-1], options)
    .map((request) => [request.id, [request.physics, request.readPoint]]));
  assert.deepEqual(readPoints(), { 'm@-1': [true, true], 's@-1': [true, true], 'r@-1': [false, false], 'f@-1': [false, false] });
  assert.deepEqual(readPoints({ readPoint: 'none' }), { 'm@-1': [true, false], 's@-1': [true, false], 'r@-1': [false, false], 'f@-1': [false, false] });
  assert.throws(() => capture.planRequests(parts, [-1], { readPoint: 'late' }), /physics-read-point/);
  assert.deepEqual(capture.PHYSICS_READ_POINTS, ['update', 'none']);
  const springRecord = capture.editorRecord(capture.planRequests(parts, [-1]).find((request) => request.id === 's@-1'),
    { values: { clock: { directorTime: 3 } }, seekMs: 1, dumpMs: 1, steps: 4, prerollStart: 2.2, prerollSource: 'game-frames', readPointStep: 33.3 }, 30);
  assert.deepEqual([springRecord.clock.directorTime, springRecord.clock.phaseSource, springRecord.clock.readPointStep], [3, 'recorded', 33.3]);
  const record = capture.editorRecord(planned.get('f0164@-1'), { values: { clock: { directorTime: 100.335 } }, seekMs: 1, dumpMs: 1 }, 30);
  assert.deepEqual([record.clock.phaseSource, Math.round(record.clock.phaseSeconds * 1e9) / 1e9], ['recorded', -0.219]);

  // --frame-history: the seeks hand the editor the game's rendered frame times
  // (the cheek floats MemberCheekMixer keeps after a clip follow them).
  {
    const seeks = [];
    globalThis.mvFrameProbe = { scene: { seek: (...args) => seeks.push(args), assetDump: () => ({}),
      inspect: () => ({ time: -1 }), setPlaying() {}, playbackFrame() {} } };
    const fake = { evaluate: async (fn, arg) => fn(arg) };
    try {
      await capture.setFrameHistory(fake, [1, 2.5]);
      await capture.evaluatePure(fake, [{ id: 'a', t: 3, sections: ['materials'] }], null);
      await capture.evaluatePhysics(fake, { id: 'b', t: 3, sections: ['members'] }, 0, 30, null, null, 30);
      assert.deepEqual(seeks.map((args) => [args[0], args[3]]), [[3, [1, 2.5]], [3, [1, 2.5]]]);
      await capture.setFrameHistory(fake, null);
      await capture.evaluatePure(fake, [{ id: 'c', t: 4, sections: ['materials'] }], null);
      assert.equal(seeks.at(-1)[3], null, '--frame-history none: plain seeks');
    } finally {
      delete globalThis.mvFrameProbe;
    }
  }

  // Sampler 3 frame clocks (trailer.frameClocks, clock.prevFrame / nextFrame): every rendered
  // frame's own director time. Records of those frames still come first ("recorded"); a frame
  // only the frame clock read is "frameClock"; without either the deltaTime rule stays.
  {
    const fields = capture.FRAME_CLOCK_FIELDS;
    assert.deepEqual(fields, ['frameCount', 'directorTime', 'musicTime', 'unityTime', 'deltaTime', 'realtimeSinceStartup', 'source']);
    const row = (frameCount, directorTime, unityTime, deltaTime, extra = {}) => fields.map((name) => (
      { frameCount, directorTime, musicTime: directorTime === null ? extra.musicTime : Math.round(directorTime * 1000), unityTime, deltaTime,
        realtimeSinceStartup: 1000 + frameCount, source: extra.source ?? 0 })[name] ?? null);
    const doc = { records: [
      { id: 'f0001', kind: 'frame', directors: [{ main: true, duration: 106.683333 }],
        clock: { frameCount: 500, directorTime: 50.1, deltaTime: 1 / 3, unityTime: 990.1,
          prevFrame: { frameCount: 499, directorTime: 49.62, musicTime: 49620, unityTime: 989.767, deltaTime: 1 / 3 } } },
      { id: 'p1-members-00', kind: 'full', part: 'members', clock: { frameCount: 503, directorTime: 50.9, deltaTime: 0.2, unityTime: 990.6 } }],
      trailer: { frameClocks: { schema: 'sifas-mv-frame-clock/1', fields, rows: [row(498, 49.2, 989.434, 0.25), row(500, 50.1, 990.1, 1 / 3, { source: 1 }),
        row(501, null, 990.3, 0.2, { musicTime: 50300 }), row(502, 50.6, 990.4, 0.1), row(503, 50.9, 990.6, 0.2, { source: 1 }),
        row(504, 51.12, 990.82, 0.22)] } } };
    const clocks = capture.frameClocks(doc);
    assert.deepEqual([...clocks.keys()], [498, 499, 500, 501, 502, 503, 504], 'rows plus the prevFrame a record carries');
    assert.deepEqual([clocks.get(501).directorTime, clocks.get(501).directorFrom], [50.3, 'musicTime'],
      'no director read: SyncMusicPlayingTime sets it from the music time');
    const planned = new Map(capture.planRequests(doc, [-1, 0, 1]).map((request) => [request.id, [request.t, request.phaseSource]]));
    assert.deepEqual(planned.get('f0001@-1'), [49.62, 'frameClock'], 'clamped deltaTime: the previous frame was read');
    assert.deepEqual(planned.get('f0001@1'), [50.3, 'frameClock']);
    assert.deepEqual(planned.get('p1-members-00@-1'), [50.6, 'frameClock']);
    assert.deepEqual(planned.get('p1-members-00@1'), [51.12, 'frameClock']);
    // A record of the neighbouring frame stays the source it was.
    const both = { records: [...doc.records, { id: 'f0002', kind: 'frame', clock: { frameCount: 501, directorTime: 50.3, deltaTime: 0.2 } }],
      trailer: doc.trailer };
    assert.deepEqual(new Map(capture.planRequests(both, [1]).map((request) => [request.id, request.phaseSource])).get('f0001@1'), 'recorded');
    // Every frame read is an anchor of the game frame grid: nothing is spread between records.
    assert.deepEqual([...capture.gameFrames(doc)], [[498, 49.2], [499, 49.62], [500, 50.1], [501, 50.3], [502, 50.6], [503, 50.9], [504, 51.12]]);
    // Older dumps (no frame clock): the same requests and grid as before.
    const older = { records: doc.records.map((record) => ({ ...record, clock: { ...record.clock, prevFrame: undefined } })) };
    assert.equal(capture.frameClocks(older).size, 0);
    assert.deepEqual(capture.planRequests(older, [-1]).map((request) => request.phaseSource), ['deltaTime', 'deltaTime']);
    // The rows travel in rtdump-core only: merging keeps them whatever the blob order.
    const core = { schema: capture.SCHEMA, side: 'game', header: {}, records: [doc.records[0]], trailer: { stopReason: 'mv-ended', ...doc.trailer } };
    const fullBlob = { schema: capture.SCHEMA, side: 'game', header: {}, records: [doc.records[1]],
      trailer: { stopReason: 'mv-ended', frameClocks: { in: 'rtdump-core', frames: 6 } } };
    for (const order of [[core, fullBlob], [fullBlob, core]]) assert.equal(capture.mergeDumps(order).trailer.frameClocks.rows.length, 6);

    // The particle clock: [directorTime, Time.time] of every frame read; records fill frames the frame
    // clock missed; pre-start and non-advancing frames are left out. 12035 dump4 ran Time.time 0.87 s
    // behind the director between 47.1 and 96.7 s (Time.maximumDeltaTime clamps).
    const game = capture.gameClockSamples(doc);
    assert.equal(game.source, 'frameClock');
    assert.deepEqual(game.samples.map(([t, u]) => [t, Math.round(u * 1e3) / 1e3]),
      [[49.2, 989.434], [49.62, 989.767], [50.1, 990.1], [50.3, 990.3], [50.6, 990.4], [50.9, 990.6], [51.12, 990.82]]);
    assert.ok(Math.abs(game.lagMax - ((50.9 - 49.2) - (990.6 - 989.434))) < 1e-9, `lagMax ${game.lagMax}`);
    const fromRecords = capture.gameClockSamples({ records: [
      { clock: { frameCount: 1, directorTime: 0, unityTime: 900 } }, { clock: { frameCount: 2, directorTime: 1, unityTime: 901 } },
      { clock: { frameCount: 3, directorTime: 106.666, unityTime: 1005 } }, { clock: { frameCount: 4, directorTime: 106.666, unityTime: 1005.2 } }] });
    assert.deepEqual([fromRecords.source, fromRecords.samples], ['records', [[1, 901], [106.666, 1005]]]);
    assert.deepEqual(capture.gameClockSamples({ records: [] }), { source: 'records', samples: [], lagMax: null, frames: null });
    // The run's own device frames (MVStudioParticleSystems.frameGrid): every frame from the first row to the
    // last one with its director time and Time.deltaTime, when the frame clock holds them all.
    assert.deepEqual(capture.deviceFrames(doc), [[49.2, 0.25, 498], [49.62, 1 / 3, 499], [50.1, 1 / 3, 500], [50.3, 0.2, 501],
      [50.6, 0.1, 502], [50.9, 0.2, 503], [51.12, 0.22, 504]]);
    assert.deepEqual(game.frames, capture.deviceFrames(doc));
    const gap = { records: [doc.records[1]], trailer: { frameClocks: { ...doc.trailer.frameClocks,
      rows: doc.trailer.frameClocks.rows.filter((entry) => entry[0] !== 500) } } };
    assert.equal(capture.deviceFrames(gap), null, 'a frame the clock missed: no device frames');
    assert.equal(capture.deviceFrames(older), null, 'no frame clock rows');
    const back = { records: [], trailer: { frameClocks: { ...doc.trailer.frameClocks,
      rows: [row(1, 2, 900, .2), row(2, 1.9, 900.2, .2)] } } };
    assert.equal(capture.deviceFrames(back), null, 'a director going back');
    // Each request names the game frame it shows (scene.setGameFrame) where it is known.
    const frames = new Map(capture.planRequests(doc, [-1, 0, 1]).map((request) => [request.id, request.frame]));
    assert.deepEqual([frames.get('f0001@-1'), frames.get('f0001@0'), frames.get('f0001@1')], [499, 500, 501]);
    assert.deepEqual(capture.planRequests(older, [-1]).map((request) => request.frame), [null, null], 'deltaTime estimates name no frame');

    // The capture hands the samples to the scene (MVStudioScene.setGameClock); null keeps the director's clock.
    const calls = [];
    let held = 0;
    globalThis.mvFrameProbe = { scene: { setGameClock: (...args) => { calls.push(args); held = args[1] ? args[1].length : 0;
      return args[0] ? args[0].length : 0; }, gameFrames: () => held } };
    const fake = { evaluate: async (fn, arg) => fn(arg) };
    try {
      assert.equal(await capture.setGameClock(fake, game.samples), 7);
      assert.equal(await capture.setGameClock(fake, null), 0);
      assert.equal(await capture.setGameClock(fake, game.samples, game.frames), 7);
      assert.equal(await capture.gameFrameCount(fake), 7);
      assert.deepEqual(calls, [[game.samples], [null], [game.samples, game.frames]]);
      globalThis.mvFrameProbe = { scene: { setGameClock: () => 0 } };
      await assert.rejects(capture.setGameClock(fake, game.samples, game.frames), /gameFrames/);
      globalThis.mvFrameProbe = { scene: {} };
      await assert.rejects(capture.setGameClock(fake, game.samples), /setGameClock/);
    } finally {
      delete globalThis.mvFrameProbe;
    }
  }

  console.log('MV_RUNTIME_CAPTURE_PASS viewport, stage-scene selector and pinned suits');
})().catch((error) => { console.error(error); process.exitCode = 1; });
