/* Actual100/256 small Unity source files, long UTF8 native paths, transactional
 * source limits and retained-library skeleton rebinding. Original neutral data.
 */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process'), { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-motion-sources-proof-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-motion-sources-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(models, { recursive: true });
const fixture = JSON.parse(execFileSync(python, ['-B', '-c', `import json,sys;sys.path.insert(0,'tests');from test_viewer_motion_library import make_many_motion_source_fixture;print(json.dumps(make_many_motion_source_fixture(sys.argv[1])))`, models], { cwd: product, encoding: 'utf8' }));
const sources = fixture.sources, allSources = [fixture.body_a, fixture.body_b, ...sources];
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashes = Object.fromEntries(allSources.map(file => [file, sha(file)]));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, stream }; } catch (_) {} await new Promise(resolve => setTimeout(resolve, 100)); }
  child.kill(); throw new Error('Product server did not become ready');
}
async function ready(page) { await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); }
async function select(page, index) {
  return page.evaluate(index => {
    const select = document.getElementById('viewer-motion'); select.value = 'Source pose ' + String(index).padStart(4, '0'); select.dispatchEvent(new Event('change', { bubbles: true }));
    const time = document.getElementById('viewer-time'); time.value = '.75'; time.dispatchEvent(new Event('input', { bubbles: true }));
    const state = ModelViewer.getState(); if (state.rig.selectedClip !== select.value) throw new Error('Requested pose not selected');
    return state.rig.bones.find(bone => bone.name.includes('LeftUpLeg'));
  }, index);
}
async function main() {
  let server, browser; const errors = [], requests = [], report = { cases: [], sourceBytes256: sources.slice(0, 256).reduce((sum, file) => sum + fs.statSync(file).size, 0) };
  try {
    server = await start();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    report.browser = { version: browser.version(), host: 'Linux Chromium with macOS host bridge stub', renderer: 'ANGLE SwiftShader' };
    const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } }), page = await context.newPage();
    await context.addInitScript(() => { localStorage.setItem('sifas_lang', 'en'); window.ElichikaDesktop = { platform: 'macos', version: 1, capabilities: [] }; });
    page.setDefaultTimeout(120000); page.on('pageerror', error => errors.push(String(error.stack || error)));
    page.on('request', request => { if (request.url().endsWith('/api/viewer/prepare')) { const payload = request.postDataJSON(); requests.push({ motions: (payload.motion_paths || []).length, models: payload.paths.length, requestBytes: Buffer.byteLength(request.postData(), 'utf8') }); } });
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, fixture.body_a); await ready(page);
    let previous;
    for (const count of [100, 256]) {
      const started = Date.now(); await page.evaluate(sources => ModelViewer.addMotion(sources), sources.slice(count === 100 ? 0 : 100, count)); await ready(page);
      const state = await page.evaluate(() => ModelViewer.getState());
      assert.deepStrictEqual(state.motionLibraryPaths, sources.slice(0, count)); assert.deepStrictEqual(state.loadedMotionPaths, sources.slice(0, count));
      assert.equal(state.rig.clipNames.filter(name => name.startsWith('Source pose')).length, count); assert.equal(state.rig.clipNames.length, count + 1); assert.equal(state.rig.internalClipCount, 0, 'only selected source files enter the clip choices');
      if (previous) { assert.equal(state.rig.selectedClip, previous.selectedClip); assert.equal(state.rig.time, previous.time); }
      const pose = await select(page, count - 1), probe = await page.evaluate(() => ModelViewer.renderProbe(23));
      assert(probe.ready && probe.glError === 0 && probe.chromaticSamples > 0);
      previous = (await page.evaluate(() => ModelViewer.getState())).rig;
      report.cases.push({ name: count + ' actual one-clip Unity source files', count, loadMs: Date.now() - started, choices: state.rig.clipNames.length, pose, probe, request: requests[requests.length - 1] });
    }
    assert(requests.find(request => request.motions === 100).requestBytes > 16 * 1024, 'long native UTF8 paths exercise the former request-body limit');
    assert(await page.locator('#viewer-add-motion').isDisabled(), 'capacity is reflected by the actual Add control');
    assert.equal(await page.locator('#viewer-motion-file-count').textContent(), '256');
    const stable = await page.evaluate(() => ({ state: ModelViewer.getState(), authoring: ModelViewer.getAuthoringState() })), requestCount = requests.length;
    const rejected = await page.evaluate(async source => { try { await ModelViewer.addMotion([source]); return { ok: true }; } catch (error) { return { ok: false, message: error.message, code: error.code, limit: error.limit, selectedFiles: error.selectedFiles }; } }, sources[256]);
    assert.equal(rejected.ok, false); assert.equal(rejected.code, 'motion_source_limit'); assert.equal(rejected.limit, 256); assert.equal(rejected.selectedFiles, 257); assert(rejected.message.includes('at most 256') && rejected.message.includes('Selected: 257')); assert.equal(requests.length, requestCount, 'frontend rejects capacity overflow before another conversion request');
    const http = await page.request.post(server.url + '/api/viewer/prepare', { data: { paths: [fixture.body_a], motion_paths: sources, rigged: true, auto_face: false } });
    const detail = await http.json(); assert.equal(http.status(), 400); assert.equal(detail.error_code, 'motion_source_limit'); assert.equal(detail.max_motion_files, 256); assert.equal(detail.motion_files, 257); assert(detail.error.includes('at most 256') && detail.error.includes('Selected: 257'));
    const afterRejected = await page.evaluate(() => ({ state: ModelViewer.getState(), authoring: ModelViewer.getAuthoringState() }));
    assert.equal(afterRejected.state.modelId, stable.state.modelId); assert.deepStrictEqual(afterRejected.state.motionLibraryPaths, stable.state.motionLibraryPaths); assert.deepStrictEqual(afterRejected.authoring, stable.authoring); assert.equal(afterRejected.state.rig.selectedClip, stable.state.rig.selectedClip); assert.equal(afterRejected.state.rig.time, stable.state.rig.time);
    report.rejection = { frontend: rejected, httpStatus: http.status(), backend: detail, displayPreserved: true };
    const oldFirst = await select(page, 0), oldLast = await select(page, 255);
    await page.evaluate(source => ModelViewer.open([source]), fixture.body_b); await ready(page);
    const rebound = await page.evaluate(() => ModelViewer.getState()); assert.deepStrictEqual(rebound.motionLibraryPaths, sources.slice(0, 256)); assert.deepStrictEqual(rebound.loadedMotionPaths, sources.slice(0, 256)); assert.deepStrictEqual(rebound.loadedPaths, [fixture.body_b]);
    const newFirst = await select(page, 0), newLast = await select(page, 255); assert.notEqual(newFirst.node, oldFirst.node, 'different model node identities require real rebinding'); assert(newFirst.quaternion.some((value, index) => Math.abs(value - newLast.quaternion[index]) > .01));
    for (const pair of [[oldFirst, newFirst], [oldLast, newLast]]) pair[0].quaternion.forEach((value, index) => assert(Math.abs(value - pair[1].quaternion[index]) < 1e-8));
    const probe = await page.evaluate(() => ModelViewer.renderProbe(23)); assert(probe.ready && probe.glError === 0 && probe.chromaticSamples > 0);
    report.rebound = { count: rebound.rig.clipNames.length, previousNode: oldFirst.node, reboundNode: newFirst.node, first: newFirst.quaternion, last: newLast.quaternion, probe };
    await page.locator('#viewer-stage canvas').screenshot({ path: path.join(evidence, '256-source-rebound.png') });
    for (const [file, hash] of Object.entries(hashes)) assert.equal(sha(file), hash, 'source immutable: ' + file);
    report.sources = Object.entries(hashes).map(([file, hash]) => ({ name: path.basename(file), before: hash, after: sha(file) }));
    assert.deepStrictEqual(errors, []); report.errors = errors; report.requests = requests; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.rmSync(library, { recursive: true, force: true }); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
