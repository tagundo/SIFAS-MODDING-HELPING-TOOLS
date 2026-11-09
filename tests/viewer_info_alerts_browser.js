/* Real viewer/DOM/WebGL with controlled prepare diagnostics. No game assets. */
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-info-alerts-'));
fs.mkdirSync(evidence, { recursive: true });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  let child, browser;
  const report = { status: 'RUNNING', scope: 'Product DOM/WebGL and actual Info activation with controlled prepare warnings/errors', cases: [] };
  try {
    const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
    const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
      { cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-alert-library-')) }, stdio: 'ignore' });
    const url = 'http://127.0.0.1:' + port;
    let ready = false;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(url + '/api/tools')).ok) { ready = true; break; } } catch (_) {} await pause(100); }
    assert(ready, 'Product server starts');
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = []; page.on('pageerror', error => errors.push(String(error)));
    await page.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const model = fixture({ allSaved: true }); let warnings = [], failure = '', prepares = 0;
    await page.route('**/api/viewer/prepare', route => {
      prepares++;
      return route.fulfill({ status: failure ? 422 : 200, contentType: 'application/json', body: JSON.stringify(failure ? { error: failure } : {
        id: 'info-alert-' + prepares, url: '/api/viewer/model/info-alert.glb', stats: { meshes: 3, triangles: 11578 }, rig: model.rig, warnings }) });
    });
    await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: model.glb }));
    await page.goto(url); await page.waitForFunction(() => window.ModelViewer && typeof openModelViewer === 'function');
    const open = source => page.evaluate(source => openModelViewer([source]), source);
    const info = page.locator('#viewer-info'), summary = page.locator('#viewer-info > summary');
    await open('/synthetic/costume.unity');
    assert.equal(await info.getAttribute('open'), null, 'Model ready and routine help never open Info');
    warnings = [{ code: 'face_source_unavailable', message: 'The original face is unavailable. The costume is still shown; check the asset connection and try again.' }];
    await open('/synthetic/costume.unity');
    assert(await info.evaluate(element => element.open), 'An unseen face failure is shown');
    assert(await page.locator('#viewer-warning').isVisible());
    assert(!await page.locator('#viewer-status').isVisible(), 'Automatic notice omits routine model statistics');
    assert(!await page.locator('#viewer-quality-help').isVisible());
    assert(!await page.locator('#viewer-info .viewer-gesture-help').isVisible());
    await page.screenshot({ path: path.join(evidence, 'new-face-warning.png') });
    await summary.click();
    await page.evaluate(() => ModelViewer.addMotion(['/synthetic/motion-one.unity']));
    assert(!await info.evaluate(element => element.open), 'Acknowledged identical warning stays closed after loading motion');
    assert(await info.evaluate(element => element.classList.contains('viewer-info-alert')), 'The warning indicator remains available');
    assert((await page.locator('#viewer-warning').textContent()).includes('The original face is unavailable.'));
    await page.setViewportSize({ width: 1180, height: 820 }); await page.evaluate(() => ModelViewer.renderProbe());
    assert(!await info.evaluate(element => element.open), 'Layout/render/status refresh cannot reopen a known alert');
    await summary.focus(); await page.keyboard.press('Enter');
    assert(await info.evaluate(element => element.open));
    assert(await page.locator('#viewer-status').isVisible());
    assert(await page.locator('#viewer-quality-help').isVisible(), 'Explicit keyboard Info access shows the full help');
    assert(await page.locator('#viewer-info .viewer-gesture-help').isVisible());
    await page.keyboard.press('Enter');
    warnings = [{ code: 'face_source_unavailable', message: 'The original face could not be opened. The costume is still shown.' }];
    await page.evaluate(() => ModelViewer.addMotion(['/synthetic/motion-two.unity']));
    assert(await info.evaluate(element => element.open), 'A changed real face failure opens a new compact notice');
    assert((await page.locator('#viewer-warning').textContent()).includes('could not be opened'));
    await summary.click(); failure = 'A newly selected motion file is invalid.';
    await open('/synthetic/invalid-motion.unity');
    assert(await info.evaluate(element => element.open), 'An unseen prepare error still opens');
    assert(await page.locator('#viewer-status.error').isVisible());
    await summary.click(); await open('/synthetic/invalid-motion.unity');
    assert(!await info.evaluate(element => element.open), 'Dismissed identical error is retained without reopening');
    failure = 'A different motion file could not be read.'; await open('/synthetic/different-motion.unity');
    assert(await info.evaluate(element => element.open), 'A different error is never muted');
    report.cases.push({ routineHelpClosed: true, newFaceWarningCompact: true, motionReloadRetainsAcknowledgement: true,
      indicatorRetained: true, keyboardFullInfo: true, changedWarningsAndErrorsOpen: true, prepares });
    assert.deepEqual(errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (child) child.kill(); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence })); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
