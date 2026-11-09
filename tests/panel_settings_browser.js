/* Real local-server UI checks for persistent panel visibility and ordering.
 * No tool jobs run, and no model conversion/API response is mocked. */
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const repo = path.resolve(__dirname, '../..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'panel-settings-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-settings-library-'));
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-settings-profile-'));
fs.mkdirSync(evidence, { recursive: true });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function startServer(module, cwd) {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, module + '.log'));
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', module, '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.pipe(log); child.stderr.pipe(log);
  const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error(module + ' exited ' + child.exitCode + ': ' + fs.readFileSync(path.join(evidence, module + '.log'), 'utf8'));
    try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) { /* starting */ }
    await wait(100);
  }
  child.kill(); throw new Error(module + ' did not become ready');
}

const row = (page, id) => page.locator('.panel-settings-dialog[open] [data-panel-id=' + JSON.stringify(id) + ']');
const dialog = page => page.locator('.panel-settings-dialog[open]');
const toolIds = page => page.locator('#tool-list button[data-id]').evaluateAll(elements => elements.map(element => element.dataset.id));
const viewerIds = page => page.locator('#viewer-control-panel > details[id]').evaluateAll(elements => elements.map(element => element.id));

async function closeDialog(page) {
  await page.keyboard.press('Escape');
  await dialog(page).waitFor({ state: 'hidden' });
}

async function toggleAll(page, checked) {
  const inputs = await dialog(page).locator('input[type=checkbox]').all();
  assert(inputs.length > 0);
  for (const input of inputs) await input.setChecked(checked);
}

async function checkToolSettings(page, url, key) {
  await page.goto(url);
  await page.waitForFunction(() => document.querySelectorAll('#tool-list button[data-id]').length > 2 && document.querySelector('#tools-panel-settings'));
  const original = await toolIds(page), first = original[0], second = original[1];
  assert(original.length > 2);
  for (const id of original) assert(await page.locator('#tool-list button[data-id=' + JSON.stringify(id) + ']').isVisible(), 'Tools initially show ' + id);
  await page.locator('#tools-panel-settings').click();
  await row(page, first).locator('input[type=checkbox]').uncheck();
  assert(!await page.locator('#tool-list button[data-id=' + JSON.stringify(first) + ']').isVisible());
  await row(page, second).locator('button[data-move=up]').click();
  assert.deepStrictEqual((await toolIds(page)).slice(0, 2), [second, first], 'Move buttons reorder actual tools');
  await closeDialog(page);
  assert(await page.evaluate(key => !!localStorage.getItem(key), key), key + ' is stored');
  await page.reload();
  await page.waitForFunction(({ first, second }) => {
    const buttons = [...document.querySelectorAll('#tool-list button[data-id]')];
    return buttons.length > 2 && buttons[0].dataset.id === second && buttons[1].dataset.id === first && !buttons[1].getClientRects().length;
  }, { first, second });
  await page.locator('#tools-panel-settings').click();
  await row(page, first).locator('input[type=checkbox]').check();
  assert(await page.locator('#tool-list button[data-id=' + JSON.stringify(first) + ']').isVisible(), 'The same row restores the hidden tool');
  await closeDialog(page);
  await page.locator('#tools-panel-settings').click();
  await toggleAll(page, false);
  await closeDialog(page);
  assert(await page.locator('#tools-panel-settings').isVisible(), 'Settings remain reachable with every tool hidden');
  assert.equal(await page.locator('#tool-list button[data-id]:visible').count(), 0);
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('#tool-list button[data-id]').length > 2);
  assert.equal(await page.locator('#tool-list button[data-id]:visible').count(), 0, 'All-hidden state persists');
  await page.locator('#tools-panel-settings').click();
  await toggleAll(page, true);
  await closeDialog(page);
  // UI settings cannot submit jobs or mutate any server content.
  await page.locator('#tool-list button[data-id=' + JSON.stringify(first) + ']').click();
  await page.locator('#tool-panel h2').waitFor();
  assert(await page.locator('#tool-form').isVisible(), 'Tool click handlers survive reordering');
  return { original, reordered: await toolIds(page), restored: first };
}

async function run() {
  let web, admin, browser, context;
  const report = { status: 'RUNNING', scope: 'Real browser and local webtools/adminui servers; settings only, no tool jobs or native app execution', cases: [] };
  try {
    web = await startServer('webtools', path.join(repo, 'modtools'));
    admin = await startServer('adminui', repo);
    const browserOptions = { headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox'], viewport: { width: 448, height: 998 }, hasTouch: true };
    context = await chromium.launchPersistentContext(profile, browserOptions);
    await context.addInitScript(() => { if (!localStorage.getItem('sifas_lang')) localStorage.setItem('sifas_lang', 'ko'); });
    const page = await context.newPage(), errors = [], jobs = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.method() === 'POST' && /\/api\/run\//.test(request.url())) jobs.push(request.url()); });
    await page.goto(web.url);
    await page.waitForFunction(() => typeof ModelViewer !== 'undefined' && document.querySelector('#viewer-panel-settings'));
    await page.locator('[data-tab=viewer]').click();
    assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false, 'Pose starts collapsed');
    assert(await page.locator('#viewer-adjustments #viewer-add-motion').count(), 'Add custom motion is inside Pose');
    assert.equal(await page.locator('.viewer-file-actions #viewer-add-motion').count(), 0);
    assert(await page.locator('#viewer-panel-settings').isVisible(), 'Settings occupy the file action position');
    const original = await viewerIds(page);
    assert.equal(original[0], 'viewer-display-options', 'View settings are the first default inspector panel');
    assert.equal(original[original.indexOf('viewer-adjustments') + 1], 'viewer-expression-adjustments');
    assert.equal(await page.locator('#viewer-expression-adjustments').evaluate(element => element.open), false, 'Expression starts collapsed');
    await page.locator('#viewer-panel-settings').click();
    assert.match(await dialog(page).innerText(), /설정|칸|패널/, 'Settings carry Korean labels');
    await page.screenshot({ path: path.join(evidence, 'settings-ko-phone.png') });
    await row(page, 'viewer-adjustments').locator('input[type=checkbox]').uncheck();
    assert(!await page.locator('#viewer-adjustments').isVisible(), 'Hide Pose removes its panel');
    while (!await row(page, 'viewer-adjustments').locator('button[data-move=up]').isDisabled()) await row(page, 'viewer-adjustments').locator('button[data-move=up]').click();
    const reordered = await viewerIds(page);
    assert(reordered.indexOf('viewer-adjustments') < reordered.indexOf(original[0]), 'Pose moves before the previously first panel');
    await closeDialog(page);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#viewer-panel-settings'));
    await page.locator('[data-tab=viewer]').click();
    await page.waitForFunction(() => {
      const panel = document.querySelector('#viewer-adjustments');
      return panel && !panel.getClientRects().length && [...panel.parentElement.children].find(element => element.matches('details[id]')).id === panel.id;
    });
    await page.locator('#viewer-panel-settings').click();
    await row(page, 'viewer-adjustments').locator('input[type=checkbox]').check();
    assert(await page.locator('#viewer-adjustments').isVisible());
    assert.equal(await page.locator('#viewer-adjustments').evaluate(element => element.open), false, 'Show preserves the collapsed state');
    await closeDialog(page);
    await page.locator('#viewer-adjustments > summary').click();
    assert(await page.locator('#viewer-add-motion').isVisible(), 'Moved motion action is reachable in expanded Pose');
    await page.screenshot({ path: path.join(evidence, 'viewer-ko-phone.png'), fullPage: true });
    report.cases.push({ name: 'viewer persistence and motion action', original, reordered });
    await page.locator('#viewer-panel-settings').click();
    await toggleAll(page, false);
    await closeDialog(page);
    assert.equal(await page.locator('#viewer-control-panel > details[id]:visible').count(), 0);
    assert(await page.locator('#viewer-panel-settings').isVisible(), 'Viewer settings remain reachable when every panel is hidden');
    await page.reload();
    await page.locator('[data-tab=viewer]').click();
    assert.equal(await page.locator('#viewer-control-panel > details[id]:visible').count(), 0, 'All-hidden viewer state survives reload');
    await page.locator('#viewer-panel-settings').click();
    await toggleAll(page, true);
    await closeDialog(page);
    await page.evaluate(() => {
      const panel = document.createElement('details');
      panel.id = 'settings-dynamic-test'; panel.innerHTML = '<summary>Dynamic tool panel</summary><p>Test content</p>';
      document.getElementById('viewer-control-panel').appendChild(panel);
    });
    await page.locator('#viewer-panel-settings').click();
    await row(page, 'settings-dynamic-test').locator('input[type=checkbox]').uncheck();
    await closeDialog(page);
    await page.locator('#settings-dynamic-test').evaluate(element => { element.hidden = true; element.hidden = false; });
    assert(!await page.locator('#settings-dynamic-test').isVisible(), 'Feature availability changes cannot override a panel visibility preference');
    await page.locator('#settings-dynamic-test').evaluate(element => element.remove());
    report.cases.push({ name: 'asset tool settings', ...await checkToolSettings(page, web.url, 'elichika.panels.tools.v1') });
    report.cases.push({ name: 'server content settings', ...await checkToolSettings(page, admin.url, 'elichika.panels.content.v1') });
    await page.goto(web.url);
    await page.locator('[data-tab=viewer]').click();
    await page.locator('#viewer-panel-settings').click();
    await row(page, 'viewer-expression-adjustments').locator('input[type=checkbox]').uncheck();
    await closeDialog(page);
    // Close the entire browser, then reopen the same disk profile as the app's
    // persistent WebView would. This goes beyond a same-document reload.
    await context.close(); context = null;
    context = await chromium.launchPersistentContext(profile, browserOptions);
    const reopened = await context.newPage();
    reopened.on('pageerror', error => errors.push(String(error)));
    await reopened.goto(web.url);
    await reopened.locator('[data-tab=viewer]').click();
    assert(!await reopened.locator('#viewer-expression-adjustments').isVisible(), 'Hidden panel survives a browser process restart');
    assert.deepStrictEqual(await viewerIds(reopened), reordered, 'Viewer order survives a browser process restart');
    await reopened.locator('[data-tab=tools]').click();
    await reopened.waitForFunction(() => document.querySelectorAll('#tool-list button[data-id]').length > 2);
    assert.deepStrictEqual(await toolIds(reopened), report.cases[1].reordered, 'Asset tool order survives restart');
    await reopened.goto(admin.url);
    await reopened.waitForFunction(() => document.querySelectorAll('#tool-list button[data-id]').length > 2);
    assert.deepStrictEqual(await toolIds(reopened), report.cases[2].reordered, 'Server content order survives restart');
    report.cases.push({ name: 'browser process restart', hiddenPanel: 'viewer-expression-adjustments', diskProfile: true });
    await reopened.setViewportSize({ width: 1440, height: 1000 });
    await reopened.goto(web.url);
    await reopened.locator('[data-tab=viewer]').click();
    await reopened.locator('#viewer-panel-settings').click();
    await reopened.screenshot({ path: path.join(evidence, 'settings-ko-desktop.png') });
    await row(reopened, 'viewer-expression-adjustments').locator('input[type=checkbox]').check();
    await closeDialog(reopened);
    assert(await reopened.locator('#viewer-expression-adjustments').isVisible(), 'Desktop controls restore a hidden panel');
    await reopened.screenshot({ path: path.join(evidence, 'viewer-ko-desktop.png'), fullPage: true });
    report.cases.push({ name: 'all-hidden recovery and desktop', dynamicPanels: true, mobileWidth: 448, desktopWidth: 1440 });
    assert.deepStrictEqual(jobs, [], 'Visibility and ordering do not run content-changing jobs');
    assert.deepStrictEqual(errors, [], 'No browser exceptions');
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error.stack || error); throw error;
  } finally {
    if (context) await context.close();
    if (browser) await browser.close();
    for (const server of [web, admin]) if (server) { server.child.kill(); server.log.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ...report, evidence }, null, 2));
  }
}

if (require.main === module) run().catch(() => { process.exitCode = 1; });
