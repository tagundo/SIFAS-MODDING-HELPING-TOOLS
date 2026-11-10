/* Actual Unity/HTTP viewer lifecycle; delegates every observed physics call. */
'use strict';
const assert = require('assert'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-physics-lifecycle-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-physics-lifecycle-library-')), source = path.join(library, 'extracted/3d_model/physics.unity');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
execFileSync(python, ['-c', 'import runpy,sys; from pathlib import Path; module=runpy.run_path(sys.argv[1]); Path(sys.argv[2]).write_bytes(module["fixture_bytes"](native=True,animated_dyna=True))', path.join(__dirname, 'generate_viewer_physics_fixture.py'), source], { cwd: repo });
const rawBank = path.join(path.dirname(source), 'additional-motion.unity'), gameBank = path.join(path.dirname(source), 'game-motion.unity');
execFileSync(python, ['-c', `import sys,UnityPy
from pathlib import Path
for destination,name in zip(sys.argv[2:],['Reload manual motion','Reload game motion']):
 env=UnityPy.load(sys.argv[1])
 for obj in list(env.objects):
  if obj.type.name!='AnimationClip': del obj.assets_file.objects[obj.path_id]
  else:
   tree=obj.read_typetree();tree['m_Name']=name;obj.save_typetree(tree)
 Path(destination).write_bytes(env.file.save())
`, source, rawBank, gameBank], {cwd: repo});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function show(locator) { await locator.evaluate(node => { for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
async function boot() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo,
    env: { ...process.env, PYTHONPATH: [product, repo, process.env.PYTHONPATH || ''].join(path.delimiter), SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 150; n++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await wait(100); }
  throw new Error('Product server did not become ready');
}
const events = page => page.evaluate(() => window.__physicsEvents.slice());
const clear = page => page.evaluate(() => { window.__physicsEvents = []; });
async function seek(page, time) { await page.locator('#viewer-time').evaluate((node, time) => { node.value = String(time); node.dispatchEvent(new Event('input', { bubbles: true })); }, time); }
function authoringResets(values) { return values.filter(value => value.method === 'resetSimulation' && value.reason.startsWith('rig:authoring:')); }
async function run() {
  const report = { status: 'RUNNING', scope: 'Real generated serialized SwingBone model and product HTTP/WebGL/UI; observing wrappers delegate every production controller call. Verifies frontend lifecycle, not native game numerical parity.', cases: [] };
  let server, browser;
  try {
    server = await boot(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }); page.setDefaultTimeout(30000);
    await page.route('**/static/viewer-game-physics.js', async route => {
      const response = await route.fetch(), source = await response.text();
      assert.equal(source.split('refreshInputs();').length, 2, 'A single native input boundary is instrumented for observation');
      await route.fulfill({response, body: source.replace('refreshInputs();', `refreshInputs();
        global.__nativeInputFrames.push({time:context.time,clipId:context.clipId,inputs:entries.map(function(entry){return {node:String(entry.record.node),child:String(entry.record.simulation.childNode),rotation:buffers[entry.index].localRotation.slice(),childPosition:entry.child.position.toArray()};})});`)});
    });
    const errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); let prepared;
    page.on('response', async response => { if (response.url().endsWith('/api/viewer/prepare') && response.ok()) prepared = await response.json(); });
    await page.addInitScript(() => {
      localStorage.setItem('sifas_lang', 'en'); window.__physicsEvents = []; window.__nativeInputFrames = [];
      Object.defineProperty(window, 'ViewerRig', { configurable: true, set(api) {
        const create = api.create;
        api.create = function () { window.__lifecycleRoot = arguments[0]; const rig = create.apply(this, arguments); window.__lifecycleRig = rig; return rig; };
        Object.defineProperty(window, 'ViewerRig', { configurable: true, writable: true, value: api });
      } });
      Object.defineProperty(window, 'ViewerPhysics', { configurable: true, set(api) {
        const create = api.create; api.create = function () {
          window.__getPhysicsInitializationPose = arguments[2].getInitializationPose;
          const controller = create.apply(this, arguments);
          for (const method of ['captureAnimationPose', 'resetSimulation', 'apply']) {
            const original = controller[method]; if (typeof original !== 'function') throw new Error('Production physics lifecycle method is missing: ' + method);
            controller[method] = function (value) {
              const pose = {};
              if (method === 'captureAnimationPose') window.__lifecycleRoot.traverse(node => {if (node.userData && node.userData.elichika_node !== undefined) pose[String(node.userData.elichika_node)] = {quaternion:node.quaternion.toArray(),position:node.position.toArray()};});
              window.__physicsEvents.push(method === 'captureAnimationPose' ? { method, context: { ...value }, pose } : method === 'resetSimulation' ? { method, reason: value } : { method, delta: value });
              return original.apply(this, arguments);
            };
          }
          return controller;
        };
        Object.defineProperty(window, 'ViewerPhysics', { configurable: true, writable: true, value: api });
      } });
    });
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().rig.physics.available);
    assert.equal(await page.evaluate(() => ModelViewer.getState().rig.physics.mode), 'game', 'The real native-metadata fixture uses the production game engine, not the enhanced fallback');
    assert.equal(await page.evaluate(() => ModelViewer.getState().rig.physics.frameRate), 0, 'Fresh original physics follows the display refresh rate');
    assert.equal(await page.evaluate(() => ModelViewer.getState().rig.physics.swingBone && ModelViewer.getState().rig.physics.swingCollider), true, 'Original SwingBone and Collider are enabled on a fresh model');
    assert(prepared && prepared.rig.clips.length, 'Actual source has exported motion metadata');
    const clip = prepared.rig.clips.find(value => value.userSelected !== false), rawName = clip.name;
    const initializationPose = await page.evaluate(() => window.__getPhysicsInitializationPose());
    assert(Object.keys(initializationPose).length >= 4, 'Every mapped rig node has a detached source initialization transform');
    await (await show(page.locator('#viewer-physics-bones'))).check();
    await clear(page); await (await show(page.locator('#viewer-motion'))).selectOption(rawName);
    let trace = await events(page); assert(trace.some(value => value.method === 'resetSimulation' && value.reason === 'rig:clip-change'));
    await clear(page); await page.locator('#viewer-play').click(); await page.waitForFunction(() => ModelViewer.getMotionState().rig.time > .2); await page.locator('#viewer-play').click();
    trace = await events(page); const advancing = trace.filter(value => value.method === 'captureAnimationPose' && value.context.advancing);
    assert(advancing.length > 1 && advancing.every(value => value.context.clipId === rawName)); assert(trace.filter(value => value.method === 'apply' && value.delta > 0).length > 1);
    assert(!authoringResets(trace).length, 'Ordinary motion advancement never reinitializes the authored baseline');
    trace.forEach((value, index) => { if (value.method === 'apply') assert.equal(trace[index - 1].method, 'captureAnimationPose', 'Every physics apply receives the completed kinematic pose first'); });
    const rawSolver = await page.evaluate(() => ModelViewer.getState().rig.physics.solver);
    assert(rawSolver.initialized && rawSolver.available && rawSolver.totalNativeSteps > 1, 'The native single job really advances, with all required source inputs available');
    assert.deepStrictEqual(rawSolver.unsupported, []);
    const nativeFrames = await page.evaluate(() => window.__nativeInputFrames.slice());
    let directlyAnimatedFrames = 0, changedDyna = false;
    for (const frame of nativeFrames.filter(value => value.clipId === rawName)) {
      const captured = trace.find(value => value.method === 'captureAnimationPose' && value.context.advancing && value.context.time === frame.time);
      if (!captured) continue;
      for (const input of frame.inputs) {
        const owned = captured.context.animatedProperties[input.node], childOwned = captured.context.animatedProperties[input.child];
        assert(owned && owned.quaternion, 'The actual source Dyna quaternion track owns this frame');
        assert(childOwned && childOwned.position, 'The actual source end-child position track owns this frame');
        const q = captured.pose[input.node].quaternion, expected = [q[0], -q[1], -q[2], q[3]].map(Math.fround);
        input.rotation.forEach((value, axis) => assert(Math.abs(value - expected[axis]) < 1e-7, 'Original native job input retains the newly keyed Dyna rotation'));
        input.childPosition.forEach((value, axis) => assert(Math.abs(value - captured.pose[input.child].position[axis]) < 1e-9, 'Native input refresh retains the keyed child position'));
        directlyAnimatedFrames++; changedDyna ||= Math.abs(q[2]) > .03;
      }
    }
    assert(directlyAnimatedFrames > 1 && changedDyna, 'Multiple actual source-keyed Dyna frames reach native input, including a nontrivial rotation');
    report.cases.push({name: 'serialized Dyna and child curves preserve their actual animated properties at the native job boundary', frames: directlyAnimatedFrames});
    report.cases.push({ name: 'raw motion receives capture-before-positive-delta without authoring resets', trace });
    async function sampleCadence() { return page.evaluate(() => {
      const seek = document.getElementById('viewer-time'); seek.value = '0'; seek.dispatchEvent(new Event('input', {bubbles: true}));
      window.__physicsEvents = [];
      // These synchronous calls use the actual Rig and controller. A browser
      // RAF cannot interleave, so display input and the selected game boundary
      // can be checked separately without changing the actual native engine.
      document.getElementById('viewer-play').click();
      const times = [], beforeSteps = window.__lifecycleRig.getState().physics.solver.totalNativeSteps;
      for (let i = 0; i < 4; i++) { window.__lifecycleRig.update(1 / 120); times.push(window.__lifecycleRig.getState().time); }
      window.__lifecycleRig.update(.1);
      document.getElementById('viewer-play').click();
      return {times, events: window.__physicsEvents.slice(), finalTime: window.__lifecycleRig.getState().time,
        nativeStepCount: window.__lifecycleRig.getState().physics.solver.totalNativeSteps - beforeSteps};
    }); }
    const displayCadence = await sampleCadence();
    displayCadence.times.forEach((time, index) => assert(Math.abs(time - (index + 1) / 120) < 1e-7,
      'The default display setting samples animation on each display frame'));
    assert.equal(displayCadence.events.filter(value => value.method === 'apply' && value.delta > 0).length, 5);
    assert.equal(displayCadence.nativeStepCount, 5, 'Each120Hz tick and one long tick advance the original job exactly once');
    assert(Math.abs(displayCadence.finalTime - (1 / 30 + .1)) < 1e-7);
    report.cases.push({name: 'default display cadence accepts each120Hz tick without catch-up substeps', cadence: displayCadence});
    await (await show(page.locator('#viewer-physics-frame-rate'))).selectOption('30');
    const cadence = await sampleCadence();
    assert.deepStrictEqual(cadence.times.slice(0, 3), [0, 0, 0], 'Sub-frame display ticks skip both kinematic sampling and native simulation');
    assert(Math.abs(cadence.times[3] - 1 / 30) < 1e-7, 'The accepted frame samples animation at the same accumulated game clock');
    assert.equal(cadence.events.filter(value => value.method === 'apply' && value.delta > 0).length, 2, 'A long accepted frame runs one original update, without catch-up substeps');
    assert.equal(cadence.nativeStepCount, 2, 'Both accepted frames actually run the native job, rather than only invoking an unavailable adapter');
    assert(Math.abs(cadence.finalTime - (1 / 30 + .1)) < 1e-7);
    report.cases.push({name: '120Hz display input samples a 30Hz game clock and performs one update per accepted frame', cadence});
    // Real part visibility changes evaluate the paused pose, without changing
    // its authored matrices or the simulation history.
    const frozen = await page.evaluate(() => ModelViewer.getState().rig.bones.map(value => [value.node, value.quaternion]));
    await clear(page); const part = page.locator('#viewer-parts input[type=checkbox]').first(); await (await show(part)).click(); await part.click();
    trace = await events(page); assert(trace.some(value => value.method === 'apply' && value.delta === 0)); assert(!trace.some(value => value.method === 'resetSimulation'));
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().rig.bones.map(value => [value.node, value.quaternion])), frozen, 'Repeated paused redraws preserve the cached physical pose');
    report.cases.push({ name: 'paused UI redraws do not propagate or reset physics', trace });
    await clear(page); await seek(page, .75); trace = await events(page);
    assert.deepStrictEqual(trace.filter(value => value.method === 'resetSimulation').map(value => value.reason), ['rig:seek']);
    assert(trace.some(value => value.method === 'captureAnimationPose' && value.context.time === .75 && !value.context.advancing));
    assert(trace.filter(value => value.method === 'apply').every(value => value.delta === 0));
    report.cases.push({ name: 'seek queues an explicit reset followed by zero-time final-pose capture', trace });
    assert.deepStrictEqual(await page.evaluate(() => window.__getPhysicsInitializationPose()), initializationPose, 'Seeking into motion never replaces authored initialization with the animated frame');
    assert(await page.evaluate(initial => ModelViewer.getState().rig.bones.some(bone => initial[bone.node] &&
      ['position', 'quaternion', 'scale'].some(field => bone[field].some((value, axis) => Math.abs(value - initial[bone.node][field][axis]) > 1e-5))), initializationPose), 'The seeked visible pose really differs from its separately preserved source initialization');
    await page.evaluate(() => {
      const before = ModelViewer.getState().rig.bones, copy = window.__getPhysicsInitializationPose();
      Object.values(copy)[0].position[0] += 1000;
      if (JSON.stringify(before) !== JSON.stringify(ModelViewer.getState().rig.bones)) throw new Error('Reading or mutating a detached initialization pose moved the visible model');
    });
    assert.deepStrictEqual(await page.evaluate(() => window.__getPhysicsInitializationPose()), initializationPose, 'Initialization results are detached from the stored source transforms');
    report.cases.push({ name: 'lazy initialization reads immutable authored rest TRS while an actual different animated pose is displayed' });
    const target = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(value => value.name === 'BreastSize'));
    assert(target, 'Actual source provides a writable physical-chain ancestor');
    await (await show(page.locator('#viewer-node-filter'))).selectOption('all'); await (await show(page.locator('#viewer-node'))).selectOption(String(target.node));
    const input = page.locator('input[data-viewer-node-kind=scale][data-axis=X]'), current = Number(await input.inputValue());
    await clear(page); await (await show(input)).fill(String(current + .125)); await input.dispatchEvent('change'); trace = await events(page);
    assert.equal(authoringResets(trace).length, 1, 'A changed physical-chain authoring baseline queues one reset');
    const editedInitialization = await page.evaluate(() => window.__getPhysicsInitializationPose());
    assert.equal(editedInitialization[target.node].scale[0], current + .125, 'Explicit authoring scale updates the detached initialization source');
    await clear(page); await input.fill(String(current + .125)); await input.dispatchEvent('change'); assert.equal(authoringResets(await events(page)).length, 0, 'Repeating an equal authoring input preserves history');
    await clear(page); const drag = await show(page.locator('[data-physics-field=dragForce]')); await drag.fill('.4'); trace = await events(page);
    assert.equal(authoringResets(trace).length, 1, 'A changed native parameter queues an explicit reset');
    const physicsEdits = await page.evaluate(() => ModelViewer.getAuthoringState().physics);
    await seek(page, .4); assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().physics), physicsEdits, 'Seeking never invokes edit-clearing reset');
    report.cases.push({ name: 'actual authoring/parameter changes reset once, no-op input and seeks preserve user edits', physicsEdits });
    const descriptor = { version: 2, category: 'mv', physics: {profile: 'live', liveId: 12007, safeSwingBoneKnown: true, safeSwingBone: true}, motion: 'lifecycle-composite', label: 'Lifecycle composite', performerPosition: 1,
      clipSources: [{ sourceHash: clip.sourceHash, sourceName: clip.sourceName }], bodySegments: [{ sourceHash: clip.sourceHash, sourceName: clip.sourceName, start: 0, duration: clip.duration, clipIn: 0, timeScale: 1 }], facialClips: [], facial: { duration: clip.duration, events: [] } };
    const composite = await page.evaluate(descriptor => ModelViewer.setMotionTimeline(descriptor), descriptor);
    const unknownCostume = await page.evaluate(() => ModelViewer.getState().rig.physics.solver);
    assert(unknownCostume.unsupported.some(value => value.startsWith('source-skirt-runtime:')), 'A generated costume without a verified game import receipt cannot silently claim the MV runtime flag');
    await (await show(page.locator('#viewer-physics-skirt-correction'))).selectOption('disabled');
    const beforeGroupSteps = await page.evaluate(() => ModelViewer.getState().rig.physics.solver.totalNativeSteps);
    await clear(page); await page.locator('#viewer-play').click(); await page.waitForFunction(() => ModelViewer.getMotionState().rig.time > .2); await page.locator('#viewer-play').click();
    trace = await events(page); assert(trace.some(value => value.method === 'captureAnimationPose' && value.context.advancing && value.context.clipId === composite.clipName));
    assert(trace.some(value => value.method === 'captureAnimationPose' && value.context.motionCategory === 'mv' && value.context.safeSwingBone === true), 'Composite scene flags reach the production controller alongside the animation clock');
    assert(trace.filter(value => value.method === 'apply' && value.delta > 0).length > 1, 'Actionless imported composite supplies the same advancing physics clock'); assert(!authoringResets(trace).length);
    const groupSolver = await page.evaluate(() => ModelViewer.getState().rig.physics.solver);
    assert(groupSolver.initialized && groupSolver.available && groupSolver.totalNativeSteps > beforeGroupSteps, 'After an explicit costume setting, the group job really advances: ' + JSON.stringify(groupSolver));
    assert.deepStrictEqual(groupSolver.unsupported, []);
    assert.equal(groupSolver.runtimeProfile.job, 'SwingBoneGroupJob');
    let groupOwnedFrames = 0;
    for (const frame of (await page.evaluate(() => window.__nativeInputFrames.slice())).filter(value => value.clipId === composite.clipName)) {
      const captured = trace.find(value => value.method === 'captureAnimationPose' && value.context.advancing && value.context.time === frame.time);
      if (!captured) continue;
      for (const input of frame.inputs) {
        assert(captured.context.animatedProperties[input.node].quaternion && captured.context.animatedProperties[input.child].position, 'Only the active composite segment supplies ownership');
        const q = captured.pose[input.node].quaternion, expected = [q[0], -q[1], -q[2], q[3]].map(Math.fround);
        input.rotation.forEach((value, axis) => assert(Math.abs(value - expected[axis]) < 1e-7, 'The actual group job consumes the newly keyed composite Dyna rotation'));
        groupOwnedFrames++;
      }
    }
    assert(groupOwnedFrames > 1, 'Multiple composite Dyna inputs really reach the original group job');
    report.cases.push({ name: 'actionless game composite advances the native physics cadence', trace });
    await (await show(page.locator('#viewer-physics-quality'))).selectOption('10');
    await (await show(page.locator('#viewer-physics-frame-rate'))).selectOption('30');
    await (await show(page.locator('#viewer-physics-motion-correction'))).selectOption('disabled');
    await (await show(page.locator('#viewer-physics-colliders'))).check();
    await (await show(page.locator('#viewer-physics-show-colliders'))).check();
    await (await show(page.locator('#viewer-motion'))).selectOption('');
    const previewKeys = ['mode', 'frameRate', 'profile', 'qualityMode', 'skirtCorrection', 'motionCorrection', 'swingBone', 'swingCollider', 'showColliders'];
    const beforeReload = await page.evaluate(keys => Object.fromEntries(keys.map(key => [key, ModelViewer.getState().rig.physics[key]])), previewKeys);
    const beforeReloadId = await page.evaluate(() => ModelViewer.getState().modelId);
    await page.evaluate(bank => ModelViewer.addMotion([bank]), rawBank);
    assert.notEqual(await page.evaluate(() => ModelViewer.getState().modelId), beforeReloadId, 'Adding a real serialized bank replaces the prepared model/controller');
    assert.deepStrictEqual(await page.evaluate(keys => Object.fromEntries(keys.map(key => [key, ModelViewer.getState().rig.physics[key]])), previewKeys), beforeReload, 'A real supplementary-motion reload preserves all physics preview controls');
    assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getAuthoringState().physics), physicsEdits, 'Reloading motion also preserves editable native parameter values');
    await page.evaluate(bank => ModelViewer.addMotion([bank], {replaceGame: true}), gameBank);
    assert.deepStrictEqual(await page.evaluate(keys => Object.fromEntries(keys.map(key => [key, ModelViewer.getState().rig.physics[key]])), previewKeys), beforeReload, 'The same retained preview settings survive the game-motion replacement path');
    const reloadedClip = prepared.rig.clips.find(value => value.sourceName === 'Reload game motion');
    assert(reloadedClip, 'The actual added Unity bank produced new source metadata');
    await page.evaluate(descriptor => ModelViewer.setMotionTimeline(descriptor), { ...descriptor, motion: 'reload-composite',
      clipSources: [{sourceHash: reloadedClip.sourceHash, sourceName: reloadedClip.sourceName}],
      bodySegments: [{sourceHash: reloadedClip.sourceHash, sourceName: reloadedClip.sourceName, start: 0, duration: reloadedClip.duration, clipIn: 0, timeScale: 1}] });
    assert.equal(await page.evaluate(() => ModelViewer.getState().rig.physics.runtime.profile), 'live', 'Auto profile follows the newly selected MV after the retained reload');
    const retainedSteps = await page.evaluate(() => ModelViewer.getState().rig.physics.solver.totalNativeSteps);
    await page.locator('#viewer-play').click();
    await page.waitForFunction(previous => ModelViewer.getState().rig.physics.solver.totalNativeSteps > previous + 2, retainedSteps);
    await page.locator('#viewer-play').click();
    const retainedSolver = await page.evaluate(() => ModelViewer.getState().rig.physics.solver);
    assert(retainedSolver.available && retainedSolver.initialized);
    assert.deepStrictEqual(retainedSolver.unsupported, []);
    assert.equal(retainedSolver.runtimeProfile.job, 'SwingBoneGroupJob');
    report.cases.push({name: 'real manual and game motion reloads retain native flags, mode, quality and FPS while the new auto scene profile updates', preview: beforeReload, nativeSteps: retainedSolver.totalNativeSteps});
    assert.deepStrictEqual(errors, []); await page.screenshot({ path: path.join(evidence, 'lifecycle-controls.png') }); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
if (require.main === module) run();
