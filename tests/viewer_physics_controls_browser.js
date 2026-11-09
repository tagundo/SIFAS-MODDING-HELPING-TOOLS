/* Real Unity/HTTP controls, original-game default playback and size-linked limits. */
'use strict';
const assert = require('assert'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const {spawn, execFileSync} = require('child_process');
const {chromium} = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-physics-controls-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-physics-controls-library-'));
const source = path.join(library, 'extracted/3d_model/physics.unity');
fs.mkdirSync(path.dirname(source), {recursive: true}); fs.mkdirSync(evidence, {recursive: true});
execFileSync(python, ['-c', 'import runpy,sys;from pathlib import Path; m=runpy.run_path(sys.argv[1]);Path(sys.argv[2]).write_bytes(m["fixture_bytes"](native=True))', path.join(__dirname, 'generate_viewer_physics_fixture.py'), source], {cwd: repo});
const original = fs.readFileSync(source), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function show(locator) {
  await locator.evaluate(node => {for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;});
  await locator.scrollIntoViewIfNeeded(); return locator;
}
async function main() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const logs = fs.createWriteStream(path.join(evidence, 'server.log'));
  const server = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: repo, env: {...process.env, PYTHONPATH: [product, repo, process.env.PYTHONPATH || ''].join(path.delimiter), SUKUSTA_DIR: library}, stdio: ['ignore', 'pipe', 'pipe']});
  server.stdout.pipe(logs); server.stderr.pipe(logs); let browser;
  const report = {status: 'RUNNING', scope: 'Real product HTTP, neutral serialized Unity model, original game engine and actual DOM controls; source save/reopen, no whole-game parity claim'};
  try {
    const url = 'http://127.0.0.1:' + port;
    for (let n = 0; n < 150; n++) {try {if ((await fetch(url + '/api/tools')).ok) break;} catch (_) {} await wait(100);}
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
    const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), errors = [];
    page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.addInitScript(() => {
      localStorage.setItem('sifas_lang', 'ko');
      Object.defineProperty(window, 'ViewerPhysics', {configurable: true, set(api) {
        const create = api.create; api.create = function () {const controller = create.apply(this, arguments); window.__physicsControls = controller; return controller;};
        Object.defineProperty(window, 'ViewerPhysics', {configurable: true, writable: true, value: api});
      }});
    });
    await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    async function load() {
      await page.evaluate(source => {document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]);}, source);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().rig.physics.available);
    }
    await load();
    const physics = () => page.evaluate(() => ModelViewer.getState().rig.physics);
    const values = () => page.evaluate(() => {
      const metadata = ModelViewer.getEditingMetadata().physics, state = ModelViewer.getAuthoringState();
      return metadata.components.map(record => ({...record, values: {...record.values, ...((state.physics || []).find(edit => edit.id === record.id) || {}).values}}));
    });
    let state = await physics();
    assert(state.nativeAvailable && state.mode === 'game' && state.swingBone && state.swingCollider, 'Both source physics systems start enabled in original mode');
    assert(await page.locator('#viewer-physics-bones').isChecked()); assert(await page.locator('#viewer-physics-colliders').isChecked());
    report.initial = state;
    await page.evaluate(() => window.__physicsControls.restorePreviewState({...ModelViewer.getState().rig.physics, swingBone: false, swingCollider: false}));
    state = await physics(); assert(!state.swingBone && !state.swingCollider, 'Explicit off inspection state wins over new defaults');
    await page.evaluate(state => window.__physicsControls.restorePreviewState(state), report.initial);
    assert((await physics()).swingBone && (await physics()).swingCollider);
    const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
    await (await show(page.locator('#viewer-motion'))).selectOption(clip);
    await (await show(page.locator('#viewer-play'))).click();
    await page.waitForFunction(() => ModelViewer.getState().rig.physics.solver.totalNativeSteps >= 3);
    await page.locator('#viewer-play').click(); report.defaultPlayback = await physics();
    assert.deepStrictEqual(report.defaultPlayback.solver.unsupported, []);
    assert.equal(await page.locator('#viewer-physics-components').evaluate(node => node.closest('#viewer-adjustments') !== null), true);
    assert.equal(await page.locator('#viewer-thighs-card [data-physics-field]').count(), 0, 'Thigh physics moved out of the thigh card');
    assert.equal(await page.locator('[data-physics-component-editor]').count(), 3);
    assert.equal(await page.locator('[data-physics-field="dragForce"]').count(), 1, 'Each original field has one editor');
    await (await show(page.locator('#viewer-physics-component-kind'))).selectOption('collider');
    assert.equal(await page.locator('[data-physics-component-editor]:visible').count(), 2);
    await page.locator('#viewer-physics-component-group').selectOption('thighs');
    await page.locator('#viewer-physics-component-search').fill('not a source name');
    assert.equal(await page.locator('[data-physics-component-editor]:visible').count(), 0);
    await page.locator('#viewer-physics-component-search').fill('');
    assert.equal(await page.locator('[data-physics-component-editor]:visible').count(), 2);
    await (await show(page.locator('[data-physics-field="radius"]').first())).fill('0.06');
    assert((await values()).some(record => record.kind === 'collider' && record.values.radius === .06), 'The generic editor authors the selected original collider');
    await (await show(page.locator('#viewer-breast-preset'))).selectOption('nozomi');
    await (await show(page.locator('#viewer-physics-breast-auto'))).check();
    function breast(rows) {return rows.find(record => record.kind === 'bone' && record.group === 'breast').values;}
    let bone = breast(await values());
    assert.deepStrictEqual(bone.lowRotationLimit, [-30, -37, -37]); assert.deepStrictEqual(bone.highRotationLimit, [30, 37, 37]);
    await page.locator('#viewer-breast-preset').selectOption('rin');
    bone = breast(await values()); assert.deepStrictEqual(bone.lowRotationLimit, [-30, -31, -31]);
    await page.locator('#viewer-breast-preset').selectOption('nozomi');
    bone = breast(await values()); assert.deepStrictEqual(bone.lowRotationLimit, [-30, -37, -37], 'Repeated size changes never add the tier repeatedly');
    await page.locator('#viewer-physics-breast-auto').uncheck();
    bone = breast(await values()); assert.deepStrictEqual(bone.lowRotationLimit, [-30, -30, -30], 'Turning auto off restores the pre-auto limits');
    await page.locator('#viewer-physics-breast-auto').check();
    const retained = await page.evaluate(() => ({physics: window.__physicsControls.getState(), edits: window.__physicsControls.getEdits()}));
    await page.locator('#viewer-physics-breast-edit').click();
    assert.equal(await page.locator('#viewer-physics-component-kind').inputValue(), 'bone');
    assert.equal(await page.locator('#viewer-physics-component-group').inputValue(), 'breast');
    await page.locator('[data-physics-field="highRotationLimit"][data-physics-axis="0"]').fill('31');
    assert.equal(await page.locator('#viewer-physics-breast-auto').isChecked(), false, 'Manual limits take over from auto');
    await page.evaluate(retained => {window.__physicsControls.restore(retained.edits); window.__physicsControls.restorePreviewState(retained.physics);}, retained);
    assert.equal(await page.locator('#viewer-physics-breast-auto').isChecked(), true, 'Inspection restore keeps the auto policy and immutable baseline');
    await page.locator('#viewer-breast-preset').selectOption('rina');
    bone = breast(await values()); assert.deepStrictEqual(bone.lowRotationLimit, [-30, -30, -30], 'Zero tier is a valid recommendation');
    await page.locator('#viewer-breast-preset').selectOption('stock');
    assert.equal((await physics()).breastAutoLimits.tiers[0].applied, false, 'An unknown source character is not assigned a guessed stock tier');
    assert.deepStrictEqual(breast(await values()).lowRotationLimit, [-30, -30, -30]);
    await page.locator('#viewer-breast-preset').selectOption('nozomi');
    await (await show(page.locator('#viewer-physics-breast-preset'))).selectOption('firm');
    bone = breast(await values()); assert.equal(bone.dragForce, .5); assert.deepStrictEqual(bone.highRotationLimit, [30, 37, 37]);
    await page.locator('#viewer-physics-breast-edit').click();
    await page.locator('[data-physics-field="dragForce"]').fill('2');
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Size sync does not erase an invalid physics draft');
    await page.locator('[data-physics-field="dragForce"]').fill('0.4');
    assert.equal(await page.locator('#viewer-save').isEnabled(), true);
    report.auto = await physics(); report.values = await values();
    await page.screenshot({path: path.join(evidence, 'component-editor.png'), fullPage: true});
    await (await show(page.locator('#viewer-physics-breast-auto'))).scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(evidence, 'auto-breast-limits.png'), fullPage: true});
    await (await show(page.locator('#viewer-save'))).click();
    await page.waitForFunction(() => !document.getElementById('viewer-open-saved').hidden);
    assert.deepStrictEqual(fs.readFileSync(source), original);
    const folder = fs.readdirSync(path.join(library, 'modded/viewer')).find(name => name.startsWith('body-edit-'));
    const savedDir = path.join(library, 'modded/viewer', folder), recipe = JSON.parse(fs.readFileSync(path.join(savedDir, 'recipe.json'), 'utf8'));
    const limits = recipe.state.physics.find(edit => edit.values.lowRotationLimit);
    assert.deepStrictEqual(limits.values.lowRotationLimit, [-30, -37, -37]); assert.deepStrictEqual(limits.values.highRotationLimit, [30, 37, 37]);
    const savedPath = path.join(savedDir, 'models', path.basename(source));
    const reopened = JSON.parse(execFileSync(python, ['-c', 'import json,sys;from pathlib import Path;from webtools.core import model_edits,viewer_physics;print(json.dumps(viewer_physics.inspect_info(model_edits._inspect(Path(sys.argv[1]).read_bytes()),0,[])))', savedPath], {cwd: product, env: {...process.env, PYTHONPATH: [product, process.env.PYTHONPATH || ''].join(path.delimiter)}, encoding: 'utf8'}));
    assert.deepStrictEqual(breast(reopened).lowRotationLimit, [-30, -37, -37]);
    assert.deepStrictEqual(breast(reopened).highRotationLimit, [30, 37, 37]);
    assert(reopened.some(record => record.kind === 'collider' && Math.abs(record.values.radius - .06) < 1e-7));
    report.reopened = reopened;
    report.recipe = recipe.state;
    await page.screenshot({path: path.join(evidence, 'physics-controls.png'), fullPage: true});
    await page.evaluate(() => window.__physicsControls.restorePreviewState({...window.__physicsControls.getState(), swingBone: false, swingCollider: false}));
    await load(); state = await physics(); assert(state.swingBone && state.swingCollider, 'A genuinely new model load uses enabled defaults');
    assert.equal(state.breastAutoLimits.enabled, false, 'Authoring auto policy does not silently migrate to a different model session');
    assert.deepStrictEqual(errors, []); report.status = 'PASS'; report.evidence = evidence;
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({status: report.status, evidence, nativeSteps: report.defaultPlayback.solver.totalNativeSteps, savedLimits: limits.values}));
  } finally {if (browser) await browser.close(); server.kill(); logs.end();}
}
main().catch(error => {console.error(error); process.exitCode = 1;});
