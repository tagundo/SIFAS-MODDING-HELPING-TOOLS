/* Real product DOM/WebGL regression for compact vertical controls and Fit.
 * All geometry, skin, morphs and motion are original generated test fixtures.
 * Run with VIEWER_URL pointing at the ordinary webtools server. */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { humanoidFixture } = require('./viewer_vertical_fixture');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-vertical-'));
fs.mkdirSync(evidence, { recursive: true });
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());
const profiles = [
  { width: 412, height: 915 }, { width: 448, height: 998 }, { width: 480, height: 1040 },
  { width: 915, height: 412 }, { width: 998, height: 448 },
  { width: 768, height: 900 }, { width: 900, height: 768 },
  { width: 360, height: 800 }, { width: 800, height: 320 }, { width: 800, height: 321 }
];

async function openPage(browser, fixtureOptions = {}, viewport = profiles[1], dpr = 1) {
  const model = humanoidFixture(fixtureOptions);
  const context = await browser.newContext({ viewport, deviceScaleFactor: dpr, hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
  // This transparent observer captures the actual scene/camera passed to the
  // product renderer. It changes no geometry, framing or rendering behavior.
  await page.route('**/static/viewer-quality.js', async route => {
    const response = await route.fetch();
    const body = await response.text();
    await route.fulfill({ response, body: body + `\n(() => {
      const create = ViewerQuality.create;
      ViewerQuality.create = function(renderer) {
        const controller = create.apply(this, arguments), render = controller.render;
        controller.render = function(scene, camera) {
          window.__verticalObserver = { renderer, scene, camera };
          return render.apply(this, arguments);
        }; return controller;
      };
    })();` });
  });
  await page.route('**/api/viewer/prepare', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ id: 'vertical-humanoid', url: '/api/viewer/model/vertical-humanoid.glb',
      warnings: [], stats: model.stats, rig: model.rig }) }));
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: model.glb }));
  await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
  await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerRig);
  await page.evaluate(paths => openModelViewer(paths), fixtureOptions.twoModels ? ['/original/left.unity', '/original/right.unity'] : ['/original/humanoid.unity']);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !!window.__verticalObserver);
  return { page, context, errors };
}

async function inspect(page) {
  await frames(page);
  return page.evaluate(() => {
    ModelViewer.renderProbe();
    const { scene, camera, renderer } = __verticalObserver, canvas = renderer.domElement;
    scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    const stage = rect(document.getElementById('viewer-stage')), cr = canvas.getBoundingClientRect();
    const selectors = ['#viewer-pose-basic', '#viewer-pose-preview', '.viewer-quality-choice', '#viewer-expand', '#viewer-fullscreen',
      '[data-viewer-view="front"]', '[data-viewer-view="back"]', '[data-viewer-view="left"]', '[data-viewer-view="right"]', '#viewer-fit', '#viewer-info > summary'];
    const controls = selectors.map(selector => {
      const element = document.querySelector(selector), r = rect(element), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return { selector, ...r, visible: !!element.getClientRects().length, hit: !!hit && (hit === element || element.contains(hit)),
        inDetails: !!element.closest('#viewer-view-menu-content'), coveredPixels: 0 };
    });
    const projected = { count: 0, outside: 0, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };
    scene.traverseVisible(child => {
      if (!child.isMesh || child.userData.viewerHelper || !child.geometry || !child.geometry.attributes.position) return;
      const positions = child.geometry.attributes.position, morphs = child.geometry.morphAttributes.position || [];
      for (let index = 0; index < positions.count; index++) {
        const original = new THREE.Vector3().fromBufferAttribute(positions, index), p = original.clone();
        morphs.forEach((morph, i) => {
          const influence = child.morphTargetInfluences && child.morphTargetInfluences[i] || 0;
          if (!influence) return;
          const delta = new THREE.Vector3().fromBufferAttribute(morph, index);
          if (!child.geometry.morphTargetsRelative) delta.sub(original);
          p.addScaledVector(delta, influence);
        });
        if (child.isSkinnedMesh) child.boneTransform(index, p);
        p.applyMatrix4(child.matrixWorld).project(camera);
        const x = (p.x + 1) / 2 * cr.width, y = (1 - p.y) / 2 * cr.height;
        projected.left = Math.min(projected.left, x); projected.right = Math.max(projected.right, x);
        projected.top = Math.min(projected.top, y); projected.bottom = Math.max(projected.bottom, y);
        projected.count++; if (Math.abs(p.x) > 1.00001 || Math.abs(p.y) > 1.00001 || Math.abs(p.z) > 1.00001) projected.outside++;
      }
    });
    const gl = renderer.getContext(), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, pixels = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    const bg = [pixels[0], pixels[1], pixels[2]], changed = (x, y) => {
      const index = ((h - y - 1) * w + x) * 4;
      return Math.abs(pixels[index] - bg[0]) + Math.abs(pixels[index + 1] - bg[1]) + Math.abs(pixels[index + 2] - bg[2]) > 35;
    };
    let top = h, bottom = -1, count = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (changed(x, y)) { top = Math.min(top, y); bottom = Math.max(bottom, y); count++; }
    for (const control of controls) {
      const x0 = Math.max(0, Math.floor((control.x - cr.x) / cr.width * w)), x1 = Math.min(w, Math.ceil((control.right - cr.x) / cr.width * w));
      const y0 = Math.max(0, Math.floor((control.y - cr.y) / cr.height * h)), y1 = Math.min(h, Math.ceil((control.bottom - cr.y) / cr.height * h));
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (changed(x, y)) control.coveredPixels++;
    }
    const pairs = [];
    controls.forEach((a, i) => controls.slice(i + 1).forEach(b => {
      if (Math.min(a.right, b.right) - Math.max(a.x, b.x) > .5 && Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > .5) pairs.push([a.selector, b.selector]);
    }));
    const s = ModelViewer.getState();
    return { viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio }, stage, projected, controls, overlapPairs: pairs,
      foregroundHeight: Math.max(0, bottom - top + 1) / h * cr.height, foregroundPixels: count,
      overflow: document.documentElement.scrollWidth > innerWidth + 1, glError: gl.getError(),
      layout: s.layout, framing: s.framing || null, camera: s.camera, rig: { clip: s.rig.selectedClip, time: s.rig.time, expressions: s.rig.expressions } };
  });
}

function assertFrame(value, label) {
  assert.equal(value.controls.length, 11);
  for (const control of value.controls) {
    assert(control.visible && control.hit && !control.inDetails, label + ': visible and reachable original action ' + JSON.stringify(control));
    assert(control.width >= 31.5 && control.height >= 31.5, label + ': actual compact target is at least32 CSS px ' + JSON.stringify(control));
    assert(control.x >= value.stage.x - 1 && control.right <= value.stage.right + 1 && control.y >= value.stage.y - 1 && control.bottom <= value.stage.bottom + 1,
      label + ': control inside canvas ' + JSON.stringify(control));
    assert.equal(control.coveredPixels, 0, label + ': model pixels must not be obscured by closed HUD ' + JSON.stringify(control));
  }
  assert.deepEqual(value.overlapPairs, [], label + ': distinct buttons cannot overlap');
  assert(value.projected.count > 500, 'Exercise a real dense humanoid, not just a three-vertex stand-in');
  assert.equal(value.projected.outside, 0, label + ': independent skin+morph vertex projection must stay inside the camera frustum');
  assert(value.foregroundPixels > 200 && value.foregroundHeight > 50, label + ': actual model pixels remain visible');
  assert.equal(value.overflow, false, label + ': no horizontal page overflow'); assert.equal(value.glError, 0);
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const report = { status: 'RUNNING', scope: 'Host Chromium real viewer/DOM/WebGL, generated humanoid with skin/morph/motion; not Android physical touch or timing', cases: [] };
  try {
    const { page, context, errors } = await openPage(browser);
    assert.equal(await page.locator('#viewer-fit').innerText(), '화면에 맞춤');
    for (const viewport of profiles) {
      await page.setViewportSize(viewport); await page.evaluate(() => scrollTo(0, 0)); await frames(page);
      for (const direction of ['front', 'back', 'left', 'right']) {
        await page.locator('[data-viewer-view="' + direction + '"]').click();
        const value = await inspect(page); assertFrame(value, JSON.stringify({ viewport, direction }));
        if (direction === 'front' && viewport.width === 448) {
          assert(value.foregroundHeight >= value.stage.height * .68, 'A standing model should use most available height');
          await page.screenshot({ path: path.join(evidence, 'vertical-phone.png'), fullPage: true });
        }
        report.cases.push({ phase: 'normal', viewport, direction, ...value });
      }
    }
    // The camera/pose survives reflow and a normal expanded round-trip. Fit is
    // explicit and is deliberately not part of this preservation assertion.
    await page.setViewportSize(profiles[1]); await frames(page);
    const before = await state(page);
    await page.setViewportSize(profiles[4]); await frames(page); assert.deepEqual((await state(page)).camera, before.camera);
    await page.setViewportSize(profiles[1]); await frames(page); assert.deepEqual((await state(page)).camera, before.camera);
    await page.locator('#viewer-expand').click(); await frames(page); assert.deepEqual((await state(page)).camera, before.camera);
    await page.locator('#viewer-fit').click(); const expanded = await inspect(page); assertFrame(expanded, 'expanded'); report.cases.push({ phase: 'expanded', ...expanded });
    const expandedCamera = (await state(page)).camera;
    await page.locator('#viewer-expand').click(); await frames(page); assert.deepEqual((await state(page)).camera, expandedCamera);
    await page.locator('#viewer-fit').click();
    await page.locator('#viewer-info > summary').click();
    report.info = await page.locator('.viewer-info-panel').evaluate(element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; });
    assert(report.info.x >= 0 && report.info.y >= 0 && report.info.right <= profiles[1].width + 1 && report.info.bottom <= profiles[1].height + 1);
    await page.locator('#viewer-info > summary').click();
    // Browser text size only; this is not a claim about an Android font-scale setting.
    await page.addStyleTag({ content: 'html { font-size: 200% !important; }' }); await frames(page);
    await page.locator('#viewer-fit').click(); const largeText = await inspect(page); assertFrame(largeText, '200% root font'); report.cases.push({ phase: '200%-root-font', ...largeText });
    assert.deepEqual(errors, []); await context.close();

    // A short phone with enlarged text cannot afford normal header/file rows.
    // The stable viewport/font guard must use the existing workspace drawer,
    // retaining every HUD action and every editing value while it changes.
    for (const language of ['en', 'ja', 'ko']) {
      const { page, context, errors } = await openPage(browser);
      await page.locator('#lang-select').selectOption(language);
      await page.waitForFunction(code => document.documentElement.lang === code, language);
      await page.locator('#viewer-breast-preset').selectOption('rin');
      await page.locator('#viewer-skirt-number').fill('.9'); await page.locator('#viewer-skirt-apply').click();
      await page.locator('[data-viewer-expression-group="eyes"]').click();
      await page.locator('[data-viewer-expression-preset="fixture-eyes-closed"]').click();
      await page.locator('#viewer-time').evaluate(element => { element.value = '.35'; element.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.evaluate(() => scrollTo(0, 0));
      const retained = () => page.evaluate(() => {
        const s = ModelViewer.getState(), r = s.rig;
        return { camera: s.camera, modelId: s.modelId, paths: s.loadedPaths, body: r.body,
          selectedClip: r.selectedClip, time: r.time, playing: r.playing,
          expressions: r.expressions, nodeAdjustments: r.nodeAdjustments,
          nodeCompensations: r.nodeCompensations, saved: r.savedNodes };
      });
      const before = await retained();
      const style = await page.addStyleTag({ content: 'html { font-size: 200% !important; }' });
      await page.setViewportSize({ width: 360, height: 456 });
      await page.waitForFunction(() => ModelViewer.getState().layout.shortHeight);
      await frames(page);
      assert.deepEqual(await retained(), before, language + ': entering enlarged-text workspace must not refit or reset edits');
      const stable = await page.evaluate(() => new Promise(resolve => {
        const observations = [];
        function sample() {
          const l = ModelViewer.getState().layout;
          observations.push({ shortHeight: l.shortHeight, width: l.stage.width, height: l.stage.height });
          if (observations.length === 12) resolve(observations); else requestAnimationFrame(sample);
        } requestAnimationFrame(sample);
      }));
      assert(stable.every(value => value.shortHeight), language + ': large-text workspace does not oscillate');
      assert.equal(new Set(stable.map(value => value.width + 'x' + value.height)).size, 1, language + ': stable canvas size across layout observer frames');
      await page.locator('#viewer-fit').click();
      const value = await inspect(page); assertFrame(value, language + ':360x456 at200% text');
      const fitted = await retained();
      await page.locator('#viewer-info > summary').click();
      const info = await page.locator('.viewer-info-panel').evaluate(element => {
        const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
      });
      assert(info.width > 0 && info.height > 0 && info.x >= 0 && info.y >= 0 && info.right <= 361 && info.bottom <= 457,
        language + ': information popup remains naturally bounded by the actual screen');
      for (const button of value.controls) assert(!(Math.min(info.right, button.right) - Math.max(info.x, button.x) > .5 &&
        Math.min(info.bottom, button.bottom) - Math.max(info.y, button.y) > .5), language + ': information leaves HUD action reachable: ' + button.selector);
      await page.keyboard.press('Escape');
      await page.locator('#viewer-workspace-menu > summary').click();
      const workspaceTargets = [];
      for (const selector of ['.tab[data-tab="tools"]', '.tab[data-tab="viewer"]', '#lang-select',
        '#viewer-add', '#viewer-add-motion', '#viewer-load', '#viewer-file-options > summary']) {
        const control = page.locator(selector); await control.scrollIntoViewIfNeeded(); await frames(page);
        const target = await control.evaluate(element => {
          const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
            hit: !!hit && (hit === element || element.contains(hit)) };
        });
        assert(target.width >= 43.5 && target.height >= 43.5 && target.hit && target.x >= 0 && target.y >= 0 && target.right <= 361 && target.bottom <= 457,
          language + ': original drawer navigation/file action stays a reachable44px target: ' + JSON.stringify({ selector, ...target }));
        workspaceTargets.push({ selector, ...target });
      }
      await page.keyboard.press('Escape'); await frames(page);
      assert.deepEqual(await retained(), fitted, language + ': drawer scrolling and popups retain model/camera/pose/edits');
      await style.evaluate(element => { element.disabled = true; });
      await page.waitForFunction(() => !ModelViewer.getState().layout.shortHeight); await frames(page);
      assert.deepEqual(await retained(), fitted, language + ': restoring normal text does not auto-fit');
      await style.evaluate(element => { element.disabled = false; });
      await page.waitForFunction(() => ModelViewer.getState().layout.shortHeight); await frames(page);
      assert.deepEqual(await retained(), fitted, language + ': enlarged-text workspace re-entry does not reset the camera or edits');
      await page.locator('#viewer-fit').click(); const restored = await inspect(page); assertFrame(restored, language + ': enlarged-text re-entry');
      report.cases.push({ phase: 'short-phone-200%-root-font', language, stable, info, workspaceTargets, ...restored });
      assert.deepEqual(errors, []); await context.close();
    }

    for (const options of [{ wide: true }, { twoModels: true }, { shifted: true }, { wide: true, twoModels: true }]) {
      const { page, context, errors } = await openPage(browser, options, options.wide && options.twoModels ? profiles[4] : profiles[1], 3);
      await page.locator('#viewer-motion').selectOption('Original humanoid preview');
      await page.locator('#viewer-time').evaluate(element => { element.value = '.55'; element.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.locator('[data-viewer-expression-group="eyes"]').click();
      await page.locator('[data-viewer-expression-preset="fixture-eyes-closed"]').click();
      assert((await state(page)).rig.expressions.some(expression => expression.weight > .99), 'Use an actually enabled authored morph for the independent vertex projection');
      await page.evaluate(() => scrollTo(0, 0));
      for (const direction of ['front', 'back', 'left', 'right']) {
        await page.locator('[data-viewer-view="' + direction + '"]').click();
        const value = await inspect(page); assertFrame(value, JSON.stringify({ options, direction }));
        report.cases.push({ phase: 'posed-morphed', options, direction, ...value });
      }
      assert.deepEqual(errors, []); await context.close();
    }
    report.status = 'PASS'; fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
