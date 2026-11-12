/* Real HTTP/Unity regression for file-row clipping and keyboard removal.
 * Host Chromium checks responsive layout and a Mac bridge protocol fixture;
 * it does not claim native NSOpenPanel or WKWebView execution. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const {spawn, execFileSync} = require('child_process');
const {chromium} = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-model-picker-delete-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-picker-delete-library-')), extracted = path.join(library, 'extracted'), models = path.join(extracted, '3d_model');
fs.mkdirSync(evidence, {recursive: true}); fs.mkdirSync(models, {recursive: true});
const filenames = ['ch0201_suit_' + 'costume_model_with_long_filename_'.repeat(6) + '01.unity', 'second_' + '衣装_model_'.repeat(14) + '.unity', 'third.unity'];
const sources = filenames.map(name => path.join(models, name));
execFileSync(python, ['-B', '-c', 'import sys;from pathlib import Path;sys.path.insert(0,"tests");from generate_viewer_body_fixture import fixture_bytes;Path(sys.argv[1]).write_bytes(fixture_bytes())', sources[0]], {cwd: product, env: process.env});
sources.slice(1).forEach(file => fs.copyFileSync(sources[0], file));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), sourceHashes = sources.map(sha);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {cwd: product, env: {...process.env, SUKUSTA_DIR: library}, stdio: ['ignore', 'pipe', 'pipe']});
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) {if (child.exitCode !== null) throw new Error('Product server exited'); try {if ((await fetch(url + '/api/tools')).ok) return {child, stream, url};} catch (_) {} await wait(100);}
  child.kill(); throw new Error('Product server did not start');
}
async function init(page, url, width) {
  await page.addInitScript(width => {localStorage.setItem('sifas_lang', 'en'); localStorage.setItem('elichika.viewer.files-width.v1', String(width));}, width);
  await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function' && document.querySelector('#tool-list button'));
  await page.evaluate(() => {document.getElementById('viewer-auto-face').checked = false;});
}
async function load(page) {
  await page.evaluate(sources => openModelViewer(sources), sources);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
  await frames(page);
}
async function show(locator) {
  await locator.evaluate(e => {for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;});
  await locator.scrollIntoViewIfNeeded(); return locator;
}
async function menu(page) {
  const summary = page.locator('#viewer-model-files > summary');
  await summary.focus(); if (!(await summary.locator('..').evaluate(e => e.open))) await summary.press('Enter');
  await frames(page); assert(await page.locator('#viewer-file-list').isVisible());
}
async function metric(locator) {
  await locator.scrollIntoViewIfNeeded();
  return locator.evaluate(e => {
    for (let p = e.parentElement; p; p = p.parentElement) p.scrollLeft = 0;
    const r = e.getBoundingClientRect(), row = e.parentElement.getBoundingClientRect(), list = e.closest('ul'), panel = e.closest('#viewer-files-panel') || list;
    const p = panel.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), name = e.parentElement.querySelector('span');
    return {left: r.left, right: r.right, width: r.width, height: r.height, row: {left: row.left, right: row.right}, panel: {left: p.left, right: p.right, clientWidth: panel.clientWidth, scrollWidth: panel.scrollWidth}, hit: hit === e || e.contains(hit), filename: name.textContent, title: name.title, aria: e.getAttribute('aria-label'), nameClientWidth: name.clientWidth, nameScrollWidth: name.scrollWidth, ellipsis: getComputedStyle(name).textOverflow, whiteSpace: getComputedStyle(name).whiteSpace, listClientWidth: list.clientWidth, listScrollWidth: list.scrollWidth};
  });
}
function contained(m, minimum) {
  assert(m.width >= minimum && m.height >= minimum && m.hit, 'Remove is a reachable target: ' + JSON.stringify(m));
  assert(m.left >= m.panel.left - 1 && m.right <= m.panel.right - 1 && m.right <= m.row.right + 1, 'Remove stays inside its row/panel: ' + JSON.stringify(m));
  assert(m.panel.scrollWidth <= m.panel.clientWidth + 1 && m.listScrollWidth <= m.listClientWidth + 1, 'No horizontal file-panel/list overflow: ' + JSON.stringify(m));
  assert.equal(m.ellipsis, 'ellipsis'); assert.equal(m.whiteSpace, 'nowrap');
  assert(m.title.endsWith(m.filename) && m.aria === 'Remove ' + m.filename, 'Full filename is available by title and accessible button name');
}
async function retained(page) {
  return page.evaluate(() => {const s = ModelViewer.getState(); return {modelId: s.modelId, loadedPaths: s.loadedPaths, token: ModelViewer.getEditingMetadata().token, authoring: ModelViewer.getAuthoringState(), camera: s.camera, mesh: s.meshTools, texture: s.textureTools, quality: s.quality, width: localStorage.getItem('elichika.viewer.files-width.v1')};});
}
async function scaleText(page, selector) {
  await page.locator(selector).evaluate(root => {const sizes = [root, ...root.querySelectorAll('*')].map(e => [e, parseFloat(getComputedStyle(e).fontSize)]); sizes.forEach(([e, size]) => {e.style.fontSize = size * 2 + 'px';});});
  await frames(page);
}
async function generic(page, schema, report, touch) {
  const spec = schema.tools.find(t => t.fields.some(f => f.type === 'paths'));
  const field = spec.fields.find(f => f.type === 'paths'), mode = field.mode || (spec.modes || ['single'])[0];
  await page.evaluate(() => ElichikaNavigation.showSection('tools'));
  await page.locator('#tool-list button[data-id=' + JSON.stringify(spec.id) + ']').click();
  const choice = page.locator('.mode-toggle button[data-mode=' + JSON.stringify(mode) + ']'); if (await choice.count()) await choice.click();
  const input = page.locator('#tool-form input[data-ftype="paths"][data-name=' + JSON.stringify(field.name) + ']');
  await page.locator('[data-paths-add=' + JSON.stringify(field.name) + ']').click();
  await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
  await page.locator('#picker-roots button').filter({hasText: /^extracted$/}).click();
  await page.waitForFunction(folder => document.getElementById('picker-crumb').textContent === folder, extracted);
  await page.locator('#picker-entries li[role="button"]').filter({hasText: /^📁3d_model$/}).click();
  await page.waitForFunction(folder => document.getElementById('picker-crumb').textContent === folder, models);
  for (const source of sources) await page.locator('#picker-entries input[data-path=' + JSON.stringify(source) + ']').check();
  await page.locator('#picker-add-selected').click();
  assert.equal(await input.inputValue(), sources.join('\n'));
  await input.evaluate(e => {window.__pickerChanges = 0; e.addEventListener('change', () => window.__pickerChanges++);});
  if (!touch) await scaleText(page, '.multi-list');
  const fieldRoot = input.locator('..'), remove = fieldRoot.locator('.multi-rm');
  const metrics = [];
  for (let i = 0; i < sources.length; i++) {const m = await metric(remove.nth(i)); contained(m, touch ? 44 : 34); metrics.push(m);}
  await fieldRoot.screenshot({path: path.join(evidence, touch ? 'generic-touch.png' : 'generic-200-percent-text.png')});
  await remove.nth(0).focus(); await page.keyboard.press('Enter');
  assert.equal(await input.inputValue(), sources.slice(1).join('\n'));
  assert(await remove.nth(0).evaluate(e => document.activeElement === e), 'First removal focuses next filename');
  await remove.nth(1).focus(); await page.keyboard.press('Space');
  assert.equal(await input.inputValue(), sources[1]);
  assert(await remove.nth(0).evaluate(e => document.activeElement === e), 'Last row removal focuses previous filename');
  await page.keyboard.press('Enter'); assert.equal(await input.inputValue(), '');
  assert(await page.locator('[data-paths-add=' + JSON.stringify(field.name) + ']').evaluate(e => document.activeElement === e), 'Empty list returns focus to Add files');
  assert.equal(await page.evaluate(() => window.__pickerChanges), 3);
  assert.equal(await page.evaluate(name => collectParams()[name], field.name), '');
  report.push({name: touch ? 'coarse selected-files rows' : '200% selected-files rows', metrics});
}
async function macLayout(browser, url, profile, report) {
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}}), page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.addInitScript(profile => {
    window.__macCalls = []; window.ElichikaDesktop = {platform: 'macos', version: 1, language: 'en', viewerFilesWidth: profile.width,
      capabilities: ['setSection', 'openFiles', 'setViewerFilesWidth', 'setPanelSettings'],
      panelSettings: {viewer: {hidden: [], order: ['viewer-expression-adjustments', 'viewer-adjustments', 'viewer-save-panel', 'viewer-display-options']}}};
    window.webkit = {messageHandlers: {elichika: {postMessage(message) {__macCalls.push(message); setTimeout(() => ElichikaPlatform.receive({id: message.id, result: message.action === 'openFiles' ? {cancelled: true} : {ok: true}}), 0);}}}};
  }, profile);
  try {
    await init(page, url + '/?embedded=1', profile.width); await load(page);
    assert(await page.evaluate(() => ElichikaPlatform.info().native && document.documentElement.classList.contains('elichika-macos')));
    const positions = await page.evaluate(() => {
      const ids = ['viewer-display-options', 'viewer-save-panel'];
      return {parents: ids.map(id => document.getElementById(id).parentElement.id), order: Array.from(document.getElementById('viewer-files-panel').children).filter(e => !e.hidden && !e.classList.contains('sr-only')).map(e => e.id || e.className), right: Array.from(document.querySelectorAll('#viewer-control-panel > details[id]')).map(e => e.id), hud: !!document.querySelector('#viewer-stage-tools-top .viewer-primary-tools #viewer-pose-basic')};
    });
    assert.deepStrictEqual(positions.parents, ['viewer-macos-display-slot', 'viewer-macos-save-slot']);
    assert(positions.order.indexOf('viewer-macos-display-slot') < positions.order.indexOf('viewer-file-actions'));
    assert(positions.order.indexOf('viewer-macos-save-slot') > positions.order.indexOf('viewer-file-options'));
    assert.deepStrictEqual(positions.right.slice(0, 2), ['viewer-expression-adjustments', 'viewer-adjustments'], 'Existing right-column order preference stays applied');
    assert(positions.hud, 'Pose and quality HUD stays attached to canvas');
    assert.equal(await page.locator('#viewer-display-options').evaluate(e => e.open), false);
    assert.equal(await page.locator('#viewer-save-panel').evaluate(e => e.open), false);
    await page.locator('#viewer-files-panel').screenshot({path: path.join(evidence, 'mac-' + profile.width + '-default-order.png')});
    const before = await retained(page), stage = await page.locator('#viewer-stage').boundingBox();
    await page.locator('#viewer-display-options > summary').click();
    await page.locator('#viewer-save-panel > summary').scrollIntoViewIfNeeded(); await page.locator('#viewer-save-panel > summary').click();
    if (profile.text === 2) await scaleText(page, '#viewer-files-panel');
    const overflow = await page.locator('#viewer-files-panel').evaluate(panel => {
      const p = panel.getBoundingClientRect();
      return {client: panel.clientWidth, scroll: panel.scrollWidth, controls: Array.from(panel.querySelectorAll('input,select,button')).filter(e => e.getClientRects().length).map(e => {const r = e.getBoundingClientRect(); return {id: e.id, left: r.left, right: r.right, width: r.width, inside: r.left >= p.left && r.right <= p.right};})};
    });
    assert(overflow.scroll <= overflow.client + 1, 'Open display/save forms have no horizontal overflow: ' + JSON.stringify(overflow));
    assert(overflow.controls.every(c => c.inside), 'Every display/save/import control fits the sidebar: ' + JSON.stringify(overflow));
    await menu(page); const remove = await metric(page.locator('#viewer-file-list .viewer-remove').first()); contained(remove, 32);
    await page.locator('#viewer-file-list .viewer-remove').first().focus(); await page.keyboard.press('Enter');
    assert.deepStrictEqual(await retained(page), before, 'Left-sidebar layout and selected path removal retain model state');
    assert.deepStrictEqual(await page.locator('#viewer-stage').boundingBox(), stage, 'Opening sidebar cards preserves the canvas rectangle');
    await page.locator('#viewer-model-files > summary').click();
    await page.locator('#viewer-display-options > summary').scrollIntoViewIfNeeded();
    await page.locator('#viewer-files-panel').screenshot({path: path.join(evidence, 'mac-' + profile.width + '-text-' + profile.text + '-display.png')});
    await page.locator('#viewer-save-panel > summary').scrollIntoViewIfNeeded();
    await page.locator('#viewer-files-panel').screenshot({path: path.join(evidence, 'mac-' + profile.width + '-text-' + profile.text + '-save.png')});
    await page.locator('#viewer-panel-settings').scrollIntoViewIfNeeded(); await page.locator('#viewer-panel-settings').click();
    const row = id => page.locator('#viewer-panel-settings-dialog [data-panel-id=' + JSON.stringify(id) + ']');
    for (const id of ['viewer-display-options', 'viewer-save-panel']) {await row(id).locator('input').uncheck(); assert(await page.locator('#' + id).evaluate(e => e.classList.contains('panel-setting-hidden')));}
    const prefs = await page.evaluate(() => JSON.parse(localStorage.getItem('elichika.panels.viewer.v1')));
    assert(prefs.hidden.includes('viewer-display-options') && prefs.hidden.includes('viewer-save-panel'));
    assert(await page.evaluate(() => __macCalls.some(m => m.action === 'setPanelSettings' && m.panelSettings.hidden.includes('viewer-save-panel'))));
    for (const id of ['viewer-display-options', 'viewer-save-panel']) await row(id).locator('input').check();
    await page.locator('#viewer-panel-settings-dialog button').filter({hasText: /^Close$/}).click();
    await page.waitForFunction(() => !document.getElementById('viewer-panel-settings-dialog').open);
    assert(await page.locator('#viewer-display-options').evaluate(e => e.open) && await page.locator('#viewer-save-panel').evaluate(e => e.open), 'Preference hide/show retains disclosure state');
    await page.locator('#viewer-files-resizer').focus(); await page.keyboard.press('ArrowLeft');
    assert(await page.evaluate(() => __macCalls.some(m => m.action === 'setViewerFilesWidth' && m.width >= 160 && m.width <= 360)), 'Native sidebar-width bridge still receives bounded resize preferences');
    if (profile.width === 360 && profile.text === 1) {
      await load(page); // Resolve the deliberately changed file selection before saving.
      await (await show(page.locator('#viewer-editor-node-tab'))).click(); await (await show(page.locator('#viewer-node-filter'))).selectOption('all');
      const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'HipsSize').node); await page.locator('#viewer-node').selectOption(String(node));
      const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]'); await field.fill('1.17'); await field.dispatchEvent('change');
      assert(await page.locator('#viewer-save').isEnabled(), 'Valid edits can still be saved from the relocated card');
      await (await show(page.locator('#viewer-save'))).click();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.outputPaths.length > 0);
      const saved = await page.evaluate(() => ModelViewer.getState().persistence); assert(saved.outputPaths.every(file => file.startsWith(library)));
      report.push({name: 'Relocated Mac Save edited copy performs real export', outputPaths: saved.outputPaths, recipePath: saved.recipePath});
    }
    await page.locator('#viewer-stage').scrollIntoViewIfNeeded(); await page.waitForFunction(() => ModelViewer.getState().layout.stageVisible);
    const probe = await page.evaluate(() => ModelViewer.renderProbe(33)); assert(probe.ready && probe.glError === 0 && probe.nonBackgroundSamples > 0, 'The neutral model remains rendered in the unchanged canvas: ' + JSON.stringify(probe));
    assert.deepStrictEqual(errors, []); report.push({name: 'Mac native bridge layout ' + profile.width + 'px / ' + profile.text * 100 + '% text', positions, overflow, remove, prefs, probe});
  } finally {await context.close();}
}
async function main() {
  const report = {status: 'RUNNING', scope: 'Host Chromium, actual app HTTP/Unity and public controls. 200% computed text sizes; no native macOS execution.', cases: []}; let server, browser;
  try {
    server = await startServer(); browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
    const schema = await (await fetch(server.url + '/api/tools?lang=en')).json(), errors = [];
    if (process.env.BASELINE_STATIC_DIR) {
      const context = await browser.newContext({viewport: {width: 1600, height: 1000}}), page = await context.newPage();
      await page.route('**/static/style.css', route => route.fulfill({path: path.join(process.env.BASELINE_STATIC_DIR, 'style.css'), contentType: 'text/css'}));
      await init(page, server.url, 360); await load(page); await menu(page);
      const m = await metric(page.locator('#viewer-file-list .viewer-remove').first());
      assert(m.right > m.panel.right || !m.hit || m.panel.scrollWidth > m.panel.clientWidth + 1, 'Captured baseline reproduces clipping/overflow');
      await page.screenshot({path: path.join(evidence, 'baseline-sidebar-360.png')}); report.baseline = m; await context.close();
    }
    for (const profile of [{width: 360, text: 1}, {width: 196, text: 1}, {width: 360, text: 2}, {width: 196, text: 2}]) {
      const context = await browser.newContext({viewport: {width: 1600, height: 1000}}), page = await context.newPage(); let prepares = 0;
      page.on('pageerror', e => errors.push(String(e.stack || e))); page.on('request', request => {if (request.url().includes('/api/viewer/prepare')) prepares++;});
      await init(page, server.url, profile.width); await load(page);
      assert.deepStrictEqual(await page.evaluate(() => ['viewer-display-options', 'viewer-save-panel'].map(id => document.getElementById(id).parentElement.id)), ['viewer-control-panel', 'viewer-control-panel'], 'Standalone browser keeps both cards in its existing right column');
      await (await show(page.locator('#viewer-editor-node-tab'))).click();
      await (await show(page.locator('#viewer-node-filter'))).selectOption('all');
      const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'HipsSize').node);
      await page.locator('#viewer-node').selectOption(String(node));
      const scale = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]'); await scale.fill('1.17'); await scale.dispatchEvent('change');
      await menu(page); if (profile.text === 2) await scaleText(page, '#viewer-files-panel');
      const metrics = [];
      for (let i = 0; i < sources.length; i++) {const m = await metric(page.locator('#viewer-file-list .viewer-remove').nth(i)); contained(m, 32); metrics.push(m);}
      assert(metrics[0].nameScrollWidth > metrics[0].nameClientWidth, 'Long filename uses bounded ellipsis');
      await page.screenshot({path: path.join(evidence, 'sidebar-' + profile.width + '-text-' + profile.text + '.png')});
      const before = await retained(page), count = prepares, remove = page.locator('#viewer-file-list .viewer-remove');
      await remove.first().focus(); await page.keyboard.press('Enter'); await frames(page);
      assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().paths), sources.slice(1));
      assert.deepStrictEqual(await retained(page), before, 'Removing selected loaded model preserves loaded scene, edits, camera, identity and panel preference');
      assert.equal(prepares, count, 'Changing selected paths does not prepare or reload the model');
      assert(await remove.first().evaluate(e => e === document.activeElement), 'Viewer removal focuses next filename');
      await remove.nth(1).focus(); await page.keyboard.press('Space');
      assert(await remove.first().evaluate(e => e === document.activeElement), 'Viewer last-row removal focuses previous filename');
      await page.keyboard.press('Enter'); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().paths), []);
      assert(await page.locator('#viewer-add').evaluate(e => e === document.activeElement), 'Empty viewer list focuses Add file');
      assert.deepStrictEqual(await retained(page), before); assert.equal(prepares, count);
      report.cases.push({name: 'sidebar ' + profile.width + 'px, text ' + profile.text * 100 + '%', metrics, retained: before});
      if (profile.width === 360 && profile.text === 1) await generic(page, schema, report.cases, false);
      await context.close();
    }
    const touchContext = await browser.newContext({viewport: {width: 360, height: 720}, isMobile: true, hasTouch: true}), touch = await touchContext.newPage();
    touch.on('pageerror', e => errors.push(String(e.stack || e))); await init(touch, server.url, 196); await generic(touch, schema, report.cases, true); await touchContext.close();
    const macContext = await browser.newContext({viewport: {width: 1280, height: 900}}), mac = await macContext.newPage();
    await mac.addInitScript(sources => {
      window.__macCalls = []; window.ElichikaDesktop = {platform: 'macos', version: 1, language: 'en', capabilities: ['setSection', 'openFiles']};
      window.webkit = {messageHandlers: {elichika: {postMessage(message) {__macCalls.push(message); setTimeout(() => ElichikaPlatform.receive({id: message.id, result: message.action === 'openFiles' ? {paths: sources} : {}}), 0);}}}};
    }, sources);
    await init(mac, server.url + '/?embedded=1', 360); await mac.evaluate(() => ElichikaNavigation.showSection('viewer'));
    await mac.evaluate(() => ElichikaPlatform.perform('openModel')); await mac.waitForFunction(() => ModelViewer.getState().loadedPaths.length === 3 && !ModelViewer.getState().loading);
    const calls = await mac.evaluate(() => __macCalls.filter(m => m.action === 'openFiles'));
    assert.equal(calls.length, 1); assert.equal(calls[0].multiple, true);
    assert(await mac.locator('#picker').evaluate(e => e.classList.contains('hidden')));
    report.cases.push({name: 'Mac openFiles bridge protocol fixture (not native OS execution)', calls}); await macContext.close();
    for (const profile of [{width: 360, text: 1}, {width: 196, text: 1}, {width: 360, text: 2}, {width: 196, text: 2}]) await macLayout(browser, server.url, profile, report.cases);
    assert.deepStrictEqual(errors, []); assert.deepStrictEqual(sources.map(sha), sourceHashes, 'Original files remain unchanged');
    report.sourceFiles = sources.map((file, i) => ({name: path.basename(file), sha256: sourceHashes[i]})); report.status = 'PASS';
  } catch (error) {report.status = 'FAIL'; report.error = String(error.stack || error); throw error;}
  finally {if (browser) await browser.close(); if (server) {server.child.kill(); server.stream.end();} fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({status: report.status, cases: report.cases.length, evidence, error: report.error}));}
}
main().catch(() => {process.exitCode = 1;});
