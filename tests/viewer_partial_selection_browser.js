/* Source-bound hierarchy/UV/3D selection -> actual graft -> saved mesh -> Undo. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os'), net = require('net'), crypto = require('crypto');
const { spawn, execFileSync } = require('child_process'), { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-part-selection-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-part-selection-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(models, { recursive: true });
const wearer = path.join(models, 'wearer.unity'), donor = path.join(models, 'donor.unity');
const realRoot = process.env.VIEWER_REAL_COSTUME_ROOT, real = !!realRoot;
if (real) {
  const original = suit => path.join(realRoot, fs.readdirSync(realRoot).find(name => name.startsWith('gl-' + suit + '-')), 'ch0101_suit' + suit + '_primary.unity');
  fs.copyFileSync(original('101011001'), wearer); fs.copyFileSync(original('401013001'), donor);
} else execFileSync(python, ['-c', `import sys
from pathlib import Path
import numpy as np
import UnityPy
import costume_part_transplant as part
from test_viewer_transplants import costume_fixture
raw=costume_fixture();Path(sys.argv[1]).write_bytes(raw)
env=UnityPy.load(raw);mesh=next(o for o in env.objects if o.type.name=='Mesh');tree=mesh.read_typetree()
count,channels,strides,starts,_=part.stream_layout(tree);data=np.frombuffer(bytes(tree['m_VertexData']['m_DataSize']),np.uint8).copy()
uv=np.zeros((count,2))
for face,triangle in enumerate(np.concatenate(part.submesh_triangles(tree))):
    x,y=face%5,face//5
    for vertex,offset in zip(triangle,((.15,.15),(.85,.15),(.45,.85))):uv[vertex]=((x+offset[0])/5,(y+offset[1])/4)
part.write_attr(data,uv,part.ATTR_UV0,channels,strides,starts,count);tree['m_VertexData']['m_DataSize']=data.tobytes();mesh.save_typetree(tree)
Path(sys.argv[2]).write_bytes(env.file.save(packer='original'))`, wearer, donor], { cwd: product, env: { ...process.env, PYTHONPATH: product + path.delimiter + __dirname } });
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), originals = [hash(wearer), hash(donor)];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), report = { status: 'RUNNING', evidence, real, cases: [] };
let server, browser, context;
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: path.dirname(product), env: { ...process.env, PYTHONPATH: product + path.delimiter + path.dirname(product), SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await sleep(100); }
  child.kill(); throw Error('Server did not start');
}
function meshStats(file) {
  return JSON.parse(execFileSync(python, ['-c', `import json,sys,hashlib;import UnityPy;import costume_part_transplant as p;e=UnityPy.load(sys.argv[1]);o,i=p._index(e);s=p._body_smr(o).read_typetree();m=i[s['m_Mesh']['m_PathID']].read_typetree();print(json.dumps(dict(triangles=sum(len(t) for t in p.submesh_triangles(m)),bones=len(s['m_Bones']),textures=sorted(hashlib.sha256(x.get_raw_data()).hexdigest() for x in o if x.type.name=='Texture2D'))))`, file], { cwd: product, encoding: 'utf8' }));
}
async function partState(page) { return page.evaluate(() => ModelViewer.getState().transplants.donors.find(entry => entry.operation === 'part')); }
async function button(page, id) { await page.locator('#viewer-part-transplant-' + id).click(); }
async function checkbox(page, name, checked) { await page.locator('#viewer-part-transplant-bones label').filter({ has: page.locator('input[value="' + name + '"]') }).locator('input').setChecked(checked); }
async function setMode(page, value) { await page.locator('#viewer-part-transplant-selection-mode').selectOption(value); }
async function scalar(page, id, value) { await page.locator('#viewer-part-transplant-' + id).evaluate((e, value) => { e.value = String(value); e.dispatchEvent(new Event('input', { bubbles: true })); }, value); }
async function capture(page) {
  await page.evaluate(() => {
    window.__partCaptures = []; const Renderer = THREE.WebGLRenderer;
    THREE.WebGLRenderer = new Proxy(Renderer, { construct(target, args) { const renderer = Reflect.construct(target, args), render = renderer.render; renderer.render = function (scene, camera) { if (renderer.domElement.closest('#viewer-part-transplant') && !window.__partCaptures.some(c => c.canvas === renderer.domElement)) window.__partCaptures.push({ canvas: renderer.domElement, renderer, scene, camera }); return render.apply(renderer, arguments); }; return renderer; } });
  });
}
async function visibleFace(page, excluded) {
  return page.evaluate(excluded => {
    const c = window.__partCaptures.find(c => c.canvas.isConnected), state = ModelViewer.getState().transplants.donors.find(e => e.operation === 'part');
    if (!c) return null; const meshes = []; c.scene.traverse(o => { if (o.isMesh && !o.userData.viewerHelper) meshes.push(o); });
    const rect = c.canvas.getBoundingClientRect(), skip = new Set(excluded || []), cache = {};
    const map = m => m.geometry.userData.viewerMesh || m.userData.viewerMesh || {}, body = meshes.filter(m => { const d = map(m); return d.mesh && d.mesh.source === 0 && String(d.renderer) === state.donorRenderer && String(d.mesh.id) === state.donorMesh; });
    for (const mesh of body) { const index = mesh.geometry.index, meta = map(mesh); if (!index) continue;
      for (let offset = 0; offset < index.count; offset += 3) { const source = meta.firstFace + offset / 3; if (skip.has(source)) continue;
        const centre = [0, 1, 2].reduce((p, slot) => p.add(ViewerMeshRuntime.vertexWorld(mesh, index.getX(offset + slot))), new THREE.Vector3()).divideScalar(3), p = centre.clone().project(c.camera);
        if (p.z < -1 || p.z > 1 || Math.abs(p.x) > .85 || Math.abs(p.y) > .85) continue;
        const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(p.x, p.y), c.camera);
        const hits = meshes.map(m => ViewerMeshRuntime.raycastMesh(ray.ray, m, { vertices: cache[m.uuid] || (cache[m.uuid] = []) })).filter(Boolean).sort((a, b) => a.distance - b.distance), hit = hits[0];
        if (hit && hit.object === mesh && hit.faceIndex === offset / 3) return { source, x: rect.left + (p.x + 1) * rect.width / 2, y: rect.top + (1 - p.y) * rect.height / 2, submesh: meta.submesh };
      }
    } return null;
  }, excluded || []);
}
async function donorPixel(page, point) {
  return page.evaluate(point => { const c = window.__partCaptures.find(c => c.canvas.isConnected), rect = c.canvas.getBoundingClientRect(); c.renderer.render(c.scene, c.camera); const gl = c.renderer.getContext(), pixel = new Uint8Array(4), x = Math.floor((point.x - rect.left) / rect.width * gl.drawingBufferWidth), y = gl.drawingBufferHeight - 1 - Math.floor((point.y - rect.top) / rect.height * gl.drawingBufferHeight); gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel); return { rgba: Array.from(pixel), glError: gl.getError() }; }, point);
}
async function uvSeed(page) {
  return page.evaluate(() => {
    const c = window.__partCaptures.find(c => c.canvas.isConnected), select = document.getElementById('viewer-part-transplant-texture-material'), mesh = c.scene.getObjectByProperty('uuid', select.value);
    if (!mesh || !mesh.geometry.attributes.uv) return null; const index = mesh.geometry.index, map = mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh, texture = mesh.material.map;
    for (let offset = 0; offset < index.count; offset += 3) {
      const points = [0, 1, 2].map(slot => { const uv = new THREE.Vector2().fromBufferAttribute(mesh.geometry.attributes.uv, index.getX(offset + slot)); if (texture) { texture.updateMatrix(); texture.transformUv(uv); } return [uv.x, uv.y]; });
      const area = Math.abs((points[1][0] - points[0][0]) * (points[2][1] - points[0][1]) - (points[2][0] - points[0][0]) * (points[1][1] - points[0][1]));
      const u = points.reduce((n, p) => n + p[0] / 3, 0), v = points.reduce((n, p) => n + p[1] / 3, 0);
      if (area > 1e-6 && u > .03 && u < .97 && v > .03 && v < .97) { const canvas = document.getElementById('viewer-part-transplant-texture'), pixelBefore = Array.from(canvas.getContext('2d').getImageData(Math.floor(u * canvas.width), Math.floor(v * canvas.height), 1, 1).data); if (texture && texture.image && pixelBefore[3] === 0) continue; const rect = canvas.getBoundingClientRect(); return { source: map.firstFace + offset / 3, u, v, x: rect.left + u * rect.width, y: rect.top + v * rect.height, material: select.value, pixelBefore, textureSize: texture && texture.image ? [texture.image.width, texture.image.height] : null }; }
    } return null;
  });
}
(async () => {
  try {
    server = await start(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, hasTouch: true }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = [], requests = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.on('request', r => { if (r.url().endsWith('/api/viewer/transplant/run')) requests.push(JSON.parse(r.postData())); }); page.setDefaultTimeout(60000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function'); await capture(page);
    await page.evaluate(wearer => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([wearer]); }, wearer);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    const panel = page.locator('#viewer-part-transplant'); await panel.evaluate(e => { e.open = true; });
    await panel.getByRole('button', { name: 'Choose donor costume', exact: true }).click(); await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
    await page.waitForFunction(() => { const p = ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'); return p.availableBones.length > 10 && p.donorSelectionFingerprint && document.querySelector('#viewer-part-transplant .viewer-transplant-stage canvas'); });
    await page.waitForFunction(() => !document.getElementById('viewer-part-transplant-part').disabled);
    await page.locator('#lang-select').selectOption('ko'); await page.waitForFunction(() => document.getElementById('viewer-part-transplant-selection-status').textContent.includes('선택 본'));
    await page.locator('#lang-select').selectOption('en'); await page.waitForFunction(() => document.getElementById('viewer-part-transplant-selection-status').textContent.includes('Selected bones'));
    report.cases.push({ name: 'language switching refreshes dynamic part counts without changing selection' });
    let state = await partState(page); assert.equal(state.selectedBones.length, 0); assert.equal(state.selectedTriangles, 0); assert(await panel.locator('.viewer-primary').isDisabled(), 'loading never silently selects the entire Move subtree');
    assert(await page.locator('#viewer-part-transplant-include-children').isChecked());
    const parent = real ? 'TailA_Root_Dyna' : 'Move'; await checkbox(page, parent, true); state = await partState(page);
    const subtree = state.availableBones.find(row => row.value === parent).bones; assert(subtree.length > 2); assert(subtree.every(name => state.selectedBones.includes(name))); assert(state.selectedTriangles > 0, 'a zero-weight root includes the weighted descendants');
    await button(page, 'selection-undo'); assert.equal((await partState(page)).selectedBones.length, 0);
    const roots = real ? ['TailA2_Dyna', 'RightArm'] : ['LeftArm', 'RightLeg']; for (const name of roots) await checkbox(page, name, true);
    state = await partState(page); assert(roots.every(root => state.partRoots.includes(root))); assert(state.selectedBones.length > roots.length); assert(state.highlightedFaces.length > 0);
    report.cases.push({ name: 'actual hierarchy, zero-weight parent and multi-root descendants', roots, selectedBones: state.selectedBones, highlightedFaces: state.highlightedFaces });
    const sourceStats = meshStats(wearer), beforeBones = await page.evaluate(() => ({ state: ModelViewer.getState(), authoring: ModelViewer.getAuthoringState() })), boneFaces = state.highlightedFaces.slice();
    await panel.getByRole('button', { name: 'Transplant', exact: true }).click();
    await page.waitForFunction(id => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().modelId !== id && !ModelViewer.getState().transplants.busy, beforeBones.state.modelId);
    let output = await page.evaluate(() => ModelViewer.getState().loadedPaths[0]), saved = meshStats(output); assert.equal(saved.triangles, sourceStats.triangles + boneFaces.length);
    assert.equal(requests.at(-1).partSelectionMode, 'bones'); assert.deepStrictEqual(requests.at(-1).partRoots.slice().sort(), roots.slice().sort()); assert.equal(requests.at(-1).includeDescendants, true);
    assert.equal(requests.at(-1).donorSha256, originals[1]); assert.equal(requests.at(-1).donorSelectionFingerprint, state.donorSelectionFingerprint);
    await panel.getByRole('button', { name: 'Undo transplant', exact: true }).click(); await page.waitForFunction(wearer => ModelViewer.getState().loadedPaths[0] === wearer && !ModelViewer.getState().transplants.busy, wearer);
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), beforeBones.authoring);
    report.cases.push({ name: 'one multi-root source-bound request, actual serialized union and transplant Undo', trianglesBefore: sourceStats.triangles, selectedFaces: boneFaces.length, trianglesAfter: saved.triangles });
    await button(page, 'selection-clear'); await setMode(page, 'triangles'); await scalar(page, 'brush-radius', 2);
    await page.locator('#viewer-part-transplant-texture').scrollIntoViewIfNeeded(); const uv = await uvSeed(page); assert(uv, 'real donor UV triangle is available');
    await page.mouse.move(uv.x, uv.y); const cursor = await page.locator('#viewer-part-transplant-brush-cursor').boundingBox(); assert(cursor && Math.abs(cursor.width - 4) < .1);
    await page.mouse.click(uv.x, uv.y); state = await partState(page); assert(state.selectedFaces.includes(uv.source)); assert.deepStrictEqual(state.highlightedFaces, state.selectedFaces); const textureFaces = state.selectedFaces.slice();
    const selectedPixel = await page.locator('#viewer-part-transplant-texture').evaluate((canvas, uv) => Array.from(canvas.getContext('2d').getImageData(Math.floor(uv.u * canvas.width), Math.floor(uv.v * canvas.height), 1, 1).data), uv); assert.notDeepStrictEqual(selectedPixel, uv.pixelBefore, 'the selected source face is visibly overlaid on its actual texture'); if (real) assert(uv.textureSize && uv.textureSize[0] > 1, 'actual game texture was decoded and shown');
    await page.locator('#viewer-part-transplant .viewer-transplant-stage').scrollIntoViewIfNeeded(); const face = await visibleFace(page, textureFaces); assert(face, 'another visible source face is available');
    const pixelBefore3D = await donorPixel(page, face), strokeStarted = Date.now(); await page.mouse.click(face.x, face.y); const strokeDuration = Date.now() - strokeStarted; state = await partState(page); assert(state.selectedFaces.includes(face.source)); assert(textureFaces.every(id => state.selectedFaces.includes(id)), '3D painting adds to the same UV selection');
    const pixelAfter3D = await donorPixel(page, face); assert.equal(pixelBefore3D.glError, 0); assert.equal(pixelAfter3D.glError, 0); assert.notDeepStrictEqual(pixelAfter3D.rgba, pixelBefore3D.rgba, 'the exact newly selected face is visibly highlighted in the donor WebGL renderer'); await page.screenshot({ path: path.join(evidence, 'model-selected-source-faces.png') });
    const combinedFaces = state.selectedFaces.slice(); await button(page, 'selection-undo'); assert.deepStrictEqual((await partState(page)).selectedFaces, textureFaces); await button(page, 'selection-redo'); assert.deepStrictEqual((await partState(page)).selectedFaces, combinedFaces);
    await page.locator('#viewer-part-transplant-scene-action').selectOption('connected'); await page.locator('#viewer-part-transplant .viewer-transplant-stage').scrollIntoViewIfNeeded(); const connectedSeed = await visibleFace(page, combinedFaces); assert(connectedSeed); await page.mouse.click(connectedSeed.x, connectedSeed.y); assert((await partState(page)).selectedFaces.length > combinedFaces.length); await button(page, 'selection-undo'); assert.deepStrictEqual((await partState(page)).selectedFaces, combinedFaces);
    await page.locator('#viewer-part-transplant-scene-action').selectOption('paint');
    await scalar(page, 'texture-zoom', 4); const zoomed = await partState(page); assert.equal(zoomed.textureView.zoom, 4); assert.deepStrictEqual(zoomed.selectedFaces, combinedFaces); await button(page, 'texture-fit'); assert.equal((await partState(page)).textureView.zoom, 1);
    await page.screenshot({ path: path.join(evidence, 'selected-source-faces.png') });
    report.cases.push({ name: 'real UV and 3D pointer strokes, brush cursor, multi-patch union, connected mode and selection Undo/Redo', uv, selectedPixel, face, pixelBefore3D, pixelAfter3D, textureFaces, combinedFaces, first3dStrokeMs: strokeDuration });
    await page.locator('#viewer-part-transplant .viewer-transplant-stage').scrollIntoViewIfNeeded(); const sceneBox = await page.locator('#viewer-part-transplant .viewer-transplant-stage canvas').boundingBox();
    const cameraBefore = await page.evaluate(() => window.__partCaptures.find(c => c.canvas.isConnected).camera.position.toArray());
    await page.mouse.move(sceneBox.x + sceneBox.width * .5, sceneBox.y + sceneBox.height * .5); await page.mouse.down({ button: 'right' }); await page.mouse.move(sceneBox.x + sceneBox.width * .6, sceneBox.y + sceneBox.height * .5, { steps: 4 }); await page.mouse.up({ button: 'right' });
    const cameraRotated = await page.evaluate(() => window.__partCaptures.find(c => c.canvas.isConnected).camera.position.toArray()); assert.notDeepStrictEqual(cameraRotated, cameraBefore); assert.deepStrictEqual((await partState(page)).selectedFaces, combinedFaces);
    await page.mouse.wheel(0, -120); const cameraZoomed = await page.evaluate(() => window.__partCaptures.find(c => c.canvas.isConnected).camera.position.toArray()); assert.notDeepStrictEqual(cameraZoomed, cameraRotated); assert.deepStrictEqual((await partState(page)).selectedFaces, combinedFaces);
    report.cases.push({ name: 'right-drag orbit and wheel zoom while painting preserve source selection', cameraBefore, cameraRotated, cameraZoomed });
    await page.locator('#viewer-part-transplant-texture').scrollIntoViewIfNeeded(); const box = await page.locator('#viewer-part-transplant-texture').boundingBox(), cx = box.x + box.width / 2, cy = box.y + box.height / 2, beforePinch = await partState(page), cdp = await context.newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: cx - 20, y: cy, id: 1 }, { x: cx + 20, y: cy, id: 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: cx - 50, y: cy, id: 1 }, { x: cx + 50, y: cy, id: 2 }] }); await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    state = await partState(page); assert(state.textureView.zoom > 2); assert.deepStrictEqual(state.selectedFaces, beforePinch.selectedFaces); assert.equal(state.selectionUndoCount, beforePinch.selectionUndoCount); await button(page, 'texture-fit');
    report.cases.push({ name: 'native touch pinch zoom has no accidental paint or selection-history entries', zoom: state.textureView.zoom });
    const beforeMask = await page.evaluate(() => ({ id: ModelViewer.getState().modelId, state: ModelViewer.getAuthoringState() }));
    await panel.getByRole('button', { name: 'Transplant', exact: true }).click(); await page.waitForFunction(id => ModelViewer.getState().modelId !== id && ModelViewer.getState().loaded && !ModelViewer.getState().loading && !ModelViewer.getState().transplants.busy, beforeMask.id);
    output = await page.evaluate(() => ModelViewer.getState().loadedPaths[0]); saved = meshStats(output);
    assert.equal(requests.at(-1).partSelectionMode, 'triangles'); assert.deepStrictEqual(requests.at(-1).triangleIndices, combinedFaces); assert.equal(saved.triangles, sourceStats.triangles + combinedFaces.length);
    await panel.getByRole('button', { name: 'Undo transplant', exact: true }).click(); await page.waitForFunction(wearer => ModelViewer.getState().loadedPaths[0] === wearer && !ModelViewer.getState().transplants.busy, wearer); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), beforeMask.state);
    await panel.getByRole('button', { name: 'Redo transplant', exact: true }).click(); await page.waitForFunction(output => ModelViewer.getState().loadedPaths[0] === output && !ModelViewer.getState().transplants.busy, output); assert.equal(meshStats(output).triangles, saved.triangles);
    assert.deepStrictEqual([hash(wearer), hash(donor)], originals); assert.deepStrictEqual(errors, []);
    const probe = await page.evaluate(() => ModelViewer.renderProbe(33)); assert(probe.ready && probe.glError === 0 && probe.chromaticSamples > 2);
    report.cases.push({ name: 'exact face mask emitted once, actual saved/reopened mesh, transplant Undo/Redo and immutable originals', selectedFaces: combinedFaces, trianglesBefore: sourceStats.triangles, trianglesAfter: saved.triangles, probe }); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
})().catch(() => { process.exitCode = 1; });
