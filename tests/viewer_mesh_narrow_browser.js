/* Real mobile visual viewport, long mesh names and source-bound view state. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-narrow-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-narrow-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_rig.unity'));
const names = ['viewer-rig-qa-724626505937.unity', 'viewer-rig-qa-' + 'longvalidfilename'.repeat(8) + '.unity'];
const sources = names.map(name => { const filename = path.join(models, name); fs.writeFileSync(filename, raw); return filename; });
const sha = value => crypto.createHash('sha256').update(value).digest('hex'), sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, stream }; } catch (_) {} await sleep(100); }
  child.kill(); throw new Error('Product server did not start');
}
async function state(page) {
  return page.evaluate(() => {
    const s = ModelViewer.getState(), mesh = s.meshTools;
    return { modelId: s.modelId, authoring: ModelViewer.getAuthoringState(), fingerprint: ModelViewer.getEditingMetadata().sourceFingerprint,
      selectedFaces: mesh.selectedFaces, selectedVertices: mesh.selectedVertices, history: mesh.history, future: mesh.future, views: mesh.textureViews, edits: mesh.edits,
      geometry: mesh.runtime.bindings.map(b => ({ mesh: b.mesh, submesh: b.submesh, triangles: b.triangles, positions: b.samplePositions, weights: b.sampleWeights })) };
  });
}
async function rectangles(page, tool) {
  return page.evaluate(tool => {
    const panel = document.getElementById('viewer-mesh-' + tool), viewport = window.visualViewport;
    const viewportLeft = viewport ? viewport.offsetLeft : 0, viewportWidth = viewport ? viewport.width : document.documentElement.clientWidth;
    return { width: viewportWidth, viewportLeft, innerWidth, documentWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth,
      compact: ModelViewer.getState().layout.compactControls,
      controls: Array.from(panel.querySelectorAll('select,input[type=number],input[type=range],button,canvas')).filter(e => e.getBoundingClientRect().width > 0).map(e => {
        const r = e.getBoundingClientRect(), style = getComputedStyle(e);
        return { id: e.id || '', type: e.type || e.tagName, left: r.left, right: r.right, width: r.width, height: r.height, font: style.font,
          text: e.tagName === 'SELECT' && e.selectedOptions[0] ? e.selectedOptions[0].textContent : e.textContent };
      }) };
  }, tool);
}
function fits(measurement) {
  assert(Math.abs(measurement.width - 360) < .1, 'use physical visualViewport width, not overflow-expanded innerWidth');
  assert(measurement.documentWidth <= measurement.clientWidth + 1, 'mesh controls must not widen the page');
  measurement.controls.forEach(c => { assert(c.width > 0 && c.left >= measurement.viewportLeft - 1 && c.right <= measurement.viewportLeft + measurement.width + 1, 'control fits actual mobile width: ' + JSON.stringify(c)); });
}
async function main() {
  const report = { status: 'RUNNING', evidence, viewport: { width: 360, height: 456 }, cases: [] }; let server, browser, context;
  try {
    server = await startServer(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: report.viewport, isMobile: true, hasTouch: true, deviceScaleFactor: 1 }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    for (const source of sources) {
      await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      await page.locator('#viewer-mesh-modify').evaluate(e => { e.open = true; });
      const listingResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect')); await page.locator('#viewer-mesh-modify-load').click(); const listing = await (await listingResponse).json();
      const mesh = JSON.stringify(listing.meshes.find(m => m.available).mesh); await page.locator('#viewer-mesh-modify-select').selectOption(mesh); await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy);
      await page.locator('#viewer-mesh-deleter').evaluate(e => { e.open = true; }); await page.locator('#viewer-mesh-deleter-select').selectOption(mesh);
      await page.locator('#viewer-mesh-modify-zoom').evaluate(e => { e.value = '4'; e.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.locator('#viewer-mesh-deleter-zoom').evaluate(e => { e.value = '2'; e.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.locator('#viewer-mesh-modify-select-vertex').click(); const selected = await state(page); assert.deepStrictEqual(selected.selectedVertices, [0]);
      await page.locator('#viewer-mesh-modify-connected').click(); assert.deepStrictEqual((await state(page)).selectedVertices.slice().sort(), [0, 1, 2, 3, 4, 5]);
      await page.locator('#viewer-mesh-modify-undo').click(); const before = await state(page); assert.deepStrictEqual(before.selectedVertices, [0]);
      // This browser-only legacy rule reproduces the old automatic flex minimum
      // without changing a filename, source file, device width or success API.
      const legacy = await page.addStyleTag({ content: '.viewer-mesh-tools .mesh-row>label{min-width:auto!important;max-width:none!important}' });
      await page.waitForTimeout(50); const broken = await rectangles(page, 'modify');
      const brokenSelect = broken.controls.find(c => c.id === 'viewer-mesh-modify-select'); assert(brokenSelect.right > broken.viewportLeft + broken.width + 1, 'the pre-fix label minimum really overflows the same360px viewport');
      await legacy.evaluate(e => e.remove()); await page.waitForTimeout(50);
      const recovered = await rectangles(page, 'modify'); fits(recovered);
      assert.deepStrictEqual(await state(page), before, 'CSS layout recovery changes neither selection/Undo nor authored/actual geometry');
      const variants = [];
      for (const font of [null, 14, 16]) {
        const fontStyle = font === null ? null : await page.addStyleTag({ content: '.viewer-mesh-tools select{font-size:' + font + 'px}' });
        await page.waitForTimeout(50);
        for (const tool of ['deleter', 'modify']) { const geometry = await rectangles(page, tool); fits(geometry); variants.push({ tool, font, geometry }); }
        if (fontStyle) await fontStyle.evaluate(e => e.remove());
      }
      assert.deepStrictEqual(await state(page), before, 'long names and font variants preserve source-bound mesh state');
      await page.locator('#viewer-mesh-modify-fit-texture').click(); let value = await state(page); assert.equal(value.views.find(v => v.panel === 'viewer-mesh-modify').zoom, 1); assert.equal(value.views.find(v => v.panel === 'viewer-mesh-deleter').zoom, 2);
      await page.locator('#viewer-mesh-modify-redo').click(); value = await state(page); assert.deepStrictEqual(value.selectedVertices.slice().sort(), [0, 1, 2, 3, 4, 5]); assert.deepStrictEqual(value.geometry, before.geometry); assert.deepStrictEqual(value.authoring, before.authoring); assert.equal(value.edits.meshes.length, 0);
      await page.screenshot({ path: path.join(evidence, path.basename(source).startsWith('viewer-rig-qa-long') ? 'long-name.png' : 'same-native-name.png') });
      report.cases.push({ name: path.basename(source), broken, recovered, variants, originalSelection: before.selectedVertices, redoneSelection: value.selectedVertices, sourceGeometryPreserved: true });
      assert.equal(sha(fs.readFileSync(source)), sha(raw), 'original Unity source is immutable');
    }
    assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
main().catch(() => { process.exitCode = 1; });
