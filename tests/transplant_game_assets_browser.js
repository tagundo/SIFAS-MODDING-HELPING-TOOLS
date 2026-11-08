/* Real catalogs, encrypted source packs and SSE for the two transplant fields.
 * Only race delivery is controlled; native adapters are browser stubs, not OS QA. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');

const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'transplant-game-assets-'));
fs.mkdirSync(evidence, { recursive: true });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sources = ['webtools/core/game_models.py', 'webtools/server.py', 'webtools/tools/registry.py',
  'webtools/web/static/app.js', 'webtools/web/static/viewer-game-assets.js'];
const sourceHashes = () => Object.fromEntries(sources.map(name => [name, sha(fs.readFileSync(path.join(product, name)))]));
const report = { status: 'RUNNING', scope: 'Chromium with simulated native adapters; real isolated product catalog, pack decryption, native bundle cache and SSE. No game playback or physical-device claim.', sourceBefore: sourceHashes(), cases: [] };
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const field = (page, name) => page.locator('#tool-panel input[data-name="' + name + '"]');
const button = (page, name) => page.locator('[data-game-asset-field="' + name + '"]');
const modal = page => page.locator('#viewer-game-assets-dialog');
const modelState = page => page.evaluate(() => { const s = ModelViewer.getState(); return { id: s.modelId, paths: s.loadedPaths, camera: s.camera }; });
let child, browser;

function snapshot(root) {
  const result = {};
  function walk(directory) {
    for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, item.name);
      if (item.isDirectory()) walk(file);
      else if (item.isFile()) result[path.relative(root, file)] = sha(fs.readFileSync(file));
    }
  }
  for (const name of ['assets', 'packs']) walk(path.join(root, name));
  return result;
}

async function startServer() {
  child = spawn(python, [path.join(__dirname, 'transplant_game_models_browser_server.py')], {
    cwd: product,
    env: { ...process.env, PYTHONPATH: [path.dirname(product), product, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const log = fs.createWriteStream(path.join(evidence, 'server.log')); child.stderr.pipe(log);
  return new Promise((resolve, reject) => {
    let text = '';
    const timeout = setTimeout(() => reject(new Error('Isolated native fixture server did not start')), 20000);
    child.stdout.on('data', chunk => {
      text += chunk;
      if (!text.includes('\n')) return;
      clearTimeout(timeout);
      try { resolve(JSON.parse(text.split('\n')[0])); } catch (error) { reject(error); }
    });
    child.once('exit', code => { clearTimeout(timeout); reject(new Error('Fixture server exited: ' + code)); });
  });
}

async function catalogReady(page) {
  await page.waitForFunction(() => document.querySelector('#viewer-game-assets-dialog').open && document.querySelector('#viewer-game-character').options.length > 1);
}

async function choose(page, { region = 'gl', character = '101', suit = 'suit:1', variant = 'primary', platform = 'android' } = {}) {
  await catalogReady(page);
  const change = page.waitForResponse(response => response.url().includes('/api/viewer/game/catalog?') && new URL(response.url()).searchParams.get('region') === region);
  await page.locator('#viewer-game-region').selectOption(region); await change;
  await page.waitForFunction(region => document.querySelector('#viewer-game-region').value === region && document.querySelector('#viewer-game-character').options.length > 1, region);
  await page.locator('#viewer-game-character').selectOption(character);
  await page.waitForFunction(suit => Array.from(document.querySelector('#viewer-game-costume').options).some(option => option.value === suit), suit);
  await page.locator('#viewer-game-costume').selectOption(suit);
  if (await page.locator('#viewer-game-variant').isVisible()) await page.locator('#viewer-game-variant').selectOption(variant);
  else assert.equal(await page.locator('#viewer-game-variant').inputValue(), variant, 'A single primary variant stays selected without a hidden-control action');
  if (await page.locator('#viewer-game-platform').count()) await page.locator('#viewer-game-platform').selectOption(platform);
  await page.locator('#viewer-game-download').uncheck();
}

async function seedViewer(page) {
  await page.evaluate(() => ElichikaNavigation.showSection('viewer', { notify: false }));
  await page.locator('#viewer-file-options').evaluate(node => { node.open = true; });
  await page.locator('#viewer-auto-face').uncheck();
  await page.locator('#viewer-file-options').evaluate(node => { node.open = false; });
  await page.locator('#viewer-game-assets').click(); await choose(page);
  assert.equal(await page.locator('#viewer-game-platform').count(), 0, 'Existing viewer selection keeps its original four-field protocol');
  await page.locator('#viewer-game-import').click();
  await page.waitForFunction(() => !document.querySelector('#viewer-game-assets-dialog').open && ModelViewer.getState().loaded && !ModelViewer.getState().loading);
  await page.locator('[data-viewer-view="left"]').click(); await frames(page);
  await page.evaluate(() => ElichikaNavigation.showSection('tools', { notify: false }));
  await page.locator('#tool-list button[data-id="costume_transplant"]').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-game-asset-field]').length === 2);
}

async function pickField(page, name, selection) {
  const before = await field(page, name).inputValue();
  await button(page, name).click(); await choose(page, selection);
  const dialog = await modal(page).evaluate(node => { const r = node.getBoundingClientRect(); return { width: r.width, height: r.height, contained: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight }; });
  assert(dialog.contained, 'The shared picker stays inside the native/browser viewport');
  await page.locator('#viewer-game-import').click();
  await page.waitForFunction(({ name, before }) => !document.querySelector('#viewer-game-assets-dialog').open && document.querySelector('#tool-panel input[data-name="' + name + '"]').value !== before, { name, before });
  const value = await field(page, name).inputValue();
  assert(path.isAbsolute(value) && value.endsWith('.unity') && !value.endsWith('.zip'));
  return { value, dialog };
}

async function inputRowLayout(page, minHeight = 44) {
  const rows = [];
  for (const name of ['donor', 'target']) {
    await button(page, name).scrollIntoViewIfNeeded();
    const metrics = await button(page, name).evaluate(node => {
      const box = node.getBoundingClientRect(), row = node.parentElement;
      const input = row.querySelector('input').getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return { width: box.width, height: box.height, contained: box.left >= 0 && box.right <= innerWidth + 1,
        inputContained: input.left >= 0 && input.right <= innerWidth + 1,
        rowOverflow: row.scrollWidth - row.clientWidth, hittable: !!hit && (hit === node || node.contains(hit)) };
    });
    assert(metrics.width >= 44 && metrics.height >= minHeight && metrics.contained && metrics.inputContained && metrics.hittable, JSON.stringify({ name, minHeight, ...metrics }));
    assert(metrics.rowOverflow <= 1);
    rows.push({ name, ...metrics });
  }
  return rows;
}

async function actualTransplant(page, ready, profile, donor, target) {
  const originalBodies = [donor, target].map(file => sha(fs.readFileSync(file)));
  const outDir = path.join(ready.library, 'modded', profile.name); fs.mkdirSync(outDir, { recursive: true });
  await field(page, 'out_dir').fill(outDir);
  const submitted = page.waitForResponse(response => response.url().includes('/api/run/costume_transplant'));
  await page.locator('#tool-form .run-btn').click();
  const reply = await (await submitted).json(); assert(reply.job_id && !reply.error);
  await page.waitForFunction(() => state.es === null && document.querySelector('#cancel-btn').disabled);
  const log = await page.locator('#log').textContent(); assert(log.includes('(validate: ok)'), log);
  const output = path.join(outDir, path.basename(target, '.unity') + '_transplant.unity'); assert(fs.existsSync(output));
  const result = JSON.parse(execFileSync(python, ['-c', 'import json,sys,UnityPy,costume_transplant; p=sys.argv[1]; print(json.dumps({"validated":costume_transplant.validate(p,verbose=False),"platforms":[int(a.target_platform) for a in UnityPy.load(p).assets]}))', output], { cwd: product, encoding: 'utf8' }));
  assert(result.validated); assert(result.platforms.every(value => value === (profile.platform === 'ios' ? 9 : 13)));
  assert.deepEqual([donor, target].map(file => sha(fs.readFileSync(file))), originalBodies);
  await page.locator('#console-close').click();
  return { output, ...result, sourceBodiesUnchanged: true };
}

async function delayedPostInvalidation(page, invalidate) {
  const arrived = deferred(), release = deferred();
  await page.route('**/api/viewer/game/import?**', async route => { arrived.resolve(); await release.promise; await route.continue(); });
  await button(page, 'donor').click(); await choose(page);
  const cancelled = page.waitForRequest(request => /\/api\/jobs\/[a-f0-9]+\/cancel$/.test(request.url()));
  await page.locator('#viewer-game-import').click(); await arrived.promise;
  await invalidate();
  await page.waitForFunction(() => !document.querySelector('#viewer-game-assets-dialog').open);
  release.resolve(); await cancelled;
  await page.unroute('**/api/viewer/game/import?**');
}

(async () => {
  try {
    const ready = await startServer(), originalInputs = snapshot(ready.root);
    assert(ready.source_objects_unchanged);
    report.fixture = { sourceObjectsUnchanged: true, androidSHA: ready.android_sha256, iosSHA: ready.ios_sha256 };
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const profile of [
      { name: 'android-phone-ko', mode: 'android', width: 448, height: 998, touch: true, lang: 'ko', platform: 'android' },
      { name: 'macos-wide-en', mode: 'macos', width: 1600, height: 1000, touch: false, lang: 'en', platform: 'ios' },
      { name: 'standalone-en', mode: 'browser', width: 1280, height: 860, touch: false, lang: 'en', platform: 'android' },
    ]) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: profile.touch });
      const page = await context.newPage(), errors = [], posts = [];
      let prepares = 0;
      page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => {
        if (request.url().includes('/api/viewer/prepare')) prepares++;
        if (request.url().includes('/api/viewer/game/import?')) posts.push(request.postDataJSON());
      });
      await page.addInitScript(profile => {
        localStorage.setItem('sifas_lang', profile.lang);
        window.__sectionMessages = []; window.__fieldEvents = [];
        if (profile.mode === 'android') window.ElichikaNavigationNative = { postMessage: value => __sectionMessages.push(JSON.parse(value)) };
        if (profile.mode === 'macos') {
          window.ElichikaDesktop = { platform: 'macos', version: 1, language: profile.lang, capabilities: ['setSection', 'openFiles'] };
          window.webkit = { messageHandlers: { elichika: { postMessage(message) {
            __sectionMessages.push(message);
            setTimeout(() => ElichikaPlatform.receive({ id: message.id, result: message.action === 'openFiles' ? { cancelled: true } : {} }), 0);
          } } } };
        }
        const NativeEvents = window.EventSource;
        window.__sources = [];
        window.EventSource = class extends NativeEvents { constructor(...args) { super(...args); __sources.push(this); } };
      }, profile);
      await page.goto(ready.url + (profile.mode === 'browser' ? '/' : '/?embedded=1&lang=' + profile.lang));
      await page.waitForFunction(() => window.GameAssetPicker && document.querySelector('#tool-list button[data-id="costume_transplant"]'));
      await seedViewer(page);
      const originalModel = await modelState(page), prepareCount = prepares;
      assert.equal(posts.length, 1); assert.deepEqual(Object.keys(posts[0]).sort(), ['download', 'region', 'suit', 'variant']);
      assert.equal(await button(page, 'donor').count(), 1); assert.equal(await button(page, 'target').count(), 1);
      const inputRows = await inputRowLayout(page, profile.mode === 'macos' ? 34 : 44);
      for (const name of ['donor', 'target']) {
        await field(page, name).evaluate(node => ['input', 'change'].forEach(type => node.addEventListener(type, () => __fieldEvents.push({ name: node.dataset.name, type }))));
      }
      const donor = await pickField(page, 'donor', { platform: profile.platform });
      assert.equal(await field(page, 'target').inputValue(), '');
      await button(page, 'target').click(); await catalogReady(page);
      assert.equal(await page.locator('#viewer-game-platform').inputValue(), profile.platform, 'The second field defaults to the successful first platform');
      await page.keyboard.press('Escape');
      const target = await pickField(page, 'target', { region: 'jp', character: '209', suit: 'suit:2', variant: 'unmasked', platform: profile.platform });
      assert.equal(path.basename(target.value), 'unmasked.unity'); assert.equal(await field(page, 'donor').inputValue(), donor.value);
      const targetPrimary = await pickField(page, 'target', { region: 'jp', character: '209', suit: 'suit:2', variant: 'primary', platform: profile.platform });
      assert.equal(path.basename(targetPrimary.value), 'masked.unity');
      const actualPlatform = JSON.parse(execFileSync(python, ['-c', 'import json,sys,UnityPy;print(json.dumps([[int(a.target_platform) for a in UnityPy.load(p).assets] for p in sys.argv[1:]]))', donor.value, target.value, targetPrimary.value], { encoding: 'utf8' }));
      assert(actualPlatform.every(values => values.length > 0 && values.every(value => value === (profile.platform === 'ios' ? 9 : 13))));
      assert.equal(sha(fs.readFileSync(donor.value)), profile.platform === 'ios' ? ready.ios_sha256 : ready.android_sha256);
      assert.deepEqual((await page.evaluate(() => __fieldEvents)).slice(0, 2), [{ name: 'donor', type: 'input' }, { name: 'donor', type: 'change' }]);
      assert(posts.slice(1).every(item => item.purpose === 'transplant' && item.platform === profile.platform));
      assert.equal(await page.evaluate(() => ElichikaNavigation.currentSection()), 'tools');
      assert.deepEqual(await modelState(page), originalModel); assert.equal(prepares, prepareCount);
      const transplant = await actualTransplant(page, ready, profile, donor.value, targetPrimary.value);
      assert.deepEqual(await modelState(page), originalModel); assert.equal(prepares, prepareCount);

      if (profile.mode === 'macos') {
        const override = await pickField(page, 'target', { region: 'jp', character: '209', suit: 'suit:2', platform: 'android' });
        const platforms = JSON.parse(execFileSync(python, ['-c', 'import json,sys,UnityPy; print(json.dumps([int(a.target_platform) for a in UnityPy.load(sys.argv[1]).assets]))', override.value], { encoding: 'utf8' }));
        assert(platforms.every(value => value === 13)); assert.equal(await field(page, 'donor').inputValue(), donor.value);
        await button(page, 'donor').click(); await catalogReady(page);
        assert.equal(await page.locator('#viewer-game-platform').inputValue(), 'android', 'A successful target override becomes the next donor default');
        await page.keyboard.press('Escape');
        assert.deepEqual(await modelState(page), originalModel); assert.equal(prepares, prepareCount);
        report.cases.push({ name: 'iOS donor → iOS target default → explicit Android target → Android donor default', nativeTargets: platforms, fieldsIndependent: true, status: 'PASS' });
      }

      // The original manual picker still works beside the new game picker.
      await field(page, 'donor').fill(path.join(path.dirname(donor.value), 'manual-placeholder.unity'));
      const manual = field(page, 'donor').locator('..').locator('button:not([data-game-asset-field])');
      await manual.click();
      if (profile.mode === 'macos') {
        await page.waitForFunction(() => __sectionMessages.some(message => message.action === 'openFiles'));
        assert.equal(await field(page, 'donor').inputValue(), path.join(path.dirname(donor.value), 'manual-placeholder.unity'));
      } else {
        await page.waitForFunction(() => state.picker !== null && document.querySelector('#picker-entries li.bundle'));
        await page.locator('#picker-entries li.bundle').filter({ hasText: path.basename(donor.value) }).click();
        assert.equal(await field(page, 'donor').inputValue(), donor.value);
      }
      await field(page, 'donor').fill(donor.value);
      await button(page, 'donor').click(); await catalogReady(page); await page.keyboard.press('Escape');
      assert.equal(await field(page, 'donor').inputValue(), donor.value);
      assert.equal(await page.evaluate(() => ElichikaNavigation.currentSection()), 'tools');

      if (profile.mode === 'android') {
        // Closing while POST is in flight must cancel the eventual job id.
        await delayedPostInvalidation(page, () => page.locator('#viewer-game-assets-dialog .modal-head button').click());
        assert.equal(await field(page, 'donor').inputValue(), donor.value);
        // A different tool/form makes the old donor stale, even if the same
        // tool is selected again before the original job id arrives.
        await delayedPostInvalidation(page, async () => {
          await page.evaluate(() => selectTool('skirt'));
          await page.evaluate(() => selectTool('costume_transplant'));
          await field(page, 'donor').fill('/fresh-form-donor.unity');
          await field(page, 'target').fill('/fresh-form-target.unity');
        });
        assert.equal(await field(page, 'donor').inputValue(), '/fresh-form-donor.unity');
        assert.equal(await field(page, 'target').inputValue(), '/fresh-form-target.unity');

        const eventsArrived = deferred(), releaseEvents = deferred(), eventsServed = deferred();
        let doneEvent;
        await page.route('**/api/jobs/*/events', async route => {
          const response = await route.fetch(); const body = await response.text();
          doneEvent = body.split('\n').filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6))).find(item => item.type === 'done');
          assert(doneEvent && doneEvent.status === 'done'); eventsArrived.resolve(); await releaseEvents.promise;
          try { await route.fulfill({ response, body }); }
          catch (error) { if (!/Target|closed|cancel|already handled/i.test(String(error))) throw error; }
          finally { eventsServed.resolve(); }
        });
        await button(page, 'donor').click(); await choose(page); await page.locator('#viewer-game-import').click(); await eventsArrived.promise;
        await page.evaluate(() => changeLang('ja'));
        await page.waitForFunction(() => document.documentElement.lang === 'ja' && !document.querySelector('#viewer-game-assets-dialog').open);
        await field(page, 'donor').fill('/ja-form-donor.unity'); await field(page, 'target').fill('/ja-form-target.unity');
        const japaneseRows = await inputRowLayout(page);
        await page.evaluate(done => { const source = __sources[__sources.length - 1]; if (source.onmessage) source.onmessage({ data: JSON.stringify(done) }); }, doneEvent);
        releaseEvents.resolve(); await eventsServed.promise; await page.unroute('**/api/jobs/*/events');
        await frames(page);
        assert.equal(await field(page, 'donor').inputValue(), '/ja-form-donor.unity');
        assert.equal(await field(page, 'target').inputValue(), '/ja-form-target.unity');
        assert.deepEqual(await modelState(page), originalModel); assert.equal(prepares, prepareCount);

        // This generated rig has no recolour texture. The real job must fail
        // explicitly instead of filling the base-colour body into the field.
        await button(page, 'donor').click(); await choose(page, { suit: 'suit:3' });
        await page.locator('#viewer-game-import').click();
        await page.waitForFunction(() => document.querySelector('#viewer-game-assets-status').classList.contains('viewer-warning'));
        assert(await modal(page).evaluate(node => node.open));
        assert.equal(await field(page, 'donor').inputValue(), '/ja-form-donor.unity');
        await page.keyboard.press('Escape');
        assert.deepEqual(await modelState(page), originalModel); assert.equal(prepares, prepareCount);
        report.cases.push({ name: 'close-before-job-id, changed-form, late-real-SSE-after-language-change and missing-colour refusal', japaneseRows, status: 'PASS' });
      }
      assert.deepEqual(errors, []);
      const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
      assert(layout.scrollWidth <= layout.width + 1);
      await page.screenshot({ path: path.join(evidence, profile.name + '-tools.png') });
      report.cases.push({ profile, donor: donor.value, unmasked: target.value, primary: targetPrimary.value, actualNativeTargets: actualPlatform,
        unchangedViewer: true, noNewViewerPreparation: true, manualPickerAvailable: true, fieldsIndependent: true, inputRows, transplant, layout, status: 'PASS' });
      await context.close();
    }
    assert.deepEqual(snapshot(ready.root), originalInputs, 'Every original catalog and encrypted source pack remains byte-identical');
    report.sourcePacksAndCatalogsUnchanged = true;
    report.sourceAfter = sourceHashes(); assert.deepEqual(report.sourceAfter, report.sourceBefore);
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = error.stack || String(error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close();
    if (child && child.exitCode === null) child.kill('SIGTERM');
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error }));
  }
})();
