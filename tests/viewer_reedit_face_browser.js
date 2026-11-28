/* Rina board held face rows, the face option of a costume ZIP that includes
 * its face, named pair refusals, save notes and "Re-edit from original"
 * through the product viewer page (Korean UI, one Japanese case).
 *
 * Fixture cases run on the neutral serialized fixtures with a real isolated
 * server. Some responses are deliberately extended there, and say so: the
 * prepare response gains held face rows and an included face (a neutral
 * fixture has no Rina face), one restore response gains a release notice,
 * export jobs fail with a pair refusal, one save result gains an automatic
 * face original, one Mod ZIP result gains a kept-parts note and one install
 * job fails with the Elichika installer's own summary.
 *
 * With ELICHIKA_ROOT (an Elichika tree with assets/db and static), the real
 * cases import member suits from Game assets (no download) and drive Save ->
 * Re-edit from original -> Save mod ZIP, and package Rina 302092002's Normal
 * face view as a scene, reopen it in the board view and Save mod ZIP with the
 * face option as it opens, with nothing replaced.
 * Run with VIEWER_PYTHON selecting a Python with the product dependencies. */
'use strict';
const assert = require('assert'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');

const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-reedit-face-evidence-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', cases: [] };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const libraries = [];

async function startServer({ cwd = product, library, pythonPath } = {}) {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server-' + port + '.log'));
  const env = { ...process.env, SUKUSTA_DIR: library };
  if (pythonPath) env.PYTHONPATH = pythonPath;
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let attempt = 0; attempt < 200; attempt++) {
    if (child.exitCode !== null) throw new Error('Isolated product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* starting */ }
    await wait(100);
  }
  child.kill('SIGTERM'); throw new Error('Isolated product server did not become ready');
}

async function stopServer(server) {
  if (!server) return;
  if (server.child.exitCode === null) {
    const stopped = new Promise(resolve => server.child.once('exit', resolve));
    server.child.kill('SIGTERM'); await Promise.race([stopped, wait(1500)]);
  }
  server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end();
}

async function show(page, selector) {
  const locator = page.locator(selector);
  await locator.evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await locator.scrollIntoViewIfNeeded();
  return locator;
}

async function openPage(browser, url, autoFace, language = 'ko') {
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage(), errors = [];
  page.setDefaultTimeout(240000); page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(value => localStorage.setItem('sifas_lang', value), language);
  await page.goto(url);
  await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ModelViewer && !!window.ViewerPersistence);
  await page.locator('.tab[data-tab="viewer"]').click();
  await page.evaluate(value => { document.getElementById('viewer-auto-face').checked = value; }, autoFace);
  const strings = await page.evaluate(async value => (await (await fetch('/api/i18n?lang=' + value)).json()).strings, language);
  return { page, context, errors, strings };
}

async function openModel(page, paths) {
  await page.evaluate(paths => openModelViewer(paths), paths);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading &&
    ModelViewer.getEditingMetadata() && ModelViewer.getEditingMetadata().available);
}

const persistence = page => page.evaluate(() => ModelViewer.getState().persistence);
const statusText = async page => (await page.locator('#viewer-save-status').innerText()).trim();

async function setScale(page, values) {
  const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
  const target = metadata.nodes.find(node => node.name === 'LeftUpLeg');
  const tab = target.recommendedMethod === 'mesh' ? '#viewer-editor-mesh-tab' : '#viewer-editor-node-tab';
  if (await page.locator(tab).count()) await (await show(page, tab)).click();
  const listed = await page.locator('#viewer-node').evaluate((select, id) => Array.from(select.options).some(option => option.value === id), String(target.node));
  if (!listed) {
    await show(page, '#viewer-node-filter');
    await page.locator('#viewer-node-search').fill('');
    await page.locator('#viewer-node-filter').selectOption('all');
  }
  await show(page, '#viewer-node');
  await page.locator('#viewer-node').selectOption(String(target.node));
  for (let index = 0; index < 3; index++) {
    const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="' + 'XYZ'[index] + '"]');
    await input.fill(String(values[index])); await input.dispatchEvent('change');
  }
}

async function clickSave(page) {
  await (await show(page, '#viewer-save')).click();
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && (ModelViewer.getState().persistence.status === 'done' || ModelViewer.getState().persistence.error));
  const saved = await persistence(page);
  assert(!saved.error, saved.error);
  return saved;
}

async function fixtureCases(browser) {
  const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-reedit-face-library-')); libraries.push(library);
  const setup = spawnSync(python, [path.join(__dirname, 'inspect_viewer_persistence.py'), library, '--setup'], { cwd: product, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  const fixtures = JSON.parse(setup.stdout);
  const server = await startServer({ library });
  try {
    const { page, context, errors, strings } = await openPage(browser, server.url, false);
    const heldRows = [{ id: '7:0:1', factor: 1, absolute: 40 }, { id: '7:0:2', factor: 1, absolute: 20 }, { id: '7:0:3', factor: 0.5 }];
    // Injected: a neutral fixture has no Rina face, so the server holds none.
    await page.route('**/api/viewer/prepare', async route => {
      const response = await route.fetch(), json = await response.json();
      if (json.editing) {
        json.editing.heldFaceOutlines = { count: 3, meshes: ['Eye', 'Mouth'], rows: heldRows };
        Object.assign(json.editing.modPackaging, { hasFaceCompanions: true, faceIncluded: true });
      }
      await route.fulfill({ response, json });
    });
    await openModel(page, [fixtures.raw]);
    await page.unroute('**/api/viewer/prepare');
    // A costume ZIP that includes its own face opens with the face option on.
    const faceOption = await show(page, '#viewer-mod-include-face');
    await page.waitForFunction(() => document.getElementById('viewer-mod-include-face').checked);
    assert.equal(await faceOption.isDisabled(), false);
    const included = strings["This costume ZIP includes its own face, so it is included by default. Only this costume uses it; other costumes and the character's shared face stay unchanged."];
    assert(/[가-힣]/.test(included));
    assert.equal((await page.locator('#viewer-mod-face-help').innerText()).trim(), included);
    report.cases.push({ name: 'included face option default (ko)', help: included });
    const note = page.locator('#viewer-save-held-note');
    await page.waitForFunction(() => !document.getElementById('viewer-save-held-note').hidden);
    await show(page, '#viewer-save-held-note');
    assert.equal(await note.isVisible(), true, 'The board view shows the held face rows');
    const expectedNote = strings['{count} face outline edits made in the Normal face view are kept ({meshes}).'].replace('{count}', '3').replace('{meshes}', 'Eye, Mouth');
    assert.equal((await note.innerText()).trim(), expectedNote);
    assert(/[가-힣]/.test(expectedNote), 'The note is Korean');
    assert.equal(await statusText(page), strings['Model changes'] + ': 3', 'Held rows count as model changes');
    assert((await page.locator('#viewer-mod-name').inputValue()).includes(strings['Outlines']), 'The suggested mod name names the held outline edits');
    await page.screenshot({ path: path.join(evidence, 'held-note-ko.png') });
    report.cases.push({ name: 'held note (ko)', note: expectedNote });

    // A pair refusal naming one mesh is translated with the name kept.
    await page.route('**/api/viewer/edit/export', route => route.fulfill({ json: { job_id: 'abcdef012345' } }));
    await page.route('**/api/jobs/abcdef012345/events', route => route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream' },
      body: 'data: ' + JSON.stringify({ type: 'done', status: 'error', summary: 'The counterpart has no unique matching outline mesh: Mask' }) + '\n\n' }));
    await setScale(page, [1.2, 1, 1]);
    await (await show(page, '#viewer-save')).click();
    await page.waitForFunction(() => !!ModelViewer.getState().persistence.error);
    const refusal = strings['The counterpart has no unique matching outline mesh: {name}'].replace('{name}', 'Mask');
    assert.equal(await statusText(page), refusal);
    await page.unroute('**/api/jobs/abcdef012345/events');
    report.cases.push({ name: 'named pair refusal (ko)', status: refusal });
    // The job's {text, values} message is shown, whatever its summary says.
    await page.route('**/api/jobs/abcdef012345/events', route => route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream' },
      body: 'data: ' + JSON.stringify({ type: 'message', text: 'The counterpart has no unique matching physics component: {name}', values: { name: 'HairA1_Dyna' } }) + '\n\n' +
        'data: ' + JSON.stringify({ type: 'done', status: 'error', summary: 'Refused.' }) + '\n\n' }));
    await (await show(page, '#viewer-save')).click();
    await page.waitForFunction(() => !!ModelViewer.getState().persistence.error && !ModelViewer.getState().persistence.busy);
    const physicsRefusal = strings['The counterpart has no unique matching physics component: {name}'].replace('{name}', 'HairA1_Dyna');
    assert.equal(await statusText(page), physicsRefusal);
    assert.equal((await persistence(page)).error, 'The counterpart has no unique matching physics component: HairA1_Dyna');
    await page.unroute('**/api/viewer/edit/export'); await page.unroute('**/api/jobs/abcdef012345/events');
    report.cases.push({ name: 'pair refusal message event (ko)', status: physicsRefusal });

    // A real save; its recipe restored with an injected release notice.
    const saved = await clickSave(page);
    await page.route('**/api/viewer/edit/restore', async route => {
      const response = await route.fetch(), json = await response.json();
      // Two rows released, one still held: the note follows the response.
      json.heldFaceOutlines = { count: 1, meshes: ['Eye'], rows: heldRows.slice(0, 1) };
      json.notice = { text: 'This recipe sets the face outlines itself; {count} face outline edits made in the Normal face view were released.', values: { count: 2 } };
      await route.fulfill({ response, json });
    });
    const prepared = [];
    const listen = request => { if (request.url().endsWith('/api/viewer/prepare')) prepared.push(JSON.parse(request.postData())); };
    page.on('request', listen);
    // Injected: the save gains an automatically completed face original.
    await page.route('**/api/viewer/edit/result/*', async route => {
      const response = await route.fetch(), json = await response.json();
      if (json.original_paths) {
        json.reedit_paths = json.original_paths.slice(); json.reedit_variants = {}; json.reedit_auto_face = true;
        json.original_paths = json.original_paths.concat([fixtures.morph]);
      }
      await route.fulfill({ response, json });
    });
    const resaved = await clickSave(page);
    await page.unroute('**/api/viewer/edit/result/*');
    assert.equal(resaved.originalPaths.length, saved.originalPaths.length + 1);
    await (await show(page, '#viewer-reedit-original')).click();
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.status === 'restored');
    page.off('request', listen);
    assert.deepStrictEqual(prepared.map(payload => [payload.paths, payload.auto_face]), [[resaved.originalPaths.slice(0, -1), true]],
      'Re-edit reopens only the selected original, with automatic face completion');
    assert.equal(await page.locator('#viewer-auto-face').isChecked(), true);
    const released = strings['This recipe sets the face outlines itself; {count} face outline edits made in the Normal face view were released.'].replace('{count}', '2');
    assert(/[가-힣]/.test(released) && (await statusText(page)).endsWith(released), 'The restore says which face rows it released: ' + await statusText(page));
    assert.equal((await note.innerText()).trim(), strings['1 face outline edit made in the Normal face view is kept ({meshes}).'].replace('{meshes}', 'Eye'),
      'Only the row the restore still holds is shown as kept');
    await page.screenshot({ path: path.join(evidence, 'released-notice-ko.png') });
    report.cases.push({ name: 're-edit button and release notice (ko)', prepared, status: await statusText(page) });
    // Add to game: a Mod ZIP result naming parts kept on this variant, then
    // the Elichika installer's own failure summary.
    await setScale(page, [1.15, 1, 1]);
    // The page sends its language with a package request (?lang=ko), which a
    // '**/api/viewer/edit/package' glob would not match.
    const packageRoute = url => url.pathname === '/api/viewer/edit/package', packageQueries = [];
    await page.route(packageRoute, route => { packageQueries.push(new URL(route.request().url()).search); return route.fulfill({ json: { job_id: 'abcdef0000aa' } }); });
    await page.route('**/api/viewer/edit/install', route => route.fulfill({ json: { job_id: 'abcdef0000bb' } }));
    const stream = body => route => route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream' }, body: 'data: ' + JSON.stringify(body) + '\n\n' });
    await page.route('**/api/jobs/abcdef0000aa/events', stream({ type: 'done', status: 'done', summary: 'ok', output_paths: [] }));
    await page.route('**/api/jobs/abcdef0000bb/events', stream({ type: 'done', status: 'error', summary: 'costume installer failed for /library/suit/Costume-1234.zip (exit 1)' }));
    const packagePath = resaved.previewPaths[0].replace(/[^/]+$/, 'costume-mod.zip');
    await page.route('**/api/viewer/edit/result/abcdef0000aa', route => route.fulfill({ json: {
      output_paths: [packagePath, resaved.recipePath], preview_paths: resaved.previewPaths.slice(), original_paths: resaved.originalPaths.slice(),
      recipe_path: resaved.recipePath, recipe: { state: {} }, notes: [{ text: 'Edits of parts that only the selected costume variant has stay on that variant: {names}', values: { names: ['Mask', 'eye_neutral'] } }],
      mod_package: { token: 'a'.repeat(32), package_path: packagePath, installable: true, character_id: 6, variants: [] } } }));
    await (await show(page, '#viewer-save-mod')).click();
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.status === 'done');
    const kept = strings['Edits of parts that only the selected costume variant has stay on that variant: {names}'].replace('{names}', 'Mask' + strings[', '] + 'eye_neutral');
    assert((await statusText(page)).endsWith(kept), 'The Mod ZIP status names the parts kept on this variant: ' + await statusText(page));
    await (await show(page, '#viewer-add-to-game')).click();
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && !!ModelViewer.getState().persistence.error);
    const installer = strings["The costume installer stopped with exit code {code}. Usual causes are missing Elichika settings (config.json) or a Mod ZIP the installer could not find in its costume folder; the server console shows the installer's message."].replace('{code}', '1');
    assert(/[가-힣]/.test(installer));
    assert.equal(await statusText(page), installer);
    assert.deepStrictEqual(packageQueries, ['?lang=ko', '?lang=ko'], 'Save mod ZIP and Add to game each package once through the fixture');
    for (const pattern of [packageRoute, '**/api/viewer/edit/install', '**/api/jobs/abcdef0000aa/events', '**/api/jobs/abcdef0000bb/events', '**/api/viewer/edit/result/abcdef0000aa']) await page.unroute(pattern);
    report.cases.push({ name: 'kept-parts note and installer summary (ko)', kept, installer });
    assert.deepStrictEqual(errors, []);
    await context.close();
    // Japanese lists part names with its own separator.
    const ja = await openPage(browser, server.url, false, 'ja');
    await ja.page.route('**/api/viewer/prepare', async route => {
      const response = await route.fetch(), json = await response.json();
      if (json.editing) json.editing.heldFaceOutlines = { count: 2, meshes: ['Eye', 'Mouth'], rows: heldRows.slice(0, 2) };
      await route.fulfill({ response, json });
    });
    await openModel(ja.page, [fixtures.raw]);
    await ja.page.waitForFunction(() => !document.getElementById('viewer-save-held-note').hidden);
    await show(ja.page, '#viewer-save-held-note');
    const jaNote = ja.strings['{count} face outline edits made in the Normal face view are kept ({meshes}).'].replace('{count}', '2').replace('{meshes}', 'Eye、Mouth');
    assert.equal((await ja.page.locator('#viewer-save-held-note').innerText()).trim(), jaNote);
    // Without an included face the option starts off, as before.
    assert.equal(await ja.page.locator('#viewer-mod-include-face').isChecked(), false);
    report.cases.push({ name: 'held note list separator (ja)', note: jaNote });
    assert.deepStrictEqual(ja.errors, []);
    await ja.context.close();
  } finally { await stopServer(server); }
}

async function realRinaBoard(browser, server) {
  // Normal face view of Rina 302092002: a Mouth outline edit, packaged as a scene with its face.
  const job = await (await fetch(server.url + '/api/viewer/game/import?lang=ko', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: server.url },
    body: JSON.stringify({ region: 'gl', suit: 'suit:302092002', variant: 'unmasked', download: false, purpose: 'viewer', platform: 'android' }) })).json();
  const events = await (await fetch(server.url + '/api/jobs/' + job.job_id + '/events')).text();
  const done = events.split('\n').filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6))).find(item => item.type === 'done');
  assert(done && done.status === 'done' && done.output_paths.length === 1, 'Rina import: ' + JSON.stringify(done));
  const { page, context, errors, strings } = await openPage(browser, server.url, true);
  await openModel(page, done.output_paths);
  const mouth = (await page.evaluate(() => ModelViewer.getEditingMetadata().outlines)).meshes.find(row => row.name === 'Mouth');
  await page.locator('#viewer-outline-card').evaluate(node => { node.open = true; });
  await (await show(page, '#viewer-outline-mesh')).selectOption(mouth.id);
  await (await show(page, '#viewer-outline-number')).fill('140'); await page.locator('#viewer-outline-number').dispatchEvent('input');
  assert.equal(await page.locator('#viewer-mod-include-face').isChecked(), false, 'An automatic face starts off');
  await (await show(page, '#viewer-mod-include-face')).check();
  await (await show(page, '#viewer-save-mod')).click();
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && (ModelViewer.getState().persistence.modPackage || ModelViewer.getState().persistence.error));
  const first = await persistence(page);
  assert(!first.error && /-scene\.zip$/.test(first.modPackage.packagePath), 'Normal face scene Mod ZIP: ' + first.error);
  // Its board view: the face edits are held, the face option starts on, and Save mod ZIP works as it opens.
  await openModel(page, [first.modPackage.packagePath]);
  await page.waitForFunction(() => !document.getElementById('viewer-save-held-note').hidden);
  const option = await show(page, '#viewer-mod-include-face');
  assert.equal(await option.isChecked(), true, 'The board view keeps the included face by default');
  assert.equal(await option.isDisabled(), false);
  const held = (await page.locator('#viewer-save-held-note').innerText()).trim();
  await (await show(page, '#viewer-save-mod')).click();
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && (ModelViewer.getState().persistence.status === 'done' || ModelViewer.getState().persistence.error));
  const board = await persistence(page);
  assert(!board.error, 'Board view Save mod ZIP with the default face option: ' + board.error);
  assert(/-scene\.zip$/.test(board.modPackage.packagePath) && board.modPackage.packagePath !== first.modPackage.packagePath);
  await page.screenshot({ path: path.join(evidence, 'rina-board-mod-zip-default-ko.png') });
  // Turning the option off is refused with the translated sentence that says to tick it.
  await option.uncheck();
  await (await show(page, '#viewer-save-mod')).click();
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && !!ModelViewer.getState().persistence.error);
  const refusal = strings["This costume's body uses the face its ZIP includes, so that face cannot be left out. Tick 'Include face and mouth edits for this costume' to keep it; no Mod ZIP was created."];
  assert(/[가-힣]/.test(refusal) && refusal.includes(strings['Include face and mouth edits for this costume']));
  assert.equal(await statusText(page), refusal);
  report.cases.push({ name: 'real Rina board view Save mod ZIP default (ko)', held, package: path.basename(board.modPackage.packagePath), refusal });
  assert.deepStrictEqual(errors, []);
  await context.close();
}

async function realCases(browser, root) {
  const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-reedit-face-real-')); libraries.push(library);
  const server = await startServer({ cwd: root, library, pythonPath: [product, root].join(path.delimiter) });
  try {
    if (process.env.REEDIT_REAL_RINA !== '0') await realRinaBoard(browser, server);
    for (const suit of (process.env.REEDIT_REAL_SUITS || '402032004,102062001').split(',').map(Number)) {
      const job = await (await fetch(server.url + '/api/viewer/game/import?lang=ko', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: server.url },
        body: JSON.stringify({ region: 'gl', suit: 'suit:' + suit, variant: 'primary', download: false, purpose: 'viewer', platform: 'android' }) })).json();
      assert(job.job_id, JSON.stringify(job));
      const events = await (await fetch(server.url + '/api/jobs/' + job.job_id + '/events')).text();
      const done = events.split('\n').filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6))).find(item => item.type === 'done');
      assert(done && done.status === 'done' && done.output_paths.length === 1, 'Game asset import: ' + JSON.stringify(done));
      const { page, context, errors } = await openPage(browser, server.url, true);
      await openModel(page, done.output_paths);
      const opened = await page.evaluate(() => ({ faces: ModelViewer.getState().faces, outlines: ModelViewer.getEditingMetadata().outlines }));
      assert.equal(opened.faces.status, 'added', 'The body opens with its automatic face');
      const mouth = opened.outlines.meshes.find(row => row.name === 'Mouth');
      await page.locator('#viewer-outline-card').evaluate(node => { node.open = true; });
      await (await show(page, '#viewer-outline-mesh')).selectOption(mouth.id);
      await (await show(page, '#viewer-outline-number')).fill('150'); await page.locator('#viewer-outline-number').dispatchEvent('input');
      const saved = await clickSave(page);
      assert.equal(saved.originalPaths.length, 2, 'The body and its face are both preserved');
      const prepared = [];
      const listen = request => { if (request.url().endsWith('/api/viewer/prepare')) prepared.push(JSON.parse(request.postData())); };
      page.on('request', listen);
      await (await show(page, '#viewer-reedit-original')).click();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ['restored', 'error'].includes(ModelViewer.getState().persistence.status));
      page.off('request', listen);
      assert(!(await persistence(page)).error, (await persistence(page)).error);
      assert.deepStrictEqual(prepared.map(payload => [payload.paths, payload.auto_face]), [[saved.originalPaths.slice(0, 1), true]]);
      assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), [{ id: mouth.id, factor: 1.5 }]);
      await (await show(page, '#viewer-save-mod')).click();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && (ModelViewer.getState().persistence.modPackage || ModelViewer.getState().persistence.error));
      const packaged = await persistence(page);
      assert(!packaged.error, 'Save mod ZIP after re-edit: ' + packaged.error);
      assert(packaged.modPackage && fs.existsSync(packaged.modPackage.packagePath));
      await page.screenshot({ path: path.join(evidence, 'reedit-mod-zip-' + suit + '.png') });
      report.cases.push({ name: 'real re-edit Mod ZIP', suit, prepared, package: path.basename(packaged.modPackage.packagePath), status: await statusText(page) });
      assert.deepStrictEqual(errors, []);
      await context.close();
    }
  } finally { await stopServer(server); }
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined),
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await fixtureCases(browser);
    const root = process.env.ELICHIKA_ROOT;
    if (root && fs.existsSync(path.join(root, 'assets/db/gl/masterdata.db'))) await realCases(browser, path.resolve(root));
    else report.realCases = 'skipped: set ELICHIKA_ROOT to an Elichika tree with game data';
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.stack || String(error);
    try {
      const last = browser && browser.contexts().flatMap(context => context.pages()).slice(-1)[0];
      if (last) { report.failureState = await last.evaluate(() => ModelViewer.getState().persistence); await last.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }); }
    } catch (_) { /* keep the original failure */ }
    throw error;
  } finally {
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    if (browser) await browser.close();
    for (const library of libraries) fs.rmSync(library, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ status: report.status, cases: report.cases.length, report: path.join(evidence, 'report.json') }));
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
