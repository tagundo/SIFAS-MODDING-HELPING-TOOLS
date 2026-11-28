/* Runtime value capture against the real editor UI and scene, with a synthetic game catalog.

   A fake game dump (3 frame records and 2 full parts) is evaluated through the
   same functions the CLI runner uses. Checks that the game's quality is applied
   (and that an unusable one marks the capture invalid:quality), one editor record per game record
   and phase with matching ids and times, the live camera values in editor
   space (degrees, column-major), that the document is accepted by
   the comparator, and that the comparator reports zero error for the
   editor-vs-editor join and for the mirrored game document.
*/
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const capture = require('./mv_frame_capture');
const runtime = require('./mv_runtime_capture');

const media = (ext) => '/api/mv-studio/media/' + 'b'.repeat(32) + ext;
const quality = (height) => ({ rendering_resolution: height, frame_rate_60fps: false, posteffect: false });
const binding = '/EntryPoint/Live/Cameras/MainCamera';
const DT = 1 / 15;

function project() {
  return {
    version: 1, name: 'Runtime fixture', token: 'e'.repeat(32), duration: 4,
    stage: { glb: media('.glb'), label: 'Fixture stage' },
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34,
      deck: { deckType: 2, userId: null, saved: false }, suits: [] },
    tracks: [{ id: 'cam', kind: 'camera', label: 'Camera/MainCamera', nativeClass: 'AnimationTrack', binding,
      events: [{ id: 'cam:0', start: 0, duration: 4, label: 'Shot', values: { keyframes: [
        { time: 0, position: [0, 1.0, 3.0], rotation: [0, 0, 0, 1], fov: 30 },
        { time: 4, position: [4.0, 1.6, 2.0], rotation: [0, 0.25881905, 0, 0.96592583], fov: 50 },
      ] } }] }],
    assets: [], performers: [], warnings: [],
    quality: { mode: 30, values: quality(180), modes: [{ id: 30, label: 'Normal 3D', values: quality(180) }],
      options: [{ key: 'rendering_resolution', label: 'Render resolution', type: 'number' },
        { key: 'frame_rate_60fps', label: '60 fps', type: 'boolean' }, { key: 'posteffect', label: 'Post-processing effects', type: 'boolean' }] },
  };
}

function gameDump() {
  const record = (id, kind, seq, t, extra) => ({ id, kind, seq, clock: { directorTime: t, deltaTime: DT, frameCount: 100 + seq },
    clockEnd: { directorTime: t, frameCount: 100 + seq }, nonFinite: [], ...extra });
  return { schema: runtime.SCHEMA, side: 'game',
    header: { conventions: { space: 'unity-lh', matrixLayout: 'column-major', angles: 'degrees', quaternion: 'xyzw', color: 'raw',
      time: 'director-seconds' }, screen: { width: 320, height: 180 }, producer: { name: 'fake' },
      quality: { values: { RenderingResolution: 180, PostEffect: false, MovieLive: false } } },
    records: [record('f0001', 'frame', 1, 0.5), record('f0002', 'frame', 2, 1.0), record('f0003', 'frame', 3, 2.5),
      record('p0-renderers-00', 'full', 4, 1.0, { pass: 0, part: 'renderers', chunk: 0 }),
      record('p0-members-00', 'full', 5, 1.0, { pass: 0, part: 'members', chunk: 0 })],
    trailer: { stopReason: 'synthetic' } };
}

async function run() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-runtime-capture-'));
  const library = path.join(work, 'library');
  fs.mkdirSync(library);
  const game = gameDump();
  const gameFile = path.join(work, 'game.json.gz');
  fs.writeFileSync(gameFile, zlib.gzipSync(JSON.stringify(game)));
  const read = runtime.readDump(gameFile);
  assert.deepEqual(read.doc.records.map((item) => item.id), game.records.map((item) => item.id), 'gzip dump round trip');
  const plan = runtime.planRequests(read.doc, [-1, 0, 1]);
  assert.equal(plan.length, 15);
  assert.equal(plan.filter((request) => request.physics).length, 3, 'members are prerolled with physics');
  const server = await capture.bootEditor(path.resolve(__dirname, '..'), library, path.join(work, 'server.log'));
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true, args: capture.browserArgs(true) });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(capture.attachSceneProbe);
    await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: {
      region: 'gl', platform: 'android', regions: [{ id: 'gl', label: 'GL' }],
      platforms: [{ id: 'android', label: 'Android' }, { id: 'ios', label: 'iOS' }],
      songs: [{ id: 12, title: 'Fixture song', variants: [{ id: 34, label: 'MV' }] }],
    } }));
    await page.route('**/api/mv-studio/game-stream?*', (route) => {
      const value = project();
      const preview = { stage: value.stage, assets: [], tracks: [], quality: value.quality, duration: value.duration, source: value.source };
      return route.fulfill({ contentType: 'application/x-ndjson; charset=utf-8',
        body: JSON.stringify({ type: 'stage', preview }) + '\n' + JSON.stringify({ type: 'complete', project: value }) + '\n' });
    });
    await page.route('**/api/mv-studio/media/*.glb', (route) => route.fulfill({ contentType: 'model/gltf-binary', body: fixture().glb }));
    await page.goto(server.url + '/#mv');
    const source = { region: 'gl', platform: 'android', liveId: 12, assetId: 34 };
    await capture.importOriginal(page, source, false);
    // Contract 5: the editor runs at the game's quality; one it cannot apply falls back and is invalid.
    const refused = await runtime.applyGameQuality(page, { values: { Quality: 99, PostEffect: false } }, { mode: 30 });
    assert.equal(refused.status, 'invalid:quality');
    assert(refused.reasons.some((reason) => reason.includes('could not be applied')), JSON.stringify(refused.reasons));
    const applied = await runtime.applyGameQuality(page, read.doc.header.quality, { mode: 30 });
    assert.equal(applied.status, 'matched', JSON.stringify(applied.reasons));
    assert.equal(applied.source, 'game');
    assert.deepEqual(applied.request, { mode: 30, overrides: { rendering_resolution: 180, posteffect: false } });
    assert.deepEqual(applied.gameOnly, ['MovieLive']);
    const viewport = runtime.viewportFor(read.doc);
    assert.deepEqual([viewport.width, viewport.height], [320, 180]);
    const pinned = await runtime.prepareLiveView(page, viewport);
    assert.equal(pinned.cameraMode, 'live');
    const { records, timing } = await runtime.capturePage(page, read.doc, { phases: [-1, 0, 1], preroll: 0.5, rate: 30, batchSize: 4 });
    assert.equal(records.length, 15, 'one editor record per game record and phase');
    assert.deepEqual(records.map((item) => item.id).sort(), plan.map((item) => item.id).sort());
    for (const item of records) {
      const [sourceId, phase] = item.id.split('@');
      assert.equal(item.sourceRecord, sourceId);
      assert.equal(item.phase, Number(phase));
      const source = game.records.find((entry) => entry.id === sourceId);
      // A recorded neighbour frame gives its own director time; otherwise the estimate is on the
      // millisecond clock (whole-millisecond director times).
      const neighbour = item.phase ? game.records.find((entry) => entry.clock.frameCount === source.clock.frameCount + item.phase) : null;
      const estimate = Math.round((source.clock.directorTime + item.phase * DT) * 1000) / 1000;
      assert.equal(item.clock.phaseSource, item.phase === 0 ? 'record' : neighbour ? 'recorded' : 'deltaTime', `phase source of ${item.id}`);
      assert(Math.abs(item.clock.directorTime - (neighbour ? neighbour.clock.directorTime : estimate)) < 1e-12, `time of ${item.id}`);
      assert.equal(item.clock.sourceDirectorTime, source.clock.directorTime);
      assert.equal(item.kind, source.kind);
      assert(!item.errors, `${item.id}: ${JSON.stringify(item.errors)}`);
    }
    for (const item of records.filter((entry) => entry.kind === 'frame')) {
      const t = item.clock.directorTime, camera = item.cameras[0];
      assert.equal(camera.key, 'camera:main');
      assert.equal(camera.liveShot, true);
      assert(Math.abs(camera.fieldOfView - (30 + 20 * t / 4)) < 1e-6, `fov in degrees at ${t}`);
      assert(Math.abs(camera.authoredFov - camera.fieldOfView) < 1e-6, 'Correction is 1 at 16:9');
      assert.equal(item.correctors[0].correction, 1);
      const expected = [-4 * t / 4, 1 + 0.6 * t / 4, 3 - t / 4];
      camera.transform.position.forEach((value, axis) => assert(Math.abs(value - expected[axis]) < 1e-5, `camera ${axis} at ${t}`));
      assert.equal(camera.projection[11], -1, 'column-major projection');
      assert.deepEqual(camera.checks, { matrixWorldCurrent: true, projectionMatchesFov: true });
      assert.equal(camera.event.binding, binding);
      assert.deepEqual(item.renderSettings, { modeled: false });
    }
    const renderers = records.find((entry) => entry.id === 'p0-renderers-00@0').renderers;
    assert(renderers.length > 0 && renderers.every((entry) => entry.key.startsWith('renderer:stage:')), 'stage renderers are keyed by scope and mesh');
    assert(renderers.every((entry) => (entry.path === null) === (entry.pathSource === 'flattened') && entry.culled === false),
      'every renderer states its GameObject path source and culler state');
    assert(records.find((entry) => entry.id === 'p0-members-00@0').cost.prerollSteps === 15, 'physics preroll on the 30 Hz grid');
    // The members record is read after the next frame's pre-timeline spring step (PHYSICS_READ_POINT);
    // the fixture performer has no swing bones, so the read point runs and steps nothing.
    assert.deepEqual(records.filter((entry) => entry.part === 'members').map((entry) => entry.clock.readPointStep), [0, 0, 0]);
    assert(records.filter((entry) => entry.kind === 'frame' || entry.part === 'renderers').every((entry) => !('readPointStep' in entry.clock)));
    assert(timing.captureSeconds >= 0);
    assert.deepEqual(errors, []);

    // Sampler 3 frame clocks: every rendered frame's own director time. A neighbour only the frame
    // clock read is evaluated at its time ("frameClock"); one a record was taken in stays "recorded".
    const rows = [[100, 0.44], [101, 0.5], [102, 1.0], [103, 2.5], [104, 1.0], [105, 1.0], [106, 1.06]]
      .map(([frame, t]) => [frame, t, Math.round(t * 1000), 900 + t, DT, 1000 + frame / 15, 0]);
    const clocked = { ...read.doc, trailer: { ...read.doc.trailer, frameClocks: { schema: 'sifas-mv-frame-clock/1',
      fields: runtime.FRAME_CLOCK_FIELDS, rows } } };
    const clockedRun = await runtime.capturePage(page, clocked, { phases: [-1, 0, 1], preroll: 0.5, rate: 30, batchSize: 8 });
    const at = (id) => clockedRun.records.find((entry) => entry.id === id).clock;
    assert.deepEqual([at('f0001@-1').directorTime, at('f0001@-1').phaseSource], [0.44, 'frameClock']);
    assert.deepEqual([at('f0003@1').directorTime, at('f0003@1').phaseSource], [1.0, 'recorded']);
    assert.deepEqual([at('p0-members-00@1').directorTime, at('p0-members-00@1').phaseSource], [1.06, 'frameClock']);
    assert(clockedRun.records.every((entry) => !entry.errors), 'frame clock phases evaluate cleanly');
    // The game's Time.time for the original particle systems reaches the scene.
    const samples = runtime.gameClockSamples(clocked);
    assert.equal(samples.source, 'frameClock');
    assert.equal(await runtime.setGameClock(page, samples.samples), samples.samples.length);
    assert.equal(samples.frames, null, 'a director that goes back gives no device frames');
    // The run's own device frames: the scene steps them, and a seek can show one of several frames at a time.
    const frames = [[0.44, DT, 100], [0.5, DT, 101], [1.0, DT, 102], [1.0, DT, 103], [1.06, DT, 104]];
    assert.equal(await runtime.setGameClock(page, samples.samples, frames), samples.samples.length);
    assert.equal(await runtime.gameFrameCount(page), 5);
    assert.equal(await page.evaluate(() => mvFrameProbe.scene.setGameFrame(102)), 102);
    await page.evaluate(() => mvFrameProbe.scene.seek(1.0, undefined, true));
    assert.equal(await page.evaluate(() => mvFrameProbe.scene.setGameFrame(null)), null);
    assert.equal(await runtime.setGameClock(page, null), 0);
    assert.equal(await runtime.gameFrameCount(page), 0);
    assert.deepEqual(errors, []);

    const doc = runtime.editorDocument({ game: read.doc, gameFile, sha256: read.sha256, records, timing,
      conventions: await page.evaluate(() => ({ ...MVStudioAssetDump.CONVENTIONS })), manifest: { source }, viewport,
      quality: applied, phases: [-1, 0, 1], preroll: 0.5, rate: 30, batchSize: 4, keysFile: null,
      producer: { name: 'mv_runtime_capture_browser.js' }, errors, began: Date.now() });
    assert.deepEqual(doc.header.quality.gameDifferences.differences, []);
    assert.deepEqual(doc.header.quality.gameDifferences.gameOnly, ['MovieLive']);
    assert.equal(doc.header.quality.status, 'matched');
    const editorFile = path.join(work, 'editor-dump.json.gz');
    fs.writeFileSync(editorFile, zlib.gzipSync(JSON.stringify(doc)));
    const python = process.env.VIEWER_PYTHON || 'python3';
    const compare = (gameInput, out) => JSON.parse(execFileSync(python, [path.join(__dirname, 'mv_runtime_compare.py'), '--game', gameInput,
      '--editor', editorFile, '--out', path.join(work, out)], { encoding: 'utf8' }).trim().split('\n').at(-1));
    const identity = compare(editorFile, 'identity');
    assert.equal(identity.validity, 'valid');
    assert.equal(identity.beyondTolerance, 0);
    assert.equal(identity.worstScore, 0, 'editor-vs-editor is identically zero');
    const mirrored = path.join(work, 'mirror.json.gz');
    execFileSync(python, [path.join(__dirname, 'mv_runtime_synthetic.py'), 'mirror', '--editor', editorFile, '--out', mirrored], { stdio: 'ignore' });
    const result = compare(mirrored, 'mirror');
    assert.equal(result.validity, 'valid');
    assert.equal(result.beyondTolerance, 0);
    assert.equal(result.phase, 0);
    assert.equal(result.hypothesis, 'H180');
    assert.equal(result.fov, 'FOVMOD_DEFAULT_NO_CORRECTION');
    assert.equal(result.editorFov, 'EDITOR_FOV_MATCH');
    console.log(JSON.stringify({ ok: true, records: records.length, captureSeconds: timing.captureSeconds, evidence: work }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
  }
}

run().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
