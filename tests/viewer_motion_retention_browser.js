/* Real Unity/HTTP/WebGL library retention and transactional failure/cancel. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-motion-retention-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-motion-retention-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const fixtures = JSON.parse(execFileSync(python, ['-c', `import json,sys;from pathlib import Path;sys.path.insert(0,'tests');from test_viewer_motion_library import make_motion_library_fixture;print(json.dumps(make_motion_library_fixture(Path(sys.argv[1]))))`, models], { cwd: product, encoding: 'utf8' }));
const hashes = Object.fromEntries(Object.values(fixtures).map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, stream }; } catch (_) {} await wait(100); }
  child.kill(); throw new Error('Product server did not become ready');
}
async function show(locator) { await locator.evaluate(e => { for (let parent = e.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
async function state(page) { return page.evaluate(() => ModelViewer.getState()); }
async function input(page, id, value, type = 'input') { await (await show(page.locator('#' + id))).evaluate((e, data) => { e.value = data.value; e.dispatchEvent(new Event(data.type, { bubbles: true })); }, { value: String(value), type }); }
async function open(page, source) { await page.evaluate(source => ModelViewer.open([source]), source); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); }
async function snapshot(page) { return page.evaluate(() => { const state = ModelViewer.getState(); return { state, authoring: ModelViewer.getAuthoringState(), editing: ModelViewer.getEditingMetadata(), inspectedNodeControl: document.getElementById('viewer-node').value }; }); }
async function add(page, source, replaceGame = false) { await page.evaluate(({ source, replaceGame }) => ModelViewer.addMotion([source], { replaceGame }), { source, replaceGame }); await page.waitForFunction(() => !ModelViewer.getState().loading); }
async function select(page, clip) { await input(page, 'viewer-motion', clip, 'change'); await input(page, 'viewer-time', '.75'); const s = await state(page), target = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'LeftUpLeg').node); assert.equal(s.rig.selectedClip, clip); assert(Math.abs(s.rig.time - .75) < 1e-7); const bone = s.rig.bones.find(b => String(b.node) === String(target)); assert(bone, 'the current editable LeftUpLeg maps to a real runtime bone'); return bone; }
function differs(a, b) { return a.some((value, index) => Math.abs(value - b[index]) > .01); }
function nearVector(a, b, why) { assert.equal(a.length, b.length); a.forEach((value, index) => assert(Math.abs(value - b[index]) < 1e-8, why + ': ' + a + ' != ' + b)); }
function assertLibrary(s, bodies, motions) { assert.deepStrictEqual(s.loadedPaths, bodies); assert.deepStrictEqual(s.paths, bodies); assert.deepStrictEqual(s.loadedMotionPaths, motions); assert.deepStrictEqual(s.motionLibraryPaths, motions); }
async function heldAddition(page, source, action) {
  let release, received; const held = new Promise(resolve => { received = resolve; }), gate = new Promise(resolve => { release = resolve; });
  const handler = async route => { const data = route.request().postDataJSON(); if ((data.motion_paths || []).includes(source)) { received(); await gate; } await route.continue().catch(() => {}); };
  await page.route('**/api/viewer/prepare', handler);
  try {
    await page.evaluate(source => { window.__motionRetentionPending = null; ModelViewer.addMotion([source]).then(() => { window.__motionRetentionPending = { ok: true }; }, error => { window.__motionRetentionPending = { ok: false, name: error.name, message: error.message }; }); }, source);
    await held; await action(); await page.waitForFunction(() => window.__motionRetentionPending !== null);
    const result = await page.evaluate(() => window.__motionRetentionPending); assert.equal(result.ok, false); assert.equal(result.name, 'AbortError'); return result;
  } finally { release(); await page.unroute('**/api/viewer/prepare', handler); }
}
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = [], prepareRequests = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    page.on('request', request => { if (request.url().endsWith('/api/viewer/prepare')) prepareRequests.push(request.postDataJSON()); });
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function'); await page.evaluate(() => { document.getElementById('viewer-auto-face').checked = false; });
    await page.evaluate(source => openModelViewer([source]), fixtures.body_a); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    await add(page, fixtures.motion_a, true); await select(page, 'Library A');
    const breast = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'BreastSize').node);
    await page.evaluate(node => ModelViewer.restoreAuthoringState({ version: 1, savedSettingsEnabled: true, edits: [{ node, method: 'node', scale: [1.12, 1.08, 1.04] }] }), breast);
    await input(page, 'viewer-node-filter', 'all', 'change'); await input(page, 'viewer-node', breast, 'change'); await input(page, 'viewer-fov', 52);
    await input(page, 'viewer-physics-frame-rate', 60, 'change');
    const drag = page.locator('[data-physics-field=dragForce]').first(); await (await show(drag)).evaluate(e => { e.value = '.4'; e.dispatchEvent(new Event('input', { bubbles: true })); });
    await (await show(page.locator('#viewer-physics-colliders'))).uncheck();
    const rawValue = await page.locator('#viewer-expression option').evaluateAll(options => options.find(o => o.value)?.value);
    assert(rawValue, 'the fixture has a real morph inspection channel'); await input(page, 'viewer-expression', rawValue, 'change'); await input(page, 'viewer-expression-number', 37);
    const before = await snapshot(page); assert(before.authoring.edits.length); assert(before.authoring.physics.some(e => e.values.dragForce === .4)); assert.equal(before.state.rig.selectedNode, String(breast)); assert(Object.keys(before.state.rig.expressionPanel.overrides).length);
    await add(page, fixtures.motion_b, true); const after = await snapshot(page);
    report.inspection = { before: before.inspectedNodeControl, after: after.inspectedNodeControl, beforeState: before.state.rig.selectedNode, afterState: after.state.rig.selectedNode };
    assertLibrary(after.state, [fixtures.body_a], [fixtures.motion_a, fixtures.motion_b]);
    assert.deepStrictEqual(after.authoring, before.authoring, 'adding a game selection retains exact authored body and physics values');
    nearVector(after.state.camera.position, before.state.camera.position, 'camera position retained'); nearVector(after.state.camera.target, before.state.camera.target, 'camera target retained'); assert.equal(after.state.camera.fov, before.state.camera.fov);
    assert.equal(after.state.rig.selectedClip, 'Library A'); assert(Math.abs(after.state.rig.time - .75) < 1e-7); assert.equal(after.state.rig.selectedNode, before.state.rig.selectedNode, 'inspected bone remains selected');
    assert.equal(after.inspectedNodeControl, before.inspectedNodeControl, 'the actual inspector control retains the selected bone as well');
    assert.deepStrictEqual(after.state.rig.expressionPanel.overrides, before.state.rig.expressionPanel.overrides, 'manual expression remains while adding another motion'); assert.equal(after.state.rig.expressionPanel.selectedRaw, before.state.rig.expressionPanel.selectedRaw);
    for (const key of ['swingBone', 'swingCollider', 'mode', 'frameRate', 'profile', 'qualityMode', 'skirtCorrection', 'motionCorrection']) assert.equal(after.state.rig.physics[key], before.state.rig.physics[key], 'physics option retained: ' + key);
    assert.equal(after.editing.sourceFingerprint, before.editing.sourceFingerprint, 'adding clips never changes editable model identity');
    const a = await select(page, 'Library A'); const aPixels = await page.locator('#viewer-stage canvas').screenshot({ path: path.join(evidence, 'body-a-library-a.png') });
    const b = await select(page, 'Library B'); const bPixels = await page.locator('#viewer-stage canvas').screenshot({ path: path.join(evidence, 'body-a-library-b.png') });
    assert(differs(a.quaternion, b.quaternion), 'both retained clips drive the real bound skeleton'); assert.notEqual(crypto.createHash('sha256').update(aPixels).digest('hex'), crypto.createHash('sha256').update(bPixels).digest('hex'), 'both clips visibly change the actual WebGL canvas');
    report.cases.push({ name: 'accumulated game imports retain authored state, inspection, camera, physics and real visible poses', before: { selectedNode: before.state.rig.selectedNode, time: before.state.rig.time }, after: { selectedNode: after.state.rig.selectedNode, time: after.state.rig.time }, a, b });
    await open(page, fixtures.body_b); let s = await state(page); assertLibrary(s, [fixtures.body_b], [fixtures.motion_a, fixtures.motion_b]); assert.equal(s.stats.meshes, 1);
    const newA = await select(page, 'Library A'), newB = await select(page, 'Library B'); assert.notEqual(newA.node, a.node, 'new source has a different runtime bone index'); assert(differs(newA.quaternion, newB.quaternion), 'retained clips rebind to the new body rather than stale bone objects');
    await open(page, fixtures.body_a); s = await state(page); assertLibrary(s, [fixtures.body_a], [fixtures.motion_a, fixtures.motion_b]); await select(page, 'Library A');
    const reloadRequest = prepareRequests[prepareRequests.length - 1]; assert.deepStrictEqual(reloadRequest.paths, [fixtures.body_a]); assert.deepStrictEqual(reloadRequest.motion_paths, [fixtures.motion_a, fixtures.motion_b]);
    report.cases.push({ name: 'new source with changed IDs/node order, then original source, preserves library and actually rebinds', originalNode: a.node, newNode: newA.node, newA, newB });
    await (await show(page.locator('#viewer-clear-motion-library'))).click(); await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().motionLibraryPaths.length === 0);
    s = await state(page); assertLibrary(s, [fixtures.body_a], []); assert.equal(s.error, '', 'intentional clear completes inspection restore without a hidden error'); assert(!s.rig.clipNames.includes('Library A') && !s.rig.clipNames.includes('Library B')); assert(s.rig.clipNames.includes('Body A idle'));
    await add(page, fixtures.motion_a); await select(page, 'Library A'); const rollback = await snapshot(page);
    for (const source of [path.join(models, 'missing.unity'), '/etc/hosts']) {
      const result = await page.evaluate(async source => { try { await ModelViewer.addMotion([source]); return { ok: true }; } catch (e) { return { ok: false, name: e.name, message: e.message }; } }, source);
      assert.equal(result.ok, false); const current = await snapshot(page); assertLibrary(current.state, [fixtures.body_a], [fixtures.motion_a]); assert.equal(current.state.modelId, rollback.state.modelId); assert.deepStrictEqual(current.authoring, rollback.authoring);
    }
    const badSource = path.join(models, 'broken.unity'); fs.writeFileSync(badSource, 'This is deliberately not a Unity bundle.');
    const failed = await page.evaluate(async source => { try { await ModelViewer.addMotion([source]); return false; } catch (_) { return true; } }, badSource); assert(failed); assertLibrary(await state(page), [fixtures.body_a], [fixtures.motion_a]);
    const cancelled = await heldAddition(page, fixtures.motion_b, async () => { await (await show(page.locator('#viewer-cancel'))).click(); });
    s = await state(page); assertLibrary(s, [fixtures.body_a], [fixtures.motion_a]); assert.equal(s.modelId, rollback.state.modelId, 'cancel keeps the previous displayed model');
    const raced = await heldAddition(page, fixtures.motion_b, async () => { await open(page, fixtures.body_b); });
    s = await state(page); assertLibrary(s, [fixtures.body_b], [fixtures.motion_a]); assert(!s.rig.clipNames.includes('Library B'), 'aborted provisional source cannot leak into a concurrently opened body');
    await select(page, 'Library A'); report.cases.push({ name: 'clear, missing/forbidden/malformed-bank rollback, explicit cancel and concurrent model-open abort', cancelled, raced });
    for (const payload of [
      { paths: [fixtures.body_b], motion_paths: [fixtures.motion_a], auto_face: false, rigged: false },
      { paths: [fixtures.body_b], motion_paths: Array(33).fill(fixtures.motion_a), auto_face: false, rigged: true },
      { paths: Array(9).fill(fixtures.body_b), motion_paths: [fixtures.motion_a], auto_face: false, rigged: true }
    ]) { const response = await page.request.post(server.url + '/api/viewer/prepare', { data: payload }); assert.equal(response.status(), 400); }
    const outside = await page.request.post(server.url + '/api/viewer/prepare', { data: { paths: [fixtures.body_b], motion_paths: ['/etc/hosts'], auto_face: false, rigged: true } }); assert.equal(outside.status(), 403);
    assertLibrary(await state(page), [fixtures.body_b], [fixtures.motion_a]);
    await page.locator('#viewer-stage').scrollIntoViewIfNeeded(); await page.waitForFunction(() => ModelViewer.getState().layout.stageVisible);
    const probe = await page.evaluate(() => ModelViewer.renderProbe(33)); report.finalProbe = probe;
    const final = await state(page); report.finalView = { camera: final.camera, framing: final.framing, stats: final.stats, quality: final.quality, layout: final.layout };
    await page.locator('#viewer-stage canvas').screenshot({ path: path.join(evidence, 'final-rebound-body-b.png') });
    assert(probe.ready && probe.glError === 0 && probe.chromaticSamples > 0); report.cases.push({ name: 'real HTTP independent8/32 bounds and forbidden paths; actual final WebGL', probe });
    assert.deepStrictEqual(errors, []); for (const [file, hash] of Object.entries(hashes)) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), hash, 'source immutable: ' + file);
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); }
}
main().catch(() => { process.exitCode = 1; });
