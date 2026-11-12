/* Real Unity/HTTP/WebGL: visible reset, original semantics, Undo and copies. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-reset-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-reset-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'original.unity'), raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, raw);
const sha = value => crypto.createHash('sha256').update(value).digest('hex'), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const meshState = page => page.evaluate(() => ModelViewer.getState().meshTools);
const geometry = state => state.runtime.bindings.map(b => ({ mesh: b.mesh, submesh: b.submesh, triangles: b.triangles, positions: b.samplePositions, weights: b.sampleWeights }));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw Error('Product server did not become ready');
}
async function save(page) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/export')); await page.locator('#viewer-mesh-deleter-save').click();
  const result = await response; assert.equal(result.status(), 200, await result.text());
  const output = await result.json(); await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy); return output;
}
async function inspectCopy(page, output) {
  return page.evaluate(async paths => {
    async function post(endpoint, body) { const response = await fetch('/api/viewer/' + endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!response.ok) throw Error(await response.text()); return response.json(); }
    const prepared = await post('prepare', { paths, rigged: true, auto_face: false }), token = prepared.editing.token;
    const listing = await post('mesh/inspect', { token }); return post('mesh/data', { token, mesh: listing.meshes.find(m => m.available).mesh });
  }, output.preview_paths);
}
async function selectAll(page) {
  const panel = page.locator('#viewer-mesh-deleter'); await panel.locator('.uv-selection-menu > summary').click();
  await panel.getByRole('button', { name: 'Select all', exact: true }).click();
  await panel.locator('.uv-selection-menu > summary').click();
}
async function layout(page) {
  return page.locator('#viewer-mesh-deleter-reset').evaluate(button => {
    const r = button.getBoundingClientRect(), viewport = visualViewport, style = getComputedStyle(button), panel = button.closest('.viewer-mesh-tools'), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { text: button.textContent, x: r.x, right: r.right, y: r.y, bottom: r.bottom, width: r.width, height: r.height, fontSize: +parseFloat(style.fontSize),
      inInspector: !!button.closest('.uv-edit-inspector'), inMenu: !!button.closest('.uv-selection-menu'), mistakenDelete: button.classList.contains('uv-delete-button'),
      inspectorHidden: panel.querySelector('.uv-edit-inspector').hidden, hit: hit === button || button.contains(hit), viewportWidth: viewport.width, viewportHeight: viewport.height,
      pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 };
  });
}
function fits(value, expanded) {
  assert(value.width > 50 && value.height >= 32 && value.fontSize >= 12, 'reset keeps a visible text label and usable button');
  assert(!value.inInspector && !value.inMenu && !value.mistakenDelete && value.inspectorHidden, 'reset needs no settings or selection menu and never becomes Delete');
  assert(value.x >= -1 && value.right <= value.viewportWidth + 1 && !value.pageOverflow, 'reset fits the actual viewport');
  if (expanded) assert(value.y >= -1 && value.bottom <= value.viewportHeight + 1 && value.hit, 'expanded reset is on screen and receives pointer input');
}
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    await page.locator('#viewer-mesh-deleter').evaluate(e => { e.open = true; });
    const reset = page.locator('#viewer-mesh-deleter-reset'); assert(await reset.isVisible()); assert(await reset.isDisabled(), 'no selected mesh cannot reset');
    const listingResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/inspect')); await page.locator('#viewer-mesh-deleter-load').click();
    const listing = await (await listingResponse).json(), identity = listing.meshes.find(m => m.available).mesh, value = JSON.stringify(identity);
    const dataResponse = page.waitForResponse(r => r.url().endsWith('/api/viewer/mesh/data')); await page.locator('#viewer-mesh-deleter-select').selectOption(value); const data = await (await dataResponse).json();
    await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
    const initial = await meshState(page), authoring = await page.evaluate(() => ModelViewer.getAuthoringState());
    fits(await layout(page), false); assert.equal(await reset.textContent(), 'Restore mesh changes');
    // Author real position and skin changes through the existing Modify controls.
    const modify = page.locator('#viewer-mesh-modify'); await modify.evaluate(e => { e.open = true; });
    await page.locator('#viewer-mesh-modify-select').selectOption(value); await modify.locator('[data-uv-settings]').click();
    await page.locator('#viewer-mesh-modify-vertex').fill('2'); await page.locator('#viewer-mesh-modify-select-vertex').click();
    for (const [axis, number] of [['X', '.2'], ['Y', '.8'], ['Z', '-.1']]) await modify.locator('[data-mesh-position-axis=' + axis + ']').fill(number);
    await page.locator('#viewer-mesh-modify-position-set').click();
    await page.locator('#viewer-mesh-modify-weight-bone').selectOption('2'); await page.locator('#viewer-mesh-modify-weight-value').fill('.4'); await page.locator('#viewer-mesh-modify-weight-apply').click();
    await modify.getByRole('button', { name: 'Close settings', exact: true }).click(); await modify.evaluate(e => { e.open = false; });
    const canvas = page.locator('#viewer-mesh-deleter-canvas'); await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox(), face = data.triangles[0], uv = [0, 1].map(axis => face.reduce((s, v) => s + data.uv[v][axis] / 3, 0));
    await page.locator('#viewer-mesh-deleter-radius').fill('2'); await page.mouse.click(box.x + uv[0] * box.width, box.y + (1 - uv[1]) * box.height);
    const marked = (await meshState(page)).selectedFaces; assert(marked.length > 0 && marked.length < data.triangles.length);
    await page.locator('#viewer-mesh-deleter-delete').click(); const edited = await meshState(page);
    assert.equal(edited.edits.meshes[0].positions.length, 1); assert.equal(edited.edits.meshes[0].weights.length, 1);
    assert.equal(edited.runtime.bindings[0].triangles, data.triangles.length - marked.length);
    const deletionCopy = await save(page), savedHash = sha(fs.readFileSync(deletionCopy.preview_paths[0]));
    await reset.click(); let restored = await meshState(page);
    assert.deepStrictEqual(restored.edits.meshes, []); assert.deepStrictEqual(restored.selectedFaces, []); assert.deepStrictEqual(restored.selectedVertices, []);
    assert.deepStrictEqual(geometry(restored), geometry(initial), 'reset restores actual GPU topology, positions and skin');
    assert.equal(restored.history, edited.history + 1, 'reset adds exactly one undo step');
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authoring, 'reset remains scoped to mesh edits');
    await page.locator('#viewer-mesh-deleter-undo').click(); const undone = await meshState(page);
    assert.deepStrictEqual(undone.edits, edited.edits); assert.deepStrictEqual(geometry(undone), geometry(edited));
    await page.locator('#viewer-mesh-deleter-redo').click(); restored = await meshState(page); assert.deepStrictEqual(geometry(restored), geometry(initial));
    const restoredCopy = await save(page), serialized = await inspectCopy(page, restoredCopy), serializedDeleted = await inspectCopy(page, deletionCopy);
    assert.deepStrictEqual(serialized.triangles, data.triangles); assert.deepStrictEqual(serialized.positions, data.positions); assert.deepStrictEqual(serialized.skin, data.skin);
    assert.equal(serializedDeleted.triangles.length, data.triangles.length - marked.length); assert.equal(sha(fs.readFileSync(deletionCopy.preview_paths[0])), savedHash, 'earlier saved copy keeps its version');
    report.cases.push({ name: 'native visible reset restores original current-mesh topology/position/skin, one-step Undo/Redo and independent serialized copies', removedFaces: marked, originalFaces: data.triangles.length, deletedCopyFaces: serializedDeleted.triangles.length, restoredCopyFaces: serialized.triangles.length });
    await selectAll(page); const selected = await meshState(page); assert.equal(selected.selectedFaces.length, data.triangles.length);
    await reset.click(); assert.deepStrictEqual((await meshState(page)).selectedFaces, []);
    await page.locator('#viewer-mesh-deleter-undo').click(); assert.deepStrictEqual((await meshState(page)).selectedFaces, selected.selectedFaces);
    const beforeLayout = await meshState(page), profiles = [];
    for (const size of [{ width: 1440, height: 1100 }, { width: 360, height: 456 }, { width: 640, height: 360 }]) {
      await page.setViewportSize(size);
      for (const [lang, label] of [['en', 'Restore mesh changes'], ['ko', '메시 변경 초기화'], ['ja', 'メッシュ変更をリセット']]) {
        await page.evaluate(lang => { localStorage.setItem('sifas_lang', lang); document.documentElement.lang = lang; ModelViewer.updateLanguage(); }, lang);
        await reset.scrollIntoViewIfNeeded(); let normal = await layout(page); fits(normal, false); assert.equal(normal.text, label);
        await page.locator('#viewer-mesh-deleter .texture-pane-expand-button').click(); await page.waitForFunction(() => TexturePanelExpand.getState().expanded === 'viewer-mesh-deleter'); await page.waitForTimeout(100);
        let expanded = await layout(page); fits(expanded, true); assert.equal(expanded.text, label);
        if (lang === 'ko') await page.screenshot({ path: path.join(evidence, 'reset-ko-' + size.width + 'x' + size.height + '.png') });
        await page.keyboard.press('Escape'); await page.waitForFunction(() => !TexturePanelExpand.getState().expanded);
        profiles.push({ size, lang, normal, expanded });
      }
    }
    const afterLayout = await meshState(page); assert.deepStrictEqual(afterLayout.edits, beforeLayout.edits); assert.equal(afterLayout.history, beforeLayout.history); assert.equal(afterLayout.future, beforeLayout.future);
    assert.deepStrictEqual(geometry(afterLayout), geometry(beforeLayout), 'translation, resize and expanded layouts preserve actual edit state');
    await page.locator('#viewer-mesh-deleter .texture-pane-expand-button').click(); await page.waitForFunction(() => TexturePanelExpand.getState().expanded === 'viewer-mesh-deleter');
    await reset.click(); assert.deepStrictEqual((await meshState(page)).selectedFaces, []);
    await page.locator('#viewer-mesh-deleter-undo').click(); assert.deepStrictEqual((await meshState(page)).selectedFaces, beforeLayout.selectedFaces, 'short expanded reset and Undo use the same native actions');
    await page.evaluate(() => { localStorage.setItem('sifas_lang', 'en'); document.documentElement.lang = 'en'; ModelViewer.updateLanguage(); });
    assert.equal(await reset.textContent(), 'Restore mesh changes', 'visible label updates while already expanded'); fits(await layout(page), true);
    await page.keyboard.press('Escape');
    report.cases.push({ name: 'selection-only reset/Undo, native short expanded reset/Undo and visible labelled EN/KO/JA action in normal, narrow and short expanded layouts', profiles });
    assert.equal(sha(fs.readFileSync(source)), sha(raw), 'original Unity file is immutable'); assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
main().catch(() => { process.exitCode = 1; });
