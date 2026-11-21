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
  await chooseLocal(page, modded, modelName);
  await page.waitForFunction(() => !!MVStudio.getState().project?.stage?.glb);
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
    performers: [{ id: 'actor-1', label: 'Actor 1', glb: local.stage.glb, transform: { position: [0, 0, 0] } }],
    soundtrack: soundtrack.soundtrack,
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34, mvOnly: true },
    tracks: [{ id: 'camera', label: 'Camera', kind: 'camera', binding: 'MainCamera', events: [{ id: 'sample-clip',
      label: 'Opening camera', start: 2, duration: 8, values: { fov: 40, fixed: 1 }, editableValues: ['fov'] }] }],
    quality: { mode: 1, modes: [{ id: 1, label: 'Medium', values: { shadow: true } }],
      options: [{ key: 'shadow', label: 'Shadow', type: 'boolean' }], values: { shadow: true } },
  };
  await page.route('**/api/mv-studio/catalog?*', route => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 12, title: 'MV Studio sample', mvOnly: true, variants: [{ id: 34, label: 'MV' }] }],
  } }));
  let request;
  await page.route('**/api/mv-studio/game?*', route => {
    request = route.request().postDataJSON();
    return route.fulfill({ json: gameProject });
  });
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').waitFor({ state: 'attached' });
  assert.match(await page.locator('#mv-game-song option').textContent(), /MV 전용/);
  await page.locator('#mv-game-load').click();
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false });
  await page.locator('#mv-performers summary').click();
  const position = page.locator('[data-mv-performer-axis=X]');
  await position.fill('1.25'); await position.press('Tab');
  await page.locator('#mv-performers summary').click();
  await page.locator('#mv-soundtrack summary').click();
  const soundtrackOffset = page.locator('#mv-soundtrack-offset');
  await soundtrackOffset.fill('0.75'); await soundtrackOffset.press('Tab');
  await page.locator('#mv-soundtrack summary').click();
  await page.locator('.mv-clip[data-event=sample-clip]').click();
  assert.equal(await page.evaluate(() => MVStudio.getState().time), 2);
  assert.equal(await page.locator('[data-mv-field=fixed]').count(), 0);
  const start = page.locator('[data-mv-field=start]');
  await start.fill('7.5');
  await start.press('Tab');
  assert.equal(await page.evaluate(() => MVStudio.getState().time), 7.5);
  const fov = page.locator('[data-mv-field=fov]');
  await fov.fill('60');
  await fov.press('Tab');
  await page.locator('#mv-quality summary').click();
  const shadow = page.locator('[data-mv-quality=shadow]');
  await shadow.uncheck();
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
  assert.equal(restored.tracks[0].events[0].values.fov, 60);
  assert.equal(restored.quality.values.shadow, false);
  assert.deepEqual(restored.performers[0].transform.position, [1.25, 0, 0]);
  assert.equal(restored.soundtrack.offset, .75);
  await page.screenshot({ path: path.join(evidence, 'mv-landscape-ko.png') });
  await registrationControls(page);
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
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.processHandle.kill();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
