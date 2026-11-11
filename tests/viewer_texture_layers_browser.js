/* Real product layer, marquee, internal clipboard and portable project flows.
 * Expected paint/compositing bytes are computed independently of the editor.
 */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-layers-browser-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-layers-library-')), models = path.join(library, 'extracted/3d_model');
const source = path.join(models, 'layer-colors.unity'), motion = path.join(models, 'layer-motion.unity'), originalPNG = path.join(library, 'extracted/textures/original.png');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(path.dirname(originalPNG), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex'), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function py(code, args = []) { return JSON.parse(execFileSync(python, ['-B', '-c', code, ...args], { cwd: product, encoding: 'utf8', env: { ...process.env, PYTHONPATH: product + path.delimiter + repo }, maxBuffer: 8 * 1024 * 1024 })); }
const fixture = py(`import json,sys,UnityPy
from pathlib import Path
from PIL import Image
env=UnityPy.load(Path('tests/fixtures/viewer_persistence.unity').read_bytes())
im=Image.new('RGBA',(16,16))
for y in range(16):
 for x in range(16):im.putpixel((x,y),(20+x*7,40+y*5,60+x+y,255))
im.putpixel((15,14),(30,160,70,128));im.putpixel((15,15),(9,8,7,0))
for obj in env.objects:
 if obj.type.name=='Texture2D':
  texture=obj.read();texture.image=im;texture.m_Name='ch0001_co0001_body';texture.save()
Path(sys.argv[1]).write_bytes(env.file.save(packer='original'));im.save(sys.argv[2])
for obj in list(env.objects):
 if obj.type.name!='AnimationClip':del obj.assets_file.objects[obj.path_id]
 else:
  tree=obj.read_typetree();tree['m_Name']='Layered texture retention';obj.save_typetree(tree)
Path(sys.argv[3]).write_bytes(env.file.save(packer='original'));print(json.dumps({'width':16,'height':16,'rgba':list(im.tobytes())}))`, [source, originalPNG, motion]);
const sourceSHA = sha(fs.readFileSync(source));
const productFiles = ['webtools/server.py', 'webtools/core/texture_project_io.py', 'webtools/web/index.html', 'webtools/web/static/model-viewer.js', 'webtools/web/static/viewer-persistence.js', 'webtools/web/static/viewer-texture-tools.js', 'webtools/web/static/viewer-texture-tools.css', 'webtools/web/static/texture-paint-engine.js'];
const sourceHashes = () => Object.fromEntries(productFiles.map(file => [file, sha(fs.readFileSync(path.join(product, file)))]));
const report = { status: 'RUNNING', evidence, scope: 'Actual production HTTP/Unity/Chromium; observational rendering hooks only; independent RGBA and Pillow decoding', cases: [], sourceBefore: sourceHashes() };
let server, browser, desktop, mobile, page;
async function startServer() {
  const sock = net.createServer(); await new Promise(resolve => sock.listen(0, '127.0.0.1', resolve)); const port = sock.address().port; await new Promise(resolve => sock.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); } throw Error('Product server not ready');
}
async function frames(p) { await p.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
function response(p, suffix) { const pending = p.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === 'POST'); pending.catch(() => {}); return pending; }
async function state(p) { return p.evaluate(() => ModelViewer.getTextureTools().getState()); }
async function idle(p) { await p.waitForFunction(() => { const tools = ModelViewer.getTextureTools(), s = tools && tools.getState(); return s && (!s.pending || s.selection && s.selection.floatingSelection) && !s.loading; }); await frames(p); }
async function show(p, id) { const e = p.locator(id); await e.evaluate(e => { for (let a = e.parentElement; a; a = a.parentElement) if (a.tagName === 'DETAILS') a.open = true; }); await e.scrollIntoViewIfNeeded(); return e; }
async function click(p, id) { await (await show(p, id)).click(); await idle(p); }
async function field(p, id, value, event = 'input') {
  const control = await show(p, id), type = await control.getAttribute('type');
  if (event === 'change' && ['text', 'number'].includes(type)) { await control.fill(String(value)); await control.press('Tab'); }
  else { await control.focus(); await control.evaluate((e, v) => { e.value = String(v.value); e.dispatchEvent(new Event(v.event, { bubbles: true })); }, { value, event }); }
  await idle(p);
}
function decodePNG(png) { return py("import io,base64,json,sys;from PIL import Image;im=Image.open(io.BytesIO(base64.b64decode(sys.argv[1].split(',',1)[-1]))).convert('RGBA');print(json.dumps({'width':im.width,'height':im.height,'rgba':list(im.tobytes())}))", [png]); }
function decodeFile(file) { return decodePNG('data:image/png;base64,' + fs.readFileSync(file).toString('base64')); }
async function pixels(p) { const rows = await p.evaluate(() => ModelViewer.getTextureTools().getEdits()); return rows.length ? decodePNG(rows[0].png).rgba : fixture.rgba.slice(); }
function blank() { return new Array(16 * 16 * 4).fill(0); }
function rectangle(rgba, rect, color) { const result = rgba.slice(); for (let y = rect[1]; y < rect[3]; y++) for (let x = rect[0]; x < rect[2]; x++) result.splice((y * 16 + x) * 4, 4, ...color); return result; }
function composite(bottom, top, opacity = 1) {
  const result = bottom.slice();
  for (let i = 0; i < top.length; i += 4) {
    const foreground = top[i + 3] / 255 * opacity; if (!foreground) continue;
    const background = bottom[i + 3] / 255, alpha = foreground + background * (1 - foreground);
    for (let c = 0; c < 3; c++) result[i + c] = Math.round((top[i + c] * foreground + bottom[i + c] * background * (1 - foreground)) / alpha);
    result[i + 3] = Math.round(alpha * 255);
  }
  return result;
}
async function imagePoint(p, x, y) {
  const canvas = p.locator('#viewer-texture-canvas-host canvas:visible'); await canvas.scrollIntoViewIfNeeded(); await frames(p);
  const rect = await canvas.boundingBox(), view = (await state(p)).selection.view;
  return { x: rect.x + view.x + x * view.zoom, y: rect.y + view.y + y * view.zoom };
}
async function pointer(p, x, y) { const point = await imagePoint(p, x, y); await p.mouse.click(point.x, point.y); await idle(p); return point; }
async function marquee(p, rect) {
  await (await show(p, '#viewer-texture-paint-tool')).selectOption('select-rectangle');
  const a = await imagePoint(p, rect[0], rect[1]), b = await imagePoint(p, rect[2], rect[3]);
  await p.mouse.move(a.x, a.y); await p.mouse.down(); await p.mouse.move(b.x, b.y, { steps: 8 }); await p.mouse.up(); await idle(p);
  const selected = (await state(p)).selection;
  assert(selected.selectionActive && selected.selectionVisible); assert.equal(selected.selectedPixels, (rect[2] - rect[0]) * (rect[3] - rect[1]), 'Marquee maps image pixel centers exactly');
  return selected;
}
async function fill(p, rect, color) {
  await marquee(p, rect); await field(p, '#viewer-texture-paint-color', color); await field(p, '#viewer-texture-paint-alpha', 100); await field(p, '#viewer-texture-opacity', 100);
  await (await show(p, '#viewer-texture-paint-tool')).selectOption('fill'); await pointer(p, rect[0] + .5, rect[1] + .5);
}
async function focusCanvas(p) { await p.locator('#viewer-texture-canvas-host canvas:visible').evaluate(e => e.focus({ preventScroll: true })); }
async function shortcut(p, key) { await focusCanvas(p); await p.keyboard.press(key); await idle(p); }
async function dragFloating(p, origin, dx, dy) {
  const a = await imagePoint(p, origin[0], origin[1]), b = await imagePoint(p, origin[0] + dx, origin[1] + dy);
  await p.mouse.move(a.x, a.y); await p.mouse.down(); await p.mouse.move(b.x, b.y, { steps: 7 }); await p.mouse.up(); await frames(p);
}
async function shaderPixels(p) { await frames(p); return p.evaluate(() => { let result = null; __layerObserved.scene.traverse(mesh => { const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]; materials.forEach(m => { const t = m && m.uniforms && m.uniforms.uMainTex && m.uniforms.uMainTex.value; if (t && t.isDataTexture && t.image && t.image.data) result = Array.from(t.image.data); }); }); return result; }); }
async function waitShader(p, expected) { await p.waitForFunction(expected => { let found = false; __layerObserved.scene.traverse(mesh => { const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]; materials.forEach(m => { const t = m && m.uniforms && m.uniforms.uMainTex && m.uniforms.uMainTex.value, bytes = t && t.isDataTexture && t.image && t.image.data; if (bytes && bytes.length === expected.length && expected.every((v, i) => bytes[i] === v)) found = true; }); }); return found; }, expected); }
async function assertImage(p, expected, label) {
  await idle(p); assert.deepStrictEqual(await pixels(p), expected, label + ': committed PNG');
  if (expected.every((v, i) => v === fixture.rgba[i])) {
    await p.waitForFunction(() => ModelViewer.getState().materials.textureOverrides === 0);
    assert.equal(await shaderPixels(p), null, label + ': original high-quality sampler is restored when flattened pixels equal the source');
  } else { await waitShader(p, expected); assert.deepStrictEqual(await shaderPixels(p), expected, label + ': actual high-quality uMainTex'); }
}
async function addLayer(p, name) { await click(p, '#viewer-texture-layer-add'); await field(p, '#viewer-texture-layer-name', name, 'change'); return (await state(p)).selection.activeLayerId; }
async function selectLayer(p, id) { await p.locator('#viewer-texture-layer-list [data-layer-id="' + id + '"] button').click(); await idle(p); }
async function saveProject(p) { const pending = response(p, '/api/texture/editor/project/save'); await (await show(p, '#viewer-texture-project-save')).click(); const r = await pending; assert.equal(r.status(), 200, await r.text()); const saved = await r.json(); assert(fs.existsSync(saved.path)); assert(saved.url.startsWith('/api/download?')); const project = JSON.parse(fs.readFileSync(saved.path, 'utf8')); await idle(p); return { saved, project }; }
function projectPixels(project) { return project.layers.map(layer => ({ ...layer, rgba: decodePNG(layer.png).rgba })); }
async function openProjectPicker(p, file) {
  const originalZ = await p.locator('#picker').evaluate(e => e.style.zIndex);
  await (await show(p, '#viewer-texture-project-open')).click(); await p.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
  await p.evaluate(folder => navigate(folder), path.dirname(file)); await p.waitForFunction(folder => document.getElementById('picker-crumb').textContent === folder, path.dirname(file));
  const row = p.locator('#picker-entries li').filter({ hasText: path.basename(file) }); await row.scrollIntoViewIfNeeded();
  const hit = await row.evaluate(e => { const r = e.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { reachable: hit === e || e.contains(hit), expanded: ModelViewer.getTextureTools().getState().expanded }; });
  assert(hit.reachable, 'Project picker file row receives actual pointer hits above expanded editor');
  const pending = response(p, '/api/texture/editor/project/open'); await row.click(); const r = await pending; assert.equal(r.status(), 200, await r.text());
  await p.waitForFunction(() => document.getElementById('picker').classList.contains('hidden')); await idle(p); assert.equal(await p.locator('#picker').evaluate(e => e.style.zIndex), originalZ); return hit;
}
function bundlePixels(file) { return py(`import io,json,sys,zipfile,UnityPy
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes();objects=[]
if zipfile.is_zipfile(io.BytesIO(raw)):
 z=zipfile.ZipFile(io.BytesIO(raw))
 for name in z.namelist():
  if name.endswith('.unity'):objects.extend(UnityPy.load(z.read(name)).objects)
else:objects=UnityPy.load(raw).objects
result=[]
for obj in objects:
 if obj.type.name=='Texture2D':
  t=obj.read();im=t.image.convert('RGBA');result.append({'name':t.m_Name,'rgba':list(im.tobytes())})
print(json.dumps(result))`, [file]); }
async function setup(p, errors, model = true) {
  p.setDefaultTimeout(45000); p.on('pageerror', e => errors.push(String(e.stack || e)));
  await p.addInitScript(() => { localStorage.setItem('sifas_lang', 'en'); window.__layerDashes = []; const original = CanvasRenderingContext2D.prototype.setLineDash; CanvasRenderingContext2D.prototype.setLineDash = function (segments) { if (this.canvas.closest('#viewer-texture-canvas-host') && segments.some(v => v > 0)) __layerDashes.push(segments.slice()); return original.apply(this, arguments); }; });
  await p.route('**/static/viewer-quality.js', async route => { const response = await route.fetch(); await route.fulfill({ response, body: (await response.text()) + '\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const controller=create.apply(this,arguments),render=controller.render;controller.render=function(scene,camera){window.__layerObserved={scene,camera};return render.apply(this,arguments);};return controller;};})();' }); });
  await p.goto(server.url); await p.waitForFunction(() => window.ModelViewer && ModelViewer.getTextureTools());
  if (model) { await p.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source); await p.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available && window.__layerObserved); await (await show(p, '#viewer-texture-select')).selectOption({ index: 1 }); await idle(p); await (await show(p, '#viewer-shader')).selectOption('sifas'); await (await show(p, '#viewer-high-quality')).check(); }
  else { await click(p, '#texture-editor-launch'); await p.locator('#viewer-texture-paint-panel input[type="file"][accept="image/png,.png"]').setInputFiles(originalPNG); await idle(p); }
  await p.evaluate(() => ModelViewer.getTextureTools().setTab('paint')); await idle(p);
}
async function run() {
  const errors = [];
  try {
    server = await startServer(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    desktop = await browser.newContext({ viewport: { width: 1480, height: 1100 }, hasTouch: true }); page = await desktop.newPage(); await setup(page, errors);
    const duplicateIds = await page.evaluate(() => { const counts = new Map(); document.querySelectorAll('[id]').forEach(e => counts.set(e.id, (counts.get(e.id) || 0) + 1)); return Array.from(counts).filter(([id, count]) => id && count > 1); });
    assert.deepStrictEqual(duplicateIds, [], 'Every mounted product DOM ID is unique, including preview Cancel and moved-pixels Cancel');
    const initial = await state(page), originalLayer = initial.selection.activeLayerId, sourceTextureSHA = initial.sourceSha256;
    const red = [230, 40, 70, 255], redRect = [2, 3, 6, 7], redRaw = rectangle(blank(), redRect, red), redFlatten = composite(fixture.rgba, redRaw);
    const redLayer = await addLayer(page, '의상 · Red'); await fill(page, redRect, '#e62846'); await assertImage(page, redFlatten, 'Marquee-limited fill on transparent layer');
    assert((await page.evaluate(() => __layerDashes)).length > 0, 'Visible selection uses an actual dashed canvas outline');
    await page.screenshot({ path: path.join(evidence, '01-layer-marquee-fill.png') }); report.cases.push({ name: 'rectangle marquee visible dashed bounds; bucket fill edits only selected active-layer pixels', selected: (await state(page)).selection.selectedPixels });
    await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(true)); await frames(page);
    const beforeCopy = (await state(page)).selection.undoCount; await shortcut(page, 'Control+c'); assert.equal((await state(page)).selection.undoCount, beforeCopy, 'Copy creates no undo entry');
    await shortcut(page, 'Control+v'); assert((await state(page)).selection.floatingSelection); await dragFloating(page, [3.5, 4.5], 6, 1);
    assert(await page.locator('#viewer-save').isDisabled()); assert(await page.locator('#viewer-texture-project-save').isDisabled()); assert(await page.locator('#viewer-texture-export').isDisabled(), 'Pending moved pixels cannot be flattened by export');
    assert.deepStrictEqual(await pixels(page), redFlatten, 'Pending paste never enters saved edits');
    const copiedRaw = rectangle(redRaw, [8, 4, 12, 8], red), copiedFlatten = composite(fixture.rgba, copiedRaw); await waitShader(page, copiedFlatten); assert.deepStrictEqual(await shaderPixels(page), copiedFlatten, 'Floating paste is visible on actual 3D material');
    await shortcut(page, 'Escape'); assert(!(await state(page)).selection.floatingSelection); assert((await state(page)).expanded, 'First Escape cancels floating pixels and retains expanded workspace'); await assertImage(page, redFlatten, 'Cancel pasted pixels');
    await shortcut(page, 'Control+v'); await dragFloating(page, [3.5, 4.5], 6, 1); await shortcut(page, 'Enter'); await assertImage(page, copiedFlatten, 'Enter commits moved paste');
    assert.equal((await state(page)).selection.undoCount, beforeCopy + 1, 'Paste and move commit is one undo'); await shortcut(page, 'Control+z'); await assertImage(page, redFlatten, 'Undo pasted pixels');
    await marquee(page, redRect); const beforeCut = (await state(page)).selection.undoCount; await shortcut(page, 'Control+x'); await assertImage(page, fixture.rgba, 'Cut affects active paint layer and reveals original'); assert.equal((await state(page)).selection.undoCount, beforeCut + 1); await shortcut(page, 'Control+z'); await assertImage(page, redFlatten, 'Undo cut restores exact active-layer pixels');
    await click(page, '#viewer-texture-move'); await dragFloating(page, [3.5, 4.5], 6, 1); await click(page, '#viewer-texture-cancel-move'); assert(!(await state(page)).selection.floatingSelection); await assertImage(page, redFlatten, 'Dedicated Cancel move button cancels cut-move');
    await click(page, '#viewer-texture-move'); await dragFloating(page, [3.5, 4.5], 6, 1); await shortcut(page, 'Enter'); const movedRaw = rectangle(blank(), [8, 4, 12, 8], red); await assertImage(page, composite(fixture.rgba, movedRaw), 'Cut-move commits at destination'); await shortcut(page, 'Control+z'); await assertImage(page, redFlatten, 'One Undo restores cut-move');
    await page.screenshot({ path: path.join(evidence, '02-clipboard-expanded.png') }); report.cases.push({ name: 'actual keyboard copy/cut/paste, pointer move, Enter/Escape, pending export guards and one-step Undo' });
    await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(false)); await selectLayer(page, originalLayer); await click(page, '#viewer-texture-layer-duplicate'); const hiddenLayer = (await state(page)).selection.activeLayerId; await field(page, '#viewer-texture-layer-name', '숨김 원본 · Hidden RGB', 'change'); await page.locator('#viewer-texture-layer-list [data-layer-id="' + hiddenLayer + '"] input[type="checkbox"]').uncheck(); await idle(page);
    await selectLayer(page, redLayer); const blueLayer = await addLayer(page, '장식 · Blue'); const blueRect = [4, 5, 8, 9], blue = [16, 48, 240, 255], blueRaw = rectangle(blank(), blueRect, blue); await fill(page, blueRect, '#1030f0'); await field(page, '#viewer-texture-layer-opacity', 50, 'change');
    let expected = composite(redFlatten, blueRaw, .5); assert.deepStrictEqual(expected.slice((5 * 16 + 4) * 4, (5 * 16 + 4) * 4 + 4), [123, 44, 155, 255], 'Independent fixed overlap color'); await assertImage(page, expected, 'Upper-layer opacity composites exact straight-alpha pixels');
    const beforeOrder = (await state(page)).selection.layers.map(e => e.id); await click(page, '#viewer-texture-layer-down'); await assertImage(page, composite(composite(fixture.rgba, blueRaw, .5), redRaw), 'Layer down changes visible overlap'); await shortcut(page, 'Control+z'); assert.deepStrictEqual((await state(page)).selection.layers.map(e => e.id), beforeOrder); await assertImage(page, expected, 'Undo restores original layer order');
    const metadata = (await state(page)).selection.layers; await click(page, '#viewer-texture-layer-merge'); assert.equal((await state(page)).selection.layers.length, 3);
    // Baking a pair's fractional effective alpha to RGBA8 can round final RGB
    // by one byte when it is later composited over another, unchanged layer.
    const merged = await pixels(page); assert(merged.every((v, i) => { const alphaIndex = i - i % 4 + 3, tolerance = i % 4 !== 3 && blueRaw[alphaIndex] && !redRaw[alphaIndex] ? 1 : 0; return Math.abs(v - expected[i]) <= tolerance; }), 'Only fractional merged alpha can incur one-byte RGB rounding; every unrelated pixel and alpha remains exact'); await assertImage(page, merged, 'Merged pixels agree between PNG and high-quality 3D');
    const mergedPNGResponse = response(page, '/api/texture/editor/save'); await (await show(page, '#viewer-texture-export')).click(); const mergedPNG = await (await mergedPNGResponse).json(); assert.deepStrictEqual(decodeFile(mergedPNG.path).rgba, merged, 'Actual PNG export after merge adds no encode loss');
    await shortcut(page, 'Control+z'); assert.deepStrictEqual((await state(page)).selection.layers, metadata); await assertImage(page, expected, 'Undo merge restores stack metadata and pixels exactly');
    const saved = await saveProject(page), rawLayers = projectPixels(saved.project); assert.equal(rawLayers.length, 4); assert.deepStrictEqual(rawLayers.find(e => e.id === originalLayer).rgba, fixture.rgba); assert.deepStrictEqual(rawLayers.find(e => e.id === hiddenLayer).rgba, fixture.rgba, 'Hidden duplicate preserves alpha-zero RGB and partial alpha exactly'); assert.deepStrictEqual(rawLayers.find(e => e.id === redLayer).rgba, redRaw); assert.deepStrictEqual(rawLayers.find(e => e.id === blueLayer).rgba, blueRaw); assert.equal(rawLayers.find(e => e.id === hiddenLayer).visible, false); assert.equal(rawLayers.find(e => e.id === blueLayer).opacity, .5);
    assert.equal(rawLayers.find(e => e.id === redLayer).name, '의상 · Red'); assert.equal(rawLayers.find(e => e.id === hiddenLayer).name, '숨김 원본 · Hidden RGB'); assert.equal(rawLayers.find(e => e.id === blueLayer).name, '장식 · Blue');
    assert.deepStrictEqual(await page.locator('#viewer-texture-layer-list [data-layer-id]').evaluateAll(rows => rows.map(e => e.dataset.layerId)), metadata.map(e => e.id).reverse(), 'UI layer list displays top to bottom');
    report.cases.push({ name: 'layer add/name/duplicate/visibility/opacity/order/merge Undo; saved hidden RGBA exact', saved: saved.saved, layers: metadata, mergeQuantization: { maximumRGBDifference: Math.max(...merged.map((v, i) => Math.abs(v - expected[i]))), permittedOnly: 'fractional pair alpha baked to RGBA8 over unchanged lower layer; other pixels/alpha and full Undo are exact', pngAfterMerge: mergedPNG.path } });
    await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(true)); await click(page, '#viewer-texture-layer-remove'); assert.equal((await state(page)).selection.layers.length, 3);
    const projectHit = await openProjectPicker(page, saved.saved.path); assert(projectHit.expanded); assert.deepStrictEqual((await state(page)).selection.layers, metadata); assert.equal((await state(page)).sourceSha256, sourceTextureSHA, 'Portable project binds current texture SHA'); await assertImage(page, expected, 'Reopened layer project');
    const reopened = await saveProject(page); assert.deepStrictEqual(projectPixels(reopened.project), rawLayers, 'Save/reopen preserves every layer name, order, visibility, opacity and exact PNG pixels'); report.cases.push({ name: 'expanded actual project picker, current source binding, save/reopen full layer stack', projectHit });
    await marquee(page, blueRect); await page.evaluate(() => ModelViewer.getTextureTools().setTab('costume'));
    await (await show(page, '#viewer-texture-hue')).evaluate(e => { e.value = '90'; e.dispatchEvent(new Event('input', { bubbles: true })); });
    await page.waitForFunction(() => ModelViewer.getTextureTools().getState().preview && !document.getElementById('viewer-texture-apply').disabled);
    assert.deepStrictEqual(await pixels(page), expected, 'Active-layer OKLCH preview is not a committed flat replacement');
    await (await show(page, '#viewer-texture-apply')).click(); await idle(page); await page.evaluate(() => ModelViewer.getTextureTools().setTab('paint')); const recolored = await saveProject(page), recoloredLayers = projectPixels(recolored.project);
    for (const id of [originalLayer, hiddenLayer, redLayer]) assert.deepStrictEqual(recoloredLayers.find(e => e.id === id).rgba, rawLayers.find(e => e.id === id).rgba, 'Color input never edits another layer');
    const newBlue = recoloredLayers.find(e => e.id === blueLayer).rgba; assert.notDeepStrictEqual(newBlue, blueRaw);
    for (let i = 0; i < blueRaw.length; i += 4) { assert.equal(newBlue[i + 3], blueRaw[i + 3]); if (!blueRaw[i + 3]) assert.deepStrictEqual(newBlue.slice(i, i + 4), blueRaw.slice(i, i + 4)); }
    await assertImage(page, composite(redFlatten, newBlue, .5), 'Active-layer color adjustment still composites the full stack');
    await shortcut(page, 'Control+z'); await page.evaluate(() => ModelViewer.getTextureTools().setTab('paint')); await assertImage(page, expected, 'Undo restores active-layer color adjustment');
    report.cases.push({ name: 'OKLCH color input changes only active layer, preserves other layers/alpha, and full stack remains live in 3D' });
    await page.evaluate(() => ModelViewer.getTextureTools().setExpanded(false)); const pngResponse = response(page, '/api/texture/editor/save'); await (await show(page, '#viewer-texture-export')).click(); const pngSaved = await (await pngResponse).json(); assert.deepStrictEqual(decodeFile(pngSaved.path).rgba, expected, 'PNG export flattens visible layers only'); assert(pngSaved.url.startsWith('/api/download?'));
    await field(page, '#viewer-mod-name', 'Layer QA', 'change'); await (await show(page, '#viewer-mod-thumbnail-mode')).selectOption('texture'); await (await show(page, '#viewer-save-mod')).click(); await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.modPackage && p.modPackage.packagePath); }); const persistence = await page.evaluate(() => ModelViewer.getState().persistence); assert(!persistence.error, persistence.error); assert.deepStrictEqual(bundlePixels(persistence.modPackage.packagePath).find(t => t.name === 'ch0001_co0001_body').rgba, expected, 'Actual Mod ZIP keeps the flattened visible stack');
    report.cases.push({ name: 'lossless persisted HTTP PNG and actual Mod ZIP serialize visible-layer composite', pngSaved, packagePath: persistence.modPackage.packagePath });
    const rawStack = await page.evaluate(() => { const p = ModelViewer.getTextureTools().getProject(); return { ...p, layers: p.layers.map(layer => ({ ...layer, image: { width: layer.image.width, height: layer.image.height, rgba: Array.from(layer.image.data) } })) }; });
    await page.evaluate(() => { window.__heldLayerCheckpoint = ModelViewer.captureCheckpoint(); });
    await fill(page, blueRect, '#20e060'); await field(page, '#viewer-texture-layer-name', 'Changed after checkpoint', 'change');
    assert.notDeepStrictEqual((await state(page)).selection.layers, metadata, 'Post-checkpoint UI changes are real');
    await page.evaluate(() => ModelViewer.restoreCheckpoint(window.__heldLayerCheckpoint)); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); await idle(page);
    const restoredCheckpointStack = await page.evaluate(() => { window.__heldLayerCheckpoint = null; const p = ModelViewer.getTextureTools().getProject(); return { ...p, layers: p.layers.map(layer => ({ ...layer, image: { width: layer.image.width, height: layer.image.height, rgba: Array.from(layer.image.data) } })) }; });
    assert.deepStrictEqual(restoredCheckpointStack, rawStack, 'Held public checkpoint owns raw pixel buffers and restores the exact old layer stack after later painting/renaming'); assert.equal((await state(page)).sourceSha256, sourceTextureSHA); await assertImage(page, expected, 'Public checkpoint restores original layer appearance');
    report.cases.push({ name: 'public captureCheckpoint → later repaint/rename → restoreCheckpoint retains independent exact old layers' });
    await page.evaluate(file => ModelViewer.addMotion([file]), motion); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); await idle(page);
    assert((await page.evaluate(() => ModelViewer.getState().loadedMotionPaths)).includes(motion), 'The real clip file entered the motion library');
    const afterMotionStack = await page.evaluate(() => { const p = ModelViewer.getTextureTools().getProject(); return { ...p, layers: p.layers.map(layer => ({ ...layer, image: { width: layer.image.width, height: layer.image.height, rgba: Array.from(layer.image.data) } })) }; });
    assert.deepStrictEqual(afterMotionStack, rawStack, 'Actual motion-import model reload retains full editable layers and exact RGBA'); assert.equal((await state(page)).sourceSha256, sourceTextureSHA); await assertImage(page, expected, 'Motion import retains layered 3D texture');
    report.cases.push({ name: 'actual native AnimationClip import reload retains hidden/visible layers, source SHA, active layer and exact RGBA' });
    await (await show(page, '#viewer-save')).click(); await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.recipePath); }); assert(!(await page.evaluate(() => ModelViewer.getState().persistence.error)));
    await (await show(page, '#viewer-open-saved')).click(); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved && !ModelViewer.getState().persistence.busy);
    assert(await page.locator('#viewer-save').isDisabled(), 'Saved-copy review stays read-only');
    await (await show(page, '#viewer-reedit-original')).click(); await page.waitForFunction(() => { const s = ModelViewer.getState(), t = ModelViewer.getTextureTools().getState(); return s.loaded && !s.loading && !s.persistence.reviewingSaved && !s.persistence.busy && t.selection && t.selection.layers.length === 4; }); await idle(page);
    const returnedStack = await page.evaluate(() => { const p = ModelViewer.getTextureTools().getProject(); return { ...p, layers: p.layers.map(layer => ({ ...layer, image: { width: layer.image.width, height: layer.image.height, rgba: Array.from(layer.image.data) } })) }; });
    assert.deepStrictEqual(returnedStack, rawStack, 'Saved-copy review → source re-edit retains the full editable hidden/visible layer stack, active layer, names, order, opacity and every RGBA byte'); assert.equal((await state(page)).sourceSha256, sourceTextureSHA); await assertImage(page, expected, 'Source re-edit restores full layered 3D appearance');
    report.cases.push({ name: 'actual saved-copy review → Re-edit original retains full editable layers instead of replacing them with flattened recipe', layerCount: returnedStack.layers.length, sourceTextureSHA });
    mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A; wv) AppleWebKit/537.36 Version/4.0 Chrome/132.0.0.0 Mobile Safari/537.36' }); const m = await mobile.newPage(); await setup(m, errors, false); assert((await state(m)).standalone); assert.equal(await m.evaluate(() => ModelViewer.getState().loaded), false);
    await m.evaluate(() => ModelViewer.getTextureTools().setExpanded(true)); const mobileHit = await openProjectPicker(m, saved.saved.path); assert(mobileHit.expanded); assert.deepStrictEqual((await state(m)).selection.layers, metadata);
    for (const id of ['#viewer-texture-project-open', '#viewer-texture-project-save', '#viewer-texture-layer-add', '#viewer-texture-copy', '#viewer-texture-paint-tool']) { const control = await show(m, id); assert(await control.isVisible()); const rect = await control.boundingBox(); assert(rect.x >= 0 && rect.x + rect.width <= 391, 'Mobile layer control stays within viewport: ' + id); assert(await control.evaluate(e => { const r = e.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return hit === e || e.contains(hit); }), 'Mobile layer control is reachable: ' + id); }
    const urlBefore = m.url(), dataNavigations = []; m.on('framenavigated', frame => { if (/^data:/.test(frame.url())) dataNavigations.push(frame.url().slice(0, 40)); }); const mobilePNGResponse = response(m, '/api/texture/editor/save'); await (await show(m, '#viewer-texture-export')).click(); const mobilePNG = await (await mobilePNGResponse).json(); assert.deepStrictEqual(decodeFile(mobilePNG.path).rgba, expected); assert.equal(m.url(), urlBefore); assert.deepStrictEqual(dataNavigations, []); assert((await state(m)).expanded && (await state(m)).standalone); assert((await m.locator('#viewer-texture-download').getAttribute('href')).startsWith('/api/download?'));
    await m.screenshot({ path: path.join(evidence, '03-mobile-project-editor.png') }); report.cases.push({ name: 'no-model Android-WebView-style mobile project reopen, reachable expanded controls, HTTP PNG without data-URL navigation', mobileHit, mobilePNG });
    assert.deepStrictEqual(errors, []); assert.equal(sha(fs.readFileSync(source)), sourceSHA, 'Every action leaves original Unity source intact'); report.sourceAfter = sourceHashes(); assert.deepStrictEqual(report.sourceAfter, report.sourceBefore, 'Product files changed during QA; rerun one final version'); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); report.pageErrors = errors; if (page) { report.failureState = await state(page).catch(() => null); await page.screenshot({ path: path.join(evidence, 'failure.png') }).catch(() => {}); } throw error; }
  finally { fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); if (mobile) await mobile.close(); if (desktop) await desktop.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence })); }
}
if (require.main === module) run().catch(error => { console.error(error.stack); process.exitCode = 1; });
