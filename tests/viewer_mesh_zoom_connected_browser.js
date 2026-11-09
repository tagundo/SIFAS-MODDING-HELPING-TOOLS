/* Real Unity/HTTP/WebGL: zoom/pan painting, native pinch and connected islands. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-zoom-connected-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-components-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'components.unity'), stripes = path.join(evidence, 'original-detail.png');
execFileSync(python, ['-c', `
import struct,sys
from pathlib import Path
import UnityPy
from PIL import Image
env=UnityPy.load(Path('tests/fixtures/viewer_persistence.unity').read_bytes())
obj=next(o for o in env.objects if o.type.name=='Mesh'); tree=obj.read_typetree()
tree['m_IndexBuffer']=struct.pack('<9H',0,1,2,2,1,3,3,4,5)
tree['m_SubMeshes'][0]['indexCount']=9
obj.save_typetree(tree);Path(sys.argv[1]).write_bytes(env.file.save(packer='original'))
image=Image.new('RGB',(1024,1024)); row=bytes(sum(([255,0,0] if i%2==0 else [0,0,255] for i in range(1024)),[]))
image.frombytes(row*1024);image.save(sys.argv[2])
`, source, stripes], { cwd: product });
const original = fs.readFileSync(source), sha = value => crypto.createHash('sha256').update(value).digest('hex');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function serverStart() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, log }; } catch (_) {} await sleep(100); }
  child.kill(); throw new Error('Product server did not become ready');
}
async function state(page) { return page.evaluate(() => ModelViewer.getState().meshTools); }
async function textureView(page, tool) { return (await state(page)).textureViews.find(v => v.panel === 'viewer-mesh-' + tool); }
async function clear(page, tool) { await page.locator('#viewer-mesh-' + tool).getByRole('button', { name: 'Clear selection', exact: true }).click(); }
async function undo(page, tool) { await page.locator('#viewer-mesh-' + tool + '-undo').click(); }
async function uvPoint(page, tool, uv) { const box = await page.locator('#viewer-mesh-' + tool + '-canvas').boundingBox(), view = await textureView(page, tool); return { x: box.x + (view.x + uv[0] * view.zoom) * box.width, y: box.y + (view.y + (1 - uv[1]) * view.zoom) * box.height, box }; }
async function scalar(page, id, value) { await page.locator(id).evaluate((e, value) => { e.value = value; e.dispatchEvent(new Event('input', { bubbles: true })); }, String(value)); }
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await serverStart(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, hasTouch: true }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    await page.locator('#viewer-mesh-deleter').evaluate(e => { e.open = true; });
    const listingResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect')); await page.locator('#viewer-mesh-deleter-load').click(); const listing = await (await listingResponse).json();
    const identity = listing.meshes.find(m => m.available).mesh, value = JSON.stringify(identity);
    const dataResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/data')); await page.locator('#viewer-mesh-deleter-select').selectOption(value); const data = await (await dataResponse).json();
    await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
    assert.deepStrictEqual(data.triangles, [[0, 1, 2], [2, 1, 3], [3, 4, 5]], 'fixture has a shared-edge quad and a vertex-only touching island');
    const faceUV = data.triangles[0].reduce((p, vertex) => [p[0] + data.uv[vertex][0] / 3, p[1] + data.uv[vertex][1] / 3], [0, 0]);
    const canvas = page.locator('#viewer-mesh-deleter-canvas'); await canvas.scrollIntoViewIfNeeded(); await page.locator('#viewer-mesh-deleter-radius').fill('2');
    let point = await uvPoint(page, 'deleter', faceUV); await page.mouse.move(point.x, point.y); const history = (await state(page)).history;
    await page.mouse.wheel(0, -700); await page.waitForTimeout(100); const zoomed = await textureView(page, 'deleter'); assert(zoomed.zoom > 4 && zoomed.zoom < 4.1);
    point = await uvPoint(page, 'deleter', faceUV); await page.mouse.move(point.x, point.y); await page.mouse.click(point.x, point.y);
    assert.deepStrictEqual((await state(page)).selectedFaces, [0], 'zoomed brush selects the intended original face');
    const cursor = await page.locator('#viewer-mesh-uv-cursor').boundingBox(); assert(Math.abs(cursor.width - 4) < .01, 'zoom leaves brush radius in CSS pixels');
    await page.locator('#viewer-mesh-deleter-mode').selectOption('erase'); await canvas.scrollIntoViewIfNeeded(); point = await uvPoint(page, 'deleter', faceUV); await page.mouse.click(point.x, point.y);
    assert.deepStrictEqual((await state(page)).selectedFaces, [], 'zoomed eraser hits the same face'); await undo(page, 'deleter'); assert.deepStrictEqual((await state(page)).selectedFaces, [0]);
    const viewAfterUndo = await textureView(page, 'deleter'); assert.equal(viewAfterUndo.zoom, zoomed.zoom, 'Undo edits does not reset the inspection zoom');
    await page.locator('#viewer-mesh-deleter-mode').selectOption('paint'); await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox(), beforePan = await textureView(page, 'deleter');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down({ button: 'right' }); await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 - 15, { steps: 3 }); await page.mouse.up({ button: 'right' });
    const afterPan = await textureView(page, 'deleter'); assert.notEqual(afterPan.x, beforePan.x); assert.notEqual(afterPan.y, beforePan.y); assert.deepStrictEqual((await state(page)).selectedFaces, [0], 'right-drag pans without painting');
    report.cases.push({ name: 'wheel anchored zoom, precise paint/erase, constant brush, undo and right-pan', zoomed, beforePan, afterPan, initialHistory: history });
    await clear(page, 'deleter'); await page.locator('#viewer-mesh-deleter-fit-texture').click(); await page.locator('#viewer-mesh-deleter-texture-mode').selectOption('connected'); await canvas.scrollIntoViewIfNeeded();
    point = await uvPoint(page, 'deleter', faceUV); await page.mouse.click(point.x, point.y);
    assert.deepStrictEqual((await state(page)).selectedFaces.slice().sort(), [0, 1], 'UV click expands across shared edges, excluding another face island');
    await undo(page, 'deleter'); assert.deepStrictEqual((await state(page)).selectedFaces, []);
    await page.locator('#viewer-mesh-deleter-scene-mode').selectOption('connected'); await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
    const projected = await page.evaluate(({ mesh, face }) => face.map(vertex => ModelViewer.projectMeshVertex(mesh, vertex)), { mesh: identity, face: data.triangles[0] });
    const hit = { x: projected.reduce((n, p) => n + p.x / 3, 0), y: projected.reduce((n, p) => n + p.y / 3, 0) };
    await page.mouse.click(hit.x, hit.y); assert.deepStrictEqual((await state(page)).selectedFaces.slice().sort(), [0, 1], '3D face click selects the exact source component');
    await undo(page, 'deleter'); assert.deepStrictEqual((await state(page)).selectedFaces, []);
    await page.locator('#viewer-mesh-deleter-texture-mode').selectOption('paint'); await canvas.scrollIntoViewIfNeeded(); point = await uvPoint(page, 'deleter', faceUV); await page.mouse.click(point.x, point.y);
    assert.deepStrictEqual((await state(page)).selectedFaces, [0]); await page.locator('#viewer-mesh-deleter-connected').click(); assert.deepStrictEqual((await state(page)).selectedFaces.slice().sort(), [0, 1]);
    await page.locator('#viewer-mesh-deleter-delete').click(); assert.equal((await state(page)).runtime.bindings[0].triangles, 1, 'connected deletion retains the other island');
    const exportResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/export')); await page.locator('#viewer-mesh-deleter-save').click(); const output = await (await exportResponse).json();
    const decoded = JSON.parse(execFileSync(python, ['-c', `import json,sys;from pathlib import Path;from webtools.core import viewer_mesh_tools as m;_,records=m._mesh_records(Path(sys.argv[1]).read_bytes(),0);r=records[0];print(json.dumps(m._triangles(r[2],6)[0]))`, output.preview_paths[0]], { cwd: product, encoding: 'utf8' }));
    assert.deepStrictEqual(decoded, [[3, 4, 5]], 'serialized copy keeps exactly the unselected source island');
    await undo(page, 'deleter'); assert.equal((await state(page)).runtime.bindings[0].triangles, 3, 'Undo after save restores real live topology');
    report.cases.push({ name: 'UV and 3D connected seed selection, expansion button, save and Undo', selectedFaces: [0, 1], savedFaces: decoded, hit });
    await clear(page, 'deleter'); await page.locator('#viewer-mesh-deleter-scene-mode').selectOption('orbit'); await page.locator('#viewer-mesh-deleter-fit-texture').click(); await canvas.scrollIntoViewIfNeeded();
    const pinchHistory = (await state(page)).history, pinchBox = await canvas.boundingBox(), cx = pinchBox.x + pinchBox.width / 2, cy = pinchBox.y + pinchBox.height / 2;
    const cdp = await context.newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: cx - 20, y: cy, id: 1 }, { x: cx + 20, y: cy, id: 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: cx - 60, y: cy, id: 1 }, { x: cx + 60, y: cy, id: 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await page.waitForTimeout(100);
    const pinched = await textureView(page, 'deleter'); assert(pinched.zoom > 2.5 && pinched.zoom < 3.5, 'native two-finger gesture zooms texture'); assert.equal((await state(page)).history, pinchHistory, 'pinch creates no edit/Undo entries'); assert.deepStrictEqual((await state(page)).selectedFaces, [], 'pinch never paints its first touch');
    report.cases.push({ name: 'native touch pinch without accidental paint or history', view: pinched });
    await page.locator('#viewer-mesh-deleter input[type=file]').setInputFiles(stripes); await page.waitForTimeout(150);
    await page.locator('#viewer-mesh-deleter').getByLabel('Show UV lines', { exact: true }).uncheck(); await page.locator('#viewer-mesh-deleter-fit-texture').click(); await scalar(page, '#viewer-mesh-deleter-zoom', 16);
    const detail = await canvas.evaluate(canvas => { const ctx = canvas.getContext('2d'), results = []; for (let sourceX = 480; sourceX < 544; sourceX++) { const x = Math.floor(((sourceX + .5) / 1024 * 16 - 7.5) * 640), p = Array.from(ctx.getImageData(x, 320, 1, 1).data); results.push({ sourceX, pixel: p }); } return results; });
    assert(detail.every(({ sourceX, pixel }) => sourceX % 2 === 0 ? pixel[0] > 200 && pixel[2] < 55 : pixel[2] > 200 && pixel[0] < 55), 'zoom resamples high-resolution original pixels, not a reduced preview');
    await page.screenshot({ path: path.join(evidence, 'texture-detail-16x.png') }); report.cases.push({ name: 'original 1024px texture preserves its 1px stripe detail at16x', sampledStripeCentres: detail.length });
    await page.locator('#viewer-mesh-modify').evaluate(e => { e.open = true; }); await page.locator('#viewer-mesh-modify-select').selectOption(value);
    await scalar(page, '#viewer-mesh-modify-zoom', 4); assert.equal((await textureView(page, 'modify')).zoom, 4, 'modify tool has its own zoom');
    await page.locator('#viewer-mesh-modify-vertex').fill('0'); await page.locator('#viewer-mesh-modify-select-vertex').click(); assert.deepStrictEqual((await state(page)).selectedVertices, [0]);
    await page.locator('#viewer-mesh-modify-connected').click(); assert.deepStrictEqual((await state(page)).selectedVertices.slice().sort(), [0, 1, 2, 3], 'modify expands vertex seed to connected face vertices'); await undo(page, 'modify'); assert.deepStrictEqual((await state(page)).selectedVertices, [0]); assert.equal((await textureView(page, 'modify')).zoom, 4);
    await clear(page, 'modify'); await page.locator('#viewer-mesh-modify-scene-mode').selectOption('connected'); await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
    const modifyHit = await page.evaluate(({ mesh, face }) => { const points = face.map(v => ModelViewer.projectMeshVertex(mesh, v)); return { x: points.reduce((n, p) => n + p.x / 3, 0), y: points.reduce((n, p) => n + p.y / 3, 0) }; }, { mesh: identity, face: data.triangles[0] });
    await page.mouse.click(modifyHit.x, modifyHit.y); assert.deepStrictEqual((await state(page)).selectedVertices.slice().sort(), [0, 1, 2, 3]); assert.equal((await state(page)).edits.meshes.length, 0, 'selection and texture viewing do not author geometry');
    report.cases.push({ name: 'modify independent zoom, connected vertex seed, 3D component and Undo', selectedVertices: [0, 1, 2, 3] });
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'original source is immutable'); assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); }
}
main().catch(() => { process.exitCode = 1; });
