/* Model minimization through actual HTTP, Unity, DOM, export and WebGL.
 * The quality wrapper only observes the real camera passed to rendering.
 * The Mac/native fullscreen adapter is a host protocol stub, not native OS QA.
 * No successful model, export or recipe response is fabricated. */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-minimize-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-minimize-library-'));
const source = path.join(library, 'extracted/3d_model/neutral.unity');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(path.dirname(source), { recursive: true });
const original = fs.readFileSync(path.join(product, 'tests/fixtures/viewer_persistence.unity'));
fs.writeFileSync(source, original);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sourceFiles = ['webtools/web/index.html', 'webtools/web/static/model-viewer.js', 'webtools/web/static/style.css',
  'webtools/web/static/viewer-rig.js', 'webtools/web/static/viewer-persistence.js', 'webtools/i18n.py'];
const sourceHashes = () => Object.fromEntries(sourceFiles.map(name => [name, sha(fs.readFileSync(path.join(product, name)))]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());
async function startServer() {
  const reservation = net.createServer(); await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error('Product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('Product server was not ready');
}
async function show(page, selector) {
  const target = page.locator(selector);
  await target.evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await target.scrollIntoViewIfNeeded(); await frames(page); return target;
}
async function hit(page, selector, minimum) {
  const target = page.locator(selector); assert(await target.isVisible(), selector + ' is visible before interaction');
  await target.scrollIntoViewIfNeeded(); await frames(page);
  const result = await target.evaluate(element => {
    const r = element.getBoundingClientRect(), h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { width: r.width, height: r.height, x: r.x, top: r.top, right: r.right, bottom: r.bottom,
      hit: h === element || element.contains(h), label: element.getAttribute('aria-label') || element.textContent.trim() };
  });
  assert(result.hit && result.width >= minimum && result.height >= minimum && result.label, selector + ' is an accessible hittable target: ' + JSON.stringify(result));
  return result;
}
async function snapshot(page) {
  return page.evaluate(() => {
    const s = ModelViewer.getState(), canvas = document.getElementById('viewer-canvas');
    const rect = selector => { const element = document.querySelector(selector), r = element.getBoundingClientRect();
      return { x: r.x, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, visible: !!element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden' }; };
    return { modelId: s.modelId, editingToken: (ModelViewer.getEditingMetadata() || {}).token, paths: s.paths, loadedPaths: s.loadedPaths,
      camera: s.camera, cameraAspect: window.__minimizeCamera && window.__minimizeCamera.aspect,
      authoring: ModelViewer.getAuthoringState(), layout: s.layout, frames: s.renderedFrames,
      motion: { clip: s.rig.selectedClip, time: s.rig.time, playing: s.rig.playing }, selected: s.rig.selectedNode,
      persistence: s.persistence, quality: s.quality, canvas: { width: canvas.width, height: canvas.height },
      stage: rect('#viewer-stage'), editor: rect('.viewer-control-panel'), restore: rect('#viewer-model-restore'), inspect: rect('.viewer-inspect-layout'), header: rect('header'),
      panels: Object.fromEntries(['viewer-adjustments', 'viewer-body-adjustments', 'viewer-expression-adjustments', 'viewer-node-editor', 'viewer-breast-card', 'viewer-hips-card', 'viewer-skirt-card'].map(id => [id, document.getElementById(id).open])),
      panePreferences: { panel: localStorage.getItem('elichika.viewer.panel-width.v1'), files: localStorage.getItem('elichika.viewer.files-width.v1') },
      overflow: document.documentElement.scrollWidth > innerWidth + 1, focus: document.activeElement && document.activeElement.id };
  });
}
function retained(before, after, label, body = true) {
  for (const key of ['modelId', 'editingToken', 'paths', 'loadedPaths', 'camera', 'selected', 'panePreferences']) assert.deepStrictEqual(after[key], before[key], label + ': ' + key + ' retained');
  if (body) assert.deepStrictEqual(after.authoring, before.authoring, label + ': pending body edits retained');
  assert(Number.isFinite(after.cameraAspect) && after.cameraAspect > 0, label + ': actual camera aspect stays finite and positive');
  assert(after.canvas.width > 0 && after.canvas.height > 0 && after.quality.cssWidth > 0 && after.quality.cssHeight > 0, label + ': last positive canvas/quality geometry retained');
}
async function folded(page, direction) {
  await page.waitForFunction(direction => {
    const layout = ModelViewer.getState().layout;
    return layout.minimized === true && layout.minimizeDirection === direction && !layout.expanded && layout.fullscreen === 'none' && !layout.fullscreenPending;
  }, direction);
  await frames(page); const s = await snapshot(page);
  assert(!s.stage.visible, 'The model stage is actually hidden');
  assert(s.restore.visible && s.editor.visible && !s.overflow, 'Restore control and editor are visible without horizontal overflow');
  assert.equal(await page.locator('#viewer-minimize').getAttribute('aria-pressed'), 'true');
  if (direction === 'height') {
    assert(s.restore.height >= 44 && s.restore.height <= 56, 'Portrait minimization uses a compact restore bar');
    assert(s.restore.width >= s.inspect.width - 8, 'Portrait restore bar spans the model/editor workspace');
    assert(s.editor.width >= s.inspect.width - 8 && s.editor.top >= s.restore.bottom - 1, 'Portrait editor gets the width below the compact bar');
  } else {
    assert(s.restore.width >= 44 && s.restore.width <= 56, 'Landscape minimization uses a compact restore rail');
    assert(s.editor.width >= s.inspect.width - 68 && s.editor.x >= s.restore.right - 1, 'Landscape editor gets the released model width');
  }
  return s;
}
async function minimize(page, direction) {
  await hit(page, '#viewer-minimize', 32); await page.locator('#viewer-minimize').click();
  const s = await folded(page, direction); assert.equal(s.focus, 'viewer-model-restore', 'Focus moves out of the hidden stage to the restore control');
  return s;
}
async function restore(page, keyboard = false) {
  await hit(page, '#viewer-model-restore', 44);
  if (keyboard) { await page.locator('#viewer-model-restore').focus(); await page.keyboard.press('Enter'); }
  else await page.locator('#viewer-model-restore').click();
  await page.waitForFunction(() => ModelViewer.getState().layout.minimized === false);
  await page.waitForFunction(() => { const s = ModelViewer.getState(); return s.quality && s.quality.ready && s.quality.cssWidth > 0 && s.quality.cssHeight > 0; });
  await frames(page); const s = await snapshot(page);
  assert(s.stage.visible && !s.restore.visible && !s.overflow, 'Restoring shows the model and removes its compact placeholder');
  assert.equal(await page.locator('#viewer-minimize').getAttribute('aria-pressed'), 'false');
  return s;
}
async function setBreast(page, value) {
  await (await show(page, '#viewer-editor-node-tab')).click(); await (await show(page, '#viewer-node-filter')).selectOption('all');
  const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'BreastSize'));
  await page.locator('#viewer-node').selectOption(String(node.node)); await page.locator('#viewer-save-method').selectOption('node');
  const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]');
  await field.fill(String(value)); await field.dispatchEvent('change'); return { field, node };
}
async function main() {
  let server, browser, currentPage;
  const report = { status: 'RUNNING', scope: 'Actual shared UI/HTTP/Unity/export/Chromium WebGL. Real browser fullscreen plus explicitly simulated Mac/native fullscreen protocol, not a physical-device claim.',
    sourceBefore: sourceHashes(), cases: [] };
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const profiles = [
      { name: 'phone-portrait', width: 448, height: 998, locale: 'ko', touch: true, direction: 'height', browserFullscreen: true },
      { name: 'phone-landscape', width: 998, height: 448, locale: 'en', touch: true, direction: 'width' },
      { name: 'phone-short-landscape', width: 998, height: 300, locale: 'en', touch: true, direction: 'width', short: true },
      { name: 'wide-mac', width: 1360, height: 900, locale: 'ja', mac: true, direction: 'width', nativeFullscreen: true, contextRestore: true },
      { name: 'narrow-tall-mac', width: 600, height: 1200, locale: 'en', mac: true, direction: 'height' }
    ].filter(profile => !process.env.PROFILE_ONLY || profile.name === process.env.PROFILE_ONLY);
    for (const profile of profiles) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch });
      await context.addInitScript(p => {
        localStorage.setItem('sifas_lang', p.locale);
        if (p.mac) { window.ElichikaDesktop = { platform: 'macos', version: 1, language: p.locale, capabilities: [] };
          window.webkit = { messageHandlers: { elichika: { postMessage() {} } } }; }
        if (p.nativeFullscreen) {
          window.__minimizeNative = { active: false, timeline: [] };
          window.ElichikaViewerFullscreen = { postMessage(command) {
            const native = window.__minimizeNative; native.timeline.push({ type: 'command', command, minimized: ModelViewer.getState().layout.minimized });
            setTimeout(() => { native.active = command === 'enter'; native.timeline.push({ type: 'ack', active: native.active, minimized: ModelViewer.getState().layout.minimized });
              dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: native.active, settled: true } })); }, command === 'exit' ? 150 : 0);
          } };
        }
      }, profile);
      const page = await context.newPage(); currentPage = page; page.setDefaultTimeout(30000);
      const errors = [], requests = [];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => { const endpoint = new URL(request.url()).pathname;
        if (endpoint === '/api/viewer/prepare' || endpoint === '/api/viewer/edit/export') requests.push({ endpoint, body: request.postDataJSON() }); });
      await page.route('**/static/viewer-quality.js', async route => {
        const response = await route.fetch(), body = await response.text();
        await route.fulfill({ response, body: body + '\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__minimizeCamera=camera;return render.apply(this,arguments);};return c;};})();' });
      });
      await page.goto(server.url); await page.waitForFunction(locale => document.documentElement.lang === locale && typeof openModelViewer === 'function', profile.locale);
      await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !!window.__minimizeCamera);
      const initial = await snapshot(page); assert.equal(initial.layout.minimized, false); assert(initial.stage.visible && !initial.restore.visible);
      assert.equal(initial.panels['viewer-adjustments'], false, 'Pose / motion starts collapsed');
      assert.equal(initial.panels['viewer-expression-adjustments'], false, 'Expression starts collapsed');
      if (profile.short) assert.equal(initial.layout.shortHeight, true, 'This case actually enters the short workspace drawer');
      const initialProbe = await page.evaluate(() => ModelViewer.renderProbe(13)); assert(initialProbe.ready && initialProbe.glError === 0 && initialProbe.nonBackgroundSamples > 0);
      // Use real view/FOV controls so restoration must preserve a non-default camera.
      const fov = await show(page, '#viewer-fov'); await fov.focus(); await page.keyboard.press('Home');
      const fovMinimum = Number(await fov.getAttribute('min'));
      for (let value = fovMinimum; value < 29; value++) await page.keyboard.press('ArrowRight');
      assert.equal(await fov.inputValue(), '29', 'The actual range control changes perspective');
      await setBreast(page, 1.17);
      const minimum = profile.mac ? 34 : 44;
      await hit(page, 'input[data-viewer-node-kind="scale"][data-axis="X"]', minimum);
      if (profile.name === 'wide-mac') {
        for (const selector of ['#viewer-panel-resizer', '#viewer-files-resizer']) if (await page.locator(selector).isVisible()) {
          await page.locator(selector).focus(); await page.keyboard.press('ArrowLeft'); await frames(page);
        }
      }
      const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
      await (await show(page, '#viewer-motion')).selectOption(clip); await page.locator('#viewer-time').press('Home');
      await page.locator('#viewer-play').click(); await page.waitForFunction(() => ModelViewer.getState().rig.playing && ModelViewer.getState().rig.time > .05);
      await page.locator('#viewer-adjustments > summary').click();
      await page.locator('#viewer-expression-adjustments > summary').click();
      assert.equal(await page.locator('#viewer-expression-adjustments').evaluate(element => element.open), true, 'Expression can be opened through its summary');
      await page.locator('#viewer-expression-adjustments > summary').click();
      const before = await snapshot(page); assert(before.motion.playing && !before.panels['viewer-adjustments'] && !before.panels['viewer-expression-adjustments']);
      const first = await minimize(page, profile.direction); retained(before, first, 'Minimize');
      assert.deepStrictEqual(first.panels, before.panels, 'Minimize preserves manual panel folds');
      await wait(650); const paused = await snapshot(page);
      assert.equal(paused.frames, first.frames, 'No natural WebGL frames render while minimized');
      assert.equal(paused.motion.time, first.motion.time, 'Motion time freezes while minimized'); assert.equal(paused.motion.playing, true, 'Playback intent remains enabled');
      assert.deepStrictEqual(paused.canvas, first.canvas); assert.equal(paused.cameraAspect, first.cameraAspect);
      const refusedProbe = await page.evaluate(() => ModelViewer.renderProbe(13)); assert.equal(refusedProbe.ready, false, 'Diagnostics cannot force a hidden model render');
      assert.equal((await state(page)).renderedFrames, first.frames);
      const edited = await setBreast(page, 1.25); const editorHit = await hit(page, 'input[data-viewer-node-kind="scale"][data-axis="X"]', minimum);
      if (profile.direction === 'height') {
        await edited.field.evaluate(element => { element.focus(); element.scrollIntoView({ block: 'start' }); }); await frames(page);
        editorHit.focusScroll = await edited.field.evaluate(element => {
          const r = element.getBoundingClientRect(), bar = document.getElementById('viewer-model-restore').getBoundingClientRect(), h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { top: r.top, bottom: r.bottom, restoreBottom: bar.bottom, scrollMarginTop: getComputedStyle(element).scrollMarginTop, hit: h === element || element.contains(h) };
        });
        assert(editorHit.focusScroll.hit && editorHit.focusScroll.top >= editorHit.focusScroll.restoreBottom - 1,
          'Focusing/scrolling an edit stays below the sticky minimized restore bar: ' + JSON.stringify(editorHit.focusScroll));
      }
      const pending = await snapshot(page); retained(first, pending, 'Editing the minimized model', false); assert.notDeepStrictEqual(pending.authoring, first.authoring);
      await (await show(page, '#viewer-save')).click();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.status === 'done');
      const saved = await snapshot(page); retained(pending, saved, 'Saving while minimized'); assert.equal(saved.frames, first.frames);
      assert.equal(saved.motion.time, first.motion.time); assert.equal(saved.layout.minimized, true);
      const recipe = JSON.parse(fs.readFileSync(saved.persistence.recipePath));
      assert(recipe.state.edits.some(edit => edit.node === edited.node.node && edit.method === 'node' && edit.scale[0] === 1.25));
      assert(saved.persistence.outputPaths.every(file => fs.existsSync(file)));
      await page.screenshot({ path: path.join(evidence, profile.name + '-minimized.png') });
      // Reorient the available CSS window while folded. The instance and last
      // positive buffer survive even though the editor changes bar/rail layout.
      const swapped = { width: profile.height, height: profile.width }, otherDirection = profile.direction === 'height' ? 'width' : 'height';
      await page.setViewportSize(swapped); const rotated = await folded(page, otherDirection); retained(saved, rotated, 'Orientation while minimized');
      assert.deepStrictEqual(rotated.canvas, saved.canvas); assert.equal(rotated.cameraAspect, saved.cameraAspect); assert.equal(rotated.frames, saved.frames);
      await page.setViewportSize({ width: profile.width, height: profile.height }); await folded(page, profile.direction);
      if (profile.contextRestore) {
        const available = await page.evaluate(() => { const canvas = document.getElementById('viewer-canvas'), gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
          window.__minimizeLostContext = gl.getExtension('WEBGL_lose_context'); if (__minimizeLostContext) __minimizeLostContext.loseContext(); return !!__minimizeLostContext; });
        assert(available, 'Chromium provides the real WebGL context-loss test extension');
        await page.waitForFunction(() => ModelViewer.getState().contextLost); await wait(120);
        await page.evaluate(() => __minimizeLostContext.restoreContext()); await page.waitForFunction(() => !ModelViewer.getState().contextLost);
        const recovered = await snapshot(page); retained(saved, recovered, 'Hidden context restoration');
        assert.equal(recovered.layout.minimized, true); assert.equal(recovered.frames, saved.frames);
      }
      const restored = await restore(page, true); retained(saved, restored, 'Keyboard restore');
      assert.deepStrictEqual(restored.panels, saved.panels, 'Restore preserves manual panel and Node-card folds');
      assert.equal(restored.motion.playing, true); assert(restored.motion.time >= saved.motion.time && restored.motion.time - saved.motion.time < .35, 'Restore resumes playback without adding hidden wall time');
      await page.waitForFunction(count => ModelViewer.getState().renderedFrames > count, restored.frames);
      const restoredProbe = await page.evaluate(() => ModelViewer.renderProbe(13)); assert(restoredProbe.ready && restoredProbe.glError === 0 && restoredProbe.nonBackgroundSamples > 0);
      await (await show(page, '#viewer-play')).click();
      assert.equal((await state(page)).rig.playing, false);
      await hit(page, '#viewer-expand', 32); await page.locator('#viewer-expand').click(); await page.waitForFunction(() => ModelViewer.getState().layout.expanded);
      const expanded = await snapshot(page); const fromExpanded = await minimize(page, profile.direction); retained(expanded, fromExpanded, 'Minimize from expanded view');
      await restore(page);
      let fullscreen = null;
      if (profile.browserFullscreen || profile.nativeFullscreen) {
        await hit(page, '#viewer-fullscreen', 32); await page.locator('#viewer-fullscreen').click();
        await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen !== 'none');
        const full = await snapshot(page); await hit(page, '#viewer-minimize', 32); await page.locator('#viewer-minimize').click();
        if (profile.nativeFullscreen) {
          const beforeAck = await page.evaluate(() => ({ native: __minimizeNative.active, minimized: ModelViewer.getState().layout.minimized }));
          assert(beforeAck.native && !beforeAck.minimized, 'Native minimization waits for the real protocol exit acknowledgement');
        }
        fullscreen = await folded(page, profile.direction); retained(full, fullscreen, 'Minimize after fullscreen exit');
        if (profile.browserFullscreen) assert.equal(await page.evaluate(() => !!document.fullscreenElement), false);
        if (profile.nativeFullscreen) {
          const native = await page.evaluate(() => __minimizeNative); assert.equal(native.active, false);
          assert(native.timeline.some(event => event.type === 'command' && event.command === 'exit'));
          assert(native.timeline.every(event => event.type !== 'ack' || event.active || !event.minimized), 'Ordinary fold occurs only after native exit settlement');
          fullscreen.nativeTimeline = native.timeline;
        }
        await restore(page);
      }
      const final = await snapshot(page); retained(saved, final, 'Final restore'); assert.equal(requests.filter(r => r.endpoint === '/api/viewer/prepare').length, 1, 'Minimize, orientation, fullscreen and restoration never reload the model');
      assert.equal(requests.filter(r => r.endpoint === '/api/viewer/edit/export').length, 1, 'The only export is the explicit Save while minimized');
      assert.deepStrictEqual(errors, []); await page.screenshot({ path: path.join(evidence, profile.name + '-restored.png') });
      report.cases.push({ profile, initial, initialProbe, before, first, paused, editorHit, pending, saved, rotated, restored, restoredProbe, fromExpanded, fullscreen, final, requests, errors });
      await context.close(); currentPage = null;
    }
    assert.equal(sha(fs.readFileSync(source)), sha(original), 'Original Unity input is unchanged'); report.sourceSha256 = sha(original);
    report.sourceAfter = sourceHashes(); assert.deepStrictEqual(report.sourceAfter, report.sourceBefore, 'The product source stayed frozen during the browser run');
    report.status = 'PASS'; fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error.stack || error);
    if (currentPage) { try { report.failureState = await snapshot(currentPage); await currentPage.screenshot({ path: path.join(evidence, 'failure.png') }); } catch (_) {} }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); throw error;
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill('SIGTERM'); server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end(); }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
