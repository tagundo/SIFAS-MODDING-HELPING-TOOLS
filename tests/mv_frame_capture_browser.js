/* Frame capture runner against the real editor UI and scene, with a synthetic game catalog.

   Checks that the runner imports through the catalog and game stream, applies the
   game quality mode, pins the render size, steps to exact times with the game
   camera, reads back deterministic pixels, and that the comparator maps those
   frames back onto a 30 fps export of themselves. The runner always chooses the MV
   deck and local player explicitly (no player by default, even when the editor
   preselects a lone one) and refuses a project dressed from another deck.
*/
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, execFileSync } = require('node:child_process');
const net = require('node:net');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const capture = require('./mv_frame_capture');

const media = (ext) => '/api/mv-studio/media/' + 'a'.repeat(32) + ext;
const quality = (height) => ({ rendering_resolution: height, frame_rate_60fps: false, posteffect: false });
const OFFSET = 0.25;

function project(deck = { deckType: 2, userId: null, saved: false }, performers = []) {
  const suits = performers.map(({ position, memberId, costumeId, viewStatus, suitSource, attachKey }) =>
    ({ position, memberId, costumeId, viewStatus, suitSource, attachKey }));
  return {
    version: 1, name: 'Frame fixture', token: 'f'.repeat(32), duration: 4,
    stage: { glb: media('.glb'), label: 'Fixture stage' }, soundtrack: { url: media('.wav'), offset: OFFSET },
    source: { kind: 'game', region: 'gl', platform: 'ios', liveId: 12, assetId: 34, deck, suits },
    tracks: [{ id: 'cam', kind: 'camera', label: 'Camera', events: [{ id: 'cam:0', start: 0, duration: 4, label: 'Shot',
      values: { keyframes: [
        { time: 0, position: [0, 1.0, 3.0], rotation: [0, 0, 0, 1], fov: 30 },
        { time: 4, position: [4.0, 1.6, 2.0], rotation: [0, 0.25881905, 0, 0.96592583], fov: 50 },
      ] } }] }],
    assets: [], performers, warnings: ['Synthetic stage for the frame capture runner.'],
    quality: { mode: 30, values: quality(180), modes: [{ id: 20, label: 'High 3D', values: quality(360) }, { id: 30, label: 'Normal 3D', values: quality(180) }],
      options: [{ key: 'rendering_resolution', label: 'Render resolution', type: 'number' },
        { key: 'frame_rate_60fps', label: '60 fps', type: 'boolean' }, { key: 'posteffect', label: 'Post-processing effects', type: 'boolean' }] },
  };
}

function noiseWav(seconds, rate = 16000) {
  let seed = 0x9e3779b9 | 0;
  // xorshift32: aperiodic over the clip, so the audio lag has a single peak.
  const samples = new Int16Array(seconds * rate).map(() => { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >> 20); });
  const header = Buffer.alloc(44);
  header.write('RIFF', 0); header.writeUInt32LE(36 + samples.byteLength, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22); header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34); header.write('data', 36);
  header.writeUInt32LE(samples.byteLength, 40);
  return Buffer.concat([header, Buffer.from(samples.buffer)]);
}

async function boot(library) {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)],
    { cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: 'ignore' });
  const url = 'http://127.0.0.1:' + port;
  for (let tries = 0; tries < 100; tries++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { child, url }; } catch (_) {}
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 75));
  }
  child.kill();
  throw new Error('Isolated MV editor did not start');
}

function planning() {
  const tracks = [{ kind: 'camera', events: [{ start: 0, duration: 2 }, { start: 2, duration: 0.6 }, { start: 2.6, duration: 4 }, { start: 6.6, duration: 3 }] },
    { kind: 'lighting', events: [{ start: 1, duration: 1 }] }, { kind: 'camera', muted: true, events: [{ start: 0.5, duration: 1 }] }];
  assert.deepEqual(capture.cameraCuts(tracks), [0, 2, 2.6, 6.6, 9.6], 'only unmuted game camera clips define cuts');
  // The 0.6 s shot cannot keep 0.5 s from both cuts; the rest are spread and on the 30 fps grid.
  assert.deepEqual(capture.midShotTimes(tracks, { count: 9, grid: 30, margin: 0.5 }), [1, 4.6, 8.1]);
  assert.deepEqual(capture.midShotTimes(tracks, { count: 2, grid: 30, margin: 0.5 }), [1, 8.1]);
  assert(Math.abs(capture.cutDistance(capture.cameraCuts(tracks), 2.05) - 0.05) < 1e-9);
  assert.throws(() => capture.readManifest(writeManifest({ autoFrames: { count: 3, grid: 25 } })), /grid/);
  assert.equal(capture.readManifest(writeManifest({ autoFrames: { count: 3 } })).frames.length, 0);
  // The deck tab and local player: Customize and a new player unless the manifest names them.
  const sourceWith = (extra) => ({ source: { region: 'gl', platform: 'ios', liveId: 1, assetId: 2, ...extra } });
  assert.deepEqual(capture.deckRequest(capture.readManifest(writeManifest({ frames: [1] })).source), { deckType: 2, userId: null });
  assert.deepEqual(capture.deckRequest(capture.readManifest(writeManifest({ frames: [1], ...sourceWith({ deck: 'original', player: 7 }) })).source),
    { deckType: 1, userId: 7 });
  for (const player of [0, '7', 1.5]) {
    assert.throws(() => capture.readManifest(writeManifest({ frames: [1], ...sourceWith({ player }) })), /source\.player/);
  }
}

// Every manifest planning() writes goes into one temporary folder, removed when planning ends.
let manifests = null, written = 0;
function writeManifest(extra) {
  manifests ||= fs.mkdtempSync(path.join(os.tmpdir(), 'mv-frame-manifest-'));
  const file = path.join(manifests, `frames-${written++}.json`);
  fs.writeFileSync(file, JSON.stringify({ source: { region: 'gl', platform: 'ios', liveId: 1, assetId: 2 }, quality: { mode: 30 }, ...extra }));
  return file;
}

function plan() {
  try {
    planning();
  } finally {
    if (manifests) fs.rmSync(manifests, { recursive: true, force: true });
  }
  assert(manifests && !fs.existsSync(manifests), 'the temporary manifests are removed');
  manifests = null;
}

async function run() {
  plan();
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-frame-capture-'));
  const library = path.join(work, 'library'), out = path.join(work, 'capture');
  fs.mkdirSync(library); fs.mkdirSync(out);
  const wav = noiseWav(5);
  const server = await boot(library);
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true, args: capture.browserArgs(true) });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(capture.attachSceneProbe);
    let streamed = null, served = null;
    // One local Elichika player: the editor preselects it, the runner must not follow it silently.
    await page.route('**/api/mv-studio/catalog?*', route => route.fulfill({ json: {
      region: 'gl', platform: 'ios', regions: [{ id: 'gl', label: 'GL' }],
      platforms: [{ id: 'android', label: 'Android' }, { id: 'ios', label: 'iOS' }],
      songs: [{ id: 12, title: 'Fixture song', variants: [{ id: 34, label: 'MV' }] }],
      players: [{ id: 7, name: 'Player' }],
    } }));
    await page.route('**/api/mv-studio/game-stream?*', route => {
      streamed = route.request().postDataJSON();
      // Like the server: project.source.deck is the deck the import resolved.
      const deck = { deckType: streamed.deck?.deckType ?? 2, userId: streamed.deck?.userId ?? null, saved: false };
      const value = served ? served(deck) : project(deck);
      const preview = { stage: value.stage, assets: [], tracks: [], quality: value.quality, duration: value.duration, source: value.source };
      return route.fulfill({ contentType: 'application/x-ndjson; charset=utf-8',
        body: JSON.stringify({ type: 'stage', preview }) + '\n' + JSON.stringify({ type: 'complete', project: value }) + '\n' });
    });
    await page.route('**/api/mv-studio/media/*.glb', route => route.fulfill({ contentType: 'model/gltf-binary', body: fixture().glb }));
    await page.route('**/api/mv-studio/media/*.wav', route => route.fulfill({ contentType: 'audio/wav', body: wav }));
    await page.goto(server.url + '/#mv');
    const source = { region: 'gl', platform: 'ios', liveId: 12, assetId: 34 };
    assert.deepEqual(await capture.importOriginal(page, source, false),
      { kind: 'game', ...source, deck: { deckType: 2, userId: null, saved: false }, suits: [] });
    assert.deepEqual(streamed, { ...source, download: false },
      'The runner must import through the game stream with the manifest source, as a new player despite the preselected one');
    const record = await capture.projectRecord(page);
    assert.deepEqual([record.source.deck, record.performers], [{ deckType: 2, userId: null, saved: false }, []]);

    // A higher preset changes the native height; the requested mode then wins.
    const high = await capture.applyQuality(page, { mode: 20 });
    assert.equal(high.values.rendering_resolution, 360);
    // With --game-dump the quality the game ran wins over the manifest's preset, and the spring
    // clock's rule rate follows it (the preset here has frame_rate_60fps false).
    const gameRun = { file: 'dump.json', doc: { side: 'game', header: { quality: { values: { Quality: { v: 20, n: null },
      RenderingResolution: 240, FrameRate60Fps: true, PostEffect: false, MovieLive: false } } } } };
    const fromGame = await capture.captureQuality(page, { quality: { mode: 30 } }, gameRun);
    assert.deepEqual([fromGame.source, fromGame.status, fromGame.mode, fromGame.gameOnly], ['game', 'matched', 20, ['MovieLive']],
      JSON.stringify(fromGame.reasons));
    assert.deepEqual([fromGame.values.rendering_resolution, fromGame.values.frame_rate_60fps, fromGame.values.posteffect], [240, true, false]);
    assert.equal(capture.physicsReference({ physics: { order: 'game' } }, fromGame.values).rate, 60);
    const fromManifest = await capture.captureQuality(page, { quality: { mode: 20 } });
    assert.deepEqual([fromManifest.source, fromManifest.values.frame_rate_60fps], ['manifest', false]);
    assert.equal(capture.physicsReference({ physics: { order: 'game' } }, fromManifest.values).rate, 30);
    const applied = await capture.applyQuality(page, { mode: 30, overrides: { posteffect: false } });
    assert.equal(applied.values.rendering_resolution, 180);
    await capture.pinViewport(page, 320, 180);
    await page.evaluate(() => {
      const select = document.querySelector('#mv-camera-mode');
      select.value = 'live';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const rate = 30, frames = [];
    for (let index = 0; index <= 60; index++) frames.push(await capture.renderFrame(page, index / rate, 0.5, rate));
    for (const [index, frame] of frames.entries()) {
      const time = index / rate, state = frame.state;
      assert.equal(state.liveShot, true);
      assert.deepEqual(state.cameraEvent, { track: 'cam', event: 'cam:0', start: 0, duration: 4 });
      assert.deepEqual([state.canvas.width, state.canvas.height], [320, 180]);
      assert(Math.abs(state.time - time) < 1e-9, `state time ${state.time} != ${time}`);
      assert(Math.abs(state.camera.fov - (30 + 20 * time / 4)) < 1e-6, `fov at ${time}`);
      const x = -4 * time / 4, y = 1 + 0.6 * time / 4, z = 3 - time / 4;
      state.camera.position.forEach((value, axis) => assert(Math.abs(value - [x, y, z][axis]) < 1e-5, `camera ${axis} at ${time}`));
      assert.equal(frame.steps, Math.min(index, 15), 'preroll steps on the 30 Hz grid');
    }
    // Re-rendering an earlier time after a later one returns the same pixels.
    const again = await capture.renderFrame(page, 1, 0.5, rate);
    assert.equal(again.png, frames[30].png, 'Frame readback must be deterministic');
    assert.notEqual(frames[29].png, frames[30].png, 'Adjacent frames must differ for timing checks');
    const info = await capture.rendererInfo(page);
    assert(info.renderer, 'WebGL renderer string');
    assert.deepEqual(errors, []);

    // Encode the captured frames as a 30 fps "game export" whose audio starts at the soundtrack offset.
    const sequence = path.join(work, 'sequence');
    fs.mkdirSync(sequence);
    frames.forEach((frame, index) => fs.writeFileSync(path.join(sequence, String(index).padStart(3, '0') + '.png'),
      Buffer.from(frame.png.slice(frame.png.indexOf(',') + 1), 'base64')));
    fs.writeFileSync(path.join(work, 'soundtrack.wav'), wav);
    const video = path.join(work, 'game.mp4');
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-framerate', '30', '-i', path.join(sequence, '%03d.png'),
      '-ss', String(OFFSET), '-i', path.join(work, 'soundtrack.wav'), '-map', '0:v', '-map', '1:a',
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709',
      '-color_trc', 'bt709', '-color_range', 'tv', '-c:v', 'libx264', '-crf', '10', '-preset', 'veryfast', '-c:a', 'aac', video]);
    const picks = [15, 30, 45];
    fs.copyFileSync(path.join(work, 'soundtrack.wav'), path.join(out, 'soundtrack.wav'));
    const records = picks.map(index => {
      const file = capture.frameName(index / rate);
      fs.copyFileSync(path.join(sequence, String(index).padStart(3, '0') + '.png'), path.join(out, file));
      return { time: index / rate, image: file, state: frames[index].state };
    });
    fs.writeFileSync(path.join(out, 'capture.json'), JSON.stringify({ schema: 1, kind: 'elichika-mv-editor-frames',
      manifest: { source, quality: { mode: 30 }, frames: picks.map(index => index / rate) }, soundtrack: 'soundtrack.wav',
      project: { soundtrack: { offset: OFFSET }, warnings: [] }, environment: { webgl: info }, frames: records }));
    execFileSync(process.env.VIEWER_PYTHON || 'python3', [path.join(__dirname, 'mv_frame_compare.py'), '--capture',
      path.join(out, 'capture.json'), '--video', video, '--out', path.join(work, 'report')], { stdio: 'ignore' });
    const report = JSON.parse(fs.readFileSync(path.join(work, 'report', 'report.json'), 'utf8'));
    assert.equal(report.alignment.method, 'audio');
    assert(Math.abs(report.alignment.lag - OFFSET) < 0.002, `audio lag ${report.alignment.lag}`);
    assert.deepEqual(report.frames.map(frame => frame.videoFrame), picks);
    for (const frame of report.frames) {
      assert.equal(frame.bestOffset, 0, `best neighbour at ${frame.time}`);
      assert(frame.metrics.ssim > 0.9, `SSIM ${frame.metrics.ssim} at ${frame.time}`);
      assert(Math.abs(frame.geometry.scale - 1) < 0.011 && Math.hypot(frame.geometry.dx, frame.geometry.dy) < 1.5, `geometry at ${frame.time}`);
    }
    await playerChoice(page, () => streamed, (value) => { served = value; });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, renderer: info.renderer, meanSSIM: report.summary.meanSSIM, evidence: work }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
  }
}

// A named player and the Original tab reach the request; capture.json's project record
// carries each position's suit and why; a project dressed from another deck, or a player
// the server does not list, is refused.
async function playerChoice(page, lastRequest, serve) {
  const source = { region: 'gl', platform: 'ios', liveId: 12, assetId: 34, deck: 'original', player: 7 };
  const performer = { id: 'member-1', label: 'Member 1', position: 1, memberId: 211, costumeId: 102111001, viewStatus: 1,
    suitSource: 'deck', attachKey: 'c1', transform: { position: [0, 0, 0] } };
  serve((deck) => project(deck, [performer]));
  const imported = await capture.importOriginal(page, source, false);
  assert.deepEqual(lastRequest().deck, { deckType: 1, userId: 7 });
  assert.deepEqual(imported.deck, { deckType: 1, userId: 7, saved: false });
  const record = await capture.projectRecord(page);
  assert.deepEqual(record.source.suits, [{ position: 1, memberId: 211, costumeId: 102111001, viewStatus: 1, suitSource: 'deck', attachKey: 'c1' }]);
  assert.deepEqual(record.performers, [{ position: 1, memberId: 211, costumeId: 102111001, viewStatus: 1, suitSource: 'deck',
    attachKey: 'c1', loaded: false }]);
  serve((deck) => project({ ...deck, userId: null }, [performer]));
  await assert.rejects(capture.importOriginal(page, source, false), /dressed the members from deck/);
  serve(null);
  await assert.rejects(capture.importOriginal(page, { ...source, player: 8 }, false), /Player 8 is not in the editor server's player database \(offered: 7\)/);
  await page.evaluate(() => document.querySelector('#mv-game-picker').close());
}

run().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
