/* Actual MV editor UI with controlled chunked local import and a canvas probe. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

function attachProbe() {
  const probe = window.mvStreamProbe = { requests: [], prepared: [], loaded: [], shown: [], cancelled: 0, mode: '404' };
  const fetchActual = window.fetch;
  window.fetch = (url, options) => {
    if (!String(url).startsWith('/api/mv-studio/game-stream?')) return fetchActual(url, options);
    probe.requests.push({ body: JSON.parse(options.body), credentials: options.credentials, accept: options.headers.Accept });
    probe.signal = options.signal;
    if (probe.mode === '404') return Promise.resolve(new Response('{}', { status: 404 }));
    if (probe.mode === 'json') return Promise.resolve(new Response('{}', { headers: { 'Content-Type': 'application/json' } }));
    const body = new ReadableStream({ start(writer) { probe.writer = writer; } });
    return Promise.resolve(new Response(body, { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } }));
  };
  const create = document.createElement.bind(document);
  document.createElement = function (name, ...options) {
    const element = create(name, ...options);
    if (name === 'audio' && !probe.audio) probe.audio = element;
    return element;
  };
  Object.defineProperty(window, 'MVStudioScene', {
    get() {
      return { create(mount, options) {
        const canvas = create('canvas');
        mount.append(canvas);
        probe.shown.push(options.visible);
        return {
          setVisible(value) { probe.shown.push(value); },
          prepareStage(value) {
            probe.prepared.push(value);
            return new Promise(resolve => { probe.stageReady = resolve; });
          },
          cancelStagePreparation() { probe.cancelled++; },
          load(value, choices) { probe.loaded.push({ value: value.name, reuseStage: choices.reuseStage, visible: probe.shown.at(-1) }); },
          seek() {}, setPlaying() {}, resize() {}, flushSeekDraw() {}, dispose() { probe.disposed = true; }
        };
      }};
    },
    set() {}
  });
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

const model = (key) => '/api/mv-studio/media/' + key.repeat(32) + '.glb';
const audio = (key) => '/api/mv-studio/media/' + key.repeat(32) + '.wav';
function project(name, key) {
  return { version: 1, name, token: key.repeat(32), duration: 16, stage: { glb: model(key) }, soundtrack: { url: audio(key) },
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34 },
    tracks: [], assets: [], performers: [], warnings: [], quality: {} };
}
const progress = { type: 'stage', preview: { stage: { glb: model('b'), label: '무대 🎵' }, assets: [], tracks: [], quality: {}, duration: 16 } };

async function sendChunks(page, event, finish = false) {
  await page.evaluate(({ event, finish }) => {
    const bytes = new TextEncoder().encode(JSON.stringify(event) + '\n');
    const multibyte = bytes.findIndex(value => value > 127);
    const firstCut = multibyte < 0 ? 3 : multibyte + 1;
    const writer = mvStreamProbe.writer;
    writer.enqueue(bytes.subarray(0, firstCut));
    writer.enqueue(bytes.subarray(firstCut, firstCut + 1));
    writer.enqueue(bytes.subarray(firstCut + 1));
    if (finish) writer.close();
  }, { event, finish });
}

async function run() {
  const library = fs.mkdtempSync(path.join(os.tmpdir(), 'elichika-mv-stream-browser-'));
  const server = await boot(library);
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
    const page = await browser.newPage();
    const errors = [];
    let legacy = 0;
    await page.addInitScript(attachProbe);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/mv-studio/catalog?*', route => route.fulfill({ json: {
      region: 'gl', platform: 'android', regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
      songs: [{ id: 12, title: 'Fixture song', variants: [{ id: 34, label: 'MV' }] }]
    } }));
    await page.route('**/api/mv-studio/game?*', route => { legacy++; return route.fulfill({ json: project('Legacy fixture', 'a') }); });
    await page.route('**/api/mv-studio/media/*.wav', route => route.fulfill({ status: 404 }));
    await page.goto(server.url + '/#mv');
    await page.waitForFunction(() => MVStudio.getState().visible);
    const begin = async (mode) => {
      await page.evaluate(mode => { mvStreamProbe.mode = mode; mvStreamProbe.writer = null; }, mode);
      await page.locator('#mv-import-game').click();
      await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
      await page.locator('#mv-game-load').click();
      if (mode === 'stream') await page.waitForFunction(() => !!mvStreamProbe.writer);
    };
    const settled = () => page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
    const snapshot = () => page.evaluate(() => ({
      name: MVStudio.getState().project?.name, time: MVStudio.getState().time, url: mvStreamProbe.audio.src,
      prepared: mvStreamProbe.prepared.map(p => p.stage.label), loaded: mvStreamProbe.loaded,
      cancelled: mvStreamProbe.cancelled, shown: mvStreamProbe.shown.at(-1), aborted: mvStreamProbe.signal?.aborted,
    }));

    await begin('404');
    await settled();
    assert.equal(legacy, 1);
    assert.equal((await snapshot()).name, 'Legacy fixture');
    await page.locator('#mv-seek').evaluate(slider => {
      slider.value = '3.5';
      slider.dispatchEvent(new Event('input', { bubbles: true }));
    });

    await begin('stream');
    await sendChunks(page, progress);
    await page.waitForFunction(() => mvStreamProbe.prepared.length === 1);
    await page.evaluate(() => mvStreamProbe.stageReady(true));
    await page.waitForFunction(() => document.querySelector('#mv-empty-preview').hidden);
    let state = await snapshot();
    assert.deepEqual(state.prepared, ['무대 🎵']);
    assert.equal(state.name, 'Legacy fixture');
    assert.equal(state.time, 3.5);
    assert.equal(state.url, server.url + audio('a'));
    for (const id of ['mv-play', 'mv-rewind', 'mv-seek', 'mv-save']) assert(await page.locator('#' + id).isDisabled());
    assert(await page.locator('#mv-inspector').evaluate(element => element.inert));
    await sendChunks(page, { type: 'complete', project: project('Gradual fixture', 'b') });
    assert.equal((await snapshot()).name, 'Legacy fixture');
    await page.evaluate(() => mvStreamProbe.writer.close());
    await settled();
    state = await snapshot();
    assert.equal(state.name, 'Gradual fixture');
    assert.equal(state.url, server.url + audio('b'));
    assert.deepEqual(state.loaded.at(-1), { value: 'Gradual fixture', reuseStage: true, visible: true });
    assert(!(await page.locator('#mv-inspector').evaluate(element => element.inert)));

    // A terminal failure restores the canonical scene and leaves audio alone.
    await begin('stream');
    await sendChunks(page, progress);
    await page.waitForFunction(() => mvStreamProbe.prepared.length === 2);
    await page.evaluate(() => mvStreamProbe.stageReady(true));
    await sendChunks(page, { type: 'error', error: 'Synthetic stage import failure' }, true);
    await settled();
    state = await snapshot();
    assert.equal(state.cancelled, 1);
    assert.equal(state.name, 'Gradual fixture');
    assert.equal(state.url, server.url + audio('b'));
    assert.match(await page.locator('#mv-status').textContent(), /Synthetic stage import failure/);

    // Leaving the tab hides draws and lets the import finish in the background.
    await begin('stream');
    await page.evaluate(() => MVStudio.setVisible(false));
    await sendChunks(page, progress);
    await sendChunks(page, { type: 'complete', project: project('Hidden completion', 'c') }, true);
    await settled();
    state = await snapshot();
    assert.equal(state.name, 'Hidden completion');
    assert.equal(state.aborted, false);
    assert.equal(state.prepared.length, 2);
    assert.deepEqual(state.loaded.at(-1), { value: 'Hidden completion', reuseStage: false, visible: false });
    await page.evaluate(() => MVStudio.setVisible(true));
    assert.equal((await snapshot()).shown, true);

    // The definitive project can take over while preview decoding is unfinished.
    await begin('stream');
    await sendChunks(page, progress);
    await page.waitForFunction(() => mvStreamProbe.prepared.length === 3);
    await sendChunks(page, { type: 'complete', project: project('Fast completion', 'e') }, true);
    await settled();
    state = await snapshot();
    assert.deepEqual(state.loaded.at(-1), { value: 'Fast completion', reuseStage: true, visible: true });
    await page.evaluate(() => mvStreamProbe.stageReady(true));
    assert.equal((await snapshot()).name, 'Fast completion');
    assert.equal((await snapshot()).cancelled, 1);

    // Unsupported streaming API falls back before requesting the new endpoint.
    const beforeUnsupported = await page.evaluate(() => {
      mvStreamProbe.savedDecoder = window.TextDecoder;
      window.TextDecoder = undefined;
      return mvStreamProbe.requests.length;
    });
    await begin('404');
    await settled();
    assert.equal(await page.evaluate(() => mvStreamProbe.requests.length), beforeUnsupported);
    await page.evaluate(() => { window.TextDecoder = mvStreamProbe.savedDecoder; });
    assert.equal(legacy, 2);

    await begin('json');
    await settled();
    assert.equal(legacy, 2, 'a claimed but invalid response must not start another import');

    // Actual destruction discards partial work and ignores a late terminal.
    await begin('stream');
    await sendChunks(page, progress);
    await page.waitForFunction(() => mvStreamProbe.prepared.length === 4);
    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })));
    await page.evaluate(() => mvStreamProbe.stageReady(true));
    await sendChunks(page, { type: 'complete', project: project('Stale completion', 'd') }, true);
    await settled();
    state = await snapshot();
    assert.equal(state.aborted, true);
    assert.equal(state.cancelled, 2);
    assert.equal(state.name, 'Legacy fixture');
    assert.equal(state.url, server.url + audio('a'));
    assert.equal(legacy, 2);
    assert.deepEqual(errors, []);
    const wire = await page.evaluate(() => mvStreamProbe.requests[0]);
    assert.deepEqual(wire, { body: { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false },
      credentials: 'same-origin', accept: 'application/x-ndjson' });
    console.log('PASS: MV stream chunks, progress isolation, failure rollback, hidden completion, preflight fallback and stale cancellation');
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(library, { recursive: true, force: true });
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
