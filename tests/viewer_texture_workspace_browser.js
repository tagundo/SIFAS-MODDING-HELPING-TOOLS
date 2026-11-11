/* Canvas-first texture workspace: actual HTTP/Unity/WebGL, pointer editing and
 * persistent accessible layout controls. No preparation/export success mocks. */
'use strict';
const assert = require('assert/strict'), fs = require('fs'), path = require('path'), os = require('os'), net = require('net'), crypto = require('crypto');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-workspace-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-workspace-library-'));
const source = path.join(library, 'extracted/3d_model/workspace-uv-islands.unity');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(path.dirname(source), { recursive: true });
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function py(code, args = []) { return JSON.parse(execFileSync(python, ['-B', '-c', code, ...args], { cwd: product, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo }, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 })); }
const fixture = py(`import json,struct,sys,UnityPy
from pathlib import Path
from PIL import Image
env=UnityPy.load(Path('tests/fixtures/viewer_persistence.unity').read_bytes())
im=Image.new('RGBA',(16,16),(70,120,190,255));im.putpixel((15,14),(30,160,70,128));im.putpixel((15,15),(9,8,7,0))
uv=[(.1,.1),(.4,.1),(.1,.4),(.4,.4),(.65,.65),(.9,.65),(.65,.9)]
for obj in env.objects:
 if obj.type.name=='Texture2D':
  texture=obj.read();texture.image=im;texture.m_Name='ch0001_co0001_body';texture.save()
 elif obj.type.name=='Mesh':
  tree=obj.read_typetree();data=tree['m_VertexData'];old=data['m_DataSize'];stride=len(old)//data['m_VertexCount'];assert stride==56
  buffer=bytearray(old+old[-stride:]);struct.pack_into('<3f',buffer,6*stride,.15,1.0,0)
  assert data['m_Channels'][4]['offset']==24 and data['m_Channels'][4]['format']==0
  for i,p in enumerate(uv):struct.pack_into('<2f',buffer,i*stride+24,*p)
  data['m_DataSize']=bytes(buffer);data['m_VertexCount']=7;tree['m_IndexBuffer']=struct.pack('<9H',0,1,2,1,3,2,4,5,6)
  tree['m_SubMeshes'][0]['indexCount']=9;tree['m_SubMeshes'][0]['vertexCount']=7;obj.save_typetree(tree)
Path(sys.argv[1]).write_bytes(env.file.save(packer='original'))
print(json.dumps({'width':16,'height':16,'rgba':list(im.tobytes()),'uv':uv,'triangles':[[0,1,2],[1,3,2],[4,5,6]],'islands':[[0,1],[2]]}))`, [source]);
const fixtureHash = hash(fs.readFileSync(source));
const files = ['viewer-texture-tools.js', 'viewer-texture-tools.css', 'texture-paint-engine.js', 'texture-uv-selection.js'];
const sourceHashes = () => Object.fromEntries(files.filter(file => fs.existsSync(path.join(product, 'webtools/web/static', file))).map(file => [file, hash(fs.readFileSync(path.join(product, 'webtools/web/static', file)))]));
const report = { status: 'RUNNING', scope: 'Actual generated Unity model/real Python HTTP/Chromium WebGL; UI geometry and exact selected-pixel export checks; no native-device claim', evidence, sourceBefore: sourceHashes(), fixture: { sha256: fixtureHash, width: 16, height: 16, islands: fixture.islands }, cases: [], profiles: [], errors: [] };
let server, browser, currentPage;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function state(page) { return page.evaluate(() => ModelViewer.getTextureTools().getState()); }
async function idle(page) { await page.waitForFunction(() => { const t = ModelViewer.getTextureTools(), s = t && t.getState(); return s && !s.loading && (!s.pending || s.selection && s.selection.floatingSelection); }); await frames(page); }
async function reveal(page, selector) { const target = page.locator(selector); await target.evaluate(e => { for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); return target; }
async function field(page, selector, value) { const target = await reveal(page, selector); await target.evaluate((e, value) => { e.value = String(value); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); }, value); await idle(page); }
async function snapshot(page) {
  return page.evaluate(() => {
    const box = selector => { const e = document.querySelector(selector); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    const canvas = box('#viewer-texture-canvas-host canvas:not([hidden])'), workbench = box('#viewer-texture-workbench');
    const visibleArea = canvas ? Math.max(0, Math.min(innerWidth, canvas.right) - Math.max(0, canvas.x)) * Math.max(0, Math.min(innerHeight, canvas.bottom) - Math.max(0, canvas.y)) : 0;
    return { viewport: { width: innerWidth, height: innerHeight }, canvas, workbench, rail: box('.viewer-texture-tool-rail'), paint: box('#viewer-texture-paint-tool'), selection: box('#viewer-texture-selection-tool'), selectionMode: box('#viewer-texture-selection-mode'), inspector: box('#viewer-texture-inspector'), inspectorOpen: document.getElementById('viewer-texture-inspector').open, visibleCanvasAreaFraction: visibleArea / (innerWidth * innerHeight), canvasWorkbenchAreaFraction: canvas.width * canvas.height / (workbench.width * workbench.height), overflow: document.documentElement.scrollWidth > innerWidth + 1 };
  });
}
function canvasFirst(value, name) {
  const c = value.canvas, v = value.viewport;
  assert(c.width > 0 && c.height > 0 && c.x >= -1 && c.y >= -1 && c.right <= v.width + 1 && c.bottom <= v.height + 1, name + ': canvas is initially wholly visible: ' + JSON.stringify(value));
  assert(value.canvasWorkbenchAreaFraction > .5, name + ': canvas occupies over half the workbench: ' + JSON.stringify(value));
  assert(value.visibleCanvasAreaFraction >= .4, name + ': canvas occupies at least40% of viewport: ' + JSON.stringify(value));
  assert(!value.overflow, name + ': no horizontal document overflow');
  const activeTool = value.paint && value.paint.width ? value.paint : value.selection;
  for (const [label, control] of [['selectionMode', value.selectionMode], ['activeTool', activeTool]]) {
    assert(control && control.width > 0 && control.height > 0 && control.y >= 0 && control.bottom <= v.height + 1, name + ': ' + label + ' remains visible beside the canvas');
    const distance = Math.max(0, c.y - control.bottom, control.y - c.bottom, c.x - control.right, control.x - c.right);
    assert(distance <= 160, name + ': ' + label + ' is adjacent to canvas, not a page of scrolling away: ' + distance);
  }
}
async function mode(page, name) {
  const buttons = page.locator('#viewer-texture-tools [data-texture-tool="' + name + '"]'); assert.equal(await buttons.count(), 1, 'each texture interaction has one authoritative button'); const button = buttons.first();
  const hit = await button.evaluate(e => { const r = e.getBoundingClientRect(), target = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { visible: r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1, hit: target === e || e.contains(target) }; });
  assert(hit.visible && hit.hit, name + ': interaction button is initially visible and directly hittable'); await button.click(); await idle(page);
  assert.equal((await state(page)).selection.tool, name, 'rail updates real engine mode');
  assert.equal(await page.locator('#viewer-texture-paint-tool').inputValue(), name, 'legacy/current mode controls share one state');
  assert.equal(await button.getAttribute('aria-pressed'), 'true', 'active interaction mode is exposed');
  return button;
}
async function point(page, x, y) { const c = await page.locator('#viewer-texture-canvas-host canvas:visible').boundingBox(), v = (await state(page)).selection.view; return { x: c.x + v.x + x * v.zoom, y: c.y + v.y + y * v.zoom }; }
async function pixel(page, x, y) { const p = await point(page, x, y); await page.mouse.click(p.x, p.y); await idle(page); }
async function rectangle(page, r) { await mode(page, 'select-rectangle'); const a = await point(page, r[0], r[1]), b = await point(page, r[2], r[3]); await page.mouse.move(a.x, a.y); await page.mouse.down(); await page.mouse.move(b.x, b.y, { steps: 6 }); await page.mouse.up(); await idle(page); }
async function shortcut(page, key) { await page.locator('#viewer-texture-canvas-host canvas:visible').evaluate(e => e.focus({ preventScroll: true })); await page.keyboard.press(key); await idle(page); }
async function exportedPixels(page) { const edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.equal(edits.length, 1); return py("import base64,io,json,sys;from PIL import Image;im=Image.open(io.BytesIO(base64.b64decode(sys.argv[1].split(',',1)[-1]))).convert('RGBA');print(json.dumps(list(im.tobytes())))", [edits[0].png]); }
async function startServer() {
  const socket = net.createServer(); await new Promise(r => socket.listen(0, '127.0.0.1', r)); const port = socket.address().port; await new Promise(r => socket.close(r));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log')); const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); } throw Error('Product server not ready');
}
async function load(page) {
  await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && ModelViewer.getTextureTools && ModelViewer.getTextureTools());
  await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && window.__workspaceObserved);
  await reveal(page, '#viewer-texture-select'); await page.locator('#viewer-texture-select').selectOption({ index: 1 }); await idle(page);
  await page.locator('#viewer-texture-tab-paint').click(); await idle(page);
}
async function sampleUVs(page) {
  return page.evaluate(() => {
    let found = null; __workspaceObserved.scene.traverse(mesh => { if (found || !mesh.isMesh || !mesh.geometry || !mesh.geometry.attributes.uv || mesh.userData && mesh.userData.viewerHelper) return; const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material; const texture = material && (material.uniforms && material.uniforms.uMainTex && material.uniforms.uMainTex.value || material.map); if (!texture) return; if (texture.matrixAutoUpdate) texture.updateMatrix(); const index = mesh.geometry.index, uv = mesh.geometry.attributes.uv; const triangles = []; for (let face = 0; face < 3; face++) { const points = []; for (let k = 0; k < 3; k++) { const v = index ? index.getX(face * 3 + k) : face * 3 + k, p = new THREE.Vector2(uv.getX(v), uv.getY(v)); texture.transformUv(p); points.push([p.x, p.y]); } triangles.push(points); } found = triangles; }); if (!found) throw Error('No rendered source UV mesh'); return found;
  });
}
const centroid = points => [points.reduce((sum, p) => sum + p[0], 0) / 3 * fixture.width, points.reduce((sum, p) => sum + p[1], 0) / 3 * fixture.height];
async function uvSelection(page) {
  const triangles = await sampleUVs(page), a = centroid(triangles[0]), b = centroid(triangles[2]);
  await page.locator('#viewer-texture-selection-mode').selectOption('replace'); await mode(page, 'select-uv-face'); await pixel(page, ...a); const face = await state(page); assert(face.selection.selectionActive && face.selection.selectedPixels > 0); assert.equal(face.lastUVSelection.faceCount, 1, 'actual face tool selected exactly one source triangle');
  await mode(page, 'select-uv-island'); await pixel(page, ...a); const island = await state(page); assert(island.selection.selectedPixels > face.selection.selectedPixels, 'UV island adds the connected neighboring triangle'); assert.equal(island.lastUVSelection.faceCount, 2, 'island follows the shared UV edge and excludes the separate triangle');
  await page.locator('#viewer-texture-selection-mode').selectOption('add'); await pixel(page, ...b); const both = (await state(page)).selection.selectedPixels; assert(both > island.selection.selectedPixels, 'add selects the separate UV island');
  await page.locator('#viewer-texture-selection-mode').selectOption('subtract'); await pixel(page, ...b); assert.equal((await state(page)).selection.selectedPixels, island.selection.selectedPixels, 'subtract removes only the second UV island');
  await page.locator('#viewer-texture-undo').click(); await idle(page); assert.equal((await state(page)).selection.selectedPixels, both, 'UV selection remains undoable'); await page.locator('#viewer-texture-redo').click(); await idle(page); assert.equal((await state(page)).selection.selectedPixels, island.selection.selectedPixels);
  await field(page, '#viewer-texture-paint-color', '#ff0000'); await field(page, '#viewer-texture-opacity', 100); await mode(page, 'fill'); await pixel(page, ...a);
  const rgba = await exportedPixels(page); const read = p => rgba.slice((Math.floor(p[1]) * fixture.width + Math.floor(p[0])) * 4, (Math.floor(p[1]) * fixture.width + Math.floor(p[0])) * 4 + 4);
  assert.deepEqual(read(a), [255, 0, 0, 255], 'fill edits selected UV island pixels'); assert.deepEqual(read(b), [70, 120, 190, 255], 'separate UV island pixels remain unchanged');
  await shortcut(page, 'Control+z'); assert.equal((await state(page)).editedTextures.length, 0, 'undo restores original texture bytes after UV-scoped fill');
  report.cases.push({ name: 'actual UV face/island selection with add/subtract/undo/redo and scoped PNG pixels', facePixels: face.selection.selectedPixels, islandPixels: island.selection.selectedPixels, bothPixels: both, displayedTriangles: triangles });
}
async function editSmoke(page) {
  const fileSummary = page.locator('.viewer-texture-file-menu > summary'); await fileSummary.click(); assert(await page.locator('.viewer-texture-file-menu').evaluate(e => e.open)); await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.querySelector('.viewer-texture-file-menu').open); await page.waitForFunction(() => document.activeElement === document.querySelector('.viewer-texture-file-menu > summary'));
  assert((await state(page)).expanded, 'Escape closes the active file menu and restores its summary focus without closing the editor');
  await page.locator('#viewer-texture-selection-mode').selectOption('replace'); await rectangle(page, [2, 3, 6, 7]); assert.equal((await state(page)).selection.selectedPixels, 16);
  await shortcut(page, 'Control+c'); assert.equal((await state(page)).editedTextures.length, 0); await shortcut(page, 'Control+x'); assert.equal((await state(page)).editedTextures.length, 1, 'cut still edits selected pixels after UI reparenting');
  await shortcut(page, 'Control+z'); assert.equal((await state(page)).editedTextures.length, 0); await shortcut(page, 'Control+v'); assert((await state(page)).selection.floatingSelection); await shortcut(page, 'Escape'); assert(!(await state(page)).selection.floatingSelection && (await state(page)).expanded, 'Escape cancels pending paste without closing workspace');
  await field(page, '#viewer-texture-brush-size', 1); await field(page, '#viewer-texture-softness', 0); await field(page, '#viewer-texture-opacity', 100); await mode(page, 'brush'); await pixel(page, 3.5, 4.5); assert.equal((await state(page)).editedTextures.length, 1, 'brush still paints'); await shortcut(page, 'Control+z'); assert.equal((await state(page)).editedTextures.length, 0);
  report.cases.push({ name: 'canvas-local marquee/brush, clipboard cut/copy/paste, undo and floating Escape preserve existing editing flows', fileMenuEscapeRestoresInvokerWithoutClosingEditor: true });
}
async function resizeInspector(page) {
  const handle = page.locator('#viewer-texture-inspector-resizer'); await handle.focus(); const before = await snapshot(page); await page.keyboard.press('ArrowLeft'); await page.keyboard.press('ArrowLeft'); await page.keyboard.press('ArrowLeft'); await frames(page); const after = await snapshot(page);
  assert(Math.abs(after.inspector.width - before.inspector.width) >= 16 && Math.abs(after.canvas.width - before.canvas.width) >= 16, 'inspector separator resizes actual canvas and inspector dimensions');
  for (let i = 0; i < 7; i++) { await reveal(page, '#viewer-texture-layer-add'); await page.locator('#viewer-texture-layer-add').click(); await idle(page); }
  await page.locator('#viewer-texture-inspector').evaluate(root => root.querySelectorAll('details').forEach(e => e.open = true)); await frames(page); const stationary = await snapshot(page);
  const scrolled = await page.locator('#viewer-texture-inspector').evaluate(root => { const nodes = [root, ...root.querySelectorAll('*')].filter(e => e.clientHeight && e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(e).overflowY)); nodes.sort((a, b) => b.scrollHeight - b.clientHeight - (a.scrollHeight - a.clientHeight)); const target = nodes[0]; if (!target) return null; target.scrollTop = target.scrollHeight; return { tag: target.tagName, id: target.id, top: target.scrollTop, max: target.scrollHeight - target.clientHeight }; });
  assert(scrolled && scrolled.top > 0, 'layer/inspector contents scroll independently'); await frames(page); const later = await snapshot(page); assert(Math.abs(later.canvas.y - stationary.canvas.y) < 1 && Math.abs(later.rail.y - stationary.rail.y) < 1, 'inspector scrolling does not move canvas or mode rail');
  report.cases.push({ name: 'accessible inspector separator and independent property/layer scrolling', before, after, scrolled });
  for (let i = 0; i < 7; i++) { await page.locator('#viewer-texture-undo').click(); await idle(page); }
}
async function resizeCanvasPersistence(page) {
  await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(false)); await frames(page); const handle = page.locator('#viewer-texture-canvas-resizer'); await handle.scrollIntoViewIfNeeded(); await handle.focus(); const before = (await snapshot(page)).canvas.height;
  for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowDown'); await frames(page); let after = (await snapshot(page)).canvas.height;
  if (Math.abs(after - before) < 16) { for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowUp'); await frames(page); after = (await snapshot(page)).canvas.height; }
  assert(Math.abs(after - before) >= 16, 'canvas separator changes actual visible canvas height');
  await load(page); await frames(page); const reloaded = (await snapshot(page)).canvas.height; assert(Math.abs(reloaded - after) <= 2, 'canvas height persists across reload/reopening the model');
  report.cases.push({ name: 'keyboard canvas-height resizing persists across app-page reload', before, after, reloaded });
}
(async () => { try {
  server = await startServer(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  for (const profile of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'phone', width: 390, height: 844, touch: true }]) {
    const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch }); const page = await context.newPage(); currentPage = page; page.setDefaultTimeout(25000); page.on('pageerror', e => report.errors.push(String(e.stack || e))); await page.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    await page.route('**/static/viewer-quality.js', async route => { const response = await route.fetch(), source = await response.text(); await route.fulfill({ response, body: source + '\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__workspaceObserved={scene,camera};return render.apply(this,arguments);};return c;};})();' }); });
    await load(page); await page.locator('#viewer-texture-workbench').waitFor(); await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(true)); await frames(page); const initial = await snapshot(page); canvasFirst(initial, profile.name); assert.equal(initial.inspectorOpen, !profile.touch, 'expanded inspector defaults suit the screen size'); await page.screenshot({ path: path.join(evidence, profile.name + '-workspace-initial.png') });
    report.profiles.push({ profile, initial }); report.cases.push({ name: profile.name + ': initial dominant canvas and adjacent visible interaction tools', visibleCanvasAreaFraction: initial.visibleCanvasAreaFraction, canvasWorkbenchAreaFraction: initial.canvasWorkbenchAreaFraction });
    if (!profile.touch) { await uvSelection(page); await editSmoke(page); await page.screenshot({ path: path.join(evidence, 'desktop-workspace-editing.png') }); await resizeInspector(page); await resizeCanvasPersistence(page); }
    else { await mode(page, 'pan'); const c = await page.locator('#viewer-texture-canvas-host canvas:visible').boundingBox(), before = (await state(page)).selection.view; await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2); await page.mouse.down(); await page.mouse.move(c.x + c.width / 2 + 20, c.y + c.height / 2 + 15, { steps: 5 }); await page.mouse.up(); await frames(page); const after = (await state(page)).selection.view; assert(before.x !== after.x || before.y !== after.y, 'phone local pan mode moves the actual texture view'); report.cases.push({ name: 'phone canvas-local pan switches interaction without scrolling away' }); }
    await context.close(); currentPage = null;
  }
  assert.deepEqual(report.errors, []); assert.equal(hash(fs.readFileSync(source)), fixtureHash); report.sourceAfter = sourceHashes(); assert.deepEqual(report.sourceAfter, report.sourceBefore, 'relevant production source stayed fixed during proof'); report.status = 'PASS';
} catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); if (currentPage) { try { report.failureState = await state(currentPage); await currentPage.screenshot({ path: path.join(evidence, 'failure.png') }); } catch (_) {} } throw error;
} finally { if (browser) await browser.close(); if (server) { server.child.kill('SIGTERM'); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence, error: report.error })); }
})().catch(() => process.exitCode = 1);
