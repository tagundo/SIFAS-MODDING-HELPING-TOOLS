/* Native-host contract checks in Chromium, not a native macOS execution claim.
 * Fresh browser contexts and rotating real local-server origins have no shared
 * localStorage. Only the host-stub metadata carries preferences across them. */
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const repo = path.resolve(__dirname, '../..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'panel-settings-native-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-settings-native-library-'));
fs.mkdirSync(evidence, { recursive: true });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const copy = value => JSON.parse(JSON.stringify(value));
const nativeSettings = {
  viewer: { hidden: ['viewer-expression-adjustments'], order: ['viewer-adjustments', 'viewer-save-panel'] },
  tools: { hidden: ['breast_dyna'], order: ['breast_size', 'character_info'] },
  content: { hidden: ['backup'], order: ['restore', 'clear_packs'] },
};
const messages = [];

async function until(check, label) {
  for (let n = 0; n < 100; n++) { if (check()) return; await wait(50); }
  throw new Error('Timed out: ' + label);
}
async function server(module, serial) {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, module + '-' + serial + '.log'));
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', module, '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: module === 'webtools' ? path.join(repo, 'modtools') : repo,
    env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.pipe(log); child.stderr.pipe(log); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error(module + ' failed: ' + fs.readFileSync(path.join(evidence, module + '-' + serial + '.log'), 'utf8'));
    try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) { /* starting */ }
    await wait(100);
  }
  child.kill(); throw new Error(module + ' not ready');
}
async function nativeContext(browser) {
  const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } });
  await context.exposeBinding('__panelHostRequest', async (_source, message) => {
    messages.push(copy(message));
    if (message.action !== 'setPanelSettings') throw new Error('Unexpected native action ' + message.action);
    assert(['viewer', 'tools', 'content'].includes(message.panelScope));
    assert(message.panelSettings && Array.isArray(message.panelSettings.hidden) && Array.isArray(message.panelSettings.order));
    nativeSettings[message.panelScope] = copy(message.panelSettings);
    return { ok: true };
  });
  await context.addInitScript(settings => {
    window.__panelStorageAtStartup = ['viewer', 'tools', 'content'].map(scope => localStorage.getItem('elichika.panels.' + scope + '.v1'));
    window.__panelNativeAcks = [];
    window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'ko', capabilities: ['setPanelSettings'], panelSettings: settings };
    window.webkit = { messageHandlers: { elichika: { postMessage(message) {
      window.__panelHostRequest(message).then(result => {
        window.__panelNativeAcks.push(message);
        if (window.ElichikaPlatform) ElichikaPlatform.receive({ id: message.id, result });
      }, error => {
        if (window.ElichikaPlatform) ElichikaPlatform.receive({ id: message.id, error: String(error) });
      });
    } } } };
  }, copy(nativeSettings));
  return context;
}
const row = (page, id) => page.locator('.panel-settings-dialog[open] [data-panel-id=' + JSON.stringify(id) + ']');
const tools = page => page.locator('#tool-list > button[data-id]').evaluateAll(nodes => nodes.map(node => node.dataset.id));
const roots = page => page.locator('#viewer-control-panel > details[id]').evaluateAll(nodes => nodes.map(node => node.id));
async function close(page) { await page.keyboard.press('Escape'); await page.locator('.panel-settings-dialog[open]').waitFor({ state: 'hidden' }); }
async function ready(page, url) {
  await page.goto(url); await page.waitForFunction(() => document.querySelector('#tool-list .panel-settings-button') && document.querySelectorAll('#tool-list > button[data-id]').length > 2);
  assert.deepStrictEqual(await page.evaluate(() => window.__panelStorageAtStartup), [null, null, null], 'Fresh origin starts without localStorage preferences');
}
async function verifyWeb(page, expected) {
  assert.equal(await page.evaluate(() => ElichikaPlatform.supports('setPanelSettings')), true);
  await page.locator('[data-tab=viewer]').click();
  for (const id of expected.viewer.hidden) assert(!await page.locator('#' + id).isVisible(), 'Native viewer preference hides ' + id);
  assert.deepStrictEqual((await roots(page)).slice(0, 2), expected.viewer.order.slice(0, 2));
  await page.locator('[data-tab=tools]').click();
  for (const id of expected.tools.hidden) assert(!await page.locator('#tool-list button[data-id=' + JSON.stringify(id) + ']').isVisible(), 'Native asset preference hides ' + id);
  assert.deepStrictEqual((await tools(page)).slice(0, 2), expected.tools.order.slice(0, 2));
}
async function verifyContent(page, expected) {
  assert.equal(await page.evaluate(() => typeof window.ElichikaPlatform), 'undefined', 'Standalone content screen tests the direct native bridge');
  for (const id of expected.hidden) assert(!await page.locator('#tool-list button[data-id=' + JSON.stringify(id) + ']').isVisible(), 'Native content preference hides ' + id);
  assert.deepStrictEqual((await tools(page)).slice(0, 2), expected.order.slice(0, 2));
}

async function run() {
  let browser, context; const servers = [];
  const report = { status: 'RUNNING', scope: 'Real webtools/adminui HTTP with Chromium native-host bridge stub, fresh contexts and changed ports; no native macOS execution claim' };
  try {
    const webA = await server('webtools', 'a'); servers.push(webA);
    const contentA = await server('adminui', 'a'); servers.push(contentA);
    const webB = await server('webtools', 'b'); servers.push(webB);
    const contentB = await server('adminui', 'b'); servers.push(contentB);
    assert.notEqual(webA.url, webB.url); assert.notEqual(contentA.url, contentB.url);
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox'] });
    context = await nativeContext(browser);
    let page = await context.newPage(); const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const initial = copy(nativeSettings);
    await ready(page, webA.url); await verifyWeb(page, initial);
    await page.locator('[data-tab=viewer]').click();
    await page.locator('#viewer-panel-settings').click();
    await row(page, 'viewer-body-adjustments').locator('input[type=checkbox]').uncheck();
    await row(page, 'viewer-adjustments').locator('[data-move=down]').click(); await close(page);
    await until(() => nativeSettings.viewer.hidden.includes('viewer-body-adjustments') && nativeSettings.viewer.order[0] === 'viewer-save-panel', 'viewer native save ack');
    await page.locator('[data-tab=tools]').click(); await page.locator('#tool-list .panel-settings-button').click();
    await row(page, 'character_info').locator('input[type=checkbox]').uncheck();
    await row(page, 'breast_size').locator('[data-move=down]').click(); await close(page);
    await until(() => nativeSettings.tools.hidden.includes('character_info') && nativeSettings.tools.order[0] === 'character_info', 'tools native save ack');
    const callsBefore = messages.length;
    const rejections = await page.evaluate(async () => Promise.all([
      { panelScope: 'arbitrary', panelSettings: { hidden: [], order: [] } },
      { panelScope: 'viewer', panelSettings: { hidden: 'invalid', order: [] } },
      { panelScope: 'viewer', panelSettings: { hidden: [], order: null } },
    ].map(args => ElichikaPlatform.request('setPanelSettings', args).then(() => 'unexpected success', error => error.message))));
    assert(rejections.every(value => value !== 'unexpected success'));
    assert.equal(messages.length, callsBefore, 'Adapter rejects invalid values without calling native host');
    await ready(page, contentA.url); await verifyContent(page, initial.content);
    await page.locator('#tool-list .panel-settings-button').click();
    await row(page, 'clear_packs').locator('input[type=checkbox]').uncheck();
    await row(page, 'restore').locator('[data-move=down]').click(); await close(page);
    await until(() => nativeSettings.content.hidden.includes('clear_packs') && nativeSettings.content.order[0] === 'clear_packs', 'direct content native save');
    const persisted = copy(nativeSettings);
    assert(messages.some(message => message.panelScope === 'viewer') && messages.some(message => message.panelScope === 'tools') && messages.some(message => message.panelScope === 'content'));
    await context.close(); context = null;
    context = await nativeContext(browser); page = await context.newPage(); page.on('pageerror', error => errors.push(String(error)));
    await ready(page, webB.url); await verifyWeb(page, persisted);
    await page.locator('[data-tab=viewer]').click(); await page.locator('#viewer-panel-settings').click();
    await page.screenshot({ path: path.join(evidence, 'native-restored-viewer.png') }); await close(page);
    await ready(page, contentB.url); await verifyContent(page, persisted.content);
    assert.deepStrictEqual(errors, []);
    Object.assign(report, { status: 'PASS', initial, persisted, nativeWrites: messages.length, invalidRequestsRejected: rejections, changedOrigins: [webA.url, webB.url, contentA.url, contentB.url], freshLocalStorage: true });
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally {
    if (context) await context.close(); if (browser) await browser.close();
    for (const item of servers) { item.child.kill(); item.log.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ ...report, evidence }, null, 2));
  }
}
if (require.main === module) run().catch(() => { process.exitCode = 1; });
