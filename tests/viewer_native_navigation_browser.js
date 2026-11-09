/* Real shared editor/gallery, with an explicit native navigation host stub.
 * Native Swift WebView identity is separately checked by app smoke on macOS. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'native-navigation-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'native-navigation-'));
fs.mkdirSync(evidence, { recursive: true });
const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true });
const source = path.join(models, 'neutral.unity');
const original = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, original);
const galleryBundle = path.join(models, 'gallery-costume.unity');
const generated = spawnSync(process.env.VIEWER_PYTHON || 'python3', ['-c',
  'import sys;from pathlib import Path;from viewer_scene_fixture import bundle_fixture;Path(sys.argv[1]).write_bytes(bundle_fixture())', galleryBundle],
  { cwd: __dirname, encoding: 'utf8' });
assert.equal(generated.status, 0, generated.stderr);
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 100; i++) { try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw new Error('Server did not start');
}
async function hostNavigate(page, surface) {
  await page.evaluate(surface => {
    window.__nativeSurface = surface; ElichikaDesktop.editorSurface = surface;
    ElichikaPlatform.perform(surface === 'viewer' ? 'showViewer' : 'showTools');
  }, surface);
  await page.waitForFunction(surface => document.getElementById('tab-' + surface).classList.contains('active'), surface);
}
async function retainedState(page) {
  return page.evaluate(() => { const state = ModelViewer.getState(); return { id: state.modelId, paths: state.loadedPaths,
    camera: state.camera, authoring: ModelViewer.getAuthoringState(), time: state.rig.time,
    clip: state.rig.selectedClip, preferences: localStorage.getItem('elichika.panels.viewer.v1') }; });
}
async function openParents(page, selector) {
  await page.locator(selector).evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
}
async function run() {
  let server, browser;
  const report = { status: 'RUNNING', scope: 'Real HTTP/Unity/WebGL/gallery and serialized save in Chromium with native message/navigation stub; not native Swift execution', cases: [] };
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
    await context.addInitScript(({ source, models }) => {
      localStorage.setItem('sifas_lang', 'ko'); window.__nativeMessages = []; window.__nativeSurface = 'tools';
      window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'ko', editorSurface: 'tools',
        capabilities: ['openFiles', 'chooseDirectory', 'fullscreen', 'editorNavigation', 'setPanelSettings'] };
      window.webkit = { messageHandlers: { elichika: { postMessage(message) {
        __nativeMessages.push(message); let result = {};
        if (message.action === 'openFiles') result = { paths: [source] };
        if (message.action === 'chooseDirectory') result = { path: models };
        if (message.action === 'setEditorSurface') { __nativeSurface = message.editorSurface; result = { editorSurface: message.editorSurface }; }
        if (message.action === 'setFullscreen') result = { active: message.enabled, settled: true };
        queueMicrotask(() => { ElichikaPlatform.receive({ id: message.id, result });
          if (message.action === 'setFullscreen') window.dispatchEvent(new CustomEvent('elichika-native-fullscreen-changed', { detail: result })); });
      } } } };
    }, { source, models });
    const page = await context.newPage(), errors = [], prepares = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.url().endsWith('/api/viewer/prepare')) prepares.push(request.postData()); });
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelector('#tool-list [data-id="texture_previews"]') && ElichikaPlatform.info().editorNavigation);
    assert(!await page.locator('body > header').isVisible(), 'Native sidebar replaces duplicate web header');
    assert.equal(await page.locator('.tab').count(), 2);
    assert.equal(await page.locator('.tab[data-tab=gallery]').count(), 0);
    assert(await page.locator('#tab-tools').isVisible());
    await page.locator('#tool-list [data-id=texture_previews]').click();
    assert(await page.locator('#tool-gallery-panel').isVisible());
    assert(await page.locator('#tool-list').isVisible(), 'Gallery stays inside the tool workspace');
    await page.locator('#gallery-browse').click(); await page.waitForFunction(() => document.getElementById('gallery-path').value); await page.locator('#gallery-load').click();
    await page.locator('#gallery-grid .gcard').waitFor();
    await page.evaluate(() => { window.__galleryIdentity = document.getElementById('tool-gallery-panel'); window.__galleryImage = document.querySelector('#gallery-grid img'); });
    const galleryPath = await page.locator('#gallery-path').inputValue();
    await page.locator('#tool-list [data-id=breast_size]').click();
    assert(!await page.locator('#tool-gallery-panel').isVisible());
    assert(await page.locator('#tool-form').isVisible());
    await page.locator('#tool-list [data-id=texture_previews]').click();
    assert.equal(await page.locator('#gallery-path').inputValue(), galleryPath);
    assert(await page.evaluate(() => document.getElementById('tool-gallery-panel') === __galleryIdentity && document.querySelector('#gallery-grid img') === __galleryImage), 'Switching tools retains gallery state and nodes');
    await page.evaluate(() => { document.getElementById('viewer-auto-face').checked = false; });
    await page.keyboard.press('Meta+o');
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    assert.equal(await page.evaluate(() => __nativeSurface), 'viewer', 'Open routes to the native model sidebar');
    await openParents(page, '#viewer-breast-preset');
    const preset = await page.locator('#viewer-breast-preset option').evaluateAll(options => options.find(option => option.value !== 'loaded').value);
    await page.locator('#viewer-breast-preset').selectOption(preset);
    assert((await page.evaluate(() => ModelViewer.getAuthoringState().edits)).length);
    await page.locator('#viewer-panel-settings').click();
    await page.locator('#viewer-panel-settings-dialog [data-panel-id=viewer-display-options] input').uncheck();
    await page.keyboard.press('Escape');
    await openParents(page, '#viewer-motion');
    const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
    await page.locator('#viewer-motion').selectOption(clip);
    await page.locator('#viewer-time').evaluate(element => { element.value = '0.25'; element.dispatchEvent(new Event('input', { bubbles: true })); });
    const before = await retainedState(page), prepareCount = prepares.length;
    for (let i = 0; i < 3; i++) {
      await hostNavigate(page, 'tools');
      assert(!await page.evaluate(() => ModelViewer.getState().visible));
      assert(await page.locator('#tool-gallery-panel').isVisible());
      await hostNavigate(page, 'viewer');
      assert.deepStrictEqual(await retainedState(page), before, 'Native surface changes retain model, camera, body, playhead, source and panel preferences');
    }
    assert.equal(prepares.length, prepareCount, 'Navigation never reloads the model');
    await page.locator('#viewer-fullscreen').click();
    await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'native');
    await hostNavigate(page, 'tools');
    await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'none');
    await hostNavigate(page, 'viewer');
    assert.deepStrictEqual(await retainedState(page), before);
    await page.keyboard.press('Meta+s');
    await page.waitForFunction(() => { const state = ModelViewer.getState().persistence; return state && !state.busy && state.jobId && state.outputs.length >= 2 && !state.error; });
    assert.equal(hash(fs.readFileSync(source)), hash(original));
    await openParents(page, '#viewer-mesh-modify-load');
    await page.locator('#viewer-mesh-modify-load').click();
    await page.waitForFunction(() => document.getElementById('viewer-mesh-modify-select').options.length > 1);
    const mesh = await page.locator('#viewer-mesh-modify-select option').evaluateAll(options => options.find(option => option.value).value);
    await page.locator('#viewer-mesh-modify-select').selectOption(mesh);
    await page.waitForFunction(() => !document.getElementById('viewer-mesh-modify-select-vertex').disabled);
    await page.locator('#viewer-mesh-modify-vertex').fill('0'); await page.locator('#viewer-mesh-modify-select-vertex').click();
    for (const [axis, value] of [['X', '.2'], ['Y', '.8'], ['Z', '-.1']]) await page.locator('#viewer-mesh-modify [data-mesh-position-axis=' + axis + ']').fill(value);
    await page.locator('#viewer-mesh-modify-position-set').click();
    assert(await page.evaluate(() => ModelViewer.getState().meshTools.dirty));
    const originalModel = await page.evaluate(() => ModelViewer.getState().modelId);
    await page.keyboard.press('Meta+s');
    await page.waitForFunction(() => {
      const state = ModelViewer.getState(); return state.loaded && !state.loading && !state.meshTools.busy &&
        state.meshTools.lastSaved && state.meshTools.lastSaved.preview_paths.some(path => path.includes('mesh-edit-'));
    });
    const savedMesh = await page.evaluate(() => ModelViewer.getState().meshTools);
    assert.equal(await page.evaluate(() => ModelViewer.getState().modelId), originalModel, 'Native Save retains the editable session for Undo');
    assert(savedMesh.history > 0);
    assert(savedMesh.lastSaved.preview_paths.every(file => fs.existsSync(file)));
    assert.equal(hash(fs.readFileSync(source)), hash(original), 'Native mesh Save preserves original source');
    await hostNavigate(page, 'tools');
    await page.locator('#gallery-grid .gallery-view-model').click();
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    assert.equal(await page.evaluate(() => __nativeSurface), 'viewer', 'Gallery View in 3D selects native model destination');
    assert.equal(await page.locator('#lang-select').inputValue(), 'ko');
    const invalid = await page.evaluate(async () => {
      try { await ElichikaPlatform.request('setEditorSurface', { editorSurface: 'gallery' }); return false; } catch (_) { return true; }
    }); assert(invalid);
    await page.screenshot({ path: path.join(evidence, 'native-model-ko.png') });
    await hostNavigate(page, 'tools'); await page.screenshot({ path: path.join(evidence, 'native-tools-gallery-ko.png') });
    report.cases.push({ name: 'native shared editor surfaces', modelPreserved: true, galleryPreserved: true, preferencesPreserved: true,
      noPrepareOnNavigation: true, menuOpenSave: true, menuSavesPendingMesh: true, fullscreenExit: true, messages: await page.evaluate(() => __nativeMessages.map(message => message.action)) });
    const browserContext = await browser.newContext({ viewport: { width: 448, height: 998 }, hasTouch: true });
    const phone = await browserContext.newPage(); phone.on('pageerror', error => errors.push(String(error)));
    await phone.goto(server.url); await phone.waitForSelector('#tool-list [data-id=texture_previews]');
    assert(await phone.locator('body > header').isVisible());
    assert(await phone.locator('.tab[data-tab=tools]').isVisible()); assert(await phone.locator('.tab[data-tab=viewer]').isVisible());
    await phone.locator('#tool-list [data-id=texture_previews]').click(); assert(await phone.locator('#gallery-browse').isVisible());
    await phone.locator('.tab[data-tab=viewer]').click(); assert(await phone.locator('#tab-viewer').isVisible());
    report.cases.push({ name: 'browser and Android layout', twoWebTabs: true, galleryInToolList: true, nativeHeaderUnaffected: true });
    assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence })); }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
