/* Compact file controls and responsive minimized cards with real HTTP/Unity.
 * Font profiles scale the root/rem font in host Chromium; they do not claim
 * Android system textZoom or native execution. No successful API is mocked. */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-compact-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-compact-library-'));
const source = path.join(library, 'extracted/3d_model/neutral-body-layout-with-all-three-node-controls.unity');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(path.dirname(source), { recursive: true });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const files = ['webtools/web/index.html', 'webtools/web/static/style.css', 'webtools/web/static/model-viewer.js',
  'webtools/web/static/viewer-rig.js', 'webtools/web/static/viewer-persistence.js', 'webtools/i18n.py'];
const hashes = () => Object.fromEntries(files.map(file => [file, sha(fs.readFileSync(path.join(product, file)))]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const generate = spawnSync(python, ['-c', `import sys;sys.path.insert(0,'tests');import generate_viewer_body_fixture as f;from pathlib import Path
f.BONES=f.BONES+(('BreastSize','Move',(0,.6,0),(0,0,0),(1,1,1)),('SkirtA1_Dyna','Move',(0,.4,0),(0,0,0),(.9,.9,.9)))
Path(sys.argv[1]).write_bytes(f.fixture_bytes())`, source], { cwd: product, env: process.env, encoding: 'utf8' });
assert.equal(generate.status, 0, generate.stderr);
const originalHash = sha(fs.readFileSync(source));
async function startServer() {
  const reservation = net.createServer(); await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('Product server was not ready');
}
async function show(page, selector) {
  const target = page.locator(selector);
  await target.evaluate(element => { for (let p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; });
  await target.scrollIntoViewIfNeeded(); await frames(page); return target;
}
async function hit(page, selector, minimum, enabled = true) {
  const target = page.locator(selector); assert(await target.isVisible(), selector + ' is visible');
  await target.scrollIntoViewIfNeeded(); await frames(page);
  const metric = await target.evaluate(element => { const r = element.getBoundingClientRect(), h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { width: r.width, height: r.height, left: r.left, top: r.top, right: r.right, bottom: r.bottom,
      hit: h === element || element.contains(h), disabled: !!element.disabled }; });
  assert(metric.width >= minimum && metric.height >= minimum && metric.hit, selector + ': ' + JSON.stringify(metric));
  if (enabled) assert(!metric.disabled, selector + ' is actionable'); return metric;
}
async function snapshot(page) {
  await frames(page); return page.evaluate(() => {
    const rect = element => { const r = element.getBoundingClientRect(), s = getComputedStyle(element);
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
        display: s.display, maxWidth: s.maxWidth, clip: s.clip, marginLeft: s.marginLeft, columns: s.gridTemplateColumns,
        visible: !!element.getClientRects().length && r.width > 1 && r.height > 1 }; };
    const e = id => document.getElementById(id), state = ModelViewer.getState();
    return { viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio, coarse: matchMedia('(pointer:coarse)').matches },
      files: rect(e('viewer-files-panel')), title: rect(e('viewer-title')), actions: rect(document.querySelector('.viewer-file-actions')),
      buttons: ['viewer-game-assets', 'viewer-add', 'viewer-add-motion', 'viewer-load'].map(id => ({ id, ...rect(e(id)) })),
      sidebar: e('tab-viewer').classList.contains('viewer-files-resizable'), editor: rect(e('viewer-control-panel')),
      options: rect(e('viewer-file-options').querySelector('summary')), list: rect(e('viewer-file-list')),
      node: (() => { const group = document.querySelector('#viewer-editor-node-panel .viewer-body-controls');
        return { ...rect(group), parent: rect(group.parentElement), cards: Array.from(group.children).filter(card => card.classList.contains('viewer-body-card')).map(rect) }; })(),
      mesh: (() => { const group = document.querySelector('#viewer-editor-mesh-panel .viewer-body-controls');
        return { ...rect(group), parent: rect(group.parentElement), cards: Array.from(group.children).filter(card => card.classList.contains('viewer-body-card')).map(rect) }; })(),
      layout: state.layout, modelId: state.modelId, token: (ModelViewer.getEditingMetadata() || {}).token,
      camera: state.camera, authoring: ModelViewer.getAuthoringState(), saveDisabled: e('viewer-save').disabled,
      preferences: { panel: localStorage.getItem('elichika.viewer.panel-width.v1'), files: localStorage.getItem('elichika.viewer.files-width.v1') },
      pane: { width: e('viewer-control-panel').getBoundingClientRect().width, min: e('viewer-panel-resizer').getAttribute('aria-valuemin'), max: e('viewer-panel-resizer').getAttribute('aria-valuemax') },
      filesPane: { min: e('viewer-files-resizer').getAttribute('aria-valuemin'), max: e('viewer-files-resizer').getAttribute('aria-valuemax') },
      folds: ['viewer-breast-card', 'viewer-hips-card', 'viewer-skirt-card', 'viewer-height-card'].map(id => e(id).open),
      overflow: document.documentElement.scrollWidth > innerWidth + 1 };
  });
}
function retains(before, after, label) {
  for (const key of ['modelId', 'token', 'camera', 'authoring', 'preferences']) assert.deepStrictEqual(after[key], before[key], label + ': ' + key);
  assert(!after.overflow, label + ': no horizontal overflow');
}
function fills(group, label) {
  assert(group.visible && Math.abs(group.left - group.parent.left) <= 1 && Math.abs(group.width - group.parent.width) <= 2, label + ' fills its actual container: ' + JSON.stringify(group));
  const columns = group.columns.trim().split(/\s+/).length;
  assert(columns >= 1 && columns <= 2, label + ' uses at most two columns');
  assert.equal(columns, group.width >= 528 ? 2 : 1, label + ' responds to actual group width');
  assert(Math.abs(group.cards[0].left - group.left) <= 1, label + ' starts on the left');
  const occupied = group.cards[0].width * columns + (columns - 1) * 8;
  assert(Math.abs(occupied - group.width) <= 2, label + ' has no narrow card cap or centered empty strip');
}
(async () => {
  let server, browser;
  const report = { status: 'RUNNING', scope: 'Actual host HTTP/Unity/WebGL; root/rem font simulation, not native Android textZoom', before: hashes(), cases: [] };
  try {
    server = await startServer(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const profiles = [
      { name: 'phone448', width: 448, height: 998, touch: true, dpr: 2, locale: 'ko' },
      { name: 'fold768', width: 768, height: 620, touch: true, dpr: 1.5, locale: 'ko' },
      { name: 'fold853', width: 853, height: 560, touch: true, dpr: 1.5, locale: 'ko' },
      { name: 'fold853-font200', width: 853, height: 590, touch: true, dpr: 1.5, locale: 'ko', font: 2 },
      { name: 'fold768-font130', width: 768, height: 620, touch: true, dpr: 1.5, locale: 'ja', font: 1.3 },
      { name: 'edge719', width: 719, height: 900, touch: true, dpr: 1.5, locale: 'en' },
      { name: 'edge720', width: 720, height: 900, touch: true, dpr: 1.5, locale: 'en' },
      { name: 'edge1079', width: 1079, height: 900, touch: true, dpr: 1.5, locale: 'ko' },
      { name: 'edge1080', width: 1080, height: 900, touch: true, dpr: 1.5, locale: 'ko' },
      { name: 'mac1199-p640-f360', width: 1199, height: 900, dpr: 1, mac: true, locale: 'en', panel: 640, files: 360 },
      { name: 'mac1200-p240-f160', width: 1200, height: 900, dpr: 1, mac: true, locale: 'ja', panel: 240, files: 160 },
      { name: 'mac1360', width: 1360, height: 900, dpr: 1, mac: true, locale: 'en' },
    ];
    for (const p of profiles) {
      if (process.env.PROFILE && p.name !== process.env.PROFILE) continue;
      const context = await browser.newContext({ viewport: { width: p.width, height: p.height }, deviceScaleFactor: p.dpr, hasTouch: !!p.touch, colorScheme: p.touch ? 'dark' : 'light' });
      await context.addInitScript(p => {
        localStorage.setItem('sifas_lang', p.locale);
        if (p.panel) localStorage.setItem('elichika.viewer.panel-width.v1', String(p.panel));
        if (p.files) localStorage.setItem('elichika.viewer.files-width.v1', String(p.files));
        if (p.mac) { window.ElichikaDesktop = { platform: 'macos', version: 1, language: p.locale, capabilities: [] }; window.webkit = { messageHandlers: { elichika: { postMessage() {} } } }; }
      }, p);
      const page = await context.newPage(), errors = [], prepare = [];
      page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => { if (new URL(request.url()).pathname === '/api/viewer/prepare') prepare.push(request.postData()); });
      await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
      await page.waitForFunction(code => document.documentElement.lang === code, p.locale);
      if (p.font) await page.evaluate(font => { document.documentElement.style.fontSize = 16 * font + 'px'; dispatchEvent(new Event('resize')); }, p.font);
      await page.locator('[data-tab="viewer"]').click(); await page.waitForFunction(() => !!ModelViewer.getState().layout.stage);
      const unloaded = await snapshot(page); report.inProgress = { profile: p, unloaded }; assert(!unloaded.overflow);
      if (!unloaded.sidebar) {
        assert(!unloaded.title.visible, 'The horizontal toolbar does not reserve a title row');
        assert.equal(new Set(unloaded.buttons.map(button => Math.round(button.top))).size, 1, 'Unloaded actions occupy one row at these widths');
        assert(unloaded.files.height <= (p.font ? 100 : 60), 'The unloaded horizontal toolbar stays compact');
      } else assert(unloaded.title.visible, 'The desktop sidebar retains its section title');
      for (const id of ['viewer-game-assets', 'viewer-add', 'viewer-add-motion']) await hit(page, '#' + id, p.touch ? 44 : 32);
      await hit(page, '#viewer-load', p.touch ? 44 : 32, false); await hit(page, '#viewer-file-options > summary', p.touch ? 44 : 32);
      await page.locator('#viewer-file-options > summary').click();
      assert(await page.locator('#viewer-file-help').isVisible()); assert((await page.locator('#viewer-file-help').innerText()).trim().length > 30, 'The moved introduction remains available under options');
      await page.locator('#viewer-file-options > summary').click();
      await page.screenshot({ path: path.join(evidence, p.name + '-unloaded.png') });
      await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
      const loaded = await snapshot(page); report.inProgress.loaded = loaded; await page.screenshot({ path: path.join(evidence, p.name + '-loaded.png') }); assert(!loaded.overflow);
      if (!loaded.sidebar) {
        assert(!loaded.title.visible, 'Loading does not recreate a title row');
        assert.equal(new Set(loaded.buttons.map(button => Math.round(button.top))).size, 1, 'Loaded actions remain in one row at these widths');
        // A long translated label may wrap inside its button on a phone. The
        // toolbar tracks that real control, without an extra title/help row.
        assert(loaded.files.height <= Math.max(loaded.actions.height, loaded.options.height, loaded.list.height) + 8,
          'Loaded toolbar has only its real controls and border/padding');
      }
      await hit(page, '#viewer-file-list .viewer-remove', p.touch ? 44 : 32);
      assert((await page.locator('#viewer-file-list').innerText()).includes(path.basename(source)), 'Selected filename remains available');
      if (p.panel) {
        const clamped = Math.max(Number(loaded.pane.min), Math.min(Number(loaded.pane.max), p.panel));
        assert(Math.abs(loaded.pane.width - clamped) <= 1, 'Ordinary pane width still clamps the stored preference');
        const filesWidth = Math.max(Number(loaded.filesPane.min), Math.min(Number(loaded.filesPane.max), p.files));
        assert(Math.abs(loaded.files.width - filesWidth) <= 1, 'Ordinary files width still clamps the stored preference');
        for (const axis of ['x', 'y', 'z']) {
          await show(page, '#viewer-hips-scale-' + axis); await hit(page, '#viewer-hips-scale-' + axis, 34);
        }
      }
      await (await show(page, '#viewer-editor-node-tab')).click(); await (await show(page, '#viewer-node-filter')).selectOption('all');
      const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'BreastSize').node);
      await page.locator('#viewer-node').selectOption(String(node)); await page.locator('#viewer-save-method').selectOption('node');
      const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]'); await field.fill('1.11'); await field.dispatchEvent('change');
      const pending = await snapshot(page); assert.equal(pending.saveDisabled, false);
      await (await show(page, '#viewer-minimize')).click(); await page.waitForFunction(() => ModelViewer.getState().layout.minimized);
      const minimized = await snapshot(page); retains(pending, minimized, 'Minimize'); fills(minimized.node, 'Node cards');
      await (await show(page, '#viewer-breast-card > summary')).scrollIntoViewIfNeeded();
      const hips = page.locator('#viewer-hips-card input[type="number"]');
      for (let n = 0; n < await hips.count(); n++) await hit(page, '#viewer-hips-card input[type="number"] >> nth=' + n, p.touch ? 44 : 34);
      await page.screenshot({ path: path.join(evidence, p.name + '-node-minimized.png') });
      await (await show(page, '#viewer-editor-mesh-tab')).click(); const mesh = await snapshot(page); fills(mesh.mesh, 'Mesh cards');
      await (await show(page, '#viewer-thighs-number')).fill('110'); await page.locator('#viewer-thighs-apply').click();
      assert.equal((await snapshot(page)).saveDisabled, false, 'Mesh edits remain saveable');
      await show(page, '#viewer-save-mod'); await hit(page, '#viewer-save-mod', p.touch ? 44 : 34); await hit(page, '#viewer-add-to-game', p.touch ? 44 : 34);
      const edited = await snapshot(page); assert(edited.authoring.edits.some(edit => edit.method === 'mesh') && edited.authoring.edits.some(edit => edit.method === 'node'));
      await (await show(page, '#viewer-model-restore')).click(); await page.waitForFunction(() => !ModelViewer.getState().layout.minimized); const restored = await snapshot(page);
      retains(edited, restored, 'Restore');
      if (p.panel) {
        assert(Math.abs(restored.pane.width - loaded.pane.width) <= 1, 'Restoring returns the ordinary stored-width pane');
        assert(Math.abs(restored.files.width - loaded.files.width) <= 1, 'Restoring returns the ordinary stored-width files');
      }
      if (p.panel) {
        await page.setViewportSize({ width: 719, height: 1000 }); await frames(page);
        await (await show(page, '#viewer-minimize')).click(); await page.waitForFunction(() => ModelViewer.getState().layout.minimized);
        fills((await snapshot(page)).mesh, 'Narrow minimized Mesh cards');
        await (await show(page, '#viewer-editor-node-tab')).click(); fills((await snapshot(page)).node, 'Narrow minimized Node cards');
        await page.locator('#viewer-model-restore').click(); await page.setViewportSize({ width: p.width, height: p.height }); await frames(page); const wideAgain = await snapshot(page);
        assert.deepStrictEqual(wideAgain.preferences, loaded.preferences); assert(Math.abs(wideAgain.pane.width - loaded.pane.width) <= 1);
        assert(Math.abs(wideAgain.files.width - loaded.files.width) <= 1);
      }
      assert.equal(prepare.length, 1, 'Layout changes and options never reload the source'); assert.deepStrictEqual(errors, []);
      const probe = await page.evaluate(() => ModelViewer.renderProbe(13)); assert(probe.ready && probe.glError === 0);
      report.cases.push({ profile: p, unloaded, loaded, minimized, mesh: mesh.mesh, restored, preparedOnce: true }); await context.close();
    }
    assert.equal(sha(fs.readFileSync(source)), originalHash); report.after = hashes(); assert.deepStrictEqual(report.after, report.before);
    delete report.inProgress; report.status = 'PASS'; fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } catch (error) { report.status = 'FAIL'; report.failure = String(error.stack || error); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); throw error;
  } finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end(); } }
})().catch(error => { console.error(error); process.exitCode = 1; });
