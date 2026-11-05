/* Shared UI with a simulated native chooser, real HTTP/Unity preparation and
 * serialized saves. This is a host-browser contract/layout test, not macOS QA. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-macos-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-macos-evidence-'));
fs.mkdirSync(evidence, { recursive: true });
const original = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
const source = path.join(library, 'extracted/3d_model/neutral.unity');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.writeFileSync(source, original);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const names = ['webtools/web/index.html', 'webtools/web/static/platform.js', 'webtools/web/static/app.js',
  'webtools/web/static/style.css', 'webtools/web/static/model-viewer.js', 'webtools/web/static/viewer-persistence.js', 'webtools/i18n.py'];
const hashes = () => Object.fromEntries(names.map(name => [name, sha(fs.readFileSync(path.join(product, name)))]));
const report = { status: 'RUNNING', scope: 'Chromium host with native message stub; actual unchanged Unity source and real product HTTP/save APIs', sourceBefore: hashes(), cases: [] };
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function show(locator) {
  await locator.evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await locator.scrollIntoViewIfNeeded();
}
async function startServer() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error('Server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('HTTP server was not ready');
}
async function installNative(context) {
  await context.addInitScript(({ source, library }) => {
    window.__macMessages = []; window.__cancelNext = false;
    window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'ko', capabilities: ['openFiles', 'chooseDirectory', 'reveal', 'fullscreen', 'setLanguage'] };
    window.webkit = { messageHandlers: { elichika: { postMessage(message) {
      __macMessages.push(message);
      setTimeout(() => {
        let result = {};
        if (__cancelNext) { __cancelNext = false; result = { cancelled: true }; }
        else if (message.action === 'openFiles') result = { paths: [source] };
        else if (message.action === 'chooseDirectory') result = { path: library };
        window.ElichikaPlatform.receive({ id: message.id, result });
        if (message.action === 'setFullscreen') requestAnimationFrame(() => window.dispatchEvent(new CustomEvent('elichika-native-fullscreen-changed', { detail: { active: message.enabled, settled: true } })));
      }, 20);
    } } } };
  }, { source, library });
}
async function loaded(page) {
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && document.getElementById('viewer-busy').hidden);
  await frames(page);
}
async function edit(page, name, z, method) {
  const node = await page.evaluate(name => ModelViewer.getEditingMetadata().nodes.find(node => node.name === name), name);
  const tab = page.locator(method === 'mesh' ? '#viewer-editor-mesh-tab' : '#viewer-editor-node-tab');
  await show(tab); await tab.click();
  await show(page.locator('#viewer-node')); await page.locator('#viewer-node').selectOption(String(node.node));
  const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="Z"]');
  await show(input); await input.fill(String(z)); await input.dispatchEvent('change');
  await page.locator('#viewer-save-method').selectOption(method);
}
async function desktopLayout(page) {
  return page.evaluate(() => {
    const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    return { files: rect('.viewer-files'), stage: rect('#viewer-stage'), editor: rect('.viewer-control-panel'),
      overflow: document.documentElement.scrollWidth > innerWidth, render: ModelViewer.renderProbe(17),
      desktop: document.documentElement.classList.contains('elichika-desktop') };
  });
}
async function run() {
  let server, browser, context;
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1 });
    await installNative(context);
    const page = await context.newPage(), errors = [], dialogs = [];
    page.on('pageerror', error => errors.push(String(error))); page.setDefaultTimeout(30000);
    page.on('dialog', dialog => { dialogs.push(dialog.message()); dialog.dismiss(); });
    let saves = 0; page.on('request', request => { if (request.url().endsWith('/api/viewer/edit/export')) saves++; });
    await page.goto(server.url);
    await page.waitForFunction(() => window.ModelViewer && typeof openModelViewer === 'function' && document.documentElement.lang === 'ko');
    assert.equal(await page.evaluate(() => ElichikaPlatform.info().native), true);
    await page.locator('.tab[data-tab="viewer"]').click();
    await page.locator('#viewer-file-options').evaluate(element => { element.open = true; });
    await page.locator('#viewer-auto-face').uncheck();
    await page.locator('#viewer-file-options').evaluate(element => { element.open = false; });
    await page.evaluate(() => { __cancelNext = true; });
    await page.locator('#viewer-add').click();
    await page.waitForFunction(() => state.picker === null && __macMessages.length === 1);
    assert.equal(await page.locator('#picker').evaluate(element => element.classList.contains('hidden')), true);
    assert.deepEqual(await page.evaluate(() => ModelViewer.getState().paths), []);
    report.cases.push({ name: 'native-chooser-cancel-keeps-shared-selection', status: 'PASS' });

    await page.evaluate(() => ElichikaPlatform.perform('openModel'));
    await loaded(page);
    assert.deepEqual(await page.evaluate(() => ModelViewer.getState().loadedPaths), [source]);
    const layout = await desktopLayout(page);
    assert(layout.desktop && layout.files.right < layout.stage.x && layout.stage.right < layout.editor.x);
    assert(layout.stage.width > 500 && layout.stage.height > 650 && !layout.overflow);
    assert(layout.render.ready && layout.render.nonBackgroundSamples > 0);
    report.cases.push({ name: 'native-menu-opens-real-Unity-in-three-column-layout', status: 'PASS', layout });

    await edit(page, 'LeftUpLeg', 1.2, 'mesh'); await edit(page, 'BreastSize', 1.15, 'node');
    const retained = await page.evaluate(() => ({ state: ModelViewer.getAuthoringState(), camera: ModelViewer.getState().camera }));
    for (const viewport of [{ width: 800, height: 700 }, { width: 448, height: 998 }, { width: 1360, height: 900 }]) {
      await page.setViewportSize(viewport); await frames(page);
      assert.deepEqual(await page.evaluate(() => ({ state: ModelViewer.getAuthoringState(), camera: ModelViewer.getState().camera })), retained);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }
    report.cases.push({ name: 'desktop-window-resize-preserves-edits-and-camera', status: 'PASS' });

    // Cmd-S must commit an active numeric field through its existing change handler.
    const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="Z"]');
    await show(input); await input.fill('1.17'); await page.keyboard.press('Meta+s');
    await page.waitForFunction(() => ModelViewer.getState().persistence.outputPaths.length > 0 && !ModelViewer.getState().persistence.busy);
    const result = await page.evaluate(() => ModelViewer.getState().persistence);
    assert(!result.error, result.error); assert.equal(saves, 1);
    assert(fs.readFileSync(source).equals(original));
    const inspect = spawnSync(python, [path.join(__dirname, 'inspect_viewer_persistence.py'), result.previewPaths[0]], { cwd: product, encoding: 'utf8' });
    assert.equal(inspect.status, 0, inspect.stderr);
    const serialized = JSON.parse(inspect.stdout);
    const breast = serialized.components.flatMap(component => component.entries).find(entry => entry.target === 'BreastSize' && entry.kind === 'scale');
    assert(Math.abs(breast.scaled[2] - 1.17) < .00001);
    await show(page.locator('.viewer-reveal').first()); await page.locator('.viewer-reveal').first().click();
    await page.waitForFunction(() => __macMessages.some(message => message.action === 'reveal'));
    const reveal = await page.evaluate(() => __macMessages.find(message => message.action === 'reveal'));
    assert(result.outputPaths.includes(reveal.path));
    report.cases.push({ name: 'native-save-command-serializes-both-methods-and-reveals-completed-file', status: 'PASS', output: serialized.file_sha256, exports: saves });

    await show(page.locator('#viewer-open-saved')); await page.locator('#viewer-open-saved').click();
    await page.waitForFunction(() => ModelViewer.getState().persistence.reviewingSaved && !ModelViewer.getState().loading && document.getElementById('viewer-busy').hidden);
    await frames(page); await page.screenshot({ path: path.join(evidence, 'desktop-saved-result.png') });
    const beforeFullscreen = await page.evaluate(() => __macMessages.filter(message => message.action === 'setFullscreen').length);
    await page.evaluate(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen-changed', { detail: { active: true, settled: true } })));
    assert.equal(await page.evaluate(() => __macMessages.filter(message => message.action === 'setFullscreen').length), beforeFullscreen,
      'A macOS green-window fullscreen notification must not trigger an unwanted exit');
    await page.locator('#viewer-fullscreen').click();
    await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'native');
    await page.locator('#viewer-fullscreen').click(); await frames(page);
    assert.equal(await page.evaluate(() => ModelViewer.getState().layout.fullscreen), 'none');
    report.cases.push({ name: 'native-viewer-fullscreen-keeps-global-window-actions-independent', status: 'PASS' });

    const languageState = await page.evaluate(() => ({ id: ModelViewer.getState().modelId, camera: ModelViewer.getState().camera,
      paths: ModelViewer.getState().loadedPaths, authoring: ModelViewer.getAuthoringState() }));
    await page.locator('#lang-select').selectOption('ja');
    await page.waitForFunction(() => document.documentElement.lang === 'ja' && __macMessages.some(message => message.action === 'setLanguage' && message.language === 'ja'));
    assert.equal(await page.locator('.viewer-reveal').first().innerText(), 'Finderで表示');
    assert.deepEqual(await page.evaluate(() => ({ id: ModelViewer.getState().modelId, camera: ModelViewer.getState().camera,
      paths: ModelViewer.getState().loadedPaths, authoring: ModelViewer.getAuthoringState() })), languageState);
    const languageRequests = await page.evaluate(() => __macMessages.filter(message => message.action === 'setLanguage').length);
    await page.evaluate(() => changeLang('ja'));
    assert.equal(await page.evaluate(() => __macMessages.filter(message => message.action === 'setLanguage').length), languageRequests,
      'Native language feedback must not create an update loop');
    report.cases.push({ name: 'native-language-sync-preserves-model-and-prevents-feedback-loop', status: 'PASS' });

    const denied = await page.evaluate(async () => {
      const count = __macMessages.length;
      let unknown = false, relative = false;
      try { await ElichikaPlatform.request('runShell', { command: 'forbidden' }); } catch (_) { unknown = true; }
      try { await ElichikaPlatform.request('reveal', { path: '../outside' }); } catch (_) { relative = true; }
      return { unknown, relative, countUnchanged: count === __macMessages.length,
        command: ElichikaPlatform.perform('runShell'), response: ElichikaPlatform.receive({ id: 'unrequested', result: {} }) };
    });
    assert.deepEqual(denied, { unknown: true, relative: true, countUnchanged: true, command: false, response: false });
    assert.deepEqual(errors, []);
    report.cases.push({ name: 'unsupported-native-commands-and-invalid-responses-fail-closed', status: 'PASS' });
    const closing = await page.evaluate(async () => {
      ElichikaPlatform.perform('openModel');
      dispatchEvent(new Event('pagehide'));
      await Promise.resolve();
      return { supports: ElichikaPlatform.supports('openFiles'), command: ElichikaPlatform.perform('openModel') };
    });
    assert.deepEqual(closing, { supports: false, command: false });
    await wait(100); assert.deepEqual(dialogs, [], 'Closing the view must not open native-request error dialogs');
    report.cases.push({ name: 'window-close-rejects-pending-native-request-without-dialog-or-reopen', status: 'PASS' });
    await context.close(); context = null;

    for (const fakeMetadata of [false, true]) {
      const mobile = await browser.newContext({ viewport: { width: 448, height: 998 }, hasTouch: true });
      if (fakeMetadata) await mobile.addInitScript(() => { window.ElichikaDesktop = { platform: 'macos', version: 1, capabilities: ['openFiles'] }; });
      const page = await mobile.newPage(); await page.goto(server.url);
      await page.waitForFunction(() => window.ElichikaPlatform && window.ModelViewer && typeof openPicker === 'function');
      assert.equal(await page.evaluate(() => ElichikaPlatform.info().native), false);
      await page.locator('.tab[data-tab="viewer"]').click(); await page.locator('#viewer-add').click();
      assert.equal(await page.locator('#picker').evaluate(element => !element.classList.contains('hidden')), true);
      assert.equal(await page.evaluate(() => document.documentElement.classList.contains('elichika-desktop')), false);
      await mobile.close();
    }
    report.cases.push({ name: 'browser-and-Android-style-chooser-remains-default-without-trusted-host', status: 'PASS' });
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally {
    report.sourceAfter = hashes(); report.sourcesUnchanged = JSON.stringify(report.sourceBefore) === JSON.stringify(report.sourceAfter);
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    if (context) await context.close(); if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.stream.end(); }
    fs.rmSync(library, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ status: report.status, cases: report.cases.length, report: path.join(evidence, 'report.json') }));
}
run().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
