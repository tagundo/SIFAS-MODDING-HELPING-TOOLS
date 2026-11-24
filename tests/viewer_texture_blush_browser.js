/* Bake blush through the actual product: HTTP server, DOM, WebGL preview, history and export.
 *
 * The head model and the cheek array are synthetic (tests/test_viewer_texture_blush.py);
 * the server process alone treats that array's hash as the stock one, so no game
 * texture data is needed. Temporary folders are removed unless EVIDENCE_DIR is set.
 */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || 'python3';
const keepEvidence = !!process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-blush-e2e-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-blush-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(models, { recursive: true });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { status: 'RUNNING', cases: [], evidence };
const env = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests'), repo].join(path.delimiter), SUKUSTA_DIR: library, PYTHONDONTWRITEBYTECODE: '1' };
function py(code, args = []) { return JSON.parse(execFileSync(python, ['-B', '-c', code, ...args], { cwd: product, env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })); }
const fixture = py(`
import base64, hashlib, json, sys
from pathlib import Path
import astc_standin
from test_viewer_texture_blush import head_fixture, recolour_images, synthetic_payload
from webtools.core import texture_blush as tb, viewer_texture_tools as textures
raw, images = head_fixture()
astcenc = ""
if astc_standin.available():
    astcenc = astc_standin.write(sys.argv[5])
    Path(sys.argv[4]).write_bytes(head_fixture(astc=True)[0])
payload = synthetic_payload()
tb.CHEEK_SHA256 = hashlib.sha256(payload).hexdigest()
Path(sys.argv[1]).write_bytes(raw)
Path(sys.argv[2]).write_bytes(raw)
Path(sys.argv[3]).write_bytes(head_fixture(attach=True)[0])
cache = textures._cheek_cache_file(); cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(payload)
print(json.dumps({"sha": tb.CHEEK_SHA256, "cache": str(cache), "width": images[0].width, "height": images[0].height, "astcenc": astcenc,
                  "savedExact": textures.SAVED_EXACT, "savedAstc": textures.SAVED_ASTC, "notAstc": textures.KEEP_NOT_ASTC,
                  "rgba": base64.b64encode(images[0].tobytes()).decode(), "recolour": base64.b64encode(recolour_images()[0].tobytes()).decode()}))
`, [path.join(models, 'ch0001_co0001.unity'), path.join(models, 'ch0001_co0001_copy.unity'), path.join(models, 'ch0001_co0002.unity'), path.join(models, 'ch0001_co0003.unity'), library]);
const source = path.join(models, 'ch0001_co0001.unity'), second = path.join(models, 'ch0001_co0001_copy.unity'), recolourModel = path.join(models, 'ch0001_co0002.unity'), astcModel = path.join(models, 'ch0001_co0003.unity');
// The ASTC head decodes and (opt-in) re-encodes with the test astcenc (tests/astc_standin.py).
if (fixture.astcenc) env.ASTCENC_BIN = fixture.astcenc;
const original = Buffer.from(fixture.rgba, 'base64'), recolour = Buffer.from(fixture.recolour, 'base64');
function expected(layer, k, image = fixture.rgba) {
  return Buffer.from(py(`
import base64, json, sys
from test_viewer_texture_blush import synthetic_payload
from webtools.core import texture_blush as tb
out, changed, _ = tb.bake_rgba(base64.b64decode(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), tb.layer_bytes(synthetic_payload(), int(sys.argv[4])), float(sys.argv[5]))
print(json.dumps(base64.b64encode(out).decode()))`, [image, String(fixture.width), String(fixture.height), String(layer), String(k)]), 'base64');
}
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
// Where the status, the strength hint, the five levels, the type buttons, Apply
// and the save line sit against the settings scroller and the window. With
// scroll 'top' the settings box is scrolled to its top and into the window, as a
// user would; without it, everything stays where the product put it.
async function blushLayout(page, scroll) {
  return page.evaluate(scroll => {
    const box = document.querySelector('.viewer-texture-properties');
    if (scroll) { box.scrollTop = 0; box.scrollIntoView({ block: 'nearest' }); }
    // Inside the box and the window, and not covered by anything (a pinned row, say).
    const view = box.getBoundingClientRect(), uncovered = (e, r) => [r.top + 2, (r.top + r.bottom) / 2, r.bottom - 2].every(y => { const at = document.elementFromPoint((r.left + r.right) / 2, y); return !!at && e.contains(at); });
    const place = e => { const r = e.getBoundingClientRect(), inside = r.height > 0 && r.top >= Math.max(0, view.top) - 1 && r.bottom <= Math.min(innerHeight, view.bottom) + 1; return { top: Math.round(r.top), bottom: Math.round(r.bottom), inside: inside && uncovered(e, r) }; };
    const id = name => place(document.getElementById(name)), all = selector => Array.from(document.querySelectorAll(selector)).map(place);
    return { scroller: { top: Math.round(view.top), bottom: Math.round(view.bottom), scrollTop: box.scrollTop, scrollHeight: box.scrollHeight }, status: id('viewer-texture-blush-status'), hint: id('viewer-texture-blush-game-level'),
      levels: all('#viewer-texture-blush-levels .viewer-texture-blush-level'), types: all('#viewer-texture-blush-types .viewer-texture-blush-layer'),
      apply: id('viewer-texture-blush-apply'), before: id('viewer-texture-blush-before'), save: id('viewer-texture-blush-save-mode') };
  }, scroll || null);
}
// The status, the hint beside the strength heading, all five levels, Apply,
// Show before and the save line are in view together; the two types share a row.
function assertBlushInView(where, label) {
  const text = label + ' ' + JSON.stringify(where);
  assert.equal(where.levels.length, 5, text);
  assert.ok(['status', 'hint', 'apply', 'before', 'save'].every(key => where[key].inside) && where.levels.every(row => row.inside), text);
  assert.ok(where.types.length === 2 && where.types[0].top === where.types[1].top && where.types[0].bottom === where.types[1].bottom, 'type buttons side by side, same height: ' + text);
}
// Leave the blush tab and open it again with a click, as a user does.
async function reopenBlush(page) {
  await page.evaluate(() => ModelViewer.getTextureTools().setTab('costume')); await frames(page);
  await page.locator('#viewer-texture-tab-blush').click();
  await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.cheek.loaded && b.swatches; }); await frames(page);
}
async function panelShot(page, file) {
  const clip = await page.evaluate(() => { const v = document.querySelector('.viewer-texture-properties').getBoundingClientRect(); return { x: Math.max(0, v.left - 8), y: Math.max(0, v.top - 8), width: v.width + 16, height: Math.min(innerHeight, v.bottom + 8) - Math.max(0, v.top - 8) }; });
  await page.screenshot({ path: file, clip });
}
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function state(page) { return page.evaluate(() => ModelViewer.getTextureTools().getState()); }
async function click(page, selector) { const target = page.locator(selector); await target.evaluate(e => { for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await target.scrollIntoViewIfNeeded(); await target.click(); await frames(page); }
// The pixels the 3D view samples: the texture override uploaded to the actual SIFAS shader.
async function live(page) {
  return page.evaluate(() => {
    let found = null; __blushObserved.scene.traverse(mesh => { if (found || !mesh.isMesh || mesh.userData && mesh.userData.viewerHelper) return; [].concat(mesh.material).forEach(material => { const texture = material && (material.uniforms && material.uniforms.uMainTex ? material.uniforms.uMainTex.value : material.map); if (!found && texture && texture.isDataTexture && texture.image && texture.image.data) found = Array.from(texture.image.data); }); });
    return found;
  });
}
function same(left, right) { return !!left && Buffer.from(left).equals(Buffer.from(right)); }
function pngPixels(data) { return Buffer.from(py("import base64,io,json,sys;from PIL import Image;im=Image.open(io.BytesIO(base64.b64decode(sys.argv[1].split(',',1)[1]))).convert('RGBA');print(json.dumps(base64.b64encode(im.tobytes()).decode()))", [data]), 'base64'); }
async function main() {
  let server, browser, page; const errors = [];
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1480, height: 1100 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    page = await context.newPage(); page.setDefaultTimeout(60000); page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.route('**/static/viewer-quality.js', async route => { const response = await route.fetch(), body = await response.text(); await route.fulfill({ response, body: body + '\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__blushObserved={scene,camera};return render.apply(this,arguments);};return c;};})();' }); });
    await page.goto(server.url); await page.waitForFunction(() => window.ModelViewer && ModelViewer.getTextureTools && ModelViewer.getTextureTools());
    await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available && window.__blushObserved);
    await page.evaluate(() => { const s = document.getElementById('viewer-shader'); s.value = 'sifas'; s.dispatchEvent(new Event('change', { bubbles: true })); });
    await page.locator('#viewer-texture-tools > summary').scrollIntoViewIfNeeded(); await page.evaluate(() => { const d = document.getElementById('viewer-texture-tools'); if (!d.open) d.querySelector('summary').click(); });
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.textureCount > 0 && s.blush.tabVisible && s.blush.cheek && !s.loading; });

    // One clear entry: the tab appears for the head texture; one click opens it with working defaults.
    const tab = page.locator('#viewer-texture-tab-blush'); assert.equal(await tab.textContent(), 'Bake blush');
    await tab.click();
    await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.cheek.loaded && b.swatches && b.previewing; });
    let s = await state(page);
    assert.deepStrictEqual(s.blush.choice, { layer: 0, k: 1.65, level: 'medium', encoding: 'exact' }); assert.equal(s.blush.cheek.source, 'cache');
    assert.equal(await page.locator('#viewer-texture-blush-level-medium').getAttribute('aria-checked'), 'true');
    assert.equal(await page.locator('#viewer-texture-blush-layer-0').getAttribute('aria-checked'), 'true');
    assert.match(await page.locator('#viewer-texture-blush-status').textContent(), /^Preview, not applied yet: Medium \(k 1\.65\) · Cheeks \(Ppo\)$/);
    assert.deepStrictEqual(s.blush.alerts, ["Android and iOS bundles are separate: bake each platform's file.", 'This file is the Android bundle.']);
    assert.deepStrictEqual(s.blush.notes, ["The game's own song blush still appears on top during blush scenes.", 'Using the verified blush pattern saved from a costume you opened before.']);
    assert.match(s.status, /^Pick a strength, check the 3D preview, then apply\.$/);
    // The status and the platform alert sit inside the visible part of the settings scroller.
    const layout = await page.evaluate(() => {
      const box = document.querySelector('.viewer-texture-properties'), panel = document.getElementById('viewer-texture-blush-panel'), view = box.getBoundingClientRect();
      const inside = id => { const r = document.getElementById(id).getBoundingClientRect(); return r.top >= view.top - 1 && r.bottom <= view.bottom + 1 && r.height > 0; };
      return { status: inside('viewer-texture-blush-status'), alerts: inside('viewer-texture-blush-alerts'), order: Array.from(panel.children).map(e => e.id || e.className),
        levelGroup: Array.from(document.getElementById('viewer-texture-blush-levels').children).slice(0, 3).map(e => e.id) };
    });
    assert.ok(layout.status && layout.alerts, JSON.stringify(layout));
    // Status and alerts, the choices, then Apply with its save line in normal
    // flow; the explanations and Advanced come after them.
    assert.deepStrictEqual(layout.order.slice(0, 6), ['viewer-texture-blush-target', 'viewer-texture-blush-status', 'viewer-texture-blush-alerts', 'viewer-texture-blush-types', 'viewer-texture-blush-levels', 'viewer-texture-blush-commit']);
    // Where the game's own blush is, right under the strength heading.
    assert.deepStrictEqual(layout.levelGroup, ['viewer-texture-blush-level-title', 'viewer-texture-blush-game-level', 'viewer-texture-blush-base']);
    assert.equal(await page.locator('#viewer-texture-blush-game-level').textContent(), "Light ≈ the game's strongest song blush");
    assert.equal(await page.locator('#viewer-texture-blush-levels').getAttribute('aria-describedby'), 'viewer-texture-blush-game-level');
    // The status, the five levels and Apply are in view together, at the top
    // of the settings box, also on a 1366x900 screen and with Advanced open.
    const layouts = [];
    for (const [width, height] of [[1480, 1100], [1366, 900]]) {
      await page.setViewportSize({ width, height }); await frames(page);
      for (const advanced of [false, true]) {
        await page.evaluate(open => { document.querySelector('.viewer-texture-blush-advanced').open = open; }, advanced); await frames(page);
        const where = await blushLayout(page, 'top'); layouts.push({ width, height, advanced, where });
        assertBlushInView(where, width + 'x' + height + (advanced ? ' Advanced open' : ''));
      }
    }
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = false; document.querySelector('.viewer-texture-properties').scrollTop = 0; });
    // As the tab opens on a 1366x900 screen, without any scrolling by the user.
    await page.setViewportSize({ width: 1366, height: 900 }); await page.evaluate(() => { document.querySelector('.viewer-texture-properties').scrollTop = 300; window.scrollTo(0, 0); });
    await reopenBlush(page); let opened = await blushLayout(page); layouts.push({ width: 1366, height: 900, opened: true, where: opened });
    assertBlushInView(opened, 'en as the tab opens'); await panelShot(page, path.join(evidence, 'panel-1366x900-en.png'));
    // Keyboard: every control from the types to Apply is in view when it takes focus.
    await page.locator('#viewer-texture-blush-layer-0').focus(); const focused = [];
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab'); await frames(page);
      focused.push(await page.evaluate(() => { const e = document.activeElement, v = document.querySelector('.viewer-texture-properties').getBoundingClientRect(), r = e.getBoundingClientRect(); return { id: e.id, inside: r.top >= v.top - 1 && r.bottom <= v.bottom + 1 }; }));
    }
    assert.deepStrictEqual(focused.map(row => row.id), ['viewer-texture-blush-layer-1', 'viewer-texture-blush-level-veryLight', 'viewer-texture-blush-level-light', 'viewer-texture-blush-level-medium', 'viewer-texture-blush-level-strong', 'viewer-texture-blush-level-veryStrong', 'viewer-texture-blush-apply', 'viewer-texture-blush-before']);
    assert.ok(focused.every(row => row.inside), JSON.stringify(focused));
    await page.setViewportSize({ width: 1480, height: 1100 }); await frames(page);
    s = await state(page); assert.deepStrictEqual(s.blush.choice, { layer: 0, k: 1.65, level: 'medium', encoding: 'exact' }); assert(s.blush.previewing);
    // How Save writes this RGBA32 face is always in view; the selection display does not apply here.
    assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), 'Save: exact pixels');
    assert.equal(await page.locator('#viewer-texture-show-selection').isVisible(), false, 'the selection toggle is hidden in the blush tab');
    assert.match(await page.locator('#viewer-texture-blush-layer-1 .viewer-texture-blush-shape').textContent(), /^Band across the nose$/);
    // Advanced names what it holds; this RGBA32 face has no ASTC to keep.
    assert.equal(await page.locator('#viewer-texture-blush-advanced-summary').textContent(), 'Advanced: strength value');
    assert.equal(await page.locator('#viewer-texture-blush-remove').textContent(), 'Remove');
    const swatches = await page.evaluate(() => Array.from(document.querySelectorAll('#viewer-texture-blush-levels .viewer-texture-blush-level')).map(b => ({ id: b.dataset.blushLevel, colour: b.dataset.colour, text: b.textContent })));
    assert.deepStrictEqual(swatches.map(r => r.text), ['Very light', 'Light', 'Medium', 'Strong', 'Very strong']);
    assert.equal(new Set(swatches.map(r => r.colour)).size, 5, 'each level shows its own cheek-centre colour');
    for (let i = 1; i < 5; i++) { const a = s.blush.swatches.colours[i - 1], b = s.blush.swatches.colours[i]; assert(b[1] < a[1] && b[2] < a[2], 'neighbouring levels get darker'); }
    report.cases.push({ name: 'blush tab, defaults, swatches and caveats', choice: s.blush.choice, swatches });
    report.cases.push({ name: 'status, the five levels, Apply and the save line in view together at 1480x1100 and 1366x900, also as the tab opens', layouts, focused });

    // Live 3D preview before saving, exact against the Python rule; Save waits for Apply.
    assert(same(await live(page), expected(0, 1.65)), 'the 3D texture shows the exact bake preview');
    assert(await page.locator('#viewer-save').isDisabled(), 'an unapplied preview blocks saving');
    assert.equal((await page.evaluate(() => ModelViewer.getTextureTools().getEdits())).length, 0);
    await page.screenshot({ path: path.join(evidence, 'preview-medium.png') });
    await click(page, '#viewer-texture-blush-before'); s = await state(page);
    assert(s.blush.before && !s.blush.displayed); const before = await live(page); assert(!before || same(before, original), 'Show before shows the texture without the blush');
    await click(page, '#viewer-texture-blush-before'); assert(same(await live(page), expected(0, 1.65)));
    await click(page, '#viewer-texture-blush-level-veryStrong'); assert(same(await live(page), expected(0, 3)));
    await click(page, '#viewer-texture-blush-layer-1'); assert(same(await live(page), expected(1, 3)));
    report.cases.push({ name: 'live preview, before/after toggle, level and type changes' });

    // One click applies; the recipe keeps the unbaked pixels plus the operation.
    const undoBefore = s.selection.undoCount;
    await click(page, '#viewer-texture-blush-apply');
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; });
    s = await state(page); assert.deepStrictEqual(s.blush.committed, { layer: 1, k: 3, encoding: 'exact' }); assert.equal(s.selection.undoCount, undoBefore + 1);
    let edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits());
    assert.equal(edits.length, 1); assert.deepStrictEqual(edits[0].blush, { layer: 1, k: 3, encoding: 'exact' }); assert.equal(edits[0].kind, 'blush');
    assert(pngPixels(edits[0].png).equals(original), 'the recipe PNG holds the original, unbaked pixels');
    assert(same(await live(page), expected(1, 3))); assert(!(await page.locator('#viewer-save').isDisabled()));
    assert.match(await page.locator('#viewer-texture-blush-status').textContent(), /^Applied: Very strong \(k 3\) · Cheeks and nose \(Akarame\)$/);
    // Undo/redo through the existing history buttons.
    await click(page, '#viewer-texture-undo'); s = await state(page); assert.equal(s.blush.committed, null);
    assert.equal((await page.evaluate(() => ModelViewer.getTextureTools().getEdits())).length, 0); const undone = await live(page); assert(!undone || same(undone, original));
    await click(page, '#viewer-texture-redo'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; });
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 3, encoding: 'exact' });
    // Re-bake replaces the operation; undo returns to the previous one.
    await click(page, '#viewer-texture-blush-level-light'); await click(page, '#viewer-texture-blush-apply');
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.k === 1.05 && !s.pending; });
    edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.deepStrictEqual(edits[0].blush, { layer: 1, k: 1.05, encoding: 'exact' }); assert(pngPixels(edits[0].png).equals(original));
    assert(same(await live(page), expected(1, 1.05)), 'a re-bake starts from the original pixels');
    await click(page, '#viewer-texture-undo'); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 3, encoding: 'exact' });
    await click(page, '#viewer-texture-redo'); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 1.05, encoding: 'exact' });
    // Advanced numeric strength.
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = true; });
    const field = page.locator('#viewer-texture-blush-k'); await field.fill('2.0'); await field.press('Tab'); await frames(page);
    s = await state(page); assert.deepStrictEqual(s.blush.choice, { layer: 1, k: 2, level: 'custom', encoding: 'exact' }); assert(same(await live(page), expected(1, 2)));
    await click(page, '#viewer-texture-blush-apply'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.k === 2 && !s.pending; });
    report.cases.push({ name: 'apply, undo/redo, re-bake without compounding and advanced strength' });

    // Cancel preview drops the previewed choice: the next change starts from the applied bake.
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = false; });
    await click(page, '#viewer-texture-blush-level-veryStrong'); s = await state(page); assert.deepStrictEqual(s.blush.choice, { layer: 1, k: 3, level: 'veryStrong', encoding: 'exact' }); assert(s.blush.previewing);
    await click(page, '#viewer-texture-cancel'); s = await state(page);
    assert.deepStrictEqual([s.blush.choice, s.blush.pending, s.blush.previewing], [{ layer: 1, k: 2, level: 'custom', encoding: 'exact' }, false, false]);
    assert.equal(s.blush.status, 'Applied: Custom (k 2) · Cheeks and nose (Akarame)'); assert(same(await live(page), expected(1, 2)));
    assert.equal(await page.locator('#viewer-texture-blush-level-veryStrong').getAttribute('aria-checked'), 'false');
    assert.equal(await page.locator('#viewer-texture-blush-k').inputValue(), '2');
    await click(page, '#viewer-texture-blush-layer-0'); s = await state(page);
    assert.deepStrictEqual(s.blush.choice, { layer: 0, k: 2, level: 'custom', encoding: 'exact' }, 'a type click keeps the applied strength, not the cancelled one');
    assert.equal(s.blush.status, 'Preview, not applied yet: Custom (k 2) · Cheeks (Ppo)'); assert(same(await live(page), expected(0, 2)));
    await click(page, '#viewer-texture-cancel'); s = await state(page);
    assert.deepStrictEqual([s.blush.choice, s.blush.pending], [{ layer: 1, k: 2, level: 'custom', encoding: 'exact' }, false]);
    report.cases.push({ name: 'Cancel preview restores the applied choice; the next type click starts from it' });

    // Keyboard undo/redo from the panel: a click on its text leaves focus on the page body.
    await page.locator('#viewer-texture-blush-status').click(); await page.keyboard.press('Control+z'); await frames(page);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 1.05, encoding: 'exact' }, 'Ctrl+Z after a click in the panel');
    await page.keyboard.press('Control+y'); await frames(page); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 2, encoding: 'exact' });
    await page.focus('#viewer-texture-blush-before'); await page.keyboard.press('Control+z'); await frames(page);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 1.05, encoding: 'exact' }, 'Ctrl+Z on a panel button');
    await page.keyboard.press('Control+Shift+z'); await frames(page); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 2, encoding: 'exact' });
    await page.locator('#viewer-stage').click({ position: { x: 5, y: 5 } }).catch(() => {}); await page.keyboard.press('Control+z'); await frames(page);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 2, encoding: 'exact' }, 'a shortcut outside the tools is not taken');
    report.cases.push({ name: 'Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z from the blush panel' });

    // Exact pixels are the default save mode. Keeping the ASTC compression is the
    // opt-in choice under Advanced; this RGBA32 head cannot take it.
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = true; });
    assert.equal(await page.locator('#viewer-texture-blush-astc-keep').isDisabled(), true);
    assert.equal(await page.locator('#viewer-texture-blush-astc-keep').isChecked(), false);
    assert.equal(await page.locator('#viewer-texture-blush-astc-keep-hint').textContent(), 'This texture is not ASTC-compressed, so it is always saved as exact pixels.');
    assert.equal(await page.evaluate(() => ModelViewer.getTextureTools().setBlushEncoding('astc-keep')), false);
    assert.equal((await state(page)).blush.choice.encoding, 'exact');
    report.cases.push({ name: 'exact pixels by default; ASTC keep unavailable for a non-ASTC texture' });

    // Save through the product and check every authored mip of the written texture.
    await click(page, '#viewer-save');
    await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.recipePath); });
    const persistence = await page.evaluate(() => ModelViewer.getState().persistence); assert(!persistence.error, persistence.error);
    // The save summary names the encoding used for the baked blush.
    assert.deepStrictEqual(persistence.notes, [fixture.savedExact]);
    assert.ok((await page.locator('#viewer-save-status').textContent()).endsWith(' ' + fixture.savedExact));
    // Japanese sentences follow one another without a space after 。.
    await page.selectOption('#lang-select', 'ja');
    await page.waitForFunction(() => document.getElementById('viewer-texture-tab-blush').textContent === '頬紅の焼き込み', null, { timeout: 20000 });
    const jaSaved = await page.locator('#viewer-save-status').textContent();
    assert.ok(jaSaved.includes('。頬紅を正確なピクセル') && !/。 /.test(jaSaved), jaSaved);
    await page.selectOption('#lang-select', 'en');
    await page.waitForFunction(() => document.getElementById('viewer-texture-tab-blush').textContent === 'Bake blush', null, { timeout: 20000 });
    const written = py(`
import base64, json, sys, time
import UnityPy
from test_viewer_texture_blush import synthetic_payload, authored_images
from webtools.core import decode, texture_blush as tb
from webtools.core.model_materials import _original_mips
env = UnityPy.load(open(sys.argv[1], 'rb').read())
obj = next(o for o in env.objects if o.type.name == 'Texture2D')
texture = obj.read()
levels = [decode._android_image(texture, time.monotonic() + 60).convert('RGBA')] + [decode._android_image(p.read(), time.monotonic() + 60).convert('RGBA') for p in _original_mips(obj, texture)]
layer = tb.layer_bytes(synthetic_payload(), 1)
rows = []
for authored, level in zip(authored_images(), levels):
    expected, changed, _ = tb.bake_rgba(authored.tobytes(), authored.width, authored.height, layer, 2.0)
    rows.append({'exact': level.tobytes() == expected, 'changed': changed, 'alpha': level.tobytes()[3::4] == authored.tobytes()[3::4]})
print(json.dumps({'format': texture.m_TextureFormat, 'mips': texture.m_MipCount, 'levels': rows}))`, [persistence.previewPaths[0]]);
    assert.equal(written.format, 4); assert.equal(written.mips, 7);
    assert(written.levels.every(row => row.exact && row.alpha), JSON.stringify(written)); assert(written.levels[0].changed > 0 && written.levels[1].changed > 0);
    report.cases.push({ name: 'saved model bakes every authored mip in place', written });

    // A recipe restores the operation; the texture keeps its original pixels.
    await page.evaluate(rows => ModelViewer.restoreAuthoringState({ version: 1, savedSettingsEnabled: true, edits: [], unsupported: [], textures: rows }), [{ texture: edits[0].texture, sourceSha256: edits[0].sourceSha256, png: edits[0].png, kind: 'blush', blush: { layer: 0, k: 0.5 } }]);
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.k === 0.5 && !s.loading; });
    assert(same(await live(page), expected(0, 0.5)));
    await click(page, '#viewer-texture-undo'); await page.waitForFunction(() => !ModelViewer.getTextureTools().getState().pending);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 2, encoding: 'exact' }, 'undoing a recipe restore brings back the previous bake');
    assert(same(await live(page), expected(1, 2)));
    await click(page, '#viewer-texture-redo'); await page.waitForFunction(() => !ModelViewer.getTextureTools().getState().pending);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 0, k: 0.5, encoding: 'exact' });
    // Restoring a recipe without this texture removes the bake, also undoably.
    await page.evaluate(() => ModelViewer.restoreAuthoringState({ version: 1, savedSettingsEnabled: true, edits: [], unsupported: [], textures: [] }));
    // (In the blush tab a face without a bake starts the default preview again.)
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return !s.blush.committed && !s.loading && !s.editedTextures.length; });
    await click(page, '#viewer-texture-undo'); await page.waitForFunction(() => !ModelViewer.getTextureTools().getState().pending);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 0, k: 0.5, encoding: 'exact' });
    report.cases.push({ name: 'recipe restore, with undo and redo of the bake' });

    // Export PNG includes the bake; importing that PNG must not bake it twice.
    const exported = await page.evaluate(() => ModelViewer.getTextureTools().exportPNG().then(() => document.getElementById('viewer-texture-saved-path') ? document.getElementById('viewer-texture-saved-path').textContent : null));
    const savedPath = exported || await page.evaluate(() => { const e = Array.from(document.querySelectorAll('#viewer-texture-tools *')).find(n => !n.children.length && /\.png$/.test(n.textContent.trim()) && /[\\/]/.test(n.textContent)); return e && e.textContent.trim(); });
    assert.ok(savedPath && fs.existsSync(savedPath), 'Export PNG wrote a file: ' + savedPath);
    const exportedPixels = Buffer.from(py("import base64,json,sys;from PIL import Image;print(json.dumps(base64.b64encode(Image.open(sys.argv[1]).convert('RGBA').tobytes()).decode()))", [savedPath]), 'base64');
    assert(exportedPixels.equals(expected(0, 0.5)), 'the exported PNG is the texture as the game shows it');
    assert.equal(await page.evaluate(p => ModelViewer.getTextureTools().importPNGPath(p), savedPath), true);
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return !s.pending && !s.loading; });
    s = await state(page); assert.equal(s.blush.committed, null, 'the imported pixels replace the bake');
    assert(same(await live(page), exportedPixels), 'single bake in the 3D view');
    assert.match(s.status, /^The imported PNG is used as the final pixels/);
    assert.equal(s.blush.status, 'No blush');
    edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.equal(edits.length, 1); assert.equal(edits[0].blush, undefined); assert.equal(edits[0].kind, 'paint');
    assert(pngPixels(edits[0].png).equals(exportedPixels));
    await click(page, '#viewer-texture-undo'); await page.waitForFunction(() => !ModelViewer.getTextureTools().getState().pending);
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 0, k: 0.5, encoding: 'exact' }, 'undoing the import brings the bake back'); assert(same(await live(page), expected(0, 0.5)));
    await click(page, '#viewer-texture-redo'); await page.waitForFunction(() => !ModelViewer.getTextureTools().getState().pending);
    assert.equal((await state(page)).blush.committed, null); assert(same(await live(page), exportedPixels));
    fs.rmSync(savedPath, { force: true });
    report.cases.push({ name: 'Export PNG then Import PNG never bakes twice' });

    // Korean and Japanese labels.
    for (const [lang, tabText, medium, apply, types] of [['ko', '홍조 굽기', '보통', '홍조 적용', ['볼 홍조(Ppo)', '볼·콧등 홍조(Akarame)']], ['ja', '頬紅の焼き込み', '普通', '頬紅を適用', ['頬(Ppo)', '頬・鼻すじ(Akarame)']]]) {
      await page.selectOption('#lang-select', lang);
      await page.waitForFunction(text => document.getElementById('viewer-texture-tab-blush').textContent === text, tabText, { timeout: 20000 });
      const labels = await page.evaluate(() => ({ tab: document.getElementById('viewer-texture-tab-blush').textContent, medium: document.querySelector('#viewer-texture-blush-level-medium .viewer-texture-blush-name').textContent, apply: document.getElementById('viewer-texture-blush-apply').textContent,
        types: Array.from(document.querySelectorAll('#viewer-texture-blush-types .viewer-texture-blush-layer .viewer-texture-blush-name')).map(e => e.textContent) }));
      assert.deepStrictEqual(labels, { tab: tabText, medium, apply, types }, lang);
      // The blush types name a shape, never a strength.
      assert.ok(labels.types.every(text => !/진한|진하|濃/.test(text)), JSON.stringify(labels.types));
      // The status, the five levels and Apply in view together on a 1366x900
      // screen in this language too: as the tab opens and at the top of the box
      // (the type buttons share one row and have the same height).
      await page.setViewportSize({ width: 1366, height: 900 }); await page.evaluate(() => { document.querySelector('.viewer-texture-properties').scrollTop = 300; window.scrollTo(0, 0); });
      await reopenBlush(page); assertBlushInView(await blushLayout(page), lang + ' as the tab opens');
      await panelShot(page, path.join(evidence, 'panel-1366x900-' + lang + '.png'));
      assertBlushInView(await blushLayout(page, 'top'), lang);
      assert.equal(await page.locator('#viewer-texture-blush-game-level').textContent(), lang === 'ko' ? '‘약하게’ ≈ 게임 곡의 가장 진한 홍조' : '「薄く」≈ ゲームの楽曲で最も濃い頬紅');
      assert.equal(await page.locator('#viewer-texture-blush-remove').textContent(), lang === 'ko' ? '홍조 제거' : '頬紅を外す');
      assert.equal(await page.locator('#viewer-texture-blush-advanced-summary').textContent(), lang === 'ko' ? '고급 설정: 세기 값' : '詳細設定: 強さの値');
      // Reopening the tab started the default preview again; drop it.
      await click(page, '#viewer-texture-cancel'); assert.equal((await state(page)).blush.pending, false);
      await page.setViewportSize({ width: 1480, height: 1100 }); await frames(page);
      assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), lang === 'ko' ? '저장: 정확한 픽셀' : '保存: 正確なピクセル');
    }
    report.cases.push({ name: 'ko and ja labels' });

    // A recolour face texture is previewed on the head it replaces in the game.
    await page.selectOption('#lang-select', 'en');
    await page.evaluate(file => openModelViewer([file]), recolourModel);
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return ModelViewer.getState().loaded && !ModelViewer.getState().loading && s.textureCount > 1 && s.blush.cheek && !s.loading; });
    await page.evaluate(() => { const s = document.getElementById('viewer-shader'); if (s.value !== 'sifas') { s.value = 'sifas'; s.dispatchEvent(new Event('change', { bubbles: true })); } });
    await page.evaluate(() => ModelViewer.getTextureTools().openBlush());
    await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.rule.role === 'head' && b.cheek.loaded && b.previewing; });
    s = await state(page); assert.ok(s.blush.alerts.includes('Recolour suits of this costume replace this texture in the game: bake their recolour texture too.'));
    const attach = s.blush.eligible.find(row => row.role === 'attach'); assert.ok(attach, JSON.stringify(s.blush.eligible));
    await page.evaluate(texture => ModelViewer.getTextureTools().selectTexture(texture), attach.texture);
    await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.rule.role === 'attach' && b.proxy && b.previewing; });
    s = await state(page);
    assert.match(s.status, /^Pick a strength, check the 3D preview, then apply\.$/);
    assert.deepStrictEqual(s.blush.alerts.slice(0, 2), ["This recolour texture replaces the face texture of its recolour suit, so bake it as well as the costume's own face texture.", 'The 3D view shows this recolour texture on the face while this tab is open.']);
    assert(same(await live(page), expected(0, 1.65, fixture.recolour)), 'the face shows the baked recolour texture');
    await click(page, '#viewer-texture-blush-before'); assert(same(await live(page), recolour), 'Show before shows the recolour texture without the bake');
    await click(page, '#viewer-texture-blush-before'); await click(page, '#viewer-texture-blush-apply');
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; });
    assert(same(await live(page), expected(0, 1.65, fixture.recolour)));
    await page.evaluate(() => ModelViewer.getTextureTools().setTab('costume')); await frames(page);
    s = await state(page); assert.equal(s.blush.proxy, null); const head = await live(page);
    assert(!head || same(head, original), 'leaving the tab puts the costume face back');
    await page.evaluate(() => ModelViewer.getTextureTools().setTab('blush'));
    await page.waitForFunction(() => !!ModelViewer.getTextureTools().getState().blush.proxy); assert(same(await live(page), expected(0, 1.65, fixture.recolour)));
    edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.deepStrictEqual(edits.map(row => [row.texture.id, row.blush]), [[attach.texture.id, { layer: 0, k: 1.65, encoding: 'exact' }]]);
    report.cases.push({ name: 'recolour texture previewed on its head in 3D' });

    // An ASTC head: exact pixels by default; Advanced keeps the game's ASTC compression only on request.
    if (fixture.astcenc) {
      const saveNow = async () => {
        const previous = (await page.evaluate(() => ModelViewer.getState().persistence)).recipePath;
        await click(page, '#viewer-save');
        await page.waitForFunction(old => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.status === 'done' && p.recipePath && p.recipePath !== old); }, previous);
        const result = await page.evaluate(() => ModelViewer.getState().persistence); assert(!result.error, result.error); return result;
      };
      const writtenFormat = file => py("import json,sys,UnityPy;t=next(o.read() for o in UnityPy.load(open(sys.argv[1],'rb').read()).objects if o.type.name=='Texture2D');print(json.dumps([t.m_TextureFormat,t.m_MipCount]))", [file]);
      await page.evaluate(file => openModelViewer([file]), astcModel);
      await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return ModelViewer.getState().loaded && !ModelViewer.getState().loading && s.textureCount > 0 && s.blush.cheek && !s.loading; });
      await page.evaluate(() => ModelViewer.getTextureTools().openBlush());
      await page.waitForFunction(() => { const b = ModelViewer.getTextureTools().getState().blush; return b.rule && b.cheek.loaded && b.previewing; });
      await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = true; });
      assert.equal(await page.locator('#viewer-texture-blush-astc-keep').isDisabled(), false);
      assert.equal(await page.locator('#viewer-texture-blush-astc-keep').isChecked(), false, 'exact pixels are the default');
      assert.equal(await page.locator('#viewer-texture-blush-astc-keep-hint').textContent(), 'Smaller file and memory, but the 6×6 blocks the blush touches are compressed again, so nearby pixels change slightly too.');
      s = await state(page); assert.equal(s.blush.choice.encoding, 'exact'); assert.match(s.blush.status, /· Cheeks \(Ppo\)$/, 'the default save mode is not named');
      assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), 'Save: exact pixels (data about 9× larger)');
      assert.equal(await page.locator('#viewer-texture-blush-advanced-summary').textContent(), 'Advanced: strength value, keep ASTC');
      await click(page, '#viewer-texture-blush-apply'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; });
      let saved = await saveNow();
      assert.deepStrictEqual(saved.notes, [fixture.savedExact]); assert.deepStrictEqual(writtenFormat(saved.previewPaths[0]), [4, 7], 'exact pixels: lossless RGBA32');
      // A cancelled preview never comes back with the save-mode checkbox.
      await click(page, '#viewer-texture-blush-level-veryStrong'); await click(page, '#viewer-texture-cancel'); s = await state(page);
      assert.deepStrictEqual([s.blush.choice, s.blush.pending], [{ layer: 0, k: 1.65, level: 'medium', encoding: 'exact' }, false]);
      assert.equal(s.blush.status, 'Applied: Medium (k 1.65) · Cheeks (Ppo)');
      // Opt in: the choice is part of the operation, previewed like any other change and named in the status.
      await click(page, '#viewer-texture-blush-astc-keep'); s = await state(page);
      assert.deepStrictEqual(s.blush.choice, { layer: 0, k: 1.65, level: 'medium', encoding: 'astc-keep' }); assert(s.blush.previewing);
      assert.match(s.blush.status, /^Preview, not applied yet: Medium \(k 1\.65\) · Cheeks \(Ppo\) · Keep ASTC when saving$/);
      assert.deepStrictEqual(s.blush.displayed, { layer: 0, k: 1.65, encoding: 'astc-keep' }, 'the previewed strength is unchanged');
      // Only a request until Save reports what it wrote.
      assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), 'Save: keeping ASTC is requested');
      await click(page, '#viewer-texture-blush-apply'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.encoding === 'astc-keep' && !s.pending; });
      edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.deepStrictEqual(edits[0].blush, { layer: 0, k: 1.65, encoding: 'astc-keep' });
      saved = await saveNow();
      assert.deepStrictEqual(saved.notes, [fixture.savedAstc]); assert.deepStrictEqual(writtenFormat(saved.previewPaths[0]), [56, 7], 'ASTC 6x6 kept');
      assert.ok((await page.locator('#viewer-save-status').textContent()).endsWith(' ' + fixture.savedAstc));
      await click(page, '#viewer-texture-undo'); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 0, k: 1.65, encoding: 'exact' });
      report.cases.push({ name: 'ASTC head: exact pixels by default, ASTC kept on request, save summary names the mode; a cancelled level never returns with the checkbox' });
    }

    // Without a verified array the entry explains why and refuses to apply.
    fs.unlinkSync(fixture.cache);
    await page.evaluate(file => openModelViewer([file]), second);
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return ModelViewer.getState().loaded && !ModelViewer.getState().loading && s.textureCount > 0 && s.blush.cheek && !s.loading; });
    await page.evaluate(() => ModelViewer.getTextureTools().openBlush());
    await page.waitForFunction(() => !!ModelViewer.getTextureTools().getState().blush.rule);
    s = await state(page); assert.equal(s.blush.cheek.available, false);
    assert(await page.locator('#viewer-texture-blush-apply').isDisabled());
    assert.equal(await page.evaluate(() => ModelViewer.getTextureTools().applyBlush()), false);
    assert(/cheek_array/.test(await page.locator('#viewer-texture-blush-status').textContent()) || /cheek_array/.test(s.blush.status));
    assert(/cheek_array/.test(s.error) && !/Pick a strength/.test(s.status), 'the tool status explains instead of asking for a strength: ' + s.status + ' / ' + s.error);
    report.cases.push({ name: 'missing cheek array is explained', status: s.blush.status });

    assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error.stack || error); report.pageErrors = errors;
    if (page) { report.failureState = await page.evaluate(() => ModelViewer.getTextureTools().getState()).catch(() => null); await page.screenshot({ path: path.join(evidence, 'failure.png') }).catch(() => {}); }
    throw error;
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.log.end(); await new Promise(resolve => server.child.once('exit', resolve)).catch(() => {}); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.map(row => row.name), error: report.error }));
    fs.rmSync(library, { recursive: true, force: true });
    if (!keepEvidence && report.status === 'PASS') fs.rmSync(evidence, { recursive: true, force: true });
  }
}
main().catch(() => { process.exitCode = 1; });
