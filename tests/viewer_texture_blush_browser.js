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
// Where the status line and the Apply button sit against the settings scroller.
async function blushLayout(page, scroll) {
  return page.evaluate(scroll => {
    // The page itself scrolls the settings box into the window, as a user would.
    const box = document.querySelector('.viewer-texture-properties'); box.scrollTop = scroll === 'bottom' ? box.scrollHeight : 0; box.scrollIntoView({ block: 'nearest' });
    const view = box.getBoundingClientRect(), place = id => { const r = document.getElementById(id).getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), inside: r.height > 0 && r.top >= Math.max(0, view.top) - 1 && r.bottom <= Math.min(innerHeight, view.bottom) + 1 }; };
    return { scroller: { top: Math.round(view.top), bottom: Math.round(view.bottom), scrollTop: box.scrollTop, scrollHeight: box.scrollHeight }, status: place('viewer-texture-blush-status'), apply: place('viewer-texture-blush-apply'), before: place('viewer-texture-blush-before'), save: place('viewer-texture-blush-save-mode') };
  }, scroll);
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
      return { status: inside('viewer-texture-blush-status'), alerts: inside('viewer-texture-blush-alerts'), order: Array.from(panel.children).map(e => e.id || e.className) };
    });
    assert.ok(layout.status && layout.alerts, JSON.stringify(layout));
    assert.deepStrictEqual(layout.order.slice(1, 4), ['viewer-texture-blush-target', 'viewer-texture-blush-status', 'viewer-texture-blush-alerts']);
    assert.equal(layout.order[layout.order.length - 1], 'viewer-texture-blush-footer');
    // The status and the actions are both in view without scrolling, also on a
    // 1366x900 screen and with Advanced open and scrolled to its end.
    const layouts = [];
    for (const [width, height] of [[1480, 1100], [1366, 900]]) {
      await page.setViewportSize({ width, height }); await frames(page);
      for (const advanced of [false, true]) {
        await page.evaluate(open => { document.querySelector('.viewer-texture-blush-advanced').open = open; }, advanced); await frames(page);
        for (const scroll of advanced ? ['top', 'bottom'] : ['top']) {
          const where = await blushLayout(page, scroll); layouts.push({ width, height, advanced, scroll, where });
          assert.ok(where.apply.inside && where.before.inside && where.save.inside, 'actions and save line in view: ' + JSON.stringify(layouts[layouts.length - 1]));
          if (scroll === 'top') assert.ok(where.status.inside, 'status in view: ' + JSON.stringify(layouts[layouts.length - 1]));
        }
      }
    }
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = false; document.querySelector('.viewer-texture-properties').scrollTop = 0; });
    await page.setViewportSize({ width: 1480, height: 1100 }); await frames(page);
    // How Save writes this RGBA32 face is always in view.
    assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), 'Save: exact pixels');
    assert.match(await page.locator('#viewer-texture-blush-layer-1 .viewer-texture-blush-shape').textContent(), /^Band across the nose and both cheeks$/);
    const swatches = await page.evaluate(() => Array.from(document.querySelectorAll('#viewer-texture-blush-levels .viewer-texture-blush-level')).map(b => ({ id: b.dataset.blushLevel, colour: b.dataset.colour, text: b.textContent })));
    assert.deepStrictEqual(swatches.map(r => r.text), ['Very light', 'Light', 'Medium', 'Strong', 'Very strong']);
    assert.equal(new Set(swatches.map(r => r.colour)).size, 5, 'each level shows its own cheek-centre colour');
    for (let i = 1; i < 5; i++) { const a = s.blush.swatches.colours[i - 1], b = s.blush.swatches.colours[i]; assert(b[1] < a[1] && b[2] < a[2], 'neighbouring levels get darker'); }
    report.cases.push({ name: 'blush tab, defaults, swatches and caveats', choice: s.blush.choice, swatches });
    report.cases.push({ name: 'status, actions and save line in view at 1480x1100 and 1366x900', layouts });

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
    for (const [lang, tabText, medium, apply, types] of [['ko', '홍조 굽기', '보통', '홍조 적용', ['볼 홍조(Ppo)', '볼·콧등 홍조(Akarame)']], ['ja', '頬紅の焼き込み', '普通', '頬紅を適用', ['頬の赤み(Ppo)', '頬・鼻すじの赤み(Akarame)']]]) {
      await page.selectOption('#lang-select', lang);
      await page.waitForFunction(text => document.getElementById('viewer-texture-tab-blush').textContent === text, tabText, { timeout: 20000 });
      const labels = await page.evaluate(() => ({ tab: document.getElementById('viewer-texture-tab-blush').textContent, medium: document.querySelector('#viewer-texture-blush-level-medium .viewer-texture-blush-name').textContent, apply: document.getElementById('viewer-texture-blush-apply').textContent,
        types: Array.from(document.querySelectorAll('#viewer-texture-blush-types .viewer-texture-blush-layer .viewer-texture-blush-name')).map(e => e.textContent) }));
      assert.deepStrictEqual(labels, { tab: tabText, medium, apply, types }, lang);
      // The blush types name a shape, never a strength.
      assert.ok(labels.types.every(text => !/진한|진하|濃/.test(text)), JSON.stringify(labels.types));
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
      assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), 'Save: exact pixels (texture data about 9× larger) · keeping ASTC is under Advanced');
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
      assert.equal(await page.locator('#viewer-texture-blush-save-mode').textContent(), "Save: keeps the game's ASTC compression · only the blush blocks are compressed again");
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
