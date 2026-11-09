/* Independent Pose/Body/Expression panels through real HTTP, Unity and export.
 * The macOS message stub only enables native keyboard routing; no successful
 * model, editing or export API response is intercepted. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-pose-body-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-pose-body-library-'));
const source = path.join(library, 'extracted/3d_model/neutral.unity');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(path.dirname(source), { recursive: true });
const original = fs.readFileSync(path.join(product, 'tests/fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, original);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('Product server was not ready');
}
async function snapshot(page) {
  await frames(page);
  return page.evaluate(() => {
    const s = ModelViewer.getState();
    return { modelId: s.modelId, camera: s.camera, authoring: ModelViewer.getAuthoringState(),
      motion: { clip: s.rig.selectedClip, time: s.rig.time, playing: s.rig.playing },
      panels: Object.fromEntries(['viewer-adjustments', 'viewer-body-adjustments', 'viewer-expression-adjustments'].map(id => [id, document.getElementById(id).open])) };
  });
}
async function target(page, selector, minHeight) {
  const locator = page.locator(selector);
  assert(await locator.isVisible(), selector + ' must already be visible without reopening any panel');
  await locator.scrollIntoViewIfNeeded(); await frames(page);
  const metric = await locator.evaluate(element => {
    const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { width: r.width, height: r.height, top: r.top, bottom: r.bottom,
      hit: hit === element || element.contains(hit), visible: !!element.getClientRects().length };
  });
  assert(metric.visible && metric.hit && metric.height >= minHeight, selector + ' keeps a visible, hittable platform target: ' + JSON.stringify(metric));
  return metric;
}
function retained(before, after, label) {
  assert.equal(after.modelId, before.modelId, label + ': same model');
  assert.deepStrictEqual(after.camera, before.camera, label + ': camera preserved');
  assert.deepStrictEqual(after.authoring, before.authoring, label + ': body edits preserved');
}
async function run() {
  let server, browser;
  const report = { status: 'RUNNING', scope: 'Real HTTP/Unity/WebGL shared UI and serialized export; native keyboard adapter is a host stub, not a macOS/Android execution claim', cases: [] };
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [
      { name: 'phone-ko', width: 448, height: 998, locale: 'ko', touch: true, pose: '포즈·모션', body: '체형·의상' },
      { name: 'fold-ja', width: 853, height: 1200, locale: 'ja', touch: true, pose: 'ポーズ・モーション', body: '体型・衣装' },
      { name: 'mac-en', width: 1360, height: 900, locale: 'en', mac: true, pose: 'Pose and motion', body: 'Body and outfit' }
    ]) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch });
      await context.addInitScript(({ locale, mac }) => {
        localStorage.setItem('sifas_lang', locale);
        if (mac) {
          window.ElichikaDesktop = { platform: 'macos', version: 1, language: locale, capabilities: [] };
          window.webkit = { messageHandlers: { elichika: { postMessage() {} } } };
        }
      }, profile);
      const page = await context.newPage(), errors = [], requests = [];
      page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => { if (request.url().includes('/api/viewer/edit/export')) requests.push(JSON.parse(request.postData())); });
      await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
      await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      const initial = await snapshot(page);
      assert.equal(initial.panels['viewer-adjustments'], false, 'Pose starts collapsed');
      assert(initial.panels['viewer-body-adjustments'] && initial.panels['viewer-expression-adjustments'], 'Body and Expression start independently open');
      const structure = await page.evaluate(() => {
        const pose = document.getElementById('viewer-adjustments'), body = document.getElementById('viewer-body-adjustments'), expression = document.getElementById('viewer-expression-adjustments');
        return { siblings: pose.parentElement === body.parentElement && body.parentElement === expression.parentElement,
          disjoint: !pose.contains(body) && !body.contains(pose) && !body.contains(expression),
          motionInPose: pose.contains(document.getElementById('viewer-motion')) && !body.contains(document.getElementById('viewer-motion')),
          bodyInBody: ['viewer-editor-tabs', 'viewer-shared-bone-editor', 'viewer-saved-nodes'].every(id => body.contains(document.getElementById(id)) && !pose.contains(document.getElementById(id))),
          uniqueControls: ['viewer-motion', 'viewer-time', 'viewer-editor-tabs', 'viewer-shared-bone-editor', 'viewer-node-fields'].every(id => document.querySelectorAll('#' + id).length === 1) };
      });
      assert(Object.values(structure).every(Boolean), 'The real controls are separate sibling panels with no duplicates');
      assert.equal(await page.locator('#viewer-adjustments > summary').innerText(), profile.pose);
      assert.equal(await page.locator('#viewer-body-adjustments > summary').innerText(), profile.body);
      const minHeight = profile.mac ? 34 : 44;
      await target(page, '#viewer-adjustments > summary', minHeight);
      await target(page, '#viewer-body-adjustments > summary', minHeight);
      await page.locator('#viewer-adjustments > summary').click();
      const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
      await page.locator('#viewer-motion').selectOption(clip);
      await page.locator('#viewer-time').press('Home');
      await page.locator('#viewer-editor-mesh-tab').click();
      await page.locator('#viewer-node-editor > summary').click();
      await page.locator('#viewer-node-filter').selectOption('all');
      const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'LeftUpLeg').node);
      await page.locator('#viewer-node').selectOption(String(node));
      await page.locator('#viewer-save-method').selectOption('mesh');
      const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="Y"]');
      await field.fill('1.125'); await field.dispatchEvent('change');
      assert.equal(await page.locator('#viewer-save').isDisabled(), false);
      const beforeFolds = await snapshot(page);
      await page.locator('#viewer-adjustments > summary').click();
      assert.equal(await page.locator('#viewer-motion').isVisible(), false);
      assert.equal(await page.locator('#viewer-body-adjustments').evaluate(element => element.open), true);
      const bodyHit = await target(page, 'input[data-viewer-node-kind="scale"][data-axis="Y"]', minHeight);
      retained(beforeFolds, await snapshot(page), 'Closing Pose');
      // Invalid input deliberately does not replace the last valid edit. Its
      // bubbled input must still disable Save from the new Body event root.
      await field.fill('0');
      const invalid = await page.evaluate(() => ({ disabled: document.getElementById('viewer-save').disabled,
        raw: document.querySelector('input[data-viewer-node-kind="scale"][data-axis="Y"]').value,
        invalid: document.querySelector('input[data-viewer-node-kind="scale"][data-axis="Y"]').validity.customError,
        edits: ModelViewer.getAuthoringState().edits }));
      assert(invalid.disabled && invalid.invalid && invalid.raw === '0');
      assert.deepStrictEqual(invalid.edits, beforeFolds.authoring.edits, 'Invalid drafts retain the previous valid edit');
      if (profile.mac) {
        await field.focus(); await page.keyboard.press('Meta+s'); await frames(page);
        assert.equal(requests.length, 0, 'Native Save must not discard invalid body input and export stale edits');
        assert.equal(await field.inputValue(), '0', 'Native Save preserves the invalid draft for correction');
        assert.equal(await page.locator('#viewer-save').isDisabled(), true);
      }
      await field.fill('1.25'); await field.dispatchEvent('change');
      assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'Correcting the Body draft reenables Save');
      assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false);
      const pendingBody = await snapshot(page);
      await page.locator('#viewer-body-adjustments > summary').click();
      assert.equal(await page.locator('#viewer-editor-tabs').isVisible(), false);
      assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false);
      await page.locator('#viewer-adjustments > summary').click();
      const poseHit = await target(page, '#viewer-motion', minHeight);
      await page.locator('#viewer-time').press('End');
      assert((await snapshot(page)).motion.time > 1, 'The visible Pose time control changes the actual motion');
      await page.locator('#viewer-time').press('Home');
      await page.locator('#viewer-play').click();
      await page.waitForFunction(() => ModelViewer.getState().rig.playing && ModelViewer.getState().rig.time > .05);
      await page.locator('#viewer-play').click();
      const afterMotion = await snapshot(page);
      assert(!afterMotion.motion.playing && afterMotion.motion.time > 0);
      assert.equal(afterMotion.panels['viewer-body-adjustments'], false, 'Pose controls must not reopen Body');
      retained(pendingBody, afterMotion, 'Pose playback while Body is closed');
      await page.locator('#viewer-body-adjustments > summary').focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('#viewer-body-adjustments').evaluate(element => element.open), true);
      assert.equal(await field.inputValue(), '1.25');
      retained(pendingBody, await snapshot(page), 'Keyboard reopening Body');
      await page.locator('#viewer-expression-adjustments > summary').click();
      assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), true);
      assert.equal(await page.locator('#viewer-body-adjustments').evaluate(element => element.open), true);
      await page.locator('#viewer-expression-adjustments > summary').click();
      await page.locator('#viewer-adjustments > summary').click();
      if (profile.mac) {
        await field.evaluate(element => { window.__bodyBlurred = false; element.addEventListener('blur', () => { __bodyBlurred = true; }, { once: true }); });
        await field.focus(); await page.keyboard.press('Meta+s');
        await page.waitForFunction(() => window.__bodyBlurred);
      } else {
        await page.locator('#viewer-save-panel > summary').click(); await page.locator('#viewer-save').click();
      }
      await page.waitForFunction(() => ModelViewer.getState().persistence.outputPaths.length > 0 && !ModelViewer.getState().persistence.busy);
      const saved = await page.evaluate(() => ModelViewer.getState().persistence);
      assert.equal(saved.status, 'done'); assert.equal(requests.length, 1, 'Exactly one intentional body export occurred');
      assert(requests[0].state.edits.some(edit => edit.node === node && edit.method === 'mesh' && edit.scale[1] === 1.25));
      assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false, 'Saving does not open Pose');
      assert.equal(await page.locator('#viewer-body-adjustments').evaluate(element => element.open), true);
      assert(saved.outputPaths.every(file => fs.existsSync(file)));
      const recipe = JSON.parse(fs.readFileSync(saved.recipePath));
      assert(recipe.state.edits.some(edit => edit.node === node && edit.scale[1] === 1.25));
      assert.deepStrictEqual((await snapshot(page)).camera, initial.camera);
      const probe = await page.evaluate(() => ModelViewer.renderProbe(13)); assert(probe.ready && probe.glError === 0);
      await page.screenshot({ path: path.join(evidence, profile.name + '.png') });
      assert.deepStrictEqual(errors, []);
      report.cases.push({ profile, structure, initialPanels: initial.panels, bodyHit, poseHit, invalid,
        beforeFolds, pendingBody, afterMotion, saved: { status: saved.status, outputs: saved.outputPaths.length }, nativeShortcut: !!profile.mac });
      await context.close();
    }
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'The source Unity model remains unchanged');
    report.sourceSha256 = sha(original); report.status = 'PASS';
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end(); }
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
