/* MV Studio real-time playback on the playback clock (mv-studio-playback-clock.js) in the real
   workbench, with a synthetic soundtrack: the page's media elements are replaced by a fake
   whose clock is read in coarse 20-50 ms steps with reading jitter and a start latency, so the
   test knows where the soundtrack really is on every frame. Each frame the scene draws is
   recorded (scene.playbackFrame with its frame timestamp).

   Synthetic project (stage fixture model, a soundtrack with a 0.5 s offset):
   - playback advances evenly: once locked, every frame advances by its frame interval times a
     rate within 1 ± 3 %, no frame repeats a time, no frame goes back (no clock rewind), and the
     shown time stays within 50 ms of the soundtrack, plus whatever a slow frame takes beyond
     1/60 s (the raw readings, as tick() used them, repeat a time on many frames: counted, and
     required to be above zero here only);
   - pause keeps the shown time at the soundtrack's; play again with no seek starts at the
     paused time and leaves the soundtrack where it is; a seek while paused and play from there,
     and a seek back while playing, start from the sought time and lock onto the soundtrack (a
     seek while playing writes the soundtrack once, to the sought time plus the offset);
   - a soundtrack stall holds the picture and it follows again on resume, never going back;
   - a soundtrack the browser pauses on its own: the time goes on with the frames; when the
     soundtrack comes back far behind, it is moved to the picture (to the shown time plus the
     offset);
   - a scrub of the seek slider while paused, then an edit (a seek to the time shown, the
     soundtrack left alone), then play: the scrub moved the soundtrack, so play does not move it
     again; the same after playback stopped at the song's end;
   - a soundtrack offset change while playing moves the soundtrack and follows the new offset;
   - a playing soundtrack whose readyState stays below HAVE_FUTURE_DATA is still followed;
   - edits while playing (seeks to the time shown, soundtrack left alone) change nothing;
   - a plugin seek with {audio: false} to another time while playing, forward or back, goes on
     from the sought time and moves the soundtrack there once;
   - a 1.5 s seek holds the picture at the sought time until the soundtrack plays (the fake's
     seeking flag is the only sign of it), then follows;
   - two 2 s stalls in one playback are each realigned and end in sync;
   - a 2 s stall whose realignment seek lands in data not loaded yet (2.5 s of loading after the
     write) holds the picture at the realigned time while the soundtrack loads, then follows it;
   - a soundtrack that ends before the MV (ended, not paused): the time goes on with the frames;
   - a soundtrack loading for 1.5 s after play holds the picture at the paused time without
     moving the soundtrack; one that fails to load (an error) is given up on after 1 s;
   - without a soundtrack every frame advances by exactly its frame interval (as before);
   - fixed-step frame captures (mv_frame_capture.renderFrame) are the same PNG and scene state
     before and after all of the above (the reference after one warm-up capture: the first
     capture after an import draws differently from later ones, at 0fcfd4d as well).

   Real 12035 MV (skipped unless MV_PLAYBACK_SERVER_ROOT is an Elichika server root that imports
   GL Android 12035/1203503; no game data in Git): the same playback, pause, play again, seek and
   resume checks (the raw-reading repeat count only logged: with frames slower than the readings
   it can be zero), a fixed-step capture identical before and after playback, and the native
   timeline export byte-identical before and after playback.

   Run: node tests/mv_studio_playback_clock_browser.js (EVIDENCE_DIR keeps the server logs). */
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const capture = require('./mv_frame_capture');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-playback-library-'));
const modded = path.join(library, 'modded');
const ownEvidence = !process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-playback-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);
const serverRoot = process.env.MV_PLAYBACK_SERVER_ROOT || '';
// The shown time may trail the soundtrack by up to one frame more than at 60 Hz when a frame
// takes longer (the last reading trails the soundtrack by up to a frame interval).
const SLEW = 0.03, BOUND = 0.05;
const allowed = (interval) => BOUND + Math.max(0, interval - 1 / 60);
// The largest offset from the soundtrack beyond what each frame allows (<= 0: within bounds).
function excess(frames) {
  let worst = -Infinity;
  for (let index = 1; index < frames.length; index++) {
    const interval = (frames[index].stamp - frames[index - 1].stamp) / 1000;
    worst = Math.max(worst, Math.abs(frames[index].time - frames[index].truth) - allowed(interval));
  }
  return worst;
}

async function startServer() {
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const processLog = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const processHandle = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)], {
    cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', processLog, processLog],
  });
  fs.closeSync(processLog);
  const url = 'http://127.0.0.1:' + port;
  for (let count = 0; count < 100; count++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { processHandle, url }; } catch (_) {}
    if (processHandle.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  processHandle.kill();
  throw new Error('Isolated workbench did not start');
}

// Replaces the MV soundtrack's media clock (a media element playing an /api/mv-studio/ URL;
// other media elements keep the browser's) with a fake soundtrack (window.fakeAudio): its true
// position advances with performance.now() (after a start latency, and not while stalled); a
// read returns the position of its latest update, updates coming 20-50 ms apart. A currentTime
// write seeks for seekMs (seeking true, the position held; readyState stays as set, so only the
// seeking flag tells the clock); play() from paused loads for loadMs (readyState 1, the position
// held); with loadAfterWrite set, a write also loads for that long after its seek (readyState 1,
// the position held: a seek into data not fetched yet); at endAt the soundtrack ends (ended true
// while paused stays false, so only the ended flag tells the clock). Each write records the time
// shown by the next frame drawn.
function installFakeAudio() {
  let seed = 12345;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const now = () => performance.now();
  const fake = window.fakeAudio = { steps: [0.02, 0.05], jitter: 0.002, latency: 0.06, playing: false, stalled: false,
    base: 0, anchor: 0, reported: 0, next: 0, writes: [], plays: 0, readAt: 0, readyState: 4, seekMs: 40, seekUntil: 0, loadMs: 0,
    loadUntil: 0, loadAfterWrite: 0, endAt: Infinity, error: null };
  const step = () => (fake.steps[0] + (fake.steps[1] - fake.steps[0]) * random()) * 1000;
  fake.truth = (t = now()) => Math.min(fake.endAt,
    fake.playing && !fake.stalled ? fake.base + Math.max(0, t - fake.anchor) / 1000 : fake.base);
  fake.start = (position, after = 0) => {
    fake.base = fake.reported = position;
    fake.anchor = now() + Math.max(fake.latency * 1000, after);
    fake.next = now() + step();
  };
  fake.read = () => {
    const t = fake.readAt = now();
    // A stalled clock, or one not yet playing (start latency, loading, seeking), reads the same,
    // jitter and all.
    while (!fake.stalled && fake.next <= t) {
      if (fake.next >= fake.anchor) fake.reported = fake.truth(fake.next) + (random() * 2 - 1) * fake.jitter;
      fake.next += step();
    }
    return fake.reported;
  };
  fake.stall = () => { fake.base = fake.reported = fake.truth(); fake.stalled = true; };
  fake.resume = () => { fake.anchor = now(); fake.stalled = false; fake.next = now() + step(); };
  // The browser pauses the soundtrack on its own (an interruption), then lets it go on.
  fake.interrupt = () => { fake.stoppedAt = now(); fake.base = fake.reported = fake.truth(fake.stoppedAt); fake.playing = false; };
  fake.uninterrupt = () => { fake.playing = true; fake.start(fake.base); };
  const proto = HTMLMediaElement.prototype;
  const mine = (element) => /\/api\/mv-studio\//.test(element.getAttribute('src') || '');
  const define = (name, get, set) => {
    const native = Object.getOwnPropertyDescriptor(proto, name);
    Object.defineProperty(proto, name, { configurable: true,
      get() { return mine(this) ? get() : native.get.call(this); },
      ...(set ? { set(value) { if (mine(this)) set(value); else native.set.call(this, value); } } : {}) });
  };
  define('currentTime', () => fake.read(), (value) => {
    fake.writes.push({ value, at: now() });
    fake.seekUntil = now() + fake.seekMs;
    if (fake.loadAfterWrite) fake.loadUntil = fake.seekUntil + fake.loadAfterWrite;
    fake.start(value, fake.seekMs + fake.loadAfterWrite);
  });
  define('paused', () => !fake.playing);
  define('ended', () => fake.playing && fake.truth() >= fake.endAt);
  define('seeking', () => now() < fake.seekUntil);
  define('readyState', () => now() < fake.loadUntil ? 1 : fake.readyState);
  define('error', () => fake.error);
  const { play, pause } = proto;
  proto.play = function () {
    if (!mine(this)) return play.call(this);
    fake.plays++;
    if (!fake.playing) {
      fake.playing = true;
      fake.loadUntil = now() + fake.loadMs;
      fake.start(fake.base, fake.loadMs);
    }
    return Promise.resolve();
  };
  proto.pause = function () {
    if (!mine(this)) return pause.call(this);
    if (fake.playing) fake.interrupt();
  };
}

// Records every frame the scene draws during playback: shown time, frame timestamp, the
// soundtrack's true song time at the frame timestamp (the reference: the clock works on frame
// timestamps, and the frame is shown for that time) and when it was read, and its raw reading.
function recordFrames() {
  window.playLog = [];
  const scene = window.probeCtx.scene(), draw = scene.playbackFrame;
  if (scene.recorded) return;
  scene.recorded = true;
  const offset = () => window.probeCtx.project()?.soundtrack?.offset || 0;
  scene.playbackFrame = function (time, stamp, ...rest) {
    if (Number.isFinite(stamp) && window.probeCtx.playing()) {
      const fake = window.fakeAudio, song = (value) => value - offset();
      window.lastFrameStamp = stamp;
      window.playLog.push({ time, stamp, truth: song(fake.truth(stamp)), truthAtRead: song(fake.truth(fake.readAt)), reading: song(fake.reported),
        sounding: fake.playing && !fake.stalled, ended: fake.playing && fake.truth(stamp) >= fake.endAt });
      for (const write of fake.writes) if (write.shown === undefined) Object.assign(write, { shown: time, offset: offset() });
    }
    return draw.call(this, time, stamp, ...rest);
  };
}

// Frames of a played segment: per-frame advance against the frame interval.
function analyse(frames, { settle = 400, from = null } = {}) {
  assert(frames.length >= 10, `enough frames (${frames.length})`);
  const start = frames[0].stamp;
  let back = 0, repeated = 0, naiveRepeated = 0, naiveBack = 0, worst = 0, minRatio = Infinity, maxRatio = -Infinity, uneven = 0;
  let over = -Infinity, longest = 0;
  for (let index = 1; index < frames.length; index++) {
    const [a, b] = [frames[index - 1], frames[index]];
    const advance = b.time - a.time, interval = (b.stamp - a.stamp) / 1000;
    if (advance < -1e-12) back++;
    if (b.reading === a.reading) naiveRepeated++;
    if (b.reading < a.reading) naiveBack++;
    if (b.stamp - start < settle) continue;
    if (advance === 0) repeated++;
    const ratio = advance / interval;
    minRatio = Math.min(minRatio, ratio);
    maxRatio = Math.max(maxRatio, ratio);
    if (ratio < 1 - SLEW - 1e-9 || ratio > 1 + SLEW + 1e-9) uneven++;
    worst = Math.max(worst, Math.abs(b.time - b.truth));
    over = Math.max(over, Math.abs(b.time - b.truth) - allowed(interval));
    longest = Math.max(longest, interval);
  }
  if (from !== null) assert(frames[0].time >= from - 1e-9, `starts at the sought time (${frames[0].time} >= ${from})`);
  return { frames: frames.length, back, repeated, uneven, minRatio: +minRatio.toFixed(4), maxRatio: +maxRatio.toFixed(4),
    maxOffsetMs: +(worst * 1000).toFixed(1), overMs: +(over * 1000).toFixed(1), longestFrameMs: +(longest * 1000).toFixed(1),
    naiveRepeated, naiveBack };
}

function steady(label, result) {
  assert.equal(result.back, 0, `${label}: no frame goes back`);
  assert.equal(result.repeated, 0, `${label}: no frame repeats a time`);
  assert.equal(result.uneven, 0, `${label}: every frame advances by its interval × 1 ± ${SLEW} (${result.minRatio}..${result.maxRatio})`);
  assert(result.overMs <= 0, `${label}: within ${BOUND * 1000} ms (plus any frame time beyond 1/60 s) of the soundtrack ` +
    `(${result.maxOffsetMs} ms, longest frame ${result.longestFrameMs} ms)`);
}

const take = (page) => page.evaluate(() => window.playLog.splice(0));
// The soundtrack writes since the last call: { value, at, shown (time of the next frame drawn), offset }.
const writesOf = (page) => page.evaluate(() => window.fakeAudio.writes.splice(0));
const offsetOf = (page) => page.evaluate(() => window.probeCtx.project().soundtrack?.offset || 0);
const near = (a, b) => Math.abs(a - b) < 1e-9;
const playing = (page) => page.evaluate(() => MVStudio.getState().playing);
async function play(page, ms) {
  if (!(await playing(page))) await page.locator('#mv-play').click();
  await page.waitForTimeout(ms);
}
async function pause(page) {
  if (await playing(page)) await page.locator('#mv-play').click();
}
// Seeks as the editor's plugins do (the scene and the soundtrack), from a fresh frame log.
const seek = (page, time) => page.evaluate((value) => { window.playLog.length = 0; window.probeCtx.seek(value); }, time);
const sha = (value) => crypto.createHash('sha256').update(value).digest('hex');

async function newPage(browser, errors, viewport = { width: 1280, height: 800 }) {
  const context = await browser.newContext({ locale: 'ko', viewport });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  await page.addInitScript(installFakeAudio);
  await page.addInitScript(() => {
    (window.MVStudioPlugins ||= []).push({ id: 'test-probe', order: 99, attach(ctx) { window.probeCtx = ctx; } });
  });
  return page;
}

// The fixed-step capture of the frame-capture tool at `time`: its PNG hash and scene state.
// The first capture after an import draws differently from later ones (also at 0fcfd4d,
// without any playback), so a reference is taken after one warm-up capture.
async function fixedCapture(page, time, warm = false) {
  if (warm) await fixedCapture(page, time);
  await page.evaluate(() => { window.mvFrameProbe = { scene: window.probeCtx.scene() }; });
  const frame = await capture.renderFrame(page, time, 1, 30);
  return { png: sha(frame.png), state: JSON.stringify(frame.state) };
}

function gameProject(local, soundtrack) {
  return {
    version: 1, name: soundtrack ? 'Playback clock MV' : 'Playback clock MV (silent)', duration: 30, nativeTimeline: false,
    assets: local.assets, stage: local.stage, warnings: [], quality: {}, performers: [],
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 79, assetId: soundtrack ? 1 : 2 },
    ...(soundtrack ? { soundtrack: { url: '/api/mv-studio/playback-test.wav', offset: 0.5, duration: 40 } } : {}),
    tracks: [],
  };
}

async function importGame(page, project) {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 79, title: project.name, variants: [{ id: project.source.assetId, label: 'MV' }] }] } }));
  await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: project }));
  await page.route('**/api/mv-studio/playback-test.wav', (route) => route.fulfill({ status: 204 }));
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
  await page.locator('#mv-game-load').click();
  await page.waitForFunction((name) => MVStudio.getState().project?.name === name && !document.getElementById('mv-import-game').disabled, project.name);
  await page.waitForFunction(() => !document.getElementById('mv-play').disabled);
}

// Play, pause, seek and resume checks shared by the synthetic and the real MV. `rawRepeats`:
// the raw readings must repeat a time on some frames (a precondition that holds only while
// frames come faster than the fake's 20-50 ms readings: the synthetic project at 60 Hz, not
// the real MV, whose frames can take 50-700 ms under swiftshader; there the count is logged).
async function transport(page, label, { from, later, earlier, ms = 1500, rawRepeats = true }) {
  const results = {};
  const offset = await offsetOf(page);
  await seek(page, from);
  await writesOf(page);
  await play(page, ms);
  results.play = analyse(await take(page), { from });
  console.log(label, 'play', JSON.stringify(results.play));
  steady(`${label} play`, results.play);
  if (rawRepeats) assert(results.play.naiveRepeated > 0, `${label}: the raw readings repeat a time on some frames (${results.play.naiveRepeated})`);

  // Pause: the shown time (the last frame's) is the soundtrack's where it stopped.
  await pause(page);
  const paused = await page.evaluate(() => ({ time: window.probeCtx.time(), audio: window.fakeAudio.base - (window.probeCtx.project().soundtrack?.offset || 0),
    since: (window.fakeAudio.stoppedAt - window.lastFrameStamp) / 1000 }));
  assert(Math.abs(paused.time - paused.audio) <= allowed(paused.since),
    `${label}: paused in sync (${paused.time} vs ${paused.audio}, ${paused.since} s after the last frame)`);
  results.pausedOffsetMs = +((paused.time - paused.audio) * 1000).toFixed(1);

  // Play again with no seek: the first frame shows the paused time, the soundtrack is not moved.
  await page.evaluate(() => { window.playLog.length = 0; });
  await writesOf(page);
  await play(page, ms);
  const replay = await take(page);
  assert.equal(replay[0].time, paused.time, `${label}: play after pause starts at the paused time`);
  assert.deepEqual(await writesOf(page), [], `${label}: play after pause leaves the soundtrack where it is`);
  results.replay = analyse(replay);
  console.log(label, 'play after pause', JSON.stringify(results.replay));
  steady(`${label} play after pause`, results.replay);
  await pause(page);

  // Seek while paused, then play from there.
  await seek(page, later);
  await play(page, ms);
  results.resume = analyse(await take(page), { from: later });
  console.log(label, 'resume', JSON.stringify(results.resume));
  steady(`${label} resume`, results.resume);

  // Seek back while playing: from the sought time, locked again; the soundtrack is moved once,
  // to the sought time (and not back to the old one).
  await writesOf(page);
  await seek(page, earlier);
  await page.waitForTimeout(ms);
  const back = await take(page);
  results.seekBack = analyse(back, { from: earlier });
  console.log(label, 'seek while playing', JSON.stringify(results.seekBack));
  const moved = await writesOf(page);
  assert.equal(moved.length, 1, `${label}: a seek while playing moves the soundtrack once (${JSON.stringify(moved)})`);
  assert(near(moved[0].value, earlier + offset), `${label}: to the sought time plus the offset (${moved[0].value})`);
  assert.equal(moved[0].shown, earlier, `${label}: the next frame shows the sought time`);
  assert(back[0].time - earlier <= 1 / 60 + 1e-9, `${label}: the first frame after the seek is at the sought time (${back[0].time})`);
  steady(`${label} seek while playing`, results.seekBack);
  await pause(page);
  return results;
}

async function synthetic(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  assert(local.stage && local.stage.glb, 'the stage fixture opens');
  await importGame(page, gameProject(local, true));
  await page.evaluate(recordFrames);
  const before = await fixedCapture(page, 4, true);
  const result = await transport(page, 'synthetic', { from: 2, later: 8, earlier: 3 });

  // A scrub of the seek slider while paused (the scene and the soundtrack seek on the next
  // frame), then an edit (apply() seeks to the time shown with the soundtrack left alone), then
  // play: the scrub moved the soundtrack, so play leaves it where it is. The same after playback
  // stopped at the song's end (the clock there may be past the duration) and a scrub back.
  result.pausedScrubs = [];
  for (const [label, prepare] of [['paused scrub', null], ['scrub after the song end', async () => {
    await seek(page, 29.6);
    await play(page, 1500);
    assert.equal(await playing(page), false, 'the song end stops playback');
  }]]) {
    if (prepare) await prepare();
    await writesOf(page);
    const to = 9, offset = await offsetOf(page);
    await page.evaluate((value) => {
      const input = document.getElementById('mv-seek');
      input.value = String(value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, to);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const scrubbed = await writesOf(page);
    assert(scrubbed.length === 1 && near(scrubbed[0].value, to + offset), `${label}: the scrub moves the soundtrack once (${JSON.stringify(scrubbed)})`);
    await page.evaluate(() => window.probeCtx.seek(window.probeCtx.time(), { audio: false }));
    await page.evaluate(() => { window.playLog.length = 0; });
    await play(page, 1000);
    await pause(page);
    const frames = await take(page);
    assert.deepEqual(await writesOf(page), [], `${label}, an edit, then play: the soundtrack is not moved again`);
    assert.equal(frames[0].time, to, `${label}: play starts at the scrubbed time`);
    const analysed = analyse(frames, { from: to });
    steady(`${label}, an edit, then play`, analysed);
    result.pausedScrubs.push({ label, ...analysed });
  }

  // A stall: the picture holds within the stall limit and follows again, never going back.
  await seek(page, 12);
  await play(page, 800);
  await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.stall(); });
  await page.waitForTimeout(500);
  await page.evaluate(() => window.fakeAudio.resume());
  await page.waitForTimeout(1200);
  const stalled = await take(page);
  const stall = analyse(stalled, { settle: 0 });
  assert.equal(stall.back, 0, 'stall: no frame goes back');
  const frozen = stalled.filter((frame) => !frame.sounding);
  assert(frozen.length > 5, 'frames during the stall');
  const lead = Math.max(...frozen.map((frame) => frame.time - frame.truth));
  assert(lead <= .5 + 1 / 30, `stall: the picture stops within the stall limit (${lead} s ahead)`);
  fs.writeFileSync(path.join(evidence, 'stall-frames.json'), JSON.stringify(stalled));
  const afterStall = stalled.filter((frame) => frame.stamp >= stalled.at(-1).stamp - 500);
  assert(excess(afterStall) <= 0, `stall: in sync again (${excess(afterStall)} s beyond the bound)`);
  result.stall = { ...stall, leadMs: +(lead * 1000).toFixed(1) };

  // The browser pauses the soundtrack on its own for 1.2 s: frames only, then the soundtrack is
  // moved to the picture when it comes back behind it.
  await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.writes.length = 0; window.fakeAudio.interrupt(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => window.fakeAudio.uninterrupt());
  await page.waitForTimeout(1200);
  const interrupted = await take(page);
  const interruption = analyse(interrupted, { settle: 0 });
  assert.equal(interruption.back, 0, 'interruption: no frame goes back');
  const silent = interrupted.filter((frame) => !frame.sounding);
  for (let index = 1; index < silent.length; index++) {
    const advance = silent[index].time - silent[index - 1].time, interval = (silent[index].stamp - silent[index - 1].stamp) / 1000;
    assert(Math.abs(advance - interval) < 1e-6, 'interruption: the time goes on with the frames');
  }
  const writes = await page.evaluate(() => window.fakeAudio.writes.slice());
  assert.equal(writes.length, 1, `interruption: the soundtrack is moved once (${JSON.stringify(writes)})`);
  assert(near(writes[0].value, writes[0].shown + 0.5), `interruption: to the shown time plus the offset (${JSON.stringify(writes[0])})`);
  const tail = interrupted.filter((frame) => frame.stamp >= interrupted.at(-1).stamp - 400);
  assert(excess(tail) <= 0, `interruption: in sync again (${excess(tail)} s beyond the bound)`);
  result.interruption = { ...interruption, realignedTo: writes[0].value };

  // A soundtrack offset change while playing moves the soundtrack and follows the new offset.
  const moved = await page.evaluate(() => {
    window.fakeAudio.writes.length = 0;
    const input = document.getElementById('mv-soundtrack-offset');
    input.value = '0.75';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return { writes: window.fakeAudio.writes.slice(), time: window.probeCtx.time(), offset: window.probeCtx.project().soundtrack.offset };
  });
  assert.equal(moved.offset, 0.75);
  assert.equal(moved.writes.length, 1, 'the soundtrack is moved once');
  assert(near(moved.writes[0].value, moved.time + 0.75), 'to the shown time plus the new offset');
  await page.evaluate(() => { window.playLog.length = 0; });
  await page.waitForTimeout(1200);
  result.offsetChange = analyse(await take(page));
  steady('offset change', result.offsetChange);

  // A playing soundtrack whose readyState stays below HAVE_FUTURE_DATA is still followed
  // (buffering shows as readings that stop changing).
  await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.readyState = 2; });
  await page.waitForTimeout(1000);
  result.lowReadyState = analyse(await take(page), { settle: 0 });
  await page.evaluate(() => { window.fakeAudio.readyState = 4; });
  steady('readyState 2', result.lowReadyState);
  await writesOf(page);
  const offset = await offsetOf(page);
  assert.equal(offset, 0.75);

  // Edits while playing (a plugin seeks to the time shown, the soundtrack left alone, about 20
  // times a second): playback goes on undisturbed and the soundtrack is not moved.
  await page.evaluate(() => {
    window.playLog.length = 0;
    window.editTimer = setInterval(() => window.probeCtx.seek(window.probeCtx.time(), { audio: false }), 45);
  });
  await page.waitForTimeout(900);
  await page.evaluate(() => clearInterval(window.editTimer));
  result.editsWhilePlaying = analyse(await take(page), { settle: 0 });
  steady('edits while playing', result.editsWhilePlaying);
  assert.deepEqual(await writesOf(page), [], 'edits while playing: the soundtrack is not moved');

  // A plugin seek to another time while playing, the soundtrack left alone ({audio: false}, as
  // selecting a follow camera rig does), forward and back: the picture goes on from the sought
  // time and the soundtrack is moved there once.
  result.pluginSeeks = [];
  for (const by of [0.3, -1]) {
    const sought = await page.evaluate((delta) => {
      window.playLog.length = 0;
      window.probeCtx.seek(window.probeCtx.time() + delta, { audio: false });
      return window.probeCtx.time();
    }, by);
    await page.waitForTimeout(1200);
    const frames = await take(page), moved = await writesOf(page);
    assert.equal(moved.length, 1, `plugin seek by ${by} s: the soundtrack is moved once (${JSON.stringify(moved)})`);
    assert(near(moved[0].value, sought + offset) && moved[0].shown === sought, `plugin seek by ${by} s: to the sought time (${JSON.stringify(moved[0])})`);
    assert.equal(frames[0].time, sought, `plugin seek by ${by} s: the first frame shows the sought time`);
    const analysed = analyse(frames, { from: sought });
    steady(`plugin seek by ${by} s`, analysed);
    result.pluginSeeks.push({ by, ...analysed });
  }

  // A slow seek while playing (1.5 s, as over a phone's network): the picture holds at the sought
  // time while the soundtrack seeks, without giving up on it, then follows.
  await page.evaluate(() => { window.fakeAudio.seekMs = 1500; });
  await seek(page, 5);
  await page.waitForTimeout(2700);
  await page.evaluate(() => { window.fakeAudio.seekMs = 40; });
  {
    const frames = await take(page), moved = await writesOf(page);
    assert.equal(moved.length, 1, `slow seek: the soundtrack is moved once (${JSON.stringify(moved)})`);
    assert(near(moved[0].value, 5 + offset), `slow seek: to the sought time plus the offset (${moved[0].value})`);
    const seeking = frames.filter((frame) => frame.stamp < moved[0].at + 1500 - 100);
    assert(seeking.length > 10 && seeking.every((frame) => frame.time === 5), 'slow seek: held at the sought time while the soundtrack seeks');
    const analysed = analyse(frames, { settle: 0 });
    assert.equal(analysed.back, 0, 'slow seek: no frame goes back');
    const tail = frames.filter((frame) => frame.stamp >= frames.at(-1).stamp - 500);
    assert(excess(tail) <= 0, `slow seek: in sync afterwards (${excess(tail)} s beyond the bound)`);
    result.slowSeek = { frames: frames.length, heldFrames: seeking.length };
  }

  // Two long stalls (2 s each) in one playback: the picture runs on with the frames, and each
  // time the soundtrack comes back far behind it is moved to the picture, the second time too.
  await seek(page, 6);
  await page.waitForTimeout(600);
  await writesOf(page);
  result.longStalls = [];
  for (const round of [1, 2]) {
    await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.stall(); });
    await page.waitForTimeout(2000);
    await page.evaluate(() => window.fakeAudio.resume());
    await page.waitForTimeout(2500);
    const frames = await take(page), moved = await writesOf(page);
    assert.equal(analyse(frames, { settle: 0 }).back, 0, `long stall ${round}: no frame goes back`);
    assert.equal(moved.length, 1, `long stall ${round}: the soundtrack is moved once (${JSON.stringify(moved)})`);
    assert(near(moved[0].value, moved[0].shown + offset), `long stall ${round}: to the shown time plus the offset`);
    const tail = frames.filter((frame) => frame.stamp >= frames.at(-1).stamp - 500);
    assert(excess(tail) <= 0, `long stall ${round}: in sync again (${excess(tail)} s beyond the bound)`);
    result.longStalls.push({ frames: frames.length, movedTo: moved[0].value, tailMaxOffsetMs: +(Math.max(...tail.map((frame) => Math.abs(frame.time - frame.truth))) * 1000).toFixed(1) });
  }

  // A 2 s stall whose realignment lands in data not loaded yet (a soundtrack fetched by range
  // requests on a phone): after the write the soundtrack seeks, then loads for 2.5 s (readyState 1,
  // the position held). The picture waits at the realigned time while it loads, as at a start,
  // and follows the soundtrack once it plays (it is not given up on and left behind).
  {
    await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.stall(); });
    await page.waitForTimeout(2000);
    await page.evaluate(() => { window.fakeAudio.loadAfterWrite = 2500; window.fakeAudio.resume(); });
    await page.waitForTimeout(4300);
    await page.evaluate(() => { window.fakeAudio.loadAfterWrite = 0; });
    const frames = await take(page), moved = await writesOf(page);
    assert.equal(analyse(frames, { settle: 0 }).back, 0, 'loading after the realignment: no frame goes back');
    assert.equal(moved.length, 1, `loading after the realignment: the soundtrack is moved once (${JSON.stringify(moved)})`);
    assert(near(moved[0].value, moved[0].shown + offset), 'loading after the realignment: to the shown time plus the offset');
    const first = frames.findIndex((frame) => frame.time === moved[0].shown);
    const loading = frames.slice(first).filter((frame) => frame.stamp < moved[0].at + 40 + 2500 - 100);
    assert(first >= 0 && loading.length > 10 && loading.every((frame) => frame.time === moved[0].shown),
      `loading after the realignment: held at the realigned time while the soundtrack loads (${loading.length} frames)`);
    const tail = frames.filter((frame) => frame.stamp >= frames.at(-1).stamp - 500);
    assert(excess(tail) <= 0, `loading after the realignment: in sync once it plays (${excess(tail)} s beyond the bound)`);
    result.loadingAfterRealign = { frames: frames.length, heldFrames: loading.length, movedTo: moved[0].value,
      tailMaxOffsetMs: +(Math.max(...tail.map((frame) => Math.abs(frame.time - frame.truth))) * 1000).toFixed(1) };
  }

  // The soundtrack ends before the MV (ended, not paused): the time goes on with the frames.
  await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.endAt = window.fakeAudio.truth() + 0.4; });
  await page.waitForTimeout(1200);
  {
    const frames = await take(page);
    await page.evaluate(() => { window.fakeAudio.endAt = Infinity; });
    let free = 0;
    for (let index = 1; index < frames.length; index++) {
      if (!frames[index - 1].ended || !frames[index].ended) continue;
      const advance = frames[index].time - frames[index - 1].time, interval = (frames[index].stamp - frames[index - 1].stamp) / 1000;
      assert(Math.abs(advance - interval) < 1e-6, `ended: frame advances by its interval (${advance} over ${interval})`);
      free++;
    }
    assert(free > 20, `frames after the end (${free})`);
    result.ended = { frames: free };
  }
  await pause(page);
  await writesOf(page);

  // A soundtrack still loading when play starts (1.5 s, as WKWebView fetches it on play()): the
  // picture waits at the paused time while it loads and the soundtrack is not moved.
  {
    const pausedAt = await page.evaluate(() => { window.playLog.length = 0; window.fakeAudio.loadMs = 1500; return window.probeCtx.time(); });
    await play(page, 2600);
    const loadUntil = await page.evaluate(() => { window.fakeAudio.loadMs = 0; return window.fakeAudio.loadUntil; });
    const frames = await take(page);
    const loading = frames.filter((frame) => frame.stamp < loadUntil - 100);
    assert(loading.length > 10 && loading.every((frame) => frame.time === pausedAt),
      `late start: held at the paused time while loading (${pausedAt}, ${JSON.stringify(loading.filter((frame) => frame.time !== pausedAt).slice(0, 3))}, ${loading.length})`);
    assert.deepEqual(await writesOf(page), [], 'late start: the soundtrack is not moved');
    const tail = frames.filter((frame) => frame.stamp >= frames.at(-1).stamp - 500);
    assert(excess(tail) <= 0, `late start: in sync once playing (${excess(tail)} s beyond the bound)`);
    result.lateStart = { frames: frames.length, heldFrames: loading.length };
  }
  await pause(page);

  // A soundtrack that fails to load (an error, never playing): not waited for as a loading one;
  // after 1 s the time goes on with the frames.
  {
    await page.evaluate(() => { window.playLog.length = 0; Object.assign(window.fakeAudio, { error: { code: 4 }, loadMs: 1e9 }); });
    await play(page, 2200);
    const frames = await take(page);
    await pause(page);
    await page.evaluate(() => Object.assign(window.fakeAudio, { error: null, loadMs: 0, loadUntil: 0 }));
    const late = frames.filter((frame) => frame.stamp > frames[0].stamp + 1200);
    assert(late.length > 20, `failed soundtrack: frames after 1.2 s (${late.length})`);
    for (let index = 1; index < late.length; index++) {
      const advance = late[index].time - late[index - 1].time, interval = (late[index].stamp - late[index - 1].stamp) / 1000;
      assert(Math.abs(advance - interval) < 1e-6, `failed soundtrack: the time goes on with the frames (${advance} over ${interval})`);
    }
    assert.deepEqual(await writesOf(page), [], 'failed soundtrack: not moved');
    result.failedSoundtrack = { frames: frames.length, freeFrames: late.length };
  }

  // Fixed-step captures are unchanged by all of the above.
  assert.deepEqual(await fixedCapture(page, 4), before, 'the fixed-step capture is the same PNG and scene state');
  result.fixedCapture = before.png.slice(0, 16);

  // Without a soundtrack: exactly the frame clock, as before.
  await importGame(page, gameProject(local, false));
  await page.evaluate(recordFrames);
  await seek(page, 1);
  await play(page, 1200);
  await pause(page);
  const silentFrames = await take(page);
  assert(silentFrames.length > 10);
  for (let index = 1; index < silentFrames.length; index++) {
    const advance = silentFrames[index].time - silentFrames[index - 1].time;
    assert(Math.abs(advance - (silentFrames[index].stamp - silentFrames[index - 1].stamp) / 1000) < 1e-9, 'no soundtrack: time + frame interval');
  }
  assert(silentFrames[0].time >= 1, 'no soundtrack: starts at the sought time');
  result.noSoundtrack = { frames: silentFrames.length };
  assert.deepEqual(errors, []);
  await page.context().close();
  return result;
}

// The real 12035 MV through the editor's own game import (Elichika server root).
async function real(browser) {
  if (!serverRoot) {
    console.log('real 12035 playback skipped (set MV_PLAYBACK_SERVER_ROOT to an Elichika server root)');
    return 'skipped';
  }
  const server = await capture.bootEditor(path.resolve(serverRoot), library, path.join(evidence, 'server-12035.log'));
  const errors = [];
  try {
    const page = await newPage(browser, errors, { width: 960, height: 720 });
    await page.goto(server.url + '/#mv');
    await capture.importOriginal(page, { region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503 }, true);
    await page.waitForFunction(() => window.probeCtx.scene() && !document.getElementById('mv-play').disabled, null, { timeout: 600000 });
    await page.waitForTimeout(1500);
    const exportTimeline = async () => {
      await page.evaluate(() => { document.getElementById('mv-save-result').hidden = true; document.getElementById('mv-save-result').replaceChildren(); });
      await page.locator('#mv-export-timeline').click();
      const link = page.locator('#mv-save-result a');
      await link.waitFor({ timeout: 600000 });
      return fs.readFileSync(await link.getAttribute('title'));
    };
    const exportedBefore = await exportTimeline();
    await page.evaluate(recordFrames);
    const before = await fixedCapture(page, 30, true);
    const project = await page.evaluate(() => JSON.stringify(MVStudio.getState().project));
    const result = await transport(page, '12035', { from: 30, later: 45, earlier: 32, ms: 3000, rawRepeats: false });
    assert.deepEqual(await fixedCapture(page, 30), before, '12035: the fixed-step capture is the same PNG and scene state');
    assert.equal(await page.evaluate(() => JSON.stringify(MVStudio.getState().project)), project, '12035: the project is unchanged');
    const exportedAfter = await exportTimeline();
    assert(exportedAfter.equals(exportedBefore), '12035: the native timeline export is byte-identical');
    assert.deepEqual(errors, []);
    await page.context().close();
    return { ...result, fixedCapture: before.png.slice(0, 16), exportBytes: exportedAfter.length, exportSha: sha(exportedAfter).slice(0, 16) };
  } finally {
    server.child.kill();
  }
}

async function run() {
  let browser, server;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const syntheticResult = await synthetic(browser, server.url);
    const realResult = await real(browser);
    console.log(JSON.stringify({ status: 'PASS', synthetic: syntheticResult, real: realResult }));
  } finally {
    if (browser) await browser.close();
    if (server) server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
    if (ownEvidence && process.exitCode === undefined) fs.rmSync(evidence, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
