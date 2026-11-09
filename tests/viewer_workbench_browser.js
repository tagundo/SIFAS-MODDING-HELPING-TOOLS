/* Workbench integration through real HTTP, Unity bundles and WebGL.
 * Uses original generated geometry. No successful API responses are mocked. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const repo = path.resolve(__dirname, '../..'), product = path.join(repo, 'modtools');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-workbench-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-workbench-library-'));
const models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'neutral.unity'), donor = path.join(models, 'donor.unity');
const replacement = path.join(models, 'replacement.unity');
const raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, raw); fs.writeFileSync(donor, raw);
fs.writeFileSync(replacement, raw);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const near = (actual, expected, label) => assert(Math.abs(actual - expected) < .00001, label + ': ' + actual + ' != ' + expected);

async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: repo, env: { ...process.env, PYTHONPATH: [product, process.env.PYTHONPATH || ''].filter(Boolean).join(path.delimiter), SUKUSTA_DIR: library },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Server exited: ' + fs.readFileSync(path.join(evidence, 'server.log'), 'utf8'));
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* starting */ }
    await wait(100);
  }
  child.kill(); throw new Error('Workbench server not ready');
}

async function post(page, endpoint, payload) {
  const result = await page.evaluate(async ({ endpoint, payload }) => {
    const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    return { status: response.status, data: await response.json() };
  }, { endpoint, payload });
  assert.equal(result.status, 200, endpoint + ': ' + JSON.stringify(result.data));
  assert(!result.data.error, JSON.stringify(result.data)); return result.data;
}
async function openSource(page) {
  await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
}
function wav() {
  const rate = 8000, seconds = 3, bytes = Buffer.alloc(44 + rate * seconds * 2);
  bytes.write('RIFF'); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8); bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22); bytes.writeUInt32LE(rate, 24); bytes.writeUInt32LE(rate * 2, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(bytes.length - 44, 40); return bytes;
}

async function checkMotions(page) {
  await page.locator('#viewer-adjustments').evaluate(element => { element.open = true; });
  assert(await page.locator('#viewer-game-motions').isVisible());
  const catalog = page.waitForResponse(response => response.url().includes('/api/viewer/game/motions/catalog') && response.status() === 200);
  await page.locator('#viewer-game-motions').click();
  const data = await (await catalog).json();
  assert.deepStrictEqual(data.categories.map(entry => entry.value), ['home', 'tap', 'voice', 'mv', 'special']);
  await page.locator('#viewer-motion-character').selectOption('1');
  await page.waitForFunction(() => document.getElementById('viewer-game-motion-choice').options.length > 1);
  const counts = {};
  for (const category of ['home', 'tap', 'voice', 'mv', 'special']) {
    if (category !== 'home') {
      const response = page.waitForResponse(response => response.url().includes('/api/viewer/game/motions/catalog') && new URL(response.url()).searchParams.get('category') === category);
      await page.locator('#viewer-motion-category').selectOption(category); const loaded = await response;
      assert.equal(loaded.status(), 200); const catalog = await loaded.json(); counts[category] = catalog.motions.length;
      assert(catalog.motions.length > 0, category + ' has real game catalog rows');
    } else counts.home = await page.locator('#viewer-game-motion-choice option').count() - 1;
  }
  await page.keyboard.press('Escape');
  await page.locator('#viewer-motion-audio-file').evaluate(element => element.closest('details').open = true);
  await page.locator('#viewer-motion-audio-file').setInputFiles({ name: 'neutral-silence.wav', mimeType: 'audio/wav', buffer: wav() });
  await page.waitForFunction(() => ViewerGameMotions.getAudioState().loaded && ViewerGameMotions.getAudioState().enabled);
  const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value && !option.disabled).value);
  await page.locator('#viewer-motion').selectOption(clip);
  await page.locator('#viewer-time').press('Home');
  await page.locator('#viewer-play').click();
  await page.waitForFunction(() => ModelViewer.getState().rig.playing && !ViewerGameMotions.getAudioState().paused && ViewerGameMotions.getAudioState().time > .05);
  await page.locator('#viewer-play').click();
  await page.waitForFunction(() => !ModelViewer.getState().rig.playing && ViewerGameMotions.getAudioState().paused);
  return { categories: counts, audio: await page.evaluate(() => ViewerGameMotions.getAudioState()) };
}

async function checkDonors(page) {
  const output = [];
  for (const id of ['viewer-costume-transplant', 'viewer-part-transplant', 'viewer-lower-transplant']) {
    await page.locator('#' + id).evaluate(element => { element.open = true; });
    const response = page.waitForResponse(response => response.url().endsWith('/api/viewer/transplant/inspect'));
    await page.locator('#' + id + ' [data-transplant-label="Choose donor costume"]').click();
    await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
    const inspected = await response; assert.equal(inspected.status(), 200, await inspected.text());
    await page.locator('#' + id + ' .viewer-transplant-stage canvas').waitFor({ state: 'visible' });
    const data = await inspected.json(); assert.equal(data.sha256, sha(raw));
    output.push({ id, parts: data.parts.length, platform: data.platform });
  }
  await page.locator('#viewer-lower-transplant-low').fill('.3'); await page.locator('#viewer-lower-transplant-low').dispatchEvent('input');
  await page.locator('#viewer-lower-transplant-high').fill('.9'); await page.locator('#viewer-lower-transplant-high').dispatchEvent('input');
  const lower = await page.evaluate(() => ModelViewer.getState().transplants.donors.find(entry => entry.operation === 'lower'));
  near(lower.cutLow, .3, 'Lower cut'); near(lower.cutHigh, .9, 'Upper cut');
  return output;
}

async function checkMeshUI(page) {
  await page.locator('#viewer-body-adjustments').evaluate(element => { element.open = true; });
  await page.locator('#viewer-editor-node-tab').click();
  await page.locator('#viewer-breast-card').evaluate(element => { element.open = true; });
  const breastProfile = await page.locator('#viewer-breast-preset option').evaluateAll(options => options.find(option => option.value !== 'loaded' && !option.disabled).value);
  await page.locator('#viewer-breast-preset').selectOption(breastProfile);
  await page.waitForFunction(() => !document.getElementById('viewer-save').disabled);
  const bodyState = await page.evaluate(() => ModelViewer.getAuthoringState());
  const breastNode = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'BreastSize').node);
  const breastEdit = bodyState.edits.find(edit => edit.node === breastNode);
  assert(breastEdit && breastEdit.scale, 'Real body preset creates a body change before mesh editing');
  const token = await page.evaluate(() => ModelViewer.getEditingMetadata().token);
  await page.locator('#viewer-mesh-deleter').evaluate(element => { element.open = true; });
  const inspectedResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect'));
  await page.locator('#viewer-mesh-deleter-load').click();
  const inspected = await (await inspectedResponse).json();
  const identity = inspected.meshes.find(mesh => mesh.available).mesh;
  const identityValue = JSON.stringify(identity);
  const originalResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data'));
  await page.locator('#viewer-mesh-deleter-select').selectOption(identityValue);
  const original = await (await originalResponse).json();
  assert(original.uv && original.texture && original.skinWritable && original.positionWritable);
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
  const face = original.triangles[0], centre = [0, 1].map(axis => face.reduce((sum, vertex) => sum + original.uv[vertex][axis], 0) / 3);
  const canvas = page.locator('#viewer-mesh-deleter-canvas'); await canvas.scrollIntoViewIfNeeded();
  const bounds = await canvas.boundingBox();
  await page.mouse.click(bounds.x + centre[0] * bounds.width, bounds.y + (1 - centre[1]) * bounds.height);
  const painted = await page.evaluate(() => ModelViewer.getState().meshTools.edits.meshes[0].deleteFaces);
  assert(painted.length > 0 && painted.length < original.triangles.length, 'Texture brush selects a bounded region');
  assert(await page.locator('#viewer-save').isDisabled(), 'Pending mesh edits disable the separate body save');
  await page.locator('#viewer-mesh-deleter-undo').click();
  assert.equal(await page.evaluate(() => ModelViewer.getState().meshTools.dirty), false, 'Undo reverses the brush');
  assert(!await page.locator('#viewer-save').isDisabled(), 'Undoing the only mesh edit restores body save availability');
  await page.locator('#viewer-mesh-deleter-redo').click();
  assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().meshTools.edits.meshes[0].deleteFaces), painted);
  assert(await page.locator('#viewer-save').isDisabled(), 'Redo blocks separate body save again');
  await page.locator('#viewer-mesh-modify').evaluate(element => { element.open = true; });
  await page.locator('#viewer-mesh-modify-select').selectOption(identityValue);
  await page.locator('#viewer-mesh-modify-vertex').fill('2');
  await page.locator('#viewer-mesh-modify-select-vertex').click();
  for (const [axis, value] of [['X', '.2'], ['Y', '.8'], ['Z', '-.1']]) await page.locator('#viewer-mesh-modify [data-mesh-position-axis=' + axis + ']').fill(value);
  await page.locator('#viewer-mesh-modify-position-set').click();
  await page.locator('#viewer-mesh-modify-weight-bone').selectOption('2');
  await page.locator('#viewer-mesh-modify-weight-value').fill('.4');
  await page.locator('#viewer-mesh-modify-weight-apply').click();
  const pending = await page.evaluate(() => ModelViewer.getState().meshTools.edits);
  assert.equal(pending.meshes[0].positions[0].vertex, 2);
  assert.equal(pending.meshes[0].weights[0].vertex, 2);
  near(pending.meshes[0].weights[0].influences.find(([index]) => index === 2)[1], .4, 'UI weight assignment');
  const exported = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/export'));
  await page.locator('#viewer-mesh-modify-save').click();
  const resultResponse = await exported;
  assert.equal(resultResponse.status(), 200, await resultResponse.text());
  const saved = await resultResponse.json();
  assert.equal(saved.preview_paths.length, 1); assert(fs.existsSync(saved.preview_paths[0]));
  const serialized = JSON.parse(execFileSync(python, [path.join(__dirname, 'inspect_viewer_persistence.py'), saved.preview_paths[0]], { cwd: product, encoding: 'utf8' }));
  const savedBreast = serialized.components.flatMap(component => component.entries).find(entry => entry.kind === 'scale' && entry.target === 'BreastSize');
  assert(savedBreast, 'Mesh output retains a serialized breast adjustment');
  savedBreast.scaled.forEach((value, axis) => near(value, breastEdit.scale[axis], 'Body change preserved in mesh export ' + axis));
  assert.equal(sha(fs.readFileSync(source)), sha(raw), 'The source model remains unchanged');
  await page.waitForFunction(paths => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths[0] === paths[0] && ModelViewer.getEditingMetadata().available, saved.preview_paths);
  const secondToken = await page.evaluate(() => ModelViewer.getEditingMetadata().token);
  const afterInspect = await post(page, '/api/viewer/mesh/inspect', { token: secondToken });
  const after = await post(page, '/api/viewer/mesh/data', { token: secondToken, mesh: afterInspect.meshes.find(mesh => mesh.available).mesh });
  assert.equal(after.triangles.length, original.triangles.length - painted.length);
  after.positions[2].forEach((value, axis) => near(value, [.2, .8, -.1][axis], 'Saved vertex axis ' + axis));
  near(after.skin[2].find(([index]) => index === 2)[1], .4, 'Saved assigned influence');
  near(after.skin[2].reduce((sum, pair) => sum + pair[1], 0), 1, 'Saved influence sum');
  return { facesBefore: original.triangles.length, facesAfter: after.triangles.length, position: after.positions[2], skin: after.skin[2], breastScale: savedBreast.scaled, saved: saved.preview_paths[0] };
}

async function checkMeshSaveRace(page) {
  await page.locator('#viewer-mesh-modify').evaluate(element => { element.open = true; });
  const inspectedResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect'));
  await page.locator('#viewer-mesh-modify-load').click();
  const inspected = await (await inspectedResponse).json();
  const dataResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data'));
  await page.locator('#viewer-mesh-modify-select').selectOption(JSON.stringify(inspected.meshes.find(mesh => mesh.available).mesh));
  await dataResponse; await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
  await page.locator('#viewer-mesh-modify-vertex').fill('1');
  await page.locator('#viewer-mesh-modify-select-vertex').click();
  await page.locator('#viewer-mesh-modify [data-mesh-position-axis=X]').fill('.123');
  await page.locator('#viewer-mesh-modify-position-set').click();
  function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
  const exportReady = deferred(), exportGate = deferred(), exportSent = deferred(), prepareReady = deferred(), prepareGate = deferred();
  let saved = null;
  const routeErrors = [];
  const exportHandler = async route => {
    try {
      const response = await route.fetch();
      const bytes = await response.body();
      assert.equal(response.status(), 200, bytes.toString()); saved = JSON.parse(bytes);
      exportReady.resolve(); await exportGate.promise;
      await route.fulfill({ response, body: bytes }); exportSent.resolve();
    } catch (error) { routeErrors.push(String(error)); exportReady.resolve(); exportSent.resolve(); await route.abort().catch(() => {}); }
  };
  const prepareHandler = async route => {
    if (JSON.stringify(route.request().postDataJSON().paths) !== JSON.stringify([replacement])) return route.continue();
    try {
      const response = await route.fetch(); const bytes = await response.body();
      assert.equal(response.status(), 200, bytes.toString()); prepareReady.resolve();
      await prepareGate.promise; await route.fulfill({ response, body: bytes });
    } catch (error) { routeErrors.push(String(error)); prepareReady.resolve(); await route.abort().catch(() => {}); }
  };
  await page.route('**/api/viewer/mesh/export', exportHandler);
  await page.route('**/api/viewer/prepare', prepareHandler);
  try {
    await page.locator('#viewer-mesh-modify-save').click(); await exportReady.promise;
    assert(saved && saved.preview_paths.length === 1, 'The held export is a successful real backend response');
    await page.evaluate(path => {
      window.__replacementOpenResult = null;
      ModelViewer.open([path]).then(() => { window.__replacementOpenResult = 'done'; }, error => { window.__replacementOpenResult = String(error); });
    }, replacement);
    await prepareReady.promise;
    assert(await page.evaluate(() => ModelViewer.getState().loading), 'The newer model is being opened');
    exportGate.resolve(); await exportSent.promise;
    await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
    const pending = await page.evaluate(() => ({ paths: ModelViewer.getState().paths, loading: ModelViewer.getState().loading }));
    assert.deepStrictEqual(pending.paths, [replacement], 'An older mesh save cannot retarget the newer pending Open');
    assert(pending.loading, 'The actual newer prepare response remains pending');
    prepareGate.resolve();
    await page.waitForFunction(path => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths[0] === path, replacement);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().paths), [replacement]);
    assert(fs.existsSync(saved.preview_paths[0]), 'The older requested save still writes its copy');
    assert.deepStrictEqual(routeErrors, []);
    return { newerPaths: [replacement], oldSavedCopy: saved.preview_paths[0], heldRealExportAndPrepareResponses: true };
  } finally {
    exportGate.resolve(); prepareGate.resolve();
    await page.unroute('**/api/viewer/mesh/export', exportHandler);
    await page.unroute('**/api/viewer/prepare', prepareHandler);
  }
}

async function checkMaterialScope(page) {
  const multi = path.join(models, 'multi-material.unity');
  execFileSync(python, [path.join(__dirname, 'generate_viewer_mesh_fixture.py'), multi], { cwd: product });
  const originalHash = sha(fs.readFileSync(multi));
  await page.evaluate(path => ModelViewer.open([path]), multi);
  await page.waitForFunction(path => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths[0] === path, multi);
  await page.locator('#viewer-mesh-deleter').evaluate(element => { element.open = true; });
  const inspectResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect'));
  await page.locator('#viewer-mesh-deleter-load').click();
  const inspected = await (await inspectResponse).json();
  const dataResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data'));
  await page.locator('#viewer-mesh-deleter-select').selectOption(JSON.stringify(inspected.meshes.find(mesh => mesh.available).mesh));
  const data = await (await dataResponse).json();
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
  assert.deepStrictEqual(data.submeshes.map(material => material.faceCount), [4, 4]);
  assert.equal(data.textures.length, 2); assert.notEqual(data.textures[0], data.textures[1]);
  const canvas = page.locator('#viewer-mesh-deleter-canvas');
  const sample = () => canvas.evaluate(element => Array.from(element.getContext('2d').getImageData(600, 40, 1, 1).data));
  await page.waitForFunction(() => document.getElementById('viewer-mesh-deleter-canvas').getContext('2d').getImageData(600, 40, 1, 1).data[3] > 0);
  const firstColor = await sample();
  const face = data.triangles[0], centre = [0, 1].map(axis => face.reduce((sum, vertex) => sum + data.uv[vertex][axis], 0) / 3);
  async function paint() {
    await canvas.scrollIntoViewIfNeeded(); const bounds = await canvas.boundingBox();
    await page.mouse.click(bounds.x + centre[0] * bounds.width, bounds.y + (1 - centre[1]) * bounds.height);
    return page.evaluate(() => ModelViewer.getState().meshTools.edits.meshes[0].deleteFaces);
  }
  const firstPaint = await paint();
  assert(firstPaint.length > 0 && firstPaint.every(index => index < 4), 'Painting material 0 leaves overlapping material 1 untouched');
  await page.locator('#viewer-mesh-deleter-submesh').selectOption('1');
  const secondColor = await sample(); assert.notDeepStrictEqual(secondColor, firstColor, 'Changing material displays its actual different texture');
  const bothPaint = await paint();
  assert(bothPaint.some(index => index >= 4), 'Painting material 1 selects its own overlapping faces');
  await page.locator('#viewer-mesh-deleter-undo').click();
  assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().meshTools.edits.meshes[0].deleteFaces), firstPaint, 'Undo restores just the first material selection');
  const exportResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/export'));
  await page.locator('#viewer-mesh-deleter-save').click();
  const result = await exportResponse; assert.equal(result.status(), 200, await result.text());
  const saved = await result.json();
  await page.waitForFunction(path => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths[0] === path, saved.preview_paths[0]);
  const token = await page.evaluate(() => ModelViewer.getEditingMetadata().token);
  const afterInspect = await post(page, '/api/viewer/mesh/inspect', { token });
  const after = await post(page, '/api/viewer/mesh/data', { token, mesh: afterInspect.meshes.find(mesh => mesh.available).mesh });
  assert.deepStrictEqual(after.submeshes.map(material => material.faceCount), [4 - firstPaint.length, 4]);
  assert.equal(sha(fs.readFileSync(multi)), originalHash);
  return { before: [4, 4], after: after.submeshes.map(material => material.faceCount), firstColor, secondColor, overlappingUVsScoped: true };
}

async function run() {
  let server, browser, context;
  const report = { status: 'RUNNING', scope: 'Actual HTTP/serialized neutral Unity fixture/browser UI; transplant inspection and preview, no claim successful game costume graft', cases: [] };
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1360, height: 1000 } });
    await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    const page = await context.newPage(), errors = [], failed = [];
    page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
    page.on('response', response => { if (response.status() >= 400 && response.url().includes('/static/')) failed.push(response.url() + ': ' + response.status()); });
    await page.goto(server.url); await page.waitForFunction(() => typeof ModelViewer !== 'undefined');
    await openSource(page);
    assert.deepStrictEqual(failed, [], 'Every workbench script loads');
    const panelIds = ['viewer-costume-transplant', 'viewer-part-transplant', 'viewer-lower-transplant', 'viewer-mesh-deleter', 'viewer-mesh-modify'];
    for (const id of panelIds) await page.locator('#' + id).waitFor();
    await page.locator('#viewer-panel-settings').click();
    for (const id of panelIds) assert(await page.locator('#viewer-panel-settings-dialog [data-panel-id=' + JSON.stringify(id) + ']').count(), 'Settings include dynamic panel ' + id);
    await page.keyboard.press('Escape');
    report.cases.push({ name: 'game catalog and accompanying audio', ...await checkMotions(page) });
    report.cases.push({ name: 'donor inspection and separate preview', donors: await checkDonors(page) });
    report.cases.push({ name: 'UV brush, position/weight controls and real mesh export roundtrip', ...await checkMeshUI(page) });
    report.cases.push({ name: 'older mesh save preserves newer pending model Open', ...await checkMeshSaveRace(page) });
    report.cases.push({ name: 'overlapping UVs are scoped to the selected material', ...await checkMaterialScope(page) });
    await page.setViewportSize({ width: 448, height: 998 });
    await page.locator('#viewer-panel-settings').click();
    await page.screenshot({ path: path.join(evidence, 'workbench-panels-ko-phone.png') }); await page.keyboard.press('Escape');
    assert.deepStrictEqual(errors, [], 'No browser exceptions'); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally {
    if (context) await context.close(); if (browser) await browser.close();
    if (server) { server.child.kill(); server.stream.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ ...report, evidence }, null, 2));
  }
}
if (require.main === module) run().catch(() => { process.exitCode = 1; });
