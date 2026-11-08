/* Shared section navigation with original generated geometry and host-message
 * stubs. Native APK/WebKit execution is a separate integration gate. */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const url = process.env.VIEWER_URL || 'http://127.0.0.1:8898';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-navigation-'));
fs.mkdirSync(evidence, { recursive: true });
const generated = fixture({ allSaved: true });
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const retained = state => ({ modelId: state.modelId, paths: state.loadedPaths, camera: state.camera,
  adjustments: state.rig.nodeAdjustments, methods: state.rig.editingMethods });
const report = { status: 'RUNNING', scope: 'Real shared DOM/WebGL with original generated model and simulated native navigation only', cases: [] };

async function openPage(browser, { embedded = false, native = 'android', hash = 'tools', delayed = false } = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(({ embedded, native }) => {
    localStorage.setItem('sifas_lang', 'en');
    window.__sectionMessages = [];
    if (embedded && native === 'android') {
      window.ElichikaNavigationNative = { postMessage: message => __sectionMessages.push(JSON.parse(message)) };
    } else if (embedded) {
      window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'ko', capabilities: ['setSection'] };
      window.webkit = { messageHandlers: { elichika: { postMessage(message) {
        __sectionMessages.push(message);
        setTimeout(() => ElichikaPlatform.receive({ id: message.id, result: {} }), 0);
      } } } };
    }
  }, { embedded, native });
  let releaseTools;
  const toolsReady = delayed ? new Promise(resolve => { releaseTools = resolve; }) : Promise.resolve();
  await page.route('**/api/tools?*', async route => {
    await toolsReady;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ roots: {}, tools: [{
      id: 'navigation_fixture', label: 'Original navigation test form', modes: ['single', 'batch'],
      fields: [{ name: 'draft', label: 'Unsaved draft', type: 'text', default: 'original' }],
    }] }) });
  });
  await page.route('**/api/viewer/prepare', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    id: 'navigation-original', url: '/api/viewer/model/navigation-original.glb', warnings: [],
    stats: { meshes: 1, vertices: 3, triangles: 1, textures: 0, materials: 1 }, rig: generated.rig,
  }) }));
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: generated.glb }));
  await page.route('**/api/fs/list?*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entries: [
    { name: 'Original neutral fixture', path: '/navigation-fixture.unity', is_dir: false, is_bundle: true },
  ] }) }));
  await page.route('**/api/thumb?*', route => route.fulfill({ status: 200, contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><path d="M0 0h16v16H0z" fill="blue"/></svg>' }));
  await page.goto(url + (embedded ? '/?embedded=1&lang=ko' : '/') + '#' + hash, { waitUntil: 'domcontentloaded' });
  return { context, page, errors, releaseTools };
}

async function ready(page) {
  await page.waitForFunction(() => !!window.ElichikaNavigation && document.querySelector('#tool-list button[data-id="texture_previews"]'));
  await frames(page);
}

(async () => {
  const launch = { headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch);
  try {
    for (const native of ['android', 'macos']) {
      const { context, page, errors, releaseTools } = await openPage(browser, { embedded: true, native, hash: 'viewer', delayed: true });
      await page.waitForFunction(() => !!window.ElichikaNavigation);
      assert.deepEqual(await page.evaluate(() => {
        ElichikaNavigation.showSection('tools', { notify: false });
        ElichikaNavigation.showSection('viewer', { notify: false });
        ElichikaNavigation.showSection('tools', { notify: false });
        return { section: ElichikaNavigation.currentSection(), invalid: ElichikaNavigation.showSection('settings') };
      }), { section: 'tools', invalid: false });
      releaseTools(); await ready(page);
      await page.waitForFunction(() => __sectionMessages.some(message => message.event === 'ready'));
      assert.equal(await page.evaluate(() => ElichikaNavigation.currentSection()), 'tools');
      assert(await page.locator('#tab-tools').evaluate(node => node.classList.contains('active')));
      assert.equal(await page.locator('#asset-tools-header').evaluate(node => node.getBoundingClientRect().height), 0);
      assert.equal(await page.evaluate(() => document.documentElement.lang), 'ko');
      assert.equal((await page.evaluate(() => __sectionMessages.filter(message => message.event === 'change'))).length, 0);

      await page.locator('#tool-list button[data-id="navigation_fixture"]').click();
      await page.locator('#tool-panel input[data-name="draft"]').fill('한글 unsaved draft 1.234');
      await page.locator('#tool-list button[data-id="texture_previews"]').click();
      await page.locator('#gallery-path').evaluate(node => { node.value = '/original preview folder'; });
      await page.locator('#gallery-load').click();
      await page.waitForFunction(() => document.querySelectorAll('#gallery-grid .gcard').length === 1);
      await page.evaluate(() => { window.__galleryNode = document.querySelector('#gallery-grid .gcard'); });
      await page.locator('#tool-list button[data-id="navigation_fixture"]').click();
      assert.equal(await page.locator('#tool-panel input[data-name="draft"]').inputValue(), '한글 unsaved draft 1.234');

      await page.evaluate(() => openModelViewer(['/navigation-fixture.unity']));
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      await page.locator('[data-viewer-view="left"]').click();
      await page.evaluate(() => {
        const filter = document.querySelector('#viewer-node-filter');
        filter.value = 'all'; filter.dispatchEvent(new Event('change', { bubbles: true }));
        const node = document.querySelector('#viewer-node');
        const move = Array.from(node.options).find(option => option.textContent.includes('Move'));
        if (!move) throw new Error('Generated editable Move bone missing');
        node.value = move.value; node.dispatchEvent(new Event('change', { bubbles: true }));
        const scale = document.querySelector('[data-viewer-node-kind="scale"][data-axis="Z"]');
        if (scale.disabled) throw new Error('Generated scale field is unavailable');
        scale.value = '1.234'; scale.dispatchEvent(new Event('input', { bubbles: true }));
        scale.dispatchEvent(new Event('change', { bubbles: true }));
      });
      await frames(page);
      const before = retained(await page.evaluate(() => ModelViewer.getState()));
      assert(Object.keys(before.adjustments).length > 0, 'Use a real unsaved model edit for state retention');
      const messages = await page.evaluate(() => __sectionMessages.length);
      const historyLength = await page.evaluate(() => history.length);
      await page.evaluate(() => {
        ElichikaNavigation.showSection('tools', { notify: false });
        ElichikaNavigation.showSection('viewer', { notify: false });
        ElichikaNavigation.showSection('tools', { notify: false });
      });
      await page.locator('#tool-list button[data-id="texture_previews"]').click();
      assert.equal(await page.locator('#gallery-path').inputValue(), '/original preview folder');
      assert(await page.evaluate(() => document.querySelector('#gallery-grid .gcard') === __galleryNode));
      await page.evaluate(() => ElichikaNavigation.showSection('viewer', { notify: false }));
      await frames(page);
      assert.deepEqual(retained(await page.evaluate(() => ModelViewer.getState())), before);
      assert.equal(await page.evaluate(() => __sectionMessages.length), messages);
      assert.equal(await page.evaluate(() => history.length), historyLength);
      assert.equal(await page.locator('#asset-tools-header').evaluate(node => node.getBoundingClientRect().height), 0);
      assert.equal(await page.locator('#viewer-stage canvas').count(), 1);
      if (native === 'macos') {
        const count = await page.evaluate(() => __sectionMessages.length);
        assert(await page.evaluate(async () => {
          for (const args of [{ section: 'server', event: 'change' }, { section: 'viewer', event: 'unknown' }]) {
            try { await ElichikaPlatform.request('setSection', args); return false; } catch (_) { /* expected */ }
          }
          return true;
        }));
        assert.equal(await page.evaluate(() => __sectionMessages.length), count);
      }
      assert.deepEqual(errors, []);
      await page.screenshot({ path: path.join(evidence, native + '-embedded-viewer.png') });
      report.cases.push({ name: native + '-early-selection-host-feedback-and-live-state-retention', status: 'PASS' });
      await context.close();
    }

    const { context, page, errors } = await openPage(browser, { hash: 'gallery' });
    await ready(page);
    assert.equal(await page.locator('.tab').count(), 2);
    assert.equal(await page.locator('.tab[data-tab="gallery"]').count(), 0);
    assert.equal(await page.evaluate(() => ElichikaNavigation.currentSection()), 'tools');
    assert(await page.locator('#tab-gallery').isVisible());
    assert.equal(await page.evaluate(() => location.hash), '#tools');
    await page.locator('#gallery-path').evaluate(node => { node.value = '/legacy original folder'; });
    await page.locator('#gallery-load').click();
    await page.waitForFunction(() => document.querySelector('#gallery-grid .gallery-view-model'));
    await page.locator('#gallery-grid .gallery-view-model').click();
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    assert.equal(await page.evaluate(() => ElichikaNavigation.currentSection()), 'viewer');
    await page.locator('.tab[data-tab="tools"]').click();
    assert(await page.locator('#tab-gallery').isVisible());
    assert.equal(await page.locator('#gallery-path').inputValue(), '/legacy original folder');
    assert.deepEqual(errors, []);
    report.cases.push({ name: 'standalone-two-sections-and-legacy-gallery-to-viewer', status: 'PASS' });
    await context.close();
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error.stack || error); throw error;
  } finally {
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report));
})().catch(error => { console.error(error); process.exitCode = 1; });
