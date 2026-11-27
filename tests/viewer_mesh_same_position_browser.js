/* Real Unity/HTTP/WebGL: "Move vertices at the same position together" on a
 * ribbon whose upper quad is a second material joined by seam copies (vertex 6
 * = vertex 2 exactly with other weights, vertex 7 = vertex 3 one float32 step
 * away, both in the second material; vertex 8 = vertex 1 exactly, a UV seam
 * inside the first material). Checkbox, partner count and UV dots and rings,
 * nudge, axis and free drag, delta and absolute position, Undo/Redo, OFF =
 * selected vertices only, regrouping by current position (tear, Undo, join,
 * recipe), weights and Select connected unchanged, save + reopen + open copy +
 * recipe restore, and phone/touch and narrow layouts. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-same-position-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-same-position-library-'));
const source = path.join(library, 'extracted/3d_model/seam-ribbon.unity');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
execFileSync(python, ['-B', path.join(__dirname, 'generate_viewer_seam_fixture.py'), source], { cwd: root, env: { ...process.env, PYTHONPATH: root + path.delimiter + path.dirname(root) } });
const original = fs.readFileSync(source);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const f32 = new Float32Array(1), i32 = new Int32Array(f32.buffer);
const ordered = x => { f32[0] = x; const bits = i32[0]; return bits < 0 ? -(bits & 0x7fffffff) : bits; };
const ulps = (a, b) => Math.max(...a.map((x, axis) => Math.abs(ordered(x) - ordered(b[axis]))));
const stored = p => p.map(x => Math.fround(x));
const gap = (a, b) => Math.max(...a.map((x, axis) => Math.abs(x - b[axis])));
const TOLERANCE = 5e-7;
let server, browser;
const report = { status: 'RUNNING', scope: 'Actual UnityFS/HTTP/WebGL, generated seam fixture, trusted mouse and touch; no prepare/export response is mocked.', profiles: [], pageErrors: [] };
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function snapshot(page) { return page.evaluate(() => ({ mesh: ModelViewer.getState().meshTools, camera: ModelViewer.getState().camera })); }
function edits(state) { const mesh = state.mesh.edits.meshes[0]; return mesh ? mesh.positions.slice().sort((a, b) => a.vertex - b.vertex) : []; }
function position(state, vertex, data) { const row = edits(state).find(row => row.vertex === vertex); return row ? row.position : data.positions[vertex]; }
function near(actual, expected, why, tolerance = 1e-9) { assert(Math.abs(actual - expected) <= tolerance, why + ': ' + actual + ' != ' + expected); }
async function stage(page) { await page.locator('#viewer-stage').scrollIntoViewIfNeeded(); await frames(page); await page.evaluate(() => ModelViewer.renderProbe(9)); await frames(page); }
async function project(page, mesh, vertex) { await stage(page); return page.evaluate(({ mesh, vertex }) => ModelViewer.projectMeshVertex(mesh, vertex), { mesh, vertex }); }
async function gizmo(page, axis) {
  await stage(page);
  const value = await page.evaluate(axis => { const state = ModelViewer.getState().meshTools.runtime; return state && state.gizmo.handles.find(handle => handle.axis === axis); }, axis);
  assert(value, 'Visible ' + axis + ' handle'); return value;
}
function along(handle, pixels) { const dx = handle.end.x - handle.start.x, dy = handle.end.y - handle.start.y, length = Math.hypot(dx, dy); return { x: dx / length * pixels, y: dy / length * pixels }; }
async function mouseDrag(page, from, delta, back) {
  await page.mouse.move(from.x, from.y); await page.mouse.down(); await page.mouse.move(from.x + delta.x, from.y + delta.y, { steps: 7 });
  if (back) await page.mouse.move(from.x, from.y, { steps: 7 });
  await page.mouse.up(); await frames(page);
}
async function touchDrag(page, from, delta) {
  const client = await page.context().newCDPSession(page), point = (x, y) => ({ id: 1, x, y, radiusX: 1, radiusY: 1 });
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(from.x, from.y)] });
  for (let i = 1; i <= 7; i++) { await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(from.x + delta.x * i / 7, from.y + delta.y * i / 7)] }); await wait(18); }
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await client.detach(); await frames(page);
}
async function post(page, route, payload) {
  return page.evaluate(async ({ route, payload }) => {
    const response = await fetch('/api/viewer/mesh/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error(await response.text()); return response.json();
  }, { route, payload });
}
async function reopen(page, paths) {
  const prepared = await page.evaluate(async paths => {
    const response = await fetch('/api/viewer/prepare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths, rigged: true, auto_face: false }) });
    if (!response.ok) throw new Error(await response.text()); return response.json();
  }, paths);
  const listing = await post(page, 'inspect', { token: prepared.editing.token });
  return post(page, 'data', { token: prepared.editing.token, mesh: listing.meshes.find(mesh => mesh.available).mesh });
}
async function open(page, file) {
  await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, file);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
  await page.locator('#viewer-mesh-modify').evaluate(details => details.open = true);
  const listingResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect'));
  await page.locator('#viewer-mesh-modify-load').click();
  const listing = await (await listingResponse).json(), chosen = listing.meshes.find(mesh => mesh.available);
  const dataResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data'));
  await page.locator('#viewer-mesh-modify-select').selectOption(JSON.stringify(chosen.mesh)); const data = await (await dataResponse).json();
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
  return data;
}
async function pick(page, data, vertex, shift) {
  if ((await page.locator('#viewer-mesh-modify-quick-pick').getAttribute('aria-pressed')) !== 'true') await page.locator('#viewer-mesh-modify-quick-pick').click();
  const target = await project(page, data.mesh, vertex);
  if (shift) await page.keyboard.down('Shift'); await page.mouse.click(target.x, target.y); if (shift) await page.keyboard.up('Shift'); await frames(page);
}
async function inspector(page, open) {
  const expanded = (await page.locator('#viewer-mesh-modify [data-uv-settings]').getAttribute('aria-expanded')) === 'true';
  if (expanded !== open) await page.locator('#viewer-mesh-modify [data-uv-settings]').click();
}
// UV canvas pixel at a texture coordinate (zoom 1, no pan).
async function uvPixel(page, uv) {
  return page.evaluate(uv => { const canvas = document.getElementById('viewer-mesh-modify-canvas'), size = canvas.width, ctx = canvas.getContext('2d');
    return Array.from(ctx.getImageData(Math.round(uv[0] * size), Math.round((1 - uv[1]) * size), 1, 1).data); }, uv);
}
const pink = pixel => pixel[0] > 200 && pixel[1] < 150 && pixel[2] > 170;
// Pixels on a horizontal line from a texture coordinate, offsets in CSS pixels.
async function uvRow(page, uv, offsets) {
  return page.evaluate(({ uv, offsets }) => { const canvas = document.getElementById('viewer-mesh-modify-canvas'), size = canvas.width, ctx = canvas.getContext('2d'), density = size / canvas.getBoundingClientRect().width;
    return offsets.map(dx => Array.from(ctx.getImageData(Math.round(uv[0] * size + dx * density), Math.round((1 - uv[1]) * size), 1, 1).data)); }, { uv, offsets });
}
async function selectIndex(page, vertex) {
  await inspector(page, true); await page.locator('#viewer-mesh-modify-vertex').fill(String(vertex)); await page.locator('#viewer-mesh-modify-select-vertex').click(); await inspector(page, false); await frames(page);
}
async function desktop(url) {
  const result = { profile: 'desktop', cases: [] }; report.profiles.push(result);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => {
    localStorage.setItem('sifas_lang', 'en'); let api;
    Object.defineProperty(window, 'ViewerMeshTools', { configurable: true, get: () => api, set: value => { api = value; const create = api.create; api.create = function (options) { const tool = create(options); window.__meshTool = tool; return tool; }; } });
  });
  const page = await context.newPage(); page.on('pageerror', error => report.pageErrors.push(String(error))); page.setDefaultTimeout(30000);
  try {
    await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    const data = await open(page, source);
    assert.equal(data.positions.length, 9); assert.deepEqual(data.positions[6], data.positions[2]); assert.deepEqual(data.positions[8], data.positions[1]); assert.equal(ulps(data.positions[7], data.positions[3]), 1);
    assert.notDeepEqual(data.skin[6], data.skin[2], 'the exact seam copy has other weights'); assert.equal(data.submeshes.length, 2);
    const quick = page.locator('#viewer-mesh-modify-same-position'), settings = page.locator('#viewer-mesh-modify-same-position-settings');
    // Selection and the partner indicator (UV dots for partners in the shown material).
    // Vertices 1 and 8 project to one screen point: a click picks either one.
    await pick(page, data, 1); let value = await snapshot(page);
    assert.equal(value.mesh.selectedVertices.length, 1); assert([1, 8].includes(value.mesh.selectedVertices[0]));
    assert.deepEqual(value.mesh.samePosition.partners, [9 - value.mesh.selectedVertices[0]]); assert.equal(value.mesh.samePosition.enabled, true);
    // Vertex 1 by index: its partner 8 has a UV inside the texture (1 sits on the corner).
    await inspector(page, true); await page.locator('#viewer-mesh-modify-vertex').fill('1'); await page.locator('#viewer-mesh-modify-select-vertex').click(); await inspector(page, false);
    value = await snapshot(page); assert.deepEqual(value.mesh.selectedVertices, [1]); assert.deepEqual(value.mesh.samePosition.partners, [8]);
    assert(pink(await uvPixel(page, data.uv[8])), 'the UV canvas marks the partner'); assert(!pink(await uvPixel(page, data.uv[3])), 'non-partners are unmarked');
    // A pink ring above the selected dots (radius 5.6 px), so a partner under a
    // yellow dot (same UV) still shows; the filled dot ends at 4 px.
    assert((await uvRow(page, data.uv[8], [-6, -5.5, -5])).some(pink), 'the partner ring is drawn outside the dot');
    assert(!(await uvRow(page, data.uv[3], [-6, -5.5, -5])).some(pink), 'no ring around a non-partner');
    // The partner lookup is reused while the selection and positions stay.
    let lookups = (await snapshot(page)).mesh.samePosition.lookups;
    await page.evaluate(() => { window.__meshTool.updateLanguage(); window.__meshTool.updateLanguage(); window.__meshTool.refresh(); });
    assert.equal((await snapshot(page)).mesh.samePosition.lookups, lookups, 'redraws without a selection change reuse the partners');
    await pick(page, data, 2); value = await snapshot(page);
    assert.deepEqual(value.mesh.selectedVertices, [2]); assert.deepEqual(value.mesh.samePosition.partners, [6], 'partners in any submesh');
    assert(value.mesh.samePosition.lookups > lookups, 'a new selection looks the partners up again');
    assert(!pink(await uvPixel(page, data.uv[6])), 'a partner in a hidden material gets no dot');
    assert(!(await uvRow(page, data.uv[6], [-6, -5.5, -5, 5, 5.5, 6])).some(pink), 'and no ring');
    assert.match(await page.locator('#viewer-mesh-modify-count').textContent(), /^Selected vertices: 1 \(\+1 at the same position\) · /);
    assert(!pink(await uvPixel(page, data.uv[8])), 'the dot follows the selection');
    assert.equal(await quick.isVisible(), false, 'Pick mode keeps the move tools to one row');
    await page.locator('#viewer-mesh-modify-quick-drag').click();
    assert(await quick.isVisible()); assert(await quick.isChecked(), 'default ON'); assert(await settings.isChecked(), 'the settings copy agrees');
    assert.equal((await page.locator('#viewer-mesh-modify .mesh-transform-together label').textContent()).trim(), 'Move vertices at the same position together');
    result.moveToolsHeight = (await page.locator('#viewer-mesh-modify .mesh-transform-tools').boundingBox()).height;
    result.cases.push('Pick shows partners (count + pink UV dot and ring, none in a hidden material, lookup reused across redraws); Move shows the checkbox, default ON, selection unchanged');
    // Nudge with partners, one Undo step.
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('x'); await page.locator('#viewer-mesh-modify-move-step').fill('.025');
    const start = await snapshot(page); await page.locator('#viewer-mesh-modify-nudge-plus').click(); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2, 6]); assert.deepEqual(position(value, 6, data), position(value, 2, data));
    near(position(value, 2, data)[0], data.positions[2][0] + .025, 'X+ step'); assert.equal(position(value, 2, data)[1], data.positions[2][1]);
    assert.equal(value.mesh.history, start.mesh.history + 1, 'one history step including the partner');
    await page.locator('#viewer-mesh-modify-undo').click(); assert.deepEqual((await snapshot(page)).mesh.edits, start.mesh.edits);
    await page.locator('#viewer-mesh-modify-redo').click(); assert.deepEqual((await snapshot(page)).mesh.edits, value.mesh.edits);
    await page.locator('#viewer-mesh-modify-undo').click();
    result.cases.push('Nudge moves the partner by the same step; Undo/Redo restore both in one step');
    // OFF: exactly the selected vertex, as before.
    const buildsBeforeOff = (await snapshot(page)).mesh.samePosition.builds;
    await quick.uncheck(); value = await snapshot(page);
    assert.equal(value.mesh.samePosition.enabled, false); assert(!(await settings.isChecked())); assert.equal(value.mesh.history, start.mesh.history, 'the option is not an edit');
    assert.match(await page.locator('#viewer-mesh-modify-count').textContent(), /^Selected vertices: 1 · /);
    await page.locator('#viewer-mesh-modify-nudge-plus').click(); value = await snapshot(page);
    assert.deepEqual(edits(value), [{ vertex: 2, position: [data.positions[2][0] + .025, data.positions[2][1], data.positions[2][2]] }], 'OFF writes the selected vertex only');
    await page.locator('#viewer-mesh-modify-undo').click();
    let handle = await gizmo(page, 'x'); await mouseDrag(page, handle, along(handle, 28)); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2], 'OFF axis drag tears the seam open as before'); await page.locator('#viewer-mesh-modify-undo').click();
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('screen');
    let point = await project(page, data.mesh, 2); await mouseDrag(page, point, { x: 25, y: -15 }); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2], 'OFF free drag moves the selected vertex only'); await page.locator('#viewer-mesh-modify-undo').click();
    assert.equal((await snapshot(page)).mesh.samePosition.builds, buildsBeforeOff, 'OFF never builds position groups');
    await settings.evaluate(box => box.click()); assert(await settings.isChecked()); assert(await quick.isChecked(), 'either checkbox sets the option');
    result.cases.push('OFF: nudge, axis drag and free drag write only the selected vertex; no groups built; settings copy turns it back on');
    // Groups follow the current positions. Tear 2 from 6 with the option off
    // and keep the edit: with the option on again, 2 has no partner and moves alone.
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('x');
    const untorn = await snapshot(page); await quick.uncheck(); await page.locator('#viewer-mesh-modify-nudge-plus').click(); await quick.check(); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2]); assert.deepEqual(value.mesh.samePosition.partners, [], 'a vertex torn away with the option off has no partners');
    assert.match(await page.locator('#viewer-mesh-modify-count').textContent(), /^Selected vertices: 1 · /);
    await page.locator('#viewer-mesh-modify-nudge-plus').click(); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2], 'the next nudge with the option on writes the torn vertex only');
    near(position(value, 2, data)[0], data.positions[2][0] + .05, 'two X+ steps');
    await page.locator('#viewer-mesh-modify-undo').click(); assert.deepEqual((await snapshot(page)).mesh.samePosition.partners, [], 'still torn after one Undo');
    await page.locator('#viewer-mesh-modify-undo').click(); value = await snapshot(page);
    assert.deepEqual(value.mesh.edits, untorn.mesh.edits); assert.deepEqual(value.mesh.samePosition.partners, [6], 'Undo of the tear joins the copies again');
    // Join: put vertex 0 (no copy) exactly on vertex 4 with Set vertex position.
    await selectIndex(page, 0); assert.deepEqual((await snapshot(page)).mesh.samePosition.partners, []);
    await inspector(page, true); for (const [i, axis] of ['X', 'Y', 'Z'].entries()) await page.locator('#viewer-mesh-modify [data-mesh-position-axis=' + axis + ']').fill(String(data.positions[4][i]));
    await page.locator('#viewer-mesh-modify-position-set').click(); await inspector(page, false); value = await snapshot(page);
    assert.deepEqual(edits(value), [{ vertex: 0, position: data.positions[4] }], 'Set writes vertex 0 only (it had no partner)');
    assert.deepEqual(value.mesh.samePosition.partners, [4], 'a vertex placed on another becomes its partner');
    await page.locator('#viewer-mesh-modify-undo').click(); await page.locator('#viewer-mesh-modify-undo').click();
    // A recipe that moves 2 alone: after the restore 2 has no partner.
    const torn = data.positions[2].slice(); torn[1] += 0.05;
    await page.evaluate(state => window.__meshTool.restoreEdits(state), { version: 1, meshes: [{ mesh: data.mesh, positions: [{ vertex: 2, position: torn }] }] });
    await selectIndex(page, 2); value = await snapshot(page);
    assert.deepEqual(edits(value), [{ vertex: 2, position: torn }]); assert.deepEqual(value.mesh.samePosition.partners, [], 'a recipe that tore the seam leaves no partner');
    await page.locator('#viewer-mesh-modify-undo').click(); await page.locator('#viewer-mesh-modify-undo').click();
    value = await snapshot(page); assert.deepEqual(value.mesh.edits, untorn.mesh.edits);
    await selectIndex(page, 2); assert.deepEqual((await snapshot(page)).mesh.samePosition.partners, [6]);
    result.cases.push('Regrouping by current position: torn with the option off stays apart (and Undo joins), Set onto another vertex joins, a tearing recipe leaves no partner');
    // Axis drag with partners; a return-to-start drag leaves no edit.
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('x');
    let before = await snapshot(page); handle = await gizmo(page, 'x'); await mouseDrag(page, handle, along(handle, 28)); value = await snapshot(page);
    assert.deepEqual(edits(value).map(row => row.vertex), [2, 6]); assert.deepEqual(position(value, 6, data), position(value, 2, data), 'axis drag keeps the group bit-identical');
    assert(Math.abs(position(value, 2, data)[0] - data.positions[2][0]) > .001); assert.equal(value.mesh.history, before.mesh.history + 1);
    await page.locator('#viewer-mesh-modify-undo').click(); before = await snapshot(page);
    handle = await gizmo(page, 'x'); await mouseDrag(page, handle, along(handle, 18), true); value = await snapshot(page);
    assert.deepEqual(value.mesh.edits, before.mesh.edits, 'return-to-start drag prunes the partner too'); assert.equal(value.mesh.history, before.mesh.history);
    result.cases.push('Axis drag moves the partner with one Undo step; a return-to-start drag leaves no edit');
    // Free camera-plane drag: the copies have different weights but keep one delta.
    await page.locator('#viewer-mesh-modify-move-axis').selectOption('screen');
    const buildsBeforeDrag = (await snapshot(page)).mesh.samePosition.builds;
    point = await project(page, data.mesh, 2); before = await snapshot(page);
    await page.mouse.move(point.x, point.y); await page.mouse.down();
    for (let i = 1; i <= 12; i++) await page.mouse.move(point.x + 2 * i, point.y - i);
    const during = await snapshot(page); await page.mouse.up(); await frames(page); value = await snapshot(page);
    assert.equal(during.mesh.samePosition.builds, buildsBeforeDrag, 'no group build while the pointer moves');
    assert.deepEqual(during.mesh.samePosition.partners, [6], 'the drag keeps its groups');
    assert(value.mesh.samePosition.builds <= buildsBeforeDrag + 1, 'one rebuild after the drag for the new positions');
    assert.deepEqual(edits(value).map(row => row.vertex), [2, 6]); assert.deepEqual(position(value, 6, data), position(value, 2, data), 'free drag keeps the group bit-identical');
    assert(Math.hypot(...position(value, 2, data).map((x, axis) => x - data.positions[2][axis])) > .001); assert.equal(value.mesh.history, before.mesh.history + 1);
    const freeDrag = edits(value);
    await page.locator('#viewer-mesh-modify-undo').click(); assert.deepEqual((await snapshot(page)).mesh.edits, before.mesh.edits);
    await page.locator('#viewer-mesh-modify-redo').click(); assert.deepEqual(edits(await snapshot(page)), freeDrag);
    result.cases.push('Free drag gives the seam copy (other weights) the seed delta: saved values identical, one Undo step, groups built once');
    // The 1-step group: vertex 3 and its copy 7 move together and keep their offset.
    await pick(page, data, 3); value = await snapshot(page); assert.deepEqual(value.mesh.samePosition.partners, [7], 'a one-step seam copy is a partner');
    await page.locator('#viewer-mesh-modify-quick-drag').click(); await page.locator('#viewer-mesh-modify-move-axis').selectOption('y');
    await page.locator('#viewer-mesh-modify-nudge-plus').click(); value = await snapshot(page);
    near(position(value, 3, data)[1], data.positions[3][1] + .025, 'Y+ moves 3'); near(position(value, 7, data)[1], data.positions[7][1] + .025, 'Y+ moves 7');
    assert.equal(position(value, 7, data)[0], data.positions[7][0], 'the copy keeps its own X');
    // Translate by delta from the settings panel.
    await inspector(page, true);
    for (const [axis, number] of [['X', '.01'], ['Y', '-.02'], ['Z', '.03']]) await page.locator('#viewer-mesh-modify [data-mesh-delta-axis=' + axis + ']').fill(number);
    before = value; await page.locator('#viewer-mesh-modify-translate').click(); value = await snapshot(page);
    [3, 7].forEach(vertex => position(value, vertex, data).forEach((x, axis) => near(x, position(before, vertex, data)[axis] + [.01, -.02, .03][axis], 'translate ' + vertex)));
    assert(gap(position(value, 7, data), position(value, 3, data)) <= TOLERANCE, 'still one point');
    assert.deepEqual(value.mesh.samePosition.partners, [7], 'and still one group');
    assert.equal(value.mesh.history, before.mesh.history + 1);
    result.cases.push('A one-step seam copy is a partner for nudge and Translate (keeps its own offset)');
    // Absolute position: one selected vertex; its partner takes the same value.
    await inspector(page, false); await pick(page, data, 2); await inspector(page, true);
    for (const [axis, number] of [['X', '-.375'], ['Y', '.7'], ['Z', '.05']]) await page.locator('#viewer-mesh-modify [data-mesh-position-axis=' + axis + ']').fill(number);
    await page.locator('#viewer-mesh-modify-position-set').click(); value = await snapshot(page);
    assert.deepEqual(position(value, 2, data), [-.375, .7, .05]); assert.deepEqual(position(value, 6, data), [-.375, .7, .05], 'Set vertex position moves the partner to the same value');
    await inspector(page, false); await pick(page, data, 3, true); value = await snapshot(page);
    assert.deepEqual(value.mesh.selectedVertices.slice().sort(), [2, 3]); assert.deepEqual(value.mesh.samePosition.partners, [6, 7]);
    assert.match(await page.locator('#viewer-mesh-modify-count').textContent(), /^Selected vertices: 2 \(\+2 at the same position\) · /);
    await inspector(page, true); before = value; await page.locator('#viewer-mesh-modify-position-set').evaluate(button => { button.disabled = false; button.click(); });
    value = await snapshot(page); assert.deepEqual(value.mesh.edits, before.mesh.edits, 'two selected vertices: no absolute edit');
    assert.equal(await page.locator('#viewer-mesh-modify-status').textContent(), 'Choose one vertex for an absolute position.');
    result.cases.push('Set vertex position: the partner takes the same value; the one-vertex rule counts selected vertices only');
    // Weights and Select connected act on the selected vertices only.
    await inspector(page, false); await pick(page, data, 2); await inspector(page, true);
    await page.locator('#viewer-mesh-modify-weight-bone').selectOption('2'); await page.locator('#viewer-mesh-modify-weight-value').fill('.3');
    before = await snapshot(page); await page.locator('#viewer-mesh-modify-weight-apply').click(); value = await snapshot(page);
    assert.deepEqual(value.mesh.edits.meshes[0].weights.map(row => row.vertex), [2], 'weights change on the selected vertex only');
    await page.locator('#viewer-mesh-modify-undo').click(); await inspector(page, false);
    await page.locator('#viewer-mesh-modify .uv-selection-menu > summary').click(); await page.locator('#viewer-mesh-modify-connected').click();
    value = await snapshot(page); assert.deepEqual(value.mesh.selectedVertices.slice().sort(), [0, 1, 2, 3, 8], 'Select connected stays in the selected material');
    assert.deepEqual(value.mesh.samePosition.partners, [6, 7]); await page.locator('#viewer-mesh-modify .uv-selection-menu > summary').click();
    result.cases.push('Weights and Select connected use the selected vertices only');
    // Save, reopen and open the copy: groups stay one point in the saved mesh.
    const expected = edits(await snapshot(page)), response = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/export'));
    await page.locator('#viewer-mesh-modify-save').click(); const saved = await (await response).json();
    assert.deepEqual(saved.recipe.state.meshes[0].positions.map(row => row.vertex).sort((a, b) => a - b), [2, 3, 6, 7], 'partners are saved as ordinary position edits');
    const reopened = await reopen(page, saved.preview_paths);
    assert.deepEqual(reopened.positions[6], reopened.positions[2], 'exported exact group: bit-identical float32');
    assert(gap(reopened.positions[7], reopened.positions[3]) <= TOLERANCE && ulps(reopened.positions[7], reopened.positions[3]) <= 2, 'exported one-step group keeps its gap');
    expected.forEach(row => assert.deepEqual(reopened.positions[row.vertex], stored(row.position), 'saved vertex ' + row.vertex));
    [0, 1, 4, 5, 8].forEach(vertex => assert.deepEqual(reopened.positions[vertex], data.positions[vertex]));
    assert.deepEqual(reopened.skin, data.skin); assert.deepEqual(reopened.triangles, data.triangles);
    const copyData = await open(page, saved.preview_paths[0]);
    assert.deepEqual(copyData.positions, reopened.positions, 'the opened copy has the saved positions');
    await pick(page, copyData, 2); assert.deepEqual((await snapshot(page)).mesh.samePosition.partners, [6], 'the copy still groups the seam');
    result.cases.push('Save + reopen + open copy: partners saved as position edits, exact group bit-identical, one-step group keeps its gap');
    // Recipe restore of that save on the original.
    await open(page, source); const restored = await page.evaluate(state => window.__meshTool.restoreEdits(state), saved.recipe.state);
    assert.deepEqual(restored.meshes[0].positions.map(row => row.vertex).sort((a, b) => a - b), [2, 3, 6, 7]);
    value = await snapshot(page); edits(value).forEach(row => assert.deepEqual(row.position, expected.find(item => item.vertex === row.vertex).position));
    await page.locator('#viewer-mesh-modify-undo').click(); assert.deepEqual((await snapshot(page)).mesh.edits.meshes, [], 'one Undo removes the restored recipe');
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'source stays byte-identical');
    result.cases.push('Recipe restore applies the partner edits with no server change; one Undo step');
    await stage(page); await page.screenshot({ path: path.join(evidence, 'desktop.png') }); result.status = 'PASS';
  } finally { await context.close(); }
}
async function touch(url, profile) {
  const result = { profile: profile.name, cases: [] }; report.profiles.push(result);
  const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: true, isMobile: !!profile.mobile, deviceScaleFactor: 2 });
  await context.addInitScript(language => localStorage.setItem('sifas_lang', language), profile.language || 'en');
  const page = await context.newPage(); page.on('pageerror', error => report.pageErrors.push(String(error))); page.setDefaultTimeout(30000);
  try {
    await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    const data = await open(page, source);
    await inspector(page, true); await page.locator('#viewer-mesh-modify-vertex').fill('2'); await page.locator('#viewer-mesh-modify-select-vertex').tap(); await inspector(page, false);
    assert.deepEqual((await snapshot(page)).mesh.selectedVertices, [2]); assert.deepEqual((await snapshot(page)).mesh.samePosition.partners, [6]);
    await page.locator('#viewer-mesh-modify-quick-drag').tap();
    const label = page.locator('#viewer-mesh-modify .mesh-transform-together label'), box = await label.boundingBox(), coarse = await page.evaluate(() => matchMedia('(pointer: coarse)').matches);
    const layout = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, viewport: window.visualViewport ? window.visualViewport.width : innerWidth }));
    result.layout = { label: box, coarse, ...layout, text: (await label.textContent()).trim() };
    assert(box && box.width > 0, 'the checkbox is shown'); assert(box.x >= -1 && box.x + box.width <= layout.viewport + 1, 'the checkbox fits the phone width');
    assert(layout.documentWidth <= layout.clientWidth + 1, 'no horizontal page scroll');
    if (coarse) assert(box.height >= 44, 'a 44 px touch target under pointer:coarse: ' + box.height);
    if (profile.language === 'ko') assert.equal(result.layout.text, '같은 위치 정점 함께 이동');
    await label.tap(); assert.equal((await snapshot(page)).mesh.samePosition.enabled, false, 'tapping the label turns it off');
    await label.tap(); assert.equal((await snapshot(page)).mesh.samePosition.enabled, true);
    if (profile.drag) {
      await page.locator('#viewer-mesh-modify-move-axis').selectOption('x'); await page.locator('#viewer-mesh-modify-move-step').fill('.02');
      await page.locator('#viewer-mesh-modify-nudge-plus').tap(); let value = await snapshot(page);
      assert.deepEqual(position(value, 6, data), position(value, 2, data)); near(position(value, 2, data)[0], data.positions[2][0] + .02, 'touch nudge');
      await page.locator('#viewer-mesh-modify-undo').tap();
      await page.locator('#viewer-mesh-modify-move-axis').selectOption('y'); const handle = await gizmo(page, 'y'); await touchDrag(page, handle, along(handle, 22)); value = await snapshot(page);
      assert.deepEqual(edits(value).map(row => row.vertex), [2, 6]); assert.deepEqual(position(value, 6, data), position(value, 2, data), 'touch axis drag keeps the group');
      result.cases.push('Touch nudge and touch axis drag move the partner');
    }
    result.cases.push('Checkbox visible, inside the viewport, toggled by tapping its label' + (coarse ? ' (44 px target)' : ''));
    await page.screenshot({ path: path.join(evidence, profile.name + '.png') }); result.status = 'PASS';
  } finally { await context.close(); }
}
(async () => {
  try {
    const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    const log = fs.createWriteStream(path.join(evidence, 'server.log'));
    server = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: root, env: { ...process.env, SUKUSTA_DIR: library, PYTHONPATH: root + ':' + path.dirname(root) }, stdio: ['ignore', 'pipe', 'pipe'] }); server.stdout.pipe(log); server.stderr.pipe(log);
    const url = 'http://127.0.0.1:' + port; for (let i = 0; i < 120; i++) { try { if ((await fetch(url + '/api/tools')).ok) break; } catch (_) {} await wait(100); }
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await desktop(url);
    await touch(url, { name: 'phone-touch', width: 450, height: 1000, drag: true });
    await touch(url, { name: 'narrow-360-ko', width: 360, height: 740, mobile: true, language: 'ko' });
    assert.deepEqual(report.pageErrors, []); report.status = 'PASS';
    console.log(JSON.stringify({ status: report.status, profiles: report.profiles.length, cases: report.profiles.reduce((sum, profile) => sum + profile.cases.length, 0), evidence }));
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); console.error(error); }
  finally {
    if (browser) await browser.close(); if (server) server.kill(); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    fs.rmSync(library, { recursive: true, force: true }); if (report.status !== 'PASS') process.exitCode = 1;
  }
})();
