/* Actual picker -> donor WebGL -> Unity graft -> immutable output -> reopen. */
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-transplants-evidence-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-transplants-library-'));
const models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(models, 'wearer.unity'), donor = path.join(models, 'donor.unity');
const generated = spawnSync(python, ['-c', 'import sys;from pathlib import Path;from test_viewer_transplants import costume_fixture;raw=costume_fixture();Path(sys.argv[1]).write_bytes(raw);Path(sys.argv[2]).write_bytes(raw)', source, donor],
  { cwd: product, encoding: 'utf8', env: { ...process.env, PYTHONPATH: product + path.delimiter + __dirname } });
assert.equal(generated.status, 0, generated.stderr);
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const original = hash(source), donorOriginal = hash(donor);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { status: 'RUNNING', scope: 'Real local HTTP, neutral UnityFS, Chromium WebGL and legacy graft algorithms; no API mocks or game assets', cases: [] };
let server, browser, page;
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const logs = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(logs); child.stderr.pipe(logs); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw Error('Server exited');
    try { if ((await fetch(url + '/api/tools')).ok) return { child, url, logs }; } catch (_) {}
    await wait(100);
  }
  child.kill(); throw Error('Server did not become ready');
}
(async () => {
  try {
    server = await start();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); const errors = [], requests = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.url().endsWith('/api/viewer/transplant/run')) requests.push(JSON.parse(request.postData())); });
    page.setDefaultTimeout(45000); await page.goto(server.url);
    await page.waitForFunction(() => window.ModelViewer && typeof openModelViewer === 'function');
    await page.evaluate(() => { document.getElementById('viewer-auto-face').checked = false; });
    for (const operation of [
      { id: 'viewer-costume-transplant', value: 'costume', button: 'Transplant' },
      { id: 'viewer-part-transplant', value: 'part', button: 'Transplant' },
      { id: 'viewer-lower-transplant', value: 'lower', button: 'Replace lower body' }
    ]) {
      await page.evaluate(source => openModelViewer([source]), source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
      const before = await page.evaluate(() => ({ state: ModelViewer.getState(), edits: ModelViewer.getAuthoringState() }));
      assert.equal(before.edits.edits.length, 0, 'An unedited wearer must be transplantable');
      const panel = page.locator('#' + operation.id);
      await panel.evaluate(element => { element.open = true; });
      await panel.getByRole('button', { name: 'Choose donor costume', exact: true }).click();
      await page.locator('#picker-entries li').filter({ hasText: 'donor.unity' }).click();
      await page.waitForFunction(({ operation }) => ModelViewer.getState().transplants.donors.some(entry => entry.operation === operation && entry.donor), { operation: operation.value });
      await panel.locator('.viewer-transplant-stage canvas').waitFor({ state: 'visible' });
      if (operation.value === 'part') await panel.locator('select').first().selectOption('BreastSize');
      if (operation.value === 'lower') {
        await panel.locator('#' + operation.id + '-low').fill('.5');
        await panel.locator('#' + operation.id + '-high').fill('.96');
        const cuts = await page.evaluate(() => ModelViewer.getState().transplants.donors.find(entry => entry.operation === 'lower'));
        assert.equal(cuts.cutLow, .5); assert.equal(cuts.cutHigh, .96);
        await panel.scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(evidence, 'lower-cut-preview.png') });
      }
      await page.waitForFunction(({ id }) => !document.querySelector('#' + id + ' .viewer-primary').disabled, { id: operation.id });
      await panel.getByRole('button', { name: operation.button, exact: true }).click();
      await page.waitForFunction(previous => {
        const state = ModelViewer.getState(); return state.loaded && !state.loading && state.modelId !== previous && state.loadedPaths[0].includes('/transplant-');
      }, before.state.modelId);
      const after = await page.evaluate(() => ModelViewer.getState());
      const output = after.loadedPaths[0]; assert(fs.existsSync(output)); assert.notEqual(output, source);
      assert.equal(hash(source), original, 'The original wearer remains byte-identical');
      assert.equal(hash(donor), donorOriginal, 'The original donor remains byte-identical');
      assert.equal(requests.at(-1).state.edits.length, 0, 'The real endpoint supports unchanged source snapshots');
      assert.equal(requests.at(-1).operation, operation.value);
      if (operation.value === 'part') assert.equal(requests.at(-1).partRoot, 'BreastSize');
      if (operation.value === 'lower') {
        assert.equal(requests.at(-1).cutLow, .5); assert.equal(requests.at(-1).cutHigh, .96);
        assert((await panel.locator('.viewer-transplant-log').innerText()).includes('target drop: 1 tris   donor take: 1 tris'));
      }
      await page.screenshot({ path: path.join(evidence, operation.value + '-result.png') });
      report.cases.push({ operation: operation.value, currentEdits: requests.at(-1).state.edits.length, output, triangles: after.stats.triangles, originalUnchanged: true, donorUnchanged: true });
    }
    assert.deepEqual(errors, []); report.pageErrors = errors; report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.stack || String(error); process.exitCode = 1;
    if (page) {
      report.failureState = await page.evaluate(() => ({ state: ModelViewer.getState(), panels: Array.from(document.querySelectorAll('.viewer-transplant-panel')).map(node => ({ id: node.id, text: node.innerText })) })).catch(() => null);
      await page.screenshot({ path: path.join(evidence, 'failure.png') }).catch(() => {});
    }
  }
  finally {
    if (browser) await browser.close(); if (server) { server.child.kill('SIGTERM'); server.logs.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error }));
  }
})();
