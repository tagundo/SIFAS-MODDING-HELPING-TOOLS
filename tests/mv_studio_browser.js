/* Shared MV workbench, a real local GLB/ZIP round-trip and a synthetic game catalog. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-studio-library-'));
const modded = path.join(library, 'modded');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-studio-browser-'));
const modelName = 'stage-fixture.glb';
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, modelName), fixture().glb);
fs.writeFileSync(path.join(modded, 'android-timeline.unity'), 'selection fixture');
fs.writeFileSync(path.join(modded, 'chart.json'), '{}');
fs.writeFileSync(path.join(modded, 'custom.acb'), 'selection fixture');
fs.writeFileSync(path.join(modded, 'custom.awb'), 'selection fixture');
const wav = Buffer.alloc(44 + 160000);
wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
fs.writeFileSync(path.join(modded, 'soundtrack.wav'), wav);

async function startServer() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const processLog = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const processHandle = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)], {
    cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', processLog, processLog],
  });
  fs.closeSync(processLog);
  const url = 'http://127.0.0.1:' + port;
  for (let count = 0; count < 100; count++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { processHandle, url }; } catch (_) {}
    if (processHandle.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  processHandle.kill();
  throw new Error('Isolated workbench did not start');
}

async function chooseLocal(page, folder, file) {
  await page.locator('#mv-open').click();
  await chooseFile(page, folder, file);
}

async function chooseFile(page, folder, file) {
  await page.waitForFunction(expected => document.getElementById('picker-crumb').textContent === expected, folder);
  await page.locator('#picker-entries li').filter({ hasText: file }).click();
}

async function registrationControls(page) {
  let registration, attachment;
  await page.route('**/api/mv-studio/register?*', route => {
    registration = route.request().postDataJSON();
    return route.fulfill({ json: { liveId: 90, title: 'MV copy', mvOnly: true, restartRequired: true } });
  });
  await page.route('**/api/mv-studio/chart-templates?*', route => route.fulfill({ json: {
    templates: [{ id: 765, difficultyType: 30, label: '상급' }],
  } }));
  await page.route('**/api/mv-studio/charts?*', route => {
    attachment = route.request().postDataJSON();
    return route.fulfill({ json: { liveId: 90, title: 'MV copy', mvOnly: false, restartRequired: true } });
  });
  await page.locator('#mv-registration summary').click();
  await page.locator('#mv-registration-title').fill('MV copy');
  await page.locator('[data-mv-register-timeline=android]').click();
  await chooseFile(page, modded, 'android-timeline.unity');
  await page.locator('[data-mv-register-audio=awb]').click();
  await chooseFile(page, modded, 'custom.awb');
  assert(await page.locator('#mv-register').isDisabled());
  await page.locator('[data-mv-register-audio=acb]').click();
  await chooseFile(page, modded, 'custom.acb');
  await page.locator('#mv-register').click();
  await page.waitForFunction(() => document.getElementById('mv-status').textContent.includes('재시작'));
  assert.deepEqual(registration, { region: 'gl', sourceLiveId: 12, assetId: 34, title: 'MV copy',
    timelinePaths: { android: path.join(modded, 'android-timeline.unity') },
    audioAcbPath: path.join(modded, 'custom.acb'), audioAwbPath: path.join(modded, 'custom.awb') });
  await page.locator('#mv-chart-templates').click();
  assert.equal(await page.locator('#mv-chart-template').inputValue(), '765');
  await page.locator('#mv-chart-file').click();
  await chooseFile(page, modded, 'chart.json');
  await page.locator('#mv-attach-chart').click();
  await page.locator('#mv-chart-templates').waitFor();
  assert.deepEqual(attachment, { region: 'gl', liveId: 90, charts: { 30: {
    path: path.join(modded, 'chart.json'), template_difficulty_id: 765,
  } } });
}

async function localAndGame(page, url) {
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  let releaseModel;
  const waitingForModel = new Promise(resolve => { releaseModel = resolve; });
  const delayedModel = async route => { await waitingForModel; await route.continue(); };
  await page.route('**/api/mv-studio/media/*.glb', delayedModel);
  try {
    await chooseLocal(page, modded, modelName);
    await page.waitForFunction(() => !!MVStudio.getState().project?.stage?.glb);
    assert.equal(await page.locator('#mv-project-title').textContent(), 'stage-fixture');
    assert(await page.locator('#mv-timeline-scroll').isVisible());
    assert(await page.locator('#mv-save').isDisabled());
    assert(!(await page.locator('#mv-camera-mode').isVisible()));
  } finally { releaseModel(); }
  await page.locator('#mv-camera-mode').waitFor();
  await page.unroute('**/api/mv-studio/media/*.glb', delayedModel);
  const local = await page.evaluate(() => MVStudio.getState().project);
  assert(local.assets.find(asset => asset.kind === 'stage'));
  assert(await page.locator('#mv-scene canvas').isVisible());
  assert(await page.locator('#mv-camera-mode').isVisible());
  await page.locator('#mv-camera-mode').selectOption('orbit');
  await page.locator('#mv-frame-scene').click();
  const soundtrack = await page.request.post(url + '/api/mv-studio/asset', {
    data: { path: path.join(modded, 'soundtrack.wav'), kind: 'audio' },
  }).then(response => response.json());
  assert(soundtrack.soundtrack.url);

  const gameProject = { ...local, name: 'MV Studio sample', duration: 35,
    performers: [{ id: 'actor-1', label: 'Actor 1', position: 1, glb: local.stage.glb, transform: { position: [0, 0, 0] },
      costumeId: 51, viewStatus: 1, suitSource: 'memberInit',
      costumes: [{ id: 51, name: 'Winter uniform', asset: 'a' }, { id: 52, name: 'Stage suit', asset: 'b' },
        { id: 52, name: 'Stage suit', asset: 'c', viewStatus: 2 }] }],
    soundtrack: soundtrack.soundtrack,
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34, mvOnly: true },
    tracks: [{ id: 'camera', label: 'Camera', kind: 'camera', binding: 'MainCamera', events: [{ id: 'sample-clip',
      label: 'Opening camera', start: 2, duration: 8, values: { fov: 40, fixed: 1 }, editableValues: ['fov'] }] },
    { id: 'light', label: 'Light', kind: 'lighting', events: [{ id: 'light-clip', label: 'Opening light',
      start: 0, duration: 4, values: {} }] }],
    quality: { mode: 1, modes: [{ id: 1, label: 'Medium', values: { shadow: true } }],
      options: [{ key: 'shadow', label: 'Shadow', type: 'boolean' }], values: { shadow: true } },
  };
  let catalogRequests = 0;
  await page.route('**/api/mv-studio/catalog?*', route => {
    catalogRequests++;
    return route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
      songs: [{ id: 12, title: 'MV Studio sample', mvOnly: true, variants: [{ id: 34, label: 'MV' }] },
        { id: 13, title: '다른 노래', variants: [{ id: 35, label: '별빛 무대' }] }],
    } });
  });
  let request;
  await page.route('**/api/mv-studio/game-stream?*', route => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', route => {
    request = route.request().postDataJSON();
    return route.fulfill({ json: gameProject });
  });
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  const search = page.locator('#mv-game-search');
  await search.fill('별빛');
  assert.equal(await page.locator('#mv-game-song').inputValue(), '13');
  await search.fill('ｍｖ studio');
  assert.equal(await page.locator('#mv-game-song').inputValue(), '12');
  assert.match(await page.locator('#mv-game-song option').textContent(), /MV 전용/);
  await page.locator('#mv-game-load').click();
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.equal(catalogRequests, 1);
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false });
  await page.locator('#mv-performers summary').click();
  // The costume override re-imports the game MV with the suit and m_suit_view model pinned.
  const costume = page.locator('#mv-performer-costume');
  assert.equal(await costume.inputValue(), '0');
  assert.deepEqual(await costume.locator('option').allTextContents(),
    ['Winter uniform (51)', 'Stage suit (52)', 'Stage suit (52 · 뷰 2)']);
  request = null;
  await costume.selectOption('2');
  await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false,
    costumes: { 1: { suit: 52, viewStatus: 2 } } });
  // The deck tab and player choice travel with the next picker import.
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  assert(await page.locator('#mv-game-player-field').isHidden(), 'No player database, no player choice');
  await page.locator('#mv-game-deck').selectOption('1');
  request = null;
  await page.locator('#mv-game-load').click();
  await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false, deck: { deckType: 1 } });
  if (!(await page.locator('#mv-performer-costume').isVisible())) await page.locator('#mv-performers summary').click();
  const position = page.locator('[data-mv-performer-axis=X]');
  await position.fill('1.25'); await position.press('Tab');
  await page.locator('#mv-performers summary').click();
  await page.locator('#mv-soundtrack summary').click();
  const soundtrackOffset = page.locator('#mv-soundtrack-offset');
  await soundtrackOffset.fill('0.75'); await soundtrackOffset.press('Tab');
  await page.locator('#mv-soundtrack summary').click();
  const scrubbedTimes = await page.evaluate(async () => {
    const range = document.getElementById('mv-seek');
    const scrub = value => {
      range.value = value;
      range.dispatchEvent(new Event('input', { bubbles: true }));
      return MVStudio.getState().time;
    };
    const inputs = [scrub(1.25), scrub(4.75)];
    range.dispatchEvent(new Event('change', { bubbles: true }));
    const committed = MVStudio.getState().time;
    scrub(30);
    document.querySelector('.mv-clip[data-event=sample-clip]').click();
    await new Promise(resolve => requestAnimationFrame(resolve));
    return { inputs, committed, selected: MVStudio.getState().time };
  });
  assert.deepEqual(scrubbedTimes, { inputs: [1.25, 4.75], committed: 4.75, selected: 2 });
  assert.equal(await page.locator('[data-mv-field=fixed]').count(), 0);
  const untouched = await page.locator('.mv-clip[data-event=light-clip]').elementHandle();
  const clip = page.locator('.mv-clip[data-event=sample-clip]');
  const originalWidth = await clip.evaluate(element => element.style.width);
  const start = page.locator('[data-mv-field=start]');
  await start.fill('7.5');
  await start.press('Tab');
  assert.equal(await page.evaluate(() => MVStudio.getState().time), 7.5);
  const duration = page.locator('[data-mv-field=duration]');
  await duration.fill('11.5');
  await duration.press('Tab');
  assert(await untouched.evaluate(element => element.isConnected));
  assert.notEqual(await clip.evaluate(element => element.style.width), originalWidth);
  assert.equal(await clip.getAttribute('aria-pressed'), 'true');
  const fov = page.locator('[data-mv-field=fov]');
  await fov.fill('60');
  await fov.press('Tab');
  await page.locator('#mv-quality summary').click();
  const shadow = page.locator('[data-mv-quality=shadow]');
  await shadow.uncheck();
  // The device option is offered off by default and is not saved with the project.
  const refresh = page.locator('#mv-refresh-rate-mode');
  assert.equal(await refresh.inputValue(), '0');
  assert.deepEqual(await refresh.locator('option').evaluateAll(options => options.map(option => option.value)), ['0', '60', '90', '120']);
  await refresh.selectOption('120');
  assert.equal(await page.locator('#mv-refresh-rate-mode').inputValue(), '120');
  await page.locator('#mv-refresh-rate-mode').selectOption('0');
  await page.locator('#mv-panel-menu summary').click();
  await page.locator('[data-mv-panel-option=quality]').uncheck();
  assert(!(await shadow.isVisible()));
  await page.locator('[data-mv-panel-option=quality]').check();
  assert(await shadow.isVisible());
  await page.locator('#mv-panel-menu summary').click();
  await page.locator('#mv-play').click();
  await page.waitForFunction(() => MVStudio.getState().time > 7.55);
  await page.locator('[data-tab=tools]').click();
  assert.equal(await page.evaluate(() => MVStudio.getState().playing), false);
  await page.locator('[data-tab=mv]').click();

  await page.locator('#mv-save').click();
  const link = page.locator('#mv-save-result a');
  await link.waitFor();
  const saved = await link.getAttribute('title');
  assert.match(saved, /\.mv-project\.zip$/);
  assert(await page.request.get(await link.getAttribute('href')).then(response => response.ok()));
  const restored = await page.request.post(url + '/api/mv-studio/open', { data: { path: saved } }).then(response => response.json());
  assert.equal(restored.tracks[0].events[0].start, 7.5);
  assert.equal(restored.tracks[0].events[0].duration, 11.5);
  assert.equal(restored.tracks[0].events[0].values.fov, 60);
  assert.equal(restored.quality.values.shadow, false);
  assert.deepEqual(restored.performers[0].transform.position, [1.25, 0, 0]);
  assert.equal(restored.soundtrack.offset, .75);
  await page.screenshot({ path: path.join(evidence, 'mv-landscape-ko.png') });
  await registrationControls(page);
}

async function timelineResize(page) {
  const grip = page.getByRole('separator', { name: '타임라인 높이' });
  const scroll = page.locator('#mv-timeline-scroll');
  const timeline = page.locator('#mv-timeline-grid');
  const clip = await timeline.locator('.mv-clip').first().elementHandle();
  const height = () => scroll.evaluate(element => element.clientHeight);
  const positions = () => page.evaluate(() => {
    const bounds = selector => document.querySelector(selector).getBoundingClientRect();
    return { top: bounds('.mv-timeline').top, bottom: bounds('.mv-timeline').bottom,
      grip: bounds('#mv-timeline-resizer').top, tools: bounds('.mv-timeline-toolbar').top,
      preview: bounds('.mv-preview').height, workspaceBottom: bounds('#mv-workspace').bottom,
      viewportBottom: innerHeight - parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom) };
  });
  const near = (actual, expected) => assert(Math.abs(actual - expected) <= 1, `${actual} differs from ${expected}`);
  const before = await positions();
  const initial = await height();
  assert(initial > 62);
  near(before.bottom, before.workspaceBottom);
  near(before.bottom, before.viewportBottom);
  assert(before.grip < before.tools);
  assert.equal(await grip.getAttribute('aria-orientation'), 'horizontal');
  const rect = await grip.boundingBox();
  const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y - 24, { steps: 8 });
  await page.mouse.up();
  const dragged = initial + 24;
  assert.equal(await height(), dragged);
  const afterDrag = await positions();
  near(afterDrag.bottom, before.bottom);
  near(afterDrag.top, before.top - 24);
  near(afterDrag.grip, before.grip - 24);
  near(afterDrag.preview, before.preview - 24);
  assert.equal(await grip.getAttribute('aria-valuenow'), String(dragged));
  assert(await clip.evaluate(element => element.isConnected));
  await grip.press('ArrowUp');
  assert.equal(await height(), dragged + 16);
  await grip.press('Shift+ArrowDown');
  assert.equal(await height(), Math.max(62, dragged + 16 - 48));
  await grip.press('Shift+ArrowDown');
  assert.equal(await height(), 62);
  near((await positions()).bottom, before.bottom);
  assert(await clip.evaluate(element => element.isConnected));

  await page.locator('#mv-zoom').selectOption('96');
  await scroll.hover();
  await page.mouse.wheel(120, 120);
  await page.waitForFunction(() => {
    const pane = document.getElementById('mv-timeline-scroll');
    return pane.scrollTop > 0 && pane.scrollLeft > 0;
  });
  await grip.press('End');
  const wide = Number(await grip.getAttribute('aria-valuemax'));
  assert.equal(await height(), wide);
  const expanded = await positions();
  near(expanded.bottom, before.bottom);
  assert(expanded.preview >= 143);
  await page.reload();
  await grip.waitFor();
  assert.equal(await height(), wide);

  await page.setViewportSize({ width: 408, height: 600 });
  await page.waitForFunction(wideHeight => {
    const grip = document.getElementById('mv-timeline-resizer');
    const height = document.getElementById('mv-timeline-scroll').clientHeight;
    return height < wideHeight && height === Number(grip.getAttribute('aria-valuemax')) &&
      height === Number(grip.getAttribute('aria-valuenow'));
  }, wide);
  const portrait = await positions();
  near(portrait.bottom, portrait.workspaceBottom);
  near(portrait.bottom, portrait.viewportBottom);
  assert(portrait.preview >= 107);
  await page.setViewportSize({ width: 1180, height: 820 });
  await page.waitForFunction(expected => document.getElementById('mv-timeline-scroll').clientHeight === expected, wide);
  await grip.press('Home');
  assert.equal(await height(), 62);
  assert.equal(await scroll.evaluate(element => element.style.getPropertyValue('--mv-timeline-height')), '');
}

async function run() {
  const server = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ locale: 'ko', viewport: { width: 1180, height: 820 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await localAndGame(page, server.url);
    const layout = await page.locator('.mv-workspace').evaluate(element => {
      const rect = selector => element.querySelector(selector).getBoundingClientRect();
      const stage = rect('.mv-preview'), inspector = rect('.mv-inspector'), timeline = rect('.mv-timeline');
      return stage.right < inspector.left && stage.top === inspector.top && timeline.top > stage.bottom &&
        timeline.left === stage.left && timeline.right === inspector.right;
    });
    assert(layout, 'The timeline spans the preview and inspector columns');
    await timelineResize(page);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.processHandle.kill();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
