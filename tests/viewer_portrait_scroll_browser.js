/* Real HTTP/Unity/WebGL regression for editing below a tall stacked viewport.
 * No model/prepare response is mocked. Native macOS and Android remain separate
 * execution gates; the desktop adapter below only selects the shared Mac CSS. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = process.env.VIEWER_PRODUCT || path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-portrait-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-portrait-library-'));
const source = path.join(library, 'extracted/3d_model/neutral.unity');
fs.mkdirSync(path.dirname(source), { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
const original = fs.readFileSync(path.join(product, 'tests/fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, original);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function startServer() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error('Product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('Product server was not ready');
}
async function measure(page) {
  await frames(page);
  return page.evaluate(() => {
    const rect = selector => { const element = document.querySelector(selector), r = element.getBoundingClientRect();
      return { x: r.x, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
        position: getComputedStyle(element).position }; };
    const field = document.querySelector('input[data-viewer-node-kind="rotation"][data-axis="Z"]'), f = field.getBoundingClientRect();
    const hit = document.elementFromPoint(f.x + f.width / 2, f.y + f.height / 2);
    const state = ModelViewer.getState();
    return { scrollY, stage: rect('#viewer-stage'), modelPanel: rect('.viewer-model-panel'), editor: rect('.viewer-control-panel'),
      header: rect('body > header'), field: { top: f.top, bottom: f.bottom, width: f.width, height: f.height, value: field.value,
        hit: hit === field || field.contains(hit), scrollMarginTop: getComputedStyle(field).scrollMarginTop },
      camera: state.camera, modelId: state.modelId, authoring: ModelViewer.getAuthoringState(),
      probe: ModelViewer.renderProbe(13), overflow: document.documentElement.scrollWidth > innerWidth + 1,
      viewport: { width: innerWidth, height: innerHeight }, short: state.layout.shortHeight };
  });
}
async function main() {
  let server, browser;
  const report = { status: 'RUNNING', scope: 'Real product HTTP/Unity conversion and Chromium WebGL, actual document scrolling and input; no physical-device claim', cases: [] };
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [
      { name: 'phone-portrait', width: 448, height: 998, touch: true },
      { name: 'tall-phone', width: 448, height: 1400, touch: true },
      { name: 'normal-short-phone', width: 360, height: 456 },
      { name: 'stacked-breakpoint', width: 719, height: 1200, touch: true },
      { name: 'narrow-mac', width: 600, height: 1200, mac: true },
      { name: 'fold-side-by-side', width: 853, height: 1200, touch: true },
      { name: 'wide-mac', width: 1600, height: 1000, mac: true }
    ].filter(profile => !process.env.PROFILE_ONLY || profile.name === process.env.PROFILE_ONLY)) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height },
        deviceScaleFactor: 1, hasTouch: !!profile.touch });
      await context.addInitScript(({ mac }) => {
        localStorage.setItem('sifas_lang', 'en');
        if (mac) {
          window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'en', capabilities: [] };
          window.webkit = { messageHandlers: { elichika: { postMessage() {} } } };
        }
      }, { mac: !!profile.mac });
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(String(error))); page.setDefaultTimeout(30000);
      await page.goto(server.url);
      await page.waitForFunction(() => typeof openModelViewer === 'function');
      await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      const id = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'LeftUpLeg').node);
      await page.locator('#viewer-node-editor').evaluate(element => { element.open = true; });
      await page.locator('#viewer-node-search').fill('');
      await page.locator('#viewer-node-filter').selectOption('all');
      await page.locator('#viewer-node').selectOption(String(id));
      const field = page.locator('input[data-viewer-node-kind="rotation"][data-axis="Z"]');
      await field.fill('7.5'); await field.dispatchEvent('change');
      await page.evaluate(() => { scrollTo(0, 0); document.querySelector('.viewer-control-panel').scrollTop = 0; });
      const initial = await measure(page);
      assert(!initial.overflow && initial.probe.triangles > 0 && initial.probe.nonBackgroundSamples > 0 && initial.probe.glError === 0,
        'The actual Unity model renders visible pixels without horizontal overflow');
      await page.screenshot({ path: path.join(evidence, profile.name + '-initial.png') });
      const observations = [];
      await page.mouse.move(profile.width - 5, profile.height - 30);
      for (let turn = 0; turn < 3; turn++) {
        await page.mouse.wheel(0, 650); observations.push(await measure(page));
      }
      const scrolled = observations[observations.length - 1];
      if (profile.width < 720 && !process.env.OBSERVE_OLD_LAYOUT) {
        assert(scrolled.scrollY > initial.scrollY + 200, 'Use actual document scroll, not an inner control scroll');
        for (const sample of observations) {
          assert(Math.abs(sample.stage.height - initial.stage.height) <= 1, 'Scrolling must not grow or shrink the stacked model');
          assert(Math.abs(sample.stage.top - initial.stage.top + sample.scrollY - initial.scrollY) <= 1,
            'The stacked model must move with the document, rather than follow the viewport');
        }
        assert(scrolled.stage.bottom <= scrolled.header.bottom + 1, 'The tall model leaves the editing viewport');
      } else if (profile.width >= 720) {
        assert.equal(scrolled.modelPanel.position, 'sticky', 'Independent wide model column keeps its sticky behavior');
        assert(scrolled.stage.right <= scrolled.editor.x + 1, 'The wide model must not cover the separate editor column');
      }
      await field.evaluate(element => { element.focus(); element.scrollIntoView({ block: 'start' }); });
      const focused = await measure(page);
      if (profile.width < 720 && !process.env.OBSERVE_OLD_LAYOUT) {
        assert(focused.stage.bottom <= focused.header.bottom + 1, 'Focusing an edit must not pull the model back over it');
        // A field near the document end cannot align to the header without
        // inventing blank content below it. Measure the actual editor area.
        const visibleEditor = Math.min(profile.height, focused.editor.bottom) - Math.max(focused.header.bottom, focused.editor.top);
        const availableEditor = Math.min(focused.editor.height, profile.height - focused.header.bottom - 16);
        assert(visibleEditor >= availableEditor - 1, 'Editing can use the full viewport below the header');
        assert(focused.field.top >= focused.header.bottom - 1 && focused.field.bottom <= profile.height + 1, 'The focused field remains inside the available editor area');
        assert(focused.field.hit && focused.field.height >= (profile.mac ? 34 : 44), 'The editing field remains an unobstructed target under the platform sizing policy');
        assert(parseFloat(focused.field.scrollMarginTop) <= focused.header.height + 16, 'Focus margin excludes the scrolled-away model');
      }
      assert.deepStrictEqual(focused.authoring, initial.authoring, 'Scrolling/focus preserves actual edits');
      assert.deepStrictEqual(focused.camera, initial.camera, 'Scrolling/focus preserves the camera');
      assert.equal(focused.modelId, initial.modelId);
      await field.fill('8.5'); await field.dispatchEvent('change');
      const edited = await measure(page);
      assert.equal(edited.field.value, '8.5', 'The visible editor accepts a real value change');
      assert.notDeepStrictEqual(edited.authoring, initial.authoring, 'The changed value reaches the actual editing state');
      assert.deepStrictEqual(edited.camera, initial.camera);
      await page.screenshot({ path: path.join(evidence, profile.name + '-editing.png') });
      await page.evaluate(() => scrollTo(0, 0));
      const returned = await measure(page);
      assert(returned.stage.bottom > returned.header.bottom && returned.probe.triangles > 0 && returned.probe.nonBackgroundSamples > 0 && returned.probe.glError === 0,
        'Scrolling back shows the same rendered model pixels');
      assert.deepStrictEqual(returned.authoring, edited.authoring);
      assert.deepStrictEqual(returned.camera, initial.camera);
      if (profile.name === 'phone-portrait') {
        await page.locator('#viewer-expand').click();
        const expanded = await measure(page);
        assert(expanded.stage.height >= profile.height * .95, 'Expand view still fills the viewport');
        assert.deepStrictEqual(expanded.camera, initial.camera);
        await page.locator('#viewer-expand').click();
        const restored = await measure(page);
        assert.deepStrictEqual(restored.authoring, edited.authoring);
        assert.deepStrictEqual(restored.camera, initial.camera);
      }
      assert.deepStrictEqual(errors, []);
      report.cases.push({ profile, initial, observations, focused, edited, returned });
      await context.close();
    }
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'The source Unity file remains unchanged');
    report.sourceSha256 = sha(original);
    report.status = process.env.OBSERVE_OLD_LAYOUT ? 'OBSERVED_ORIGINAL_LAYOUT' : 'PASS';
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end(); }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
