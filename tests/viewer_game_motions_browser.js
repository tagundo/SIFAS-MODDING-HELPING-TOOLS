/* Real API/SSE/decryption/GLB import with an original encrypted motion fixture.
 * Real game-database category coverage lives in viewer_workbench_browser.js. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-game-motions-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', scope: 'Actual product HTTP/SSE/pack decryption/Unity-to-GLB/WebGL using an original neutral encrypted animation fixture; no original game audio or playback claim', cases: [] };
let child, browser;
const snapshot = page => page.evaluate(() => {
  const s = ModelViewer.getState();
  return { camera: s.camera, authoring: ModelViewer.getAuthoringState(), paths: s.loadedPaths, clips: s.rig.clipNames, selected: s.rig.selectedClip, triangles: s.sourceTriangles };
});
(async () => {
  try {
    child = spawn(process.env.VIEWER_PYTHON || 'python3', [path.join(__dirname, 'game_motions_browser_server.py')], { cwd: product, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
    const logs = fs.createWriteStream(path.join(evidence, 'server.log')); child.stderr.pipe(logs);
    const ready = await new Promise((resolve, reject) => {
      let output = ''; const timeout = setTimeout(() => reject(new Error('Motion fixture server did not start')), 20000);
      child.stdout.on('data', chunk => { output += chunk; if (output.includes('\n')) { try { const data = JSON.parse(output.split('\n')[0]); clearTimeout(timeout); resolve(data); } catch (error) { reject(error); } } });
      child.once('exit', code => reject(new Error('Motion fixture server exited ' + code)));
    });
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true, args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [{ name: 'phone-ko', width: 448, height: 998, lang: 'ko' }, { name: 'desktop-en', width: 1500, height: 1000, lang: 'en' }]) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: profile.name.startsWith('phone') });
      await context.addInitScript(lang => localStorage.setItem('sifas_lang', lang), profile.lang);
      const page = await context.newPage(), errors = [];
      page.setDefaultTimeout(45000); page.on('pageerror', error => { errors.push(String(error)); report.lastPageErrors = errors; });
      page.on('console', message => { if (message.type() === 'error') { report.consoleErrors = report.consoleErrors || []; report.consoleErrors.push(message.text()); } });
      await page.goto(ready.url); await page.waitForFunction(() => typeof openModelViewer === 'function' && window.ViewerGameMotions);
      await page.waitForFunction(() => document.getElementById('viewer-mesh-deleter'));
      await page.evaluate(model => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([model]); }, ready.model);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false, 'Pose and motion starts collapsed');
      await page.evaluate(() => {
        const bone = ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'BreastSize');
        const state = ModelViewer.getAuthoringState(); state.edits = [{ node: bone.node, method: 'node', scale: [1.15, 1.05, 1.1] }];
        ModelViewer.restoreAuthoringState(state);
        const fov = document.getElementById('viewer-fov'); fov.value = '48'; fov.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('viewer-adjustments').open = true;
      });
      const before = await snapshot(page);
      await page.locator('#viewer-game-motions').click();
      await page.waitForFunction(() => document.getElementById('viewer-motion-character').options.length > 1);
      await page.locator('#viewer-motion-character').selectOption('1');
      await page.waitForFunction(() => document.getElementById('viewer-game-motion-choice').value === 'idle:1');
      const dialog = await page.locator('#viewer-game-motions-dialog').evaluate(element => {
        const r = element.getBoundingClientRect(); return { width: r.width, height: r.height, within: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight };
      });
      assert(dialog.within, 'Motion picker stays in viewport');
      await page.locator('#viewer-motion-download').uncheck();
      await page.locator('#viewer-motion-import').click();
      await page.waitForFunction(() => !document.getElementById('viewer-game-motions-dialog').open && ModelViewer.getState().loadedPaths.length === 2 && !ModelViewer.getState().loading);
      const after = await snapshot(page);
      assert.deepStrictEqual(after.camera, before.camera, 'Import preserves camera exactly');
      assert.deepStrictEqual(after.authoring, before.authoring, 'Import preserves existing body edits');
      assert.equal(after.selected, before.selected, 'Import preserves selected pose');
      assert.equal(after.triangles, before.triangles, 'Animation import adds no geometry');
      assert(after.clips.includes('Imported motion fixture'), 'Imported encrypted clip is present in the real converted rig');
      const output = after.paths.find(value => value.includes('/game-motions/'));
      assert(output, 'Imported output is the motion cache');
      assert.equal(crypto.createHash('sha256').update(fs.readFileSync(output)).digest('hex'), ready.motion_sha256, 'Decrypted bytes exactly match original fixture');
      await page.locator('#viewer-motion').selectOption('Imported motion fixture');
      await page.locator('#viewer-play').click();
      await page.waitForFunction(() => ModelViewer.getState().rig.playing && ModelViewer.getState().rig.time > .1);
      await page.locator('#viewer-play').click();
      const probe = await page.evaluate(() => ModelViewer.renderProbe(33)); assert(probe.ready && probe.glError === 0 && probe.nonBackgroundSamples > 0);
      // Hold the actual old preparation response, then let a newer Open finish.
      // Releasing or cancelling that response must never retarget the new model.
      let release, intercepted;
      const gate = new Promise(resolve => { release = resolve; });
      const held = new Promise(resolve => { intercepted = resolve; });
      await page.route('**/api/viewer/prepare', async route => {
        const request = route.request().postDataJSON();
        if (request.paths && request.paths.includes(ready.alternate)) {
          const response = await route.fetch(); assert(response.ok(), 'Delayed old response is an actual successful preparation');
          intercepted(); await gate; await route.fulfill({ response }).catch(() => {});
        } else await route.continue().catch(() => {});
      });
      await page.evaluate(alternate => { window.__pendingMotionResult = null; ModelViewer.addMotion([alternate]).then(() => { window.__pendingMotionResult = 'done'; }, error => { window.__pendingMotionResult = error.name; }); }, ready.alternate);
      await held;
      await page.evaluate(replacement => ModelViewer.open([replacement]), ready.replacement);
      release();
      await page.waitForFunction(() => window.__pendingMotionResult !== null);
      const raced = await page.evaluate(() => ({ result: window.__pendingMotionResult, paths: ModelViewer.getState().paths, loaded: ModelViewer.getState().loadedPaths }));
      assert.equal(raced.result, 'AbortError'); assert.deepStrictEqual(raced.paths, [ready.replacement]); assert.deepStrictEqual(raced.loaded, [ready.replacement]);
      await page.unroute('**/api/viewer/prepare');
      await page.screenshot({ path: path.join(evidence, profile.name + '.png') });
      assert.deepStrictEqual(errors, []);
      report.cases.push({ profile, dialog, before, after, probe, raced, exactEncryptedImport: true, preservesBodyCameraAndPose: true, newerModelSurvivesOlderMotion: true, pageErrors: errors });
      await context.close();
    }
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = error.stack || String(error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close(); if (child && child.exitCode === null) child.kill('SIGTERM');
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error }));
  }
})();
