/* Source-bound outline diagnostics through real HTTP, controls and clipboard. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outline-diagnostics-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outline-diagnostics-library-'));
const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const sources = ['outline-first.unity', 'outline-second.unity'].map(name => path.join(models, name));
const pythonEnv = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) };
execFileSync(python, ['-c', `import sys
from pathlib import Path
import UnityPy
from test_model_outlines import colored_fixture
for index,name in enumerate(sys.argv[1:]):
 env=UnityPy.load(colored_fixture())
 for obj in env.objects:
  if obj.type.name=='Mesh':
   tree=obj.read_typetree();tree['m_Name']='Diagnostic mesh '+str(index+1);obj.save_typetree(tree)
 Path(name).write_bytes(env.file.save())`, ...sources], { cwd: product, env: pythonEnv });
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashes = sources.map(sha), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function show(locator) { await locator.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
async function field(page, selector, value) { const input = await show(page.locator(selector)); await input.fill(String(value)); await input.dispatchEvent('input'); }
async function boot() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...pythonEnv, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 150; n++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); }
  throw new Error('Product server did not become ready');
}
async function open(page, paths) {
  await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(paths); }, paths);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available && !ModelViewer.getState().materials.loading);
  await show(page.locator('#viewer-outline-diagnostics-copy'));
}
async function immutable(page) {
  return page.evaluate(() => {
    const attributes = [];
    window.__outlineRoot.traverse(mesh => {
      if (!mesh.isMesh || mesh.userData.viewerHelper) return;
      attributes.push({ name: mesh.name, attributes: Object.fromEntries(Object.entries(mesh.geometry.attributes).map(([key, value]) => [key, Array.from(value.array)])) });
    });
    return JSON.stringify({ authoring: ModelViewer.getAuthoringState(), catalogue: ModelViewer.getEditingMetadata().outlines, attributes });
  });
}
async function run() {
  const report = { status: 'RUNNING', evidence, cases: [], sourceHashesBefore: hashes };
  let server, browser;
  try {
    server = await boot();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage(), errors = [], requests = [];
    page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error.stack || error)));
    page.on('request', request => requests.push({ method: request.method(), url: request.url() }));
    await page.addInitScript(() => {
      localStorage.setItem('sifas_lang', 'en');
      Object.defineProperty(window, 'SifasMaterial', { configurable: true, set(value) {
        const apply = value.apply; value.apply = function (root) { window.__outlineRoot = root; return apply.apply(this, arguments); };
        Object.defineProperty(window, 'SifasMaterial', { configurable: true, writable: true, value });
      } });
    });
    await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && window.ViewerOutlines && document.getElementById('viewer-outline-diagnostics-copy'));
    assert(await page.locator('#viewer-outline-diagnostics-copy').isDisabled(), 'No model cannot copy diagnostics');
    await open(page, sources);
    const catalogue = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines);
    assert.deepStrictEqual(catalogue.sources, sources.map((file, sourceIndex) => ({ sourceIndex, name: path.basename(file), sha256: hashes[sourceIndex] })));
    async function copy() {
      const before = await immutable(page), start = requests.length;
      await page.locator('#viewer-outline-diagnostics-copy').click();
      await page.waitForFunction(() => !document.getElementById('viewer-outline-diagnostics-copy').disabled && !document.getElementById('viewer-outline-diagnostics-status').hidden);
      await wait(100);
      assert.strictEqual(await immutable(page), before, 'Copy changes no authoring, metadata or source/preview vertex buffers');
      assert.deepStrictEqual(requests.slice(start), [], 'Copy issues no HTTP request, upload or save');
      const copied = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
      assert(!JSON.stringify(copied).includes(library), 'Diagnostics omit absolute source paths');
      return copied;
    }
    const pristine = await copy();
    assert.equal(pristine.format, 'elichika-outline-diagnostics'); assert.equal(pristine.version, 1);
    assert.equal(pristine.editedMeshCount, 0); assert(pristine.rendering.sifasEnabled);
    assert(pristine.meshes.every(mesh => mesh.factor === 1 && mesh.localVertexEditCount === 0 && !Object.hasOwn(mesh, 'absolute')));
    assert(!Object.hasOwn(pristine, 'appVersion'), 'No release version is invented');
    assert.deepStrictEqual(pristine.sources, catalogue.sources);
    assert.deepStrictEqual(pristine.meshes.map(mesh => mesh.originalWidth), catalogue.meshes.map(mesh => mesh.originalWidth));
    assert.equal(await page.locator('#viewer-outline-diagnostics-status').innerText(), 'Outline diagnostics copied.');
    assert(await page.locator('#viewer-outline-diagnostics-text').isHidden());
    report.cases.push({ name: 'Actual clipboard API copies source hashes and unchanged original defaults without HTTP or mutation', diagnostics: pristine });

    await page.locator('#viewer-outline-mesh').selectOption(catalogue.meshes[0].id);
    await field(page, '#viewer-outline-absolute', 37); await page.locator('#viewer-outline-absolute-apply').click();
    await field(page, '#viewer-outline-number', 50);
    await field(page, '#viewer-outline-vertex-width', 25); await field(page, '#viewer-outline-vertex-index', 0);
    await (await show(page.locator('#viewer-outline-vertex-apply'))).click();
    await show(page.locator('#viewer-outline-diagnostics-copy'));
    const edited = await copy(), first = edited.meshes.find(mesh => mesh.id === catalogue.meshes[0].id), other = edited.meshes.find(mesh => mesh.id === catalogue.meshes[1].id);
    assert.equal(edited.editedMeshCount, 1); assert.equal(edited.selection.meshId, first.id); assert.equal(edited.selection.meshCount, 1);
    assert.equal(first.factor, .5); assert.equal(first.absolute, 37); assert.equal(first.localVertexEditCount, 1);
    assert.equal(other.factor, 1); assert.equal(other.localVertexEditCount, 0); assert(!Object.hasOwn(other, 'absolute'));
    assert.deepStrictEqual(edited.meshes.map(mesh => mesh.originalWidth), pristine.meshes.map(mesh => mesh.originalWidth));
    await (await show(page.locator('#viewer-shader'))).selectOption('basic');
    await show(page.locator('#viewer-outline-diagnostics-copy'));
    assert.equal((await copy()).rendering.sifasEnabled, false, 'Report identifies disabled SIFAS preview');
    report.cases.push({ name: 'Current source-bound factor, absolute byte, local vertex count and selection; original widths stay unchanged', diagnostics: edited });

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('Denied in test'); } } });
      document.execCommand = () => false;
    });
    const fallbackBefore = await immutable(page), fallbackStart = requests.length;
    await page.locator('#viewer-outline-diagnostics-copy').click();
    await page.waitForFunction(() => !document.getElementById('viewer-outline-diagnostics-text').hidden);
    const fallback = await page.locator('#viewer-outline-diagnostics-text').evaluate(node => ({ text: node.value, readOnly: node.readOnly, selected: node.selectionEnd - node.selectionStart, active: document.activeElement === node }));
    assert(fallback.readOnly && fallback.active && fallback.selected === fallback.text.length, 'Denied clipboard provides fully selected, copyable readonly JSON');
    assert.equal(JSON.parse(fallback.text).editedMeshCount, 1);
    assert.equal(await page.locator('#viewer-outline-diagnostics-status').innerText(), 'Select and copy the diagnostics below.');
    assert.strictEqual(await immutable(page), fallbackBefore); assert.deepStrictEqual(requests.slice(fallbackStart), []);
    await page.screenshot({ path: path.join(evidence, 'fallback-selectable.png') });

    await open(page, [sources[1]]);
    assert(await page.locator('#viewer-outline-diagnostics-text').isHidden(), 'New model clears prior model diagnostics fallback');
    assert.equal(await page.locator('#viewer-outline-diagnostics-text').inputValue(), '');
    assert(await page.locator('#viewer-outline-diagnostics-status').isHidden());
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), [], 'New model discards unsaved outline edits');
    await page.locator('#viewer-outline-diagnostics-copy').click();
    const reopened = JSON.parse(await page.locator('#viewer-outline-diagnostics-text').inputValue());
    assert.equal(reopened.editedMeshCount, 0); assert.equal(reopened.meshes.length, 1); assert.equal(reopened.meshes[0].factor, 1);
    assert.deepStrictEqual(reopened.sources, [{ sourceIndex: 0, name: path.basename(sources[1]), sha256: hashes[1] }]);
    report.cases.push({ name: 'Clipboard-denied selectable fallback and new-model clearing without outline leakage', diagnostics: reopened });

    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.getElementById('viewer-outline-diagnostics-copy').textContent === '외곽선 진단 복사');
    await show(page.locator('#viewer-outline-diagnostics-copy')); await page.locator('#viewer-outline-diagnostics-copy').click();
    assert.equal(await page.locator('#viewer-outline-diagnostics-status').innerText(), '아래 진단 내용을 선택해 복사하세요.');
    assert.equal(await page.locator('#viewer-outline-diagnostics-text').getAttribute('aria-label'), '외곽선 진단');
    report.cases.push({ name: 'Korean copy action, status and accessible fallback label' });
    assert.deepStrictEqual(sources.map(sha), hashes, 'Every original Unity fixture remains byte-identical');
    assert.deepStrictEqual(errors, []); assert(!requests.some(request => /\/api\/viewer\/edit\/(?:export|mod|install)/.test(request.url)), 'No save/export route is used by this test');
    report.sourceHashesAfter = sources.map(sha); report.pageErrors = errors; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally {
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    if (browser) await browser.close(); if (server) { server.child.kill('SIGTERM'); server.stream.end(); }
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error || null }));
  }
}
run();
