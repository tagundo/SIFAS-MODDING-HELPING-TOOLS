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
const sourcePaths=['viewer-mesh-tools.js','viewer-transplants.js','texture-panel-expand.js','texture-panel-expand.css'].map(name=>path.join(product,'webtools/web/static',name));
const sourceHashes=()=>Object.fromEntries(sourcePaths.map(file=>[file,hash(file)])); const sourceBefore=sourceHashes();
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
async function cardLayoutRegression(page, viewport) {
  const result = { cards: [], width: null };
  for (const selector of ['#viewer-mesh-deleter', '#viewer-mesh-modify']) {
    const pane = page.locator(selector);
    await pane.evaluate(node => { node.open = false; });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const closed = await pane.evaluate(node => {
      const summary = node.querySelector('summary'), root = node.getBoundingClientRect(), row = summary.getBoundingClientRect();
      return { height: root.height, summaryHeight: row.height, bottom: root.bottom, summaryBottom: row.bottom,
        summaryButtons: summary.querySelectorAll('button').length, overflow: node.scrollWidth - node.clientWidth };
    });
    assert.equal(closed.summaryButtons, 0, 'Closed UV cards keep only their compact title in the summary');
    assert(closed.summaryBottom <= closed.bottom + 1 && closed.height <= closed.summaryHeight + 3,
      'Closed UV card title stays inside its own row without a floating enlarge button: ' + JSON.stringify(closed));
    assert(closed.overflow <= 1, 'Closed UV cards do not create intrinsic horizontal overflow');
    await pane.evaluate(node => { node.open = true; });
    const button = pane.locator('.texture-pane-expand-button'); await button.scrollIntoViewIfNeeded();
    const open = await pane.evaluate(node => {
      const button = node.querySelector('.texture-pane-expand-button'), rect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return { inViewbar: !!button.closest('.uv-edit-viewbar'), hasIcon: !!button.querySelector('svg'),
        width: rect.width, height: rect.height, hit: hit === button || button.contains(hit),
        overflow: node.scrollWidth - node.clientWidth, label: button.getAttribute('aria-label') };
    });
    assert(open.inViewbar && open.hasIcon && open.hit && open.width <= 46 && open.height <= 46,
      'Enlarge is a compact accessible icon beside the actual texture view controls: ' + JSON.stringify(open));
    assert(open.overflow <= 1, 'Open UV cards do not force the inspector wider than its selected width');
    result.cards.push({ selector, closed, open });
  }
  await page.locator('#lang-select').selectOption('ko');
  await page.waitForFunction(() => document.querySelector('#viewer-mesh-modify .texture-pane-expand-button').getAttribute('aria-label') === '텍스처 크게 보기');
  result.koreanLabel = await page.locator('#viewer-mesh-modify .texture-pane-expand-button').getAttribute('aria-label');
  await page.locator('#lang-select').selectOption('en');
  await page.waitForFunction(() => document.querySelector('#viewer-mesh-modify .texture-pane-expand-button').getAttribute('aria-label') === 'Enlarge texture');
  await page.locator('#viewer-mesh-modify').evaluate(node => { node.open = false; });
  if (viewport.width >= 1000 && viewport.height >= 700) {
    await page.setViewportSize({ width: 1600, height: 1000 });
    const splitter = page.locator('#viewer-panel-resizer'); await splitter.waitFor({ state: 'visible' }); await splitter.press('Home');
    await page.waitForFunction(() => Number(document.getElementById('viewer-panel-resizer').getAttribute('aria-valuemax')) > 800);
    const before = await page.locator('#viewer-mesh-deleter canvas').evaluate(canvas => {
      window.__uvWidthCanvas = canvas;
      return { canvas: canvas.getBoundingClientRect().width, authoring: ModelViewer.getAuthoringState(), selected: ModelViewer.getState().meshTools.selectedFaces };
    });
    const handle = await splitter.boundingBox(), point = { x: handle.x + handle.width / 2, y: handle.y + handle.height / 2 };
    assert(await splitter.evaluate((node, p) => { const hit = document.elementFromPoint(p.x, p.y); return hit === node || node.contains(hit); }, point),
      'Actual inspector divider is reachable beside open UV editing cards');
    await page.mouse.move(point.x, point.y); await page.mouse.down();
    await page.mouse.move(point.x - 500, point.y, { steps: 12 }); await page.mouse.up();
    await page.waitForFunction(() => document.getElementById('viewer-control-panel').getBoundingClientRect().width > 700);
    await splitter.press('Shift+ArrowLeft');
    await page.waitForFunction(() => document.querySelector('#viewer-mesh-deleter canvas').getBoundingClientRect().width > 700);
    await page.waitForFunction(() => {
      const node = document.getElementById('viewer-mesh-deleter'), canvas = node.querySelector('canvas'), stage = node.querySelector('.uv-canvas-stage');
      return Math.abs(canvas.getBoundingClientRect().width - stage.getBoundingClientRect().width) <= 2;
    }, null, { timeout: 3000 });
    const widened = await page.locator('#viewer-mesh-deleter').evaluate(node => {
      const canvas = node.querySelector('canvas'), stage = node.querySelector('.uv-canvas-stage'), panel = document.getElementById('viewer-control-panel');
      return { panelWidth: panel.getBoundingClientRect().width, modelWidth: document.getElementById('viewer-stage').getBoundingClientRect().width,
        stageWidth: stage.getBoundingClientRect().width, canvasWidth: canvas.getBoundingClientRect().width,
        sameCanvas: canvas === window.__uvWidthCanvas, overflow: panel.scrollWidth - panel.clientWidth,
        authoring: ModelViewer.getAuthoringState(), selected: ModelViewer.getState().meshTools.selectedFaces };
    });
    assert(widened.panelWidth > 640 && widened.modelWidth >= 319 && widened.canvasWidth > before.canvas + 100,
      'Dragging the actual right-pane divider gives its added width to the texture, while preserving the model: ' + JSON.stringify(widened));
    assert(Math.abs(widened.canvasWidth - widened.stageWidth) <= 2 && widened.sameCanvas && widened.overflow <= 1,
      'Automatic square texture view follows the widened pane rather than a fixed canvas cap: ' + JSON.stringify(widened));
    assert.deepStrictEqual(widened.authoring, before.authoring); assert.deepStrictEqual(widened.selected, before.selected);
    result.width = { before, widened };
    await splitter.press('Home'); await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  return result;
}
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
    if (!(geometry.canvasCSS > originalCanvas.css + 1)) {
      const debug=await pane.evaluate(root=>[root,...root.querySelectorAll('.uv-edit-workspace,.uv-edit-main,.uv-canvas-stage,.uv-edit-source,.uv-edit-toolbar,.uv-edit-viewbar,.uv-edit-footer,.uv-edit-inspector,canvas')].map(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);return {node:n.className||n.tagName,rect:r.toJSON(),display:s.display,flex:s.flex,grid:s.gridTemplateRows,height:s.height,maxHeight:s.maxHeight,width:s.width,inline:n.style.cssText};}));
      fs.writeFileSync(path.join(evidence,'failure-layout.json'),JSON.stringify(debug,null,2)); await page.screenshot({path:path.join(evidence,'failure.png')});
    }
    assert(geometry.canvasCSS > originalCanvas.css + 1, label + ': canvas gains usable viewport space ' + JSON.stringify({ originalCanvas, geometry }));
  }
  if (await pane.locator('.uv-edit-workspace').count()) {
    geometry.workspace = await pane.evaluate(root => {
      const c=root.querySelector('canvas').getBoundingClientRect(), t=root.querySelector('.uv-edit-toolbar').getBoundingClientRect();
      return {canvas:{x:c.x,y:c.y,width:c.width,height:c.height,bottom:c.bottom,right:c.right}, toolbar:{x:t.x,right:t.right,y:t.y,bottom:t.bottom,height:t.height}, viewport:{width:innerWidth,height:innerHeight}};
    });
    assert(geometry.workspace.canvas.bottom <= geometry.workspace.viewport.height + 1, label + ': whole canvas stays visible');
    assert(geometry.workspace.canvas.right <= geometry.workspace.viewport.width + 1, label + ': canvas fits viewport width');
    if (geometry.workspace.viewport.height < 500) assert(geometry.workspace.canvas.height >= 160, label + ': short screen keeps a usable texture canvas');
    assert((geometry.workspace.canvas.y >= geometry.workspace.toolbar.bottom - 1 && geometry.workspace.canvas.y-geometry.workspace.toolbar.bottom < 18) || (geometry.workspace.canvas.x >= geometry.workspace.toolbar.right-1 && geometry.workspace.canvas.x-geometry.workspace.toolbar.right < 18), label + ': tools are directly above or beside canvas');
  }
  return geometry;
}
async function escape(page, selector) {
  await page.keyboard.press('Escape'); await page.waitForFunction(() => !TexturePanelExpand.getState().expanded); await page.waitForFunction(selector => document.activeElement === document.querySelector(selector + ' .texture-pane-expand-button'), selector, { timeout: 2000 });
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
  const context = await browser.newContext({ viewport, deviceScaleFactor: (viewport.width < 600 || viewport.height < 500) ? 2 : 1.5, isMobile: (viewport.width < 600 || viewport.height < 500), hasTouch: (viewport.width < 600 || viewport.height < 500) });
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
    const normalLayout = await cardLayoutRegression(page, viewport);
    const face = data.triangles[0], uv = [0, 1].map(axis => face.reduce((n, v) => n + data.uv[v][axis], 0) / 3);
    const resizeHandle=page.locator(del+' .uv-canvas-resizer');
    await page.waitForFunction(selector=>document.querySelector(selector).hasAttribute('aria-valuenow'), del+' .uv-canvas-resizer');
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const initialStage=await page.locator(del+' .uv-canvas-stage').evaluate(e=>e.getBoundingClientRect().height); await resizeHandle.press(initialStage <= 212 ? 'ArrowDown' : 'ArrowUp');
    await page.waitForFunction(value=>Math.abs(document.querySelector(value.selector).getBoundingClientRect().height-value.before)>20, { selector: del+' .uv-canvas-stage', before: initialStage }, { timeout: 3000 });
    const shortenedStage=await page.locator(del+' .uv-canvas-stage').evaluate(e=>e.getBoundingClientRect().height);
    assert(Math.abs(shortenedStage-initialStage)>20, 'Keyboard resize changes the actual texture viewport: '+JSON.stringify({initialStage,shortenedStage,control:await resizeHandle.evaluate(e=>({active:document.activeElement.id,html:e.outerHTML,stage:e.previousElementSibling.style.cssText,expanded:TexturePanelExpand.getState().expanded}))}));
    await resizeHandle.press('Home'); await wait(80);
    const deletionGeometry = await expand(page, del, fallback, name + ' mesh delete');
    const point = await hitCanvas(page, del, uv); const cursor = page.locator('#viewer-mesh-uv-cursor');
    assert(await cursor.isVisible()); const radius = +await page.locator(del + '-radius').inputValue();
    assert.equal(Math.round((await cursor.boundingBox()).width), radius * 2, 'Brush diameter remains CSS pixels after DPR resize');
    assert(await cursor.evaluate(e => !!e.closest('.texture-pane-expanded')), 'Brush cursor belongs to the top layer');
    await page.mouse.down(); await page.mouse.up(); let selected = await meshState(page); assert(selected.selectedFaces.length > 0, 'Enlarged UV pointer coordinates select real faces');
    await page.locator(del+'-canvas').focus(); await page.keyboard.press('v');
    assert.equal((await meshState(page)).textureViews.find(v=>v.panel==='viewer-mesh-deleter').mode,'pan','Canvas shortcut switches to Pan');
    await page.keyboard.press('b'); const oldRadius=Number(await page.locator(del+'-radius').inputValue());
    await page.keyboard.press(']'); assert.equal(Number(await page.locator(del+'-radius').inputValue()),oldRadius+2); await page.keyboard.press('[');
    const beforeModes=await meshState(page); await page.locator(del+'-tool-pan').click();
    assert.equal((await meshState(page)).textureViews.find(v=>v.panel==='viewer-mesh-deleter').mode,'pan');
    await page.locator(del+'-tool-connected').click();
    assert.equal((await meshState(page)).textureViews.find(v=>v.panel==='viewer-mesh-deleter').mode,'connected');
    await page.locator(del+'-tool-paint').click();
    assert.deepStrictEqual((await meshState(page)).selectedFaces,beforeModes.selectedFaces,'Mode switching keeps exact selection');
    await page.locator(del+'-tool-erase').click(); await hitCanvas(page,del,uv); await page.mouse.down(); await page.mouse.up();
    const erased=(await meshState(page)).selectedFaces; assert(erased.length < beforeModes.selectedFaces.length,'Local Erase removes marked faces');
    await page.locator(del+'-undo').click(); assert.deepStrictEqual((await meshState(page)).selectedFaces,beforeModes.selectedFaces,'Local Undo restores exact selection');
    await page.locator(del+'-redo').click(); assert.deepStrictEqual((await meshState(page)).selectedFaces,erased,'Local Redo restores erased selection');
    await page.locator(del+'-undo').click(); await page.locator(del+'-tool-paint').click();
    await page.locator(del+' .uv-selection-menu > summary').click();
    const clearButton=page.locator(del).getByRole('button',{name:'Clear selection',exact:true});
    assert(await clearButton.evaluate(e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return (h===e||e.contains(h))&&r.y>=0&&r.bottom<=innerHeight;}),'Local Selection popup remains hittable in the viewport');
    await clearButton.click(); assert.equal((await meshState(page)).selectedFaces.length,0); await page.locator(del+'-undo').click();
    assert.deepStrictEqual((await meshState(page)).selectedFaces,beforeModes.selectedFaces,'Local Selection menu preserves Undo');


    await page.locator(del + '-zoom-in').click(); assert((await meshState(page)).textureViews.find(v => v.panel === 'viewer-mesh-deleter').zoom > 1, 'Existing UV zoom still works');
    const marked = (await meshState(page)).selectedFaces; await page.screenshot({ path: path.join(evidence, name + '-mesh-delete.png') });
    await escape(page, del); assert.deepStrictEqual((await meshState(page)).selectedFaces, marked, 'Collapsing retains exact selection and undo state');
    await page.locator(del + '-fit-texture').click(); await page.locator(del + ' .uv-selection-menu > summary').click(); await page.locator(del).getByRole('button', { name: 'Clear selection', exact: true }).click();
    const modify = '#viewer-mesh-modify'; await page.locator(modify).evaluate(e => { e.open = true; }); await page.locator(modify + '-select').selectOption(value);
    const modificationGeometry = await expand(page, modify, fallback, name + ' mesh modify'); await hitCanvas(page, modify, data.uv[face[0]]); await page.mouse.down(); await page.mouse.up();
    assert((await meshState(page)).selectedVertices.length > 0, 'Enlarged mesh modify selects actual original vertices');
    const vertices = (await meshState(page)).selectedVertices; await escape(page, modify); assert.deepStrictEqual((await meshState(page)).selectedVertices, vertices);
    await page.locator(modify + ' .uv-selection-menu > summary').click(); await page.locator(modify).getByRole('button', { name: 'Clear selection', exact: true }).click();
    const part = page.locator('#viewer-part-transplant'); await part.evaluate(e => { e.open = true; });
    const donorResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/transplant/inspect'));
    await part.getByRole('button', { name: 'Choose donor costume', exact: true }).click(); await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
    const inspected = await (await donorResponse).json(); await part.locator('.viewer-transplant-stage canvas').waitFor({ state: 'visible' });
    await page.locator('#viewer-part-transplant-selection-mode').selectOption('triangles'); await part.locator('.viewer-transplant-texture-panel').waitFor({ state: 'visible' });
    const donorPane = '.viewer-transplant-texture-panel'; const donorGeometry = await expand(page, donorPane, fallback, name + ' donor texture');
    await page.locator('#viewer-part-transplant-texture').focus(); await page.keyboard.press('v');
    assert(await page.locator('#viewer-part-transplant-texture-pan').isChecked(),'Donor canvas shortcut switches to Pan'); await page.keyboard.press('b');
    await page.locator(donorPane+' [data-donor-tool=pan]').click();
    assert(await page.locator('#viewer-part-transplant-texture-pan').isChecked(),'Local donor Pan tool changes actual interaction mode');
    await page.locator(donorPane+' [data-donor-tool=paint]').click();
    assert(!await page.locator('#viewer-part-transplant-texture-pan').isChecked());

    assert(inspected.geometry.triangles.length > 0, 'The donor inspector returned real geometry');
    // Both immutable fixture files contain the same source UVs; the donor's
    // independently prepared GLTF must map this exact texture coordinate too.
    const donorUV = uv;
    const donorPoint = await hitCanvas(page, donorPane, donorUV); await page.mouse.down(); await page.mouse.up();
    const donorState = await page.evaluate(() => ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'));
    assert(donorState.selectedTriangles > 0, 'Donor texture enlarged pointer selects actual donor faces');
    await page.locator('#viewer-part-transplant-texture-pane [data-uv-settings]').click();
    await page.locator('#viewer-part-transplant-texture-zoom').fill('2'); await page.locator('#viewer-part-transplant-texture-zoom').dispatchEvent('input');
    assert.equal((await page.evaluate(() => ModelViewer.getState().transplants.donors.find(e => e.operation === 'part'))).textureView.zoom, 2);
    await page.locator('#viewer-part-transplant-texture-pane .uv-inspector-heading > button').click();
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
    report.cases.push({ name, fallback, viewport, normalLayout, deletionGeometry, modificationGeometry, donorGeometry, galleryGeometry, meshSelectedFaces: selected.selectedFaces, donorSelectedFaces: donorState.selectedFaces, point, donorPoint });
  } finally { await context.close(); }
}
async function run() {
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const [name, viewport, fallback] of [['desktop-popover', { width: 1280, height: 1000 }, false], ['mobile-popover', { width: 385, height: 800 }, false], ['desktop-fallback', { width: 1280, height: 1000 }, true], ['mobile-fallback', { width: 385, height: 800 }, true], ['landscape-popover', { width: 800, height: 385 }, false], ['landscape-fallback', { width: 800, height: 385 }, true]]) await runCase(name, viewport, fallback);
    assert.equal(hash(source), before.source); assert.equal(hash(donor), before.donor); report.sourceSha256 = before; assert.deepStrictEqual(sourceHashes(),sourceBefore,'Owned UI source stays frozen during the run'); report.productSourceSha256=sourceBefore; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({status:report.status,cases:report.cases.length,error:report.error,evidence:report.evidence})); }
}
if (require.main === module) run().catch(() => { process.exitCode = 1; });
