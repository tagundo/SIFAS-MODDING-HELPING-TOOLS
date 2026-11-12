/* Real source-bound Unity/HTTP/WebGL vertex movement and selection history. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-move-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-move-library-'));
const source = path.join(library, 'extracted/3d_model/neutral.unity');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const original = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity')); fs.writeFileSync(source, original);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
let server, browser;
const report = { status: 'RUNNING', scope: 'Actual UnityFS/HTTP/WebGL, original source, trusted mouse and touch; no prepare/export response is mocked.', profiles: [], pageErrors: [] };
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function snapshot(page) { return page.evaluate(() => ({ mesh: ModelViewer.getState().meshTools, camera: ModelViewer.getState().camera, authoring: ModelViewer.getAuthoringState() })); }
function position(state, vertex, fallback) {
  const mesh = state.mesh.edits.meshes[0]; const row = mesh && mesh.positions.find(row => row.vertex === vertex);
  return row ? row.position : fallback;
}
function near(actual, expected, why) { assert(Math.abs(actual - expected) <= 1e-5, why + ': ' + actual + ' != ' + expected); }
async function stage(page) { await page.locator('#viewer-stage').scrollIntoViewIfNeeded(); await frames(page); await page.evaluate(() => ModelViewer.renderProbe(9)); await frames(page); }
async function gizmo(page, axis) {
  await stage(page);
  const value = await page.evaluate(axis => {
    const state = ModelViewer.getState().meshTools.runtime, gizmo = state && state.gizmo;
    return gizmo && gizmo.handles.find(handle => handle.axis === axis);
  }, axis);
  assert(value, 'Visible actual ' + axis + ' handle exists');
  assert(await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id === 'viewer-canvas', value), 'Handle has an actual unobstructed canvas target');
  return value;
}
function dragDelta(handle, pixels = 28) {
  const dx = handle.end.x - handle.start.x, dy = handle.end.y - handle.start.y, length = Math.hypot(dx, dy);
  assert(length >= 12, 'Axis projects to a usable screen length'); return { x: dx / length * pixels, y: dy / length * pixels };
}
async function mouseDrag(page, handle, delta, back) {
  await page.mouse.move(handle.x, handle.y); await page.mouse.down();
  await page.mouse.move(handle.x + delta.x, handle.y + delta.y, { steps: 7 });
  if (back) await page.mouse.move(handle.x, handle.y, { steps: 7 });
  await page.mouse.up(); await frames(page);
}
async function touchDrag(page, handle, delta, cancel) {
  const client = await page.context().newCDPSession(page);
  const point = (x, y) => ({ id: 1, x, y, radiusX: 1, radiusY: 1 });
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(handle.x, handle.y)] });
  for (let i = 1; i <= 7; i++) {
    await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(handle.x + delta.x * i / 7, handle.y + delta.y * i / 7)] }); await wait(18);
  }
  await client.send('Input.dispatchTouchEvent', { type: cancel ? 'touchCancel' : 'touchEnd', touchPoints: [] });
  await client.detach(); await frames(page);
}
async function post(page, route, payload) {
  return page.evaluate(async ({ route, payload }) => {
    const response = await fetch('/api/viewer/mesh/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error(await response.text()); return response.json();
  }, { route, payload });
}
async function inspectSaved(page, output) {
  const prepared = await page.evaluate(async paths => {
    const response = await fetch('/api/viewer/prepare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths, rigged: true, auto_face: false }) });
    if (!response.ok) throw new Error(await response.text()); return response.json();
  }, output.preview_paths);
  const listing = await post(page, 'inspect', { token: prepared.editing.token });
  const mesh = listing.meshes.find(mesh => mesh.available && mesh.name === 'Body') || listing.meshes.find(mesh => mesh.available);
  return post(page, 'data', { token: prepared.editing.token, mesh: mesh.mesh });
}
async function runProfile(url, profile) {
  const result = { profile, cases: [] }; report.profiles.push(result);
  const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch, deviceScaleFactor: profile.touch ? 2 : 1 });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
  const page = await context.newPage(); page.on('pageerror', error => report.pageErrors.push(String(error)));
  page.setDefaultTimeout(30000);
  try {
    await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    await page.locator('#viewer-mesh-modify').evaluate(details => details.open = true);
    const listingResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect'));
    await page.locator('#viewer-mesh-modify-load').click();
    const listing = await (await listingResponse).json(), chosen = listing.meshes.find(mesh => mesh.available && mesh.name === 'Body') || listing.meshes.find(mesh => mesh.available);
    const dataResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data'));
    await page.locator('#viewer-mesh-modify-select').selectOption(JSON.stringify(chosen.mesh)); const data = await (await dataResponse).json();
    await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
    await page.locator('#viewer-mesh-modify-quick-pick').click(); await stage(page);
    const target = await page.evaluate(mesh => ModelViewer.projectMeshVertex(mesh, 2), data.mesh);
    await page.mouse.click(target.x, target.y); await frames(page);
    let value = await snapshot(page); assert.deepEqual(value.mesh.selectedVertices, [2]);
    assert.equal(value.mesh.runtime.mode, 'pick');
    assert.equal(await page.locator('#viewer-mesh-modify-move-axis').isVisible(), false, 'Axis controls stay closed outside Move mode');
    assert((await page.locator('#viewer-mesh-modify .mesh-transform-tools').boundingBox()).height <= 60, 'Selection mode only uses one compact movement row');
    result.cases.push('One-click Pick selects an actual model vertex; move details remain compact');
    await page.locator('#viewer-mesh-modify-quick-drag').click(); await page.locator('#viewer-mesh-modify-move-axis').selectOption('x'); await page.locator('#viewer-mesh-modify-move-step').fill('.025');
    const movementBox = await page.locator('#viewer-mesh-modify .mesh-transform-tools').boundingBox();
    assert(movementBox.height <= 112, 'Selected movement controls fit in two compact rows: ' + JSON.stringify(movementBox));
    const beforeNudge = await snapshot(page); await page.locator('#viewer-mesh-modify-nudge-plus').click();
    const nudged = await snapshot(page), nudgePosition = position(nudged, 2, data.positions[2]);
    near(nudgePosition[0], data.positions[2][0] + .025, 'X+ uses source mesh units');
    assert.equal(nudgePosition[1], data.positions[2][1]); assert.equal(nudgePosition[2], data.positions[2][2]);
    assert.equal(nudged.mesh.history, beforeNudge.mesh.history + 1); assert.deepEqual(nudged.camera, beforeNudge.camera);
    await page.locator('#viewer-mesh-modify-undo').click(); assert.deepEqual((await snapshot(page)).mesh.edits, beforeNudge.mesh.edits);
    await page.locator('#viewer-mesh-modify-redo').click(); near(position(await snapshot(page), 2, data.positions[2])[0], nudgePosition[0], 'Redo restores nudge');
    await page.locator('#viewer-mesh-modify-undo').click();
    result.cases.push('Source-local step nudge has one real Undo/Redo and preserves other axes/camera');
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('x');
    let handle = await gizmo(page, 'x'), delta = dragDelta(handle), beforeDrag = await snapshot(page);
    await mouseDrag(page, handle, delta); value = await snapshot(page);
    const moved = position(value, 2, data.positions[2]);
    assert(Math.abs(moved[0] - data.positions[2][0]) > .001, 'Trusted X handle drag moves source vertex');
    near(moved[1], data.positions[2][1], 'X handle preserves source Y'); near(moved[2], data.positions[2][2], 'X handle preserves source Z');
    assert.equal(value.mesh.history, beforeDrag.mesh.history + 1, 'Whole drag is one Undo entry'); assert.deepEqual(value.camera, beforeDrag.camera);
    result.cases.push('Actual X arrow supports source-local mouse drag without rotating the camera');
    handle = await gizmo(page, 'x'); const beforeClick = await snapshot(page); await page.mouse.click(handle.x, handle.y); await frames(page);
    value = await snapshot(page); assert.deepEqual(value.mesh.edits, beforeClick.mesh.edits); assert.equal(value.mesh.history, beforeClick.mesh.history, 'No-op handle click creates no history');
    handle = await gizmo(page, 'x'); await mouseDrag(page, handle, dragDelta(handle, 15), true);
    value = await snapshot(page); assert.deepEqual(value.mesh.edits, beforeClick.mesh.edits); assert.equal(value.mesh.history, beforeClick.mesh.history, 'Return-to-start drag restores original history');
    result.cases.push('No-op clicks and return-to-start gestures preserve exact authored state/history');
    if (profile.touch) {
      await page.locator('#viewer-mesh-modify-move-axis').selectOption('y'); handle = await gizmo(page, 'y'); delta = dragDelta(handle, 22);
      const beforeTouch = await snapshot(page); await touchDrag(page, handle, delta, true);
      value = await snapshot(page); assert.deepEqual(value.mesh.edits, beforeTouch.mesh.edits); assert.equal(value.mesh.history, beforeTouch.mesh.history); assert.deepEqual(value.camera, beforeTouch.camera);
      handle = await gizmo(page, 'y'); await touchDrag(page, handle, dragDelta(handle, 22), false); value = await snapshot(page);
      const touched = position(value, 2, data.positions[2]); assert(Math.abs(touched[1] - position(beforeTouch, 2, data.positions[2])[1]) > .001);
      near(touched[0], position(beforeTouch, 2, data.positions[2])[0], 'Y touch handle preserves source X'); near(touched[2], position(beforeTouch, 2, data.positions[2])[2], 'Y touch handle preserves source Z');
      assert.equal(value.mesh.history, beforeTouch.mesh.history + 1); assert.deepEqual(value.camera, beforeTouch.camera);
      result.cases.push('Trusted touch axis drag and cancellation preserve per-gesture Undo and camera');
    }
    const beforeClear = await snapshot(page); await stage(page);
    assert(await page.locator('#viewer-interaction-clear').isEnabled()); await page.locator('#viewer-interaction-clear').click(); value = await snapshot(page);
    assert.deepEqual(value.mesh.selectedVertices, []); assert.deepEqual(value.mesh.edits, beforeClear.mesh.edits); assert.deepEqual(value.authoring, beforeClear.authoring); assert.deepEqual(value.camera, beforeClear.camera); assert.equal(value.mesh.runtime.mode, beforeClear.mesh.runtime.mode);
    assert.equal(value.mesh.history, beforeClear.mesh.history + 1);
    await page.locator('#viewer-mesh-modify-undo').click(); value = await snapshot(page); assert.deepEqual(value.mesh.selectedVertices, [2]); assert.deepEqual(value.mesh.edits, beforeClear.mesh.edits);
    result.cases.push('Main clear-selection preserves committed position edits, edit mode and camera; Undo restores selection');
    const expected = position(value, 2, data.positions[2]).slice(), response = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/export'));
    await page.locator('#viewer-mesh-modify-save').click(); const actualResponse = await response; assert.equal(actualResponse.status(), 200, await actualResponse.text()); const saved = await actualResponse.json();
    const reopened = await inspectSaved(page, saved); reopened.positions[2].forEach((part, axis) => near(part, expected[axis], 'Serialized/reopened source position'));
    assert.deepEqual(reopened.skin, data.skin, 'Position changes preserve original skin weights'); assert.deepEqual(reopened.triangles, data.triangles, 'Position changes preserve topology');
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'Source remains byte-identical');
    result.cases.push('Real exported/reopened Unity copy preserves moved source coordinates, weights, topology and immutable input');
    await stage(page); await page.screenshot({ path: path.join(evidence, profile.name + '.png') }); result.status = 'PASS';
  } finally { await context.close(); }
}
(async () => {
  try {
    const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    const log = fs.createWriteStream(path.join(evidence, 'server.log'));
    server = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: root, env: { ...process.env, SUKUSTA_DIR: library, PYTHONPATH: root + ':' + path.dirname(root) }, stdio: ['ignore', 'pipe', 'pipe'] }); server.stdout.pipe(log); server.stderr.pipe(log);
    const url = 'http://127.0.0.1:' + port; for (let i = 0; i < 120; i++) { try { if ((await fetch(url + '/api/tools')).ok) break; } catch (_) {} await wait(100); }
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await runProfile(url, { name: 'desktop', width: 1440, height: 1000, touch: false });
    await runProfile(url, { name: 'phone-touch', width: 450, height: 1000, touch: true });
    assert.deepEqual(report.pageErrors, []); report.status = 'PASS'; console.log(JSON.stringify({ status: report.status, profiles: report.profiles.length, cases: report.profiles.reduce((sum, profile) => sum + profile.cases.length, 0), evidence }));
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); console.error(error); }
  finally { if (browser) await browser.close(); if (server) server.kill(); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); if (report.status !== 'PASS') process.exitCode = 1; }
})();
