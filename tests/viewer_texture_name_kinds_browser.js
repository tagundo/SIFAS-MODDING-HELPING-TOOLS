/* The automatic Mod name lists each texture operation that is applied, in Korean.
 *
 * Actual product: HTTP server, DOM, texture tools, undo history, Save, Re-edit
 * from original, recipe file, layer project and PNG import, the 2D canvas
 * selection brush and the layer panel. The head texture
 * (BodyPartManager.headMaterial, so it can take a baked blush) and a second body
 * texture are synthetic, built with real Unity serialization; the cheek array is
 * the synthetic stock one of tests/test_viewer_texture_blush.py, accepted by this
 * server process only. Temporary folders are removed unless EVIDENCE_DIR is set.
 *
 * NAME_KINDS_REPORT=1 records every scenario and check instead of stopping at
 * the first mismatch (used to reproduce the old behaviour).
 */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || 'python3';
const keepEvidence = !!process.env.EVIDENCE_DIR, reportOnly = !!process.env.NAME_KINDS_REPORT;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-name-kinds-e2e-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-name-kinds-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(models, { recursive: true });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { status: 'RUNNING', cases: [], evidence };
const env = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), repo].join(path.delimiter), SUKUSTA_DIR: library, PYTHONDONTWRITEBYTECODE: '1' };
function py(code, args = []) { return JSON.parse(execFileSync(python, ['-B', '-c', code, ...args], { cwd: product, env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })); }
// The PNG to import sits in the library, a folder the server lets the viewer read.
const source = path.join(models, 'ch0001_co0001.unity'), importPNG = path.join(library, 'extracted/textures/imported.png');
fs.mkdirSync(path.dirname(importPNG), { recursive: true });
const fixture = py(`
import hashlib, json, sys
from pathlib import Path
import UnityPy
from PIL import Image
import costume_part_transplant as cpt
from test_viewer_texture_blush import LEVELS, SIZE, head_fixture, smooth_images, synthetic_payload, texture_payload
from webtools.core import texture_blush as tb, viewer_texture_tools as textures
raw, _ = head_fixture()
env = UnityPy.load(raw)
texture = next(obj for obj in env.objects if obj.type.name == "Texture2D")
# A second, body texture in the same bundle: a darker skin gradient.
body = [image.point(lambda value: max(0, value - 40)) for image in smooth_images()]
tree = texture.read_typetree()
payload = texture_payload(body, False)
tree.update(m_Name="ch0001_co0001_body", m_Width=SIZE, m_Height=SIZE, m_TextureFormat=4, m_MipCount=LEVELS, m_CompleteImageSize=len(payload))
tree["image data"] = payload
if "m_MipMap" in tree:
    tree["m_MipMap"] = True
cpt._make_object(texture.assets_file, texture, 901, tree)
Path(sys.argv[1]).write_bytes(env.file.save(packer="original"))
Image.new("RGBA", (SIZE, SIZE), (40, 90, 200, 255)).save(sys.argv[2])
cheek = synthetic_payload()
tb.CHEEK_SHA256 = hashlib.sha256(cheek).hexdigest()
cache = textures._cheek_cache_file(); cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(cheek)
print(json.dumps({"sha": tb.CHEEK_SHA256, "size": SIZE}))
`, [source, importPNG]);
async function startServer() {
  const s = net.createServer(); await new Promise(resolve => s.listen(0, '127.0.0.1', resolve)); const port = s.address().port; await new Promise(resolve => s.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  // Test-only: this process accepts the synthetic array as the stock one.
  const code = 'import sys, runpy\nfrom webtools.core import texture_blush\ntexture_blush.CHEEK_SHA256 = sys.argv[1]\nsys.argv = ["webtools"] + sys.argv[2:]\nrunpy.run_module("webtools", run_name="__main__", alter_sys=True)';
  const child = spawn(python, ['-B', '-c', code, fixture.sha, '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 300; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, log }; } catch (_) {} await wait(100); }
  child.kill(); throw new Error('Server did not become ready');
}
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function show(page, selector) { const target = page.locator(selector); await target.evaluate(e => { for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await target.scrollIntoViewIfNeeded(); return target; }
async function click(page, selector) { await (await show(page, selector)).click(); await frames(page); }
async function state(page) { return page.evaluate(() => ModelViewer.getTextureTools().getState()); }
async function idle(page) {
  await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(), p = ModelViewer.getState().persistence; return !s.pending && !s.loading && !p.busy; });
  await frames(page);
}
// The Mod name's operations: everything after its name base (the member's
// number and name, then the costume or file name).
async function name(page) {
  await idle(page);
  const value = await page.locator('#viewer-mod-name').inputValue();
  const base = await page.evaluate(() => { const p = ModelViewer.getEditingMetadata().modPackaging || {}; return (p.nameBases || {})[document.documentElement.lang] || p.nameBase || ''; });
  assert(base && value.startsWith(base), 'The automatic name starts with its base: ' + JSON.stringify({ value, base }));
  return value.slice(base.length).split(' · ').slice(1);
}
async function open(page) {
  await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
  await page.evaluate(() => { const d = document.getElementById('viewer-texture-tools'); if (!d.open) d.querySelector('summary').click(); });
  await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.textureCount > 1 && s.blush.tabVisible && s.blush.cheek && !s.loading; });
  await tab(page, 'costume');
}
async function tab(page, value) { await click(page, '#viewer-texture-tab-' + value); await idle(page); }
async function texture(page, label) {
  const value = await page.evaluate(label => { const option = [...document.querySelectorAll('#viewer-texture-select option')].find(row => row.textContent.split(' · ')[0] === label); return option && option.value; }, label);
  assert(value, 'texture ' + label);
  await (await show(page, '#viewer-texture-select')).selectOption(value);
  await page.waitForFunction(label => { const s = ModelViewer.getTextureTools().getState(); return !s.loading && s.selection && document.getElementById('viewer-texture-select').selectedOptions[0].textContent.split(' · ')[0] === label; }, label);
  await idle(page);
}
// Costume colour or skin tone through the panel: select all, a lightness change, Apply.
async function colour(page, which, label) {
  await tab(page, which); await texture(page, label);
  await click(page, '#viewer-texture-select-all');
  await page.locator(which === 'skin' ? '#viewer-texture-skin-lightness' : '#viewer-texture-lightness').evaluate(e => { e.value = '12'; e.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.waitForFunction(() => ModelViewer.getTextureTools().getState().preview);
  await click(page, '#viewer-texture-apply'); await idle(page);
  const s = await state(page); assert(!s.preview && s.editedTextures.length, which + ' applied: ' + JSON.stringify(s.editedTextures));
}
const skin = (page, label = 'ch0001_co0001_head') => colour(page, 'skin', label);
const costume = (page, label = 'ch0001_co0001_body') => colour(page, 'costume', label);
// One drag with the current tool on the visible 2D texture canvas.
async function drag(page, shift = 0) {
  const canvas = page.locator('#viewer-texture-canvas-host canvas').filter({ visible: true }); await canvas.scrollIntoViewIfNeeded();
  const box = await canvas.boundingBox(), view = (await state(page)).selection.view;
  await page.mouse.move(box.x + view.x + (10 + shift) * view.zoom, box.y + view.y + 12 * view.zoom); await page.mouse.down();
  await page.mouse.move(box.x + view.x + (40 + shift) * view.zoom, box.y + view.y + 30 * view.zoom, { steps: 8 }); await page.mouse.up();
  await idle(page);
}
// One brush stroke on the 2D canvas of the Paint tab.
async function paint(page, label = 'ch0001_co0001_head') {
  await tab(page, 'paint'); await texture(page, label);
  // An empty selection left by another tab would clip the stroke away.
  if ((await state(page)).selection.selectionActive) await click(page, '#viewer-texture-selection-clear');
  await click(page, '#viewer-texture-tools [data-texture-tool="brush"]');
  const before = (await state(page)).revision;
  await drag(page); assert((await state(page)).revision > before, 'the stroke changed the texture');
}
// A selection brush stroke on the 2D canvas: the default selection tool of the
// Costume colour and Skin tone tabs. It selects pixels and changes none.
let strokes = 0;
async function selectionStroke(page) {
  const before = await state(page);
  if (before.activeTab === 'paint') await click(page, '#viewer-texture-tools [data-texture-tool="select-brush"]');
  assert.equal((await state(page)).selection.tool, 'select-brush');
  // Each stroke a little further right, so it never repeats the current selection exactly.
  await drag(page, 6 * (strokes++ % 4));
  const after = await state(page);
  assert(after.selection.selectionActive && after.selection.selectedPixels > 0 && after.selection.undoCount === before.selection.undoCount + 1, 'a selection brush step: ' + JSON.stringify([before.selection.undoCount, after.selection.undoCount, after.selection.selectedPixels]));
  assert.equal(after.revision, before.revision, 'no pixel changed');
}
// Costume colour or skin tone on a selection brush selection.
async function colourBrushed(page, which, label) {
  await tab(page, which); await texture(page, label);
  await selectionStroke(page);
  await page.locator(which === 'skin' ? '#viewer-texture-skin-lightness' : '#viewer-texture-lightness').evaluate(e => { e.value = '12'; e.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.waitForFunction(() => ModelViewer.getTextureTools().getState().preview);
  await click(page, '#viewer-texture-apply'); await idle(page);
}
async function layerAction(page, action) { const before = (await state(page)).selection.undoCount; await click(page, '#viewer-texture-layer-' + action); await idle(page); assert.equal((await state(page)).selection.undoCount, before + 1, action); }
async function activeLayerVisible(page, visible) {
  const id = (await state(page)).selection.activeLayerId;
  const box = page.locator('#viewer-texture-layer-list [data-layer-id="' + id + '"] input[type="checkbox"]');
  if ((await box.isChecked()) !== visible) { await (await show(page, '#viewer-texture-layer-list [data-layer-id="' + id + '"] input[type="checkbox"]')).click(); await idle(page); }
}
async function blush(page) {
  await click(page, '#viewer-texture-tab-blush');
  await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.cheek.loaded && b.previewing; });
  await click(page, '#viewer-texture-blush-apply');
  await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; }); await idle(page);
}
async function undo(page) { await click(page, '#viewer-texture-undo'); await idle(page); }
// A recipe file as an older version saved it: rows without their operations.
function legacyRecipe(file) {
  const recipe = JSON.parse(fs.readFileSync(file, 'utf8')), target = path.join(path.dirname(file), 'legacy-recipe.json');
  const strip = state => { for (const row of (state && state.textures) || []) delete row.operations; };
  strip(recipe.state); if (recipe.bodyRecipe) { strip(recipe.bodyRecipe.state); strip(recipe.bodyState); }
  fs.writeFileSync(target, JSON.stringify(recipe, null, 2) + '\n'); return target;
}
// Undo through selection steps until the head's baked blush is undone too.
async function undoBlush(page) { for (let i = 0; i < 8 && (await state(page)).blush.committed; i++) await undo(page); assert(!(await state(page)).blush.committed, 'blush undone'); }
async function redo(page) { await click(page, '#viewer-texture-redo'); await idle(page); }
async function restoreOriginal(page) { await click(page, '#viewer-texture-reset'); await click(page, '#viewer-texture-restore-confirm'); await idle(page); }
async function saveModel(page) {
  await click(page, '#viewer-save');
  await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.recipePath); });
  const p = await page.evaluate(() => ModelViewer.getState().persistence); assert(!p.error, p.error); return p;
}
async function persistence(page, selector, status) {
  await click(page, selector);
  await page.waitForFunction(status => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.status === status); }, status);
  const p = await page.evaluate(() => ModelViewer.getState().persistence); assert(!p.error, p.error); await idle(page); return p;
}
async function openRecipe(page, recipePath) {
  await click(page, '#viewer-recipe-open'); await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
  await page.evaluate(directory => navigate(directory), path.dirname(recipePath));
  await page.waitForFunction(directory => document.getElementById('picker-crumb').textContent === directory, path.dirname(recipePath));
  await page.locator('#picker-entries li').filter({ hasText: path.basename(recipePath) }).click();
  await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.status === 'restored'); });
  const p = await page.evaluate(() => ModelViewer.getState().persistence); assert(!p.error, p.error); await idle(page);
}
const COSTUME = '의상 컬러', SKIN = '스킨톤', BLUSH = '홍조 굽기', PAINT = '텍스쳐 페인팅';
async function main() {
  let server, browser, page; const errors = [], mismatches = [];
  // The name shown, and (unless the saved copy is reviewed) the texture tools'
  // own operations behind it: the name never lags behind them.
  const LABELS = { costume: COSTUME, skin: SKIN, blush: BLUSH, paint: PAINT };
  async function expect(scenario, step, wanted, own = true) {
    const actual = await name(page), full = await page.locator('#viewer-mod-name').inputValue(), row = { scenario, step, wanted, actual, full };
    // (Report mode also runs on versions from before the texture tools had them.)
    const applied = (await state(page)).appliedOperations;
    if (own && (applied || !reportOnly)) {
      const found = new Set(applied.flatMap(entry => entry.operations));
      row.state = ['costume', 'skin', 'blush', 'paint'].filter(kind => found.has(kind)).map(kind => LABELS[kind]);
    }
    report.cases.push(row);
    const wrong = JSON.stringify(actual) !== JSON.stringify(wanted) || row.state && JSON.stringify(row.state) !== JSON.stringify(wanted);
    if (wrong) { mismatches.push(row); if (!reportOnly) assert.deepStrictEqual([actual, row.state || wanted], [wanted, wanted], scenario + ' / ' + step + ': ' + full); }
  }
  function check(scenario, step, actual, wanted) {
    const row = { scenario, step, wanted, actual }; report.cases.push(row);
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) { mismatches.push(row); if (!reportOnly) assert.deepStrictEqual(actual, wanted, scenario + ' / ' + step); }
  }
  const typed = () => page.locator('#viewer-mod-name').inputValue();
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1480, height: 1100 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    page = await context.newPage(); page.setDefaultTimeout(60000); page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && ModelViewer.getTextureTools && ModelViewer.getTextureTools());

    // 1. Skin tone, then painting on the same texture: both, in that order.
    await open(page); await expect('skin then paint', 'opened', []);
    await skin(page); await expect('skin then paint', 'skin tone', [SKIN]);
    await paint(page); await expect('skin then paint', 'paint stroke', [SKIN, PAINT]);
    // The painting undone keeps the skin tone; Redo brings the painting back.
    await undo(page); await expect('skin then paint', 'undo the stroke', [SKIN]);
    await redo(page); await expect('skin then paint', 'redo the stroke', [SKIN, PAINT]);
    await page.screenshot({ path: path.join(evidence, 'skin-and-paint-ko.png') });

    // 2. Skin tone, then only opening the Paint tab; then an empty new layer.
    await open(page); await skin(page); await tab(page, 'paint'); await expect('skin then Paint tab', 'Paint tab opened', [SKIN]);
    await click(page, '#viewer-texture-layer-add'); await idle(page); await expect('skin then Paint tab', 'empty layer added', [SKIN]);

    // 3. Skin tone undone and redone from other tabs.
    await open(page); await skin(page);
    await tab(page, 'paint'); await undo(page); await expect('skin undo/redo on other tabs', 'undo on Paint', []);
    await redo(page); await expect('skin undo/redo on other tabs', 'redo on Paint', [SKIN]);
    await tab(page, 'costume'); await undo(page); await redo(page); await expect('skin undo/redo on other tabs', 'undo+redo on Costume colour', [SKIN]);

    // 4. A baked blush on the head, then painting it: blush before painting.
    await open(page); await blush(page); await expect('blush then paint', 'blush', [BLUSH]);
    await paint(page); await expect('blush then paint', 'paint stroke', [BLUSH, PAINT]);
    await undo(page); await expect('blush then paint', 'stroke undone', [BLUSH]);
    await undoBlush(page); await expect('blush then paint', 'blush undone', []);
    await redo(page); await expect('blush then paint', 'blush redone', [BLUSH]);

    // 5. Skin tone on the body, blush on the head; then all four on two textures.
    await open(page); await skin(page, 'ch0001_co0001_body'); await blush(page); await expect('skin body + blush head', 'both', [SKIN, BLUSH]);
    await costume(page); await paint(page); await expect('all four', 'costume colour + skin on body, blush + paint on head', [COSTUME, SKIN, BLUSH, PAINT]);
    // The saved rows keep their one legacy kind (the tab last used, as before)
    // and list what their pixels went through; the blush stays the row's own.
    const rows = await page.evaluate(() => ModelViewer.getTextureTools().getEdits().map(row => ({ id: row.texture.id, kind: row.kind, blush: !!row.blush, operations: row.operations })));
    check('saved rows', 'kinds and operations', rows.sort((a, b) => a.id.localeCompare(b.id)), [{ id: '14', kind: 'paint', blush: true, operations: ['paint'] }, { id: '901', kind: 'costume', blush: false, operations: ['costume', 'skin'] }]);
    // Evidence for byte identity with the old code: the complete state Save sends.
    report.authoringSha256 = crypto.createHash('sha256').update(await page.evaluate(() => JSON.stringify(ModelViewer.getAuthoringState()))).digest('hex');

    // 6. Save, open the saved result, Re-edit from original: the same name.
    const saved = await saveModel(page);
    report.saved = { recipeSha256: crypto.createHash('sha256').update(fs.readFileSync(saved.recipePath)).digest('hex'),
      models: saved.previewPaths.map(file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')) };
    // The saved copy has no edits of its own; a Mod ZIP saved from it is named after the edits it was saved with.
    await persistence(page, '#viewer-open-saved', 'reviewing'); await expect('re-edit from original', 'reviewing the saved copy', [COSTUME, SKIN, BLUSH, PAINT], false);
    assert(!(await page.locator('#viewer-save-mod').isDisabled()), 'a Mod ZIP can be saved from the reviewed copy');
    await persistence(page, '#viewer-reedit-original', 'restored'); await expect('re-edit from original', 'after re-edit', [COSTUME, SKIN, BLUSH, PAINT]);
    // 7. The saved recipe file opened on a fresh original names the same operations.
    const recipeRows = JSON.parse(fs.readFileSync(saved.recipePath, 'utf8')).state.textures.map(row => ({ id: row.texture.id, kind: row.kind, operations: row.operations }));
    check('recipe file', 'rows on disk', recipeRows.sort((a, b) => a.id.localeCompare(b.id)), [{ id: '14', kind: 'paint', operations: ['paint'] }, { id: '901', kind: 'costume', operations: ['costume', 'skin'] }]);
    await open(page); await openRecipe(page, saved.recipePath); report.recipeRows = (await state(page)).editedTextures;
    await expect('recipe file', 'opened', [COSTUME, SKIN, BLUSH, PAINT]);
    // Each texture keeps its own: the head restored leaves the body's costume colour and skin tone; Undo returns the head's.
    await tab(page, 'paint'); await texture(page, 'ch0001_co0001_head'); await restoreOriginal(page); await expect('recipe file', 'head restored to its original', [COSTUME, SKIN]);
    await undo(page); await expect('recipe file', 'head restore undone', [COSTUME, SKIN, BLUSH, PAINT]);
    // A recipe saved before rows had operations opens as before: one kind each, with the blush.
    await open(page); await openRecipe(page, legacyRecipe(saved.recipePath));
    await expect('older recipe file', 'opened', [COSTUME, BLUSH, PAINT]);
    await skin(page); await expect('older recipe file', 'skin tone on the reopened head', [COSTUME, SKIN, BLUSH, PAINT]);

    // 8. Restore original texture wipes the head's operations; Undo returns them.
    await open(page); await skin(page); await paint(page); await restoreOriginal(page); await expect('restore original', 'restored', []);
    await undo(page); await expect('restore original', 'undo', [SKIN, PAINT]);

    // 9. An imported PNG replaces skin tone and blush with painting; Undo returns them.
    await open(page); await skin(page); await blush(page); await tab(page, 'paint');
    await page.evaluate(file => ModelViewer.getTextureTools().importPNGPath(file), importPNG); await expect('import PNG', 'imported', [PAINT]);
    await undo(page); await expect('import PNG', 'undo', [SKIN, BLUSH]);

    // 10. A layer project saved from a skin-toned texture and opened again.
    await open(page); await skin(page); await tab(page, 'paint');
    await click(page, '#viewer-texture-project-save'); await page.waitForFunction(() => !document.getElementById('viewer-texture-project-saved').hidden); await idle(page);
    const project = await page.locator('#viewer-texture-project-saved-path').textContent();
    await restoreOriginal(page); await expect('layer project', 'restored before opening', []);
    await page.evaluate(file => ModelViewer.getTextureTools().openProjectPath(file), project); await expect('layer project', 'project opened', [SKIN]);
    await undo(page); await expect('layer project', 'undo', []);

    // 11. A typed name is never replaced, also not by Save, reviewing the saved
    // copy or re-editing its original; Automatic returns the suggestion.
    await open(page); await (await show(page, '#viewer-mod-name')).fill('내 의상');
    await skin(page); await paint(page); check('manual name', 'skin tone and painting', await typed(), '내 의상');
    await saveModel(page); check('manual name', 'saved', await typed(), '내 의상');
    await persistence(page, '#viewer-open-saved', 'reviewing'); check('manual name', 'reviewing the saved copy', await typed(), '내 의상');
    await persistence(page, '#viewer-reedit-original', 'restored'); check('manual name', 're-edit from original', await typed(), '내 의상');
    const offered = !(await page.locator('#viewer-mod-name-auto').isDisabled()); check('manual name', 'Automatic offered', offered, true);
    if (offered) await click(page, '#viewer-mod-name-auto');
    await expect('manual name', 'automatic again', [SKIN, PAINT]);

    // 12. The 2D canvas selection brush (the default selection tool of these
    // tabs) selects pixels and paints none.
    await open(page); await colourBrushed(page, 'skin', 'ch0001_co0001_head'); await expect('selection brush', 'skin tone on a brushed selection', [SKIN]);
    await colourBrushed(page, 'costume', 'ch0001_co0001_body'); await expect('selection brush', 'costume colour on a brushed selection', [COSTUME, SKIN]);
    await tab(page, 'paint'); await texture(page, 'ch0001_co0001_head'); await selectionStroke(page); await expect('selection brush', 'brushed on the Paint tab', [COSTUME, SKIN]);
    await click(page, '#viewer-texture-layer-add'); await idle(page); await expect('selection brush', 'then an empty layer', [COSTUME, SKIN]);

    // 13. A selection after the skin tone, an unrelated refresh and its Undo: the name follows the texture's own operations.
    await open(page); await skin(page); await selectionStroke(page); await expect('selection after skin tone', 'selection brushed', [SKIN]);
    await page.locator('#viewer-adjustments').evaluate(e => e.dispatchEvent(new Event('change', { bubbles: true }))); await expect('selection after skin tone', 'another panel refreshed', [SKIN]);
    await undo(page); await expect('selection after skin tone', 'selection undone', [SKIN]);
    await undo(page); await expect('selection after skin tone', 'skin tone undone', []);

    // 14. Layer steps that leave the flattened texture as it was add nothing.
    await open(page); await skin(page); await tab(page, 'paint'); await texture(page, 'ch0001_co0001_head');
    await layerAction(page, 'add'); await expect('empty layer steps', 'added', [SKIN]);
    await (await show(page, '#viewer-texture-layer-opacity')).evaluate(e => { e.value = '50'; e.dispatchEvent(new Event('change', { bubbles: true })); }); await idle(page); await expect('empty layer steps', 'opacity 50', [SKIN]);
    await activeLayerVisible(page, false); await expect('empty layer steps', 'hidden', [SKIN]);
    await activeLayerVisible(page, true); await expect('empty layer steps', 'shown', [SKIN]);
    await layerAction(page, 'duplicate'); await expect('empty layer steps', 'duplicated', [SKIN]);
    await layerAction(page, 'merge'); await expect('empty layer steps', 'merged down', [SKIN]);
    await layerAction(page, 'down'); await expect('empty layer steps', 'moved below the texture', [SKIN]);
    await layerAction(page, 'up'); await expect('empty layer steps', 'moved back', [SKIN]);
    await layerAction(page, 'remove'); await expect('empty layer steps', 'deleted', [SKIN]);

    // 15. Painting on a new layer, then deleting that layer: the pixels are the
    // original again, so only the baked blush is left to name.
    await open(page); await blush(page); await tab(page, 'paint'); await texture(page, 'ch0001_co0001_head');
    await layerAction(page, 'add'); await paint(page); await expect('painted layer deleted', 'painted on a new layer', [BLUSH, PAINT]);
    await layerAction(page, 'remove'); await expect('painted layer deleted', 'that layer deleted', [BLUSH]);
    await undo(page); await expect('painted layer deleted', 'deletion undone', [BLUSH, PAINT]);

    // 16. Skin tone and an empty layer, saved and opened again from the recipe file.
    await open(page); await skin(page); await tab(page, 'paint'); await layerAction(page, 'add'); await expect('recipe after an empty layer', 'before saving', [SKIN]);
    const emptyLayer = await saveModel(page);
    await open(page); await openRecipe(page, emptyLayer.recipePath); await expect('recipe after an empty layer', 'recipe opened', [SKIN]);
    // While a recipe's textures load, the name already lists the rows' operations (this row's kind is the legacy "paint").
    const pending = await page.evaluate(async () => {
      const tools = ModelViewer.getTextureTools(), rows = tools.getEdits(), restoring = tools.restoreEdits(rows);
      const during = tools.getState().appliedOperations.map(row => row.operations); await restoring;
      return { kinds: rows.map(row => row.kind), during };
    });
    check('recipe after an empty layer', 'operations while the recipe loads', pending, { kinds: ['paint'], during: [['skin']] });
    await expect('recipe after an empty layer', 'loaded again', [SKIN]);
    // A recipe row whose operations are not the canonical list is refused before anything changes.
    const refused = await page.evaluate(() => {
      const tools = ModelViewer.getTextureTools(), row = tools.getEdits()[0];
      return Promise.all([["paint", "skin"], ["skin", "skin"], ["blush"], []].map(operations => tools.restoreEdits([Object.assign({}, row, { operations })]).then(() => "restored", error => error.message)));
    });
    check('recipe after an empty layer', 'non-canonical operations refused', refused, Array(4).fill('Invalid texture recipe.'));
    await expect('recipe after an empty layer', 'still as opened', [SKIN]);

    assert.deepStrictEqual(errors, []);
    report.mismatches = mismatches; report.status = mismatches.length ? 'FAIL' : 'PASS';
    if (mismatches.length) throw new Error(mismatches.length + ' name mismatches');
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error.stack || error); report.pageErrors = errors; report.mismatches = mismatches;
    if (page) { report.failureState = await page.evaluate(() => ModelViewer.getTextureTools().getState()).catch(() => null); await page.screenshot({ path: path.join(evidence, 'failure.png') }).catch(() => {}); }
    throw error;
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.log.end(); await new Promise(resolve => server.child.once('exit', resolve)).catch(() => {}); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, mismatches: mismatches.map(row => row.scenario + ' / ' + row.step + ': ' + JSON.stringify(row.actual) + ' wanted ' + JSON.stringify(row.wanted)), error: report.error && report.error.split('\n')[0] }, null, 1));
    fs.rmSync(library, { recursive: true, force: true });
    if (!keepEvidence && report.status === 'PASS') fs.rmSync(evidence, { recursive: true, force: true });
  }
}
main().catch(() => { process.exitCode = 1; });
