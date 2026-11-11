/* Actual Korean controls, HTTP/Unity and measured hit boxes. Optional frozen CSS
 * supplies the before comparison; API responses and button content stay real. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-compact-buttons-'));
const baseline = process.env.BASELINE_STYLE_DIR;
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-compact-buttons-library-'));
const source = path.join(library, 'extracted/3d_model/neutral-button-layout.unity');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
execFileSync(python, ['-c', "import sys;from pathlib import Path;sys.path.insert(0,'tests');from test_model_outlines import colored_fixture;Path(sys.argv[1]).write_bytes(colored_fixture())", source], { cwd: product });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex'), sourceHash = sha(fs.readFileSync(source));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function boot(module, cwd, name) {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, name + '-server.log'));
  const child = spawn(python, ['-m', module, '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd, env: { ...process.env, SUKUSTA_DIR: library, PYTHONPATH: [product, repo, process.env.PYTHONPATH || ''].join(path.delimiter) }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 150; n++) { if (child.exitCode !== null) throw new Error(name + ' exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); }
  throw new Error(name + ' did not become ready');
}
async function show(page, selector) {
  const target = page.locator(selector).first();
  await target.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await target.scrollIntoViewIfNeeded(); await frames(page); return target;
}
async function metric(page, selector) {
  const target = await show(page, selector);
  return target.evaluate(node => {
    const box = node.getBoundingClientRect(), parent = node.parentElement.getBoundingClientRect(), range = document.createRange(); range.selectNodeContents(node);
    const text = range.getBoundingClientRect(), hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return { text: node.textContent.trim(), x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom,
      parentWidth: parent.width, textWidth: text.width, textHeight: text.height, textFits: text.width <= box.width + 1 && text.height <= box.height + 1,
      hit: hit === node || node.contains(hit), clippedX: box.left < -1 || box.right > innerWidth + 1,
      disabled: !!node.disabled, coarse: matchMedia('(pointer:coarse)').matches };
  });
}
function checkButtons(metrics, profile, phase) {
  for (const [name, box] of Object.entries(metrics)) {
    assert(box.width > 0 && box.height > 0 && !box.clippedX && box.textFits, name + ' fits without clipping: ' + JSON.stringify(box));
    assert(box.hit, name + ' remains an actual pointer target: ' + JSON.stringify(box));
    if (phase === 'after') {
      assert(box.height >= (profile.touch ? 44 : 32) - .5, name + ' preserves platform target height: ' + JSON.stringify(box));
      if (profile.touch) assert(box.width >= 44 - .5, name + ' preserves touch target width');
      else assert(box.height <= 40, name + ' has a compact desktop row: ' + JSON.stringify(box));
    }
  }
}
async function main() {
  const report = { status: 'RUNNING', scope: 'Korean shared UI in actual host Chromium; Mac adapter selects desktop CSS only, touch profile emulates coarse pointer; not native device QA', baselineCSS: baseline || null, cases: [] };
  let browser, tools, admin;
  try {
    [tools, admin] = await Promise.all([boot('webtools', product, 'tools'), boot('adminui', repo, 'admin')]);
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [{ name: 'mac-desktop', width: 1440, height: 1100, mac: true }, { name: 'desktop', width: 1440, height: 1100 }, { name: 'phone-portrait', width: 390, height: 844, touch: true }]) {
      const observations = {};
      for (const phase of baseline ? ['before', 'after'] : ['after']) {
        const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch });
        await context.addInitScript(({ mac }) => { localStorage.setItem('sifas_lang', 'ko'); if (mac) { window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'ko', capabilities: [] }; window.webkit = { messageHandlers: { elichika: { postMessage() {} } } }; } }, { mac: !!profile.mac });
        if (phase === 'before') {
          for (const [route, name] of [['**/static/style.css', 'style.css'], ['**/static/viewer-transplants.css', 'viewer-transplants.css'], ['**/ui/style.css', 'admin-style.css']]) {
            const file = path.join(baseline, name); assert(fs.existsSync(file), 'Frozen before CSS exists: ' + file);
            await context.route(route, request => request.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(file) }));
          }
        }
        const page = await context.newPage(), errors = [], requests = [];
        page.on('pageerror', error => errors.push(String(error.stack || error))); page.on('request', request => requests.push({ method: request.method(), url: request.url() })); page.setDefaultTimeout(30000);
        await page.goto(tools.url); await page.waitForFunction(() => document.querySelector('#tool-list button[data-id="costume_packer"]'));
        await page.locator('#tool-list button[data-id="costume_packer"]').click();
        await page.locator('[data-mode="multi"]').click();
        const metrics = { toolRun: await metric(page, '#tool-form .run-btn'), addFiles: await metric(page, '[data-paths-add]') };
        await (await show(page, '[data-paths-add]')).click();
        await page.locator('#picker-entries li').filter({ hasText: '3d_model' }).click();
        await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden') && document.querySelector('#picker-entries input[data-picker-file]'));
        await page.locator('#picker-entries input[data-picker-file]').first().check();
        metrics.pickerAdd = await metric(page, '#picker-add-selected');
        await page.locator('#picker-add-selected').click();
        assert.equal(await page.locator('#tool-form .multi-list .multi-rm').count(), 1, 'One picker confirmation populates the actual selected-files list');
        await show(page, '#tool-form .run-btn'); await page.screenshot({ path: path.join(evidence, profile.name + '-' + phase + '-asset-tool.png') });

        await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
        await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().outlines.meshes.length > 0);
        const beforeState = await page.evaluate(() => ({ id: ModelViewer.getState().modelId, authoring: ModelViewer.getAuthoringState(), camera: ModelViewer.getState().camera }));
        for (const [name, selector] of Object.entries({ fileAdd: '#viewer-add', fileGame: '#viewer-game-assets', fileSettings: '#viewer-panel-settings', fileOpen: '#viewer-load', outlineReset: '#viewer-outline-reset', outlineAbsolute: '#viewer-outline-absolute-apply', outlineDiagnostics: '#viewer-outline-diagnostics-copy', outlineUndo: '#viewer-outline-undo', motionAdd: '#viewer-add-motion', motionGame: '#viewer-game-motions', donorChoose: '#viewer-costume-transplant [data-transplant-label="Choose donor costume"]', donorGame: '#viewer-costume-transplant [data-transplant-label="Load donor from game"]' })) metrics[name] = await metric(page, selector);
        await show(page, '#viewer-outline-absolute-apply'); await page.screenshot({ path: path.join(evidence, profile.name + '-' + phase + '-outline.png') });
        assert.deepStrictEqual(await page.evaluate(() => ({ id: ModelViewer.getState().modelId, authoring: ModelViewer.getAuthoringState(), camera: ModelViewer.getState().camera })), beforeState, 'Layout inspection preserves edits and camera');
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
        assert(!overflow, 'No page horizontal overflow in ' + profile.name);

        const adminPage = await context.newPage(); adminPage.on('pageerror', error => errors.push(String(error.stack || error))); await adminPage.goto(admin.url);
        await adminPage.waitForFunction(() => document.querySelector('#tool-list button[data-id="backup"]'));
        await adminPage.locator('#tool-list button[data-id="backup"]').click();
        metrics.serverRun = await metric(adminPage, '#tool-form .run-btn');
        metrics.serverTool = await metric(adminPage, '#tool-list button[data-id="backup"]');
        assert(!(await adminPage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), 'Server content has no horizontal overflow');
        await adminPage.screenshot({ path: path.join(evidence, profile.name + '-' + phase + '-server-content.png') });
        checkButtons(metrics, profile, phase); assert.deepStrictEqual(errors, []);
        assert(!requests.some(request => request.method === 'POST' && /\/api\/(?:run|viewer\/edit|viewer\/transplant\/run)/.test(request.url)), 'Measurement never executes a tool, edits, exports or transplants');
        observations[phase] = { metrics, overflow, pageErrors: errors };
        await context.close();
      }
      if (baseline && !profile.touch) {
        for (const name of ['toolRun', 'outlineReset', 'outlineAbsolute', 'outlineDiagnostics', 'serverRun']) {
          const before = observations.before.metrics[name], after = observations.after.metrics[name];
          assert(after.width <= before.width + 1 && after.height <= before.height + 1, name + ' must not grow');
        }
        assert(observations.after.metrics.toolRun.width < observations.before.metrics.toolRun.width * .7, 'The desktop tool action no longer stretches across the settings column');
        assert(observations.after.metrics.outlineReset.width < observations.before.metrics.outlineReset.width * .9, 'The outline reset no longer stretches across its grid row');
        assert(observations.after.metrics.serverRun.width < observations.before.metrics.serverRun.width * .7, 'Server tool execution no longer stretches across its form');
      }
      report.cases.push({ profile, ...observations });
    }
    assert.equal(sha(fs.readFileSync(source)), sourceHash, 'Model source is unchanged');
    report.sourceHash = sourceHash; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close(); for (const server of [tools, admin]) if (server) { server.child.kill('SIGTERM'); server.stream.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error || null }));
  }
}
main();
