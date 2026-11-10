/* Actual Unity/HTTP/canvas UV colors: all three tools, reload and source safety. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-uv-color-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-uv-color-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'wearer.unity'), donor = path.join(models, 'donor.unity');
fs.copyFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'), source);
const pythonEnv = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) };
execFileSync(python, ['-c', `import struct,sys
from pathlib import Path
import UnityPy
from test_viewer_transplants import costume_fixture
from sifas_mesh_baker import stream_layout
env=UnityPy.load(costume_fixture())
for obj in env.objects:
 if obj.type.name!='Mesh': continue
 tree=obj.read_typetree();count,channels,strides,starts,_=stream_layout(tree)
 raw=bytearray(tree['m_VertexData']['m_DataSize']);uv=channels[4]
 for vertex in range(count):
  point=[(.15,.15),(.85,.15),(.5,.85)][vertex%3]
  struct.pack_into('<2f',raw,starts[uv['stream']]+vertex*strides[uv['stream']]+uv['offset'],*point)
 tree['m_VertexData']['m_DataSize']=bytes(raw);obj.save_typetree(tree)
Path(sys.argv[1]).write_bytes(env.file.save())`, donor], { cwd: product, env: pythonEnv });
const sha = value => crypto.createHash('sha256').update(value).digest('hex'), originalHash = sha(fs.readFileSync(source)), donorHash = sha(fs.readFileSync(donor));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const ids = ['viewer-mesh-deleter', 'viewer-mesh-modify', 'viewer-part-transplant'];
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...pythonEnv, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw Error('Product server did not become ready');
}
async function show(page, id) { const locator = page.locator('#' + id); await locator.evaluate(node => { for (let p = node; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
async function setup(page) {
  await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
  await show(page, 'viewer-mesh-deleter');
  const listingPromise = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/inspect')); await page.locator('#viewer-mesh-deleter-load').click();
  const listing = await (await listingPromise).json(), mesh = listing.meshes.find(row => row.available).mesh, value = JSON.stringify(mesh);
  const dataPromise = page.waitForResponse(response => response.url().endsWith('/api/viewer/mesh/data')); await page.locator('#viewer-mesh-deleter-select').selectOption(value);
  const data = await (await dataPromise).json(); await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
  await show(page, 'viewer-mesh-modify'); await page.locator('#viewer-mesh-modify-select').selectOption(value);
  const panel = await show(page, 'viewer-part-transplant'); await panel.getByRole('button', { name: 'Choose donor costume', exact: true }).click();
  await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
  await page.evaluate(directory => navigate(directory), models); await page.waitForFunction(directory => document.getElementById('picker-crumb').textContent === directory, models);
  await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
  await page.waitForFunction(() => ModelViewer.getState().transplants.donors.some(row => row.operation === 'part' && row.donor) && !ModelViewer.getState().transplants.busy);
  await page.locator('#viewer-part-transplant-selection-mode').selectOption('triangles');
  await page.locator('#viewer-part-transplant-texture').waitFor({ state: 'visible' });
  await wait(200); return { data, value, mesh };
}
async function pixels(page) {
  const values = await page.evaluate(ids => ids.map(id => {
    const canvas = document.querySelector('#' + id + (id === 'viewer-part-transplant' ? '-texture' : '-canvas'));
    return { panel: id, color: document.getElementById(id + '-uv-color').value, image: canvas.toDataURL(), width: canvas.width, height: canvas.height };
  }), ids);
  return values.map(value => ({ panel: value.panel, color: value.color, sha256: sha(value.image), width: value.width, height: value.height }));
}
async function change(page, id, color) {
  await (await show(page, id + '-uv-color')).evaluate((input, color) => { input.value = color; input.dispatchEvent(new Event('input', { bubbles: true })); }, color);
  return pixels(page);
}
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    await context.addInitScript(() => { localStorage.setItem('sifas_lang', 'en'); let api;
      Object.defineProperty(window, 'ViewerMeshTools', { configurable: true, get: () => api, set: value => { api = value; const create = value.create;
        value.create = function () { const tool = create.apply(this, arguments); window.__uvMeshTool = tool; return tool; }; } }); });
    const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function'); const loaded = await setup(page);
    const beforeEdits = await page.evaluate(() => ({ body: ModelViewer.getAuthoringState(), mesh: __uvMeshTool.getEdits(), history: ModelViewer.getState().meshTools.history,
      selection: ModelViewer.getState().transplants.donors.find(row => row.operation === 'part').selectedTriangles }));
    let previous = await pixels(page); report.initialCanvases = previous;
    for (const [index, color] of ['#ff00ff', '#00ffff', '#00ff00'].entries()) {
      const current = await change(page, ids[index], color);
      report.lastCanvases = current;
      report.donorTexture = await page.evaluate(() => ({ status: document.querySelector('#viewer-part-transplant .viewer-transplant-texture-panel').innerText,
        materials: Array.from(document.getElementById('viewer-part-transplant-texture-material').options).map(option => ({ value: option.value, text: option.text })),
        donor: ModelViewer.getState().transplants.donors.find(row => row.operation === 'part') }));
      for (let tool = 0; tool < ids.length; tool++) { assert.equal(current[tool].color, color); assert.notEqual(current[tool].sha256, previous[tool].sha256, 'Real UV canvas changes color: ' + ids[tool]); }
      assert.equal(await page.evaluate(() => localStorage.getItem('elichika.viewer.uv-color.v1')), color);
      report.cases.push({ name: 'Changing ' + ids[index] + ' updates the actual UV drawing and controls in all three tools', color, canvases: current }); previous = current;
    }
    assert.deepStrictEqual(await page.evaluate(() => ({ body: ModelViewer.getAuthoringState(), mesh: __uvMeshTool.getEdits(), history: ModelViewer.getState().meshTools.history,
      selection: ModelViewer.getState().transplants.donors.find(row => row.operation === 'part').selectedTriangles })), beforeEdits, 'Display color never authors model/texture edits or selection history');
    await page.reload(); await page.waitForFunction(() => typeof openModelViewer === 'function'); await setup(page);
    const reloaded = await pixels(page); reloaded.forEach((value, index) => { assert.equal(value.color, '#00ff00'); assert.equal(value.sha256, previous[index].sha256); });
    report.cases.push({ name: 'Full application reload preserves the shared UV preference and redraws identical original texture/UV canvases', canvases: reloaded });
    await page.evaluate(mesh => __uvMeshTool.restoreEdits({ version: 1, meshes: [{ mesh, deleteFaces: [1] }] }), loaded.mesh);
    await show(page, 'viewer-mesh-deleter-canvas');
    const uv = loaded.data.triangles[0].reduce((sum, vertex) => [sum[0] + loaded.data.uv[vertex][0] / 3, sum[1] + loaded.data.uv[vertex][1] / 3], [0, 0]);
    const box = await page.locator('#viewer-mesh-deleter-canvas').boundingBox(); await page.mouse.click(box.x + uv[0] * box.width, box.y + (1 - uv[1]) * box.height);
    assert.equal(await page.evaluate(() => __uvMeshTool.getStatus().hasUnappliedSelection), true);
    assert.equal(await page.evaluate(() => ModelViewer.getState().meshTools.hasUnappliedSelection), true);
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Global Save cannot silently omit newly painted face selections');
    await page.locator('#viewer-mesh-deleter').getByRole('button', { name: 'Clear selection', exact: true }).click();
    assert.equal(await page.evaluate(() => __uvMeshTool.getStatus().hasUnappliedSelection), false);
    await show(page, 'viewer-mesh-modify-select-vertex'); await page.locator('#viewer-mesh-modify-select-vertex').click();
    const selected = await page.evaluate(() => ModelViewer.getState().meshTools); assert.equal(selected.selectedVertices.length, 1); assert.equal(selected.hasUnappliedSelection, false); assert.equal(selected.edits.meshes.length, 1);
    assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'Vertex-only selection preserves valid global Save');
    report.cases.push({ name: 'Applied edits plus unapplied painted faces report the dedicated save blocker; selecting vertices alone does not block', selectedVertices: selected.selectedVertices });
    for (const id of ids) { await show(page, id); await page.locator('#' + id).screenshot({ path: path.join(evidence, id + '.png') }); }
    assert.equal(sha(fs.readFileSync(source)), originalHash); assert.equal(sha(fs.readFileSync(donor)), donorHash); assert.deepStrictEqual(errors, []);
    report.sources = [{ path: source, sha256: originalHash }, { path: donor, sha256: donorHash }]; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify(report, null, 2)); }
}
if (require.main === module) main().catch(() => { process.exitCode = 1; });
