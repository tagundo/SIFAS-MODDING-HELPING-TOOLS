/* Actual production page + UnityFS + Chromium: legacy UV/image workspaces. */
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-panel-expand-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-panel-library-'));
const models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'wearer.unity'), donor = path.join(models, 'donor.unity');
const generated = spawnSync(python, ['-B', '-c', `import sys,struct,UnityPy
from pathlib import Path
from test_viewer_transplants import costume_fixture
env=UnityPy.load(costume_fixture())
mesh=next(obj for obj in env.objects if obj.type.name=='Mesh')
tree=mesh.read_typetree();vertex=tree['m_VertexData'];count=vertex['m_VertexCount'];raw=bytearray(vertex['m_DataSize']);start=(count*28+15)//16*16
for index in range(count):struct.pack_into('<2f',raw,start+index*8,*[(.25,.25),(.75,.25),(.5,.75)][index%3])
vertex['m_DataSize']=bytes(raw);mesh.save_typetree(tree)
raw=env.file.save();Path(sys.argv[1]).write_bytes(raw);Path(sys.argv[2]).write_bytes(raw)`, source, donor],
  { cwd: product, encoding: 'utf8', env: { ...process.env, PYTHONPATH: product + path.delimiter + __dirname } });
assert.equal(generated.status, 0, generated.stderr);
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const before = { source: hash(source), donor: hash(donor) };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let server, browser;
const report = { status: 'RUNNING', evidence, scope: 'Production index, real HTTP/UnityFS/WebGL, desktop and mobile; native popover and legacy fallback', cases: [] };
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); }
  throw Error('Product server did not start');
}
async function meshState(page) { return page.evaluate(() => ModelViewer.getState().meshTools); }
async function expand(page, selector, fallback, label) {
  const pane = page.locator(selector), button = pane.locator('.texture-pane-expand-button');
  await button.scrollIntoViewIfNeeded(); await button.focus();
  const originalCanvas = await pane.locator('canvas').count() ? await pane.locator('canvas').evaluate(e => { window.__expandedCanvas = e; return { width: e.width, css: e.getBoundingClientRect().width }; }) : null;
  const buttonSize = await button.boundingBox(); assert(buttonSize.height <= 46, label + ': compact, accessible control');
  await button.click(); await page.waitForFunction(() => !!TexturePanelExpand.getState().expanded);
  await page.waitForTimeout(180);
  const geometry = await pane.evaluate(node => {
    const rect = node.getBoundingClientRect(), canvas = node.querySelector('canvas'), button = node.querySelector('.texture-pane-expand-button'), b = button.getBoundingClientRect();
    const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, vw: innerWidth, vh: innerHeight,
      topLayer: TexturePanelExpand.getState().topLayer, hit: hit === button || button.contains(hit), aria: button.getAttribute('aria-expanded'),
      sameCanvas: !canvas || canvas === window.__expandedCanvas, bitmap: canvas && canvas.width, canvasCSS: canvas && canvas.getBoundingClientRect().width,
      dpr: devicePixelRatio, bodyOverflow: document.body.style.overflow };
  });
  assert(geometry.x >= -1 && geometry.y >= -1 && geometry.x + geometry.width <= geometry.vw + 1 && geometry.y + geometry.height <= geometry.vh + 1, label + ': pane fits visible viewport');
  assert(geometry.hit, label + ': Restore button is actually clickable above other panels');
  assert.equal(geometry.aria, 'true'); assert.equal(geometry.topLayer, !fallback); assert.equal(geometry.sameCanvas, true); assert.equal(geometry.bodyOverflow, 'hidden');
  if (geometry.bitmap) {
    const expected = Math.min(2048, Math.max(128, Math.round(geometry.canvasCSS * Math.min(2, geometry.dpr))));
    assert(Math.abs(geometry.bitmap - expected) <= 1, label + ': backing bitmap follows DPR and visible size');
    assert(geometry.canvasCSS > originalCanvas.css + 1, label + ': canvas gains usable viewport space ' + JSON.stringify({ originalCanvas, geometry }));
  }
  return geometry;
}
async function escape(page, selector) {
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !TexturePanelExpand.getState().expanded); await page.waitForTimeout(80);
  assert.equal(await page.locator(selector + ' .texture-pane-expand-button').getAttribute('aria-expanded'), 'false');
  assert(await page.locator(selector + ' .texture-pane-expand-button').evaluate(e => document.activeElement === e), 'Escape restores the invoking button focus');
  assert.equal(await page.evaluate(() => document.body.style.overflow), '');
  assert.equal(await page.locator('.texture-pane-overlay-path').count(), 0, 'Fallback stacking path is restored');
  assert.equal(await page.locator(selector).getAttribute('popover'), null, 'Original popover attribute restored');
}
async function hitCanvas(page, selector, uv) {
  const canvas = page.locator(selector + ' canvas'); await canvas.scrollIntoViewIfNeeded();
  const b = await canvas.boundingBox(), point = { x: b.x + uv[0] * b.width, y: b.y + (1 - uv[1]) * b.height };
  const hit = await canvas.evaluate((e, p) => { const hit = document.elementFromPoint(p.x, p.y); return { correct: hit === e, tag: hit && hit.tagName, id: hit && hit.id, cls: hit && hit.className, rect: e.getBoundingClientRect().toJSON(), point: p }; }, point);
  assert(hit.correct, 'Canvas pointer target is not occluded: ' + JSON.stringify(hit));
  await page.mouse.move(point.x, point.y); return point;
}
async function runCase(name, viewport, fallback) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: viewport.width < 600 ? 2 : 1.5, isMobile: viewport.width < 600, hasTouch: viewport.width < 600 });
  try {
    if (fallback) await context.addInitScript(() => { Object.defineProperty(HTMLElement.prototype, 'showPopover', { configurable: true, value: undefined }); Object.defineProperty(HTMLElement.prototype, 'hidePopover', { configurable: true, value: undefined }); });
    const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.setDefaultTimeout(45000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function' && window.TexturePanelExpand);
    await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    const del = '#viewer-mesh-deleter'; await page.locator(del).evaluate(e => { e.open = true; });
    const listingResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect')); await page.locator(del + '-load').click();
    const listing = await (await listingResponse).json(), chosen = listing.meshes.find(m => m.available && m.name === 'Body') || listing.meshes.find(m => m.available), value = JSON.stringify(chosen.mesh);
    const dataResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/data')); await page.locator(del + '-select').selectOption(value); const data = await (await dataResponse).json();
    await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
    const face = data.triangles[0], uv = [0, 1].map(axis => face.reduce((n, v) => n + data.uv[v][axis], 0) / 3);
    const deletionGeometry = await expand(page, del, fallback, name + ' mesh delete');
    const point = await hitCanvas(page, del, uv); const cursor = page.locator('#viewer-mesh-uv-cursor');
    assert(await cursor.isVisible()); const radius = +await page.locator(del + '-radius').inputValue();
    assert.equal(Math.round((await cursor.boundingBox()).width), radius * 2, 'Brush diameter remains CSS pixels after DPR resize');
    assert(await cursor.evaluate(e => !!e.closest('.texture-pane-expanded')), 'Brush cursor belongs to the top layer');
    await page.mouse.down(); await page.mouse.up(); let selected = await meshState(page); assert(selected.selectedFaces.length > 0, 'Enlarged UV pointer coordinates select real faces');
    await page.locator(del + '-zoom-in').click(); assert((await meshState(page)).textureViews.find(v => v.panel === 'viewer-mesh-deleter').zoom > 1, 'Existing UV zoom still works');
    const marked = (await meshState(page)).selectedFaces; await page.screenshot({ path: path.join(evidence, name + '-mesh-delete.png') });
    await escape(page, del); assert.deepStrictEqual((await meshState(page)).selectedFaces, marked, 'Collapsing retains exact selection and undo state');
    await page.locator(del + '-fit-texture').click(); await page.locator(del).getByRole('button', { name: 'Clear selection', exact: true }).click();
    const modify = '#viewer-mesh-modify'; await page.locator(modify).evaluate(e => { e.open = true; }); await page.locator(modify + '-select').selectOption(value);
    const modificationGeometry = await expand(page, modify, fallback, name + ' mesh modify'); await hitCanvas(page, modify, data.uv[face[0]]); await page.mouse.down(); await page.mouse.up();
    assert((await meshState(page)).selectedVertices.length > 0, 'Enlarged mesh modify selects actual original vertices');
    const vertices = (await meshState(page)).selectedVertices; await escape(page, modify); assert.deepStrictEqual((await meshState(page)).selectedVertices, vertices);
    await page.locator(modify).getByRole('button', { name: 'Clear selection', exact: true }).click();
    const part = page.locator('#viewer-part-transplant'); await part.evaluate(e => { e.open = true; });
    const donorResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/transplant/inspect'));
    await part.getByRole('button', { name: 'Choose donor costume', exact: true }).click(); await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
    const inspected = await (await donorResponse).json(); await part.locator('.viewer-transplant-stage canvas').waitFor({ state: 'visible' });
    await page.locator('#viewer-part-transplant-selection-mode').selectOption('triangles'); await part.locator('.viewer-transplant-texture-panel').waitFor({ state: 'visible' });
    const donorPane = '.viewer-transplant-texture-panel'; const donorGeometry = await expand(page, donorPane, fallback, name + ' donor texture');
    assert(inspected.geometry.triangles.length > 0, 'The donor inspector returned real geometry');
    // Both immutable fixture files contain the same source UVs; the donor's
    // independently prepared GLTF must map this exact texture coordinate too.
    const donorUV = uv;
    const donorPoint = await hitCanvas(page, donorPane, donorUV); await page.mouse.down(); await page.mouse.up();
    const donorState = await page.evaluate(() => ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'));
    assert(donorState.selectedTriangles > 0, 'Donor texture enlarged pointer selects actual donor faces');
    await page.locator('#viewer-part-transplant-texture-zoom').fill('2'); await page.locator('#viewer-part-transplant-texture-zoom').dispatchEvent('input');
    assert.equal((await page.evaluate(() => ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'))).textureView.zoom, 2);
    await page.screenshot({ path: path.join(evidence, name + '-donor.png') }); await page.keyboard.press('Escape'); await page.waitForFunction(() => !TexturePanelExpand.getState().expanded);
    assert.deepStrictEqual((await page.evaluate(() => ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'))).selectedFaces, donorState.selectedFaces);
    await page.evaluate(folder => { switchTab('tools'); selectTool('texture_previews'); document.getElementById('gallery-path').value = folder; }, models);
    await page.locator('#gallery-load').click(); const card = page.locator('#gallery-grid .gcard').filter({ hasText: 'donor.unity' });
    await card.locator('img').waitFor({ state: 'visible' }); await page.waitForFunction(() => Array.from(document.querySelectorAll('#gallery-grid .gcard img')).some(e => e.naturalWidth > 0));
    const cardId = await card.getAttribute('id'); await page.waitForFunction(() => TexturePanelExpand.getState().registered.some(id => id.startsWith('legacy-texture-pane-')));
    const actualId = cardId || await card.getAttribute('id'), gallerySelector = '#' + actualId;
    const galleryGeometry = await expand(page, gallerySelector, fallback, name + ' texture preview');
    assert(await card.locator('.cap').isVisible()); assert(await card.locator('.gallery-view-model').isVisible());
    const imgBounds = await card.locator('img').boundingBox(); assert(imgBounds.width > 200 && imgBounds.height > 100, 'Gallery image uses the large workspace');
    await page.screenshot({ path: path.join(evidence, name + '-gallery.png') }); await escape(page, gallerySelector);
    await card.locator('.texture-pane-expand-button').click(); await card.locator('.gallery-view-model').click();
    await page.waitForFunction(() => !TexturePanelExpand.getState().expanded && ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    assert.equal(await page.evaluate(() => document.body.style.overflow), '', 'View in 3D dismisses gallery overlay');
    assert.equal(await page.locator('.texture-pane-overlay-path').count(), 0); assert.deepStrictEqual(errors, [], 'No browser exceptions');
    report.cases.push({ name, fallback, viewport, deletionGeometry, modificationGeometry, donorGeometry, galleryGeometry, meshSelectedFaces: selected.selectedFaces, donorSelectedFaces: donorState.selectedFaces, point, donorPoint });
  } finally { await context.close(); }
}
async function run() {
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const [name, viewport, fallback] of [['desktop-popover', { width: 1280, height: 1000 }, false], ['mobile-popover', { width: 385, height: 800 }, false], ['desktop-fallback', { width: 1280, height: 1000 }, true], ['mobile-fallback', { width: 385, height: 800 }, true]]) await runCase(name, viewport, fallback);
    assert.equal(hash(source), before.source); assert.equal(hash(donor), before.donor); report.sourceSha256 = before; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); }
}
if (require.main === module) run().catch(() => { process.exitCode = 1; });
