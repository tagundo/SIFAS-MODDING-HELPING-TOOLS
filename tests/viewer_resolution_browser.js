/* Short-window and Fold portrait regression: generated geometry only, actual
 * product WebGL/DOM/browser fullscreen. Actual character/API matrix is separate.
 * VIEWER_URL points to a local WebUI. No Android/native fullscreen claim. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-resolution-'));
fs.mkdirSync(evidence, { recursive: true });
const made = fixture({ skirtSet: true, semanticExpressions: true, previewName: 'Original generated preview', previewVerified: true });
const profiles = [
  { id: 'cover-default-landscape', width: 840, height: 195, dpr: 3, short: true },
  { id: 'cover-bracket-landscape', width: 960, height: 246, dpr: 2.625, short: true },
  { id: 'short-narrow-workspace', width: 640, height: 246, dpr: 2, short: true, narrow: true },
  { id: 'fold-default-portrait', width: 752, height: 669, dpr: 3, fold: true },
  { id: 'old-short-phone', width: 360, height: 456, dpr: 2 },
  { id: 'wide-tablet', width: 1480, height: 788, dpr: 2 },
  { id: 'tall-wide-boundary', width: 1200, height: 1000, dpr: 2 }
];
const temporaryPickerFiles = new Set();
let pickerFixture = null;
const lifecycleOnly = process.env.VIEWER_RESOLUTION_LIFECYCLE_ONLY === '1';
const pickerRaceOnly = process.env.VIEWER_PICKER_RACE_ONLY === '1';
const popoverBoundsOnly = process.env.VIEWER_POPOVER_BOUNDS_ONLY === '1';
assert([lifecycleOnly, pickerRaceOnly, popoverBoundsOnly].filter(Boolean).length <= 1, 'Select one diagnostic mode at a time');
const report = { status: 'RUNNING', runMode: popoverBoundsOnly ? 'POPOVER_BOUNDS_ONLY_DIAGNOSTIC' : pickerRaceOnly ? 'PICKER_RACE_ONLY_DIAGNOSTIC' : lifecycleOnly ? 'LIFECYCLE_ONLY_DIAGNOSTIC' : 'FULL_SEVEN_PROFILES_LIFECYCLE_AND_PICKER_RACES', scope: 'Generated skinned GLB through actual product viewer; strict visible target intersections and actual WebGL pixels; host/browser only', profiles: [], lifecycle: [] };
const save = () => fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
const state = page => page.evaluate(() => ModelViewer.getState());
const retained = s => ({ modelId: s.modelId, loadedPaths: s.loadedPaths, camera: s.camera, qualityEnabled: s.quality.enabled,
  rig: { body: s.rig.body, selectedClip: s.rig.selectedClip, time: s.rig.time, playing: s.rig.playing, nodeAdjustments: s.rig.nodeAdjustments,
    nodeCompensations: s.rig.nodeCompensations, expressions: s.rig.expressions, skirtValues: s.rig.skirtValues,
    savedEnabled: s.rig.savedNodes.enabled, groups: s.rig.savedNodes.groups.map(({ id, enabled, nodes, settings }) => ({ id, enabled, nodes, settings })) } });
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function settle(page) {
  await page.evaluate(() => { window.__resolutionLastCamera = ''; window.__resolutionStableFrames = 0; });
  await page.waitForFunction(() => {
    const s = ModelViewer.getState();
    if (!s.loaded || s.loading || !s.quality || !s.quality.ready) return false;
    const camera = JSON.stringify(s.camera);
    window.__resolutionStableFrames = camera === window.__resolutionLastCamera ? window.__resolutionStableFrames + 1 : 0;
    window.__resolutionLastCamera = camera;
    return window.__resolutionStableFrames >= 3;
  });
  await frames(page);
}
async function closeMenus(page) {
  await page.evaluate(() => ['viewer-view-menu', 'viewer-info', 'viewer-workspace-menu', 'viewer-file-options'].forEach(id => {
    const n = document.getElementById(id); if (n) n.open = false;
  }));
  await frames(page);
}
async function openDetails(page, id) {
  const details = page.locator('#' + id);
  assert(await details.locator('summary').first().isVisible(), id + ' summary must be visible');
  if (!(await details.evaluate(n => n.open))) await details.locator('summary').first().click();
  await frames(page);
}
async function target(page, selector, popup) {
  return page.evaluate(async ({ selector, popup }) => {
    const n = document.querySelector(selector); if (!n) return { selector, missing: true };
    const e = n.matches('input[type=checkbox]') ? n.closest('label') : n;
    const panel = popup && document.querySelector(popup);
    const scrollBefore = { pageX: scrollX, pageY: scrollY, popup: panel ? panel.scrollTop : null };
    const popupScrolls = [];
    if (panel) {
      // Nested Model options uses an overflow-visible inner panel. Scroll only
      // real user-scrollable ancestors, never the page or a hidden clip box.
      for (let parent = e.parentElement; parent && parent !== document.body && parent !== document.documentElement; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (!/^(auto|scroll)$/.test(style.overflowY) || parent.scrollHeight <= parent.clientHeight) continue;
        const before = parent.scrollTop, r = e.getBoundingClientRect(), p = parent.getBoundingClientRect();
        const top = Math.max(0, p.top), bottom = Math.min(innerHeight, p.bottom);
        if (r.bottom > bottom - 3) parent.scrollTop += r.bottom - bottom + 3;
        const moved = e.getBoundingClientRect(); if (moved.top < top + 3) parent.scrollTop -= top - moved.top + 3;
        popupScrolls.push({ id: parent.id, className: parent.className, overflowY: style.overflowY, before, after: parent.scrollTop });
      }
    }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const r = e.getBoundingClientRect();
    let left = Math.max(0, r.left), top = Math.max(0, r.top), right = Math.min(innerWidth, r.right), bottom = Math.min(innerHeight, r.bottom);
    for (const p of [e.closest('#viewer-stage'), panel, e.closest('#viewer-workspace-menu-content'), e.closest('.viewer-file-options-panel'), e.closest('.modal-box')]) if (p) {
      const c = p.getBoundingClientRect(); left = Math.max(left, c.left); top = Math.max(top, c.top); right = Math.min(right, c.right); bottom = Math.min(bottom, c.bottom);
    }
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    const vertical = document.getElementById('tab-viewer').classList.contains('viewer-vertical-controls');
    const inPopup = !!e.closest('.viewer-workspace-menu-content,.viewer-view-menu-content,.viewer-file-options-panel,.viewer-info-panel,.modal-box');
    const compactSurface = !!e.closest('.viewer-stage-tools,.viewer-files,body.viewer-active-page > header');
    const minimumTarget = vertical && compactSurface && !inPopup ? 32 : 44;
    return { selector, width: r.width, height: r.height, visibleWidth: Math.max(0, right - left), visibleHeight: Math.max(0, bottom - top),
      minimumTarget, inPopup,
      x: r.x, y: r.y, right: r.right, bottom: r.bottom, hit: !!hit && (hit === e || e.contains(hit)), disabled: !!n.disabled,
      popupScrolls, scrollBefore, scrollAfter: { pageX: scrollX, pageY: scrollY, popup: panel ? panel.scrollTop : null },
      hitElement: hit ? hit.tagName + '#' + hit.id : null,
      hitStack: document.elementsFromPoint(r.x + r.width / 2, r.y + r.height / 2).slice(0, 6).map(item => ({ tag: item.tagName, id: item.id, className: item.className, text: item.textContent.trim().slice(0, 80) })) };
  }, { selector, popup });
}
function assertTarget(c, message) {
  const minimum = (c.minimumTarget || 44) - .5;
  assert(!c.missing && c.width >= minimum && c.height >= minimum && c.visibleWidth >= c.width - .5 && c.visibleHeight >= c.height - .5 && c.hit,
    message + ': ' + JSON.stringify(c));
  assert.equal(c.scrollBefore.pageX, c.scrollAfter.pageX, 'HUD reachability must not rely on scrolling the page');
  assert.equal(c.scrollBefore.pageY, c.scrollAfter.pageY, 'HUD reachability must not rely on scrolling the model off screen');
}
async function viewportMetrics(page) {
  return page.evaluate(() => {
    const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    const s = ModelViewer.getState(), probe = ModelViewer.renderProbe(33), canvas = document.getElementById('viewer-canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl'), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const pixels = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    const bg = [pixels[0], pixels[1], pixels[2]]; let minY = h, maxY = -1, count = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (Math.abs(pixels[i] - bg[0]) + Math.abs(pixels[i + 1] - bg[1]) + Math.abs(pixels[i + 2] - bg[2]) > 24) { minY = Math.min(minY, y); maxY = Math.max(maxY, y); count++; }
    }
    return { viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio }, stage: rect('#viewer-stage'), inspector: rect('.viewer-control-panel'),
      files: rect('.viewer-files'), overflow: document.documentElement.scrollWidth - innerWidth,
      layout: s.layout, sourceTriangles: s.sourceTriangles, pixelCount: count,
      foregroundHeight: count ? (maxY - minY + 1) / h * canvas.getBoundingClientRect().height : 0,
      glError: gl.getError(), probe };
  });
}
async function capture(page, cdp, name) {
  await settle(page);
  const before = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio }));
  const shot = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
  const buffer = Buffer.from(shot.data, 'base64'), width = buffer.readUInt32BE(16), height = buffer.readUInt32BE(20);
  const after = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio }));
  const proof = { name, pngWidth: width, pngHeight: height, viewport: before, after };
  fs.writeFileSync(path.join(evidence, name), buffer);
  fs.writeFileSync(path.join(evidence, name + '.json'), JSON.stringify(proof, null, 2));
  assert.deepEqual(after, before, 'Screenshot must retain the actual viewport and DPR');
  assert(Math.abs(width - before.width * before.dpr) <= 2 && Math.abs(height - before.height * before.dpr) <= 2, 'PNG must match actual viewport/DPR: ' + JSON.stringify(proof));
  return proof;
}
async function setViewport(page, cdp, viewport, dpr) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: viewport.width, height: viewport.height, deviceScaleFactor: dpr, mobile: true, screenWidth: viewport.width, screenHeight: viewport.height, screenOrientation: { type: viewport.width > viewport.height ? 'landscapePrimary' : 'portraitPrimary', angle: viewport.width > viewport.height ? 90 : 0 } });
  await settle(page);
}
async function setup(browser, profile) {
  const context = await browser.newContext({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: profile.dpr, hasTouch: true, isMobile: true });
  const page = await context.newPage(), cdp = await context.newCDPSession(page), errors = [], requests = [];
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
  await page.route('**/api/viewer/prepare', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'resolution-generated', url: '/api/viewer/model/resolution-generated.glb', warnings: [],
      stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 0 }, rig: made.rig }) });
  });
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: made.glb }));
  await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
  await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerRig);
  await page.evaluate(() => {
    window.__resolutionIdentity = { header: document.querySelector('body > header'), files: document.querySelector('.viewer-files'),
      add: document.getElementById('viewer-add'), motion: document.getElementById('viewer-add-motion'), load: document.getElementById('viewer-load'),
      camera: document.querySelector('.viewer-camera-actions'), info: document.getElementById('viewer-info'), inspector: document.querySelector('.viewer-control-panel') };
  });
  await page.evaluate(() => openModelViewer(['/original/generated-resolution.unity'])); await settle(page);
  // An authored .85 source and an explicit manual absolute endpoint must survive
  // layout reparenting. These are actual existing user inputs, not state mocks.
  await page.locator('#viewer-skirt-number').fill('.85'); await page.locator('#viewer-skirt-apply').click();
  await page.locator('#viewer-node-editor').evaluate(n => { n.open = true; });
  await page.locator('#viewer-node').selectOption('3');
  await page.locator('[data-viewer-node-kind="position"][data-axis="X"]').fill('.2');
  await page.locator('#viewer-motion').selectOption('Original generated preview');
  await page.locator('#viewer-time').evaluate(n => { n.value = '.37'; n.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.locator('#viewer-node-editor').evaluate(n => { n.open = false; });
  await page.locator('#viewer-high-quality').check(); await settle(page);
  const edited = await state(page);
  assert.equal(edited.rig.skirtValues.fileUniform, .85, 'File-local skirt .85 stays distinct from current editing');
  assert.equal(edited.rig.skirtValues.currentUniform, .85);
  assert.equal(edited.rig.nodeAdjustments['3'].position[0], -.2, 'Position X stores the actual mirrored glTF endpoint');
  await setViewport(page, cdp, { width: profile.width, height: profile.height }, profile.dpr);
  await page.evaluate(() => { document.querySelector('.viewer-control-panel').scrollTop = 0; scrollTo(0, 0); }); await settle(page);
  if (!(await page.locator('#viewer-fit').isVisible())) await openDetails(page, 'viewer-view-menu');
  await page.locator('#viewer-fit').click(); await closeMenus(page); await settle(page);
  return { context, page, cdp, errors, requests };
}
async function popoverObservation(page, opened, context) {
  const geometry = await page.evaluate(() => {
    const rect = selector => { const n = document.querySelector(selector); if (!n) return null; const r = n.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom, scrollHeight: n.scrollHeight, clientHeight: n.clientHeight, overflowY: getComputedStyle(n).overflowY, display: getComputedStyle(n).display }; };
    const layout = ModelViewer.getState().layout, stage = rect('#viewer-stage'), topHud = rect('#viewer-stage-tools-top'), bottomHud = rect('#viewer-stage-tools-bottom');
    const topInset = topHud.display !== 'none' && topHud.height ? Math.max(0, topHud.bottom - stage.y) : 0;
    const bottomInset = bottomHud.display !== 'none' && bottomHud.height ? Math.max(0, stage.bottom - bottomHud.y) : 0;
    return { locale: document.documentElement.lang, viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
      stage, topHud, bottomHud,
      info: { open: document.getElementById('viewer-info').open, panel: rect('.viewer-info-panel') },
      view: { open: document.getElementById('viewer-view-menu').open, panel: rect('#viewer-view-menu-content') },
      measuredInsets: layout.safeInsets, actualHudInsets: { top: topInset, bottom: bottomInset },
      visibleCanvas: { top: Math.max(0, stage.y), bottom: Math.min(innerHeight, stage.bottom),
        left: Math.max(0, stage.x), right: Math.min(innerWidth, stage.right) } };
  });
  const observation = { opened, context, ...geometry, oppositeControls: [] };
  if (!report.popoverObservations) report.popoverObservations = [];
  report.popoverObservations.push(observation); save(); return observation;
}
async function assertOppositeHud(page, opened, context, capturePopup) {
  const observation = await popoverObservation(page, opened, context);
  // With visible side columns, each individual control must remain reachable;
  // the empty middle of a HUD bounding box is no longer a reserved edge strip.
  const selectors = ['#viewer-view-menu > summary', '#viewer-workspace-menu > summary',
    '#viewer-pose-basic', '#viewer-pose-preview', '#viewer-high-quality', '#viewer-expand', '#viewer-fullscreen',
    '#viewer-info > summary', '[data-viewer-view="front"]', '[data-viewer-view="back"]',
    '[data-viewer-view="left"]', '[data-viewer-view="right"]', '#viewer-fit'];
  for (const selector of selectors) {
    const locator = page.locator(selector); if (!(await locator.count()) || !(await locator.isVisible())) continue;
    const control = await target(page, selector); observation.oppositeControls.push(control); save();
    assertTarget(control, opened + ' open must leave every visible HUD action fully visible and hittable at its explicit size policy; ' + JSON.stringify({ context, locale: observation.locale, viewport: observation.viewport,
      stage: observation.stage, topHud: observation.topHud, bottomHud: observation.bottomHud, info: observation.info, view: observation.view, visibleCanvas: observation.visibleCanvas }));
  }
  const panel = opened === 'info' ? observation.info.panel : observation.view.panel;
  const bounds = observation.visibleCanvas;
  assert(panel.y >= bounds.top - 1 && panel.bottom <= bounds.bottom + 1 && panel.x >= bounds.left - 1 && panel.right <= bounds.right + 1 && panel.height > 0 && panel.width > 0,
    'The natural ' + opened + ' popup must remain inside the actually visible canvas; ' + JSON.stringify(observation));
  for (const control of observation.oppositeControls) {
    const overlapX = Math.min(panel.right, control.right) - Math.max(panel.x, control.x);
    const overlapY = Math.min(panel.bottom, control.bottom) - Math.max(panel.y, control.y);
    assert(overlapX <= .5 || overlapY <= .5, 'A popup must not cover any visible side-column action: ' + JSON.stringify({ opened, panel, control, context }));
  }
  if (capturePopup) { observation.image = await capturePopup(opened); save(); }
  return observation;
}
async function assertHud(page, short, context = {}, capturePopup) {
  const controls = [];
  await closeMenus(page);
  for (const selector of ['#viewer-expand', '#viewer-fullscreen', '#viewer-info > summary']) { const c = await target(page, selector); assertTarget(c, selector + ' ' + JSON.stringify(context)); controls.push(c); }
  const hasViewMenu = await page.locator('#viewer-view-menu > summary').isVisible();
  if (hasViewMenu) { const c = await target(page, '#viewer-view-menu > summary'); assertTarget(c, c.selector + ' ' + JSON.stringify(context)); controls.push(c); await openDetails(page, 'viewer-view-menu'); }
  for (const selector of ['#viewer-pose-basic', '#viewer-pose-preview', '#viewer-high-quality']) {
    const c = await target(page, selector); assertTarget(c, selector + ' ' + JSON.stringify(context)); controls.push(c);
  }
  const viewObservation = hasViewMenu ? await assertOppositeHud(page, 'view', context, capturePopup) : null;
  for (const selector of ['[data-viewer-view="front"]', '[data-viewer-view="back"]', '[data-viewer-view="left"]', '[data-viewer-view="right"]', '#viewer-fit']) {
    const c = await target(page, selector); assertTarget(c, selector + ' ' + JSON.stringify(context)); controls.push(c);
  }
  await closeMenus(page);
  await page.locator('#viewer-info > summary').click(); await frames(page);
  const infoObservation = await assertOppositeHud(page, 'info', context, capturePopup);
  const info = await page.locator('.viewer-info-panel').evaluate(n => {
    const p = n.getBoundingClientRect(), s = document.getElementById('viewer-stage').getBoundingClientRect();
    return { top: p.top, bottom: p.bottom, left: p.left, right: p.right, height: p.height, scrollHeight: n.scrollHeight,
      stageTop: s.top, stageBottom: s.bottom, viewportHeight: innerHeight, viewportWidth: innerWidth };
  });
  assert(info.top >= Math.max(0, info.stageTop) - 1 && info.bottom <= Math.min(info.viewportHeight, info.stageBottom) + 1,
    'Info and actual status text must fit inside the visible model viewport: ' + JSON.stringify({ context, info }));
  if (hasViewMenu) {
    await openDetails(page, 'viewer-view-menu'); assert.equal(await page.locator('#viewer-info').evaluate(n => n.open), false);
    await assertOppositeHud(page, 'view', context);
    await page.locator('#viewer-info > summary').click(); await frames(page); assert.equal(await page.locator('#viewer-view-menu').evaluate(n => n.open), false);
  }
  await closeMenus(page);
  return { controls, info, viewObservation, infoObservation, mutualExclusion: hasViewMenu ? 'exercised' : 'not-applicable' };
}
async function popoverBoundsRegressions(browser) {
  const cases = []; report.popoverBounds = { scope: 'Natural translated product Info/View content with the unchanged original generated neutral rig; no fabricated warnings or actual-character/model claim', cases };
  for (const profile of [{ id: 'phone-360x400', width: 360, height: 400, dpr: 2 }, { id: 'phone-320x400', width: 320, height: 400, dpr: 2 }, { id: 'legacy-phone-360x456', width: 360, height: 456, dpr: 2 }]) {
    const { page, context, cdp, errors } = await setup(browser, profile);
    try {
      for (const locale of ['ko', 'en', 'ja']) {
        await page.locator('#lang-select').selectOption(locale); await page.waitForFunction(language => document.documentElement.lang === language, locale); await settle(page);
        for (const mode of ['normal', 'expanded']) {
          const test = { profile, locale, mode, naturalProductHelp: true }; cases.push(test); save();
          try {
            if (mode === 'expanded') { await page.locator('#viewer-expand').click(); await settle(page); }
            const before = retained(await state(page)); test.geometry = await viewportMetrics(page);
            const label = profile.id + '-' + locale + '-' + mode;
            test.hud = await assertHud(page, false, { profile: profile.id, viewport: profile, locale, mode }, kind => capture(page, cdp, label + '-' + kind + '-open.png'));
            assert.deepEqual(retained(await state(page)), before, 'Opening natural popovers and real mutual-exclusion clicks retain camera, pose, HQ and source edits');
            test.status = 'PASS'; save();
            if (mode === 'expanded') { await page.locator('#viewer-expand').click(); await settle(page); }
          } catch (error) {
            test.error = { message: String(error), stack: error.stack };
            test.failureSnapshot = await popoverObservation(page, 'failure-state', { profile: profile.id, locale, mode });
            try { test.failureImage = await capture(page, cdp, profile.id + '-' + locale + '-' + mode + '-failure.png'); } catch (captureError) { test.captureError = String(captureError); }
            save(); throw error;
          }
        }
      }
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  }
  assert.equal(cases.length, 18); assert(cases.every(test => test.status === 'PASS')); report.popoverBounds.status = 'PASS'; save(); return cases;
}
async function pickerState(page) {
  return page.locator('#picker').evaluate(n => {
    const blocked = []; for (let p = n; p; p = p.parentElement) if (p.getAttribute('aria-hidden') === 'true' || p.inert) blocked.push({ id: p.id, tag: p.tagName, ariaHidden: p.getAttribute('aria-hidden'), inert: !!p.inert });
    const c = document.getElementById('picker-cancel'), r = c.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    const active = document.activeElement, a = active.getBoundingClientRect(), activeHit = document.elementFromPoint(a.x + a.width / 2, a.y + a.height / 2);
    return { blocked, hidden: n.classList.contains('hidden'), ariaHidden: n.getAttribute('aria-hidden'), inert: !!n.inert,
      cancel: { width: r.width, height: r.height, x: r.x, y: r.y, right: r.right, bottom: r.bottom, hit: !!hit && (hit === c || c.contains(hit)) },
      activeInsidePicker: n.contains(active), active: { id: active.id, tag: active.tagName, inWorkspace: !!active.closest('#viewer-workspace-menu'), inViewer: !!active.closest('#tab-viewer'), visible: a.width > 0 && a.height > 0 && a.x >= 0 && a.y >= 0 && a.right <= innerWidth + 1 && a.bottom <= innerHeight + 1 && !!activeHit && (activeHit === active || active.contains(activeHit)) },
      parent: n.parentElement.id || n.parentElement.tagName, browserFullscreen: !!document.fullscreenElement, viewport: { width: innerWidth, height: innerHeight } };
  });
}
async function ensurePickerFixture(page) {
  if (pickerFixture) return pickerFixture;
  const tools = await (await page.request.get((process.env.VIEWER_URL || 'http://127.0.0.1:8898') + '/api/tools')).json();
  assert(tools.roots && typeof tools.roots.models === 'string', 'The real jailed models root is required for picker callback coverage');
  fs.mkdirSync(tools.roots.models, { recursive: true });
  const name = 'viewer-resolution-neutral-' + process.pid + '.unity', file = path.join(tools.roots.models, name);
  assert(!fs.existsSync(file), 'Use a new temporary original fixture name');
  fs.copyFileSync(path.join(__dirname, 'fixtures', 'viewer_textured_triangle.unity'), file); temporaryPickerFiles.add(file);
  pickerFixture = { name, file }; return pickerFixture;
}
async function workspace(page, mode = 'normal', selectRealFixture = false) {
  const controls = [], pickerProofs = [];
  await openDetails(page, 'viewer-workspace-menu');
  assert(await page.evaluate(() => document.getElementById('viewer-workspace-menu-content').contains(__resolutionIdentity.header)));
  assert(await page.evaluate(() => document.getElementById('viewer-workspace-menu-content').contains(__resolutionIdentity.files)));
  for (const selector of ['#viewer-add', '#viewer-add-motion', '#viewer-load', '.tab[data-tab="tools"]', '.tab[data-tab="viewer"]', '.tab[data-tab="gallery"]', '#lang-select']) {
    const c = await target(page, selector, '#viewer-workspace-menu-content'); assertTarget(c, selector); controls.push(c);
  }
  for (const id of ['viewer-add', 'viewer-add-motion']) {
    await target(page, '#' + id, '#viewer-workspace-menu-content'); const originalPicker = await pickerState(page), layoutBeforePicker = (await state(page)).layout;
    await page.locator('#' + id).click();
    const immediate = await pickerState(page); assert(immediate.activeInsidePicker, mode + ' chooser immediately owns focus: ' + JSON.stringify(immediate));
    await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
    const picker = await pickerState(page);
    assert.deepEqual(picker.blocked, [], mode + ' chooser must not remain aria-hidden/inert behind fullscreen focus isolation: ' + JSON.stringify(picker));
    assert(picker.cancel.hit && picker.cancel.x >= 0 && picker.cancel.y >= 0 && picker.cancel.right <= picker.viewport.width + 1 && picker.cancel.bottom <= picker.viewport.height + 1, mode + ' chooser Cancel must be visible and hittable: ' + JSON.stringify(picker));
    const cancelMethod = id === 'viewer-add-motion' ? 'Escape' : 'Cancel button';
    if (cancelMethod === 'Escape') await page.keyboard.press('Escape'); else await page.locator('#picker-cancel').click();
    await page.waitForFunction(() => document.getElementById('picker').classList.contains('hidden')); await frames(page);
    const layoutAfterPicker = (await state(page)).layout; assert.equal(layoutAfterPicker.expanded, layoutBeforePicker.expanded); assert.equal(layoutAfterPicker.fullscreen, layoutBeforePicker.fullscreen, 'One picker Escape must not exit fullscreen');
    const restored = await pickerState(page);
    assert.equal(restored.parent, originalPicker.parent, 'Cancel restores the original picker DOM parent');
    assert.equal(restored.ariaHidden, originalPicker.ariaHidden); assert.equal(restored.inert, originalPicker.inert);
    assert(restored.active.inWorkspace && restored.active.visible, 'Cancel restores focus to a visible Workspace control: ' + JSON.stringify(restored));
    pickerProofs.push({ trigger: id, mode, immediate, picker, originalPicker, restored, cancelMethod, cancelWorked: true }); await openDetails(page, 'viewer-workspace-menu');
  }
  let callback = null;
  if (selectRealFixture) {
    const fixtureFile = await ensurePickerFixture(page), before = retained(await state(page));
    await target(page, '#viewer-add', '#viewer-workspace-menu-content'); await page.locator('#viewer-add').click();
    await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
    const row = page.locator('#picker-entries > li').filter({ hasText: fixtureFile.name }); await row.waitFor();
    await row.evaluate(n => { n.setAttribute('data-resolution-original-fixture', 'true'); });
    const hit = await target(page, '[data-resolution-original-fixture]', '#picker-entries'); assertTarget(hit, 'The actual neutral Unity file entry is selectable');
    await row.click(); await page.waitForFunction(file => ModelViewer.getState().paths.includes(file), fixtureFile.file); await frames(page);
    assert.deepEqual(retained(await state(page)), before, 'Choosing a companion only changes the pending path list; it must not reload or alter the actual model');
    await openDetails(page, 'viewer-workspace-menu');
    const optionsHit = await target(page, '#viewer-file-options > summary', '#viewer-workspace-menu-content'); assertTarget(optionsHit, 'Model options remains accessible after choosing a file');
    await openDetails(page, 'viewer-file-options');
    const remove = page.locator('#viewer-file-list > li').filter({ hasText: fixtureFile.name }).locator('.viewer-remove');
    await remove.evaluate(n => { n.setAttribute('data-resolution-remove-fixture', 'true'); });
    const removeHit = await target(page, '[data-resolution-remove-fixture]', '.viewer-file-options-panel'); assertTarget(removeHit, 'The selected companion has a real reachable Remove control');
    await remove.click(); await page.waitForFunction(file => !ModelViewer.getState().paths.includes(file), fixtureFile.file); await frames(page);
    assert.deepEqual(retained(await state(page)), before, 'Removing the pending companion preserves the loaded model and absolute edits');
    callback = { originalGeneratedUnityFixture: fixtureFile.name, realRoot: path.dirname(fixtureFile.file), selectedViaRealEntry: true, entryHit: hit, removeHit, loadedModelAndRigRetained: true };
  }
  await closeMenus(page);
  return { controls, originalHeaderAndFileNodes: true, fileAndMotionPickerListeners: true, pickerProofs, callback };
}
async function pickerOpenAcrossViewportChange(page, cdp, dpr) {
  const baseline = retained(await state(page)), cases = []; report.openPickerResize = cases;
  await page.locator('#viewer-expand').click(); await settle(page);
  for (const input of [{ trigger: 'viewer-add', close: 'Cancel button' }, { trigger: 'viewer-add-motion', close: 'Escape' }]) {
    await setViewport(page, cdp, { width: 840, height: 195 }, dpr); await openDetails(page, 'viewer-workspace-menu');
    const hit = await target(page, '#' + input.trigger, '#viewer-workspace-menu-content'); assertTarget(hit, input.trigger + ' before open-picker resize');
    const originalPicker = await pickerState(page), test = { ...input, originalPicker }; cases.push(test); save();
    await page.locator('#' + input.trigger).click(); test.immediate = await pickerState(page); save();
    assert(test.immediate.activeInsidePicker && !test.immediate.hidden && !test.immediate.blocked.length, 'The opened picker immediately owns usable focus before resize');
    await setViewport(page, cdp, { width: 1024, height: 768 }, dpr);
    test.beforeClose = await pickerState(page); test.layoutBeforeClose = (await state(page)).layout; save();
    assert.equal(test.layoutBeforeClose.shortHeight, false); assert.equal(test.layoutBeforeClose.expanded, true);
    assert(test.beforeClose.activeInsidePicker && !test.beforeClose.hidden && !test.beforeClose.blocked.length && test.beforeClose.cancel.hit,
      'An open chooser remains usable and focused after switching to a tall expanded viewport: ' + JSON.stringify(test.beforeClose));
    if (input.close === 'Escape') await page.keyboard.press('Escape'); else await page.locator('#picker-cancel').click();
    await page.waitForFunction(() => document.getElementById('picker').classList.contains('hidden')); await frames(page);
    test.restored = await pickerState(page); test.layoutAfterClose = (await state(page)).layout; save();
    assert.equal(test.restored.parent, originalPicker.parent, 'Viewport-changing Cancel restores the original picker parent');
    assert.equal(test.restored.ariaHidden, originalPicker.ariaHidden); assert.equal(test.restored.inert, originalPicker.inert);
    assert.equal(test.layoutAfterClose.expanded, true); assert.equal(test.layoutAfterClose.fullscreen, 'none');
    assert(test.restored.active.inViewer && test.restored.active.visible,
      'Closing a resized expanded chooser must focus a visible active viewer control, not a hidden old File button: ' + JSON.stringify(test.restored));
    assert.deepEqual(retained(await state(page)), baseline, 'Keeping a chooser open across resize preserves camera, pose, HQ and edits'); test.status = 'PASS'; save();
  }
  await setViewport(page, cdp, { width: 840, height: 195 }, dpr); await page.locator('#viewer-expand').click(); await settle(page);
  assert.deepEqual(retained(await state(page)), baseline); return cases;
}
async function finishRealInputCoast(page) {
  const initial = await state(page), trace = [], startedAt = new Date().toISOString();
  let previous = initial, stableRenders = 0;
  const delta = (a, b) => ({ position: a.position.map((v, i) => v - b.position[i]), target: a.target.map((v, i) => v - b.target[i]), fov: a.fov - b.fov });
  const maxAbs = change => Math.max(...change.position.map(Math.abs), ...change.target.map(Math.abs), Math.abs(change.fov));
  report.userInputSettling = { startedAt, bound: 1024, requiredExactFreshRenders: 4, method: 'Actual no-op window resize events drive product renders; no camera/control/transform reset or mutation', initialCamera: initial.camera, initialRenderedFrames: initial.renderedFrames, trace }; save();
  for (let cycle = 1; cycle <= 1024; cycle++) {
    const beforeFrames = previous.renderedFrames;
    await page.evaluate(() => window.dispatchEvent(new Event('resize')));
    await page.waitForFunction(before => ModelViewer.getState().renderedFrames > before, beforeFrames);
    await frames(page);
    const current = await state(page), change = delta(current.camera, previous.camera);
    const same = JSON.stringify(current.camera) === JSON.stringify(previous.camera);
    stableRenders = same ? stableRenders + 1 : 0;
    trace.push({ cycle, at: new Date().toISOString(), renderedFrames: current.renderedFrames, freshFrames: current.renderedFrames - beforeFrames, exactSame: same, maxAbsStepDelta: maxAbs(change), camera: current.camera });
    report.userInputSettling.cycles = cycle; report.userInputSettling.stableRenders = stableRenders;
    report.userInputSettling.lastStepDelta = change; report.userInputSettling.maxAbsLastStepDelta = maxAbs(change);
    report.userInputSettling.finalCamera = current.camera; report.userInputSettling.finalRenderedFrames = current.renderedFrames;
    report.userInputSettling.coastDelta = delta(current.camera, initial.camera); report.userInputSettling.maxAbsCoastDelta = maxAbs(report.userInputSettling.coastDelta);
    if (stableRenders >= 4) { report.userInputSettling.exactStable = true; report.userInputSettling.finishedAt = new Date().toISOString(); save(); return report.userInputSettling; }
    if (cycle % 64 === 0) save(); previous = current;
  }
  report.userInputSettling.exactStable = false; report.userInputSettling.finishedAt = new Date().toISOString(); save();
  assert.fail('User input coast did not become bitwise stable within1024 fresh product renders: ' + JSON.stringify({ maxAbsLastStepDelta: report.userInputSettling.maxAbsLastStepDelta, lastStepDelta: report.userInputSettling.lastStepDelta }));
}
async function adjustCameraWithRealInput(page) {
  await closeMenus(page);
  const before = (await state(page)).camera, stage = await page.locator('#viewer-stage').boundingBox();
  const x = stage.x + stage.width * .62, y = stage.y + stage.height * .74;
  await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 28, y - 12, { steps: 4 }); await page.mouse.up();
  await page.mouse.wheel(0, 80); await settle(page);
  await page.mouse.move(x, y); await page.mouse.down({ button: 'right' }); await page.mouse.move(x + 12, y + 5, { steps: 3 }); await page.mouse.up({ button: 'right' }); await settle(page);
  const after = (await state(page)).camera;
  assert.notDeepEqual(after.position, before.position, 'Real drag/wheel changes the actual camera');
  assert.notDeepEqual(after.target, before.target, 'Real pan changes the actual target');
  return { before, after, realDragWheelPan: true };
}
async function collapseCards(page) {
  const ids = ['viewer-breast-card', 'viewer-skirt-card', 'viewer-common-adjustments'], before = retained(await state(page)), results = [];
  if (!(await page.locator('#viewer-breast-card > summary').isVisible())) await openDetails(page, 'viewer-workspace-menu');
  for (const id of ids) {
    const n = page.locator('#' + id), summary = n.locator('summary').first(), original = await n.evaluate(e => e.open);
    const others = {}; for (const other of ids.filter(v => v !== id)) others[other] = await page.locator('#' + other).evaluate(e => e.open);
    try {
      await summary.scrollIntoViewIfNeeded(); await summary.click(); await frames(page);
      assert.equal(await n.evaluate(e => e.open), !original);
      for (const other of Object.keys(others)) assert.equal(await page.locator('#' + other).evaluate(e => e.open), others[other]);
      assert.deepEqual(retained(await state(page)), before, 'A card collapse must retain camera, HQ, absolute edits, source .85, and pose');
      await summary.focus(); await summary.press('Enter'); await frames(page); assert.equal(await n.evaluate(e => e.open), original);
      assert.deepEqual(retained(await state(page)), before); results.push({ id, independent: true, keyboardReopen: true });
    } finally { await n.evaluate((e, open) => { e.open = open; }, original); }
  }
  await page.evaluate(() => { document.querySelector('.viewer-control-panel').scrollTop = 0; scrollTo(0, 0); }); await closeMenus(page); await settle(page);
  return results;
}
async function pickerTransportRegressions(browser) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
  const page = await context.newPage(), rules = [], responses = [], errors = [], dialogs = [], cases = [], modelRequests = [];
  page.setDefaultTimeout(15000);
  const result = { scope: 'Actual local filesystem API bytes transported unchanged; only completion order/explicit network rejection is controlled. Public picker controls and documented openPicker callback; no model prepare or synthetic positive API response.',
    cases, responses, pageErrors: errors, dialogs, modelRequests };
  report.pickerRaces = result; save();
  const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
  const normalize = file => path.resolve(String(file));
  const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
  function arm(file, label, delivery = 'unchanged') {
    const rule = { file: normalize(file), label, delivery, ready: deferred(), gate: deferred(), delivered: deferred(), taken: false, released: false };
    rules.push(rule); return rule;
  }
  async function release(rule) {
    if (!rule.released) { rule.released = true; rule.gate.resolve(); }
    await rule.delivered.promise; await frames(page);
  }
  const loadedApplicationScript = deferred();
  page.on('response', async response => { if (new URL(response.url()).pathname === '/static/app.js') { const bytes = await response.body(); result.applicationScriptSha256 = digest(bytes); result.applicationScriptUrl = response.url(); loadedApplicationScript.resolve(); save(); } });
  page.on('pageerror', error => { errors.push(String(error)); save(); });
  page.on('dialog', async dialog => { dialogs.push({ type: dialog.type(), message: dialog.message() }); save(); await dialog.dismiss(); });
  page.on('request', request => { if (request.url().endsWith('/api/viewer/prepare')) modelRequests.push(request.postDataJSON()); });
  await page.route('**/api/fs/list?*', async route => {
    const file = normalize(new URL(route.request().url()).searchParams.get('path') || '');
    const rule = rules.find(item => !item.taken && item.file === file);
    if (rule) rule.taken = true;
    try {
      const actual = await route.fetch(), body = await actual.body();
      const record = { index: responses.length + 1, requestedPath: file, url: route.request().url(), status: actual.status(), headers: actual.headers(), bytes: body.length,
        sha256: digest(body), body: JSON.parse(body.toString('utf8')), label: rule ? rule.label : null, held: !!rule, delivery: rule ? rule.delivery : 'unchanged' };
      responses.push(record); fs.writeFileSync(path.join(evidence, 'picker-real-response-' + record.index + '.json'), body); save();
      if (rule) { rule.record = record; rule.ready.resolve(record); await rule.gate.promise; }
      if (rule && rule.delivery === 'transport-abort') await route.abort('failed');
      else await route.fulfill({ response: actual, body });
      if (rule) rule.delivered.resolve();
    } catch (error) {
      if (rule) { rule.ready.reject(error); rule.delivered.reject(error); }
      throw error;
    }
  });
  let temporaryRoot = null;
  const snapshot = () => page.evaluate(() => ({ hidden: document.getElementById('picker').classList.contains('hidden'),
    crumb: document.getElementById('picker-crumb').textContent,
    names: Array.from(document.querySelectorAll('#picker-entries > li'), li => Array.from(li.childNodes).filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('').trim()),
    title: document.getElementById('picker-title').textContent,
    folderVisible: getComputedStyle(document.getElementById('picker-use-folder')).display !== 'none', folderDisabled: document.getElementById('picker-use-folder').disabled }));
  const lastResponse = file => responses.filter(item => item.requestedPath === normalize(file)).slice(-1)[0];
  async function expectDirectory(file, record, folderMode) {
    await page.waitForFunction(expected => document.getElementById('picker-crumb').textContent === expected, file); await frames(page);
    const current = await snapshot(), expected = record || lastResponse(file);
    assert(expected && !expected.body.error && expected.body.path === file, 'Use a real successful server listing as the oracle');
    const names = (expected.body.parent ? ['..'] : []).concat(expected.body.entries.filter(entry => entry.is_dir || !folderMode).map(entry => entry.name));
    assert.deepEqual(current.names, names, 'Picker entries must equal the actual current listing');
    assert.equal(current.hidden, false); assert.equal(current.folderVisible, !!folderMode);
    if (folderMode) assert.equal(current.folderDisabled, false, 'A successfully validated current folder is usable');
    return { current, expectedResponse: expected.index };
  }
  async function close() { if (!(await snapshot()).hidden) { await page.locator('#picker-cancel').click(); await frames(page); } }
  async function openViewer(root) {
    await page.locator('.tab[data-tab="viewer"]').click(); await page.locator('#viewer-add').click();
    return expectDirectory(root, null, false);
  }
  async function openGallery(root) {
    await page.locator('.tab[data-tab="gallery"]').click(); await page.locator('#gallery-browse').click();
    return expectDirectory(root, null, true);
  }
  async function folder(name) {
    await page.locator('#picker-entries > li').filter({ hasText: new RegExp('^\\s*📁?\\s*' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$') }).click();
  }
  async function modelsRoot() { await page.locator('#picker-roots > button').filter({ hasText: /^models$/ }).click(); }
  async function attempt(id, body) {
    const test = { id, status: 'RUNNING', pageErrorsBefore: errors.length, dialogsBefore: dialogs.length }; cases.push(test); save();
    try { await body(test); }
    catch (error) { test.error = { message: String(error), actual: error.actual, expected: error.expected, stack: error.stack }; }
    finally {
      for (const rule of rules.filter(item => item.taken && !item.released)) await release(rule);
      await frames(page); test.after = await snapshot();
      test.pageErrors = errors.slice(test.pageErrorsBefore); test.dialogs = dialogs.slice(test.dialogsBefore);
      test.status = test.error || test.pageErrors.length || test.dialogs.length ? 'FAIL' : 'PASS'; save(); await close();
    }
  }
  try {
    await page.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898'); await loadedApplicationScript.promise; await page.waitForFunction(() => typeof openPicker === 'function' && typeof openModelViewer === 'function');
    const tools = await (await page.request.get((process.env.VIEWER_URL || 'http://127.0.0.1:8898') + '/api/tools')).json();
    const models = normalize(tools.roots.models), modded = normalize(tools.roots.modded), baseName = 'viewer-picker-race-' + process.pid + '-' + Date.now();
    temporaryRoot = path.join(models, baseName); const a = path.join(temporaryRoot, 'folder-a'), b = path.join(temporaryRoot, 'folder-b');
    fs.mkdirSync(path.join(a, 'child-a'), { recursive: true }); fs.mkdirSync(path.join(b, 'child-b'), { recursive: true }); fs.mkdirSync(modded, { recursive: true });
    for (const [directory, name] of [[a, 'neutral-a.unity'], [b, 'neutral-b.unity']]) fs.copyFileSync(path.join(__dirname, 'fixtures', 'viewer_textured_triangle.unity'), path.join(directory, name));
    result.fixture = { root: temporaryRoot, sourceSha256: digest(fs.readFileSync(path.join(__dirname, 'fixtures', 'viewer_textured_triangle.unity'))), noGameAsset: true }; save();
    async function openBase() { await openViewer(models); await folder(baseName); return expectDirectory(temporaryRoot, null, false); }
    await attempt('cancel-pending-success-does-not-write-hidden-dom', async test => {
      const pending = arm(models, 'cancelled-initial-models-list');
      await page.locator('.tab[data-tab="viewer"]').click(); await page.locator('#viewer-add').click(); await pending.ready.promise;
      test.pending = await snapshot(); await page.locator('#picker-cancel').click(); test.cancelled = await snapshot();
      await release(pending); test.completed = await snapshot();
      assert.deepEqual(test.completed, test.cancelled, 'A cancelled response must not write hidden picker DOM');
    });
    await attempt('close-reopen-new-session-ignores-old-success', async test => {
      await openBase(); const old = arm(a, 'closed-session-folder-a'); await folder('folder-a'); await old.ready.promise;
      await page.locator('#picker-cancel').click(); await openGallery(modded); await modelsRoot(); await expectDirectory(models, null, true);
      await folder(baseName); await expectDirectory(temporaryRoot, null, true); await folder('folder-b'); test.latest = await expectDirectory(b, null, true);
      await release(old); assert.deepEqual(await snapshot(), test.latest.current, 'Old picker-session results cannot replace the reopened current folder');
      await page.locator('#picker-use-folder').click(); await page.waitForFunction(() => document.getElementById('picker').classList.contains('hidden'));
      assert.equal(await page.locator('#gallery-path').inputValue(), b, 'The real gallery callback receives the current validated directory');
    });
    await attempt('same-session-out-of-order-folder-navigation-latest-wins', async test => {
      await openBase(); const old = arm(models, 'same-session-models-folder-a'), latest = arm(modded, 'same-session-modded-folder-b');
      await modelsRoot(); await old.ready.promise; await page.locator('#picker-roots > button').filter({ hasText: /^modded$/ }).click(); await latest.ready.promise;
      await release(latest); test.latest = await expectDirectory(modded, latest.record, false);
      await release(old); assert.deepEqual(await snapshot(), test.latest.current, 'A late earlier navigation cannot overwrite the latest current folder');
    });
    await attempt('stale-http-json-failure-does-not-alert-or-overwrite', async test => {
      const gone = path.join(temporaryRoot, 'deleted-folder'); fs.mkdirSync(gone); await openBase(); fs.rmdirSync(gone);
      const old = arm(gone, 'deleted-real-folder-http-json-error'); await folder('deleted-folder'); const response = await old.ready.promise;
      assert(response.status >= 400 && response.body.error, 'Use the actual server HTTP/JSON failure, not a fabricated payload'); test.realFailureResponse = response.index;
      await page.locator('#picker-roots > button').filter({ hasText: /^modded$/ }).click(); test.latest = await expectDirectory(modded, null, false); await release(old);
      assert.deepEqual(await snapshot(), test.latest.current, 'A stale real HTTP/JSON error must not change current picker DOM');
    });
    await attempt('stale-transport-rejection-does-not-alert-or-overwrite', async test => {
      await openBase(); const old = arm(a, 'real-response-followed-by-explicit-transport-rejection', 'transport-abort'); await folder('folder-a'); await old.ready.promise;
      await page.locator('#picker-cancel').click(); await openViewer(models); await folder(baseName); await expectDirectory(temporaryRoot, null, false);
      await folder('folder-b'); test.latest = await expectDirectory(b, null, false); await release(old);
      assert.deepEqual(await snapshot(), test.latest.current, 'A rejected obsolete transport must not contaminate a later picker session');
    });
    await attempt('directory-open-clears-stale-ui-and-disables-unvalidated-folder-use', async test => {
      const pending = arm(modded, 'pending-directory-picker-before-validated-cwd');
      await page.locator('.tab[data-tab="gallery"]').click(); await page.locator('#gallery-browse').click(); await pending.ready.promise;
      test.pending = await snapshot(); assert.equal(test.pending.folderVisible, true); assert.equal(test.pending.folderDisabled, true, 'Use folder is disabled until the current directory has been validated');
      assert.equal(test.pending.crumb, '', 'Reopening clears the old displayed directory immediately'); assert.deepEqual(test.pending.names, [], 'Reopening clears old selectable entries immediately');
      await release(pending); test.loaded = await expectDirectory(modded, pending.record, true);
    });
    await attempt('reentrant-actual-entry-callback-keeps-new-picker-session-open', async test => {
      await page.evaluate(({ a, b }) => openPicker('path', () => openPicker('dir', () => {}, 'models', b), 'models', a), { a, b });
      await expectDirectory(a, null, false); const next = arm(b, 'reentrant-next-picker-folder-b');
      await page.locator('#picker-entries > li').filter({ hasText: 'neutral-a.unity' }).click(); await next.ready.promise;
      test.pendingNewSession = await snapshot(); assert.equal(test.pendingNewSession.hidden, false, 'Closing the completed old selection must not close its reentrant replacement session');
      assert.equal(test.pendingNewSession.folderVisible, true); assert.equal(test.pendingNewSession.folderDisabled, true);
      await release(next); test.loaded = await expectDirectory(b, next.record, true);
    });
    result.status = cases.length === 7 && cases.every(test => test.status === 'PASS') && !errors.length && !dialogs.length ? 'PASS' : 'FAIL'; save();
    assert.deepEqual(modelRequests, [], 'Filesystem race coverage must not fake or claim a model preparation');
    assert.deepEqual(errors, [], 'No page errors are filtered or permitted'); assert.deepEqual(dialogs, [], 'No stale-response alerts are filtered or permitted');
    assert(cases.length === 7 && cases.every(test => test.status === 'PASS'), 'Every deterministic picker race must pass: ' + JSON.stringify(cases.filter(test => test.status !== 'PASS').map(test => ({ id: test.id, error: test.error, pageErrors: test.pageErrors, dialogs: test.dialogs }))));
    result.status = 'PASS'; save(); return result;
  } finally {
    for (const rule of rules.filter(item => item.taken && !item.released)) await release(rule).catch(() => {});
    await context.close(); if (temporaryRoot) fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

(async () => {
  const launch = { headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch);
  try {
    for (const profile of pickerRaceOnly || lifecycleOnly || popoverBoundsOnly ? [] : profiles) {
      const test = { profile }; report.profiles.push(test); save();
      const { page, context, cdp, errors, requests } = await setup(browser, profile);
      try {
        const edited = retained(await state(page));
        test.normal = await viewportMetrics(page);
        assert.equal(test.normal.viewport.width, profile.width); assert.equal(test.normal.viewport.height, profile.height);
        assert.equal(test.normal.overflow, 0); assert.equal(test.normal.glError, 0); assert(test.normal.pixelCount > 100 && test.normal.foregroundHeight > 30);
        assert(test.normal.stage.y >= -1 && test.normal.stage.bottom <= profile.height + 1, 'Initial model stage must be fully visible, not revealed by scrolling');
        if (profile.short) {
          assert(test.normal.stage.height >= profile.height - 8, 'Loaded short window gives its usable height to the preview');
          assert(test.normal.layout.safeInsets.top <= 8.5 && test.normal.layout.safeInsets.bottom <= 8.5, 'Vertical HUD fitting uses a small canvas margin, not full-width edge rows');
          assert(test.normal.foregroundHeight > (test.normal.stage.height - test.normal.layout.safeInsets.top) * .45, 'Generated vertical geometry must use a useful part of unobscured height');
          assert.equal(test.normal.layout.shortHeight, true);
          test.workspace = await workspace(page);
          if (profile.narrow) assert(await page.evaluate(() => document.getElementById('viewer-workspace-menu-content').contains(__resolutionIdentity.inspector)), 'Narrow short-window editing remains reachable inside the workspace popup');
        }
        if (profile.fold) {
          assert(test.normal.stage.height > 500, 'Primary 752px Fold portrait gets a taller preview than old 401px stacked layout');
          assert(test.normal.stage.width < test.normal.stage.height, 'Primary Fold preview is taller than it is wide');
          assert(test.normal.inspector.x >= test.normal.stage.right - 1 && test.normal.inspector.y <= test.normal.stage.y + 2, 'Editing stays beside the model');
          assert(test.normal.inspector.width >= 239 && test.normal.inspector.width <= 301, 'Fold inspector is narrow and bounded');
        }
        if (profile.id === 'wide-tablet') {
          const cards = await page.evaluate(() => { const rect = id => { const r = document.getElementById(id).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, right: r.right }; }; return { breast: rect('viewer-breast-card'), skirt: rect('viewer-skirt-card') }; });
          assert(test.normal.stage.width <= test.normal.stage.height * 1.27, 'Normal wide preview avoids unbounded empty horizontal space');
          assert(cards.breast.width <= 361 && cards.skirt.width <= 361 && cards.skirt.x > cards.breast.x && Math.abs(cards.breast.y - cards.skirt.y) <= 2, 'Freed wide space holds two compact independent editing cards beside one another');
          assert(test.normal.inspector.right >= profile.width - 24, 'Normal wide editing uses freed width rather than leaving an empty outer gutter'); test.wideCards = cards;
        }
        if (profile.id === 'tall-wide-boundary') {
          const cards = await page.evaluate(() => { const rect = id => { const r = document.getElementById(id).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, right: r.right }; }; return { breast: rect('viewer-breast-card'), skirt: rect('viewer-skirt-card') }; });
          assert(test.normal.inspector.width >= 319 && test.normal.inspector.width <= 321, 'Tall1200 viewport retains the bounded320px editor');
          assert(cards.breast.width >= 259 && cards.skirt.width >= 259 && Math.abs(cards.skirt.x - cards.breast.x) <= 2 && cards.skirt.y > cards.breast.y, 'A bounded320px editor uses usable single-column cards rather than two tiny forced columns'); test.tallCards = cards;
        }
        test.hud = await assertHud(page, !!profile.short, { profile: profile.id, locale: 'ko', mode: 'normal' }); assert.deepEqual(retained(await state(page)), edited);
        test.cards = await collapseCards(page); test.normalImage = await capture(page, cdp, profile.id + '-normal.png');
        const beforeExpand = retained(await state(page)); await page.locator('#viewer-expand').click(); await settle(page);
        assert.deepEqual(retained(await state(page)), beforeExpand, 'Expand preserves actual orbit, zoom, pose, HQ and source/edit endpoints');
        test.expanded = await viewportMetrics(page); assert(test.expanded.stage.height >= profile.height - 1); test.expandedHud = await assertHud(page, !!profile.short, { profile: profile.id, locale: 'ko', mode: 'expanded' });
        if (profile.short) test.expandedWorkspace = await workspace(page, 'expanded-short', profile.id === 'cover-default-landscape');
        await page.locator('#viewer-expand').click(); await settle(page); assert.deepEqual(retained(await state(page)), beforeExpand);
        test.retained = retained(await state(page)); assert.deepEqual(errors, []); test.errors = errors; test.prepareCalls = requests.length; test.status = 'PASS'; save();
      } catch (error) {
        test.error = { message: String(error), stack: error.stack };
        try { test.failureImage = await capture(page, cdp, profile.id + '-failure.png'); } catch (captureError) { test.failureCaptureError = String(captureError); }
        save(); throw error;
      } finally { await context.close(); }
    }
    if (!pickerRaceOnly && !popoverBoundsOnly) {
    // Reparenting a global header across short/normal modes while fullscreen is
    // active must retain focus isolation and restore the same original node.
    const profile = profiles[0], { page, context, cdp, errors } = await setup(browser, profile);
    try {
      const openPickerResize = await pickerOpenAcrossViewportChange(page, cdp, profile.dpr);
      const actualUserCamera = await adjustCameraWithRealInput(page);
      const inputCoast = await finishRealInputCoast(page);
      const before = retained(await state(page));
      report.lifecycleProgress = { actualUserCamera, inputCoast: { cycles: inputCoast.cycles, exactStable: inputCoast.exactStable, coastDelta: inputCoast.coastDelta }, before }; save();
      await page.locator('#viewer-fullscreen').click(); await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'browser'); await settle(page);
      report.lifecycleProgress.shortFullscreen = retained(await state(page)); save();
      const fullscreenWorkspace = await workspace(page, 'browser-fullscreen-short');
      report.lifecycleProgress.fullscreenWorkspace = fullscreenWorkspace; report.lifecycleProgress.afterChooser = retained(await state(page)); save();
      await openDetails(page, 'viewer-workspace-menu');
      assert(await page.evaluate(() => document.getElementById('viewer-workspace-menu-content').contains(__resolutionIdentity.header)));
      assert.notEqual(await page.locator('.tab[data-tab="tools"]').getAttribute('tabindex'), '-1', 'Internal app navigation stays keyboard reachable');
      await closeMenus(page);
      await setViewport(page, cdp, { width: 1024, height: 768 }, profile.dpr);
      assert(await page.evaluate(() => __resolutionIdentity.header.parentElement === document.body));
      assert.equal(await page.locator('body > header').getAttribute('aria-hidden'), 'true', 'Header moved outside active fullscreen must join focus isolation');
      assert.equal(await page.locator('.tab[data-tab="tools"]').getAttribute('tabindex'), '-1');
      report.lifecycleProgress.afterOrientation = retained(await state(page)); save();
      assert.deepEqual(report.lifecycleProgress.afterOrientation, before, 'Orientation/mode reparenting preserves actual model/camera state');
      const fullscreenImage = await capture(page, cdp, 'fullscreen-header-restore.png');
      await page.locator('#viewer-fullscreen').click(); await page.waitForFunction(() => ModelViewer.getState().layout.fullscreen === 'none'); await settle(page);
      assert.equal((await state(page)).layout.expanded, false); assert.equal(await page.locator('body > header').getAttribute('aria-hidden'), null);
      assert.notEqual(await page.locator('.tab[data-tab="tools"]').getAttribute('tabindex'), '-1');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'viewer-fullscreen', 'Fullscreen returns focus to its real initiating control');
      await setViewport(page, cdp, { width: 840, height: 195 }, profile.dpr);
      await openDetails(page, 'viewer-workspace-menu'); await target(page, '.tab[data-tab="tools"]', '#viewer-workspace-menu-content');
      await page.locator('.tab[data-tab="tools"]').click();
      assert(await page.locator('#tab-tools').evaluate(n => n.classList.contains('active')));
      assert(await page.evaluate(() => __resolutionIdentity.header.parentElement === document.body), 'Leaving viewer restores navigation to the document');
      await page.evaluate(() => { window.__resolutionInactiveEscape = []; document.addEventListener('keydown', e => { if (e.key === 'Escape') __resolutionInactiveEscape.push({ defaultPrevented: e.defaultPrevented, hiddenViewerFocus: !!document.activeElement.closest('#tab-viewer'), activeTab: document.activeElement.dataset.tab || null }); }); });
      await page.keyboard.press('Escape');
      const inactiveEscape = await page.evaluate(() => __resolutionInactiveEscape[0]);
      assert(inactiveEscape && !inactiveEscape.defaultPrevented && !inactiveEscape.hiddenViewerFocus && inactiveEscape.activeTab === 'tools', 'An inactive viewer must not consume Escape or steal focus back into hidden controls: ' + JSON.stringify(inactiveEscape));
      await page.locator('.tab[data-tab="viewer"]').click(); await settle(page);
      assert.deepEqual(retained(await state(page)), before, 'Actual app tab switch preserves loaded/edited model');
      await page.evaluate(() => ModelViewer.dispose());
      assert(await page.evaluate(() => __resolutionIdentity.header.parentElement === document.body));
      assert.notEqual(await page.locator('.tab[data-tab="tools"]').getAttribute('tabindex'), '-1');
      assert.deepEqual(errors, []); report.lifecycle.push({ status: 'PASS', sameHeaderRestored: true, focusIsolationAcrossReparenting: true, realTabNavigation: true, disposedNavigationRestored: true, actualUserCamera, fullscreenWorkspace, inactiveEscape, openPickerResize, fullscreenImage });
    } catch (error) {
      report.lifecycleError = { message: String(error), stack: error.stack };
      try { report.lifecycleFailureImage = await capture(page, cdp, 'fullscreen-lifecycle-failure.png'); } catch (captureError) { report.lifecycleFailureCaptureError = String(captureError); }
      save(); throw error;
    } finally { await context.close(); }
    }
    if (!lifecycleOnly && !pickerRaceOnly) await popoverBoundsRegressions(browser);
    if (!lifecycleOnly && !popoverBoundsOnly) await pickerTransportRegressions(browser);
    report.status = 'PASS'; save(); console.log(JSON.stringify({ status: report.status, profiles: report.profiles.length, lifecycleCases: report.lifecycle.length, evidence }));
  } catch (error) { report.status = 'FAIL'; report.error = { message: String(error), stack: error.stack, actual: error.actual, expected: error.expected }; save(); throw error; }
  finally { await browser.close(); for (const file of temporaryPickerFiles) { if (fs.existsSync(file)) fs.unlinkSync(file); } }
})().catch(error => { console.error(error); process.exitCode = 1; });
