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
from test_viewer_texture_blush import head_fixture, synthetic_payload
from webtools.core import texture_blush as tb, viewer_texture_tools as textures
raw, images = head_fixture()
payload = synthetic_payload()
tb.CHEEK_SHA256 = hashlib.sha256(payload).hexdigest()
Path(sys.argv[1]).write_bytes(raw)
Path(sys.argv[2]).write_bytes(raw)
cache = textures._cheek_cache_file(); cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(payload)
print(json.dumps({"sha": tb.CHEEK_SHA256, "cache": str(cache), "width": images[0].width, "height": images[0].height,
                  "rgba": base64.b64encode(images[0].tobytes()).decode()}))
`, [path.join(models, 'ch0001_co0001.unity'), path.join(models, 'ch0001_co0001_copy.unity')]);
const source = path.join(models, 'ch0001_co0001.unity'), second = path.join(models, 'ch0001_co0001_copy.unity');
const original = Buffer.from(fixture.rgba, 'base64');
function expected(layer, k) {
  return Buffer.from(py(`
import base64, json, sys
from test_viewer_texture_blush import synthetic_payload
from webtools.core import texture_blush as tb
out, changed, _ = tb.bake_rgba(base64.b64decode(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), tb.layer_bytes(synthetic_payload(), int(sys.argv[4])), float(sys.argv[5]))
print(json.dumps(base64.b64encode(out).decode()))`, [fixture.rgba, String(fixture.width), String(fixture.height), String(layer), String(k)]), 'base64');
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
    assert.deepStrictEqual(s.blush.choice, { layer: 0, k: 1.65, level: 'medium' }); assert.equal(s.blush.cheek.source, 'cache');
    assert.equal(await page.locator('#viewer-texture-blush-level-medium').getAttribute('aria-checked'), 'true');
    assert.equal(await page.locator('#viewer-texture-blush-layer-0').getAttribute('aria-checked'), 'true');
    assert.match(await page.locator('#viewer-texture-blush-status').textContent(), /^Preview, not applied yet: Medium \(k 1\.65\) · Standard \(Ppo\)$/);
    assert.deepStrictEqual(s.blush.notes, ["The game's own song blush still appears on top during blush scenes.", "Android and iOS bundles are separate: bake each platform's file.", 'This file is the Android bundle.', 'Using the verified blush pattern saved from a costume you opened before.']);
    const swatches = await page.evaluate(() => Array.from(document.querySelectorAll('#viewer-texture-blush-levels .viewer-texture-blush-level')).map(b => ({ id: b.dataset.blushLevel, colour: b.dataset.colour, text: b.textContent })));
    assert.deepStrictEqual(swatches.map(r => r.text), ['Very light', 'Light', 'Medium', 'Strong', 'Very strong']);
    assert.equal(new Set(swatches.map(r => r.colour)).size, 5, 'each level shows its own cheek-centre colour');
    for (let i = 1; i < 5; i++) { const a = s.blush.swatches.colours[i - 1], b = s.blush.swatches.colours[i]; assert(b[1] < a[1] && b[2] < a[2], 'neighbouring levels get darker'); }
    report.cases.push({ name: 'blush tab, defaults, swatches and caveats', choice: s.blush.choice, swatches });

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
    s = await state(page); assert.deepStrictEqual(s.blush.committed, { layer: 1, k: 3 }); assert.equal(s.selection.undoCount, undoBefore + 1);
    let edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits());
    assert.equal(edits.length, 1); assert.deepStrictEqual(edits[0].blush, { layer: 1, k: 3 }); assert.equal(edits[0].kind, 'blush');
    assert(pngPixels(edits[0].png).equals(original), 'the recipe PNG holds the original, unbaked pixels');
    assert(same(await live(page), expected(1, 3))); assert(!(await page.locator('#viewer-save').isDisabled()));
    assert.match(await page.locator('#viewer-texture-blush-status').textContent(), /^Applied: Very strong \(k 3\) · Deep \(Akarame\)$/);
    // Undo/redo through the existing history buttons.
    await click(page, '#viewer-texture-undo'); s = await state(page); assert.equal(s.blush.committed, null);
    assert.equal((await page.evaluate(() => ModelViewer.getTextureTools().getEdits())).length, 0); const undone = await live(page); assert(!undone || same(undone, original));
    await click(page, '#viewer-texture-redo'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && !s.pending; });
    assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 3 });
    // Re-bake replaces the operation; undo returns to the previous one.
    await click(page, '#viewer-texture-blush-level-light'); await click(page, '#viewer-texture-blush-apply');
    await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.k === 1.05 && !s.pending; });
    edits = await page.evaluate(() => ModelViewer.getTextureTools().getEdits()); assert.deepStrictEqual(edits[0].blush, { layer: 1, k: 1.05 }); assert(pngPixels(edits[0].png).equals(original));
    assert(same(await live(page), expected(1, 1.05)), 'a re-bake starts from the original pixels');
    await click(page, '#viewer-texture-undo'); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 3 });
    await click(page, '#viewer-texture-redo'); assert.deepStrictEqual((await state(page)).blush.committed, { layer: 1, k: 1.05 });
    // Advanced numeric strength.
    await page.evaluate(() => { document.querySelector('.viewer-texture-blush-advanced').open = true; });
    const field = page.locator('#viewer-texture-blush-k'); await field.fill('2.0'); await field.press('Tab'); await frames(page);
    s = await state(page); assert.deepStrictEqual(s.blush.choice, { layer: 1, k: 2, level: 'custom' }); assert(same(await live(page), expected(1, 2)));
    await click(page, '#viewer-texture-blush-apply'); await page.waitForFunction(() => { const s = ModelViewer.getTextureTools().getState(); return s.blush.committed && s.blush.committed.k === 2 && !s.pending; });
    report.cases.push({ name: 'apply, undo/redo, re-bake without compounding and advanced strength' });

    // Save through the product and check every authored mip of the written texture.
    await click(page, '#viewer-save');
    await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.recipePath); });
    const persistence = await page.evaluate(() => ModelViewer.getState().persistence); assert(!persistence.error, persistence.error);
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
    report.cases.push({ name: 'recipe restore' });

    // Korean and Japanese labels.
    for (const [lang, tabText, medium, apply] of [['ko', '홍조 굽기', '보통', '홍조 적용'], ['ja', '頬紅の焼き込み', '普通', '頬紅を適用']]) {
      await page.selectOption('#lang-select', lang);
      await page.waitForFunction(text => document.getElementById('viewer-texture-tab-blush').textContent === text, tabText, { timeout: 20000 });
      const labels = await page.evaluate(() => ({ tab: document.getElementById('viewer-texture-tab-blush').textContent, medium: document.querySelector('#viewer-texture-blush-level-medium .viewer-texture-blush-name').textContent, apply: document.getElementById('viewer-texture-blush-apply').textContent }));
      assert.deepStrictEqual(labels, { tab: tabText, medium, apply }, lang);
    }
    report.cases.push({ name: 'ko and ja labels' });

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
