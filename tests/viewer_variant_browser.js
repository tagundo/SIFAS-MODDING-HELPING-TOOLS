/* Real product/API variant selection with generated neutral Unity model inputs.
 * VIEWER_URL must point at a host server sharing this filesystem. No game assets.
 */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-variants-'));
fs.mkdirSync(evidence, { recursive: true });
const source = path.join(__dirname, 'fixtures', 'viewer_rig.unity');
const sourceHash = crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  let temporary;
  try {
    const page = await browser.newPage({ viewport: { width: 853, height: 640 }, deviceScaleFactor: 1.5, hasTouch: true });
    page.setDefaultTimeout(30000);
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.url().endsWith('/api/viewer/prepare')) requests.push(request.postDataJSON()); });
    await page.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.THREE);
    const tools = await (await page.request.get(new URL('/api/tools', page.url()).href)).json();
    const library = tools.roots.sukusta || tools.roots.extracted;
    fs.mkdirSync(library, { recursive: true });
    temporary = fs.mkdtempSync(path.join(library, 'viewer-variant-qa-'));
    const first = path.join(temporary, 'first.zip'), second = path.join(temporary, 'second.zip');
    const companion = path.join(temporary, 'companion.unity'), single = path.join(temporary, 'single-model.zip');
    fs.copyFileSync(source, companion);
    execFileSync(process.env.PYTHON_EXECUTABLE || 'python3', ['-c',
      'import pathlib,sys,zipfile;data=pathlib.Path(sys.argv[1]).read_bytes();' +
      '\nfor dest in sys.argv[2:]:\n with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as z:' +
      '\n  z.writestr("board.unity",data);z.writestr("normal.unity",data);' +
      '\n  z.writestr("modinstall.txt","costume_file=\\\"board.unity\\\"\\nrina_unmask_costume_file=\\\"normal.unity\\\"\\n")',
      source, first, second]);
    execFileSync(process.env.PYTHON_EXECUTABLE || 'python3', ['-c',
      'import sys,zipfile\nwith zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED) as z:z.write(sys.argv[1],"single.unity")', companion, single]);
    const sceneDefault = path.join(temporary, 'default-unmasked.zip');
    const sceneExplicit = path.join(temporary, 'explicit-board-without-extension');
    const sceneStale = path.join(temporary, 'stale-default-unmasked.zip');
    const sceneMalformed = path.join(temporary, 'malformed-selection.zip');
    // Generate a real production v2 packet with original-bound recipes. The
    // browser still uses the actual HTTP preparation, parser and GL renderer.
    execFileSync(process.env.PYTHON_EXECUTABLE || 'python3', ['-c',
      'import copy,json,pathlib,sys\nsys.path.insert(0,sys.argv[1])\n' +
      'from test_viewer_scene_roles import SceneRolesTests\n' +
      'from webtools.core import viewer_scene_format as fmt\n' +
      'case=SceneRolesTests();case.setUp()\n' +
      'try:\n token,nodes,_=case.prepare(case.source());_,decoded=case.package(token,case.state(nodes))\n' +
      ' decoded["manifest"].update(target_member_id=109,default_variant="unmasked")\n' +
      ' raw=fmt.encode_package(decoded["manifest"],decoded["files"])\n' +
      ' for name in sys.argv[2:]:pathlib.Path(name).write_bytes(raw)\n' +
      'finally:case.doCleanups()\n',
      __dirname, sceneDefault, sceneExplicit, sceneStale, sceneMalformed], { cwd: path.resolve(__dirname, '..') });
    const originals = [first, second, companion, single, sceneDefault, sceneExplicit, sceneStale, sceneMalformed]
      .map(file => ({ file, hash: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') }));
    await page.locator('.tab[data-tab="viewer"]').click();
    await page.locator('#viewer-file-options').evaluate(element => { element.open = true; });
    await page.locator('#viewer-auto-face').uncheck();
    await page.locator('#viewer-file-options').evaluate(element => { element.open = false; });
    await page.evaluate(file => openModelViewer([file]), first);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    const initial = await state(page);
    assert.equal(initial.stats.meshes, 1, 'Default ZIP must not combine the two whole bodies');
    assert.deepEqual(initial.loadedArchiveVariants, ['primary']);
    assert(!requests[0].archive_variants, 'Ordinary initial input keeps the legacy request shape');
    async function menu() {
      if (!(await page.locator('#viewer-view-menu').evaluate(element => element.open))) await page.locator('#viewer-view-menu > summary').click();
    }
    async function select(index, value) {
      await menu();
      await page.locator('#viewer-variant-' + index).selectOption(value);
      await page.waitForFunction(([index, value]) => {
        const state = ModelViewer.getState(); return !state.loading && state.loadedArchiveVariants[index] === value && !state.error;
      }, [index, value]);
    }
    await menu();
    const hit = await page.locator('#viewer-variant-0').evaluate(element => {
      element.scrollIntoView({ block: 'center' }); const r = element.getBoundingClientRect();
      return { width: r.width, height: r.height, hit: document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === element,
        label: element.getAttribute('aria-label'), inStage: !!element.closest('#viewer-stage') };
    });
    assert(hit.width >= 44 && hit.height >= 44 && hit.hit && hit.inStage && hit.label.includes('Rina face'));
    await page.locator('#viewer-high-quality').check();
    const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
    await page.locator('#viewer-motion').selectOption(clip);
    await page.locator('#viewer-time').evaluate(element => { element.value = '.37'; element.dispatchEvent(new Event('input', { bubbles: true })); });
    await page.locator('#viewer-breast-card').evaluate(element => { element.open = false; });
    await page.locator('#viewer-skirt-card').evaluate(element => { element.open = false; });
    await page.locator('#viewer-fullscreen').click();
    await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'browser');
    const beforeVariant = await state(page);
    await select(0, 'unmasked');
    const unmasked = await state(page);
    assert.equal(unmasked.stats.meshes, 1); assert.deepEqual(unmasked.camera, beforeVariant.camera);
    assert.equal(unmasked.layout.fullscreen, 'browser');
    assert.equal(unmasked.quality.enabled, true); assert.equal(await page.locator('#viewer-high-quality').isChecked(), true);
    assert.equal(unmasked.rig.selectedClip, beforeVariant.rig.selectedClip);
    assert.equal(unmasked.rig.time, beforeVariant.rig.time);
    assert.equal(await page.locator('#viewer-breast-card').evaluate(element => element.open), false);
    assert.equal(await page.locator('#viewer-skirt-card').evaluate(element => element.open), false);
    assert.deepEqual(requests[requests.length - 1].archive_variants, { '0': 'unmasked' });
    await page.locator('#viewer-pose-basic').click();
    await select(0, 'primary');
    const primary = await state(page); assert.deepEqual(primary.camera, beforeVariant.camera);
    assert.equal(primary.rig.selectedClip, '', 'Variant reload retains the explicit basic pose');
    assert(primary.quality.enabled);
    assert.equal(primary.layout.fullscreen, 'browser');
    await page.locator('#viewer-fullscreen').click();
    await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'none');
    const locales = [];
    for (const [language, title, labels] of [['ko', '리나 얼굴', ['리나 보드', '일반 얼굴']], ['ja', '璃奈の顔', ['璃奈ちゃんボード', '素顔']], ['en', 'Rina face', ['Rina board', 'Normal face']]]) {
      await page.locator('#lang-select').selectOption(language);
      await page.waitForFunction(title => document.getElementById('viewer-variant-0').getAttribute('aria-label').includes(title), title);
      await menu();
      const actual = await page.locator('#viewer-variant-0').evaluate(element => ({ title: element.getAttribute('aria-label'), labels: Array.from(element.options, option => option.textContent) }));
      assert(actual.title.includes(title)); assert.deepEqual(actual.labels, labels); locales.push({ language, ...actual });
    }
    // Delegate the actual parser and delay only its completion callback. A
    // cancelled old GLTF must be disposed, never committed over the new model.
    await page.evaluate(() => {
      const parse = THREE.GLTFLoader.prototype.parse; window.__variantHoldNext = true;
      THREE.GLTFLoader.prototype.parse = function (data, resource, loaded, failed) {
        const hold = window.__variantHoldNext; window.__variantHoldNext = false;
        return parse.call(this, data, resource, function (gltf) {
          if (hold) window.__variantHeld = { gltf, loaded }; else loaded(gltf);
        }, failed);
      };
    });
    await menu(); await page.locator('#viewer-variant-0').selectOption('unmasked');
    await page.waitForFunction(() => !!window.__variantHeld);
    assert(await page.locator('#viewer-variant-0').isDisabled(), 'Choices are disabled while the actual model is loading');
    await page.locator('#viewer-cancel').click();
    assert.equal((await state(page)).loadedArchiveVariants[0], 'primary');
    await select(0, 'primary');
    const latest = await state(page);
    await page.evaluate(() => { __variantHeld.loaded(__variantHeld.gltf); delete window.__variantHeld; });
    await frames(page);
    const afterStale = await state(page);
    assert.equal(afterStale.modelId, latest.modelId); assert.deepEqual(afterStale.loadedArchiveVariants, ['primary']);
    assert(!afterStale.loading && !afterStale.error);
    await page.evaluate(files => openModelViewer(files), [first, second, companion]);
    await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().stats.meshes === 3);
    await select(1, 'unmasked');
    const multiple = await state(page); assert.equal(multiple.stats.meshes, 3);
    assert.deepEqual(multiple.loadedArchiveVariants, ['primary', 'unmasked', 'primary']);
    assert.deepEqual(requests[requests.length - 1].archive_variants, { '0': 'primary', '1': 'unmasked' });
    assert.equal(await page.locator('[data-viewer-variant-index]').count(), 2);
    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.getElementById('viewer-variant-0').getAttribute('aria-label').includes('리나 얼굴'));
    const layouts = [];
    for (const viewport of [{ width: 320, height: 740 }, { width: 360, height: 456 }, { width: 640, height: 360 }, { width: 853, height: 640 }]) {
      await page.setViewportSize(viewport); await frames(page); await menu();
      const result = await page.evaluate(() => {
        const controls = ['viewer-variant-0', 'viewer-variant-1', 'viewer-pose-basic', 'viewer-pose-preview', 'viewer-high-quality'].map(id => {
          const input = document.getElementById(id), element = id === 'viewer-high-quality' ? input.closest('label') : input;
          element.scrollIntoView({ block: 'center' }); const r = element.getBoundingClientRect();
          const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { id, width: r.width, height: r.height, hit: hit === element || element.contains(hit), disabled: !!input.disabled,
            withinViewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight };
        });
        return { controls, language: document.documentElement.lang, overflow: document.documentElement.scrollWidth > innerWidth + 1 };
      });
      assert.equal(result.language, 'ko'); assert(!result.overflow);
      for (const control of result.controls) {
        const minimum = control.id.startsWith('viewer-variant-') ? 44 : 32;
        assert(control.width >= minimum && control.height >= minimum && control.hit && control.withinViewport, JSON.stringify({ viewport, control }));
      }
      assert(result.controls.filter(control => control.id !== 'viewer-pose-preview').every(control => !control.disabled));
      layouts.push({ viewport, ...result });
      await page.screenshot({ path: path.join(evidence, 'variant-' + viewport.width + 'x' + viewport.height + '.png') });
    }
    const probe = await page.evaluate(() => ModelViewer.renderProbe()); assert(probe.ready && probe.nonBackgroundSamples > 0 && probe.glError === 0);
    const defaults = {};
    async function ready() {
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !ModelViewer.getState().error);
      return state(page);
    }
    await page.evaluate(file => openModelViewer([file]), sceneDefault);
    defaults.implicit = await ready();
    assert.deepEqual(defaults.implicit.archiveVariants, ['unmasked']);
    assert.deepEqual(defaults.implicit.loadedArchiveVariants, ['unmasked']);
    assert.equal(await page.locator('#viewer-variant-0').inputValue(), 'unmasked');
    assert(!requests[requests.length - 1].archive_variants, 'A first file-picker open leaves the server default unspecified');
    const afterDefaultRequests = requests.length;
    await frames(page); await frames(page);
    assert.equal(requests.length, afterDefaultRequests, 'Resolving the declared default must not reload the model');
    assert(!defaults.implicit.error && defaults.implicit.persistence.available);
    await page.locator('#viewer-load').click();
    await ready();
    assert.deepEqual(requests[requests.length - 1].archive_variants, { '0': 'unmasked' }, 'A committed default is stable on refresh');
    // A fresh explicit board request must survive even when the valid ZIP has
    // no .zip suffix. Game Assets uses this same openModelViewer choice API.
    await page.evaluate(file => openModelViewer([file], { 0: 'primary' }), sceneExplicit);
    defaults.explicit = await ready();
    assert.deepEqual(defaults.explicit.loadedArchiveVariants, ['primary']);
    assert.deepEqual(requests[requests.length - 1].archive_variants, { '0': 'primary' });
    const retained = await page.evaluate(() => ({ modelId: ModelViewer.getState().modelId,
      camera: ModelViewer.getState().camera, body: ModelViewer.getAuthoringState() }));
    // Corrupt only an actual response for negative validation. No successful
    // model or metadata response is fabricated by the test.
    const refusals = [];
    for (const fault of ['unknown', 'mismatched-explicit', 'missing-explicit']) {
      await page.route('**/api/viewer/prepare', async route => {
        const response = await route.fetch(), body = await response.json();
        assert.equal(response.status(), 200);
        if (fault === 'unknown') body.variants[0].selected = 'other';
        else if (fault === 'mismatched-explicit') body.variants[0].selected = 'unmasked';
        else body.variants = [];
        await route.fulfill({ response, json: body });
      });
      try {
        await page.evaluate(({ file, explicit }) => openModelViewer([file], explicit ? { 0: 'primary' } : undefined),
          { file: sceneMalformed, explicit: fault !== 'unknown' });
        await page.waitForFunction(() => !ModelViewer.getState().loading && !!ModelViewer.getState().error);
        const actual = await state(page);
        assert.equal(actual.modelId, retained.modelId, 'Rejected metadata must leave the prior model intact');
        assert.deepEqual(actual.camera, retained.camera);
        assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), retained.body);
        assert.deepEqual(actual.loadedArchiveVariants, ['primary']);
        refusals.push({ fault, error: actual.error });
      } finally { await page.unroute('**/api/viewer/prepare'); }
    }
    // Hold an actual prepare response independently of AbortSignal, modeling
    // a transport that completes after cancellation. Its data stays unchanged.
    await page.evaluate(() => {
      const real = window.fetch; window.__variantDefaultHold = true;
      window.fetch = async function (url, options) {
        if (window.__variantDefaultHold && String(url) === '/api/viewer/prepare') {
          window.__variantDefaultHold = false;
          const response = await real.call(this, url, Object.assign({}, options, { signal: undefined }));
          const metadata = await response.clone().json();
          window.__variantDefaultMetadata = metadata.variants;
          return new Promise(resolve => { window.__variantDefaultRelease = () => resolve(response); });
        }
        return real.apply(this, arguments);
      };
      window.__variantRestoreFetch = () => { window.fetch = real; };
    });
    await page.evaluate(file => { window.__variantDefaultOldLoad = openModelViewer([file]); }, sceneStale);
    await page.waitForFunction(() => !!window.__variantDefaultRelease);
    assert.deepEqual(await page.evaluate(() => __variantDefaultMetadata.map(record => record.selected)), ['unmasked']);
    assert.deepEqual((await state(page)).archiveVariants, ['primary'], 'Pending implicit defaults are local until commit');
    await page.evaluate(file => openModelViewer([file], { 0: 'primary' }), sceneExplicit);
    const beforeLateDefault = await ready();
    await page.evaluate(async () => { __variantDefaultRelease(); await __variantDefaultOldLoad; __variantRestoreFetch(); });
    await frames(page);
    const afterLateDefault = await state(page);
    assert.equal(afterLateDefault.modelId, beforeLateDefault.modelId);
    assert.deepEqual(afterLateDefault.archiveVariants, ['primary']);
    assert.deepEqual(afterLateDefault.loadedArchiveVariants, ['primary']);
    assert(!afterLateDefault.loading && !afterLateDefault.error);
    // Exercise the distinct post-admission/precommit window too: prepare has
    // already selected unmasked, but the real parser completion is still held.
    await page.evaluate(() => { window.__variantHoldNext = true; });
    await page.evaluate(file => { window.__variantDefaultParserLoad = openModelViewer([file]); }, sceneStale);
    await page.waitForFunction(() => !!window.__variantHeld);
    const admittedPending = await state(page);
    assert(admittedPending.loading);
    assert.deepEqual(admittedPending.archiveVariants, ['primary'], 'An admitted default must not mutate selection before GLTF commit');
    assert.deepEqual(admittedPending.loadedArchiveVariants, ['primary'], 'An admitted default must not mutate loaded variants before GLTF commit');
    await page.evaluate(file => openModelViewer([file], { 0: 'primary' }), sceneStale);
    const beforeLateParser = await ready();
    const parserBody = await page.evaluate(() => ModelViewer.getAuthoringState());
    await page.evaluate(async () => { __variantHeld.loaded(__variantHeld.gltf); delete window.__variantHeld; await __variantDefaultParserLoad; });
    await frames(page);
    const afterLateParser = await state(page);
    assert.equal(afterLateParser.modelId, beforeLateParser.modelId);
    assert.deepEqual(afterLateParser.archiveVariants, ['primary']);
    assert.deepEqual(afterLateParser.loadedArchiveVariants, ['primary']);
    assert.deepEqual(afterLateParser.camera, beforeLateParser.camera);
    assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), parserBody);
    assert(!afterLateParser.loading && !afterLateParser.error);
    defaults.staleAfterAdmission = { modelId: afterLateParser.modelId, variants: afterLateParser.loadedArchiveVariants };
    await page.evaluate(file => openModelViewer([file]), single);
    const ordinarySingle = await ready();
    assert.deepEqual(ordinarySingle.loadedArchiveVariants, ['primary']);
    assert.equal(await page.locator('[data-viewer-variant-index]').count(), 0);
    assert(!requests[requests.length - 1].archive_variants, 'A single-model ZIP without alternatives keeps its ordinary request shape');
    // Raw source refresh must never become an explicit ZIP choice merely
    // because its nonvariant fallback is primary.
    await page.evaluate(file => openModelViewer([file]), companion);
    await ready();
    assert(!requests[requests.length - 1].archive_variants);
    await page.locator('#viewer-load').click(); await ready();
    assert(!requests[requests.length - 1].archive_variants);
    await page.evaluate(() => {
      const target = ModelViewer.getEditingMetadata().nodes.find(node => node.name === 'Move' && node.methods.includes('mesh'));
      if (!target) throw Error('The neutral raw fixture has no writable Move bone');
      ModelViewer.restoreAuthoringState({ version: 1, savedSettingsEnabled: true,
        edits: [{ node: target.node, method: 'mesh', scale: [1.2, 1.05, 1] }], unsupported: [] });
    });
    async function reveal(selector) {
      await page.locator(selector).evaluate(element => {
        for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
          if (ancestor.tagName === 'DETAILS') ancestor.open = true;
        }
      });
      await page.locator(selector).scrollIntoViewIfNeeded();
    }
    await reveal('#viewer-save'); await page.locator('#viewer-save').click();
    await page.waitForFunction(() => {
      const persistence = ModelViewer.getState().persistence;
      return !persistence.busy && (persistence.status === 'done' || !!persistence.error);
    });
    assert.equal((await state(page)).persistence.error, '');
    await reveal('#viewer-open-saved'); await page.locator('#viewer-open-saved').click();
    await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
    assert(!requests[requests.length - 1].archive_variants, 'Raw saved-result {} must not become an explicit archive primary');
    await reveal('#viewer-reedit-original'); await page.locator('#viewer-reedit-original').click();
    await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().persistence.status === 'restored');
    assert(!requests[requests.length - 1].archive_variants, 'Raw original/recipe reopening keeps its empty archive choices');
    defaults.rawReopen = { variants: (await state(page)).loadedArchiveVariants, request: requests[requests.length - 1] };
    defaults.refusals = refusals;
    defaults.stale = { modelId: afterLateDefault.modelId, variants: afterLateDefault.loadedArchiveVariants };
    const rawProbe = await page.evaluate(() => ModelViewer.renderProbe()); assert(rawProbe.ready && rawProbe.nonBackgroundSamples > 0 && rawProbe.glError === 0);
    for (const { file, hash } of originals) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), hash);
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex'), sourceHash);
    assert.deepEqual(errors, []);
    const report = { status: 'PASS', scope: 'Real local API/GL/DOM with neutral serialized Unity rigs; actual browser fullscreen; delegated parser callback delay only for stale-result regression',
      rawProbe, hit, initial: { stats: initial.stats, variants: initial.loadedArchiveVariants }, unmasked: { stats: unmasked.stats, variants: unmasked.loadedArchiveVariants },
      defaults, locales, stale: { latestId: latest.modelId, retainedId: afterStale.modelId }, multiple: { stats: multiple.stats, variants: multiple.loadedArchiveVariants }, layouts, probe, requests, errors };
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: 'PASS', evidence, requests: requests.length, layouts, errors }));
  } finally { await browser.close(); if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exit(1); });
