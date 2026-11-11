/* Real product DOM/WebGL with original generated geometry and expression data.
 * The native message host is a browser stub; this is not native app execution. */
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'compact-controls-'));
fs.mkdirSync(evidence, { recursive: true });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  let server, browser;
  const report = { status: 'RUNNING', scope: 'Product DOM/WebGL and actual expression controller with generated fixture; native navigation is a host stub', cases: [] };
  try {
    const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
    const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    server = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
      { cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: fs.mkdtempSync(path.join(os.tmpdir(), 'compact-controls-library-')) }, stdio: 'ignore' });
    const url = 'http://127.0.0.1:' + port;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(url + '/api/tools')).ok) break; } catch (_) {} await delay(100); }
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [{ name: 'phone-ko', width: 360, height: 800, lang: 'ko', touch: true },
      { name: 'fold-ja', width: 853, height: 1100, lang: 'ja', touch: true },
      { name: 'mac-en', width: 1360, height: 900, lang: 'en', native: true }]) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch });
      await context.addInitScript(profile => {
        localStorage.setItem('sifas_lang', profile.lang);
        if (!profile.native) return;
        window.__nativeSurface = 'viewer';
        window.ElichikaDesktop = { platform: 'macos', version: 1, language: profile.lang, editorSurface: 'viewer', panelSettings: {}, capabilities: ['editorNavigation', 'setSection', 'setPanelSettings'] };
        window.webkit = { messageHandlers: { elichika: { postMessage(message) {
          let result = {};
          if (message.action === 'setSection') { if (message.event !== 'ready') __nativeSurface = message.section; result = { section: __nativeSurface }; }
          if (message.action === 'setEditorSurface') { __nativeSurface = message.editorSurface; result = { editorSurface: __nativeSurface }; }
          queueMicrotask(() => ElichikaPlatform.receive({ id: message.id, result }));
        } } } };
      }, profile);
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      const exact = [0.3333333432674408, 0.699999988079071];
      const generated = fixture({ semanticExpressions: true, rawWeights: exact, expressionBone: true });
      generated.rig.expressionCatalog.presets[0].visibility = [{ node: 4, visible: false }];
      // Transparent observer: keep the real controller and source node objects.
      await page.route('**/static/viewer-expressions.js', async route => {
        const response = await route.fetch(); const source = await response.text();
        await route.fulfill({ response, body: source + '\n(() => {const create=ViewerExpressions.create;ViewerExpressions.create=function(options){const controller=create(options);window.__expressionController=controller;window.__expressionNodes=options.nodes;return controller;};})();' });
      });
      await page.route('**/api/viewer/prepare', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'compact-fixture', url: '/api/viewer/model/compact-fixture.glb', warnings: [], stats: { meshes: 1, triangles: 1 }, rig: generated.rig }) }));
      await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: generated.glb }));
      await page.goto(url + (profile.native ? '/?embedded=1#viewer' : '/'));
      await page.waitForFunction(() => typeof openModelViewer === 'function' && document.getElementById('viewer-game-motions'));
      await page.evaluate(() => openModelViewer(['/generated/compact-controls.unity']));
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
      const initial = await page.evaluate(() => {
        const roots = [...document.querySelectorAll('#viewer-control-panel > details[id]')].map(node => node.id);
        return { roots, pose: document.getElementById('viewer-adjustments').open, expression: document.getElementById('viewer-expression-adjustments').open,
          modelId: ModelViewer.getState().modelId, weights: ModelViewer.getState().rig.expressions.map(item => item.weight) };
      });
      assert.equal(initial.roots[0], 'viewer-display-options');
      assert.equal(initial.roots[initial.roots.indexOf('viewer-adjustments') + 1], 'viewer-expression-adjustments');
      assert(initial.roots.includes('viewer-outline-card') && initial.roots.indexOf('viewer-outline-card') < initial.roots.indexOf('viewer-body-adjustments'), 'Dynamic outline keeps its intended default position');
      assert.equal(initial.pose, false); assert.equal(initial.expression, false); assert.deepEqual(initial.weights, exact);
      await page.locator('#viewer-adjustments > summary').click();
      await page.locator('.viewer-motion-import-actions').scrollIntoViewIfNeeded();
      const buttonRects = await page.locator('.viewer-motion-import-actions > button').evaluateAll(nodes => nodes.map(node => {
        const r = node.getBoundingClientRect(), row = node.parentElement.getBoundingClientRect(), style = getComputedStyle(node), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), range = document.createRange(); range.selectNodeContents(node);
        const textRects = Array.from(range.getClientRects()).filter(t => t.width && t.height);
        return { id: node.id, x: r.x, y: r.y, right: r.right, width: r.width, height: r.height, text: node.textContent.trim(), font: style.font, hit: hit === node || node.contains(hit),
          noClip: node.scrollWidth <= node.clientWidth + 1 && node.scrollHeight <= node.clientHeight + 1 && textRects.every(t => t.left >= r.left - 1 && t.right <= r.right + 1 && t.top >= r.top - 1 && t.bottom <= r.bottom + 1),
          noOverflow: r.left >= row.left - 1 && r.right <= row.right + 1 && r.left >= 0 && r.right <= innerWidth && node.parentElement.scrollWidth <= node.parentElement.clientWidth + 1 };
      }));
      assert.equal(buttonRects.length, 2); assert(Math.abs(buttonRects[0].y - buttonRects[1].y) < 1);
      assert(buttonRects.every(rect => rect.width >= (profile.native ? 34 : 44) && rect.height >= (profile.native ? 34 : 36)), profile.name + ': usable compact targets: ' + JSON.stringify(buttonRects));
      assert(buttonRects.every(rect => rect.text && rect.hit && rect.noClip && rect.noOverflow), profile.name + ': labels remain readable, unclipped and pointer-reachable in one row: ' + JSON.stringify(buttonRects));
      await page.screenshot({ path: path.join(evidence, profile.name + '-pose-row.png') });
      const thin = await page.locator('#viewer-expression-adjustments').evaluate(node => node.getBoundingClientRect().height);
      assert(thin <= 50, 'Collapsed panel is compact, including touch targets: ' + thin);
      assert(!await page.locator('#viewer-outline-card').evaluate(node => node.open));
      await page.locator('#viewer-outline-card > summary').click();
      const outline = await page.locator('#viewer-outline-card').evaluate(node => {
        const panel = node.getBoundingClientRect(), fields = ['viewer-outline-range', 'viewer-outline-number', 'viewer-outline-value'].map(id => document.getElementById(id).getBoundingClientRect());
        return { overflow: fields.some(r => r.right > panel.right || r.x < panel.x), centers: fields.map(r => r.y + r.height / 2) };
      });
      assert(!outline.overflow && Math.max(...outline.centers) - Math.min(...outline.centers) < 1, 'Outline range and exact-entry controls share a usable row');
      await page.locator('#viewer-outline-card > summary').click();
      await page.locator('#viewer-expression-adjustments > summary').click();
      await page.locator('#viewer-expression-advanced > summary').click();
      const keys = await page.locator('#viewer-expression option').evaluateAll(nodes => nodes.map(node => node.value).filter(Boolean));
      await page.locator('#viewer-expression').selectOption(keys[0]);
      assert.equal(await page.locator('#viewer-expression-number').inputValue(), '33.33');
      assert.equal(await page.locator('#viewer-expression-output').innerText(), '33.33%');
      assert.deepEqual(await page.evaluate(() => ModelViewer.getState().rig.expressions.map(item => item.weight)), exact, 'Formatting never changes original weights');
      await page.locator('[data-viewer-expression-group="eyes"]').click();
      await page.locator('[data-viewer-expression-preset="fixture-eyes-closed"]').click();
      await page.locator('#viewer-expression').selectOption(keys[1]);
      const typed = '12.345678901234'; await page.locator('#viewer-expression-number').fill(typed);
      await page.locator('#viewer-expression').focus();
      assert.equal(await page.locator('#viewer-expression-number').inputValue(), '12.35');
      const expected = Number(typed) / 100;
      assert.equal((await page.evaluate(() => __expressionController.getState())).overrides[keys[1]], expected, 'Typed exact weight survives compact display');
      const restored = await page.evaluate(() => {
        const controller = __expressionController, snapshot = controller.getState(); controller.reset();
        const accepted = controller.restoreState(snapshot), after = controller.getState();
        const invalid = { ...snapshot, overrides: { ...snapshot.overrides, nonexistent: 1 } };
        const rejected = controller.restoreState(invalid), unchanged = controller.getState();
        return { accepted, rejected, snapshot, after, unchanged, visible: __expressionNodes['4'].visible, scale: __expressionNodes['2'].scale.toArray(), id: ModelViewer.getState().modelId };
      });
      assert(restored.accepted && !restored.rejected);
      for (const key of ['overrides', 'boneOperations', 'visibility', 'group', 'selectedRaw', 'selectedPresets', 'lastSelection']) {
        assert.deepEqual(restored.after[key], restored.snapshot[key], 'Restore retains ' + key);
        assert.deepEqual(restored.unchanged[key], restored.snapshot[key], 'Invalid restore is atomic for ' + key);
      }
      assert.equal(restored.visible, false); assert.deepEqual(restored.scale, [.8, .7, .6]); assert.equal(restored.id, initial.modelId);
      await page.screenshot({ path: path.join(evidence, profile.name + '.png') });
      await page.evaluate(() => ElichikaNavigation.showSection('tools', { notify: false }));
      const settings = page.locator('#tools-panel-settings');
      assert(await settings.isVisible(), 'Settings are visible in the actual tool workspace');
      if (profile.native) assert(!await page.locator('body > header').isVisible(), 'Native hidden header cannot hide settings');
      const top = (await settings.boundingBox()).y;
      await page.locator('#tool-list').evaluate(node => { node.scrollTop = node.scrollHeight; node.scrollLeft = node.scrollWidth; });
      assert(Math.abs((await settings.boundingBox()).y - top) < 1, 'Tool-list scrolling cannot move the settings control away');
      await settings.click();
      for (const input of await page.locator('#tools-panel-settings-dialog input[type=checkbox]').all()) await input.uncheck();
      await page.keyboard.press('Escape');
      assert(await settings.isVisible()); assert.equal(await page.locator('#tool-list > button[data-id]:visible').count(), 0);
      await page.reload(); await page.waitForFunction(() => document.querySelectorAll('#tool-list > button[data-id]').length > 2);
      await page.evaluate(() => ElichikaNavigation.showSection('tools', { notify: false }));
      assert(await settings.isVisible()); assert.equal(await page.locator('#tool-list > button[data-id]:visible').count(), 0);
      await settings.click(); await page.locator('#tools-panel-settings-dialog .panel-settings-actions button').first().click(); await page.keyboard.press('Escape');
      assert(await page.locator('#tool-list > button[data-id]').first().isVisible());
      await page.screenshot({ path: path.join(evidence, profile.name + '-tool-settings.png') });
      assert.deepEqual(errors, []); report.cases.push({ name: profile.name, singleMotionRow: buttonRects, collapsedHeight: thin, initialWeights: exact, typedWeight: expected, exactRestore: true });
      await context.close();
    }
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) server.kill(); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence })); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
