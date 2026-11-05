/* Actual WebGL checks for the SIFAS 2x MSAA/native-resolution viewer option.
 * All model, animation and texture inputs below are generated test data.
 */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const texturePixels = [82, 150, 210, 255];
const textureData = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMImnbpPwAFsgK6ryJ6FAAAAABJRU5ErkJggg==';
const previewName = 'Synthetic verified preview';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-quality-'));
fs.mkdirSync(evidence, { recursive: true });

function observeGpu(options) {
  const forceWebGL1 = options.forceWebGL1;
  const originalContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type) {
    if (forceWebGL1 && type === 'webgl2') return null;
    if (options.forceNoAA && (type === 'webgl' || type === 'experimental-webgl')) {
      const args = Array.from(arguments);
      args[1] = Object.assign({}, args[1] || {}, { antialias: false });
      return originalContext.apply(this, args);
    }
    return originalContext.apply(this, arguments);
  };
  window.__qualityGpu = { allocations: [], uploads: [], deletedRenderbuffers: 0, deletedFramebuffers: 0 };
  const record = window.__qualityGpu;
  const prototypes = [window.WebGLRenderingContext && WebGLRenderingContext.prototype,
    window.WebGL2RenderingContext && WebGL2RenderingContext.prototype].filter(Boolean);
  prototypes.forEach(prototype => {
    const upload = prototype.texImage2D;
    prototype.texImage2D = function () {
      const result = upload.apply(this, arguments);
      const image = arguments[arguments.length - 1];
      if (image && typeof image.width === 'number' && image.width > 0 && image.height > 0) {
        const data = { width: image.width, height: image.height };
        if (image.width === 1 && image.height === 1) {
          try {
            const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
            const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
            data.pixels = Array.from(context.getImageData(0, 0, 1, 1).data);
          } catch (error) { data.error = String(error); }
        }
        record.uploads.push(data);
      }
      return result;
    };
    for (const [method, key] of [['deleteRenderbuffer', 'deletedRenderbuffers'], ['deleteFramebuffer', 'deletedFramebuffers']]) {
      const original = prototype[method];
      prototype[method] = function (object) { if (object) record[key] += 1; return original.apply(this, arguments); };
    }
  });
  if (window.WebGL2RenderingContext) {
    const prototype = WebGL2RenderingContext.prototype;
    const allocate = prototype.renderbufferStorageMultisample;
    prototype.renderbufferStorageMultisample = function (target, samples, format, width, height) {
      const result = allocate.apply(this, arguments);
      record.allocations.push({ requested: samples, format, width, height,
        depthStencil: format === this.DEPTH24_STENCIL8 || format === this.DEPTH32F_STENCIL8,
        actual: this.getRenderbufferParameter(this.RENDERBUFFER, this.RENDERBUFFER_SAMPLES) });
      return result;
    };
  }
}

async function capture(page, save, compare) {
  return page.evaluate(([save, compare]) => {
    const probe = ModelViewer.renderProbe(33), canvas = document.getElementById('viewer-canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    const width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
    const pixels = new Uint8Array(width * height * 4);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    const background = Array.from(pixels.slice((width + 1) * 4, (width + 1) * 4 + 4));
    const histogram = new Map();
    let objectSamples = 0;
    for (let y = 0; y < height; y += 2) {
      for (let x = 0; x < width; x += 2) {
        const offset = (y * width + x) * 4;
        if (Math.abs(pixels[offset] - background[0]) + Math.abs(pixels[offset + 1] - background[1]) +
            Math.abs(pixels[offset + 2] - background[2]) <= 24) continue;
        objectSamples += 1;
        const key = pixels[offset] + ',' + pixels[offset + 1] + ',' + pixels[offset + 2] + ',' + pixels[offset + 3];
        histogram.set(key, (histogram.get(key) || 0) + 1);
      }
    }
    const dominant = Array.from(histogram.entries()).sort((a, b) => b[1] - a[1])[0];
    const frames = window.__qualityFrames || (window.__qualityFrames = {});
    let changedPixels = null;
    if (compare) {
      const previous = frames[compare];
      if (!previous || previous.length !== pixels.length) throw new Error('Quality round-trip viewport changed');
      changedPixels = 0;
      for (let offset = 0; offset < pixels.length; offset += 4) {
        if (pixels[offset] !== previous[offset] || pixels[offset + 1] !== previous[offset + 1] ||
            pixels[offset + 2] !== previous[offset + 2] || pixels[offset + 3] !== previous[offset + 3]) changedPixels += 1;
      }
    }
    if (save) frames[save] = pixels;
    return { probe, width, height, glError: gl.getError(), objectSamples, background,
      dominantColor: dominant ? dominant[0].split(',').map(Number) : null,
      dominantSamples: dominant ? dominant[1] : 0, changedPixels,
      contextSamples: gl.getParameter(gl.SAMPLES), version: gl.getParameter(gl.VERSION),
      maxRenderbufferSize: gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) };
  }, [save, compare]);
}

function nearColor(actual, expected, label) {
  assert(actual && expected, label + ' missing color');
  actual.forEach((channel, index) => assert(Math.abs(channel - expected[index]) <= 1,
    label + ': ' + JSON.stringify({ actual, expected })));
}

function retained(state) {
  return { camera: state.camera, rig: state.rig, loadedPaths: state.loadedPaths, modelId: state.modelId,
    sourceTriangles: state.sourceTriangles, stats: state.stats };
}

async function exerciseSizingNoOps(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const reference = await capture(page, 'sizing-no-op-reference');
  const observations = await page.evaluate(() => {
    const observer = window.__qualitySizingQa, quality = observer.controller;
    const initial = quality.getState(), ratioProperty = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio');
    const result = {}, draw = () => ModelViewer.renderProbe(33);
    function repeats() {
      const start = quality.getState(), allocations = __qualityGpu.allocations.length;
      observer.calls.length = 0;
      for (let count = 0; count < 12; count++) quality.resize(start.cssWidth, start.cssHeight);
      return { before: start, after: quality.getState(), setters: observer.calls.slice(),
        newAllocations: __qualityGpu.allocations.length - allocations };
    }
    try {
      result.standard = repeats();
      quality.resize(initial.cssWidth + 8, initial.cssHeight + 6);
      result.actualResize = quality.getState();
      quality.resize(initial.cssWidth, initial.cssHeight); draw();
      quality.setEnabled(true); quality.resize(initial.cssWidth, initial.cssHeight); draw();
      result.high = repeats();
      Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1.25 });
      quality.resize(initial.cssWidth, initial.cssHeight); result.actualDprChange = quality.getState(); draw();
      const highDimensions = quality.getState();
      quality.setEnabled(false); quality.resize(initial.cssWidth, initial.cssHeight);
      result.equalResolutionModeChange = { before: highDimensions, after: quality.getState() }; draw();
      quality.invalidateGPU(); quality.restoreGPU(); quality.resize(initial.cssWidth, initial.cssHeight);
      result.gpuRestore = quality.getState(); draw();
    } finally {
      if (ratioProperty) Object.defineProperty(window, 'devicePixelRatio', ratioProperty);
      else delete window.devicePixelRatio;
      quality.setEnabled(initial.enabled); quality.resize(initial.cssWidth, initial.cssHeight); draw();
    }
    return result;
  });
  for (const mode of ['standard', 'high']) {
    const row = observations[mode];
    assert(row.before.ready && row.after.ready, mode + ': identical measurements must keep the actual rendered pipeline ready');
    assert.deepEqual(row.setters, [], mode + ': repeated observers must not reset the canvas or GPU resources');
    assert.equal(row.newAllocations, 0);
    assert.equal(row.before.width, row.after.width); assert.equal(row.before.height, row.after.height);
  }
  for (const key of ['actualResize', 'actualDprChange', 'gpuRestore']) {
    assert.equal(observations[key].ready, false, key + ': real invalidation still requires a new draw');
  }
  const equal = observations.equalResolutionModeChange;
  assert.equal(equal.before.width, equal.after.width); assert.equal(equal.before.height, equal.after.height);
  assert.notEqual(equal.before.enabled, equal.after.enabled);
  assert.equal(equal.after.ready, false, 'A quality-mode change cannot be hidden by identical pixel dimensions');
  const restored = await capture(page, null, 'sizing-no-op-reference');
  assert.equal(restored.changedPixels, 0, 'Sizing/HQ/DPR/GPU resource checks must restore exact source pixels');
  assert.equal(restored.glError, 0); assert.equal(reference.glError, 0);
  return observations;
}

async function exercisePage(browser, forceWebGL1, forceNoAA = false) {
  let generated = fixture({ allSaved: true, previewName, previewVerified: true, textureData });
  const context = await browser.newContext({ viewport: { width: 480, height: 780 }, deviceScaleFactor: 2.5 });
  await context.addInitScript(observeGpu, { forceWebGL1, forceNoAA });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
  const page = await context.newPage(), errors = [], gpuMessages = [], requests = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (/WebGL|GL_INVALID|THREE.WebGLProgram/.test(message.text())) gpuMessages.push(message.text()); });
  await page.route('**/api/viewer/prepare', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'quality-fixture', url: '/api/viewer/model/quality-fixture.glb',
      stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 1 }, warnings: [], rig: generated.rig
    }) });
  });
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200,
    contentType: 'model/gltf-binary', headers: { 'Cache-Control': 'no-store' }, body: generated.glb }));
  const state = () => page.evaluate(() => ModelViewer.getState());
  const slider = (id, value) => page.locator('#' + id).evaluate((input, value) => {
    input.value = String(value); input.dispatchEvent(new Event('input', { bubbles: true }));
  }, value);
  async function open(name) {
    await page.evaluate(name => openModelViewer(['/synthetic/' + name + '.unity']), name);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    await page.evaluate(() => ModelViewer.renderProbe());
  }
  async function setQuality(enabled) {
    await page.locator('#viewer-high-quality').setChecked(enabled);
    await page.waitForFunction(enabled => {
      const state = ModelViewer.getState();
      ModelViewer.renderProbe();
      return !!state.quality && state.quality.enabled === enabled && state.quality.ready;
    }, enabled);
  }
  try {
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerQuality);
    await page.evaluate(() => {
      const create = ViewerQuality.create;
      ViewerQuality.create = function (renderer) {
        const observer = window.__qualitySizingQa = { renderer, calls: [] };
        for (const name of ['setSize', 'setPixelRatio']) {
          const original = renderer[name];
          renderer[name] = function () { observer.calls.push({ name, args: Array.from(arguments) }); return original.apply(this, arguments); };
        }
        return observer.controller = create.apply(this, arguments);
      };
    });
    await open('quality-basic');
    const checkbox = page.locator('#viewer-high-quality');
    assert(await checkbox.isVisible(), 'Quality switch must be visible outside collapsed display options');
    assert(!(await checkbox.isChecked()), 'Standard quality preserves the existing default');
    const hit = await checkbox.evaluate(input => {
      const label = input.closest('label'), rect = label.getBoundingClientRect();
      return { width: rect.width, height: rect.height, label: label.textContent.trim() };
    });
    assert(hit.width >= 32 && hit.height >= 32, JSON.stringify(hit));
    const initial = await state();
    assert.equal(initial.quality.enabled, false);
    assert.equal(initial.quality.nativePixelRatio, 2.5);
    assert.equal(initial.quality.effectivePixelRatio, 1.75);
    assert.equal(initial.rig.savedNodes.applied, 5);
    await page.locator('#viewer-adjustments').evaluate(element => { element.open = true; });
    assert.equal(await page.locator('#viewer-height,#viewer-height-number,#viewer-breast,#viewer-breast-number').count(), 0,
      'Quality tests use discrete source profiles, without arbitrary height or breast percentages');
    await page.locator('#viewer-breast-preset').selectOption('emma');
    await slider('viewer-time', .37);
    await page.locator('#viewer-expression-advanced').evaluate(element => { element.open = true; });
    const firstExpression = await page.locator('#viewer-expression option').evaluateAll(options => options.find(option => option.value).value);
    await page.locator('#viewer-expression').selectOption(firstExpression);
    await slider('viewer-expression-value', 65);
    await page.locator('.viewer-node-editor').evaluate(element => { element.open = true; });
    await page.locator('#viewer-node').selectOption('3');
    await page.locator('[data-viewer-node-kind="position"][data-axis="Y"]').fill('.95');
    await page.locator('[data-viewer-node-kind="rotation"][data-axis="X"]').fill('12');
    const before = await state(), standard = await capture(page, 'standard');
    assert.equal(before.rig.body.breastPreset, 'emma');
    assert.deepEqual(before.rig.bones.find(bone => bone.node === '2').scale, [1.3, 1.18, 1.3]);
    assert.deepEqual(before.rig.bones.find(bone => bone.node === '3').position, [-.1, .95, 0]);
    assert.equal(before.rig.expressions[0].weight, .65, 'Quality round trips retain an actual selected expression');
    assert(standard.probe.ready && standard.objectSamples > 20 && standard.glError === 0);
    assert.equal(standard.probe.triangles, 1); assert.equal(standard.probe.sourceTriangles, 1);
    const sizingNoOps = await exerciseSizingNoOps(page);
    const requestCount = requests.length;
    await setQuality(true);
    const high = await state(), hq = await capture(page, 'hq');
    assert.equal(requests.length, requestCount, 'Quality switch must not reload the model');
    assert.deepEqual(retained(high), retained(before), 'Quality changes must preserve camera, pose and all user/saved edits');
    assert.equal(high.quality.gameSamples, 2);
    assert.equal(high.quality.nativePixelRatio, 2.5);
    assert.equal(high.quality.effectivePixelRatio, 2.5);
    assert(hq.width > standard.width && hq.height > standard.height, 'HQ must lift the existing 1.75 DPR limit');
    assert.equal(hq.width, high.quality.width); assert.equal(hq.height, high.quality.height);
    assert.equal(hq.width, Math.floor(high.quality.cssWidth * 2.5));
    assert.equal(hq.height, Math.floor(high.quality.cssHeight * 2.5));
    assert(hq.width <= hq.maxRenderbufferSize && hq.height <= hq.maxRenderbufferSize);
    assert.equal(hq.glError, 0); assert.equal(hq.probe.glError, 0);
    assert.equal(hq.probe.triangles, 1, 'Fullscreen composition must not appear as model triangles');
    assert.equal(high.trianglesRendered, 1); assert.equal(hq.probe.sourceTriangles, 1);
    nearColor(hq.dominantColor, standard.dominantColor, 'Basic material gamma/color');
    const gpu = await page.evaluate(() => window.__qualityGpu);
    if (!forceWebGL1) {
      assert(high.quality.webgl2, 'Modern test target must have real WebGL2');
      const allocations = gpu.allocations.filter(row => row.width === hq.width && row.height === hq.height);
      assert(allocations.length >= 2, 'HQ needs actual multisample color and depth/stencil storage');
      assert(high.quality.requestedSamples >= 2);
      assert(allocations.every(row => row.requested === high.quality.requestedSamples && row.actual >= row.requested), JSON.stringify(allocations));
      assert(allocations.some(row => row.depthStencil), 'The offscreen target retains real depth/stencil storage');
      assert.equal(high.quality.effectiveSamples, allocations[0].actual, 'Report actual GPU rounding, not the requested count');
      assert.equal(high.quality.mode, 'multisample');
      assert(high.quality.targetAllocated);
    } else {
      assert(!high.quality.webgl2); assert.equal(gpu.allocations.length, 0);
      assert.equal(high.quality.effectiveSamples, hq.contextSamples);
      assert(['context-aa', 'native-resolution'].includes(high.quality.mode), JSON.stringify(high.quality));
      assert(high.quality.fallbackReason, 'Unsupported exact MSAA must be reported truthfully');
      if (forceNoAA) {
        assert.equal(hq.contextSamples, 0);
        assert.equal(high.quality.mode, 'native-resolution');
        await page.locator('#viewer-info').evaluate(element => { element.open = true; });
        assert(await page.locator('#viewer-quality-status').isVisible());
        assert((await page.locator('#viewer-quality-status').innerText()).includes('edge smoothing is unavailable'));
        await page.locator('#viewer-info').evaluate(element => { element.open = false; });
      }
    }
    const uploaded = gpu.uploads;
    assert(uploaded.length > 0, 'Observe the actual original texture upload');
    for (const row of uploaded) {
      assert.equal(row.width, 1, 'Quality mode must not resize the authored source image');
      assert.equal(row.height, 1, 'Quality mode must not resize the authored source image');
      assert(!row.error, row.error); assert.deepEqual(row.pixels, texturePixels);
    }
    await setQuality(false);
    const returned = await capture(page, null, 'standard');
    assert.equal(returned.changedPixels, 0, 'Standard→HQ→standard restores the exact original framebuffer');
    assert.deepEqual(retained(await state()), retained(before));
    await setQuality(true);
    const repeated = await capture(page, null, 'hq');
    assert.equal(repeated.changedPixels, 0, 'Repeated HQ activation must not accumulate transforms or color changes');

    const resizedFrom = await state();
    await page.setViewportSize({ width: 620, height: 850 });
    await page.waitForFunction(width => ModelViewer.getState().quality.width !== width, resizedFrom.quality.width);
    const resized = await capture(page), resizedState = await state();
    assert.equal(resized.glError, 0); assert.equal(resized.width, resizedState.quality.width);
    assert.equal(resized.width, Math.floor(resizedState.quality.cssWidth * 2.5));
    assert.deepEqual(resizedState.rig, resizedFrom.rig); assert.deepEqual(resizedState.camera, resizedFrom.camera);
    await page.locator('#viewer-play').click(); await page.waitForTimeout(100);
    const playingBefore = await state(); assert(playingBefore.rig.playing);
    await setQuality(false); await page.waitForTimeout(80);
    const playingAfter = await state(); assert(playingAfter.rig.playing);
    assert.equal(playingAfter.rig.selectedClip, playingBefore.rig.selectedClip);
    assert.deepEqual(playingAfter.rig.body, playingBefore.rig.body);
    assert.deepEqual(playingAfter.rig.nodeAdjustments, playingBefore.rig.nodeAdjustments);
    assert.deepEqual(playingAfter.rig.expressions, playingBefore.rig.expressions);
    await page.locator('#viewer-play').click(); await setQuality(true);
    const beforeLoss = await state(), beforeLossFrame = await capture(page);
    await page.evaluate(() => {
      const canvas = document.getElementById('viewer-canvas'), gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      window.__qualityLostContext = gl.getExtension('WEBGL_lose_context');
      if (!window.__qualityLostContext) throw new Error('Real context-loss extension unavailable');
      window.__qualityLostContext.loseContext();
    });
    await page.waitForFunction(() => ModelViewer.getState().contextLost);
    await page.waitForTimeout(150); await page.evaluate(() => window.__qualityLostContext.restoreContext());
    await page.waitForFunction(() => !ModelViewer.getState().contextLost);
    await page.waitForFunction(() => { ModelViewer.renderProbe(); return ModelViewer.getState().quality.ready; });
    const recovered = await capture(page), recoveredState = await state();
    assert.equal(recovered.glError, 0); assert.equal(recovered.probe.triangles, 1);
    assert(recoveredState.quality.enabled); assert.deepEqual(retained(recoveredState), retained(beforeLoss));
    nearColor(recovered.dominantColor, beforeLossFrame.dominantColor, 'Restored material gamma/color');
    const recoveredUploads = await page.evaluate(() => window.__qualityGpu.uploads);
    assert(recoveredUploads.length >= 2, 'Restored context reuploads the same original image');
    recoveredUploads.forEach(row => {
      assert.equal(row.width, 1); assert.equal(row.height, 1); assert.deepEqual(row.pixels, texturePixels);
    });

    generated = fixture({ allSaved: true, previewName, previewVerified: true, textureData, shader: true });
    await open('quality-member'); await setQuality(false);
    const memberStandard = await capture(page);
    assert.equal(memberStandard.probe.triangles, 2, 'Real SIFAS outline pass is present');
    await setQuality(true);
    const memberHigh = await capture(page), memberState = await state();
    assert.equal(memberHigh.glError, 0); assert.equal(memberHigh.probe.triangles, 2);
    assert.equal(memberHigh.probe.sourceTriangles, 1); assert.equal(memberState.trianglesRendered, 2);
    nearColor(memberHigh.dominantColor, memberStandard.dominantColor, 'AS/Member gamma/color');
    nearColor(memberHigh.background, memberStandard.background, 'Scene background encoding');
    const targetName = forceNoAA ? 'forced-real-webgl1-no-aa' : forceWebGL1 ? 'forced-real-webgl1' : 'webgl2';
    await page.screenshot({ path: path.join(evidence, 'quality-' + targetName + '.png'), fullPage: true });
    const beforeDispose = await page.evaluate(() => ({
      renderbuffers: __qualityGpu.deletedRenderbuffers, framebuffers: __qualityGpu.deletedFramebuffers
    }));
    await page.evaluate(() => ModelViewer.dispose());
    const disposed = await state(); assert(!disposed.loaded); assert(!disposed.quality.targetAllocated);
    const afterDispose = await page.evaluate(() => ({
      renderbuffers: __qualityGpu.deletedRenderbuffers, framebuffers: __qualityGpu.deletedFramebuffers
    }));
    if (!forceWebGL1) {
      assert(afterDispose.renderbuffers > beforeDispose.renderbuffers, 'Dispose deletes owned multisample buffers');
      assert(afterDispose.framebuffers > beforeDispose.framebuffers, 'Dispose deletes owned framebuffers');
    }
    await page.reload(); await page.waitForFunction(() => !!window.ViewerQuality && typeof openModelViewer === 'function');
    await open('quality-reopened'); await setQuality(true);
    const reopened = await capture(page); assert.equal(reopened.glError, 0); assert.equal(reopened.probe.triangles, 2);
    assert.deepEqual(errors, []);
    assert(!gpuMessages.some(message => /GL_INVALID|INVALID_OPERATION|THREE.WebGLProgram/.test(message)), JSON.stringify(gpuMessages));
    return { target: targetName, status: 'PASS', hit, requests, sizingNoOps,
      standard, high: { state: high.quality, frame: hq }, returned, repeated, resized,
      playing: { before: playingBefore.rig.time, after: playingAfter.rig.time }, recovered,
      member: { standard: memberStandard, high: memberHigh }, disposal: { before: beforeDispose, after: afterDispose },
      reopened, allocations: gpu.allocations, sourceTextureUploads: recoveredUploads, errors, gpuMessages };
  } finally { await context.close(); }
}

async function stencilProbe(browser) {
  const page = await browser.newPage({ viewport: { width: 400, height: 400 }, deviceScaleFactor: 2.5 });
  try {
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => !!window.ViewerQuality && !!window.THREE);
    return await page.evaluate(() => {
      const T = window.THREE, renderer = new T.WebGLRenderer({ antialias: false, stencil: true });
      renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping;
      document.body.appendChild(renderer.domElement);
      const quality = ViewerQuality.create(renderer), scene = new T.Scene();
      scene.background = new T.Color(0x202020);
      const camera = new T.OrthographicCamera(-1, 1, 1, -1, .1, 10); camera.position.z = 2;
      const writerMaterial = new T.MeshBasicMaterial({ color: 0x40aa70, depthTest: false, depthWrite: false,
        stencilWrite: true, stencilRef: 1, stencilFunc: T.AlwaysStencilFunc,
        stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.ReplaceStencilOp });
      const overlayMaterial = new T.MeshBasicMaterial({ color: 0xdd2244, depthTest: false, depthWrite: false,
        stencilWrite: true, stencilRef: 1, stencilFunc: T.NotEqualStencilFunc,
        stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp });
      const writer = new T.Mesh(new T.PlaneBufferGeometry(.8, .8), writerMaterial),
        overlay = new T.Mesh(new T.PlaneBufferGeometry(2, 2), overlayMaterial);
      writer.renderOrder = 0; overlay.renderOrder = 1; scene.add(writer, overlay);
      function draw(enabled) {
        quality.setEnabled(enabled); quality.resize(96, 96); quality.render(scene, camera);
        const gl = renderer.getContext(), width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
        const center = new Uint8Array(4), outside = new Uint8Array(4);
        gl.readPixels(Math.floor(width / 2), Math.floor(height / 2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, center);
        gl.readPixels(2, 2, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, outside);
        return { center: Array.from(center), outside: Array.from(outside), glError: gl.getError(), state: quality.getState() };
      }
      try { return { standard: draw(false), high: draw(true) }; }
      finally {
        quality.dispose(); writer.geometry.dispose(); overlay.geometry.dispose(); writerMaterial.dispose(); overlayMaterial.dispose(); renderer.dispose();
      }
    });
  } finally { await page.close(); }
}

async function allocationFailureProbe(browser) {
  const context = await browser.newContext({ viewport: { width: 480, height: 780 }, deviceScaleFactor: 2.5 });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
  const page = await context.newPage(), errors = [], gpuMessages = [], requests = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (/WebGL|GL_INVALID|THREE.WebGLProgram/.test(message.text())) gpuMessages.push(message.text()); });
  const generated = fixture({ allSaved: true, previewName, previewVerified: true, textureData });
  await page.route('**/api/viewer/prepare', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'quality-rejection', url: '/api/viewer/model/quality-rejection.glb',
      stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 1 }, warnings: [], rig: generated.rig
    }) });
  });
  await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200,
    contentType: 'model/gltf-binary', headers: { 'Cache-Control': 'no-store' }, body: generated.glb }));
  try {
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerQuality);
    await page.evaluate(() => openModelViewer(['/synthetic/quality-rejection.unity']));
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    const initial = await page.evaluate(() => {
      const probe = ModelViewer.renderProbe(33), canvas = document.getElementById('viewer-canvas');
      const gl = canvas.getContext('webgl2');
      if (!gl) throw new Error('Allocation rejection requires actual WebGL2');
      window.__qualityRejectedGL = gl;
      window.__qualityOriginalStorage = gl.renderbufferStorageMultisample;
      window.__qualityRejectedCalls = 0;
      const maximum = gl.getParameter(gl.MAX_SAMPLES);
      gl.renderbufferStorageMultisample = function (target, samples, format, width, height) {
        window.__qualityRejectedCalls += 1;
        // Issue a genuinely invalid GPU allocation. No error flag, return
        // status, renderer or product fallback is mocked by this fixture.
        return window.__qualityOriginalStorage.call(this, target, maximum + 1, format, width, height);
      };
      return { probe, state: ModelViewer.getState(), maximum };
    });
    assert.equal(initial.probe.glError, 0); assert(initial.probe.nonBackgroundSamples > 0);

    const rejected = await page.evaluate(() => {
      const input = document.getElementById('viewer-high-quality'); input.checked = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const probe = ModelViewer.renderProbe(33);
      return { probe, state: ModelViewer.getState(), rawError: __qualityRejectedGL.getError(),
        rejectedCalls: __qualityRejectedCalls };
    });
    assert(rejected.rejectedCalls >= 2, 'Real color and depth/stencil allocations were attempted');
    assert.equal(rejected.probe.glError, 0, 'Owned allocation failure recovers within the first public probe');
    assert.equal(rejected.rawError, 0, 'Recovered allocation flags must not remain sticky in the actual GL context');
    assert(rejected.probe.ready && rejected.probe.nonBackgroundSamples > 0);
    assert.equal(rejected.probe.triangles, 1); assert.equal(rejected.probe.sourceTriangles, 1);
    assert(!rejected.state.contextLost); assert(rejected.state.quality.enabled && rejected.state.quality.ready);
    assert(!rejected.state.quality.targetAllocated);
    assert(['context-aa', 'native-resolution'].includes(rejected.state.quality.mode));
    assert.equal(rejected.state.quality.fallbackReason, 'multisample-framebuffer-unavailable');
    assert(rejected.state.quality.allocationErrors.includes(1282), JSON.stringify(rejected.state.quality));
    assert.equal(rejected.state.quality.allocationFailures, 1);
    assert(rejected.state.quality.recoveredAllocationErrors >= 1);
    assert.deepEqual(retained(rejected.state), retained(initial.state));

    const preexisting = await page.evaluate(() => {
      const input = document.getElementById('viewer-high-quality');
      input.checked = false; input.dispatchEvent(new Event('change', { bubbles: true })); ModelViewer.renderProbe();
      // This error precedes the owned allocation boundary and must survive it.
      __qualityRejectedGL.enable(0xdeadbeef);
      input.checked = true; input.dispatchEvent(new Event('change', { bubbles: true }));
      const first = ModelViewer.renderProbe(33), state = ModelViewer.getState();
      const second = ModelViewer.renderProbe(33);
      return { first, second, state, rawError: __qualityRejectedGL.getError() };
    });
    assert.equal(preexisting.first.glError, 1280, 'The public viewer probe exposes a preexisting INVALID_ENUM');
    assert.equal(preexisting.second.glError, 0, 'A preserved unrelated flag is reported once');
    assert.equal(preexisting.rawError, 0);
    assert(preexisting.first.ready && preexisting.first.nonBackgroundSamples > 0);
    assert.equal(preexisting.state.quality.allocationFailures, 2);
    assert(preexisting.state.quality.externalErrorCount >= 1);
    assert.deepEqual(retained(preexisting.state), retained(initial.state));

    const sceneError = await page.evaluate(() => {
      const gl = __qualityRejectedGL;
      window.__qualityOriginalDraw = gl.drawElements;
      window.__qualityInjectedDraws = 0;
      gl.drawElements = function () {
        const result = window.__qualityOriginalDraw.apply(this, arguments);
        if (!window.__qualityInjectedDraws) {
          window.__qualityInjectedDraws += 1;
          // Generate a real unrelated flag during the model's GPU draw,
          // after optional target allocation has already failed and recovered.
          this.enable(0xdeadbeef);
        }
        return result;
      };
      const first = ModelViewer.renderProbe(33), state = ModelViewer.getState();
      const second = ModelViewer.renderProbe(33);
      gl.drawElements = window.__qualityOriginalDraw;
      return { first, second, state, rawError: gl.getError(), injectedDraws: __qualityInjectedDraws };
    });
    assert.equal(sceneError.injectedDraws, 1, 'An actual model draw generated the unrelated error');
    assert.equal(sceneError.first.glError, 1280, 'Fallback rendering must not hide a model-render INVALID_ENUM');
    assert.equal(sceneError.second.glError, 0, 'A scene-render flag is consumed once by the public probe');
    assert.equal(sceneError.rawError, 0);
    assert(sceneError.state.quality.externalErrorCount >= 2);
    assert.deepEqual(retained(sceneError.state), retained(initial.state));

    const recovered = await page.evaluate(() => {
      const gl = __qualityRejectedGL, input = document.getElementById('viewer-high-quality');
      gl.renderbufferStorageMultisample = window.__qualityOriginalStorage;
      input.checked = false; input.dispatchEvent(new Event('change', { bubbles: true }));
      const standard = ModelViewer.renderProbe(33);
      input.checked = true; input.dispatchEvent(new Event('change', { bubbles: true }));
      const high = ModelViewer.renderProbe(33);
      return { standard, high, state: ModelViewer.getState(), rawError: gl.getError() };
    });
    assert.equal(recovered.standard.glError, 0); assert.equal(recovered.high.glError, 0); assert.equal(recovered.rawError, 0);
    assert(recovered.high.ready && recovered.high.nonBackgroundSamples > 0);
    assert.equal(recovered.state.quality.mode, 'multisample'); assert(recovered.state.quality.targetAllocated);
    assert(recovered.state.quality.effectiveSamples >= 2);
    assert.deepEqual(recovered.state.quality.pendingGLErrors, []);
    assert.equal(recovered.state.quality.allocationFailures, 2, 'Successful reactivation introduces no new recovered failure');
    assert.deepEqual(retained(recovered.state), retained(initial.state));
    assert.equal(requests.length, 1, 'Allocation recovery must not reopen the original model');
    assert.deepEqual(errors, []);
    assert(!gpuMessages.some(message => /THREE.WebGLProgram/.test(message)), JSON.stringify(gpuMessages));
    await page.evaluate(() => ModelViewer.dispose());
    return { status: 'PASS', scope: 'Actual rejected WebGL2 allocation and unrelated real GL errors through the public viewer probe',
      initial, rejected, preexisting, sceneError, recovered, requests, errors, expectedGpuDiagnostics: gpuMessages };
  } finally { await context.close(); }
}

(async () => {
  const launch = { headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch);
  try {
    const targets = [];
    for (const forceWebGL1 of [false, true]) targets.push(await exercisePage(browser, forceWebGL1));
    targets.push(await exercisePage(browser, true, true));
    const stencil = await stencilProbe(browser);
    assert.equal(stencil.standard.state.contextSamples, 0, 'The dedicated stencil target starts without default-framebuffer AA');
    assert.equal(stencil.high.state.gameSamples, 2);
    assert.equal(stencil.high.state.requestedSamples, 2, 'Without stronger default AA, issue the original game two-sample request');
    assert(stencil.high.state.effectiveSamples >= 2);
    for (const frame of [stencil.standard, stencil.high]) {
      assert.equal(frame.glError, 0); assert(frame.center[1] > frame.center[0], JSON.stringify(frame));
      assert(frame.outside[0] > frame.outside[1], JSON.stringify(frame));
    }
    nearColor(stencil.high.center, stencil.standard.center, 'MSAA depth/stencil coverage');
    nearColor(stencil.high.outside, stencil.standard.outside, 'MSAA depth/stencil outside');
    const allocationFailure = await allocationFailureProbe(browser);
    const report = { status: 'PASS', scope: 'Generated rig/texture, real WebGL2 allocations and WebGL1 fallback; unmodified product UI and rendering', targets, stencil, allocationFailure };
    fs.writeFileSync(path.join(evidence, 'quality-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, targets: targets.map(target => target.target), stencil: 'PASS', allocationFailure: allocationFailure.status, evidence }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
