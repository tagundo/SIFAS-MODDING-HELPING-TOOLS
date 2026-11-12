/* Real page, donor inspection and Unity jobs; inject failures only at named boundaries. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'transplant-diagnostics-browser-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'transplant-diagnostics-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'wearer.unity'), donor = path.join(models, 'donor.unity');
execFileSync(python, ['-B', '-c', 'import sys;from pathlib import Path;from test_viewer_transplants import costume_fixture;raw=costume_fixture();Path(sys.argv[1]).write_bytes(raw);Path(sys.argv[2]).write_bytes(raw)', source, donor], { cwd: product, env: { ...process.env, PYTHONPATH: product + path.delimiter + path.join(product, 'tests') } });
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), hashes = [sha(source), sha(donor)], wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.pipe(log); child.stderr.pipe(log);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw Error('Product server did not become ready');
}
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    const panel = page.locator('#viewer-lower-transplant'), status = panel.locator('[role=status]'); await panel.evaluate(e => { e.open = true; });
    const original = await page.evaluate(() => ({ modelId: ModelViewer.getState().modelId, paths: ModelViewer.getState().loadedPaths, authoring: ModelViewer.getAuthoringState() }));
    async function pick() { await panel.getByRole('button', { name: 'Choose donor costume', exact: true }).click(); await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click(); }
    async function failure(name, url, handler, stage, expected) {
      await page.route(url, handler, { times: 1 }); await pick();
      await page.waitForFunction(() => document.querySelector('#viewer-lower-transplant [role=status]').classList.contains('viewer-warning'));
      const message = await status.textContent(); assert(message.includes('Lower body replacement') && message.includes(stage) && message.includes('donor.unity'), message);
      for (const text of expected) assert(message.includes(text), 'retains concrete failure reason: ' + message);
      const current = await page.evaluate(() => ({ modelId: ModelViewer.getState().modelId, paths: ModelViewer.getState().loadedPaths, authoring: ModelViewer.getAuthoringState() }));
      assert.deepStrictEqual(current, original, 'failed donor work preserves current model and authoring'); report.cases.push({ name, message });
    }
    for (const fallback of [false, true]) {
      const available = await page.evaluate(fallback => {
        if (!fallback) { window.__diagnosticPlatform = ElichikaPlatform; return typeof ElichikaPlatform.requestJSON === 'function' && typeof ElichikaPlatform.requestBytes === 'function'; }
        window.ElichikaPlatform = Object.assign({}, __diagnosticPlatform, { requestJSON: undefined, requestBytes: undefined }); return !ElichikaPlatform.requestJSON && !ElichikaPlatform.requestBytes;
      }, fallback);
      assert(available, 'shared request helpers are present in the actual product');
      const suffix = fallback ? 'fallback' : 'shared helper';
      await failure('non-JSON HTTP inspection ' + suffix, '**/api/viewer/transplant/inspect', route => route.fulfill({ status: 503, contentType: 'text/plain', body: 'Donor file is temporarily unreadable: disk I/O failure.' }), 'Donor inspection', ['503', 'disk I/O failure']);
      await failure('network inspection ' + suffix, '**/api/viewer/transplant/inspect', route => route.abort('failed'), 'Donor inspection', ['No HTTP response']);
      await failure('JSON preview preparation ' + suffix, '**/api/viewer/prepare', route => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: 'The donor renderer refers to missing mesh 123.' }) }), 'Donor preview preparation', ['422', 'missing mesh 123']);
      await failure('HTTP GLB download ' + suffix, '**/api/viewer/model/*.glb', route => route.fulfill({ status: 502, contentType: 'text/plain', body: 'GLB cache entry could not be read.' }), 'Donor preview download', ['502', 'cache entry could not be read']);
      await failure('corrupt GLB parser ' + suffix, '**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: Buffer.from('invalid GLB data') }), 'Donor preview parsing', ['JSON']);
    }
    await page.evaluate(() => { window.ElichikaPlatform = __diagnosticPlatform; });
    await pick(); await panel.locator('.viewer-transplant-stage canvas').waitFor({ state: 'visible' });
    const run = panel.getByRole('button', { name: 'Replace lower body', exact: true });
    await page.route('**/api/viewer/transplant/run', route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'The current wearer source changed: wearer.unity.' }) }), { times: 1 });
    await run.click(); await page.waitForFunction(() => !ModelViewer.getState().transplants.busy);
    let message = await status.textContent(); for (const text of ['Lower body replacement', 'Start transplant job', 'donor.unity', '409', 'current wearer source changed']) assert(message.includes(text), message);
    report.cases.push({ name: 'job start retains operation, stage, donor, HTTP status and backend reason', message });
    await page.locator('#viewer-lower-transplant-low').fill('8'); await page.locator('#viewer-lower-transplant-high').fill('9');
    await run.click(); await page.waitForFunction(() => !ModelViewer.getState().transplants.busy);
    message = await status.textContent(); for (const text of ['Lower body replacement', 'Graft model', 'wearer.unity']) assert(message.includes(text), message);
    assert(await status.evaluate(e => e.classList.contains('viewer-warning')), 'real graft failure is surfaced');
    assert(message.length > 80 && !message.endsWith('Load failed'), 'concrete underlying graft reason is retained');
    report.cases.push({ name: 'real lower graft failure uses last backend phase and wearer filename', message });
    // Correct the same operation and perform it twice; each new result reopens.
    await page.locator('#viewer-lower-transplant-low').fill('.5'); await page.locator('#viewer-lower-transplant-high').fill('.96');
    await page.route('**/api/viewer/prepare', route => route.fulfill({ status: 502, contentType: 'text/plain', body: 'Output bundle failed to deserialize: missing mesh reference 404.' }), { times: 1 });
    await run.click(); await page.waitForFunction(() => !ModelViewer.getState().transplants.busy);
    message = await status.textContent(); for (const text of ['Lower body replacement', 'Open transplant result', 'wearer.unity', '502', 'missing mesh reference 404']) assert(message.includes(text), message);
    assert.deepStrictEqual(await page.evaluate(() => ({ modelId: ModelViewer.getState().modelId, paths: ModelViewer.getState().loadedPaths, authoring: ModelViewer.getAuthoringState() })), original, 'failed output load preserves wearer');
    const reopen = panel.getByRole('button', { name: 'Open transplant result', exact: true }); assert(await reopen.isVisible()); await reopen.click();
    await page.waitForFunction(() => !ModelViewer.getState().transplants.busy && ModelViewer.getState().transplants.undoCount > 0);
    assert(await page.evaluate(() => ModelViewer.getState().loaded && ModelViewer.getEditingMetadata().available), 'published output can be opened after load failure');
    report.cases.push({ name: 'output reopen error retains outer operation and underlying loader request details, preserves wearer and keeps valid output available', message });
    await page.route('**/api/jobs/*/events', route => route.abort('connectionreset'), { times: 1 });
    await run.click();
    await page.waitForFunction(() => document.querySelector('#viewer-lower-transplant [role=status]').textContent.includes('Transplant progress stream'));
    message = await status.textContent(); for (const text of ['Lower body replacement', 'Transplant progress stream', 'donor.unity', 'job ', 'HTTP response status']) assert(message.includes(text), message);
    if (message.includes('reconnecting')) {
      assert(await page.evaluate(() => ModelViewer.getState().transplants.busy), 'temporary SSE interruption keeps the running job and reconnect behavior');
      await page.waitForFunction(() => !ModelViewer.getState().transplants.busy && !ModelViewer.getState().loading);
      assert(/Transplanted/.test(await status.textContent()), await status.textContent());
    } else {
      assert(message.includes('connection closed'), message);
      assert.equal(await page.evaluate(() => ModelViewer.getState().transplants.busy), false, 'a terminal EventSource error releases the busy state');
    }
    report.cases.push({ name: 'native failed progress connection identifies operation/file/last phase and retains native reconnect or terminal-close behavior', message });
    const outputs = [];
    for (let repeat = 0; repeat < 2; repeat++) {
      await run.click(); await page.waitForFunction(() => !ModelViewer.getState().transplants.busy && !ModelViewer.getState().loading);
      const result = await page.evaluate(() => ({ state: ModelViewer.getState(), editing: ModelViewer.getEditingMetadata() }));
      assert(result.state.loaded && result.editing.available && /Transplanted/.test(await status.textContent()), await status.textContent());
      assert.equal(result.state.loadedPaths.length, 1); const file = result.state.loadedPaths[0]; assert(fs.existsSync(file)); outputs.push({ file, sha256: sha(file) });
      if (repeat) assert.notEqual(outputs[0].file, file);
    }
    assert.equal(sha(outputs[0].file), outputs[0].sha256, 'later graft keeps previous output immutable');
    report.cases.push({ name: 'same lower operation recovers from failure and publishes two independently reopened valid Unity copies', outputs });
    assert.deepStrictEqual([sha(source), sha(donor)], hashes); assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence, error: report.error })); }
}
main().catch(() => { process.exitCode = 1; });
