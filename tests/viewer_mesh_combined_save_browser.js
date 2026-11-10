/* Real Unity/HTTP/WebGL: global mesh + body + outline save and source re-edit. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-combined-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-combined-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'colored-original.unity');
const pythonEnv = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) };
execFileSync(python, ['-c', 'import sys\nfrom pathlib import Path\nfrom test_model_outlines import colored_fixture\nPath(sys.argv[1]).write_bytes(colored_fixture())', source], { cwd: product, env: pythonEnv });
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const originalHash = sha(source), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const actualSource = process.env.MESH_COMBINED_GAME_MODEL ? path.join(models, path.basename(process.env.MESH_COMBINED_GAME_MODEL)) : '';
if (actualSource) fs.copyFileSync(process.env.MESH_COMBINED_GAME_MODEL, actualSource);
const actualHash = actualSource ? sha(actualSource) : '';
const state = page => page.evaluate(() => ModelViewer.getState());
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function show(page, selector) {
  const locator = page.locator(selector);
  await locator.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await locator.scrollIntoViewIfNeeded(); return locator;
}
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...pythonEnv, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw Error('Product server did not become ready');
}
async function points(page) {
  await frames(page);
  return page.evaluate(() => {
    const result = []; __combinedScene.scene.updateMatrixWorld(true);
    __combinedScene.scene.traverseVisible(mesh => {
      if (!mesh.isMesh || mesh.userData.viewerHelper || mesh.userData.sifasOutline || !mesh.geometry || !mesh.geometry.attributes.position) return;
      const positions = mesh.geometry.attributes.position;
      for (let index = 0; index < positions.count; index++) {
        const original = new THREE.Vector3().fromBufferAttribute(positions, index), point = original.clone();
        (mesh.geometry.morphAttributes.position || []).forEach((morph, channel) => {
          const amount = mesh.morphTargetInfluences && mesh.morphTargetInfluences[channel] || 0;
          const delta = new THREE.Vector3().fromBufferAttribute(morph, index);
          if (!mesh.geometry.morphTargetsRelative) delta.sub(original); point.addScaledVector(delta, amount);
        });
        if (mesh.isSkinnedMesh) mesh.boneTransform(index, point);
        point.applyMatrix4(mesh.matrixWorld); result.push(point.toArray());
      }
    }); return result;
  });
}
function comparePoints(actual, expected) {
  assert.equal(actual.length, expected.length); let maximum = 0;
  actual.forEach((point, vertex) => point.forEach((axis, index) => { maximum = Math.max(maximum, Math.abs(axis - expected[vertex][index])); }));
  assert(maximum < .00003, 'Saved mesh/body skin matches preview: ' + maximum); return maximum;
}
async function save(page) {
  const button = await show(page, '#viewer-save'); assert.equal(await button.isDisabled(), false);
  const before = (await state(page)).persistence.recipePath; await button.click();
  await page.waitForFunction(before => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.recipePath && p.recipePath !== before); }, before);
  const saved = (await state(page)).persistence; assert(!saved.error, saved.error); assert(saved.previewPaths.length && fs.existsSync(saved.recipePath)); return saved;
}
async function clickAndWait(page, selector, expectedStatus) {
  await (await show(page, selector)).click();
  await page.waitForFunction(expectedStatus => { const p = ModelViewer.getState().persistence; return !ModelViewer.getState().loading && !p.busy && (p.error || p.status === expectedStatus); }, expectedStatus);
  const saved = (await state(page)).persistence; assert(!saved.error, saved.error); return saved;
}
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    // Capture real controllers and the actual rendered scene for assertions.
    await context.addInitScript(() => {
      let meshAPI, qualityAPI;
      Object.defineProperty(window, 'ViewerMeshTools', { configurable: true, get: () => meshAPI, set: value => { meshAPI = value; const create = value.create;
        value.create = function () { const tool = create.apply(this, arguments); window.__combinedMeshTool = tool; return tool; }; } });
      Object.defineProperty(window, 'ViewerQuality', { configurable: true, get: () => qualityAPI, set: value => { qualityAPI = value; const create = value.create;
        value.create = function () { const controller = create.apply(this, arguments), render = controller.render;
          controller.render = function (scene, camera) { window.__combinedScene = { scene, camera }; return render.apply(this, arguments); }; return controller; }; } });
    });
    const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
    const thigh = metadata.nodes.find(node => node.name === 'LeftUpLeg'), breast = metadata.nodes.find(node => node.name === 'BreastSize');
    assert(thigh && breast && metadata.outlines.available);
    const body = { version: 1, savedSettingsEnabled: true, edits: [
      { node: thigh.node, method: 'mesh', scale: [1.4, 1.1, 1.2] },
      { node: breast.node, method: 'node', scale: [1.05, 1.02, 1.03] }
    ], outlines: [{ id: metadata.outlines.meshes[0].id, factor: .5, vertices: [{ vertex: 1, value: .25 }] }] };
    await page.evaluate(body => ModelViewer.restoreAuthoringState(body), body);
    const mesh = await page.evaluate(async () => {
      const response = await fetch('/api/viewer/mesh/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: ModelViewer.getEditingMetadata().token }) });
      if (!response.ok) throw Error(await response.text()); return (await response.json()).meshes.find(row => row.available).mesh;
    });
    const meshState = { version: 1, meshes: [{ mesh, deleteFaces: [1], positions: [{ vertex: 2, position: [.2, .8, -.1] }], weights: [{ vertex: 2, influences: [[0, .2], [1, .8]] }] }] };
    await page.evaluate(value => __combinedMeshTool.restoreEdits(value), meshState);
    await (await show(page, '#viewer-pose-basic')).click();
    const expectedPoints = await points(page), authored = await page.evaluate(() => ModelViewer.getAuthoringState()), meshEdits = (await state(page)).meshTools.edits;
    const first = await save(page), recipe = JSON.parse(fs.readFileSync(first.recipePath, 'utf8'));
    assert.equal(recipe.tool, 'mesh-tools'); assert.deepStrictEqual(recipe.state, meshEdits); assert.equal(recipe.bodyState.edits.length, 2); assert.equal(recipe.bodyState.outlines.length, 1);
    assert.deepStrictEqual(recipe.bodyRecipe.state, recipe.bodyState); assert.equal(sha(source), originalHash);
    assert.equal((await state(page)).meshTools.history, 1, 'Save preserves mesh Undo');
    report.cases.push({ name: 'Global Save includes actual deletion, positions, weights, mesh/body methods and per-vertex outlines in one source-bound recipe', recipePath: first.recipePath, output: first.previewPaths[0], sha256: sha(first.previewPaths[0]) });

    await clickAndWait(page, '#viewer-open-saved', 'reviewing');
    assert.equal((await state(page)).persistence.reviewingSaved, true); assert.equal(await page.locator('#viewer-save').isDisabled(), true);
    await (await show(page, '#viewer-pose-basic')).click();
    const reloadError = comparePoints(await points(page), expectedPoints);
    const outputMesh = await page.evaluate(async () => { const token = ModelViewer.getEditingMetadata().token;
      async function request(endpoint, body) { const r = await fetch('/api/viewer/mesh/' + endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!r.ok) throw Error(await r.text()); return r.json(); }
      const mesh = (await request('inspect', { token })).meshes.find(row => row.available).mesh; return request('data', { token, mesh }); });
    assert.equal(outputMesh.triangles.length, 3); assert(outputMesh.skin[2].some(pair => Math.abs(pair[1] - .8) < 1e-6));
    report.cases.push({ name: 'Open Saved reloads actual serialized topology and weighted/body preview without a second bake', maximumVertexError: reloadError, triangles: outputMesh.triangles.length });

    await clickAndWait(page, '#viewer-reedit-original', 'restored');
    assert.deepStrictEqual((await state(page)).meshTools.edits, meshEdits);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored);
    assert.equal((await state(page)).meshTools.history, 1, 'Whole restored mesh recipe is one Undo entry');
    await page.evaluate(() => __combinedMeshTool.undo()); assert.deepStrictEqual((await state(page)).meshTools.edits.meshes, []);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored, 'Mesh Undo preserves body and outline edits');
    await page.evaluate(() => __combinedMeshTool.redo()); assert.deepStrictEqual((await state(page)).meshTools.edits, meshEdits);
    const second = await save(page); assert.notEqual(second.previewPaths[0], first.previewPaths[0]); assert.equal(sha(second.previewPaths[0]), sha(first.previewPaths[0]), 'Recipe rebuild is byte-identical');
    report.cases.push({ name: 'Re-edit Original restores all channels atomically; one mesh Undo/Redo and repeat Save preserve body/outline without accumulating edits', secondOutput: second.previewPaths[0], sha256: sha(second.previewPaths[0]) });

    await page.evaluate(() => __combinedMeshTool.restoreEdits({ version: 1, meshes: [] }));
    await page.evaluate(() => ModelViewer.restoreAuthoringState({ version: 1, edits: [], savedSettingsEnabled: true }));
    await (await show(page, '#viewer-recipe-open')).click(); await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
    await page.evaluate(directory => navigate(directory), path.dirname(first.recipePath));
    await page.waitForFunction(directory => document.getElementById('picker-crumb').textContent === directory, path.dirname(first.recipePath));
    await page.locator('#picker-entries li').filter({ hasText: path.basename(first.recipePath) }).click();
    await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.status === 'restored'); });
    assert(!(await state(page)).persistence.error, (await state(page)).persistence.error);
    assert.deepStrictEqual((await state(page)).meshTools.edits, meshEdits); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored);
    report.cases.push({ name: 'Load Recipe through the application file picker restores all channels from current immutable originals' });
    await page.evaluate(() => ModelViewer.restoreAuthoringState({ version: 1, edits: [], savedSettingsEnabled: true }));
    const meshOnly = await save(page), meshOnlyRecipe = JSON.parse(fs.readFileSync(meshOnly.recipePath, 'utf8'));
    assert.deepStrictEqual(meshOnlyRecipe.state, meshEdits); assert.deepStrictEqual(meshOnlyRecipe.bodyState.edits, []); assert(!meshOnlyRecipe.bodyState.outlines);
    await clickAndWait(page, '#viewer-open-saved', 'reviewing'); await clickAndWait(page, '#viewer-reedit-original', 'restored');
    assert.deepStrictEqual((await state(page)).meshTools.edits, meshEdits);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().edits), []);
    report.cases.push({ name: 'Mesh-only global Save/Open Saved/Re-edit Original works with an empty validated body recipe', output: meshOnly.previewPaths[0], sha256: sha(meshOnly.previewPaths[0]) });
    if (actualSource) {
      await page.evaluate(file => openModelViewer([file]), actualSource);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
      const data = await page.evaluate(async () => {
        const token = ModelViewer.getEditingMetadata().token;
        async function request(endpoint, body) { const r = await fetch('/api/viewer/mesh/' + endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!r.ok) throw Error(await r.text()); return r.json(); }
        const record = (await request('inspect', { token })).meshes.find(row => row.available && row.name === 'Body');
        if (!record) throw Error('Real costume body is unavailable'); return request('data', { token, mesh: record.mesh });
      });
      assert.equal(data.skinWritable, true, 'Native signed32 game skin must be writable');
      const primary = data.skin[0][0][0], secondary = (primary + 1) % data.bones.length;
      const recipe = { version: 1, meshes: [{ mesh: data.mesh, deleteFaces: [0], positions: [{ vertex: 0, position: data.positions[0].map(value => value + .01) }], weights: [{ vertex: 0, influences: [[primary, .25], [secondary, .75]] }] }] };
      await page.evaluate(value => __combinedMeshTool.restoreEdits(value), recipe);
      const applied = (await state(page)).meshTools;
      assert.equal(applied.runtime.bindings.reduce((total, row) => total + row.triangles, 0), data.triangles.length - 1);
      assert(applied.runtime.bindings[0].sampleWeights.slice(0, 4).some(value => Math.abs(value - .75) < 1e-6));
      const saved = await save(page); await clickAndWait(page, '#viewer-open-saved', 'reviewing');
      const outputData = await page.evaluate(async identity => {
        const token = ModelViewer.getEditingMetadata().token, r = await fetch('/api/viewer/mesh/data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, mesh: identity }) });
        if (!r.ok) throw Error(await r.text()); return r.json();
      }, data.mesh);
      assert.equal(outputData.triangles.length, data.triangles.length - 1); assert.deepStrictEqual(outputData.skin[0], [[secondary, .75], [primary, .25]]);
      const gpu = await page.evaluate(identity => { const result = []; __combinedScene.scene.traverse(mesh => {
        if (!mesh.isMesh || mesh.userData.viewerHelper || mesh.userData.sifasOutline || !mesh.geometry) return;
        const map = mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh;
        if (map && map.mesh.source === identity.source && map.mesh.id === identity.id) result.push({ triangles: mesh.geometry.index.count / 3, weights: Array.from(mesh.geometry.attributes.skinWeight.array.slice(0, 4)) });
      }); return result; }, data.mesh);
      assert.equal(gpu.reduce((total, row) => total + row.triangles, 0), data.triangles.length - 1); assert(gpu[0].weights.some(value => Math.abs(value - .75) < 1e-6));
      const channels = JSON.parse(execFileSync(python, ['-c', `import json,sys
from pathlib import Path
from webtools.core import viewer_mesh_tools
rows=[]
for path in sys.argv[1:]:
 _,records=viewer_mesh_tools._mesh_records(Path(path).read_bytes(),0)
 tree=next(row[2] for row in records if row[2]['m_Name']=='Body')
 rows.append(tree['m_VertexData']['m_Channels'][13])
print(json.dumps(rows))`, actualSource, saved.previewPaths[0]], { cwd: product, env: pythonEnv, encoding: 'utf8' }));
      assert.equal(channels[0].format, 11); assert.deepStrictEqual(channels[1], channels[0]);
      await clickAndWait(page, '#viewer-reedit-original', 'restored'); assert.deepStrictEqual((await state(page)).meshTools.edits, applied.edits);
      await page.evaluate(() => __combinedMeshTool.undo()); assert.deepStrictEqual((await state(page)).meshTools.edits.meshes, []);
      await page.evaluate(() => __combinedMeshTool.redo()); assert.deepStrictEqual((await state(page)).meshTools.edits, applied.edits);
      const repeated = await save(page); assert.equal(sha(repeated.previewPaths[0]), sha(saved.previewPaths[0])); assert.equal(sha(actualSource), actualHash);
      report.cases.push({ name: 'Actual game signed32 body weights, positions and deletion survive GPU rendering, global export, serialized reload, re-edit and Undo/Redo without a second bake', source: process.env.MESH_COMBINED_GAME_MODEL, sourceSha256: actualHash, output: saved.previewPaths[0], outputSha256: sha(saved.previewPaths[0]), channel: channels[1], vertices: data.positions.length, triangles: data.triangles.length });
    }
    assert.equal(sha(source), originalHash); assert.deepStrictEqual(errors, []);
    await page.screenshot({ path: path.join(evidence, 'combined-saved-reedited.png') }); report.sourceSha256 = originalHash; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify(report, null, 2)); }
}
if (require.main === module) main().catch(() => { process.exitCode = 1; });
