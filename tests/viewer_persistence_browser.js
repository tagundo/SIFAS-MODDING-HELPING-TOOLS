/* Actual HTTP/Unity-bundle editing through the product viewer.
 * Uses original neutral serialized fixtures and an isolated temporary library.
 * No successful preparation, export, recipe restore or GLB response is mocked.
 * Run with VIEWER_PYTHON selecting a Python with the product dependencies. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');

const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-persistence-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-persistence-evidence-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', scope: 'Actual host Chromium DOM/WebGL and isolated product HTTP/serialized Unity output; no original SIFAS playback claim', cases: [] };
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const productFiles = ['webtools/server.py', 'webtools/core/model_edits.py', 'webtools/core/model_rig.py',
  'webtools/core/viewer_archive.py', 'webtools/i18n.py', 'webtools/web/index.html', 'webtools/web/static/style.css',
  'webtools/web/static/viewer-editing.js',
  'webtools/web/static/model-viewer.js', 'webtools/web/static/viewer-rig.js', 'webtools/web/static/viewer-persistence.js'];
function productHashes() { return Object.fromEntries(productFiles.map(name => [name, sha(fs.readFileSync(path.join(product, name)))])); }
report.productSourceSha256Before = productHashes();
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());

function fixtureCommand(args) {
  const result = spawnSync(python, [path.join(__dirname, 'inspect_viewer_persistence.py'), ...args],
    { cwd: product, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  assert.equal(result.status, 0, 'Serialized fixture inspection failed: ' + result.stderr);
  return JSON.parse(result.stdout);
}

async function startServer() {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: temporary }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error('Isolated product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* starting */ }
    await wait(100);
  }
  child.kill('SIGTERM'); throw new Error('Isolated product server did not become ready');
}

async function showAncestors(locator) {
  await locator.evaluate(element => {
    let parent = element.parentElement;
    while (parent) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
  });
  await locator.scrollIntoViewIfNeeded();
}

async function openPage(browser, url, viewport = { width: 448, height: 998 }, locale = 'ko') {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(lang => localStorage.setItem('sifas_lang', lang), locale);
  // Observe the real renderer without changing a model, camera or render order.
  await page.route('**/static/viewer-quality.js', async route => {
    const response = await route.fetch(), body = await response.text();
    await route.fulfill({ response, body: body + '\n(() => { const original = ViewerQuality.create; ViewerQuality.create = function() {' +
      'const controller=original.apply(this,arguments), render=controller.render; controller.render=function(scene,camera){' +
      'window.__persistentScene={scene,camera}; return render.apply(this,arguments);}; return controller;};})();' });
  });
  await page.goto(url);
  await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ModelViewer);
  await page.locator('.tab[data-tab="viewer"]').click();
  await showAncestors(page.locator('#viewer-auto-face'));
  await page.locator('#viewer-auto-face').uncheck();
  await page.locator('#viewer-file-options').evaluate(element => { element.open = false; });
  return { page, context, errors };
}

async function openModel(page, source) {
  await page.evaluate(source => openModelViewer([source]), source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !!window.__persistentScene);
  await page.waitForFunction(() => ModelViewer.getEditingMetadata && ModelViewer.getEditingMetadata().available);
  await frames(page);
}

async function selectBone(page, name) {
  const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
  const target = metadata.nodes.find(node => node.name === name);
  assert(target, 'Real serialized target is available: ' + name);
  const groupTab = page.locator(target.recommendedMethod === 'mesh' ? '#viewer-editor-mesh-tab' : '#viewer-editor-node-tab');
  if (await groupTab.count()) { await showAncestors(groupTab); await groupTab.click(); }
  await showAncestors(page.locator('#viewer-node'));
  await page.locator('#viewer-node').selectOption(String(target.node));
  return target;
}

async function setScale(page, name, values, method) {
  const target = await selectBone(page, name);
  for (let index = 0; index < 3; index++) {
    const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="' + 'XYZ'[index] + '"]');
    await input.fill(String(values[index])); await input.dispatchEvent('change');
  }
  if (method !== undefined) {
    await showAncestors(page.locator('#viewer-save-method'));
    await page.locator('#viewer-save-method').selectOption(method);
  }
  await frames(page);
  return target;
}

async function skinPoints(page) {
  await frames(page);
  return page.evaluate(() => {
    const result = [], scene = __persistentScene.scene;
    scene.updateMatrixWorld(true);
    scene.traverseVisible(mesh => {
      if (!mesh.isMesh || mesh.userData.viewerHelper || !mesh.geometry || !mesh.geometry.attributes.position) return;
      const positions = mesh.geometry.attributes.position;
      for (let index = 0; index < positions.count; index++) {
        const original = new THREE.Vector3().fromBufferAttribute(positions, index), point = original.clone();
        (mesh.geometry.morphAttributes.position || []).forEach((morph, channel) => {
          const amount = mesh.morphTargetInfluences && mesh.morphTargetInfluences[channel] || 0;
          const delta = new THREE.Vector3().fromBufferAttribute(morph, index);
          if (!mesh.geometry.morphTargetsRelative) delta.sub(original);
          point.addScaledVector(delta, amount);
        });
        if (mesh.isSkinnedMesh) mesh.boneTransform(index, point);
        point.applyMatrix4(mesh.matrixWorld); result.push(point.toArray());
      }
    });
    return result;
  });
}

function comparePoints(actual, expected, label) {
  assert.equal(actual.length, expected.length, label + ': same independent vertex count');
  let maximum = 0;
  actual.forEach((value, vertex) => value.forEach((axis, i) => { maximum = Math.max(maximum, Math.abs(axis - expected[vertex][i])); }));
  assert(maximum < 0.00003, label + ': saved skin matches authoring preview, maximum error=' + maximum);
  return maximum;
}

function maximumPointDifference(actual, expected) {
  assert.equal(actual.length, expected.length);
  return Math.max(...actual.flatMap((point, index) => point.map((axis, i) => Math.abs(axis - expected[index][i]))));
}

function scaleRecord(model, name) {
  return model.components.flatMap(component => component.entries).find(entry => entry.kind === 'scale' && entry.target === name);
}

async function semanticAuthoring(page) {
  return page.evaluate(() => {
    const value = JSON.parse(JSON.stringify(ModelViewer.getAuthoringState()));
    const metadata = ModelViewer.getEditingMetadata();
    value.edits.forEach(edit => {
      if (edit.method === 'auto') {
        const target = metadata.nodes.find(node => node.node === edit.node);
        edit.method = edit.compensate ? 'mesh' : target.recommendedMethod;
      }
      if (edit.compensationTargets) edit.compensationTargets.sort((a, b) => a - b);
    });
    value.edits.sort((a, b) => a.node - b.node);
    if (value.compensationReference) value.compensationReference.sort((a, b) => a.node - b.node);
    // Euler conversion and compensation can introduce floating point roundoff;
    // the separate vertex assertion checks the complete exported deformation.
    return JSON.parse(JSON.stringify(value, (_key, item) => typeof item === 'number' ? Math.round(item * 1e9) / 1e9 : item));
  });
}

async function save(page, delayRequest = false) {
  let requests = 0;
  const handler = async route => { requests++; if (delayRequest) await wait(700); await route.continue(); };
  await page.route('**/api/viewer/edit/export', handler);
  await showAncestors(page.locator('#viewer-save'));
  assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'Valid body edits can be saved');
  await page.locator('#viewer-save').click();
  if (delayRequest) {
    await page.waitForFunction(() => ModelViewer.getState().persistence.busy);
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Save disables duplicate submissions while busy');
    assert((await page.locator('#viewer-save-status').innerText()).trim(), 'Saving status is visible');
  }
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.outputPaths.length > 0);
  await page.unroute('**/api/viewer/edit/export', handler);
  const result = (await state(page)).persistence;
  assert.equal(requests, 1, 'One user save produces one export request');
  assert(!result.error, result.error);
  assert(result.recipePath && fs.existsSync(result.recipePath), 'A completed recipe is written');
  assert(result.previewPaths.length, 'A completed output can be reopened');
  return result;
}

async function basicPose(page) {
  await page.locator('#viewer-pose-basic').scrollIntoViewIfNeeded();
  await page.locator('#viewer-pose-basic').click(); await frames(page);
}

async function fullMorph(page) {
  await showAncestors(page.locator('#viewer-expression'));
  const channel = await page.locator('#viewer-expression').evaluate(element =>
    Array.from(element.options).find(option => option.value && !option.disabled).value);
  await page.locator('#viewer-expression').selectOption(channel);
  await page.locator('#viewer-expression-number').fill('100');
  await page.locator('#viewer-expression-number').dispatchEvent('change');
  return skinPoints(page);
}

async function posedAuthoringPoints(page) {
  await showAncestors(page.locator('#viewer-motion'));
  await page.locator('#viewer-motion').selectOption({ label: 'Neutral MV scale override' });
  await page.locator('#viewer-time').evaluate(element => { element.value = '.75'; element.dispatchEvent(new Event('input', { bubbles: true })); });
  await showAncestors(page.locator('#viewer-edit-evaluation'));
  await page.locator('#viewer-edit-evaluation').selectOption('authoring');
  return skinPoints(page);
}

async function importRecipe(page, recipePath, expectError = false) {
  await showAncestors(page.locator('#viewer-recipe-open'));
  await page.locator('#viewer-recipe-open').click();
  await page.waitForFunction(() => !document.getElementById('picker').classList.contains('hidden'));
  // Navigate through the same application function used by folder/root buttons;
  // the actual selection still goes through the normal picker click and API.
  await page.evaluate(directory => navigate(directory), path.dirname(recipePath));
  await page.waitForFunction(directory => document.getElementById('picker-crumb').textContent === directory, path.dirname(recipePath));
  await page.locator('#picker-entries li').filter({ hasText: path.basename(recipePath) }).click();
  await page.waitForFunction(() => document.getElementById('picker').classList.contains('hidden'));
  await page.waitForFunction(errorExpected => {
    const persistence = ModelViewer.getState().persistence;
    return !persistence.busy && (errorExpected ? !!persistence.error : persistence.status === 'restored');
  }, expectError);
}

async function hybridRoundTrip(page, source, label, variant = 'primary') {
  const selectedMember = variant === 'unmasked' ? 'alternate.unity' : 'primary.unity';
  const inspectArgs = file => [file, '--member', selectedMember];
  const original = fixtureCommand(inspectArgs(source));
  await openModel(page, source); await basicPose(page);
  if (variant === 'unmasked') {
    await showAncestors(page.locator('#viewer-variant-0'));
    await page.locator('#viewer-variant-0').selectOption('unmasked');
    await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().loadedArchiveVariants[0] === 'unmasked');
    await basicPose(page);
  }
  const thigh = await setScale(page, 'LeftUpLeg', [1.7, 1.1, 1.2]);
  const breast = await setScale(page, 'BreastSize', [1.08, 1.02, 1.03]);
  assert.equal(thigh.recommendedMethod, 'mesh', 'An observed MV-overridden thigh recommends mesh export');
  assert.equal(breast.recommendedMethod, 'node', 'A safe saved body node recommends NodeScaling');
  const authoring = await page.evaluate(() => ModelViewer.getAuthoringState());
  const semanticState = await semanticAuthoring(page);
  assert.deepEqual(authoring.unsupported || [], [], 'Supported edits have no hidden unsupported state');
  assert.equal(authoring.edits.length, 2);
  const expected = await skinPoints(page);
  assert(expected.length >= 6, 'Actual serialized skinned geometry is rendered');
  let expectedMorph = null;
  if (original.meshes.some(mesh => mesh.morphs.channels.length)) {
    expectedMorph = await fullMorph(page);
    await page.locator('#viewer-expression-reset').click();
    assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authoring,
      'Resetting a diagnostic morph leaves only the body authoring edits');
  }
  const initialCamera = (await state(page)).camera;

  // Real motion has a constant scale1 channel. Animation-order checking must
  // show that collision while the export still uses authoring values.
  await showAncestors(page.locator('#viewer-motion'));
  await page.locator('#viewer-motion').selectOption({ label: 'Neutral MV scale override' });
  await page.locator('#viewer-time').evaluate(element => { element.value = '.75'; element.dispatchEvent(new Event('input', { bubbles: true })); });
  await showAncestors(page.locator('#viewer-edit-evaluation'));
  await page.locator('#viewer-edit-evaluation').selectOption('animation');
  const checkAnimatedThigh = async () => {
    const animatedThigh = (await state(page)).rig.bones.find(bone => String(bone.node) === String(thigh.node));
    assert(animatedThigh, 'Actual thigh remains in the loaded rig');
    animatedThigh.scale.forEach(value => assert(Math.abs(value - 1) < .00001,
      'Animation-order preview exposes scale1 even when PropertyMixer skips an unchanged constant'));
  };
  await checkAnimatedThigh();
  for (let index = 0; index < 4; index++) { await frames(page); await checkAnimatedThigh(); }
  await page.locator('#viewer-time').evaluate(element => { element.value = '1.2'; element.dispatchEvent(new Event('input', { bubbles: true })); });
  await checkAnimatedThigh();
  await page.locator('#viewer-play').click(); await wait(120); await checkAnimatedThigh();
  await page.locator('#viewer-play').click();
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authoring, 'Changing playback never changes export values');
  const posedBefore = label === 'mixed-weight-model' ? await posedAuthoringPoints(page) : null;
  const first = await save(page, true);
  assert.deepEqual((await state(page)).camera, initialCamera, 'Saving preserves the camera');
  assert.equal(sha(fs.readFileSync(source)), original.file_sha256, 'Original input bytes survive saving');
  const outputPath = first.previewPaths[0], output = fixtureCommand(inspectArgs(outputPath));
  assert.notEqual(output.model_sha256, original.model_sha256, 'A real modified Unity model was produced');
  assert.deepEqual(output.transforms, original.transforms, 'Skeleton local transforms are retained');
  assert.deepEqual(output.meshes.map(mesh => mesh.bind_pose_sha256), original.meshes.map(mesh => mesh.bind_pose_sha256), 'Bind poses are retained');
  const savedBreast = scaleRecord(output, 'BreastSize');
  assert(savedBreast, 'Node route adds an actual saved scale record');
  savedBreast.scaled.forEach((value, i) => assert(Math.abs(value - [1.08, 1.02, 1.03][i]) < .00001));
  const unchangedTypes = new Set(['Transform', 'AnimationClip', 'Material', 'Texture2D', 'Shader', 'MonoScript', 'GameObject']);
  for (const object of original.objects.filter(item => unchangedTypes.has(item.type))) {
    assert.equal(output.objects.find(item => item.id === object.id).sha256, object.sha256, 'Unedited serialized object remains exact: ' + object.type + '/' + object.id);
  }
  if (original.archive_entries) {
    assert.deepEqual(Object.keys(output.archive_entries).sort(), Object.keys(original.archive_entries).sort(), 'ZIP retains every original entry');
    for (const [name, value] of Object.entries(original.archive_entries)) {
      if (name !== selectedMember) assert.deepEqual(output.archive_entries[name], value, 'Unselected ZIP companion stays exact: ' + name);
    }
  }

  await showAncestors(page.locator('#viewer-open-saved'));
  await page.locator('#viewer-open-saved').click();
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
  if (original.archive_entries) assert.deepEqual((await state(page)).loadedArchiveVariants, [variant], 'Saved-result review retains the selected costume alternative');
  assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Saved-result review cannot accidentally bake an already baked input');
  const posedDifference = posedBefore ? maximumPointDifference(await posedAuthoringPoints(page), posedBefore) : null;
  await basicPose(page);
  const maximumError = comparePoints(await skinPoints(page), expected, label + ' output reload');
  let maximumMorphError = null;
  if (expectedMorph) {
    maximumMorphError = comparePoints(await fullMorph(page), expectedMorph, label + ' baked morph reload');
    await page.locator('#viewer-expression-reset').click();
  }
  await showAncestors(page.locator('#viewer-reedit-original'));
  await page.locator('#viewer-reedit-original').click();
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading &&
    !ModelViewer.getState().persistence.reviewingSaved && !ModelViewer.getState().persistence.busy &&
    ModelViewer.getAuthoringState().edits.length === 2);
  if (original.archive_entries) assert.deepEqual((await state(page)).loadedArchiveVariants, [variant], 'Re-editing original retains the selected costume alternative');
  assert.deepEqual(await semanticAuthoring(page), semanticState,
    'Return to original restores the authoring values and resolved save methods');
  const second = await save(page);
  assert.notEqual(second.previewPaths[0], outputPath, 'Saving again creates a new completed copy');
  assert.equal(sha(fs.readFileSync(second.previewPaths[0])), sha(fs.readFileSync(outputPath)), 'Same original plus same recipe does not accumulate a second bake');
  assert.equal(sha(fs.readFileSync(source)), original.file_sha256, 'Original remains exact after recipe rebuild');
  await showAncestors(page.locator('#viewer-preview-reset'));
  await page.locator('#viewer-preview-reset').click();
  assert.equal((await page.evaluate(() => ModelViewer.getAuthoringState())).edits.length, 0);
  await importRecipe(page, first.recipePath);
  assert.deepEqual(await semanticAuthoring(page), semanticState, 'A recipe selected from disk restores the body values');
  return { label, sourceSha256: original.file_sha256, outputSha256: output.file_sha256,
    maximumReloadVertexError: maximumError, maximumMorphError,
    posedMeshVsAuthoringMaximumDifference: posedDifference,
    posedDifferenceScope: posedBefore ? 'Measured without assuming bone-TRS authoring and rest-baked mixed-weight animation are identical' : null,
    originalUnchanged: true, repeatExportByteIdentical: true,
    recipe: first.recipePath, nodeTarget: breast.node, meshTarget: thigh.node,
    archiveCompanionsUnchanged: !!original.archive_entries, selectedVariant: variant };
}

async function compensatedProfileRoundTrip(page, source) {
  await openModel(page, source); await basicPose(page);
  await showAncestors(page.locator('#viewer-breast-preset'));
  await page.locator('#viewer-breast-preset').selectOption('nozomi');
  await setScale(page, 'LeftUpLeg', [1.5, 1.1, 1.1]);
  await showAncestors(page.locator('#bone-compensate-children'));
  await page.locator('#bone-compensate-children').check();
  const originalState = await page.evaluate(() => ModelViewer.getAuthoringState());
  const semanticState = await semanticAuthoring(page);
  assert(originalState.edits.some(edit => edit.compensate), 'Exercise an actual compensated parent');
  assert(originalState.compensationReference && originalState.compensationReference.length,
    'The selected body profile supplies a recorded static compensation reference');
  const expected = await skinPoints(page);
  const first = await save(page);
  await showAncestors(page.locator('#viewer-open-saved'));
  await page.locator('#viewer-open-saved').click();
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
  await basicPose(page);
  const maximumError = comparePoints(await skinPoints(page), expected, 'Profile and child compensation output reload');
  await showAncestors(page.locator('#viewer-reedit-original'));
  await page.locator('#viewer-reedit-original').click();
  await page.waitForFunction(() => !ModelViewer.getState().loading && !ModelViewer.getState().persistence.busy &&
    ModelViewer.getAuthoringState().edits.some(edit => edit.compensate));
  assert.deepEqual(await semanticAuthoring(page), semanticState,
    'Restored profile reference and compensation recipe remain exact');
  comparePoints(await skinPoints(page), expected, 'Restored compensated recipe preview');
  const second = await save(page);
  assert.equal(sha(fs.readFileSync(first.previewPaths[0])), sha(fs.readFileSync(second.previewPaths[0])),
    'Profile plus compensation rebuild does not accumulate or change its frame');
  return { label: 'body-profile-child-compensation', maximumReloadVertexError: maximumError,
    sameRecipeGeometry: true, repeatExportByteIdentical: true };
}

async function fractionalFileValues(page, source) {
  const original = fixtureCommand([source]);
  await openModel(page, source); await basicPose(page);
  await showAncestors(page.locator('#viewer-breast-preset'));
  await page.locator('#viewer-breast-preset').selectOption('nozomi');
  await setScale(page, 'LeftUpLeg', [1.55, 1.234567, 1.1]);
  const offGrid = await page.locator('#viewer-node-fields input').evaluateAll(inputs =>
    inputs.filter(input => input.validity.stepMismatch).map(input => ({ kind: input.dataset.viewerNodeKind,
      axis: input.dataset.axis, value: input.value, step: input.step })));
  assert(offGrid.some(input => input.kind === 'position') && offGrid.some(input => input.kind === 'rotation'),
    'The actual authored fractional position and rotation stay visible, without rounding to spinner steps');
  assert(offGrid.some(input => input.kind === 'scale' && input.value === '1.234567'),
    'Explicit finite scale edits may use precision finer than the spinner increment');
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState().unsupported), [],
    'Fractional original TRS and precise body edits are valid authoring values');
  assert.equal(await page.locator('input[data-viewer-node-kind="scale"][data-axis="Y"]').getAttribute('step'), '0.001');
  assert.equal(await page.locator('input[data-viewer-node-kind="rotation"][data-axis="X"]').getAttribute('step'), '1');
  const expected = await skinPoints(page);
  const first = await save(page);
  const serialized = fixtureCommand([first.previewPaths[0]]);
  const before = original.transforms.find(node => node.name === 'LeftUpLeg');
  const after = serialized.transforms.find(node => node.name === 'LeftUpLeg');
  assert.deepEqual(after.position, before.position, 'Untouched original position floats remain exact');
  assert.deepEqual(after.rotation, before.rotation, 'Untouched original quaternion floats remain exact');
  assert.equal(sha(fs.readFileSync(source)), original.file_sha256, 'ZIP source bytes are unchanged');
  assert.equal(serialized.archive_entries['notes.txt'].sha256, original.archive_entries['notes.txt'].sha256);
  await showAncestors(page.locator('#viewer-open-saved')); await page.locator('#viewer-open-saved').click();
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
  await basicPose(page);
  const maximumError = comparePoints(await skinPoints(page), expected, 'Fractional-file hybrid output reload');
  await showAncestors(page.locator('#viewer-reedit-original')); await page.locator('#viewer-reedit-original').click();
  await page.waitForFunction(() => !ModelViewer.getState().loading && !ModelViewer.getState().persistence.busy &&
    ModelViewer.getAuthoringState().edits.length > 0 && !ModelViewer.getState().persistence.reviewingSaved);
  await selectBone(page, 'LeftUpLeg');
  const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="Y"]');
  for (const value of ['', '0', '1000001', '-1000001']) {
    await input.fill(value);
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Actual invalid input still blocks saving: ' + JSON.stringify(value));
    assert((await page.evaluate(() => ModelViewer.getAuthoringState())).unsupported.includes('Correct the invalid editing values before saving.'));
    await input.fill('1.234567'); await input.dispatchEvent('change');
    assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'Recovering a valid precise value re-enables saving');
  }
  const second = await save(page);
  assert.equal(sha(fs.readFileSync(first.previewPaths[0])), sha(fs.readFileSync(second.previewPaths[0])),
    'Re-editing the exact original and recipe preserves fractional file data without accumulating changes');
  return { label: 'fractional-ZIP-breast-and-thigh-save', spinnerIncrementsPreserved: true,
    authoredPositionAndQuaternionPreserved: true, fineScalePrecisionAccepted: true,
    invalidFiniteRangeAndNonzeroValidationRetained: true, maximumReloadVertexError: maximumError,
    repeatExportByteIdentical: true, offGridInputs: offGrid };
}

async function rejectionCases(page, source) {
  await openModel(page, source); await basicPose(page);
  await setScale(page, 'LeftUpLeg', [1.7, 1.1, 1.2]);
  const before = await page.evaluate(() => ModelViewer.getAuthoringState());
  await selectBone(page, 'LeftUpLeg');
  const input = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]');
  await input.fill('0');
  assert((await page.evaluate(() => ModelViewer.getAuthoringState())).unsupported.length,
    'Invalid live form input cannot silently export the last valid value');
  await showAncestors(page.locator('#viewer-save'));
  assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Invalid values block saving');
  await showAncestors(input); await input.fill('1.7'); await input.dispatchEvent('change');
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), before);
  await showAncestors(page.locator('#viewer-saved-nodes'));
  await page.locator('#viewer-saved-nodes').uncheck();
  assert((await page.evaluate(() => ModelViewer.getAuthoringState())).unsupported.length,
    'Disabling saved settings is not silently persisted as an unrelated body change');
  await page.locator('#viewer-saved-nodes').check();
  const badRecipe = path.join(path.dirname(source), 'invalid-body-recipe.json');
  fs.writeFileSync(badRecipe, '{ not valid JSON');
  await importRecipe(page, badRecipe, true);
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), before, 'Invalid recipe import retains the edits');

  // Alter only this isolated fixture after its preparation. The live source
  // binding must reject it without a result copy or loss of authoring state.
  const bytes = fs.readFileSync(source), hashBefore = sha(bytes);
  const previousOutputs = (await state(page)).persistence.outputPaths.slice();
  const previousError = (await state(page)).persistence.error;
  fs.appendFileSync(source, Buffer.from([0]));
  try {
    await showAncestors(page.locator('#viewer-save'));
    await page.locator('#viewer-save').click();
    await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && !!ModelViewer.getState().persistence.error);
    assert.notEqual((await state(page)).persistence.error, previousError, 'The stale-source failure replaces the earlier recipe error');
    assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), before, 'Failed export retains the edits');
    assert.deepEqual((await state(page)).persistence.outputPaths, previousOutputs,
      'Stale source publishes no new result and retains previously completed outputs');
    assert((await page.locator('#viewer-save-status').innerText()).trim(), 'A failed export is explained in the UI');
  } finally { fs.writeFileSync(source, bytes); }
  assert.equal(sha(fs.readFileSync(source)), hashBefore);
  return { label: 'invalid-input-disabled-settings-stale-source', originalRestored: true,
    editsPreservedOnFailure: true, noPublishedResult: true };
}

async function separateEditorGroups(page, source) {
  await openModel(page, source); await basicPose(page);
  assert.equal(await page.locator('#viewer-editor-node-tab').count(), 1, 'NodeScaling has its own workspace tab');
  assert.equal(await page.locator('#viewer-editor-mesh-tab').count(), 1, 'MeshBaker has its own workspace tab');
  const thigh = await setScale(page, 'LeftUpLeg', [1.55, 1.2, 1.1]);
  const breast = await setScale(page, 'BreastSize', [1.13, 1.07, 1.05]);
  const authored = await page.evaluate(() => ModelViewer.getAuthoringState()), camera = (await state(page)).camera;
  assert.equal(authored.edits.find(edit => edit.node === thigh.node).method, 'mesh', 'Editing in MeshBaker records mesh processing');
  assert.equal(authored.edits.find(edit => edit.node === breast.node).method, 'node', 'Editing in NodeScaling records node processing');
  const expected = await skinPoints(page), stageHeight = await page.locator('#viewer-stage').evaluate(element => element.getBoundingClientRect().height);
  for (const group of ['mesh', 'node', 'mesh', 'node']) {
    const tab = page.locator('#viewer-editor-' + group + '-tab'); await showAncestors(tab); await tab.click();
    assert.equal(await tab.getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#viewer-editor-' + group + '-panel').isVisible(), true);
    assert.equal(await page.locator('#viewer-editor-' + (group === 'mesh' ? 'node' : 'mesh') + '-panel').isVisible(), false);
    assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored, 'Switching editing areas never moves or rewrites existing edits');
    assert.deepEqual((await state(page)).camera, camera, 'Changing editing areas preserves camera');
    comparePoints(await skinPoints(page), expected, 'Group switching retains edited geometry');
    assert.equal(await page.locator('#viewer-stage').evaluate(element => element.getBoundingClientRect().height), stageHeight,
      'Editing areas do not reduce the canvas height');
    const options = await page.locator('#viewer-node').evaluate(element => Array.from(element.options, option => option.value));
    assert(options.includes(String(group === 'mesh' ? thigh.node : breast.node)), 'Active area offers its recommended bone');
    assert(!options.includes(String(group === 'mesh' ? breast.node : thigh.node)), 'Default area filter separates the other tool’s bones');
  }
  await page.locator('#viewer-node-filter').selectOption('all');
  await page.locator('#viewer-node').selectOption(String(thigh.node));
  assert.equal(await page.locator('#viewer-save-method').inputValue(), 'mesh', 'Advanced cross-group selection still shows its existing mesh route');
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored);
  return { label: 'separate-node-and-mesh-editing-areas', tabSwitchPreservesEdits: true,
    recommendedBoneFilters: true, explicitRouteVisibleAcrossGroups: true, canvasHeightUnchanged: true };
}

async function convertExistingNodeScale(page, source) {
  const original = fixtureCommand([source]);
  await openModel(page, source); await basicPose(page);
  await showAncestors(page.locator('#viewer-preview-reset'));
  await page.locator('#viewer-preview-reset').click();
  const target = await selectBone(page, 'LeftUpLeg');
  assert.equal((await page.evaluate(() => ModelViewer.getAuthoringState())).edits.length, 0);
  const expected = await skinPoints(page);
  await page.locator('#viewer-save-method').selectOption('mesh');
  const authored = await page.evaluate(() => ModelViewer.getAuthoringState());
  assert.equal(authored.edits.length, 1, 'Choosing Mesh explicitly records conversion without slider fidgeting');
  assert.equal(authored.edits[0].node, target.node); assert.equal(authored.edits[0].method, 'mesh');
  authored.edits[0].scale.forEach((value, i) => assert(Math.abs(value - [1.3, .9, 1][i]) < .00001));
  const first = await save(page);
  const saved = fixtureCommand([first.previewPaths[0]]);
  assert.notDeepEqual(saved.meshes[0].positions, original.meshes[0].positions, 'Saved node shape is actually baked into vertices');
  const record = scaleRecord(saved, 'LeftUpLeg');
  record.scaled.forEach(value => assert(Math.abs(value - 1) < .00001, 'Migrated saved scale does not apply a second time'));
  await showAncestors(page.locator('#viewer-open-saved')); await page.locator('#viewer-open-saved').click();
  await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
  await basicPose(page); comparePoints(await skinPoints(page), expected, 'Method-only conversion keeps current saved body shape');
  await showAncestors(page.locator('#viewer-reedit-original')); await page.locator('#viewer-reedit-original').click();
  await page.waitForFunction(() => !ModelViewer.getState().loading && !ModelViewer.getState().persistence.busy && ModelViewer.getAuthoringState().edits.length === 1);
  assert.equal((await page.evaluate(() => ModelViewer.getAuthoringState())).edits[0].method, 'mesh', 'Recipe retains method-only conversion intent');
  const second = await save(page);
  assert.equal(sha(fs.readFileSync(first.previewPaths[0])), sha(fs.readFileSync(second.previewPaths[0])));
  return { label: 'convert-saved-node-scale-without-changing-slider', preservedShape: true,
    actualVertexBake: true, nodeOverrideNeutralized: true, repeatExportByteIdentical: true };
}

async function previewOnlyInspectionSave(page, source) {
  const original = fixtureCommand([source]);
  await openModel(page, source); await basicPose(page);
  await showAncestors(page.locator('#viewer-preview-reset')); await page.locator('#viewer-preview-reset').click();
  await setScale(page, 'LeftUpLeg', [1.43, 1.17, 1.06]);
  const authored = await page.evaluate(() => ModelViewer.getAuthoringState());
  await fullMorph(page);
  await showAncestors(page.locator('#viewer-parts input[type="checkbox"]'));
  await page.locator('#viewer-parts input[type="checkbox"]').first().uncheck();
  assert.deepEqual(await page.evaluate(() => ModelViewer.getAuthoringState()), authored,
    'Expression and visibility inspection are not body edits');
  const result = await save(page), output = fixtureCommand([result.previewPaths[0]]);
  assert.deepEqual(output.renderers, original.renderers,
    'Preview-only morph weights and hidden parts do not overwrite original serialized defaults');
  assert.equal(sha(fs.readFileSync(source)), original.file_sha256);
  return { label: 'save-body-with-expression-and-visibility-inspection', bodySaveAllowed: true,
    serializedMorphAndVisibilityDefaultsUnchanged: true, sourceUnchanged: true };
}

async function reachable(page, selector) {
  const control = page.locator(selector); await showAncestors(control);
  return control.evaluate(element => {
    const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { selector: element.id, visible: !!element.getClientRects().length, hit: hit === element || element.contains(hit),
      width: r.width, height: r.height, left: r.left, right: r.right, viewportWidth: innerWidth };
  });
}

(async () => {
  let server, browser;
  try {
    const versions = spawnSync(python, ['-c', 'import json,sys,UnityPy,numpy,PIL;print(json.dumps({"python":sys.version.split()[0],"UnityPy":UnityPy.__version__,"numpy":numpy.__version__,"Pillow":PIL.__version__}))'],
      { cwd: product, encoding: 'utf8' });
    assert.equal(versions.status, 0, versions.stderr); report.dependencies = JSON.parse(versions.stdout);
    const fixtures = fixtureCommand([temporary, '--setup']);
    server = await startServer();
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined),
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const { page, context, errors } = await openPage(browser, server.url);
    const selectedCases = process.env.PERSISTENCE_CASES ? process.env.PERSISTENCE_CASES.split(',') : null;
    const knownGroups = ['groups', 'raw', 'zip', 'unmasked', 'morph', 'mixed', 'compensation', 'conversion', 'inspection', 'precision', 'rejections', 'layout'];
    assert(!selectedCases || selectedCases.every(name => knownGroups.includes(name)), 'Choose known persistence case groups');
    report.selectedCaseGroups = selectedCases;
    const enabled = name => !selectedCases || selectedCases.includes(name);
    async function run(name, fn) { if (enabled(name)) report.cases.push(await fn()); }
    await run('groups', () => separateEditorGroups(page, fixtures.raw));
    await run('raw', () => hybridRoundTrip(page, fixtures.raw, 'raw-model'));
    await run('zip', () => hybridRoundTrip(page, fixtures.archive, 'selected-ZIP-variant'));
    await run('unmasked', () => hybridRoundTrip(page, fixtures.editable_archive, 'unmasked-ZIP-variant', 'unmasked'));
    await run('morph', () => hybridRoundTrip(page, fixtures.morph, 'morph-model'));
    await run('mixed', () => hybridRoundTrip(page, fixtures.mixed, 'mixed-weight-model'));
    await run('compensation', () => compensatedProfileRoundTrip(page, fixtures.raw));
    await run('conversion', () => convertExistingNodeScale(page, fixtures.raw));
    await run('inspection', () => previewOnlyInspectionSave(page, fixtures.morph));
    await run('precision', () => fractionalFileValues(page, fixtures.fractional_archive));
    await run('rejections', () => rejectionCases(page, fixtures.stale));
    assert.deepEqual(errors, [], 'Successful persistence flows do not cause page errors');
    await context.close();

    for (const profile of (enabled('layout') ? [
      { width: 448, height: 998, locale: 'ko', font: 100 },
      { width: 768, height: 900, locale: 'en', font: 100 },
      { width: 998, height: 448, locale: 'ja', font: 100 },
      { width: 360, height: 800, locale: 'ko', font: 200 }
    ] : [])) {
      const opened = await openPage(browser, server.url, { width: profile.width, height: profile.height }, profile.locale);
      await openModel(opened.page, fixtures.raw);
      await setScale(opened.page, 'LeftUpLeg', [1.6, 1.2, 1.1]);
      await opened.page.evaluate(percent => { document.documentElement.style.fontSize = percent + '%'; }, profile.font);
      const controls = [];
      for (const selector of ['#viewer-editor-node-tab', '#viewer-editor-mesh-tab', '#viewer-save', '#viewer-recipe-open', '#viewer-save-method', '#viewer-edit-evaluation']) {
        const value = await reachable(opened.page, selector);
        assert(value.visible && value.hit && value.left >= -1 && value.right <= value.viewportWidth + 1,
          'Persistence control remains reachable: ' + JSON.stringify({ profile, value }));
        controls.push(value);
      }
      assert.equal(await opened.page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'No horizontal overflow');
      await opened.page.screenshot({ path: path.join(evidence, 'persistence-' + profile.width + 'x' + profile.height + '-' + profile.font + '.png'), fullPage: true });
      assert.deepEqual(opened.errors, []); report.cases.push({ label: 'layout', profile, controls });
      await opened.context.close();
    }
    if (!selectedCases) assert.equal(report.cases.length, 15, 'The full suite runs every persistence and layout case');
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.stack || String(error);
    if (error.actual !== undefined) report.assertionActual = error.actual;
    if (error.expected !== undefined) report.assertionExpected = error.expected;
    try {
      const lastPage = browser && browser.contexts().flatMap(context => context.pages()).slice(-1)[0];
      if (lastPage) {
        report.failureState = await state(lastPage);
        report.failureAuthoring = await lastPage.evaluate(() => ModelViewer.getAuthoringState());
        await lastPage.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true });
      }
    } catch (_) { /* Retain the original assertion if diagnostics cannot run. */ }
    throw error;
  } finally {
    report.productSourceSha256After = productHashes();
    report.productSourcesUnchangedDuringRun = JSON.stringify(report.productSourceSha256Before) === JSON.stringify(report.productSourceSha256After);
    if (report.status === 'PASS' && !report.productSourcesUnchangedDuringRun) report.status = 'PASS_EXPLORATORY_SOURCES_CHANGED';
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    if (browser) await browser.close();
    if (server) {
      if (server.child.exitCode === null) {
        const stopped = new Promise(resolve => server.child.once('exit', resolve));
        server.child.kill('SIGTERM'); await Promise.race([stopped, wait(1500)]);
      }
      server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end();
    }
    if (!process.env.KEEP_VIEWER_PERSISTENCE_FIXTURES) fs.rmSync(temporary, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ status: report.status, cases: report.cases.length, report: path.join(evidence, 'report.json') }));
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
