/* Real Unity/HTTP/export/WebGL outline editing and generated GPU isolation. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outlines-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outlines-library-'));
const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const sources = ['colored-a.unity', 'colored-b.unity'].map(name => path.join(models, name));
const pythonEnv = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) };
execFileSync(python, ['-c', `import sys
from pathlib import Path
import UnityPy
from test_model_outlines import colored_fixture
for index,name in enumerate(sys.argv[1:]):
 env=UnityPy.load(colored_fixture())
 for obj in env.objects:
  if obj.type.name=='Mesh':
   tree=obj.read_typetree();tree['m_Name']='Outline mesh '+str(index+1);obj.save_typetree(tree)
 Path(name).write_bytes(env.file.save())`, ...sources], { cwd: product, env: pythonEnv });
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashes = sources.map(sha), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const actualSources = process.env.SIFAS_OUTLINE_BODY && process.env.SIFAS_OUTLINE_FACE ? ['ch0201_co0002.unity', 'ch0201_face.unity'].map((name, index) => { const file = path.join(models, name); fs.copyFileSync(process.env[index ? 'SIFAS_OUTLINE_FACE' : 'SIFAS_OUTLINE_BODY'], file); return file; }) : [];
const actualHashes = actualSources.map(sha);
async function show(locator) { await locator.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
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
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
}
async function field(page, selector, value) {
  const input = await show(page.locator(selector));
  if (await input.evaluate(node => node.type === 'range')) await input.evaluate((node, value) => { node.value = String(value); node.dispatchEvent(new Event('input', { bubbles: true })); }, value);
  else { await input.fill(String(value)); await input.dispatchEvent('input'); }
}
async function choose(page, selector, value) { const input = await show(page.locator(selector)); await input.focus(); await input.selectOption(value); }
async function geometry(page) {
  return page.evaluate(() => {
    const values = []; window.__outlineRoot.traverse(mesh => {
      if (!mesh.isMesh || mesh.userData.viewerHelper) return;
      const outline = mesh.children.find(child => child.userData.sifasOutline); if (!outline) return;
      values.push({ name: mesh.name, same: outline.geometry === mesh.geometry, geometry: mesh.geometry.uuid, outlineGeometry: outline.geometry.uuid,
        indices: mesh.geometry.index.count, outlineIndices: outline.geometry.index.count,
        positions: Array.from(mesh.geometry.attributes.position.array), outlinePositions: Array.from(outline.geometry.attributes.position.array) });
    }); return values;
  });
}
async function gpuCase(page) {
  await page.setContent('<html><body></body></html>');
  await page.addScriptTag({ path: path.join(product, 'webtools/web/static/vendor/three-r128/three.min.js') });
  await page.addScriptTag({ path: path.join(product, 'webtools/web/static/sifas-material.js') });
  return page.evaluate(async () => {
    const T = THREE, renderer = new T.WebGLRenderer({ antialias: false, stencil: true }); renderer.setSize(1024, 512); document.body.append(renderer.domElement);
    renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping;
    const scene = new T.Scene(); scene.background = new T.Color(0x141414);
    const root = new T.Group(); scene.add(root);
    const camera = new T.PerspectiveCamera(35, 2, .01, 10); camera.position.set(0, 0, 3); camera.lookAt(0, 0, 0);
    const shape = new T.SphereBufferGeometry(.4, 64, 32); shape.setAttribute('_sifas_color', new T.Float32BufferAttribute(Array(shape.attributes.position.count).fill([1, 1, 1, 1]).flat(), 4));
    const texture = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1, T.RGBAFormat); texture.encoding = T.sRGBEncoding; texture.needsUpdate = true;
    const original = new T.MeshBasicMaterial({ map: texture }); original.userData.sifas = { version: 1, shader: 'AS/Member', colors: {}, floats: { _CullMode: 2, _OutlineStencilComp: 8 }, features: { outline: true }, textures: { _MainTex: { index: 0 } } };
    const left = new T.Mesh(shape, original), right = new T.Mesh(shape, original); left.position.x = -.65; right.position.x = .65; root.add(left, right);
    [left, right].forEach((mesh, index) => mesh.userData.viewerMesh = { mesh: { source: 0, file: 'generated', id: String(index) } });
    const controller = SifasMaterial.apply(root, renderer, { parser: { getDependency: async () => texture } }); await controller.ready;
    const helpers = [left, right].map(mesh => mesh.children.find(child => child.userData.sifasOutline));
    const shared = helpers[0].material === helpers[1].material;
    function draw(a, b) {
      controller.setOutlineEdits([{ id: '0:generated:0', factor: a }, { id: '0:generated:1', factor: b }]); renderer.render(scene, camera);
      const gl = renderer.getContext(), pixels = new Uint8Array(1024 * 512 * 4), counts = [0, 0]; gl.readPixels(0, 0, 1024, 512, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      for (let y = 0; y < 512; y++) for (let x = 0; x < 1024; x++) { const offset = (y * 1024 + x) * 4; if (pixels[offset] > 65 && pixels[offset] < 150 && Math.abs(pixels[offset] - pixels[offset + 1]) < 3 && Math.abs(pixels[offset] - pixels[offset + 2]) < 3) counts[x < 512 ? 0 : 1]++; }
      return { factors: [a, b], outlinePixels: counts, glError: gl.getError() };
    }
    const both = draw(1, 1), onlyRight = draw(0, 1), onlyLeft = draw(1, 0), zero = draw(0, 0);
    return { shared, both, onlyRight, onlyLeft, zero, state: controller.getState() };
  });
}
async function run() {
  const report = { status: 'RUNNING', evidence, scope: 'Generated original UNorm8 Unity fixtures through real HTTP/export and WebGL; an observing material wrapper exposes actual mesh references without replacing rendering or responses', cases: [] };
  let server, browser;
  try {
    server = await boot(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }); page.setDefaultTimeout(30000);
    const errors = []; page.on('pageerror', error => errors.push(String(error.stack || error)));
    await page.addInitScript(() => {
      localStorage.setItem('sifas_lang', 'en');
      Object.defineProperty(window, 'SifasMaterial', { configurable: true, set(value) {
        const apply = value.apply; value.apply = function (root, renderer, options) { window.__outlineRoot = root; return apply.apply(this, arguments); };
        Object.defineProperty(window, 'SifasMaterial', { configurable: true, writable: true, value });
      } });
    });
    await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && window.ViewerOutlines && document.getElementById('viewer-outline-card')); await open(page, sources);
    const catalogue = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines);
    assert.equal(catalogue.meshes.length, 2); assert(catalogue.meshes.every(mesh => mesh.format === 'UNorm8'));
    const order = await page.evaluate(() => Array.from(document.getElementById('viewer-control-panel').children).map(node => node.id));
    assert(order.indexOf('viewer-outline-card') > order.indexOf('viewer-expression-adjustments') && order.indexOf('viewer-outline-card') < order.indexOf('viewer-body-adjustments'), 'Outline follows expressions and precedes body controls');
    await page.locator('#viewer-outline-card').evaluate(node => node.open = true);
    await choose(page, '#viewer-outline-mesh', catalogue.meshes[0].id); await field(page, '#viewer-outline-number', 50);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), [{ id: catalogue.meshes[0].id, factor: .5 }]);
    assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'An outline-only edit enables normal Save');
    await choose(page, '#viewer-shader', 'basic'); assert((await page.locator('#viewer-outline-status').innerText()).includes('Enable SIFAS rendering'));
    await choose(page, '#viewer-shader', 'sifas'); assert(!(await page.locator('#viewer-outline-status').innerText()).includes('Enable SIFAS rendering'));
    await choose(page, '#viewer-outline-mesh', catalogue.meshes[1].id); assert.equal(await page.locator('#viewer-outline-number').inputValue(), '100');
    await choose(page, '#viewer-outline-mesh', ''); assert.equal(await page.locator('#viewer-outline-number').inputValue(), '');
    await field(page, '#viewer-outline-range', 75); assert.equal((await page.evaluate(() => ModelViewer.getAuthoringState().outlines)).length, 2);
    await choose(page, '#viewer-outline-mesh', catalogue.meshes[0].id); await page.locator('#viewer-outline-reset').click();
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), [{ id: catalogue.meshes[1].id, factor: .75 }]);
    await choose(page, '#viewer-outline-mesh', ''); await field(page, '#viewer-outline-number', 50);
    await field(page, '#viewer-outline-number', 250); assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Invalid outline input blocks serialization');
    await page.locator('#viewer-outline-reset').click(); assert.equal(await page.locator('#viewer-outline-number').inputValue(), '100'); assert.equal(await page.locator('#viewer-outline-number').evaluate(node => node.validationMessage), '');
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Reset clears outline-only edits');
    await field(page, '#viewer-outline-number', 50);
    const authored = await page.evaluate(() => ModelViewer.getAuthoringState());
    const response = page.waitForResponse(r => r.url().endsWith('/api/viewer/edit/export'));
    await (await show(page.locator('#viewer-save'))).click(); assert.equal((await response).status(), 200);
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.previewPaths.length);
    const saved = await page.evaluate(() => ModelViewer.getState().persistence); assert(!saved.error, saved.error);
    const recipe = JSON.parse(fs.readFileSync(saved.recipePath, 'utf8')); assert.deepStrictEqual(recipe.state.outlines, authored.outlines);
    const preservation = JSON.parse(execFileSync(python, ['-c', `import json,sys
from pathlib import Path
from test_model_outlines import OutlineTests,colors
from webtools.core import model_edits
catalog=json.loads(sys.argv[1]);originals=json.loads(sys.argv[2]);outputs=json.loads(sys.argv[3]);case=OutlineTests('test_catalogue_rounding_clamp_masks_and_exact_unrelated_bytes');result=[]
for index,(original,output) in enumerate(zip(originals,outputs)):
 before=Path(original).read_bytes();after=Path(output).read_bytes();rows=[row for row in catalog['meshes'] if row['sourceIndex']==index]
 case.assert_only_red_changed(before,after,{(row['file'],int(row['meshId'])):.5 for row in rows})
 info=model_edits._inspect(after);result.append({'source':original,'saved':output,'red':colors(info['objects'][rows[0]['file'],int(rows[0]['meshId'])])[:,0].tolist(),'onlyRedChanged':True})
print(json.dumps(result))`, JSON.stringify(catalogue), JSON.stringify(sources), JSON.stringify(saved.previewPaths)], { cwd: product, env: pythonEnv }).toString());
    await open(page, saved.previewPaths); await page.locator('#viewer-outline-card').evaluate(node => node.open = true);
    assert.equal(await page.locator('#viewer-outline-number').inputValue(), '100'); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), [], 'Reopened copy starts from its baked source red mask at100%');
    await page.screenshot({ path: path.join(evidence, '01-saved-outline-copy.png') });
    report.cases.push({ name: 'Per-mesh/all controls, invalid/reset, shader status, real outline-only Save, portable recipe and source100% reopen', catalogue, authored, saved, preservation, order });
    await open(page, [sources[0]]); await page.locator('#viewer-outline-card').evaluate(node => node.open = true);
    const detailCatalog = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines), detailIdentity = detailCatalog.meshes[0].id;
    await choose(page, '#viewer-outline-mesh', detailIdentity); await field(page, '#viewer-outline-vertex-width', 50); await field(page, '#viewer-outline-vertex-index', 0);
    await page.locator('#viewer-outline-vertex-apply').click();
    const exactDetail = await page.evaluate(() => ModelViewer.getAuthoringState().outlines);
    assert.deepStrictEqual(exactDetail, [{ id: detailIdentity, factor: 1, vertices: [{ vertex: 0, value: .5 }] }]);
    const detailGpu = await page.evaluate(() => { ModelViewer.renderProbe(); const mesh = window.__outlineRoot.children.find(mesh => mesh.isMesh && !mesh.userData.viewerHelper) || (() => { let found; window.__outlineRoot.traverse(mesh => { if (!found && mesh.isMesh && !mesh.userData.viewerHelper) found = mesh; }); return found; })(); return { sourceRed: mesh.geometry.attributes._sifas_color.getX(0), previewRed: mesh.geometry.attributes._sifas_outline_width.getX(0), borrowed: mesh.children.find(child => child.userData.sifasOutline).geometry === mesh.geometry }; });
    assert.equal(detailGpu.sourceRed, 0, 'Preview never rewrites the authored color buffer'); assert(Math.abs(detailGpu.previewRed - 128 / 255) < 1e-7, 'Zero-red source vertex receives the actual final UNorm8 width'); assert(detailGpu.borrowed);
    await page.locator('#viewer-outline-undo').click(); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), []);
    await page.locator('#viewer-outline-redo').click(); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), exactDetail);
    await field(page, '#viewer-outline-vertex-width', 25); await choose(page, '#viewer-outline-scene-mode', 'paint');
    const paintPoint = await page.evaluate(identity => { const p = [0, 1, 2].map(index => ModelViewer.projectOutlineVertex(identity, index)); return { x: p[0].x * .9 + p[1].x * .05 + p[2].x * .05, y: p[0].y * .9 + p[1].y * .05 + p[2].y * .05 }; }, detailIdentity);
    await page.mouse.move(paintPoint.x, paintPoint.y); await page.mouse.down(); await page.mouse.up();
    const paintedDetail = await page.evaluate(() => ModelViewer.getAuthoringState().outlines);
    assert(paintedDetail[0].vertices.some(row => row.value === .25), 'Trusted 3D pointer paints source-bound vertex width');
    assert.equal(await page.locator('.viewer-outline-brush-cursor').evaluate(node => Number.parseFloat(node.style.width)), 48);
    await page.keyboard.press('Control+z'); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), exactDetail, 'Ctrl+Z restores one complete outline stroke');
    await page.keyboard.press('Control+Shift+z'); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), paintedDetail);
    await choose(page, '#viewer-outline-scene-mode', 'orbit');
    const detailExport = page.waitForResponse(response => response.url().endsWith('/api/viewer/edit/export')); await (await show(page.locator('#viewer-save'))).click(); assert.equal((await detailExport).status(), 200);
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.previewPaths.length);
    const detailSaved = await page.evaluate(() => ModelViewer.getState().persistence), detailRecipe = JSON.parse(fs.readFileSync(detailSaved.recipePath, 'utf8'));
    assert.deepStrictEqual(detailRecipe.state.outlines, paintedDetail, 'Sparse detailed edits survive the actual Save recipe');
    report.cases.push({ name: 'Sparse zero-mask vertex width, actual GPU override, 3D brush/cursor, Ctrl+Z/Redo and real detail export', exactDetail, detailGpu, paintedDetail, detailSaved });
    await open(page, sources); await choose(page, '#viewer-outline-mesh', '');
    const absoluteCatalogue = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines);
    await field(page, '#viewer-outline-absolute', 37); await page.locator('#viewer-outline-absolute-apply').click();
    const absoluteState = await page.evaluate(() => ModelViewer.getAuthoringState().outlines);
    assert.deepStrictEqual(absoluteState, absoluteCatalogue.meshes.map(mesh => ({ id: mesh.id, factor: 1, absolute: 37 })).sort((a, b) => a.id.localeCompare(b.id)));
    await field(page, '#viewer-outline-absolute', 1.5); assert(await page.locator('#viewer-save').isDisabled(), 'An invalid absolute raw byte must not serialize');
    await field(page, '#viewer-outline-absolute', 37); assert(!(await page.locator('#viewer-save').isDisabled()));
    const absoluteGPU = await page.evaluate(() => {
      ModelViewer.renderProbe(); const result = [];
      window.__outlineRoot.traverse(mesh => { if (!mesh.isMesh || mesh.userData.viewerHelper) return; const source = mesh.geometry.attributes._sifas_color, width = mesh.geometry.attributes._sifas_outline_width;
        result.push({ source: Array.from({ length: source.count }, (_, i) => source.getX(i)), width: width && Array.from(width.array) });
      }); return result;
    });
    assert(absoluteGPU.length === 2 && absoluteGPU.every(mesh => mesh.width.every(value => Math.abs(value - 37 / 255) < 1e-7)), 'Absolute raw 37 paints all source vertices, including original zero-red vertices');
    assert(absoluteGPU.every(mesh => mesh.source[0] === 0 && mesh.source[4] === 1), 'Absolute preview retains every immutable source mask');
    await page.locator('#viewer-outline-undo').click(); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), []);
    await page.locator('#viewer-outline-redo').click(); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), absoluteState);
    await choose(page, '#viewer-outline-mesh', absoluteCatalogue.meshes[0].id); await field(page, '#viewer-outline-vertex-index', 0); await page.locator('#viewer-outline-vertex-reset').click();
    const originalRestored = await page.evaluate(() => { ModelViewer.renderProbe(); let result; window.__outlineRoot.traverse(mesh => { const map = mesh.geometry && (mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh); if (mesh.isMesh && !mesh.userData.viewerHelper && map && map.mesh.source === 0) { window.__widthBufferBefore = mesh.geometry.attributes._sifas_outline_width; result = Array.from(window.__widthBufferBefore.array); } }); return result; });
    assert.equal(originalRestored[0], 0, 'Restore vertex recovers its original zero mask after an absolute fill'); assert(originalRestored.slice(1).every(value => Math.abs(value - 37 / 255) < 1e-7));
    await field(page, '#viewer-outline-vertex-width', 25); await page.locator('#viewer-outline-vertex-apply').click();
    const bufferReused = await page.evaluate(() => { ModelViewer.renderProbe(); let value; window.__outlineRoot.traverse(mesh => { const map = mesh.geometry && (mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh); if (mesh.isMesh && !mesh.userData.viewerHelper && map && map.mesh.source === 0) value = mesh.geometry.attributes._sifas_outline_width === window.__widthBufferBefore; }); return value; });
    assert(bufferReused, 'A sparse width update reuses its live GPU attribute instead of rebuilding geometry');
    await choose(page, '#viewer-outline-mesh', ''); await page.locator('#viewer-outline-absolute-apply').click();
    const absoluteResponse = page.waitForResponse(response => response.url().endsWith('/api/viewer/edit/export')); await (await show(page.locator('#viewer-save'))).click(); assert.equal((await absoluteResponse).status(), 200);
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.previewPaths.length === 2);
    const absoluteSaved = await page.evaluate(() => ModelViewer.getState().persistence);
    const absolutePreservation = JSON.parse(execFileSync(python, ['-c', `import json,sys
from pathlib import Path
from webtools.core.model_edits import _inspect
from webtools.core.model_outlines import _layout
catalog=json.loads(sys.argv[1]);before_paths=json.loads(sys.argv[2]);after_paths=json.loads(sys.argv[3]);out=[]
for index,(before_path,after_path) in enumerate(zip(before_paths,after_paths)):
 a,b=_inspect(Path(before_path).read_bytes()),_inspect(Path(after_path).read_bytes());keys={(r['file'],int(r['meshId'])) for r in catalog['meshes'] if r['sourceIndex']==index}
 for key,obj in a['objects'].items():
  if key not in keys:assert obj.get_raw_data()==b['objects'][key].get_raw_data();continue
  x,y=obj.read_typetree(),b['objects'][key].read_typetree();expected=bytearray(x['m_VertexData']['m_DataSize']);count,start,stride=_layout(x)
  for vertex in range(count):expected[start+vertex*stride]=37
  assert bytes(expected)==y['m_VertexData']['m_DataSize'];x['m_VertexData']['m_DataSize']=y['m_VertexData']['m_DataSize'];assert x==y
 out.append({'source':before_path,'saved':after_path,'onlyRedChanged':True,'allAbsolute':37})
print(json.dumps(out))`, JSON.stringify(absoluteCatalogue), JSON.stringify(sources), JSON.stringify(absoluteSaved.previewPaths)], { cwd: product, env: pythonEnv }).toString());
    await open(page, absoluteSaved.previewPaths); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), []);
    report.cases.push({ name: 'Compact absolute native width, original-zero restoration, GPU buffer reuse, Undo/Redo and actual red-only two-source export', absoluteState, absoluteGPU, originalRestored, bufferReused, absoluteSaved, absolutePreservation });
    await open(page, [sources[0]]); const before = await geometry(page); assert(before.length && before.every(value => value.same));
    await page.locator('#viewer-mesh-deleter').evaluate(node => node.open = true);
    const inspectResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect')); await page.locator('#viewer-mesh-deleter-load').click();
    const listing = await (await inspectResponse).json(), mesh = listing.meshes.find(mesh => mesh.available), choice = JSON.stringify(mesh.mesh);
    const dataResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/data')); await page.locator('#viewer-mesh-deleter-select').selectOption(choice); const data = await (await dataResponse).json();
    await page.waitForFunction(() => ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
    await page.evaluate(() => ModelViewer.renderProbe());
    const bound = await geometry(page); assert(bound.every(value => value.same)); assert.notEqual(bound[0].geometry, before[0].geometry, 'Mesh editor owns a new live geometry clone');
    const face = data.triangles[0], uv = [0, 1].map(axis => face.reduce((sum, vertex) => sum + data.uv[vertex][axis], 0) / 3), canvas = await show(page.locator('#viewer-mesh-deleter-canvas')), box = await canvas.boundingBox();
    await page.mouse.click(box.x + uv[0] * box.width, box.y + (1 - uv[1]) * box.height); assert((await page.evaluate(() => ModelViewer.getState().meshTools.selectedFaces)).length);
    await page.locator('#viewer-mesh-deleter-delete').click(); await page.evaluate(() => ModelViewer.renderProbe());
    const deleted = await geometry(page); assert(deleted.every(value => value.same && value.indices === value.outlineIndices)); assert(deleted[0].indices < bound[0].indices);
    await page.locator('#viewer-mesh-deleter').getByRole('button', { name: 'Undo', exact: true }).click(); await page.evaluate(() => ModelViewer.renderProbe());
    const restored = await geometry(page); assert.equal(restored[0].indices, bound[0].indices); assert(restored.every(value => value.same));
    await page.locator('#viewer-mesh-modify').evaluate(node => node.open = true); await page.locator('#viewer-mesh-modify-select').selectOption(choice);
    await page.locator('#viewer-mesh-modify-select-vertex').click(); await field(page, '#viewer-mesh-modify [data-mesh-position-axis=X]', .1234567); await page.locator('#viewer-mesh-modify-position-set').click(); await page.evaluate(() => ModelViewer.renderProbe());
    const moved = await geometry(page); assert(moved.every(value => value.same)); assert.deepStrictEqual(moved[0].positions, moved[0].outlinePositions); assert.notDeepStrictEqual(moved[0].positions, bound[0].positions);
    await page.locator('#viewer-mesh-modify').getByRole('button', { name: 'Undo', exact: true }).click(); await page.evaluate(() => ModelViewer.renderProbe());
    const undo = await geometry(page); assert(undo.every(value => value.same)); assert.deepStrictEqual(undo[0].positions, bound[0].positions);
    report.cases.push({ name: 'Actual live outline shares editor geometry through binding, deletion, vertex move and Undo', before, bound, deleted, restored, moved, undo });
    if (actualSources.length) {
      await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = true; return openModelViewer(paths); }, [actualSources[0]]);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().outlines.meshes.some(mesh => mesh.sourceIndex === 1 && mesh.name === 'Mouth'));
      const actualCatalogue = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines), jaw = actualCatalogue.meshes.find(mesh => mesh.sourceIndex === 1 && mesh.name === 'Mouth');
      const jawVertex = Number(execFileSync(python, ['-c', "import sys,numpy as np\nfrom pathlib import Path\nfrom UnityPy.helpers.MeshHelper import MeshHandler\nfrom webtools.core.model_edits import _inspect\ni=_inspect(Path(sys.argv[1]).read_bytes());m=next(o for o in i['objects'].values() if o.type.name=='Mesh' and o.read_typetree()['m_Name']=='Mouth');h=MeshHandler(m.read());h.process();print(int(np.argmin(np.asarray(h.m_Vertices)[:,1])))", actualSources[1]], { cwd: product, env: pythonEnv }).toString().trim());
      await choose(page, '#viewer-outline-mesh', jaw.id); await field(page, '#viewer-outline-vertex-width', 25); await field(page, '#viewer-outline-vertex-index', jawVertex); await page.locator('#viewer-outline-vertex-apply').click();
      const jawPreview = await page.evaluate(({ identity, vertex }) => { ModelViewer.renderProbe(); let result; window.__outlineRoot.traverse(mesh => { const map = mesh.geometry && mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh; if (!mesh.isMesh || mesh.userData.viewerHelper || !map || !map.mesh || [map.mesh.source, map.mesh.file, map.mesh.id].join(':') !== identity) return; result = { originalRed: mesh.geometry.attributes._sifas_color.getX(vertex), editedRed: mesh.geometry.attributes._sifas_outline_width.getX(vertex), positionWritable: map.writable, hasActualOutline: mesh.children.some(child => child.userData.sifasOutline) }; }); return result; }, { identity: jaw.id, vertex: jawVertex });
      assert(jawPreview && jawPreview.hasActualOutline); assert.equal(jawPreview.positionWritable, false, 'Auto-face position/skin protections remain in place'); assert.equal(jawPreview.originalRed, 1); assert(Math.abs(jawPreview.editedRed - 64 / 255) < 1e-7);
      const jawExport = page.waitForResponse(response => response.url().endsWith('/api/viewer/edit/export')); await (await show(page.locator('#viewer-save'))).click(); assert.equal((await jawExport).status(), 200);
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.previewPaths.length);
      const jawSaved = await page.evaluate(() => ModelViewer.getState().persistence); assert.equal(jawSaved.previewPaths.length, 2, 'Original body and verified companion face are exported as new copies');
      assert.deepStrictEqual(actualSources.map(sha), actualHashes); await page.screenshot({ path: path.join(evidence, '03-actual-jaw-detail-copy.png') });
      report.cases.push({ name: 'Original Ayumu auto-face lower jaw is source-bound, editable with protected skin, and saves model+face copies', jaw, jawVertex, jawPreview, jawSaved });
    }
    const gpu = await browser.newPage(); report.gpu = await gpuCase(gpu);
    assert(report.gpu.shared, 'Isolation test uses the same cached outline material for both meshes');
    assert(report.gpu.both.outlinePixels.every(count => count > 20), 'Stock outline produces measurable pixels');
    assert(report.gpu.onlyRight.outlinePixels[0] < report.gpu.both.outlinePixels[0] * .2 && report.gpu.onlyRight.outlinePixels[1] > 20, 'Zero left width does not change right width despite shared material');
    assert(report.gpu.onlyLeft.outlinePixels[1] < report.gpu.both.outlinePixels[1] * .2 && report.gpu.onlyLeft.outlinePixels[0] > 20, 'Reversed draw factors remain independent');
    assert(report.gpu.zero.outlinePixels.every(count => count < 5)); assert([report.gpu.both, report.gpu.onlyRight, report.gpu.onlyLeft, report.gpu.zero].every(frame => frame.glError === 0));
    await gpu.screenshot({ path: path.join(evidence, '02-generated-zero-outlines.png') }); await gpu.close();
    assert.deepStrictEqual(errors, []); assert.deepStrictEqual(sources.map(sha), hashes, 'Original Unity files remain byte-exact'); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
if (require.main === module) run();
