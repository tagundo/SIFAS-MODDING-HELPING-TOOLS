/* Real HTTP/Unity/WebGL mesh editing: no success API or renderer is mocked. */
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-live-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-live-library-'));
const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'neutral.unity'), raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, raw);
const gameSource = process.env.VIEWER_GAME_MODEL ? path.join(models, 'game-costume.unity') : null;
if (gameSource) fs.copyFileSync(process.env.VIEWER_GAME_MODEL, gameSource);
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const near = (actual, expected, label) => assert(Math.abs(actual - expected) < 1e-5, `${label}: ${actual} != ${expected}`);
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server failed'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, stream }; } catch (_) {} await wait(100); }
  throw new Error('Product server did not start');
}
async function state(page) { return page.evaluate(() => ModelViewer.getState().meshTools); }
async function open(page, file) {
  await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, file);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
}
async function loadMesh(page) {
  await page.locator('#viewer-mesh-deleter').evaluate(e => { e.open = true; });
  const response = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect'));
  await page.locator('#viewer-mesh-deleter-load').click(); const listing = await (await response).json();
  const chosen = listing.meshes.find(m => m.available && m.name === 'Body') || listing.meshes.find(m => m.available), value = JSON.stringify(chosen.mesh);
  const dataResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/data'));
  await page.locator('#viewer-mesh-deleter-select').selectOption(value); const data = await (await dataResponse).json();
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
  return { data, value };
}
async function project(page, mesh, vertex) { return page.evaluate(({ mesh, vertex }) => ModelViewer.projectMeshVertex(mesh, vertex), { mesh, vertex }); }
async function stageFocus(page) { await page.locator('#viewer-stage canvas').evaluate(e => { e.tabIndex = 0; e.focus({ preventScroll: true }); }); }
async function shortcut(page, key) { await stageFocus(page); await page.keyboard.press(key); await page.waitForTimeout(70); }
async function save(page, id = '#viewer-mesh-deleter-save') {
  const response = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/export'));
  await page.locator(id).click(); const r = await response; assert.equal(r.status(), 200, await r.text());
  const output = await r.json(); await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy); return output;
}
async function post(page, route, payload) { return page.evaluate(async ({ route, payload }) => { const response = await fetch('/api/viewer/mesh/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); if (!response.ok) throw new Error(await response.text()); return response.json(); }, { route, payload }); }
async function inspectCopy(page, output) {
  const prepared = await page.evaluate(async paths => { const response = await fetch('/api/viewer/prepare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths, rigged: true, auto_face: false }) }); if (!response.ok) throw new Error(await response.text()); return response.json(); }, output.preview_paths);
  const token = prepared.editing.token, listing = await post(page, 'inspect', { token }); return post(page, 'data', { token, mesh: (listing.meshes.find(m => m.available && m.name === 'Body') || listing.meshes.find(m => m.available)).mesh });
}
async function run() {
  let server, browser, context;
  const report = { status: 'RUNNING', evidence, cases: [] };
  try {
    server = await startServer(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function'); await open(page, source);
    const { data, value } = await loadMesh(page), originalToken = await page.evaluate(() => ModelViewer.getEditingMetadata().token);
    assert.equal((await state(page)).runtime.bindings[0].vertexCount, data.positions.length);
    // UV paint selects/highlights the corresponding *actual* 3D triangles.
    const face = data.triangles[0], uv = [0, 1].map(axis => face.reduce((s, v) => s + data.uv[v][axis], 0) / 3);
    const canvas = page.locator('#viewer-mesh-deleter-canvas'); await canvas.scrollIntoViewIfNeeded(); const box = await canvas.boundingBox();
    await page.mouse.move(box.x + uv[0] * box.width, box.y + (1 - uv[1]) * box.height);
    assert(await page.locator('#viewer-mesh-uv-cursor').isVisible());
    const radius = +await page.locator('#viewer-mesh-deleter input[type=number]').inputValue();
    near((await page.locator('#viewer-mesh-uv-cursor').boundingBox()).width, radius * 2, 'UV brush size in CSS pixels');
    await page.mouse.down(); await page.mouse.up();
    let s = await state(page); assert(s.selectedFaces.length > 0); assert.equal(s.runtime.highlightedFaces, s.selectedFaces.length); assert.equal(s.runtime.bindings[0].triangles, 4);
    await page.screenshot({ path: path.join(evidence, '01-uv-selection-on-live-model.png') });
    const marked = s.selectedFaces.slice(); await page.locator('#viewer-mesh-deleter-delete').click();
    s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 4 - marked.length); assert.equal(s.selectedFaces.length, 0);
    await shortcut(page, 'Control+z'); s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 4); assert.deepStrictEqual(s.selectedFaces, marked);
    await shortcut(page, 'Meta+Shift+z'); s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 4 - marked.length);
    const deletionCopy = await save(page);
    assert.equal(await page.evaluate(() => ModelViewer.getEditingMetadata().token), originalToken, 'Save retains the live source session and undo history');
    await shortcut(page, 'Meta+z'); s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 4, 'Undo after serializing a copy restores live indices');
    // Saving after Undo serializes the restored topology, not a prior deletion.
    const restoredCopy = await save(page); const restored = await inspectCopy(page, restoredCopy); assert.equal(restored.triangles.length, 4);
    const deleted = await inspectCopy(page, deletionCopy); assert.equal(deleted.triangles.length, 4 - marked.length);
    report.cases.push({ name: 'UV selection, exact live deletion, keyboard Undo/Redo, serialized-save undo', selectedFaces: marked, deletedTriangles: deleted.triangles.length, restoredTriangles: restored.triangles.length });
    // Clear the restored selection and paint directly on the model surface.
    await page.locator('#viewer-mesh-deleter').getByRole('button', { name: 'Clear selection', exact: true }).click();
    await page.locator('#viewer-mesh-deleter-scene-mode').selectOption('paint');
    const centre = await Promise.all(face.map(v => project(page, data.mesh, v)));
    const target = { x: centre.reduce((sum, p) => sum + p.x, 0) / 3, y: centre.reduce((sum, p) => sum + p.y, 0) / 3 };
    await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
    await page.mouse.move(target.x, target.y); assert(await page.locator('#viewer-mesh-brush-cursor').isVisible());
    await page.mouse.down(); await page.mouse.up(); s = await state(page); assert(s.selectedFaces.length > 0, 'Direct model stroke selects source faces'); assert.equal(s.runtime.highlightedFaces, s.selectedFaces.length);
    await shortcut(page, 'Control+z'); assert.equal((await state(page)).selectedFaces.length, 0);
    report.cases.push({ name: 'direct 3D surface brush', hit: target });
    // Vertex dots are exact original-vertex click targets; drag updates geometry.
    await page.locator('#viewer-mesh-modify').evaluate(e => { e.open = true; }); await page.locator('#viewer-mesh-modify-select').selectOption(value);
    await page.locator('#viewer-mesh-modify-scene-mode').selectOption('pick');
    let vertex = await project(page, data.mesh, 2); await page.mouse.click(vertex.x, vertex.y); s = await state(page); assert.deepStrictEqual(s.selectedVertices, [2]); assert(s.runtime.vertexDots > 0);
    await page.locator('#viewer-mesh-modify [data-mesh-position-axis=X]').fill('.1234567'); await page.locator('#viewer-mesh-modify-position-set').click();
    s = await state(page); near(s.edits.meshes[0].positions[0].position[0], .1234567, 'Finite sub-millimeter source coordinate accepted'); near(s.edits.meshes[0].positions[0].position[1], data.positions[2][1], 'Untouched source Float32 coordinate retained');
    await shortcut(page, 'Control+z');
    for (const [axis, number] of [['X', '.2'], ['Y', '.8'], ['Z', '-.1']]) await page.locator('#viewer-mesh-modify [data-mesh-position-axis=' + axis + ']').fill(number);
    await page.locator('#viewer-mesh-modify-position-set').click(); s = await state(page);
    near(s.runtime.bindings[0].samplePositions[6], -.2, 'Live source X reflection'); near(s.runtime.bindings[0].samplePositions[7], .8, 'Live source Y'); near(s.runtime.bindings[0].samplePositions[8], -.1, 'Live source Z');
    await shortcut(page, 'Control+z'); s = await state(page); near(s.runtime.bindings[0].samplePositions[6], -data.positions[2][0], 'Undo restores actual source position');
    await shortcut(page, 'Control+Shift+z');
    await page.locator('#viewer-mesh-modify-scene-mode').selectOption('drag'); vertex = await project(page, data.mesh, 2);
    const beforeDrag = (await state(page)).edits.meshes[0].positions[0].position.slice();
    await page.mouse.move(vertex.x, vertex.y); await page.mouse.down(); await page.mouse.move(vertex.x + 25, vertex.y - 15, { steps: 4 }); await page.mouse.up();
    const afterDrag = (await state(page)).edits.meshes[0].positions[0].position; assert.notDeepStrictEqual(afterDrag, beforeDrag, 'Dragging a node edits source-local positions');
    await shortcut(page, 'Control+z'); assert.deepStrictEqual((await state(page)).edits.meshes[0].positions[0].position, beforeDrag);
    // Weight assignment changes actual GPU skin attributes; undo restores them.
    await page.locator('#viewer-mesh-modify-weight-bone').selectOption('2'); await page.locator('#viewer-mesh-modify-weight-value').fill('.4'); await page.locator('#viewer-mesh-modify-weight-apply').click();
    s = await state(page); const weights = s.runtime.bindings[0].sampleWeights.slice(8, 12); near(weights.reduce((sum, n) => sum + n, 0), 1, 'Live GPU skin weights normalize'); assert(weights.some(w => Math.abs(w - .4) < 1e-5));
    const weightCopy = await save(page, '#viewer-mesh-modify-save'); const savedWeights = await inspectCopy(page, weightCopy); near(savedWeights.skin[2].find(([index]) => index === 2)[1], .4, 'Serialized changed skin weight');
    await shortcut(page, 'Control+z'); s = await state(page); near(s.runtime.bindings[0].sampleWeights[8], 1, 'Undo after saving restores prior skin');
    await page.screenshot({ path: path.join(evidence, '02-live-vertex-targets.png') });
    report.cases.push({ name: '3D vertex pick, live XYZ, drag and GPU/serialized skin with Undo', beforeDrag, afterDrag, weights });
    if (gameSource) {
      const gameHash = sha(fs.readFileSync(gameSource)); await open(page, gameSource);
      const loaded = await loadMesh(page), game = loaded.data;
      assert(game.positions.length > 100, 'The original game costume supplies real geometry');
      await page.locator('#viewer-mesh-deleter-scene-mode').selectOption('paint');
      await page.locator('#viewer-mesh-deleter input[type=number]').fill('4');
      await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
      const submesh = game.submeshes[0], step = Math.max(1, Math.floor(submesh.faceCount / 70)); let picked = null;
      for (let local = 0; local < submesh.faceCount && !picked; local += step) {
        const faceId = submesh.firstFace + local, face = game.triangles[faceId], points = await Promise.all(face.map(v => project(page, game.mesh, v)));
        if (points.some(p => !p || p.depth < -1 || p.depth > 1)) continue;
        const target = { x: points.reduce((sum, p) => sum + p.x, 0) / 3, y: points.reduce((sum, p) => sum + p.y, 0) / 3 };
        const hittable = await page.evaluate(point => { const e = document.elementFromPoint(point.x, point.y); return !!e && e.tagName === 'CANVAS' && !!e.closest('#viewer-stage'); }, target);
        if (!hittable) continue; await page.mouse.click(target.x, target.y);
        if ((await state(page)).selectedFaces.length) picked = target;
      }
      assert(picked, 'Direct brush hits a real costume surface');
      const selected = (await state(page)).selectedFaces;
      assert(selected.every(face => face >= submesh.firstFace && face < submesh.firstFace + submesh.faceCount));
      assert.equal((await state(page)).runtime.highlightedFaces, selected.length);
      await page.screenshot({ path: path.join(evidence, '03-original-game-costume-selection.png') });
      await page.locator('#viewer-mesh-deleter-delete').click(); const realCopy = await save(page), actual = await inspectCopy(page, realCopy);
      assert.equal(actual.triangles.length, game.triangles.length - selected.length, 'Exact selected original faces are serialized');
      const expectedFaces = game.triangles.filter((face, index) => !selected.includes(index)); assert.deepStrictEqual(actual.triangles, expectedFaces, 'Other source face/vertex identities remain intact');
      await shortcut(page, 'Control+z'); assert((await state(page)).runtime.bindings.reduce((sum, b) => sum + b.triangles, 0) >= game.triangles.length);
      assert.equal(sha(fs.readFileSync(gameSource)), gameHash, 'Original game bundle remains unchanged');
      report.cases.push({ name: 'original game costume direct 3D selection/deletion/serialized exact-face identity and Undo', vertices: game.positions.length, faces: game.triangles.length, deletedFaces: selected.length, sourceSha256: gameHash });
    }
    assert.equal(sha(fs.readFileSync(source)), sha(raw), 'Original file is immutable'); assert.deepStrictEqual(errors, [], 'No browser exceptions'); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); }
}
if (require.main === module) run().catch(() => { process.exitCode = 1; });
