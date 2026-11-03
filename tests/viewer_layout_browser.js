/* Actual product WebGL/DOM layout and fullscreen lifecycle checks using only
 * original generated geometry. Run with VIEWER_URL pointing at local WebUI. */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-layout-'));
fs.mkdirSync(evidence, { recursive: true });
const generated = fixture({ allSaved: true, semanticExpressions: true, previewName: 'Verified original preview', previewVerified: true });
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());
const retained = value => ({ camera: value.camera, modelId: value.modelId, paths: value.loadedPaths,
  rig: { body: value.rig.body, selectedClip: value.rig.selectedClip, time: value.rig.time,
    playing: value.rig.playing, nodeAdjustments: value.rig.nodeAdjustments,
    nodeCompensations: value.rig.nodeCompensations, expressions: value.rig.expressions,
    savedEnabled: value.rig.savedNodes.enabled, savedGroups: value.rig.savedNodes.groups.map(({ id, enabled, nodes, settings }) => ({ id, enabled, nodes, settings })) } });
function originalUnityTriangle() {
  const source = path.join(__dirname, 'fixtures', 'viewer_textured_triangle.unity');
  const data = JSON.parse(execFileSync(process.env.PYTHON_EXECUTABLE || 'python3', ['-c',
    'import base64,hashlib,json,sys;from pathlib import Path;from webtools.core import model_viewer as v;' +
    'p=Path(sys.argv[1]);m=v.prepare([str(p)],rigged=True);' +
    'print(json.dumps({"metadata":m,"rawMetadata":json.dumps(m,ensure_ascii=False,separators=(",",":")),"glb":base64.b64encode(v.get_model(m["id"])).decode(),"sourceSha256":hashlib.sha256(p.read_bytes()).hexdigest()}))', source],
  { cwd: path.join(__dirname, '..'), encoding: 'utf8' }));
  assert.equal(data.sourceSha256, '512035f15592dd8a32bdeca4cacaaf2ea8a9c5d70c9b269080c9348ebf537fd4', 'Use the unchanged Unity fixture from the official Android pixel test');
  // Retain this already-authorized conversion for independent host checks.
  // The Python-produced metadata text and model bytes are written without field changes.
  fs.writeFileSync(path.join(evidence, 'original-unity-metadata.json'), data.rawMetadata);
  fs.writeFileSync(path.join(evidence, 'original-unity-model.glb'), Buffer.from(data.glb, 'base64'));
  fs.writeFileSync(path.join(evidence, 'original-unity-source.json'), JSON.stringify({ source, sourceSha256: data.sourceSha256 }));
  return { ...data.metadata, glb: Buffer.from(data.glb, 'base64'), sourceSha256: data.sourceSha256 };
}
async function openPage(browser, mode = 'browser', viewport = { width: 853, height: 590 }, dpr = 1.5, model = generated) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: dpr, hasTouch: true });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(({ mode }) => {
    localStorage.setItem('sifas_lang', 'en');
    if (mode === 'rejected') HTMLElement.prototype.requestFullscreen = function () {
      return Promise.reject(new DOMException('Fullscreen denied in test', 'NotAllowedError'));
    };
    if (mode === 'native' || mode === 'native-held') {
      window.__nativeFullscreenMessages = [];
      window.ElichikaViewerFullscreen = { postMessage(value) {
        __nativeFullscreenMessages.push(value);
        if (mode !== 'native-held') setTimeout(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: value === 'enter', settled: true } })), 0);
      } };
    }
  }, { mode });
  await page.route('**/api/viewer/prepare', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ id: 'layout-original', url: '/api/viewer/model/layout-original.glb', warnings: mode === 'touch' ? Array.from({ length: 12 }, (_, i) => 'Original QA diagnostic ' + i + ': this generated warning provides a long, scrollable information panel for touch verification.') : [],
      stats: model.stats || { meshes: 1, vertices: 3, triangles: 1, textures: 0, materials: 1 }, rig: model.rig }) }));
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: model.glb }));
  await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
  await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerRig);
  await page.evaluate(source => openModelViewer([source]), model.sourceSha256 ? '/original/viewer-qa-832049459529.unity' : '/original/layout.unity');
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
  return { page, context, errors };
}
async function metrics(page) {
  await frames(page);
  return page.evaluate(() => {
    const rect = selector => { const element = document.querySelector(selector), r = element.getBoundingClientRect();
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
    const probe = ModelViewer.renderProbe(33), canvas = document.getElementById('viewer-canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl'), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const pixels = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    const background = (w + 1) * 4; let top = h, bottom = -1, count = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (Math.abs(pixels[i] - pixels[background]) + Math.abs(pixels[i + 1] - pixels[background + 1]) + Math.abs(pixels[i + 2] - pixels[background + 2]) > 24) {
        top = Math.min(top, y); bottom = Math.max(bottom, y); count++;
      }
    }
    const controls = {};
    for (const selector of ['#viewer-expand', '#viewer-fullscreen', '#viewer-pose-basic', '#viewer-pose-preview',
      '#viewer-fit', '[data-viewer-view="front"]', '[data-viewer-view="back"]', '[data-viewer-view="left"]', '[data-viewer-view="right"]']) {
      const element = document.querySelector(selector), r = element.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
      const hit = x >= 0 && y >= 0 && x < innerWidth && y < innerHeight ? document.elementFromPoint(x, y) : null;
      controls[selector] = { ...rect(selector), hit: !!hit && (hit === element || element.contains(hit)), disabled: !!element.disabled };
    }
    return { stage: rect('#viewer-stage'), sidebar: rect('.viewer-control-panel'), breast: rect('#viewer-breast-card'),
      skirt: rect('#viewer-skirt-card'), viewport: { width: innerWidth, height: innerHeight },
      sidebarDisplayed: document.querySelector('.viewer-control-panel').getClientRects().length > 0,
      foregroundHeight: (bottom - top + 1) / h * canvas.getBoundingClientRect().height, foregroundPixels: count,
      controls, overflow: document.documentElement.scrollWidth > innerWidth + 1, glError: gl.getError(), probe, layout: ModelViewer.getState().layout };
  });
}
function assertHud(value) {
  for (const [name, control] of Object.entries(value.controls)) {
    assert(control.width >= 44 && control.height >= 44, name + ' must keep a44px target: ' + JSON.stringify(control));
    assert(control.x >= value.stage.x - 1 && control.right <= value.stage.right + 1 &&
      control.y >= value.stage.y - 1 && control.bottom <= value.stage.bottom + 1, name + ' must remain inside model viewport');
    assert(control.x >= -1 && control.right <= value.viewport.width + 1 && control.y >= -1 && control.bottom <= value.viewport.height + 1,
      name + ' must remain inside the screen');
    assert(control.hit, name + ' must be reachable without scrolling the model offscreen');
  }
  assert.equal(value.overflow, false);
  assert.equal(value.glError, 0);
  assert(value.foregroundPixels > 100 && value.foregroundHeight > 50, 'Real model pixels must remain visible');
}
// An empty viewer already provides a natural document scroll range. Its later
// file bar must not cover any part of the sticky primary navigation targets.
async function stickyHeaderNaturalScroll(browser) {
  const context = await browser.newContext({ viewport: { width: 752, height: 699 }, deviceScaleFactor: 1.125 });
  const page = await context.newPage(), errors = [], modelRequests = [], observations = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => { if (request.url().includes('/api/viewer/prepare')) modelRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
  try {
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => !!window.ModelViewer && typeof openModelViewer === 'function');
    await page.locator('.tab[data-tab="viewer"]').click(); await frames(page);
    assert(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight), 'Use the real unloaded-viewer document scroll range');
    for (let step = 0; step < 12; step++) {
      if (step) {
        // Scroll the real document margin, leaving the canvas wheel gesture for zoom.
        await page.mouse.move(750, 500); await page.mouse.wheel(0, 100);
        if (step === 1) await page.waitForFunction(() => scrollY > 0, null, { timeout: 5000 });
        await frames(page);
      }
      const observation = await page.evaluate(() => {
        const target = document.querySelector('.tab[data-tab="tools"]'), header = document.querySelector('body > header'), files = document.querySelector('#tab-viewer .viewer-files');
        const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
        const r = target.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2, edge = 21, diagonal = edge / Math.sqrt(2);
        const samples = [[0, 0], [-edge, 0], [edge, 0], [0, -edge], [0, edge], [-diagonal, -diagonal], [diagonal, -diagonal], [-diagonal, diagonal], [diagonal, diagonal]].map(([dx, dy]) => {
          const hit = document.elementFromPoint(x + dx, y + dy);
          return { x: x + dx, y: y + dy, hit: !!hit && (hit === target || target.contains(hit)), tag: hit && hit.tagName, id: hit && hit.id };
        });
        return { scrollY, viewport: { width: innerWidth, height: innerHeight }, target: rect(target), header: rect(header), files: rect(files), samples,
          headerZ: getComputedStyle(header).zIndex, fileBarZ: getComputedStyle(files).zIndex, loaded: ModelViewer.getState().loaded };
      });
      assert(observation.target.width >= 43.5 && observation.target.height >= 43.5 && observation.samples.every(sample => sample.hit),
        'All nine actual points in the primary Tools touch target remain reachable during natural scroll: ' + JSON.stringify(observation));
      assert.equal(observation.loaded, false); observations.push(observation);
    }
    assert(observations.some(value => value.scrollY > 0 && value.files.y < value.target.bottom && value.files.bottom > value.target.y),
      'Natural mouse-wheel scrolling must move the real file bar behind the sticky navigation: ' + JSON.stringify(observations));
    await page.locator('.tab[data-tab="tools"]').click();
    assert(await page.locator('#tab-tools').evaluate(element => element.classList.contains('active')), 'The scrolled Tools target performs its actual navigation');
    assert.deepEqual(errors, []); assert.deepEqual(modelRequests, []);
    return { status: 'PASS', scope: 'Actual empty viewer and mouse-wheel document scroll; no padding, overlays or model preparation', observations };
  } finally { await context.close(); }
}
// Native webview-sized CSS profiles cover the tablet, inner Fold orientations,
// and cover orientations. These are host layout regressions, not device claims.
async function primaryNavigationTargets(browser) {
  const profiles = [
    { id: 'tablet', width: 1692, height: 919 },
    { id: 'fold-portrait', width: 752, height: 669 },
    { id: 'fold-landscape', width: 835, height: 587 },
    { id: 'cover-portrait', width: 360, height: 675 },
    { id: 'cover-landscape', width: 840, height: 195 }
  ];
  const { page, context, errors } = await openPage(browser, 'browser', profiles[0], 1);
  const rows = [];
  try {
    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.documentElement.lang === 'ko');
    await frames(page);
    const before = retained(await state(page));
    async function target(selector) {
      const control = page.locator(selector); await control.scrollIntoViewIfNeeded(); await frames(page);
      const value = await control.evaluate(element => {
        const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return { width: r.width, height: r.height, x: r.x, y: r.y, right: r.right, bottom: r.bottom,
          visibleWidth: Math.max(0, Math.min(innerWidth, r.right) - Math.max(0, r.x)),
          visibleHeight: Math.max(0, Math.min(innerHeight, r.bottom) - Math.max(0, r.y)),
          hit: !!hit && (hit === element || element.contains(hit)) };
      });
      assert(value.width >= 43.5 && value.height >= 43.5 && value.visibleWidth >= 43.5 && value.visibleHeight >= 43.5 && value.hit,
        selector + ' keeps a visible, reachable44px primary navigation target: ' + JSON.stringify(value));
      return { selector, ...value };
    }
    async function geometry() {
      await frames(page);
      return page.evaluate(() => {
        const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
        const sidebar = document.querySelector('.viewer-control-panel');
        return { viewport: { width: innerWidth, height: innerHeight }, stage: rect('#viewer-stage'), sidebar: rect('.viewer-control-panel'),
          sidebarDisplayed: sidebar.getClientRects().length > 0, breast: rect('#viewer-breast-card'), skirt: rect('#viewer-skirt-card'),
          overflow: document.documentElement.scrollWidth > innerWidth + 1, layout: ModelViewer.getState().layout };
      });
    }
    for (const profile of profiles) {
      await page.setViewportSize({ width: profile.width, height: profile.height });
      await page.evaluate(() => scrollTo(0, 0)); await frames(page);
      const workspace = page.locator('#viewer-workspace-menu');
      if (await page.locator('#viewer-workspace-menu > summary').isVisible() && !(await workspace.evaluate(n => n.open))) await workspace.locator('summary').first().click();
      const controls = [];
      for (const selector of ['.tab[data-tab="tools"]', '.tab[data-tab="viewer"]', '.tab[data-tab="gallery"]', '#lang-select']) controls.push(await target(selector));
      await page.locator('.tab[data-tab="tools"]').click(); await frames(page);
      assert(await page.locator('#tab-tools').evaluate(n => n.classList.contains('active')));
      const toolButtons = await page.locator('#tool-list button').evaluateAll(buttons => buttons.map(button => ({ id: button.dataset.id, width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })));
      assert(toolButtons.length > 0 && toolButtons.every(button => button.height >= 44), 'Every tool-list entry keeps its44px height: ' + JSON.stringify(toolButtons));
      controls.push(await target('#tool-list button[data-id="mesh_baker"]'));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Tools navigation must not overflow the page');
      await page.locator('.tab[data-tab="viewer"]').click(); await frames(page);
      await page.evaluate(() => { const workspace = document.getElementById('viewer-workspace-menu'); if (workspace.open) workspace.querySelector('summary').click(); scrollTo(0, 0); });
      const normal = await geometry();
      assert.equal(normal.overflow, false); assert(normal.stage.height >= profile.height * .55, 'Navigation sizing retains meaningful model height');
      if (profile.width >= 720 && !normal.layout.shortHeight) {
        assert(normal.stage.right <= normal.sidebar.x + 1 && normal.sidebar.width >= 280, 'Model and usable editor retain separate columns');
        assert(normal.breast.width <= 380 && normal.skirt.width <= 380, 'Body cards remain compact');
        if (profile.width >= 1200) assert(normal.stage.width <= normal.stage.height * 1.27, 'Tablet preview does not waste width beside a standing model');
      }
      assert.deepEqual(retained(await state(page)), before, 'Real app navigation and resizing retain the loaded model and edits');
      await page.locator('#viewer-expand').click();
      const expanded = await geometry();
      assert.equal(expanded.overflow, false); assert.equal(expanded.sidebarDisplayed, false);
      assert(expanded.stage.height >= profile.height * .88 && expanded.stage.x >= -1 && expanded.stage.right <= profile.width + 1, 'Expanded model uses the available height without page overflow');
      assert.deepEqual(retained(await state(page)), before);
      await page.locator('#viewer-expand').click(); await frames(page);
      assert.deepEqual(retained(await state(page)), before);
      rows.push({ profile, controls, toolButtons, normal, expanded });
    }
    assert.deepEqual(errors, []); return rows;
  } finally { await context.close(); }
}
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const report = { status: 'RUNNING', scope: 'Original generated rig through real viewer/GL/DOM and actual browser fullscreen', layouts: [], lifecycles: [] };
  try {
    report.headerNaturalScroll = await stickyHeaderNaturalScroll(browser);
    report.primaryNavigation = await primaryNavigationTargets(browser);
    if (process.env.VIEWER_NAVIGATION_TARGETS_ONLY === '1') {
      report.status = 'PASS'; report.runMode = 'FIVE_PROFILE_PRIMARY_NAVIGATION_ONLY';
      fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
      console.log(JSON.stringify({ status: report.status, navigationProfiles: report.primaryNavigation.length, evidence }));
      return;
    }
    {
      const model = originalUnityTriangle();
      const { page, context, errors } = await openPage(browser, 'browser', { width: 360, height: 456 }, 2, model);
      report.shortPhone = { sourceSha256: model.sourceSha256, languages: [] };
      for (const language of ['en', 'ko', 'ja']) {
        await page.locator('#lang-select').selectOption(language);
        await page.evaluate(() => window.scrollTo(0, 0));
        await frames(page);
        const before = retained(await state(page));
        const normal = await metrics(page);
        const sparseProbe = await page.evaluate(() => ModelViewer.renderProbe());
        assert(sparseProbe.ready && sparseProbe.sourceTriangles >= 1 && sparseProbe.triangles >= 1 &&
          sparseProbe.nonBackgroundSamples >= 5 && sparseProbe.chromaticSamples >= 3 &&
          sparseProbe.width >= 100 && sparseProbe.height >= 100 && sparseProbe.glError === 0,
        'The exact official Unity texture fixture must pass the unchanged native sparse pixel thresholds: ' + JSON.stringify({ language, sparseProbe, layout: normal.layout }));
        assert.equal(sparseProbe.gridSize, 11, 'Use the production default sparse probe; denser samples would mask a tiny model');
        assert(normal.layout.compactControls, 'Short phone view reserves model space by grouping view controls');
        assert(normal.layout.safeInsets.top <= 55 && normal.layout.safeInsets.bottom <= 55,
          'The closed phone HUD must occupy one 44 px row at each edge');
        assert(normal.stage.height - normal.layout.safeInsets.top - normal.layout.safeInsets.bottom >= 150,
          'The actual short phone must retain usable unobscured model height: ' + JSON.stringify({ language, stage: normal.stage, safeInsets: normal.layout.safeInsets }));
        assert.equal(normal.overflow, false);
        assert.equal(await page.locator('#viewer-view-menu').evaluate(element => element.open), false);
        assert(await page.locator('#viewer-file-options').evaluate(element => element.contains(document.getElementById('viewer-file-list'))),
          'The loaded filename stays accessible in Model options without another row above the phone model');
        async function assertReachable(selector) {
          const control = await page.locator(selector).evaluate(element => {
            const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return { width: r.width, height: r.height, x: r.x, y: r.y, right: r.right, bottom: r.bottom,
              hit: !!hit && (hit === element || element.contains(hit)), viewportWidth: innerWidth, viewportHeight: innerHeight };
          });
          assert(control.width >= 44 && control.height >= 44 && control.x >= 0 && control.y >= 0 &&
            control.right <= control.viewportWidth + 1 && control.bottom <= control.viewportHeight + 1 && control.hit,
          selector + ' remains a reachable 44 px control on the exact failing phone viewport: ' + JSON.stringify(control));
          return { selector, ...control };
        }
        const primaryNavigation = [];
        for (const selector of ['.tab[data-tab="tools"]', '.tab[data-tab="viewer"]', '.tab[data-tab="gallery"]', '#lang-select']) primaryNavigation.push(await assertReachable(selector));
        assert(Math.max(...primaryNavigation.map(value => value.y + value.height / 2)) - Math.min(...primaryNavigation.map(value => value.y + value.height / 2)) <= 1,
          'Short-phone primary navigation and language selection share one reachable row: ' + JSON.stringify(primaryNavigation));
        assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1, 'The visually compact brand remains an accessible heading');
        assert.equal(normal.layout.expanded, false); assert.equal(normal.layout.fullscreen, 'none');
        for (const selector of ['#viewer-view-menu > summary', '#viewer-expand', '#viewer-fullscreen', '#viewer-fit']) await assertReachable(selector);
        await page.locator('#viewer-view-menu > summary').click();
        assert(await page.locator('#viewer-view-menu').evaluate(element => element.open));
        for (const selector of ['#viewer-pose-basic', '#viewer-pose-preview', '.viewer-quality-choice']) await assertReachable(selector);
        await page.locator('#viewer-high-quality').check();
        await page.waitForFunction(() => { const q = ModelViewer.getState().quality; return q.enabled && q.ready; });
        await page.locator('#viewer-high-quality').uncheck();
        await page.waitForFunction(() => { const q = ModelViewer.getState().quality; return !q.enabled && q.ready; });
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#viewer-view-menu').evaluate(element => element.open), false);
        assert.deepEqual(retained(await state(page)), before, 'Opening view controls and quality round-trip preserve the model, rig and camera');
        await page.screenshot({ path: path.join(evidence, 'short-phone-' + language + '.png') });
        await page.setViewportSize({ width: 456, height: 360 }); await frames(page);
        assert.deepEqual(retained(await state(page)), before, 'Phone orientation reflow preserves camera, pose and edits');
        await page.setViewportSize({ width: 360, height: 456 }); await frames(page);
        assert.deepEqual(retained(await state(page)), before);
        report.shortPhone.languages.push({ language, normal, sparseProbe, primaryNavigation });
      }
      assert.deepEqual(errors, []); await context.close();
    }
    const { page, context, errors } = await openPage(browser);
    await page.locator('#viewer-breast-preset').selectOption('rin');
    await page.locator('#viewer-skirt-number').fill('.9'); await page.locator('#viewer-skirt-apply').click();
    await page.locator('#viewer-node-editor').evaluate(element => { element.open = true; });
    await page.locator('#viewer-node').selectOption('3');
    await page.locator('[data-viewer-node-kind="position"][data-axis="X"]').fill('.2');
    const original = retained(await state(page)), sections = ['viewer-breast-card', 'viewer-skirt-card', 'viewer-common-adjustments'];
    for (const id of sections) {
      const summary = page.locator('#' + id + ' > summary'); await summary.scrollIntoViewIfNeeded();
      const before = await page.locator('#' + id).evaluate(element => element.getBoundingClientRect().height);
      await summary.click();
      assert.equal(await page.locator('#' + id).evaluate(element => element.open), false);
      const closed = await page.locator('#' + id).evaluate(element => element.getBoundingClientRect().height);
      assert(before - closed >= 40, id + ' collapse must free actual sidebar space');
      assert((await summary.boundingBox()).height >= 44);
      for (const other of sections.filter(value => value !== id)) assert(await page.locator('#' + other).evaluate(element => element.open), 'Sections collapse independently');
      assert.deepEqual(retained(await state(page)), original);
      await summary.focus(); await summary.press('Enter');
      assert(await page.locator('#' + id).evaluate(element => element.open), id + ' must reopen with the keyboard');
      assert.deepEqual(retained(await state(page)), original);
    }
    for (const language of ['en', 'ko', 'ja']) {
      await page.locator('#lang-select').selectOption(language);
      for (const viewport of [{ width: 320, height: 900 }, { width: 768, height: 640 }, { width: 853, height: 590 }, { width: 1024, height: 768 }, { width: 1280, height: 800 }]) {
        await page.setViewportSize(viewport); await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('.viewer-control-panel').scrollTop = 0; });
        const normal = await metrics(page); assertHud(normal);
        if (viewport.width >= 720) {
          assert(normal.stage.right <= normal.sidebar.x + 1, 'Tablet model and editor use separate columns');
          assert(normal.sidebar.width >= 280, 'Editor keeps usable controls beside the model');
          if (viewport.width < 1200) assert(normal.sidebar.width <= 380, 'Compact tablet editors stay bounded');
          else assert(normal.stage.width <= normal.stage.height * 1.27, 'Wide tablets use freed preview width for editing rather than empty canvas');
          assert(normal.breast.width <= 380 && normal.skirt.width <= 380);
          assert(normal.stage.height >= viewport.height * .55, 'Tablet model must use meaningful screen height');
        }
        const beforeCamera = (await state(page)).camera;
        await page.locator('#viewer-expand').click();
        const expanded = await metrics(page); assertHud(expanded);
        assert.equal(expanded.sidebarDisplayed, false, 'Expanded model mode gives the viewport to the model');
        assert(expanded.stage.height >= viewport.height * .88, 'Expanded mode must fill screen height');
        assert.deepEqual((await state(page)).camera, beforeCamera, 'A layout change must preserve the camera');
        assert.deepEqual(retained(await state(page)), original);
        await page.locator('#viewer-expand').click(); await frames(page);
        assert.deepEqual(retained(await state(page)), original);
        report.layouts.push({ language, viewport, normal, expanded });
      }
    }
    assert.deepEqual(errors, []); await context.close();
    for (const mode of ['browser', 'rejected', 'native']) {
      const { page, context, errors } = await openPage(browser, mode);
      const before = retained(await state(page));
      await page.locator('#viewer-fullscreen').click();
      await page.waitForFunction(mode => { const l = ModelViewer.getState().layout; return !l.fullscreenPending && (mode === 'rejected' ? l.expanded : l.fullscreen === mode); }, mode);
      if (mode === 'browser') assert(await page.evaluate(() => !!document.fullscreenElement), 'Use the real browser Fullscreen API');
      if (mode === 'rejected') {
        await page.locator('#viewer-info').evaluate(element => { element.open = true; });
        assert((await page.locator('#viewer-layout-status').innerText()).length > 0, 'Denied full screen has a discoverable fallback explanation');
        await page.locator('#viewer-info').evaluate(element => { element.open = false; });
      }
      assert.deepEqual(retained(await state(page)), before); assertHud(await metrics(page));
      await page.keyboard.press('Escape');
      await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'none' && !ModelViewer.getState().layout.expanded);
      assert.deepEqual(retained(await state(page)), before);
      await page.locator('#viewer-fullscreen').click();
      await page.waitForFunction(mode => !ModelViewer.getState().layout.fullscreenPending && (mode === 'rejected' || ModelViewer.getState().layout.fullscreen === mode), mode);
      await page.evaluate(() => document.querySelector('[data-tab="tools"]').click());
      await page.waitForFunction(() => !ModelViewer.getState().visible && ModelViewer.getState().layout.fullscreen === 'none' && !ModelViewer.getState().layout.expanded);
      assert.equal(await page.evaluate(() => !!document.fullscreenElement), false);
      assert.equal(await page.evaluate(() => document.body.classList.contains('viewer-is-expanded')), false);
      await page.locator('[data-tab="viewer"]').click(); await frames(page);
      assert.deepEqual(retained(await state(page)), before);
      await page.locator('#viewer-fullscreen').click(); await frames(page);
      await page.evaluate(() => ModelViewer.dispose());
      await page.waitForFunction(() => !document.fullscreenElement && !document.body.classList.contains('viewer-is-expanded'));
      assert.deepEqual(errors, []); report.lifecycles.push({ mode, final: (await state(page)).layout }); await context.close();
    }
    {
      const { page, context, errors } = await openPage(browser, 'native-held');
      await page.locator('#viewer-fullscreen').click();
      await page.waitForFunction(() => ModelViewer.getState().layout.fullscreenPending);
      await page.evaluate(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: false, settled: false } })));
      assert((await state(page)).layout.fullscreenPending, 'An unsolicited initial false is not a rejection of a later enter request');
      await page.evaluate(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: false, settled: true } })));
      await page.waitForFunction(() => !ModelViewer.getState().layout.fullscreenPending && !ModelViewer.getState().layout.expanded);
      await page.locator('#viewer-fullscreen').click();
      await page.waitForFunction(() => ModelViewer.getState().layout.fullscreenPending);
      await page.evaluate(() => document.querySelector('[data-tab="tools"]').click());
      await page.evaluate(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: true, settled: true } })));
      await frames(page);
      assert.equal((await state(page)).layout.expanded, false, 'A late native enter acknowledgement must not resurrect a hidden viewer');
      assert.equal(await page.evaluate(() => document.body.classList.contains('viewer-is-expanded')), false);
      await page.evaluate(() => dispatchEvent(new CustomEvent('elichika-native-fullscreen', { detail: { active: false, settled: true } })));
      await page.waitForFunction(() => !ModelViewer.getState().layout.fullscreenPending);
      assert.deepEqual(errors, []); report.lifecycles.push({ mode: 'native-held-initial-false-and-late-ack', messages: await page.evaluate(() => __nativeFullscreenMessages) });
      await context.close();
    }
    {
      const { page, context, errors } = await openPage(browser, 'touch');
      await page.locator('#viewer-info').evaluate(element => { element.open = true; });
      const panel = page.locator('.viewer-info-panel');
      const area = await panel.boundingBox();
      assert(await panel.evaluate(element => element.scrollHeight > element.clientHeight + 50), 'Long product information must actually overflow');
      const cdp = await context.newCDPSession(page);
      async function drag(x, y, dx, dy) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1, radiusX: 1, radiusY: 1, force: 1 }] });
        for (let step = 1; step <= 6; step++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + dx * step / 6, y: y + dy * step / 6, id: 1, radiusX: 1, radiusY: 1, force: 1 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      }
      const before = (await state(page)).camera;
      await drag(area.x + area.width / 2, area.y + area.height - 24, 0, -Math.min(120, area.height - 48));
      await page.waitForFunction(() => document.querySelector('.viewer-info-panel').scrollTop > 0);
      assert.deepEqual((await state(page)).camera, before, 'Swiping information scrolls the panel without rotating the model');
      const scroll = await panel.evaluate(element => element.scrollTop);
      await page.locator('#viewer-info').evaluate(element => { element.open = false; });
      const stage = await page.locator('#viewer-stage').boundingBox(), windowScroll = await page.evaluate(() => scrollY);
      await drag(stage.x + stage.width / 2, stage.y + stage.height / 2, 70, 0);
      await page.waitForFunction(position => ModelViewer.getState().camera.position.some((value, i) => Math.abs(value - position[i]) > .001), before.position);
      assert.equal(await page.evaluate(() => scrollY), windowScroll, 'Canvas touch rotation must not scroll the document');
      assert.equal((await page.evaluate(() => ModelViewer.renderProbe())).glError, 0);
      assert.deepEqual(errors, []); report.touch = { informationScrolled: scroll, canvasRotated: true, documentScrollPreserved: true };
      await context.close();
    }
    report.status = 'PASS'; fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, layouts: report.layouts.length, fullscreenModes: report.lifecycles.map(value => value.mode), evidence }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
