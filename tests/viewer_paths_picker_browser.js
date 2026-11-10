/* Every actual tools schema uses the same bounded multi-file picker.
 * Real filesystem/HTTP and input events; no successful API response is mocked.
 * Native bridge semantics are exercised separately by the packaged app QA. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const {spawn} = require('child_process');
const {chromium} = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-paths-picker-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-paths-library-')), extracted = path.join(library, 'extracted');
fs.mkdirSync(evidence, {recursive: true}); fs.mkdirSync(path.join(extracted, '3d_model'), {recursive: true});
fs.mkdirSync(path.join(library, 'modded'), {recursive: true});
fs.mkdirSync(path.join(library, 'suit'), {recursive: true});
const raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_textured_triangle.unity'));
const originals = [];
function bundle(folder, name) {fs.mkdirSync(folder, {recursive: true}); const file = path.join(folder, name); fs.writeFileSync(file, raw); originals.push(file); return file;}
const files = {alpha: bundle(extracted, 'alpha.unity'), beta: bundle(extracted, 'beta.unity'), gamma: bundle(extracted, 'gamma.unity'),
  delta: bundle(path.join(extracted, 'nested'), 'delta.unity')};
const limit = path.join(extracted, 'exactly128'), overflow = path.join(extracted, 'too-many129'), touchFolder = path.join(extracted, 'touch');
for (let i = 0; i < 128; i++) bundle(limit, 'costume-' + String(i).padStart(3, '0') + '.unity');
for (let i = 0; i < 129; i++) bundle(overflow, 'costume-' + String(i).padStart(3, '0') + '.unity');
const touchFiles = [bundle(touchFolder, 'a-very-long-costume-bundle-name-that-must-wrap-without-hiding-the-checkbox-or-its-touch-target.unity'), bundle(touchFolder, 'second.unity')];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), sha = b => crypto.createHash('sha256').update(b).digest('hex');
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {cwd: product, env: {...process.env, SUKUSTA_DIR: library}, stdio: ['ignore', 'pipe', 'pipe']});
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) {if (child.exitCode !== null) throw new Error('Product server exited'); try {if ((await fetch(url + '/api/tools')).ok) return {url, child, stream};} catch (_) {} await sleep(100);}
  child.kill(); throw new Error('Product server did not start');
}
const input = (page, name = 'in_paths') => page.locator('#tool-form input[data-ftype="paths"][data-name="' + name + '"]');
const checkbox = (page, file) => page.locator('#picker-entries input[data-path=' + JSON.stringify(file) + ']');
const selected = page => page.locator('#picker-selection-count').textContent();
async function directory(page, folder) {await page.waitForFunction(folder => document.getElementById('picker-crumb').textContent === folder && !document.getElementById('picker-select-all').disabled, folder);}
async function root(page) {await page.locator('#picker-roots button').filter({hasText: /^extracted$/}).click(); await directory(page, extracted);}
async function folder(page, name, destination) {await page.locator('#picker-entries > li[role="button"]').filter({hasText: name}).click(); await directory(page, destination);}
async function open(page, name = 'in_paths') {await page.locator('[data-paths-add=' + JSON.stringify(name) + ']').click(); await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden')); await root(page);}
async function commit(page) {await page.locator('#picker-add-selected').click(); await page.waitForFunction(() => document.getElementById('picker').classList.contains('hidden'));}
async function tool(page, id, mode) {await page.locator('#tool-list button[data-id=' + JSON.stringify(id) + ']').click(); const choice = page.locator('.mode-toggle button[data-mode=' + JSON.stringify(mode) + ']'); if (await choice.count()) await choice.click();}
async function checkWithKeyboard(page, file) {const target = checkbox(page, file); await target.focus(); await target.press('Space'); assert(await target.isChecked());}
async function main() {
  const report = {status: 'RUNNING', evidence, scope: 'Actual public tool schemas, real jailed filesystem/HTTP and keyboard/touch input. Native OS dialog is not exercised here.', tools: [], cases: []}; let server, browser;
  try {
    server = await startServer(); const schema = await (await fetch(server.url + '/api/tools?lang=en')).json();
    for (const root of Object.values(schema.roots || {})) if (typeof root === 'string' && root.startsWith(library + path.sep)) fs.mkdirSync(root, {recursive: true});
    const specs = schema.tools.flatMap(tool => (tool.modes || ['single']).flatMap(mode => tool.fields.filter(field => field.type === 'paths' && (!field.mode || field.mode === mode)).map(field => ({tool: tool.id, mode, name: field.name}))));
    assert(specs.length > 5, 'Use every actual tool exposing a paths field');
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}}); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = [], dialogs = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.on('dialog', async dialog => {dialogs.push(dialog.message()); await dialog.accept();}); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openPicker === 'function' && document.querySelector('#tool-list button'));
    const first = specs[0]; await tool(page, first.tool, first.mode);
    await input(page, first.name).evaluate(element => {element.dataset.batchChanges = '0'; element.addEventListener('change', () => {element.dataset.batchChanges = String(Number(element.dataset.batchChanges) + 1);});});
    await open(page, first.name); await checkWithKeyboard(page, files.alpha);
    assert.equal(await input(page, first.name).inputValue(), '', 'Checkbox edits do not change the tool before confirmation');
    const nested = page.locator('#picker-entries > li[role="button"]').filter({hasText: /^📁nested$/}); await nested.focus(); await nested.press('Enter'); await directory(page, path.dirname(files.delta));
    assert((await selected(page)).includes('1')); await checkWithKeyboard(page, files.delta); await root(page);
    assert(await checkbox(page, files.alpha).isChecked(), 'Selections survive navigating to another folder and back');
    await checkWithKeyboard(page, files.beta); await commit(page);
    const initial = [files.alpha, files.delta, files.beta].join('\n'); assert.equal(await input(page, first.name).inputValue(), initial);
    assert.equal(await input(page, first.name).getAttribute('data-batch-changes'), '1', 'One confirmation publishes one atomic field change');
    await open(page, first.name); await checkbox(page, files.alpha).check(); await checkbox(page, files.beta).check(); await commit(page);
    assert.equal(await input(page, first.name).inputValue(), initial); assert.equal(await input(page, first.name).getAttribute('data-batch-changes'), '1', 'Adding existing files never duplicates or publishes a spurious change');
    for (const cancel of ['Escape', 'button']) {await open(page, first.name); await checkbox(page, files.gamma).check(); if (cancel === 'Escape') await page.keyboard.press('Escape'); else await page.locator('#picker-cancel').click(); assert(await page.locator('#picker').evaluate(e => e.classList.contains('hidden'))); assert.equal(await input(page, first.name).inputValue(), initial); assert(await page.locator('[data-paths-add=' + JSON.stringify(first.name) + ']').evaluate(element => document.activeElement === element), 'Cancel returns keyboard focus to the Add files control');}
    report.cases.push('keyboard selection, cross-folder retention, single confirmation, duplicates and two cancellation paths');
    await open(page, first.name); await page.locator('#picker-select-all').click(); assert.equal(await page.locator('#picker-select-all').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#picker-entries input:checked').count(), 3); await page.locator('#picker-select-all').click(); assert.equal(await page.locator('#picker-entries input:checked').count(), 0);
    await checkbox(page, files.alpha).check(); await folder(page, /^📁nested$/, path.dirname(files.delta)); await checkbox(page, files.delta).check(); await page.locator('#picker-clear-selection').click(); assert((await selected(page)).includes('0')); assert(await page.locator('#picker-add-selected').isDisabled()); await root(page); assert(!await checkbox(page, files.alpha).isChecked());
    await folder(page, /^📁exactly128$/, limit); await page.locator('#picker-select-all').click(); assert((await selected(page)).includes('128')); await root(page);
    await checkbox(page, files.gamma).click(); assert(!await checkbox(page, files.gamma).isChecked()); assert((await selected(page)).includes('128')); assert.equal(dialogs.length, 1);
    await commit(page); assert.equal((await input(page, first.name).inputValue()).split('\n').length, 131, 'The128 bound applies to one selection, not the accumulated field');
    await open(page, first.name); await folder(page, /^📁too-many129$/, overflow); await page.locator('#picker-select-all').click(); assert((await selected(page)).includes('0')); assert(await page.locator('#picker-add-selected').isDisabled()); assert.equal(dialogs.length, 2, 'A too-large folder selection is rejected atomically'); await page.locator('#picker-cancel').click();
    const field = input(page, first.name).locator('..'); await field.locator('.multi-list li').filter({hasText: 'alpha.unity'}).locator('.multi-rm').click();
    assert.equal((await input(page, first.name).inputValue()).split('\n').length, 130); assert(!(await input(page, first.name).inputValue()).split('\n').includes(files.alpha));
    report.cases.push('folder select/deselect, cross-folder clear, per-selection128 bound, no new total bound and existing individual removal');
    // Delay only completion of genuine HTTP bytes, then navigate elsewhere.
    await open(page, first.name); await checkbox(page, files.alpha).check(); let release, arrived;
    const received = new Promise(resolve => {arrived = resolve;});
    const gate = new Promise(resolve => {release = resolve;}); const pattern = '**/api/fs/list?path=' + encodeURIComponent(path.dirname(files.delta));
    await page.route(pattern, async route => {const response = await route.fetch(); const body = await response.body(); arrived(); await gate; await route.fulfill({response, body});});
    await page.locator('#picker-entries > li[role="button"]').filter({hasText: /^📁nested$/}).click(); await received; assert(await page.locator('#picker-add-selected').isDisabled());
    await root(page); release(); await page.waitForTimeout(80); assert.equal(await page.locator('#picker-crumb').textContent(), extracted); assert(await checkbox(page, files.alpha).isChecked()); assert((await selected(page)).includes('1')); await page.unroute(pattern); await page.locator('#picker-cancel').click();
    report.cases.push('a delayed actual directory response cannot replace the latest folder or its retained selection');
    await open(page, first.name); await checkbox(page, files.alpha).check();
    await input(page, first.name).evaluate(element => {element.addEventListener('change', () => openPicker('dir', () => {}, 'models'), {once: true});});
    await page.locator('#picker-add-selected').click();
    await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden') && document.getElementById('picker-title').textContent === 'Choose a folder' && !document.getElementById('picker-use-folder').disabled);
    assert(await page.locator('#picker-multi-controls').evaluate(element => element.hidden), 'An old multi-picker completion cannot close or overwrite a new folder-picker session');
    await page.locator('#picker-cancel').click();
    report.cases.push('a reentrant real field change opens a new picker without being closed by the old batch confirmation');
    for (const spec of specs) {
      await tool(page, spec.tool, spec.mode); const before = await input(page, spec.name).inputValue(); const expected = before ? before.split('\n') : [];
      await input(page, spec.name).evaluate(element => {element.dataset.schemaChanges = '0'; element.addEventListener('change', () => {element.dataset.schemaChanges = String(Number(element.dataset.schemaChanges) + 1);});});
      await open(page, spec.name); await checkbox(page, files.alpha).check(); await checkbox(page, files.beta).check();
      assert.equal(await input(page, spec.name).inputValue(), before); await commit(page);
      const merged = [...expected]; for (const file of [files.alpha, files.beta]) if (!merged.includes(file)) merged.push(file);
      assert.equal(await input(page, spec.name).inputValue(), merged.join('\n'));
      assert.equal(await page.evaluate(name => collectParams()[name], spec.name), merged.join('\n'), 'The real run parameter collector receives every selected file');
      assert.equal(await input(page, spec.name).getAttribute('data-schema-changes'), merged.length > expected.length ? '1' : '0'); report.tools.push(spec);
    }
    assert.deepStrictEqual(errors, []); assert.deepStrictEqual(dialogs, ['You can select up to 128 files at once.', 'You can select up to 128 files at once.']); await context.close();
    const touchContext = await browser.newContext({viewport: {width: 360, height: 640}, deviceScaleFactor: 2, hasTouch: true, isMobile: true}); await touchContext.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    const touch = await touchContext.newPage(); touch.on('pageerror', e => errors.push(String(e.stack || e))); await touch.goto(server.url); await touch.waitForFunction(() => document.querySelector('#tool-list button'));
    await tool(touch, first.tool, first.mode); await touch.locator('[data-paths-add=' + JSON.stringify(first.name) + ']').tap(); await touch.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden')); await root(touch); await folder(touch, /^📁touch$/, touchFolder);
    report.touch = [];
    for (const file of touchFiles) {
      const label = checkbox(touch, file).locator('..'); await label.scrollIntoViewIfNeeded();
      const metric = await label.evaluate(e => {const r = e.getBoundingClientRect(), v = visualViewport, hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return {x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom, viewport: {width: v.width, height: v.height}, hit: hit === e || e.contains(hit)};});
      assert(metric.width >= 44 && metric.height >= 44 && metric.hit && metric.x >= -1 && metric.right <= metric.viewport.width + 1 && metric.y >= -1 && metric.bottom <= metric.viewport.height + 1, JSON.stringify(metric));
      await label.tap(); assert(await checkbox(touch, file).isChecked()); report.touch.push(metric);
    }
    assert.equal(await input(touch, first.name).inputValue(), ''); await touch.locator('#picker-add-selected').tap(); await touch.waitForFunction(() => document.getElementById('picker').classList.contains('hidden')); assert.equal(await input(touch, first.name).inputValue(), touchFiles.join('\n'));
    assert.equal(await touch.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1), false);
    await touch.screenshot({path: path.join(evidence, 'touch-confirmed-files.png')}); await touchContext.close();
    assert.deepStrictEqual(errors, []); assert(originals.every(file => sha(fs.readFileSync(file)) === sha(raw)), 'The original Unity files are unchanged'); report.dialogs = dialogs; report.status = 'PASS';
  } catch (error) {report.status = 'FAIL'; report.error = String(error.stack || error); throw error;}
  finally {if (browser) await browser.close(); if (server) {server.child.kill(); server.stream.end();} fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({status: report.status, evidence, tools: report.tools.length, error: report.error}));}
}
main().catch(() => {process.exitCode = 1;});
