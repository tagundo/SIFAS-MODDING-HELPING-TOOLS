/* Real HTTP/3D/clipboard coverage for eligible and excluded outline meshes. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outline-inventory-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outline-inventory-library-'));
const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const names = ['renamed-body.unity', 'integer-colors.unity', 'unknown-shader.unity', 'standalone-mesh.unity', 'float-colors.unity'];
const sources = names.map(name => path.join(models, name));
const pythonEnv = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) };
execFileSync(python, ['-c', `import sys
from pathlib import Path
import numpy as np
import UnityPy
from test_model_outlines import colored_fixture
from sifas_mesh_baker import stream_layout
for kind,name in enumerate(sys.argv[1:]):
 env=UnityPy.load(colored_fixture())
 for obj in list(env.objects):
  tree=obj.read_typetree()
  if obj.type.name=='Mesh':
   tree['m_Name']=['사용자_의상.Mesh.001','Integer color mesh','Unknown shader mesh','Standalone mesh','Float color mesh'][kind]
   if kind==1:
    tree['m_VertexData']['m_Channels'][3]['format']=6
   if kind==4:
    count,channels,strides,starts,_=stream_layout(tree)
    data=bytes(tree['m_VertexData']['m_DataSize']); color=channels[3]
    assert strides=={0:56} and color['offset']==52
    body=b''.join(data[i*56:i*56+52] for i in range(count))
    rgba=np.asarray([list(data[i*56+52:i*56+56]) for i in range(count)],dtype='<f4')/255
    tree['m_VertexData']['m_DataSize']=body+bytes((-len(body))%16)+rgba.astype('<f4').tobytes()
    color.update(stream=1,offset=0,format=0)
   obj.save_typetree(tree)
  elif kind==0 and obj.type.name in ('GameObject','Material'):
   tree['m_Name']='사용자_의상.'+obj.type.name+'.'+str(obj.path_id); obj.save_typetree(tree)
  elif kind==2 and obj.type.name=='Shader':
   tree['m_Name']='Custom/OldMember'
   if 'm_ParsedForm' in tree: tree['m_ParsedForm']['m_Name']='Custom/OldMember'
   obj.save_typetree(tree)
  if kind==3 and obj.type.name in ('SkinnedMeshRenderer','MeshRenderer'):
   del obj.assets_file.objects[obj.path_id]
 Path(name).write_bytes(env.file.save())`, ...sources], { cwd: product, env: pythonEnv });
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashes = sources.map(sha), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function show(locator) { await locator.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
async function boot() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...pythonEnv, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 150; n++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); }
  throw new Error('Product server did not become ready');
}
async function open(page, selected) {
  await page.evaluate(selected => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(selected); }, selected);
  await page.waitForFunction(() => {
    const state = ModelViewer.getState(), editing = ModelViewer.getEditingMetadata();
    return state.loaded && !state.loading && editing && editing.outlines && !state.materials.loading;
  });
  await show(page.locator('#viewer-outline-mesh'));
  return page.evaluate(() => ModelViewer.getEditingMetadata());
}
async function immutable(page) {
  return page.evaluate(() => {
    const attributes = [];
    window.__outlineRoot.traverse(mesh => {
      if (!mesh.isMesh || mesh.userData.viewerHelper) return;
      attributes.push({ name: mesh.name, attributes: Object.fromEntries(Object.entries(mesh.geometry.attributes).map(([key, value]) => [key, Array.from(value.array)])) });
    });
    return JSON.stringify({ authoring: ModelViewer.getAuthoringState(), editing: ModelViewer.getEditingMetadata(), attributes });
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
    await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && window.ViewerOutlines && document.getElementById('viewer-outline-mesh'));
    async function copy() {
      await show(page.locator('#viewer-outline-diagnostics-copy'));
      const before = await immutable(page), start = requests.length;
      assert(!(await page.locator('#viewer-outline-diagnostics-copy').isDisabled()));
      await page.locator('#viewer-outline-diagnostics-copy').click();
      await page.waitForFunction(() => !document.getElementById('viewer-outline-diagnostics-copy').disabled && !document.getElementById('viewer-outline-diagnostics-status').hidden);
      await wait(100);
      assert.strictEqual(await immutable(page), before, 'Copy does not change authoring, metadata or preview vertex buffers');
      assert.deepStrictEqual(requests.slice(start), [], 'Copy does not read, upload or save model files');
      const copied = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
      assert(!JSON.stringify(copied).includes(library), 'Diagnostics omit absolute source paths');
      return copied;
    }
    async function options() { return page.locator('#viewer-outline-mesh option').evaluateAll(nodes => nodes.map(node => ({ value: node.value, text: node.textContent, disabled: node.disabled }))); }
    async function blockedControls() {
      for (const selector of ['#viewer-outline-range', '#viewer-outline-number', '#viewer-outline-absolute-apply', '#viewer-outline-vertex-apply']) assert(await page.locator(selector).isDisabled(), selector + ' must reject an excluded target');
      assert(!(await page.locator('#viewer-outline-mesh').isDisabled()), 'Inventory remains inspectable');
      assert(!(await page.locator('#viewer-outline-diagnostics-copy').isDisabled()), 'Excluded-only inventory remains copyable');
    }

    const mixed = await open(page, sources.slice(0, 2)), catalogue = mixed.outlines;
    assert(mixed.available); assert.equal(catalogue.meshes.length, 1); assert.equal(catalogue.excludedMeshes.length, 1);
    assert.equal(catalogue.meshes[0].name, '사용자_의상.Mesh.001', 'Mesh, GameObject and Material renaming remains editable');
    assert(catalogue.excludedMeshes[0].reasons.some(reason => reason.code === 'unsupported_color_layout'));
    const listed = await options(); assert.equal(listed.length, 3);
    for (const mesh of catalogue.meshes.concat(catalogue.excludedMeshes)) assert(listed.some(option => option.value === mesh.id && option.text.includes(mesh.name) && !option.disabled));
    assert(/2/.test(await page.locator('#viewer-outline-inventory-count').innerText()) && /1/.test(await page.locator('#viewer-outline-inventory-count').innerText()));
    const pristine = await copy(); assert(pristine.editingAvailable); assert.deepStrictEqual(pristine.excludedMeshes, catalogue.excludedMeshes);
    assert.equal(pristine.selection.meshCount, 1, 'All editable affects only eligible source records');
    await show(page.locator('#viewer-outline-absolute')); await page.locator('#viewer-outline-absolute').fill('37'); await page.locator('#viewer-outline-absolute-apply').click();
    const authoring = await page.evaluate(() => ModelViewer.getAuthoringState().outlines);
    assert.deepStrictEqual(authoring, [{ id: catalogue.meshes[0].id, factor: 1, absolute: 37 }], 'Bulk editing cannot reach the unsupported integer-color record');
    await show(page.locator('#viewer-outline-mesh')); await page.locator('#viewer-outline-mesh').selectOption(catalogue.excludedMeshes[0].id);
    await blockedControls();
    const reasonText = await page.locator('#viewer-outline-status').innerText(); assert(/RGBA|UNorm8|color/i.test(reasonText), 'Selected unsupported layout has a specific explanation');
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines), authoring, 'Inspecting a blocked mesh does not erase or change edits');
    const blocked = await copy(); assert.equal(blocked.selection.meshId, catalogue.excludedMeshes[0].id); assert.equal(blocked.selection.meshCount, 0);
    const rejected = await page.evaluate(id => { try { ViewerOutlines.checked([{ id, factor: .5 }], ModelViewer.getEditingMetadata().outlines); return false; } catch (_) { return true; } }, catalogue.excludedMeshes[0].id);
    assert(rejected, 'Excluded inventory IDs never authorize edits');
    await page.screenshot({ path: path.join(evidence, 'mixed-integer-color-exclusion.png') });
    report.cases.push({ name: 'Renamed original remains editable; UInt8 mesh is listed with explanation and cannot be bulk edited', diagnostics: blocked, options: listed, status: reasonText });

    const shader = await open(page, [sources[2]]); assert(shader.available); assert.equal(shader.outlines.meshes.length, 0); assert.equal(shader.outlines.excludedMeshes.length, 1);
    assert(shader.outlines.excludedMeshes[0].reasons.some(reason => reason.code === 'unsupported_material'));
    await page.locator('#viewer-outline-mesh').selectOption(shader.outlines.excludedMeshes[0].id); await blockedControls();
    assert(/AS\/Member|material|shader/i.test(await page.locator('#viewer-outline-status').innerText()));
    const unknownShader = await copy(); assert(unknownShader.editingAvailable); assert.equal(unknownShader.meshes.length, 0); assert.deepStrictEqual(unknownShader.excludedMeshes, shader.outlines.excludedMeshes);
    report.cases.push({ name: 'Unsupported shader with zero editable outlines still exposes mesh, reason and source-bound clipboard diagnostic', diagnostics: unknownShader });

    const orphan = await open(page, [sources[3]]); assert.equal(orphan.available, true, 'Original textures remain editable without a rig'); assert.equal(orphan.bodyEditingAvailable, false, 'Texture editing must not authorize outline or body writes'); assert.equal(typeof orphan.token, 'string'); assert.equal(orphan.outlines.meshes.length, 0); assert.equal(orphan.outlines.excludedMeshes.length, 1);
    assert(orphan.outlines.excludedMeshes[0].reasons.some(reason => reason.code === 'no_verified_renderer_binding'));
    await page.locator('#viewer-outline-mesh').selectOption(orphan.outlines.excludedMeshes[0].id); await blockedControls();
    const orphanStatus = await page.locator('#viewer-outline-status').innerText(); assert(/renderer|bound|binding/i.test(orphanStatus));
    const standalone = await copy(); assert.equal(standalone.editingAvailable, false); assert.deepStrictEqual(standalone.excludedMeshes, orphan.outlines.excludedMeshes);
    assert.deepStrictEqual(standalone.sources, [{ sourceIndex: 0, name: names[3], sha256: hashes[3] }]);
    await page.screenshot({ path: path.join(evidence, 'standalone-mesh-inventory.png') });
    report.cases.push({ name: 'Standalone mesh remains visible and diagnosable when the model has no editable rig', diagnostics: standalone, status: orphanStatus });

    assert(!requests.some(request => /\/api\/viewer\/edit\/(?:export|mod|install)/.test(request.url)), 'Inventory inspection uses no save or install route');

    const floats = await open(page, [sources[4]]), floatMesh = floats.outlines.meshes[0];
    assert(floats.available); assert.equal(floats.outlines.meshes.length, 1); assert.equal(floats.outlines.excludedMeshes.length, 0); assert.equal(floatMesh.format, 'Float32');
    await page.locator('#viewer-outline-mesh').selectOption(floatMesh.id);
    assert(!(await page.locator('#viewer-outline-absolute-apply').isDisabled()), 'Verified Float32 AS/Member masks are editable');
    await show(page.locator('#viewer-outline-absolute')); await page.locator('#viewer-outline-absolute').fill('37'); await page.locator('#viewer-outline-absolute-apply').click();
    await show(page.locator('#viewer-outline-vertex-width')); await page.locator('#viewer-outline-vertex-width').fill('12.3456'); await page.locator('#viewer-outline-vertex-index').fill('0'); await page.locator('#viewer-outline-vertex-apply').click();
    await show(page.locator('#viewer-outline-number')); await page.locator('#viewer-outline-number').fill('37.1'); await page.locator('#viewer-outline-number').dispatchEvent('input');
    const floatEdits = await page.evaluate(() => ModelViewer.getAuthoringState().outlines);
    assert.deepStrictEqual(floatEdits, [{ id: floatMesh.id, factor: .371, absolute: 37, vertices: [{ vertex: 0, value: .123456 }] }]);
    const floatGpu = await page.evaluate(id => {
      ModelViewer.renderProbe(); let found;
      window.__outlineRoot.traverse(mesh => {
        const mapping = mesh.geometry && (mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh);
        if (!mesh.isMesh || mesh.userData.viewerHelper || !mapping || [mapping.mesh.source, mapping.mesh.file, mapping.mesh.id].join(':') !== id) return;
        found = { source: Array.from(mesh.geometry.attributes._sifas_color.array), width: Array.from(mesh.geometry.attributes._sifas_outline_width.array) };
      }); return found;
    }, floatMesh.id);
    const exactFloatWidth = .123456 * .371;
    assert(floatGpu && Math.abs(floatGpu.width[0] - exactFloatWidth) < 1e-7 && floatGpu.width.slice(1).every(value => Math.abs(value - 37 / 255 * .371) < 1e-7));
    assert(Math.abs(floatGpu.width[0] - Math.round(exactFloatWidth * 255) / 255) > 1e-4, 'Float32 preview keeps native precision instead of quantizing to an 8-bit color');
    assert.equal(floatGpu.source[0], 0, 'Live float width updates preserve immutable source colors');
    const exported = page.waitForResponse(response => response.url().endsWith('/api/viewer/edit/export'));
    await (await show(page.locator('#viewer-save'))).click(); assert.equal((await exported).status(), 200);
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.previewPaths.length === 1);
    const saved = await page.evaluate(() => ModelViewer.getState().persistence); assert(!saved.error, saved.error);
    const preservation = JSON.parse(execFileSync(python, ['-c', `import json,struct,sys
from pathlib import Path
from webtools.core.model_edits import _inspect
from sifas_mesh_baker import stream_layout
a,b=(_inspect(Path(p).read_bytes()) for p in sys.argv[1:3]);count=0
for key,obj in a['objects'].items():
 other=b['objects'][key]
 if obj.type.name!='Mesh':
  assert obj.get_raw_data()==other.get_raw_data(),(key,obj.type.name);continue
 x,y=obj.read_typetree(),other.read_typetree();n,channels,strides,starts,_=stream_layout(x);color=channels[3]
 assert color['format']==0 and color['dimension']==4
 expected=bytearray(x['m_VertexData']['m_DataSize'])
 for vertex in range(n):
  offset=starts[color['stream']]+vertex*strides[color['stream']]+color['offset'];expected[offset:offset+4]=struct.pack('<f',(.123456 if vertex==0 else 37/255)*.371)
 assert bytes(expected)==bytes(y['m_VertexData']['m_DataSize'])
 x['m_VertexData']['m_DataSize']=y['m_VertexData']['m_DataSize'];assert x==y
 count+=n
print(json.dumps({'vertices':count,'formatPreserved':'Float32','onlyRedChanged':True,'otherObjectsByteIdentical':True}))`, sources[4], saved.previewPaths[0]], { cwd: product, env: pythonEnv }).toString());
    assert(preservation.vertices > 0);
    await open(page, saved.previewPaths);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().outlines || []), [], 'Reopened saved Float32 widths are new immutable originals');
    const reopenedFloats = await page.evaluate(() => ModelViewer.getEditingMetadata().outlines);
    assert.equal(reopenedFloats.meshes[0].format, 'Float32'); assert.equal(reopenedFloats.excludedMeshes.length, 0);
    report.cases.push({ name: 'Verified Float32 outline supports live absolute and local editing, red-only native-format Save, and reopen', edits: floatEdits, gpu: floatGpu, saved, preservation });

    await open(page, [sources[3]]); await page.locator('#viewer-outline-mesh').selectOption(orphan.outlines.excludedMeshes[0].id);

    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.getElementById('viewer-outline-diagnostics-copy').textContent === '외곽선 진단 복사');
    assert((await options()).find(option => option.value === orphan.outlines.excludedMeshes[0].id).text.includes('편집 불가'));
    const koreanReason = await page.locator('#viewer-outline-status').innerText(); assert(/[가-힣]/.test(koreanReason)); assert.notEqual(koreanReason, orphanStatus);
    await page.locator('#lang-select').selectOption('ja');
    await page.waitForFunction(() => document.getElementById('viewer-outline-diagnostics-copy').textContent === '輪郭線の診断をコピー');
    assert(/[\u3040-\u30ff]/.test(await page.locator('#viewer-outline-status').innerText()));
    report.cases.push({ name: 'Excluded mesh labels and reasons update in Korean and Japanese' });
    assert.deepStrictEqual(sources.map(sha), hashes, 'Every original bundle remains byte-identical');
    assert.deepStrictEqual(errors, []);
    assert.equal(requests.filter(request => /\/api\/viewer\/edit\/export$/.test(request.url)).length, 1, 'Only the explicit Float32 Save exports a model');
    assert(!requests.some(request => /\/api\/viewer\/edit\/(?:mod|install)/.test(request.url)), 'No mod packaging or install is requested');
    report.sourceHashesAfter = sources.map(sha); report.pageErrors = errors; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally {
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    if (browser) await browser.close(); if (server) { server.child.kill('SIGTERM'); server.stream.end(); }
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error || null }));
  }
}
run();
